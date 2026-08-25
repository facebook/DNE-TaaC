# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""1-RSW testconfigs package — re-exports from member modules.

Allows callers to use the package-level path:
    from taac.testconfigs.single_dut_rsw import gen_rsw_test_config

instead of the deeper module path.
"""

from taac.testconfigs.single_dut_rsw.single_dut_rsw_test_config import (
    gen_rsw_test_config,
)

__all__ = ["gen_rsw_test_config"]
