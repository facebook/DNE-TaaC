# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe
import typing as t

from taac.constants import TestDevice
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
)
from taac.utils.health_check_utils import (
    ip_ntop,
    is_parent_prefix,
)
from taac.health_check.health_check import types as hc_types


class BgpMultipathNextHopCountHealthCheck(
    AbstractDeviceHealthCheck[hc_types.BaseHealthCheckIn]
):
    """
    Health check to verify BGP multipath group (next-hop count) for prefixes.

    This check queries the BGP++ RIB and validates that prefixes have the expected
    number of next-hops in their multipath group. This is essential for verifying
    that BGP session oscillations correctly affect the multipath group size.

    Supports two modes:
        1. Discovery mode (discover_baseline=True): Queries the BGP RIB and discovers
           all prefixes that have the expected baseline next-hop count. The discovered
           prefixes are stored in the test context for use in subsequent validation.
        2. Validation mode (default): Validates that prefixes have the expected
           number of next-hops.

    Supports:
        - Exact next-hop count validation
        - Minimum next-hop count validation
        - Maximum next-hop count validation
        - Range-based validation (min and max)

    check_params:
        - discover_baseline: If True, discover prefixes with baseline_nexthop_count and store them
        - baseline_nexthop_count: Expected next-hop count for baseline discovery
        - prefix_subnets: Optional list of prefix subnets to check (e.g., ["10.0.0.0/8", "2001:db8::/32"])
        - parent_prefixes_to_ignore: Optional list of parent prefixes to ignore
        - expected_nexthop_count: Optional exact number of next-hops expected
        - min_nexthop_count: Optional minimum number of next-hops expected
        - max_nexthop_count: Optional maximum number of next-hops expected
        - sample_size: Optional number of prefixes to sample for validation (default: 10)
        - ebgp_only: If True, only consider eBGP routes (routes with non-empty AS_PATH). Default: True for discovery mode.
    """

    # TODO: Change to BGP_MULTIPATH_NEXT_HOP_COUNT_CHECK once thrift enum lands
    CHECK_NAME = hc_types.CheckName.NEXT_HOP_COUNT_CHECK
    OPERATING_SYSTEMS = ["EOS"]

    # Class-level storage for discovered baseline prefixes
    # This allows sharing discovered prefixes across health check instances
    _discovered_baseline_prefixes: t.ClassVar[t.Set[str]] = set()

    async def _run(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        """
        Run the BGP multipath next-hop count check for Arista devices.

        Args:
            obj: Test device
            input: Base health check input
            check_params: Dictionary containing:
                - discover_baseline: If True, discover and store prefixes with baseline next-hop count
                - baseline_nexthop_count: Expected next-hop count for baseline discovery
                - prefix_subnets: Optional list of prefix subnets to check
                - parent_prefixes_to_ignore: Optional list of parent prefixes to ignore
                - expected_nexthop_count: Optional exact next-hop count
                - min_nexthop_count: Optional minimum next-hop count
                - max_nexthop_count: Optional maximum next-hop count
                - sample_size: Number of prefixes to sample (default: 10)

        Returns:
            HealthCheckResult: Result of the health check
        """
        self.logger.debug(
            f"Executing BGP multipath next-hop count check on {obj.name}."
        )

        discover_baseline = check_params.get("discover_baseline", False)
        baseline_nexthop_count = check_params.get("baseline_nexthop_count")

        if discover_baseline:
            return await self._run_discovery_mode(
                obj, check_params, baseline_nexthop_count
            )
        else:
            return await self._run_validation_mode(obj, check_params)

    async def _run_discovery_mode(
        self,
        obj: TestDevice,
        check_params: t.Dict[str, t.Any],
        baseline_nexthop_count: int | None,
    ) -> hc_types.HealthCheckResult:
        """
        Discovery mode: Find prefixes with the expected baseline next-hop count
        and store them for later validation.

        Only considers eBGP routes (routes with non-empty AS_PATH) by default
        to avoid including iBGP or self-originated routes.
        """
        if baseline_nexthop_count is None:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.ERROR,
                message="baseline_nexthop_count is required when discover_baseline=True",
            )

        parent_prefixes_to_ignore = check_params.get("parent_prefixes_to_ignore", [])
        # Default to True for discovery mode - only consider eBGP routes
        ebgp_only = check_params.get("ebgp_only", True)

        try:
            # Get BGP++ RIB entries
            bgp_rib_entries = await self.driver.async_get_bgp_rib_entries()
            self.logger.debug(f"Retrieved {len(bgp_rib_entries)} BGP++ RIB entries")

            # Get self-originated prefixes to exclude
            bgp_originated_routes = await self.driver.async_get_bgp_originated_routes()
            bgp_originated_prefixes = {
                f"{ip_ntop(originated_route.prefix.prefix_bin)}/{originated_route.prefix.num_bits}"
                for originated_route in bgp_originated_routes
            }

            # Find prefixes with the baseline next-hop count
            discovered_prefixes = set()
            skipped_ibgp_count = 0
            skipped_originated_count = 0
            nexthop_count_distribution: t.Dict[int, int] = {}
            sample_entries_logged = 0
            path_structure_logged = False

            for entry in bgp_rib_entries:
                ip_str = ip_ntop(entry.prefix.prefix_bin)
                prefix_str = f"{ip_str}/{entry.prefix.num_bits}"

                # Skip self-originated prefixes
                if prefix_str in bgp_originated_prefixes:
                    skipped_originated_count += 1
                    continue

                # Skip parent prefixes to ignore
                if any(
                    is_parent_prefix(ip_str, parent_prefix)
                    for parent_prefix in parent_prefixes_to_ignore
                ):
                    continue

                # Log the path structure once for debugging
                if not path_structure_logged:
                    self._log_path_structure_for_debugging(entry)
                    path_structure_logged = True

                # If ebgp_only is True, skip routes without AS_PATH (iBGP or local routes)
                if ebgp_only and not self._is_ebgp_route(entry):
                    skipped_ibgp_count += 1
                    continue

                # Count next-hops from best group
                nexthop_count = self._count_nexthops(entry)

                # Track next-hop count distribution for debugging
                nexthop_count_distribution[nexthop_count] = (
                    nexthop_count_distribution.get(nexthop_count, 0) + 1
                )

                # Log a few sample entries for debugging
                if sample_entries_logged < 5:
                    self.logger.debug(
                        f"Sample eBGP prefix: {prefix_str}, nexthop_count={nexthop_count}"
                    )
                    sample_entries_logged += 1

                # If this prefix has the baseline next-hop count, add it
                if nexthop_count == baseline_nexthop_count:
                    discovered_prefixes.add(prefix_str)

            # Log next-hop count distribution for debugging
            self.logger.info(
                f"Next-hop count distribution (eBGP only={ebgp_only}): {dict(sorted(nexthop_count_distribution.items()))}"
            )
            self.logger.info(
                f"Skipped: {skipped_originated_count} originated, {skipped_ibgp_count} iBGP/local routes"
            )

            if not discovered_prefixes:
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.FAIL,
                    message=f"No prefixes found with {baseline_nexthop_count} next-hops in BGP RIB (skipped {skipped_ibgp_count} iBGP/local routes)",
                )

            # Store discovered prefixes for later use
            BgpMultipathNextHopCountHealthCheck._discovered_baseline_prefixes = (
                discovered_prefixes
            )

            success_message = (
                f"BGP multipath baseline discovery PASSED.\n"
                f"  - Discovered {len(discovered_prefixes)} eBGP prefixes with {baseline_nexthop_count} next-hops\n"
                f"  - Skipped {skipped_ibgp_count} iBGP/local routes\n"
                f"  - Sample prefixes: {list(discovered_prefixes)[:5]}"
            )
            self.logger.info(success_message)
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.PASS,
                message=success_message,
            )

        except Exception as e:
            error_message = f"Error during BGP multipath baseline discovery: {str(e)}"
            self.logger.error(error_message)
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.ERROR,
                message=error_message,
            )

    async def _run_validation_mode(
        self,
        obj: TestDevice,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        """
        Validation mode: Check that prefixes have the expected next-hop count.
        Uses discovered baseline prefixes if available, otherwise uses prefix_subnets.
        """
        prefix_subnets = check_params.get("prefix_subnets", [])
        parent_prefixes_to_ignore = check_params.get("parent_prefixes_to_ignore", [])
        expected_nexthop_count = check_params.get("expected_nexthop_count")
        min_nexthop_count = check_params.get("min_nexthop_count")
        max_nexthop_count = check_params.get("max_nexthop_count")
        sample_size = check_params.get("sample_size", 10)
        use_discovered_prefixes = check_params.get("use_discovered_prefixes", False)

        # Get discovered prefixes if requested
        discovered_prefixes = None
        if use_discovered_prefixes:
            discovered_prefixes = (
                BgpMultipathNextHopCountHealthCheck._discovered_baseline_prefixes
            )
            if not discovered_prefixes:
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.SKIP,
                    message="Skipping validation: no baseline prefixes have been discovered. Discovery step should have reported the failure.",
                )
            self.logger.debug(
                f"Using {len(discovered_prefixes)} discovered baseline prefixes"
            )

        # Validate that at least one validation criterion is provided
        if (
            expected_nexthop_count is None
            and min_nexthop_count is None
            and max_nexthop_count is None
        ):
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.ERROR,
                message="At least one of expected_nexthop_count, min_nexthop_count, or max_nexthop_count must be provided",
            )

        try:
            # Get BGP++ RIB entries
            bgp_rib_entries = await self.driver.async_get_bgp_rib_entries()
            self.logger.debug(f"Retrieved {len(bgp_rib_entries)} BGP++ RIB entries")

            # Get self-originated prefixes to exclude
            bgp_originated_routes = await self.driver.async_get_bgp_originated_routes()
            bgp_originated_prefixes = {
                f"{ip_ntop(originated_route.prefix.prefix_bin)}/{originated_route.prefix.num_bits}"
                for originated_route in bgp_originated_routes
            }

            # Process BGP RIB entries and extract next-hop counts
            prefix_nexthop_counts = {}
            for entry in bgp_rib_entries:
                ip_str = ip_ntop(entry.prefix.prefix_bin)
                prefix_str = f"{ip_str}/{entry.prefix.num_bits}"

                # Skip self-originated prefixes
                if prefix_str in bgp_originated_prefixes:
                    continue

                # Skip parent prefixes to ignore
                if any(
                    is_parent_prefix(ip_str, parent_prefix)
                    for parent_prefix in parent_prefixes_to_ignore
                ):
                    continue

                # If using discovered prefixes, only check those
                if discovered_prefixes is not None:
                    if prefix_str not in discovered_prefixes:
                        continue
                # Otherwise, filter by specific prefix subnets if provided
                elif prefix_subnets and not self._matches_prefix_subnets(
                    ip_str, prefix_subnets
                ):
                    continue

                # Count next-hops
                nexthop_count = self._count_nexthops(entry)
                prefix_nexthop_counts[prefix_str] = nexthop_count

            if not prefix_nexthop_counts:
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.FAIL,
                    message="No matching prefixes found in BGP RIB",
                )

            # Validate next-hop counts
            failures = []
            validated_count = 0
            sample_results = []

            for prefix, nexthop_count in prefix_nexthop_counts.items():
                is_valid = True
                failure_reason = None

                if expected_nexthop_count is not None:
                    if nexthop_count != expected_nexthop_count:
                        is_valid = False
                        failure_reason = f"expected exactly {expected_nexthop_count}, got {nexthop_count}"

                if min_nexthop_count is not None and is_valid:
                    if nexthop_count < min_nexthop_count:
                        is_valid = False
                        failure_reason = f"expected at least {min_nexthop_count}, got {nexthop_count}"

                if max_nexthop_count is not None and is_valid:
                    if nexthop_count > max_nexthop_count:
                        is_valid = False
                        failure_reason = (
                            f"expected at most {max_nexthop_count}, got {nexthop_count}"
                        )

                if is_valid:
                    validated_count += 1
                else:
                    failures.append({"prefix": prefix, "reason": failure_reason})

                # Collect sample results for logging
                if len(sample_results) < sample_size:
                    sample_results.append(
                        {
                            "prefix": prefix,
                            "nexthop_count": nexthop_count,
                            "valid": is_valid,
                        }
                    )

            total_checked = len(prefix_nexthop_counts)

            if failures:
                # Limit number of failures to report
                failure_sample = failures[:10]
                error_details = "\n".join(
                    f"  - {f['prefix']}: {f['reason']}" for f in failure_sample
                )
                error_message = (
                    f"BGP multipath next-hop count check FAILED.\n"
                    f"  - Total prefixes checked: {total_checked}\n"
                    f"  - Failures: {len(failures)}\n"
                    f"  - Sample failures (first 10):\n{error_details}"
                )
                self.logger.error(error_message)
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.FAIL,
                    message=error_message,
                )

            # Build success message
            criteria = []
            if expected_nexthop_count is not None:
                criteria.append(f"exactly {expected_nexthop_count}")
            if min_nexthop_count is not None:
                criteria.append(f"at least {min_nexthop_count}")
            if max_nexthop_count is not None:
                criteria.append(f"at most {max_nexthop_count}")

            success_message = (
                f"BGP multipath next-hop count check PASSED.\n"
                f"  - Total prefixes checked: {total_checked}\n"
                f"  - All prefixes have {' and '.join(criteria)} next-hops"
            )
            self.logger.info(success_message)
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.PASS,
                message=success_message,
            )

        except Exception as e:
            error_message = f"Error during BGP multipath next-hop count check: {str(e)}"
            self.logger.error(error_message)
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.ERROR,
                message=error_message,
            )

    def _count_nexthops(self, entry: t.Any) -> int:
        """Extract next-hop count from a BGP RIB entry's best group."""
        next_hops = []
        if hasattr(entry, "paths") and entry.paths and hasattr(entry, "best_group"):
            best_group = entry.best_group
            if best_group and best_group in entry.paths:
                for path in entry.paths[best_group]:
                    if hasattr(path, "next_hop") and path.next_hop:
                        next_hops.append(ip_ntop(path.next_hop.prefix_bin))
        return len(next_hops)

    def _is_ebgp_route(self, entry: t.Any) -> bool:
        """
        Check if a BGP RIB entry is an eBGP route.

        eBGP routes have a non-empty AS_PATH because the first AS in the path
        is the neighbor's AS. iBGP routes from the same AS may have an empty
        AS_PATH or only contain our own AS.

        Returns:
            True if any path in the best group has a non-empty AS_PATH (eBGP route),
            False otherwise (iBGP or local route).
        """
        if not hasattr(entry, "paths") or not entry.paths:
            return False

        if not hasattr(entry, "best_group") or not entry.best_group:
            return False

        best_group = entry.best_group
        if best_group not in entry.paths:
            return False

        # Check if any path in the best group has a non-empty AS_PATH
        for path in entry.paths[best_group]:
            # Try different attribute names that BGP++ might use for AS_PATH
            # Common variants: as_path, asPath, as_path_segments, aspath
            as_path_value = None
            for attr_name in ["as_path", "asPath", "as_path_segments", "aspath"]:
                if hasattr(path, attr_name):
                    as_path_value = getattr(path, attr_name)
                    if as_path_value:
                        return True

            # Also check for path_attributes dict-style access
            if hasattr(path, "path_attributes") and path.path_attributes:
                attrs = path.path_attributes
                for key in [
                    "as_path",
                    "asPath",
                    "AS_PATH",
                    "2",
                ]:  # 2 is AS_PATH type code
                    if key in attrs and attrs[key]:
                        return True

        return False

    def _matches_prefix_subnets(self, ip_str: str, prefix_subnets: t.List[str]) -> bool:
        """Check if IP address matches any of the specified prefix subnets"""
        import ipaddress

        try:
            ip_addr = ipaddress.ip_address(ip_str)
            for subnet_str in prefix_subnets:
                try:
                    subnet = ipaddress.ip_network(subnet_str, strict=False)
                    if ip_addr in subnet:
                        return True
                except ValueError:
                    continue
            return False
        except ValueError:
            return False

    def _log_path_structure_for_debugging(self, entry: t.Any) -> None:
        """
        Log the structure of a BGP RIB entry for debugging purposes.
        This helps identify the correct attribute names for AS_PATH and other fields.
        """
        try:
            prefix_str = "unknown"
            try:
                ip_str = ip_ntop(entry.prefix.prefix_bin)
                prefix_str = f"{ip_str}/{entry.prefix.num_bits}"
            except Exception:
                pass

            self.logger.info(f"[DEBUG] Sample RIB entry structure for {prefix_str}:")

            # Log entry-level attributes
            try:
                entry_attrs = [attr for attr in dir(entry) if not attr.startswith("_")]
                self.logger.info(
                    f"[DEBUG] Entry attributes: {entry_attrs[:20]}"
                )  # Limit to first 20
            except Exception as e:
                self.logger.info(f"[DEBUG] Could not get entry attributes: {e}")

            if hasattr(entry, "paths") and entry.paths:
                try:
                    self.logger.info(
                        f"[DEBUG] paths keys: {list(entry.paths.keys())[:5]}"
                    )  # Limit to first 5
                except Exception as e:
                    self.logger.info(f"[DEBUG] Could not get paths keys: {e}")

                if hasattr(entry, "best_group") and entry.best_group:
                    best_group = entry.best_group
                    self.logger.info(f"[DEBUG] best_group: {best_group}")

                    if best_group in entry.paths:
                        try:
                            paths = entry.paths[best_group]
                            self.logger.info(
                                f"[DEBUG] Number of paths in best_group: {len(paths)}"
                            )

                            if paths:
                                first_path = paths[0]
                                try:
                                    path_attrs = [
                                        attr
                                        for attr in dir(first_path)
                                        if not attr.startswith("_")
                                    ]
                                    self.logger.info(
                                        f"[DEBUG] First path attributes: {path_attrs[:30]}"  # Limit to first 30
                                    )
                                except Exception as e:
                                    self.logger.info(
                                        f"[DEBUG] Could not get path attributes: {e}"
                                    )

                                # Log specific AS_PATH related attributes
                                for attr_name in [
                                    "as_path",
                                    "asPath",
                                    "as_path_segments",
                                    "aspath",
                                    "path_attributes",
                                    "peer_as",
                                    "source_as",
                                ]:
                                    try:
                                        if hasattr(first_path, attr_name):
                                            attr_value = getattr(first_path, attr_name)
                                            # Truncate long values
                                            str_value = str(attr_value)[:200]
                                            self.logger.info(
                                                f"[DEBUG] {attr_name} = {str_value} (type: {type(attr_value).__name__})"
                                            )
                                    except Exception as e:
                                        self.logger.info(
                                            f"[DEBUG] Error reading {attr_name}: {e}"
                                        )
                        except Exception as e:
                            self.logger.info(f"[DEBUG] Error accessing paths: {e}")
        except Exception as e:
            self.logger.warning(f"[DEBUG] Error logging path structure: {e}")
