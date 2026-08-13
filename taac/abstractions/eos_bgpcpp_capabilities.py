# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

from __future__ import annotations

from dataclasses import dataclass

from taac.abstractions.compatibility.eos_bgpcpp_policy_bindings import (
    resolve_eos_bgpcpp_policy_binding,
)
from taac.abstractions.compilation.model import (
    BgpAdjacencyPlan,
    DesiredPresence,
    DutPlan,
    EndpointPlan,
    EndpointSetupMode,
    PolicyDirection,
    ResourceId,
    RoutingConfigPlan,
)
from taac.abstractions.component_semantics import (
    ComponentDesiredState,
    ComponentReadinessRequirement,
    ComponentReconcileMode,
    ComponentRole,
)
from taac.abstractions.config_artifact_semantics import (
    ConfigArtifactProvider,
)


class UnsupportedEosBgpCppCapabilityError(ValueError):
    pass


@dataclass(frozen=True)
class EosBgpCppCapabilityPreflight:
    """Validates the task-free EOS/BGP++ capability before rendering."""

    def validate(self, plan: DutPlan) -> None:
        endpoint = _required_dut_endpoint(plan)
        routing_config = _validate_routing_config(plan, endpoint)
        _validate_components(plan, endpoint, routing_config)
        _validate_policy_bindings(plan, endpoint)


def _required_dut_endpoint(plan: DutPlan) -> EndpointPlan:
    endpoints = tuple(endpoint for endpoint in plan.endpoints if endpoint.is_dut)
    if len(endpoints) != 1:
        raise UnsupportedEosBgpCppCapabilityError(
            "EOS/BGP++ capability requires exactly one DUT endpoint; "
            f"found {len(endpoints)}"
        )
    endpoint = endpoints[0]
    if endpoint.backend != "eos":
        raise UnsupportedEosBgpCppCapabilityError(
            f"DUT endpoint {endpoint.resource_id} has unsupported backend "
            f"{endpoint.backend!r}"
        )
    if not isinstance(endpoint.physical_identifier, str) or not (
        endpoint.physical_identifier
    ):
        raise UnsupportedEosBgpCppCapabilityError(
            f"DUT endpoint {endpoint.resource_id} has no physical identifier"
        )
    return endpoint


def _validate_routing_config(
    plan: DutPlan,
    endpoint: EndpointPlan,
) -> RoutingConfigPlan:
    if endpoint.setup_mode is EndpointSetupMode.PRELOADED:
        raise UnsupportedEosBgpCppCapabilityError(
            "EOS/BGP++ capability does not support preloaded setup"
        )
    if len(plan.routing_configs) != 1:
        raise UnsupportedEosBgpCppCapabilityError(
            "EOS/BGP++ capability requires exactly one routing-config plan; "
            f"found {len(plan.routing_configs)}"
        )
    routing_config = plan.routing_configs[0]
    if routing_config.endpoint_id != endpoint.resource_id:
        raise UnsupportedEosBgpCppCapabilityError(
            f"routing config {routing_config.resource_id} targets "
            f"{routing_config.endpoint_id}, expected {endpoint.resource_id}"
        )
    if routing_config.routing_driver != "bgpcpp":
        raise UnsupportedEosBgpCppCapabilityError(
            f"routing config {routing_config.resource_id} has unsupported driver "
            f"{routing_config.routing_driver!r}"
        )
    source = routing_config.source
    if endpoint.setup_mode is EndpointSetupMode.FULL and source is None:
        raise UnsupportedEosBgpCppCapabilityError(
            f"routing config {routing_config.resource_id} requires a config "
            "artifact source for full setup"
        )
    if (
        source is not None
        and source.provider is not ConfigArtifactProvider.CONFIGERATOR
    ):
        raise UnsupportedEosBgpCppCapabilityError(
            f"routing config {routing_config.resource_id} has unsupported source "
            f"provider {source.provider.value!r}"
        )
    return routing_config


def _validate_components(
    plan: DutPlan,
    endpoint: EndpointPlan,
    routing_config: RoutingConfigPlan,
) -> None:
    if len(plan.components) != 1:
        raise UnsupportedEosBgpCppCapabilityError(
            "EOS/BGP++ capability requires exactly one routing-control-plane "
            f"component; found {len(plan.components)}"
        )
    component = plan.components[0]
    if component.endpoint_id != endpoint.resource_id:
        raise UnsupportedEosBgpCppCapabilityError(
            f"component {component.resource_id} targets {component.endpoint_id}, "
            f"expected {endpoint.resource_id}"
        )
    expected = (
        ComponentRole.ROUTING_CONTROL_PLANE,
        ComponentDesiredState.RUNNING,
        ComponentReconcileMode.RESTART_AFTER_CONFIGURATION,
        ComponentReadinessRequirement.ACKNOWLEDGED,
        (routing_config.resource_id,),
    )
    actual = (
        component.role,
        component.desired_state,
        component.reconcile_mode,
        component.readiness,
        component.depends_on,
    )
    if actual != expected:
        raise UnsupportedEosBgpCppCapabilityError(
            f"component {component.resource_id} has unsupported routing-control-plane "
            f"contract {actual!r}"
        )


def _validate_policy_bindings(plan: DutPlan, endpoint: EndpointPlan) -> None:
    policies_by_id = {policy.resource_id: policy for policy in plan.policies}
    for policy in plan.policies:
        if policy.preset is not None:
            resolve_eos_bgpcpp_policy_binding(policy.preset.key)
    adjacencies = _required_policy_adjacencies(plan)
    _validate_exact_policy_coverage(plan, adjacencies)
    adjacencies_by_id = {adjacency.resource_id: adjacency for adjacency in adjacencies}
    for binding in plan.policy_bindings:
        policy = policies_by_id.get(binding.policy_id)
        if policy is None or policy.preset is None:
            raise UnsupportedEosBgpCppCapabilityError(
                f"policy binding {binding.resource_id} has no role-policy preset"
            )
        if policy.preset.key.direction is not binding.direction:
            raise UnsupportedEosBgpCppCapabilityError(
                f"policy binding {binding.resource_id} direction does not match "
                f"policy {policy.resource_id}"
            )
        adjacency = adjacencies_by_id[binding.adjacency_id]
        key = policy.preset.key
        if (
            key.afi is not adjacency.afi
            or key.relationship is not adjacency.relationship
        ):
            raise UnsupportedEosBgpCppCapabilityError(
                f"policy binding {binding.resource_id} does not match adjacency "
                f"{adjacency.resource_id}"
            )
        if endpoint.network_role is None or key.local_role is not endpoint.network_role:
            raise UnsupportedEosBgpCppCapabilityError(
                f"policy binding {binding.resource_id} does not match DUT network role"
            )


def _required_policy_adjacencies(plan: DutPlan) -> tuple[BgpAdjacencyPlan, ...]:
    adjacencies = tuple(
        adjacency
        for adjacency in plan.adjacencies
        if adjacency.desired_presence is DesiredPresence.PRESENT
    )
    missing_relationship = tuple(
        adjacency.resource_id
        for adjacency in adjacencies
        if adjacency.relationship is None
    )
    if missing_relationship:
        raise UnsupportedEosBgpCppCapabilityError(
            "EOS/BGP++ adjacencies require peer relationships: "
            f"missing={missing_relationship}"
        )
    return adjacencies


def _validate_exact_policy_coverage(
    plan: DutPlan,
    adjacencies: tuple[BgpAdjacencyPlan, ...],
) -> None:
    expected = tuple(
        (adjacency.resource_id, direction)
        for adjacency in adjacencies
        for direction in PolicyDirection
    )
    actual = tuple(
        (binding.adjacency_id, binding.direction) for binding in plan.policy_bindings
    )
    duplicate = _duplicate_binding_keys(actual)
    missing = tuple(key for key in expected if key not in actual)
    unexpected = tuple(key for key in actual if key not in expected)
    if duplicate or missing or unexpected:
        raise UnsupportedEosBgpCppCapabilityError(
            "EOS/BGP++ policy binding coverage mismatch: "
            f"duplicate={duplicate}, missing={missing}, unexpected={unexpected}"
        )


def _duplicate_binding_keys(
    keys: tuple[tuple[ResourceId, PolicyDirection], ...],
) -> tuple[tuple[ResourceId, PolicyDirection], ...]:
    seen: set[tuple[ResourceId, PolicyDirection]] = set()
    duplicate = []
    for key in keys:
        if key in seen and key not in duplicate:
            duplicate.append(key)
        seen.add(key)
    return tuple(duplicate)


__all__ = (
    "EosBgpCppCapabilityPreflight",
    "UnsupportedEosBgpCppCapabilityError",
)
