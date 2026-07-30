# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""Spec 2.5 — Multi-Group Formation Correctness. SKELETON testconfig factory.

Empty-playbook placeholder. Establishes the lifecycle-binding surface while the
qualification plan enumerates all 7 UG spec sections; sub-spec playbook
implementations pending.

Sub-specs to implement:
- 2.5.1 Multiple Groups Formed for Different Outbound Policies
- 2.5.2 Scale Withdraw: 10+ Peers in Same Group, Withdraw Routes
"""

from taac.abstractions.physical_inventory import PhysicalInventory
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import Endpoint, TestConfig


def create_bgp_ug_multigroup_formation_test_config(
    physical_inventory: PhysicalInventory,
) -> taac_types.TestConfig:
    """Spec 2.5 — Multi-Group Formation Correctness. SKELETON qualification testconfig."""
    return TestConfig(
        name="BGP_UG_MULTIGROUP_FORMATION_TEST",
        endpoints=[
            Endpoint(
                name=physical_inventory.device_name,
                dut=True,
                ixia_ports=[physical_inventory.ixia_ports[0][0]]
                if physical_inventory.ixia_ports
                else [],
            ),
        ],
        playbooks=[],
    )
