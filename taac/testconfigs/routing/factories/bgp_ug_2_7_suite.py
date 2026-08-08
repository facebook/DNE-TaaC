# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""BAG012 EBB full-scale bindings for Update Group cases 2.7.3-2.7.6."""

import ipaddress
import re
import typing as t
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
from taac.playbooks.routing.factories.qual_bgp_update_group.tc7_cases.cold_start import (
    create_bgp_ug_cold_start_playbook,
)
from taac.playbooks.routing.factories.qual_bgp_update_group.tc7_cases.fibagent_restart import (
    create_bgp_ug_fibagent_restart_playbook,
)
from taac.playbooks.routing.factories.qual_bgp_update_group.tc7_cases.peer_flapping import (
    create_bgp_ug_bgp_peer_flapping_playbook,
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


def _required_group(bound: BoundTopology, name: str) -> BoundDeviceGroup:
    matches = [group for group in bound.device_groups if group.name == name]
    if len(matches) != 1:
        raise ValueError(f"Expected one EBB group {name!r}; found {len(matches)}")
    return matches[0]


def _required_peer_name(group: BoundDeviceGroup) -> str:
    name = group.legacy_ixia_bgp_peer_name or group.legacy_ixia_tag_name
    if not name:
        raise ValueError(f"TC7 group {group.name!r} has no IXIA BGP peer name")
    return name


def _required_z_ip(group: BoundDeviceGroup) -> str:
    if not group.z_ips:
        raise ValueError(f"TC7 group {group.name!r} has no z_ips")
    return min(group.z_ips, key=lambda address: int(ipaddress.ip_address(address)))


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


def _cold_start_wire_inputs(
    bound: BoundTopology,
) -> tuple[list[str], list[str], list[str]]:
    sources_by_interface: dict[str, list[str]] = {}
    for group in bound.device_groups:
        interface = group.a_interface
        if not interface or not group.a_ips:
            raise ValueError(
                f"2.7.5 wire capture requires DUT interface and IPs for {group.name}"
            )
        sources_by_interface.setdefault(interface, []).extend(group.a_ips)
    if len(sources_by_interface) != 2:
        raise ValueError(
            "2.7.5 wire capture requires exactly two DUT-facing IXIA interfaces; "
            f"found {sorted(sources_by_interface)}"
        )
    interfaces = sorted(sources_by_interface)
    sources = [
        address
        for interface in interfaces
        for address in sources_by_interface[interface]
    ]
    if len(sources) != EXPECTED_SESSION_COUNT or len(set(sources)) != len(sources):
        raise ValueError(
            "2.7.5 wire capture requires exactly 1272 unique DUT source addresses"
        )
    for address in sources:
        try:
            ipaddress.ip_address(address)
        except ValueError as error:
            raise ValueError(
                f"2.7.5 wire capture found invalid DUT source {address!r}"
            ) from error
    ibgp_interfaces = {
        group.a_interface for afi in ("v4", "v6") for group in _ibgp_groups(bound, afi)
    }
    if None in ibgp_interfaces or len(ibgp_interfaces) != 1:
        raise ValueError(
            "2.7.5 runtime route fanout requires one shared iBGP capture "
            f"interface; found {sorted(str(value) for value in ibgp_interfaces)}"
        )
    return interfaces, sources, [t.cast(str, next(iter(ibgp_interfaces)))]


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


def _validated_device_group_names(bound: BoundTopology) -> list[str]:
    device_group_names = [
        group.legacy_ixia_device_group_name for group in bound.device_groups
    ]
    if len(device_group_names) != 18 or any(not name for name in device_group_names):
        raise ValueError("2.7.5 requires 18 named IXIA device groups")
    names = t.cast(list[str], device_group_names)
    if len(set(names)) != 18:
        raise ValueError("2.7.5 requires 18 unique named IXIA device groups")
    return names


def _cold_start(inventory: PhysicalInventory, bound: BoundTopology) -> Playbook:
    playbook_name = "bgp_ug_cold_start"
    prechecks, postchecks, snapshots = _health_checks()
    groups, counts, afis = _group_contract()
    device_group_names = _validated_device_group_names(bound)
    (
        capture_interfaces,
        dut_source_addresses,
        runtime_update_interfaces,
    ) = _cold_start_wire_inputs(bound)
    return create_bgp_ug_cold_start_playbook(
        device_name=inventory.device_name,
        state_key=_case_key(inventory.device_name, playbook_name, "semantic-state"),
        device_group_regex=rf"^(?:{'|'.join(re.escape(name) for name in device_group_names)})$",
        capture_interfaces=capture_interfaces,
        dut_source_addresses=dut_source_addresses,
        runtime_update_interfaces=runtime_update_interfaces,
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


def _peer_flapping(inventory: PhysicalInventory, bound: BoundTopology) -> Playbook:
    playbook_name = "bgp_ug_bgp_peer_flapping"
    v4 = _required_group(bound, "dg_ebgp_v4")
    v6 = _required_group(bound, "dg_ebgp_v6")
    names = [_required_peer_name(group) for group in (v4, v6)]
    prechecks, postchecks, snapshots = _health_checks()
    return create_bgp_ug_bgp_peer_flapping_playbook(
        device_name=inventory.device_name,
        peer_regex=rf"^(?:{'|'.join(re.escape(name) for name in names)})$",
        reserved_peer_addresses=[_required_z_ip(v4), _required_z_ip(v6)],
        churn_prefix_pool_regexes=[
            _SHARED_RUNTIME_POOL_REGEX_BY_AFI["ipv4"],
            _SHARED_RUNTIME_POOL_REGEX_BY_AFI["ipv6"],
        ],
        receiver_parent_prefixes=[
            *_host_prefixes(_ibgp_groups(bound, "v4")),
            *_host_prefixes(_ibgp_groups(bound, "v6")),
        ],
        state_key=_case_key(inventory.device_name, playbook_name, "semantic-state"),
        prechecks=prechecks,
        postchecks=postchecks,
        snapshot_checks=snapshots,
    )


def build_bgp_ug_2_7_playbook(
    playbook_name: str,
    inventory: PhysicalInventory,
    bound: BoundTopology,
) -> Playbook:
    if playbook_name == "bgp_ug_cold_start":
        return _cold_start(inventory, bound)
    if playbook_name == "bgp_ug_bgp_peer_flapping":
        return _peer_flapping(inventory, bound)
    if playbook_name == "bgp_ug_fibagent_restart":
        return _fibagent_restart(inventory, bound)
    if playbook_name != "bgp_ug_bgp_daemon_restart":
        raise ValueError(f"Unsupported TC7 playbook {playbook_name!r}")
    return _daemon_restart(inventory, bound)
