# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

from __future__ import annotations

from dataclasses import dataclass

from taac.abstractions.compilation.basic_port_composition import (
    BasicPortCompositionFragment,
    BasicPortCompositionRequest,
    BasicPortCompositionResult,
    BasicPortDeviceGroupProvenance,
)
from taac.abstractions.compilation.model import IxiaPortPlan
from taac.abstractions.compilation.traffic_generator import (
    TrafficGeneratorPortBaseFragment,
    TrafficGeneratorPortDeviceGroupFragment,
)
from taac.test_as_a_config import types as taac_types


@dataclass(frozen=True)
class TaacBasicPortComposer:
    """Composes shared IXIA-owned BasicPortConfig fields by resource ID."""

    def compose(
        self,
        request: BasicPortCompositionRequest[object, object],
    ) -> BasicPortCompositionResult[taac_types.BasicPortConfig]:
        bases_by_port_id = {
            fragment.port_id: fragment for fragment in request.port_bases.fragments
        }
        groups_by_port_id = {
            fragment.port_id: fragment
            for fragment in request.port_device_groups.fragments
        }
        fragments = tuple(
            _compose_port(
                request,
                port,
                bases_by_port_id[port.resource_id],
                groups_by_port_id[port.resource_id],
            )
            for port in request.active_ports()
        )
        result: BasicPortCompositionResult[taac_types.BasicPortConfig] = (
            BasicPortCompositionResult(fragments=fragments)
        )
        result.validate(request)
        return result


def _compose_port(
    request: BasicPortCompositionRequest[object, object],
    port: IxiaPortPlan,
    base_fragment: TrafficGeneratorPortBaseFragment[object],
    body_fragment: TrafficGeneratorPortDeviceGroupFragment[object],
) -> BasicPortCompositionFragment[taac_types.BasicPortConfig]:
    base = base_fragment.basic_port_config
    if not isinstance(base, taac_types.BasicPortConfig):
        raise TypeError(f"basic-port base {port.resource_id} must use the TAAC schema")
    if base.endpoint != base_fragment.physical_endpoint:
        raise ValueError(f"basic-port base {port.resource_id} endpoint mismatch")
    if base.l1_config is not None or base.device_group_configs is not None:
        raise ValueError(f"basic-port base {port.resource_id} overlaps owned fields")

    configs = []
    provenance = []
    for group in body_fragment.device_groups:
        config = group.device_group_config
        if not isinstance(config, taac_types.DeviceGroupConfig):
            raise TypeError(
                f"device-group body {group.device_group_id} must use the TAAC schema"
            )
        configs.append(config)
        provenance.append(
            BasicPortDeviceGroupProvenance(
                device_group_id=group.device_group_id,
                session_id=group.session_id,
                advertisement_ids=group.advertisement_ids,
            )
        )
    return BasicPortCompositionFragment(
        port_id=port.resource_id,
        dut_endpoint_id=base_fragment.dut_endpoint_id,
        physical_endpoint=base_fragment.physical_endpoint,
        device_groups=tuple(provenance),
        basic_port_config=taac_types.BasicPortConfig(
            endpoint=base.endpoint,
            device_group_configs=configs,
        ),
    )


__all__ = ("TaacBasicPortComposer",)
