# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""CTE UCMP feature testconfig factories.

Wave 2C — moved verbatim from
``testconfigs/routing/test_config_cte_ucmp.py`` and
``testconfigs/routing/test_config_cte_ucmp_stand_alone.py``. Both bodies
retain their private module-level constants; only DUT identity fields are
sourced from ``physical_inventory``. The ``name`` field is a required kwarg so the
lifecycle binding preserves the legacy ``TestConfig.name`` verbatim and the
golden manifest hash stays byte-identical.

See ``docs/routing/TESTCONFIGS.md`` for the factory contract.
"""

import json

from ixia.ixia import types as ixia_types
from taac.abstractions.physical_inventory import PhysicalInventory
from taac.health_checks.healthcheck_definitions import (
    create_core_dumps_snapshot_check,
    create_lldp_check,
    create_port_state_check,
)
from taac.playbooks.playbook_definitions import (
    create_baseline_ecmp_playbook,
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
    create_ucmp_iteration_playbook,
)
from taac.task_definitions import (
    create_configure_parallel_bgp_peers_task,
    create_coop_apply_patchers_task,
    create_coop_register_patcher_task,
    create_coop_unregister_patchers_task,
    create_wait_for_agent_convergence_task,
)
from taac.test_as_a_config import types as taac_types
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


__all__ = [
    "create_cte_ucmp_qzd_test_config",
    "create_cte_ucmp_stand_alone_test_config",
]


# =============================================================================
# CTE UCMP QZD — Inter-DC VIP Traffic Balancing (multi-node logical_topology)
# =============================================================================
#
# fa001-du004.qzd1 (DUT) advertises VIP_V6_SOURCE and receives VIP
# advertisements from 3 IXIA-simulated DCs on 3 spine switches. See the docstring
# on ``create_cte_ucmp_qzd_test_config`` for the full spec.

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
_QZD_VIP_V4 = "203.0.113.0/24"
_QZD_VIP_V6 = "2402:db00:1100::/64"  # VIP prefix (matches VIP_V6_SOURCE)
_QZD_VIP_V6_WITHOUT_MASK = "2402:db00:1100"
_QZD_VIP_COMMUNITY = "65441:260"

_QZD_NON_VIP_COMMUNITY = "65441:132"
_QZD_NON_VIP_V6 = "2402:db00:1300::/64"
_QZD_NON_VIP_V6_WITHOUT_MASK = "2402:db00:1300"

# DC Configuration
_QZD_DC1_ASN = 50001
_QZD_DC2_ASN = 50002
_QZD_DC3_ASN = 50003

# UCMP Weights
_QZD_DC1_WEIGHT = 10
_QZD_DC2_WEIGHT = 5
_QZD_DC3_WEIGHT = 2

# Spine endpoints (multi-node, no shared chassis IP — hardcoded here per Wave 2C).
_QZD_SPINE_DC1 = "ssw004.s002.f01.qzd1"
_QZD_SPINE_DC2 = "ssw004.s003.f01.qzd1"
_QZD_SPINE_DC3 = "ssw004.s004.f01.qzd1"
_QZD_DUT_IXIA_PORT = "eth6/16/1"
_QZD_SPINE_IXIA_PORT = "eth8/16/1"


def create_cte_ucmp_qzd_test_config(
    physical_inventory: PhysicalInventory, *, name: str
) -> TestConfig:
    """CTE UCMP QZD Lab TestConfig for Inter-DC VIP Traffic Balancing.

    Multi-node logical_topology:
      - DUT (from ``physical_inventory.device_name``, expected ``fa001-du004.qzd1``) —
        advertises VIP_V6_SOURCE with UCMP policy under test.
      - 3 spine switches (hardcoded ``ssw004.s{002,003,004}.f01.qzd1``) —
        simulate 3 DCs advertising the same VIP prefix with AS_PATH prepending.

    See legacy ``test_config_cte_ucmp.py`` docstring for the full spec
    (Test Cases 1/3/4/6/7/8/9/10/12/13/14 + fallback-to-ECMP + extra-weights).
    """
    assert physical_inventory.device_name == "fa001-du004.qzd1", (
        f"create_cte_ucmp_qzd_test_config Wave 2C is hardcoded to "
        f"fa001-du004.qzd1; got physical_inventory.device_name={physical_inventory.device_name!r}."
    )
    dut_name = physical_inventory.device_name

    return TestConfig(
        name=name,
        skip_ixia_protocol_verification=True,
        basset_pool="dne.test",
        log_collection_timeout=180,
        basset_reservation_time_hr=4,
        ignore_down_circuits=True,
        ignore_circuit_fbnet_status=False,
        endpoints=[
            # fa-du device is the DUT where we configure UCMP policy
            Endpoint(
                name=dut_name,
                dut=True,
                ixia_ports=[_QZD_DUT_IXIA_PORT],
            ),
            # Spine switches are part of network topology (non-DUTs)
            Endpoint(
                name=_QZD_SPINE_DC1,
                dut=False,
                ixia_ports=[_QZD_SPINE_IXIA_PORT],
            ),
            Endpoint(
                name=_QZD_SPINE_DC2,
                dut=False,
                ixia_ports=[_QZD_SPINE_IXIA_PORT],
            ),
            Endpoint(
                name=_QZD_SPINE_DC3,
                dut=False,
                ixia_ports=[_QZD_SPINE_IXIA_PORT],
            ),
        ],
        # Deprecated - define at playbook level
        # prechecks - moved to playbook level
        # postchecks - moved to playbook level
        # snapshot_checks - moved to playbook level
        basic_port_configs=[
            BasicPortConfig(
                endpoint=f"{dut_name}:{_QZD_DUT_IXIA_PORT}",
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
                endpoint=f"{_QZD_SPINE_DC1}:{_QZD_SPINE_IXIA_PORT}",
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
                                            [_QZD_DC1_ASN]
                                        ],  # Prepend DC1 ASN to differentiate
                                    ),
                                ),
                                # Network Group 1: Non-VIP routes (ECMP)
                                RouteScaleSpec(
                                    network_group_index=1,
                                    multiplier=1,
                                    v6_route_scale=RouteScale(
                                        prefix_name="NON_VIP_V6_DC1",
                                        starting_prefixes=_QZD_NON_VIP_V6_WITHOUT_MASK
                                        + "::",
                                        prefix_length=64,
                                        multiplier=1,
                                        prefix_count=1000,
                                        ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                        bgp_communities=[
                                            "65529:34814",
                                            "65441:131",
                                        ],
                                        as_path_prepend_numbers=[
                                            [_QZD_DC1_ASN]
                                        ],  # Same AS_PATH as VIP routes
                                    ),
                                ),
                            ],
                        ),
                    ),
                ],
            ),
            BasicPortConfig(
                endpoint=f"{_QZD_SPINE_DC2}:{_QZD_SPINE_IXIA_PORT}",
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
                                            [_QZD_DC2_ASN]
                                        ],  # Prepend DC2 ASN to differentiate
                                    ),
                                ),
                                # Network Group 1: Non-VIP routes (ECMP)
                                RouteScaleSpec(
                                    network_group_index=1,
                                    multiplier=1,
                                    v6_route_scale=RouteScale(
                                        prefix_name="NON_VIP_V6_DC2",
                                        starting_prefixes=_QZD_NON_VIP_V6_WITHOUT_MASK
                                        + "::",
                                        prefix_length=64,
                                        multiplier=1,
                                        prefix_count=1000,
                                        ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                        bgp_communities=[
                                            "65529:34814",
                                            "65441:131",
                                        ],
                                        as_path_prepend_numbers=[
                                            [_QZD_DC2_ASN]
                                        ],  # Same AS_PATH as VIP routes
                                    ),
                                ),
                            ],
                        ),
                    ),
                ],
            ),
            BasicPortConfig(
                endpoint=f"{_QZD_SPINE_DC3}:{_QZD_SPINE_IXIA_PORT}",
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
                                            [_QZD_DC3_ASN]
                                        ],  # Prepend DC3 ASN to differentiate
                                    ),
                                ),
                                # Network Group 1: Non-VIP routes (ECMP)
                                RouteScaleSpec(
                                    network_group_index=1,
                                    multiplier=1,
                                    v6_route_scale=RouteScale(
                                        prefix_name="NON_VIP_V6_DC3",
                                        starting_prefixes=_QZD_NON_VIP_V6_WITHOUT_MASK
                                        + "::",
                                        prefix_length=64,
                                        multiplier=1,
                                        prefix_count=1000,
                                        ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                        bgp_communities=[
                                            "65529:34814",
                                            "65441:131",
                                        ],
                                        as_path_prepend_numbers=[
                                            [_QZD_DC3_ASN]
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
                        name=f"{dut_name}:{_QZD_DUT_IXIA_PORT}",
                        network_group_index=0,
                        device_group_index=0,
                    ),
                ],
                dest_endpoints=[
                    TrafficEndpoint(
                        name=f"{_QZD_SPINE_DC1}:{_QZD_SPINE_IXIA_PORT}",
                        network_group_index=0,
                        device_group_index=0,
                    ),
                    TrafficEndpoint(
                        name=f"{_QZD_SPINE_DC2}:{_QZD_SPINE_IXIA_PORT}",
                        network_group_index=0,
                        device_group_index=0,
                    ),
                    TrafficEndpoint(
                        name=f"{_QZD_SPINE_DC3}:{_QZD_SPINE_IXIA_PORT}",
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
                        name=f"{dut_name}:{_QZD_DUT_IXIA_PORT}",
                        network_group_index=0,
                        device_group_index=0,
                    ),
                ],
                dest_endpoints=[
                    TrafficEndpoint(
                        name=f"{_QZD_SPINE_DC1}:{_QZD_SPINE_IXIA_PORT}",
                        network_group_index=1,  # Network group 1 (non-VIP routes)
                        device_group_index=0,
                    ),
                    TrafficEndpoint(
                        name=f"{_QZD_SPINE_DC2}:{_QZD_SPINE_IXIA_PORT}",
                        network_group_index=1,  # Network group 1 (non-VIP routes)
                        device_group_index=0,
                    ),
                    TrafficEndpoint(
                        name=f"{_QZD_SPINE_DC3}:{_QZD_SPINE_IXIA_PORT}",
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
                vip_community=_QZD_VIP_COMMUNITY,
                vip_v6=_QZD_VIP_V6,  # Use full prefix notation (2402:db00:1100::/64)
                dc1_asn=_QZD_DC1_ASN,
                dc2_asn=_QZD_DC2_ASN,
                dc3_asn=_QZD_DC3_ASN,
                dc1_weight=_QZD_DC1_WEIGHT,
                dc2_weight=_QZD_DC2_WEIGHT,
                dc3_weight=_QZD_DC3_WEIGHT,
            )
            + create_test_case_3_playbooks(
                vip_community=_QZD_VIP_COMMUNITY,
                vip_v6=_QZD_VIP_V6,
                dc1_asn=_QZD_DC1_ASN,
                dc2_asn=_QZD_DC2_ASN,
                dc3_asn=_QZD_DC3_ASN,
                dc1_weight=_QZD_DC1_WEIGHT,
                dc2_weight=_QZD_DC2_WEIGHT,
                dc3_weight=_QZD_DC3_WEIGHT,
            )
            + create_test_case_4_playbooks(
                vip_community=_QZD_VIP_COMMUNITY,
                vip_v6=_QZD_VIP_V6,
                dc1_asn=_QZD_DC1_ASN,
                dc2_asn=_QZD_DC2_ASN,
                dc3_asn=_QZD_DC3_ASN,
                dc1_weight=_QZD_DC1_WEIGHT,
                dc2_weight=_QZD_DC2_WEIGHT,
                dc3_weight=_QZD_DC3_WEIGHT,
            )
            + create_test_case_6_playbooks(
                vip_community=_QZD_VIP_COMMUNITY,
                non_vip_community=_QZD_NON_VIP_COMMUNITY,
                vip_v6=_QZD_VIP_V6,
                non_vip_v6=_QZD_NON_VIP_V6,
                dc1_asn=_QZD_DC1_ASN,
                dc2_asn=_QZD_DC2_ASN,
                dc3_asn=_QZD_DC3_ASN,
                dc1_weight=_QZD_DC1_WEIGHT,
                dc2_weight=_QZD_DC2_WEIGHT,
                dc3_weight=_QZD_DC3_WEIGHT,
            )
            + create_test_case_7_playbooks(
                vip_community=_QZD_VIP_COMMUNITY,
                vip_v6=_QZD_VIP_V6,
                dc1_asn=_QZD_DC1_ASN,
                dc2_asn=_QZD_DC2_ASN,
                dc3_asn=_QZD_DC3_ASN,
                dc1_weight=_QZD_DC1_WEIGHT,
                dc2_weight=_QZD_DC2_WEIGHT,
                dc3_weight=_QZD_DC3_WEIGHT,
                dc1_neighbor_hostname=_QZD_SPINE_DC1,  # DC1 spine for link failure simulation
                num_interfaces_to_flap=2,  # Shut down 2 of 4 links (50% link failure)
            )
            + create_test_case_8_playbooks(
                vip_community=_QZD_VIP_COMMUNITY,
                vip_v6=_QZD_VIP_V6,
                dc1_asn=_QZD_DC1_ASN,
                dc2_asn=_QZD_DC2_ASN,
                dc3_asn=_QZD_DC3_ASN,
                dc1_weight=_QZD_DC1_WEIGHT,
                dc2_weight=_QZD_DC2_WEIGHT,
                dc3_weight=_QZD_DC3_WEIGHT,
                dc1_neighbor_hostname=_QZD_SPINE_DC1,  # DC1 spine for link failure simulation
            )
            + create_test_case_9_playbooks(
                vip_community=_QZD_VIP_COMMUNITY,
                vip_v6=_QZD_VIP_V6,
                dc1_asn=_QZD_DC1_ASN,
                dc2_asn=_QZD_DC2_ASN,
                dc3_asn=_QZD_DC3_ASN,
                dc1_weight=_QZD_DC1_WEIGHT,
                dc2_weight=_QZD_DC2_WEIGHT,
                dc3_weight=_QZD_DC3_WEIGHT,
            )
            + create_test_case_10_playbooks(
                vip_community=_QZD_VIP_COMMUNITY,
                vip_v6=_QZD_VIP_V6,
                dc1_asn=_QZD_DC1_ASN,
                dc2_asn=_QZD_DC2_ASN,
                dc3_asn=_QZD_DC3_ASN,
                dc1_weight=_QZD_DC1_WEIGHT,
                dc2_weight=_QZD_DC2_WEIGHT,
                dc3_weight=_QZD_DC3_WEIGHT,
            )
            + create_test_case_14_playbooks(
                vip_community=_QZD_VIP_COMMUNITY,
                vip_v6=_QZD_VIP_V6,
                dc1_asn=_QZD_DC1_ASN,
                dc2_asn=_QZD_DC2_ASN,
                dc3_asn=_QZD_DC3_ASN,
                dc1_weight=_QZD_DC1_WEIGHT,
                dc2_weight=_QZD_DC2_WEIGHT,
                dc3_weight=_QZD_DC3_WEIGHT,
                dc1_device_name=_QZD_SPINE_DC1,  # DC1 spine for drain testing
            )
            + create_test_case_12_playbooks(
                vip_community=_QZD_VIP_COMMUNITY,
                vip_v6=_QZD_VIP_V6,
                dc1_asn=_QZD_DC1_ASN,
                dc2_asn=_QZD_DC2_ASN,
                dc3_asn=_QZD_DC3_ASN,
                dc1_weight=_QZD_DC1_WEIGHT,
                dc2_weight=_QZD_DC2_WEIGHT,
                dc3_weight=_QZD_DC3_WEIGHT,
                iter=5,
            )
            + create_test_case_13_playbooks(
                vip_community=_QZD_VIP_COMMUNITY,
                vip_v6=_QZD_VIP_V6,
                dc1_asn=_QZD_DC1_ASN,
                dc2_asn=_QZD_DC2_ASN,
                dc3_asn=_QZD_DC3_ASN,
                dc1_weight=_QZD_DC1_WEIGHT,
                dc2_weight=_QZD_DC2_WEIGHT,
                dc3_weight=_QZD_DC3_WEIGHT,
                iter=5,
            )
            + create_extra_weights_added_to_policy(
                vip_community=_QZD_VIP_COMMUNITY,
                vip_v6=_QZD_VIP_V6,
                dc1_asn=_QZD_DC1_ASN,
                dc2_asn=_QZD_DC2_ASN,
                dc3_asn=_QZD_DC3_ASN,
                dc1_weight=_QZD_DC1_WEIGHT,
                dc2_weight=_QZD_DC2_WEIGHT,
                dc3_weight=_QZD_DC3_WEIGHT,
            )
            + create_test_case_fallback_to_ecmp_playbooks(
                vip_community=_QZD_VIP_COMMUNITY,
                vip_v6=_QZD_VIP_V6,
                dc1_asn=_QZD_DC1_ASN,
                dc2_asn=_QZD_DC2_ASN,
                dc3_asn=_QZD_DC3_ASN,
                dc1_weight=_QZD_DC1_WEIGHT,
                dc2_weight=_QZD_DC2_WEIGHT,
                dc3_weight=_QZD_DC3_WEIGHT,
            )
        ),
    )


# =============================================================================
# CTE UCMP STAND ALONE — thrift-API-driven UCMP weight changes (single-node)
# =============================================================================
#
# DUT hosts 1 uplink eBGP peer + 12 downlink confed peers across 3 DCs.
# See legacy ``test_config_cte_ucmp_stand_alone.py`` docstring for the spec.

# BGP peer groups and route maps
_STAND_PEERGROUP_UPLINK_V6 = "PEERGROUP_FSW_SSW_V6"
_STAND_PEERGROUP_DOWNLINK_V6 = "PEERGROUP_FSW_RSW_V6"

# IP addressing
_STAND_IXIA_UPLINK_IC_PARENT_NETWORK_V6 = "2401:db00:e50d:11:9"
_STAND_IXIA_DOWNLINK_IC_PARENT_NETWORK_V6 = "2401:db00:e50d:11:8"

# AS numbers
_STAND_REMOTE_UPLINK_AS = 65000
_STAND_REMOTE_DOWNLINK_AS = 2000
_STAND_IS_UPLINK_PEER_CONFED = "False"
_STAND_IS_DOWNLINK_PEER_CONFED = "True"

# Communities
_STAND_IXIA_UPLINK_COMMUNITIES = [
    "65441:196",
    "65441:9001",
    "65441:9002",
    "65441:9003",
    "65441:9004",
    "65441:9005",
]
_STAND_IXIA_DOWNLINK_COMMUNITIES = [
    "65441:194",
    "65441:260",  # VIP community — required for UCMP policy matching
    "65441:9001",
    "65441:9002",
    "65441:9003",
    "65441:9004",
    "65441:9005",
]

# UCMP Test Constants
_STAND_VIP_V6_PREFIX = "2402:db00:1100"

_STAND_DC1_ASN = 50001
_STAND_DC2_ASN = 50002
_STAND_DC3_ASN = 50003
_STAND_DC_ASNS = [_STAND_DC1_ASN, _STAND_DC2_ASN, _STAND_DC3_ASN]

_STAND_PEERS_PER_DC = 4
_STAND_TOTAL_DOWNLINK_PEERS = _STAND_PEERS_PER_DC * len(_STAND_DC_ASNS)  # 12

_STAND_PER_PEER_MAX_ROUTE_LIMIT = "10000"
_STAND_PREFIX_COUNT_V6 = 1000


def _stand_alone_downlink_device_groups() -> list[taac_types.DeviceGroupConfig]:
    """Create 3 downlink DGs, each with 4 peers, advertising same VIP prefix."""
    dgs = []
    for i, dc_asn in enumerate(_STAND_DC_ASNS):
        # Each DG gets a separate IP range on the downlink subnet
        # DG0: starts at ::11, DG1: starts at ::19, DG2: starts at ::21
        ixia_start = 0x11 + i * (_STAND_PEERS_PER_DC * 2)
        gw_start = 0x10 + i * (_STAND_PEERS_PER_DC * 2)

        dgs.append(
            taac_types.DeviceGroupConfig(
                device_group_index=i,
                device_group_name=f"IXIA_DC{i + 1}_ADVERTISER",
                multiplier=_STAND_PEERS_PER_DC,
                v6_addresses_config=taac_types.IpAddressesConfig(
                    starting_ip=f"{_STAND_IXIA_DOWNLINK_IC_PARENT_NETWORK_V6}::{ixia_start:x}",
                    increment_ip="0:0:0:0::2",
                    gateway_starting_ip=f"{_STAND_IXIA_DOWNLINK_IC_PARENT_NETWORK_V6}::{gw_start:x}",
                    gateway_increment_ip="0:0:0:0::2",
                    mask=127,
                ),
                v6_bgp_config=taac_types.BgpConfig(
                    local_as_4_bytes=_STAND_REMOTE_DOWNLINK_AS
                    + i * _STAND_PEERS_PER_DC,
                    local_as_increment=1,
                    enable_4_byte_local_as=True,
                    is_confed=True,
                    bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                    route_scales=[
                        taac_types.RouteScaleSpec(
                            network_group_index=0,
                            multiplier=1,
                            v6_route_scale=taac_types.RouteScale(
                                prefix_name=f"VIP_V6_DC{i + 1}",
                                starting_prefixes=f"{_STAND_VIP_V6_PREFIX}::",
                                prefix_length=64,
                                multiplier=1,
                                prefix_count=_STAND_PREFIX_COUNT_V6,
                                prefix_step="0:0:0:0::",
                                ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                bgp_communities=_STAND_IXIA_DOWNLINK_COMMUNITIES,
                                as_path_prepend_numbers=[[dc_asn]],
                            ),
                        ),
                    ],
                ),
            )
        )
    return dgs


def create_cte_ucmp_stand_alone_test_config(
    physical_inventory: PhysicalInventory, *, name: str
) -> TestConfig:
    """CTE UCMP Stand-Alone TestConfig for thrift-API-driven UCMP weight changes.

    Single-DUT topology on ``physical_inventory.device_name`` (expected
    ``fsw003.p003.f01.qzd1``):
      - Uplink port (from ``physical_inventory.ixia_ports[0]``): 1 eBGP peer traffic source.
      - Downlink port (from ``physical_inventory.ixia_ports[1]``): 12 confed peers across
        3 DCs, all advertising the same VIP prefix pool.
    """
    assert physical_inventory.device_name == "fsw003.p003.f01.qzd1", (
        f"create_cte_ucmp_stand_alone_test_config Wave 2C is hardcoded to "
        f"fsw003.p003.f01.qzd1; got physical_inventory.device_name={physical_inventory.device_name!r}."
    )
    assert physical_inventory.mac_address is not None, (
        "PhysicalInventory must have mac_address set (used as DUT MAC in Endpoint)"
    )
    assert len(physical_inventory.ixia_ports) >= 2, (
        "PhysicalInventory must have >= 2 IXIA ports (uplink + downlink)"
    )

    device_name = physical_inventory.device_name
    ixia_chassis_ip = physical_inventory.ixia_chassis_ip
    uplink_iface, uplink_chassis_port = physical_inventory.ixia_ports[0]
    downlink_iface, downlink_chassis_port = physical_inventory.ixia_ports[1]

    direct_ixia_connections = [
        taac_types.DirectIxiaConnection(
            interface=uplink_iface,
            ixia_chassis_ip=ixia_chassis_ip,
            ixia_port=uplink_chassis_port,
        ),
        taac_types.DirectIxiaConnection(
            interface=downlink_iface,
            ixia_chassis_ip=ixia_chassis_ip,
            ixia_port=downlink_chassis_port,
        ),
    ]

    return TestConfig(
        name=name,
        skip_ixia_protocol_verification=True,
        basset_pool="dne.test",
        basset_reservation_time_hr=4,
        log_collection_timeout=180,
        endpoints=[
            taac_types.Endpoint(
                name=device_name,
                ixia_ports=[uplink_iface, downlink_iface],
                dut=True,
                mac_address=physical_inventory.mac_address,
                direct_ixia_connections=direct_ixia_connections,
            ),
        ],
        # Deprecated - define at playbook level
        # prechecks - moved to playbook level
        # postchecks - moved to playbook level
        # snapshot_checks - moved to playbook level
        # ================================================================
        # Setup Tasks (COOP patchers from best_path_eval)
        # ================================================================
        setup_tasks=[
            # ---- Step 1: Clean slate ----
            create_coop_unregister_patchers_task(device_name),
            create_coop_apply_patchers_task(hostnames=[device_name]),
            create_wait_for_agent_convergence_task([device_name]),
            # ---- Step 2: Remove existing BGP peers ----
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name="a_remove_bgp_peers",
                task_name="coop_register_patcher",
                patcher_args={"delete_all": "True"},
                py_func_name="remove_bgp_peers",
            ),
            # ---- Step 3: Enable IXIA ports ----
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="agent",
                patcher_name="enable_port_all_ixia_ports",
                task_name="coop_register_patcher",
                patcher_args={
                    uplink_iface: "enable",
                    downlink_iface: "enable",
                },
                py_func_name="change_port_admin_state",
            ),
            # ---- Step 4: Update peer groups ----
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name="update_peer_group_patcher_V6_Downlink",
                task_name="coop_register_patcher",
                patcher_args={
                    "name": _STAND_PEERGROUP_DOWNLINK_V6,
                    "attributes_to_update_json": json.dumps(
                        {
                            "disable_ipv4_afi": "True",
                            "v4_over_v6_nexthop": "False",
                            "is_passive": "False",
                            "is_confed_peer": _STAND_IS_DOWNLINK_PEER_CONFED,
                            "max_routes": _STAND_PER_PEER_MAX_ROUTE_LIMIT,
                        }
                    ),
                },
                py_func_name="configure_bgp_peer_group",
            ),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name=f"update_peer_group_patcher_{_STAND_PEERGROUP_UPLINK_V6}_Uplink",
                task_name="coop_register_patcher",
                patcher_args={
                    "name": _STAND_PEERGROUP_UPLINK_V6,
                    "attributes_to_update_json": json.dumps(
                        {
                            "disable_ipv4_afi": "True",
                            "v4_over_v6_nexthop": "False",
                            "is_passive": "False",
                            "is_confed_peer": _STAND_IS_UPLINK_PEER_CONFED,
                            "max_routes": _STAND_PER_PEER_MAX_ROUTE_LIMIT,
                        }
                    ),
                },
                py_func_name="configure_bgp_peer_group",
            ),
            # ---- Step 5: Configure DUT VLANs and BGP peers ----
            # Uplink: 1 eBGP peer
            create_configure_parallel_bgp_peers_task(
                hostname=device_name,
                configure_vlans_patcher_name="configure_vlans_patcher_uplink",
                add_bgp_peers_patcher_name="add_bgp_peers_patcher_uplink",
                config_json=json.dumps(
                    {
                        uplink_iface: [
                            {
                                "starting_ip": f"{_STAND_IXIA_UPLINK_IC_PARENT_NETWORK_V6}::10",
                                "increment_ip": "0:0:0:0::2",
                                "prefix_length": 127,
                                "description": "Uplink IPv6 Peer (EBGP)",
                                "peer_group_name": _STAND_PEERGROUP_UPLINK_V6,
                                "num_sessions": 1,
                                "remote_as_4_byte": _STAND_REMOTE_UPLINK_AS,
                                "remote_as_4_byte_step": 1,
                                "gateway_starting_ip": f"{_STAND_IXIA_UPLINK_IC_PARENT_NETWORK_V6}::11",
                                "gateway_increment_ip": "0:0:0:0::2",
                            },
                        ],
                    }
                ),
            ),
            # Downlink: 12 confed peers (3 DCs × 4 peers)
            create_configure_parallel_bgp_peers_task(
                hostname=device_name,
                configure_vlans_patcher_name="configure_vlans_patcher_downlink",
                add_bgp_peers_patcher_name="add_bgp_peers_patcher_downlink",
                config_json=json.dumps(
                    {
                        downlink_iface: [
                            {
                                "starting_ip": f"{_STAND_IXIA_DOWNLINK_IC_PARENT_NETWORK_V6}::10",
                                "increment_ip": "0:0:0:0::2",
                                "prefix_length": 127,
                                "description": "Downlink IPv6 Peers (Confed, 3 DCs × 4 links)",
                                "peer_group_name": _STAND_PEERGROUP_DOWNLINK_V6,
                                "num_sessions": _STAND_TOTAL_DOWNLINK_PEERS,
                                "remote_as_4_byte": _STAND_REMOTE_DOWNLINK_AS,
                                "remote_as_4_byte_step": 1,
                                "gateway_starting_ip": f"{_STAND_IXIA_DOWNLINK_IC_PARENT_NETWORK_V6}::11",
                                "gateway_increment_ip": "0:0:0:0::2",
                            },
                        ],
                    }
                ),
            ),
            # ---- Step 6: Apply all registered patchers ----
            create_coop_apply_patchers_task(hostnames=[device_name]),
            create_wait_for_agent_convergence_task([device_name]),
        ],
        # ================================================================
        # IXIA Port Configs
        # ================================================================
        basic_port_configs=[
            # ---- UPLINK PORT: Traffic source ----
            taac_types.BasicPortConfig(
                endpoint=f"{device_name}:{uplink_iface}",
                device_group_configs=[
                    taac_types.DeviceGroupConfig(
                        device_group_index=0,
                        multiplier=1,
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{_STAND_IXIA_UPLINK_IC_PARENT_NETWORK_V6}::11",
                            increment_ip="0:0:0:0::2",
                            gateway_starting_ip=f"{_STAND_IXIA_UPLINK_IC_PARENT_NETWORK_V6}::10",
                            gateway_increment_ip="0:0:0:0::2",
                            mask=127,
                        ),
                        v6_bgp_config=taac_types.BgpConfig(
                            local_as_4_bytes=_STAND_REMOTE_UPLINK_AS,
                            local_as_increment=1,
                            enable_4_byte_local_as=True,
                            is_confed=False,
                            bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                            route_scales=[
                                taac_types.RouteScaleSpec(
                                    network_group_index=0,
                                    multiplier=1,
                                    v6_route_scale=taac_types.RouteScale(
                                        prefix_name="SOURCE_V6_UPLINK",
                                        starting_prefixes="2402:db00:1200::",
                                        prefix_length=64,
                                        multiplier=1,
                                        prefix_count=_STAND_PREFIX_COUNT_V6,
                                        ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                        bgp_communities=_STAND_IXIA_UPLINK_COMMUNITIES,
                                    ),
                                ),
                            ],
                        ),
                    ),
                ],
            ),
            # ---- DOWNLINK PORT: 3 DCs × 4 peers ----
            taac_types.BasicPortConfig(
                endpoint=f"{device_name}:{downlink_iface}",
                device_group_configs=_stand_alone_downlink_device_groups(),
            ),
        ],
        # ================================================================
        # Traffic Items
        # ================================================================
        basic_traffic_item_configs=[
            taac_types.BasicTrafficItemConfig(
                name="UCMP_STAND_ALONE_TRAFFIC",
                bidirectional=False,
                merge_destinations=True,
                line_rate=10,
                src_dest_mesh=ixia_types.SrcDestMeshType.MANY_TO_MANY,
                src_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{uplink_iface}",
                        device_group_index=0,
                        network_group_index=0,
                    ),
                ],
                dest_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{downlink_iface}",
                        device_group_index=0,
                        network_group_index=0,
                    ),
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{downlink_iface}",
                        device_group_index=1,
                        network_group_index=0,
                    ),
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{downlink_iface}",
                        device_group_index=2,
                        network_group_index=0,
                    ),
                ],
                traffic_type=ixia_types.TrafficType.IPV6,
                tracking_types=[ixia_types.TrafficStatsTrackingType.TRAFFIC_ITEM],
            ),
        ],
        # ================================================================
        # Playbooks
        # ================================================================
        playbooks=[
            create_baseline_ecmp_playbook(),
            create_ucmp_iteration_playbook(),
        ],
    )
