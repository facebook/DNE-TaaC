# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""Spec 2.4 — New Peer Joining a Busy Group. UG qualification testconfig factory.

Byte-wise-identical move from ``testconfigs/routing/factories/bgp_update_group.py``
(pre-Wave-6). See ``playbooks/routing/factories/qual_bgp_update_group/tc4_new_peer_join.py``
for the 3 sub-spec playbook factories (2.4.1 / 2.4.2 / 2.4.3).
"""

import typing as t
from dataclasses import dataclass

from ixia.ixia import types as ixia_types
from taac.abstractions.topologies.ug_new_peer_join import (
    UG_NEW_PEER_JOIN,
    UG_NEW_PEER_JOIN_AS_NUMBERS,
    UG_NEW_PEER_JOIN_PARENT_NETWORKS,
    UG_NEW_PEER_JOIN_PEER_GROUPS,
    UG_NEW_PEER_JOIN_PORT_MAP,
)
from taac.abstractions.topology import (
    BgpPeerGroup,
    BgpPolicy,
    BoundDeviceGroup,
    BoundTopology,
)
from taac.constants import BgpPlusPlusProfile
from taac.playbooks.routing.factories.qual_bgp_update_group.tc4_new_peer_join import (
    create_bgp_ug_new_peer_join_attribute_change_playbook,
    create_bgp_ug_new_peer_join_full_sync_resilience_playbook,
    create_bgp_ug_new_peer_join_routes_withdrawn_playbook,
)
from taac.steps.step_definitions import (
    create_ixia_api_step,
    create_longevity_step,
    create_start_stop_bgp_peers_step,
)
from taac.testconfigs.routing.testbed import Testbed
from taac.testconfigs.routing.util.bgp_ebb_constants import (
    EBGP_REMOTE_AS,
    IBGP_REMOTE_AS,
    IXIA_EBGP_IC_PARENT_NETWORK_V6,
    IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE1,
)
from taac.testconfigs.routing.util.bgp_ebb_setup_tasks import (
    get_update_packing_setup_tasks,
)
from taac.test_as_a_config import types as taac_types


# =============================================================================
# BGP UG new-peer-join (spec 2.4.1 + 2.4.2 + 2.4.3) — bag012 topology
# =============================================================================
#
# 21-eBGP + 4-iBGP topology on bag012.ash6 (moved from
# testconfigs/routing/ebb/bag012_ash6_test_config.py).
#
# Side A receivers on eBGP port (EB-FA-V6 UG under test):
#   CTRL × 4    — always UP
#   HELD × 1    — admin-DOWN at baseline; brought UP mid-test = the SUT
#   DISP × 16   — always UP; killed mid-sync in 2.4.1
#
# Side B senders on iBGP port (EB-EB-V6):
#   KEEP_INITIAL   — 300 routes with initial community; UP at baseline
#   KEEP_MUTATED   — 300 routes with mutated community; DG-disabled baseline
#                    (2.4.3 trigger flips the pair to swap community on wire)
#   VAR1           — 200 routes; DG-enabled at baseline but sessions DOWN
#   VAR2           — 50 routes; DG-enabled at baseline but sessions DOWN

_UG_PEER_GROUP_SUBSTRING = "EB-FA-V6"

# Community values required to pass DUT's policy chain.
_UG_IBGP_SENDER_COMMUNITIES = [
    "65060:10012",
    "65140:65529",
    "65520:503",
    "65529:11610",
    "65529:39744",
    "65530:50300",
    "65530:50320",
    "65530:50800",
]
_UG_INITIAL_COMMUNITY = "65529:39744"  # 2.4.3 starting "marker" community
_UG_MUTATED_COMMUNITY = "65531:50200"
_UG_BASE_SENDER_COMMUNITIES = _UG_IBGP_SENDER_COMMUNITIES

# Per-DG counts (multiplier).
_UG_CTRL_MULTIPLIER = 4
_UG_DISP_MULTIPLIER = 16
_UG_DISP_KILL_COUNT = 16  # kill all 16 in 2.4.1
_UG_TOTAL_EBGP_PEERS = _UG_CTRL_MULTIPLIER + 1 + _UG_DISP_MULTIPLIER  # 21
_UG_TOTAL_IBGP_PEERS = 1 + 1 + 1 + 1  # KEEP_INITIAL + KEEP_MUTATED + VAR1 + VAR2

# Pool sizes.
_UG_KEEP_ROUTE_COUNT = 300
_UG_VAR1_ROUTE_COUNT = 200
_UG_VAR2_ROUTE_COUNT = 50

# Tag names = IXIA peer-object regex handles used by step_definitions.
_UG_DG_A_CTRL_TAG = "BGP_PEER_IPV6_EBGP_UG_CTRL"
_UG_DG_A_HELD_TAG = "BGP_PEER_IPV6_EBGP_UG_HELD"
_UG_DG_A_DISP_TAG = "BGP_PEER_IPV6_EBGP_UG_DISP"
_UG_DG_B_KEEP_TAG = "BGP_PEER_IPV6_IBGP_UG_B_KEEP"  # = INITIAL (legacy name)
_UG_DG_B_KEEP_MUTATED_TAG = "BGP_PEER_IPV6_IBGP_UG_B_KEEP_MUTATED"
_UG_DG_B_VAR1_TAG = "BGP_PEER_IPV6_IBGP_UG_B_VAR1"
_UG_DG_B_VAR2_TAG = "BGP_PEER_IPV6_IBGP_UG_B_VAR2"


# IXIA-side peer addresses derived from `_generate_ixia_v6_peer_entries_for_bgpcpp`
# (start_offset=0x10, stride=2). For each AF: DUT-local at offset i*2+0x10
# (::10, ::12, ...); IXIA-side peer at i*2+0x11 (::11, ::13, ...).
def _ug_ibgp_peer_addr(idx: int) -> str:
    """IXIA-side peer address for the idx-th iBGP peer (0-based)."""
    return f"{IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE1}::{0x11 + 2 * idx:x}"


def _ug_ibgp_gateway_addr(idx: int) -> str:
    """DUT-side iBGP local address (= IXIA-side gateway) for the idx-th peer."""
    return f"{IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE1}::{0x10 + 2 * idx:x}"


def _ug_ebgp_peer_addr(idx: int) -> str:
    """IXIA-side peer address for the idx-th eBGP peer (sender)."""
    return f"{IXIA_EBGP_IC_PARENT_NETWORK_V6}::{0x11 + 2 * idx:x}"


def _ug_ebgp_gateway_addr(idx: int) -> str:
    """DUT-side eBGP local address (= IXIA-side gateway) for the idx-th peer."""
    return f"{IXIA_EBGP_IC_PARENT_NETWORK_V6}::{0x10 + 2 * idx:x}"


# Allocate peer index ranges to roles within their respective AF/protocol.
_UG_EBGP_CTRL_START_IDX = 0  # 0..3
_UG_EBGP_HELD_IDX = 4
_UG_EBGP_DISP_START_IDX = 5  # 5..20
_UG_IBGP_B_KEEP_IDX = 0
_UG_IBGP_B_KEEP_MUTATED_IDX = 1
_UG_IBGP_B_VAR1_IDX = 2
_UG_IBGP_B_VAR2_IDX = 3

# Mutated 8-community list: base list with the marker position swapped.
_UG_MUTATED_SENDER_COMMUNITIES = [
    _UG_MUTATED_COMMUNITY if c == _UG_INITIAL_COMMUNITY else c
    for c in _UG_BASE_SENDER_COMMUNITIES
]

# Resolved peer-IP lists used by playbook factories.
_UG_CTRL_PEER_ADDRS = [
    _ug_ebgp_peer_addr(_UG_EBGP_CTRL_START_IDX + i) for i in range(_UG_CTRL_MULTIPLIER)
]
_UG_HELD_PEER_ADDR = _ug_ebgp_peer_addr(_UG_EBGP_HELD_IDX)
_UG_DISP_PEER_ADDRS = [
    _ug_ebgp_peer_addr(_UG_EBGP_DISP_START_IDX + i) for i in range(_UG_DISP_MULTIPLIER)
]
_UG_B_KEEP_PEER_ADDR = _ug_ibgp_peer_addr(_UG_IBGP_B_KEEP_IDX)
_UG_B_KEEP_MUTATED_PEER_ADDR = _ug_ibgp_peer_addr(_UG_IBGP_B_KEEP_MUTATED_IDX)
_UG_B_VAR1_PEER_ADDR = _ug_ibgp_peer_addr(_UG_IBGP_B_VAR1_IDX)
_UG_B_VAR2_PEER_ADDR = _ug_ibgp_peer_addr(_UG_IBGP_B_VAR2_IDX)


@dataclass(frozen=True)
class _UgNewPeerJoinSelectors:
    control_peer_addrs: list[str]
    held_back_peer_addr: str
    held_back_peer_regex: str
    disp_peer_addrs: list[str]
    disp_peer_regex: str
    b_keep_peer_addr: str
    b_keep_peer_regex: str
    b_keep_route_count: int
    b_keep_mutated_peer_addr: str
    b_keep_mutated_peer_regex: str
    b_var1_peer_addr: str
    b_var1_peer_regex: str
    b_var1_route_count: int
    b_var2_peer_addr: str
    b_var2_peer_regex: str
    b_var2_route_count: int
    initial_community: str
    mutated_community: str
    ug_peer_group_substring: str


def _legacy_selectors() -> _UgNewPeerJoinSelectors:
    return _UgNewPeerJoinSelectors(
        control_peer_addrs=_UG_CTRL_PEER_ADDRS,
        held_back_peer_addr=_UG_HELD_PEER_ADDR,
        held_back_peer_regex=_UG_DG_A_HELD_TAG,
        disp_peer_addrs=_UG_DISP_PEER_ADDRS,
        disp_peer_regex=_UG_DG_A_DISP_TAG,
        b_keep_peer_addr=_UG_B_KEEP_PEER_ADDR,
        b_keep_peer_regex=_UG_DG_B_KEEP_TAG,
        b_keep_route_count=_UG_KEEP_ROUTE_COUNT,
        b_keep_mutated_peer_addr=_UG_B_KEEP_MUTATED_PEER_ADDR,
        b_keep_mutated_peer_regex=_UG_DG_B_KEEP_MUTATED_TAG,
        b_var1_peer_addr=_UG_B_VAR1_PEER_ADDR,
        b_var1_peer_regex=_UG_DG_B_VAR1_TAG,
        b_var1_route_count=_UG_VAR1_ROUTE_COUNT,
        b_var2_peer_addr=_UG_B_VAR2_PEER_ADDR,
        b_var2_peer_regex=_UG_DG_B_VAR2_TAG,
        b_var2_route_count=_UG_VAR2_ROUTE_COUNT,
        initial_community=_UG_INITIAL_COMMUNITY,
        mutated_community=_UG_MUTATED_COMMUNITY,
        ug_peer_group_substring=_UG_PEER_GROUP_SUBSTRING,
    )


def _required_bound_group(
    bound: BoundTopology,
    role: str,
) -> BoundDeviceGroup:
    matches = [group for group in bound.device_groups if group.role == role]
    if len(matches) != 1:
        raise ValueError(
            f"UG new-peer-join requires exactly one {role!r} device group; "
            f"found {[group.name for group in matches]}"
        )
    return matches[0]


def _required_peer_addresses(group: BoundDeviceGroup) -> list[str]:
    peer_addresses = list(group.z_ips)
    if len(peer_addresses) != group.peer_count:
        raise ValueError(
            f"UG new-peer-join device group {group.name!r} requires "
            f"{group.peer_count} resolved IXIA peer addresses; got {peer_addresses}"
        )
    return peer_addresses


def _required_ixia_tag(group: BoundDeviceGroup) -> str:
    tag = group.legacy_ixia_tag_name
    if not tag:
        raise ValueError(
            f"UG new-peer-join device group {group.name!r} requires an IXIA tag"
        )
    return tag


def _required_route_intent(
    group: BoundDeviceGroup,
) -> tuple[int, tuple[str, ...]]:
    if len(group.spec.prefix_pools) != 1:
        raise ValueError(
            f"UG new-peer-join sender {group.name!r} requires one prefix pool"
        )
    prefix_pool = group.spec.prefix_pools[0]
    policy = prefix_pool.policy
    if not isinstance(policy, BgpPolicy):
        raise ValueError(
            f"UG new-peer-join prefix pool {prefix_pool.name!r} requires a BGP policy"
        )
    return prefix_pool.route_count, policy.communities


def _selectors_from_bound(bound: BoundTopology) -> _UgNewPeerJoinSelectors:
    ctrl = _required_bound_group(bound, "ebgp_ug_ctrl")
    held = _required_bound_group(bound, "ebgp_ug_held")
    disp = _required_bound_group(bound, "ebgp_ug_disp")
    keep = _required_bound_group(bound, "ibgp_ug_keep_initial")
    keep_mutated = _required_bound_group(bound, "ibgp_ug_keep_mutated")
    var1 = _required_bound_group(bound, "ibgp_ug_var1")
    var2 = _required_bound_group(bound, "ibgp_ug_var2")

    keep_route_count, keep_communities = _required_route_intent(keep)
    mutated_route_count, mutated_communities = _required_route_intent(keep_mutated)
    if keep_route_count != mutated_route_count:
        raise ValueError(
            "UG new-peer-join initial and mutated sender route counts must match"
        )
    if len(keep_communities) != len(mutated_communities):
        raise ValueError(
            "UG new-peer-join sender policies must have matching community counts"
        )
    community_changes = [
        (initial, mutated)
        for initial, mutated in zip(keep_communities, mutated_communities)
        if initial != mutated
    ]
    if len(community_changes) != 1:
        raise ValueError(
            "UG new-peer-join sender policies must contain one community mutation"
        )
    initial_community, mutated_community = community_changes[0]

    peer_group = ctrl.peer_group
    if not isinstance(peer_group, BgpPeerGroup):
        raise ValueError("UG new-peer-join control peers require a resolved peer group")
    held_peer_addrs = _required_peer_addresses(held)
    keep_peer_addrs = _required_peer_addresses(keep)
    keep_mutated_peer_addrs = _required_peer_addresses(keep_mutated)
    var1_peer_addrs = _required_peer_addresses(var1)
    var2_peer_addrs = _required_peer_addresses(var2)
    var1_route_count, _ = _required_route_intent(var1)
    var2_route_count, _ = _required_route_intent(var2)

    return _UgNewPeerJoinSelectors(
        control_peer_addrs=_required_peer_addresses(ctrl),
        held_back_peer_addr=held_peer_addrs[0],
        held_back_peer_regex=_required_ixia_tag(held),
        disp_peer_addrs=_required_peer_addresses(disp),
        disp_peer_regex=_required_ixia_tag(disp),
        b_keep_peer_addr=keep_peer_addrs[0],
        b_keep_peer_regex=_required_ixia_tag(keep),
        b_keep_route_count=keep_route_count,
        b_keep_mutated_peer_addr=keep_mutated_peer_addrs[0],
        b_keep_mutated_peer_regex=_required_ixia_tag(keep_mutated),
        b_var1_peer_addr=var1_peer_addrs[0],
        b_var1_peer_regex=_required_ixia_tag(var1),
        b_var1_route_count=var1_route_count,
        b_var2_peer_addr=var2_peer_addrs[0],
        b_var2_peer_regex=_required_ixia_tag(var2),
        b_var2_route_count=var2_route_count,
        initial_community=initial_community,
        mutated_community=mutated_community,
        ug_peer_group_substring=peer_group.name,
    )


def _ug_bgp_dg(
    *,
    device_group_index: int,
    tag_name: str,
    multiplier: int,
    starting_peer_ip: str,
    gateway_ip: str,
    remote_as: int,
    is_ebgp: bool,
    advertised_route_count: int = 0,
    starting_prefix: str = "",
    communities: t.Optional[t.List[str]] = None,
) -> taac_types.DeviceGroupConfig:
    """Build one BGP DG (eBGP or iBGP) for the UG hardening topology."""
    route_scales = []
    if advertised_route_count > 0:
        route_scales = [
            taac_types.RouteScaleSpec(
                network_group_index=0,
                v6_route_scale=taac_types.RouteScale(
                    multiplier=1,
                    prefix_count=advertised_route_count,
                    prefix_length=128,
                    starting_prefixes=starting_prefix,
                    prefix_step="0:0:0:0::1",
                    bgp_communities=list(communities or []),
                    ip_address_family=ixia_types.IpAddressFamily.IPV6,
                ),
            ),
        ]

    peer_type = ixia_types.BgpPeerType.EBGP if is_ebgp else ixia_types.BgpPeerType.IBGP

    return taac_types.DeviceGroupConfig(
        device_group_index=device_group_index,
        tag_name=tag_name,
        multiplier=multiplier,
        v6_addresses_config=taac_types.IpAddressesConfig(
            starting_ip=starting_peer_ip,
            increment_ip="0:0:0:0::2",
            gateway_starting_ip=gateway_ip,
            gateway_increment_ip="0:0:0:0::2",
            mask=127,
            start_index=0,
        ),
        v6_bgp_config=taac_types.BgpConfig(
            bgp_peer_name=tag_name,
            local_as_4_bytes=remote_as,
            enable_4_byte_local_as=True,
            bgp_peer_type=peer_type,
            bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
            hold_timer=30,
            keepalive_timer=10,
            route_scales=route_scales,
        ),
    )


def _ebgp_dgs() -> list:
    """Return the 3 eBGP receiver DGs on Et3/36/1 (CTRL, HELD, DISP)."""
    return [
        _ug_bgp_dg(
            device_group_index=0,
            tag_name=_UG_DG_A_CTRL_TAG,
            multiplier=_UG_CTRL_MULTIPLIER,
            starting_peer_ip=_ug_ebgp_peer_addr(_UG_EBGP_CTRL_START_IDX),
            gateway_ip=_ug_ebgp_gateway_addr(_UG_EBGP_CTRL_START_IDX),
            remote_as=EBGP_REMOTE_AS,
            is_ebgp=True,
        ),
        _ug_bgp_dg(
            device_group_index=1,
            tag_name=_UG_DG_A_HELD_TAG,
            multiplier=1,
            starting_peer_ip=_ug_ebgp_peer_addr(_UG_EBGP_HELD_IDX),
            gateway_ip=_ug_ebgp_gateway_addr(_UG_EBGP_HELD_IDX),
            remote_as=EBGP_REMOTE_AS,
            is_ebgp=True,
        ),
        _ug_bgp_dg(
            device_group_index=2,
            tag_name=_UG_DG_A_DISP_TAG,
            multiplier=_UG_DISP_MULTIPLIER,
            starting_peer_ip=_ug_ebgp_peer_addr(_UG_EBGP_DISP_START_IDX),
            gateway_ip=_ug_ebgp_gateway_addr(_UG_EBGP_DISP_START_IDX),
            remote_as=EBGP_REMOTE_AS,
            is_ebgp=True,
        ),
    ]


def _ibgp_dgs() -> list:
    """Return the 4 iBGP sender DGs on Et3/36/2."""
    return [
        _ug_bgp_dg(
            device_group_index=0,
            tag_name=_UG_DG_B_KEEP_TAG,
            multiplier=1,
            starting_peer_ip=_ug_ibgp_peer_addr(_UG_IBGP_B_KEEP_IDX),
            gateway_ip=_ug_ibgp_gateway_addr(_UG_IBGP_B_KEEP_IDX),
            remote_as=IBGP_REMOTE_AS,
            is_ebgp=False,
            advertised_route_count=_UG_KEEP_ROUTE_COUNT,
            starting_prefix="2401:db00:1000::",
            communities=_UG_BASE_SENDER_COMMUNITIES,
        ),
        _ug_bgp_dg(
            device_group_index=1,
            tag_name=_UG_DG_B_KEEP_MUTATED_TAG,
            multiplier=1,
            starting_peer_ip=_ug_ibgp_peer_addr(_UG_IBGP_B_KEEP_MUTATED_IDX),
            gateway_ip=_ug_ibgp_gateway_addr(_UG_IBGP_B_KEEP_MUTATED_IDX),
            remote_as=IBGP_REMOTE_AS,
            is_ebgp=False,
            advertised_route_count=_UG_KEEP_ROUTE_COUNT,
            starting_prefix="2401:db00:1000::",
            communities=_UG_MUTATED_SENDER_COMMUNITIES,
        ),
        _ug_bgp_dg(
            device_group_index=2,
            tag_name=_UG_DG_B_VAR1_TAG,
            multiplier=1,
            starting_peer_ip=_ug_ibgp_peer_addr(_UG_IBGP_B_VAR1_IDX),
            gateway_ip=_ug_ibgp_gateway_addr(_UG_IBGP_B_VAR1_IDX),
            remote_as=IBGP_REMOTE_AS,
            is_ebgp=False,
            advertised_route_count=_UG_VAR1_ROUTE_COUNT,
            starting_prefix="2401:db00:2000::",
            communities=_UG_BASE_SENDER_COMMUNITIES,
        ),
        _ug_bgp_dg(
            device_group_index=3,
            tag_name=_UG_DG_B_VAR2_TAG,
            multiplier=1,
            starting_peer_ip=_ug_ibgp_peer_addr(_UG_IBGP_B_VAR2_IDX),
            gateway_ip=_ug_ibgp_gateway_addr(_UG_IBGP_B_VAR2_IDX),
            remote_as=IBGP_REMOTE_AS,
            is_ebgp=False,
            advertised_route_count=_UG_VAR2_ROUTE_COUNT,
            starting_prefix="2401:db00:3000::",
            communities=_UG_BASE_SENDER_COMMUNITIES,
        ),
    ]


def _baseline_steps(
    *,
    bring_var1_up: bool = False,
    selectors: _UgNewPeerJoinSelectors | None = None,
) -> list:
    """Return setup_steps that bring HELD/VAR1/VAR2 to a clean baseline state.

    SCRUB-THEN-REARM pattern — see legacy `bag012_ash6_test_config._baseline_steps`
    for the full commentary on why DG-disable + hold-timer settle is required.
    """
    selectors = selectors or _legacy_selectors()
    return [
        create_ixia_api_step(
            api_name="toggle_device_groups",
            args_dict={
                "enable": False,
                "device_group_name_regex": selectors.b_var1_peer_regex,
                "sleep_time_before_applying_change": 0,
            },
            description=(
                "UG baseline SCRUB: DG-disable DG_B_VAR1 -- forces DUT to "
                "drop stale VAR1 routes from adj-RIB-out via hold-timer"
            ),
        ),
        create_ixia_api_step(
            api_name="toggle_device_groups",
            args_dict={
                "enable": False,
                "device_group_name_regex": selectors.b_var2_peer_regex,
                "sleep_time_before_applying_change": 0,
            },
            description=(
                "UG baseline SCRUB: DG-disable DG_B_VAR2 -- forces DUT to "
                "drop stale VAR2 routes from adj-RIB-out via hold-timer"
            ),
        ),
        create_ixia_api_step(
            api_name="toggle_device_groups",
            args_dict={
                "enable": False,
                "device_group_name_regex": selectors.b_keep_mutated_peer_regex,
                "sleep_time_before_applying_change": 0,
            },
            description=(
                "UG baseline SCRUB: DG-disable DG_B_KEEP_MUTATED -- ensures "
                "only KEEP_INITIAL advertises the 300-prefix range at baseline "
                "(2.4.3 trigger toggles this pair to swap community)"
            ),
        ),
        create_longevity_step(
            duration=90,
            description=(
                "UG baseline SCRUB: settle 90s for DUT hold-timer expiry "
                "+ adj-RIB-out withdraw to propagate (iBGP peer-group "
                "hold-time is >60s on bag012, per 2.4.2 v17 finding)"
            ),
        ),
        create_ixia_api_step(
            api_name="toggle_device_groups",
            args_dict={
                "enable": True,
                "device_group_name_regex": selectors.b_var1_peer_regex,
                "sleep_time_before_applying_change": 0,
            },
            description="UG baseline REARM: re-enable DG_B_VAR1",
        ),
        create_ixia_api_step(
            api_name="toggle_device_groups",
            args_dict={
                "enable": True,
                "device_group_name_regex": selectors.b_var2_peer_regex,
                "sleep_time_before_applying_change": 0,
            },
            description="UG baseline REARM: re-enable DG_B_VAR2",
        ),
        create_start_stop_bgp_peers_step(
            peer_regex=selectors.held_back_peer_regex,
            start=False,
            start_idx=1,
            end_idx=1,
            description="UG baseline: bring HELD admin-DOWN",
        ),
        create_start_stop_bgp_peers_step(
            peer_regex=selectors.b_var1_peer_regex,
            start=bring_var1_up,
            start_idx=1,
            end_idx=1,
            description=(
                "UG baseline: bring DG_B_VAR1 admin-"
                + ("UP" if bring_var1_up else "DOWN")
            ),
        ),
        create_start_stop_bgp_peers_step(
            peer_regex=selectors.b_var2_peer_regex,
            start=False,
            start_idx=1,
            end_idx=1,
            description="UG baseline: bring DG_B_VAR2 admin-DOWN",
        ),
    ]


def _pb_2_4_1(
    device_name: str,
    selectors: _UgNewPeerJoinSelectors | None = None,
) -> taac_types.Playbook:
    selectors = selectors or _legacy_selectors()
    return create_bgp_ug_new_peer_join_full_sync_resilience_playbook(
        device_name=device_name,
        control_peer_addrs=selectors.control_peer_addrs,
        held_back_peer_addr=selectors.held_back_peer_addr,
        held_back_peer_regex=selectors.held_back_peer_regex,
        disp_peer_addrs=selectors.disp_peer_addrs,
        disp_peer_regex=selectors.disp_peer_regex,
        disp_session_start_idx=1,
        disp_session_end_idx=len(selectors.disp_peer_addrs),
        b_keep_peer_addr=selectors.b_keep_peer_addr,
        b_keep_route_count=selectors.b_keep_route_count,
        b_var1_peer_regex=selectors.b_var1_peer_regex,
        b_var1_peer_addr=selectors.b_var1_peer_addr,
        b_var1_route_count=selectors.b_var1_route_count,
        b_var2_peer_regex=selectors.b_var2_peer_regex,
        b_var2_peer_addr=selectors.b_var2_peer_addr,
        b_var2_route_count=selectors.b_var2_route_count,
        ug_peer_group_substring=selectors.ug_peer_group_substring,
        setup_steps=_baseline_steps(bring_var1_up=False, selectors=selectors),
    )


def _pb_2_4_2(
    device_name: str,
    selectors: _UgNewPeerJoinSelectors | None = None,
) -> taac_types.Playbook:
    selectors = selectors or _legacy_selectors()
    return create_bgp_ug_new_peer_join_routes_withdrawn_playbook(
        device_name=device_name,
        control_peer_addrs=selectors.control_peer_addrs,
        held_back_peer_addr=selectors.held_back_peer_addr,
        held_back_peer_regex=selectors.held_back_peer_regex,
        b_keep_peer_addr=selectors.b_keep_peer_addr,
        b_keep_route_count=selectors.b_keep_route_count,
        b_var1_peer_regex=selectors.b_var1_peer_regex,
        b_var1_peer_addr=selectors.b_var1_peer_addr,
        b_var1_route_count=selectors.b_var1_route_count,
        b_var1_device_group_regex=selectors.b_var1_peer_regex,
        ug_peer_group_substring=selectors.ug_peer_group_substring,
        capture_tcpdump_device=device_name,
        setup_steps=_baseline_steps(bring_var1_up=True, selectors=selectors),
    )


def _pb_2_4_3(
    device_name: str,
    selectors: _UgNewPeerJoinSelectors | None = None,
) -> taac_types.Playbook:
    selectors = selectors or _legacy_selectors()
    return create_bgp_ug_new_peer_join_attribute_change_playbook(
        device_name=device_name,
        control_peer_addrs=selectors.control_peer_addrs,
        held_back_peer_addr=selectors.held_back_peer_addr,
        held_back_peer_regex=selectors.held_back_peer_regex,
        b_keep_peer_addr=selectors.b_keep_peer_addr,
        b_keep_route_count=selectors.b_keep_route_count,
        b_keep_peer_regex=selectors.b_keep_peer_regex,
        b_keep_device_group_regex=selectors.b_keep_peer_regex,
        b_keep_mutated_peer_addr=selectors.b_keep_mutated_peer_addr,
        b_keep_mutated_device_group_regex=selectors.b_keep_mutated_peer_regex,
        initial_community=selectors.initial_community,
        mutated_community=selectors.mutated_community,
        ug_peer_group_substring=selectors.ug_peer_group_substring,
        setup_steps=_baseline_steps(bring_var1_up=False, selectors=selectors),
    )


def _build_legacy_bgp_ug_new_peer_join_test_config(
    testbed: Testbed,
) -> taac_types.TestConfig:
    """BGP++ Update Group qualification specs 2.4.1 + 2.4.2 + 2.4.3 TestConfig.

    Three qualification playbooks sharing one 21-eBGP + 4-iBGP testbed.
    ``enable_update_group=True`` is baked in (UG MUST be on for these specs).

    Wave 1 constraint: hardcoded to bag012's topology + IXIA wiring
    (helpers use ``IXIA_EBGP_IC_PARENT_NETWORK_V6`` etc. from the shared
    EBB conveyor constants module). ``testbed`` MUST be BAG012_ASH6. Wave 2
    parameterizes the underlying helpers on ``testbed.ixia_ports`` +
    ``testbed.dut_bgp_as`` so bag010/011/013 can host this qualification via
    a one-line catalog change.
    """
    assert testbed.device_name == "bag012.ash6", (
        f"create_bgp_ug_new_peer_join_test_config Wave 1 is hardcoded to "
        f"bag012.ash6; got testbed.device_name={testbed.device_name!r}. "
        f"Wave 2 will parameterize on testbed."
    )
    assert testbed.dut_bgp_as is not None, "Testbed must have dut_bgp_as set"
    assert testbed.router_id is not None, (
        "Testbed must have router_id set (used as BGP router-id)"
    )
    assert testbed.bgpcpp_configerator_path is not None, (
        "Testbed must have bgpcpp_configerator_path set for BGP++ deployment"
    )
    assert len(testbed.ixia_ports) >= 2, (
        "Testbed must have >= 2 IXIA ports (eBGP + iBGP)"
    )

    ebgp_dut_iface, ebgp_chassis_port = testbed.ixia_ports[0]
    ibgp_dut_iface, ibgp_chassis_port = testbed.ixia_ports[1]

    setup_tasks = get_update_packing_setup_tasks(
        device_name=testbed.device_name,
        bgp_asn=testbed.dut_bgp_as,
        ixia_interface_mimic_ebgp=ebgp_dut_iface,
        ixia_interface_mimic_ibgp=ibgp_dut_iface,
        ebgp_peer_count=_UG_TOTAL_EBGP_PEERS,
        ibgp_peer_count=_UG_TOTAL_IBGP_PEERS,
        ebgp_remote_as=EBGP_REMOTE_AS,
        ibgp_remote_as=IBGP_REMOTE_AS,
        ixia_ebgp_ic_parent_network_v6=IXIA_EBGP_IC_PARENT_NETWORK_V6,
        ixia_ibgp_ic_parent_network_v6=IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE1,
        router_id=testbed.router_id,
        bgpcpp_configerator_path=testbed.bgpcpp_configerator_path,
        profile=BgpPlusPlusProfile.BGP_PLUS_PLUS_WITHOUT_OPEN_R,
        enable_update_group=True,
    )

    return taac_types.TestConfig(
        name="BGP_UG_NEW_PEER_JOIN_TEST",
        skip_ixia_protocol_verification=True,
        log_collection_timeout=600,
        basset_pool="dne.test",
        endpoints=[
            taac_types.Endpoint(
                name=testbed.device_name,
                dut=True,
                ixia_ports=[
                    f"{testbed.ixia_chassis_ip}:{ebgp_chassis_port}",
                    f"{testbed.ixia_chassis_ip}:{ibgp_chassis_port}",
                ],
                direct_ixia_connections=[
                    taac_types.DirectIxiaConnection(
                        interface=ebgp_dut_iface,
                        ixia_chassis_ip=testbed.ixia_chassis_ip,
                        ixia_port=ebgp_chassis_port,
                    ),
                    taac_types.DirectIxiaConnection(
                        interface=ibgp_dut_iface,
                        ixia_chassis_ip=testbed.ixia_chassis_ip,
                        ixia_port=ibgp_chassis_port,
                    ),
                ],
            ),
        ],
        host_os_type_map={testbed.device_name: taac_types.DeviceOsType.ARISTA_FBOSS},
        startup_checks=[],
        setup_tasks=setup_tasks,
        teardown_tasks=[],
        basic_port_configs=[
            taac_types.BasicPortConfig(
                endpoint=f"{testbed.device_name}:{ebgp_dut_iface}",
                device_group_configs=_ebgp_dgs(),
            ),
            taac_types.BasicPortConfig(
                endpoint=f"{testbed.device_name}:{ibgp_dut_iface}",
                device_group_configs=_ibgp_dgs(),
            ),
        ],
        playbooks=[
            _pb_2_4_1(testbed.device_name),
            _pb_2_4_2(testbed.device_name),
            _pb_2_4_3(testbed.device_name),
        ],
    )


def create_bgp_ug_new_peer_join_test_config(testbed: Testbed) -> taac_types.TestConfig:
    """Build the BAG012 UG new-peer-join config from typed topology intent."""
    if testbed.device_name != "bag012.ash6":
        raise ValueError(
            f"create_bgp_ug_new_peer_join_test_config Wave 1 is hardcoded to "
            f"bag012.ash6; got testbed.device_name={testbed.device_name!r}. "
            f"Wave 2 will parameterize on testbed."
        )
    if testbed.dut_bgp_as is None:
        raise ValueError("Testbed must have dut_bgp_as set")
    if testbed.router_id is None:
        raise ValueError("Testbed must have router_id set (used as BGP router-id)")
    if testbed.bgpcpp_configerator_path is None:
        raise ValueError(
            "Testbed must have bgpcpp_configerator_path set for BGP++ deployment"
        )
    if len(testbed.ixia_ports) < 2:
        raise ValueError("Testbed must have >= 2 IXIA ports (eBGP + iBGP)")

    bound = UG_NEW_PEER_JOIN.bind_to_testbed(
        testbed=testbed,
        port_map=UG_NEW_PEER_JOIN_PORT_MAP,
        parent_networks=UG_NEW_PEER_JOIN_PARENT_NETWORKS,
        peer_groups=UG_NEW_PEER_JOIN_PEER_GROUPS,
        as_numbers=UG_NEW_PEER_JOIN_AS_NUMBERS,
    )
    selectors = _selectors_from_bound(bound)
    compiled = bound.compile()

    return taac_types.TestConfig(
        name="BGP_UG_NEW_PEER_JOIN_TEST",
        skip_ixia_protocol_verification=True,
        log_collection_timeout=600,
        basset_pool="dne.test",
        endpoints=compiled.endpoints,
        host_os_type_map=compiled.host_os_type_map,
        startup_checks=[],
        setup_tasks=compiled.setup_tasks,
        teardown_tasks=compiled.teardown_tasks,
        basic_port_configs=compiled.basic_port_configs,
        playbooks=[
            _pb_2_4_1(testbed.device_name, selectors),
            _pb_2_4_2(testbed.device_name, selectors),
            _pb_2_4_3(testbed.device_name, selectors),
        ],
    )


__all__ = [
    "create_bgp_ug_new_peer_join_test_config",
]
