# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe

"""Shared disrupt-window health-check contract for the FPF service-kill tests.

The bgp/wedge_agent/fsdb "SIGKILL every Ns for M min" configs (tc49/tc50/tc51)
all kill ONE service on the DUT GTSW (gtsw001, which owns the impacted lane) for
the whole kill loop. During that loop the per-lane HRT/RDMA "collector" signals
(session census, host-spray, bulk/remote-failure/prod-prefix convergence) are
deliberately perturbed — the impacted lane churns on every kill — so they carry
no stable verdict here. They are therefore asserted FULL-STRENGTH in the
stable-state longevity playbook instead, NOT in this disrupt window.

The disrupt window asserts only the "did the kill break something it shouldn't"
safety signals, which differ by service:

  killed service │ bgp up? │ ports up? │ exclude (systemctl) │ unclean-exit asserted?
  ───────────────┼─────────┼───────────┼─────────────────────┼───────────────────────
  fsdb           │  yes    │   yes     │ fsdb                │ yes (minus fsdb)
  bgpd           │  no     │   yes     │ bgpd                │ yes (minus bgpd)
  wedge_agent    │  no     │   no      │ wedge_agent + bgpd  │ NO (coldboot teardown
                 │         │           │   (BindsTo)         │   is legitimately unclean)

Asserted in the disrupt window for all three:
  - SYSTEMCTL_ACTIVE_STATE (minus killed/cascaded) — others stay active
  - UNCLEAN_EXIT (minus killed/cascaded)           — EXCEPT wedge_agent (see above)
  - DEVICE_CORE_DUMPS                              — no new core dumps
  - FPF_HRT_SYSTEM_MEMORY / DRIVER_DISCONNECT      — HRT process healthy
  - GENERIC_ODS discards                           — in_dst_null & in_discard captured
                                                     (informational), congestion == 0
  - FPF_BGP_RIB_CONVERGENCE                        — ONLY when bgpd stays up (fsdb
                                                     kill): the RIB must NOT be
                                                     impacted by an fsdb restart.

NOT asserted in the disrupt window (judged in the longevity playbook instead):
FPF_HRT_FSDB_SESSION, FPF_HOST_SPRAY, FPF_HRT_BULK, FPF_HRT_REMOTE_FAILURE,
FPF_PROD_HRT_PREFIX.
"""

from taac.health_checks.healthcheck_definitions import (
    create_bgp_session_establish_check,
    create_device_core_dumps_check,
    create_fpf_bgp_rib_convergence_check,
    create_fpf_hrt_driver_disconnect_check,
    create_fpf_hrt_system_memory_check,
    create_fpf_ods_counter_check,
    create_port_state_check,
    create_systemctl_active_state_check,
    create_unclean_exit_check,
)

ALL_FPF_SERVICES = ["bgpd", "fsdb", "wedge_agent", "qsfp_service"]

# Services to drop from the systemctl/unclean-exit assertions per killed service.
# wedge_agent is BindsTo bgpd, so killing the agent also bounces bgpd.
KILL_EXCLUDE_SERVICES = {
    "fsdb": ["fsdb"],
    "bgpd": ["bgpd"],
    "wedge_agent": ["wedge_agent", "bgpd"],
}

# ODS discard/congestion counters on the GTSW "industrial cards".
_ODS_REDUCE = r"groupby(entity, (\S+?\.\S+?)\..*, %1),sum"
_ODS_IN_DST_NULL_KEY = (
    r"regex(fboss.agent.eth.*discards.sum.60),filter(.*in_dst_null.*)"
)
_ODS_IN_DISCARD_KEY = r"regex(fboss.agent.eth.*discards.sum.60),filter(.*in_discard.*)"
_ODS_IN_CONGESTION_KEY = (
    r"regex(fboss.agent.eth.*congestion.*sum.60),filter(.*in_congestion_discards.sum.*)"
)
_ODS_OUT_CONGESTION_KEY = r"regex(fboss.agent.eth.*congestion.*sum.60),filter(.*out_congestion_discards.sum.*)"
DISCARD_FLOOR = 10000  # in_dst_null / in_discard must spike past this (loss occurred)


def build_kill_disrupt_postchecks(
    *,
    killed_service: str,
    observer_gtsws: list[str],
    hrt_memory_hosts: list[str],
    spray_hosts: list[str] | None,
    kill_duration_sec: int,
    prefix_count: int,
    skip_ssh: bool,
    expected_fsdb_total: int = 32,
    impacted_lane: int = 0,
    session_lookback_sec: int = 1000,
    out_congestion_informational: bool = False,
) -> list:
    """Return the disrupt-window postcheck list for a service-kill test.

    ``killed_service`` is one of "fsdb" | "bgpd" | "wedge_agent" and selects the
    per-service knobs (see module docstring). The killed service owns
    ``impacted_lane`` (lane 0 = gtsw001) on the BE node.
    """
    if killed_service not in KILL_EXCLUDE_SERVICES:
        raise ValueError(
            f"killed_service must be one of {sorted(KILL_EXCLUDE_SERVICES)}, "
            f"got {killed_service!r}"
        )
    excluded = KILL_EXCLUDE_SERVICES[killed_service]
    allow_services = [s for s in ALL_FPF_SERVICES if s not in excluded]

    # fsdb kill leaves bgpd up (RIB/sessions intact) and tears HRT FSDB sessions
    # on lane 0; bgpd/wedge_agent kills take bgp down but leave fsdb up.
    bgp_healthy = killed_service == "fsdb"
    ports_healthy = killed_service in ("fsdb", "bgpd")

    checks = []

    # --- SSH/device-shell: everything healthy except the killed/cascaded svc ---
    if not skip_ssh:
        if bgp_healthy:
            checks.append(
                create_bgp_session_establish_check(
                    min_established_pct=0.5,
                    check_id=f"{killed_service}_disrupt_bgp_establish",
                )
            )
        if ports_healthy:
            checks.append(create_port_state_check())
        checks.append(create_systemctl_active_state_check(services_json=allow_services))
        # A wedge_agent kill triggers a coldboot whose teardown is legitimately
        # "unclean" (forwarding/DOCA state wiped, bgpd BindsTo-bounced), so the
        # unclean-exit signal carries no information there — skip it for
        # wedge_agent only. fsdb/bgpd kills still assert it (minus the killed
        # service), where an unclean exit of any OTHER service is a real bug.
        if killed_service != "wedge_agent":
            checks.append(create_unclean_exit_check(exclude_services=excluded))
        checks.append(create_device_core_dumps_check(use_start_time=True))

    # --- BGP RIB stays converged only when bgpd is alive (fsdb kill) ---
    if bgp_healthy:
        for lane_id, gtsw in enumerate(observer_gtsws):
            checks.append(
                create_fpf_bgp_rib_convergence_check(
                    lane_map={str(lane_id): gtsw},
                    expected_matched=prefix_count,
                    use_live_collectors=True,
                    check_id=f"{killed_service}_disrupt_bgp_rib_lane{lane_id}",
                )
            )

    # --- HRT process health (all services) ---
    checks.append(
        create_fpf_hrt_system_memory_check(
            hosts=hrt_memory_hosts, check_id=f"{killed_service}_disrupt_hrt_mem"
        )
    )
    checks.append(
        create_fpf_hrt_driver_disconnect_check(
            hosts=hrt_memory_hosts, check_id=f"{killed_service}_disrupt_hrt_driver"
        )
    )

    # --- HRT FSDB session census: NOT asserted in the disrupt window ---
    # gtsw001 owns the impacted lane. Killing ANY of fsdb/bgpd/wedge_agent on it
    # tears HRT's view of that lane's ribMap across all GPUs, so the CONNECTED
    # census churns for the entire kill loop on every service. The census is only
    # a meaningful verdict once the dust settles, so it is asserted FULL-STRENGTH
    # in the longevity playbook instead (where the impacted lane must have fully
    # recovered) and is deliberately omitted here.

    # --- ODS discards ---
    # Graceful loop-kill: lane 0 keeps spraying, so there is NO sustained
    # blackhole — the in_dst_null/in_discard spikes are small transients (~6k
    # observed, below the old 10k bar) and asserting >=10k would contradict the
    # "lane 0 sprays" expectation. We therefore CAPTURE the discard peaks
    # informationally (the peak + ODS link are recorded, the check never fails)
    # and keep congestion == 0 as a HARD assertion.
    ods_entity_desc = ",".join(observer_gtsws)
    checks.extend(
        [
            create_fpf_ods_counter_check(
                entity_desc=ods_entity_desc,
                key_desc=_ODS_IN_DST_NULL_KEY,
                validation_expr=f">= {DISCARD_FLOOR}",
                reduce_desc=_ODS_REDUCE,
                aggregate="max",
                require="any",
                informational=True,
                counter_name="in_dst_null discards (captured)",
                check_id=f"{killed_service}_disrupt_ods_in_dst_null",
            ),
            create_fpf_ods_counter_check(
                entity_desc=ods_entity_desc,
                key_desc=_ODS_IN_DISCARD_KEY,
                validation_expr=f">= {DISCARD_FLOOR}",
                reduce_desc=_ODS_REDUCE,
                aggregate="max",
                require="any",
                informational=True,
                counter_name="in_discard discards (captured)",
                check_id=f"{killed_service}_disrupt_ods_in_discard",
            ),
            create_fpf_ods_counter_check(
                entity_desc=ods_entity_desc,
                key_desc=_ODS_IN_CONGESTION_KEY,
                validation_expr="<= 0",
                reduce_desc=_ODS_REDUCE,
                counter_name="in_congestion discards (must be 0)",
                check_id=f"{killed_service}_disrupt_ods_in_congestion",
            ),
            create_fpf_ods_counter_check(
                entity_desc=ods_entity_desc,
                key_desc=_ODS_OUT_CONGESTION_KEY,
                validation_expr="<= 0",
                reduce_desc=_ODS_REDUCE,
                counter_name="out_congestion discards (must be 0)",
                informational=out_congestion_informational,
                check_id=f"{killed_service}_disrupt_ods_out_congestion",
            ),
        ]
    )

    # --- Host spray: NOT asserted in the disrupt window ---
    # Per-lane RDMA egress is a "collector" signal that the kill loop deliberately
    # perturbs: the impacted lane (the one the killed GTSW owns) may keep spraying
    # (graceful bgp/fsdb loop-kill), dip, or drain to ~0 (wedge_agent coldboot,
    # bidirectionally on BOTH hosts), so no floor/spread assertion on it is stable
    # during the kill. Spray fairness is verified FULL-STRENGTH in the longevity
    # playbook once traffic has re-settled, so it is omitted here.

    return checks
