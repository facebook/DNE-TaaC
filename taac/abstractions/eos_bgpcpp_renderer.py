# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

from __future__ import annotations

import typing as t
from dataclasses import dataclass

from taac.abstractions.compilation.dut import (
    DutEndpointBaseFragment,
    DutEndpointBaseRenderResult,
    DutHostOsFragment,
    DutHostOsRenderResult,
)
from taac.abstractions.compilation.model import (
    DutPlan,
    EndpointPlan,
)
from taac.test_as_a_config import types as taac_types


class UnsupportedEosBgpCppHostOsRenderingError(ValueError):
    pass


class UnsupportedEosBgpCppEndpointBaseRenderingError(ValueError):
    pass


@dataclass(frozen=True)
class EosBgpCppHostOsRenderer:
    """Lowers EOS/BGP++ host-OS metadata in shadow mode."""

    def render(
        self,
        plan: DutPlan,
    ) -> DutHostOsRenderResult[taac_types.DeviceOsType]:
        endpoint, physical_identifier = _required_eos_dut_endpoint(
            plan,
            subject="host-OS",
            error_type=UnsupportedEosBgpCppHostOsRenderingError,
        )

        result = DutHostOsRenderResult(
            owned_endpoint_ids=(endpoint.resource_id,),
            fragments=(
                DutHostOsFragment(
                    endpoint_id=endpoint.resource_id,
                    physical_identifier=physical_identifier,
                    os_type=taac_types.DeviceOsType.ARISTA_FBOSS,
                ),
            ),
        )
        result.validate(plan)
        return result


@dataclass(frozen=True)
class EosBgpCppEndpointBaseRenderer:
    """Lowers EOS-owned endpoint fields without IXIA wiring."""

    def render(
        self,
        plan: DutPlan,
    ) -> DutEndpointBaseRenderResult[taac_types.Endpoint]:
        endpoint, physical_identifier = _required_eos_dut_endpoint(
            plan,
            subject="endpoint-base",
            error_type=UnsupportedEosBgpCppEndpointBaseRenderingError,
        )
        result = DutEndpointBaseRenderResult(
            owned_endpoint_ids=(endpoint.resource_id,),
            fragments=(
                DutEndpointBaseFragment(
                    endpoint_id=endpoint.resource_id,
                    physical_identifier=physical_identifier,
                    endpoint=taac_types.Endpoint(
                        name=physical_identifier,
                        dut=True,
                    ),
                ),
            ),
        )
        result.validate(plan)
        return result


TUnsupportedRenderingError = t.TypeVar(
    "TUnsupportedRenderingError",
    bound=ValueError,
)


def _required_eos_dut_endpoint(
    plan: DutPlan,
    *,
    subject: str,
    error_type: type[TUnsupportedRenderingError],
) -> tuple[EndpointPlan, str]:
    endpoints = tuple(endpoint for endpoint in plan.endpoints if endpoint.is_dut)
    if len(endpoints) != 1:
        raise error_type(
            f"EOS/BGP++ {subject} rendering requires exactly one DUT endpoint; "
            f"found {len(endpoints)}"
        )
    endpoint = endpoints[0]
    if endpoint.backend != "eos":
        raise error_type(
            f"DUT endpoint {endpoint.resource_id} has unsupported backend "
            f"{endpoint.backend!r}"
        )
    physical_identifier = endpoint.physical_identifier
    if not physical_identifier:
        raise error_type(
            f"DUT endpoint {endpoint.resource_id} has no physical identifier"
        )
    return endpoint, physical_identifier


__all__ = (
    "EosBgpCppEndpointBaseRenderer",
    "EosBgpCppHostOsRenderer",
    "UnsupportedEosBgpCppEndpointBaseRenderingError",
    "UnsupportedEosBgpCppHostOsRenderingError",
)
