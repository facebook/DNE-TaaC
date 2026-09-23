# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-strict

"""IXIA configuration snapshots for TAAC baseline restoration boundaries."""

from __future__ import annotations

import asyncio
import dataclasses
from typing import Protocol

from taac.libs.baseline_lifecycle import BaselineContext


_IXIA_COMMON_STORAGE_DIRECTORY = "/root/.local/share/Ixia/sdmStreamManager/common"
_TOPOLOGY_BASELINE_FILE_PREFIX = "taac_topology_baseline"


class IxiaConfigClient(Protocol):
    def save_config_to_chassis(self, config_path: str) -> bool: ...

    def load_config_from_chassis(self, config_path: str) -> bool: ...

    def remove_config_from_chassis(self, config_path: str) -> bool: ...


@dataclasses.dataclass
class IxiaConfigSnapshot:
    config_path: str
    restore_completed: bool = False


class IxiaTopologyBaselineParticipant:
    name = "ixia_topology"

    def __init__(self, ixia: IxiaConfigClient) -> None:
        self._ixia = ixia

    async def capture(self, context: BaselineContext) -> IxiaConfigSnapshot:
        config_path = self._config_path(context)
        saved = await asyncio.to_thread(
            self._ixia.save_config_to_chassis,
            config_path,
        )
        if not saved:
            raise RuntimeError(f"IXIA topology baseline save failed for {config_path}")
        return IxiaConfigSnapshot(config_path=config_path)

    async def restore(self, context: BaselineContext, snapshot: object) -> None:
        del context
        ixia_snapshot = self._require_snapshot(snapshot)
        restored = await asyncio.to_thread(
            self._ixia.load_config_from_chassis,
            ixia_snapshot.config_path,
        )
        if not restored:
            raise RuntimeError(
                f"IXIA topology baseline load failed for {ixia_snapshot.config_path}"
            )
        ixia_snapshot.restore_completed = True

    async def verify(self, context: BaselineContext, snapshot: object) -> None:
        del context
        ixia_snapshot = self._require_snapshot(snapshot)
        # The IXIA client reports restore success only after loading the native
        # config, reassigning physical ports, and verifying protocol startup.
        # Repeating those expensive operations here would not add new evidence.
        if not ixia_snapshot.restore_completed:
            raise RuntimeError(
                "IXIA configuration load and protocol verification did not complete"
            )

    async def release(self, context: BaselineContext, snapshot: object) -> None:
        ixia_snapshot = self._require_snapshot(snapshot)
        if not ixia_snapshot.config_path:
            return
        expected_config_path = self._config_path(context)
        if ixia_snapshot.config_path != expected_config_path:
            # This participant owns only its invocation-scoped baseline. Cache
            # entries are durable across runs and must never be removed here.
            raise RuntimeError(
                "refusing to remove an IXIA config not owned by this baseline "
                f"invocation: {ixia_snapshot.config_path}"
            )
        removed = await asyncio.to_thread(
            self._ixia.remove_config_from_chassis,
            ixia_snapshot.config_path,
        )
        if not removed:
            raise RuntimeError(
                f"IXIA topology baseline cleanup failed for {ixia_snapshot.config_path}"
            )
        ixia_snapshot.config_path = ""

    @staticmethod
    def _config_path(context: BaselineContext) -> str:
        return (
            f"{_IXIA_COMMON_STORAGE_DIRECTORY}/"
            f"{_TOPOLOGY_BASELINE_FILE_PREFIX}_{context.invocation_id}.ixncfg"
        )

    @staticmethod
    def _require_snapshot(snapshot: object) -> IxiaConfigSnapshot:
        if not isinstance(snapshot, IxiaConfigSnapshot):
            raise TypeError("IXIA baseline participant requires an IxiaConfigSnapshot")
        return snapshot
