# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from taac.abstractions.artifacts import CompiledTaacArtifacts
from taac.abstractions.compilation.basic_port_composition import (
    BasicPortCompositionRequest,
    BasicPortCompositionResult,
)
from taac.abstractions.compilation.dut import (
    DutEndpointBaseRenderResult,
    DutHostOsRenderResult,
    DutLifecycleRenderResult,
)
from taac.abstractions.compilation.endpoint_composition import (
    EndpointCompositionRequest,
    EndpointCompositionResult,
)
from taac.abstractions.compilation.lifecycle import LifecyclePlan
from taac.abstractions.compilation.lifecycle_materialization import (
    validate_lifecycle_task_materialization,
)
from taac.abstractions.compilation.model import (
    DutPlan,
    TopologyCompilationPlan,
)
from taac.abstractions.compilation.planner import PlanningResult
from taac.abstractions.compilation.protocols import (
    BasicPortComposer,
    DutCapabilityPreflight,
    DutEndpointBaseRenderer,
    DutHostOsRenderer,
    DutLifecycleRenderer,
    DutLifecycleTaskMaterializer,
    EndpointComposer,
    TrafficGeneratorEndpointRenderer,
    TrafficGeneratorPortBaseRenderer,
    TrafficGeneratorPortDeviceGroupRenderer,
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
    TrafficGeneratorPortBaseRenderRequest,
    TrafficGeneratorPortBaseRenderResult,
    TrafficGeneratorPortDeviceGroupRenderRequest,
    TrafficGeneratorPortDeviceGroupRenderResult,
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
    dut_endpoint_base_shadow: DutEndpointBaseRenderResult[object] | None = None
    dut_host_os_shadow: DutHostOsRenderResult[object] | None = None
    dut_lifecycle_shadow: DutLifecycleRenderResult[object] | None = None
    dut_lifecycle_task_shadow: DutLifecycleRenderResult[object] | None = None
    traffic_generator_endpoint_shadow: TrafficGeneratorEndpointRenderResult | None = (
        None
    )
    traffic_generator_port_base_shadow: (
        TrafficGeneratorPortBaseRenderResult[object] | None
    ) = None
    traffic_generator_port_device_group_shadow: (
        TrafficGeneratorPortDeviceGroupRenderResult[object] | None
    ) = None
    basic_port_composition_shadow: BasicPortCompositionResult[object] | None = None
    endpoint_composition_shadow: EndpointCompositionResult[object] | None = None
    traffic_generator_shadow: TrafficGeneratorRenderResult | None = None
    lifecycle: LifecyclePlan = field(default_factory=LifecyclePlan)


def _traffic_generator_request(
    planning: PlanningResult,
    *renderers: object | None,
) -> TrafficGeneratorRenderRequest | None:
    if all(renderer is None for renderer in renderers):
        return None
    return TrafficGeneratorRenderRequest.from_compilation_plan(
        planning.plan,
        planning.legacy_ixia_identity,
    )


def _require_traffic_generator_request(
    request: TrafficGeneratorRenderRequest | None,
) -> TrafficGeneratorRenderRequest:
    if request is None:
        raise RuntimeError("traffic-generator request was not constructed")
    return request


def _materialize_dut_lifecycle(
    materializer: DutLifecycleTaskMaterializer | None,
    plan: DutPlan,
    lifecycle: LifecyclePlan,
    intents: DutLifecycleRenderResult[object] | None,
) -> DutLifecycleRenderResult[object] | None:
    if materializer is None:
        return None
    if intents is None:
        raise RuntimeError("DUT lifecycle intent was not rendered")
    tasks = materializer.materialize(plan, lifecycle, intents)
    validate_lifecycle_task_materialization(
        plan,
        lifecycle,
        intents,
        tasks,
    )
    return tasks


@dataclass(frozen=True)
class CandidateTopologyCompiler:
    planner: CandidatePlanner
    dut_capability_preflight: DutCapabilityPreflight
    artifact_adapter: ArtifactAdapter
    dut_endpoint_base_renderer: DutEndpointBaseRenderer[object] | None = None
    dut_host_os_renderer: DutHostOsRenderer[object] | None = None
    dut_lifecycle_renderer: DutLifecycleRenderer[object] | None = None
    dut_lifecycle_task_materializer: DutLifecycleTaskMaterializer | None = None
    traffic_generator_endpoint_renderer: TrafficGeneratorEndpointRenderer | None = None
    traffic_generator_port_base_renderer: (
        TrafficGeneratorPortBaseRenderer[object] | None
    ) = None
    traffic_generator_port_device_group_renderer: (
        TrafficGeneratorPortDeviceGroupRenderer[object] | None
    ) = None
    basic_port_composer: BasicPortComposer | None = None
    endpoint_composer: EndpointComposer | None = None
    traffic_generator_renderer: TrafficGeneratorRenderer | None = None

    def __post_init__(self) -> None:
        if (
            self.dut_lifecycle_task_materializer is not None
            and self.dut_lifecycle_renderer is None
        ):
            raise ValueError(
                "DUT lifecycle task materializer requires lifecycle renderer"
            )
        if self.endpoint_composer is not None and (
            self.dut_endpoint_base_renderer is None
            or self.traffic_generator_endpoint_renderer is None
        ):
            raise ValueError(
                "endpoint composer requires DUT base and traffic-generator "
                "endpoint renderers"
            )
        if self.basic_port_composer is not None and (
            self.traffic_generator_port_base_renderer is None
            or self.traffic_generator_port_device_group_renderer is None
        ):
            raise ValueError(
                "basic-port composer requires port-base and device-group renderers"
            )

    def analyze(self, bound: BoundTopology) -> PlanningResult:
        return self.planner.plan(bound)

    def compile_with_report(self, bound: BoundTopology) -> CandidateCompilation:
        planning = self.analyze(bound)
        resource_ids = planning.plan.iter_resource_ids()
        planning.report.assert_renderable(resource_ids)
        self.dut_capability_preflight.validate(planning.plan.dut)
        adapted = self.artifact_adapter.render(bound, planning.plan)
        traffic_generator_request = _traffic_generator_request(
            planning,
            self.traffic_generator_endpoint_renderer,
            self.traffic_generator_port_base_renderer,
            self.traffic_generator_port_device_group_renderer,
            self.traffic_generator_renderer,
        )
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
        dut_lifecycle_shadow = None
        if self.dut_lifecycle_renderer is not None:
            dut_lifecycle_shadow = self.dut_lifecycle_renderer.render(
                planning.plan.dut,
                planning.lifecycle,
            )
            dut_lifecycle_shadow.validate(
                planning.plan.dut,
                planning.lifecycle,
            )
        dut_lifecycle_task_shadow = _materialize_dut_lifecycle(
            self.dut_lifecycle_task_materializer,
            planning.plan.dut,
            planning.lifecycle,
            dut_lifecycle_shadow,
        )
        traffic_generator_endpoint_request = None
        traffic_generator_endpoint_shadow = None
        if self.traffic_generator_endpoint_renderer is not None:
            traffic_generator_endpoint_request = (
                TrafficGeneratorEndpointRenderRequest.from_render_request(
                    _require_traffic_generator_request(traffic_generator_request)
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
        traffic_generator_port_base_shadow = None
        if self.traffic_generator_port_base_renderer is not None:
            traffic_generator_port_base_request = (
                TrafficGeneratorPortBaseRenderRequest.from_render_request(
                    _require_traffic_generator_request(traffic_generator_request)
                )
            )
            traffic_generator_port_base_shadow = (
                self.traffic_generator_port_base_renderer.render(
                    traffic_generator_port_base_request
                )
            )
            traffic_generator_port_base_shadow.validate(
                traffic_generator_port_base_request
            )
        traffic_generator_port_device_group_shadow = None
        if self.traffic_generator_port_device_group_renderer is not None:
            traffic_generator_port_device_group_request = (
                TrafficGeneratorPortDeviceGroupRenderRequest.from_render_request(
                    _require_traffic_generator_request(traffic_generator_request)
                )
            )
            traffic_generator_port_device_group_shadow = (
                self.traffic_generator_port_device_group_renderer.render(
                    traffic_generator_port_device_group_request
                )
            )
            traffic_generator_port_device_group_shadow.validate(
                traffic_generator_port_device_group_request
            )
        basic_port_composition_shadow = None
        if self.basic_port_composer is not None:
            if (
                traffic_generator_port_base_shadow is None
                or traffic_generator_port_device_group_shadow is None
            ):
                raise RuntimeError("basic-port composer dependencies were not rendered")
            required_traffic_generator_request = _require_traffic_generator_request(
                traffic_generator_request
            )
            basic_port_composition_request = BasicPortCompositionRequest(
                plan=required_traffic_generator_request.plan,
                endpoint_activations=(
                    required_traffic_generator_request.endpoint_activations
                ),
                port_bases=traffic_generator_port_base_shadow,
                port_device_groups=traffic_generator_port_device_group_shadow,
            )
            basic_port_composition_shadow = self.basic_port_composer.compose(
                basic_port_composition_request
            )
            basic_port_composition_shadow.validate(basic_port_composition_request)
        endpoint_composition_shadow = None
        if self.endpoint_composer is not None:
            if (
                dut_endpoint_base_shadow is None
                or traffic_generator_endpoint_request is None
                or traffic_generator_endpoint_shadow is None
            ):
                raise RuntimeError("endpoint composer dependencies were not rendered")
            endpoint_composition_request = EndpointCompositionRequest(
                dut_plan=planning.plan.dut,
                dut_endpoint_bases=dut_endpoint_base_shadow,
                traffic_generator_request=traffic_generator_endpoint_request,
                traffic_generator_result=traffic_generator_endpoint_shadow,
            )
            endpoint_composition_shadow = self.endpoint_composer.compose(
                endpoint_composition_request
            )
            endpoint_composition_shadow.validate(endpoint_composition_request)
        traffic_generator_shadow = None
        if self.traffic_generator_renderer is not None:
            traffic_generator_request = _require_traffic_generator_request(
                traffic_generator_request
            )
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
            dut_lifecycle_shadow=dut_lifecycle_shadow,
            dut_lifecycle_task_shadow=dut_lifecycle_task_shadow,
            traffic_generator_endpoint_shadow=traffic_generator_endpoint_shadow,
            traffic_generator_port_base_shadow=traffic_generator_port_base_shadow,
            traffic_generator_port_device_group_shadow=(
                traffic_generator_port_device_group_shadow
            ),
            basic_port_composition_shadow=basic_port_composition_shadow,
            endpoint_composition_shadow=endpoint_composition_shadow,
            traffic_generator_shadow=traffic_generator_shadow,
            lifecycle=planning.lifecycle,
        )

    def compile(self, bound: BoundTopology) -> CompiledTaacArtifacts:
        return self.compile_with_report(bound).artifacts
