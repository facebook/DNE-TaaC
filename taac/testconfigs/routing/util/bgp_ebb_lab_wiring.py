# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""Shared IXIA-wiring helpers for EBB factories.

Wave 4.5B retired the ``_lab_device_wiring`` helper — its output
(``host_driver_args`` + ``oss_mock_device_data``) is now stored on
``PhysicalInventory`` as first-class fields, so factories read the values
directly from the physical_inventory object instead of calling a helper. This
module now only hosts ``_direct_ixia_conns_two_port``, which stays a
helper because it derives from ``physical_inventory.ixia_ports`` (a runtime layout
that does not fit cleanly on the frozen dataclass).
"""

from taac.testconfigs.routing.physical_inventory import (
    PhysicalInventory,
)
from taac.test_as_a_config.types import DirectIxiaConnection


def _direct_ixia_conns_two_port(
    physical_inventory: PhysicalInventory,
) -> list[DirectIxiaConnection]:
    """Two ``DirectIxiaConnection`` entries (eBGP + iBGP) derived from physical_inventory.

    Matches the layout the case1/3/4/6/9 legacy factories use: only the first
    two ``physical_inventory.ixia_ports`` entries are wired (BGP-MON is unused).
    """
    ebgp_iface, ebgp_port = physical_inventory.ixia_ports[0]
    ibgp_iface, ibgp_port = physical_inventory.ixia_ports[1]
    return [
        DirectIxiaConnection(
            interface=ebgp_iface,
            ixia_chassis_ip=physical_inventory.ixia_chassis_ip,
            ixia_port=ebgp_port,
        ),
        DirectIxiaConnection(
            interface=ibgp_iface,
            ixia_chassis_ip=physical_inventory.ixia_chassis_ip,
            ixia_port=ibgp_port,
        ),
    ]
