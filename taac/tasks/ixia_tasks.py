# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe

import ipaddress
import json
import random
import typing as t

from neteng.fboss.switch_config.ttypes import PortSpeed
from taac.ixia.ixia import Ipv4PrefixPools
from taac.tasks.base_task import BaseTask
from taac.utils.common import get_default_bgp_configs
from taac.utils.driver_factory import async_get_device_driver
from neteng.test_infra.dne.taac.utils.oss_taac_lib_utils import none_throws, retryable


class IxiaEnableDisableBgpPrefixes(BaseTask):
    NAME = "ixia_enable_disable_bgp_prefixes"

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        prefix_pool_regex = params["prefix_pool_regex"]
        prefix_start_index = params.get("prefix_start_index", 0)
        prefix_end_index = params.get("prefix_end_index")
        enable = params["enable"]
        self.configure_bgp_prefixes_active_state(
            enable, prefix_pool_regex, prefix_start_index, prefix_end_index
        )

    @retryable(num_tries=2)
    def configure_bgp_prefixes_active_state(
        self,
        active_state: bool,
        prefix_pool_regex: str,
        prefix_start_index: int = 0,
        prefix_end_index: t.Optional[int] = None,
    ) -> None:
        """
        Advertise or withdraw BGP prefixes within a specified range for matching prefix pools.

        This method controls BGP prefix advertisement by setting the active state in IXIA:
        - Active (True) = Prefixes are advertised to BGP peers
        - Inactive (False) = Prefixes are withdrawn from BGP peers

        The method operates by:
        1. Finding all prefix pools matching the provided regex pattern
        2. For each prefix pool, selecting prefixes within the specified index range
        3. Setting the active state (advertised/withdrawn) for those prefixes
        4. Applying the changes to the IXIA configuration

        The method handles both IPv4 and IPv6 prefix pools and uses modulo arithmetic
        to map prefix indices to their position within the network group multiplier.

        Args:
            active_state: True to advertise prefixes, False to withdraw them
            prefix_pool_regex: Regex pattern to match prefix pool names
            prefix_start_index: Starting index (inclusive) within the network group multiplier.
                Defaults to 0.
            prefix_end_index: Ending index (exclusive) within the network group multiplier.
                If None, uses the network group multiplier value (all remaining prefixes).
        """
        prefix_pool_obj_list = self.ixia.get_prefix_pools_by_regexes(
            prefix_pool_regex=prefix_pool_regex
        )
        for prefix_pool_obj in prefix_pool_obj_list:
            bgp_ip_route_property = (
                (prefix_pool_obj.BgpIPRouteProperty.find())
                if isinstance(prefix_pool_obj, Ipv4PrefixPools)
                else prefix_pool_obj.BgpV6IPRouteProperty.find()
            )[0]
            network_group_multiplier = self.ixia.map_prefix_pool_to_network_group(
                prefix_pool_obj
            ).Multiplier
            prefix_pool_prefix_end_index = min(
                prefix_end_index or network_group_multiplier, network_group_multiplier
            )
            active_list = bgp_ip_route_property.Active.Values
            for i in range(prefix_pool_obj.Count):
                mod = i % network_group_multiplier
                if mod >= prefix_start_index and mod < prefix_pool_prefix_end_index:
                    active_list[i] = active_state
            bgp_ip_route_property.Active.ValueList(active_list)
            self.logger.info(
                f"Configured prefixes in range {prefix_start_index} - {prefix_pool_prefix_end_index}"
                f" active state to {active_state} for {prefix_pool_obj.Name}"
            )
        self.ixia.apply_changes()


class IxiaRandomizeBgpPrefixLocalPreference(BaseTask):
    NAME = "ixia_randomize_bgp_prefix_local_preference"

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        prefix_pool_regex = params["prefix_pool_regex"]
        prefix_start_index = params.get("prefix_start_index", 0)
        prefix_end_index = params.get("prefix_end_index")
        start_value: int = params["start_value"]
        end_value: int = params["end_value"]
        prefix_pool_obj_list = self.ixia.get_prefix_pools_by_regexes(
            prefix_pool_regex=prefix_pool_regex
        )
        for prefix_pool_obj in prefix_pool_obj_list:
            self.configure_bgp_prefix_local_preference(
                prefix_pool_obj,
                start_value,
                end_value,
                prefix_start_index,
                prefix_end_index,
            )
        self.ixia.apply_changes()

    @retryable(num_tries=2)
    def configure_bgp_prefix_local_preference(
        self,
        prefix_pool_obj,
        start_value: int,
        end_value: int,
        prefix_start_index: int = 0,
        prefix_end_index: t.Optional[int] = None,
    ) -> None:
        """
        Randomize BGP local preference values for prefixes within a specified range.

        This method configures BGP prefix local preference by assigning random values
        to influence BGP path selection. Local preference is a well-known BGP attribute
        used to prefer certain paths over others within an autonomous system.

        The method operates by:
        1. Determining whether the prefix pool is IPv4 or IPv6 and accessing the
           appropriate BGP route property
        2. Selecting prefixes within the specified index range using modulo arithmetic
           to map indices to their position within the network group multiplier
        3. Assigning a random local preference value (between start_value and end_value)
           to each selected prefix
        4. Applying the updated local preference values to the IXIA configuration

        The method handles both IPv4 and IPv6 prefix pools and uses the network group
        multiplier to correctly map prefix indices.

        Args:
            prefix_pool_obj: Prefix pool object, either Ipv4PrefixPools or IPv6.
            start_value: Minimum local preference value (inclusive) for randomization.
            end_value: Maximum local preference value (exclusive) for randomization.
            prefix_start_index: Starting index (inclusive) within the network group multiplier.
                Defaults to 0.
            prefix_end_index: Ending index (exclusive) within the network group multiplier.
                If None, uses the network group multiplier value (all remaining prefixes).
        """
        bgp_ip_route_property = (
            (prefix_pool_obj.BgpIPRouteProperty.find())
            if isinstance(prefix_pool_obj, Ipv4PrefixPools)
            else prefix_pool_obj.BgpV6IPRouteProperty.find()
        )[0]
        network_group_multiplier = self.ixia.map_prefix_pool_to_network_group(
            prefix_pool_obj
        ).Multiplier
        prefix_pool_prefix_end_index = min(
            prefix_end_index or network_group_multiplier, network_group_multiplier
        )
        local_preference_values = bgp_ip_route_property.LocalPreference.Values
        for i in range(prefix_pool_obj.Count):
            mod = i % network_group_multiplier
            if mod >= prefix_start_index and mod < prefix_pool_prefix_end_index:
                random_local_preference = random.randrange(start_value, end_value)
                local_preference_values[i] = random_local_preference
        bgp_ip_route_property.LocalPreference.ValueList(local_preference_values)
        self.logger.info(
            f"Configured local preference of prefixes in range {prefix_start_index} - {prefix_pool_prefix_end_index}"
            f" to a randomized number between {start_value} and {end_value} for {prefix_pool_obj.Name}"
        )


class IxiaModifyBgpPrefixesOriginValue(BaseTask):
    NAME = "ixia_modify_bgp_prefixes_origin_value"

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        prefix_pool_regex = params["prefix_pool_regex"]
        prefix_start_index = params.get("prefix_start_index", 0)
        prefix_end_index = params.get("prefix_end_index")
        origin_value = params["origin_value"]
        prefix_pool_obj_list = self.ixia.get_prefix_pools_by_regexes(
            prefix_pool_regex=prefix_pool_regex
        )
        for prefix_pool_obj in prefix_pool_obj_list:
            self.configure_bgp_prefix_origin_value(
                prefix_pool_obj, origin_value, prefix_start_index, prefix_end_index
            )
        self.ixia.apply_changes()

    @retryable(num_tries=2)
    def configure_bgp_prefix_origin_value(
        self,
        prefix_pool_obj,
        origin_value: str,
        prefix_start_index: int = 0,
        prefix_end_index: t.Optional[int] = None,
    ) -> None:
        bgp_ip_route_property = (
            (prefix_pool_obj.BgpIPRouteProperty.find())
            if isinstance(prefix_pool_obj, Ipv4PrefixPools)
            else prefix_pool_obj.BgpV6IPRouteProperty.find()
        )[0]
        network_group_multiplier = self.ixia.map_prefix_pool_to_network_group(
            prefix_pool_obj
        ).Multiplier
        prefix_pool_prefix_end_index = min(
            prefix_end_index or network_group_multiplier,
            network_group_multiplier,
        )
        origin_value_list = bgp_ip_route_property.Origin.Values
        for i in range(prefix_pool_obj.Count):
            mod = i % network_group_multiplier
            if mod >= prefix_start_index and mod < prefix_pool_prefix_end_index:
                origin_value_list[i] = origin_value
        bgp_ip_route_property.Origin.ValueList(origin_value_list)
        self.logger.info(
            f"Configured origin of prefixes in range {prefix_start_index} - {prefix_pool_prefix_end_index}"
            f" to {origin_value} for {prefix_pool_obj.Name}"
        )


class IxiaModifyBgpPrefixesMedValue(BaseTask):
    NAME = "ixia_modify_bgp_prefixes_med_value"

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        prefix_pool_regex = params["prefix_pool_regex"]
        prefix_start_index = params.get("prefix_start_index", 0)
        prefix_end_index = params.get("prefix_end_index")
        med_value: int = params["med_value"]
        prefix_pool_obj_list = self.ixia.get_prefix_pools_by_regexes(
            prefix_pool_regex=prefix_pool_regex
        )
        for prefix_pool_obj in prefix_pool_obj_list:
            self.configure_bgp_prefix_med_value(
                prefix_pool_obj, med_value, prefix_start_index, prefix_end_index
            )
        self.ixia.apply_changes()

    @retryable(num_tries=2)
    def configure_bgp_prefix_med_value(
        self,
        prefix_pool_obj,
        med_value: int,
        prefix_start_index: int = 0,
        prefix_end_index: t.Optional[int] = None,
    ) -> None:
        """
        Configure BGP MED (Multi-Exit Discriminator) value for prefixes within a specified range.

        MED is a BGP attribute used to influence inbound traffic routing decisions from
        neighboring autonomous systems. Lower MED values are preferred over higher values.

        The method operates by:
        1. Determining whether the prefix pool is IPv4 or IPv6 and accessing the
           appropriate BGP route property
        2. Selecting prefixes within the specified index range using modulo arithmetic
           to map indices to their position within the network group multiplier
        3. Setting the MED value for each selected prefix
        4. Applying the updated MED values to the IXIA configuration

        The method handles both IPv4 and IPv6 prefix pools and uses the network group
        multiplier to correctly map prefix indices.

        Args:
            prefix_pool_obj: Prefix pool object, either Ipv4PrefixPools or IPv6.
            med_value: MED (Multi-Exit Discriminator) value to set for the prefixes. If -1, randomly select a value between 10, 100
            prefix_start_index: Starting index (inclusive) within the network group multiplier.
                Defaults to 0.
            prefix_end_index: Ending index (exclusive) within the network group multiplier.
                If None, uses the network group multiplier value (all remaining prefixes).
        """
        bgp_ip_route_property = (
            (prefix_pool_obj.BgpIPRouteProperty.find())
            if isinstance(prefix_pool_obj, Ipv4PrefixPools)
            else prefix_pool_obj.BgpV6IPRouteProperty.find()
        )[0]
        # Enable MED advertisement - this is required for MED values to be sent
        bgp_ip_route_property.EnableMultiExitDiscriminator.Single(True)
        self.logger.info(f"Enabled MED advertisement for {prefix_pool_obj.Name}")
        network_group_multiplier = self.ixia.map_prefix_pool_to_network_group(
            prefix_pool_obj
        ).Multiplier
        prefix_pool_prefix_end_index = min(
            prefix_end_index or network_group_multiplier,
            network_group_multiplier,
        )
        med_value_list = bgp_ip_route_property.MultiExitDiscriminator.Values
        for i in range(prefix_pool_obj.Count):
            mod = i % network_group_multiplier
            if mod >= prefix_start_index and mod < prefix_pool_prefix_end_index:
                if med_value < 0:
                    med_value_list[i] = random.randint(10, 100)
                else:
                    med_value_list[i] = med_value
        bgp_ip_route_property.MultiExitDiscriminator.ValueList(med_value_list)
        med_value_str = str(med_value) if med_value >= 0 else "randomly selected"
        self.logger.info(
            f"Configured MED of prefixes in range {prefix_start_index} - {prefix_pool_prefix_end_index}"
            f" to {med_value_str} for {prefix_pool_obj.Name}"
        )


class IxiaModifyBgpPrefixesCommunities(BaseTask):
    NAME = "ixia_modify_communities"

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        prefix_pool_regex = params["prefix_pool_regex"]
        count = params["count"]
        to_add = params["to_add"]
        prefix_pool_obj_list = self.ixia.get_prefix_pools_by_regexes(
            prefix_pool_regex=prefix_pool_regex
        )
        for prefix_pool_obj in prefix_pool_obj_list:
            self.configure_bgp_prefix_communities(
                prefix_pool_obj,
                count,
                to_add,
            )
        self.ixia.apply_changes()

    @retryable(num_tries=3)
    def configure_bgp_prefix_communities(
        self,
        prefix_pool_obj,
        count: int,
        to_add: bool,
    ) -> None:
        """
        Add or remove a certain count of communities.

        Args:
            prefix_pool_obj: Prefix pool object, either Ipv4PrefixPools or IPv6.
            count: Number of communities to add/remove
            to_add: Either to add or remove
            prefix_start_index: Starting index (inclusive) within the network group multiplier.
                Defaults to 0.
            prefix_end_index: Ending index (exclusive) within the network group multiplier.
                If None, uses the network group multiplier value (all remaining prefixes).
        """
        bgp_peer_obj = self.ixia.map_prefix_pool_to_bgp_peer(prefix_pool_obj)
        bgp_peer_obj.Stop()
        self.logger.info(
            f"Stopped BGP peer {bgp_peer_obj.Name} before modifying communities"
        )

        bgp_ip_route_property_list = (
            prefix_pool_obj.BgpIPRouteProperty.find()
            if isinstance(prefix_pool_obj, Ipv4PrefixPools)
            else prefix_pool_obj.BgpV6IPRouteProperty.find()
        )

        if not bgp_ip_route_property_list:
            self.logger.error(
                f"No BGP IP route property found for {prefix_pool_obj.Name}. "
                f"Is this prefix pool properly configured with BGP?"
            )
            bgp_peer_obj.Start()
            self.logger.info(f"Started BGP peer {bgp_peer_obj.Name} after error")
            return

        bgp_ip_route_property = bgp_ip_route_property_list[0]

        # Set the number of communities
        if to_add:
            bgp_ip_route_property.NoOfCommunities = (
                bgp_ip_route_property.NoOfCommunities + count
            )
        else:
            bgp_ip_route_property.NoOfCommunities = (
                bgp_ip_route_property.NoOfCommunities - count
            )

        self.logger.info(
            f"Set NoOfCommunities to {bgp_ip_route_property.NoOfCommunities} for {prefix_pool_obj.Name}"
        )

        bgp_peer_obj.Start()
        self.logger.info(
            f"Started BGP peer {bgp_peer_obj.Name} after modifying communities"
        )


class IxiaChangeAsPathLength(BaseTask):
    NAME = "ixia_change_as_path_length"

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        prefix_pool_regex = params["prefix_pool_regex"]
        as_path_length = params.get("as_path_length", 1)

        prefix_pool_obj_list = self.ixia.get_prefix_pools_by_regexes(
            prefix_pool_regex=prefix_pool_regex
        )

        for prefix_pool_obj in prefix_pool_obj_list:
            self.configure_bgp_prefix_as_path_prepend(prefix_pool_obj, as_path_length)

        self.ixia.apply_changes()

    @retryable(num_tries=2)
    def configure_bgp_prefix_as_path_prepend(
        self,
        prefix_pool_obj,
        as_path_length: int = 1,
    ) -> None:
        """
        Configure size of AS_PATH

        Args:
            prefix_pool_obj: Prefix pool object, either Ipv4PrefixPools or IPv6.
            as_path_length: Total number of AS Numbers
        """
        bgp_peer_obj = self.ixia.map_prefix_pool_to_bgp_peer(prefix_pool_obj)
        bgp_peer_obj.Stop()
        self.logger.info(
            f"Stopped BGP peer {bgp_peer_obj.Name} before modifying AS path"
        )

        bgp_ip_route_property = (
            (prefix_pool_obj.BgpIPRouteProperty.find())
            if isinstance(prefix_pool_obj, Ipv4PrefixPools)
            else prefix_pool_obj.BgpV6IPRouteProperty.find()
        )[0]
        bgp_as_path_segment_list = bgp_ip_route_property.BgpAsPathSegmentList.find()
        for bgp_as_path_segment_obj in bgp_as_path_segment_list:
            bgp_as_path_segment_obj.NumberOfAsNumberInSegment = as_path_length
            as_number_list_obj_list = bgp_as_path_segment_obj.BgpAsNumberList.find()
            for i in range(len(as_number_list_obj_list)):
                as_number_list_obj_list[i].EnableASNumber.Single(True)

        bgp_peer_obj.Start()
        self.logger.info(
            f"Started BGP peer {bgp_peer_obj.Name} after modifying AS path"
        )


class IxiaDrainUndrainBgpPeers(BaseTask):
    NAME = "ixia_drain_undrain_bgp_peers"

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        prefix_pool_regex = params["prefix_pool_regex"]
        as_numbers = params.get("as_numbers", ["65099"])
        prefix_pool_obj_list = self.ixia.get_prefix_pools_by_regexes(
            prefix_pool_regex=prefix_pool_regex
        )
        drain = params["drain"]
        prefix_pool_names = [
            prefix_pool_obj.Name for prefix_pool_obj in prefix_pool_obj_list
        ]
        self.logger.info(
            f"{'Draining' if drain else 'Undraining'} prefixes in prefix pools {prefix_pool_names}"
        )
        for prefix_pool_obj in prefix_pool_obj_list:
            self.drain_undrain_prefix_pool(
                drain,
                prefix_pool_obj,
                as_numbers,
            )
        self.ixia.apply_changes()

    def _get_as_number_and_enabled_as_number_values(
        self,
        as_number_list_obj,
    ) -> list:
        as_numbers_list = as_number_list_obj.AsNumber.Values
        last_two_octets_list = as_number_list_obj.EnableASNumber.Values
        return list(zip(as_numbers_list, last_two_octets_list))

    def configure_as_number_for_drain_undrain(
        self,
        drain: bool,
        prefix_pool_obj,
        as_numbers: t.List[str],
    ) -> None:
        """
        Configure AS numbers for drain or undrain operation on BGP route properties.
        Args:
            drain: True to configure drain AS numbers, False to undrain.
            prefix_pool_obj: Prefix pool object, either IPv4 or IPv6.
            as_numbers: List of AS numbers to apply for drain or remove for undrain.
        """
        if isinstance(prefix_pool_obj, Ipv4PrefixPools):
            bgp_ip_route_property = prefix_pool_obj.BgpIPRouteProperty.find()[0]
        else:
            bgp_ip_route_property = prefix_pool_obj.BgpV6IPRouteProperty.find()[0]
        bgp_as_path_segment_list = bgp_ip_route_property.BgpAsPathSegmentList.find()
        as_numbers_added_or_removed = set()
        for bgp_as_path_segment_obj in bgp_as_path_segment_list:
            as_number_list_obj_list = bgp_as_path_segment_obj.BgpAsNumberList.find()
            for as_number_list_obj in as_number_list_obj_list:
                if as_number_list_obj.AsNumber.Single in as_numbers:
                    as_number_list_obj.EnableASNumber.Single(drain)
                    as_numbers_added_or_removed.add(as_number_list_obj.AsNumber.Single)
        as_numbers_not_added = set(as_numbers) - as_numbers_added_or_removed
        if as_numbers_not_added:
            bgp_as_path_segment_obj.NumberOfAsNumberInSegment = (
                bgp_as_path_segment_obj.NumberOfAsNumberInSegment
                + len(as_numbers_not_added)
            )
            as_number_list_obj_list = bgp_as_path_segment_obj.BgpAsNumberList.find()
            for i, as_number in enumerate(as_numbers_not_added):
                reverse_i = -(i + 1)
                as_number_list_obj_list[reverse_i].AsNumber.Single(as_number)
                as_number_list_obj_list[reverse_i].EnableASNumber.Single(True)
        origin_value = "incomplete" if drain else "igp"
        bgp_ip_route_property.Origin.Single(origin_value)
        self.logger.info(
            f"Successfully {'drained' if drain else 'undrained'} all prefixes in "
            f"{prefix_pool_obj.Name} by {'adding' if drain else 'removing'} AS numbers {as_numbers} {'to' if drain else 'from'} AS path "
            f"and set origin value to {origin_value}"
        )

    @retryable(num_tries=2)
    def drain_undrain_prefix_pool(
        self,
        drain: bool,
        prefix_pool_obj,
        as_numbers: t.List[str],
    ) -> None:
        bgp_peer_obj = self.ixia.map_prefix_pool_to_bgp_peer(prefix_pool_obj)
        bgp_peer_obj.Stop()
        self.logger.info(
            f"Stopped BGP peer {bgp_peer_obj.Name} before configuring AS numbers"
        )
        self.configure_as_number_for_drain_undrain(drain, prefix_pool_obj, as_numbers)
        bgp_peer_obj.Start()
        self.logger.info(
            f"Started BGP peer {bgp_peer_obj.Name} after configuring AS numbers"
        )


class IxiaRestartBgpSessions(BaseTask):
    NAME = "ixia_restart_bgp_sessions"

    def get_randomized_session_indices(
        self, total_sessions: int, num_session: int
    ) -> str:
        full_range = list(range(1, total_sessions + 1))
        picked_numbers = random.sample(full_range, min(num_session, len(full_range)))
        picked_numbers.sort()
        ranges = []
        range_start = picked_numbers[0]
        range_end = range_start
        for num in picked_numbers[1:]:
            if num == range_end + 1:
                range_end = num
            else:
                ranges.append(f"{range_start}-{range_end}")
                range_start = range_end = num
        ranges.append(f"{range_start}-{range_end}")
        return ";".join(ranges) + ";"

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        bgp_peer_regex = params.get("bgp_peer_regex")
        session_indices = params.get("session_indices")
        random_session_num = params.get("random_session_num")
        bgp_peer_obj_list = self.ixia.find_bgp_peers(bgp_peer_regex)
        self.logger.info(
            f"Restarting bgp peers: {[bgp_peer_obj.Name for bgp_peer_obj in bgp_peer_obj_list]}"
        )
        for bgp_peer_obj in bgp_peer_obj_list:
            if random_session_num:
                bgp_peer_session_indices = self.get_randomized_session_indices(
                    bgp_peer_obj.Count, random_session_num
                )
            else:
                bgp_peer_session_indices = session_indices or f"1-{bgp_peer_obj.Count}"
            bgp_peer_obj.Stop(bgp_peer_session_indices)
            bgp_peer_obj.Start(bgp_peer_session_indices)
            self.logger.info(
                f"Successfully restarted sessions {bgp_peer_session_indices} of {bgp_peer_obj.Name}"
            )
        self.ixia.apply_changes()


class ConfigureIxiaInterfaces(BaseTask):
    NAME = "configure_ixia_interfaces"

    ADD_BGP_PEER_PY_FUNC_NAME = "add_bgp_peer"
    CONFIGURE_VLAN_PY_FUNC_NAME = "configure_vlans"
    CHANGE_SPEED_PY_FUNC_NAME = "change_speed"
    CHANGE_PORT_ADMIN_STATE_PY_FUNC_NAME = "change_port_admin_state"

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        port_configs = params["port_configs"]
        hostname = params["hostname"]
        driver = await async_get_device_driver(hostname)
        for port_config in port_configs:
            interface = port_config["interface"]
            ip_address = port_config["ip_address"]
            remote_as_4_byte = port_config["remote_as_4_byte"]
            peer_group_name = port_config["peer_group_name"]
            speed_in_gbps = port_config.get("speed_in_gbps")
            profile_id = port_config.get("profile_id")
            mtu = port_config.get("mtu", 9000)
            ip_interface = ipaddress.ip_interface(ip_address)
            add_bgp_peer_kwargs = {
                "remote_as_4_byte": str(remote_as_4_byte),
                "peer_group_name": peer_group_name,
                "local_addr": str(ip_interface.ip),
                "peer_addr": str(ip_interface.network),
                "description": f"Ixia {interface} peer",
            }
            # pyre-fixme[16]: `AbstractSwitch` has no attribute
            #  `async_get_all_interfaces_info`.
            interface_info = (await driver.async_get_all_interfaces_info())[interface]
            port_num = interface_info.port_id
            vlan_id = interface_info.vlan_id
            vlan_name = f"vlan{vlan_id}"
            configure_vlan_kwargs = {
                vlan_name: json.dumps(
                    {
                        "ports": [port_num],
                        "vlan_id": vlan_id,
                        "mtu": mtu,
                        "ip_addresses": [ip_address],
                    }
                )
            }
            for config in get_default_bgp_configs(hostname):
                # pyre-fixme[16]: `AbstractSwitch` has no attribute
                #  `async_register_python_patcher`.
                await driver.async_register_python_patcher(
                    config,
                    f"add_bgp_peer_{interface}",
                    self.ADD_BGP_PEER_PY_FUNC_NAME,
                    add_bgp_peer_kwargs,
                )
            # pyrefly: ignore [missing-attribute]
            await driver.async_register_python_patcher(
                "agent",
                f"configure_vlan_{interface}",
                self.CONFIGURE_VLAN_PY_FUNC_NAME,
                configure_vlan_kwargs,
            )
            if speed_in_gbps and profile_id:
                speed_name = PortSpeed._VALUES_TO_NAMES.get(speed_in_gbps * 1000)
                if not speed_name:
                    self.logger.error(
                        f"Invalid speed {speed_in_gbps}. Skipping speed configuration."
                    )
                    continue
                change_speed_kwargs = {
                    "intfs": interface,
                    "speed": speed_name,
                    "profile_id": profile_id,
                }
                # pyrefly: ignore [missing-attribute]
                await driver.async_register_python_patcher(
                    "agent",
                    f"change_speed_{interface}_{speed_in_gbps}G_{profile_id}",
                    self.CHANGE_SPEED_PY_FUNC_NAME,
                    change_speed_kwargs,
                )
            else:
                self.logger.info(
                    f"Speed and profile_id not provided for {interface}, Skipping speed configuration."
                )
        change_port_admin_state_kwargs = {
            port_config["interface"]: "enable" for port_config in port_configs
        }
        # pyrefly: ignore [missing-attribute]
        await driver.async_register_python_patcher(
            "agent",
            "change_ixia_port_admin_state",
            self.CHANGE_PORT_ADMIN_STATE_PY_FUNC_NAME,
            change_port_admin_state_kwargs,
        )


class IxiaSetBgpPrefixesLocalPreference(BaseTask):
    NAME = "ixia_set_bgp_prefixes_local_preference"

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        prefix_pool_regex = params["prefix_pool_regex"]
        local_pref_value = params["local_pref_value"]
        prefix_start_index = params.get("prefix_start_index", 0)
        prefix_end_index = params.get("prefix_end_index")

        prefix_pool_obj_list = self.ixia.get_prefix_pools_by_regexes(
            prefix_pool_regex=prefix_pool_regex
        )
        for prefix_pool_obj in prefix_pool_obj_list:
            self.configure_bgp_peer_local_preference(
                prefix_pool_obj,
                local_pref_value,
                prefix_start_index,
                prefix_end_index,
            )
        self.ixia.apply_changes()

    @retryable(num_tries=2)
    def configure_bgp_peer_local_preference(
        self,
        prefix_pool_obj,
        local_pref_value: int,
        prefix_start_index: int = 0,
        prefix_end_index: t.Optional[int] = None,
    ) -> None:
        """
        Configure BGP local preference for prefixes within a specified range.

        This method modifies the local preference attribute for prefixes in the
        specified prefix pool. Local preference is a well-known BGP attribute
        used to prefer certain paths over others within an autonomous system.

        The method operates by:
        1. Determining whether the prefix pool is IPv4 or IPv6 and accessing the
           appropriate BGP route property
        2. Selecting prefixes within the specified index range using modulo arithmetic
           to map indices to their position within the network group multiplier
        3. Setting the local preference value for each selected prefix
        4. Applying the updated local preference values to the IXIA configuration

        Args:
            prefix_pool_obj: Prefix pool object, either Ipv4PrefixPools or IPv6.
            local_pref_value: Local preference value to set
            prefix_start_index: Starting index (inclusive) within the network group multiplier.
                Defaults to 0.
            prefix_end_index: Ending index (exclusive) within the network group multiplier.
                If None, uses the network group multiplier value (all remaining prefixes).
        """
        bgp_peer_obj = self.ixia.map_prefix_pool_to_bgp_peer(prefix_pool_obj)

        bgp_ip_route_property = (
            (prefix_pool_obj.BgpIPRouteProperty.find())
            if isinstance(prefix_pool_obj, Ipv4PrefixPools)
            else prefix_pool_obj.BgpV6IPRouteProperty.find()
        )[0]

        network_group_multiplier = self.ixia.map_prefix_pool_to_network_group(
            prefix_pool_obj
        ).Multiplier
        prefix_pool_prefix_end_index = min(
            prefix_end_index or network_group_multiplier, network_group_multiplier
        )

        local_preference_values = bgp_ip_route_property.LocalPreference.Values
        for i in range(prefix_pool_obj.Count):
            mod = i % network_group_multiplier
            if mod >= prefix_start_index and mod < prefix_pool_prefix_end_index:
                local_preference_values[i] = local_pref_value

        bgp_ip_route_property.LocalPreference.ValueList(local_preference_values)

        self.logger.info(
            f"Configured local preference to {local_pref_value} for prefixes in range "
            f"{prefix_start_index}-{prefix_pool_prefix_end_index} of {prefix_pool_obj.Name} "
            f"(BGP peer: {bgp_peer_obj.Name})"
        )


class IxiaPacketCaptureTask(BaseTask):
    NAME = "ixia_packet_capture"

    # Store vport_href and pcap_path for stop/save/verify operations
    _vport_href_storage: t.Dict[str, str] = {}
    _pcap_path_storage: t.Dict[str, str] = {}

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        """
        Manage IXIA packet capture lifecycle.

        This task handles starting, stopping, and saving packet captures on IXIA ports.
        It captures at the BGP monitor (IXIA side) for accurate convergence measurement.

        Args (from params dict):
            hostname: Device hostname (for interface lookup)
            interface: Interface name on device
            mode: "start", "stop", or "save"
            capture_filter: BPF filter (default: "tcp port 179")
            pcap_filename: Filename for saved PCAP (for save mode)
            capture_id: Unique ID to track vport_href across steps
        """
        mode = params["mode"]
        hostname = params["hostname"]
        interface = params["interface"]
        capture_id = params.get("capture_id", f"{hostname}:{interface}")

        ixia = none_throws(self.ixia)

        if mode == "start":
            # Default: no filter, capture all packets (tshark filters during analysis)
            capture_filter = params.get("capture_filter", "")

            if capture_filter:
                self.logger.info(
                    f"Starting IXIA packet capture on {hostname}:{interface} "
                    f"with filter '{capture_filter}'"
                )
            else:
                self.logger.info(
                    f"Starting IXIA packet capture on {hostname}:{interface} "
                    f"(capturing all packets - tshark will filter during analysis)"
                )

            vport_href = ixia.start_packet_capture(
                hostname=hostname,
                interface=interface,
                capture_filter=capture_filter,
            )

            # Store vport_href for later use
            IxiaPacketCaptureTask._vport_href_storage[capture_id] = vport_href

            self.logger.info(f"IXIA packet capture started, vport_href: {vport_href}")

        elif mode == "stop":
            vport_href = IxiaPacketCaptureTask._vport_href_storage.get(capture_id)
            if not vport_href:
                raise ValueError(
                    f"No vport_href found for capture_id '{capture_id}'. "
                    "Did you start capture first?"
                )

            self.logger.info(f"Stopping IXIA packet capture (vport: {vport_href})")
            ixia.stop_packet_capture(vport_href)
            self.logger.info("IXIA packet capture stopped")

        elif mode == "save":
            vport_href = IxiaPacketCaptureTask._vport_href_storage.get(capture_id)
            if not vport_href:
                raise ValueError(
                    f"No vport_href found for capture_id '{capture_id}'. "
                    "Did you start capture first?"
                )

            pcap_filename = params.get("pcap_filename", "bgp_capture.pcap")

            self.logger.info(
                f"Saving IXIA packet capture to {pcap_filename} (vport: {vport_href})"
            )
            pcap_path = ixia.save_capture_to_pcap(vport_href, pcap_filename)
            self.logger.info(f"IXIA packet capture saved to {pcap_path}")

            # Store pcap_path for later retrieval by verification step
            IxiaPacketCaptureTask._pcap_path_storage[pcap_filename] = pcap_path

            # Clean up stored vport_href
            del IxiaPacketCaptureTask._vport_href_storage[capture_id]

        else:
            raise ValueError(
                f"Invalid mode: {mode}. Must be 'start', 'stop', or 'save'"
            )


class InvokeIxiaApiTask(BaseTask):
    NAME = "invoke_ixia_api"

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        """
        Invoke an IXIA API method with the specified parameters.

        Expected params:
        - api_name: The name of the IXIA API method to call
        - args_json: JSON string containing the arguments for the API method
        """
        ixia = none_throws(self.ixia)
        api_name = params["api_name"]
        api_func = getattr(ixia, api_name)
        if not api_func:
            raise ValueError(f"Invalid ixia API name: {api_name}")
        args = json.loads(params.get("args_json", "{}"))
        assert isinstance(args, dict), (
            f"Invalid args_json: {args}: {type(args)}. Args must be a dict"
        )
        api_func(**args)
