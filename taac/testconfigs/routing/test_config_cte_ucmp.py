# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""
CTE UCMP Test Configuration

This test config implements CTE UCMP test cases for Inter-DC VIP Traffic Balancing.

Test Cases:
  - Test Case 1: Progressive DC bring-up (1, 1a, 1b)
  - Test Case 3: ECMP to UCMP transition (initial CTE deployment)

Topology Overview:
==================

  Traffic Source (fa001-du004 - DUT):
    - Advertises VIP_V6_SOURCE (2402:db00:1000::/64) with community 65441:260
    - This is the DUT where UCMP policy is configured and tested
    - Receives VIP advertisements from the 3 DCs (spines) via IXIA

  3 Data Centers (Simulated by IXIA on 3 Spine Switches):
    DC1 (ssw004.s002): AS 65403 (spine AS), Prepends 64901, Weight 10
      - Advertises VIP_V6_DC1 (2402:db00:1000::/64) with community 65441:260
      - AS_PATH: 65403 64901 (prepends DC1_ASN to differentiate from other DCs)
      - DeviceGroupConfig starts DISABLED (enable=False)
      - Enabled by playbook "bringup_shiv_dc1" (Test Case 1)

    DC2 (ssw004.s003): AS 65403 (spine AS), Prepends 64902, Weight 5
      - Advertises VIP_V6_DC2 (2402:db00:1000::/64) with community 65441:260
      - AS_PATH: 65403 64902 (prepends DC2_ASN to differentiate from other DCs)
      - DeviceGroupConfig starts DISABLED (enable=False)
      - Enabled by playbook "bringup_shiv_dc2" (Test Case 1a)

    DC3 (ssw004.s004): AS 65403 (spine AS), Prepends 64903, Weight 2
      - Advertises VIP_V6_DC3 (2402:db00:1000::/64) with community 65441:260
      - AS_PATH: 65403 64903 (prepends DC3_ASN to differentiate from other DCs)
      - DeviceGroupConfig starts DISABLED (enable=False)
      - Enabled by playbook "bringup_shiv_dc3" (Test Case 1b)

Test Flow:
==========
  1. Pre-test: All 3 DC DeviceGroups are DISABLED (no VIP advertisements)
  2. Test Case 1 (bringup_shiv_dc1):
     - Playbook enables VIP_V6_DC1 via IXIA activate_deactivate_bgp_prefix
     - fa001-du004 receives VIP routes from DC1 only
     - UCMP policy configured with all 3 DC weights
     - Traffic flows 100% to DC1 (only DC online)
  3. Test Case 1a (bringup_shiv_dc2):
     - Playbook enables VIP_V6_DC2
     - fa001-du004 receives VIP routes from DC1 and DC2
     - Traffic redistributes: DC1 66.67% (weight 10), DC2 33.33% (weight 5)
  4. Test Case 1b (bringup_shiv_dc3):
     - Playbook enables VIP_V6_DC3
     - fa001-du004 receives VIP routes from all 3 DCs
     - Final traffic: DC1 58.8% (10/17), DC2 29.4% (5/17), DC3 11.8% (2/17)

IMPORTANT Notes:
================
  - All 3 spines share the same AS (65403) as they're part of the same spine layer
  - DCs are differentiated using AS_PATH prepending (64901, 64902, 64903)
  - The 3 spine DeviceGroupConfigs MUST start with enable=False
  - Each playbook's custom step enables the corresponding DC via IXIA API
  - All 3 DCs advertise the SAME VIP prefix (2402:db00:1000::/64)
  - UCMP policy on fa001-du004 assigns weights based on AS_PATH matching (matches prepended ASNs)
"""

from ixia.ixia import types as ixia_types
from taac.health_checks.healthcheck_definitions import (
    create_core_dumps_snapshot_check,
    create_lldp_check,
    create_port_state_check,
)
from taac.playbooks.playbook_definitions import (
    create_extra_weights_added_to_policy,
    create_test_case_10_playbooks,
    create_test_case_12_playbooks,
    create_test_case_13_playbooks,
    create_test_case_14_playbooks,
    create_test_case_1_playbooks,
    create_test_case_3_playbooks,
    create_test_case_4_playbooks,
    create_test_case_6_playbooks,
    create_test_case_7_playbooks,
    create_test_case_8_playbooks,
    create_test_case_9_playbooks,
    create_test_case_fallback_to_ecmp_playbooks,
)
from taac.test_as_a_config.types import (
    BasicPortConfig,
    BasicTrafficItemConfig,
    BgpConfig,
    DeviceGroupConfig,
    Endpoint,
    IpAddressesConfig,
    Playbook,
    RouteScale,
    RouteScaleSpec,
    TestConfig,
    TrafficEndpoint,
)


_CTE_UCMP_PRECHECKS = [
    create_lldp_check(),
    create_port_state_check(),
]

_CTE_UCMP_POSTCHECKS = [
    create_lldp_check(),
    create_port_state_check(),
]

_CTE_UCMP_SNAPSHOT_CHECKS = [
    create_core_dumps_snapshot_check(),
]


def _add_checks_to_playbooks(
    playbooks: list[Playbook],
) -> list[Playbook]:
    """Add standard prechecks/postchecks/snapshot_checks to each playbook."""
    return [
        pb(
            prechecks=list(pb.prechecks or []) + _CTE_UCMP_PRECHECKS,
            postchecks=list(pb.postchecks or []) + _CTE_UCMP_POSTCHECKS,
            snapshot_checks=list(pb.snapshot_checks or []) + _CTE_UCMP_SNAPSHOT_CHECKS,
        )
        for pb in playbooks
    ]


# VIP Configuration Constants
VIP_V4 = "203.0.113.0/24"
VIP_V6 = "2402:db00:1100::/64"  # VIP prefix (matches VIP_V6_SOURCE in test config)
VIP_V6_WITHOUT_MASK = "2402:db00:1100"
VIP_COMMUNITY = "65441:260"  # Community for VIP routes (must match BGP advertisements)


NON_VIP_COMMUNITY = "65441:132"
# Non-VIP Configuration Constants (for TC6 Policy Isolation)
NON_VIP_V6 = "2402:db00:1300::/64"  # Non-VIP prefix (no community tag)
NON_VIP_V6_WITHOUT_MASK = "2402:db00:1300"

# DC Configuration
DC1_ASN = 50001
DC2_ASN = 50002
DC3_ASN = 50003

# UCMP Weights
DC1_WEIGHT = 10
DC2_WEIGHT = 5
DC3_WEIGHT = 2


# QZD Lab Test Config for CTE UCMP Testing
# Based https://docs.google.com/document/d/1fW6Guu8_cpOj9g_YVuWZMtqAD4SEvwSozQILv9bKEhk/edit?tab=t.tr8agcvhi35g#heading=h.202a1dd60gt0
CTE_UCMP_QZD_TEST = TestConfig(
    name="CTE_UCMP_QZD_TEST",
    skip_ixia_protocol_verification=True,
    basset_pool="dne.test",
    log_collection_timeout=180,
    basset_reservation_time_hr=4,
    ignore_down_circuits=True,
    ignore_circuit_fbnet_status=False,
    endpoints=[
        # fa-du device is the DUT where we configure UCMP policy
        Endpoint(
            name="fa001-du004.qzd1",
            dut=True,
            ixia_ports=["eth6/16/1"],
        ),
        # Spine switches are part of network topology (non-DUTs)
        Endpoint(
            name="ssw004.s002.f01.qzd1",
            dut=False,
            ixia_ports=["eth8/16/1"],
        ),
        Endpoint(
            name="ssw004.s003.f01.qzd1",
            dut=False,
            ixia_ports=["eth8/16/1"],
        ),
        Endpoint(
            name="ssw004.s004.f01.qzd1",
            dut=False,
            ixia_ports=["eth8/16/1"],
        ),
    ],
    # Deprecated - define at playbook level
    # prechecks - moved to playbook level
    # postchecks - moved to playbook level
    # snapshot_checks - moved to playbook level
    basic_port_configs=[
        BasicPortConfig(
            endpoint="fa001-du004.qzd1:eth6/16/1",
            device_group_configs=[
                DeviceGroupConfig(
                    device_group_index=0,
                    multiplier=1,
                    v6_addresses_config=IpAddressesConfig(
                        starting_ip="2401:db00:e50f:3:6::2",
                        gateway_starting_ip="2401:db00:e50f:3:6::1",
                    ),
                    v6_bgp_config=BgpConfig(
                        local_as_4_bytes=64903,  # AS for fa001-du004
                        enable_4_byte_local_as=True,
                        bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                        enable_graceful_restart=True,
                        graceful_restart_timer=120,
                        advertise_end_of_rib=True,
                        route_scales=[
                            RouteScaleSpec(
                                network_group_index=0,
                                multiplier=1,
                                v6_route_scale=RouteScale(
                                    prefix_name="VIP_V6_SOURCE",
                                    starting_prefixes="2402:db00:1200::",
                                    prefix_length=64,
                                    multiplier=1,
                                    prefix_count=1000,
                                    ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                    bgp_communities=["65441:260"],
                                ),
                            ),
                        ],
                    ),
                ),
            ],
        ),
        BasicPortConfig(
            endpoint="ssw004.s002.f01.qzd1:eth8/16/1",
            device_group_configs=[
                DeviceGroupConfig(
                    device_group_index=0,
                    multiplier=1,
                    enable=False,  # Start disabled, enabled by playbook when DC1 comes online
                    device_group_name="IXIA_DC1_ADVERTISER",  # Single device group for DC1
                    v6_addresses_config=IpAddressesConfig(
                        starting_ip="2401:db00:e50d:311:8::2",
                        gateway_starting_ip="2401:db00:e50d:311:8::1",
                    ),
                    v6_bgp_config=BgpConfig(
                        local_as_4_bytes=65403,  # All spines share same AS
                        enable_4_byte_local_as=True,
                        bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                        enable_graceful_restart=True,
                        graceful_restart_timer=120,
                        advertise_end_of_rib=True,
                        route_scales=[
                            # Network Group 0: VIP routes (UCMP)
                            RouteScaleSpec(
                                network_group_index=0,
                                multiplier=1,
                                v6_route_scale=RouteScale(
                                    prefix_name="VIP_V6_DC1",
                                    starting_prefixes="2402:db00:1100::",
                                    prefix_length=64,
                                    multiplier=1,
                                    prefix_count=1000,
                                    ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                    bgp_communities=["65441:259"],
                                    as_path_prepend_numbers=[
                                        [DC1_ASN]
                                    ],  # Prepend DC1 ASN to differentiate
                                ),
                            ),
                            # Network Group 1: Non-VIP routes (ECMP)
                            RouteScaleSpec(
                                network_group_index=1,
                                multiplier=1,
                                v6_route_scale=RouteScale(
                                    prefix_name="NON_VIP_V6_DC1",
                                    starting_prefixes=NON_VIP_V6_WITHOUT_MASK + "::",
                                    prefix_length=64,
                                    multiplier=1,
                                    prefix_count=1000,
                                    ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                    bgp_communities=[
                                        "65529:34814",
                                        "65441:131",
                                    ],
                                    as_path_prepend_numbers=[
                                        [DC1_ASN]
                                    ],  # Same AS_PATH as VIP routes
                                ),
                            ),
                        ],
                    ),
                ),
            ],
        ),
        BasicPortConfig(
            endpoint="ssw004.s003.f01.qzd1:eth8/16/1",
            device_group_configs=[
                DeviceGroupConfig(
                    device_group_index=0,
                    multiplier=1,
                    enable=False,  # Start disabled, enabled by playbook when DC2 comes online
                    device_group_name="IXIA_DC2_ADVERTISER",  # Single device group for DC2
                    v6_addresses_config=IpAddressesConfig(
                        starting_ip="2401:db00:e50d:321:8::2",
                        gateway_starting_ip="2401:db00:e50d:321:8::1",
                    ),
                    v6_bgp_config=BgpConfig(
                        local_as_4_bytes=65403,  # All spines share same AS
                        enable_4_byte_local_as=True,
                        bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                        enable_graceful_restart=True,
                        graceful_restart_timer=120,
                        advertise_end_of_rib=True,
                        route_scales=[
                            # Network Group 0: VIP routes (UCMP)
                            RouteScaleSpec(
                                network_group_index=0,
                                multiplier=1,
                                v6_route_scale=RouteScale(
                                    prefix_name="VIP_V6_DC2",
                                    starting_prefixes="2402:db00:1100::",
                                    prefix_length=64,
                                    multiplier=1,
                                    prefix_count=1000,
                                    ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                    bgp_communities=["65441:259"],
                                    as_path_prepend_numbers=[
                                        [DC2_ASN]
                                    ],  # Prepend DC2 ASN to differentiate
                                ),
                            ),
                            # Network Group 1: Non-VIP routes (ECMP)
                            RouteScaleSpec(
                                network_group_index=1,
                                multiplier=1,
                                v6_route_scale=RouteScale(
                                    prefix_name="NON_VIP_V6_DC2",
                                    starting_prefixes=NON_VIP_V6_WITHOUT_MASK + "::",
                                    prefix_length=64,
                                    multiplier=1,
                                    prefix_count=1000,
                                    ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                    bgp_communities=[
                                        "65529:34814",
                                        "65441:131",
                                    ],
                                    as_path_prepend_numbers=[
                                        [DC2_ASN]
                                    ],  # Same AS_PATH as VIP routes
                                ),
                            ),
                        ],
                    ),
                ),
            ],
        ),
        BasicPortConfig(
            endpoint="ssw004.s004.f01.qzd1:eth8/16/1",
            device_group_configs=[
                DeviceGroupConfig(
                    device_group_index=0,
                    multiplier=1,
                    enable=False,  # Start disabled, enabled by playbook when DC3 comes online
                    device_group_name="IXIA_DC3_ADVERTISER",  # Single device group for DC3
                    v6_addresses_config=IpAddressesConfig(
                        starting_ip="2401:db00:e50d:331:8::2",
                        gateway_starting_ip="2401:db00:e50d:331:8::1",
                    ),
                    v6_bgp_config=BgpConfig(
                        local_as_4_bytes=65403,  # All spines share same AS
                        enable_4_byte_local_as=True,
                        bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                        enable_graceful_restart=True,
                        graceful_restart_timer=120,
                        advertise_end_of_rib=True,
                        route_scales=[
                            # Network Group 0: VIP routes (UCMP)
                            RouteScaleSpec(
                                network_group_index=0,
                                multiplier=1,
                                v6_route_scale=RouteScale(
                                    prefix_name="VIP_V6_DC3",
                                    starting_prefixes="2402:db00:1100::",
                                    prefix_length=64,
                                    multiplier=1,
                                    prefix_count=1000,
                                    ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                    bgp_communities=["65441:259"],
                                    as_path_prepend_numbers=[
                                        [DC3_ASN]
                                    ],  # Prepend DC3 ASN to differentiate
                                ),
                            ),
                            # Network Group 1: Non-VIP routes (ECMP)
                            RouteScaleSpec(
                                network_group_index=1,
                                multiplier=1,
                                v6_route_scale=RouteScale(
                                    prefix_name="NON_VIP_V6_DC3",
                                    starting_prefixes=NON_VIP_V6_WITHOUT_MASK + "::",
                                    prefix_length=64,
                                    multiplier=1,
                                    prefix_count=1000,
                                    ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                    bgp_communities=[
                                        "65529:34814",
                                        "65441:131",
                                    ],
                                    as_path_prepend_numbers=[
                                        [DC3_ASN]
                                    ],  # Same AS_PATH as VIP routes
                                ),
                            ),
                        ],
                    ),
                ),
            ],
        ),
    ],
    # Traffic configuration - fa-du sends traffic to all 3 DC spines
    basic_traffic_item_configs=[
        BasicTrafficItemConfig(
            src_endpoints=[
                TrafficEndpoint(
                    name="fa001-du004.qzd1:eth6/16/1",
                    network_group_index=0,
                    device_group_index=0,
                ),
            ],
            dest_endpoints=[
                TrafficEndpoint(
                    name="ssw004.s002.f01.qzd1:eth8/16/1",
                    network_group_index=0,
                    device_group_index=0,
                ),
                TrafficEndpoint(
                    name="ssw004.s003.f01.qzd1:eth8/16/1",
                    network_group_index=0,
                    device_group_index=0,
                ),
                TrafficEndpoint(
                    name="ssw004.s004.f01.qzd1:eth8/16/1",
                    network_group_index=0,
                    device_group_index=0,
                ),
            ],
            name="UCMP_TEST_TRAFFIC",
            line_rate_type=ixia_types.RateType.PERCENT_LINE_RATE,
            line_rate=10,
            traffic_type=ixia_types.TrafficType.IPV6,
            src_dest_mesh=ixia_types.SrcDestMeshType.MANY_TO_MANY,
            merge_destinations=True,
            bidirectional=False,
        ),
        # TC6: Non-VIP traffic stream (ECMP)
        BasicTrafficItemConfig(
            src_endpoints=[
                TrafficEndpoint(
                    name="fa001-du004.qzd1:eth6/16/1",
                    network_group_index=0,
                    device_group_index=0,
                ),
            ],
            dest_endpoints=[
                TrafficEndpoint(
                    name="ssw004.s002.f01.qzd1:eth8/16/1",
                    network_group_index=1,  # Network group 1 (non-VIP routes)
                    device_group_index=0,
                ),
                TrafficEndpoint(
                    name="ssw004.s003.f01.qzd1:eth8/16/1",
                    network_group_index=1,  # Network group 1 (non-VIP routes)
                    device_group_index=0,
                ),
                TrafficEndpoint(
                    name="ssw004.s004.f01.qzd1:eth8/16/1",
                    network_group_index=1,  # Network group 1 (non-VIP routes)
                    device_group_index=0,
                ),
            ],
            name="NON_VIP_TEST_TRAFFIC",
            line_rate_type=ixia_types.RateType.PERCENT_LINE_RATE,
            line_rate=10,  # Lower rate for non-VIP traffic
            traffic_type=ixia_types.TrafficType.IPV6,
            src_dest_mesh=ixia_types.SrcDestMeshType.MANY_TO_MANY,
            merge_destinations=True,
            bidirectional=False,
        ),
    ],
    # Playbooks for Test Case 1 (Progressive DC Bring-up), Test Case 3 (ECMP to UCMP Transition),
    # Test Case 4 (DC Withdrawal), and Test Case 6 (Policy Isolation)
    playbooks=_add_checks_to_playbooks(
        create_test_case_1_playbooks(
            vip_community=VIP_COMMUNITY,
            vip_v6=VIP_V6,  # Use full prefix notation (2402:db00:1100::/64)
            dc1_asn=DC1_ASN,
            dc2_asn=DC2_ASN,
            dc3_asn=DC3_ASN,
            dc1_weight=DC1_WEIGHT,
            dc2_weight=DC2_WEIGHT,
            dc3_weight=DC3_WEIGHT,
        )
        + create_test_case_3_playbooks(
            vip_community=VIP_COMMUNITY,
            vip_v6=VIP_V6,
            dc1_asn=DC1_ASN,
            dc2_asn=DC2_ASN,
            dc3_asn=DC3_ASN,
            dc1_weight=DC1_WEIGHT,
            dc2_weight=DC2_WEIGHT,
            dc3_weight=DC3_WEIGHT,
        )
        + create_test_case_4_playbooks(
            vip_community=VIP_COMMUNITY,
            vip_v6=VIP_V6,
            dc1_asn=DC1_ASN,
            dc2_asn=DC2_ASN,
            dc3_asn=DC3_ASN,
            dc1_weight=DC1_WEIGHT,
            dc2_weight=DC2_WEIGHT,
            dc3_weight=DC3_WEIGHT,
        )
        + create_test_case_6_playbooks(
            vip_community=VIP_COMMUNITY,
            non_vip_community=NON_VIP_COMMUNITY,
            vip_v6=VIP_V6,
            non_vip_v6=NON_VIP_V6,
            dc1_asn=DC1_ASN,
            dc2_asn=DC2_ASN,
            dc3_asn=DC3_ASN,
            dc1_weight=DC1_WEIGHT,
            dc2_weight=DC2_WEIGHT,
            dc3_weight=DC3_WEIGHT,
        )
        + create_test_case_7_playbooks(
            vip_community=VIP_COMMUNITY,
            vip_v6=VIP_V6,
            dc1_asn=DC1_ASN,
            dc2_asn=DC2_ASN,
            dc3_asn=DC3_ASN,
            dc1_weight=DC1_WEIGHT,
            dc2_weight=DC2_WEIGHT,
            dc3_weight=DC3_WEIGHT,
            dc1_neighbor_hostname="ssw004.s002.f01.qzd1",  # DC1 spine for link failure simulation
            num_interfaces_to_flap=2,  # Shut down 2 of 4 links (50% link failure)
        )
        + create_test_case_8_playbooks(
            vip_community=VIP_COMMUNITY,
            vip_v6=VIP_V6,
            dc1_asn=DC1_ASN,
            dc2_asn=DC2_ASN,
            dc3_asn=DC3_ASN,
            dc1_weight=DC1_WEIGHT,
            dc2_weight=DC2_WEIGHT,
            dc3_weight=DC3_WEIGHT,
            dc1_neighbor_hostname="ssw004.s002.f01.qzd1",  # DC1 spine for link failure simulation
        )
        + create_test_case_9_playbooks(
            vip_community=VIP_COMMUNITY,
            vip_v6=VIP_V6,
            dc1_asn=DC1_ASN,
            dc2_asn=DC2_ASN,
            dc3_asn=DC3_ASN,
            dc1_weight=DC1_WEIGHT,
            dc2_weight=DC2_WEIGHT,
            dc3_weight=DC3_WEIGHT,
        )
        + create_test_case_10_playbooks(
            vip_community=VIP_COMMUNITY,
            vip_v6=VIP_V6,
            dc1_asn=DC1_ASN,
            dc2_asn=DC2_ASN,
            dc3_asn=DC3_ASN,
            dc1_weight=DC1_WEIGHT,
            dc2_weight=DC2_WEIGHT,
            dc3_weight=DC3_WEIGHT,
        )
        + create_test_case_14_playbooks(
            vip_community=VIP_COMMUNITY,
            vip_v6=VIP_V6,
            dc1_asn=DC1_ASN,
            dc2_asn=DC2_ASN,
            dc3_asn=DC3_ASN,
            dc1_weight=DC1_WEIGHT,
            dc2_weight=DC2_WEIGHT,
            dc3_weight=DC3_WEIGHT,
            dc1_device_name="ssw004.s002.f01.qzd1",  # DC1 spine for drain testing
        )
        + create_test_case_12_playbooks(
            vip_community=VIP_COMMUNITY,
            vip_v6=VIP_V6,
            dc1_asn=DC1_ASN,
            dc2_asn=DC2_ASN,
            dc3_asn=DC3_ASN,
            dc1_weight=DC1_WEIGHT,
            dc2_weight=DC2_WEIGHT,
            dc3_weight=DC3_WEIGHT,
            iter=5,
        )
        + create_test_case_13_playbooks(
            vip_community=VIP_COMMUNITY,
            vip_v6=VIP_V6,
            dc1_asn=DC1_ASN,
            dc2_asn=DC2_ASN,
            dc3_asn=DC3_ASN,
            dc1_weight=DC1_WEIGHT,
            dc2_weight=DC2_WEIGHT,
            dc3_weight=DC3_WEIGHT,
            iter=5,
        )
        + create_extra_weights_added_to_policy(
            vip_community=VIP_COMMUNITY,
            vip_v6=VIP_V6,
            dc1_asn=DC1_ASN,
            dc2_asn=DC2_ASN,
            dc3_asn=DC3_ASN,
            dc1_weight=DC1_WEIGHT,
            dc2_weight=DC2_WEIGHT,
            dc3_weight=DC3_WEIGHT,
        )
        + create_test_case_fallback_to_ecmp_playbooks(
            vip_community=VIP_COMMUNITY,
            vip_v6=VIP_V6,
            dc1_asn=DC1_ASN,
            dc2_asn=DC2_ASN,
            dc3_asn=DC3_ASN,
            dc1_weight=DC1_WEIGHT,
            dc2_weight=DC2_WEIGHT,
            dc3_weight=DC3_WEIGHT,
        )
    ),
)
