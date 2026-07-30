# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""CTE UCMP feature testconfigs (ad-hoc — not on the CICD conveyor).

This is an ``adhoc_`` lifecycle binding module. Both TestConfigs and their
Python constant names are grandfathered from
``testconfigs/routing/test_config_cte_ucmp{,_stand_alone}.py`` (Wave 2C
hierarchical move only). The internal ``TestConfig.name`` field is preserved
verbatim via the factory ``name=`` kwarg so the golden manifest stays
byte-wise identical.

External consumers import from this member module directly; see
``docs/routing/TESTCONFIGS.md``.
"""

from taac.abstractions.physical_inventory import (
    CTE_UCMP_QZD_PHYSICAL_INVENTORY,
    CTE_UCMP_STAND_ALONE_PHYSICAL_INVENTORY,
)
from taac.testconfigs.routing.factories.cte_ucmp import (
    create_cte_ucmp_qzd_test_config,
    create_cte_ucmp_stand_alone_test_config,
)


CTE_UCMP_QZD_TEST = create_cte_ucmp_qzd_test_config(
    CTE_UCMP_QZD_PHYSICAL_INVENTORY, name="CTE_UCMP_QZD_TEST"
)
CTE_UCMP_STAND_ALONE = create_cte_ucmp_stand_alone_test_config(
    CTE_UCMP_STAND_ALONE_PHYSICAL_INVENTORY, name="CTE_UCMP_STAND_ALONE"
)


__all__ = [
    "CTE_UCMP_QZD_TEST",
    "CTE_UCMP_STAND_ALONE",
]
