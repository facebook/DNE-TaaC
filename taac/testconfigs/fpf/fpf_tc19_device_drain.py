# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

"""TC19: GTSW Device Drain (link-event, "control up / data drains").

Soft-drains the ENTIRE DUT GTSW via the on-box LOCAL_DRAINER (not a single
port), waits 2 minutes, validates the drain contract, then undrains the whole
device and validates full recovery. A device soft-drain depreferences the
GTSW's BGP advertisements for its plane while keeping the FSDB/HRT sessions
CONNECTED and the data plane clean — exactly the same observable contract as a
link drain (TC17), the only difference being the drain SCOPE (whole device vs a
single port). Because the only circuit we monitor on the DUT GTSW is
``rtptest1555`` GPU0 lane 0, the OBSERVED impact is identical to TC17:

  - FSDB/HRT session: stays all-CONNECTED (control plane intact).
  - ODS discards: stays within the clean bound (no packet loss).
  - HRT bulk: impacted lane withdrawn; remote-failure rises 0->count within SLA;
    prod/broad prefix plane goes unreachable within SLA — all on the impacted
    host only.

Device drain/undrain use the device-level LOCAL_DRAINER (``create_drain_undrain_
step`` with NO ``interfaces`` arg drains the whole DUT).

SSH-dependent pieces (ib_write_bw traffic task, host-spray check, generic
device-shell checks) are gated off via ``skip_ssh_dependencies()`` so the config
runs headless on the Thrift/ODS signal path.

Usage:
  TAAC_FPF_SKIP_SSH_DEPS=1 buck2 run neteng/netcastle:netcastle_taac -- \\
    --team taac --test-config fpf_tc19_device_drain \\
    --dev --skip-basset-reservation --skip-testbed-isolation \\
    --debug --continue-on-precheck-failure --skip-fboss-rsyslog
"""

from taac.libs.fpf.fpf_prod_prefix_map import get_prefix
from taac.playbooks.playbook_definitions import (
    create_fpf_hardening_playbook_v2,
    create_fpf_link_event_disrupt_playbook,
)
from taac.steps.step_definitions import (
    create_fpf_drain_interface_step,
    create_fpf_verify_disruption_step,
    create_longevity_step,
)
from taac.task_definitions import (
    create_fpf_start_collectors_task,
    create_fpf_start_ib_traffic_task,
    create_fpf_stop_collectors_task,
    create_fpf_stop_ib_traffic_task,
)
from taac.testconfigs.fpf.fpf_hardening_common import (
    ALLOW_BASELINE_FAILURES,
    Circuit,
    create_fpf_endpoints,
    DEFAULT_COMMUNITY_LIST,
    DEFAULT_SUBNET_PREFIX,
    EXPECTED_FSDB_SESSION_COUNT,
    FSDB_COLLECTOR_MODE,
    GPU_HOSTS,
    impacted_lanes_by_host_gpu,
    OBSERVER_GTSWS,
    skip_ssh_dependencies,
    TRIGGER_STSWS,
)
from taac.test_as_a_config.types import TestConfig

PREFIX_COUNT = 1000
STABILIZATION_DELAY_SEC = 300
LONGEVITY_SEC = 120
INJECTED_LANES = [0, 1]

# The drained DEVICE is the DUT GTSW. The circuit below is what we MONITOR on it
# (rtptest1555 GPU0 lane 0); draining the whole GTSW depreferences this plane, so
# the observed impact matches a link drain of this circuit.
DRAIN_TARGET_GTSW = OBSERVER_GTSWS[0]
CIRCUITS = [
    Circuit(
        a_end_device=OBSERVER_GTSWS[0],  # gtsw001.l1002 -> lane 0
        a_end_interface="eth1/45/5",
        z_end_device=GPU_HOSTS[0],  # rtptest1555.mwg2, GPU0 beth0
        z_end_gpu_id=0,
    ),
]

PROD_PREFIX_HOST = GPU_HOSTS[0]
PROD_PREFIX_DEVICE_ID = 0
PROD_PREFIXES = [get_prefix(PROD_PREFIX_HOST, PROD_PREFIX_DEVICE_ID)]
HRT_MEMORY_HOSTS = ["rtptest1555.mwg2", "rtptest1575.mwg2"]
IB_TRAFFIC_SERVER = GPU_HOSTS[0]
IB_TRAFFIC_CLIENTS = [GPU_HOSTS[1]]
SPRAY_HOSTS = [IB_TRAFFIC_SERVER, *IB_TRAFFIC_CLIENTS]


def _impacted_beths_by_host(circuits: list[Circuit]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for c in circuits:
        out.setdefault(c.z_end_device, [])
        if c.nic_interface not in out[c.z_end_device]:
            out[c.z_end_device].append(c.nic_interface)
    return {h: sorted(v) for h, v in sorted(out.items())}


def _impacted_planes_by_host(circuits: list[Circuit]) -> dict[str, list[int]]:
    out: dict[str, list[int]] = {}
    for c in circuits:
        out.setdefault(c.z_end_device, [])
        if c.lane not in out[c.z_end_device]:
            out[c.z_end_device].append(c.lane)
    return {h: sorted(v) for h, v in sorted(out.items())}


def create_fpf_tc19_test_config() -> TestConfig:
    skip_ssh = skip_ssh_dependencies()
    spray = None if skip_ssh else SPRAY_HOSTS
    impacted_lanes = sorted({c.lane for c in CIRCUITS})

    disrupt_steps = [
        # DEVICE-level soft-drain (control-up): no `interfaces` -> the whole DUT
        # GTSW is soft-drained via async_onbox_softdrain_device.
        create_fpf_drain_interface_step(
            interfaces=[],
            drain=True,
            description=f"Soft-drain DEVICE {DRAIN_TARGET_GTSW} via local drainer",
        ),
        # DEVICE-drain effectiveness gate (mode="device_drain"): query the on-box
        # local drainer's DEVICE-level is_drained() — the authoritative "the box
        # transitioned to drained" signal. A device soft-drain does NOT set the
        # per-port isDrained flag, so the per-port "drain" gate is the wrong check
        # here; this device-level check is. fail_if_ineffective=True aborts if the
        # box never drained (the test would be invalid). Only once this confirms
        # drained do the downstream prod/broad-prefix transition checks run — the
        # prefix transition is a corroborating downstream signal, not the primary
        # effectiveness proof.
        create_fpf_verify_disruption_step(
            interfaces=[],
            mode="device_drain",
            expect_drained=True,
            fail_if_ineffective=True,
            description=f"Gate: confirm DEVICE {DRAIN_TARGET_GTSW} is_drained()=True",
        ),
        create_longevity_step(
            duration=LONGEVITY_SEC,
            description=f"Settle {LONGEVITY_SEC}s after device drain before assertion",
        ),
    ]

    disrupt_playbook = create_fpf_link_event_disrupt_playbook(
        gtsws=OBSERVER_GTSWS,
        hosts=GPU_HOSTS,
        trigger_stsws=TRIGGER_STSWS,
        disruption_steps=disrupt_steps,
        prefix_count=PREFIX_COUNT,
        community_list=DEFAULT_COMMUNITY_LIST,
        stabilization_delay_sec=STABILIZATION_DELAY_SEC,
        injected_lanes=INJECTED_LANES,
        impacted_lanes=impacted_lanes,
        impacted_lanes_by_host_gpu=impacted_lanes_by_host_gpu(CIRCUITS),
        impacted_beths_by_host=_impacted_beths_by_host(CIRCUITS),
        impacted_planes_by_host=_impacted_planes_by_host(CIRCUITS),
        prod_prefixes=PROD_PREFIXES,
        hrt_memory_hosts=HRT_MEMORY_HOSTS,
        hrt_driver_hosts=HRT_MEMORY_HOSTS,
        spray_hosts=spray,
        # Device drain = control up / data drains: sessions stay connected, no loss.
        flip_fsdb_session=False,
        flip_discards=False,
        # Soft-drain depreferences the production VF plane (asserted by the
        # prod-prefix transition) but does NOT withdraw the directly-injected
        # test prefixes, so don't expect bulk/remote-failure withdrawal.
        injected_prefixes_withdrawn=False,
        fsdb_expected_total=EXPECTED_FSDB_SESSION_COUNT,
        # Device drain: the impacted plane (lane 0) goes DRAINED on the GPU's
        # hrtctl plane-status while the other 7 planes stay UP.
        plane_status_mode="drain",
        playbook_name="fpf_tc19_device_drain_disrupt",
    )

    # Recovery: undrain the whole device, validate stable state.
    restore_playbook = create_fpf_hardening_playbook_v2(
        gtsws=OBSERVER_GTSWS,
        hosts=GPU_HOSTS,
        trigger_stsws=TRIGGER_STSWS,
        disruption_steps=[
            create_fpf_drain_interface_step(
                interfaces=[],
                drain=False,
                description=f"Undrain DEVICE {DRAIN_TARGET_GTSW} via local drainer",
            ),
            create_longevity_step(
                duration=180,
                description="Settle after device undrain; expect full recovery",
            ),
        ],
        soak_duration_sec=0,
        stabilization_delay_sec=0,
        prefix_count=PREFIX_COUNT,
        community_list=DEFAULT_COMMUNITY_LIST,
        playbook_name="fpf_tc19_device_drain_restore",
        prod_prefixes=PROD_PREFIXES,
        skip_ssh_dependent_checks=True,
        use_bgp_snapshot=True,
        prod_prefix_settle_sec=120,
        convergence_settle_sec=120,
        fsdb_expected_total=EXPECTED_FSDB_SESSION_COUNT,
        skip_fsdb_session_precheck=True,
        hrt_memory_hosts=HRT_MEMORY_HOSTS,
        hrt_driver_hosts=HRT_MEMORY_HOSTS,
        spray_hosts=spray,
        # After undrain, every plane must return to UP (hrtctl plane-status).
        plane_status_check=True,
        # Recovery-anchored prod-prefix check: measure the restored lane returning
        # to reachable, timed from the device-undrain command to plane 0 re-entering
        # the reachable set — not a settle-and-baseline stability assertion.
        prod_prefix_recovery=True,
        local_prod_prefixes=PROD_PREFIXES,
        impacted_planes_by_host=_impacted_planes_by_host(CIRCUITS),
    )

    setup_tasks = []
    teardown_tasks = []
    if not skip_ssh:
        setup_tasks.append(
            create_fpf_start_ib_traffic_task(
                server=IB_TRAFFIC_SERVER, clients=IB_TRAFFIC_CLIENTS
            )
        )
        teardown_tasks.append(
            create_fpf_stop_ib_traffic_task(
                server=IB_TRAFFIC_SERVER, clients=IB_TRAFFIC_CLIENTS
            )
        )
    setup_tasks.append(
        create_fpf_start_collectors_task(
            gtsws=OBSERVER_GTSWS,
            hosts=GPU_HOSTS,
            subnet_prefix=DEFAULT_SUBNET_PREFIX,
            prod_prefixes=PROD_PREFIXES,
            prod_prefix_host=PROD_PREFIX_HOST,
            prod_prefix_device_id=PROD_PREFIX_DEVICE_ID,
            fsdb_mode=FSDB_COLLECTOR_MODE,
            allow_baseline_failures=ALLOW_BASELINE_FAILURES,
        )
    )
    teardown_tasks.append(
        create_fpf_stop_collectors_task(
            trigger_stsws=TRIGGER_STSWS,
            prefix_count=PREFIX_COUNT,
            community_list=DEFAULT_COMMUNITY_LIST,
        )
    )

    return TestConfig(
        name="fpf_tc19_device_drain",
        endpoints=create_fpf_endpoints(),
        setup_tasks=setup_tasks,
        teardown_tasks=teardown_tasks,
        playbooks=[disrupt_playbook, restore_playbook],
    )


TEST_CONFIG = create_fpf_tc19_test_config()
