# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe

"""TC37: one held NIC-side link disable followed by explicit restore.

Same observable contract as the GTSW interface-disable test (TC15) EXCEPT the
admin down/up is applied on the NIC side (the rtptest GPU host), not on the
GTSW. The lane-0 GPU<->GTSW link is flapped from the host end, so HRT churns on
that lane while the GTSW port stays as configured.

DISRUPTION MECHANISM (real, headless TAAC step — no longer a placeholder):
  NIC-side admin state is NOT ``ip link`` and NOT ethtool-derived PCIe — it is
  the mstreg PAOS register on the GPU NIC, run over SSH on the rtptest test host:

    DOWN: mstreg --yes -d <BDF> --reg_name PAOS \\
            --set "admin_status=2,ase=1,fd=1" -i "local_port=1"
    UP:   mstreg --yes -d <BDF> --reg_name PAOS \\
            --set "admin_status=1,ase=1,fd=1" -i "local_port=1"

  The PCIe BDF is DETERMINISTIC (no ethtool needed):
  ``BDF = "<DEV_BLOCK>:03:00.<LANE>"`` where DEV_BLOCK is fixed per GPU/dev index
  (dev0=0000, dev1=0002, dev2=0010, dev3=0012), the middle block ``03`` is
  constant, and the PCIe function ``00.<LANE>`` carries the lane id (00.0=lane0
  ... 00.7=lane7). Example: dev0 lane1 -> ``0000:03:00.1``. This config drives
  the transition via ``create_fpf_nic_mstreg_paos_step``; the
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

The disrupt playbook sends one verified DOWN and leaves the lane down while its
postchecks run. The restore playbook sends one verified UP, waits for recovery,
then applies the same stable-state contract as TC15.

Assumptions:
  - NIC-side trigger is the mstreg PAOS register shown above. The physical GPU
    and lane are derived from ``CIRCUITS``; for the canonical twshared setup
    this is dev0/lane0/beth0 (BDF ``0000:03:00.0``).
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
    create_fpf_disrupt_window_playbook,
    create_fpf_hardening_playbook_v2,
    create_fpf_link_event_disrupt_playbook,
)
from taac.steps.step_definitions import (
    create_fpf_nic_mstreg_flap_step,
    create_fpf_nic_mstreg_paos_step,
    create_fpf_nic_mstreg_verify_link_step,
    create_fpf_up_port_baseline_step,
    create_longevity_step,
)
from taac.task_definitions import (
    create_fpf_inject_vf_groups_task,
    create_fpf_restart_service_task,
    create_fpf_start_collectors_task,
    create_fpf_stop_collectors_task,
    create_fpf_withdraw_vf_groups_task,
)
from taac.testconfigs.fpf.fpf_flap_contract import (
    build_flap_disrupt_postchecks,
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


NIC_CONTINUOUS_FLAP_DURATION_SEC = 900
NIC_FLAP_DOWN_SEC = 2.0
NIC_FLAP_UP_SEC = 2.0
NIC_STATE_TIMEOUT_SEC = 30.0
NIC_FINAL_CLEANUP_TIMEOUT_SEC = 120.0
CONTINUOUS_LONGEVITY_SEC = 300
RECOVERY_QUALIFICATION_SEC = 120
UP_PORT_BASELINE_KEY = "tc37b_pre_disruption_up_ports"


def _nic_paos_step(*, admin_up: bool, verify_link_health: bool = False):
    """Build one verified PAOS transition from the selected Circuit."""
    circuit = CIRCUITS[0]
    return create_fpf_nic_mstreg_paos_step(
        host=circuit.z_end_device,
        dev=circuit.z_end_gpu_id,
        lane=circuit.lane,
        admin_up=admin_up,
        state_timeout_sec=NIC_STATE_TIMEOUT_SEC,
        verify_link_health=verify_link_health,
        description=(
            f"NIC-side mstreg PAOS {'UP' if admin_up else 'DOWN'}: "
            f"dev={circuit.z_end_gpu_id} "
            f"lane={circuit.lane} ({circuit.nic_interface}) on "
            f"{circuit.z_end_device}"
        ),
    )


def _nic_continuous_flap_step():
    """Build the 15-minute deadline-based 2s-DOWN/2s-UP stress trigger."""
    circuit = CIRCUITS[0]
    return create_fpf_nic_mstreg_flap_step(
        host=circuit.z_end_device,
        dev=circuit.z_end_gpu_id,
        lane=circuit.lane,
        duration_sec=NIC_CONTINUOUS_FLAP_DURATION_SEC,
        down_time_sec=NIC_FLAP_DOWN_SEC,
        up_time_sec=NIC_FLAP_UP_SEC,
        state_timeout_sec=NIC_STATE_TIMEOUT_SEC,
        final_cleanup_timeout_sec=NIC_FINAL_CLEANUP_TIMEOUT_SEC,
        description=(
            f"NIC-side PAOS stress on {circuit.z_end_device} "
            f"dev={circuit.z_end_gpu_id} lane={circuit.lane} "
            f"for {NIC_CONTINUOUS_FLAP_DURATION_SEC}s"
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

    # One verified PAOS DOWN transition on beth0. It stays down throughout the
    # disrupt postchecks; the second playbook owns the explicit UP transition.
    disrupt_steps = [
        _nic_paos_step(admin_up=False),
        create_longevity_step(
            duration=LONGEVITY_SEC,
            description=(
                f"Settle {LONGEVITY_SEC}s after NIC-side PAOS DOWN on {n} "
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
        disruption_steps=[
            _nic_paos_step(admin_up=True, verify_link_health=True),
            create_longevity_step(
                duration=180,
                description="Settle after NIC-side PAOS UP; expect full recovery",
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


def create_fpf_tc37b_test_config() -> TestConfig:
    """Build the separate 15-minute NIC-side continuous-flap stress case."""
    base = create_fpf_tc37_test_config()
    skip_ssh = skip_ssh_dependencies()
    skip_ib = skip_ib_traffic()
    spray = None if skip_ssh or skip_ib else SPRAY_HOSTS
    circuit = CIRCUITS[0]

    disrupt_playbook = create_fpf_disrupt_window_playbook(
        playbook_name="fpf_tc37b_nic_side_continuous_flap_disrupt",
        disruption_steps=[
            create_fpf_up_port_baseline_step(
                action="capture",
                devices=[circuit.a_end_device],
                baseline_key=UP_PORT_BASELINE_KEY,
                device_regexes=[circuit.a_end_device],
            ),
            _nic_continuous_flap_step(),
            create_longevity_step(
                duration=LONGEVITY_SEC,
                description=(
                    f"Settle {LONGEVITY_SEC}s after NIC-side continuous flaps"
                ),
            ),
        ],
        postchecks=build_flap_disrupt_postchecks(
            observer_gtsws=OBSERVER_GTSWS,
            hrt_memory_hosts=HRT_MEMORY_HOSTS,
            prefix_count=PREFIX_COUNT,
            skip_ssh=skip_ssh,
            include_route_convergence=False,
            bgp_route_diagnostic_only=True,
        ),
        ib_traffic_config=IB_TRAFFIC_CONFIG if spray else None,
    )

    longevity_playbook = create_fpf_hardening_playbook_v2(
        gtsws=OBSERVER_GTSWS,
        hosts=GPU_HOSTS,
        trigger_stsws=TRIGGER_STSWS,
        soak_duration_sec=CONTINUOUS_LONGEVITY_SEC,
        stabilization_delay_sec=0,
        prefix_count=PREFIX_COUNT,
        community_list=DEFAULT_COMMUNITY_LIST,
        playbook_name="fpf_tc37b_nic_side_continuous_flap_longevity",
        prod_prefixes=PROD_PREFIXES,
        prod_prefixes_by_host=PROD_PREFIXES_BY_HOST,
        skip_ssh_dependent_checks=skip_ssh,
        fsdb_expected_total=EXPECTED_FSDB_SESSION_COUNT,
        hrt_memory_hosts=HRT_MEMORY_HOSTS,
        hrt_driver_hosts=HRT_MEMORY_HOSTS,
        spray_hosts=spray,
        ib_traffic_config=IB_TRAFFIC_CONFIG if spray else None,
        plane_status_check=True,
        lanes=INJECTED_LANES,
        skip_injection=True,
        rf_vf_groups=RF_VF_GROUPS,
        hrt_device_ids=HRT_DEVICE_IDS,
        recovered_baseline_qualification_sec=RECOVERY_QUALIFICATION_SEC,
        bgp_require_final_exact=True,
        final_validation_steps=[
            create_fpf_nic_mstreg_verify_link_step(
                host=circuit.z_end_device,
                dev=circuit.z_end_gpu_id,
                lane=circuit.lane,
            ),
            create_fpf_up_port_baseline_step(
                action="verify",
                devices=[circuit.a_end_device],
                baseline_key=UP_PORT_BASELINE_KEY,
                device_regexes=[circuit.a_end_device],
            ),
        ],
    )

    return TestConfig(
        name="fpf_tc37b_nic_side_continuous_flap",
        endpoints=base.endpoints,
        setup_tasks=base.setup_tasks,
        teardown_tasks=base.teardown_tasks,
        playbooks=[disrupt_playbook, longevity_playbook],
        tags=["fpf"],
    )


TEST_CONFIG = create_fpf_tc37_test_config()
