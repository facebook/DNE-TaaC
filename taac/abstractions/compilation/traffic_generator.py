# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

from __future__ import annotations

import typing as t
from dataclasses import dataclass, field
from enum import Enum

from taac.abstractions.compilation.ixia_presentation import (
    resolve_ixia_port_presentations,
)
from taac.abstractions.compilation.legacy_ixia_identity import (
    LegacyIxiaIdentitySidecar,
)
from taac.abstractions.compilation.model import (
    EndpointSetupMode,
    IxiaNextHopMode,
    IxiaPlan,
    IxiaPortPlan,
    ResourceId,
    ResourceKind,
    TopologyCompilationPlan,
)
from taac.abstractions.routing_semantics import PeerRelationship


_ENDPOINT_CONNECTION_RELATIONSHIP_ORDER = {
    PeerRelationship.EXTERNAL: 0,
    PeerRelationship.INTERNAL: 1,
    PeerRelationship.MONITOR: 2,
}
TPortBase_co = t.TypeVar("TPortBase_co", covariant=True)
TDeviceGroupConfig_co = t.TypeVar("TDeviceGroupConfig_co", covariant=True)


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
class TrafficGeneratorEndpointPortRequest:
    port: IxiaPortPlan
    relationship: PeerRelationship
    ixia_port_label: str

    def __post_init__(self) -> None:
        if not isinstance(self.relationship, PeerRelationship):
            raise TypeError("traffic-generator port relationship must be typed")
        if not self.ixia_port_label:
            raise ValueError("traffic-generator IXIA port label must be nonempty")


@dataclass(frozen=True)
class TrafficGeneratorEndpointRenderRequest:
    ports: tuple[TrafficGeneratorEndpointPortRequest, ...]
    endpoint_activations: tuple[TrafficGeneratorEndpointActivation, ...]

    def __post_init__(self) -> None:
        _validate_unique_resource_ids(
            "traffic-generator endpoint port request",
            tuple(port_request.port.resource_id for port_request in self.ports),
        )
        _validate_exact_resource_order(
            "traffic-generator endpoint activation",
            _ordered_dut_endpoint_ids_from_ports(
                tuple(port_request.port for port_request in self.ports)
            ),
            tuple(activation.endpoint_id for activation in self.endpoint_activations),
        )

    def endpoint_ports(
        self,
        endpoint_id: ResourceId,
    ) -> tuple[TrafficGeneratorEndpointPortRequest, ...]:
        return tuple(
            port_request
            for port_request in self.ports
            if port_request.port.dut_endpoint_id == endpoint_id
        )

    def direct_connection_ports(
        self,
        endpoint_id: ResourceId,
    ) -> tuple[TrafficGeneratorEndpointPortRequest, ...]:
        return tuple(
            sorted(
                self.endpoint_ports(endpoint_id),
                key=lambda port_request: _ENDPOINT_CONNECTION_RELATIONSHIP_ORDER[
                    port_request.relationship
                ],
            )
        )

    @classmethod
    def from_render_request(
        cls,
        request: TrafficGeneratorRenderRequest,
    ) -> TrafficGeneratorEndpointRenderRequest:
        group_ids_by_port: dict[ResourceId, list[ResourceId]] = {}
        for group in request.plan.device_groups:
            group_ids_by_port.setdefault(group.port_id, []).append(group.resource_id)
        session_group_ids = tuple(
            session.device_group_id for session in request.plan.bgp_sessions
        )
        _validate_unique_resource_ids(
            "traffic-generator endpoint session group",
            session_group_ids,
        )
        sessions_by_group = {
            session.device_group_id: session for session in request.plan.bgp_sessions
        }
        presentations_by_port_id = {
            presentation.resource_id: presentation
            for presentation in resolve_ixia_port_presentations(
                request.plan,
                request.legacy_identity,
            )
        }
        ports = []
        for port in request.plan.ports:
            relationships: set[PeerRelationship] = set()
            for group_id in group_ids_by_port.get(port.resource_id, ()):
                session = sessions_by_group.get(group_id)
                if session is None:
                    raise ValueError(
                        f"IXIA group {group_id} has no BGP session for endpoint "
                        "rendering"
                    )
                relationships.add(session.relationship)
            if len(relationships) != 1:
                raise ValueError(
                    f"IXIA port {port.resource_id} must have exactly one peer "
                    "relationship; found "
                    f"{tuple(sorted(relationships, key=lambda item: item.value))}"
                )
            ports.append(
                TrafficGeneratorEndpointPortRequest(
                    port=port,
                    relationship=next(iter(relationships)),
                    ixia_port_label=(
                        presentations_by_port_id[
                            port.resource_id
                        ].endpoint_ixia_port_label
                    ),
                )
            )
        return cls(
            ports=tuple(ports),
            endpoint_activations=request.endpoint_activations,
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
class TrafficGeneratorEndpointRenderResult:
    consumed_endpoint_ids: tuple[ResourceId, ...]
    consumed_port_ids: tuple[ResourceId, ...]
    endpoint_patches: tuple[TrafficGeneratorEndpointPatch, ...] = ()

    def __post_init__(self) -> None:
        _validate_unique_resource_ids(
            "traffic-generator endpoint result",
            self.consumed_endpoint_ids,
        )
        _validate_unique_resource_ids(
            "traffic-generator endpoint result port",
            self.consumed_port_ids,
        )
        _validate_unique_resource_ids(
            "traffic-generator endpoint patch",
            tuple(patch.endpoint_id for patch in self.endpoint_patches),
        )

    def validate(self, request: TrafficGeneratorEndpointRenderRequest) -> None:
        _validate_exact_resource_order(
            "traffic-generator endpoint result",
            tuple(
                activation.endpoint_id for activation in request.endpoint_activations
            ),
            self.consumed_endpoint_ids,
        )
        _validate_exact_resource_order(
            "traffic-generator endpoint result port",
            tuple(port_request.port.resource_id for port_request in request.ports),
            self.consumed_port_ids,
        )
        expected_patch_ids = tuple(
            activation.endpoint_id
            for activation in request.endpoint_activations
            if activation.emit_endpoint_patch
        )
        _validate_exact_resource_order(
            "traffic-generator endpoint patch",
            expected_patch_ids,
            tuple(patch.endpoint_id for patch in self.endpoint_patches),
        )
        for patch in self.endpoint_patches:
            expected_ixia_port_ids = tuple(
                port_request.port.resource_id
                for port_request in request.endpoint_ports(patch.endpoint_id)
            )
            expected_connection_port_ids = tuple(
                port_request.port.resource_id
                for port_request in request.direct_connection_ports(patch.endpoint_id)
            )
            _validate_exact_resource_order(
                "traffic-generator IXIA port fragment",
                expected_ixia_port_ids,
                tuple(fragment.port_id for fragment in patch.ixia_port_fragments),
            )
            _validate_exact_resource_order(
                "traffic-generator direct connection fragment",
                expected_connection_port_ids,
                tuple(
                    fragment.port_id for fragment in patch.direct_connection_fragments
                ),
            )


@dataclass(frozen=True)
class TrafficGeneratorPortBaseRenderRequest:
    ports: tuple[IxiaPortPlan, ...]
    endpoint_activations: tuple[TrafficGeneratorEndpointActivation, ...]

    def __post_init__(self) -> None:
        _validate_unique_resource_ids(
            "traffic-generator port-base request",
            tuple(port.resource_id for port in self.ports),
        )
        _validate_exact_resource_order(
            "traffic-generator port-base endpoint activation",
            _ordered_dut_endpoint_ids_from_ports(self.ports),
            tuple(activation.endpoint_id for activation in self.endpoint_activations),
        )

    @classmethod
    def from_render_request(
        cls,
        request: TrafficGeneratorRenderRequest,
    ) -> TrafficGeneratorPortBaseRenderRequest:
        return cls(
            ports=request.plan.ports,
            endpoint_activations=request.endpoint_activations,
        )

    def active_ports(self) -> tuple[IxiaPortPlan, ...]:
        return _active_ports(
            self.ports,
            self.endpoint_activations,
        )


@dataclass(frozen=True)
class TrafficGeneratorPortBaseFragment(t.Generic[TPortBase_co]):
    port_id: ResourceId
    dut_endpoint_id: ResourceId
    physical_endpoint: str
    basic_port_config: TPortBase_co

    def __post_init__(self) -> None:
        _require_ixia_port_id(self.port_id)
        _require_endpoint_id(self.dut_endpoint_id)
        if not self.physical_endpoint:
            raise ValueError("traffic-generator physical endpoint must be nonempty")
        if self.basic_port_config is None:
            raise ValueError("traffic-generator basic port config must be present")


@dataclass(frozen=True)
class TrafficGeneratorPortBaseRenderResult(t.Generic[TPortBase_co]):
    consumed_port_ids: tuple[ResourceId, ...]
    fragments: tuple[TrafficGeneratorPortBaseFragment[TPortBase_co], ...] = ()

    def __post_init__(self) -> None:
        _validate_unique_resource_ids(
            "traffic-generator port-base result",
            self.consumed_port_ids,
        )
        _validate_unique_resource_ids(
            "traffic-generator port-base fragment",
            tuple(fragment.port_id for fragment in self.fragments),
        )

    def validate(self, request: TrafficGeneratorPortBaseRenderRequest) -> None:
        _validate_exact_resource_order(
            "traffic-generator port-base result",
            tuple(port.resource_id for port in request.ports),
            self.consumed_port_ids,
        )
        active_ports = request.active_ports()
        _validate_exact_resource_order(
            "traffic-generator port-base fragment",
            tuple(port.resource_id for port in active_ports),
            tuple(fragment.port_id for fragment in self.fragments),
        )
        for port, fragment in zip(active_ports, self.fragments, strict=True):
            if fragment.dut_endpoint_id != port.dut_endpoint_id:
                raise ValueError(
                    "traffic-generator port-base endpoint ID mismatch: "
                    f"expected={port.dut_endpoint_id}, "
                    f"actual={fragment.dut_endpoint_id}"
                )
            expected_endpoint = f"{port.dut_physical_identifier}:{port.dut_interface}"
            if fragment.physical_endpoint != expected_endpoint:
                raise ValueError(
                    "traffic-generator port-base physical endpoint mismatch: "
                    f"expected={expected_endpoint!r}, "
                    f"actual={fragment.physical_endpoint!r}"
                )


@dataclass(frozen=True)
class TrafficGeneratorPortDeviceGroupRenderRequest(TrafficGeneratorRenderRequest):
    @classmethod
    def from_render_request(
        cls,
        request: TrafficGeneratorRenderRequest,
    ) -> TrafficGeneratorPortDeviceGroupRenderRequest:
        return cls(
            plan=request.plan,
            legacy_identity=request.legacy_identity,
            endpoint_activations=request.endpoint_activations,
        )

    def active_ports(self) -> tuple[IxiaPortPlan, ...]:
        return _active_ports(
            self.plan.ports,
            self.endpoint_activations,
        )


@dataclass(frozen=True)
class TrafficGeneratorDeviceGroupConfigFragment(t.Generic[TDeviceGroupConfig_co]):
    device_group_id: ResourceId
    session_id: ResourceId
    advertisement_ids: tuple[ResourceId, ...]
    device_group_config: TDeviceGroupConfig_co

    def __post_init__(self) -> None:
        _require_resource_kinds(
            (self.device_group_id,),
            ResourceKind.IXIA_DEVICE_GROUP,
            "traffic-generator device-group config fragment",
        )
        _require_resource_kinds(
            (self.session_id,),
            ResourceKind.IXIA_BGP_SESSION,
            "traffic-generator device-group session fragment",
        )
        _require_resource_kinds(
            self.advertisement_ids,
            ResourceKind.IXIA_ADVERTISEMENT,
            "traffic-generator device-group advertisement fragment",
        )
        _validate_unique_resource_ids(
            "traffic-generator device-group advertisement fragment",
            self.advertisement_ids,
        )
        if self.device_group_config is None:
            raise ValueError("traffic-generator device-group config must be present")


@dataclass(frozen=True)
class TrafficGeneratorPortDeviceGroupFragment(t.Generic[TDeviceGroupConfig_co]):
    port_id: ResourceId
    device_groups: tuple[
        TrafficGeneratorDeviceGroupConfigFragment[TDeviceGroupConfig_co], ...
    ]

    def __post_init__(self) -> None:
        _require_ixia_port_id(self.port_id)
        for subject, resource_ids in (
            ("traffic-generator port device-group fragment", self.device_group_ids),
            ("traffic-generator port session fragment", self.session_ids),
            (
                "traffic-generator port advertisement fragment",
                self.advertisement_ids,
            ),
        ):
            _validate_unique_resource_ids(subject, resource_ids)

    @property
    def device_group_ids(self) -> tuple[ResourceId, ...]:
        return tuple(fragment.device_group_id for fragment in self.device_groups)

    @property
    def session_ids(self) -> tuple[ResourceId, ...]:
        return tuple(fragment.session_id for fragment in self.device_groups)

    @property
    def advertisement_ids(self) -> tuple[ResourceId, ...]:
        return tuple(
            advertisement_id
            for fragment in self.device_groups
            for advertisement_id in fragment.advertisement_ids
        )

    @property
    def device_group_configs(self) -> tuple[TDeviceGroupConfig_co, ...]:
        return tuple(fragment.device_group_config for fragment in self.device_groups)


@dataclass(frozen=True)
class TrafficGeneratorPortDeviceGroupRenderResult(t.Generic[TDeviceGroupConfig_co]):
    referenced_resource_ids: tuple[ResourceId, ...]
    fragments: tuple[
        TrafficGeneratorPortDeviceGroupFragment[TDeviceGroupConfig_co], ...
    ] = ()

    def __post_init__(self) -> None:
        _validate_unique_resource_ids(
            "traffic-generator port device-group result resource",
            self.referenced_resource_ids,
        )
        _validate_unique_resource_ids(
            "traffic-generator port device-group result fragment",
            tuple(fragment.port_id for fragment in self.fragments),
        )

    def validate(
        self,
        request: TrafficGeneratorPortDeviceGroupRenderRequest,
    ) -> None:
        self.validate_plan(request.plan, request.endpoint_activations)

    def validate_plan(
        self,
        plan: IxiaPlan,
        endpoint_activations: tuple[TrafficGeneratorEndpointActivation, ...],
    ) -> None:
        _validate_exact_resource_order(
            "traffic-generator port device-group result resource",
            plan.iter_resource_ids(),
            self.referenced_resource_ids,
        )
        active_ports = _active_ports(plan.ports, endpoint_activations)
        _validate_exact_resource_order(
            "traffic-generator port device-group result fragment",
            tuple(port.resource_id for port in active_ports),
            tuple(fragment.port_id for fragment in self.fragments),
        )
        fragments_by_port_id = {
            fragment.port_id: fragment for fragment in self.fragments
        }
        for port in active_ports:
            fragment = fragments_by_port_id[port.resource_id]
            group_ids = tuple(
                group.resource_id
                for group in plan.device_groups
                if group.port_id == port.resource_id
            )
            _validate_exact_resource_order(
                "traffic-generator port device-group fragment",
                group_ids,
                fragment.device_group_ids,
            )
            fragments_by_group_id = {
                group_fragment.device_group_id: group_fragment
                for group_fragment in fragment.device_groups
            }
            for group_id in group_ids:
                group_fragment = fragments_by_group_id[group_id]
                session_ids = tuple(
                    session.resource_id
                    for session in plan.bgp_sessions
                    if session.device_group_id == group_id
                )
                _validate_exact_resource_order(
                    "traffic-generator device-group session fragment",
                    session_ids,
                    (group_fragment.session_id,),
                )
                advertisement_ids = tuple(
                    advertisement.resource_id
                    for advertisement in plan.advertisements
                    if advertisement.device_group_id == group_id
                )
                _validate_exact_resource_order(
                    "traffic-generator device-group advertisement fragment",
                    advertisement_ids,
                    group_fragment.advertisement_ids,
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


def _active_ports(
    ports: tuple[IxiaPortPlan, ...],
    endpoint_activations: tuple[TrafficGeneratorEndpointActivation, ...],
) -> tuple[IxiaPortPlan, ...]:
    activations = {
        activation.endpoint_id: activation for activation in endpoint_activations
    }
    return tuple(
        port
        for port in ports
        if activations[port.dut_endpoint_id].emit_basic_port_configs
    )


def _ordered_dut_endpoint_ids(plan: IxiaPlan) -> tuple[ResourceId, ...]:
    return _ordered_dut_endpoint_ids_from_ports(plan.ports)


def _ordered_dut_endpoint_ids_from_ports(
    ports: tuple[IxiaPortPlan, ...],
) -> tuple[ResourceId, ...]:
    return tuple(dict.fromkeys(port.dut_endpoint_id for port in ports))


def _require_endpoint_id(resource_id: ResourceId) -> None:
    if resource_id.kind is not ResourceKind.ENDPOINT:
        raise ValueError(f"resource {resource_id} must identify an endpoint")


def _require_ixia_port_id(resource_id: ResourceId) -> None:
    if resource_id.kind is not ResourceKind.IXIA_PORT:
        raise ValueError(f"resource {resource_id} must identify an IXIA port")


def _require_resource_kinds(
    resource_ids: tuple[ResourceId, ...],
    expected_kind: ResourceKind,
    subject: str,
) -> None:
    invalid = tuple(
        resource_id
        for resource_id in resource_ids
        if resource_id.kind is not expected_kind
    )
    if invalid:
        raise ValueError(
            f"{subject} IDs must identify {expected_kind.value} resources: "
            f"invalid={invalid}"
        )


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


def _validate_exact_resource_order(
    subject: str,
    expected: tuple[ResourceId, ...],
    actual: tuple[ResourceId, ...],
) -> None:
    _validate_exact_resource_coverage(subject, expected, actual)
    if actual != expected:
        raise ValueError(
            f"{subject} order mismatch: expected={expected}, actual={actual}"
        )


__all__ = (
    "TrafficGeneratorEndpointActivation",
    "TrafficGeneratorEndpointPortRequest",
    "TrafficGeneratorEndpointPatch",
    "TrafficGeneratorEndpointRenderRequest",
    "TrafficGeneratorEndpointRenderResult",
    "TrafficGeneratorDirectConnectionFragment",
    "TrafficGeneratorDeviceGroupConfigFragment",
    "TrafficGeneratorIxiaPortFragment",
    "TrafficGeneratorLifecycleFragment",
    "TrafficGeneratorLifecycleSlot",
    "TrafficGeneratorPortBaseFragment",
    "TrafficGeneratorPortBaseRenderRequest",
    "TrafficGeneratorPortBaseRenderResult",
    "TrafficGeneratorPortDeviceGroupFragment",
    "TrafficGeneratorPortDeviceGroupRenderRequest",
    "TrafficGeneratorPortDeviceGroupRenderResult",
    "TrafficGeneratorRenderRequest",
    "TrafficGeneratorRenderResult",
)
