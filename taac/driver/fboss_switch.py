#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
import asyncio
import datetime
import ipaddress
import json
import logging
import os
import random
import re
import socket
import time
import typing
import typing as t
from collections import defaultdict
from contextlib import asynccontextmanager
from enum import Enum
from functools import reduce
from ipaddress import ip_address, ip_network, IPv4Interface, IPv6Interface
from typing import (
    Any,
    AsyncGenerator,
    DefaultDict,
    Dict,
    List,
    Mapping,
    Optional,
    Sequence,
    Set,
    Tuple,
    Union,
)

# =============================================================================
# Third-party (PyPI / OSS-compatible)
# =============================================================================
import bunch

# =============================================================================
# FBOSS thrift types & clients (already OSS'd)
# =============================================================================
import neteng.fboss.bgp_thrift.types as fboss_bgp_thrift_types
import neteng.fboss.fsdb.types as fsdb_types
import pexpect
from fboss.fb_thrift_clients import FbossAgentClient, FbossAgentClientWrapper
from neteng.fboss.bgp_attr.types import TBgpAfi, TIpPrefix
from neteng.fboss.bgp_route_types.types import TBgpPath, TRibEntry
from neteng.fboss.bgp_thrift.clients import TBgpService
from neteng.fboss.bgp_thrift.types import TBgpPeerState, TBgpSession, TOriginatedRoute
from neteng.fboss.ctrl.clients import FbossCtrl
from neteng.fboss.ctrl.types import (
    AggregatePortThrift,
    ArpEntryThrift,
    DsfSessionThrift,
    FabricEndpoint,
    HwObjectType,
    InterfaceDetail,
    L2EntryThrift,
    LinkNeighborThrift,
    MultiSwitchRunState,
    NdpEntryThrift,
    PortAdminState,
    PortInfoThrift,
    PortOperState,
    PortStatus,
    RouteDetails,
    SwitchRunState,
    SystemPortThrift,
    UnicastRoute,
)
from neteng.fboss.fboss.types import FbossBaseError
from neteng.fboss.fsdb.clients import FsdbService
from neteng.fboss.hardware_stats.types import CpuPortStats
from neteng.fboss.hw_ctrl.clients import FbossHwCtrl
from neteng.fboss.phy.phy.types import PortComponent
from neteng.fboss.switch_config.thrift_types import SwitchDrainState
from neteng.fboss.switch_config.types import DsfNode
from neteng.fboss.transceiver import thrift_types as transceiver_types
from neteng.fboss.transceiver.thrift_types import ReadRequest, TransceiverIOParameters

# =============================================================================
# TAAC / DNE (OSS-compatible)
# =============================================================================
from taac.driver.abstract_switch import (
    AbstractSwitch,
    TestingException,
)
from taac.driver.driver_constants import (
    _ONE_MBPS,
    ALLOWED_FBOSS_AGENTS,
    AristaCriticalAgents,
    BGP_SUMMARY_HEADER,
    BgpPeerAction,
    CoreDumpFiles,
    DEFAULT_AGENT_REMOTE_PORT,
    DEFAULT_THRIFT_TIMEOUT,
    DeviceDrainState,
    EcmpGroup,
    EGRESS_PKT_RATE_KEY,
    EGRESS_RATE_KEY,
    FBOSS_CRITICAL_CORE_DUMPS,
    FBOSS_CRITICAL_CORE_NON_SELECTOR,
    FbossSystemctlServiceName,
    FSDB_PORT,
    HW_AGENT_BASE_PORT,
    HwCounters,
    INGRESS_RATE_KEY,
    InterfaceEventState,
    InterfaceFlapMethod,
    InterfaceInfo,
    NextHopAttributes,
    OPENR_FIB_AGENT_PORT,
    OPENR_THRIFT_CALL_TIMEOUT,
    OpenrKvStoreDetails,
    PortCounters,
    Service,
    ServiceStatusCounters,
    SwitchLldpData,
    SystemctlServiceName,
    SystemctlServiceStatus,
    SystemRebootMethod,
    WAIT_FOR_DEVICE_UP_AFTER_REBOOT,
)
from taac.driver.drivers_common import (
    BgpPeerNotFoundError,
    CommandExecutionError,
    DomValidationError,
    EmptyOutputReturnError,
    get_tabulated_output,
    InterfaceNotFoundError,
    InvalidInputError,
    InvalidIpAddressError,
    is_dne_test_device,
    QsfpThriftException,
)
from taac.driver.memoize_on_app_overload import (
    memoize_on_app_overload,
)
from taac.utils.common import (
    async_everpaste_str,
    create_everpaste_fburl,
)
from taac.utils.oss_driver_utils import AsyncSSHClient
from taac.utils.oss_taac_lib_utils import (
    async_memoize_timed,
    async_retryable,
    await_sync,
    ConsoleFileLogger,
    convert_to_async,
    none_throws,
    retryable,
    to_fb_fqdn,
    to_fb_uqdn,
)

TAAC_OSS = os.environ.get("TAAC_OSS", "").lower() in ("1", "true", "yes")

if not TAAC_OSS:
    from openr.py.openr.cli.utils.commands import OpenrCtrlCmd
    from openr.py.openr.clients.openr_client import get_openr_ctrl_cpp_client
    from openr.thrift.KvStore.thrift_types import KeyDumpParams
    from openr.thrift.OpenrCtrl.thrift_types import (
        AdjacenciesFilter,
        AdvertisedRouteFilter,
        ReceivedRouteFilter,
    )
    from openr.thrift.Platform.types import FibClient
    from openr.thrift.Types.thrift_types import AdjacencyDatabase
from thrift.py3.exceptions import Error as ThriftError
from thrift.python.exceptions import Error as ThriftPythonError


def fb_gethostbyname(hostname: str) -> str:
    """Resolve hostname to IP address."""
    return socket.gethostbyname(hostname)


PexpectSpawnType = pexpect.spawn


class Reason(Enum):
    COOP_NOT_RESPONDING = 0


class InsufficientInputError(Exception):
    pass


class NoOOBError(ValueError):
    """Error to indicate an FBOSS device does not have a oob hostname
    - Should be impossible"""

    pass


class FBOSSConsoleError(Exception):
    """Error to indicate issues with the FBOSS console session"""

    pass


class MnpuNotEnabled(Exception):
    pass


class FbossSwitch(AbstractSwitch):
    def __init__(self, hostname: str, logger: logging.Logger, *args, **kwargs) -> None:
        super().__init__(hostname, logger)

    # pyre-fixme[11]: Annotation `FbossAgentClient` is not defined as a type.
    def _get_fboss_agent_client(self) -> FbossAgentClient:
        client = FbossAgentClient(
            self.hostname,
            port=DEFAULT_AGENT_REMOTE_PORT,
            timeout=DEFAULT_THRIFT_TIMEOUT,
        )
        if not client:
            self.logger.info(
                f"Failed to connect to {self.hostname}. Please make sure that the agent on {self.hostname} is UP!"
            )
            raise Exception(
                f"Failed to connect to {self.hostname}. Please make sure that the agent on {self.hostname} is UP!"
            )
        return client

    async def async_get_fboss_build_info_show(self) -> str:
        raise NotImplementedError(
            "FBOSS build info not available in OSS mode. "
            "Use FbossSwitchInternal for SSH-based build info retrieval."
        )

    async def async_get_all_hw_drops(self) -> HwCounters:
        """
        Yet to be implemented, will start implementing once we start qualifying
        Modular chassis for offline regions
        """
        # TODO: Implement Getting hardware counters for FBOSS for offline regions qualification
        raise TestingException("Getting Hardware counters yet to be implemented")

    async def async_clear_all_hw_counters(self) -> None:
        """
        Yet to be implemented, will start implementing once we start qualifying
        FBOSS Modular chassis for offline regions
        """
        # TODO: Implement clearing hardware counters for FBOSS for offline regions qualification
        raise TestingException("Clearing Hardware counters yet to be implemented")

    async def async_is_modular_chassis(self) -> bool:
        """
        Checks if the given device is a Modular chassis, returns true if it is
        a modular chassis, or false if it isn't
        Also, in this case we treat a chassis as modlular only if it support hardware counters
        """
        # TODO: Implement is_modular_chassis for FBOSS devices
        raise TestingException("is_modular_chassis yet to be implemented for FBOSS")

    async def async_clear_all_port_counters(self) -> None:
        """
        Clear all port counters on device
        """
        all_port_info = await self.async_get_all_port_info()
        port_ids = list(all_port_info.keys())
        await self._async_fboss_clear_port_stats(port_ids)

    async def async_get_multiple_port_stats(
        self,
        interface_names: Optional[List[str]] = None,
    ) -> List[PortCounters]:
        """
        Returns a list of port counters, each comprising of the input/output errors and
        discards for all interfaces on the device.
        Args:
            interface_names: if provided will return only counters for provided interfaces
                            Example: ["eth1/1/1", "eth1/2/1"]
        """
        port_counters: List = []
        all_port_info = await self.async_get_all_port_info()

        port_counters = [
            PortCounters(
                device_name=self.hostname,
                interface_name=port_info.name,
                out_discards=port_info.output.errors.discards,
                out_error=port_info.output.errors.errors,
                in_discards=port_info.input.errors.discards,
                in_error=port_info.input.errors.errors,
            )
            for port_info in all_port_info.values()
        ]
        # filter specific interfaces if requested
        if interface_names:
            port_counters = [
                port_counter
                for port_counter in port_counters
                if port_counter.interface_name in interface_names
            ]

        counter_fburl: str = await async_everpaste_str(str(port_counters), color=False)
        self.logger.info(f"Port counter values for {self.hostname}: {counter_fburl}")
        return port_counters

    async def async_get_qsfp_client(self):
        raise NotImplementedError(
            "QsfpService client not available in OSS mode. "
            "Use FbossSwitchInternal for ServiceRouter-based connection."
        )

    async def async_qsfp_get_transceiver_inf_count(
        self,
    ) -> None:
        try:
            async with await self.async_get_qsfp_client() as qsfp_client:
                txcvr_info = await qsfp_client.getTransceiverInfo([])
                self.logger.info(f"txcvr_count: {len(txcvr_info)}")
        except Exception as e:
            self.logger.error(f"Error attempting to get transceiver info count: {e}")

    async def async_get_transceiver_register(
        self,
    ):
        """
        Used to get the mapping of the transceiver id to the ports TransceiverInfo using
        a Thrift api call.
        If the fetch is unsuccessful raises an Exception
        """
        try:
            async with await self.async_get_qsfp_client() as qsfp_client:
                id_info_map = await qsfp_client.getTransceiverInfo([])
                read_request = ReadRequest(
                    ids=list(id_info_map.keys()),
                    parameter=TransceiverIOParameters(offset=0, length=128),
                )
                read_register = await qsfp_client.readTransceiverRegister(read_request)
                self.logger.info(f"read register: {read_register}")
                return read_register
        except Exception as ex:
            raise QsfpThriftException(
                f"Error occured during a thrift call for readTransceiverRegister {ex}"
            )

    async def async_get_dump_transceiver_i2c_log(
        self,
    ):
        try:
            intf_map_result: Dict[
                str, InterfaceInfo
            ] = await self.async_get_all_interfaces_info()
            interface_names = list(intf_map_result.keys())
            dump_transceiver_i2c_log_list = []
            async with await self.async_get_qsfp_client() as qsfp_client:
                for interface_name in interface_names:
                    dump_transceiver_i2c_log = await qsfp_client.dumpTransceiverI2cLog(
                        interface_name
                    )
                    dump_transceiver_i2c_log_list.append(dump_transceiver_i2c_log)
                    self.logger.info(f"{dump_transceiver_i2c_log=}")
                return dump_transceiver_i2c_log
        except Exception as ex:
            raise QsfpThriftException(
                f"Error occured during a thrift call for dumpTransceiverI2cLog {ex}"
            )

    async def async_get_interface_name_from_port_id(self, port_id: int) -> str:
        """
        Used to fetch the interface name (F.ex Eth1/1/1) given the
        Port ID information
        """
        intf_map_result: Dict[
            str, InterfaceInfo
        ] = await self.async_get_all_interfaces_info()

        for interface_name, port_info in intf_map_result.items():
            if port_info and port_id == port_info.port_id:
                return interface_name

        raise InterfaceNotFoundError(
            f"Could not find any interface matching the Port ID {port_id} "
            f"on {self.hostname}"
        )
        return

    ########################
    # CAPTURE DUT METADATA #
    ########################

    async def get_async_get_sr_client(self):
        raise NotImplementedError(
            "CoopService client not available in OSS mode. "
            "Use FbossSwitchInternal for ServiceRouter-based connection."
        )

    @is_dne_test_device
    @async_retryable(retries=20, sleep_time=5, exceptions=(Exception,))
    async def async_agent_config_reload(self) -> None:
        """
        Reloads the agent config and ensure the wedge_agent is stable and
        converged (CONFIGURED state)
        """
        with FbossAgentClientWrapper(
            host=self.hostname, timeout=DEFAULT_THRIFT_TIMEOUT
        ) as agent_client:
            agent_client.reloadConfig()
            self.logger.info(
                f"Successfully reloaded the agent config on {self.hostname} "
            )
        # Ensure agent is converged (CONFIGURED) state after reloading the config
        await self.async_wait_for_agent_state_configured()

    @is_dne_test_device
    async def async_try_agent_config_reload(self) -> None:
        """
        Try agent config reload to apply agent patcher(s). On failure, resort
        to agent warmboot
        """
        try:
            with FbossAgentClientWrapper(
                host=self.hostname, timeout=DEFAULT_THRIFT_TIMEOUT
            ) as agent_client:
                agent_client.reloadConfig()
                self.logger.info(
                    f"Successfully reloaded the agent config on {self.hostname} "
                )
        except Exception:
            self.async_restart_service(FbossSystemctlServiceName.AGENT)
        await self.async_wait_for_agent_state_configured()

    @async_retryable(retries=30, sleep_time=6, exceptions=(Exception,))
    async def async_check_ports_admin_states(
        self, interfaces: List[str], desired_interface_state: bool
    ) -> None:
        all_ports_admin_status: Dict[
            str, bool
        ] = await self.async_get_all_interfaces_admin_status()
        action: str = "enabled" if desired_interface_state else "disabled"
        for interface in interfaces:
            self.test_case_obj.assertEqual(
                all_ports_admin_status[interface],
                desired_interface_state,
                msg=f"Looks like the interface {interface} was not persistently "
                f"{action} as expected. Please check!",
            )
        self.logger.info(
            "Successfully validated the admin states of all the ports that "
            f"were {action} on {self.hostname} and it looks good!"
        )

    @memoize_on_app_overload()
    async def async_get_all_aggregated_interfaces(
        self,
    ) -> Dict[str, List[str]]:
        """
        Used to fetch and create a mapping for all the aggregated logical
        interfaces to their physical member ports
        Note: The output will have the interface names (F.ex, Port-Channel-100)
        as opposed to the Port ID

        Sample Output:
        {
            <agg_intf_name_1>: [<member_port_name_1>, <member_port_name_2>, ...],
            <agg_intf_name_2>: [<member_port_name_1>, <member_port_name_2>, ...],
        }
        """
        agg_intf_map: DefaultDict[str, List[str]] = defaultdict(list)
        agg_port_info_table: Sequence[
            AggregatePortThrift
        ] = await self.async_get_all_aggregated_port_info()

        if not agg_port_info_table:
            return {}
        for agg_port_info in agg_port_info_table:
            for member_port in agg_port_info.memberPorts:
                member_port_name: str = (
                    await self.async_get_interface_name_from_port_id(
                        member_port.memberPortID
                    )
                )
                agg_intf_map[agg_port_info.name].append(member_port_name)
        return agg_intf_map

    async def async_get_aggregated_interface_status(
        self, aggregated_interface_name: str
    ) -> bool:
        all_aggregated_port_info = (
            # pyre-ignore: currently it only supports fboss devices
            await self.async_get_all_aggregated_port_info()
        )
        for agg_port_info in all_aggregated_port_info:
            port_channel_name = agg_port_info.name
            if aggregated_interface_name == port_channel_name:
                return agg_port_info.isUp
        raise Exception(f"{aggregated_interface_name} not found on {self.hostname}")

    @memoize_on_app_overload()
    async def async_get_all_interfaces_info(
        self,
    ) -> Dict[str, InterfaceInfo]:
        """
        Used to fetch the interface name to the internal Port ID mapping on
        FBOSS devices for all the interfaces using the Thrift API. This output
        can be compared with the CLI command output of 'fboss port details'
        that shows the mapping. Sample output: P59125449

        F.ex, Interface name eth402/4/1 is mapped to Port ID 96
        """
        intf_map: Dict = {}

        with self._get_fboss_agent_client() as client:
            port_info_result = client.getAllPortInfo()

        if not port_info_result:
            raise EmptyOutputReturnError(
                f"Empty Port Info result returned by getAllPortInfo() "
                f"for {self.hostname}"
            )

        for port_info in port_info_result.values():
            interface_name: str = port_info.name
            port_id: int = port_info.portId
            # pyrefly: ignore [bad-assignment]
            vlan_id: int = port_info.vlans[0] if port_info.vlans else None
            intf_map[interface_name] = InterfaceInfo(port_id=port_id, vlan_id=vlan_id)

        return intf_map

    @memoize_on_app_overload()
    async def async_get_all_aggregated_port_info(
        self,
    ) -> Sequence[AggregatePortThrift]:
        """
        Used to obtain the raw thrift object for the FBOSS Aggregated Portx
        Table. Sample Output: P59966459
        """
        async with self.async_agent_client as client:
            agg_port_info_table = await client.getAggregatePortTable()
        return agg_port_info_table

    async def async_get_interface_name_to_port_id_and_vlan_id(
        self, interface_name: str
    ) -> InterfaceInfo:
        """
        Used to fetch the interface name to (FBOSS Port ID, Internal VLAN ID)
        mapping for any given interface. This output can be compared with the
        CLI command output of 'fboss port details' that shows the mapping.

        Sample output: P59125449
        F.ex, Interface name eth402/4/1 is mapped to Port ID 96 and VLAN ID 2013
        """
        intf_map_result: Dict[
            str, InterfaceInfo
        ] = await self.async_get_all_interfaces_info()
        if interface_name not in intf_map_result:
            raise InterfaceNotFoundError(
                f"Interface {interface_name} was not found in the map "
                f"while trying to fetch its Port and Vlan ID"
            )

        return intf_map_result[interface_name]

    async def _async_get_interface_names_to_port_id_and_vlan_id(
        self, interface_names: List[str]
    ) -> Dict[str, InterfaceInfo]:
        """
        Used to fetch the interface name to (FBOSS Port ID, Internal VLAN ID)
        mapping for any given interface. This output can be compared with the
        CLI command output of 'fboss port details' that shows the mapping.

        Sample output: P59125449
        F.ex, Interface name eth402/4/1 is mapped to Port ID 96 and VLAN ID 2013
        """
        intf_map_result: Dict[
            str, InterfaceInfo
        ] = await self.async_get_all_interfaces_info()
        return {
            name: intf_map_result[name]
            for name in interface_names
            if name in intf_map_result
        }

    async def async_get_interfaces_status(
        self, interface_names: List[str], skip_logging: bool = False
    ) -> Dict[str, bool]:
        """
        Used to fetch the operational state of a given interface on FBOSS
        devices. True is returned if the interface is UP and False will be
        returned for UP/DOWN or DOWN/DOWN state.
        """
        oper_state = None
        # agg_intf_map is a dict that has the mapping between aggregated interfaces
        # and its member ports
        aggregated_interfaces = await self.async_get_all_aggregated_interfaces()
        intf_map_result: Dict[
            str, InterfaceInfo
        ] = await self.async_get_all_interfaces_info()
        interface_status_map: Dict[str, bool] = {}
        ports_status_map = await self.async_get_port_status()
        for interface_name in interface_names:
            # If the interface is an aggregated interface then its operational
            # status is checked
            if aggregated_interfaces and interface_name in aggregated_interfaces:
                oper_state = await self.async_get_aggregated_interface_status(
                    interface_name
                )

            # Otherwise, the operational status of the unbundled physical port
            # is checked
            else:
                port_vlan_id_res: InterfaceInfo = intf_map_result[interface_name]
                port_id = port_vlan_id_res.port_id
                if port_id not in ports_status_map:
                    raise InterfaceNotFoundError(
                        f"Please check if the Port ID {port_id} exists on "
                        f"{self.hostname} for interface {interface_name}"
                    )
                oper_state = ports_status_map[port_id].up
            if oper_state:
                self.logger.info(f"Interface {interface_name} on {self.hostname} is UP")
                interface_status_map[interface_name] = True
            else:
                self.logger.info(
                    f"Interface {interface_name} on {self.hostname} is DOWN"
                )
                interface_status_map[interface_name] = False
        return interface_status_map

    async def async_get_interfaces_speed_in_Gbps(
        self,
        interface_names: Optional[List[str]] = None,
    ) -> Dict[str, int]:
        """
        Used to fetch a snapshot of the speed in Gbps of all the
        interfaces on the DUT.
        """
        all_ports_info: Dict[int, PortInfoThrift] = await self.async_get_all_port_info()

        return {
            port_info.name: int(port_info.speedMbps / 1000)
            for port_info in all_ports_info.values()
            if not interface_names or port_info.name in interface_names
        }

    @memoize_on_app_overload()
    async def async_get_interfaces_speed_profile_id(
        self,
        interface_names: Optional[List[str]] = None,
    ) -> Dict[str, str]:
        """
        Used to fetch a snapshot of the speed in Gbps of all the
        interfaces on the DUT.
        """
        all_ports_info: Dict[int, PortInfoThrift] = await self.async_get_all_port_info()

        return {
            port_info.name: port_info.profileID
            for port_info in all_ports_info.values()
            if not interface_names or port_info.name in interface_names
        }

    @retryable(num_tries=30, sleep_time=2, max_duration=60, debug=False)
    def check_interface_status(self, interface_name: str, state) -> None:
        """
        Used to validate the expected interface status with the observed
        status depending on the state variable.

        @state: InterfaceEventState.STABLE|InterfaceEventState.UNSTABLE
        If the state is stable, interface_status is expected to be True
        (UP/enabled), otherwise it is expected to be False.
        """
        interface_status_map: Dict[str, bool] = asyncio.run(
            self.async_get_interfaces_status([interface_name])
        )
        intf_oper_status = interface_status_map[interface_name]
        if state == InterfaceEventState.STABLE:
            self.test_case_obj.assertTrue(
                intf_oper_status,
                msg=f"{self.hostname}:{interface_name} is NOT UP/enabled. Please check!",
            )
        elif state == InterfaceEventState.UNSTABLE:
            self.test_case_obj.assertFalse(
                intf_oper_status,
                msg=f"{self.hostname}:{interface_name} is NOT DOWN/disabled. Please check!",
            )

    # TODO: move a list of ignored files to configerator
    async def async_is_critical_core_dumps(
        self,
        core_dump_file: str,
        allow_listed_files: List[str],
    ) -> bool:
        """
        Return a list of substrings whose presence in the core files are high values signals
        """

        if any(key_word in core_dump_file for key_word in allow_listed_files):
            if any(
                ignore_word in core_dump_file
                for ignore_word in FBOSS_CRITICAL_CORE_NON_SELECTOR
            ):
                # Tests for events such is bgpd.dogpile
                return False
            # If key word do not have non-selector, then we return True
            return True
        # Returns False if there is not keyword in core dump file
        return False

    async def async_check_for_core_dump(
        self, start_time: float, critical_processes: Optional[List[str]] = None
    ) -> CoreDumpFiles:
        """
        Used to find the presence of core dump on the FBOSS DUT that can
        indicate a potential agent crash since the given start_time by
        searching under /var/tmp/cores/
        The return dataclass comprises of critical and non-critical core dumps
        identified for regression runs

        Args:
            start_time: Unix timestamp to filter core dumps newer than this time
            critical_processes: Optional list of critical process names. If not provided,
                              uses the default FBOSS_CRITICAL_CORE_DUMPS
        """
        CORE_DUMP_PATH = "/var/tmp/cores/"

        # Use provided critical processes or default to FBOSS_CRITICAL_CORE_DUMPS
        processes_to_check = critical_processes or FBOSS_CRITICAL_CORE_DUMPS

        self.logger.info(f"Checking if there are core dump files in {CORE_DUMP_PATH}")
        self.logger.info(f"Using critical processes: {processes_to_check}")

        core_dump_find_cmd = f"find {CORE_DUMP_PATH} -type f -newermt @{start_time}"
        core_dump_output: str = none_throws(
            await self.async_run_cmd_on_shell(
                core_dump_find_cmd,
            )
        )

        core_dump_files = CoreDumpFiles()
        for core_file_full_path in core_dump_output.splitlines() or []:
            core_file = core_file_full_path[len(CORE_DUMP_PATH) :]
            if await self.async_is_critical_core_dumps(
                core_file_full_path, processes_to_check
            ):
                core_dump_files.critical_core_dumps.append(core_file)
            else:
                core_dump_files.non_critical_core_dumps.append(core_file)
        return core_dump_files

    async def aysnc_collect_critical_core_dumps_logs(self, core_file_name: str) -> None:
        """
        Used to collect backtrace of critical core dump on the FBOSS DUT that can
        indicate a potential agent crash since the given start_time by
        searching under /var/tmp/cores

        """
        core_file = core_file_name
        core_dump_path = "/var/tmp/cores"
        raised_exception_message = "Error uploading file or file does not exist"
        file_location = f"{core_dump_path}/{core_file}"
        everpaste_url = await self.async_generate_everpaste_file_url(file_location)
        if everpaste_url == raised_exception_message:
            raise Exception(
                f"Error when collecting and uploading core file from  {self.hostname}"
            )

        self.logger.critical(
            f"Coredump logs for {core_file} in device {self.hostname} @ : {everpaste_url}"
        )

    @async_retryable(retries=3, sleep_time=10, exceptions=(Exception,))
    async def async_get_interface_neighbor(
        self, interface_name: str
    ) -> Optional[Tuple[str, str]]:
        """
        Return a tuple with the remote hostname and interface based on
        the interface_name if a corresponding LLDP entry is present.
        """
        aggregated_interface = await self.async_get_aggregated_interface(interface_name)
        if aggregated_interface:
            interface_name = aggregated_interface

        port_vlan_id_res: InterfaceInfo = (
            await self.async_get_interface_name_to_port_id_and_vlan_id(interface_name)
        )
        local_port = port_vlan_id_res.port_id
        self.logger.debug(f"{self.hostname}:{interface_name} maps to port {local_port}")

        self.logger.debug(
            f"Getting the neighbor connected to {self.hostname}:{interface_name}"
        )
        lldp_neighbors: Sequence[
            LinkNeighborThrift
        ] = await self._async_get_lldp_neighbors()

        for lldp_neighbor in lldp_neighbors:
            if lldp_neighbor.localPort == int(local_port):
                # pyre-fixme[9]: remote_dev has type `str`; used as `Optional[str]`.
                remote_dev: str = lldp_neighbor.systemName
                remote_port: str = lldp_neighbor.printablePortId
                self.logger.debug(
                    f"{self.hostname}:{interface_name} is connected to "
                    f"{remote_dev}:{remote_port}"
                )
                return (remote_dev, remote_port)

        # This might be applicable for cases where the interface is down and
        # there is no corresponding LLDP entry for that interface.
        raise InterfaceNotFoundError(
            f"No device was found to be connected on the remote side of "
            f"{self.hostname}:{interface_name}. Please check if this is expected!"
        )

    async def async_get_aggregated_interface(
        self, interface_name: str
    ) -> Optional[str]:
        """
        Used to validate if the given interface is a logical aggregated
        interface or not. If it is an aggregated interface, a random
        member port from the bundle will be returned. Otherwise None
        will be returned
        """
        aggregated_interfaces = await self.async_get_all_aggregated_interfaces()
        # Check if the DUT has any aggregated interfaces. If so, then check
        # if the given interface is in the mapping of aggregate interfaces
        if aggregated_interfaces and interface_name in aggregated_interfaces:
            self.logger.info(f"{interface_name} is an aggregated interface")
            return random.choice(aggregated_interfaces[interface_name])
        return None

    @is_dne_test_device
    @retryable(num_tries=2, sleep_time=10, debug=True)
    def get_service_status(
        self, service: FbossSystemctlServiceName
    ) -> SystemctlServiceStatus:
        """
        For a given service, returns its SystemctlServiceStatus state.
        """
        return asyncio.run(self.async_get_service_status(service))

    ##########################################
    # FBOSS INTERFACE BASED HELPER FUNCTIONS #
    ##########################################

    def enable_port(
        self,
        interface_name: str,
        flap_method: InterfaceFlapMethod,
        skip_validation: bool = False,
    ) -> bool:
        """
        Used to enable or bring up a specific interface on FBOSS devices
        depending on the method name used. True will be returned if the
        interface was successfully enabled, else an exception will be raised.
        Args:
            interface_name: interface name to flap
            flap_method: flap method to use
                THRIFT_PORT_STATE_CHANGE
                    Flap interface with a Thrift call
                FBOSS_WEDGE_QSFP_UTIL_TX
                    Flap interface with
                    wedge_qsfp_util -tx_disable/-tx_enable
                FBOSS_WEDGE_QSFP_UTIL_POWER
                    Flap interface with
                    wedge_qsfp_util -set_low_power/-clear_low_power

        """
        # Fetching the actual method name (string) from the Enum value (int)
        flap_method_name: str = flap_method.value

        self.logger.info(
            f"Attempting to enable {interface_name} using {flap_method_name} method on {self.hostname}"
        )
        intf_enable_method = getattr(self, flap_method_name)

        # Check if the given interface is an logical aggregated interface.
        # If so, enable/un-shut all its member ports and check if the
        # aggregated interface came up
        if asyncio.run(self.async_get_aggregated_interface(interface_name)):
            # pyre-ignore[9]: agg_intf_map is declared to have type `DefaultDict[str, List[str]]` but is used as type `Optional[DefaultDict[str, List[str]]]`.
            agg_intf_map: DefaultDict[str, List[str]] = asyncio.run(
                self.async_get_all_aggregated_interfaces()
            )
            member_ports = agg_intf_map[interface_name]
            for member_port in member_ports:
                result = intf_enable_method(member_port, enable=True)

                # If enabling one of the member ports failed, mark that as
                # an error by raising Exception and break out of the loop
                self.test_case_obj.assertTrue(
                    result,
                    msg=f"Attempt to enable member port {member_port} which "
                    f"is a part of the agg_intf {interface_name} using "
                    f"{flap_method_name} failed. Please check!",
                )

        # For normal unbundled physical ports
        else:
            result = intf_enable_method(interface_name, enable=True)
            self.test_case_obj.assertTrue(
                result,
                msg=f"Attempt to enable interface {interface_name} using "
                f"{flap_method_name} failed. Please check!",
            )
        if not skip_validation:
            asyncio.run(
                self.async_check_interface_status(
                    interface_name, state=InterfaceEventState.STABLE
                )
            )
        self.logger.info(
            f"Successfully enabled the interface {interface_name} "
            f"using {flap_method_name} on {self.hostname}"
        )
        return True

    def disable_port(
        self,
        interface_name: str,
        flap_method: InterfaceFlapMethod,
        skip_validation: bool = False,
    ) -> bool:
        """
        Used to disable or bring down a specific interface on FBOSS devices
        depending on the method name used. True will be returned if the
        interface was successfully disabled, else an exception will be raised.
        Args:
            interface_name: interface name to flap
            flap_method: flap method to use
                THRIFT_PORT_STATE_CHANGE
                    Flap interface with a Thrift call
                FBOSS_WEDGE_QSFP_UTIL_TX
                    Flap interface with
                    wedge_qsfp_util -tx_disable/-tx_enable
                FBOSS_WEDGE_QSFP_UTIL_POWER
                    Flap interface with
                    wedge_qsfp_util -set_low_power/-clear_low_power
            skip_validation: do not verify status after disabling
        """
        # Fetching the actual method name (string) from the Enum value (int)
        flap_method_name: str = flap_method.value

        self.logger.info(
            f"Attempting to disable {interface_name} using {flap_method_name} method on {self.hostname}"
        )
        intf_enable_method = getattr(self, flap_method_name)

        # check if the given interface is an logical aggregated interface.
        # If so, disable/shut all its member ports and check if the
        # aggregated interface went down
        if asyncio.run(self.async_get_aggregated_interface(interface_name)):
            # pyre-ignore[9]: agg_intf_map is declared to have type `DefaultDict[str, List[str]]` but is used as type `Optional[DefaultDict[str, List[str]]]`.
            agg_intf_map: DefaultDict[str, List[str]] = asyncio.run(
                self.async_get_all_aggregated_interfaces()
            )
            member_ports = agg_intf_map[interface_name]
            result = True
            for member_port in member_ports:
                result = intf_enable_method(member_port, enable=False)

                # If disabling one of the member ports failed, mark that as
                # an error by raising Exception and break out of the loop
                self.test_case_obj.assertTrue(
                    result,
                    msg=f"Attempt to disable member port {member_port} which "
                    f"is a part of the agg_intf {interface_name} using "
                    f"{flap_method_name} failed. Please check!",
                )

                # Else if that member port was successsfully disabled, break
                # out of the for loop and return True
                self.logger.info(
                    f"Bundled member port {member_port} was successfully disabled"
                )
                break

        # For normal unbundled physical ports
        else:
            result = intf_enable_method(interface_name, enable=False)
            self.test_case_obj.assertTrue(
                result,
                msg=f"Attempt to disable interface {interface_name} using "
                f"{flap_method_name} failed. Please check!",
            )

        if not skip_validation:
            asyncio.run(
                self.async_check_interface_status(
                    interface_name, state=InterfaceEventState.UNSTABLE
                )
            )

        self.logger.info(
            f"Successfully disabled the interface {interface_name} "
            f"using {flap_method_name} on {self.hostname}"
        )
        return True

    async def async_register_patcher_to_shut_ports_persistently(
        self, patcher_name: str, interfaces: List[str], additional_desc=None
    ) -> None:
        raise NotImplementedError(
            "Persistent port shut patcher not available in OSS mode. "
            "Use FbossSwitchInternal for COOP-based patcher operations."
        )

    async def async_unregister_patcher_to_shut_ports_persistently(
        self, patcher_name: str, interfaces: List[str]
    ) -> None:
        raise NotImplementedError(
            "Persistent port shut patcher not available in OSS mode. "
            "Use FbossSwitchInternal for COOP-based patcher operations."
        )

    async def async_add_static_route_patcher(
        self,
        prefix_to_next_hops_map: Dict[str, List[str]],
        patcher_name: str,
        patcher_desc: str = "",
        is_patcher_name_uuid_needed: bool = True,
    ) -> str:
        raise NotImplementedError(
            "Static route patcher not available in OSS mode. "
            "Use FbossSwitchInternal for COOP-based patcher operations."
        )

    async def async_coop_unregister_patchers(
        self, patcher_name: str, config_name: Optional[str] = None
    ) -> None:
        raise NotImplementedError(
            "COOP patcher operations not available in OSS mode. "
            "Use FbossSwitchInternal for COOP-based patcher operations."
        )

    async def async_get_ip_route(
        self, ip: str, print_interfaces: bool = True
    ) -> Optional[List[str]]:
        """
        Given a destination IPv[46] address, returns a list of egress interfaces
        according to the route table. Returns None if no route is present.

        OSS-compatible: uses async thrift getRouteTable() instead of deprecated
        addr_tt and sync getIpRouteDetails().
        """
        egress_intfs = []
        async with self.async_agent_client as client:
            routes = await client.getRouteTable()

        target_ip = ip_address(ip)
        matched_route = None
        for route in routes:
            route_ip = self.ip_ntop(route.dest.ip.addr)
            route_network = ip_network(
                f"{route_ip}/{route.dest.prefixLength}", strict=False
            )
            if target_ip in route_network:
                if matched_route is None:
                    matched_route = route
                else:
                    existing_ip = self.ip_ntop(matched_route.dest.ip.addr)
                    existing_network = ip_network(
                        f"{existing_ip}/{matched_route.dest.prefixLength}", strict=False
                    )
                    if route_network.prefixlen > existing_network.prefixlen:
                        matched_route = route

        if not matched_route or not matched_route.nextHops:
            self.logger.info(f"No route found for destination {ip} on {self.hostname}")
            return None

        intf_name_to_id_map: Dict[
            str, InterfaceInfo
        ] = await self.async_get_all_interfaces_info()
        egress_intf_ids = set()
        for nh in matched_route.nextHops:
            if hasattr(nh, "address") and nh.address:
                if hasattr(nh.address, "ifName") and nh.address.ifName:
                    egress_intfs.append(nh.address.ifName)
                    continue
            if hasattr(nh, "interfaceID"):
                # pyre-fixme[16]: `NextHopThrift` has no attribute `interfaceID`.
                egress_intf_ids.add(nh.interfaceID)

        for intf_name, intf_details in intf_name_to_id_map.items():
            if intf_details.vlan_id in egress_intf_ids:
                egress_intfs.append(intf_name)

        if not egress_intfs:
            self.logger.info(
                f"No egress interfaces found in the route table for destination {ip} on {self.hostname}"
            )
            return None

        if print_interfaces:
            self.logger.info(
                f"The following egress interfaces were found in the route table "
                f"on {self.hostname} for destination {ip}: \n {egress_intfs}"
            )

        return egress_intfs

    async def _async_get_interface_name_to_ip_address_mapping(
        self, interface_name: str
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Fetch the IPv4 and IPv6 (global) address for a given interface.

        OSS-compatible: uses async thrift getAllInterfaces() and string parsing
        instead of deprecated addr_tt (facebook.network.Address.ttypes).

        Returns:
            Tuple of (ipv4_address, ipv6_address) as strings. Either may be None.
        """
        port_vlan_id_res: InterfaceInfo = (
            await self.async_get_interface_name_to_port_id_and_vlan_id(interface_name)
        )
        vlan_id: int = port_vlan_id_res.vlan_id

        all_interfaces = await self.async_get_all_interfaces()
        addresses = None
        for interface_detail in all_interfaces.values():
            if interface_detail.vlanId == vlan_id:
                addresses = interface_detail.address
                break

        if not addresses:
            raise EmptyOutputReturnError(
                f"Empty address info returned for VLAN ID {vlan_id} "
                f"corresponding to interface {interface_name}"
            )

        v4_addr, v6_addr = None, None
        for addr in addresses:
            addr_str = str(ipaddress.ip_address(addr.ip.addr))
            if ":" in addr_str:
                if not addr_str.startswith("fe80"):
                    v6_addr = ipaddress.ip_address(addr.ip.addr).compressed
            else:
                v4_addr = addr_str

        if v4_addr is None and v6_addr is None:
            raise InvalidIpAddressError(
                f"Interface {interface_name} does not have IPv4 or IPv6 addresses. "
                f"IPv4: {v4_addr} IPv6: {v6_addr}"
            )

        return (v4_addr, v6_addr)

    @async_retryable(retries=3, sleep_time=10, exceptions=(ThriftError,))
    async def get_specific_interface_info(self, interface: str) -> PortInfoThrift:
        """
        Provides portInfo details for a particular interface on the host.
        OSS-compatible: uses async agent client.
        """
        port_id: int = await self._async_get_port_id_from_interface_name(interface)
        self.logger.debug(
            f"Port ID {port_id} for interface {interface} on {self.hostname}"
        )
        try:
            async with self.async_agent_client as client:
                return await client.getPortInfo(port_id)
        except Exception as ex:
            raise Exception(
                f"Thrift error on {self.hostname} calling getPortInfo: {ex}"
            ) from ex

    @is_dne_test_device
    @async_retryable(retries=2, sleep_time=10, exceptions=(Exception,))
    async def async_crash_service(
        self,
        service: Service,
        agents: Optional[List[str]] = None,
    ) -> None:
        """
        Crash a service by sending SIGKILL.
        OSS-compatible: uses self.async_is_multi_switch() instead of the
        standalone Meta-internal async_is_multi_switch function.
        """
        service_name = service.value
        command = f"pkill -9 {service_name}"

        try:
            is_multi_switch = await self.async_is_multi_switch()
        except NotImplementedError:
            is_multi_switch = False

        if is_multi_switch:
            match service_name:
                case FbossSystemctlServiceName.AGENT.value:
                    command = "pkill -9 -f fboss_"
                case FbossSystemctlServiceName.FBOSS_HW_AGENT_0.value:
                    command = 'pkill -9 -f "fboss_hw_agent .* --switchIndex 0"'
                case FbossSystemctlServiceName.FBOSS_HW_AGENT_1.value:
                    command = 'pkill -9 -f "fboss_hw_agent .* --switchIndex 1"'

        self.logger.info(f"Running {command} on {self.hostname}")
        await self.async_run_cmd_on_shell(command)

    async def _async_get_qsfp_transceiver_id(self, interface_name: str) -> int:
        """
        Used to obtain the QSFP Transceiver ID corresponding to a given
        interface name on a FBOSS device
        """
        port_vlan_id_res: InterfaceInfo = (
            await self.async_get_interface_name_to_port_id_and_vlan_id(interface_name)
        )
        port_id = port_vlan_id_res.port_id
        with self._get_fboss_agent_client() as client:
            port_status: PortStatus = client.getPortStatus([port_id])

        # pyre-fixme[16]: `PortStatus` has no attribute `__getitem__`.
        port_status_obj = port_status[port_id]
        # TODO: The transceiver ID exposed by the wedge_agent service right now
        # under getPortStatus / 'fboss port status' command is 1 lesser than
        # the actual transceiver ID value used by the qsfp_utils service.
        # This needs to be fixed and tracked in T30132285
        transceiver_id: int = (port_status_obj.transceiverIdx.transceiverId) + 1

        # NOTE: Transceiver ID can be even 0. That is why we validate the value
        # to ensure it is NOT NONE
        if transceiver_id is None:
            raise InterfaceNotFoundError(
                f"Unable to obtain the Transceiver_id ID for interface "
                f"{interface_name} on {self.hostname} while attempting "
                f"to change the interface state using qsfp_utils methods"
            )
        return transceiver_id

    async def async_get_all_interfaces_admin_status(self) -> DefaultDict[str, bool]:
        """
        Used to fetch a snapshot of the admin status of all the
        interfaces on the DUT. An interface that is in ENABLED state
        will be marked as True, while it will be marked as False if
        it is DISABLED.
        """
        all_interfaces_status_map: DefaultDict[str, bool] = defaultdict(bool)

        all_ports_info: Dict[int, PortInfoThrift] = await self.async_get_all_port_info()

        for port_info in all_ports_info.values():
            if port_info.adminState == PortAdminState.ENABLED:
                all_interfaces_status_map[port_info.name] = True
            else:
                all_interfaces_status_map[port_info.name] = False

        return all_interfaces_status_map

    async def async_get_all_interfaces_operational_status(
        self,
    ) -> DefaultDict[str, bool]:
        """
        Used to fetch a snapshot of the operational status of all the
        interfaces on the DUT. An active interface that is operationally
        UP will be marked as True, while it will be marked as False if
        it is down.
        """
        all_interfaces_status_map: DefaultDict[str, bool] = defaultdict(bool)
        all_ports_info: Dict[int, PortInfoThrift] = await self.async_get_all_port_info()

        for port_info in all_ports_info.values():
            if port_info.operState == PortOperState.UP:
                all_interfaces_status_map[port_info.name] = True
            else:
                all_interfaces_status_map[port_info.name] = False

        return all_interfaces_status_map

    async def async_get_port_status(self) -> Mapping[int, PortStatus]:
        """
        Used to get the mapping of the port id to its PortStatus information using
        a Thrift api call.
        """
        async with self.async_agent_client as client:
            ports_status_map: Mapping[int, PortStatus] = await client.getPortStatus([])
            return ports_status_map

    async def _get_qsfp_info_map(self) -> Dict[int, transceiver_types.TransceiverInfo]:
        """
        Used to get the mapping of the transceiver id to the ports TransceiverInfo using
        a Thrift api call.
        If the fetch is unsuccessful raises an Exception
        """
        try:
            async with await self.async_get_qsfp_client() as qsfp_client:
                return await qsfp_client.getTransceiverInfo([])
        except Exception as ex:
            raise QsfpThriftException(
                f"Error occured during a thrift call to QSFP service with ex {ex}"
            )

    async def async_get_all_interface_to_qsfp_info_mapping(
        self,
    ) -> Dict[str, transceiver_types.TransceiverInfo]:
        """
        Used to fetch the interface name to transceiver info mapping on
        FBOSS devices for all the interfaces using Thrift API.
        """
        intf_to_transceiver_map: Dict[str, transceiver_types.TransceiverInfo] = {}
        intf_map_result: Dict[
            str, InterfaceInfo
        ] = await self.async_get_all_interfaces_info()

        port_status = await self.async_get_port_status()
        qsfp_info = await self._get_qsfp_info_map()
        for interface_name, port_info in intf_map_result.items():
            # pyre-fixme[16]: `Optional` has no attribute `transceiverId`.
            trans_id = port_status[port_info.port_id].transceiverIdx.transceiverId
            if trans_id in qsfp_info.keys():
                intf_to_transceiver_map[interface_name] = qsfp_info[trans_id]

        return intf_to_transceiver_map

    async def async_find_my_transceiver(self, transceiver_ids: List[str]) -> None:
        intf_to_transceiver = await self.async_get_all_interface_to_qsfp_info_mapping()
        for interface in intf_to_transceiver:
            for xcvr in transceiver_ids:
                if intf_to_transceiver[interface].tcvrState.vendor:
                    if none_throws(
                        intf_to_transceiver[interface].tcvrState.vendor
                    ).partNumber == xcvr.replace("_", "-"):
                        self.logger.info(
                            f"Found {xcvr} in {self.hostname} on interface {interface}"
                        )

    @async_retryable(retries=20, sleep_time=5, exceptions=(Exception,))
    async def async_get_all_qsfp_dom_values(
        self, desired_interfaces: List[str]
    ) -> None:
        """
        Used to verify the QSFP DOM values for all specified
        interfaces on a FBOSS device
        Args:
            desired_interfaces: List of interface names whose DOM values are to be checked
        Raises:
            DomValidationError: When validation fails for any interface
        """
        all_intf_error_messages = []
        int_name_to_trans_map: Dict[
            str, transceiver_types.TransceiverInfo
        ] = await self.async_get_all_interface_to_qsfp_info_mapping()

        for intf_name in desired_interfaces:
            if intf_name in int_name_to_trans_map.keys():
                trans_info = int_name_to_trans_map[intf_name]
                all_intf_error_messages.extend(
                    await self._async_verify_dom_values(trans_info, intf_name)
                )
            else:
                all_intf_error_messages.append(f"No tranceiver for {intf_name}")

        if all_intf_error_messages:
            raise DomValidationError(
                f"Optical DOM validation failed: {all_intf_error_messages}"
            )
        else:
            self.logger.info("DOM validation passed for all interfaces")

    async def _async_verify_dom_values(
        self, transceiver_data: transceiver_types.TransceiverInfo, interface_name: str
    ) -> List[str]:
        """
        Used to verify the QSFP DOM values of an interface on a FBOSS device.
        Returns the list of error messages if the validation fails for any
        of the DOM values
        """
        error_messages = []
        if not transceiver_data.tcvrState.present:
            error_messages.append(
                f"Transceiver status failed on interface {interface_name}"
            )
        else:
            error_messages.extend(
                await self._async_verify_temp_dom_value(
                    transceiver_data, interface_name
                )
            )

            error_messages.extend(
                await self._async_verify_vcc_dom_value(transceiver_data, interface_name)
            )
            for channel in transceiver_data.tcvrStats.channels:
                error_messages.extend(
                    await self._async_verify_Rxpower_dom_value(
                        transceiver_data, channel, interface_name
                    )
                )

                error_messages.extend(
                    await self._async_verify_Txpower_dom_value(
                        transceiver_data, channel, interface_name
                    )
                )

        return error_messages

    async def _async_verify_temp_dom_value(
        self,
        transceiver_data: transceiver_types.TransceiverInfo,
        interface_name: str,
    ) -> List[str]:
        """
        Used to check if the temperature of the optical transceiver for a given
        interface on a FBOSS device is within the threshold.
        Returns an error message if the alarm flag is set for temperature
        """
        intf_error_message = []
        # pyre-fixme[16]: `Optional` has no attribute `temp`.
        temp_flag = transceiver_data.tcvrStats.sensor.temp.flags
        # pyre-fixme[16]: `Optional` has no attribute `temp`.
        temp_threshold = transceiver_data.tcvrState.thresholds.temp
        if temp_flag.warn.high or temp_flag.warn.low:
            await self._async_log_dom_warning(
                "Temperature",
                # pyrefly: ignore [missing-attribute]
                transceiver_data.tcvrStats.sensor.temp.value,
                temp_threshold,
                temp_flag,
                interface_name,
            )
        if temp_flag.alarm.high or temp_flag.alarm.low:
            intf_error_message.append(
                f"Temperature value is out of range for interface {interface_name}"
            )
        return intf_error_message

    async def _async_verify_vcc_dom_value(
        self,
        transceiver_data: transceiver_types.TransceiverInfo,
        interface_name: str,
    ) -> List[str]:
        """
        Used to check if the voltage of the optical transceiver for a given
        interface on a FBOSS device is within the threshold.
        Returns an error message if the alarm flag is set for vcc
        """
        intf_error_message = []
        # pyre-fixme[16]: `Optional` has no attribute `vcc`.
        vcc_flag = transceiver_data.tcvrStats.sensor.vcc.flags
        # pyre-fixme[16]: `Optional` has no attribute `vcc`.
        vcc_threshold = transceiver_data.tcvrState.thresholds.vcc

        if vcc_flag.warn.high or vcc_flag.warn.low:
            await self._async_log_dom_warning(
                "Voltage",
                # pyrefly: ignore [missing-attribute]
                transceiver_data.tcvrStats.sensor.vcc.value,
                vcc_threshold,
                vcc_flag,
                interface_name,
            )
        if vcc_flag.alarm.high or vcc_flag.alarm.low:
            intf_error_message.append(
                f"Vcc value is out of range for interface {interface_name}"
            )
        return intf_error_message

    async def _async_verify_Rxpower_dom_value(
        self,
        transceiver_data: transceiver_types.TransceiverInfo,
        channel: transceiver_types.Channel,
        interface_name: str,
    ) -> List[str]:
        """
        Given the interface name and transceiver channel on the fboss device
        this method is used to check if the receive power of the channel is
        within the threshold.
        Returns an error message if the alarm flag is set for Rxpower
        """
        intf_error_message = []
        chnl_id = channel.channel
        rxpwr_flag = channel.sensors.rxPwr.flags
        # pyre-fixme[16]: `Optional` has no attribute `rxPwr`.
        rxpwr_threshold = transceiver_data.tcvrState.thresholds.rxPwr
        # pyre-fixme[16]: `Optional` has no attribute `warn`.
        if rxpwr_flag.warn.high or rxpwr_flag.warn.low:
            await self._async_log_dom_warning(
                f"Rxpower on channel{chnl_id}",
                channel.sensors.rxPwr.value,
                rxpwr_threshold,
                rxpwr_flag,
                interface_name,
            )
        # pyre-fixme[16]: `Optional` has no attribute `alarm`.
        if rxpwr_flag.alarm.high or rxpwr_flag.alarm.low:
            intf_error_message.append(
                f"Rxpower on channel {chnl_id} is out of range for interface {interface_name}"
            )
        return intf_error_message

    async def _async_verify_Txpower_dom_value(
        self,
        transceiver_data: transceiver_types.TransceiverInfo,
        channel: transceiver_types.Channel,
        interface_name: str,
    ) -> List[str]:
        """
        Given the interface name and transceiver channel on the fboss device
        this method is used to check the transmit power of the channel
        is within the threshold.
        Returns an error message if the alarm flag is set for Txpower
        """
        intf_error_message = []
        chnl_id = channel.channel
        txpwr_flag = channel.sensors.txPwr.flags
        # pyre-fixme[16]: `Optional` has no attribute `txPwr`.
        txpwr_threshold = transceiver_data.tcvrState.thresholds.txPwr

        # pyre-fixme[16]: `Optional` has no attribute `warn`.
        if txpwr_flag.warn.high or txpwr_flag.warn.low:
            await self._async_log_dom_warning(
                f"Txpower on channel{chnl_id}",
                channel.sensors.txPwr.value,
                txpwr_threshold,
                txpwr_flag,
                interface_name,
            )
        # pyre-fixme[16]: `Optional` has no attribute `alarm`.
        if txpwr_flag.alarm.high or txpwr_flag.alarm.low:
            intf_error_message.append(
                f"Txpower on channel {chnl_id} is out of range for interface {interface_name}"
            )
        return intf_error_message

    async def _async_log_dom_warning(
        self, name, actual_val, threshold, flag, interface_name
    ) -> None:
        """
        Used to obtain log warning when DOM values of a port are out of range
        """
        thresh_value_warn, thresh_value_alarm, alarm_type = (
            [threshold.warn.low, threshold.alarm.low, "low"]
            if actual_val < threshold.warn.low
            else [threshold.warn.high, threshold.alarm.high, "high"]
        )
        flag_type = "ALARM" if flag.alarm.high or flag.alarm.low else "WARNING"
        self.logger.warning(
            f"{name} values on {interface_name} exceeds the {alarm_type} {flag_type}"
            f" threshold values.Actual : {actual_val}, {alarm_type} warning threshold "
            f":{thresh_value_warn}, {alarm_type} alarm threshold :{thresh_value_alarm}"
        )

    ##############################
    # FBOSS BGP HELPER FUNCTIONS #
    ##############################
    @async_retryable(
        retries=30,
        sleep_time=2,
        max_duration=60,
        exceptions=(ThriftError,),
    )
    async def count_bgp_ipv6_rib_entries(self) -> int:
        """
        Count number of ipv6 entries in BGP RIB
        """
        async with await self._get_bgp_client() as bgp_client:
            rib_entries = await bgp_client.getRibEntries(TBgpAfi.AFI_IPV6)
        return len(rib_entries)

    async def async_get_bgp_rib_entries(self) -> List[TRibEntry]:
        """
        Returns the rib entries for the given device
        This structure is seen in `fbgf bgp_thrift.thrift` - https://fburl.com/phabricator/0gxnbgz
        """
        rib_entries = []
        async with await self._get_bgp_client() as bgp_client:
            rib_entries.extend(await bgp_client.getRibEntries(TBgpAfi.AFI_IPV6))
            rib_entries.extend(await bgp_client.getRibEntries(TBgpAfi.AFI_IPV4))
        return rib_entries

    @async_retryable(retries=3, sleep_time=1, exceptions=(Exception,))
    async def async_count_established_bgp_sessions(self) -> int:
        """
        Count established BGP sessions.
        """
        bgp_sessions = await self.async_get_bgp_sessions()
        established_bgp_sessions = [
            session.peer
            for session in bgp_sessions
            if session.peer.peer_state == TBgpPeerState.ESTABLISHED
        ]
        return len(established_bgp_sessions)

    @async_retryable(
        retries=3,
        sleep_time=1,
        exceptions=(ThriftError,),
    )
    async def get_bgp_sessions_count(self) -> int:
        """
        Get BGP session count
        """
        async with await self._get_bgp_client() as client:
            bgp_sessions = await client.getBgpSessions()
        session_length = len(bgp_sessions)
        self.logger.info(f"BGP session length: {session_length}")
        return session_length

    @async_retryable(
        retries=3,
        sleep_time=1,
        exceptions=(ThriftError,),
    )
    async def shutdown_all_bgp_sessions(self) -> bool:
        """
        Shutdown all BGP sessions.
        """
        async with await self._get_bgp_client() as client:
            bgp_sessions = await client.getBgpSessions()
            for session in bgp_sessions:
                await client.shutdownSession(peer=session.peer_addr)
            return (
                True
                if await self.async_count_established_bgp_sessions() == 0
                else False
            )

    async def start_all_bgp_sessions(self) -> bool:
        """
        Start all BGP sessions.
        """
        async with await self._get_bgp_client() as client:
            bgp_sessions = await client.getBgpSessions()
            for session in bgp_sessions:
                await client.startSession(peer=session.peer_addr)
            time.sleep(1)
            return (
                True
                if await self.async_count_established_bgp_sessions() != 0
                else False
            )

    async def async_get_all_interface_ip_addresses(
        self,
    ) -> Dict[str, List[Union[IPv4Interface, IPv6Interface]]]:
        """Return a list of ip addresses assigned to every interface in the
           fboss switch

        Returns:
            Dict[str, List[Union[IPv4Interface, IPv6Interface]]]:
            eg: {"eth1/1/1:[
                        IPv4Interface(1.1.1.1/32,
                        IPv6Interface(2401:db00:e2::1/127),
                    ]
                }
        """
        interface_vlan_map = {}
        interface_address_map = defaultdict(list)
        try:
            ports = await self.async_get_all_port_info()
            if not ports:
                raise ValueError("No ports found")
            vlan_to_interface_detail = await self.async_get_all_interfaces()
        except (FbossBaseError, ValueError) as ex:
            self.logger.debug(
                f"Unable to fetch port details for device {self.hostname} excpetion {str(ex)}"
            )
            return {}

        for port in ports.values():
            interface_name: str = port.name
            vlan_id = int(port.vlans[0]) if port.vlans else None
            interface_vlan_map[interface_name] = vlan_id

        for interface, vlan_id in interface_vlan_map.items():
            # pyrefly: ignore [bad-argument-type]
            intf_detail = vlan_to_interface_detail.get(vlan_id)
            if not intf_detail:
                self.logger.debug(
                    f"Interface detail does not exist for {self.hostname} vlan {vlan_id}"
                )
                continue

            for address in intf_detail.address:
                ip_addr_obj = ipaddress.ip_address(address.ip.addr)
                if isinstance(ip_addr_obj, ipaddress.IPv4Address):
                    v4_addr = str(ip_addr_obj)
                    v4_mask = str(address.prefixLength)
                    v4_addr_mask = ipaddress.IPv4Interface(f"{v4_addr}/{v4_mask}")
                    interface_address_map[interface].append(v4_addr_mask)
                elif (
                    isinstance(ip_addr_obj, ipaddress.IPv6Address)
                    and ip_addr_obj.is_global
                ):
                    v6_addr = str(ip_addr_obj)
                    v6_mask = str(address.prefixLength)
                    v6_addr_mask = ipaddress.IPv6Interface(f"{v6_addr}/{v6_mask}")
                    interface_address_map[interface].append(v6_addr_mask)

        return interface_address_map

    async def _get_remote_bgp_peer_addresses(
        self, interface_name: str
    ) -> List[Union[ipaddress.IPv4Address, ipaddress.IPv6Address]]:
        """
        Used to obtain the v4 and v6 IP addresses of the remote side BGP
        peer given a local interface name.
        Output:
            peer_ip_addresses = [
                IPv4Address(<v4_address>),
                IPv6Address(<v6_address>),
            ]
        """
        peer_ip_addresses = []
        intf_addr_map = await self.async_get_all_interface_ip_addresses()
        desired_intf_details = intf_addr_map[interface_name]
        bgp_v4_local_ip, bgp_v6_local_ip = None, None
        if desired_intf_details:
            for ip_addr in desired_intf_details:
                if isinstance(ip_addr, ipaddress.IPv4Interface):
                    bgp_v4_local_ip = str(ip_addr.ip)
                elif isinstance(ip_addr, ipaddress.IPv6Interface):
                    bgp_v6_local_ip = str(ip_addr.ip)

        if all(addr is None for addr in [bgp_v4_local_ip, bgp_v6_local_ip]):
            raise InvalidIpAddressError(
                f"Looks like Interface {interface_name} does not have both IPv4 "
                f"and IPv6 addresses. IPv4: {bgp_v4_local_ip} IPv6: {bgp_v6_local_ip} Please check!"
            )

        all_bgp_sessions = await self.async_get_bgp_sessions()

        for session in all_bgp_sessions:
            if bgp_v4_local_ip and re.match(rf"^{bgp_v4_local_ip}$", session.my_addr):
                ip_address = ipaddress.IPv4Address(str(session.peer_addr))
                peer_ip_addresses.append(ip_address)
            elif bgp_v6_local_ip and re.match(rf"^{bgp_v6_local_ip}$", session.my_addr):
                ip_address = ipaddress.IPv6Address(str(session.peer_addr))
                # pyrefly: ignore [bad-argument-type]
                peer_ip_addresses.append(ip_address)

        if not any(
            [isinstance(peer, ipaddress.IPv6Address) for peer in peer_ip_addresses]
        ):
            raise BgpPeerNotFoundError(
                f"Something went wrong while attempting to get v6"
                f"BGP peer IP addresses on interface {interface_name}. "
                f"Please investigate! peer_ip_addresses: {peer_ip_addresses}"
            )

        # pyrefly: ignore [bad-return]
        return peer_ip_addresses

    async def _async_get_formatted_bgp_neighbor_table_output(
        self, bgp_session_raw_output: List[TBgpSession]
    ) -> List[List[Union[str, int]]]:
        """
        Used to convert the raw BGP neighbor table output from FBOSS Thrift
        API to a nested list that can be further used by tabulate library for
        printing the output in tabular format
        """
        bgp_session_fmt_output: List = []
        for session in bgp_session_raw_output:
            peer_state: str = session.peer.peer_state.name
            uptime_str = str(datetime.timedelta(milliseconds=session.uptime))
            uptime: str = uptime_str.split(".")[0]
            # List[str, str, int, int, str, str, str]
            row_data = [
                str(session.peer_addr),
                str(session.my_addr),
                session.peer.local_as,
                session.peer.remote_as,
                str(peer_state),
                uptime,
                session.description,
                session.prepolicy_rcvd_prefix_count,
                session.postpolicy_sent_prefix_count,
            ]
            bgp_session_fmt_output.append(row_data)
        return bgp_session_fmt_output

    async def _async_print_bgp_neighbor_table_output(
        self, bgp_session_raw_output: List[TBgpSession], title: str = ""
    ) -> None:
        """
        Print the output originally obtained from Thrift APIs in the form of
        nested lists. This will be similar to the CLI output of 'fboss bgp neighbor'

        Sample output: P59125674
        """
        bgp_session_fmt_output: List[
            List[Union[str, int]]
        ] = await self._async_get_formatted_bgp_neighbor_table_output(
            bgp_session_raw_output
        )

        tabulated_bgp_output = get_tabulated_output(
            bgp_session_fmt_output, header_fields=BGP_SUMMARY_HEADER, title=title
        )

        self.logger.info(f"{tabulated_bgp_output}")

    async def _get_bgp_client(self) -> TBgpService:
        raise NotImplementedError(
            "BGP client not available in OSS mode. "
            "Use FbossSwitchInternal for ServiceRouter-based connection."
        )

    @async_retryable(
        retries=30,
        sleep_time=2,
        exceptions=(Exception,),
    )
    async def async_get_bgp_sessions(self) -> Sequence[TBgpSession]:
        async with await self._get_bgp_client() as bgp_client:
            return await bgp_client.getBgpSessions()

    @async_retryable(
        retries=30,
        sleep_time=2,
        exceptions=(Exception,),
    )
    async def async_get_postfilter_received_networks(
        self, peer: str
    ) -> t.Mapping[TIpPrefix, TBgpPath]:
        """
        Get postfilter received networks for a peer.

        Args:
            peer: IP address of the BGP peer

        Returns:
            Mapping of prefixes to paths received from the peer after policy
        """
        async with await self._get_bgp_client() as bgp_client:
            return await bgp_client.getPostfilterReceivedNetworks(peer)

    @async_retryable(
        retries=30,
        sleep_time=2,
        exceptions=(Exception,),
    )
    async def async_get_postfilter_advertised_networks(
        self, peer: str
    ) -> t.Mapping[TIpPrefix, TBgpPath]:
        """
        Get postfilter advertised networks for a peer.

        Args:
            peer: IP address of the BGP peer

        Returns:
            Mapping of prefixes to paths advertised to the peer after policy
        """
        async with await self._get_bgp_client() as bgp_client:
            return await bgp_client.getPostfilterAdvertisedNetworks(peer)

    async def _async_modify_bgp_nbr(
        self,
        peer_ip_addr: Union[ipaddress.IPv4Address, ipaddress.IPv6Address],
        bgp_peer_action: BgpPeerAction,
    ) -> None:
        """
        Uses the non blocking thrift BGP client to modify the BGP state of the
        peer address in the interface
        """
        async with await self._get_bgp_client() as bgp_client:
            if bgp_peer_action == BgpPeerAction.ENABLE:
                await bgp_client.startSession(str(peer_ip_addr))
            elif bgp_peer_action == BgpPeerAction.RESTART:
                await bgp_client.restartSession(str(peer_ip_addr))
            elif bgp_peer_action == BgpPeerAction.SHUT:
                await bgp_client.shutdownSession(str(peer_ip_addr))

    async def async_get_specific_bgp_session_state(
        self,
        interface_name: str,
    ) -> Dict[str, int]:
        """
        Used to obtain the number of established and non-established BGP
        v4 and v6 sessions on a given interface that is used to peer with
        the neighbor.

        There is an optional desc_regex field that can be used to further
        validate if the expected BGP sessions are fetched by the Thrift APIs.
        """
        return await self._async_get_specific_bgp_session_state(
            interface_name,
            await_sync(self.async_get_bgp_sessions()),
        )

    async def async_get_multiple_intfs_bgp_session_state(
        self,
        interface_names: List[str],
    ) -> Dict[str, Dict[str, int]]:
        """
        For the given list of interfaces, we parse the BGP session stats to map each interface
        to their count of current BGP state using the async BGP client
        Args:
            interface_names(List[str]): List of interface names whose BGP sess counts are needed

        Returns:
            Dictionary which maps the list of interfaces with their corresponding count
                of established and non-established BGP v4 and v6 sessions
        """

        interface_bgp_session_state_map: Dict[str, Dict[str, int]] = {}
        all_bgp_sessions = await self.async_get_bgp_sessions()
        for interface_name in interface_names:
            interface_bgp_session_state_map[
                interface_name
            ] = await self._async_get_specific_bgp_session_state(
                interface_name, all_bgp_sessions
            )
        log_message: List[str] = []
        for (
            interface_name,
            session_state_map,
        ) in interface_bgp_session_state_map.items():
            log_message.append(
                f"There is a total of {session_state_map['estab_peers']} established and "
                f"{session_state_map['non_estab_peers']} non-established BGP sessions on "
                f"interface {interface_name}"
            )
        # create a FBURL for long log messages
        joined_logs = "\n".join(log_message)
        if len(log_message) > 10:
            self.logger.info(
                f"BGP session info of {self.hostname}: {create_everpaste_fburl(joined_logs)}"
            )
        else:
            self.logger.info(joined_logs)

        return interface_bgp_session_state_map

    async def async_create_cold_boot_file(self) -> None:
        cmd: str = "touch /dev/shm/fboss/warm_boot/cold_boot_once_0 && "
        await self.async_run_cmd_on_shell(cmd)

    async def _async_get_port_id_from_interface_name(self, interface_name: str) -> int:
        """
        Used to obtain the port id number of an interface, given the
        interface name
        """
        intf_map_result: Dict[
            str, InterfaceInfo
        ] = await self.async_get_all_interfaces_info()
        if interface_name not in intf_map_result:
            raise InterfaceNotFoundError(
                f"{interface_name} was not found"
                f" Please ensure if correct interface name is used."
            )

        return intf_map_result[interface_name].port_id

    async def async_get_intf_to_bgp_rx_prefix_count_map(self) -> Dict[str, int]:
        """Get the number of received bgp prefix count per interface.

        Returns:
            Dict[str, int]: interface name maps to received bgp prefix count
        """
        all_bgp_sessions: Sequence[TBgpSession] = await self.async_get_bgp_sessions()
        intf_addr_map = await self.async_get_all_interface_ip_addresses()

        intf_name_to_local_v4_ip_map: Dict[str, str] = {}
        intf_name_to_local_v6_ip_map: Dict[str, str] = {}
        for intf_name, intf_details in intf_addr_map.items():
            for ip_addr in intf_details:
                if isinstance(ip_addr, ipaddress.IPv4Interface):
                    intf_name_to_local_v4_ip_map[intf_name] = str(ip_addr.ip)
                elif isinstance(ip_addr, ipaddress.IPv6Interface):
                    intf_name_to_local_v6_ip_map[intf_name] = str(ip_addr.ip)

        intf_name_to_prefix_count_map: Dict[str, int] = {
            intf_name: 0 for intf_name in intf_addr_map.keys()
        }
        for session in all_bgp_sessions:
            for intf_name in intf_name_to_prefix_count_map.keys():
                local_v4_ip = intf_name_to_local_v4_ip_map.get(intf_name, "")
                local_v6_ip = intf_name_to_local_v6_ip_map.get(intf_name, "")
                if session.my_addr == local_v4_ip or session.my_addr == local_v6_ip:
                    intf_name_to_prefix_count_map[intf_name] += (
                        session.prepolicy_rcvd_prefix_count
                    )
                    break
        return intf_name_to_prefix_count_map

    async def async_get_bgp_rx_prefix_count_per_intf(self, interface_name: str) -> int:
        intf_name_to_prefix_count_map: Dict[
            str, int
        ] = await self.async_get_intf_to_bgp_rx_prefix_count_map()

        prefix_count = intf_name_to_prefix_count_map.get(interface_name, None)
        if prefix_count is None:
            raise InvalidIpAddressError(
                f"Looks like Interface {interface_name} does not have both IPv4 "
                "and IPv6 addresses. Please check!"
            )
        return prefix_count

    @async_retryable(retries=10, sleep_time=10, exceptions=(ThriftError,))
    async def async_get_multiple_sess_bgp_uptime(
        self,
    ) -> Dict[str, float]:
        """
        Used to obtain the uptime for all the established
        BGP v4 and v6 sessions across all the interfaces that are up and
        running on the fboss device.
        """
        bgp_session_uptime_map: Dict[str, float] = {}
        all_bgp_sessions = await self.async_get_bgp_sessions()
        for session in all_bgp_sessions:
            bgp_state = session.peer.peer_state
            uptime = float(session.uptime)
            if bgp_state == TBgpPeerState.ESTABLISHED:
                bgp_session_uptime_map[f"{session.my_addr}_{session.peer_addr}"] = (
                    uptime
                )
        return bgp_session_uptime_map

    # pyrefly: ignore [bad-override]
    async def stress_system_memory_cmd(
        self, n_workers: str, bytes_per_worker: str, timeout: str = "60s"
    ):
        """
        This method stressess the system memory for the given timeout period by spawing n_workers
        and allocating bytes_per_worker. The output of the command is directed
        to /dev/null. So no output is expected. To verify if the execution was successful
        run get_stress_mem_util method which returns the system memory utilization.
        """

        self.logger.info("Executing the memory stress command")
        stress_cmd: str = f"stress --vm {n_workers} --vm-bytes {bytes_per_worker} --vm-keep --timeout {timeout}> /dev/null 2>&1 &\n\n\n"

        return await self.async_run_cmd_on_shell(stress_cmd)

    async def execute_pgrep_cmd(self, process: str) -> str:
        """
        Executes pgrep command for the given process name. Returns the command output if successful
        else returns EmptyOutputReturnError exception.
        """
        pgrep_cmd = f"pgrep {process}"
        cmd_output = await self.async_run_cmd_on_shell(pgrep_cmd)
        if not cmd_output:
            raise EmptyOutputReturnError(
                f"Something went wrong while attempting to get the "
                f"PID using command: {pgrep_cmd} "
            )

        return cmd_output

    async def get_service_main_pid(self, service: str) -> str:
        """
        Gets the main PID of a systemctl service using systemctl show command.
        Returns the PID if successful, else raises EmptyOutputReturnError exception.

        Args:
            service: The service name (e.g., "wedge_agent", "bgpd", "coop")

        Returns:
            str: The main PID of the service

        Raises:
            EmptyOutputReturnError: If the command fails or returns empty output
        """
        systemctl_cmd = f"systemctl show {service} -p MainPID | awk -F= '{{print $2}}'"
        cmd_output = await self.async_run_cmd_on_shell(systemctl_cmd)

        if not cmd_output or not cmd_output.strip():
            raise EmptyOutputReturnError(
                f"Something went wrong while attempting to get the "
                f"main PID for service '{service}' using command: {systemctl_cmd}"
            )

        # Strip whitespace and return the PID
        pid = cmd_output.strip()

        # Validate that we got a numeric PID (not "0" which indicates no main process)
        if pid == "0":
            raise EmptyOutputReturnError(
                f"Service '{service}' has no main process (MainPID=0)"
            )

        return pid

    async def get_stress_process_pids(self, process: str) -> List[str]:
        """
        Returns the process ids of the stress process.
        If the stress pid could not be fetched EmptyOutputReturnError is returned
        """
        cmd_output = await self.execute_pgrep_cmd(process=process)

        pids = cmd_output.strip().split("\n")

        return pids

    async def get_stress_mem_util(self, process_id: str) -> int:
        """
        Executes pmap command to get the memory utilization of the given process.
        If successful returns the total memory usage in kbytes else
        throws EmptyOutputReturnError exception.
        """

        mem_util_cmd = f"pmap {process_id} | grep total"
        mem_util_out = await self.async_run_cmd_on_shell(mem_util_cmd)

        if not mem_util_out:
            raise EmptyOutputReturnError(
                f"Something went wrong while attempting to get the "
                f"stress memory utilization using command: {mem_util_cmd} "
            )

        # pmap {process_id} | grep total returns output in the format
        # total     4202284K
        mem_util = mem_util_out.split()[-1]
        result = re.search(r"(\d+)", mem_util)
        return int(result.group(1)) if result else 0

    async def _async_get_specific_bgp_session_state(
        self,
        interface_name: str,
        all_bgp_sessions: Sequence[TBgpSession],
    ) -> Dict[str, int]:
        intf_addr_map = await self.async_get_all_interface_ip_addresses()
        desired_intf_details = intf_addr_map[interface_name]
        local_v4_ip, local_v6_ip = None, None
        if desired_intf_details:
            for ip_addr in desired_intf_details:
                if isinstance(ip_addr, ipaddress.IPv4Interface):
                    local_v4_ip = str(ip_addr.ip)
                elif isinstance(ip_addr, ipaddress.IPv6Interface):
                    local_v6_ip = str(ip_addr.ip)

        if all(addr is None for addr in [local_v4_ip, local_v6_ip]):
            raise InvalidIpAddressError(
                f"Looks like Interface {interface_name} does not have both IPv4 "
                f"and IPv6 addresses. IPv4: {local_v4_ip} IPv6: {local_v6_ip} Please check!"
            )

        spec_estab_sess: List[TBgpSession] = []
        spec_non_estab_sess: List[TBgpSession] = []
        spec_bgp_neigh_state: Dict[str, int] = {}

        for session in all_bgp_sessions:
            if session.my_addr == str(local_v4_ip) or session.my_addr == str(
                local_v6_ip
            ):
                bgp_state = session.peer.peer_state
                if bgp_state == TBgpPeerState.ESTABLISHED:
                    spec_estab_sess.append(session)
                else:
                    spec_non_estab_sess.append(session)

        if not spec_estab_sess and not spec_non_estab_sess:
            raise EmptyOutputReturnError(
                f"There are no BGP sessions on interface {interface_name} for "
                f"MyIP: {local_v4_ip} and {local_v6_ip}"
            )
        await self._async_print_bgp_neighbor_table_output(
            bgp_session_raw_output=spec_estab_sess + spec_non_estab_sess,
            title=f"BGP session info for {self.hostname}:{interface_name}",
        )
        spec_bgp_neigh_state["estab_peers"] = len(spec_estab_sess)
        spec_bgp_neigh_state["non_estab_peers"] = len(spec_non_estab_sess)
        return spec_bgp_neigh_state

    async def get_all_bgp_session_states(self) -> DefaultDict[str, int]:
        """
        Used to obtain the number of all the established and non-established
        BGP v4 and v6 sessions across all the interfaces that are up and
        running on the whole device
        """

        all_bgp_neigh_state: DefaultDict[str, int] = defaultdict(int)

        all_bgp_sessions = await self.async_get_bgp_sessions()
        if not all_bgp_sessions:
            raise EmptyOutputReturnError(
                f"{self.hostname} does not have any BGP sessions configured on it!"
            )

        for session in all_bgp_sessions:
            # NOTE: As per the addressing convention, if the local AS and remote
            # AS are same, then they are dynamic BGP peers and we ignore such
            # peers for the purpose of testing
            if session.peer.local_as != session.peer.remote_as:
                bgp_state = session.peer.peer_state
                if bgp_state == TBgpPeerState.ESTABLISHED:
                    all_bgp_neigh_state["estab_peers"] += 1
                else:
                    all_bgp_neigh_state["non_estab_peers"] += 1

        self.logger.info(
            f"There is a total of {all_bgp_neigh_state['estab_peers']} "
            f"established and {all_bgp_neigh_state['non_estab_peers']} "
            f"non-established BGP sessions across all interfaces on the device"
        )

        return all_bgp_neigh_state

    async def get_all_bgp_session_state_count(self) -> DefaultDict[str, int]:
        """
        Used to obtain the number of all the established and non-established
        BGP v4 and v6 sessions including multi-hop that are up and
        running on the whole device
        """

        all_bgp_neigh_state: DefaultDict[str, int] = defaultdict(int)

        all_bgp_sessions = await self.async_get_bgp_sessions()
        if not all_bgp_sessions:
            raise EmptyOutputReturnError(
                f"{self.hostname} does not have any BGP sessions configured on it!"
            )

        for session in all_bgp_sessions:
            bgp_state = session.peer.peer_state
            if bgp_state == TBgpPeerState.ESTABLISHED:
                all_bgp_neigh_state["estab_peers"] += 1
            else:
                all_bgp_neigh_state["non_estab_peers"] += 1

        self.logger.info(
            f"There is a total of {all_bgp_neigh_state['estab_peers']} "
            f"established and {all_bgp_neigh_state['non_estab_peers']} "
            f"non-established BGP sessions across all interfaces on the device"
        )

        return all_bgp_neigh_state

    async def async_get_all_bgp_peer_ip_addresses(self) -> DefaultDict[str, List[str]]:
        """Used to obtain the peer ip address of all the established as well as
        non-established BGP (both v4 and v6 sessions) across all the
        interfaces that are up and running on a given device.

        Raises:
            EmptyOutputReturnError: exception is raised when no bgp sessions are found

        Returns:
            DefaultDict[str, List[str]]: list of ip addresses for established
                or non-established bgp seesions
        """
        all_bgp_session_ips: DefaultDict[str, List[str]] = defaultdict(list)

        all_bgp_sessions = await self.async_get_bgp_sessions()
        if not all_bgp_sessions:
            raise EmptyOutputReturnError(
                f"{self.hostname} does not have any BGP sessions configured on it!"
            )
        for session in all_bgp_sessions:
            bgp_state = session.peer.peer_state
            if bgp_state == TBgpPeerState.ESTABLISHED:
                all_bgp_session_ips["estab_peers"].append(session.peer_addr)
            else:
                all_bgp_session_ips["non_estab_peers"].append(session.peer_addr)

        self.logger.info(
            "Get all the bgp peer ip addresses: "
            f"estab_peers: {all_bgp_session_ips['estab_peers']}. "
            f"non_estab_peers: {all_bgp_session_ips['non_estab_peers']}. "
        )

        return all_bgp_session_ips

    async def get_ingress_traffic_stats(
        self, ingress_interfaces: List[str]
    ) -> Dict[str, int]:
        """
        Calculate the ingress traffic rate over 1 minute load interval for
        all the given interfaces. The output is returned as a dictionary
        wherein each interface is mapped to their ingress traffic rates.
        Note: rate in bps over 1 minute load interval

        Input:
            ingress_interfaces = [ingress_interface_1, ingress_interface_2, ...]

        Output:
            ingress_tr_stats = {
                <ingress_interface_1>: <in_bits.rate.60_value>,
                <ingress_interface_2>: <in_bits.rate.60_value>,
            },
        """
        ingress_interface_keys = list(
            map(
                lambda interface: INGRESS_RATE_KEY.format(interface), ingress_interfaces
            )
        )
        ingress_stats_bytes = await self.async_get_selected_counters(
            ingress_interface_keys
        )
        return {
            keys: int(bytes_speed * 8)
            for keys, bytes_speed in ingress_stats_bytes.items()
        }

    async def get_egress_traffic_stats(
        self, egress_interfaces: List[str]
    ) -> Dict[str, int]:
        """
        Calculate the egress traffic rate over 1 minute load interval for
        all the given interfaces. The output is returned as a dictionary
        wherein each interface is mapped to their egress traffic rates.
        Note: rate in bps over 1 minute load interval

        Input:
            egress_interfaces = [egress_interface_1, egress_interface_2, ...]

        Output:
            egress_tr_stats = {
                <egress_interface_1>: <out_bits.rate.60_value>,
                <egress_interface_2>: <out_bits.rate.60_value>,
            },
        """
        egress_interface_keys = list(
            map(lambda interface: EGRESS_RATE_KEY.format(interface), egress_interfaces)
        )
        egress_stats_bytes = await self.async_get_selected_counters(
            egress_interface_keys
        )
        return {
            keys.split(".")[0]: int(bytes_speed * 8)
            for keys, bytes_speed in egress_stats_bytes.items()
        }

    def _bounce_specific_interface_using_port_enable_command(
        self, interface_name: str, enable: bool
    ) -> bool:
        """
        Used to shut or unshut any given interface (eth402/4/1) using the
        FBOSS Thrift API. This is equivalent to executing command
        "fboss port enable <port_id>" on the FBOSS CLI.

        Interface will be SHUT if enable is False. Else, interface will be
        UNSHUT. True will be returned.
        """
        port_vlan_id_res: InterfaceInfo = asyncio.run(
            self.async_get_interface_name_to_port_id_and_vlan_id(interface_name)
        )
        port_id = port_vlan_id_res.port_id
        with self._get_fboss_agent_client() as client:
            client.setPortState(port_id, enable)
        return True

    async def async_thrift_disable_enable(
        self,
        interface_names: Tuple[str],
        interval_between_disable_enable_s: int = 2,
        total_flaps: int = 10,
    ) -> None:
        for iteration in range(total_flaps):
            self.logger.info(f"Flap {iteration=}")
            disable = False
            async with self.async_agent_client as client:
                port_info_result = await client.getAllPortInfo()
                for interface_name in interface_names:
                    for port_info in port_info_result.values():
                        if interface_name == port_info.name:
                            await client.setPortState(port_info.portId, disable)
                            self.logger.info(
                                f"Disabling port {self.hostname}:{interface_name}"
                            )
            self.logger.info(
                f"Sleeping {interval_between_disable_enable_s}s after disabling {(', '.join(interface_names))}"
            )
            await asyncio.sleep(interval_between_disable_enable_s)

            async with self.async_agent_client as client:
                port_info_result = await client.getAllPortInfo()
                for interface_name in interface_names:
                    for port_info in port_info_result.values():
                        if interface_name == port_info.name:
                            await client.setPortState(port_info.portId, not disable)
                            self.logger.info(
                                f"Enabling port {self.hostname}:{interface_name}"
                            )
            self.logger.info("Disabled and enabled all the ports once")
            await asyncio.sleep(interval_between_disable_enable_s)

    async def async_thrift_disable_enable_interfaces(
        self,
        interface_names: List[str],
        is_enable_port: bool,
    ) -> None:
        async with self.async_agent_client as client:
            port_info_result = await client.getAllPortInfo()
            for interface_name in interface_names:
                for port_info in port_info_result.values():
                    if interface_name == port_info.name:
                        await client.setPortState(port_info.portId, is_enable_port)
                        state = "Disabling" if not is_enable_port else "Enabling"
                        self.logger.info(
                            f"{state} port {self.hostname}:{interface_name}"
                        )

    async def get_sw_agent_client(self):
        raise NotImplementedError(
            "SW Agent client not available in OSS mode. "
            "Use FbossSwitchInternal for ServiceRouter-based connection."
        )

    async def get_hw_agent_port(self, interface: str) -> int:
        """
        There could be more than one HW agent running in the device, in order to talk
        to it, we need to figure out which instance is managing the given interface.
        To do that we query SW Agent to find the switch index (aka NPU) that the interface
        connects to, and from there we derive the HW Agent port.
        """
        async with await self.get_sw_agent_client() as fboss:
            result = await fboss.getSwitchIndicesForInterfaces([interface])

        thrift_port: int | None = None
        for switch_index, interface_list in result.items():
            if interface in interface_list:
                thrift_port = HW_AGENT_BASE_PORT + switch_index
                break

        if thrift_port is None:
            raise ValueError("Could not find hw agent port")

        return thrift_port

    async def get_hw_agent_client(
        self, interface: Optional[str] = None, switch_index: Optional[int] = None
    ) -> FbossHwCtrl:
        raise NotImplementedError(
            "HW Agent client not available in OSS mode. "
            "Use FbossSwitchInternal for ServiceRouter-based connection."
        )

    @asynccontextmanager
    async def _get_hw_agent_client(
        self, switch_index: int
    ) -> AsyncGenerator[FbossHwCtrl, None]:
        raise NotImplementedError(
            "HW Agent client not available in OSS mode. "
            "Use FbossSwitchInternal for ServiceRouter-based connection."
        )
        yield  # unreachable, needed to make this a generator

    async def async_clear_prbs_stats(self, interface: str) -> None:
        self.logger.info(f"Clearing PRBS stats for {interface}")
        async with await self.get_hw_agent_client(interface) as hw_agent:
            await hw_agent.clearInterfacePrbsStats(interface, PortComponent.ASIC)

    # @async_retryable(retries=10, sleep_time=1, exceptions=(ThriftError,))
    async def get_sai_hw_objects(
        self,
    ) -> str:
        hw_object_type_list = [
            HwObjectType.NEXT_HOP,
            HwObjectType.NEXT_HOP_GROUP,
            HwObjectType.ROUTE_ENTRY,
        ]
        if await self.async_is_mnpu():
            async with self._get_hw_agent_client(0) as client:
                hw_objects = await client.listHwObjects(
                    hw_object_type_list, cached=False
                )
                self.logger.info(f"hw_object info generated for {self.hostname}")
            return hw_objects
        else:
            async with self.async_agent_client as client:
                hw_objects = await client.listHwObjects(
                    hw_object_type_list, cached=False
                )
                self.logger.info(f"hw_object info generated for {self.hostname}")
            return hw_objects

    @retryable(num_tries=30, sleep_time=10, debug=True)
    def _bounce_specific_interface_using_wedge_qsfp_util(
        self,
        interface_name: str,
        enable: bool,
        flap_method: InterfaceFlapMethod,
    ) -> bool:
        """
        Used to shut or unshut any given interface (eth1/1/1) using the
        wedge_qsfp_util tool -tx_disable/-tx_enable or
        wedge_qsfp_util tool -set_low_power/-clear_low_power

        Equivalent to executing the following command:
        wedge_qsfp_util (--tx_disable | --tx_enable) <transceiver_id>

        Interface will be eventually activated by qsfp_service if it is
        running

        Args:
            interface_name: eth1/1/1
            enable: enable interface if True. Disable if False
            flap_methos: One of FBOSS_WEDGE_QSFP_UTIL_POWER or FBOSS_WEDGE_QSFP_UTIL_TX
        Raises:
            CommandExecutionError: if the action is unsuccessful
        Returns:
            True if successful
        """
        FLAP_COMMAND: Dict[InterfaceFlapMethod, Dict[bool, str]] = {
            InterfaceFlapMethod.FBOSS_WEDGE_QSFP_UTIL_POWER: {
                True: "-clear_low_power",
                False: "-set_low_power",
            },
            InterfaceFlapMethod.FBOSS_WEDGE_QSFP_UTIL_TX: {
                True: "-tx_enable",
                False: "-tx_disable",
            },
        }
        EXPECTED_OUTPUT = {
            InterfaceFlapMethod.FBOSS_WEDGE_QSFP_UTIL_POWER: "low power flags",
            InterfaceFlapMethod.FBOSS_WEDGE_QSFP_UTIL_TX: "TX on all channels",
        }

        action_cmd = FLAP_COMMAND[flap_method][enable]

        qsfp_command = f"wedge_qsfp_util {action_cmd} {interface_name}"

        result = asyncio.run(self.async_run_cmd_on_shell(qsfp_command))

        if not result or EXPECTED_OUTPUT[flap_method] not in result:
            raise CommandExecutionError(
                f"wedge_qsfp_util execution failed with result: {result}"
            )
        return True

    async def async_do_rapid_interface_flaps(
        self, interface_names: Tuple[str], interval_to_link_up: int, total_flaps: int
    ) -> None:
        for _ in range(total_flaps):
            interface_names_str = " ".join(interface_names)
            flap_command = f"wedge_qsfp_util -tx_disable {interface_names_str} && sleep 0.1 && wedge_qsfp_util -tx_enable {interface_names_str}"
            await self.async_run_cmd_on_shell(flap_command)
            await asyncio.sleep(interval_to_link_up)
            self.logger.info("Flap command executed")

    def _bounce_specific_interface_using_wedge_qsfp_util_tx(
        self, interface_name: str, enable: bool
    ) -> bool:
        """
        Used to shut or unshut any given interface (eth1/1/1) using the
        wedge_qsfp_util tool -tx_disable/-tx_enable

        Equivalent to executing the following command:
        wedge_qsfp_util (--tx_disable | --tx_enable) <transceiver_id>
        -platform <platform_type>

        Interface will be eventually activated by qsfp_service if it is
        running

        Args:
            interface_name: eth1/1/1
            enable: enable interface if True. Disable if False
        Raises:
            CommandExecutionError: if the action is unsuccessful
        Returns:
            True if successful
        """
        return self._bounce_specific_interface_using_wedge_qsfp_util(
            interface_name, enable, InterfaceFlapMethod.FBOSS_WEDGE_QSFP_UTIL_TX
        )

    def _bounce_specific_interface_using_wedge_qsfp_util_low_power(
        self, interface_name: str, enable: bool
    ) -> bool:
        """
        Used to shut or unshut any given interface (eth1/1/1) using the
        wedge_qsfp_util tool -set_low_power/-clear_low_power

        Equivalent to executing the following command:
        wedge_qsfp_util (-set_low_power | -clear_low_power) <transceiver_id>
        -platform <platform_type>

        Interface will be eventually activated by qsfp_service if it is
        running

        Args:
            interface_name: eth1/1/1
            enable: enable interface if True. Disable if False
        Raises:
            CommandExecutionError: if the action is unsuccessful
        Returns:
            True if successful
        """
        return self._bounce_specific_interface_using_wedge_qsfp_util(
            interface_name, enable, InterfaceFlapMethod.FBOSS_WEDGE_QSFP_UTIL_POWER
        )

    async def get_agents_uptime(
        self, services: Optional[List[str]] = None
    ) -> Dict[str, int]:
        """
        Used to get the uptime (in seconds) for all the agents on a given
        FBOSS device and output is returned as a dictionary.
        Output:
            {
                'bgpd': <uptime_in_seconds>,
                'wedge_agent': <uptime_in_seconds>,
            }
        """
        agent_uptime_map = {}
        services = services or ALLOWED_FBOSS_AGENTS
        for agent_name in services:
            pid_output = await self.get_service_main_pid(service=agent_name.lower())
            pid = pid_output.strip().split("\n")
            if pid:
                process_id = int("".join(pid[0]))
                # 'etimes' will give the elapsed time of the PID in seconds
                check_uptime_cmd = (
                    f"sudo ps -p {process_id} -o etimes | grep -v ELAPSED"
                )
                uptime_output = await self.async_run_cmd_on_shell(check_uptime_cmd)
                if not uptime_output:
                    self.logger.error(
                        f"Uptime output of agent {agent_name} was empty. This "
                        f"could be a sign of the agent crashing on the device. "
                        f'Use the command "systemctl status {agent_name}" to '
                        f"obtain the device status"
                    )
                    # NOTE: Initializing the uptime to 0 seconds to symbolize
                    # the agent crash and let the test fail for further debugging
                    uptime_output = "0"
                agent_uptime_map[agent_name] = int(uptime_output.strip())

        return agent_uptime_map

    async def async_format_ip(self, ip):
        family = socket.AF_INET if len(ip.addr) == 4 else socket.AF_INET6
        return socket.inet_ntop(family, ip.addr)

    async def async_format_route(self, route):
        next_hops = ", ".join(
            await self.async_format_ip(ip) for ip in route.nextHopAddrs
        )
        return "%s --> %s" % (await self.async_format_prefix(route.dest), next_hops)

    async def async_format_prefix(self, prefix):
        return "%s/%d" % (await self.async_format_ip(prefix.ip), prefix.prefixLength)

    async def get_route_table_count(self) -> int:
        """
        Queries agent to fetch the number of routes in the route table
        """
        try:
            async with self.async_agent_client as client:
                route_table = await client.getRouteTable()
                self.logger.info(
                    f"Successfully Executed get route table details: {len(route_table)}"
                )
                return len(route_table)
        except Exception as e:
            self.logger.info(e)
            return 0

    async def get_route_table_details_count(self) -> int:
        """
        Queries agent to fetch the number of routes in the route table
        """
        try:
            async with self.async_agent_client as client:
                route_table = await client.getRouteTableDetails()
                self.logger.info(
                    f"Successfully Executed get route table details: {len(route_table)}"
                )
                return len(route_table)
        except Exception as e:
            self.logger.info(e)
            return 0

    # =========================================================================
    # OpenR Methods (Internal Only - Not Available in OSS)
    # =========================================================================

    @async_retryable(retries=5, sleep_time=60)
    async def _get_kvstore_keys(
        self, node: str, area: str, keydump_params: "KeyDumpParams"
    ) -> List[Tuple[str, OpenrKvStoreDetails]]:
        """
        Given a node and a default keydump_params, this method retrieves the
        keys in the kv store of the node and the originator_id and version for
        each key
        """
        if TAAC_OSS:
            raise NotImplementedError(
                "OpenR KvStore operations require Meta-internal OpenR infrastructure. "
                "Not available in OSS mode."
            )
        try:
            async with get_openr_ctrl_cpp_client(to_fb_fqdn(node)) as client:
                resp = await client.getKvStoreKeyValsFilteredArea(keydump_params, area)
            all_details: List[Tuple[str, OpenrKvStoreDetails]] = []

            for k, v in resp.keyVals.items():
                details = OpenrKvStoreDetails(
                    key=str(k),
                    originator_id=str(v.originatorId),
                    version=str(v.version),
                )
                all_details.append((str(k), details))

            all_details.sort()
            return all_details

        except Exception as ex:
            self.logger.info(
                f"Caught this exception while making a thrift call to openr on {self.hostname}: {ex}. \nRetrying!"
            )
            raise

    @async_retryable(retries=30, sleep_time=5)
    async def _validate_openr_kvstore_sync_per_area(
        self, nodes: List[str], area: str
    ) -> None:
        """
        Given a list of nodes, this method will verify if the kv store of all the nodes
        and the DUT are in sync.
        """
        if TAAC_OSS:
            raise NotImplementedError(
                "OpenR KvStore sync validation requires Meta-internal OpenR infrastructure. "
                "Not available in OSS mode."
            )
        # Set openr options to instantiate OpenrCtrlCmd
        self.logger.info(f"Validating the KV store sync for {area} for {nodes}")
        openr_options = bunch.Bunch()
        openr_options.host = self.hostname
        openr_options.timeout = OPENR_THRIFT_CALL_TIMEOUT
        openr_options.fib_agent_port = OPENR_FIB_AGENT_PORT

        # Get default dump params
        openr_ctrl_cmd = OpenrCtrlCmd(openr_options)
        keydump_params: KeyDumpParams = openr_ctrl_cmd.buildKvStoreKeyDumpParams(
            prefix=""
        )

        node_to_kvdetails: Dict[str, List[Tuple[str, OpenrKvStoreDetails]]] = {}
        # nodes.append(self.hostname)
        self.logger.info(
            "Now fetch KV store entries for all OpenR running nodes in test bed"
        )
        for node in nodes:
            all_details = await self._get_kvstore_keys(node, area, keydump_params)
            node_to_kvdetails[node] = all_details

        # get the first value in the dict and then compare if all the
        # keys have the same value
        # If the kvstore is in sync, we expect everyone to ahve the same value
        # since we have sorted the values for each node
        n_iter = iter(node_to_kvdetails)
        first_node = next(n_iter)
        first_node_details = node_to_kvdetails[first_node]

        kvstore_in_sync = True
        for k, v in node_to_kvdetails.items():
            if v == first_node_details:
                self.logger.info(f"{k} has kv store in sync")
            else:
                self.logger.info(f"{k} does not have kv store in sync!")
                kvstore_in_sync = False

        self.test_case_obj.assertTrue(
            kvstore_in_sync,
            f"kv store is not in sync between {node_to_kvdetails.keys()}",
        )
        self.logger.info("All nodes are verified to have their kv store in sync")

    async def validate_openr_kvstore_sync(self, nodes: List[str]) -> None:
        if TAAC_OSS:
            raise NotImplementedError(
                "OpenR KvStore sync validation requires Meta-internal OpenR infrastructure. "
                "Not available in OSS mode."
            )
        area_nodes_map: DefaultDict[str, List[str]] = defaultdict(list)
        for node in nodes:
            async with get_openr_ctrl_cpp_client(to_fb_fqdn(node)) as client:
                areas_info = await client.getRunningConfigThrift()
                areas: Set[str] = {a.area_id for a in areas_info.areas}
                self.logger.info(f"Area found for {node}: {areas}")
                for area in areas:
                    area_nodes_map[area].append(node)

        self.logger.info(f"Areas to devices mapping: {area_nodes_map}")
        for area, node_list in area_nodes_map.items():
            await self._validate_openr_kvstore_sync_per_area(node_list, area)

    async def _async_get_all_openr_adjacencies(self) -> Sequence["AdjacencyDatabase"]:
        """
        Returns OpenR LM adj database
        """
        if TAAC_OSS:
            raise NotImplementedError(
                "OpenR adjacency operations require Meta-internal OpenR infrastructure. "
                "Not available in OSS mode."
            )
        adj_filter: AdjacenciesFilter = AdjacenciesFilter(selectAreas=set())
        async with get_openr_ctrl_cpp_client(to_fb_fqdn(self.hostname)) as client:
            openr_adjacency_database: Sequence[
                AdjacencyDatabase
            ] = await client.getLinkMonitorAdjacenciesFiltered(adj_filter)

        if not openr_adjacency_database[0].adjacencies:
            raise EmptyOutputReturnError(
                f"{self.hostname} does not have any OpenR sessions configured on it!"
            )
        return openr_adjacency_database

    # NOTE : T105172173 Move all these openr asserts out of driver code and add them to the new HealthChecks
    def _assert_openr_adjacency_count(
        self, openr_adj_intf_map, interface_names
    ) -> None:
        """
        Based on the state specified, this function asserts the need to have
        a certain number of OPENR adjacencies on the host
        """
        self.test_case_obj.assertEqual(
            len(openr_adj_intf_map["existing adjacencies"]),
            len(interface_names),
            msg=f"OpenR expected adjacencies missing on interface list {openr_adj_intf_map['missing adjacencies']} on {self.hostname}",
        )

    async def async_get_openr_adjacencies_intf_states(
        self,
        interface_names: List[str],
        print_output: bool = True,
        desc_regex: str = "",
    ) -> Dict[str, List[Dict[str, str]]]:
        """
        Args:
            interface_names(List[str]): List of interface names whose OPENR sess counts are needed
            print_output (str): Tabulates the OPENR session output per interface when set to true
            desc_regex (str): Extra validation for sessions fetched by OPENR Thrift API

        Returns:
            Dictionary which maps the list of interfaces with their corresponding count
            of OPENR adjacencies
        """
        if TAAC_OSS:
            raise NotImplementedError(
                "OpenR adjacency operations require Meta-internal OpenR infrastructure. "
                "Not available in OSS mode."
            )
        openr_adjacency_database_sequence: Sequence[
            AdjacencyDatabase
        ] = await self._async_get_all_openr_adjacencies()
        existing_adjacency_intfs: List[Dict[str, str]] = []
        missing_adjacency_intfs: List[Dict[str, str]] = []
        openr_adj_intf_map: Dict[str, List[Dict[str, str]]] = {}

        for interface_name in interface_names:
            vlan_info = await self.async_get_interface_name_to_port_id_and_vlan_id(
                interface_name
            )
            vlan_id = vlan_info.vlan_id
            port_name: str = f"fboss{vlan_id}"
            port_dict: Dict[str, str] = {interface_name: port_name}
            # NOTE :  T105171590 Convert openr_adj_intf_map to a dataclass along with refactoring of BGP equivalent.
            for openr_adjacency_database in openr_adjacency_database_sequence:
                for adj in openr_adjacency_database.adjacencies:
                    if port_name == adj.ifName:
                        existing_adjacency_intfs.append(port_dict)
                if port_dict not in existing_adjacency_intfs:
                    missing_adjacency_intfs.append(port_dict)
        openr_adj_intf_map["existing adjacencies"] = existing_adjacency_intfs
        openr_adj_intf_map["missing adjacencies"] = missing_adjacency_intfs
        return openr_adj_intf_map

    @async_retryable(
        retries=30,
        sleep_time=2,
        max_duration=60,
        exceptions=(ThriftPythonError,),
    )
    async def async_check_openr_adjacencies(
        self,
        interface_names: List[str],
        print_output: bool = True,
    ) -> None:
        """
        Takes in the list of interfaces and does the following:
        1) For every interface, gets the session count for established/non-established sessions
        2) Asserts that all of the interfaces have the specified session count based on 'state' info
        """
        if TAAC_OSS:
            raise NotImplementedError(
                "OpenR adjacency operations require Meta-internal OpenR infrastructure. "
                "Not available in OSS mode."
            )
        openr_adj_intf_map: Dict[
            str, List[Dict[str, str]]
        ] = await self.async_get_openr_adjacencies_intf_states(
            interface_names, print_output
        )
        self.logger.info(
            f"OpenR adjacencies found  on intf list {openr_adj_intf_map['existing adjacencies']} on {self.hostname}"
        )
        # TODO(pavanpatil) : To take care of openr_dc realted scenarios
        self._assert_openr_adjacency_count(openr_adj_intf_map, interface_names)

    @async_retryable(retries=150, sleep_time=5, exceptions=(Exception,))
    async def async_wait_for_agent_state_configured(self) -> None:
        """
        Check if agent satate is CONFIGURED
        Raieses:
            Exception if state is not CONFIGURED
        """
        agent_state = await self.async_get_switch_run_state()

        self.logger.debug(f"Agent state is {agent_state}")
        if agent_state is None or agent_state != SwitchRunState.CONFIGURED:
            raise AssertionError("Agent is not in CONFIGURED state")

    def get_async_local_drainer_client(self):
        # TODO: Implement OSS alternative for local drainer
        raise NotImplementedError(
            "LocalDrainer client not available in OSS mode. "
            "Drain/undrain requires Meta-internal infrastructure."
        )

    @property
    def async_agent_client(self) -> FbossCtrl:
        """
        Create FBOSS Agent async client
        """
        raise NotImplementedError(
            "FBOSS Agent async client not available in OSS mode. "
            "Use FbossSwitchInternal for ServiceRouter-based connection."
        )

    async def async_get_lldp_neighbors(self) -> Dict[str, SwitchLldpData]:
        """
        Return LLDP data in format
        {eth1/1/1: SwitchLldpData('rsw001.p001.f01.abc', eth1/2/1)}
        """
        fboss_lldp_data = await self._async_get_lldp_neighbors()
        switch_lldp_data: Dict[str, SwitchLldpData] = {}
        for lldp_peer_info in fboss_lldp_data:
            remote_device_name = lldp_peer_info.systemName
            remote_port = lldp_peer_info.printablePortId
            local_port = lldp_peer_info.localPortName
            if remote_device_name is None or local_port is None or remote_port is None:
                continue
            # strip domain name
            remote_device_name = remote_device_name.replace(".tfbnw.net", "").replace(
                ".facebook.com", ""
            )
            switch_lldp_data[local_port] = SwitchLldpData(
                remote_device_name=remote_device_name,
                remote_intf_name=remote_port,
            )
        return switch_lldp_data

    @async_retryable(retries=3, sleep_time=5, exceptions=(ThriftError,))
    async def _async_get_lldp_neighbors(self) -> Sequence[LinkNeighborThrift]:
        """
        Request LLDP neighbors from FBOSS switch
        Returns:
            LinkNeighborThrift
        """
        self.logger.debug(f"Collecting LLDP info {self.hostname}")
        async with self.async_agent_client as client:
            return await client.getLldpNeighbors()

    async def async_get_switch_run_state(self) -> SwitchRunState:
        """
        Request agent run state
        Returns:
            SwitchRunState
        """
        self.logger.debug("Fetching agent_state")
        async with self.async_agent_client as client:
            return await client.getSwitchRunState()

    @async_retryable(retries=3, sleep_time=5, exceptions=(Exception,))
    async def async_get_all_port_info(self) -> Dict[int, PortInfoThrift]:
        """
        Makes a thrift call to agent to get all the port info
        """
        async with self.async_agent_client as client:
            all_ports_info = dict(await client.getAllPortInfo())

        if not all_ports_info:
            raise EmptyOutputReturnError(
                f"Something went wrong while attempting to retrieve all the "
                f"port information status on {self.hostname}. Please check!"
            )
        return all_ports_info

    @async_retryable(retries=3, sleep_time=5, exceptions=(ThriftError,))
    async def async_get_selected_counters(
        self, keys: List[str]
    ) -> Mapping[str, Union[int, float]]:
        """
        Makes a thrift call to return the values of the selected counters on the
        FBOSS
        Returns a map of the counter's key to the value
        """
        async with self.async_agent_client as client:
            result = await client.getSelectedCounters(keys)
        no_value_keys = set(keys) - set(result.keys())
        if no_value_keys:
            raise InvalidInputError(f"Unable to find values for {no_value_keys}")
        return dict(result)

    async def _async_fboss_clear_port_stats(self, port_ids: List[int]) -> None:
        """
        Clear all port counters by id
        """
        self.logger.debug("Clearing port counters")
        async with self.async_agent_client as client:
            await client.clearPortStats(port_ids)

    @memoize_on_app_overload()
    async def async_get_fib_table_entries_count(self) -> int:
        """
        Used to obtain the instantaneous number of v4 and v6 route entries
        in the FIB of a given FBOSS device.
        """
        async with self.async_agent_client as client:
            fib_result = await client.getRouteTable()
        self.logger.info(
            f"{self.hostname} has a total of {len(fib_result)} entries in its FIB"
        )
        return len(fib_result)

    async def async_get_fib_table_entries_all(self) -> Sequence[UnicastRoute]:
        """
        Used to obtain the instantaneous number of v4 and v6 route entries
        in the FIB of a given FBOSS device.
        """
        async with self.async_agent_client as client:
            return await client.getRouteTable()

    async def async_get_fib_table_entries(self) -> None:
        """
        Used to obtain the instantaneous number of v4 and v6 route entries
        in the FIB of a given FBOSS device.
        """
        fib_routes: str = ""
        fib_result: Sequence[
            UnicastRoute
        ] = await self.async_get_fib_table_entries_all()
        for route in fib_result:
            fib_routes += f"Route {await self.async_format_route(route)}\n"
        fib_entries_url = await async_everpaste_str(content=fib_routes, color=False)
        self.logger.info(f"Fib entries on {self.hostname}: {fib_entries_url}")

    ######################################################
    #                  ASYNC SSH METHODS                 #
    ######################################################

    @async_retryable(retries=2, sleep_time=10, exceptions=(ConnectionResetError,))
    async def async_run_cmd_on_shell(
        self,
        cmd: str,
        timeout: int = 300,
        print_stdout: bool = False,
        block: bool = True,
        return_on_msg: t.Optional[str] = None,
        *args,
        **kwargs,
    ) -> str:
        """
        Run a command on the remote switch via SSH.

        OSS implementation uses asyncssh from oss_driver_utils.
        The internal mixin overrides this with Meta's AsyncSSHClient/ParamikoClient.
        """
        username = "root"
        ssh_port = 22

        self.logger.debug(f"Running cmd {cmd} on {self.hostname}")

        async with AsyncSSHClient(
            self.hostname, port=ssh_port, username=username
        ) as client:
            result = await client.async_run(
                cmd=cmd,
                timeout_sec=timeout,
                print_stdout=print_stdout,
                block=block,
                return_on_msg=return_on_msg,
            )

        # pyrefly: ignore [bad-return]
        return result.stdout if result else None

    async def async_create_dir_if_not_exists(self, file_path: str) -> None:
        from taac.utils.oss_driver_utils import (
            create_dir_if_not_exists,
        )

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None, create_dir_if_not_exists, self.hostname, file_path
        )

    async def async_check_if_file_exists(self, path: str) -> bool:
        async with AsyncSSHClient(self.hostname) as client:
            return await client.async_exists_and_isfile(remote_path=path)

    async def wait_for_ssh_reachable(
        self, max_duration: int = 600, sleep_time: int = 5
    ) -> None:
        from taac.utils.oss_driver_utils import (
            wait_for_ssh_reachable as _wait_for_ssh_reachable,
        )

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: _wait_for_ssh_reachable(
                ssh_entity=self.hostname,
                max_duration=max_duration,
                sleep_time=sleep_time,
            ),
        )

    async def async_get_fboss_lldp_neighbors(self):
        cmd = "fboss lldp"
        output = await self.async_run_cmd_on_shell(cmd)
        return output

    async def async_get_systemd_service_counters(
        self, service: Union[AristaCriticalAgents, SystemctlServiceName]
    ) -> Dict[str, str]:
        """
        Get systemd service counters
        # systemctl show wedge_agent
        Type=simple
        Restart=always
        NRestarts=0
        Returns:
            Dictionary {"Type":"simple", "Restart:"always"}
        """
        cmd = f"systemctl show {service.value} --no-page"
        output = await self.async_run_cmd_on_shell(cmd)
        result: Dict[str, str] = {}
        for line in output.split("\n"):
            splitted_line = line.split("=")
            if len(splitted_line) == 2:
                result[splitted_line[0]] = splitted_line[1]
        return result

    async def async_get_single_systemd_service_counter_as_int(
        self,
        service: Union[AristaCriticalAgents, SystemctlServiceName],
        counter: str,
        service_counters_map: Optional[Dict[str, str]] = None,
    ) -> int:
        """
        Return systemd counter as integer
        Args:
            service: service to check for number of restarts
            counter: counter name to return
            service_counters_map: output of async_get_systemd_service_counters.
                                  If not provided will be retrieved from device
        """
        if service_counters_map is None:
            service_counters_map = await self.async_get_systemd_service_counters(
                service
            )
        try:
            return int(service_counters_map[counter])
        except KeyError as ex:
            self.logger.exception(
                f"systemctl show {service.value} output doesn't have {counter} counter"
            )
            raise ex
        except ValueError as ex:
            self.logger.exception(
                f"systemctl show {service.value} {counter} {service_counters_map[counter]}"
                "cannot be converted to int"
            )
            raise ex

    async def async_get_process_restart_count(
        self,
        service: SystemctlServiceName,
        service_counters_map: Optional[Dict[str, str]] = None,
    ) -> int:
        """
        Return Systemd NRestarts counter, e.g. number of unplanned restarts for service.
        Args:
            service: service to check for number of restarts
            service_counters_map: output of async_get_systemd_service_counters.
                                  If not provided will be retrieved from device
        """
        return await self.async_get_single_systemd_service_counter_as_int(
            service, "NRestarts", service_counters_map
        )

    async def async_get_service_monotonic_start_time(
        self,
        service: Service,
        service_counters_map: Optional[Dict[str, str]] = None,
    ) -> int:
        """
        For the specified service returns an integer, which is the monotonic
        start time of the service
        systemctl show <service> -p ExecMainStartTimestampMonotonic
        Args:
            service: service to check for number of restarts
            service_counters_map: output of async_get_systemd_service_counters.
                                  If not provided will be retrieved from device
        """
        return await self.async_get_single_systemd_service_counter_as_int(
            service, "ExecMainStartTimestampMonotonic", service_counters_map
        )

    async def async_get_service_status(
        self,
        service: Service,
        service_counters_map: Optional[Dict[str, str]] = None,
    ) -> SystemctlServiceStatus:
        """
        For a given service, returns its SystemctlServiceStatus state.
        Args:
            service: service to check for number of restarts
            service_counters_map: output of async_get_systemd_service_counters.
                                  If not provided will be retrieved from device
        """
        if service_counters_map is None:
            service_counters_map = await self.async_get_systemd_service_counters(
                service
            )
        COUNTER = "ActiveState"
        try:
            output = service_counters_map[COUNTER]
        except KeyError as ex:
            self.logger.exception(
                f"systemctl show {service.value} output doesn't have {COUNTER} counter"
            )
            raise ex

        if output == "active":
            status: SystemctlServiceStatus = SystemctlServiceStatus.ACTIVE
        elif output == "inactive":
            status: SystemctlServiceStatus = SystemctlServiceStatus.INACTIVE
        elif output == "failed":
            status: SystemctlServiceStatus = SystemctlServiceStatus.FAILED
        else:
            status: SystemctlServiceStatus = SystemctlServiceStatus.TRANSITIONING

        self.logger.debug(f"Current status of service {service.value}: {status.name}")
        return status

    async def async_get_service_status_counters(
        self,
        service: SystemctlServiceName,
    ) -> ServiceStatusCounters:
        service_counters = await self.async_get_systemd_service_counters(service)
        status = await self.async_get_service_status(service, service_counters)
        start_time = await self.async_get_service_monotonic_start_time(
            service, service_counters
        )
        restart_count = await self.async_get_process_restart_count(
            service, service_counters
        )
        return ServiceStatusCounters(
            start_time=start_time,
            restart_count=restart_count,
            status=status,
        )

    @is_dne_test_device
    @async_retryable(retries=2, sleep_time=10, exceptions=(Exception,))
    async def async_restart_service(
        self,
        service: Service,
        agents: Optional[List[str]] = None,
    ) -> None:
        """
        Restart service and validate restart process by comparing service uptime
        before and after restart
        Args:
            service: service to restart
        """
        self.logger.debug(
            f"Checking the uptime of service {service.value} before restarting it"
        )
        service_start_time_before_restart = (
            await self.async_get_service_monotonic_start_time(service)
        )

        self.logger.debug(
            f"Attempting to perform {service.value} restart on {self.hostname}..."
        )
        cmd = f"systemctl restart {service.value}"
        await self.async_run_cmd_on_shell(cmd)

        self.logger.debug(
            f"Checking the uptime of service {service.value} after restarting it"
        )
        service_start_time_after_restart = (
            await self.async_get_service_monotonic_start_time(service)
        )

        # Verifying service restart based on service uptime
        assert service_start_time_after_restart > service_start_time_before_restart
        self.logger.debug(
            f"Successfully restarted service {service.value} on {self.hostname} "
        )

    @is_dne_test_device
    @async_retryable(retries=2, sleep_time=10, exceptions=(Exception,))
    async def async_stop_service(
        self,
        service: Service,
        agents: Optional[List[str]] = None,
    ) -> None:
        cmd: str = f"systemctl stop {service.value}"
        self.logger.info(f"Attempting to stop {service.value} on {self.hostname}...")
        await self.async_run_cmd_on_shell(cmd)
        # verifying if the service is now inactive
        status = await self.async_get_service_status(service)
        assert status == SystemctlServiceStatus.INACTIVE
        self.logger.info(
            f"Successfully verified that the {service.name} is now inactive on {self.hostname}"
        )

    @is_dne_test_device
    @async_retryable(retries=2, sleep_time=10, exceptions=(Exception,))
    async def async_start_service(
        self,
        service: Service,
        agents: Optional[List[str]] = None,
    ) -> None:
        cmd: str = f"systemctl start {service.value}"
        self.logger.info(f"Attempting to start {service.value} on {self.hostname}...")
        await self.async_run_cmd_on_shell(cmd)
        # verifying if the service is now active
        status = await self.async_get_service_status(service)
        assert status == SystemctlServiceStatus.ACTIVE
        self.logger.info(
            f"Successfully verified that the {service.name} is now active on {self.hostname}."
        )

    async def async_create_file_with_content(
        self, file_location: str, content: str
    ) -> None:
        """
        This is an async function to create files on device and write provided content in to the file. If file already exists, it will overwrite the file.
        Args:
            file_location:
                file name with absolute path. For example - /var/facebook/dne/tmp-logfile.log
            content:
                content to add to the file
        Returns:
            None
        """
        file_path = "/".join(file_location.split("/")[:-1])
        self.logger.debug(
            f"Checking if path {file_path} exists on {self.hostname}. If not, creating and adding {content} to it."
        )
        await self.async_create_dir_if_not_exists(file_path)

        cmd = f"""echo '{content}' > {file_location}"""
        await self.async_run_cmd_on_shell(cmd)

    @async_retryable(
        retries=3,
        sleep_time=5,
        exceptions=(Exception,),
    )
    async def async_read_file(self, file_location: str) -> str:
        """
        Asynchronously checks if the file exists at the given location in the switch.

            Args:
                file_location: The file to check if exists

            Returns: None if the file exists else raises SshCommandError exceptiion
        """
        try:
            cmd = f"cat {file_location}"
            output: str = await self.async_run_cmd_on_shell(cmd)
            self.logger.debug(
                f"Verified if file is present at {file_location} on {self.hostname}"
            )
            return output
        except Exception as ex:
            self.logger.critical(
                f"While verfiying {file_location} on {self.hostname}, exception was raised: {ex}"
            )
            raise ex

    async def async_delete_file(self, file_location: str) -> None:
        """
        This is an async function to delete files from host. No error raised if file does not exists
        Args:
            file_location:
                file_name with absolute file path. For example /var/facebook/dne/tmp-file.log
        Returns:
            None
        """
        cmd = f"rm -f {file_location}"
        self.logger.debug(f"deleting file {file_location} on {self.hostname}")
        await self.async_run_cmd_on_shell(cmd)

    async def async_generate_everpaste_file_url(
        self, file_location: str
    ) -> Optional[str]:
        """
        This function takes a file path on the remote dut as an input argument, and returns an everpaste link of the content of that file.
        Args:
            file_location:
                file_name with absolute file path. For example /var/facebook/dne/tmp-file.log
        Returns:
            everpaste link of the file content. Error message if there are any errors
        """
        try:
            file_content = await self.async_read_file(file_location)
            return await async_everpaste_str(file_content, color=False)
        except Exception:
            return "Error uploading file or file does not exist"

    async def _async_is_onbox_drained_helper(self) -> DeviceDrainState:
        """
        Checks the onbox status drained status of the device
        """
        async with self.get_async_local_drainer_client() as client:
            is_drained: bool = await client.is_drained()
            on_box_drain_state: DeviceDrainState = (
                DeviceDrainState.DRAINED if is_drained else DeviceDrainState.UNDRAINED
            )
        self.logger.info(
            f"Device {self.hostname} on-box drain state is '{on_box_drain_state.name}'"
        )
        return on_box_drain_state

    async def async_softdrain_interface(self, interface: str, task_id: int = 0) -> None:
        """
        Soft-drain a single interface on this FBOSS switch via the on-box
        local drainer's `softdrain_interface` API. Equivalent to:

            fboss_local_drainer softdrain-interface <interface>

        Soft-drain depreferences the BGP advertisements via community without
        bringing the link down at the data plane.

        Args:
            interface: FBOSS interface name (e.g. "eth1/33/5").
            task_id: Optional task identifier passed through to the
                local drainer (default 0, matching the CLI default).
        """
        self.logger.info(
            f"Softdraining interface '{interface}' on {self.hostname} "
            f"(task_id={task_id})"
        )
        async with self.get_async_local_drainer_client() as client:
            await client.softdrain_interface(interface, task_id)
        self.logger.info(
            f"Softdrain of interface '{interface}' on {self.hostname} completed"
        )

    async def async_undrain_interface(self, interface: str) -> None:
        """
        Undrain a single interface on this FBOSS switch via the on-box
        local drainer's `undrain_interface` API. Equivalent to:

            fboss_local_drainer undrain-interface <interface>

        Reverses both hard- and soft-drain state for the named interface.

        Args:
            interface: FBOSS interface name (e.g. "eth1/33/5").
        """
        self.logger.info(f"Undraining interface '{interface}' on {self.hostname}")
        async with self.get_async_local_drainer_client() as client:
            await client.undrain_interface(interface)
        self.logger.info(
            f"Undrain of interface '{interface}' on {self.hostname} completed"
        )

    @memoize_on_app_overload()
    async def async_get_interface_detail(self, vlan_id) -> InterfaceDetail:
        """
        Makes a thrift call to agent to get all the port info
        """
        async with self.async_agent_client as client:
            return await client.getInterfaceDetail(interfaceId=vlan_id)

    @memoize_on_app_overload()
    async def async_get_all_interfaces(self) -> Mapping[int, InterfaceDetail]:
        """
        Makes a thrift call to agent to get all interface details
        """
        async with self.async_agent_client as client:
            interface_details = await client.getAllInterfaces()
            self.logger.info(f"Interface count: {len(interface_details)}")
        return interface_details

    async def async_get_interface_ipv6_address(
        self, interface_name: str
    ) -> Tuple[str, int]:
        """
        Fetches the ipv6 address associated with the interface.
        On fboss its a straightforward mapping of every interface to its vlan,
        to its ipv6 address

        On arista and cisco, if its an L3 port, the mapping is simple
        and the method will return the ipv6 address configured directly
        on the port. However if its an L2 port, then the method will first find
        the vlan that the port belongs to, and then based on the VLAN
        it will find the ipv6 address associated with the Vlan.

        Args:
            interface_name (str): Interface name on the arista/cisco/fboss
            device that is connected to the ixia port, or whose ipv6 address
            association is required to be returned

        Returns:
            Tuple[str, int]: Returns the global ipv6 address and the subnet mask
        """
        vlan_id: Optional[int] = None
        ports = await self.async_get_all_port_info()
        for port in ports.values():
            if port.name == interface_name:
                vlan_id = port.vlans[0]
                break
        intf_detail: InterfaceDetail = await self.async_get_interface_detail(
            vlan_id=vlan_id
        )

        for address in intf_detail.address:
            ip_addr_obj = ipaddress.ip_address(address.ip.addr)
            if (
                not isinstance(ip_addr_obj, ipaddress.IPv6Address)
                or not ip_addr_obj.is_global
                or ip_addr_obj.is_link_local
            ):
                continue

            return (str(ip_addr_obj), int(address.prefixLength))

        raise InsufficientInputError("Unable to find Global IPv6 address")

    async def async_get_low_traffic_ports(
        self, port_names: List[str], bidirectional: bool = False
    ) -> List[str]:
        """
        Given a list of port names, this method will return only those ports which have low traffic.
        The threshold for low traffic is defined by the variable LOW_TRAFFIC_THRESHOLD constant
        Default behavior is to check for egress traffic only. When bidirectional is set to true then
        it will check for both ports
        """
        port_egress_traffic_bps = await self.get_egress_traffic_stats(port_names)
        port_ingress_traffic_bps = await self.get_egress_traffic_stats(port_names)
        combined_port_speeds = {}
        for key in port_egress_traffic_bps.keys():
            # Add a new entry in the combined dictionary with the key and a list of the values from the two dictionaries
            combined_port_speeds[key] = [
                port_egress_traffic_bps[key],
                port_ingress_traffic_bps[key],
            ]
        low_traffic_ports = []
        # Iterate over the items in the combined dictionary
        for key, value in combined_port_speeds.items():
            # If either of the elements in the value list is less than 150
            if bidirectional and value[0] < _ONE_MBPS or value[1] < _ONE_MBPS:
                # Print the key and value
                self.logger.info(f"Port with low traffic found: {key}: {value}")
                low_traffic_ports.append(key)

            if not bidirectional and value[0] < _ONE_MBPS:
                self.logger.info(f"Port with low traffic found: {key}: {value}")
                low_traffic_ports.append(key)
        return low_traffic_ports

    async def async_get_egress_pkt_traffic_stats(
        self, egress_interfaces: List[str]
    ) -> Dict[str, float]:
        egress_interface_keys = list(
            map(
                lambda interface: EGRESS_PKT_RATE_KEY.format(interface),
                egress_interfaces,
            )
        )
        egress_stats_pkts = await self.async_get_selected_counters(
            egress_interface_keys
        )
        return {
            keys.split(".")[0]: int(pkts) for keys, pkts in egress_stats_pkts.items()
        }

    def ip_ntop(self, addr):
        if len(addr) == 4:
            return socket.inet_ntop(socket.AF_INET, addr)
        elif len(addr) == 16:
            return socket.inet_ntop(socket.AF_INET6, addr)
        else:
            raise ValueError("bad binary address %r" % (addr,))

    async def async_get_desired_unicast_route(self, prefix: str) -> UnicastRoute:
        """
        Get the weights of the prefixes
        """
        async with self.async_agent_client as client:
            routes = await client.getRouteTable()
        candidate_route = None
        for route in routes:
            iter_prefix = "{}/{}".format(
                self.ip_ntop(route.dest.ip.addr), route.dest.prefixLength
            )
            if iter_prefix == prefix:
                self.logger.info(f"Found prefix {iter_prefix} in {self.hostname}")
                candidate_route = route
                break
        if not candidate_route:
            raise Exception(f"Prefix {prefix} not found in {self.hostname}")
        # Retrieve the next hops and their weights for the given prefix
        return candidate_route

    async def async_get_desired_unicast_routes_in_network(
        self, network: str
    ) -> Dict[str, UnicastRoute]:
        """
        Get unicast routes in the given network in CIDR format (e.g. 192.168.0.0/24)
        """
        async with self.async_agent_client as client:
            routes = await client.getRouteTable()
        ip_address_network = ip_network(network)
        candidate_routes = {}
        for route in routes:
            ip_addr = self.ip_ntop(route.dest.ip.addr)
            iter_prefix = "{}/{}".format(ip_addr, route.dest.prefixLength)
            if ip_address(ip_addr) in ip_address_network:
                candidate_routes[iter_prefix] = route
        return candidate_routes

    async def async_get_next_hop_weights_in_network(
        self, network: str
    ) -> Dict[str, List[NextHopAttributes]]:
        """
        Get the weights of the prefixes in the given network in CIDR format (e.g. 192.168.0.0/24)
        """
        routes = await self.async_get_desired_unicast_routes_in_network(network)
        nh_attribute_map = defaultdict(list)

        interface_name_to_port_name_mapping = (
            await self._async_get_all_interface_name_to_port_name_mapping()
        )
        interface_speed_map = await self.async_get_interfaces_speed_in_Gbps()
        for prefix, route in routes.items():
            for nexthops in route.nextHops:
                nh_ifname = none_throws(nexthops.address.ifName)
                nh_port_name = interface_name_to_port_name_mapping[nh_ifname]
                nh_attribute_map[prefix].append(
                    NextHopAttributes(
                        nh_addr=self.ip_ntop(nexthops.address.addr),
                        nh_ifname=nh_ifname,
                        nh_weight=nexthops.weight,
                        nh_port_name=nh_port_name,
                        nh_port_speed=interface_speed_map[nh_port_name],
                    )
                )
        return nh_attribute_map

    async def async_get_next_hop_weights(self, prefix: str) -> List[NextHopAttributes]:
        """
        Get the weights of the prefixes
        """
        route = await self.async_get_desired_unicast_route(prefix)

        interface_name_to_port_name_mapping = (
            await self._async_get_all_interface_name_to_port_name_mapping()
        )
        interface_speed_map = await self.async_get_interfaces_speed_in_Gbps()

        # Fetching the Nexthops weight information
        nh_attribute_list = []
        for nexthops in route.nextHops:
            nh_ifname = none_throws(nexthops.address.ifName)
            nh_port_name = interface_name_to_port_name_mapping[nh_ifname]
            nh_attribute_list.append(
                NextHopAttributes(
                    nh_addr=self.ip_ntop(nexthops.address.addr),
                    nh_ifname=nh_ifname,
                    nh_weight=nexthops.weight,
                    nh_port_name=nh_port_name,
                    nh_port_speed=interface_speed_map[nh_port_name],
                )
            )
        self.logger.info(
            f"Nexthop attributes for {prefix} on {self.hostname} are {nh_attribute_list}"
        )
        return nh_attribute_list

    async def _async_get_all_interface_name_to_port_name_mapping(
        self,
    ) -> Dict[str, str]:
        """
        Given a list of interface names, this function returns a map of corresponding
        port names
        """
        interface_name_to_port_id_mapping = await self.async_get_all_interfaces_info()
        interface_name_to_port_name_mapping = {}
        for port_name, interface_info in interface_name_to_port_id_mapping.items():
            vlan = interface_info.vlan_id
            interface_name_to_port_name_mapping[f"fboss{vlan}"] = port_name
        return interface_name_to_port_name_mapping

    async def async_get_cps_route_attribute_policy(self):
        """
        For a given box, gets the CPS policy on the box. A CPS policy is a combination of
        path_selection_policy and route_attribute_policy
        Path-selection-policy typically has use-cases in HGRID staggered drain
        Route-attribute-policy typically has use-cases in CTE
        """
        async with await self._get_bgp_client() as bgp_client:
            route_attribute_policy = await bgp_client.getRouteAttributePolicy()
        return route_attribute_policy

    async def get_bgp_table_length(self) -> int:
        """
        Returns the rib entries for the given device
        This structure is seen in `fbgf bgp_thrift.thrift` - https://fburl.com/phabricator/0gxnbgz
        """
        async with await self._get_bgp_client() as bgp_client:
            # pyre-fixme[58]: `+` is not supported for operand types
            #  `Sequence[TRibEntry]` and `Sequence[TRibEntry]`.
            rib_entries = await bgp_client.getRibEntries(
                TBgpAfi.AFI_IPV6
            ) + await bgp_client.getRibEntries(TBgpAfi.AFI_IPV4)
        rib_table_count = len(rib_entries)
        self.logger.info(f"Rib table count: {rib_table_count}")
        return rib_table_count

    async def async_get_cps_path_selection_policy(self):
        """
        For a given box, gets the CPS policy on the box. A CPS policy is a combination of
        path_selection_policy and route_attribute_policy
        Path-selection-policy typically has use-cases in HGRID staggered drain
        Route-attribute-policy typically has use-cases in CTE
        """
        async with await self._get_bgp_client() as bgp_client:
            path_selection_policy = await bgp_client.getPathSelectionPolicy()
        return path_selection_policy

    async def async_verify_ecmp_nexthop_group_member_count(
        self,
    ) -> int:
        # Step 1: Determine the minimum length of subnets needed

        # Define the command to run on the shell
        cmd = "fboss2 show hw-object NEXT_HOP_GROUP"
        # Run the command on the shell and get the result
        res = await self.async_run_cmd_on_shell(cmd)
        # Use regular expression to find all occurrences of NextHopGroupMemberSaiId(xxxx):
        pattern = r"NextHopGroupMemberSaiId\(\d+\):"
        matches = re.findall(pattern, res)
        # Count the occurrences
        return len(matches)

    async def get_prefix_to_nexthopid_map(self) -> Dict[str, int]:
        cmd = "fboss2 show hw-object ROUTE_ENTRY"
        route_entry_objects = await self.async_run_cmd_on_shell(cmd)
        prefix_to_nexthopid = {}
        for line in route_entry_objects.splitlines():
            if "RouteEntry" in line:
                match = re.search(r"prefix: ([^)]+)", line)
                if match:
                    prefix = match.group(1)
                    match = re.search(r"NextHopId: (\d+), Metadata: (\d+)", line)
                    if match:
                        next_hop_id = int(match.group(1))
                        prefix_to_nexthopid[prefix] = next_hop_id
        prefix_to_nexthopid_fburl: str = await async_everpaste_str(
            str(prefix_to_nexthopid), color=False
        )
        self.logger.info(
            f"Prefix to Nexthop(ecmp/non-ecmp): {prefix_to_nexthopid_fburl}"
        )
        return prefix_to_nexthopid

    async def group_id_to_member_id_list(
        self, is_validate_all_groups: bool = False
    ) -> t.DefaultDict[int, t.List[int]]:
        cmd = "fboss2 show hw-object NEXT_HOP_GROUP"
        next_hop_group_objects = await self.async_run_cmd_on_shell(cmd)

        next_hop_group_members = defaultdict(list)
        unresolved_group_list = []

        for line in next_hop_group_objects.splitlines():
            if line.startswith("NextHopGroupMemberSaiId"):
                match = re.search(
                    r"NextHopGroupMemberSaiId\((\d+)\): \(NextHopGroupId: (\d+)", line
                )
                if match:
                    next_hop_group_member_id = int(match.group(1))
                    next_hop_group_id = int(match.group(2))
                    next_hop_group_members[next_hop_group_id].append(
                        next_hop_group_member_id
                    )
            elif line.startswith("NextHopGroupSaiId"):
                match = re.search(r"NextHopGroupSaiId\((\d+)\):", line)
                if match:
                    unresolved_group_list.append(int(match.group(1)))

        if is_validate_all_groups:
            next_hop_group_ids = set(next_hop_group_members.keys())
            unresolved_group_set = set(unresolved_group_list)

            # ECMP group not having Members
            missing_from_next_hop_group_members = (
                unresolved_group_set - next_hop_group_ids
            )

            #
            missing_from_unresolved_group_list = (
                next_hop_group_ids - unresolved_group_set
            )

            if missing_from_next_hop_group_members:
                fburl: str = await async_everpaste_str(
                    str(missing_from_next_hop_group_members), color=False
                )
                self.logger.info(
                    f"{len(missing_from_next_hop_group_members)} ECMP groups that do not have ECMP members associated with them: {fburl}"
                )
                missing_prefix_nhid_map = {}
                total_prefix_nexthopid_map = await self.get_prefix_to_nexthopid_map()
                for prefix, nexthop_id in total_prefix_nexthopid_map.items():
                    if nexthop_id in missing_from_next_hop_group_members:
                        missing_prefix_nhid_map[prefix] = nexthop_id
                missing_prefix_nhid_map_fburl: str = await async_everpaste_str(
                    str(missing_prefix_nhid_map), color=False
                )
                self.logger.info(
                    f"{len(missing_prefix_nhid_map)} prefixes associated with these Unresolved ECMP groups\n"
                    f"{len(set(missing_prefix_nhid_map.values()))} Groups out of total of {len(missing_from_next_hop_group_members)} groups associated with Prefixes\n"
                    f"Mapping details: {missing_prefix_nhid_map_fburl}"
                )
            if missing_from_unresolved_group_list:
                self.logger.info(
                    f"ECMP groups/members map missing from unresolved ECMP group list: {missing_from_unresolved_group_list}"
                )

            if (
                not missing_from_next_hop_group_members
                and not missing_from_unresolved_group_list
            ):
                self.logger.info(
                    "All NextHopGroupSaiIds are accounted for in both next_hop_group_members and unresolved_group_list"
                )

        return next_hop_group_members

    async def get_monitored_prefix_supernet_nexthop_map(
        self, monitored_prefix_supernet: t.Optional[str] = None
    ):
        prefix_to_nexthopid = await self.get_prefix_to_nexthopid_map()
        next_hop_group_members = await self.group_id_to_member_id_list(
            is_validate_all_groups=True
        )
        monitored_prefix_supernet_nexthop_map = defaultdict(dict)
        for prefix, nexthop_id in prefix_to_nexthopid.items():
            if monitored_prefix_supernet is None or prefix.startswith(
                monitored_prefix_supernet
            ):
                if nexthop_id not in next_hop_group_members:
                    print(
                        f"Failure: NextHopId {nexthop_id} for prefix {prefix} not found in next_hop_group_members"
                    )
                elif not next_hop_group_members[nexthop_id]:
                    print(
                        f"Failure: NextHopId {nexthop_id} for prefix {prefix} has an empty list in next_hop_group_members"
                    )
                else:
                    monitored_prefix_supernet_nexthop_map[prefix][nexthop_id] = (
                        next_hop_group_members[nexthop_id]
                    )
        fburl: str = await async_everpaste_str(
            str(monitored_prefix_supernet_nexthop_map), color=False
        )
        self.logger.info(f"Monitored Prefix's group & member details: {fburl}")
        return monitored_prefix_supernet_nexthop_map

    async def async_get_ecmp_groups_snapshot(
        self, raise_exception_on_validation_mismatch: bool = True
    ) -> Dict[int, EcmpGroup]:
        """
        Get the ecmp groups snapshot from the device via fboss_bcm_shell.
        Example of raw output: P1203426281.

        Returns:
            Dict[int, EcmpGroup]: Mapping of ecmp group id to EcmpGroup object
        """
        # todo(pavanpatil) use list hwobject API instead of CLI
        cmd = "fboss2 show hw-object NEXT_HOP_GROUP"
        res = await self.async_run_cmd_on_shell(cmd)
        ecmp_groups = {}
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

        for group_id in group_to_mbr_intf_map:
            ecmp_groups[group_id] = EcmpGroup(
                ecmp_group_id=group_id,
                l3_ecmp_flags="",
                max_path=-1,
                interfaces=group_to_mbr_intf_map[group_id],
            )
        if (
            parent_nhop_group_id_set != set(group_to_mbr_intf_map.keys())
            and raise_exception_on_validation_mismatch
        ):
            raise Exception(
                f"Parent NextHopGroupSaiId {parent_nhop_group_id_set} does not match with Child NextHopGroupMemberSaiId {group_to_mbr_intf_map.keys()}"
            )
        self.logger.info(f"ECMP groups used on {self.hostname}: {len(ecmp_groups)}")
        return ecmp_groups

    async def async_is_ucmp_enabled(self) -> bool:
        # TODO: Implement OSS alternative for UCMP enabled check
        raise NotImplementedError(
            "async_is_ucmp_enabled requires CoopService (Meta-internal). "
            "Will be implemented for OSS in a future update."
        )

    async def async_wedge_qsfp_util_pause_remediation(self, duration: int) -> None:
        if duration == 0:
            self.logger.info(
                f"Attempting to resume qsfp remediations on {self.hostname}."
            )
        else:
            self.logger.info(
                f"Attempting to pause qsfp remediations duration on {self.hostname} for {duration} seconds."
            )
        cmd = f"wedge_qsfp_util --pause_remediation {duration}"
        await self.async_run_cmd_on_shell(cmd)

    async def async_get_global_system_port_offset(self) -> int:
        async with self.async_agent_client as client:
            dsf_nodes = await client.getDsfNodes()
            name_to_dsf_name = {node.name: node for node in dsf_nodes.values()}
            host_dsf_node = name_to_dsf_name[to_fb_uqdn(self.hostname)]
            global_system_offset = none_throws(host_dsf_node.globalSystemPortOffset)
            return global_system_offset

    async def _async_get_dsf_interfaces_ip_address(
        self, interfaces: Optional[List[str]] = None
    ) -> Dict[str, Tuple[str, int]]:
        """
        This function returns the IP address of the DSF interfaces on the device. Our traditional way of
        mapping VLAN to IP address is not applicable for DSF devices. The DSF interfaces are not configured
        to have a VLAN. Hence, we need to use the following method.


        How to get the IP address of the DSF interfaces programmatically:
        1: Fetch the systemport range via getDsfNodes
        2: Fetch the port id of each interface via getAllPortInfo
        4. Fetch the InterfaceDetail of each interface via getAllInterfaces, which contains the ip address info
        3: Fetch the IP address for each interfaces via interface ID (dsfNode start index + port id)

        Via the CLI:
        1: "fboss2 show dsfnodes" to get the systemport range
        2: "fboss2 show port" to get the port id of each interface
        3: "ifconfig fboss<interface_id>" to get the IP address of each interface
        """
        async with self.async_agent_client as client:
            dsf_nodes = await client.getDsfNodes()
            name_to_dsf_name = {node.name: node for node in dsf_nodes.values()}
            host_dsf_node = name_to_dsf_name[to_fb_uqdn(self.hostname)]
            global_system_offset = none_throws(host_dsf_node.globalSystemPortOffset)
            all_port_info = await client.getAllPortInfo()
            interface_to_port_id = {}
            for port_info in all_port_info.values():
                interface_to_port_id[port_info.name] = port_info.portId

            interfaces = interfaces or list(interface_to_port_id.keys())

            all_interface_details = await client.getAllInterfaces()

        id_to_interface_ip_addr = {}
        for id, interface_detail in all_interface_details.items():
            for ipaddr in interface_detail.address:
                addr = ip_address(ipaddr.ip.addr)
                if addr.version == 6 and addr.is_global:
                    id_to_interface_ip_addr[id] = str(addr), ipaddr.prefixLength
                    break
        interface_to_ip_addr = {}
        for interface in interfaces:
            port_id = interface_to_port_id[interface]
            interface_id = global_system_offset + port_id
            ip_addr = id_to_interface_ip_addr.get(interface_id)
            if ip_addr:
                interface_to_ip_addr[interface] = ip_addr
            else:
                raise ValueError(
                    f"Unable to find IP address for interface {interface} (System Port ID: {interface_id}) on {self.hostname}"
                )
        return interface_to_ip_addr

    async def async_get_dsf_sessions(self) -> Sequence[DsfSessionThrift]:
        async with self.async_agent_client as client:
            return await client.getDsfSessions()

    def is_host_dsf(self) -> bool:
        prefixes = ["rdsw", "fdsw", "edsw"]
        return any(self.hostname.startswith(prefix) for prefix in prefixes)

    async def _async_get_interfaces_ipv6_address(
        self, interfaces: List[str]
    ) -> Dict[str, Tuple[str, int]]:
        ports = await self.async_get_all_port_info()
        interface_details = await self.async_get_all_interfaces()
        interface_to_vlan_id = {port.name: port.vlans[0] for port in ports.values()}
        interface_to_ip_addr = {}
        for interface in interfaces:
            interface_vlan_id = interface_to_vlan_id.get(interface)
            if not interface_vlan_id:
                raise InsufficientInputError(f"Unable to find VLAN ID for {interface}")
            interface_detail = interface_details.get(interface_vlan_id)
            if not interface_detail:
                raise InsufficientInputError(
                    f"Unable to find InterfaceDetail for VLAN {interface_vlan_id} for {interface}"
                )
            for address in interface_detail.address:
                ip_addr_obj = ipaddress.ip_address(address.ip.addr)
                if (
                    isinstance(ip_addr_obj, ipaddress.IPv6Address)
                    and ip_addr_obj.is_global
                ):
                    interface_to_ip_addr[interface] = (
                        str(ip_addr_obj),
                        int(address.prefixLength),
                    )
                    break
        return interface_to_ip_addr

    async def async_get_interfaces_ipv6_address(
        self, interfaces: List[str]
    ) -> Dict[str, Tuple[str, int]]:
        if self.is_host_dsf():
            return await self._async_get_dsf_interfaces_ip_address(interfaces)
        else:
            return await self._async_get_interfaces_ipv6_address(interfaces)

    @async_retryable(
        retries=10,
        sleep_time=30,
        exceptions=(ThriftError,),
    )
    async def monitor_advertised_networks_for_bgp_peers(
        self,
        role: Optional[str] = None,
        input_peer_addrs: Optional[List[str]] = None,
        input_peer_names: Optional[List[str]] = None,
        duration: int = 180,
        interval: int = 5,
    ) -> Dict[str, List[Tuple[str, int]]]:
        """
        Monitors the advertised networks for all RSW peers over a specified duration.
        Args:
            role (str): The role of the BGP peers to monitor.
            peer_addrs (List[str]): The IP addresses of the BGP peers to monitor.
            peer_names (List[str]): The names of the BGP peers to monitor.
            duration (int): The total duration to monitor (in seconds).
            interval (int): The interval between checks (in seconds).
        Returns:
            Dict[str, List[Tuple[float, int]]]: A dictionary with peer names as keys and
            lists of tuples containing timestamps and advertised network counts as values.
        """

        self.logger.info("Starting to monitor advertised networks for BGP peers...")

        results: Dict[str, List[Tuple[str, int]]] = {}
        end_time = time.time() + duration

        bgp_peers: List[Tuple[str, str]] = []

        async with await self._get_bgp_client() as bgp_client:
            # Get a list of all BGP neighbors
            bgp_sessions = await bgp_client.getBgpSessions()

            if role:
                self.logger.info(f"Role provided, filtering BGP peers by role {role}")
                # Use role to filter BGP peers
                bgp_peers = [
                    (bgp_session.description, bgp_session.peer_addr)
                    for bgp_session in bgp_sessions
                    if role.lower() in bgp_session.description
                ]
            elif input_peer_addrs:
                self.logger.info(
                    f"input_peer_addrs provided, filtering BGP peers by role {input_peer_addrs}"
                )
                # Use peer addresses to filter BGP peers
                bgp_peers = [
                    (bgp_session.description, bgp_session.peer_addr)
                    for bgp_session in bgp_sessions
                    if bgp_session.peer_addr in input_peer_addrs
                ]
            elif input_peer_names:
                self.logger.info(
                    f"input_peer_names provided, filtering BGP peers by role {input_peer_names}"
                )
                # Use peer names to filter BGP peers
                bgp_peers = [
                    (bgp_session.description, bgp_session.peer_addr)
                    for bgp_session in bgp_sessions
                    if bgp_session.description in input_peer_names
                ]
            else:
                self.logger.info("No input is provided, monitoring all BGP peers")

                # If no parameters are provided, use all BGP peers
                bgp_peers = [
                    (bgp_session.description, bgp_session.peer_addr)
                    for bgp_session in bgp_sessions
                ]

            while time.time() < end_time:
                timestamp = time.time()

                dt = datetime.datetime.fromtimestamp(timestamp)

                for description, peer_addr in bgp_peers:
                    key = description + "_" + peer_addr
                    if key not in results:
                        results[key] = []

                    try:
                        advertised_network = await bgp_client.getAdvertisedNetworks(
                            peer_addr
                        )
                        count = len(advertised_network)
                        results[key].append((str(dt), count))
                    except Exception as e:
                        # Log or handle the exception
                        self.logger.error(f"Error: {e}")

                await asyncio.sleep(interval)

        return results

    @async_retryable(retries=10, sleep_time=2, exceptions=(Exception,))
    async def async_get_bgp_initialization_events(
        self,
    ) -> Mapping[fboss_bgp_thrift_types.BgpInitializationEvent, int]:
        """
        This method measures the time taken for BGP to converge on a device.
        It does this by fetching the time taken for each phase of BGP convergence.
        """
        self.logger.info(f"Measuring BGP convergence time on {self.hostname}")

        async with await self._get_bgp_client() as bgp_client:
            init_events = await bgp_client.getInitializationEvents()

        self.logger.info(init_events)

        return init_events

    async def async_is_bgp_initialization_converged(self) -> bool:
        self.logger.debug(f"Checking if BGP is converged on {self.hostname}")

        async with await self._get_bgp_client() as bgp_client:
            try:
                return await bgp_client.initializationConverged()
            except Exception:
                return False

    @async_retryable(
        retries=5,
        sleep_time=200,
        exceptions=(ThriftError,),
    )
    async def is_device_ready_for_bgp_convergence_measurement(self) -> bool:
        """
        Before we start to collect the metrics, we want to ensure that the
        device's BGP process has converged and completed programming the FIB
        """

        self.logger.info(
            f"Check1: Verifying if the BGP process in {self.hostname} has converged and completed programming the FIB"
        )
        resp = await self.async_is_bgp_initialization_converged()
        if not resp:
            self.logger.info(
                f"The BGP process in {self.hostname} did not converge and complete programming the FIB"
            )
            return False

        self.logger.info(
            f"BGP has converged and completed programming the FIB in {self.hostname}."
        )

        return True

    @async_retryable(
        retries=10,
        sleep_time=30,
        exceptions=(ThriftError,),
    )
    async def monitor_bgp_rib_convergence(
        self,
        prefix: str,
        duration: int = 300,
        interval: int = 7,
    ) -> Dict[str, int]:
        """
        Measures convergence time for BGP RIB by monitoring advertised networks.
        Args:
            prefix (str): The prefix to monitor.
            duration (int): The total duration to monitor (in seconds).
            interval (int): The interval between checks (in seconds).
        Returns:
            Dict[str, int]: A dictionary with timestamps as keys and advertised network counts as values.
        """

        results: Dict[str, int] = {}

        self.logger.info(
            f"Measuring convergence time for BGP RIB with prefix {prefix}..."
        )

        if not prefix:
            self.logger.error("Prefix cannot be empty")
            return results

        end_time = time.time() + duration

        async with await self._get_bgp_client() as bgp_client:
            while time.time() < end_time:
                timestamp = time.time()

                dt = datetime.datetime.fromtimestamp(timestamp)

                try:
                    total_sub_prefixes = await bgp_client.getRibSubprefixes(prefix)
                    results[str(dt)] = len(total_sub_prefixes)
                except Exception as e:
                    # Log or handle the exception
                    self.logger.error(f"Error: {e}")

                await asyncio.sleep(interval)

        return results

    async def async_get_inferface_port_info(self, interface: str) -> PortInfoThrift:
        """
        Get the port info for a given interface
        """
        async with self.async_agent_client as client:
            all_port_info = await client.getAllPortInfo()
        for port_info in all_port_info.values():
            if port_info.name == interface:
                return port_info
        raise ValueError(f"Unable to find port info for interface {interface}")

    async def async_get_vlan_addresses(
        self, vlan_id: int, global_only: bool = False
    ) -> List[str]:
        all_interface_details = await self.async_get_all_interfaces()
        addresses = None
        for interface_detail in all_interface_details.values():
            if interface_detail.vlanId == vlan_id:
                addresses = interface_detail.address
        if not addresses:
            raise ValueError(f"Unable to find addresses for vlan {vlan_id}")

        ip_addresses_str = []
        for address in addresses:
            ip_address_obj = ipaddress.ip_address(address.ip.addr)
            if not global_only or (global_only and ip_address_obj.is_global):
                ip_addresses_str.append(f"{ip_address_obj}/{address.prefixLength}")
        return ip_addresses_str

    async def async_get_bgp_local_asn(self) -> int:
        async with await self._get_bgp_client() as bgp_client:
            bgp_local_config = await bgp_client.getBgpLocalConfig()
            return bgp_local_config.local_as_4_byte

    async def async_get_static_nexthop_group_count(
        self, prefix_str: str
    ) -> Dict[str, Union[Dict[typing.Any, typing.Any], int]]:
        async with self.async_agent_client as client:
            agent_local = await client.getRunningConfig()
            data = json.loads(agent_local)
            prefix_nexthops_map = {}
            all_static_route_data = data["staticRoutesWithNhops"]
            for element in all_static_route_data:
                if element["prefix"].startswith(prefix_str):
                    prefix_nexthops_map[element["prefix"]] = element["nexthops"]

            # Create an empty dictionary to store list values as keys and their corresponding dict keys as values
            list_value_keys = {}
            total_element_count = 0
            # Iterate over each key-value pair in the dictionary
            for key, value_list in prefix_nexthops_map.items():
                total_element_count += len(value_list)
                # Convert the list to a tuple (since lists are not hashable) and use it as a key
                value_tuple = tuple(sorted(value_list))

                # If the value tuple is already in the list_value_keys dictionary, it means the list is associated with multiple keys
                if value_tuple in list_value_keys:
                    list_value_keys[value_tuple].append(key)
                else:
                    list_value_keys[value_tuple] = [key]

            # Find and return list values associated with multiple keys
            duplicate_list_values = {
                value: keys for value, keys in list_value_keys.items() if len(keys) > 1
            }
            return {
                "Duplicate_nexthop_groups": duplicate_list_values,
                "total_member_element_count": total_element_count,
            }

    async def async_get_bgp_prefix_limit(self) -> Optional[int]:
        async with await self._get_bgp_client() as bgp_client:
            bgp_local_config = await bgp_client.getRunningConfig()
            pattern = r"switch_limit_config.*?prefix_limit\":(\d+)"
            match = re.search(pattern, bgp_local_config)
            if match:
                prefix_limit = int(match.group(1))
                return prefix_limit

    @memoize_on_app_overload()
    async def async_get_bgp_originated_routes(
        self,
    ) -> Optional[Sequence[TOriginatedRoute]]:
        async with await self._get_bgp_client() as bgp_client:
            originated = await bgp_client.getOriginatedRoutes()
            return originated

    async def async_get_bgp_originated_routes_prefixes_only(
        self,
    ) -> t.List[str]:
        prefix_list = []
        routes = await self.async_get_bgp_originated_routes()
        if routes:
            for route in routes:
                prefix_list.append(
                    f"{self.ip_ntop(route.prefix.prefix_bin)}/{route.prefix.num_bits}"
                )
        return prefix_list

    async def async_get_policy_name_for_originated_prefix(
        self,
        prefix: str,
    ) -> t.Optional[str]:
        routes = await self.async_get_bgp_originated_routes()
        if routes:
            for route in routes:
                route_readable = (
                    f"{self.ip_ntop(route.prefix.prefix_bin)}/{route.prefix.num_bits}"
                )
                if route_readable == prefix:
                    return route.policy_name
        return ""

    async def async_get_bgp_prefixes_for_given_community(
        self, asn: int, value: int
    ) -> t.List[str]:
        matched_prefixes = []
        routes = await self.async_get_bgp_originated_routes()
        if routes:
            for route in routes:
                if route.communities:
                    for community in route.communities:
                        if community.asn == asn and community.value == value:
                            matched_prefixes.append(
                                f"{self.ip_ntop(route.prefix.prefix_bin)}/{route.prefix.num_bits}"
                            )
                            break

        return matched_prefixes

    async def async_get_bgp_confed_asn(self) -> int:
        async with await self._get_bgp_client() as bgp_client:
            bgp_local_config = await bgp_client.getBgpLocalConfig()
            return bgp_local_config.local_confed_as_4_byte

    async def async_get_bgp_drain_state(self) -> t.Dict[str, t.Any]:
        """Returns BGP-level drain state from bgpcpp (getDrainState thrift).

        This is different from switch-level drain (async_is_switch_drained).
        BGP drain means bgpcpp has drain policies active, which is what
        'fboss2 show bgp summary' reports as 'BGP Switch Drain State'.
        """
        async with await self._get_bgp_client() as bgp_client:
            drain_state = await bgp_client.getDrainState()
            return {
                "drain_state": drain_state.drain_state.name
                if drain_state.drain_state is not None
                else "UNKNOWN",
                "drained_interfaces": list(drain_state.drained_interfaces)
                if drain_state.drained_interfaces
                else [],
            }

    async def async_get_all_interface_names(
        self,
    ) -> List[str]:
        async with self.async_agent_client as client:
            port_info_result = await client.getAllPortInfo()
        return [port_info.name for port_info in port_info_result.values()]

    @memoize_on_app_overload()
    async def async_get_mac_table(self) -> Sequence[L2EntryThrift]:
        async with self.async_agent_client as client:
            return await client.getL2Table()

    @memoize_on_app_overload()
    async def async_get_arp_table(self) -> Sequence[ArpEntryThrift]:
        async with self.async_agent_client as client:
            return await client.getArpTable()

    @memoize_on_app_overload()
    async def async_get_ndp_table(self) -> Sequence[NdpEntryThrift]:
        async with self.async_agent_client as client:
            return await client.getNdpTable()

    @memoize_on_app_overload()
    async def async_get_multi_switch_run_state(self) -> MultiSwitchRunState:
        async with self.async_agent_client as client:
            return await client.getMultiSwitchRunState()

    async def async_is_netos(self) -> bool:
        """
        Check if the device runs NetOS.
        OSS default: returns False. Internal mixin overrides with NetWhoAmI check.
        """
        return False

    async def async_is_mnpu(self, check_smc_tiers: bool = False) -> bool:
        # TODO: Implement for OSS. Requires detecting multi-NPU configuration
        # via thrift or config inspection instead of SMC tiers / COOP.
        raise NotImplementedError(
            "async_is_mnpu requires Meta-internal SMC tier lookup or COOP service. "
            "Not yet available in OSS. Use FbossSwitchInternal for full support."
        )

    async def async_is_multi_switch(self) -> bool:
        try:
            async with self.async_agent_client as client:
                mpnu_state = await client.getMultiSwitchRunState()
            return mpnu_state.multiSwitchEnabled
        except Exception:
            return False

    async def async_wait_for_agent_configured(
        self, timeout: int = 300, interval: int = 5
    ) -> None:
        self.logger.info(
            f"Waiting for agent to reach configured state on {self.hostname}"
        )
        end_time = time.time() + timeout
        while time.time() < end_time:
            if await self.async_is_agent_configured():
                return
            await asyncio.sleep(interval)
        self.logger.info(f"Agent has reached configured state on {self.hostname}")
        raise Exception(
            f"Agent did not reach configured state within {timeout} seconds on {self.hostname}"
        )

    async def async_is_agent_configured(self) -> bool:
        try:
            is_mnpu = await self.async_is_multi_switch()
            if is_mnpu:
                multi_switch_state = await self.async_get_multi_switch_run_state()
                return (
                    multi_switch_state.swSwitchRunState == SwitchRunState.CONFIGURED
                    and all(
                        multi_switch_state.hwIndexToRunState[hw_idx]
                        == SwitchRunState.CONFIGURED
                        for hw_idx in multi_switch_state.hwIndexToRunState
                    )
                )
            else:
                agent_state = await self.async_get_switch_run_state()
                if not agent_state:
                    return False
                return agent_state == SwitchRunState.CONFIGURED
        except Exception:
            return False

    async def async_wait_for_bgp_convergence(
        self, timeout: int = 300, interval: int = 5
    ) -> None:
        end_time = time.time() + timeout
        while time.time() < end_time:
            if await self.async_is_bgp_initialization_converged():
                return
            await asyncio.sleep(interval)
        raise Exception(f"Bgpd did not converge within {timeout} seconds")

    async def async_get_bgp_client(self) -> TBgpService:
        """
        Public accessor for the BGP thrift client.
        OSS: raises NotImplementedError (override in mixin for ServiceRouter).
        """
        return await self._get_bgp_client()

    async def async_get_interfaces_operational_state(
        self,
        interfaces: Optional[List[str]] = None,
    ) -> Dict[str, bool]:
        """
        Get operational state (up/down) for specified interfaces.

        Args:
            interfaces: List of interface names. If None, returns all interfaces.

        Returns:
            Dict mapping interface name -> True if up, False if down.
        """
        all_interfaces_info: Dict[
            str, InterfaceInfo
        ] = await self.async_get_all_interfaces_info()
        all_aggregated_interfaces = await self.async_get_all_aggregated_interfaces()

        interface_to_port_id = {
            name: info.port_id for name, info in all_interfaces_info.items()
        }
        interfaces = interfaces or list(interface_to_port_id.keys())

        port_ids = [
            interface_to_port_id[intf]
            for intf in interfaces
            if intf in interface_to_port_id
        ]
        port_status_map: Mapping[int, PortStatus] = await self.async_get_port_status()

        interface_states = {}
        for intf in interfaces:
            if intf in all_aggregated_interfaces:
                member_ports = all_aggregated_interfaces[intf]
                interface_states[intf] = all(
                    port_status_map.get(
                        interface_to_port_id.get(mp, -1), PortStatus()
                    ).up
                    for mp in member_ports
                )
            elif intf in interface_to_port_id:
                pid = interface_to_port_id[intf]
                interface_states[intf] = port_status_map.get(pid, PortStatus()).up
        return interface_states

    async def async_get_bgp_daemon_version(self) -> str:
        """
        Get the BGP daemon version from the device.

        Runs 'fboss2 show bgp version | grep Version' via SSH and parses
        the output to extract the package version string.

        Returns:
            str: BGP daemon version (e.g., "neteng.fboss.wedge_bgpd:590"),
                 or "unknown" if not found.
        """
        try:
            output = await self.async_run_cmd_on_shell(
                "fboss2 show bgp version | grep Version"
            )
            if output:
                for line in output.strip().splitlines():
                    if "Package Version:" in line:
                        return line.split("Package Version:")[-1].strip()
                    if "Version:" in line:
                        return line.split("Version:")[-1].strip()
        except Exception as ex:
            self.logger.debug(f"Failed to get BGP daemon version: {ex}")
        return "unknown"

    async def async_get_fabric_connectivity(self) -> t.Mapping[str, FabricEndpoint]:
        async with self.async_agent_client as client:
            return await client.getFabricConnectivity()

    async def async_is_switch_drained(self) -> bool:
        """Returns True if the switch is drained by Drainer"""
        async with self.async_agent_client as client:
            return await client.isSwitchDrained()

    async def async_get_actual_switch_drain_state(
        self,
    ) -> t.Mapping[int, SwitchDrainState]:
        """
        Returns DSF drain state for the switch

        In DSF, a switch goes to DRAINED state if number of enabled
        fabric links goes below minLinksToRemainInVOQDomain
        """
        async with self.async_agent_client as client:
            return await client.getActualSwitchDrainState()

    async def async_get_cpu_port_stats(self) -> CpuPortStats:
        async with self.async_agent_client as client:
            return await client.getCpuPortStats()

    @memoize_on_app_overload()
    async def async_get_route_table_by_client(
        self, client_id: int
    ) -> t.Sequence[UnicastRoute]:
        async with self.async_agent_client as client:
            return await client.getRouteTableByClient(client_id)

    @memoize_on_app_overload()
    async def async_get_route_table_details(self) -> t.Sequence[RouteDetails]:
        """
        Get route table with detailed nexthop information including interface names.

        Unlike async_get_route_table_by_client(), this returns routes with
        nexthops that have ifName populated, which is needed for traffic analysis.
        """
        async with self.async_agent_client as client:
            return await client.getRouteTableDetails()

    async def verify_if_route_is_installed(self, route: str) -> bool:
        """Route should be in the form of <ip> without the mask"""
        table = await self.async_get_route_table_by_client(FibClient.BGP.value)
        for entry in table:
            table_prefix = f"{self.ip_ntop(entry.dest.ip.addr)}"
            if table_prefix == route:
                return True

        return False

    async def get_next_hops_for_route(self, route: str) -> t.List[str]:
        """Route should be in the form of <ip>/<mask> without the mask"""
        table = await self.async_get_route_table_by_client(FibClient.BGP.value)
        for entry in table:
            address = f"{self.ip_ntop(entry.dest.ip.addr)}/{entry.dest.prefixLength}"
            if address == route:
                return [self.ip_ntop(nh.addr) for nh in entry.nextHopAddrs]

        return []

    # pyrefly: ignore [bad-override]
    async def async_enable_ports_via_ssh(
        self, interfaces: List[str], enable: bool
    ) -> None:
        subcmd = "enable" if enable else "disable"
        tasks = []
        for interface in interfaces:
            cmd = f"fboss2 set port {interface} state {subcmd}"
            tasks.append(self.async_run_cmd_on_shell(cmd))
        await asyncio.gather(*tasks)

    async def async_get_memory_total(
        self,
    ) -> int:
        return int(
            await self.async_run_cmd_on_shell(
                "cat /proc/meminfo | grep MemTotal | awk '{print $2}'"
            )
        )

    async def async_get_workload_slice_max_allocated_memory(self) -> int:
        """
        Get the max allocated memory for workload slice in bytes
        Returns:
            Integer value representing max allocated memory in bytes (e.g., 25769803776)
        """
        cmd = "cat /sys/fs/cgroup/workload.slice/memory.max"
        output = await self.async_run_cmd_on_shell(cmd)
        max_allocated_memory = int(output.strip())
        self.logger.info(
            f"Workload slice max allocated memory: {max_allocated_memory} bytes"
        )
        return max_allocated_memory

    async def async_set_port_state(self, port_id: int, enable: bool) -> None:
        async with self.async_agent_client as client:
            await client.setPortState(port_id, enable)

    async def async_get_qsfp_service_run_state(
        self,
    ) -> transceiver_types.QsfpServiceRunState:
        async with await self.async_get_qsfp_client() as client:
            return await client.getQsfpServiceRunState()

    async def async_wait_for_qsfp_service_state_active(
        self,
        timeout: int = 60,
        interval: int = 5,
    ) -> None:
        end_time = time.time() + timeout
        while time.time() < end_time:
            try:
                qsfp_run_state = await self.async_get_qsfp_service_run_state()
                if qsfp_run_state == transceiver_types.QsfpServiceRunState.ACTIVE:
                    return
            except Exception:
                continue
            finally:
                await asyncio.sleep(interval)
        raise Exception(
            f"qsfp_service did not reach active state within {timeout} seconds"
        )

    async def async_wait_for_fsdb_state_active(
        self,
        timeout: int = 10,
        interval: int = 1,
    ) -> None:
        end_time = time.time() + timeout
        while time.time() < end_time:
            try:
                async with await self.async_get_fsdb_client() as fsdb_client:
                    await (
                        fsdb_client.getAllOperPublisherInfos()
                    )  # just a random fsdb api
                    return
            except Exception:
                await asyncio.sleep(interval)
                continue
        raise Exception(
            f"fsdb did not become responsive to thrift calls within {timeout} seconds"
        )

    async def async_get_all_fsdb_subscribers(
        self,
    ) -> t.Mapping[str, t.Sequence[fsdb_types.OperSubscriberInfo]]:
        """
        Get all FSDB oper subscriber infos via the getAllOperSubscriberInfos() thrift API.
        This is the thrift equivalent of `fboss2 show fsdb subscribers`.

        Returns:
            SubscriberIdToOperSubscriberInfos: map of subscriber ID to list of OperSubscriberInfo
        """
        async with await self.async_get_fsdb_client() as fsdb_client:
            return await fsdb_client.getAllOperSubscriberInfos()

    async def async_get_fsdb_client(self, port: int = FSDB_PORT) -> FsdbService:
        """
        Gets a FSDB service client for the given host

        Arguments:
            host: The hostname to make the connection to
        Returns:
            A FsdbService thrift client
        """
        raise NotImplementedError(
            "FsdbService client not available in OSS mode. "
            "Use FbossSwitchInternal for ServiceRouter-based connection."
        )

    async def async_get_dsf_nodes(self) -> t.Mapping[int, DsfNode]:
        async with self.async_agent_client as client:
            return await client.getDsfNodes()

    @async_memoize_timed(600)
    async def async_get_dsf_cluster_switch_id_mapping(
        self,
    ) -> t.Mapping[int, str]:
        dsf_nodes = await self.async_get_dsf_nodes()
        switch_id_mapping = {
            switch_id: dsf_node.name for switch_id, dsf_node in dsf_nodes.items()
        }
        return switch_id_mapping

    async def async_get_system_ports(
        self,
    ) -> t.Mapping[int, SystemPortThrift]:
        async with self.async_agent_client as client:
            return await client.getSystemPorts()

    async def async_get_agent_config_attribute(
        self,
        attr: str,
    ) -> t.Union[str, int, float]:
        # TODO: Implement OSS alternative for agent config attribute retrieval
        raise NotImplementedError(
            "async_get_agent_config_attribute requires CoopService (Meta-internal). "
            "Will be implemented for OSS in a future update."
        )

    async def async_wait_for_disconnected_gr_hold_to_expire(
        self,
        subscriber_id: str,
        timeout: int = 300,
        interval: int = 5,
    ) -> None:
        start_time = int(time.time())
        formatted_ts = [
            time.strftime("%b %e %H:%M", time.localtime(timestamp))
            for timestamp in range(start_time, start_time + timeout, 60)
        ]
        regex = r"\(" + r"\|".join(formatted_ts) + r"\)"
        cmd = (
            f'cat /var/facebook/logs/wedge_agent.log | grep -a "{regex}.*{subscriber_id}: '
            'subscription state changed DISCONNECTED_GR_HOLD -> DISCONNECTED_GR_HOLD_EXPIRED"'
        )
        end_time = time.time() + timeout
        while time.time() < end_time:
            gr_disconnected_hold_expiry = await self.async_run_cmd_on_shell(cmd)
            if not gr_disconnected_hold_expiry:
                self.logger.debug(
                    f"GR disconnected hold towards {subscriber_id} not expired on {self.hostname}"
                )
                await asyncio.sleep(interval)
                continue
            self.logger.debug(
                f"GR disconnected hold towards {subscriber_id} expired on {self.hostname}"
            )
            return
        raise Exception(
            f"No GR disconnected hold expiry event found for {subscriber_id} within {timeout} seconds on {self.hostname} "
        )

    async def async_full_system_reboot(self) -> None:
        """
        Reboots the entire system
        """
        await self.async_run_cmd_on_shell("reboot")
        self.logger.info("Successfully initiated full system reboot.")

    async def async_get_processes_top(self) -> Dict[str, Any]:
        """
        Get process information from FBOSS device.

        Note: FBOSS doesn't provide a 'show processes top' equivalent.
        This returns basic system info from available sources.

        Returns:
            Dict[str, Any]: Basic process/system information
        """
        self.logger.warning(
            f"async_get_processes_top not fully implemented for FBOSS on {self.hostname}"
        )
        return {
            "processes": {},
            "note": "FBOSS does not have 'show processes top' equivalent",
        }

    async def async_get_static_routes(
        self, address_family: str = "both"
    ) -> dict[str, dict]:
        """
        Get static routes from FBOSS device using Thrift APIs.

        Note: This is a stub implementation for testing purposes.
        FBOSS devices typically use dynamic routing protocols rather than static routes.

        Args:
            address_family: Address family to retrieve ("ipv4", "ipv6", or "both")

        Returns:
            dict: Dictionary of static routes keyed by prefix
        """
        # Stub implementation for testing - FBOSS typically doesn't use static routes
        routes = {}
        self.logger.debug(
            "FBOSS static route retrieval not fully implemented - returning empty dict"
        )
        return routes

    # =========================================================================
    # Breeze / Open/R Thrift Diagnostic Methods
    # =========================================================================

    async def async_get_openr_spark_neighbors(self) -> Sequence:
        """
        Returns discovered Open/R Spark neighbors with state
        (ESTABLISHED/RESTART), area, interface, and RTT.
        Thrift equivalent of ``breeze spark neighbors``.
        """
        if TAAC_OSS:
            raise NotImplementedError(
                "OpenR Spark operations require Meta-internal OpenR infrastructure. "
                "Not available in OSS mode."
            )
        async with get_openr_ctrl_cpp_client(to_fb_fqdn(self.hostname)) as client:
            neighbors = await client.getNeighbors()
        self.logger.info(f"{self.hostname}: found {len(neighbors)} Spark neighbor(s)")
        return neighbors

    async def async_get_openr_lm_links(self):
        """
        Returns monitored interfaces with status, addresses, metrics,
        and overload state from Open/R Link Monitor.
        Thrift equivalent of ``breeze lm links``.
        """
        if TAAC_OSS:
            raise NotImplementedError(
                "OpenR Link Monitor operations require Meta-internal OpenR infrastructure. "
                "Not available in OSS mode."
            )
        async with get_openr_ctrl_cpp_client(to_fb_fqdn(self.hostname)) as client:
            links = await client.getInterfaces()
        self.logger.info(
            f"{self.hostname}: retrieved Link Monitor dump "
            f"({len(links.interfaceDetails)} interface(s))"
        )
        return links

    async def async_get_openr_kvstore_adj(self) -> Dict[str, Any]:
        """
        Returns the adjacency database from all nodes in every area
        from Open/R KvStore.
        Thrift equivalent of ``breeze kvstore adj``.

        Returns a dict mapping area -> Publication (KvStore key/vals
        filtered to ``adj:`` prefix).
        """
        if TAAC_OSS:
            raise NotImplementedError(
                "OpenR KvStore operations require Meta-internal OpenR infrastructure. "
                "Not available in OSS mode."
            )
        params = KeyDumpParams(keys=["adj:"])
        result: Dict[str, Any] = {}
        async with get_openr_ctrl_cpp_client(to_fb_fqdn(self.hostname)) as client:
            config = await client.getRunningConfigThrift()
            areas: Set[str] = {a.area_id for a in config.areas}
            for area in areas:
                publication = await client.getKvStoreKeyValsFilteredArea(params, area)
                result[area] = publication
        self.logger.info(f"{self.hostname}: retrieved kvstore adj for area(s) {areas}")
        return result

    async def async_get_openr_kvstore_prefixes(self) -> Dict[str, Any]:
        """
        Returns all advertised prefixes from all nodes in Open/R KvStore.
        Thrift equivalent of ``breeze kvstore prefixes``.

        Returns a dict mapping area -> Publication (KvStore key/vals
        filtered to ``prefix:`` prefix).
        """
        if TAAC_OSS:
            raise NotImplementedError(
                "OpenR KvStore operations require Meta-internal OpenR infrastructure. "
                "Not available in OSS mode."
            )
        params = KeyDumpParams(keys=["prefix:"])
        result: Dict[str, Any] = {}
        async with get_openr_ctrl_cpp_client(to_fb_fqdn(self.hostname)) as client:
            config = await client.getRunningConfigThrift()
            areas: Set[str] = {a.area_id for a in config.areas}
            for area in areas:
                publication = await client.getKvStoreKeyValsFilteredArea(params, area)
                result[area] = publication
        self.logger.info(
            f"{self.hostname}: retrieved kvstore prefixes for area(s) {areas}"
        )
        return result

    async def async_get_openr_kvstore_kv_signature(self) -> Dict[str, str]:
        """
        Returns a SHA-256 hash of the KvStore per area.  All switches in
        the same area must produce the same signature when in sync.
        Thrift equivalent of ``breeze kvstore kv-signature``.

        Returns a dict mapping area -> hex-digest signature string.
        """
        if TAAC_OSS:
            raise NotImplementedError(
                "OpenR KvStore operations require Meta-internal OpenR infrastructure. "
                "Not available in OSS mode."
            )
        import hashlib

        params = KeyDumpParams()
        result: Dict[str, str] = {}
        async with get_openr_ctrl_cpp_client(to_fb_fqdn(self.hostname)) as client:
            config = await client.getRunningConfigThrift()
            areas: Set[str] = {a.area_id for a in config.areas}
            for area in areas:
                publication = await client.getKvStoreHashFilteredArea(params, area)
                hashes = sorted(str(v.hash) for v in publication.keyVals.values())
                signature = hashlib.sha256("".join(hashes).encode()).hexdigest()
                result[area] = signature
        self.logger.info(f"{self.hostname}: kvstore kv-signature per area: {result}")
        return result

    async def async_get_openr_kvstore_peers(self) -> Dict[str, Any]:
        """
        Returns KvStore peer sync status (IDLE/SYNCING/SYNCED) per area.
        Thrift equivalent of ``breeze kvstore peers``.

        Returns a dict mapping area -> PeersMap (map<string, PeerSpec>).
        """
        if TAAC_OSS:
            raise NotImplementedError(
                "OpenR KvStore operations require Meta-internal OpenR infrastructure. "
                "Not available in OSS mode."
            )
        result: Dict[str, Any] = {}
        async with get_openr_ctrl_cpp_client(to_fb_fqdn(self.hostname)) as client:
            config = await client.getRunningConfigThrift()
            areas: Set[str] = {a.area_id for a in config.areas}
            for area in areas:
                peers = await client.getKvStorePeersArea(area)
                result[area] = peers
        self.logger.info(
            f"{self.hostname}: retrieved kvstore peers for area(s) {areas}"
        )
        return result

    async def async_get_openr_decision_routes(self):
        """
        Returns all computed routes with next-hops from the
        Open/R Decision module.
        Thrift equivalent of ``breeze decision routes``.

        Returns a RouteDatabase for this node.
        """
        if TAAC_OSS:
            raise NotImplementedError(
                "OpenR Decision operations require Meta-internal OpenR infrastructure. "
                "Not available in OSS mode."
            )
        async with get_openr_ctrl_cpp_client(to_fb_fqdn(self.hostname)) as client:
            route_db = await client.getRouteDbComputed("")
        self.logger.info(
            f"{self.hostname}: Decision computed "
            f"{len(route_db.unicastRoutes)} unicast route(s), "
            f"{len(route_db.mplsRoutes)} MPLS route(s)"
        )
        return route_db

    async def async_get_openr_decision_validate(self) -> Dict[str, Any]:
        """
        Retrieves Decision adjacency DBs, received prefix DBs, and
        initialization events for validation.
        Thrift equivalent of ``breeze decision validate``.

        Returns a dict with initialization_events, adjacency_dbs,
        and prefix_dbs.
        """
        if TAAC_OSS:
            raise NotImplementedError(
                "OpenR Decision operations require Meta-internal OpenR infrastructure. "
                "Not available in OSS mode."
            )
        async with get_openr_ctrl_cpp_client(to_fb_fqdn(self.hostname)) as client:
            init_events = await client.getInitializationEvents()
            adj_filter = AdjacenciesFilter(selectAreas=set())
            decision_adj_dbs = await client.getDecisionAdjacenciesFiltered(adj_filter)
            route_filter = ReceivedRouteFilter()
            decision_prefix_dbs = await client.getReceivedRoutesFiltered(route_filter)
        self.logger.info(
            f"{self.hostname}: Decision validate — "
            f"{len(init_events)} init event(s), "
            f"{len(decision_adj_dbs)} adj DB(s), "
            f"{len(decision_prefix_dbs)} prefix DB(s)"
        )
        return {
            "initialization_events": init_events,
            "adjacency_dbs": decision_adj_dbs,
            "prefix_dbs": decision_prefix_dbs,
        }

    async def async_get_openr_fib_routes(self):
        """
        Returns routes from the Open/R FIB module (what Open/R has
        programmed into the platform).
        Thrift equivalent of ``breeze fib routes-installed``.

        Returns a RouteDatabase.
        """
        if TAAC_OSS:
            raise NotImplementedError(
                "OpenR FIB operations require Meta-internal OpenR infrastructure. "
                "Not available in OSS mode."
            )
        async with get_openr_ctrl_cpp_client(to_fb_fqdn(self.hostname)) as client:
            route_db = await client.getRouteDb()
        self.logger.info(
            f"{self.hostname}: FIB module has "
            f"{len(route_db.unicastRoutes)} unicast route(s), "
            f"{len(route_db.mplsRoutes)} MPLS route(s)"
        )
        return route_db

    async def async_validate_openr_fib(self) -> Dict[str, Any]:
        """
        Compares Decision-computed routes vs FIB-programmed routes and
        reports mismatches.
        Thrift equivalent of ``breeze fib validate``.

        Returns a dict with decision_route_db, fib_route_db,
        missing_in_fib, extra_in_fib, and a boolean ``match`` flag.
        """
        if TAAC_OSS:
            raise NotImplementedError(
                "OpenR FIB operations require Meta-internal OpenR infrastructure. "
                "Not available in OSS mode."
            )
        async with get_openr_ctrl_cpp_client(to_fb_fqdn(self.hostname)) as client:
            decision_route_db = await client.getRouteDbComputed("")
            fib_route_db = await client.getRouteDb()

        decision_prefixes = {str(r.dest) for r in decision_route_db.unicastRoutes}
        fib_prefixes = {str(r.dest) for r in fib_route_db.unicastRoutes}
        missing_in_fib = decision_prefixes - fib_prefixes
        extra_in_fib = fib_prefixes - decision_prefixes
        match = len(missing_in_fib) == 0 and len(extra_in_fib) == 0

        self.logger.info(
            f"{self.hostname}: FIB validate — match={match}, "
            f"{len(missing_in_fib)} missing in FIB, "
            f"{len(extra_in_fib)} extra in FIB"
        )
        return {
            "decision_route_db": decision_route_db,
            "fib_route_db": fib_route_db,
            "missing_in_fib": missing_in_fib,
            "extra_in_fib": extra_in_fib,
            "match": match,
        }

    async def async_get_openr_advertised_routes(self) -> Sequence:
        """
        Returns prefixes this switch is advertising via
        Open/R PrefixManager.
        Thrift equivalent of ``breeze prefixmgr advertised-routes``.

        Returns a list of AdvertisedRouteDetail.
        """
        if TAAC_OSS:
            raise NotImplementedError(
                "OpenR PrefixManager operations require Meta-internal OpenR infrastructure. "
                "Not available in OSS mode."
            )
        async with get_openr_ctrl_cpp_client(to_fb_fqdn(self.hostname)) as client:
            route_filter = AdvertisedRouteFilter()
            advertised_routes = await client.getAdvertisedRoutesFiltered(route_filter)
        self.logger.info(
            f"{self.hostname}: PrefixManager advertising "
            f"{len(advertised_routes)} route(s)"
        )
        return advertised_routes

    async def async_validate_openr(self) -> Dict[str, Any]:
        """
        Retrieves overall Open/R health data: initialization events,
        running config, Spark neighbors, and Link Monitor state.
        Thrift equivalent of ``breeze openr validate``.

        Returns a dict with initialization_events, config, neighbors,
        and links.
        """
        if TAAC_OSS:
            raise NotImplementedError(
                "OpenR validation requires Meta-internal OpenR infrastructure. "
                "Not available in OSS mode."
            )
        async with get_openr_ctrl_cpp_client(to_fb_fqdn(self.hostname)) as client:
            init_events = await client.getInitializationEvents()
            config = await client.getRunningConfigThrift()
            neighbors = await client.getNeighbors()
            links = await client.getInterfaces()
        self.logger.info(
            f"{self.hostname}: OpenR validate — "
            f"{len(init_events)} init event(s), "
            f"{len(neighbors)} neighbor(s), "
            f"{len(links.interfaceDetails)} interface(s)"
        )
        return {
            "initialization_events": init_events,
            "config": config,
            "neighbors": neighbors,
            "links": links,
        }

    async def async_get_openr_monitor_counters(self) -> Mapping[str, int]:
        """
        Returns Open/R runtime counters (memory, CPU, SPF time, flood
        rate, etc.) via fb303.
        Thrift equivalent of ``breeze monitor counters``.
        """
        if TAAC_OSS:
            raise NotImplementedError(
                "OpenR monitor operations require Meta-internal OpenR infrastructure. "
                "Not available in OSS mode."
            )
        async with get_openr_ctrl_cpp_client(to_fb_fqdn(self.hostname)) as client:
            counters = await client.getCounters()
        self.logger.info(
            f"{self.hostname}: retrieved {len(counters)} monitor counter(s)"
        )
        return counters

    # =========================================================================
    # Open/R Thrift Action Methods (write operations)
    # =========================================================================

    async def async_set_openr_node_overload(self) -> None:
        """Set node overload (hard-drain) on this switch via OpenR Thrift."""
        if TAAC_OSS:
            raise NotImplementedError(
                "OpenR overload operations require Meta-internal OpenR infrastructure. "
                "Not available in OSS mode."
            )
        async with get_openr_ctrl_cpp_client(to_fb_fqdn(self.hostname)) as client:
            await client.setNodeOverload()
        self.logger.info(f"{self.hostname}: node overload SET")

    async def async_unset_openr_node_overload(self) -> None:
        """Clear node overload (hard-drain) on this switch via OpenR Thrift."""
        if TAAC_OSS:
            raise NotImplementedError(
                "OpenR overload operations require Meta-internal OpenR infrastructure. "
                "Not available in OSS mode."
            )
        async with get_openr_ctrl_cpp_client(to_fb_fqdn(self.hostname)) as client:
            await client.unsetNodeOverload()
        self.logger.info(f"{self.hostname}: node overload CLEARED")

    async def async_set_openr_link_overload(self, interface_name: str) -> None:
        """Set link overload on a specific interface via OpenR Thrift."""
        if TAAC_OSS:
            raise NotImplementedError(
                "OpenR overload operations require Meta-internal OpenR infrastructure. "
                "Not available in OSS mode."
            )
        async with get_openr_ctrl_cpp_client(to_fb_fqdn(self.hostname)) as client:
            await client.setInterfaceOverload(interface_name)
        self.logger.info(f"{self.hostname}: link overload SET on {interface_name}")

    async def async_unset_openr_link_overload(self, interface_name: str) -> None:
        """Clear link overload on a specific interface via OpenR Thrift."""
        if TAAC_OSS:
            raise NotImplementedError(
                "OpenR overload operations require Meta-internal OpenR infrastructure. "
                "Not available in OSS mode."
            )
        async with get_openr_ctrl_cpp_client(to_fb_fqdn(self.hostname)) as client:
            await client.unsetInterfaceOverload(interface_name)
        self.logger.info(f"{self.hostname}: link overload CLEARED on {interface_name}")

    async def async_set_openr_node_metric_increment(
        self, metric_increment: int
    ) -> None:
        """
        Increase the node-level metric by the given increment (soft-drain).
        All adjacencies on this node will have their metric increased.
        """
        if TAAC_OSS:
            raise NotImplementedError(
                "OpenR metric operations require Meta-internal OpenR infrastructure. "
                "Not available in OSS mode."
            )
        async with get_openr_ctrl_cpp_client(to_fb_fqdn(self.hostname)) as client:
            await client.setNodeInterfaceMetricIncrement(metric_increment)
        self.logger.info(
            f"{self.hostname}: node metric increment SET to {metric_increment}"
        )

    async def async_unset_openr_node_metric_increment(self) -> None:
        """Clear the node-level metric increment (undo soft-drain)."""
        if TAAC_OSS:
            raise NotImplementedError(
                "OpenR metric operations require Meta-internal OpenR infrastructure. "
                "Not available in OSS mode."
            )
        async with get_openr_ctrl_cpp_client(to_fb_fqdn(self.hostname)) as client:
            await client.unsetNodeInterfaceMetricIncrement()
        self.logger.info(f"{self.hostname}: node metric increment CLEARED")

    async def async_set_openr_link_metric_increment(
        self, interface_names: List[str], metric_increment: int
    ) -> None:
        """
        Increase the metric on specific interfaces by the given increment.
        """
        if TAAC_OSS:
            raise NotImplementedError(
                "OpenR metric operations require Meta-internal OpenR infrastructure. "
                "Not available in OSS mode."
            )
        async with get_openr_ctrl_cpp_client(to_fb_fqdn(self.hostname)) as client:
            await client.setInterfaceMetricIncrementMulti(
                interface_names, metric_increment
            )
        self.logger.info(
            f"{self.hostname}: link metric increment SET to "
            f"{metric_increment} on {interface_names}"
        )

    async def async_unset_openr_link_metric_increment(
        self, interface_names: List[str]
    ) -> None:
        """Clear the metric increment on specific interfaces."""
        if TAAC_OSS:
            raise NotImplementedError(
                "OpenR metric operations require Meta-internal OpenR infrastructure. "
                "Not available in OSS mode."
            )
        async with get_openr_ctrl_cpp_client(to_fb_fqdn(self.hostname)) as client:
            await client.unsetInterfaceMetricIncrementMulti(interface_names)
        self.logger.info(
            f"{self.hostname}: link metric increment CLEARED on {interface_names}"
        )

    async def async_openr_advertise_prefix(self, prefix: str) -> None:
        """
        Advertise a prefix via Open/R PrefixManager.
        prefix: CIDR string, e.g. "10.99.0.0/24"
        """
        if TAAC_OSS:
            raise NotImplementedError(
                "OpenR PrefixManager operations require Meta-internal OpenR infrastructure. "
                "Not available in OSS mode."
            )
        from openr.py.openr.utils.ipnetwork import ip_str_to_prefix
        from openr.thrift.Network.thrift_types import PrefixType
        from openr.thrift.Types.thrift_types import PrefixEntry

        network = ip_network(prefix, strict=False)
        prefix_entry = PrefixEntry(
            prefix=ip_str_to_prefix(prefix),
            type=PrefixType.BREEZE,
        )
        async with get_openr_ctrl_cpp_client(to_fb_fqdn(self.hostname)) as client:
            await client.advertisePrefixes([prefix_entry])
        self.logger.info(
            f"{self.hostname}: advertised prefix {prefix} via PrefixManager"
        )

    async def async_openr_withdraw_prefix(self, prefix: str) -> None:
        """
        Withdraw a prefix from Open/R PrefixManager.
        prefix: CIDR string, e.g. "10.99.0.0/24"
        """
        if TAAC_OSS:
            raise NotImplementedError(
                "OpenR PrefixManager operations require Meta-internal OpenR infrastructure. "
                "Not available in OSS mode."
            )
        from openr.py.openr.utils.ipnetwork import ip_str_to_prefix
        from openr.thrift.Network.thrift_types import PrefixType
        from openr.thrift.Types.thrift_types import PrefixEntry

        prefix_entry = PrefixEntry(
            prefix=ip_str_to_prefix(prefix),
            type=PrefixType.BREEZE,
        )
        async with get_openr_ctrl_cpp_client(to_fb_fqdn(self.hostname)) as client:
            await client.withdrawPrefixes([prefix_entry])
        self.logger.info(
            f"{self.hostname}: withdrew prefix {prefix} from PrefixManager"
        )

    async def async_add_iptables_rule(self, rule: str, ipv6: bool = False) -> None:
        """
        Add an iptables/ip6tables rule on the switch via SSH.
        rule: the rule arguments, e.g. "-I INPUT -p udp --dport 6666 -j DROP"
        """
        cmd = f"{'ip6tables' if ipv6 else 'iptables'} {rule}"
        await self.async_run_cmd_on_shell(cmd)
        self.logger.info(f"{self.hostname}: added iptables rule: {cmd}")

    async def async_remove_iptables_rule(self, rule: str, ipv6: bool = False) -> None:
        """
        Remove an iptables/ip6tables rule on the switch via SSH.
        rule: the rule arguments with -D, e.g. "-D INPUT -p udp --dport 6666 -j DROP"
        """
        cmd = f"{'ip6tables' if ipv6 else 'iptables'} {rule}"
        await self.async_run_cmd_on_shell(cmd)
        self.logger.info(f"{self.hostname}: removed iptables rule: {cmd}")

    @async_retryable(retries=30, sleep_time=2)
    async def async_wait_for_openr_initialized(self) -> Mapping[Any, int]:
        """
        Poll until Open/R reports INITIALIZED via initialization events.
        Retries up to 30 times (60 seconds) with 2-second intervals.
        Returns the initialization events dict on success.
        """
        if TAAC_OSS:
            raise NotImplementedError(
                "OpenR initialization check requires Meta-internal OpenR infrastructure. "
                "Not available in OSS mode."
            )
        async with get_openr_ctrl_cpp_client(to_fb_fqdn(self.hostname)) as client:
            init_events = await client.getInitializationEvents()
        if not init_events:
            raise RuntimeError(
                f"{self.hostname}: OpenR not yet initialized (no init events)"
            )
        self.logger.info(
            f"{self.hostname}: OpenR initialized with {len(init_events)} event(s)"
        )
        return init_events
