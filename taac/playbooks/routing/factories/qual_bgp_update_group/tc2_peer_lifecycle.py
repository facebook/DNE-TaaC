# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""Spec 2.2 — Peer Lifecycle Within Update Groups. UG qualification playbook factories.

Implemented:
- 2.2.1 Peer Down: Remaining Group Members Unaffected
- 2.2.2 Peer Reconnect: Re-Sync from Shadow RIB
- 2.2.3 Sustained Group Membership Churn: No Memory Leak
"""

import typing as t

from taac.health_checks.healthcheck_definitions import (
    create_bgp_peer_route_set_equality_check,
    create_bgp_session_establish_check,
    create_bgp_session_snapshot_check,
    create_bgp_update_group_check,
    create_cpu_percentile_observe_check,
    create_device_core_dumps_check,
    create_log_parsing_check,
    create_memory_utilization_check,
    create_service_restart_check,
    create_system_cpu_load_average_check,
)
from taac.stages.stage_definitions import create_steps_stage
from taac.steps.step_definitions import (
    create_advertise_withdraw_prefixes_step,
    create_cpu_percentile_start_step,
    create_cpu_percentile_stop_step,
    create_longevity_step,
    create_start_stop_bgp_peers_step,
    create_validation_step,
)
from taac.testconfigs.routing.util.bgp_ebb_health_checks import (
    BGP_STANDARD_POSTCHECKS,
    BGP_STANDARD_SNAPSHOT_CHECKS,
)
from taac.utils.characterization import CPU_SUMMARY_JQ_VAR
from taac.health_check.health_check import types as hc_types
from taac.test_as_a_config.types import (
    Playbook,
    PointInTimeHealthCheck,
    SnapshotHealthCheck,
    Step,
)


_CRASH_GATE_SERVICES: t.List[str] = ["Bgp", "FibAgent", "FibAgentBgp"]
_CRASH_GATE_DAEMONS: t.List[str] = ["FibBgpGrpc"]

# Spec 2.2.3 leak gate: max allowed memory growth over the churn run (200 MB).
_MEMORY_GROWTH_THRESHOLD_BYTES: int = 200 * (1024**2)


# jq var the CPU percentile STOP step stashes its summary into, read back by
# the CPU_PERCENTILE_CHECK postcheck. jq-safe: no dots or colons.
_CPU_PERCENTILE_SUMMARY_JQ_VAR = CPU_SUMMARY_JQ_VAR


# Standard checks that cannot reach a verdict on this EOS DUT, so they only ever
# report SKIP here. None of them is a QUAL-UG-03/04/05 blocking signal:
#   UNCLEAN_EXIT_CHECK, DRAIN_STATE_CHECK -- OPERATING_SYSTEMS = ["FBOSS"], and
#     the "no crash" signal is carried by _no_crash_checks() (service restart +
#     core dumps), which do run on EOS.
#   CPU_UTILIZATION_CHECK -- runs on Arista but its sampling path needs a
#     'delta' the standard factory cannot supply, so it self-skips. The "no CPU
#     breach" signal is carried by CPU_PERCENTILE_CHECK instead.
# Dropped from this suite only: the shared BGP_STANDARD_* lists stay intact for
# the FBOSS devices where these do produce a verdict.
_SKIP_ONLY_ON_EOS: t.FrozenSet[hc_types.CheckName] = frozenset(
    {
        hc_types.CheckName.UNCLEAN_EXIT_CHECK,
        hc_types.CheckName.DRAIN_STATE_CHECK,
        hc_types.CheckName.CPU_UTILIZATION_CHECK,
    }
)


def _drop_skip_only_checks(
    checks: t.Sequence[PointInTimeHealthCheck],
) -> t.List[PointInTimeHealthCheck]:
    """Strip postchecks that can only ever SKIP on this EOS DUT.

    Only the postchecks need this: create_standard_prechecks does not include
    any of the three.
    """
    return [check for check in checks if check.name not in _SKIP_ONLY_ON_EOS]


def _no_crash_checks() -> t.List[PointInTimeHealthCheck]:
    """No-crash gate: BGP/FIB daemons did not restart and no new core dumps."""
    return [
        create_service_restart_check(
            services=_CRASH_GATE_SERVICES,
            daemons=_CRASH_GATE_DAEMONS,
        ),
        create_device_core_dumps_check(),
    ]


def create_bgp_ug_peer_down_remaining_unaffected_playbook(
    *,
    device_name: str,
    ebgp_peer_regex: str,
    ebgp_peer_group_substrings: t.List[str],
    ibgp_peer_group_substrings: t.List[str],
    non_ibgp_parent_prefixes: t.List[str],
    ebgp_inject_pool_regex: str,
    inject_route_count: int = 50,
    survivor_baseline_peer_addr: t.Optional[str] = None,
    survivor_tested_peer_addrs: t.Optional[t.List[str]] = None,
    sessions_to_drop_start_idx: int = 1,
    sessions_to_drop_end_idx: int = 64,
    isolation_expected_member_counts: t.Optional[t.Dict[str, int]] = None,
    enable_cpu_percentile: bool = True,
    cpu_percentile_interval_s: float = 2.0,
    cpu_gate_percentile: float = 95.0,
    cpu_gate_threshold_pct: t.Optional[float] = None,
    prechecks: t.List[PointInTimeHealthCheck],
    postchecks: t.Optional[t.List[PointInTimeHealthCheck]] = None,
    snapshot_checks: t.Optional[t.List[SnapshotHealthCheck]] = None,
    vmhwm_threshold_bytes: t.Optional[int] = None,
    settle_after_drop_s: int = 300,
    isolation_soak_s: int = 300,
    session_retry_count: int = 4,
    session_retry_delay_seconds: float = 30.0,
) -> Playbook:
    """Build the BGP++ Update Group qualification 2.2.1 playbook
    (Peer Down: Remaining Group Members Unaffected).

    Intent (spec 2.2.1): stopping a SUBSET of eBGP peers in an update group must
    not disrupt the remaining eBGP peers, the iBGP update groups, or route
    distribution through survivors.

    Flow:

      1. Baseline: withdraw the eBGP inject pool so a later advertise is a
         genuine +N.
      2. Trigger+isolation: stop a SUBSET of eBGP sessions
         (``sessions_to_drop_start_idx`` to ``sessions_to_drop_end_idx``,
         1-based inclusive, default 1-64 = 64 sessions per QUAL-UG-03),
         settle (~5 min soak), then assert:
         - iBGP sessions still Established (scoped via
           ``non_ibgp_parent_prefixes`` to ignore eBGP + BGP-MON parents).
         - Update groups intact (eBGP + iBGP peer groups still formed).
         - No crash (BGP/FIB daemons did not restart, no new core dumps).
      3. Distribution workload: inject ``inject_route_count`` (50) routes
         through survivors via the eBGP inject pool and hold, then assert that
         every surviving eBGP peer's post-policy advertised route SET is equal
         (``create_bgp_peer_route_set_equality_check`` over
         ``survivor_baseline_peer_addr`` + ``survivor_tested_peer_addrs``, backed
         by the DUT thrift ``getPostfilterAdvertisedNetworks``). This is the
         genuine positive-distribution gate: if a survivor's advertised set
         diverges (or is empty while the baseline has routes) the check fails.
         Skipped only when no survivor peer addresses are supplied.
      4. Cleanup: restore the dropped eBGP sessions as ``cleanup_steps``.

    Postchecks: BGP_STANDARD_POSTCHECKS + no-crash + CPU load-average < 12 +
    UG still enabled + log parsing + memory VmHWM if supplied.

    Snapshot checks: BGP_STANDARD_SNAPSHOT_CHECKS + no-iBGP-flap gate (scoped
    via ``non_ibgp_parent_prefixes``).

    Args:
        device_name: DUT hostname
        ebgp_peer_regex: Regex matching eBGP peer names to drop
        ebgp_peer_group_substrings: eBGP peer-group names for UG structure
            checks
        ibgp_peer_group_substrings: iBGP peer-group names for UG structure
            checks
        non_ibgp_parent_prefixes: Parent prefixes of all non-eBGP peers (iBGP +
            BGP-MON) to scope the "iBGP still Established" assertion to iBGP
            only
        ebgp_inject_pool_regex: eBGP prefix pool regex for the distribution
            workload inject
        inject_route_count: Number of routes to inject through survivors
            (default 50)
        survivor_baseline_peer_addr: A surviving (never-dropped) eBGP peer IP
            used as the ground-truth advertised-route set. When supplied with
            ``survivor_tested_peer_addrs``, the post-inject stage asserts every
            tested survivor's advertised set equals this baseline's.
        survivor_tested_peer_addrs: Other surviving eBGP peer IPs whose
            post-policy advertised set must equal the baseline's. Omit both to
            skip the positive-distribution assertion.
        sessions_to_drop_start_idx: Start index of sessions to drop (1-based,
            inclusive, default 1). IXIA session indices start at 1; a 0 here
            wedges the IxNetwork session (504 on operations/select).
        sessions_to_drop_end_idx: End index of sessions to drop (1-based,
            inclusive, default 64, giving the 64 sessions QUAL-UG-03 specifies)
        isolation_expected_member_counts: Optional peer-group substring ->
            expected Established member count, asserted by the isolation
            update-group check. Supplying it turns "the departed peers were
            removed" from an observation into an assertion; omitting it leaves
            the check verifying only that the groups are still formed.
        enable_cpu_percentile: Bracket the isolation window with a bgpcpp CPU
            percentile START/STOP pair and report the summary as a postcheck
            (default True).
        cpu_percentile_interval_s: Sampling interval for that bracket
            (default 2.0s).
        cpu_gate_percentile: Percentile the gate reads when a threshold is set
            (default p95).
        cpu_gate_threshold_pct: CPU%% ceiling for that percentile. None (the
            default) is observe-only: the value is reported and always passes.
        prechecks: Precheck health checks
        postchecks: Postcheck health checks (default BGP_STANDARD_POSTCHECKS)
        snapshot_checks: Snapshot health checks (default
            BGP_STANDARD_SNAPSHOT_CHECKS)
        vmhwm_threshold_bytes: Optional VmHWM ceiling (bytes) for the memory
            postcheck
        settle_after_drop_s: Settle duration after dropping sessions (default
            300s)
        isolation_soak_s: Soak duration with sessions down (default 300s)
        session_retry_count: Retry count for session-establish checks (default
            4). Retries absorb a transient CLI-empty race under heavy load;
            they cannot wait out a deterministic failure. The framework
            back-off is exponential (delay = retry_delay_seconds * 1.5**n), so
            the count is kept low: 4 retries cap the wait at ~4 min, while 10
            would reach ~57 min with the last four attempts alone accounting
            for ~46 of them.
        session_retry_delay_seconds: Retry delay for session-establish checks
            (default 30.0s), grown by the framework's 1.5x exponential
            multiplier on each retry.

    Returns:
        Playbook for spec 2.2.1
    """
    # The later advertise has to be a genuine +N, so the pool is withdrawn
    # first: re-advertising already-active routes would be a no-op.
    baseline_stage = create_steps_stage(
        steps=[
            create_advertise_withdraw_prefixes_step(
                device_name=device_name,
                advertise=False,
                prefix_pool_regex=ebgp_inject_pool_regex,
                prefix_start_index=0,
                prefix_end_index=inject_route_count,
                description=(
                    f"2.2.1 baseline — withdraw {inject_route_count} eBGP routes "
                    f"so the later advertise is a genuine +N"
                ),
            ),
        ],
    )

    # Only a SUBSET of the eBGP sessions is stopped: the case asserts the
    # remaining members are unaffected, so the rest have to stay up.
    trigger_isolation_checks: t.List[PointInTimeHealthCheck] = [
        *_no_crash_checks(),
        # iBGP must stay Established while eBGP is partially down (core 2.2.1
        # isolation claim). Scoped to iBGP by ignoring eBGP + BGP-MON parents.
        # Retries absorb transient CLI-empty races under heavy load.
        create_bgp_session_establish_check(
            parent_prefixes_to_ignore=non_ibgp_parent_prefixes,
            retry_count=session_retry_count,
            retry_delay_seconds=session_retry_delay_seconds,
            check_id="peer_down_ibgp_established",
        ),
        # Update groups must remain intact (eBGP + iBGP peer groups still
        # formed). When the caller supplies expected member counts, the
        # departed peers being *removed* is asserted rather than merely
        # observed: "groups still exist" would also hold if the stopped peers
        # were still counted as members.
        create_bgp_update_group_check(
            expect_enabled=True,
            peer_group_substrings=ebgp_peer_group_substrings
            + ibgp_peer_group_substrings,
            expected_member_counts=isolation_expected_member_counts,
            check_id="peer_down_ug_intact",
        ),
    ]

    # Embeddable bgpcpp CPU percentile bracket. START before the trigger and
    # STOP after the soak, so the window is exactly the disruption: the peer
    # -down event plus the whole period the subset is down. A percentile over
    # that window is the "what does partial peer loss cost in CPU" number.
    # Sequential, so no ConcurrentStep is needed; the sampler runs in the
    # background across the steps in between.
    cpu_session_key = f"peer_down_isolation:{device_name}"
    cpu_bracket_start = (
        [
            create_cpu_percentile_start_step(
                device_name=device_name,
                session_key=cpu_session_key,
                interval_seconds=cpu_percentile_interval_s,
            )
        ]
        if enable_cpu_percentile
        else []
    )
    cpu_bracket_stop = (
        [
            create_cpu_percentile_stop_step(
                session_key=cpu_session_key,
                summary_jq_var=_CPU_PERCENTILE_SUMMARY_JQ_VAR,
            )
        ]
        if enable_cpu_percentile
        else []
    )

    trigger_isolation_stage = create_steps_stage(
        steps=[
            *cpu_bracket_start,
            # Stop the subset (spec 2.2.1 is a peer-down trigger, so the peers
            # stay in the emulation and go Idle/Down). Indices are 1-based:
            # index 0 is not a valid IXIA session and leaves an IxNetwork lock
            # unreleased, wedging the next operations/select into a 504. The
            # cleanup step below restarts the same subset.
            create_start_stop_bgp_peers_step(
                start=False,
                peer_regex=ebgp_peer_regex,
                start_idx=sessions_to_drop_start_idx,
                end_idx=sessions_to_drop_end_idx,
                description=(
                    f"2.2.1 trigger — stop eBGP sessions "
                    f"[{sessions_to_drop_start_idx}:{sessions_to_drop_end_idx}] "
                    f"(subset of eBGP group)"
                ),
            ),
            create_longevity_step(
                duration=settle_after_drop_s,
                description=(
                    f"2.2.1 — settle {settle_after_drop_s}s after stopping eBGP subset"
                ),
            ),
            create_validation_step(
                point_in_time_checks=trigger_isolation_checks,
                description=(
                    "2.2.1 isolation — iBGP Established; eBGP + iBGP update "
                    "groups intact; no crash"
                ),
            ),
            create_longevity_step(
                duration=isolation_soak_s,
                description=(
                    f"2.2.1 — soak {isolation_soak_s}s with eBGP subset down "
                    f"(remaining groups active)"
                ),
            ),
            *cpu_bracket_stop,
        ],
    )

    # Positive distribution: every surviving eBGP peer's post-policy advertised
    # set has to be equal, read from the DUT via
    # getPostfilterAdvertisedNetworks.
    distribution_workload_checks: t.List[PointInTimeHealthCheck] = [
        *_no_crash_checks(),
        create_bgp_session_establish_check(
            parent_prefixes_to_ignore=non_ibgp_parent_prefixes,
            retry_count=session_retry_count,
            retry_delay_seconds=session_retry_delay_seconds,
            check_id="peer_down_distribution_ibgp_established",
        ),
        create_bgp_update_group_check(
            expect_enabled=True,
            peer_group_substrings=ebgp_peer_group_substrings
            + ibgp_peer_group_substrings,
            check_id="peer_down_distribution_ug_intact",
        ),
    ]
    # Positive-distribution gate: survivors must all carry the same advertised
    # set. Non-vacuous by construction -- if the injected routes did not
    # propagate (or advertised-post-policy is empty under UG) the sets diverge
    # from the baseline and the check fails. Skipped only if no survivor
    # addresses are supplied.
    if survivor_baseline_peer_addr and survivor_tested_peer_addrs:
        distribution_workload_checks.append(
            create_bgp_peer_route_set_equality_check(
                baseline_peer_addr=survivor_baseline_peer_addr,
                tested_peer_addrs=survivor_tested_peer_addrs,
                check_id="peer_down_distribution_survivor_route_set_equal",
            )
        )

    distribution_workload_stage = create_steps_stage(
        steps=[
            create_advertise_withdraw_prefixes_step(
                device_name=device_name,
                advertise=True,
                prefix_pool_regex=ebgp_inject_pool_regex,
                prefix_start_index=0,
                prefix_end_index=inject_route_count,
                description=(
                    f"2.2.1 distribution workload — inject {inject_route_count} "
                    f"eBGP routes through survivors"
                ),
            ),
            create_validation_step(
                point_in_time_checks=distribution_workload_checks,
                description=(
                    "2.2.1 post-inject — iBGP Established; update groups intact; "
                    "no crash; survivor advertised route sets equal"
                ),
            ),
        ],
    )

    # Lives on the Playbook rather than a Stage so the dropped sessions are
    # restored regardless of stage outcome.
    cleanup_steps: t.List[Step] = [
        create_start_stop_bgp_peers_step(
            start=True,
            peer_regex=ebgp_peer_regex,
            start_idx=sessions_to_drop_start_idx,
            end_idx=sessions_to_drop_end_idx,
            description=(
                f"2.2.1 cleanup — restart eBGP sessions "
                f"[{sessions_to_drop_start_idx}:{sessions_to_drop_end_idx}]"
            ),
        ),
    ]

    stages = [
        baseline_stage,
        trigger_isolation_stage,
        distribution_workload_stage,
    ]

    # Always-appended bounds (spec pass-criteria): load-average < 12, UG still
    # enabled, log parsing, no crash. Memory VmHWM check if supplied.
    base_postchecks = _drop_skip_only_checks(
        postchecks if postchecks is not None else BGP_STANDARD_POSTCHECKS
    )
    postchecks = base_postchecks + [
        *_no_crash_checks(),
        create_system_cpu_load_average_check(baseline=12.0),
        create_bgp_update_group_check(expect_enabled=True),
        create_log_parsing_check(start_time_jq_var="test_case_start_time"),
    ]
    if vmhwm_threshold_bytes is not None:
        postchecks.append(
            create_memory_utilization_check(vmhwm_threshold=vmhwm_threshold_bytes)
        )
    # Reports the bgpcpp CPU percentiles measured over the isolation window into
    # the results table. Observe-only while cpu_gate_threshold_pct is None: the
    # standard CPU_UTILIZATION_CHECK skips on Arista without a 'delta' and has
    # no meaningful default, so there is no calibrated ceiling to gate on yet.
    # Set cpu_gate_threshold_pct once runs have established one.
    if enable_cpu_percentile:
        postchecks.append(
            create_cpu_percentile_observe_check(
                summary_jq_var=_CPU_PERCENTILE_SUMMARY_JQ_VAR,
                gate_percentile=cpu_gate_percentile,
                gate_threshold_pct=cpu_gate_threshold_pct,
            )
        )

    # Snapshot checks: BGP_STANDARD_SNAPSHOT_CHECKS + no-iBGP-flap gate (scoped
    # to iBGP by ignoring eBGP + BGP-MON parents).
    # Build a new list rather than appending to the caller's: mutating a
    # caller-supplied list would accumulate duplicate snapshot checks if the
    # same list were passed to more than one factory. Mirrors the postchecks
    # path, which already copies via list(postchecks).
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
        name="bgp_ug_peer_down_remaining_unaffected",
        stages=stages,
        prechecks=prechecks,
        postchecks=postchecks,
        snapshot_checks=snapshot_checks,
        # Restore the dropped eBGP sessions regardless of stage outcome.
        cleanup_steps=cleanup_steps,
    )


def create_bgp_ug_peer_reconnect_shadow_rib_playbook(
    *,
    device_name: str,
    ebgp_peer_regex: str,
    ebgp_peer_group_substrings: t.List[str],
    ibgp_peer_group_substrings: t.List[str],
    non_ibgp_parent_prefixes: t.List[str],
    ebgp_inject_pool_regex: str,
    inject_route_count: int = 100,
    reconnect_baseline_peer_addr: t.Optional[str] = None,
    reconnect_tested_peer_addrs: t.Optional[t.List[str]] = None,
    sessions_to_reconnect_start_idx: int = 1,
    sessions_to_reconnect_end_idx: int = 32,
    reconnect_expected_member_counts: t.Optional[t.Dict[str, int]] = None,
    prechecks: t.List[PointInTimeHealthCheck],
    postchecks: t.Optional[t.List[PointInTimeHealthCheck]] = None,
    snapshot_checks: t.Optional[t.List[SnapshotHealthCheck]] = None,
    bgp_mon_ignore_prefixes: t.Optional[t.List[str]] = None,
    vmhwm_threshold_bytes: t.Optional[int] = None,
    settle_after_drop_s: int = 120,
    downtime_inject_soak_s: int = 120,
    resync_soak_s: int = 300,
    session_retry_count: int = 4,
    session_retry_delay_seconds: float = 30.0,
) -> Playbook:
    """Build the BGP++ Update Group qualification 2.2.2 playbook
    (Peer Reconnect: Re-Sync from Shadow RIB).

    Intent (spec 2.2.2): a subset of eBGP peers goes down, routes are added while
    they are down, and when they reconnect they must re-sync the complete current
    route set from the shadow RIB and rejoin their original update group.

    Flow:

      1. Baseline: withdraw the eBGP inject pool so the later downtime advertise
         is a genuine +N.
      2. Trigger: stop a SUBSET of eBGP sessions
         (``sessions_to_reconnect_start_idx``..``sessions_to_reconnect_end_idx``,
         spec default 0-32 = 32 peers) and settle.
      3. Downtime inject: advertise ``inject_route_count`` (100) routes through
         the survivors while the subset is down, then soak.
      4. Reconnect + resync: restart the dropped eBGP sessions, soak
         ``resync_soak_s`` for shadow-RIB resync, then assert:
         - ALL eBGP + iBGP sessions Established again (reconnected peers rejoined,
           scoped only to ignore BGP-MON).
         - Update groups intact (reconnected peers back in their groups).
         - No crash.
         - RESYNC CORRECTNESS: each reconnected peer's post-policy advertised
           route SET equals a continuously-connected (never-dropped) baseline
           peer's (``create_bgp_peer_route_set_equality_check`` over
           ``reconnect_baseline_peer_addr`` + ``reconnect_tested_peer_addrs``,
           backed by DUT thrift ``getPostfilterAdvertisedNetworks``). This is the
           spec's "route counts match continuously connected peers" gate --
           non-vacuous because the baseline never went down, so a reconnected
           peer that fails to resync (empty/partial) diverges and FAILS. Skipped
           only when no reconnect peer addresses are supplied.
      5. Cleanup: ensure the subset is restored.

    Args mirror ``create_bgp_ug_peer_down_remaining_unaffected_playbook`` with a
    reconnect-oriented naming; see that factory for the shared parameters.
    ``reconnect_baseline_peer_addr`` MUST be a never-dropped survivor.

    ``reconnect_expected_member_counts`` is the one parameter that does NOT
    mirror 2.2.1's: there the counts are the survivors (full minus the dropped
    subset) asserted while the peers are down, whereas here they are the FULL
    per-group membership, asserted after the resync soak because every stopped
    peer must have rejoined by then.
    """
    # The downtime advertise has to be a genuine +N, so the pool is withdrawn
    # first.
    baseline_stage = create_steps_stage(
        steps=[
            create_advertise_withdraw_prefixes_step(
                device_name=device_name,
                advertise=False,
                prefix_pool_regex=ebgp_inject_pool_regex,
                prefix_start_index=0,
                prefix_end_index=inject_route_count,
                description=(
                    f"2.2.2 baseline — withdraw {inject_route_count} eBGP routes "
                    f"so the downtime advertise is a genuine +N"
                ),
            ),
        ],
    )

    trigger_stage = create_steps_stage(
        steps=[
            create_start_stop_bgp_peers_step(
                start=False,
                peer_regex=ebgp_peer_regex,
                start_idx=sessions_to_reconnect_start_idx,
                end_idx=sessions_to_reconnect_end_idx,
                description=(
                    f"2.2.2 trigger — stop eBGP sessions "
                    f"[{sessions_to_reconnect_start_idx}:"
                    f"{sessions_to_reconnect_end_idx}] (reconnect subset)"
                ),
            ),
            create_longevity_step(
                duration=settle_after_drop_s,
                description=(
                    f"2.2.2 — settle {settle_after_drop_s}s after stopping the "
                    f"reconnect subset"
                ),
            ),
        ],
    )

    # These routes arrive while the subset is down, so they are the shadow-RIB
    # content the reconnect has to resync.
    downtime_inject_stage = create_steps_stage(
        steps=[
            create_advertise_withdraw_prefixes_step(
                device_name=device_name,
                advertise=True,
                prefix_pool_regex=ebgp_inject_pool_regex,
                prefix_start_index=0,
                prefix_end_index=inject_route_count,
                description=(
                    f"2.2.2 downtime inject — add {inject_route_count} routes "
                    f"through survivors while the subset is down (shadow-RIB "
                    f"source for the reconnect resync)"
                ),
            ),
            create_longevity_step(
                duration=downtime_inject_soak_s,
                description=(
                    f"2.2.2 — soak {downtime_inject_soak_s}s with routes added "
                    f"and the subset still down"
                ),
            ),
        ],
    )

    # The reconnected peers have to re-establish and rejoin their update
    # groups, with advertised sets matching a never-dropped baseline peer.
    reconnect_checks: t.List[PointInTimeHealthCheck] = [
        *_no_crash_checks(),
        # ALL peers (eBGP reconnected + iBGP) must be Established again. Scoped
        # only to ignore BGP-MON (topology omits it). Retries absorb the
        # resync/re-establish window.
        create_bgp_session_establish_check(
            parent_prefixes_to_ignore=bgp_mon_ignore_prefixes or [],
            retry_count=session_retry_count,
            retry_delay_seconds=session_retry_delay_seconds,
            check_id="peer_reconnect_all_established",
        ),
        # Reconnected peers must rejoin their original update groups.
        # When the caller supplies expected member counts, "the reconnected
        # peers rejoined their group" is asserted rather than inferred. This
        # runs after the resync soak, so every peer the trigger stopped must be
        # back: "the groups still exist" would also hold if the subset never
        # rejoined.
        create_bgp_update_group_check(
            expect_enabled=True,
            peer_group_substrings=ebgp_peer_group_substrings
            + ibgp_peer_group_substrings,
            expected_member_counts=reconnect_expected_member_counts,
            check_id="peer_reconnect_ug_intact",
        ),
    ]
    # Resync correctness gate (spec 2.2.2 core): each reconnected peer's
    # post-policy advertised route SET must equal a never-dropped baseline
    # survivor's. Non-vacuous -- a reconnected peer that failed to re-sync from
    # the shadow RIB (empty/partial) diverges from the baseline and FAILS.
    if reconnect_baseline_peer_addr and reconnect_tested_peer_addrs:
        reconnect_checks.append(
            create_bgp_peer_route_set_equality_check(
                baseline_peer_addr=reconnect_baseline_peer_addr,
                tested_peer_addrs=reconnect_tested_peer_addrs,
                check_id="peer_reconnect_resync_route_set_equal",
            )
        )

    reconnect_stage = create_steps_stage(
        steps=[
            create_start_stop_bgp_peers_step(
                start=True,
                peer_regex=ebgp_peer_regex,
                start_idx=sessions_to_reconnect_start_idx,
                end_idx=sessions_to_reconnect_end_idx,
                description=(
                    f"2.2.2 reconnect — restart eBGP sessions "
                    f"[{sessions_to_reconnect_start_idx}:"
                    f"{sessions_to_reconnect_end_idx}]"
                ),
            ),
            create_longevity_step(
                duration=resync_soak_s,
                description=(
                    f"2.2.2 — soak {resync_soak_s}s for shadow-RIB resync after "
                    f"reconnect"
                ),
            ),
            create_validation_step(
                point_in_time_checks=reconnect_checks,
                description=(
                    "2.2.2 resync — all eBGP + iBGP Established; update groups "
                    "intact; no crash; reconnected peers' advertised route sets "
                    "match a never-dropped baseline"
                ),
            ),
        ],
    )

    stages = [
        baseline_stage,
        trigger_stage,
        downtime_inject_stage,
        reconnect_stage,
    ]

    # Cleanup: ensure the subset is restored regardless of stage outcome.
    cleanup_steps: t.List[Step] = [
        create_start_stop_bgp_peers_step(
            start=True,
            peer_regex=ebgp_peer_regex,
            start_idx=sessions_to_reconnect_start_idx,
            end_idx=sessions_to_reconnect_end_idx,
            description=(
                f"2.2.2 cleanup — restore eBGP sessions "
                f"[{sessions_to_reconnect_start_idx}:"
                f"{sessions_to_reconnect_end_idx}]"
            ),
        ),
    ]

    base_postchecks = _drop_skip_only_checks(
        postchecks if postchecks is not None else BGP_STANDARD_POSTCHECKS
    )
    postchecks = base_postchecks + [
        *_no_crash_checks(),
        create_system_cpu_load_average_check(baseline=12.0),
        create_bgp_update_group_check(expect_enabled=True),
        create_log_parsing_check(start_time_jq_var="test_case_start_time"),
    ]
    if vmhwm_threshold_bytes is not None:
        postchecks.append(
            create_memory_utilization_check(vmhwm_threshold=vmhwm_threshold_bytes)
        )

    # Build a new list rather than appending to the caller's: mutating a
    # caller-supplied list would accumulate duplicate snapshot checks if the
    # same list were passed to more than one factory. Mirrors the postchecks
    # path, which already copies via list(postchecks).
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
        name="bgp_ug_peer_reconnect_shadow_rib",
        stages=stages,
        prechecks=prechecks,
        postchecks=postchecks,
        snapshot_checks=snapshot_checks,
        cleanup_steps=cleanup_steps,
    )


def create_bgp_ug_sustained_group_membership_churn_playbook(
    *,
    device_name: str,
    ebgp_peer_regex: str,
    ebgp_peer_group_substrings: t.List[str],
    ibgp_peer_group_substrings: t.List[str],
    non_ibgp_parent_prefixes: t.List[str],
    prechecks: t.List[PointInTimeHealthCheck],
    postchecks: t.Optional[t.List[PointInTimeHealthCheck]] = None,
    snapshot_checks: t.Optional[t.List[SnapshotHealthCheck]] = None,
    vmhwm_threshold_bytes: t.Optional[int] = None,
    memory_growth_threshold_bytes: int = _MEMORY_GROWTH_THRESHOLD_BYTES,
    sessions_to_flap_start_idx: int = 1,
    sessions_to_flap_end_idx: int = 32,
    cycles_per_checkpoint: int = 15,
    num_checkpoints: int = 4,
    flap_down_seconds: int = 20,
    flap_up_seconds: int = 40,
    session_retry_count: int = 4,
    session_retry_delay_seconds: float = 30.0,
) -> Playbook:
    """Build the BGP++ Update Group qualification 2.2.3 playbook
    (Sustained Group Membership Churn: No Memory Leak).

    Intent (spec 2.2.3): flap a subset of eBGP peers repeatedly for ~1 hour and
    prove group membership + route counts stay correct at every checkpoint and
    that memory does not leak (VmHWM growth < 200 MB, no crash / error logs /
    load-average breach).

    Structure: ``num_checkpoints`` (default 4) blocks, each running
    ``cycles_per_checkpoint`` (default 15) flap cycles then a checkpoint
    validation. 4 x 15 = 60 cycles at ~1 min/cycle (``flap_down_seconds`` +
    ``flap_up_seconds`` = 60s) ~= 1 hour, matching the source plan. Each cycle is
    stop-subset -> settle-down -> start-subset -> settle-up.

    Blocking signals (per checkpoint + postcheck):
      - iBGP Established + update groups intact + no crash at every checkpoint.
      - Memory growth (RSS delta over the run) < ``memory_growth_threshold_bytes``
        and absolute VmHWM < ``vmhwm_threshold_bytes``; no error logs; load
        average bounded.

    Note: each ``start_bgp_peers`` re-resolves peers via the root
    ``Topology.find()`` select. If IXIA cannot service that within the 600s
    gateway ceiling while the topology churns (T282904746), the flap step FAILS
    the run genuinely -- surfacing the infra limit rather than masking it.

    Args mirror the sibling lifecycle factories; see
    ``create_bgp_ug_peer_down_remaining_unaffected_playbook`` for shared params.
    """

    def _checkpoint_checks(idx: int) -> t.List[PointInTimeHealthCheck]:
        return [
            *_no_crash_checks(),
            create_bgp_session_establish_check(
                parent_prefixes_to_ignore=non_ibgp_parent_prefixes,
                retry_count=session_retry_count,
                retry_delay_seconds=session_retry_delay_seconds,
                check_id=f"churn_ibgp_established_ckpt{idx}",
            ),
            create_bgp_update_group_check(
                expect_enabled=True,
                peer_group_substrings=ebgp_peer_group_substrings
                + ibgp_peer_group_substrings,
                check_id=f"churn_ug_intact_ckpt{idx}",
            ),
            create_memory_utilization_check(
                delta=memory_growth_threshold_bytes,
                start_time_jq_var="test_case_start_time",
                vmhwm_threshold=vmhwm_threshold_bytes,
            ),
        ]

    stages = []
    for ckpt in range(1, num_checkpoints + 1):
        # One churn block: cycles_per_checkpoint flap cycles (stop -> down ->
        # start -> up), iterated by the stage runner.
        churn_stage = create_steps_stage(
            iteration=cycles_per_checkpoint,
            steps=[
                create_start_stop_bgp_peers_step(
                    start=False,
                    peer_regex=ebgp_peer_regex,
                    start_idx=sessions_to_flap_start_idx,
                    end_idx=sessions_to_flap_end_idx,
                    description=(
                        f"2.2.3 churn ckpt{ckpt} — stop eBGP subset "
                        f"[{sessions_to_flap_start_idx}:{sessions_to_flap_end_idx}]"
                    ),
                ),
                create_longevity_step(
                    duration=flap_down_seconds,
                    description=f"2.2.3 — down {flap_down_seconds}s",
                ),
                create_start_stop_bgp_peers_step(
                    start=True,
                    peer_regex=ebgp_peer_regex,
                    start_idx=sessions_to_flap_start_idx,
                    end_idx=sessions_to_flap_end_idx,
                    description=(
                        f"2.2.3 churn ckpt{ckpt} — start eBGP subset "
                        f"[{sessions_to_flap_start_idx}:{sessions_to_flap_end_idx}]"
                    ),
                ),
                create_longevity_step(
                    duration=flap_up_seconds,
                    description=f"2.2.3 — up {flap_up_seconds}s",
                ),
            ],
        )
        checkpoint_stage = create_steps_stage(
            steps=[
                create_validation_step(
                    point_in_time_checks=_checkpoint_checks(ckpt),
                    description=(
                        f"2.2.3 checkpoint {ckpt}/{num_checkpoints} — iBGP "
                        f"Established; update groups intact; no crash; memory "
                        f"growth bounded"
                    ),
                ),
            ],
        )
        stages.append(churn_stage)
        stages.append(checkpoint_stage)

    # Cleanup: ensure the flapped subset ends up restored.
    cleanup_steps: t.List[Step] = [
        create_start_stop_bgp_peers_step(
            start=True,
            peer_regex=ebgp_peer_regex,
            start_idx=sessions_to_flap_start_idx,
            end_idx=sessions_to_flap_end_idx,
            description=(
                f"2.2.3 cleanup — restore eBGP sessions "
                f"[{sessions_to_flap_start_idx}:{sessions_to_flap_end_idx}]"
            ),
        ),
    ]

    base_postchecks = _drop_skip_only_checks(
        postchecks if postchecks is not None else BGP_STANDARD_POSTCHECKS
    )
    postchecks = base_postchecks + [
        *_no_crash_checks(),
        create_system_cpu_load_average_check(baseline=12.0),
        create_bgp_update_group_check(expect_enabled=True),
        create_log_parsing_check(start_time_jq_var="test_case_start_time"),
        # Leak gate: RSS growth over the whole run bounded + absolute VmHWM
        # ceiling. bgpcpp exports no VmHWM counter, so growth is gated via the
        # RSS delta and VmHWM is gated absolutely (see create_memory_utilization
        # _check docstring); a VmHWM-growth-specific delta remains a gap.
        create_memory_utilization_check(
            delta=memory_growth_threshold_bytes,
            start_time_jq_var="test_case_start_time",
            vmhwm_threshold=vmhwm_threshold_bytes,
        ),
    ]

    # Build a new list rather than appending to the caller's: mutating a
    # caller-supplied list would accumulate duplicate snapshot checks if the
    # same list were passed to more than one factory. Mirrors the postchecks
    # path, which already copies via list(postchecks).
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
        name="bgp_ug_sustained_group_membership_churn",
        stages=stages,
        prechecks=prechecks,
        postchecks=postchecks,
        snapshot_checks=snapshot_checks,
        cleanup_steps=cleanup_steps,
    )
