# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""BGP feature testconfigs (ad-hoc -- not on the CICD conveyor).

Wave 5B.1 -- absorbs the eb03.lab.ash6 wrappers previously living at
``testconfigs/routing/ebb/eb03_arista_well_known_community_test_config.py``,
``testconfigs/internal/arista_bgp_fast_reset_feature_test.py`` and
``testconfigs/internal/arista_bgp_weight_feature_test.py``. Wave 5B.2 --
extends with ``ARISTA_BGP_ENFORCE_FIRST_AS_FEATURE_TEST`` (from
``testconfigs/internal/arista_bgp_enforce_first_as_feature_test.py``) and
``ARISTA_BGP_MED_FEATURE_TEST`` (from
``testconfigs/internal/arista_bgp_med_feature_test.py``). Each binding
below preserves the legacy ``TestConfig.name`` verbatim via the factory
``name=`` kwarg so the golden manifest hash stays byte-wise identical.

External consumers import via ``testconfigs.routing`` root; see README.md §7.
"""

from taac.testconfigs.routing.factories.bgp_features import (
    create_bgp_feature_enforce_first_as_test_config,
    create_bgp_feature_fast_reset_test_config,
    create_bgp_feature_med_test_config,
    create_bgp_feature_weight_test_config,
    create_bgp_feature_well_known_communities_test_config,
)
from taac.testconfigs.routing.physical_inventory import (
    EB03_LAB_ASH6,
)


ARISTA_BGP_FAST_RESET_FEATURE_TEST = create_bgp_feature_fast_reset_test_config(
    EB03_LAB_ASH6,
    name="ARISTA_BGP_FAST_RESET_FEATURE_TEST",
)
ARISTA_BGP_WEIGHT_FEATURE_TEST = create_bgp_feature_weight_test_config(
    EB03_LAB_ASH6,
    name="ARISTA_BGP_WEIGHT_FEATURE_TEST",
)
EB03_ARISTA_RFC1997_WELL_KNOWN_COMMUNITY_FILTER_TEST = (
    create_bgp_feature_well_known_communities_test_config(
        EB03_LAB_ASH6,
        name="EB03-ARISTA_RFC1997_WELL_KNOWN_COMMUNITY_FILTER_TEST",
    )
)
ARISTA_BGP_ENFORCE_FIRST_AS_FEATURE_TEST = (
    create_bgp_feature_enforce_first_as_test_config(
        EB03_LAB_ASH6,
        name="ARISTA_BGP_ENFORCE_FIRST_AS_FEATURE_TEST",
    )
)
ARISTA_BGP_MED_FEATURE_TEST = create_bgp_feature_med_test_config(
    EB03_LAB_ASH6,
    name="ARISTA_BGP_MED_FEATURE_TEST",
)


__all__ = [
    "ARISTA_BGP_ENFORCE_FIRST_AS_FEATURE_TEST",
    "ARISTA_BGP_FAST_RESET_FEATURE_TEST",
    "ARISTA_BGP_MED_FEATURE_TEST",
    "ARISTA_BGP_WEIGHT_FEATURE_TEST",
    "EB03_ARISTA_RFC1997_WELL_KNOWN_COMMUNITY_FILTER_TEST",
]
