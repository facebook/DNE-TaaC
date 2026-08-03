# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""Factory for the EBB full-scale topology."""

import ipaddress
from collections import Counter

from taac.abstractions.physical_inventory import PhysicalInventory
from taac.abstractions.topologies.ebb_full_scale import (
    EBB_ACCEPT_POLICY,
    EBB_AS_NUMBERS,
    EBB_EBGP_V4_PREFIX_SET,
    EBB_EBGP_V6_PREFIX_SET,
    EBB_FULL_SCALE_PORT_MAP,
    EBB_FULL_SCALE_PORT_MAP_WITH_BGPMON,
    ebb_full_scale_topology,
    EBB_PARENT_NETWORKS,
    EBB_PEER_GROUPS,
)
from taac.abstractions.topology import (
    BgpPeerGroup,
    BoundDeviceGroup,
    BoundTopology,
    FormulaicPrefixSource,
    NextHopIntent,
    NextHopMode,
    OpenRMode,
    PeerPrefixDistribution,
    PrefixAdvertisement,
    PrefixAllocation,
    PrefixMembership,
    PrefixSet,
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
    PEERGROUP_EBGP_V4,
    PEERGROUP_EBGP_V6,
    PEERGROUP_IBGP_V4,
    PEERGROUP_IBGP_V6,
)
from taac.testconfigs.routing.util.bgp_ebb_health_checks import (
    create_standard_postchecks,
    create_standard_prechecks,
    create_standard_snapshot_checks,
)
from taac.testconfigs.routing.util.bgp_ebb_setup_tasks import (
    build_expected_peer_identity,
)
from taac.test_as_a_config.types import (
    Playbook,
    PointInTimeHealthCheck,
    SnapshotHealthCheck,
    TestConfig,
)


_LONGEVITY_DURATION_SECONDS = 14400
_NEXTHOP_GROUP_THRESHOLD = 100
_RUNTIME_UPDATE_EBGP_PREFIX_COUNT = 850
_TC7_STATIC_EBGP_PREFIX_COUNT = 650
_TC7_EXPECTED_SESSION_COUNT = 1272
_TC7_PLAYBOOK_NAMES = (
    "bgp_ug_link_flap_recovery",
    "update_group_sustained_link_flap",
    "bgp_ug_bgp_peer_flapping",
    "bgp_ug_bgp_daemon_restart",
    "bgp_ug_cold_start",
    "bgp_ug_fibagent_restart",
)
_TC7_SHARED_IBGP_RUNTIME_POOL_V4 = "PREFIX_POOL_IBGP_IPV4_UG_2_7_RUNTIME"
_TC7_SHARED_IBGP_RUNTIME_POOL_V6 = "PREFIX_POOL_IBGP_IPV6_UG_2_7_RUNTIME"
_TC7_SHARED_EBGP_RUNTIME_POOL_V4 = "PREFIX_POOL_IPV4_EBGP_UG_2_7_RUNTIME"
_TC7_SHARED_EBGP_RUNTIME_POOL_V6 = "PREFIX_POOL_IPV6_EBGP_UG_2_7_RUNTIME"
_RuntimeRouteSpec = tuple[str, str, str, str, str, int, int]


def _prefix_at_index(prefix_set: PrefixSet, index: int) -> str:
    source = prefix_set.source
    if (
        isinstance(index, bool)
        or not isinstance(index, int)
        or not 0 <= index < source.count
    ):
        raise ValueError(
            f"Prefix index {index!r} is outside {prefix_set.name!r} inventory "
            f"[0, {source.count})"
        )
    return str(
        ipaddress.ip_address(source.start_prefix) + int(source.prefix_step) * index
    )


def _runtime_route_intent(
    *,
    pool_name: str,
    afi: str,
    start_prefix: str,
    parent_network: str,
    count: int,
    network_group_index: int,
) -> tuple[PrefixSet, PrefixAdvertisement]:
    intent_name = pool_name.lower()
    prefix_set = PrefixSet(
        name=intent_name,
        afi=afi,
        source=FormulaicPrefixSource(
            start_prefix=start_prefix,
            prefix_step=1 << (64 if afi == "v6" else 8),
            prefix_length=64 if afi == "v6" else 24,
            count=count,
            parent_network=parent_network,
        ),
    )
    advertisement = PrefixAdvertisement(
        name=f"{intent_name}_advertisement",
        prefix_set=prefix_set.name,
        allocation=PrefixAllocation(
            prefixes_per_peer=count,
            peer_distribution=PeerPrefixDistribution.SHARED,
            network_group_index=network_group_index,
        ),
        membership=PrefixMembership(
            start_index=0,
            prefix_count=count,
        ),
        next_hop=NextHopIntent(mode=NextHopMode.SELF),
        policy=EBB_ACCEPT_POLICY,
        attributes=(("med", None), ("local_pref", 100), ("origin", "igp")),
        legacy_ixia_name=pool_name,
    )
    return prefix_set, advertisement


def _shared_runtime_route_specs() -> tuple[_RuntimeRouteSpec, ...]:
    return (
        (
            "dg_ibgp_v4_dc_p1",
            _TC7_SHARED_IBGP_RUNTIME_POOL_V4,
            "v4",
            "11.200.0.0",
            "11.0.0.0/8",
            100,
            1,
        ),
        (
            "dg_ibgp_v6_dc_p1",
            _TC7_SHARED_IBGP_RUNTIME_POOL_V6,
            "v6",
            "2001:db8:0:c000::",
            "2001:db8::/48",
            100,
            1,
        ),
        (
            "dg_ebgp_v4",
            _TC7_SHARED_EBGP_RUNTIME_POOL_V4,
            "v4",
            _prefix_at_index(EBB_EBGP_V4_PREFIX_SET, _TC7_STATIC_EBGP_PREFIX_COUNT),
            EBB_EBGP_V4_PREFIX_SET.source.parent_network,
            100,
            1,
        ),
        (
            "dg_ebgp_v6",
            _TC7_SHARED_EBGP_RUNTIME_POOL_V6,
            "v6",
            _prefix_at_index(EBB_EBGP_V6_PREFIX_SET, _TC7_STATIC_EBGP_PREFIX_COUNT),
            EBB_EBGP_V6_PREFIX_SET.source.parent_network,
            100,
            1,
        ),
    )


def _tc7_runtime_intents(
    selected_playbooks: set[str],
) -> tuple[tuple[PrefixSet, ...], dict[str, tuple[PrefixAdvertisement, ...]]]:
    if not selected_playbooks:
        return (), {}
    prefix_sets = []
    advertisements: dict[str, list[PrefixAdvertisement]] = {}
    for (
        group_name,
        pool_name,
        afi,
        start,
        parent,
        count,
        index,
    ) in _shared_runtime_route_specs():
        prefix_set, advertisement = _runtime_route_intent(
            pool_name=pool_name,
            afi=afi,
            start_prefix=start,
            parent_network=parent,
            count=count,
            network_group_index=index,
        )
        prefix_sets.append(prefix_set)
        advertisements.setdefault(group_name, []).append(advertisement)
    return tuple(prefix_sets), {
        name: tuple(group_advertisements)
        for name, group_advertisements in advertisements.items()
    }


def _required_bound_group(bound: BoundTopology, name: str) -> BoundDeviceGroup:
    groups = [group for group in bound.device_groups if group.name == name]
    if len(groups) != 1:
        raise ValueError(
            f"EBB full-scale topology requires one {name!r} device group; "
            f"found {[group.name for group in groups]}"
        )
    return groups[0]


def _required_peer_addresses(
    groups: list[BoundDeviceGroup], expected_count: int
) -> list[str]:
    addresses = [address for group in groups for address in group.z_ips]
    if len(addresses) != expected_count or len(set(addresses)) != expected_count:
        raise ValueError(
            "EBB full-scale peer cohort cardinality mismatch: "
            f"expected {expected_count} unique peers, got {len(addresses)} total "
            f"and {len(set(addresses))} unique"
        )
    return addresses


def _tc7_group_contract() -> tuple[list[str], dict[str, int], dict[str, str]]:
    peer_groups = [
        PEERGROUP_EBGP_V4,
        PEERGROUP_EBGP_V6,
        PEERGROUP_IBGP_V4,
        PEERGROUP_IBGP_V6,
    ]
    member_counts = {
        PEERGROUP_EBGP_V4: EBGP_PEER_COUNT_V4,
        PEERGROUP_EBGP_V6: EBGP_PEER_COUNT_V6,
        PEERGROUP_IBGP_V4: IBGP_PEER_SCALE_PER_PLANE * 8,
        PEERGROUP_IBGP_V6: IBGP_PEER_SCALE_PER_PLANE * 8,
    }
    afis = {
        PEERGROUP_EBGP_V4: "ipv4",
        PEERGROUP_EBGP_V6: "ipv6",
        PEERGROUP_IBGP_V4: "ipv4",
        PEERGROUP_IBGP_V6: "ipv6",
    }
    return peer_groups, member_counts, afis


def _validate_tc7_bound_topology(bound: BoundTopology) -> None:
    _, expected_counts, _ = _tc7_group_contract()
    actual_counts: Counter[str] = Counter()
    graceful_restart_groups = []
    for group in bound.device_groups:
        peer_group = group.peer_group
        if not isinstance(peer_group, BgpPeerGroup):
            raise ValueError(f"TC7 group {group.name!r} has no resolved peer group")
        actual_counts[peer_group.name] += group.peer_count
        if peer_group.enable_graceful_restart:
            graceful_restart_groups.append(group.name)
    if len(bound.device_groups) != 18 or dict(actual_counts) != expected_counts:
        raise ValueError(
            "TC7 requires the exact two-interface 18-DG/1272-session EBB topology; "
            f"got {len(bound.device_groups)} DGs and {dict(actual_counts)}"
        )
    if graceful_restart_groups:
        raise ValueError(
            "TC7 requires graceful restart disabled on every peer group; "
            f"enabled on {graceful_restart_groups}"
        )
    device_config = bound.device_config
    if device_config is None or not device_config.update_group_enable:
        raise ValueError("TC7 requires Update Group enabled in resolved intent")
    if device_config.openr_mode is not OpenRMode.STANDALONE:
        raise ValueError("TC7 requires standalone OpenR in resolved intent")


def _tc7_health_checks() -> tuple[
    list[PointInTimeHealthCheck],
    list[PointInTimeHealthCheck],
    list[SnapshotHealthCheck],
]:
    prechecks = create_standard_prechecks(
        peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
        peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
        expected_established_sessions=_TC7_EXPECTED_SESSION_COUNT,
        cpu_baseline=12.0,
        check_ibgp_pnh=True,
        check_hardware_capacity=False,
        exclude_bgp_mon=True,
    )
    postchecks = create_standard_postchecks(
        expected_established_session_count=_TC7_EXPECTED_SESSION_COUNT,
        exclude_bgp_mon=True,
    )
    return (
        prechecks,
        postchecks,
        create_standard_snapshot_checks(
            skip_flap_check=True,
            skip_uptime_check=True,
            exclude_bgp_mon=True,
        ),
    )


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
    *,
    bound: BoundTopology,
    selected_tc7_playbooks: set[str],
) -> list[Playbook]:
    if selected_tc7_playbooks:
        return []

    device_name = physical_inventory.device_name
    ixia_interface_mimic_ebgp = physical_inventory.ixia_ports[0][0]
    ixia_interface_mimic_ibgp = physical_inventory.ixia_ports[1][0]
    ixia_interface_mimic_bgp_mon = physical_inventory.ixia_ports[2][0]
    session_count = _expected_established_session_count()
    expected_peer_identity = build_expected_peer_identity()
    local_link = _openr_owner_kv_link(physical_inventory)
    other_link = _openr_helper_kv_link(physical_inventory)

    playbooks = [
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
    return playbooks


def create_bgp_ebb_full_scale_test_config(
    physical_inventory: PhysicalInventory,
    *,
    name: str,
    playbooks_selected: list[str] | None = None,
    profile: BgpPlusPlusProfile = DEFAULT_PROFILE,
    enable_update_group: bool = True,
) -> TestConfig:
    """Build one selectable test suite on the canonical EBB full-scale topology."""
    duplicate_names = sorted(
        selected_name
        for selected_name, count in Counter(playbooks_selected or ()).items()
        if count > 1
    )
    if duplicate_names:
        raise ValueError(f"Duplicate BGP EBB playbook selections: {duplicate_names}")

    selected_tc7_playbooks = set(playbooks_selected or ()) & set(_TC7_PLAYBOOK_NAMES)
    if selected_tc7_playbooks and (
        profile != BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R
    ):
        raise ValueError("BGP Update Group 2.7 requires the WITH_OPEN_R profile")
    if selected_tc7_playbooks and not enable_update_group:
        raise ValueError("BGP Update Group 2.7 requires Update Group enabled")

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
    runtime_prefix_sets, runtime_advertisements = _tc7_runtime_intents(
        selected_tc7_playbooks
    )
    topology = ebb_full_scale_topology(
        openr_mode=openr_mode,
        include_bgpmon=not selected_tc7_playbooks,
        ebgp_graceful_restart=not selected_tc7_playbooks,
        enable_attribute_churn=enable_attribute_churn,
        ebgp_prefix_count=(
            _RUNTIME_UPDATE_EBGP_PREFIX_COUNT if enable_runtime_update else 750
        ),
        ebgp_static_prefix_count=(
            _TC7_STATIC_EBGP_PREFIX_COUNT if selected_tc7_playbooks else None
        ),
        extra_prefix_sets=runtime_prefix_sets,
        extra_advertisements=runtime_advertisements,
    )
    bound = topology.bind_to_inventory(
        physical_inventory=physical_inventory,
        port_map=(
            EBB_FULL_SCALE_PORT_MAP
            if selected_tc7_playbooks
            else EBB_FULL_SCALE_PORT_MAP_WITH_BGPMON
        ),
        parent_networks=EBB_PARENT_NETWORKS,
        peer_groups=EBB_PEER_GROUPS,
        as_numbers=EBB_AS_NUMBERS,
        device_config_override=RoutingDeviceConfig(
            openr_mode=openr_mode,
            update_group_enable=enable_update_group,
        ),
    )
    if selected_tc7_playbooks:
        _validate_tc7_bound_topology(bound)
    playbooks = _get_bgp_ebb_full_scale_playbooks(
        physical_inventory,
        profile=profile,
        bound=bound,
        selected_tc7_playbooks=selected_tc7_playbooks,
    )
    if playbooks_selected:
        playbooks_by_name = {playbook.name: playbook for playbook in playbooks}
        unknown_names = [
            playbook_name
            for playbook_name in playbooks_selected
            if playbook_name not in playbooks_by_name
            and playbook_name not in _TC7_PLAYBOOK_NAMES
        ]
        if unknown_names:
            raise ValueError(
                "Unknown BGP EBB playbook selections: "
                f"{unknown_names}; available: "
                f"{sorted(set(playbooks_by_name) | set(_TC7_PLAYBOOK_NAMES))}"
            )
        unavailable_names = [
            playbook_name
            for playbook_name in playbooks_selected
            if playbook_name not in playbooks_by_name
        ]
        if unavailable_names:
            raise NotImplementedError(
                "BGP Update Group 2.7 playbook factories are not wired yet: "
                f"{unavailable_names}"
            )
        playbooks = [playbooks_by_name[name] for name in playbooks_selected]

    compiled = bound.compile()
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
