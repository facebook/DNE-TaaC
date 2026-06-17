# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import typing as t

from taac.ai_bb.dsf.dsf_test_handler import DsfTestHandler
from taac.custom_test_handlers.base_custom_test_handler import (
    BaseCustomTestHandler,
)
from taac.custom_test_handlers.patcher_cleanup_handler import (
    PatcherCleanupHandler,
)


# pyre-ignore
CUSTOM_TEST_HANDLERS: t.List[BaseCustomTestHandler] = [
    DsfTestHandler,
    PatcherCleanupHandler,
]
