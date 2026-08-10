# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

from __future__ import annotations

from enum import Enum

from taac.abstractions.compilation.model import (
    AddressFamily,
    PolicyDirection,
    RolePolicyKey,
    RolePolicyPreset,
)
from taac.abstractions.routing_semantics import (
    NetworkRole,
    PeerRelationship,
)


class EbPolicySemantic(str, Enum):
    EXTERNAL_IMPORT = "eb_external_import"
    EXTERNAL_EXPORT = "eb_external_export"
    INTERNAL_IMPORT = "eb_internal_import"
    INTERNAL_EXPORT = "eb_internal_export"
    MONITOR_IMPORT = "eb_monitor_import"
    MONITOR_EXPORT = "eb_monitor_export"


class UnsupportedEbPolicyPresetError(ValueError):
    pass


def _semantic_for(
    relationship: PeerRelationship,
    direction: PolicyDirection,
) -> EbPolicySemantic:
    if relationship is PeerRelationship.EXTERNAL:
        return (
            EbPolicySemantic.EXTERNAL_IMPORT
            if direction is PolicyDirection.IMPORT
            else EbPolicySemantic.EXTERNAL_EXPORT
        )
    if relationship is PeerRelationship.INTERNAL:
        return (
            EbPolicySemantic.INTERNAL_IMPORT
            if direction is PolicyDirection.IMPORT
            else EbPolicySemantic.INTERNAL_EXPORT
        )
    if relationship is PeerRelationship.MONITOR:
        return (
            EbPolicySemantic.MONITOR_IMPORT
            if direction is PolicyDirection.IMPORT
            else EbPolicySemantic.MONITOR_EXPORT
        )
    raise UnsupportedEbPolicyPresetError(
        f"unsupported EB peer relationship {relationship!r}"
    )


EB_POLICY_PRESETS: tuple[RolePolicyPreset, ...] = tuple(
    RolePolicyPreset(
        key=RolePolicyKey(
            local_role=NetworkRole.EB,
            relationship=relationship,
            afi=afi,
            direction=direction,
        ),
        semantic_id=semantic.value,
    )
    for relationship in PeerRelationship
    for afi in AddressFamily
    for direction in PolicyDirection
    for semantic in (_semantic_for(relationship, direction),)
)


def resolve_eb_policy_preset(key: RolePolicyKey) -> RolePolicyPreset:
    if key.local_role is not NetworkRole.EB:
        raise UnsupportedEbPolicyPresetError(
            f"unsupported local network role {key.local_role.value!r}"
        )
    for preset in EB_POLICY_PRESETS:
        if preset.key == key:
            return preset
    raise UnsupportedEbPolicyPresetError(f"unsupported EB role-policy key {key!r}")
