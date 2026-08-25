# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

from __future__ import annotations

from taac.abstractions.candidate_compiler import (
    ArtifactAdapter,
    CandidateTopologyCompiler,
)
from taac.abstractions.compilation.planner import (
    BoundTopologyPlanner,
)
from taac.abstractions.eos_bgpcpp_capabilities import (
    EosBgpCppCapabilityPreflight,
)
from taac.abstractions.eos_bgpcpp_lifecycle_materializer import (
    EosBgpCppLifecycleTaskMaterializer,
)
from taac.abstractions.eos_bgpcpp_renderer import (
    EosBgpCppEndpointBaseRenderer,
    EosBgpCppHostOsRenderer,
    EosBgpCppLifecycleRenderer,
)
from taac.abstractions.ixia_renderer import (
    SharedIxiaEndpointRenderer,
    SharedIxiaPortBaseRenderer,
    SharedIxiaPortDeviceGroupRenderer,
    SharedIxiaRenderer,
)
from taac.abstractions.native_artifact_assembler import (
    NativeTaacArtifactAssembler,
)
from taac.abstractions.taac_basic_port_composer import (
    TaacBasicPortComposer,
)
from taac.abstractions.taac_endpoint_composer import (
    TaacEndpointComposer,
)


def build_eos_bgpcpp_candidate_compiler(
    artifact_adapter: ArtifactAdapter,
) -> CandidateTopologyCompiler:
    return CandidateTopologyCompiler(
        planner=BoundTopologyPlanner(),
        dut_capability_preflight=EosBgpCppCapabilityPreflight(),
        artifact_adapter=artifact_adapter,
        dut_endpoint_base_renderer=EosBgpCppEndpointBaseRenderer(),
        dut_host_os_renderer=EosBgpCppHostOsRenderer(),
        dut_lifecycle_renderer=EosBgpCppLifecycleRenderer(),
        dut_lifecycle_task_materializer=EosBgpCppLifecycleTaskMaterializer(),
        traffic_generator_endpoint_renderer=SharedIxiaEndpointRenderer(),
        traffic_generator_port_base_renderer=SharedIxiaPortBaseRenderer(),
        traffic_generator_port_device_group_renderer=(
            SharedIxiaPortDeviceGroupRenderer()
        ),
        basic_port_composer=TaacBasicPortComposer(),
        endpoint_composer=TaacEndpointComposer(),
        traffic_generator_renderer=SharedIxiaRenderer(),
        artifact_assembler=NativeTaacArtifactAssembler(),
    )


__all__ = ("build_eos_bgpcpp_candidate_compiler",)
