# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import asyncio
import base64
import copy
import ipaddress
import itertools
import json
import random
import re
import tempfile
import time
import typing as t
from collections import defaultdict
from ipaddress import IPv4Address, IPv4Network, IPv6Address, IPv6Network

from configerator.client import ConfigeratorClient
from libfb.py.asyncio.thrift import get_direct_client
from neteng.fboss.ctrl.types import PortInfoThrift
from neteng.fboss.lib.hostname_utils import get_role_from_hostname
from neteng.netcastle.utils.paramiko_utils import ParamikoClient
from taac.constants import ARISTA_DAEMON_EXEC_SCRIPTS
from taac.driver.driver_constants import (
    DNE_TEST_REGRESSION_NAME,
    FbossSystemctlServiceName,
)
from taac.file_templates import FILE_TEMPLATES
from taac.tasks.base_task import BaseTask
from taac.utils.common import (
    get_default_bgp_configs,
    get_default_configs,
    is_host_drainable,
    run_in_thread,
)
from taac.utils.driver_factory import async_get_device_driver
from taac.utils.health_check_utils import (
    generate_prefix_nh_list_map,
)
from taac.utils.json_thrift_utils import try_json_loads
from taac.utils.oss_taac_lib_utils import (
    async_retryable,
    get_ipv6_for_host,
    none_throws,
)
from taac.utils.system_stress_utils import (
    async_get_memory_current_pct,
)
from nettools.vipinjector.VipService.clients import VipService
from nettools.vipinjector.VipService.types import TVipPreference, TVipRoute, TVipScope
from taac.test_as_a_config import types as taac_types

IPAddress = t.Union[IPv4Address, IPv6Address]
IPNetwork = t.Union[IPv4Network, IPv6Network]


class WaitForAgentConvergenceTask(BaseTask):
    NAME = "wait_for_agent_convergence"

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        hostnames = params["hostnames"]
        timeout = params.get("timeout", 600)
        interval = params.get("interval", 5)
        coroutines = []
        for hostname in hostnames:
            driver = await async_get_device_driver(hostname)
            coroutines.append(
                driver.async_wait_for_agent_configured(
                    timeout=timeout, interval=interval
                )
            )
        await asyncio.gather(*coroutines)


class WaitForBgpConvergenceTask(BaseTask):
    NAME = "wait_for_bgp_convergence"

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        hostnames = params["hostnames"]
        timeout = params.get("timeout", 1200)
        interval = params.get("interval", 10)
        coroutines = []
        for hostname in hostnames:
            driver = await async_get_device_driver(hostname)
            coroutines.append(
                driver.async_wait_for_bgp_convergence(
                    timeout=timeout, interval=interval
                )
            )
        await asyncio.gather(*coroutines)


class ConfigureParallelBgpPeers(BaseTask):
    NAME = "configure_parallel_bgp_peers"
    DEFAULT_CONFIGURE_VLANS_PATCHER_NAME = "configure_vlans"
    DEFAULT_ADD_BGP_PEERS_PATCHER_NAME = "add_bgp_peers"

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        """
        example params:
        {
            "hostname": "rsw001.p001.f01.abc1",
            "config_json": {
                {
                    "eth9/16/1": [
                        {
                            "starting_ip": "10.163.28.1",
                            "increment_ip": "0.0.0.1",
                            "gateway_starting_ip": "10.163.29.1",
                            "gateway_increment_ip": "0.0.0.1",
                            "num_sessions": 100,
                            "description": "foo",
                            "remote_as_4_byte": 65000, # optional. if not provided, will fetch for neighbor switch's local asn
                            "remote_as_4_byte_step": 1, # optional. defaults to 0
                            "peer_group_name": "PEERGROUP_FSW_RSW_V4",
                            "prefix_length": 127,
                        },
                    ]
                }
            },
        }
        """
        hostname = params["hostname"]

        # If peer_configs is provided and non-empty, merge config_json from all peer configs
        if "peer_configs" in params and params["peer_configs"]:
            config_json = {}
            for peer_config in params["peer_configs"]:
                peer_config_json = json.loads(peer_config["config_json"])
                for interface, configs in peer_config_json.items():
                    if interface in config_json:
                        config_json[interface].extend(configs)
                    else:
                        config_json[interface] = configs
            first_peer_config = params["peer_configs"][0]
            configure_vlans_patcher_name = first_peer_config.get(
                "configure_vlans_patcher_name",
                self.__class__.DEFAULT_CONFIGURE_VLANS_PATCHER_NAME,
            )
            add_bgp_peers_patcher_name = first_peer_config.get(
                "add_bgp_peers_patcher_name",
                self.__class__.DEFAULT_ADD_BGP_PEERS_PATCHER_NAME,
            )
        else:
            config_json = json.loads(params["config_json"])
            configure_vlans_patcher_name = params.get(
                "configure_vlans_patcher_name",
                self.__class__.DEFAULT_CONFIGURE_VLANS_PATCHER_NAME,
            )
            add_bgp_peers_patcher_name = params.get(
                "add_bgp_peers_patcher_name",
                self.__class__.DEFAULT_ADD_BGP_PEERS_PATCHER_NAME,
            )
        driver = await async_get_device_driver(hostname)
        configure_vlan_configs = defaultdict(list)
        add_bgp_peer_configs = []
        # pyre-fixme[16]: `AbstractSwitch` has no attribute `async_get_all_port_info`.
        all_port_info = await driver.async_get_all_port_info()
        interface_to_port_info = {
            port_info.name: port_info for port_info in all_port_info.values()
        }
        for interface, configs in config_json.items():
            for config in configs:
                config_only_interface_ip = config.get("config_only_interface_ip", False)
                description = config.get("description", "")
                remote_as_4_byte = config["remote_as_4_byte"]
                remote_as_4_byte_step = config.get("remote_as_4_byte_step", 0)
                peer_group_name = config["peer_group_name"]
                num_sessions = config["num_sessions"]
                starting_ip = config["starting_ip"]
                prefix_length = config["prefix_length"]
                increment_ip = config["increment_ip"]
                gateway_starting_ip = config["gateway_starting_ip"]
                gateway_increment_ip = config["gateway_increment_ip"]
                interface_port_info = interface_to_port_info[interface]
                increment_ip_int = int(ipaddress.ip_address(increment_ip))
                starting_ip_int = int(ipaddress.ip_address(starting_ip))
                gateway_ip_int = int(ipaddress.ip_address(gateway_starting_ip))
                gateway_increment_ip_int = int(
                    ipaddress.ip_address(gateway_increment_ip)
                )

                local_addresses = self.create_ip_addreses(
                    starting_ip_int,
                    increment_ip_int,
                    num_sessions,
                )
                peer_addresses = self.create_ip_addreses(
                    gateway_ip_int,
                    gateway_increment_ip_int,
                    num_sessions,
                )

                if config_only_interface_ip is False:
                    for i, (local_address, peer_address) in enumerate(
                        zip(local_addresses, peer_addresses)
                    ):
                        remote_asn_4_byte = remote_as_4_byte + i * remote_as_4_byte_step
                        add_bgp_peer_configs.append(
                            self.create_add_bgp_peer_config(
                                local_address,
                                peer_address,
                                peer_group_name,
                                remote_asn_4_byte,
                                description,
                            )
                        )
                vlan_ip_addresses = list(
                    set(
                        (
                            # pyre-fixme[16]: `AbstractSwitch` has no attribute
                            #  `async_get_vlan_addresses`.
                            await driver.async_get_vlan_addresses(
                                interface_port_info.vlans[0], global_only=True
                            )
                            + [
                                f"{ip_address}/{prefix_length}"
                                for ip_address in local_addresses
                            ]
                        )
                    )
                )
                configure_vlan_configs[f"vlan{interface_port_info.vlans[0]}"].append(
                    await self.create_configure_vlan_config(
                        vlan_ip_addresses,
                        interface_port_info,
                    )
                )
        await self.register_patchers_to_configure_vlans(
            hostname, configure_vlan_configs, configure_vlans_patcher_name
        )

        await self.register_patchers_to_add_bgp_peers(
            hostname, add_bgp_peer_configs, add_bgp_peers_patcher_name
        )

    async def register_patchers_to_add_bgp_peers(
        self,
        hostname: str,
        add_bgp_peer_configs: t.List[t.Dict[str, t.Any]],
        patcher_name: str,
    ) -> None:
        driver = await async_get_device_driver(hostname)
        async_register_python_patcher_args = {
            "patcher_name": patcher_name,
            "py_func_name": "add_bgp_peers",
            "patcher_args": {"peer_configs": json.dumps(add_bgp_peer_configs)},
            "patcher_desc": "",
        }
        if is_host_drainable(hostname):
            configs = ["bgpcpp", "bgpcpp_softdrain"]
        else:
            configs = ["bgpcpp"]
        await asyncio.gather(
            *[
                # pyre-fixme[16]: `AbstractSwitch` has no attribute
                #  `async_register_python_patcher`.
                driver.async_register_python_patcher(
                    config_name=config, **async_register_python_patcher_args
                )
                for config in configs
            ]
        )

    async def register_patchers_to_configure_vlans(
        self,
        hostname: str,
        configure_vlan_configs: t.Dict[str, t.List[t.Any]],
        patcher_name: str,
    ) -> None:
        driver = await async_get_device_driver(hostname)
        patcher_args = {}
        for vlan_name, configs in configure_vlan_configs.items():
            ip_addresses = set()
            for config in configs:
                ip_addresses.update(config["ip_addresses"])
            ip_addr_to_mask_length = {}
            for ip_addr in ip_addresses:
                ip, mask = ip_addr.split("/")
                if (
                    ip not in ip_addr_to_mask_length
                    or ip_addr_to_mask_length[ip] < mask
                ):
                    ip_addr_to_mask_length[ip] = mask
            deduped_ip_addrs = [
                f"{ip}/{mask}" for ip, mask in ip_addr_to_mask_length.items()
            ]
            config = configs[0]
            config["ip_addresses"] = list(deduped_ip_addrs)
            patcher_args[vlan_name] = json.dumps(config)
        # pyre-fixme[16]: `AbstractSwitch` has no attribute
        #  `async_register_python_patcher`.
        await driver.async_register_python_patcher(
            config_name="agent",
            patcher_name=patcher_name,
            py_func_name="configure_vlans",
            patcher_args=patcher_args,
            patcher_desc="",
        )

    def create_add_bgp_peer_config(
        self,
        local_addr: str,
        peer_addr: str,
        peer_group_name: str,
        remote_as_4_byte: int,
        description: str,
    ) -> t.Dict[str, t.Any]:
        return {
            "local_addr": local_addr,
            "peer_addr": peer_addr,
            "peer_group_name": peer_group_name,
            "remote_as_4_byte": str(remote_as_4_byte),
            "description": description,
        }

    async def create_configure_vlan_config(
        self,
        ip_addresses: t.List[str],
        port_info: PortInfoThrift,
    ) -> t.Dict[str, t.Any]:
        return {
            "vlan_id": port_info.vlans[0],
            "ports": [port_info.portId],
            "ip_addresses": ip_addresses,
            "mtu": 9000,
        }

    def create_ip_addreses(
        self,
        starting_ip_int: int,
        increment_ip_int: int,
        count: int,
    ) -> t.List[str]:
        ip_addresses = []
        for i in range(count):
            new_address = str(
                ipaddress.ip_address(starting_ip_int + increment_ip_int * i)
            )
            ip_addresses.append(new_address)
        return ip_addresses


class CoopUnregisterPatchersTask(BaseTask):
    NAME = "coop_unregister_patchers"

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        hostnames = params.get("hostnames") or [none_throws(params.get("hostname"))]
        regex = params.get("regex", r".*.")
        owner = params.get("owner", DNE_TEST_REGRESSION_NAME)
        config_names = params.get("config_names")
        unregister_patchers_coroutines = []
        for hostname in hostnames:
            configs = config_names or get_default_configs(hostname)
            unregister_patchers_coroutines.append(
                self.unregister_patchers(hostname, configs, regex, owner)
            )
        results = await asyncio.gather(
            *unregister_patchers_coroutines, return_exceptions=True
        )
        errors = [result for result in results if isinstance(result, Exception)]
        if errors:
            raise Exception(
                "Failed to unregister patchers: "
                + ", ".join([str(error) for error in errors])
            )

    @async_retryable(retries=2, sleep_time=10, exceptions=(Exception,))
    async def unregister_patchers(
        self,
        hostname: str,
        config_names: t.List[str],
        regex: str,
        owner: t.Optional[str] = None,
    ) -> None:
        driver = await async_get_device_driver(hostname)
        for config_name in config_names:
            # pyre-fixme[16]: `AbstractSwitch` has no attribute
            #  `async_coop_list_patchers`.
            patchers = await driver.async_coop_list_patchers(config_name)
            patchers_to_unregister = [
                patcher.name
                for patcher in patchers
                if re.search(regex, patcher.name) and patcher.owner == owner
            ]
            if not patchers_to_unregister:
                break
            self.logger.info(
                f"Unregistering patchers {patchers_to_unregister} from {hostname}:{config_name}"
            )
            for patcher in patchers_to_unregister:
                # pyre-fixme[28]: Unexpected keyword argument `auto_remediate_failure`.
                await driver.async_coop_unregister_patchers(
                    # pyrefly: ignore [unexpected-keyword]
                    patcher,
                    config_name,
                    # pyrefly: ignore [unexpected-keyword]
                    auto_remediate_failure=True,
                )
            registered_patchers = [
                patcher.name
                # pyrefly: ignore [missing-attribute]
                for patcher in await driver.async_coop_list_patchers(config_name)
            ]
            if any(
                patcher in registered_patchers for patcher in patchers_to_unregister
            ):
                err_msg = f"Failed to unregister patchers {patchers_to_unregister} from {hostname}:{config_name}"
                self.logger.error(err_msg)
                raise Exception(err_msg)


class CoopRegisterPatcherTask(BaseTask):
    NAME = "coop_register_patcher"

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        hostname = params["hostname"]
        config_names = params.get("config_names") or [params["config_name"]]
        patcher_name = params["patcher_name"]
        py_func_name = params["py_func_name"]
        patcher_args = json.loads(params["patcher_args"])
        patcher_desc = params.get("patcher_desc", "")
        driver = await async_get_device_driver(hostname)
        for config_name in config_names:
            # pyre-fixme[16]: `AbstractSwitch` has no attribute
            #  `async_register_python_patcher`.
            await driver.async_register_python_patcher(
                config_name=config_name,
                patcher_name=patcher_name,
                py_func_name=py_func_name,
                patcher_args=patcher_args,
                patcher_desc=patcher_desc,
            )


class CoopApplyPatchersTask(BaseTask):
    NAME = "coop_apply_patchers"

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        hostnames = params["hostnames"]
        config_names = params.get(
            "config_names",
        )

        do_warmboot = params.get("do_warmboot", False)
        do_coldboot = params.get("do_coldboot", False)

        if do_coldboot:
            create_cold_boot_file_coroutines = []
            agent_restart_coroutines = []
            wait_for_convergence_coroutines = []
            for hostname in hostnames:
                driver = await async_get_device_driver(hostname)
                # pyre-fixme[16]: `AbstractSwitch` has no attribute
                #  `async_create_cold_boot_file`.
                create_cold_boot_file_coroutines.append(
                    driver.async_create_cold_boot_file()
                )
                agent_restart_coroutines.append(
                    driver.async_restart_service(FbossSystemctlServiceName.AGENT)
                )
                wait_for_convergence_coroutines.append(
                    driver.async_wait_for_agent_configured()
                )
            await asyncio.gather(*create_cold_boot_file_coroutines)
            await asyncio.gather(*agent_restart_coroutines)
            await asyncio.gather(*wait_for_convergence_coroutines)
        elif do_warmboot:
            agent_warmboot_coroutines = []
            wait_for_convergence_coroutines = []
            for hostname in hostnames:
                driver = await async_get_device_driver(hostname)
                agent_warmboot_coroutines.append(
                    driver.async_restart_service(FbossSystemctlServiceName.AGENT)
                )
                wait_for_convergence_coroutines.append(
                    driver.async_wait_for_agent_configured()
                )
            await asyncio.gather(*agent_warmboot_coroutines)
            await asyncio.gather(*wait_for_convergence_coroutines)
        else:
            reload_agent_config_coroutines = []
            restart_bgp_coroutines = []
            for hostname in hostnames:
                config_names = config_names or get_default_configs(hostname)
                driver = await async_get_device_driver(hostname)
                if "agent" in config_names:
                    reload_agent_config_coroutines.append(
                        # pyre-fixme[16]: `AbstractSwitch` has no attribute
                        #  `async_agent_config_reload`.
                        driver.async_agent_config_reload()
                    )
                if "bgpcpp" in config_names:
                    restart_bgp_coroutines.append(
                        driver.async_restart_service(FbossSystemctlServiceName.BGP)
                    )
            await asyncio.gather(
                *reload_agent_config_coroutines, return_exceptions=True
            )
            await asyncio.gather(*restart_bgp_coroutines)


class CoopApplyPatchersV2(BaseTask):
    NAME = "coop_apply_patchers_v2"

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        hostnames = params["hostnames"]
        apply_patcher_method = params["apply_patcher_method"]
        apply_patcher_method_enum = taac_types.ApplyPatcherMethod(apply_patcher_method)
        coroutines = []
        for hostname in hostnames:
            driver = await async_get_device_driver(hostname)
            coroutines.append(
                # pyre-fixme[16]: `AbstractSwitch` has no attribute
                #  `async_apply_patchers`.
                driver.async_apply_patchers(
                    apply_patcher_method=apply_patcher_method_enum,
                )
            )
        await asyncio.gather(*coroutines)


class InvokeConcurrentThriftRequestsTask(BaseTask):
    NAME = "invoke_concurrent_thrift_requests"

    async def _get_thrift_client(self, hostname: str, client_name: str):
        """Get a thrift client for the given hostname and client type via driver."""
        driver = await async_get_device_driver(hostname)
        if client_name == "wedge_agent":
            # pyre-fixme[16]: `AbstractSwitch` has no attribute `async_agent_client`.
            return driver.async_agent_client
        elif client_name == "bgpd":
            # pyre-fixme[16]: `AbstractSwitch` has no attribute `async_get_bgp_client`.
            return await driver.async_get_bgp_client()
        else:
            raise ValueError(f"Unknown thrift client: {client_name}")

    async def async_invoke_thrift_api(
        self,
        hostname: str,
        client_name: str,
        api_name: str,
    ) -> None:
        try:
            client_ctx = await self._get_thrift_client(hostname, client_name)
            async with client_ctx as client:
                self.logger.info(f"Calling {client_name}.{api_name} on {hostname}")
                api = getattr(client, api_name)
                await api()
        except Exception as e:
            self.logger.error(
                f"Failed to call {client_name} api {api_name} with exception: {e}"
            )

    async def async_invoke_driver_api(
        self,
        hostname,
        api_name: str,
        **kwargs,
    ) -> None:
        try:
            driver = await async_get_device_driver(hostname, self.logger)
            api = getattr(driver, api_name)
            self.logger.info(f"Calling {api_name} on {hostname}")
            await api(**kwargs)
        except Exception as e:
            self.logger.error(f"Failed to call {api_name} with exception: {e}")

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        hostname = params["hostname"]
        num_concurrent_requests = params.get("num_concurrent_requests", 100)
        num_concurrent_requests_by_api = try_json_loads(
            params.get("num_concurrent_requests_by_api", {})
        )
        thrift_apis = try_json_loads(params.get("thrift_apis", {}))
        thrift_apis_to_args = try_json_loads(params.get("thrift_apis_to_args", {}))
        driver_apis = try_json_loads(params.get("driver_apis", []))
        driver_apis_to_args = try_json_loads(params.get("driver_apis_to_args", {}))
        concurrent_tasks = []

        for client_name, api_names in thrift_apis.items():
            api_names = list(
                set(api_names + thrift_apis_to_args.get(client_name, {}).keys())
            )
            for api_name in api_names:
                for _ in range(
                    num_concurrent_requests_by_api.get(
                        api_name, num_concurrent_requests
                    )
                ):
                    task = asyncio.create_task(
                        self.async_invoke_thrift_api(
                            hostname,
                            client_name,
                            api_name,
                            **thrift_apis_to_args.get(client_name, {}).get(
                                api_name, {}
                            ),
                        )
                    )
                    concurrent_tasks.append(task)
        for api_name in list(set(driver_apis + list(driver_apis_to_args.keys()))):
            for _ in range(
                num_concurrent_requests_by_api.get(api_name, num_concurrent_requests)
            ):
                task = asyncio.create_task(
                    self.async_invoke_driver_api(
                        hostname,
                        api_name,
                        **driver_apis_to_args.get(api_name, {}),
                    )
                )
                concurrent_tasks.append(task)
        random.shuffle(concurrent_tasks)
        chunk_size = params.get("chunk_size", 10)
        concurrent_task_chunks = [
            concurrent_tasks[i : i + chunk_size]
            for i in range(0, len(concurrent_tasks), chunk_size)
        ]
        for chunk in concurrent_task_chunks:
            await asyncio.gather(*chunk, return_exceptions=True)


class AddStressStaticRoutes(BaseTask):
    NAME = "add_stress_static_routes"

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        hostname = params["hostname"]
        dut_driver_class = await async_get_device_driver(hostname)
        static_route_patcher_name = "ecmp_nh_stressor_patcher"

        nh_common_last_hextet = "a000"
        max_ecmp_group = params["max_ecmp_group"]
        max_ecmp_members = params["max_ecmp_members"]
        nh_prefix_1 = params["nh_prefix_1"]
        lb_prefix_agg = params["lb_prefix_agg"]
        device_group_count = params["device_group_count"]
        sleep_time_route_add_s = params.get("sleep_time_route_add_s", 60)

        # Identifying the current offset numbers after removing the patcher stress
        current_ecmp_member = (
            await dut_driver_class.async_verify_ecmp_nexthop_group_member_count()
        )
        self.logger.info(
            f"Intended ECMP member with current + static routes: {max_ecmp_members}"
        )
        self.logger.info(f"Current ECMP member: {current_ecmp_member}")
        current_ecmp_group = len(
            await dut_driver_class.async_get_ecmp_groups_snapshot(
                raise_exception_on_validation_mismatch=False
            )
        )
        self.logger.info(f"Current ECMP group: {current_ecmp_group}")
        static_based_ecmp_group = max(max_ecmp_group - current_ecmp_group, 0)
        self.logger.info(
            f"Applying static route to additionally add {static_based_ecmp_group=} groups"
        )
        static_based_ecmp_member = max(max_ecmp_members - current_ecmp_member, 0)
        self.logger.info(
            f"Applying static route to additionally add {static_based_ecmp_member=} members"
        )
        if static_based_ecmp_group == 0 or static_based_ecmp_member == 0:
            self.logger.info(
                "No additional ECMP groups or members needed. Skipping static route addition"
            )
            return
        # Createst the list of Nexthops from infra ip address and list of loadbearing prefixes
        network_1 = ipaddress.IPv6Network(nh_prefix_1, strict=False)
        base_increment = int(nh_common_last_hextet, 16)
        nh_list = [
            str(network_1.network_address + base_increment + i)
            for i in range(device_group_count)
        ]
        lb_network = ipaddress.IPv6Network(lb_prefix_agg, strict=False)
        lb_prefix_len = 128
        lb_subnets_iterator = lb_network.subnets(new_prefix=lb_prefix_len)
        lb_subnets = list(
            itertools.islice(lb_subnets_iterator, static_based_ecmp_group)
        )
        lb_prefix_list = [
            f"{subnet.network_address}/{lb_prefix_len}" for subnet in lb_subnets
        ]
        ecmp_combinations_list = generate_prefix_nh_list_map(
            nh_list, static_based_ecmp_member, static_based_ecmp_group
        )

        prefix_to_nexthops = {
            prefix: list(combination)
            for prefix, combination in zip(lb_prefix_list, ecmp_combinations_list)
        }
        self.logger.info(
            f"Number of unique ecmp combinations: {len(ecmp_combinations_list)}"
        )
        expected_ecmp_member_count = sum(
            len(nh_set) for nh_set in ecmp_combinations_list
        )
        self.logger.info(f"Total ECMP members: {expected_ecmp_member_count}")
        static_route_patcher_name = "ecmp_nh_stressor_patcher"
        await dut_driver_class.async_add_static_route_patcher(
            prefix_to_nexthops,
            static_route_patcher_name,
            is_patcher_name_uuid_needed=False,
        )
        self.logger.info(
            f"Sleeping {sleep_time_route_add_s}s after addition of new static route patcher"
        )
        await asyncio.sleep(sleep_time_route_add_s)
        self.logger.info(
            f"Current member count: {await dut_driver_class.async_verify_ecmp_nexthop_group_member_count()} "
            f"Current Group  count: {len(await dut_driver_class.async_get_ecmp_groups_snapshot(raise_exception_on_validation_mismatch=False))}"
        )


class CreateVipInjectors(BaseTask):
    NAME = "create_vip_injectors"

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        hostname = params["hostname"]
        vip_server_ip_str = get_ipv6_for_host(hostname)
        vip_server_ip = ipaddress.IPv6Address(vip_server_ip_str)

        vip_injector_count = int(params.get("vip_injector_count", 1))
        num_vips_per_injector = int(params.get("num_vips_per_injector", 1))

        starting_vip_ip = params["starting_vip_ip"]
        starting_vip_ip_int = int(ipaddress.ip_address(starting_vip_ip))

        vip_increment_ip = params["vip_increment_ip"]
        vip_increment_ip_int = int(ipaddress.ip_address(vip_increment_ip))

        vip_prefix_len = int(params.get("vip_prefix_len", 64))

        starting_nexthop = params["starting_nexthop"]
        starting_nexthop_int = int(ipaddress.ip_address(starting_nexthop))

        nexthop_increment_ip = params["nexthop_increment_ip"]
        nexthop_increment_int = int(ipaddress.ip_address(nexthop_increment_ip))

        starting_next_hop_address = self.create_ip_addreses(
            starting_nexthop_int, nexthop_increment_int, vip_injector_count
        )

        scope = int(params.get("vip_scope", TVipScope.PRIVATE_REGIONAL))
        scope = TVipScope(scope)

        preference = int(params.get("vip_preference", TVipPreference.PRIMARY))
        preference = TVipPreference(preference)

        # Create VIP injectors
        for i in range(vip_injector_count):
            injector_id = f"vip_injector_{i}"
            vips = self.generate_vips(
                starting_vip_ip_int,
                vip_increment_ip_int,
                vip_prefix_len,
                num_vips_per_injector,
                starting_next_hop_address[i],
                scope,
                preference,
            )
            await self.inject_vips(
                vipserver_ip=vip_server_ip,
                injector_id=injector_id,
                duration=10000000,
                vips=vips,
            )
            starting_vip_ip_int += vip_increment_ip_int * num_vips_per_injector

            injector_ids = await self.get_all_injector_ids(vip_server_ip)
            if injector_id in injector_ids:
                self.logger.info(f"Injector ID {injector_id} is created properly")
            else:
                self.logger.error(f"Injector ID {injector_id} is not created properly")

    def create_ip_addreses(
        self,
        starting_ip_int: int,
        increment_ip_int: int,
        count: int,
    ) -> t.List[str]:
        ip_addresses = []
        for i in range(count):
            new_address = str(
                ipaddress.ip_address(starting_ip_int + increment_ip_int * i)
            )
            ip_addresses.append(new_address)
        return ip_addresses

    def generate_vips(
        self,
        starting_vip_ip_int: int,
        vip_increment_ip_int: int,
        vip_prefix_len: int,
        num_ips: int,
        next_hop: str,
        scope: TVipScope,
        preference: TVipPreference,
    ) -> t.List[TVipRoute]:
        vips = []

        for _ in range(num_ips):
            new_address = str(ipaddress.ip_address(starting_vip_ip_int))
            vips.append(
                TVipRoute(
                    prefix=f"{str(new_address)}/{vip_prefix_len}",
                    scope=scope,
                    preference=preference,
                    next_hop=next_hop,
                )
            )
            starting_vip_ip_int += vip_increment_ip_int
        return vips

    async def inject_vips(
        self,
        vipserver_ip: IPAddress,
        injector_id: str,
        duration: float,
        vips: t.List[TVipRoute],
        port: int = 3333,
    ) -> int:
        async with get_direct_client(
            VipService, host=str(vipserver_ip), port=port
        ) as vsclient:
            await vsclient.syncVips(injector_id, vips, int(duration * 1000))
            self.logger.info(
                f"Injected {len(vips)}  {vips} to {vipserver_ip}. TTL is {duration}s"
            )

        return 0

    async def get_all_injector_ids(
        self,
        vipserver_ip: IPAddress,
        port: int = 3333,
    ) -> t.Sequence[str]:
        async with get_direct_client(
            VipService, host=str(vipserver_ip), port=port
        ) as vsclient:
            injector_ids = await vsclient.getAllInjectorIDs()
            self.logger.info(
                f"Got {len(injector_ids)} injector IDs from {vipserver_ip}"
            )
            return injector_ids


class ScpFile(BaseTask):
    """
    Task to copy a file to a remote device via SCP.

    Supports multiple sources for file content:
    - configerator_path: Path to a file in configerator
    - file_template: Name of a predefined template from FILE_TEMPLATES
    - file_content: Direct string content to write
    """

    NAME = "scp_file"

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        self.logger.info(f"Running {self.NAME} task with params: {params}")
        hostname = params["hostname"]
        remote_path = params["remote_path"]
        file_template = params.get("file_template")
        template_params = params.get("template_params", {})
        file_content = params.get("file_content", "")
        configerator_path = params.get("configerator_path")

        if configerator_path:
            self.logger.info(f"Reading file from configerator: {configerator_path}")
            with ConfigeratorClient() as client:
                file_content = client.get_config_contents(configerator_path)
                self.logger.info(
                    f"Successfully read {len(file_content)} bytes from configerator"
                )
        elif file_template:
            file_template, default_params = FILE_TEMPLATES[file_template]
            default_params = copy.copy(default_params)
            default_params.update(template_params)
            file_content = file_template.format(**default_params)
        else:
            assert file_content, (
                "One of 'configerator_path', 'file_template', or 'file_content' must be provided"
            )

        with tempfile.NamedTemporaryFile(
            dir=tempfile.gettempdir(), mode="w", delete=False, newline="\n"
        ) as tmp_file:
            tmp_file.write(file_content)
            local_file_path = tmp_file.name
        with ParamikoClient(hostname) as client:
            client.scp(
                local_path=local_file_path,
                remote_path=remote_path,
            )
        self.logger.info(f"Successfully copied file to {hostname}:{remote_path}")


class RunCommandsOnShell(BaseTask):
    NAME = "run_commands_on_shell"

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        hostname = params["hostname"]
        cmds = params.get("cmds", [])
        driver = await async_get_device_driver(hostname)
        for cmd in cmds:
            self.logger.info(f"{hostname} -- Running command: {cmd}")
            await driver.async_run_cmd_on_shell(cmd)


class AllocateCgroupSliceMemory(BaseTask):
    NAME = "allocate_cgroup_slice_memory"

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        hostname = params["hostname"]
        executable_path = params.get("executable_path", "/opt/memory_pressure")
        slice_name = params["slice_name"]
        keep_alive = params.get("keep_alive", True)
        initial_memory_allocation = params.get("initial_memory_allocation")
        duration = params.get("duration", 300)
        ods_query_duration = params.get("ods_query_duration", 300)
        driver = await async_get_device_driver(hostname)
        percentile = params.get("percentile")

        # Check for new workload slice based parameter
        workload_slice_based_total_memory_decimal = params.get(
            "workload_slice_based_total_memory_decimal"
        )
        total_memory_pct_decimal = params.get("total_memory_pct_decimal")

        # pyre-fixme[16]: `AbstractSwitch` has no attribute
        #  `async_check_if_file_exists`.
        if not await driver.async_check_if_file_exists(executable_path):
            raise Exception(
                f"Memory pressure script does not exist at {executable_path} on {hostname}"
            )
        end_time = int(time.time())
        start_time = end_time - ods_query_duration
        p90_memory_current = await async_get_memory_current_pct(
            hostname, slice_name, start_time, end_time, percentile
        )  # In B
        # pyre-fixme[16]: `AbstractSwitch` has no attribute `async_get_memory_total`.
        memory_total = await driver.async_get_memory_total()  # In B

        # Calculate target memory based on available parameters
        if workload_slice_based_total_memory_decimal is not None:
            workload_slice_based_total_memory_decimal = float(
                workload_slice_based_total_memory_decimal
            )
            workload_max_mem = (
                await driver.async_get_workload_slice_max_allocated_memory()
            )
            target_memory = (
                workload_max_mem / 0.75
            ) * workload_slice_based_total_memory_decimal  # In B
            self.logger.info(
                f"Using workload slice based calculation: workload_max_mem={workload_max_mem / (1024**3):.2f}GB, workload_slice_based_total_memory_decimal={workload_slice_based_total_memory_decimal}, target_memory={target_memory / (1024**3):.2f}GB"
            )
        elif total_memory_pct_decimal is not None:
            total_memory_pct = float(total_memory_pct_decimal)  # In B
            target_memory = total_memory_pct * memory_total  # In B
            self.logger.info(
                f"Using total memory percentage calculation: total_memory_pct={total_memory_pct}, memory_total={memory_total}, target_memory={target_memory / (1024**3):.2f}GB"
            )
        else:
            raise ValueError(
                "Either 'workload_slice_based_total_memory_decimal' or 'total_memory_pct_decimal' must be provided"
            )

        memory_to_allocate = int((target_memory - p90_memory_current) / 1024**2)
        self.logger.info(
            f"Final calculation: target_memory={target_memory / (1024**3):.2f}GB, p90_memory_current={p90_memory_current / (1024**3):.2f}GB, memory_to_allocate={memory_to_allocate / (1024):.2f}GB"
        )
        if memory_to_allocate <= 0:
            self.logger.info("No memory allocation needed")
            return
        allocate_memory_cmds = [
            f"{executable_path}",
            "-c",
            f"{slice_name}.slice",
            "-m",
            memory_to_allocate,
            "-t",
            duration,
        ]
        if keep_alive:
            allocate_memory_cmds.append("-k")
        if initial_memory_allocation:
            allocate_memory_cmds.append("-i")
            allocate_memory_cmds.append(initial_memory_allocation)
        allocate_memory_cmds = [str(cmd) for cmd in allocate_memory_cmds]
        run_in_thread(driver.async_run_cmd_on_shell, cmd=" ".join(allocate_memory_cmds))


class InjectBgpPolicyStatements(BaseTask):
    """
    Task for installing BGP policy statements from configerator or filesystem to FBOSS devices.

    This task fetches BGP policy statements from configerator or directly from a file
    and applies them to the specified device using the add_bgp_policy_statement patcher.
    """

    NAME = "inject_bgp_policy_statements"

    async def fetch_policy_from_configerator(
        self,
        config_path: str,
        # pyrefly: ignore [bad-return]
    ) -> t.Dict[str, t.Any]:
        """
        Fetch BGP policy from configerator.
        """
        try:
            self.logger.info(f"Fetching BGP policy from {config_path}")
            with ConfigeratorClient() as client:
                policy_json = client.get_config_contents_as_JSON(config_path)
                return policy_json
        except Exception as e:
            raise Exception(f"Failed to fetch BGP policy: {str(e)}")

    async def fetch_policy_from_file(self, file_path: str) -> t.Dict[str, t.Any]:
        """
        Read BGP policy directly from a file.

        Args:
            file_path: Path to the JSON file containing BGP policy

        Returns:
            Dict containing the BGP policy

        Raises:
            Exception: If there's an error reading the file
        """
        try:
            self.logger.info(f"Reading BGP policy from file: {file_path}")
            with open(file_path, "r") as f:
                return json.load(f)
        except Exception as e:
            raise Exception(f"Failed to read BGP policy from file: {str(e)}")

    async def apply_policy_statements(
        self, hostname: str, statements: t.List[t.Dict[str, t.Any]], config_name: str
    ) -> None:
        """
        Apply BGP policy statements to a device.

        Args:
            hostname: Device hostname
            statements: List of BGP policy statements
            config_name: Config name (e.g., "bgpcpp")

        Raises:
            Exception: If there's an error applying the statements
        """
        try:
            driver = await async_get_device_driver(hostname)

            for statement in statements:
                # Create a patcher for add_bgp_policy_statement
                patcher_name = f"bgp_policy_patcher_{statement['name']}"

                self.logger.info(f"Creating patcher '{patcher_name}' for BGP policy")
                self.logger.info(f"{statement.get('policy_entries', [])}")

                # Register the patcher with the device
                try:
                    # pyre-fixme[16]: `AbstractSwitch` has no attribute
                    #  `async_register_python_patcher`.
                    await driver.async_register_python_patcher(
                        config_name=config_name,
                        patcher_name=patcher_name,
                        py_func_name="add_bgp_policy_statement",
                        patcher_args={
                            "name": statement["name"],
                            "description": statement["description"],
                            "policy_entries": json.dumps(
                                statement.get("policy_entries", [])
                            ),
                        },
                        patcher_desc="BGP policy statements applied by InjectBgpPolicyStatements",
                    )
                    self.logger.info(
                        f"Successfully registered patcher '{patcher_name}'"
                    )
                except Exception as e:
                    raise Exception(f"Failed to register patcher: {str(e)}")
        except Exception as e:
            raise Exception(
                f"Error applying BGP policy statements to {hostname}: {str(e)}"
            )

        # Apply the patcher to update the BGP policy
        try:
            # pyre-fixme[16]: `AbstractSwitch` has no attribute
            #  `async_agent_config_reload`.
            await driver.async_agent_config_reload()
            self.logger.info(
                f"Successfully applied BGP policy statements to {hostname}"
            )
        except Exception as e:
            self.logger.error(f"Failed to apply patcher: {str(e)}")
            raise Exception(f"Failed to apply patcher: {str(e)}")

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        """
        Run the BGP policy installer task.

        Args:
            params: Dictionary containing:
                - hostname: Device hostname
                - config_path: Path to the BGP policy in configerator (optional if file_path is provided)
                - file_path: Path to the BGP policy file on the filesystem (optional if config_path is provided)
                - config_name: Config name (default: "bgpcpp")
                - filter_policy_names: List of policy names to filter (optional)

        Raises:
            Exception: If there's an error during execution
        """
        hostname = params.get("hostname")
        config_path = params.get("config_path")
        file_path = params.get("file_path")
        config_name = params.get("config_name", "bgpcpp")
        if not hostname:
            raise ValueError("Hostname is required")
        # Determine how to fetch the policy
        if file_path:
            # Use direct file access
            policy = await self.fetch_policy_from_file(file_path)
        elif config_path:
            # Use configerator
            policy = await self.fetch_policy_from_configerator(config_path)
        else:
            raise ValueError("Either config_path or file_path is required")
        statements = policy.get("bgp_policy_statements", [])
        # Apply policy statements to the device
        await self.apply_policy_statements(hostname, statements, config_name)


class IsolatePorts(BaseTask):
    NAME = "isolate_selected_ports"

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        device_to_disabled_ports = params["device_to_disabled_ports"]
        for device, disabled_interfaces in device_to_disabled_ports.items():
            self.logger.info(f"Disabling ports on {device}")
            # Create an instance of the FbossSwitch class
            dut_driver_class = await async_get_device_driver(device)

            await dut_driver_class.async_register_patcher_to_shut_ports_persistently(
                patcher_name="port_shut_patcher", interfaces=disabled_interfaces
            )


class AristaDaemonControlTask(BaseTask):
    """
    Generic task for controlling daemons on Arista switches.

    This task provides functionality to:
    - Enable any daemon (create "daemon <name>" with exec script and no shutdown)
    - Disable any daemon (shutdown existing "daemon <name>")
    - Check current daemon status

    Supports daemons like: Bgp, FibAgent, FibAgentBgp, etc.
    """

    NAME = "arista_daemon_control"

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        """
        Run the daemon control task.

        Args:
            params: Dictionary containing:
                - hostname: Device hostname (required)
                - action: "enable" or "disable" (required)
                - daemon_name: Name of the daemon (required) - e.g., "Bgp", "FibAgent", "FibAgentBgp"
                - exec_script: Path to execution script (optional, uses default if not provided)
        """
        hostname = params["hostname"]
        action = params["action"].lower()
        daemon_name = params["daemon_name"]
        exec_script = params.get("exec_script") or ARISTA_DAEMON_EXEC_SCRIPTS.get(
            daemon_name
        )

        if action not in ["enable", "disable"]:
            raise ValueError("Action must be either 'enable' or 'disable'")

        self.logger.info(
            f"Daemon '{daemon_name}' control action '{action}' on {hostname}"
        )

        driver = await async_get_device_driver(hostname)

        if action == "enable":
            await self._enable_daemon(driver, daemon_name, exec_script)
        elif action == "disable":
            await self._disable_daemon(driver, daemon_name)

        self.logger.info(
            f"Successfully completed daemon '{daemon_name}' {action} on {hostname}"
        )

    async def _check_daemon_exists(self, driver, daemon_name: str) -> bool:
        """
        Check if 'daemon <name>' configuration exists.

        Args:
            driver: Device driver instance
            daemon_name: Name of the daemon to check

        Returns:
            bool: True if daemon exists, False otherwise
        """
        try:
            cmd = "show running-config section daemon"
            output = await driver.async_execute_show_or_configure_cmd_on_shell(cmd)

            # Use word boundary to match exact daemon name, not substring
            pattern = rf"^daemon\s+{re.escape(daemon_name)}\s*$"
            return bool(re.search(pattern, output, re.MULTILINE))
        except Exception as e:
            self.logger.warning(f"Failed to check daemon {daemon_name} status: {e}")
            return False

    async def _check_daemon_running_status(
        self, driver, daemon_name: str
    ) -> t.Dict[str, t.Any]:
        """
        Check if daemon is actually running (not just configured).

        Args:
            driver: Device driver instance
            daemon_name: Name of the daemon to check

        Returns:
            Dict containing:
                - daemon_exists: bool - whether daemon config exists
                - is_running: bool - whether daemon process is active
                - process_info: str - daemon process information
        """
        try:
            # Check if daemon config exists
            config_cmd = "show running-config section daemon"
            config_output = await driver.async_execute_show_or_configure_cmd_on_shell(
                config_cmd
            )

            # Use word boundary to match exact daemon name, not substring
            pattern = rf"^daemon\s+{re.escape(daemon_name)}\s*$"
            daemon_exists = bool(re.search(pattern, config_output, re.MULTILINE))

            # Check if daemon process is running
            process_cmd = f"show daemon {daemon_name}"
            try:
                process_output = (
                    await driver.async_execute_show_or_configure_cmd_on_shell(
                        process_cmd
                    )
                )
                # If we can get daemon info, it's likely running
                # Check for indicators that daemon is active
                is_running = (
                    "Running" in process_output
                    or "Active" in process_output
                    or "PID" in process_output
                )
                process_info = process_output.strip()
            except Exception:
                # If show daemon command fails, daemon is likely not running
                is_running = False
                process_info = "Process not found or not accessible"

            return {
                "daemon_exists": daemon_exists,
                "is_running": is_running,
                "process_info": process_info,
            }
        except Exception as e:
            self.logger.warning(
                f"Failed to check daemon {daemon_name} running status: {e}"
            )
            return {
                "daemon_exists": False,
                "is_running": False,
                "process_info": f"Error: {str(e)}",
            }

    async def _enable_daemon(
        self, driver, daemon_name: str, exec_script: t.Optional[str] = None
    ) -> None:
        """
        Enable daemon.

        If daemon doesn't exist, creates it with exec script.
        Then ensures it's not shutdown.

        Args:
            driver: Device driver instance
            daemon_name: Name of the daemon
            exec_script: Path to execution script (optional)
        """
        daemon_exists = await self._check_daemon_exists(driver, daemon_name)

        if not daemon_exists:
            self.logger.info(f"daemon {daemon_name} does not exist, creating it")
        else:
            self.logger.info(
                f"daemon {daemon_name} exists, ensuring it's properly configured"
            )

        # Always configure both exec script and no shutdown, regardless of whether daemon exists
        # This handles cases where daemon exists but lacks exec script or is shutdown
        if exec_script:
            cmd = f"daemon {daemon_name}\nexec {exec_script}\nno shutdown"
        else:
            cmd = f"daemon {daemon_name}\nno shutdown"
            self.logger.warning(f"No exec script provided for daemon {daemon_name}")

        await driver.async_execute_show_or_configure_cmd_on_shell(cmd, configure=True)

        # Verify daemon was enabled successfully
        await asyncio.sleep(2)  # Brief pause to allow daemon to start
        post_enable_status = await self._check_daemon_running_status(
            driver, daemon_name
        )
        self.logger.info(
            f"Post-enable status for daemon {daemon_name}: "
            f"exists={post_enable_status.get('daemon_exists', False)}, "
            f"running={post_enable_status.get('is_running', False)}"
        )

        if not post_enable_status.get("daemon_exists", False):
            self.logger.error(
                f"daemon {daemon_name} configuration was not created properly"
            )
            raise Exception(f"daemon {daemon_name} was not enabled successfully")

        self.logger.info(f"Daemon {daemon_name} enabled successfully")

    async def _disable_daemon(self, driver, daemon_name: str) -> None:
        """
        Disable daemon by shutting it down.

        If shutdown doesn't work effectively, falls back to removing
        the daemon configuration entirely with "no daemon <name>".

        Args:
            driver: Device driver instance
            daemon_name: Name of the daemon
        """
        daemon_exists = await self._check_daemon_exists(driver, daemon_name)

        if not daemon_exists:
            self.logger.info(f"daemon {daemon_name} does not exist, nothing to disable")
            return

        # First attempt: Standard shutdown
        self.logger.info(f"Shutting down daemon {daemon_name}")
        cmd = f"daemon {daemon_name}\nshutdown"
        await driver.async_execute_show_or_configure_cmd_on_shell(cmd, configure=True)

        # Verify daemon status after shutdown
        await asyncio.sleep(4)  # Brief pause to allow config to take effect
        post_shutdown_status = await self._check_daemon_running_status(
            driver, daemon_name
        )

        if post_shutdown_status.get("is_running", False):
            self.logger.warning(
                f"daemon {daemon_name} is still running after shutdown command. "
                f"Attempting to remove daemon configuration entirely."
            )

            # Fallback: Remove daemon configuration entirely
            self.logger.info(f"Removing daemon {daemon_name} configuration completely")
            cmd = f"no daemon {daemon_name}"
            await driver.async_execute_show_or_configure_cmd_on_shell(
                cmd, configure=True
            )

            # Final verification
            await asyncio.sleep(5)
            final_status = await self._check_daemon_running_status(driver, daemon_name)

            if final_status.get("daemon_exists", True):
                self.logger.error(f"Failed to disable daemon {daemon_name} completely")
                raise Exception(
                    f"daemon {daemon_name} could not be disabled effectively"
                )
            else:
                self.logger.info(
                    f"daemon {daemon_name} configuration removed successfully"
                )
        else:
            self.logger.info(f"daemon {daemon_name} shutdown successfully")


class AddBgpPolicyMatchPrefixToPropagateRoutes(BaseTask):
    NAME = "add_bgp_policy_match_prefix_to_propagate_routes"

    PATCHER_PY_FUNC_NAME = "add_bgp_policy_match_prefix_to_propagate_routes"

    def find_indices(self, lst: list, value: t.Any) -> t.List[int]:
        return [i for i, x in enumerate(lst) if x == value]

    def sanitize_role_name(self, role_name: str) -> str:
        return role_name.replace("_", "").upper()

    def get_stmt_pairs(
        self, traverse_path: t.List[str], role_name: str, is_drain_config: bool
    ) -> t.Dict[t.Tuple[str, str], t.Tuple[str, str]]:
        indices = self.find_indices(traverse_path, role_name)
        stmt_pairs = {}
        for idx in indices:
            prev_role = traverse_path[idx - 1] if idx > 0 else None
            next_role = traverse_path[idx + 1] if idx < len(traverse_path) - 1 else None
            if prev_role:
                in_stmt = f"PROPAGATE_{self.sanitize_role_name(role_name)}_{self.sanitize_role_name(prev_role)}_IN"
                out_stmt = f"PROPAGATE_{self.sanitize_role_name(role_name)}_{self.sanitize_role_name(prev_role)}_OUT{'_DRAIN' if is_drain_config else ''}"
                stmt_pairs[(prev_role, role_name)] = (in_stmt, out_stmt)
            if next_role:
                in_stmt = f"PROPAGATE_{self.sanitize_role_name(role_name)}_{self.sanitize_role_name(next_role)}_IN"
                out_stmt = f"PROPAGATE_{self.sanitize_role_name(role_name)}_{self.sanitize_role_name(next_role)}_OUT{'_DRAIN' if is_drain_config else ''}"
                stmt_pairs[(next_role, role_name)] = (in_stmt, out_stmt)
        self.logger.debug(f"stmt_pairs: {stmt_pairs}")
        return stmt_pairs

    async def add_prefix_to_bgp_policy_match(
        self,
        hostname: str,
        prefixes: t.List[str],
        in_stmt: str,
        out_stmt: str,
        config_name: str,
    ) -> None:
        driver = await async_get_device_driver(hostname)
        tasks = []
        for prefix in prefixes:
            patcher_name = f"bgp_policy_match_prefix_to_propagate_routes_{prefix}_in_{in_stmt}_out_{out_stmt}"
            patcher_args = {
                "in_stmt_name": in_stmt,
                "out_stmt_name": out_stmt,
                "matching_prefix": prefix,
            }
            tasks.append(
                # pyre-fixme[16]: `AbstractSwitch` has no attribute
                #  `async_register_python_patcher`.
                driver.async_register_python_patcher(
                    config_name,
                    patcher_name,
                    self.PATCHER_PY_FUNC_NAME,
                    patcher_args,
                    "",
                )
            )
        await asyncio.gather(*tasks)

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        hostnames = params["hostnames"]
        prefixes = params["prefixes"]
        path = params["path"]  # eg: ["BC", "FX", "BC"]
        for hostname in hostnames:
            role_name = get_role_from_hostname(hostname).name
            for config in get_default_bgp_configs(hostname):
                is_drain_config = "drain" in config
                stmt_pairs = self.get_stmt_pairs(path, role_name, is_drain_config)
                for in_stmt, out_stmt in stmt_pairs.values():
                    self.logger.debug(
                        f"Propagating {prefixes} via {in_stmt} and {out_stmt}"
                    )
                    await self.add_prefix_to_bgp_policy_match(
                        hostname, prefixes, in_stmt, out_stmt, config
                    )


class AristaCreateFileFromConfig(BaseTask):
    """
    Task to create a file on an Arista device from a configerator path.
    This mimics the coop pattern of using base64 encoding to copy file content
    via echo commands rather than SCP, avoiding the need for a coop patcher and
    create_file patcher.
    """

    NAME = "arista_create_file_from_config"
    MAX_RETRIES = 3
    # Each base64 chunk is pushed as a single `echo '<chunk>'` argument inside a
    # `bash sudo sh -c "echo '<chunk>' > <path>.b64"` command. The hard ceiling
    # is NOT the Linux per-argument cap (MAX_ARG_STRLEN = 131072) — it is the
    # Arista EOS shell parser's command-token limit, which is much smaller and
    # rejects oversized tokens at parse time with `% Invalid input (command
    # token is too long)`. The size-verify + retry below does NOT save us from
    # parse-time rejection because the shell never executes the echo and no
    # bytes ever land on the device.
    #
    # Empirical headroom: 30000-byte chunks deploy reliably on the EBB Arista
    # devices used by the dne_routing conveyor (bag010 / bag011 / bag012, all
    # `nettools.ebb.eos.orinoco_dne_routing_test` images). 120000 was tried in
    # D107698353 to cut wall-clock; every image-deploy node hit the EOS token
    # limit on the very first chunk (R110.x, 2026-06-06). Keep this value at or
    # below 30000 unless and until the transport is switched off in-shell echo
    # (e.g. scp/sftp — see internal/tasks/bgp_weight_policy_task.py for the
    # scp pattern).
    DEFAULT_CHUNK_SIZE = 30000

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        """
        Run the Arista create file task.

        Args:
            params: Dictionary containing:
                - hostname: Device hostname (required)
                - configerator_path: Path to a file in configerator (required)
                - file_path: Path to the file on the device (required)
                - chunk_size: Size of each chunk (default: DEFAULT_CHUNK_SIZE)
        """
        hostname = params["hostname"]
        configerator_path = params["configerator_path"]
        file_path = params["file_path"]
        chunk_size = params.get("chunk_size", self.DEFAULT_CHUNK_SIZE)

        file_content = ""
        self.logger.info(f"Reading file from configerator path: {configerator_path}")
        with ConfigeratorClient() as client:
            file_content = client.get_config_contents(configerator_path)
            self.logger.info(
                f"Successfully read {len(file_content)} bytes from configerator"
            )

        expected_size = len(file_content.encode("utf-8"))
        encoded = base64.b64encode(file_content.encode("utf-8")).decode("utf-8")
        chunks = [
            encoded[i : i + chunk_size] for i in range(0, len(encoded), chunk_size)
        ]
        self.logger.info(f"Split file into {len(chunks)} chunks")

        driver = await async_get_device_driver(hostname)

        try:
            for attempt in range(1, self.MAX_RETRIES + 1):
                cmds = []
                for i, chunk in enumerate(chunks):
                    if i == 0:
                        cmds.append(
                            f"bash sudo sh -c \"echo '{chunk}' > {file_path}.b64\""
                        )
                    else:
                        cmds.append(
                            f"bash sudo sh -c \"echo '{chunk}' >> {file_path}.b64\""
                        )
                cmds.append(
                    f'bash sudo sh -c "base64 -d {file_path}.b64 > {file_path}"'
                )

                for cmd in cmds:
                    # pyre-fixme[16]: `AbstractSwitch` has no attribute
                    #  `async_execute_show_or_configure_cmd_on_shell`.
                    await driver.async_execute_show_or_configure_cmd_on_shell(cmd)

                # Verify written file size matches expected
                # pyre-fixme[16]: `AbstractSwitch` has no attribute
                #  `async_execute_show_or_configure_cmd_on_shell`.
                size_output = await driver.async_execute_show_or_configure_cmd_on_shell(
                    f"bash wc -c < {file_path}"
                )
                try:
                    actual_size = int(size_output.strip())
                except (ValueError, AttributeError):
                    self.logger.warning(
                        f"Attempt {attempt}/{self.MAX_RETRIES}: "
                        f"Could not parse file size from wc output: {size_output!r}"
                    )
                    if attempt < self.MAX_RETRIES:
                        continue
                    raise Exception(
                        f"Failed to verify file size on {hostname}:{file_path} "
                        f"after {self.MAX_RETRIES} attempts. "
                        f"Last wc output: {size_output!r}"
                    )

                if actual_size == expected_size:
                    self.logger.info(
                        f"File size verified: {actual_size} bytes on "
                        f"{hostname}:{file_path} (attempt {attempt})"
                    )
                    break
                else:
                    self.logger.warning(
                        f"Attempt {attempt}/{self.MAX_RETRIES}: "
                        f"File size mismatch on {hostname}:{file_path}: "
                        f"expected {expected_size} bytes, got {actual_size} bytes. "
                        f"Base64-chunked transfer likely dropped chunks."
                    )
                    if attempt >= self.MAX_RETRIES:
                        raise Exception(
                            f"File size mismatch on {hostname}:{file_path} after "
                            f"{self.MAX_RETRIES} attempts: expected {expected_size} "
                            f"bytes, got {actual_size} bytes. "
                            f"The base64-chunked transfer is unreliable on this device."
                        )
        finally:
            # Always clean up staging file, even if upload/verify failed.
            try:
                # pyre-fixme[16]: `AbstractSwitch` has no attribute
                #  `async_execute_show_or_configure_cmd_on_shell`.
                await driver.async_execute_show_or_configure_cmd_on_shell(
                    f"bash sudo rm -f {file_path}.b64"
                )
            except Exception as cleanup_exc:
                self.logger.warning(
                    f"Failed to remove staging file {file_path}.b64 on "
                    f"{hostname}: {cleanup_exc}"
                )


class ValidateBgpcppConfigOnDevice(BaseTask):
    """
    Validate BGP++ config on an Arista device using the production
    bgp_config_validator binary installed via the fb-bgpcpp RPM.
    """

    NAME = "validate_bgpcpp_config_on_device"
    VALIDATOR_PATH = "/usr/sbin/bgp_config_validator"

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        """
        Run bgp_config_validator on the device to validate config integrity.

        Args:
            params: Dictionary containing:
                - hostname: Device hostname (required)
                - config_path: Path to bgpcpp_config on device (required)
                - policy_path: Path to bgpcpp_policy on device (optional)
        """
        hostname = params["hostname"]
        config_path = params["config_path"]
        policy_path = params.get("policy_path")

        driver = await async_get_device_driver(hostname)

        # Check if validator binary exists on device
        # pyre-fixme[16]: `AbstractSwitch` has no attribute
        #  `async_execute_show_or_configure_cmd_on_shell`.
        check_output = await driver.async_execute_show_or_configure_cmd_on_shell(
            f"bash test -x {self.VALIDATOR_PATH} && echo EXISTS || echo MISSING"
        )
        if "MISSING" in (check_output or ""):
            self.logger.warning(
                f"bgp_config_validator not found at {self.VALIDATOR_PATH} "
                f"on {hostname}. Skipping validation."
            )
            return

        cmd = f"bash {self.VALIDATOR_PATH} --config {config_path}"
        if policy_path:
            cmd += f" --policy {policy_path}"

        self.logger.info(f"Validating BGP++ config on {hostname}: {cmd}")

        # pyre-fixme[16]: `AbstractSwitch` has no attribute
        #  `async_execute_show_or_configure_cmd_on_shell`.
        output = await driver.async_execute_show_or_configure_cmd_on_shell(cmd)
        output_str = output or ""

        if "[PASS]" in output_str:
            self.logger.info(
                f"BGP++ config validation passed on {hostname}: {output_str.strip()}"
            )
        elif "[FAIL]" in output_str or "[ERROR]" in output_str:
            raise Exception(
                f"BGP++ config validation failed on {hostname}: {output_str.strip()}"
            )
        else:
            self.logger.warning(
                f"BGP++ config validator returned unexpected output on "
                f"{hostname}: {output_str.strip()}"
            )


class DeployEosImageTask(BaseTask):
    """
    Task to deploy an EOS image to an Arista device.

    Uses on-device wget to download the image directly from
    fbpkg.fbinfra.net, avoiding SSH/SCP file transfer.
    Follows the same pattern as push_unified_image_eb.

    Steps:
    1. Get blob hash from fbpkg metadata (on automation host)
    2. Download image tar via wget on device
    3. Verify SHA1 checksum
    4. Untar, move .swi to flash, set boot config
    5. Reload device and wait for boot

    This is designed to run as a PRE-IXIA task (ixia_needed=False) so it
    executes BEFORE any config tasks that need to persist after boot.
    """

    NAME = "deploy_eos_image"

    FLASH_DIR = "/mnt/flash"
    BOOT_TIMEOUT = 900  # 15 minutes
    WAIT_TIME_BEFORE_SSH_CHECK_SEC = 30

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        """
        Deploy EOS image to an Arista device.

        Args:
            params: Dictionary containing:
                - hostname: Device hostname (required)
                - eos_image_id: EOS image ID in fbpkg format, e.g.,
                    "neteng.arista_fboss.bag:tag" or full UUID (required)
                - clear_old_images: Clear old EOS images from flash (default: True)
        """
        import subprocess

        hostname = params["hostname"]
        eos_image_id = params["eos_image_id"]
        clear_old_images = params.get("clear_old_images", True)
        output_tar = "/tmp/fb-image.swi.tar"
        tmp_swi = "/tmp/fb-image.swi"

        self.logger.info(f"Deploying EOS image {eos_image_id} to {hostname}")

        # Step 1: Get blob hash from fbpkg metadata (runs on automation host)
        self.logger.info(f"  Getting blob hash for {eos_image_id}...")
        result = subprocess.run(
            ["fbpkg", "info", "--format=json", eos_image_id],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            raise Exception(
                f"fbpkg info failed (exit {result.returncode}): "
                f"{result.stderr or result.stdout}"
            )
        metadata = json.loads(result.stdout)
        blob_id = metadata["pkg_hash"]
        self.logger.info(f"  Blob ID (SHA1): {blob_id}")

        dst_name = self._get_dst_name(eos_image_id)

        try:
            driver = await async_get_device_driver(hostname)

            # Step 2: Check if the image already exists on the device
            if await self._check_existing_image(driver, hostname, dst_name):
                return

            # Step 3: Clear old images from flash (optional, before download)
            if clear_old_images:
                await self._clear_flash_images(driver)

            # Step 4: Clean up any old temp files on device
            self.logger.info("  Cleaning up old image files on device...")
            for cleanup_path in [output_tar, tmp_swi]:
                try:
                    await driver.async_run_cmd_on_shell(
                        f"bash sudo rm -rf {cleanup_path}"
                    )
                except Exception:
                    pass

            # Step 5: Download image tar via wget on device
            await self._wget_image_to_device(driver, hostname, blob_id, output_tar)

            # Step 6: Untar the image
            self.logger.info("  Untarring EOS image...")
            await driver.async_run_cmd_on_shell(
                f"bash timeout 30 sudo tar -C /tmp -xvf {output_tar}"
            )

            # Step 7: Clear flash space before moving new image
            await self._clear_flash_images(driver)

            # Step 8: Move .swi to flash
            self.logger.info(f"  Moving image to {self.FLASH_DIR}/{dst_name}...")
            await driver.async_run_cmd_on_shell(
                f"bash timeout 120 sudo mv {tmp_swi} {self.FLASH_DIR}/{dst_name}"
            )

            # Step 9: Verify the image is in flash
            verify_result = await driver.async_run_cmd_on_shell(
                f"bash ls -la {self.FLASH_DIR}/{dst_name}"
            )
            self.logger.info(f"  Verify image in flash: {verify_result}")
            if dst_name not in str(verify_result):
                raise Exception(f"Image not found in flash after move: {verify_result}")

            # Step 10: Set boot config with PORT_NUMBERING_SCHEME
            self.logger.info("  Setting boot config...")
            boot_config_content = (
                f"PORT_NUMBERING_SCHEME=OCTAL_4\\nSWI=flash:/{dst_name}"
            )
            boot_config_cmd = (
                f'bash echo -e "{boot_config_content}" | '
                f"sudo tee {self.FLASH_DIR}/boot-config"
            )
            await driver.async_run_cmd_on_shell(boot_config_cmd)

            # Step 11: Reload the device
            self.logger.info(f"  Reloading {hostname}...")
            try:
                await driver.async_run_cmd_on_shell("reload now")
            except Exception as e:
                self.logger.info(
                    f"  Reload initiated (connection dropped as expected): {e}"
                )

            # Step 12: Wait for device to boot
            await self._wait_for_boot(hostname)
            self.logger.info(f"  Successfully deployed EOS image to {hostname}")

        except Exception as e:
            self.logger.error(f"  Failed to deploy EOS image to {hostname}: {e}")
            raise

    def _get_dst_name(self, eos_image_id: str) -> str:
        """Generate destination filename for EOS image."""
        pkg_name = eos_image_id.split(":")[0]
        pkg_uuid = eos_image_id.split(":")[1] if ":" in eos_image_id else "latest"
        return f"fb-image-{pkg_name.replace('.', '_')}-{pkg_uuid}.swi"

    async def _wget_image_to_device(
        self,
        driver,
        hostname: str,
        blob_id: str,
        output_tar: str,
    ) -> None:
        """Download EOS image tar to device via wget from fbpkg.fbinfra.net.

        Tries ns-management namespace first, then default namespace.
        Verifies download via SHA1 checksum.
        """
        download_url = f"https://fbpkg.fbinfra.net/blob/{blob_id}"
        err_msgs = ["unreachable", "returned error code"]

        for namespace in ["ns-management", "default"]:
            # Check reachability
            self.logger.info(
                f"  Checking fbpkg.fbinfra.net reachability over {namespace}..."
            )
            try:
                ping_cmd = (
                    f"bash timeout 30 sudo ip netns exec {namespace} "
                    f"ping6 -c 2 fbpkg.fbinfra.net"
                )
                ping_result = await driver.async_run_cmd_on_shell(ping_cmd)
                if any(err in str(ping_result) for err in err_msgs):
                    self.logger.info(
                        f"  fbpkg.fbinfra.net unreachable over {namespace}"
                    )
                    continue
            except Exception as e:
                self.logger.info(f"  Reachability check failed for {namespace}: {e}")
                continue

            self.logger.info(f"  fbpkg.fbinfra.net reachable over {namespace}")

            # Download image
            self.logger.info(f"  Downloading image via wget over {namespace}...")
            try:
                wget_cmd = (
                    f"bash timeout 1800 sudo ip netns exec {namespace} "
                    f"wget {download_url} -O {output_tar} --no-check-certificate"
                )
                await driver.async_run_cmd_on_shell(wget_cmd)
            except Exception as e:
                self.logger.info(f"  wget failed over {namespace}: {e}")
                continue

            # Verify checksum
            self.logger.info("  Verifying image checksum...")
            try:
                checksum_result = await driver.async_run_cmd_on_shell(
                    f"bash timeout 30 sha1sum {output_tar}"
                )
                checksum_str = str(checksum_result).strip()
                if blob_id in checksum_str:
                    self.logger.info(
                        f"  Checksum verified. Download succeeded over {namespace}"
                    )
                    return
                self.logger.info(
                    f"  Checksum mismatch. Expected {blob_id}, got: {checksum_str}"
                )
            except Exception as e:
                self.logger.info(f"  Checksum verification failed: {e}")

            # Clean up failed download
            try:
                await driver.async_run_cmd_on_shell(
                    f"bash timeout 10 sudo rm -rf {output_tar}"
                )
            except Exception:
                pass

        raise Exception(
            f"Failed to download EOS image to {hostname} "
            f"over both ns-management and default namespaces"
        )

    async def _check_existing_image(
        self,
        driver,
        hostname: str,
        dst_name: str,
    ) -> bool:
        """Check if image already exists on device. Returns True if handled."""
        self.logger.info(f"  Checking if {dst_name} already exists...")
        check_cmd = (
            f"bash ls -la {self.FLASH_DIR}/{dst_name} 2>/dev/null || echo 'NOT_FOUND'"
        )
        check_result = await driver.async_run_cmd_on_shell(check_cmd)

        if dst_name not in str(check_result) or "NOT_FOUND" in str(check_result):
            return False

        self.logger.info(
            f"  Image {dst_name} already exists on device, skipping upload"
        )

        # Set boot config
        self.logger.info("  Setting boot config...")
        boot_config_content = f"PORT_NUMBERING_SCHEME=OCTAL_4\\nSWI=flash:/{dst_name}"
        boot_config_cmd = (
            f'bash echo -e "{boot_config_content}" | '
            f"sudo tee {self.FLASH_DIR}/boot-config"
        )
        await driver.async_run_cmd_on_shell(boot_config_cmd)

        # Check if reload is needed
        current_boot = await driver.async_run_cmd_on_shell(
            f"bash cat {self.FLASH_DIR}/boot-config"
        )
        if dst_name in str(current_boot):
            self.logger.info(
                f"  Boot config already points to {dst_name}, "
                f"checking current version..."
            )
            version_result = await driver.async_run_cmd_on_shell(
                "show version | grep image"
            )
            if dst_name in str(version_result):
                self.logger.info(
                    f"  Device already running {dst_name}, skipping reload"
                )
                return True

        # Reload needed
        self.logger.info(f"  Reloading {hostname} to boot new image...")
        try:
            await driver.async_run_cmd_on_shell("reload now")
        except Exception as e:
            self.logger.info(
                f"  Reload initiated (connection dropped as expected): {e}"
            )

        await self._wait_for_boot(hostname)
        return True

    async def _clear_flash_images(self, driver) -> None:
        """Clear old EOS images from flash."""
        self.logger.info("  Clearing old images from flash...")
        clear_cmds = [
            f"bash sudo rm -rf {self.FLASH_DIR}/.extensions",
            f"bash sudo rm -rf {self.FLASH_DIR}/expected-boot-extension",
            f"bash sudo rm -rf {self.FLASH_DIR}/boot-extensions",
            f"bash sudo rm -rf {self.FLASH_DIR}/fb-image*.swi",
            f"bash sudo rm -rf {self.FLASH_DIR}/EOS*.swi",
        ]
        for cmd in clear_cmds:
            try:
                await driver.async_run_cmd_on_shell(cmd)
            except Exception:
                pass

    async def _wait_for_boot(self, hostname: str) -> None:
        """Wait for device to boot after reload."""
        self.logger.info(f"  Waiting for {hostname} to boot...")

        # Clear the memoized driver cache so that subsequent
        # operations get fresh driver connections after the device reload
        if hasattr(async_get_device_driver, "cache_clear"):
            self.logger.info("  Clearing driver cache after reload...")
            # pyre-fixme[16]: Callable `async_get_device_driver` has no attribute
            #  `cache_clear`.
            async_get_device_driver.cache_clear()

        retries = self.BOOT_TIMEOUT / self.WAIT_TIME_BEFORE_SSH_CHECK_SEC
        while retries > 0:
            retries -= 1
            try:
                driver = await async_get_device_driver(hostname)
                await driver.async_run_cmd_on_shell("show version")
                self.logger.info(f"  {hostname} is back online")
                break
            except Exception as e:
                self.logger.info(f"  Device still rebooting: {e}")
            self.logger.info(
                f"  Waiting {self.WAIT_TIME_BEFORE_SSH_CHECK_SEC}s before retry"
            )
            await asyncio.sleep(self.WAIT_TIME_BEFORE_SSH_CHECK_SEC)
        else:
            raise Exception(
                f"Timed out waiting for {hostname} to boot after {self.BOOT_TIMEOUT}s"
            )

        # Wait additional time for interfaces to stabilize after boot
        self.logger.info("  Waiting 30s for interfaces to stabilize after boot...")
        await asyncio.sleep(30)


class SetPortChannelMinLinkPatcherTask(BaseTask):
    NAME = "set_port_channel_min_link_patcher"

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        hostname = params["hostname"]
        port_channel_name = params["port_channel_name"]
        min_link_percentage = params["min_link_percentage"]
        min_link_up_percentage = params["min_link_up_percentage"]
        patcher_name = params.get(
            "patcher_name", "configure_port_channel_min_link_percentage"
        )
        description = params.get(
            "description", f"Min link capacity for {port_channel_name}"
        )

        driver = await async_get_device_driver(hostname)
        patcher_args = {
            "link_percentage": str(min_link_percentage),
            "port_channel_name": port_channel_name,
        }
        if min_link_up_percentage is not None:
            patcher_args["min_link_up_percentage"] = str(min_link_up_percentage)

        # pyre-fixme[16]: `AbstractSwitch` has no attribute
        #  `async_register_python_patcher`.
        await driver.async_register_python_patcher(
            config_name="agent",
            patcher_name=patcher_name,
            py_func_name="set_port_channel_min_link_capacity",
            patcher_args=patcher_args,
            patcher_desc=description,
        )


class AssertThriftRateLimitEnabledTask(BaseTask):
    """Setup-gate task: fail-fast if `thriftApiToRateLimitInQps` is empty in
    the DUT's COOP-materialized agent config.

    Background: the THFT (thrift-hardening) testconfig fires ~7,000
    concurrent read-only thrift calls per burst against `fboss_sw_agent`.
    Without server-side rate limiting (configerator
    `agent_thrift_api_to_rate_limit.mcconf`), the storm pegs CPU and can
    cascade into kernel OOMs on swap-tight hosts (see T275336067 /
    T275512222). With rate limiting on, the agent throttles excess calls
    and CPU stays bounded (confirmed working on gtsw001 2026-06-11: bgpd
    1% CPU under 10K-concurrent storm vs 1339% pre-D108220182).

    D108220182 removed `ICECUBE800BC` from the EMPTY_HW exclusion list so
    RTSW/FTSW/STSW/GTSW roles on TH6 IcePack now pick up the default
    `thriftApiToRateLimitInQps` map (~140 APIs at 2-8 qps each). This task
    asserts that landed reality on the DUT before any THFT playbook runs;
    if the map is missing or empty, the test fails immediately with a
    clear pointer rather than burning a 4-hour soak before the postcheck
    catches the symptom.

    Implementation: reads the COOP-materialized agent config at
    `/etc/coop/agent/current` on the DUT (this is the canonical "running"
    config — what the FBOSS agent actually loads on (re)start, and what
    `/dev/shm/fboss/agent_startup_config` symlinks to). Verified on
    gtsw001 2026-06-11 that the `thriftApiToRateLimitInQps` key lives at
    the top level of this JSON with ~140 APIs populated. Earlier shelved
    implementation that called `getRunningConfig()` thrift API on the
    agent did NOT find the key because that thrift API returns a different
    (filtered) view of the config; the COOP-materialized file is the
    authoritative source. Parsing is done server-side via a small Python
    script (sent base64-encoded to avoid shell-quoting fragility) so we
    transfer ~50 bytes of summary instead of the full 830 KB config blob.

    Probe states (one printed per run, parsed by `run()` for tailored
    error messages so on-call can distinguish failure modes without re-
    running the probe by hand):

      OK size=<N> sample=<k=v,...>     map is populated; precheck passes
      MISSING                          key absent at top level
      WRONG_TYPE type=<typename>       key present but not a dict (list/str/int/...)
      EMPTY                            key present, is a dict, but empty
      NOT_DICT type=<typename>         the entire config root is not a dict
      MISSING_FILE path=<p>            config file does not exist on the DUT
      INVALID_JSON error=<ExcName: ..> open()/json.loads() raised
      ERROR <ExcName: ...>             any other unexpected exception (catch-all)
    """

    NAME = "assert_thrift_rate_limit_enabled"
    THRIFT_RATE_LIMIT_KEY = "thriftApiToRateLimitInQps"
    AGENT_CONFIG_PATH = "/etc/coop/agent/current"

    # Multi-line python script run on the DUT. Sent base64-encoded so we
    # don't have to escape quotes/newlines in the shell command. Catches
    # every failure mode and emits a single structured status line on
    # stdout so the caller can distinguish file-missing / parse-error /
    # wrong-type / empty / populated without re-running by hand.
    _PROBE_SCRIPT: str = """
import json, os, sys
PATH = {path!r}
KEY = {key!r}
try:
    if not os.path.exists(PATH):
        print(f'MISSING_FILE path={{PATH}}')
        sys.exit(0)
    with open(PATH) as f:
        raw = f.read()
    try:
        cfg = json.loads(raw)
    except (ValueError, TypeError) as e:
        print(f'INVALID_JSON error={{type(e).__name__}}: {{e}}')
        sys.exit(0)
    if not isinstance(cfg, dict):
        print(f'NOT_DICT type={{type(cfg).__name__}}')
        sys.exit(0)
    m = cfg.get(KEY)
    if m is None:
        print('MISSING')
    elif not isinstance(m, dict):
        print(f'WRONG_TYPE type={{type(m).__name__}}')
    elif len(m) == 0:
        print('EMPTY')
    else:
        print(f'OK size={{len(m)}} sample=' + ','.join(f'{{k}}={{v}}' for k, v in list(m.items())[:5]))
except Exception as e:
    print(f'ERROR {{type(e).__name__}}: {{e}}')
"""

    # Prefixes the probe script emits — one of these MUST be at the start
    # of the status line. The `OK ` trailing-space prefix is intentional
    # (distinguishes "OK size=..." status from anything that happens to
    # start with the substring "OK").
    _STATUS_PREFIXES: tuple = (
        "OK ",
        "MISSING_FILE ",
        "INVALID_JSON ",
        "NOT_DICT ",
        "WRONG_TYPE ",
        "ERROR ",
        "MISSING",
        "EMPTY",
    )

    @classmethod
    def _build_probe_cmd(cls) -> str:
        """Encode the probe script as base64 and wrap it in a shell command
        that decodes + pipes to python3, with stderr merged so any shell-
        level failure (python3-not-found, base64-not-found) surfaces in
        the captured output instead of disappearing."""
        script = cls._PROBE_SCRIPT.format(
            path=cls.AGENT_CONFIG_PATH, key=cls.THRIFT_RATE_LIMIT_KEY
        )
        b64 = base64.b64encode(script.encode("utf-8")).decode("ascii")
        return f"echo {b64} | base64 -d | python3 - 2>&1"

    @classmethod
    def _extract_status_line(cls, raw: str) -> t.Optional[str]:
        """Find the structured status line in the probe's output.

        Since we redirect stderr to stdout via `2>&1`, any incidental
        stderr noise (DeprecationWarning, locale banners, sudo messages,
        thrift-py-deprecated warnings) can prepend or interleave with the
        status line. The probe script emits EXACTLY ONE status line, so
        we scan ALL lines and return the LAST one that starts with a
        known status prefix. This makes the parser tolerant of stderr
        noise while still failing cleanly if no status line is present.
        """
        if not raw:
            return None
        for line in reversed(raw.splitlines()):
            stripped = line.strip()
            if not stripped:
                continue
            for prefix in cls._STATUS_PREFIXES:
                if stripped == prefix or stripped.startswith(prefix):
                    return stripped
        return None

    def _raise_for_probe_status(
        self, hostname: str, result: str, probe_cmd: str
    ) -> None:
        """Translate a structured probe-status line into a tailored
        RuntimeError. Caller has already verified result is non-empty and
        is not the success ('OK ...') case. Raises in every code path
        (catch-all at the end handles unrecognized output)."""
        if result == "MISSING":
            raise RuntimeError(
                f"{hostname}: `{self.THRIFT_RATE_LIMIT_KEY}` not found at "
                f"top level of {self.AGENT_CONFIG_PATH}. Thrift API rate "
                f"limiting is NOT enabled — refusing to start a THFT "
                f"(thrift-hardening) run because the storm will overload "
                f"`fboss_sw_agent`. See D108220182 (enables defaults for "
                f"ICECUBE800BC) and verify the configerator change has "
                f"shipped + COOP has re-applied the agent config on this "
                f"host."
            )
        if result.startswith("WRONG_TYPE "):
            raise RuntimeError(
                f"{hostname}: `{self.THRIFT_RATE_LIMIT_KEY}` is present in "
                f"{self.AGENT_CONFIG_PATH} but is NOT a dict ({result}). "
                f"Expected mapping of API-name → qps int. The COOP-side "
                f"schema may have changed; inspect the config and the "
                f"`agent_thrift_api_to_rate_limit.mcconf` materialization "
                f"path."
            )
        if result == "EMPTY":
            raise RuntimeError(
                f"{hostname}: `{self.THRIFT_RATE_LIMIT_KEY}` is present "
                f"and is a dict but empty in {self.AGENT_CONFIG_PATH}. "
                f"Thrift API rate limiting is effectively disabled — "
                f"refusing to start THFT run. See D108220182."
            )
        if result.startswith("NOT_DICT "):
            raise RuntimeError(
                f"{hostname}: root of {self.AGENT_CONFIG_PATH} is not a "
                f"dict ({result}). The COOP-materialized config schema "
                f"may have changed; cannot probe for "
                f"`{self.THRIFT_RATE_LIMIT_KEY}`."
            )
        if result.startswith("MISSING_FILE "):
            raise RuntimeError(
                f"{hostname}: COOP-materialized agent config does not "
                f"exist on the DUT ({result}). COOP may not have applied "
                f"the agent config yet — try `systemctl restart coop` and "
                f"wait for the file to materialize at "
                f"{self.AGENT_CONFIG_PATH}."
            )
        if result.startswith("INVALID_JSON "):
            raise RuntimeError(
                f"{hostname}: {self.AGENT_CONFIG_PATH} exists but is not "
                f"valid JSON ({result}). The file may have been truncated "
                f"by a partial COOP write — re-fetch via `coop` CLI."
            )
        if result.startswith("ERROR "):
            raise RuntimeError(
                f"{hostname}: probe script hit an unexpected exception "
                f"({result}). Re-run the probe manually on the DUT to "
                f"reproduce: {probe_cmd}"
            )
        # Catch-all: shell-level failure (e.g. python3 not on PATH, base64
        # missing) or unrecognized output. Include the raw output so on-
        # call can diagnose without re-running.
        raise RuntimeError(
            f"{hostname}: unexpected probe output (likely python3/base64 "
            f"missing on the remote, or a shell-level failure). Raw: "
            f"{result[:500]!r}"
        )

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        hostname = params["hostname"]
        driver = await async_get_device_driver(hostname)
        probe_cmd = self._build_probe_cmd()
        # pyre-ignore[16]: AbstractSwitch has no attribute `async_run_cmd_on_shell`
        raw = await driver.async_run_cmd_on_shell(probe_cmd)
        raw_str = raw or ""
        # Tolerate stderr noise (DeprecationWarning, locale banners) that
        # gets merged into stdout by `2>&1`. The probe emits exactly one
        # status line; scan ALL lines and pick the last one matching a
        # known prefix. Falling back to the catch-all if no line matches.
        status = self._extract_status_line(raw_str)
        if status is None:
            raise RuntimeError(
                f"{hostname}: probe output contained no recognizable "
                f"status line (likely shell exited before writing, or "
                f"python3/base64 missing on the remote). Raw (first 500 "
                f"chars): {raw_str.strip()[:500]!r}. Probe was: {probe_cmd}"
            )
        if status.startswith("OK "):
            # "OK size=N sample=k1=v1,k2=v2,..."
            self.logger.info(
                f"{hostname}: thrift API rate limiting is ENABLED. "
                f"Probe output: {status}"
            )
            return
        self._raise_for_probe_status(hostname, status, probe_cmd)
