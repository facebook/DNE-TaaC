# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-strict

"""Behavioral contracts for IXIA-owned churn runtime operations."""

from __future__ import annotations

import contextlib
import typing as t
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from taac.constants import TestCaseFailure
from taac.ixia.churn.attribute_runtime import (
    apply_changes,
    apply_restoration_with_retry,
    mutation_scope,
    request_deadline,
    restore_vectors_and_apply,
)
from taac.ixia.churn.attribute_state import IxiaAttributePoolState


class AttributeRuntimeTest(unittest.IsolatedAsyncioTestCase):
    def test_transaction_and_deadline_delegate_to_ixia(self) -> None:
        transaction = contextlib.nullcontext("transaction")
        deadline = contextlib.nullcontext("deadline")

        class Ixia:
            mutation_transaction = MagicMock(return_value=transaction)
            request_deadline = MagicMock(return_value=deadline)

        ixia = Ixia()

        self.assertIs(transaction, mutation_scope(ixia))
        self.assertIs(deadline, request_deadline(ixia, 12.0, "restore"))
        Ixia.request_deadline.assert_called_once_with(ixia, 12.0, "restore")

    def test_apply_changes_requires_bounded_ixia_api(self) -> None:
        class BoundedIxia:
            def __init__(self) -> None:
                self.calls: list[tuple[float, float]] = []

            def apply_changes_bounded(
                self, timeout_seconds: float, *, abort_timeout_seconds: float
            ) -> None:
                self.calls.append((timeout_seconds, abort_timeout_seconds))

        ixia = BoundedIxia()
        apply_changes(ixia, 60.0, 10.0)
        self.assertEqual([(60.0, 10.0)], ixia.calls)

        with self.assertRaisesRegex(TestCaseFailure, "apply_changes_bounded"):
            apply_changes(SimpleNamespace(), 60.0, 10.0)

    async def test_vector_restore_retries_only_failed_vectors(self) -> None:
        failed = MagicMock(label="failed")
        failed.restore.side_effect = [RuntimeError("busy"), None]
        successful = MagicMock(label="successful")
        pool = t.cast(
            IxiaAttributePoolState,
            SimpleNamespace(
                local_pref=failed,
                med_enabled=successful,
                med=MagicMock(label="med"),
                origin=MagicMock(label="origin"),
            ),
        )
        apply = AsyncMock()

        with patch(
            "neteng.test_infra.dne.taac.ixia.churn.attribute_runtime.asyncio.sleep",
            new_callable=AsyncMock,
        ) as sleep:
            await restore_vectors_and_apply(
                (pool,),
                apply,
                attempts=3,
                retry_base_seconds=1.0,
                on_vector_failure=MagicMock(),
            )

        self.assertEqual(2, failed.restore.call_count)
        successful.restore.assert_called_once_with()
        self.assertEqual(2, apply.await_count)
        sleep.assert_awaited_once_with(1.0)

    async def test_restoration_apply_retries_runtime_failure(self) -> None:
        apply = MagicMock(side_effect=[RuntimeError("busy"), None])
        on_retry = MagicMock()

        with patch(
            "neteng.test_infra.dne.taac.ixia.churn.attribute_runtime.asyncio.sleep",
            new_callable=AsyncMock,
        ) as sleep:
            await apply_restoration_with_retry(
                apply,
                attempts=3,
                retry_base_seconds=1.0,
                on_retryable_failure=on_retry,
                on_programming_error=MagicMock(),
            )

        self.assertEqual(2, apply.call_count)
        on_retry.assert_called_once()
        sleep.assert_awaited_once_with(1.0)

    async def test_restoration_apply_does_not_retry_programming_error(self) -> None:
        apply = MagicMock(side_effect=ValueError("invalid"))
        on_programming_error = MagicMock()

        with self.assertRaisesRegex(ValueError, "invalid"):
            await apply_restoration_with_retry(
                apply,
                attempts=3,
                retry_base_seconds=1.0,
                on_retryable_failure=MagicMock(),
                on_programming_error=on_programming_error,
            )

        apply.assert_called_once_with()
        on_programming_error.assert_called_once_with()
