# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

from __future__ import annotations

import typing as t

from taac.abstractions.compilation.dut import (
    DutEndpointBaseRenderResult,
    DutHostOsRenderResult,
)
from taac.abstractions.compilation.endpoint_composition import (
    EndpointCompositionRequest,
    EndpointCompositionResult,
)
from taac.abstractions.compilation.model import DutPlan
from taac.abstractions.compilation.traffic_generator import (
    TrafficGeneratorEndpointRenderRequest,
    TrafficGeneratorEndpointRenderResult,
    TrafficGeneratorRenderRequest,
    TrafficGeneratorRenderResult,
)


TDutOutput_co = t.TypeVar("TDutOutput_co", covariant=True)
TEndpoint_co = t.TypeVar("TEndpoint_co", covariant=True)
THostOs_co = t.TypeVar("THostOs_co", covariant=True)


class DutBackend(t.Protocol[TDutOutput_co]):
    def render(self, plan: DutPlan) -> TDutOutput_co: ...


class DutHostOsRenderer(t.Protocol[THostOs_co]):
    def render(self, plan: DutPlan) -> DutHostOsRenderResult[THostOs_co]: ...


class DutEndpointBaseRenderer(t.Protocol[TEndpoint_co]):
    def render(self, plan: DutPlan) -> DutEndpointBaseRenderResult[TEndpoint_co]: ...


class EndpointComposer(t.Protocol):
    def compose(
        self,
        request: EndpointCompositionRequest[object],
    ) -> EndpointCompositionResult[object]: ...


class TrafficGeneratorRenderer(t.Protocol):
    def render(
        self,
        request: TrafficGeneratorRenderRequest,
    ) -> TrafficGeneratorRenderResult: ...


class TrafficGeneratorEndpointRenderer(t.Protocol):
    def render(
        self,
        request: TrafficGeneratorEndpointRenderRequest,
    ) -> TrafficGeneratorEndpointRenderResult: ...
