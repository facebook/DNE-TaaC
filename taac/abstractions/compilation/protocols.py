# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

from __future__ import annotations

import typing as t

from neteng.test_infra.dne.taac.abstractions.compilation.model import DutPlan, IxiaPlan


TDutOutput_co = t.TypeVar("TDutOutput_co", covariant=True)
TTrafficOutput_co = t.TypeVar("TTrafficOutput_co", covariant=True)


class DutBackend(t.Protocol[TDutOutput_co]):
    def render(self, plan: DutPlan) -> TDutOutput_co: ...


class TrafficGeneratorRenderer(t.Protocol[TTrafficOutput_co]):
    def render(self, plan: IxiaPlan) -> TTrafficOutput_co: ...
