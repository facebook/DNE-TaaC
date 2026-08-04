# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""Spec 2.9 — Edge Cases and Adversarial Scenarios. UG qualification playbook factories.

Implemented:
- 2.9.1 Best-Path Change During Active Distribution
- 2.9.2 Simultaneous Disruptions Across All Groups
- 2.9.3 NOTIFICATION Sent to One Peer -> Group Isolation
- 2.9.4 Dual-Stack Isolation: IPv4 Operations Do Not Affect IPv6 Group
- 2.9.6 Staggered Peer Startup: Peers Coming Up at Different Times
- 2.9.7 Empty Group, Last Peer Goes Down Without Detached Peers
- 2.9.8 Quantifying CPU Reduction from Update Group

Spec 2.9.5 is struck-through / excluded in the qualification plan.
"""

import typing as t

from taac.constants import OpenRRouteAction
from taac.health_checks.healthcheck_definitions import (
    create_bgp_session_establish_check,
    create_bgp_session_snapshot_check,
    create_bgp_update_group_check,
    create_device_core_dumps_check,
    create_log_parsing_check,
    create_memory_utilization_check,
    create_service_restart_check,
    create_system_cpu_load_average_check,
)
from taac.stages.stage_definitions import create_steps_stage
from taac.steps.step_definitions import (
    create_advertise_withdraw_prefixes_step,
    create_custom_step,
    create_ixia_api_step,
    create_longevity_step,
    create_openr_route_action_step,
    create_resume_bgp_keepalive_step,
    create_run_task_step,
    create_set_bgp_prefixes_local_preference_step,
    create_snapshot_bgp_dut_best_path_as_path_step,
    create_snapshot_bgp_peer_advertised_as_path_step,
    create_snapshot_bgp_sent_route_counts_step,
    create_start_stop_bgp_peers_step,
    create_stop_bgp_keepalive_step,
    create_validation_step,
    create_verify_bgp_advertised_nlris_step,
    create_verify_bgp_dut_best_path_as_path_converged_step,
    create_verify_bgp_notification_occurred_step,
    create_verify_bgp_peer_advertised_as_path_converged_step,
    create_verify_bgp_peers_joined_running_step,
    create_verify_bgp_sent_route_count_delta_step,
    create_verify_bgp_sent_route_counts_uniform_step,
)
from taac.testconfigs.routing.util.bgp_ebb_health_checks import (
    BGP_STANDARD_POSTCHECKS,
    BGP_STANDARD_SNAPSHOT_CHECKS,
)
from taac.test_as_a_config.types import (
    ConcurrentStep,
    Playbook,
    PointInTimeHealthCheck,
    SnapshotHealthCheck,
    Step,
)


# Crash gate for every UG edge-case stage: if an empty-group transition kills
# any of these, ``create_service_restart_check`` (no ``expected_restarted_services``
# -> asserts none restarted) fails the test. Same service/daemon set as
# ``create_standard_postchecks`` so empty-group churn is held to the same
# no-restart bar as the rest of the EBB suite.
_CRASH_GATE_SERVICES: t.List[str] = ["Bgp", "FibAgent", "FibAgentBgp"]
_CRASH_GATE_DAEMONS: t.List[str] = ["FibBgpGrpc"]


def _no_crash_checks() -> t.List[PointInTimeHealthCheck]:
    """No-crash gate: BGP/FIB daemons did not restart and no new core dumps."""
    return [
        create_service_restart_check(
            services=_CRASH_GATE_SERVICES,
            daemons=_CRASH_GATE_DAEMONS,
        ),
        create_device_core_dumps_check(),
    ]


def _flap_bgp_peers(*, peer_regex: str, start: bool, description: str):
    """Start/stop ALL sessions of every IXIA BGP peer matching ``peer_regex``.

    Empties / recovers update groups by bringing the IXIA-emulated peers' BGP
    SESSIONS down/up -- NOT by toggling their DeviceGroups. This is deliberate:

    - ``toggle_device_groups(enable=False)`` removes the whole emulated router
      and de-materializes its IXIA-imported route range (the eBGP prefixes come
      from a one-shot ``ImportBgpRoutes`` at setup). Nothing ever re-imports, so
      after recovery the peers advertise NOTHING and the DUT has no eBGP routes
      to redistribute to iBGP -- the recovery never actually re-syncs routes,
      and any distribution check (spec step 10) sees an empty dump.
    - ``start_bgp_peers`` only stops/starts the BGP protocol; the emulated
      routers and their imported route ranges stay materialized, so on ``start``
      the peers re-advertise their routes -- exactly what a real peer does when
      it flaps. This makes the recovery genuinely restore the route state (spec
      pass-criterion "full route re-sync") and lets step 10 verify distribution.
      It also matches the spec wording ("shut down ALL eBGP sessions").

    Omits the session indices so ``start_bgp_peers`` flaps each matched peer's
    FULL session range (the API defaults ``session_end_idx`` to each peer's own
    ``Count``); ``create_start_stop_bgp_peers_step`` can't express "all sessions"
    across peers with differing session counts, hence the direct API step.
    """
    return create_ixia_api_step(
        api_name="start_bgp_peers",
        args_dict={"start": start, "regex": peer_regex},
        description=description,
    )


def create_bgp_ug_empty_group_playbook(
    *,
    device_name: str,
    ebgp_peer_regex: str,
    ibgp_peer_regex: str,
    ibgp_v6_peer_group: str,
    ebgp_v6_peer_group: str,
    prechecks: t.List[PointInTimeHealthCheck],
    postchecks: t.Optional[t.List[PointInTimeHealthCheck]] = None,
    snapshot_checks: t.Optional[t.List[SnapshotHealthCheck]] = None,
    bgp_mon_ignore_prefixes: t.Optional[t.List[str]] = None,
    non_ebgp_parent_prefixes: t.Optional[t.List[str]] = None,
    # Spec step 3 (iBGP keeps functioning while eBGP is empty): inject
    # ``inject_route_count`` iBGP routes (withdraw then re-advertise) from this
    # prefix pool. None -> skip the injection.
    ibgp_inject_pool_regex: t.Optional[str] = None,
    inject_route_count: int = 100,
    # Spec step 10 (full initial dump + distribution on recovery): the on-wire
    # tcpdump dump-compare -- the only view that proves identical path ATTRIBUTES
    # (the thrift NLRI view via ``recovery_ibgp_ug_parent_prefixes`` is
    # prefix-level). All three required to run. (Pre-fix binary read
    # postpolicy_sent_prefix_count = 0 under UG, T271301144, so the wire dump was
    # once the ONLY per-peer signal; the fixed binary populates the thrift views.)
    ibgp_dump_capture_interface: t.Optional[str] = None,
    ibgp_dump_peer_regex: t.Optional[str] = None,
    ibgp_dump_session_indices: t.Optional[t.List[int]] = None,
    dump_capture_duration_s: int = 300,
    dump_settle_s: int = 10,
    settle_after_flap_s: int = 90,
    ebgp_empty_soak_s: int = 300,
    all_empty_soak_s: int = 120,
    recovery_convergence_s: int = 240,
    recovery_session_retry_count: int = 10,
    recovery_session_retry_delay_s: float = 30.0,
    # Spec step 8 fidelity ("bring peers back up") + pass-criterion "full route
    # re-sync": IXIA does NOT re-advertise the one-shot ``ImportBgpRoutes``-imported
    # eBGP prefixes when a session comes back up, so after recovery the DUT would
    # relearn 0 eBGP routes (recovery re-establishes sessions but never re-syncs
    # routes -- and spec step 10's distribution check then sees an empty dump).
    # When set, withdraw then re-advertise this eBGP prefix pool at recovery to
    # force IXIA to re-send the imported routes -- emulating what a real eBGP peer
    # does on flap. None -> skip (topologies where session-up re-advertises).
    ebgp_prefix_pool_regex: t.Optional[str] = None,
    recovery_readvertise_settle_s: int = 30,
    # Spec pass-criterion "groups re-created correctly" + "no stale group
    # entries": when set, assert the TOTAL update-group count on recovery equals
    # the pre-test baseline (records the baseline count per spec pre-condition 3
    # and proves no orphaned/leftover empty group survived the empty-group
    # period -- a count above baseline would mean a stale group). None -> skip.
    expected_recovered_group_count: t.Optional[int] = None,
    # Spec pass-criterion "VmHWM below 10 GB": when set, append a postcheck
    # asserting the BGP++ (bgpcpp) process VmHWM stays below this many bytes.
    # Reads /proc/<pid>/status on Arista (the standard memory check only samples
    # RSS deltas there and cannot assert an absolute peak). None -> skip.
    vmhwm_threshold_bytes: t.Optional[int] = None,
    # Spec step 10 ("all peers received full initial dump + distribution works"):
    # the iBGP update group's peers. When set, after recovery converges, assert
    # every peer has a NON-ZERO UNIFORM sent-count AND all advertise the IDENTICAL
    # NLRI set -- extends the two-peer dump-compare to ALL members. None -> only the
    # two-peer wire dump-compare runs. Scope to ONE update group (so identity holds).
    recovery_ibgp_ug_parent_prefixes: t.Optional[t.List[str]] = None,
) -> Playbook:
    """Build the BGP++ Update Group qualification 2.9.7 playbook
    (Empty Group — Last Peer Goes Down Without Detached Peers).

    Intent (spec 2.9.7): shutting every peer in a group (empty group), and
    then every peer in every group, must not crash the BGP daemon; the
    update groups must re-form cleanly on recovery with no stale routes.

    Flow — the groups are emptied / recovered by STOPPING and STARTING the
    IXIA-emulated peers' BGP SESSIONS (``start_bgp_peers``), NOT by toggling
    their DeviceGroups. See ``_flap_bgp_peers`` for the full rationale: session
    stop/start leaves the imported eBGP route ranges materialized, so recovery
    genuinely re-syncs routes (DeviceGroup toggling de-materializes them and the
    recovery would advertise nothing, defeating spec step 10). It also matches
    the spec wording ("shut down ALL eBGP sessions"). ``settle_after_flap_s``
    gives the DUT time to tear the sessions down and empty the groups after each
    stop (90s default, ample for the EBB hold-times):

      1. Empty the eBGP update group: stop ALL eBGP BGP sessions
         (``ebgp_peer_regex``). Settle, then verify
         no crash; the eBGP sessions actually went down (0 eBGP Established --
         a non-vacuous guard against a mis-matched regex, when
         ``non_ebgp_parent_prefixes`` is supplied); the eBGP UPDATE GROUP
         itself emptied on the device (``expect_empty_peer_groups`` -- spec
         "group with zero members"); AND the iBGP update group is still
         enabled/formed (isolation -- emptying one group must not disturb the
         others).
      2. Soak with the eBGP group empty (spec step 4: default 5 minutes).
      3. Empty ALL groups: stop ALL iBGP BGP sessions too
         (``ibgp_peer_regex``). Every update group is now empty (the "last
         peer goes down" condition). Verify no crash; 0 sessions Established
         (excluding BGP-MON); AND both update groups empty on the device
         (``expect_empty_peer_groups`` for eBGP + iBGP).
      4. Soak with all groups empty (spec step 7: default 2 minutes).
      5. Recover: start ALL eBGP then ALL iBGP BGP sessions, then (if
         ``ebgp_prefix_pool_regex`` is set) withdraw + re-advertise the eBGP
         prefix pool so IXIA actually re-sends the imported eBGP routes -- a bare
         session-up does NOT re-advertise them, so without this the DUT relearns
         0 eBGP routes and recovery re-syncs nothing. Then wait
         ``recovery_convergence_s`` for the ~640-session topology to begin
         re-establishing, then verify no crash, the update groups re-formed
         (eBGP + iBGP), and sessions re-established. When
         ``expected_recovered_group_count`` is supplied, ALSO assert the total
         update-group count returned to the pre-test baseline (spec: groups
         re-created correctly, no stale/orphaned groups left from the empty
         period). The session-establish check retries
         (``recovery_session_retry_*``) to absorb full-scale re-convergence
         timing. "No stale routes" is asserted by the postchecks
         (``BGP_STANDARD_POSTCHECKS``), which run after the full 600s
         convergence budget rather than at this mid-test point.

    Spec step 3 (``ibgp_inject_pool_regex``): between stages 1 and 2, inject
    ``inject_route_count`` iBGP routes (withdraw then re-advertise) as CHURN and
    re-check the iBGP update group -- verifies the iBGP UG keeps functioning while
    the eBGP group is empty. Per-member distribution is NOT asserted at step 3: with
    the eBGP group empty the DUT has nothing to distribute to the other iBGP peers
    (no eBGP-origin routes, and member-originated iBGP routes are not re-advertised
    within the group), so every other iBGP peer legitimately receives 0. Distribution
    is verified at step 10 instead. Spec step 10: two complementary views --
    (a) when ``recovery_ibgp_ug_parent_prefixes`` is set, an ALL-members thrift
    view after recovery (every iBGP peer non-zero + uniform sent-count AND
    identical advertised NLRIs), and (b) the ``ibgp_dump_*`` tcpdump dump-compare
    asserting two iBGP peers in one update group receive identical UPDATEs on the
    wire -- the only view that also proves identical path ATTRIBUTES (the thrift
    NLRI view is prefix-level). The dump-compare cold-starts ONLY the iBGP sink
    peers (``flap_peer_regex`` = the dump peer set) so the eBGP route sources stay
    up and the DUT still holds the routes to dump; it flaps those peers, so it
    runs LAST (after the all-members view). All are skipped if their params are
    omitted. (The per-peer thrift views read the PS gauge +
    getPostfilterAdvertisedNetworks, populated under UG on the fixed binary --
    T271301144/T281417842; the earlier "vacuous/gauge reads 0" was the pre-fix
    binary, which is why distribution used to be wire-only.)

    ``bgp_mon_ignore_prefixes`` (if the testbed has BGP-MON peers configured
    on the device that IXIA does not emulate) is threaded into the session
    checks so those intentionally-down peers do not fail them.

    ``non_ebgp_parent_prefixes`` (the iBGP + BGP-MON parent networks) scopes
    the Stage-1 "eBGP actually emptied" assertion to eBGP-only. If omitted,
    that assertion is skipped (the Stage-3 all-empty assertion still proves
    the toggles took effect). See spec 2.9.7 in the qualification plan.
    """
    # Stage-1 checks: no crash + iBGP update group still formed (isolation).
    # When the caller supplies ``non_ebgp_parent_prefixes`` we ALSO assert the
    # eBGP group actually emptied (0 eBGP sessions Established, scoped to eBGP by
    # ignoring every non-eBGP parent). Without this, a mis-matched DeviceGroup
    # regex would make the whole test pass vacuously.
    ebgp_emptied_checks: t.List[PointInTimeHealthCheck] = [
        *_no_crash_checks(),
        # One UG check asserts BOTH: the iBGP update group is still formed
        # (isolation) AND the eBGP update group itself emptied -- 0 Established
        # members / cleaned up (spec 2.9.7 "group with zero members" +
        # pass-criterion "no stale group entries or orphaned state").
        create_bgp_update_group_check(
            expect_enabled=True,
            peer_group_substrings=[ibgp_v6_peer_group],
            expect_empty_peer_groups=[ebgp_v6_peer_group],
            check_id="empty_group_ebgp_ug_empty_ibgp_ug_intact",
        ),
    ]
    if non_ebgp_parent_prefixes is not None:
        ebgp_emptied_checks.append(
            create_bgp_session_establish_check(
                expected_established_sessions=0,
                parent_prefixes_to_ignore=non_ebgp_parent_prefixes,
                check_id="empty_group_ebgp_sessions_down",
            )
        )

    # Stage-3 checks: no crash + assert EVERY group is empty (the "last peer
    # goes down" condition): 0 Established sessions, ignoring only BGP-MON
    # (never emulated by IXIA under UG). This is the primary non-vacuous guard --
    # it fails if either the eBGP or the iBGP toggle did not take effect.
    all_empty_checks: t.List[PointInTimeHealthCheck] = [
        *_no_crash_checks(),
        create_bgp_session_establish_check(
            expected_established_sessions=0,
            parent_prefixes_to_ignore=bgp_mon_ignore_prefixes,
            check_id="empty_group_all_sessions_down",
        ),
        # Both update groups empty on the UG object too (spec 2.9.7 "ALL groups
        # are empty"): neither peer-group maps to an update group with an
        # Established member.
        create_bgp_update_group_check(
            expect_enabled=True,
            expect_empty_peer_groups=[ebgp_v6_peer_group, ibgp_v6_peer_group],
            check_id="empty_group_all_ugs_empty",
        ),
    ]

    # --- Spec step 3: verify the iBGP update group keeps FUNCTIONING while the eBGP
    # group is empty. Inject (withdraw then re-advertise) iBGP routes as CHURN, then
    # re-check the iBGP UG is still formed + no crash. Per-member distribution is NOT
    # asserted at step 3: with eBGP empty the DUT has no eBGP-origin routes to
    # distribute and does not re-advertise member-originated iBGP routes within the
    # group (no RR fan-out for that path), so every other iBGP peer legitimately
    # receives 0 (HW 2026-08-01: all 434 sinks = 0). Distribution is verified at
    # step 10 (post-recovery, eBGP-origin -> iBGP, where it genuinely happens). ---
    step3_stage = None
    if ibgp_inject_pool_regex is not None:
        step3_steps: t.List[Step] = [
            create_advertise_withdraw_prefixes_step(
                device_name=device_name,
                advertise=False,
                prefix_pool_regex=ibgp_inject_pool_regex,
                prefix_start_index=0,
                prefix_end_index=inject_route_count,
                description=(
                    f"2.9.7 step 3 -- withdraw {inject_route_count} iBGP "
                    "routes while the eBGP group is empty"
                ),
            ),
            create_longevity_step(
                duration=settle_after_flap_s,
                description="2.9.7 step 3 -- settle after withdraw",
            ),
            create_advertise_withdraw_prefixes_step(
                device_name=device_name,
                advertise=True,
                prefix_pool_regex=ibgp_inject_pool_regex,
                prefix_start_index=0,
                prefix_end_index=inject_route_count,
                description=(
                    f"2.9.7 step 3 -- inject (re-advertise) "
                    f"{inject_route_count} iBGP routes"
                ),
            ),
            create_longevity_step(
                duration=settle_after_flap_s,
                description="2.9.7 step 3 -- settle after inject",
            ),
        ]
        # NOTE: step 3's "verify distribution within the iBGP group" is NOT asserted
        # here. At step 3 the eBGP group is empty, so the DUT has no eBGP-origin
        # routes to distribute AND it does not re-advertise member-originated iBGP
        # routes to the other iBGP peers (no route-reflector fan-out for that path) --
        # so every other iBGP peer legitimately receives 0 at this point (HW
        # 2026-08-01: all 434 sink peers = 0). The inject here therefore serves as
        # CHURN that verifies the iBGP UG keeps FUNCTIONING while the eBGP group is
        # empty (group stays formed, route churn accepted, no crash). Actual
        # per-member distribution is verified at step 10 (post-recovery, eBGP-origin
        # -> iBGP, where distribution genuinely happens).
        step3_steps.append(
            create_validation_step(
                point_in_time_checks=[
                    *_no_crash_checks(),
                    create_bgp_update_group_check(
                        expect_enabled=True,
                        peer_group_substrings=[ibgp_v6_peer_group],
                        check_id="empty_group_step3_ibgp_functions",
                    ),
                ],
                description=(
                    "2.9.7 step 3 -- iBGP update group continues to function "
                    "under eBGP-empty (route churn accepted, group formed, "
                    "no crash)"
                ),
            )
        )
        step3_stage = create_steps_stage(steps=step3_steps)

    # --- Spec step 10: verify all peers received the full initial dump + route
    # distribution on recovery. The tcpdump dump-compare cold-starts BGP and
    # asserts two iBGP peers in the same update group receive IDENTICAL UPDATEs
    # (NLRI + attributes) -- the only UG-immune per-peer distribution check. It
    # cold-starts, so it runs LAST (after the empty-group recovery). ---
    step10_stage = None
    if (
        ibgp_dump_peer_regex is not None
        and ibgp_dump_capture_interface is not None
        and ibgp_dump_session_indices is not None
    ):
        step10_stage = create_steps_stage(
            steps=[
                create_custom_step(
                    params_dict={
                        "custom_step_name": "test_bgp_update_group_dump_compare",
                        "hostname": device_name,
                        "ixia_capture_interface": ibgp_dump_capture_interface,
                        "ibgp_peer_regex": ibgp_dump_peer_regex,
                        "ibgp_peer_session_indices": list(ibgp_dump_session_indices),
                        "capture_duration_seconds": dump_capture_duration_s,
                        "settle_seconds": dump_settle_s,
                        # Flap ONLY the iBGP sink peers, NOT the whole layer:
                        # bouncing eBGP would strip the DUT's imported eBGP RIB
                        # (never re-advertised on session-up) and yield an empty
                        # dump. Keeping eBGP up means the re-establishing iBGP
                        # peers get a real, non-empty initial dump to compare.
                        "flap_peer_regex": ibgp_dump_peer_regex,
                    },
                    description=(
                        "2.9.7 step 10 -- verify full initial dump: two iBGP peers "
                        "in the same update group receive identical UPDATEs "
                        "(distribution correct after recovery)"
                    ),
                ),
            ],
        )

    # Spec step 8 + "full route re-sync": force IXIA to re-advertise the imported
    # eBGP routes at recovery (session-up alone does not re-send them). Withdraw
    # then re-advertise creates the per-prefix Active False->True transition that
    # makes IXIA re-flood the persisted imported eBGP pool, so the DUT relearns
    # its eBGP RIB and can redistribute to iBGP (spec step 10). Empty if the
    # caller does not configure a pool (e.g. session-up re-advertises natively).
    recovery_readvertise_steps = []
    if ebgp_prefix_pool_regex is not None:
        recovery_readvertise_steps = [
            create_advertise_withdraw_prefixes_step(
                device_name=device_name,
                advertise=False,
                prefix_pool_regex=ebgp_prefix_pool_regex,
                prefix_start_index=0,
                description=(
                    "2.9.7 recovery -- withdraw eBGP prefixes (forces the Active "
                    "transition so the following re-advertise actually re-sends)"
                ),
            ),
            create_longevity_step(
                duration=recovery_readvertise_settle_s,
                description="2.9.7 recovery -- settle before re-advertising eBGP",
            ),
            create_advertise_withdraw_prefixes_step(
                device_name=device_name,
                advertise=True,
                prefix_pool_regex=ebgp_prefix_pool_regex,
                prefix_start_index=0,
                description=(
                    "2.9.7 recovery -- re-advertise ALL eBGP prefixes so the DUT "
                    "relearns its eBGP RIB (IXIA does not re-advertise imported "
                    "routes on session-up); enables full re-sync + step 10 dump"
                ),
            ),
        ]

    # --- Spec step 10 (all-peers view): after recovery converges, assert every
    # peer in the iBGP update group received the full re-synced distribution -- a
    # NON-ZERO UNIFORM sent-count AND an IDENTICAL per-peer advertised NLRI set
    # across ALL members (the thrift all-peers analog of the two-peer wire
    # dump-compare, which only samples a pair). Runs AFTER recovery converges and
    # BEFORE step 10's dump-compare (which cold-starts/flaps the sink peers).
    # UG-safe reads on the fixed binary (T271301144/T281417842). ---
    recovery_dist_stage = None
    if recovery_ibgp_ug_parent_prefixes is not None:
        recovery_dist_stage = create_steps_stage(
            steps=[
                create_verify_bgp_sent_route_counts_uniform_step(
                    hostname=device_name,
                    peer_parent_prefixes=recovery_ibgp_ug_parent_prefixes,
                    min_count=1,
                    max_spread=0,
                    description=(
                        "2.9.7 step 10 -- every iBGP peer has a NON-ZERO, UNIFORM "
                        "sent-count after recovery (all members received the full "
                        "dump)"
                    ),
                ),
                create_verify_bgp_advertised_nlris_step(
                    hostname=device_name,
                    peer_parent_prefixes=recovery_ibgp_ug_parent_prefixes,
                    min_count=1,
                    require_identical=True,
                    description=(
                        "2.9.7 step 10 -- every iBGP peer advertises the IDENTICAL "
                        "post-recovery NLRI set (UG distribution correct, all "
                        "members)"
                    ),
                ),
            ],
        )

    stages = [
        # 1. Empty the eBGP update group.
        create_steps_stage(
            steps=[
                _flap_bgp_peers(
                    peer_regex=ebgp_peer_regex,
                    start=False,
                    description=(
                        "2.9.7 -- stop ALL eBGP BGP sessions (empty the eBGP "
                        "update group; routes stay materialized for recovery)"
                    ),
                ),
                create_longevity_step(
                    duration=settle_after_flap_s,
                    description="2.9.7 -- settle after stopping eBGP sessions",
                ),
                create_validation_step(
                    point_in_time_checks=ebgp_emptied_checks,
                    description=(
                        "2.9.7 -- eBGP group emptied: no crash; eBGP sessions "
                        "down; iBGP update group still enabled/formed (isolation)"
                    ),
                ),
            ],
        ),
        # 2. Soak with the eBGP group empty.
        create_steps_stage(
            steps=[
                create_longevity_step(
                    duration=ebgp_empty_soak_s,
                    description=(
                        "2.9.7 step 4 -- soak (default 5 min) with the eBGP "
                        "update group empty, iBGP groups active"
                    ),
                ),
            ],
        ),
        # 3. Empty ALL groups (last peer down across every group).
        create_steps_stage(
            steps=[
                _flap_bgp_peers(
                    peer_regex=ibgp_peer_regex,
                    start=False,
                    description=(
                        "2.9.7 -- stop ALL iBGP BGP sessions (all update "
                        "groups now empty -- last peer goes down)"
                    ),
                ),
                create_longevity_step(
                    duration=settle_after_flap_s,
                    description="2.9.7 -- settle after stopping iBGP sessions",
                ),
                create_validation_step(
                    point_in_time_checks=all_empty_checks,
                    description=(
                        "2.9.7 -- all update groups empty (last peer down): no "
                        "crash; 0 sessions Established (excl BGP-MON)"
                    ),
                ),
            ],
        ),
        # 4. Soak fully empty.
        create_steps_stage(
            steps=[
                create_longevity_step(
                    duration=all_empty_soak_s,
                    description=(
                        "2.9.7 step 7 -- soak (default 2 min) with all update "
                        "groups empty"
                    ),
                ),
            ],
        ),
        # 5. Recover eBGP then iBGP and verify re-formation.
        create_steps_stage(
            steps=[
                _flap_bgp_peers(
                    peer_regex=ebgp_peer_regex,
                    start=True,
                    description=(
                        "2.9.7 -- start ALL eBGP BGP sessions (re-advertise the "
                        "still-materialized eBGP routes for redistribution)"
                    ),
                ),
                _flap_bgp_peers(
                    peer_regex=ibgp_peer_regex,
                    start=True,
                    description="2.9.7 -- start ALL iBGP BGP sessions",
                ),
                # Force IXIA to re-advertise the imported eBGP routes now that the
                # eBGP sessions are back up (session-up alone does not re-send
                # them) -- otherwise the DUT relearns nothing and recovery is a
                # no-op for routes. No-op when ebgp_prefix_pool_regex is unset.
                *recovery_readvertise_steps,
                create_longevity_step(
                    duration=recovery_convergence_s,
                    description=(
                        "2.9.7 -- allow sessions to re-establish and update "
                        "groups to re-form"
                    ),
                ),
                create_validation_step(
                    point_in_time_checks=[
                        *_no_crash_checks(),
                        create_bgp_update_group_check(
                            expect_enabled=True,
                            peer_group_substrings=[
                                ibgp_v6_peer_group,
                                ebgp_v6_peer_group,
                            ],
                            # Assert the total update-group count returned to the
                            # pre-test baseline (spec: groups re-created correctly,
                            # no stale/orphaned groups). No-op when the caller does
                            # not supply a baseline count.
                            expected_group_count=expected_recovered_group_count,
                            check_id="empty_group_recovery_ug_reformed",
                        ),
                        # Retries absorb full-scale (~640-session) re-convergence
                        # timing. "No stale routes" is left to the postchecks,
                        # which run after the full convergence budget rather than
                        # at this mid-test point.
                        create_bgp_session_establish_check(
                            parent_prefixes_to_ignore=bgp_mon_ignore_prefixes,
                            retry_count=recovery_session_retry_count,
                            retry_delay_seconds=recovery_session_retry_delay_s,
                            check_id="empty_group_recovery_sessions_reestablished",
                        ),
                    ],
                    description=(
                        "2.9.7 -- recovery: no crash, update groups re-formed "
                        "(eBGP + iBGP), sessions re-established"
                    ),
                ),
            ],
        ),
    ]
    # Step 3 runs during the eBGP-empty window (after Stage 1, before the 5-min
    # soak); step 10 runs last (after recovery, since it cold-starts BGP).
    if step3_stage is not None:
        stages.insert(1, step3_stage)
    # All-peers distribution view runs after recovery (last base stage) and before
    # the dump-compare, which flaps the sink peers.
    if recovery_dist_stage is not None:
        stages.append(recovery_dist_stage)
    if step10_stage is not None:
        stages.append(step10_stage)

    # The two UG-specific bounds the spec calls out (load-average never crosses
    # 12; update group enabled) are ALWAYS appended -- whether the caller takes
    # the default ``BGP_STANDARD_POSTCHECKS`` bundle or supplies its own list --
    # so a caller-provided ``postchecks`` can never silently drop them.
    base_postchecks = (
        list(postchecks) if postchecks is not None else list(BGP_STANDARD_POSTCHECKS)
    )
    postchecks = base_postchecks + [
        create_system_cpu_load_average_check(baseline=12.0),
        create_bgp_update_group_check(expect_enabled=True),
    ]
    # Spec pass-criterion "VmHWM below 10 GB" -- the standard postcheck memory
    # check SKIPs on Arista (RSS-delta only), so add an explicit absolute-VmHWM
    # postcheck when the caller supplies a ceiling.
    if vmhwm_threshold_bytes is not None:
        postchecks.append(
            create_memory_utilization_check(vmhwm_threshold=vmhwm_threshold_bytes)
        )
    if snapshot_checks is None:
        snapshot_checks = list(BGP_STANDARD_SNAPSHOT_CHECKS)

    return Playbook(
        # Generic, DUT-agnostic name -- device scope lives in the surrounding
        # TestConfig (e.g. ``BAG013_ASH6_BGP_UG_EDGE_CASES_TEST``).
        name="bgp_ug_empty_group",
        stages=stages,
        prechecks=prechecks,
        postchecks=postchecks,
        snapshot_checks=snapshot_checks,
    )


# =============================================================================
# 2.9.2 Simultaneous Disruptions Across All Groups
# =============================================================================
#
# The spec runs FOUR disruption types concurrently for 30 minutes -- eBGP route
# churn (with varying communities), random eBGP session flaps (without graceful
# restart), IGP-metric instability via Open/R, and iBGP LOCAL_PREF churn -- while
# monitoring that the iBGP update group stays stable (sessions Established, no
# crash, CPU/load bounded), then stops everything, waits for convergence, and
# verifies recovery + a bounded VmHWM growth. Modeled as ONE concurrent
# ``create_steps_stage`` with one ``ConcurrentStep`` per disruption track plus a
# monitor track and a spanning VmHWM-growth track (each ConcurrentStep is an
# independent asyncio task; the stage ends when the longest finishes), followed by
# a sequential convergence-verify stage. Each track's total sleep sums to
# ~``disruption_duration_s`` so the whole stage runs for the intended window.
#
# Distribution/route-count verification (spec pass-criterion 3) is intentionally
# NOT asserted: adj-RIB-out is vacuous under UG (T271301144) and the DUT
# advertises 0 on this topology pending a DNE egress-policy answer, so the
# landable substance here is stability (no crash, iBGP stays up, CPU/mem/load
# bounded) -- which is exactly what 2.9.2 stresses, and it directly exercises the
# known cross-group bugs T275928998 / T264949859.


def _route_churn_track_steps(
    *,
    device_name: str,
    route_count: int,
    interval_s: int,
    duration_s: int,
    prefix_pool_regex: t.Optional[str] = None,
    community_values: t.Optional[t.List[str]] = None,
    variant_pool_regexes: t.Optional[t.List[str]] = None,
) -> t.List[Step]:
    """Track: every ``interval_s`` withdraw + re-advertise ``route_count`` eBGP
    routes. Two modes:

    - 2.9.2 legacy (``prefix_pool_regex`` + ``community_values``): each cycle
      rotate the community on the single eBGP pool via ``ixia_modify_communities``
      (which bounces the owning peer) then withdraw -> wait -> re-advertise.

    - 2.9.8 Option-A (``variant_pool_regexes``, ordered A/B/C): each cycle withdraw
      the currently-active pre-staged variant pool and advertise the NEXT one,
      rotating A->B->C->A. Each variant carries a DIFFERENT community set at BUILD
      time (RouteScale.bgp_communities), so the DUT sees the same NLRI re-advertised
      with a modified community every cycle with NO runtime community write (which
      IxNetwork rejects on a started element -- the run-2 failure) and NO peer
      bounce -- only the proven Active-flag toggle runs. Exactly one variant pool
      is Active at a time: the playbook's prime stage leaves ``variant[0]`` active
      before this rotation starts, and each cycle withdraws the active pool before
      advertising the next (never two same-NLRI pools active at once).
    """
    steps: t.List[Step] = []
    iterations = max(1, duration_s // interval_s)
    half = max(1, interval_s // 2)

    if variant_pool_regexes is not None:
        assert len(variant_pool_regexes) >= 2, (
            "2.9.8 variant rotation needs >= 2 pre-staged pools so the community "
            "changes each cycle"
        )
        n = len(variant_pool_regexes)
        # variant[0] is Active coming in (the playbook prime stage). Each cycle:
        # withdraw the active pool -> wait -> advertise the next (a DIFFERENT
        # build-time community). Exactly one variant Active throughout.
        active_idx = 0
        for i in range(iterations):
            cur = variant_pool_regexes[active_idx]
            nxt = variant_pool_regexes[(active_idx + 1) % n]
            steps.extend(
                [
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=False,
                        prefix_pool_regex=cur,
                        prefix_start_index=0,
                        # None -> toggle the whole (multiplier=1) pool. route_count
                        # is the pool size, used only for the readable count; a
                        # numeric end-index would be a no-op for multiplier=1 pools.
                        prefix_end_index=None,
                        description=(
                            f"route churn -- withdraw {route_count} eBGP routes "
                            f"({cur}) (cycle {i + 1}/{iterations})"
                        ),
                    ),
                    create_longevity_step(duration=half),
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=True,
                        prefix_pool_regex=nxt,
                        prefix_start_index=0,
                        prefix_end_index=None,
                        description=(
                            f"route churn -- re-advertise {route_count} eBGP routes "
                            f"with modified community ({nxt}) "
                            f"(cycle {i + 1}/{iterations})"
                        ),
                    ),
                    create_longevity_step(duration=interval_s - half),
                ]
            )
            active_idx = (active_idx + 1) % n
        return steps

    # 2.9.2 legacy community-rotate-then-churn (byte-identical to the original).
    assert prefix_pool_regex is not None and community_values is not None, (
        "legacy route churn requires prefix_pool_regex + community_values"
    )
    for i in range(iterations):
        community = community_values[i % len(community_values)]
        steps.extend(
            [
                # Rotate the community on the eBGP pool -- peer-scoped modify (only
                # the owning peer restarts, no chassis-wide cascade); the tc3
                # backpressure pattern (count=0 + broadcast_to_all_slots).
                create_run_task_step(
                    task_name="ixia_modify_communities",
                    params_dict={
                        "prefix_pool_regex": prefix_pool_regex,
                        "count": 0,
                        "to_add": True,
                        "community_values": [community],
                        "broadcast_to_all_slots": True,
                    },
                    description=(
                        f"2.9.2 route churn -- set community {community} on "
                        f"{prefix_pool_regex} (cycle {i + 1}/{iterations})"
                    ),
                    ixia_needed=True,
                ),
                create_advertise_withdraw_prefixes_step(
                    device_name=device_name,
                    advertise=False,
                    prefix_pool_regex=prefix_pool_regex,
                    prefix_start_index=0,
                    prefix_end_index=route_count,
                    description=(
                        f"2.9.2 route churn -- withdraw {route_count} eBGP routes "
                        f"(cycle {i + 1}/{iterations})"
                    ),
                ),
                create_longevity_step(duration=half),
                create_advertise_withdraw_prefixes_step(
                    device_name=device_name,
                    advertise=True,
                    prefix_pool_regex=prefix_pool_regex,
                    prefix_start_index=0,
                    prefix_end_index=route_count,
                    description=(
                        f"2.9.2 route churn -- re-advertise {route_count} eBGP "
                        f"routes (cycle {i + 1}/{iterations})"
                    ),
                ),
                create_longevity_step(duration=interval_s - half),
            ]
        )
    return steps


def _variant_pool_prime_steps(
    *,
    device_name: str,
    variant_pool_regexes: t.List[str],
) -> t.List[Step]:
    """Bring the pre-staged variant pools to a SINGLE-active baseline (only
    ``variant_pool_regexes[0]`` Active) before the measured churn. All variant
    pools come up Active at build and share identical NLRI, so if left as-is the
    DUT sees the same NLRI advertised by every pool at once (ambiguous
    last-writer-wins community).

    Withdraw EVERY variant first (including ``variant[0]``), THEN advertise only
    ``variant[0]``. Doing variant[0] via an explicit inactive->active transition
    (rather than just leaving its build-time Active state) forces a guaranteed
    fresh re-advertise, so the single-active baseline holds regardless of
    IxNetwork's overlapping-same-NLRI withdraw semantics (an "assert variant[0]
    active" on an already-Active pool would be a no-op). ``prefix_end_index=None``
    toggles the whole (multiplier=1) pool."""
    steps: t.List[Step] = []
    # 1) Clean slate: withdraw ALL variants so no same-NLRI pool is left active.
    for regex in variant_pool_regexes:
        steps.append(
            create_advertise_withdraw_prefixes_step(
                device_name=device_name,
                advertise=False,
                prefix_pool_regex=regex,
                prefix_start_index=0,
                prefix_end_index=None,
                description=f"churn prime -- withdraw variant {regex} (clean slate)",
            )
        )
    # 2) Advertise exactly variant[0] -> a guaranteed inactive->active re-send.
    steps.append(
        create_advertise_withdraw_prefixes_step(
            device_name=device_name,
            advertise=True,
            prefix_pool_regex=variant_pool_regexes[0],
            prefix_start_index=0,
            prefix_end_index=None,
            description=(
                f"churn prime -- advertise variant {variant_pool_regexes[0]} "
                f"(single-active baseline)"
            ),
        )
    )
    return steps


def _session_flap_track_steps(
    *,
    ebgp_flap_peer_regex: str,
    random_session_num: int,
    interval_s: int,
    duration_s: int,
) -> t.List[Step]:
    """Track: every ``interval_s`` flap ``random_session_num`` RANDOM eBGP
    sessions (Stop/Start; the eBGP peers are built GR-off so this is a flap
    "without graceful restart" per spec). ``ixia_restart_bgp_sessions`` is the
    only random-subset flap primitive (random.sample of the matched sessions)."""
    steps: t.List[Step] = []
    iterations = max(1, duration_s // interval_s)
    for i in range(iterations):
        steps.extend(
            [
                create_run_task_step(
                    task_name="ixia_restart_bgp_sessions",
                    params_dict={
                        "bgp_peer_regex": ebgp_flap_peer_regex,
                        "random_session_num": random_session_num,
                    },
                    description=(
                        f"2.9.2 session flap -- restart {random_session_num} "
                        f"random eBGP sessions (cycle {i + 1}/{iterations})"
                    ),
                    ixia_needed=True,
                ),
                create_longevity_step(duration=interval_s),
            ]
        )
    return steps


def _attribute_churn_track_steps(
    *,
    ibgp_prefix_pool_regex: str,
    route_count: int,
    local_pref_low: int,
    local_pref_high: int,
    interval_s: int,
    duration_s: int,
) -> t.List[Step]:
    """Track: every ``interval_s`` toggle LOCAL_PREF on ``route_count`` iBGP
    routes between two values (spec 2.9.2 attribute churn -- best-path flips)."""
    steps: t.List[Step] = []
    iterations = max(1, duration_s // interval_s)
    for i in range(iterations):
        lp = local_pref_high if i % 2 == 0 else local_pref_low
        steps.extend(
            [
                create_set_bgp_prefixes_local_preference_step(
                    prefix_pool_regex=ibgp_prefix_pool_regex,
                    local_pref_value=lp,
                    prefix_start_index=0,
                    prefix_end_index=route_count,
                    description=(
                        f"2.9.2 attribute churn -- set LOCAL_PREF={lp} on "
                        f"{route_count} iBGP routes (cycle {i + 1}/{iterations})"
                    ),
                ),
                create_longevity_step(duration=interval_s),
            ]
        )
    return steps


def _monitor_track_steps(
    *,
    non_ibgp_parent_prefixes: t.List[str],
    load_avg_baseline: float,
    interval_s: int,
    duration_s: int,
    retry_count: int,
    retry_delay_s: float,
) -> t.List[Step]:
    """Track: every ``interval_s`` assert -- throughout the disruption -- that no
    BGP daemon crashed, the iBGP sessions stay Established (eBGP is intentionally
    flapping, so scope to iBGP by ignoring eBGP + BGP-MON parents), and the system
    load-average stays under baseline (spec 2.9.2 monitoring + pass-criteria 1/2/6).

    Device-CPU health is asserted via the system load-average (the correct EOS
    device signal). A per-process bgpcpp CPU% gate was intentionally NOT used: the
    ``bgpd.process.cpu.percent`` counter is per-process and routinely reads >100%
    (~1 core) under this churn, so it is not the spec's device-level "CPU < 40%"
    and mis-fires; load-average is the meaningful EOS device-CPU signal."""
    steps: t.List[Step] = []
    iterations = max(1, duration_s // interval_s)
    for i in range(iterations):
        steps.extend(
            [
                create_validation_step(
                    point_in_time_checks=[
                        *_no_crash_checks(),
                        # iBGP must stay Established despite eBGP churn / IGP
                        # instability -- the core 2.9.2 invariant and the known
                        # cross-group bugs T275928998 / T264949859. Retries absorb
                        # the "CLI empty under heavy load" transient (T271300586)
                        # without masking a real sustained iBGP flap.
                        create_bgp_session_establish_check(
                            parent_prefixes_to_ignore=non_ibgp_parent_prefixes,
                            retry_count=retry_count,
                            retry_delay_seconds=retry_delay_s,
                            check_id="simul_disrupt_ibgp_established",
                        ),
                        create_system_cpu_load_average_check(
                            baseline=load_avg_baseline
                        ),
                    ],
                    description=(
                        f"2.9.2 monitor -- no crash; iBGP Established; "
                        f"load-avg<={load_avg_baseline} (sample {i + 1}/{iterations})"
                    ),
                ),
                create_longevity_step(duration=interval_s),
            ]
        )
    return steps


def create_bgp_ug_simultaneous_disruptions_playbook(
    *,
    device_name: str,
    # --- Route churn track (eBGP) ---
    ebgp_route_pool_regex: str,
    ibgp_attr_pool_regex: str,
    ebgp_flap_peer_regex: str,
    # --- IGP-instability track (Open/R metric oscillation; requires WITH_OPEN_R)
    openr_start_ipv4s: t.List[str],
    openr_start_ipv6s: t.List[str],
    openr_local_link: t.Dict[str, t.Any],
    openr_other_link: t.Dict[str, t.Any],
    # --- Monitor track scoping + gates ---
    non_ibgp_parent_prefixes: t.List[str],
    # --- Resource gates ---
    vmhwm_growth_threshold_bytes: int,
    # --- Checks ---
    prechecks: t.List[PointInTimeHealthCheck],
    postchecks: t.Optional[t.List[PointInTimeHealthCheck]] = None,
    snapshot_checks: t.Optional[t.List[SnapshotHealthCheck]] = None,
    bgp_mon_ignore_prefixes: t.Optional[t.List[str]] = None,
    # --- Tunables (spec defaults) ---
    route_churn_count: int = 200,
    route_churn_community_values: t.Optional[t.List[str]] = None,
    route_churn_interval_s: int = 60,
    flap_random_session_num: int = 16,
    session_flap_interval_s: int = 120,
    attr_churn_count: int = 100,
    local_pref_low: int = 90,
    local_pref_high: int = 110,
    attr_churn_interval_s: int = 60,
    igp_metric_count: int = 63,
    igp_metric_step: int = 2,
    igp_frequency_s: int = 60,
    load_avg_baseline: float = 12.0,
    monitor_interval_s: int = 120,
    monitor_retry_count: int = 3,
    monitor_retry_delay_s: float = 10.0,
    vmhwm_absolute_threshold_bytes: t.Optional[int] = None,
    disruption_duration_s: int = 1800,
    convergence_quiesce_s: int = 300,
    recovery_session_retry_count: int = 10,
    recovery_session_retry_delay_s: float = 30.0,
) -> Playbook:
    """Build the BGP++ Update Group qualification 2.9.2 playbook (Simultaneous
    Disruptions Across All Groups).

    Intent (spec 2.9.2): under FOUR concurrent disruption types the BGP++ agent
    must not crash and the iBGP update group must stay stable (all iBGP sessions
    Established throughout), and after the disruption stops it must reconverge
    cleanly with bounded memory growth. This is the "kitchen-sink" UG stress test.

    Structure -- one concurrent stage of six tracks running ``disruption_duration_s``
    (default 30 min):
      1. Route churn (``_route_churn_track_steps``): every ``route_churn_interval_s``
         withdraw + re-advertise ``route_churn_count`` eBGP routes, rotating the
         community.
      2. Session flaps (``_session_flap_track_steps``): every
         ``session_flap_interval_s`` flap ``flap_random_session_num`` RANDOM eBGP
         sessions (GR-off, so a real "no graceful restart" flap per spec).
      3. Attribute churn (``_attribute_churn_track_steps``): every
         ``attr_churn_interval_s`` toggle LOCAL_PREF on ``attr_churn_count`` iBGP
         routes between ``local_pref_low`` and ``local_pref_high``.
      4. IGP instability: one self-running ``create_openr_route_action_step``
         (``METRIC_OSCILLATION``) oscillating Open/R metrics toward the injected
         PNHs for the whole window (needs the WITH_OPEN_R profile).
      5. VmHWM growth gate: one spanning ``bgp_vmhwm_growth_monitor`` custom step
         that captures VmHWM, waits the window, re-reads, and FAILs if growth
         exceeds ``vmhwm_growth_threshold_bytes`` (spec pass-criterion 4).
      6. Monitor (``_monitor_track_steps``): every ``monitor_interval_s`` assert
         no crash + iBGP Established + system load-average bound (the EOS
         device-CPU signal; a per-process bgpcpp CPU% gate is intentionally not
         used -- it reads >100% under churn and isn't the spec's device "40%").

    Then a sequential convergence stage: re-inject the Open/R routes to restore
    baseline IGP metrics, quiesce ``convergence_quiesce_s`` (default 5 min), and
    verify no crash + ALL sessions re-Established (excl BGP-MON) + UG still formed.

    ``non_ibgp_parent_prefixes`` (eBGP v6/v4 + BGP-MON parents) scopes the
    "iBGP Established throughout" check to iBGP only, since eBGP is intentionally
    being flapped. ``bgp_mon_ignore_prefixes`` scopes the recovery all-sessions
    check to exclude the never-emulated BGP-MON peers.

    Route-count / distribution verification (spec pass-criterion 3) is not
    asserted -- adj-RIB-out is vacuous under UG (T271301144) and the DUT advertises
    0 on this topology pending a DNE egress answer -- so the substance here is the
    stability/no-crash/no-flap/bounded-resource invariants (the rest of 2.9.2's
    pass criteria), which directly exercise the known cross-group bugs
    T275928998 / T264949859.
    """
    if route_churn_community_values is None:
        # Arbitrary distinct standard communities to vary per cycle. Only used to
        # add attribute variation to the churn -- not verified end-to-end (this is
        # an ingress-side stress, and distribution is not asserted; see above).
        route_churn_community_values = ["65529:1001", "65529:1002", "65529:1003"]

    concurrent_steps = [
        ConcurrentStep(
            steps=_route_churn_track_steps(
                device_name=device_name,
                prefix_pool_regex=ebgp_route_pool_regex,
                route_count=route_churn_count,
                community_values=route_churn_community_values,
                interval_s=route_churn_interval_s,
                duration_s=disruption_duration_s,
            )
        ),
        ConcurrentStep(
            steps=_session_flap_track_steps(
                ebgp_flap_peer_regex=ebgp_flap_peer_regex,
                random_session_num=flap_random_session_num,
                interval_s=session_flap_interval_s,
                duration_s=disruption_duration_s,
            )
        ),
        ConcurrentStep(
            steps=_attribute_churn_track_steps(
                ibgp_prefix_pool_regex=ibgp_attr_pool_regex,
                route_count=attr_churn_count,
                local_pref_low=local_pref_low,
                local_pref_high=local_pref_high,
                interval_s=attr_churn_interval_s,
                duration_s=disruption_duration_s,
            )
        ),
        # IGP metric oscillation -- one self-running step spanning the window.
        ConcurrentStep(
            steps=[
                create_openr_route_action_step(
                    device_name=device_name,
                    start_ipv4s=openr_start_ipv4s,
                    start_ipv6s=openr_start_ipv6s,
                    local_link=openr_local_link,
                    other_link=openr_other_link,
                    action=OpenRRouteAction.METRIC_OSCILLATION.value,
                    count=igp_metric_count,
                    step=igp_metric_step,
                    duration=disruption_duration_s,
                    frequency=igp_frequency_s,
                    description=(
                        "2.9.2 IGP instability -- oscillate Open/R metrics toward "
                        "the injected PNHs for the disruption window"
                    ),
                ),
            ]
        ),
        # VmHWM growth gate -- one spanning custom step (capture, wait, capture,
        # FAIL if growth > threshold). Spec pass-criterion 4.
        ConcurrentStep(
            steps=[
                create_custom_step(
                    params_dict={
                        "custom_step_name": "bgp_vmhwm_growth_monitor",
                        "hostname": device_name,
                        "duration_seconds": disruption_duration_s,
                        "growth_threshold_bytes": vmhwm_growth_threshold_bytes,
                    },
                    description=(
                        "2.9.2 -- assert bgpcpp VmHWM growth over the disruption "
                        "window stays below the threshold (< 500 MB)"
                    ),
                ),
            ]
        ),
        ConcurrentStep(
            steps=_monitor_track_steps(
                non_ibgp_parent_prefixes=non_ibgp_parent_prefixes,
                load_avg_baseline=load_avg_baseline,
                interval_s=monitor_interval_s,
                duration_s=disruption_duration_s,
                retry_count=monitor_retry_count,
                retry_delay_s=monitor_retry_delay_s,
            )
        ),
    ]

    disruption_stage = create_steps_stage(
        concurrent=True,
        concurrent_steps=concurrent_steps,
        description=(
            "2.9.2 -- four concurrent disruption tracks (route churn, random "
            "eBGP flaps, IGP-metric oscillation, iBGP attribute churn) + monitor "
            "+ VmHWM-growth gate, for the disruption window"
        ),
    )

    convergence_stage = create_steps_stage(
        steps=[
            # Restore baseline IGP metrics (METRIC_OSCILLATION left them random).
            create_openr_route_action_step(
                device_name=device_name,
                start_ipv4s=openr_start_ipv4s,
                start_ipv6s=openr_start_ipv6s,
                local_link=openr_local_link,
                other_link=openr_other_link,
                action=OpenRRouteAction.INJECT.value,
                count=igp_metric_count,
                step=igp_metric_step,
                description=(
                    "2.9.2 recovery -- re-inject Open/R routes to restore the "
                    "baseline IGP metrics"
                ),
            ),
            create_longevity_step(
                duration=convergence_quiesce_s,
                description=(
                    "2.9.2 -- quiesce (default 5 min) for full convergence after "
                    "all disruptions stop"
                ),
            ),
            create_validation_step(
                point_in_time_checks=[
                    *_no_crash_checks(),
                    # All sessions must be re-Established after convergence (excl
                    # the never-emulated BGP-MON). Retries absorb full-scale
                    # re-convergence timing.
                    create_bgp_session_establish_check(
                        parent_prefixes_to_ignore=bgp_mon_ignore_prefixes,
                        retry_count=recovery_session_retry_count,
                        retry_delay_seconds=recovery_session_retry_delay_s,
                        check_id="simul_disrupt_recovery_sessions",
                    ),
                    create_bgp_update_group_check(
                        expect_enabled=True,
                        check_id="simul_disrupt_recovery_ug",
                    ),
                ],
                description=(
                    "2.9.2 -- post-disruption convergence: no crash; all sessions "
                    "re-Established (excl BGP-MON); update group still formed"
                ),
            ),
        ],
    )

    stages = [disruption_stage, convergence_stage]

    # Always-appended bounds (spec pass-criteria 5/6), whether the caller takes
    # the default ``BGP_STANDARD_POSTCHECKS`` bundle or supplies its own list, so
    # a caller-provided ``postchecks`` can never silently drop them.
    base_postchecks = (
        list(postchecks) if postchecks is not None else list(BGP_STANDARD_POSTCHECKS)
    )
    postchecks = base_postchecks + [
        create_system_cpu_load_average_check(baseline=load_avg_baseline),
        create_bgp_update_group_check(expect_enabled=True),
        # Spec pass-criterion 5: no EOS logs at severity Error or higher over the
        # test window. On EOS an empty-json/agent-less LOG_PARSING_CHECK routes to
        # the system-log severity path (show logging emergencies/critical/errors).
        create_log_parsing_check(start_time_jq_var="test_case_start_time"),
    ]
    # Optional absolute VmHWM ceiling (extra safety; not a 2.9.2 criterion, but
    # cheap and consistent with the other UG tests). None -> skip.
    if vmhwm_absolute_threshold_bytes is not None:
        postchecks.append(
            create_memory_utilization_check(
                vmhwm_threshold=vmhwm_absolute_threshold_bytes
            )
        )
    if snapshot_checks is None:
        snapshot_checks = list(BGP_STANDARD_SNAPSHOT_CHECKS)

    return Playbook(
        name="bgp_ug_simultaneous_disruptions",
        stages=stages,
        prechecks=prechecks,
        postchecks=postchecks,
        snapshot_checks=snapshot_checks,
    )


# =============================================================================
# 2.9.4 Dual-Stack Isolation: IPv4 Operations Do Not Affect IPv6 Group
# =============================================================================
#
# The spec verifies STRICT AFI isolation: an IPv4 route operation (add, withdraw,
# attribute change) must not leak into the IPv6 update group, and vice versa --
# because IPv4 and IPv6 peers are in SEPARATE update groups even on the same
# peer-group. It advertises/withdraws v4 and v6 prefixes and checks (a) the v4 op
# reaches every iBGP v4 peer, (b) the v6 op reaches every iBGP v6 peer, and
# (c) each op leaves the OTHER AFI's per-peer distribution unchanged.
#
# Per-peer distribution IS observable here via the ``postpolicy_sent_prefix_count``
# ("PS") gauge from getBgpSessions -- the same CLI "PS" column -- which is
# populated and non-vacuous under Update Group (unlike getPostfilterAdvertised-
# Networks / adj-RIB-out, which is vacuous under UG per T271301144). This runs
# under WITH_OPEN_R so the iBGP next-hops resolve and the DUT actually advertises
# (under WITHOUT_OPEN_R the routes are inactive and the DUT advertises ~0; see the
# tracking-doc appendix "Route Advertisement Under Open/R"). The checks:
#   1. STRUCTURAL AFI-separation -- the v4 and v6 peer-groups map to separate,
#      AFI-pure update groups (``expected_afi_by_substring`` on the UG check).
#      Isolation BY CONSTRUCTION: a v4 route physically cannot be distributed
#      through the v6 group. Asserted at baseline and after each operation.
#   2. PER-AFI DISTRIBUTION + ISOLATION -- snapshot the PS gauge across every
#      iBGP peer of each AFI (selected by peer-ADDRESS subnet: the iBGP v4 plane
#      /16s vs v6 plane /80s -- session.peer_group is not the AFI peer-group name
#      here), do the op, then assert the OPERATED AFI's per-peer PS moved by the
#      expected delta (advertise 500 -> +500; withdraw 200 -> -200) while the
#      ISOLATED AFI's PS stayed flat (spec steps 2/3/6/9).
#   3. NO cross-AFI disruption -- no crash and all sessions stay Established
#      across the v4-only, v6-only, and simultaneous operations.
#
# All checks are STRICT: v4 distribution (+500/+100), v6 distribution (-200/-100),
# and BOTH isolation directions (v6 flat during a v4 op, v4 flat during a v6 op)
# fail the test if they break. HW-verified end-to-end on bag011 (2026-07-18): every
# per-AFI distribution + isolation check passes on a converged session.
#
# COLD-START CAVEAT (v6): the eBGP v6 peers' next-hops resolve SLOWLY after a FRESH
# IXIA build -- on a just-built session iBGP v6 PS can read 0 for a long window
# (observed 0 at ~30 min post-build, resolved by the time the session was ~90 min
# old), so the v6 distribution checks can transiently fail on a cold build until the
# v6 next-hops converge. On a warm/reused session (the conveyor norm) v6 distributes
# normally. The slow cold-start v6 next-hop resolution is itself under investigation
# (Open/R vs bgpcpp connected-resolution timing; earlier "always-0 / bgpcpp defect"
# in appendix Part B was this cold-start artifact, not a permanent defect). Give a
# freshly-built session time to converge before running, or run on a warm session.
#
# "advertise 500 new" advertises GENUINELY-NEW prefixes ON TOP of the existing
# routes: a dedicated SPARE eBGP v4 pool (distinct 120.100.x /24s, inline-
# generated via RouteScale in the testconfig, carrying the accept communities +
# the spec marker 65529:44444) is built inactive; the setup step withdraws it so
# baseline is the untouched existing routes, then step 1/8 advertise index ranges
# of the spare -- so iBGP v4 goes 749 -> 1249 (+500), a real addition. The v4
# ``prefix_pool_regex`` the caller passes therefore targets the SPARE pool.


def create_bgp_ug_dual_stack_isolation_playbook(
    *,
    device_name: str,
    # --- Structural AFI-separation (baseline + re-asserted after each op) ---
    afi_peer_group_substrings: t.List[str],
    expected_group_count: int,
    expected_member_counts: t.Dict[str, int],
    expected_afi_by_substring: t.Dict[str, str],
    # --- Per-AFI distribution (PS gauge, iBGP peers selected by peer-address
    # subnet -- session.peer_group is not the AFI peer-group name on bag011, so
    # we scope by the iBGP v4/v6 plane subnets, same as the session checks) ---
    ibgp_v4_peer_parent_prefixes: t.List[str],
    ibgp_v6_peer_parent_prefixes: t.List[str],
    # Two separate spare v4 pools (advertised WHOLE -- a RouteScale-generated
    # pool toggles Active per network-group, not per-index): SPARE_A for step 1,
    # SPARE_B for step 8. Sized to advertise_v4_step1_count / _step8_count.
    ebgp_v4_step1_pool_regex: str,
    ebgp_v4_step8_pool_regex: str,
    ebgp_v6_prefix_pool_regex: str,
    # --- Checks ---
    prechecks: t.List[PointInTimeHealthCheck],
    postchecks: t.Optional[t.List[PointInTimeHealthCheck]] = None,
    snapshot_checks: t.Optional[t.List[SnapshotHealthCheck]] = None,
    bgp_mon_ignore_prefixes: t.Optional[t.List[str]] = None,
    # --- Route-operation sizing (index ranges into the eBGP pools) ---
    advertise_v4_step1_count: int = 500,
    advertise_v4_step8_count: int = 100,
    withdraw_v6_step5_count: int = 200,
    withdraw_v6_step8_count: int = 100,
    # --- Per-peer delta gating ---
    count_window: int = 10,
    unchanged_window: int = 2,
    peer_violation_tolerance: int = 3,
    # --- Timing / sessions / gates ---
    op_settle_s: int = 90,
    session_retry_count: int = 10,
    session_retry_delay_s: float = 30.0,
    load_avg_baseline: float = 12.0,
    vmhwm_absolute_threshold_bytes: t.Optional[int] = None,
) -> Playbook:
    """Build the BGP++ Update Group qualification 2.9.4 playbook (Dual-Stack
    Isolation: IPv4 operations do not affect the IPv6 update group).

    Intent (spec 2.9.4): prove strict AFI isolation -- IPv4 and IPv6 peers form
    SEPARATE update groups, so a route operation on one AFI never perturbs the
    other. Per-peer distribution is verified via the ``postpolicy_sent_prefix_count``
    ("PS") gauge, snapshotting/verifying every iBGP peer of an AFI by peer-address
    subnet (``ibgp_v4_peer_parent_prefixes`` / ``ibgp_v6_peer_parent_prefixes`` --
    the per-session peer-group field is not the AFI peer-group name on bag011).
    Requires WITH_OPEN_R so the iBGP next-hops resolve and the DUT advertises.

    Stages (each op: snapshot both AFIs' PS -> do the op -> settle -> verify the
    operated AFI's per-peer delta and the isolated AFI's flatness -> validate no
    crash / sessions up / UG still AFI-split):
      0. Setup + baseline -- withdraw BOTH spare v4 pools (SPARE_A/step 1,
         SPARE_B/step 8) so they are inactive at baseline (their genuinely-new
         prefixes are advertised WHOLE on top of the untouched existing routes in
         step 1/8); assert BGP up, sessions Established, update groups AFI-split
         (``expected_afi_by_substring`` + counts).
      1. IPv4 advertise (spec step 1) -- advertise the whole SPARE_A pool (~N1
         new prefixes); assert every iBGP v4 peer's PS grew ~N1 (distribution)
         and every iBGP v6 peer's PS is unchanged (isolation).
      2. IPv6 withdraw (spec step 5) -- withdraw eBGP v6 [0, M5) (imported pool,
         index-sliced); assert every iBGP v4 peer's PS unchanged (isolation,
         checked FIRST) then every iBGP v6 peer's PS dropped ~M5 (distribution).
         The v6 distribution check is strict and passes on a warm/converged
         session (the conveyor norm); on a FRESH build it can read 0 until the
         eBGP v6 next-hops converge (a cold-start characteristic, not a permanent
         defect -- see the COLD-START CAVEAT above). The v4 isolation is checked
         FIRST so its PASS is recorded before a cold-start v6 abort, if any.
      3. Simultaneous (spec step 8) -- advertise the whole SPARE_B pool (~N8) and
         withdraw v6 [M5, M5+M8) together; assert v4 +~N8 then v6 -~M8 (same
         warm-pass / cold-start-0 behavior as step 5's v6 check).
      4. Restore -- withdraw both spare v4 pools + re-advertise the v6 ranges.

    Per-peer deltas are gated with a signed window: an advertise/withdraw of K is
    accepted in [K-``count_window``, K+``count_window``]; "unchanged" is
    |delta| <= ``unchanged_window``; up to ``peer_violation_tolerance`` peers may
    fall outside before the step fails (absorbs a few slow-converging peers at
    ~496-peer scale). "advertise N new" advertises a dedicated SPARE v4 pool of
    genuinely-new prefixes (inline-generated in the testconfig, carrying the
    accept communities + the spec marker 65529:44444), inactive at baseline and
    added on top of the existing routes -- so the delta is a true addition.
    """

    def _structure_check(check_id: str) -> PointInTimeHealthCheck:
        """The AFI-split update-group structure: v4/v6 peer-groups map only to
        same-AFI, AFI-pure update groups (the core dual-stack-isolation proof)."""
        return create_bgp_update_group_check(
            peer_group_substrings=afi_peer_group_substrings,
            expected_group_count=expected_group_count,
            expected_member_counts=expected_member_counts,
            expected_afi_by_substring=expected_afi_by_substring,
            expect_enabled=True,
            check_id=check_id,
        )

    def _all_sessions_check(check_id: str) -> PointInTimeHealthCheck:
        """All sessions Established (excl the never-emulated BGP-MON). The ops
        only advertise/withdraw ROUTES (not flap sessions), so sessions must stay
        up; a drop would mean a route op disrupted the sessions."""
        return create_bgp_session_establish_check(
            parent_prefixes_to_ignore=bgp_mon_ignore_prefixes,
            retry_count=session_retry_count,
            retry_delay_seconds=session_retry_delay_s,
            check_id=check_id,
        )

    def _validation(check_id_prefix: str, description: str) -> Step:
        """No crash + AFI-split UG structure + all sessions up (re-asserted after
        every operation: an op must not crash, merge/split groups, or drop
        sessions)."""
        return create_validation_step(
            point_in_time_checks=[
                *_no_crash_checks(),
                _structure_check(f"{check_id_prefix}_structure"),
                _all_sessions_check(f"{check_id_prefix}_sessions"),
            ],
            description=description,
        )

    def _snapshot_both(key: str, note: str) -> t.List[Step]:
        """Snapshot the PS gauge across every iBGP v4 peer and every iBGP v6 peer
        (selected by peer-address subnet) so the following op's per-AFI delta is
        measured from a fresh baseline."""
        return [
            create_snapshot_bgp_sent_route_counts_step(
                hostname=device_name,
                snapshot_key=f"{key}_v4",
                peer_parent_prefixes=ibgp_v4_peer_parent_prefixes,
                description=f"2.9.4 {note} -- snapshot iBGP v4 PS (by subnet)",
            ),
            create_snapshot_bgp_sent_route_counts_step(
                hostname=device_name,
                snapshot_key=f"{key}_v6",
                peer_parent_prefixes=ibgp_v6_peer_parent_prefixes,
                description=f"2.9.4 {note} -- snapshot iBGP v6 PS (by subnet)",
            ),
        ]

    def _verify(
        *,
        snapshot_key: str,
        peer_parent_prefixes: t.List[str],
        expected_delta: int,
        description: str,
        unchanged: bool = False,
    ) -> Step:
        """Verify a per-AFI PS delta. ``unchanged`` -> |delta| <= unchanged_window
        (isolation); otherwise delta in [expected-count_window, expected+count_window]
        (distribution -- signed, so a negative ``expected_delta`` is a withdraw)."""
        if unchanged:
            min_d, max_d = -unchanged_window, unchanged_window
        else:
            min_d, max_d = expected_delta - count_window, expected_delta + count_window
        return create_verify_bgp_sent_route_count_delta_step(
            hostname=device_name,
            snapshot_key=snapshot_key,
            peer_parent_prefixes=peer_parent_prefixes,
            min_delta=min_d,
            max_delta=max_d,
            tolerance=peer_violation_tolerance,
            description=description,
        )

    v6_total_withdraw_count = withdraw_v6_step5_count + withdraw_v6_step8_count

    stages = [
        # Stage 0: setup + baseline. Withdraw BOTH spare v4 pools so they are
        # inactive at baseline; step 1/8 then advertise their genuinely-new
        # prefixes ON TOP of the untouched existing routes. Then assert the
        # starting state is AFI-split with all sessions up.
        create_steps_stage(
            steps=[
                create_advertise_withdraw_prefixes_step(
                    device_name=device_name,
                    advertise=False,
                    prefix_pool_regex=ebgp_v4_step1_pool_regex,
                    prefix_start_index=0,
                    description=(
                        "2.9.4 setup -- withdraw the step-1 spare v4 pool so it is "
                        "inactive at baseline"
                    ),
                ),
                create_advertise_withdraw_prefixes_step(
                    device_name=device_name,
                    advertise=False,
                    prefix_pool_regex=ebgp_v4_step8_pool_regex,
                    prefix_start_index=0,
                    description=(
                        "2.9.4 setup -- withdraw the step-8 spare v4 pool so it is "
                        "inactive at baseline"
                    ),
                ),
                create_longevity_step(
                    duration=op_settle_s,
                    description="2.9.4 setup -- settle after deactivating the spare v4 pools",
                ),
                _validation(
                    "dual_stack_baseline",
                    "2.9.4 baseline -- BGP up; update groups AFI-split (v4 and v6 "
                    "peers in separate, AFI-pure update groups); spare v4 pools "
                    "inactive",
                ),
            ],
        ),
        # Stage 1 (spec step 1): an IPv4 advertise reaches the v4 UG only.
        create_steps_stage(
            steps=[
                *_snapshot_both("ds_s1", "step 1"),
                create_advertise_withdraw_prefixes_step(
                    device_name=device_name,
                    advertise=True,
                    prefix_pool_regex=ebgp_v4_step1_pool_regex,
                    prefix_start_index=0,
                    description=(
                        f"2.9.4 step 1 -- advertise the step-1 spare v4 pool "
                        f"(~{advertise_v4_step1_count} genuinely-new prefixes) "
                        f"on top of the existing routes"
                    ),
                ),
                create_longevity_step(
                    duration=op_settle_s,
                    description="2.9.4 step 1 -- settle after the v4 advertise",
                ),
                _verify(
                    snapshot_key="ds_s1_v4",
                    peer_parent_prefixes=ibgp_v4_peer_parent_prefixes,
                    expected_delta=advertise_v4_step1_count,
                    description=(
                        f"2.9.4 step 1 (distribution) -- every iBGP v4 peer's PS "
                        f"grew by ~{advertise_v4_step1_count}: the v4 routes "
                        f"reached the v4 update group"
                    ),
                ),
                _verify(
                    snapshot_key="ds_s1_v6",
                    peer_parent_prefixes=ibgp_v6_peer_parent_prefixes,
                    expected_delta=0,
                    unchanged=True,
                    description=(
                        "2.9.4 step 1 (isolation) -- every iBGP v6 peer's PS "
                        "unchanged: the v4 op did not touch the v6 update group"
                    ),
                ),
                _validation(
                    "dual_stack_after_v4",
                    "2.9.4 -- after IPv4 op: no crash; sessions Established; "
                    "update groups still AFI-split",
                ),
            ],
        ),
        # Stage 2 (spec step 5): an IPv6 withdraw reaches the v6 UG only. The v6
        # DISTRIBUTION check is strict and passes on a warm/converged session; on
        # a cold build it can read 0 until the eBGP v6 next-hops converge (a
        # cold-start characteristic, not a permanent defect -- see the module
        # COLD-START CAVEAT). Isolation (v4 flat) is checked FIRST so its PASS is
        # recorded before a cold-start v6 abort, if any.
        create_steps_stage(
            steps=[
                *_snapshot_both("ds_s5", "step 5"),
                create_advertise_withdraw_prefixes_step(
                    device_name=device_name,
                    advertise=False,
                    prefix_pool_regex=ebgp_v6_prefix_pool_regex,
                    prefix_start_index=0,
                    prefix_end_index=withdraw_v6_step5_count,
                    description=(
                        f"2.9.4 step 5 -- withdraw {withdraw_v6_step5_count} eBGP "
                        f"v6 prefixes [0, {withdraw_v6_step5_count})"
                    ),
                ),
                create_longevity_step(
                    duration=op_settle_s,
                    description="2.9.4 step 5 -- settle after the v6 withdraw",
                ),
                _verify(
                    snapshot_key="ds_s5_v4",
                    peer_parent_prefixes=ibgp_v4_peer_parent_prefixes,
                    expected_delta=0,
                    unchanged=True,
                    description=(
                        "2.9.4 step 5 (isolation) -- every iBGP v4 peer's PS "
                        "unchanged: the v6 op did not touch the v4 update group"
                    ),
                ),
                _verify(
                    snapshot_key="ds_s5_v6",
                    peer_parent_prefixes=ibgp_v6_peer_parent_prefixes,
                    expected_delta=-withdraw_v6_step5_count,
                    description=(
                        f"2.9.4 step 5 (distribution) -- every iBGP v6 peer's PS "
                        f"dropped by ~{withdraw_v6_step5_count}: the v6 withdraw "
                        f"reached the v6 update group (requires a converged "
                        f"session -- see the cold-start note in the module doc)"
                    ),
                ),
                _validation(
                    "dual_stack_after_v6",
                    "2.9.4 -- after IPv6 op: no crash; sessions Established; "
                    "update groups still AFI-split",
                ),
            ],
        ),
        # Stage 3 (spec step 8): TRULY-SIMULTANEOUS v4-advertise + v6-withdraw.
        # The two ops run in PARALLEL ConcurrentStep tracks (not issued
        # back-to-back), so they are genuinely concurrent on the wire -- the
        # spec's "simultaneously advertise 100 v4 AND withdraw 100 v6". A stage
        # is either concurrent or sequential, so step 8 spans three stages:
        # (3a) snapshot the per-AFI baseline BEFORE the ops; (3b) the concurrent
        # advertise || withdraw; (3c) settle, then verify each AFI moved by its
        # exact delta and nothing else (no cross-AFI interference) + no crash.
        create_steps_stage(
            steps=[*_snapshot_both("ds_s8", "step 8")],
        ),
        create_steps_stage(
            concurrent=True,
            concurrent_steps=[
                ConcurrentStep(
                    steps=[
                        create_advertise_withdraw_prefixes_step(
                            device_name=device_name,
                            advertise=True,
                            prefix_pool_regex=ebgp_v4_step8_pool_regex,
                            prefix_start_index=0,
                            description=(
                                f"2.9.4 step 8 -- advertise the step-8 spare v4 "
                                f"pool (~{advertise_v4_step8_count} more "
                                f"genuinely-new prefixes), concurrent with the "
                                f"v6 withdraw"
                            ),
                        )
                    ]
                ),
                ConcurrentStep(
                    steps=[
                        create_advertise_withdraw_prefixes_step(
                            device_name=device_name,
                            advertise=False,
                            prefix_pool_regex=ebgp_v6_prefix_pool_regex,
                            prefix_start_index=withdraw_v6_step5_count,
                            prefix_end_index=v6_total_withdraw_count,
                            description=(
                                f"2.9.4 step 8 -- concurrently withdraw "
                                f"{withdraw_v6_step8_count} eBGP v6 prefixes "
                                f"[{withdraw_v6_step5_count}, "
                                f"{v6_total_withdraw_count})"
                            ),
                        )
                    ]
                ),
            ],
        ),
        create_steps_stage(
            steps=[
                create_longevity_step(
                    duration=op_settle_s,
                    description=(
                        "2.9.4 step 8 -- settle after the simultaneous "
                        "v4-advertise / v6-withdraw"
                    ),
                ),
                _verify(
                    snapshot_key="ds_s8_v4",
                    peer_parent_prefixes=ibgp_v4_peer_parent_prefixes,
                    expected_delta=advertise_v4_step8_count,
                    description=(
                        f"2.9.4 step 8 (distribution) -- every iBGP v4 peer's PS "
                        f"grew by ~{advertise_v4_step8_count} during the "
                        f"simultaneous op (v4 unaffected by the concurrent v6 op)"
                    ),
                ),
                _verify(
                    snapshot_key="ds_s8_v6",
                    peer_parent_prefixes=ibgp_v6_peer_parent_prefixes,
                    expected_delta=-withdraw_v6_step8_count,
                    description=(
                        f"2.9.4 step 8 (distribution) -- every iBGP v6 peer's PS "
                        f"dropped by ~{withdraw_v6_step8_count} during the "
                        f"simultaneous op (v6 unaffected by the concurrent v4 op)"
                    ),
                ),
                _validation(
                    "dual_stack_after_simul",
                    "2.9.4 -- after simultaneous op: no crash; sessions "
                    "Established; update groups still AFI-split",
                ),
            ],
        ),
        # Stage 4: restore to baseline. Baseline has the spare v4 pools inactive,
        # so withdraw both again (undo the step-1/8 advertises); re-advertise the
        # v6 ranges that steps 5/8 withdrew.
        create_steps_stage(
            steps=[
                create_advertise_withdraw_prefixes_step(
                    device_name=device_name,
                    advertise=False,
                    prefix_pool_regex=ebgp_v4_step1_pool_regex,
                    prefix_start_index=0,
                    description=(
                        "2.9.4 restore -- withdraw the step-1 spare v4 pool "
                        "(return it to the inactive baseline)"
                    ),
                ),
                create_advertise_withdraw_prefixes_step(
                    device_name=device_name,
                    advertise=False,
                    prefix_pool_regex=ebgp_v4_step8_pool_regex,
                    prefix_start_index=0,
                    description=(
                        "2.9.4 restore -- withdraw the step-8 spare v4 pool "
                        "(return it to the inactive baseline)"
                    ),
                ),
                create_advertise_withdraw_prefixes_step(
                    device_name=device_name,
                    advertise=True,
                    prefix_pool_regex=ebgp_v6_prefix_pool_regex,
                    prefix_start_index=0,
                    prefix_end_index=v6_total_withdraw_count,
                    description=(
                        "2.9.4 restore -- re-advertise all withdrawn eBGP v6 "
                        "prefixes (return to baseline)"
                    ),
                ),
                create_longevity_step(
                    duration=op_settle_s,
                    description="2.9.4 restore -- settle after restoring the pools",
                ),
            ],
        ),
    ]

    # Always-appended bounds (UG enabled; load-average never crosses baseline; no
    # Error+ EOS logs), whether the caller takes the default bundle or supplies
    # its own list, so a caller-provided ``postchecks`` can never silently drop
    # them.
    base_postchecks = (
        list(postchecks) if postchecks is not None else list(BGP_STANDARD_POSTCHECKS)
    )
    postchecks = base_postchecks + [
        create_system_cpu_load_average_check(baseline=load_avg_baseline),
        create_bgp_update_group_check(expect_enabled=True),
        create_log_parsing_check(start_time_jq_var="test_case_start_time"),
    ]
    # Optional absolute VmHWM ceiling (consistent with the other UG tests; not a
    # 2.9.4 pass-criterion). None -> skip.
    if vmhwm_absolute_threshold_bytes is not None:
        postchecks.append(
            create_memory_utilization_check(
                vmhwm_threshold=vmhwm_absolute_threshold_bytes
            )
        )
    if snapshot_checks is None:
        snapshot_checks = list(BGP_STANDARD_SNAPSHOT_CHECKS)

    return Playbook(
        name="bgp_ug_dual_stack_isolation",
        stages=stages,
        prechecks=prechecks,
        postchecks=postchecks,
        snapshot_checks=snapshot_checks,
    )


# =============================================================================
# 2.9.6 Staggered Peer Startup: Peers Coming Up at Different Times
# =============================================================================
#
# The spec brings eBGP peers up in THREE staggered waves (50 -> +100 -> +130, with
# 2-min gaps) on top of a stable iBGP route source, injects new iBGP routes between
# waves, and verifies that late-joining peers still receive the full accumulated
# initial dump, all eBGP peers converge to identical route sets, runtime
# distribution reaches everyone, nothing crashes, and no routes go stale.
#
# TOPOLOGY REALIZATION (documented deviation): the EBB full-scale IXIA topology has
# 140 eBGP sessions PER AFI in one peer object per AFI (BGP_PEER_IPV4_EBGP /
# BGP_PEER_IPV6_EBGP), NOT 280 in
# a single pool. The spec's 50/100/130 waves are realized as SYMMETRIC per-AFI
# session-index ranges applied to the combined v4+v6 eBGP regex (``start_bgp_peers``
# ``SessionIndices``, 1-based inclusive): 25/AFI -> 50/AFI -> 65/AFI = 50 -> 100 ->
# 130 combined, 280 total. "Route counts identical across all eBGP peers" is
# therefore a PER-AFI statement (v4 peers carry v4 routes, v6 peers v6 routes --
# cross-AFI counts differ by construction).
#
# DISTRIBUTION IS STRICT (both AFIs): all three spec pass-criteria are DUT->eBGP
# adj-RIB-out, read via the ``postpolicy_sent_prefix_count`` ("PS") gauge. With
# next-hop-self resolution (WITHOUT_OPEN_R + the bgpcpp interface-state gflag,
# D113330327) the iBGP next-hops resolve, the DUT installs + re-advertises, and the
# DUT->eBGP PS is HW-observed. The PS-gauge path is used rather than
# ``getPostfilterAdvertisedNetworks`` (SET equality) because the latter is vacuous
# under an Update Group (T271301144). The playbook ASSERTS, per eBGP peer:
#   * Criterion 1 (late waves get the accumulated dump): each between-wave inject
#     uses a genuinely-new dedicated pool, so the eBGP v4 count grows measurably; a
#     +total_wave_inject PS DELTA since the wave-1 baseline (``staggered_accum_baseline``)
#     proves the injected-before-they-joined routes reached the peers, and the uniform
#     check then proves the late waves share that grown total.
#   * Criteria 1-2 (identical counts across all peers): a non-zero, UNIFORM PS at
#     steady state (``verify_bgp_sent_route_counts_uniform``) -- v4 AND v6.
#   * Criterion 3 (runtime distribution reaches ALL 280): a per-peer +N PS DELTA after
#     a runtime inject of a genuinely-new dedicated pool -- one per AFI (v4 pool -> v4
#     peers, v6 pool -> v6 peers), so both eBGP AFIs are covered.
# All HW-validated on bag013 2026-07-23. The eBGP IPv6 next-hop (connected /127) can
# resolve slowly on a fresh cold-start (~30-90 min -- Appendix B); if a future fresh
# build regresses on the v6 uniform check, set ``v6_distribution_expected_fail`` to
# XFAIL it. What also lands: the wave orchestration; the eBGP UG MEMBERSHIP growing
# 25->75->140/AFI across the waves (structural proof that late peers join and attach);
# iBGP stays Established throughout; no crash per wave; and no stale routes (postcheck).
#
# Genuinely-new dedicated pools are required because the existing plane iBGP CSV pools
# share NLRI across all four planes -- a plane-1 withdraw/re-advertise is a no-op at
# the eBGP egress. So each measurable inject (two between-wave v4 pools + one v4 + one
# v6 final pool) has UNIQUE NLRI in its AFI's EB-PRIVATE accept aggregate.


def create_bgp_ug_staggered_startup_playbook(
    *,
    device_name: str,
    ebgp_peer_regex: str,
    ibgp_peer_regex: str,
    ibgp_v6_peer_group: str,
    ebgp_v4_peer_group: str,
    ebgp_v6_peer_group: str,
    # Waves: (start_idx, end_idx) 1-based inclusive ``SessionIndices`` applied to
    # BOTH AFI eBGP peers via the combined regex. ``cumulative_members_per_afi[i]``
    # is the eBGP UG member count PER AFI expected once wave ``i`` has come up.
    waves: t.List[t.Tuple[int, int]],
    cumulative_members_per_afi: t.List[int],
    # Scopes the "iBGP stays Established" checks to iBGP while eBGP is only partially
    # up (the eBGP v4/v6 + BGP-MON parent networks to ignore).
    non_ibgp_parent_prefixes: t.List[str],
    # Between-wave dump-growth inject pools -- ONE dedicated, genuinely-new v4 pool
    # per wave gap (len == len(waves) - 1), each with UNIQUE NLRI so its advertise is
    # a MEASURABLE +N at the eBGP egress (spec step 5 / criterion 1: late waves get
    # the accumulated dump). Advertised WHOLE after each wave (RouteScale pools toggle
    # Active whole-pool, not per-index) and withdrawn at Stage 1 so each advertise is
    # genuinely new.
    ibgp_wave_inject_pool_regexes: t.List[str],
    inject_per_wave: int = 100,
    final_inject_count: int = 50,
    # Dedicated criterion-3 runtime inject pools: genuinely-new pools with UNIQUE NLRI
    # so the runtime +N is measurable at the eBGP egress. v4 + v6 (one each) so
    # criterion 3 covers ALL eBGP peers (spec step 6 / criterion 3: "all 280 receive").
    # Advertised WHOLE ([0, final_inject_count)). None -> skip that AFI's criterion 3.
    ibgp_runtime_inject_pool_regex: t.Optional[str] = None,
    ibgp_v6_runtime_inject_pool_regex: t.Optional[str] = None,
    # eBGP peer selection (by peer-address subnet) for the STRICT distribution
    # verifies: all eBGP peers non-zero + uniform (criteria 1-2) and the runtime
    # +N delta (criterion 3). None -> skip that AFI. Both v4 and v6 are verified
    # STRICTLY (HW-validated on bag013 2026-07-23).
    ebgp_v4_peer_parent_prefixes: t.Optional[t.List[str]] = None,
    ebgp_v6_peer_parent_prefixes: t.Optional[t.List[str]] = None,
    # Per-peer count window (uniform spread + runtime +N delta) and how many peers
    # may fall outside before the check fails (absorbs a few slow-converging peers
    # at ~140-peer/AFI scale).
    distribution_count_window: int = 10,
    distribution_tolerance: int = 3,
    # ESCAPE HATCH (default off -> v6 STRICT): the eBGP v6 next-hop (connected /127)
    # can resolve slowly on a fresh cold build (Appendix B). If a future fresh build
    # regresses on the v6 uniform check, set this True to XFAIL v6 instead of failing.
    v6_distribution_expected_fail: bool = False,
    v6_distribution_expected_fail_reason: t.Optional[str] = None,
    # --- Checks ---
    prechecks: t.List[PointInTimeHealthCheck],
    postchecks: t.Optional[t.List[PointInTimeHealthCheck]] = None,
    snapshot_checks: t.Optional[t.List[SnapshotHealthCheck]] = None,
    bgp_mon_ignore_prefixes: t.Optional[t.List[str]] = None,
    # --- Timing / sessions / gates ---
    wave_gap_s: int = 120,
    settle_after_flap_s: int = 90,
    ibgp_source_settle_s: int = 120,
    inject_settle_s: int = 30,
    session_retry_count: int = 10,
    session_retry_delay_s: float = 30.0,
    load_avg_baseline: float = 12.0,
    vmhwm_absolute_threshold_bytes: t.Optional[int] = None,
) -> Playbook:
    """Build the BGP++ Update Group qualification 2.9.6 playbook (Staggered Peer
    Startup -- peers coming up at different times).

    Intent (spec 2.9.6): Update Group must handle eBGP peers coming up at staggered
    intervals -- early peers receive routes immediately, and late-joining peers get
    a full initial dump of everything accumulated before they came up; once all are
    up every eBGP peer has an identical route set and runtime distribution reaches
    all; no crash, no stale routes.

    Flow:
      0. Pre-condition 1 ("no established sessions at start"): stop ALL eBGP + iBGP
         sessions, settle, assert 0 Established (excl the never-emulated BGP-MON).
         (The framework precheck validates baseline health post-setup; this stage
         is the literal "start from no sessions" pre-condition -- the same
         start-from-a-known-state pattern as 2.9.7.)
      1. Bring the iBGP peers UP first as the stable route source, then withdraw every
         dedicated inject pool (a LIVE withdraw, so each between-wave / final inject
         re-advertises genuinely-new routes); assert iBGP Established + iBGP update
         group formed + no crash.
      2. Bring eBGP up in staggered waves (``waves``). After each wave's
         ``wave_gap_s`` gap, assert no crash; iBGP still Established (scoped by
         ``non_ibgp_parent_prefixes`` since eBGP is only partially up); and the eBGP
         update group grew to the expected cumulative member count PER AFI
         (``cumulative_members_per_afi`` -- the structural proof that the late peers
         joined and attached). Snapshot the eBGP v4 baseline at wave 1; between waves,
         inject ``inject_per_wave`` genuinely-new iBGP routes from that gap's dedicated
         pool so later waves receive a larger accumulated initial dump.
      3. All peers up: assert every eBGP peer Established + attached (full per-AFI UG
         membership); ASSERT criterion 1 (eBGP v4 count grew by the accumulated
         between-wave injects since wave 1); ASSERT criteria 1-2 (every eBGP peer, both
         AFIs, has a non-zero UNIFORM PS -- late-wave peers caught up, no peer missing
         routes); inject ``final_inject_count`` genuinely-new routes per AFI and ASSERT
         criterion 3 (every eBGP peer of that AFI grew by ~N -- all 280 covered); no
         crash.

    Distribution (spec pass-criteria 1-3) is STRICT on BOTH AFIs: criterion 1 via a
    per-peer +N accumulation delta (the between-wave injects use dedicated genuinely-new
    pools) plus the uniform check; criteria 1-2 via a per-peer PS-gauge uniform check
    (v4 + v6); criterion 3 via a per-peer +N delta after a runtime inject of a
    genuinely-new pool per AFI (v4 + v6 -> all 280 eBGP peers). All HW-validated on
    bag013 2026-07-23. The v6 uniform check has an escape hatch
    (``v6_distribution_expected_fail``) for the cold-start next-hop slowness (Appendix
    B), off by default. Also landing: the wave orchestration + UG-membership growth +
    iBGP-stays-up + no-crash + no-stale (postcheck). See the module comment above.
    """
    if not waves:
        raise ValueError("2.9.6: waves must be a non-empty list of (start, end) ranges")
    if len(cumulative_members_per_afi) != len(waves):
        raise ValueError(
            "2.9.6: cumulative_members_per_afi must have one entry per wave "
            f"(got {len(cumulative_members_per_afi)} counts for {len(waves)} waves)"
        )
    num_gaps = len(waves) - 1
    if len(ibgp_wave_inject_pool_regexes) != num_gaps:
        raise ValueError(
            "2.9.6: need one between-wave inject pool per wave gap "
            f"(got {len(ibgp_wave_inject_pool_regexes)} pools for {num_gaps} gaps)"
        )
    # Total between-wave routes injected across all gaps (the accumulated dump growth
    # a late-joining wave must receive -- criterion 1).
    total_wave_inject = inject_per_wave * num_gaps

    # Every dedicated genuinely-new inject pool, with its whole-pool size. All start
    # Active (inline RouteScale) and are withdrawn at Stage 1 so each later advertise
    # is a genuine +N: the per-wave dump-growth pools, plus the v4 + v6 final pools.
    _dedicated_inject_pools: t.List[t.Tuple[str, int]] = [
        (regex, inject_per_wave) for regex in ibgp_wave_inject_pool_regexes
    ]
    if ibgp_runtime_inject_pool_regex is not None:
        _dedicated_inject_pools.append(
            (ibgp_runtime_inject_pool_regex, final_inject_count)
        )
    if ibgp_v6_runtime_inject_pool_regex is not None:
        _dedicated_inject_pools.append(
            (ibgp_v6_runtime_inject_pool_regex, final_inject_count)
        )

    def _ibgp_up_check(check_id: str) -> PointInTimeHealthCheck:
        """iBGP sessions stay Established while eBGP is (partially) down -- scoped
        to iBGP by ignoring the eBGP + BGP-MON parents. Retries absorb full-scale
        convergence timing."""
        return create_bgp_session_establish_check(
            parent_prefixes_to_ignore=non_ibgp_parent_prefixes,
            retry_count=session_retry_count,
            retry_delay_seconds=session_retry_delay_s,
            check_id=check_id,
        )

    stages = [
        # Stage 0 -- pre-condition 1: no established sessions at the start.
        create_steps_stage(
            steps=[
                _flap_bgp_peers(
                    peer_regex=ebgp_peer_regex,
                    start=False,
                    description="2.9.6 setup -- stop ALL eBGP sessions",
                ),
                _flap_bgp_peers(
                    peer_regex=ibgp_peer_regex,
                    start=False,
                    description="2.9.6 setup -- stop ALL iBGP sessions",
                ),
                create_longevity_step(
                    duration=settle_after_flap_s,
                    description="2.9.6 setup -- settle after stopping all sessions",
                ),
                create_validation_step(
                    point_in_time_checks=[
                        *_no_crash_checks(),
                        create_bgp_session_establish_check(
                            expected_established_sessions=0,
                            parent_prefixes_to_ignore=bgp_mon_ignore_prefixes,
                            check_id="staggered_precond_no_sessions",
                        ),
                    ],
                    description=(
                        "2.9.6 pre-condition 1 -- no established BGP sessions at "
                        "the start of the test (all stopped)"
                    ),
                ),
            ],
        ),
        # Stage 1 -- bring iBGP UP first as the stable route source.
        create_steps_stage(
            steps=[
                _flap_bgp_peers(
                    peer_regex=ibgp_peer_regex,
                    start=True,
                    description=(
                        "2.9.6 -- bring iBGP peers UP first (stable route source "
                        "for the staggered eBGP dump)"
                    ),
                ),
                create_longevity_step(
                    duration=ibgp_source_settle_s,
                    description="2.9.6 -- settle after bringing iBGP up",
                ),
                # Withdraw every dedicated inject pool now that iBGP is UP (a LIVE
                # withdraw, the proven 2.9.4 pattern) so each wave/final advertise is a
                # genuinely-new +N at the eBGP egress. Inline RouteScale pools start
                # Active and toggle whole-pool, so withdraw each one whole. wave 0 comes
                # up after this seeing the reduced baseline; each later inject then
                # re-advertises a measurable +N (wave gaps +100 each, finals +50).
                *[
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=False,
                        prefix_pool_regex=regex,
                        prefix_start_index=0,
                        prefix_end_index=count,
                        description=(
                            f"2.9.6 -- withdraw dedicated inject pool [0, {count}) "
                            f"so its later advertise is a genuinely-new +N"
                        ),
                    )
                    for regex, count in _dedicated_inject_pools
                ],
                create_longevity_step(
                    duration=inject_settle_s,
                    description="2.9.6 -- settle after withdrawing the inject range",
                ),
                create_validation_step(
                    point_in_time_checks=[
                        *_no_crash_checks(),
                        _ibgp_up_check("staggered_ibgp_source_up"),
                        create_bgp_update_group_check(
                            expect_enabled=True,
                            peer_group_substrings=[ibgp_v6_peer_group],
                            check_id="staggered_ibgp_ug_formed",
                        ),
                    ],
                    description=(
                        "2.9.6 -- iBGP source up: iBGP sessions Established, iBGP "
                        "update group formed, no crash"
                    ),
                ),
            ],
        ),
    ]

    # Stage 2 -- staggered eBGP waves. After each wave settles, assert the eBGP
    # update group grew to the expected cumulative member count PER AFI (structural
    # proof the late peers joined + attached), iBGP is still up, and nothing
    # crashed. Between waves, inject new iBGP routes so later waves receive a larger
    # accumulated initial dump.
    for i, (start_idx, end_idx) in enumerate(waves):
        cum = cumulative_members_per_afi[i]
        wave_no = i + 1
        wave_steps: t.List[Step] = [
            create_start_stop_bgp_peers_step(
                peer_regex=ebgp_peer_regex,
                start=True,
                start_idx=start_idx,
                end_idx=end_idx,
                description=(
                    f"2.9.6 wave {wave_no}/{len(waves)} -- bring up eBGP sessions "
                    f"[{start_idx}, {end_idx}] per AFI"
                ),
            ),
            create_longevity_step(
                duration=wave_gap_s,
                description=(
                    f"2.9.6 wave {wave_no} -- {wave_gap_s}s gap for the new peers "
                    f"to receive their initial dump"
                ),
            ),
            create_validation_step(
                point_in_time_checks=[
                    *_no_crash_checks(),
                    _ibgp_up_check(f"staggered_wave{wave_no}_ibgp_up"),
                    create_bgp_update_group_check(
                        expect_enabled=True,
                        peer_group_substrings=[
                            ebgp_v4_peer_group,
                            ebgp_v6_peer_group,
                            ibgp_v6_peer_group,
                        ],
                        expected_member_counts={
                            ebgp_v4_peer_group: cum,
                            ebgp_v6_peer_group: cum,
                        },
                        check_id=f"staggered_wave{wave_no}_ug_membership",
                    ),
                ],
                description=(
                    f"2.9.6 wave {wave_no} -- eBGP update group grew to {cum} "
                    f"members/AFI (late peers joined + attached); iBGP up; no crash"
                ),
            ),
        ]
        # Snapshot the eBGP v4 baseline ONCE, when the first wave is up but before any
        # between-wave inject -- the reference for the criterion-1 accumulation delta
        # at all-up (the count must grow by total_wave_inject as the injects land, and
        # the uniform check then proves late-wave peers share that grown total).
        if i == 0 and ebgp_v4_peer_parent_prefixes is not None:
            wave_steps.append(
                create_snapshot_bgp_sent_route_counts_step(
                    hostname=device_name,
                    snapshot_key="staggered_accum_baseline",
                    peer_parent_prefixes=ebgp_v4_peer_parent_prefixes,
                    description=(
                        "2.9.6 criterion 1 -- snapshot eBGP v4 PS at wave 1 (baseline "
                        "for the between-wave accumulation delta)"
                    ),
                )
            )
        # Inject the between-wave routes AFTER this wave (feeds the NEXT wave's larger
        # dump) from this gap's DEDICATED unique-NLRI pool, advertised WHOLE so the +N
        # is measurable at the eBGP egress. The last wave has no between-wave inject
        # (the final runtime inject is separate, in Stage 3).
        if i < num_gaps:
            wave_steps.extend(
                [
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=True,
                        prefix_pool_regex=ibgp_wave_inject_pool_regexes[i],
                        prefix_start_index=0,
                        prefix_end_index=inject_per_wave,
                        description=(
                            f"2.9.6 wave {wave_no} -- inject {inject_per_wave} "
                            f"genuinely-new iBGP routes (dedicated pool, whole) before "
                            f"the next wave: later peers get a larger accumulated dump"
                        ),
                    ),
                    create_longevity_step(
                        duration=inject_settle_s,
                        description=(
                            f"2.9.6 wave {wave_no} -- settle after injecting iBGP routes"
                        ),
                    ),
                ]
            )
        stages.append(create_steps_stage(steps=wave_steps))

    # Stage 3 -- all peers up: full membership + STRICT distribution verifies
    # (accumulation delta + per-AFI uniform + per-AFI runtime +N) + no crash.
    steady_state_steps: t.List[Step] = [
        create_validation_step(
            point_in_time_checks=[
                *_no_crash_checks(),
                create_bgp_session_establish_check(
                    parent_prefixes_to_ignore=bgp_mon_ignore_prefixes,
                    retry_count=session_retry_count,
                    retry_delay_seconds=session_retry_delay_s,
                    check_id="staggered_all_up_sessions",
                ),
                create_bgp_update_group_check(
                    expect_enabled=True,
                    peer_group_substrings=[
                        ebgp_v4_peer_group,
                        ebgp_v6_peer_group,
                        ibgp_v6_peer_group,
                    ],
                    expected_member_counts={
                        ebgp_v4_peer_group: cumulative_members_per_afi[-1],
                        ebgp_v6_peer_group: cumulative_members_per_afi[-1],
                    },
                    check_id="staggered_all_up_ug_membership",
                ),
            ],
            description=(
                "2.9.6 -- all waves up: every eBGP peer Established + attached "
                "(full eBGP UG membership per AFI); iBGP up; no crash"
            ),
        ),
    ]
    # --- Criterion 1 (late-wave peers receive the FULL accumulated dump, INCLUDING
    # routes injected before they came up) -- MEASURABLE: the between-wave injects
    # used genuinely-new dedicated pools, so the eBGP v4 count must have grown by
    # ~total_wave_inject since the wave-1 baseline. The baseline is snapshotted at
    # wave 1 when only the FIRST wave is up, so ``min_baseline=1`` restricts the delta
    # to the wave-1 cohort (peers with a real baseline) -- the later waves were down
    # then (baseline 0) and would otherwise show a spurious whole-RIB delta. Those
    # late joiners are covered by the uniform check below (all peers identical), which
    # together with this delta proves the late waves also received the accumulated
    # dump, not merely a bare baseline.
    if ebgp_v4_peer_parent_prefixes is not None and total_wave_inject > 0:
        steady_state_steps.append(
            create_verify_bgp_sent_route_count_delta_step(
                hostname=device_name,
                snapshot_key="staggered_accum_baseline",
                peer_parent_prefixes=ebgp_v4_peer_parent_prefixes,
                min_delta=max(1, total_wave_inject - distribution_count_window),
                max_delta=total_wave_inject + distribution_count_window,
                tolerance=distribution_tolerance,
                min_baseline=1,
                description=(
                    f"2.9.6 criterion 1 -- the wave-1 eBGP v4 peers' count grew by "
                    f"~{total_wave_inject}: the between-wave injects reached the peers "
                    f"(uniform check proves late waves share the accumulated dump)"
                ),
            )
        )
    # --- Criteria 1 & 2 (late-wave peers received the full initial dump; route
    # counts identical on all eBGP peers) -- STRICT: every eBGP peer's PS is
    # non-zero and UNIFORM (spread <= distribution_count_window). Asserted at steady
    # state, after the staggered dump + between-wave injects settle, so a late peer
    # missing routes would show a lower count. BOTH AFIs STRICT (v4 + v6, HW-validated
    # bag013 2026-07-23); the v6 check keeps an escape hatch (default off) for the
    # cold-start next-hop slowness (Appendix B).
    if ebgp_v4_peer_parent_prefixes is not None:
        steady_state_steps.append(
            create_verify_bgp_sent_route_counts_uniform_step(
                hostname=device_name,
                peer_parent_prefixes=ebgp_v4_peer_parent_prefixes,
                min_count=1,
                max_spread=distribution_count_window,
                tolerance=distribution_tolerance,
                description=(
                    "2.9.6 criteria 1-2 -- every eBGP v4 peer has a NON-ZERO, "
                    "UNIFORM route count (late-wave peers caught up; no peer "
                    "missing routes)"
                ),
            )
        )
    if ebgp_v6_peer_parent_prefixes is not None:
        steady_state_steps.append(
            create_verify_bgp_sent_route_counts_uniform_step(
                hostname=device_name,
                peer_parent_prefixes=ebgp_v6_peer_parent_prefixes,
                min_count=1,
                max_spread=distribution_count_window,
                tolerance=distribution_tolerance,
                expected_fail=v6_distribution_expected_fail,
                expected_fail_reason=v6_distribution_expected_fail_reason,
                description=(
                    "2.9.6 criteria 1-2 (v6) -- every eBGP v6 peer has a NON-ZERO, "
                    "UNIFORM route count (STRICT; escape hatch off)"
                ),
            )
        )
    # --- Criterion 3 (runtime distribution reaches ALL 280 eBGP peers, spec step 6):
    # after all peers are up, inject genuinely-new routes from a DEDICATED unique-NLRI
    # pool per AFI (advertised WHOLE, accept communities -> re-advertised iBGP->eBGP)
    # and assert EVERY eBGP peer of that AFI RECEIVED them -- its PS grew by AT LEAST
    # ~final_inject_count. Both AFIs are covered (v4 pool -> v4 peers, v6 pool -> v6
    # peers). NO upper cap on the delta: the criterion is "all peers receive the routes"
    # (spec step 6), and the DUT may re-advertise a given AFI's EB-PRIVATE range with
    # expansion -- HW-observed on bag013 2026-07-23: a 50-prefix v6 inject re-advertised
    # as a UNIFORM +111 to all 140 v6 peers (v4 was exactly +50). The uniform delta =
    # every peer received it; the exact multiple is a DUT v6 re-advertisement detail,
    # not a distribution failure. ``min_delta`` is floored at 1 so it never degrades to
    # "grew by >= 0". An AFI is skipped only if its peer scope or inject pool is None.
    for afi_label, afi_parents, afi_pool in (
        ("v4", ebgp_v4_peer_parent_prefixes, ibgp_runtime_inject_pool_regex),
        ("v6", ebgp_v6_peer_parent_prefixes, ibgp_v6_runtime_inject_pool_regex),
    ):
        if afi_parents is None or afi_pool is None:
            continue
        snap_key = f"staggered_runtime_ebgp_{afi_label}"
        steady_state_steps.append(
            create_snapshot_bgp_sent_route_counts_step(
                hostname=device_name,
                snapshot_key=snap_key,
                peer_parent_prefixes=afi_parents,
                description=(
                    f"2.9.6 criterion 3 ({afi_label}) -- snapshot eBGP {afi_label} PS "
                    f"before the runtime inject"
                ),
            )
        )
        steady_state_steps.extend(
            [
                create_advertise_withdraw_prefixes_step(
                    device_name=device_name,
                    advertise=True,
                    prefix_pool_regex=afi_pool,
                    prefix_start_index=0,
                    prefix_end_index=final_inject_count,
                    description=(
                        f"2.9.6 runtime ({afi_label}) -- inject {final_inject_count} "
                        f"genuinely-new iBGP {afi_label} routes (dedicated pool, whole) "
                        f"after all peers are up"
                    ),
                ),
                create_longevity_step(
                    duration=inject_settle_s,
                    description=(
                        f"2.9.6 runtime ({afi_label}) -- settle after the final inject"
                    ),
                ),
            ]
        )
        steady_state_steps.append(
            create_verify_bgp_sent_route_count_delta_step(
                hostname=device_name,
                snapshot_key=snap_key,
                peer_parent_prefixes=afi_parents,
                min_delta=max(1, final_inject_count - distribution_count_window),
                # No max: see the block comment -- the criterion is "all peers receive
                # the routes"; the DUT may re-advertise more (v6 EB-PRIVATE expands).
                tolerance=distribution_tolerance,
                description=(
                    f"2.9.6 criterion 3 ({afi_label}) -- every eBGP {afi_label} peer's "
                    f"PS grew by >= ~{final_inject_count}: the runtime inject reached "
                    f"all peers"
                ),
            )
        )
    steady_state_steps.append(
        create_validation_step(
            point_in_time_checks=list(_no_crash_checks()),
            description="2.9.6 runtime -- no crash after the final inject",
        )
    )
    stages.append(create_steps_stage(steps=steady_state_steps))

    # Always-appended bounds (UG enabled; load-average never crosses baseline),
    # whether the caller takes the default ``BGP_STANDARD_POSTCHECKS`` bundle (which
    # asserts no stale routes -- spec pass-criterion 5) or supplies its own list, so
    # a caller-provided ``postchecks`` can never silently drop them.
    base_postchecks = (
        list(postchecks) if postchecks is not None else list(BGP_STANDARD_POSTCHECKS)
    )
    postchecks = base_postchecks + [
        create_system_cpu_load_average_check(baseline=load_avg_baseline),
        create_bgp_update_group_check(expect_enabled=True),
    ]
    # Optional absolute VmHWM ceiling (extra safety; consistent with the other UG
    # tests -- not a 2.9.6 pass-criterion). None -> skip.
    if vmhwm_absolute_threshold_bytes is not None:
        postchecks.append(
            create_memory_utilization_check(
                vmhwm_threshold=vmhwm_absolute_threshold_bytes
            )
        )
    if snapshot_checks is None:
        snapshot_checks = list(BGP_STANDARD_SNAPSHOT_CHECKS)

    return Playbook(
        name="bgp_ug_staggered_startup",
        stages=stages,
        prechecks=prechecks,
        postchecks=postchecks,
        snapshot_checks=snapshot_checks,
    )


def create_bgp_ug_best_path_change_playbook(
    *,
    device_name: str,
    # The two competing eBGP v4 pools (same NLRI, distinct names): Set A long
    # AS-PATH (less preferred), Set B short AS-PATH (preferred). Advertising Set B
    # flips the best-path A->B; withdrawing it flips back -- both Active toggles.
    ebgp_bestpath_a_pool_regex: str,
    ebgp_bestpath_b_pool_regex: str,
    # iBGP v4 peers (by peer-address subnet) for the measure-first PS probe. The
    # per-session peer-group field is not the AFI peer-group name on the full-scale
    # topology, so scope by subnet (same as 2.9.4 / 2.9.6). The v6 leg has its own
    # ``ibgp_v6_peer_parent_prefixes`` (see the IPv6 section below).
    ibgp_v4_peer_parent_prefixes: t.List[str],
    test_prefix_count: int = 500,
    # --- Strict criterion-1 (DUT-side best-path convergence) ---
    # When both ``test_prefix_parents`` and ``discriminator_asn`` are supplied, the
    # playbook ADDITIONALLY asserts (strictly) that the DUT converged every test
    # prefix's SELECTED best path to Set B. It baselines Set A's best-path AS-PATH
    # in stage 1 (Set A alone), then after the flip (step 4) and the final settle
    # (step 8) asserts each best path dropped by exactly ``best_path_as_path_delta``
    # occurrences of ``discriminator_asn`` (Set A -> Set B) with none stuck on Set
    # A. Reads the DUT Loc-RIB best path (correct under UG, no flap); combined with
    # the update-group membership check it establishes every group member received
    # Set B. Left unset => measure-first PS probe only (the pre-existing behavior).
    test_prefix_parents: t.Optional[t.List[str]] = None,
    discriminator_asn: t.Optional[int] = None,
    best_path_as_path_delta: int = 3,
    # Restrict best-path/per-peer matching to prefixes of exactly this mask length
    # (the v4 test prefixes are all /24). Excludes any aggregate/summary route that
    # falls inside ``test_prefix_parents`` so the matched count == the injected set.
    test_prefix_length: t.Optional[int] = None,
    strict_convergence_expected_fail: bool = False,
    strict_convergence_expected_fail_reason: t.Optional[str] = None,
    # --- IPv6 leg (opt-in) ---
    # When the v6 pool regexes are supplied, the playbook ALSO drives the eBGP v6
    # competing sets at every stage (advertise / withdraw / oscillate) and, when
    # ``test_prefix_parents_v6`` + ``discriminator_asn`` are set, runs the same STRICT
    # best-path convergence assertion for v6 (its own baseline snapshot key). v6 forms
    # its own update groups, so this exercises the best-path change on both AFIs. The
    # discriminator ASN + delta are shared with v4 (the eBGP peers are the same AS on
    # both AFIs). Left unset -> v4-only (byte-identical to the pre-v6 behavior).
    ebgp_bestpath_a_pool_regex_v6: t.Optional[str] = None,
    ebgp_bestpath_b_pool_regex_v6: t.Optional[str] = None,
    ibgp_v6_peer_parent_prefixes: t.Optional[t.List[str]] = None,
    test_prefix_parents_v6: t.Optional[t.List[str]] = None,
    # v6 analogue of ``test_prefix_length`` (the v6 test prefixes are all /64).
    test_prefix_length_v6: t.Optional[int] = None,
    # --- Per-peer distribution check (opt-in; the "better" / true per-peer gate) ---
    # When True, ALSO read each in-scope iBGP peer's post-policy adj-RIB-out
    # (getPostfilterAdvertisedNetworks, readable under UG since D109395098) and assert
    # every peer was advertised the winner for every test prefix -- catching a per-peer
    # split-brain the DUT-side Loc-RIB check cannot see. Runs for whichever AFIs have
    # their strict params set (reuses ibgp_v4/v6_peer_parent_prefixes + the same
    # discriminator/delta). Defaults to XFAIL (measure-first) while the
    # advertised-path AS-PATH delta is confirmed on HW, then flip to strict.
    per_peer_check: bool = False,
    # Per-AFI XFAIL knobs: the per-peer check can be strict on one AFI while
    # measure-first on the other (v4 distribution is confirmed on HW, so v4 goes
    # strict; v6 fans out more slowly, so it stays XFAIL until it demonstrably
    # completes distribution).
    per_peer_expected_fail_v4: bool = True,
    per_peer_expected_fail_v6: bool = True,
    per_peer_expected_fail_reason: t.Optional[str] = None,
    # --- Checks ---
    prechecks: t.List[PointInTimeHealthCheck],
    postchecks: t.Optional[t.List[PointInTimeHealthCheck]] = None,
    snapshot_checks: t.Optional[t.List[SnapshotHealthCheck]] = None,
    bgp_mon_ignore_prefixes: t.Optional[t.List[str]] = None,
    # --- Timing / oscillation ---
    op_settle_s: int = 90,
    converge_settle_s: int = 60,
    # Spec step 6: alternate the winning path every ~10s for 5 min. 30 flips x 10s
    # = 5 min; the even count ends on "advertise Set B" so the test settles on the
    # preferred (B) path (spec step 7 "ending on LOCAL_PREF 200").
    oscillation_flip_count: int = 30,
    oscillation_interval_s: int = 10,
    session_retry_count: int = 10,
    session_retry_delay_s: float = 30.0,
    load_avg_baseline: float = 12.0,
    vmhwm_absolute_threshold_bytes: t.Optional[int] = None,
) -> Playbook:
    """Build the BGP++ Update Group qualification 2.9.1 playbook (Best-Path Change
    During Active Distribution).

    Intent (spec 2.9.1): while the DUT is still distributing one path for a set of
    prefixes to a large update group, the best path changes -- verify every group
    member converges to the same final best path (no split-brain, no stale routes)
    and that rapid best-path oscillation neither crashes BGP++ nor corrupts
    update-group state.

    DISCRIMINATOR (DNE-approved deviation from the spec's LOCAL_PREF): LOCAL_PREF is
    non-transitive over eBGP and bag013's EB-FA-IN sets no LP (on-device policy dump
    P2421451582), so the best path is driven by AS-PATH LENGTH instead. Two eBGP
    "competing sets" advertise the SAME ``test_prefix_count`` v4 prefixes -- Set A
    with a long AS-PATH (less preferred), Set B short (preferred; both built at
    config time via each pool's ``RouteScale.as_path_prepend_numbers``). Advertising
    Set B flips the best path A->B; withdrawing it flips back -- both are IXIA Active
    toggles (``create_advertise_withdraw_prefixes_step``), so no session flaps.

    DUAL-AFI: when the ``*_v6`` knobs are supplied, the same competition + strict
    convergence runs on the eBGP v6 sets in lock-step at every stage (v6 forms its
    own update groups), so 2.9.1 exercises the best-path change on both v4 and v6.
    v6 runs strict from the start -- next-hop-self resolves v6 next-hops
    deterministically under WITHOUT_OPEN_R, so there is no cold-start distribution
    delay. Left unset -> v4-only.

    STRICT CRITERION-1 (spec steps 4/5/8, pass-criteria 1/3) -- DUT-side best-path
    convergence: when ``test_prefix_parents`` + ``discriminator_asn`` are supplied,
    the playbook baselines Set A's best-path AS-PATH while only Set A is up (stage 1)
    and, after the flip and after the final settle, asserts the DUT's SELECTED best
    path for EVERY test prefix converged to Set B (baseline ``discriminator_asn``
    count minus ``best_path_as_path_delta``), with none stuck on Set A. This reads
    the DUT Loc-RIB (best-path selection), which is populated and correct under
    Update Group -- unlike adj-RIB-out (T271301144) -- and needs no BGP flap. This
    verifies the best-path DECISION converged to Set B for every prefix. Under
    Update Group the DUT distributes that one best path to all group members by
    construction, and the playbook separately confirms the UG is enabled
    (``BGP_UPDATE_GROUP_CHECK``) and every session Established
    (``BGP_SESSION_ESTABLISH_CHECK``). It does NOT independently read each peer's
    adj-RIB-out, so a per-peer split-brain -- DUT selects Set B but fails to
    re-advertise it to some member -- is OUT OF SCOPE here; a true per-peer
    IXIA-side learned-route reader is the deferred enhancement (T271301144).

    The iBGP-v4 PS gauge is ALSO probed (snapshot -> log, measure-first) around each
    phase as a diagnostic: it reveals whether the DUT advertises the test prefixes
    at all (the next-hop-self precondition) and that the count stays
    ~``test_prefix_count`` across the flips (no route loss). The PS gauge is a COUNT
    and cannot itself see a best-path flip (the prefix count is unchanged when only
    the path changes) -- which is exactly why the DUT best-path RIB check above is
    needed for criterion-1.

    What lands UNCONDITIONALLY (the adversarial substance -- spec pass-criteria
    2/4/5): rapid best-path oscillation does not crash BGP++, does not disrupt
    sessions, keeps the update group intact, and produces no stale routes /
    Emergency-Critical-Error logs (the always-appended postchecks).
    """
    # The oscillation ends on "advertise Set B" (the winner) only if the flip count
    # is EVEN -- the loop starts from "Set B advertised" (Stage 2), so flip 0 withdraws
    # B and an even count lands the last flip back on advertise-B. An odd count would
    # leave Set A winning and make the Stage-4 "converged on Set B" assertion fail.
    # Enforce the invariant instead of relying on the caller.
    if oscillation_flip_count % 2 != 0:
        raise ValueError(
            f"oscillation_flip_count must be EVEN so the oscillation ends on Set B "
            f"(spec steps 7-8); got {oscillation_flip_count}."
        )

    def _validation(check_id_prefix: str, description: str) -> Step:
        """No crash + all sessions Established + update group intact -- re-asserted
        after every best-path change (a flip must not crash, drop sessions, or
        merge/tear the update group)."""
        return create_validation_step(
            point_in_time_checks=[
                *_no_crash_checks(),
                create_bgp_session_establish_check(
                    parent_prefixes_to_ignore=bgp_mon_ignore_prefixes,
                    retry_count=session_retry_count,
                    retry_delay_seconds=session_retry_delay_s,
                    check_id=f"{check_id_prefix}_sessions",
                ),
                create_bgp_update_group_check(
                    expect_enabled=True,
                    check_id=f"{check_id_prefix}_ug",
                ),
            ],
            description=description,
        )

    def _probe(key: str, note: str) -> Step:
        """Measure-first: snapshot the iBGP v4 PS gauge (logs the non-zero peer
        count + a sample). Does NOT assert -- it reveals whether the DUT advertises
        the test prefixes and whether the count holds across the flips."""
        return create_snapshot_bgp_sent_route_counts_step(
            hostname=device_name,
            snapshot_key=key,
            peer_parent_prefixes=ibgp_v4_peer_parent_prefixes,
            description=f"2.9.1 {note} -- probe iBGP v4 PS (measure-first)",
        )

    # Strict criterion-1 (DUT-side): baseline Set A's best-path AS-PATH while only
    # Set A is up (stage 1), then assert convergence to Set B after the flip and
    # after the final settle. Gated on the caller supplying both the test-prefix
    # scope and the discriminator ASN.
    strict_convergence = (
        test_prefix_parents is not None and discriminator_asn is not None
    )
    _bp_snapshot_key = "dut_best_path_baseline"

    def _snapshot_best_path() -> Step:
        return create_snapshot_bgp_dut_best_path_as_path_step(
            hostname=device_name,
            snapshot_key=_bp_snapshot_key,
            test_prefix_parents=test_prefix_parents or [],
            discriminator_asn=discriminator_asn or 0,
            expected_prefix_count=test_prefix_count,
            test_prefix_length=test_prefix_length,
            description=(
                "2.9.1 baseline -- record the DUT best-path AS-PATH while only Set A "
                "(loser, long AS-PATH) is advertised"
            ),
        )

    def _verify_converged(step_note: str) -> Step:
        return create_verify_bgp_dut_best_path_as_path_converged_step(
            hostname=device_name,
            snapshot_key=_bp_snapshot_key,
            test_prefix_parents=test_prefix_parents or [],
            discriminator_asn=discriminator_asn or 0,
            expected_prefix_count=test_prefix_count,
            expected_as_path_delta=best_path_as_path_delta,
            expected_fail=strict_convergence_expected_fail,
            expected_fail_reason=strict_convergence_expected_fail_reason,
            test_prefix_length=test_prefix_length,
            description=(
                f"2.9.1 {step_note} -- STRICT: DUT converged every test prefix's "
                f"best path to Set B (none stuck on Set A)"
            ),
        )

    # IPv6 leg: same competition + strict convergence on the eBGP v6 sets, gated on
    # the caller supplying the v6 pool regexes. Its own baseline snapshot key so it
    # never collides with the v4 baseline.
    _v6 = (
        ebgp_bestpath_a_pool_regex_v6 is not None
        and ebgp_bestpath_b_pool_regex_v6 is not None
    )
    strict_convergence_v6 = (
        _v6 and test_prefix_parents_v6 is not None and discriminator_asn is not None
    )
    _v6_probe = _v6 and bool(ibgp_v6_peer_parent_prefixes)
    _bp_snapshot_key_v6 = "dut_best_path_baseline_v6"

    def _toggle_v6(pool_regex: t.Optional[str], advertise: bool, note: str) -> Step:
        # Only reached when ``_v6`` is True, i.e. both v6 pool regexes are set.
        assert pool_regex is not None
        return create_advertise_withdraw_prefixes_step(
            device_name=device_name,
            advertise=advertise,
            prefix_pool_regex=pool_regex,
            prefix_start_index=0,
            description=f"2.9.1 (v6) {note}",
        )

    def _probe_v6(key: str, note: str) -> Step:
        return create_snapshot_bgp_sent_route_counts_step(
            hostname=device_name,
            snapshot_key=key,
            peer_parent_prefixes=ibgp_v6_peer_parent_prefixes or [],
            description=f"2.9.1 (v6) {note} -- probe iBGP v6 PS (measure-first)",
        )

    def _snapshot_best_path_v6() -> Step:
        return create_snapshot_bgp_dut_best_path_as_path_step(
            hostname=device_name,
            snapshot_key=_bp_snapshot_key_v6,
            test_prefix_parents=test_prefix_parents_v6 or [],
            discriminator_asn=discriminator_asn or 0,
            expected_prefix_count=test_prefix_count,
            test_prefix_length=test_prefix_length_v6,
            description=(
                "2.9.1 (v6) baseline -- record the DUT best-path AS-PATH while only "
                "Set A (loser, long AS-PATH) is advertised"
            ),
        )

    def _verify_converged_v6(step_note: str) -> Step:
        return create_verify_bgp_dut_best_path_as_path_converged_step(
            hostname=device_name,
            snapshot_key=_bp_snapshot_key_v6,
            test_prefix_parents=test_prefix_parents_v6 or [],
            discriminator_asn=discriminator_asn or 0,
            expected_prefix_count=test_prefix_count,
            expected_as_path_delta=best_path_as_path_delta,
            expected_fail=strict_convergence_expected_fail,
            expected_fail_reason=strict_convergence_expected_fail_reason,
            test_prefix_length=test_prefix_length_v6,
            description=(
                f"2.9.1 (v6) {step_note} -- STRICT: DUT converged every test prefix's "
                f"best path to Set B (none stuck on Set A)"
            ),
        )

    # Per-peer distribution check (the "better" gate): read each iBGP peer's advertised
    # adj-RIB-out and assert it got the winner. Runs per AFI that has its strict params
    # set. Its own snapshot keys, distinct from the DUT-side ones.
    per_peer_v4 = per_peer_check and strict_convergence
    per_peer_v6 = (
        per_peer_check and strict_convergence_v6 and bool(ibgp_v6_peer_parent_prefixes)
    )

    def _pp_snapshot(
        key: str,
        peer_parents: t.List[str],
        test_parents: t.Optional[t.List[str]],
        note: str,
        xfail: bool,
        tpl: t.Optional[int],
    ) -> Step:
        return create_snapshot_bgp_peer_advertised_as_path_step(
            hostname=device_name,
            snapshot_key=key,
            peer_parent_prefixes=peer_parents,
            test_prefix_parents=test_parents or [],
            discriminator_asn=discriminator_asn or 0,
            expected_prefix_count=test_prefix_count,
            expected_fail=xfail,
            expected_fail_reason=per_peer_expected_fail_reason,
            test_prefix_length=tpl,
            description=f"2.9.1 {note} -- per-peer baseline (advertised adj-RIB-out)",
        )

    def _pp_verify(
        key: str,
        peer_parents: t.List[str],
        test_parents: t.Optional[t.List[str]],
        note: str,
        xfail: bool,
        tpl: t.Optional[int],
    ) -> Step:
        return create_verify_bgp_peer_advertised_as_path_converged_step(
            hostname=device_name,
            snapshot_key=key,
            peer_parent_prefixes=peer_parents,
            test_prefix_parents=test_parents or [],
            discriminator_asn=discriminator_asn or 0,
            expected_prefix_count=test_prefix_count,
            expected_as_path_delta=best_path_as_path_delta,
            expected_fail=xfail,
            expected_fail_reason=per_peer_expected_fail_reason,
            test_prefix_length=tpl,
            description=f"2.9.1 {note} -- per-peer verify (every peer got the winner)",
        )

    stages = [
        # Stage 0: setup + baseline. Both competing pools carry genuinely-new
        # prefixes advertised ON TOP of the existing routes, so deactivate both at
        # baseline (like 2.9.4's spare pools) -- step 1/2 then advertise them.
        create_steps_stage(
            steps=[
                create_advertise_withdraw_prefixes_step(
                    device_name=device_name,
                    advertise=False,
                    prefix_pool_regex=ebgp_bestpath_a_pool_regex,
                    prefix_start_index=0,
                    description=(
                        "2.9.1 setup -- withdraw the Set A (long AS-PATH) pool so it "
                        "is inactive at baseline"
                    ),
                ),
                create_advertise_withdraw_prefixes_step(
                    device_name=device_name,
                    advertise=False,
                    prefix_pool_regex=ebgp_bestpath_b_pool_regex,
                    prefix_start_index=0,
                    description=(
                        "2.9.1 setup -- withdraw the Set B (short AS-PATH) pool so it "
                        "is inactive at baseline"
                    ),
                ),
                *(
                    [
                        _toggle_v6(
                            ebgp_bestpath_a_pool_regex_v6,
                            False,
                            "setup -- withdraw v6 Set A pool (inactive at baseline)",
                        ),
                        _toggle_v6(
                            ebgp_bestpath_b_pool_regex_v6,
                            False,
                            "setup -- withdraw v6 Set B pool (inactive at baseline)",
                        ),
                    ]
                    if _v6
                    else []
                ),
                create_longevity_step(
                    duration=op_settle_s,
                    description="2.9.1 setup -- settle after deactivating both competing pools",
                ),
                _validation(
                    "bestpath_baseline",
                    "2.9.1 baseline -- BGP up, sessions Established, update group "
                    "enabled; both competing pools inactive",
                ),
                _probe("bp_baseline", "baseline"),
            ],
        ),
        # Stage 1 (spec step 1): advertise the 500 prefixes from the FIRST eBGP set
        # (Set A, long AS-PATH) and let the DUT distribute them.
        create_steps_stage(
            steps=[
                create_advertise_withdraw_prefixes_step(
                    device_name=device_name,
                    advertise=True,
                    prefix_pool_regex=ebgp_bestpath_a_pool_regex,
                    prefix_start_index=0,
                    description=(
                        f"2.9.1 step 1 -- advertise {test_prefix_count} prefixes from "
                        f"the first eBGP set (Set A, long AS-PATH)"
                    ),
                ),
                *(
                    [
                        _toggle_v6(
                            ebgp_bestpath_a_pool_regex_v6,
                            True,
                            f"step 1 -- advertise {test_prefix_count} v6 prefixes from "
                            f"the first eBGP set (Set A, long AS-PATH)",
                        )
                    ]
                    if _v6
                    else []
                ),
                create_longevity_step(
                    duration=op_settle_s,
                    description="2.9.1 step 1 -- wait for all peers to receive Set A",
                ),
                _probe("bp_after_a", "after Set A advertise"),
                *(
                    [_probe_v6("bp_after_a_v6", "after Set A advertise")]
                    if _v6_probe
                    else []
                ),
                # STRICT baseline: with only Set A up, record its (uniform)
                # best-path AS-PATH so the post-flip verify can prove convergence
                # to Set B without hard-coding absolute AS-PATH values.
                *([_snapshot_best_path()] if strict_convergence else []),
                *([_snapshot_best_path_v6()] if strict_convergence_v6 else []),
                # Per-peer baseline (advertised adj-RIB-out) while only Set A is up.
                *(
                    [
                        _pp_snapshot(
                            "pp_v4",
                            ibgp_v4_peer_parent_prefixes,
                            test_prefix_parents,
                            "step 1 v4",
                            per_peer_expected_fail_v4,
                            test_prefix_length,
                        )
                    ]
                    if per_peer_v4
                    else []
                ),
                *(
                    [
                        _pp_snapshot(
                            "pp_v6",
                            ibgp_v6_peer_parent_prefixes or [],
                            test_prefix_parents_v6,
                            "step 1 v6",
                            per_peer_expected_fail_v6,
                            test_prefix_length_v6,
                        )
                    ]
                    if per_peer_v6
                    else []
                ),
                _validation(
                    "bestpath_after_a",
                    "2.9.1 step 1 -- Set A distributing; no crash; sessions up; UG intact",
                ),
            ],
        ),
        # Stage 2 (spec steps 2-4): immediately re-advertise the SAME prefixes from a
        # DIFFERENT eBGP set (Set B, short AS-PATH) while Set A may still be
        # distributing -> best-path change A->B. Converge, then re-assert stability.
        create_steps_stage(
            steps=[
                create_advertise_withdraw_prefixes_step(
                    device_name=device_name,
                    advertise=True,
                    prefix_pool_regex=ebgp_bestpath_b_pool_regex,
                    prefix_start_index=0,
                    description=(
                        f"2.9.1 step 2 -- immediately re-advertise the same "
                        f"{test_prefix_count} prefixes from a DIFFERENT eBGP set "
                        f"(Set B, short AS-PATH, higher preference) -> best-path change"
                    ),
                ),
                *(
                    [
                        _toggle_v6(
                            ebgp_bestpath_b_pool_regex_v6,
                            True,
                            f"step 2 -- re-advertise the same {test_prefix_count} v6 "
                            f"prefixes from a DIFFERENT eBGP set (Set B, short AS-PATH) "
                            f"-> best-path change",
                        )
                    ]
                    if _v6
                    else []
                ),
                create_longevity_step(
                    duration=converge_settle_s,
                    description="2.9.1 step 3 -- wait for convergence after the best-path change",
                ),
                _probe("bp_after_flip", "after best-path flip to Set B"),
                *(
                    [_probe_v6("bp_after_flip_v6", "after best-path flip to Set B")]
                    if _v6_probe
                    else []
                ),
                # STRICT (spec step 4/5): every test prefix's DUT best path is now
                # Set B (baseline count - delta), none stuck on Set A.
                *([_verify_converged("step 4")] if strict_convergence else []),
                *([_verify_converged_v6("step 4")] if strict_convergence_v6 else []),
                # Per-peer: every iBGP peer was actually advertised Set B.
                *(
                    [
                        _pp_verify(
                            "pp_v4",
                            ibgp_v4_peer_parent_prefixes,
                            test_prefix_parents,
                            "step 4 v4",
                            per_peer_expected_fail_v4,
                            test_prefix_length,
                        )
                    ]
                    if per_peer_v4
                    else []
                ),
                *(
                    [
                        _pp_verify(
                            "pp_v6",
                            ibgp_v6_peer_parent_prefixes or [],
                            test_prefix_parents_v6,
                            "step 4 v6",
                            per_peer_expected_fail_v6,
                            test_prefix_length_v6,
                        )
                    ]
                    if per_peer_v6
                    else []
                ),
                _validation(
                    "bestpath_after_flip",
                    "2.9.1 step 4 -- after the best-path change: no split-brain crash; "
                    "sessions Established; update group intact",
                ),
            ],
        ),
    ]

    # Stage 3 (spec step 6): rapid best-path oscillation -- alternate the winning set
    # every ``oscillation_interval_s`` for ~5 min by toggling Set B (Active toggle,
    # no session flap): B advertised -> best-path B; B withdrawn -> best-path A.
    # Start state is "Set B advertised" (Stage 2), so flip 0 withdraws; an even
    # ``oscillation_flip_count`` ends on "advertise Set B" (settles on Set B).
    oscillation_steps: t.List[Step] = []
    for i in range(oscillation_flip_count):
        advertise_b = i % 2 == 1
        oscillation_steps.append(
            create_advertise_withdraw_prefixes_step(
                device_name=device_name,
                advertise=advertise_b,
                prefix_pool_regex=ebgp_bestpath_b_pool_regex,
                prefix_start_index=0,
                description=(
                    f"2.9.1 step 6 -- flip {i + 1}/{oscillation_flip_count}: "
                    f"{'advertise' if advertise_b else 'withdraw'} Set B "
                    f"(best-path -> {'B' if advertise_b else 'A'})"
                ),
            )
        )
        if _v6:
            oscillation_steps.append(
                _toggle_v6(
                    ebgp_bestpath_b_pool_regex_v6,
                    advertise_b,
                    f"step 6 -- flip {i + 1}/{oscillation_flip_count}: "
                    f"{'advertise' if advertise_b else 'withdraw'} v6 Set B "
                    f"(best-path -> {'B' if advertise_b else 'A'})",
                )
            )
        oscillation_steps.append(
            create_longevity_step(
                duration=oscillation_interval_s,
                description=f"2.9.1 step 6 -- {oscillation_interval_s}s before the next flip",
            )
        )
    oscillation_steps.append(
        create_validation_step(
            point_in_time_checks=list(_no_crash_checks()),
            description=(
                f"2.9.1 step 6 -- no crash after {oscillation_flip_count} rapid "
                f"best-path flips over ~{oscillation_flip_count * oscillation_interval_s // 60} min"
            ),
        )
    )
    stages.append(create_steps_stage(steps=oscillation_steps))

    # Stage 4 (spec steps 7-8): the oscillation stopped on "advertise Set B"; settle
    # and verify convergence on the preferred (B) path -- measure-first.
    stages.append(
        create_steps_stage(
            steps=[
                create_longevity_step(
                    duration=converge_settle_s,
                    description=(
                        "2.9.1 step 7 -- wait for full convergence after the rapid "
                        "alternation stops (ending on Set B)"
                    ),
                ),
                _probe("bp_final", "final (converged on Set B)"),
                *(
                    [_probe_v6("bp_final_v6", "final (converged on Set B)")]
                    if _v6_probe
                    else []
                ),
                # STRICT (spec step 8): after the rapid oscillation ends on Set B,
                # every test prefix's DUT best path is Set B -- no peer stuck on the
                # old (Set A) path after the churn.
                *([_verify_converged("step 8 final")] if strict_convergence else []),
                *(
                    [_verify_converged_v6("step 8 final")]
                    if strict_convergence_v6
                    else []
                ),
                # Per-peer: every iBGP peer still advertised Set B after the churn.
                *(
                    [
                        _pp_verify(
                            "pp_v4",
                            ibgp_v4_peer_parent_prefixes,
                            test_prefix_parents,
                            "step 8 final v4",
                            per_peer_expected_fail_v4,
                            test_prefix_length,
                        )
                    ]
                    if per_peer_v4
                    else []
                ),
                *(
                    [
                        _pp_verify(
                            "pp_v6",
                            ibgp_v6_peer_parent_prefixes or [],
                            test_prefix_parents_v6,
                            "step 8 final v6",
                            per_peer_expected_fail_v6,
                            test_prefix_length_v6,
                        )
                    ]
                    if per_peer_v6
                    else []
                ),
                _validation(
                    "bestpath_final",
                    "2.9.1 step 8 -- converged on Set B: no crash; all sessions "
                    "Established; update group intact (no peer stuck / no stale routes)",
                ),
            ],
        )
    )

    # Always-appended bounds so they can never be dropped whether the caller takes
    # the default BGP_STANDARD_POSTCHECKS bundle (which asserts no stale routes --
    # spec pass-criterion 3 -- but NOT device-log severity) or supplies its own
    # list: UG enabled, load-average within baseline, and a system-log severity
    # scan (spec pass-criterion 5: no Emergency/Critical/Error logs over the test
    # window; the bare/agent-less LOG_PARSING_CHECK routes to the EOS
    # "show logging emergencies/critical/errors" path).
    base_postchecks = (
        list(postchecks) if postchecks is not None else list(BGP_STANDARD_POSTCHECKS)
    )
    postchecks = base_postchecks + [
        create_system_cpu_load_average_check(baseline=load_avg_baseline),
        create_bgp_update_group_check(expect_enabled=True),
        create_log_parsing_check(start_time_jq_var="test_case_start_time"),
    ]
    if vmhwm_absolute_threshold_bytes is not None:
        postchecks.append(
            create_memory_utilization_check(
                vmhwm_threshold=vmhwm_absolute_threshold_bytes
            )
        )
    if snapshot_checks is None:
        snapshot_checks = list(BGP_STANDARD_SNAPSHOT_CHECKS)

    return Playbook(
        name="bgp_ug_best_path_change",
        stages=stages,
        prechecks=prechecks,
        postchecks=postchecks,
        snapshot_checks=snapshot_checks,
    )


# =============================================================================
# 2.9.8 Quantifying CPU reduction from Update Group
# =============================================================================
#
# The spec runs the SAME 1-hour route-churn workload TWICE -- Update Group OFF
# (baseline) vs ON -- and compares CPU: with UG on the average CPU must be
# measurably lower, peak CPU < 40% in both runs, VmHWM < 10 GB in both, no crash,
# no session flaps, and 1m/5m/15m load-average < 12. Because UG optimizes EGRESS
# (update packing), the DUT must actually advertise the full table -- otherwise
# there is no egress work for UG to reduce and no measurable difference. This runs
# WITHOUT_OPEN_R + next-hop-self (the bgpcpp interface-state gflag), which resolves
# the iBGP next-hops so the DUT advertises the full table with no Open/R dependency.
#
# Two runs => two TestConfigs (enable_update_group False vs True). Each run's
# playbook (this factory, one variant):
#   - churns ``route_churn_count`` eBGP routes/peer every minute for the hour
#     (withdraw -> 30s -> re-advertise with a rotated community) -- the CPU
#     stimulus, reusing the 2.9.2 route-churn track;
#   - runs ``bgp_cpu_utilization_monitor`` spanning the hour: samples device CPU%,
#     records avg + peak, FAILs on peak >= 40% (crit 2), reads VmHWM (crit 3), and
#     PERSISTS its metrics to a per-variant file;
#   - runs a session-stability + load-average monitor (the 2.9.2 monitor track,
#     scoped to ALL non-MON sessions since 2.9.8 flaps nothing) -- crit 4 (no
#     crash), crit 5 (no flaps), crit 6 (load-avg).
# The UG-ON run additionally runs ``bgp_cpu_reduction_compare`` at the end, reading
# the UG-off baseline file + its own and asserting the average dropped (crit 1) --
# so the UG-OFF config MUST run before the UG-ON config (metrics handoff via a file
# on the runner).


def create_bgp_ug_cpu_quantification_playbook(
    *,
    device_name: str,
    # One ORDERED list of pre-staged community-variant pool regexes PER AFI
    # (e.g. [[v4_A, v4_B, v4_C], [v6_A, v6_B, v6_C]]) -- 2.9.8 runs one rotation
    # track per AFI, each rotating its variants A->B->C->A, so v4 and v6 get the
    # same treatment.
    variant_pool_regexes_by_afi: t.List[t.List[str]],
    # BGP-MON parent(s) only -- 2.9.8 does not flap sessions, so the monitor
    # asserts EVERY non-MON session stays Established throughout (crit 5, no flaps).
    all_sessions_ignore_prefixes: t.List[str],
    # This run's CPU-metrics output file (the monitor writes it).
    cpu_metrics_file_path: str,
    variant: str,
    # UG-ON run only: the UG-off baseline metrics file to compare against. None on
    # the UG-off run (no comparison stage).
    baseline_metrics_file_path: t.Optional[str] = None,
    # --- Checks ---
    prechecks: t.List[PointInTimeHealthCheck],
    postchecks: t.Optional[t.List[PointInTimeHealthCheck]] = None,
    snapshot_checks: t.Optional[t.List[SnapshotHealthCheck]] = None,
    # --- Tunables (spec defaults) ---
    route_churn_count: int = 500,
    route_churn_interval_s: int = 60,
    # Settle after the prime stage (before the measured churn+monitor stage) so the
    # DUT converges from the one-time prime route change and the CPU monitor does
    # not fold that startup convergence into the measured window (protects crit-2).
    prime_settle_s: int = 60,
    duration_s: int = 3600,
    cpu_sample_interval_s: int = 15,
    peak_cpu_threshold_percent: float = 40.0,
    min_reduction_percent: float = 0.0,
    monitor_interval_s: int = 120,
    monitor_retry_count: int = 3,
    monitor_retry_delay_s: float = 10.0,
    load_avg_baseline: float = 12.0,
    vmhwm_absolute_threshold_bytes: t.Optional[int] = None,
    expect_update_group_enabled: bool = True,
) -> Playbook:
    """Build the BGP++ Update Group qualification 2.9.8 playbook (Quantifying CPU
    reduction from Update Group) -- ONE variant (UG off or on).

    Intent (spec 2.9.8): run the identical 1-hour churn workload with UG off then
    on; UG-on average CPU must be measurably lower, with peak CPU < 40%, VmHWM
    < 10 GB, no crash, no session flaps, and load-average < 12 in both runs.

    Structure -- a sequential PRIME stage, then one concurrent stage of tracks for
    ``duration_s`` (1 hr):
      0. Prime (``_variant_pool_prime_steps``, per AFI): the pre-staged variant
         pools all come up Active at build (same NLRI), so withdraw EVERY variant
         then re-advertise only variant[0] -> exactly one community per prefix
         before the measured churn.
      1. Route churn (``_route_churn_track_steps``), one rotation track per AFI in
         ``variant_pool_regexes_by_afi`` (BOTH AFIs get the same treatment): every
         ``route_churn_interval_s`` (60s) withdraw the active variant pool (500
         routes/peer), wait 30s, advertise the NEXT variant (a DIFFERENT build-time
         community) -- the CPU stimulus with NO runtime community write (Option A).
      2. CPU-utilization monitor (``bgp_cpu_utilization_monitor`` custom step):
         sample device CPU% every ``cpu_sample_interval_s``, record avg + peak,
         FAIL if peak >= ``peak_cpu_threshold_percent`` (crit 2), read VmHWM and
         FAIL if >= ``vmhwm_absolute_threshold_bytes`` (crit 3), and persist
         {variant, avg, peak, vmhwm} to ``cpu_metrics_file_path``.
      3. Session-stability + load monitor (``_monitor_track_steps``, scoped to all
         non-MON sessions): every ``monitor_interval_s`` assert no crash (crit 4),
         all sessions Established (crit 5, no flaps), load-average < baseline
         (crit 6).

    When ``baseline_metrics_file_path`` is set (the UG-ON run), a final stage runs
    ``bgp_cpu_reduction_compare`` to assert UG-on avg CPU is measurably lower than
    UG-off (crit 1) -- so the UG-OFF run must complete first (file handoff).

    ``expect_update_group_enabled`` appends a UG-enabled postcheck on the UG-ON run
    (omitted on the UG-off baseline, where UG is intentionally disabled).
    """
    cpu_monitor_params: t.Dict[str, t.Any] = {
        "custom_step_name": "bgp_cpu_utilization_monitor",
        "hostname": device_name,
        "duration_seconds": duration_s,
        "sample_interval_seconds": cpu_sample_interval_s,
        "metrics_file_path": cpu_metrics_file_path,
        "variant": variant,
        "peak_cpu_threshold_percent": peak_cpu_threshold_percent,
    }
    if vmhwm_absolute_threshold_bytes is not None:
        cpu_monitor_params["vmhwm_threshold_bytes"] = vmhwm_absolute_threshold_bytes

    concurrent_steps = [
        # One route-churn ROTATION track per AFI (v4 + v6) -- both AFIs churned
        # equally so the CPU comparison exercises every AFI's update groups. Each
        # track rotates its ordered pre-staged community-variant pools (A->B->C->A)
        # via pure Active-flag toggles: no runtime community write (which IxNetwork
        # rejects on a started element) and no peer bounce.
        *[
            ConcurrentStep(
                steps=_route_churn_track_steps(
                    device_name=device_name,
                    route_count=route_churn_count,
                    interval_s=route_churn_interval_s,
                    duration_s=duration_s,
                    variant_pool_regexes=variant_pool_regexes,
                )
            )
            for variant_pool_regexes in variant_pool_regexes_by_afi
        ],
        ConcurrentStep(
            steps=[
                create_custom_step(
                    params_dict=cpu_monitor_params,
                    description=(
                        f"2.9.8 ({variant}) -- sample device CPU% over the "
                        f"{duration_s}s churn window; record avg+peak; FAIL if peak "
                        f">= {peak_cpu_threshold_percent}%; record VmHWM; persist "
                        f"metrics for the UG-off/on comparison"
                    ),
                ),
            ]
        ),
        ConcurrentStep(
            steps=_monitor_track_steps(
                non_ibgp_parent_prefixes=all_sessions_ignore_prefixes,
                load_avg_baseline=load_avg_baseline,
                interval_s=monitor_interval_s,
                duration_s=duration_s,
                retry_count=monitor_retry_count,
                retry_delay_s=monitor_retry_delay_s,
            )
        ),
    ]

    # Sequential PRIME stage: the variant pools all come up Active at build (same
    # NLRI per AFI), so reduce each AFI to a single-active baseline (only
    # variant[0] advertised) BEFORE the measured churn, so exactly one community is
    # on the wire per prefix when the rotation starts (no ambiguous multi-active).
    prime_steps: t.List[Step] = []
    for variant_pool_regexes in variant_pool_regexes_by_afi:
        prime_steps.extend(
            _variant_pool_prime_steps(
                device_name=device_name,
                variant_pool_regexes=variant_pool_regexes,
            )
        )
    # Let the one-time prime route change converge before the measured window.
    prime_steps.append(create_longevity_step(duration=prime_settle_s))

    stages = [
        create_steps_stage(
            steps=prime_steps,
            description=(
                f"2.9.8 ({variant}) -- prime variant pools to a single-active "
                f"baseline (only variant[0] per AFI advertised) before churn"
            ),
        ),
        create_steps_stage(
            concurrent=True,
            concurrent_steps=concurrent_steps,
            description=(
                f"2.9.8 ({variant}) -- 1-hour eBGP route churn "
                f"({route_churn_count} routes/peer/min) + CPU-utilization monitor "
                f"+ session/load monitor"
            ),
        ),
    ]

    # UG-ON run: compare against the UG-off baseline (crit 1). Runs last, after the
    # monitor has written this run's metrics file. Skipped on the UG-off run.
    if baseline_metrics_file_path is not None:
        compare_params: t.Dict[str, t.Any] = {
            "custom_step_name": "bgp_cpu_reduction_compare",
            "baseline_metrics_path": baseline_metrics_file_path,
            "ug_metrics_path": cpu_metrics_file_path,
            "min_reduction_percent": min_reduction_percent,
            "peak_cpu_threshold_percent": peak_cpu_threshold_percent,
        }
        if vmhwm_absolute_threshold_bytes is not None:
            compare_params["vmhwm_threshold_bytes"] = vmhwm_absolute_threshold_bytes
        stages.append(
            create_steps_stage(
                steps=[
                    create_custom_step(
                        params_dict=compare_params,
                        description=(
                            "2.9.8 -- compare UG-on vs UG-off CPU: assert UG-on avg "
                            "CPU measurably lower (crit 1); both peaks < ceiling; "
                            "both VmHWM < ceiling"
                        ),
                    ),
                ],
            )
        )

    # Always-appended bounds. The monitor track already asserts no-crash /
    # sessions-up / load-avg PER SAMPLE across the hour; these postchecks re-assert
    # at test end (load-avg) + add the no-Error-logs gate. The UG-ON run also
    # asserts UG is still enabled (omitted on the UG-off baseline).
    base_postchecks = (
        list(postchecks) if postchecks is not None else list(BGP_STANDARD_POSTCHECKS)
    )
    postchecks = base_postchecks + [
        create_system_cpu_load_average_check(baseline=load_avg_baseline),
        create_log_parsing_check(start_time_jq_var="test_case_start_time"),
    ]
    if expect_update_group_enabled:
        postchecks.append(create_bgp_update_group_check(expect_enabled=True))
    if vmhwm_absolute_threshold_bytes is not None:
        postchecks.append(
            create_memory_utilization_check(
                vmhwm_threshold=vmhwm_absolute_threshold_bytes
            )
        )
    if snapshot_checks is None:
        snapshot_checks = list(BGP_STANDARD_SNAPSHOT_CHECKS)

    return Playbook(
        name="bgp_ug_cpu_quantification",
        stages=stages,
        prechecks=prechecks,
        postchecks=postchecks,
        snapshot_checks=snapshot_checks,
    )


# =============================================================================
# 2.9.3 NOTIFICATION Sent to One Peer -> Group Isolation
# =============================================================================
#
# StopKeepAlive on ONE eBGP session per AFI silences that neighbor while its
# session stays materialized, so the DUT hits hold-timer expiry on it and
# originates a Hold-Timer-Expired NOTIFICATION -- tearing down JUST that one
# session. The spec's isolation claim is that this must NOT disturb the rest of
# the group (the other eBGP peers keep their sessions) or the other update
# groups (iBGP stays fully Established), route distribution to everyone else
# keeps working, and on recovery (ResumeKeepAlive) the peer re-syncs cleanly
# into the update group.
#
# Robust-signal design (the targeted session flaps down/up on the hold-timer
# cycle while KeepAlive is suppressed, so its instantaneous state is unreliable):
#   * "a NOTIFICATION happened, isolated to the target" is asserted on the
#     per-peer num_resets DELTA (snapshot before / verify after) + the
#     last_reset_reason string, and by requiring every OTHER eBGP peer in the
#     AFI scope to be undisturbed -- ``verify_bgp_notification_occurred``.
#   * cross-group isolation = iBGP stays fully Established (a session-establish
#     check that ignores the eBGP + BGP-MON parents) + a no-iBGP-flap snapshot
#     check across the whole run.
#   * distribution during isolation = inject 50 genuinely-new eBGP routes/AFI
#     (SHARED across all eBGP peers, so it lands even with the target down) and
#     assert every iBGP peer's PS grew by ~50 (the DUT re-advertised them).
#   * recovery re-sync = ResumeKeepAlive, then assert the target + its mates are
#     back in PeerUpdateState JOINED_RUNNING (the DNE-approved primary re-sync
#     signal), all sessions re-Established, and full UG membership restored. There
#     is NO DUT->eBGP uniform-advertise check: the DUT advertises 0 to eBGP peers
#     in this config (they are route sources) -- see the NOTE in the recovery
#     stage. (HW-validated on bag013.)
# Dual-AFI throughout (v4 AND v6); the v6 distribution/re-sync verifies carry the
# XFAIL escape hatch for the first HW run (like 2.9.1/2.9.6).


def create_bgp_ug_notification_isolation_playbook(
    *,
    device_name: str,
    # Per-AFI eBGP peer-name regexes -- the StopKeepAlive/ResumeKeepAlive trigger
    # targets ONE session index on each.
    ebgp_v4_peer_regex: str,
    ebgp_v6_peer_regex: str,
    # Update-group peer-group names for the UG structure checks.
    ebgp_v4_peer_group: str,
    ebgp_v6_peer_group: str,
    ibgp_v6_peer_group: str,
    # eBGP peer-address parents per AFI: the target/isolation scope (identify the
    # reset peer + assert the rest undisturbed) AND the recovery JOINED_RUNNING
    # re-sync scope (the update-group members that must return to JOINED_RUNNING).
    ebgp_v4_peer_parent_prefixes: t.List[str],
    ebgp_v6_peer_parent_prefixes: t.List[str],
    # iBGP peer-address parents per AFI: the PS-gauge scope for the "50 new eBGP
    # routes reach every iBGP peer" distribution delta.
    ibgp_v4_peer_parent_prefixes: t.List[str],
    ibgp_v6_peer_parent_prefixes: t.List[str],
    # Everything that is NOT iBGP (both eBGP AFIs + BGP-MON): scopes the
    # "iBGP fully Established" cross-group-isolation check + the no-flap snapshot
    # to iBGP, since the targeted eBGP session is intentionally flapping.
    non_ibgp_parent_prefixes: t.List[str],
    # Dedicated genuinely-new inject pools (one per AFI) staged on the eBGP DGs,
    # withdrawn at baseline and advertised whole during the isolation window so
    # each is a measurable +N at the DUT's iBGP egress.
    ebgp_v4_inject_pool_regex: str,
    ebgp_v6_inject_pool_regex: str,
    inject_route_count: int = 50,
    # eBGP UG member baseline PER AFI (140 on the EBB-scale topology): asserted
    # restored after recovery.
    ebgp_members_per_afi: int = 140,
    # The single 1-based session index silenced per AFI.
    target_session_index: int = 1,
    expected_group_count: int = 4,
    # --- Checks ---
    prechecks: t.List[PointInTimeHealthCheck],
    postchecks: t.Optional[t.List[PointInTimeHealthCheck]] = None,
    snapshot_checks: t.Optional[t.List[SnapshotHealthCheck]] = None,
    bgp_mon_ignore_prefixes: t.Optional[t.List[str]] = None,
    # --- Timing / gates ---
    keepalive_settle_s: int = 200,
    inject_settle_s: int = 30,
    recovery_convergence_s: int = 180,
    monitor_interval_s: int = 60,
    monitor_retry_count: int = 3,
    monitor_retry_delay_s: float = 10.0,
    session_retry_count: int = 10,
    session_retry_delay_s: float = 30.0,
    distribution_count_window: int = 10,
    distribution_tolerance: int = 3,
    load_avg_baseline: float = 12.0,
    vmhwm_absolute_threshold_bytes: t.Optional[int] = None,
    # v6 first-HW-run escape hatches (default OFF -> v6 STRICT), like 2.9.1/2.9.6.
    v6_distribution_expected_fail: bool = False,
    v6_distribution_expected_fail_reason: t.Optional[str] = None,
    v6_resync_expected_fail: bool = False,
    v6_resync_expected_fail_reason: t.Optional[str] = None,
    # First-HW-run escape hatch for the notification-occurred verify (both AFIs):
    # the hold-timer ``last_reset_reason`` phrasing is device-specific and
    # unverified on the first run, so allow XFAIL until confirmed. Default OFF
    # (strict). ``notification_reason_substrings`` overrides the default match set
    # once the actual on-device reason string is known (None keeps the default).
    notification_expected_fail: bool = False,
    notification_expected_fail_reason: t.Optional[str] = None,
    notification_reason_substrings: t.Optional[t.List[str]] = None,
) -> Playbook:
    """Build the BGP++ Update Group qualification 2.9.3 playbook (NOTIFICATION
    Sent to One Peer -> Group Isolation).

    Flow (dual-AFI):
      1. Baseline: withdraw the per-AFI eBGP inject pools (so their later
         advertise is a genuine +N), log the targeted eBGP session address per
         AFI, and snapshot the eBGP num_resets baseline per AFI (the notification
         reference).
      2. Trigger + monitor (concurrent): StopKeepAlive on ONE eBGP session per
         AFI, wait ``keepalive_settle_s`` for the DUT hold-timer to expire and
         originate the Hold-Timer-Expired NOTIFICATION, and -- concurrently --
         run the monitor track (no crash + iBGP stays Established + load-avg)
         across the window (no iBGP flap). After the settle, in the same track:
         assert iBGP fully Established (cross-group isolation), the update groups
         are intact/enabled, no crash, and -- per AFI -- exactly the targeted
         peer took a hold-timer NOTIFICATION with every other eBGP peer in the
         group undisturbed (intra-group isolation).
      3. Distribution during isolation: snapshot the iBGP PS (now that the target
         is isolated), advertise the 50 genuinely-new eBGP routes per AFI (SHARED,
         so they land even with the target down) and assert every iBGP peer's PS
         grew by ~``inject_route_count`` (the DUT re-advertised them) --
         distribution to the rest keeps working.
      4. Recovery: ResumeKeepAlive on the same session per AFI, wait
         ``recovery_convergence_s``, then assert all sessions re-Established +
         full UG membership restored + no crash, and -- per AFI -- the target +
         its mates back in PeerUpdateState JOINED_RUNNING (the DNE-approved
         re-sync signal). No DUT->eBGP uniform-advertise check -- the DUT
         advertises 0 to eBGP peers here (see the NOTE in the recovery stage).

    v6 distribution + re-sync verifies carry the XFAIL escape hatch (default off).
    The notification-occurred verify has its own escape hatch
    (``notification_expected_fail``, default off) plus a
    ``notification_reason_substrings`` override for the device-specific hold-timer
    reason string, since the exact phrasing is unverified until the first HW run.
    """
    inject_min_delta = max(1, inject_route_count - distribution_count_window)

    # --- Stage 1: baseline -----------------------------------------------------
    baseline_steps: t.List[Step] = [
        create_advertise_withdraw_prefixes_step(
            device_name=device_name,
            advertise=False,
            prefix_pool_regex=ebgp_v4_inject_pool_regex,
            prefix_start_index=0,
            prefix_end_index=inject_route_count,
            description=(
                "2.9.3 baseline -- withdraw the eBGP v4 inject pool so its later "
                "advertise is a genuinely-new +N at the iBGP egress"
            ),
        ),
        create_advertise_withdraw_prefixes_step(
            device_name=device_name,
            advertise=False,
            prefix_pool_regex=ebgp_v6_inject_pool_regex,
            prefix_start_index=0,
            prefix_end_index=inject_route_count,
            description="2.9.3 baseline -- withdraw the eBGP v6 inject pool",
        ),
        create_longevity_step(
            duration=inject_settle_s,
            description="2.9.3 baseline -- settle after withdrawing inject pools",
        ),
        # Log the targeted session's (peer, DUT) address per AFI (the IXIA method
        # logs it; the return value is unused -- the checks identify the target
        # dynamically via the num_resets delta, robust to build-time IP unknowns).
        create_ixia_api_step(
            api_name="get_bgp_session_addresses",
            args_dict={
                "regex": ebgp_v4_peer_regex,
                "session_idx": target_session_index,
            },
            description=(
                f"2.9.3 baseline -- log the targeted eBGP v4 session "
                f"{target_session_index} address"
            ),
        ),
        create_ixia_api_step(
            api_name="get_bgp_session_addresses",
            args_dict={
                "regex": ebgp_v6_peer_regex,
                "session_idx": target_session_index,
            },
            description=(
                f"2.9.3 baseline -- log the targeted eBGP v6 session "
                f"{target_session_index} address"
            ),
        ),
        create_verify_bgp_notification_occurred_step(
            hostname=device_name,
            snapshot_key="notif_ebgp_v4",
            mode="snapshot",
            peer_parent_prefixes=ebgp_v4_peer_parent_prefixes,
            description=(
                "2.9.3 baseline -- snapshot eBGP v4 num_resets (notification ref)"
            ),
        ),
        create_verify_bgp_notification_occurred_step(
            hostname=device_name,
            snapshot_key="notif_ebgp_v6",
            mode="snapshot",
            peer_parent_prefixes=ebgp_v6_peer_parent_prefixes,
            description=(
                "2.9.3 baseline -- snapshot eBGP v6 num_resets (notification ref)"
            ),
        ),
    ]

    # --- Stage 2: trigger + settle + isolation verify (monitor concurrently) ---
    trigger_isolation_track: t.List[Step] = [
        create_stop_bgp_keepalive_step(
            peer_regex=ebgp_v4_peer_regex,
            session_index=target_session_index,
            description=(
                f"2.9.3 -- StopKeepAlive on ONE eBGP v4 session "
                f"({target_session_index}) -> DUT hold-timer NOTIFICATION"
            ),
        ),
        create_stop_bgp_keepalive_step(
            peer_regex=ebgp_v6_peer_regex,
            session_index=target_session_index,
            description=(
                f"2.9.3 -- StopKeepAlive on ONE eBGP v6 session "
                f"({target_session_index}) -> DUT hold-timer NOTIFICATION"
            ),
        ),
        create_longevity_step(
            duration=keepalive_settle_s,
            description=(
                "2.9.3 -- wait for the DUT hold-timer to expire on the silenced "
                "session and originate the Hold-Timer-Expired NOTIFICATION"
            ),
        ),
        create_validation_step(
            point_in_time_checks=[
                *_no_crash_checks(),
                # Cross-group isolation: iBGP stays fully Established (the eBGP
                # target is intentionally down/flapping, so ignore eBGP + MON).
                create_bgp_session_establish_check(
                    parent_prefixes_to_ignore=non_ibgp_parent_prefixes,
                    retry_count=session_retry_count,
                    retry_delay_seconds=session_retry_delay_s,
                    check_id="notif_ibgp_isolation_established",
                ),
                # Groups intact / still enabled. eBGP member counts are NOT pinned
                # here (the target flaps on the hold-timer cycle so the count
                # oscillates 139<->140); the per-peer isolation is asserted
                # robustly by verify_bgp_notification_occurred below.
                create_bgp_update_group_check(
                    expect_enabled=True,
                    peer_group_substrings=[
                        ebgp_v4_peer_group,
                        ebgp_v6_peer_group,
                        ibgp_v6_peer_group,
                    ],
                    expected_group_count=expected_group_count,
                    check_id="notif_ug_intact",
                ),
            ],
            description=(
                "2.9.3 -- isolation: iBGP fully Established (cross-group), update "
                "groups intact/enabled, no crash"
            ),
        ),
        create_verify_bgp_notification_occurred_step(
            hostname=device_name,
            snapshot_key="notif_ebgp_v4",
            mode="verify",
            peer_parent_prefixes=ebgp_v4_peer_parent_prefixes,
            expected_notified_peers=1,
            reason_substrings=notification_reason_substrings,
            expected_fail=notification_expected_fail,
            expected_fail_reason=notification_expected_fail_reason,
            description=(
                "2.9.3 -- exactly ONE eBGP v4 peer took a hold-timer NOTIFICATION; "
                "every other eBGP v4 peer undisturbed (intra-group isolation)"
            ),
        ),
        create_verify_bgp_notification_occurred_step(
            hostname=device_name,
            snapshot_key="notif_ebgp_v6",
            mode="verify",
            peer_parent_prefixes=ebgp_v6_peer_parent_prefixes,
            expected_notified_peers=1,
            reason_substrings=notification_reason_substrings,
            expected_fail=notification_expected_fail,
            expected_fail_reason=notification_expected_fail_reason,
            description=(
                "2.9.3 -- exactly ONE eBGP v6 peer took a hold-timer NOTIFICATION; "
                "every other eBGP v6 peer undisturbed (intra-group isolation)"
            ),
        ),
    ]
    trigger_isolation_stage = create_steps_stage(
        concurrent=True,
        concurrent_steps=[
            ConcurrentStep(steps=trigger_isolation_track),
            # No-iBGP-flap + no-crash monitor across the whole isolation window.
            ConcurrentStep(
                steps=_monitor_track_steps(
                    non_ibgp_parent_prefixes=non_ibgp_parent_prefixes,
                    load_avg_baseline=load_avg_baseline,
                    interval_s=monitor_interval_s,
                    duration_s=keepalive_settle_s,
                    retry_count=monitor_retry_count,
                    retry_delay_s=monitor_retry_delay_s,
                )
            ),
        ],
        description=(
            "2.9.3 -- trigger the hold-timer NOTIFICATION on one eBGP session/AFI, "
            "settle, and verify isolation while monitoring iBGP stability"
        ),
    )

    # --- Stage 3: distribution during isolation --------------------------------
    # Snapshot the iBGP PS baseline HERE (after the target is isolated, before the
    # inject) so the delta measures ONLY the 50-route inject -- immune to any RIB
    # change from the targeted eBGP peer being down.
    distribution_steps: t.List[Step] = [
        create_snapshot_bgp_sent_route_counts_step(
            hostname=device_name,
            snapshot_key="notif_ibgp_v4",
            peer_parent_prefixes=ibgp_v4_peer_parent_prefixes,
            description=(
                "2.9.3 distribution -- snapshot iBGP v4 PS during isolation "
                "(delta ref for the v4 inject)"
            ),
        ),
        create_snapshot_bgp_sent_route_counts_step(
            hostname=device_name,
            snapshot_key="notif_ibgp_v6",
            peer_parent_prefixes=ibgp_v6_peer_parent_prefixes,
            description=(
                "2.9.3 distribution -- snapshot iBGP v6 PS during isolation "
                "(delta ref for the v6 inject)"
            ),
        ),
        create_advertise_withdraw_prefixes_step(
            device_name=device_name,
            advertise=True,
            prefix_pool_regex=ebgp_v4_inject_pool_regex,
            prefix_start_index=0,
            prefix_end_index=inject_route_count,
            description=(
                f"2.9.3 distribution -- advertise {inject_route_count} genuinely-new "
                f"eBGP v4 routes (SHARED; lands even with the target down)"
            ),
        ),
        create_longevity_step(
            duration=inject_settle_s,
            description="2.9.3 distribution -- settle after the v4 inject",
        ),
        create_verify_bgp_sent_route_count_delta_step(
            hostname=device_name,
            snapshot_key="notif_ibgp_v4",
            peer_parent_prefixes=ibgp_v4_peer_parent_prefixes,
            min_delta=inject_min_delta,
            tolerance=distribution_tolerance,
            description=(
                f"2.9.3 distribution -- every iBGP v4 peer's PS grew by "
                f">= ~{inject_route_count} (the 50 new eBGP routes reached iBGP)"
            ),
        ),
        create_advertise_withdraw_prefixes_step(
            device_name=device_name,
            advertise=True,
            prefix_pool_regex=ebgp_v6_inject_pool_regex,
            prefix_start_index=0,
            prefix_end_index=inject_route_count,
            description=(
                f"2.9.3 distribution -- advertise {inject_route_count} genuinely-new "
                f"eBGP v6 routes (SHARED)"
            ),
        ),
        create_longevity_step(
            duration=inject_settle_s,
            description="2.9.3 distribution -- settle after the v6 inject",
        ),
        create_verify_bgp_sent_route_count_delta_step(
            hostname=device_name,
            snapshot_key="notif_ibgp_v6",
            peer_parent_prefixes=ibgp_v6_peer_parent_prefixes,
            min_delta=inject_min_delta,
            # No max: the DUT may re-advertise the v6 EB-PRIVATE range with
            # expansion (HW-observed on bag013; see 2.9.6 criterion 3).
            tolerance=distribution_tolerance,
            expected_fail=v6_distribution_expected_fail,
            expected_fail_reason=v6_distribution_expected_fail_reason,
            description=(
                f"2.9.3 distribution (v6) -- every iBGP v6 peer's PS grew by "
                f">= ~{inject_route_count}"
            ),
        ),
        create_validation_step(
            point_in_time_checks=list(_no_crash_checks()),
            description="2.9.3 distribution -- no crash after the injects",
        ),
    ]

    # --- Stage 4: recovery + re-sync -------------------------------------------
    recovery_steps: t.List[Step] = [
        create_resume_bgp_keepalive_step(
            peer_regex=ebgp_v4_peer_regex,
            session_index=target_session_index,
            description=(
                f"2.9.3 recovery -- ResumeKeepAlive on the eBGP v4 session "
                f"({target_session_index})"
            ),
        ),
        create_resume_bgp_keepalive_step(
            peer_regex=ebgp_v6_peer_regex,
            session_index=target_session_index,
            description=(
                f"2.9.3 recovery -- ResumeKeepAlive on the eBGP v6 session "
                f"({target_session_index})"
            ),
        ),
        create_longevity_step(
            duration=recovery_convergence_s,
            description=(
                "2.9.3 recovery -- allow the recovered session to re-establish and "
                "the update group to re-sync"
            ),
        ),
        create_validation_step(
            point_in_time_checks=[
                *_no_crash_checks(),
                # All sessions back (incl the recovered target), excl BGP-MON.
                create_bgp_session_establish_check(
                    parent_prefixes_to_ignore=bgp_mon_ignore_prefixes,
                    retry_count=session_retry_count,
                    retry_delay_seconds=session_retry_delay_s,
                    check_id="notif_recovery_sessions",
                ),
                # Full UG membership restored (the target rejoined) -- safe to pin
                # now that KeepAlive is resumed and the session is stable.
                create_bgp_update_group_check(
                    expect_enabled=True,
                    peer_group_substrings=[
                        ebgp_v4_peer_group,
                        ebgp_v6_peer_group,
                        ibgp_v6_peer_group,
                    ],
                    expected_member_counts={
                        ebgp_v4_peer_group: ebgp_members_per_afi,
                        ebgp_v6_peer_group: ebgp_members_per_afi,
                    },
                    expected_group_count=expected_group_count,
                    check_id="notif_recovery_ug_membership",
                ),
            ],
            description=(
                "2.9.3 recovery -- all sessions re-Established; full UG membership "
                "restored; no crash"
            ),
        ),
        create_verify_bgp_peers_joined_running_step(
            hostname=device_name,
            peer_parent_prefixes=ebgp_v4_peer_parent_prefixes,
            description=(
                "2.9.3 re-sync -- every eBGP v4 peer (incl the recovered target) is "
                "back in PeerUpdateState JOINED_RUNNING"
            ),
        ),
        create_verify_bgp_peers_joined_running_step(
            hostname=device_name,
            peer_parent_prefixes=ebgp_v6_peer_parent_prefixes,
            expected_fail=v6_resync_expected_fail,
            expected_fail_reason=v6_resync_expected_fail_reason,
            description=(
                "2.9.3 re-sync (v6) -- every eBGP v6 peer is back in "
                "PeerUpdateState JOINED_RUNNING"
            ),
        ),
        # NOTE (HW-observed on bag013, 2026-07-26): the DUT advertises 0 prefixes
        # to the eBGP peers in this config -- min=max=0 uniformly across all 140,
        # with every session Established and JOINED_RUNNING. The eBGP peers are
        # route SOURCES here (they inject -> DUT -> iBGP, which the distribution
        # stage verifies), so there is no iBGP-sourced table for the DUT to
        # re-advertise back to them (unlike 2.9.6, which injects iBGP DC routes and
        # therefore does see ~45k of DUT->eBGP egress). A DUT->eBGP "non-zero
        # advertised count" is thus not a meaningful re-sync signal for 2.9.3.
        # Per DNE, JOINED_RUNNING is the primary re-sync proof -- covered above by
        # verify_bgp_peers_joined_running (recovered target + all mates) plus the
        # all-Established + full-UG-membership validation checks. A DUT->eBGP
        # received-count re-sync assertion would require injecting iBGP/DC routes
        # the way 2.9.6 does; deferred, as DNE deemed JOINED_RUNNING sufficient.
    ]

    stages = [
        create_steps_stage(
            steps=baseline_steps,
            description=(
                "2.9.3 baseline -- withdraw inject pools; snapshot eBGP reset "
                "baselines; log the targeted sessions"
            ),
        ),
        trigger_isolation_stage,
        create_steps_stage(
            steps=distribution_steps,
            description=(
                "2.9.3 distribution -- inject 50 new eBGP routes/AFI and verify "
                "every iBGP peer received them"
            ),
        ),
        create_steps_stage(
            steps=recovery_steps,
            description=(
                "2.9.3 recovery -- resume KeepAlive and verify the peer + its "
                "mates re-sync into the update group"
            ),
        ),
    ]

    # Always-appended bounds (whether the caller takes the default
    # BGP_STANDARD_POSTCHECKS bundle or supplies its own). BGP_STANDARD_POSTCHECKS
    # covers no-stale-routes / unclean-exit; _no_crash_checks adds the
    # service-restart + core-dump gate; plus the UG-specific bounds the spec calls
    # out (log-parsing, load-avg, UG enabled).
    base_postchecks = (
        list(postchecks) if postchecks is not None else list(BGP_STANDARD_POSTCHECKS)
    )
    postchecks = base_postchecks + [
        *_no_crash_checks(),
        create_system_cpu_load_average_check(baseline=load_avg_baseline),
        create_log_parsing_check(start_time_jq_var="test_case_start_time"),
        create_bgp_update_group_check(expect_enabled=True),
    ]
    if vmhwm_absolute_threshold_bytes is not None:
        postchecks.append(
            create_memory_utilization_check(
                vmhwm_threshold=vmhwm_absolute_threshold_bytes
            )
        )
    # BGP_STANDARD_SNAPSHOT_CHECKS does NOT include the session/flap check, so add
    # it explicitly: no iBGP peer may flap across the whole run (the targeted eBGP
    # session legitimately does, so ignore the eBGP + BGP-MON parents). Append it
    # UNCONDITIONALLY -- even when a caller supplies custom snapshot_checks -- so
    # criterion 2 (no iBGP flap) can never be silently dropped by an override.
    snapshot_checks = (
        list(snapshot_checks)
        if snapshot_checks is not None
        else list(BGP_STANDARD_SNAPSHOT_CHECKS)
    ) + [
        create_bgp_session_snapshot_check(
            parent_prefixes_to_ignore=non_ibgp_parent_prefixes,
        )
    ]

    return Playbook(
        name="bgp_ug_notification_isolation",
        stages=stages,
        prechecks=prechecks,
        postchecks=postchecks,
        snapshot_checks=snapshot_checks,
    )
