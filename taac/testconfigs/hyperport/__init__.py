# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""Hyperport testconfigs package — re-exports from member modules.

Allows callers to use the package-level path:
    from taac.testconfigs.hyperport import (
        EDSW003_BGP_PATH_SCALE_TEST_CONFIGS,
    )

instead of the deeper module path.
"""

# Side-effect import: registers the file with `sys.modules` so the
# inline-construction gates can scan it. The module exposes a builder
# (`test_config_for_edsw_ecmp_scale_3port`) plus a single TestConfig instance
# (`EDSW003_N001_ECMP_SCALE_3PORT`) that is intentionally NOT in
# INTERNAL_TEST_CONFIGS — it is invoked ad-hoc via `--test-config`.
import taac.testconfigs.hyperport.hyperport_edsw003_ecmp_scale_test_config  # noqa: F401
from taac.testconfigs.hyperport.hyperport_edsw003_bgp_path_scale_test_config import (
    EDSW003_BGP_PATH_SCALE_TEST_CONFIGS,
)
from taac.testconfigs.hyperport.hyperport_edsw003_dsf_hardening_test_config import (
    EDSW003_N001_DSF_HARDENING_TEST_CONFIGS,
)
from taac.testconfigs.hyperport.hyperport_snc_bag_test_configs import (
    HYPERPORT_SNC_BAG_TEST_CONFIGS,
)
from taac.testconfigs.hyperport.hyperport_vrf_bag_n000_edsw_dut_test_configs import (
    HYPERPORT_VRF_BAG_N000_EDSW_DUT_TEST_CONFIGS,
)
from taac.testconfigs.hyperport.hyperport_vrf_bag_n000_test_configs import (
    HYPERPORT_VRF_BAG_N000_TEST_CONFIGS,
)
from taac.testconfigs.hyperport.hyperport_vrf_bag_test_configs import (
    HYPERPORT_VRF_BAG_TEST_CONFIGS,
)

__all__ = [
    "EDSW003_BGP_PATH_SCALE_TEST_CONFIGS",
    "EDSW003_N001_DSF_HARDENING_TEST_CONFIGS",
    "HYPERPORT_SNC_BAG_TEST_CONFIGS",
    "HYPERPORT_VRF_BAG_N000_EDSW_DUT_TEST_CONFIGS",
    "HYPERPORT_VRF_BAG_N000_TEST_CONFIGS",
    "HYPERPORT_VRF_BAG_TEST_CONFIGS",
]
