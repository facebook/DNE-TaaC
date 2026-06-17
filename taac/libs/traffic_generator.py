# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import asyncio
import copy
import itertools
import json
import typing as t

from ixia.ixia import types as ixia_types
from taac.constants import (
    DEFAULT_PREFIX_LEN_V4,
    DEFAULT_PREFIX_LEN_V6,
    DEVICE_ROLE_IXIA_ASN_MAP,
    IXIA_GATEWAY_IP_INCREMENT_V4,
    IXIA_GATEWAY_IP_INCREMENT_V6,
    IXIA_PREFIX_STEP_IP_V4,
    IXIA_PREFIX_STEP_IP_V6,
    IXIA_STARTING_IP_INCREMENT_V4,
    IXIA_STARTING_IP_INCREMENT_V6,
    IxiaEndpointInfo,
    LABS_WITH_INBAND_CONNECTIVITY,
)
from taac.driver.driver_constants import InterfaceEventState
from taac.ixia.taac_ixia import TaacIxia
from taac.libs.ixia_config_cache_manager import (
    IxiaConfigCacheManager,
)
from taac.utils.common import get_session_info
from taac.utils.driver_factory import async_get_device_driver
from taac.utils.ixia_utils import (
    async_create_optical_switch_ixia_connection_assets,
    async_get_ixia_logical_port,
    fetch_ixia_password,
    get_attr_value,
    get_next_available_ipv6_address,
)
from taac.utils.oss_taac_constants import (
    EmptyOutputError,
    InsufficientInputError,
    IxiaTestSetupError,
    TAAC_OSS,
)
from taac.utils.oss_taac_lib_utils import (
    async_memoize_timed,
    async_retryable,
    ConsoleFileLogger,
    get_root_logger,
    none_throws,
    retryable,
    string_is_ip,
)
from taac.utils.serf_utils import (
    async_get_hostname_from_ip,
    async_get_ip_from_hostname,
    async_get_serf_device_mac_address,
)
from taac.utils.skynet_utils import get_skynet_device_role
from taac.test_as_a_config import types as taac_types


def mac_to_ipv6_link_local(mac: str) -> str:
    """
    Convert a MAC address to an IPv6 link-local address using EUI-64.

    Args:
        mac: MAC address in colon-separated format (e.g., "b6:db:91:95:fe:2e")

    Returns:
        IPv6 link-local address (e.g., "fe80::b4db:91ff:fe95:fe2e")
    """
    octets = [int(b, 16) for b in mac.split(":")]
    # Flip the 7th bit (Universal/Local bit) of the first octet
    octets[0] ^= 0x02
    # Insert FF:FE in the middle to form EUI-64
    eui64 = octets[:3] + [0xFF, 0xFE] + octets[3:]
    # Group into 4 pairs of 2 bytes each for IPv6 format
    groups = []
    for i in range(0, 8, 2):
        groups.append(f"{eui64[i]:02x}{eui64[i + 1]:02x}")
    return f"fe80::{groups[0]}:{groups[1]}:{groups[2]}:{groups[3]}"


DEFAULT_DEVICE_GROUP_CONFIG = taac_types.DeviceGroupConfig(
    device_group_index=0,
    v6_addresses_config=taac_types.IpAddressesConfig(),
)


class TrafficGenerator:
    def __init__(
        self,
        endpoints: t.List[taac_types.Endpoint],
        basset_pool: t.Optional[str] = None,
        session_name: t.Optional[str] = None,
        primary_chassis_ip: t.Optional[str] = None,
        cleanup_config: bool = True,
        tear_down_session: bool = True,
        session_id: t.Optional[int] = None,
        override_traffic_items: bool = False,
        cleanup_failed_setup: bool = True,
        basic_traffic_item_configs: t.Optional[
            t.Sequence[taac_types.BasicTrafficItemConfig]
        ] = None,
        user_defined_traffic_items: t.Optional[
            t.Sequence[ixia_types.TrafficItem]
        ] = None,
        basic_port_configs: t.Optional[t.Sequence[taac_types.BasicPortConfig]] = None,
        default_basic_port_config: t.Optional[taac_types.BasicPortConfig] = None,
        snake_configs: t.Optional[t.Sequence[taac_types.SnakeConfig]] = None,
        ptp_configs: t.Optional[t.Sequence[ixia_types.PTPConfig]] = None,
        logger: t.Optional[ConsoleFileLogger] = None,
        skip_advertised_prefixes_check: t.Optional[bool] = None,
        skip_ixia_protocol_verification: bool = False,
        ixia_protocol_verification_timeout: int = 90,
        ixia_config_cache: t.Optional[taac_types.IxiaConfigCache] = None,
        ixia_recovery: t.Optional[taac_types.IxiaRecovery] = None,
        *args,
        **kwargs,
    ) -> None:
        self.endpoints = endpoints
        self.name_to_endpoint = {endpoint.name: endpoint for endpoint in self.endpoints}
        self.endpoint_names = list(self.name_to_endpoint.keys())
        self.primary_chassis_ip = primary_chassis_ip
        self.cleanup_config: bool = cleanup_config
        self.session_id = session_id
        self.tear_down_session = tear_down_session
        self.cleanup_failed_setup = cleanup_failed_setup
        self.override_traffic_items = override_traffic_items
        self.ixia: TaacIxia = None  # pyre-ignore[8]
        self.logger = logger or get_root_logger()
        self.session_name = session_name
        self.basic_traffic_item_configs = basic_traffic_item_configs or []

        self.default_basic_port_config = (
            default_basic_port_config
            or taac_types.BasicPortConfig(
                device_group_configs=[DEFAULT_DEVICE_GROUP_CONFIG]
            )
        )
        self.basic_port_configs = basic_port_configs
        self.basset_pool = basset_pool
        self.user_defined_traffic_items = user_defined_traffic_items or []
        self.ptp_configs = ptp_configs or []
        self.skip_advertised_prefixes_check = skip_advertised_prefixes_check
        self.skip_ixia_protocol_verification = skip_ixia_protocol_verification
        self.ixia_protocol_verification_timeout = ixia_protocol_verification_timeout
        # Opt-in IXIA topology cache — see IxiaConfigCache Thrift docstring
        self.ixia_config_cache = ixia_config_cache
        # Opt-in IXIA REST API soft recovery — see IxiaRecovery Thrift docstring
        self.ixia_recovery = ixia_recovery
        # snake testing
        self.snake_configs = snake_configs or []
        self.is_standalone = bool(self.snake_configs)

        self._port_configs: t.List[ixia_types.PortConfig] = []
        self._traffic_items: t.List[ixia_types.TrafficItem] = []

    def teardown_ixia_setup(self) -> None:
        if not self.ixia:
            raise EmptyOutputError(
                "Missing IXIA instance while attempting to teardown the setup"
            )
        is_existing_session = bool(self.session_id)
        if not is_existing_session:
            self.ixia.tear_down()

    def get_session_name(self) -> str:
        """
        Returned string comprises of Group-id and unixname each separated by ":".
        This will be used as session name during the Ixia set-up
        """
        session_info = get_session_info()
        group_id = session_info["group_id"]
        unixname = session_info["unixname"]
        if self.session_name:
            session_name = f"{unixname}:{self.session_name}:{group_id[:8]}"
        else:
            session_name = f"{unixname}:{group_id[:8]}"
        return session_name[:64]

    def dc_has_inband_connectivity(
        self,
    ) -> bool:
        """
        return True if the datacenter that the test devices are in has inband connectivity
        """
        for endpoint in self.endpoints:
            if any(dc in endpoint.name for dc in LABS_WITH_INBAND_CONNECTIVITY):
                return True
        return False

    async def async_update_endpoint(
        self, endpoint: taac_types.Endpoint
    ) -> taac_types.Endpoint:
        if not endpoint.mac_address:
            return endpoint(
                mac_address=await async_get_serf_device_mac_address(endpoint.name)
            )
        return endpoint

    async def async_update_all_endpoints(self) -> None:
        endpoints = await asyncio.gather(
            *[self.async_update_endpoint(endpoint) for endpoint in self.endpoints]
        )
        self.endpoints = list(endpoints)

    @async_retryable(retries=3, sleep_time=10)
    async def async_create_ixia_config(self) -> ixia_types.IxiaConfig:
        await self.async_update_all_endpoints()

        ixia_config = ixia_types.IxiaConfig(
            api_server_ip=await self.async_get_primary_ixia_chassis_ip(),
            port_configs=await self.async_create_ixia_port_configs(),
            traffic_items=await self.async_create_all_traffic_items(),
            ptp_configs=self.ptp_configs,
        )
        return ixia_config

    async def async_create_ixia_setup(self) -> None:
        try:
            # Build the IxiaConfig once — used both for the TaacIxia constructor
            # AND for computing the cache key (if cache is enabled).
            built_ixia_config: t.Optional[ixia_types.IxiaConfig] = None
            if not self.session_id or self.override_traffic_items:
                built_ixia_config = await self.async_create_ixia_config()

            self.ixia = TaacIxia(
                ixia_config=built_ixia_config,
                logger=self.logger,
                session_name=self.get_session_name(),
                cleanup_config=False if self.session_id else self.cleanup_config,
                teardown_session=self.tear_down_session,
                force_take_port_ownership=True,
                session_id=self.session_id,
                password=fetch_ixia_password(),
                chassis_ip=(
                    await self.async_get_primary_ixia_chassis_ip()
                    if self.session_id
                    else None
                ),
                override_traffic_items=self.override_traffic_items,
                skip_advertised_prefixes_check=(
                    self.skip_advertised_prefixes_check
                    if self.skip_advertised_prefixes_check is not None
                    else not self.dc_has_inband_connectivity()
                ),
                cleanup_failed_setup=self.cleanup_failed_setup,
                skip_ixia_protocol_verification=self.skip_ixia_protocol_verification,
                ixia_protocol_verification_timeout=self.ixia_protocol_verification_timeout,
                ixia_recovery=self.ixia_recovery,
            )

            # Topology cache — only when (a) cache is enabled in TestConfig AND
            # (b) we have an IxiaConfig to hash. Without an IxiaConfig (session
            # reuse path) there's nothing to key on.
            cache_mgr = None
            cache_key = None
            cache_hit = False
            if (
                self.ixia_config_cache
                and self.ixia_config_cache.enabled
                and built_ixia_config is not None
            ):
                # Best-effort: catch any unexpected exception during cache
                # lookup so cache bugs degrade to cold setup, never fail the
                # whole test. The manager's own methods already swallow
                # expected misses; this is belt-and-braces for the rest.
                try:
                    cache_mgr = IxiaConfigCacheManager(
                        ixia=self.ixia,
                        cache_config=self.ixia_config_cache,
                        logger=self.logger,
                    )
                    # session_name is Optional but always set by
                    # TestSetupOrchestrator (test_config.name); none_throws fails
                    # fast if the contract breaks.
                    cache_key = cache_mgr.compute_key(
                        none_throws(self.session_name), built_ixia_config
                    )
                    self.logger.info(
                        f"\033[36m[IXIA]\033[0m cache enabled — key: "
                        f"\033[33m{cache_key}\033[0m"
                    )
                    # LoadConfig requires a live IxNetwork session, but the
                    # SessionAssistant isn't created until create_basic_setup
                    # Step 1. Connect first so `self.session` is populated; the
                    # cold-path create_basic_setup re-uses the same session via
                    # its own connect() (SessionAssistant reuses by SessionId).
                    self.ixia.connect()
                    cache_hit = cache_mgr.try_load_from_chassis(cache_key)
                    if cache_hit:
                        self.logger.info(
                            "\033[32m\033[1m[IXIA]\033[0m Tier 1 HIT — "
                            "skipping create_basic_setup (~226s+ saved)"
                        )
                    elif self.ixia_config_cache.manifold_bucket:
                        # Tier 2 — durable cross-testbed Manifold cache. Sidesteps
                        # the Tier 1 chassis persistence problem because the
                        # ixncfg is always downloaded fresh from Manifold and
                        # staged to chassis just-in-time for LoadConfig.
                        cache_hit = await cache_mgr.try_load_from_manifold(cache_key)
                        if cache_hit:
                            self.logger.info(
                                "\033[32m\033[1m[IXIA]\033[0m Tier 2 HIT — "
                                "skipping create_basic_setup (~226s+ saved)"
                            )
                except Exception as cache_exc:
                    self.logger.error(
                        f"\033[33m[IXIA]\033[0m cache lookup raised "
                        f"unexpectedly ({type(cache_exc).__name__}: "
                        f"{cache_exc!r}). Falling through to cold setup."
                    )
                    cache_mgr = None
                    cache_key = None
                    cache_hit = False

            if not cache_hit:
                self.logger.info(
                    "\033[36m\033[1m[IXIA]\033[0m starting full create_basic_setup..."
                )
                self.ixia.create_basic_setup()
                self.logger.info("\033[32m\033[1m[IXIA]\033[0m IXIA setup complete")
                # Warm BOTH cache tiers for next run. Both are best-effort:
                # any failure is logged and swallowed so the test stays green.
                if cache_mgr is not None and cache_key is not None:
                    try:
                        cache_mgr.save_to_chassis(cache_key)
                    except Exception as save_exc:
                        self.logger.error(
                            f"\033[33m[IXIA]\033[0m Tier 1 warm-up raised "
                            f"unexpectedly ({type(save_exc).__name__}: "
                            f"{save_exc!r}). Next run will pay cold cost again."
                        )
                    if (
                        self.ixia_config_cache
                        and self.ixia_config_cache.manifold_bucket
                    ):
                        try:
                            await cache_mgr.save_to_manifold(cache_key)
                        except Exception as save_exc:
                            self.logger.error(
                                f"\033[33m[IXIA]\033[0m Tier 2 warm-up raised "
                                f"unexpectedly ({type(save_exc).__name__}: "
                                f"{save_exc!r}). Next run will pay cold cost again."
                            )

        except Exception as ex:
            raise IxiaTestSetupError(
                f"Following error occurred while attempting to setup IXIA {ex}"
            )

    def create_direct_ixia_connection_assets(
        self, endpoint: taac_types.Endpoint
    ) -> t.List[IxiaEndpointInfo]:
        direct_ixia_connection_assets = []
        for direct_ixia_connection in endpoint.direct_ixia_connections or []:
            ixia_slot_num, ixia_port_num = direct_ixia_connection.ixia_port.split("/")
            ixia_endpoint = IxiaEndpointInfo(
                ixia_chassis_ip=direct_ixia_connection.ixia_chassis_ip
                or none_throws(self.primary_chassis_ip),
                ixia_slot_num=ixia_slot_num,
                ixia_port_num=ixia_port_num,
                remote_device_name=endpoint.name,
                remote_intf_name=direct_ixia_connection.interface,
                is_logical_port=direct_ixia_connection.is_logical_port,
            )
            direct_ixia_connection_assets.append(ixia_endpoint)
        return list(set(direct_ixia_connection_assets))

    def create_ixia_endpoint(
        self, endpoint: taac_types.TrafficEndpoint
    ) -> ixia_types.Endpoint:
        return ixia_types.Endpoint(
            port_name=endpoint.name,
            device_group_index=endpoint.device_group_index,
            network_group_index=endpoint.network_group_index,
        )

    def create_ixia_traffic_item(
        self,
        traffic_item_config: taac_types.BasicTrafficItemConfig,
    ) -> ixia_types.TrafficItem:
        src_ixia_endpoints = [
            self.create_ixia_endpoint(endpoint)
            for endpoint in none_throws(traffic_item_config.src_endpoints)
        ]

        dest_ixia_endpoints = [
            self.create_ixia_endpoint(endpoint)
            for endpoint in none_throws(traffic_item_config.dest_endpoints)
        ]

        traffic_flow_config = ixia_types.TrafficFlowConfig(
            frame_size=traffic_item_config.frame_size_settings,
            bidirectional=traffic_item_config.bidirectional,
            allow_self_destined=traffic_item_config.allow_self_destined,
            merge_destinations=traffic_item_config.merge_destinations,
            tracking_types=traffic_item_config.tracking_types,
            src_dest_mesh=traffic_item_config.src_dest_mesh,
            route_mesh=traffic_item_config.route_mesh,
        )
        packet_headers = self.create_packet_headers(traffic_item_config)

        is_raw_traffic = traffic_item_config.traffic_type == ixia_types.TrafficType.RAW
        default_l4_protocol_config = (
            ixia_types.L4ProtocolConfig()
            if not is_raw_traffic and not traffic_item_config.skip_default_l4_protocol
            else None
        )
        return ixia_types.TrafficItem(
            name=traffic_item_config.name,
            traffic_rate_info=ixia_types.TrafficRateInfo(
                rate_type=traffic_item_config.line_rate_type,
                rate_value=traffic_item_config.line_rate,
            ),
            traffic_flow_config=traffic_flow_config,
            l4_protocol_config=default_l4_protocol_config,
            source_endpoints=src_ixia_endpoints,
            dest_endpoints=dest_ixia_endpoints,
            packet_headers=packet_headers,
            traffic_type=traffic_item_config.traffic_type,
            qos_config=traffic_item_config.qos_config,
            enabled=traffic_item_config.enabled,
        )

    async def async_create_all_traffic_items(
        self,
    ) -> t.List[ixia_types.TrafficItem]:
        traffic_items: t.List[ixia_types.TrafficItem] = []
        if self.basic_traffic_item_configs:
            ixia_assets = await asyncio.gather(
                *[
                    self.async_get_endpoint_desired_ixia_assets(endpoint)
                    for endpoint in self.endpoints
                ]
            )
            all_ixia_assets = list(itertools.chain(*ixia_assets))
            all_endpoints = [
                taac_types.TrafficEndpoint(
                    name=f"{asset.remote_device_name}:{asset.remote_intf_name}",
                )
                for asset in all_ixia_assets
            ]
            for basic_traffic_item_config in self.basic_traffic_item_configs:
                self.logger.info(
                    f"Creating traffic item {basic_traffic_item_config.name}"
                )

                config = copy.deepcopy(basic_traffic_item_config)
                if basic_traffic_item_config.full_mesh:
                    config = config(
                        src_dest_mesh=ixia_types.SrcDestMeshType.FULL_MESH,
                        src_endpoints=all_endpoints,
                        dest_endpoints=all_endpoints,
                    )
                traffic_items.append(
                    self.create_ixia_traffic_item(basic_traffic_item_config)
                )
            if not traffic_items:
                raise InsufficientInputError(
                    "No traffic items created. Please specify the source and destination "
                    "endpoints of the traffic items in BasicTrafficItemConfigs"
                )
        # pyrefly: ignore [unsupported-operation]
        all_traffic_items = traffic_items + self.user_defined_traffic_items
        self._traffic_items = all_traffic_items
        return all_traffic_items

    def get_snake_config(self, endpoint_str: str) -> taac_types.SnakeConfig:
        for snake_config in self.snake_configs:
            if (
                snake_config.source == endpoint_str
                or snake_config.destination == endpoint_str
            ):
                return snake_config
        raise ValueError(f"Unable to find matching snake config for {endpoint_str}")

    def get_standalone_ip_fields(self, endpoint_str: str) -> t.Tuple[str, str, int]:
        snake_config = self.get_snake_config(endpoint_str)
        is_src_endpoint = snake_config.source == endpoint_str
        if is_src_endpoint:
            prefix_v6, prefix_len = snake_config.source_ip.split("/")
            ixia_starting_ip = snake_config.destination_ip.split("/")[0]
        else:
            prefix_v6, prefix_len = snake_config.destination_ip.split("/")
            ixia_starting_ip = snake_config.source_ip.split("/")[0]
        prefix_len = int(prefix_len)
        return ixia_starting_ip, prefix_v6, prefix_len

    async def async_create_ip_addresses_config(
        self,
        endpoint_str: str,
        v4_addresses_config: t.Optional[taac_types.IpAddressesConfig],
        v6_addresses_config: t.Optional[taac_types.IpAddressesConfig],
    ) -> ixia_types.IpAddresses:
        """
        @interface_name: This is the name of the network device on the
                         remote side of the IXIA port

        Used to fetch the IP address information needed to the configure
        the IXIA port using the IP address information of the device on
        the remote side of this IXIA port

        NOTE: Only V6 IP address information is deduced on the fly
        """

        ipv6_addresses = None
        ipv4_addresses = None
        if (
            v6_addresses_config or not v4_addresses_config
        ):  # if neither v4 or v6 is specified, resort to auto ip configuration
            v6_addresses_config = v6_addresses_config or taac_types.IpAddressesConfig()
            if v6_addresses_config.gateway_starting_ip:
                prefix_len = v6_addresses_config.mask
                prefix_v6 = v6_addresses_config.gateway_starting_ip
            else:
                hostname, interface = endpoint_str.split(":")
                driver = await async_get_device_driver(hostname)
                prefix_v6, prefix_len = (
                    # pyre-fixme[16]: `AbstractSwitch` has no attribute
                    #  `async_get_interfaces_ipv6_address`.
                    await driver.async_get_interfaces_ipv6_address([interface])
                )[interface]
            ixia_starting_ip = (
                v6_addresses_config.starting_ip
                # pyrefly: ignore [bad-argument-type]
                or get_next_available_ipv6_address(prefix_v6, prefix_len)
            )
            ipv6_addresses = ixia_types.IPv6AddressInfo(
                starting_ip=ixia_starting_ip,
                subnet_mask=(
                    v6_addresses_config.mask or prefix_len or DEFAULT_PREFIX_LEN_V6
                ),
                increment_ip=(
                    v6_addresses_config.increment_ip or IXIA_STARTING_IP_INCREMENT_V6
                ),
                gateway_starting_ip=prefix_v6,
                gateway_increment_ip=(
                    v6_addresses_config.gateway_increment_ip
                    or IXIA_GATEWAY_IP_INCREMENT_V6
                ),
                start_index=v6_addresses_config.start_index,
            )
        if v4_addresses_config:
            ipv4_addresses = ixia_types.IPv4AddressInfo(
                starting_ip=none_throws(v4_addresses_config.starting_ip),
                subnet_mask=v4_addresses_config.mask or DEFAULT_PREFIX_LEN_V4,
                increment_ip=v4_addresses_config.increment_ip
                or IXIA_STARTING_IP_INCREMENT_V4,
                gateway_starting_ip=none_throws(
                    v4_addresses_config.gateway_starting_ip
                ),
                gateway_increment_ip=v4_addresses_config.gateway_increment_ip
                or IXIA_GATEWAY_IP_INCREMENT_V4,
                start_index=v4_addresses_config.start_index,
            )
        return ixia_types.IpAddresses(
            ipv4_addresses_config=ipv4_addresses,
            ipv6_addresses_config=ipv6_addresses,
        )

    async def async_create_bgp_config_thrift(
        self,
        hostname: str,
        bgp_config: taac_types.BgpConfig,
        ip_address_info: t.Union[
            ixia_types.IPv4AddressInfo, ixia_types.IPv6AddressInfo
        ],
        ip_address_family: ixia_types.IpAddressFamily,
    ) -> ixia_types.BgpConfig:
        bgp_prefix_configs = list(
            itertools.chain.from_iterable(
                self.create_bgp_prefix_configs(route_scale)
                for route_scale in bgp_config.route_scales or []
            )
        )
        local_as = (
            bgp_config.local_as
            or DEVICE_ROLE_IXIA_ASN_MAP[
                none_throws((await get_skynet_device_role(hostname))).upper()
            ]
            if not (bgp_config.local_as_4_bytes or bgp_config.enable_4_byte_local_as)
            else 0
        )
        # Custom Network Group Configuration support
        custom_network_group_configs = None
        if bgp_config.custom_network_group_configs:
            custom_network_group_configs = [
                ixia_types.CustomNetworkGroupConfig(
                    device_group_name=config.device_group_name,
                    network_group_name=config.network_group_name,
                    network_group_multiplier=config.network_group_multiplier,
                    prefix_start_value=config.prefix_start_value,
                    prefix_length=config.prefix_length,
                    nexthop_start_value=config.nexthop_start_value,
                    nexthop_increments=config.nexthop_increments,
                    ecmp_width=config.ecmp_width,
                    number_of_addresses_per_row=config.number_of_addresses_per_row,
                    community_list=config.community_list,
                    next_hop_type=config.next_hop_type,
                    next_hop_ip_type=config.next_hop_ip_type,
                    next_hop_increment_mode=config.next_hop_increment_mode,
                    network_group_index=config.network_group_index,
                )
                for config in bgp_config.custom_network_group_configs
            ]

        return ixia_types.BgpConfig(
            ip_address_family=ip_address_family,
            bgp_peer_config=self._create_bgp_peer_config(
                bgp_config=bgp_config,
                ip_address_info=ip_address_info,
                ip_address_family=ip_address_family,
                local_as=local_as,
            ),
            bgp_prefix_configs=bgp_prefix_configs,
            import_bgp_routes_params_list=bgp_config.import_bgp_routes_params_list,
            custom_network_group_configs=custom_network_group_configs,
        )

    def _create_bgp_peer_config(
        self,
        bgp_config: taac_types.BgpConfig,
        ip_address_info: t.Union[
            ixia_types.IPv4AddressInfo, ixia_types.IPv6AddressInfo
        ],
        ip_address_family: ixia_types.IpAddressFamily,
        local_as: int,
    ) -> ixia_types.BgpPeerConfig:
        """
        Create a BgpPeerConfig with optional as_set_mode support.

        The as_set_mode field may not be available in all versions of the IXIA types.
        This method handles the field conditionally to maintain backward compatibility.
        """
        # Build base kwargs
        peer_config_kwargs = {
            "local_as": local_as,
            "local_as_4_bytes": bgp_config.local_as_4_bytes or local_as,
            "local_as_increment": bgp_config.local_as_increment,
            "enable_4_byte_local_as": bgp_config.enable_4_byte_local_as,
            "peer_type": bgp_config.bgp_peer_type,
            "local_peer_starting_ip": bgp_config.local_peer_starting_ip
            or ip_address_info.starting_ip,
            "local_peer_increment_ip": bgp_config.local_peer_increment_ip
            or ip_address_info.increment_ip
            or (
                IXIA_STARTING_IP_INCREMENT_V6
                if ip_address_family == ixia_types.IpAddressFamily.IPV6
                else IXIA_STARTING_IP_INCREMENT_V4
            ),
            "remote_peer_starting_ip": bgp_config.remote_peer_starting_ip
            or ip_address_info.gateway_starting_ip,
            "remote_peer_increment_ip": bgp_config.remote_peer_increment_ip
            or ip_address_info.gateway_increment_ip
            or (
                IXIA_GATEWAY_IP_INCREMENT_V6
                if ip_address_family == ixia_types.IpAddressFamily.IPV6
                else IXIA_GATEWAY_IP_INCREMENT_V4
            ),
            "capabilities": bgp_config.bgp_capabilities,
            "enable_graceful_restart": bgp_config.enable_graceful_restart,
            "advertise_end_of_rib": bgp_config.advertise_end_of_rib,
            "graceful_restart_timer": bgp_config.graceful_restart_timer,
            "peer_flap_config": bgp_config.peer_flap_config,
            "is_confed": bgp_config.is_confed,
            "bgp_peer_name": bgp_config.bgp_peer_name,
            "hold_timer": bgp_config.hold_timer,
            "keepalive_timer": bgp_config.keepalive_timer,
        }

        # Try to add as_set_mode if the field is supported
        if bgp_config.as_set_mode is not None:
            try:
                # Test if the field exists by creating a minimal config
                _ = ixia_types.BgpPeerConfig(as_set_mode=bgp_config.as_set_mode)
                # If we get here, the field is supported
                peer_config_kwargs["as_set_mode"] = bgp_config.as_set_mode
            except TypeError:
                # Field not supported in this version of IXIA types
                self.logger.warning(
                    "as_set_mode field not supported in BgpPeerConfig, "
                    f"ignoring value: {bgp_config.as_set_mode}"
                )

        # pyre-ignore[6]: Pyre can't infer types from dict unpacking
        return ixia_types.BgpPeerConfig(**peer_config_kwargs)

    def get_matching_basic_port_config(
        self,
        endpoint_str: str,
    ) -> taac_types.BasicPortConfig:
        if not self.basic_port_configs:
            return self.default_basic_port_config
        for basic_port_config in self.basic_port_configs:  # pyre-ignore
            if basic_port_config.endpoint == endpoint_str:
                return basic_port_config
        return self.default_basic_port_config

    @retryable(num_tries=3, sleep_time=60, debug=True)
    def select_ixia_assets(
        self, endpoint: taac_types.Endpoint, ixia_assets: t.List[IxiaEndpointInfo]
    ) -> t.List[IxiaEndpointInfo]:
        """
        Selects Ixia assets based on user input within an Endpoint.
        The user can specify either the number of Ixia assets to use or the name of the local interfaces connecting to the Ixia ports.
        This function will then choose the corresponding Ixia assets accordingly.
        """
        ixia_ports = endpoint.ixia_ports or []
        matching_ixia_assets = []
        if ixia_ports:
            for ixia_asset in ixia_assets:
                if ixia_asset.remote_intf_name in ixia_ports:
                    matching_ixia_assets.append(ixia_asset)
            if len(matching_ixia_assets) != len(ixia_ports):
                matching_ixia_asset_names = [
                    ixia_asset.remote_intf_name for ixia_asset in matching_ixia_assets
                ]
                assets_not_found = [
                    asset
                    for asset in ixia_ports
                    if asset not in matching_ixia_asset_names
                ]
                raise ValueError(
                    f"Unable to find ixia assets connecting to interfaces: {assets_not_found} on {endpoint.name}"
                )
        else:
            matching_ixia_assets = ixia_assets
        desired_ixia_assets = matching_ixia_assets
        exclude_ixia_ports = endpoint.exclude_ixia_ports or []
        desired_ixia_assets = [
            ixia_asset
            for ixia_asset in desired_ixia_assets
            if ixia_asset.remote_intf_name not in exclude_ixia_ports
        ]
        return desired_ixia_assets

    @async_memoize_timed(3600)
    @async_retryable(retries=3, sleep_time=30, exceptions=(Exception,))
    async def async_get_endpoint_desired_ixia_assets(
        self, endpoint: taac_types.Endpoint
    ) -> t.List[IxiaEndpointInfo]:
        """
        Fetches the Ixia assets that are needed for the given endpoint
        """
        direct_ixia_connection_assets = self.create_direct_ixia_connection_assets(
            endpoint
        )

        # OSS mode: Only use direct IXIA connections, no LLDP/optical switch discovery
        if TAAC_OSS:
            if direct_ixia_connection_assets:
                self.logger.info(
                    f"[OSS Mode] Using {len(direct_ixia_connection_assets)} direct IXIA connection(s) "
                    f"for endpoint {endpoint.name}"
                )
                return list(set(direct_ixia_connection_assets))
            else:
                raise InsufficientInputError(
                    f"[OSS Mode] No direct IXIA connections provided for endpoint {endpoint.name}. "
                    "In OSS mode, direct IXIA connections must be explicitly configured. "
                    "Please provide IXIA connection details in the endpoint configuration."
                )

        # Internal mode: Use direct connections if provided, otherwise use LLDP/optical switch discovery
        if direct_ixia_connection_assets:
            # When direct IXIA connections are explicitly provided, rely solely
            # on them and skip LLDP/optical switch discovery to avoid picking up
            # unrelated connections on the same device.
            self.logger.info(
                f"Using {len(direct_ixia_connection_assets)} direct IXIA connection(s) "
                f"for endpoint {endpoint.name}, skipping LLDP/optical switch discovery"
            )
            return list(set(direct_ixia_connection_assets))

        # Lazy import for OSS compatibility - only needed in internal mode
        from taac.internal.internal_utils import (
            async_create_lldp_ixia_connection_assets,
        )

        lldp_assets = await async_create_lldp_ixia_connection_assets(endpoint.name)
        self.logger.debug(f"lldp ixia assets: {lldp_assets}")
        ixia_assets = (
            lldp_assets
            or await async_create_optical_switch_ixia_connection_assets(endpoint.name)
        )
        desired_ixia_assets: t.List[IxiaEndpointInfo] = []
        if ixia_assets:
            desired_ixia_assets = self.select_ixia_assets(endpoint, ixia_assets)
        if not desired_ixia_assets:
            raise InsufficientInputError(
                f"Unable to find any ixia assets for endpoint {endpoint.name}"
            )

        # Fallback: use primary_chassis_ip for assets with missing ixia_chassis_ip
        if self.primary_chassis_ip:
            for asset in desired_ixia_assets:
                if not asset.ixia_chassis_ip:
                    self.logger.info(
                        f"Using primary_chassis_ip '{self.primary_chassis_ip}' as fallback "
                        f"for asset {asset.remote_device_name}:{asset.remote_intf_name}"
                    )
                    # Type is guaranteed to be str here since we checked primary_chassis_ip is truthy
                    asset.ixia_chassis_ip = str(self.primary_chassis_ip)

        return list(set(desired_ixia_assets))

    async def async_create_endpoint_ixia_port_configs(
        self, endpoint: taac_types.Endpoint
    ) -> t.List[ixia_types.PortConfig]:
        hostname = endpoint.name
        ixia_assets = await self.async_get_endpoint_desired_ixia_assets(endpoint)
        port_configs = []
        if not ixia_assets:
            raise InsufficientInputError(
                f"Unable to find any ixia assets for endpoint {endpoint.name}"
            )
        driver = await async_get_device_driver(hostname)
        await asyncio.gather(
            *[
                driver.async_check_interface_status(
                    ixia_asset.remote_intf_name,
                    state=InterfaceEventState.STABLE,
                )
                for ixia_asset in ixia_assets
            ]
        )
        for asset in ixia_assets:
            chassis_hostname = await async_get_hostname_from_ip(asset.ixia_chassis_ip)
            try:
                logical_port_num = (
                    int(asset.ixia_port_num)
                    if asset.is_logical_port
                    else await async_get_ixia_logical_port(
                        chassis_hostname, int(asset.ixia_port_num)
                    )
                )
            except Exception as ex:
                raise Exception(
                    f"Failed to get the ixia logical port number for"
                    f" port {asset.ixia_port_num} on chassis {chassis_hostname}: {ex}"
                )
            hostname, interface = asset.remote_device_name, asset.remote_intf_name
            endpoint_str = f"{hostname}:{interface}"
            basic_port_config = self.get_matching_basic_port_config(endpoint_str)
            if not basic_port_config.device_group_configs:
                basic_port_config = basic_port_config(
                    device_group_configs=[DEFAULT_DEVICE_GROUP_CONFIG]
                )
            if self.is_standalone:
                port_configs.append(
                    self.create_standalone_port_config(
                        endpoint_str, asset, logical_port_num
                    )
                )
            elif basic_port_config.device_group_configs:
                thrift_device_group_configs = []
                for device_group_config in basic_port_config.device_group_configs:
                    thrift_ip_addresses_config = (
                        await self.async_create_ip_addresses_config(
                            endpoint_str,
                            device_group_config.v4_addresses_config,
                            device_group_config.v6_addresses_config,
                        )
                    )
                    thrift_v4_bgp_config = None
                    thrift_v6_bgp_config = None
                    thrift_bgp_config = None
                    if device_group_config.v4_bgp_config:
                        thrift_v4_bgp_config = (
                            await self.async_create_bgp_config_thrift(
                                hostname,
                                device_group_config.v4_bgp_config,
                                none_throws(
                                    thrift_ip_addresses_config.ipv4_addresses_config
                                ),
                                ixia_types.IpAddressFamily.IPV4,
                            )
                        )
                    if device_group_config.v6_bgp_config:
                        thrift_v6_bgp_config = (
                            await self.async_create_bgp_config_thrift(
                                hostname,
                                device_group_config.v6_bgp_config,
                                none_throws(
                                    thrift_ip_addresses_config.ipv6_addresses_config
                                ),
                                ixia_types.IpAddressFamily.IPV6,
                            )
                        )
                    thrift_bgp_config = ixia_types.BgpConfigInfo(
                        bgp_v4_config=thrift_v4_bgp_config,
                        bgp_v6_config=thrift_v6_bgp_config,
                    )
                    thrift_device_group_configs.append(
                        ixia_types.DeviceGroupConfig(
                            multiplier=device_group_config.multiplier,
                            ip_addresses_config=thrift_ip_addresses_config,
                            bgp_config=thrift_bgp_config,
                            device_group_index=device_group_config.device_group_index,
                            enable=device_group_config.enable,
                            tag_name=device_group_config.tag_name,
                            device_group_name=device_group_config.device_group_name,
                        )
                    )
                port_configs.append(
                    ixia_types.PortConfig(
                        port_name=endpoint_str,
                        phy_port_config=ixia_types.PhyPortConfig(
                            chassis_ip=asset.ixia_chassis_ip,
                            slot_number=int(asset.ixia_slot_num),
                            port_number=logical_port_num,
                        ),
                        l1_config=basic_port_config.l1_config,
                        device_group_configs=thrift_device_group_configs,
                    )
                )
        return port_configs

    def create_standalone_port_config(
        self,
        endpoint_str: str,
        ixia_asset: IxiaEndpointInfo,
        ixia_logical_port_num: int,
    ) -> ixia_types.PortConfig:
        ixia_starting_ip, prefix_v6, prefix_len = self.get_standalone_ip_fields(
            endpoint_str
        )

        ipv6_addresses = ixia_types.IPv6AddressInfo(
            starting_ip=ixia_starting_ip,
            subnet_mask=prefix_len,
            increment_ip=IXIA_STARTING_IP_INCREMENT_V6,
            gateway_starting_ip=prefix_v6,
            gateway_increment_ip=IXIA_GATEWAY_IP_INCREMENT_V6,
        )
        thrift_ip_addresses_config = ixia_types.IpAddresses(
            ipv6_addresses_config=ipv6_addresses,
        )
        device_group_configs = [
            ixia_types.DeviceGroupConfig(
                multiplier=1,
                ip_addresses_config=thrift_ip_addresses_config,
                device_group_index=0,
            )
        ]
        port_config = ixia_types.PortConfig(
            port_name=endpoint_str,
            phy_port_config=ixia_types.PhyPortConfig(
                chassis_ip=ixia_asset.ixia_chassis_ip,
                slot_number=int(ixia_asset.ixia_slot_num),
                port_number=ixia_logical_port_num,
            ),
            device_group_configs=device_group_configs,
        )
        return port_config

    async def async_create_ixia_port_configs(
        self,
    ) -> t.List[ixia_types.PortConfig]:
        """
        Fetches the default IXIA port configs that are needed for the given
        IXIA setup of the current Test Config
        """
        port_configs = list(
            itertools.chain(
                *await asyncio.gather(
                    *[
                        self.async_create_endpoint_ixia_port_configs(endpoint)
                        for endpoint in self.endpoints
                        if endpoint.ixia_ports or endpoint.ixia_needed
                    ]
                )
            )
        )
        if not port_configs:
            raise Exception("No ixia port configs created.")
        self._port_configs = port_configs
        self.logger.info("Successfully created the IXIA port configs.")
        self.logger.debug(f"Ixia port info generated: {port_configs}")
        return port_configs

    def create_bgp_prefix_configs(
        self,
        route_scale_spec: taac_types.RouteScaleSpec,
    ) -> t.List[ixia_types.BgpPrefixConfig]:
        bgp_prefix_configs = []
        if route_scale_spec.v4_route_scale:
            route_scale = route_scale_spec.v4_route_scale
            bgp_prefix_configs.append(
                ixia_types.BgpPrefixConfig(
                    prefix_name=route_scale.prefix_name,
                    starting_ip=route_scale.starting_prefixes,
                    increment_ip=route_scale.prefix_step or IXIA_PREFIX_STEP_IP_V4,
                    prefix_length=route_scale.prefix_length,
                    distributed_prefix_length_config=route_scale.distributed_prefix_length_config,
                    count=route_scale.prefix_count,
                    prefix_flap_config=route_scale.prefix_flap_config,
                    bgp_communities=self.get_bgp_communities(route_scale),
                    as_path_prepends=self.get_bgp_as_path_prepends(route_scale),
                    extended_bgp_communities=self.get_extended_bgp_communities(
                        route_scale
                    ),
                    ip_address_family=route_scale.ip_address_family,
                    network_group_index=route_scale_spec.network_group_index,
                    multiplier=route_scale.multiplier,
                    prefix_pool_name=route_scale.prefix_name,
                )
            )
        if route_scale_spec.v6_route_scale:
            route_scale = route_scale_spec.v6_route_scale
            bgp_prefix_configs.append(
                ixia_types.BgpPrefixConfig(
                    prefix_name=route_scale.prefix_name,
                    starting_ip=route_scale.starting_prefixes,
                    increment_ip=route_scale.prefix_step or IXIA_PREFIX_STEP_IP_V6,
                    prefix_length=route_scale.prefix_length,
                    distributed_prefix_length_config=route_scale.distributed_prefix_length_config,
                    count=route_scale.prefix_count,
                    prefix_flap_config=route_scale.prefix_flap_config,
                    bgp_communities=self.get_bgp_communities(route_scale),
                    as_path_prepends=self.get_bgp_as_path_prepends(route_scale),
                    extended_bgp_communities=self.get_extended_bgp_communities(
                        route_scale
                    ),
                    ip_address_family=route_scale.ip_address_family,
                    network_group_index=route_scale_spec.network_group_index,
                    multiplier=route_scale.multiplier,
                    prefix_pool_name=route_scale.prefix_name,
                )
            )
        return bgp_prefix_configs

    def get_bgp_communities(
        self,
        route_scale: taac_types.RouteScale,
    ) -> t.Optional[t.List[ixia_types.BgpCommunity]]:
        """
        Adds the community values for the BGP prefxies based on the values specified
        in the test configs
        """
        bgp_communities = route_scale.bgp_communities
        if not bgp_communities:
            return None
        community_list: t.List[ixia_types.BgpCommunity] = []
        for community in bgp_communities:
            community_as_number = int(community.split(":")[0])
            community_last_two_octets = int(community.split(":")[1])
            community_list.append(
                ixia_types.BgpCommunity(
                    bgp_community_type=ixia_types.BgpCommunityType.MANUAL,
                    as_number=community_as_number,
                    last_two_octets=community_last_two_octets,
                )
            )
        return community_list

    def get_extended_bgp_communities(
        self,
        route_scale: taac_types.RouteScale,
    ) -> t.Optional[t.List[ixia_types.ExtendedBgpCommunity]]:
        """
        Converts extended BGP community strings from the test config into
        ExtendedBgpCommunity thrift objects for IXIA prefix configuration.

        Supported formats:
            - "link_bw:SUB_TYPE:AS:BW_VALUE" -> Link Bandwidth extended community
        """
        extended_bgp_communities = route_scale.extended_bgp_communities
        if not extended_bgp_communities:
            return None
        ext_community_list: t.List[ixia_types.ExtendedBgpCommunity] = []
        type_mapping = {
            "link_bw": ixia_types.ExtendedBgpCommunityType.LINK_BW,
        }
        for community_str in extended_bgp_communities:
            parts = community_str.split(":")
            if len(parts) == 4:
                ec_type_str, sub_type, as_num, value = parts
                ec_type = type_mapping.get(ec_type_str.lower())
                if ec_type is None:
                    self.logger.warning(
                        f"Unknown extended BGP community type: {ec_type_str}, "
                        f"supported types: {list(type_mapping.keys())}"
                    )
                    continue
                ext_community_list.append(
                    ixia_types.ExtendedBgpCommunity(
                        type=ec_type,
                        sub_type=int(sub_type),
                        global_as_number=int(as_num),
                        local_bw_value=int(value),
                    )
                )
            else:
                self.logger.warning(
                    f"Invalid extended BGP community format: {community_str}, "
                    f"expected 'link_bw:SUB_TYPE:AS:BW_VALUE'"
                )
        return ext_community_list if ext_community_list else None

    def get_bgp_as_path_prepends(
        self,
        route_scale: taac_types.RouteScale,
    ) -> t.Optional[t.List[ixia_types.AsPathPrepend]]:
        """
        Prepends the AS path for the BGP prefxies based on the values specified
        """
        as_path_prepend_numbers = route_scale.as_path_prepend_numbers
        if not as_path_prepend_numbers:
            return None
        as_path_prepends = []
        for as_path_prepend_segment_numbers in as_path_prepend_numbers:
            as_path_prepends.append(
                ixia_types.AsPathPrepend(as_numbers=as_path_prepend_segment_numbers)
            )
        return as_path_prepends

    @async_memoize_timed(60)
    async def async_get_primary_ixia_chassis_ip(self) -> str:
        if self.primary_chassis_ip:
            if string_is_ip(self.primary_chassis_ip):
                return self.primary_chassis_ip  # pyre-ignore
            else:
                # pyre-fixme[6]: For 1st argument expected `str` but got
                #  `Optional[str]`.
                return await async_get_ip_from_hostname(self.primary_chassis_ip)
        else:
            ixia_chassis_ips = set()
            for endpoint in self.endpoints:
                ixia_assets = await self.async_get_endpoint_desired_ixia_assets(
                    endpoint
                )
                if ixia_assets:
                    for ixia_asset in ixia_assets:
                        if ixia_asset.ixia_chassis_ip:
                            ixia_chassis_ips.add(ixia_asset.ixia_chassis_ip)
            if len(ixia_chassis_ips) == 1:
                self.primary_chassis_ip = ixia_chassis_ips.pop()
                return self.primary_chassis_ip
            raise ValueError(
                f"Multiple or no IXIA chassis IPs found: {ixia_chassis_ips}. Please specify the primary IXIA chassis IP"
            )

    def get_reference_value(
        self,
        traffic_item_config: taac_types.BasicTrafficItemConfig,
        reference: taac_types.Reference,
    ) -> t.Any:
        src_endpoints = none_throws(traffic_item_config.src_endpoints)
        dest_endpoints = none_throws(traffic_item_config.dest_endpoints)
        reference_values = []
        for i in reference.indices:
            value = None
            src_hostname = src_endpoints[i].name.split(":")[0]
            dst_hostname = dest_endpoints[i].name.split(":")[0]
            src_port_config = self.get_port_config_by_name(src_hostname)
            dst_port_config = self.get_port_config_by_name(dst_hostname)
            match reference.type:
                case taac_types.ReferenceType.SRC_MAC_ADDRESS:
                    value = self.name_to_endpoint[src_hostname].mac_address
                case taac_types.ReferenceType.DST_MAC_ADDRESS:
                    value = self.name_to_endpoint[dst_hostname].mac_address
                case taac_types.ReferenceType.SRC_IPV6_ADDRESS:
                    value = none_throws(
                        src_port_config.device_group_configs[
                            reference.device_group_index
                        ].ip_addresses_config.ipv6_addresses_config
                    ).starting_ip
                case taac_types.ReferenceType.DST_IPV6_ADDRESS:
                    value = none_throws(
                        dst_port_config.device_group_configs[
                            reference.device_group_index
                        ].ip_addresses_config.ipv6_addresses_config
                    ).starting_ip
                case taac_types.ReferenceType.SRC_GATEWAY_IPV6_ADDRESS:
                    value = none_throws(
                        src_port_config.device_group_configs[
                            reference.device_group_index
                        ].ip_addresses_config.ipv6_addresses_config
                    ).gateway_starting_ip
                case taac_types.ReferenceType.DST_GATEWAY_IPV6_ADDRESS:
                    value = none_throws(
                        dst_port_config.device_group_configs[
                            reference.device_group_index
                        ].ip_addresses_config.ipv6_addresses_config
                    ).gateway_starting_ip
                case taac_types.ReferenceType.SRC_IPV4_ADDRESS:
                    value = none_throws(
                        src_port_config.device_group_configs[
                            reference.device_group_index
                        ].ip_addresses_config.ipv4_addresses_config
                    ).starting_ip
                case taac_types.ReferenceType.DST_IPV4_ADDRESS:
                    value = none_throws(
                        dst_port_config.device_group_configs[
                            reference.device_group_index
                        ].ip_addresses_config.ipv4_addresses_config
                    ).starting_ip
                case taac_types.ReferenceType.SRC_GATEWAY_IPV4_ADDRESS:
                    value = none_throws(
                        src_port_config.device_group_configs[
                            reference.device_group_index
                        ].ip_addresses_config.ipv4_addresses_config
                    ).gateway_starting_ip
                case taac_types.ReferenceType.DST_GATEWAY_IPV4_ADDRESS:
                    value = none_throws(
                        dst_port_config.device_group_configs[
                            reference.device_group_index
                        ].ip_addresses_config.ipv4_addresses_config
                    ).gateway_starting_ip
                case taac_types.ReferenceType.DST_LINK_LOCAL_IPV6_ADDRESS:
                    value = mac_to_ipv6_link_local(
                        # pyrefly: ignore [bad-argument-type]
                        self.name_to_endpoint[dst_hostname].mac_address
                    )
            reference_values.append(value)
        if reference_values:
            if reference.data_type == taac_types.DataType.SCALAR:
                return reference_values[0]
            elif reference.data_type == taac_types.DataType.LIST:
                return reference_values

    def create_packet_headers(
        self, traffic_item_config: taac_types.BasicTrafficItemConfig
    ) -> t.List[ixia_types.PacketHeader]:
        ixia_packet_headers = []
        for packet_header in traffic_item_config.packet_headers or []:
            ixia_fields = []
            # example: https://fburl.com/phabricator/pdg51o9p
            for field in packet_header.fields or []:
                attrs = []
                attrs_dict = json.loads(field.attrs_json)
                for key, value in attrs_dict.items():
                    attrs.append(
                        ixia_types.Attr(
                            name=key,
                            value=get_attr_value(value),
                        )
                    )
                if field.references:
                    for key, reference in field.references.items():
                        attr = ixia_types.Attr(
                            name=key,
                            value=get_attr_value(
                                self.get_reference_value(traffic_item_config, reference)
                            ),
                        )
                        attrs.append(attr)
                ixia_fields.append(
                    ixia_types.Field(
                        query=field.query,
                        attrs=attrs,
                    )
                )
            ixia_packet_headers.append(
                ixia_types.PacketHeader(
                    query=packet_header.query,
                    append_to_query=packet_header.append_to_query,
                    fields=ixia_fields,
                    remove_from_stack=packet_header.remove_from_stack,
                )
            )
        return ixia_packet_headers

    def get_port_config_by_name(self, port_name: str) -> ixia_types.PortConfig:
        for port_config in self._port_configs:
            if port_config.port_name.split(":")[0] == port_name:
                return port_config
        raise ValueError(f"Unable to find port config for {port_name}")
