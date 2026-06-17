# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""ai_bb testconfigs package — re-exports from member modules.

Allows callers to use the package-level path:
    from taac.testconfigs.ai_bb import (
        CBAG_BAG_TEST_CONFIGS,
    )

instead of the deeper module path.
"""

from taac.testconfigs.ai_bb.cbag_bag_test_config import (
    CBAG_BAG_TEST_CONFIGS,
)
from taac.testconfigs.ai_bb.cpr_bc_test_config import (
    CPR_BC_TEST_CONFIGS,
)
from taac.testconfigs.ai_bb.dsf_hardening_test_config import (
    RDSW004_C085_N001_SNC1_HARDENING_NODE,
)
from taac.testconfigs.ai_bb.dsf_snc1_c084_test_config import (
    TEST_SNC1_C084_DSF_FR4_LITE_OPTICS,
)
from taac.testconfigs.ai_bb.edsw003_n001_l201_snc1_hardening_test_config import (
    EDSW003_N001_L201_SNC1_HARDENING_NODE,
)
from taac.testconfigs.ai_bb.mp3n_bgp_path_scale_test_config import (
    EXP1_1_5M_ECMP52,
    EXP3_4M_ECMP120,
    EXP5_4M_ECMP240,
)
from taac.testconfigs.ai_bb.mp3n_prefix_profiling_ixia_config import (
    CONTIGUOUS_PREFIX_ALL,
    CONTIGUOUS_PREFIX_ALL_SETUP_ONLY,
    HYBRID_PREFIX_ALL,
    NON_CONTIGUOUS_PREFIX_ALL,
)
from taac.testconfigs.ai_bb.wedge400_ecmp_resource_testing_config import (
    RTSW001_L1003_C084_ECMP_RESOURCE_TESTING,
    RTSW001_U001_C081_ECMP_RESOURCE_TESTING,
)

__all__ = [
    "CBAG_BAG_TEST_CONFIGS",
    "CPR_BC_TEST_CONFIGS",
    "CONTIGUOUS_PREFIX_ALL",
    "CONTIGUOUS_PREFIX_ALL_SETUP_ONLY",
    "EDSW003_N001_L201_SNC1_HARDENING_NODE",
    "EXP1_1_5M_ECMP52",
    "EXP3_4M_ECMP120",
    "EXP5_4M_ECMP240",
    "HYBRID_PREFIX_ALL",
    "NON_CONTIGUOUS_PREFIX_ALL",
    "RDSW004_C085_N001_SNC1_HARDENING_NODE",
    "RTSW001_L1003_C084_ECMP_RESOURCE_TESTING",
    "RTSW001_U001_C081_ECMP_RESOURCE_TESTING",
    "TEST_SNC1_C084_DSF_FR4_LITE_OPTICS",
]
