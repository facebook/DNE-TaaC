# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from taac.abstractions.artifacts import CompiledTaacArtifacts
from taac.abstractions.compatibility.eos_bgpcpp_policy_bindings import (
    resolve_eos_bgpcpp_policy_binding,
)
from taac.abstractions.compilation.dut import (
    DutEndpointBaseRenderResult,
    DutHostOsRenderResult,
)
from taac.abstractions.compilation.model import (
    TopologyCompilationPlan,
)
from taac.abstractions.compilation.planner import PlanningResult
from taac.abstractions.compilation.protocols import (
    DutEndpointBaseRenderer,
    DutHostOsRenderer,
    TrafficGeneratorEndpointRenderer,
    TrafficGeneratorRenderer,
)
from taac.abstractions.compilation.report import (
    CompileReport,
    RendererDisposition,
    RendererLane,
    RendererReport,
)
from taac.abstractions.compilation.traffic_generator import (
    TrafficGeneratorEndpointRenderRequest,
    TrafficGeneratorEndpointRenderResult,
    TrafficGeneratorRenderRequest,
    TrafficGeneratorRenderResult,
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
        for policy in plan.dut.policies:
            if policy.preset is not None:
                resolve_eos_bgpcpp_policy_binding(policy.preset.key)
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
    dut_endpoint_base_shadow: DutEndpointBaseRenderResult[object] | None = None
    dut_host_os_shadow: DutHostOsRenderResult[object] | None = None
    traffic_generator_endpoint_shadow: TrafficGeneratorEndpointRenderResult | None = (
        None
    )
    traffic_generator_shadow: TrafficGeneratorRenderResult | None = None


@dataclass(frozen=True)
class CandidateTopologyCompiler:
    planner: CandidatePlanner
    artifact_adapter: ArtifactAdapter
    dut_endpoint_base_renderer: DutEndpointBaseRenderer[object] | None = None
    dut_host_os_renderer: DutHostOsRenderer[object] | None = None
    traffic_generator_endpoint_renderer: TrafficGeneratorEndpointRenderer | None = None
    traffic_generator_renderer: TrafficGeneratorRenderer | None = None

    def analyze(self, bound: BoundTopology) -> PlanningResult:
        return self.planner.plan(bound)

    def compile_with_report(self, bound: BoundTopology) -> CandidateCompilation:
        planning = self.analyze(bound)
        resource_ids = planning.plan.iter_resource_ids()
        planning.report.assert_renderable(resource_ids)
        adapted = self.artifact_adapter.render(bound, planning.plan)
        dut_endpoint_base_shadow = None
        if self.dut_endpoint_base_renderer is not None:
            dut_endpoint_base_shadow = self.dut_endpoint_base_renderer.render(
                planning.plan.dut
            )
            dut_endpoint_base_shadow.validate(planning.plan.dut)
        dut_host_os_shadow = None
        if self.dut_host_os_renderer is not None:
            dut_host_os_shadow = self.dut_host_os_renderer.render(planning.plan.dut)
            dut_host_os_shadow.validate(planning.plan.dut)
        traffic_generator_request = None
        if (
            self.traffic_generator_endpoint_renderer is not None
            or self.traffic_generator_renderer is not None
        ):
            traffic_generator_request = (
                TrafficGeneratorRenderRequest.from_compilation_plan(
                    planning.plan,
                    planning.legacy_ixia_identity,
                )
            )
        traffic_generator_endpoint_shadow = None
        if self.traffic_generator_endpoint_renderer is not None:
            assert traffic_generator_request is not None
            traffic_generator_endpoint_request = (
                TrafficGeneratorEndpointRenderRequest.from_render_request(
                    traffic_generator_request
                )
            )
            traffic_generator_endpoint_shadow = (
                self.traffic_generator_endpoint_renderer.render(
                    traffic_generator_endpoint_request
                )
            )
            traffic_generator_endpoint_shadow.validate(
                traffic_generator_endpoint_request
            )
        traffic_generator_shadow = None
        if self.traffic_generator_renderer is not None:
            assert traffic_generator_request is not None
            traffic_generator_shadow = self.traffic_generator_renderer.render(
                traffic_generator_request
            )
            traffic_generator_shadow.validate(traffic_generator_request)
        report = planning.report.with_renderer_reports(*adapted.renderer_reports)
        report.assert_renderable(
            resource_ids,
            _REQUIRED_RENDERER_LANES,
        )
        return CandidateCompilation(
            plan=planning.plan,
            report=report,
            artifacts=adapted.artifacts,
            dut_endpoint_base_shadow=dut_endpoint_base_shadow,
            dut_host_os_shadow=dut_host_os_shadow,
            traffic_generator_endpoint_shadow=traffic_generator_endpoint_shadow,
            traffic_generator_shadow=traffic_generator_shadow,
        )

    def compile(self, bound: BoundTopology) -> CompiledTaacArtifacts:
        return self.compile_with_report(bound).artifacts
