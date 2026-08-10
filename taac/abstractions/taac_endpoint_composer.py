# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

from __future__ import annotations

from dataclasses import dataclass

from taac.abstractions.compilation.endpoint_composition import (
    EndpointCompositionFragment,
    EndpointCompositionRequest,
    EndpointCompositionResult,
)
from taac.abstractions.compilation.traffic_generator import (
    TrafficGeneratorEndpointPatch,
)
from taac.test_as_a_config import types as taac_types


@dataclass(frozen=True)
class TaacEndpointComposer:
    """Composes platform base fields and shared IXIA fields by resource ID."""

    def compose(
        self,
        request: EndpointCompositionRequest[object],
    ) -> EndpointCompositionResult[taac_types.Endpoint]:
        bases_by_id = {
            fragment.endpoint_id: fragment
            for fragment in request.dut_endpoint_bases.fragments
        }
        patches_by_id = {
            patch.endpoint_id: patch
            for patch in request.traffic_generator_result.endpoint_patches
        }
        fragments = []
        for endpoint_plan in request.dut_plan.endpoints:
            if not endpoint_plan.is_dut:
                continue
            base_fragment = bases_by_id[endpoint_plan.resource_id]
            base = base_fragment.endpoint
            if not isinstance(base, taac_types.Endpoint):
                raise TypeError(
                    f"endpoint base {endpoint_plan.resource_id} must be a TAAC Endpoint"
                )
            _validate_base(base_fragment.physical_identifier, base)
            fragments.append(
                EndpointCompositionFragment(
                    endpoint_id=endpoint_plan.resource_id,
                    physical_identifier=base_fragment.physical_identifier,
                    endpoint=_compose_endpoint(
                        base,
                        patches_by_id.get(endpoint_plan.resource_id),
                    ),
                )
            )
        result: EndpointCompositionResult[taac_types.Endpoint] = (
            EndpointCompositionResult(fragments=tuple(fragments))
        )
        result.validate(request)
        return result


def _validate_base(
    physical_identifier: str,
    base: taac_types.Endpoint,
) -> None:
    if base.name != physical_identifier:
        raise ValueError(
            "TAAC endpoint base name mismatch: "
            f"expected={physical_identifier!r}, actual={base.name!r}"
        )
    if base.dut is not True:
        raise ValueError("TAAC endpoint base must identify a DUT")
    if base.ixia_ports is not None or base.direct_ixia_connections is not None:
        raise ValueError("TAAC endpoint base overlaps IXIA-owned fields")


def _compose_endpoint(
    base: taac_types.Endpoint,
    patch: TrafficGeneratorEndpointPatch | None,
) -> taac_types.Endpoint:
    ixia_ports = None
    direct_ixia_connections = None
    if patch is not None:
        if any(not isinstance(label, str) for label in patch.ixia_ports):
            raise TypeError("TAAC endpoint IXIA port labels must be strings")
        if any(
            not isinstance(connection, taac_types.DirectIxiaConnection)
            for connection in patch.direct_ixia_connections
        ):
            raise TypeError(
                "TAAC endpoint direct IXIA connections must use the TAAC schema"
            )
        ixia_ports = list(patch.ixia_ports)
        direct_ixia_connections = list(patch.direct_ixia_connections)
    return taac_types.Endpoint(
        name=base.name,
        direct_ixia_connections=direct_ixia_connections,
        ixia_needed=base.ixia_needed,
        ixia_ports=ixia_ports,
        dut=base.dut,
        mac_address=base.mac_address,
        exclude_ixia_ports=base.exclude_ixia_ports,
    )


__all__ = ("TaacEndpointComposer",)
