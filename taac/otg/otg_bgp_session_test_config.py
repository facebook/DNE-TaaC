# pyre-unsafe
"""OTG BGP session establishment + forwarding test config.

Exercises the full OTG backend with IPv4 eBGP peering: TestConfig ->
TrafficGenerator pipeline -> OtgTrafficGenerator -> OtgTrafficGen -> snappi.

Each OTG port establishes an eBGP session with the DUT and advertises a
small pool of IPv4 prefixes.  Bidirectional traffic is forwarded between
the two ports via the DUT's connected routes (device-group IPs), while
the BGP sessions validate protocol establishment and route advertisement.

OTG setup requirements
~~~~~~~~~~~~~~~~~~~~~~
An OTG-compatible traffic generator with at least two ports, reachable via
the snappi HTTPS API (ixia-c, Keysight hardware chassis with OTG API, etc.).

Each OTG port must have L2 connectivity to a distinct DUT interface.

Logical topology (two ports, two subnets, eBGP):

  OTG port 1 (eth1)  <-- L2 --> DUT interface A    10.0.1.0/24
    10.0.1.1, AS 65001 (eBGP)    10.0.1.2, AS 65000
    advertises 198.51.100.0/24 (10 prefixes)

  OTG port 2 (eth2)  <-- L2 --> DUT interface B    10.0.2.0/24
    10.0.2.1, AS 65001 (eBGP)    10.0.2.2, AS 65000
    advertises 203.0.113.0/24 (10 prefixes)

DUT requirements:
  - bgpcpp.conf with two IPv4 eBGP peer entries matching the OTG addresses
    (see taac/otg/configs/otg_bgp_session_bgpcpp.conf for a reference config)
  - Interface A: 10.0.1.2/24
  - Interface B: 10.0.2.2/24
  - L3 forwarding enabled between the two subnets

This test config uses the @topology_aware decorator so port and device
information is discovered from the circuit_info CSV at runtime.

Example invocation:

% export TAAC_OSS=1 TAAC_SSH_USER=root TAAC_SSH_PASSWORD=root
% ./docker/run_taac_docker.sh run python3 -m taac.runner.oss_entry_point \
      --test-configs /workspace/taac/otg/otg_bgp_session_test_config.py \
      --dut <dut> \
      --ixia-api-server https://<otg-api-host>:8443 \
      --device-info-csv /workspace/examples/topology/otg_l3_forwarding_device_info.csv \
      --circuit-info-csv /workspace/examples/topology/otg_l3_forwarding_circuit_info.csv \
      --skip-post-setup-wait
"""

import typing as t

from ixia.ixia import types as ixia_types
from taac.health_check.health_check import types as hc_types
from taac.runner.testbed_topology import (
    ConfigTopology,
    LinkType,
    topology_aware,
)
from taac.steps.step_definitions import create_longevity_step
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import (
    BasicPortConfig,
    BasicTrafficItemConfig,
    BgpConfig,
    DeviceGroupConfig,
    DirectIxiaConnection,
    Endpoint,
    IpAddressesConfig,
    Playbook,
    PointInTimeHealthCheck,
    RouteScale,
    RouteScaleSpec,
    Stage,
    TestConfig,
    TrafficEndpoint,
)

OTG_LOCAL_AS = 65001

BGP_HOLD_TIMER = 90
BGP_KEEPALIVE_TIMER = 30

BGP_PREFIX_COUNT = 10
BGP_PREFIX_LENGTH = 24

TRAFFIC_DURATION_SEC = 30
TRAFFIC_FRAMES_PER_SEC = 1000

_ADVERTISED_PREFIXES = ["198.51.100.0", "203.0.113.0"]


def _v4_subnet_ip(index: int, host: int) -> str:
    return f"10.0.{index + 1}.{host}"


def _tgen_links(
    topology: ConfigTopology,
) -> t.List[t.Tuple[str, str, str, str]]:
    """Extract TGEN links as (dut_host, dut_port, tgen_host, tgen_port)."""
    links = []
    for link in topology.links:
        if link.link_type == LinkType.TGEN:
            links.append(
                (link.local_host, link.local_port, link.remote_host, link.remote_port)
            )
    return links


@topology_aware
def test_config(topology: ConfigTopology) -> TestConfig:
    """Generate an OTG BGP session + forwarding test config from topology.

    Discovers TGEN links from the circuit CSV and builds:
    - Two OTG ports with IPv4 device groups and eBGP peering
    - Route advertisement (distinct prefix pool per port)
    - Bidirectional IPv4 traffic between the two ports
    """
    tgen_links = _tgen_links(topology)
    if len(tgen_links) < 2:
        raise RuntimeError(
            f"BGP session test requires at least 2 TGEN links in the circuit CSV, "
            f"found {len(tgen_links)}: {tgen_links}"
        )

    tgen_links = tgen_links[:2]
    device_name = tgen_links[0][0]

    direct_ixia_connections = []
    basic_port_configs = []

    for i, (_, _, _, tgen_port) in enumerate(tgen_links):
        endpoint_str = f"{device_name}:{tgen_port}"

        direct_ixia_connections.append(
            DirectIxiaConnection(
                interface=tgen_port,
                ixia_port=f"1/{i + 1}",
                is_logical_port=True,
                port_location=tgen_port,
            )
        )

        basic_port_configs.append(
            BasicPortConfig(
                endpoint=endpoint_str,
                device_group_configs=[
                    DeviceGroupConfig(
                        device_group_index=0,
                        multiplier=1,
                        enable=True,
                        device_group_name=f"DG_BGP_PORT{i + 1}",
                        v4_addresses_config=IpAddressesConfig(
                            starting_ip=_v4_subnet_ip(i, 1),
                            gateway_starting_ip=_v4_subnet_ip(i, 2),
                            mask=24,
                        ),
                        v4_bgp_config=BgpConfig(
                            local_as_4_bytes=OTG_LOCAL_AS,
                            enable_4_byte_local_as=True,
                            bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                            bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                            hold_timer=BGP_HOLD_TIMER,
                            keepalive_timer=BGP_KEEPALIVE_TIMER,
                            route_scales=[
                                RouteScaleSpec(
                                    network_group_index=0,
                                    v4_route_scale=RouteScale(
                                        multiplier=1,
                                        prefix_count=BGP_PREFIX_COUNT,
                                        prefix_length=BGP_PREFIX_LENGTH,
                                        starting_prefixes=_ADVERTISED_PREFIXES[i],
                                        ip_address_family=ixia_types.IpAddressFamily.IPV4,
                                    ),
                                ),
                            ],
                        ),
                    ),
                ],
            )
        )

    src_endpoint = f"{device_name}:{tgen_links[0][3]}"
    dst_endpoint = f"{device_name}:{tgen_links[1][3]}"

    bgp_playbook = Playbook(
        name="otg_bgp_session",
        stages=[
            Stage(
                steps=[
                    create_longevity_step(duration=TRAFFIC_DURATION_SEC),
                ],
            ),
        ],
        prechecks=[
            PointInTimeHealthCheck(
                name=hc_types.CheckName.WEDGE_AGENT_CONFIGURED_CHECK,
            ),
            PointInTimeHealthCheck(
                name=hc_types.CheckName.SYSTEMCTL_ACTIVE_STATE_CHECK,
                input_json='{"services": [1]}',
            ),
            PointInTimeHealthCheck(
                name=hc_types.CheckName.DEVICE_CORE_DUMPS_CHECK,
            ),
        ],
        postchecks=[
            PointInTimeHealthCheck(
                name=hc_types.CheckName.IXIA_PACKET_LOSS_CHECK,
                input_json=(
                    '{"thresholds":[{"metric":3,"str_value":"0.1",'
                    '"expect_packet_loss":false,"comparison":3}],'
                    '"sleep_time":10,"clear_traffic_stats":false}'
                ),
            ),
            PointInTimeHealthCheck(
                name=hc_types.CheckName.DEVICE_CORE_DUMPS_CHECK,
            ),
        ],
        snapshot_checks=[],
    )

    return TestConfig(
        name="OTG_BGP_SESSION",
        basset_pool="",
        traffic_generator_backend=taac_types.TrafficGeneratorBackend.OTG,
        skip_ixia_protocol_verification=False,
        endpoints=[
            Endpoint(
                name=device_name,
                dut=True,
                direct_ixia_connections=direct_ixia_connections,
            ),
        ],
        basic_port_configs=basic_port_configs,
        basic_traffic_item_configs=[
            BasicTrafficItemConfig(
                name="bgp_v4_forwarding",
                traffic_type=ixia_types.TrafficType.IPV4,
                src_endpoints=[
                    TrafficEndpoint(
                        name=src_endpoint,
                        device_group_index=0,
                    ),
                ],
                dest_endpoints=[
                    TrafficEndpoint(
                        name=dst_endpoint,
                        device_group_index=0,
                    ),
                ],
                line_rate=TRAFFIC_FRAMES_PER_SEC,
                line_rate_type=ixia_types.RateType.FRAMES_PER_SECOND,
                bidirectional=True,
            ),
        ],
        playbooks=[bgp_playbook],
        host_os_type_map={device_name: taac_types.DeviceOsType.FBOSS},
    )
