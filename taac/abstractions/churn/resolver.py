# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-strict

"""Target-resolution contract implemented by concrete TAAC adapters."""

from __future__ import annotations

import typing as t

from .context import Deadline
from .selectors import TargetIdentity, TargetSelection


class TargetResolver(t.Protocol):
    async def resolve(
        self, selection: TargetSelection, deadline: Deadline
    ) -> tuple[TargetIdentity, ...]: ...
