# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""BGP++ verify qualification testconfigs (FA-UU FA001-UU001 in QZD1).

Wave 5D.2 -- migrates the 2 thin wrappers previously living at
``testconfigs/routing/ebb/bgp_plus_plus_verify_computational_load_test_config.py``
and
``testconfigs/routing/ebb/bgp_plus_plus_verify_constant_attribute_storage_test_config.py``
into this catalog. Each ``TestConfig.name`` string is grandfathered from
the legacy wrapper (note plural ``TEST_CONFIGS`` suffix) so the golden
manifest hash is byte-wise identical.

External consumers import via ``testconfigs.routing`` root; see README.md §7.
"""

from taac.abstractions.physical_inventory import FA001_UU001_QZD1
from taac.testconfigs.routing.factories.bgp_ebb_characteristic import (
    create_bgp_ebb_characteristic_verify_computational_load_test_config,
    create_bgp_ebb_characteristic_verify_constant_attribute_storage_test_config,
)


BGP_PLUS_PLUS_VERIFY_COMPUTATIONAL_LOAD_TEST_CONFIG = (
    create_bgp_ebb_characteristic_verify_computational_load_test_config(
        FA001_UU001_QZD1,
        name="BGP_PLUS_PLUS_VERIFY_COMPUTATIONAL_LOAD_TEST_CONFIGS",
    )
)


BGP_PLUS_PLUS_VERIFY_CONSTANT_ATTRIBUTE_STORAGE_TEST_CONFIG = (
    create_bgp_ebb_characteristic_verify_constant_attribute_storage_test_config(
        FA001_UU001_QZD1,
        name="BGP_PLUS_PLUS_VERIFY_CONSTANT_ATTRIBUTE_STORAGE_TEST_CONFIGS",
    )
)


__all__ = [
    "BGP_PLUS_PLUS_VERIFY_COMPUTATIONAL_LOAD_TEST_CONFIG",
    "BGP_PLUS_PLUS_VERIFY_CONSTANT_ATTRIBUTE_STORAGE_TEST_CONFIG",
]
