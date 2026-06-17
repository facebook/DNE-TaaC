# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""
EOS-specific tasks for TAAC.

Tasks in this module operate on Arista EOS devices using the AristaSwitch driver
directly (EOS CLI via FCR), rather than COOP patchers used by FBOSS tasks.
"""

import ipaddress
import typing as t

from taac.tasks.base_task import BaseTask
from taac.utils import arista_utils


class CreateEosBgpPeerGroup(BaseTask):
    """
    Create a BGP peer group on an Arista EOS device.

    This task wraps AristaSwitch.async_create_bgp_peer_group() to create a BGP
    peer group via EOS CLI commands. It is the EOS ar-bgp equivalent of the FBOSS
    add_peer_group_patcher COOP patcher.

    Example params:
        {
            "hostname": "bag002.snc1",
            "peer_group_name": "PEERGROUP_BAG_STSW_V6",
            "remote_as": 65000,
            "description": "BGP peering to STSW IPv6",
            "route_map_in": "PROPAGATE_BAG_STSW_IN",
            "route_map_out": "PROPAGATE_BAG_STSW_OUT",
            "next_hop_self": true,
            "graceful_restart_helper": true,
            "timers_keepalive": 10,
            "timers_holdtime": 30,
            "ipv4_unicast": false,
            "ipv6_unicast": true,
            "maximum_routes": 90000,
            "maximum_routes_warning_limit": 0,
            "maximum_routes_warning_only": true
        }
    """

    NAME = "create_eos_bgp_peer_group"

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        from taac.internal.driver.arista_switch import (
            AristaSwitch,
        )

        hostname = params["hostname"]
        peer_group_name = params["peer_group_name"]
        register = params.get("register", True)

        driver = AristaSwitch(hostname, logger=self.logger)

        if not register:
            self.logger.info(
                f"Removing BGP peer group '{peer_group_name}' on {hostname}"
            )
            await driver.async_remove_bgp_peer_group(peer_group_name)
            self.logger.info(
                f"Successfully removed BGP peer group '{peer_group_name}' on {hostname}"
            )
            return

        kwargs: t.Dict[str, t.Any] = {"peer_group_name": peer_group_name}

        optional_fields = [
            "remote_as",
            "description",
            "update_source",
            "activate",
            "ipv4_unicast",
            "ipv6_unicast",
            "route_map_in",
            "route_map_out",
            "next_hop_self",
            "out_delay",
            "timers_keepalive",
            "timers_holdtime",
            "send_community",
            "maximum_routes",
            "maximum_routes_warning_limit",
            "maximum_routes_warning_only",
            "local_as",
            "local_as_no_prepend",
            "local_as_replace_as",
            "local_as_fallback",
            "graceful_restart_helper",
            "send_community_link_bandwidth",
            "link_bandwidth_aggregate",
        ]

        for field in optional_fields:
            if field in params:
                kwargs[field] = params[field]

        self.logger.info(f"Creating BGP peer group '{peer_group_name}' on {hostname}")
        await driver.async_create_bgp_peer_group(**kwargs)
        self.logger.info(
            f"Successfully created BGP peer group '{peer_group_name}' on {hostname}"
        )


class AddEosBgpPrefixListToPeerGroup(BaseTask):
    """
    Add a prefix-list and attach it to one or more BGP peer groups on an Arista
    EOS device.

    This is the EOS ar-bgp equivalent of the FBOSS
    add_bgp_policy_match_prefix_to_propagate_routes COOP patcher. Instead of
    modifying BGP++ policy terms, it creates an EOS prefix-list and attaches it
    to peer group(s) under the appropriate address-family.

    peer_group_name can be a single string or a list of strings. When a list is
    provided, the prefix-list is attached to / detached from all peer groups in
    a single CLI transaction. On removal, the prefix-list is detached from every
    peer group before deleting the prefix-list itself.

    When register=False, removes the prefix-list attachment and deletes the
    prefix-list.

    Example params:
        {
            "hostname": "bag002.snc1",
            "prefix_list_name": "ALLOW_BAG_STSW_V6_PREFIXES",
            "prefix": "5000::/16",
            "peer_group_name": ["PEERGROUP_BAG_STSW_V6", "PEERGROUP_BAG_CBAG_V6"],
            "direction": "in",
            "prefix_length": 128,
            "seq": 10
        }
    """

    NAME = "add_eos_bgp_prefix_list_to_peer_group"

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        import ipaddress as ipaddress_mod

        from taac.internal.driver.arista_switch import (
            AristaSwitch,
        )

        hostname = params["hostname"]
        prefix_list_name = params["prefix_list_name"]
        route_map_name = params.get("route_map_name")
        route_map_names = (
            [route_map_name] if isinstance(route_map_name, str) else route_map_name
        )
        route_map_seq = params.get("route_map_seq")
        register = params.get("register", True)

        driver = AristaSwitch(hostname, logger=self.logger)

        if not register:
            is_ipv6 = params.get("is_ipv6", True)
            if "prefix" in params:
                network = ipaddress_mod.ip_network(params["prefix"], strict=False)
                is_ipv6 = network.version == 6

            self.logger.info(
                f"Removing prefix-list '{prefix_list_name}' from "
                f"{route_map_names} on {hostname}"
            )
            await driver.async_remove_bgp_prefix_list_from_peer_group(
                prefix_list_name=prefix_list_name,
                is_ipv6=is_ipv6,
                # pyrefly: ignore [bad-argument-type]
                route_map_names=route_map_names,
                route_map_seq=route_map_seq,
            )
            self.logger.info(
                f"Successfully removed prefix-list '{prefix_list_name}' from "
                f"{route_map_names} on {hostname}"
            )
            return

        prefix = params["prefix"]
        prefix_length = params.get("prefix_length")
        seq = params.get("seq")

        self.logger.info(
            f"Adding prefix-list '{prefix_list_name}' with prefix '{prefix}' "
            f"to {route_map_names} on {hostname}"
        )
        await driver.async_add_bgp_prefix_list_to_peer_group(
            prefix_list_name=prefix_list_name,
            prefix=prefix,
            prefix_length=prefix_length,
            seq=seq,
            # pyrefly: ignore [bad-argument-type]
            route_map_names=route_map_names,
            route_map_seq=route_map_seq,
        )
        self.logger.info(
            f"Successfully added prefix-list '{prefix_list_name}' to "
            f"{route_map_names} on {hostname}"
        )


class ConfigureEosParallelBgpPeers(BaseTask):
    """
    Configure parallel BGP peers on an Arista EOS device.

    This is the EOS equivalent of ConfigureParallelBgpPeers (which uses COOP
    patchers for FBOSS devices). It directly configures the Arista switch by:
    1. Assigning IP addresses to the specified interfaces
    2. Creating BGP neighbor configurations for each peer

    Supports multiple sessions with multiple IPs on the same interface.

    Example params:
        {
            "hostname": "bag002.snc1",
            "config_json": {
                "Ethernet3/25/1": [
                    {
                        "starting_ip": "2401:db00:e50d:11:8::10",
                        "increment_ip": "::2",
                        "gateway_starting_ip": "2401:db00:e50d:11:8::11",
                        "gateway_increment_ip": "::2",
                        "num_sessions": 100,
                        "remote_as_4_byte": 65000,
                        "remote_as_4_byte_step": 0,
                        "peer_group_name": "PEERGROUP_EBGP_V6",
                        "prefix_length": 127,
                        "description": "IXIA eBGP peer",
                        "ipv4_unicast": false,
                        "ipv6_unicast": true,
                        "all_secondary": false,                 # Required only in case of IPv4 addresses
                        "clear_existing": false,
                        "use_peer_group_syntax": false,         # TODO: Remove this once we have a way to detect peer group syntax, True by default
                    }
                ]
            }
        }
    """

    NAME = "configure_eos_parallel_bgp_peers"

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        from taac.internal.driver.arista_switch import (
            AristaSwitch,
        )

        hostname = params["hostname"]

        # Flag to either add new bgp peers or remove existing bgp peers
        register = params.get("register", True)
        config_json = self.merge_config(params)

        driver = AristaSwitch(hostname, logger=self.logger)

        for interface, configs in config_json.items():
            all_ipv4_ips: t.List[str] = []
            all_ipv6_ips: t.List[str] = []
            bgp_neighbor_args = []

            for config in configs:
                num_sessions = config["num_sessions"]
                starting_ip = config["starting_ip"]
                increment_ip = config["increment_ip"]
                gateway_starting_ip = config["gateway_starting_ip"]
                gateway_increment_ip = config["gateway_increment_ip"]
                prefix_length = config["prefix_length"]
                remote_as_4_byte = config["remote_as_4_byte"]
                remote_as_4_byte_step = config.get("remote_as_4_byte_step", 0)

                local_addresses = self.create_ip_addresses(
                    starting_ip, increment_ip, num_sessions
                )
                peer_addresses = self.create_ip_addresses(
                    gateway_starting_ip, gateway_increment_ip, num_sessions
                )

                # Collect local IPs for interface assignment, separated by family
                for addr in local_addresses:
                    ip_with_prefix = f"{addr}/{prefix_length}"
                    if isinstance(ipaddress.ip_address(addr), ipaddress.IPv4Address):
                        all_ipv4_ips.append(ip_with_prefix)
                    else:
                        all_ipv6_ips.append(ip_with_prefix)

                # Collect BGP neighbor configs
                config_only_interface_ip = config.get("config_only_interface_ip", False)
                if not config_only_interface_ip:
                    for i, peer_addr in enumerate(peer_addresses):
                        remote_asn = remote_as_4_byte + i * remote_as_4_byte_step
                        bgp_neighbor_args.append(
                            self._build_bgp_neighbor_kwargs(
                                config, peer_addr, remote_asn, interface
                            )
                        )
            if not register:
                # remove all bgp peers
                if bgp_neighbor_args:
                    self.logger.info(
                        f"Removing {len(bgp_neighbor_args)} BGP neighbors on {interface}"
                    )
                    for kwargs in bgp_neighbor_args:
                        await driver.async_remove_bgp_neighbor(kwargs["peer_ip_addr"])

                # remove all secondary ips
                self.logger.info(f"Removing secondary IPs on {interface}")
                await arista_utils.clear_interface_secondary_ips(
                    driver,
                    interface,
                    ipv4_addresses=all_ipv4_ips or None,
                    ipv6_addresses=all_ipv6_ips or None,
                    clear_existing=configs[0].get("clear_existing", False),
                    all_secondary=configs[0].get("all_secondary", False),
                    logger_instance=self.logger,
                )
                continue
            # Step 1: Assign IPs to the interface
            total_ips = len(all_ipv4_ips) + len(all_ipv6_ips)
            self.logger.info(f"Configuring {total_ips} IP addresses on {interface}")
            await arista_utils.configure_interface_secondary_ips(
                driver,
                interface,
                ipv4_addresses=all_ipv4_ips or None,
                ipv6_addresses=all_ipv6_ips or None,
                clear_existing=configs[0].get("clear_existing", False),
                all_secondary=configs[0].get("all_secondary", False),
                logger_instance=self.logger,
            )

            # Step 2: Create BGP neighbors
            if bgp_neighbor_args:
                self.logger.info(
                    f"Creating {len(bgp_neighbor_args)} BGP neighbors on {interface}"
                )
                for kwargs in bgp_neighbor_args:
                    await driver.async_create_bgp_neighbor(**kwargs)

        self.logger.info(f"Finished configuring EOS parallel BGP peers on {hostname}")

    def merge_config(
        self, params: t.Dict[str, t.Any]
    ) -> t.Dict[str, t.List[t.Dict[str, t.Any]]]:
        """Merge config_json from peer_configs list or parse single config_json."""
        import json

        if "peer_configs" in params and params["peer_configs"]:
            config_json: t.Dict[str, t.List[t.Dict[str, t.Any]]] = {}
            for peer_config in params["peer_configs"]:
                peer_config_json = json.loads(peer_config["config_json"])
                for interface, configs in peer_config_json.items():
                    if interface in config_json:
                        config_json[interface].extend(configs)
                    else:
                        config_json[interface] = configs
            return config_json
        else:
            return json.loads(params["config_json"])

    def create_ip_addresses(
        self,
        starting_ip: str,
        increment_ip: str,
        count: int,
    ) -> t.List[str]:
        starting_ip_int = int(ipaddress.ip_address(starting_ip))
        increment_ip_int = int(ipaddress.ip_address(increment_ip))
        ip_addresses = []
        for i in range(count):
            new_address = str(
                ipaddress.ip_address(starting_ip_int + increment_ip_int * i)
            )
            ip_addresses.append(new_address)
        return ip_addresses

    def _build_bgp_neighbor_kwargs(
        self,
        config: t.Dict[str, t.Any],
        peer_addr: str,
        remote_asn: int,
        interface: str,
    ) -> t.Dict[str, t.Any]:
        """Build keyword arguments for async_create_bgp_neighbor from config dict."""
        kwargs: t.Dict[str, t.Any] = {
            "peer_ip_addr": ipaddress.ip_address(peer_addr),
            "remote_as": remote_asn,
            "update_source": interface,
        }
        if config.get("description"):
            kwargs["description"] = config["description"]
        if config.get("peer_group_name"):
            kwargs["peer_group"] = config["peer_group_name"]

        kwargs["use_peer_group_syntax"] = config.get("use_peer_group_syntax", True)

        kwargs["ipv4_unicast"] = config.get("ipv4_unicast", True)
        kwargs["ipv6_unicast"] = config.get("ipv6_unicast", False)
        kwargs["activate"] = config.get("activate", True)

        if config.get("route_map_in"):
            kwargs["route_map_in"] = config["route_map_in"]
        if config.get("route_map_out"):
            kwargs["route_map_out"] = config["route_map_out"]
        if config.get("next_hop_self"):
            kwargs["next_hop_self"] = True
        if config.get("send_community"):
            kwargs["send_community"] = True
        if config.get("maximum_routes") is not None:
            kwargs["maximum_routes"] = config["maximum_routes"]
            if config.get("maximum_routes_warning_limit") is not None:
                kwargs["maximum_routes_warning_limit"] = config[
                    "maximum_routes_warning_limit"
                ]
            if config.get("maximum_routes_warning_only"):
                kwargs["maximum_routes_warning_only"] = True
        if config.get("out_delay") is not None:
            kwargs["out_delay"] = config["out_delay"]
        if config.get("timers_keepalive") is not None:
            kwargs["timers_keepalive"] = config["timers_keepalive"]
        if config.get("timers_holdtime") is not None:
            kwargs["timers_holdtime"] = config["timers_holdtime"]
        if config.get("local_as") is not None:
            kwargs["local_as"] = config["local_as"]
            kwargs["local_as_no_prepend"] = config.get("local_as_no_prepend", False)
            kwargs["local_as_replace_as"] = config.get("local_as_replace_as", False)
            kwargs["local_as_fallback"] = config.get("local_as_fallback", False)
        if config.get("graceful_restart_helper"):
            kwargs["graceful_restart_helper"] = True

        return kwargs


class BackupRunningConfigTask(BaseTask):
    """
    Backup the running config of an Arista EOS device.

    This task wraps arista_utils.save_running_config() to backup the running config.
    The actual backup filename is stored in shared data under the key
    "backup_running_config_<hostname>" so that RestoreRunningConfigTask can retrieve it.
    """

    NAME = "backup_running_config"

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        from taac.internal.driver.arista_switch import (
            AristaSwitch,
        )

        hostname = params["hostname"]
        backup_file = params.get("backup_file")

        driver = AristaSwitch(hostname, logger=self.logger)

        self.logger.info(
            f"Backing up running config on {hostname}"
            + (f" to {backup_file}" if backup_file else " (auto-generated name)")
        )
        actual_backup_file = await arista_utils.save_running_config(
            driver, backup_name=backup_file, logger_instance=self.logger
        )

        self.logger.info(
            f"Successfully backed up running config on {hostname} to {actual_backup_file}"
        )


class RestoreRunningConfigTask(BaseTask):
    """
    Restore the running config of an Arista EOS device.

    This task wraps arista_utils.restore_running_config() to restore the running config
    from a backup file

    Backup file name must be of format: flash:<backup file name>
    Example: flash:running_config_2023-10-10_10-10-10
    """

    NAME = "restore_running_config"

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        from taac.internal.driver.arista_switch import (
            AristaSwitch,
        )

        hostname = params["hostname"]
        backup_file = params.get("backup_file")

        if backup_file is None:
            raise ValueError("backup_file must be provided")

        driver = AristaSwitch(hostname, logger=self.logger)

        self.logger.info(f"Restoring running config from {backup_file}")
        await arista_utils.restore_running_config(
            driver, backup_file=backup_file, logger_instance=self.logger
        )
        self.logger.info(f"Successfully restored running config from {backup_file}")
