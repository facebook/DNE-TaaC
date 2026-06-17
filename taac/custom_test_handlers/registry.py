# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import os
import typing as t

from taac.custom_test_handlers.base_custom_test_handler import (
    BaseCustomTestHandler,
)
from taac.custom_test_handlers.patcher_cleanup_handler import (
    PatcherCleanupHandler,
)

TAAC_OSS = os.environ.get("TAAC_OSS", "").lower() in ("1", "true", "yes")

# pyre-ignore
CUSTOM_TEST_HANDLERS: t.List[BaseCustomTestHandler] = [
    PatcherCleanupHandler,
]

if not TAAC_OSS:
    # DsfTestHandler lives in the Meta-internal taac.ai_bb subpackage which
    # isn't shipped in the OSS slice.
    from taac.ai_bb.dsf.dsf_test_handler import DsfTestHandler

    # pyre-ignore[6]: registry holds handler classes, annotated as instances.
    CUSTOM_TEST_HANDLERS.append(DsfTestHandler)
