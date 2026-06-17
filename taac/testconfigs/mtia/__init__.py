# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""MTIA testconfigs package — re-exports from member modules.

Allows callers to use the package-level path:
    from taac.testconfigs.mtia import (
        create_mtia_eibgp_test_config,
    )

instead of the deeper module path.
"""

from taac.testconfigs.mtia.mtia_eibgp_test_configs import (
    create_mtia_eibgp_test_config,
)

__all__ = [
    "create_mtia_eibgp_test_config",
]
