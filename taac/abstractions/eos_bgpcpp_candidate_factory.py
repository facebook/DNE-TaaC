# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

from __future__ import annotations

import logging

from taac.abstractions.artifacts import CompiledTaacArtifacts
from taac.abstractions.candidate_compiler import (
    ArtifactAdapter,
    CandidateTopologyCompiler,
)
from taac.abstractions.compilation.planner import (
    BoundTopologyPlanner,
)
from taac.abstractions.compilation.report import (
    UnsupportedRequiredIntentError,
)
from taac.abstractions.eos_bgpcpp_capabilities import (
    EosBgpCppCapabilityPreflight,
    UnsupportedEosBgpCppCapabilityError,
)
from taac.abstractions.eos_bgpcpp_lifecycle_materializer import (
    EosBgpCppLifecycleTaskMaterializer,
    UnsupportedEosBgpCppLifecycleMaterializationError,
)
from taac.abstractions.eos_bgpcpp_renderer import (
    EosBgpCppEndpointBaseRenderer,
    EosBgpCppHostOsRenderer,
    EosBgpCppLifecycleRenderer,
    UnsupportedEosBgpCppLifecycleRenderingError,
)
from taac.abstractions.ixia_renderer import (
    SharedIxiaEndpointRenderer,
    SharedIxiaPortBaseRenderer,
    SharedIxiaPortDeviceGroupRenderer,
    SharedIxiaRenderer,
    UnsupportedIxiaRenderingError,
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
from taac.abstractions.topology.model import BoundTopology


logger: logging.Logger = logging.getLogger(__name__)


def build_eos_bgpcpp_candidate_compiler(
    artifact_adapter: ArtifactAdapter | None = None,
    *,
    native_artifacts_authoritative: bool = False,
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
        native_artifacts_authoritative=native_artifacts_authoritative,
    )


def compile_profile_free_eos_if_supported(
    bound: BoundTopology,
) -> CompiledTaacArtifacts | None:
    if bound.logical_topology.legacy_profile is not None:
        return None
    try:
        return build_eos_bgpcpp_candidate_compiler(
            native_artifacts_authoritative=True,
        ).compile(bound)
    except (
        UnsupportedEosBgpCppCapabilityError,
        UnsupportedEosBgpCppLifecycleMaterializationError,
        UnsupportedEosBgpCppLifecycleRenderingError,
        UnsupportedIxiaRenderingError,
        UnsupportedRequiredIntentError,
    ) as error:
        if bound.logical_topology.task_compatibility_profile is not None:
            raise
        logger.warning(
            "Falling back from native profile-free EOS compilation for %s: %s",
            bound.logical_topology.name,
            error,
        )
        return None


__all__ = (
    "build_eos_bgpcpp_candidate_compiler",
    "compile_profile_free_eos_if_supported",
)
