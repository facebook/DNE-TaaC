# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe

"""TC15: GTSW<->GPU Interface Disable (link-event).

Disables the GTSW interface(s) of one or more circuits, waits 2 minutes for the
connectors/HRT to settle, validates the *disrupted* contract, then immediately
re-enables the interface(s) and validates full stable-state recovery. The
re-enable playbook runs right after the disable playbook (hard requirement) to
avoid leaving the testbed in a disrupted state and to catch false signals.

Selection is driven entirely by a list of ``Circuit`` objects (single source of
truth). From it we derive: the interfaces to disable, the unique RTP hosts, the
impacted lanes per (host, gpu), the impacted beths for the spray check, and N
(used for the overall FSDB-session signal 32 - N).

Disrupted-phase expectations (interface disable):
  - HRT bulk: impacted lanes withdrawn (~0); other injected lanes converge.
  - HRT remote-failure: impacted lanes 0->prefix_count within 30s; rest stable.
  - Prod/broad prefix: impacted planes go reachable->unreachable within 30s on
    every host.
  - Host-spray: impacted beths <10 Gbps; floor+fairness on unimpacted lanes.
  - FSDB/HRT session: overall 32 - N CONNECTED + per-GPU0 lane reconciliation.
  - ODS discards: assert real packet loss (>= threshold).
  - BGP RIB + FSDB ribMap (GTSW-side): unchanged convergence.

Recovery playbook (interface enable): identical to stable-state postchecks.

Usage:
  buck2 run neteng/netcastle:netcastle_taac -- \\
    --team taac --test-config fpf_tc15_interface_disable \\
    --dev --skip-basset-reservation --skip-testbed-isolation \\
    --debug --continue-on-precheck-failure --skip-fboss-rsyslog
"""

from taac.libs.fpf.fpf_prod_prefix_map import get_prefix
from taac.playbooks.playbook_definitions import (
    create_fpf_hardening_playbook_v2,
    create_fpf_link_event_disrupt_playbook,
)
from taac.steps.step_definitions import (
    create_fpf_set_interface_admin_step,
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
    disable_interfaces_by_device,
    EXPECTED_FSDB_SESSION_COUNT,
    FSDB_COLLECTOR_MODE,
    GPU_HOSTS,
    impacted_lanes_by_host_gpu,
    num_disrupted_circuits,
    OBSERVER_GTSWS,
    skip_ssh_dependencies,
    TRIGGER_STSWS,
)
from taac.test_as_a_config.types import TestConfig

PREFIX_COUNT = 1000
STABILIZATION_DELAY_SEC = 300
LONGEVITY_SEC = 120  # 2-minute settle after disable (per requirement)
INJECTED_LANES = [0, 1]

# --- Circuit list: the single source of truth for what gets disabled. ---
# TODO(pavanpatil): migrate to a topology source-of-truth constants file.
CIRCUITS = [
    Circuit(
        a_end_device=OBSERVER_GTSWS[0],  # gtsw001.l1002 -> lane 0
        a_end_interface="eth1/45/5",
        z_end_device=GPU_HOSTS[0],  # rtptest1555.mwg2, GPU0 beth0
        z_end_gpu_id=0,
    ),
]

# Prod prefix monitored on the impacted host/dev (local VF1).
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


def _disable_steps(circuits: list[Circuit], enable: bool) -> list:
    """Thrift-based held disable/enable of the A-end interface(s) on the DUT.

    Uses the live-agent setPortState path (immediate + held) rather than the
    COOP config patcher (which only patches config and needs a reload/warmboot
    to actually shut the port). All A-end interfaces must be on the DUT GTSW.
    """
    steps = []
    for dev, intfs in disable_interfaces_by_device(circuits).items():
        steps.append(
            create_fpf_set_interface_admin_step(
                interfaces=intfs,
                enable=enable,
                description=(
                    f"{'Enable' if enable else 'Disable'} {intfs} on {dev} "
                    f"(thrift admin state)"
                ),
            )
        )
    return steps


def create_fpf_tc15_test_config() -> TestConfig:
    impacted_lanes = sorted({c.lane for c in CIRCUITS})
    n = num_disrupted_circuits(CIRCUITS)
    skip_ssh = skip_ssh_dependencies()
    spray = None if skip_ssh else SPRAY_HOSTS

    disrupt_interfaces = sorted(
        {i for intfs in disable_interfaces_by_device(CIRCUITS).values() for i in intfs}
    )
    disrupt_steps = [
        *_disable_steps(CIRCUITS, enable=False),
        create_longevity_step(
            duration=LONGEVITY_SEC,
            description=(
                f"Settle {LONGEVITY_SEC}s after disabling {n} circuit(s) "
                f"so connectors/HRT converge before assertion"
            ),
        ),
        # Disruption-effectiveness gate: confirm the link(s) actually went down
        # (admin DISABLED / oper DOWN) before asserting the disrupted contract.
        # fail_if_ineffective: abort the playbook if the disable was a no-op —
        # a disabled-but-still-up link makes the disrupted assertions invalid.
        create_fpf_verify_disruption_step(
            interfaces=disrupt_interfaces, fail_if_ineffective=True
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
        flip_fsdb_session=True,
        flip_discards=True,
        fsdb_expected_total=EXPECTED_FSDB_SESSION_COUNT,
        include_ssh_checks=not skip_ssh,
        playbook_name="fpf_tc15_interface_disable_disrupt",
    )

    # Recovery: re-enable interface(s) immediately, validate stable state.
    restore_playbook = create_fpf_hardening_playbook_v2(
        gtsws=OBSERVER_GTSWS,
        hosts=GPU_HOSTS,
        trigger_stsws=TRIGGER_STSWS,
        disruption_steps=[
            *_disable_steps(CIRCUITS, enable=True),
            create_longevity_step(
                duration=180,
                description="Settle after re-enable; expect full recovery",
            ),
        ],
        soak_duration_sec=0,
        stabilization_delay_sec=0,
        prefix_count=PREFIX_COUNT,
        community_list=DEFAULT_COMMUNITY_LIST,
        playbook_name="fpf_tc15_interface_disable_restore",
        prod_prefixes=PROD_PREFIXES,
        skip_ssh_dependent_checks=skip_ssh,
        # BGP: tally established sessions at precheck (no fail on baseline-down),
        # assert unchanged at postcheck — a GPU-link re-enable must not drop any
        # GTSW<->STSW BGP session. Mirrors the disrupt playbook's BGP snapshot.
        use_bgp_snapshot=True,
        # The re-enabled plane recovers mid-window; take the prod-prefix stability
        # baseline AFTER it settles (the 180s recovery longevity) so the recovery
        # itself isn't flagged as a regression. Leaves ~60s tail to assert the
        # recovered steady state stays stable. Same settle for the HRT bulk
        # convergence (impacted lane re-converge transient).
        prod_prefix_settle_sec=120,
        convergence_settle_sec=120,
        # Recovery-anchored prod-prefix check: measure the restored lane (plane 0)
        # returning to reachable, timed from the re-enable command moment (the
        # set_interface_admin step records it) to when plane 0 re-enters the
        # reachable set — instead of a settle-and-baseline stability assertion
        # that flags the recovery itself when it lands after the settle window.
        prod_prefix_recovery=True,
        local_prod_prefixes=PROD_PREFIXES,
        impacted_planes_by_host=_impacted_planes_by_host(CIRCUITS),
        # FSDB sessions: all 32 (4 GPUs x 8 GTSWs per BE node) should be up post
        # re-enable; the default len(observer_gtsws)*4 = 8 is wrong here. And
        # skip the session PRECHECK — a lingering graceful-restart hold from the
        # disrupt is informational, not a restore-precheck failure.
        fsdb_expected_total=EXPECTED_FSDB_SESSION_COUNT,
        skip_fsdb_session_precheck=True,
        hrt_memory_hosts=HRT_MEMORY_HOSTS,
        hrt_driver_hosts=HRT_MEMORY_HOSTS,
        spray_hosts=spray,
        # After re-enable, every plane must be UP on the GPU's hrtctl plane-status.
        # (The disrupt half is a port DISABLE — the plane goes DOWN, not DRAINED —
        # so no plane-status postcheck is added there.)
        plane_status_check=True,
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
        name="fpf_tc15_interface_disable",
        endpoints=create_fpf_endpoints(),
        setup_tasks=setup_tasks,
        teardown_tasks=teardown_tasks,
        playbooks=[disrupt_playbook, restore_playbook],
    )


TEST_CONFIG = create_fpf_tc15_test_config()
