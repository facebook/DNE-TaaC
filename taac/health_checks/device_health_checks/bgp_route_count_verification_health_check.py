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
from collections import Counter

from taac.constants import TestDevice
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
)
from taac.utils.bgp_route_count_utils import (
    filter_bgp_sessions,
    get_route_count_histogram_by_afi_for_peers,
    get_route_counts_for_peers,
    normalize_expected_count_histogram_by_afi,
    select_peer_addresses_by_exact_config_peer_group,
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

    @staticmethod
    def _validate_peer_selectors(
        descriptions_to_ignore: t.Sequence[str],
        descriptions_to_check: t.Sequence[str],
        exact_peer_group_names: t.Sequence[str],
    ) -> None:
        if exact_peer_group_names and (descriptions_to_ignore or descriptions_to_check):
            raise ValueError(
                "description filters and exact_peer_group_names are mutually exclusive"
            )

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
                - exact_peer_group_names: Exact BGP peer-group names to check (optional)
                - direction: "received" or "advertised" (optional, defaults to "received")
                - policy_type: "pre_policy" or "post_policy" (optional, defaults to "pre_policy")
                    - pre_policy: Uses getPrefilterReceivedNetworks/getPrefilterAdvertisedNetworks
                      APIs to get route counts before policy filtering
                    - post_policy: Uses getPostfilterReceivedNetworks/getPostfilterAdvertisedNetworks
                      APIs to get route counts after policy filtering
                - expected_count: Expected number of routes per peer (optional)
                - expected_count_histogram_by_afi: Exact route-count distribution
                  for each selected address family (optional)
                - min_count: Minimum expected routes per peer (optional)
                - max_count: Maximum expected routes per peer (optional)

        Returns:
            HealthCheckResult: Result of the health check
        """
        hostname = obj.name

        # Extract parameters
        descriptions_to_ignore = check_params.get("descriptions_to_ignore", [])
        descriptions_to_check = check_params.get("descriptions_to_check", [])
        exact_peer_group_names = check_params.get("exact_peer_group_names", [])
        direction = check_params.get("direction", "received")
        policy_type = check_params.get("policy_type", "pre_policy")
        expected_count = check_params.get("expected_count")
        expected_count_histogram_by_afi = None
        min_count = check_params.get("min_count")
        max_count = check_params.get("max_count")

        try:
            self._validate_peer_selectors(
                descriptions_to_ignore,
                descriptions_to_check,
                exact_peer_group_names,
            )
            validate_direction(direction)
            validate_policy_type(policy_type)
            expected_count_histogram_by_afi = normalize_expected_count_histogram_by_afi(
                check_params.get("expected_count_histogram_by_afi")
            )
            if expected_count_histogram_by_afi is not None and any(
                value is not None for value in (expected_count, min_count, max_count)
            ):
                raise ValueError(
                    "expected_count_histogram_by_afi is mutually exclusive with "
                    "expected_count, min_count, and max_count"
                )
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
            peer_addresses_to_check = await self._resolve_peer_group_addresses(
                hostname,
                exact_peer_group_names,
            )

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
                peer_addresses_to_check=peer_addresses_to_check,
            )
            if peer_addresses_to_check is not None and not peers_to_check:
                raise RuntimeError(
                    "No established peers matched the selected exact peer groups"
                )

            self.logger.info(
                f"Checking {len(peers_to_check)} peers after filtering on {hostname}"
            )

            validation_errors: list[str] = []
            if expected_count_histogram_by_afi is not None:
                try:
                    # The transport peer address is not the route AFI in
                    # MP-BGP.  Use negotiated-family counters from detailed
                    # neighbor state so crossed and dual-stack sessions are
                    # attributed to their actual NLRI families.
                    # pyrefly: ignore [missing-attribute]
                    bgp_helper = await self.driver.bgp()
                    actual_histogram = await get_route_count_histogram_by_afi_for_peers(
                        peers=peers_to_check,
                        afis=expected_count_histogram_by_afi,
                        direction=direction,
                        policy_type=policy_type,
                        bgp_helper=bgp_helper,
                    )
                except Exception as error:
                    return hc_types.HealthCheckResult(
                        status=hc_types.HealthCheckStatus.ERROR,
                        message=(
                            "Could not collect authoritative route-count histogram "
                            f"by AFI on {hostname} ({direction}, {policy_type}): "
                            f"{type(error).__name__}: {error}"
                        ),
                    )
                if actual_histogram != expected_count_histogram_by_afi:
                    validation_errors.append(
                        "Expected route-count histogram by AFI "
                        f"{expected_count_histogram_by_afi}, got "
                        f"{actual_histogram} ({direction}, {policy_type})"
                    )
            else:
                # Scalar verification preserves the existing per-peer network
                # query path and its legacy failure semantics.
                peer_route_counts = await get_route_counts_for_peers(
                    peers=peers_to_check,
                    direction=direction,
                    policy_type=policy_type,
                    driver=self.driver,
                )
                results = validate_all_peer_route_counts(
                    peer_route_counts=peer_route_counts,
                    expected_count=expected_count,
                    min_count=min_count,
                    max_count=max_count,
                    direction=direction,
                    policy_type=policy_type,
                )
                for result in results:
                    validation_errors.extend(result.errors)

            # Build result message
            if not validation_errors:
                # All peers passed validation
                if expected_count_histogram_by_afi is not None:
                    message = (
                        f"BGP route count verification PASSED on {hostname}: "
                        "exact per-AFI histogram "
                        f"{expected_count_histogram_by_afi} "
                        f"({direction}, {policy_type})"
                    )
                elif expected_count is None and min_count is None and max_count is None:
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

    async def _resolve_peer_group_addresses(
        self,
        hostname: str,
        exact_peer_group_names: t.Sequence[str],
    ) -> t.Optional[t.Set[str]]:
        if not exact_peer_group_names:
            return None

        # pyrefly: ignore [missing-attribute]
        bgp_helper = await self.driver.bgp()
        bgp_config = await bgp_helper.async_get_running_config_struct()
        selected, observed = select_peer_addresses_by_exact_config_peer_group(
            bgp_config,
            exact_peer_group_names,
        )
        missing = set(exact_peer_group_names) - observed
        if missing or not selected:
            raise RuntimeError(
                f"Exact BGP peer-group selection failed on {hostname}: "
                f"requested={sorted(set(exact_peer_group_names))}, "
                f"missing={sorted(missing)}, observed={sorted(observed)}, "
                f"selected_peers={len(selected)}, "
                f"configured_peers={len(getattr(bgp_config, 'peers', None) or [])}"
            )
        return selected

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
                - expected_count_histogram_by_afi: Exact route-count distribution
                  for each selected address family (optional)
                - min_count: Minimum expected routes per peer (optional)
                - max_count: Maximum expected routes per peer (optional)
                - descriptions_to_check: List of peer descriptions to filter on (optional)
                - descriptions_to_ignore: List of peer descriptions to ignore (optional)
                - exact_peer_group_names: Exact BGP peer-group names to check (optional)
        """
        hostname = obj.name
        address_family = check_params.get("address_family", "ipv6")
        expected_count = check_params.get("expected_count")
        expected_count_histogram_by_afi = None
        min_count = check_params.get("min_count")
        max_count = check_params.get("max_count")
        descriptions_to_check = check_params.get("descriptions_to_check", [])
        descriptions_to_ignore = check_params.get("descriptions_to_ignore", [])
        exact_peer_group_names = check_params.get("exact_peer_group_names", [])

        try:
            self._validate_peer_selectors(
                descriptions_to_ignore,
                descriptions_to_check,
                exact_peer_group_names,
            )
            expected_count_histogram_by_afi = normalize_expected_count_histogram_by_afi(
                check_params.get("expected_count_histogram_by_afi")
            )
            if expected_count_histogram_by_afi is not None and any(
                value is not None for value in (expected_count, min_count, max_count)
            ):
                raise ValueError(
                    "expected_count_histogram_by_afi is mutually exclusive with "
                    "expected_count, min_count, and max_count"
                )
            if expected_count_histogram_by_afi is None and address_family not in {
                "ipv4",
                "ipv6",
            }:
                raise ValueError(f"unsupported address_family {address_family!r}")
        except ValueError as e:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=f"Invalid peer selector on {hostname}: {e}",
            )

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
                message=f"Invalid route-count parameters on {hostname}: {e}",
            )

        address_families = (
            tuple(expected_count_histogram_by_afi)
            if expected_count_histogram_by_afi is not None
            else (address_family,)
        )
        self.logger.info(
            "Running ar-bgp route count verification "
            f"({', '.join(address_families)}) on {hostname}"
        )

        try:
            errors: list[str] = []
            runtime_errors: list[str] = []
            runtime_error_afis: set[str] = set()
            filter_miss_afis: set[str] = set()
            peers_by_afi: dict[str, t.Mapping[str, t.Any]] = {}
            for afi in address_families:
                cmd = f"show bgp {afi} unicast summary | json"
                # pyrefly: ignore [missing-attribute]
                result = await self.driver.async_execute_show_json_on_shell(cmd)
                peers = result.get("vrfs", {}).get("default", {}).get("peers", {})
                if not peers:
                    runtime_errors.append(f"No BGP peers found on {hostname} for {afi}")
                    runtime_error_afis.add(afi)
                    continue
                peers_by_afi[afi] = peers

            peer_addresses_to_check = await self._resolve_peer_group_addresses(
                hostname,
                exact_peer_group_names,
            )
            peer_route_counts_by_afi: dict[str, dict[str, int]] = {
                afi: {} for afi in address_families
            }
            checked_peer_addresses: set[str] = set()
            for afi, peers in peers_by_afi.items():
                filtered_peers = {
                    peer_ip: peer_info
                    for peer_ip, peer_info in peers.items()
                    if (
                        peer_addresses_to_check is None
                        or peer_ip in peer_addresses_to_check
                    )
                    and not (
                        descriptions_to_ignore
                        and any(
                            ignore in peer_info.get("description", "")
                            for ignore in descriptions_to_ignore
                        )
                    )
                    and not (
                        descriptions_to_check
                        and not any(
                            check in peer_info.get("description", "")
                            for check in descriptions_to_check
                        )
                    )
                }
                if peer_addresses_to_check is not None and not filtered_peers:
                    runtime_errors.append(
                        "No established peers matched the selected exact peer groups "
                        f"for {afi}"
                    )
                    runtime_error_afis.add(afi)
                    continue
                if not filtered_peers:
                    errors.append(
                        (
                            f"No peers matched filter on {hostname} for {afi}. "
                            f"descriptions_to_check={descriptions_to_check}, "
                            f"exact_peer_group_names={exact_peer_group_names}"
                        )
                    )
                    filter_miss_afis.add(afi)
                    continue

                for peer_ip, peer_info in filtered_peers.items():
                    state = peer_info.get("peerState", "Unknown")
                    if state != "Established":
                        errors.append(f"Peer {peer_ip} not Established (state={state})")
                        continue

                    if "prefixReceived" not in peer_info:
                        # Preserve the legacy EOS behavior for an omitted
                        # field, while requiring present device evidence to
                        # already have the exact JSON integer type.
                        prefix_received = 0
                    else:
                        raw_prefix_received = peer_info["prefixReceived"]
                        if (
                            type(raw_prefix_received) is not int
                            or raw_prefix_received < 0
                        ):
                            runtime_errors.append(
                                f"Peer {peer_ip} for {afi}: invalid prefixReceived "
                                f"value {raw_prefix_received!r}"
                            )
                            runtime_error_afis.add(afi)
                            continue
                        prefix_received = raw_prefix_received
                    checked_peer_addresses.add(peer_ip)
                    peer_route_counts_by_afi[afi][peer_ip] = prefix_received
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

            if expected_count_histogram_by_afi is not None:
                for afi, expected_histogram in expected_count_histogram_by_afi.items():
                    if afi in runtime_error_afis or afi in filter_miss_afis:
                        continue
                    peer_counts = peer_route_counts_by_afi.get(afi, {})
                    actual_histogram = dict(
                        sorted(Counter(peer_counts.values()).items())
                    )
                    if actual_histogram != expected_histogram:
                        errors.append(
                            f"Expected route-count histogram for {afi} "
                            f"{expected_histogram}, got {actual_histogram}"
                        )

            if runtime_errors:
                # Malformed device output and exact-selector misses make the
                # observation operationally untrustworthy. Continue all
                # peers/AFIs first so validation mismatches remain available
                # as context, but preserve ERROR precedence over FAIL.
                all_errors = [*runtime_errors, *errors]
                error_summary = "\n  ".join(all_errors[:10])
                if len(all_errors) > 10:
                    error_summary += f"\n  ... and {len(all_errors) - 10} more errors"
                raise RuntimeError(error_summary)

            if errors:
                error_summary = "\n  ".join(errors[:10])
                if len(errors) > 10:
                    error_summary += f"\n  ... and {len(errors) - 10} more errors"
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.FAIL,
                    message=(
                        f"ar-bgp route count verification FAILED on {hostname} "
                        f"({', '.join(address_families)}):\n  {error_summary}"
                    ),
                )

            criteria = []
            if expected_count is not None:
                criteria.append(f"expected={expected_count}")
            if min_count is not None:
                criteria.append(f"min={min_count}")
            if max_count is not None:
                criteria.append(f"max={max_count}")
            if expected_count_histogram_by_afi is not None:
                criteria.append(
                    f"expected_count_histogram_by_afi={expected_count_histogram_by_afi}"
                )

            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.PASS,
                message=(
                    f"ar-bgp route count verification PASSED on {hostname}: "
                    f"{len(checked_peer_addresses)} peers checked "
                    f"({', '.join(address_families)})"
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
