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
    (eth1/41/5), withdraws the impacted VF, and the HC contract fires.
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
    create_fpf_inject_vf_groups_task,
    create_fpf_restart_service_task,
    create_fpf_start_collectors_task,
    create_fpf_stop_collectors_task,
    create_fpf_withdraw_vf_groups_task,
)
from taac.testconfigs.fpf.fpf_hardening_common import (
    ALL_STSWS,
    ALLOW_BASELINE_FAILURES,
    Circuit,
    create_fpf_endpoints,
    DEFAULT_COMMUNITY_LIST,
    EXPECTED_FSDB_SESSION_COUNT,
    fpf_hrt_device_ids,
    fpf_hrt_lanes,
    fpf_hrt_vf_device_ids,
    fpf_ib_traffic_config,
    fpf_ib_traffic_tasks,
    fpf_link_drain_interface,
    fpf_rf_vf_groups,
    fpf_vf_injection_groups,
    FSDB_COLLECTOR_MODE,
    GPU_HOSTS,
    HRT_MEMORY_HOSTS,
    impacted_lanes_by_host_gpu,
    num_disrupted_circuits,
    OBSERVER_GTSWS,
    skip_ib_traffic,
    skip_ssh_dependencies,
    SPRAY_HOSTS,
    TRIGGER_STSWS,
    VF_COLLECTOR_SUBNET,
    VF_GROUP_PREFIX_COUNT,
)
from taac.test_as_a_config.types import TestConfig

# 8-plane VF-group injection (VF1 5000:dd on s001-s004 = planes 0-3, VF2 5000:ee
# on s005-s008 = planes 4-7); injected once by the setup task, withdrawn in
# teardown, so the playbooks pass skip_injection=True.
INJECTION_GROUPS = fpf_vf_injection_groups()
PREFIX_COUNT = VF_GROUP_PREFIX_COUNT
INJECT_SETTLE_SEC = 300
INJECTED_LANES = fpf_hrt_lanes()
HRT_DEVICE_IDS = fpf_hrt_device_ids()
HRT_VF_DEVICE_IDS = fpf_hrt_vf_device_ids(HRT_DEVICE_IDS)
RF_VF_GROUPS = fpf_rf_vf_groups(
    active_lanes=INJECTED_LANES,
    device_ids_by_vf=(HRT_VF_DEVICE_IDS if HRT_DEVICE_IDS != [0] else None),
)
IB_TRAFFIC_CONFIG = fpf_ib_traffic_config()
STABILIZATION_DELAY_SEC = 300
LONGEVITY_SEC = 120

# The flapped circuit. The disable is on the NIC side (z_end host's beth lane),
# not the GTSW; the GTSW interface is recorded only to derive the lane/beth.
CIRCUITS = [
    Circuit(
        a_end_device=OBSERVER_GTSWS[0],  # gtsw001.l1002 -> lane 0
        a_end_interface=fpf_link_drain_interface(GPU_HOSTS),
        z_end_device=GPU_HOSTS[0],
        z_end_gpu_id=0,
    ),
]

PROD_PREFIX_HOST = GPU_HOSTS[0]
PROD_PREFIX_DEVICE_ID = 0
PROD_PREFIXES = [get_prefix(PROD_PREFIX_HOST, PROD_PREFIX_DEVICE_ID)]
PROD_PREFIXES_BY_HOST = {host: PROD_PREFIXES for host in GPU_HOSTS}


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
    """Real mstreg PAOS NIC-side flap of the selected end-to-end circuit.

    Drives ``create_fpf_nic_mstreg_flap_step`` — the headless TAAC equivalent
    The physical GPU and global lane are derived from the same Circuit that
    drives beth/plane expectations, so the PAOS BDF cannot drift from the
    GTSW-side adjacency.
    """
    circuit = CIRCUITS[0]
    return create_fpf_nic_mstreg_flap_step(
        host=circuit.z_end_device,
        dev=circuit.z_end_gpu_id,
        lane=circuit.lane,
        iterations=NIC_FLAP_ITERATIONS,
        interval_sec=NIC_FLAP_INTERVAL_SEC,
        description=(
            f"NIC-side mstreg flap: dev={circuit.z_end_gpu_id} "
            f"lane={circuit.lane} ({circuit.nic_interface}) on "
            f"{circuit.z_end_device}, {NIC_FLAP_ITERATIONS} iterations"
        ),
    )


def create_fpf_tc37_test_config() -> TestConfig:
    skip_ssh = skip_ssh_dependencies()
    skip_ib = skip_ib_traffic()
    ib_setup, ib_teardown = fpf_ib_traffic_tasks(
        skip_ssh, skip_ib, traffic_config=IB_TRAFFIC_CONFIG
    )
    spray = None if skip_ssh or skip_ib else SPRAY_HOSTS
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
        prod_prefixes_by_host=PROD_PREFIXES_BY_HOST,
        hrt_memory_hosts=HRT_MEMORY_HOSTS,
        hrt_driver_hosts=HRT_MEMORY_HOSTS,
        spray_hosts=spray,
        ib_traffic_config=IB_TRAFFIC_CONFIG if spray else None,
        # NIC-side flap is a hard link-down (same as the GTSW interface-disable):
        # the impacted lane's HRT FSDB session drops (32 - N) and frames are lost.
        flip_fsdb_session=True,
        flip_discards=True,
        injected_prefixes_withdrawn=True,
        fsdb_expected_total=EXPECTED_FSDB_SESSION_COUNT,
        # Prefixes injected once by the setup task (8-STSW split-per-VF).
        skip_injection=True,
        rf_vf_groups=RF_VF_GROUPS,
        hrt_device_ids=HRT_DEVICE_IDS,
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
        prod_prefixes_by_host=PROD_PREFIXES_BY_HOST,
        skip_ssh_dependent_checks=skip_ssh,
        use_bgp_snapshot=True,
        prod_prefix_settle_sec=120,
        convergence_settle_sec=120,
        fsdb_expected_total=EXPECTED_FSDB_SESSION_COUNT,
        skip_fsdb_session_precheck=True,
        hrt_memory_hosts=HRT_MEMORY_HOSTS,
        hrt_driver_hosts=HRT_MEMORY_HOSTS,
        spray_hosts=spray,
        ib_traffic_config=IB_TRAFFIC_CONFIG if spray else None,
        plane_status_check=True,
        prod_prefix_recovery=True,
        local_prod_prefixes=PROD_PREFIXES,
        impacted_planes_by_host=_impacted_planes_by_host(CIRCUITS),
        # Check all 8 injected lanes recovered (not just the default [0,1]).
        lanes=INJECTED_LANES,
        # Prefixes injected once by the setup task; do not re-inject on restore.
        skip_injection=True,
        rf_vf_groups=RF_VF_GROUPS,
        hrt_device_ids=HRT_DEVICE_IDS,
    )

    setup_tasks = [*ib_setup]
    teardown_tasks = [*ib_teardown]
    setup_tasks.append(
        create_fpf_start_collectors_task(
            gtsws=OBSERVER_GTSWS,
            hosts=GPU_HOSTS,
            hrt_device_ids=HRT_DEVICE_IDS,
            hrt_plane_ids=INJECTED_LANES,
            subnet_prefix=VF_COLLECTOR_SUBNET,
            prod_prefixes_by_host=PROD_PREFIXES_BY_HOST,
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
        create_fpf_stop_collectors_task(
            trigger_stsws=TRIGGER_STSWS,
            withdraw=False,
            community_list=DEFAULT_COMMUNITY_LIST,
        )
    )

    return TestConfig(
        name="fpf_tc37_nic_side_link_flap",
        endpoints=create_fpf_endpoints(stsws=ALL_STSWS),
        setup_tasks=setup_tasks,
        teardown_tasks=teardown_tasks,
        playbooks=[disrupt_playbook, restore_playbook],
        tags=["fpf"],
    )


TEST_CONFIG = create_fpf_tc37_test_config()
