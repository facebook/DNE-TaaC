# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-strict
"""Spec 2.4 — New Peer Joining a Busy Group. UG qualification testconfig factory.

See ``playbooks/routing/factories/qual_bgp_update_group/tc4_new_peer_join.py``
for the three sub-spec playbook factories (2.4.1 / 2.4.2 / 2.4.3).
"""

from dataclasses import dataclass

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
from taac.testconfigs.routing.physical_inventory import (
    PhysicalInventory,
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
    if len(group.prefix_advertisements) != 1:
        raise ValueError(
            f"UG new-peer-join sender {group.name!r} requires one prefix advertisement"
        )
    advertisement = group.prefix_advertisements[0]
    policy = advertisement.spec.policy
    if not isinstance(policy, BgpPolicy):
        raise ValueError(
            f"UG new-peer-join advertisement {advertisement.spec.name!r} "
            "requires a BGP policy"
        )
    return advertisement.spec.allocation.prefixes_per_peer, policy.communities


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


def _baseline_steps(
    *,
    bring_var1_up: bool = False,
    selectors: _UgNewPeerJoinSelectors,
) -> list:
    """Return setup_steps that bring HELD/VAR1/VAR2 to a clean baseline state.

    SCRUB-THEN-REARM pattern — see legacy `bag012_ash6_test_config._baseline_steps`
    for the full commentary on why DG-disable + hold-timer settle is required.
    """
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
    selectors: _UgNewPeerJoinSelectors,
) -> taac_types.Playbook:
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
    selectors: _UgNewPeerJoinSelectors,
) -> taac_types.Playbook:
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
    selectors: _UgNewPeerJoinSelectors,
) -> taac_types.Playbook:
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


def create_bgp_ug_new_peer_join_test_config(
    physical_inventory: PhysicalInventory,
) -> taac_types.TestConfig:
    """Build the BAG012 UG new-peer-join config from typed topology intent."""
    if physical_inventory.device_name != "bag012.ash6":
        raise ValueError(
            f"create_bgp_ug_new_peer_join_test_config Wave 1 is hardcoded to "
            f"bag012.ash6; got physical_inventory.device_name={physical_inventory.device_name!r}. "
            f"Wave 2 will parameterize on physical_inventory."
        )
    if physical_inventory.dut_bgp_as is None:
        raise ValueError("PhysicalInventory must have dut_bgp_as set")
    if physical_inventory.router_id is None:
        raise ValueError(
            "PhysicalInventory must have router_id set (used as BGP router-id)"
        )
    if physical_inventory.bgpcpp_configerator_path is None:
        raise ValueError(
            "PhysicalInventory must have bgpcpp_configerator_path set for BGP++ deployment"
        )
    if len(physical_inventory.ixia_ports) < 2:
        raise ValueError("PhysicalInventory must have >= 2 IXIA ports (eBGP + iBGP)")

    bound = UG_NEW_PEER_JOIN.bind_to_inventory(
        physical_inventory=physical_inventory,
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
            _pb_2_4_1(physical_inventory.device_name, selectors),
            _pb_2_4_2(physical_inventory.device_name, selectors),
            _pb_2_4_3(physical_inventory.device_name, selectors),
        ],
    )


__all__ = [
    "create_bgp_ug_new_peer_join_test_config",
]
