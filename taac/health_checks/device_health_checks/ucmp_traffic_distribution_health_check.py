# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
import asyncio
import logging
import time
import typing as t

from taac.constants import TestDevice
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
)
from taac.internal.ods_utils import (
    async_generate_ods_url,
    async_query_fbnet_interface_metric,
)
from taac.utils.common import async_get_fburl
from taac.utils.health_check_utils import ip_ntop
from taac.health_check.health_check import types as hc_types

_logger = logging.getLogger(__name__)


async def _build_vlan_to_port_map(driver) -> t.Dict[int, str]:
    """Build mapping from VLAN ID to physical port name."""
    vlan_to_port = {}

    # First, check aggregate ports (takes priority)
    try:
        async with driver.async_agent_client as client:
            agg_port_table = await client.getAggregatePortTable()
            all_port_info = await client.getAllPortInfo()

        for agg_port in agg_port_table:
            for member_port in agg_port.memberPorts:
                port_info = all_port_info.get(member_port.memberPortID)
                if port_info and port_info.vlans:
                    for vlan_id in port_info.vlans:
                        vlan_to_port[vlan_id] = agg_port.name
    except Exception as e:
        _logger.debug(f"Error getting aggregate port table: {e}")

    # Then get all port info for non-aggregated ports
    try:
        # pyre-fixme[61]: `all_port_info` is undefined, or not always defined.
        if not all_port_info:
            async with driver.async_agent_client as client:
                all_port_info = await client.getAllPortInfo()

        for port_info in all_port_info.values():
            if not port_info.vlans:
                continue
            for vlan_id in port_info.vlans:
                if vlan_id not in vlan_to_port:
                    vlan_to_port[vlan_id] = port_info.name
    except Exception as e:
        _logger.warning(f"Error getting port info: {e}")

    _logger.debug(f"Built VLAN to port map with {len(vlan_to_port)} entries")
    return vlan_to_port


def _convert_vlan_to_physical_interface(
    vlan_interface: str, vlan_to_port_map: t.Dict[int, str]
) -> t.Optional[str]:
    """Convert VLAN interface name (e.g., 'fboss2097') to physical port name."""
    if not vlan_interface.startswith("fboss"):
        return vlan_interface
    try:
        vlan_id = int(vlan_interface.replace("fboss", ""))
        return vlan_to_port_map.get(vlan_id)
    except ValueError:
        return None


class UcmpTrafficDistributionHealthCheck(
    AbstractDeviceHealthCheck[hc_types.BaseHealthCheckIn]
):
    """
    Health check to verify UCMP traffic distribution matches configured weights.

    This check validates that actual traffic distribution across nexthops
    matches the expected distribution based on UCMP weights configured in FIB.

    Validates:
    1. FIB route exists for target prefix
    2. FIB nexthops have UCMP weights configured
    3. Traffic (output BPS) is distributed across interfaces according to weights
    4. Distribution is within acceptable tolerance

    Usage in test config:
        Step(
            name=StepName.HEALTH_CHECK,
            step_params=Params(
                json_params=json.dumps({
                    "check_name": CheckName.UCMP_TRAFFIC_DISTRIBUTION_CHECK,
                    "check_params": {
                        "target_prefix": "2402:db00:1100:1e9::/64",
                        "tolerance_percent": 10,  # Allow ±10% deviation
                        "min_traffic_bps": 1000000,  # Minimum 1 Mbps to be significant
                        "min_ods_query_duration": 300,  # Minimum query duration (5 minutes)
                        "start_time": time.time(),  # Optional: ODS query start time
                        "end_time": time.time(),  # Optional: ODS query end time
                        "sleep_timer": 120,  # Optional: Wait before querying ODS
                    }
                })
            ),
        )
    """

    CHECK_NAME = hc_types.CheckName.UCMP_TRAFFIC_DISTRIBUTION_CHECK
    OPERATING_SYSTEMS = ["FBOSS"]

    def _extract_nexthop_interfaces(
        self, fib_route: t.Any
    ) -> t.List[t.Dict[str, t.Any]]:
        """
        Extract interface names and weights from FIB nexthops.

        Args:
            fib_route: FIB route entry (from getRouteTableDetails)

        Returns:
            List of dicts with 'interface', 'weight', and 'nexthop_ip'
            Note: interface contains VLAN interface name (e.g., "fboss2097")
        """
        nexthops = []

        if not hasattr(fib_route, "nextHops") or not fib_route.nextHops:
            return nexthops

        for nh in fib_route.nextHops:
            weight = getattr(nh, "weight", 1)
            # Weight 0 in FIB means ECMP, treat as weight 1
            if weight == 0:
                weight = 1

            nexthop_ip = None
            interface = None

            if hasattr(nh, "address"):
                # Get nexthop IP address
                if hasattr(nh.address, "addr"):
                    nexthop_ip = ip_ntop(nh.address.addr)

                # Get interface name (VLAN interface like "fboss2097")
                if hasattr(nh.address, "ifName") and nh.address.ifName:
                    interface = nh.address.ifName

            if interface:
                nexthops.append(
                    {
                        "interface": interface,
                        "weight": weight,
                        "nexthop_ip": nexthop_ip,
                    }
                )
            else:
                self.logger.warning(
                    f"Could not find interface for nexthop {nexthop_ip}"
                )

        return nexthops

    async def _query_interface_traffic(
        self,
        hostname: str,
        interface: str,
        start_time: int,
        end_time: int,
    ) -> t.Optional[float]:
        """
        Query ODS for average output BPS on an interface.

        Args:
            hostname: Device hostname
            interface: Interface name (e.g., "eth8/1/1")
            start_time: Unix timestamp
            end_time: Unix timestamp

        Returns:
            Average output BPS or None if no data
        """
        return await async_query_fbnet_interface_metric(
            hostname=hostname,
            interface=interface,
            metric="output_bps",
            start_time=start_time,
            end_time=end_time,
        )

    def _calculate_expected_distribution(
        self, nexthops: t.List[t.Dict[str, t.Any]]
    ) -> t.Dict[str, float]:
        """
        Calculate expected traffic distribution based on weights.

        Args:
            nexthops: List of nexthop info with 'interface' and 'weight'

        Returns:
            Dict mapping interface → expected traffic percentage (0-100)
        """
        total_weight = sum(nh["weight"] for nh in nexthops)
        if total_weight == 0:
            return {}

        expected_dist = {}
        for nh in nexthops:
            expected_pct = (nh["weight"] / total_weight) * 100
            expected_dist[nh["interface"]] = expected_pct

        return expected_dist

    def _map_dc_distribution_to_interfaces(
        self,
        dc_distribution: t.Dict[str, float],
        nexthops: t.List[t.Dict[str, t.Any]],
        expected_fib_weights: t.Dict[int, int],
    ) -> t.Dict[str, float]:
        """
        Map per-DC traffic percentages to individual interface percentages.

        This is used when manually specifying combined expected distribution
        (e.g., for mixed UCMP + ECMP traffic scenarios).

        Args:
            dc_distribution: Manual per-DC percentages, e.g., {"dc1": 50.3, "dc2": 30.7, "dc3": 19.0}
            nexthops: List of nexthop info with 'interface' and 'weight'
            expected_fib_weights: Expected FIB weights {weight: count}, e.g., {10: 4, 5: 4, 2: 4}

        Returns:
            Dict mapping interface → expected traffic percentage (0-100)
        """
        # Map weight to DC identifier and percentage
        # Assumption: DCs are identified by unique weights in descending order
        sorted_weights = sorted(expected_fib_weights.keys(), reverse=True)
        dc_keys = sorted(dc_distribution.keys())

        if len(sorted_weights) != len(dc_keys):
            self.logger.error(
                f"Mismatch: {len(sorted_weights)} unique weights but {len(dc_keys)} DC percentages provided"
            )
            return {}

        # Map weight → DC percentage
        weight_to_dc_pct = {}
        for i, weight in enumerate(sorted_weights):
            dc_key = dc_keys[i]
            weight_to_dc_pct[weight] = dc_distribution[dc_key]
            self.logger.debug(
                f"Mapping weight {weight} → {dc_key} ({dc_distribution[dc_key]}%)"
            )

        # Calculate per-interface percentage by dividing DC percentage by num interfaces in DC
        expected_dist = {}
        for nh in nexthops:
            weight = nh["weight"]
            if weight not in weight_to_dc_pct:
                self.logger.warning(
                    f"Weight {weight} not found in weight_to_dc_pct mapping"
                )
                continue

            # Get DC percentage for this weight
            dc_pct = weight_to_dc_pct[weight]

            # Count interfaces with same weight (same DC)
            num_interfaces_in_dc = sum(1 for n in nexthops if n["weight"] == weight)

            # Divide DC percentage equally among its interfaces
            interface_pct = dc_pct / num_interfaces_in_dc
            expected_dist[nh["interface"]] = interface_pct

            self.logger.debug(
                f"Interface {nh['interface']} (weight {weight}): {interface_pct:.2f}% "
                f"({dc_pct}% / {num_interfaces_in_dc} interfaces)"
            )

        return expected_dist

    def _calculate_actual_distribution(
        self, traffic_data: t.Dict[str, float]
    ) -> t.Dict[str, float]:
        """
        Calculate actual traffic distribution from BPS data.

        Args:
            traffic_data: Dict mapping interface → BPS

        Returns:
            Dict mapping interface → actual traffic percentage (0-100)
        """
        total_bps = sum(traffic_data.values())
        if total_bps == 0:
            return {}

        actual_dist = {}
        for interface, bps in traffic_data.items():
            actual_pct = (bps / total_bps) * 100
            actual_dist[interface] = actual_pct

        return actual_dist

    async def _run(  # noqa: C901
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        """
        Verify UCMP traffic distribution matches configured weights.

        Args:
            obj: Test device
            input: Health check input (unused)
            check_params: Parameters including:
                - target_prefix (str): Prefix to check (e.g., "2402:db00:1100:1e9::/64")
                - tolerance_percent (float): Acceptable deviation percentage. Default: 10
                - min_traffic_bps (float): Minimum BPS to be considered significant. Default: 1000000 (1 Mbps)
                - min_ods_query_duration (int): Minimum duration in seconds to query ODS. Default: 300 (5 minutes)
                - start_time (int): Optional ODS query start time (Unix timestamp). Default: current time
                - end_time (int): Optional ODS query end time (Unix timestamp). Default: current time
                - sleep_timer (int): Optional seconds to wait before querying ODS. Default: 0

        Returns:
            HealthCheckResult with PASS/FAIL status
        """
        self.logger.debug(f"Executing UCMP traffic distribution check on {obj.name}")

        # Parse parameters
        target_prefix = check_params.get("target_prefix")
        tolerance_pct = float(check_params.get("tolerance_percent", 10))
        min_traffic_bps = float(check_params.get("min_traffic_bps", 1000000))
        min_ods_query_duration = int(check_params.get("min_ods_query_duration", 300))

        # ODS time parameters - following GenericOdsHealthCheck pattern
        start_time = int(check_params.get("start_time", time.time()))
        sleep_timer = check_params.get("sleep_timer", 0)
        if sleep_timer > 0:
            self.logger.debug(f"Waiting {sleep_timer} seconds before querying ODS")
            await asyncio.sleep(sleep_timer)
        end_time = int(check_params.get("end_time", time.time()))

        # Ensure minimum query duration
        if end_time - start_time < min_ods_query_duration:
            start_time = end_time - min_ods_query_duration
            self.logger.debug(
                f"Adjusted start_time to ensure minimum query duration of {min_ods_query_duration}s"
            )

        # Validate required parameters
        if not target_prefix:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.ERROR,
                message="Missing required parameter: target_prefix",
            )

        # Step 1: Get FIB route for target prefix
        self.logger.debug(f"Fetching FIB route details for {target_prefix}")
        try:
            # pyrefly: ignore [missing-attribute]
            fib_routes = await self.driver.async_get_route_table_details()
        except Exception as e:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.ERROR,
                message=f"Failed to fetch FIB route details: {e}",
            )

        # Find the target prefix in FIB
        target_fib_route = None
        for fib_route in fib_routes:
            try:
                prefix_str = (
                    f"{ip_ntop(fib_route.dest.ip.addr)}/{fib_route.dest.prefixLength}"
                )
                if prefix_str == target_prefix:
                    target_fib_route = fib_route
                    break
            except Exception:
                continue

        if not target_fib_route:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=f"Prefix {target_prefix} not found in FIB",
            )

        # Step 2: Extract nexthop interfaces and weights (VLAN interfaces)
        nexthops = self._extract_nexthop_interfaces(target_fib_route)
        if not nexthops:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=f"No nexthops found for prefix {target_prefix}",
            )

        nexthop_info = [f"{nh['interface']} (weight {nh['weight']})" for nh in nexthops]
        self.logger.info(
            f"Found {len(nexthops)} VLAN nexthops for {target_prefix}: {', '.join(nexthop_info)}"
        )

        # Step 3: Build VLAN to physical port mapping
        self.logger.debug("Building VLAN to physical port mapping...")
        vlan_to_port_map = await _build_vlan_to_port_map(self.driver)

        # Convert VLAN interfaces to physical interfaces
        mapped_interfaces = []
        unmapped_interfaces = []
        vlan_to_physical = {}  # Mapping for output display
        for nh in nexthops:
            vlan_interface = nh["interface"]
            physical_interface = _convert_vlan_to_physical_interface(
                vlan_interface, vlan_to_port_map
            )
            if physical_interface:
                nh["physical_interface"] = physical_interface
                vlan_to_physical[vlan_interface] = physical_interface
                mapped_interfaces.append(f"{vlan_interface} → {physical_interface}")
                self.logger.debug(f"Mapped {vlan_interface} → {physical_interface}")
            else:
                self.logger.warning(
                    f"Could not map VLAN interface {vlan_interface} to physical interface"
                )
                unmapped_interfaces.append(vlan_interface)
                nh["physical_interface"] = vlan_interface  # Fallback to VLAN name
                vlan_to_physical[vlan_interface] = vlan_interface

        # Log summary of interface mappings
        self.logger.info(
            f"Interface mapping complete: {len(mapped_interfaces)} mapped, {len(unmapped_interfaces)} unmapped"
        )
        if mapped_interfaces:
            self.logger.info(f"Mapped interfaces: {', '.join(mapped_interfaces)}")
        if unmapped_interfaces:
            self.logger.warning(
                f"Unmapped interfaces: {', '.join(unmapped_interfaces)}"
            )

        # Step 4: Validate FIB weights and calculate expected distribution
        expected_fib_weights = check_params.get("expected_fib_weights")
        expected_fib_weights_int = {}

        if expected_fib_weights:
            # Validate FIB has expected UCMP weights programmed
            actual_fib_weights = {}
            for nh in nexthops:
                weight = nh["weight"]
                actual_fib_weights[weight] = actual_fib_weights.get(weight, 0) + 1

            # Convert expected_fib_weights keys to integers
            expected_fib_weights_int = {
                int(k) if isinstance(k, str) else k: v
                for k, v in expected_fib_weights.items()
            }

            if actual_fib_weights != expected_fib_weights_int:
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.FAIL,
                    message=f"FIB weight distribution mismatch for {target_prefix}. "
                    f"Expected FIB weights {expected_fib_weights_int}, got {actual_fib_weights}. "
                    f"UCMP policy may not be correctly programmed in FIB. "
                    f"Check control plane (BGP RIB) for correct weight assignment.",
                )

            # Use expected weights to calculate expected traffic distribution
            self.logger.info(
                f"FIB weights validated: {actual_fib_weights} matches expected {expected_fib_weights_int}"
            )

        # Step 4a: Calculate expected distribution
        # Check if manual expected traffic distribution is provided (for combined traffic scenarios)
        expected_traffic_dist = check_params.get("expected_traffic_distribution")

        if expected_traffic_dist:
            # Use manually provided per-DC percentages (e.g., for mixed UCMP + ECMP traffic)
            self.logger.info(
                f"Using manually specified expected traffic distribution: {expected_traffic_dist}"
            )
            expected_dist = self._map_dc_distribution_to_interfaces(
                dc_distribution=expected_traffic_dist,
                nexthops=nexthops,
                expected_fib_weights=expected_fib_weights_int,
            )
        else:
            # Calculate expected distribution from FIB weights (default behavior)
            expected_dist = self._calculate_expected_distribution(nexthops)

        if not expected_dist:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.ERROR,
                message="Failed to calculate expected traffic distribution",
            )

        # Step 5: Query ODS for traffic on each physical interface
        query_duration = end_time - start_time
        self.logger.debug(
            f"Querying ODS for traffic data (start={start_time}, end={end_time}, duration={query_duration}s)"
        )

        traffic_data = {}
        for nh in nexthops:
            vlan_interface = nh["interface"]
            physical_interface = nh["physical_interface"]

            bps = await self._query_interface_traffic(
                obj.name, physical_interface, start_time, end_time
            )
            if bps is not None:
                # Store traffic data using VLAN interface as key (for consistency with expected_dist)
                traffic_data[vlan_interface] = bps
                self.logger.debug(
                    f"Interface {vlan_interface} ({physical_interface}): {bps:.2f} BPS (avg)"
                )
            else:
                self.logger.warning(
                    f"No traffic data available for {vlan_interface} ({physical_interface})"
                )

        # Check if we got traffic data for all interfaces
        if len(traffic_data) != len(nexthops):
            missing = {nh["interface"] for nh in nexthops} - set(traffic_data.keys())
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.SKIP,
                message=f"Missing traffic data for interfaces: {missing}. "
                f"Cannot verify traffic distribution.",
            )

        # Check if total traffic is above minimum threshold
        total_traffic = sum(traffic_data.values())
        if total_traffic < min_traffic_bps:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.SKIP,
                message=f"Total traffic ({total_traffic:.2f} BPS) is below minimum threshold "
                f"({min_traffic_bps} BPS). Cannot accurately verify distribution.",
            )

        # Step 5: Calculate actual distribution and compare
        actual_dist = self._calculate_actual_distribution(traffic_data)

        # Verify distribution is within tolerance
        violations = []
        for interface in expected_dist:
            expected_pct = expected_dist[interface]
            actual_pct = actual_dist.get(interface, 0)
            deviation = abs(actual_pct - expected_pct)

            if deviation > tolerance_pct:
                violations.append(
                    {
                        "interface": interface,
                        "expected": expected_pct,
                        "actual": actual_pct,
                        "deviation": deviation,
                    }
                )

        # Build ODS links for all interfaces. Only shorten through the globally
        # throttled fburl tier on failure (where the shortest link aids triage);
        # on the passing path keep the raw ODS URL (still clickable) so a healthy
        # UCMP check — re-run per oscillation iteration across a wide nexthop
        # fanout (8-64 nexthops) — makes zero fburl calls.
        ods_links = []
        for nh in nexthops:
            physical_interface = nh["physical_interface"]
            # Use the same format as async_query_fbnet_interface_metric
            entity_desc = f"{obj.name}:{physical_interface}.FBNet"
            key_desc = "FBNet:interface.output_bps"
            ods_query_url = await async_generate_ods_url(
                entity_desc=entity_desc,
                key_desc=key_desc,
                start_time=start_time,
                end_time=end_time,
            )
            if violations:
                try:
                    ods_query_url = await async_get_fburl(ods_query_url)
                except Exception:
                    pass
            ods_links.append(f"{vlan_to_physical[nh['interface']]}: {ods_query_url}")

        ods_links_text = "\n".join(ods_links)

        if violations:
            # Build detailed error message with physical interface names
            error_details = "\n".join(
                [
                    f"  {vlan_to_physical[v['interface']]}: expected {v['expected']:.2f}%, "
                    f"got {v['actual']:.2f}% (deviation: {v['deviation']:.2f}%)"
                    for v in violations
                ]
            )
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=f"Traffic distribution exceeds tolerance ({tolerance_pct}%):\n{error_details}\n\n"
                f"ODS Links for traffic verification:\n{ods_links_text}",
            )

        # Success - build detailed message with physical interface names
        dist_summary = ", ".join(
            [
                f"{vlan_to_physical[intf]}: {actual_dist[intf]:.2f}% (expected {expected_dist[intf]:.2f}%)"
                for intf in expected_dist
            ]
        )

        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
            message=f"UCMP traffic distribution verified for {target_prefix} with "
            f"{len(nexthops)} nexthops. Total traffic: {total_traffic:.2f} BPS. "
            f"Distribution within {tolerance_pct}% tolerance: {dist_summary}\n\n"
            f"ODS Links:\n{ods_links_text}",
        )
