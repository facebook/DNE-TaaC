# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from taac.abstractions.ixia_semantics import IxiaBgpCapability
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


class IxiaPeerPrefixDistribution(str, Enum):
    SHARED = "shared"
    DISJOINT = "disjoint"


class IxiaNextHopMode(str, Enum):
    SELF = "self"
    FORMULAIC = "formulaic"
    EXPLICIT = "explicit"


class IxiaNextHopDistribution(str, Enum):
    SHARED = "shared"
    PER_PEER = "per_peer"
    PER_PREFIX = "per_prefix"
    PER_PEER_PREFIX = "per_peer_prefix"


class IxiaRouteAttributeDistribution(str, Enum):
    ROUND_ROBIN = "round_robin"


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


IxiaAttributeValue = str | int | float | bool | None


@dataclass(frozen=True)
class IxiaStandardCommunityPlan:
    asn: int
    value: int


@dataclass(frozen=True)
class IxiaExtendedCommunityPlan:
    kind: str
    administrator: int
    assigned_number: int

    def __post_init__(self) -> None:
        if not self.kind:
            raise ValueError("extended-community kind must be nonempty")


@dataclass(frozen=True)
class IxiaAsPathPlan:
    asns: tuple[int, ...]


@dataclass(frozen=True)
class IxiaRouteAttributePoolPlan:
    community_rows: tuple[tuple[IxiaStandardCommunityPlan, ...], ...] = ()
    extended_community_rows: tuple[tuple[IxiaExtendedCommunityPlan, ...], ...] = ()
    as_paths: tuple[IxiaAsPathPlan, ...] = ()
    distribution: IxiaRouteAttributeDistribution = (
        IxiaRouteAttributeDistribution.ROUND_ROBIN
    )

    def __post_init__(self) -> None:
        if not isinstance(self.distribution, IxiaRouteAttributeDistribution):
            raise TypeError(
                "route-attribute distribution must be an IxiaRouteAttributeDistribution"
            )


@dataclass(frozen=True)
class IxiaPrefixWindowPlan:
    source_start: str
    source_step: int
    source_count: int
    source_excluded_indices: tuple[int, ...]
    membership_start_index: int
    membership_prefix_count: int
    starting_prefix: str
    prefix_length: int
    prefixes_per_peer: int
    peer_distribution: IxiaPeerPrefixDistribution
    network_group_index: int

    def __post_init__(self) -> None:
        if not self.source_start or not self.starting_prefix:
            raise ValueError("IXIA prefix source and starting prefix must be nonempty")
        _require_positive(self.source_step, "source_step")
        _require_positive(self.source_count, "source_count")
        _require_non_negative(self.membership_start_index, "membership_start_index")
        _require_positive(self.membership_prefix_count, "membership_prefix_count")
        _require_non_negative(self.prefix_length, "prefix_length")
        _require_positive(self.prefixes_per_peer, "prefixes_per_peer")
        _require_non_negative(self.network_group_index, "network_group_index")
        if not isinstance(self.peer_distribution, IxiaPeerPrefixDistribution):
            raise TypeError("peer distribution must be an IxiaPeerPrefixDistribution")
        if (
            self.membership_start_index + self.membership_prefix_count
            > self.source_count
        ):
            raise ValueError("prefix membership extends beyond the retained source")
        excluded = self.source_excluded_indices
        if any(index < 0 for index in excluded) or any(
            left >= right for left, right in zip(excluded, excluded[1:])
        ):
            raise ValueError(
                "source excluded indices must be non-negative, unique, and sorted"
            )
        if excluded and excluded[-1] >= self.source_count + len(excluded):
            raise ValueError("source excluded index is outside the candidate span")


@dataclass(frozen=True)
class IxiaNextHopPlan:
    mode: IxiaNextHopMode
    distribution: IxiaNextHopDistribution | None = None
    formulaic_start: str | None = None
    formulaic_step: int | None = None
    explicit_addresses: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.mode, IxiaNextHopMode):
            raise TypeError("next-hop mode must be an IxiaNextHopMode")
        if self.mode is IxiaNextHopMode.SELF:
            if (
                self.distribution is not None
                or self.formulaic_start is not None
                or self.formulaic_step is not None
                or self.explicit_addresses
            ):
                raise ValueError("self next hop cannot carry a source or distribution")
            return
        if not isinstance(self.distribution, IxiaNextHopDistribution):
            raise ValueError("non-self next hop requires a distribution")
        if self.mode is IxiaNextHopMode.FORMULAIC:
            if not self.formulaic_start or self.formulaic_step is None:
                raise ValueError("formulaic next hop requires a start and step")
            _require_positive(self.formulaic_step, "formulaic_step")
            if self.explicit_addresses:
                raise ValueError("formulaic next hop cannot carry explicit addresses")
            return
        if self.formulaic_start is not None or self.formulaic_step is not None:
            raise ValueError("explicit next hop cannot carry a formulaic source")
        if not self.explicit_addresses:
            raise ValueError("explicit next hop requires at least one address")


@dataclass(frozen=True)
class EndpointPlan:
    resource_id: ResourceId
    logical_name: str
    role: str
    kind: str
    backend: str
    is_dut: bool
    physical_identifier: str | None = None
    setup_mode: EndpointSetupMode = EndpointSetupMode.FULL
    network_role: NetworkRole | None = None

    def __post_init__(self) -> None:
        _require_kind(self.resource_id, ResourceKind.ENDPOINT)
        if not isinstance(self.is_dut, bool):
            raise TypeError("endpoint DUT classification must be a bool")


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
    dut_endpoint_id: ResourceId
    traffic_endpoint_id: ResourceId
    dut_physical_identifier: str
    chassis_identifier: str
    dut_interface: str
    ixia_port: str
    physical_inventory_index: int
    reuse_group: str | None = None

    def __post_init__(self) -> None:
        _require_kind(self.resource_id, ResourceKind.IXIA_PORT)
        _require_kinds(self.link_ids, ResourceKind.LINK)
        _require_kind(self.dut_endpoint_id, ResourceKind.ENDPOINT)
        _require_kind(self.traffic_endpoint_id, ResourceKind.ENDPOINT)
        if not self.dut_physical_identifier or not self.chassis_identifier:
            raise ValueError("IXIA port endpoint identifiers must be nonempty")
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
    peer_start_index: int = 0

    def __post_init__(self) -> None:
        _require_kind(self.resource_id, ResourceKind.IXIA_DEVICE_GROUP)
        _require_kind(self.link_id, ResourceKind.LINK)
        _require_kind(self.port_id, ResourceKind.IXIA_PORT)
        _require_positive(self.peer_count, "peer_count")
        _require_non_negative(self.peer_start_index, "peer_start_index")


@dataclass(frozen=True)
class IxiaBgpSessionPlan:
    resource_id: ResourceId
    device_group_id: ResourceId
    adjacency_ids: tuple[ResourceId, ...]
    local_addresses: tuple[str, ...]
    peer_addresses: tuple[str, ...]
    peer_cidrs: tuple[str | None, ...]
    relationship: PeerRelationship
    capabilities: tuple[IxiaBgpCapability, ...]
    address_prefix_length: int
    address_step: int
    address_start_index: int
    enable_four_byte_local_as: bool
    hold_timer_s: int
    keepalive_timer_s: int
    enable_graceful_restart: bool

    def __post_init__(self) -> None:
        _require_kind(self.resource_id, ResourceKind.IXIA_BGP_SESSION)
        _require_kind(self.device_group_id, ResourceKind.IXIA_DEVICE_GROUP)
        _require_kinds(self.adjacency_ids, ResourceKind.BGP_ADJACENCY)
        counts = {
            len(self.adjacency_ids),
            len(self.local_addresses),
            len(self.peer_addresses),
            len(self.peer_cidrs),
        }
        if len(counts) != 1:
            raise ValueError(
                "IXIA BGP adjacency, address, and peer-CIDR counts must match"
            )
        if not isinstance(self.relationship, PeerRelationship):
            raise TypeError("IXIA BGP relationship must be a PeerRelationship")
        if not self.capabilities or any(
            not isinstance(capability, IxiaBgpCapability)
            for capability in self.capabilities
        ):
            raise ValueError("IXIA BGP sessions require typed capabilities")
        if len(frozenset(self.capabilities)) != len(self.capabilities):
            raise ValueError("IXIA BGP session capabilities must be unique")
        _require_non_negative(self.address_prefix_length, "address_prefix_length")
        _require_positive(self.address_step, "address_step")
        _require_non_negative(self.address_start_index, "address_start_index")
        if not isinstance(self.enable_four_byte_local_as, bool):
            raise TypeError("IXIA four-byte-local-AS intent must be a bool")
        _require_positive(self.hold_timer_s, "hold_timer_s")
        _require_positive(self.keepalive_timer_s, "keepalive_timer_s")
        if not isinstance(self.enable_graceful_restart, bool):
            raise TypeError("IXIA graceful-restart intent must be a bool")


@dataclass(frozen=True)
class IxiaAdvertisementPlan:
    resource_id: ResourceId
    device_group_id: ResourceId
    logical_name: str
    prefix_set_name: str
    afi: AddressFamily
    route_count: int
    prefix_window: IxiaPrefixWindowPlan
    next_hop: IxiaNextHopPlan
    attributes: tuple[tuple[str, IxiaAttributeValue], ...] = ()
    route_attributes: IxiaRouteAttributePoolPlan | None = None
    policy_communities: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_kind(self.resource_id, ResourceKind.IXIA_ADVERTISEMENT)
        _require_kind(self.device_group_id, ResourceKind.IXIA_DEVICE_GROUP)
        _require_non_negative(self.route_count, "route_count")
        if any(not name for name, _value in self.attributes):
            raise ValueError("IXIA advertisement attribute names must be nonempty")
        if any(not community for community in self.policy_communities):
            raise ValueError("IXIA policy communities must be nonempty")

    @property
    def prefixes_per_peer(self) -> int:
        return self.prefix_window.prefixes_per_peer

    @property
    def prefix_length(self) -> int:
        return self.prefix_window.prefix_length


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

    def __post_init__(self) -> None:
        _validate_unique_resource_ids(self.iter_resources())
        _validate_ixia_internal_references(self)

    def iter_resources(self) -> tuple[ResourcePlan, ...]:
        return (
            *self.ports,
            *self.device_groups,
            *self.bgp_sessions,
            *self.advertisements,
        )

    def iter_resource_ids(self) -> tuple[ResourceId, ...]:
        return tuple(resource.resource_id for resource in self.iter_resources())


@dataclass(frozen=True)
class TopologyCompilationPlan:
    dut: DutPlan = field(default_factory=DutPlan)
    ixia: IxiaPlan = field(default_factory=IxiaPlan)

    def __post_init__(self) -> None:
        _validate_unique_resource_ids(self.iter_resources())
        _validate_ixia_topology_references(self)

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


def _validate_ixia_internal_references(plan: IxiaPlan) -> None:
    ports = {port.resource_id: port for port in plan.ports}
    device_groups = {group.resource_id: group for group in plan.device_groups}
    _validate_ixia_device_group_internal_references(plan, ports)
    _validate_ixia_session_internal_references(plan, device_groups)
    _validate_ixia_advertisement_internal_references(plan, device_groups)


def _validate_ixia_device_group_internal_references(
    plan: IxiaPlan,
    ports: dict[ResourceId, IxiaPortPlan],
) -> None:
    for device_group in plan.device_groups:
        port = ports.get(device_group.port_id)
        if port is None:
            raise ValueError(
                f"IXIA device group {device_group.resource_id} references unknown "
                f"port {device_group.port_id}"
            )
        if device_group.link_id not in port.link_ids:
            raise ValueError(
                f"IXIA device group {device_group.resource_id} link "
                f"{device_group.link_id} is not owned by port {port.resource_id}"
            )


def _validate_ixia_session_internal_references(
    plan: IxiaPlan,
    device_groups: dict[ResourceId, IxiaDeviceGroupPlan],
) -> None:
    for session in plan.bgp_sessions:
        device_group = device_groups.get(session.device_group_id)
        if device_group is None:
            raise ValueError(
                f"IXIA BGP session {session.resource_id} references unknown "
                f"device group {session.device_group_id}"
            )
        if len(session.adjacency_ids) != device_group.peer_count:
            raise ValueError(
                f"IXIA BGP session {session.resource_id} has "
                f"{len(session.adjacency_ids)} peers but device group "
                f"{device_group.resource_id} declares {device_group.peer_count}"
            )
        max_prefix_length = 32 if device_group.afi is AddressFamily.IPV4 else 128
        if session.address_prefix_length > max_prefix_length:
            raise ValueError(
                f"IXIA BGP session {session.resource_id} address prefix length "
                f"exceeds {device_group.afi.value} width"
            )


def _validate_ixia_advertisement_internal_references(
    plan: IxiaPlan,
    device_groups: dict[ResourceId, IxiaDeviceGroupPlan],
) -> None:
    for advertisement in plan.advertisements:
        device_group = device_groups.get(advertisement.device_group_id)
        if device_group is None:
            raise ValueError(
                f"IXIA advertisement {advertisement.resource_id} references unknown "
                f"device group {advertisement.device_group_id}"
            )
        if advertisement.afi is not device_group.afi:
            raise ValueError(
                f"IXIA advertisement {advertisement.resource_id} address family "
                f"does not match device group {device_group.resource_id}"
            )
        expected_route_count = advertisement.prefixes_per_peer
        if (
            advertisement.prefix_window.peer_distribution
            is IxiaPeerPrefixDistribution.DISJOINT
        ):
            expected_route_count *= device_group.peer_count
        if advertisement.route_count != expected_route_count:
            raise ValueError(
                f"IXIA advertisement {advertisement.resource_id} route count "
                f"{advertisement.route_count} does not match allocation "
                f"{expected_route_count}"
            )
        if expected_route_count > advertisement.prefix_window.membership_prefix_count:
            raise ValueError(
                f"IXIA advertisement {advertisement.resource_id} allocation requires "
                f"{expected_route_count} prefixes but its membership contains "
                f"{advertisement.prefix_window.membership_prefix_count}"
            )


def _validate_ixia_topology_references(plan: TopologyCompilationPlan) -> None:
    endpoint_ids = frozenset(endpoint.resource_id for endpoint in plan.dut.endpoints)
    links = {link.resource_id: link for link in plan.dut.links}
    adjacencies = {
        adjacency.resource_id: adjacency for adjacency in plan.dut.adjacencies
    }
    ixia_device_groups = {
        device_group.resource_id: device_group
        for device_group in plan.ixia.device_groups
    }
    _validate_ixia_port_topology_references(plan, endpoint_ids, links)
    _validate_ixia_device_group_topology_references(plan, links)
    _validate_ixia_session_topology_references(
        plan,
        ixia_device_groups,
        adjacencies,
    )


def _validate_ixia_port_topology_references(
    plan: TopologyCompilationPlan,
    endpoint_ids: frozenset[ResourceId],
    links: dict[ResourceId, DutLinkPlan],
) -> None:
    for port in plan.ixia.ports:
        for endpoint_id in (port.dut_endpoint_id, port.traffic_endpoint_id):
            if endpoint_id not in endpoint_ids:
                raise ValueError(
                    f"IXIA port {port.resource_id} references unknown endpoint "
                    f"{endpoint_id}"
                )
        for link_id in port.link_ids:
            link = links.get(link_id)
            if link is None:
                raise ValueError(
                    f"IXIA port {port.resource_id} references unknown link {link_id}"
                )
            if frozenset((link.a_endpoint_id, link.z_endpoint_id)) != frozenset(
                (port.dut_endpoint_id, port.traffic_endpoint_id)
            ):
                raise ValueError(
                    f"IXIA port {port.resource_id} endpoints do not match link "
                    f"{link.resource_id}"
                )


def _validate_ixia_device_group_topology_references(
    plan: TopologyCompilationPlan,
    links: dict[ResourceId, DutLinkPlan],
) -> None:
    for device_group in plan.ixia.device_groups:
        link = links.get(device_group.link_id)
        if link is None:
            raise ValueError(
                f"IXIA device group {device_group.resource_id} references unknown "
                f"link {device_group.link_id}"
            )
        if device_group.afi is not link.afi:
            raise ValueError(
                f"IXIA device group {device_group.resource_id} address family "
                f"does not match link {link.resource_id}"
            )
        if device_group.peer_start_index + device_group.peer_count > link.peer_count:
            raise ValueError(
                f"IXIA device group {device_group.resource_id} peer window exceeds "
                f"link {link.resource_id} peer count {link.peer_count}"
            )


def _validate_ixia_session_topology_references(
    plan: TopologyCompilationPlan,
    device_groups: dict[ResourceId, IxiaDeviceGroupPlan],
    adjacencies: dict[ResourceId, BgpAdjacencyPlan],
) -> None:
    for session in plan.ixia.bgp_sessions:
        device_group = device_groups[session.device_group_id]
        expected_ordinals = range(
            device_group.peer_start_index,
            device_group.peer_start_index + device_group.peer_count,
        )
        for adjacency_id, local_address, peer_address, expected_ordinal in zip(
            session.adjacency_ids,
            session.local_addresses,
            session.peer_addresses,
            expected_ordinals,
            strict=True,
        ):
            adjacency = adjacencies.get(adjacency_id)
            if adjacency is None:
                raise ValueError(
                    f"IXIA BGP session {session.resource_id} references unknown "
                    f"adjacency {adjacency_id}"
                )
            _validate_ixia_session_peer(
                session,
                device_group,
                adjacency,
                local_address,
                peer_address,
                expected_ordinal,
            )


def _validate_ixia_session_peer(
    session: IxiaBgpSessionPlan,
    device_group: IxiaDeviceGroupPlan,
    adjacency: BgpAdjacencyPlan,
    local_address: str,
    peer_address: str,
    expected_ordinal: int,
) -> None:
    if (
        adjacency.link_id != device_group.link_id
        or adjacency.ordinal != expected_ordinal
        or adjacency.afi is not device_group.afi
    ):
        raise ValueError(
            f"IXIA BGP session {session.resource_id} adjacency "
            f"{adjacency.resource_id} does not match device group "
            f"{device_group.resource_id}"
        )
    if (local_address, peer_address) != (
        adjacency.peer_address,
        adjacency.local_address,
    ):
        raise ValueError(
            f"IXIA BGP session {session.resource_id} addresses do not mirror "
            f"adjacency {adjacency.resource_id}"
        )
    if session.relationship is not adjacency.relationship:
        raise ValueError(
            f"IXIA BGP session {session.resource_id} relationship does not match "
            f"adjacency {adjacency.resource_id}"
        )
    if (
        device_group.local_asn != adjacency.remote_asn
        or device_group.remote_asn != adjacency.local_asn
    ):
        raise ValueError(
            f"IXIA device group {device_group.resource_id} ASNs do not mirror "
            f"adjacency {adjacency.resource_id}"
        )
