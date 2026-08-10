# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

from __future__ import annotations

import typing as t

from taac.abstractions.compilation.model import DutPlan
from taac.abstractions.compilation.traffic_generator import (
    TrafficGeneratorRenderRequest,
    TrafficGeneratorRenderResult,
)


TDutOutput_co = t.TypeVar("TDutOutput_co", covariant=True)


class DutBackend(t.Protocol[TDutOutput_co]):
    def render(self, plan: DutPlan) -> TDutOutput_co: ...


class TrafficGeneratorRenderer(t.Protocol):
    def render(
        self,
        request: TrafficGeneratorRenderRequest,
    ) -> TrafficGeneratorRenderResult: ...
