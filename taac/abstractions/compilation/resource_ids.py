# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

from __future__ import annotations

from taac.abstractions.compilation.model import (
    AddressFamily,
    PolicyDirection,
    ResourceId,
    ResourceKind,
    RolePolicyKey,
)
from taac.abstractions.component_semantics import ComponentRole
from taac.abstractions.physical_interface_semantics import (
    PhysicalInterfaceGroupKind,
)
from taac.abstractions.topology.model import EndpointSpec


_TRAFFIC_ENDPOINT_ROLES = frozenset({"ixia", "traffic", "trafficgen"})


def is_dut_endpoint(endpoint: EndpointSpec) -> bool:
    return endpoint.role == "dut" or (
        endpoint.kind == "dut" and endpoint.role not in _TRAFFIC_ENDPOINT_ROLES
    )


def endpoint_resource_id(logical_name: str) -> ResourceId:
    return ResourceId(ResourceKind.ENDPOINT, (logical_name,))


def link_resource_id(device_group_name: str) -> ResourceId:
    return ResourceId(ResourceKind.LINK, (device_group_name,))


def interface_resource_id(
    endpoint_name: str,
    logical_port_role: str,
    afi: AddressFamily,
) -> ResourceId:
    return ResourceId(
        ResourceKind.INTERFACE,
        (endpoint_name, logical_port_role, afi.value),
    )


def physical_interface_resource_id(
    endpoint_id: ResourceId,
    group_kind: PhysicalInterfaceGroupKind,
    logical_key: str,
) -> ResourceId:
    if endpoint_id.kind is not ResourceKind.ENDPOINT:
        raise ValueError("physical interface endpoint ID must have endpoint kind")
    if not isinstance(group_kind, PhysicalInterfaceGroupKind):
        raise TypeError("physical interface group kind must be typed")
    if not isinstance(logical_key, str) or not logical_key:
        raise ValueError("physical interface logical key must be nonempty")
    return ResourceId(
        ResourceKind.PHYSICAL_INTERFACE,
        (*endpoint_id.path, group_kind.value, logical_key),
    )


def adjacency_resource_id(device_group_name: str, ordinal: int) -> ResourceId:
    return ResourceId(
        ResourceKind.BGP_ADJACENCY,
        (device_group_name, str(ordinal)),
    )


def policy_resource_id(logical_name: str) -> ResourceId:
    return ResourceId(ResourceKind.POLICY, (logical_name,))


def role_policy_resource_id(key: RolePolicyKey) -> ResourceId:
    return ResourceId(
        ResourceKind.POLICY,
        (
            "role",
            key.local_role.value,
            key.relationship.value,
            key.afi.value,
            key.direction.value,
        ),
    )


def policy_binding_resource_id(
    adjacency_id: ResourceId,
    direction: PolicyDirection,
) -> ResourceId:
    return ResourceId(
        ResourceKind.POLICY_BINDING,
        (*adjacency_id.path, direction.value),
    )


def routing_config_resource_id(endpoint_name: str) -> ResourceId:
    return ResourceId(ResourceKind.ROUTING_CONFIG, (endpoint_name,))


def component_resource_id(
    endpoint_id: ResourceId,
    role: ComponentRole,
) -> ResourceId:
    if endpoint_id.kind is not ResourceKind.ENDPOINT:
        raise ValueError("component endpoint ID must have endpoint kind")
    return ResourceId(ResourceKind.COMPONENT, (*endpoint_id.path, role.value))


def openr_resource_id(endpoint_name: str) -> ResourceId:
    return ResourceId(ResourceKind.OPENR, (endpoint_name,))


def ixia_port_resource_id(logical_role: str) -> ResourceId:
    return ResourceId(ResourceKind.IXIA_PORT, (logical_role,))


def ixia_device_group_resource_id(
    device_group_name: str,
    child_name: str | None = None,
) -> ResourceId:
    return ResourceId(
        ResourceKind.IXIA_DEVICE_GROUP,
        _ixia_instance_path(device_group_name, child_name),
    )


def ixia_session_resource_id(
    device_group_name: str,
    child_name: str | None = None,
) -> ResourceId:
    return ResourceId(
        ResourceKind.IXIA_BGP_SESSION,
        _ixia_instance_path(device_group_name, child_name),
    )


def ixia_advertisement_resource_id(
    device_group_name: str,
    logical_name: str,
    child_name: str | None = None,
) -> ResourceId:
    return ResourceId(
        ResourceKind.IXIA_ADVERTISEMENT,
        (*_ixia_instance_path(device_group_name, child_name), logical_name),
    )


def _ixia_instance_path(
    device_group_name: str,
    child_name: str | None,
) -> tuple[str, ...]:
    return (
        (device_group_name,) if child_name is None else (device_group_name, child_name)
    )


__all__ = (
    "adjacency_resource_id",
    "component_resource_id",
    "endpoint_resource_id",
    "interface_resource_id",
    "ixia_advertisement_resource_id",
    "ixia_device_group_resource_id",
    "ixia_port_resource_id",
    "ixia_session_resource_id",
    "is_dut_endpoint",
    "link_resource_id",
    "openr_resource_id",
    "physical_interface_resource_id",
    "policy_binding_resource_id",
    "policy_resource_id",
    "role_policy_resource_id",
    "routing_config_resource_id",
)
