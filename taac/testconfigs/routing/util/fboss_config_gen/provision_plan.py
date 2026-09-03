# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""Turn ``RbbTopology`` + ``TAAC_RBB_*`` env into a per-DUT provisioning plan.

The plan is the single, generic, doc-range-defaulted description of everything
the from-scratch generators need: loopbacks / router-id / ASN, the SVI RIFs
(loopback, per-core-PC, per-IXIA-edge, and the two SRv6 SID interfaces), the
aggregate ports (from ``circuit_info`` core members), the SRv6 ``mySidConfig`` /
``srv6Tunnels`` / steering static routes, and the ``clientIdToAdminDistance``
map. VLAN/interface IDs are derived deterministically from the numbering scheme
in ``bgp_rbb_constants``; addresses default to RFC 3849 / RFC 5737 documentation
ranges and are overridable via ``TAAC_RBB_*`` env so NO lab values are committed.

``build_rbb_provision_plan(topology, port_map)`` returns ``{"r1": NodePlan,
"r2": NodePlan}``. ``port_map`` (parsed platform mapping) is optional: when
present, aggregate-port members and the SRv6 tunnel underlay interface resolve
to real logical port IDs; when absent (pure unit tests) a deterministic stub ID
is used.
"""

from __future__ import annotations

import os
import typing as t
from dataclasses import dataclass, field

from taac.testconfigs.routing.util import bgp_rbb_constants as C
from taac.testconfigs.routing.util.bgp_rbb_topology import NodeTopology, RbbTopology
from taac.testconfigs.routing.util.fboss_config_gen.platform_mapping import (
    PortEntry,
    resolve_port,
)


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Rif:
    """One SVI (VLAN) routed interface."""

    vlan_id: int
    intf_id: int
    name: str
    ip_addresses: t.Tuple[str, ...]  # CIDR strings
    member_iface: t.Optional[str] = None  # physical port joined to the VLAN
    mtu: int = 9000


@dataclass(frozen=True)
class AggPort:
    """One aggregate port (port-channel)."""

    agg_id: int
    name: str  # fboss2 render, e.g. "Port-Channel161"
    description: str
    member_port_ids: t.Tuple[int, ...]
    member_ifaces: t.Tuple[str, ...]


@dataclass(frozen=True)
class MySidEntry:
    """One ``mySidConfig`` entry (adjacency micro-SID or tail decap)."""

    key: str
    behavior: str  # "adjacency" | "decap"
    port_name: t.Optional[str] = None
    address: t.Optional[str] = None
    is_v6: bool = True


@dataclass(frozen=True)
class Srv6Tunnel:
    tunnel_id: str
    underlay_intf_id: int
    src_ip: str


@dataclass(frozen=True)
class StaticRoute:
    prefix: str
    nexthops: t.Tuple[str, ...]


@dataclass(frozen=True)
class NodePlan:
    """Everything the generators need for one DUT."""

    role: str
    node_index: int
    hostname: str
    local_as: int
    router_id: str
    loopback_v4: str  # CIDR
    loopback_v6: str  # CIDR
    peer_loopback_v4: str  # bare
    networks4: t.Tuple[str, ...]
    networks6: t.Tuple[str, ...]
    rifs: t.Tuple[Rif, ...]
    agg_ports: t.Tuple[AggPort, ...]
    mysid_locator: str
    mysid_entries: t.Tuple[MySidEntry, ...]
    srv6_tunnels: t.Tuple[Srv6Tunnel, ...]
    static_routes: t.Tuple[StaticRoute, ...]
    client_admin_distance: t.Dict[int, int] = field(default_factory=dict)
    core_member_ifaces: t.Tuple[str, ...] = ()
    edge_ifaces: t.Tuple[str, ...] = ()


# ClientID -> admin distance (reference deployment). FBOSS-generic:
# 0=BGP(20), 1=STATIC(1), 2=INTERFACE(0), 3=LINKLOCAL(0), 700=OPENR(255),
# 786=TE_AGENT-ish(10). Kept as a generic default; not lab-specific.
_DEFAULT_CLIENT_ADMIN_DISTANCE: t.Dict[int, int] = {
    0: 20,
    1: 1,
    2: 0,
    3: 0,
    700: 255,
    786: 10,
}


def _resolve_port_id(
    port_map: t.Optional[t.Mapping[str, PortEntry]], iface: str, fallback: int
) -> int:
    if port_map:
        try:
            return resolve_port(port_map, iface)[0]
        except KeyError:
            pass
    return fallback


def _build_node_plan(
    node: NodeTopology,
    peer: NodeTopology,
    node_index: int,
    port_map: t.Optional[t.Mapping[str, PortEntry]],
) -> NodePlan:
    role = node.role  # "r1" | "r2"
    up = role.upper()  # "R1" | "R2"
    is_tail = node_index == 2

    router_id = _env(f"TAAC_RBB_{up}_ROUTER_ID", getattr(C, f"{up}_ROUTER_ID"))
    loopback_v6 = _env(f"TAAC_RBB_{up}_LOOPBACK_V6", getattr(C, f"{up}_LOOPBACK_V6"))
    peer_up = peer.role.upper()
    peer_router_id = _env(
        f"TAAC_RBB_{peer_up}_ROUTER_ID", getattr(C, f"{peer_up}_ROUTER_ID")
    )

    loopback_v4_cidr = f"{router_id}/32"
    loopback_v6_cidr = f"{loopback_v6}/128"
    networks4 = (f"{router_id}/32",) + getattr(C, f"{up}_NETWORKS4_EXTRA")
    networks6 = (f"{loopback_v6}/128",)

    rifs: t.List[Rif] = []
    # Loopback RIF (Vlan4000).
    rifs.append(
        Rif(
            vlan_id=C.LOOPBACK_VLAN,
            intf_id=C.LOOPBACK_VLAN,
            name=f"Vlan{C.LOOPBACK_VLAN}",
            ip_addresses=(loopback_v4_cidr, loopback_v6_cidr),
        )
    )

    # Core-PC RIFs (one per core port-channel). FBOSS uses a per-port SVI model:
    # the RIF VLAN/interface ID is ``2000 + <member logical port id>`` (e.g.
    # eth1/6/1 id 11 -> Vlan2011), so the RIF rides the member port's own VLAN.
    agg_ports: t.List[AggPort] = []
    core_member_ifaces: t.List[str] = []
    for i, pc in enumerate(node.core_pcs):
        member_iface = pc.members[0] if pc.members else None
        member_ids = tuple(
            _resolve_port_id(port_map, m, 11 + i) for m in pc.members
        )
        primary_id = member_ids[0] if member_ids else (11 + i)
        vlan = 2000 + primary_id
        v4 = _env(
            f"TAAC_RBB_{up}_CORE{i}_V4",
            f"198.51.100.{i * 4 + node_index}/30",
        )
        v6 = _env(f"TAAC_RBB_{up}_CORE{i}_V6", f"2001:db8:c{i}::{node_index - 1}/127")
        ips = (v4, v6) if v6 else (v4,)
        rifs.append(
            Rif(
                vlan_id=vlan,
                intf_id=vlan,
                name=f"Vlan{vlan}",
                ip_addresses=ips,
                member_iface=member_iface,
            )
        )
        agg_ports.append(
            AggPort(
                agg_id=int(pc.name.split("channel")[-1]) if "channel" in pc.name else (161 + i),
                name=pc.show_name,
                description=f"RBB core {pc.show_name}",
                member_port_ids=member_ids,
                member_ifaces=tuple(pc.members),
            )
        )
        core_member_ifaces.extend(pc.members)

    # IXIA-facing edge RIFs (one per edge). Same per-port SVI scheme: RIF
    # VLAN = 2000 + edge member port id.
    edge_ifaces: t.List[str] = []
    for i, edge in enumerate(node.ixia_edges):
        edge_id = _resolve_port_id(port_map, edge.dut_interface, 1 + i)
        vlan = 2000 + edge_id
        v4 = _env(
            f"TAAC_RBB_{up}_EDGE{i}_V4",
            f"192.0.2.{100 + i * 2 + node_index}/24",
        )
        v6 = _env(
            f"TAAC_RBB_{up}_EDGE{i}_V6",
            f"2001:db8:e{i}:{node_index}::1/64",
        )
        rifs.append(
            Rif(
                vlan_id=vlan,
                intf_id=vlan,
                name=f"Vlan{vlan}",
                ip_addresses=(v4, v6),
                member_iface=edge.dut_interface,
            )
        )
        edge_ifaces.append(edge.dut_interface)

    # SRv6 SID interfaces (Vlan10 / Vlan11).
    sid_a = _env(
        f"TAAC_RBB_{up}_SRV6_SID_A",
        f"2001:db8:fe00:200::{node_index}:0/128",
    )
    sid_b = _env(
        f"TAAC_RBB_{up}_SRV6_SID_B",
        f"2001:db8:feff:200::{node_index}:0/128",
    )
    rifs.append(
        Rif(
            vlan_id=C.SRV6_SID_VLAN_A,
            intf_id=C.SRV6_SID_VLAN_A,
            name=f"Vlan{C.SRV6_SID_VLAN_A}",
            ip_addresses=(sid_a,),
        )
    )
    rifs.append(
        Rif(
            vlan_id=C.SRV6_SID_VLAN_B,
            intf_id=C.SRV6_SID_VLAN_B,
            name=f"Vlan{C.SRV6_SID_VLAN_B}",
            ip_addresses=(sid_b,),
        )
    )

    # SRv6 mySidConfig: locator + adjacency (+ decap on tail).
    mysid_locator = _env("TAAC_RBB_SRV6_MYSID_LOCATOR", C.SRV6_LOCATOR)
    adj_key = _env(f"TAAC_RBB_{up}_MYSID_KEY", "10188" if not is_tail else "10198")
    # R1 adjacency over its first core PC toward R2; R2 over its last core PC.
    adj_pc = node.core_pcs[0] if not is_tail else (
        node.core_pcs[-1] if node.core_pcs else None
    )
    adj_port_name = adj_pc.show_name if adj_pc else ""
    adj_addr = _env(
        f"TAAC_RBB_{up}_MYSID_ADJ_ADDR",
        # Default adjacency next-hop = peer side of core0 /127.
        f"2001:db8:c0::{0 if is_tail else 1}",
    )
    mysid_entries: t.List[MySidEntry] = [
        MySidEntry(
            key=adj_key,
            behavior="adjacency",
            port_name=adj_port_name,
            address=adj_addr,
            is_v6=True,
        )
    ]
    if is_tail:
        mysid_entries.append(
            MySidEntry(key=C.DECAP_MYSID_KEY, behavior="decap")
        )

    # SRv6 tunnel (underlay = first core PC member port).
    underlay_iface = (
        node.core_pcs[0].members[0]
        if node.core_pcs and node.core_pcs[0].members
        else ""
    )
    underlay_id = _resolve_port_id(port_map, underlay_iface, 11) if underlay_iface else 11
    tunnel_src = _env(
        f"TAAC_RBB_{up}_SRV6_TUNNEL_SRC",
        f"2001:db8:feff:200::{node_index}:0",
    )
    srv6_tunnels = (
        Srv6Tunnel(
            tunnel_id=C.SRV6_TUNNEL_ID,
            underlay_intf_id=underlay_id,
            src_ip=tunnel_src,
        ),
    )

    # Steering static routes. Head (R1): locator -> adjacency next-hop (onto core).
    # Tail (R2): reverse toward the head's edge prefix.
    static_routes: t.List[StaticRoute] = []
    if not is_tail:
        static_routes.append(
            StaticRoute(prefix=mysid_locator, nexthops=(adj_addr,))
        )
    else:
        rev_prefix = _env("TAAC_RBB_SRV6_REVERSE_PREFIX", "2001:db8:e0:1::/64")
        rev_nh = _env(f"TAAC_RBB_{up}_SRV6_REVERSE_NH", adj_addr)
        static_routes.append(StaticRoute(prefix=rev_prefix, nexthops=(rev_nh,)))

    return NodePlan(
        role=role,
        node_index=node_index,
        hostname=node.hostname,
        local_as=C.CORE_IBGP_AS,
        router_id=router_id,
        loopback_v4=loopback_v4_cidr,
        loopback_v6=loopback_v6_cidr,
        peer_loopback_v4=peer_router_id,
        networks4=networks4,
        networks6=networks6,
        rifs=tuple(rifs),
        agg_ports=tuple(agg_ports),
        mysid_locator=mysid_locator,
        mysid_entries=tuple(mysid_entries),
        srv6_tunnels=srv6_tunnels,
        static_routes=tuple(static_routes),
        client_admin_distance=dict(_DEFAULT_CLIENT_ADMIN_DISTANCE),
        core_member_ifaces=tuple(core_member_ifaces),
        edge_ifaces=tuple(edge_ifaces),
    )


def build_rbb_provision_plan(
    topology: RbbTopology,
    port_map: t.Optional[t.Mapping[str, PortEntry]] = None,
) -> t.Dict[str, NodePlan]:
    """Build ``{"r1": NodePlan, "r2": NodePlan}`` from topology + env."""
    return {
        "r1": _build_node_plan(topology.r1, topology.r2, 1, port_map),
        "r2": _build_node_plan(topology.r2, topology.r1, 2, port_map),
    }
