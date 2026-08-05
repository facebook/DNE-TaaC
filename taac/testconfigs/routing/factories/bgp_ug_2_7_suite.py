# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""BAG012 EBB full-scale bindings for Update Group cases 2.7.4 and 2.7.6."""

import uuid

from taac.abstractions.physical_inventory import PhysicalInventory
from taac.abstractions.topology import (
    BoundDeviceGroup,
    BoundTopology,
)
from taac.playbooks.routing.factories.qual_bgp_update_group.tc7_cases.bgp_daemon_restart import (
    create_bgp_ug_bgp_daemon_restart_playbook,
    EXPECTED_SESSION_COUNT,
)
from taac.playbooks.routing.factories.qual_bgp_update_group.tc7_cases.fibagent_restart import (
    create_bgp_ug_fibagent_restart_playbook,
)
from taac.testconfigs.routing.util.bgp_ebb_constants import (
    EBGP_PEER_COUNT_V4,
    EBGP_PEER_COUNT_V6,
    IBGP_PEER_SCALE_PER_PLANE,
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
from taac.test_as_a_config.types import Playbook


_SHARED_RUNTIME_POOL_REGEX_BY_AFI = {
    "ipv4": r"^PREFIX_POOL_IPV4_EBGP_UG_2_7_RUNTIME$",
    "ipv6": r"^PREFIX_POOL_IPV6_EBGP_UG_2_7_RUNTIME$",
}


def _ibgp_groups(bound: BoundTopology, afi: str) -> list[BoundDeviceGroup]:
    groups = [
        group
        for group in bound.device_groups
        if group.afi == afi and group.role.startswith("ibgp_")
    ]
    if len(groups) != 8 or any(group.peer_count != 62 for group in groups):
        raise ValueError(f"TC7 requires eight 62-peer iBGP {afi} device groups")
    return groups


def _host_prefixes(groups: list[BoundDeviceGroup]) -> list[str]:
    return [
        f"{address}/{'128' if ':' in address else '32'}"
        for group in groups
        for address in group.z_ips
    ]


def _health_checks() -> tuple[list, list, list]:
    prechecks = create_standard_prechecks(
        peergroup_ibgp_v6=PEERGROUP_IBGP_V6,
        peergroup_ibgp_v4=PEERGROUP_IBGP_V4,
        expected_established_sessions=EXPECTED_SESSION_COUNT,
        cpu_baseline=12.0,
        check_ibgp_pnh=True,
        check_hardware_capacity=False,
        exclude_bgp_mon=True,
    )
    postchecks = create_standard_postchecks(
        expected_established_session_count=EXPECTED_SESSION_COUNT,
        exclude_bgp_mon=True,
    )
    snapshots = create_standard_snapshot_checks(
        skip_flap_check=True,
        skip_uptime_check=True,
        exclude_bgp_mon=True,
    )
    return prechecks, postchecks, snapshots


def _group_contract() -> tuple[list[str], dict[str, int], dict[str, str]]:
    groups = [
        PEERGROUP_EBGP_V4,
        PEERGROUP_EBGP_V6,
        PEERGROUP_IBGP_V4,
        PEERGROUP_IBGP_V6,
    ]
    counts = {
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
    return groups, counts, afis


def _all_peer_addresses(bound: BoundTopology) -> list[str]:
    addresses = [address for group in bound.device_groups for address in group.z_ips]
    if (
        len(addresses) != EXPECTED_SESSION_COUNT
        or len(set(addresses)) != EXPECTED_SESSION_COUNT
    ):
        raise ValueError(
            "TC7 route parity requires exactly "
            f"{EXPECTED_SESSION_COUNT} unique peer addresses"
        )
    return addresses


def _case_key(device_name: str, playbook_name: str, suffix: str) -> str:
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"{device_name}:{playbook_name}:{suffix}",
        )
    )


def _daemon_restart(
    inventory: PhysicalInventory,
    bound: BoundTopology,
) -> Playbook:
    playbook_name = "bgp_ug_bgp_daemon_restart"
    prechecks, postchecks, snapshots = _health_checks()
    groups, counts, afis = _group_contract()
    return create_bgp_ug_bgp_daemon_restart_playbook(
        device_name=inventory.device_name,
        state_key=_case_key(inventory.device_name, playbook_name, "semantic-state"),
        route_pool_regex_by_afi=_SHARED_RUNTIME_POOL_REGEX_BY_AFI,
        ibgp_receiver_host_prefixes_by_afi={
            "ipv4": _host_prefixes(_ibgp_groups(bound, "v4")),
            "ipv6": _host_prefixes(_ibgp_groups(bound, "v6")),
        },
        all_peer_addresses=_all_peer_addresses(bound),
        peer_group_substrings=groups,
        expected_member_counts=counts,
        expected_afi_by_substring=afis,
        prechecks=prechecks,
        postchecks=postchecks,
        snapshot_checks=snapshots,
    )


def _fibagent_restart(inventory: PhysicalInventory, bound: BoundTopology) -> Playbook:
    playbook_name = "bgp_ug_fibagent_restart"
    prechecks, postchecks, snapshots = _health_checks()
    groups, counts, afis = _group_contract()
    return create_bgp_ug_fibagent_restart_playbook(
        device_name=inventory.device_name,
        state_key=_case_key(inventory.device_name, playbook_name, "semantic-state"),
        route_pool_regex_by_afi=_SHARED_RUNTIME_POOL_REGEX_BY_AFI,
        ibgp_receiver_parent_prefixes_by_afi={
            "ipv4": _host_prefixes(_ibgp_groups(bound, "v4")),
            "ipv6": _host_prefixes(_ibgp_groups(bound, "v6")),
        },
        peer_group_substrings=groups,
        expected_member_counts=counts,
        expected_afi_by_substring=afis,
        prechecks=prechecks,
        postchecks=postchecks,
        snapshot_checks=snapshots,
    )


def build_bgp_ug_2_7_playbook(
    playbook_name: str,
    inventory: PhysicalInventory,
    bound: BoundTopology,
) -> Playbook:
    if playbook_name == "bgp_ug_fibagent_restart":
        return _fibagent_restart(inventory, bound)
    if playbook_name != "bgp_ug_bgp_daemon_restart":
        raise ValueError(f"Unsupported TC7 playbook {playbook_name!r}")
    return _daemon_restart(inventory, bound)
