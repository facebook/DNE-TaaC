# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe

"""
MP3N Prefix Profiling IXIA Test Configuration.

This file defines the complete IXIA setup for MP3N prefix profiling tests.
Testbed: rtsw002.l1003.c084.ash6

FILE STRUCTURE:
    1. IMPORTS
    2. CONSTANTS
       - Distribution Types
       - Device & IXIA Configuration
       - Port Mapping
       - BGP Configuration
       - Prefix Configuration
    3. DATA CLASSES
       - PrefixMaskConfig
    4. HELPER FUNCTIONS
       - Prefix Config Helpers
       - Route Scale Helpers
       - Device Group Helpers
       - Port Config Helpers
    5. SETUP/TEARDOWN TASKS
    6. DEVICE GROUP CONFIGURATIONS
    7. PORT CONFIGURATIONS
    8. PLAYBOOK DEFINITIONS
       - Warmboot Playbook
       - BGP Restart Playbook
       - Coldboot Playbook
    9. TEST CONFIG GENERATION
    10. TEST CONFIG EXPORTS

Topology (4 ports):
    - eth1/2/1  (uplink)   -> ixia12 1/23 - Contiguous prefix stresser
    - eth1/2/5  (uplink)   -> ixia12 1/24 - Hybrid prefix stresser
    - eth1/3/1  (uplink)   -> ixia13 1/9  - Non-contiguous prefix stresser
    - eth1/3/5  (downlink) -> ixia13 1/10 - L3 traffic destination

Network Groups (3 distribution types):
    - Network Group 0: CONTIGUOUS     - Sequential prefixes (INCREMENT pattern)
    - Network Group 1: HYBRID         - Clustered prefixes (RANDOM_MASK pattern)
    - Network Group 2: NON-CONTIGUOUS - Scattered prefixes (RANDOM_MASK pattern)
"""

# =============================================================================
# SECTION 1: IMPORTS
# =============================================================================
import json
import typing as t
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List

from ixia.ixia import types as ixia_types
from taac.health_checks.healthcheck_definitions import (
    create_bgp_convergence_check,
    create_core_dumps_snapshot_check,
    create_cpu_utilization_check,
    create_ixia_packet_loss_check,
    create_memory_utilization_check,
    create_prefix_limit_check,
    create_unclean_exit_check,
)
from taac.playbooks.playbook_definitions import (
    build_mp3n_profiling_playbook,
)
from taac.stages.stage_definitions import (
    create_clear_stats_stage,
    create_enable_and_configure_stage,
    create_mp3n_bgp_restart_trigger_stage,
    create_mp3n_coldboot_trigger_stage,
    create_mp3n_warmboot_trigger_stage,
    create_packet_loss_validation_stage,
    create_start_traffic_stage,
    create_toggle_and_analyze_stage,
    create_wait_convergence_stage,
)
from taac.task_definitions import (
    create_configure_parallel_bgp_peers_task,
    create_coop_apply_patchers_task,
    create_coop_register_patcher_task,
    create_coop_unregister_patchers_task,
)
from taac.health_check.health_check import types as hc_types
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import (
    Params,
    Playbook,
    PointInTimeHealthCheck,
    TestConfig,
)


# =============================================================================
# SECTION 2: CONSTANTS
# =============================================================================


# -----------------------------------------------------------------------------
# 2.1 Distribution Types
# -----------------------------------------------------------------------------
class PrefixDistributionType(Enum):
    """Type of prefix distribution pattern."""

    CONTIGUOUS = "contiguous"
    HYBRID = "hybrid"
    NON_CONTIGUOUS = "non_contiguous"


# Distribution type string constants
DIST_CONTIGUOUS: str = "contiguous"
DIST_HYBRID: str = "hybrid"
DIST_NON_CONTIGUOUS: str = "non_contiguous"

# Supported prefix lengths
SUPPORTED_PREFIX_LENGTHS: list[int] = [48, 64, 80, 128]
DEFAULT_PREFIX_LENGTH: int = 64


# -----------------------------------------------------------------------------
# 2.2 Device Configuration
# -----------------------------------------------------------------------------
DEVICE_NAME: str = "rtsw002.l1003.c084.ash6"
REMOTE_AS_4BYTE: int = 65421


# -----------------------------------------------------------------------------
# 2.3 IXIA Chassis Configuration
# -----------------------------------------------------------------------------
IXIA12_CHASSIS_IP: str = "2401:db00:2066:304b::3003"  # ixia12.netcastle.ash6
IXIA13_CHASSIS_IP: str = "2401:db00:2066:304b::3002"  # ixia13.netcastle.ash6


# -----------------------------------------------------------------------------
# 2.4 Port to IXIA Mapping
# -----------------------------------------------------------------------------
# Interface       IXIA Chassis    IXIA Port    Purpose           Distribution
# --------------- --------------- ------------ ----------------- -------------
# eth1/2/1        ixia12          1/23         Prefix Stresser   Contiguous
# eth1/2/5        ixia12          1/24         Prefix Stresser   Hybrid
# eth1/3/1        ixia13          1/9          Prefix Stresser   Non-Contiguous
# eth1/3/5        ixia13          1/10         Downlink          -
# -----------------------------------------------------------------------------

# Prefix Stresser 1: Contiguous (eth1/2/1 -> ixia12 1/23)
PREFIX_STRESSER_CONTIGUOUS_INTERFACE: str = "eth1/2/1"
PREFIX_STRESSER_CONTIGUOUS_IXIA_CHASSIS: str = IXIA12_CHASSIS_IP
PREFIX_STRESSER_CONTIGUOUS_IXIA_PORT: str = "1/23"
PREFIX_STRESSER_CONTIGUOUS_NETWORK_V6: str = "2401:db00:209e:42"
PREFIX_STRESSER_CONTIGUOUS_IXIA_IP: str = f"{PREFIX_STRESSER_CONTIGUOUS_NETWORK_V6}::b"
PREFIX_STRESSER_CONTIGUOUS_GATEWAY_IP: str = (
    f"{PREFIX_STRESSER_CONTIGUOUS_NETWORK_V6}::a"
)

# Prefix Stresser 2: Hybrid (eth1/2/5 -> ixia12 1/24)
PREFIX_STRESSER_HYBRID_INTERFACE: str = "eth1/2/5"
PREFIX_STRESSER_HYBRID_IXIA_CHASSIS: str = IXIA12_CHASSIS_IP
PREFIX_STRESSER_HYBRID_IXIA_PORT: str = "1/24"
PREFIX_STRESSER_HYBRID_NETWORK_V6: str = "2401:db00:209e:43"
PREFIX_STRESSER_HYBRID_IXIA_IP: str = f"{PREFIX_STRESSER_HYBRID_NETWORK_V6}::b"
PREFIX_STRESSER_HYBRID_GATEWAY_IP: str = f"{PREFIX_STRESSER_HYBRID_NETWORK_V6}::a"

# Prefix Stresser 3: Non-Contiguous (eth1/3/1 -> ixia13 1/9)
PREFIX_STRESSER_NON_CONTIGUOUS_INTERFACE: str = "eth1/3/1"
PREFIX_STRESSER_NON_CONTIGUOUS_IXIA_CHASSIS: str = IXIA13_CHASSIS_IP
PREFIX_STRESSER_NON_CONTIGUOUS_IXIA_PORT: str = "1/9"
PREFIX_STRESSER_NON_CONTIGUOUS_NETWORK_V6: str = "2401:db00:209e:44"
PREFIX_STRESSER_NON_CONTIGUOUS_IXIA_IP: str = (
    f"{PREFIX_STRESSER_NON_CONTIGUOUS_NETWORK_V6}::b"
)
PREFIX_STRESSER_NON_CONTIGUOUS_GATEWAY_IP: str = (
    f"{PREFIX_STRESSER_NON_CONTIGUOUS_NETWORK_V6}::a"
)


# Distribution type to interface mapping
DISTRIBUTION_INTERFACE_MAP: Dict[str, str] = {
    "contiguous": PREFIX_STRESSER_CONTIGUOUS_INTERFACE,
    "hybrid": PREFIX_STRESSER_HYBRID_INTERFACE,
    "non_contiguous": PREFIX_STRESSER_NON_CONTIGUOUS_INTERFACE,
}

# Distribution type to traffic item name mapping
DISTRIBUTION_TRAFFIC_ITEM_MAP: Dict[str, str] = {
    DIST_CONTIGUOUS: "TRAFFIC_TO_CONTIGUOUS_PREFIXES",
    DIST_HYBRID: "TRAFFIC_TO_HYBRID_PREFIXES",
    DIST_NON_CONTIGUOUS: "TRAFFIC_TO_NON_CONTIGUOUS_PREFIXES",
}


# -----------------------------------------------------------------------------
# 2.5 BGP Configuration
# -----------------------------------------------------------------------------
PEERGROUP_RTSW_IXIA_V6: str = "PEERGROUP_RTSW_IXIA_V6"

DEFAULT_BGP_PEER_CONFIGS: List[Dict[str, str]] = [
    {
        "local_ip": PREFIX_STRESSER_CONTIGUOUS_GATEWAY_IP,
        "peer_ip": PREFIX_STRESSER_CONTIGUOUS_IXIA_IP,
        "description": "ixia_mp3n_contiguous",
    },
    {
        "local_ip": PREFIX_STRESSER_HYBRID_GATEWAY_IP,
        "peer_ip": PREFIX_STRESSER_HYBRID_IXIA_IP,
        "description": "ixia_mp3n_hybrid",
    },
    {
        "local_ip": PREFIX_STRESSER_NON_CONTIGUOUS_GATEWAY_IP,
        "peer_ip": PREFIX_STRESSER_NON_CONTIGUOUS_IXIA_IP,
        "description": "ixia_mp3n_non_contiguous",
    },
]

# Network group descriptions
NETWORK_GROUP_DESCRIPTIONS: Dict[int, str] = {
    0: "Contiguous (INCREMENT pattern)",
    1: "Hybrid (RANDOM_MASK pattern)",
    2: "Non-contiguous (RANDOM_MASK pattern)",
}


# -----------------------------------------------------------------------------
# 2.6 L1 Configuration
# -----------------------------------------------------------------------------
MP3N_L1_CONFIG: ixia_types.L1Config = ixia_types.L1Config(
    enable_fcoe=True,
)


# =============================================================================
# SECTION 3: DATA CLASSES
# =============================================================================


# -----------------------------------------------------------------------------
# 3.1 PrefixMaskConfig
# -----------------------------------------------------------------------------
@dataclass(frozen=True)
class PrefixMaskConfig:
    """Configuration for prefix generation.

    For CONTIGUOUS (INCREMENT pattern): Uses prefix_step (IXIA default)
    For HYBRID/NON_CONTIGUOUS (RANDOM_MASK): Uses random_mask via API
    """

    fixed_prefix: str
    random_mask: str
    seed: int
    prefix_count: int
    prefix_length: int
    prefix_step: str
    multiplier: int


# -----------------------------------------------------------------------------
# 3.2 Prefix Configurations by Distribution Type
# -----------------------------------------------------------------------------

# CONTIGUOUS: INCREMENT pattern (sequential prefixes)
# count=1, multiplier=69900 (1 prefix per group, 69900 groups)
CONTIGUOUS_PREFIX_CONFIGS: dict[int, PrefixMaskConfig] = {
    48: PrefixMaskConfig(
        fixed_prefix="6000:0:0:0:0:0:0:0",
        random_mask="0:0:0:0:0:0:0:0",
        seed=1,
        prefix_count=1,
        prefix_length=48,
        prefix_step="0:0:1:0:0:0:0:0",
        multiplier=69900,
    ),
    64: PrefixMaskConfig(
        fixed_prefix="6000:0:0:0:0:0:0:0",
        random_mask="0:0:0:0:0:0:0:0",
        seed=1,
        prefix_count=1,
        prefix_length=64,
        prefix_step="0:0:0:1:0:0:0:0",
        multiplier=69900,
    ),
    80: PrefixMaskConfig(
        fixed_prefix="6000:0:0:0:0:0:0:0",
        random_mask="0:0:0:0:0:0:0:0",
        seed=1,
        prefix_count=1,
        prefix_length=80,
        prefix_step="0:0:0:0:1:0:0:0",
        multiplier=69900,
    ),
    128: PrefixMaskConfig(
        fixed_prefix="6000:0:0:0:0:0:0:0",
        random_mask="0:0:0:0:0:0:0:0",
        seed=1,
        prefix_count=1,
        prefix_length=128,
        prefix_step="0:0:0:0:0:0:0:1",
        multiplier=69900,
    ),
}

# HYBRID: RANDOM_MASK pattern (clustered prefixes)
# count=1000, multiplier=74 (1000 prefixes per group, 74 groups)
HYBRID_PREFIX_CONFIGS: dict[int, PrefixMaskConfig] = {
    48: PrefixMaskConfig(
        fixed_prefix="6000:dd:0:0:0:0:0:0",
        random_mask="0:ffff:ffff:0:0:0:0:0",
        seed=1,
        prefix_count=1000,
        prefix_length=48,
        prefix_step="0:0:1:0:0:0:0:0",
        multiplier=74,
    ),
    64: PrefixMaskConfig(
        fixed_prefix="6000:dd:0:0:0:0:0:0",
        random_mask="0:ffff:ffff:ffff:0:0:0:0",
        seed=1,
        prefix_count=1000,
        prefix_length=64,
        prefix_step="0:0:0:1:0:0:0:0",
        multiplier=74,
    ),
    80: PrefixMaskConfig(
        fixed_prefix="6000:dd:0:0:0:0:0:0",
        random_mask="0:ffff:ffff:ffff:ffff:0:0:0",
        seed=1,
        prefix_count=1000,
        prefix_length=80,
        prefix_step="0:0:0:0:1:0:0:0",
        multiplier=74,
    ),
    128: PrefixMaskConfig(
        fixed_prefix="6000:dd:0:0:0:0:0:0",
        random_mask="0:ffff:ffff:ffff:ffff:ffff:ffff:ffff",
        seed=1,
        prefix_count=1000,
        prefix_length=128,
        prefix_step="0:0:0:0:0:0:0:1",
        multiplier=74,
    ),
}

# NON_CONTIGUOUS: RANDOM_MASK pattern (scattered prefixes)
# count=1, multiplier=74900 (1 prefix per group, 74900 groups)
NON_CONTIGUOUS_PREFIX_CONFIGS: dict[int, PrefixMaskConfig] = {
    48: PrefixMaskConfig(
        fixed_prefix="6000:dd:0:0:0:0:0:0",
        random_mask="0:ffff:ffff:0:0:0:0:0",
        seed=1,
        prefix_count=1,
        prefix_length=48,
        prefix_step="0:0:1:0:0:0:0:0",
        multiplier=40000,
    ),
    64: PrefixMaskConfig(
        fixed_prefix="6000:dd:0:0:0:0:0:0",
        random_mask="0:ffff:ffff:ffff:0:0:0:0",
        seed=1,
        prefix_count=1,
        prefix_length=64,
        prefix_step="0:0:0:1:0:0:0:0",
        multiplier=40000,
    ),
    80: PrefixMaskConfig(
        fixed_prefix="6000:dd:0:0:0:0:0:0",
        random_mask="0:ffff:ffff:ffff:ffff:0:0:0",
        seed=1,
        prefix_count=1,
        prefix_length=80,
        prefix_step="0:0:0:0:1:0:0:0",
        multiplier=40000,
    ),
    128: PrefixMaskConfig(
        fixed_prefix="6000:dd:0:0:0:0:0:0",
        random_mask="0:ffff:ffff:ffff:ffff:ffff:ffff:ffff",
        seed=1,
        prefix_count=1,
        prefix_length=128,
        prefix_step="0:0:0:0:0:0:0:1",
        multiplier=40000,
    ),
}


# =============================================================================
# SECTION 4: HELPER FUNCTIONS
# =============================================================================


# -----------------------------------------------------------------------------
# 4.1 Prefix Config Helpers
# -----------------------------------------------------------------------------
def get_prefix_mask_config(
    prefix_length: int,
    distribution: str,
) -> PrefixMaskConfig:
    """Get PrefixMaskConfig for a given prefix length and distribution type."""
    config_map = {
        DIST_CONTIGUOUS: CONTIGUOUS_PREFIX_CONFIGS,
        DIST_HYBRID: HYBRID_PREFIX_CONFIGS,
        DIST_NON_CONTIGUOUS: NON_CONTIGUOUS_PREFIX_CONFIGS,
    }
    configs = config_map.get(distribution, CONTIGUOUS_PREFIX_CONFIGS)
    return configs.get(prefix_length, configs[64])


# -----------------------------------------------------------------------------
# 4.2 Route Scale Helpers
# -----------------------------------------------------------------------------
def create_route_scale(
    prefix_length: int,
    distribution: str,
    network_group_index: int,
    prefix_count: int | None = None,
    multiplier: int | None = None,
    starting_prefix: str | None = None,
    bgp_communities: List[str] | None = None,
) -> taac_types.RouteScaleSpec:
    """Create a RouteScaleSpec with the specified prefix length and distribution."""
    mask_config = get_prefix_mask_config(prefix_length, distribution)

    if prefix_count is None:
        prefix_count = mask_config.prefix_count
    if multiplier is None:
        multiplier = mask_config.multiplier
    if bgp_communities is None:
        bgp_communities = ["65527:12711"]
    if starting_prefix is None:
        starting_prefix = mask_config.fixed_prefix

    # Determine pattern type based on distribution
    if distribution == DIST_CONTIGUOUS:
        pattern_type = taac_types.PrefixPatternType.INCREMENT
        prefix_step = mask_config.prefix_step
        random_mask_config = None
    else:
        pattern_type = taac_types.PrefixPatternType.RANDOM_MASK
        prefix_step = "::1"
        random_mask_config = taac_types.RandomMaskConfig(
            fixed_value=mask_config.fixed_prefix,
            mask_value=mask_config.random_mask,
            seed=mask_config.seed,
        )

    return taac_types.RouteScaleSpec(
        v6_route_scale=taac_types.RouteScale(
            prefix_name=f"PREFIX_POOL_V6_{prefix_length}_{distribution.upper()}",
            starting_prefixes=starting_prefix,
            prefix_length=prefix_length,
            prefix_step=prefix_step,
            prefix_count=prefix_count,
            multiplier=multiplier,
            bgp_communities=bgp_communities,
            pattern_type=pattern_type,
            random_mask_config=random_mask_config,
        ),
        multiplier=1,
        network_group_index=network_group_index,
    )


def get_enabled_route_scales(
    enabled_groups: List[int] | None = None,
    prefix_length: int | None = None,
) -> List[taac_types.RouteScaleSpec]:
    """Get the list of enabled RouteScaleSpec based on enabled network groups."""
    if enabled_groups is None:
        enabled_groups = [0]
    if prefix_length is None:
        prefix_length = DEFAULT_PREFIX_LENGTH

    index_to_dist = {
        0: DIST_CONTIGUOUS,
        1: DIST_HYBRID,
        2: DIST_NON_CONTIGUOUS,
    }

    return [
        create_route_scale(prefix_length, index_to_dist[idx], idx)
        for idx in enabled_groups
        if idx in index_to_dist
    ]


# -----------------------------------------------------------------------------
# 4.3 Device Group Helpers
# -----------------------------------------------------------------------------
def create_uplink_contiguous_device_group(
    prefix_length: int | None = None,
    ixia_ip: str = PREFIX_STRESSER_CONTIGUOUS_IXIA_IP,
    gateway_ip: str = PREFIX_STRESSER_CONTIGUOUS_GATEWAY_IP,
    remote_as: int = REMOTE_AS_4BYTE,
) -> taac_types.DeviceGroupConfig:
    """Create Device Group for Contiguous prefix distribution."""
    if prefix_length is None:
        prefix_length = DEFAULT_PREFIX_LENGTH

    return taac_types.DeviceGroupConfig(
        device_group_index=0,
        tag_name="PREFIX_STRESSER_CONTIGUOUS",
        multiplier=1,
        enable=True,
        v6_addresses_config=taac_types.IpAddressesConfig(
            starting_ip=ixia_ip,
            gateway_starting_ip=gateway_ip,
            increment_ip="::",
            gateway_increment_ip="::",
            mask=64,
        ),
        v6_bgp_config=taac_types.BgpConfig(
            local_as_4_bytes=remote_as,
            local_as_increment=0,
            enable_4_byte_local_as=True,
            bgp_peer_type=ixia_types.BgpPeerType.EBGP,
            is_confed=False,
            bgp_capabilities=[
                ixia_types.BgpCapability.IpV6Unicast,
                ixia_types.BgpCapability.Ipv6UnicastAddPath,
            ],
            route_scales=[create_route_scale(prefix_length, DIST_CONTIGUOUS, 0)],
        ),
    )


def create_uplink_hybrid_device_group(
    prefix_length: int | None = None,
    ixia_ip: str = PREFIX_STRESSER_HYBRID_IXIA_IP,
    gateway_ip: str = PREFIX_STRESSER_HYBRID_GATEWAY_IP,
    remote_as: int = REMOTE_AS_4BYTE,
) -> taac_types.DeviceGroupConfig:
    """Create Device Group for Hybrid prefix distribution."""
    if prefix_length is None:
        prefix_length = DEFAULT_PREFIX_LENGTH

    return taac_types.DeviceGroupConfig(
        device_group_index=0,
        tag_name="PREFIX_STRESSER_HYBRID",
        multiplier=1,
        enable=False,
        v6_addresses_config=taac_types.IpAddressesConfig(
            starting_ip=ixia_ip,
            gateway_starting_ip=gateway_ip,
            increment_ip="::",
            gateway_increment_ip="::",
            mask=64,
        ),
        v6_bgp_config=taac_types.BgpConfig(
            local_as_4_bytes=remote_as,
            local_as_increment=0,
            enable_4_byte_local_as=True,
            bgp_peer_type=ixia_types.BgpPeerType.EBGP,
            is_confed=False,
            bgp_capabilities=[
                ixia_types.BgpCapability.IpV6Unicast,
                ixia_types.BgpCapability.Ipv6UnicastAddPath,
            ],
            route_scales=[create_route_scale(prefix_length, DIST_HYBRID, 0)],
        ),
    )


def create_uplink_non_contiguous_device_group(
    prefix_length: int | None = None,
    ixia_ip: str = PREFIX_STRESSER_NON_CONTIGUOUS_IXIA_IP,
    gateway_ip: str = PREFIX_STRESSER_NON_CONTIGUOUS_GATEWAY_IP,
    remote_as: int = REMOTE_AS_4BYTE,
) -> taac_types.DeviceGroupConfig:
    """Create Device Group for Non-Contiguous prefix distribution."""
    if prefix_length is None:
        prefix_length = DEFAULT_PREFIX_LENGTH

    return taac_types.DeviceGroupConfig(
        device_group_index=0,
        tag_name="PREFIX_STRESSER_NON_CONTIGUOUS",
        multiplier=1,
        enable=False,
        v6_addresses_config=taac_types.IpAddressesConfig(
            starting_ip=ixia_ip,
            gateway_starting_ip=gateway_ip,
            increment_ip="::",
            gateway_increment_ip="::",
            mask=64,
        ),
        v6_bgp_config=taac_types.BgpConfig(
            local_as_4_bytes=remote_as,
            local_as_increment=0,
            enable_4_byte_local_as=True,
            bgp_peer_type=ixia_types.BgpPeerType.EBGP,
            is_confed=False,
            bgp_capabilities=[
                ixia_types.BgpCapability.IpV6Unicast,
                ixia_types.BgpCapability.Ipv6UnicastAddPath,
            ],
            route_scales=[create_route_scale(prefix_length, DIST_NON_CONTIGUOUS, 0)],
        ),
    )


# =============================================================================
# SECTION 5: SETUP/TEARDOWN TASKS
# =============================================================================
def create_mp3n_setup_tasks(
    device_name: str,
    peer_group: str,
    local_ip: str,
    peer_ip: str,
    interface_configs: t.Optional[t.List[t.Tuple[str, str, str, str]]] = None,
    peer_description: str = "ixia_mp3n",
    remote_as: int = REMOTE_AS_4BYTE,
    ingress_policy: str = "PROPAGATE_RTSW_IXIA_PREFIX_PROFILING_IN",
    egress_policy: str = "PROPAGATE_RTSW_IXIA_PREFIX_PROFILING_OUT",
    patcher_suffix: str = "rtsw_ixia",
) -> List[taac_types.Task]:
    """Create setup tasks to configure BGP peering on DUT.

    Args:
        interface_configs: List of (interface, local_ip, peer_ip, description) tuples.
            When provided, uses configure_parallel_bgp_peers to assign IPs + peers.
            When None, uses raw add_bgp_peers COOP patcher (for devices with pre-existing IPs).
    """
    max_routes = "2000000"

    tasks = [
        create_coop_unregister_patchers_task(device_name),
        create_coop_register_patcher_task(
            hostname=device_name,
            config_name="bgpcpp",
            patcher_name=f"add_peer_group_patcher_{peer_group}",
            task_name="add_peer_group_patcher",
            patcher_args={
                "name": peer_group,
                "description": f"BGP peer group for {peer_group} prefix profiling tests",
                "disable_ipv4_afi": "True",
                "disable_ipv6_afi": "False",
                "ingress_policy_name": ingress_policy,
                "egress_policy_name": egress_policy,
                "bgp_peer_timers_hold_time_seconds": "30",
                "bgp_peer_timers_keep_alive_seconds": "10",
                "bgp_peer_timers_out_delay_seconds": "0",
                "bgp_peer_timers_withdraw_unprog_delay_seconds": "0",
                "peer_tag": "IXIA",
                "max_routes": max_routes,
                "warning_only": "True",
                "warning_limit": "0",
                "next_hop_self": "True",
                "add_path": "BOTH",
                "is_confed_peer": "False",
                "is_passive": "False",
                "v4_over_v6_nexthop": "False",
                "link_bandwidth_bps": "auto",
            },
            py_func_name="add_peer_group_patcher",
        ),
        create_coop_register_patcher_task(
            hostname=device_name,
            config_name="bgpcpp",
            patcher_name=f"a_add_bgp_policy_statement_{ingress_policy}",
            task_name="add_bgp_policy_statement",
            patcher_args={
                "name": ingress_policy,
                "description": "Accept routes from IXIA for prefix profiling test",
            },
            py_func_name="add_bgp_policy_statement",
        ),
        create_coop_register_patcher_task(
            hostname=device_name,
            config_name="bgpcpp",
            patcher_name=f"a_add_bgp_policy_statement_{egress_policy}",
            task_name="add_bgp_policy_statement",
            patcher_args={
                "name": egress_policy,
                "description": "Egress policy for IXIA prefix profiling test",
            },
            py_func_name="add_bgp_policy_statement",
        ),
        create_coop_register_patcher_task(
            hostname=device_name,
            config_name="bgpcpp",
            patcher_name=f"add_bgp_policy_match_prefix_{ingress_policy}_v6",
            task_name="add_bgp_policy_match_prefix_to_propagate_routes",
            patcher_args={
                "matching_prefix": "::/0",
                "in_stmt_name": ingress_policy,
                "out_stmt_name": "RANDOM",
            },
            py_func_name="add_bgp_policy_match_prefix_to_propagate_routes",
        ),
    ]

    if interface_configs is not None:
        config_json = {}
        for iface, iface_local_ip, iface_peer_ip, iface_desc in interface_configs:
            config_json[iface] = [
                {
                    "starting_ip": iface_local_ip,
                    "increment_ip": "::",
                    "prefix_length": 64,
                    "description": iface_desc,
                    "peer_group_name": peer_group,
                    "num_sessions": 1,
                    "remote_as_4_byte": str(remote_as),
                    "remote_as_4_byte_step": 0,
                    "gateway_starting_ip": iface_peer_ip,
                    "gateway_increment_ip": "::",
                },
            ]
        tasks.append(
            create_configure_parallel_bgp_peers_task(
                hostname=device_name,
                configure_vlans_patcher_name=f"configure_vlans_{patcher_suffix}",
                add_bgp_peers_patcher_name=f"add_bgp_peers_{patcher_suffix}",
                config_json=json.dumps(config_json),
            )
        )
    else:
        tasks.append(
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name=f"add_bgp_peers_{patcher_suffix}",
                task_name="add_bgp_peers",
                patcher_args={
                    "peer_configs": json.dumps(
                        [
                            {
                                "local_addr": local_ip,
                                "peer_addr": peer_ip,
                                "peer_group_name": peer_group,
                                "remote_as_4_byte": str(remote_as),
                                "description": peer_description,
                            },
                        ]
                    ),
                },
                py_func_name="add_bgp_peers",
            )
        )

    tasks.append(
        create_coop_apply_patchers_task(
            hostnames=[device_name],
            do_warmboot=False,
        ),
    )

    return tasks


def create_mp3n_teardown_tasks(
    device_name: str = DEVICE_NAME,
) -> List[taac_types.Task]:
    """Create teardown tasks to cleanup DUT configuration."""
    return [
        create_coop_unregister_patchers_task(device_name),
    ]


# =============================================================================
# SECTION 6: DEVICE GROUP CONFIGURATIONS
# =============================================================================

# Downlink (eth1/3/5 -> ixia13 1/10)
DOWNLINK_INTERFACE: str = "eth1/3/5"
DOWNLINK_IXIA_CHASSIS: str = IXIA13_CHASSIS_IP
DOWNLINK_IXIA_PORT: str = "1/10"
DOWNLINK_NETWORK_V6: str = "2401:db00:209e:45"
DOWNLINK_IXIA_IP: str = f"{DOWNLINK_NETWORK_V6}::b"
DOWNLINK_GATEWAY_IP: str = f"{DOWNLINK_NETWORK_V6}::a"

DOWNLINK_DEVICE_GROUP: taac_types.DeviceGroupConfig = taac_types.DeviceGroupConfig(
    device_group_index=0,
    tag_name="DOWNLINK_L3_TRAFFIC",
    multiplier=1,
    v6_addresses_config=taac_types.IpAddressesConfig(
        starting_ip=DOWNLINK_IXIA_IP,
        gateway_starting_ip=DOWNLINK_GATEWAY_IP,
        increment_ip="::",
        gateway_increment_ip="::",
        mask=64,
    ),
)


# =============================================================================
# SECTION 7: PORT CONFIGURATIONS
# =============================================================================

# -----------------------------------------------------------------------------
# 7.1 Direct IXIA Connections
# -----------------------------------------------------------------------------
DIRECT_IXIA_CONNECTIONS: list[taac_types.DirectIxiaConnection] = [
    taac_types.DirectIxiaConnection(
        interface=PREFIX_STRESSER_CONTIGUOUS_INTERFACE,
        ixia_chassis_ip=IXIA12_CHASSIS_IP,
        ixia_port="1/23",
    ),
    taac_types.DirectIxiaConnection(
        interface=PREFIX_STRESSER_HYBRID_INTERFACE,
        ixia_chassis_ip=IXIA12_CHASSIS_IP,
        ixia_port="1/24",
    ),
    taac_types.DirectIxiaConnection(
        interface=PREFIX_STRESSER_NON_CONTIGUOUS_INTERFACE,
        ixia_chassis_ip=IXIA13_CHASSIS_IP,
        ixia_port="1/9",
    ),
    taac_types.DirectIxiaConnection(
        interface=DOWNLINK_INTERFACE,
        ixia_chassis_ip=IXIA13_CHASSIS_IP,
        ixia_port="1/10",
    ),
]

# -----------------------------------------------------------------------------
# 7.2 Basic Port Configs
# -----------------------------------------------------------------------------
DOWNLINK_PORT_CONFIG: taac_types.BasicPortConfig = taac_types.BasicPortConfig(
    l1_config=MP3N_L1_CONFIG,
    endpoint=f"{DEVICE_NAME}:{DOWNLINK_INTERFACE}",
    device_group_configs=[DOWNLINK_DEVICE_GROUP],
)

PREFIX_STRESSER_CONTIGUOUS_PORT_CONFIG: taac_types.BasicPortConfig = (
    taac_types.BasicPortConfig(
        l1_config=MP3N_L1_CONFIG,
        endpoint=f"{DEVICE_NAME}:{PREFIX_STRESSER_CONTIGUOUS_INTERFACE}",
        device_group_configs=[create_uplink_contiguous_device_group()],
    )
)

PREFIX_STRESSER_HYBRID_PORT_CONFIG: taac_types.BasicPortConfig = (
    taac_types.BasicPortConfig(
        l1_config=MP3N_L1_CONFIG,
        endpoint=f"{DEVICE_NAME}:{PREFIX_STRESSER_HYBRID_INTERFACE}",
        device_group_configs=[create_uplink_hybrid_device_group()],
    )
)

PREFIX_STRESSER_NON_CONTIGUOUS_PORT_CONFIG: taac_types.BasicPortConfig = (
    taac_types.BasicPortConfig(
        l1_config=MP3N_L1_CONFIG,
        endpoint=f"{DEVICE_NAME}:{PREFIX_STRESSER_NON_CONTIGUOUS_INTERFACE}",
        device_group_configs=[create_uplink_non_contiguous_device_group()],
    )
)


# -----------------------------------------------------------------------------
# 7.3 Port Config Collections
BASIC_PORT_CONFIGS: List[taac_types.BasicPortConfig] = [
    DOWNLINK_PORT_CONFIG,
    PREFIX_STRESSER_CONTIGUOUS_PORT_CONFIG,
    PREFIX_STRESSER_HYBRID_PORT_CONFIG,
    PREFIX_STRESSER_NON_CONTIGUOUS_PORT_CONFIG,
]

# -----------------------------------------------------------------------------
# 7.4 Endpoint Configuration
# -----------------------------------------------------------------------------
ENDPOINT: taac_types.Endpoint = taac_types.Endpoint(
    name=DEVICE_NAME,
    ixia_ports=[
        PREFIX_STRESSER_CONTIGUOUS_INTERFACE,
        PREFIX_STRESSER_HYBRID_INTERFACE,
        PREFIX_STRESSER_NON_CONTIGUOUS_INTERFACE,
        DOWNLINK_INTERFACE,
    ],
    dut=True,
    mac_address="ae:81:b5:03:d6:95",
    direct_ixia_connections=DIRECT_IXIA_CONNECTIONS,
)


# =============================================================================
# SECTION 8: PLAYBOOK DEFINITIONS
# =============================================================================

# -----------------------------------------------------------------------------
# 8.0 Prefix Count Limits per Distribution Type (for health checks)
# -----------------------------------------------------------------------------
# Total route counts + 100 buffer for PREFIX_LIMIT_CHECK
DISTRIBUTION_PREFIX_LIMITS: Dict[str, int] = {
    DIST_CONTIGUOUS: 70000,  # 69900 + 100 buffer
    DIST_HYBRID: 74100,  # 74000 + 100 buffer
    DIST_NON_CONTIGUOUS: 40100,  # 40000 + 100 buffer
}


# -----------------------------------------------------------------------------
# 8.1 Common Postchecks
# -----------------------------------------------------------------------------
def _create_common_postchecks(
    prefix_limit: int,
    bgp_convergence_threshold: int = 300,
) -> List[PointInTimeHealthCheck]:
    """Create common postchecks for all playbooks.

    Args:
        prefix_limit: Maximum expected prefix count + buffer for PREFIX_LIMIT_CHECK
        bgp_convergence_threshold: Threshold in seconds for BGP_CONVERGENCE_CHECK (default: 300)

    Note:
    - ROUTE_CONVERGENCE_TIME_CHECK: Handled by toggle_and_analyze stage (35s threshold)
    - BGP_CONVERGENCE_CHECK: Uses bgp_convergence_threshold, fail_on_eor_expired=False
    """
    return [
        create_unclean_exit_check(),
        create_prefix_limit_check(prefix_limit=str(prefix_limit)),
        create_memory_utilization_check(
            threshold=5 * (1024**3),
            threshold_by_service={
                "bgpd": 4.5 * (1024**3),
                "fsdb": 7 * (1024**3),
                "qsfp_service": 2 * (1024**3),
                "fboss_sw_agent": 0.8 * 16 * (1024**3),
                "fboss_hw_agent@0": 8 * (1024**3),
            },
            start_time_jq_var="test_case_start_time",
        ),
        create_cpu_utilization_check(
            threshold=400.0, start_time_jq_var="test_case_start_time"
        ),
        create_bgp_convergence_check(
            convergence_threshold=bgp_convergence_threshold,
            fail_on_eor_expired=False,
        ),
    ]


# -----------------------------------------------------------------------------
# 8.2 Warmboot Playbook
# -----------------------------------------------------------------------------
def create_warmboot_playbook(
    distribution_type: str,
    prefix_length: int,
    mask_config: PrefixMaskConfig,
    _network_group_index: int = 0,
    device_name: str = DEVICE_NAME,
    distribution_interface_map: Dict[str, str] | None = None,
    convergence_duration: int = 120,
) -> Playbook:
    """Create a TAAC Playbook for Warmboot testing.

    Stages:
        1. Enable/Configure target network group
        2. Wait for route install (120s) - let routes get programmed into FIB
        3. Start traffic (routes now in FIB)
        4. Warmboot trigger (agent restart, 600s timeout)
        5. Wait for convergence (120s)
        6. Validate packet loss (mid-test)
        7. Toggle and analyze route timing (DELETE/ADD x5)
           - Each iteration captures time before DELETE/ADD internally
        8. Clear stats (post-toggle)
        9. Soak (60s post-toggle)

    Note: stop_traffic is handled by IXIA_PACKET_LOSS_CHECK in postchecks.
    """
    if distribution_interface_map is None:
        distribution_interface_map = DISTRIBUTION_INTERFACE_MAP
    ng_regex = f".*PREFIX_STRESSER_{distribution_type.upper()}.*"
    dist_interface = distribution_interface_map[distribution_type]

    return build_mp3n_profiling_playbook(
        name=f"test_{distribution_type}_warmboot_{prefix_length}",
        description=(
            f"Warmboot test for {distribution_type} prefix distribution "
            f"with /{prefix_length} mask length."
        ),
        postchecks_to_skip=[
            hc_types.CheckName.SERVICE_RESTART_CHECK,
        ],
        postchecks=_create_common_postchecks(
            prefix_limit=DISTRIBUTION_PREFIX_LIMITS[distribution_type],
            bgp_convergence_threshold=300,
        )
        + [
            create_ixia_packet_loss_check(
                thresholds=[
                    hc_types.PacketLossThreshold(
                        names=[DISTRIBUTION_TRAFFIC_ITEM_MAP[distribution_type]],
                        str_value="0.3",
                        expect_packet_loss=False,
                        metric=hc_types.PacketLossMetric.DURATION,
                    ),
                ],
            ),
        ],
        snapshot_checks=[
            create_core_dumps_snapshot_check(),
        ],
        stages=[
            create_enable_and_configure_stage(
                stage_id_prefix="enable_and_configure_warmboot",
                distribution_type=distribution_type,
                prefix_length=prefix_length,
                device_name=device_name,
                uplink_interface=dist_interface,
                prefix_count=mask_config.prefix_count,
                network_group_regex=ng_regex,
                fixed_prefix=mask_config.fixed_prefix
                if distribution_type != DIST_CONTIGUOUS
                else None,
                random_mask=mask_config.random_mask
                if distribution_type != DIST_CONTIGUOUS
                else None,
                seed=mask_config.seed if distribution_type != DIST_CONTIGUOUS else None,
                random_mask_count=(
                    mask_config.prefix_count * mask_config.multiplier
                    if distribution_type == DIST_HYBRID
                    else mask_config.multiplier
                )
                if distribution_type != DIST_CONTIGUOUS
                else None,
            ),
            create_wait_convergence_stage(
                stage_id_prefix="wait_route_install_warmboot",
                distribution_type=distribution_type,
                prefix_length=prefix_length,
                duration=convergence_duration,
            ),
            create_start_traffic_stage(
                stage_id_prefix="start_traffic_warmboot",
                distribution_type=distribution_type,
                prefix_length=prefix_length,
            ),
            create_clear_stats_stage(
                stage_id_prefix="clear_stats_pre_warmboot",
                distribution_type=distribution_type,
                prefix_length=prefix_length,
            ),
            create_mp3n_warmboot_trigger_stage(
                distribution_type=distribution_type,
                prefix_length=prefix_length,
                timeout=600,
            ),
            create_wait_convergence_stage(
                stage_id_prefix="wait_warmboot",
                distribution_type=distribution_type,
                prefix_length=prefix_length,
                duration=120,
            ),
            create_packet_loss_validation_stage(
                stage_id_prefix="validate_pktloss_post_warmboot",
                distribution_type=distribution_type,
                prefix_length=prefix_length,
                traffic_item_names=[DISTRIBUTION_TRAFFIC_ITEM_MAP[distribution_type]],
                description=f"Validate zero packet loss for {distribution_type} after warmboot",
            ),
            create_toggle_and_analyze_stage(
                network_group_regex=f".*PREFIX_STRESSER_{distribution_type.upper()}.*",
                iterations=5,
                time_threshold=35,
            ),
            create_wait_convergence_stage(
                stage_id_prefix="wait_route_convergence_warmboot",
                distribution_type=distribution_type,
                prefix_length=prefix_length,
                duration=convergence_duration,
            ),
            create_clear_stats_stage(
                stage_id_prefix="clear_stats_warmboot",
                distribution_type=distribution_type,
                prefix_length=prefix_length,
            ),
            create_start_traffic_stage(
                stage_id_prefix="restart_traffic_warmboot",
                distribution_type=distribution_type,
                prefix_length=prefix_length,
            ),
            create_wait_convergence_stage(
                stage_id_prefix="soak_warmboot",
                distribution_type=distribution_type,
                prefix_length=prefix_length,
                duration=600,
            ),
        ],
    )


# -----------------------------------------------------------------------------
# 8.3 BGP Restart Playbook
# -----------------------------------------------------------------------------
def create_bgp_restart_playbook(
    distribution_type: str,
    prefix_length: int,
    mask_config: PrefixMaskConfig,
    _network_group_index: int,
    device_name: str = DEVICE_NAME,
    distribution_interface_map: Dict[str, str] | None = None,
    convergence_duration: int = 120,
) -> Playbook:
    """Create a TAAC Playbook for BGP Restart testing.

    Stages:
        1. Enable/Configure target network group
        2. Wait for route install (120s) - let routes get programmed into FIB
        3. Start traffic (routes now in FIB)
        4. BGP restart trigger (bgpd restart, 600s timeout)
        5. Wait for convergence (120s)
        6. Validate packet loss (mid-test)
        7. Toggle and analyze route timing (DELETE/ADD x5)
           - Each iteration captures time before DELETE/ADD internally
        8. Clear stats (post-toggle)
        9. Soak (60s post-toggle)

    Note: stop_traffic is handled by IXIA_PACKET_LOSS_CHECK in postchecks.
    """
    if distribution_interface_map is None:
        distribution_interface_map = DISTRIBUTION_INTERFACE_MAP
    ng_regex = f".*PREFIX_STRESSER_{distribution_type.upper()}.*"
    dist_interface = distribution_interface_map[distribution_type]

    return build_mp3n_profiling_playbook(
        name=f"bgp_restart_{distribution_type}_{prefix_length}",
        description=(
            f"BGP Restart test for {distribution_type} prefix distribution "
            f"with /{prefix_length} mask length."
        ),
        postchecks_to_skip=[
            hc_types.CheckName.SERVICE_RESTART_CHECK,
        ],
        postchecks=_create_common_postchecks(
            prefix_limit=DISTRIBUTION_PREFIX_LIMITS[distribution_type],
            bgp_convergence_threshold=300,
        )
        + [
            create_ixia_packet_loss_check(
                thresholds=[
                    hc_types.PacketLossThreshold(
                        names=[DISTRIBUTION_TRAFFIC_ITEM_MAP[distribution_type]],
                        str_value="0.3",
                        expect_packet_loss=False,
                        metric=hc_types.PacketLossMetric.DURATION,
                    ),
                ],
            ),
        ],
        snapshot_checks=[
            create_core_dumps_snapshot_check(),
        ],
        stages=[
            create_enable_and_configure_stage(
                stage_id_prefix="enable_and_configure_bgp_restart",
                distribution_type=distribution_type,
                prefix_length=prefix_length,
                device_name=device_name,
                uplink_interface=dist_interface,
                prefix_count=mask_config.prefix_count,
                network_group_regex=ng_regex,
                fixed_prefix=mask_config.fixed_prefix
                if distribution_type != DIST_CONTIGUOUS
                else None,
                random_mask=mask_config.random_mask
                if distribution_type != DIST_CONTIGUOUS
                else None,
                seed=mask_config.seed if distribution_type != DIST_CONTIGUOUS else None,
                random_mask_count=(
                    mask_config.prefix_count * mask_config.multiplier
                    if distribution_type == DIST_HYBRID
                    else mask_config.multiplier
                )
                if distribution_type != DIST_CONTIGUOUS
                else None,
            ),
            create_wait_convergence_stage(
                stage_id_prefix="wait_route_install_bgp_restart",
                distribution_type=distribution_type,
                prefix_length=prefix_length,
                duration=convergence_duration,
            ),
            create_start_traffic_stage(
                stage_id_prefix="start_traffic_bgp_restart",
                distribution_type=distribution_type,
                prefix_length=prefix_length,
            ),
            create_clear_stats_stage(
                stage_id_prefix="clear_stats_pre_bgp_restart",
                distribution_type=distribution_type,
                prefix_length=prefix_length,
            ),
            create_mp3n_bgp_restart_trigger_stage(
                distribution_type=distribution_type,
                prefix_length=prefix_length,
                timeout=600,
            ),
            create_wait_convergence_stage(
                stage_id_prefix="wait_bgp_restart",
                distribution_type=distribution_type,
                prefix_length=prefix_length,
                duration=120,
            ),
            create_packet_loss_validation_stage(
                stage_id_prefix="validate_pktloss_post_bgp_restart",
                distribution_type=distribution_type,
                prefix_length=prefix_length,
                traffic_item_names=[DISTRIBUTION_TRAFFIC_ITEM_MAP[distribution_type]],
                description=f"Validate zero packet loss for {distribution_type} after BGP restart",
            ),
            create_toggle_and_analyze_stage(
                network_group_regex=f".*PREFIX_STRESSER_{distribution_type.upper()}.*",
                iterations=5,
                time_threshold=35,
            ),
            create_wait_convergence_stage(
                stage_id_prefix="wait_route_convergence_bgp_restart",
                distribution_type=distribution_type,
                prefix_length=prefix_length,
                duration=convergence_duration,
            ),
            create_clear_stats_stage(
                stage_id_prefix="clear_stats_bgp_restart",
                distribution_type=distribution_type,
                prefix_length=prefix_length,
            ),
            create_start_traffic_stage(
                stage_id_prefix="restart_traffic_bgp_restart",
                distribution_type=distribution_type,
                prefix_length=prefix_length,
            ),
            create_wait_convergence_stage(
                stage_id_prefix="soak_bgp_restart",
                distribution_type=distribution_type,
                prefix_length=prefix_length,
                duration=600,
            ),
        ],
    )


# -----------------------------------------------------------------------------
# 8.4 Coldboot Playbook
# -----------------------------------------------------------------------------
def create_coldboot_playbook(
    distribution_type: str,
    prefix_length: int,
    mask_config: PrefixMaskConfig,
    _network_group_index: int,
    device_name: str = DEVICE_NAME,
    distribution_interface_map: Dict[str, str] | None = None,
    convergence_duration: int = 120,
) -> Playbook:
    """Create a TAAC Playbook for Coldboot testing.

    Stages:
        1. Enable/Configure target network group
        2. Wait for route install (120s) - let routes get programmed into FIB
        3. Start traffic (routes now in FIB)
        4. Coldboot trigger (agent restart + cold_boot_file, 900s timeout)
        5. Wait for convergence (300s)
        6. Clear stats (wipe loss from reboot)
        7. Soak (60s - forwarding should be stable)
        8. Validate packet loss (mid-test, zero loss expected)
        9. Toggle and analyze route timing (DELETE/ADD x5)
        10. Clear stats (post-toggle)
        11. Soak (60s post-toggle)

    Note: stop_traffic is handled by IXIA_PACKET_LOSS_CHECK in postchecks.
    """
    if distribution_interface_map is None:
        distribution_interface_map = DISTRIBUTION_INTERFACE_MAP
    ng_regex = f".*PREFIX_STRESSER_{distribution_type.upper()}.*"
    dist_interface = distribution_interface_map[distribution_type]

    return build_mp3n_profiling_playbook(
        name=f"test_{distribution_type}_coldboot_{prefix_length}",
        description=(
            f"Coldboot test for {distribution_type} prefix distribution "
            f"with /{prefix_length} mask length."
        ),
        postchecks_to_skip=[
            hc_types.CheckName.SERVICE_RESTART_CHECK,
        ],
        postchecks=_create_common_postchecks(
            prefix_limit=DISTRIBUTION_PREFIX_LIMITS[distribution_type],
            bgp_convergence_threshold=300,
        )
        + [
            create_ixia_packet_loss_check(
                thresholds=[
                    hc_types.PacketLossThreshold(
                        names=[DISTRIBUTION_TRAFFIC_ITEM_MAP[distribution_type]],
                        str_value="0.3",
                        expect_packet_loss=False,
                        metric=hc_types.PacketLossMetric.DURATION,
                    ),
                ],
            ),
        ],
        snapshot_checks=[
            create_core_dumps_snapshot_check(),
        ],
        stages=[
            create_enable_and_configure_stage(
                stage_id_prefix="enable_and_configure_coldboot",
                distribution_type=distribution_type,
                prefix_length=prefix_length,
                device_name=device_name,
                uplink_interface=dist_interface,
                prefix_count=mask_config.prefix_count,
                network_group_regex=ng_regex,
                fixed_prefix=mask_config.fixed_prefix
                if distribution_type != DIST_CONTIGUOUS
                else None,
                random_mask=mask_config.random_mask
                if distribution_type != DIST_CONTIGUOUS
                else None,
                seed=mask_config.seed if distribution_type != DIST_CONTIGUOUS else None,
                random_mask_count=(
                    mask_config.prefix_count * mask_config.multiplier
                    if distribution_type == DIST_HYBRID
                    else mask_config.multiplier
                )
                if distribution_type != DIST_CONTIGUOUS
                else None,
            ),
            create_wait_convergence_stage(
                stage_id_prefix="wait_route_install_coldboot",
                distribution_type=distribution_type,
                prefix_length=prefix_length,
                duration=convergence_duration,
            ),
            create_start_traffic_stage(
                stage_id_prefix="start_traffic_coldboot",
                distribution_type=distribution_type,
                prefix_length=prefix_length,
            ),
            create_clear_stats_stage(
                stage_id_prefix="clear_stats_pre_coldboot",
                distribution_type=distribution_type,
                prefix_length=prefix_length,
            ),
            create_mp3n_coldboot_trigger_stage(
                distribution_type=distribution_type,
                prefix_length=prefix_length,
                timeout=900,
            ),
            create_wait_convergence_stage(
                stage_id_prefix="wait_coldboot",
                distribution_type=distribution_type,
                prefix_length=prefix_length,
                duration=120,
            ),
            create_clear_stats_stage(
                stage_id_prefix="clear_stats_post_reboot_coldboot",
                distribution_type=distribution_type,
                prefix_length=prefix_length,
            ),
            create_wait_convergence_stage(
                stage_id_prefix="soak_post_reboot_coldboot",
                distribution_type=distribution_type,
                prefix_length=prefix_length,
                duration=60,
            ),
            create_packet_loss_validation_stage(
                stage_id_prefix="validate_pktloss_post_coldboot",
                distribution_type=distribution_type,
                prefix_length=prefix_length,
                traffic_item_names=[DISTRIBUTION_TRAFFIC_ITEM_MAP[distribution_type]],
                description=f"Validate zero packet loss for {distribution_type} after coldboot",
            ),
            create_toggle_and_analyze_stage(
                network_group_regex=f".*PREFIX_STRESSER_{distribution_type.upper()}.*",
                iterations=5,
                time_threshold=35,
            ),
            create_wait_convergence_stage(
                stage_id_prefix="wait_route_convergence_coldboot",
                distribution_type=distribution_type,
                prefix_length=prefix_length,
                duration=convergence_duration,
            ),
            create_clear_stats_stage(
                stage_id_prefix="clear_stats_coldboot",
                distribution_type=distribution_type,
                prefix_length=prefix_length,
            ),
            create_start_traffic_stage(
                stage_id_prefix="restart_traffic_coldboot",
                distribution_type=distribution_type,
                prefix_length=prefix_length,
            ),
            create_wait_convergence_stage(
                stage_id_prefix="soak_coldboot",
                distribution_type=distribution_type,
                prefix_length=prefix_length,
                duration=600,
            ),
        ],
    )


# =============================================================================
# SECTION 9: TEST CONFIG GENERATION
# =============================================================================

# -----------------------------------------------------------------------------
# 9.1 Distribution Config Mapping
# -----------------------------------------------------------------------------
DISTRIBUTION_CONFIG_MAP: dict[str, tuple[dict[int, PrefixMaskConfig], int]] = {
    DIST_CONTIGUOUS: (CONTIGUOUS_PREFIX_CONFIGS, 0),
    DIST_HYBRID: (HYBRID_PREFIX_CONFIGS, 1),
    DIST_NON_CONTIGUOUS: (NON_CONTIGUOUS_PREFIX_CONFIGS, 2),
}

DISTRIBUTION_SETUP_MAP: dict[
    str,
    tuple[list[taac_types.BasicPortConfig], str, str, str],
] = {
    DIST_CONTIGUOUS: (
        BASIC_PORT_CONFIGS,
        PREFIX_STRESSER_CONTIGUOUS_GATEWAY_IP,
        PREFIX_STRESSER_CONTIGUOUS_IXIA_IP,
        "ixia_mp3n_contiguous",
    ),
    DIST_HYBRID: (
        BASIC_PORT_CONFIGS,
        PREFIX_STRESSER_HYBRID_GATEWAY_IP,
        PREFIX_STRESSER_HYBRID_IXIA_IP,
        "ixia_mp3n_hybrid",
    ),
    DIST_NON_CONTIGUOUS: (
        BASIC_PORT_CONFIGS,
        PREFIX_STRESSER_NON_CONTIGUOUS_GATEWAY_IP,
        PREFIX_STRESSER_NON_CONTIGUOUS_IXIA_IP,
        "ixia_mp3n_non_contiguous",
    ),
}


# -----------------------------------------------------------------------------
# 9.2 Playbook Generation Functions
# -----------------------------------------------------------------------------
def create_warmboot_playbooks_for_distribution(
    distribution_type: str,
    prefix_lengths: list[int] | None = None,
    device_name: str = DEVICE_NAME,
    distribution_interface_map: Dict[str, str] | None = None,
    convergence_duration: int = 120,
) -> list[Playbook]:
    """Create warmboot playbooks for a distribution type."""
    if prefix_lengths is None:
        prefix_lengths = SUPPORTED_PREFIX_LENGTHS
    if distribution_interface_map is None:
        distribution_interface_map = DISTRIBUTION_INTERFACE_MAP
    config_dict, ng_index = DISTRIBUTION_CONFIG_MAP[distribution_type]
    return [
        create_warmboot_playbook(
            distribution_type,
            pl,
            config_dict[pl],
            ng_index,
            device_name=device_name,
            distribution_interface_map=distribution_interface_map,
            convergence_duration=convergence_duration,
        )
        for pl in prefix_lengths
    ]


def create_bgp_restart_playbooks_for_distribution(
    distribution_type: str,
    prefix_lengths: list[int] | None = None,
    device_name: str = DEVICE_NAME,
    distribution_interface_map: Dict[str, str] | None = None,
    convergence_duration: int = 120,
) -> list[Playbook]:
    """Create BGP restart playbooks for a distribution type."""
    if prefix_lengths is None:
        prefix_lengths = SUPPORTED_PREFIX_LENGTHS
    if distribution_interface_map is None:
        distribution_interface_map = DISTRIBUTION_INTERFACE_MAP
    config_dict, ng_index = DISTRIBUTION_CONFIG_MAP[distribution_type]
    return [
        create_bgp_restart_playbook(
            distribution_type,
            pl,
            config_dict[pl],
            ng_index,
            device_name=device_name,
            distribution_interface_map=distribution_interface_map,
            convergence_duration=convergence_duration,
        )
        for pl in prefix_lengths
    ]


def create_coldboot_playbooks_for_distribution(
    distribution_type: str,
    prefix_lengths: list[int] | None = None,
    device_name: str = DEVICE_NAME,
    distribution_interface_map: Dict[str, str] | None = None,
    convergence_duration: int = 120,
) -> list[Playbook]:
    """Create coldboot playbooks for a distribution type."""
    if prefix_lengths is None:
        prefix_lengths = SUPPORTED_PREFIX_LENGTHS
    if distribution_interface_map is None:
        distribution_interface_map = DISTRIBUTION_INTERFACE_MAP
    config_dict, ng_index = DISTRIBUTION_CONFIG_MAP[distribution_type]
    return [
        create_coldboot_playbook(
            distribution_type,
            pl,
            config_dict[pl],
            ng_index,
            device_name=device_name,
            distribution_interface_map=distribution_interface_map,
            convergence_duration=convergence_duration,
        )
        for pl in prefix_lengths
    ]


def create_all_playbooks_for_distribution(
    distribution_type: str,
    prefix_lengths: list[int] | None = None,
    device_name: str = DEVICE_NAME,
    distribution_interface_map: Dict[str, str] | None = None,
    convergence_duration: int = 120,
) -> list[Playbook]:
    """Create all playbooks (warmboot, BGP restart, coldboot) for a distribution."""
    if distribution_interface_map is None:
        distribution_interface_map = DISTRIBUTION_INTERFACE_MAP
    return (
        create_warmboot_playbooks_for_distribution(
            distribution_type,
            prefix_lengths,
            device_name=device_name,
            distribution_interface_map=distribution_interface_map,
            convergence_duration=convergence_duration,
        )
        + create_bgp_restart_playbooks_for_distribution(
            distribution_type,
            prefix_lengths,
            device_name=device_name,
            distribution_interface_map=distribution_interface_map,
            convergence_duration=convergence_duration,
        )
        + create_coldboot_playbooks_for_distribution(
            distribution_type,
            prefix_lengths,
            device_name=device_name,
            distribution_interface_map=distribution_interface_map,
            convergence_duration=convergence_duration,
        )
    )


# -----------------------------------------------------------------------------
# 9.3 TestConfig Generation
# -----------------------------------------------------------------------------
def create_test_config_for_distribution(
    distribution_type: str,
    prefix_lengths: list[int] | None = None,
    setup_only: bool = False,
    device_name: str = DEVICE_NAME,
    endpoint: taac_types.Endpoint | None = None,
    distribution_setup_map: dict | None = None,
    distribution_interface_map: Dict[str, str] | None = None,
    downlink_interface: str = DOWNLINK_INTERFACE,
    peer_group: str = PEERGROUP_RTSW_IXIA_V6,
    remote_as: int = REMOTE_AS_4BYTE,
    ingress_policy: str = "PROPAGATE_RTSW_IXIA_PREFIX_PROFILING_IN",
    egress_policy: str = "PROPAGATE_RTSW_IXIA_PREFIX_PROFILING_OUT",
    patcher_suffix: str = "rtsw_ixia",
    config_name_prefix: str = "MP3N_PREFIX_PROFILING_SCALE",
    basset_pool: str | None = None,
    convergence_duration: int = 120,
) -> TestConfig:
    """Create a TestConfig for a distribution type."""
    if prefix_lengths is None:
        prefix_lengths = SUPPORTED_PREFIX_LENGTHS
    if endpoint is None:
        endpoint = ENDPOINT
    if distribution_setup_map is None:
        distribution_setup_map = DISTRIBUTION_SETUP_MAP
    if distribution_interface_map is None:
        distribution_interface_map = DISTRIBUTION_INTERFACE_MAP

    port_configs, gateway_ip, ixia_ip, peer_description = distribution_setup_map[
        distribution_type
    ]

    if set(prefix_lengths) == set(SUPPORTED_PREFIX_LENGTHS):
        prefix_str = "ALL"
    else:
        prefix_str = "_".join(str(p) for p in prefix_lengths)
    suffix = "_SETUP_ONLY" if setup_only else ""
    name = (
        f"{config_name_prefix}_{distribution_type.upper()}_PREFIX_{prefix_str}{suffix}"
    )

    dist_interface = distribution_interface_map[distribution_type]
    traffic_item_name = DISTRIBUTION_TRAFFIC_ITEM_MAP[distribution_type]

    return TestConfig(
        name=name,
        basset_pool=basset_pool,
        ixia_protocol_verification_timeout=10,
        skip_ixia_protocol_verification=True,
        endpoints=[endpoint],
        basic_port_configs=port_configs,
        basic_traffic_item_configs=[
            taac_types.BasicTrafficItemConfig(
                name=traffic_item_name,
                bidirectional=False,
                merge_destinations=True,
                line_rate=10,
                src_dest_mesh=ixia_types.SrcDestMeshType.MANY_TO_MANY,
                src_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{downlink_interface}",
                        device_group_index=0,
                    ),
                ],
                dest_endpoints=[
                    taac_types.TrafficEndpoint(
                        name=f"{device_name}:{dist_interface}",
                        device_group_index=0,
                        network_group_index=0,
                    ),
                ],
                traffic_type=ixia_types.TrafficType.IPV6,
                tracking_types=[
                    ixia_types.TrafficStatsTrackingType.TRAFFIC_ITEM,
                ],
            ),
        ],
        setup_tasks=create_mp3n_setup_tasks(
            device_name=device_name,
            peer_group=peer_group,
            local_ip=gateway_ip,
            peer_ip=ixia_ip,
            peer_description=peer_description,
            remote_as=remote_as,
            ingress_policy=ingress_policy,
            egress_policy=egress_policy,
            patcher_suffix=patcher_suffix,
        ),
        teardown_tasks=create_mp3n_teardown_tasks(device_name=device_name),
        playbooks=(
            []
            if setup_only
            else create_all_playbooks_for_distribution(
                distribution_type,
                prefix_lengths,
                device_name=device_name,
                distribution_interface_map=distribution_interface_map,
                convergence_duration=convergence_duration,
            )
        ),
    )


# =============================================================================
# SECTION 10: TEST CONFIG EXPORTS
# =============================================================================

# -----------------------------------------------------------------------------
# 10.1 Contiguous Prefix Test Configs
# -----------------------------------------------------------------------------
CONTIGUOUS_PREFIX_ALL: TestConfig = create_test_config_for_distribution(DIST_CONTIGUOUS)
CONTIGUOUS_PREFIX_48: TestConfig = create_test_config_for_distribution(
    DIST_CONTIGUOUS, prefix_lengths=[48]
)
CONTIGUOUS_PREFIX_64: TestConfig = create_test_config_for_distribution(
    DIST_CONTIGUOUS, prefix_lengths=[64]
)
CONTIGUOUS_PREFIX_80: TestConfig = create_test_config_for_distribution(
    DIST_CONTIGUOUS, prefix_lengths=[80]
)
CONTIGUOUS_PREFIX_128: TestConfig = create_test_config_for_distribution(
    DIST_CONTIGUOUS, prefix_lengths=[128]
)
CONTIGUOUS_PREFIX_ALL_SETUP_ONLY: TestConfig = create_test_config_for_distribution(
    DIST_CONTIGUOUS, setup_only=True
)

# -----------------------------------------------------------------------------
# 10.2 Hybrid Prefix Test Configs
# -----------------------------------------------------------------------------
HYBRID_PREFIX_ALL: TestConfig = create_test_config_for_distribution(DIST_HYBRID)
HYBRID_PREFIX_48: TestConfig = create_test_config_for_distribution(
    DIST_HYBRID, prefix_lengths=[48]
)
HYBRID_PREFIX_64: TestConfig = create_test_config_for_distribution(
    DIST_HYBRID, prefix_lengths=[64]
)
HYBRID_PREFIX_80: TestConfig = create_test_config_for_distribution(
    DIST_HYBRID, prefix_lengths=[80]
)
HYBRID_PREFIX_128: TestConfig = create_test_config_for_distribution(
    DIST_HYBRID, prefix_lengths=[128]
)
HYBRID_PREFIX_ALL_SETUP_ONLY: TestConfig = create_test_config_for_distribution(
    DIST_HYBRID, setup_only=True
)

# -----------------------------------------------------------------------------
# 10.3 Non-Contiguous Prefix Test Configs
# -----------------------------------------------------------------------------
NON_CONTIGUOUS_PREFIX_ALL: TestConfig = create_test_config_for_distribution(
    DIST_NON_CONTIGUOUS
)
NON_CONTIGUOUS_PREFIX_48: TestConfig = create_test_config_for_distribution(
    DIST_NON_CONTIGUOUS, prefix_lengths=[48]
)
NON_CONTIGUOUS_PREFIX_64: TestConfig = create_test_config_for_distribution(
    DIST_NON_CONTIGUOUS, prefix_lengths=[64]
)
NON_CONTIGUOUS_PREFIX_80: TestConfig = create_test_config_for_distribution(
    DIST_NON_CONTIGUOUS, prefix_lengths=[80]
)
NON_CONTIGUOUS_PREFIX_128: TestConfig = create_test_config_for_distribution(
    DIST_NON_CONTIGUOUS, prefix_lengths=[128]
)
NON_CONTIGUOUS_PREFIX_ALL_SETUP_ONLY: TestConfig = create_test_config_for_distribution(
    DIST_NON_CONTIGUOUS, setup_only=True
)


# =============================================================================
# SECTION 11: MULTI-DEVICE FACTORY
# =============================================================================
def create_device_test_configs(
    device_name: str,
    remote_as: int,
    peer_group: str,
    contiguous: tuple[str, str, str, str],
    hybrid: tuple[str, str, str, str],
    non_contiguous: tuple[str, str, str, str],
    downlink: tuple[str, str, str, str],
    mac_address: str,
    ingress_policy: str,
    egress_policy: str,
    patcher_suffix: str,
    config_name_prefix: str,
    basset_pool: str | None = None,
    convergence_duration: int = 120,
) -> tuple[TestConfig, TestConfig, TestConfig]:
    """Create all MP3N test configs for a device from interface specs.

    Each spec is (interface, network_v6, ixia_chassis_ip, ixia_port).
    Returns (contiguous, hybrid, non_contiguous).
    """
    ports = {
        DIST_CONTIGUOUS: contiguous,
        DIST_HYBRID: hybrid,
        DIST_NON_CONTIGUOUS: non_contiguous,
    }
    tag_names = {
        DIST_CONTIGUOUS: "PREFIX_STRESSER_CONTIGUOUS",
        DIST_HYBRID: "PREFIX_STRESSER_HYBRID",
        DIST_NON_CONTIGUOUS: "PREFIX_STRESSER_NON_CONTIGUOUS",
    }
    enable_map = {
        DIST_CONTIGUOUS: True,
        DIST_HYBRID: False,
        DIST_NON_CONTIGUOUS: False,
    }

    dl_iface, dl_net, dl_chassis, dl_port = downlink
    dl_port_config = taac_types.BasicPortConfig(
        l1_config=MP3N_L1_CONFIG,
        endpoint=f"{device_name}:{dl_iface}",
        device_group_configs=[
            taac_types.DeviceGroupConfig(
                device_group_index=0,
                tag_name="DOWNLINK_L3_TRAFFIC",
                multiplier=1,
                v6_addresses_config=taac_types.IpAddressesConfig(
                    starting_ip=f"{dl_net}::b",
                    gateway_starting_ip=f"{dl_net}::a",
                    increment_ip="::",
                    gateway_increment_ip="::",
                    mask=64,
                ),
            )
        ],
    )
    basic_port_configs = [dl_port_config] + [
        taac_types.BasicPortConfig(
            l1_config=MP3N_L1_CONFIG,
            endpoint=f"{device_name}:{iface}",
            device_group_configs=[
                _create_parameterized_device_group(
                    dist=dist,
                    ixia_ip=f"{net}::b",
                    gateway_ip=f"{net}::a",
                    remote_as=remote_as,
                    tag_name=tag_names[dist],
                    enable=enable_map[dist],
                )
            ],
        )
        for dist, (iface, net, _c, _p) in ports.items()
    ]

    all_specs = [contiguous, hybrid, non_contiguous, downlink]
    endpoint = taac_types.Endpoint(
        name=device_name,
        ixia_ports=[s[0] for s in all_specs],
        dut=True,
        mac_address=mac_address,
        direct_ixia_connections=[
            taac_types.DirectIxiaConnection(
                interface=iface, ixia_chassis_ip=chassis, ixia_port=port
            )
            for iface, _net, chassis, port in all_specs
        ],
    )
    interface_map = {dist: spec[0] for dist, spec in ports.items()}
    setup_map = {
        dist: (basic_port_configs, f"{net}::a", f"{net}::b", f"ixia_mp3n_{dist}")
        for dist, (_iface, net, _c, _p) in ports.items()
    }

    def _make(dist: str) -> TestConfig:
        port_cfgs, gw_ip, ix_ip, peer_desc = setup_map[dist]
        dist_iface = interface_map[dist]
        traffic_name = DISTRIBUTION_TRAFFIC_ITEM_MAP[dist]
        name = f"{config_name_prefix}_{dist.upper()}_PREFIX_ALL"

        return TestConfig(
            name=name,
            basset_pool=basset_pool,
            ixia_protocol_verification_timeout=10,
            skip_ixia_protocol_verification=True,
            endpoints=[endpoint],
            basic_port_configs=port_cfgs,
            basic_traffic_item_configs=[
                taac_types.BasicTrafficItemConfig(
                    name=traffic_name,
                    bidirectional=False,
                    merge_destinations=True,
                    line_rate=10,
                    src_dest_mesh=ixia_types.SrcDestMeshType.MANY_TO_MANY,
                    src_endpoints=[
                        taac_types.TrafficEndpoint(
                            name=f"{device_name}:{dl_iface}",
                            device_group_index=0,
                        ),
                    ],
                    dest_endpoints=[
                        taac_types.TrafficEndpoint(
                            name=f"{device_name}:{dist_iface}",
                            device_group_index=0,
                            network_group_index=0,
                        ),
                    ],
                    traffic_type=ixia_types.TrafficType.IPV6,
                    tracking_types=[
                        ixia_types.TrafficStatsTrackingType.TRAFFIC_ITEM,
                    ],
                ),
            ],
            setup_tasks=create_mp3n_setup_tasks(
                device_name=device_name,
                peer_group=peer_group,
                local_ip=gw_ip,
                peer_ip=ix_ip,
                interface_configs=[
                    (iface, f"{net}::a", f"{net}::b", f"ixia_mp3n_{d}")
                    for d, (iface, net, _c, _p) in ports.items()
                ]
                + [(dl_iface, f"{dl_net}::a", f"{dl_net}::b", "ixia_mp3n_downlink")],
                peer_description=peer_desc,
                remote_as=remote_as,
                ingress_policy=ingress_policy,
                egress_policy=egress_policy,
                patcher_suffix=patcher_suffix,
            ),
            teardown_tasks=create_mp3n_teardown_tasks(device_name=device_name),
            playbooks=create_all_playbooks_for_distribution(
                dist,
                device_name=device_name,
                distribution_interface_map=interface_map,
                convergence_duration=convergence_duration,
            ),
        )

    return (
        _make(DIST_CONTIGUOUS),
        _make(DIST_HYBRID),
        _make(DIST_NON_CONTIGUOUS),
    )


def _create_parameterized_device_group(
    dist: str,
    ixia_ip: str,
    gateway_ip: str,
    remote_as: int,
    tag_name: str,
    enable: bool = True,
) -> taac_types.DeviceGroupConfig:
    """Create a parameterized DeviceGroupConfig for any device."""
    return taac_types.DeviceGroupConfig(
        device_group_index=0,
        tag_name=tag_name,
        multiplier=1,
        enable=enable,
        v6_addresses_config=taac_types.IpAddressesConfig(
            starting_ip=ixia_ip,
            gateway_starting_ip=gateway_ip,
            increment_ip="::",
            gateway_increment_ip="::",
            mask=64,
        ),
        v6_bgp_config=taac_types.BgpConfig(
            local_as_4_bytes=remote_as,
            local_as_increment=0,
            enable_4_byte_local_as=True,
            bgp_peer_type=ixia_types.BgpPeerType.EBGP,
            is_confed=False,
            bgp_capabilities=[
                ixia_types.BgpCapability.IpV6Unicast,
                ixia_types.BgpCapability.Ipv6UnicastAddPath,
            ],
            route_scales=[create_route_scale(DEFAULT_PREFIX_LENGTH, dist, 0)],
        ),
    )


# =============================================================================
# SECTION 12: GTSW001.L1001.C085.ASH6
# =============================================================================
# Topology (ixia19.netcastle.ash6):
#   eth1/1/1 -> 1/25 (contiguous), eth1/1/3 -> 1/27 (hybrid),
#   eth1/1/5 -> 1/29 (non-contiguous), eth1/1/7 -> 1/31 (downlink)

_GTSW001_CHASSIS = "2401:db00:2066:31fb::3019"

(
    GTSW001_CONTIGUOUS_PREFIX_ALL,
    GTSW001_HYBRID_PREFIX_ALL,
    GTSW001_NON_CONTIGUOUS_PREFIX_ALL,
) = create_device_test_configs(
    device_name="gtsw001.l1001.c085.ash6",
    remote_as=4200601902,
    peer_group="PEERGROUP_GTSW_IXIA_V6",
    contiguous=("eth1/1/1", "2401:db00:206a:c000", _GTSW001_CHASSIS, "1/25"),
    hybrid=("eth1/1/3", "2401:db00:206a:c002", _GTSW001_CHASSIS, "1/27"),
    non_contiguous=("eth1/1/5", "2401:db00:206a:c004", _GTSW001_CHASSIS, "1/29"),
    downlink=("eth1/1/7", "2401:db00:206a:c006", _GTSW001_CHASSIS, "1/31"),
    mac_address="02:00:00:00:00:01",  # TODO: Update with actual MAC
    ingress_policy="PROPAGATE_GTSW_IXIA_PREFIX_PROFILING_IN",
    egress_policy="PROPAGATE_GTSW_IXIA_PREFIX_PROFILING_OUT",
    patcher_suffix="gtsw_ixia",
    config_name_prefix="GTSW001_C085_MP3N_PREFIX_PROFILING_SCALE",
    basset_pool="dne.test",
    convergence_duration=300,
)
