# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

from __future__ import annotations

import typing as t
from dataclasses import dataclass

from taac.abstractions.compilation.dut import (
    DutHostOsFragment,
    DutHostOsRenderResult,
)
from taac.abstractions.compilation.model import DutPlan
from taac.test_as_a_config import types as taac_types


class UnsupportedEosBgpCppHostOsRenderingError(ValueError):
    pass


@dataclass(frozen=True)
class EosBgpCppHostOsRenderer:
    """Lowers EOS/BGP++ host-OS metadata in shadow mode."""

    def render(
        self,
        plan: DutPlan,
    ) -> DutHostOsRenderResult[taac_types.DeviceOsType]:
        endpoints = tuple(endpoint for endpoint in plan.endpoints if endpoint.is_dut)
        if len(endpoints) != 1:
            _unsupported(
                "EOS/BGP++ host-OS rendering requires exactly one DUT endpoint; "
                f"found {len(endpoints)}"
            )
        endpoint = endpoints[0]
        if endpoint.backend != "eos":
            _unsupported(
                f"DUT endpoint {endpoint.resource_id} has unsupported backend "
                f"{endpoint.backend!r}"
            )
        physical_identifier = endpoint.physical_identifier
        if not physical_identifier:
            _unsupported(
                f"DUT endpoint {endpoint.resource_id} has no physical identifier"
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


def _unsupported(message: str) -> t.NoReturn:
    raise UnsupportedEosBgpCppHostOsRenderingError(message)


__all__ = (
    "EosBgpCppHostOsRenderer",
    "UnsupportedEosBgpCppHostOsRenderingError",
)
