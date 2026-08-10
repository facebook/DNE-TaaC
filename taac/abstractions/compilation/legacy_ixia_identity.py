# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from taac.abstractions.compilation.model import (
    ResourceId,
    ResourceKind,
)


class LegacyIxiaIdentityError(ValueError):
    pass


@dataclass(frozen=True)
class LegacyIxiaPortIdentity:
    resource_id: ResourceId
    endpoint_ixia_port_label: str

    def __post_init__(self) -> None:
        _require_kind(self.resource_id, ResourceKind.IXIA_PORT)
        if not self.endpoint_ixia_port_label:
            raise LegacyIxiaIdentityError(
                "legacy endpoint IXIA port label must be non-empty"
            )


@dataclass(frozen=True)
class LegacyIxiaGroupIdentity:
    resource_id: ResourceId
    device_group_name: str | None = None
    tag_name: str | None = None
    device_group_index: int | None = None

    def __post_init__(self) -> None:
        _require_kind(self.resource_id, ResourceKind.IXIA_DEVICE_GROUP)
        names = (self.device_group_name, self.tag_name)
        if any(name is not None and not name for name in names):
            raise LegacyIxiaIdentityError("legacy IXIA names must be non-empty")
        if self.device_group_index is not None and self.device_group_index < 0:
            raise LegacyIxiaIdentityError(
                "legacy IXIA device-group index must be non-negative"
            )
        if all(value is None for value in (*names, self.device_group_index)):
            raise LegacyIxiaIdentityError(
                f"legacy IXIA group identity for {self.resource_id} is empty"
            )


@dataclass(frozen=True)
class LegacyIxiaSessionIdentity:
    resource_id: ResourceId
    bgp_peer_name: str

    def __post_init__(self) -> None:
        _require_kind(self.resource_id, ResourceKind.IXIA_BGP_SESSION)
        if not self.bgp_peer_name:
            raise LegacyIxiaIdentityError("legacy IXIA BGP peer name must be non-empty")


@dataclass(frozen=True)
class LegacyIxiaAdvertisementIdentity:
    resource_id: ResourceId
    prefix_name: str

    def __post_init__(self) -> None:
        _require_kind(self.resource_id, ResourceKind.IXIA_ADVERTISEMENT)
        if not self.prefix_name:
            raise LegacyIxiaIdentityError(
                "legacy IXIA advertisement prefix name must be non-empty"
            )


@dataclass(frozen=True)
class LegacyIxiaIdentitySidecar:
    port_identities: tuple[LegacyIxiaPortIdentity, ...] = ()
    group_identities: tuple[LegacyIxiaGroupIdentity, ...] = ()
    session_identities: tuple[LegacyIxiaSessionIdentity, ...] = ()
    advertisement_identities: tuple[LegacyIxiaAdvertisementIdentity, ...] = ()

    def __post_init__(self) -> None:
        resource_ids = tuple(
            identity.resource_id
            for identity in (
                *self.port_identities,
                *self.group_identities,
                *self.session_identities,
                *self.advertisement_identities,
            )
        )
        duplicates = _duplicate_ids(resource_ids)
        if duplicates:
            rendered = ", ".join(str(resource_id) for resource_id in duplicates)
            raise LegacyIxiaIdentityError(
                f"legacy IXIA sidecar contains duplicate resource IDs: {rendered}"
            )

    def port_identity(
        self,
        resource_id: ResourceId,
    ) -> LegacyIxiaPortIdentity | None:
        return next(
            (
                identity
                for identity in self.port_identities
                if identity.resource_id == resource_id
            ),
            None,
        )

    def group_identity(
        self,
        resource_id: ResourceId,
    ) -> LegacyIxiaGroupIdentity | None:
        return next(
            (
                identity
                for identity in self.group_identities
                if identity.resource_id == resource_id
            ),
            None,
        )

    def advertisement_identity(
        self,
        resource_id: ResourceId,
    ) -> LegacyIxiaAdvertisementIdentity | None:
        return next(
            (
                identity
                for identity in self.advertisement_identities
                if identity.resource_id == resource_id
            ),
            None,
        )

    def session_identity(
        self,
        resource_id: ResourceId,
    ) -> LegacyIxiaSessionIdentity | None:
        return next(
            (
                identity
                for identity in self.session_identities
                if identity.resource_id == resource_id
            ),
            None,
        )

    def validate(self, known_resource_ids: Iterable[ResourceId]) -> None:
        known = frozenset(known_resource_ids)
        unknown = tuple(
            identity.resource_id
            for identity in (
                *self.port_identities,
                *self.group_identities,
                *self.session_identities,
                *self.advertisement_identities,
            )
            if identity.resource_id not in known
        )
        if unknown:
            rendered = ", ".join(str(resource_id) for resource_id in unknown)
            raise LegacyIxiaIdentityError(
                f"legacy IXIA sidecar references unknown resources: {rendered}"
            )


def _require_kind(resource_id: ResourceId, expected_kind: ResourceKind) -> None:
    if resource_id.kind is not expected_kind:
        raise LegacyIxiaIdentityError(
            f"legacy IXIA identity for {resource_id} must reference "
            f"{expected_kind.value!r}"
        )


def _duplicate_ids(resource_ids: tuple[ResourceId, ...]) -> tuple[ResourceId, ...]:
    seen: set[ResourceId] = set()
    duplicates: list[ResourceId] = []
    for resource_id in resource_ids:
        if resource_id in seen and resource_id not in duplicates:
            duplicates.append(resource_id)
        seen.add(resource_id)
    return tuple(duplicates)
