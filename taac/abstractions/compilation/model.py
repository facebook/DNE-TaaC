# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from taac.abstractions.routing_semantics import (
    NetworkRole,
    PeerRelationship,
)


class ResourceKind(str, Enum):
    ENDPOINT = "endpoint"
    LINK = "link"
    INTERFACE = "interface"
    BGP_ADJACENCY = "bgp_adjacency"
    POLICY = "policy"
    POLICY_BINDING = "policy_binding"
    ROUTING_CONFIG = "routing_config"
    COMPONENT = "component"
    IXIA_PORT = "ixia_port"
    IXIA_DEVICE_GROUP = "ixia_device_group"
    IXIA_BGP_SESSION = "ixia_bgp_session"
    IXIA_ADVERTISEMENT = "ixia_advertisement"
    OPENR = "openr"


class AddressFamily(str, Enum):
    IPV4 = "v4"
    IPV6 = "v6"


class EndpointSetupMode(str, Enum):
    FULL = "full"
    PRELOADED = "preloaded"
    SKIP = "skip"
    VERIFY_ONLY = "verify_only"


class DesiredPresence(str, Enum):
    PRESENT = "present"
    ABSENT = "absent"


class PolicyDirection(str, Enum):
    IMPORT = "import"
    EXPORT = "export"


@dataclass(frozen=True)
class RolePolicyKey:
    local_role: NetworkRole
    relationship: PeerRelationship
    afi: AddressFamily
    direction: PolicyDirection

    def __post_init__(self) -> None:
        if not isinstance(self.local_role, NetworkRole):
            raise TypeError("local role must be a NetworkRole")
        if not isinstance(self.relationship, PeerRelationship):
            raise TypeError("relationship must be a PeerRelationship")
        if not isinstance(self.afi, AddressFamily):
            raise TypeError("address family must be an AddressFamily")
        if not isinstance(self.direction, PolicyDirection):
            raise TypeError("policy direction must be a PolicyDirection")


@dataclass(frozen=True)
class RolePolicyPreset:
    key: RolePolicyKey
    semantic_id: str

    def __post_init__(self) -> None:
        if not self.semantic_id:
            raise ValueError("role-policy semantic ID must be nonempty")


class OpenRDesiredMode(str, Enum):
    NONE = "none"
    STANDALONE = "standalone"
    PEER = "peer"


@dataclass(frozen=True)
class ResourceId:
    """Logical identity; bound and compatibility identities are deliberately absent."""

    kind: ResourceKind
    path: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ResourceKind):
            raise TypeError("resource kind must be a ResourceKind")
        if not isinstance(self.path, tuple) or not self.path:
            raise ValueError("resource ID path must be a non-empty tuple")
        if any(not isinstance(segment, str) or not segment for segment in self.path):
            raise ValueError("resource ID path segments must be non-empty strings")

    def __str__(self) -> str:
        return f"{self.kind.value}:{'/'.join(self.path)}"


@dataclass(frozen=True)
class EndpointPlan:
    resource_id: ResourceId
    logical_name: str
    role: str
    kind: str
    backend: str
    physical_identifier: str | None = None
    setup_mode: EndpointSetupMode = EndpointSetupMode.FULL
    network_role: NetworkRole | None = None

    def __post_init__(self) -> None:
        _require_kind(self.resource_id, ResourceKind.ENDPOINT)


@dataclass(frozen=True)
class DutLinkPlan:
    resource_id: ResourceId
    a_endpoint_id: ResourceId
    z_endpoint_id: ResourceId
    afi: AddressFamily
    logical_port_role: str
    peer_count: int = 1
    parent_network: str | None = None

    def __post_init__(self) -> None:
        _require_kind(self.resource_id, ResourceKind.LINK)
        _require_kind(self.a_endpoint_id, ResourceKind.ENDPOINT)
        _require_kind(self.z_endpoint_id, ResourceKind.ENDPOINT)
        _require_positive(self.peer_count, "peer_count")


@dataclass(frozen=True)
class InterfacePlan:
    resource_id: ResourceId
    endpoint_id: ResourceId
    link_ids: tuple[ResourceId, ...]
    logical_port_role: str
    afi: AddressFamily
    addresses: tuple[str, ...] = ()
    bound_interface: str | None = None

    def __post_init__(self) -> None:
        _require_kind(self.resource_id, ResourceKind.INTERFACE)
        _require_kind(self.endpoint_id, ResourceKind.ENDPOINT)
        _require_kinds(self.link_ids, ResourceKind.LINK)


@dataclass(frozen=True)
class BgpAdjacencyPlan:
    resource_id: ResourceId
    link_id: ResourceId
    ordinal: int
    afi: AddressFamily
    local_address: str
    peer_address: str
    local_asn: int | None
    remote_asn: int | None
    desired_presence: DesiredPresence = DesiredPresence.PRESENT
    relationship: PeerRelationship | None = None

    def __post_init__(self) -> None:
        _require_kind(self.resource_id, ResourceKind.BGP_ADJACENCY)
        _require_kind(self.link_id, ResourceKind.LINK)
        _require_non_negative(self.ordinal, "ordinal")


@dataclass(frozen=True)
class PolicyPlan:
    resource_id: ResourceId
    logical_name: str
    preset: RolePolicyPreset | None = None

    def __post_init__(self) -> None:
        _require_kind(self.resource_id, ResourceKind.POLICY)


@dataclass(frozen=True)
class PolicyBinding:
    resource_id: ResourceId
    adjacency_id: ResourceId
    policy_id: ResourceId
    direction: PolicyDirection

    def __post_init__(self) -> None:
        _require_kind(self.resource_id, ResourceKind.POLICY_BINDING)
        _require_kind(self.adjacency_id, ResourceKind.BGP_ADJACENCY)
        _require_kind(self.policy_id, ResourceKind.POLICY)


@dataclass(frozen=True)
class RoutingConfigPlan:
    resource_id: ResourceId
    endpoint_id: ResourceId
    routing_driver: str
    required_features: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_kind(self.resource_id, ResourceKind.ROUTING_CONFIG)
        _require_kind(self.endpoint_id, ResourceKind.ENDPOINT)


@dataclass(frozen=True)
class ComponentPlan:
    resource_id: ResourceId
    endpoint_id: ResourceId
    role: str
    enabled: bool = True
    depends_on: tuple[ResourceId, ...] = ()

    def __post_init__(self) -> None:
        _require_kind(self.resource_id, ResourceKind.COMPONENT)
        _require_kind(self.endpoint_id, ResourceKind.ENDPOINT)
        _require_kinds(self.depends_on, ResourceKind.COMPONENT)


@dataclass(frozen=True)
class IxiaPortPlan:
    resource_id: ResourceId
    logical_role: str
    link_ids: tuple[ResourceId, ...]
    dut_interface: str
    ixia_port: str
    physical_inventory_index: int
    reuse_group: str | None = None

    def __post_init__(self) -> None:
        _require_kind(self.resource_id, ResourceKind.IXIA_PORT)
        _require_kinds(self.link_ids, ResourceKind.LINK)
        _require_non_negative(
            self.physical_inventory_index,
            "physical_inventory_index",
        )


@dataclass(frozen=True)
class IxiaDeviceGroupPlan:
    resource_id: ResourceId
    link_id: ResourceId
    port_id: ResourceId
    afi: AddressFamily
    peer_count: int
    local_asn: int | None
    remote_asn: int | None
    parent_network: str | None = None

    def __post_init__(self) -> None:
        _require_kind(self.resource_id, ResourceKind.IXIA_DEVICE_GROUP)
        _require_kind(self.link_id, ResourceKind.LINK)
        _require_kind(self.port_id, ResourceKind.IXIA_PORT)
        _require_positive(self.peer_count, "peer_count")


@dataclass(frozen=True)
class IxiaBgpSessionPlan:
    resource_id: ResourceId
    device_group_id: ResourceId
    adjacency_ids: tuple[ResourceId, ...]
    local_addresses: tuple[str, ...]
    peer_addresses: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_kind(self.resource_id, ResourceKind.IXIA_BGP_SESSION)
        _require_kind(self.device_group_id, ResourceKind.IXIA_DEVICE_GROUP)
        _require_kinds(self.adjacency_ids, ResourceKind.BGP_ADJACENCY)
        if len(self.local_addresses) != len(self.peer_addresses):
            raise ValueError("IXIA BGP local and peer address counts must match")


@dataclass(frozen=True)
class IxiaAdvertisementPlan:
    resource_id: ResourceId
    device_group_id: ResourceId
    logical_name: str
    prefix_set_name: str
    afi: AddressFamily
    route_count: int
    prefixes_per_peer: int
    prefix_length: int | None = None

    def __post_init__(self) -> None:
        _require_kind(self.resource_id, ResourceKind.IXIA_ADVERTISEMENT)
        _require_kind(self.device_group_id, ResourceKind.IXIA_DEVICE_GROUP)
        _require_non_negative(self.route_count, "route_count")
        _require_non_negative(self.prefixes_per_peer, "prefixes_per_peer")
        if self.prefix_length is not None:
            _require_non_negative(self.prefix_length, "prefix_length")


@dataclass(frozen=True)
class OpenRPlan:
    resource_id: ResourceId
    endpoint_id: ResourceId
    mode: OpenRDesiredMode
    link_id: ResourceId | None = None

    def __post_init__(self) -> None:
        _require_kind(self.resource_id, ResourceKind.OPENR)
        _require_kind(self.endpoint_id, ResourceKind.ENDPOINT)
        if self.link_id is not None:
            _require_kind(self.link_id, ResourceKind.LINK)


ResourcePlan = (
    EndpointPlan
    | DutLinkPlan
    | InterfacePlan
    | BgpAdjacencyPlan
    | PolicyPlan
    | PolicyBinding
    | RoutingConfigPlan
    | ComponentPlan
    | IxiaPortPlan
    | IxiaDeviceGroupPlan
    | IxiaBgpSessionPlan
    | IxiaAdvertisementPlan
    | OpenRPlan
)


@dataclass(frozen=True)
class DutPlan:
    endpoints: tuple[EndpointPlan, ...] = ()
    links: tuple[DutLinkPlan, ...] = ()
    interfaces: tuple[InterfacePlan, ...] = ()
    adjacencies: tuple[BgpAdjacencyPlan, ...] = ()
    policies: tuple[PolicyPlan, ...] = ()
    policy_bindings: tuple[PolicyBinding, ...] = ()
    routing_configs: tuple[RoutingConfigPlan, ...] = ()
    components: tuple[ComponentPlan, ...] = ()
    openr: tuple[OpenRPlan, ...] = ()

    def iter_resources(self) -> tuple[ResourcePlan, ...]:
        return (
            *self.endpoints,
            *self.links,
            *self.interfaces,
            *self.adjacencies,
            *self.policies,
            *self.policy_bindings,
            *self.routing_configs,
            *self.components,
            *self.openr,
        )


@dataclass(frozen=True)
class IxiaPlan:
    ports: tuple[IxiaPortPlan, ...] = ()
    device_groups: tuple[IxiaDeviceGroupPlan, ...] = ()
    bgp_sessions: tuple[IxiaBgpSessionPlan, ...] = ()
    advertisements: tuple[IxiaAdvertisementPlan, ...] = ()

    def iter_resources(self) -> tuple[ResourcePlan, ...]:
        return (
            *self.ports,
            *self.device_groups,
            *self.bgp_sessions,
            *self.advertisements,
        )


@dataclass(frozen=True)
class TopologyCompilationPlan:
    dut: DutPlan = field(default_factory=DutPlan)
    ixia: IxiaPlan = field(default_factory=IxiaPlan)

    def __post_init__(self) -> None:
        _validate_unique_resource_ids(self.iter_resources())

    def iter_resources(self) -> tuple[ResourcePlan, ...]:
        return (*self.dut.iter_resources(), *self.ixia.iter_resources())

    def iter_resource_ids(self) -> tuple[ResourceId, ...]:
        return tuple(resource.resource_id for resource in self.iter_resources())


def _require_kind(resource_id: ResourceId, expected_kind: ResourceKind) -> None:
    if resource_id.kind is not expected_kind:
        raise ValueError(
            f"resource {resource_id} must have kind {expected_kind.value!r}"
        )


def _require_kinds(
    resource_ids: tuple[ResourceId, ...],
    expected_kind: ResourceKind,
) -> None:
    for resource_id in resource_ids:
        _require_kind(resource_id, expected_kind)


def _require_non_negative(value: int, field_name: str) -> None:
    if value < 0:
        raise ValueError(f"{field_name} must be non-negative")


def _require_positive(value: int, field_name: str) -> None:
    if value <= 0:
        raise ValueError(f"{field_name} must be positive")


def _validate_unique_resource_ids(resources: tuple[ResourcePlan, ...]) -> None:
    seen: set[ResourceId] = set()
    duplicates: list[ResourceId] = []
    for resource in resources:
        resource_id = resource.resource_id
        if resource_id in seen and resource_id not in duplicates:
            duplicates.append(resource_id)
        seen.add(resource_id)
    if duplicates:
        rendered = ", ".join(str(resource_id) for resource_id in duplicates)
        raise ValueError(f"duplicate compilation resource IDs: {rendered}")
