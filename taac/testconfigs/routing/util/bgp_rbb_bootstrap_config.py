# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""Pure, fail-closed builders for the optional RBB fresh-image bootstrap.

The FBOSS image already owns the hardware configuration: platform firmware,
port inventory, supported profiles, speed, queues, and switch settings.  This
module never generates any of those fields.  It deep-copies the installed
AgentConfig and changes only the logical RBB slice selected by
``circuit_info.csv``: selected core ports/RIFs/LAGs, three virtual RIFs, SRv6
MySIDs/tunnel/routes, OpenR interface selection, and one loopback iBGP peer.

Every builder is side-effect free so the complete result can be validated
before the device task creates a recovery snapshot or writes a live file.
"""

from __future__ import annotations

import copy
import ipaddress
import posixpath
import re
import typing as t
from dataclasses import dataclass

from taac.testconfigs.routing.util import bgp_rbb_constants as C
from taac.testconfigs.routing.util.bgp_rbb_topology import (
    CorePortChannel,
    RbbTopology,
    validate_rbb_topology,
)

_PORT_CHANNEL_RE = re.compile(r"^port-channel([0-9]+)$", re.IGNORECASE)
_SAFE_DEVICE_PATH_RE = re.compile(r"^/[A-Za-z0-9._/+:-]+$")
_RESERVED_DEVICE_PATH_SUFFIXES = (
    ".taac_tmp",
    ".taac-rbb-bootstrap-orig",
    ".taac-rbb-bootstrap-orig.missing",
    ".taac-rbb-edge-orig",
    ".taac-rbb-edge-orig.missing",
)
_PORT_ENABLED = 2  # cfg::PortState.ENABLED
_INTERFACE_PORT = 0  # cfg::PortType.INTERFACE_PORT
_IBGP_PEER_GROUP = "RBB-IBGP-LOOPBACK-V4V6"


@dataclass(frozen=True)
class NodeBootstrapPlan:
    """Validated logical/address plan for one DUT."""

    role: str
    router_id: str
    loopback_v6: str
    peer_router_id: str
    core_v4: t.Tuple[str, ...]
    core_v6: t.Tuple[str, ...]
    peer_core_v6: t.Tuple[str, ...]
    srv6_source_a: str
    srv6_source_b: str


@dataclass(frozen=True)
class BootstrapDocuments:
    """The three documents changed by one bootstrap task."""

    agent: t.Dict[str, t.Any]
    bgp: t.Dict[str, t.Any]
    openr: t.Dict[str, t.Any]


def _interface(value: str, *, family: int, prefixlen: int, label: str) -> str:
    try:
        parsed = ipaddress.ip_interface(value)
    except ValueError as exc:
        raise ValueError(f"{label} is not a valid interface address: {value!r}") from exc
    if parsed.version != family or parsed.network.prefixlen != prefixlen:
        raise ValueError(f"{label} must be IPv{family} /{prefixlen}: {value!r}")
    if parsed.ip.is_unspecified or parsed.ip.is_multicast:
        raise ValueError(f"{label} must be a usable unicast address: {value!r}")
    return str(parsed)


def _address(value: str, *, family: int, label: str) -> str:
    try:
        parsed = ipaddress.ip_address(value.split("/", 1)[0])
    except ValueError as exc:
        raise ValueError(f"{label} is not a valid IP address: {value!r}") from exc
    if parsed.version != family or parsed.is_unspecified or parsed.is_multicast:
        raise ValueError(f"{label} must be a usable IPv{family} address: {value!r}")
    return str(parsed)


def port_channel_key(name: str) -> int:
    """Return the numeric FBOSS aggregate key, rejecting ambiguous names."""
    match = _PORT_CHANNEL_RE.fullmatch(name.strip())
    if match is None:
        raise ValueError(
            f"bootstrap port-channel {name!r} must be named port-channel<N>"
        )
    key = int(match.group(1))
    if not 1 <= key <= 0x7FFF:
        raise ValueError(f"bootstrap port-channel key must be 1..32767: {name!r}")
    return key


def validate_bootstrap_device_paths(paths: t.Sequence[str]) -> None:
    """Reject ambiguous or shell-active on-device configuration paths.

    FBOSS driver file existence checks are shell-backed.  Paths are normally
    image-owned constants, but OSS adopters may override them through the
    environment, so validation must happen before the first path-dependent
    device call.
    """
    if not paths or not all(isinstance(path, str) for path in paths):
        raise ValueError("bootstrap device paths must be non-empty strings")
    if len(set(paths)) != len(paths):
        raise ValueError("bootstrap config and recovery paths must be distinct")
    for path in paths:
        if (
            path == "/"
            or path.startswith("//")
            or posixpath.normpath(path) != path
            or _SAFE_DEVICE_PATH_RE.fullmatch(path) is None
            or path.endswith(_RESERVED_DEVICE_PATH_SUFFIXES)
        ):
            raise ValueError(
                "bootstrap device paths must be canonical absolute paths using "
                "only letters, digits, '.', '_', '/', '+', ':', or '-', and "
                "must not name a TAAC recovery/staging artifact"
            )


def validate_bootstrap_topology(topology: RbbTopology) -> None:
    """Apply the stricter wiring contract needed for config generation.

    Read-only qualification supports arbitrary LAG width.  The first bootstrap
    intentionally supports one physical member per core LAG because the stock
    FBOSS image gives every port a distinct ingress VLAN; inventing a multi-port
    VLAN/LAG model without a platform contract would be unsafe.
    """
    validate_rbb_topology(topology, require_ixia=False)
    errors: t.List[str] = []
    for node in (topology.r1, topology.r2):
        keys: t.Set[int] = set()
        for pc in node.core_pcs:
            try:
                key = port_channel_key(pc.name)
            except ValueError as exc:
                errors.append(f"{node.hostname}: {exc}")
                continue
            if key in keys:
                errors.append(
                    f"{node.hostname}: duplicate numeric port-channel key {key}"
                )
            keys.add(key)
            if len(pc.members) != 1:
                errors.append(
                    f"{node.hostname}: bootstrap currently requires exactly one "
                    f"member in {pc.name!r}; found {len(pc.members)}"
                )
    if errors:
        raise ValueError("invalid RBB bootstrap topology: " + "; ".join(errors))
    _validate_address_plan(len(topology.r1.core_pcs))


def _node_plan(role: str, core_count: int) -> NodeBootstrapPlan:
    if role == "r1":
        router_id, peer_router_id = C.R1_ROUTER_ID, C.R2_ROUTER_ID
        loopback_v6 = C.R1_LOOPBACK_V6
    elif role == "r2":
        router_id, peer_router_id = C.R2_ROUTER_ID, C.R1_ROUTER_ID
        loopback_v6 = C.R2_LOOPBACK_V6
    else:
        raise ValueError(f"unknown RBB role {role!r}; expected 'r1' or 'r2'")
    peer_role = "r2" if role == "r1" else "r1"
    return NodeBootstrapPlan(
        role=role,
        router_id=_address(router_id, family=4, label=f"{role} router ID"),
        loopback_v6=_address(
            loopback_v6, family=6, label=f"{role} IPv6 loopback"
        ),
        peer_router_id=_address(
            peer_router_id, family=4, label=f"{peer_role} router ID"
        ),
        core_v4=tuple(
            _interface(
                C.core_rif_cidr(role, index, 4),
                family=4,
                prefixlen=30,
                label=f"{role} core{index} IPv4 RIF",
            )
            for index in range(core_count)
        ),
        core_v6=tuple(
            _interface(
                C.core_rif_cidr(role, index, 6),
                family=6,
                prefixlen=127,
                label=f"{role} core{index} IPv6 RIF",
            )
            for index in range(core_count)
        ),
        peer_core_v6=tuple(
            _interface(
                C.core_rif_cidr(peer_role, index, 6),
                family=6,
                prefixlen=127,
                label=f"{peer_role} core{index} IPv6 RIF",
            )
            for index in range(core_count)
        ),
        srv6_source_a=_interface(
            C.srv6_source_cidr(role, "A"),
            family=6,
            prefixlen=128,
            label=f"{role} SRv6 source A",
        ),
        srv6_source_b=_interface(
            C.srv6_source_cidr(role, "B"),
            family=6,
            prefixlen=128,
            label=f"{role} SRv6 source B",
        ),
    )


def _validate_address_plan(count: int) -> None:
    r1, r2 = _node_plan("r1", count), _node_plan("r2", count)
    if r1.router_id == r2.router_id:
        raise ValueError("R1 and R2 router IDs must differ")
    if r1.loopback_v6 == r2.loopback_v6:
        raise ValueError("R1 and R2 IPv6 loopbacks must differ")
    seen_v4: t.Set[ipaddress.IPv4Network] = set()
    seen_v6: t.Set[ipaddress.IPv6Network] = set()
    core_v4_addresses: t.Set[ipaddress.IPv4Address] = set()
    core_v6_addresses: t.Set[ipaddress.IPv6Address] = set()
    for index in range(count):
        left4 = ipaddress.ip_interface(r1.core_v4[index])
        right4 = ipaddress.ip_interface(r2.core_v4[index])
        left6 = ipaddress.ip_interface(r1.core_v6[index])
        right6 = ipaddress.ip_interface(r2.core_v6[index])
        if left4.network != right4.network or left4.ip == right4.ip:
            raise ValueError(f"core{index} IPv4 RIFs must be distinct peers in one /30")
        if left6.network != right6.network or left6.ip == right6.ip:
            raise ValueError(f"core{index} IPv6 RIFs must be distinct peers in one /127")
        if left4.network in seen_v4 or left6.network in seen_v6:
            raise ValueError("each core port-channel needs a unique RIF subnet")
        if left4.ip in (
            left4.network.network_address,
            left4.network.broadcast_address,
        ) or right4.ip in (
            right4.network.network_address,
            right4.network.broadcast_address,
        ):
            raise ValueError(f"core{index} IPv4 RIFs must use the two host addresses")
        seen_v4.add(t.cast(ipaddress.IPv4Network, left4.network))
        seen_v6.add(t.cast(ipaddress.IPv6Network, left6.network))
        core_v4_addresses.update(
            (
                t.cast(ipaddress.IPv4Address, left4.ip),
                t.cast(ipaddress.IPv4Address, right4.ip),
            )
        )
        core_v6_addresses.update(
            (
                t.cast(ipaddress.IPv6Address, left6.ip),
                t.cast(ipaddress.IPv6Address, right6.ip),
            )
        )
    router_ids = {
        ipaddress.IPv4Address(r1.router_id),
        ipaddress.IPv4Address(r2.router_id),
    }
    if router_ids & core_v4_addresses or any(
        router_id in network for router_id in router_ids for network in seen_v4
    ):
        raise ValueError("router IDs must be outside every core RIF subnet")
    loopbacks_and_sources = {
        ipaddress.IPv6Address(value.split("/", 1)[0])
        for value in (
            r1.loopback_v6,
            r2.loopback_v6,
            r1.srv6_source_a,
            r1.srv6_source_b,
            r2.srv6_source_a,
            r2.srv6_source_b,
        )
    }
    if len(loopbacks_and_sources) != 6:
        raise ValueError("loopback and SRv6 source addresses must all differ")
    if loopbacks_and_sources & core_v6_addresses:
        raise ValueError("loopback/SRv6 source addresses must not duplicate core RIFs")
    locator = ipaddress.ip_network(C.SRV6_LOCATOR, strict=False)
    if locator.version != 6:
        raise ValueError("SRv6 locator must be IPv6")
    tail_prefix = ipaddress.ip_network(C.TAIL_DEST_PREFIX, strict=True)
    if tail_prefix.version != 6:
        raise ValueError("the SRv6 tail prefix must be IPv6")
    if locator.overlaps(tail_prefix):
        raise ValueError("SRv6 locator and tail destination prefix must not overlap")
    if any(locator.overlaps(network) for network in seen_v6):
        raise ValueError("SRv6 locator must not overlap a core RIF subnet")
    if any(tail_prefix.overlaps(network) for network in seen_v6):
        raise ValueError("tail destination prefix must not overlap a core RIF subnet")
    if any(address in locator for address in loopbacks_and_sources):
        raise ValueError("loopback/SRv6 source addresses must be outside the locator")
    if any(address in tail_prefix for address in loopbacks_and_sources):
        raise ValueError(
            "loopback/SRv6 source addresses must be outside the tail prefix"
        )

    usid_addresses = {
        ipaddress.IPv6Address(
            _address(sid, family=6, label=f"SRv6 {name} uSID")
        )
        for name, sid in (
            ("head", C.SRV6_USID_HEAD),
            ("mid", C.SRV6_USID_MID),
            ("decap", C.SRV6_DECAP_SID),
        )
    }
    functions = {
        _usid_function(C.SRV6_LOCATOR, sid, label=f"SRv6 {name} uSID")
        for name, sid in (
            ("head", C.SRV6_USID_HEAD),
            ("mid", C.SRV6_USID_MID),
            ("decap", C.SRV6_DECAP_SID),
        )
    }
    if len(functions) != 3:
        raise ValueError("SRv6 head, midpoint, and decap uSID functions must differ")
    if usid_addresses & loopbacks_and_sources:
        raise ValueError("uSIDs must not duplicate loopback/SRv6 source addresses")


def _usid_function(locator: str, sid: str, *, label: str) -> int:
    try:
        network = ipaddress.ip_network(locator, strict=False)
        address = ipaddress.ip_address(sid.split("/", 1)[0])
    except ValueError as exc:
        raise ValueError(f"{label} or locator is invalid") from exc
    if network.version != 6 or network.prefixlen % 16 or network.prefixlen > 112:
        raise ValueError("SRv6 locator must be IPv6 and 16-bit aligned")
    if address.version != 6 or address not in network:
        raise ValueError(f"{label} must be inside locator {network}")
    shift = 128 - network.prefixlen - 16
    function = (int(address) >> shift) & 0xFFFF
    trailing_mask = (1 << shift) - 1 if shift else 0
    if function == 0 or function > 0x7FFF or int(address) & trailing_mask:
        raise ValueError(
            f"{label} must contain one positive i16 function after the locator"
        )
    return function


def _indexed(items: t.Any, key: str, *, label: str) -> t.Dict[t.Any, t.Dict[str, t.Any]]:
    if not isinstance(items, list):
        raise ValueError(f"AgentConfig sw.{label} must be a list")
    result: t.Dict[t.Any, t.Dict[str, t.Any]] = {}
    for item in items:
        if not isinstance(item, dict) or key not in item:
            raise ValueError(f"AgentConfig sw.{label} contains an invalid entry")
        value = item[key]
        if value in result:
            raise ValueError(f"AgentConfig sw.{label} contains duplicate {key}={value!r}")
        result[value] = item
    return result


def _virtual_vlan(vlan_id: int, name: str, addresses: t.Sequence[str]) -> t.Dict[str, t.Any]:
    return {
        "id": vlan_id,
        "name": name,
        "recordStats": True,
        "routable": True,
        "ipAddresses": list(addresses),
    }


def _virtual_interface(
    intf_id: int, addresses: t.Sequence[str], *, is_virtual: bool
) -> t.Dict[str, t.Any]:
    return {
        "intfID": intf_id,
        "routerID": 0,
        "vlanID": intf_id,
        "ipAddresses": list(addresses),
        "mtu": 9000,
        "isVirtual": is_virtual,
        "isStateSyncDisabled": True,
        "type": 1,
        "scope": 0,
    }


def _replace_by_id(
    items: t.List[t.Dict[str, t.Any]], key: str, value: int, replacement: t.Dict[str, t.Any]
) -> None:
    matches = [index for index, item in enumerate(items) if item.get(key) == value]
    if len(matches) > 1:
        raise ValueError(f"AgentConfig contains duplicate {key}={value}")
    if matches:
        items[matches[0]] = replacement
    else:
        items.append(replacement)


def build_agent_config(
    base: t.Mapping[str, t.Any],
    *,
    role: str,
    core_pcs: t.Sequence[CorePortChannel],
    include_traffic: bool = False,
) -> t.Dict[str, t.Any]:
    """Patch only the RBB logical slice of an installed AgentConfig."""
    if not core_pcs:
        raise ValueError("bootstrap requires at least one core port-channel")
    if not isinstance(include_traffic, bool):
        raise ValueError("include_traffic must be a boolean")
    if not isinstance(base.get("platform"), dict) or not isinstance(
        base.get("defaultCommandLineArgs"), dict
    ):
        raise ValueError(
            "installed AgentConfig must contain platform and defaultCommandLineArgs"
        )
    cfg = copy.deepcopy(dict(base))
    sw = cfg.get("sw")
    if not isinstance(sw, dict):
        raise ValueError("installed AgentConfig must contain a sw object")
    ports = _indexed(sw.get("ports"), "name", label="ports")
    ports_by_id = _indexed(sw.get("ports"), "logicalID", label="ports")
    vlans = t.cast(t.List[t.Dict[str, t.Any]], sw.get("vlans"))
    interfaces = t.cast(t.List[t.Dict[str, t.Any]], sw.get("interfaces"))
    vlan_ports = t.cast(t.List[t.Dict[str, t.Any]], sw.get("vlanPorts"))
    vlan_by_id = _indexed(vlans, "id", label="vlans")
    interface_by_id = _indexed(interfaces, "intfID", label="interfaces")
    if not isinstance(vlan_ports, list) or any(
        not isinstance(entry, dict) for entry in vlan_ports
    ):
        raise ValueError("AgentConfig sw.vlanPorts must be a list of objects")
    virtual_ids = {C.LOOPBACK_VLAN, C.SRV6_SID_VLAN_A, C.SRV6_SID_VLAN_B}
    try:
        physical_vlans = {
            int(port.get("ingressVlan", -1)) for port in ports.values()
        }
    except (TypeError, ValueError) as exc:
        raise ValueError("installed AgentConfig contains an invalid ingressVlan") from exc
    if physical_vlans & virtual_ids:
        raise ValueError(
            "bootstrap virtual RIF IDs collide with an installed physical port VLAN"
        )
    if virtual_ids & set(vlan_by_id) or virtual_ids & set(interface_by_id):
        raise ValueError(
            "bootstrap virtual RIF IDs are already present; use the preconfigured "
            "workflow without --setup-duts"
        )
    if sw.get("mySidConfig"):
        raise ValueError(
            "installed AgentConfig already has MySID state; use the "
            "preconfigured workflow without --setup-duts"
        )
    plan = _node_plan(role, len(core_pcs))

    desired_aggregates: t.List[t.Dict[str, t.Any]] = []
    selected_ids: t.Set[int] = set()
    selected_vlans: t.Set[int] = set()
    desired_names: t.Set[str] = set()
    desired_keys: t.Set[int] = set()
    for index, pc in enumerate(core_pcs):
        if len(pc.members) != 1:
            raise ValueError(
                f"bootstrap requires exactly one member in {pc.name!r}; found {len(pc.members)}"
            )
        member_name = pc.members[0]
        port = ports.get(member_name)
        if port is None:
            raise ValueError(
                f"core member {member_name!r} is absent from installed AgentConfig; "
                "CSV interface names must use the device's exact spelling"
            )
        try:
            port_id = int(port["logicalID"])
            vlan_id = int(port["ingressVlan"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"core member {member_name!r} has no usable ID/VLAN") from exc
        if ports_by_id.get(port_id) is not port:
            raise ValueError(f"core member {member_name!r} has an ambiguous logicalID")
        port_type = port.get("portType")
        if (
            not isinstance(port_type, int)
            or isinstance(port_type, bool)
            or port_type != _INTERFACE_PORT
            or port.get("routable") is not True
        ):
            raise ValueError(
                f"core member {member_name!r} must be a routable FBOSS "
                "INTERFACE_PORT"
            )
        if not 1 <= vlan_id <= 4094:
            raise ValueError(
                f"core member {member_name!r} has invalid ingress VLAN {vlan_id}"
            )
        try:
            port_state = int(port["state"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                f"core member {member_name!r} has no usable administrative state"
            ) from exc
        if port_state not in (0, 1, _PORT_ENABLED):
            raise ValueError(
                f"core member {member_name!r} has unsupported state {port_state}"
            )
        if port_id in selected_ids or vlan_id in selected_vlans:
            raise ValueError("core members must resolve to distinct logical IDs and VLANs")
        selected_ids.add(port_id)
        selected_vlans.add(vlan_id)
        ingress_vlan_owners = [
            candidate
            for candidate in ports.values()
            if int(candidate.get("ingressVlan", -1)) == vlan_id
        ]
        if len(ingress_vlan_owners) != 1 or ingress_vlan_owners[0] is not port:
            raise ValueError(
                f"core member {member_name!r} has shared ingress VLAN {vlan_id}; "
                "bootstrap requires the stock one-port/one-RIF baseline"
            )
        vlan = vlan_by_id.get(vlan_id)
        interface = interface_by_id.get(vlan_id)
        if vlan is None or interface is None or int(interface.get("vlanID", -1)) != vlan_id:
            raise ValueError(
                f"core member {member_name!r} needs existing VLAN/interface {vlan_id}"
            )
        if vlan.get("ipAddresses") or interface.get("ipAddresses"):
            raise ValueError(
                f"core member {member_name!r} already has RIF addresses; use the "
                "preconfigured workflow without --setup-duts"
            )
        vlan_port_entries = [
            entry
            for entry in vlan_ports
            if int(entry.get("vlanID", -1)) == vlan_id
        ]
        if (
            len(vlan_port_entries) != 1
            or int(vlan_port_entries[0].get("logicalPort", -1)) != port_id
        ):
            raise ValueError(
                f"core member {member_name!r} needs exactly one matching "
                f"vlanPorts entry for VLAN {vlan_id}"
            )
        link_local = f"fe80::{vlan_id}:{1 if role == 'r1' else 2}/64"
        addresses = [plan.core_v4[index], plan.core_v6[index], link_local]
        port["state"] = _PORT_ENABLED
        vlan["ipAddresses"] = addresses
        interface["ipAddresses"] = addresses

        key = port_channel_key(pc.name)
        show_name = "Port-Channel" + str(key)
        if key in desired_keys or show_name.lower() in desired_names:
            raise ValueError(f"duplicate desired aggregate port {pc.name!r}")
        desired_keys.add(key)
        desired_names.add(show_name.lower())
        desired_aggregates.append(
            {
                "aggregatePortType": 0,
                "description": f"TAAC RBB core {show_name}",
                "extendedKey": 0,
                "key": key,
                "memberPorts": [
                    {
                        "activity": 1,
                        "holdTimerMultiplier": 3,
                        "memberPortID": port_id,
                        "priority": 32768,
                        "rate": 0,
                    }
                ],
                "minimumCapacity": {"linkPercentage": 0.65},
                "minimumCapacityToUp": {"linkPercentage": 0.75},
                "name": show_name,
            }
        )

    existing_aggregates = sw.get("aggregatePorts")
    if not isinstance(existing_aggregates, list):
        raise ValueError("AgentConfig sw.aggregatePorts must be a list")
    preserved_aggregates: t.List[t.Dict[str, t.Any]] = []
    for aggregate in existing_aggregates:
        if not isinstance(aggregate, dict):
            raise ValueError("AgentConfig sw.aggregatePorts contains an invalid entry")
        if not isinstance(aggregate.get("memberPorts", []), list) or any(
            not isinstance(member, dict)
            for member in aggregate.get("memberPorts", [])
        ):
            raise ValueError("AgentConfig aggregate port has invalid memberPorts")
        same_owned_slot = aggregate.get("key") in desired_keys or str(
            aggregate.get("name", "")
        ).lower() in desired_names
        member_ids = {
            member.get("memberPortID")
            for member in aggregate.get("memberPorts", [])
            if isinstance(member, dict)
        }
        if same_owned_slot or member_ids & selected_ids:
            raise ValueError(
                "a selected core port/aggregate key is already configured; use "
                "the preconfigured workflow without --setup-duts"
            )
        preserved_aggregates.append(aggregate)
    sw["aggregatePorts"] = preserved_aggregates + desired_aggregates

    loopback_addresses = [f"{plan.router_id}/32", f"{plan.loopback_v6}/128"]
    source_a = [plan.srv6_source_a]
    source_b = [plan.srv6_source_b]
    _replace_by_id(
        vlans,
        "id",
        C.LOOPBACK_VLAN,
        _virtual_vlan(C.LOOPBACK_VLAN, "Vlan4000", loopback_addresses),
    )
    _replace_by_id(
        interfaces,
        "intfID",
        C.LOOPBACK_VLAN,
        _virtual_interface(C.LOOPBACK_VLAN, loopback_addresses, is_virtual=False),
    )
    for vlan_id, name, addresses in (
        (C.SRV6_SID_VLAN_A, "fbossLoopback0", source_a),
        (C.SRV6_SID_VLAN_B, "fbossLoopback1", source_b),
    ):
        _replace_by_id(vlans, "id", vlan_id, _virtual_vlan(vlan_id, name, addresses))
        _replace_by_id(
            interfaces,
            "intfID",
            vlan_id,
            _virtual_interface(vlan_id, addresses, is_virtual=True),
        )

    adjacency_index = 0 if role == "r1" else len(core_pcs) - 1
    adjacency_sid = C.SRV6_USID_HEAD if role == "r1" else C.SRV6_USID_MID
    entries: t.Dict[str, t.Any] = {
        str(_usid_function(C.SRV6_LOCATOR, adjacency_sid, label=f"{role} adjacency uSID")): {
            "adjacency": {
                "isV6": True,
                "portName": desired_aggregates[adjacency_index]["name"],
                "address": str(
                    ipaddress.ip_interface(plan.peer_core_v6[adjacency_index]).ip
                ),
            }
        }
    }
    if role == "r2":
        entries[
            str(
                _usid_function(
                    C.SRV6_LOCATOR, C.SRV6_DECAP_SID, label="r2 decap uSID"
                )
            )
        ] = {"decap": {}}
    sw["mySidConfig"] = {
        "locatorPrefix": str(ipaddress.ip_network(C.SRV6_LOCATOR, strict=False)),
        "entries": entries,
    }

    desired_tunnel = {
        "srv6TunnelId": C.SRV6_TUNNEL_ID,
        # FBOSS expects an InterfaceID here, not a physical PortID. The tunnel
        # source address is owned by the virtual source RIF created above.
        "underlayIntfID": C.SRV6_SID_VLAN_B,
        "srcIp": str(ipaddress.ip_interface(plan.srv6_source_b).ip),
        "tunnelTermType": 2,
        "tunnelType": 1,
        "ttlMode": 0,
        "dscpMode": 0,
        "ecnMode": 0,
    }
    tunnels = sw.get("srv6Tunnels", [])
    if not isinstance(tunnels, list) or any(
        not isinstance(tunnel, dict) for tunnel in tunnels
    ):
        raise ValueError("AgentConfig sw.srv6Tunnels must be a list of objects")
    if any(tunnel.get("srv6TunnelId") == C.SRV6_TUNNEL_ID for tunnel in tunnels):
        raise ValueError(
            f"SRv6 tunnel {C.SRV6_TUNNEL_ID!r} already exists; use the "
            "preconfigured workflow without --setup-duts"
        )
    sw["srv6Tunnels"] = tunnels + [desired_tunnel]

    route_prefix: t.Optional[str] = None
    route_nh: t.Optional[str] = None
    if role == "r1":
        route_prefix = str(ipaddress.ip_network(C.SRV6_LOCATOR, strict=False))
        route_nh = str(ipaddress.ip_interface(plan.peer_core_v6[0]).ip)
    elif include_traffic:
        # Only live IXIA traffic needs R2's ordinary return path to the R1
        # source edge. Device-only SRv6 validation does not install it.
        route_prefix = str(
            ipaddress.ip_network(
                f"{C.IXIA_R1_EDGE_V6}/{C.IXIA_EDGE_PREFIX_MASK}", strict=False
            )
        )
        route_nh = str(ipaddress.ip_interface(plan.peer_core_v6[0]).ip)
    routes = sw.get("staticRoutesWithNhops", [])
    if not isinstance(routes, list) or any(
        not isinstance(route, dict) for route in routes
    ):
        raise ValueError(
            "AgentConfig sw.staticRoutesWithNhops must be a list of objects"
        )
    if route_prefix is not None and route_nh is not None:
        route_collision = False
        for route in routes:
            existing_prefix = route.get("prefix")
            if not isinstance(existing_prefix, str):
                raise ValueError("AgentConfig static route is missing a string prefix")
            try:
                route_collision = (
                    ipaddress.ip_network(existing_prefix, strict=False)
                    == ipaddress.ip_network(route_prefix, strict=False)
                )
            except ValueError as exc:
                raise ValueError(
                    f"AgentConfig contains an invalid static route {existing_prefix!r}"
                ) from exc
            if route_collision:
                break
        if route_collision:
            raise ValueError(
                f"static route {route_prefix!r} already exists; use the "
                "preconfigured workflow without --setup-duts"
            )
        sw["staticRoutesWithNhops"] = routes + [
            {"routerID": 0, "prefix": route_prefix, "nexthops": [route_nh]}
        ]
    return cfg


def build_bgp_config(
    base: t.Mapping[str, t.Any],
    *,
    role: str,
    core_count: int,
    originate_tail_prefix: bool = False,
) -> t.Dict[str, t.Any]:
    """Converge the image's placeholder bgp.json to one loopback iBGP peer."""
    cfg = copy.deepcopy(dict(base))
    plan = _node_plan(role, core_count)
    if cfg.get("router_id") != "REPLACE_ROUTER_ID":
        raise ValueError(
            "installed bgp.json is not the fresh-image placeholder; use the "
            "preconfigured workflow without --setup-duts"
        )
    if not 1 <= C.CORE_IBGP_AS <= 0xFFFFFFFF:
        raise ValueError("TAAC_RBB_CORE_AS must be in 1..4294967295")
    if not isinstance(cfg.get("net_service_config"), dict):
        raise ValueError("installed bgp.json needs a net_service_config object")
    for field in ("peer_groups", "peers", "networks4", "networks6"):
        value = cfg.get(field)
        if not isinstance(value, list):
            raise ValueError(f"installed bgp.json field {field!r} must be a list")
        if value:
            raise ValueError(
                "installed bgp.json already contains routing state; use the "
                "preconfigured workflow without --setup-duts"
            )
    networks6 = [{"prefix": f"{plan.loopback_v6}/128"}]
    if originate_tail_prefix:
        if role != "r2":
            raise ValueError("only R2 may originate the device-only tail prefix")
        networks6.append(
            {
                "prefix": str(ipaddress.ip_network(C.TAIL_DEST_PREFIX, strict=True)),
                "nexthop": _address(
                    C.SRV6_DECAP_SID, family=6, label="R2 decap next hop"
                ),
                "install_to_fib": False,
            }
        )
    cfg.update(
        {
            "router_id": plan.router_id,
            "local_as_4_byte": C.CORE_IBGP_AS,
            "networks4": [{"prefix": f"{plan.router_id}/32"}],
            "networks6": networks6,
            "peer_groups": [
                {
                    "bgp_peer_timers": {
                        "hold_time_seconds": 30,
                        "keep_alive_seconds": 10,
                        "out_delay_seconds": 3,
                    },
                    "disable_ipv4_afi": False,
                    "disable_ipv6_afi": False,
                    "name": _IBGP_PEER_GROUP,
                    # Preserve the non-zero decap next hop of the synthetic
                    # device-only tail route. Zero-next-hop local loopbacks
                    # still use the peer's configured next_hop6.
                    "next_hop_self": not originate_tail_prefix,
                    "remote_as_4_byte": C.CORE_IBGP_AS,
                    "v4_over_v6_nexthop": False,
                }
            ],
            "peers": [
                {
                    "description": "TAAC RBB loopback iBGP peer",
                    "local_addr": plan.router_id,
                    "next_hop4": plan.router_id,
                    "next_hop6": plan.loopback_v6,
                    "peer_addr": plan.peer_router_id,
                    "peer_group_name": _IBGP_PEER_GROUP,
                    "peer_id": "rbb-loopback-ibgp-peer",
                    "remote_as_4_byte": C.CORE_IBGP_AS,
                }
            ],
        }
    )
    return cfg


def build_openr_config(
    base: t.Mapping[str, t.Any],
    *,
    role: str,
    core_interface_ids: t.Sequence[int],
) -> t.Dict[str, t.Any]:
    """Patch the image's OpenR defaults with exact generated FBOSS RIF names."""
    cfg = copy.deepcopy(dict(base))
    if cfg.get("node_name") != "REPLACE_NODE_NAME":
        raise ValueError(
            "installed openr.conf is not the fresh-image placeholder; use the "
            "preconfigured workflow without --setup-duts"
        )
    areas = cfg.get("areas")
    if not isinstance(areas, list) or len(areas) != 1 or not isinstance(areas[0], dict):
        raise ValueError("installed openr.conf must contain exactly one area object")
    area = areas[0]
    area_id = area.get("area_id")
    if not isinstance(area_id, str) or not area_id:
        raise ValueError("installed openr.conf area_id must be a non-empty string")
    redistribute = area.get("redistribute_interface_regexes")
    if not isinstance(redistribute, list) or not all(
        isinstance(pattern, str) for pattern in redistribute
    ):
        raise ValueError(
            "installed openr.conf redistribute_interface_regexes must be a "
            "list of strings"
        )
    loopback_pattern = f"^fboss{C.LOOPBACK_VLAN}$"
    area.update(
        {
            "area_id": area_id,
            "neighbor_regexes": [".*"],
            "include_interface_regexes": [
                f"^fboss{interface_id}$" for interface_id in core_interface_ids
            ],
            "exclude_interface_regexes": [],
            "redistribute_interface_regexes": list(
                dict.fromkeys([*redistribute, loopback_pattern])
            ),
        }
    )
    cfg.update(
        {
            "node_name": role,
            "enable_v4": True,
            "v4_over_v6_nexthop": True,
            "enable_netlink_fib_handler": False,
            "fib_port": 5909,
            "assume_drained": False,
        }
    )
    return cfg


def build_bootstrap_documents(
    *,
    base_agent: t.Mapping[str, t.Any],
    base_bgp: t.Mapping[str, t.Any],
    base_openr: t.Mapping[str, t.Any],
    role: str,
    core_pcs: t.Sequence[CorePortChannel],
    include_traffic: bool = False,
) -> BootstrapDocuments:
    """Build all changed documents; callers validate/write only after return."""
    if not isinstance(include_traffic, bool):
        raise ValueError("include_traffic must be a boolean")
    _validate_address_plan(len(core_pcs))
    agent = build_agent_config(
        base_agent,
        role=role,
        core_pcs=core_pcs,
        include_traffic=include_traffic,
    )
    ports_by_name = {
        str(port.get("name", "")): port for port in agent["sw"]["ports"]
    }
    core_interface_ids = [
        int(ports_by_name[pc.members[0]]["ingressVlan"]) for pc in core_pcs
    ]
    return BootstrapDocuments(
        agent=agent,
        bgp=build_bgp_config(
            base_bgp,
            role=role,
            core_count=len(core_pcs),
            originate_tail_prefix=role == "r2" and not include_traffic,
        ),
        openr=build_openr_config(
            base_openr, role=role, core_interface_ids=core_interface_ids
        ),
    )


__all__ = [
    "BootstrapDocuments",
    "build_agent_config",
    "build_bgp_config",
    "build_bootstrap_documents",
    "build_openr_config",
    "port_channel_key",
    "validate_bootstrap_device_paths",
    "validate_bootstrap_topology",
]
