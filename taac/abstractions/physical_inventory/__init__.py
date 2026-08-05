# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict
"""DICE physical inventory model and concrete testbed inventories."""

from taac.abstractions.physical_inventory.physical_inventory import (
    PhysicalInventory,
    VALID_USAGES,
)
from taac.abstractions.physical_inventory.routing_cte_testbed import (
    CTE_UCMP_QZD_PHYSICAL_INVENTORY,
    CTE_UCMP_STAND_ALONE_PHYSICAL_INVENTORY,
)
from taac.abstractions.physical_inventory.routing_dcn_testbed import (
    FA001_UU001_QZD1,
    FSW001_QZB,
    FSW_FUJI_QZD1,
    FSW_P001_QZD1,
    FSW_P006_QZD1,
    FSW_QZB,
    QZD_FSW002,
    QZD_LAB,
    SSW_ELBERT_QZD1,
)
from taac.abstractions.physical_inventory.routing_ebb_testbed import (
    BAG002_SNC1,
    BAG010_ASH6,
    BAG011_ASH6,
    BAG012_ASH6,
    BAG013_ASH6,
    EB01_LAB_ASH6,
    EB02_LAB_ASH6,
    EB03_LAB_ASH6,
    EB04_LAB_ASH6,
    EB_TEST_DEVICE,
    JSW002_M001_SNC1,
)

__all__ = (
    "BAG002_SNC1",
    "BAG010_ASH6",
    "BAG011_ASH6",
    "BAG012_ASH6",
    "BAG013_ASH6",
    "CTE_UCMP_QZD_PHYSICAL_INVENTORY",
    "CTE_UCMP_STAND_ALONE_PHYSICAL_INVENTORY",
    "EB_TEST_DEVICE",
    "EB01_LAB_ASH6",
    "EB02_LAB_ASH6",
    "EB03_LAB_ASH6",
    "EB04_LAB_ASH6",
    "FA001_UU001_QZD1",
    "FSW_FUJI_QZD1",
    "FSW_P001_QZD1",
    "FSW_P006_QZD1",
    "FSW_QZB",
    "FSW001_QZB",
    "JSW002_M001_SNC1",
    "PhysicalInventory",
    "QZD_FSW002",
    "QZD_LAB",
    "SSW_ELBERT_QZD1",
    "VALID_USAGES",
)
