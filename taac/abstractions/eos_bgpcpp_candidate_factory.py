# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

from __future__ import annotations

import logging
import typing as t
from dataclasses import replace

from taac.abstractions.artifacts import CompiledTaacArtifacts
from taac.abstractions.candidate_compiler import (
    ArtifactAdapter,
    CandidateTopologyCompiler,
    EstablishedEosArtifactAdapter,
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
from taac.test_as_a_config import types as taac_types


logger: logging.Logger = logging.getLogger(__name__)

PROFILE_FREE_EOS_UNSUPPORTED_ERRORS: tuple[type[Exception], ...] = (
    UnsupportedEosBgpCppCapabilityError,
    UnsupportedEosBgpCppLifecycleMaterializationError,
    UnsupportedEosBgpCppLifecycleRenderingError,
    UnsupportedIxiaRenderingError,
    UnsupportedRequiredIntentError,
)


class IncompleteProfileFreeEosShadowError(RuntimeError):
    """The enabled native shadow omitted output required for drift detection."""


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


def _build_eos_bgpcpp_basic_port_shadow_compiler() -> CandidateTopologyCompiler:
    return replace(
        build_eos_bgpcpp_candidate_compiler(
            artifact_adapter=EstablishedEosArtifactAdapter(
                lambda _: CompiledTaacArtifacts()
            ),
        ),
        dut_endpoint_base_renderer=None,
        dut_host_os_renderer=None,
        dut_lifecycle_renderer=None,
        dut_lifecycle_task_materializer=None,
        traffic_generator_endpoint_renderer=None,
        endpoint_composer=None,
        traffic_generator_renderer=None,
        artifact_assembler=None,
    )


def compile_profile_free_eos_if_supported(
    bound: BoundTopology,
) -> CompiledTaacArtifacts | None:
    if bound.logical_topology.legacy_profile is not None:
        return None
    try:
        return compile_profile_free_eos(bound)
    except PROFILE_FREE_EOS_UNSUPPORTED_ERRORS as error:
        if bound.logical_topology.task_compatibility_profile is not None:
            raise
        logger.warning(
            "Falling back from native profile-free EOS compilation for %s: %s",
            bound.logical_topology.name,
            error,
        )
        return None


def compile_profile_free_eos(bound: BoundTopology) -> CompiledTaacArtifacts:
    if bound.logical_topology.legacy_profile is not None:
        raise ValueError("native EOS compilation requires a profile-free topology")
    return build_eos_bgpcpp_candidate_compiler(
        native_artifacts_authoritative=True,
    ).compile(bound)


def compile_profile_free_eos_basic_ports(
    bound: BoundTopology,
) -> list[taac_types.BasicPortConfig]:
    if bound.logical_topology.legacy_profile is not None:
        raise ValueError("native EOS IXIA shadow requires a profile-free topology")
    compilation = _build_eos_bgpcpp_basic_port_shadow_compiler().compile_with_report(
        bound
    )

    basic_ports = compilation.basic_port_composition_shadow
    if basic_ports is None:
        raise IncompleteProfileFreeEosShadowError(
            "native profile-free EOS IXIA basic-port shadow is incomplete"
        )
    return t.cast(
        list[taac_types.BasicPortConfig],
        list(basic_ports.basic_port_configs),
    )


__all__ = (
    "IncompleteProfileFreeEosShadowError",
    "PROFILE_FREE_EOS_UNSUPPORTED_ERRORS",
    "build_eos_bgpcpp_candidate_compiler",
    "compile_profile_free_eos",
    "compile_profile_free_eos_basic_ports",
    "compile_profile_free_eos_if_supported",
)
