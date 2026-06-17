# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

import typing as t

from taac.constants import TestDevice
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
)
from taac.utils.health_check_utils import ip_ntop
from taac.health_check.health_check import types as hc_types


class BgpNonBestRouteHealthCheck(AbstractDeviceHealthCheck[hc_types.BaseHealthCheckIn]):
    """
    Detects BGP routes with paths but no best path designation.
    """

    CHECK_NAME = hc_types.CheckName.BGP_NON_BEST_PATH_CHECK
    OPERATING_SYSTEMS = [
        "FBOSS",
        "EOS",
    ]

    def _has_valid_best_path(self, entry) -> bool:
        """Check if entry has a valid best path designation."""
        best_group = getattr(entry, "best_group", None)
        return (
            best_group is not None
            and best_group in entry.paths
            and len(entry.paths[best_group]) > 0
        )

    def _extract_path_info(self, entry) -> list[str]:
        """Extract readable path information from RIB entry."""
        paths = []
        for _group_name, group_paths in entry.paths.items():
            for path in group_paths or []:
                next_hop = "unknown"
                if hasattr(path, "next_hop") and path.next_hop:
                    try:
                        next_hop = ip_ntop(path.next_hop.prefix_bin)
                    except Exception:
                        next_hop = str(path.next_hop)
                paths.append(f"via {next_hop}")
        return paths

    def _create_problem_explanation(self, entry) -> str:
        """Create explanation string for problematic route."""
        prefix = f"{ip_ntop(entry.prefix.prefix_bin)}/{entry.prefix.num_bits}"
        paths = self._extract_path_info(entry)
        return f"{prefix} has paths [{'; '.join(paths)}] but no best path selected"

    def _analyze_rib_entries(self, entries: list, verbose: bool) -> list[str]:
        """Analyze RIB entries and return list of problem explanations."""
        problems: list[str] = []

        for entry in entries:
            if not entry.paths:
                continue

            if not self._has_valid_best_path(entry):
                explanation = self._create_problem_explanation(entry)
                problems.append(explanation)

                if verbose:
                    self.logger.warning(f"BGP issue: {explanation}")

        return problems

    async def _run(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        """Execute BGP non-best route health check."""
        hostname = obj.name
        verbose = check_params.get("verbose", False)

        self.logger.info(f"Starting BGP non-best route check for {hostname}")

        try:
            # pyrefly: ignore [missing-attribute]
            entries = await self.driver.async_get_bgp_rib_entries()

            if not entries:
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.FAIL,
                    message=f"No BGP entries on {hostname}. BGP may not be running.",
                )

            problems = self._analyze_rib_entries(entries, verbose)

            if problems:
                routes_list = "; ".join(problems)
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.FAIL,
                    message=routes_list,
                )

            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.PASS,
                message=f"No BGP best path issues found on {hostname}",
            )

        except Exception as e:
            error = f"BGP non-best route check ERROR on {hostname}: {str(e)}"
            self.logger.error(error)
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.ERROR, message=error
            )
