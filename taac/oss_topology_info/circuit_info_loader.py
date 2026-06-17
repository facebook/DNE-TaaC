# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""
Circuit info loader for OSS topology lookups.

This module mirrors Skynet circuit lookup functionality using CSV-based data
sources so that TAAC can operate without Meta-internal dependencies.
"""

from __future__ import annotations

import csv
import os
import typing as t
from dataclasses import dataclass

from taac.utils.oss_taac_lib_utils import memoize_forever

# Default path to circuit info CSV (relative to this module)
DEFAULT_CIRCUIT_INFO_PATH = os.path.join(
    os.path.dirname(__file__),
    "circuit_info.csv",
)

# Environment variable override for circuit info path
CIRCUIT_INFO_PATH_ENV = "TAAC_CIRCUIT_INFO_PATH"


@dataclass(frozen=True)
class DesiredPlatformRecord:
    os_type_name: t.Optional[str]


@dataclass(frozen=True)
class DeviceRecord:
    name: str
    desired_platform: DesiredPlatformRecord


@dataclass(frozen=True)
class AggregatedInterfaceRecord:
    name: str


@dataclass(frozen=True)
class EndpointRecord:
    name: str
    device: DeviceRecord
    aggregated_interface: t.Optional[AggregatedInterfaceRecord]


@dataclass(frozen=True)
class DesiredCircuitRecord:
    a_endpoint: EndpointRecord
    z_endpoint: EndpointRecord
    status: t.Optional[str]
    role_name: t.Optional[str]


def _build_device(hostname: str, platform: t.Optional[str]) -> DeviceRecord:
    return DeviceRecord(
        name=hostname,
        desired_platform=DesiredPlatformRecord(os_type_name=platform),
    )


def _build_endpoint(
    hostname: str,
    interface: str,
    platform: t.Optional[str],
    aggregated_interface: t.Optional[str],
) -> EndpointRecord:
    aggregated = (
        AggregatedInterfaceRecord(name=aggregated_interface)
        if aggregated_interface
        else None
    )
    return EndpointRecord(
        name=interface,
        device=_build_device(hostname, platform),
        aggregated_interface=aggregated,
    )


@memoize_forever
def load_circuit_info(
    csv_path: t.Optional[str] = None,
) -> t.Tuple[t.List[DesiredCircuitRecord], t.Dict[str, t.List[DesiredCircuitRecord]]]:
    """
    Load circuit information from CSV file.

    The CSV file should have the format:
    hostname,local_interface,local_platform,local_parent_interface,
    neighbor_hostname,neighbor_interface,neighbor_platform,neighbor_parent_interface,
    status,role

    Lines starting with # are treated as comments and skipped.

    Args:
        csv_path: Optional override for CSV path. Defaults to environment variable
                  TAAC_CIRCUIT_INFO_PATH or the bundled circuit_info.csv.

    Returns:
        Tuple of:
          - List of DesiredCircuitRecord entries representing all circuits
          - Mapping from normalized hostname to the subset of circuits where the
            hostname participates as either endpoint
    """
    if csv_path is None:
        csv_path = os.environ.get(CIRCUIT_INFO_PATH_ENV, DEFAULT_CIRCUIT_INFO_PATH)

    all_circuits: t.List[DesiredCircuitRecord] = []
    host_to_circuits: t.Dict[str, t.List[DesiredCircuitRecord]] = {}

    if not os.path.exists(csv_path):
        return all_circuits, host_to_circuits

    with open(csv_path, "r") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row or row[0].startswith("#"):
                continue

            # Ensure row has at least hostname and neighbor hostname fields
            if len(row) < 10:
                # Pad missing columns with empty strings to simplify unpacking
                row = list(row) + [""] * (10 - len(row))

            (
                hostname,
                local_interface,
                local_platform,
                local_parent_interface,
                neighbor_hostname,
                neighbor_interface,
                neighbor_platform,
                neighbor_parent_interface,
                status,
                role_name,
            ) = (value.strip() for value in row[:10])

            if (
                not hostname
                or not local_interface
                or not neighbor_hostname
                or not neighbor_interface
            ):
                continue

            a_endpoint = _build_endpoint(
                hostname=hostname,
                interface=local_interface,
                platform=local_platform or None,
                aggregated_interface=local_parent_interface or None,
            )
            z_endpoint = _build_endpoint(
                hostname=neighbor_hostname,
                interface=neighbor_interface,
                platform=neighbor_platform or None,
                aggregated_interface=neighbor_parent_interface or None,
            )

            circuit = DesiredCircuitRecord(
                a_endpoint=a_endpoint,
                z_endpoint=z_endpoint,
                status=status or None,
                role_name=role_name or None,
            )
            all_circuits.append(circuit)

            for device_name in (hostname, neighbor_hostname):
                normalized = device_name.strip().lower()
                if not normalized:
                    continue
                host_to_circuits.setdefault(normalized, []).append(circuit)

    return all_circuits, host_to_circuits


def get_circuits_for_hostname_oss(
    hostname: str,
    ignore_ckt_status: bool = False,
) -> t.List[DesiredCircuitRecord]:
    """Retrieve circuit records for a given hostname from CSV data."""

    _, host_to_circuits = load_circuit_info()
    normalized = hostname.strip().lower()
    circuits = host_to_circuits.get(normalized, [])

    if ignore_ckt_status:
        return list(circuits)

    filtered: t.List[DesiredCircuitRecord] = []
    for circuit in circuits:
        if circuit.status is None or circuit.status == "3":
            filtered.append(circuit)
    return filtered
