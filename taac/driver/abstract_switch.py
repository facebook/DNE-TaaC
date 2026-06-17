#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

import asyncio
import logging
import os
import re
import subprocess
import typing as t
import unittest
from abc import ABC, abstractmethod
from dataclasses import asdict
from ipaddress import IPv4Address, IPv4Interface, IPv6Address, IPv6Interface
from typing import DefaultDict, Dict, List, Optional, Tuple, Union

from taac.driver.driver_constants import (
    BgpPeerAction,
    BgpSessionState,
    CoreDumpFiles,
    DeviceDrainState,
    DNE_TEST_REGRESSION_FBID,
    DRAIN_UNDRAIN_TEST_TASK,
    DrainJobType,
    EcmpGroup,
    FbossSystemctlServiceName,
    FIB_COUNT_ALLOWED_OFFSET,
    GALAXY_WEDGE_RE_PATTERN,
    HwCounters,
    INTERFACE_CHECKS_RETRYABLE_TIMOUT,
    InterfaceEventState,
    InterfaceFlapMethod,
    PING_COUNT,
    PING_TIMEOUT,
    PortCounters,
    Service,
    ServiceStatusCounters,
    SwitchLldpData,
    SystemAvailability,
    SystemctlServiceName,
    SystemctlServiceStatus,
    SystemRebootMethod,
)
from taac.driver.drivers_common import (
    InterfaceStatusError,
    is_dne_test_device,
)
from taac.utils.oss_taac_lib_utils import (
    async_retryable,
    await_sync,
    ConsoleFileLogger,
    retryable,
)
from thrift.py3.exceptions import Error as ThriftError

TAAC_OSS = os.environ.get("TAAC_OSS", "").lower() in ("1", "true", "yes")

if not TAAC_OSS:
    from neteng.drainer.thrift_clients import DrainerService
    from neteng.drainer.thrift_types import Caller, DrainEntity, DrainRequest
    from servicerouter.python.sync_client import get_sr_client


class TestingException(Exception):
    pass


class FibCountFailure(Exception):
    pass


class AbstractSwitch(ABC):
    """
    Base class for FBoss/Arista/other testing
    Inherited by FbossSwitch and AristaSwitch
    """

    def __init__(self, hostname, logger: logging.Logger, *args, **kwargs) -> None:
        """
        @params:
        hostname: hostname of the Network Switch to be initialized
        logger: By default (if None), Netcastle's root logger will be used

        """
        self.hostname = hostname
        if not logger:
            raise TestingException(
                "Please provide a valid logger while initiating a driver."
            )
        self.logger = logger
        self.oob_hostname = self._generate_oob_hostname()
        self.test_case_obj = unittest.TestCase()

    def _generate_oob_hostname(self) -> str:
        splitHost = self.hostname.split(".", maxsplit=1)
        if (len(splitHost)) == 1:
            self.logger.debug(
                "OOB Hostname generation error: We can not generate a oob hostname out of: {hostname}"
            )
            return ""
        return (
            self.hostname
            if splitHost[0].endswith("-oob")
            else splitHost[0] + "-oob." + splitHost[1]
        )

    async def async_run_cmd_on_shell(
        self,
        cmd: str,
        timeout: int = 300,
        *args,
        **kwargs,
    ) -> str: ...

    @abstractmethod
    async def async_get_interfaces_status(
        self, interface_names: List[str], skip_logging: bool = False
    ) -> Dict[str, bool]:
        """
        Used to fetch the operational state of a given interface on FBOSS
        devices. True is returned if the interface is UP and False will be
        returned for UP/DOWN or DOWN/DOWN state.
        """
        ...

    async def async_get_interfaces_speed_in_Gbps(
        self,
        interface_names: Optional[List[str]] = None,
    ) -> Dict[str, int]:
        """
        Used to fetch a snapshot of the speed in Gbps of the given
        interfaces on the DUT.
        """
        ...

    @async_retryable(
        retries=30, sleep_time=5, max_duration=150, exceptions=(Exception,)
    )
    async def async_check_interface_status(self, interface_name: str, state) -> None:
        """
        Used to validate the expected interface status with the observed
        status depending on the state variable.

        @state: InterfaceEventState.STABLE|InterfaceEventState.UNSTABLE
        If the state is stable, interface_status is expected to be True
        (UP/enabled), otherwise it is expected to be False.
        """
        intf_oper_status_result = await self.async_get_interfaces_status(
            [interface_name]
        )
        intf_oper_status = intf_oper_status_result[interface_name]
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

    @async_retryable(retries=60, sleep_time=5, exceptions=(Exception,))
    async def async_check_interfaces_status(
        self, interface_names: List[str], state: bool
    ) -> None:
        """
        Used to validate the expected interface status with the observed
        status depending on the state variable.

        If the state is stable, interface_status is expected to be True
        (UP/enabled), otherwise it is expected to be False.
        """
        interfaces_oper_status = await self.async_get_interfaces_status(interface_names)
        interface_state_mismatch_map = {}
        for interface_name in interface_names:
            intf_oper_status = interfaces_oper_status[interface_name]
            if state != intf_oper_status:
                interface_state_mismatch_map[interface_name] = intf_oper_status
        if interface_state_mismatch_map:
            err_msg = f"Interface state mismatch: {interface_state_mismatch_map} on {self.hostname}: expected state: {state}"
            self.logger.error(err_msg)
            raise Exception(err_msg)

    def enable_port(
        self,
        interface_name: str,
        flap_method: InterfaceFlapMethod,
        skip_validation=False,
    ) -> bool:
        """
        Used to enable or bring up a specific interface on FBOSS as well
        Arista devices depending on the method name used. True will be
        returned if the interface was successfully enabled, else None.
        """
        ...

    def disable_port(
        self,
        interface_name: str,
        flap_method: InterfaceFlapMethod,
        skip_validation=False,
    ) -> bool:
        """
        Used to disable or shut down a specific interface on FBOSS as well
        Arista devices depending on the method name used. True will be
        returned if the interface was successfully disabled, else None.
        """
        ...

    async def async_get_all_interfaces_operational_status(
        self,
    ) -> DefaultDict[str, bool]:
        """
        Used to fetch a snapshot of the operational status of all the
        interfaces on the DUT. An active interface that is operationally
        UP will be marked as True, while it will be marked as False if
        it is down.
        """
        ...

    async def async_get_all_interfaces_admin_status(self) -> DefaultDict[str, bool]:
        """
        Used to fetch a snapshot of the admin status of all the
        interfaces on the DUT. An interface that is in ENABLED state
        will be marked as True, while it will be marked as False if
        it is DISABLED.
        """
        ...

    @async_retryable(
        retries=1000,
        sleep_time=5,
        max_duration=INTERFACE_CHECKS_RETRYABLE_TIMOUT,
        exceptions=(
            InterfaceStatusError,
            ThriftError,
        ),
    )
    async def async_check_all_ports_states(
        self, disabled_interfaces: List[str], enabled_interfaces: List[str]
    ) -> None:
        """
        Used to check if the specified disabled_interfaces are down and enabled_interfaces are up.
        If any of the interfaces is not in the desired state it raises InterfaceStatusError.
        """
        all_ports_status: Dict[
            str, bool
        ] = await self.async_get_all_interfaces_operational_status()

        failed_disabled_interfaces = [
            interface
            for interface in disabled_interfaces
            if all_ports_status[interface]
        ]
        failed_enabled_interfaces = [
            interface
            for interface in enabled_interfaces
            if not all_ports_status[interface]
        ]

        if failed_enabled_interfaces or failed_disabled_interfaces:
            msg = f"Interfaces not UP/enabled: {failed_enabled_interfaces} not DOWN/disabled: {failed_disabled_interfaces} on device: {self.hostname}"
            self.logger.info(msg)
            raise InterfaceStatusError(msg)

        self.logger.info(
            f"Successfully validated the operational status of all the ports on {self.hostname}"
        )

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
        ...

    async def async_get_above_threshold_port_stats(
        self, interface_names: List[str], threshold_value: int = 0
    ) -> List[PortCounters]:
        """
        Returns the port counter values of those interfaces that have pkt counter discards
        greater than the threshold values
        NOTE: The threshold is checked against (in|out)-(discard|error)
        """

        port_counters = await self.async_get_multiple_port_stats(interface_names)
        checked_interface_list = [
            port_counter.interface_name for port_counter in port_counters
        ]
        self.logger.debug(
            f"Port counter stats collected for {self.hostname}: {checked_interface_list}"
        )
        return [
            port_counter
            for port_counter in port_counters
            for err_discard_counter in asdict(port_counter).values()
            if isinstance(err_discard_counter, int)
            if err_discard_counter > threshold_value
        ]

    async def async_is_modular_chassis(self) -> bool:
        """
        Checks if the given device is a modular chassis or not,
        returns true if it is or false if it isn't
        """
        ...

    async def async_get_all_hw_drops(self) -> HwCounters:
        """
        Return a dict of all harware discards. The dict will contain the drop_type as the
        key and discards on every interface as values
        """
        ...

    async def async_clear_all_hw_counters(self) -> None:
        """
        Clear all harware counters on device
        """
        ...

    async def async_clear_all_port_counters(self) -> None:
        """
        Clear all port counters on device
        """
        ...

    async def async_get_specific_bgp_session_state(
        self, interface_name: str
    ) -> Dict[str, int]:
        """
        Used to obtain the number of established and non-established BGP
        (both v4 and v6) sessions on a given interface that is used to
        peer with the neighbor.

        Sample output:
            spec_bgp_neigh_state = {
                'estab_peers': <Total_num_of_established_sesssions>,
                'non_estab_peers': <Total_num_of_non_established_sesssions>,
            },
        """
        ...

    async def get_all_bgp_session_states(self) -> DefaultDict[str, int]:
        """
        Used to obtain the total number of all the established as well as
        non-established BGP (both v4 and v6 sessions) across all the
        interfaces that are up and running on a given device.

        Sample output:
            all_bgp_neigh_state = {
                'estab_peers': <Total_num_of_established_sesssions>,
                'non_estab_peers': <Total_num_of_non_established_sesssions>,
            },
        """
        ...

    async def async_get_all_bgp_peer_ip_addresses(self) -> DefaultDict[str, List[str]]:
        """
        Used to obtain the peer ip address of all the established as well as
        non-established BGP (both v4 and v6 sessions) across all the
        interfaces that are up and running on a given device.

        Sample output:
            all_bgp_neigh_state = {
                'estab_peers': <List_of_ip_addresses_of_established_sessions>,
                'non_estab_peers': <List_of_ip_addresses_of_non_established_sessions>,
            },
        """
        ...

    @retryable(num_tries=100, sleep_time=3, max_duration=500, debug=True)
    def compare_all_bgp_neighbor_states(self, bgp_sess_stable, state, **kwargs) -> None:
        """
        Used to compare the all BGP sessions (both established and
        non-established) before and after an event. The total number of BGP
        sessions (bgp_sess_stable) in the ideal, stable state (before the
        start of the test) will be used as the baseline value for comparison.

        @state: stable|unstable
        stable - enabling the linecard module, ribd agent restart, after reboot
        unstable - disabling the linecard module
        """
        if state == BgpSessionState.UNSTABLE:
            bgp_sess_unstable = await_sync(self.get_all_bgp_session_states())
            self.test_case_obj.assertGreaterEqual(
                bgp_sess_stable["estab_peers"],
                bgp_sess_unstable["estab_peers"],
                msg="Number of established BGP sessions in stable state is "
                "lesser when compared to the same in the unstable state",
            )
            self.test_case_obj.assertEqual(
                bgp_sess_stable["estab_peers"] + bgp_sess_stable["non_estab_peers"],
                bgp_sess_unstable["estab_peers"] + bgp_sess_unstable["non_estab_peers"],
                msg="Total number of BGP sessions before and after the disruption "
                "event does not match.",
            )

        elif state == BgpSessionState.STABLE:
            bgp_sess_stable_final = await_sync(self.get_all_bgp_session_states())
            total_sessions_before_disruption = (
                bgp_sess_stable["estab_peers"] + bgp_sess_stable["non_estab_peers"]
            )
            total_sessions_after_recovery = (
                bgp_sess_stable_final["estab_peers"]
                + bgp_sess_stable_final["non_estab_peers"]
            )

            # It is marked as greater than or equal to, instead of just equal to
            # bypass corner cases where in the new sessions from previous iteration
            # which took time to recover suddenly came up and becomes a part of
            # the bgp_sess_stable_final. This way we still account for those
            # new sessions
            self.test_case_obj.assertGreaterEqual(
                total_sessions_after_recovery,
                total_sessions_before_disruption,
                msg="Total number of BGP sessions before the disruptive event "
                "is less than the total sessions after the recovery event. "
                "It should be either greater than or equal to the total "
                "number of sessions after the recovery event.",
            )
            if total_sessions_after_recovery > total_sessions_before_disruption:
                self.logger.warning(
                    f"There is a total of {total_sessions_after_recovery} "
                    "sessions after the recovery event, which is more than "
                    f"the total of {total_sessions_after_recovery} sessions "
                    "before the disruptive event. This is unexpected as we "
                    "expect some new sessions unexpectedly came up during "
                    "the test. Investigate further!"
                )

            self.test_case_obj.assertGreaterEqual(
                bgp_sess_stable_final["estab_peers"],
                bgp_sess_stable["estab_peers"],
                msg="The total number of established BGP sessions before the "
                "disruptive event is greater than the total number of "
                "established sessions after recovery. It should be either "
                "lesser than or equal to the estab sessions after recovery. "
                "This means some sessions did not come up after recovery!",
            )
            if bgp_sess_stable_final["estab_peers"] > bgp_sess_stable["estab_peers"]:
                self.logger.warning(
                    "The number of established BGP sessions after the recovery "
                    "event is greater than the number of established sessions "
                    "before the disruptive event. This is not expected. Please "
                    "investigate!"
                )

    async def async_get_interface_neighbor(
        self, interface_name: str
    ) -> Optional[Tuple[str, str]]:
        """
        Return a tuple with the remote hostname and interface based on
        the interface_name if a corresponding LLDP entry is present.
        """
        ...

    def enable_agent(self, agent_name: str) -> bool:
        """
        Used to enable or restart the agent / services running on either
        FBOSS or Arista devices.

        Returns True if the agent has been successfully restarted and
        found to be in active/running state post that.

        Possible agent names for FBOSS devices:
            1. bgpd: Can be used to restart the Bgpd agent
            2. wedge_agent: Can be used to restart the Wedge agent

        Possible agent names for Arista EOS devices:
            1. 'ribd': Restart the Ribd agent on the EOS. Interface_name
                is not neededto perform this operation.
            2. 'linecard': Enable or Power up the linecard module on that
                particular chassis depending on the Interface name.
                F.ex, for Eth3/20/1, the Linecard module 3 will be enabled.

        True will be returned if the agent was enabled successfully.
        Otherwise, None will be returned.
        """
        ...

    async def async_disable_agent(self, agent_name: str, force=False) -> bool:
        """
        Used to disable or stop the agent / services running on either
        FBOSS or Arista devices.

        Returns True if the agent has been successfully stopped and
        found to be in inactive/dead state post that.

        Possible agent names for FBOSS devices that can be disabled:
            1. bgpd: Can be used to kill the Bgpd agent
            2. wedge_agent: Can be used to kill the Wedge agent

        Possible agent names for Arista EOS devices:
            1. 'ribd': Restart the Ribd agent on the EOS. Interface_name
                is not neededto perform this operation.
            2. 'linecard': Enable or Power up the linecard module on that
                particular chassis depending on the Interface name.
                F.ex, for Eth3/20/1, the Linecard module 3 will be enabled.

        True will be returned if the agent was enabled successfully.
        Otherwise, None will be returned.
        """
        ...

    def get_system_reachability_status(self) -> int:
        """
        Used to test if the test device was pingable from the devserver
        over its inband IPv6 address. Returns the return code of the ping
        command.
        Possible Output:
            Success: code 0
            No reply: code 1
            Other errors: code 2

        ping -w 'deadline' option
            Specify a timeout, in seconds, before ping exits regardless of
            how many packets have been sent or received. In this case ping
            does not stop after count packet are sent, it waits either for
            deadline expire or until count probes are answered or for some
            error notification from network.
        """
        cmd = [
            "ping6",
            "-c",
            str(PING_COUNT),
            "-w",
            str(PING_TIMEOUT),
            str(self.hostname),
        ]
        ping_rc = subprocess.call(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.logger.info(
            f"The return code of ping test to {self.hostname} is {ping_rc}"
        )
        if ping_rc != 0:
            cmd.remove(str(self.hostname))
            alt_keyword = "-inband" if type(self).__name__ == "FbossSwitch" else "-mgmt"
            # Changing name to switch between inband and oob. for example:
            # fsw001.p001.f01.snc1 to fsw001-mgmt.p001.f01.snc1
            # fsw002.p001.f01.snc1 to fsw001-inband.p001.f01.snc1
            alt_name = re.sub(r"(.sw.*?)(\..*)", rf"\1{alt_keyword}\2", self.hostname)
            self.logger.info(
                f"Pings to {self.hostname} didn't succeed. Trying {alt_name}"
            )
            cmd.append(alt_name)
            ping_rc = subprocess.call(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            self.logger.info(f"The return code of ping test to {alt_name} is {ping_rc}")
        return ping_rc

    @retryable(num_tries=30, sleep_time=10, max_duration=500, debug=True)
    def check_system_reachability(
        self, expected_state: SystemAvailability, **kwargs
    ) -> None:
        """
        Used to assert the expected reachability state of the device.
        Typically used during reboot based test cases where we would
        like to confirm if the device completely went down or came
        back up properly after reboot. This method is based on the
        return codes returned by ping test from devserver.
            Success: code 0
            No reply: code 1
            Other errors: code 2
        """
        ping_rc = self.get_system_reachability_status()
        if expected_state == SystemAvailability.REACHABLE:
            self.test_case_obj.assertEqual(
                ping_rc,
                0,
                msg=f"Invalid ping return code {ping_rc} was observed instead of "
                f"the expected value of 0 that asserts the {self.hostname} "
                f"was pingable. This could indicate the device is still down "
                f"and unreachable. Please check!",
            )
            self.logger.info(
                f"{self.hostname} is reachable as expected from the ping test!"
            )
        elif expected_state == SystemAvailability.UNREACHABLE:
            self.test_case_obj.assertNotEqual(
                ping_rc,
                0,
                msg=f"Invalid ping return code {ping_rc} was observed instead of "
                f"a non-zero return code. This could indicate the device is "
                f"reachable while we expect it to be down. Please check!",
            )
            self.logger.info(
                f"{self.hostname} is unreachable as expected from the ping test!"
            )

    def check_process_statuses(
        self,
        services: List[FbossSystemctlServiceName],
        desired_status: SystemctlServiceStatus,
    ) -> None:
        """
        Used to check status of all fboss processes

        Args:
            services: list of services to check
            desired_status: desired status of the services
        Raises:
            AssertionError: if status of any process is not as desired
        """
        failed_services: Dict[FbossSystemctlServiceName, SystemctlServiceStatus] = {}
        for service in services:
            # pyre-fixme[16]: `AbstractSwitch` has no attribute `get_service_status`.
            service_status: SystemctlServiceStatus = self.get_service_status(service)
            if service_status != desired_status:
                failed_services[service] = service_status
        self.test_case_obj.assertFalse(failed_services)

    async def async_reboot_switch(
        self,
        reboot_method: SystemRebootMethod,
        wait_till_eor: bool = False,
        skip_undrain: bool = False,
    ) -> bool:
        """
        Used to reboot either FBOSS or Arista EOS devices. True will be
        returned if the device was successfully power cycled, else None
        will be returned.
        """
        ...

    async def _get_remote_bgp_peer_addresses(
        self, interface_name: str
    ) -> List[Union[IPv4Address, IPv6Address]]:
        """
        Abstract method to return a list of Ipv4/IPv6 bgp peer addresses
        """
        ...

    @abstractmethod
    async def _async_modify_bgp_nbr(
        self,
        peer_ip_addr: Union[IPv4Address, IPv6Address],
        bgp_peer_action: BgpPeerAction,
    ) -> None:
        """
        Abstract driver method that will execute the get/set BGP peer modifications
        using the appropirate client i.e fboss bgp client, FCR for Arista etc
        """
        ...

    def disable_bgp_neighborship(self, interface_name: str) -> bool:
        """
        Used to disable/shut both the v4 and v6 BGP neighborship on
        a given specific interface in FBOSS devices.
        Args:
            interface_name: interface name to didsable bgp neighborship
            skip_validation: do not verify status after disabling
        """

        for peer_ip_addr in await_sync(
            self._get_remote_bgp_peer_addresses(interface_name)
        ):
            self.logger.info(
                f"Disabling BGP peering on interface {interface_name} "
                f"for remote peer IP {peer_ip_addr}"
            )
            await_sync(self._async_modify_bgp_nbr(peer_ip_addr, BgpPeerAction.SHUT))
        self.logger.info(
            f"Successfully disabled BGP neighborship on interface {interface_name}"
        )
        return True

    def enable_bgp_neighborship(self, interface_name: str) -> bool:
        """
        Used to enable/unshut both the v4 and v6 BGP neighborship on
        a given specific interface in FBOSS devices.
        Args:
            interface_name: interface name to enable bgp neighborship
        """
        for peer_ip_addr in await_sync(
            self._get_remote_bgp_peer_addresses(interface_name)
        ):
            self.logger.info(
                f"Enabling BGP peering on interface {interface_name} "
                f"for remote peer IP {peer_ip_addr}"
            )
            await_sync(self._async_modify_bgp_nbr(peer_ip_addr, BgpPeerAction.ENABLE))

        self.logger.info(
            f"Successfully enabled BGP neighborship on interface {interface_name}"
        )
        return True

    def restart_bgp_neighborship(self, interface_name: str) -> None:
        """
        Used to perform Graceful restart of the BGP session on the given
        interface in FBOSS devices.
        Args:
            interface_name: interface name to restart bgp peer
        """
        for peer_ip_addr in await_sync(
            self._get_remote_bgp_peer_addresses(interface_name)
        ):
            self.logger.info(
                f"Attempting to restart (GR) the BGP session on {interface_name} "
                f"for remote peer IP {peer_ip_addr}"
            )
            await_sync(self._async_modify_bgp_nbr(peer_ip_addr, BgpPeerAction.RESTART))
        self.logger.info(
            f"Successfully restarted BGP neighborship(s) on {interface_name}"
        )

    async def get_ingress_traffic_stats(
        self, ingress_interfaces: List[str]
    ) -> Dict[str, int]:
        """
        Used to find the total ingress rate for all the given interfaces.
        Note: Value in bits per second (bps) calculated over a load of 1 min
        """
        ...

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
                <egress_interface_1>: <out_bytes.rate.60_value>,
                <egress_interface_2>: <out_bytes.rate.60_value>,
            },
        """
        ...

    @retryable(num_tries=3, sleep_time=10)
    def _start_unified_drainer_request_for_test_devices(self, request) -> int:
        """
        Submits a request to the new drainer to start a drain job.
        @Args: request(DrainRequest)
        @Returns: drainer_job(int(job_id)) of the new drain job
                  submitted by the drainer.
        """
        if TAAC_OSS:
            raise NotImplementedError(
                "Unified drainer is a Meta-internal service. Not available in OSS mode."
            )
        with get_sr_client(DrainerService) as client:
            return client.start(request)

    def _start_unified_drainer_job_for_test_devices(
        self, device_name, job_type, task_number: str = "T0"
    ) -> int:
        """
        Attempt to drain a device/link using the new unified drainer_job_result
        Arguments:
            device_name: (string) Name of the device to be drained.
            job_type: DrainJobType
            undrain: (bool) True if the device needs to be undrained.
            task_number: (int) Task Number.

        Returns:
            Job ID if the drain was successful started with an exception.

        NOTE: It is important to understand that this helper functions will
              skip all the audits by default as they run mostly on test devices
              in SNC where the chances of audits (capacity or netmachine checker)
              failing is quite high
        """
        if TAAC_OSS:
            raise NotImplementedError(
                "Unified drainer is a Meta-internal service. Not available in OSS mode."
            )
        if job_type == DrainJobType.DRAIN:
            force_undrain = False
        elif job_type == DrainJobType.UNDRAIN:
            force_undrain = True
        task_number = task_number.lower().replace("t", "")

        caller = Caller(user_fbid=DNE_TEST_REGRESSION_FBID)
        entity = DrainEntity(node=device_name)
        request = DrainRequest(
            to_drain=[entity],
            caller=caller,
            task_id=int(task_number),
            # pyre-fixme[61]: `force_undrain` is undefined, or not always defined.
            force_undrain=force_undrain,
        )
        drainer_job = self._start_unified_drainer_request_for_test_devices(request)
        return drainer_job

    @is_dne_test_device
    async def async_drain_device(
        self,
        is_drainer_local: bool = False,
        interfaces: Optional[List[str]] = None,
    ) -> bool:
        """
        Used to perform a complete chassis level device drain using the
        unified drainer tool and validates if the drain job was successfully
        complete
        """

        # If it is a galaxy fsw subswitch, drain command requires the entire switch name
        # Example: fsw004-fc002.p023.f01.atn3 -> fsw004.p023.f01.atn3

        # r"(^fsw[\d]{3})(-[fl]{1}c[\d]{3})(.p[\d]{3}.f[\d]{2}.[a-z]{3}[\d])"
        # Sample subswitches: fsw004-lc101.p023.f01.atn3, fsw004-fc003.p007.f01.frc3
        match = re.match(GALAXY_WEDGE_RE_PATTERN, self.hostname)
        if match:
            self.hostname = match.group(1) + match.group(3)

        # TODO(shrutidalvi): T111407643
        # Remove local drainer service request after drainer audits
        # have been migrated to NHS
        if is_drainer_local:
            self.logger.info(
                f"Attempting to drain {self.hostname} using local drainer service"
            )
            await self.async_onbox_drain_device()
            self.logger.info(
                f"{self.hostname} was successfully drained using local drainer service"
            )
            return True
        # Draining via NDS
        self.logger.info(f"Attempting to drain {self.hostname} using NDS")
        if TAAC_OSS:
            raise NotImplementedError(
                "NDS drain requires Meta-internal drainer service. "
                "Not available in OSS mode. Use is_drainer_local=True for local drain."
            )
        from taac.internal.driver.internal_drivers_common import (
            run_drain_job,
        )

        return await run_drain_job(
            device_names=[self.hostname],
            force_undrain=False,
            task_number=DRAIN_UNDRAIN_TEST_TASK,
            caller=DNE_TEST_REGRESSION_FBID,
            device_to_interfaces_map=(
                {self.hostname: interfaces} if interfaces else None
            ),
        )

    @is_dne_test_device
    async def async_undrain_device(
        self,
        is_drainer_local: bool = False,
        interfaces: Optional[List[str]] = None,
    ) -> bool:
        """
        Used to perform a complete chassis level device undrain using the
        unified drainer tool and validates if the undrain job was successfully
        complete
        """
        # If it is a galaxy fsw subswitch, undrain command requires the entire switch name
        # Example: fsw004-fc002.p023.f01.atn3 -> fsw004.p023.f01.atn3

        # r"(^fsw[\d]{3})(-[fl]{1}c[\d]{3})(.p[\d]{3}.f[\d]{2}.[a-z]{3}[\d])"
        # Sample subswitches: fsw004-lc101.p023.f01.atn3, fsw004-fc003.p007.f01.frc3
        match = re.match(GALAXY_WEDGE_RE_PATTERN, self.hostname)
        if match:
            self.hostname = match.group(1) + match.group(3)

        # TODO(shrutidalvi): T111407643
        # Remove local drainer service request after drainer audits
        # have been migrated to NHS
        if is_drainer_local:
            self.logger.info(
                f"Attempting to undrain {self.hostname} using local drainer service."
            )
            await self.async_onbox_undrain_device()
            self.logger.info(
                f"{self.hostname} was successfully undrained using local drainer service"
            )
            return True
        # UnDraining via NDS
        self.logger.info(f"Attempting to undrain {self.hostname} using NDS")
        if TAAC_OSS:
            raise NotImplementedError(
                "NDS undrain requires Meta-internal drainer service. "
                "Not available in OSS mode. Use is_drainer_local=True for local undrain."
            )
        from taac.internal.driver.internal_drivers_common import (
            run_drain_job,
        )

        return await run_drain_job(
            device_names=[self.hostname],
            force_undrain=True,
            task_number=DRAIN_UNDRAIN_TEST_TASK,
            caller=DNE_TEST_REGRESSION_FBID,
            device_to_interfaces_map=(
                {self.hostname: interfaces} if interfaces else None
            ),
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
        ...

    ######################################
    # STRESS TEST HELPER FUNCTIONS #
    ######################################

    async def async_check_for_core_dump(
        self, start_time: float, critical_processes: Optional[List[str]] = None
    ) -> CoreDumpFiles:
        """
        Used to find the presence of core dump on the DUT that can
        indicate a potential agent crash since the given start_time.

        Args:
            start_time: Unix timestamp to filter core dumps newer than this time
            critical_processes: Optional list of critical process names. If not provided,
                              uses the driver's default critical processes list
        """
        ...

    async def stress_system_memory_cmd(
        self, n_workers: str, bytes_per_worker: str, timeout: str = "60s"
    ):
        """
        This method stressess the system memory for the given timeout period by spawing n_workers
        and allocating bytes_per_worker. The output of the command is directed
        to /dev/null. So no output is expected. To verify if the execution was successful
        run get_stress_mem_util method which returns the system memory utilization.
        """
        ...

    async def async_get_workload_slice_max_allocated_memory(self) -> int:
        """
        Get the max allocated memory for workload slice in bytes
        Returns:
            Integer value representing max allocated memory in bytes (e.g., 25769803776)
        """
        raise NotImplementedError()

    @abstractmethod
    async def async_read_file(self, file_location: str) -> str:
        """
        Asynchronously checks if the file exists at the given location
        in the switch.
        """

    @abstractmethod
    async def async_generate_everpaste_file_url(
        self, file_location: str
    ) -> Optional[str]:
        """
        This function takes a file path on the remote dut as an input argument,
        and returns an everpaste link of the content of that file.
        """

    @abstractmethod
    async def aysnc_collect_critical_core_dumps_logs(self, core_file_name: str) -> None:
        """
        Used to collect backtrace of critical core dump on the Arista DUT that can
        indicate a potential agent crash since the given start_time by
        searching under /var/core/

        """

    async def async_is_critical_core_dumps(
        self, core_dump_file: str, allow_listed_files: List[str]
    ) -> bool:
        """
        Return a list of substrings whose presence in the core files are high values signals
        """
        return any(
            key_word in core_dump_file.lower() for key_word in allow_listed_files
        )

    def get_fib_table_entries_count(self) -> int:
        """'
        Used to obtain the instantaneous number of v4 and v6 route entries
        in the FIB of a given device.
        """
        ...

    async def get_agents_uptime(self) -> Dict[str, int]:
        """
        Used to get the uptime (in seconds) for all the agents on a given
        device and output is returned as a dictionary.
        Output:
            {
                '<agent_name_1>': <uptime_in_seconds>,
                '<agent_name_2>': <uptime_in_seconds>,
            }
        """
        ...

    def get_disk_usage(self, filesystem: str) -> Optional[Tuple[int, int, int]]:
        """
        Get the disk usage for a particular file system / mount point.
        """
        ...

    def fill_disk(self, file_size: int) -> bool:
        """
        Fill the disk by creating a temporary file using fallocate.
        """
        ...

    def unfill_disk(self) -> bool:
        """
        Unfill the disk by removing a temporary file.
        """
        ...

    def get_active_port(self, neighbor_role: str = "") -> str:
        """
        Return the name of the first port that has an oper state of up.
        """
        ...

    def disable_chef(self) -> bool:
        """
        Disable Chef.
        """
        ...

    def enable_chef(self) -> bool:
        """
        Enable Chef.
        """
        ...

    async def async_count_established_bgp_sessions(self) -> int:
        """
        Count active BGP sessions.
        """
        ...

    async def shutdown_all_bgp_sessions(self) -> bool:
        """
        Shutdown all BGP sessions.
        """
        ...

    async def async_create_cold_boot_file(self) -> None: ...

    async def async_get_aggregated_interfaces(
        self,
    ) -> Optional[Dict[str, List[str]]]:
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
        return {}

    async def async_get_active_and_inactive_members_count(
        self, agg_intf_name: str
    ) -> Tuple[int, int, int]:
        """
        Used to obtain the number of active (operationally up), inactive
        member ports and min-link value for any given bundle/aggregated
        interface (Thrift object)
        """
        raise NotImplementedError()

    async def async_verify_ecmp_nexthop_group_member_count(
        self,
    ) -> int:
        raise NotImplementedError()

    def stop_service(
        self,
        service: Service,
    ) -> None:
        """
        Method to stop running a service on fboss or arista switch
        """
        asyncio.run(self.async_stop_service(service))

    def start_service(
        self,
        service: Service,
    ) -> None:
        """
        Method to start running a service on fboss or arista switch
        """
        asyncio.run(self.async_start_service(service))

    def crash_service(
        self,
        service: Service,
    ) -> None:
        """
        Method to crash running a service on fboss or arista switch
        """
        asyncio.run(self.async_crash_service(service))

    async def async_crash_service(
        self,
        service: Service,
        agents: Optional[List[str]] = None,
    ) -> None:
        raise NotImplementedError()

    async def async_restart_service(
        self,
        service: Service,
        agents: Optional[List[str]] = None,
    ) -> None:
        raise NotImplementedError()

    async def async_start_service(
        self,
        service: Service,
        agents: Optional[List[str]] = None,
    ) -> None:
        raise NotImplementedError()

    async def async_stop_service(
        self,
        service: Service,
        agents: Optional[List[str]] = None,
    ) -> None:
        raise NotImplementedError()

    def restart_service(
        self,
        service: Service,
    ) -> None:
        """
        It restarts the specific service and validates the restart process
        by comparing the service uptime before and after restart.
        """
        asyncio.run(self.async_restart_service(service))

    @abstractmethod
    async def async_register_patcher_to_shut_ports_persistently(
        self, patcher_name: str, interfaces: List[str], additional_desc=None
    ) -> None:
        """
        Used to disable a given list of interfaces on the DUT persistently.
        In other words, the interface will remain disabled even across agent
        restarts or system reboots.
        """
        ...

    @abstractmethod
    async def async_add_static_route_patcher(
        self,
        prefix_to_next_hops_map: Dict[str, List[str]],
        patcher_name: str,
        patcher_desc: str = "",
        is_patcher_name_uuid_needed: bool = True,
    ) -> str:
        """Add static route patcher on the box

        Returns:
            str: the name of the patcher
        """
        ...

    @abstractmethod
    async def async_coop_unregister_patchers(
        self, patcher_name: str, config_name: Optional[str] = None
    ) -> None:
        """Add static route patcher on the box

        Returns:
            str: the name of the patcher
        """
        ...

    @abstractmethod
    async def async_unregister_patcher_to_shut_ports_persistently(
        self, patcher_name: str, interfaces: List[str]
    ) -> None:
        """
        Used to enable a given list of interfaces on the DUT persistently.
        In other words, the interface will remain enabled even across agent
        restarts or system reboots.
        """
        ...

    async def async_get_lldp_neighbors(self) -> Dict[str, SwitchLldpData]:
        """
        Return LLDP data in format
        {eth1/1/1: SwitchLldpData('rsw001.p001.f01.abc', eth1/2/1)}
        """
        ...

    @abstractmethod
    async def async_get_fib_table_entries_count(self) -> int:
        """
        Used to obtain the instantaneous number of v4 and v6 route entries
        in the FIB of a given device.
        """
        ...

    @abstractmethod
    async def async_get_fib_table_entries(self) -> None:
        """
        Used to obtain the instantaneous v4 and v6 route entries
        in the FIB of a given device. Returns everpaste link
        """
        ...

    @abstractmethod
    async def async_get_bgp_rx_prefix_count_per_intf(self, interface_name: str) -> int:
        """
        Used to obtain the number of bgp prefixes received over the bgp neibhorships that are present on a local interface
        """

    @abstractmethod
    async def async_get_fboss_build_info_show(self) -> str:
        """
        Used to obtain the build info of the fboss agent
        """

    def get_bgp_rx_prefix_count_per_intf(self, interface: str) -> int:
        return asyncio.run(self.async_get_bgp_rx_prefix_count_per_intf(interface))

    @async_retryable(
        retries=20,
        sleep_time=6,
        max_duration=120,
        exceptions=(FibCountFailure,),
        exception_to_raise=TestingException(
            "Fib count health check raised an exception"
        ),
    )
    async def async_compare_fib_counts(
        self,
        expected_fib_count: int = 0,
        expected_rx_prefix_loss: int = 0,
    ) -> None:
        current_fib_count = await self.async_get_fib_table_entries_count()
        log_msg: str = f"Curernt fib count on device {self.hostname}: {current_fib_count}. Expected: {round((expected_fib_count - expected_rx_prefix_loss) * FIB_COUNT_ALLOWED_OFFSET)} includes Expected rx_prefix loss {expected_rx_prefix_loss} with {FIB_COUNT_ALLOWED_OFFSET} offset."
        if (
            not round(
                (expected_fib_count - expected_rx_prefix_loss)
                * FIB_COUNT_ALLOWED_OFFSET
            )
            <= current_fib_count
        ):
            self.logger.critical(log_msg)
            raise FibCountFailure(log_msg)
        else:
            self.logger.debug(log_msg)

    async def async_is_onbox_drained(self) -> DeviceDrainState:
        # RSW is not a drainable. There is no reason to
        # perform a Dapper Drain on a lab RSW
        if "rsw" in self.hostname.lower():
            return DeviceDrainState.NON_DRAINABLE
        return await self._async_is_onbox_drained_helper()

    @abstractmethod
    async def _async_is_onbox_drained_helper(self) -> DeviceDrainState: ...

    @abstractmethod
    async def async_get_ip_route(
        self, ip: str, print_interfaces: bool = True
    ) -> Optional[List[str]]:
        """
        Given a destination IPv[46] address, this method returns a list of Egress
        interfaces through which the destination can be reached.

        1) The "List[str]" is a list of interface names (e.g. ['eth1/2/1'])
        2) If the destination is unreachable, this method should
           return None
        3) By default, this method prints the egress interfaces to console,
           but can be disabled by setting print_interfaces=False
        """
        pass

    @abstractmethod
    async def async_get_processes_top(self) -> Dict[str, t.Any]:
        """
        Get process information from the device.

        Returns:
            Dict[str, Any]: JSON output containing process information including:
                - CPU and memory usage per process
                - Process metadata (PID, command, status, etc.)
        """
        ...

    @abstractmethod
    async def async_get_static_routes(
        self,
        address_family: str = "both",
        # pyrefly: ignore [bad-return]
    ) -> Dict[str, Dict]:
        """
        Get static routes from the device.

        This method retrieves static route information from the device's routing table.
        Implementation varies by vendor (Arista, Cisco, Juniper, etc.) as each has
        different CLI commands and response formats.

        Args:
            address_family: Address family to retrieve ("ipv4", "ipv6", or "both")

        Returns:
            Dict[str, Dict]: Dictionary of static routes keyed by prefix.
                           The inner dictionary contains route details specific
                           to the vendor implementation.

        Example:
            routes = await driver.async_get_static_routes("ipv4")
            # Returns: {"10.0.0.0/24": {"nexthops": [{"gateway": "10.0.1.1"}], ...}}
        """
        pass
        ...

    async def async_onbox_drain_device(self) -> None: ...

    async def async_onbox_undrain_device(self) -> None: ...

    async def async_get_multiple_sess_bgp_uptime(
        self,
    ) -> Dict[str, float]: ...

    async def async_get_interface_ipv6_address(
        self, interface_name: str
    ) -> Tuple[str, int]:
        """Fetches the ipv6 address associated with the interface.
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
        ...

    async def async_get_service_status_counters(
        self,
        service: SystemctlServiceName,
    ) -> ServiceStatusCounters:
        """
        This is a method that doesnt need to be implemented here, it is only to better support abstraction of drivers
        """
        ...

    async def async_get_ecmp_groups_snapshot(
        self, raise_exception_on_validation_mismatch=True
    ) -> Dict[int, EcmpGroup]:
        """
        Get the ecmp groups snapshot from the device.
        """
        ...

    async def async_get_all_interface_names(self) -> List[str]: ...

    async def async_enable_ports_via_ssh(
        self, interfaces: List[str], enable: bool = True
    ) -> None:
        raise NotImplementedError()

    async def async_wait_for_bgp_convergence(
        self,
        timeout: int = 300,
        interval: int = 5,
    ) -> None:
        raise NotImplementedError()

    async def async_wait_for_agent_configured(
        self,
        timeout: int = 300,
        interval: int = 5,
    ) -> None:
        raise NotImplementedError()

    async def async_restore_test_bed_connectivity(
        self,
        interfaces: List[str],
        *args,
        **kwargs,
    ) -> None:
        raise NotImplementedError()

    async def async_isolate_test_bed_connectivity(
        self,
        interfaces: List[str],
        *args,
        **kwargs,
    ) -> None:
        raise NotImplementedError()

    async def async_full_system_reboot(self) -> None:
        raise NotImplementedError()

    async def wait_for_ssh_reachable(
        self, max_duration: int = 600, sleep_time: int = 5
    ) -> None:
        raise NotImplementedError()

    @abstractmethod
    async def async_get_multiple_intfs_bgp_session_state(
        self, interface_names: List[str]
    ) -> Dict[str, Dict[str, int]]:
        """
        For the given list of interfaces, parse the BGP session stats to map each interface
        to their count of current BGP state using the async BGP client.

        This method retrieves BGP session state information for multiple interfaces,
        returning the counts of established and non-established BGP sessions per interface.
        Implementation varies by vendor (Arista, Cisco, FBOSS, etc.) as each has
        different API calls and response formats.

        Args:
            interface_names: List of interface names whose BGP session counts are needed
                           (e.g., ["Ethernet3/5/1", "FourHundredGigE0/0/0/0"])

        Returns:
            Dict[str, Dict[str, int]]: Dictionary mapping interface names to BGP session counts.
                                     Each interface maps to a dict with keys:
                                     - "estab_peers": count of established BGP sessions
                                     - "non_estab_peers": count of non-established BGP sessions

        Example:
            session_counts = await driver.async_get_multiple_intfs_bgp_session_state(
                ["Ethernet3/5/1", "Ethernet3/6/1"]
            )
            # Returns: {
            #     "Ethernet3/5/1": {"estab_peers": 2, "non_estab_peers": 0},
            #     "Ethernet3/6/1": {"estab_peers": 1, "non_estab_peers": 1}
            # }
        """
        pass

    async def get_nexthop_group_data(self) -> Dict:
        """Get nexthop group data from the switch."""
        raise NotImplementedError()

    async def extract_nexthop_group_info(
        self, data: Dict, size_filter: Optional[int] = None
    ) -> Dict:
        """Extract nexthop group info from the data with optional size filter."""
        raise NotImplementedError()

    async def classify_nexthop_groups(
        self, keys_list: Optional[List[str]] = None
    ) -> Dict[str, List[str]]:
        """Classify nexthop groups by IP version."""
        raise NotImplementedError()

    async def monitor_nexthop_routes1(
        self,
        keys_list: Optional[Dict[str, List[str]]] = None,
        poll_interval: int = 10,
        threshold_v6: int = 0,
        threshold_v4: int = 0,
        duration_minutes: int = 10,
    ) -> Dict:
        """Monitor nexthop routes until thresholds are reached."""
        raise NotImplementedError()

    async def async_get_bgp_rib_summary(self) -> Dict:
        """Get BGP RIB summary statistics."""
        raise NotImplementedError()

    async def get_route_summary(self, afi: str) -> Dict:
        """Retrieve the route summary for a given address family (v4 or v6)."""
        raise NotImplementedError()

    async def get_persistent_and_nhg_routes_from_route_summary(
        self, data: Dict
    ) -> Dict[str, List]:
        """Extract persistent static routes and static nexthop-groups from route summary data."""
        raise NotImplementedError()

    async def poll_persistent_routes(
        self, poll_interval: int = 20, duration_minutes: int = 2
    ) -> Dict[str, List[Dict]]:
        """Poll persistent routes for both IPv4 and IPv6 concurrently."""
        raise NotImplementedError()

    async def calculate_route_count_time_diff(
        self, data: Dict, direction: str = "decrease"
    ) -> Dict:
        """Calculate time difference between lowest and highest counts for each route type."""
        raise NotImplementedError()
