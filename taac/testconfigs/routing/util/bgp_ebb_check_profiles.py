# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""Check-profile registry — the single source of truth for *which* health
checks each Conveyor test runs and their per-(check, phase) functional params.

Background: previously every test's pre/post/snapshot policy (which checks,
convergence on/off, ``fail_on_eor_expired``, thresholds) was decided ad-hoc at
each playbook/config call site, in three parallel definition styles. That made
"what does test X check" and "flip EOR for test Y" hard to see and easy to drift
(see the dne_routing Conveyor health-check audit). This registry collapses that
into one declarative place: a playbook looks up its profile instead of
hand-assembling check lists.

Two parameter categories, deliberately kept separate:

* **Retry policy** (retry_count / delay / multiplier) — keyed by *check* alone,
  identical across pre/post and across all tests. It is NOT specified here; it
  is pulled from ``retry_policy`` (the SSOT) and baked into each check via the
  factory. Profiles never hand-pass retry numbers, which is what kills the drift.
* **Functional params** (``validate_sequence``, ``fail_on_eor_expired``,
  ``convergence_threshold``, …) — keyed by *(check, phase)* and may differ
  between the pre and post bundles of the SAME check. These ARE declared here,
  explicitly, so an EOR-type issue is a one-line edit in one visible place.

Every profile builder takes a ``ProfileContext`` (a uniform, required arg)
carrying the per-invocation, device-specific runtime values (peer groups,
thresholds, cpu_baseline, …). Standard-shape profiles thread those through the
shared ``create_standard_{pre,post,snapshot}`` factories and fix only the
POLICY; minimal-shape profiles (e.g. ``PERF_SCALING_BOUNDED_ECMP``) hand-pick a
few checks and ignore the context. Keeping the signature uniform means callers
never have to reason about which profiles need a context.

All checks are built via the ``create_*`` factories (never constructed inline)
so the ``test_no_inline_healthcheck_construction`` gate stays satisfied.
"""

from __future__ import annotations

import dataclasses
import enum
import typing as t

from taac.abstractions.compatibility.legacy_ebb_binding import (
    IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE1,
    IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE1,
)
from taac.health_checks.healthcheck_definitions import (
    create_bgp_convergence_check,
    create_bgp_rib_fib_consistency_check,
    create_bgp_route_count_verification_check,
    create_bgp_session_establish_check,
    create_bgp_session_snapshot_check,
    create_bgp_tcpdump_check,
    create_core_dumps_snapshot_check,
    create_cpu_percentile_observe_check,
    create_hardware_capacity_check,
    create_next_hop_count_check,
    create_rss_delta_observe_check,
)
from taac.health_checks.retry_policy import get_retry_kwargs
from taac.testconfigs.routing.util.bgp_ebb_health_checks import (
    BgpMonScope,
    create_standard_postchecks,
    create_standard_prechecks,
    create_standard_snapshot_checks,
    DEFAULT_BGP_MON_SCOPE,
)
from taac.utils.characterization import (
    CPU_SUMMARY_JQ_VAR,
    RSS_SUMMARY_JQ_VAR,
)
from taac.health_check.health_check import types as hc_types
from taac.test_as_a_config.types import PointInTimeHealthCheck, SnapshotHealthCheck

# SC9 asserts on the eBGP population and nothing else: the 128 eBGP peers per
# AFI are what advertise the 5,000 prefixes, and the ECMP sets under test are
# built entirely from them. The topology's iBGP "mimic" groups carry
# ``bgp_prefix_configs=[]`` -- they advertise NOTHING and contribute no path to
# any ECMP set -- so a shortfall there cannot affect a single SC9 assertion.
#
# Scoping them out is therefore correct, not convenient. It is also necessary:
# on the first bag013 run 22 of the 128 IPv6 iBGP peers sat in IDLE from before
# the prechecks through every retry (all 256 eBGP were Established), which fails
# the run on a population the test does not measure. Those 22 are a real open
# question about the lab topology and are tracked separately; they are not an
# SC9 result, and SC9 should not be the thing that reports them.
#
# The constants are bare prefixes, so the masks are applied here.
#
# The v6 mask is /80, NOT /64. eBGP and iBGP differ only in the FIFTH hextet
# ("...:11:8::" vs "...:11:9::"), which sits beyond a /64 boundary --
# `is_parent_prefix` calls `ip_network(prefix, strict=False)`, so
# "2401:db00:e50d:11:9::/64" silently normalises to "2401:db00:e50d:11::/64"
# and swallows the eBGP range as well. That is not theoretical: with /64 the
# first clean bag013 run reported "All 133 BGP sessions are established" --
# 128 eBGP v4 plus 5 others, with all 128 eBGP v6 sessions quietly out of
# scope. /80 covers exactly the five hextets that distinguish the two.
#
# The v4 mask is /23, NOT /24, because the peer range ROLLS OVER. iBGP v4
# starts at 10.164.28.11 and steps by 2 for 128 peers, so the last five land at
# 10.164.29.1 .. .9 -- past the /24 boundary. A /24 leaves exactly those five in
# scope, which is the other half of the 133 the first clean run reported:
# 128 eBGP v4 (correctly in scope) + 5 iBGP v4 stragglers (wrongly in scope).
# /23 covers 10.164.28.0-10.164.29.255 and still excludes eBGP, which lives in
# 10.163.28.0/23. The v6 peers do not roll over -- they run ::11 to ::10f,
# entirely inside the fifth hextet -- so /80 is exact there.
#
# Net effect of the two masks: exactly the 256 eBGP sessions stay in scope.
IBGP_MIMIC_PARENTS: t.List[str] = [
    f"{IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE1}::/80",
    f"{IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE1}.0/23",
]

# 128 eBGP peers per AFI, both AFIs -- the population the masks above leave in
# scope. Shared with the playbook's drain stage so the session count the drain
# asserts and the count the postcheck asserts cannot drift apart.
SC9_EBGP_SESSION_COUNT = 256

# Absolute bound on the device-maintained ECMP peak. DNE's already-sanctioned
# bar (health_checks/constants.py) rather than a number invented here, and it
# has to be ABSOLUTE: the watermark cannot be reset in-test, so bag013 carried a
# pre-existing peak of 416 into the first SC9 run and will carry one into every
# run until it is reloaded. A bound below that would fail on lab history rather
# than on anything SC9 did.
# Applied at BOTH the precheck and the postcheck, at the same value, so a peak
# the box arrived with is attributed to the testbed instead of to SC9's drain.
_SC9_MAX_ECMP_HIGH_WATERMARK = 1000

_LIFECYCLE_CONVERGENCE_HARD_TIMEOUT_SECONDS = 1200
_SOAK_READINESS_STABILITY_WINDOW_SECONDS = 30.0
RUNTIME_UPDATE_EXACT_PEER_GROUP_NAMES = ("EB-FA-V6", "EB-FA-V4")


class CheckProfile(enum.Enum):
    """Named check profiles. Add one entry per de-facto test profile and route
    the playbook through ``get_profile_checks`` instead of inlining checks.
    """

    # Standard-shape (compose create_standard_* + a ProfileContext):
    # BGP/agent daemon restart, convergence ON, restart-aware postcheck, strict
    # EOR (EOR-timer expiry fails the convergence check).
    DAEMON_RESTART = "daemon_restart"
    # Full cold start, convergence ON, EOR tolerated, full snapshot.
    COLD_START = "cold_start"
    # BGP route/session oscillation & multipath churn: convergence OFF; which
    # snapshot sub-checks to skip varies by sub-shape (carried in the context).
    OSCILLATION = "oscillation"
    # FA/plane drain-undrain: convergence OFF, iBGP-PNH precheck off, snapshot
    # skips flap only (uptime still checked).
    DRAIN_UNDRAIN = "drain_undrain"
    # CICD-EBB-11 route storm: convergence OFF, expected established-session count
    # enforced, and a context-selected snapshot shape. The custom steps own
    # exact in-window route, attribute, and session-stability verdicts.
    CHURN_STORM = "churn_storm"
    # IGP instability (PNH-metric oscillation / unresolvable PNHs): convergence
    # OFF, standard snapshot, plus a BGP tcpdump check whose message-types and
    # last-mod-time window come from the context.
    IGP_INSTABILITY = "igp_instability"
    # No-precheck longevity stress: standard postchecks and a snapshot that
    # skips flap + uptime (sessions churn during the workload).
    SOAK_NO_PRECHECK = "soak_no_precheck"
    # CICD-EBB-16: block route oscillation until required sessions, ingress EOR,
    # accepted routes, and all three route-programming views are ready. The
    # postcheck tolerates setup-era EOR expiry because readiness is established
    # before the workload begins.
    SOAK_READINESS_GATED = "soak_readiness_gated"
    # Route-registry prefix-list runtime update: standard prechecks plus a
    # route-count verification add-on, postchecks with convergence ON but EOR
    # expiry tolerated (a runtime prefix-list update is not a restart).
    RUNTIME_UPDATE = "runtime_update"

    # Minimal-shape (accept the context for a uniform API, but ignore it):
    # bag012 perf-scaling, bounded-ECMP-sets (case9).
    PERF_SCALING_BOUNDED_ECMP = "perf_scaling_bounded_ecmp"
    SC9_BOUNDED_ECMP = "sc9_bounded_ecmp"


@dataclasses.dataclass(frozen=True)
class CpuCharacterizationConfig:
    """Per-test-case config for the bgpcpp CPU percentile postcheck.

    The measurement is collected by a START/STOP bracket in the stage; this
    config drives the reporting/gating postcheck (CPU_PERCENTILE_CHECK).
    Observe-only while ``gate_threshold_pct`` is None (always PASS, value in the
    results table); set it to gate on the raw ``gate_percentile``.
    """

    summary_jq_var: str = CPU_SUMMARY_JQ_VAR
    gate_percentile: float = 95.0
    gate_threshold_pct: t.Optional[float] = None


@dataclasses.dataclass(frozen=True)
class RssDeltaConfig:
    """Per-test-case config for the bgpcpp RSS delta postcheck.

    The measurement is collected by a START/STOP bracket in the stage; this
    config drives the reporting/gating postcheck (RSS_DELTA_CHECK). Observe-only
    while ``max_growth_pct`` is None (always PASS, value in the results table);
    set it to gate on steady-state RSS growth over the in-run baseline.
    """

    summary_jq_var: str = RSS_SUMMARY_JQ_VAR
    max_growth_pct: t.Optional[float] = None


@dataclasses.dataclass(frozen=True)
class ProfileContext:
    """Per-invocation, device-specific values threaded into a profile.

    These are NOT policy (they vary per device/run); standard profiles fix the
    policy and pass these through to the shared ``create_standard_*`` factories.
    Minimal-shape profiles ignore this. All profile builders accept it (an empty
    ``ProfileContext()`` is fine for profiles that don't use any field) so the
    ``get_profile_checks`` signature stays uniform.
    """

    # Required for standard-shape profiles (threaded into create_standard_*,
    # which take non-optional ``str``); minimal-shape profiles ignore them, so
    # the empty-string default is only ever seen by profiles that don't use it.
    peergroup_ibgp_v6: str = ""
    peergroup_ibgp_v4: str = ""
    precheck_thresholds: t.Optional[t.Any] = None
    postcheck_thresholds: t.Optional[t.Any] = None
    # Default matches the standard-shape playbook entry points (8.0), which are
    # the only profiles that thread this into create_standard_prechecks. NOT
    # create_standard_prechecks' own 4.0 default — drain/churn want the factory
    # 4.0 and get it by not passing cpu_baseline at all, so this default is only
    # ever read by the 8.0 consumers. Keeping it 8.0 means a direct
    # get_profile_checks(DAEMON_RESTART, ProfileContext()) matches the playbook.
    cpu_baseline: float = 8.0
    check_cpu_load_average: bool = True
    check_ibgp_pnh: bool = False
    expected_peer_identity: t.Optional[t.Dict[str, str]] = None
    parent_prefixes_to_ignore: t.Optional[t.List[str]] = None
    # Whether to exclude BGP-MON peers from the session checks, and which
    # chassis' BGP-MON prefix to exclude. The default keeps the ixia11 prefix;
    # a config driving the secondary chassis must set ``parent_network``, or
    # its BGP-MON sessions are counted instead of excluded and every
    # session-count check is off by the BGP-MON peer count. Held as one value
    # so a profile cannot thread the exclusion but forget the chassis.
    bgp_mon: BgpMonScope = DEFAULT_BGP_MON_SCOPE
    # Cold-start tolerates an expired EOR timer by default.
    fail_on_eor_expired: bool = False
    # Oscillation: expected established session count at precheck, and which
    # snapshot sub-checks to skip (sessions intentionally flap during the test).
    expected_established_sessions: int = 0
    snapshot_skip_flap: bool = False
    snapshot_skip_uptime: bool = False
    # CICD-EBB-10 restores an exact baseline before requiring the full session
    # snapshot. CICD-EBB-11 leaves this false because its setup and cleanup restart
    # generator sessions outside the measured storm window.
    full_session_snapshot: bool = False
    # IGP-instability: parameters for the appended BGP tcpdump check. message
    # types that must / must not appear in the capture, and an optional window
    # (seconds) the capture's last-mod time must fall within.
    tcpdump_expected_message_types: t.Optional[t.List[str]] = None
    tcpdump_unexpected_message_types: t.Optional[t.List[str]] = None
    tcpdump_expected_last_mod_time: t.Optional[int] = None
    # Soak profiles: whether the convergence postcheck runs and an optional
    # convergence threshold threaded only when set (so the factory keeps the
    # single source of truth for the default).
    check_bgp_convergence: bool = True
    convergence_threshold: t.Optional[int] = None
    # Expected baseline eBGP route count for readiness and runtime-update
    # route-count verification prechecks.
    route_count_expected: t.Optional[int] = None
    # EBB-16 requires the aggregate EOR milestone only with Update Group.
    enable_update_group: bool = True
    # Opt-in observe-only characterization postchecks (results land in the
    # POST-HEALTH CHECK RESULTS table). CPU needs the stage START/STOP collector;
    # RSS is self-soaking (postcheck only). None => not added.
    cpu_characterization: t.Optional[CpuCharacterizationConfig] = None
    rss_delta: t.Optional[RssDeltaConfig] = None


class ProfileChecks(t.NamedTuple):
    """Resolved checks for a profile, split by phase."""

    prechecks: t.List[PointInTimeHealthCheck]
    postchecks: t.List[PointInTimeHealthCheck]
    snapshot_checks: t.List[SnapshotHealthCheck]


def _daemon_restart(ctx: ProfileContext) -> ProfileChecks:
    """BGP/agent daemon restart: convergence ON, restart-aware postcheck, strict
    EOR (inherits create_standard_postchecks default fail_on_eor_expired=True),
    snapshot skips flap and uptime checks because sessions intentionally reset.
    """
    return ProfileChecks(
        prechecks=create_standard_prechecks(
            peergroup_ibgp_v6=ctx.peergroup_ibgp_v6,
            peergroup_ibgp_v4=ctx.peergroup_ibgp_v4,
            precheck_thresholds=ctx.precheck_thresholds,
            expected_established_sessions=(ctx.expected_established_sessions or 0),
            cpu_baseline=ctx.cpu_baseline,
            check_ibgp_pnh=ctx.check_ibgp_pnh,
            bgp_mon=ctx.bgp_mon,
        ),
        postchecks=create_standard_postchecks(
            postcheck_thresholds=ctx.postcheck_thresholds,
            convergence_hard_timeout_seconds=(
                _LIFECYCLE_CONVERGENCE_HARD_TIMEOUT_SECONDS
            ),
            expected_established_session_count=(
                ctx.expected_established_sessions or None
            ),
            expected_restarted_services=["Bgp"],
            restart_start_time_jq_var="daemon_restart_time",
            bgp_mon=ctx.bgp_mon,
        ),
        snapshot_checks=create_standard_snapshot_checks(
            skip_flap_check=True,
            skip_uptime_check=True,
            expected_peer_identity=ctx.expected_peer_identity,
            parent_prefixes_to_ignore=ctx.parent_prefixes_to_ignore,
            bgp_mon=ctx.bgp_mon,
        ),
    )


def _append_characterization_postchecks(
    postchecks: t.List[PointInTimeHealthCheck], ctx: ProfileContext
) -> t.List[PointInTimeHealthCheck]:
    """Append the opt-in observe-only characterization postchecks (RSS delta,
    CPU percentile) when configured on the context. Both land in the results
    table; observe-only unless their config carries a threshold.
    """
    if ctx.rss_delta is not None:
        postchecks.append(
            create_rss_delta_observe_check(
                summary_jq_var=ctx.rss_delta.summary_jq_var,
                max_growth_pct=ctx.rss_delta.max_growth_pct,
            )
        )
    if ctx.cpu_characterization is not None:
        postchecks.append(
            create_cpu_percentile_observe_check(
                summary_jq_var=ctx.cpu_characterization.summary_jq_var,
                gate_percentile=ctx.cpu_characterization.gate_percentile,
                gate_threshold_pct=ctx.cpu_characterization.gate_threshold_pct,
            )
        )
    return postchecks


def _cold_start(ctx: ProfileContext) -> ProfileChecks:
    """Full cold start: convergence ON, EOR tolerated (fail_on_eor_expired from
    the context, default False), full snapshot (flap + uptime checks ON).
    """
    return ProfileChecks(
        prechecks=create_standard_prechecks(
            peergroup_ibgp_v6=ctx.peergroup_ibgp_v6,
            peergroup_ibgp_v4=ctx.peergroup_ibgp_v4,
            precheck_thresholds=ctx.precheck_thresholds,
            cpu_baseline=ctx.cpu_baseline,
            check_ibgp_pnh=ctx.check_ibgp_pnh,
            bgp_mon=ctx.bgp_mon,
        ),
        postchecks=create_standard_postchecks(
            postcheck_thresholds=ctx.postcheck_thresholds,
            convergence_hard_timeout_seconds=(
                _LIFECYCLE_CONVERGENCE_HARD_TIMEOUT_SECONDS
            ),
            fail_on_eor_expired=ctx.fail_on_eor_expired,
            expected_established_session_count=(
                ctx.expected_established_sessions or None
            ),
            expected_restarted_services=["Bgp"],
            restart_start_time_jq_var="daemon_restart_time",
            bgp_mon=ctx.bgp_mon,
        ),
        snapshot_checks=create_standard_snapshot_checks(
            expected_peer_identity=ctx.expected_peer_identity,
            bgp_mon=ctx.bgp_mon,
        ),
    )


def _oscillation(ctx: ProfileContext) -> ProfileChecks:
    """BGP route/session oscillation & multipath churn: standard prechecks,
    postchecks with convergence OFF (routes/sessions intentionally churn), and a
    snapshot whose flap/uptime skips are set per sub-shape via the context.
    """
    return ProfileChecks(
        prechecks=create_standard_prechecks(
            peergroup_ibgp_v6=ctx.peergroup_ibgp_v6,
            peergroup_ibgp_v4=ctx.peergroup_ibgp_v4,
            precheck_thresholds=ctx.precheck_thresholds,
            expected_established_sessions=ctx.expected_established_sessions,
            cpu_baseline=ctx.cpu_baseline,
            check_ibgp_pnh=ctx.check_ibgp_pnh,
            bgp_mon=ctx.bgp_mon,
        ),
        postchecks=create_standard_postchecks(
            postcheck_thresholds=ctx.postcheck_thresholds,
            check_bgp_convergence=False,
            bgp_mon=ctx.bgp_mon,
        ),
        snapshot_checks=create_standard_snapshot_checks(
            skip_flap_check=ctx.snapshot_skip_flap,
            skip_uptime_check=ctx.snapshot_skip_uptime,
            expected_peer_identity=ctx.expected_peer_identity,
            parent_prefixes_to_ignore=ctx.parent_prefixes_to_ignore,
            bgp_mon=ctx.bgp_mon,
        ),
    )


def _drain_undrain(ctx: ProfileContext) -> ProfileChecks:
    """FA/plane drain-undrain: standard prechecks with the iBGP-PNH check OFF
    (drain tests don't assert PNH metric), postchecks with convergence OFF, and
    a snapshot that skips only the flap check (uptime is still validated).
    """
    return ProfileChecks(
        prechecks=create_standard_prechecks(
            peergroup_ibgp_v6=ctx.peergroup_ibgp_v6,
            peergroup_ibgp_v4=ctx.peergroup_ibgp_v4,
            expected_established_sessions=ctx.expected_established_sessions,
            check_ibgp_pnh=False,
            bgp_mon=ctx.bgp_mon,
        ),
        postchecks=create_standard_postchecks(
            check_bgp_convergence=False,
            bgp_mon=ctx.bgp_mon,
        ),
        snapshot_checks=create_standard_snapshot_checks(
            skip_flap_check=True,
            bgp_mon=ctx.bgp_mon,
        ),
    )


def _churn_storm(ctx: ProfileContext) -> ProfileChecks:
    """BGP churn/storm checks with custom in-window stability verdicts.

    The grouped IXIA setup and cleanup intentionally restart generator sessions
    outside the measured route-storm window, so CICD-EBB-11 keeps the default
    core-dumps-only snapshot. CICD-EBB-10 opts into the full session snapshot after
    restoring its exact baseline.
    """
    return ProfileChecks(
        prechecks=create_standard_prechecks(
            peergroup_ibgp_v6=ctx.peergroup_ibgp_v6,
            peergroup_ibgp_v4=ctx.peergroup_ibgp_v4,
            expected_established_sessions=ctx.expected_established_sessions,
            check_cpu_load_average=ctx.check_cpu_load_average,
            check_ibgp_pnh=ctx.check_ibgp_pnh,
            bgp_mon=ctx.bgp_mon,
        ),
        postchecks=create_standard_postchecks(
            check_bgp_convergence=False,
            expected_established_session_count=ctx.expected_established_sessions,
            bgp_mon=ctx.bgp_mon,
        ),
        snapshot_checks=(
            create_standard_snapshot_checks(
                expected_peer_identity=ctx.expected_peer_identity,
                parent_prefixes_to_ignore=ctx.parent_prefixes_to_ignore,
                bgp_mon=ctx.bgp_mon,
            )
            if ctx.full_session_snapshot
            else [create_core_dumps_snapshot_check()]
        ),
    )


def _igp_instability(ctx: ProfileContext) -> ProfileChecks:
    """IGP instability (PNH-metric oscillation / unresolvable PNHs): standard
    prechecks, postchecks with convergence OFF, an optional BGP tcpdump check,
    and a standard snapshot. The PNH playbooks use direct BGP++ counter
    validation plus session snapshots instead of requesting tcpdump here.
    """
    postchecks = create_standard_postchecks(
        postcheck_thresholds=ctx.postcheck_thresholds,
        check_bgp_convergence=False,
        bgp_mon=ctx.bgp_mon,
    )
    if (
        ctx.tcpdump_expected_message_types is not None
        or ctx.tcpdump_unexpected_message_types is not None
    ):
        postchecks.append(
            create_bgp_tcpdump_check(
                expected_message_types=ctx.tcpdump_expected_message_types,
                unexpected_message_types=ctx.tcpdump_unexpected_message_types,
                expected_last_mod_time=ctx.tcpdump_expected_last_mod_time,
            )
        )
    return ProfileChecks(
        prechecks=create_standard_prechecks(
            peergroup_ibgp_v6=ctx.peergroup_ibgp_v6,
            peergroup_ibgp_v4=ctx.peergroup_ibgp_v4,
            precheck_thresholds=ctx.precheck_thresholds,
            expected_established_sessions=ctx.expected_established_sessions,
            cpu_baseline=ctx.cpu_baseline,
            check_ibgp_pnh=ctx.check_ibgp_pnh,
            bgp_mon=ctx.bgp_mon,
        ),
        postchecks=postchecks,
        snapshot_checks=create_standard_snapshot_checks(
            expected_peer_identity=ctx.expected_peer_identity,
            bgp_mon=ctx.bgp_mon,
        ),
    )


def _soak_no_precheck(ctx: ProfileContext) -> ProfileChecks:
    """No-precheck stress (longevity soak): NO
    prechecks, standard postchecks with the convergence check toggled by the
    context (and an optional threaded threshold), and a snapshot that skips flap
    + uptime since sessions intentionally churn during the long workload.
    """
    postcheck_kwargs: t.Dict[str, t.Any] = {
        "postcheck_thresholds": ctx.postcheck_thresholds,
        "check_bgp_convergence": ctx.check_bgp_convergence,
        "bgp_mon": ctx.bgp_mon,
    }
    if ctx.convergence_threshold is not None:
        postcheck_kwargs["convergence_threshold"] = ctx.convergence_threshold

    return ProfileChecks(
        prechecks=[],
        postchecks=create_standard_postchecks(**postcheck_kwargs),
        snapshot_checks=create_standard_snapshot_checks(
            skip_flap_check=True,
            skip_uptime_check=True,
            bgp_mon=ctx.bgp_mon,
        ),
    )


def _soak_readiness_gated(ctx: ProfileContext) -> ProfileChecks:
    """CICD-EBB-16 readiness gate before route oscillation.

    Require the exact non-monitor session count, a continuously observable
    mode-specific initialization milestone, the expected per-peer-group
    accepted-route count, and consistent BGP RIB, FibAgent, and hardware views.
    Update Group uses ALL_EOR_RECEIVED. Non-Update Group uses INITIALIZED
    because it is the guaranteed terminal startup milestone for that mode.
    """
    if ctx.expected_established_sessions <= 0:
        raise ValueError("SOAK_READINESS_GATED requires expected_established_sessions")
    if ctx.route_count_expected is None:
        raise ValueError("SOAK_READINESS_GATED requires route_count_expected")

    convergence_threshold = ctx.convergence_threshold or 600
    if ctx.enable_update_group:
        readiness_end_event = "4"  # ALL_EOR_RECEIVED
        readiness_check_id = "startup_all_eor_received"
    else:
        readiness_end_event = "9"  # INITIALIZED
        readiness_check_id = "startup_bgp_initialized"
    return ProfileChecks(
        prechecks=[
            create_bgp_session_establish_check(
                expected_established_sessions_static=(
                    ctx.expected_established_sessions
                ),
                parent_prefixes_to_ignore=ctx.bgp_mon.ignore_prefixes(),
                check_id="startup_bgp_session_verification",
                **get_retry_kwargs(hc_types.CheckName.BGP_SESSION_ESTABLISH_CHECK),
            ),
            create_bgp_convergence_check(
                convergence_threshold=convergence_threshold,
                hard_timeout_seconds=convergence_threshold,
                stability_window_seconds=_SOAK_READINESS_STABILITY_WINDOW_SECONDS,
                fail_on_eor_expired=False,
                validate_sequence=False,
                extra_json_params={
                    "start_event": "3",  # PEER_INFO_LOADED
                    "end_event": readiness_end_event,
                },
                check_id=readiness_check_id,
            ),
            create_bgp_route_count_verification_check(
                json_params={
                    "exact_peer_group_names": [
                        *RUNTIME_UPDATE_EXACT_PEER_GROUP_NAMES,
                    ],
                    "direction": "received",
                    "expected_count": ctx.route_count_expected,
                    "policy_type": "post_policy",
                },
                check_id="startup_bgp_route_count_verification",
            ),
            create_bgp_rib_fib_consistency_check(
                check_id="rib_fib_consistency_precheck",
                **get_retry_kwargs(hc_types.CheckName.BGP_RIB_FIB_CONSISTENCY_CHECK),
            ),
        ],
        postchecks=create_standard_postchecks(
            postcheck_thresholds=ctx.postcheck_thresholds,
            convergence_threshold=convergence_threshold,
            fail_on_eor_expired=False,
            expected_established_session_count=ctx.expected_established_sessions,
            bgp_mon=ctx.bgp_mon,
        ),
        snapshot_checks=create_standard_snapshot_checks(
            skip_flap_check=True,
            skip_uptime_check=True,
            bgp_mon=ctx.bgp_mon,
        ),
    )


def _runtime_update(ctx: ProfileContext) -> ProfileChecks:
    """Route-registry prefix-list runtime update: standard prechecks plus a
    route-count verification add-on (eBGP received post-policy routes vs the
    expected baseline), postchecks with convergence ON but EOR expiry tolerated
    (a runtime prefix-list update is not a restart), and a standard snapshot.
    """
    return ProfileChecks(
        prechecks=create_standard_prechecks(
            peergroup_ibgp_v6=ctx.peergroup_ibgp_v6,
            peergroup_ibgp_v4=ctx.peergroup_ibgp_v4,
            precheck_thresholds=ctx.precheck_thresholds,
            cpu_baseline=ctx.cpu_baseline,
            expected_established_sessions=(ctx.expected_established_sessions or None),
            check_ibgp_pnh=ctx.check_ibgp_pnh,
            bgp_mon=ctx.bgp_mon,
        )
        + [
            create_bgp_route_count_verification_check(
                json_params={
                    "exact_peer_group_names": [
                        *RUNTIME_UPDATE_EXACT_PEER_GROUP_NAMES,
                    ],
                    "direction": "received",
                    "expected_count": ctx.route_count_expected,
                    "policy_type": "post_policy",
                },
                check_id="startup_bgp_session_verification",
            ),
        ],
        postchecks=create_standard_postchecks(
            postcheck_thresholds=ctx.postcheck_thresholds,
            fail_on_eor_expired=False,
            bgp_mon=ctx.bgp_mon,
        ),
        snapshot_checks=create_standard_snapshot_checks(
            bgp_mon=ctx.bgp_mon,
        ),
    )


def _perf_scaling_bounded_ecmp(ctx: ProfileContext) -> ProfileChecks:
    """Profile for the bag012 bounded-ECMP-sets (case9) playbook.

    Minimal shape (ignores ``ctx``). Behavior-preserving vs. the prior inline
    list, with the one intended improvement: the post-test session / RIB-FIB /
    convergence checks now carry the standardized retry from the SSOT
    (previously single-shot), so transient post-disruption settling no longer
    trips a false failure.
    """
    return ProfileChecks(
        prechecks=[],
        postchecks=[
            create_bgp_session_establish_check(
                **get_retry_kwargs(hc_types.CheckName.BGP_SESSION_ESTABLISH_CHECK),
            ),
            create_bgp_rib_fib_consistency_check(
                **get_retry_kwargs(hc_types.CheckName.BGP_RIB_FIB_CONSISTENCY_CHECK),
            ),
            create_bgp_convergence_check(
                convergence_threshold=600,
                # Functional knob (per check, phase). Kept True to preserve the
                # current bag012 behavior (the prior call omitted it, inheriting
                # the server-side default True). Flip to False here to align with
                # the fleet standard (BGP_STANDARD_POSTCHECKS) if an expired EOR
                # timer under bounded-ECMP stress is deemed acceptable.
                fail_on_eor_expired=True,
                check_id="postcheck_bgp_convergence_time",
                **get_retry_kwargs(hc_types.CheckName.BGP_CONVERGENCE_CHECK),
            ),
        ],
        snapshot_checks=[
            create_core_dumps_snapshot_check(),
            create_bgp_session_snapshot_check(
                skip_flap_check=True, skip_uptime_check=True
            ),
        ],
    )


def _sc9_bounded_ecmp(ctx: ProfileContext) -> ProfileChecks:
    """Profile for the SC9 bounded-ECMP-sets characteristic on bag013.

    SC9 asserts that 5,000 routes learned from 128 eBGP peers install as ONE
    ECMP set per AFI, that a simultaneous drain does not push the programmed
    set count past what the hardware can hold, and that the structure collapses
    back afterwards.

    Only the claims that can be recorded as Requirement Coverage live here.
    ``_VALIDATION_PHASES`` admits precheck / workload / postcheck / snapshot
    only, so a periodic-task verdict can never be counted as coverage -- the
    nexthop-group poll therefore carries the transient series and the
    instrument-liveness guards, while the coverage-bearing assertions are the
    postchecks below.

    Deliberately additive: ``PERF_SCALING_BOUNDED_ECMP`` is left byte-identical
    so the retained bounded-ECMP TestConfig is unaffected.
    """
    return ProfileChecks(
        prechecks=[
            # Hardware headroom BEFORE the drain, recorded so a postcheck
            # breach can be read against where the device started.
            #
            # Nothing in the framework compares the two readings -- each
            # hardware-capacity check is independent and stateless -- so this is
            # documentation of the starting point, not half of a delta. An
            # earlier revision of this profile claimed it "establishes the floor
            # the post reading is compared against"; that mechanism does not
            # exist. check_watermarks=False keeps the within-reading delta check
            # off, because bag013 carries a large stale FEC peak that no SC9 run
            # can reset or influence.
            #
            # The ECMP high-watermark bound is applied HERE TOO, at the same
            # value as the postcheck. That watermark is monotonic within a boot
            # and no SC9 step resets it, so a box arriving with a peak left by a
            # previous full-scale run would fail the postcheck and read as
            # "SC9's drain exhausted the ECMP table" when SC9 never touched it.
            # Asserting it before the run attributes that state to the testbed,
            # where it belongs. The delta step in the playbook covers the same
            # counter immune to staleness, by comparing against SC9's own
            # capture rather than against an absolute.
            create_hardware_capacity_check(
                check_id="sc9_precheck_hw_capacity_baseline",
                check_watermarks=False,
                ecmp_high_watermark_threshold=_SC9_MAX_ECMP_HIGH_WATERMARK,
            ),
        ],
        postchecks=[
            # Scoped to the eBGP population -- see IBGP_MIMIC_PARENTS. The
            # drain withdraws routes without tearing down sessions, so an eBGP
            # peer that is not Established at postcheck IS a real finding.
            create_bgp_session_establish_check(
                check_id="sc9_postcheck_ebgp_sessions_established",
                parent_prefixes_to_ignore=IBGP_MIMIC_PARENTS,
                # The COUNT, not just the scope. Without it this passes on any
                # number of in-scope sessions INCLUDING ZERO -- so the very bug
                # the masks above fix (a mask that accidentally excludes the
                # population under test) would sail through this check rather
                # than be caught by it. 128 eBGP peers per AFI, both AFIs.
                expected_established_sessions=SC9_EBGP_SESSION_COUNT,
                **get_retry_kwargs(hc_types.CheckName.BGP_SESSION_ESTABLISH_CHECK),
            ),
            create_bgp_rib_fib_consistency_check(
                **get_retry_kwargs(hc_types.CheckName.BGP_RIB_FIB_CONSISTENCY_CHECK),
            ),
            create_bgp_convergence_check(
                convergence_threshold=ctx.convergence_threshold or 600,
                # Unlike PERF_SCALING_BOUNDED_ECMP this does NOT fail on an
                # expired EOR timer. SC9 drains peers on purpose, so peers that
                # never re-send EOR are the stimulus, not a defect; failing on
                # it reports the workload as a fault. This matches the fleet
                # standard (BGP_STANDARD_POSTCHECKS).
                fail_on_eor_expired=False,
                check_id="sc9_postcheck_convergence",
                **get_retry_kwargs(hc_types.CheckName.BGP_CONVERGENCE_CHECK),
            ),
            # RECOVERY, at RIB level: every prefix discovered at baseline must
            # be back at its baseline multipath width. peers_stopped_delta=0
            # because the drain is a route withdrawal followed by a restore --
            # no peer is left administratively down at postcheck time.
            create_next_hop_count_check(
                check_id="sc9_postcheck_multipath_width_restored",
                use_discovered_prefixes=True,
                use_discovered_width=True,
                peers_stopped_delta=0,
            ),
            # Hardware headroom AFTER the drain.
            #
            # This deliberately does NOT use watermark_delta_threshold, which an
            # earlier revision set to the topology's structural max. That knob
            # does not mean what the name suggests: validate_hardware_capacity
            # computes abs(high_watermark - used) WITHIN A SINGLE READING, so it
            # never compares the precheck to the postcheck, and the same knob
            # gates FEC as well as ECMP. The first bag013 run failed on exactly
            # that -- "FEC high watermark delta (19398) exceeds threshold (258)"
            # -- where 19398 is a stale FEC peak (hwm 24271 vs 4873 used) that
            # was identical at precheck and postcheck and has nothing to do with
            # SC9. check_watermarks=False turns the delta checks off.
            #
            # `ecmp_high_watermark_threshold` IS load-bearing and stays: unlike
            # every neighbouring threshold, HardwareCapacityThresholds.from_dict
            # reads it with a bare params.get() and applies NO default, so
            # passing it is the only thing that enables the bound at all. Its
            # value coinciding with ARISTA_DEFAULT_ECMP_THRESHOLD is a red
            # herring -- that default belongs to `ecmp_threshold`, a different
            # counter. It is evaluated outside the check_watermarks block.
            #
            # `max_ecmp_level2` was dropped: it was set to 500, which is exactly
            # ARISTA_DEFAULT_MAX_ECMP_LEVEL2 and IS applied by from_dict on
            # None, so it was a no-op dressed as a deliberate SC9 bound -- and
            # sitting beside a genuinely load-bearing parameter it implied both
            # were chosen. The framework default still applies.
            create_hardware_capacity_check(
                check_id="sc9_postcheck_hw_capacity",
                check_watermarks=False,
                ecmp_high_watermark_threshold=_SC9_MAX_ECMP_HIGH_WATERMARK,
            ),
        ],
        snapshot_checks=[
            create_core_dumps_snapshot_check(),
            # The drain withdraws routes; it does not tear down sessions, so a
            # flap here is a real finding rather than expected churn. Unlike
            # PERF_SCALING_BOUNDED_ECMP the flap and uptime checks stay ON.
            # Scoped the SAME way as the postcheck above. Leaving it unscoped
            # would let the iBGP mimic population -- which this profile argues
            # at length is outside SC9's subject -- fail the run through the
            # back door on a flap or a drop the test does not assert on.
            create_bgp_session_snapshot_check(
                parent_prefixes_to_ignore=IBGP_MIMIC_PARENTS,
            ),
        ],
    )


# Explicit profile -> builder mapping (no decorator/registration side effects, per
# the lazy-import guidance). Builders are referenced, not called, at import time.
_PROFILE_BUILDERS: t.Dict[CheckProfile, t.Callable[[ProfileContext], ProfileChecks]] = {
    CheckProfile.DAEMON_RESTART: _daemon_restart,
    CheckProfile.COLD_START: _cold_start,
    CheckProfile.OSCILLATION: _oscillation,
    CheckProfile.DRAIN_UNDRAIN: _drain_undrain,
    CheckProfile.CHURN_STORM: _churn_storm,
    CheckProfile.IGP_INSTABILITY: _igp_instability,
    CheckProfile.SOAK_NO_PRECHECK: _soak_no_precheck,
    CheckProfile.SOAK_READINESS_GATED: _soak_readiness_gated,
    CheckProfile.RUNTIME_UPDATE: _runtime_update,
    CheckProfile.PERF_SCALING_BOUNDED_ECMP: _perf_scaling_bounded_ecmp,
    CheckProfile.SC9_BOUNDED_ECMP: _sc9_bounded_ecmp,
}


def get_profile_checks(profile: CheckProfile, ctx: ProfileContext) -> ProfileChecks:
    """Resolve a ``CheckProfile`` to its (prechecks, postchecks, snapshot_checks).

    ``ctx`` carries per-invocation runtime values; it is required for every
    profile (pass an empty ``ProfileContext()`` for minimal-shape profiles that
    ignore it) so the entry point is uniform. Each call constructs fresh check
    objects (thrift structs are mutable, so callers must not share instances
    across playbooks).
    """
    builder = _PROFILE_BUILDERS.get(profile)
    if builder is None:
        raise ValueError(f"Unknown CheckProfile: {profile}")
    checks = builder(ctx)
    # Characterization reporting is profile-independent. Any playbook that
    # brackets a span (see create_characterization_bracket_stages) sets these
    # configs on the context, and the matching postcheck is appended here rather
    # than in each of the 20+ profile builders. Without it the bracket would
    # collect a measurement and stash it into a jq var that nothing reads.
    # No-op when neither config is set, which is every playbook that has not
    # opted in.
    _append_characterization_postchecks(checks.postchecks, ctx)
    return checks
