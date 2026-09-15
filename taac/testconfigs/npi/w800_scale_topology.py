# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict
"""Shared four-device scale topology for Wedge800 NPI test configs."""

from ixia.ixia import types as ixia_types
from taac.testconfigs.npi import (  # oss-rewrite-touch
    w800_constants as w800,
)
from taac.test_as_a_config import types as taac_types


W800_DIRECTIONAL_TRAFFIC_ITEM_NAMES: tuple[str, str] = (
    "V6_DIRECTIONAL_TRAFFIC_BETWEEN_DOWNLINK_AND_UPLINK",
    "V4_DIRECTIONAL_TRAFFIC_BETWEEN_DOWNLINK_AND_UPLINK",
)


def _create_scale_endpoints(
    test_config: taac_types.TestConfig,
) -> list[taac_types.Endpoint]:
    dut_endpoints = [endpoint for endpoint in test_config.endpoints if endpoint.dut]
    if len(dut_endpoints) != 1:
        raise ValueError(
            f"W800 scale topology requires one factory DUT; got {len(dut_endpoints)}"
        )

    dut_endpoint = dut_endpoints[0](ixia_ports=w800.W800_RSW_DUT_IXIA_PORTS)
    return [
        *[
            taac_types.Endpoint(name=device_name, dut=False)
            for device_name in w800.W800_FSW_DEVICE_NAMES
        ],
        dut_endpoint,
        taac_types.Endpoint(
            name=w800.W800_RSW_PEER_DEVICE_NAME,
            dut=False,
            ixia_ports=w800.W800_RSW_PEER_IXIA_PORTS,
            mac_address=w800.W800_RSW_PEER_LOCAL_MAC_ADDRESS,
        ),
    ]


def _create_directional_traffic_items() -> list[taac_types.BasicTrafficItemConfig]:
    frame_size = ixia_types.FrameSize(type=ixia_types.FrameSizeType.CUSTOM_IMIX)
    return [
        taac_types.BasicTrafficItemConfig(
            name=name,
            bidirectional=True,
            merge_destinations=True,
            line_rate=49,
            line_rate_type=ixia_types.RateType.PERCENT_LINE_RATE,
            src_dest_mesh=ixia_types.SrcDestMeshType.MANY_TO_MANY,
            src_endpoints=[
                taac_types.TrafficEndpoint(
                    name=(
                        f"{w800.W800_RSW_DUT_DEVICE_NAME}:"
                        f"{w800.W800_IXIA_UPLINK_INTERFACE}"
                    ),
                    network_group_index=0,
                    device_group_index=device_group_index,
                )
            ],
            dest_endpoints=[
                taac_types.TrafficEndpoint(
                    name=(
                        f"{w800.W800_RSW_PEER_DEVICE_NAME}:"
                        f"{w800.W800_RSW_PEER_IXIA_DOWNLINK_INTERFACE}"
                    ),
                    network_group_index=0,
                    device_group_index=device_group_index,
                )
            ],
            traffic_type=traffic_type,
            tracking_types=[ixia_types.TrafficStatsTrackingType.TRAFFIC_ITEM],
            frame_size_settings=frame_size,
        )
        for name, traffic_type, device_group_index in (
            (
                W800_DIRECTIONAL_TRAFFIC_ITEM_NAMES[0],
                ixia_types.TrafficType.IPV6,
                0,
            ),
            (
                W800_DIRECTIONAL_TRAFFIC_ITEM_NAMES[1],
                ixia_types.TrafficType.IPV4,
                1,
            ),
        )
    ]


def _create_peer_downlink_port_config(
    test_config: taac_types.TestConfig,
) -> taac_types.BasicPortConfig:
    dut_downlink_endpoint = (
        f"{w800.W800_RSW_DUT_DEVICE_NAME}:{w800.W800_IXIA_DOWNLINK_INTERFACE}"
    )
    matching_configs = [
        port_config
        for port_config in test_config.basic_port_configs or []
        if port_config.endpoint == dut_downlink_endpoint
    ]
    if len(matching_configs) != 1:
        raise ValueError(
            "W800 scale topology requires one DUT downlink IXIA port config; "
            f"got {len(matching_configs)}"
        )
    return matching_configs[0](
        endpoint=(
            f"{w800.W800_RSW_PEER_DEVICE_NAME}:"
            f"{w800.W800_RSW_PEER_IXIA_DOWNLINK_INTERFACE}"
        )
    )


def _replace_directional_traffic_items(
    test_config: taac_types.TestConfig,
) -> list[taac_types.BasicTrafficItemConfig]:
    replacements = {item.name: item for item in _create_directional_traffic_items()}
    traffic_items: list[taac_types.BasicTrafficItemConfig] = []
    for item in test_config.basic_traffic_item_configs or []:
        replacement = replacements.pop(item.name, None)
        traffic_items.append(replacement if replacement is not None else item)
    traffic_items.extend(replacements.values())
    return traffic_items


def apply_w800_scale_topology(
    test_config: taac_types.TestConfig,
    *,
    start_directional_traffic: bool,
) -> taac_types.TestConfig:
    """Apply the shared FSW/RSW topology and cross-RSW traffic profile."""
    endpoints = _create_scale_endpoints(test_config)
    basic_port_configs = [
        *(test_config.basic_port_configs or []),
        _create_peer_downlink_port_config(test_config),
    ]
    basic_traffic_item_configs = _replace_directional_traffic_items(test_config)
    if start_directional_traffic:
        return test_config(
            endpoints=endpoints,
            basic_port_configs=basic_port_configs,
            basic_traffic_item_configs=basic_traffic_item_configs,
            traffic_items_to_start=list(W800_DIRECTIONAL_TRAFFIC_ITEM_NAMES),
        )
    return test_config(
        endpoints=endpoints,
        basic_port_configs=basic_port_configs,
        basic_traffic_item_configs=basic_traffic_item_configs,
    )
