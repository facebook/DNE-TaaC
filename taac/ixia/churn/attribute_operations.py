# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-strict

"""Reusable IXIA attribute mutation, readback, and restoration operations."""

from __future__ import annotations

import typing as t

from taac.constants import TestCaseFailure
from taac.ixia.churn.attribute_state import (
    AttributeVector,
    IxiaAttributePoolState,
)
from taac.ixia.route_geometry import IxiaOverlayVector


def normalize_origin(value: t.Any) -> str:
    key = str(value).lower()
    if key not in {"igp", "egp", "incomplete"}:
        raise TestCaseFailure(f"invalid ORIGIN value {value!r}")
    return key


def normalize_boolean(value: t.Any) -> bool:
    if isinstance(value, bool):
        return value
    normalized = str(value).lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise TestCaseFailure(f"invalid IXIA boolean value {value!r}")


def _attribute_vector(pool: IxiaAttributePoolState, family: str) -> AttributeVector:
    try:
        return {
            "local_pref": pool.local_pref,
            "med": pool.med,
            "origin": pool.origin,
        }[family]
    except KeyError as error:
        raise TestCaseFailure(f"unsupported BGP attribute family {family!r}") from error


def assert_overlay_readback(vector: AttributeVector, *, refresh_base: bool) -> None:
    if isinstance(vector, IxiaOverlayVector):
        vector.assert_exact_readback(refresh_base=refresh_base)


def validate_write_rows(vector: AttributeVector, rows: t.Iterable[int]) -> None:
    selected_rows = tuple(rows)
    if isinstance(vector, IxiaOverlayVector):
        vector.validate_rows(selected_rows)
    else:
        vector.current_values()
    if any(row < 0 or row >= vector.expanded_row_count for row in selected_rows):
        raise TestCaseFailure("selected row is outside IXIA vector geometry")


def write_rows(vector: AttributeVector, rows: t.Iterable[int], value: t.Any) -> None:
    selected_rows = tuple(rows)
    validate_write_rows(vector, selected_rows)
    vector.write_rows(selected_rows, value)


def validate_scalar_write(
    pool: IxiaAttributePoolState, family: str, value: t.Any
) -> t.Any:
    vector = _attribute_vector(pool, family)
    normalized = normalize_origin(value) if family == "origin" else int(value)
    validate_write_rows(vector, pool.rows)
    if family == "med":
        validate_write_rows(pool.med_enabled, pool.rows)
    return normalized


def write_scalar(pool: IxiaAttributePoolState, family: str, value: t.Any) -> None:
    normalized = validate_scalar_write(pool, family, value)
    write_rows(_attribute_vector(pool, family), pool.rows, normalized)
    if family == "med":
        write_rows(pool.med_enabled, pool.rows, "true")


def peer_for_row(pool: IxiaAttributePoolState, row: int) -> str:
    for start, end, peer in pool.peer_ranges:
        if start <= row <= end:
            return peer
    return "<unselected>"


def readback_mismatches(
    pool: IxiaAttributePoolState,
    vector: AttributeVector,
    expected_by_row: t.Callable[[int], t.Any],
    *,
    boolean: bool = False,
) -> list[t.Mapping[str, t.Any]]:
    mismatches: list[t.Mapping[str, t.Any]] = []
    if isinstance(vector, IxiaOverlayVector):
        vector.assert_exact_readback(refresh_base=True)
        rows = vector.audit_rows()
    else:
        rows = tuple(range(vector.expanded_row_count))
    for offset, row in enumerate(rows):
        raw_observed = vector.current_value(row)
        observed = normalize_boolean(raw_observed) if boolean else raw_observed
        raw_expected = expected_by_row(row)
        expected = normalize_boolean(raw_expected) if boolean else raw_expected
        matches = (
            observed == expected
            if boolean
            else str(observed).lower() == str(expected).lower()
        )
        if not matches:
            mismatches.append(
                {
                    "row": row,
                    "peer": peer_for_row(pool, row),
                    "expected": expected,
                    "observed": observed,
                }
            )
        if len(mismatches) == 10:
            if offset + 1 < len(rows):
                mismatches.append(
                    {
                        "row": None,
                        "peer": None,
                        "expected": None,
                        "observed": None,
                        "truncated": True,
                        "reported": 10,
                        "unexamined_rows": len(rows) - offset - 1,
                    }
                )
            break
    return mismatches


def verify_readback(pool: IxiaAttributePoolState, family: str, value: t.Any) -> None:
    vector = _attribute_vector(pool, family)
    expected = normalize_origin(value) if family == "origin" else int(value)
    selected_rows = set(pool.rows)
    mismatches = readback_mismatches(
        pool,
        vector,
        lambda row: expected if row in selected_rows else vector.baseline_value(row),
    )
    if mismatches:
        raise TestCaseFailure(
            f"{pool.name}: afi={pool.afi} plane={pool.plane} {family} "
            f"readback mismatch; mismatches={mismatches}"
        )
    if family != "med":
        return
    enable_mismatches = readback_mismatches(
        pool,
        pool.med_enabled,
        lambda row: (
            True
            if row in selected_rows
            else normalize_boolean(pool.med_enabled.baseline_value(row))
        ),
        boolean=True,
    )
    if enable_mismatches:
        raise TestCaseFailure(
            f"{pool.name}: afi={pool.afi} plane={pool.plane} MED enable "
            f"readback mismatch; mismatches={enable_mismatches}"
        )


def attribute_values_match(
    pools: t.Sequence[IxiaAttributePoolState],
    family: str,
    value: t.Any,
    planes: t.AbstractSet[int],
) -> bool:
    expected = normalize_origin(value) if family == "origin" else int(value)
    for pool in pools:
        if pool.plane not in planes:
            continue
        vector = _attribute_vector(pool, family)
        assert_overlay_readback(vector, refresh_base=True)
        if any(
            str(vector.current_value(row)).lower() != str(expected).lower()
            for row in pool.rows
        ):
            return False
        if family == "med":
            assert_overlay_readback(pool.med_enabled, refresh_base=True)
            if any(
                not normalize_boolean(pool.med_enabled.current_value(row))
                for row in pool.rows
            ):
                return False
    return True


def restoration_vectors(
    pools: t.Sequence[IxiaAttributePoolState],
) -> tuple[AttributeVector, ...]:
    return tuple(
        vector
        for pool in pools
        for vector in (pool.local_pref, pool.med_enabled, pool.med, pool.origin)
    )


def restore_vector_batch(
    vectors: t.Sequence[AttributeVector],
) -> tuple[tuple[AttributeVector, Exception], ...]:
    failures: list[tuple[AttributeVector, Exception]] = []
    for vector in vectors:
        try:
            vector.restore()
        except Exception as error:
            failures.append((vector, error))
    return tuple(failures)


def restore_vectors(
    pools: t.Sequence[IxiaAttributePoolState],
) -> tuple[tuple[AttributeVector, Exception], ...]:
    return restore_vector_batch(restoration_vectors(pools))


def pool_vectors_are_exactly_restored(pool: IxiaAttributePoolState) -> bool:
    return all(
        vector.is_exactly_restored()
        for vector in (pool.local_pref, pool.med_enabled, pool.med, pool.origin)
    )
