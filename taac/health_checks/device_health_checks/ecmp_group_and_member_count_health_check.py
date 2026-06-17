# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import asyncio
import re
import typing as t
from collections import defaultdict

from taac.constants import (
    MAX_ECMP_GROUP_COUNT,
    MAX_ECMP_MEMBER_COUNT,
    TestDevice,
)
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
)
from taac.health_check.health_check import types as hc_types


class EcmpGroupAndMemberCountHealthCheck(
    AbstractDeviceHealthCheck[hc_types.BaseHealthCheckIn]
):
    CHECK_NAME = hc_types.CheckName.ECMP_GROUP_AND_MEMBER_COUNT_CHECK
    OPERATING_SYSTEMS = ["FBOSS"]

    async def _run(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        ecmp_member_threshold = check_params.get(
            "ecmp_member_count", MAX_ECMP_MEMBER_COUNT
        )
        ecmp_group_threshold = check_params.get(
            "ecmp_group_count", MAX_ECMP_GROUP_COUNT
        )
        tasks = []
        tasks.append(self.async_verify_ecmp_nexthop_group_count(ecmp_group_threshold))
        tasks.append(
            self.async_verify_ecmp_nexthop_group_member_count(ecmp_member_threshold)
        )
        results = await asyncio.gather(*tasks, return_exceptions=True)
        failed_checks = [result for result in results if isinstance(result, Exception)]
        if failed_checks:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=f"{', '.join([str(check) for check in failed_checks])}",
            )

        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
        )

    async def async_verify_ecmp_nexthop_group_count(self, max_count: int) -> None:
        # currently only works for fboss
        cmd = "fboss2 show hw-object NEXT_HOP_GROUP"
        # pyrefly: ignore [missing-attribute]
        res = await self.driver.async_run_cmd_on_shell(cmd)
        parent_nhop_group_id_set = set()
        group_to_mbr_intf_map = defaultdict(list)
        for line in res.splitlines():
            if line:
                if line.startswith("NextHopGroupSaiId"):
                    next_hop_group_sai_id = int(
                        line.split(":")[0]
                        .replace("NextHopGroupSaiId", "")
                        .strip("(")
                        .strip(")")
                    )
                    parent_nhop_group_id_set.add(next_hop_group_sai_id)
                if line.startswith("NextHopGroupMemberSaiId"):
                    pattern = r"NextHopGroupMemberSaiId\((\d+)\).*?NextHopGroupId:\s*(\d+),.*?NextHopId:\s*(\d+)"
                    match = re.search(pattern, line)

                    if match:
                        nhop_group_id = int(match.group(2))
                        nhop_id = int(match.group(3))
                        group_to_mbr_intf_map[nhop_group_id].append(nhop_id)
        if parent_nhop_group_id_set != set(group_to_mbr_intf_map.keys()):
            raise Exception(
                f"Parent NextHopGroupSaiId {parent_nhop_group_id_set} does not match with Child NextHopGroupMemberSaiId {group_to_mbr_intf_map.keys()}"
            )
        if len(group_to_mbr_intf_map.keys()) > max_count:
            raise Exception(
                # pyrefly: ignore [missing-attribute]
                f"The number of ecmp groups on {self.driver.hostname} exceeded the defined threshold {max_count}"
            )

    async def async_verify_ecmp_nexthop_group_member_count(
        self,
        max_count: int,
    ) -> None:
        # Step 1: Determine the minimum length of subnets needed

        # Define the command to run on the shell
        cmd = "fboss2 show hw-object NEXT_HOP_GROUP"
        # Run the command on the shell and get the result
        # pyrefly: ignore [missing-attribute]
        res = await self.driver.async_run_cmd_on_shell(cmd)
        # Use regular expression to find all occurrences of NextHopGroupMemberSaiId(xxxx):
        pattern = r"NextHopGroupMemberSaiId\(\d+\):"
        matches = re.findall(pattern, res)
        # Count the occurrences
        current_count = len(matches)
        # Check if the current count is greater than or equal to the requested scale
        if current_count >= max_count:
            raise ValueError(
                f"Current count ({current_count}) is greater than or equal to the requested scale ({max_count})"
            )

    async def _run_arista(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        """
        Verify ECMP next-hop count for a prefix on EOS (ar-bgp) devices via CLI.

        Uses 'show ipv6 route <prefix> | json' to count the number of
        next-hops (ECMP width) for a given prefix.

        Args:
            obj: Test device
            input: Base health check input
            check_params: Dictionary containing:
                - prefix: IPv6 prefix to check (e.g., "2402:db00:1100::/64")
                - expected_ecmp_width: Expected number of ECMP next-hops (optional)
                - min_ecmp_width: Minimum ECMP width (optional)
                - address_family: "ipv6" or "ipv4" (optional, defaults to "ipv6")
        """
        hostname = obj.name
        prefix = check_params.get("prefix")
        expected_ecmp_width = check_params.get("expected_ecmp_width")
        min_ecmp_width = check_params.get("min_ecmp_width")
        address_family = check_params.get("address_family", "ipv6")

        if not prefix:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=(
                    f"'prefix' parameter is required for ECMP check on {hostname}"
                ),
            )

        try:
            if expected_ecmp_width is not None:
                expected_ecmp_width = int(expected_ecmp_width)
            if min_ecmp_width is not None:
                min_ecmp_width = int(min_ecmp_width)
        except (ValueError, TypeError) as e:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=f"Invalid ECMP width parameter on {hostname}: {e}",
            )

        self.logger.info(
            f"Running ECMP check for prefix {prefix} on {hostname} via EOS CLI"
        )

        try:
            if address_family == "ipv4":
                cmd = f"show ip route {prefix} | json"
            else:
                cmd = f"show ipv6 route {prefix} | json"

            # pyrefly: ignore [missing-attribute]
            result = await self.driver.async_execute_show_json_on_shell(cmd)

            # Parse next-hops from the route entry
            routes = result.get("vrfs", {}).get("default", {}).get("routes", {})

            if not routes:
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.FAIL,
                    message=f"Prefix {prefix} not found in routing table on {hostname}",
                )

            # Get the route entry (may have slightly different key format)
            route_entry = None
            for route_key, route_info in routes.items():
                route_entry = route_info
                break

            if not route_entry:
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.FAIL,
                    message=f"No route entry for {prefix} on {hostname}",
                )

            # Count next-hops (ECMP width)
            vias = route_entry.get("vias", [])
            ecmp_width = len(vias)

            self.logger.info(
                f"ECMP width for {prefix} on {hostname}: {ecmp_width} next-hops"
            )
            for i, via in enumerate(vias):
                nexthop = via.get("nexthopAddr", "unknown")
                interface = via.get("interface", "unknown")
                self.logger.info(f"  next-hop {i + 1}: {nexthop} via {interface}")

            # Validate ECMP width
            if expected_ecmp_width is not None and ecmp_width != expected_ecmp_width:
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.FAIL,
                    message=(
                        f"ECMP width mismatch for {prefix} on {hostname}: "
                        f"expected {expected_ecmp_width}, got {ecmp_width}"
                    ),
                )

            if min_ecmp_width is not None and ecmp_width < min_ecmp_width:
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.FAIL,
                    message=(
                        f"ECMP width too low for {prefix} on {hostname}: "
                        f"expected at least {min_ecmp_width}, got {ecmp_width}"
                    ),
                )

            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.PASS,
                message=(
                    f"ECMP verification PASSED for {prefix} on {hostname}: "
                    f"{ecmp_width} next-hops"
                ),
            )

        except Exception as e:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.ERROR,
                message=f"Error checking ECMP on {hostname}: {e}",
            )
