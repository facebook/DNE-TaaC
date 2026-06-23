# pyre-unsafe
import asyncio
import itertools
import typing as t

from ixia.ixia import types as ixia_types
from taac.libs.traffic_generator import DEFAULT_DEVICE_GROUP_CONFIG, TrafficGenerator
from taac.utils.oss_taac_constants import IxiaTestSetupError
from taac.utils.oss_taac_lib_utils import none_throws
from taac.test_as_a_config import types as taac_types


class OtgTrafficGenerator(TrafficGenerator):
    """TrafficGenerator subclass for OTG/snappi backends.

    Overrides port config creation and setup to skip chassis discovery,
    SSH checks, and logical port lookup — OTG uses port_location strings
    from DirectIxiaConnection instead.
    """

    async def async_create_ixia_setup(self) -> None:
        try:
            from taac.ixia.otg_traffic_gen import OtgTrafficGen

            ixia_config = await self.async_create_ixia_config()
            controller_url = (
                self.primary_chassis_ip or self._otg_controller_from_endpoints()
            )
            self.ixia = OtgTrafficGen(
                ixia_config=ixia_config,
                location=controller_url,
                logger=self.logger,
            )
            self.logger.info(
                "[OTG] Starting OTG setup "
                "(push config → ARP → flows)..."
            )
            self.ixia.setup()  # type: ignore[attr-defined]
        except Exception as ex:
            raise IxiaTestSetupError(
                f"Following error occurred while attempting to setup IXIA {ex}"
            ) from ex

    def _otg_controller_from_endpoints(self) -> t.Optional[str]:
        """Extract OTG controller host from the first DirectIxiaConnection."""
        for endpoint in self.endpoints:
            for conn in endpoint.direct_ixia_connections or []:
                if conn.ixia_chassis_ip:
                    return conn.ixia_chassis_ip
        return None

    async def _async_build_full_mesh_endpoints(
        self,
    ) -> t.List[taac_types.TrafficEndpoint]:
        return [
            taac_types.TrafficEndpoint(
                name=f"{ep.name}:{conn.interface}",
            )
            for ep in self.endpoints
            for conn in (ep.direct_ixia_connections or [])
        ]

    async def async_create_ixia_port_configs(
        self,
    ) -> t.List[ixia_types.PortConfig]:
        port_configs = list(
            itertools.chain(
                *await asyncio.gather(
                    *[
                        self._async_create_otg_port_configs(endpoint)
                        for endpoint in self.endpoints
                        if endpoint.direct_ixia_connections
                        or endpoint.ixia_ports
                        or endpoint.ixia_needed
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

    async def _async_create_otg_port_configs(
        self, endpoint: taac_types.Endpoint
    ) -> t.List[ixia_types.PortConfig]:
        """Build ixia PortConfigs for OTG — no chassis discovery or SSH checks."""
        port_configs = []
        for conn in endpoint.direct_ixia_connections or []:
            endpoint_str = f"{endpoint.name}:{conn.interface}"
            port_location = getattr(conn, "port_location", None) or conn.interface
            basic_port_config = self.get_matching_basic_port_config(endpoint_str)
            if not basic_port_config.device_group_configs:
                basic_port_config = basic_port_config(
                    device_group_configs=[DEFAULT_DEVICE_GROUP_CONFIG]
                )

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
                if device_group_config.v4_bgp_config:
                    thrift_v4_bgp_config = (
                        await self.async_create_bgp_config_thrift(
                            endpoint.name,
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
                            endpoint.name,
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
                        chassis_ip=conn.ixia_chassis_ip
                        or self.primary_chassis_ip
                        or "otg",
                    ),
                    port_location=port_location,
                    l1_config=basic_port_config.l1_config,
                    device_group_configs=thrift_device_group_configs,
                )
            )
        return port_configs
