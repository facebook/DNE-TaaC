# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe

"""
BGP++ Update Group received-route community equality across peers.

Asserts that a set of tested peers receive routes carrying the SAME community
list (per prefix) as a baseline peer. Optionally also asserts that every route
on every checked peer carries a specific anchor community.

The spec gate for BGP++ UG 2.4.3 -- after a mid-sync community mutation on the
sender, every UG member (including the newly-joined held-back peer) must end
up with the NEW community, not the stale one.

Backed primarily by BGP++ thrift ``getPostfilterAdvertisedNetworks`` (one
call per peer, returns ``Mapping[TIpPrefix, TBgpPath]`` with each TBgpPath
carrying ``community_list`` -- the DUT-side mirror of what the receiver
peer should be getting after egress policy). EOS devices not declared
``ARISTA_FBOSS`` in the TestConfig's ``host_os_type_map`` run native EOS BGP
and are read via
``show bgp ipv6 unicast neighbors <peer> advertised-routes detail | json``.

KNOWN LIMITATION under BGP++ Update Group: ``getPostfilterAdvertisedNetworks``
returns 0 prefixes for every peer when UG is enabled, because UG bypasses
per-peer adj-RIB-out. This makes the HC effectively vacuous (it iterates an
empty prefix set and trivially satisfies all assertions). Tracked:
T271301144 (owner xiangxu1121, NO_PROGRESS). No counter-based workaround
exists for per-prefix community attributes (the gauge replacement used in
``BgpPeerRouteSetEqualityHealthCheck`` only gives counts, not attrs). Until
T271301144 lands OR an IXIA-side ``GetAllLearnedInfo`` path is added, this
HC is a placeholder for the 2.4.3 spec gate -- documented as a vacuous-OK
limitation in the consumer testconfig (see D109339151 Summary).

Scoping note: ``_evaluate`` compares COMMUNITY ATTRIBUTES on the set
intersection of baseline and tested-peer prefixes. Prefixes present on only
one side are silently ignored by this check -- the companion
``BgpPeerRouteSetEqualityHealthCheck`` is the dedicated assertion for
prefix-set equality across peers, and callers should pair the two when both
checks matter.
"""

import ipaddress
import typing as t

from taac.constants import TestDevice
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
)
from taac.health_checks.common_utils import declares_bgpcpp
from taac.health_check.health_check import types as hc_types


def _norm(addr: t.Optional[str]) -> str:
    if not addr:
        return ""
    try:
        return str(ipaddress.ip_address(addr))
    except ValueError:
        return addr


def _format_prefix(prefix: t.Any) -> str:
    try:
        return f"{prefix.prefix}/{prefix.prefix_length}"
    except AttributeError:
        return str(prefix)


def _normalize_community(value: t.Any) -> str:
    """Render a community in canonical ``ASN:value`` form.

    BGP communities can arrive as ``"65529:39744"`` strings, as packed 32-bit
    ints (``65529 << 16 | 39744``), as ``(asn, value)`` tuples, or as
    ``TBgpCommunity`` thrift structs (``.asn`` + ``.value`` fields) depending
    on the source. Normalize to a single comparable string.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    # TBgpCommunity thrift struct (the actual type returned by
    # getPostfilterAdvertisedNetworks / getPostfilterReceivedNetworks post-
    # T271301144). Must be checked BEFORE the int branch because TBgpCommunity
    # is not an int instance but does have .asn + .value attributes.
    if hasattr(value, "asn") and hasattr(value, "value"):
        return f"{value.asn}:{value.value}"
    if isinstance(value, int):
        asn = (value >> 16) & 0xFFFF
        val = value & 0xFFFF
        return f"{asn}:{val}"
    if isinstance(value, (tuple, list)) and len(value) == 2:
        return f"{value[0]}:{value[1]}"
    return str(value)


def _extract_communities(path: t.Any) -> t.FrozenSet[str]:
    """Extract communities from a TBgpPath-like object as a frozenset of strings.

    The actual TBgpPath field is named ``communities`` (per
    ``neteng/fboss/bgp/if/bgp_route_types.thrift::TBgpPath.3``). The legacy
    ``community_list`` is a defensive alias for older bindings.

    Uses explicit ``is not None`` instead of ``or`` so an empty modern
    ``communities=[]`` field doesn't silently fall back to a stale legacy
    ``community_list`` value (per Devmate review).
    """
    communities = getattr(path, "communities", None)
    if communities is None:
        communities = getattr(path, "community_list", None)
    if not communities:
        return frozenset()
    return frozenset(_normalize_community(c) for c in communities)


def _short_sample_prefixes(prefixes: t.Iterable[t.Any], limit: int = 10) -> str:
    rendered = sorted(_format_prefix(p) for p in prefixes)
    head = rendered[:limit]
    tail = f" ... +{len(rendered) - limit} more" if len(rendered) > limit else ""
    return ", ".join(head) + tail


class BgpReceivedRouteCommunityHealthCheck(
    AbstractDeviceHealthCheck[hc_types.BaseHealthCheckIn]
):
    """
    Verify a set of tested peers receive the same community list (per prefix)
    as a baseline peer, optionally anchored on an expected community.

    Two assertions, both run in a single pass:

    1. **Anchor community present on every received route** (if
       ``anchor_community`` set): every prefix on baseline and every tested
       peer must carry the anchor community. Diagnoses the spec failure mode
       directly -- "stale community survived the mutation".

    2. **Per-prefix community equality** between baseline and tested peers:
       prefix-for-prefix, the community list must match. Catches drift even
       when the anchor is present (e.g. a stray extra community on a single
       peer).

    Configurable via ``check_params``:

      - ``baseline_peer_addr`` (str, required): IP of the ground-truth peer.
      - ``tested_peer_addrs`` (list[str], required): IPs of peers whose
        per-prefix community lists must match baseline.
      - ``anchor_community`` (optional str, e.g. ``"0:665"``): asserted to be
        present on EVERY route on EVERY checked peer.
      - ``forbidden_communities`` (optional list[str]): communities that
        must NOT appear on any route on any checked peer (e.g. the pre-
        mutation community in a 2.4.3 test).
      - ``address_family`` (str, default "ipv6"): arista-CLI path only.

    OS: ARISTA_FBOSS (declared in host_os_type_map) uses thrift; other EOS
    devices use the EOS CLI path.
    """

    CHECK_NAME = hc_types.CheckName.BGP_RECEIVED_ROUTE_COMMUNITY_CHECK
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
        anchor_community = check_params.get("anchor_community")
        forbidden_communities = check_params.get("forbidden_communities") or []
        sender_peer_addr = check_params.get("sender_peer_addr")

        # adj-RIB-IN mode (TRIGGER verification): probe what DUT received on
        # the wire from a SINGLE sender peer via ``getPrefilterReceivedNetworks``.
        # This isolates the IXIA-side mutation (the wrapper task's job) from
        # any downstream UG replication delay or per-receiver-peer adj-RIB-out
        # state. Use when the test goal is "did my IXIA mutation actually
        # land on the wire?"; for "did UG propagate to every receiver?",
        # use the default adj-RIB-OUT mode below.
        if sender_peer_addr:
            try:
                # pyrefly: ignore [missing-attribute]
                mapping = await self.driver.async_get_prefilter_received_networks(
                    sender_peer_addr
                )
                per_peer: t.Dict[str, t.Dict[t.Any, t.FrozenSet[str]]] = {
                    _norm(sender_peer_addr): {
                        prefix: _extract_communities(path)
                        for prefix, path in mapping.items()
                    }
                }
            except Exception as e:
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.ERROR,
                    message=(
                        f"BGP received-route community check on {hostname}: "
                        f"adj-RIB-IN thrift query for sender={sender_peer_addr} "
                        f"failed: {e}"
                    ),
                )
            return self._evaluate(
                hostname=hostname,
                baseline_peer_addr=_norm(sender_peer_addr),
                tested_peer_addrs=[],
                per_peer=per_peer,
                anchor_community=anchor_community,
                forbidden_communities=forbidden_communities,
            )

        if not baseline_peer_addr:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=(
                    f"BGP received-route community check on {hostname}: "
                    f"missing required param baseline_peer_addr."
                ),
            )
        if not tested_peer_addrs:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=(
                    f"BGP received-route community check on {hostname}: "
                    f"missing required param tested_peer_addrs."
                ),
            )

        all_peer_addrs = [baseline_peer_addr] + [
            p for p in tested_peer_addrs if _norm(p) != _norm(baseline_peer_addr)
        ]

        # Fetch per-peer prefix -> community-set map via thrift. "Tested peers
        # receive" (test semantics) = "DUT advertised to them" (DUT-side mirror).
        try:
            per_peer = {}
            for peer_addr in all_peer_addrs:
                # pyrefly: ignore [missing-attribute]
                mapping = await self.driver.async_get_postfilter_advertised_networks(
                    peer_addr
                )
                per_peer[_norm(peer_addr)] = {
                    prefix: _extract_communities(path)
                    for prefix, path in mapping.items()
                }
        except Exception as e:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.ERROR,
                message=(
                    f"BGP received-route community check on {hostname}: "
                    f"thrift query failed: {e}"
                ),
            )

        return self._evaluate(
            hostname=hostname,
            baseline_peer_addr=_norm(baseline_peer_addr),
            tested_peer_addrs=[_norm(p) for p in tested_peer_addrs],
            per_peer=per_peer,
            anchor_community=anchor_community,
            forbidden_communities=forbidden_communities,
        )

    async def _run_arista(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        """Thrift for devices declared ARISTA_FBOSS; EOS CLI otherwise."""
        if declares_bgpcpp(obj.name):
            return await self._run(obj, input, check_params)
        hostname = obj.name
        baseline_peer_addr = check_params.get("baseline_peer_addr")
        tested_peer_addrs = check_params.get("tested_peer_addrs") or []
        anchor_community = check_params.get("anchor_community")
        forbidden_communities = check_params.get("forbidden_communities") or []
        address_family = check_params.get("address_family", "ipv6")
        sender_peer_addr = check_params.get("sender_peer_addr")

        # adj-RIB-IN mode has no native EOS CLI equivalent (EOS
        # ``show ip bgp neighbors <peer> received-routes`` doesn't surface
        # the same prefilter view as bgpcpp's ``getPrefilterReceivedNetworks``).
        # Always delegate to the thrift path on _run, which is correct for
        # both ARISTA_FBOSS (bgpcpp running on EOS-host) and pure FBOSS.
        if sender_peer_addr:
            return await self._run(obj, input, check_params)

        if not baseline_peer_addr or not tested_peer_addrs:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=(
                    f"BGP received-route community check on {hostname}: "
                    f"baseline_peer_addr and tested_peer_addrs are required."
                ),
            )

        all_peer_addrs = [baseline_peer_addr] + [
            p for p in tested_peer_addrs if _norm(p) != _norm(baseline_peer_addr)
        ]

        per_peer: t.Dict[str, t.Dict[str, t.FrozenSet[str]]] = {}
        try:
            for peer_addr in all_peer_addrs:
                cmd = (
                    f"show bgp {address_family} unicast neighbors "
                    f"{peer_addr} advertised-routes detail | json"
                )
                # pyrefly: ignore [missing-attribute]
                result = await self.driver.async_execute_show_json_on_shell(cmd)
                route_entries = (
                    result.get("vrfs", {}).get("default", {}).get("bgpRouteEntries", {})
                )
                prefix_map: t.Dict[str, t.FrozenSet[str]] = {}
                for prefix, entry in route_entries.items():
                    paths = entry.get("bgpRoutePaths") or []
                    # Take the first path's community list -- arista returns
                    # paths in best-first order; for advertised-routes from a
                    # single peer there should be exactly one.
                    if not paths:
                        prefix_map[prefix] = frozenset()
                        continue
                    raw = paths[0].get("routeDetail", {}).get("communityList", [])
                    prefix_map[prefix] = frozenset(_normalize_community(c) for c in raw)
                per_peer[_norm(peer_addr)] = prefix_map
        except Exception as e:
            # Fall back to BGP++ thrift on any of:
            #   - "BGP inactive": native EOS BGP daemon is off (ARISTA_FBOSS with
            #     BGP++ running instead).
            #   - "% Invalid input" / "Invalid input": EOS CLI doesn't recognize
            #     the command -- BGP++ FBOSS doesn't expose the EOS
            #     ``advertised-routes detail`` CLI surface.
            err_str = str(e)
            if (
                "BGP inactive" in err_str
                or "Invalid input" in err_str
                or "% Invalid" in err_str
            ):
                self.logger.info(
                    f"Native EOS BGP CLI unavailable on {hostname} "
                    f"({err_str.strip()[:80]}); falling back to BGP++ thrift "
                    f"route-community query."
                )
                return await self._run(obj, input, check_params)
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.ERROR,
                message=(
                    f"BGP received-route community check on {hostname}: "
                    f"EOS CLI query failed: {e}"
                ),
            )

        return self._evaluate(
            hostname=hostname,
            baseline_peer_addr=_norm(baseline_peer_addr),
            tested_peer_addrs=[_norm(p) for p in tested_peer_addrs],
            per_peer=per_peer,
            anchor_community=anchor_community,
            forbidden_communities=forbidden_communities,
        )

    def _check_anchor(self, all_peers, per_peer, anchor):
        """Sub-assertion (1): anchor community present on every received route."""
        failures: t.List[str] = []
        for peer in all_peers:
            missing = sorted(
                _format_prefix(prefix)
                for prefix, comms in per_peer.get(peer, {}).items()
                if anchor not in comms
            )
            if missing:
                tail = f" ... +{len(missing) - 10} more" if len(missing) > 10 else ""
                failures.append(
                    f"Peer {peer} has {len(missing)} prefix(es) missing anchor "
                    f"community {anchor}: {', '.join(missing[:10])}{tail}"
                )
        return failures

    def _check_forbidden(self, all_peers, per_peer, forbidden):
        """Sub-assertion (2): forbidden communities absent from every route."""
        failures: t.List[str] = []
        for peer in all_peers:
            bad = sorted(
                _format_prefix(prefix)
                for prefix, comms in per_peer.get(peer, {}).items()
                if comms & forbidden
            )
            if bad:
                tail = f" ... +{len(bad) - 10} more" if len(bad) > 10 else ""
                failures.append(
                    f"Peer {peer} has {len(bad)} prefix(es) carrying forbidden "
                    f"community(ies) {sorted(forbidden)}: "
                    f"{', '.join(bad[:10])}{tail}"
                )
        return failures

    def _check_equality(self, baseline_peer_addr, tested_peer_addrs, per_peer):
        """Sub-assertion (3): per-prefix community equality on the set
        intersection of baseline and tested-peer prefixes. Prefixes present
        on only one side are intentionally ignored here -- the companion
        ``BgpPeerRouteSetEqualityHealthCheck`` is the dedicated prefix-set
        equality assertion."""
        failures: t.List[str] = []
        baseline_map = per_peer.get(baseline_peer_addr, {})
        for tested in tested_peer_addrs:
            tested_map = per_peer.get(tested, {})
            shared = set(baseline_map) & set(tested_map)
            mismatched = sorted(
                f"{_format_prefix(prefix)} "
                f"[baseline={sorted(baseline_map[prefix])} "
                f"tested={sorted(tested_map[prefix])}]"
                for prefix in shared
                if baseline_map[prefix] != tested_map[prefix]
            )
            if mismatched:
                tail = (
                    f" ... +{len(mismatched) - 5} more" if len(mismatched) > 5 else ""
                )
                failures.append(
                    f"Tested peer {tested} has {len(mismatched)} prefix(es) "
                    f"with community mismatch vs baseline "
                    f"{baseline_peer_addr}: {', '.join(mismatched[:5])}{tail}"
                )
        return failures

    def _evaluate(
        self,
        hostname: str,
        baseline_peer_addr: str,
        tested_peer_addrs: t.List[str],
        per_peer: t.Dict[str, t.Dict[t.Any, t.FrozenSet[str]]],
        anchor_community: t.Optional[str],
        forbidden_communities: t.List[str],
    ) -> hc_types.HealthCheckResult:
        """Shared assertion logic for thrift + arista paths."""
        anchor = _normalize_community(anchor_community) if anchor_community else None
        forbidden = {_normalize_community(c) for c in forbidden_communities}
        all_peers = [baseline_peer_addr] + tested_peer_addrs

        failures: t.List[str] = []
        if anchor:
            failures.extend(self._check_anchor(all_peers, per_peer, anchor))
        if forbidden:
            failures.extend(self._check_forbidden(all_peers, per_peer, forbidden))
        failures.extend(
            self._check_equality(baseline_peer_addr, tested_peer_addrs, per_peer)
        )

        baseline_map = per_peer.get(baseline_peer_addr, {})

        if failures:
            numbered = "\n".join(f"  {i}. {f}" for i, f in enumerate(failures, 1))
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=(
                    f"BGP received-route community check found {len(failures)} "
                    f"failure(s) on {hostname} (baseline={baseline_peer_addr}, "
                    f"tested={tested_peer_addrs}):\n{numbered}"
                ),
            )

        baseline_count = len(baseline_map)
        summary = (
            f"baseline {baseline_peer_addr} has {baseline_count} prefixes; "
            f"{len(tested_peer_addrs)} tested peer(s) match per-prefix communities"
            + (f" (anchor={anchor})" if anchor else "")
            + (f" (forbidden={sorted(forbidden)})" if forbidden else "")
        )
        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
            message=(
                f"BGP received-route community check PASSED on {hostname}: {summary}."
            ),
        )
