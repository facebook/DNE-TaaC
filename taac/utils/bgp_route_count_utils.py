# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""
Utility functions for BGP route count verification.

This module provides shared logic for verifying BGP route counts using
prefilter and postfilter APIs. It is used by both BgpRouteCountVerificationHealthCheck
and BgpVerifyReceivedRoutesTask.
"""

import asyncio
import ipaddress
import json
import math
import typing as t
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass

from neteng.fboss.bgp_thrift.types import TBgpPeerState, TBgpSession

# Valid values for direction and policy_type parameters
DIRECTION_RECEIVED = "received"
DIRECTION_ADVERTISED = "advertised"
VALID_DIRECTIONS = [DIRECTION_RECEIVED, DIRECTION_ADVERTISED]

POLICY_TYPE_PRE_POLICY = "pre_policy"
POLICY_TYPE_POST_POLICY = "post_policy"
VALID_POLICY_TYPES = [POLICY_TYPE_PRE_POLICY, POLICY_TYPE_POST_POLICY]

_UPDATE_GROUP_DIAGNOSTIC_LIMIT = 20
_BGP_NEIGHBOR_QUERY_CHUNK_SIZE = 128

RouteCountHistogram = t.Dict[int, int]
RouteCountHistogramByAfi = t.Dict[str, RouteCountHistogram]
_VALID_AFI_NAMES = ("ipv4", "ipv6")


def _normalize_histogram_integer(value: t.Any) -> int:
    if isinstance(value, bool):
        raise ValueError
    try:
        normalized = int(value)
    except (OverflowError, TypeError, ValueError) as error:
        raise ValueError from error
    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            raise ValueError
    elif str(normalized) != str(value):
        raise ValueError
    return normalized


def _normalize_route_count_histogram(
    value: t.Any,
    *,
    afi: str,
) -> RouteCountHistogram:
    if not isinstance(value, Mapping) or not value:
        raise ValueError(
            f"expected_count_histogram_by_afi[{afi!r}] must be a non-empty mapping"
        )

    normalized: RouteCountHistogram = {}
    for raw_route_count, raw_peer_count in value.items():
        try:
            route_count = _normalize_histogram_integer(raw_route_count)
            peer_count = _normalize_histogram_integer(raw_peer_count)
        except (TypeError, ValueError) as error:
            raise ValueError(
                "expected_count_histogram_by_afi route and peer counts must be integers"
            ) from error
        if route_count < 0 or peer_count <= 0:
            raise ValueError(
                "expected_count_histogram_by_afi route counts must be non-negative "
                "and peer counts must be positive"
            )
        if route_count in normalized:
            raise ValueError(
                "expected_count_histogram_by_afi contains duplicate route count "
                f"{route_count} for {afi}"
            )
        normalized[route_count] = peer_count

    return dict(sorted(normalized.items()))


def normalize_expected_count_histogram_by_afi(
    value: t.Optional[Mapping[t.Any, t.Any]],
) -> t.Optional[RouteCountHistogramByAfi]:
    """Normalize serialized per-AFI route-count histograms."""
    if value is None:
        return None
    if not isinstance(value, Mapping) or not value:
        raise ValueError("expected_count_histogram_by_afi must be a non-empty mapping")

    normalized: RouteCountHistogramByAfi = {}
    for raw_afi, raw_histogram in value.items():
        if raw_afi not in _VALID_AFI_NAMES:
            raise ValueError(
                "expected_count_histogram_by_afi keys must be 'ipv4' or 'ipv6'"
            )
        afi = t.cast(str, raw_afi)
        normalized[afi] = _normalize_route_count_histogram(
            raw_histogram,
            afi=afi,
        )

    return {afi: normalized[afi] for afi in _VALID_AFI_NAMES if afi in normalized}


_ROUTE_COUNT_FIELD_PREFIX = {
    (DIRECTION_RECEIVED, POLICY_TYPE_PRE_POLICY): "prepolicy_rcvd_prefix_count",
    (DIRECTION_RECEIVED, POLICY_TYPE_POST_POLICY): "postpolicy_rcvd_prefix_count",
    (DIRECTION_ADVERTISED, POLICY_TYPE_PRE_POLICY): "prepolicy_sent_prefix_count",
    (DIRECTION_ADVERTISED, POLICY_TYPE_POST_POLICY): "postpolicy_sent_prefix_count",
}


def _normalize_session_route_count(
    value: t.Any,
    *,
    peer: str,
    afi: str,
    field_name: str,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(
            f"BGP neighbor {peer!r} has invalid {afi} route count "
            f"{field_name}={value!r}; expected a non-negative integer"
        )
    return value


def _normalize_peer_identity(value: t.Any) -> str:
    raw_value = str(value)
    try:
        # BGP service peer keys and targeted getBgpNeighbors requests use the
        # bare address.  A link-local scope can appear in higher-level session
        # renderings, but it is not part of the service identity.
        return str(ipaddress.ip_address(raw_value.split("%", 1)[0]))
    except ValueError as error:
        raise ValueError(
            f"BGP neighbor identity {raw_value!r} is not an IP address"
        ) from error


def route_count_histogram_from_bgp_neighbors(  # noqa: C901
    sessions: t.Sequence[TBgpSession],
    *,
    requested_peers: t.Sequence[str],
    afis: t.Collection[str],
    direction: str,
    policy_type: str,
) -> RouteCountHistogramByAfi:
    """Build route-count distributions from authoritative route-AFI counters.

    A transport peer address does not identify the NLRI address family in
    MP-BGP.  Detailed neighbor state exposes both negotiated route families and
    their independent counters, so histogram attribution must come from that
    state rather than from the peer address literal.
    """
    validate_direction(direction)
    validate_policy_type(policy_type)
    requested_afis = tuple(afi for afi in _VALID_AFI_NAMES if afi in set(afis))
    if not requested_afis or set(requested_afis) != set(afis):
        raise ValueError("route-count histogram AFIs must be 'ipv4' or 'ipv6'")

    requested = tuple(_normalize_peer_identity(peer) for peer in requested_peers)
    if not requested:
        raise ValueError("route-count histogram requires at least one selected peer")
    if len(set(requested)) != len(requested):
        raise ValueError("route-count histogram peer request contains duplicates")
    requested_set = set(requested)

    sessions_by_peer: t.Dict[str, TBgpSession] = {}
    unexpected: t.Set[str] = set()
    duplicates: t.Set[str] = set()
    for session in sessions:
        peer = _normalize_peer_identity(getattr(session, "peer_addr", ""))
        if peer not in requested_set:
            unexpected.add(peer)
            continue
        if peer in sessions_by_peer:
            duplicates.add(peer)
            continue
        sessions_by_peer[peer] = session

    missing = requested_set - set(sessions_by_peer)
    if missing or unexpected or duplicates:
        raise ValueError(
            "Detailed BGP neighbor response does not exactly match the request: "
            f"missing={sorted(missing)}, unexpected={sorted(unexpected)}, "
            f"duplicates={sorted(duplicates)}"
        )

    field_prefix = _ROUTE_COUNT_FIELD_PREFIX[(direction, policy_type)]
    counters = {afi: Counter[int]() for afi in requested_afis}
    for peer in requested:
        session = sessions_by_peer[peer]
        peer_state = getattr(getattr(session, "peer", None), "peer_state", None)
        if peer_state != TBgpPeerState.ESTABLISHED:
            raise ValueError(
                f"Detailed BGP neighbor {peer!r} is not ESTABLISHED: {peer_state!r}"
            )
        details = getattr(session, "details", None)
        if details is None:
            raise ValueError(f"Detailed BGP neighbor {peer!r} has no session details")

        for afi in _VALID_AFI_NAMES:
            negotiated_field = f"{afi}_unicast"
            negotiated = getattr(details, negotiated_field, None)
            if not isinstance(negotiated, bool):
                raise ValueError(
                    f"Detailed BGP neighbor {peer!r} has invalid "
                    f"{negotiated_field}={negotiated!r}; expected bool"
                )
            count_field = f"{field_prefix}_{afi}"
            route_count = _normalize_session_route_count(
                getattr(details, count_field, None),
                peer=peer,
                afi=afi,
                field_name=count_field,
            )
            if not negotiated:
                if route_count:
                    raise ValueError(
                        f"Detailed BGP neighbor {peer!r} reports {route_count} "
                        f"{afi} routes while {negotiated_field}=False"
                    )
                continue
            if afi in counters:
                counters[afi][route_count] += 1

    return {afi: dict(sorted(counters[afi].items())) for afi in requested_afis}


async def get_route_count_histogram_by_afi_for_peers(
    *,
    peers: t.Sequence[str],
    afis: t.Collection[str],
    direction: str,
    policy_type: str,
    bgp_helper: t.Any,
) -> RouteCountHistogramByAfi:
    """Fetch detailed neighbors and build an authoritative route-AFI histogram."""
    normalized_peers = tuple(_normalize_peer_identity(peer) for peer in peers)
    if not normalized_peers:
        raise ValueError("route-count histogram requires at least one selected peer")
    if len(set(normalized_peers)) != len(normalized_peers):
        raise ValueError("route-count histogram peer request contains duplicates")
    chunks = tuple(
        normalized_peers[index : index + _BGP_NEIGHBOR_QUERY_CHUNK_SIZE]
        for index in range(0, len(normalized_peers), _BGP_NEIGHBOR_QUERY_CHUNK_SIZE)
    )
    results = await asyncio.gather(
        *(bgp_helper.async_get_bgp_neighbors(chunk) for chunk in chunks)
    )
    sessions = tuple(session for result in results for session in result)
    return route_count_histogram_from_bgp_neighbors(
        sessions,
        requested_peers=normalized_peers,
        afis=afis,
        direction=direction,
        policy_type=policy_type,
    )


@dataclass
class RouteCountValidationResult:
    """Result of a route count validation."""

    peer_ip: str
    route_count: int
    passed: bool
    errors: t.List[str]

    @property
    def failed(self) -> bool:
        return not self.passed


def validate_direction(direction: str) -> None:
    """
    Validate that direction is a valid value.

    Args:
        direction: Direction string to validate

    Raises:
        ValueError: If direction is invalid
    """
    if direction not in VALID_DIRECTIONS:
        raise ValueError(
            f"Invalid direction '{direction}'. Must be 'received' or 'advertised'."
        )


def validate_policy_type(policy_type: str) -> None:
    """
    Validate that policy_type is a valid value.

    Args:
        policy_type: Policy type string to validate

    Raises:
        ValueError: If policy_type is invalid
    """
    if policy_type not in VALID_POLICY_TYPES:
        raise ValueError(
            f"Invalid policy_type '{policy_type}'. Must be 'pre_policy' or 'post_policy'."
        )


def validate_route_count(
    peer_ip: str,
    route_count: int,
    expected_count: t.Optional[int] = None,
    min_count: t.Optional[int] = None,
    max_count: t.Optional[int] = None,
    direction: t.Optional[str] = None,
    policy_type: t.Optional[str] = None,
) -> RouteCountValidationResult:
    """
    Validate a route count against expected, min, and max thresholds.

    Args:
        peer_ip: IP address of the BGP peer
        route_count: Actual number of routes
        expected_count: Expected exact route count (optional)
        min_count: Minimum expected routes (optional)
        max_count: Maximum expected routes (optional)
        direction: Direction of routes for error messages (optional)
        policy_type: Policy type for error messages (optional)

    Returns:
        RouteCountValidationResult with validation outcome
    """
    errors = []

    # Build context suffix for error messages
    context_parts = []
    if direction:
        context_parts.append(direction)
    if policy_type:
        context_parts.append(policy_type)
    context_suffix = f" ({', '.join(context_parts)})" if context_parts else ""

    if expected_count is not None and route_count != expected_count:
        errors.append(
            f"Peer {peer_ip}: expected {expected_count}, got {route_count}{context_suffix}"
        )

    if min_count is not None and route_count < min_count:
        errors.append(
            f"Peer {peer_ip}: expected >= {min_count}, got {route_count}{context_suffix}"
        )

    if max_count is not None and route_count > max_count:
        errors.append(
            f"Peer {peer_ip}: expected <= {max_count}, got {route_count}{context_suffix}"
        )

    return RouteCountValidationResult(
        peer_ip=peer_ip,
        route_count=route_count,
        passed=len(errors) == 0,
        errors=errors,
    )


def filter_bgp_sessions(
    bgp_sessions: t.Sequence[TBgpSession],
    descriptions_to_ignore: t.Optional[t.List[str]] = None,
    descriptions_to_check: t.Optional[t.List[str]] = None,
    peer_addresses_to_check: t.Optional[t.AbstractSet[str]] = None,
) -> t.List[str]:
    """
    Filter BGP sessions by description and return peer IPs of ESTABLISHED sessions.

    Args:
        bgp_sessions: Sequence of BGP sessions to filter
        descriptions_to_ignore: List of description substrings to ignore peers by (optional)
        descriptions_to_check: List of description substrings to check peers by (optional)
        peer_addresses_to_check: Exact peer addresses to check (optional)

    Returns:
        List of peer IP addresses that passed the filter
    """
    descriptions_to_ignore = descriptions_to_ignore or []
    descriptions_to_check = descriptions_to_check or []

    peers_to_check = []
    for session in bgp_sessions:
        peer_ip = str(session.peer_addr)

        if (
            peer_addresses_to_check is not None
            and peer_ip not in peer_addresses_to_check
        ):
            continue

        # Check if peer should be ignored by description
        if descriptions_to_ignore:
            peer_description = getattr(session, "description", "")
            should_ignore = any(
                desc_substring in peer_description
                for desc_substring in descriptions_to_ignore
            )
            if should_ignore:
                continue

        if descriptions_to_check:
            peer_description = getattr(session, "description", "")
            should_check = any(
                desc_substring in peer_description
                for desc_substring in descriptions_to_check
            )
            if not should_check:
                continue

        # Check peer state
        if session.peer.peer_state != TBgpPeerState.ESTABLISHED:
            continue

        peers_to_check.append(peer_ip)

    return peers_to_check


def select_peer_addresses_by_exact_peer_group(
    update_group_response: t.Any,
    peer_group_names: t.Sequence[str],
) -> t.Tuple[t.Set[str], t.Set[str]]:
    """Resolve exact peer-group names to peer addresses from update-group state.

    A peer group can span multiple update groups, so addresses are accumulated
    across every group whose authoritative key is an exact name match.

    Returns:
        Selected peer addresses and all observed non-empty peer-group names.
    """
    requested_names = set(peer_group_names)
    selected_addresses: t.Set[str] = set()
    observed_names: t.Set[str] = set()

    for group in getattr(update_group_response, "update_groups", None) or []:
        group_key = getattr(group, "group_key", None)
        peer_group_name = str(
            getattr(group_key, "peer_group_name", "") if group_key else ""
        )
        if peer_group_name:
            observed_names.add(peer_group_name)
        if peer_group_name not in requested_names:
            continue
        selected_addresses.update(
            str(peer.peer_addr)
            for peer in (getattr(group, "peers", None) or [])
            if getattr(peer, "peer_addr", None)
        )

    return selected_addresses, observed_names


def select_peer_addresses_by_exact_config_peer_group(
    bgp_config: t.Any,
    peer_group_names: t.Sequence[str],
) -> t.Tuple[t.Set[str], t.Set[str]]:
    """Resolve exact peer-group names to addresses from structured BGP config."""
    requested_names = set(peer_group_names)
    selected_addresses: t.Set[str] = set()
    observed_names: t.Set[str] = set()

    for peer in getattr(bgp_config, "peers", None) or []:
        peer_group_name = str(getattr(peer, "peer_group_name", "") or "")
        if peer_group_name:
            observed_names.add(peer_group_name)
        if peer_group_name not in requested_names:
            continue
        peer_address = getattr(peer, "peer_addr", None)
        if peer_address:
            selected_addresses.add(str(peer_address))

    return selected_addresses, observed_names


def format_update_group_diagnostics(update_group_response: t.Any) -> str:
    """Format bounded diagnostics from a structured update-group response."""
    groups = list(getattr(update_group_response, "update_groups", None) or [])
    formatted_groups = []
    for group in groups[:_UPDATE_GROUP_DIAGNOSTIC_LIMIT]:
        group_key = getattr(group, "group_key", None)
        peers = list(getattr(group, "peers", None) or [])
        formatted_groups.append(
            {
                "group_id": getattr(group, "group_id", None),
                "group_key": {
                    "afi_ipv4_negotiated": getattr(
                        group_key, "afi_ipv4_negotiated", None
                    ),
                    "afi_ipv6_negotiated": getattr(
                        group_key, "afi_ipv6_negotiated", None
                    ),
                    "egress_policy_name": getattr(
                        group_key, "egress_policy_name", None
                    ),
                    "peer_group_name": getattr(group_key, "peer_group_name", None),
                    "route_filter_stmt_name": getattr(
                        group_key, "route_filter_stmt_name", None
                    ),
                    "session_type": getattr(group_key, "session_type", None),
                },
                "group_state": getattr(group, "group_state", None),
                "member_count": getattr(group, "member_count", None),
                "in_sync_peer_count": getattr(group, "in_sync_peer_count", None),
                "detached_peer_count": getattr(group, "detached_peer_count", None),
                "peer_count": len(peers),
            }
        )

    diagnostics = {
        "enable_update_group": getattr(
            update_group_response, "enable_update_group", None
        ),
        "group_count": len(groups),
        "groups": formatted_groups,
        "omitted_group_count": max(0, len(groups) - _UPDATE_GROUP_DIAGNOSTIC_LIMIT),
    }
    return json.dumps(diagnostics, sort_keys=True)


async def get_route_count_for_peer(
    driver: t.Any,
    peer_ip: str,
    direction: str,
    policy_type: str,
) -> int:
    """
    Get route count for a single peer using the driver.

    Args:
        driver: The switch driver with BGP methods
        peer_ip: IP address of the BGP peer
        direction: "received" or "advertised"
        policy_type: "pre_policy" or "post_policy"

    Returns:
        Number of routes for the peer
    """
    if policy_type == POLICY_TYPE_PRE_POLICY:
        if direction == DIRECTION_RECEIVED:
            networks = await driver.async_get_prefilter_received_networks(peer_ip)
        else:
            networks = await driver.async_get_prefilter_advertised_networks(peer_ip)
    else:
        if direction == DIRECTION_RECEIVED:
            networks = await driver.async_get_postfilter_received_networks(peer_ip)
        else:
            networks = await driver.async_get_postfilter_advertised_networks(peer_ip)

    return len(networks)


async def get_route_count_for_peer_with_helper(
    bgp_helper: t.Any,
    peer_ip: str,
    direction: str,
    policy_type: str,
) -> int:
    """
    Get route count for a single peer using BgpClientHelper directly.

    Args:
        bgp_helper: BgpClientHelper instance
        peer_ip: IP address of the BGP peer
        direction: "received" or "advertised"
        policy_type: "pre_policy" or "post_policy"

    Returns:
        Number of routes for the peer
    """
    if policy_type == POLICY_TYPE_PRE_POLICY:
        if direction == DIRECTION_RECEIVED:
            networks = await bgp_helper.async_get_prefilter_received_networks(peer_ip)
        else:
            networks = await bgp_helper.async_get_prefilter_advertised_networks(peer_ip)
    else:
        if direction == DIRECTION_RECEIVED:
            networks = await bgp_helper.async_get_postfilter_received_networks(peer_ip)
        else:
            networks = await bgp_helper.async_get_postfilter_advertised_networks(
                peer_ip
            )

    return len(networks)


async def get_route_counts_for_peers(
    peers: t.List[str],
    direction: str,
    policy_type: str,
    driver: t.Optional[t.Any] = None,
    bgp_helper: t.Optional[t.Any] = None,
) -> t.Dict[str, int]:
    """
    Get route counts for multiple peers concurrently.

    Must provide either driver or bgp_helper.

    Args:
        peers: List of peer IP addresses
        direction: "received" or "advertised"
        policy_type: "pre_policy" or "post_policy"
        driver: The switch driver with BGP methods (optional)
        bgp_helper: BgpClientHelper instance (optional)

    Returns:
        Dictionary mapping peer IP to route count
    """
    if driver is None and bgp_helper is None:
        raise ValueError("Must provide either driver or bgp_helper")

    async def get_count_for_peer(peer_ip: str) -> t.Tuple[str, int]:
        try:
            if driver is not None:
                count = await get_route_count_for_peer(
                    driver=driver,
                    peer_ip=peer_ip,
                    direction=direction,
                    policy_type=policy_type,
                )
            else:
                count = await get_route_count_for_peer_with_helper(
                    bgp_helper=bgp_helper,
                    peer_ip=peer_ip,
                    direction=direction,
                    policy_type=policy_type,
                )
            return (peer_ip, count)
        except Exception:
            return (peer_ip, 0)

    tasks = [get_count_for_peer(peer_ip) for peer_ip in peers]
    results = await asyncio.gather(*tasks)

    return dict(results)


def validate_all_peer_route_counts(
    peer_route_counts: t.Dict[str, int],
    expected_count: t.Optional[int] = None,
    min_count: t.Optional[int] = None,
    max_count: t.Optional[int] = None,
    direction: t.Optional[str] = None,
    policy_type: t.Optional[str] = None,
) -> t.List[RouteCountValidationResult]:
    """
    Validate route counts for all peers.

    Args:
        peer_route_counts: Dictionary mapping peer IP to route count
        expected_count: Expected exact route count (optional)
        min_count: Minimum expected routes (optional)
        max_count: Maximum expected routes (optional)
        direction: Direction for error messages (optional)
        policy_type: Policy type for error messages (optional)

    Returns:
        List of RouteCountValidationResult for each peer
    """
    results = []
    for peer_ip, route_count in peer_route_counts.items():
        result = validate_route_count(
            peer_ip=peer_ip,
            route_count=route_count,
            expected_count=expected_count,
            min_count=min_count,
            max_count=max_count,
            direction=direction,
            policy_type=policy_type,
        )
        results.append(result)
    return results
