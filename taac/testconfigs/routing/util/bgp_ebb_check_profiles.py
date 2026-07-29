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

from taac.health_checks.healthcheck_definitions import (
    create_bgp_convergence_check,
    create_bgp_rib_fib_consistency_check,
    create_bgp_route_count_verification_check,
    create_bgp_session_establish_check,
    create_bgp_session_snapshot_check,
    create_bgp_tcpdump_check,
    create_core_dumps_snapshot_check,
)
from taac.health_checks.retry_policy import get_retry_kwargs
from taac.testconfigs.routing.util.bgp_ebb_health_checks import (
    create_standard_postchecks,
    create_standard_prechecks,
    create_standard_snapshot_checks,
)
from taac.health_check.health_check import types as hc_types
from taac.test_as_a_config.types import PointInTimeHealthCheck, SnapshotHealthCheck

_LIFECYCLE_CONVERGENCE_HARD_TIMEOUT_SECONDS = 1200


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
    # CICD-11 route storm: convergence OFF, expected established-session count
    # enforced, and a context-selected snapshot shape. The custom steps own
    # exact in-window route, attribute, and session-stability verdicts.
    CHURN_STORM = "churn_storm"
    # IGP instability (PNH-metric oscillation / unresolvable PNHs): convergence
    # OFF, standard snapshot, plus a BGP tcpdump check whose message-types and
    # last-mod-time window come from the context.
    IGP_INSTABILITY = "igp_instability"
    # No-precheck stress (nexthop-group-count threshold / longevity soak): NO
    # prechecks, standard postchecks (convergence toggled by context), and a
    # snapshot that skips flap + uptime (sessions churn during the workload).
    SOAK_NO_PRECHECK = "soak_no_precheck"
    # Route-registry prefix-list runtime update: standard prechecks plus a
    # route-count verification add-on, postchecks with convergence ON but EOR
    # expiry tolerated (a runtime prefix-list update is not a restart).
    RUNTIME_UPDATE = "runtime_update"

    # Minimal-shape (accept the context for a uniform API, but ignore it):
    # bag012 perf-scaling, bounded-ECMP-sets (case9).
    PERF_SCALING_BOUNDED_ECMP = "perf_scaling_bounded_ecmp"


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
    check_ibgp_pnh: bool = False
    expected_peer_identity: t.Optional[t.Dict[str, str]] = None
    parent_prefixes_to_ignore: t.Optional[t.List[str]] = None
    exclude_bgp_mon: bool = True
    # Cold-start tolerates an expired EOR timer by default.
    fail_on_eor_expired: bool = False
    # Oscillation: expected established session count at precheck, and which
    # snapshot sub-checks to skip (sessions intentionally flap during the test).
    expected_established_sessions: int = 0
    snapshot_skip_flap: bool = False
    snapshot_skip_uptime: bool = False
    # CICD-10 restores an exact baseline before requiring the full session
    # snapshot. CICD-11 leaves this false because its setup and cleanup restart
    # generator sessions outside the measured storm window.
    full_session_snapshot: bool = False
    # IGP-instability: parameters for the appended BGP tcpdump check. message
    # types that must / must not appear in the capture, and an optional window
    # (seconds) the capture's last-mod time must fall within.
    tcpdump_expected_message_types: t.Optional[t.List[str]] = None
    tcpdump_unexpected_message_types: t.Optional[t.List[str]] = None
    tcpdump_expected_last_mod_time: t.Optional[int] = None
    # No-precheck soak: whether the convergence postcheck runs (the only policy
    # difference between the nexthop-threshold and longevity shapes), and an
    # optional convergence threshold threaded only when set (so the factory keeps
    # the single source of truth for the default).
    check_bgp_convergence: bool = True
    convergence_threshold: t.Optional[int] = None
    # Runtime-update: expected baseline eBGP route count for the route-count
    # verification precheck add-on (the only per-call variable in its params).
    route_count_expected: t.Optional[int] = None


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
            exclude_bgp_mon=ctx.exclude_bgp_mon,
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
            exclude_bgp_mon=ctx.exclude_bgp_mon,
        ),
        snapshot_checks=create_standard_snapshot_checks(
            skip_flap_check=True,
            skip_uptime_check=True,
            expected_peer_identity=ctx.expected_peer_identity,
            parent_prefixes_to_ignore=ctx.parent_prefixes_to_ignore,
            exclude_bgp_mon=ctx.exclude_bgp_mon,
        ),
    )


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
            exclude_bgp_mon=ctx.exclude_bgp_mon,
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
            exclude_bgp_mon=ctx.exclude_bgp_mon,
        ),
        snapshot_checks=create_standard_snapshot_checks(
            expected_peer_identity=ctx.expected_peer_identity,
            exclude_bgp_mon=ctx.exclude_bgp_mon,
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
            exclude_bgp_mon=ctx.exclude_bgp_mon,
        ),
        postchecks=create_standard_postchecks(
            postcheck_thresholds=ctx.postcheck_thresholds,
            check_bgp_convergence=False,
            exclude_bgp_mon=ctx.exclude_bgp_mon,
        ),
        snapshot_checks=create_standard_snapshot_checks(
            skip_flap_check=ctx.snapshot_skip_flap,
            skip_uptime_check=ctx.snapshot_skip_uptime,
            expected_peer_identity=ctx.expected_peer_identity,
            parent_prefixes_to_ignore=ctx.parent_prefixes_to_ignore,
            exclude_bgp_mon=ctx.exclude_bgp_mon,
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
            exclude_bgp_mon=ctx.exclude_bgp_mon,
        ),
        postchecks=create_standard_postchecks(
            check_bgp_convergence=False,
            exclude_bgp_mon=ctx.exclude_bgp_mon,
        ),
        snapshot_checks=create_standard_snapshot_checks(
            skip_flap_check=True,
            exclude_bgp_mon=ctx.exclude_bgp_mon,
        ),
    )


def _churn_storm(ctx: ProfileContext) -> ProfileChecks:
    """BGP churn/storm checks with custom in-window stability verdicts.

    The grouped IXIA setup and cleanup intentionally restart generator sessions
    outside the measured route-storm window, so CICD-11 keeps the default
    core-dumps-only snapshot. CICD-10 opts into the full session snapshot after
    restoring its exact baseline.
    """
    return ProfileChecks(
        prechecks=create_standard_prechecks(
            peergroup_ibgp_v6=ctx.peergroup_ibgp_v6,
            peergroup_ibgp_v4=ctx.peergroup_ibgp_v4,
            expected_established_sessions=ctx.expected_established_sessions,
            check_ibgp_pnh=ctx.check_ibgp_pnh,
            exclude_bgp_mon=ctx.exclude_bgp_mon,
        ),
        postchecks=create_standard_postchecks(
            check_bgp_convergence=False,
            expected_established_session_count=ctx.expected_established_sessions,
            exclude_bgp_mon=ctx.exclude_bgp_mon,
        ),
        snapshot_checks=(
            create_standard_snapshot_checks(
                expected_peer_identity=ctx.expected_peer_identity,
                parent_prefixes_to_ignore=ctx.parent_prefixes_to_ignore,
                exclude_bgp_mon=ctx.exclude_bgp_mon,
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
        exclude_bgp_mon=ctx.exclude_bgp_mon,
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
            exclude_bgp_mon=ctx.exclude_bgp_mon,
        ),
        postchecks=postchecks,
        snapshot_checks=create_standard_snapshot_checks(
            expected_peer_identity=ctx.expected_peer_identity,
            exclude_bgp_mon=ctx.exclude_bgp_mon,
        ),
    )


def _soak_no_precheck(ctx: ProfileContext) -> ProfileChecks:
    """No-precheck stress (nexthop-group-count threshold / longevity soak): NO
    prechecks, standard postchecks with the convergence check toggled by the
    context (and an optional threaded threshold), and a snapshot that skips flap
    + uptime since sessions intentionally churn during the long workload.
    """
    postcheck_kwargs: t.Dict[str, t.Any] = {
        "postcheck_thresholds": ctx.postcheck_thresholds,
        "check_bgp_convergence": ctx.check_bgp_convergence,
        "exclude_bgp_mon": ctx.exclude_bgp_mon,
    }
    if ctx.convergence_threshold is not None:
        postcheck_kwargs["convergence_threshold"] = ctx.convergence_threshold

    return ProfileChecks(
        prechecks=[],
        postchecks=create_standard_postchecks(**postcheck_kwargs),
        snapshot_checks=create_standard_snapshot_checks(
            skip_flap_check=True,
            skip_uptime_check=True,
            exclude_bgp_mon=ctx.exclude_bgp_mon,
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
            expected_established_sessions=ctx.expected_established_sessions,
            check_ibgp_pnh=ctx.check_ibgp_pnh,
            exclude_bgp_mon=ctx.exclude_bgp_mon,
        )
        + [
            create_bgp_route_count_verification_check(
                json_params={
                    "descriptions_to_ignore": ["IBGP"],
                    "descriptions_to_check": ["EBGP"],
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
            exclude_bgp_mon=ctx.exclude_bgp_mon,
        ),
        snapshot_checks=create_standard_snapshot_checks(
            exclude_bgp_mon=ctx.exclude_bgp_mon,
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
    CheckProfile.RUNTIME_UPDATE: _runtime_update,
    CheckProfile.PERF_SCALING_BOUNDED_ECMP: _perf_scaling_bounded_ecmp,
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
    return builder(ctx)
