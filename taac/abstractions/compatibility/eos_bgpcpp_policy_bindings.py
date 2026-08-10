# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

from __future__ import annotations

from dataclasses import dataclass

from taac.abstractions.compilation.model import (
    AddressFamily,
    PolicyDirection,
    RolePolicyKey,
)
from taac.abstractions.routing_semantics import (
    NetworkRole,
    PeerRelationship,
)


EBB_BGPCPP_CONFIGERATOR_PROFILE = "taac/ebb_ci_cd_configs/ebb_full_scale_bgpcpp_config"


@dataclass(frozen=True)
class EosBgpCppPolicyBinding:
    configerator_profile: str
    peer_group: str
    direction: PolicyDirection
    route_map: str

    def __post_init__(self) -> None:
        if not self.configerator_profile:
            raise ValueError("Configerator profile must be nonempty")
        if not self.peer_group:
            raise ValueError("BGP++ peer group must be nonempty")
        if not isinstance(self.direction, PolicyDirection):
            raise TypeError("policy direction must be a PolicyDirection")
        if not self.route_map:
            raise ValueError("BGP++ route map must be nonempty")


class UnsupportedEosBgpCppPolicyBindingError(ValueError):
    pass


@dataclass(frozen=True)
class _PolicyBindingRule:
    local_role: NetworkRole
    relationship: PeerRelationship
    afi: AddressFamily
    peer_group: str
    import_route_map: str
    export_route_map: str

    def resolve(self, direction: PolicyDirection) -> EosBgpCppPolicyBinding:
        if direction is PolicyDirection.IMPORT:
            route_map = self.import_route_map
        elif direction is PolicyDirection.EXPORT:
            route_map = self.export_route_map
        else:
            raise UnsupportedEosBgpCppPolicyBindingError(
                f"EOS/BGP++ does not support policy direction {direction!r}"
            )
        return EosBgpCppPolicyBinding(
            configerator_profile=EBB_BGPCPP_CONFIGERATOR_PROFILE,
            peer_group=self.peer_group,
            direction=direction,
            route_map=route_map,
        )


_POLICY_BINDING_RULES = (
    _PolicyBindingRule(
        local_role=NetworkRole.EB,
        relationship=PeerRelationship.EXTERNAL,
        afi=AddressFamily.IPV4,
        peer_group="EB-FA-V4",
        import_route_map="EB-FA-IN",
        export_route_map="EB-FA-OUT",
    ),
    _PolicyBindingRule(
        local_role=NetworkRole.EB,
        relationship=PeerRelationship.EXTERNAL,
        afi=AddressFamily.IPV6,
        peer_group="EB-FA-V6",
        import_route_map="EB-FA-IN",
        export_route_map="EB-FA-OUT",
    ),
    _PolicyBindingRule(
        local_role=NetworkRole.EB,
        relationship=PeerRelationship.INTERNAL,
        afi=AddressFamily.IPV4,
        peer_group="EB-EB-V4",
        import_route_map="EB-EB-IN",
        export_route_map="EB-EB-OUT",
    ),
    _PolicyBindingRule(
        local_role=NetworkRole.EB,
        relationship=PeerRelationship.INTERNAL,
        afi=AddressFamily.IPV6,
        peer_group="EB-EB-V6",
        import_route_map="EB-EB-IN",
        export_route_map="EB-EB-OUT",
    ),
    _PolicyBindingRule(
        local_role=NetworkRole.EB,
        relationship=PeerRelationship.MONITOR,
        afi=AddressFamily.IPV6,
        peer_group="BGP-MON",
        import_route_map="PROPAGATE_NOTHING_IN",
        export_route_map="PROPAGATE_EVERYTHING_OUT",
    ),
)


def resolve_eos_bgpcpp_policy_binding(
    key: RolePolicyKey,
) -> EosBgpCppPolicyBinding:
    _validate_role_policy_key(key)
    if (
        key.local_role is NetworkRole.EB
        and key.relationship is PeerRelationship.MONITOR
        and key.afi is AddressFamily.IPV4
    ):
        raise UnsupportedEosBgpCppPolicyBindingError(
            "EOS/BGP++ EB monitor policy does not support IPv4"
        )

    for rule in _POLICY_BINDING_RULES:
        if (
            key.local_role is rule.local_role
            and key.relationship is rule.relationship
            and key.afi is rule.afi
        ):
            return rule.resolve(key.direction)

    raise UnsupportedEosBgpCppPolicyBindingError(
        "EOS/BGP++ has no policy binding for "
        f"role={key.local_role.value}, "
        f"relationship={key.relationship.value}, afi={key.afi.value}, "
        f"direction={key.direction.value}"
    )


def _validate_role_policy_key(key: RolePolicyKey) -> None:
    if not isinstance(key, RolePolicyKey):
        raise TypeError("policy binding key must be a RolePolicyKey")
    if not isinstance(key.local_role, NetworkRole):
        raise TypeError("RolePolicyKey.local_role must be a NetworkRole")
    if not isinstance(key.relationship, PeerRelationship):
        raise TypeError("RolePolicyKey.relationship must be a PeerRelationship")
    if not isinstance(key.afi, AddressFamily):
        raise TypeError("RolePolicyKey.afi must be an AddressFamily")
    if not isinstance(key.direction, PolicyDirection):
        raise TypeError("RolePolicyKey.direction must be a PolicyDirection")


__all__ = (
    "EBB_BGPCPP_CONFIGERATOR_PROFILE",
    "EosBgpCppPolicyBinding",
    "UnsupportedEosBgpCppPolicyBindingError",
    "resolve_eos_bgpcpp_policy_binding",
)
