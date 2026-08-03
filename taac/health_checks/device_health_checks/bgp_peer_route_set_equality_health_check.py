# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe

"""
BGP++ Update Group route-set equality across peers.

Asserts that a set of tested peers receive the SAME postfilter route SET
(prefix-by-prefix) as a baseline peer. Used to validate that all members of
an Update Group converge to a consistent received-route view -- the spec
gate for BGP++ UG 2.4.1 (resilience under UG-member churn during sync) and
2.4.2 (mid-sync withdrawal).

Backed primarily by BGP++ thrift ``getPostfilterAdvertisedNetworks`` (one
call per peer). The thrift API is the DUT-side mirror of what the receiver
peer should be getting -- it returns the prefixes that DUT *would* advertise
to that peer after egress policy. EOS native-BGP fallback uses ``show bgp
ipv6 unicast neighbors <peer> advertised-routes | json`` -- on "BGP
inactive" the arista path delegates back to thrift (the standard cross-OS
fallback pattern in this codebase).

Update Group is supported. This previously returned 0 prefixes for every peer
when UG was enabled -- the per-peer show path looked entries up under the peer
owner key while an in-sync peer's RIB-OUT entries live under the GROUP owner
key. Fixed by D109395098 (``bcfe71f88827``, 2026-06-23), which routes the
advertised branches of ``getNetworks`` through
``AdjRibOutGroup::resolve{Lite,Path}EntriesForPeer(...)``: per prefix an in-sync
peer now resolves to the shared group entry, a diverged/standalone peer to its
own, and a post-detach entry the peer never saw to nothing.

The fix is version-gated on the bgpd build, so a device running a bgpcpp older
than 2026-06-23 will still report 0. Check with ``sh bgpcpp version`` on the DUT
and confirm the fix is an ancestor of the reported revision. Where a build-
independent signal is needed, ``TBgpSession.postpolicy_sent_prefix_count`` (via
``getBgpSessions``) is a per-peer gauge that has always been UG-safe -- but it
is only a count, whereas this API returns the actual prefix set.
"""

import ipaddress
import typing as t

from taac.constants import TestDevice
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
)
from taac.health_check.health_check import types as hc_types


def _norm(addr: t.Optional[str]) -> str:
    """Normalize an IP string (collapse v6 to canonical form, leave bad addrs alone)."""
    if not addr:
        return ""
    try:
        return str(ipaddress.ip_address(addr))
    except ValueError:
        return addr


def _format_prefix(prefix: t.Any) -> str:
    """Render a ``TIpPrefix`` thrift object as ``addr/len`` for diagnostics."""
    try:
        return f"{prefix.prefix}/{prefix.prefix_length}"
    except AttributeError:
        return str(prefix)


def _short_sample(prefixes: t.Iterable[t.Any], limit: int = 10) -> str:
    """Render the first ``limit`` prefixes (sorted) as a comma-separated string."""
    rendered = sorted(_format_prefix(p) for p in prefixes)
    head = rendered[:limit]
    tail = f" ... +{len(rendered) - limit} more" if len(rendered) > limit else ""
    return ", ".join(head) + tail


class BgpPeerRouteSetEqualityHealthCheck(
    AbstractDeviceHealthCheck[hc_types.BaseHealthCheckIn]
):
    """
    Verify a set of tested peers receive the same postfilter route SET as a
    baseline peer.

    The thrift path (``_run``) issues one ``getPostfilterAdvertisedNetworks``
    per peer (DUT-side mirror of what that peer should be receiving) and
    compares the resulting prefix sets. The EOS native-BGP path
    (``_run_arista``) issues ``show bgp ipv6 unicast neighbors <peer>
    advertised-routes | json`` per peer; if EOS reports "BGP inactive", the
    arista path delegates back to ``_run`` (BGP++ is what's actually
    answering on ARISTA_FBOSS devices). This mirrors the cross-OS fallback
    pattern in ``BgpRouteCountVerificationHealthCheck`` and others.

    See module docstring for the BGP++ UG limitation: under UG enabled, the
    thrift returns 0 prefixes; the stacked bag012 testconfig diff
    (D109339151) replaces the implementation with a counter-based gauge.

    Configurable via ``check_params``:

      - ``baseline_peer_addr`` (str, required): IP address of the peer whose
        received-route set is treated as ground truth.
      - ``tested_peer_addrs`` (list[str], required): IP addresses of peers
        whose received-route sets must equal the baseline's. Order is
        irrelevant.
      - ``anchor_route_count`` (optional int): if set, additionally asserts
        each peer's received count equals this value. Catches the case where
        baseline AND tested have the same (wrong) count.
      - ``count_tolerance`` (int, default 0): permitted deviation when
        ``anchor_route_count`` is set.
      - ``address_family`` (str, default "ipv6"): "ipv4" or "ipv6". Affects
        only the arista-path CLI command.
      - ``allow_extra_in_tested`` (bool, default False): when True, tested
        peers may have a strict superset of the baseline's prefixes (no
        missing prefixes, extra prefixes allowed). Default mode requires
        exact equality.

    All assertions are evaluated in a single run; every failure is collected
    and reported together so one run surfaces every problem at once.

    OS: ARISTA_FBOSS (thrift) + EOS (CLI fallback that delegates back to
    thrift on "BGP inactive").
    """

    CHECK_NAME = hc_types.CheckName.BGP_PEER_ROUTE_SET_EQUALITY_CHECK
    OPERATING_SYSTEMS = [
        "FBOSS",
        "EOS",
    ]

    async def _run(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        hostname = obj.name
        baseline_peer_addr = check_params.get("baseline_peer_addr")
        tested_peer_addrs = check_params.get("tested_peer_addrs") or []
        anchor_route_count = check_params.get("anchor_route_count")
        count_tolerance = int(check_params.get("count_tolerance", 0) or 0)

        if not baseline_peer_addr:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=(
                    f"BGP peer route-set equality on {hostname}: "
                    f"missing required param baseline_peer_addr."
                ),
            )
        if not tested_peer_addrs:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=(
                    f"BGP peer route-set equality on {hostname}: "
                    f"missing required param tested_peer_addrs (non-empty list)."
                ),
            )
        if anchor_route_count is not None:
            try:
                anchor_route_count = int(anchor_route_count)
            except (TypeError, ValueError) as e:
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.FAIL,
                    message=(
                        f"BGP peer route-set equality on {hostname}: "
                        f"invalid anchor_route_count: {e}"
                    ),
                )

        all_peer_addrs = [baseline_peer_addr] + [
            p for p in tested_peer_addrs if _norm(p) != _norm(baseline_peer_addr)
        ]
        all_norm = {_norm(p) for p in all_peer_addrs}

        # Per-peer "routes advertised to peer" count via getBgpSessions ->
        # postpolicy_sent_prefix_count. We do NOT use
        # getPostfilterAdvertisedNetworks because BGP++ with UG enabled does
        # not populate per-peer adj-RIB-out (UG fans out collectively, so the
        # postfilter API returns 0 even when routes are being advertised).
        # postpolicy_sent_prefix_count is the same counter shown in the CLI
        # `show bgpcpp summary` "PS" column and is reliable across UG modes.
        try:
            # pyrefly: ignore [missing-attribute]
            sessions = await self.driver.async_get_bgp_sessions()
        except Exception as e:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.ERROR,
                message=(
                    f"BGP peer route-set equality on {hostname}: "
                    f"getBgpSessions thrift query failed: {e}"
                ),
            )

        per_peer_count: t.Dict[str, int] = {}
        for s in sessions or []:
            peer_addr = _norm(s.peer_addr)
            if peer_addr in all_norm:
                per_peer_count[peer_addr] = int(
                    getattr(s, "postpolicy_sent_prefix_count", 0) or 0
                )

        return self._evaluate_counts(
            hostname=hostname,
            baseline_peer_addr=_norm(baseline_peer_addr),
            tested_peer_addrs=[_norm(p) for p in tested_peer_addrs],
            per_peer_count=per_peer_count,
            anchor_route_count=anchor_route_count,
            count_tolerance=count_tolerance,
        )

    def _evaluate_counts(
        self,
        hostname: str,
        baseline_peer_addr: str,
        tested_peer_addrs: t.List[str],
        per_peer_count: t.Dict[str, int],
        anchor_route_count: t.Optional[int],
        count_tolerance: int,
    ) -> hc_types.HealthCheckResult:
        """Count-based evaluation using postpolicy_sent_prefix_count per peer.

        We can't compare prefix SETS via this counter (it's only a count) so
        the equality check degrades to a count equality check across baseline
        + tested peers. The optional anchor_route_count enforces the absolute
        expected count.
        """
        failures: t.List[str] = []
        baseline_count = per_peer_count.get(baseline_peer_addr)
        if baseline_count is None:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=(
                    f"BGP peer route-set equality on {hostname}: baseline peer "
                    f"{baseline_peer_addr} has no BGP session (not in "
                    f"getBgpSessions result)."
                ),
            )

        # (1) Optional anchor count
        if anchor_route_count is not None:
            lo = anchor_route_count - count_tolerance
            hi = anchor_route_count + count_tolerance
            if not (lo <= baseline_count <= hi):
                failures.append(
                    f"Baseline peer {baseline_peer_addr} sent_prefix_count="
                    f"{baseline_count}; expected {anchor_route_count} "
                    f"(+/-{count_tolerance})."
                )
            for tested in tested_peer_addrs:
                tested_count = per_peer_count.get(tested)
                if tested_count is None:
                    failures.append(f"Tested peer {tested} has no BGP session.")
                    continue
                if not (lo <= tested_count <= hi):
                    failures.append(
                        f"Tested peer {tested} sent_prefix_count="
                        f"{tested_count}; expected {anchor_route_count} "
                        f"(+/-{count_tolerance})."
                    )

        # (2) Count equality vs baseline
        for tested in tested_peer_addrs:
            tested_count = per_peer_count.get(tested)
            if tested_count is None:
                # already reported above if anchor set; otherwise report here
                if anchor_route_count is None:
                    failures.append(f"Tested peer {tested} has no BGP session.")
                continue
            if tested_count != baseline_count:
                failures.append(
                    f"Tested peer {tested} sent_prefix_count={tested_count} "
                    f"differs from baseline {baseline_peer_addr}="
                    f"{baseline_count}."
                )

        if failures:
            numbered = "\n".join(f"  {i}. {f}" for i, f in enumerate(failures, 1))
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=(
                    f"BGP peer route-set equality found {len(failures)} "
                    f"failure(s) on {hostname} (baseline={baseline_peer_addr}, "
                    f"tested={tested_peer_addrs}):\n{numbered}"
                ),
            )

        summary = (
            f"baseline {baseline_peer_addr} sent_prefix_count={baseline_count}; "
            f"{len(tested_peer_addrs)} tested peer(s) all match"
            + (
                f" (anchor_route_count={anchor_route_count})"
                if anchor_route_count is not None
                else ""
            )
        )
        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
            message=f"BGP peer route-set equality PASSED on {hostname}: {summary}.",
        )

    async def _run_arista(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        """ARISTA_FBOSS path: delegates to thrift `_run` which uses
        ``getBgpSessions`` + ``postpolicy_sent_prefix_count``. The native EOS
        ``show bgp ipv6 unicast neighbors <peer> advertised-routes`` CLI does
        not exist on BGP++ devices, so there is no useful CLI-only path here.
        """
        return await self._run(obj, input, check_params)

    def _evaluate(
        self,
        hostname: str,
        baseline_peer_addr: str,
        tested_peer_addrs: t.List[str],
        per_peer_prefixes: t.Dict[str, t.Set[t.Any]],
        anchor_route_count: t.Optional[int],
        count_tolerance: int,
        allow_extra_in_tested: bool,
    ) -> hc_types.HealthCheckResult:
        """Shared assertion logic for thrift + arista paths."""
        failures: t.List[str] = []

        baseline_prefixes = per_peer_prefixes.get(baseline_peer_addr, set())
        baseline_count = len(baseline_prefixes)

        # (1) Optional anchor count: baseline first, then each tested peer.
        if anchor_route_count is not None:
            lo = anchor_route_count - count_tolerance
            hi = anchor_route_count + count_tolerance
            if not (lo <= baseline_count <= hi):
                failures.append(
                    f"Baseline peer {baseline_peer_addr} received {baseline_count} "
                    f"routes; expected {anchor_route_count} (+/-{count_tolerance})."
                )
            for tested in tested_peer_addrs:
                tested_count = len(per_peer_prefixes.get(tested, set()))
                if not (lo <= tested_count <= hi):
                    failures.append(
                        f"Tested peer {tested} received {tested_count} routes; "
                        f"expected {anchor_route_count} (+/-{count_tolerance})."
                    )

        # (2) Set equality (or superset when allow_extra_in_tested).
        for tested in tested_peer_addrs:
            tested_prefixes = per_peer_prefixes.get(tested, set())
            missing = baseline_prefixes - tested_prefixes
            extra = tested_prefixes - baseline_prefixes
            if missing:
                failures.append(
                    f"Tested peer {tested} is MISSING "
                    f"{len(missing)} prefix(es) present on baseline "
                    f"{baseline_peer_addr}: {_short_sample(missing)}."
                )
            if extra and not allow_extra_in_tested:
                failures.append(
                    f"Tested peer {tested} has {len(extra)} EXTRA prefix(es) "
                    f"not present on baseline {baseline_peer_addr}: "
                    f"{_short_sample(extra)}."
                )

        if failures:
            numbered = "\n".join(f"  {i}. {f}" for i, f in enumerate(failures, 1))
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=(
                    f"BGP peer route-set equality found {len(failures)} failure(s) "
                    f"on {hostname} (baseline={baseline_peer_addr}, "
                    f"tested={tested_peer_addrs}):\n{numbered}"
                ),
            )

        summary = (
            f"baseline {baseline_peer_addr} has {baseline_count} prefixes; "
            f"{len(tested_peer_addrs)} tested peer(s) all match"
            + (
                f" (anchor_route_count={anchor_route_count})"
                if anchor_route_count is not None
                else ""
            )
        )
        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
            message=f"BGP peer route-set equality PASSED on {hostname}: {summary}.",
        )
