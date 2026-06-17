# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""
Health check for verifying BGP route counts from peers.

This health check verifies the number of routes received from or advertised to
BGP peers, supporting both pre-policy and post-policy counters.
It's useful for validating that route filter policies (prefix-lists) are
working correctly on specific peer groups like EB-FA.
"""

import typing as t

from taac.constants import TestDevice
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
)
from taac.utils.bgp_route_count_utils import (
    filter_bgp_sessions,
    get_route_counts_for_peers,
    validate_all_peer_route_counts,
    validate_direction,
    validate_policy_type,
)
from taac.health_check.health_check import types as hc_types


class BgpRouteCountVerificationHealthCheck(
    AbstractDeviceHealthCheck[hc_types.BaseHealthCheckIn]
):
    """
    Health check to verify BGP route counts with pre/post policy filtering.

    This check supports both pre-policy and post-policy route counts:
    - pre_policy: Uses getPrefilterReceivedNetworks/getPrefilterAdvertisedNetworks APIs
    - post_policy: Uses getPostfilterReceivedNetworks/getPostfilterAdvertisedNetworks APIs

    Useful for validating that prefix-lists and route filter policies are working
    correctly for all established BGP peers (or a filtered subset).
    """

    CHECK_NAME = hc_types.CheckName.BGP_ROUTE_COUNT_VERIFICATION_CHECK
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
        """
        Verify BGP route counts from all peers (or filtered subset).

        Args:
            obj: Test device
            input: Base health check input
            check_params: Dictionary containing:
                - descriptions_to_ignore: List of description substrings to ignore peers by (optional)
                - descriptions_to_check: List of description substrings to check peers by (optional)
                - direction: "received" or "advertised" (optional, defaults to "received")
                - policy_type: "pre_policy" or "post_policy" (optional, defaults to "pre_policy")
                    - pre_policy: Uses getPrefilterReceivedNetworks/getPrefilterAdvertisedNetworks
                      APIs to get route counts before policy filtering
                    - post_policy: Uses getPostfilterReceivedNetworks/getPostfilterAdvertisedNetworks
                      APIs to get route counts after policy filtering
                - expected_count: Expected number of routes per peer (optional)
                - min_count: Minimum expected routes per peer (optional)
                - max_count: Maximum expected routes per peer (optional)

        Returns:
            HealthCheckResult: Result of the health check
        """
        hostname = obj.name

        # Extract parameters
        descriptions_to_ignore = check_params.get("descriptions_to_ignore", [])
        descriptions_to_check = check_params.get("descriptions_to_check", [])
        direction = check_params.get("direction", "received")
        policy_type = check_params.get("policy_type", "pre_policy")
        expected_count = check_params.get("expected_count")
        min_count = check_params.get("min_count")
        max_count = check_params.get("max_count")

        # Validate direction and policy_type
        try:
            validate_direction(direction)
        except ValueError as e:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=str(e),
            )

        try:
            validate_policy_type(policy_type)
        except ValueError as e:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=str(e),
            )

        # Convert parameters to appropriate types if they're strings (from JSON)
        try:
            if expected_count is not None:
                expected_count = int(expected_count)
            if min_count is not None:
                min_count = int(min_count)
            if max_count is not None:
                max_count = int(max_count)
        except (ValueError, TypeError) as e:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=f"Invalid count parameter type on {hostname}: {e}",
            )

        self.logger.info(
            f"Running BGP route count verification ({direction}, {policy_type}) on {hostname}"
        )

        try:
            # Get all BGP sessions
            # pyrefly: ignore [missing-attribute]
            bgp_sessions = await self.driver.async_get_bgp_sessions()
            self.logger.info(
                f"Found {len(bgp_sessions)} total BGP sessions on {hostname}"
            )

            # Filter peers based on description and state
            peers_to_check = filter_bgp_sessions(
                bgp_sessions=bgp_sessions,
                descriptions_to_ignore=descriptions_to_ignore,
                descriptions_to_check=descriptions_to_check,
            )

            self.logger.info(
                f"Checking {len(peers_to_check)} peers after filtering on {hostname}"
            )

            # Get route counts for all peers concurrently
            peer_route_counts = await get_route_counts_for_peers(
                peers=peers_to_check,
                direction=direction,
                policy_type=policy_type,
                driver=self.driver,
            )

            # Validate counts for each peer
            results = validate_all_peer_route_counts(
                peer_route_counts=peer_route_counts,
                expected_count=expected_count,
                min_count=min_count,
                max_count=max_count,
                direction=direction,
                policy_type=policy_type,
            )

            # Collect all errors
            validation_errors = []
            for result in results:
                validation_errors.extend(result.errors)

            # Build result message
            if not validation_errors:
                # All peers passed validation
                if expected_count is None and min_count is None and max_count is None:
                    message = f"BGP route count verification on {hostname} ({direction}, {policy_type})"
                else:
                    criteria = []
                    if expected_count is not None:
                        criteria.append(f"expected={expected_count}")
                    if min_count is not None:
                        criteria.append(f"min={min_count}")
                    if max_count is not None:
                        criteria.append(f"max={max_count}")

                    message = (
                        f"BGP route count verification PASSED on {hostname}: "
                        f"all peers meet criteria ({', '.join(criteria)}) ({direction}, {policy_type})"
                    )

                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.PASS,
                    message=message,
                )
            else:
                # Some peers failed validation
                error_summary = "\n  ".join(
                    validation_errors[:10]
                )  # Limit to first 10 errors
                if len(validation_errors) > 10:
                    error_summary += (
                        f"\n  ... and {len(validation_errors) - 10} more errors"
                    )

                message = f"BGP route count verification FAILED on {hostname} ({direction}, {policy_type}):\n  {error_summary}"

                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.FAIL,
                    message=message,
                )

        except Exception as e:
            self.logger.error(f"Failed to verify BGP route counts on {hostname}: {e}")
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=f"Failed to verify BGP route counts on {hostname}: {str(e)}",
            )

    async def _run_arista(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        """
        Verify BGP route counts on ar-bgp (native EOS BGP) devices via EOS CLI.

        ar-bgp has no BGP++ thrift API, so getPrefilterReceivedNetworks() etc.
        are not available. Instead, uses 'show bgp ipv6 unicast summary | json'
        which returns per-peer prefixReceived counts.

        Args:
            obj: Test device
            input: Base health check input
            check_params: Dictionary containing:
                - address_family: "ipv4" or "ipv6" (optional, defaults to "ipv6")
                - expected_count: Expected route count per peer (optional)
                - min_count: Minimum expected routes per peer (optional)
                - max_count: Maximum expected routes per peer (optional)
                - descriptions_to_check: List of peer descriptions to filter on (optional)
                - descriptions_to_ignore: List of peer descriptions to ignore (optional)
        """
        hostname = obj.name
        address_family = check_params.get("address_family", "ipv6")
        expected_count = check_params.get("expected_count")
        min_count = check_params.get("min_count")
        max_count = check_params.get("max_count")
        descriptions_to_check = check_params.get("descriptions_to_check", [])
        descriptions_to_ignore = check_params.get("descriptions_to_ignore", [])

        try:
            if expected_count is not None:
                expected_count = int(expected_count)
            if min_count is not None:
                min_count = int(min_count)
            if max_count is not None:
                max_count = int(max_count)
        except (ValueError, TypeError) as e:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=f"Invalid count parameter on {hostname}: {e}",
            )

        self.logger.info(
            f"Running ar-bgp route count verification ({address_family}) on {hostname}"
        )

        try:
            if address_family == "ipv4":
                cmd = "show bgp ipv4 unicast summary | json"
            else:
                cmd = "show bgp ipv6 unicast summary | json"

            # pyrefly: ignore [missing-attribute]
            result = await self.driver.async_execute_show_json_on_shell(cmd)
            peers = result.get("vrfs", {}).get("default", {}).get("peers", {})

            if not peers:
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.FAIL,
                    message=f"No BGP peers found on {hostname} for {address_family}",
                )

            # Filter peers by description
            filtered_peers = {}
            for peer_ip, peer_info in peers.items():
                desc = peer_info.get("description", "")
                if descriptions_to_ignore and any(
                    ignore in desc for ignore in descriptions_to_ignore
                ):
                    continue
                if descriptions_to_check and not any(
                    check in desc for check in descriptions_to_check
                ):
                    continue
                filtered_peers[peer_ip] = peer_info

            if not filtered_peers:
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.FAIL,
                    message=(
                        f"No peers matched filter on {hostname}. "
                        f"descriptions_to_check={descriptions_to_check}"
                    ),
                )

            # Check route counts per peer
            errors = []
            for peer_ip, peer_info in filtered_peers.items():
                state = peer_info.get("peerState", "Unknown")
                if state != "Established":
                    errors.append(f"Peer {peer_ip} not Established (state={state})")
                    continue

                prefix_received = peer_info.get("prefixReceived", 0)
                desc = peer_info.get("description", peer_ip)

                if expected_count is not None and prefix_received != expected_count:
                    errors.append(
                        f"Peer {peer_ip} ({desc}): got {prefix_received} routes, "
                        f"expected {expected_count}"
                    )
                if min_count is not None and prefix_received < min_count:
                    errors.append(
                        f"Peer {peer_ip} ({desc}): got {prefix_received} routes, "
                        f"min expected {min_count}"
                    )
                if max_count is not None and prefix_received > max_count:
                    errors.append(
                        f"Peer {peer_ip} ({desc}): got {prefix_received} routes, "
                        f"max expected {max_count}"
                    )

                self.logger.info(
                    f"Peer {peer_ip} ({desc}): {prefix_received} routes received"
                )

            if errors:
                error_summary = "\n  ".join(errors[:10])
                if len(errors) > 10:
                    error_summary += f"\n  ... and {len(errors) - 10} more errors"
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.FAIL,
                    message=(
                        f"ar-bgp route count verification FAILED on {hostname} "
                        f"({address_family}):\n  {error_summary}"
                    ),
                )

            criteria = []
            if expected_count is not None:
                criteria.append(f"expected={expected_count}")
            if min_count is not None:
                criteria.append(f"min={min_count}")
            if max_count is not None:
                criteria.append(f"max={max_count}")

            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.PASS,
                message=(
                    f"ar-bgp route count verification PASSED on {hostname}: "
                    f"{len(filtered_peers)} peers checked ({address_family})"
                    + (f", criteria: {', '.join(criteria)}" if criteria else "")
                ),
            )

        except Exception as e:
            # If native EOS BGP is inactive, this is likely an ARISTA_FBOSS
            # device running BGP++ instead of native EOS BGP. Fall back to
            # the Thrift-based check which queries BGP++ directly.
            if "BGP inactive" in str(e):
                self.logger.info(
                    f"Native EOS BGP is inactive on {hostname}, "
                    f"falling back to BGP++ Thrift-based route count check"
                )
                return await self._run(obj, input, check_params)
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.ERROR,
                message=f"Error verifying ar-bgp route counts on {hostname}: {e}",
            )
