# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""Physical inventories for routing CTE testbeds."""

from taac.abstractions.physical_inventory.physical_inventory import (
    PhysicalInventory,
)


# ─── CTE UCMP physical inventories ────────────────────────────────────────────────────
# Wave 2C — CTE UCMP feature testconfigs (moved from testconfigs/routing/
# test_config_cte_ucmp{,_stand_alone}.py). The multi-node QZD topology
# (4 endpoints, no shared chassis IP) does not fit the flat PhysicalInventory dataclass;
# only the DUT identity is captured here and the spine + IXIA-port layout
# stays as private module-level constants inside factories/cte_ucmp.py.

CTE_UCMP_QZD_PHYSICAL_INVENTORY = PhysicalInventory(
    usage=frozenset({"adhoc"}),
    device_name="fa001-du004.qzd1",
    # No shared IXIA chassis IP: the QZD test config uses per-endpoint
    # ``ixia_ports`` strings and does not declare a chassis IP anywhere.
    # ``ixia_ports`` stays empty for the same reason (per-endpoint port lists
    # live on Endpoint objects built inside the factory).
    primary_ixia_chassis_ip="",
)

CTE_UCMP_STAND_ALONE_PHYSICAL_INVENTORY = PhysicalInventory(
    device_name="fsw003.p003.f01.qzd1",
    usage=frozenset({"adhoc"}),
    primary_ixia_chassis_ip="2401:db00:0116:303b:0000:0000:0000:0100",
    ixia_ports=[
        ("eth7/16/1", "6/2"),  # uplink (eBGP)
        ("eth8/16/1", "3/3"),  # downlink (12 confed peers across 3 DCs)
    ],
    mac_address="b6:a9:fc:34:2b:41",
)
