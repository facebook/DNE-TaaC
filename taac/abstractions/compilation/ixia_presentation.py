# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum

from taac.abstractions.compilation.legacy_ixia_identity import (
    LegacyIxiaIdentitySidecar,
)
from taac.abstractions.compilation.model import (
    IxiaAdvertisementPlan,
    IxiaBgpSessionPlan,
    IxiaDeviceGroupPlan,
    IxiaPlan,
    IxiaPortPlan,
    ResourceId,
    ResourceKind,
)
from taac.abstractions.ixia_semantics import (
    IxiaEndpointPortLabelStyle,
)


class IxiaPresentationError(ValueError):
    pass


class IxiaPresentationKind(str, Enum):
    DEVICE_GROUP = "device_group"
    BGP_SESSION = "bgp_session"
    ADVERTISEMENT = "advertisement"


@dataclass(frozen=True)
class IxiaPortPresentation:
    resource_id: ResourceId
    endpoint_ixia_port_label: str

    def __post_init__(self) -> None:
        if self.resource_id.kind is not ResourceKind.IXIA_PORT:
            raise IxiaPresentationError(
                f"IXIA port presentation cannot reference {self.resource_id.kind.value}"
            )
        if not self.endpoint_ixia_port_label:
            raise IxiaPresentationError("IXIA endpoint port label is empty")


@dataclass(frozen=True)
class IxiaDeviceGroupPresentation:
    resource_id: ResourceId
    device_group_name: str | None
    tag_name: str | None
    device_group_index: int

    def __post_init__(self) -> None:
        names = tuple(
            name for name in (self.device_group_name, self.tag_name) if name is not None
        )
        if len(names) != 1 or not names[0]:
            raise IxiaPresentationError(
                "IXIA device-group presentation requires exactly one name"
            )
        if self.device_group_index < 0:
            raise IxiaPresentationError(
                "IXIA device-group presentation index must be non-negative"
            )


@dataclass(frozen=True)
class IxiaSessionPresentation:
    resource_id: ResourceId
    bgp_peer_name: str

    def __post_init__(self) -> None:
        if not self.bgp_peer_name:
            raise IxiaPresentationError("IXIA session presentation name is empty")


@dataclass(frozen=True)
class IxiaAdvertisementPresentation:
    resource_id: ResourceId
    prefix_name: str

    def __post_init__(self) -> None:
        if not self.prefix_name:
            raise IxiaPresentationError("IXIA advertisement presentation name is empty")


def resolve_ixia_port_presentation(
    overrides: LegacyIxiaIdentitySidecar,
    port: IxiaPortPlan,
) -> IxiaPortPresentation:
    override = overrides.port_identity(port.resource_id)
    return IxiaPortPresentation(
        resource_id=port.resource_id,
        endpoint_ixia_port_label=(
            override.endpoint_ixia_port_label
            if override is not None
            else default_ixia_port_label(port)
        ),
    )


def resolve_ixia_port_presentations(
    plan: IxiaPlan,
    overrides: LegacyIxiaIdentitySidecar,
) -> tuple[IxiaPortPresentation, ...]:
    presentations = tuple(
        resolve_ixia_port_presentation(overrides, port) for port in plan.ports
    )
    for endpoint_id in dict.fromkeys(port.dut_endpoint_id for port in plan.ports):
        labels = tuple(
            presentation.endpoint_ixia_port_label
            for port, presentation in zip(plan.ports, presentations, strict=True)
            if port.dut_endpoint_id == endpoint_id
        )
        if len(frozenset(labels)) != len(labels):
            raise IxiaPresentationError(
                f"IXIA endpoint {endpoint_id} has duplicate resolved port labels"
            )
    return presentations


def default_ixia_port_label(port: IxiaPortPlan) -> str:
    if port.endpoint_label_style is IxiaEndpointPortLabelStyle.DUT_INTERFACE:
        return port.dut_interface
    if port.endpoint_label_style is IxiaEndpointPortLabelStyle.CHASSIS_PORT:
        return f"{port.chassis_identifier}:{port.ixia_port}"
    raise IxiaPresentationError(
        f"IXIA port {port.resource_id} has unsupported endpoint label style"
    )


def resolve_ixia_device_group_presentation(
    plan: IxiaPlan,
    overrides: LegacyIxiaIdentitySidecar,
    group: IxiaDeviceGroupPlan,
) -> IxiaDeviceGroupPresentation:
    default_name = default_ixia_presentation_name(
        IxiaPresentationKind.DEVICE_GROUP,
        group.resource_id,
    )
    override = overrides.group_identity(group.resource_id)
    device_group_name = default_name
    tag_name = None
    device_group_index = _default_group_index(plan, group)
    if override is not None:
        if override.device_group_name is not None or override.tag_name is not None:
            device_group_name = override.device_group_name
            tag_name = override.tag_name
        if override.device_group_index is not None:
            device_group_index = override.device_group_index
    return IxiaDeviceGroupPresentation(
        resource_id=group.resource_id,
        device_group_name=device_group_name,
        tag_name=tag_name,
        device_group_index=device_group_index,
    )


def resolve_ixia_session_presentation(
    overrides: LegacyIxiaIdentitySidecar,
    session: IxiaBgpSessionPlan,
) -> IxiaSessionPresentation:
    override = overrides.session_identity(session.resource_id)
    return IxiaSessionPresentation(
        resource_id=session.resource_id,
        bgp_peer_name=(
            override.bgp_peer_name
            if override is not None
            else default_ixia_presentation_name(
                IxiaPresentationKind.BGP_SESSION,
                session.resource_id,
            )
        ),
    )


def resolve_ixia_advertisement_presentation(
    overrides: LegacyIxiaIdentitySidecar,
    advertisement: IxiaAdvertisementPlan,
) -> IxiaAdvertisementPresentation:
    override = overrides.advertisement_identity(advertisement.resource_id)
    return IxiaAdvertisementPresentation(
        resource_id=advertisement.resource_id,
        prefix_name=(
            override.prefix_name
            if override is not None
            else default_ixia_presentation_name(
                IxiaPresentationKind.ADVERTISEMENT,
                advertisement.resource_id,
            )
        ),
    )


def _default_group_index(plan: IxiaPlan, group: IxiaDeviceGroupPlan) -> int:
    port_groups = tuple(
        candidate
        for candidate in plan.device_groups
        if candidate.port_id == group.port_id
    )
    for index, candidate in enumerate(port_groups):
        if candidate.resource_id == group.resource_id:
            return index
    raise IxiaPresentationError(
        f"IXIA device group {group.resource_id} is not present in the plan"
    )


def default_ixia_presentation_name(
    kind: IxiaPresentationKind,
    resource_id: ResourceId,
) -> str:
    expected_kind, prefix = _PRESENTATION_KIND_FIELDS[kind]
    if resource_id.kind is not expected_kind:
        raise IxiaPresentationError(
            f"IXIA {kind.value} presentation cannot name {resource_id.kind.value}"
        )
    digest = hashlib.sha256()
    for component in (resource_id.kind.value, *resource_id.path):
        encoded = component.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, byteorder="big"))
        digest.update(encoded)
    return f"{prefix}_v1_{digest.hexdigest()[:32]}"


_PRESENTATION_KIND_FIELDS = {
    IxiaPresentationKind.DEVICE_GROUP: (ResourceKind.IXIA_DEVICE_GROUP, "ixdg"),
    IxiaPresentationKind.BGP_SESSION: (ResourceKind.IXIA_BGP_SESSION, "ixbgp"),
    IxiaPresentationKind.ADVERTISEMENT: (
        ResourceKind.IXIA_ADVERTISEMENT,
        "ixpfx",
    ),
}


__all__ = (
    "IxiaAdvertisementPresentation",
    "IxiaDeviceGroupPresentation",
    "IxiaPortPresentation",
    "IxiaPresentationError",
    "IxiaPresentationKind",
    "IxiaSessionPresentation",
    "default_ixia_presentation_name",
    "default_ixia_port_label",
    "resolve_ixia_advertisement_presentation",
    "resolve_ixia_device_group_presentation",
    "resolve_ixia_port_presentation",
    "resolve_ixia_port_presentations",
    "resolve_ixia_session_presentation",
)
