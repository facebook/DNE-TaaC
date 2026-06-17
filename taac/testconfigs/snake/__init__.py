# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""Snake testconfigs package — re-exports from member modules.

Allows callers to use the package-level path:
    from taac.testconfigs.snake import SNAKE_TEST_CONFIGS

instead of the deeper module path.
"""

from taac.testconfigs.snake.test_test_config import (
    SNAKE_TEST_CONFIGS,
)

__all__ = ["SNAKE_TEST_CONFIGS"]
