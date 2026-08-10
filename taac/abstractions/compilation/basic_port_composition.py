# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

from __future__ import annotations

import typing as t
from dataclasses import dataclass

from taac.abstractions.compilation.model import (
    IxiaPlan,
    IxiaPortPlan,
    ResourceId,
    ResourceKind,
)
from taac.abstractions.compilation.traffic_generator import (
    TrafficGeneratorEndpointActivation,
    TrafficGeneratorPortBaseRenderRequest,
    TrafficGeneratorPortBaseRenderResult,
    TrafficGeneratorPortDeviceGroupRenderResult,
)


TPortBase_co = t.TypeVar("TPortBase_co", covariant=True)
TDeviceGroupConfig_co = t.TypeVar("TDeviceGroupConfig_co", covariant=True)
TBasicPort_co = t.TypeVar("TBasicPort_co", covariant=True)


@dataclass(frozen=True)
class BasicPortCompositionRequest(t.Generic[TPortBase_co, TDeviceGroupConfig_co]):
    plan: IxiaPlan
    endpoint_activations: tuple[TrafficGeneratorEndpointActivation, ...]
    port_bases: TrafficGeneratorPortBaseRenderResult[TPortBase_co]
    port_device_groups: TrafficGeneratorPortDeviceGroupRenderResult[
        TDeviceGroupConfig_co
    ]

    def __post_init__(self) -> None:
        self.port_bases.validate(self.port_base_request())
        self.port_device_groups.validate_plan(self.plan, self.endpoint_activations)

    def port_base_request(self) -> TrafficGeneratorPortBaseRenderRequest:
        return TrafficGeneratorPortBaseRenderRequest(
            ports=self.plan.ports,
            endpoint_activations=self.endpoint_activations,
        )

    def active_ports(self) -> tuple[IxiaPortPlan, ...]:
        return self.port_base_request().active_ports()


@dataclass(frozen=True)
class BasicPortDeviceGroupProvenance:
    device_group_id: ResourceId
    session_id: ResourceId
    advertisement_ids: tuple[ResourceId, ...]

    def __post_init__(self) -> None:
        _require_kind(self.device_group_id, ResourceKind.IXIA_DEVICE_GROUP)
        _require_kind(self.session_id, ResourceKind.IXIA_BGP_SESSION)
        for advertisement_id in self.advertisement_ids:
            _require_kind(advertisement_id, ResourceKind.IXIA_ADVERTISEMENT)
        _validate_unique_ids(
            "basic-port composition advertisement provenance",
            self.advertisement_ids,
        )


@dataclass(frozen=True)
class BasicPortCompositionFragment(t.Generic[TBasicPort_co]):
    port_id: ResourceId
    dut_endpoint_id: ResourceId
    physical_endpoint: str
    device_groups: tuple[BasicPortDeviceGroupProvenance, ...]
    basic_port_config: TBasicPort_co

    def __post_init__(self) -> None:
        _require_kind(self.port_id, ResourceKind.IXIA_PORT)
        _require_kind(self.dut_endpoint_id, ResourceKind.ENDPOINT)
        if not self.physical_endpoint:
            raise ValueError("composed basic-port physical endpoint must be nonempty")
        if self.basic_port_config is None:
            raise ValueError("composed basic-port config must be present")
        _validate_unique_ids(
            "basic-port composition device-group provenance",
            tuple(group.device_group_id for group in self.device_groups),
        )
        _validate_unique_ids(
            "basic-port composition session provenance",
            tuple(group.session_id for group in self.device_groups),
        )
        _validate_unique_ids(
            "basic-port composition advertisement provenance",
            tuple(
                advertisement_id
                for group in self.device_groups
                for advertisement_id in group.advertisement_ids
            ),
        )


@dataclass(frozen=True)
class BasicPortCompositionResult(t.Generic[TBasicPort_co]):
    fragments: tuple[BasicPortCompositionFragment[TBasicPort_co], ...] = ()

    def __post_init__(self) -> None:
        _validate_unique_ids(
            "basic-port composition fragment",
            tuple(fragment.port_id for fragment in self.fragments),
        )

    @property
    def basic_port_configs(self) -> tuple[TBasicPort_co, ...]:
        return tuple(fragment.basic_port_config for fragment in self.fragments)

    def validate(self, request: BasicPortCompositionRequest[object, object]) -> None:
        active_ports = request.active_ports()
        _validate_exact_order(
            "basic-port composition fragment",
            tuple(port.resource_id for port in active_ports),
            tuple(fragment.port_id for fragment in self.fragments),
        )
        bases_by_port_id = {
            fragment.port_id: fragment for fragment in request.port_bases.fragments
        }
        groups_by_port_id = {
            fragment.port_id: fragment
            for fragment in request.port_device_groups.fragments
        }
        fragments_by_port_id = {
            fragment.port_id: fragment for fragment in self.fragments
        }
        for port in active_ports:
            fragment = fragments_by_port_id[port.resource_id]
            base = bases_by_port_id[port.resource_id]
            body = groups_by_port_id[port.resource_id]
            if fragment.dut_endpoint_id != base.dut_endpoint_id:
                raise ValueError(
                    f"basic-port composition {port.resource_id} DUT endpoint mismatch"
                )
            if fragment.physical_endpoint != base.physical_endpoint:
                raise ValueError(
                    f"basic-port composition {port.resource_id} physical endpoint mismatch"
                )
            expected_provenance = tuple(
                BasicPortDeviceGroupProvenance(
                    device_group_id=group.device_group_id,
                    session_id=group.session_id,
                    advertisement_ids=group.advertisement_ids,
                )
                for group in body.device_groups
            )
            if fragment.device_groups != expected_provenance:
                raise ValueError(
                    f"basic-port composition {port.resource_id} provenance mismatch"
                )


def _require_kind(resource_id: ResourceId, expected: ResourceKind) -> None:
    if resource_id.kind is not expected:
        raise ValueError(
            f"basic-port composition resource {resource_id} must identify "
            f"{expected.value}"
        )


def _validate_unique_ids(subject: str, resource_ids: tuple[ResourceId, ...]) -> None:
    if len(frozenset(resource_ids)) != len(resource_ids):
        raise ValueError(f"{subject} IDs must be unique")


def _validate_exact_order(
    subject: str,
    expected: tuple[ResourceId, ...],
    actual: tuple[ResourceId, ...],
) -> None:
    _validate_unique_ids(subject, actual)
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
    if actual != expected:
        raise ValueError(
            f"{subject} order mismatch: expected={expected}, actual={actual}"
        )


__all__ = (
    "BasicPortCompositionFragment",
    "BasicPortCompositionRequest",
    "BasicPortCompositionResult",
    "BasicPortDeviceGroupProvenance",
)
