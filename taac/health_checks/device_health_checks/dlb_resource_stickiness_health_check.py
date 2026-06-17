# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""
DLB Resource Stickiness Health Check..

This health check verifies DLB (Dynamic Load Balancing) resources by analyzing
ECMP next hop groups and their distribution across prefix categories.

Based on: scripts/pavanpatil/prefix_to_dlb_resource_stickiness.py

The check counts UNIQUE ECMP GROUPS (not individual routes) and categorizes them by:
- Prefix category (configurable patterns like "5000:dd::", "5000:ee::", or "all else")
- ECMP mode (Default/DLB, PER_PACKET_RANDOM, Other Modes)
"""

import ipaddress
import typing as t
from dataclasses import dataclass, field

from taac.constants import TestDevice
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
)
from taac.health_check.health_check import types as hc_types


@dataclass
class NextHopGroup:
    """Structure to hold common prefixes sharing the same next hops."""

    prefixes: list = field(default_factory=list)
    ecmp_modes: set = field(default_factory=set)

    def add_route(self, prefix: str, ecmp_mode: t.Optional[str]) -> None:
        self.prefixes.append(prefix)
        self.ecmp_modes.add(str(ecmp_mode) if ecmp_mode else "None")


@dataclass
class CategoryStats:
    """Statistics for a prefix category."""

    dlb_count: int = 0
    per_packet_random_count: int = 0
    other_modes_count: int = 0
    next_hop_counts: list = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.dlb_count + self.per_packet_random_count + self.other_modes_count

    @property
    def max_next_hops(self) -> str:
        if not self.next_hop_counts:
            return "-"
        return str(max(self.next_hop_counts))


class DlbResourceStickinessHealthCheck(
    AbstractDeviceHealthCheck[hc_types.BaseHealthCheckIn]
):
    """
    Health check to verify DLB resources by counting unique ECMP next hop groups.

    This check analyzes routes and groups them by their next hops, then counts
    unique ECMP groups (groups with >1 next hop) per prefix category and ECMP mode.

    Output format:
    ```
    Prefix Category      | Default (DLB) | PER_PACKET_RANDOM | Other Modes | Total | Max Next Hops
    ------------------------------------------------------------------------------------------------
    5000:dd prefixes     | 2             | 0                 | 0           | 2     | 4
    5000:ee prefixes     | 3             | 0                 | 0           | 3     | 6
    all else             | 1             | 0                 | 0           | 1     | 2
    ------------------------------------------------------------------------------------------------
    TOTAL                | 6             | 0                 | 0           | 6     | n/a
    ```

    Parameters:
        prefix_patterns: List of prefix patterns to categorize (e.g., ["5000:dd::", "5000:ee::"])
                        Routes not matching any pattern are categorized as "all else"
        expected_counts: Optional dict with expected counts PER PREFIX CATEGORY:
            {
                "5000:dd prefixes": {"dlb": 2, "total": 2},
                "5000:ee prefixes": {"dlb": 3, "total": 3, "min_total": 3},
                "all else": {"dlb": 1, "total": 1}
            }
            Supported keys per category:
            - "dlb": Exact match for DLB count
            - "per_packet_random": Exact match for PER_PACKET_RANDOM count
            - "other_modes": Exact match for other modes count
            - "total": Exact match for total count
            - "min_total": Minimum total count (>=)
            - "max_next_hops": Exact match for max next hops
        expected_totals: Optional dict with expected TOTAL counts across all categories:
            - "dlb": Expected total DLB groups
            - "per_packet_random": Expected total PER_PACKET_RANDOM groups
            - "other_modes": Expected total other mode groups
            - "total": Expected total ECMP groups

    Example usage:
        {
            "prefix_patterns": ["5000:dd::", "5000:ee::"],
            "expected_counts": {
                "5000:dd prefixes": {"dlb": 2, "total": 2},
                "5000:ee prefixes": {"dlb": 3, "min_total": 3}
            },
            "expected_totals": {
                "dlb": 6,
                "total": 6
            }
        }
    """

    CHECK_NAME = hc_types.CheckName.DLB_RESOURCE_STICKINESS_CHECK
    OPERATING_SYSTEMS = ["FBOSS"]

    async def _run(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        prefix_patterns = check_params.get("prefix_patterns", [])
        expected_counts = check_params.get("expected_counts", {})
        expected_totals = check_params.get("expected_totals", {})

        # Get all routes from agent
        # pyrefly: ignore [missing-attribute]
        async with self.driver.async_agent_client as client:
            routes = await client.getRouteTable()

        # Step 1: Group routes by their next hops
        nexthop_groups = self._group_routes_by_nexthops(routes)

        self.logger.info(f"Total unique next hop groups: {len(nexthop_groups)}")

        # Step 2: Build the matrix - count ECMP groups per prefix category/mode
        matrix = self._build_matrix(nexthop_groups, prefix_patterns)

        # Step 3: Generate the table output
        table_output = self._generate_table(matrix, prefix_patterns)

        # Step 4: Validate expected counts per prefix pattern
        validation_result = self._validate_counts(matrix, expected_counts)
        if validation_result["status"] == "FAIL":
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=f"{validation_result['message']}\n\n{table_output}",
            )

        # Step 5: Validate expected totals if provided
        validation_result = self._validate_totals(matrix, expected_totals)

        if validation_result["status"] == "FAIL":
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=f"{validation_result['message']}\n\n{table_output}",
            )

        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
            message=f"DLB Resource Analysis:\n{table_output}",
        )

    def _group_routes_by_nexthops(self, routes: list) -> t.Dict[tuple, NextHopGroup]:
        """
        Group routes by their next hops.

        Args:
            routes: List of routes from agent

        Returns:
            Dictionary mapping next_hops_tuple -> NextHopGroup
        """
        nexthop_groups: t.Dict[tuple, NextHopGroup] = {}

        for route in routes:
            # pyrefly: ignore [missing-attribute]
            ip_addr = self.driver.ip_ntop(route.dest.ip.addr)
            dest_prefix = f"{ip_addr}/{route.dest.prefixLength}"

            # Get next hops list
            next_hops_list = []
            if route.nextHops:
                for nhop in route.nextHops:
                    # pyrefly: ignore [missing-attribute]
                    nhop_ip = self.driver.ip_ntop(nhop.address.addr)
                    next_hops_list.append(nhop_ip)

            # Get overridden ECMP mode
            overridden_mode = None
            if (
                hasattr(route, "overrideEcmpSwitchingMode")
                and route.overrideEcmpSwitchingMode is not None
            ):
                overridden_mode = route.overrideEcmpSwitchingMode
            elif (
                hasattr(route, "overridenEcmpMode")
                and route.overridenEcmpMode is not None
            ):
                overridden_mode = route.overridenEcmpMode

            # Group by next hops (create tuple key from sorted next hops)
            next_hops_tuple = tuple(sorted(next_hops_list))

            if next_hops_tuple not in nexthop_groups:
                nexthop_groups[next_hops_tuple] = NextHopGroup()

            nexthop_groups[next_hops_tuple].add_route(dest_prefix, overridden_mode)

        return nexthop_groups

    def _categorize_prefix(self, route_prefix: str, prefix_patterns: list) -> str:
        """
        Categorize route prefix into one of the configured patterns or "all else".

        Args:
            route_prefix: Route prefix string (e.g., "5000:dd::1/128")
            prefix_patterns: List of prefix patterns (e.g., ["5000:dd::", "5000:ee::"])

        Returns:
            Category string (e.g., "5000:dd prefixes" or "all else")
        """
        try:
            network = ipaddress.IPv6Network(route_prefix, strict=False)

            for pattern in prefix_patterns:
                # Normalize the pattern
                if "/" not in pattern:
                    pattern_network = ipaddress.IPv6Network(
                        f"{pattern}/32", strict=False
                    )
                else:
                    pattern_network = ipaddress.IPv6Network(pattern, strict=False)

                if network.subnet_of(pattern_network):
                    return f"{pattern.rstrip(':')} prefixes"

            return "all else"
        except ValueError:
            return "all else"

    def _categorize_ecmp_mode(self, mode_str: str) -> str:
        """
        Categorize ECMP mode into DLB or non-DLB categories.

        Args:
            mode_str: String representation of ECMP mode

        Returns:
            Category: "Default (DLB)", "PER_PACKET_RANDOM", or "Other Modes"
        """
        if mode_str == "None":
            return "Default (DLB)"
        elif "PER_PACKET_RANDOM" in mode_str:
            return "PER_PACKET_RANDOM"
        else:
            return "Other Modes"

    def _build_matrix(
        self, nexthop_groups: t.Dict[tuple, NextHopGroup], prefix_patterns: list
    ) -> t.Dict[str, CategoryStats]:
        """
        Build the matrix counting unique ECMP groups per prefix category/mode.

        Only counts ECMP groups (groups with >1 next hop).

        Args:
            nexthop_groups: Dictionary of next hop groups
            prefix_patterns: List of prefix patterns

        Returns:
            Dictionary mapping category -> CategoryStats
        """
        # Initialize matrix with all categories
        matrix: t.Dict[str, CategoryStats] = {}
        for pattern in prefix_patterns:
            category = f"{pattern.rstrip(':')} prefixes"
            matrix[category] = CategoryStats()
        matrix["all else"] = CategoryStats()

        ecmp_groups_count = 0
        single_hop_groups_count = 0

        for next_hops_tuple, group in nexthop_groups.items():
            # Only process ECMP groups (>1 next hop)
            if len(next_hops_tuple) <= 1:
                single_hop_groups_count += 1
                continue

            ecmp_groups_count += 1
            num_next_hops = len(next_hops_tuple)

            # Find which prefix categories this next hop group serves
            prefix_categories_served = set()
            for prefix in group.prefixes:
                prefix_category = self._categorize_prefix(prefix, prefix_patterns)
                prefix_categories_served.add(prefix_category)

            # For each prefix category, count this group once per ECMP mode
            for prefix_category in prefix_categories_served:
                if prefix_category not in matrix:
                    matrix[prefix_category] = CategoryStats()

                # Determine ECMP mode for this group
                if len(group.ecmp_modes) == 1:
                    mode_str = list(group.ecmp_modes)[0]
                    ecmp_category = self._categorize_ecmp_mode(mode_str)

                    if ecmp_category == "Default (DLB)":
                        matrix[prefix_category].dlb_count += 1
                    elif ecmp_category == "PER_PACKET_RANDOM":
                        matrix[prefix_category].per_packet_random_count += 1
                    else:
                        matrix[prefix_category].other_modes_count += 1
                else:
                    # Mixed modes - count as Other Modes
                    matrix[prefix_category].other_modes_count += 1

                # Track next hop count only for prefix patterns (not "all else")
                if prefix_category != "all else":
                    matrix[prefix_category].next_hop_counts.append(num_next_hops)

        self.logger.info(
            f"ECMP groups (>1 next hop): {ecmp_groups_count}, "
            f"Single next hop groups: {single_hop_groups_count}"
        )

        return matrix

    def _generate_table(
        self, matrix: t.Dict[str, CategoryStats], prefix_patterns: list
    ) -> str:
        """
        Generate the formatted table output.

        Args:
            matrix: Dictionary mapping category -> CategoryStats
            prefix_patterns: List of prefix patterns

        Returns:
            Formatted table string
        """
        lines = []

        # Header
        lines.append(
            f"{'Prefix Category':<20} | {'Default (DLB)':<13} | "
            f"{'PER_PACKET_RANDOM':<17} | {'Other Modes':<11} | "
            f"{'Total':<5} | {'Max Next Hops':<13}"
        )
        lines.append("-" * 100)

        # Build ordered category list
        categories = []
        for pattern in prefix_patterns:
            category = f"{pattern.rstrip(':')} prefixes"
            if category in matrix:
                categories.append(category)
        if "all else" in matrix:
            categories.append("all else")

        # Data rows
        total_dlb = 0
        total_random = 0
        total_other = 0

        for category in categories:
            stats = matrix.get(category, CategoryStats())
            total_dlb += stats.dlb_count
            total_random += stats.per_packet_random_count
            total_other += stats.other_modes_count

            lines.append(
                f"{category:<20} | {stats.dlb_count:<13} | "
                f"{stats.per_packet_random_count:<17} | {stats.other_modes_count:<11} | "
                f"{stats.total:<5} | {stats.max_next_hops:<13}"
            )

        # Total row
        lines.append("-" * 100)
        grand_total = total_dlb + total_random + total_other

        lines.append(
            f"{'TOTAL':<20} | {total_dlb:<13} | "
            f"{total_random:<17} | {total_other:<11} | "
            f"{grand_total:<5} | {'n/a':<13}"
        )

        return "\n".join(lines)

    def _validate_totals(
        self, matrix: t.Dict[str, CategoryStats], expected_totals: t.Dict[str, int]
    ) -> t.Dict[str, t.Any]:
        """
        Validate the totals against expected values.

        Args:
            matrix: Dictionary mapping category -> CategoryStats
            expected_totals: Expected counts for validation

        Returns:
            Dict with status and message
        """
        if not expected_totals:
            return {"status": "PASS", "message": ""}

        # Calculate actual totals
        actual_dlb = sum(stats.dlb_count for stats in matrix.values())
        actual_random = sum(stats.per_packet_random_count for stats in matrix.values())
        actual_other = sum(stats.other_modes_count for stats in matrix.values())
        actual_total = actual_dlb + actual_random + actual_other

        failures = []

        if "dlb" in expected_totals:
            expected = expected_totals["dlb"]
            if actual_dlb != expected:
                failures.append(f"DLB groups: expected {expected}, got {actual_dlb}")

        if "per_packet_random" in expected_totals:
            expected = expected_totals["per_packet_random"]
            if actual_random != expected:
                failures.append(
                    f"PER_PACKET_RANDOM groups: expected {expected}, got {actual_random}"
                )

        if "other_modes" in expected_totals:
            expected = expected_totals["other_modes"]
            if actual_other != expected:
                failures.append(
                    f"Other Modes groups: expected {expected}, got {actual_other}"
                )

        if "total" in expected_totals:
            expected = expected_totals["total"]
            if actual_total != expected:
                failures.append(
                    f"Total ECMP groups: expected {expected}, got {actual_total}"
                )

        if failures:
            return {
                "status": "FAIL",
                "message": "Validation FAILED: " + "; ".join(failures),
            }

        return {"status": "PASS", "message": "All validations passed"}

    def _validate_category(
        self,
        category: str,
        stats: "CategoryStats",
        expected: t.Dict[str, int],
    ) -> t.List[str]:
        """Validate a single category's stats against expected values."""
        failures = []
        validators = {
            "dlb": ("DLB", lambda s: s.dlb_count),
            "per_packet_random": (
                "PER_PACKET_RANDOM",
                lambda s: s.per_packet_random_count,
            ),
            "other_modes": ("Other Modes", lambda s: s.other_modes_count),
            "total": ("Total", lambda s: s.total),
        }
        for key, (label, getter) in validators.items():
            if key in expected and getter(stats) != expected[key]:
                failures.append(
                    f"{category} - {label}: expected {expected[key]}, got {getter(stats)}"
                )
        if "min_total" in expected and stats.total < expected["min_total"]:
            failures.append(
                f"{category} - Total: expected >= {expected['min_total']}, got {stats.total}"
            )
        if "max_next_hops" in expected:
            actual_max = max(stats.next_hop_counts) if stats.next_hop_counts else 0
            if actual_max != expected["max_next_hops"]:
                failures.append(
                    f"{category} - Max Next Hops: expected {expected['max_next_hops']}, got {actual_max}"
                )
        return failures

    def _validate_counts(
        self,
        matrix: t.Dict[str, CategoryStats],
        expected_counts: t.Dict[str, t.Dict[str, int]],
    ) -> t.Dict[str, t.Any]:
        """
        Validate the counts per prefix category against expected values.

        Args:
            matrix: Dictionary mapping category -> CategoryStats
            expected_counts: Expected counts per category for validation.
                Supported keys per category:
                - "dlb": Exact match for DLB count
                - "per_packet_random": Exact match for PER_PACKET_RANDOM count
                - "other_modes": Exact match for other modes count
                - "total": Exact match for total count
                - "min_total": Minimum total count (>=)
                - "max_next_hops": Exact match for max next hops

        Returns:
            Dict with status and message
        """
        if not expected_counts:
            return {"status": "PASS", "message": ""}

        failures = []
        for category, expected in expected_counts.items():
            stats = matrix.get(category, CategoryStats())
            failures.extend(self._validate_category(category, stats, expected))

        if failures:
            return {
                "status": "FAIL",
                "message": "Validation FAILED: " + "; ".join(failures),
            }

        return {"status": "PASS", "message": "All per-category validations passed"}
