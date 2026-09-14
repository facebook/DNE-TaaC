# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe

"""TC36: All STSW Connections Down Simultaneously.

Shuts EVERY gtsw001.l1002.c087.mwg2 -> stsw001.s001.l202.mwg2 uplink interface
AT ONCE (a single batched thrift port-disable run ON the GTSW), so the whole
GTSW<->STSW plane-1 trunk drops in one step rather than one link at a time.
This is the "lose an entire spine-side connection bundle" failure: the impacted
GTSW lane (lane 0) loses its STSW uplink set wholesale.

The LLDP query + disable is performed from the GTSW side (the test owner's
request): on gtsw001, resolve the uplinks facing stsw001.s001 and shut them.

DISRUPTION MECHANISM (runtime LLDP plus run-scoped restore state):
  Uses ``create_fpf_lldp_batched_set_interface_admin_step``: at step run time,
  on ``DUT_GTSW`` (gtsw001), the handler enumerates LLDP neighbors and matches
  the remote system name against ``MEMBER_NEIGHBOR_PATTERN`` (fnmatch glob over
  the specific STSW plane being downed, ``"stsw001.s001*"``) to get gtsw001's
  local uplink interfaces facing that STSW, then issues a SINGLE batched
  ``async_thrift_disable_enable_interfaces`` call over the resolved tuple. The
  exact 36-interface set is cached before disable. Restore consumes that cache
  because LLDP disappears while every member is down; a restore-only run uses
  the same explicit, validated 36-port allowlist as its fallback. Both mutations
  verify admin state after the batched call.
  Broadening the pattern to ``"stsw*"`` would down ALL planes' uplinks at once;
  we scope to the single plane under test.
  "Batched" here means one ``async_agent_client`` context with sequential
  per-port ``setPortState`` calls (FBOSS exposes no list-RPC), the same
  primitive used by the held-admin-down step. No COOP config patcher — that
  only patches config and needs reload/warmboot to actually shut the port.

EXPECTATIONS (mirror the STSW/GTSW DEVICE-DRAIN test, TC19, with the
all-connections-down nuances):
  - The directly-injected test prefixes and GTSW-side RIB on the impacted lane
    (lane 0) are withdrawn while all 36 uplinks are down. The disrupted phase
    therefore omits the inapplicable lane-0 BGP/FSDB stability checks while
    keeping the unaffected observer strict; the restore phase checks both.
  - The directly-injected test prefixes on the impacted lane (lane 0) are
    WITHDRAWN from the bulk/prod collectors of THAT (impacted) lane — those
    collectors no longer see lane-0 prefixes. They instead surface in the
    REMOTE-FAILURE collector (lane 0 rises 0->prefix_count), which is exactly
    the "impacted lane appears in the remote-failure view, not in the
    bulk/prod view" contract. ``impacted_lanes=[0]`` +
    ``injected_prefixes_withdrawn=True`` drives the bulk-withdrawal assertion
    and the remote-failure rise on lane 0.
  - Prod/broad prefix: impacted plane (lane 0) goes reachable->unreachable
    within the transition SLA on the impacted host.
  - FSDB/HRT session: shutting gtsw001's UPLINKS to stsw001 does NOT drop the
    GPU<->GTSW HRT FSDB sessions — those ride the gtsw DOWNLINKS, which stay up;
    sessions stay all-CONNECTED. ``flip_fsdb_session=False`` (as before; mirrors
    TC19 device-drain).
  - ODS discards (in_discard / in_dst_null): packet loss is EXPECTED on the
    impacted plane but is RECORDED non-failing, mirroring the
    ``ods_discard_informational`` knob on the service-restart playbook. Both
    DISCARD checks are added with ``informational=True`` (breach -> PASS with
    an ``[INFORMATIONAL]`` prefix instead of FAIL). The two CONGESTION checks
    stay hard (a link event must not cause congestion). ``flip_discards`` is
    left at False so the hard ``loss>=threshold`` "assert loss occurred"
    counter (used by tc15/tc37) is NOT added — the informational discards
    record the same loss without failing.
  - Host-spray + all other generic HCs: same as the device-drain test.

Two-playbook shape (disrupt-only + stable-state restore), mirroring TC15/TC19:
the disrupt playbook performs the batched STSW shut + settle + effectiveness
gate; the restore playbook re-enables the whole member set and validates full
stable-state recovery.

Assumptions:
  - Member interfaces are resolved live from LLDP on ``DUT_GTSW`` (gtsw001)
    for disruption and must exactly match ``EXPECTED_MEMBER_INTERFACES``.
    Restore uses the cached set or that same allowlist when invoked separately.
  - Batched-at-once semantics: a single
    ``async_thrift_disable_enable_interfaces`` call over the resolved tuple
    issues sequential per-port ``setPortState`` calls inside ONE
    ``async_agent_client`` context — "simultaneous" within the limits of the
    FBOSS thrift API (no list-RPC exists).
  - Informational discard semantics use ``ods_discard_informational=True``
    (record-but-never-fail) on the link-event playbook. ``flip_discards`` is
    False so the hard ``loss>=threshold`` "loss expected" check is not added
    alongside the informational discards.

Usage:
  TAAC_FPF_SKIP_SSH_DEPS=1 buck2 run neteng/netcastle:netcastle_taac -- \\
    --team taac --test-config fpf_tc36_stsw_all_connections_down \\
    --dev --skip-basset-reservation --skip-testbed-isolation \\
    --debug --continue-on-precheck-failure --skip-fboss-rsyslog
"""

from taac.health_checks.healthcheck_definitions import (
    create_fpf_prod_hrt_prefix_stability_check,
)
from taac.libs.fpf.fpf_prod_prefix_map import get_prefix
from taac.playbooks.playbook_definitions import (
    create_fpf_hardening_playbook_v2,
    create_fpf_link_event_disrupt_playbook,
)
from taac.steps.step_definitions import (
    create_fpf_lldp_batched_set_interface_admin_step,
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
from taac.testconfigs.fpf.fpf_hardening_common import (
    ALL_STSWS,
    ALLOW_BASELINE_FAILURES,
    Circuit,
    create_fpf_endpoints,
    DEFAULT_COMMUNITY_LIST,
    EXPECTED_FSDB_SESSION_COUNT,
    fpf_gpu_downlink_interfaces,
    fpf_hrt_device_ids,
    fpf_hrt_lanes,
    fpf_hrt_vf_device_ids,
    fpf_ib_traffic_config,
    fpf_ib_traffic_tasks,
    fpf_rf_vf_groups,
    fpf_vf_injection_groups,
    FSDB_COLLECTOR_MODE,
    GPU_HOSTS,
    HRT_MEMORY_HOSTS,
    impacted_lanes_by_host_gpu,
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

# The GTSW on which the batched admin-disable is run. The LLDP query +
# disable is done from the GTSW side (the test owner's request): on gtsw001,
# resolve every uplink interface facing the STSW being downed and shut them
# all at once. DUT_GTSW is the impacted GTSW (OBSERVER_GTSWS[0]).
DUT_GTSW = OBSERVER_GTSWS[0]  # gtsw001.l1002.c087.mwg2

# The STSW whose entire connection bundle to gtsw001 is shut (plane-1 trunk:
# gtsw001.l1002 -> stsw001.s001.l202). Documented for the docstring/intent.
DISRUPT_STSW = TRIGGER_STSWS[0]  # stsw001.s001.l202.mwg2

# LLDP-resolved at run time: on DUT_GTSW (gtsw001), every local interface whose
# LLDP remote system name matches this fnmatch glob is included in the batched
# admin-disable. ``stsw001.s001*`` is the SPECIFIC plane being downed (plane 1)
# from the CSV — it matches only gtsw001's uplinks facing stsw001.s001.
# NOTE: broadening to ``stsw*`` would down ALL STSW planes' uplinks at once;
# we intentionally scope to the single plane under test.
MEMBER_NEIGHBOR_PATTERN = "stsw001.s001*"
INTERFACE_CACHE_KEY = "tc36_gtsw_stsw_members"
UP_PORT_BASELINE_KEY = "tc36_pre_disruption_up_ports"
# Exact 36-port scope observed from the healthy LLDP baseline. Restore-only
# invocations use this fail-closed allowlist because LLDP is absent while every
# member is held admin-down.
EXPECTED_MEMBER_INTERFACES = [
    "eth1/10/1",
    "eth1/10/5",
    "eth1/14/1",
    "eth1/14/5",
    "eth1/18/1",
    "eth1/18/5",
    "eth1/2/1",
    "eth1/2/5",
    "eth1/22/1",
    "eth1/22/5",
    "eth1/23/1",
    "eth1/23/5",
    "eth1/26/1",
    "eth1/26/5",
    "eth1/30/1",
    "eth1/30/5",
    "eth1/34/1",
    "eth1/34/5",
    "eth1/38/1",
    "eth1/38/5",
    "eth1/42/1",
    "eth1/42/5",
    "eth1/46/1",
    "eth1/46/5",
    "eth1/50/1",
    "eth1/50/5",
    "eth1/54/1",
    "eth1/54/5",
    "eth1/58/1",
    "eth1/58/5",
    "eth1/6/1",
    "eth1/6/5",
    "eth1/62/1",
    "eth1/62/5",
    "eth1/63/1",
    "eth1/63/5",
]

# The MONITORED circuit on the impacted GTSW lane (lane 0). Shutting the STSW
# uplink bundle for gtsw001 depreferences/withdraws this plane, so the observed
# impact matches a lane-0 link event on the GPU side.
CIRCUITS = [
    Circuit(
        a_end_device=OBSERVER_GTSWS[0],  # gtsw001.l1002 -> lane 0
        a_end_interface=interface,
        z_end_device=GPU_HOSTS[0],
        z_end_gpu_id=gpu_id,
    )
    for gpu_id, interface in enumerate(fpf_gpu_downlink_interfaces(GPU_HOSTS))
]

PROD_PREFIX_HOST = GPU_HOSTS[0]
PROD_PREFIX_DEVICE_ID = 0
PROD_PREFIXES = [get_prefix(PROD_PREFIX_HOST, PROD_PREFIX_DEVICE_ID)]
PROD_PREFIXES_BY_HOST = {host: PROD_PREFIXES for host in GPU_HOSTS}
# The source keeps its own route reachable. Conditional-route withdrawal and
# recovery are observed on the remote host, while the source must remain stable.
IMPACTED_PROD_PREFIXES_BY_HOST = {GPU_HOSTS[1]: PROD_PREFIXES}
UNAFFECTED_PROD_PREFIXES_BY_HOST = {GPU_HOSTS[0]: PROD_PREFIXES}
IMPACTED_PLANES_BY_HOST = {GPU_HOSTS[1]: [0]}


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


def _stsw_member_disable_steps(enable: bool) -> list:
    """Single LLDP-resolved batched thrift admin-state step on the GTSW.

    At step run time, on ``DUT_GTSW`` (gtsw001), enumerate LLDP neighbors and
    pick the local interfaces whose remote system name matches
    ``MEMBER_NEIGHBOR_PATTERN`` (``stsw001.s001*``) — i.e. gtsw001's uplinks
    facing the STSW being downed — then issue ONE batched
    ``async_thrift_disable_enable_interfaces`` call over the resolved tuple —
    the "shut all ... at once" requirement, within the limits of the FBOSS
    thrift API (no list-RPC exists; "batched" = one open agent client context,
    sequential per-port setPortState). NOT the COOP config patcher.
    """
    return [
        create_fpf_lldp_batched_set_interface_admin_step(
            neighbor_pattern=MEMBER_NEIGHBOR_PATTERN,
            enable=enable,
            device_regexes=[DUT_GTSW],
            interface_cache_key=INTERFACE_CACHE_KEY,
            use_cached_interfaces=enable,
            expected_interfaces=EXPECTED_MEMBER_INTERFACES,
            description=(
                f"{'Enable' if enable else 'Disable'} ALL LLDP-resolved "
                f"{DUT_GTSW} uplink interfaces with neighbor~="
                f"{MEMBER_NEIGHBOR_PATTERN!r} in one batched thrift call"
            ),
        )
    ]


def create_fpf_tc36_test_config() -> TestConfig:
    skip_ssh = skip_ssh_dependencies()
    skip_ib = skip_ib_traffic()
    ib_setup, ib_teardown = fpf_ib_traffic_tasks(
        skip_ssh, skip_ib, traffic_config=IB_TRAFFIC_CONFIG
    )
    spray = None if skip_ssh or skip_ib else SPRAY_HOSTS
    impacted_lanes = sorted({c.lane for c in CIRCUITS})

    # NOTE: the prior per-interface verify_disruption gate is dropped because
    # the member list is only known at step run time (LLDP-resolved). The
    # batched LLDP step itself raises if the LLDP query returns no neighbors,
    # so the disruption can never silently no-op. A future LLDP-aware
    # verify_disruption step is a follow-up.
    disrupt_steps = [
        create_fpf_up_port_baseline_step(
            action="capture",
            devices=[DUT_GTSW],
            baseline_key=UP_PORT_BASELINE_KEY,
            expected_interfaces_by_device={DUT_GTSW: EXPECTED_MEMBER_INTERFACES},
            device_regexes=[DUT_GTSW],
            description=(
                "Capture and validate the exact 36 operationally-UP TC36 "
                "uplinks before disruption"
            ),
        ),
        *_stsw_member_disable_steps(enable=False),
        create_longevity_step(
            duration=LONGEVITY_SEC,
            description=(
                f"Settle {LONGEVITY_SEC}s after shutting the whole "
                f"{DUT_GTSW}->{DISRUPT_STSW} uplink bundle before assertion"
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
        impacted_planes_by_host=IMPACTED_PLANES_BY_HOST,
        prod_prefixes=PROD_PREFIXES,
        prod_prefixes_by_host=IMPACTED_PROD_PREFIXES_BY_HOST,
        hrt_memory_hosts=HRT_MEMORY_HOSTS,
        hrt_driver_hosts=HRT_MEMORY_HOSTS,
        spray_hosts=None,
        ib_traffic_config=None,
        # Losing the STSW uplink bundle WITHDRAWS the impacted lane's injected
        # prefixes from the bulk/prod collectors; they surface in the
        # remote-failure collector (lane 0 rises 0->count) instead.
        injected_prefixes_withdrawn=True,
        # GPU<->GTSW HRT FSDB sessions are GTSW-local and stay CONNECTED when the
        # STSW-side bundle drops — mirror the device-drain "control up" contract.
        flip_fsdb_session=False,
        # Discards/loss are EXPECTED on the impacted plane but RECORDED
        # non-failing via ods_discard_informational=True (the two DISCARD
        # checks come in with informational=True; the two CONGESTION checks
        # stay hard). flip_discards stays False so the hard "loss>=threshold"
        # assertion is not added alongside the informational discards.
        flip_discards=False,
        ods_discard_informational=True,
        fsdb_expected_total=EXPECTED_FSDB_SESSION_COUNT,
        # Prefixes injected once by the setup task (8-STSW split-per-VF).
        skip_injection=True,
        rf_vf_groups=RF_VF_GROUPS,
        hrt_device_ids=HRT_DEVICE_IDS,
        gtsw_rib_unavailable_lanes=impacted_lanes,
        prod_prefix_precheck_lookback_sec=120,
        additional_postchecks=[
            create_fpf_prod_hrt_prefix_stability_check(
                prefixes_by_host=UNAFFECTED_PROD_PREFIXES_BY_HOST,
                check_id="fpf_prod_hrt_prefix_unaffected_stability",
            )
        ],
        playbook_name="fpf_tc36_stsw_all_connections_down_disrupt",
    )

    restore_playbook = create_fpf_hardening_playbook_v2(
        gtsws=OBSERVER_GTSWS,
        hosts=GPU_HOSTS,
        trigger_stsws=TRIGGER_STSWS,
        disruption_steps=[
            *_stsw_member_disable_steps(enable=True),
            create_longevity_step(
                duration=180,
                description=(
                    "Settle after re-enabling the whole gtsw001->STSW uplink "
                    "bundle; expect full recovery"
                ),
            ),
        ],
        soak_duration_sec=0,
        stabilization_delay_sec=0,
        prefix_count=PREFIX_COUNT,
        community_list=DEFAULT_COMMUNITY_LIST,
        playbook_name="fpf_tc36_stsw_all_connections_down_restore",
        prod_prefixes=PROD_PREFIXES,
        prod_prefixes_by_host=IMPACTED_PROD_PREFIXES_BY_HOST,
        skip_ssh_dependent_checks=skip_ssh,
        use_bgp_snapshot=True,
        prod_prefix_settle_sec=120,
        convergence_settle_sec=120,
        fsdb_expected_total=EXPECTED_FSDB_SESSION_COUNT,
        skip_fsdb_session_precheck=True,
        # The disrupt half left the gtsw001->stsw001 uplink bundle DOWN; this
        # restore re-enables it in-stage and settles 180s. Skip the PORT_STATE
        # precheck (it runs BEFORE the re-enable, so it would FAIL on the
        # still-down / just-re-enabled-but-unsettled ports). The postcheck still
        # re-asserts full port/plane recovery after the settle.
        skip_port_state_precheck=True,
        hrt_memory_hosts=HRT_MEMORY_HOSTS,
        hrt_driver_hosts=HRT_MEMORY_HOSTS,
        spray_hosts=spray,
        ib_traffic_config=IB_TRAFFIC_CONFIG if spray else None,
        plane_status_check=True,
        prod_prefix_recovery=True,
        local_prod_prefixes=PROD_PREFIXES,
        impacted_planes_by_host=IMPACTED_PLANES_BY_HOST,
        # Check all 8 injected lanes recovered (not just the default [0,1]).
        lanes=INJECTED_LANES,
        # Prefixes injected once by the setup task; do not re-inject on restore.
        skip_injection=True,
        rf_vf_groups=RF_VF_GROUPS,
        hrt_device_ids=HRT_DEVICE_IDS,
        ensure_traffic_after_disruption=True,
        recovered_baseline_qualification_sec=120,
        bgp_convergence_blip_mode="skip_null_strict",
        bgp_require_final_exact=True,
        additional_postchecks=[
            create_fpf_prod_hrt_prefix_stability_check(
                prefixes_by_host=UNAFFECTED_PROD_PREFIXES_BY_HOST,
                settle_sec=120,
                check_id="fpf_prod_hrt_prefix_unaffected_stability",
            )
        ],
        final_validation_steps=[
            create_longevity_step(
                duration=300,
                description="Strict stable-state soak after link and traffic recovery",
            ),
            create_fpf_up_port_baseline_step(
                action="verify",
                devices=[DUT_GTSW],
                baseline_key=UP_PORT_BASELINE_KEY,
                expected_interfaces_by_device={DUT_GTSW: EXPECTED_MEMBER_INTERFACES},
                device_regexes=[DUT_GTSW],
                description=(
                    "Assert every exact TC36 uplink that was UP before "
                    "disruption is operationally UP after longevity"
                ),
            ),
        ],
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
        name="fpf_tc36_stsw_all_connections_down",
        endpoints=create_fpf_endpoints(stsws=ALL_STSWS),
        setup_tasks=setup_tasks,
        teardown_tasks=teardown_tasks,
        playbooks=[disrupt_playbook, restore_playbook],
        tags=["fpf"],
    )


TEST_CONFIG = create_fpf_tc36_test_config()
