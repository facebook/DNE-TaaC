# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe

from __future__ import annotations

import ipaddress
import typing as t
from dataclasses import dataclass

from ixia.ixia import types as ixia_types
from taac.abstractions.artifacts import CompiledTaacArtifacts
from taac.abstractions.compatibility.eos_bgpcpp_compatibility import (
    ACL_COMMANDS,
    ADD_INTERN_USER_IDS_CMD,
    BGPCPP_DAEMONS,
    EBB_BGPCPP_LOGGING_CONFIG,
    FIBAGENT_BGP_CONF_DEPLOY_CMD,
    FIBAGENT_CONF_DEPLOY_CMD,
    REQUIRE_THRIFT_ACL_FILES_CMD,
    UPDATE_GROUP_VERIFICATION_CMD,
    VERIFY_THRIFT_ACL_USER_IDS_CMD,
)
from taac.abstractions.compatibility.legacy_ebb_binding import (
    IXIA_IPV4_START_OFFSET,
    IXIA_IPV6_START_OFFSET,
)
from taac.abstractions.compatibility.legacy_ebb_topology import (
    BGP_MON_PEER_COUNT,
    EBGP_PEER_COUNT_V4,
    EBGP_PEER_COUNT_V6,
    EBGP_REMOTE_AS,
    EGRESS_PEER_SCALE_SWEEP_PEER_COUNTS,
    IBGP_PEER_SCALE_PER_PLANE,
    IBGP_REMOTE_AS,
)
from taac.abstractions.eos_bgpcpp_component_runtime import (
    ComponentRuntime,
    ComponentStartupOption,
    EosDaemonComponentDeployer,
    MetaComponentRuntimePlan,
)
from taac.abstractions.eos_bgpcpp_device_plan import (
    BgpPeerPlan,
    BgpPeerPlanEntry,
    BgpPolicyPlan,
    EosBgpCppDevicePlan,
    EosBgpCppSetupPhase,
    EosBgpCppSetupPhaseOwner,
    EosEndpointPlan,
    InterfaceAddressBlockPlan,
    InterfacePlan,
    IxiaPlan,
    OpenRFeaturePlan,
    TeardownPlan,
)
from taac.abstractions.eos_bgpcpp_setup_tasks import (
    create_bgpcpp_logging_setup_task,
    create_bgpcpp_peer_replacement_tasks,
    get_bgpcpp_startup_tasks_for_openr_mode,
    get_openr_standalone_setup_tasks,
    get_openr_standalone_teardown_tasks,
    OpenRStandaloneTeardownTasks,
)
from taac.abstractions.topology.model import (
    BgpPeerGroup,
    BgpPolicy,
    BoundDeviceGroup,
    BoundIxiaDeviceGroupChild,
    BoundTopology,
    EndpointSpec,
    LogicalTopology,
    OpenRMode,
    OpenRStandaloneLink,
    ResolvedIxiaPortAssignment,
    ResolvedPeer,
    RoutingDeviceConfig,
)
from taac.abstractions.topology.prefix import (
    NextHopMode,
    PeerPrefixDistribution,
)
from taac.abstractions.validation import (
    TopologyValidationError,
    ValidationIssue,
)
from taac.task_definitions import (
    create_arista_create_file_from_config_task,
    create_arista_daemon_control_task,
    create_bgp_clear_route_filter_task,
    create_deploy_tls_certs_task,
    create_interface_ip_cleanup_task,
    create_interface_ip_configuration_task,
    create_invoke_ixia_api_task,
    create_run_commands_on_shell_task,
)
from taac.test_as_a_config import types as taac_types

_T = t.TypeVar("_T")
_TRAFFIC_ENDPOINT_ROLES = frozenset({"ixia", "traffic", "trafficgen"})
_EBB_FULL_SCALE_PROFILE = "ebb_full_scale"
_EBB_FULL_SCALE_TOPOLOGY_NAMES = frozenset(
    {"ebb_full_scale_with_bgpmon", "ebb_full_scale_no_bgpmon"}
)
_UG_NEW_PEER_JOIN_PROFILE = "ug_new_peer_join"
_UG_NEW_PEER_JOIN_TOPOLOGY = "ug_new_peer_join"
# Spec 2.4.4 shares the ug_new_peer_join compiler handler (same legacy_profile)
# but is a DISTINCT topology name carrying one OPTIONAL spare eBGP group.
_UG_ADD_PEER_DYNAMIC_TOPOLOGY = "ug_add_peer_dynamic"
_IPV6_UPDATE_PACKING_PROFILE = "ipv6_update_packing"
_IPV6_UPDATE_PACKING_TOPOLOGY = "ipv6_update_packing"
_EGRESS_PEER_SCALE_PROFILE = "egress_peer_scale"
_EGRESS_PEER_SCALE_TOPOLOGY = "egress_peer_scale"
_BOUNDED_ECMP_PROFILE = "bounded_ecmp"
_BOUNDED_ECMP_TOPOLOGY = "bounded_ecmp"
_EBB_BGPCPP_CONFIG_PATH = "/mnt/flash/bgpcpp_config"
_EBB_NO_SETUP_MODES = frozenset({"skip", "verify_only"})
_EBB_IBGP_ROLES = (
    "ibgp_dc_p1",
    "ibgp_dc_p2",
    "ibgp_dc_p3",
    "ibgp_dc_p4",
    "ibgp_mp_p1",
    "ibgp_mp_p2",
    "ibgp_mp_p3",
    "ibgp_mp_p4",
)
_EBB_REQUIRED_ROLE_AFI_COUNTS = {
    ("uplink", "v4"): EBGP_PEER_COUNT_V4,
    ("uplink", "v6"): EBGP_PEER_COUNT_V6,
    **{
        (role, afi): IBGP_PEER_SCALE_PER_PLANE
        for role in _EBB_IBGP_ROLES
        for afi in ("v4", "v6")
    },
}
_EBB_OPTIONAL_ROLE_AFI_COUNTS = {("bgpmon", "v6"): BGP_MON_PEER_COUNT}
_UG_NEW_PEER_JOIN_ROLE_COUNTS = (
    ("ebgp_ug_ctrl", 4),
    ("ebgp_ug_held", 1),
    ("ebgp_ug_disp", 16),
    ("ibgp_ug_keep_initial", 1),
    ("ibgp_ug_keep_mutated", 1),
    ("ibgp_ug_var1", 1),
    ("ibgp_ug_var2", 1),
)
# OPTIONAL (0-or-1) roles for the ug_new_peer_join handler. Present only on
# UG_ADD_PEER_DYNAMIC (spec 2.4.4): the spare eBGP receiver whose DUT /127
# interface IP + IXIA session are provisioned, but whose static bgpcpp neighbor
# is absent (added at runtime via addPeers). Kept OPTIONAL so the spare-free
# UG_NEW_PEER_JOIN render stays byte-identical to master.
_UG_NEW_PEER_JOIN_OPTIONAL_ROLE_COUNTS = (("ebgp_ug_spare", 1),)


def _is_ug_new_peer_join(bound: BoundTopology) -> bool:
    # UG_NEW_PEER_JOIN and UG_ADD_PEER_DYNAMIC (spec 2.4.4) share this handler via
    # the same legacy_profile; the latter adds one OPTIONAL spare eBGP group.
    return (
        bound.logical_topology.name
        in (_UG_NEW_PEER_JOIN_TOPOLOGY, _UG_ADD_PEER_DYNAMIC_TOPOLOGY)
        and bound.logical_topology.legacy_profile == _UG_NEW_PEER_JOIN_PROFILE
    )


def _is_ebb_full_scale(bound: BoundTopology) -> bool:
    return (
        bound.logical_topology.name in _EBB_FULL_SCALE_TOPOLOGY_NAMES
        and bound.logical_topology.legacy_profile == _EBB_FULL_SCALE_PROFILE
    )


def _is_ipv6_update_packing(bound: BoundTopology) -> bool:
    return (
        bound.logical_topology.name == _IPV6_UPDATE_PACKING_TOPOLOGY
        and bound.logical_topology.legacy_profile == _IPV6_UPDATE_PACKING_PROFILE
    )


def _is_egress_peer_scale(bound: BoundTopology) -> bool:
    return (
        bound.logical_topology.name == _EGRESS_PEER_SCALE_TOPOLOGY
        and bound.logical_topology.legacy_profile == _EGRESS_PEER_SCALE_PROFILE
    )


def _is_bounded_ecmp(bound: BoundTopology) -> bool:
    return (
        bound.logical_topology.name == _BOUNDED_ECMP_TOPOLOGY
        and bound.logical_topology.legacy_profile == _BOUNDED_ECMP_PROFILE
    )


def _validate_bound_provenance_for_compile(bound: BoundTopology) -> None:
    issues = []
    for group_index, device_group in enumerate(bound.device_groups):
        provenance = device_group.provenance
        if provenance is None:
            issues.append(
                ValidationIssue(
                    path=f"device_groups[{group_index}].provenance",
                    code="missing_bind_provenance",
                    message="bound device group is missing its normalized bind snapshot",
                )
            )
            continue
        for field_name, expected, code in (
            (
                "parent_network",
                provenance.parent_network,
                "post_bind_parent_network_replacement",
            ),
            ("local_asn", provenance.local_asn, "post_bind_local_asn_replacement"),
            (
                "remote_asn",
                provenance.remote_asn,
                "post_bind_remote_asn_replacement",
            ),
        ):
            actual = getattr(device_group, field_name)
            if actual == expected:
                continue
            issues.append(
                ValidationIssue(
                    path=f"device_groups[{group_index}].{field_name}",
                    code=code,
                    message=(
                        f"bound {field_name} {actual!r} differs from the "
                        f"normalized bind snapshot {expected!r}"
                    ),
                )
            )
    if issues:
        raise TopologyValidationError(bound.logical_topology.name, issues)


def _validate_route_attributes_for_compile(
    bound: BoundTopology,
) -> None:
    for device_group in bound.device_groups:
        for advertisement_index, advertisement in enumerate(
            device_group.prefix_advertisements
        ):
            route_attributes = advertisement.spec.route_attributes
            if route_attributes is None:
                continue
            if not (
                route_attributes.as_paths
                or route_attributes.community_rows
                or route_attributes.extended_community_rows
            ):
                continue
            path = (
                f"device_groups.{device_group.name}.prefix_advertisements"
                f"[{advertisement_index}].route_attributes"
            )
            if (
                route_attributes.as_paths
                and bound.logical_topology.legacy_profile != _EBB_FULL_SCALE_PROFILE
            ):
                raise TopologyValidationError(
                    bound.logical_topology.name,
                    [
                        ValidationIssue(
                            path=f"{path}.as_paths",
                            code="unsupported_backend_route_attributes",
                            message=(
                                "formulaic IXIA lowering cannot initialize typed "
                                "AS-path route attributes"
                            ),
                        )
                    ],
                )
            if bound.logical_topology.legacy_profile in {
                _EGRESS_PEER_SCALE_PROFILE,
                _BOUNDED_ECMP_PROFILE,
            }:
                if (
                    len(route_attributes.community_rows) == 1
                    and route_attributes.community_rows[0]
                    and not route_attributes.extended_community_rows
                ):
                    continue
                raise TopologyValidationError(
                    bound.logical_topology.name,
                    [
                        ValidationIssue(
                            path=path,
                            code="unsupported_backend_route_attributes",
                            message=(
                                "native characteristic lowering requires one "
                                "nonempty standard-community row"
                            ),
                        )
                    ],
                )
            if bound.logical_topology.legacy_profile != _EBB_FULL_SCALE_PROFILE:
                suffix = (
                    ".community_rows"
                    if route_attributes.community_rows
                    else ".extended_community_rows"
                )
                raise TopologyValidationError(
                    bound.logical_topology.name,
                    [
                        ValidationIssue(
                            path=f"{path}{suffix}",
                            code="unsupported_backend_route_attributes",
                            message=(
                                "typed route attributes require formulaic EBB lowering"
                            ),
                        )
                    ],
                )


@dataclass(frozen=True)
class CompilerKey:
    endpoint_os: str
    routing_driver: str


@dataclass(frozen=True)
class CompiledTaacProfiles:
    primary: CompiledTaacArtifacts
    secondary_ixia_profile: taac_types.IxiaSetupProfile | None = None

    def test_config_fields(self) -> dict[str, t.Any]:
        fields: dict[str, t.Any] = {
            "endpoints": self.primary.endpoints,
            "host_os_type_map": self.primary.host_os_type_map,
            "setup_tasks": self.primary.setup_tasks,
            "teardown_tasks": self.primary.teardown_tasks,
            "basic_port_configs": self.primary.basic_port_configs,
            "basic_traffic_item_configs": self.primary.basic_traffic_item_configs,
        }
        if self.secondary_ixia_profile is not None:
            fields["secondary_ixia_profile"] = self.secondary_ixia_profile
        return fields


def compile_topology_profiles(
    logical_topology: LogicalTopology,
    *,
    physical_inventory: t.Any,
    port_map: t.Mapping[str, int],
    parent_networks: t.Mapping[str, str] | None = None,
    peer_groups: t.Mapping[str, BgpPeerGroup | str] | None = None,
    as_numbers: t.Mapping[str, int] | None = None,
    device_config_override: RoutingDeviceConfig | None = None,
) -> CompiledTaacProfiles:
    primary_bound, primary_artifacts = _bind_and_compile_topology(
        logical_topology,
        physical_inventory=physical_inventory,
        port_map=port_map,
        parent_networks=parent_networks,
        peer_groups=peer_groups,
        as_numbers=as_numbers,
        device_config_override=device_config_override,
    )
    if not getattr(physical_inventory, "has_secondary_ixia", False):
        return CompiledTaacProfiles(primary=primary_artifacts)

    secondary_inventory = physical_inventory.for_secondary_ixia()
    secondary_bound, secondary_artifacts = _bind_and_compile_topology(
        logical_topology,
        physical_inventory=secondary_inventory,
        port_map=port_map,
        parent_networks=parent_networks,
        peer_groups=peer_groups,
        as_numbers=as_numbers,
        device_config_override=device_config_override,
    )
    _validate_profile_equivalence(
        primary_bound,
        primary_artifacts,
        secondary_bound,
        secondary_artifacts,
    )
    secondary_chassis = t.cast(str, secondary_inventory.ixia_chassis_ip)
    return CompiledTaacProfiles(
        primary=primary_artifacts,
        secondary_ixia_profile=_artifacts_to_ixia_setup_profile(
            secondary_artifacts,
            name=secondary_chassis,
            api_server_ip=secondary_chassis,
        ),
    )


def _bind_and_compile_topology(
    logical_topology: LogicalTopology,
    *,
    physical_inventory: t.Any,
    port_map: t.Mapping[str, int],
    parent_networks: t.Mapping[str, str] | None,
    peer_groups: t.Mapping[str, BgpPeerGroup | str] | None,
    as_numbers: t.Mapping[str, int] | None,
    device_config_override: RoutingDeviceConfig | None,
) -> tuple[BoundTopology, CompiledTaacArtifacts]:
    bound = logical_topology.bind_to_inventory(
        physical_inventory=physical_inventory,
        port_map=port_map,
        parent_networks=parent_networks,
        peer_groups=peer_groups,
        as_numbers=as_numbers,
        device_config_override=device_config_override,
    )
    return bound, t.cast(CompiledTaacArtifacts, bound.compile())


def _artifacts_to_ixia_setup_profile(
    artifacts: CompiledTaacArtifacts,
    *,
    name: str,
    api_server_ip: str,
) -> taac_types.IxiaSetupProfile:
    return taac_types.IxiaSetupProfile(
        name=name,
        api_server_ip=api_server_ip,
        endpoints=artifacts.endpoints,
        setup_tasks=artifacts.setup_tasks,
        teardown_tasks=artifacts.teardown_tasks,
        basic_port_configs=artifacts.basic_port_configs,
        basic_traffic_item_configs=artifacts.basic_traffic_item_configs,
    )


def _validate_profile_equivalence(
    primary_bound: BoundTopology,
    primary: CompiledTaacArtifacts,
    secondary_bound: BoundTopology,
    secondary: CompiledTaacArtifacts,
) -> None:
    issues: list[ValidationIssue] = []
    if tuple(group.spec for group in primary_bound.device_groups) != tuple(
        group.spec for group in secondary_bound.device_groups
    ):
        issues.append(
            ValidationIssue(
                path="secondary_ixia_profile.device_groups",
                code="ixia_profile_device_group_mismatch",
                message="primary and secondary IXIA profiles must bind equivalent device groups",
            )
        )
    if (
        primary_bound.logical_topology.traffic_flows
        != secondary_bound.logical_topology.traffic_flows
    ):
        issues.append(
            ValidationIssue(
                path="secondary_ixia_profile.traffic_flows",
                code="ixia_profile_traffic_flow_mismatch",
                message="primary and secondary IXIA profiles must use equivalent traffic flows",
            )
        )
    if dict(primary_bound.port_map) != dict(secondary_bound.port_map) or set(
        primary_bound.ixia_ports.keys()
    ) != set(secondary_bound.ixia_ports.keys()):
        issues.append(
            ValidationIssue(
                path="secondary_ixia_profile.port_map",
                code="ixia_profile_port_index_mismatch",
                message="primary and secondary IXIA profiles must resolve the same required port indices",
            )
        )
    # DUT interface names may differ across profiles when the two chassis wire
    # to disjoint DUT ports; logical-role identity is what's asserted below.
    if _basic_port_signature(primary) != _basic_port_signature(secondary):
        issues.append(
            ValidationIssue(
                path="secondary_ixia_profile.basic_port_configs",
                code="ixia_profile_basic_port_config_mismatch",
                message="primary and secondary IXIA artifacts must materialize equivalent device groups",
            )
        )
    if _named_sequence_signature(
        primary.basic_traffic_item_configs,
        "name",
        "traffic_item_name",
    ) != _named_sequence_signature(
        secondary.basic_traffic_item_configs,
        "name",
        "traffic_item_name",
    ):
        issues.append(
            ValidationIssue(
                path="secondary_ixia_profile.basic_traffic_item_configs",
                code="ixia_profile_basic_traffic_item_mismatch",
                message="primary and secondary IXIA artifacts must materialize equivalent traffic flows",
            )
        )
    for phase, primary_tasks, secondary_tasks in (
        ("setup_tasks", primary.setup_tasks, secondary.setup_tasks),
        ("teardown_tasks", primary.teardown_tasks, secondary.teardown_tasks),
    ):
        if _named_sequence_signature(
            primary_tasks,
            "task_name",
        ) != _named_sequence_signature(secondary_tasks, "task_name"):
            issues.append(
                ValidationIssue(
                    path=f"secondary_ixia_profile.{phase}",
                    code="ixia_profile_task_phase_mismatch",
                    message=f"primary and secondary IXIA profiles must have equivalent {phase}",
                )
            )
    if issues:
        raise TopologyValidationError(primary_bound.logical_topology.name, issues)


def _basic_port_signature(
    artifacts: CompiledTaacArtifacts,
) -> tuple[tuple[t.Any, ...], ...]:
    return tuple(
        tuple(
            (
                type(group).__name__,
                getattr(group, "device_group_name", None),
                getattr(group, "tag_name", None),
                getattr(group, "device_group_index", None),
                getattr(group, "multiplier", None),
                getattr(
                    getattr(group, "v4_bgp_config", None),
                    "bgp_peer_name",
                    None,
                ),
                getattr(
                    getattr(group, "v6_bgp_config", None),
                    "bgp_peer_name",
                    None,
                ),
            )
            for group in (getattr(config, "device_group_configs", None) or [])
        )
        for config in artifacts.basic_port_configs
    )


def _named_sequence_signature(
    values: t.Sequence[t.Any],
    *attributes: str,
) -> tuple[t.Any, ...]:
    # When none of the requested identity attributes are populated, fall back to
    # `repr(value)` (which exposes the struct's field values) rather than the
    # bare class name, so two same-class items with distinct hidden data are not
    # silently equated.
    return tuple(
        next(
            (
                getattr(value, attribute)
                for attribute in attributes
                if getattr(value, attribute, None) is not None
            ),
            repr(value),
        )
        for value in values
    )


@dataclass(frozen=True)
class _EbbFullScaleInterfaces:
    device_name: str
    ebgp: str
    ibgp: str
    bgpmon: str | None
    include_bgpmon: bool


@dataclass(frozen=True)
class _EbbFullScaleSetupArgs:
    interfaces: _EbbFullScaleInterfaces
    bgp_asn: int
    bgpcpp_configerator_path: str
    enable_update_group: bool


@dataclass(frozen=True)
class _EosBgpCppOpenRInputs:
    mode: OpenRMode
    device_name: str | None = None
    configerator_path: str | None = None
    standalone_link: OpenRStandaloneLink | None = None


@dataclass(frozen=True)
class _EbbIxiaConnection:
    role: str
    interface: str
    ixia_port: str


@dataclass(frozen=True)
class _EbbFullScaleIxiaArgs:
    interfaces: _EbbFullScaleInterfaces
    groups: t.Mapping[tuple[str, str], BoundDeviceGroup]
    ebgp_remote_asn: int
    ibgp_remote_asn: int
    bgpmon_remote_asn: int | None


@dataclass(frozen=True)
class _UgNewPeerJoinArgs:
    device_name: str
    ixia_chassis_ip: str
    ebgp_interface: str
    ebgp_ixia_port: str
    ibgp_interface: str
    ibgp_ixia_port: str
    groups: t.Mapping[str, BoundDeviceGroup]
    bgp_asn: int
    # Optional: bag012 pins an explicit router-id; bag010/bag011/bag013 rely on
    # the device-default BGP router-id (get_update_packing_setup_tasks accepts
    # ``router_id=None``). Kept Optional so the UG new-peer-join topology can bind
    # to devices without a pinned router-id (e.g. bag013 for spec 2.4.4).
    router_id: str | None
    bgpcpp_configerator_path: str
    ebgp_remote_asn: int
    ibgp_remote_asn: int
    ebgp_parent_network: str
    ibgp_parent_network: str
    ebgp_peer_group_name: str
    ibgp_peer_group_name: str
    openr_mode: OpenRMode


@dataclass(frozen=True)
class _Ipv6UpdatePackingArgs:
    device_name: str
    ixia_chassis_ip: str
    ibgp_group: BoundDeviceGroup
    ebgp_group: BoundDeviceGroup
    ibgp_interface: str
    ebgp_interface: str
    ibgp_ixia_port: str
    ebgp_ixia_port: str
    bgp_asn: int
    router_id: str | None
    bgpcpp_configerator_path: str | None
    enable_update_group: bool
    openr_mode: OpenRMode


@dataclass(frozen=True)
class _EgressPeerScaleArgs:
    device_name: str
    ixia_chassis_ip: str
    groups: t.Mapping[tuple[str, str], BoundDeviceGroup]
    ebgp_interface: str
    ebgp_ixia_port: str
    ibgp_interface: str
    ibgp_ixia_port: str
    bgp_asn: int
    router_id: str | None
    bgpcpp_configerator_path: str
    enable_update_group: bool
    openr_mode: OpenRMode


@dataclass(frozen=True)
class _BoundedEcmpArgs:
    device_name: str
    ixia_chassis_ip: str
    groups: t.Mapping[tuple[str, str], BoundDeviceGroup]
    ebgp_interface: str
    ebgp_ixia_port: str
    ibgp_interface: str
    ibgp_ixia_port: str
    bgp_asn: int
    router_id: str | None
    bgpcpp_configerator_path: str | None
    enable_update_group: bool
    openr_mode: OpenRMode


def _ebb_full_scale_pre_ixia_setup_tasks(
    interfaces: _EbbFullScaleInterfaces,
) -> list:
    tasks = [
        create_arista_daemon_control_task(
            hostname=interfaces.device_name,
            daemon_name="BgpTcpdump",
            action="disable",
        )
    ]
    ixia_interfaces = [
        (interfaces.ebgp, "IXIA_MIMIC_EBGP"),
        (interfaces.ibgp, "IXIA_MIMIC_IBGP"),
    ]
    if interfaces.include_bgpmon:
        assert interfaces.bgpmon is not None
        ixia_interfaces.append((interfaces.bgpmon, "IXIA_MIMIC_BGP_MON"))

    for interface_name, description in ixia_interfaces:
        tasks.append(
            create_run_commands_on_shell_task(
                hostname=interfaces.device_name,
                cmds=[
                    "configure\n"
                    f"interface {interface_name}\n"
                    f"description {description}\n"
                    "no shutdown\n"
                    "speed 100g-2\n"
                    "no switchport\n"
                    "ipv6 enable\n"
                    "end",
                ],
                set_outer_hostname=True,
                ixia_needed=False,
            )
        )

    tasks.append(
        create_run_commands_on_shell_task(
            hostname=interfaces.device_name,
            cmds=["bash sleep 30"],
            set_outer_hostname=True,
            ixia_needed=False,
        )
    )
    return tasks


def _ebb_full_scale_bgpcpp_deployment_tasks(
    args: _EbbFullScaleSetupArgs,
) -> list:
    device_name = args.interfaces.device_name
    tasks = [
        create_run_commands_on_shell_task(
            hostname=device_name,
            cmds=[
                "bash mkdir -p /usr/facebook/thrift_acls",
                "bash mkdir -p /mnt/fb/agent_configs",
                "bash mkdir -p /mnt/fb/certs",
                "bash touch /usr/facebook/thrift_acls/auth_kill_switch_file",
            ],
            set_outer_hostname=True,
            ixia_needed=True,
        ),
        create_deploy_tls_certs_task(hostname=device_name),
        create_run_commands_on_shell_task(
            hostname=device_name,
            cmds=[f"configure\nrouter bgp {args.bgp_asn}\nshutdown\nend"],
            set_outer_hostname=True,
            ixia_needed=True,
        ),
        create_arista_create_file_from_config_task(
            hostname=device_name,
            configerator_path=args.bgpcpp_configerator_path,
            file_path=_EBB_BGPCPP_CONFIG_PATH,
            ixia_needed=True,
        ),
        create_run_commands_on_shell_task(
            hostname=device_name,
            cmds=[
                'bash sudo python3 -c "'
                "import json; "
                f"f=open('{_EBB_BGPCPP_CONFIG_PATH}'); c=json.load(f); f.close(); "
                "c.setdefault('thrift_server_config',{})['verify_client_type']=0; "
                f"f=open('{_EBB_BGPCPP_CONFIG_PATH}','w'); "
                "json.dump(c,f,indent=2); f.close(); "
                "print('Patched verify_client_type to 0')"
                '"',
            ],
            set_outer_hostname=True,
            ixia_needed=True,
        ),
    ]

    tasks.extend(
        [
            create_run_commands_on_shell_task(
                hostname=device_name,
                cmds=[FIBAGENT_BGP_CONF_DEPLOY_CMD],
                set_outer_hostname=True,
                ixia_needed=True,
            ),
            create_run_commands_on_shell_task(
                hostname=device_name,
                cmds=[FIBAGENT_CONF_DEPLOY_CMD],
                set_outer_hostname=True,
                ixia_needed=True,
            ),
        ]
    )

    return tasks


def _ebb_full_scale_control_plane_tasks(
    args: _EbbFullScaleSetupArgs,
    openr_mode: OpenRMode,
) -> list:
    device_name = args.interfaces.device_name
    tasks = [
        create_run_commands_on_shell_task(
            hostname=device_name,
            cmds=[ACL_COMMANDS],
            set_outer_hostname=True,
            ixia_needed=True,
        )
    ]

    tasks.append(
        create_run_commands_on_shell_task(
            hostname=device_name,
            cmds=[REQUIRE_THRIFT_ACL_FILES_CMD, ADD_INTERN_USER_IDS_CMD],
            set_outer_hostname=True,
            ixia_needed=True,
        )
    )

    for daemon in reversed(BGPCPP_DAEMONS):
        tasks.append(
            create_arista_daemon_control_task(
                hostname=device_name,
                daemon_name=daemon,
                action="disable",
                ixia_needed=True,
            )
        )

    for daemon in BGPCPP_DAEMONS:
        if daemon == "Openr" and openr_mode is OpenRMode.NONE:
            continue
        tasks.append(
            create_arista_daemon_control_task(
                hostname=device_name,
                daemon_name=daemon,
                action="enable",
                ixia_needed=True,
            )
        )

    tasks.append(
        create_run_commands_on_shell_task(
            hostname=device_name,
            cmds=[VERIFY_THRIFT_ACL_USER_IDS_CMD],
            set_outer_hostname=True,
            ixia_needed=True,
        )
    )

    if args.enable_update_group:
        tasks.append(
            create_run_commands_on_shell_task(
                hostname=device_name,
                cmds=[UPDATE_GROUP_VERIFICATION_CMD],
                set_outer_hostname=True,
                ixia_needed=True,
            )
        )

    return tasks


def _ebb_required_interface_ip_group(
    bound: BoundTopology,
    groups: t.Mapping[tuple[str, str], BoundDeviceGroup],
    role: str,
    afi: str,
) -> tuple[BoundDeviceGroup, str]:
    device_group = groups.get((role, afi))
    if device_group is None:
        raise TopologyValidationError(
            bound.logical_topology.name,
            [
                ValidationIssue(
                    path=f"device_groups.{role}.{afi}",
                    code="missing_ebb_interface_ip_input",
                    message=(
                        "native EBB full-scale interface IP setup requires a "
                        f"bound group for role={role!r}, afi={afi!r}"
                    ),
                )
            ],
        )
    parent_network = device_group.parent_network
    if not parent_network:
        raise TopologyValidationError(
            bound.logical_topology.name,
            [
                ValidationIssue(
                    path=f"device_groups.{device_group.name}.parent_network",
                    code="missing_ebb_ixia_input",
                    message=(
                        "canonical EBB full-scale IXIA mapping requires a bound "
                        f"parent network for {device_group.name!r}"
                    ),
                )
            ],
        )
    return device_group, parent_network


def _required_interface_address_block(
    bound: BoundTopology,
    plan: InterfacePlan,
    role: str,
    afi: str,
) -> InterfaceAddressBlockPlan:
    matches = [
        block
        for block in plan.address_blocks
        if block.role == role and block.afi == afi
    ]
    if len(matches) != 1:
        raise TopologyValidationError(
            bound.logical_topology.name,
            [
                ValidationIssue(
                    path=f"device_plan.interface_plan.{role}.{afi}",
                    code="missing_interface_address_projection",
                    message=(
                        "EOS interface rendering requires exactly one address "
                        f"block, got {len(matches)}"
                    ),
                )
            ],
        )
    return matches[0]


def _ebb_full_scale_interface_ip_config_tasks(
    bound: BoundTopology,
    plan: InterfacePlan,
    interfaces: _EbbFullScaleInterfaces,
) -> list:
    uplink_v4 = _required_interface_address_block(bound, plan, "uplink", "v4")
    uplink_v6 = _required_interface_address_block(bound, plan, "uplink", "v6")
    tasks = [
        create_interface_ip_configuration_task(
            interface=interfaces.ebgp,
            peer_count=len(uplink_v6.local_addresses),
            ipv4_base_network=uplink_v4.parent_network,
            ipv6_base_network=uplink_v6.parent_network,
            address_families=["ipv4", "ipv6"],
            clear_existing=True,
            hostname=interfaces.device_name,
            ixia_needed=True,
        )
    ]

    for plane_index, role in enumerate(_EBB_IBGP_ROLES):
        ipv4 = _required_interface_address_block(bound, plan, role, "v4")
        ipv6 = _required_interface_address_block(bound, plan, role, "v6")
        tasks.append(
            create_interface_ip_configuration_task(
                interface=interfaces.ibgp,
                peer_count=len(ipv6.local_addresses),
                ipv4_base_network=ipv4.parent_network,
                ipv6_base_network=ipv6.parent_network,
                address_families=["ipv4", "ipv6"],
                clear_existing=plane_index == 0,
                all_secondary=plane_index > 0,
                hostname=interfaces.device_name,
                ixia_needed=True,
            )
        )

    if interfaces.include_bgpmon:
        bgpmon_interface = interfaces.bgpmon
        if bgpmon_interface is None:
            raise TopologyValidationError(
                bound.logical_topology.name,
                [
                    ValidationIssue(
                        path="device_groups.bgpmon.interface",
                        code="missing_ebb_interface_ip_input",
                        message=(
                            "native EBB full-scale BGP-MON interface IP setup "
                            "requires a bound DUT interface"
                        ),
                    )
                ],
            )
        bgpmon = _required_interface_address_block(bound, plan, "bgpmon", "v6")
        tasks.append(
            create_interface_ip_configuration_task(
                interface=bgpmon_interface,
                peer_count=len(bgpmon.local_addresses),
                ipv6_base_network=bgpmon.parent_network,
                address_families=["ipv6"],
                clear_existing=True,
                hostname=interfaces.device_name,
                ixia_needed=True,
            )
        )

    return tasks


def _ebb_full_scale_setup_tail_tasks(
    args: _EbbFullScaleSetupArgs,
) -> list:
    return [
        create_run_commands_on_shell_task(
            hostname=args.interfaces.device_name,
            cmds=[
                "bash sudo iptables -F EOS_BGP",
                "bash sudo iptables -A EOS_BGP -j ACCEPT",
                "bash sudo ip6tables -F EOS_BGP",
                "bash sudo ip6tables -A EOS_BGP -j ACCEPT",
            ],
            set_outer_hostname=True,
            ixia_needed=True,
        )
    ]


def _characteristic_component_startup_tasks(
    setup_args: _EbbFullScaleSetupArgs,
    openr_mode: OpenRMode,
) -> tuple[t.Any, ...]:
    device_name = setup_args.interfaces.device_name
    # Characteristic profiles own OpenR startup in the later feature phase.
    control_plane_tasks = _ebb_full_scale_control_plane_tasks(
        setup_args,
        OpenRMode.NONE,
    )
    return (
        create_bgpcpp_logging_setup_task(
            device_name,
            EBB_BGPCPP_LOGGING_CONFIG,
        ),
        *get_bgpcpp_startup_tasks_for_openr_mode(
            device_name,
            openr_mode,
        ),
        *control_plane_tasks,
    )


def _characteristic_setup_prefix_phases(
    bound: BoundTopology,
    *,
    setup_args: _EbbFullScaleSetupArgs,
    interface_plan: InterfacePlan,
    openr_mode: OpenRMode,
) -> tuple[EosBgpCppSetupPhase, ...]:
    interfaces = setup_args.interfaces
    return (
        EosBgpCppSetupPhase(
            owner=EosBgpCppSetupPhaseOwner.HOST_PREPARATION,
            tasks=tuple(_ebb_full_scale_pre_ixia_setup_tasks(interfaces)),
        ),
        EosBgpCppSetupPhase(
            owner=EosBgpCppSetupPhaseOwner.COMPONENT_CONFIGURATION,
            tasks=tuple(_ebb_full_scale_bgpcpp_deployment_tasks(setup_args)),
        ),
        EosBgpCppSetupPhase(
            owner=EosBgpCppSetupPhaseOwner.COMPONENT_STARTUP,
            tasks=_characteristic_component_startup_tasks(setup_args, openr_mode),
        ),
        EosBgpCppSetupPhase(
            owner=EosBgpCppSetupPhaseOwner.INTERFACE_CONFIGURATION,
            tasks=tuple(
                _characteristic_interface_ip_tasks(
                    bound,
                    interface_plan,
                    interfaces.device_name,
                )
            ),
        ),
    )


def _characteristic_setup_suffix_phases(
    bound: BoundTopology,
    *,
    setup_args: _EbbFullScaleSetupArgs,
    peer_plan: BgpPeerPlan,
    router_id: str | None,
    finalization_tasks: t.Sequence[t.Any],
) -> tuple[EosBgpCppSetupPhase, ...]:
    device_name = setup_args.interfaces.device_name
    peer_tasks = create_bgpcpp_peer_replacement_tasks(
        hostname=device_name,
        router_id=router_id,
        peers=_bgpcpp_peer_configs(bound, peer_plan),
    )
    return (
        EosBgpCppSetupPhase(
            owner=EosBgpCppSetupPhaseOwner.COMPONENT_CONFIGURATION,
            tasks=tuple(peer_tasks),
        ),
        EosBgpCppSetupPhase(
            owner=EosBgpCppSetupPhaseOwner.COMPONENT_STARTUP,
            tasks=(
                create_arista_daemon_control_task(
                    hostname=device_name,
                    daemon_name="Bgp",
                    action="disable",
                    ixia_needed=True,
                ),
                create_arista_daemon_control_task(
                    hostname=device_name,
                    daemon_name="Bgp",
                    action="enable",
                    ixia_needed=True,
                ),
            ),
        ),
        EosBgpCppSetupPhase(
            owner=EosBgpCppSetupPhaseOwner.HOST_FINALIZATION,
            tasks=(
                *_ebb_full_scale_setup_tail_tasks(setup_args),
                *finalization_tasks,
            ),
        ),
    )


def _characteristic_setup_phases(
    bound: BoundTopology,
    *,
    device_name: str,
    bgp_asn: int,
    ebgp_interface: str,
    ibgp_interface: str,
    router_id: str | None,
    bgpcpp_configerator_path: str,
    enable_update_group: bool,
    openr_mode: OpenRMode,
    finalization_tasks: t.Sequence[t.Any] = (),
) -> tuple[EosBgpCppSetupPhase, ...]:
    setup_args = _EbbFullScaleSetupArgs(
        interfaces=_EbbFullScaleInterfaces(
            device_name=device_name,
            ebgp=ebgp_interface,
            ibgp=ibgp_interface,
            bgpmon=None,
            include_bgpmon=False,
        ),
        bgp_asn=bgp_asn,
        bgpcpp_configerator_path=bgpcpp_configerator_path,
        enable_update_group=enable_update_group,
    )
    return (
        *_characteristic_setup_prefix_phases(
            bound,
            setup_args=setup_args,
            interface_plan=_eos_bgpcpp_interface_plan(bound),
            openr_mode=openr_mode,
        ),
        *_characteristic_setup_suffix_phases(
            bound,
            setup_args=setup_args,
            peer_plan=_eos_bgpcpp_peer_plan(bound),
            router_id=router_id,
            finalization_tasks=finalization_tasks,
        ),
    )


def _ebb_required_legacy_ixia_names(
    bound: BoundTopology,
    device_group: BoundDeviceGroup,
) -> tuple[str, str]:
    device_group_name = device_group.legacy_ixia_device_group_name
    peer_name = (
        device_group.legacy_ixia_bgp_peer_name or device_group.legacy_ixia_tag_name
    )
    issues = []
    if not device_group_name:
        issues.append(
            ValidationIssue(
                path=(
                    f"device_groups.{device_group.name}.legacy_ixia_device_group_name"
                ),
                code="missing_ebb_ixia_input",
                message=(
                    "canonical EBB full-scale IXIA mapping requires a legacy "
                    f"device-group name for {device_group.name!r}"
                ),
            )
        )
    if not peer_name:
        issues.append(
            ValidationIssue(
                path=f"device_groups.{device_group.name}.legacy_ixia_tag_name",
                code="missing_ebb_ixia_input",
                message=(
                    "canonical EBB full-scale IXIA mapping requires a legacy "
                    f"peer tag for {device_group.name!r}"
                ),
            )
        )
    if issues:
        raise TopologyValidationError(bound.logical_topology.name, issues)
    assert device_group_name is not None
    assert peer_name is not None
    return device_group_name, peer_name


def _first_resolved_peer(
    bound: BoundTopology,
    device_group: BoundDeviceGroup,
) -> ResolvedPeer:
    if not device_group.a_ips or not device_group.z_ips:
        raise TopologyValidationError(
            bound.logical_topology.name,
            [
                ValidationIssue(
                    path=f"device_groups.{device_group.name}.peers",
                    code="missing_compiler_peer",
                    message="IXIA peer lowering requires at least one resolved peer",
                )
            ],
        )
    peer_cidr = device_group.peer_cidrs[0] if device_group.peer_cidrs else None
    return ResolvedPeer(
        a_ip=device_group.a_ips[0],
        z_ip=device_group.z_ips[0],
        peer_cidr=peer_cidr,
    )


def _raise_unsupported_group_lowering(
    bound: BoundTopology,
    device_group: BoundDeviceGroup,
    message: str,
    *,
    suffix: str = "",
    code: str,
) -> t.NoReturn:
    raise TopologyValidationError(
        bound.logical_topology.name,
        [
            ValidationIssue(
                path=f"device_groups.{device_group.name}{suffix}",
                code=code,
                message=message,
            )
        ],
    )


def _resolved_ixia_assignment(
    bound: BoundTopology,
    device_group: BoundDeviceGroup,
) -> ResolvedIxiaPortAssignment:
    assignment = device_group.port_assignment
    if assignment is None:
        _raise_unsupported_group_lowering(
            bound,
            device_group,
            "IXIA lowering requires a resolved port assignment",
            suffix=".port_assignment",
            code="missing_resolved_ixia_port_assignment",
        )
    return assignment


def _required_legacy_device_group_index(
    bound: BoundTopology,
    device_group: BoundDeviceGroup,
) -> int:
    explicit_index = device_group.legacy_ixia_device_group_index
    if explicit_index is None:
        _raise_unsupported_group_lowering(
            bound,
            device_group,
            "IXIA lowering requires an explicit legacy device-group index",
            suffix=".legacy_ixia_device_group_index",
            code="ixia_device_group_index_required",
        )
    return explicit_index


def _graceful_restart_kwargs(
    device_group: BoundDeviceGroup,
    *,
    established_default: bool,
) -> dict[str, t.Any]:
    peer_group = device_group.peer_group
    configured = (
        peer_group.enable_graceful_restart
        if isinstance(peer_group, BgpPeerGroup)
        else None
    )
    return {
        "enable_graceful_restart": (
            established_default if configured is None else configured
        )
    }


def _resolved_peer_prefix_length(
    bound: BoundTopology,
    device_group: BoundDeviceGroup,
    first_peer: ResolvedPeer | None = None,
) -> int:
    peer_cidr = (first_peer or _first_resolved_peer(bound, device_group)).peer_cidr
    if peer_cidr is None:
        raise TopologyValidationError(
            bound.logical_topology.name,
            [
                ValidationIssue(
                    path=(f"device_groups.{device_group.name}.peers[0].peer_cidr"),
                    code="missing_compiler_peer_cidr",
                    message="IXIA peer lowering requires a resolved peer CIDR",
                )
            ],
        )
    return int(peer_cidr.rsplit("/", 1)[1])


def _ip_step(value: int | str, afi: str) -> int:
    if isinstance(value, int):
        return value
    parsed = ipaddress.ip_address(value)
    if parsed.version != (4 if afi == "v4" else 6):
        raise ValueError(f"step {value!r} does not match afi={afi!r}")
    return int(parsed)


def _step_address(value: int, afi: str) -> str:
    address_type = ipaddress.IPv4Address if afi == "v4" else ipaddress.IPv6Address
    return str(address_type(value))


def _single_prefix_advertisement(
    bound: BoundTopology,
    device_group: BoundDeviceGroup,
):
    advertisements = device_group.prefix_advertisements
    if len(advertisements) != 1:
        raise TopologyValidationError(
            bound.logical_topology.name,
            [
                ValidationIssue(
                    path=f"device_groups.{device_group.name}.prefix_advertisements",
                    code="invalid_route_intent",
                    message="route-bearing device groups require one advertisement",
                )
            ],
        )
    return advertisements[0]


def _route_communities_for_advertisement(
    bound: BoundTopology,
    device_group: BoundDeviceGroup,
    advertisement: t.Any,
) -> list[str]:
    policy = advertisement.spec.policy
    if isinstance(policy, BgpPolicy):
        return list(policy.communities)
    route_attributes = advertisement.spec.route_attributes
    if (
        _is_ebb_full_scale(bound)
        and device_group.role.startswith("ibgp_dc_p")
        and route_attributes is not None
        and route_attributes.community_rows
        and route_attributes.community_rows[0]
    ):
        primary_community = route_attributes.community_rows[0][0]
        return [f"{primary_community.asn}:{primary_community.value}"]
    return []


def _uses_flat_ebb_prefix_geometry(
    bound: BoundTopology,
    advertisement: t.Any,
) -> bool:
    """Keep primary full-scale EBB pools addressable by logical prefix index."""
    return (
        _is_ebb_full_scale(bound)
        and advertisement.spec.allocation.network_group_index == 0
    )


def _route_scale_for_advertisement(
    bound: BoundTopology,
    device_group: BoundDeviceGroup,
    advertisement: t.Any,
    *,
    include_single_community_row: bool = False,
    lower_next_hop_intent: bool = False,
) -> taac_types.RouteScaleSpec:
    spec = advertisement.spec
    source = advertisement.prefix_set.spec.source
    communities = _route_communities_for_advertisement(
        bound,
        device_group,
        advertisement,
    )
    route_attributes = spec.route_attributes
    if include_single_community_row:
        if route_attributes is None:
            raise TopologyValidationError(
                bound.logical_topology.name,
                [
                    ValidationIssue(
                        path=(
                            f"device_groups.{device_group.name}."
                            "prefix_advertisements[0].route_attributes"
                        ),
                        code="missing_route_attributes",
                        message="route-scale lowering requires route attributes",
                    )
                ],
            )
        if not route_attributes.community_rows:
            raise TopologyValidationError(
                bound.logical_topology.name,
                [
                    ValidationIssue(
                        path=(
                            f"device_groups.{device_group.name}."
                            "prefix_advertisements[0].route_attributes.community_rows"
                        ),
                        code="missing_route_attribute_community_row",
                        message="route-scale lowering requires one community row",
                    )
                ],
            )
        if not route_attributes.community_rows[0]:
            raise TopologyValidationError(
                bound.logical_topology.name,
                [
                    ValidationIssue(
                        path=(
                            f"device_groups.{device_group.name}."
                            "prefix_advertisements[0].route_attributes."
                            "community_rows[0]"
                        ),
                        code="missing_route_attribute_community_row",
                        message="route-scale lowering requires a non-empty community row",
                    )
                ],
            )
        communities = [
            f"{community.asn}:{community.value}"
            for community in route_attributes.community_rows[0]
        ]
    source_step = _ip_step(source.prefix_step, device_group.afi)
    outer_step = (
        source_step
        if device_group.peer_count == 1
        else (
            0
            if spec.allocation.peer_distribution == PeerPrefixDistribution.SHARED
            else source_step * spec.allocation.prefixes_per_peer
        )
    )
    flat_prefix_geometry = _uses_flat_ebb_prefix_geometry(bound, advertisement)
    route_multiplier = spec.allocation.prefixes_per_peer if flat_prefix_geometry else 1
    route_prefix_count = (
        1 if flat_prefix_geometry else spec.allocation.prefixes_per_peer
    )
    route_step = source_step if flat_prefix_geometry else outer_step
    route_scale = taac_types.RouteScale(
        prefix_name=spec.legacy_ixia_name,
        prefix_count=route_prefix_count,
        prefix_length=source.prefix_length,
        starting_prefixes=advertisement.path_at(0, 0).prefix,
        prefix_step=(
            "0:0:0:0::1"
            if device_group.afi == "v6"
            and device_group.peer_count == 1
            and route_step == 1
            else _step_address(route_step, device_group.afi)
        ),
        multiplier=route_multiplier,
        as_path_prepend_numbers=(
            [list(path.asns) for path in route_attributes.as_paths]
            if route_attributes is not None and route_attributes.as_paths
            else None
        ),
        bgp_communities=communities,
        ip_address_family=(
            ixia_types.IpAddressFamily.IPV4
            if device_group.afi == "v4"
            else ixia_types.IpAddressFamily.IPV6
        ),
        set_next_hop_type=(
            ixia_types.SetNextHopType.SAME_AS_LOCAL_IP
            if lower_next_hop_intent and spec.next_hop.mode is NextHopMode.SELF
            else None
        ),
    )
    return taac_types.RouteScaleSpec(
        network_group_index=spec.allocation.network_group_index,
        multiplier=route_multiplier,
        v4_route_scale=route_scale if device_group.afi == "v4" else None,
        v6_route_scale=route_scale if device_group.afi == "v6" else None,
    )


def _route_scales(
    bound: BoundTopology,
    device_group: BoundDeviceGroup,
    *,
    include_single_community_row: bool = False,
    lower_next_hop_intent: bool = False,
) -> list[taac_types.RouteScaleSpec]:
    if not device_group.prefix_advertisements:
        return []
    return [
        _route_scale_for_advertisement(
            bound,
            device_group,
            advertisement,
            include_single_community_row=include_single_community_row,
            lower_next_hop_intent=lower_next_hop_intent,
        )
        for advertisement in device_group.prefix_advertisements
    ]


def _lower_self_nexthop_from_interface_state(bound: BoundTopology) -> bool:
    device_config = bound.device_config
    return (
        isinstance(device_config, RoutingDeviceConfig)
        and device_config.openr_mode is OpenRMode.NONE
    )


def _formulaic_prefix_mutation(advertisement: t.Any) -> dict[str, t.Any]:
    source = advertisement.prefix_set.spec.source
    membership = advertisement.spec.membership
    first_prefix = advertisement.path_at(0, 0).prefix
    source_start = ipaddress.ip_address(source.start_prefix)
    window_start = ipaddress.ip_address(first_prefix)
    source_step = _ip_step(source.prefix_step, advertisement.prefix_set.spec.afi)
    if source_step <= 0:
        raise ValueError("formulaic prefix mutation requires a positive source step")
    delta = int(window_start) - int(source_start)
    if delta < 0:
        raise ValueError("formulaic prefix window starts before its source")
    raw_start_index, remainder = divmod(delta, source_step)
    if remainder:
        raise ValueError("formulaic prefix window is not aligned to its source step")
    membership = advertisement.spec.membership
    last_prefix = advertisement.prefix_set.prefixes[
        membership.start_index + membership.prefix_count - 1
    ]
    end_delta = int(ipaddress.ip_address(last_prefix)) - int(source_start)
    raw_end_index, end_remainder = divmod(end_delta, source_step)
    if end_remainder:
        raise ValueError(
            "formulaic prefix window end is not aligned to its source step"
        )
    # prefix_count counts retained prefixes, while raw_end_index also spans
    # source indices excluded from the materialized prefix inventory.
    excluded_indices = [
        index - raw_start_index
        for index in source.excluded_indices
        if raw_start_index <= index <= raw_end_index
    ]
    raw_window_count = raw_end_index - raw_start_index + 1
    if raw_window_count != membership.prefix_count + len(excluded_indices):
        raise ValueError("formulaic prefix window has inconsistent sparse geometry")
    return {
        "start": first_prefix,
        "step": source_step,
        "count": membership.prefix_count,
        "excluded_indices": excluded_indices,
        "distribution": advertisement.spec.allocation.peer_distribution.value,
    }


def _formulaic_route_attribute_mutation(
    advertisement: t.Any,
) -> dict[str, t.Any] | None:
    route_attributes = advertisement.spec.route_attributes
    if route_attributes is None:
        return None
    return {
        "distribution": route_attributes.distribution.value,
        "community_rows": [
            [f"{community.asn}:{community.value}" for community in row]
            for row in route_attributes.community_rows
        ],
        "extended_community_rows": [
            [
                (
                    f"{community.kind.value}:{community.administrator}:"
                    f"{community.assigned_number}"
                )
                for community in row
            ]
            for row in route_attributes.extended_community_rows
        ],
    }


def _route_attribute_mutation_for_advertisement(
    advertisement: t.Any,
) -> dict[str, t.Any] | None:
    return _formulaic_route_attribute_mutation(advertisement)


def _ebb_route_mutations(bound: BoundTopology) -> list[dict[str, t.Any]]:
    mutations = []
    for device_group in bound.device_groups:
        for advertisement in device_group.prefix_advertisements:
            spec = advertisement.spec
            next_hop: dict[str, t.Any] | None = None
            next_hop_distribution = spec.next_hop.distribution
            if spec.next_hop.mode == NextHopMode.FORMULAIC:
                formula = spec.next_hop.formulaic_source
                if formula is None or next_hop_distribution is None:
                    raise TopologyValidationError(
                        bound.logical_topology.name,
                        [
                            ValidationIssue(
                                path=(
                                    f"device_groups.{device_group.name}."
                                    f"prefix_advertisements.{spec.name}.next_hop"
                                ),
                                code="invalid_route_intent",
                                message=(
                                    "formulaic next-hop intent requires a source and "
                                    "distribution"
                                ),
                            )
                        ],
                    )
                next_hop = {
                    "kind": "formulaic",
                    "start": formula.start,
                    "step": _ip_step(formula.step, device_group.afi),
                    "distribution": next_hop_distribution.value,
                }
            elif spec.next_hop.mode == NextHopMode.EXPLICIT:
                explicit = spec.next_hop.explicit_source
                if explicit is None or next_hop_distribution is None:
                    raise TopologyValidationError(
                        bound.logical_topology.name,
                        [
                            ValidationIssue(
                                path=(
                                    f"device_groups.{device_group.name}."
                                    f"prefix_advertisements.{spec.name}.next_hop"
                                ),
                                code="invalid_route_intent",
                                message=(
                                    "explicit next-hop intent requires a source and "
                                    "distribution"
                                ),
                            )
                        ],
                    )
                next_hop = {
                    "kind": "explicit",
                    "addresses": list(explicit.addresses),
                    "distribution": next_hop_distribution.value,
                }
            elif spec.next_hop.mode == NextHopMode.SELF:
                pass
            else:
                raise TopologyValidationError(
                    bound.logical_topology.name,
                    [
                        ValidationIssue(
                            path=(
                                f"device_groups.{device_group.name}."
                                f"prefix_advertisements.{spec.name}.next_hop.mode"
                            ),
                            code="unsupported_next_hop_mode",
                            message=f"unsupported next-hop mode {spec.next_hop.mode!r}",
                        )
                    ],
                )
            mutation = {
                "device_group_name": (
                    device_group.legacy_ixia_device_group_name or device_group.name
                ),
                "prefix_pool_name": spec.legacy_ixia_name or spec.name,
                "afi": device_group.afi,
                "peer_count": device_group.peer_count,
                "prefixes_per_peer": spec.allocation.prefixes_per_peer,
                "flat_prefix_geometry": _uses_flat_ebb_prefix_geometry(
                    bound, advertisement
                ),
                "prefix": _formulaic_prefix_mutation(advertisement),
                "next_hop": next_hop,
                "attributes": dict(spec.attributes),
            }
            route_attributes = _route_attribute_mutation_for_advertisement(
                advertisement
            )
            if route_attributes is not None:
                mutation["route_attributes"] = route_attributes
            mutations.append(mutation)
    return mutations


def _ebb_full_scale_ibgp_plane_device_groups(
    bound: BoundTopology,
    args: _EbbFullScaleIxiaArgs,
    plane_number: int,
) -> list[taac_types.DeviceGroupConfig]:
    dc_role = f"ibgp_dc_p{plane_number}"
    mp_role = f"ibgp_mp_p{plane_number}"
    v6_dc, _ = _ebb_required_interface_ip_group(bound, args.groups, dc_role, "v6")
    v6_mp, _ = _ebb_required_interface_ip_group(bound, args.groups, mp_role, "v6")
    v4_dc, _ = _ebb_required_interface_ip_group(bound, args.groups, dc_role, "v4")
    v4_mp, _ = _ebb_required_interface_ip_group(bound, args.groups, mp_role, "v4")
    v6_dc_name, v6_dc_peer = _ebb_required_legacy_ixia_names(bound, v6_dc)
    v6_mp_name, v6_mp_peer = _ebb_required_legacy_ixia_names(bound, v6_mp)
    v4_dc_name, v4_dc_peer = _ebb_required_legacy_ixia_names(bound, v4_dc)
    v4_mp_name, v4_mp_peer = _ebb_required_legacy_ixia_names(bound, v4_mp)
    v6_dc_first = _first_resolved_peer(bound, v6_dc)
    v6_mp_first = _first_resolved_peer(bound, v6_mp)
    v4_dc_first = _first_resolved_peer(bound, v4_dc)
    v4_mp_first = _first_resolved_peer(bound, v4_mp)
    return [
        taac_types.DeviceGroupConfig(
            device_group_name=v6_dc_name,
            device_group_index=_required_legacy_device_group_index(bound, v6_dc),
            multiplier=v6_dc.peer_count,
            v6_addresses_config=taac_types.IpAddressesConfig(
                starting_ip=v6_dc_first.z_ip,
                increment_ip="0:0:0:0::2",
                gateway_starting_ip=v6_dc_first.a_ip,
                gateway_increment_ip="0:0:0:0::2",
                start_index=0,
            ),
            v6_bgp_config=taac_types.BgpConfig(
                bgp_peer_name=v6_dc_peer,
                local_as_4_bytes=args.ibgp_remote_asn,
                enable_4_byte_local_as=True,
                **_graceful_restart_kwargs(v6_dc, established_default=False),
                bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                bgp_peer_type=ixia_types.BgpPeerType.IBGP,
                route_scales=_route_scales(
                    bound,
                    v6_dc,
                    lower_next_hop_intent=_lower_self_nexthop_from_interface_state(
                        bound
                    ),
                ),
            ),
        ),
        taac_types.DeviceGroupConfig(
            device_group_index=_required_legacy_device_group_index(bound, v6_mp),
            device_group_name=v6_mp_name,
            multiplier=v6_mp.peer_count,
            v6_addresses_config=taac_types.IpAddressesConfig(
                starting_ip=v6_mp_first.z_ip,
                increment_ip="0:0:0:0::2",
                gateway_starting_ip=v6_mp_first.a_ip,
                gateway_increment_ip="0:0:0:0::2",
            ),
            v6_bgp_config=taac_types.BgpConfig(
                bgp_peer_name=v6_mp_peer,
                local_as_4_bytes=args.ibgp_remote_asn,
                enable_4_byte_local_as=True,
                **_graceful_restart_kwargs(v6_mp, established_default=False),
                bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                bgp_peer_type=ixia_types.BgpPeerType.IBGP,
            ),
        ),
        taac_types.DeviceGroupConfig(
            device_group_index=_required_legacy_device_group_index(bound, v4_dc),
            device_group_name=v4_dc_name,
            multiplier=v4_dc.peer_count,
            v4_addresses_config=taac_types.IpAddressesConfig(
                starting_ip=v4_dc_first.z_ip,
                increment_ip="0.0.0.2",
                gateway_starting_ip=v4_dc_first.a_ip,
                gateway_increment_ip="0.0.0.2",
                mask=_resolved_peer_prefix_length(bound, v4_dc, v4_dc_first),
                start_index=0,
            ),
            v4_bgp_config=taac_types.BgpConfig(
                bgp_peer_name=v4_dc_peer,
                local_as_4_bytes=args.ibgp_remote_asn,
                enable_4_byte_local_as=True,
                **_graceful_restart_kwargs(v4_dc, established_default=False),
                bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                bgp_peer_type=ixia_types.BgpPeerType.IBGP,
                route_scales=_route_scales(
                    bound,
                    v4_dc,
                    lower_next_hop_intent=_lower_self_nexthop_from_interface_state(
                        bound
                    ),
                ),
            ),
        ),
        taac_types.DeviceGroupConfig(
            device_group_index=_required_legacy_device_group_index(bound, v4_mp),
            device_group_name=v4_mp_name,
            multiplier=v4_mp.peer_count,
            v4_addresses_config=taac_types.IpAddressesConfig(
                starting_ip=v4_mp_first.z_ip,
                increment_ip="0.0.0.2",
                gateway_starting_ip=v4_mp_first.a_ip,
                gateway_increment_ip="0.0.0.2",
                mask=_resolved_peer_prefix_length(bound, v4_mp, v4_mp_first),
            ),
            v4_bgp_config=taac_types.BgpConfig(
                bgp_peer_name=v4_mp_peer,
                local_as_4_bytes=args.ibgp_remote_asn,
                enable_4_byte_local_as=True,
                **_graceful_restart_kwargs(v4_mp, established_default=False),
                bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                bgp_peer_type=ixia_types.BgpPeerType.IBGP,
            ),
        ),
    ]


def _ebb_partition_family_base_address(
    address: str,
    device_group: BoundDeviceGroup,
) -> str:
    partition = device_group.partition
    if partition is None:
        return address
    parsed = ipaddress.ip_address(address)
    stride = _ip_step(device_group.spec.address_plan.stride, device_group.afi)
    return str(type(parsed)(int(parsed) - partition.start_index * stride))


def _ebb_authored_leaf_address_config(
    bound: BoundTopology,
    device_group: BoundDeviceGroup,
) -> taac_types.IpAddressesConfig:
    first_peer = _first_resolved_peer(bound, device_group)
    params: dict[str, t.Any] = {
        "starting_ip": _ebb_partition_family_base_address(
            first_peer.z_ip, device_group
        ),
        "increment_ip": ("0.0.0.2" if device_group.afi == "v4" else "0:0:0:0::2"),
        "gateway_starting_ip": _ebb_partition_family_base_address(
            first_peer.a_ip, device_group
        ),
        "gateway_increment_ip": (
            "0.0.0.2" if device_group.afi == "v4" else "0:0:0:0::2"
        ),
    }
    if device_group.afi == "v4":
        params["mask"] = _resolved_peer_prefix_length(bound, device_group, first_peer)
    if device_group.partition is not None:
        params["start_index"] = device_group.partition.start_index
    return taac_types.IpAddressesConfig(**params)


def _ebb_authored_leaf_bgp_config(
    bound: BoundTopology,
    device_group: BoundDeviceGroup,
) -> taac_types.BgpConfig:
    if device_group.remote_asn is None:
        _raise_unsupported_group_lowering(
            bound,
            device_group,
            "IXIA lowering requires a resolved remote ASN",
            suffix=".remote_asn",
            code="missing_ebb_ixia_input",
        )
    _, peer_name = _ebb_required_legacy_ixia_names(bound, device_group)
    base_role = _device_group_base_role(device_group)
    is_ebgp = base_role in {"ebgp", "uplink"}
    if base_role == "bgpmon":
        capabilities = [
            ixia_types.BgpCapability.IpV6Unicast,
            ixia_types.BgpCapability.IpV4Unicast,
            ixia_types.BgpCapability.Ipv4UnicastAddPath,
            ixia_types.BgpCapability.Ipv6UnicastAddPath,
            ixia_types.BgpCapability.NHEncodingCapabilities,
        ]
        peer_type = ixia_types.BgpPeerType.EBGP
        graceful_restart_default = False
    else:
        capabilities = [
            (
                ixia_types.BgpCapability.IpV4Unicast
                if device_group.afi == "v4"
                else ixia_types.BgpCapability.IpV6Unicast
            )
        ]
        peer_type = (
            ixia_types.BgpPeerType.EBGP if is_ebgp else ixia_types.BgpPeerType.IBGP
        )
        graceful_restart_default = is_ebgp
    params: dict[str, t.Any] = {
        "bgp_peer_name": peer_name,
        "local_as_4_bytes": device_group.remote_asn,
        "enable_4_byte_local_as": True,
        **_graceful_restart_kwargs(
            device_group,
            established_default=graceful_restart_default,
        ),
        "bgp_capabilities": capabilities,
        "bgp_peer_type": peer_type,
    }
    route_scales = _route_scales(bound, device_group)
    if route_scales:
        params["route_scales"] = route_scales
    return taac_types.BgpConfig(**params)


def _ebb_authored_leaf_device_group_config(
    bound: BoundTopology,
    device_group: BoundDeviceGroup,
) -> taac_types.DeviceGroupConfig:
    device_group_name, _ = _ebb_required_legacy_ixia_names(bound, device_group)
    address_config = _ebb_authored_leaf_address_config(bound, device_group)
    bgp_config = _ebb_authored_leaf_bgp_config(bound, device_group)
    return taac_types.DeviceGroupConfig(
        device_group_name=device_group_name,
        device_group_index=_required_legacy_device_group_index(bound, device_group),
        multiplier=device_group.peer_count,
        v4_addresses_config=address_config if device_group.afi == "v4" else None,
        v6_addresses_config=address_config if device_group.afi == "v6" else None,
        v4_bgp_config=bgp_config if device_group.afi == "v4" else None,
        v6_bgp_config=bgp_config if device_group.afi == "v6" else None,
    )


def _ebb_partitioned_basic_port_configs(
    bound: BoundTopology,
) -> list[taac_types.BasicPortConfig]:
    _validate_ebb_full_scale_shape(bound)
    device_name = _ebb_device_name(bound)
    configs_by_assignment: dict[
        tuple[str, str], list[taac_types.DeviceGroupConfig]
    ] = {}
    for device_group in bound.device_groups:
        assignment = _resolved_ixia_assignment(bound, device_group)
        key = (assignment.dut_interface, assignment.ixia_port)
        configs_by_assignment.setdefault(key, []).append(
            _ebb_authored_leaf_device_group_config(bound, device_group)
        )
    return [
        taac_types.BasicPortConfig(
            endpoint=f"{device_name}:{interface}",
            device_group_configs=device_group_configs,
        )
        for (
            interface,
            _ixia_port,
        ), device_group_configs in configs_by_assignment.items()
    ]


def _ebb_full_scale_basic_port_configs(
    bound: BoundTopology,
    args: _EbbFullScaleIxiaArgs,
) -> list[taac_types.BasicPortConfig]:
    ebgp_v6, _ = _ebb_required_interface_ip_group(bound, args.groups, "uplink", "v6")
    ebgp_v4, _ = _ebb_required_interface_ip_group(bound, args.groups, "uplink", "v4")
    ebgp_v6_name, ebgp_v6_peer = _ebb_required_legacy_ixia_names(bound, ebgp_v6)
    ebgp_v4_name, ebgp_v4_peer = _ebb_required_legacy_ixia_names(bound, ebgp_v4)
    ebgp_v6_first = _first_resolved_peer(bound, ebgp_v6)
    ebgp_v4_first = _first_resolved_peer(bound, ebgp_v4)
    configs = [
        taac_types.BasicPortConfig(
            endpoint=f"{args.interfaces.device_name}:{args.interfaces.ebgp}",
            device_group_configs=[
                taac_types.DeviceGroupConfig(
                    device_group_name=ebgp_v6_name,
                    device_group_index=_required_legacy_device_group_index(
                        bound, ebgp_v6
                    ),
                    multiplier=ebgp_v6.peer_count,
                    v6_addresses_config=taac_types.IpAddressesConfig(
                        starting_ip=ebgp_v6_first.z_ip,
                        increment_ip="0:0:0:0::2",
                        gateway_starting_ip=ebgp_v6_first.a_ip,
                        gateway_increment_ip="0:0:0:0::2",
                        start_index=0,
                    ),
                    v6_bgp_config=taac_types.BgpConfig(
                        bgp_peer_name=ebgp_v6_peer,
                        local_as_4_bytes=args.ebgp_remote_asn,
                        enable_4_byte_local_as=True,
                        bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                        bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                        **_graceful_restart_kwargs(ebgp_v6, established_default=True),
                        route_scales=_route_scales(
                            bound,
                            ebgp_v6,
                            lower_next_hop_intent=_lower_self_nexthop_from_interface_state(
                                bound
                            ),
                        ),
                    ),
                ),
                taac_types.DeviceGroupConfig(
                    device_group_name=ebgp_v4_name,
                    device_group_index=_required_legacy_device_group_index(
                        bound, ebgp_v4
                    ),
                    multiplier=ebgp_v4.peer_count,
                    v4_addresses_config=taac_types.IpAddressesConfig(
                        starting_ip=ebgp_v4_first.z_ip,
                        increment_ip="0.0.0.2",
                        gateway_starting_ip=ebgp_v4_first.a_ip,
                        gateway_increment_ip="0.0.0.2",
                        mask=_resolved_peer_prefix_length(
                            bound, ebgp_v4, ebgp_v4_first
                        ),
                        start_index=0,
                    ),
                    v4_bgp_config=taac_types.BgpConfig(
                        bgp_peer_name=ebgp_v4_peer,
                        local_as_4_bytes=args.ebgp_remote_asn,
                        enable_4_byte_local_as=True,
                        bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                        bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                        **_graceful_restart_kwargs(ebgp_v4, established_default=True),
                        route_scales=_route_scales(
                            bound,
                            ebgp_v4,
                            lower_next_hop_intent=_lower_self_nexthop_from_interface_state(
                                bound
                            ),
                        ),
                    ),
                ),
            ],
        )
    ]

    ibgp_device_groups = []
    for plane_number in range(1, 5):
        ibgp_device_groups.extend(
            _ebb_full_scale_ibgp_plane_device_groups(
                bound,
                args,
                plane_number,
            )
        )
    configs.append(
        taac_types.BasicPortConfig(
            endpoint=f"{args.interfaces.device_name}:{args.interfaces.ibgp}",
            device_group_configs=ibgp_device_groups,
        )
    )

    if args.interfaces.include_bgpmon:
        bgpmon, _ = _ebb_required_interface_ip_group(bound, args.groups, "bgpmon", "v6")
        bgpmon_name, bgpmon_peer = _ebb_required_legacy_ixia_names(bound, bgpmon)
        bgpmon_first = _first_resolved_peer(bound, bgpmon)
        bgpmon_interface = args.interfaces.bgpmon
        bgpmon_remote_asn = args.bgpmon_remote_asn
        if bgpmon_interface is None or bgpmon_remote_asn is None:
            raise TopologyValidationError(
                bound.logical_topology.name,
                [
                    ValidationIssue(
                        path="device_groups.bgpmon",
                        code="missing_ebb_ixia_input",
                        message=(
                            "canonical EBB full-scale IXIA mapping requires a "
                            "bound BGP-MON interface and remote ASN"
                        ),
                    )
                ],
            )
        configs.append(
            taac_types.BasicPortConfig(
                endpoint=f"{args.interfaces.device_name}:{bgpmon_interface}",
                device_group_configs=[
                    taac_types.DeviceGroupConfig(
                        device_group_name=bgpmon_name,
                        device_group_index=_required_legacy_device_group_index(
                            bound, bgpmon
                        ),
                        multiplier=bgpmon.peer_count,
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=bgpmon_first.z_ip,
                            increment_ip="0:0:0:0::2",
                            gateway_starting_ip=bgpmon_first.a_ip,
                            gateway_increment_ip="0:0:0:0::2",
                            start_index=0,
                        ),
                        v6_bgp_config=taac_types.BgpConfig(
                            bgp_peer_name=bgpmon_peer,
                            local_as_4_bytes=bgpmon_remote_asn,
                            enable_4_byte_local_as=True,
                            **_graceful_restart_kwargs(
                                bgpmon, established_default=False
                            ),
                            bgp_capabilities=[
                                ixia_types.BgpCapability.IpV6Unicast,
                                ixia_types.BgpCapability.IpV4Unicast,
                                ixia_types.BgpCapability.Ipv4UnicastAddPath,
                                ixia_types.BgpCapability.Ipv6UnicastAddPath,
                                ixia_types.BgpCapability.NHEncodingCapabilities,
                            ],
                            bgp_peer_type=ixia_types.BgpPeerType.EBGP,
                        ),
                    )
                ],
            )
        )

    return configs


def _ug_new_peer_join_args(  # noqa: C901
    bound: BoundTopology,
) -> _UgNewPeerJoinArgs:
    optional_counts = dict(_UG_NEW_PEER_JOIN_OPTIONAL_ROLE_COUNTS)
    # Allowed = required + optional; the optional spare (UG_ADD_PEER_DYNAMIC) must
    # not be flagged "unsupported", but it is NOT required (so the spare-free
    # UG_NEW_PEER_JOIN still validates identically to master).
    expected_counts = dict(_UG_NEW_PEER_JOIN_ROLE_COUNTS) | optional_counts
    grouped: dict[str, list[BoundDeviceGroup]] = {}
    for device_group in bound.device_groups:
        grouped.setdefault(device_group.role, []).append(device_group)

    issues: list[ValidationIssue] = []
    for role, expected_count in _UG_NEW_PEER_JOIN_ROLE_COUNTS:
        role_groups = grouped.get(role, [])
        if len(role_groups) != 1:
            issues.append(
                ValidationIssue(
                    path=f"device_groups.{role}",
                    code="invalid_ug_new_peer_join_shape",
                    message=(
                        "UG new-peer-join requires exactly one device group for "
                        f"role {role!r}; found {[group.name for group in role_groups]}"
                    ),
                )
            )
            continue
        device_group = role_groups[0]
        if device_group.afi != "v6" or device_group.peer_count != expected_count:
            issues.append(
                ValidationIssue(
                    path=f"device_groups.{device_group.name}",
                    code="invalid_ug_new_peer_join_shape",
                    message=(
                        f"role {role!r} requires {expected_count} IPv6 peers; "
                        f"got afi={device_group.afi!r}, "
                        f"peer_count={device_group.peer_count}"
                    ),
                )
            )
    # Optional roles (spec 2.4.4 spare): 0 or 1 group; if present, validate its
    # AFI + peer_count exactly as for a required role.
    for role, expected_count in _UG_NEW_PEER_JOIN_OPTIONAL_ROLE_COUNTS:
        role_groups = grouped.get(role, [])
        if len(role_groups) > 1:
            issues.append(
                ValidationIssue(
                    path=f"device_groups.{role}",
                    code="invalid_ug_new_peer_join_shape",
                    message=(
                        "UG new-peer-join allows at most one device group for "
                        f"optional role {role!r}; found "
                        f"{[group.name for group in role_groups]}"
                    ),
                )
            )
            continue
        if role_groups:
            device_group = role_groups[0]
            if device_group.afi != "v6" or device_group.peer_count != expected_count:
                issues.append(
                    ValidationIssue(
                        path=f"device_groups.{device_group.name}",
                        code="invalid_ug_new_peer_join_shape",
                        message=(
                            f"optional role {role!r} requires {expected_count} "
                            f"IPv6 peers; got afi={device_group.afi!r}, "
                            f"peer_count={device_group.peer_count}"
                        ),
                    )
                )
    for role in grouped:
        if role not in expected_counts:
            issues.append(
                ValidationIssue(
                    path=f"device_groups.{role}",
                    code="invalid_ug_new_peer_join_shape",
                    message=f"unsupported UG new-peer-join role {role!r}",
                )
            )

    physical_inventory = bound.physical_inventory
    device_name = getattr(physical_inventory, "device_name", None)
    ixia_chassis_ip = getattr(physical_inventory, "ixia_chassis_ip", None)
    bgp_asn = getattr(physical_inventory, "dut_bgp_as", None)
    router_id = getattr(physical_inventory, "router_id", None)
    bgpcpp_configerator_path = getattr(
        physical_inventory, "bgpcpp_configerator_path", None
    )
    for path, value in (
        ("physical_inventory.device_name", device_name),
        ("physical_inventory.ixia_chassis_ip", ixia_chassis_ip),
        ("physical_inventory.dut_bgp_as", bgp_asn),
        # router_id is intentionally NOT required -- devices without a pinned
        # router-id (bag010/bag011/bag013) use the device default.
        ("physical_inventory.bgpcpp_configerator_path", bgpcpp_configerator_path),
    ):
        if not value:
            issues.append(
                ValidationIssue(
                    path=path,
                    code="missing_ug_new_peer_join_input",
                    message=f"UG new-peer-join requires {path}",
                )
            )

    device_config = bound.device_config
    if device_config is None:
        issues.append(
            ValidationIssue(
                path="device_config",
                code="missing_ug_new_peer_join_input",
                message="UG new-peer-join requires bound device config",
            )
        )
    elif (
        not device_config.update_group_enable
        or device_config.openr_mode is not OpenRMode.NONE
    ):
        issues.append(
            ValidationIssue(
                path="device_config",
                code="invalid_ug_new_peer_join_device_config",
                message=(
                    "UG new-peer-join requires update_group_enable=True and "
                    "openr_mode=OpenRMode.NONE"
                ),
            )
        )

    if issues:
        raise TopologyValidationError(bound.logical_topology.name, issues)

    device_name = t.cast(str, device_name)
    ixia_chassis_ip = t.cast(str, ixia_chassis_ip)
    bgp_asn = t.cast(int, bgp_asn)
    router_id = t.cast("str | None", router_id)
    bgpcpp_configerator_path = t.cast(str, bgpcpp_configerator_path)

    groups = {role: role_groups[0] for role, role_groups in grouped.items()}

    def role_value_set(base_role: str, getter: t.Callable[[BoundDeviceGroup], t.Any]):
        return {
            value
            for role, group in groups.items()
            if role.startswith(f"{base_role}_")
            for value in (getter(group),)
        }

    def require_one(base_role: str, field: str, values: set[t.Any]) -> t.Any:
        if len(values) == 1:
            value = next(iter(values))
            if value:
                return value
        raise TopologyValidationError(
            bound.logical_topology.name,
            [
                ValidationIssue(
                    path=f"device_groups.{base_role}.{field}",
                    code="invalid_ug_new_peer_join_mapping",
                    message=(
                        f"UG new-peer-join {base_role} groups require one "
                        f"{field}; got {sorted(values, key=str)}"
                    ),
                )
            ],
        )

    def group_interface(device_group: BoundDeviceGroup) -> str | None:
        return _resolved_ixia_assignment(bound, device_group).dut_interface

    def peer_group_name(device_group: BoundDeviceGroup) -> str | None:
        peer_group = device_group.peer_group
        if isinstance(peer_group, BgpPeerGroup):
            return peer_group.name
        return peer_group

    ebgp_interface = require_one(
        "ebgp", "interface", role_value_set("ebgp", group_interface)
    )
    ibgp_interface = require_one(
        "ibgp", "interface", role_value_set("ibgp", group_interface)
    )
    ebgp_ixia_port = require_one(
        "ebgp",
        "ixia_port",
        role_value_set(
            "ebgp", lambda group: _resolved_ixia_assignment(bound, group).ixia_port
        ),
    )
    ibgp_ixia_port = require_one(
        "ibgp",
        "ixia_port",
        role_value_set(
            "ibgp", lambda group: _resolved_ixia_assignment(bound, group).ixia_port
        ),
    )
    ebgp_remote_asn = require_one(
        "ebgp", "remote_asn", role_value_set("ebgp", lambda group: group.remote_asn)
    )
    ibgp_remote_asn = require_one(
        "ibgp", "remote_asn", role_value_set("ibgp", lambda group: group.remote_asn)
    )
    ebgp_parent_network = require_one(
        "ebgp",
        "parent_network",
        role_value_set("ebgp", lambda group: group.parent_network),
    )
    ibgp_parent_network = require_one(
        "ibgp",
        "parent_network",
        role_value_set("ibgp", lambda group: group.parent_network),
    )
    ebgp_peer_group_name = require_one(
        "ebgp", "peer_group", role_value_set("ebgp", peer_group_name)
    )
    ibgp_peer_group_name = require_one(
        "ibgp", "peer_group", role_value_set("ibgp", peer_group_name)
    )

    return _UgNewPeerJoinArgs(
        device_name=device_name,
        ixia_chassis_ip=ixia_chassis_ip,
        ebgp_interface=ebgp_interface,
        ebgp_ixia_port=ebgp_ixia_port,
        ibgp_interface=ibgp_interface,
        ibgp_ixia_port=ibgp_ixia_port,
        groups=groups,
        bgp_asn=bgp_asn,
        router_id=router_id,
        bgpcpp_configerator_path=bgpcpp_configerator_path,
        ebgp_remote_asn=ebgp_remote_asn,
        ibgp_remote_asn=ibgp_remote_asn,
        ebgp_parent_network=ebgp_parent_network,
        ibgp_parent_network=ibgp_parent_network,
        ebgp_peer_group_name=ebgp_peer_group_name,
        ibgp_peer_group_name=ibgp_peer_group_name,
        openr_mode=t.cast(RoutingDeviceConfig, device_config).openr_mode,
    )


def _ug_new_peer_join_endpoint(args: _UgNewPeerJoinArgs) -> taac_types.Endpoint:
    connections = (
        (args.ebgp_interface, args.ebgp_ixia_port),
        (args.ibgp_interface, args.ibgp_ixia_port),
    )
    return taac_types.Endpoint(
        name=args.device_name,
        dut=True,
        ixia_ports=[
            f"{args.ixia_chassis_ip}:{ixia_port}" for _, ixia_port in connections
        ],
        direct_ixia_connections=[
            taac_types.DirectIxiaConnection(
                interface=interface,
                ixia_chassis_ip=args.ixia_chassis_ip,
                ixia_port=ixia_port,
            )
            for interface, ixia_port in connections
        ],
    )


def _ug_new_peer_join_setup_phases(
    bound: BoundTopology,
    args: _UgNewPeerJoinArgs,
) -> tuple[EosBgpCppSetupPhase, ...]:
    return _characteristic_setup_phases(
        bound,
        device_name=args.device_name,
        bgp_asn=args.bgp_asn,
        ebgp_interface=args.ebgp_interface,
        ibgp_interface=args.ibgp_interface,
        router_id=args.router_id,
        bgpcpp_configerator_path=args.bgpcpp_configerator_path,
        enable_update_group=True,
        openr_mode=args.openr_mode,
    )


def _ug_new_peer_join_route_scales(
    bound: BoundTopology,
    device_group: BoundDeviceGroup,
) -> list[taac_types.RouteScaleSpec]:
    return _route_scales(bound, device_group)


def _ug_new_peer_join_device_group_config(
    bound: BoundTopology,
    device_group: BoundDeviceGroup,
) -> taac_types.DeviceGroupConfig:
    tag_name = device_group.legacy_ixia_tag_name
    peer_name = device_group.legacy_ixia_bgp_peer_name or tag_name
    peer_group = device_group.peer_group
    if (
        not tag_name
        or not device_group.a_ips
        or not device_group.z_ips
        or device_group.remote_asn is None
        or not isinstance(peer_group, BgpPeerGroup)
    ):
        raise TopologyValidationError(
            bound.logical_topology.name,
            [
                ValidationIssue(
                    path=f"device_groups.{device_group.name}",
                    code="missing_ug_new_peer_join_ixia_input",
                    message=(
                        "UG IXIA emission requires a tag, bound peer addresses, "
                        "remote ASN, and resolved peer group"
                    ),
                )
            ],
        )
    first_peer = _first_resolved_peer(bound, device_group)
    is_ebgp = device_group.role.startswith("ebgp_")
    return taac_types.DeviceGroupConfig(
        device_group_index=_required_legacy_device_group_index(bound, device_group),
        tag_name=tag_name,
        multiplier=device_group.peer_count,
        v6_addresses_config=taac_types.IpAddressesConfig(
            starting_ip=first_peer.z_ip,
            increment_ip="0:0:0:0::2",
            gateway_starting_ip=first_peer.a_ip,
            gateway_increment_ip="0:0:0:0::2",
            mask=_resolved_peer_prefix_length(bound, device_group, first_peer),
            start_index=0,
        ),
        v6_bgp_config=taac_types.BgpConfig(
            bgp_peer_name=peer_name,
            local_as_4_bytes=device_group.remote_asn,
            enable_4_byte_local_as=True,
            bgp_peer_type=(
                ixia_types.BgpPeerType.EBGP if is_ebgp else ixia_types.BgpPeerType.IBGP
            ),
            bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
            hold_timer=peer_group.hold_timer_s,
            keepalive_timer=peer_group.keepalive_timer_s,
            route_scales=_ug_new_peer_join_route_scales(bound, device_group),
            **_graceful_restart_kwargs(device_group, established_default=True),
        ),
    )


def _ug_new_peer_join_basic_port_configs(
    bound: BoundTopology,
    args: _UgNewPeerJoinArgs,
) -> list[taac_types.BasicPortConfig]:
    role_groups = (
        (
            args.ebgp_interface,
            ("ebgp_ug_ctrl", "ebgp_ug_held", "ebgp_ug_disp", "ebgp_ug_spare"),
        ),
        (
            args.ibgp_interface,
            (
                "ibgp_ug_keep_initial",
                "ibgp_ug_keep_mutated",
                "ibgp_ug_var1",
                "ibgp_ug_var2",
            ),
        ),
    )
    return [
        taac_types.BasicPortConfig(
            endpoint=f"{args.device_name}:{interface}",
            device_group_configs=[
                # ``if role in args.groups`` skips the optional spare when absent
                # (UG_NEW_PEER_JOIN) so the emitted configs are byte-identical to
                # master; UG_ADD_PEER_DYNAMIC adds the spare's IXIA device group.
                _ug_new_peer_join_device_group_config(bound, args.groups[role])
                for role in roles
                if role in args.groups
            ],
        )
        for interface, roles in role_groups
    ]


def _ipv6_update_packing_args(  # noqa: C901
    bound: BoundTopology,
) -> _Ipv6UpdatePackingArgs:
    issues: list[ValidationIssue] = []
    grouped: dict[str, list[BoundDeviceGroup]] = {}
    for device_group in bound.device_groups:
        grouped.setdefault(device_group.role, []).append(device_group)

    if tuple(device_group.role for device_group in bound.device_groups) != (
        "ibgp",
        "ebgp",
    ):
        issues.append(
            ValidationIssue(
                path="device_groups",
                code="invalid_ipv6_update_packing_shape",
                message=(
                    "IPv6 update packing requires authored device-group order "
                    "['ibgp', 'ebgp']"
                ),
            )
        )

    expected_counts = {"ibgp": 1, "ebgp": 10}
    for role, expected_count in expected_counts.items():
        role_groups = grouped.get(role, [])
        if len(role_groups) != 1:
            issues.append(
                ValidationIssue(
                    path=f"device_groups.{role}",
                    code="invalid_ipv6_update_packing_shape",
                    message=(
                        "IPv6 update packing requires exactly one device group "
                        f"for role {role!r}; found "
                        f"{[group.name for group in role_groups]}"
                    ),
                )
            )
            continue
        group = role_groups[0]
        if group.afi != "v6" or group.peer_count != expected_count:
            issues.append(
                ValidationIssue(
                    path=f"device_groups.{group.name}",
                    code="invalid_ipv6_update_packing_shape",
                    message=(
                        f"role {role!r} requires {expected_count} IPv6 peers; "
                        f"got afi={group.afi!r}, peer_count={group.peer_count}"
                    ),
                )
            )
    for role in grouped:
        if role not in expected_counts:
            issues.append(
                ValidationIssue(
                    path=f"device_groups.{role}",
                    code="invalid_ipv6_update_packing_shape",
                    message=f"unsupported IPv6 update-packing role {role!r}",
                )
            )

    if issues:
        raise TopologyValidationError(bound.logical_topology.name, issues)

    ibgp_group = grouped["ibgp"][0]
    ebgp_group = grouped["ebgp"][0]
    for (
        role,
        group,
        expected_group_name,
        expected_peer_group,
        expected_legacy_group,
        expected_legacy_peer,
        expected_peer_group_local_asn,
        expected_peer_group_remote_asn,
        expected_remote_asn,
    ) in (
        (
            "ibgp",
            ibgp_group,
            "dg_ipv6_update_packing_ibgp",
            "EB-EB-V6",
            "DEVICE_GROUP_IPV6_IBGP",
            "BGP_PEER_IPV6_IBGP",
            "ibgp",
            "ibgp",
            64981,
        ),
        (
            "ebgp",
            ebgp_group,
            "dg_ipv6_update_packing_ebgp",
            "EB-FA-V6",
            "DEVICE_GROUP_IPV6_EBGP",
            "BGP_PEER_IPV6_EBGP",
            None,
            "ebgp",
            65334,
        ),
    ):
        assignment = group.port_assignment
        peer_group = group.peer_group
        if (
            assignment is None
            or assignment.logical_role != role
            or assignment.reuse_group is not None
        ):
            issues.append(
                ValidationIssue(
                    path=f"device_groups.{group.name}.port_assignment",
                    code="invalid_ipv6_update_packing_mapping",
                    message=(
                        f"{role} requires a dedicated resolved IXIA assignment "
                        f"with logical role {role!r}"
                    ),
                )
            )
        if not isinstance(peer_group, BgpPeerGroup) or (
            peer_group.name != expected_peer_group
            or peer_group.local_asn != expected_peer_group_local_asn
            or peer_group.remote_asn != expected_peer_group_remote_asn
            or peer_group.hold_timer_s != 30
            or peer_group.keepalive_timer_s != 10
            or peer_group.enable_graceful_restart is not True
        ):
            issues.append(
                ValidationIssue(
                    path=f"device_groups.{group.name}.peer_group",
                    code="invalid_ipv6_update_packing_peer_group",
                    message=(
                        f"{role} requires checked peer group "
                        f"{expected_peer_group!r} with 30/10 timers and graceful restart"
                    ),
                )
            )
        if group.name != expected_group_name:
            issues.append(
                ValidationIssue(
                    path=f"device_groups.{group.name}.name",
                    code="invalid_ipv6_update_packing_shape",
                    message=(
                        f"{role} requires logical group name {expected_group_name!r}"
                    ),
                )
            )
        if (
            group.legacy_ixia_device_group_name != expected_legacy_group
            or group.legacy_ixia_bgp_peer_name != expected_legacy_peer
            or group.legacy_ixia_tag_name is not None
            or group.legacy_ixia_device_group_index != 0
        ):
            issues.append(
                ValidationIssue(
                    path=f"device_groups.{group.name}.legacy_ixia_names",
                    code="invalid_ipv6_update_packing_ixia_identity",
                    message=(
                        "IPv6 update packing requires distinct device-group and "
                        "BGP peer names, no device-group tag, and explicit index 0"
                    ),
                )
            )
        if (
            not group.parent_network
            or group.remote_asn != expected_remote_asn
            or (role == "ibgp" and group.local_asn != expected_remote_asn)
            or (
                role == "ebgp"
                and group.local_asn
                != getattr(bound.physical_inventory, "dut_bgp_as", None)
            )
            or group.remote_asn is None
            or not group.a_ips
            or not group.z_ips
            or len(group.a_ips) != group.peer_count
            or len(group.z_ips) != group.peer_count
        ):
            issues.append(
                ValidationIssue(
                    path=f"device_groups.{group.name}.peers",
                    code="missing_ipv6_update_packing_input",
                    message=f"{role} requires complete bound peer and ASN inputs",
                )
            )

    if ibgp_group.prefix_advertisements:
        issues.append(
            ValidationIssue(
                path=(f"device_groups.{ibgp_group.name}.prefix_advertisements"),
                code="invalid_ipv6_update_packing_route_intent",
                message="the iBGP capture leaf must not advertise initial routes",
            )
        )
    if len(ebgp_group.prefix_advertisements) != 1:
        issues.append(
            ValidationIssue(
                path=(f"device_groups.{ebgp_group.name}.prefix_advertisements"),
                code="invalid_ipv6_update_packing_route_intent",
                message="the eBGP sender requires exactly one advertisement",
            )
        )
    else:
        advertisement = ebgp_group.prefix_advertisements[0]
        spec = advertisement.spec
        source_spec = advertisement.prefix_set.spec
        source = source_spec.source
        allocation = spec.allocation
        membership = spec.membership
        if (
            spec.name != "ipv6_update_packing_ebgp_routes"
            or source_spec.name != "ipv6_update_packing"
            or source_spec.afi != "v6"
            or source.start_prefix != "5001:db8:1000::"
            or _ip_step(source.prefix_step, "v6") != 1 << 80
            or source.prefix_length != 64
            or source.count != 10_000
            or source.excluded_indices
            or allocation.prefixes_per_peer != 10_000
            or allocation.peer_distribution is not PeerPrefixDistribution.SHARED
            or allocation.network_group_index != 0
            or membership.start_index != 0
            or membership.prefix_count != 10_000
            or spec.next_hop.mode is not NextHopMode.SELF
            or spec.route_attributes is not None
            or spec.attributes
            or spec.legacy_ixia_name != "PREFIX_POOL_IPV6_EBGP"
        ):
            issues.append(
                ValidationIssue(
                    path=(f"device_groups.{ebgp_group.name}.prefix_advertisements[0]"),
                    code="invalid_ipv6_update_packing_route_intent",
                    message=(
                        "eBGP requires the checked formulaic 10K shared IPv6 "
                        "pool with self next hop and no initial attributes"
                    ),
                )
            )

    expected_sender = (
        ebgp_group.name,
        (
            ebgp_group.prefix_advertisements[0].spec.name
            if len(ebgp_group.prefix_advertisements) == 1
            else None
        ),
    )
    actual_senders = tuple(
        (sender.device_group, sender.prefix_advertisement)
        for sender in bound.resolved_route_senders
    )
    if actual_senders != (expected_sender,):
        issues.append(
            ValidationIssue(
                path="route_senders",
                code="invalid_ipv6_update_packing_route_intent",
                message="IPv6 update packing requires exactly the eBGP route sender",
            )
        )

    device_config = bound.device_config
    if not isinstance(
        device_config, RoutingDeviceConfig
    ) or device_config.openr_mode not in {OpenRMode.NONE, OpenRMode.STANDALONE}:
        issues.append(
            ValidationIssue(
                path="device_config.openr_mode",
                code="invalid_ipv6_update_packing_device_config",
                message=(
                    "IPv6 update packing requires OpenRMode.NONE or "
                    "OpenRMode.STANDALONE"
                ),
            )
        )

    inventory = bound.physical_inventory
    device_name = getattr(inventory, "device_name", None)
    ixia_chassis_ip = getattr(inventory, "ixia_chassis_ip", None)
    bgp_asn = getattr(inventory, "dut_bgp_as", None)
    router_id = getattr(inventory, "router_id", None)
    bgpcpp_configerator_path = getattr(inventory, "bgpcpp_configerator_path", None)
    required_inventory = [
        ("physical_inventory.device_name", device_name),
        ("physical_inventory.ixia_chassis_ip", ixia_chassis_ip),
        ("physical_inventory.dut_bgp_as", bgp_asn),
    ]
    if _primary_dut_endpoint(bound).setup_mode == "full":
        required_inventory.extend(
            (
                (
                    "physical_inventory.bgpcpp_configerator_path",
                    bgpcpp_configerator_path,
                ),
            )
        )
    for path, value in required_inventory:
        if not value:
            issues.append(
                ValidationIssue(
                    path=path,
                    code="missing_ipv6_update_packing_input",
                    message=f"IPv6 update packing requires {path}",
                )
            )

    if issues:
        raise TopologyValidationError(bound.logical_topology.name, issues)

    assert isinstance(device_config, RoutingDeviceConfig)
    ibgp_assignment = _resolved_ixia_assignment(bound, ibgp_group)
    ebgp_assignment = _resolved_ixia_assignment(bound, ebgp_group)
    return _Ipv6UpdatePackingArgs(
        device_name=t.cast(str, device_name),
        ixia_chassis_ip=t.cast(str, ixia_chassis_ip),
        ibgp_group=ibgp_group,
        ebgp_group=ebgp_group,
        ibgp_interface=ibgp_assignment.dut_interface,
        ebgp_interface=ebgp_assignment.dut_interface,
        ibgp_ixia_port=ibgp_assignment.ixia_port,
        ebgp_ixia_port=ebgp_assignment.ixia_port,
        bgp_asn=t.cast(int, bgp_asn),
        router_id=router_id,
        bgpcpp_configerator_path=bgpcpp_configerator_path,
        enable_update_group=device_config.update_group_enable,
        openr_mode=device_config.openr_mode,
    )


def _checked_characteristic_endpoint(
    *,
    device_name: str,
    ixia_chassis_ip: str,
    ixia_interfaces: t.Iterable[str],
    connections: t.Iterable[tuple[str, str]],
) -> taac_types.Endpoint:
    return taac_types.Endpoint(
        name=device_name,
        dut=True,
        ixia_ports=list(ixia_interfaces),
        direct_ixia_connections=[
            taac_types.DirectIxiaConnection(
                interface=interface,
                ixia_chassis_ip=ixia_chassis_ip,
                ixia_port=ixia_port,
            )
            for interface, ixia_port in connections
        ],
    )


def _ipv6_update_packing_endpoint(
    args: _Ipv6UpdatePackingArgs,
) -> taac_types.Endpoint:
    return _checked_characteristic_endpoint(
        device_name=args.device_name,
        ixia_chassis_ip=args.ixia_chassis_ip,
        ixia_interfaces=(args.ibgp_interface, args.ebgp_interface),
        connections=(
            (args.ebgp_interface, args.ebgp_ixia_port),
            (args.ibgp_interface, args.ibgp_ixia_port),
        ),
    )


def _ipv6_update_packing_setup_phases(
    bound: BoundTopology,
    args: _Ipv6UpdatePackingArgs,
) -> tuple[EosBgpCppSetupPhase, ...]:
    assert args.bgpcpp_configerator_path is not None
    return _characteristic_setup_phases(
        bound,
        device_name=args.device_name,
        bgp_asn=args.bgp_asn,
        ebgp_interface=args.ebgp_interface,
        ibgp_interface=args.ibgp_interface,
        router_id=args.router_id,
        bgpcpp_configerator_path=args.bgpcpp_configerator_path,
        enable_update_group=args.enable_update_group,
        openr_mode=args.openr_mode,
    )


def _ipv6_update_packing_route_scales(
    bound: BoundTopology,
    device_group: BoundDeviceGroup,
) -> list[taac_types.RouteScaleSpec] | None:
    if not device_group.prefix_advertisements:
        return None
    advertisement = _single_prefix_advertisement(bound, device_group)
    spec = advertisement.spec
    source = advertisement.prefix_set.spec.source
    route_scale = taac_types.RouteScale(
        prefix_name=spec.legacy_ixia_name,
        starting_prefixes=advertisement.path_at(0, 0).prefix,
        prefix_step=_step_address(_ip_step(source.prefix_step, "v6"), "v6"),
        prefix_length=source.prefix_length,
        multiplier=1,
        prefix_count=spec.allocation.prefixes_per_peer,
        ip_address_family=ixia_types.IpAddressFamily.IPV6,
        bgp_communities=[],
    )
    return [
        taac_types.RouteScaleSpec(
            v6_route_scale=route_scale,
            multiplier=1,
            network_group_index=spec.allocation.network_group_index,
        )
    ]


def _ipv6_update_packing_device_group_config(
    bound: BoundTopology,
    device_group: BoundDeviceGroup,
) -> taac_types.DeviceGroupConfig:
    first_peer = _first_resolved_peer(bound, device_group)
    peer_name = device_group.legacy_ixia_bgp_peer_name
    if peer_name is None:
        raise TopologyValidationError(
            bound.logical_topology.name,
            [
                ValidationIssue(
                    path=(
                        f"device_groups.{device_group.name}.legacy_ixia_bgp_peer_name"
                    ),
                    code="missing_ipv6_update_packing_input",
                    message="IPv6 update-packing requires a legacy IXIA BGP peer name",
                )
            ],
        )
    return taac_types.DeviceGroupConfig(
        device_group_name=device_group.legacy_ixia_device_group_name,
        device_group_index=_required_legacy_device_group_index(bound, device_group),
        multiplier=device_group.peer_count,
        v6_addresses_config=taac_types.IpAddressesConfig(
            starting_ip=first_peer.z_ip,
            increment_ip="0:0:0:0::2",
            gateway_starting_ip=first_peer.a_ip,
            gateway_increment_ip="0:0:0:0::2",
            start_index=0,
        ),
        v6_bgp_config=taac_types.BgpConfig(
            bgp_peer_name=peer_name,
            local_as_4_bytes=device_group.remote_asn,
            enable_4_byte_local_as=True,
            bgp_peer_type=(
                ixia_types.BgpPeerType.EBGP
                if device_group.role == "ebgp"
                else ixia_types.BgpPeerType.IBGP
            ),
            route_scales=_ipv6_update_packing_route_scales(bound, device_group),
        ),
    )


def _ipv6_update_packing_basic_port_configs(
    bound: BoundTopology,
    args: _Ipv6UpdatePackingArgs,
) -> list[taac_types.BasicPortConfig]:
    return [
        taac_types.BasicPortConfig(
            endpoint=f"{args.device_name}:{interface}",
            device_group_configs=[
                _ipv6_update_packing_device_group_config(bound, group)
            ],
        )
        for interface, group in (
            (args.ibgp_interface, args.ibgp_group),
            (args.ebgp_interface, args.ebgp_group),
        )
    ]


def _egress_peer_scale_peer_group_issues(
    group: BoundDeviceGroup,
) -> list[ValidationIssue]:
    if isinstance(group.peer_group, BgpPeerGroup):
        return []
    return [
        ValidationIssue(
            path=f"device_groups.{group.name}.peer_group",
            code="invalid_egress_peer_scale_peer_group",
            message="egress peer scale requires a resolved BGP peer group",
        )
    ]


def _egress_peer_scale_args(bound: BoundTopology) -> _EgressPeerScaleArgs:
    max_sweep_peer_count = max(EGRESS_PEER_SCALE_SWEEP_PEER_COUNTS)
    expected = (
        ("ebgp", "v6", 1),
        ("ebgp", "v4", 1),
        ("ibgp", "v6", max_sweep_peer_count),
        ("ibgp", "v4", max_sweep_peer_count),
    )
    actual = tuple(
        (group.role, group.afi, group.peer_count) for group in bound.device_groups
    )
    if actual != expected:
        raise TopologyValidationError(
            bound.logical_topology.name,
            [
                ValidationIssue(
                    path="device_groups",
                    code="invalid_egress_peer_scale_shape",
                    message=f"egress peer scale requires {expected!r}; got {actual!r}",
                )
            ],
        )

    groups = {(group.role, group.afi): group for group in bound.device_groups}
    issues: list[ValidationIssue] = []
    expected_ixia_identity = (
        ("DEVICE_GROUP_IPV6_EBGP", "BGP_PEER_IPV6_EBGP", 0),
        ("DEVICE_GROUP_IPV4_EBGP", "BGP_PEER_IPV4_EBGP", 1),
        ("DEVICE_GROUP_IPV6_IBGP", "BGP_PEER_IPV6_IBGP", 0),
        ("DEVICE_GROUP_IPV4_IBGP", "BGP_PEER_IPV4_IBGP", 1),
    )
    actual_ixia_identity = tuple(
        (
            group.legacy_ixia_device_group_name,
            group.legacy_ixia_bgp_peer_name,
            group.legacy_ixia_device_group_index,
        )
        for group in bound.device_groups
    )
    if actual_ixia_identity != expected_ixia_identity:
        issues.append(
            ValidationIssue(
                path="device_groups.legacy_ixia_identity",
                code="invalid_egress_peer_scale_ixia_identity",
                message="egress peer scale requires its four checked IXIA identities",
            )
        )
    for role, afi, peer_count in expected:
        group = groups[(role, afi)]
        assignment = group.port_assignment
        issues.extend(_egress_peer_scale_peer_group_issues(group))
        if (
            assignment is None
            or assignment.logical_role != role
            or not group.legacy_ixia_device_group_name
            or not group.legacy_ixia_bgp_peer_name
            or group.legacy_ixia_device_group_index is None
            or group.remote_asn is None
            or not group.parent_network
            or len(group.a_ips) != peer_count
            or len(group.z_ips) != peer_count
        ):
            issues.append(
                ValidationIssue(
                    path=f"device_groups.{group.name}",
                    code="missing_egress_peer_scale_input",
                    message="compiler requires complete peer, IXIA, and ASN inputs",
                )
            )
        advertisements = group.prefix_advertisements
        if (role == "ebgp" and len(advertisements) != 1) or (
            role == "ibgp" and advertisements
        ):
            issues.append(
                ValidationIssue(
                    path=f"device_groups.{group.name}.prefix_advertisements",
                    code="invalid_egress_peer_scale_route_intent",
                    message="eBGP leaves require one advertisement; iBGP leaves none",
                )
            )

    for role in ("ebgp", "ibgp"):
        assignments = tuple(groups[(role, afi)].port_assignment for afi in ("v6", "v4"))
        if (
            None in assignments
            or len(
                {
                    (
                        assignment.dut_interface,
                        assignment.ixia_port,
                        assignment.physical_inventory_index,
                    )
                    for assignment in assignments
                    if assignment is not None
                }
            )
            != 1
        ):
            issues.append(
                ValidationIssue(
                    path=f"device_groups.{role}.port_assignment",
                    code="invalid_egress_peer_scale_mapping",
                    message=f"{role} IPv4 and IPv6 leaves must share one port",
                )
            )

    device_config = bound.device_config
    if (
        not isinstance(device_config, RoutingDeviceConfig)
        or device_config.openr_mode is not OpenRMode.NONE
    ):
        issues.append(
            ValidationIssue(
                path="device_config.openr_mode",
                code="invalid_egress_peer_scale_device_config",
                message="egress peer scale requires OpenRMode.NONE",
            )
        )

    inventory = bound.physical_inventory
    required_inventory = {
        "device_name": getattr(inventory, "device_name", None),
        "ixia_chassis_ip": getattr(inventory, "ixia_chassis_ip", None),
        "dut_bgp_as": getattr(inventory, "dut_bgp_as", None),
        "bgpcpp_configerator_path": getattr(
            inventory, "bgpcpp_configerator_path", None
        ),
    }
    for name, value in required_inventory.items():
        if not value:
            issues.append(
                ValidationIssue(
                    path=f"physical_inventory.{name}",
                    code="missing_egress_peer_scale_input",
                    message=f"egress peer scale requires physical_inventory.{name}",
                )
            )
    if issues:
        raise TopologyValidationError(bound.logical_topology.name, issues)

    ebgp_assignment = _resolved_ixia_assignment(bound, groups[("ebgp", "v6")])
    ibgp_assignment = _resolved_ixia_assignment(bound, groups[("ibgp", "v6")])
    assert isinstance(device_config, RoutingDeviceConfig)
    return _EgressPeerScaleArgs(
        device_name=t.cast(str, required_inventory["device_name"]),
        ixia_chassis_ip=t.cast(str, required_inventory["ixia_chassis_ip"]),
        groups=groups,
        ebgp_interface=ebgp_assignment.dut_interface,
        ebgp_ixia_port=ebgp_assignment.ixia_port,
        ibgp_interface=ibgp_assignment.dut_interface,
        ibgp_ixia_port=ibgp_assignment.ixia_port,
        bgp_asn=t.cast(int, required_inventory["dut_bgp_as"]),
        # None intentionally delegates router-id selection to the device default.
        router_id=t.cast(str | None, getattr(inventory, "router_id", None)),
        bgpcpp_configerator_path=t.cast(
            str, required_inventory["bgpcpp_configerator_path"]
        ),
        enable_update_group=device_config.update_group_enable,
        openr_mode=device_config.openr_mode,
    )


def _egress_peer_scale_endpoint(args: _EgressPeerScaleArgs) -> taac_types.Endpoint:
    connections = (
        (args.ebgp_interface, args.ebgp_ixia_port),
        (args.ibgp_interface, args.ibgp_ixia_port),
    )
    return _checked_characteristic_endpoint(
        device_name=args.device_name,
        ixia_chassis_ip=args.ixia_chassis_ip,
        ixia_interfaces=tuple(interface for interface, _ in connections),
        connections=connections,
    )


def _egress_peer_scale_setup_phases(
    bound: BoundTopology,
    args: _EgressPeerScaleArgs,
) -> tuple[EosBgpCppSetupPhase, ...]:
    return _characteristic_setup_phases(
        bound,
        device_name=args.device_name,
        bgp_asn=args.bgp_asn,
        ebgp_interface=args.ebgp_interface,
        ibgp_interface=args.ibgp_interface,
        router_id=args.router_id,
        bgpcpp_configerator_path=args.bgpcpp_configerator_path,
        enable_update_group=args.enable_update_group,
        openr_mode=args.openr_mode,
        finalization_tasks=(
            create_bgp_clear_route_filter_task(
                hostname=args.device_name,
                set_outer_hostname=True,
                ixia_needed=True,
            ),
        ),
    )


def _egress_peer_scale_device_group_config(
    bound: BoundTopology,
    device_group: BoundDeviceGroup,
) -> taac_types.DeviceGroupConfig:
    first_peer = _first_resolved_peer(bound, device_group)
    peer_name = device_group.legacy_ixia_bgp_peer_name
    group_name = device_group.legacy_ixia_device_group_name
    assert peer_name is not None and group_name is not None
    address_config = taac_types.IpAddressesConfig(
        starting_ip=first_peer.z_ip,
        increment_ip=("0.0.0.2" if device_group.afi == "v4" else "0:0:0:0::2"),
        gateway_starting_ip=first_peer.a_ip,
        gateway_increment_ip=("0.0.0.2" if device_group.afi == "v4" else "0:0:0:0::2"),
        mask=(
            _resolved_peer_prefix_length(bound, device_group, first_peer)
            if device_group.afi == "v4"
            else None
        ),
        start_index=0,
    )
    bgp_params: dict[str, t.Any] = {
        "bgp_peer_name": peer_name,
        "local_as_4_bytes": device_group.remote_asn,
        "enable_4_byte_local_as": True,
        "bgp_capabilities": [
            (
                ixia_types.BgpCapability.IpV4Unicast
                if device_group.afi == "v4"
                else ixia_types.BgpCapability.IpV6Unicast
            )
        ],
        "bgp_peer_type": (
            ixia_types.BgpPeerType.EBGP
            if device_group.role == "ebgp"
            else ixia_types.BgpPeerType.IBGP
        ),
    }
    if device_group.role == "ebgp":
        bgp_params["route_scales"] = _route_scales(
            bound,
            device_group,
            include_single_community_row=True,
            lower_next_hop_intent=_lower_self_nexthop_from_interface_state(bound),
        )
    else:
        bgp_params["enable_graceful_restart"] = False
    bgp_config = taac_types.BgpConfig(**bgp_params)
    return taac_types.DeviceGroupConfig(
        device_group_name=group_name,
        device_group_index=_required_legacy_device_group_index(bound, device_group),
        multiplier=device_group.peer_count,
        v4_addresses_config=address_config if device_group.afi == "v4" else None,
        v6_addresses_config=address_config if device_group.afi == "v6" else None,
        v4_bgp_config=bgp_config if device_group.afi == "v4" else None,
        v6_bgp_config=bgp_config if device_group.afi == "v6" else None,
    )


def _egress_peer_scale_basic_port_configs(
    bound: BoundTopology,
    args: _EgressPeerScaleArgs,
) -> list[taac_types.BasicPortConfig]:
    return [
        taac_types.BasicPortConfig(
            endpoint=f"{args.device_name}:{interface}",
            device_group_configs=[
                _egress_peer_scale_device_group_config(bound, args.groups[(role, afi)])
                for afi in ("v6", "v4")
            ],
        )
        for role, interface in (
            ("ebgp", args.ebgp_interface),
            ("ibgp", args.ibgp_interface),
        )
    ]


def _bounded_ecmp_args(bound: BoundTopology) -> _BoundedEcmpArgs:  # noqa: C901
    expected = (
        ("ebgp", "v6", 128),
        ("ebgp", "v4", 128),
        ("ibgp", "v6", 128),
        ("ibgp", "v4", 128),
    )
    actual = tuple(
        (group.role, group.afi, group.peer_count) for group in bound.device_groups
    )
    if actual != expected:
        raise TopologyValidationError(
            bound.logical_topology.name,
            [
                ValidationIssue(
                    path="device_groups",
                    code="invalid_bounded_ecmp_shape",
                    message=f"bounded ECMP requires {expected!r}; got {actual!r}",
                )
            ],
        )

    groups = {(group.role, group.afi): group for group in bound.device_groups}
    expected_names = {
        ("ebgp", "v6"): "dg_bounded_ecmp_ebgp_v6",
        ("ebgp", "v4"): "dg_bounded_ecmp_ebgp_v4",
        ("ibgp", "v6"): "dg_bounded_ecmp_ibgp_v6",
        ("ibgp", "v4"): "dg_bounded_ecmp_ibgp_v4",
    }
    expected_children = {
        ("ebgp", "v6"): (
            (
                "bounded_ecmp_ebgp_v6_set1",
                0,
                0,
                42,
                "DEVICE_GROUP_IPV6_EBGP_SET1",
                "BGP_PEER_IPV6_EBGP_SET1",
                "PREFIX_POOL_IPV6_EBGP_SET1",
            ),
            (
                "bounded_ecmp_ebgp_v6_set2",
                1,
                42,
                42,
                "DEVICE_GROUP_IPV6_EBGP_SET2",
                "BGP_PEER_IPV6_EBGP_SET2",
                "PREFIX_POOL_IPV6_EBGP_SET2",
            ),
            (
                "bounded_ecmp_ebgp_v6_set3",
                2,
                84,
                44,
                "DEVICE_GROUP_IPV6_EBGP_SET3",
                "BGP_PEER_IPV6_EBGP_SET3",
                "PREFIX_POOL_IPV6_EBGP_SET3",
            ),
        ),
        ("ebgp", "v4"): (
            (
                "bounded_ecmp_ebgp_v4_set1",
                0,
                0,
                42,
                "DEVICE_GROUP_IPV4_EBGP_SET1",
                "BGP_PEER_IPV4_EBGP_SET1",
                "PREFIX_POOL_IPV4_EBGP_SET1",
            ),
            (
                "bounded_ecmp_ebgp_v4_set2",
                1,
                42,
                42,
                "DEVICE_GROUP_IPV4_EBGP_SET2",
                "BGP_PEER_IPV4_EBGP_SET2",
                "PREFIX_POOL_IPV4_EBGP_SET2",
            ),
            (
                "bounded_ecmp_ebgp_v4_set3",
                2,
                84,
                44,
                "DEVICE_GROUP_IPV4_EBGP_SET3",
                "BGP_PEER_IPV4_EBGP_SET3",
                "PREFIX_POOL_IPV4_EBGP_SET3",
            ),
        ),
        ("ibgp", "v6"): (
            (
                "bounded_ecmp_ibgp_v6",
                0,
                0,
                128,
                "DEVICE_GROUP_IPV6_IBGP",
                "BGP_PEER_IPV6_IBGP",
                None,
            ),
        ),
        ("ibgp", "v4"): (
            (
                "bounded_ecmp_ibgp_v4",
                0,
                0,
                128,
                "DEVICE_GROUP_IPV4_IBGP",
                "BGP_PEER_IPV4_IBGP",
                None,
            ),
        ),
    }
    expected_indices = {
        ("ebgp", "v6"): (0, 1, 2),
        ("ebgp", "v4"): (3, 4, 5),
        ("ibgp", "v6"): (0,),
        ("ibgp", "v4"): (1,),
    }
    expected_peer_groups = {
        ("ebgp", "v6"): "EB-FA-V6",
        ("ebgp", "v4"): "EB-FA-V4",
        ("ibgp", "v6"): "EB-EB-V6",
        ("ibgp", "v4"): "EB-EB-V4",
    }
    issues: list[ValidationIssue] = []
    for key, group in groups.items():
        role, afi = key
        assignment = group.port_assignment
        peer_group = group.peer_group
        if group.name != expected_names[key]:
            issues.append(
                ValidationIssue(
                    path=f"device_groups.{group.name}.name",
                    code="invalid_bounded_ecmp_shape",
                    message=f"bounded ECMP requires logical group {expected_names[key]!r}",
                )
            )
        if (
            assignment is None
            or assignment.logical_role != role
            or assignment.reuse_group != f"bounded_ecmp_{role}"
        ):
            issues.append(
                ValidationIssue(
                    path=f"device_groups.{group.name}.port_assignment",
                    code="invalid_bounded_ecmp_mapping",
                    message=f"{role} leaves require their checked shared IXIA assignment",
                )
            )
        if (
            not isinstance(peer_group, BgpPeerGroup)
            or peer_group.name != expected_peer_groups[key]
            or group.remote_asn
            != (EBGP_REMOTE_AS if role == "ebgp" else IBGP_REMOTE_AS)
            or (role == "ibgp" and group.local_asn != IBGP_REMOTE_AS)
            or (role == "ibgp" and peer_group.enable_graceful_restart is not False)
        ):
            issues.append(
                ValidationIssue(
                    path=f"device_groups.{group.name}.peer_group",
                    code="invalid_bounded_ecmp_peer_group",
                    message="bounded ECMP requires its checked peer-group, ASN, and GR semantics",
                )
            )
        if (
            not group.parent_network
            or len(group.a_ips) != 128
            or len(group.z_ips) != 128
            or any(peer.peer_cidr is None for peer in group.peers)
        ):
            issues.append(
                ValidationIssue(
                    path=f"device_groups.{group.name}.peers",
                    code="missing_bounded_ecmp_input",
                    message="bounded ECMP requires 128 completely resolved peers",
                )
            )

        actual_children = tuple(
            (
                child.spec.name,
                child.spec.ordinal,
                child.spec.start_index,
                child.spec.peer_count,
                child.spec.legacy_ixia_device_group_name,
                child.spec.legacy_ixia_bgp_peer_name,
                child.spec.legacy_ixia_prefix_pool_name,
            )
            for child in group.ixia_children
        )
        if (
            actual_children != expected_children[key]
            or tuple(
                child.spec.legacy_ixia_device_group_index
                for child in group.ixia_children
            )
            != expected_indices[key]
        ):
            issues.append(
                ValidationIssue(
                    path=f"device_groups.{group.name}.ixia_children",
                    code="invalid_bounded_ecmp_child_shape",
                    message="bounded ECMP requires its checked 42/42/44 or one-to-one IXIA child layout",
                )
            )
        if any(
            len(child.peers) != child.spec.peer_count
            or child.peers
            != group.peers[
                child.spec.start_index : child.spec.start_index + child.spec.peer_count
            ]
            for child in group.ixia_children
        ):
            issues.append(
                ValidationIssue(
                    path=f"device_groups.{group.name}.ixia_children.peers",
                    code="invalid_bounded_ecmp_child_binding",
                    message="bounded ECMP children must be slices of the resolved parent peers",
                )
            )

        advertisements = group.prefix_advertisements
        if role == "ibgp":
            if advertisements or any(
                child.prefix_advertisements for child in group.ixia_children
            ):
                issues.append(
                    ValidationIssue(
                        path=f"device_groups.{group.name}.prefix_advertisements",
                        code="invalid_bounded_ecmp_route_intent",
                        message="bounded ECMP iBGP parents and children cannot advertise routes",
                    )
                )
            continue
        if len(advertisements) != 1:
            issues.append(
                ValidationIssue(
                    path=f"device_groups.{group.name}.prefix_advertisements",
                    code="invalid_bounded_ecmp_route_intent",
                    message="bounded ECMP eBGP parents require one advertisement",
                )
            )
            continue
        advertisement = advertisements[0]
        source = advertisement.prefix_set.spec.source
        spec = advertisement.spec
        route_attributes = spec.route_attributes
        expected_step = 256 if afi == "v4" else 1 << 64
        if (
            source.prefix_step != expected_step
            or source.prefix_length != (24 if afi == "v4" else 64)
            or spec.membership.start_index != 0
            or spec.membership.prefix_count != 5000
            or spec.allocation.prefixes_per_peer != 5000
            or spec.allocation.peer_distribution is not PeerPrefixDistribution.SHARED
            or spec.allocation.network_group_index != 0
            or spec.next_hop.mode is not NextHopMode.SELF
            or route_attributes is None
            or len(route_attributes.community_rows) != 1
            or tuple(
                (community.asn, community.value)
                for community in route_attributes.community_rows[0]
            )
            != ((65529, 39744),)
            or route_attributes.as_paths
            or route_attributes.extended_community_rows
        ):
            issues.append(
                ValidationIssue(
                    path=f"device_groups.{group.name}.prefix_advertisements[0]",
                    code="invalid_bounded_ecmp_route_intent",
                    message="bounded ECMP requires checked shared 5K formulaic routes with self next hops and one standard community",
                )
            )
        if any(
            len(child.prefix_advertisements) != 1
            or child.prefix_advertisements[0].paths_by_peer
            != advertisement.paths_by_peer[
                child.spec.start_index : child.spec.start_index + child.spec.peer_count
            ]
            for child in group.ixia_children
        ):
            issues.append(
                ValidationIssue(
                    path=f"device_groups.{group.name}.ixia_children.prefix_advertisements",
                    code="invalid_bounded_ecmp_child_binding",
                    message="bounded ECMP child advertisements must slice parent resolved paths",
                )
            )

    for role in ("ebgp", "ibgp"):
        assignments = tuple(groups[(role, afi)].port_assignment for afi in ("v6", "v4"))
        if (
            None in assignments
            or len(
                {
                    (assignment.dut_interface, assignment.ixia_port)
                    for assignment in assignments
                    if assignment is not None
                }
            )
            != 1
        ):
            issues.append(
                ValidationIssue(
                    path=f"device_groups.{role}.port_assignment",
                    code="invalid_bounded_ecmp_mapping",
                    message=f"{role} IPv4 and IPv6 parents must share one physical IXIA port",
                )
            )

    device_config = bound.device_config
    if device_config is None or device_config.openr_mode not in {
        OpenRMode.NONE,
        OpenRMode.STANDALONE,
    }:
        issues.append(
            ValidationIssue(
                path="device_config",
                code="invalid_bounded_ecmp_device_config",
                message=(
                    "bounded ECMP requires OpenRMode.NONE or OpenRMode.STANDALONE"
                ),
            )
        )
    inventory = bound.physical_inventory
    required_inventory = {
        "device_name": getattr(inventory, "device_name", None),
        "ixia_chassis_ip": getattr(inventory, "ixia_chassis_ip", None),
        "dut_bgp_as": getattr(inventory, "dut_bgp_as", None),
    }
    if _primary_dut_endpoint(bound).setup_mode == "full":
        required_inventory.update(
            {
                "bgpcpp_configerator_path": getattr(
                    inventory, "bgpcpp_configerator_path", None
                ),
            }
        )
    for name, value in required_inventory.items():
        if not value:
            issues.append(
                ValidationIssue(
                    path=f"physical_inventory.{name}",
                    code="missing_bounded_ecmp_input",
                    message=f"bounded ECMP requires physical_inventory.{name}",
                )
            )
    if issues:
        raise TopologyValidationError(bound.logical_topology.name, issues)

    ebgp_assignment = _resolved_ixia_assignment(bound, groups[("ebgp", "v6")])
    ibgp_assignment = _resolved_ixia_assignment(bound, groups[("ibgp", "v6")])
    return _BoundedEcmpArgs(
        device_name=t.cast(str, required_inventory["device_name"]),
        ixia_chassis_ip=t.cast(str, required_inventory["ixia_chassis_ip"]),
        groups=groups,
        ebgp_interface=ebgp_assignment.dut_interface,
        ebgp_ixia_port=ebgp_assignment.ixia_port,
        ibgp_interface=ibgp_assignment.dut_interface,
        ibgp_ixia_port=ibgp_assignment.ixia_port,
        bgp_asn=t.cast(int, required_inventory["dut_bgp_as"]),
        router_id=getattr(inventory, "router_id", None),
        bgpcpp_configerator_path=getattr(inventory, "bgpcpp_configerator_path", None),
        enable_update_group=t.cast(
            RoutingDeviceConfig, device_config
        ).update_group_enable,
        openr_mode=t.cast(RoutingDeviceConfig, device_config).openr_mode,
    )


def _bounded_ecmp_endpoint(args: _BoundedEcmpArgs) -> taac_types.Endpoint:
    return _checked_characteristic_endpoint(
        device_name=args.device_name,
        ixia_chassis_ip=args.ixia_chassis_ip,
        ixia_interfaces=(args.ebgp_interface, args.ibgp_interface),
        connections=(
            (args.ebgp_interface, args.ebgp_ixia_port),
            (args.ibgp_interface, args.ibgp_ixia_port),
        ),
    )


def _bounded_ecmp_setup_phases(
    bound: BoundTopology,
    args: _BoundedEcmpArgs,
) -> tuple[EosBgpCppSetupPhase, ...]:
    assert args.bgpcpp_configerator_path is not None
    return _characteristic_setup_phases(
        bound,
        device_name=args.device_name,
        bgp_asn=args.bgp_asn,
        ebgp_interface=args.ebgp_interface,
        ibgp_interface=args.ibgp_interface,
        router_id=args.router_id,
        bgpcpp_configerator_path=args.bgpcpp_configerator_path,
        enable_update_group=args.enable_update_group,
        openr_mode=args.openr_mode,
    )


def _bounded_ecmp_child_device_group_config(
    bound: BoundTopology,
    parent: BoundDeviceGroup,
    child: BoundIxiaDeviceGroupChild,
) -> taac_types.DeviceGroupConfig:
    if not child.peers:
        _raise_unsupported_group_lowering(
            bound,
            parent,
            f"bounded ECMP child {child.name!r} has no resolved peers",
            suffix=f".ixia_children.{child.name}.peers",
            code="missing_bounded_ecmp_input",
        )
    first_peer = child.peers[0]
    address_config = taac_types.IpAddressesConfig(
        starting_ip=first_peer.z_ip,
        increment_ip=("0.0.0.2" if parent.afi == "v4" else "0:0:0:0::2"),
        gateway_starting_ip=first_peer.a_ip,
        gateway_increment_ip=("0.0.0.2" if parent.afi == "v4" else "0:0:0:0::2"),
        mask=(
            int(t.cast(str, first_peer.peer_cidr).rsplit("/", 1)[1])
            if parent.afi == "v4"
            else None
        ),
        start_index=0,
    )
    bgp_params: dict[str, t.Any] = {
        "bgp_peer_name": child.spec.legacy_ixia_bgp_peer_name,
        "local_as_4_bytes": parent.remote_asn,
        "enable_4_byte_local_as": True,
        "bgp_capabilities": [
            (
                ixia_types.BgpCapability.IpV4Unicast
                if parent.afi == "v4"
                else ixia_types.BgpCapability.IpV6Unicast
            )
        ],
        "bgp_peer_type": (
            ixia_types.BgpPeerType.EBGP
            if parent.role == "ebgp"
            else ixia_types.BgpPeerType.IBGP
        ),
    }
    if parent.role == "ebgp":
        advertisement = child.prefix_advertisements[0]
        spec = advertisement.spec
        source = advertisement.prefix_set.spec.source
        route_attributes = t.cast(t.Any, spec.route_attributes)
        route_scale = taac_types.RouteScale(
            prefix_name=spec.legacy_ixia_name,
            prefix_count=spec.allocation.prefixes_per_peer,
            prefix_length=source.prefix_length,
            starting_prefixes=advertisement.path_at(0, 0).prefix,
            prefix_step=("0.0.0.0" if parent.afi == "v4" else "0:0:0:0:0:0:0:0"),
            multiplier=1,
            bgp_communities=[
                f"{community.asn}:{community.value}"
                for community in route_attributes.community_rows[0]
            ],
            ip_address_family=(
                ixia_types.IpAddressFamily.IPV4
                if parent.afi == "v4"
                else ixia_types.IpAddressFamily.IPV6
            ),
            set_next_hop_type=ixia_types.SetNextHopType.SAME_AS_LOCAL_IP,
        )
        bgp_params["route_scales"] = [
            taac_types.RouteScaleSpec(
                network_group_index=spec.allocation.network_group_index,
                multiplier=1,
                v4_route_scale=route_scale if parent.afi == "v4" else None,
                v6_route_scale=route_scale if parent.afi == "v6" else None,
            )
        ]
    else:
        bgp_params["enable_graceful_restart"] = False
    bgp_config = taac_types.BgpConfig(**bgp_params)
    return taac_types.DeviceGroupConfig(
        device_group_name=child.spec.legacy_ixia_device_group_name,
        device_group_index=child.spec.legacy_ixia_device_group_index,
        multiplier=child.peer_count,
        v4_addresses_config=address_config if parent.afi == "v4" else None,
        v6_addresses_config=address_config if parent.afi == "v6" else None,
        v4_bgp_config=bgp_config if parent.afi == "v4" else None,
        v6_bgp_config=bgp_config if parent.afi == "v6" else None,
    )


def _bounded_ecmp_basic_port_configs(
    bound: BoundTopology,
    args: _BoundedEcmpArgs,
) -> list[taac_types.BasicPortConfig]:
    return [
        taac_types.BasicPortConfig(
            endpoint=f"{args.device_name}:{interface}",
            device_group_configs=[
                _bounded_ecmp_child_device_group_config(bound, group, child)
                for afi in ("v6", "v4")
                for group in (args.groups[(role, afi)],)
                for child in group.ixia_children
            ],
        )
        for role, interface in (
            ("ebgp", args.ebgp_interface),
            ("ibgp", args.ibgp_interface),
        )
    ]


def _eos_bgpcpp_openr_inputs(bound: BoundTopology) -> _EosBgpCppOpenRInputs:
    device_config = bound.device_config
    physical_inventory = bound.physical_inventory
    issues: list[ValidationIssue] = []
    if device_config is None:
        issues.append(
            ValidationIssue(
                path="device_config",
                code="missing_bound_device_config",
                message="EOS BGP++ OpenR lowering requires bound device config",
            )
        )
    if issues:
        raise TopologyValidationError(bound.logical_topology.name, issues)

    assert device_config is not None
    mode = device_config.openr_mode
    if mode is OpenRMode.NONE:
        return _EosBgpCppOpenRInputs(mode=mode)

    device_name = getattr(physical_inventory, "device_name", None)
    if not device_name:
        issues.append(
            ValidationIssue(
                path="physical_inventory.device_name",
                code="missing_eos_bgpcpp_device_name",
                message="EOS BGP++ OpenR lowering requires a physical DUT name",
            )
        )
    if issues:
        raise TopologyValidationError(bound.logical_topology.name, issues)

    assert device_name

    configerator_path = device_config.openr_configerator_path or getattr(
        physical_inventory, "openr_configerator_path", None
    )
    if not configerator_path:
        issues.append(
            ValidationIssue(
                path="device_config.openr_configerator_path",
                code="missing_openr_configerator_path",
                message=(
                    f"OpenR {mode.value.upper()} mode requires an OpenR "
                    "configerator path from device config or PhysicalInventory"
                ),
            )
        )

    standalone_link = None
    if mode is OpenRMode.STANDALONE:
        standalone_link = device_config.openr_standalone_link or getattr(
            physical_inventory, "openr_standalone_link", None
        )
        if standalone_link is None:
            issues.append(
                ValidationIssue(
                    path="device_config.openr_standalone_link",
                    code="missing_openr_standalone_input",
                    message=(
                        "OpenR STANDALONE mode requires a typed owner/helper link "
                        "from device config or PhysicalInventory"
                    ),
                )
            )
        elif standalone_link.owner.hostname != device_name:
            issues.append(
                ValidationIssue(
                    path="device_config.openr_standalone_link.owner.hostname",
                    code="invalid_openr_standalone_owner",
                    message=(
                        "OpenR standalone link owner must match the physical DUT; "
                        f"got {standalone_link.owner.hostname!r} for {device_name!r}"
                    ),
                )
            )
    if issues:
        raise TopologyValidationError(bound.logical_topology.name, issues)
    return _EosBgpCppOpenRInputs(
        mode=mode,
        device_name=device_name,
        configerator_path=configerator_path,
        standalone_link=standalone_link,
    )


def _eos_bgpcpp_openr_config_tasks(inputs: _EosBgpCppOpenRInputs) -> list:
    if inputs.mode is OpenRMode.NONE:
        return []

    assert inputs.configerator_path
    assert inputs.device_name
    return [
        create_arista_create_file_from_config_task(
            hostname=inputs.device_name,
            configerator_path=inputs.configerator_path,
            file_path="/mnt/flash/openr_config",
            ixia_needed=True,
        ),
        create_run_commands_on_shell_task(
            hostname=inputs.device_name,
            cmds=["bash sudo ln -sf /mnt/flash/openr_config /etc/openr_config"],
            set_outer_hostname=True,
            ixia_needed=True,
        ),
    ]


def _eos_bgpcpp_openr_daemon_tasks(inputs: _EosBgpCppOpenRInputs) -> list:
    if inputs.mode is OpenRMode.NONE:
        return []
    assert inputs.device_name
    return [
        create_arista_daemon_control_task(
            hostname=inputs.device_name,
            daemon_name="Openr",
            action="disable",
            ixia_needed=True,
        ),
        create_arista_daemon_control_task(
            hostname=inputs.device_name,
            daemon_name="Openr",
            action="enable",
            ixia_needed=True,
        ),
    ]


def _eos_bgpcpp_openr_tail_tasks(inputs: _EosBgpCppOpenRInputs) -> list:
    if inputs.mode is OpenRMode.STANDALONE:
        assert inputs.standalone_link is not None
        return get_openr_standalone_setup_tasks(inputs.standalone_link)
    return []


def _eos_bgpcpp_openr_setup_tasks(inputs: _EosBgpCppOpenRInputs) -> list:
    return [
        *_eos_bgpcpp_openr_config_tasks(inputs),
        *_eos_bgpcpp_openr_daemon_tasks(inputs),
        *_eos_bgpcpp_openr_tail_tasks(inputs),
    ]


def _ebb_component_runtime_plan(
    bound: BoundTopology,
    args: _EbbFullScaleSetupArgs,
    openr_inputs: _EosBgpCppOpenRInputs,
) -> MetaComponentRuntimePlan:
    peer_plan = _eos_bgpcpp_peer_plan(bound)
    peer_tasks = create_bgpcpp_peer_replacement_tasks(
        hostname=args.interfaces.device_name,
        router_id=None,
        peers=_bgpcpp_peer_configs(bound, peer_plan),
    )
    dependencies = {
        "FibAgent": ("FibGrpc",),
        "FibAgentBgp": ("FibBgpGrpc",),
        "Bgp": (
            "FibAgent",
            "FibAgentBgp",
            *(("Openr",) if openr_inputs.mode is not OpenRMode.NONE else ()),
        ),
    }
    startup_options = (
        (
            ComponentStartupOption(
                component="Bgp",
                name="bgp_resolve_nexthops_from_interface_state",
                value="true",
            ),
        )
        if openr_inputs.mode is OpenRMode.NONE
        else ()
    )
    return MetaComponentRuntimePlan(
        logical_topology_name=bound.logical_topology.name,
        hostname=args.interfaces.device_name,
        components=tuple(
            ComponentRuntime(
                name=daemon,
                enabled=daemon != "Openr" or openr_inputs.mode is not OpenRMode.NONE,
                depends_on=dependencies.get(daemon, ()),
            )
            for daemon in BGPCPP_DAEMONS
        ),
        startup_options=startup_options,
        configuration_tasks=(
            *_ebb_full_scale_bgpcpp_deployment_tasks(args),
            *peer_tasks,
        ),
        startup_tasks=(
            create_bgpcpp_logging_setup_task(
                args.interfaces.device_name,
                EBB_BGPCPP_LOGGING_CONFIG,
            ),
            *get_bgpcpp_startup_tasks_for_openr_mode(
                args.interfaces.device_name,
                openr_inputs.mode,
            ),
            *_ebb_full_scale_control_plane_tasks(args, openr_inputs.mode),
        ),
    )


def _dut_peer_addresses(
    bound: BoundTopology,
    device_group: BoundDeviceGroup,
) -> tuple[tuple[str, ...], tuple[str, ...], str | None]:
    if device_group.a_interface is not None and device_group.z_interface is not None:
        raise TopologyValidationError(
            bound.logical_topology.name,
            [
                ValidationIssue(
                    path=f"device_groups.{device_group.name}.interfaces",
                    code="ambiguous_dut_interface_projection",
                    message=(
                        "EOS device groups must resolve the DUT to exactly one "
                        "side of the link"
                    ),
                )
            ],
        )
    if device_group.a_interface is not None:
        return device_group.a_ips, device_group.z_ips, device_group.a_interface
    if device_group.z_interface is not None:
        return device_group.z_ips, device_group.a_ips, device_group.z_interface
    return (), (), None


def _interface_parent_base(
    parent_network: str,
    afi: str,
) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    raw = parent_network.split("/", 1)[0]
    try:
        return ipaddress.ip_address(raw)
    except ValueError:
        if afi == "v4":
            octets = raw.split(".")
            if len(octets) == 3:
                raw = ".".join((*octets, "0"))
        elif afi == "v6" and "::" not in raw:
            raw = f"{raw}::"
        return ipaddress.ip_address(raw)


def _interface_prefix_length(
    bound: BoundTopology,
    device_group: BoundDeviceGroup,
) -> int:
    prefix_lengths = {
        int(peer.peer_cidr.rsplit("/", 1)[1])
        for peer in device_group.peers
        if peer.peer_cidr is not None
    }
    if len(prefix_lengths) == 1:
        return next(iter(prefix_lengths))
    raise TopologyValidationError(
        bound.logical_topology.name,
        [
            ValidationIssue(
                path=f"device_groups.{device_group.name}.peers",
                code="invalid_interface_address_projection",
                message=(
                    "EOS interface planning requires one resolved prefix "
                    f"length per device group, got {sorted(prefix_lengths)}"
                ),
            )
        ],
    )


def _interface_start_offset(
    bound: BoundTopology,
    device_group: BoundDeviceGroup,
    local_address: str,
) -> int:
    try:
        parent_network = device_group.parent_network
        if parent_network is None:
            raise ValueError("missing parent network")
        start_offset = int(ipaddress.ip_address(local_address)) - int(
            _interface_parent_base(parent_network, device_group.afi)
        )
    except ValueError as error:
        raise TopologyValidationError(
            bound.logical_topology.name,
            [
                ValidationIssue(
                    path=f"device_groups.{device_group.name}.parent_network",
                    code="invalid_interface_address_projection",
                    message=(
                        "EOS interface planning requires valid local and parent "
                        f"addresses, got local_address={local_address!r}, "
                        f"parent_network={device_group.parent_network!r}"
                    ),
                )
            ],
        ) from error
    if start_offset < 0:
        raise TopologyValidationError(
            bound.logical_topology.name,
            [
                ValidationIssue(
                    path=f"device_groups.{device_group.name}.parent_network",
                    code="invalid_interface_address_projection",
                    message=(
                        "EOS interface planning requires the first local address "
                        f"to be at or above the parent base, got "
                        f"local_address={local_address!r}, "
                        f"parent_network={parent_network!r}"
                    ),
                )
            ],
        )
    return start_offset


def _interface_stride(
    bound: BoundTopology,
    device_group: BoundDeviceGroup,
) -> int:
    raw_stride = device_group.spec.address_plan.stride
    try:
        stride = int(raw_stride)
    except (TypeError, ValueError) as error:
        raise TopologyValidationError(
            bound.logical_topology.name,
            [
                ValidationIssue(
                    path=f"device_groups.{device_group.name}.address_plan.stride",
                    code="invalid_interface_address_projection",
                    message=f"EOS interface planning requires an integer stride, got {raw_stride!r}",
                )
            ],
        ) from error
    if stride <= 0:
        raise TopologyValidationError(
            bound.logical_topology.name,
            [
                ValidationIssue(
                    path=f"device_groups.{device_group.name}.address_plan.stride",
                    code="invalid_interface_address_projection",
                    message=f"EOS interface planning requires a positive stride, got {stride}",
                )
            ],
        )
    return stride


def _eos_bgpcpp_interface_plan(bound: BoundTopology) -> InterfacePlan:
    grouped: dict[
        tuple[str, str, str],
        tuple[list[str], str, list[str], list[str], int, int, int],
    ] = {}
    for device_group in bound.device_groups:
        local_addresses, peer_addresses, interface = _dut_peer_addresses(
            bound, device_group
        )
        if len(local_addresses) != len(peer_addresses):
            raise TopologyValidationError(
                bound.logical_topology.name,
                [
                    ValidationIssue(
                        path=f"device_groups.{device_group.name}.peers",
                        code="invalid_interface_address_projection",
                        message=(
                            "interface planning requires equal local and peer "
                            f"address counts, got {len(local_addresses)} and "
                            f"{len(peer_addresses)}"
                        ),
                    )
                ],
            )
        if interface is None or not local_addresses or not device_group.parent_network:
            continue
        prefix_length = _interface_prefix_length(bound, device_group)
        stride = _interface_stride(bound, device_group)
        start_offset = _interface_start_offset(
            bound,
            device_group,
            local_addresses[0],
        )
        key = (interface, device_group.afi, device_group.parent_network)
        if key not in grouped:
            grouped[key] = (
                [],
                device_group.role,
                [],
                [],
                prefix_length,
                start_offset,
                stride,
            )
        (
            device_groups,
            _role,
            block_local_addresses,
            block_peer_addresses,
            _prefix_length,
            _start_offset,
            _stride,
        ) = grouped[key]
        expected_start_offset = _start_offset + _stride * len(block_local_addresses)
        if (
            _bgp_role_family(device_group.role) != _bgp_role_family(_role)
            or prefix_length != _prefix_length
            or stride != _stride
            or start_offset != expected_start_offset
        ):
            raise TopologyValidationError(
                bound.logical_topology.name,
                [
                    ValidationIssue(
                        path=f"device_groups.{device_group.name}",
                        code="inconsistent_interface_address_projection",
                        message=(
                            "EOS interface aggregation requires matching role "
                            "family and prefix length with contiguous address "
                            f"slices; expected role_family="
                            f"{_bgp_role_family(_role)!r}, prefix_length="
                            f"{_prefix_length}, start_offset="
                            f"{expected_start_offset}, got role_family="
                            f"{_bgp_role_family(device_group.role)!r}, prefix_length="
                            f"{prefix_length}, stride={stride}, "
                            f"start_offset={start_offset}"
                        ),
                    )
                ],
            )
        device_groups.append(device_group.name)
        block_local_addresses.extend(local_addresses)
        block_peer_addresses.extend(peer_addresses)

    return InterfacePlan(
        consumed_device_groups=tuple(group.name for group in bound.device_groups),
        address_blocks=tuple(
            InterfaceAddressBlockPlan(
                device_groups=tuple(device_groups),
                role=role,
                interface=interface,
                afi=afi,
                parent_network=parent_network,
                local_addresses=tuple(local_addresses),
                peer_addresses=tuple(peer_addresses),
                prefix_length=prefix_length,
                start_offset=start_offset,
            )
            for (
                interface,
                afi,
                parent_network,
            ), (
                device_groups,
                role,
                local_addresses,
                peer_addresses,
                prefix_length,
                start_offset,
                _stride,
            ) in grouped.items()
        ),
    )


def _bgp_role_family(role: str) -> str:
    if role == "uplink" or role.startswith("ebgp"):
        return "ebgp"
    if role.startswith("ibgp"):
        return "ibgp"
    return role


def _eos_bgpcpp_peer_plan(bound: BoundTopology) -> BgpPeerPlan:
    role_order = {"ebgp": 0, "ibgp": 1, "bgpmon": 2}
    group_order = {group.name: index for index, group in enumerate(bound.device_groups)}
    ordered_groups = sorted(
        bound.device_groups,
        key=lambda group: (
            0 if group.afi == "v6" else 1,
            role_order.get(_bgp_role_family(group.role), 3),
            group_order[group.name],
        ),
    )
    afi_ordinals: dict[str, int] = {}
    peers: list[BgpPeerPlanEntry] = []
    for device_group in ordered_groups:
        # Runtime-added peers (dut_neighbor_absent -- e.g. spec 2.4.4 addPeers) get
        # their IXIA session + DUT interface IP (via the interface plan) but NO
        # baseline DUT BGP neighbor -- skip them here so none is generated; the test
        # adds the neighbor live via the addPeers control-plane RPC.
        if device_group.dut_neighbor_absent:
            continue
        local_addresses, peer_addresses, _interface = _dut_peer_addresses(
            bound, device_group
        )
        if len(local_addresses) != len(peer_addresses):
            raise TopologyValidationError(
                bound.logical_topology.name,
                [
                    ValidationIssue(
                        path=f"device_groups.{device_group.name}.peers",
                        code="invalid_bgpcpp_peer_projection",
                        message=(
                            "BGP++ peer planning requires equal local and peer "
                            f"address counts, got {len(local_addresses)} and "
                            f"{len(peer_addresses)}"
                        ),
                    )
                ],
            )
        peer_group = device_group.peer_group
        peer_group_name = (
            peer_group.name if isinstance(peer_group, BgpPeerGroup) else peer_group
        )
        next_ordinal = afi_ordinals.get(device_group.afi, 0)
        for group_ordinal, (local_address, peer_address) in enumerate(
            zip(local_addresses, peer_addresses, strict=True)
        ):
            ordinal = next_ordinal + group_ordinal
            peers.append(
                BgpPeerPlanEntry(
                    device_group=device_group.name,
                    ordinal=ordinal,
                    afi=device_group.afi,
                    remote_asn=device_group.remote_asn,
                    local_address=local_address,
                    peer_address=peer_address,
                    peer_group_name=peer_group_name,
                    description=f"IXIA_{device_group.afi.upper()}_PEER_{ordinal + 1}",
                )
            )
        afi_ordinals[device_group.afi] = next_ordinal + len(local_addresses)

    return BgpPeerPlan(
        consumed_device_groups=tuple(group.name for group in bound.device_groups),
        peers=tuple(peers),
    )


def _bgpcpp_peer_configs(
    bound: BoundTopology,
    plan: BgpPeerPlan,
) -> list[dict[str, t.Any]]:
    if not plan.peers:
        raise TopologyValidationError(
            bound.logical_topology.name,
            [
                ValidationIssue(
                    path="device_plan.bgp_peer_plan.peers",
                    code="missing_bgpcpp_peer_projection",
                    message="BGP++ setup requires at least one compiled peer",
                )
            ],
        )
    issues = [
        ValidationIssue(
            path=f"device_groups.{peer.device_group}.peers[{peer.ordinal}]",
            code="incomplete_bgpcpp_peer_projection",
            message="BGP++ peer planning requires remote ASN and peer-group name",
        )
        for peer in plan.peers
        if peer.remote_asn is None or peer.peer_group_name is None
    ]
    if issues:
        raise TopologyValidationError(bound.logical_topology.name, issues)
    return [peer.bgpcpp_config() for peer in plan.peers]


def _characteristic_interface_ip_tasks(
    bound: BoundTopology,
    plan: InterfacePlan,
    hostname: str,
) -> list:
    if not plan.address_blocks:
        raise TopologyValidationError(
            bound.logical_topology.name,
            [
                ValidationIssue(
                    path="device_plan.interface_plan.address_blocks",
                    code="missing_interface_address_projection",
                    message="characteristic setup requires at least one address block",
                )
            ],
        )
    blocks_by_family: dict[str, dict[str, InterfaceAddressBlockPlan]] = {}
    for block in plan.address_blocks:
        family = _bgp_role_family(block.role)
        if family not in {"ebgp", "ibgp"}:
            continue
        afi_blocks = blocks_by_family.setdefault(family, {})
        if block.afi in afi_blocks:
            raise TopologyValidationError(
                bound.logical_topology.name,
                [
                    ValidationIssue(
                        path=f"device_plan.interface_plan.{family}.{block.afi}",
                        code="ambiguous_interface_address_projection",
                        message=(
                            f"characteristic rendering requires one {block.afi} "
                            f"address block for {family}"
                        ),
                    )
                ],
            )
        afi_blocks[block.afi] = block

    tasks = []
    for family in ("ebgp", "ibgp"):
        blocks = blocks_by_family.get(family, {})
        if not blocks:
            continue
        interfaces = {block.interface for block in blocks.values()}
        peer_counts = {len(block.local_addresses) for block in blocks.values()}
        if len(interfaces) != 1 or len(peer_counts) != 1:
            raise TopologyValidationError(
                bound.logical_topology.name,
                [
                    ValidationIssue(
                        path=f"device_plan.interface_plan.{family}",
                        code="invalid_interface_address_projection",
                        message=(
                            "dual-stack characteristic blocks must share one "
                            "interface and peer count"
                        ),
                    )
                ],
            )
        v4 = blocks.get("v4")
        v6 = blocks.get("v6")
        tasks.append(
            create_interface_ip_configuration_task(
                interface=next(iter(interfaces)),
                peer_count=next(iter(peer_counts)),
                ipv4_base_network=v4.parent_network if v4 is not None else None,
                ipv6_base_network=v6.parent_network if v6 is not None else None,
                address_families=[
                    afi
                    for afi, key in (("ipv6", "v6"), ("ipv4", "v4"))
                    if key in blocks
                ],
                clear_existing=True,
                ipv4_start_offset=(
                    v4.start_offset if v4 is not None else IXIA_IPV4_START_OFFSET
                ),
                ipv6_start_offset=(
                    v6.start_offset if v6 is not None else IXIA_IPV6_START_OFFSET
                ),
                hostname=hostname,
                ixia_needed=True,
            )
        )
    return tasks


def _eos_bgpcpp_policy_plan(bound: BoundTopology) -> BgpPolicyPlan:
    # Absence of group policy is still an explicit policy-planner decision.
    return BgpPolicyPlan(
        consumed_device_groups=tuple(group.name for group in bound.device_groups),
    )


def _eos_bgpcpp_ixia_plan(
    bound: BoundTopology,
    basic_port_configs: t.Iterable[t.Any],
    basic_traffic_item_configs: t.Iterable[t.Any],
) -> IxiaPlan:
    return IxiaPlan(
        consumed_device_groups=tuple(group.name for group in bound.device_groups),
        basic_port_configs=tuple(basic_port_configs),
        basic_traffic_item_configs=tuple(basic_traffic_item_configs),
    )


def _configured_interface_order(plan: InterfacePlan) -> tuple[str, ...]:
    role_order = {"ebgp": 0, "ibgp": 1, "bgpmon": 2}
    ordered_blocks = sorted(
        plan.address_blocks,
        key=lambda block: (
            role_order.get(_bgp_role_family(block.role), 3),
            0 if block.afi == "v6" else 1,
        ),
    )
    interfaces: list[str] = []
    for block in ordered_blocks:
        if block.interface not in interfaces:
            interfaces.append(block.interface)
    return tuple(interfaces)


_EOS_BGPCPP_TEARDOWN_PROFILES = frozenset(
    {
        _EBB_FULL_SCALE_PROFILE,
        _UG_NEW_PEER_JOIN_PROFILE,
        _IPV6_UPDATE_PACKING_PROFILE,
        _EGRESS_PEER_SCALE_PROFILE,
        _BOUNDED_ECMP_PROFILE,
    }
)


def _teardown_hostname(bound: BoundTopology) -> str:
    hostname = getattr(bound.physical_inventory, "device_name", None)
    if hostname:
        return hostname
    raise TopologyValidationError(
        bound.logical_topology.name,
        [
            ValidationIssue(
                path="device_plan.teardown_plan",
                code="missing_teardown_input",
                message="EOS teardown requires device_name",
            )
        ],
    )


def _openr_teardown_tasks(
    bound: BoundTopology,
    openr_inputs: _EosBgpCppOpenRInputs,
) -> OpenRStandaloneTeardownTasks | None:
    if openr_inputs.mode is not OpenRMode.STANDALONE:
        return None
    standalone_link = openr_inputs.standalone_link
    if standalone_link is None:
        raise TopologyValidationError(
            bound.logical_topology.name,
            [
                ValidationIssue(
                    path="device_plan.teardown_plan.openr_standalone_link",
                    code="missing_teardown_input",
                    message="standalone OpenR teardown requires its link intent",
                )
            ],
        )
    return get_openr_standalone_teardown_tasks(standalone_link)


def _enabled_teardown_components(
    bound: BoundTopology,
    component_runtime_plan: MetaComponentRuntimePlan | None,
    openr_mode: OpenRMode,
) -> tuple[str, ...]:
    if bound.logical_topology.legacy_profile == _EBB_FULL_SCALE_PROFILE:
        if component_runtime_plan is None:
            raise TopologyValidationError(
                bound.logical_topology.name,
                [
                    ValidationIssue(
                        path="device_plan.teardown_plan.component_runtime_plan",
                        code="missing_teardown_input",
                        message=(
                            "full-scale EOS teardown requires its component "
                            "runtime plan"
                        ),
                    )
                ],
            )
        return tuple(
            component.name
            for component in component_runtime_plan.components
            if component.enabled
        )
    # Characteristic setup starts EOS Openr only for PEER mode. STANDALONE
    # configures its separately owned link feature without starting the daemon.
    return tuple(
        daemon
        for daemon in BGPCPP_DAEMONS
        if daemon != "Openr" or openr_mode is OpenRMode.PEER
    )


def _teardown_cleanup_task(hostname: str) -> t.Any:
    return create_run_commands_on_shell_task(
        hostname=hostname,
        cmds=[
            "bash sudo rm -f /etc/openr_config /mnt/flash/openr_config",
            "bash sudo rm -f /tmp/experiment_peers.json /tmp/peers.b64",
            "bash sudo iptables -F EOS_BGP 2>/dev/null || true",
            "bash sudo ip6tables -F EOS_BGP 2>/dev/null || true",
        ],
        set_outer_hostname=True,
        ixia_needed=True,
    )


def _eos_bgpcpp_teardown_plan(
    bound: BoundTopology,
    interface_plan: InterfacePlan,
    component_runtime_plan: MetaComponentRuntimePlan | None,
    openr_inputs: _EosBgpCppOpenRInputs,
) -> TeardownPlan:
    if (
        bound.logical_topology.legacy_profile not in _EOS_BGPCPP_TEARDOWN_PROFILES
        or _primary_dut_endpoint(bound).setup_mode != "full"
    ):
        return TeardownPlan(tasks=())

    hostname = _teardown_hostname(bound)
    openr_tasks = _openr_teardown_tasks(bound, openr_inputs)
    tasks = [] if openr_tasks is None else [openr_tasks.route_withdrawal]
    enabled_components = _enabled_teardown_components(
        bound,
        component_runtime_plan,
        openr_inputs.mode,
    )
    for component_name in reversed(enabled_components):
        tasks.append(
            create_arista_daemon_control_task(
                hostname=hostname,
                daemon_name=component_name,
                action="disable",
                ixia_needed=True,
            )
        )

    configured_interfaces = _configured_interface_order(interface_plan)
    for interface in reversed(configured_interfaces):
        tasks.append(
            create_interface_ip_cleanup_task(
                interfaces=[interface],
                restore_from_backup=True,
                hostname=hostname,
            )
        )

    if openr_tasks is not None:
        tasks.extend(openr_tasks.link_cleanup)
    tasks.append(_teardown_cleanup_task(hostname))
    return TeardownPlan(
        tasks=tuple(tasks),
        restored_interfaces=tuple(reversed(configured_interfaces)),
        disabled_components=tuple(reversed(enabled_components)),
    )


class TopologyCompiler:
    def compile(self, bound: BoundTopology) -> CompiledTaacArtifacts:
        _validate_bound_provenance_for_compile(bound)
        _validate_route_attributes_for_compile(bound)
        return CompiledTaacArtifacts(
            endpoints=self.build_endpoints(bound),
            host_os_type_map=self.build_host_os_type_map(bound),
            setup_tasks=self.build_setup_tasks(bound),
            teardown_tasks=self.build_teardown_tasks(bound),
            basic_port_configs=self.build_basic_port_configs(bound),
            basic_traffic_item_configs=self.build_basic_traffic_item_configs(bound),
        )

    def build_endpoints(self, bound: BoundTopology) -> list:
        return []

    def build_host_os_type_map(self, bound: BoundTopology) -> dict[str, str]:
        return dict(bound.endpoint_os)

    def build_setup_tasks(self, bound: BoundTopology) -> list:
        return []

    def build_teardown_tasks(self, bound: BoundTopology) -> list:
        return []

    def build_basic_port_configs(self, bound: BoundTopology) -> list:
        return []

    def build_basic_traffic_item_configs(self, bound: BoundTopology) -> list:
        return []


class EosBgpCppCompiler(TopologyCompiler):
    """EOS BGP++ compiler with a typed device-plan rendering boundary."""

    def compile(self, bound: BoundTopology) -> CompiledTaacArtifacts:
        return self.build_device_plan(bound).render()

    def build_device_plan(self, bound: BoundTopology) -> EosBgpCppDevicePlan:
        _validate_bound_provenance_for_compile(bound)
        _validate_route_attributes_for_compile(bound)
        openr = _eos_bgpcpp_openr_inputs(bound)
        endpoints = self.build_endpoints(bound)
        host_os_type_map = self.build_host_os_type_map(bound)
        interface_plan = _eos_bgpcpp_interface_plan(bound)
        bgp_peer_plan = _eos_bgpcpp_peer_plan(bound)
        bgp_policy_plan = _eos_bgpcpp_policy_plan(bound)
        component_runtime_plan = self.build_component_runtime_plan(bound)
        setup_phases = list(
            self.build_setup_phases(
                bound,
                component_runtime_plan=component_runtime_plan,
            )
        )

        if (
            _primary_dut_endpoint(bound).setup_mode == "full"
            and openr.mode is OpenRMode.STANDALONE
        ):
            assert openr.standalone_link is not None
            helper_name = openr.standalone_link.helper.hostname
            existing_endpoint_names = {endpoint.name for endpoint in endpoints}
            if (
                helper_name in existing_endpoint_names
                or helper_name in host_os_type_map
            ):
                raise TopologyValidationError(
                    bound.logical_topology.name,
                    [
                        ValidationIssue(
                            path="device_config.openr_standalone_link.helper.hostname",
                            code="openr_helper_endpoint_collision",
                            message=(
                                "OpenR standalone helper must not collide with an "
                                f"existing compiled endpoint; got {helper_name!r}"
                            ),
                        )
                    ],
                )
        if (
            _primary_dut_endpoint(bound).setup_mode == "full"
            and bound.logical_topology.legacy_profile != _EBB_FULL_SCALE_PROFILE
        ):
            setup_phases.append(
                EosBgpCppSetupPhase(
                    owner=EosBgpCppSetupPhaseOwner.OPENR_FEATURE,
                    tasks=tuple(_eos_bgpcpp_openr_setup_tasks(openr)),
                )
            )

        device_groups = tuple(group.name for group in bound.device_groups)
        return EosBgpCppDevicePlan(
            logical_topology_name=bound.logical_topology.name,
            device_groups=device_groups,
            endpoint_plan=EosEndpointPlan(
                endpoints=tuple(endpoints),
                host_os_type_map=host_os_type_map,
            ),
            interface_plan=interface_plan,
            bgp_peer_plan=bgp_peer_plan,
            bgp_policy_plan=bgp_policy_plan,
            component_runtime_plan=component_runtime_plan,
            setup_phases=tuple(setup_phases),
            ixia_plan=_eos_bgpcpp_ixia_plan(
                bound,
                self.build_basic_port_configs(bound),
                self.build_basic_traffic_item_configs(bound),
            ),
            openr_feature_plan=OpenRFeaturePlan(mode=openr.mode),
            teardown_plan=self.build_teardown_plan(
                bound,
                interface_plan=interface_plan,
                component_runtime_plan=component_runtime_plan,
                openr_inputs=openr,
            ),
        )

    def build_component_runtime_plan(
        self,
        bound: BoundTopology,
    ) -> MetaComponentRuntimePlan | None:
        if (
            bound.logical_topology.legacy_profile != _EBB_FULL_SCALE_PROFILE
            or not _should_delegate_ebb_full_scale(bound)
        ):
            return None
        return _ebb_component_runtime_plan(
            bound,
            _ebb_full_scale_setup_args(bound),
            _eos_bgpcpp_openr_inputs(bound),
        )

    def build_teardown_plan(
        self,
        bound: BoundTopology,
        *,
        interface_plan: InterfacePlan | None = None,
        component_runtime_plan: MetaComponentRuntimePlan | None = None,
        openr_inputs: _EosBgpCppOpenRInputs | None = None,
    ) -> TeardownPlan:
        resolved_interface_plan = (
            _eos_bgpcpp_interface_plan(bound)
            if interface_plan is None
            else interface_plan
        )
        resolved_component_runtime_plan = (
            self.build_component_runtime_plan(bound)
            if component_runtime_plan is None
            else component_runtime_plan
        )
        resolved_openr_inputs = (
            _eos_bgpcpp_openr_inputs(bound) if openr_inputs is None else openr_inputs
        )
        return _eos_bgpcpp_teardown_plan(
            bound,
            resolved_interface_plan,
            resolved_component_runtime_plan,
            resolved_openr_inputs,
        )

    def build_endpoints(self, bound: BoundTopology) -> list:
        if _is_bounded_ecmp(bound):
            return [_bounded_ecmp_endpoint(_bounded_ecmp_args(bound))]
        if _is_egress_peer_scale(bound):
            return [_egress_peer_scale_endpoint(_egress_peer_scale_args(bound))]
        if _is_ipv6_update_packing(bound):
            return [_ipv6_update_packing_endpoint(_ipv6_update_packing_args(bound))]
        if _is_ug_new_peer_join(bound):
            return [_ug_new_peer_join_endpoint(_ug_new_peer_join_args(bound))]
        if bound.logical_topology.legacy_profile != _EBB_FULL_SCALE_PROFILE:
            return super().build_endpoints(bound)

        setup_mode = _ebb_setup_mode(bound)
        _validate_ebb_full_scale_shape(bound)
        device_name = _ebb_device_name(bound)
        if setup_mode == "verify_only":
            return [taac_types.Endpoint(name=device_name, dut=True)]

        connections = _ebb_full_scale_ixia_connections(bound)
        ixia_chassis_ip = _ebb_ixia_chassis(bound)
        endpoints = [
            taac_types.Endpoint(
                name=device_name,
                dut=True,
                ixia_ports=[connection.interface for connection in connections],
                direct_ixia_connections=[
                    taac_types.DirectIxiaConnection(
                        interface=connection.interface,
                        ixia_chassis_ip=ixia_chassis_ip,
                        ixia_port=connection.ixia_port,
                    )
                    for connection in connections
                ],
            )
        ]
        return endpoints

    def build_host_os_type_map(self, bound: BoundTopology) -> dict[str, t.Any]:
        if _is_bounded_ecmp(bound):
            args = _bounded_ecmp_args(bound)
            return {args.device_name: taac_types.DeviceOsType.ARISTA_FBOSS}
        if _is_egress_peer_scale(bound):
            args = _egress_peer_scale_args(bound)
            return {args.device_name: taac_types.DeviceOsType.ARISTA_FBOSS}
        if _is_ipv6_update_packing(bound):
            args = _ipv6_update_packing_args(bound)
            return {args.device_name: taac_types.DeviceOsType.ARISTA_FBOSS}
        if _is_ug_new_peer_join(bound):
            args = _ug_new_peer_join_args(bound)
            return {args.device_name: taac_types.DeviceOsType.ARISTA_FBOSS}
        if bound.logical_topology.legacy_profile != _EBB_FULL_SCALE_PROFILE:
            return super().build_host_os_type_map(bound)

        _ebb_setup_mode(bound)
        _validate_ebb_full_scale_shape(bound)
        host_os_type_map = {
            _ebb_device_name(bound): taac_types.DeviceOsType.ARISTA_FBOSS
        }
        return host_os_type_map

    def build_setup_tasks(self, bound: BoundTopology) -> list:
        component_runtime_plan = self.build_component_runtime_plan(bound)
        return [
            task
            for phase in self.build_setup_phases(
                bound,
                component_runtime_plan=component_runtime_plan,
            )
            for task in phase.tasks
        ]

    def build_setup_phases(
        self,
        bound: BoundTopology,
        *,
        component_runtime_plan: MetaComponentRuntimePlan | None,
    ) -> tuple[EosBgpCppSetupPhase, ...]:
        if _is_bounded_ecmp(bound):
            if _primary_dut_endpoint(bound).setup_mode in _EBB_NO_SETUP_MODES:
                return ()
            return _bounded_ecmp_setup_phases(
                bound,
                _bounded_ecmp_args(bound),
            )
        if _is_egress_peer_scale(bound):
            return _egress_peer_scale_setup_phases(
                bound,
                _egress_peer_scale_args(bound),
            )
        if _is_ipv6_update_packing(bound):
            if _primary_dut_endpoint(bound).setup_mode in _EBB_NO_SETUP_MODES:
                return ()
            return _ipv6_update_packing_setup_phases(
                bound,
                _ipv6_update_packing_args(bound),
            )
        if _is_ug_new_peer_join(bound):
            return _ug_new_peer_join_setup_phases(
                bound,
                _ug_new_peer_join_args(bound),
            )
        if bound.logical_topology.legacy_profile != _EBB_FULL_SCALE_PROFILE:
            tasks = super().build_setup_tasks(bound)
            return (
                (
                    EosBgpCppSetupPhase(
                        owner=EosBgpCppSetupPhaseOwner.LEGACY_COMPATIBILITY,
                        tasks=tuple(tasks),
                    ),
                )
                if tasks
                else ()
            )
        if not _should_delegate_ebb_full_scale(bound):
            return ()

        args = _ebb_full_scale_setup_args(bound)
        openr_inputs = _eos_bgpcpp_openr_inputs(bound)
        native_pre_ixia_tasks = _ebb_full_scale_pre_ixia_setup_tasks(args.interfaces)
        if component_runtime_plan is None:
            raise TopologyValidationError(
                bound.logical_topology.name,
                [
                    ValidationIssue(
                        path="device_plan.component_runtime_plan",
                        code="missing_component_runtime_projection",
                        message="delegated EBB setup requires its component runtime plan",
                    )
                ],
            )
        deployment_tasks = EosDaemonComponentDeployer().build_tasks(
            component_runtime_plan
        )
        native_openr_config_tasks = _eos_bgpcpp_openr_config_tasks(openr_inputs)
        native_interface_plan = _eos_bgpcpp_interface_plan(bound)
        native_interface_ip_config_tasks = _ebb_full_scale_interface_ip_config_tasks(
            bound, native_interface_plan, args.interfaces
        )
        native_setup_tail_tasks = _ebb_full_scale_setup_tail_tasks(args)
        openr_tail_tasks = _eos_bgpcpp_openr_tail_tasks(openr_inputs)
        route_mutation_task = create_invoke_ixia_api_task(
            api_name="configure_formulaic_bgp_routes",
            args_dict={"mutations": _ebb_route_mutations(bound)},
        )
        return (
            EosBgpCppSetupPhase(
                owner=EosBgpCppSetupPhaseOwner.HOST_PREPARATION,
                tasks=tuple(native_pre_ixia_tasks),
            ),
            EosBgpCppSetupPhase(
                owner=EosBgpCppSetupPhaseOwner.IXIA_CONFIGURATION,
                tasks=(route_mutation_task,),
            ),
            EosBgpCppSetupPhase(
                owner=EosBgpCppSetupPhaseOwner.COMPONENT_CONFIGURATION,
                tasks=deployment_tasks.configuration_tasks,
            ),
            EosBgpCppSetupPhase(
                owner=EosBgpCppSetupPhaseOwner.OPENR_CONFIGURATION,
                tasks=tuple(native_openr_config_tasks),
            ),
            EosBgpCppSetupPhase(
                owner=EosBgpCppSetupPhaseOwner.COMPONENT_STARTUP,
                tasks=deployment_tasks.startup_tasks,
            ),
            EosBgpCppSetupPhase(
                owner=EosBgpCppSetupPhaseOwner.INTERFACE_CONFIGURATION,
                tasks=tuple(native_interface_ip_config_tasks),
            ),
            EosBgpCppSetupPhase(
                owner=EosBgpCppSetupPhaseOwner.OPENR_FEATURE,
                tasks=tuple(openr_tail_tasks),
            ),
            EosBgpCppSetupPhase(
                owner=EosBgpCppSetupPhaseOwner.HOST_FINALIZATION,
                tasks=tuple(native_setup_tail_tasks),
            ),
        )

    def build_teardown_tasks(self, bound: BoundTopology) -> list:
        return list(self.build_teardown_plan(bound).tasks)

    def build_basic_port_configs(self, bound: BoundTopology) -> list:
        if _is_bounded_ecmp(bound):
            args = _bounded_ecmp_args(bound)
            return _bounded_ecmp_basic_port_configs(bound, args)
        if _is_egress_peer_scale(bound):
            args = _egress_peer_scale_args(bound)
            return _egress_peer_scale_basic_port_configs(bound, args)
        if _is_ipv6_update_packing(bound):
            args = _ipv6_update_packing_args(bound)
            return _ipv6_update_packing_basic_port_configs(bound, args)
        if _is_ug_new_peer_join(bound):
            args = _ug_new_peer_join_args(bound)
            return _ug_new_peer_join_basic_port_configs(bound, args)
        if bound.logical_topology.legacy_profile != _EBB_FULL_SCALE_PROFILE:
            return super().build_basic_port_configs(bound)
        if _ebb_setup_mode(bound) == "verify_only":
            return []
        if _has_ebb_partitions(bound):
            return _ebb_partitioned_basic_port_configs(bound)

        args = _ebb_full_scale_ixia_args(bound)
        return _ebb_full_scale_basic_port_configs(bound, args)


class FbossCoopCompiler(TopologyCompiler):
    """FBOSS compiler shell.

    Phase 1 only proves compiler selection and the flat artifact facade. Real
    FBOSS COOP emission starts after the EBB BGP++ migration path is proven.
    """


def select_topology_compiler(bound: BoundTopology) -> TopologyCompiler:
    primary_dut_os = _primary_dut_os(bound)
    key = CompilerKey(
        endpoint_os=primary_dut_os,
        routing_driver=_primary_routing_driver(bound, primary_dut_os),
    )
    if key == CompilerKey(endpoint_os="eos", routing_driver="bgpcpp"):
        return EosBgpCppCompiler()
    if key == CompilerKey(endpoint_os="fboss", routing_driver="fboss"):
        return FbossCoopCompiler()
    raise TopologyValidationError(
        bound.logical_topology.name,
        [
            ValidationIssue(
                path="compiler_key",
                code="unknown_compiler_key",
                message=(
                    "no TAAC topology compiler registered for "
                    f"endpoint_os={key.endpoint_os!r}, "
                    f"routing_driver={key.routing_driver!r}"
                ),
            )
        ],
    )


def _primary_dut_os(bound: BoundTopology) -> str:
    primary_dut = _primary_dut_endpoint(bound)
    if primary_dut.name in bound.endpoint_os:
        return bound.endpoint_os[primary_dut.name]
    raise TopologyValidationError(
        bound.logical_topology.name,
        [
            ValidationIssue(
                path=f"endpoint_os.{primary_dut.name}",
                code="missing_primary_dut_os",
                message=(
                    "could not resolve the primary DUT backend for endpoint "
                    f"{primary_dut.name!r}"
                ),
            )
        ],
    )


def _primary_dut_endpoint(bound: BoundTopology) -> EndpointSpec:
    dut_endpoints = [
        endpoint
        for endpoint in bound.logical_topology.endpoints
        if _endpoint_is_dut(endpoint)
    ]
    if len(dut_endpoints) == 1:
        return dut_endpoints[0]
    if len(dut_endpoints) > 1:
        raise TopologyValidationError(
            bound.logical_topology.name,
            [
                ValidationIssue(
                    path="logical_topology.endpoints",
                    code="multiple_primary_dut_endpoints",
                    message=(
                        "Phase 1 compiler selection requires exactly one DUT "
                        f"endpoint; found {[endpoint.name for endpoint in dut_endpoints]}"
                    ),
                )
            ],
        )
    raise TopologyValidationError(
        bound.logical_topology.name,
        [
            ValidationIssue(
                path="logical_topology.endpoints",
                code="missing_primary_dut_endpoint",
                message="could not find a primary DUT endpoint",
            )
        ],
    )


def _primary_routing_driver(bound: BoundTopology, dut_os: str) -> str:
    drivers: set[str] = set()
    for device_group in bound.device_groups:
        driver = _normalize_routing_driver(device_group.routing_driver)
        if driver is not None:
            drivers.add(driver)
    if len(drivers) == 1:
        return next(iter(drivers))
    if len(drivers) > 1:
        raise TopologyValidationError(
            bound.logical_topology.name,
            [
                ValidationIssue(
                    path="device_groups",
                    code="mixed_routing_drivers",
                    message=(
                        "Phase 1 single-DUT topologies require one routing "
                        f"driver, got {sorted(drivers)}"
                    ),
                )
            ],
        )

    if dut_os == "eos":
        return "bgpcpp"
    if dut_os == "fboss":
        return "fboss"
    raise TopologyValidationError(
        bound.logical_topology.name,
        [
            ValidationIssue(
                path="device_groups",
                code="missing_routing_driver",
                message=f"no default routing driver for backend {dut_os!r}",
            )
        ],
    )


def _normalize_routing_driver(driver: str | None) -> str | None:
    if driver in {"bgp++", "bgpcpp"}:
        return "bgpcpp"
    return driver


def _endpoint_is_dut(endpoint) -> bool:
    return endpoint.role == "dut" or (
        endpoint.kind == "dut" and endpoint.role not in _TRAFFIC_ENDPOINT_ROLES
    )


def _ebb_setup_mode(bound: BoundTopology) -> str:
    dut_endpoint = _primary_dut_endpoint(bound)
    if dut_endpoint.setup_mode in {"full", *_EBB_NO_SETUP_MODES}:
        return dut_endpoint.setup_mode
    raise TopologyValidationError(
        bound.logical_topology.name,
        [
            ValidationIssue(
                path=f"endpoints.{dut_endpoint.name}.setup_mode",
                code="unsupported_ebb_setup_mode",
                message=(
                    "delegated EBB full-scale artifacts support setup_mode='full', "
                    "'skip', or 'verify_only'; "
                    f"got {dut_endpoint.setup_mode!r}"
                ),
            )
        ],
    )


def _ebb_device_name(bound: BoundTopology) -> str:
    device_name = getattr(bound.physical_inventory, "device_name", None)
    if device_name:
        return device_name
    raise TopologyValidationError(
        bound.logical_topology.name,
        [
            ValidationIssue(
                path="physical_inventory.device_name",
                code="missing_ebb_compiler_input",
                message="delegated EBB full-scale artifacts require a DUT device name",
            )
        ],
    )


def _ebb_ixia_chassis(bound: BoundTopology) -> str:
    chassis = getattr(bound.physical_inventory, "ixia_chassis_ip", None)
    if chassis:
        return t.cast(str, chassis)
    raise TopologyValidationError(
        bound.logical_topology.name,
        [
            ValidationIssue(
                path="physical_inventory.ixia_chassis_ip",
                code="missing_ebb_ixia_input",
                message="EBB full-scale IXIA wiring requires a nonempty chassis",
            )
        ],
    )


def _ebb_full_scale_ixia_connections(
    bound: BoundTopology,
) -> list[_EbbIxiaConnection]:
    _validate_ebb_full_scale_shape(bound)
    issues: list[ValidationIssue] = []
    chassis = getattr(bound.physical_inventory, "ixia_chassis_ip", None)
    if not chassis:
        issues.append(
            ValidationIssue(
                path="physical_inventory.ixia_chassis_ip",
                code="missing_ebb_ixia_input",
                message="EBB full-scale IXIA wiring requires a nonempty chassis",
            )
        )

    role_groups = (
        (
            "ebgp",
            [
                device_group
                for device_group in bound.device_groups
                if _device_group_base_role(device_group) in {"ebgp", "uplink"}
            ],
        ),
        (
            "ibgp",
            [
                device_group
                for device_group in bound.device_groups
                if _device_group_base_role(device_group) == "ibgp"
            ],
        ),
        (
            "bgpmon",
            [
                device_group
                for device_group in bound.device_groups
                if _device_group_base_role(device_group) == "bgpmon"
            ],
        ),
    )
    connections: list[_EbbIxiaConnection] = []
    for role, device_groups in role_groups:
        if role == "bgpmon" and not device_groups:
            continue
        connection = _ebb_ixia_connection_for_role(bound, role, device_groups, issues)
        if connection is not None:
            connections.append(connection)

    interfaces = [connection.interface for connection in connections]
    ixia_ports = [connection.ixia_port for connection in connections]
    if len(set(interfaces)) != len(interfaces) or len(set(ixia_ports)) != len(
        ixia_ports
    ):
        issues.append(
            ValidationIssue(
                path="device_groups",
                code="reused_ebb_ixia_connection",
                message=(
                    "EBB full-scale eBGP, iBGP, and BGP-MON roles must use "
                    "distinct DUT interfaces and IXIA ports; "
                    f"got interfaces={interfaces}, ixia_ports={ixia_ports}"
                ),
            )
        )

    if issues:
        raise TopologyValidationError(bound.logical_topology.name, issues)
    return connections


def _ebb_ixia_connection_for_role(
    bound: BoundTopology,
    role: str,
    device_groups: list[BoundDeviceGroup],
    issues: list[ValidationIssue],
) -> _EbbIxiaConnection | None:
    pairs: set[tuple[str, str]] = set()
    interfaces: set[str] = set()
    for device_group in device_groups:
        assignment = device_group.port_assignment
        if assignment is None:
            issues.append(
                ValidationIssue(
                    path=f"device_groups.{device_group.name}.port_assignment",
                    code="missing_resolved_ixia_port_assignment",
                    message="IXIA lowering requires a resolved port assignment",
                )
            )
            continue
        interfaces.add(assignment.dut_interface)
        pairs.add((assignment.dut_interface, assignment.ixia_port))

    if not pairs:
        issues.append(
            ValidationIssue(
                path=f"device_groups.{role}.ixia_connection",
                code="missing_ebb_ixia_connection",
                message=(
                    f"every EBB full-scale {role} device group must resolve one "
                    "nonempty DUT interface and IXIA port"
                ),
            )
        )
        return None
    if len(pairs) != 1:
        issues.append(
            ValidationIssue(
                path=f"device_groups.{role}.ixia_connection",
                code="ambiguous_ebb_ixia_connection",
                message=(
                    f"all EBB full-scale {role} device groups must share one "
                    f"DUT interface/IXIA port pair; got {sorted(pairs)}"
                ),
            )
        )
        if len(interfaces) > 1:
            issues.append(
                ValidationIssue(
                    path=f"device_groups.{role}.interface",
                    code="ambiguous_ebb_dut_interface",
                    message=(
                        f"delegated EBB full-scale tasks require one {role} DUT "
                        f"interface, got {sorted(interfaces)}"
                    ),
                )
            )
        return None

    interface, ixia_port = next(iter(pairs))
    return _EbbIxiaConnection(
        role=role,
        interface=interface,
        ixia_port=ixia_port,
    )


def _ebb_full_scale_ixia_args(bound: BoundTopology) -> _EbbFullScaleIxiaArgs:
    _validate_ebb_full_scale_shape(bound)
    connections = {
        connection.role: connection
        for connection in _ebb_full_scale_ixia_connections(bound)
    }
    groups = {
        (device_group.role, device_group.afi): device_group
        for device_group in bound.device_groups
    }
    issues: list[ValidationIssue] = []
    for device_group in bound.device_groups:
        if not device_group.parent_network:
            issues.append(
                ValidationIssue(
                    path=f"device_groups.{device_group.name}.parent_network",
                    code="missing_ebb_ixia_input",
                    message=(
                        "canonical EBB full-scale IXIA mapping requires a bound "
                        f"parent network for {device_group.name!r}"
                    ),
                )
            )

    ebgp_remote_asn = _ebb_remote_asn(
        "ebgp",
        [
            device_group
            for device_group in bound.device_groups
            if device_group.role == "uplink"
        ],
        issues,
    )
    ibgp_remote_asn = _ebb_remote_asn(
        "ibgp",
        [
            device_group
            for device_group in bound.device_groups
            if _device_group_base_role(device_group) == "ibgp"
        ],
        issues,
    )
    bgpmon_groups = [
        device_group
        for device_group in bound.device_groups
        if device_group.role == "bgpmon"
    ]
    bgpmon_remote_asn = (
        _ebb_remote_asn("bgpmon", bgpmon_groups, issues) if bgpmon_groups else None
    )

    if issues:
        raise TopologyValidationError(bound.logical_topology.name, issues)

    assert ebgp_remote_asn is not None
    assert ibgp_remote_asn is not None
    return _EbbFullScaleIxiaArgs(
        interfaces=_EbbFullScaleInterfaces(
            device_name=_ebb_device_name(bound),
            ebgp=connections["ebgp"].interface,
            ibgp=connections["ibgp"].interface,
            bgpmon=(
                connections["bgpmon"].interface if "bgpmon" in connections else None
            ),
            include_bgpmon="bgpmon" in connections,
        ),
        groups=groups,
        ebgp_remote_asn=ebgp_remote_asn,
        ibgp_remote_asn=ibgp_remote_asn,
        bgpmon_remote_asn=bgpmon_remote_asn,
    )


def _ebb_remote_asn(
    role: str,
    device_groups: list[BoundDeviceGroup],
    issues: list[ValidationIssue],
) -> int | None:
    remote_asns = {
        device_group.remote_asn
        for device_group in device_groups
        if device_group.remote_asn is not None
    }
    if any(device_group.remote_asn is None for device_group in device_groups):
        issues.append(
            ValidationIssue(
                path=f"device_groups.{role}.remote_asn",
                code="missing_ebb_ixia_input",
                message=(
                    f"every canonical EBB full-scale {role} device group requires "
                    "a bound remote ASN"
                ),
            )
        )
    if len(remote_asns) > 1:
        issues.append(
            ValidationIssue(
                path=f"device_groups.{role}.remote_asn",
                code="inconsistent_ebb_remote_asn",
                message=(
                    f"canonical EBB full-scale {role} device groups must share "
                    f"one remote ASN; got {sorted(remote_asns)}"
                ),
            )
        )
    return next(iter(remote_asns)) if len(remote_asns) == 1 else None


def _ebb_full_scale_setup_args(bound: BoundTopology) -> _EbbFullScaleSetupArgs:
    interfaces = _ebb_full_scale_interfaces(bound)
    issues: list[ValidationIssue] = []
    physical_inventory = bound.physical_inventory
    if physical_inventory is None:
        issues.append(
            ValidationIssue(
                path="physical_inventory",
                code="missing_ebb_compiler_input",
                message="delegated EBB full-scale setup requires a bound PhysicalInventory",
            )
        )

    device_config = bound.device_config
    if device_config is None:
        issues.append(
            ValidationIssue(
                path="device_config",
                code="missing_ebb_compiler_input",
                message="delegated EBB full-scale setup requires device config",
            )
        )

    bgp_asn = getattr(physical_inventory, "dut_bgp_as", None)
    if bgp_asn is None:
        issues.append(
            ValidationIssue(
                path="physical_inventory.dut_bgp_as",
                code="missing_ebb_compiler_input",
                message="delegated EBB full-scale setup requires the DUT BGP AS",
            )
        )
    bgpcpp_configerator_path = getattr(
        physical_inventory, "bgpcpp_configerator_path", None
    )
    if not bgpcpp_configerator_path:
        issues.append(
            ValidationIssue(
                path="physical_inventory.bgpcpp_configerator_path",
                code="missing_ebb_compiler_input",
                message=(
                    "delegated EBB full-scale setup requires the BGP++ "
                    "configerator path"
                ),
            )
        )

    if issues:
        raise TopologyValidationError(bound.logical_topology.name, issues)

    assert physical_inventory is not None
    assert device_config is not None
    assert bgp_asn is not None
    assert bgpcpp_configerator_path

    return _EbbFullScaleSetupArgs(
        interfaces=interfaces,
        bgp_asn=bgp_asn,
        bgpcpp_configerator_path=bgpcpp_configerator_path,
        enable_update_group=device_config.update_group_enable,
    )


def _ebb_full_scale_interfaces(bound: BoundTopology) -> _EbbFullScaleInterfaces:
    _validate_ebb_full_scale_shape(bound)
    issues: list[ValidationIssue] = []
    physical_inventory = bound.physical_inventory
    device_name = getattr(physical_inventory, "device_name", None)
    if not device_name:
        issues.append(
            ValidationIssue(
                path="physical_inventory.device_name",
                code="missing_ebb_compiler_input",
                message="delegated EBB full-scale tasks require the DUT device name",
            )
        )

    ebgp_groups = [
        dg
        for dg in bound.device_groups
        if _device_group_base_role(dg) in {"ebgp", "uplink"}
    ]
    ibgp_groups = [
        dg for dg in bound.device_groups if _device_group_base_role(dg) == "ibgp"
    ]
    bgpmon_groups = [
        dg for dg in bound.device_groups if _device_group_base_role(dg) == "bgpmon"
    ]

    ebgp = _unique_dut_interface(bound, "ebgp", ebgp_groups, True, issues)
    ibgp = _unique_dut_interface(bound, "ibgp", ibgp_groups, True, issues)
    include_bgpmon = bool(bgpmon_groups)
    bgpmon = _unique_dut_interface(
        bound, "bgpmon", bgpmon_groups, include_bgpmon, issues
    )

    if issues:
        raise TopologyValidationError(bound.logical_topology.name, issues)

    assert device_name
    assert ebgp is not None
    assert ibgp is not None
    return _EbbFullScaleInterfaces(
        device_name=device_name,
        ebgp=ebgp,
        ibgp=ibgp,
        bgpmon=bgpmon,
        include_bgpmon=include_bgpmon,
    )


def _unique_dut_interface(
    bound: BoundTopology,
    role: str,
    device_groups: list[BoundDeviceGroup],
    required: bool,
    issues: list[ValidationIssue],
) -> str | None:
    interfaces = set()
    for device_group in device_groups:
        assignment = device_group.port_assignment
        if assignment is None:
            issues.append(
                ValidationIssue(
                    path=f"device_groups.{device_group.name}.port_assignment",
                    code="missing_resolved_ixia_port_assignment",
                    message="IXIA lowering requires a resolved port assignment",
                )
            )
            continue
        interfaces.add(assignment.dut_interface)
    if not interfaces:
        if required:
            issues.append(
                ValidationIssue(
                    path=f"device_groups.{role}.interface",
                    code="missing_ebb_dut_interface",
                    message=(
                        f"delegated EBB full-scale tasks require one resolved {role} "
                        "DUT interface"
                    ),
                )
            )
        return None
    if len(interfaces) > 1:
        issues.append(
            ValidationIssue(
                path=f"device_groups.{role}.interface",
                code="ambiguous_ebb_dut_interface",
                message=(
                    f"delegated EBB full-scale tasks require one {role} DUT "
                    f"interface, got {sorted(interfaces)}"
                ),
            )
        )
        return None
    return next(iter(interfaces))


def _device_group_base_role(device_group: BoundDeviceGroup) -> str:
    return device_group.role.split("_", 1)[0]


def _has_ebb_partitions(bound: BoundTopology) -> bool:
    return any(
        device_group.partition is not None for device_group in bound.device_groups
    )


def _should_delegate_ebb_full_scale(bound: BoundTopology) -> bool:
    dut_endpoint = _primary_dut_endpoint(bound)
    if dut_endpoint.setup_mode == "full":
        return True
    if dut_endpoint.setup_mode in _EBB_NO_SETUP_MODES:
        return False
    raise TopologyValidationError(
        bound.logical_topology.name,
        [
            ValidationIssue(
                path=f"endpoints.{dut_endpoint.name}.setup_mode",
                code="unsupported_ebb_setup_mode",
                message=(
                    "delegated EBB full-scale tasks support setup_mode='full', "
                    "'skip', or 'verify_only'; "
                    f"got {dut_endpoint.setup_mode!r}"
                ),
            )
        ],
    )


def _validate_ebb_full_scale_shape(  # noqa: C901
    bound: BoundTopology,
) -> None:
    allowed_counts = {
        **_EBB_REQUIRED_ROLE_AFI_COUNTS,
        **_EBB_OPTIONAL_ROLE_AFI_COUNTS,
    }
    groups_by_role_afi: dict[tuple[str, str], list[tuple[int, BoundDeviceGroup]]] = {}
    for index, device_group in enumerate(bound.device_groups):
        groups_by_role_afi.setdefault((device_group.role, device_group.afi), []).append(
            (index, device_group)
        )

    issues: list[ValidationIssue] = []
    for role_afi, indexed_groups in groups_by_role_afi.items():
        expected_count = allowed_counts.get(role_afi)
        if expected_count is None:
            issues.append(
                ValidationIssue(
                    path="device_groups",
                    code="invalid_ebb_full_scale_shape",
                    message=(
                        "delegated EBB full-scale helpers do not support "
                        f"role/AFI combination {role_afi!r}"
                    ),
                )
            )
            continue
        if len(indexed_groups) == 1 and indexed_groups[0][1].partition is None:
            _, device_group = indexed_groups[0]
            if device_group.peer_count != expected_count:
                issues.append(
                    ValidationIssue(
                        path="device_groups",
                        code="invalid_ebb_full_scale_shape",
                        message=(
                            "delegated EBB full-scale helpers require "
                            f"{expected_count} peers for {role_afi!r}; got "
                            f"{device_group.peer_count}"
                        ),
                    )
                )
            continue

        if role_afi == ("bgpmon", "v6"):
            issues.append(
                ValidationIssue(
                    path="device_groups",
                    code="invalid_ebb_full_scale_shape",
                    message=(
                        "delegated EBB full-scale helpers do not support a "
                        f"partitioned optional group for {role_afi!r}; found "
                        f"{[group.name for _, group in indexed_groups]}"
                    ),
                )
            )
            continue

        if any(group.partition is None for _, group in indexed_groups):
            issues.append(
                ValidationIssue(
                    path="device_groups",
                    code="invalid_ebb_full_scale_shape",
                    message=(
                        "delegated EBB full-scale helpers require either one "
                        "unpartitioned group or one complete partition family "
                        f"for {role_afi!r}"
                    ),
                )
            )
            continue

        partitions = [t.cast(t.Any, group.partition) for _, group in indexed_groups]
        family_names = {partition.family for partition in partitions}
        ordered = sorted(
            zip(indexed_groups, partitions, strict=True),
            key=lambda item: item[1].ordinal,
        )
        expected_start = 0
        contiguous = True
        for expected_ordinal, ((_index, group), partition) in enumerate(ordered):
            if (
                partition.ordinal != expected_ordinal
                or partition.start_index != expected_start
                or partition.total_peer_count != expected_count
            ):
                contiguous = False
            expected_start += group.peer_count
        if len(family_names) != 1 or not contiguous or expected_start != expected_count:
            issues.append(
                ValidationIssue(
                    path="device_groups",
                    code="invalid_ebb_full_scale_shape",
                    message=(
                        "delegated EBB full-scale partition family for "
                        f"{role_afi!r} must be contiguous and total "
                        f"{expected_count} peers"
                    ),
                )
            )

    for role_afi in _EBB_REQUIRED_ROLE_AFI_COUNTS:
        if role_afi not in groups_by_role_afi:
            issues.append(
                ValidationIssue(
                    path="device_groups",
                    code="invalid_ebb_full_scale_shape",
                    message=(
                        "delegated EBB full-scale helpers require one device "
                        f"group for {role_afi!r}"
                    ),
                )
            )

    if issues:
        raise TopologyValidationError(bound.logical_topology.name, issues)
