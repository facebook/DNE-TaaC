# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import asyncio
import ipaddress
import typing as t
from collections import defaultdict
from typing import Dict

from taac.constants import (
    ARP_SOFT_LIMIT,
    MAC_SOFT_LIMIT,
    NDP_SOFT_LIMIT,
    TestDevice,
)
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
)
from taac.utils.common import async_everpaste_str
from taac.health_check.health_check import types as hc_types

NDP_THRESHOLD_TOLERANCE = 100


class L2EntryThresholdHealthCheck(
    AbstractDeviceHealthCheck[hc_types.BaseHealthCheckIn]
):
    CHECK_NAME = hc_types.CheckName.L2_ENTRY_THRESHOLD_CHECK
    OPERATING_SYSTEMS = ["FBOSS"]

    async def _run(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        try:
            mac_entry_upper_lower_threshold = check_params.get(
                "mac_entry_upper_lower_threshold"
            )
            arp_entry_upper_lower_threshold = check_params.get(
                "arp_entry_upper_lower_threshold"
            )
            ndp_entry_upper_lower_threshold = check_params.get(
                "ndp_entry_upper_lower_threshold"
            )
            mac_entry_pattern_threshold = check_params.get(
                "mac_entry_pattern_threshold"
            )
            arp_entry_pattern_threshold = check_params.get(
                "arp_entry_pattern_threshold"
            )
            ndp_entry_pattern_threshold = check_params.get(
                "ndp_entry_pattern_threshold"
            )
            tasks = []
            if mac_entry_pattern_threshold:
                tasks.append(
                    self.async_verify_mac_entry_threshold_mapping(
                        mac_entry_pattern_threshold
                    )
                )

            if arp_entry_pattern_threshold:
                tasks.append(
                    self.async_verify_arp_entry_threshold_mapping(
                        # pyrefly: ignore [bad-argument-type]
                        mac_entry_pattern_threshold
                    )
                )

            if ndp_entry_pattern_threshold:
                tasks.append(
                    self.async_verify_ndp_entry_threshold_mapping(
                        # pyrefly: ignore [bad-argument-type]
                        mac_entry_pattern_threshold
                    )
                )

            if mac_entry_upper_lower_threshold:
                tasks.append(
                    self.async_verify_mac_entry_upper_lower_threshold(
                        mac_entry_upper_lower_threshold[0],
                        mac_entry_upper_lower_threshold[1],
                    )
                )
            if arp_entry_upper_lower_threshold:
                tasks.append(
                    self.async_verify_arp_entry_threshold(
                        arp_entry_upper_lower_threshold[0],
                        arp_entry_upper_lower_threshold[1],
                    )
                )
            if ndp_entry_upper_lower_threshold:
                tasks.append(
                    self.async_verify_ndp_entry_threshold(
                        ndp_entry_upper_lower_threshold[0],
                        ndp_entry_upper_lower_threshold[1],
                    )
                )

            results = await asyncio.gather(*tasks, return_exceptions=True)

            failed_checks = [
                result for result in results if isinstance(result, Exception)
            ]
            if failed_checks:
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.FAIL,
                    message=f"{', '.join([str(check) for check in failed_checks])}",
                )

            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.PASS,
            )
        except Exception as e:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=str(e),
            )

    async def async_verify_mac_entry_upper_lower_threshold(
        self, upper_threshold: int, lower_threshold: int
    ) -> None:
        self.logger.info(
            f"Verifying mac entry threshold is between {upper_threshold, lower_threshold}"
        )
        # currently only works for fboss
        # pyrefly: ignore [missing-attribute]
        mac_table = await self.driver.async_get_mac_table()
        mac_table_everpaste = await async_everpaste_str(str(mac_table))
        self.logger.info(
            f"Mac table length: {len(mac_table)}, Details: {mac_table_everpaste}"
        )
        if len(mac_table) > upper_threshold or len(mac_table) < lower_threshold:
            raise Exception(
                # pyrefly: ignore [missing-attribute]
                f"The number of mac entries on {self.driver.hostname} is not in range of {lower_threshold, upper_threshold}: {mac_table_everpaste}"
            )

    async def async_verify_arp_entry_threshold(
        self, upper_threshold: int, lower_threshold: int
    ) -> None:
        # currently only works for fboss
        self.logger.info(
            f"Verifying arp entry threshold is between {upper_threshold, lower_threshold}"
        )
        # pyrefly: ignore [missing-attribute]
        arp_table = await self.driver.async_get_arp_table()
        arp_table_everpaste = await async_everpaste_str(str(arp_table))
        self.logger.info(
            f"ARP table length: {len(arp_table)}, Details: {arp_table_everpaste}"
        )
        if len(arp_table) > upper_threshold or len(arp_table) < lower_threshold:
            raise Exception(
                # pyrefly: ignore [missing-attribute]
                f"The number of arp entries on {self.driver.hostname} is not in range of {lower_threshold, upper_threshold}: {arp_table_everpaste}"
            )

    async def async_verify_ndp_entry_threshold(
        self, upper_threshold: int, lower_threshold: int
    ) -> None:
        self.logger.info(
            f"Verifying ndp entry threshold is between {upper_threshold, lower_threshold}"
        )
        # pyrefly: ignore [missing-attribute]
        ndp_table = await self.driver.async_get_ndp_table()
        mac_table_everpaste = await async_everpaste_str(str(ndp_table))
        self.logger.info(
            f"NDP table length: {len(ndp_table)}, Details: {mac_table_everpaste}"
        )

        if (
            len(ndp_table) > (upper_threshold + NDP_THRESHOLD_TOLERANCE)
            or len(ndp_table) < lower_threshold
        ):
            raise Exception(
                # pyrefly: ignore [missing-attribute]
                f"The number of NDP entries on {self.driver.hostname} is not in range of {lower_threshold, upper_threshold + NDP_THRESHOLD_TOLERANCE}: {mac_table_everpaste}"
            )

    async def async_verify_arp_entry_threshold_mapping(
        self, value_to_threshold_mapping: Dict[str, int]
    ) -> None:
        """
        Verifies if the ARP entry count matches the expected threshold for each IP network.
        Args:
            value_to_threshold_mapping (Dict[str, int]): A dictionary mapping IP networks to their expected ARP entry counts.
        Returns:
            None
        """
        # Get the ARP table from the driver
        # pyrefly: ignore [missing-attribute]
        arp_table = await self.driver.async_get_arp_table()
        # Convert the ARP table to a dictionary with decimal IP addresses
        arp_data = {
            str(ipaddress.IPv4Address(entry.ip.addr)): entry.mac for entry in arp_table
        }
        # Initialize a dictionary to store the actual ARP entry counts for each IP network
        actual_counts = defaultdict(int)
        # Iterate over the IP networks and count the ARP entries for each one
        for ip_network in value_to_threshold_mapping:
            for ip_address in arp_data:
                if ipaddress.IPv4Network(ip_address).subnet_of(
                    ipaddress.IPv4Network(ip_network)
                ):
                    actual_counts[ip_network] += 1
        # Check if the actual ARP entry counts match the expected thresholds
        for ip_network, threshold in value_to_threshold_mapping.items():
            actual_count = actual_counts.get(ip_network)
            if actual_count and actual_count > threshold:
                raise Exception(
                    # pyrefly: ignore [missing-attribute]
                    f"The number of arp entries on {self.driver.hostname} and expected entries do not match"
                )
        if len(arp_data) > ARP_SOFT_LIMIT:
            raise Exception(
                # pyrefly: ignore [missing-attribute]
                f"The number of arp entries on {self.driver.hostname} greater than {ARP_SOFT_LIMIT}"
            )

    async def async_verify_ndp_entry_threshold_mapping(
        self, value_to_threshold_mapping: Dict[str, int]
    ) -> None:
        """
        Verifies if the NDP entry count matches the expected threshold for each IP network.
        Args:
            value_to_threshold_mapping (Dict[str, int]): A dictionary mapping IP networks to their expected ARP entry counts.
        Returns:
            None
        """
        # Get the ARP table from the driver
        # pyrefly: ignore [missing-attribute]
        ndp_table = await self.driver.async_get_ndp_table()
        ndp_data = {
            str(ipaddress.IPv6Address(entry.ip.addr)): entry.mac for entry in ndp_table
        }
        # Initialize a dictionary to store the actual NDP entry counts for each IP network
        actual_counts = defaultdict(int)
        # Iterate over the IP networks and count the NDP entries for each one
        for ip_network in value_to_threshold_mapping:
            for ip_address in ndp_data:
                if ipaddress.IPv6Network(ip_address).subnet_of(
                    ipaddress.IPv6Network(ip_network)
                ):
                    actual_counts[ip_network] += 1
        # Check if the actual ARP entry counts match the expected thresholds
        for ip_network, threshold in value_to_threshold_mapping.items():
            actual_count = actual_counts.get(ip_network)
            if actual_count and actual_count > threshold:
                raise Exception(
                    # pyrefly: ignore [missing-attribute]
                    f"The number of ndp entries on {self.driver.hostname} and expected entries do not match"
                )

        if len(ndp_data) > NDP_SOFT_LIMIT:
            raise Exception(
                # pyrefly: ignore [missing-attribute]
                f"The number of ndp entries on {self.driver.hostname} greater than {NDP_SOFT_LIMIT}"
            )

    async def async_verify_mac_entry_threshold_mapping(
        self, value_to_threshold_mapping: Dict[str, int]
    ) -> None:
        """
        Verifies if the mac count matches the expected vaue.
        Args:
            value_to_threshold_mapping (Dict[str, int]): A dictionary mapping MAC to their expected MAC entry counts.
        Returns:
            None
        """
        # Get the ARP table from the driver
        # pyrefly: ignore [missing-attribute]
        mac_table = await self.driver.async_get_mac_table()
        mac_data = {str(entry.mac) for entry in mac_table}
        # Initialize a dictionary to store the actual MAC entry counts for each IP network
        actual_counts = defaultdict(int)
        # Iterate over the IP networks and count the ARP entries for each one
        for mac_pattern in value_to_threshold_mapping:
            for mac_address in mac_data:
                if mac_address.startswith(mac_pattern.lower()):
                    actual_counts[mac_pattern] += 1
        # Check if the actual ARP entry counts match the expected thresholds
        for mac_network, threshold in value_to_threshold_mapping.items():
            actual_count = actual_counts.get(mac_network)
            if actual_count and actual_count > threshold:
                raise Exception(
                    # pyrefly: ignore [missing-attribute]
                    f"The number of mac entries on {self.driver.hostname} and expected entries do not match"
                )

        if len(mac_data) > MAC_SOFT_LIMIT:
            raise Exception(
                # pyrefly: ignore [missing-attribute]
                f"The number of mac entries on {self.driver.hostname} greater than {MAC_SOFT_LIMIT}"
            )
