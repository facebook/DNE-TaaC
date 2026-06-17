# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import unittest
from unittest import mock

from taac.health_checks import common_utils


class AsyncGetEverpasteFburlIfNeededTest(unittest.IsolatedAsyncioTestCase):
    """``async_get_everpaste_fburl_if_needed`` must default to everpaste-only
    (no globally throttled ``fburl`` call) and only mint an fburl when
    ``shorten_fburl=True`` (failure-class results)."""

    async def test_returns_none_for_empty(self) -> None:
        ep = mock.AsyncMock()
        fb = mock.AsyncMock()
        with mock.patch.object(common_utils, "async_everpaste_str", new=ep):
            with mock.patch.object(common_utils, "async_get_fburl", new=fb):
                self.assertIsNone(
                    await common_utils.async_get_everpaste_fburl_if_needed(None)
                )
                self.assertIsNone(
                    await common_utils.async_get_everpaste_fburl_if_needed("")
                )
                ep.assert_not_awaited()
                fb.assert_not_awaited()

    async def test_short_message_returned_unchanged_without_network(self) -> None:
        ep = mock.AsyncMock()
        fb = mock.AsyncMock()
        with mock.patch.object(common_utils, "async_everpaste_str", new=ep):
            with mock.patch.object(common_utils, "async_get_fburl", new=fb):
                msg = "short message"
                self.assertEqual(
                    await common_utils.async_get_everpaste_fburl_if_needed(
                        msg, min_chars=1000
                    ),
                    msg,
                )
                ep.assert_not_awaited()
                fb.assert_not_awaited()

    async def test_long_message_default_is_everpaste_only_no_fburl(self) -> None:
        ep = mock.AsyncMock(return_value="https://everpaste/url")
        fb = mock.AsyncMock(return_value="https://fburl.com/x")
        with mock.patch.object(common_utils, "async_everpaste_str", new=ep):
            with mock.patch.object(common_utils, "async_get_fburl", new=fb):
                result = await common_utils.async_get_everpaste_fburl_if_needed(
                    "x" * 2000, min_chars=1000
                )
                self.assertEqual(result, "https://everpaste/url")
                ep.assert_awaited_once()
                fb.assert_not_awaited()

    async def test_long_message_with_shorten_fburl_calls_fburl(self) -> None:
        ep = mock.AsyncMock(return_value="https://everpaste/url")
        fb = mock.AsyncMock(return_value="https://fburl.com/x")
        with mock.patch.object(common_utils, "async_everpaste_str", new=ep):
            with mock.patch.object(common_utils, "async_get_fburl", new=fb):
                result = await common_utils.async_get_everpaste_fburl_if_needed(
                    "x" * 2000, min_chars=1000, shorten_fburl=True
                )
                self.assertEqual(result, "https://fburl.com/x")
                ep.assert_awaited_once()
                fb.assert_awaited_once_with("https://everpaste/url")

    async def test_message_truncated_before_upload(self) -> None:
        ep = mock.AsyncMock(return_value="https://everpaste/url")
        fb = mock.AsyncMock(return_value="https://fburl.com/x")
        with mock.patch.object(common_utils, "async_everpaste_str", new=ep):
            with mock.patch.object(common_utils, "async_get_fburl", new=fb):
                await common_utils.async_get_everpaste_fburl_if_needed(
                    "y" * 50_000, min_chars=1000, max_chars=10_000
                )
                await_args = ep.await_args
                assert await_args is not None  # narrow Optional for the type checker
                uploaded = await_args.args[0]
                self.assertTrue(uploaded.endswith(" ...[truncated]"))
                self.assertLessEqual(len(uploaded), 10_000 + len(" ...[truncated]"))
