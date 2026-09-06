# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

"""TC19: GTSW Device Drain (link-event, "control up / data drains").

Soft-drains the ENTIRE DUT GTSW via the on-box LOCAL_DRAINER (not a single
port), waits 2 minutes, validates the drain contract, then undrains the whole
device and validates full recovery. A device soft-drain depreferences the
GTSW's BGP advertisements for its plane while keeping the FSDB/HRT sessions
CONNECTED and the data plane clean — exactly the same observable contract as a
link drain (TC17), the only difference being the drain SCOPE (whole device vs a
single port). The target GTSW is selected by
``TAAC_FPF_DEVICE_DRAIN_GTSW`` (legacy default gtsw001) and its global lane is
translated to each monitored GPU/device-local-plane tuple.

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
    create_fpf_conditional_undrain_step,
    create_fpf_drain_interface_step,
    create_fpf_verify_disruption_step,
    create_longevity_step,
)
from taac.task_definitions import (
    create_fpf_inject_vf_groups_task,
    create_fpf_restart_service_task,
    create_fpf_start_collectors_task,
    create_fpf_start_ib_traffic_task,
    create_fpf_stop_collectors_task,
    create_fpf_stop_ib_traffic_task,
    create_fpf_withdraw_vf_groups_task,
)
from taac.testconfigs.fpf.fpf_hardening_common import (
    ALL_STSWS,
    ALLOW_BASELINE_FAILURES,
    Circuit,
    create_fpf_endpoints,
    DEFAULT_COMMUNITY_LIST,
    EXPECTED_FSDB_SESSION_COUNT,
    fpf_device_drain_gtsw,
    fpf_hrt_device_ids,
    fpf_hrt_lanes,
    fpf_hrt_vf_device_ids,
    fpf_rf_vf_groups,
    fpf_vf_injection_groups,
    FSDB_COLLECTOR_MODE,
    GPU_HOSTS,
    HRT_MEMORY_HOSTS,
    impacted_lanes_by_host_gpu,
    OBSERVER_GTSWS,
    skip_ssh_dependencies,
    VF_COLLECTOR_SUBNET,
    VF_GROUP_PREFIX_COUNT,
)
from taac.test_as_a_config.types import TestConfig

# Prefixes injected on ALL 8 STSWs, split per VF group (VF1 5000:dd on s001-s004,
# VF2 5000:ee on s005-s008), via the fpf_inject_bgp_prefixes SETUP TASK — this
# netcastle run is fully self-contained (no external script). The fabric is
# VF-segregated (VF1 only on lanes 0-3, VF2 only on lanes 4-7), so each observer
# GTSW / lane sees only its own VF group's count: PREFIX_COUNT =
# VF_GROUP_PREFIX_COUNT. Collector subnet is 5000::/16 to count both groups.
INJECTION_GROUPS = fpf_vf_injection_groups()
TRIGGER_STSWS = ALL_STSWS
PREFIX_COUNT = VF_GROUP_PREFIX_COUNT
INJECT_SETTLE_SEC = 300
STABILIZATION_DELAY_SEC = 300
LONGEVITY_SEC = 120
INJECTED_LANES = fpf_hrt_lanes()
HRT_DEVICE_IDS = fpf_hrt_device_ids()
HRT_VF_DEVICE_IDS = fpf_hrt_vf_device_ids(HRT_DEVICE_IDS)
RF_VF_GROUPS = fpf_rf_vf_groups(
    active_lanes=INJECTED_LANES,
    device_ids_by_vf=(HRT_VF_DEVICE_IDS if HRT_DEVICE_IDS != [0] else None),
)

# The drained DEVICE is selected independently from TC17's link target. Each
# circuit below represents one physical GPU's link to that GTSW; the existing
# global-lane -> paired-device/local-plane translation derives exact HRT tuples.
DRAIN_TARGET_GTSW = fpf_device_drain_gtsw()
DRAIN_OBSERVER_GTSWS = list(dict.fromkeys([DRAIN_TARGET_GTSW, OBSERVER_GTSWS[1]]))
CIRCUITS = [
    Circuit(
        a_end_device=DRAIN_TARGET_GTSW,
        a_end_interface="",
        z_end_device=GPU_HOSTS[0],
        z_end_gpu_id=gpu_id,
    )
    for gpu_id in (range(4) if HRT_DEVICE_IDS != [0] else range(1))
]

PROD_PREFIX_HOST = GPU_HOSTS[0]
PROD_PREFIX_DEVICE_ID = 0
PROD_PREFIXES = [get_prefix(PROD_PREFIX_HOST, PROD_PREFIX_DEVICE_ID)]
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
    mutation_token = "fpf_tc19_device_drain"
    cleanup_step = create_fpf_conditional_undrain_step(
        interfaces=[],
        target_device=DRAIN_TARGET_GTSW,
        mutation_token=mutation_token,
        best_effort=True,
        description=(f"Best-effort owned cleanup: restore DEVICE {DRAIN_TARGET_GTSW}"),
    )

    disrupt_steps = [
        create_fpf_verify_disruption_step(
            interfaces=[],
            mode="device_clean",
            expect_drained=False,
            fail_if_ineffective=True,
            target_device=DRAIN_TARGET_GTSW,
            description=(
                f"Precondition: verify {DRAIN_TARGET_GTSW} device and all ports "
                "are undrained"
            ),
        ),
        # DEVICE-level soft-drain (control-up): no `interfaces` -> the whole DUT
        # GTSW is soft-drained via async_onbox_softdrain_device.
        create_fpf_drain_interface_step(
            interfaces=[],
            drain=True,
            target_device=DRAIN_TARGET_GTSW,
            mutation_token=mutation_token,
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
            target_device=DRAIN_TARGET_GTSW,
            description=f"Gate: confirm DEVICE {DRAIN_TARGET_GTSW} is_drained()=True",
        ),
        create_longevity_step(
            duration=LONGEVITY_SEC,
            description=f"Settle {LONGEVITY_SEC}s after device drain before assertion",
        ),
    ]

    disrupt_playbook = create_fpf_link_event_disrupt_playbook(
        gtsws=DRAIN_OBSERVER_GTSWS,
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
        # Prefixes injected once by the setup task (8-STSW split-per-VF).
        skip_injection=True,
        rf_vf_groups=RF_VF_GROUPS,
        hrt_device_ids=HRT_DEVICE_IDS,
        # Skip the drain-moment transient (a single-poll BGP-thrift read of 0 on
        # the drained GTSW; FSDB stays converged) when judging GTSW-side stability.
        gtsw_convergence_settle_sec=30,
        playbook_name="fpf_tc19_device_drain_disrupt",
    )

    # Recovery: undrain the whole device, validate stable state.
    restore_playbook = create_fpf_hardening_playbook_v2(
        gtsws=DRAIN_OBSERVER_GTSWS,
        hosts=GPU_HOSTS,
        trigger_stsws=TRIGGER_STSWS,
        disruption_steps=[
            create_fpf_conditional_undrain_step(
                interfaces=[],
                target_device=DRAIN_TARGET_GTSW,
                mutation_token=mutation_token,
                description=(
                    f"Restore owned DEVICE drain on {DRAIN_TARGET_GTSW} if marked"
                ),
            ),
            create_fpf_verify_disruption_step(
                interfaces=[],
                mode="device_drain",
                expect_drained=False,
                fail_if_ineffective=True,
                target_device=DRAIN_TARGET_GTSW,
                description=(
                    f"Gate: confirm DEVICE {DRAIN_TARGET_GTSW} "
                    "is_drained()=False after restore"
                ),
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
        # Check all 8 injected lanes recovered (not just the default [0,1]).
        lanes=INJECTED_LANES,
        # Prefixes injected once by the setup task; do not re-inject on restore.
        skip_injection=True,
        rf_vf_groups=RF_VF_GROUPS,
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
        cleanup_steps=[cleanup_step],
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
            gtsws=DRAIN_OBSERVER_GTSWS,
            hosts=GPU_HOSTS,
            hrt_device_ids=HRT_DEVICE_IDS,
            hrt_plane_ids=INJECTED_LANES,
            subnet_prefix=VF_COLLECTOR_SUBNET,
            prod_prefixes=PROD_PREFIXES,
            prod_prefix_host=PROD_PREFIX_HOST,
            prod_prefix_device_id=PROD_PREFIX_DEVICE_ID,
            fsdb_mode=FSDB_COLLECTOR_MODE,
            allow_baseline_failures=ALLOW_BASELINE_FAILURES,
            rf_vf_groups=RF_VF_GROUPS,
        )
    )
    # Inject the two VF prefix groups on all 8 STSWs once (after collectors
    # start), persisting across both the disrupt and restore playbooks.
    setup_tasks.append(
        create_fpf_inject_vf_groups_task(
            groups=INJECTION_GROUPS,
            settle_sec=INJECT_SETTLE_SEC,
        )
    )
    teardown_tasks.append(create_fpf_withdraw_vf_groups_task(groups=INJECTION_GROUPS))
    # Robust catch-all: restart bgpd on all 8 STSWs to clear injected + any
    # leftover prefixes (reloads persistent config).
    teardown_tasks.append(
        create_fpf_restart_service_task(devices=ALL_STSWS, service="BGP")
    )
    teardown_tasks.append(
        # Stop collectors only (prefixes cleared above, not here).
        create_fpf_stop_collectors_task(
            trigger_stsws=TRIGGER_STSWS,
            withdraw=False,
            community_list=DEFAULT_COMMUNITY_LIST,
        )
    )

    return TestConfig(
        name="fpf_tc19_device_drain",
        endpoints=create_fpf_endpoints(stsws=ALL_STSWS),
        setup_tasks=setup_tasks,
        teardown_tasks=teardown_tasks,
        playbooks=[disrupt_playbook, restore_playbook],
    )


TEST_CONFIG = create_fpf_tc19_test_config()
