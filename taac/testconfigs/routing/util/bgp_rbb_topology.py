# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""RBB SRv6 qualification — topology loader (CSV + env → dataclass).

Turns the run's ``device_info.csv`` + ``circuit_info.csv`` into a small,
OSS-safe ``RbbTopology`` so a user cloning the repo can reuse the RBB SRv6 slice
by declaring *their* wiring as INPUTS instead of editing committed constants.

Derived from ``circuit_info.csv`` (schema owned by
``taac.oss_topology_info.circuit_info_loader``):

  * **Core port-channels + members** — rows where both endpoints are the two
    RBB DUTs and the local endpoint carries a parent interface (the
    ``local_parent_interface`` / ``neighbor_parent_interface`` port-channel).
    Members are grouped per node under their parent port-channel.
  * **IXIA edges + IXIA-port↔DUT-interface map** — rows with ``role=IXIA``
    (or whose peer device is the IXIA): the DUT-side ``local_interface`` maps to
    the IXIA-side ``neighbor_interface`` expressed as ``slot/port`` (e.g.
    ``1/3``), which is exactly what ``PhysicalInventory.ixia_ports`` wants.

The R1/R2 hostnames come from ``TAAC_RBB_R1_HOST`` / ``TAAC_RBB_R2_HOST`` (or the
generic ``bgp_rbb_constants`` defaults) and are matched against the CSV
hostnames. When no circuit CSV is supplied (or it yields no RBB rows) the loader
falls back to generic, documentation-only placeholder wiring so the public
factory entrypoints keep working with no external inputs. No secrets are read
here (credentials stay in ``TAAC_SSH_*`` at run time).
"""

from __future__ import annotations

import os
import typing as t
from dataclasses import dataclass, field

from taac.oss_topology_info.circuit_info_loader import (
    DesiredCircuitRecord,
    EndpointRecord,
    load_circuit_info,
)
from taac.testconfigs.routing.util import bgp_rbb_constants as C

# ─── Generic, documentation-only fallback wiring (NOT this lab's values) ────
# Used only when no circuit_info CSV is supplied. Interface / port names are
# neutral placeholders that demonstrate shape; real wiring comes from the CSV.
_DEFAULT_CORE_PCS: t.Tuple[t.Tuple[str, t.Tuple[str, ...]], ...] = (
    ("port-channel1", ("eth1/1",)),
    ("port-channel2", ("eth1/2",)),
)
_DEFAULT_R1_IXIA_EDGES: t.Tuple[t.Tuple[str, str], ...] = (("eth1/3", "1/1"),)
_DEFAULT_R2_IXIA_EDGES: t.Tuple[t.Tuple[str, str], ...] = (("eth1/3", "1/2"),)

_IXIA_ROLE = "IXIA"


@dataclass(frozen=True)
class CorePortChannel:
    """One core port-channel on a node, with its member interfaces."""

    name: str  # parent port-channel name as in the CSV, e.g. "port-channel161"
    members: t.Tuple[str, ...]

    @property
    def show_name(self) -> str:
        """Name as ``fboss2 show aggregate-port`` renders it (capitalized)."""
        low = self.name.lower()
        if low.startswith("port-channel"):
            return "Port-Channel" + self.name[len("port-channel") :]
        return self.name


@dataclass(frozen=True)
class IxiaEdge:
    """One IXIA-facing edge: DUT interface ↔ IXIA physical port (slot/port)."""

    dut_interface: str  # e.g. "eth1/1/1"
    ixia_port: str  # slot/port, e.g. "1/3"


@dataclass(frozen=True)
class NodeTopology:
    """Per-DUT wiring (core port-channels + IXIA edges)."""

    role: str  # "r1" | "r2"
    hostname: str
    core_pcs: t.Tuple[CorePortChannel, ...] = ()
    ixia_edges: t.Tuple[IxiaEdge, ...] = ()

    @property
    def ixia_port_tuples(self) -> t.List[t.Tuple[str, str]]:
        """``(dut_interface, ixia_port)`` list for ``PhysicalInventory``."""
        return [(e.dut_interface, e.ixia_port) for e in self.ixia_edges]

    @property
    def primary_ixia_interface(self) -> t.Optional[str]:
        """First IXIA-facing DUT interface (the edge the S12 step reads)."""
        return self.ixia_edges[0].dut_interface if self.ixia_edges else None

    @property
    def rif_verify_pc(self) -> t.Optional[CorePortChannel]:
        """Core PC whose RIF the S10 verify targets (2nd core PC if present)."""
        if len(self.core_pcs) >= 2:
            return self.core_pcs[1]
        return self.core_pcs[0] if self.core_pcs else None


@dataclass(frozen=True)
class RbbTopology:
    """The two-DUT RBB SRv6 topology derived from CSV/env inputs."""

    r1: NodeTopology
    r2: NodeTopology
    ixia_chassis: str = field(default="")

    def node(self, role: str) -> NodeTopology:
        return self.r1 if role == "r1" else self.r2


# ─── CSV → topology derivation ─────────────────────────────────────────────
def _norm(name: t.Optional[str]) -> str:
    return (name or "").strip().lower()


def _endpoints(circuit: DesiredCircuitRecord) -> t.Tuple[EndpointRecord, EndpointRecord]:
    return circuit.a_endpoint, circuit.z_endpoint


def _core_pcs_for(
    this_host: str, other_host: str, circuits: t.Sequence[DesiredCircuitRecord]
) -> t.Tuple[CorePortChannel, ...]:
    """Group ``this_host``'s core members (facing ``other_host``) by parent PC."""
    this_n, other_n = _norm(this_host), _norm(other_host)
    # Preserve first-seen order of parent PCs; dedup members within each.
    grouped: t.Dict[str, t.List[str]] = {}
    for ckt in circuits:
        if (ckt.role_name or "").upper() == _IXIA_ROLE:
            continue
        a, z = _endpoints(ckt)
        devices = {_norm(a.device.name), _norm(z.device.name)}
        if devices != {this_n, other_n}:
            continue
        # Pick the endpoint that belongs to this_host.
        local = a if _norm(a.device.name) == this_n else z
        if local.aggregated_interface is None:
            continue  # not a port-channel member (skip lone L3 core links)
        parent = local.aggregated_interface.name
        members = grouped.setdefault(parent, [])
        if local.name not in members:
            members.append(local.name)
    return tuple(
        CorePortChannel(name=parent, members=tuple(members))
        for parent, members in grouped.items()
    )


def _ixia_edges_for(
    this_host: str, circuits: t.Sequence[DesiredCircuitRecord]
) -> t.Tuple[IxiaEdge, ...]:
    """Collect this_host's IXIA edges (DUT iface ↔ IXIA slot/port)."""
    this_n = _norm(this_host)
    edges: t.List[IxiaEdge] = []
    seen: t.Set[t.Tuple[str, str]] = set()
    for ckt in circuits:
        a, z = _endpoints(ckt)
        is_ixia_role = (ckt.role_name or "").upper() == _IXIA_ROLE
        a_is_this = _norm(a.device.name) == this_n
        z_is_this = _norm(z.device.name) == this_n
        if not (a_is_this or z_is_this):
            continue
        dut_ep = a if a_is_this else z
        peer_ep = z if a_is_this else a
        peer_is_ixia = is_ixia_role or "ixia" in _norm(peer_ep.device.name)
        if not peer_is_ixia:
            continue
        key = (dut_ep.name, peer_ep.name)
        if key in seen:
            continue
        seen.add(key)
        edges.append(IxiaEdge(dut_interface=dut_ep.name, ixia_port=peer_ep.name))
    return tuple(edges)


def _default_node(role: str, hostname: str) -> NodeTopology:
    edges = _DEFAULT_R1_IXIA_EDGES if role == "r1" else _DEFAULT_R2_IXIA_EDGES
    return NodeTopology(
        role=role,
        hostname=hostname,
        core_pcs=tuple(
            CorePortChannel(name=name, members=members)
            for name, members in _DEFAULT_CORE_PCS
        ),
        ixia_edges=tuple(IxiaEdge(dut_interface=i, ixia_port=p) for i, p in edges),
    )


def load_rbb_topology(
    r1_host: t.Optional[str] = None,
    r2_host: t.Optional[str] = None,
    circuit_info_path: t.Optional[str] = None,
    ixia_chassis: t.Optional[str] = None,
) -> RbbTopology:
    """Build the RBB topology from circuit_info CSV + env (generic fallback).

    Args:
        r1_host / r2_host: RBB DUT hostnames; default to ``TAAC_RBB_R1_HOST`` /
            ``TAAC_RBB_R2_HOST`` (or the generic ``bgp_rbb_constants`` defaults).
        circuit_info_path: circuit_info CSV; defaults to ``TAAC_CIRCUIT_INFO_PATH``.
        ixia_chassis: IXIA chassis handle; default ``TAAC_RBB_IXIA_CHASSIS``.
    """
    r1_host = r1_host or os.environ.get("TAAC_RBB_R1_HOST") or C.R1_HOSTNAME
    r2_host = r2_host or os.environ.get("TAAC_RBB_R2_HOST") or C.R2_HOSTNAME
    ixia_chassis = (
        ixia_chassis or os.environ.get("TAAC_RBB_IXIA_CHASSIS") or C.IXIA_CHASSIS
    )
    circuit_info_path = circuit_info_path or os.environ.get("TAAC_CIRCUIT_INFO_PATH")

    circuits: t.List[DesiredCircuitRecord] = []
    if circuit_info_path and os.path.exists(circuit_info_path):
        circuits, _ = load_circuit_info(circuit_info_path)

    if not circuits:
        return RbbTopology(
            r1=_default_node("r1", r1_host),
            r2=_default_node("r2", r2_host),
            ixia_chassis=ixia_chassis,
        )

    r1_core = _core_pcs_for(r1_host, r2_host, circuits)
    r2_core = _core_pcs_for(r2_host, r1_host, circuits)
    r1_ixia = _ixia_edges_for(r1_host, circuits)
    r2_ixia = _ixia_edges_for(r2_host, circuits)

    # Per-piece fallback: if the CSV didn't describe some piece, use generics so
    # the builders still produce a valid (if placeholder) config.
    r1_default = _default_node("r1", r1_host)
    r2_default = _default_node("r2", r2_host)
    r1 = NodeTopology(
        role="r1",
        hostname=r1_host,
        core_pcs=r1_core or r1_default.core_pcs,
        ixia_edges=r1_ixia or r1_default.ixia_edges,
    )
    r2 = NodeTopology(
        role="r2",
        hostname=r2_host,
        core_pcs=r2_core or r2_default.core_pcs,
        ixia_edges=r2_ixia or r2_default.ixia_edges,
    )
    return RbbTopology(r1=r1, r2=r2, ixia_chassis=ixia_chassis)
