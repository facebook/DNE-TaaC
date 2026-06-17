# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""
Utilities for randomized IXIA flap timing.

Provides helpers to pick random uptime/downtime values from a configured
range and apply them to IXIA prefix and session flap APIs. Designed to
be re-used across any step or utility that needs randomized flap behavior.
"""

import random
import typing as t


def pick_flap_timing(
    uptime_min_sec: int = 15,
    uptime_max_sec: int = 15,
    downtime_min_sec: int = 15,
    downtime_max_sec: int = 15,
) -> t.Tuple[int, int]:
    """Pick random uptime and downtime values from the configured ranges.

    Args:
        uptime_min_sec: Minimum uptime in seconds (inclusive).
        uptime_max_sec: Maximum uptime in seconds (inclusive).
        downtime_min_sec: Minimum downtime in seconds (inclusive).
        downtime_max_sec: Maximum downtime in seconds (inclusive).

    Returns:
        A (uptime_sec, downtime_sec) tuple with randomly chosen values.
    """
    return (
        random.randint(uptime_min_sec, uptime_max_sec),
        random.randint(downtime_min_sec, downtime_max_sec),
    )


def apply_flap_timing(
    ixia: t.Any,
    churn_mode: str,
    uptime_sec: int,
    downtime_sec: int,
    enable_prefix_flap: bool = False,
    prefix_flap_network_group_regex: t.Optional[str] = None,
    enable_session_flap: bool = False,
    session_flap_bgp_peer_regex: t.Optional[str] = None,
) -> None:
    """Apply flap timing to IXIA prefix and/or session flap APIs.

    Configures the uptime/downtime on the appropriate IXIA objects
    based on the churn mode. Supports prefix-only, session-only, or
    combined prefix+session flapping.

    Args:
        ixia: The IXIA API instance.
        churn_mode: Flap mode string — checked for "prefix" and "session"
            substrings (e.g. "prefix_flap", "session_flap",
            "prefix_session_flap").
        uptime_sec: Seconds the route/session stays up per cycle.
        downtime_sec: Seconds the route/session stays down per cycle.
        enable_prefix_flap: Whether to enable or disable prefix flapping.
        prefix_flap_network_group_regex: IXIA network group name regex
            for prefix flapping. Required when "prefix" is in churn_mode.
        enable_session_flap: Whether to enable or disable session flapping.
        session_flap_bgp_peer_regex: IXIA BGP peer name regex for session
            flapping. Required when "session" is in churn_mode.
    """
    if "prefix" in churn_mode and prefix_flap_network_group_regex is not None:
        if "activate_deactivate" in churn_mode:
            ixia.logger.info(
                f"Activate/Deactivate prefixes for Network groups: "
                f"{prefix_flap_network_group_regex}"
            )
            ixia.activate_deactivate_bgp_prefix(
                active=enable_prefix_flap,
                network_group_name_regex=prefix_flap_network_group_regex,
            )
        else:
            ixia.logger.info(
                f"Flapping prefixes (uptime={uptime_sec}s, downtime={downtime_sec}s) "
                f"for Network groups: {prefix_flap_network_group_regex}"
            )
            ixia.toggle_prefix_flapping(
                is_flap=enable_prefix_flap,
                network_group_name_regex=prefix_flap_network_group_regex,
                uptime_in_sec=uptime_sec,
                downtime_in_sec=downtime_sec,
            )

    if "session" in churn_mode and session_flap_bgp_peer_regex is not None:
        ixia.logger.info(
            f"Flapping sessions (uptime={uptime_sec}s, downtime={downtime_sec}s) "
            f"for BGP peers: {session_flap_bgp_peer_regex}"
        )
        ixia.configure_bgp_peers_flap(
            enable=enable_session_flap,
            regex=session_flap_bgp_peer_regex,
            uptime_in_sec=uptime_sec,
            downtime_in_sec=downtime_sec,
        )
