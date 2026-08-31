# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

from __future__ import annotations

import ipaddress
import typing as t
from dataclasses import dataclass, field, fields, MISSING
from enum import Enum

from taac.abstractions.config_artifact_semantics import (
    ConfigArtifactRef,
)
from taac.abstractions.ixia_semantics import (
    IxiaBgpCapability,
    IxiaEndpointPortLabelStyle,
)
from taac.abstractions.physical_interface_semantics import (
    PhysicalInterfaceProfile,
)
from taac.abstractions.routing_semantics import (
    NetworkRole,
    PeerRelationship,
)
from taac.abstractions.topology.address import AddressPlan
from taac.abstractions.topology.attributes import (
    RouteAttributePool,
)
from taac.abstractions.topology.prefix import (
    NextHopIntent,
    PrefixAllocation,
    PrefixMembership,
    PrefixSet,
)

AsnReference = int | str
_ROUTING_DEVICE_CONFIG_UNSET = object()


class CompiledTaacArtifactsLike(t.Protocol):
    """Structural compile result to keep topology primitives dependency-light.

    The concrete CompiledTaacArtifacts dataclass lives outside topology/model.py.
    Keeping this as a protocol lets BoundTopology.compile() expose the artifact
    shape without making primitive topology data import compiler/artifact code.
    """

    endpoints: list[t.Any]
    host_os_type_map: dict[str, t.Any]
    setup_tasks: list[t.Any]
    teardown_tasks: list[t.Any]
    basic_port_configs: list[t.Any]
    basic_traffic_item_configs: list[t.Any]


class ResolvedPrefixSetLike(t.Protocol):
    @property
    def spec(self) -> PrefixSet: ...

    @property
    def prefixes(self) -> t.Sequence[str]: ...


class ResolvedPrefixAdvertisementLike(t.Protocol):
    @property
    def spec(self) -> PrefixAdvertisement: ...

    @property
    def prefix_set(self) -> ResolvedPrefixSetLike: ...

    @property
    def paths_by_peer(self) -> t.Sequence[t.Sequence[t.Any]]: ...

    def path_at(self, peer_index: int, prefix_index: int) -> t.Any: ...


@dataclass(frozen=True)
class EndpointSpec:
    """Logical endpoint declaration; backend OS comes from physical inventory."""

    name: str
    role: str
    kind: str = "dut"
    required_os: str | None = None
    setup_mode: str = "full"


@dataclass(frozen=True)
class IxiaPortAssignment:
    logical_role: str
    reuse_group: str | None = None
    endpoint_label_style: IxiaEndpointPortLabelStyle = (
        IxiaEndpointPortLabelStyle.DUT_INTERFACE
    )


@dataclass(frozen=True)
class ResolvedIxiaPortAssignment:
    logical_role: str
    dut_interface: str
    ixia_port: str
    physical_inventory_index: int
    reuse_group: str | None
    physical_interface_profile: PhysicalInterfaceProfile
    endpoint_label_style: IxiaEndpointPortLabelStyle = (
        IxiaEndpointPortLabelStyle.DUT_INTERFACE
    )

    def __post_init__(self) -> None:
        if not isinstance(self.physical_interface_profile, PhysicalInterfaceProfile):
            raise TypeError("resolved physical interface profile must be typed")


@dataclass(frozen=True)
class DeviceGroupPartition:
    family: str
    ordinal: int
    start_index: int
    total_peer_count: int


@dataclass(frozen=True)
class IxiaDeviceGroupChild:
    name: str
    ordinal: int
    start_index: int
    peer_count: int
    legacy_ixia_device_group_name: str | None = None
    legacy_ixia_bgp_peer_name: str | None = None
    legacy_ixia_device_group_index: int | None = None
    legacy_ixia_prefix_pool_name: str | None = None


@dataclass(frozen=True)
class RouteSender:
    device_group: str
    prefix_advertisement: str


@dataclass(frozen=True)
class BgpPolicy:
    name: str
    route_maps: tuple[str, ...] = ()
    communities: tuple[str, ...] = ()
    prefix_lists: tuple[str, ...] = ()
    actions: tuple[str, ...] = ()
    attributes: tuple[tuple[str, t.Any], ...] = ()
    local_pref: int | None = None
    med: int | None = None
    as_path_prepend: str | None = None


def _validate_ixia_bgp_capabilities(
    capabilities: tuple[IxiaBgpCapability, ...] | None,
) -> None:
    if capabilities is None:
        return
    if not capabilities or any(
        not isinstance(capability, IxiaBgpCapability) for capability in capabilities
    ):
        raise ValueError("IXIA BGP capabilities must be nonempty typed capabilities")
    if len(frozenset(capabilities)) != len(capabilities):
        raise ValueError("IXIA BGP capabilities must be unique")


def _validate_ixia_bgp_integer(
    field_name: str,
    value: object,
    *,
    allow_none: bool,
    allow_zero: bool,
) -> None:
    if value is None and allow_none:
        return
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"IXIA BGP {field_name} must be an integer")
    if value < 0 or (not allow_zero and value == 0):
        qualifier = "non-negative" if allow_zero else "positive"
        raise ValueError(f"IXIA BGP {field_name} must be {qualifier}")


@dataclass(frozen=True)
class IxiaBgpSessionIntent:
    capabilities: tuple[IxiaBgpCapability, ...] | None = None
    address_prefix_length: int | None = None
    address_step: int | None = None
    address_start_index: int | None = None
    hold_timer_s: int = 30
    keepalive_timer_s: int = 10
    enable_graceful_restart: bool | None = None

    def __post_init__(self) -> None:
        _validate_ixia_bgp_capabilities(self.capabilities)
        _validate_ixia_bgp_integer(
            "address prefix length",
            self.address_prefix_length,
            allow_none=True,
            allow_zero=True,
        )
        _validate_ixia_bgp_integer(
            "hold_timer_s",
            self.hold_timer_s,
            allow_none=False,
            allow_zero=False,
        )
        _validate_ixia_bgp_integer(
            "keepalive_timer_s",
            self.keepalive_timer_s,
            allow_none=False,
            allow_zero=False,
        )
        _validate_ixia_bgp_integer(
            "address_step",
            self.address_step,
            allow_none=True,
            allow_zero=False,
        )
        _validate_ixia_bgp_integer(
            "address_start_index",
            self.address_start_index,
            allow_none=True,
            allow_zero=True,
        )
        if self.enable_graceful_restart is not None and not isinstance(
            self.enable_graceful_restart,
            bool,
        ):
            raise TypeError("IXIA BGP graceful-restart intent must be a bool")


@dataclass(frozen=True)
class BgpPeerGroup:
    name: str
    local_asn: AsnReference | None = None
    remote_asn: AsnReference | None = None
    policy: BgpPolicy | str | None = None
    hold_timer_s: int = 180
    keepalive_timer_s: int = 60
    connect_retry_timer_s: int = 120
    route_limit: int | str | None = None
    enable_graceful_restart: bool | None = None
    ixia_session: IxiaBgpSessionIntent = field(default_factory=IxiaBgpSessionIntent)


@dataclass(frozen=True)
class PrefixPool:
    name: str
    afi: str = "v6"
    route_count: int = 0
    route_file: str | None = None
    prefixes: tuple[str, ...] = ()
    prefix_length: int | None = None
    policy: BgpPolicy | str | None = None
    legacy_ixia_name: str | None = None
    attributes: tuple[tuple[str, t.Any], ...] = ()


@dataclass(frozen=True)
class PrefixAdvertisement:
    name: str
    prefix_set: str
    allocation: PrefixAllocation
    membership: PrefixMembership
    next_hop: NextHopIntent = field(default_factory=NextHopIntent)
    policy: BgpPolicy | str | None = None
    attributes: tuple[tuple[str, t.Any], ...] = ()
    route_attributes: RouteAttributePool | None = None
    legacy_ixia_name: str | None = None
    requires_route_mutation: bool = False


@dataclass(frozen=True)
class TrafficFlowSpec:
    name: str
    src_dg: str
    dst_dg: str | None = None
    dst_prefix_pool: str | None = None
    traffic_profile: str | None = None
    rate_percent: float | None = None
    rate_bps: int | None = None
    frame_size_bytes: int | None = None
    bidirectional: bool = False
    enabled: bool = True


class OpenRMode(str, Enum):
    NONE = "none"
    STANDALONE = "standalone"
    PEER = "peer"


class TaskCompatibilityProfile(str, Enum):
    BOUNDED_ECMP = "bounded_ecmp"
    EBB_FULL_SCALE_NO_BGPMON = "ebb_full_scale_no_bgpmon"
    EBB_FULL_SCALE_WITH_BGPMON = "ebb_full_scale_with_bgpmon"
    EGRESS_PEER_SCALE = "egress_peer_scale"
    IPV6_UPDATE_PACKING = "ipv6_update_packing"
    UG_ADD_PEER_DYNAMIC = "ug_add_peer_dynamic"
    UG_BACKPRESSURE = "ug_backpressure"
    UG_NEW_PEER_JOIN = "ug_new_peer_join"


class OpenRSetupSequence(str, Enum):
    NONE = "none"
    STANDALONE_SYNTHETIC_INJECTION = "standalone_synthetic_injection"
    PEER_DAEMON = "peer_daemon"
    # Compatibility for the pre-PEER-lowering inspection API.
    PEER_UNSUPPORTED = "peer_daemon"

    @classmethod
    def _missing_(cls, value: object) -> OpenRSetupSequence | None:
        if value == "peer_unsupported":
            return cls.PEER_DAEMON
        return None


@dataclass(frozen=True)
class ResolvedOpenRIntent:
    mode: OpenRMode
    setup_sequence: OpenRSetupSequence


@dataclass(frozen=True)
class OpenRStandaloneEndpoint:
    hostname: str
    member_interface: str
    ipv4_cidr: str
    ipv6_cidr: str
    link_local_cidr: str

    def __post_init__(self) -> None:
        if not self.hostname or not self.member_interface:
            raise ValueError(
                "OpenR endpoint hostname and member interface are required"
            )
        ipv4 = ipaddress.ip_interface(self.ipv4_cidr)
        ipv6 = ipaddress.ip_interface(self.ipv6_cidr)
        link_local = ipaddress.ip_interface(self.link_local_cidr)
        if ipv4.version != 4 or ipv4.network.prefixlen != 31:
            raise ValueError("OpenR endpoint IPv4 address must use a /31")
        if ipv6.version != 6 or ipv6.network.prefixlen != 127:
            raise ValueError("OpenR endpoint global IPv6 address must use a /127")
        if (
            link_local.version != 6
            or not link_local.ip.is_link_local
            or link_local.network.prefixlen != 64
        ):
            raise ValueError("OpenR endpoint link-local IPv6 address must use a /64")

    @property
    def ipv4(self) -> str:
        return str(ipaddress.ip_interface(self.ipv4_cidr).ip)

    @property
    def link_local(self) -> str:
        return str(ipaddress.ip_interface(self.link_local_cidr).ip)


@dataclass(frozen=True)
class OpenRStandaloneLink:
    port_channel_id: int
    owner: OpenRStandaloneEndpoint
    helper: OpenRStandaloneEndpoint
    speed: str = "400g-8"
    metric: int = 10

    def __post_init__(self) -> None:
        if self.port_channel_id <= 0:
            raise ValueError("OpenR port-channel ID must be positive")
        if self.owner.hostname == self.helper.hostname:
            raise ValueError("OpenR owner and helper must be different devices")
        owner_v4 = ipaddress.ip_interface(self.owner.ipv4_cidr)
        helper_v4 = ipaddress.ip_interface(self.helper.ipv4_cidr)
        owner_v6 = ipaddress.ip_interface(self.owner.ipv6_cidr)
        helper_v6 = ipaddress.ip_interface(self.helper.ipv6_cidr)
        owner_link_local = ipaddress.ip_interface(self.owner.link_local_cidr)
        helper_link_local = ipaddress.ip_interface(self.helper.link_local_cidr)
        for family, owner_address, helper_address in (
            ("IPv4", owner_v4, helper_v4),
            ("global IPv6", owner_v6, helper_v6),
            ("link-local IPv6", owner_link_local, helper_link_local),
        ):
            if owner_address.network != helper_address.network:
                raise ValueError(f"OpenR {family} endpoints must share a network")
            if owner_address.ip == helper_address.ip:
                raise ValueError(f"OpenR {family} endpoint addresses must differ")

    @property
    def interface_name(self) -> str:
        return f"Port-Channel{self.port_channel_id}"

    @property
    def short_interface_name(self) -> str:
        return f"po{self.port_channel_id}"

    def kv_link(self, endpoint: OpenRStandaloneEndpoint) -> dict[str, t.Any]:
        if endpoint not in (self.owner, self.helper):
            raise ValueError("OpenR KV endpoint must belong to the standalone link")
        return {
            "ipv4": endpoint.ipv4,
            "ipv6": endpoint.link_local,
            "ifName": self.short_interface_name,
            "weight": 0,
            "metric": self.metric,
        }


@dataclass(frozen=True, init=False)
class RoutingDeviceConfig:
    update_group_enable: bool = False
    enable_next_hop_tracking: bool = False
    enable_dynamic_policy_evaluation: bool = False
    openr_mode: OpenRMode = OpenRMode.NONE
    openr_configerator_path: str | None = None
    openr_standalone_link: OpenRStandaloneLink | None = None
    # Reachability Open/R must inject for the next hops the emulated peers
    # advertise. Empty means "use the renderer default", which is the ixia11
    # set. A topology whose next hops sit elsewhere has to say so here, or its
    # routes arrive, sit in the RIB unresolved, and never become installable.
    openr_injected_start_ipv4s: tuple[str, ...] = ()
    openr_injected_start_ipv6s: tuple[str, ...] = ()
    route_limit: int | str | None = None
    prefix_limit: int | str | None = None
    per_peer_max_route_limit: int | str | None = None
    bgp_hold_timer_s: int = 180
    bgp_keepalive_timer_s: int = 60
    bgp_connect_retry_timer_s: int = 120
    graceful_restart_timer_s: int | None = None
    bgpcpp_logging_config_override: str | None = None
    _taac_overridden_fields: tuple[str, ...] = field(
        default=(),
        repr=False,
        compare=False,
        hash=False,
    )

    def __init__(self, *args: t.Any, **kwargs: t.Any) -> None:
        init_fields = tuple(
            config_field for config_field in fields(type(self)) if config_field.init
        )
        if len(args) > len(init_fields):
            raise TypeError(
                f"{type(self).__name__}.__init__() takes "
                f"{len(init_fields) + 1} positional arguments but "
                f"{len(args) + 1} were given"
            )
        for config_field, value in zip(init_fields, args):
            if config_field.name in kwargs:
                raise TypeError(
                    f"{type(self).__name__}.__init__() got multiple values "
                    f"for argument {config_field.name!r}"
                )
            kwargs[config_field.name] = value

        overridden_fields_arg = kwargs.pop(
            "_taac_overridden_fields",
            _ROUTING_DEVICE_CONFIG_UNSET,
        )
        config_fields = tuple(
            config_field
            for config_field in init_fields
            if not config_field.name.startswith("_")
        )
        config_field_names = {config_field.name for config_field in config_fields}
        unexpected_field_names = set(kwargs) - config_field_names
        if unexpected_field_names:
            unexpected_field_name = sorted(unexpected_field_names)[0]
            raise TypeError(
                f"{type(self).__name__}.__init__() got an unexpected "
                f"keyword argument {unexpected_field_name!r}"
            )

        overridden_fields = list(
            ()
            if overridden_fields_arg is _ROUTING_DEVICE_CONFIG_UNSET
            else overridden_fields_arg or ()
        )
        should_record_overrides = (
            overridden_fields_arg is _ROUTING_DEVICE_CONFIG_UNSET
            or overridden_fields_arg is None
        )
        for config_field in config_fields:
            field_name = config_field.name
            if field_name in kwargs:
                value = kwargs[field_name]
                if should_record_overrides:
                    overridden_fields.append(field_name)
            elif config_field.default is not MISSING:
                value = config_field.default
            elif config_field.default_factory is not MISSING:
                value = config_field.default_factory()
            else:
                raise TypeError(f"{field_name!r} is missing a default value")
            object.__setattr__(self, field_name, value)
        object.__setattr__(
            self,
            "_taac_overridden_fields",
            tuple(overridden_fields),
        )


@dataclass(frozen=True)
class DeviceGroupSpec:
    name: str
    role: str
    afi: str = "v6"
    peer_count: int = 1
    a_endpoint: str = "dut0"
    z_endpoint: str = "ixia"
    address_plan: AddressPlan = field(default_factory=AddressPlan)
    peer_group: BgpPeerGroup | str | None = None
    prefix_pools: tuple[PrefixPool, ...] = ()
    prefix_advertisements: tuple[PrefixAdvertisement, ...] = ()
    traffic_flows: tuple[TrafficFlowSpec, ...] = ()
    routing_driver: str | None = None
    legacy_ixia_tag_name: str | None = None
    legacy_ixia_bgp_peer_name: str | None = None
    legacy_ixia_device_group_name: str | None = None
    routing_device_config: RoutingDeviceConfig | None = None
    port_assignment: IxiaPortAssignment | None = None
    partition: DeviceGroupPartition | None = None
    legacy_ixia_device_group_index: int | None = None
    route_attributes: RouteAttributePool | None = None
    ixia_children: tuple[IxiaDeviceGroupChild, ...] = ()
    # When True, the group's IXIA session + DUT interface IP are still provisioned,
    # but NO DUT BGP neighbor is generated for it (it is skipped in the bgpcpp peer
    # plan). For runtime-added peers -- e.g. spec 2.4.4 (addPeers) -- where the peer
    # must be ABSENT from the DUT config at baseline so the test can add it live.
    dut_neighbor_absent: bool = False
    peer_relationship: PeerRelationship | None = None


@dataclass(frozen=True)
class LogicalTopology:
    name: str
    endpoints: tuple[EndpointSpec, ...] = ()
    device_groups: tuple[DeviceGroupSpec, ...] = ()
    device_config: RoutingDeviceConfig = field(default_factory=RoutingDeviceConfig)
    peer_groups: tuple[BgpPeerGroup, ...] = ()
    policies: tuple[BgpPolicy, ...] = ()
    prefix_pools: tuple[PrefixPool, ...] = ()
    prefix_sets: tuple[PrefixSet, ...] = ()
    traffic_flows: tuple[TrafficFlowSpec, ...] = ()
    legacy_profile: str | None = None
    task_compatibility_profile: TaskCompatibilityProfile | None = None
    route_senders: tuple[RouteSender, ...] = ()

    @property
    def routing_device_config(self) -> RoutingDeviceConfig:
        return self.device_config

    def validate(self) -> None:
        import importlib

        validation = importlib.import_module(
            "neteng.test_infra.dne.taac.abstractions.validation"
        )
        validation.validate_logical_topology(self)

    def bind_to_inventory(
        self,
        physical_inventory: t.Any,
        port_map: t.Mapping[str, int],
        parent_networks: t.Mapping[str, str] | None = None,
        peer_groups: t.Mapping[str, BgpPeerGroup | str] | None = None,
        as_numbers: t.Mapping[str, int] | None = None,
        device_config_override: RoutingDeviceConfig | None = None,
    ) -> "BoundTopology":
        import importlib

        binding = importlib.import_module(
            "neteng.test_infra.dne.taac.abstractions.topology.binding"
        )

        return binding.bind_logical_topology_to_inventory(
            logical_topology=self,
            physical_inventory=physical_inventory,
            port_map=port_map,
            parent_networks=parent_networks,
            peer_groups=peer_groups,
            as_numbers=as_numbers,
            device_config_override=device_config_override,
        )


@dataclass(frozen=True)
class ResolvedEndpoint:
    name: str
    role: str
    kind: str
    backend: str
    physical_identifier: str | None
    network_role: NetworkRole | None = None


@dataclass(frozen=True)
class ResolvedPeer:
    a_ip: str
    z_ip: str
    peer_cidr: str | None


@dataclass(frozen=True)
class ResolvedIxiaDeviceGroupChild:
    name: str
    parent_name: str
    ordinal: int
    start_index: int
    role: str
    afi: str
    a_endpoint: str
    z_endpoint: str
    a_interface: str | None
    z_interface: str | None
    ixia_port: str | None
    routing_driver: str | None
    parent_network: str | None
    local_asn: int | None
    remote_asn: int | None
    peer_group: BgpPeerGroup | str | None
    legacy_ixia_device_group_name: str | None
    legacy_ixia_bgp_peer_name: str | None
    legacy_ixia_device_group_index: int | None
    legacy_ixia_prefix_pool_name: str | None
    peers: tuple[ResolvedPeer, ...]
    prefix_advertisements: tuple[ResolvedPrefixAdvertisementLike, ...]
    port_assignment: ResolvedIxiaPortAssignment | None
    route_attributes: RouteAttributePool | None
    provenance: "ResolvedDeviceGroupProvenance | None"

    @property
    def peer_count(self) -> int:
        return len(self.peers)


@dataclass(frozen=True)
class ResolvedDeviceGroup:
    name: str
    role: str
    afi: str
    a_endpoint: str
    z_endpoint: str
    a_interface: str | None
    z_interface: str | None
    ixia_port: str | None
    routing_driver: str | None
    parent_network: str | None
    local_asn: int | None
    remote_asn: int | None
    peer_group: BgpPeerGroup | str | None
    legacy_ixia_tag_name: str | None
    legacy_ixia_device_group_name: str | None
    peers: tuple[ResolvedPeer, ...]
    legacy_ixia_bgp_peer_name: str | None = None
    prefix_advertisements: tuple[ResolvedPrefixAdvertisementLike, ...] = ()
    port_assignment: ResolvedIxiaPortAssignment | None = None
    partition: DeviceGroupPartition | None = None
    legacy_ixia_device_group_index: int | None = None
    route_attributes: RouteAttributePool | None = None
    provenance: "ResolvedDeviceGroupProvenance | None" = None
    ixia_children: tuple[ResolvedIxiaDeviceGroupChild, ...] = ()
    peer_relationship: PeerRelationship | None = None

    @property
    def peer_count(self) -> int:
        return len(self.peers)


@dataclass(frozen=True)
class ResolvedDeviceGroupProvenance:
    parent_network: str | None
    parent_network_source: str | None
    local_asn: int | None
    local_asn_source: str | None
    remote_asn: int | None
    remote_asn_source: str | None


@dataclass(frozen=True)
class ResolvedIntentReport:
    logical_topology_name: str
    endpoints: tuple[ResolvedEndpoint, ...]
    device_groups: tuple[ResolvedDeviceGroup, ...]
    openr: ResolvedOpenRIntent
    prefix_sets: tuple[ResolvedPrefixSetLike, ...] = ()
    route_senders: tuple[RouteSender, ...] = ()


@dataclass(frozen=True)
class BoundIxiaDeviceGroupChild:
    spec: IxiaDeviceGroupChild
    peers: tuple[ResolvedPeer, ...]
    prefix_advertisements: tuple[ResolvedPrefixAdvertisementLike, ...]

    @property
    def name(self) -> str:
        return self.spec.name

    @property
    def peer_count(self) -> int:
        return len(self.peers)


@dataclass(frozen=True)
class BoundDeviceGroup:
    spec: DeviceGroupSpec
    a_interface: str | None = None
    z_interface: str | None = None
    ixia_port: str | None = None
    a_ips: tuple[str, ...] = ()
    z_ips: tuple[str, ...] = ()
    a_os: str | None = None
    z_os: str | None = None
    routing_driver: str | None = None
    parent_network: str | None = None
    local_asn: int | None = None
    remote_asn: int | None = None
    peer_group: BgpPeerGroup | str | None = None
    legacy_ixia_tag_name: str | None = None
    legacy_ixia_bgp_peer_name: str | None = None
    legacy_ixia_device_group_name: str | None = None
    peer_cidrs: tuple[str | None, ...] = ()
    prefix_advertisements: tuple[ResolvedPrefixAdvertisementLike, ...] = ()
    port_assignment: ResolvedIxiaPortAssignment | None = None
    partition: DeviceGroupPartition | None = None
    legacy_ixia_device_group_index: int | None = None
    route_attributes: RouteAttributePool | None = None
    provenance: ResolvedDeviceGroupProvenance | None = None
    ixia_children: tuple[BoundIxiaDeviceGroupChild, ...] = ()
    peer_relationship: PeerRelationship | None = None

    @property
    def name(self) -> str:
        return self.spec.name

    @property
    def role(self) -> str:
        return self.spec.role

    @property
    def afi(self) -> str:
        return self.spec.afi

    @property
    def peer_count(self) -> int:
        return self.spec.peer_count

    @property
    def dut_neighbor_absent(self) -> bool:
        return self.spec.dut_neighbor_absent

    @property
    def peers(self) -> tuple[ResolvedPeer, ...]:
        peer_cidrs = self.peer_cidrs or (None,) * len(self.a_ips)
        return tuple(
            ResolvedPeer(a_ip=a_ip, z_ip=z_ip, peer_cidr=peer_cidr)
            for a_ip, z_ip, peer_cidr in zip(
                self.a_ips,
                self.z_ips,
                peer_cidrs,
                strict=True,
            )
        )


def resolve_endpoint_routing_drivers(
    endpoint_name: str,
    device_groups: t.Iterable[BoundDeviceGroup],
    routing_drivers: t.Mapping[str, str],
) -> tuple[str, ...]:
    drivers: list[str] = []
    for device_group in device_groups:
        if endpoint_name not in {
            device_group.spec.a_endpoint,
            device_group.spec.z_endpoint,
        }:
            continue
        driver = device_group.routing_driver or routing_drivers.get(device_group.name)
        if driver is not None and driver not in drivers:
            drivers.append(driver)
    return tuple(drivers)


@dataclass(frozen=True)
class BoundRoutingConfig:
    routing_driver: str
    source: ConfigArtifactRef | None
    variant: None = None

    def __post_init__(self) -> None:
        if not isinstance(self.routing_driver, str):
            raise TypeError("bound routing config driver must be a string")
        if not self.routing_driver:
            raise ValueError("bound routing config driver must be nonempty")
        if self.source is not None and not isinstance(self.source, ConfigArtifactRef):
            raise TypeError("bound routing config source must be typed")
        if self.variant is not None:
            raise ValueError("bound routing config variants are not implemented")


@dataclass(frozen=True)
class BoundTopology:
    """Resolved logical intent bound to a physical inventory."""

    __hash__ = None

    logical_topology: LogicalTopology
    physical_inventory: t.Any | None = None
    device_groups: tuple[BoundDeviceGroup, ...] = ()
    device_config: RoutingDeviceConfig | None = None
    resolved_endpoints: t.Mapping[str, t.Mapping[str, t.Any]] = field(
        default_factory=dict
    )
    resolved_device_groups: t.Mapping[str, t.Mapping[str, t.Any]] = field(
        default_factory=dict
    )
    endpoint_os: t.Mapping[str, str] = field(default_factory=dict)
    endpoint_network_roles: t.Mapping[str, NetworkRole] = field(default_factory=dict)
    routing_configs: t.Mapping[str, BoundRoutingConfig] = field(default_factory=dict)
    routing_drivers: t.Mapping[str, str] = field(default_factory=dict)
    ixia_ports: t.Mapping[str, str] = field(default_factory=dict)
    interfaces: t.Mapping[str, str] = field(default_factory=dict)
    as_numbers: t.Mapping[str, int] = field(default_factory=dict)
    peer_groups_by_device_group: t.Mapping[str, BgpPeerGroup | str] = field(
        default_factory=dict
    )
    legacy_names: t.Mapping[str, str] = field(default_factory=dict)
    port_map: t.Mapping[str, int] = field(default_factory=dict)
    parent_networks: t.Mapping[str, str] = field(default_factory=dict)
    resolved_prefix_sets: t.Mapping[str, ResolvedPrefixSetLike] = field(
        default_factory=dict
    )
    resolved_route_senders: tuple[RouteSender, ...] = ()

    def validate_for_compile(self) -> None:
        import importlib

        binding = importlib.import_module(
            "neteng.test_infra.dne.taac.abstractions.topology.binding"
        )

        binding.validate_bound_topology_for_compile(self)

    def compile(self) -> CompiledTaacArtifactsLike:
        import importlib

        compiler = importlib.import_module(
            "neteng.test_infra.dne.taac.abstractions.compiler"
        )

        self.validate_for_compile()
        return compiler.select_topology_compiler(self).compile(self)

    def inspect_resolved_intent(self) -> ResolvedIntentReport:
        # inspection imports this primitive model, so keep the reverse BUCK edge runtime-only.
        import importlib

        inspection = importlib.import_module(
            "neteng.test_infra.dne.taac.abstractions.inspection"
        )
        return inspection.inspect_resolved_intent(self)
