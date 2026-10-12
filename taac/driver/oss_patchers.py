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
from neteng.fboss.agent_config.thrift_types import AgentConfig
from neteng.fboss.bgp_attr.thrift_types import AddPath
from neteng.fboss.switch_config.thrift_types import (
    Interface,
    SpanningTreeState,
    StaticRouteWithNextHops,
    SwitchConfig,
    Vlan,
    VlanPort,
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
    "add_static_routes": AgentConfig,
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


class OssPatchApplier:
    def __init__(self, logger: logging.Logger = logger) -> None:
        self.logger = logger

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
