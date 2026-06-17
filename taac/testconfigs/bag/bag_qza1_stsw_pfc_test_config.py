# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""
Multi-node BAG <-> STSW PFC Test Configuration

PFC congestion test config spanning bag001.qza1 (EOS, ar-bgp) and
stsw003.s001.l201.qza1.tfbnw.net (FBOSS). Both devices connect to
ixia08.netcastle.ash6 on the same chassis.

Test cases (bidirectional, port speed 400G):
- BAG -> STSW: 3-source RDMA congestion, 1-source non-congestion, mixed
  RDMA/BE traffic
- STSW -> BAG: 2-source RDMA congestion, 1-source non-congestion, mixed
  RDMA/BE traffic
- Longevity: all 4 DSF protocols (RDMA, BE, NC, Monitoring) at 70% line
  rate in both directions

IXIA Port Mapping (all on ixia08.netcastle.ash6 slot 1):
  bag001.qza1:Ethernet13/1/1 <-> ixia 1/13
  bag001.qza1:Ethernet13/2/1 <-> ixia 1/10
  bag001.qza1:Ethernet14/1/1 <-> ixia 1/11
  bag001.qza1:Ethernet14/2/1 <-> ixia 1/12
  stsw003.s001.l201.qza1.tfbnw.net:eth1/63/1 <-> ixia 1/17
  stsw003.s001.l201.qza1.tfbnw.net:eth1/63/5 <-> ixia 1/18

BAG-side BGP (from `show bgp` / device_info_cli):
- bag001.qza1 own ASN: 65340
- IXIA simulates stsw013.s003.l201.qza1 (peer group PEERGROUP_BAG_STSW_LC{13,14}_V6),
  remote AS 65341
- Subnet for all 4 IXIA ports: 2401:db00:2d1b:d8d0::/64

STSW-side BGP (from `fboss2 show interface` / `fboss2 show bgp summary`):
- stsw003.s001.l201.qza1 own ASN: 65071
- IXIA simulates bag030.qza1 (production peer description), remote AS 65342
- Subnet for both IXIA ports: 2401:db00:2d1b:d8e0::/64

Operator note: stsw003.s001.l201.qza1.tfbnw.net is currently DRAINED. It must
be undrained before this test runs. Production BGP sessions on the IXIA-
connected ports are expected to be the only sessions on those subnets, so
IXIA reuses the production peer IPs exactly.
"""

from ixia.ixia import types as ixia_types
from taac.health_checks.healthcheck_definitions import (
    create_bgp_session_snapshot_check,
    create_core_dumps_snapshot_check,
    create_ixia_packet_loss_check,
    create_port_state_check,
)
from taac.playbooks.playbook_definitions import (
    create_bag_qza1_stsw_longevity_playbook,
    create_dsf_proto_ipv6_traffic_config,
    create_playbook_pfc_congestion,
    create_playbook_pfc_congestion_non_pfc_traffic,
    create_playbook_pfc_non_congestion,
    IXIA_ENABLE_PFC_PORT_CONFIG,
)
from taac.testconfigs.hyperport.hyperport_snc_bag_test_configs import (
    create_basic_port_config,
)
from taac.health_check.health_check import types as hc_types
from taac.test_as_a_config.types import (
    BasicTrafficItemConfig,
    Endpoint,
    Playbook,
    TestConfig,
    TrafficEndpoint,
)


# =============================================================================
# Constants
# =============================================================================
PORT_SPEED_GBPS = 400
LONGEVITY_DURATION_SEC = 360
PFC_TRAFFIC_DURATION_SEC = 60

# BAG side
BAG_HOSTNAME = "bag001.qza1"
BAG_OWN_ASN = 65340
# IXIA on the BAG side simulates stsw013.s003.l201.qza1 (the production
# downlink peer for bag001.qza1's Et13/x and Et14/x ports).
BAG_IXIA_PEER_AS = 65341

# STSW side
STSW_HOSTNAME = "stsw003.s001.l201.qza1"
STSW_OWN_ASN = 65071
# IXIA on the STSW side simulates bag030.qza1 (the production peer described
# in the eth1/63/x interface descriptions).
STSW_IXIA_PEER_AS = 65342

# Communities that pass production BGP ingress filtering on both sides.
#
# BAG side (IXIA -> bag001.qza1 via PEERGROUP_BAG_STSW_LC{13,14}_V6 ingress
# policy PROPAGATE_BAG_STSW_IN):
#   65520:52791  COMM_AI_ZONE_FABRIC_LOAD_AGG -- explicitly matched by
#                PROPAGATE_STSW_BAG_IN rules RULE_IBN_EDGE_IN_STSW_BAG_IN_520
#                and RULE_ADD_PREF_COMM_FOR_AI_ZONE_FABRIC_LOAD_AGG_530
#   65529:52780, 65529:52779  -- proven baseline from bag_qza1_test_config.py
#
# STSW side (IXIA -> stsw003 via PEERGROUP_STSW_BAG_V6 ingress policy
# PROPAGATE_STSW_BAG_IN) accepts the same set, validated against
# bgp_community_cli on stsw003.
BAG_BGP_COMMUNITIES = ["65529:52780", "65529:52779", "65520:52791"]
STSW_BGP_COMMUNITIES = BAG_BGP_COMMUNITIES


# =============================================================================
# Port Config Data: (port_name, ixia_ip, gateway_ip, starting_prefix)
#
# IXIA reuses the production peer IPs because the device-side BGP peers are
# expected to be inactive (STSW is drained, BAG's downlink peers go to a
# different STSW). Test prefixes use site-unique /64s that don't overlap with
# the production routing table.
# =============================================================================

# BAG (bag001.qza1): all 4 IXIA-connected ports share /64 2401:db00:2d1b:d8d0::/64
BAG001_QZA1_PORT_CONFIG_DATA = [
    # Et13/1/1 -- BAG ::, IXIA ::1
    ("Ethernet13/1/1", "2401:db00:2d1b:d8d0::1", "2401:db00:2d1b:d8d0::", "7000:1:1::"),
    # Et13/2/1 -- BAG ::2, IXIA ::3
    (
        "Ethernet13/2/1",
        "2401:db00:2d1b:d8d0::3",
        "2401:db00:2d1b:d8d0::2",
        "7000:1:2::",
    ),
    # Et14/1/1 -- BAG ::8, IXIA ::9
    (
        "Ethernet14/1/1",
        "2401:db00:2d1b:d8d0::9",
        "2401:db00:2d1b:d8d0::8",
        "7000:1:3::",
    ),
    # Et14/2/1 -- BAG ::a, IXIA ::b
    (
        "Ethernet14/2/1",
        "2401:db00:2d1b:d8d0::b",
        "2401:db00:2d1b:d8d0::a",
        "7000:1:4::",
    ),
]

# STSW (stsw003.s001.l201.qza1.tfbnw.net): both IXIA ports on /64 2401:db00:2d1b:d8e0::/64
STSW003_PORT_CONFIG_DATA = [
    # eth1/63/1 -- STSW ::1, IXIA ::
    ("eth1/63/1", "2401:db00:2d1b:d8e0::", "2401:db00:2d1b:d8e0::1", "7000:2:1::"),
    # eth1/63/5 -- STSW ::3, IXIA ::2
    ("eth1/63/5", "2401:db00:2d1b:d8e0::2", "2401:db00:2d1b:d8e0::3", "7000:2:2::"),
]

# IXIA port lists per device
BAG001_QZA1_IXIA_PORTS = [port for port, _, _, _ in BAG001_QZA1_PORT_CONFIG_DATA]
STSW003_IXIA_PORTS = [port for port, _, _, _ in STSW003_PORT_CONFIG_DATA]


# =============================================================================
# Endpoints (both devices are DUTs)
# =============================================================================
BAG_STSW_ENDPOINTS = [
    Endpoint(
        name=BAG_HOSTNAME,
        dut=True,
        ixia_ports=BAG001_QZA1_IXIA_PORTS,
    ),
    Endpoint(
        name=STSW_HOSTNAME,
        dut=True,
        ixia_ports=STSW003_IXIA_PORTS,
    ),
]


# =============================================================================
# Per-port Traffic Endpoints
# =============================================================================
BAG_PORT_13_1_ENDPOINT = TrafficEndpoint(
    name=f"{BAG_HOSTNAME}:Ethernet13/1/1",
    network_group_index=0,
    device_group_index=0,
)
BAG_PORT_13_2_ENDPOINT = TrafficEndpoint(
    name=f"{BAG_HOSTNAME}:Ethernet13/2/1",
    network_group_index=0,
    device_group_index=0,
)
BAG_PORT_14_1_ENDPOINT = TrafficEndpoint(
    name=f"{BAG_HOSTNAME}:Ethernet14/1/1",
    network_group_index=0,
    device_group_index=0,
)
BAG_PORT_14_2_ENDPOINT = TrafficEndpoint(
    name=f"{BAG_HOSTNAME}:Ethernet14/2/1",
    network_group_index=0,
    device_group_index=0,
)
STSW_PORT_63_1_ENDPOINT = TrafficEndpoint(
    name=f"{STSW_HOSTNAME}:eth1/63/1",
    network_group_index=0,
    device_group_index=0,
)
STSW_PORT_63_5_ENDPOINT = TrafficEndpoint(
    name=f"{STSW_HOSTNAME}:eth1/63/5",
    network_group_index=0,
    device_group_index=0,
)

# Source / destination groupings per direction.
# BAG->STSW: 3 BAG sources (Et13/1, Et13/2, Et14/1) -> 1 STSW dest (eth1/63/1).
# Et14/2 is held in reserve (not used in PFC playbooks but available for DSF
# longevity traffic).
B2S_SRC_ENDPOINTS = [
    BAG_PORT_13_1_ENDPOINT,
    BAG_PORT_13_2_ENDPOINT,
    BAG_PORT_14_1_ENDPOINT,
]
B2S_DST_ENDPOINTS = [STSW_PORT_63_1_ENDPOINT]

# STSW->BAG: 2 STSW sources -> 1 BAG dest (Et13/1).
S2B_SRC_ENDPOINTS = [STSW_PORT_63_1_ENDPOINT, STSW_PORT_63_5_ENDPOINT]
S2B_DST_ENDPOINTS = [BAG_PORT_13_1_ENDPOINT]


# =============================================================================
# BasicPortConfig list (per device, eBGP, PFC L1 enabled)
# =============================================================================
BAG_BASIC_PORT_CONFIGS = [
    create_basic_port_config(
        endpoint=f"{BAG_HOSTNAME}:{port}",
        starting_ip=ixia_ip,
        gateway_ip=gateway_ip,
        local_as=BAG_IXIA_PEER_AS,
        bgp_peer_type=ixia_types.BgpPeerType.EBGP,
        starting_prefixes=starting_prefix,
        bgp_communities=BAG_BGP_COMMUNITIES,
        l1_config=IXIA_ENABLE_PFC_PORT_CONFIG.l1_config,
    )
    for port, ixia_ip, gateway_ip, starting_prefix in BAG001_QZA1_PORT_CONFIG_DATA
]

STSW_BASIC_PORT_CONFIGS = [
    create_basic_port_config(
        endpoint=f"{STSW_HOSTNAME}:{port}",
        starting_ip=ixia_ip,
        gateway_ip=gateway_ip,
        local_as=STSW_IXIA_PEER_AS,
        bgp_peer_type=ixia_types.BgpPeerType.EBGP,
        starting_prefixes=starting_prefix,
        bgp_communities=STSW_BGP_COMMUNITIES,
        l1_config=IXIA_ENABLE_PFC_PORT_CONFIG.l1_config,
    )
    for port, ixia_ip, gateway_ip, starting_prefix in STSW003_PORT_CONFIG_DATA
]

ALL_BASIC_PORT_CONFIGS = BAG_BASIC_PORT_CONFIGS + STSW_BASIC_PORT_CONFIGS


# =============================================================================
# DSF protocol traffic items (longevity baseline, 70% line rate, all 4 protos
# in both directions). Each src endpoint maps to the single dst endpoint via
# ONE_TO_ONE meshing inside `create_dsf_proto_ipv6_traffic_config`.
# =============================================================================
def _build_dsf_traffic_items(
    direction_prefix: str,
    src_endpoints: list[TrafficEndpoint],
    dst_endpoints: list[TrafficEndpoint],
) -> list[BasicTrafficItemConfig]:
    """Build per-protocol DSF traffic items for one direction at 70% rate."""
    return [
        create_dsf_proto_ipv6_traffic_config(
            proto=proto,
            src_endpoints=src_endpoints,
            dest_endpoints=dst_endpoints,
            name=f"DSF_{proto}_{direction_prefix}_70PCT",
            line_rate=70,
        )
        # Match the protocol set used by hyperport_vrf_bag_test_configs.py.
        # RDMA_IB carries the IB transport header expected by the BAG/STSW
        # forwarding policies for RDMA classification.
        for proto in ("NC", "MONITORING", "BE", "RDMA_IB")
    ]


B2S_DSF_TRAFFIC_ITEMS = _build_dsf_traffic_items(
    "BAG_TO_STSW", B2S_SRC_ENDPOINTS, B2S_DST_ENDPOINTS
)
S2B_DSF_TRAFFIC_ITEMS = _build_dsf_traffic_items(
    "STSW_TO_BAG", S2B_SRC_ENDPOINTS, S2B_DST_ENDPOINTS
)


# =============================================================================
# Longevity RDMA traffic items
#
# Two dedicated per-port-pair RDMA streams (BAG -> STSW), each at 95% line
# rate. These are the only items started by the longevity playbook -- the
# DSF protocol items above are defined for ad-hoc use but not auto-started.
# =============================================================================
LONGEVITY_RDMA_BAG_13_1_TO_STSW_63_1_NAME = "RDMA_BAG_13_1_TO_STSW_63_1"
LONGEVITY_RDMA_BAG_13_2_TO_STSW_63_1_NAME = "RDMA_BAG_13_2_TO_STSW_63_1"

LONGEVITY_RDMA_TRAFFIC_ITEMS = [
    create_dsf_proto_ipv6_traffic_config(
        proto="RDMA_IB",
        src_endpoints=[BAG_PORT_13_1_ENDPOINT],
        dest_endpoints=[STSW_PORT_63_1_ENDPOINT],
        name=LONGEVITY_RDMA_BAG_13_1_TO_STSW_63_1_NAME,
        line_rate=95,
    ),
    create_dsf_proto_ipv6_traffic_config(
        proto="RDMA_IB",
        src_endpoints=[BAG_PORT_13_2_ENDPOINT],
        dest_endpoints=[STSW_PORT_63_1_ENDPOINT],
        name=LONGEVITY_RDMA_BAG_13_2_TO_STSW_63_1_NAME,
        line_rate=95,
    ),
]

LONGEVITY_TRAFFIC_ITEM_NAMES = [item.name for item in LONGEVITY_RDMA_TRAFFIC_ITEMS]


# =============================================================================
# PFC traffic items + playbooks per direction
# =============================================================================
def _build_pfc_traffic_items_and_playbooks(
    direction_prefix: str,
    src_endpoints: list[TrafficEndpoint],
    dst_endpoints: list[TrafficEndpoint],
) -> tuple[list[BasicTrafficItemConfig], list[Playbook]]:
    """Build PFC traffic items and the 3 congestion playbooks for one direction."""
    # 90% RDMA per source -- used by congestion (all sources) and
    # non-congestion (first source only) playbooks.
    rdma_90pct_names = []
    traffic_items: list[BasicTrafficItemConfig] = []
    for i, src in enumerate(src_endpoints, 1):
        name = f"{direction_prefix}_RDMA_90PCT_P{i}"
        traffic_items.append(
            create_dsf_proto_ipv6_traffic_config(
                proto="RDMA",
                src_endpoints=[src],
                dest_endpoints=dst_endpoints,
                name=name,
                line_rate=90,
            )
        )
        rdma_90pct_names.append(name)

    # 30% RDMA per source -- used by mixed-traffic playbook (combined with
    # 24% BE so total PFC traffic stays below 100% line rate).
    rdma_30pct_names = []
    for i, src in enumerate(src_endpoints, 1):
        name = f"{direction_prefix}_RDMA_30PCT_P{i}"
        traffic_items.append(
            create_dsf_proto_ipv6_traffic_config(
                proto="RDMA",
                src_endpoints=[src],
                dest_endpoints=dst_endpoints,
                name=name,
                line_rate=30,
            )
        )
        rdma_30pct_names.append(name)

    # 24% BE from a single source -- the lossy companion in the mixed-traffic
    # playbook. Source index 1 mirrors the hyperport pattern.
    be_name = f"{direction_prefix}_BE_24PCT"
    traffic_items.append(
        create_dsf_proto_ipv6_traffic_config(
            proto="BE",
            src_endpoints=[src_endpoints[min(1, len(src_endpoints) - 1)]],
            dest_endpoints=dst_endpoints,
            name=be_name,
            line_rate=24,
        )
    )

    direction_label = direction_prefix.lower()
    playbooks = [
        create_playbook_pfc_congestion(
            name=f"test_pfc_congestion_{direction_label}",
            rdma_traffic_items_names=rdma_90pct_names,
            src_endpoints=src_endpoints,
            dst_endpoints=dst_endpoints,
            traffic_duration=PFC_TRAFFIC_DURATION_SEC,
        ),
        create_playbook_pfc_non_congestion(
            name=f"test_pfc_non_congestion_{direction_label}",
            rdma_traffic_items_names=rdma_90pct_names,
            src_endpoints=src_endpoints,
            dst_endpoints=dst_endpoints,
            traffic_duration=PFC_TRAFFIC_DURATION_SEC,
        ),
        create_playbook_pfc_congestion_non_pfc_traffic(
            name=f"test_pfc_congestion_non_tc2_traffic_{direction_label}",
            pfc_traffic_items_names=rdma_30pct_names,
            be_traffic_item_name=be_name,
            src_endpoints=src_endpoints,
            dst_endpoints=dst_endpoints,
            traffic_duration=PFC_TRAFFIC_DURATION_SEC,
        ),
    ]
    return traffic_items, playbooks


B2S_PFC_TRAFFIC_ITEMS, B2S_PFC_PLAYBOOKS = _build_pfc_traffic_items_and_playbooks(
    "B2S", B2S_SRC_ENDPOINTS, B2S_DST_ENDPOINTS
)
S2B_PFC_TRAFFIC_ITEMS, S2B_PFC_PLAYBOOKS = _build_pfc_traffic_items_and_playbooks(
    "S2B", S2B_SRC_ENDPOINTS, S2B_DST_ENDPOINTS
)

ALL_TRAFFIC_ITEM_CONFIGS = (
    LONGEVITY_RDMA_TRAFFIC_ITEMS
    + B2S_DSF_TRAFFIC_ITEMS
    + S2B_DSF_TRAFFIC_ITEMS
    + B2S_PFC_TRAFFIC_ITEMS
    + S2B_PFC_TRAFFIC_ITEMS
)


# =============================================================================
# TestConfig builder
# =============================================================================
def _attach_tc_checks(
    playbook: Playbook,
    prechecks: list,
    postchecks: list,
    snapshot_checks: list,
) -> Playbook:
    """Append TestConfig-level checks to a playbook (Thrift copy-with-update)."""
    return playbook(
        prechecks=list(playbook.prechecks or []) + prechecks,
        postchecks=list(playbook.postchecks or []) + postchecks,
        snapshot_checks=list(playbook.snapshot_checks or []) + snapshot_checks,
    )


def create_bag_qza1_stsw_pfc_test_config(
    test_config_name: str = "BAG_QZA1_STSW_PFC_TEST_CONFIG",
    longevity_duration: int = LONGEVITY_DURATION_SEC,
) -> TestConfig:
    """Build the multi-node BAG <-> STSW PFC test config."""
    tc_prechecks = [
        create_ixia_packet_loss_check(
            thresholds=[hc_types.PacketLossThreshold(str_value="0.1")],
            clear_traffic_stats=True,
        )(check_scope=hc_types.Scope.DEFAULT),
        create_port_state_check()(check_scope=hc_types.Scope.DEFAULT),
    ]
    tc_postchecks = [
        create_ixia_packet_loss_check(
            thresholds=[
                hc_types.PacketLossThreshold(
                    str_value="0",
                    metric=hc_types.PacketLossMetric.PERCENTAGE,
                ),
            ],
        )(check_scope=hc_types.Scope.DEFAULT),
        create_port_state_check()(check_scope=hc_types.Scope.DEFAULT),
    ]
    tc_snapshot_checks = [
        create_core_dumps_snapshot_check()(check_scope=hc_types.Scope.DEFAULT),
        create_bgp_session_snapshot_check()(check_scope=hc_types.Scope.DEFAULT),
    ]

    longevity_playbook = create_bag_qza1_stsw_longevity_playbook(
        longevity_duration=longevity_duration,
        # pyrefly: ignore [bad-argument-type]
        traffic_items_to_start=LONGEVITY_TRAFFIC_ITEM_NAMES,
        prechecks=tc_prechecks,
        postchecks=tc_postchecks,
        snapshot_checks=tc_snapshot_checks,
    )

    pfc_playbooks = [
        _attach_tc_checks(pb, tc_prechecks, tc_postchecks, tc_snapshot_checks)
        for pb in (B2S_PFC_PLAYBOOKS + S2B_PFC_PLAYBOOKS)
    ]

    return TestConfig(
        name=test_config_name,
        endpoints=BAG_STSW_ENDPOINTS,
        setup_tasks=[],
        basic_port_configs=ALL_BASIC_PORT_CONFIGS,
        basic_traffic_item_configs=ALL_TRAFFIC_ITEM_CONFIGS,
        playbooks=[longevity_playbook, *pfc_playbooks],
    )


BAG_QZA1_STSW_PFC_TEST_CONFIGS = [create_bag_qza1_stsw_pfc_test_config()]
