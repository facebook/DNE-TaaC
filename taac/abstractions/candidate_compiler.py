# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from taac.abstractions.artifacts import CompiledTaacArtifacts
from taac.abstractions.compilation.model import (
    TopologyCompilationPlan,
)
from taac.abstractions.compilation.planner import PlanningResult
from taac.abstractions.compilation.report import (
    CompileReport,
    RendererDisposition,
    RendererLane,
    RendererReport,
)
from taac.abstractions.topology.model import BoundTopology


_REQUIRED_RENDERER_LANES = (
    RendererLane.DUT,
    RendererLane.TRAFFIC_GENERATOR,
    RendererLane.ARTIFACT_ADAPTER,
)


class CandidatePlanner(Protocol):
    def plan(self, bound: BoundTopology) -> PlanningResult: ...


@dataclass(frozen=True)
class AdaptedArtifacts:
    artifacts: CompiledTaacArtifacts
    renderer_reports: tuple[RendererReport, ...]


class ArtifactAdapter(Protocol):
    def render(
        self,
        bound: BoundTopology,
        plan: TopologyCompilationPlan,
    ) -> AdaptedArtifacts: ...


@dataclass(frozen=True)
class EstablishedEosArtifactAdapter:
    compile_bound: Callable[[BoundTopology], CompiledTaacArtifacts]

    def render(
        self,
        bound: BoundTopology,
        plan: TopologyCompilationPlan,
    ) -> AdaptedArtifacts:
        del plan
        return AdaptedArtifacts(
            artifacts=self.compile_bound(bound),
            renderer_reports=(
                RendererReport(
                    lane=RendererLane.DUT,
                    disposition=RendererDisposition.COMPATIBILITY_DELEGATED,
                    reason="EOS/BGP++ task rendering remains on the established compiler",
                ),
                RendererReport(
                    lane=RendererLane.TRAFFIC_GENERATOR,
                    disposition=RendererDisposition.COMPATIBILITY_DELEGATED,
                    reason="IXIA rendering remains on the established compiler",
                ),
                RendererReport(
                    lane=RendererLane.ARTIFACT_ADAPTER,
                    disposition=RendererDisposition.COMPATIBILITY_DELEGATED,
                    reason="flat TAAC artifact assembly remains on the established compiler",
                ),
            ),
        )


@dataclass(frozen=True)
class CandidateCompilation:
    plan: TopologyCompilationPlan
    report: CompileReport
    artifacts: CompiledTaacArtifacts


@dataclass(frozen=True)
class CandidateTopologyCompiler:
    planner: CandidatePlanner
    artifact_adapter: ArtifactAdapter

    def analyze(self, bound: BoundTopology) -> PlanningResult:
        return self.planner.plan(bound)

    def compile_with_report(self, bound: BoundTopology) -> CandidateCompilation:
        planning = self.analyze(bound)
        resource_ids = planning.plan.iter_resource_ids()
        planning.report.assert_renderable(resource_ids)
        adapted = self.artifact_adapter.render(bound, planning.plan)
        report = planning.report.with_renderer_reports(*adapted.renderer_reports)
        report.assert_renderable(
            resource_ids,
            _REQUIRED_RENDERER_LANES,
        )
        return CandidateCompilation(
            plan=planning.plan,
            report=report,
            artifacts=adapted.artifacts,
        )

    def compile(self, bound: BoundTopology) -> CompiledTaacArtifacts:
        return self.compile_with_report(bound).artifacts
