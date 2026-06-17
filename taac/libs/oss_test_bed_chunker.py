# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""
OSS-compatible TestBedChunker implementation.

This module provides an OSS-compatible version of TestBedChunker that uses
static CSV data instead of Meta-internal services (Skynet, NetWhoAmI, etc.)
for topology discovery.

Key differences from internal TestBedChunker:
- Uses device_info.csv for device attributes (role, operating_system, hardware)
- Uses circuit_info.csv for circuit/interface information
- No Skynet queries
- No NetWhoAmI service calls
- No testbed isolation (unused_interfaces is always empty)
- IXIA circuits are identified by neighbor_platform="ixia"
"""

import typing as t

from neteng.test_infra.dne.taac.constants import TestDevice, TestTopology
from taac.oss_topology_info.circuit_info_loader import (
    get_circuits_for_hostname_oss,
)
from taac.oss_topology_info.device_info_loader import (
    get_hardware_from_hostname_oss,
    get_operating_system_from_hostname_oss,
    get_role_from_hostname_oss,
)
from taac.utils.oss_taac_lib_utils import (
    ConsoleFileLogger,
    get_root_logger,
    to_fb_fqdn,
)
from taac.test_as_a_config import types as taac_types


def get_display_name(hostname: str, interface_name: str, use_fbqn: bool = True) -> str:
    return f"{to_fb_fqdn(hostname) if use_fbqn else hostname}:{interface_name}"


def _create_switch_attributes_oss(hostname: str) -> taac_types.SwitchAttributes:
    """
    Create SwitchAttributes from OSS CSV data using flat string fields.

    Reads device_info.csv to populate:
    - device_name (FQDN hostname)
    - role (RSW, FSW, SSW, etc.)
    - operating_system (FBOSS, EOS, CISCO)
    - hardware (FUJI, MINIPACK2, etc.)
    """
    role_str = get_role_from_hostname_oss(hostname)
    os_str = get_operating_system_from_hostname_oss(hostname)
    hw_str = get_hardware_from_hostname_oss(hostname)

    return taac_types.SwitchAttributes(
        device_name=to_fb_fqdn(hostname),
        role=role_str or "",
        operating_system=os_str or "",
        hardware=hw_str or "",
        tags=[],
    )


class OssTestBedChunker:
    """
    OSS-compatible TestBedChunker implementation.

    This class provides the same interface as TestBedChunker but uses
    static CSV data instead of Meta-internal services for topology discovery.

    CSV Files Required:
    - device_info.csv: hostname,ipv6_address,ipv4_address,mac_address,role,operating_system,hardware
    - circuit_info.csv: hostname,local_interface,local_platform,local_parent_interface,
                        neighbor_hostname,neighbor_interface,neighbor_platform,
                        neighbor_parent_interface,status,role

    Circuit Modeling:
    - Device A <-> Device B: Both perspectives should be in circuit_info.csv
      - Row 1: A's interface -> B (neighbor)
      - Row 2: B's interface -> A (neighbor)
    - Device A <-> IXIA: Only device side, neighbor_hostname="ixia", neighbor_platform="ixia"
    """

    def __init__(
        self,
        hostnames: t.List[str],
        logger: t.Optional[ConsoleFileLogger] = None,
    ) -> None:
        self.logger = logger or get_root_logger()
        self.hostnames = hostnames
        self.test_topology: t.Optional[TestTopology] = None

    async def async_create_test_bed(self) -> TestTopology:
        """
        Create test bed topology using OSS CSV data sources.

        Produces TestTopology with:
        - TestDevice for each hostname in self.hostnames
        - interfaces: List of TestInterface for non-IXIA circuits to other devices in group
        - ixia_interfaces: List of TestInterface for IXIA circuits
        - unused_interfaces: Empty list (no testbed isolation in OSS mode)
        - attributes: SwitchAttributes with role, operating_system, hardware from CSV

        Returns:
            TestTopology: The discovered test bed topology
        """
        test_devices = []

        for hostname in self.hostnames:
            # Get device attributes from CSV
            switch_attributes = _create_switch_attributes_oss(hostname)

            # Get all circuits for this device from CSV
            circuits = get_circuits_for_hostname_oss(hostname)

            interfaces: t.List[taac_types.TestInterface] = []
            ixia_interfaces: t.List[taac_types.TestInterface] = []

            for circuit in circuits:
                # Determine if this device is the a_endpoint or z_endpoint
                if circuit.a_endpoint.device.name.lower() == hostname.lower():
                    local_interface = circuit.a_endpoint.name
                    neighbor_hostname = circuit.z_endpoint.device.name
                    neighbor_interface = circuit.z_endpoint.name
                    neighbor_platform = (
                        circuit.z_endpoint.device.desired_platform.os_type_name or ""
                    )
                elif circuit.z_endpoint.device.name.lower() == hostname.lower():
                    local_interface = circuit.z_endpoint.name
                    neighbor_hostname = circuit.a_endpoint.device.name
                    neighbor_interface = circuit.a_endpoint.name
                    neighbor_platform = (
                        circuit.a_endpoint.device.desired_platform.os_type_name or ""
                    )
                else:
                    continue

                is_ixia = "ixia" in neighbor_platform.lower()

                if is_ixia:
                    # IXIA interfaces: match internal test_bed_chunker format
                    # (no display_name, switch_name, or neighbor_display_name)
                    test_interface = taac_types.TestInterface(
                        interface_name=local_interface,
                        switch_attributes=switch_attributes,
                        neighbor_switch_name="ixia",
                        neighbor_interface_name=neighbor_interface,
                    )
                    ixia_interfaces.append(test_interface)
                else:
                    # Check if neighbor is in our test group
                    neighbor_in_group = any(
                        to_fb_fqdn(neighbor_hostname) == to_fb_fqdn(h)
                        for h in self.hostnames
                    )

                    if neighbor_in_group:
                        test_interface = taac_types.TestInterface(
                            interface_name=local_interface,
                            switch_name=hostname,
                            display_name=get_display_name(hostname, local_interface),
                            switch_attributes=switch_attributes,
                            neighbor_switch_name=neighbor_hostname,
                            neighbor_interface_name=neighbor_interface,
                            neighbor_display_name=get_display_name(
                                neighbor_hostname, neighbor_interface
                            ),
                        )
                        interfaces.append(test_interface)

            test_device = TestDevice(
                name=hostname,
                attributes=switch_attributes,
                interfaces=interfaces,
                ixia_interfaces=ixia_interfaces,
                unused_interfaces=[],
            )
            test_devices.append(test_device)

            self.logger.debug(
                f"Created TestDevice for {hostname}: "
                f"{len(interfaces)} interface(s), {len(ixia_interfaces)} IXIA interface(s)"
            )

        self.test_topology = TestTopology(devices=test_devices)
        self.logger.info(
            f"Created TestTopology with {len(test_devices)} device(s) from CSV data"
        )
        # pyre-fixme[7]: Expected `TestTopology` but got `Optional[TestTopology]`.
        return self.test_topology

    async def async_isolate_test_bed_connectivity(self) -> None:
        """No-op in OSS mode. Testbed isolation is not supported."""
        self.logger.info("Skipping testbed isolation (not supported in OSS mode)")

    async def async_restore_test_bed_connectivity(self) -> None:
        """No-op in OSS mode. Testbed isolation is not supported."""
        self.logger.info("Skipping testbed restoration (not supported in OSS mode)")

    def get_run_info(self) -> str:
        """Return string with run metadata for OSS mode."""
        return "OSS Mode - No group ID or unixname available"
