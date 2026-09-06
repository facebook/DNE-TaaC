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
hostnames. When no circuit CSV is supplied, read-only factory inspection may use
generic documentation-only placeholder wiring. Live traffic requires an
explicit, complete CSV. No secrets are read here (credentials stay in
``TAAC_SSH_*`` at run time).
"""

from __future__ import annotations

import os
import re
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
_IXIA_PORT_RE = re.compile(r"^[0-9]+/[0-9]+$")


class RbbTopologyError(ValueError):
    """The caller-provided RBB wiring is missing, ambiguous, or inconsistent."""


@dataclass(frozen=True)
class CorePortChannel:
    """One core port-channel on a node, with its member interfaces."""

    name: str  # parent port-channel name as in the CSV, e.g. "port-channel1"
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
    traffic_ixia_interface: t.Optional[str] = None

    @property
    def ixia_port_tuples(self) -> t.List[t.Tuple[str, str]]:
        """``(dut_interface, ixia_port)`` list for ``PhysicalInventory``."""
        return [(e.dut_interface, e.ixia_port) for e in self.ixia_edges]

    @property
    def primary_ixia_interface(self) -> t.Optional[str]:
        """IXIA-facing interface selected for this two-port traffic model."""
        if self.traffic_ixia_interface:
            selected = next(
                (
                    edge.dut_interface
                    for edge in self.ixia_edges
                    if _norm(edge.dut_interface)
                    == _norm(self.traffic_ixia_interface)
                ),
                None,
            )
            # Preserve the invalid token when it has no match so validation can
            # report the user's value rather than silently choosing another link.
            return selected or self.traffic_ixia_interface
        return self.ixia_edges[0].dut_interface if self.ixia_edges else None

    @property
    def primary_ixia_edge(self) -> t.Optional[IxiaEdge]:
        """Selected DUT/IXIA edge, or the first declared edge by CSV order."""
        interface = self.primary_ixia_interface
        return next(
            (
                edge
                for edge in self.ixia_edges
                if _norm(edge.dut_interface) == _norm(interface)
            ),
            None,
        )

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
        if role == "r1":
            return self.r1
        if role == "r2":
            return self.r2
        raise RbbTopologyError(f"unknown RBB role {role!r}; expected 'r1' or 'r2'")


def validate_rbb_topology(
    topology: RbbTopology,
    *,
    require_ixia: bool = False,
) -> None:
    """Validate the topology contract before any task can touch a device.

    Port and port-channel names are intentionally user-owned.  This validates
    only relationships required by the two-node scenario; it never assumes the
    reference lab's interface numbering.
    """
    errors: t.List[str] = []
    if not topology.r1.hostname or not topology.r2.hostname:
        errors.append("both R1 and R2 hostnames are required")
    elif _norm(topology.r1.hostname) == _norm(topology.r2.hostname):
        errors.append("R1 and R2 must resolve to different hostnames")
    if topology.r1.role != "r1" or topology.r2.role != "r2":
        errors.append(
            "RbbTopology endpoints must have matching roles "
            f"(r1.role={topology.r1.role!r}, r2.role={topology.r2.role!r})"
        )

    for node in (topology.r1, topology.r2):
        if not node.core_pcs:
            errors.append(f"{node.hostname}: no R1<->R2 core port-channel declared")

        pc_names: t.Set[str] = set()
        core_members: t.Set[str] = set()
        for pc in node.core_pcs:
            if not pc.name.strip():
                errors.append(f"{node.hostname}: core port-channel has no name")
            elif _norm(pc.name) in pc_names:
                errors.append(
                    f"{node.hostname}: duplicate core port-channel {pc.name!r}"
                )
            pc_names.add(_norm(pc.name))
            if not pc.members:
                errors.append(
                    f"{node.hostname}: core port-channel {pc.name!r} has no members"
                )
            for member in pc.members:
                if not member.strip():
                    errors.append(
                        f"{node.hostname}: core port-channel {pc.name!r} has an empty member"
                    )
                elif _norm(member) in core_members:
                    errors.append(
                        f"{node.hostname}: core member {member!r} is assigned more than once"
                    )
                core_members.add(_norm(member))

        if require_ixia and not node.ixia_edges:
            errors.append(
                f"{node.hostname}: this traffic model requires at least one IXIA edge"
            )
        seen_dut_edges: t.Set[str] = set()
        seen_ixia_ports: t.Set[str] = set()
        for edge in node.ixia_edges:
            if not edge.dut_interface.strip():
                errors.append(f"{node.hostname}: IXIA edge has no DUT interface")
            elif _norm(edge.dut_interface) in seen_dut_edges:
                errors.append(
                    f"{node.hostname}: duplicate IXIA DUT interface "
                    f"{edge.dut_interface!r}"
                )
            seen_dut_edges.add(_norm(edge.dut_interface))
            if not _IXIA_PORT_RE.fullmatch(edge.ixia_port.strip()):
                errors.append(
                    f"{node.hostname}: IXIA port {edge.ixia_port!r} must be slot/port"
                )
            elif edge.ixia_port in seen_ixia_ports:
                errors.append(
                    f"{node.hostname}: duplicate IXIA port {edge.ixia_port!r}"
                )
            seen_ixia_ports.add(edge.ixia_port)
            if _norm(edge.dut_interface) in core_members:
                errors.append(
                    f"{node.hostname}: interface {edge.dut_interface!r} cannot be "
                    "both a core member and an IXIA edge"
                )
        if node.traffic_ixia_interface and not any(
            _norm(edge.dut_interface) == _norm(node.traffic_ixia_interface)
            for edge in node.ixia_edges
        ):
            errors.append(
                f"{node.hostname}: selected traffic interface "
                f"{node.traffic_ixia_interface!r} is not one of its IXIA edges"
            )

    if len(topology.r1.core_pcs) != len(topology.r2.core_pcs):
        errors.append(
            "R1 and R2 must declare the same number of core port-channels "
            f"(got {len(topology.r1.core_pcs)} and {len(topology.r2.core_pcs)})"
        )
    else:
        for index, (r1_pc, r2_pc) in enumerate(
            zip(topology.r1.core_pcs, topology.r2.core_pcs)
        ):
            if len(r1_pc.members) != len(r2_pc.members):
                errors.append(
                    f"core port-channel pair {index} has asymmetric member "
                    f"counts ({r1_pc.name}={len(r1_pc.members)}, "
                    f"{r2_pc.name}={len(r2_pc.members)})"
                )

    if require_ixia:
        r1_ports = {edge.ixia_port for edge in topology.r1.ixia_edges}
        r2_ports = {edge.ixia_port for edge in topology.r2.ixia_edges}
        overlap = sorted(r1_ports & r2_ports)
        if overlap:
            errors.append(f"IXIA ports are assigned to both DUTs: {overlap}")
    if require_ixia and not topology.ixia_chassis.strip():
        errors.append("an IXIA chassis is required when traffic is enabled")

    if errors:
        raise RbbTopologyError("invalid RBB topology: " + "; ".join(errors))


# ─── CSV → topology derivation ─────────────────────────────────────────────
def _norm(name: t.Optional[str]) -> str:
    return (name or "").strip().lower()


def _endpoints(circuit: DesiredCircuitRecord) -> t.Tuple[EndpointRecord, EndpointRecord]:
    return circuit.a_endpoint, circuit.z_endpoint


def _is_active(circuit: DesiredCircuitRecord) -> bool:
    """Match the OSS circuit loader's active-status contract."""
    return circuit.status is None or circuit.status == "3"


def _core_pcs_for(
    this_host: str, other_host: str, circuits: t.Sequence[DesiredCircuitRecord]
) -> t.Tuple[CorePortChannel, ...]:
    """Group ``this_host``'s core members (facing ``other_host``) by parent PC."""
    this_n, other_n = _norm(this_host), _norm(other_host)
    # Preserve first-seen order of parent PCs; dedup members within each.
    grouped: t.Dict[str, t.List[str]] = {}
    for ckt in circuits:
        if not _is_active(ckt):
            continue
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


def _validate_core_pairing(
    r1_host: str,
    r2_host: str,
    circuits: t.Sequence[DesiredCircuitRecord],
) -> None:
    """Require each local LAG to connect to exactly one peer LAG.

    Counting LAGs and members is not sufficient: two equally sized bundles can
    still be cross-wired member-by-member. Reject that shape before a test can
    select either bundle for SRv6 path checks.
    """
    r1_n, r2_n = _norm(r1_host), _norm(r2_host)
    peer_parents: t.Dict[t.Tuple[str, str], t.Set[str]] = {}
    errors: t.List[str] = []
    for circuit in circuits:
        if not _is_active(circuit):
            continue
        if (circuit.role_name or "").upper() == _IXIA_ROLE:
            continue
        a, z = _endpoints(circuit)
        if {_norm(a.device.name), _norm(z.device.name)} != {r1_n, r2_n}:
            continue
        a_parent = a.aggregated_interface
        z_parent = z.aggregated_interface
        if (a_parent is None) != (z_parent is None):
            errors.append(
                f"core link {a.device.name}:{a.name}<->{z.device.name}:{z.name} "
                "declares a port-channel parent on only one endpoint"
            )
            continue
        if a_parent is None or z_parent is None:
            continue
        a_key = (_norm(a.device.name), _norm(a_parent.name))
        z_key = (_norm(z.device.name), _norm(z_parent.name))
        peer_parents.setdefault(a_key, set()).add(z_key[1])
        peer_parents.setdefault(z_key, set()).add(a_key[1])

    for (hostname, parent), peers in sorted(peer_parents.items()):
        if len(peers) > 1:
            errors.append(
                f"{hostname}:{parent} has members wired across peer "
                f"port-channels {sorted(peers)}"
            )
    if errors:
        raise RbbTopologyError("invalid RBB topology: " + "; ".join(errors))


def _ixia_edges_for(
    this_host: str, circuits: t.Sequence[DesiredCircuitRecord]
) -> t.Tuple[IxiaEdge, ...]:
    """Collect this_host's IXIA edges (DUT iface ↔ IXIA slot/port)."""
    this_n = _norm(this_host)
    edges: t.List[IxiaEdge] = []
    seen: t.Set[t.Tuple[str, str]] = set()
    for ckt in circuits:
        if not _is_active(ckt):
            continue
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
        traffic_ixia_interface=os.environ.get(
            f"TAAC_RBB_{role.upper()}_IXIA_INTERFACE"
        ),
    )


def load_rbb_topology(
    r1_host: t.Optional[str] = None,
    r2_host: t.Optional[str] = None,
    circuit_info_path: t.Optional[str] = None,
    ixia_chassis: t.Optional[str] = None,
    *,
    allow_placeholder: bool = True,
    require_ixia: bool = False,
) -> RbbTopology:
    """Build the RBB topology from circuit_info CSV + env.

    Args:
        r1_host / r2_host: RBB DUT hostnames; default to ``TAAC_RBB_R1_HOST`` /
            ``TAAC_RBB_R2_HOST`` (or the generic ``bgp_rbb_constants`` defaults).
        circuit_info_path: circuit_info CSV; defaults to ``TAAC_CIRCUIT_INFO_PATH``.
        ixia_chassis: IXIA chassis handle; default ``TAAC_RBB_IXIA_CHASSIS``.
        allow_placeholder: permit documentation-only wiring when no CSV was
            supplied. Live traffic callers must set this False.
        require_ixia: require at least one IXIA edge per DUT. If several are
            declared, ``TAAC_RBB_R{1,2}_IXIA_INTERFACE`` selects the one used.
    """
    r1_host = r1_host or os.environ.get("TAAC_RBB_R1_HOST") or C.R1_HOSTNAME
    r2_host = r2_host or os.environ.get("TAAC_RBB_R2_HOST") or C.R2_HOSTNAME
    explicit_ixia_chassis = ixia_chassis or os.environ.get("TAAC_RBB_IXIA_CHASSIS")
    if require_ixia and not explicit_ixia_chassis:
        raise RbbTopologyError(
            "TAAC_RBB_IXIA_CHASSIS (or ixia_chassis=) is required for live "
            "RBB traffic; the committed chassis name is only a "
            "placeholder"
        )
    ixia_chassis = explicit_ixia_chassis or C.IXIA_CHASSIS
    circuit_info_path = circuit_info_path or os.environ.get("TAAC_CIRCUIT_INFO_PATH")

    circuits: t.List[DesiredCircuitRecord] = []
    if circuit_info_path:
        if not os.path.isfile(circuit_info_path):
            raise RbbTopologyError(
                f"circuit-info CSV does not exist: {circuit_info_path}"
            )
        circuits, _ = load_circuit_info(circuit_info_path)
        if not circuits:
            raise RbbTopologyError(
                f"circuit-info CSV has no usable circuits: {circuit_info_path}"
            )

    if not circuits:
        if not allow_placeholder:
            raise RbbTopologyError(
                "TAAC_CIRCUIT_INFO_PATH is required for live RBB traffic; "
                "placeholder wiring is documentation-only"
            )
        topology = RbbTopology(
            r1=_default_node("r1", r1_host),
            r2=_default_node("r2", r2_host),
            ixia_chassis=ixia_chassis,
        )
        validate_rbb_topology(
            topology,
            require_ixia=require_ixia,
        )
        return topology

    _validate_core_pairing(r1_host, r2_host, circuits)
    r1_core = _core_pcs_for(r1_host, r2_host, circuits)
    r2_core = _core_pcs_for(r2_host, r1_host, circuits)
    r1_ixia = _ixia_edges_for(r1_host, circuits)
    r2_ixia = _ixia_edges_for(r2_host, circuits)

    r1 = NodeTopology(
        role="r1",
        hostname=r1_host,
        core_pcs=r1_core,
        ixia_edges=r1_ixia,
        traffic_ixia_interface=os.environ.get("TAAC_RBB_R1_IXIA_INTERFACE"),
    )
    r2 = NodeTopology(
        role="r2",
        hostname=r2_host,
        core_pcs=r2_core,
        ixia_edges=r2_ixia,
        traffic_ixia_interface=os.environ.get("TAAC_RBB_R2_IXIA_INTERFACE"),
    )
    topology = RbbTopology(r1=r1, r2=r2, ixia_chassis=ixia_chassis)
    validate_rbb_topology(
        topology,
        require_ixia=require_ixia,
    )
    return topology
