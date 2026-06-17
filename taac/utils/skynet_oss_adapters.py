# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""Adapter utilities for mapping OSS CSV circuit data to Skynet-like objects."""

from __future__ import annotations

import typing as t
from types import SimpleNamespace

from taac.oss_topology_info.circuit_info_loader import (
    AggregatedInterfaceRecord,
    DesiredCircuitRecord,
    EndpointRecord,
)


def _build_device_namespace(endpoint: EndpointRecord) -> SimpleNamespace:
    desired_platform = SimpleNamespace(
        os_type_name=_coalesce(endpoint.device.desired_platform.os_type_name)
    )
    return SimpleNamespace(name=endpoint.device.name, desired_platform=desired_platform)


def _build_endpoint_namespace(endpoint: EndpointRecord) -> SimpleNamespace:
    aggregated_interface = (
        SimpleNamespace(name=endpoint.aggregated_interface.name)
        if endpoint.aggregated_interface and endpoint.aggregated_interface.name
        else None
    )
    return SimpleNamespace(
        name=endpoint.name,
        device=_build_device_namespace(endpoint),
        aggregated_interface=aggregated_interface,
    )


def convert_to_skynet_desired_circuit(
    circuit: DesiredCircuitRecord,
) -> SimpleNamespace:
    """
    Convert DesiredCircuitRecord into an object matching Skynet DesiredCircuit API.

    Returns a SimpleNamespace with attribute layout compatible with
    nettools.skynet.SkynetStructs.types.DesiredCircuit used internally.
    """

    return SimpleNamespace(
        a_endpoint=_build_endpoint_namespace(circuit.a_endpoint),
        z_endpoint=_build_endpoint_namespace(circuit.z_endpoint),
        status=_coalesce(circuit.status),
        role=SimpleNamespace(name=_coalesce(circuit.role_name))
        if circuit.role_name
        else None,
    )


def _coalesce(value: t.Optional[str]) -> t.Optional[str]:
    stripped = value.strip() if isinstance(value, str) else value
    return stripped or None
