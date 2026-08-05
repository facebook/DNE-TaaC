# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

from __future__ import annotations

import typing as t
from dataclasses import dataclass
from enum import Enum

from taac.abstractions.artifacts import CompiledTaacArtifacts
from taac.abstractions.eos_bgpcpp_component_runtime import (
    MetaComponentRuntimePlan,
)
from taac.abstractions.topology.model import OpenRMode
from taac.abstractions.validation import (
    TopologyValidationError,
    ValidationIssue,
)


class EosBgpCppSetupPhaseOwner(str, Enum):
    LEGACY_COMPATIBILITY = "legacy_compatibility"
    HOST_PREPARATION = "host_preparation"
    IXIA_CONFIGURATION = "ixia_configuration"
    COMPONENT_CONFIGURATION = "component_configuration"
    OPENR_CONFIGURATION = "openr_configuration"
    COMPONENT_STARTUP = "component_startup"
    INTERFACE_CONFIGURATION = "interface_configuration"
    OPENR_FEATURE = "openr_feature"
    HOST_FINALIZATION = "host_finalization"


@dataclass(frozen=True)
class EosBgpCppSetupPhase:
    owner: EosBgpCppSetupPhaseOwner
    tasks: tuple[t.Any, ...] = ()


@dataclass(frozen=True)
class EosEndpointPlan:
    endpoints: tuple[t.Any, ...]
    host_os_type_map: t.Mapping[str, t.Any]


@dataclass(frozen=True)
class InterfaceAddressBlockPlan:
    device_groups: tuple[str, ...]
    role: str
    interface: str
    afi: str
    parent_network: str
    local_addresses: tuple[str, ...]
    peer_addresses: tuple[str, ...]
    prefix_length: int
    start_offset: int


@dataclass(frozen=True)
class InterfacePlan:
    consumed_device_groups: tuple[str, ...]
    address_blocks: tuple[InterfaceAddressBlockPlan, ...] = ()


@dataclass(frozen=True)
class BgpPeerPlanEntry:
    device_group: str
    ordinal: int
    afi: str
    remote_asn: int | None
    local_address: str
    peer_address: str
    peer_group_name: str | None
    description: str

    def bgpcpp_config(self) -> dict[str, t.Any]:
        return {
            "remote_as_4_byte": self.remote_asn,
            "local_addr": self.local_address,
            "peer_addr": self.peer_address,
            "next_hop4": (self.local_address if self.afi == "v4" else "0.0.0.0"),
            "next_hop6": self.local_address if self.afi == "v6" else "0::0",
            "description": self.description,
            "peer_id": self.peer_address,
            "peer_group_name": self.peer_group_name,
        }


@dataclass(frozen=True)
class BgpPeerPlan:
    consumed_device_groups: tuple[str, ...]
    peers: tuple[BgpPeerPlanEntry, ...] = ()


@dataclass(frozen=True)
class BgpPolicyPlan:
    consumed_device_groups: tuple[str, ...]


@dataclass(frozen=True)
class IxiaPlan:
    consumed_device_groups: tuple[str, ...]
    basic_port_configs: tuple[t.Any, ...]
    basic_traffic_item_configs: tuple[t.Any, ...]


@dataclass(frozen=True)
class OpenRFeaturePlan:
    mode: OpenRMode


@dataclass(frozen=True)
class TeardownPlan:
    tasks: tuple[t.Any, ...]
    restored_interfaces: tuple[str, ...] = ()
    disabled_components: tuple[str, ...] = ()


@dataclass(frozen=True)
class EosBgpCppDevicePlan:
    logical_topology_name: str
    device_groups: tuple[str, ...]
    endpoint_plan: EosEndpointPlan
    interface_plan: InterfacePlan
    bgp_peer_plan: BgpPeerPlan
    bgp_policy_plan: BgpPolicyPlan
    component_runtime_plan: MetaComponentRuntimePlan | None
    setup_phases: tuple[EosBgpCppSetupPhase, ...]
    ixia_plan: IxiaPlan
    openr_feature_plan: OpenRFeaturePlan
    teardown_plan: TeardownPlan

    def assert_complete_projection_accounting(self) -> None:
        expected = set(self.device_groups)
        issues: list[ValidationIssue] = []
        for projection_name, consumed_groups in (
            ("interface", self.interface_plan.consumed_device_groups),
            ("peer", self.bgp_peer_plan.consumed_device_groups),
            ("policy", self.bgp_policy_plan.consumed_device_groups),
            ("ixia", self.ixia_plan.consumed_device_groups),
        ):
            consumed = set(consumed_groups)
            missing = sorted(expected - consumed)
            unexpected = sorted(consumed - expected)
            duplicates = sorted(
                group_name
                for group_name in consumed
                if consumed_groups.count(group_name) > 1
            )
            if missing:
                issues.append(
                    ValidationIssue(
                        path=f"device_plan.{projection_name}_plan.device_groups",
                        code="unconsumed_device_group_projection",
                        message=(
                            f"{projection_name} planning did not consume bound "
                            f"device groups {missing}"
                        ),
                    )
                )
            if unexpected:
                issues.append(
                    ValidationIssue(
                        path=f"device_plan.{projection_name}_plan.device_groups",
                        code="unknown_device_group_projection",
                        message=(
                            f"{projection_name} planning consumed unknown device "
                            f"groups {unexpected}"
                        ),
                    )
                )
            if duplicates:
                issues.append(
                    ValidationIssue(
                        path=f"device_plan.{projection_name}_plan.device_groups",
                        code="duplicate_device_group_projection",
                        message=(
                            f"{projection_name} planning consumed device groups "
                            f"more than once: {duplicates}"
                        ),
                    )
                )
        if issues:
            raise TopologyValidationError(self.logical_topology_name, issues)

    def render(self) -> CompiledTaacArtifacts:
        self.assert_complete_projection_accounting()
        return CompiledTaacArtifacts(
            endpoints=list(self.endpoint_plan.endpoints),
            host_os_type_map=dict(self.endpoint_plan.host_os_type_map),
            setup_tasks=[task for phase in self.setup_phases for task in phase.tasks],
            teardown_tasks=list(self.teardown_plan.tasks),
            basic_port_configs=list(self.ixia_plan.basic_port_configs),
            basic_traffic_item_configs=list(self.ixia_plan.basic_traffic_item_configs),
        )
