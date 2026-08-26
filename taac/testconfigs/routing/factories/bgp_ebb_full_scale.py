# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""Factory for the EBB full-scale topology."""

import ipaddress
import typing as t
import uuid
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
    EBB_NEXT_HOPS,
    EBB_PARENT_NETWORKS,
    EBB_PEER_GROUPS,
    EbbNextHopScheme,
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
from taac.playbooks.routing.factories.qual_bgp_update_group.tc7_cases.link_flap_recovery import (
    create_bgp_ug_link_flap_recovery_playbook,
)
from taac.playbooks.routing.factories.qual_bgp_update_group.tc7_cases.sustained_link_flap import (
    create_bgp_ug_sustained_link_flap_playbook,
)
from taac.testconfigs.routing.factories.bgp_ug_2_7_suite import (
    build_bgp_ug_2_7_playbook,
)
from taac.testconfigs.routing.util.bgp_ebb_constants import (
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
    BgpMonScope,
    create_standard_postchecks,
    create_standard_prechecks,
    create_standard_snapshot_checks,
)
from taac.testconfigs.routing.util.bgp_ebb_setup_tasks import (
    build_expected_peer_identity,
)
from taac.utils.characterization import (
    DISABLED,
    OBSERVE_ONLY_ON_DEVICE,
)
from taac.test_as_a_config.types import (
    Playbook,
    PointInTimeHealthCheck,
    SnapshotHealthCheck,
    TestConfig,
)


_LONGEVITY_DURATION_SECONDS = 14400
_NEXTHOP_GROUP_THRESHOLD = 100
_DEFAULT_EBGP_PREFIX_COUNT = 750
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
_TC7_LINK_FLAP_NAME = _TC7_PLAYBOOK_NAMES[0]
_TC7_SHARED_IBGP_RUNTIME_POOL_V4 = "PREFIX_POOL_IBGP_IPV4_UG_2_7_RUNTIME"
_TC7_SHARED_IBGP_RUNTIME_POOL_V6 = "PREFIX_POOL_IBGP_IPV6_UG_2_7_RUNTIME"
_TC7_SHARED_EBGP_RUNTIME_POOL_V4 = "PREFIX_POOL_IPV4_EBGP_UG_2_7_RUNTIME"
_TC7_SHARED_EBGP_RUNTIME_POOL_V6 = "PREFIX_POOL_IPV6_EBGP_UG_2_7_RUNTIME"
_RuntimeRouteSpec = tuple[str, str, str, str, str, int, int]
_UG_2_7_2_IBGP_POOLS = (
    rf"^{_TC7_SHARED_IBGP_RUNTIME_POOL_V4}$",
    rf"^{_TC7_SHARED_IBGP_RUNTIME_POOL_V6}$",
)
_UG_2_7_2_EBGP_POOLS = (
    rf"^{_TC7_SHARED_EBGP_RUNTIME_POOL_V4}$",
    rf"^{_TC7_SHARED_EBGP_RUNTIME_POOL_V6}$",
)


class _Ug272PeerCohorts(t.NamedTuple):
    ibgp_v4: tuple[str, ...]
    ibgp_v6: tuple[str, ...]
    ebgp_v4: tuple[str, ...]
    ebgp_v6: tuple[str, ...]


class _Ug272PortTrack(t.TypedDict):
    role: str
    interface: str | None
    target_peer_subnets: list[str]


class _Ug272RouteLeg(t.TypedDict):
    source_prefix_pool_regexes: list[str]
    receiver_parent_prefixes: list[str]
    expected_receiver_count: int
    expected_route_delta: int


class _Ug272HeartbeatScenario(t.TypedDict, total=False):
    down_roles: list[str]
    verification_mode: str
    legs: list[_Ug272RouteLeg]
    structural_reason: str


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
        bgp_mon=BgpMonScope(exclude=True),
    )
    postchecks = create_standard_postchecks(
        expected_established_session_count=_TC7_EXPECTED_SESSION_COUNT,
        bgp_mon=BgpMonScope(exclude=True),
    )
    return (
        prechecks,
        postchecks,
        create_standard_snapshot_checks(
            skip_flap_check=True,
            skip_uptime_check=True,
            bgp_mon=BgpMonScope(exclude=True),
        ),
    )


def _bound_groups(
    bound: BoundTopology, names: t.Iterable[str]
) -> list[BoundDeviceGroup]:
    return [_required_bound_group(bound, name) for name in names]


def _ibgp_group_names(afi: str) -> list[str]:
    return [
        f"dg_ibgp_{afi}_{fabric}_p{plane}"
        for fabric in ("dc", "mp")
        for plane in range(1, 5)
    ]


def _host_prefixes(addresses: t.Iterable[str]) -> list[str]:
    return [f"{address}/{'128' if ':' in address else '32'}" for address in addresses]


def _ug_2_7_2_peer_cohorts(bound: BoundTopology) -> _Ug272PeerCohorts:
    def peers(group_names: list[str], expected_count: int) -> tuple[str, ...]:
        return tuple(
            sorted(
                _required_peer_addresses(
                    _bound_groups(bound, group_names), expected_count
                )
            )
        )

    return _Ug272PeerCohorts(
        ibgp_v4=peers(_ibgp_group_names("v4"), 496),
        ibgp_v6=peers(_ibgp_group_names("v6"), 496),
        ebgp_v4=peers(["dg_ebgp_v4"], 140),
        ebgp_v6=peers(["dg_ebgp_v6"], 140),
    )


def _ug_2_7_2_port_tracks(
    bound: BoundTopology, peers: _Ug272PeerCohorts
) -> list[_Ug272PortTrack]:
    tracks: list[_Ug272PortTrack] = [
        {
            "role": "ebgp",
            "interface": _required_bound_group(bound, "dg_ebgp_v6").a_interface,
            "target_peer_subnets": _host_prefixes([*peers.ebgp_v4, *peers.ebgp_v6]),
        },
        {
            "role": "ibgp",
            "interface": _required_bound_group(bound, "dg_ibgp_v6_dc_p1").a_interface,
            "target_peer_subnets": _host_prefixes([*peers.ibgp_v4, *peers.ibgp_v6]),
        },
    ]
    if any(not track["interface"] for track in tracks):
        raise ValueError("2.7.2 requires both resolved BAG012 interfaces")
    return tracks


def _ug_2_7_2_route_leg(
    source_pools: t.Sequence[str],
    receivers: t.Iterable[str],
    receiver_count: int,
    route_delta: int,
) -> _Ug272RouteLeg:
    return {
        "source_prefix_pool_regexes": list(source_pools),
        "receiver_parent_prefixes": _host_prefixes(receivers),
        "expected_receiver_count": receiver_count,
        "expected_route_delta": route_delta,
    }


def _ug_2_7_2_route_scenarios(
    peers: _Ug272PeerCohorts,
) -> list[_Ug272HeartbeatScenario]:
    return [
        {
            "down_roles": [],
            "verification_mode": "route",
            "legs": [
                _ug_2_7_2_route_leg(
                    [_UG_2_7_2_EBGP_POOLS[0]],
                    peers.ibgp_v4,
                    496,
                    1,
                ),
                _ug_2_7_2_route_leg(
                    [_UG_2_7_2_EBGP_POOLS[1]],
                    peers.ibgp_v6,
                    496,
                    1,
                ),
                _ug_2_7_2_route_leg(
                    [_UG_2_7_2_IBGP_POOLS[0]],
                    peers.ebgp_v4,
                    140,
                    1,
                ),
                _ug_2_7_2_route_leg(
                    [_UG_2_7_2_IBGP_POOLS[1]],
                    peers.ebgp_v6,
                    140,
                    1,
                ),
            ],
        },
    ]


def _ug_2_7_2_structural_scenario(
    down_roles: list[str], reason: str
) -> _Ug272HeartbeatScenario:
    return {
        "down_roles": down_roles,
        "verification_mode": "structural",
        "structural_reason": reason,
    }


def _ug_2_7_2_heartbeat_scenarios(
    peers: _Ug272PeerCohorts,
) -> list[_Ug272HeartbeatScenario]:
    structural = _ug_2_7_2_structural_scenario
    return [
        *_ug_2_7_2_route_scenarios(peers),
        structural(
            ["ebgp"],
            "only-iBGP-active:iBGP-split-horizon-has-no-independent-pair",
        ),
        structural(
            ["ibgp"],
            "only-eBGP-active:same-AS-loop-prevention-has-no-independent-pair",
        ),
        structural(
            ["ebgp", "ibgp"],
            "all-links-down:no-active-source-or-receiver",
        ),
    ]


def _ug_2_7_2_playbook(
    physical_inventory: PhysicalInventory,
    bound: BoundTopology,
) -> Playbook:
    peers = _ug_2_7_2_peer_cohorts(bound)
    port_tracks = _ug_2_7_2_port_tracks(bound, peers)
    heartbeats = _ug_2_7_2_heartbeat_scenarios(peers)
    peer_groups, member_counts, afis = _tc7_group_contract()
    prechecks, postchecks, snapshot_checks = _tc7_health_checks()
    return create_bgp_ug_sustained_link_flap_playbook(
        device_name=physical_inventory.device_name,
        port_tracks=port_tracks,
        heartbeat_scenarios=heartbeats,
        state_key=str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"{physical_inventory.device_name}:update_group_sustained_link_flap",
            )
        ),
        peer_group_substrings=peer_groups,
        expected_member_counts=member_counts,
        expected_afi_by_substring=afis,
        prechecks=prechecks,
        postchecks=postchecks,
        snapshot_checks=snapshot_checks,
    )


def _ug_2_7_1_playbook(
    physical_inventory: PhysicalInventory,
    bound: BoundTopology,
) -> Playbook:
    ebgp_v6_peers = _required_peer_addresses(
        [_required_bound_group(bound, "dg_ebgp_v6")],
        EBGP_PEER_COUNT_V6,
    )
    ebgp_v4_peers = _required_peer_addresses(
        [_required_bound_group(bound, "dg_ebgp_v4")],
        EBGP_PEER_COUNT_V4,
    )
    ebgp_interface = _required_bound_group(bound, "dg_ebgp_v6").a_interface
    if ebgp_interface is None:
        raise ValueError("2.7.1 requires a resolved eBGP DUT interface")
    peer_groups, member_counts, afis = _tc7_group_contract()
    prechecks, postchecks, snapshot_checks = _tc7_health_checks()
    return create_bgp_ug_link_flap_recovery_playbook(
        device_name=physical_inventory.device_name,
        interface=ebgp_interface,
        target_peer_subnets=[
            *(f"{address}/32" for address in ebgp_v4_peers),
            *(f"{address}/128" for address in ebgp_v6_peers),
        ],
        route_pool_regexes=[rf"{_TC7_SHARED_IBGP_RUNTIME_POOL_V6}$"],
        recovered_ebgp_peer_addrs=ebgp_v6_peers,
        state_key=str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"{physical_inventory.device_name}:{_TC7_LINK_FLAP_NAME}",
            )
        ),
        peer_group_substrings=peer_groups,
        expected_member_counts=member_counts,
        expected_afi_by_substring=afis,
        prechecks=prechecks,
        postchecks=postchecks,
        snapshot_checks=snapshot_checks,
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
    return (
        EBGP_PEER_COUNT_V6
        + EBGP_PEER_COUNT_V4
        + IBGP_PEER_SCALE_PER_PLANE * 4
        + IBGP_PEER_SCALE_PER_PLANE * 4
        + IBGP_PEER_SCALE_PER_PLANE * 4
        + IBGP_PEER_SCALE_PER_PLANE * 4
    )


def _get_bgp_ebb_full_scale_playbooks(
    physical_inventory: PhysicalInventory,
    profile: BgpPlusPlusProfile,
    *,
    bound: BoundTopology,
    ebgp_prefix_count: int,
    selected_tc7_playbooks: set[str],
    port_map: t.Mapping[str, int] | None = None,
    enable_update_group: bool = True,
    multipath_test_duration_seconds: int = 1800,
    multipath_oscillation_interval_seconds: int = 280,
    multipath_cycle_count: int | None = None,
    route_storm_cycles: int = 60,
    route_storm_quiet_window_seconds: int = 120,
    route_storm_bounded_validation: bool = False,
) -> list[Playbook]:
    if selected_tc7_playbooks:
        playbooks = []
        if _TC7_LINK_FLAP_NAME in selected_tc7_playbooks:
            playbooks.append(_ug_2_7_1_playbook(physical_inventory, bound))
        if "bgp_ug_bgp_daemon_restart" in selected_tc7_playbooks:
            playbooks.append(
                build_bgp_ug_2_7_playbook(
                    "bgp_ug_bgp_daemon_restart", physical_inventory, bound
                )
            )
        if "bgp_ug_fibagent_restart" in selected_tc7_playbooks:
            playbooks.append(
                build_bgp_ug_2_7_playbook(
                    "bgp_ug_fibagent_restart", physical_inventory, bound
                )
            )
        if "update_group_sustained_link_flap" in selected_tc7_playbooks:
            playbooks.append(_ug_2_7_2_playbook(physical_inventory, bound))
        if "bgp_ug_bgp_peer_flapping" in selected_tc7_playbooks:
            playbooks.append(
                build_bgp_ug_2_7_playbook(
                    "bgp_ug_bgp_peer_flapping", physical_inventory, bound
                )
            )
        if "bgp_ug_cold_start" in selected_tc7_playbooks:
            playbooks.append(
                build_bgp_ug_2_7_playbook(
                    "bgp_ug_cold_start", physical_inventory, bound
                )
            )
        return playbooks

    device_name = physical_inventory.device_name
    resolved_port_map = EBB_FULL_SCALE_PORT_MAP if port_map is None else port_map
    missing_port_roles = sorted({"uplink", "ibgp"} - resolved_port_map.keys())
    if missing_port_roles:
        raise ValueError(
            "BGP EBB full-scale port_map is missing required roles: "
            f"{missing_port_roles}"
        )
    port_count = len(physical_inventory.ixia_ports)
    invalid_port_roles = {
        role: resolved_port_map[role]
        for role in ("uplink", "ibgp")
        if not 0 <= resolved_port_map[role] < port_count
    }
    if invalid_port_roles:
        raise ValueError(
            "BGP EBB full-scale port_map has out-of-range indices for "
            f"{port_count} IXIA ports: {invalid_port_roles}"
        )
    ixia_interface_mimic_ebgp = physical_inventory.ixia_ports[
        resolved_port_map["uplink"]
    ][0]
    ixia_interface_mimic_ibgp = physical_inventory.ixia_ports[
        resolved_port_map["ibgp"]
    ][0]
    session_count = _expected_established_session_count()
    # Derive from the bound topology rather than the module constants, so the
    # checks describe the chassis the run is actually wired to. A config using
    # for_secondary_ixia() peers on the secondary chassis' subnets, and the
    # ixia11 defaults would mark every one of those sessions unexpected.
    bound_parent_networks = dict(bound.parent_networks)
    bound_bgp_mon_network = bound_parent_networks.get(
        "bgpmon_v6", IXIA_BGP_MON_IC_PARENT_NETWORK
    )
    bgp_mon_parent_prefix = f"{bound_bgp_mon_network}::/80"
    expected_peer_identity = build_expected_peer_identity(bound_parent_networks)
    local_link = _openr_owner_kv_link(physical_inventory)
    other_link = _openr_helper_kv_link(physical_inventory)

    playbooks = [
        get_bgp_ebb_attribute_churn_playbook(
            device_name=device_name,
            peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
            peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
            total_session_count=session_count,
            profile=profile,
            characterization=OBSERVE_ONLY_ON_DEVICE,
        ),
        get_bgp_ebb_route_storm_playbook(
            device_name=device_name,
            peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
            peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
            total_session_count=session_count,
            ixia_interface_mimic_ibgp=ixia_interface_mimic_ibgp,
            observer_peer_parent_prefix=bgp_mon_parent_prefix,
            profile=profile,
            cycles=route_storm_cycles,
            quiet_window_seconds=route_storm_quiet_window_seconds,
            bounded_validation=route_storm_bounded_validation,
            characterization=OBSERVE_ONLY_ON_DEVICE,
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
            test_duration_seconds=multipath_test_duration_seconds,
            oscillation_interval_seconds=multipath_oscillation_interval_seconds,
            cycle_count=multipath_cycle_count,
            characterization=OBSERVE_ONLY_ON_DEVICE,
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
            characterization=OBSERVE_ONLY_ON_DEVICE,
        ),
        get_bgp_ebb_fauu_drain_undrain_playbook(
            device_name=device_name,
            peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
            peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
            expected_established_sessions=session_count,
            profile=profile,
            tcp_dump_capture_interface_ebgp=ixia_interface_mimic_ebgp,
            tcp_dump_capture_interface_ibgp=ixia_interface_mimic_ibgp,
            bgp_mon_parent_network=bound_bgp_mon_network,
        ),
        get_bgp_ebb_plane_drain_undrain_playbook(
            device_name=device_name,
            peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
            peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
            expected_established_sessions=session_count,
            profile=profile,
            tcp_dump_capture_interface_ebgp=ixia_interface_mimic_ebgp,
            tcp_dump_capture_interface_ibgp=ixia_interface_mimic_ibgp,
            bgp_mon_parent_network=bound_bgp_mon_network,
        ),
        get_bgp_ebb_longevity_playbook(
            device_name=device_name,
            duration=_LONGEVITY_DURATION_SECONDS,
            characterization=OBSERVE_ONLY_ON_DEVICE,
        ),
        get_bgp_ebb_daemon_restart_playbook(
            device_name=device_name,
            peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
            peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
            expected_established_sessions=session_count,
            profile=profile,
            expected_peer_identity=expected_peer_identity,
            parent_prefixes_to_ignore=[bgp_mon_parent_prefix],
            # Deliberately unmeasured. Restarting bgpcpp replaces the PID
            # mid-bracket, and both collectors resolve the PID once at START:
            # CPU then reads a dead /proc entry and silently drops every
            # sample, and RSS fails outright because `restarted` invalidates a
            # steady-state comparison by construction. Beyond the mechanism,
            # the numbers would not be worth having: this is a lifecycle
            # recovery test, not a sustained-load test, so a CPU percentile or
            # an RSS delta measured across a process boundary describes two
            # different processes rather than one workload.
            characterization=DISABLED,
        ),
        get_bgp_ebb_cold_start_playbook(
            device_name=device_name,
            peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
            peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
            expected_established_sessions=session_count,
            profile=profile,
            expected_peer_identity=expected_peer_identity,
            parent_prefixes_to_ignore=[bgp_mon_parent_prefix],
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
            parent_prefixes_to_ignore=[bgp_mon_parent_prefix],
        ),
        get_bgp_ebb_ebgp_route_oscillation_playbook(
            device_name=device_name,
            peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
            peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
            expected_established_sessions=session_count,
            profile=profile,
            parent_prefixes_to_ignore=[bgp_mon_parent_prefix],
            characterization=OBSERVE_ONLY_ON_DEVICE,
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
            parent_prefixes_to_ignore=[bgp_mon_parent_prefix],
        ),
        get_bgp_ebb_ibgp_route_oscillation_playbook(
            device_name=device_name,
            peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
            peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
            expected_established_sessions=session_count,
            profile=profile,
            expected_peer_identity=expected_peer_identity,
            parent_prefixes_to_ignore=[bgp_mon_parent_prefix],
            characterization=OBSERVE_ONLY_ON_DEVICE,
        ),
        get_bgp_ebb_igp_unresolvable_pnh_playbook(
            device_name=device_name,
            peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
            peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
            local_link=local_link,
            other_link=other_link,
            expected_in_scope_sessions=session_count,
            profile=profile,
            expected_peer_identity=expected_peer_identity,
            bgp_mon_parent_network=bound_bgp_mon_network,
            characterization=OBSERVE_ONLY_ON_DEVICE,
        ),
        get_bgp_ebb_nexthop_group_count_threshold_playbook(
            device_name=device_name,
            expected_established_sessions=session_count,
            route_count_expected=ebgp_prefix_count,
            nexthop_group_threshold=_NEXTHOP_GROUP_THRESHOLD,
            enable_update_group=enable_update_group,
            bgp_mon_parent_network=bound_bgp_mon_network,
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
    bgpcpp_logging_config_override: str | None = None,
    parent_networks: dict[str, str] | None = None,
    next_hops: EbbNextHopScheme = EBB_NEXT_HOPS,
    port_map: t.Mapping[str, int] | None = None,
    multipath_test_duration_seconds: int = 1800,
    multipath_oscillation_interval_seconds: int = 280,
    multipath_cycle_count: int | None = None,
    route_storm_cycles: int = 60,
    route_storm_quiet_window_seconds: int = 120,
    route_storm_bounded_validation: bool = False,
) -> TestConfig:
    """Build one selectable test suite on the canonical EBB full-scale topology.

    Args:
        physical_inventory: DUT and IXIA port bindings for the run.
        name: Test config name, used to resolve it from the catalog.
        playbooks_selected: Subset of the suite's playbooks to run; all if None.
        profile: BGP++ profile, which also decides the Open/R mode.
        enable_update_group: Whether to enable BGP Update Group on the device.
        bgpcpp_logging_config_override: Exact BGP++ logging configuration to
            apply to the launcher. Pass ``None`` to preserve the launcher
            without a logging override.
        parent_networks: IXIA-side parent networks, defaulting to
            ``EBB_PARENT_NETWORKS`` (ixia11). Pass ``EBB_PARENT_NETWORKS_IXIA03``
            when the inventory has been swapped with
            ``PhysicalInventory.for_secondary_ixia()``: that helper moves the
            ports but not the addressing, and the two have to agree or the
            emulated peers land on subnets the DUT has no address in.
        next_hops: Chassis scheme for the next hops the emulated peers
            advertise. Built during topology construction, before binding, so
            it cannot be derived from ``parent_networks``; pass
            ``EBB_NEXT_HOPS_IXIA03`` alongside
            ``EBB_PARENT_NETWORKS_IXIA03``. Mismatched pairs are rejected,
            because peers on one chassis' subnets advertising next hops on
            another's produce routes the DUT cannot resolve.
        port_map: Optional mapping from logical IXIA roles to ordered physical
            inventory entries. Use this for a testbed-specific role assignment.
    """
    resolved_parent_networks = parent_networks or EBB_PARENT_NETWORKS
    if resolved_parent_networks.get("ebgp_v4") != next_hops.ebgp_v4_network:
        raise ValueError(
            "parent_networks and next_hops describe different chassis: "
            f"eBGP v4 parent {resolved_parent_networks.get('ebgp_v4')!r} vs "
            f"next-hop base {next_hops.ebgp_v4_network!r}"
        )
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
    include_auxiliary_observers = (
        not selected_tc7_playbooks and len(physical_inventory.ixia_ports) > 2
    )
    default_port_map = (
        EBB_FULL_SCALE_PORT_MAP_WITH_BGPMON
        if include_auxiliary_observers
        else EBB_FULL_SCALE_PORT_MAP
    )
    resolved_port_map = dict(default_port_map if port_map is None else port_map)
    ebgp_prefix_count = (
        _RUNTIME_UPDATE_EBGP_PREFIX_COUNT
        if enable_runtime_update
        else _DEFAULT_EBGP_PREFIX_COUNT
    )
    topology = ebb_full_scale_topology(
        next_hops=next_hops,
        openr_mode=openr_mode,
        include_bgpmon=include_auxiliary_observers,
        ebgp_graceful_restart=not selected_tc7_playbooks,
        enable_attribute_churn=enable_attribute_churn,
        ebgp_prefix_count=ebgp_prefix_count,
        ebgp_static_prefix_count=(
            _TC7_STATIC_EBGP_PREFIX_COUNT if selected_tc7_playbooks else None
        ),
        extra_prefix_sets=runtime_prefix_sets,
        extra_advertisements=runtime_advertisements,
    )
    bound = topology.bind_to_inventory(
        physical_inventory=physical_inventory,
        port_map=resolved_port_map,
        parent_networks=resolved_parent_networks,
        peer_groups=EBB_PEER_GROUPS,
        as_numbers=EBB_AS_NUMBERS,
        device_config_override=RoutingDeviceConfig(
            openr_mode=openr_mode,
            update_group_enable=enable_update_group,
            bgpcpp_logging_config_override=bgpcpp_logging_config_override,
        ),
    )
    if selected_tc7_playbooks:
        _validate_tc7_bound_topology(bound)
    playbooks = _get_bgp_ebb_full_scale_playbooks(
        physical_inventory,
        profile=profile,
        bound=bound,
        ebgp_prefix_count=ebgp_prefix_count,
        selected_tc7_playbooks=selected_tc7_playbooks,
        port_map=resolved_port_map,
        enable_update_group=enable_update_group,
        multipath_test_duration_seconds=multipath_test_duration_seconds,
        multipath_oscillation_interval_seconds=(multipath_oscillation_interval_seconds),
        multipath_cycle_count=multipath_cycle_count,
        route_storm_cycles=route_storm_cycles,
        route_storm_quiet_window_seconds=route_storm_quiet_window_seconds,
        route_storm_bounded_validation=route_storm_bounded_validation,
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
