# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

import typing as t

from taac.constants import TestDevice
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
)
from taac.utils.health_check_utils import ip_ntop
from taac.health_check.health_check import types as hc_types


class BgpStaleRouteHealthCheck(AbstractDeviceHealthCheck[hc_types.BaseHealthCheckIn]):
    """
    Health check to detect stale BGP routes (prefixes with zero paths).

    This check examines the BGP RIB (Routing Information Base) to identify
    prefixes that have no available paths, which indicates stale routes.
    Such routes should be cleaned up or investigated as they may indicate
    BGP session issues or route convergence problems.
    """

    CHECK_NAME = hc_types.CheckName.BGP_STALE_ROUTE_CHECK
    OPERATING_SYSTEMS = [
        "FBOSS",
        "EOS",
    ]
    LOG_TO_SCUBA = True

    def _has_valid_paths(self, rib_entry) -> bool:
        """Check if a RIB entry has valid paths."""
        if not rib_entry.paths:
            return False

        # Check if any group has non-empty path list
        for _group_name, path_list in rib_entry.paths.items():
            if path_list:
                return True
        return False

    def _create_failure_message(
        self, stale_prefixes: t.List[t.Dict[str, t.Any]], hostname: str, verbose: bool
    ) -> str:
        """Create detailed failure message for stale routes."""
        stale_prefix_list = [info["prefix"] for info in stale_prefixes]

        failure_message = (
            f"Found {len(stale_prefixes)} stale BGP routes (prefixes with zero paths) on {hostname}:\n"
            f"Stale prefixes: {', '.join(stale_prefix_list[:10])}"  # Limit to first 10 for readability
        )

        if len(stale_prefixes) > 10:
            failure_message += f" (and {len(stale_prefixes) - 10} more)"

        failure_message += "\n\nThis indicates potential BGP convergence issues or stale routes that need cleanup."

        if verbose:
            failure_message += "\n\nDetailed stale route information logged above."

        return failure_message

    async def _run(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        """
        Check for stale BGP routes (prefixes with zero paths).

        Args:
            obj: Test device to check
            input: Base health check input (required by interface)
            check_params: Dictionary containing optional parameters:
                - verbose: Optional boolean to enable detailed logging

        Returns:
            HealthCheckResult: PASS if no stale routes found, FAIL otherwise
        """
        hostname = obj.name
        verbose = check_params.get("verbose", False)

        self.logger.info(
            f"Starting BGP stale route health check for device: {hostname}"
        )

        try:
            # Get BGP RIB entries for both IPv4 and IPv6
            # pyrefly: ignore [missing-attribute]
            bgp_rib_entries = await self.driver.async_get_bgp_rib_entries()

            if not bgp_rib_entries:
                self.logger.warning(f"No BGP RIB entries found on {hostname}")
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.FAIL,
                    message=f"No BGP RIB entries found on {hostname}. This may indicate BGP is not running or configured.",
                )

            self.logger.info(
                f"Retrieved {len(bgp_rib_entries)} BGP RIB entries for analysis"
            )

            # Analyze entries for stale routes (zero paths)
            stale_prefixes = []
            total_prefixes_checked = 0

            for rib_entry in bgp_rib_entries:
                prefix_str = f"{ip_ntop(rib_entry.prefix.prefix_bin)}/{rib_entry.prefix.num_bits}"
                total_prefixes_checked += 1

                if not self._has_valid_paths(rib_entry):
                    stale_info = {
                        "prefix": prefix_str,
                        "best_group": getattr(rib_entry, "best_group", "N/A"),
                        "paths_map": rib_entry.paths if rib_entry.paths else {},
                    }
                    stale_prefixes.append(stale_info)

                    if verbose:
                        self.logger.warning(f"Found stale prefix {prefix_str}: ")

            self.logger.info(
                f"BGP stale route analysis complete: "
                f"checked {total_prefixes_checked} prefixes, "
                f"found {len(stale_prefixes)} stale routes"
            )

            # Log detailed information for debugging
            self.add_data_to_log(
                {
                    "total_rib_entries": len(bgp_rib_entries),
                    "prefixes_checked": total_prefixes_checked,
                    "stale_routes_found": len(stale_prefixes),
                    "device": hostname,
                }
            )

            # Determine health check result
            if stale_prefixes:
                failure_message = self._create_failure_message(
                    stale_prefixes, hostname, verbose
                )
                self.logger.error(
                    f"BGP stale route health check FAILED for {hostname}: {failure_message}"
                )

                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.FAIL,
                    message=failure_message,
                )
            else:
                success_message = (
                    f"BGP stale route health check PASSED for {hostname}: "
                    f"No stale routes found among {total_prefixes_checked} checked prefixes"
                )

                self.logger.info(success_message)

                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.PASS,
                    message=success_message,
                )

        except Exception as e:
            error_msg = f"BGP stale route health check ERROR on {hostname}: {str(e)}"
            self.logger.error(error_msg)
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.ERROR,
                message=error_msg,
            )
