# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-strict

"""IXIA transaction, apply, deadline, and restoration runtime mechanisms."""

from __future__ import annotations

import asyncio
import contextlib
import typing as t

from taac.constants import TestCaseFailure
from taac.ixia.churn.attribute_operations import (
    restoration_vectors,
    restore_vector_batch,
)
from taac.ixia.churn.attribute_state import (
    AttributeVector,
    IxiaAttributePoolState,
)


def mutation_scope(ixia: t.Any) -> t.ContextManager[object]:
    transaction = getattr(type(ixia), "mutation_transaction", None)
    return contextlib.nullcontext() if transaction is None else transaction(ixia)


def require_session(ixia: t.Any) -> None:
    checker = getattr(type(ixia), "assert_session_not_quarantined", None)
    if checker is not None:
        checker(ixia)


def request_deadline(
    ixia: t.Any, timeout_seconds: float, phase: str
) -> t.ContextManager[object]:
    deadline = getattr(type(ixia), "request_deadline", None)
    if deadline is None:
        return contextlib.nullcontext()
    return deadline(ixia, timeout_seconds, phase)


def apply_changes(
    ixia: t.Any,
    apply_timeout_seconds: float,
    abort_timeout_seconds: float,
) -> None:
    bounded_apply = getattr(type(ixia), "apply_changes_bounded", None)
    if bounded_apply is None:
        raise TestCaseFailure(
            "IXIA apply_changes_bounded support is required for EBB-10"
        )
    bounded_apply(
        ixia,
        apply_timeout_seconds,
        abort_timeout_seconds=abort_timeout_seconds,
    )


async def restore_vectors_and_apply(
    pools: t.Sequence[IxiaAttributePoolState],
    apply_restoration: t.Callable[[], t.Awaitable[None]],
    *,
    attempts: int,
    retry_base_seconds: float,
    on_vector_failure: t.Callable[[int, int, AttributeVector, Exception], None],
) -> None:
    pending = restoration_vectors(pools)
    for attempt in range(1, attempts + 1):
        failures = restore_vector_batch(pending)
        await apply_restoration()
        if not failures:
            return
        for vector, error in failures:
            on_vector_failure(attempt, attempts, vector, error)
        if attempt == attempts:
            details = "; ".join(
                f"{vector.label}: {type(error).__name__}: {error}"
                for vector, error in failures
            )
            raise TestCaseFailure(
                f"IXIA vector restoration failed after {attempts} attempts: {details}"
            ) from failures[0][1]
        pending = tuple(vector for vector, _error in failures)
        await asyncio.sleep(retry_base_seconds * (2 ** (attempt - 1)))


async def apply_restoration_with_retry(
    apply: t.Callable[[], None],
    *,
    attempts: int,
    retry_base_seconds: float,
    on_retryable_failure: t.Callable[[int, int, Exception], None],
    on_programming_error: t.Callable[[], None],
) -> None:
    for attempt in range(1, attempts + 1):
        try:
            apply()
            return
        except asyncio.TimeoutError:
            raise
        except (
            AssertionError,
            AttributeError,
            IndexError,
            KeyError,
            TypeError,
            ValueError,
        ):
            on_programming_error()
            raise
        except Exception as error:
            on_retryable_failure(attempt, attempts, error)
            if attempt == attempts:
                raise TestCaseFailure(
                    f"IXIA restoration failed after {attempts} attempts: "
                    f"{type(error).__name__}: {error}"
                ) from error
            await asyncio.sleep(retry_base_seconds * (2 ** (attempt - 1)))
