# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

from __future__ import annotations

import typing as t
from dataclasses import dataclass

from taac.abstractions.compilation.dut import (
    DutEndpointBaseRenderResult,
)
from taac.abstractions.compilation.model import (
    DutPlan,
    ResourceId,
    ResourceKind,
)
from taac.abstractions.compilation.traffic_generator import (
    TrafficGeneratorEndpointRenderRequest,
    TrafficGeneratorEndpointRenderResult,
)


TEndpoint_co = t.TypeVar("TEndpoint_co", covariant=True)


@dataclass(frozen=True)
class EndpointCompositionRequest(t.Generic[TEndpoint_co]):
    dut_plan: DutPlan
    dut_endpoint_bases: DutEndpointBaseRenderResult[TEndpoint_co]
    traffic_generator_request: TrafficGeneratorEndpointRenderRequest
    traffic_generator_result: TrafficGeneratorEndpointRenderResult

    def __post_init__(self) -> None:
        self.dut_endpoint_bases.validate(self.dut_plan)
        self.traffic_generator_result.validate(self.traffic_generator_request)
        planned_dut_ids = frozenset(
            endpoint.resource_id
            for endpoint in self.dut_plan.endpoints
            if endpoint.is_dut
        )
        referenced_traffic_ids = tuple(
            dict.fromkeys(
                (
                    *(
                        activation.endpoint_id
                        for activation in self.traffic_generator_request.endpoint_activations
                    ),
                    *self.traffic_generator_result.consumed_endpoint_ids,
                    *(
                        patch.endpoint_id
                        for patch in self.traffic_generator_result.endpoint_patches
                    ),
                    *(
                        port_request.port.dut_endpoint_id
                        for port_request in self.traffic_generator_request.ports
                    ),
                )
            )
        )
        unexpected_traffic_ids = tuple(
            endpoint_id
            for endpoint_id in referenced_traffic_ids
            if endpoint_id not in planned_dut_ids
        )
        if unexpected_traffic_ids:
            raise ValueError(
                "endpoint composition traffic-generator coverage mismatch: "
                f"unexpected={unexpected_traffic_ids}"
            )


@dataclass(frozen=True)
class EndpointCompositionFragment(t.Generic[TEndpoint_co]):
    endpoint_id: ResourceId
    physical_identifier: str
    endpoint: TEndpoint_co

    def __post_init__(self) -> None:
        if self.endpoint_id.kind is not ResourceKind.ENDPOINT:
            raise ValueError(
                f"endpoint composition fragment {self.endpoint_id} must reference "
                "an endpoint"
            )
        if not self.physical_identifier:
            raise ValueError("composed endpoint physical identifier must be nonempty")
        if self.endpoint is None:
            raise ValueError("composed endpoint value must be present")


@dataclass(frozen=True)
class EndpointCompositionResult(t.Generic[TEndpoint_co]):
    fragments: tuple[EndpointCompositionFragment[TEndpoint_co], ...] = ()

    def __post_init__(self) -> None:
        _validate_unique_ids(
            "endpoint composition fragment",
            self.endpoint_ids,
        )

    @property
    def endpoint_ids(self) -> tuple[ResourceId, ...]:
        return tuple(fragment.endpoint_id for fragment in self.fragments)

    @property
    def endpoints(self) -> tuple[TEndpoint_co, ...]:
        return tuple(fragment.endpoint for fragment in self.fragments)

    def validate(self, request: EndpointCompositionRequest[object]) -> None:
        expected_endpoints = tuple(
            endpoint for endpoint in request.dut_plan.endpoints if endpoint.is_dut
        )
        expected_ids = tuple(endpoint.resource_id for endpoint in expected_endpoints)
        _validate_exact_order(
            "endpoint composition fragment",
            expected_ids,
            self.endpoint_ids,
        )
        endpoints_by_id = {
            endpoint.resource_id: endpoint for endpoint in expected_endpoints
        }
        for fragment in self.fragments:
            expected_identifier = endpoints_by_id[
                fragment.endpoint_id
            ].physical_identifier
            if fragment.physical_identifier != expected_identifier:
                raise ValueError(
                    f"endpoint composition fragment {fragment.endpoint_id} physical "
                    f"identifier mismatch: expected={expected_identifier!r}, "
                    f"actual={fragment.physical_identifier!r}"
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
    "EndpointCompositionFragment",
    "EndpointCompositionRequest",
    "EndpointCompositionResult",
)
