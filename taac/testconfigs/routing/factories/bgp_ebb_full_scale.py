# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""Factory for the 1274-peer EBB full-scale topology."""

from collections import Counter

from taac.abstractions.physical_inventory import PhysicalInventory
from taac.abstractions.topologies.ebb_full_scale import (
    EBB_AS_NUMBERS,
    EBB_FULL_SCALE_PORT_MAP_WITH_BGPMON,
    ebb_full_scale_topology,
    EBB_PARENT_NETWORKS,
    EBB_PEER_GROUPS,
)
from taac.abstractions.topology import (
    OpenRMode,
    RoutingDeviceConfig,
)
from taac.constants import BgpPlusPlusProfile
from taac.playbooks.routing.bgp_ebb_playbooks import (
    get_bgp_ebb_attribute_churn_playbook,
    get_bgp_ebb_cold_start_playbook,
    get_bgp_ebb_daemon_restart_playbook,
    get_bgp_ebb_ebgp_route_oscillation_playbook,
    get_bgp_ebb_ebgp_session_oscillation_playbook,
    get_bgp_ebb_fauu_drain_undrain_playbook,
    get_bgp_ebb_ibgp_plane_session_oscillation_playbook,
    get_bgp_ebb_ibgp_route_oscillation_playbook,
    get_bgp_ebb_igp_pnh_metric_oscillation_playbook,
    get_bgp_ebb_igp_unresolvable_pnh_playbook,
    get_bgp_ebb_longevity_playbook,
    get_bgp_ebb_multipath_group_oscillation_playbook,
    get_bgp_ebb_nexthop_group_count_threshold_playbook,
    get_bgp_ebb_plane_drain_undrain_playbook,
    get_bgp_ebb_route_registry_runtime_update_playbook,
    get_bgp_ebb_route_storm_playbook,
)
from taac.testconfigs.routing.util.bgp_ebb_constants import (
    BGP_MON_PEER_COUNT,
    DEFAULT_PROFILE,
    EBGP_PEER_COUNT_V4,
    EBGP_PEER_COUNT_V6,
    IBGP_PEER_SCALE_PER_PLANE,
    IXIA_BGP_MON_IC_PARENT_NETWORK,
    PEERGROUP_IBGP_V4,
    PEERGROUP_IBGP_V6,
)
from taac.testconfigs.routing.util.bgp_ebb_setup_tasks import (
    build_expected_peer_identity,
)
from taac.test_as_a_config.types import TestConfig


_LONGEVITY_DURATION_SECONDS = 14400
_NEXTHOP_GROUP_THRESHOLD = 100
_RUNTIME_UPDATE_EBGP_PREFIX_COUNT = 850


def _openr_owner_kv_link(physical_inventory: PhysicalInventory) -> dict:
    link = physical_inventory.openr_standalone_link
    if link is None:
        raise ValueError("OpenR playbook requires a standalone link")
    return link.kv_link(link.owner)


def _openr_helper_kv_link(physical_inventory: PhysicalInventory) -> dict:
    link = physical_inventory.openr_standalone_link
    if link is None:
        raise ValueError("OpenR playbook requires a standalone link")
    return link.kv_link(link.helper)


def _expected_established_session_count() -> int:
    total_session_count = (
        EBGP_PEER_COUNT_V6
        + EBGP_PEER_COUNT_V4
        + BGP_MON_PEER_COUNT
        + IBGP_PEER_SCALE_PER_PLANE * 4
        + IBGP_PEER_SCALE_PER_PLANE * 4
        + IBGP_PEER_SCALE_PER_PLANE * 4
        + IBGP_PEER_SCALE_PER_PLANE * 4
    )
    return total_session_count - BGP_MON_PEER_COUNT


def _get_bgp_ebb_full_scale_playbooks(
    physical_inventory: PhysicalInventory,
    profile: BgpPlusPlusProfile,
) -> list:
    device_name = physical_inventory.device_name
    ixia_interface_mimic_ebgp = physical_inventory.ixia_ports[0][0]
    ixia_interface_mimic_ibgp = physical_inventory.ixia_ports[1][0]
    ixia_interface_mimic_bgp_mon = physical_inventory.ixia_ports[2][0]
    session_count = _expected_established_session_count()
    expected_peer_identity = build_expected_peer_identity()
    local_link = _openr_owner_kv_link(physical_inventory)
    other_link = _openr_helper_kv_link(physical_inventory)

    return [
        get_bgp_ebb_attribute_churn_playbook(
            device_name=device_name,
            peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
            peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
            total_session_count=session_count,
            observer_peer_parent_prefix=f"{IXIA_BGP_MON_IC_PARENT_NETWORK}::/80",
            profile=profile,
        ),
        get_bgp_ebb_route_storm_playbook(
            device_name=device_name,
            peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
            peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
            total_session_count=session_count,
            ixia_interface_mimic_ibgp=ixia_interface_mimic_ibgp,
            observer_peer_parent_prefix=f"{IXIA_BGP_MON_IC_PARENT_NETWORK}::/80",
            profile=profile,
        ),
        get_bgp_ebb_route_registry_runtime_update_playbook(
            device_name=device_name,
            peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
            peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
            expected_established_sessions=session_count,
            profile=profile,
        ),
        get_bgp_ebb_multipath_group_oscillation_playbook(
            device_name=device_name,
            peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
            peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
            expected_established_sessions=session_count,
            profile=profile,
        ),
        get_bgp_ebb_igp_pnh_metric_oscillation_playbook(
            device_name=device_name,
            peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
            peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
            local_link=local_link,
            other_link=other_link,
            expected_established_sessions=session_count,
            profile=profile,
            expected_peer_identity=expected_peer_identity,
        ),
        get_bgp_ebb_fauu_drain_undrain_playbook(
            device_name=device_name,
            peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
            peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
            expected_established_sessions=session_count,
            profile=profile,
            tcp_dump_capture_interface_ebgp=ixia_interface_mimic_ebgp,
            tcp_dump_capture_interface_bgpmon=ixia_interface_mimic_bgp_mon,
            tcp_dump_capture_interface_ibgp=ixia_interface_mimic_ibgp,
        ),
        get_bgp_ebb_plane_drain_undrain_playbook(
            device_name=device_name,
            peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
            peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
            expected_established_sessions=session_count,
            profile=profile,
            tcp_dump_capture_interface_ebgp=ixia_interface_mimic_ebgp,
            tcp_dump_capture_interface_bgpmon=ixia_interface_mimic_bgp_mon,
            tcp_dump_capture_interface_ibgp=ixia_interface_mimic_ibgp,
        ),
        get_bgp_ebb_longevity_playbook(
            device_name=device_name,
            duration=_LONGEVITY_DURATION_SECONDS,
        ),
        get_bgp_ebb_daemon_restart_playbook(
            device_name=device_name,
            peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
            peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
            expected_established_sessions=session_count,
            profile=profile,
            expected_peer_identity=expected_peer_identity,
            parent_prefixes_to_ignore=[f"{IXIA_BGP_MON_IC_PARENT_NETWORK}::/80"],
        ),
        get_bgp_ebb_cold_start_playbook(
            device_name=device_name,
            peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
            peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
            expected_established_sessions=session_count,
            profile=profile,
            expected_peer_identity=expected_peer_identity,
            parent_prefixes_to_ignore=[f"{IXIA_BGP_MON_IC_PARENT_NETWORK}::/80"],
        ),
        get_bgp_ebb_ebgp_session_oscillation_playbook(
            device_name=device_name,
            peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
            peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
            ipv4_session_count=EBGP_PEER_COUNT_V4,
            ipv6_session_count=EBGP_PEER_COUNT_V6,
            expected_established_sessions=session_count,
            profile=profile,
            expected_peer_identity=expected_peer_identity,
            parent_prefixes_to_ignore=[f"{IXIA_BGP_MON_IC_PARENT_NETWORK}::/80"],
        ),
        get_bgp_ebb_ebgp_route_oscillation_playbook(
            device_name=device_name,
            peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
            peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
            expected_established_sessions=session_count,
            profile=profile,
            parent_prefixes_to_ignore=[f"{IXIA_BGP_MON_IC_PARENT_NETWORK}::/80"],
        ),
        get_bgp_ebb_ibgp_plane_session_oscillation_playbook(
            device_name=device_name,
            peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
            peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
            ipv4_sessions_per_plane=IBGP_PEER_SCALE_PER_PLANE,
            ipv6_sessions_per_plane=IBGP_PEER_SCALE_PER_PLANE,
            expected_established_sessions=session_count,
            profile=profile,
            expected_peer_identity=expected_peer_identity,
            parent_prefixes_to_ignore=[f"{IXIA_BGP_MON_IC_PARENT_NETWORK}::/80"],
        ),
        get_bgp_ebb_ibgp_route_oscillation_playbook(
            device_name=device_name,
            peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
            peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
            expected_established_sessions=session_count,
            profile=profile,
            expected_peer_identity=expected_peer_identity,
            parent_prefixes_to_ignore=[f"{IXIA_BGP_MON_IC_PARENT_NETWORK}::/80"],
        ),
        get_bgp_ebb_igp_unresolvable_pnh_playbook(
            device_name=device_name,
            peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
            peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
            local_link=local_link,
            other_link=other_link,
            expected_established_sessions=session_count,
            profile=profile,
            expected_peer_identity=expected_peer_identity,
        ),
        get_bgp_ebb_nexthop_group_count_threshold_playbook(
            device_name=device_name,
            nexthop_group_threshold=_NEXTHOP_GROUP_THRESHOLD,
        ),
    ]


def create_bgp_ebb_full_scale_test_config(
    physical_inventory: PhysicalInventory,
    *,
    name: str,
    playbooks_selected: list[str] | None = None,
    profile: BgpPlusPlusProfile = DEFAULT_PROFILE,
    enable_update_group: bool = True,
) -> TestConfig:
    """Build one selectable test suite on the canonical EBB full-scale topology."""
    playbooks = _get_bgp_ebb_full_scale_playbooks(
        physical_inventory,
        profile=profile,
    )
    if playbooks_selected:
        duplicate_names = sorted(
            name for name, count in Counter(playbooks_selected).items() if count > 1
        )
        if duplicate_names:
            raise ValueError(
                f"Duplicate BGP EBB playbook selections: {duplicate_names}"
            )

        playbooks_by_name = {playbook.name: playbook for playbook in playbooks}
        unknown_names = [
            playbook_name
            for playbook_name in playbooks_selected
            if playbook_name not in playbooks_by_name
        ]
        if unknown_names:
            raise ValueError(
                "Unknown BGP EBB playbook selections: "
                f"{unknown_names}; available: {sorted(playbooks_by_name)}"
            )
        playbooks = [playbooks_by_name[name] for name in playbooks_selected]

    openr_mode = (
        OpenRMode.STANDALONE
        if profile == BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R
        else OpenRMode.NONE
    )
    enable_attribute_churn = not playbooks_selected or (
        "bgp_ebb_attribute_churn_playbook" in playbooks_selected
    )
    enable_runtime_update = not playbooks_selected or (
        "bgp_ebb_route_registry_runtime_update_playbook" in playbooks_selected
    )
    compiled = (
        ebb_full_scale_topology(
            openr_mode=openr_mode,
            enable_attribute_churn=enable_attribute_churn,
            ebgp_prefix_count=(
                _RUNTIME_UPDATE_EBGP_PREFIX_COUNT if enable_runtime_update else 750
            ),
        )
        .bind_to_inventory(
            physical_inventory=physical_inventory,
            port_map=EBB_FULL_SCALE_PORT_MAP_WITH_BGPMON,
            parent_networks=EBB_PARENT_NETWORKS,
            peer_groups=EBB_PEER_GROUPS,
            as_numbers=EBB_AS_NUMBERS,
            device_config_override=RoutingDeviceConfig(
                openr_mode=openr_mode,
                update_group_enable=enable_update_group,
            ),
        )
        .compile()
    )
    return TestConfig(
        name=name,
        skip_ixia_protocol_verification=True,
        log_collection_timeout=600,
        basset_pool="dne.test",
        endpoints=compiled.endpoints,
        host_os_type_map=compiled.host_os_type_map,
        startup_checks=[],
        setup_tasks=compiled.setup_tasks,
        teardown_tasks=compiled.teardown_tasks,
        basic_port_configs=compiled.basic_port_configs,
        playbooks=playbooks,
    )
