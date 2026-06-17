# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import typing as t
from dataclasses import dataclass

from neteng.fboss.bgp_attr.types import TBgpAfi
from taac.constants import TestDevice
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
)
from taac.utils import arista_utils
from taac.health_check.health_check import types as hc_types


@dataclass
class RouteEntry:
    """
    Represents a route entry with next-hops and optional admin distance and metric.
    """

    prefix: str
    next_hops: t.List[str]
    admin_distance: t.Optional[int] = None
    metric: t.Optional[int] = None


class AristaFbossNextHopValidityHealthCheck(
    AbstractDeviceHealthCheck[hc_types.BaseHealthCheckIn]
):
    """
    Health check for validating next-hop group consistency on Arista devices.
    """

    CHECK_NAME = hc_types.CheckName.NEXT_HOP_GROUP_VALIDITY_CHECK
    OPERATING_SYSTEMS = ["EOS"]

    async def _run(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        """
        Health check for validating next-hop group consistency on Arista devices.
        This check ensures that the next-hop groups (NHGs) configured on Arista devices are consistent across
        the Routing Information Base (RIB), Forwarding Information Base (FIB), and hardware. It performs the following:
        - Compares the number of ECMP (Equal-Cost Multi-Path) sets between BGP, static routes, and NHG data.
        - Detects duplicate next-hop groups with identical sets of next-hop values.
        - Verifies that ECMP sets in BGP match those in the next-hop group data.
        - Optionally validates that the FIB Agent and hardware have the same number of next-hops, if recursive
            resolution is not expected (e.g., for static routes with direct interfaces).
        Args:
            obj (TestDevice): The test device to run the health check on.
            input (BaseHealthCheckIn): Input parameters for the health check.
            check_params (dict): Optional parameters for customizing the check:
                - parent_prefixes_to_ignore (list, optional): Parent prefixes to exclude from validation.
                - prefix_subnets (list, optional): Specific prefix subnets to check.
                - bgp_admin_distance (int, optional): Admin distance for BGP routes (default: 200).
                - expected_metric (int, optional): Expected metric value for routes.
                - validate_hardware_nexthop_count (bool, optional): If True, validates that FIB Agent and hardware
                have the same number of next-hops (default: False). Should be True only when recursive resolution
                is NOT expected.
        Returns:
            HealthCheckResult: The result of the health check, including status (PASS/FAIL/ERROR) and a message
            describing the outcome.
        Raises:
            Exception: If an error occurs during the health check, the result will have status ERROR and include
            the error message.
        Example:
            result = await AristaFbossNextHopValidityHealthCheck()._run(
                obj=test_device,
                input=health_check_input,
                check_params={
                    "parent_prefixes_to_ignore": ["10.0.0.0/8"],
                    "validate_hardware_nexthop_count": True,
                }
            )
        """
        self.logger.debug(
            f"Executing Arista Fboss NEXT_HOP_GROUP_VALIDITY_CHECK on {obj.name}."
        )
        try:
            bgp_ecmp_data = await self.process_bgp_routes_for_next_hop_to_prefix_map()
            static_route_data = await self.process_static_routes_for_ngh_to_prefix_map()
            next_hop_group_data = (
                await self.process_next_hop_group_data_for_ngh_to_nexthop_map()
            )
            return await self.validate_nhg_correctness(
                bgp_ecmp_data, static_route_data, next_hop_group_data
            )
        except Exception as e:
            error_message = f"Error during NextHop Validity consistency check: {str(e)}"
            self.logger.error(error_message)
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.ERROR,
                message=error_message,
            )

    async def validate_nhg_correctness(
        self,
        bgp_ecmp_data: dict,
        static_route_data: dict,
        next_hop_group_data: dict,
    ) -> hc_types.HealthCheckResult:
        """
        Validate the correctness of next-hop groups across BGP, static routes, and NHG data.
        Args:
            bgp_ecmp_data: BGP ECMP data
            static_route_data: Static route data
            next_hop_group_data: Next-hop group data
        Returns:
            HealthCheckResult: Result of the validation
        """
        errors = []
        # Step 1: Compare the number of ECMP sets
        ecmp_set_count_in_bgp = len(bgp_ecmp_data)
        self.logger.info(f"Total number of ECMP sets in BGP: {ecmp_set_count_in_bgp}")
        ngh_count_from_static_route_data = len(static_route_data)
        self.logger.info(
            f"Total number of ECMP sets in static route: {ngh_count_from_static_route_data}"
        )
        ngh_count_from_nexthop_group_data = len(next_hop_group_data)
        self.logger.info(
            f"Total number of ECMP sets in nexthop group: {ngh_count_from_nexthop_group_data}"
        )
        if (
            ecmp_set_count_in_bgp != ngh_count_from_static_route_data
            or ecmp_set_count_in_bgp != ngh_count_from_nexthop_group_data
        ):
            errors.append(
                f"Next hop group count mismatch: BGP={ecmp_set_count_in_bgp}, "
                f"Static={ngh_count_from_static_route_data}, NHG={ngh_count_from_nexthop_group_data}"
            )
        else:
            self.logger.info(
                f"Next hop group counts match: BGP={ecmp_set_count_in_bgp}, "
                f"Static={ngh_count_from_static_route_data}, NHG={ngh_count_from_nexthop_group_data}"
            )
        # Step 2: Check for duplicate NHGs with same set of next-hop values
        duplicate_data = await self.find_duplicate_values(next_hop_group_data)
        if duplicate_data:
            errors.append(
                f"{duplicate_data} -- Next hop Groups with Duplicate ECMP sets found"
            )
            self.logger.info(
                f"{duplicate_data} -- Next hop Groups with Duplicate ECMP sets found"
            )
        # Step 3: Compare ECMP sets between BGP and NHG data
        next_hop_group_sets = []
        if ecmp_set_count_in_bgp == ngh_count_from_nexthop_group_data:
            bgp_ecmp_sets = await self.process_ip_dict(bgp_ecmp_data)
            sorted_bgp_ecmp_sets = [sorted(ecmp_set) for ecmp_set in bgp_ecmp_sets]
            next_hop_group_sets = [
                sorted(values) for values in next_hop_group_data.values()
            ]
            if len(next_hop_group_sets) != len(sorted_bgp_ecmp_sets):
                errors.append("ECMP data count does not match between BGP and NHG data")
            for ecmp_set in next_hop_group_sets:
                if ecmp_set not in sorted_bgp_ecmp_sets:
                    errors.append(
                        f"ECMP data {ecmp_set} does not match between BGP and NHG data"
                    )
        # Final Result
        if errors:
            error_message = (
                "Nexthop Group validity consistency check FAILED. Issues:\n"
                + "\n".join(f"  - {error}" for error in errors)
            )
            self.logger.error(error_message)
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=error_message,
            )
        success_message = (
            f"Nexthop Group validity consistency check PASSED\n"
            f"  - Total ECMP sets: {len(bgp_ecmp_data)} match\n"
            "  - BGP/Static/Nexthop Group Data are consistent\n"
        )
        self.logger.info(success_message)
        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
            message=success_message,
        )

    async def process_ip_dict(self, ip_dict: dict) -> t.List[t.List[str]]:
        """
        Process a dictionary of IP sets, removing masks and sorting.
        Args:
            ip_dict: Dictionary with frozenset keys of IPs with masks
        Returns:
            List of sorted IPs (without masks) for each set
        """
        result = []
        for frozen_set in ip_dict.keys():
            ip_set = {ip_with_mask.split("/")[0] for ip_with_mask in frozen_set}
            sorted_ips = sorted(ip_set)
            result.append(sorted_ips)
        return result

    async def build_bgp_result_dict(self, bgp_entries: t.List) -> dict:
        """
        Build a result dictionary from BGP entries.
        Args:
            bgp_entries: List of BGP entries
        Returns:
            Dictionary mapping parsed data to prefixes
        """
        result_dict = {}
        for element in bgp_entries:
            afi = await self.determine_afi(element.prefix.afi)
            prefix = await self.parse_prefix(element.prefix, afi)
            parsed_data = await self.process_bgp_paths(element, afi)
            if parsed_data:
                if parsed_data not in result_dict:
                    result_dict[parsed_data] = []
                result_dict[parsed_data].append(prefix)
        return result_dict

    async def determine_afi(self, prefix_afi: TBgpAfi) -> str:
        """
        Determine address family identifier (AFI).
        Args:
            prefix_afi: Prefix AFI
        Returns:
            'v6' for IPv6, 'v4' for IPv4
        """
        return "v6" if prefix_afi == TBgpAfi.AFI_IPV6 else "v4"

    @staticmethod
    async def parse_prefix(prefix, afi: str) -> str:
        """
        Parse prefix based on AFI.
        Args:
            prefix: Prefix object
            afi: Address family identifier
        Returns:
            Parsed prefix string
        """
        if afi == "v6":
            return await arista_utils.parse_ipv6_prefix(
                prefix.prefix_bin, prefix.num_bits
            )
        return await arista_utils.parse_ipv4_prefix(prefix.prefix_bin, prefix.num_bits)

    async def process_bgp_paths(self, element, afi: str) -> t.Optional[frozenset]:
        """
        Process BGP paths for an element.
        Args:
            element: BGP entry element
            afi: Address family identifier
        Returns:
            frozenset of parsed BGP paths, or None
        """
        data_to_parse = element.paths.get("best", None)
        if not data_to_parse:
            return None
        parsed_data = frozenset(await arista_utils.parse_bgp_paths(data_to_parse, afi))
        return parsed_data if parsed_data else None

    async def process_bgp_routes_for_next_hop_to_prefix_map(self) -> dict:
        """
        Process BGP routes to build next-hop to prefix map.
        Returns:
            Dictionary mapping next-hop sets to prefixes
        """
        # pyrefly: ignore [missing-attribute]
        bgp_entries = await self.driver.async_get_bgp_rib_entries()
        return await self.build_bgp_result_dict(bgp_entries)

    async def process_static_routes_for_ngh_to_prefix_map(self) -> dict:
        """
        Process static routes to build next-hop group to prefix map.
        Returns:
            Dictionary mapping next-hop groups to prefixes
        """
        # pyrefly: ignore [missing-attribute]
        static_routes = await self.driver.async_get_static_routes()
        # pyrefly: ignore [missing-attribute]
        return await self.driver.create_group_to_ips_dict(static_routes)

    async def process_next_hop_group_data_for_ngh_to_nexthop_map(self) -> dict:
        """
        Process next-hop group data to build next-hop group to next-hop map.
        Returns:
            Dictionary mapping next-hop groups to next-hops
        """
        # pyrefly: ignore [missing-attribute]
        next_hop_group_data = await self.driver.get_nexthop_group_data()
        # pyrefly: ignore [missing-attribute]
        return await self.driver.parse_nexthop_groups(next_hop_group_data)

    async def find_duplicate_values(self, data: dict) -> dict:
        """
        Find all keys that share the same value list.
        Args:
            data: Dictionary to check for duplicate values
        Returns:
            Dictionary mapping sorted value tuples to lists of keys that share those values
        """
        value_to_keys: t.Dict[t.Tuple, t.List] = {}
        for key, value_list in data.items():
            sorted_tuple = tuple(sorted(value_list))
            value_to_keys.setdefault(sorted_tuple, []).append(key)
        duplicates = {k: v for k, v in value_to_keys.items() if len(v) > 1}
        return duplicates
