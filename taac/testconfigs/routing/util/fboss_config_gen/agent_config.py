# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""Build ``/etc/coop/agent.conf`` (cfg::AgentConfig) from scratch.

The AgentConfig wrapper has three top-level keys:

  * ``sw``  -- the cfg::SwitchConfig this module GENERATES from the provisioning
    plan + platform mapping: the full port list, the per-port SVI VLAN model
    (VLAN/interface ``2000 + logicalID``), the routed-interface (RIF) IPs for the
    loopback / core-PC / IXIA-edge / SRv6-SID interfaces, the aggregate ports,
    and the SRv6 ``mySidConfig`` / ``srv6Tunnels`` / ``staticRoutesWithNhops``.
  * ``platform`` -- the ASIC/board firmware descriptor (gr2 chip config, serdes
    swaps). This is HARDWARE, not topology: it cannot be synthesized from a CSV
    and is SOURCED from the box's own platform data at provision time (passed in
    as ``platform``). Documented seam, not a golden-config clone.
  * ``defaultCommandLineArgs`` -- agent flags; likewise sourced from the box.

The routing / L3 / SRv6 *semantics* -- everything that varies per topology -- are
100% generated here. ``base_sw`` (the box's existing SwitchConfig) is an OPTIONAL
input: when given, its board-generic scaffolding (CPU/QoS queues, load
balancers, per-port scaffolding fields) is preserved and only the generated
sections are overwritten, so the emitted config is agent-acceptable on a real
box. When absent (pure unit tests), a minimal-but-complete SwitchConfig is built
from the platform mapping alone.
"""

from __future__ import annotations

import copy
import typing as t

from taac.testconfigs.routing.util.fboss_config_gen.platform_mapping import (
    all_ports,
    choose_profile,
    PortEntry,
)
from taac.testconfigs.routing.util.fboss_config_gen.provision_plan import NodePlan

DEFAULT_ASIC_TYPE: int = 15
PORT_SPEED: int = 400000
MAX_FRAME_SIZE: int = 9412
PER_PORT_VLAN_BASE: int = 2000

# SwitchConfig sections this generator fully owns / overwrites.
_GENERATED_SECTIONS: t.Tuple[str, ...] = (
    "ports",
    "vlans",
    "vlanPorts",
    "interfaces",
    "aggregatePorts",
    "mySidConfig",
    "srv6Tunnels",
    "staticRoutesWithNhops",
    "clientIdToAdminDistance",
    "switchSettings",
)


def _port_entry(pe: PortEntry, ingress_vlan: int) -> t.Dict[str, t.Any]:
    return {
        "logicalID": pe.logical_id,
        "name": pe.name,
        "profileID": choose_profile(pe.supported_profiles),
        "speed": PORT_SPEED,
        "state": 2,  # ENABLED
        "portType": 0,
        "ingressVlan": ingress_vlan,
        "maxFrameSize": MAX_FRAME_SIZE,
        "parserType": 1,
        "routable": True,
        "scope": 0,
    }


def _vlan(vid: int, ips: t.Sequence[str]) -> t.Dict[str, t.Any]:
    return {
        "id": vid,
        "name": f"Vlan{vid}",
        "ipAddresses": list(ips),
        "recordStats": True,
        "routable": True,
    }


def _interface(
    intf_id: int, vlan_id: int, ips: t.Sequence[str], is_virtual: bool
) -> t.Dict[str, t.Any]:
    return {
        "intfID": intf_id,
        "vlanID": vlan_id,
        "type": 1,  # VLAN (SVI)
        "mtu": 9000,
        "routerID": 0,
        "scope": 0,
        "isVirtual": is_virtual,
        "isStateSyncDisabled": True,
        "ipAddresses": list(ips),
    }


def _mysid_config(plan: NodePlan) -> t.Dict[str, t.Any]:
    entries: t.Dict[str, t.Any] = {}
    for e in plan.mysid_entries:
        if e.behavior == "adjacency":
            entries[e.key] = {
                "adjacency": {
                    "isV6": e.is_v6,
                    "portName": e.port_name or "",
                    "address": e.address or "",
                }
            }
        elif e.behavior == "decap":
            entries[e.key] = {"decap": {}}
    return {"locatorPrefix": plan.mysid_locator, "entries": entries}


def _srv6_tunnels(plan: NodePlan) -> t.List[t.Dict[str, t.Any]]:
    return [
        {
            "srv6TunnelId": tnl.tunnel_id,
            "underlayIntfID": tnl.underlay_intf_id,
            "srcIp": tnl.src_ip,
            "tunnelTermType": 2,
            "tunnelType": 1,
            "ttl": 0,
            "dscp": 0,
            "ecn": 0,
        }
        for tnl in plan.srv6_tunnels
    ]


def _static_routes(plan: NodePlan) -> t.List[t.Dict[str, t.Any]]:
    return [
        {"prefix": r.prefix, "nexthops": list(r.nexthops)}
        for r in plan.static_routes
    ]


def _client_admin_distance(plan: NodePlan) -> t.List[t.Dict[str, int]]:
    # cfg::SwitchConfig.clientIdToAdminDistance is a list<ClientIdToAdminDistance>.
    return [
        {"clientId": cid, "adminDistance": dist}
        for cid, dist in sorted(plan.client_admin_distance.items())
    ]


def _switch_settings(
    asic_type: int, base_sw: t.Optional[t.Mapping[str, t.Any]]
) -> t.Dict[str, t.Any]:
    if base_sw and isinstance(base_sw.get("switchSettings"), dict):
        # Preserve the box's switchSettings (switchMac, connectionHandle, ...);
        # only pin asicType.
        ss = copy.deepcopy(base_sw["switchSettings"])
        info = ss.setdefault("switchIdToSwitchInfo", {})
        for _sid, sinfo in info.items():
            if isinstance(sinfo, dict):
                sinfo["asicType"] = asic_type
        return ss
    return {
        "switchType": 0,
        "switchIdToSwitchInfo": {
            "0": {
                "asicType": asic_type,
                "connectionHandle": "/dev/uio0",
                "portIdRange": {"minimum": 0, "maximum": 2047},
                "switchIndex": 0,
                "switchType": 0,
            }
        },
    }


def build_switch_config(
    plan: NodePlan,
    port_map: t.Mapping[str, PortEntry],
    *,
    asic_type: int = DEFAULT_ASIC_TYPE,
    base_sw: t.Optional[t.Mapping[str, t.Any]] = None,
) -> t.Dict[str, t.Any]:
    """Build the cfg::SwitchConfig ``sw`` dict from scratch.

    When ``base_sw`` is provided its board-generic scaffolding is preserved and
    only the routing/L3/SRv6 sections are overwritten; per-port scaffolding
    fields (if any) are merged onto the generated port list by logical ID.
    """
    ports_sorted = all_ports(port_map)

    # RIF IPs keyed by their VLAN id; virtual RIFs (loopback / SRv6-SID) have no
    # physical member port and get their own VLAN + interface.
    rif_ips_by_vlan: t.Dict[int, t.Sequence[str]] = {}
    virtual_rifs = []
    for rif in plan.rifs:
        if rif.member_iface is not None:
            rif_ips_by_vlan[rif.vlan_id] = rif.ip_addresses
        else:
            virtual_rifs.append(rif)

    base_ports_by_id: t.Dict[int, t.Dict[str, t.Any]] = {}
    if base_sw:
        for p in base_sw.get("ports", []) or []:
            if isinstance(p, dict) and "logicalID" in p:
                base_ports_by_id[int(p["logicalID"])] = p

    ports: t.List[t.Dict[str, t.Any]] = []
    vlans: t.List[t.Dict[str, t.Any]] = []
    vlan_ports: t.List[t.Dict[str, t.Any]] = []
    interfaces: t.List[t.Dict[str, t.Any]] = []

    for pe in ports_sorted:
        vlan = PER_PORT_VLAN_BASE + pe.logical_id
        ips = rif_ips_by_vlan.get(vlan, ())
        # Merge board-required scaffolding fields from the base port (if any),
        # then overlay the generated identity + ingress VLAN.
        port = copy.deepcopy(base_ports_by_id.get(pe.logical_id, {}))
        port.update(_port_entry(pe, vlan))
        ports.append(port)
        vlans.append(_vlan(vlan, ips))
        vlan_ports.append(
            {"logicalPort": pe.logical_id, "vlanID": vlan, "emitTags": False}
        )
        interfaces.append(_interface(vlan, vlan, ips, is_virtual=False))

    for rif in virtual_rifs:
        vlans.append(_vlan(rif.vlan_id, rif.ip_addresses))
        interfaces.append(
            _interface(rif.intf_id, rif.vlan_id, rif.ip_addresses, is_virtual=True)
        )

    aggregate_ports = [
        {
            "key": agg.agg_id,
            "name": agg.name,
            "description": agg.description,
            "memberPorts": [
                {"memberPortID": pid} for pid in agg.member_port_ids
            ],
        }
        for agg in plan.agg_ports
    ]

    sw: t.Dict[str, t.Any] = copy.deepcopy(dict(base_sw)) if base_sw else {}
    sw["ports"] = ports
    sw["vlans"] = vlans
    sw["vlanPorts"] = vlan_ports
    sw["interfaces"] = interfaces
    sw["aggregatePorts"] = aggregate_ports
    sw["mySidConfig"] = _mysid_config(plan)
    sw["srv6Tunnels"] = _srv6_tunnels(plan)
    sw["staticRoutesWithNhops"] = _static_routes(plan)
    sw["clientIdToAdminDistance"] = _client_admin_distance(plan)
    sw["switchSettings"] = _switch_settings(asic_type, base_sw)
    sw.setdefault("defaultVlan", PER_PORT_VLAN_BASE + ports_sorted[0].logical_id)
    return sw


def build_agent_config(
    plan: NodePlan,
    port_map: t.Mapping[str, PortEntry],
    *,
    platform: t.Optional[t.Mapping[str, t.Any]] = None,
    default_command_line_args: t.Optional[t.Mapping[str, t.Any]] = None,
    base_sw: t.Optional[t.Mapping[str, t.Any]] = None,
    asic_type: int = DEFAULT_ASIC_TYPE,
) -> t.Dict[str, t.Any]:
    """Assemble the full AgentConfig dict.

    ``platform`` and ``default_command_line_args`` are the box's immutable
    hardware descriptor / agent flags (sourced at provision time). They are
    omitted from the output when not supplied so unit tests can exercise the
    generated ``sw`` without a box.
    """
    cfg: t.Dict[str, t.Any] = {
        "sw": build_switch_config(
            plan, port_map, asic_type=asic_type, base_sw=base_sw
        )
    }
    if default_command_line_args is not None:
        cfg["defaultCommandLineArgs"] = copy.deepcopy(dict(default_command_line_args))
    if platform is not None:
        cfg["platform"] = copy.deepcopy(dict(platform))
    return cfg
