#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""Tests for custom-test-handler selection (``BaseCustomTestHandler.should_run``).

This single predicate decides whether a handler runs at all, so a silent
regression here turns a whole capability into a no-op — which is exactly what
happened to the OSS collectors before this was made explicit.

Note the patch target: ``collectors_test_handler.TAAC_OSS`` is bound at import
time from the environment (repo-wide convention), so patching ``os.environ``
has no effect here — the module constant is what must be patched.
"""

import typing as t
import unittest
from unittest.mock import MagicMock, patch

from taac.custom_test_handlers import collectors_test_handler
from taac.custom_test_handlers.base_custom_test_handler import (
    BaseCustomTestHandler,
)
from taac.custom_test_handlers.collectors_test_handler import (
    CollectorsTestHandler,
    OPT_OUT_TAG,
)


class TaggedHandler(BaseCustomTestHandler):
    SUPPORTED_TAGS = ["some_tag"]


class TestBaseShouldRun(unittest.TestCase):
    def test_selects_only_on_a_matching_tag(self) -> None:
        self.assertTrue(TaggedHandler.should_run(["some_tag"]))
        self.assertFalse(TaggedHandler.should_run(["other_tag"]))
        self.assertFalse(TaggedHandler.should_run([]))


class TestCollectorsHandlerShouldRun(unittest.TestCase):
    """The OSS collectors are baseline environment, not a per-test opt-in."""

    def test_runs_for_every_test_config_under_oss(self) -> None:
        with patch.object(collectors_test_handler, "TAAC_OSS", True):
            self.assertTrue(CollectorsTestHandler.should_run([]))
            self.assertTrue(CollectorsTestHandler.should_run(["unrelated_tag"]))

    def test_opt_out_tag_wins_under_oss(self) -> None:
        with patch.object(collectors_test_handler, "TAAC_OSS", True):
            self.assertFalse(CollectorsTestHandler.should_run([OPT_OUT_TAG]))

    def test_internal_mode_keeps_tag_based_opt_in(self) -> None:
        with patch.object(collectors_test_handler, "TAAC_OSS", False):
            self.assertFalse(CollectorsTestHandler.should_run([]))
            self.assertFalse(CollectorsTestHandler.should_run(["unrelated_tag"]))
            self.assertTrue(CollectorsTestHandler.should_run(["oss_collectors"]))


class TestRunnerDelegatesToShouldRun(unittest.TestCase):
    """The runner must consult should_run rather than carrying its own rule."""

    def test_collectors_handler_selected_under_oss_with_no_tags(self) -> None:
        from taac.libs.taac_runner import TaacRunner

        # filter_custom_test_handlers_by_tags only touches self.logger, so a
        # stand-in avoids constructing a whole runner (and its topology).
        with patch.object(collectors_test_handler, "TAAC_OSS", True):
            handlers = TaacRunner.filter_custom_test_handlers_by_tags(
                t.cast(TaacRunner, MagicMock()), []
            )
        self.assertIn("CollectorsTestHandler", [h.__name__ for h in handlers])


if __name__ == "__main__":
    unittest.main()
