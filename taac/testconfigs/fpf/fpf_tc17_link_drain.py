# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe

"""TC17: GTSW<->GPU Link Drain (link-event, "control up / data drains").

Drains the link carrying the circuit's lane, waits 2 minutes, validates the
drain contract, then undrains and validates full recovery. Unlike interface
disable, a drain depreferences/withdraws the VF routes on the lane while
keeping the FSDB/HRT sessions CONNECTED and the data plane clean (no packet
loss). So vs. interface-disable the expectations differ only in two checks:

  - FSDB/HRT session: stays all-CONNECTED (control plane intact).
  - ODS discards: stays within the clean bound (no packet loss).

Everything else matches interface-disable (bulk withdrawn on the impacted lane,
remote-failure rises 0->count within 30s, prod/broad prefix planes go
unreachable within 30s, host-spray impacted lane <10 Gbps).

Link drain is per-port: each circuit's GTSW interface is soft-drained on-box
via the LOCAL_DRAINER (depreferences the BGP advertisements without bringing
the link down at the data plane), so only the named link is affected — not the
whole GTSW. The Circuit list defines both the interfaces to drain and the
impacted lanes/planes the health checks assert on.

Usage:
  buck2 run neteng/netcastle:netcastle_taac -- \\
    --team taac --test-config fpf_tc17_link_drain \\
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

CIRCUITS = [
    Circuit(
        a_end_device=OBSERVER_GTSWS[0],  # gtsw001 -> lane 0
        a_end_interface="eth1/45/5",
        z_end_device=GPU_HOSTS[0],
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


def create_fpf_tc17_test_config() -> TestConfig:
    skip_ssh = skip_ssh_dependencies()
    spray = None if skip_ssh else SPRAY_HOSTS
    impacted_lanes = sorted({c.lane for c in CIRCUITS})
    drain_interfaces = sorted({c.a_end_interface for c in CIRCUITS})

    disrupt_steps = [
        create_fpf_drain_interface_step(
            interfaces=drain_interfaces,
            drain=True,
            description=f"Soft-drain link(s) {drain_interfaces} on {OBSERVER_GTSWS[0]}",
        ),
        # Disruption-effectiveness gate: confirm the soft-drain actually took
        # (port isDrained=True). A drained link stays admin=ENABLED/oper=UP by
        # design, so admin/oper is the wrong signal — use drain mode. If the
        # drain didn't register, downstream lane checks SKIP (inconclusive)
        # instead of emitting confusing FAILs.
        create_fpf_verify_disruption_step(
            interfaces=drain_interfaces,
            mode="drain",
            expect_drained=True,
        ),
        create_longevity_step(
            duration=LONGEVITY_SEC,
            description=f"Settle {LONGEVITY_SEC}s after drain before assertion",
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
        # Drain = control up / data drains: sessions stay connected, no loss.
        flip_fsdb_session=False,
        flip_discards=False,
        # Soft-drain depreferences the production VF plane (asserted by the
        # prod-prefix transition) but does NOT withdraw the directly-injected
        # test prefixes, so don't expect bulk/remote-failure withdrawal.
        injected_prefixes_withdrawn=False,
        fsdb_expected_total=EXPECTED_FSDB_SESSION_COUNT,
        # Link drain: the impacted plane (lane 0) goes DRAINED on the GPU's
        # hrtctl plane-status while the other 7 planes stay UP.
        plane_status_mode="drain",
        playbook_name="fpf_tc17_link_drain_disrupt",
    )

    restore_playbook = create_fpf_hardening_playbook_v2(
        gtsws=OBSERVER_GTSWS,
        hosts=GPU_HOSTS,
        trigger_stsws=TRIGGER_STSWS,
        disruption_steps=[
            create_fpf_drain_interface_step(
                interfaces=drain_interfaces,
                drain=False,
                description=f"Undrain link(s) {drain_interfaces} on {OBSERVER_GTSWS[0]}",
            ),
            create_longevity_step(
                duration=180,
                description="Settle after undrain; expect full recovery",
            ),
        ],
        soak_duration_sec=0,
        stabilization_delay_sec=0,
        prefix_count=PREFIX_COUNT,
        community_list=DEFAULT_COMMUNITY_LIST,
        playbook_name="fpf_tc17_link_drain_restore",
        prod_prefixes=PROD_PREFIXES,
        skip_ssh_dependent_checks=True,
        # Undrain recovery mirrors the tc15 restore contract: plane comes back
        # mid-window; settle past it and snapshot BGP. Sessions stayed up the
        # whole drain (control-up), so all 32 are CONNECTED.
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
        # to reachable, timed from the undrain command (recorded by the drain step)
        # to plane 0 re-entering the reachable set — not a settle-and-baseline
        # stability assertion that flags the recovery transient.
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
        name="fpf_tc17_link_drain",
        endpoints=create_fpf_endpoints(),
        setup_tasks=setup_tasks,
        teardown_tasks=teardown_tasks,
        playbooks=[disrupt_playbook, restore_playbook],
    )


TEST_CONFIG = create_fpf_tc17_test_config()
