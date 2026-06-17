# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""
BGP Path Scale Test Configuration for Viper EDSW003.N001.L201.SNC1

Adapted from mp3n_bgp_path_scale_test_config.py (RTSW pattern) for EDSW
with 2 IXIA eth ports. Tests BGP path scale limits by forming multiple
iBGP peers on the uplink port and listener-only peers on the downlink.

Topology:
  IXIA (downlink, traffic src) -- eth1/17/1 -- [EDSW003.N001] -- eth1/23/1 -- IXIA (uplink, iBGP peers + route injection)

Path Scale = ECMP Width (uplink peers) x Prefixes/Peer + Egress (downlink peers x prefixes)

IXIA Port Mapping:
  edsw003.n001.l201.snc1:eth1/17/1 -> chassis 2401:db00:116:3167:21a:c5ff:fe01:7173 port 1/5 (downlink)
  edsw003.n001.l201.snc1:eth1/23/1 -> chassis 2401:db00:116:3167:21a:c5ff:fe01:7173 port 1/6 (uplink)

BGP Config:
  EDSW003.N001 ASN: 65062 (iBGP)
  Uplink peer group: PEERGROUP_EDSW_IXIA_PATH_SCALE_V6 (test-created)
  Downlink peer group: PEERGROUP_EDSW_BAG_V6 (existing)

Usage:
  buck2 run neteng/netcastle:netcastle_taac -- --team taac \\
    --test-config EDSW003_BGP_PATH_SCALE_EXP1_52_ECMP_15K \\
    --dev --debug \\
    --skip-basset-reservation --skip-testbed-isolation \\
    --skip-failed-setup-cleanup --skip-ixia-cleanup \\
    --regex 'longevity' \\
    --ixia-api-server 2401:db00:116:3167:21a:c5ff:fe01:7173
"""

import json
from dataclasses import dataclass

from ixia.ixia import types as ixia_types
from taac.health_checks.healthcheck_definitions import (
    create_bgp_convergence_check,
    create_core_dumps_snapshot_check,
    create_cpu_utilization_check,
    create_ecmp_group_and_member_count_check,
    create_memory_utilization_check,
    create_prefix_limit_check,
    create_service_restart_check,
    create_systemctl_active_state_check,
    create_unclean_exit_check,
)
from taac.playbooks.playbook_definitions import (
    build_edsw003_bgp_path_scale_playbook,
)
from taac.stages.stage_definitions import create_steps_stage
from taac.steps.step_definitions import (
    create_ixia_api_step,
    create_ixia_device_group_toggle_step,
    create_longevity_step,
    create_service_convergence_step,
    create_service_interruption_step,
    create_toggle_ixia_prefix_session_flap_churn_step,
)
from taac.task_definitions import (
    create_coop_apply_patchers_task,
    create_coop_register_patcher_task,
    create_coop_unregister_patchers_task,
)
from taac.utils.json_thrift_utils import thrift_to_json
from taac.health_check.health_check import types as hc_types
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import (
    ConcurrentStep,
    Service,
    ServiceInterruptionTrigger,
    Task,
    TestConfig,
)


# =============================================================================
# Constants
# =============================================================================

PEERGROUP_EDSW_IXIA_PATH_SCALE_V6 = "PEERGROUP_EDSW_IXIA_PATH_SCALE_V6"
PEERGROUP_EDSW_BAG_V6 = "PEERGROUP_EDSW_BAG_V6"

# DSF L1 config with PFC queue mapping
DSF_L1_CONFIG = ixia_types.L1Config(
    enable_fcoe=True,
    flow_control_config=ixia_types.FlowControlConfig(
        pfc_prority_groups_config=ixia_types.PfcPriorityGroupsConfig(
            priority0_pfc_queue=ixia_types.PfcQueue.TWO,
            priority1_pfc_queue=ixia_types.PfcQueue.ONE,
            priority2_pfc_queue=ixia_types.PfcQueue.ZERO,
            priority3_pfc_queue=ixia_types.PfcQueue.THREE,
        ),
        enable_pfc_pause_delay=False,
    ),
)

# DSF IMIX frame sizes
DSF_FRAME_SIZES = ixia_types.FrameSize(
    type=ixia_types.FrameSizeType.CUSTOM_IMIX,
    imix_weight={94: 1, 96: 18, 192: 3, 512: 1, 1200: 1, 4600: 76},
)

# EDSW BGP communities for route injection
EDSW_BGP_COMMUNITIES = ["65446:30", "65441:1028", "65529:52780", "65529:52779"]

TRAFFIC_ITEM_GOLDEN = "golden"

# FBOSS RIF type for SYSTEM_PORT interfaces
SYSTEM_PORT_RIF_TYPE = 2


# =============================================================================
# Dataclasses
# =============================================================================


@dataclass(frozen=True)
class PathScaleExperiment:
    """Defines a single BGP path scale experiment."""

    ecmp_width: int
    prefix_count: int

    @property
    def path_scale(self) -> int:
        return self.ecmp_width * self.prefix_count


@dataclass(frozen=True)
class UplinkConfig:
    """Configuration for an IXIA uplink interface that advertises routes."""

    interface: str
    ic_parent_network_v6: str
    mac_address: str
    peer_count: int | None = None  # None means use experiment.ecmp_width


@dataclass(frozen=True)
class DownlinkConfig:
    """Configuration for an IXIA downlink interface with listener-only peers."""

    interface: str
    ic_parent_network_v6: str
    mac_address: str
    peer_count: int
    peer_group_name: str
    remote_as_4byte: int


# =============================================================================
# Experiments
# =============================================================================

PATH_SCALE_EXPERIMENTS = {
    "exp1_52_ecmp_15k": PathScaleExperiment(ecmp_width=52, prefix_count=15000),
    "exp2_120_ecmp_10k": PathScaleExperiment(ecmp_width=120, prefix_count=10000),
    "exp3_2048_ecmp_512": PathScaleExperiment(ecmp_width=2048, prefix_count=512),
}


# =============================================================================
# COOP Patcher Tasks
# =============================================================================


def _get_edsw_ixia_peer_group_tasks(device_name: str) -> list[Task]:
    """
    Create PEERGROUP_EDSW_IXIA_PATH_SCALE_V6 with policies that accept routes.
    """
    return [
        create_coop_register_patcher_task(
            hostname=device_name,
            config_name="bgpcpp",
            patcher_name="add_peer_group_patcher_PEERGROUP_EDSW_IXIA_PATH_SCALE_V6",
            task_name="add_peer_group_patcher",
            patcher_args={
                "name": PEERGROUP_EDSW_IXIA_PATH_SCALE_V6,
                "description": "BGP peering EDSW to IXIA, IPv6, path scale test",
                "disable_ipv4_afi": "True",
                "disable_ipv6_afi": "False",
                "ingress_policy_name": "PROPAGATE_EDSW_IXIA_PATH_SCALE_IN",
                "egress_policy_name": "PROPAGATE_EDSW_IXIA_PATH_SCALE_OUT",
                "bgp_peer_timers_hold_time_seconds": "30",
                "bgp_peer_timers_keep_alive_seconds": "10",
                "bgp_peer_timers_out_delay_seconds": "0",
                "bgp_peer_timers_withdraw_unprog_delay_seconds": "0",
                "peer_tag": "IXIA",
                "max_routes": "900000",
                "warning_only": "True",
                "warning_limit": "0",
                "next_hop_self": "True",
                "is_confed_peer": "False",
                "is_passive": "False",
                "add_path": "BOTH",
                "v4_over_v6_nexthop": "False",
                "link_bandwidth_bps": "auto",
            },
            py_func_name="add_peer_group_patcher",
        ),
        create_coop_register_patcher_task(
            hostname=device_name,
            config_name="bgpcpp",
            patcher_name="a_add_bgp_policy_statement_PROPAGATE_EDSW_IXIA_PATH_SCALE_IN",
            task_name="add_bgp_policy_statement",
            patcher_args={
                "name": "PROPAGATE_EDSW_IXIA_PATH_SCALE_IN",
                "description": "Accept routes from IXIA for path scale test",
            },
            py_func_name="add_bgp_policy_statement",
        ),
        create_coop_register_patcher_task(
            hostname=device_name,
            config_name="bgpcpp",
            patcher_name="a_add_bgp_policy_statement_PROPAGATE_EDSW_IXIA_PATH_SCALE_OUT",
            task_name="add_bgp_policy_statement",
            patcher_args={
                "name": "PROPAGATE_EDSW_IXIA_PATH_SCALE_OUT",
                "description": "Egress policy for IXIA path scale test",
            },
            py_func_name="add_bgp_policy_statement",
        ),
        create_coop_register_patcher_task(
            hostname=device_name,
            config_name="bgpcpp",
            patcher_name="add_bgp_policy_match_prefix_to_propagate_routes_PROPAGATE_EDSW_IXIA_PATH_SCALE_IN_v6",
            task_name="add_bgp_policy_match_prefix_to_propagate_routes",
            patcher_args={
                "matching_prefix": "5000::/16",
                "in_stmt_name": "PROPAGATE_EDSW_IXIA_PATH_SCALE_IN",
                "out_stmt_name": "RANDOM",
            },
            py_func_name="add_bgp_policy_match_prefix_to_propagate_routes",
        ),
    ]


def _get_edsw_bag_policy_tasks(device_name: str) -> list[Task]:
    """
    Create policy statements for the existing PEERGROUP_EDSW_BAG_V6
    peer group used by downlink listener peers.
    """
    return [
        create_coop_register_patcher_task(
            hostname=device_name,
            config_name="bgpcpp",
            patcher_name="a_add_bgp_policy_statement_PROPAGATE_EDSW_BAG_IN",
            task_name="add_bgp_policy_statement",
            patcher_args={
                "name": "PROPAGATE_EDSW_BAG_IN",
                "description": "Accept routes for BAG downlink",
            },
            py_func_name="add_bgp_policy_statement",
        ),
        create_coop_register_patcher_task(
            hostname=device_name,
            config_name="bgpcpp",
            patcher_name="a_add_bgp_policy_statement_PROPAGATE_EDSW_BAG_OUT",
            task_name="add_bgp_policy_statement",
            patcher_args={
                "name": "PROPAGATE_EDSW_BAG_OUT",
                "description": "Egress policy for BAG downlink",
            },
            py_func_name="add_bgp_policy_statement",
        ),
        create_coop_register_patcher_task(
            hostname=device_name,
            config_name="bgpcpp",
            patcher_name="add_bgp_policy_match_prefix_to_propagate_routes_PROPAGATE_EDSW_BAG_OUT_v6",
            task_name="add_bgp_policy_match_prefix_to_propagate_routes",
            patcher_args={
                "matching_prefix": "5000::/16",
                "in_stmt_name": "PROPAGATE_EDSW_BAG_OUT",
                "out_stmt_name": "RANDOM",
            },
            py_func_name="add_bgp_policy_match_prefix_to_propagate_routes",
        ),
    ]


# =============================================================================
# Test Config Factory
# =============================================================================


def test_config_for_edsw_bgp_path_scale(
    test_config_name,
    device_name,
    uplink_config,
    downlink_config,
    remote_as_4byte,
    experiment,
    uplink_intf_id,
    uplink_port_id,
    downlink_intf_id,
    downlink_port_id,
    longevity_duration_min=5,
    direct_ixia_connections=None,
    basset_pool=None,
):
    """
    EDSW BGP path scale test with DSF RDMA traffic.

    Uplink port: NDP_HANDLER + CHAINED BGP_MULTI_PEER with route injection.
    Downlink port: NDP_HANDLER + CHAINED BGP_MULTI_PEER (listener-only, no routes)
                   + DG2 for L3 traffic source.
    Traffic: DSF RDMA from downlink DG2 -> uplink network group.

    EDSW interfaces are SYSTEM_PORT type with /127 subnets. This config uses
    configure_interfaces_ip_addresses COOP patchers to add /64 secondary
    addresses on both uplink and downlink RIFs, making the broader subnet
    on-link for NDP resolution of multi-peer IXIA addresses (::100, ::101, ...).

    Path Scale = ECMP Width (uplink peers) x Prefixes/Peer + Egress (downlink peers x prefixes)

    Args:
        test_config_name: Name identifier for the test config
        device_name: DUT hostname
        uplink_config: UplinkConfig for route injection port
        downlink_config: DownlinkConfig for traffic source port
        remote_as_4byte: Remote AS number (iBGP, same as device ASN)
        experiment: PathScaleExperiment defining ECMP width and prefix count
        uplink_intf_id: FBOSS RIF intfID for the uplink interface (from agent config)
        uplink_port_id: FBOSS logical port ID for the uplink interface
        longevity_duration_min: Longevity soak duration in minutes (default 5)
        direct_ixia_connections: Direct IXIA connection configs
        basset_pool: Basset pool name
    """
    uplink_prefix = uplink_config.ic_parent_network_v6
    downlink_prefix = downlink_config.ic_parent_network_v6
    n_uplink_peers = (
        uplink_config.peer_count
        if uplink_config.peer_count is not None
        else experiment.ecmp_width
    )

    # Generate peer configs for COOP patcher
    peer_configs = []

    # Uplink peers: use test-created PEERGROUP_EDSW_IXIA_PATH_SCALE_V6
    for i in range(n_uplink_peers):
        peer_configs.append(
            {
                "local_addr": f"{uplink_prefix}::a",
                "peer_addr": f"{uplink_prefix}::{0x100 + i:x}",
                "peer_group_name": PEERGROUP_EDSW_IXIA_PATH_SCALE_V6,
                "remote_as_4_byte": str(remote_as_4byte),
                "description": f"ixia_peer_{uplink_config.interface}_{i}",
            }
        )

    # Downlink peers: use existing PEERGROUP_EDSW_BAG_V6 (listener-only)
    for i in range(downlink_config.peer_count):
        peer_configs.append(
            {
                "local_addr": f"{downlink_prefix}::a",
                "peer_addr": f"{downlink_prefix}::{0x100 + i:x}",
                "peer_group_name": downlink_config.peer_group_name,
                "remote_as_4_byte": str(downlink_config.remote_as_4byte),
                "description": f"ixia_peer_{downlink_config.interface}_{i}",
            }
        )

    all_connections = direct_ixia_connections or []
    uplink_iface = uplink_config.interface
    downlink_iface = downlink_config.interface

    # Split direct IXIA connections by interface
    uplink_connections = [c for c in all_connections if c.interface == uplink_iface]
    downlink_connections = [c for c in all_connections if c.interface == downlink_iface]

    # TC-level checks moved to playbook level
    _tc_prechecks = [
        create_systemctl_active_state_check(),
        # _create_ixia_healthcheck(),
    ]
    _tc_postchecks = [
        create_systemctl_active_state_check(),
        # _create_ixia_healthcheck(),
        create_prefix_limit_check(prefix_limit=str(experiment.prefix_count + 100)),
        create_unclean_exit_check(),
        create_memory_utilization_check(
            threshold=5 * (1024**3),
            threshold_by_service={
                "bgpd": 4.5 * (1024**3),
                "fsdb": 7 * (1024**3),
                "qsfp_service": 2 * (1024**3),
                "wedge_agent": 0.8 * 16 * (1024**3),
            },
            start_time_jq_var="test_case_start_time",
        ),
        create_cpu_utilization_check(
            threshold=100.0, start_time_jq_var="test_case_start_time"
        ),
        create_service_restart_check(
            services=["wedge_agent", "bgpd", "fsdb", "qsfp_service"]
        ),
    ]
    # TC postchecks without SERVICE_RESTART_CHECK (for playbooks that skip it)
    _tc_postchecks_no_restart = [
        c for c in _tc_postchecks if c.name != hc_types.CheckName.SERVICE_RESTART_CHECK
    ]
    _tc_snapshot_checks = [
        create_core_dumps_snapshot_check(),
    ]

    return TestConfig(
        name=test_config_name,
        ixia_protocol_verification_timeout=900,
        basset_pool=basset_pool,
        endpoints=[
            taac_types.Endpoint(
                name=device_name,
                ixia_ports=[uplink_iface],
                dut=True,
                mac_address=uplink_config.mac_address,
                direct_ixia_connections=uplink_connections,
            ),
            taac_types.Endpoint(
                name=device_name,
                ixia_ports=[downlink_iface],
                dut=True,
                mac_address=downlink_config.mac_address,
                direct_ixia_connections=downlink_connections,
            ),
        ],
        setup_tasks=[
            create_coop_unregister_patchers_task(device_name),
        ]
        + _get_edsw_ixia_peer_group_tasks(device_name)
        + _get_edsw_bag_policy_tasks(device_name)
        + [
            # Add /64 secondary addresses to uplink and downlink RIFs.
            # EDSW interfaces are SYSTEM_PORT type with /127 subnets —
            # NDP_HANDLER peers at ::100+ need a /64 on-link subnet for
            # NDP resolution. Existing /127 is preserved for production BGP.
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="agent",
                patcher_name="configure_ixia_ips_for_path_scale",
                task_name="coop_register_patcher",
                patcher_args={
                    "uplink": json.dumps(
                        {
                            "intfId": uplink_intf_id,
                            "portID": uplink_port_id,
                            "vlanId": 0,
                            "mtu": 9000,
                            "ip_addresses": [
                                f"{uplink_prefix}::/127",
                                f"{uplink_prefix}::a/64",
                            ],
                            "rif_type": SYSTEM_PORT_RIF_TYPE,
                        }
                    ),
                    "downlink": json.dumps(
                        {
                            "intfId": downlink_intf_id,
                            "portID": downlink_port_id,
                            "vlanId": 0,
                            "mtu": 9000,
                            "ip_addresses": [
                                f"{downlink_prefix}::/127",
                                f"{downlink_prefix}::a/64",
                            ],
                            "rif_type": SYSTEM_PORT_RIF_TYPE,
                        }
                    ),
                },
                py_func_name="configure_interfaces_ip_addresses",
            ),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name="add_bgp_peers_dut",
                task_name="add_bgp_peers",
                patcher_args={
                    "peer_configs": json.dumps(peer_configs),
                },
                py_func_name="add_bgp_peers",
            ),
            create_coop_apply_patchers_task(
                hostnames=[device_name],
                do_warmboot=True,
            ),
        ],
        teardown_tasks=[
            create_coop_unregister_patchers_task(device_name),
            create_coop_apply_patchers_task([device_name]),
        ],
        # Deprecated - define at playbook level
        # periodic_tasks=[],
        basic_port_configs=[
            # Downlink port: NDP handler + chained BGP listener peers + traffic source
            taac_types.BasicPortConfig(
                l1_config=DSF_L1_CONFIG,
                endpoint=f"{device_name}:{downlink_iface}",
                device_group_configs=[
                    # DG0: NDP handler for downlink listener peers
                    taac_types.DeviceGroupConfig(
                        device_group_index=0,
                        tag_name="NDP_HANDLER",
                        multiplier=downlink_config.peer_count,
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{downlink_prefix}::100",
                            increment_ip="::1",
                            gateway_starting_ip=f"{downlink_prefix}::a",
                            gateway_increment_ip="::",
                            mask=64,
                        ),
                    ),
                    # DG1: BGP listener peers (no route advertisement)
                    # Chained to DG0 for NDP resolution
                    taac_types.DeviceGroupConfig(
                        device_group_index=1,
                        tag_name="CHAINED_0:BGP_MULTI_PEER",
                        multiplier=downlink_config.peer_count,
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{downlink_prefix}::100",
                            increment_ip="::1",
                            gateway_starting_ip=f"{downlink_prefix}::a",
                            gateway_increment_ip="::",
                            mask=64,
                        ),
                        v6_bgp_config=taac_types.BgpConfig(
                            local_as_4_bytes=downlink_config.remote_as_4byte,
                            local_as_increment=0,
                            enable_4_byte_local_as=True,
                            bgp_peer_type=ixia_types.BgpPeerType.IBGP,
                            is_confed=False,
                            bgp_capabilities=[
                                ixia_types.BgpCapability.IpV6Unicast,
                            ],
                        ),
                    ),
                    # DG2: L3 traffic source (single device for DSF RDMA traffic)
                    taac_types.DeviceGroupConfig(
                        device_group_index=2,
                        tag_name="DOWNLINK_L3_TRAFFIC",
                        multiplier=1,
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{downlink_prefix}::1",
                            increment_ip="::",
                            gateway_starting_ip=f"{downlink_prefix}::",
                            gateway_increment_ip="::",
                            mask=127,
                        ),
                    ),
                ],
            ),
            # Uplink port: NDP handler + chained BGP multi-peer with route injection
            taac_types.BasicPortConfig(
                l1_config=DSF_L1_CONFIG,
                endpoint=f"{device_name}:{uplink_iface}",
                device_group_configs=[
                    # DG0: NDP handler - single device with N IPv6 addresses
                    taac_types.DeviceGroupConfig(
                        device_group_index=0,
                        tag_name="NDP_HANDLER",
                        multiplier=n_uplink_peers,
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{uplink_prefix}::100",
                            increment_ip="::1",
                            gateway_starting_ip=f"{uplink_prefix}::a",
                            gateway_increment_ip="::",
                            mask=64,
                        ),
                    ),
                    # DG1: BGP peers - N devices, each with 1 IPv6 + BGP
                    # Chained to DG0 for NDP resolution
                    taac_types.DeviceGroupConfig(
                        device_group_index=1,
                        tag_name="CHAINED_0:BGP_MULTI_PEER",
                        multiplier=n_uplink_peers,
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{uplink_prefix}::100",
                            increment_ip="::1",
                            gateway_starting_ip=f"{uplink_prefix}::a",
                            gateway_increment_ip="::",
                            mask=64,
                        ),
                        v6_bgp_config=taac_types.BgpConfig(
                            local_as_4_bytes=remote_as_4byte,
                            local_as_increment=0,
                            enable_4_byte_local_as=True,
                            bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                            is_confed=False,
                            bgp_capabilities=[
                                ixia_types.BgpCapability.IpV6Unicast,
                            ],
                            route_scales=[
                                taac_types.RouteScaleSpec(
                                    v6_route_scale=taac_types.RouteScale(
                                        starting_prefixes="5000:dd::",
                                        prefix_length=64,
                                        prefix_step="::",
                                        prefix_count=experiment.prefix_count,
                                        multiplier=1,
                                        bgp_communities=EDSW_BGP_COMMUNITIES,
                                    ),
                                    multiplier=1,
                                    network_group_index=0,
                                ),
                            ],
                        ),
                    ),
                ],
            ),
        ],
        # traffic_items_to_start=[TRAFFIC_ITEM_GOLDEN],
        # basic_traffic_item_configs=[
        #     taac_types.BasicTrafficItemConfig(
        #         name=TRAFFIC_ITEM_GOLDEN,
        #         bidirectional=False,
        #         merge_destinations=True,
        #         line_rate=30,
        #         line_rate_type=ixia_types.RateType.PERCENT_LINE_RATE,
        #         src_dest_mesh=ixia_types.SrcDestMeshType.ONE_TO_ONE,
        #         src_endpoints=[
        #             TrafficEndpoint(
        #                 name=f"{device_name}:{downlink_iface}",
        #                 device_group_index=2,  # DG2: L3 traffic source
        #             ),
        #         ],
        #         dest_endpoints=[
        #             TrafficEndpoint(
        #                 name=f"{device_name}:{uplink_iface}",
        #                 device_group_index=1,
        #                 network_group_index=0,
        #             ),
        #         ],
        #         traffic_type=ixia_types.TrafficType.IPV6,
        #         tracking_types=[ixia_types.TrafficStatsTrackingType.TRAFFIC_ITEM],
        #         frame_size_settings=DSF_FRAME_SIZES,
        #         packet_headers=DSF_RDMA_PACKET_HEADERS,
        #     ),
        # ],
        # Deprecated - define at playbook level
        # snapshot_checks (moved to each playbook)
        # Deprecated - define at playbook level
        # postchecks (moved to each playbook)
        # Deprecated - define at playbook level
        # prechecks (moved to each playbook)
        playbooks=[
            build_edsw003_bgp_path_scale_playbook(
                name="test_bgp_path_scale_longevity",
                prechecks=_tc_prechecks,
                stages=[
                    create_steps_stage(
                        steps=[
                            create_longevity_step(duration=longevity_duration_min * 60),
                        ],
                    ),
                ],
                postchecks=[
                    # _create_ixia_healthcheck(),
                    create_bgp_convergence_check(
                        convergence_threshold=600, fail_on_eor_expired=False
                    ),
                ]
                + _tc_postchecks,
                snapshot_checks=_tc_snapshot_checks,
            ),
            # --- Agent restart under path scale load ---
            build_edsw003_bgp_path_scale_playbook(
                name="test_continuous_agent_restart",
                prechecks=_tc_prechecks,
                postchecks=[
                    # _create_ixia_healthcheck(),
                    create_bgp_convergence_check(
                        convergence_threshold=600, fail_on_eor_expired=False
                    ),
                ]
                + _tc_postchecks_no_restart,
                snapshot_checks=_tc_snapshot_checks,
                stages=[
                    create_steps_stage(
                        steps=[
                            create_service_interruption_step(
                                service=Service.AGENT,
                                trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                            ),
                            create_service_convergence_step(
                                services=[Service.AGENT], timeout=600
                            ),
                        ],
                    ),
                    create_steps_stage(
                        steps=[
                            create_longevity_step(duration=120),
                        ],
                    ),
                ],
                iteration=10,
            ),
            # --- BGP restart under path scale load ---
            build_edsw003_bgp_path_scale_playbook(
                name="test_continuous_bgp_restart",
                prechecks=_tc_prechecks,
                postchecks=[
                    # _create_ixia_healthcheck(),
                    create_bgp_convergence_check(
                        convergence_threshold=600, fail_on_eor_expired=False
                    ),
                ]
                + _tc_postchecks_no_restart,
                snapshot_checks=_tc_snapshot_checks,
                stages=[
                    create_steps_stage(
                        steps=[
                            create_service_interruption_step(
                                service=Service.BGP,
                                trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                            ),
                            create_service_convergence_step(
                                services=[Service.AGENT, Service.BGP], timeout=600
                            ),
                        ],
                    ),
                    create_steps_stage(
                        steps=[
                            create_longevity_step(duration=120),
                        ],
                    ),
                ],
                iteration=10,
            ),
            # --- Agent coldboot under path scale load ---
            build_edsw003_bgp_path_scale_playbook(
                name="test_agent_coldboot",
                prechecks=_tc_prechecks,
                postchecks=[
                    # _create_ixia_healthcheck(),
                    create_bgp_convergence_check(
                        convergence_threshold=600, fail_on_eor_expired=False
                    ),
                ]
                + _tc_postchecks_no_restart,
                snapshot_checks=_tc_snapshot_checks,
                stages=[
                    create_steps_stage(
                        steps=[
                            create_service_interruption_step(
                                service=Service.AGENT,
                                trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                                create_cold_boot_file=True,
                            ),
                            create_service_convergence_step(
                                services=[Service.AGENT], timeout=600
                            ),
                        ],
                    ),
                    create_steps_stage(
                        steps=[
                            create_longevity_step(duration=180),
                        ],
                    ),
                ],
            ),
            # --- Route (prefix) flap ---
            build_edsw003_bgp_path_scale_playbook(
                name="test_route_flap",
                prechecks=_tc_prechecks,
                postchecks=[
                    # _create_ixia_healthcheck(),
                    create_bgp_convergence_check(
                        convergence_threshold=600, fail_on_eor_expired=False
                    ),
                ]
                + _tc_postchecks,
                snapshot_checks=_tc_snapshot_checks,
                stages=[
                    create_steps_stage(
                        steps=[
                            create_toggle_ixia_prefix_session_flap_churn_step(
                                churn_mode="prefix_flap",
                                enable_prefix_flap=True,
                                is_all_prefix_groups=True,
                                churn_duration_s=1000,
                            ),
                        ],
                    ),
                    create_steps_stage(
                        steps=[
                            create_toggle_ixia_prefix_session_flap_churn_step(
                                churn_mode="prefix_flap",
                                enable_prefix_flap=False,
                                is_all_prefix_groups=True,
                                churn_duration_s=0,
                            ),
                        ],
                    ),
                    create_steps_stage(
                        steps=[
                            create_ixia_api_step(
                                api_name="clear_traffic_stats", args_dict={}
                            ),
                        ],
                    ),
                    create_steps_stage(
                        steps=[
                            create_longevity_step(duration=120),
                        ],
                    ),
                ],
            ),
            # --- Session flap (all peers) ---
            build_edsw003_bgp_path_scale_playbook(
                name="test_session_flap_all_prefixes",
                prechecks=_tc_prechecks,
                postchecks=[
                    # _create_ixia_healthcheck(),
                    create_bgp_convergence_check(
                        convergence_threshold=600, fail_on_eor_expired=False
                    ),
                ]
                + _tc_postchecks,
                snapshot_checks=_tc_snapshot_checks,
                stages=[
                    create_steps_stage(
                        steps=[
                            create_toggle_ixia_prefix_session_flap_churn_step(
                                churn_mode="session_flap",
                                enable_session_flap=True,
                                is_all_session_groups=True,
                                churn_duration_s=3600,
                            ),
                        ],
                    ),
                    create_steps_stage(
                        steps=[
                            create_toggle_ixia_prefix_session_flap_churn_step(
                                churn_mode="session_flap",
                                enable_session_flap=False,
                                is_all_session_groups=True,
                                churn_duration_s=0,
                            ),
                        ],
                    ),
                    create_steps_stage(
                        steps=[
                            create_ixia_api_step(
                                api_name="clear_traffic_stats", args_dict={}
                            ),
                        ],
                    ),
                    create_steps_stage(
                        steps=[
                            create_longevity_step(duration=120),
                        ],
                    ),
                ],
            ),
            # --- Stable soak with all flaps explicitly disabled ---
            build_edsw003_bgp_path_scale_playbook(
                name="test_bgp_path_scale_no_flaps_longevity",
                prechecks=_tc_prechecks,
                postchecks=[
                    # _create_ixia_healthcheck(),
                    create_bgp_convergence_check(
                        convergence_threshold=600, fail_on_eor_expired=False
                    ),
                ]
                + _tc_postchecks,
                snapshot_checks=_tc_snapshot_checks,
                stages=[
                    create_steps_stage(
                        steps=[
                            create_toggle_ixia_prefix_session_flap_churn_step(
                                churn_mode="prefix_flap",
                                enable_prefix_flap=False,
                                is_all_prefix_groups=True,
                                churn_duration_s=0,
                            ),
                            create_toggle_ixia_prefix_session_flap_churn_step(
                                churn_mode="session_flap",
                                enable_session_flap=False,
                                is_all_session_groups=True,
                                churn_duration_s=0,
                            ),
                        ],
                    ),
                    create_steps_stage(
                        steps=[
                            create_longevity_step(duration=1800),
                        ],
                    ),
                ],
            ),
            # --- Best path recomputation via local-pref change ---
            build_edsw003_bgp_path_scale_playbook(
                name="test_best_path_recomputation_local_pref_change",
                iteration=1,
                prechecks=_tc_prechecks,
                postchecks=[
                    # _create_ixia_healthcheck(),
                    create_bgp_convergence_check(
                        convergence_threshold=600, fail_on_eor_expired=False
                    ),
                ]
                + _tc_postchecks,
                snapshot_checks=_tc_snapshot_checks,
                stages=[
                    create_steps_stage(
                        steps=[
                            create_ixia_api_step(
                                api_name="set_bgp_local_preference",
                                args_dict={
                                    "local_preference": 50,
                                    "network_group_regex": ".*BGP_PREFIX_V6.*",
                                },
                            ),
                        ],
                    ),
                    create_steps_stage(
                        steps=[
                            create_longevity_step(duration=60),
                        ],
                    ),
                    create_steps_stage(
                        steps=[
                            create_ixia_api_step(
                                api_name="set_bgp_local_preference",
                                args_dict={
                                    "local_preference": 200,
                                    "network_group_regex": ".*BGP_PREFIX_V6.*",
                                },
                            ),
                        ],
                    ),
                    create_steps_stage(
                        steps=[
                            create_longevity_step(duration=60),
                        ],
                    ),
                ],
            ),
            # --- Concurrent route flap + BGP restart ---
            build_edsw003_bgp_path_scale_playbook(
                name="test_route_flap_with_bgpd_restart",
                prechecks=_tc_prechecks,
                postchecks=[
                    # _create_ixia_healthcheck(),
                    create_bgp_convergence_check(
                        convergence_threshold=600, fail_on_eor_expired=False
                    ),
                ]
                + _tc_postchecks_no_restart,
                snapshot_checks=_tc_snapshot_checks,
                stages=[
                    create_steps_stage(
                        concurrent=True,
                        concurrent_steps=[
                            ConcurrentStep(
                                steps=[
                                    create_toggle_ixia_prefix_session_flap_churn_step(
                                        churn_mode="prefix_flap",
                                        enable_prefix_flap=True,
                                        is_all_prefix_groups=True,
                                        churn_duration_s=1800,
                                    ),
                                ],
                            ),
                            ConcurrentStep(
                                steps=[
                                    create_service_interruption_step(
                                        service=Service.BGP,
                                        trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                                    ),
                                ],
                            ),
                        ],
                    ),
                    create_steps_stage(
                        steps=[
                            create_service_convergence_step(
                                services=[Service.AGENT, Service.BGP]
                            ),
                        ],
                    ),
                    create_steps_stage(
                        steps=[
                            create_toggle_ixia_prefix_session_flap_churn_step(
                                churn_mode="prefix_flap",
                                enable_prefix_flap=False,
                                is_all_prefix_groups=True,
                                churn_duration_s=0,
                            ),
                        ],
                    ),
                    create_steps_stage(
                        steps=[
                            create_ixia_api_step(
                                api_name="clear_traffic_stats", args_dict={}
                            ),
                        ],
                    ),
                    create_steps_stage(
                        steps=[
                            create_longevity_step(duration=120),
                        ],
                    ),
                ],
            ),
            # --- Concurrent session flap + BGP restart ---
            build_edsw003_bgp_path_scale_playbook(
                name="test_session_flap_with_bgpd_restart",
                prechecks=_tc_prechecks,
                postchecks=[
                    # _create_ixia_healthcheck(),
                    create_bgp_convergence_check(
                        convergence_threshold=600, fail_on_eor_expired=False
                    ),
                ]
                + _tc_postchecks_no_restart,
                snapshot_checks=_tc_snapshot_checks,
                stages=[
                    create_steps_stage(
                        concurrent=True,
                        concurrent_steps=[
                            ConcurrentStep(
                                steps=[
                                    create_toggle_ixia_prefix_session_flap_churn_step(
                                        churn_mode="session_flap",
                                        enable_session_flap=True,
                                        is_all_session_groups=True,
                                        churn_duration_s=1800,
                                    ),
                                ],
                            ),
                            ConcurrentStep(
                                steps=[
                                    create_service_interruption_step(
                                        service=Service.BGP,
                                        trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                                    ),
                                ],
                            ),
                        ],
                    ),
                    create_steps_stage(
                        steps=[
                            create_service_convergence_step(
                                services=[Service.AGENT, Service.BGP]
                            ),
                        ],
                    ),
                    create_steps_stage(
                        steps=[
                            create_toggle_ixia_prefix_session_flap_churn_step(
                                churn_mode="session_flap",
                                enable_session_flap=False,
                                is_all_session_groups=True,
                                churn_duration_s=0,
                            ),
                        ],
                    ),
                    create_steps_stage(
                        steps=[
                            create_ixia_api_step(
                                api_name="clear_traffic_stats", args_dict={}
                            ),
                        ],
                    ),
                    create_steps_stage(
                        steps=[
                            create_longevity_step(duration=120),
                        ],
                    ),
                ],
            ),
        ],
    )


# =============================================================================
# ECMP Scale Test Config Factory (CustomNetworkGroupConfig pattern)
#
# Unlike the BGP_MULTI_PEER pattern above (1 peer = 1 ECMP member), this
# factory uses CustomNetworkGroupConfig to create wide ECMP groups with a
# single BGP peer advertising routes with many nexthops.
#
# Adapted from DSF hardening (ai_bb/dsf/dsf_hardening_test_config.py) which
# uses ecmp_width=2048 on a 3-port topology. This 2-port variant places the
# NDP_SUPPORTING_NEXTHOP device group on the same uplink port as the BGP peer.
#
# Topology (2-port):
#   IXIA (downlink, L3 src) -- eth1/17/1 -- [EDSW] -- eth1/23/1 -- IXIA (BGP + NDP nexthops)
#
# Uplink port layout:
#   DG0: NDP_SUPPORTING_NEXTHOP (multiplier=ecmp_width) — answers NDP for nexthop IPs
#   DG1: BGP_ROUTE_INJECTOR (multiplier=1) — single BGP peer with
#         CustomNetworkGroupConfig(ecmp_width=N, network_group_multiplier=prefix_count)
# =============================================================================


def test_config_for_edsw_ecmp_scale(
    test_config_name,
    device_name,
    uplink_config,
    downlink_config,
    remote_as_4byte,
    experiment,
    uplink_intf_id,
    uplink_port_id,
    downlink_intf_id,
    downlink_port_id,
    longevity_duration_min=5,
    direct_ixia_connections=None,
    basset_pool=None,
):
    """
    EDSW ECMP scale test using CustomNetworkGroupConfig pattern.

    Uses a single BGP peer with CustomNetworkGroupConfig to advertise prefixes
    with ecmp_width nexthops each. An NDP_SUPPORTING_NEXTHOP device group on
    the same uplink port provides NDP resolution for the nexthop addresses.

    This avoids the need for thousands of IXIA BGP sessions — the ECMP width
    is controlled entirely by CustomNetworkGroupConfig.ecmp_width.

    Args:
        test_config_name: Name identifier for the test config
        device_name: DUT hostname
        uplink_config: UplinkConfig for route injection port
        downlink_config: DownlinkConfig for traffic source port
        remote_as_4byte: Remote AS number for the BGP peer
        experiment: PathScaleExperiment defining ECMP width and prefix count
        uplink_intf_id: FBOSS RIF intfID for the uplink interface
        uplink_port_id: FBOSS logical port ID for the uplink interface
        downlink_intf_id: FBOSS RIF intfID for the downlink interface
        downlink_port_id: FBOSS logical port ID for the downlink interface
        longevity_duration_min: Longevity soak duration in minutes (default 5)
        direct_ixia_connections: Direct IXIA connection configs
        basset_pool: Basset pool name
    """
    uplink_prefix = uplink_config.ic_parent_network_v6
    downlink_prefix = downlink_config.ic_parent_network_v6

    # Single BGP peer for CustomNetworkGroupConfig route injection
    peer_configs = [
        {
            "local_addr": f"{uplink_prefix}::a",
            "peer_addr": f"{uplink_prefix}::100",
            "peer_group_name": PEERGROUP_EDSW_IXIA_PATH_SCALE_V6,
            "remote_as_4_byte": str(remote_as_4byte),
            "description": f"ixia_ecmp_scale_{uplink_config.interface}",
        }
    ]

    all_connections = direct_ixia_connections or []
    uplink_iface = uplink_config.interface
    downlink_iface = downlink_config.interface

    uplink_connections = [c for c in all_connections if c.interface == uplink_iface]
    downlink_connections = [c for c in all_connections if c.interface == downlink_iface]

    return TestConfig(
        name=test_config_name,
        ixia_protocol_verification_timeout=900,
        basset_pool=basset_pool,
        endpoints=[
            taac_types.Endpoint(
                name=device_name,
                ixia_ports=[uplink_iface],
                dut=True,
                mac_address=uplink_config.mac_address,
                direct_ixia_connections=uplink_connections,
            ),
            taac_types.Endpoint(
                name=device_name,
                ixia_ports=[downlink_iface],
                dut=True,
                mac_address=downlink_config.mac_address,
                direct_ixia_connections=downlink_connections,
            ),
        ],
        setup_tasks=[
            create_coop_unregister_patchers_task(device_name),
        ]
        + _get_edsw_ixia_peer_group_tasks(device_name)
        + [
            # Add /64 secondary address on uplink RIF for NDP resolution.
            # NDP_SUPPORTING_NEXTHOP peers at ::a000+ need a /64 on-link subnet.
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="agent",
                patcher_name="configure_ixia_ips_for_ecmp_scale",
                task_name="coop_register_patcher",
                patcher_args={
                    "uplink": json.dumps(
                        {
                            "intfId": uplink_intf_id,
                            "portID": uplink_port_id,
                            "vlanId": 0,
                            "mtu": 9000,
                            "ip_addresses": [
                                f"{uplink_prefix}::/127",
                                f"{uplink_prefix}::a/64",
                            ],
                            "rif_type": SYSTEM_PORT_RIF_TYPE,
                        }
                    ),
                    "downlink": json.dumps(
                        {
                            "intfId": downlink_intf_id,
                            "portID": downlink_port_id,
                            "vlanId": 0,
                            "mtu": 9000,
                            "ip_addresses": [
                                f"{downlink_prefix}::/127",
                                f"{downlink_prefix}::a/64",
                            ],
                            "rif_type": SYSTEM_PORT_RIF_TYPE,
                        }
                    ),
                },
                py_func_name="configure_interfaces_ip_addresses",
            ),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name="add_bgp_peers_dut",
                task_name="add_bgp_peers",
                patcher_args={
                    "peer_configs": json.dumps(peer_configs),
                },
                py_func_name="add_bgp_peers",
            ),
            create_coop_apply_patchers_task(
                hostnames=[device_name],
                do_warmboot=True,
            ),
        ],
        teardown_tasks=[
            create_coop_unregister_patchers_task(device_name),
            create_coop_apply_patchers_task([device_name]),
        ],
        periodic_tasks=[],
        basic_port_configs=[
            # Downlink port: L3 traffic source only (no BGP peers)
            taac_types.BasicPortConfig(
                l1_config=DSF_L1_CONFIG,
                endpoint=f"{device_name}:{downlink_iface}",
                device_group_configs=[
                    taac_types.DeviceGroupConfig(
                        device_group_index=0,
                        tag_name="DOWNLINK_L3_TRAFFIC",
                        multiplier=1,
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{downlink_prefix}::1",
                            increment_ip="::",
                            gateway_starting_ip=f"{downlink_prefix}::",
                            gateway_increment_ip="::",
                            mask=127,
                        ),
                    ),
                ],
            ),
            # Uplink port: NDP nexthop responders + BGP route injector
            taac_types.BasicPortConfig(
                l1_config=DSF_L1_CONFIG,
                endpoint=f"{device_name}:{uplink_iface}",
                device_group_configs=[
                    # DG0: NDP_SUPPORTING_NEXTHOP — provides NDP resolution
                    # for the ecmp_width nexthop addresses advertised via BGP.
                    # These addresses (::a000, ::a001, ...) must be NDP-resolvable
                    # for the DUT to program ECMP members in hardware.
                    taac_types.DeviceGroupConfig(
                        device_group_index=0,
                        tag_name="NDP_SUPPORTING_NEXTHOP",
                        multiplier=experiment.ecmp_width,
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{uplink_prefix}::a000",
                            increment_ip="::1",
                            gateway_starting_ip=f"{uplink_prefix}::a",
                            gateway_increment_ip="::",
                            mask=64,
                        ),
                    ),
                    # DG1: BGP_ROUTE_INJECTOR — single BGP peer that advertises
                    # experiment.prefix_count prefixes, each with experiment.ecmp_width
                    # nexthops pointing to the NDP addresses in DG0.
                    taac_types.DeviceGroupConfig(
                        device_group_index=1,
                        tag_name="BGP_ROUTE_INJECTOR",
                        multiplier=1,
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{uplink_prefix}::100",
                            increment_ip="::",
                            gateway_starting_ip=f"{uplink_prefix}::a",
                            gateway_increment_ip="::",
                            mask=64,
                        ),
                        v6_bgp_config=taac_types.BgpConfig(
                            local_as_4_bytes=remote_as_4byte,
                            local_as_increment=0,
                            enable_4_byte_local_as=True,
                            bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                            is_confed=False,
                            bgp_capabilities=[
                                ixia_types.BgpCapability.IpV6Unicast,
                                ixia_types.BgpCapability.Ipv6UnicastAddPath,
                            ],
                            custom_network_group_configs=[
                                ixia_types.CustomNetworkGroupConfig(
                                    device_group_name="BGP_ROUTE_INJECTOR",
                                    network_group_name="ecmp_scale_prefixes",
                                    network_group_multiplier=experiment.prefix_count,
                                    prefix_start_value="5000:dd::",
                                    prefix_length=64,
                                    nexthop_start_value=f"{uplink_prefix}::a000",
                                    nexthop_increments="::1",
                                    ecmp_width=experiment.ecmp_width,
                                    community_list=EDSW_BGP_COMMUNITIES,
                                    network_group_index=0,
                                ),
                            ],
                        ),
                    ),
                ],
            ),
        ],
        snapshot_checks=[
            create_core_dumps_snapshot_check(),
        ],
        postchecks=[
            create_systemctl_active_state_check(),
            create_ecmp_group_and_member_count_check(
                ecmp_member_count=16000, ecmp_group_count=1536
            ),
            create_prefix_limit_check(prefix_limit=str(experiment.prefix_count + 100)),
            create_unclean_exit_check(),
            create_memory_utilization_check(
                threshold=5 * (1024**3),
                threshold_by_service={
                    "bgpd": 4.5 * (1024**3),
                    "fsdb": 7 * (1024**3),
                    "qsfp_service": 2 * (1024**3),
                    "wedge_agent": 0.8 * 16 * (1024**3),
                },
                start_time_jq_var="test_case_start_time",
            ),
            create_cpu_utilization_check(
                threshold=100.0, start_time_jq_var="test_case_start_time"
            ),
            create_service_restart_check(
                services=["wedge_agent", "bgpd", "fsdb", "qsfp_service"]
            ),
        ],
        prechecks=[
            create_systemctl_active_state_check(),
        ],
        playbooks=[
            # --- Longevity soak under ECMP scale load ---
            build_edsw003_bgp_path_scale_playbook(
                name="test_ecmp_scale_longevity",
                stages=[
                    create_steps_stage(
                        steps=[
                            create_longevity_step(duration=longevity_duration_min * 60),
                        ],
                    ),
                ],
                postchecks=[
                    create_bgp_convergence_check(
                        convergence_threshold=600, fail_on_eor_expired=False
                    ),
                    create_ecmp_group_and_member_count_check(
                        ecmp_member_count=16000, ecmp_group_count=1536
                    ),
                ],
            ),
            # --- Agent restart under ECMP scale load ---
            build_edsw003_bgp_path_scale_playbook(
                name="test_continuous_agent_restart",
                postchecks_to_skip=[
                    hc_types.CheckName.SERVICE_RESTART_CHECK,
                ],
                postchecks=[
                    create_bgp_convergence_check(
                        convergence_threshold=600, fail_on_eor_expired=False
                    ),
                    create_ecmp_group_and_member_count_check(
                        ecmp_member_count=16000, ecmp_group_count=1536
                    ),
                ],
                stages=[
                    create_steps_stage(
                        steps=[
                            create_service_interruption_step(
                                service=Service.AGENT,
                                trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                            ),
                            create_service_convergence_step(
                                services=[Service.AGENT], timeout=600
                            ),
                        ],
                    ),
                    create_steps_stage(
                        steps=[
                            create_longevity_step(duration=120),
                        ],
                    ),
                ],
                iteration=10,
            ),
            # --- BGP restart under ECMP scale load ---
            build_edsw003_bgp_path_scale_playbook(
                name="test_continuous_bgp_restart",
                postchecks_to_skip=[
                    hc_types.CheckName.SERVICE_RESTART_CHECK,
                ],
                postchecks=[
                    create_bgp_convergence_check(
                        convergence_threshold=600, fail_on_eor_expired=False
                    ),
                    create_ecmp_group_and_member_count_check(
                        ecmp_member_count=16000, ecmp_group_count=1536
                    ),
                ],
                stages=[
                    create_steps_stage(
                        steps=[
                            create_service_interruption_step(
                                service=Service.BGP,
                                trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                            ),
                            create_service_convergence_step(
                                services=[Service.AGENT, Service.BGP], timeout=600
                            ),
                        ],
                    ),
                    create_steps_stage(
                        steps=[
                            create_longevity_step(duration=120),
                        ],
                    ),
                ],
                iteration=10,
            ),
            # --- Agent coldboot under ECMP scale load ---
            build_edsw003_bgp_path_scale_playbook(
                name="test_agent_coldboot",
                postchecks_to_skip=[
                    hc_types.CheckName.SERVICE_RESTART_CHECK,
                ],
                postchecks=[
                    create_bgp_convergence_check(
                        convergence_threshold=600, fail_on_eor_expired=False
                    ),
                    create_ecmp_group_and_member_count_check(
                        ecmp_member_count=16000, ecmp_group_count=1536
                    ),
                ],
                stages=[
                    create_steps_stage(
                        steps=[
                            create_service_interruption_step(
                                service=Service.AGENT,
                                trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                                create_cold_boot_file=True,
                            ),
                            create_service_convergence_step(
                                services=[Service.AGENT], timeout=600
                            ),
                        ],
                    ),
                    create_steps_stage(
                        steps=[
                            create_longevity_step(duration=180),
                        ],
                    ),
                ],
            ),
            # --- NDP nexthop flap to stress ECMP member resolution ---
            # CustomNetworkGroupConfig routes don't use standard IXIA prefix
            # pools, so TOGGLE_IXIA_PREFIX_SESSION_FLAP won't find them.
            # Instead, toggle the NDP_SUPPORTING_NEXTHOP device group to
            # make nexthops unreachable/reachable, which forces the DUT to
            # reprogram ECMP members. This is the proven DSF hardening pattern.
            build_edsw003_bgp_path_scale_playbook(
                name="test_ndp_nexthop_flap",
                postchecks=[
                    create_bgp_convergence_check(
                        convergence_threshold=600, fail_on_eor_expired=False
                    ),
                    create_ecmp_group_and_member_count_check(
                        ecmp_member_count=16000, ecmp_group_count=1536
                    ),
                ],
                stages=[
                    # Disable NDP nexthops (ECMP members become unresolved)
                    create_steps_stage(
                        steps=[
                            create_ixia_device_group_toggle_step(
                                enable=False,
                                device_group_name_regex=".*NDP_SUPPORTING_NEXTHOP.*",
                                description="Disable NDP nexthop responders — ECMP members go unresolved",
                            ),
                        ],
                    ),
                    create_steps_stage(
                        steps=[
                            create_longevity_step(duration=60),
                        ],
                    ),
                    # Re-enable NDP nexthops (ECMP members resolve again)
                    create_steps_stage(
                        steps=[
                            create_ixia_device_group_toggle_step(
                                enable=True,
                                device_group_name_regex=".*NDP_SUPPORTING_NEXTHOP.*",
                                description="Re-enable NDP nexthop responders — ECMP members resolve",
                            ),
                        ],
                    ),
                    create_steps_stage(
                        steps=[
                            create_longevity_step(duration=120),
                        ],
                    ),
                ],
                iteration=3,
            ),
            # --- Stable soak (no churn) ---
            build_edsw003_bgp_path_scale_playbook(
                name="test_ecmp_scale_no_flaps_longevity",
                postchecks=[
                    create_bgp_convergence_check(
                        convergence_threshold=600, fail_on_eor_expired=False
                    ),
                    create_ecmp_group_and_member_count_check(
                        ecmp_member_count=16000, ecmp_group_count=1536
                    ),
                ],
                stages=[
                    create_steps_stage(
                        steps=[
                            create_longevity_step(duration=1800),
                        ],
                    ),
                ],
            ),
        ],
    )


# =============================================================================
# Testbed: edsw003.n001.l201.snc1
# Uplink: eth1/23/1 -> chassis port 1/6 (iBGP peers + route injection)
# Downlink: eth1/17/1 -> chassis port 1/5 (L3 traffic source)
# =============================================================================
_EDSW003_DEVICE_NAME = "edsw003.n001.l201.snc1"
_EDSW003_MAC_ADDRESS = "02:00:00:00:0f:0b"
_EDSW003_ASN = 65062
_EDSW003_UPLINK_REMOTE_AS = 65321  # Different AS for EBGP uplink IXIA peers

_IXIA_CHASSIS_IP = "2401:db00:116:3167:21a:c5ff:fe01:7173"

_EDSW003_DIRECT_IXIA_CONNECTIONS = [
    taac_types.DirectIxiaConnection(
        interface="eth1/17/1",
        ixia_chassis_ip=_IXIA_CHASSIS_IP,
        ixia_port="1/5",
    ),
    taac_types.DirectIxiaConnection(
        interface="eth1/23/1",
        ixia_chassis_ip=_IXIA_CHASSIS_IP,
        ixia_port="1/6",
    ),
]

# IPv6 network prefixes
_EDSW003_UPLINK_PREFIX = "2401:db00:11b:d8c1"  # eth1/23/1
_EDSW003_DOWNLINK_PREFIX = "2401:db00:11b:d8c0"  # eth1/17/1

# FBOSS RIF IDs (from: fboss2 -H edsw003.n001.l201.snc1 show config running agent)
_EDSW003_UPLINK_INTF_ID = 2391  # intfID for eth1/23/1 (SYSTEM_PORT type)
_EDSW003_UPLINK_PORT_ID = 25  # logicalID for eth1/23/1
_EDSW003_DOWNLINK_INTF_ID = 2378  # intfID for eth1/17/1 (SYSTEM_PORT type)
_EDSW003_DOWNLINK_PORT_ID = 12  # logicalID for eth1/17/1


def _create_edsw003_path_scale_config(
    exp_name: str,
    experiment: PathScaleExperiment,
) -> TestConfig:
    """Create a path scale test config for edsw003.n001.l201.snc1."""
    return test_config_for_edsw_bgp_path_scale(
        test_config_name=f"EDSW003_BGP_PATH_SCALE_{exp_name.upper()}",
        device_name=_EDSW003_DEVICE_NAME,
        uplink_config=UplinkConfig(
            interface="eth1/23/1",
            ic_parent_network_v6=_EDSW003_UPLINK_PREFIX,
            mac_address=_EDSW003_MAC_ADDRESS,
        ),
        downlink_config=DownlinkConfig(
            interface="eth1/17/1",
            ic_parent_network_v6=_EDSW003_DOWNLINK_PREFIX,
            mac_address=_EDSW003_MAC_ADDRESS,
            peer_count=36,
            peer_group_name=PEERGROUP_EDSW_BAG_V6,
            remote_as_4byte=_EDSW003_ASN,
        ),
        remote_as_4byte=_EDSW003_UPLINK_REMOTE_AS,
        experiment=experiment,
        uplink_intf_id=_EDSW003_UPLINK_INTF_ID,
        uplink_port_id=_EDSW003_UPLINK_PORT_ID,
        downlink_intf_id=_EDSW003_DOWNLINK_INTF_ID,
        downlink_port_id=_EDSW003_DOWNLINK_PORT_ID,
        direct_ixia_connections=_EDSW003_DIRECT_IXIA_CONNECTIONS,
        basset_pool="networkai.test",
    )


def _create_edsw003_ecmp_scale_config(
    exp_name: str,
    experiment: PathScaleExperiment,
) -> TestConfig:
    """Create an ECMP scale test config for edsw003.n001.l201.snc1.

    Uses CustomNetworkGroupConfig pattern (1 BGP peer + NDP nexthops)
    instead of BGP_MULTI_PEER (N BGP peers).
    """
    return test_config_for_edsw_ecmp_scale(
        test_config_name=f"EDSW003_BGP_PATH_SCALE_{exp_name.upper()}",
        device_name=_EDSW003_DEVICE_NAME,
        uplink_config=UplinkConfig(
            interface="eth1/23/1",
            ic_parent_network_v6=_EDSW003_UPLINK_PREFIX,
            mac_address=_EDSW003_MAC_ADDRESS,
        ),
        downlink_config=DownlinkConfig(
            interface="eth1/17/1",
            ic_parent_network_v6=_EDSW003_DOWNLINK_PREFIX,
            mac_address=_EDSW003_MAC_ADDRESS,
            peer_count=0,
            peer_group_name=PEERGROUP_EDSW_BAG_V6,
            remote_as_4byte=_EDSW003_ASN,
        ),
        remote_as_4byte=_EDSW003_UPLINK_REMOTE_AS,
        experiment=experiment,
        uplink_intf_id=_EDSW003_UPLINK_INTF_ID,
        uplink_port_id=_EDSW003_UPLINK_PORT_ID,
        downlink_intf_id=_EDSW003_DOWNLINK_INTF_ID,
        downlink_port_id=_EDSW003_DOWNLINK_PORT_ID,
        direct_ixia_connections=_EDSW003_DIRECT_IXIA_CONNECTIONS,
        basset_pool="networkai.test.regression",
    )


# Experiment instantiations
EDSW003_EXP1_52_ECMP_15K = _create_edsw003_path_scale_config(
    "exp1_52_ecmp_15k", PATH_SCALE_EXPERIMENTS["exp1_52_ecmp_15k"]
)
EDSW003_EXP2_120_ECMP_10K = _create_edsw003_path_scale_config(
    "exp2_120_ecmp_10k", PATH_SCALE_EXPERIMENTS["exp2_120_ecmp_10k"]
)
EDSW003_EXP3_2048_ECMP_512 = _create_edsw003_ecmp_scale_config(
    "exp3_2048_ecmp_512", PATH_SCALE_EXPERIMENTS["exp3_2048_ecmp_512"]
)

EDSW003_BGP_PATH_SCALE_TEST_CONFIGS = [
    EDSW003_EXP1_52_ECMP_15K,
    EDSW003_EXP2_120_ECMP_10K,
    EDSW003_EXP3_2048_ECMP_512,
]
