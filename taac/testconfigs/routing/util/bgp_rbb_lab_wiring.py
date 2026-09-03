# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""RBB SRv6 qualification — physical inventory (from topology).

Builds the ``PhysicalInventory`` artifacts for the two RBB SRv6 DUTs (R1
head/mid, R2 tail) from the run's derived ``RbbTopology`` (see
``bgp_rbb_topology``): device names come from ``TAAC_RBB_R1_HOST`` /
``TAAC_RBB_R2_HOST`` and the IXIA ports are the topology's IXIA edges
(``circuit_info.csv``), not hardcoded here.

Both are FBOSS boxes reached over SSH; credentials are NOT committed — the FBOSS
driver picks up ``TAAC_SSH_USER`` / ``TAAC_SSH_PASSWORD`` (or ``~/.taac-secrets``)
at run time (rule: no hardcoded credentials).

``netwhoami`` returns no record for lab boxes, so a synthesized
``MockDeviceInfo`` is supplied via ``oss_mock_device_data`` (mirrors the EBB
lab-box pattern in ``routing_ebb_testbed.py``).
"""

from __future__ import annotations

import typing as t

from taac.abstractions.physical_inventory.physical_inventory import (
    PhysicalInventory,
)
from taac.test_as_a_config.types import MockDeviceInfo
from taac.testconfigs.routing.util import bgp_rbb_constants as C
from taac.testconfigs.routing.util.bgp_rbb_topology import (
    load_rbb_topology,
    NodeTopology,
    RbbTopology,
)


def _rbb_mock_device_data(device_name: str) -> dict[str, MockDeviceInfo]:
    """Synthesize a FBOSS MockDeviceInfo for a lab box (netwhoami is empty).

    Field set mirrors the proven EBB lab-box helper; values are FBOSS/RBB
    appropriate. Fields are illustrative lab metadata only (no secrets).
    """
    return {
        device_name: MockDeviceInfo(
            name=device_name,
            hardware="CISCO_8501",
            role="RBB",
            operating_system="FBOSS",
            dc="lab",
            region="lab",
            asset_id=0,
            asic="",
            routing_protocol="BGP",
            dc_type="ONE",
            network_area="BACKBONE",
            network_area_type="BACKBONE",
        )
    }


def _inventory_for(
    node: NodeTopology,
    ixia_chassis: str,
    bgp_as: int,
    router_id: str,
) -> PhysicalInventory:
    """Build one DUT's PhysicalInventory from its NodeTopology."""
    return PhysicalInventory(
        usage=frozenset({"qual"}),
        device_name=node.hostname,
        primary_ixia_chassis_ip=ixia_chassis,
        ixia_ports=node.ixia_port_tuples,
        dut_bgp_as=bgp_as,
        router_id=router_id,
        oss_mock_device_data=_rbb_mock_device_data(node.hostname),
    )


def build_rbb_inventories(
    topology: t.Optional[RbbTopology] = None,
) -> t.Tuple[PhysicalInventory, PhysicalInventory]:
    """Return ``(RBB_R1, RBB_R2)`` PhysicalInventory built from the topology."""
    topology = topology if topology is not None else load_rbb_topology()
    r1 = _inventory_for(topology.r1, topology.ixia_chassis, C.R1_BGP_AS, C.R1_ROUTER_ID)
    r2 = _inventory_for(topology.r2, topology.ixia_chassis, C.R2_BGP_AS, C.R2_ROUTER_ID)
    return r1, r2


# Default inventories built from the ambient topology (env / CSV / generic
# fallback) for back-compat with callers that don't pass a topology.
RBB_R1, RBB_R2 = build_rbb_inventories()


def rbb_oss_mock_device_data(
    inventories: t.Optional[t.Sequence[PhysicalInventory]] = None,
) -> dict[str, MockDeviceInfo]:
    """Merged mock-device map for both RBB DUTs (for the TestConfig field)."""
    invs = inventories if inventories is not None else (RBB_R1, RBB_R2)
    merged: dict[str, MockDeviceInfo] = {}
    for inv in invs:
        merged.update(inv.oss_mock_device_data or {})
    return merged
