# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-strict

"""
Task for configuring secondary IP addresses on Arista interfaces.

This task automatically generates and configures secondary IPv4/IPv6 addresses
on device interfaces to support large-scale BGP peer testing.
"""

import typing as t

from taac.tasks.base_task import BaseTask
from taac.utils import arista_utils
from taac.utils.driver_factory import async_get_device_driver
from taac.utils.oss_taac_lib_utils import ConsoleFileLogger


class InterfaceIpConfigurationTask(BaseTask):
    """
    Task to configure secondary IP addresses on Arista interfaces.

    This task is useful for tests requiring many BGP peers (e.g., 140+ EBGP peers,
    500+ IBGP peers), where manual IP configuration is error-prone.

    The task:
    1. Saves running config backup (always, for safety)
    2. Clears existing IP addresses on the interface (optional)
    3. Generates secondary IP addresses based on peer count
    4. Applies configuration using Arista driver
    5. Validates configuration succeeded
    6. Auto-restores backup on failure

    The backup is automatic and always happens to protect device configuration.
    The backup file is stored in task data and can be used by cleanup tasks.

    Example Usage:
        In test config setup_tasks:
        ```python
        setup_tasks=[
            Task(
                task_name="configure_ebgp_interface_ips",
                task_type="interface_ip_configuration",
                params=Params(
                    json_params=json.dumps({
                        "interface": "Ethernet3/1/1",
                        "ipv4_base_network": "10.163.28",
                        "ipv6_base_network": "2401:db00:e50d:11:8",
                        "peer_count": 140,
                        "address_families": ["ipv6"],
                        "clear_existing": True,
                    })
                ),
            ),
        ]

        # Cleanup task can restore the backup
        teardown_tasks=[
            Task(
                task_name="restore_original_config",
                task_type="interface_ip_cleanup",
                params=Params(
                    json_params=json.dumps({
                        "interfaces": ["Ethernet3/1/1"],
                        "restore_from_backup": True,  # Restores saved backup
                    })
                ),
            ),
        ]
        ```
    """

    # pyrefly: ignore [bad-override-mutable-attribute]
    NAME: str = "interface_ip_configuration"

    def __init__(
        self,
        hostname: t.Optional[str] = None,
        description: t.Optional[str] = None,
        ixia: t.Optional[t.Any] = None,
        logger: t.Optional[ConsoleFileLogger] = None,
        shared_data: t.Optional[t.Dict[t.Any, t.Any]] = None,
    ) -> None:
        super().__init__(hostname, description, ixia, logger, shared_data)

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        """
        Configure secondary IP addresses on an interface.

        Args:
            params: Configuration dictionary containing:
                - interface: Interface name (e.g., "Ethernet3/1/1")
                - ipv4_base_network: IPv4 base network (e.g., "10.163.28")
                - ipv6_base_network: IPv6 base network (e.g., "2401:db00:e50d:11:8")
                - peer_count: Number of BGP peers (determines IP address count)
                - address_families: List of address families (["ipv4"], ["ipv6"], or both)
                - clear_existing: Clear existing IPs before configuring (default: True)
                - all_secondary: If True, add ALL IPv4 addresses as secondary
                    (no primary). Use when appending to an interface that already
                    has a primary address. (default: False)
                - ipv4_start_offset: Starting offset for IPv4 addresses (default: 10)
                - ipv6_start_offset: Starting offset for IPv6 addresses (default: 0x10)

        Raises:
            ValueError: If required parameters are missing or configuration fails

        Note:
            This task automatically saves a backup of the running config before making
            changes. The backup file path is stored in self._data["backup_file"] and
            can be used by cleanup tasks to restore the original configuration.
        """
        # Extract parameters
        interface = params.get("interface")
        if not interface:
            raise ValueError("Missing required parameter: interface")

        ipv4_base_network = params.get("ipv4_base_network")
        ipv6_base_network = params.get("ipv6_base_network")
        peer_count = params.get("peer_count")
        if peer_count is None:
            raise ValueError("Missing required parameter: peer_count")

        address_families = params.get("address_families", ["ipv6"])
        clear_existing = params.get("clear_existing", True)
        all_secondary = params.get("all_secondary", False)
        ipv4_start_offset = params.get("ipv4_start_offset", 10)
        ipv6_start_offset = params.get("ipv6_start_offset", 0x10)

        # Get device driver
        # pyre-fixme[6]: For 1st argument expected `str` but got `Optional[str]`.
        driver = await async_get_device_driver(self.hostname)

        # Always save running config before making changes (for safety)
        self.logger.info("Saving running config before making changes...")
        backup_file = await arista_utils.save_running_config(
            driver, backup_name=None, logger_instance=self.logger
        )
        self.logger.info(f"  Backup saved to: {backup_file}")
        # Store backup file in SHARED data (cross-task communication)
        # Use _shared_data directly instead of _data for data that needs to be shared
        if self._shared_data is not None:
            # Store with a key that cleanup task can find
            backup_key = f"interface_ip_backup__{interface}"
            self._shared_data[backup_key] = backup_file
            self.logger.info(f"  Stored backup reference: {backup_key}")
        else:
            # Fallback to local _data if no shared_data (shouldn't happen in framework)
            self._data["backup_file"] = backup_file

        try:
            self.logger.info("=" * 80)
            self.logger.info(f"Configuring secondary IPs on {interface}")
            self.logger.info("=" * 80)
            self.logger.info(f"  Peer count: {peer_count}")
            self.logger.info(f"  Address families: {address_families}")
            self.logger.info(f"  Clear existing IPs: {clear_existing}")

            # Generate IP addresses
            ipv4_addresses = None
            ipv6_addresses = None

            if "ipv4" in address_families:
                if not ipv4_base_network:
                    raise ValueError(
                        "ipv4_base_network required when address_families includes ipv4"
                    )
                self.logger.info(f"  Generating {peer_count} IPv4 addresses...")
                self.logger.info(f"    Base network: {ipv4_base_network}")
                ipv4_addresses = arista_utils.generate_ipv4_secondary_addresses(
                    ipv4_base_network, peer_count, ipv4_start_offset
                )
                self.logger.info(
                    f" Generated: {ipv4_addresses[0]} ... {ipv4_addresses[-1]}"
                )

            if "ipv6" in address_families:
                if not ipv6_base_network:
                    raise ValueError(
                        "ipv6_base_network required when address_families includes ipv6"
                    )
                self.logger.info(f"  Generating {peer_count} IPv6 addresses...")
                self.logger.info(f"    Base network: {ipv6_base_network}")
                ipv6_addresses = arista_utils.generate_ipv6_secondary_addresses(
                    ipv6_base_network, peer_count, ipv6_start_offset
                )
                self.logger.info(
                    f" Generated: {ipv6_addresses[0]} ... {ipv6_addresses[-1]}"
                )

            # Apply configuration
            self.logger.info(f" Applying configuration to {interface}...")
            await arista_utils.configure_interface_secondary_ips(
                driver,
                interface,
                ipv4_addresses=ipv4_addresses,
                ipv6_addresses=ipv6_addresses,
                clear_existing=clear_existing,
                all_secondary=all_secondary,
                logger_instance=self.logger,
            )

            self.logger.info("=" * 80)
            self.logger.info(
                f"Successfully configured {interface}: "
                f"{len(ipv4_addresses or [])} IPv4, {len(ipv6_addresses or [])} IPv6"
            )
            self.logger.info("=" * 80)

        except Exception:
            # If backup was created and config failed, restore it automatically
            self.logger.error("Configuration failed, restoring backup...")
            try:
                await arista_utils.restore_running_config(
                    driver, backup_file, self.logger
                )
                self.logger.info(f"  Restored config from: {backup_file}")
            except Exception as restore_error:
                self.logger.error(f"Failed to restore backup: {restore_error}")
            raise


class InterfaceIpCleanupTask(BaseTask):
    """
    Teardown task to clean up secondary IP addresses configured by InterfaceIpConfigurationTask.

    This task can either:
    1. Clean up IPs manually (remove all or only secondaries)
    2. Restore the original config from backup (if InterfaceIpConfigurationTask was used)

    The restore option uses the backup file saved by InterfaceIpConfigurationTask,
    returning the device to its exact pre-test state.

    Example Usage:
        In test config teardown_tasks:
        ```python
        teardown_tasks=[
            # Option 1: Restore from automatic backup (recommended)
            Task(
                task_name="restore_original_config",
                task_type="interface_ip_cleanup",
                params=Params(
                    json_params=json.dumps({
                        "restore_from_backup": True,  # Uses backup from setup task
                    })
                ),
            ),

            # Option 2: Manual cleanup - remove all IPs
            Task(
                task_name="cleanup_ebgp_interface_ips",
                task_type="interface_ip_cleanup",
                params=Params(
                    json_params=json.dumps({
                        "interfaces": ["Ethernet3/1/1", "Ethernet3/1/3"],
                        "keep_primary": False,
                    })
                ),
            ),

            # Option 3: Keep primary, remove only secondaries
            Task(
                task_name="cleanup_test_secondaries",
                task_type="interface_ip_cleanup",
                params=Params(
                    json_params=json.dumps({
                        "interfaces": ["Ethernet3/1/1"],
                        "keep_primary": True,
                    })
                ),
            ),
        ]
        ```
    """

    # pyrefly: ignore [bad-override-mutable-attribute]
    NAME: str = "interface_ip_cleanup"

    def __init__(
        self,
        hostname: t.Optional[str] = None,
        description: t.Optional[str] = None,
        ixia: t.Optional[t.Any] = None,
        logger: t.Optional[ConsoleFileLogger] = None,
        shared_data: t.Optional[t.Dict[t.Any, t.Any]] = None,
    ) -> None:
        super().__init__(hostname, description, ixia, logger, shared_data)

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        """
        Clean up IP addresses from interfaces or restore from backup.

        Args:
            params: Configuration dictionary containing:
                - restore_from_backup: If True, restore config from backup (ignores other params)
                - interfaces: List of interface names to clean up (e.g., ["Ethernet3/1/1"])
                - keep_primary: If True, only remove secondary IPs (default: False)
                - delete_backup: If True, delete backup file after restore (default: True)

        Raises:
            ValueError: If required parameters are missing or cleanup fails
        """
        # Check if we should restore from backup
        restore_from_backup = params.get("restore_from_backup", False)
        delete_backup_after = params.get("delete_backup", True)

        if restore_from_backup:
            # Restore from backup saved by InterfaceIpConfigurationTask
            # Need to determine which interface to restore
            interfaces = params.get("interfaces", [])
            if not interfaces:
                raise ValueError(
                    "restore_from_backup=True requires 'interfaces' parameter "
                    "to identify which backup to restore"
                )

            # Use first interface to look up backup (assuming one backup per config task)
            interface = interfaces[0] if isinstance(interfaces, list) else interfaces

            # Look for backup in shared data first, then fall back to local _data
            backup_file = None
            if self._shared_data is not None:
                backup_key = f"interface_ip_backup__{interface}"
                backup_file = self._shared_data.get(backup_key)
                if backup_file:
                    self.logger.info(f"  Found backup via shared data: {backup_key}")

            # Fallback to local _data for backward compatibility
            if not backup_file:
                backup_file = self._data.get("backup_file")

            if not backup_file:
                raise ValueError(
                    f"No backup file found for interface {interface}. "
                    "restore_from_backup=True requires InterfaceIpConfigurationTask "
                    "to have run first."
                )

            self.logger.info("=" * 80)
            self.logger.info("Restoring Configuration from Backup")
            self.logger.info("=" * 80)
            self.logger.info(f"  Backup file: {backup_file}")

            # Get device driver
            # pyre-fixme[6]: For 1st argument expected `str` but got `Optional[str]`.
            driver = await async_get_device_driver(self.hostname)

            # Restore the backup
            try:
                await arista_utils.restore_running_config(
                    driver, backup_file, self.logger
                )
                self.logger.info(f"✓ Successfully restored config from: {backup_file}")

                # Delete backup file if requested
                if delete_backup_after:
                    await arista_utils.delete_backup_config(
                        driver, backup_file, self.logger
                    )
                    self.logger.info(f"✓ Deleted backup file: {backup_file}")

                self.logger.info("=" * 80)
                return

            except Exception as e:
                error_msg = f"Failed to restore from backup: {e}"
                self.logger.error(error_msg)
                raise ValueError(error_msg) from e

        # Otherwise, do manual cleanup
        # Extract parameters
        interfaces = params.get("interfaces")
        if not interfaces:
            raise ValueError("Missing required parameter: interfaces (list)")

        if not isinstance(interfaces, list):
            interfaces = [interfaces]

        keep_primary = params.get("keep_primary", False)

        self.logger.info("=" * 80)
        self.logger.info("Interface IP Address Cleanup")
        self.logger.info("=" * 80)
        self.logger.info(f"  Interfaces to clean: {', '.join(interfaces)}")
        self.logger.info(f"  Keep primary IP: {keep_primary}")

        # Get device driver
        # pyre-fixme[6]: For 1st argument expected `str` but got `Optional[str]`.
        driver = await async_get_device_driver(self.hostname)

        # Clean up each interface
        for interface in interfaces:
            self.logger.info(f"\n  Cleaning up {interface}...")

            try:
                # Build cleanup commands
                commands = [
                    f"interface {interface}",
                ]

                if keep_primary:
                    # Remove only secondary IPs - need to parse current config
                    self.logger.info(
                        "    Reading current configuration to identify secondary IPs..."
                    )

                    # Get current interface configuration
                    show_cmd = f"show running-config interface {interface}"
                    # pyre-fixme[16]: `AbstractSwitch` has no attribute `run_command`.
                    config_output = await driver.run_command(show_cmd)

                    # Parse for secondary IP addresses
                    secondary_ipv4s = []
                    secondary_ipv6s = []

                    for line in config_output.split("\n"):
                        line = line.strip()

                        # IPv4 secondary: "ip address 10.1.1.2/31 secondary"
                        if "ip address" in line and "secondary" in line:
                            # Extract IP address from line
                            parts = line.split()
                            if len(parts) >= 3:
                                ip_addr = parts[2]  # "ip address X.X.X.X/YY secondary"
                                secondary_ipv4s.append(ip_addr)

                        # IPv6: All IPv6 addresses after first are secondary
                        # We'll remove all IPv6 except the first one
                        if "ipv6 address" in line and "ipv6 address" in line:
                            parts = line.split()
                            if len(parts) >= 3:
                                ipv6_addr = parts[2]
                                secondary_ipv6s.append(ipv6_addr)

                    # Remove secondary IPs
                    if secondary_ipv4s:
                        self.logger.info(
                            f"    Removing {len(secondary_ipv4s)} secondary IPv4 addresses"
                        )
                        for ip in secondary_ipv4s:
                            commands.append(f"no ip address {ip} secondary")

                    if len(secondary_ipv6s) > 1:
                        # Keep first IPv6 (primary), remove others
                        self.logger.info(
                            f"    Removing {len(secondary_ipv6s) - 1} secondary IPv6 addresses"
                        )
                        for ip in secondary_ipv6s[1:]:  # Skip first (primary)
                            commands.append(f"no ipv6 address {ip}")
                    elif len(secondary_ipv6s) == 1:
                        self.logger.info("    Keeping single IPv6 address (primary)")

                    if len(secondary_ipv4s) == 0 and len(secondary_ipv6s) <= 1:
                        self.logger.info("    No secondary IPs to remove")
                        continue

                else:
                    # Remove all IP addresses
                    self.logger.info("    Removing all IP addresses")
                    commands.extend(
                        [
                            "no ip address",
                            "no ipv6 address",
                        ]
                    )

                # Apply cleanup configuration
                config_block = "\n".join(commands)
                self.logger.info(f"    Applying cleanup:\n{config_block}")

                await driver.async_run_cmd_on_shell(f"configure\n{config_block}\nend")

                self.logger.info(f"    Cleaned up {interface}")

            except Exception as e:
                error_msg = f"Failed to clean up {interface}: {e}"
                self.logger.error(error_msg)
                # Don't raise - try to clean up other interfaces
                continue

        self.logger.info("\n" + "=" * 80)
        self.logger.info(
            f"Interface cleanup completed for {len(interfaces)} interface(s)"
        )
        self.logger.info("=" * 80)
