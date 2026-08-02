# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""Spec 2.6 — Bit Allocation and Group Stability Under Flaps. UG qualification playbook factories.

Implemented:
- 2.6.1 Repeated Peer Flaps — Group Remains Stable
"""

import typing as t

from taac.health_checks.healthcheck_definitions import (
    create_bgp_session_establish_check,
    create_bgp_update_group_check,
    create_log_parsing_check,
    create_memory_utilization_check,
    create_system_cpu_load_average_check,
)

# Reuse the HW-proven no-crash gate from the sibling 2.9 edge-case module (same
# package). Importing (rather than re-declaring) honors "do not invent new
# primitives" and keeps the crash service/daemon set in one place. The periodic
# monitor is NOT reused here: 2.6.1 interleaves its health sample 1:1 into the flap
# loop (``_flap_cycle_monitor_step``) instead of running a separate windowed track.
from taac.playbooks.routing.factories.qual_bgp_update_group.tc9_edge_cases import (
    _no_crash_checks,
)
from taac.stages.stage_definitions import create_steps_stage
from taac.steps.step_definitions import (
    create_advertise_withdraw_prefixes_step,
    create_log_bgp_route_distribution_probe_step,
    create_longevity_step,
    create_snapshot_bgp_sent_route_counts_step,
    create_snapshot_bgp_vmhwm_step,
    create_start_stop_bgp_peers_step,
    create_validation_step,
    create_verify_bgp_sent_route_count_delta_step,
    create_verify_bgp_sent_route_counts_uniform_step,
    create_verify_bgp_update_group_member_addresses_step,
    create_verify_bgp_vmhwm_growth_step,
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


def _flap_cycle_monitor_step(
    *,
    cycle: int,
    cycles: int,
    non_ibgp_parent_prefixes: t.List[str],
    load_avg_baseline: float,
    retry_count: int,
    retry_delay_s: float,
) -> Step:
    """One health sample interleaved after a single flap cycle (spec 2.6.1 criteria
    3-proxy / 5 / 6): assert no BGP daemon crashed, the iBGP sessions stay
    Established (eBGP 1..32 is intentionally flapping, so scope to iBGP by ignoring
    the eBGP + BGP-MON parents), and the system load-average stays under baseline.

    Same three checks as ``_monitor_track_steps``, but emitted PER FLAP CYCLE rather
    than on a fixed wall-clock interval. Because the sample rides the flap loop, its
    coverage is exactly 1:1 with the flaps and co-terminates with them -- there is no
    separate windowed monitor track that can be starved by the shared-IXIA/device
    round-robin and then idle-tail against a quiescent box after the flaps end (the
    behavior HW-observed on the 2026-07-30 run)."""
    return create_validation_step(
        point_in_time_checks=[
            *_no_crash_checks(),
            create_bgp_session_establish_check(
                parent_prefixes_to_ignore=non_ibgp_parent_prefixes,
                retry_count=retry_count,
                retry_delay_seconds=retry_delay_s,
                check_id="repeated_flap_ibgp_established",
            ),
            create_system_cpu_load_average_check(baseline=load_avg_baseline),
        ],
        description=(
            f"2.6.1 monitor -- no crash; iBGP Established; "
            f"load-avg<={load_avg_baseline} (cycle {cycle + 1}/{cycles})"
        ),
    )


def _repeated_flap_track_steps(
    *,
    ebgp_peer_regex: str,
    flap_start_idx: int = 1,
    flap_end_idx: int = 32,
    down_hold_s: int = 5,
    up_hold_s: int = 5,
    cycles: int = 50,
    # Interleaved per-cycle health monitor (spec 2.6.1 criteria 3-proxy / 5 / 6). When
    # ``monitor_non_ibgp_parent_prefixes`` is set, one no-crash + iBGP-Established +
    # load-avg sample is appended after EACH flap cycle, so monitor coverage is exactly
    # 1:1 with the flaps and co-terminates with them (replacing the separate windowed
    # monitor track, which starved during the storm and idle-tailed after it). None ->
    # no interleaved monitor.
    monitor_non_ibgp_parent_prefixes: t.Optional[t.List[str]] = None,
    monitor_load_avg_baseline: float = 12.0,
    monitor_retry_count: int = 3,
    monitor_retry_delay_s: float = 10.0,
) -> t.List[Step]:
    """Track: flap the SAME fixed contiguous eBGP session range every cycle
    (spec 2.6.1 step 1: shut -> 5s -> up -> 5s, x50), with one interleaved
    no-crash/iBGP/load monitor sample after each cycle (see
    ``monitor_non_ibgp_parent_prefixes`` / ``_flap_cycle_monitor_step``).

    ``create_start_stop_bgp_peers_step`` applies ``start_idx``/``end_idx`` (1-based,
    inclusive) SYMMETRICALLY per-AFI to the combined v4|v6 eBGP regex, so
    ``[1, 32]`` flaps 32 sessions PER AFI (64 combined) -- exactly the spec's "32
    eBGP sessions" under dual-AFI. Flapping the IDENTICAL index range on every cycle
    is what makes criterion 1 ("the 32 reconnected peers are the same members") a
    genuine identity check rather than a random subset.

    Deliberately NOT ``ixia_restart_bgp_sessions`` / ``_session_flap_track_steps``
    (a RANDOM subset with no down-hold) nor ``_flap_bgp_peers`` (ALL sessions, no
    range) -- both violate the fixed-32 requirement.
    """
    steps: t.List[Step] = []
    for i in range(cycles):
        steps.extend(
            [
                create_start_stop_bgp_peers_step(
                    peer_regex=ebgp_peer_regex,
                    start=False,
                    start_idx=flap_start_idx,
                    end_idx=flap_end_idx,
                    description=(
                        f"2.6.1 flap {i + 1}/{cycles} -- shut eBGP sessions "
                        f"[{flap_start_idx}, {flap_end_idx}]/AFI"
                    ),
                ),
                create_longevity_step(
                    duration=down_hold_s,
                    description=(
                        f"2.6.1 flap {i + 1}/{cycles} -- hold DOWN {down_hold_s}s"
                    ),
                ),
                create_start_stop_bgp_peers_step(
                    peer_regex=ebgp_peer_regex,
                    start=True,
                    start_idx=flap_start_idx,
                    end_idx=flap_end_idx,
                    description=(
                        f"2.6.1 flap {i + 1}/{cycles} -- up eBGP sessions "
                        f"[{flap_start_idx}, {flap_end_idx}]/AFI"
                    ),
                ),
                create_longevity_step(
                    duration=up_hold_s,
                    description=(
                        f"2.6.1 flap {i + 1}/{cycles} -- hold UP {up_hold_s}s"
                    ),
                ),
            ]
        )
        # Interleave one health sample per cycle (1:1 with the flaps, co-terminating).
        if monitor_non_ibgp_parent_prefixes is not None:
            steps.append(
                _flap_cycle_monitor_step(
                    cycle=i,
                    cycles=cycles,
                    non_ibgp_parent_prefixes=monitor_non_ibgp_parent_prefixes,
                    load_avg_baseline=monitor_load_avg_baseline,
                    retry_count=monitor_retry_count,
                    retry_delay_s=monitor_retry_delay_s,
                )
            )
    return steps


def _repeated_flap_churn_track_steps(
    *,
    device_name: str,
    churn_pool_regexes: t.List[str],
    route_count: int = 10,
    interval_s: int = 30,
    cycles: int = 16,
) -> t.List[Step]:
    """Track: every ``interval_s`` advertise then withdraw ``route_count`` routes
    per AFI (spec 2.6.1 step 2: "inject 10 / withdraw 10 routes every 30s from the
    REMAINING eBGP peers", concurrent with the flapping).

    ``churn_pool_regexes`` point at DEDICATED disjoint eBGP-side pools. Pass a SINGLE
    combined ``v4|v6`` regex (matching both AFI pools) so each advertise/withdraw is ONE
    IXIA op that toggles BOTH pools -- 2 ops/cycle, the SAME rate as the flap -- rather
    than one op per AFI (4 ops/cycle): ``ixia_enable_disable_bgp_prefixes`` toggles every
    pool matched by the regex in a single apply. Because eBGP prefix pools use
    ``PeerPrefixDistribution.SHARED`` across the whole eBGP DG, the pool is sourced by
    every eBGP peer; the flapped sessions (1..32) are shut for most of the window and so
    naturally do not participate, leaving the churn on the REMAINING peers. Strict
    per-session source-isolation to sessions 33..140 is NOT expressible via a single
    advertise/withdraw regex (surfaced to DNE) -- the shared-pool + shut-flapped-peers
    approximation is the closest the primitive allows.

    Deliberately NOT ``_route_churn_track_steps`` -- that helper REQUIRES community
    rotation or ordered A/B/C variant pools; a plain advertise/withdraw loop is not one
    of its two modes. ``cycles`` is a DIRECT count (the playbook defaults it to
    ``flap_cycles`` so the churn SPANS the whole flap -- spec "during flapping"), NOT
    derived from a wall-clock window: at EBB scale each cycle's IXIA reconfigures
    SERIALIZE on the shared chassis (they can't overlap), so a duration/interval count
    over-counts. With the combined ``v4|v6`` regex the churn is 2 ops/cycle = the flap's
    rate, so churn=flap co-terminates (both finish together), interleaving with the flap
    ops to give ongoing route churn for the ENTIRE storm.
    """
    steps: t.List[Step] = []
    half = max(1, interval_s // 2)
    for i in range(cycles):
        for regex in churn_pool_regexes:
            steps.append(
                create_advertise_withdraw_prefixes_step(
                    device_name=device_name,
                    advertise=True,
                    prefix_pool_regex=regex,
                    prefix_start_index=0,
                    prefix_end_index=route_count,
                    description=(
                        f"2.6.1 churn {i + 1}/{cycles} -- inject {route_count} "
                        f"routes ({regex}) from the remaining eBGP peers"
                    ),
                )
            )
        steps.append(create_longevity_step(duration=half))
        for regex in churn_pool_regexes:
            steps.append(
                create_advertise_withdraw_prefixes_step(
                    device_name=device_name,
                    advertise=False,
                    prefix_pool_regex=regex,
                    prefix_start_index=0,
                    prefix_end_index=route_count,
                    description=(
                        f"2.6.1 churn {i + 1}/{cycles} -- withdraw {route_count} "
                        f"routes ({regex})"
                    ),
                )
            )
        steps.append(create_longevity_step(duration=interval_s - half))
    return steps


def create_bgp_ug_repeated_peer_flaps_group_stable_playbook(
    *,
    device_name: str,
    # Combined v4|v6 eBGP peer regex; the fixed flap range is applied symmetrically
    # per-AFI to it (32/AFI). iBGP is never flapped (stays the stable route source).
    ebgp_peer_regex: str,
    ebgp_v4_peer_group: str,
    ebgp_v6_peer_group: str,
    ibgp_v6_peer_group: str,
    # Per-AFI eBGP peer-name regexes for the criterion-1 per-peer IDENTITY check
    # (membership stage): the specific flapped 32/AFI target addresses are resolved
    # at RUNTIME from these (get_bgp_session_addresses), then asserted back in the
    # correct update group. When either is None the identity check is skipped and
    # only the aggregate 140/AFI count proxy runs.
    ebgp_v4_peer_regex: t.Optional[str] = None,
    ebgp_v6_peer_regex: t.Optional[str] = None,
    # Everything that is NOT an iBGP peer (both eBGP AFIs + BGP-MON): scopes the
    # "iBGP stays Established" monitor check to iBGP while eBGP is intentionally
    # flapping.
    non_ibgp_parent_prefixes: t.List[str],
    # --- Step-2 churn pools (dedicated disjoint eBGP-side pools, one per AFI) ---
    churn_pool_regexes: t.List[str],
    churn_route_count: int = 10,
    churn_interval_s: int = 30,
    # Churn cycle count. Default None -> MATCH ``flap_cycles`` so the churn spans the
    # ENTIRE flap storm (spec step 2: inject/withdraw "DURING flapping"). The flap and
    # churn tracks round-robin ~1:1 on the shared IXIA session, so equal counts make them
    # co-terminate; a smaller churn count ends early and leaves the flap tail churn-free.
    # This is a deliberate FIDELITY-over-runtime choice: IXIA ops SERIALIZE on the one
    # chassis, so each extra churn cycle (~4 ops) ADDS to the concurrent-stage wall-clock
    # -- it is NOT free/parallel. The churn count is still NOT window-derived (a
    # window/interval count over-counts ~5x at scale). Pass an explicit
    # int (e.g. 16 = the old spec-nominal ~8-min value) to intentionally cap the churn
    # short of the flap.
    churn_cycles: t.Optional[int] = None,
    # --- Step-5 distribution inject pools (dedicated unique-NLRI iBGP-side pools) ---
    # 200 new routes/AFI injected iBGP-side so the DUT re-advertises them to the eBGP
    # peers under next-hop-self and the flapped 32 actually RECEIVE them. None -> skip
    # that AFI's distribution leg.
    ibgp_inject_pool_regex: t.Optional[str] = None,
    ibgp_v6_inject_pool_regex: t.Optional[str] = None,
    inject_route_count: int = 200,
    # eBGP peer-address parent prefixes scoping the STRICT per-peer PS-gauge verifies
    # (criterion 2: distribution reaches ALL 140/AFI incl the flapped 32). None ->
    # skip that AFI.
    ebgp_v4_peer_parent_prefixes: t.Optional[t.List[str]] = None,
    ebgp_v6_peer_parent_prefixes: t.Optional[t.List[str]] = None,
    distribution_count_window: int = 10,
    distribution_tolerance: int = 3,
    # Peer-address subnets of the inject-SOURCE peers (the iBGP plane the 200-route
    # pools are advertised on), for the crit-2 distribution PROBE: it logs the DUT's
    # RECEIVED count on these + its SENT count to the eBGP peers, before/after inject
    # and after the settle, so a 0-delta run tells us received-vs-readvertised (settle
    # too short vs egress vs not-received). Diagnostic only -- None => no probe.
    inject_source_parent_prefixes: t.Optional[t.List[str]] = None,
    # ESCAPE HATCH for the distribution criterion (crit 2), per AFI. Default off ->
    # STRICT (the testconfig no longer flips these). Set True to XFAIL that AFI's
    # iBGP->eBGP distribution leg. Distribution is now STRICT: a live-DUT repro
    # (2026-07-28) proved the DUT DOES re-advertise the 200 injected iBGP routes to
    # every eBGP peer (per-peer PS 46500 -> 46700, both AFIs, community 65529:39744 on
    # the RIB best-path); the earlier 0-delta was a too-short 30s inject settle at
    # 1272-session scale right after the flap storm, now covered by the convergence poll
    # -- NOT the once-suspected D32 formulaic-inject regression (that theory is refuted).
    # HW run 2026-07-29 CONFIRMED strict: all 280 eBGP peers reached +200 (PS 46700) both
    # AFIs (then within the 900s settle; now waited for adaptively). Retained only as a
    # manual escape hatch.
    v4_distribution_expected_fail: bool = False,
    v4_distribution_expected_fail_reason: t.Optional[str] = None,
    v6_distribution_expected_fail: bool = False,
    v6_distribution_expected_fail_reason: t.Optional[str] = None,
    # --- Membership (criteria 1 + 3-proxy) ---
    expected_ebgp_member_count_per_afi: int = 140,
    expected_group_count: int = 4,
    # --- Criterion 4 (VmHWM growth < 200 MB over the whole flap+recovery bracket) ---
    vmhwm_growth_threshold_bytes: int = 200 * 1024 * 1024,
    # LOOSE mode for criterion 4: when True the whole-test VmHWM verify still RUNS +
    # LOGS the growth, but a >threshold breach is flagged (XFAIL) instead of failing the
    # test (the 200-MB bar is a first-run probe, not yet firm). A restart/crash still
    # fails (the verify's VmHWM-decrease check + the no-crash health checks).
    vmhwm_growth_expected_fail: bool = False,
    # --- Concurrent-stage sizing. IXIA ops across the tracks SERIALIZE on the shared
    # chassis (they can't truly overlap), so the stage wall-clock is ~the SUM of every
    # track's ops, not the max. The churn now MATCHES the flap (``churn_cycles`` defaults
    # to ``flap_cycles``) so it spans the whole storm, AND the churn uses a COMBINED
    # v4|v6 pool regex (one advertise + one withdraw op/cycle instead of one per AFI) =
    # 2 ops/cycle, SAME as the flap -> at 50 cycles churn ~= flap in op-demand, so they
    # co-terminate. The no-crash/iBGP/load monitor is NOT a separate windowed track: it
    # is interleaved 1:1 INTO the flap loop (one sample after each cycle via
    # ``_flap_cycle_monitor_step``), so its coverage is deterministically per-cycle and
    # co-terminates with the flaps -- no wall-clock window to size, no starvation by the
    # shared-IXIA/device round-robin, and no idle tail on a quiescent box. That idle tail
    # was the HW-observed failure of the old windowed monitor (run 2026-07-30): only ~8 of
    # its 20 samples landed during the ~59-min flap and the other ~12 drained afterward.
    # Criterion 4's VmHWM is likewise a whole-test snapshot/verify point-read bracket, not
    # a windowed monitor.
    flap_cycles: int = 50,
    flap_start_idx: int = 1,
    flap_end_idx: int = 32,
    flap_down_hold_s: int = 5,
    flap_up_hold_s: int = 5,
    # --- Interleaved per-cycle monitor (criteria 3-proxy / 5 / 6) ---
    # One no-crash/iBGP/load sample is emitted after each flap cycle (1:1, inside the
    # flap track), so there is no wall-clock monitor window to size.
    load_avg_baseline: float = 12.0,
    monitor_retry_count: int = 3,
    monitor_retry_delay_s: float = 10.0,
    # --- Timing / sessions / gates ---
    # Prime withdraw settle (pre-flap): a plain settle after withdrawing the inject +
    # churn pools; 30s is plenty and it runs once, so it is NOT bumped.
    inject_settle_s: int = 30,
    # Step-5 distribution wait: the verify-delta steps POLL each AFI's per-peer eBGP PS
    # until the inject has re-advertised AND the counts hold stable, up to a hard timeout
    # (convergence poll, shared with 2.5.x) -- no blind fixed settle. Under WITHOUT_OPEN_R
    # + next-hop-self the re-advertise is fast even post-flap: HW 2026-07-31 converged in
    # ~61s per AFI (WITHIN_SLA), so the hard cap is 300s and crit-2 fails only if nothing
    # converges by ``distribution_hard_timeout_s``. (Pre-poll blind runs waited up to
    # ~12-20 min at 1272-scale; the poll removed that guessing.) crit-2 is STRICT (the
    # escape hatches below remain default-off). ``distribution_settle_s`` is the SOFT
    # threshold -- the expected-convergence SLA marker (exceeding it logs CONVERGED_LATE,
    # not a failure) -- kept below the hard cap.
    distribution_settle_s: int = 120,
    # Convergence-poll tunables for the distribution wait (applied per verify-delta step).
    distribution_hard_timeout_s: int = 300,
    distribution_poll_interval_s: int = 30,
    distribution_stability_window_s: int = 60,
    recover_settle_s: int = 120,
    session_retry_count: int = 10,
    session_retry_delay_s: float = 30.0,
    # --- Checks ---
    prechecks: t.List[PointInTimeHealthCheck],
    postchecks: t.Optional[t.List[PointInTimeHealthCheck]] = None,
    snapshot_checks: t.Optional[t.List[SnapshotHealthCheck]] = None,
    bgp_mon_ignore_prefixes: t.Optional[t.List[str]] = None,
    # Optional absolute VmHWM ceiling postcheck (extra safety; consistent with the
    # other UG tests -- NOT the criterion-4 200-MB delta gate).
    vmhwm_absolute_threshold_bytes: t.Optional[int] = None,
) -> Playbook:
    """Build the BGP++ Update Group qualification 2.6.1 playbook (Repeated Peer
    Flaps -- Group Remains Stable).

    Intent (spec 2.6.1): rapidly flap the SAME 32 eBGP sessions (per AFI) x50 while
    concurrently churning routes and stressing the update-group bit allocation; after
    the flaps stop, the group must re-form with all members back, distribution must
    reach every peer (including the 32 that flapped), and the daemon must not crash or
    corrupt the group's member bit-allocation, all under bounded memory + load.

    Flow:
      0. Prechecks (caller-supplied) record the baseline: sessions Established, drain
         state, memory/CPU bounded, Update Group ENABLED with the baseline group count.
         A prime stage then WITHDRAWS the dedicated 200-route inject pools so the
         later distribution advertise is a genuinely-new +N (2.9.6-proven), and
         SNAPSHOTS bgpcpp VmHWM on the freshly-reloaded (cold) daemon -- the start of
         the whole-test criterion-4 growth bracket.
      1. Concurrent stage (~emergent flap wall-clock): two independent tracks --
         (a) ``_repeated_flap_track_steps``: the fixed-32/AFI flap loop (step 1), with
             one interleaved no-crash + iBGP-scoped session-establish + system
             load-average <= 12 sample after EACH cycle (criteria 3-proxy / 5 / 6,
             1:1 with the flaps -- ``_flap_cycle_monitor_step``);
         (b) ``_repeated_flap_churn_track_steps``: ``churn_cycles`` (spec nominal ~16)
             rounds of 10-advertise/10-withdraw on the remaining peers (step 2).
      2. Recover (step 3): bring the flapped range stably up, then GATE on a retrying
         all-eBGP session-establish check so every peer is re-Established before the
         membership read (2.9.6 race-avoidance), allowing the v6 next-hops to settle.
      3. Membership (criteria 1 + 3-proxy, step 4): assert the eBGP update group
         re-formed with the full member count PER AFI (140, NOT 32 -- the spec
         verifies all members back post-recovery) and the baseline group count, plus a
         log-parsing "no error logs" check and no crash. Then a per-peer IDENTITY
         check (criterion 1, literal) resolves the exact flapped-32/AFI addresses at
         runtime and asserts each is back in the correct update group (right
         peer-group + AFI), Established, and JOINED_RUNNING.
      4. Distribution (criterion 2, step 5): snapshot the eBGP-peer PS, inject the
         dedicated 200-route unique-NLRI iBGP-side pools for BOTH AFIs (re-advertised
         iBGP->eBGP under next-hop-self), then CONVERGENCE-POLL each AFI's verify-delta
         (no blind settle): wait until every eBGP peer's PS grows by ~200 and the counts
         hold stable, up to ``distribution_hard_timeout_s`` (adapts to the emergent
         post-flap re-advertise time at 1272-session scale). Then assert every eBGP peer
         (incl the flapped 32) grew by ~200 (delta) and has a non-zero UNIFORM count.
         STRICT by default: a live-DUT repro (2026-07-28) proved distribution works once
         given enough time (per-peer PS 46500 -> 46700, both AFIs, community 65529:39744
         on the RIB best-path); the earlier 0-delta was purely a too-short 30s settle,
         not the refuted D32 inject regression. Each AFI keeps a per-AFI XFAIL escape
         hatch (``v4/v6_distribution_expected_fail``, default off).
      5. Criterion-4 VmHWM verify (final stage): close the whole-test point-read bracket
         -- assert bgpcpp VmHWM grew < 200 MB since the cold-daemon prime snapshot (the
         measurement auto-matches the emergent flap+recovery length; a DECREASE => a
         restart still hard-fails). LOOSE by default (``vmhwm_growth_expected_fail``): a
         breach is flagged, not failed, while the 200-MB bar is not yet firm.
      6. Postchecks: the standard bundle (asserts no stale routes) + load-average <= 12
         + Update Group still enabled + an optional absolute VmHWM ceiling.

    Design notes / limitations honored from the plan's adversarial review:
      * TRACKS SERIALIZE, WALL-CLOCK IS EMERGENT: every IXIA op (flap start/stop, churn
        advertise/withdraw) triggers an uncached topology walk on the ~1272-session
        build (~17s each) and the ops CANNOT overlap on the shared chassis, so the
        "concurrent" stage runs its tracks round-robin and its wall-clock is ~the SUM of
        all ops, not the max. The flap is the spec-mandated heavy track (100 ops); the
        churn is deliberately a small FIXED count (``churn_cycles`` ~16 -> 64 ops), NOT
        derived from a wall-clock window -- an earlier duration/interval sizing gave
        80 cycles (320 ops) and ran the stage ~2 h. The no-crash/iBGP/load monitor is
        interleaved 1:1 INTO the flap loop (one sample per cycle), so it needs no window
        and cannot self-terminate early or idle-tail: it covers exactly the flaps and
        stops with them. (The previous windowed monitor DID mis-behave under this
        serialized round-robin -- HW run 2026-07-30 landed only ~8 of 20 samples during
        the ~59-min flap and drained the rest afterward -- which is why it was replaced.)
        Criterion 4's VmHWM is likewise a whole-test snapshot/verify bracket (see the
        VmHWM bullet) that auto-matches the emergent length, so it cannot silently
        FALSE-PASS on an under-sized window.
      * VmHWM (criterion 4): a point-read primitive now exists, so the 200-MB growth
        gate is a WHOLE-TEST bracket -- ``create_snapshot_bgp_vmhwm_step`` in the prime
        stage (cold daemon, before the flap) paired with
        ``create_verify_bgp_vmhwm_growth_step`` as the final stage (after
        recovery/membership/distribution). The measurement auto-matches however long the
        flap emergently runs -- no fixed ``duration_seconds`` window to size, replacing
        the old spanning ``bgp_vmhwm_growth_monitor``. The verify also fails on a VmHWM
        decrease, doubling as a crash detector. VmHWM is a monotonic high-water mark, so
        criterion 4 is only meaningful when bgpcpp is a freshly RELOADED daemon --
        exactly what the 2.6.1 precondition mandates ("Enable Update Group in
        bgp_setting_config and reload BGP daemon"; the full setup starts bgpcpp fresh).
        Reusing an already-running daemon (the dev-iteration norm) masks the peak. (NB
        the spec word "cold" belongs to a different test, 2.7.5 Cold Start; 2.6.1 just
        says "reload BGP daemon".) The optional absolute VmHWM postcheck ceiling is a
        separate, weaker safety net.
      * CRITERION 3 (no bit-allocation corruption) is a COMPOSITE PROXY -- DNE-APPROVED
        as the interim (2026-07-27): group count back to baseline + member counts back
        to 140/AFI + all-Established + distribution reaches everyone + no crash + no
        error logs (exactly as 2.9.7 proved "no stale group"). Per DNE the actual
        corruption mode is a DOUBLE-FREE (freeing the same consumer bit twice), and
        there is NO direct signal today (bgpcpp neither logs it nor checks the
        freeConsumerBit return). DNE will add freeConsumerBit logging/counters as a
        follow-up; once landed, add a direct create_log_parsing_check / counter check
        here for the direct signal. A double-free / bit leak also bloats the tracking
        structures, so criterion 4's VmHWM gate is a partial indirect guard.
      * CRITERION 1 (same 32 re-form) is verified TWO ways (belt + suspenders): a
        genuine per-peer IDENTITY check (``create_verify_bgp_update_group_member_addresses_step``)
        resolves the exact flapped-32/AFI peer addresses at RUNTIME
        (``get_bgp_session_addresses`` -- never re-derived arithmetically, which is
        the start_index/DutIp offset bug) and asserts each is back in an update
        group with the correct ``peer_group_name`` + AFI, Established, and
        JOINED_RUNNING -- catching a duplicated / stale / wrong-identity member that
        a bare count cannot; PLUS the AGGREGATE member counts returning to 140/AFI
        (the coarser proxy retained as a cross-check). The identity check is skipped
        (only the aggregate runs) if the per-AFI ``ebgp_v4/v6_peer_regex`` are not
        supplied.
      * DISTRIBUTION IS COUNT-ONLY (PS gauge = postpolicy_sent_prefix_count):
        ``getPostfilterAdvertisedNetworks`` set-equality is vacuous under an Update
        Group (T271301144), so the uniform + delta PS checks are the UG-safe substitute.
    """
    # Churn spans the whole flap by default: match the flap cycle count so the two
    # tracks (which round-robin ~1:1 on the shared IXIA session) co-terminate, keeping
    # inject/withdraw active for the ENTIRE flap storm (spec step 2). Callers can still
    # pass an explicit churn_cycles to cap it short.
    if churn_cycles is None:
        churn_cycles = flap_cycles
    # --- Prime stage: withdraw the dedicated 200-route inject pools so the later
    # distribution advertise is a genuinely-new +N (the pools come up Active at
    # build). iBGP is never flapped, so it is already the stable route source. ---
    dedicated_inject_pools: t.List[str] = [
        pool
        for pool in (ibgp_inject_pool_regex, ibgp_v6_inject_pool_regex)
        if pool is not None
    ]
    prime_steps: t.List[Step] = [
        create_advertise_withdraw_prefixes_step(
            device_name=device_name,
            advertise=False,
            prefix_pool_regex=pool,
            prefix_start_index=0,
            prefix_end_index=inject_route_count,
            description=(
                f"2.6.1 prime -- withdraw the dedicated inject pool "
                f"[0, {inject_route_count}) so its later advertise is a genuine +N"
            ),
        )
        for pool in dedicated_inject_pools
    ]
    # Also withdraw the churn pools (they come up Active at build), so the churn
    # track's very FIRST advertise each cycle is a genuine +N injection rather than
    # a no-op on already-active routes.
    prime_steps.extend(
        create_advertise_withdraw_prefixes_step(
            device_name=device_name,
            advertise=False,
            prefix_pool_regex=pool,
            prefix_start_index=0,
            prefix_end_index=churn_route_count,
            description=(
                f"2.6.1 prime -- withdraw the churn pool [0, {churn_route_count}) so "
                "its first churn advertise is a genuine injection"
            ),
        )
        for pool in churn_pool_regexes
    )
    prime_steps.append(
        create_longevity_step(
            duration=inject_settle_s,
            description="2.6.1 prime -- settle after withdrawing inject + churn pools",
        )
    )
    prime_steps.append(
        create_validation_step(
            point_in_time_checks=[
                *_no_crash_checks(),
                create_bgp_session_establish_check(
                    parent_prefixes_to_ignore=non_ibgp_parent_prefixes,
                    retry_count=session_retry_count,
                    retry_delay_seconds=session_retry_delay_s,
                    check_id="repeated_flap_prime_ibgp_up",
                ),
                create_bgp_update_group_check(
                    expect_enabled=True,
                    peer_group_substrings=[ibgp_v6_peer_group],
                    check_id="repeated_flap_prime_ibgp_ug",
                ),
            ],
            description=(
                "2.6.1 prime -- iBGP source up, iBGP update group formed, no crash "
                "(baseline before the flap storm)"
            ),
        )
    )
    # Criterion-4 baseline: snapshot bgpcpp VmHWM on the freshly-reloaded (cold) daemon,
    # BEFORE the flap storm, as the OPEN half of a whole-test point-read bracket (the
    # matching verify is the final stage). Auto-matches the emergent flap length -- no
    # fixed monitor window. Only meaningful because the 2.6.1 precondition reloads bgpcpp
    # fresh; a still-running daemon would already carry a higher monotonic high-water.
    prime_steps.append(
        create_snapshot_bgp_vmhwm_step(
            hostname=device_name,
            snapshot_key="repeated_flap_vmhwm",
            description=(
                "2.6.1 criterion 4 -- baseline bgpcpp VmHWM before the flap (cold "
                "daemon; whole-test bracket)"
            ),
        )
    )

    # --- Stage 1: the concurrent flap storm + churn + monitor. ---
    concurrent_steps: t.List[ConcurrentStep] = [
        ConcurrentStep(
            steps=_repeated_flap_track_steps(
                ebgp_peer_regex=ebgp_peer_regex,
                flap_start_idx=flap_start_idx,
                flap_end_idx=flap_end_idx,
                down_hold_s=flap_down_hold_s,
                up_hold_s=flap_up_hold_s,
                cycles=flap_cycles,
                # Interleave the no-crash/iBGP/load monitor 1:1 with the flap cycles
                # (one sample per cycle) instead of a separate windowed monitor track.
                monitor_non_ibgp_parent_prefixes=non_ibgp_parent_prefixes,
                monitor_load_avg_baseline=load_avg_baseline,
                monitor_retry_count=monitor_retry_count,
                monitor_retry_delay_s=monitor_retry_delay_s,
            )
        ),
        ConcurrentStep(
            steps=_repeated_flap_churn_track_steps(
                device_name=device_name,
                churn_pool_regexes=churn_pool_regexes,
                route_count=churn_route_count,
                interval_s=churn_interval_s,
                cycles=churn_cycles,
            )
        ),
    ]

    flap_stage = create_steps_stage(
        concurrent=True,
        concurrent_steps=concurrent_steps,
        description=(
            "2.6.1 -- 50 fixed-32/AFI flap cycles (each followed 1:1 by a "
            "no-crash/iBGP/load monitor sample) + remaining-peer route churn "
            "(stage ends when the longest track finishes)"
        ),
    )

    # --- Stage 2: recover -- bring the flapped range stably up and gate on all eBGP
    # re-Established before the membership read (2.9.6 race-avoidance; also lets the
    # v6 next-hops settle). ---
    recover_stage = create_steps_stage(
        steps=[
            create_start_stop_bgp_peers_step(
                peer_regex=ebgp_peer_regex,
                start=True,
                start_idx=flap_start_idx,
                end_idx=flap_end_idx,
                description=(
                    "2.6.1 step 3 -- bring the flapped eBGP range "
                    f"[{flap_start_idx}, {flap_end_idx}]/AFI stably UP"
                ),
            ),
            create_longevity_step(
                duration=recover_settle_s,
                description=(
                    "2.6.1 step 3 -- settle for full eBGP re-establish + v6 next-hop "
                    "resolution"
                ),
            ),
            create_validation_step(
                point_in_time_checks=[
                    *_no_crash_checks(),
                    create_bgp_session_establish_check(
                        parent_prefixes_to_ignore=bgp_mon_ignore_prefixes,
                        retry_count=session_retry_count,
                        retry_delay_seconds=session_retry_delay_s,
                        check_id="repeated_flap_recovery_sessions",
                    ),
                ],
                description=(
                    "2.6.1 step 3 -- all eBGP sessions re-Established (excl BGP-MON) "
                    "after the flap storm; no crash"
                ),
            ),
        ],
    )

    # --- Stage 3: membership (criteria 1 + 3-proxy) + log-parsing. ---
    membership_steps: t.List[Step] = [
        create_validation_step(
            point_in_time_checks=[
                *_no_crash_checks(),
                create_bgp_update_group_check(
                    expect_enabled=True,
                    peer_group_substrings=[
                        ebgp_v4_peer_group,
                        ebgp_v6_peer_group,
                        ibgp_v6_peer_group,
                    ],
                    expected_member_counts={
                        ebgp_v4_peer_group: expected_ebgp_member_count_per_afi,
                        ebgp_v6_peer_group: expected_ebgp_member_count_per_afi,
                    },
                    expected_group_count=expected_group_count,
                    check_id="repeated_flap_recovery_ug_membership",
                ),
                # "No error logs" over the test window -- part of the criterion-3
                # composite proxy (no bit-allocation corruption surfaced in logs).
                create_log_parsing_check(start_time_jq_var="test_case_start_time"),
            ],
            description=(
                "2.6.1 step 4 -- eBGP update group re-formed: "
                f"{expected_ebgp_member_count_per_afi} members/AFI back, "
                f"{expected_group_count} groups (criterion 1 aggregate count + "
                "criterion 3 composite proxy); no error logs; no crash"
            ),
        ),
    ]
    # Criterion 1 (LITERAL identity): assert the SAME flapped 32/AFI peers are back
    # in the correct update group -- resolve their exact addresses at RUNTIME and
    # check per-peer membership + AFI + Established + JOINED_RUNNING. This is the
    # genuine identity check the aggregate 140/AFI count only PROXIES (a count of
    # 140 cannot catch a duplicated / stale / wrong-identity member). Kept ALONGSIDE
    # the aggregate check (belt + suspenders). Skipped only if the per-AFI regexes
    # were not supplied.
    if ebgp_v4_peer_regex is not None and ebgp_v6_peer_regex is not None:
        membership_steps.append(
            create_verify_bgp_update_group_member_addresses_step(
                hostname=device_name,
                ebgp_v4_peer_regex=ebgp_v4_peer_regex,
                ebgp_v6_peer_regex=ebgp_v6_peer_regex,
                ebgp_v4_peer_group=ebgp_v4_peer_group,
                ebgp_v6_peer_group=ebgp_v6_peer_group,
                flap_start_idx=flap_start_idx,
                flap_end_idx=flap_end_idx,
                description=(
                    "2.6.1 criterion 1 (identity) -- the SAME flapped eBGP peers "
                    f"[{flap_start_idx}, {flap_end_idx}]/AFI are back in the correct "
                    "update group (per-peer address membership + AFI + Established + "
                    "JOINED_RUNNING)"
                ),
            )
        )
    membership_stage = create_steps_stage(steps=membership_steps)

    # --- Stage 4: distribution (criterion 2) -- snapshot BOTH AFIs' eBGP PS, inject
    # BOTH dedicated 200-route pools, then verify each AFI's +N delta + non-zero uniform
    # over ALL eBGP peers incl the flapped 32. Each verify-delta step CONVERGENCE-POLLS
    # (no blind settle): it waits for the +N re-advertise to land and hold stable, up to
    # ``distribution_hard_timeout_s`` (the 300s fail cap), classifying the convergence
    # time against ``distribution_settle_s`` (the 120s SOFT SLA marker -- WITHIN_SLA vs
    # CONVERGED_LATE, both PASS; only failing to converge by the hard cap fails). crit-2
    # is STRICT on BOTH AFIs: HW 2026-07-31 landed it converging in ~61s (WITHIN_SLA),
    # so the poll adapts to the emergent post-flap convergence time instead of the old
    # blind wait. The received-vs-sent probe logs the trajectory around the inject. ---
    dist_legs = [
        (label, parents, pool, xfail, reason)
        for (label, parents, pool, xfail, reason) in (
            (
                "v4",
                ebgp_v4_peer_parent_prefixes,
                ibgp_inject_pool_regex,
                v4_distribution_expected_fail,
                v4_distribution_expected_fail_reason,
            ),
            (
                "v6",
                ebgp_v6_peer_parent_prefixes,
                ibgp_v6_inject_pool_regex,
                v6_distribution_expected_fail,
                v6_distribution_expected_fail_reason,
            ),
        )
        if parents is not None and pool is not None
    ]
    distribution_steps: t.List[Step] = []
    if dist_legs:
        # eBGP re-advertise-target scopes across all active AFIs (probe SENT scope).
        sent_parents_all = [p for _, parents, _, _, _ in dist_legs for p in parents]
        # 1) Snapshot each AFI's eBGP PS baseline BEFORE any inject.
        for afi_label, afi_parents, _pool, _xf, _reason in dist_legs:
            distribution_steps.append(
                create_snapshot_bgp_sent_route_counts_step(
                    hostname=device_name,
                    snapshot_key=f"repeated_flap_dist_ebgp_{afi_label}",
                    peer_parent_prefixes=afi_parents,
                    description=(
                        f"2.6.1 step 5 ({afi_label}) -- snapshot eBGP {afi_label} PS "
                        "before the 200-route inject"
                    ),
                )
            )
        # 2) Inject each AFI's dedicated 200-route iBGP pool.
        for afi_label, _parents, afi_pool, _xf, _reason in dist_legs:
            distribution_steps.append(
                create_advertise_withdraw_prefixes_step(
                    device_name=device_name,
                    advertise=True,
                    prefix_pool_regex=afi_pool,
                    prefix_start_index=0,
                    prefix_end_index=inject_route_count,
                    description=(
                        f"2.6.1 step 5 ({afi_label}) -- inject {inject_route_count} "
                        f"genuinely-new iBGP {afi_label} routes (dedicated pool) so the "
                        "DUT re-advertises them to every eBGP peer"
                    ),
                )
            )
        # 3) Probe at t0 (right after inject): is the inject RECEIVED yet, how much SENT?
        if inject_source_parent_prefixes is not None:
            distribution_steps.append(
                create_log_bgp_route_distribution_probe_step(
                    hostname=device_name,
                    label="after-inject",
                    received_parent_prefixes=inject_source_parent_prefixes,
                    sent_parent_prefixes=sent_parents_all,
                )
            )
        # 4) No fixed settle: the verify-delta steps below POLL each AFI's per-peer PS
        # until the +N re-advertise lands and holds stable, up to the hard timeout
        # (adapts to the emergent post-flap convergence time instead of a blind wait).
        # 5) Verify each AFI: +N delta (convergence-POLLED) + non-zero uniform over ALL
        # eBGP peers.
        for (
            afi_label,
            afi_parents,
            _pool,
            afi_expected_fail,
            afi_fail_reason,
        ) in dist_legs:
            snap_key = f"repeated_flap_dist_ebgp_{afi_label}"
            distribution_steps.extend(
                [
                    create_verify_bgp_sent_route_count_delta_step(
                        hostname=device_name,
                        snapshot_key=snap_key,
                        peer_parent_prefixes=afi_parents,
                        min_delta=max(
                            1, inject_route_count - distribution_count_window
                        ),
                        # No max: the criterion is "all peers receive the routes"; the
                        # DUT may re-advertise a v6 EB-PRIVATE range with expansion.
                        tolerance=distribution_tolerance,
                        # Convergence poll: wait adaptively for this AFI's +N to land
                        # and hold, up to the hard timeout, instead of a blind settle.
                        convergence_hard_timeout_seconds=float(
                            distribution_hard_timeout_s
                        ),
                        convergence_poll_interval_seconds=float(
                            distribution_poll_interval_s
                        ),
                        convergence_stability_window_seconds=float(
                            distribution_stability_window_s
                        ),
                        convergence_soft_threshold_seconds=float(distribution_settle_s),
                        expected_fail=afi_expected_fail,
                        expected_fail_reason=afi_fail_reason,
                        description=(
                            f"2.6.1 criterion 2 ({afi_label}) -- every eBGP {afi_label} "
                            f"peer's PS grew by >= ~{inject_route_count}: the inject "
                            "reached ALL peers (incl the 32 that flapped)"
                        ),
                    ),
                    create_verify_bgp_sent_route_counts_uniform_step(
                        hostname=device_name,
                        peer_parent_prefixes=afi_parents,
                        min_count=1,
                        max_spread=distribution_count_window,
                        tolerance=distribution_tolerance,
                        expected_fail=afi_expected_fail,
                        expected_fail_reason=afi_fail_reason,
                        description=(
                            f"2.6.1 criterion 2 ({afi_label}) -- every eBGP {afi_label} "
                            "peer has a NON-ZERO, UNIFORM route count (no peer, incl the "
                            "flapped 32, is missing routes)"
                        ),
                    ),
                ]
            )
        # Post-convergence probe: log the final SENT (re-advertised) vs RECEIVED once
        # both AFIs have converged, so a passing run records the landed trajectory.
        if inject_source_parent_prefixes is not None:
            distribution_steps.append(
                create_log_bgp_route_distribution_probe_step(
                    hostname=device_name,
                    label="after-convergence",
                    received_parent_prefixes=inject_source_parent_prefixes,
                    sent_parent_prefixes=sent_parents_all,
                )
            )
    # No crash after the distribution inject.
    distribution_steps.append(
        create_validation_step(
            point_in_time_checks=list(_no_crash_checks()),
            description="2.6.1 step 5 -- no crash after the distribution inject",
        )
    )

    # --- Stage 5 (final, before postchecks): criterion-4 VmHWM verify -- close the
    # whole-test point-read bracket opened by the prime-stage snapshot. Reads bgpcpp
    # VmHWM now and asserts growth over the cold-daemon baseline is < 200 MB, so the
    # measurement auto-matches the EMERGENT flap+recovery+distribution length (no fixed
    # window). LOOSE by default (``vmhwm_growth_expected_fail``): a breach is flagged
    # (XFAIL), not failed, while the 200-MB bar is not yet firm per DNE; a VmHWM DECREASE
    # (bgpcpp restart) still hard-fails. ---
    vmhwm_verify_stage = create_steps_stage(
        steps=[
            create_verify_bgp_vmhwm_growth_step(
                hostname=device_name,
                snapshot_key="repeated_flap_vmhwm",
                growth_threshold_bytes=vmhwm_growth_threshold_bytes,
                expected_fail=vmhwm_growth_expected_fail,
                expected_fail_reason=(
                    "The 200-MB VmHWM growth bar is a first-run probe and not yet firm "
                    "per DNE (the memory-bar discussion is open; 2.9.2 exceeded its "
                    "500-MB bar) -- flag a breach rather than fail. A restart/crash "
                    "(VmHWM decrease) still hard-fails."
                ),
                description=(
                    "2.6.1 criterion 4 -- bgpcpp VmHWM growth over the whole "
                    "flap+recovery bracket vs 200 MB"
                ),
            ),
        ],
    )

    stages = [
        create_steps_stage(steps=prime_steps),
        flap_stage,
        recover_stage,
        membership_stage,
        create_steps_stage(steps=distribution_steps),
        vmhwm_verify_stage,
    ]

    # Always-appended bounds (spec criteria 5/6 + "no stale routes"), whether the
    # caller takes the default bundle or supplies its own list, so a caller-provided
    # ``postchecks`` can never silently drop them.
    base_postchecks = (
        list(postchecks) if postchecks is not None else list(BGP_STANDARD_POSTCHECKS)
    )
    postchecks = base_postchecks + [
        create_system_cpu_load_average_check(baseline=load_avg_baseline),
        create_bgp_update_group_check(expect_enabled=True),
    ]
    # Optional absolute VmHWM ceiling (extra safety; the standard memory postcheck
    # SKIPs on Arista -- RSS-delta only). NOT the criterion-4 200-MB delta gate.
    if vmhwm_absolute_threshold_bytes is not None:
        postchecks.append(
            create_memory_utilization_check(
                vmhwm_threshold=vmhwm_absolute_threshold_bytes
            )
        )
    if snapshot_checks is None:
        snapshot_checks = list(BGP_STANDARD_SNAPSHOT_CHECKS)

    return Playbook(
        name="bgp_ug_repeated_peer_flaps",
        stages=stages,
        prechecks=prechecks,
        postchecks=postchecks,
        snapshot_checks=snapshot_checks,
    )
