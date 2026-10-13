#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""Typed config patchers for OSS, modelled on COOP's ``PythonPatchApplier``.

Each patcher has the name and signature of its COOP counterpart in
neteng/fboss/coop/configs/patchers.py -- ``(config, config_name, my_args) ->
config`` -- so a ``py_func_name`` means the same operation in either mode. That
module cannot be imported here (it pulls in configerator, netwhoami and Scuba),
so the bodies are ported, with two deliberate differences:

* Configs are immutable thrift-python structs, so a patcher returns a modified
  copy instead of editing its argument.
* Bad input raises ``PatcherError`` where COOP logs and skips. A skipped patcher
  leaves the test running against a device that was never configured, which
  surfaces much later and far from its cause.

Patcher args arrive as strings (thrift ``map<string, string>``), so ``bool()`` on
one is always True; every patcher parses its own.
"""

from __future__ import annotations

import collections
import inspect
import ipaddress
import json
import logging
import typing as t

# @manual=//configerator/structs/neteng/fboss/bgp:bgp_config-python-types
# Same pin as config_modifiers: the OSS mirror target emits the same module.
from configerator.structs.neteng.fboss.bgp.bgp_config.thrift_types import (
    BgpConfig,
    BgpPeer,
    BgpPeerTimers,
    BgpSwitchLimitConfig,
    OverloadProtectionMode,
    PeerGroup,
    RouteLimit,
)
from configerator.structs.neteng.robotron.bgp_policy.thrift_types import BgpPolicies
from neteng.fboss.agent_config.thrift_types import AgentConfig
from neteng.fboss.bgp_attr.thrift_types import AddPath
from neteng.fboss.switch_config.thrift_types import (
    Interface,
    MinimumCapacity,
    Port,
    PortProfileID,
    PortSpeed,
    PortState,
    PortType,
    SpanningTreeState,
    StaticRouteWithNextHops,
    SwitchConfig,
    Vlan,
    VlanPort,
)
from taac.driver import oss_bgp_policy
from taac.driver.config_modifiers import (
    POLICY_PROPAGATE_IN,
    POLICY_PROPAGATE_OUT,
    POLICY_PROPAGATE_OUT_DRAIN,
)

logger: logging.Logger = logging.getLogger(__name__)

# The config type each patcher edits. Registration checks it, so a patcher sent
# to the wrong config fails at register time rather than mid-replay.
PATCHER_CONFIG_TYPES: t.Dict[str, type] = {
    "remove_bgp_peers": BgpConfig,
    "configure_bgp_switch_limit": BgpConfig,
    "configure_bgp_peer_group": BgpConfig,
    "add_peer_group_patcher": BgpConfig,
    "add_bgp_peers": BgpConfig,
    "configure_vlans": AgentConfig,
    "change_speed": AgentConfig,
    "change_port_admin_state": AgentConfig,
    "change_mtu": AgentConfig,
    "add_static_routes": AgentConfig,
    "add_bgp_policy_statement": BgpConfig,
    "add_bgp_policy_match_prefix_to_propagate_routes": BgpConfig,
    "drain_interface": BgpConfig,
    "set_port_channel_min_link_capacity": AgentConfig,
}

# Hardware whose /1 and /5 subports share a cage and so constrain each other's
# speed (COOP's _validate_51t_speed_change).
_HARDWARE_51T: t.FrozenSet[str] = frozenset(
    {
        "MONTBLANC",
        "MINIPACK3M",
        "MORGAN800CC",
        "MINIPACK3BA",
        "MINIPACK3BAM",
        "MINIPACK3N",
        "MINIPACK3NM",
    }
)
# 25.6T and 12.8T hardware with COOP adjacent-port / slot rules
# (_validate_25t_speed_change, _validate_12t_speed_change).
_HARDWARE_25T: t.FrozenSet[str] = frozenset(
    {"FUJI", "ELBERT", "DARWIN", "WEDGE400", "WEDGE400C"}
)
# Of those, the ones whose adjacent slots must change speed together.
_HARDWARE_25T_PAIRED: t.FrozenSet[str] = frozenset({"FUJI", "ELBERT"})
_HARDWARE_12T: t.FrozenSet[str] = frozenset({"MINIPACK", "YAMP"})
# Allowed (port, adjacent) speeds in Gbps on those, in either order.
_SUPPORTED_51T_SPEED_COMBINATIONS: t.FrozenSet[t.Tuple[int, int]] = frozenset(
    {(100, 100), (200, 200), (200, 400), (400, 400)}
)
_PORT_STATES: t.Dict[str, PortState] = {
    "enable": PortState.ENABLED,
    "disable": PortState.DISABLED,
}

_ROUTE_LIMIT_FIELDS: t.FrozenSet[str] = frozenset(
    {"max_routes", "warning_only", "warning_limit"}
)
_POLICY_HOLDER_KEYS: t.FrozenSet[str] = frozenset(
    {"peer_group_name", "ingress_policy_name", "egress_policy_name"}
)
_DEFAULT_MTU = 9000


class PatcherError(Exception):
    """A patcher's arguments do not describe a change it can make."""


def _is_true(value: t.Any) -> bool:
    return str(value).strip().lower() == "true"


def _coerce(value: t.Any) -> t.Any:
    """Best-guess type for a string arg when the target field is unset."""
    if isinstance(value, str):
        if value.lower() in ("true", "false"):
            return value.lower() == "true"
        if value.lstrip("-").isdigit():
            return int(value)
    return value


def _add_path(value: t.Any) -> AddPath:
    """COOP accepts either the AddPath name ("BOTH") or its value ("3")."""
    text = str(value).strip().upper()
    try:
        return AddPath(int(text)) if text.isdigit() else AddPath[text]
    except (KeyError, ValueError) as exc:
        raise PatcherError(f"unknown add_path {value!r}") from exc


def _with_field(struct: t.Any, key: str, raw: t.Any) -> t.Any:
    """Set one field from a string arg, converted to the type the field holds.

    COOP's ``_patch_object_attribute`` rule, except that an unset optional field
    is set (best-guess type, falling back to the string) rather than skipped,
    and an unknown field raises.
    """
    if not hasattr(struct, key):
        raise PatcherError(f"{type(struct).__name__} has no field {key!r}")
    current = getattr(struct, key)
    try:
        if isinstance(current, bool):
            candidates = [_is_true(raw)]
        elif isinstance(current, int):
            candidates = [int(raw)]
        elif isinstance(current, str):
            candidates = [str(raw)]
        else:
            candidates = [_coerce(raw), str(raw)]
    except ValueError as exc:
        raise PatcherError(
            f"{type(struct).__name__}.{key} cannot hold {raw!r}"
        ) from exc
    for value in candidates:
        try:
            return struct(**{key: value})
        except TypeError:
            continue
    raise PatcherError(f"{type(struct).__name__}.{key} cannot hold {raw!r}")


def _upsert_by_name(items: t.Iterable[t.Any], item: t.Any) -> t.List[t.Any]:
    """Replace the entry named like ``item`` in place, or append it.

    Replace rather than append so a name never appears twice -- whether the
    baseline already carries it or the same patcher is replayed.
    """
    result = list(items)
    for i, existing in enumerate(result):
        if existing.name == item.name:
            result[i] = item
            return result
    result.append(item)
    return result


def _merge(existing: t.Iterable[str], new: t.Iterable[str]) -> t.List[str]:
    existing = list(existing)
    return existing + [a for a in new if a not in existing]


def _bgp_peer(
    spec: t.Mapping[str, t.Any], local_addr: str, peer_addr: str, remote_as: int
) -> BgpPeer:
    if not _POLICY_HOLDER_KEYS & spec.keys():
        raise PatcherError(
            f"peer {peer_addr} needs one of {sorted(_POLICY_HOLDER_KEYS)}, "
            "or it inherits no policy at all"
        )
    is_v6 = ipaddress.ip_address(local_addr).version == 6
    return BgpPeer(
        remote_as_4_byte=remote_as,
        local_addr=local_addr,
        peer_addr=peer_addr,
        next_hop4="0.0.0.0" if is_v6 else local_addr,
        next_hop6=local_addr if is_v6 else "::",
        description=spec.get("description", ""),
        peer_id=peer_addr,
        peer_group_name=spec.get("peer_group_name"),
        ingress_policy_name=spec.get("ingress_policy_name"),
        egress_policy_name=spec.get("egress_policy_name"),
    )


def _peer_on(
    peer: BgpPeer,
    networks: t.Sequence[t.Union[ipaddress.IPv4Network, ipaddress.IPv6Network]],
) -> bool:
    try:
        addr = ipaddress.ip_address(peer.peer_addr)
    except ValueError:
        # A prefix spec (passive listener), not a session on one address.
        return False
    return any(addr in network for network in networks)


def _session_peers(spec: t.Mapping[str, t.Any]) -> t.Iterator[BgpPeer]:
    """Expand a per-interface session spec into ``num_sessions`` peers."""
    local = ipaddress.ip_address(spec["starting_ip"])
    remote = ipaddress.ip_address(spec["gateway_starting_ip"])
    local_step = int(ipaddress.ip_address(spec.get("increment_ip", "::")))
    remote_step = int(
        ipaddress.ip_address(
            spec.get("gateway_increment_ip", spec.get("increment_ip", "::"))
        )
    )
    remote_as = int(spec["remote_as_4_byte"])
    as_step = int(spec.get("remote_as_4_byte_step", 0))
    for n in range(int(spec["num_sessions"])):
        yield _bgp_peer(spec, str(local), str(remote), remote_as + as_step * n)
        local += local_step
        remote += remote_step


def _merge_vlan_interface(
    sw: SwitchConfig,
    name: str,
    vlan_id: int,
    addresses: t.List[str],
    mtu: t.Optional[int],
    replace: bool = False,
) -> SwitchConfig:
    interfaces = list(sw.interfaces)
    matched = False
    for i, intf in enumerate(interfaces):
        if intf.vlanID == vlan_id:
            interfaces[i] = intf(
                ipAddresses=addresses
                if replace
                else _merge(intf.ipAddresses, addresses),
                mtu=intf.mtu if mtu is None else mtu,
            )
            matched = True
    if not matched:
        interfaces.append(
            Interface(
                intfID=vlan_id,
                vlanID=vlan_id,
                name=name,
                ipAddresses=addresses,
                mtu=_DEFAULT_MTU if mtu is None else mtu,
            )
        )
    return sw(interfaces=interfaces)


def _merge_vlan(
    sw: SwitchConfig,
    name: str,
    vlan_id: int,
    addresses: t.List[str],
    replace: bool = False,
) -> SwitchConfig:
    hosts = [a.split("/")[0] for a in addresses]
    vlans = list(sw.vlans)
    for i, vlan in enumerate(vlans):
        if vlan.id == vlan_id:
            vlans[i] = vlan(
                ipAddresses=hosts if replace else _merge(vlan.ipAddresses, hosts)
            )
            return sw(vlans=vlans)
    vlans.append(
        Vlan(name=name, id=vlan_id, intfID=vlan_id, routable=True, ipAddresses=hosts)
    )
    return sw(vlans=vlans)


def _move_ports_to_vlan(
    sw: SwitchConfig, vlan_id: int, port_ids: t.List[int]
) -> SwitchConfig:
    """Put each port (by logicalID) in ``vlan_id``, and only there."""
    if not port_ids:
        return sw
    known = {p.logicalID for p in sw.ports}
    missing = [p for p in port_ids if p not in known]
    if missing:
        raise PatcherError(f"no port with logicalID {missing} in agent config")
    wanted = set(port_ids)
    ports = [p(ingressVlan=vlan_id) if p.logicalID in wanted else p for p in sw.ports]
    # A trunk port has several memberships; it keeps exactly one, in vlan_id.
    # The agent rejects a config listing a port twice in one VLAN.
    vlan_ports = []
    seen = set()
    for vlan_port in sw.vlanPorts:
        if vlan_port.logicalPort in wanted:
            if vlan_port.logicalPort in seen:
                continue
            vlan_port = vlan_port(vlanID=vlan_id)
            seen.add(vlan_port.logicalPort)
        vlan_ports.append(vlan_port)
    vlan_ports += [
        VlanPort(
            vlanID=vlan_id,
            logicalPort=port_id,
            spanningTreeState=SpanningTreeState.FORWARDING,
            emitTags=False,
        )
        for port_id in port_ids
        if port_id not in seen
    ]
    return sw(ports=ports, vlanPorts=vlan_ports)


def _value(enum_member: t.Any) -> int:
    """An enum's integer value, whichever thrift flavour produced it: the agent
    client may return py3 structs, whose enums are not the thrift-python ones."""
    return enum_member.value if hasattr(enum_member, "value") else int(enum_member)


def _profile_config(entry: t.Any, profile: PortProfileID) -> t.Any:
    for supported, port_config in entry.supportedProfiles.items():
        if _value(supported) == profile.value:
            return port_config
    return None


def _wire(platform_mapping: t.Any, profile_value: int) -> t.Optional[t.Tuple[int, ...]]:
    """What a profile puts on the wire: speed, lanes, modulation, FEC."""
    for entry in platform_mapping.platformSupportedProfiles or []:
        if _value(entry.factor.profileID) == profile_value:
            iphy = entry.profile.iphy
            return (
                _value(entry.profile.speed),
                iphy.numLanes,
                _value(iphy.modulation),
                _value(iphy.fec),
            )
    return None


def _fit_profile(
    entry: t.Any, profile: PortProfileID, platform_mapping: t.Any
) -> t.Optional[PortProfileID]:
    """The requested profile if the port offers it, as in COOP. Otherwise the
    one profile it offers that is wire-identical: media families are assigned
    per cage, so the two ends of a mixed optical/copper link need different ids
    for the same signal (e.g. 23 vs 22 at 100G), and the speed-flip step passes
    one id per platform and speed. None when there is no unique such profile."""
    if _profile_config(entry, profile) is not None:
        return profile
    want = _wire(platform_mapping, profile.value)
    if want is None:
        return None
    candidates = [
        _value(offered)
        for offered in entry.supportedProfiles
        if _wire(platform_mapping, _value(offered)) == want
    ]
    return PortProfileID(candidates[0]) if len(candidates) == 1 else None


def _51t_adjacent_port(port_name: str) -> str:
    parts = port_name.split("/")
    if len(parts) != 3:
        return ""
    adjacent = {"1": "5", "5": "1"}.get(parts[2])
    return f"{parts[0]}/{parts[1]}/{adjacent}" if adjacent else ""


def _25t_adjacent_port(port_name: str) -> str:
    """FUJI/ELBERT pair odd and even slots: ethX/3/1 with ethX/4/1."""
    parts = port_name.split("/")
    if len(parts) != 3 or not parts[1].isdigit():
        return ""
    slot = int(parts[1])
    return f"{parts[0]}/{slot - 1 if slot % 2 == 0 else slot + 1}/{parts[2]}"


def _slot(port_name: str) -> t.Optional[int]:
    parts = port_name.split("/")
    return int(parts[1]) if len(parts) == 3 and parts[1].isdigit() else None


def _cage(port_name: str) -> str:
    return port_name.rsplit("/", 1)[0]


def _vlan_for(sw: SwitchConfig, logical_id: int, taken: t.Set[int]) -> int:
    """A VLAN ID for a port that gets its own: the config's numbering when every
    such port's VLAN is its logicalID plus one offset (e.g. 2000 + id),
    otherwise the next ID above theirs."""
    users = collections.Counter(p.ingressVlan for p in sw.ports)
    own = [p for p in sw.ports if users[p.ingressVlan] == 1]
    offsets = {p.ingressVlan - p.logicalID for p in own}
    if len(offsets) == 1:
        vlan_id = offsets.pop() + logical_id
        if vlan_id not in taken:
            return vlan_id
    vlan_id = max((p.ingressVlan for p in own), default=sw.defaultVlan) + 1
    while vlan_id in taken:
        vlan_id += 1
    return vlan_id


def _new_port(
    template: t.Optional[Port],
    entry: t.Any,
    vlan_id: int,
    speed: PortSpeed,
    profile: PortProfileID,
) -> Port:
    """A named port the config lacks, e.g. a /5 that its adjacent /1 subsumed in the
    baseline. It takes every setting from its adjacent port except the ones tied to
    its own link, which are left unset -- in COOP-generated configs those are
    the only settings that differ between a /1 and its /5."""
    fields: t.Dict[str, t.Any] = {
        "logicalID": entry.mapping.id,
        "name": entry.mapping.name,
        "ingressVlan": vlan_id,
        "speed": speed,
        "profileID": profile,
        "state": PortState.ENABLED,
    }
    if template is None:
        return Port(**fields)
    blank = Port()
    for reset in ("description", "expectedLLDPValues", "expectedNeighborReachability"):
        fields[reset] = getattr(blank, reset)
    return template(**fields)


def _add_missing_ports(
    sw: SwitchConfig,
    entries: t.Mapping[str, t.Any],
    intfs: t.Sequence[str],
    speed: PortSpeed,
    profiles: t.Mapping[str, PortProfileID],
) -> SwitchConfig:
    """Create the named ports the config lacks, placed like their adjacent port:

    * adjacent port in a VLAN shared with other ports (e.g. an RSW's server downlinks):
      the same VLAN, whose interface serves it too.
    * adjacent port in its own VLAN with an L3 interface (point-to-point links): a VLAN
      named ``vlan<ID>`` and an interface without addresses, as COOP generates
      for an unused port of that kind.
    * otherwise (adjacent port unused in the default VLAN, or none): the default
      VLAN with no interface.
    """
    present = {p.name for p in sw.ports}
    missing = [name for name in intfs if name not in present]
    if not missing:
        return sw
    users = collections.Counter(p.ingressVlan for p in sw.ports)
    intf_by_vlan = {i.vlanID: i for i in sw.interfaces}
    taken = {v.id for v in sw.vlans} | {sw.defaultVlan}
    ports, vlans = list(sw.ports), list(sw.vlans)
    vlan_ports, interfaces = list(sw.vlanPorts), list(sw.interfaces)
    for name in missing:
        entry = entries[name]
        adjacent = next(
            (p for p in sw.ports if _cage(p.name or "") == _cage(name)), None
        )
        adjacent_vlan = adjacent.ingressVlan if adjacent is not None else sw.defaultVlan
        adjacent_intf = intf_by_vlan.get(adjacent_vlan)
        if adjacent_vlan != sw.defaultVlan and users[adjacent_vlan] > 1:
            vlan_id = adjacent_vlan
        elif adjacent_vlan != sw.defaultVlan and adjacent_intf is not None:
            vlan_id = _vlan_for(sw, entry.mapping.id, taken)
            taken.add(vlan_id)
            vlans.append(
                Vlan(name=f"vlan{vlan_id}", id=vlan_id, routable=True, recordStats=True)
            )
            intf_fields: t.Dict[str, t.Any] = {
                k: getattr(adjacent_intf, k)
                for k in (
                    "mtu",
                    "type",
                    "routerID",
                    "scope",
                    "isVirtual",
                    "isStateSyncDisabled",
                )
            }
            interfaces.append(
                Interface(intfID=vlan_id, vlanID=vlan_id, ipAddresses=[], **intf_fields)
            )
        else:
            vlan_id = sw.defaultVlan
            if vlan_id not in {v.id for v in vlans}:
                vlans.append(Vlan(name="default", id=vlan_id, routable=False))
        ports.append(_new_port(adjacent, entry, vlan_id, speed, profiles[name]))
        vlan_ports.append(
            VlanPort(
                vlanID=vlan_id,
                logicalPort=entry.mapping.id,
                spanningTreeState=SpanningTreeState.FORWARDING,
                emitTags=False,
            )
        )
        logger.info(f"change_speed: added {name} in VLAN {vlan_id}")
    return sw(ports=ports, vlans=vlans, vlanPorts=vlan_ports, interfaces=interfaces)


def _remove_subsumed_ports(sw: SwitchConfig, platform_mapping: t.Any) -> SwitchConfig:
    """COOP's remove_subsumed_ports: drop every port an active profile subsumes
    (the platform mapping lists them per profile), its VLAN memberships, and the
    interfaces of VLANs that lose their last port."""
    subsumed: t.Set[int] = set()
    port_vlans: t.Set[int] = set()
    for port in sw.ports:
        entry = platform_mapping.ports.get(port.logicalID)
        if entry is None:
            if port.portType == PortType.FABRIC_PORT:
                # Fabric ports may be relocated outside the platform mapping's
                # id range; they neither subsume nor are subsumed.
                continue
            raise PatcherError(
                f"change_speed: port {port.logicalID} not in platform mapping"
            )
        port_config = _profile_config(entry, port.profileID)
        if port_config is None:
            raise PatcherError(
                f"change_speed: port {port.logicalID} has unsupported profile "
                f"{port.profileID!r}"
            )
        port_vlans.add(port.ingressVlan)
        if (
            port_config.subsumedPorts is not None
            and port.portType != PortType.HYPER_PORT
        ):
            subsumed |= set(port_config.subsumedPorts)
    if not subsumed & {p.logicalID for p in sw.ports}:
        return sw

    ports = [p for p in sw.ports if p.logicalID not in subsumed]
    vlan_ports = [vp for vp in sw.vlanPorts if vp.logicalPort not in subsumed]
    all_vlans = {v.id for v in sw.vlans}
    empty_vlans = {v.id for v in sw.vlans} - port_vlans | {sw.defaultVlan}
    # A surviving port's tagged membership keeps its VLAN (and interface) too.
    keep_vlans = (
        empty_vlans | {p.ingressVlan for p in ports} | {vp.vlanID for vp in vlan_ports}
    )
    logger.info(
        "change_speed: removed subsumed ports "
        f"{sorted(p.name or str(p.logicalID) for p in sw.ports if p.logicalID in subsumed)}"
    )
    return sw(
        ports=ports,
        vlans=[v for v in sw.vlans if v.id in keep_vlans],
        vlanPorts=vlan_ports,
        interfaces=[
            i
            for i in sw.interfaces
            if i.vlanID in keep_vlans
            or (i.vlanID not in all_vlans and i.portID not in subsumed)
        ],
    )


class PatcherInputs(t.Protocol):
    """Device facts a patcher reads beyond its config, as COOP's ``_input``."""

    async def platform_mapping(self) -> t.Any: ...

    def hardware(self) -> t.Optional[str]: ...


class OssPatchApplier:
    def __init__(
        self,
        logger: logging.Logger = logger,
        inputs: t.Optional[PatcherInputs] = None,
    ) -> None:
        self.logger = logger
        self.inputs = inputs

    async def async_apply(
        self,
        config: t.Any,
        config_name: str,
        py_func_name: str,
        my_args: t.Mapping[str, t.Any],
    ) -> t.Any:
        """Run one patcher by name, as COOP's ``apply_python_patcher`` does."""
        if py_func_name not in PATCHER_CONFIG_TYPES:
            raise NotImplementedError(
                f"oss-patcher: {py_func_name!r} is not ported to OSS "
                f"(supported: {sorted(PATCHER_CONFIG_TYPES)})"
            )
        result = getattr(self, py_func_name)(config, config_name, dict(my_args))
        if inspect.isawaitable(result):
            result = await result
        return result

    def remove_bgp_peers(
        self, config: BgpConfig, config_name: str, my_args: t.Dict[str, t.Any]
    ) -> BgpConfig:
        """Remove BGP peers.

        ``delete_all`` drops every peer and ``peer_addrs`` (a JSON list) drops
        those peers. Otherwise COOP's filter applies: ``v4_only``/``v6_only``
        keep only peers of that address family, peers whose ``type`` names a
        BGP_* session (e.g. BGP monitor) are always kept, and with neither flag
        every other peer goes.
        """
        if _is_true(my_args.get("delete_all", "")):
            return config(peers=[])
        if "peer_addrs" in my_args:
            drop = set(json.loads(my_args["peer_addrs"]))
            return config(peers=[p for p in config.peers if p.peer_addr not in drop])

        v4_only = _is_true(my_args.get("v4_only", ""))
        v6_only = _is_true(my_args.get("v6_only", ""))

        def keep(peer: BgpPeer) -> bool:
            version = ipaddress.ip_network(peer.peer_addr, strict=False).version
            return (
                (v4_only and version == 4)
                or (v6_only and version == 6)
                or (peer.type is not None and "BGP_" in peer.type)
            )

        return config(peers=[p for p in config.peers if keep(p)])

    def configure_bgp_switch_limit(
        self, config: BgpConfig, config_name: str, my_args: t.Dict[str, t.Any]
    ) -> BgpConfig:
        """Replace the switch-level path/route limits with the ones given."""
        limits: t.Dict[str, t.Any] = {
            key: int(my_args[key])
            for key in (
                "ingress_path_limit",
                "prefix_limit",
                "total_path_limit",
                "max_golden_vips",
            )
            if my_args.get(key)
        }
        if my_args.get("overload_protection_mode"):
            limits["overload_protection_mode"] = OverloadProtectionMode(
                int(my_args["overload_protection_mode"])
            )
        return config(switch_limit_config=BgpSwitchLimitConfig(**limits))

    def configure_bgp_peer_group(
        self, config: BgpConfig, config_name: str, my_args: t.Dict[str, t.Any]
    ) -> BgpConfig:
        """Update an existing peer group's fields in place.

        ``attributes_to_update_json`` maps field names to values. The RouteLimit
        fields (``max_routes`` etc.) land in the group's ``pre_filter``, which
        COOP's generic setter cannot reach. A group that does not exist is left
        alone, as COOP does: inventing one would leave peers on an empty policy.
        """
        name = my_args["name"]
        groups = list(config.peer_groups or [])
        index = next((i for i, g in enumerate(groups) if g.name == name), None)
        if index is None:
            self.logger.warning(f"peer group {name} not in BgpConfig; update skipped")
            return config

        group = groups[index]
        updates = json.loads(my_args.get("attributes_to_update_json", "{}"))
        pre_filter = group.pre_filter or RouteLimit()
        for key, value in updates.items():
            if key == "add_path":
                group = group(add_path=_add_path(value))
            elif key in _ROUTE_LIMIT_FIELDS:
                pre_filter = _with_field(pre_filter, key, value)
                group = group(pre_filter=pre_filter)
            else:
                group = _with_field(group, key, value)
        groups[index] = group
        return config(peer_groups=groups)

    def add_peer_group_patcher(
        self, config: BgpConfig, config_name: str, my_args: t.Dict[str, t.Any]
    ) -> BgpConfig:
        """Create a peer group from COOP's flat kwargs, replacing one of that name.

        COOP requires every kwarg; absent ones take the defaults below instead.
        """
        timers = BgpPeerTimers(
            hold_time_seconds=int(my_args.get("bgp_peer_timers_hold_time_seconds", 30)),
            keep_alive_seconds=int(
                my_args.get("bgp_peer_timers_keep_alive_seconds", 10)
            ),
            out_delay_seconds=int(my_args.get("bgp_peer_timers_out_delay_seconds", 0)),
            withdraw_unprog_delay_seconds=int(
                my_args.get("bgp_peer_timers_withdraw_unprog_delay_seconds", 0)
            ),
        )
        group = PeerGroup(
            name=my_args["name"],
            description=my_args.get("description", ""),
            next_hop_self=_is_true(my_args.get("next_hop_self", "True")),
            disable_ipv4_afi=_is_true(my_args.get("disable_ipv4_afi", "False")),
            disable_ipv6_afi=_is_true(my_args.get("disable_ipv6_afi", "False")),
            is_confed_peer=_is_true(my_args.get("is_confed_peer", "False")),
            is_passive=_is_true(my_args.get("is_passive", "False")),
            v4_over_v6_nexthop=_is_true(my_args.get("v4_over_v6_nexthop", "False")),
            ingress_policy_name=my_args.get("ingress_policy_name"),
            egress_policy_name=my_args.get("egress_policy_name"),
            peer_tag=my_args.get("peer_tag", ""),
            bgp_peer_timers=timers,
            pre_filter=RouteLimit(
                max_routes=int(my_args.get("max_routes", 45000)),
                warning_only=_is_true(my_args.get("warning_only", "True")),
                warning_limit=int(my_args.get("warning_limit", 0)),
            ),
            link_bandwidth_bps=my_args.get("link_bandwidth_bps"),
            add_path=_add_path(my_args["add_path"]) if "add_path" in my_args else None,
        )
        return config(peer_groups=_upsert_by_name(config.peer_groups or [], group))

    def add_bgp_peers(
        self, config: BgpConfig, config_name: str, my_args: t.Dict[str, t.Any]
    ) -> BgpConfig:
        """Append peers from ``peer_configs``.

        Accepts COOP's concrete peers (``local_addr``/``peer_addr``/...) and also
        per-interface session specs (``starting_ip``/``num_sessions``/...),
        optionally grouped in a dict, which OSS callers register directly.
        """
        specs = json.loads(my_args["peer_configs"])
        if isinstance(specs, dict):
            specs = [spec for group in specs.values() for spec in group]
        peers = list(config.peers)
        for spec in specs:
            if "local_addr" in spec:
                peers.append(
                    _bgp_peer(
                        spec,
                        spec["local_addr"],
                        spec["peer_addr"],
                        int(spec["remote_as_4_byte"]),
                    )
                )
            else:
                peers.extend(_session_peers(spec))
        return config(peers=peers)

    def configure_vlans(
        self, config: AgentConfig, config_name: str, my_args: t.Dict[str, t.Any]
    ) -> AgentConfig:
        """Configure VLAN interfaces: ``{vlan_name: json(spec)}``.

        Addresses are merged into an existing interface rather than replacing its
        list, because two ports on one VLAN arrive as two patchers and the second
        must not clobber the first -- unless the spec carries
        ``retain_existing_vlan_addresses: false`` (a shared-VLAN split), which
        replaces them as COOP does. ``ports`` (logicalIDs) move into the VLAN.
        ``mtu`` is optional: an existing interface keeps its own, a new one gets
        9000.
        """
        sw = config.sw
        for vlan_name, blob in my_args.items():
            spec = json.loads(blob)
            vlan_id = spec.get("vlan_id", spec.get("vlanID"))
            if vlan_id is None:
                raise PatcherError(f"configure_vlans: {vlan_name} has no vlan_id")
            addresses = list(spec.get("ip_addresses") or [])
            if not addresses:
                raise PatcherError(f"configure_vlans: {vlan_name} has no ip_addresses")
            mtu = int(spec["mtu"]) if spec.get("mtu") is not None else None
            vlan_id = int(vlan_id)
            replace = spec.get("retain_existing_vlan_addresses", True) is False
            sw = _merge_vlan_interface(sw, vlan_name, vlan_id, addresses, mtu, replace)
            sw = _merge_vlan(sw, vlan_name, vlan_id, addresses, replace)
            sw = _move_ports_to_vlan(sw, vlan_id, list(spec.get("ports") or []))
        return config(sw=sw)

    async def change_speed(
        self, config: AgentConfig, config_name: str, my_args: t.Dict[str, t.Any]
    ) -> AgentConfig:
        """Set ``intfs`` (comma-separated port names) to ``speed`` (a PortSpeed
        name) with ``profile_id`` (a PortProfileID name), as COOP's change_speed.

        Every port must offer the profile in the platform mapping, or else exactly
        one wire-identical profile (``_fit_profile``), and on 51T hardware a
        /1-/5 pair must stay a valid speed combination. A named port
        the config lacks is created (see ``_new_port``). Ports a resulting
        profile subsumes are then removed with their VLAN memberships, which is
        why an apply that removes ports cold boots the agent (oss_coop_patcher).
        """
        intfs = [name for name in my_args["intfs"].split(",") if name]
        try:
            speed = PortSpeed[my_args["speed"]]
            profile = PortProfileID[my_args["profile_id"]]
        except KeyError as exc:
            raise PatcherError(
                f"change_speed: unknown PortSpeed or PortProfileID name {exc}"
            ) from exc
        platform_mapping = await self._platform_mapping()
        entries = {e.mapping.name: e for e in platform_mapping.ports.values()}

        unknown = [name for name in intfs if name not in entries]
        if unknown:
            raise PatcherError(f"change_speed: {unknown} not in the platform mapping")
        fitted = {
            name: _fit_profile(entries[name], profile, platform_mapping)
            for name in intfs
        }
        unsupported = [name for name, fit in fitted.items() if fit is None]
        if unsupported:
            raise PatcherError(
                f"change_speed: profile {profile.name} not supported on ports: "
                f"{', '.join(unsupported)} (and no unique wire-identical profile)"
            )
        profiles = {name: fit for name, fit in fitted.items() if fit is not None}
        for name, fit in profiles.items():
            if fit != profile:
                self.logger.info(
                    f"change_speed: {name} takes {fit.name}, its wire-identical "
                    f"profile for {profile.name}"
                )
        self._validate_speed_change(config, intfs, speed)

        sw = _add_missing_ports(config.sw, entries, intfs, speed, profiles)
        sw = sw(
            ports=[
                p(speed=speed, profileID=profiles[p.name], state=PortState.ENABLED)
                if p.name in profiles
                else p
                for p in sw.ports
            ]
        )
        sw = _remove_subsumed_ports(sw, platform_mapping)
        # A requested port another port's profile still subsumes is gone again;
        # registering that would report a speed change on a port that is absent.
        present = {p.name for p in sw.ports}
        lost = [name for name in intfs if name not in present]
        if lost:
            raise PatcherError(
                f"change_speed: {lost} would be subsumed by another port's "
                "profile; change that port's speed in the same request"
            )
        return config(sw=sw)

    async def _platform_mapping(self) -> t.Any:
        if self.inputs is None:
            raise PatcherError("change_speed needs the device's platform mapping")
        return await self.inputs.platform_mapping()

    def _validate_speed_change(
        self, config: AgentConfig, intfs: t.Sequence[str], speed: PortSpeed
    ) -> None:
        """COOP's validate_speed_change: the adjacent-port / slot rule of the
        device's hardware family, if it has one."""
        hardware = ((self.inputs.hardware() if self.inputs else None) or "").upper()
        if hardware in _HARDWARE_51T:
            self._validate_51t_speed_change(hardware, config, intfs, speed)
        elif hardware in _HARDWARE_25T:
            self._validate_25t_speed_change(hardware, intfs, speed)
        elif hardware in _HARDWARE_12T:
            self._validate_12t_speed_change(hardware, intfs, speed)
        else:
            self.logger.info(
                f"change_speed: no adjacent-port rule for hardware {hardware!r}"
            )

    def _validate_25t_speed_change(
        self, hardware: str, intfs: t.Sequence[str], speed: PortSpeed
    ) -> None:
        violations = []
        if speed == PortSpeed.FOURHUNDREDG:
            for name in intfs:
                slot = _slot(name)
                if slot is None:
                    violations.append(
                        f"Port {name} has invalid format (expected ethX/Y/Z)"
                    )
                elif hardware in ("WEDGE400", "WEDGE400C") and not 1 <= slot <= 16:
                    violations.append(
                        f"Port {name} cannot be 400G: {hardware} allows 400G only on "
                        "eth1/1/1 through eth1/16/1"
                    )
                elif hardware == "DARWIN" and not (1 <= slot <= 31 and slot % 2):
                    violations.append(
                        f"Port {name} cannot be 400G: DARWIN allows 400G only on odd "
                        "ports eth1/1/1 .. eth1/31/1"
                    )
                elif hardware in _HARDWARE_25T_PAIRED and not slot % 2:
                    violations.append(
                        f"Port {name} cannot be 400G: {hardware} allows 400G only on "
                        "odd-numbered ports"
                    )
        elif hardware in _HARDWARE_25T_PAIRED:
            for name in intfs:
                adjacent = _25t_adjacent_port(name)
                if not adjacent:
                    violations.append(f"Adjacent port for port {name} not found")
                elif adjacent not in intfs:
                    violations.append(
                        f"Port {name} -> {speed.value // 1000}G needs its adjacent "
                        f"port {adjacent} in the same request"
                    )
        if violations:
            raise PatcherError(
                f"change_speed: not allowed on 25.6T hardware {hardware}:\n"
                + "\n".join(f" - {v}" for v in violations)
            )

    def _validate_12t_speed_change(
        self, hardware: str, intfs: t.Sequence[str], speed: PortSpeed
    ) -> None:
        if speed != PortSpeed.TWOHUNDREDG:
            return
        parity = 1 if hardware == "MINIPACK" else 0
        bad = [n for n in intfs if (_slot(n) or 0) % 2 != parity]
        if bad:
            raise PatcherError(
                f"change_speed: 12.8T {hardware} allows 200G only on "
                f"{'odd' if parity else 'even'} ports, not {bad}"
            )

    def _validate_51t_speed_change(
        self,
        hardware: str,
        config: AgentConfig,
        intfs: t.Sequence[str],
        speed: PortSpeed,
    ) -> None:
        violations = []
        if speed == PortSpeed.EIGHTHUNDREDG:
            violations = [
                f"800G speed not allowed on port {name}, allowed only on X/Y/1"
                for name in intfs
                if name.split("/")[-1] != "1"
            ]
        else:
            port_speeds = {
                p.name: p.speed.value // 1000 for p in config.sw.ports if p.name
            }
            target = speed.value // 1000
            for name in intfs:
                adjacent = _51t_adjacent_port(name)
                if not adjacent:
                    violations.append(f"Adjacent port for port {name} not found")
                    continue
                adjacent_speed = port_speeds.get(adjacent)
                if adjacent in intfs or adjacent_speed is None:
                    continue
                if (
                    target,
                    adjacent_speed,
                ) not in _SUPPORTED_51T_SPEED_COMBINATIONS and (
                    adjacent_speed,
                    target,
                ) not in _SUPPORTED_51T_SPEED_COMBINATIONS:
                    violations.append(
                        f"Port {name} -> {target}G incompatible with adjacent "
                        f"port {adjacent} @ {adjacent_speed}G"
                    )
        if violations:
            raise PatcherError(
                f"change_speed: not allowed on 51T hardware {hardware}; both "
                "ports must be 100G, or a mix of 200G/400G:\n"
                + "\n".join(f" - {v}" for v in violations)
            )

    def change_port_admin_state(
        self, config: AgentConfig, config_name: str, my_args: t.Dict[str, t.Any]
    ) -> AgentConfig:
        """``{port_name: "enable" | "disable"}``; the state persists across
        agent restarts."""
        bad = {name: v for name, v in my_args.items() if v not in _PORT_STATES}
        if bad:
            raise PatcherError(
                f"change_port_admin_state: states must be one of "
                f"{sorted(_PORT_STATES)}, got {bad}"
            )
        names = {p.name for p in config.sw.ports}
        unknown = sorted(set(my_args) - names)
        if unknown:
            raise PatcherError(f"change_port_admin_state: no ports {unknown}")
        return config(
            sw=config.sw(
                ports=[
                    p(state=_PORT_STATES[my_args[p.name]]) if p.name in my_args else p
                    for p in config.sw.ports
                ]
            )
        )

    def change_mtu(
        self, config: AgentConfig, config_name: str, my_args: t.Dict[str, t.Any]
    ) -> AgentConfig:
        """Set ``mtu`` on the interfaces ``intfs`` names: comma-separated port
        names (meaning their ingress VLAN's interface), interface names, or VLAN
        IDs. MTU lives on the L3 interface, not the port."""
        intfs = [name for name in my_args["intfs"].split(",") if name]
        mtu = int(my_args["mtu"])
        vlan_ids = {p.ingressVlan for p in config.sw.ports if p.name in intfs}
        vlan_ids |= {int(name) for name in intfs if name.isdigit()}

        def named(intf: Interface) -> bool:
            return (intf.name or "") in intfs or (intf.vlanID or 0) in vlan_ids

        if not any(named(i) for i in config.sw.interfaces):
            raise PatcherError(f"change_mtu: no interface matches {intfs}")
        return config(
            sw=config.sw(
                interfaces=[i(mtu=mtu) if named(i) else i for i in config.sw.interfaces]
            )
        )

    def add_static_routes(
        self, config: AgentConfig, config_name: str, my_args: t.Dict[str, t.Any]
    ) -> AgentConfig:
        """``{prefix: json([next_hop, ...])}``; a prefix replaces any route
        already configured for it."""
        routes = list(config.sw.staticRoutesWithNhops)
        for prefix, next_hops in my_args.items():
            routes = [r for r in routes if r.prefix != prefix]
            routes.append(
                StaticRouteWithNextHops(prefix=prefix, nexthops=json.loads(next_hops))
            )
        return config(sw=config.sw(staticRoutesWithNhops=routes))

    def add_bgp_policy_statement(
        self, config: BgpConfig, config_name: str, my_args: t.Dict[str, t.Any]
    ) -> BgpConfig:
        """Add a policy statement (``name``, ``description``, ``policy_entries``
        as COOP's thrift-shaped dicts). A statement of that name already in the
        config is left as it is, as in COOP."""
        statement = oss_bgp_policy.create_policy_statement(my_args)
        policies = config.policies or BgpPolicies()
        statements = list(policies.bgp_policy_statements or [])
        if any(s.name == statement.name for s in statements):
            self.logger.info(f"Policy already present: {statement.name}")
            return config
        return config(policies=policies(bgp_policy_statements=[*statements, statement]))

    def add_bgp_policy_match_prefix_to_propagate_routes(
        self, config: BgpConfig, config_name: str, my_args: t.Dict[str, t.Any]
    ) -> BgpConfig:
        """Put a term matching ``matching_prefix`` (and longer) first in the
        ``in_stmt_name`` and ``out_stmt_name`` statements; the ingress term also
        sets local-pref 100.

        A named statement the config lacks is skipped with a warning, as COOP
        skips it silently: callers derive both names from the role path,
        including drain variants a given config does not carry."""
        prefix = my_args["matching_prefix"]
        # Same statement for both: the ingress term wins, as in COOP's if/elif.
        targets = {
            my_args["out_stmt_name"]: oss_bgp_policy.matching_prefix_term(
                prefix, False
            ),
            my_args["in_stmt_name"]: oss_bgp_policy.matching_prefix_term(prefix, True),
        }
        policies = config.policies
        statements = list((policies.bgp_policy_statements if policies else None) or [])
        absent = sorted(set(targets) - {s.name for s in statements})
        if absent:
            self.logger.warning(
                f"add_bgp_policy_match_prefix_to_propagate_routes: no statement "
                f"{absent} to add {prefix} to"
            )
        if policies is None or len(absent) == len(targets):
            return config
        return config(
            policies=policies(
                bgp_policy_statements=[
                    s(policy_entries=[targets[s.name], *s.policy_entries])
                    if s.name in targets
                    else s
                    for s in statements
                ]
            )
        )

    def drain_interface(
        self, config: BgpConfig, config_name: str, my_args: t.Dict[str, t.Any]
    ) -> BgpConfig:
        """Point the BGP sessions on one interface at the OSS drain policy.

        COOP's ``drain_ma_interface`` with ``require_peer_match``: every peer
        whose ``peer_addr`` falls in one of ``networks`` (a JSON list of the
        interface's subnets) takes ``PROPAGATE_EVERYTHING_IN`` /
        ``PROPAGATE_EVERYTHING_OUT_DRAIN``, and ``interface_name`` is recorded
        in ``drained_interfaces``. Those are the only drain policies OSS has:
        ``config_modifiers.generate_base_configs`` declares them in both the
        live and the soft-drain config, and a device drain points every group
        it manages at them.

        Refused: a config without those policies, an interface with no peer,
        and a session not on ``PROPAGATE_EVERYTHING_OUT`` -- already drained,
        or in a group a scoped setup left on its own policies, which a device
        drain does not drain either.
        """
        target = my_args.get("interface_name")
        if not target:
            raise PatcherError("drain_interface: no interface_name")
        declared = {
            s.name
            for s in (
                (config.policies.bgp_policy_statements if config.policies else None)
                or []
            )
        }
        missing = sorted({POLICY_PROPAGATE_IN, POLICY_PROPAGATE_OUT_DRAIN} - declared)
        if missing:
            raise PatcherError(
                f"drain_interface: the config does not declare {', '.join(missing)}; "
                "generate the base configs first"
            )
        networks = [
            ipaddress.ip_network(network, strict=False)
            for network in json.loads(my_args.get("networks", "[]"))
        ]
        groups = {g.name: g for g in config.peer_groups or []}

        peers = list(config.peers)
        matched = [i for i, peer in enumerate(peers) if _peer_on(peer, networks)]
        if not matched:
            raise PatcherError(
                f"drain_interface: no BGP peer sits on {target} "
                f"({', '.join(map(str, networks)) or 'no address'}), so there "
                "is no session to drain"
            )
        for i in matched:
            peer = peers[i]
            group = groups.get(peer.peer_group_name or "")
            egress = peer.egress_policy_name or (
                group.egress_policy_name if group else None
            )
            if egress != POLICY_PROPAGATE_OUT:
                raise PatcherError(
                    f"drain_interface: peer {peer.peer_addr} on {target} "
                    f"advertises through {egress}, not {POLICY_PROPAGATE_OUT}; "
                    "only sessions the base configs manage can be drained"
                )
            self.logger.info(
                f"drain_interface: {target}: peer {peer.peer_addr} -> "
                f"({POLICY_PROPAGATE_IN}, {POLICY_PROPAGATE_OUT_DRAIN})"
            )
            peers[i] = peer(
                ingress_policy_name=POLICY_PROPAGATE_IN,
                egress_policy_name=POLICY_PROPAGATE_OUT_DRAIN,
            )
        return config(
            peers=peers,
            drained_interfaces=_merge(config.drained_interfaces, [target]),
        )

    def set_port_channel_min_link_capacity(
        self, config: AgentConfig, config_name: str, my_args: t.Dict[str, t.Any]
    ) -> AgentConfig:
        """COOP's set_port_channel_min_link_capacity: the ``port_channel_name``
        aggregate port stays up while ``link_percentage`` of its members are up,
        and with ``link_up_percentage`` (optional) comes up once that many are."""
        name = my_args.get("port_channel_name")
        if not name or "link_percentage" not in my_args:
            raise PatcherError(
                "set_port_channel_min_link_capacity needs port_channel_name and "
                "link_percentage"
            )
        try:
            down = float(my_args["link_percentage"])
            up = (
                float(my_args["link_up_percentage"])
                if "link_up_percentage" in my_args
                else None
            )
        except (TypeError, ValueError) as exc:
            raise PatcherError(
                f"set_port_channel_min_link_capacity: not a number: {exc}"
            ) from exc
        ports = list(config.sw.aggregatePorts)
        index = next((i for i, a in enumerate(ports) if a.name == name), None)
        if index is None:
            raise PatcherError(
                f"set_port_channel_min_link_capacity: no aggregate port {name}"
            )
        port = ports[index](minimumCapacity=MinimumCapacity(linkPercentage=down))
        if up is not None:
            port = port(minimumCapacityToUp=MinimumCapacity(linkPercentage=up))
        ports[index] = port
        return config(sw=config.sw(aggregatePorts=ports))
