# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""
Utility functions for BGP route count verification.

This module provides shared logic for verifying BGP route counts using
prefilter and postfilter APIs. It is used by both BgpRouteCountVerificationHealthCheck
and BgpVerifyReceivedRoutesTask.
"""

import asyncio
import typing as t
from dataclasses import dataclass

from neteng.fboss.bgp_thrift.types import TBgpPeerState, TBgpSession

# Valid values for direction and policy_type parameters
DIRECTION_RECEIVED = "received"
DIRECTION_ADVERTISED = "advertised"
VALID_DIRECTIONS = [DIRECTION_RECEIVED, DIRECTION_ADVERTISED]

POLICY_TYPE_PRE_POLICY = "pre_policy"
POLICY_TYPE_POST_POLICY = "post_policy"
VALID_POLICY_TYPES = [POLICY_TYPE_PRE_POLICY, POLICY_TYPE_POST_POLICY]


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
) -> t.List[str]:
    """
    Filter BGP sessions by description and return peer IPs of ESTABLISHED sessions.

    Args:
        bgp_sessions: Sequence of BGP sessions to filter
        descriptions_to_ignore: List of description substrings to ignore peers by (optional)
        descriptions_to_check: List of description substrings to check peers by (optional)

    Returns:
        List of peer IP addresses that passed the filter
    """
    descriptions_to_ignore = descriptions_to_ignore or []
    descriptions_to_check = descriptions_to_check or []

    peers_to_check = []
    for session in bgp_sessions:
        peer_ip = str(session.peer_addr)

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
