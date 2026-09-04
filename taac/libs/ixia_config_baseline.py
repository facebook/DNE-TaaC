# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-strict

"""IXIA configuration snapshots for TAAC baseline restoration boundaries."""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import json
from typing import cast, Protocol, TypeAlias

from taac.libs.baseline_lifecycle import BaselineContext


JsonValue: TypeAlias = (
    None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
)

_MAX_STRUCTURAL_DIFFERENCES = 12
_MAX_DIFFERENCE_VALUE_CHARACTERS = 160


class IxiaConfigClient(Protocol):
    def export_json_config(
        self, *, baseline_invocation_id: str | None = None
    ) -> str: ...

    def import_json_config(
        self,
        json_config: str,
        *,
        baseline_invocation_id: str | None = None,
    ) -> None: ...


@dataclasses.dataclass
class IxiaConfigSnapshot:
    json_config: str
    digest: str
    restore_completed: bool = False


class IxiaTopologyBaselineParticipant:
    name = "ixia_topology"

    def __init__(self, ixia: IxiaConfigClient) -> None:
        self._ixia = ixia

    async def capture(self, context: BaselineContext) -> object:
        json_config = await asyncio.to_thread(
            self._ixia.export_json_config,
            baseline_invocation_id=context.invocation_id,
        )
        semantic_projection = self._semantic_projection(json_config)
        return IxiaConfigSnapshot(
            json_config,
            self._digest(semantic_projection),
        )

    async def restore(self, context: BaselineContext, snapshot: object) -> None:
        ixia_snapshot = self._require_snapshot(snapshot)
        await asyncio.to_thread(
            self._ixia.import_json_config,
            ixia_snapshot.json_config,
            baseline_invocation_id=context.invocation_id,
        )
        ixia_snapshot.restore_completed = True

    async def verify(self, context: BaselineContext, snapshot: object) -> None:
        ixia_snapshot = self._require_snapshot(snapshot)
        if not ixia_snapshot.restore_completed:
            raise RuntimeError("IXIA configuration restore did not complete")
        restored_config = await asyncio.to_thread(
            self._ixia.export_json_config,
            baseline_invocation_id=context.invocation_id,
        )
        expected_projection = self._semantic_projection(ixia_snapshot.json_config)
        restored_projection = self._semantic_projection(restored_config)
        differences, truncated = self._bounded_structural_diff(
            expected_projection,
            restored_projection,
        )
        if differences:
            restored_digest = self._digest(restored_projection)
            difference_summary = "; ".join(differences)
            if truncated:
                difference_summary += (
                    "; additional differences omitted "
                    f"(limit={_MAX_STRUCTURAL_DIFFERENCES})"
                )
            raise RuntimeError(
                "IXIA stable semantic configuration does not match the captured "
                "topology "
                f"baseline: expected={ixia_snapshot.digest}; "
                f"observed={restored_digest}; differences: {difference_summary}"
            )

    async def release(self, context: BaselineContext, snapshot: object) -> None:
        del context
        ixia_snapshot = self._require_snapshot(snapshot)
        ixia_snapshot.json_config = ""

    @staticmethod
    def _semantic_projection(json_config: str) -> JsonValue:
        parsed_config = cast(JsonValue, json.loads(json_config))
        return IxiaTopologyBaselineParticipant._normalize_semantic_value(parsed_config)

    @staticmethod
    def _normalize_semantic_value(value: JsonValue) -> JsonValue:
        if isinstance(value, dict):
            return {
                key: IxiaTopologyBaselineParticipant._normalize_semantic_value(child)
                for key, child in sorted(value.items())
            }
        if not isinstance(value, list):
            return value

        normalized = [
            IxiaTopologyBaselineParticipant._normalize_semantic_value(child)
            for child in value
        ]
        xpaths = [
            child.get("xpath") if isinstance(child, dict) else None
            for child in normalized
        ]
        # XPath uniquely identifies IXIA resource nodes, so traversal order does
        # not carry configuration semantics across export/import round trips.
        if (
            xpaths
            and all(isinstance(xpath, str) for xpath in xpaths)
            and len(set(xpaths)) == len(xpaths)
        ):
            return sorted(
                normalized,
                key=lambda child: cast(
                    str,
                    cast(dict[str, JsonValue], child)["xpath"],
                ),
            )
        return normalized

    @staticmethod
    def _digest(semantic_projection: JsonValue) -> str:
        normalized = json.dumps(
            semantic_projection,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(normalized.encode()).hexdigest()

    @staticmethod
    def _bounded_structural_diff(
        expected: JsonValue,
        observed: JsonValue,
    ) -> tuple[list[str], bool]:
        differences: list[str] = []
        truncated = IxiaTopologyBaselineParticipant._collect_structural_differences(
            expected,
            observed,
            path="",
            differences=differences,
        )
        return differences, truncated

    @staticmethod
    def _collect_structural_differences(
        expected: JsonValue,
        observed: JsonValue,
        *,
        path: str,
        differences: list[str],
    ) -> bool:
        expected_is_number = isinstance(expected, (int, float)) and not isinstance(
            expected, bool
        )
        observed_is_number = isinstance(observed, (int, float)) and not isinstance(
            observed, bool
        )
        if expected_is_number and observed_is_number and expected == observed:
            return False
        if type(expected) is not type(observed):
            return IxiaTopologyBaselineParticipant._append_difference(
                path=path,
                expected=expected,
                observed=observed,
                differences=differences,
            )
        if isinstance(expected, dict) and isinstance(observed, dict):
            return IxiaTopologyBaselineParticipant._collect_mapping_differences(
                expected,
                observed,
                path=path,
                differences=differences,
            )
        if isinstance(expected, list) and isinstance(observed, list):
            return IxiaTopologyBaselineParticipant._collect_list_differences(
                expected,
                observed,
                path=path,
                differences=differences,
            )
        if expected != observed:
            return IxiaTopologyBaselineParticipant._append_difference(
                path=path,
                expected=expected,
                observed=observed,
                differences=differences,
            )
        return False

    @staticmethod
    def _collect_mapping_differences(
        expected: dict[str, JsonValue],
        observed: dict[str, JsonValue],
        *,
        path: str,
        differences: list[str],
    ) -> bool:
        for key in sorted(expected.keys() | observed.keys()):
            child_path = IxiaTopologyBaselineParticipant._child_path(path, key)
            if key not in expected:
                truncated = IxiaTopologyBaselineParticipant._append_difference(
                    path=child_path,
                    expected="<missing>",
                    observed=observed[key],
                    differences=differences,
                )
            elif key not in observed:
                truncated = IxiaTopologyBaselineParticipant._append_difference(
                    path=child_path,
                    expected=expected[key],
                    observed="<missing>",
                    differences=differences,
                )
            else:
                truncated = (
                    IxiaTopologyBaselineParticipant._collect_structural_differences(
                        expected[key],
                        observed[key],
                        path=child_path,
                        differences=differences,
                    )
                )
            if truncated:
                return True
        return False

    @staticmethod
    def _collect_list_differences(
        expected: list[JsonValue],
        observed: list[JsonValue],
        *,
        path: str,
        differences: list[str],
    ) -> bool:
        for index in range(max(len(expected), len(observed))):
            child_path = IxiaTopologyBaselineParticipant._child_path(path, str(index))
            if index >= len(expected):
                truncated = IxiaTopologyBaselineParticipant._append_difference(
                    path=child_path,
                    expected="<missing>",
                    observed=observed[index],
                    differences=differences,
                )
            elif index >= len(observed):
                truncated = IxiaTopologyBaselineParticipant._append_difference(
                    path=child_path,
                    expected=expected[index],
                    observed="<missing>",
                    differences=differences,
                )
            else:
                truncated = (
                    IxiaTopologyBaselineParticipant._collect_structural_differences(
                        expected[index],
                        observed[index],
                        path=child_path,
                        differences=differences,
                    )
                )
            if truncated:
                return True
        return False

    @staticmethod
    def _append_difference(
        *,
        path: str,
        expected: JsonValue,
        observed: JsonValue,
        differences: list[str],
    ) -> bool:
        if len(differences) >= _MAX_STRUCTURAL_DIFFERENCES:
            return True
        differences.append(
            f"{path or '/'}: "
            f"expected={IxiaTopologyBaselineParticipant._summarize_value(expected)} "
            f"observed={IxiaTopologyBaselineParticipant._summarize_value(observed)}"
        )
        return False

    @staticmethod
    def _summarize_value(value: JsonValue) -> str:
        rendered = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
        )
        if len(rendered) <= _MAX_DIFFERENCE_VALUE_CHARACTERS:
            return rendered
        return f"{rendered[:_MAX_DIFFERENCE_VALUE_CHARACTERS]}..."

    @staticmethod
    def _child_path(path: str, child: str) -> str:
        escaped_child = child.replace("~", "~0").replace("/", "~1")
        return f"{path}/{escaped_child}"

    @staticmethod
    def _require_snapshot(snapshot: object) -> IxiaConfigSnapshot:
        if not isinstance(snapshot, IxiaConfigSnapshot):
            raise TypeError("IXIA baseline participant requires an IxiaConfigSnapshot")
        return snapshot
