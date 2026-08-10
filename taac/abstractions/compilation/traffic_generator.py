# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

from __future__ import annotations

import typing as t
from dataclasses import dataclass, field
from enum import Enum

from taac.abstractions.compilation.legacy_ixia_identity import (
    LegacyIxiaIdentitySidecar,
)
from taac.abstractions.compilation.model import (
    EndpointSetupMode,
    IxiaNextHopMode,
    IxiaPlan,
    ResourceId,
    ResourceKind,
    TopologyCompilationPlan,
)


class TrafficGeneratorLifecycleSlot(str, Enum):
    CONFIGURATION = "traffic_generator_configuration"


@dataclass(frozen=True)
class TrafficGeneratorEndpointActivation:
    endpoint_id: ResourceId
    emit_endpoint_patch: bool
    emit_basic_port_configs: bool
    emit_lifecycle: bool

    def __post_init__(self) -> None:
        _require_endpoint_id(self.endpoint_id)
        for field_name, value in (
            ("emit_endpoint_patch", self.emit_endpoint_patch),
            ("emit_basic_port_configs", self.emit_basic_port_configs),
            ("emit_lifecycle", self.emit_lifecycle),
        ):
            if not isinstance(value, bool):
                raise TypeError(f"traffic-generator {field_name} must be a bool")


@dataclass(frozen=True)
class TrafficGeneratorRenderRequest:
    plan: IxiaPlan
    legacy_identity: LegacyIxiaIdentitySidecar = field(
        default_factory=LegacyIxiaIdentitySidecar
    )
    endpoint_activations: tuple[TrafficGeneratorEndpointActivation, ...] = ()

    def __post_init__(self) -> None:
        self.legacy_identity.validate(self.plan.iter_resource_ids())
        expected_endpoint_ids = _ordered_dut_endpoint_ids(self.plan)
        actual_endpoint_ids = tuple(
            activation.endpoint_id for activation in self.endpoint_activations
        )
        _validate_exact_resource_coverage(
            "traffic-generator endpoint activation",
            expected_endpoint_ids,
            actual_endpoint_ids,
        )

    @classmethod
    def from_compilation_plan(
        cls,
        plan: TopologyCompilationPlan,
        legacy_identity: LegacyIxiaIdentitySidecar,
    ) -> TrafficGeneratorRenderRequest:
        setup_modes = {
            endpoint.resource_id: endpoint.setup_mode for endpoint in plan.dut.endpoints
        }
        activations = tuple(
            _endpoint_activation(endpoint_id, setup_modes[endpoint_id])
            for endpoint_id in _ordered_dut_endpoint_ids(plan.ixia)
        )
        return cls(
            plan=plan.ixia,
            legacy_identity=legacy_identity,
            endpoint_activations=activations,
        )


@dataclass(frozen=True)
class TrafficGeneratorIxiaPortFragment:
    port_id: ResourceId
    label: str

    def __post_init__(self) -> None:
        _require_ixia_port_id(self.port_id)
        if not self.label:
            raise ValueError("traffic-generator IXIA port label must be nonempty")


@dataclass(frozen=True)
class TrafficGeneratorDirectConnectionFragment:
    port_id: ResourceId
    connection: t.Any

    def __post_init__(self) -> None:
        _require_ixia_port_id(self.port_id)


@dataclass(frozen=True)
class TrafficGeneratorEndpointPatch:
    endpoint_id: ResourceId
    ixia_port_fragments: tuple[TrafficGeneratorIxiaPortFragment, ...] = ()
    direct_connection_fragments: tuple[
        TrafficGeneratorDirectConnectionFragment, ...
    ] = ()

    def __post_init__(self) -> None:
        _require_endpoint_id(self.endpoint_id)
        if not self.ixia_port_fragments and not self.direct_connection_fragments:
            raise ValueError("traffic-generator endpoint patch must not be empty")
        _validate_unique_resource_ids(
            "traffic-generator IXIA port fragment",
            tuple(fragment.port_id for fragment in self.ixia_port_fragments),
        )
        _validate_unique_resource_ids(
            "traffic-generator direct connection fragment",
            tuple(fragment.port_id for fragment in self.direct_connection_fragments),
        )

    @property
    def ixia_ports(self) -> tuple[str, ...]:
        return tuple(fragment.label for fragment in self.ixia_port_fragments)

    @property
    def direct_ixia_connections(self) -> tuple[t.Any, ...]:
        return tuple(
            fragment.connection for fragment in self.direct_connection_fragments
        )


@dataclass(frozen=True)
class TrafficGeneratorLifecycleFragment:
    slot: TrafficGeneratorLifecycleSlot
    tasks: tuple[t.Any, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.slot, TrafficGeneratorLifecycleSlot):
            raise TypeError("traffic-generator lifecycle slot must be typed")
        if not self.tasks:
            raise ValueError("traffic-generator lifecycle fragment must not be empty")


@dataclass(frozen=True)
class TrafficGeneratorRenderResult:
    consumed_resource_ids: tuple[ResourceId, ...]
    basic_port_configs: tuple[t.Any, ...] = ()
    basic_traffic_item_configs: tuple[t.Any, ...] = ()
    endpoint_patches: tuple[TrafficGeneratorEndpointPatch, ...] = ()
    lifecycle_fragments: tuple[TrafficGeneratorLifecycleFragment, ...] = ()

    def __post_init__(self) -> None:
        _validate_unique_resource_ids(
            "traffic-generator result resource",
            self.consumed_resource_ids,
        )
        _validate_unique_resource_ids(
            "traffic-generator endpoint patch",
            tuple(patch.endpoint_id for patch in self.endpoint_patches),
        )
        slots = tuple(fragment.slot for fragment in self.lifecycle_fragments)
        if len(frozenset(slots)) != len(slots):
            raise ValueError("traffic-generator lifecycle slots must be unique")

    def validate(self, request: TrafficGeneratorRenderRequest) -> None:
        _validate_exact_resource_coverage(
            "traffic-generator result",
            request.plan.iter_resource_ids(),
            self.consumed_resource_ids,
        )
        activations = {
            activation.endpoint_id: activation
            for activation in request.endpoint_activations
        }
        expected_patch_ids = tuple(
            activation.endpoint_id
            for activation in request.endpoint_activations
            if activation.emit_endpoint_patch
        )
        _validate_exact_resource_coverage(
            "traffic-generator endpoint patch",
            expected_patch_ids,
            tuple(patch.endpoint_id for patch in self.endpoint_patches),
        )
        for patch in self.endpoint_patches:
            expected_port_ids = tuple(
                port.resource_id
                for port in request.plan.ports
                if port.dut_endpoint_id == patch.endpoint_id
            )
            _validate_exact_resource_coverage(
                "traffic-generator IXIA port fragment",
                expected_port_ids,
                tuple(fragment.port_id for fragment in patch.ixia_port_fragments),
            )
            _validate_exact_resource_coverage(
                "traffic-generator direct connection fragment",
                expected_port_ids,
                tuple(
                    fragment.port_id for fragment in patch.direct_connection_fragments
                ),
            )
        expected_port_count = sum(
            activations[port.dut_endpoint_id].emit_basic_port_configs
            for port in request.plan.ports
        )
        if len(self.basic_port_configs) != expected_port_count:
            raise ValueError(
                "traffic-generator basic port config count mismatch: "
                f"expected={expected_port_count}, "
                f"actual={len(self.basic_port_configs)}"
            )
        if self.basic_traffic_item_configs:
            raise ValueError(
                "traffic-generator traffic-item rendering is outside Phase 1.5"
            )
        lifecycle_is_active = any(
            activation.emit_lifecycle for activation in request.endpoint_activations
        )
        requires_configuration = lifecycle_is_active and any(
            advertisement.next_hop.mode is IxiaNextHopMode.FORMULAIC
            for advertisement in request.plan.advertisements
        )
        expected_slots = (
            (TrafficGeneratorLifecycleSlot.CONFIGURATION,)
            if requires_configuration
            else ()
        )
        actual_slots = tuple(fragment.slot for fragment in self.lifecycle_fragments)
        if actual_slots != expected_slots:
            raise ValueError(
                "traffic-generator lifecycle slot mismatch: "
                f"expected={expected_slots}, actual={actual_slots}"
            )


def _endpoint_activation(
    endpoint_id: ResourceId,
    setup_mode: EndpointSetupMode,
) -> TrafficGeneratorEndpointActivation:
    emit_realization = setup_mode is not EndpointSetupMode.VERIFY_ONLY
    return TrafficGeneratorEndpointActivation(
        endpoint_id=endpoint_id,
        emit_endpoint_patch=emit_realization,
        emit_basic_port_configs=emit_realization,
        emit_lifecycle=setup_mode is EndpointSetupMode.FULL,
    )


def _ordered_dut_endpoint_ids(plan: IxiaPlan) -> tuple[ResourceId, ...]:
    return tuple(dict.fromkeys(port.dut_endpoint_id for port in plan.ports))


def _require_endpoint_id(resource_id: ResourceId) -> None:
    if resource_id.kind is not ResourceKind.ENDPOINT:
        raise ValueError(f"resource {resource_id} must identify an endpoint")


def _require_ixia_port_id(resource_id: ResourceId) -> None:
    if resource_id.kind is not ResourceKind.IXIA_PORT:
        raise ValueError(f"resource {resource_id} must identify an IXIA port")


def _validate_unique_resource_ids(
    subject: str,
    resource_ids: tuple[ResourceId, ...],
) -> None:
    if len(frozenset(resource_ids)) != len(resource_ids):
        raise ValueError(f"{subject} IDs must be unique")


def _validate_exact_resource_coverage(
    subject: str,
    expected: tuple[ResourceId, ...],
    actual: tuple[ResourceId, ...],
) -> None:
    _validate_unique_resource_ids(subject, actual)
    missing = tuple(
        resource_id for resource_id in expected if resource_id not in actual
    )
    unexpected = tuple(
        resource_id for resource_id in actual if resource_id not in expected
    )
    if missing or unexpected:
        raise ValueError(
            f"{subject} coverage mismatch: missing={missing}, unexpected={unexpected}"
        )


__all__ = (
    "TrafficGeneratorEndpointActivation",
    "TrafficGeneratorEndpointPatch",
    "TrafficGeneratorDirectConnectionFragment",
    "TrafficGeneratorIxiaPortFragment",
    "TrafficGeneratorLifecycleFragment",
    "TrafficGeneratorLifecycleSlot",
    "TrafficGeneratorRenderRequest",
    "TrafficGeneratorRenderResult",
)
