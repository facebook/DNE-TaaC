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


async def _remove_all_interface_ip_addresses(
    driver: t.Any,
    interface: str,
    logger: ConsoleFileLogger,
) -> None:
    config_block = f"interface {interface}\nno ip address\nno ipv6 address"
    logger.info(f"    Applying cleanup:\n{config_block}")
    await driver.async_run_cmd_on_shell(f"configure\n{config_block}\nend")


class InterfaceIpConfigurationTask(BaseTask):
    """
    Task to configure secondary IP addresses on Arista interfaces.

    This task is useful for tests requiring many BGP peers (e.g., 140+ EBGP peers,
    500+ IBGP peers), where manual IP configuration is error-prone.

    The task:
    1. Optionally saves or reuses a running config backup
    2. Clears existing IP addresses on the interface (optional)
    3. Generates secondary IP addresses based on peer count
    4. Applies configuration using Arista driver
    5. Validates configuration succeeded
    6. Restores the optional backup or removes interface addresses on failure

    When backup is enabled, the first task for an interface saves the backup.
    Repeated tasks reuse that snapshot. The task stores the file for cleanup.

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

    def _generate_secondary_addresses(
        self,
        family: str,
        base_network: t.Optional[str],
        peer_count: int,
        start_offset: int,
    ) -> t.List[str]:
        """
        Generate secondary addresses for a single address family ("ipv4"/"ipv6").

        peer_count may legitimately be 0 (e.g. ingress-only setups with no iBGP
        egress), which yields an empty list; the caller still clears the
        interface so no addresses are applied.
        """
        if not base_network:
            raise ValueError(
                f"{family}_base_network required when address_families includes {family}"
            )

        display = "IPv4" if family == "ipv4" else "IPv6"
        self.logger.info(f"  Generating {peer_count} {display} addresses...")
        self.logger.info(f"    Base network: {base_network}")

        if family == "ipv4":
            addresses = arista_utils.generate_ipv4_secondary_addresses(
                base_network, peer_count, start_offset
            )
        else:
            addresses = arista_utils.generate_ipv6_secondary_addresses(
                base_network, peer_count, start_offset
            )

        if addresses:
            self.logger.info(f" Generated: {addresses[0]} ... {addresses[-1]}")

        return addresses

    async def _get_or_create_backup(self, driver: t.Any, interface: str) -> str:
        backup_key = f"interface_ip_backup__{interface}"
        backup_file = (
            self._shared_data.get(backup_key) if self._shared_data is not None else None
        )
        if backup_file:
            if await arista_utils.backup_config_exists(driver, backup_file):
                self.logger.info(f"Reusing original backup: {backup_file}")
                return backup_file
            self.logger.warning(
                f"Stored backup no longer exists; creating a new one: {backup_file}"
            )

        self.logger.info("Saving running config before making changes...")
        backup_file = await arista_utils.save_running_config(
            driver, backup_name=None, logger_instance=self.logger
        )
        self.logger.info(f"  Backup saved to: {backup_file}")
        if self._shared_data is not None:
            self._shared_data[backup_key] = backup_file
            self.logger.info(f"  Stored backup reference: {backup_key}")
        else:
            self._data["backup_file"] = backup_file
        return backup_file

    async def _recover_from_configuration_failure(
        self,
        driver: t.Any,
        interface: str,
        backup_file: str | None,
        configuration_error: Exception,
    ) -> None:
        if backup_file is not None:
            self.logger.error("Configuration failed, restoring backup...")
            try:
                await arista_utils.restore_running_config(
                    driver, backup_file, self.logger
                )
                self.logger.info(f"  Restored config from: {backup_file}")
            except Exception as restore_error:
                self.logger.error(f"Failed to restore backup: {restore_error}")
            return

        self.logger.error("Configuration failed, removing interface IP addresses...")
        try:
            await _remove_all_interface_ip_addresses(driver, interface, self.logger)
        except Exception as cleanup_error:
            self.logger.error(
                f"Failed to remove interface IP addresses: {cleanup_error}"
            )
            raise configuration_error from cleanup_error

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
                - save_running_config_backup: Save the running configuration before
                    applying addresses (default: True)

        Raises:
            ValueError: If required parameters are missing or configuration fails

        Note:
            By default, this task saves the first running-config backup for each
            interface. Set save_running_config_backup=False when teardown removes
            the configured addresses directly.
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

        save_running_config_backup = params.get("save_running_config_backup", True)
        backup_file = (
            await self._get_or_create_backup(driver, interface)
            if save_running_config_backup
            else None
        )
        if not save_running_config_backup:
            self.logger.info(
                "Skipping running config backup; interface teardown owns cleanup"
            )

        try:
            self.logger.info("=" * 80)
            self.logger.info(f"Configuring secondary IPs on {interface}")
            self.logger.info("=" * 80)
            self.logger.info(f"  Peer count: {peer_count}")
            self.logger.info(f"  Address families: {address_families}")
            self.logger.info(f"  Clear existing IPs: {clear_existing}")

            # Generate IP addresses. peer_count may legitimately be 0 (e.g.
            # ingress-only setups with no iBGP egress), which yields an empty
            # address list; the interface is still cleared below when
            # clear_existing is set, so no addresses are applied.
            ipv4_addresses = None
            ipv6_addresses = None

            if "ipv4" in address_families:
                ipv4_addresses = self._generate_secondary_addresses(
                    "ipv4", ipv4_base_network, peer_count, ipv4_start_offset
                )

            if "ipv6" in address_families:
                ipv6_addresses = self._generate_secondary_addresses(
                    "ipv6", ipv6_base_network, peer_count, ipv6_start_offset
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

        except Exception as configuration_error:
            await self._recover_from_configuration_failure(
                driver, interface, backup_file, configuration_error
            )
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

    async def _restore_from_backup(
        self, params: t.Dict[str, t.Any], delete_backup_after: bool
    ) -> None:
        interfaces = params.get("interfaces", [])
        if not interfaces:
            raise ValueError(
                "restore_from_backup=True requires 'interfaces' parameter "
                "to identify which backup to restore"
            )

        interface = interfaces[0] if isinstance(interfaces, list) else interfaces
        backup_file = None
        backup_key = None
        if self._shared_data is not None:
            backup_key = f"interface_ip_backup__{interface}"
            backup_file = self._shared_data.get(backup_key)
            if backup_file:
                self.logger.info(f"  Found backup via shared data: {backup_key}")

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

        # pyre-fixme[6]: For 1st argument expected `str` but got `Optional[str]`.
        driver = await async_get_device_driver(self.hostname)
        try:
            await arista_utils.restore_running_config(driver, backup_file, self.logger)
            self.logger.info(f"✓ Successfully restored config from: {backup_file}")

            if delete_backup_after:
                await arista_utils.delete_backup_config(
                    driver, backup_file, self.logger
                )
                self.logger.info(f"✓ Deleted backup file: {backup_file}")
                if self._shared_data is not None and backup_key is not None:
                    self._shared_data.pop(backup_key, None)

            self.logger.info("=" * 80)
        except Exception as error:
            error_msg = f"Failed to restore from backup: {error}"
            self.logger.error(error_msg)
            raise ValueError(error_msg) from error

    @staticmethod
    def _extract_secondary_addresses(
        config_output: str,
    ) -> tuple[list[str], list[str]]:
        secondary_ipv4s = []
        secondary_ipv6s = []
        for raw_line in config_output.split("\n"):
            line = raw_line.strip()
            parts = line.split()
            if "ip address" in line and "secondary" in line and len(parts) >= 3:
                secondary_ipv4s.append(parts[2])
            if "ipv6 address" in line and len(parts) >= 3:
                secondary_ipv6s.append(parts[2])
        return secondary_ipv4s, secondary_ipv6s

    async def _cleanup_interface(
        self, driver: t.Any, interface: str, keep_primary: bool
    ) -> None:
        if not keep_primary:
            self.logger.info("    Removing all IP addresses")
            await _remove_all_interface_ip_addresses(driver, interface, self.logger)
            self.logger.info(f"    Cleaned up {interface}")
            return

        self.logger.info(
            "    Reading current configuration to identify secondary IPs..."
        )
        # pyre-fixme[16]: `AbstractSwitch` has no attribute `run_command`.
        config_output = await driver.run_command(
            f"show running-config interface {interface}"
        )
        secondary_ipv4s, secondary_ipv6s = self._extract_secondary_addresses(
            config_output
        )
        commands = [f"interface {interface}"]

        if secondary_ipv4s:
            self.logger.info(
                f"    Removing {len(secondary_ipv4s)} secondary IPv4 addresses"
            )
            commands.extend(
                f"no ip address {address} secondary" for address in secondary_ipv4s
            )

        if len(secondary_ipv6s) > 1:
            self.logger.info(
                f"    Removing {len(secondary_ipv6s) - 1} secondary IPv6 addresses"
            )
            commands.extend(
                f"no ipv6 address {address}" for address in secondary_ipv6s[1:]
            )
        elif secondary_ipv6s:
            self.logger.info("    Keeping single IPv6 address (primary)")

        if not secondary_ipv4s and len(secondary_ipv6s) <= 1:
            self.logger.info("    No secondary IPs to remove")
            return

        config_block = "\n".join(commands)
        self.logger.info(f"    Applying cleanup:\n{config_block}")
        await driver.async_run_cmd_on_shell(f"configure\n{config_block}\nend")
        self.logger.info(f"    Cleaned up {interface}")

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
        restore_from_backup = params.get("restore_from_backup", False)
        delete_backup_after = params.get("delete_backup", True)

        if restore_from_backup:
            await self._restore_from_backup(params, delete_backup_after)
            return

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

        # pyre-fixme[6]: For 1st argument expected `str` but got `Optional[str]`.
        driver = await async_get_device_driver(self.hostname)

        for interface in interfaces:
            self.logger.info(f"\n  Cleaning up {interface}...")
            try:
                await self._cleanup_interface(driver, interface, keep_primary)
            except Exception as error:
                error_msg = f"Failed to clean up {interface}: {error}"
                self.logger.error(error_msg)

        self.logger.info("\n" + "=" * 80)
        self.logger.info(
            f"Interface cleanup completed for {len(interfaces)} interface(s)"
        )
        self.logger.info("=" * 80)
