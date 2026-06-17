# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe

"""TC37: NIC-Side Link Flap.

Same observable contract as the GTSW interface-disable test (TC15) EXCEPT the
admin down/up is applied on the NIC side (the rtptest GPU host), not on the
GTSW. The lane-0 GPU<->GTSW link is flapped from the host end, so HRT churns on
that lane while the GTSW port stays as configured.

DISRUPTION MECHANISM (real, headless TAAC step — no longer a placeholder):
  NIC-side admin down/up is NOT ``ip link`` and NOT ethtool-derived PCIe — it is
  the mstreg PAOS register on the GPU NIC, run over SSH on the rtptest test host:

    DOWN: mstreg -d <BDF> --reg_name PAOS \\
            --set "admin_status=2,ase=1,fd=1" -i "local_port=1"
    UP:   mstreg -d <BDF> --reg_name PAOS \\
            --set "admin_status=1,ase=1,fd=1" -i "local_port=1"

  The PCIe BDF is DETERMINISTIC (no ethtool needed):
  ``BDF = "<DEV_BLOCK>:03:00.<LANE>"`` where DEV_BLOCK is fixed per GPU/dev index
  (dev0=0000, dev1=0002, dev2=0010, dev3=0012), the middle block ``03`` is
  constant, and the PCIe function ``00.<LANE>`` carries the lane id (00.0=lane0
  ... 00.7=lane7). Example: dev0 lane1 -> ``0000:03:00.1``. This config drives
  the flap via ``create_fpf_nic_mstreg_flap_step`` (the headless TAAC equivalent
  of ``scripts/pavanpatil/fpf_host_signal_test.py --flap-dev/--flap-lane``); the
  step SSHes to the GPU host as root using the caller's Meta-SSH-CA cert/agent
  (same path as ``fpf_ib_traffic_task.async_ssh_run``).

EXPECTATIONS (identical to the interface-disable/link-disable test, TC15):
  - HRT bulk: impacted lane (lane 0) withdrawn (~0); other injected lanes
    converge.
  - HRT remote-failure: impacted lane rises 0->prefix_count; the impacted lane
    appears in the REMOTE-FAILURE collector, not in the bulk/prod view of that
    lane (injected prefixes withdrawn there).
  - Prod/broad prefix: impacted plane goes reachable->unreachable within SLA on
    the impacted host.
  - FSDB/HRT session: a NIC-side flap DOES tear down that lane's HRT FSDB
    session (host end of the GPU<->GTSW link), so overall == 32 - N with the
    per-GPU0 lane reconciliation. ``flip_fsdb_session=True`` (mirrors TC15).
  - ODS discards: real packet loss on the impacted plane (``flip_discards=True``
    — a host-side admin-down drops frames, same as the GTSW disable).
  - Host-spray: impacted beth < floor; floor+fairness on the unimpacted lanes.

Two-playbook shape (disrupt-only + stable-state restore), mirroring TC15.

Assumptions:
  - NIC-side trigger is the mstreg PAOS register flap shown above; the headless
    TAAC step ``create_fpf_nic_mstreg_flap_step`` issues it via SSH to the GPU
    host with a DETERMINISTIC PCIe BDF (no ethtool). The disrupt playbook flaps
    dev=0 lane=1 (BDF ``0000:03:00.1``, a lane-0/VF1 impacted scenario) on GPU 0
    of the z_end host a few times so the GTSW sees NDP go away on its peer port
    (eth1/45/5), withdraws the impacted VF, and the HC contract fires.
  - The flap is treated as a hard link-down event (same as the GTSW
    interface-disable), hence ``flip_fsdb_session=True`` + ``flip_discards=True``.

Usage:
  TAAC_FPF_SKIP_SSH_DEPS=1 buck2 run neteng/netcastle:netcastle_taac -- \\
    --team taac --test-config fpf_tc37_nic_side_link_flap \\
    --dev --skip-basset-reservation --skip-testbed-isolation \\
    --debug --continue-on-precheck-failure --skip-fboss-rsyslog
"""

from taac.libs.fpf.fpf_prod_prefix_map import get_prefix
from taac.playbooks.playbook_definitions import (
    create_fpf_hardening_playbook_v2,
    create_fpf_link_event_disrupt_playbook,
)
from taac.steps.step_definitions import (
    create_fpf_nic_mstreg_flap_step,
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
    num_disrupted_circuits,
    OBSERVER_GTSWS,
    skip_ssh_dependencies,
    TRIGGER_STSWS,
)
from taac.test_as_a_config.types import TestConfig

PREFIX_COUNT = 1000
STABILIZATION_DELAY_SEC = 300
LONGEVITY_SEC = 120
INJECTED_LANES = [0, 1]

# The flapped circuit. The disable is on the NIC side (z_end host's beth lane),
# not the GTSW; the GTSW interface is recorded only to derive the lane/beth.
CIRCUITS = [
    Circuit(
        a_end_device=OBSERVER_GTSWS[0],  # gtsw001.l1002 -> lane 0
        a_end_interface="eth1/45/5",
        z_end_device=GPU_HOSTS[0],  # rtptest1555.mwg2, GPU0 beth0 (NIC-side flap)
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


NIC_FLAP_ITERATIONS = 5
NIC_FLAP_INTERVAL_SEC = 2.0


def _nic_flap_step():
    """Real mstreg PAOS NIC-side flap of dev=0 lane=1 on the z_end GPU host.

    Drives ``create_fpf_nic_mstreg_flap_step`` — the headless TAAC equivalent
    of ``scripts/pavanpatil/fpf_host_signal_test.py --flap-dev 0 --flap-lane 1``:
    SSHes to the GPU host as root and loops 5 DOWN/UP cycles (every 2.0s) using
    the mstreg PAOS register at the DETERMINISTIC PCIe BDF ``0000:03:00.1``
    (dev0=DEV_BLOCK 0000, lane1=function 00.1) — no ethtool probe. The cycle
    finishes with the lane UP so no separate restore flap is needed.

    dev=0/lane=1 models the lane-0/VF1 impacted scenario for this host.
    """
    return create_fpf_nic_mstreg_flap_step(
        host=GPU_HOSTS[0],
        dev=0,
        lane=1,
        iterations=NIC_FLAP_ITERATIONS,
        interval_sec=NIC_FLAP_INTERVAL_SEC,
        description=(
            f"NIC-side mstreg flap: dev=0 lane=1 (bdf 0000:03:00.1) on rtptest, "
            f"{NIC_FLAP_ITERATIONS} iterations"
        ),
    )


def create_fpf_tc37_test_config() -> TestConfig:
    skip_ssh = skip_ssh_dependencies()
    spray = None if skip_ssh else SPRAY_HOSTS
    impacted_lanes = sorted({c.lane for c in CIRCUITS})
    n = num_disrupted_circuits(CIRCUITS)

    # Single real mstreg PAOS flap step (5 DOWN/UP cycles on beth0). The cycle
    # finishes with the lane UP; the disrupt-time HCs measure the impact during
    # the cycle and the immediately-after settle. The previous effectiveness
    # gate over ``impacted_beths`` no longer makes sense (the flap is transient,
    # the lane is UP again when the gate would run), so it is dropped in favour
    # of the well-known HC contract.
    disrupt_steps = [
        _nic_flap_step(),
        create_longevity_step(
            duration=LONGEVITY_SEC,
            description=(
                f"Settle {LONGEVITY_SEC}s after NIC-side mstreg flap on {n} "
                f"lane(s) so HRT converges before assertion"
            ),
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
        # NIC-side flap is a hard link-down (same as the GTSW interface-disable):
        # the impacted lane's HRT FSDB session drops (32 - N) and frames are lost.
        flip_fsdb_session=True,
        flip_discards=True,
        injected_prefixes_withdrawn=True,
        fsdb_expected_total=EXPECTED_FSDB_SESSION_COUNT,
        playbook_name="fpf_tc37_nic_side_link_flap_disrupt",
    )

    restore_playbook = create_fpf_hardening_playbook_v2(
        gtsws=OBSERVER_GTSWS,
        hosts=GPU_HOSTS,
        trigger_stsws=TRIGGER_STSWS,
        # The mstreg flap step in the disrupt playbook finishes with the lane
        # UP, so the restore playbook only needs a settle window for HRT to
        # finish converging; no separate "re-enable" step is required.
        disruption_steps=[
            create_longevity_step(
                duration=180,
                description="Settle after NIC-side mstreg flap; expect full recovery",
            ),
        ],
        soak_duration_sec=0,
        stabilization_delay_sec=0,
        prefix_count=PREFIX_COUNT,
        community_list=DEFAULT_COMMUNITY_LIST,
        playbook_name="fpf_tc37_nic_side_link_flap_restore",
        prod_prefixes=PROD_PREFIXES,
        skip_ssh_dependent_checks=skip_ssh,
        use_bgp_snapshot=True,
        prod_prefix_settle_sec=120,
        convergence_settle_sec=120,
        fsdb_expected_total=EXPECTED_FSDB_SESSION_COUNT,
        skip_fsdb_session_precheck=True,
        hrt_memory_hosts=HRT_MEMORY_HOSTS,
        hrt_driver_hosts=HRT_MEMORY_HOSTS,
        spray_hosts=spray,
        plane_status_check=True,
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
        name="fpf_tc37_nic_side_link_flap",
        endpoints=create_fpf_endpoints(),
        setup_tasks=setup_tasks,
        teardown_tasks=teardown_tasks,
        playbooks=[disrupt_playbook, restore_playbook],
        tags=["fpf"],
    )


TEST_CONFIG = create_fpf_tc37_test_config()
