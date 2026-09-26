# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""W800 NPI snake testconfigs package — re-exports from member modules.

Allows callers to use the package-level path:
    from taac.testconfigs.snake.w800 import (
        W800_NPI_SNAKE_TEST_CONFIGS,
    )

instead of the deeper module path.
"""

from taac.testconfigs.snake.w800.w800_npi_snake_test_config import (
    W800_NPI_SNAKE_TEST_CONFIGS,
)

__all__ = ["W800_NPI_SNAKE_TEST_CONFIGS"]
