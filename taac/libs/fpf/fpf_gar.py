# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""Live BGP and FBOSS Agent assertions for MWG2 FPF GAR tests."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
import time
import typing as t
from dataclasses import dataclass

from taac.internal.driver.fboss_switch_internal import (
    FbossSwitchInternal,
)
from taac.libs.fpf.inject_bgp_prefixes import expand_prefix_range


@dataclass(frozen=True)
class GarPrefixSignal:
    path_count: int
    capacities: frozenset[int]
    spine_ids: frozenset[int]
    topology_field_sets: tuple[frozenset[str], ...]
    community_sets: tuple[frozenset[str], ...]


@dataclass(frozen=True)
class GarAgentSignal:
    client_nexthop_count: int
    forwarding_nexthop_count: int
    capacities: frozenset[int]
    spine_ids: frozenset[int]
    topology_field_sets: tuple[frozenset[str], ...]
    action: str


@dataclass(frozen=True)
class GarDeviceSnapshot:
    bgp: dict[str, GarPrefixSignal]
    agent: dict[str, GarAgentSignal]


@dataclass(frozen=True)
class GarValidationPlan:
    source_bgp: bool
    source_agent: bool
    spine_bgp: bool
    spine_agent: bool
    observer_bgp: bool
    observer_agent: bool


VALIDATION_PLANS: dict[str, GarValidationPlan] = {
    "full": GarValidationPlan(True, True, True, True, True, True),
    "topology_info": GarValidationPlan(True, False, True, False, True, True),
    "bgp": GarValidationPlan(True, False, True, False, True, False),
    "remote_rib_fib": GarValidationPlan(False, False, False, False, True, True),
}


def _binary_prefix_to_str(prefix: object) -> str | None:
    try:
        prefix_bin = prefix.prefix_bin  # pyre-ignore[16]
        num_bits = int(prefix.num_bits)  # pyre-ignore[16]
        family = socket.AF_INET if len(prefix_bin) == 4 else socket.AF_INET6
        address = socket.inet_ntop(family, prefix_bin)
        return str(ipaddress.ip_network(f"{address}/{num_bits}", strict=False))
    except (AttributeError, OSError, TypeError, ValueError):
        return None


def _agent_prefix_to_str(route: object) -> str | None:
    try:
        dest = route.dest  # pyre-ignore[16]
        prefix_bin = dest.ip.addr  # pyre-ignore[16]
        num_bits = int(dest.prefixLength)  # pyre-ignore[16]
        family = socket.AF_INET if len(prefix_bin) == 4 else socket.AF_INET6
        address = socket.inet_ntop(family, prefix_bin)
        return str(ipaddress.ip_network(f"{address}/{num_bits}", strict=False))
    except (AttributeError, OSError, TypeError, ValueError):
        return None


def _best_paths(entry: object) -> list[object]:
    paths = getattr(entry, "paths", None) or {}
    best_group = getattr(entry, "best_group", "")
    if best_group and best_group in paths:
        return list(paths[best_group])
    if "best" in paths:
        return list(paths["best"])
    return [
        path
        for group in paths.values()
        for path in group
        if bool(getattr(path, "is_best_path", False))
    ]


def _mapping_topology_value(path: object, field: str) -> int | None:
    topology = getattr(path, "topologyInfo", None) or {}
    value = topology.get(field)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _mapping_topology_fields(path: object) -> frozenset[str]:
    topology = getattr(path, "topologyInfo", None) or {}
    return frozenset(
        str(field) for field, value in topology.items() if value is not None
    )


def _community_to_str(community: object) -> str:
    if isinstance(community, str):
        return community
    if hasattr(community, "asn") and hasattr(community, "value"):
        return f"{community.asn}:{community.value}"  # pyre-ignore[16]
    if isinstance(community, int):
        return f"{(community >> 16) & 0xFFFF}:{community & 0xFFFF}"
    if isinstance(community, (tuple, list)) and len(community) == 2:
        return f"{community[0]}:{community[1]}"
    return str(community)


def _path_communities(path: object) -> frozenset[str]:
    communities = getattr(path, "communities", None)
    if communities is None:
        communities = getattr(path, "community_list", None)
    return frozenset(_community_to_str(community) for community in communities or [])


def summarize_bgp_entries(
    entries: t.Iterable[object], expected_prefixes: set[str]
) -> dict[str, GarPrefixSignal]:
    summaries: dict[str, GarPrefixSignal] = {}
    for entry in entries:
        prefix = _binary_prefix_to_str(getattr(entry, "prefix", None))
        if prefix is None or prefix not in expected_prefixes:
            continue
        paths = _best_paths(entry)
        capacities = frozenset(
            value
            for path in paths
            if (value := _mapping_topology_value(path, "remote_rack_capacity"))
            is not None
        )
        spine_ids = frozenset(
            value
            for path in paths
            if (value := _mapping_topology_value(path, "spine_id")) is not None
        )
        summaries[prefix] = GarPrefixSignal(
            path_count=len(paths),
            capacities=capacities,
            spine_ids=spine_ids,
            topology_field_sets=tuple(_mapping_topology_fields(path) for path in paths),
            community_sets=tuple(_path_communities(path) for path in paths),
        )
    return summaries


def _agent_topology_value(next_hop: object, field: str) -> int | None:
    topology = getattr(next_hop, "topologyInfo", None)
    if topology is None:
        return None
    value = getattr(topology, field, None)
    return int(value) if value is not None else None


def _agent_topology_fields(next_hop: object) -> frozenset[str]:
    topology = getattr(next_hop, "topologyInfo", None)
    if topology is None:
        return frozenset()
    return frozenset(
        field
        for field in (
            "rack_id",
            "plane_id",
            "remote_rack_capacity",
            "spine_capacity",
            "local_rack_capacity",
            "spine_id",
        )
        if getattr(topology, field, None) is not None
    )


def _route_action_name(route: object) -> str:
    action = getattr(route, "action", "")
    name = getattr(action, "name", None)
    return str(name if name is not None else action).rsplit(".", 1)[-1].lower()


def summarize_agent_routes(
    routes: t.Iterable[object], expected_prefixes: set[str]
) -> dict[str, GarAgentSignal]:
    summaries: dict[str, GarAgentSignal] = {}
    for route in routes:
        prefix = _agent_prefix_to_str(route)
        if prefix is None or prefix not in expected_prefixes:
            continue
        client_groups = getattr(route, "nextHopMulti", None) or []
        client_nexthops = max(
            (list(getattr(group, "nextHops", None) or []) for group in client_groups),
            key=len,
            default=[],
        )
        forwarding_nexthops = list(getattr(route, "nextHops", None) or [])
        capacities = frozenset(
            value
            for next_hop in client_nexthops
            if (value := _agent_topology_value(next_hop, "remote_rack_capacity"))
            is not None
        )
        spine_ids = frozenset(
            value
            for next_hop in client_nexthops
            if (value := _agent_topology_value(next_hop, "spine_id")) is not None
        )
        summaries[prefix] = GarAgentSignal(
            client_nexthop_count=len(client_nexthops),
            forwarding_nexthop_count=len(forwarding_nexthops),
            capacities=capacities,
            spine_ids=spine_ids,
            topology_field_sets=tuple(
                _agent_topology_fields(next_hop) for next_hop in client_nexthops
            ),
            action=_route_action_name(route),
        )
    return summaries


async def _collect_device_snapshot(
    hostname: str,
    expected_prefixes: set[str],
    logger: logging.Logger,
) -> GarDeviceSnapshot:
    driver = FbossSwitchInternal(hostname=hostname, logger=logger)
    bgp = await driver.bgp()
    rib_entries, route_details = await asyncio.gather(
        bgp.async_get_bgp_rib_entries(),
        driver.async_get_route_table_details(),
    )
    return GarDeviceSnapshot(
        bgp=summarize_bgp_entries(rib_entries, expected_prefixes),
        agent=summarize_agent_routes(route_details, expected_prefixes),
    )


def _histogram(values: t.Iterable[int]) -> dict[int, int]:
    result: dict[int, int] = {}
    for value in values:
        result[value] = result.get(value, 0) + 1
    return result


def _set_histogram(values: t.Iterable[frozenset[int]]) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        label = ",".join(str(item) for item in sorted(value)) if value else "none"
        result[label] = result.get(label, 0) + 1
    return result


def _action_histogram(signals: dict[str, GarAgentSignal]) -> dict[str, int]:
    result: dict[str, int] = {}
    for signal in signals.values():
        result[signal.action] = result.get(signal.action, 0) + 1
    return result


def _field_set_histogram(
    field_sets: t.Iterable[frozenset[str]],
) -> dict[str, int]:
    result: dict[str, int] = {}
    for fields in field_sets:
        label = ",".join(sorted(fields)) if fields else "none"
        result[label] = result.get(label, 0) + 1
    return result


def _community_presence_count(
    signals: dict[str, GarPrefixSignal], community: str
) -> tuple[int, int]:
    paths = [
        communities
        for signal in signals.values()
        for communities in signal.community_sets
    ]
    return sum(community in communities for communities in paths), len(paths)


def _require_exact_count(
    issues: list[str], label: str, actual: int, expected: int
) -> None:
    if actual != expected:
        issues.append(f"{label}: got {actual}, expected {expected}")


def _validate_path_attributes(
    *,
    issues: list[str],
    label: str,
    topology_field_sets: tuple[frozenset[str], ...],
    community_sets: tuple[frozenset[str], ...] | None = None,
    required_topology_fields: t.Iterable[str] = (),
    required_communities: t.Iterable[str] = (),
    forbidden_communities: t.Iterable[str] = (),
) -> None:
    required_topology = frozenset(required_topology_fields)
    required_comms = frozenset(required_communities)
    forbidden_comms = frozenset(forbidden_communities)

    if required_topology:
        missing_topology = [
            sorted(required_topology - fields)
            for fields in topology_field_sets
            if not required_topology.issubset(fields)
        ]
        if missing_topology:
            issues.append(
                f"{label}: {len(missing_topology)} path(s) missing required rack "
                f"topology fields; required={sorted(required_topology)}, "
                f"sample_missing={missing_topology[:3]}"
            )

    if community_sets is None:
        return
    if required_comms:
        missing_communities = [
            sorted(required_comms - communities)
            for communities in community_sets
            if not required_comms.issubset(communities)
        ]
        if missing_communities:
            issues.append(
                f"{label}: {len(missing_communities)} path(s) missing required "
                f"communities; required={sorted(required_comms)}, "
                f"sample_missing={missing_communities[:3]}"
            )
    if forbidden_comms:
        unexpected_communities = [
            sorted(forbidden_comms & communities)
            for communities in community_sets
            if forbidden_comms & communities
        ]
        if unexpected_communities:
            issues.append(
                f"{label}: {len(unexpected_communities)} path(s) carry forbidden "
                f"communities; forbidden={sorted(forbidden_comms)}, "
                f"sample_present={unexpected_communities[:3]}"
            )


def _validate_uniform_bgp(
    issues: list[str],
    label: str,
    signals: dict[str, GarPrefixSignal],
    expected_prefixes: set[str],
    expected_paths: int,
    expected_capacity: int | None,
    expected_spine_id: int | None = None,
    required_topology_fields: t.Iterable[str] = (),
    required_communities: t.Iterable[str] = (),
    forbidden_communities: t.Iterable[str] = (),
) -> None:
    _require_exact_count(
        issues, f"{label} prefix count", len(signals), len(expected_prefixes)
    )
    missing = expected_prefixes - signals.keys()
    if missing:
        issues.append(
            f"{label}: missing {len(missing)} prefix(es), sample={sorted(missing)[:3]}"
        )
    path_hist = _histogram(signal.path_count for signal in signals.values())
    if path_hist and path_hist != {expected_paths: len(signals)}:
        issues.append(
            f"{label}: BGP best-path histogram {path_hist}, expected {expected_paths}"
        )
    if expected_capacity is not None:
        bad = [
            prefix
            for prefix, signal in signals.items()
            if signal.capacities != {expected_capacity}
        ]
        if bad:
            issues.append(
                f"{label}: {len(bad)} prefix(es) have unexpected GAR capacity; "
                f"sample={bad[:3]}"
            )
    if expected_spine_id is not None:
        bad = [
            prefix
            for prefix, signal in signals.items()
            if signal.spine_ids != {expected_spine_id}
        ]
        if bad:
            issues.append(
                f"{label}: {len(bad)} prefix(es) have unexpected spine_id; "
                f"sample={bad[:3]}"
            )
    for prefix, signal in signals.items():
        _validate_path_attributes(
            issues=issues,
            label=f"{label} {prefix}",
            topology_field_sets=signal.topology_field_sets,
            community_sets=signal.community_sets,
            required_topology_fields=required_topology_fields,
            required_communities=required_communities,
            forbidden_communities=forbidden_communities,
        )


def _validate_uniform_agent(
    issues: list[str],
    label: str,
    signals: dict[str, GarAgentSignal],
    expected_prefixes: set[str],
    expected_forwarding: int,
    expected_client_nexthops: int | None,
    expected_capacity: int | None,
    expected_spine_id: int | None = None,
    expected_action: str | None = None,
    required_topology_fields: t.Iterable[str] = (),
) -> None:
    _require_exact_count(
        issues, f"{label} prefix count", len(signals), len(expected_prefixes)
    )
    missing = expected_prefixes - signals.keys()
    if missing:
        issues.append(
            f"{label}: missing {len(missing)} prefix(es), sample={sorted(missing)[:3]}"
        )
    forwarding_hist = _histogram(
        signal.forwarding_nexthop_count for signal in signals.values()
    )
    if forwarding_hist and forwarding_hist != {expected_forwarding: len(signals)}:
        issues.append(
            f"{label}: Agent forwarding histogram {forwarding_hist}, "
            f"expected {expected_forwarding}"
        )
    if expected_client_nexthops is not None:
        client_hist = _histogram(
            signal.client_nexthop_count for signal in signals.values()
        )
        if client_hist and client_hist != {expected_client_nexthops: len(signals)}:
            issues.append(
                f"{label}: Agent client-nexthop histogram {client_hist}, "
                f"expected {expected_client_nexthops}"
            )
    if expected_capacity is not None:
        bad = [
            prefix
            for prefix, signal in signals.items()
            if signal.capacities != {expected_capacity}
        ]
        if bad:
            issues.append(
                f"{label}: {len(bad)} prefix(es) have unexpected Agent GAR weight; "
                f"sample={bad[:3]}"
            )
    if expected_spine_id is not None:
        bad = [
            prefix
            for prefix, signal in signals.items()
            if signal.spine_ids != {expected_spine_id}
        ]
        if bad:
            issues.append(
                f"{label}: {len(bad)} prefix(es) have unexpected Agent spine_id; "
                f"sample={bad[:3]}"
            )
    if expected_action is not None:
        bad = [
            prefix
            for prefix, signal in signals.items()
            if signal.action != expected_action
        ]
        if bad:
            issues.append(
                f"{label}: {len(bad)} prefix(es) have unexpected action; "
                f"expected={expected_action}, sample={bad[:3]}"
            )
    for prefix, signal in signals.items():
        _validate_path_attributes(
            issues=issues,
            label=f"{label} {prefix}",
            topology_field_sets=signal.topology_field_sets,
            required_topology_fields=required_topology_fields,
        )


def _bgp_summary(signals: dict[str, GarPrefixSignal]) -> str:
    drained_paths, total_paths = _community_presence_count(signals, "65446:10")
    return (
        f"prefixes={len(signals)}, "
        f"best_paths={_histogram(signal.path_count for signal in signals.values())}, "
        f"gar_capacity={_set_histogram(signal.capacities for signal in signals.values())}, "
        f"spine_id={_set_histogram(signal.spine_ids for signal in signals.values())}, "
        f"topology_fields={_field_set_histogram(fields for signal in signals.values() for fields in signal.topology_field_sets)}, "
        f"drain_community_paths={drained_paths}/{total_paths}"
    )


def _agent_summary(signals: dict[str, GarAgentSignal]) -> str:
    return (
        f"prefixes={len(signals)}, actions={_action_histogram(signals)}, "
        f"client_nh={_histogram(signal.client_nexthop_count for signal in signals.values())}, "
        f"forwarding_nh={_histogram(signal.forwarding_nexthop_count for signal in signals.values())}, "
        f"gar_capacity={_set_histogram(signal.capacities for signal in signals.values())}, "
        f"spine_id={_set_histogram(signal.spine_ids for signal in signals.values())}, "
        f"topology_fields={_field_set_histogram(fields for signal in signals.values() for fields in signal.topology_field_sets)}"
    )


def _validate_source_snapshot(
    *,
    issues: list[str],
    name: str,
    snapshot: GarDeviceSnapshot,
    expected_prefixes: set[str],
    source_route_mode: str,
    pair: dict[str, t.Any],
    plan: GarValidationPlan,
) -> None:
    if plan.source_bgp:
        _validate_uniform_bgp(
            issues,
            f"{name} source BGP",
            snapshot.bgp,
            expected_prefixes,
            expected_paths=1,
            expected_capacity=None,
            required_topology_fields=pair.get(
                "source_required_bgp_topology_fields", []
            ),
            required_communities=pair.get("source_required_communities", []),
            forbidden_communities=pair.get("source_forbidden_communities", []),
        )
    if not plan.source_agent:
        return
    if source_route_mode == "drop":
        # addNetworks() originates discard routes locally. Validate that all
        # scale prefixes reached the Agent without a forwarding nexthop.
        _validate_uniform_agent(
            issues,
            f"{name} source Agent",
            snapshot.agent,
            expected_prefixes,
            expected_forwarding=0,
            expected_client_nexthops=0,
            expected_capacity=None,
            expected_action="drop",
            required_topology_fields=pair.get(
                "source_required_agent_topology_fields", []
            ),
        )
    elif source_route_mode == "vf":
        # A production VF prefix is locally reachable through its GPU downlink.
        _validate_uniform_agent(
            issues,
            f"{name} source Agent",
            snapshot.agent,
            expected_prefixes,
            expected_forwarding=int(pair.get("source_forwarding_count", 1)),
            expected_client_nexthops=int(pair.get("source_client_nexthop_count", 1)),
            expected_capacity=None,
            expected_action="nexthops",
            required_topology_fields=pair.get(
                "source_required_agent_topology_fields", []
            ),
        )
    else:
        issues.append(
            f"{name}: unsupported source_route_mode={source_route_mode!r}; "
            "expected 'drop' or 'vf'"
        )


def _validate_fabric_snapshots(
    *,
    issues: list[str],
    name: str,
    spine_snapshot: GarDeviceSnapshot,
    observer_snapshot: GarDeviceSnapshot,
    expected_prefixes: set[str],
    capacity: int,
    spine_capacity: int,
    observer_paths: int,
    observer_forwarding: int,
    spine_id: int,
    pair: dict[str, t.Any],
    plan: GarValidationPlan,
) -> None:
    if spine_capacity == 0:
        for enabled, device_label, signal_map in (
            (plan.spine_bgp, f"{name} spine BGP", spine_snapshot.bgp),
            (plan.spine_agent, f"{name} spine Agent", spine_snapshot.agent),
        ):
            if enabled and signal_map:
                issues.append(
                    f"{device_label}: {len(signal_map)} prefix(es) remain; "
                    "expected all pruned"
                )
    elif plan.spine_bgp:
        _validate_uniform_bgp(
            issues,
            f"{name} spine BGP",
            spine_snapshot.bgp,
            expected_prefixes,
            expected_paths=spine_capacity,
            expected_capacity=None,
            required_topology_fields=pair.get("spine_required_bgp_topology_fields", []),
            required_communities=pair.get("spine_required_communities", []),
            forbidden_communities=pair.get("spine_forbidden_communities", []),
        )
    if spine_capacity > 0 and plan.spine_agent:
        _validate_uniform_agent(
            issues,
            f"{name} spine Agent",
            spine_snapshot.agent,
            expected_prefixes,
            expected_forwarding=spine_capacity,
            expected_client_nexthops=spine_capacity,
            expected_capacity=None,
            required_topology_fields=pair.get(
                "spine_required_agent_topology_fields", []
            ),
        )

    if capacity == 0:
        for enabled, device_label, signal_map in (
            (plan.observer_bgp, f"{name} observer BGP", observer_snapshot.bgp),
            (
                plan.observer_agent,
                f"{name} observer Agent",
                observer_snapshot.agent,
            ),
        ):
            if enabled and signal_map:
                issues.append(
                    f"{device_label}: {len(signal_map)} prefix(es) remain; "
                    "expected all pruned"
                )
        return

    if plan.observer_bgp:
        _validate_uniform_bgp(
            issues,
            f"{name} observer BGP",
            observer_snapshot.bgp,
            expected_prefixes,
            expected_paths=observer_paths,
            expected_capacity=capacity,
            expected_spine_id=spine_id,
            required_topology_fields=pair.get(
                "observer_required_bgp_topology_fields", []
            ),
            required_communities=pair.get("observer_required_communities", []),
            forbidden_communities=pair.get("observer_forbidden_communities", []),
        )
    if plan.observer_agent:
        _validate_uniform_agent(
            issues,
            f"{name} observer Agent",
            observer_snapshot.agent,
            expected_prefixes,
            expected_forwarding=observer_forwarding,
            expected_client_nexthops=observer_paths,
            expected_capacity=capacity,
            expected_spine_id=spine_id,
            required_topology_fields=pair.get(
                "observer_required_agent_topology_fields", []
            ),
        )


def evaluate_gar_pair(
    pair: dict[str, t.Any],
    snapshots: dict[str, GarDeviceSnapshot],
    expected_prefixes: set[str],
) -> tuple[list[str], str]:
    name = str(pair["name"])
    source = str(pair["source"])
    spine = str(pair["spine"])
    observer = str(pair["observer"])
    capacity = int(pair["expected_capacity"])
    spine_capacity = int(pair.get("expected_spine_capacity", capacity))
    observer_paths = int(pair.get("observer_path_count", 36))
    observer_forwarding = int(
        pair.get("observer_forwarding_count", min(capacity, observer_paths))
    )
    spine_id = int(pair.get("spine_id", 1))
    source_route_mode = str(pair.get("source_route_mode", "drop"))
    validation_scope = str(pair.get("validation_scope", "full"))
    issues: list[str] = []

    plan = VALIDATION_PLANS.get(validation_scope)
    if plan is None:
        return (
            [
                f"{name}: unsupported validation_scope={validation_scope!r}; "
                f"expected one of {sorted(VALIDATION_PLANS)}"
            ],
            f"{name}: invalid validation scope",
        )

    source_snapshot = snapshots[source]
    _validate_source_snapshot(
        issues=issues,
        name=name,
        snapshot=source_snapshot,
        expected_prefixes=expected_prefixes,
        source_route_mode=source_route_mode,
        pair=pair,
        plan=plan,
    )

    spine_snapshot = snapshots[spine]
    observer_snapshot = snapshots[observer]
    _validate_fabric_snapshots(
        issues=issues,
        name=name,
        spine_snapshot=spine_snapshot,
        observer_snapshot=observer_snapshot,
        expected_prefixes=expected_prefixes,
        capacity=capacity,
        spine_capacity=spine_capacity,
        observer_paths=observer_paths,
        observer_forwarding=observer_forwarding,
        spine_id=spine_id,
        pair=pair,
        plan=plan,
    )

    summary = "\n".join(
        [
            f"{name}: validation_scope={validation_scope}, expected GAR "
            f"capacity={capacity}, expected spine capacity={spine_capacity}, "
            f"prefixes={len(expected_prefixes)}",
            f"  source {source}: BGP({_bgp_summary(source_snapshot.bgp)}); "
            f"Agent({_agent_summary(source_snapshot.agent)})",
            f"  spine {spine}: BGP({_bgp_summary(spine_snapshot.bgp)}); "
            f"Agent({_agent_summary(spine_snapshot.agent)})",
            f"  remote {observer}: BGP({_bgp_summary(observer_snapshot.bgp)}); "
            f"Agent({_agent_summary(observer_snapshot.agent)})",
        ]
    )
    return issues, summary


async def wait_for_gar_prefixes(
    *,
    pairs: list[dict[str, t.Any]],
    prefixes: t.Iterable[str],
    timeout_sec: float,
    poll_interval_sec: float,
    logger: logging.Logger,
) -> list[str]:
    expected_prefixes = {
        str(ipaddress.ip_network(prefix, strict=False)) for prefix in prefixes
    }
    if not expected_prefixes:
        raise ValueError("GAR validation requires at least one prefix")
    hostnames = sorted(
        {
            str(pair[field])
            for pair in pairs
            for field in ("source", "spine", "observer")
        }
    )
    deadline = time.monotonic() + timeout_sec
    last_issues: list[str] = []

    while True:
        collected = await asyncio.gather(
            *(
                _collect_device_snapshot(hostname, expected_prefixes, logger)
                for hostname in hostnames
            )
        )
        snapshots = dict(zip(hostnames, collected))
        last_issues = []
        summaries: list[str] = []
        for pair in pairs:
            pair_issues, pair_summary = evaluate_gar_pair(
                pair, snapshots, expected_prefixes
            )
            last_issues.extend(pair_issues)
            summaries.append(pair_summary)
        if not last_issues:
            return summaries
        if time.monotonic() >= deadline:
            raise RuntimeError(
                "GAR validation timed out: " + "; ".join(last_issues[:20])
            )
        await asyncio.sleep(poll_interval_sec)


async def wait_for_gar_pairs(
    *,
    pairs: list[dict[str, t.Any]],
    prefix_base: str,
    prefix_count: int,
    increment_step: str,
    timeout_sec: float,
    poll_interval_sec: float,
    logger: logging.Logger,
) -> list[str]:
    return await wait_for_gar_prefixes(
        pairs=pairs,
        prefixes=expand_prefix_range(prefix_base, prefix_count, increment_step),
        timeout_sec=timeout_sec,
        poll_interval_sec=poll_interval_sec,
        logger=logger,
    )
