# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""Spec 2.2 — Peer Lifecycle Within Update Groups. SKELETON testconfig factory.

Empty-playbook placeholder. Establishes the lifecycle-binding surface while the
qualification plan enumerates all 7 UG spec sections; sub-spec playbook
implementations pending.

Sub-specs to implement:
- 2.2.1 Peer Down: Remaining Group Members Unaffected
- 2.2.2 Peer Reconnect: Re-Sync from Shadow RIB
- 2.2.3 Sustained Group Membership Churn: No Memory Leak
"""

from taac.abstractions.physical_inventory import PhysicalInventory
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import Endpoint, TestConfig


def create_bgp_ug_peer_lifecycle_test_config(
    physical_inventory: PhysicalInventory,
) -> taac_types.TestConfig:
    """Spec 2.2 — Peer Lifecycle Within Update Groups. SKELETON qualification testconfig."""
    return TestConfig(
        name="BGP_UG_PEER_LIFECYCLE_TEST",
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
