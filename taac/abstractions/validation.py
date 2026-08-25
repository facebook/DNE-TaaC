# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe

from __future__ import annotations

import ipaddress
import typing as t
from dataclasses import dataclass

from taac.abstractions.topology.address import AddressPlan
from taac.abstractions.topology.attributes import (
    AsPathSequence,
    ExtendedCommunity,
    ExtendedCommunityKind,
    RouteAttributeDistribution,
    RouteAttributePool,
    StandardCommunity,
)
from taac.abstractions.topology.model import (
    BgpPeerGroup,
    DeviceGroupPartition,
    IxiaDeviceGroupChild,
    IxiaEndpointPortLabelStyle,
    IxiaPortAssignment,
    OpenRMode,
    TaskCompatibilityProfile,
)
from taac.abstractions.topology.prefix import (
    NextHopDistribution,
    NextHopIntent,
    NextHopMode,
    PeerPrefixDistribution,
    SelfNextHopRealization,
)

if t.TYPE_CHECKING:
    from taac.abstractions.topology.model import (
        DeviceGroupSpec,
        EndpointSpec,
        LogicalTopology,
        PrefixAdvertisement,
        PrefixPool,
        PrefixSet,
        RoutingDeviceConfig,
        TrafficFlowSpec,
    )


VALID_AFIS = frozenset({"v4", "v6"})
VALID_ENDPOINT_REQUIRED_OS = frozenset({"eos", "fboss", "ixia"})
VALID_ENDPOINT_SETUP_MODES = frozenset({"full", "preloaded", "skip", "verify_only"})
VALID_ENDPOINT_KINDS = frozenset({"dut", "ixia", "traffic", "trafficgen"})
TRAFFIC_ENDPOINT_ROLES = frozenset({"ixia", "traffic", "trafficgen"})
VALID_ROUTING_DRIVERS = frozenset({"bgpcpp", "bgp++", "arbgp", "fboss"})
VALID_LEGACY_PROFILES = frozenset(
    {
        "bounded_ecmp",
        "ebb_full_scale",
        "egress_peer_scale",
        "ipv6_update_packing",
        "ug_new_peer_join",
    }
)
IXIA_MAX_4BYTE_ASN = (1 << 32) - 1
BGP_STANDARD_COMMUNITY_FIELD_MAX = (1 << 16) - 1


@dataclass(frozen=True)
class ValidationIssue:
    path: str
    code: str
    message: str
    hint: str | None = None


class TopologyValidationError(ValueError):
    def __init__(
        self, logical_topology_name: str, issues: list[ValidationIssue]
    ) -> None:
        self.logical_topology_name = logical_topology_name
        self.issues = issues
        issue_word = "error" if len(issues) == 1 else "errors"
        details = "\n".join(
            f"- {issue.path} [{issue.code}]: {issue.message}" for issue in issues
        )
        super().__init__(
            f"Logical topology {logical_topology_name} has {len(issues)} validation "
            f"{issue_word}:\n{details}"
        )


def validate_logical_topology(logical_topology: LogicalTopology) -> None:
    issues = collect_logical_topology_issues(logical_topology)
    if issues:
        raise TopologyValidationError(logical_topology.name or "<unnamed>", issues)


def collect_logical_topology_issues(
    logical_topology: LogicalTopology,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    _validate_logical_topology_identity(logical_topology, issues)
    endpoint_names = _check_unique_names(
        issues=issues,
        objects=logical_topology.endpoints,
        path_prefix="endpoints",
        code="duplicate_endpoint_name",
    )
    endpoint_by_name = {
        endpoint.name: endpoint
        for endpoint in logical_topology.endpoints
        if endpoint.name
    }
    dg_names = _check_unique_names(
        issues=issues,
        objects=logical_topology.device_groups,
        path_prefix="device_groups",
        code="duplicate_device_group_name",
    )

    _validate_logical_topology_endpoints(logical_topology, issues)
    prefix_pool_names = _check_prefix_pool_names(logical_topology, issues)
    _validate_logical_topology_device_groups(
        logical_topology=logical_topology,
        endpoint_names=endpoint_names,
        endpoint_by_name=endpoint_by_name,
        dg_names=dg_names,
        prefix_pool_names=prefix_pool_names,
        issues=issues,
    )
    _validate_device_group_partitions(logical_topology.device_groups, issues)
    _validate_ixia_child_names(logical_topology.device_groups, issues)
    _validate_logical_topology_peer_groups(logical_topology, issues)
    _validate_logical_topology_prefix_pools(logical_topology, issues)
    prefix_sets_by_name = _validate_prefix_sets(logical_topology, issues)
    _validate_prefix_advertisements(logical_topology, prefix_sets_by_name, issues)
    _validate_route_senders(logical_topology, issues)
    _validate_logical_topology_traffic_flows(
        logical_topology,
        dg_names,
        prefix_pool_names,
        issues,
    )
    issues.extend(collect_routing_device_config_issues(logical_topology.device_config))

    return issues


def _validate_logical_topology_identity(
    logical_topology: LogicalTopology,
    issues: list[ValidationIssue],
) -> None:
    if not logical_topology.name:
        issues.append(
            _issue("name", "name_required", "logical topology name is required")
        )

    if (
        logical_topology.legacy_profile
        and logical_topology.legacy_profile not in VALID_LEGACY_PROFILES
    ):
        issues.append(
            _issue(
                "legacy_profile",
                "unknown_legacy_profile",
                f"unsupported legacy profile {logical_topology.legacy_profile!r}",
            )
        )
    compatibility_profile = logical_topology.task_compatibility_profile
    if compatibility_profile is not None:
        if not isinstance(compatibility_profile, TaskCompatibilityProfile):
            issues.append(
                _issue(
                    "task_compatibility_profile",
                    "invalid_task_compatibility_profile",
                    "task compatibility profile must be typed",
                )
            )
        elif logical_topology.legacy_profile is not None:
            issues.append(
                _issue(
                    "task_compatibility_profile",
                    "legacy_task_compatibility_conflict",
                    "task compatibility projection requires a profile-free topology",
                )
            )


def _validate_logical_topology_endpoints(
    logical_topology: LogicalTopology,
    issues: list[ValidationIssue],
) -> None:
    has_dut = False
    for index, endpoint in enumerate(logical_topology.endpoints):
        if _endpoint_is_dut(endpoint):
            has_dut = True
        _validate_endpoint(endpoint, f"endpoints[{index}]", issues)
    if logical_topology.endpoints and not has_dut:
        issues.append(
            _issue(
                "endpoints",
                "dut_endpoint_required",
                "at least one DUT endpoint is required",
            )
        )
    if not logical_topology.endpoints:
        issues.append(
            _issue(
                "endpoints",
                "endpoint_required",
                "at least one endpoint is required",
            )
        )


def _validate_logical_topology_device_groups(
    *,
    logical_topology: LogicalTopology,
    endpoint_names: set[str],
    endpoint_by_name: t.Mapping[str, EndpointSpec],
    dg_names: set[str],
    prefix_pool_names: set[str],
    issues: list[ValidationIssue],
) -> None:
    for index, dg in enumerate(logical_topology.device_groups):
        _validate_device_group(
            dg=dg,
            path=f"device_groups[{index}]",
            endpoint_names=endpoint_names,
            endpoint_by_name=endpoint_by_name,
            traffic_flow_dg_names=dg_names,
            traffic_flow_prefix_pool_names=prefix_pool_names,
            issues=issues,
        )


def _validate_logical_topology_peer_groups(
    logical_topology: LogicalTopology,
    issues: list[ValidationIssue],
) -> None:
    for index, peer_group in enumerate(logical_topology.peer_groups):
        _validate_peer_group(peer_group, f"peer_groups[{index}]", issues)


def _validate_logical_topology_prefix_pools(
    logical_topology: LogicalTopology,
    issues: list[ValidationIssue],
) -> None:
    for index, prefix_pool in enumerate(logical_topology.prefix_pools):
        _validate_prefix_pool(prefix_pool, f"prefix_pools[{index}]", issues)


def _validate_prefix_sets(
    logical_topology: LogicalTopology,
    issues: list[ValidationIssue],
) -> dict[str, PrefixSet]:
    _check_unique_names(
        issues=issues,
        objects=logical_topology.prefix_sets,
        path_prefix="prefix_sets",
        code="duplicate_prefix_set_name",
    )
    prefix_sets_by_name: dict[str, PrefixSet] = {}
    for index, prefix_set in enumerate(logical_topology.prefix_sets):
        path = f"prefix_sets[{index}]"
        if not prefix_set.name:
            issues.append(
                _issue(f"{path}.name", "name_required", "prefix set name is required")
            )
        else:
            prefix_sets_by_name.setdefault(prefix_set.name, prefix_set)
        _validate_prefix_set(prefix_set, path, issues)
    return prefix_sets_by_name


def _validate_prefix_set(
    prefix_set: PrefixSet,
    path: str,
    issues: list[ValidationIssue],
) -> None:
    if prefix_set.afi not in VALID_AFIS:
        issues.append(
            _issue(
                f"{path}.afi",
                "unsupported_afi",
                f"unsupported AFI {prefix_set.afi!r}",
            )
        )
        return
    source = prefix_set.source
    if (
        isinstance(source.count, bool)
        or not isinstance(source.count, int)
        or source.count <= 0
    ):
        issues.append(
            _issue(
                f"{path}.source.count",
                "invalid_prefix_count",
                "formulaic prefix count must be a positive integer",
            )
        )
        return
    if (
        isinstance(source.prefix_length, bool)
        or not isinstance(source.prefix_length, int)
        or source.prefix_length < 0
        or source.prefix_length > (32 if prefix_set.afi == "v4" else 128)
    ):
        issues.append(
            _issue(
                f"{path}.source.prefix_length",
                "invalid_prefix_length",
                "prefix_length is outside the AFI range",
            )
        )
        return
    parsed_start = _parse_ip(source.start_prefix, prefix_set.afi)
    parsed_parent = _parse_network(source.parent_network, prefix_set.afi)
    step = _parse_positive_ip_step(source.prefix_step, prefix_set.afi)
    if parsed_start is None:
        issues.append(
            _issue(
                f"{path}.source.start_prefix",
                "invalid_prefix_start",
                "start_prefix must be an address in the prefix-set AFI",
            )
        )
    if parsed_parent is None:
        issues.append(
            _issue(
                f"{path}.source.parent_network",
                "invalid_parent_network",
                "parent_network must be a network in the prefix-set AFI",
            )
        )
    if step is None:
        issues.append(
            _issue(
                f"{path}.source.prefix_step",
                "invalid_prefix_step",
                "prefix_step must be positive and in the prefix-set AFI",
            )
        )
    span = _validated_prefix_span(source, path, issues)
    if span is None:
        return
    if parsed_start is None or parsed_parent is None or step is None:
        return
    block_size = 1 << (parsed_start.max_prefixlen - source.prefix_length)
    if int(parsed_start) % block_size or step % block_size:
        issues.append(
            _issue(
                f"{path}.source",
                "unaligned_prefix_formula",
                "start_prefix and prefix_step must preserve prefix alignment",
            )
        )
        return
    terminal = int(parsed_start) + step * (span - 1)
    if terminal >= 1 << parsed_start.max_prefixlen:
        issues.append(
            _issue(
                f"{path}.source",
                "prefix_formula_overflow",
                "formulaic prefix set overflows its AFI",
            )
        )
    elif (
        parsed_start not in parsed_parent
        or ipaddress.ip_address(terminal) not in parsed_parent
    ):
        issues.append(
            _issue(
                f"{path}.source.parent_network",
                "prefix_formula_outside_parent",
                "formulaic prefix set is not contained by parent_network",
            )
        )


def _validated_prefix_span(
    source: t.Any,
    path: str,
    issues: list[ValidationIssue],
) -> int | None:
    excluded = source.excluded_indices
    valid_types = isinstance(excluded, tuple) and all(
        not isinstance(value, bool) and isinstance(value, int) for value in excluded
    )
    span = source.count + len(excluded) if valid_types else source.count
    if (
        not valid_types
        or tuple(sorted(set(excluded))) != excluded
        or any(value < 0 or value >= span for value in excluded)
    ):
        issues.append(
            _issue(
                f"{path}.source.excluded_indices",
                "invalid_prefix_exclusions",
                "excluded indices must be unique, sorted, and inside the candidate span",
            )
        )
        return None
    return span


def _validate_prefix_advertisements(
    logical_topology: LogicalTopology,
    prefix_sets_by_name: t.Mapping[str, PrefixSet],
    issues: list[ValidationIssue],
) -> None:
    for dg_index, device_group in enumerate(logical_topology.device_groups):
        base_path = f"device_groups[{dg_index}]"
        if device_group.prefix_pools and device_group.prefix_advertisements:
            issues.append(
                _issue(
                    base_path,
                    "mixed_prefix_authoring",
                    "a device group cannot mix legacy prefix pools and prefix advertisements",
                )
            )
        _check_unique_names(
            issues=issues,
            objects=device_group.prefix_advertisements,
            path_prefix=f"{base_path}.prefix_advertisements",
            code="duplicate_prefix_advertisement_name",
        )
        network_group_indices: dict[int, int] = {}
        for ad_index, advertisement in enumerate(device_group.prefix_advertisements):
            path = f"{base_path}.prefix_advertisements[{ad_index}]"
            if not advertisement.name:
                issues.append(
                    _issue(
                        f"{path}.name",
                        "name_required",
                        "prefix advertisement name is required",
                    )
                )
            prefix_set = prefix_sets_by_name.get(advertisement.prefix_set)
            if prefix_set is None:
                issues.append(
                    _issue(
                        f"{path}.prefix_set",
                        "unknown_prefix_set",
                        f"prefix set {advertisement.prefix_set!r} is not declared",
                    )
                )
            elif prefix_set.afi != device_group.afi:
                issues.append(
                    _issue(
                        f"{path}.prefix_set",
                        "prefix_set_afi_mismatch",
                        "prefix set AFI does not match its device group",
                    )
                )
            _validate_prefix_advertisement_geometry(
                advertisement,
                device_group.peer_count,
                device_group.afi,
                prefix_set,
                path,
                issues,
            )
            _validate_route_attribute_pool(
                advertisement.route_attributes,
                f"{path}.route_attributes",
                issues,
            )
            if (
                device_group.route_attributes is not None
                and advertisement.route_attributes is not None
            ):
                issues.append(
                    _issue(
                        f"{path}.route_attributes",
                        "multiple_route_attribute_attachments",
                        (
                            "route attributes may attach to the device group or "
                            "advertisement, not both"
                        ),
                    )
                )
            group_index = advertisement.allocation.network_group_index
            if (
                not isinstance(group_index, bool)
                and isinstance(group_index, int)
                and group_index >= 0
            ):
                if group_index in network_group_indices:
                    issues.append(
                        _issue(
                            f"{path}.allocation.network_group_index",
                            "duplicate_network_group_index",
                            "network_group_index is already used by another advertisement",
                        )
                    )
                else:
                    network_group_indices[group_index] = ad_index


def _validate_prefix_advertisement_geometry(
    advertisement: PrefixAdvertisement,
    peer_count: int,
    afi: str,
    prefix_set: PrefixSet | None,
    path: str,
    issues: list[ValidationIssue],
) -> None:
    allocation = advertisement.allocation
    if not isinstance(allocation.peer_distribution, PeerPrefixDistribution):
        issues.append(
            _issue(
                f"{path}.allocation.peer_distribution",
                "invalid_peer_prefix_distribution",
                "peer_distribution must be SHARED or DISJOINT",
            )
        )
        return
    if (
        isinstance(allocation.prefixes_per_peer, bool)
        or not isinstance(allocation.prefixes_per_peer, int)
        or allocation.prefixes_per_peer <= 0
    ):
        issues.append(
            _issue(
                f"{path}.allocation.prefixes_per_peer",
                "invalid_prefixes_per_peer",
                "prefixes_per_peer must be a positive integer",
            )
        )
        return
    if (
        isinstance(allocation.network_group_index, bool)
        or not isinstance(allocation.network_group_index, int)
        or allocation.network_group_index < 0
    ):
        issues.append(
            _issue(
                f"{path}.allocation.network_group_index",
                "invalid_network_group_index",
                "network_group_index must be a non-negative integer",
            )
        )
    membership = advertisement.membership
    if (
        isinstance(membership.start_index, bool)
        or not isinstance(membership.start_index, int)
        or membership.start_index < 0
    ):
        issues.append(
            _issue(
                f"{path}.membership.start_index",
                "invalid_membership_start",
                "membership start_index must be a non-negative integer",
            )
        )
        return
    if (
        isinstance(membership.prefix_count, bool)
        or not isinstance(membership.prefix_count, int)
        or membership.prefix_count <= 0
    ):
        issues.append(
            _issue(
                f"{path}.membership.prefix_count",
                "invalid_membership_count",
                "membership prefix_count must be a positive integer",
            )
        )
        return
    required_count = allocation.distinct_prefix_count(peer_count)
    if membership.prefix_count != required_count:
        issues.append(
            _issue(
                f"{path}.membership.prefix_count",
                "prefix_membership_count_mismatch",
                f"membership must contain exactly {required_count} distinct prefixes",
            )
        )
    if (
        prefix_set is not None
        and membership.start_index + membership.prefix_count > prefix_set.source.count
    ):
        issues.append(
            _issue(
                f"{path}.membership",
                "prefix_membership_out_of_range",
                "advertisement membership exceeds the referenced prefix set",
            )
        )
    _validate_next_hop_intent(
        advertisement,
        peer_count,
        afi,
        membership.prefix_count,
        path,
        issues,
    )


def _validate_next_hop_intent(
    advertisement: PrefixAdvertisement,
    peer_count: int,
    afi: str,
    distinct_prefix_count: int,
    path: str,
    issues: list[ValidationIssue],
) -> None:
    next_hop = advertisement.next_hop
    if not _validate_next_hop_types(next_hop, path, issues):
        return
    if next_hop.mode == NextHopMode.SELF:
        _validate_self_next_hop(next_hop, path, issues)
        return
    distribution = _validate_external_next_hop(next_hop, path, issues)
    if distribution is None:
        return
    required = _next_hop_cardinality(
        distribution,
        peer_count,
        advertisement.allocation.prefixes_per_peer,
        distinct_prefix_count,
    )
    _validate_next_hop_source(next_hop, required, afi, path, issues)


def _validate_next_hop_types(
    next_hop: NextHopIntent,
    path: str,
    issues: list[ValidationIssue],
) -> bool:
    if not isinstance(next_hop.mode, NextHopMode):
        issues.append(
            _issue(
                f"{path}.next_hop.mode",
                "invalid_next_hop_mode",
                "next-hop mode must be a NextHopMode",
            )
        )
        return False
    if next_hop.self_realization is not None and not isinstance(
        next_hop.self_realization,
        SelfNextHopRealization,
    ):
        issues.append(
            _issue(
                f"{path}.next_hop.self_realization",
                "invalid_self_next_hop_realization",
                "self next-hop realization must be a SelfNextHopRealization",
            )
        )
        return False
    return True


def _validate_self_next_hop(
    next_hop: NextHopIntent,
    path: str,
    issues: list[ValidationIssue],
) -> None:
    if any(
        value is not None
        for value in (
            next_hop.distribution,
            next_hop.formulaic_source,
            next_hop.explicit_source,
            next_hop.description,
        )
    ):
        issues.append(
            _issue(
                f"{path}.next_hop",
                "invalid_self_next_hop",
                "SELF next hop cannot carry a source or distribution",
            )
        )


def _validate_external_next_hop(
    next_hop: NextHopIntent,
    path: str,
    issues: list[ValidationIssue],
) -> NextHopDistribution | None:
    if next_hop.self_realization is not None:
        issues.append(
            _issue(
                f"{path}.next_hop.self_realization",
                "invalid_self_next_hop_realization",
                "only SELF next hop can select a self realization",
            )
        )
    if next_hop.distribution is None:
        issues.append(
            _issue(
                f"{path}.next_hop.distribution",
                "next_hop_distribution_required",
                "non-SELF next hop requires an explicit distribution",
            )
        )
        return None
    if not isinstance(next_hop.distribution, NextHopDistribution):
        issues.append(
            _issue(
                f"{path}.next_hop.distribution",
                "invalid_next_hop_distribution",
                "next-hop distribution must be a NextHopDistribution",
            )
        )
        return None
    if not next_hop.description or not next_hop.description.strip():
        issues.append(
            _issue(
                f"{path}.next_hop.description",
                "external_next_hop_description_required",
                "external next-hop reachability requires a description",
            )
        )
    return next_hop.distribution


def _validate_next_hop_source(
    next_hop: NextHopIntent,
    required: int,
    afi: str,
    path: str,
    issues: list[ValidationIssue],
) -> None:
    if next_hop.mode == NextHopMode.FORMULAIC:
        if next_hop.formulaic_source is None or next_hop.explicit_source is not None:
            issues.append(
                _issue(
                    f"{path}.next_hop",
                    "invalid_formulaic_next_hop",
                    "FORMULAIC next hop requires only formulaic_source",
                )
            )
            return
        _validate_formulaic_next_hops(
            next_hop.formulaic_source,
            required,
            afi,
            path,
            issues,
        )
    elif next_hop.mode == NextHopMode.EXPLICIT:
        source = next_hop.explicit_source
        if source is None or next_hop.formulaic_source is not None:
            issues.append(
                _issue(
                    f"{path}.next_hop",
                    "invalid_explicit_next_hop",
                    "EXPLICIT next hop requires only explicit_source",
                )
            )
        elif len(source.addresses) != required:
            issues.append(
                _issue(
                    f"{path}.next_hop.explicit_source.addresses",
                    "next_hop_cardinality_mismatch",
                    f"explicit next-hop source must contain exactly {required} addresses",
                )
            )
        else:
            _validate_explicit_next_hops(source, afi, path, issues)


def _validate_formulaic_next_hops(
    source: t.Any,
    count: int,
    expected_afi: str,
    path: str,
    issues: list[ValidationIssue],
) -> None:
    if count <= 0:
        issues.append(
            _issue(
                f"{path}.next_hop.formulaic_source",
                "invalid_next_hop_count",
                "formulaic next-hop count must be positive",
            )
        )
        return
    parsed_start = _parse_ip(source.start, "v4") or _parse_ip(source.start, "v6")
    if parsed_start is None:
        issues.append(
            _issue(
                f"{path}.next_hop.formulaic_source.start",
                "invalid_next_hop_start",
                "formulaic next-hop start must be an IP address",
            )
        )
        return
    afi = "v4" if parsed_start.version == 4 else "v6"
    if afi != expected_afi:
        issues.append(
            _issue(
                f"{path}.next_hop.formulaic_source.start",
                "next_hop_afi_mismatch",
                "next-hop AFI must match the advertising device group",
            )
        )
        return
    parsed_parent = _parse_network(source.parent_network, afi)
    step = _parse_positive_ip_step(source.step, afi)
    if parsed_parent is None or step is None:
        issues.append(
            _issue(
                f"{path}.next_hop.formulaic_source",
                "invalid_next_hop_formula",
                "next-hop step and parent network must match its AFI",
            )
        )
        return
    terminal = int(parsed_start) + step * (count - 1)
    if (
        terminal >= 1 << parsed_start.max_prefixlen
        or parsed_start not in parsed_parent
        or ipaddress.ip_address(terminal) not in parsed_parent
    ):
        issues.append(
            _issue(
                f"{path}.next_hop.formulaic_source",
                "next_hop_formula_out_of_range",
                "formulaic next-hop sequence exceeds its parent network",
            )
        )


def _validate_explicit_next_hops(
    source: t.Any,
    expected_afi: str,
    path: str,
    issues: list[ValidationIssue],
) -> None:
    afi = None
    try:
        parent = ipaddress.ip_network(source.parent_network, strict=False)
        afi = "v4" if parent.version == 4 else "v6"
    except ValueError:
        issues.append(
            _issue(
                f"{path}.next_hop.explicit_source.parent_network",
                "invalid_parent_network",
                "explicit next-hop parent network is invalid",
            )
        )
        return
    if afi != expected_afi:
        issues.append(
            _issue(
                f"{path}.next_hop.explicit_source.parent_network",
                "next_hop_afi_mismatch",
                "next-hop AFI must match the advertising device group",
            )
        )
        return
    for index, address in enumerate(source.addresses):
        parsed = _parse_ip(address, afi)
        if parsed is None or parsed not in parent:
            issues.append(
                _issue(
                    f"{path}.next_hop.explicit_source.addresses[{index}]",
                    "invalid_explicit_next_hop",
                    "explicit next hop must match and belong to parent_network",
                )
            )


def _next_hop_cardinality(
    distribution: NextHopDistribution,
    peer_count: int,
    prefixes_per_peer: int,
    distinct_prefix_count: int,
) -> int:
    if distribution == NextHopDistribution.SHARED:
        return 1
    if distribution == NextHopDistribution.PER_PEER:
        return peer_count
    if distribution == NextHopDistribution.PER_PREFIX:
        return distinct_prefix_count
    return peer_count * prefixes_per_peer


def _parse_ip(
    value: t.Any, afi: str
) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        parsed = ipaddress.ip_address(value)
    except ValueError:
        return None
    if (afi == "v4" and parsed.version != 4) or (afi == "v6" and parsed.version != 6):
        return None
    return parsed


def _parse_network(
    value: t.Any,
    afi: str,
) -> ipaddress.IPv4Network | ipaddress.IPv6Network | None:
    try:
        parsed = ipaddress.ip_network(value, strict=False)
    except ValueError:
        return None
    if (afi == "v4" and parsed.version != 4) or (afi == "v6" and parsed.version != 6):
        return None
    return parsed


def _parse_positive_ip_step(value: t.Any, afi: str) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    parsed = _parse_ip(value, afi)
    if parsed is None or int(parsed) <= 0:
        return None
    return int(parsed)


def _validate_logical_topology_traffic_flows(
    logical_topology: LogicalTopology,
    dg_names: set[str],
    prefix_pool_names: set[str],
    issues: list[ValidationIssue],
) -> None:
    for index, traffic_flow in enumerate(logical_topology.traffic_flows):
        _validate_traffic_flow(
            traffic_flow,
            f"traffic_flows[{index}]",
            dg_names,
            prefix_pool_names,
            issues,
        )


def _validate_route_senders(
    logical_topology: LogicalTopology,
    issues: list[ValidationIssue],
) -> None:
    device_group_by_name = {
        device_group.name: device_group
        for device_group in logical_topology.device_groups
        if device_group.name
    }
    seen: dict[tuple[str, str], int] = {}
    for index, sender in enumerate(logical_topology.route_senders):
        path = f"route_senders[{index}]"
        device_group = device_group_by_name.get(sender.device_group)
        if device_group is None:
            issues.append(
                _issue(
                    f"{path}.device_group",
                    "unknown_device_group",
                    f"device group {sender.device_group!r} is not declared",
                )
            )
        elif sender.prefix_advertisement not in {
            advertisement.name for advertisement in device_group.prefix_advertisements
        }:
            issues.append(
                _issue(
                    f"{path}.prefix_advertisement",
                    "unknown_prefix_advertisement",
                    (
                        f"prefix advertisement {sender.prefix_advertisement!r} is "
                        f"not attached to device group {sender.device_group!r}"
                    ),
                )
            )
        key = (sender.device_group, sender.prefix_advertisement)
        previous_index = seen.get(key)
        if previous_index is not None:
            issues.append(
                _issue(
                    path,
                    "duplicate_route_sender",
                    f"route sender is already declared at route_senders[{previous_index}]",
                )
            )
        else:
            seen[key] = index


def _validate_endpoint(
    endpoint: EndpointSpec,
    path: str,
    issues: list[ValidationIssue],
) -> None:
    if not endpoint.name:
        issues.append(
            _issue(f"{path}.name", "name_required", "endpoint name is required")
        )
    if not endpoint.role:
        issues.append(
            _issue(f"{path}.role", "role_required", "endpoint role is required")
        )
    if endpoint.kind not in VALID_ENDPOINT_KINDS:
        issues.append(
            _issue(
                f"{path}.kind",
                "unsupported_endpoint_kind",
                f"unsupported endpoint kind {endpoint.kind!r}",
            )
        )
    if (
        endpoint.required_os is not None
        and endpoint.required_os not in VALID_ENDPOINT_REQUIRED_OS
    ):
        issues.append(
            _issue(
                f"{path}.required_os",
                "unsupported_required_os",
                f"unsupported required_os {endpoint.required_os!r}",
            )
        )
    if endpoint.setup_mode not in VALID_ENDPOINT_SETUP_MODES:
        issues.append(
            _issue(
                f"{path}.setup_mode",
                "unsupported_setup_mode",
                f"unsupported setup mode {endpoint.setup_mode!r}",
            )
        )
    if _endpoint_is_dut(endpoint) and endpoint.required_os == "ixia":
        issues.append(
            _issue(
                f"{path}.required_os",
                "ixia_required_os_on_dut",
                "DUT endpoints cannot require IXIA OS",
            )
        )


def _validate_device_group(
    dg: DeviceGroupSpec,
    path: str,
    endpoint_names: set[str],
    endpoint_by_name: t.Mapping[str, EndpointSpec],
    traffic_flow_dg_names: set[str],
    traffic_flow_prefix_pool_names: set[str],
    issues: list[ValidationIssue],
) -> None:
    _validate_device_group_basics(dg, path, issues)
    _validate_device_group_endpoints(
        dg,
        path,
        endpoint_names,
        endpoint_by_name,
        issues,
    )
    _validate_device_group_routing_driver(dg, path, issues)
    _validate_device_group_port_assignment(dg, path, endpoint_by_name, issues)
    _validate_device_group_partition(dg, path, issues)
    _validate_ixia_children(dg, path, endpoint_by_name, issues)
    _validate_route_attribute_pool(
        dg.route_attributes,
        f"{path}.route_attributes",
        issues,
    )

    _validate_address_plan(
        address_plan=dg.address_plan,
        path=f"{path}.address_plan",
        peer_count=dg.peer_count,
        expected_afi=dg.afi,
        issues=issues,
    )

    if isinstance(dg.peer_group, BgpPeerGroup):
        _validate_peer_group(dg.peer_group, f"{path}.peer_group", issues)

    _validate_device_group_prefix_pools(dg, path, issues)
    _validate_device_group_traffic_flows(
        dg,
        path,
        traffic_flow_dg_names,
        traffic_flow_prefix_pool_names,
        issues,
    )

    if dg.routing_device_config is not None:
        _validate_routing_device_config(
            dg.routing_device_config,
            f"{path}.routing_device_config",
            issues,
        )


def _validate_device_group_basics(
    dg: DeviceGroupSpec,
    path: str,
    issues: list[ValidationIssue],
) -> None:
    if not dg.name:
        issues.append(
            _issue(f"{path}.name", "name_required", "device group name is required")
        )
    elif not dg.name.startswith("dg_"):
        issues.append(
            _issue(
                f"{path}.name",
                "invalid_dg_name",
                'expected device group name to start with "dg_"',
            )
        )
    if not dg.role:
        issues.append(
            _issue(f"{path}.role", "role_required", "device group role is required")
        )
    if dg.afi not in VALID_AFIS:
        issues.append(
            _issue(f"{path}.afi", "unsupported_afi", f"unsupported AFI {dg.afi!r}")
        )
    if dg.peer_count <= 0:
        issues.append(
            _issue(
                f"{path}.peer_count",
                "invalid_peer_count",
                "peer_count must be positive",
            )
        )
    if dg.legacy_ixia_bgp_peer_name is not None and (
        not isinstance(dg.legacy_ixia_bgp_peer_name, str)
        or not dg.legacy_ixia_bgp_peer_name
    ):
        issues.append(
            _issue(
                f"{path}.legacy_ixia_bgp_peer_name",
                "invalid_legacy_ixia_bgp_peer_name",
                "legacy IXIA BGP peer name must be a nonempty string when set",
            )
        )


def _validate_device_group_endpoints(
    dg: DeviceGroupSpec,
    path: str,
    endpoint_names: set[str],
    endpoint_by_name: t.Mapping[str, EndpointSpec],
    issues: list[ValidationIssue],
) -> None:
    if dg.a_endpoint == dg.z_endpoint:
        issues.append(
            _issue(
                f"{path}.z_endpoint",
                "same_endpoint_reference",
                "A and Z endpoints must be different",
            )
        )
    for attr in ("a_endpoint", "z_endpoint"):
        endpoint_name = getattr(dg, attr)
        if endpoint_name not in endpoint_names:
            issues.append(
                _issue(
                    f"{path}.{attr}",
                    "unknown_endpoint",
                    f"endpoint {endpoint_name!r} is not declared",
                )
            )
    a_endpoint = endpoint_by_name.get(dg.a_endpoint)
    z_endpoint = endpoint_by_name.get(dg.z_endpoint)
    if (
        a_endpoint is not None
        and z_endpoint is not None
        and not _endpoint_is_dut(a_endpoint)
        and _endpoint_is_dut(z_endpoint)
    ):
        issues.append(
            _issue(
                f"{path}.a_endpoint",
                "incompatible_backend_constraint",
                "routing device groups require the DUT endpoint on the A side",
            )
        )


def _validate_device_group_routing_driver(
    dg: DeviceGroupSpec,
    path: str,
    issues: list[ValidationIssue],
) -> None:
    if dg.routing_driver is not None and dg.routing_driver not in VALID_ROUTING_DRIVERS:
        issues.append(
            _issue(
                f"{path}.routing_driver",
                "unsupported_routing_driver",
                f"unsupported routing driver {dg.routing_driver!r}",
            )
        )


def _validate_device_group_port_assignment(
    dg: DeviceGroupSpec,
    path: str,
    endpoint_by_name: t.Mapping[str, EndpointSpec],
    issues: list[ValidationIssue],
) -> None:
    ixia_facing = any(
        _endpoint_is_ixia(endpoint_by_name.get(endpoint_name))
        for endpoint_name in (dg.a_endpoint, dg.z_endpoint)
    )
    endpoints_resolved = all(
        endpoint_name in endpoint_by_name
        for endpoint_name in (dg.a_endpoint, dg.z_endpoint)
    )
    if (
        ixia_facing
        and not dg.ixia_children
        and dg.legacy_ixia_device_group_index is None
    ):
        issues.append(
            _issue(
                f"{path}.legacy_ixia_device_group_index",
                "ixia_device_group_index_required",
                "IXIA-facing device groups require an explicit legacy IXIA index",
            )
        )
    assignment = dg.port_assignment
    if ixia_facing and assignment is None:
        issues.append(
            _issue(
                f"{path}.port_assignment",
                "ixia_port_assignment_required",
                "IXIA-facing device groups require an explicit port assignment",
            )
        )
        return
    if assignment is None:
        return
    if not isinstance(assignment, IxiaPortAssignment):
        issues.append(
            _issue(
                f"{path}.port_assignment",
                "invalid_ixia_port_assignment",
                "port_assignment must be an IxiaPortAssignment",
            )
        )
        return
    if endpoints_resolved and not ixia_facing:
        issues.append(
            _issue(
                f"{path}.port_assignment",
                "unexpected_ixia_port_assignment",
                "non-IXIA device groups cannot declare an IXIA port assignment",
            )
        )
    if (
        not isinstance(assignment.logical_role, str)
        or not assignment.logical_role.strip()
    ):
        issues.append(
            _issue(
                f"{path}.port_assignment.logical_role",
                "logical_port_role_required",
                "logical port role must be a non-empty string",
            )
        )
    elif assignment.logical_role != assignment.logical_role.strip():
        issues.append(
            _issue(
                f"{path}.port_assignment.logical_role",
                "invalid_logical_port_role",
                "logical port role must not contain surrounding whitespace",
            )
        )
    if assignment.reuse_group is not None and (
        not isinstance(assignment.reuse_group, str)
        or not assignment.reuse_group.strip()
        or assignment.reuse_group != assignment.reuse_group.strip()
    ):
        issues.append(
            _issue(
                f"{path}.port_assignment.reuse_group",
                "invalid_port_reuse_group",
                "reuse_group must be non-empty without surrounding whitespace",
            )
        )
    if not isinstance(
        assignment.endpoint_label_style,
        IxiaEndpointPortLabelStyle,
    ):
        issues.append(
            _issue(
                f"{path}.port_assignment.endpoint_label_style",
                "invalid_ixia_endpoint_port_label_style",
                "endpoint label style must be an IxiaEndpointPortLabelStyle",
            )
        )


def _validate_ixia_children(
    dg: DeviceGroupSpec,
    path: str,
    endpoint_by_name: t.Mapping[str, EndpointSpec],
    issues: list[ValidationIssue],
) -> None:
    if not dg.ixia_children:
        return
    _validate_ixia_child_parent(dg, path, endpoint_by_name, issues)
    expected_start = 0
    for expected_ordinal, child in enumerate(dg.ixia_children):
        child_path = f"{path}.ixia_children[{expected_ordinal}]"
        if not isinstance(child, IxiaDeviceGroupChild):
            issues.append(
                _issue(
                    child_path,
                    "invalid_ixia_child",
                    "IXIA child must be an IxiaDeviceGroupChild",
                )
            )
            continue
        _validate_ixia_child_metadata(child, child_path, dg, issues)
        expected_start = _validate_ixia_child_window(
            child,
            child_path,
            expected_ordinal,
            expected_start,
            issues,
        )
    _validate_ixia_child_indices(dg, path, issues)
    if expected_start != dg.peer_count:
        issues.append(
            _issue(
                f"{path}.ixia_children",
                "ixia_child_total_mismatch",
                "IXIA child peer windows must exactly cover the parent peer count",
            )
        )


def _validate_ixia_child_indices(
    parent: DeviceGroupSpec,
    path: str,
    issues: list[ValidationIssue],
) -> None:
    owner_by_index: dict[int, int] = {}
    for child_index, child in enumerate(parent.ixia_children):
        if not isinstance(child, IxiaDeviceGroupChild):
            continue
        index = child.legacy_ixia_device_group_index
        if not isinstance(index, int) or isinstance(index, bool) or index < 0:
            continue
        prior_child_index = owner_by_index.get(index)
        if prior_child_index is not None:
            issues.append(
                _issue(
                    (
                        f"{path}.ixia_children[{child_index}]"
                        ".legacy_ixia_device_group_index"
                    ),
                    "duplicate_ixia_device_group_index",
                    (
                        f"legacy IXIA index {index} is already used by sibling "
                        f"child {prior_child_index}"
                    ),
                )
            )
        else:
            owner_by_index[index] = child_index


def _validate_ixia_child_parent(
    dg: DeviceGroupSpec,
    path: str,
    endpoint_by_name: t.Mapping[str, EndpointSpec],
    issues: list[ValidationIssue],
) -> None:
    ixia_facing = any(
        _endpoint_is_ixia(endpoint_by_name.get(endpoint_name))
        for endpoint_name in (dg.a_endpoint, dg.z_endpoint)
    )
    if not ixia_facing and all(
        endpoint_name in endpoint_by_name
        for endpoint_name in (dg.a_endpoint, dg.z_endpoint)
    ):
        issues.append(
            _issue(
                f"{path}.ixia_children",
                "ixia_children_require_ixia_parent",
                "IXIA children can only be declared by an IXIA-facing parent",
            )
        )
    for field_name in (
        "legacy_ixia_device_group_name",
        "legacy_ixia_bgp_peer_name",
        "legacy_ixia_device_group_index",
    ):
        if getattr(dg, field_name) is not None:
            issues.append(
                _issue(
                    f"{path}.{field_name}",
                    "parent_legacy_leaf_metadata_with_ixia_children",
                    "child-bearing parents cannot also declare legacy leaf metadata",
                )
            )


def _validate_ixia_child_metadata(
    child: IxiaDeviceGroupChild,
    path: str,
    parent: DeviceGroupSpec,
    issues: list[ValidationIssue],
) -> None:
    _validate_ixia_child_name(child, path, issues)
    for field_name in (
        "legacy_ixia_device_group_name",
        "legacy_ixia_bgp_peer_name",
    ):
        _validate_optional_ixia_child_name(child, path, field_name, issues)
    prefix_pool_name = child.legacy_ixia_prefix_pool_name
    if prefix_pool_name is not None and (
        not isinstance(prefix_pool_name, str)
        or not prefix_pool_name.strip()
        or prefix_pool_name != prefix_pool_name.strip()
    ):
        issues.append(
            _issue(
                f"{path}.legacy_ixia_prefix_pool_name",
                "invalid_ixia_child_prefix_pool_name",
                "legacy IXIA prefix-pool override must be non-empty without surrounding whitespace",
            )
        )
    if prefix_pool_name is not None and len(parent.prefix_advertisements) != 1:
        issues.append(
            _issue(
                f"{path}.legacy_ixia_prefix_pool_name",
                "ambiguous_ixia_child_prefix_pool_override",
                "a child prefix-pool override requires exactly one parent advertisement",
            )
        )
    for field_name in (
        "ordinal",
        "start_index",
    ):
        if not _is_non_negative_int(getattr(child, field_name)):
            issues.append(
                _issue(
                    f"{path}.{field_name}",
                    f"invalid_ixia_child_{field_name}",
                    f"IXIA child {field_name} must be a non-negative integer",
                )
            )
    if child.legacy_ixia_device_group_index is not None and not _is_non_negative_int(
        child.legacy_ixia_device_group_index
    ):
        issues.append(
            _issue(
                f"{path}.legacy_ixia_device_group_index",
                "invalid_ixia_child_legacy_ixia_device_group_index",
                "legacy IXIA child device-group index must be non-negative",
            )
        )
    if not _is_non_negative_int(child.peer_count) or child.peer_count == 0:
        issues.append(
            _issue(
                f"{path}.peer_count",
                "invalid_ixia_child_peer_count",
                "IXIA child peer_count must be a positive integer",
            )
        )


def _validate_ixia_child_name(
    child: IxiaDeviceGroupChild,
    path: str,
    issues: list[ValidationIssue],
) -> None:
    if not isinstance(child.name, str) or not child.name.strip():
        issues.append(
            _issue(
                f"{path}.name",
                "ixia_child_name_required",
                "IXIA child name must be a non-empty string",
            )
        )
    elif child.name != child.name.strip():
        issues.append(
            _issue(
                f"{path}.name",
                "invalid_ixia_child_name",
                "IXIA child name cannot contain surrounding whitespace",
            )
        )


def _validate_optional_ixia_child_name(
    child: IxiaDeviceGroupChild,
    path: str,
    field_name: str,
    issues: list[ValidationIssue],
) -> None:
    value = getattr(child, field_name)
    if value is None:
        return
    if not isinstance(value, str) or not value.strip():
        issues.append(
            _issue(
                f"{path}.{field_name}",
                f"invalid_ixia_child_{field_name}",
                f"IXIA child {field_name} must be a non-empty string",
            )
        )
    elif value != value.strip():
        issues.append(
            _issue(
                f"{path}.{field_name}",
                f"invalid_ixia_child_{field_name}",
                f"IXIA child {field_name} cannot contain surrounding whitespace",
            )
        )


def _validate_ixia_child_window(
    child: IxiaDeviceGroupChild,
    path: str,
    expected_ordinal: int,
    expected_start: int,
    issues: list[ValidationIssue],
) -> int:
    if child.ordinal != expected_ordinal:
        issues.append(
            _issue(
                f"{path}.ordinal",
                "ixia_child_ordinal_gap",
                "IXIA child ordinals must start at zero and follow tuple order",
            )
        )
    if _is_non_negative_int(child.start_index) and child.start_index != expected_start:
        code = (
            "ixia_child_peer_overlap"
            if child.start_index < expected_start
            else "ixia_child_peer_gap"
        )
        issues.append(
            _issue(
                f"{path}.start_index",
                code,
                "IXIA child peer windows must start at zero and be contiguous",
            )
        )
    if _is_non_negative_int(child.start_index) and _is_non_negative_int(
        child.peer_count
    ):
        return child.start_index + child.peer_count
    return expected_start


def _validate_ixia_child_names(
    device_groups: t.Sequence[DeviceGroupSpec],
    issues: list[ValidationIssue],
) -> None:
    owner_by_name: dict[str, str] = {}
    for group_index, dg in enumerate(device_groups):
        for child_index, child in enumerate(dg.ixia_children):
            if not isinstance(child, IxiaDeviceGroupChild) or not child.name:
                continue
            path = f"device_groups[{group_index}].ixia_children[{child_index}].name"
            prior_path = owner_by_name.get(child.name)
            if prior_path is not None:
                issues.append(
                    _issue(
                        path,
                        "duplicate_ixia_child_name",
                        f"IXIA child name is already declared at {prior_path}",
                    )
                )
            else:
                owner_by_name[child.name] = path


def _validate_device_group_partition(
    dg: DeviceGroupSpec,
    path: str,
    issues: list[ValidationIssue],
) -> None:
    partition = dg.partition
    if partition is not None:
        if not isinstance(partition, DeviceGroupPartition):
            issues.append(
                _issue(
                    f"{path}.partition",
                    "invalid_device_group_partition",
                    "partition must be a DeviceGroupPartition",
                )
            )
        else:
            if not isinstance(partition.family, str) or not partition.family.strip():
                issues.append(
                    _issue(
                        f"{path}.partition.family",
                        "partition_family_required",
                        "partition family must be a non-empty string",
                    )
                )
            elif partition.family != partition.family.strip():
                issues.append(
                    _issue(
                        f"{path}.partition.family",
                        "invalid_partition_family",
                        "partition family must not contain surrounding whitespace",
                    )
                )
            for field_name in ("ordinal", "start_index", "total_peer_count"):
                value = getattr(partition, field_name)
                if not _is_non_negative_int(value) or (
                    field_name == "total_peer_count" and value == 0
                ):
                    issues.append(
                        _issue(
                            f"{path}.partition.{field_name}",
                            f"invalid_partition_{field_name}",
                            f"{field_name} must be a valid non-negative integer",
                        )
                    )
            if (
                not (dg.address_plan.a_ips or dg.address_plan.z_ips)
                and _is_non_negative_int(partition.start_index)
                and dg.address_plan.start_index != partition.start_index
            ):
                issues.append(
                    _issue(
                        f"{path}.address_plan.start_index",
                        "partition_address_window_mismatch",
                        "address-plan start_index must match partition start_index",
                    )
                )
            _validate_partition_advertisement_windows(dg, path, partition, issues)

    legacy_index = dg.legacy_ixia_device_group_index
    if legacy_index is not None and not _is_non_negative_int(legacy_index):
        issues.append(
            _issue(
                f"{path}.legacy_ixia_device_group_index",
                "invalid_ixia_device_group_index",
                "legacy IXIA device-group index must be non-negative",
            )
        )


def _validate_partition_advertisement_windows(
    dg: DeviceGroupSpec,
    path: str,
    partition: DeviceGroupPartition,
    issues: list[ValidationIssue],
) -> None:
    if not _is_non_negative_int(partition.start_index):
        return
    for index, advertisement in enumerate(dg.prefix_advertisements):
        allocation = advertisement.allocation
        if allocation.peer_distribution is not PeerPrefixDistribution.DISJOINT:
            continue
        expected_start = partition.start_index * allocation.prefixes_per_peer
        expected_count = dg.peer_count * allocation.prefixes_per_peer
        if (
            advertisement.membership.start_index != expected_start
            or advertisement.membership.prefix_count != expected_count
        ):
            issues.append(
                _issue(
                    f"{path}.prefix_advertisements[{index}].membership",
                    "partition_prefix_window_mismatch",
                    (
                        "DISJOINT advertisement membership must match the "
                        "partition peer window"
                    ),
                )
            )


def _validate_device_group_partitions(  # noqa: C901
    device_groups: t.Sequence[DeviceGroupSpec],
    issues: list[ValidationIssue],
) -> None:
    families: dict[str, list[tuple[int, DeviceGroupSpec, DeviceGroupPartition]]] = {}
    for index, dg in enumerate(device_groups):
        partition = dg.partition
        if isinstance(partition, DeviceGroupPartition) and partition.family:
            families.setdefault(partition.family, []).append((index, dg, partition))
    for entries in families.values():
        ordered = sorted(entries, key=lambda entry: entry[2].ordinal)
        first_index, first_dg, _ = ordered[0]
        expected_start = 0
        for expected_ordinal, (index, dg, partition) in enumerate(ordered):
            path = f"device_groups[{index}]"
            if partition.ordinal != expected_ordinal:
                issues.append(
                    _issue(
                        f"{path}.partition.ordinal",
                        "partition_ordinal_gap",
                        "partition ordinals must start at zero and be consecutive",
                    )
                )
            if partition.start_index < expected_start:
                code = "partition_peer_overlap"
            elif partition.start_index > expected_start:
                code = (
                    "partition_start_gap"
                    if expected_ordinal == 0
                    else "partition_peer_gap"
                )
            else:
                code = ""
            if code:
                issues.append(
                    _issue(
                        f"{path}.partition.start_index",
                        code,
                        "partition peer windows must start at zero and be contiguous",
                    )
                )
            if index != first_index:
                mismatch = _partition_geometry_mismatch_path(first_dg, dg, path)
                if mismatch is not None:
                    issues.append(
                        _issue(
                            mismatch,
                            "partition_geometry_mismatch",
                            "partition family members must use matching geometry",
                        )
                    )
            expected_start = partition.start_index + dg.peer_count
        for index, _, partition in ordered:
            if partition.total_peer_count != expected_start:
                issues.append(
                    _issue(
                        f"device_groups[{index}].partition.total_peer_count",
                        "partition_total_mismatch",
                        "total_peer_count must equal the final peer end",
                    )
                )


def _partition_geometry_mismatch_path(
    first: DeviceGroupSpec,
    current: DeviceGroupSpec,
    current_path: str,
) -> str | None:
    if first.afi != current.afi:
        return f"{current_path}.afi"
    if _base_role(first.role) != _base_role(current.role):
        return f"{current_path}.role"
    for field_name in (
        "parent_network",
        "parent_network_key",
        "a_offset",
        "z_offset",
        "stride",
        "increment",
        "prefix_length",
        "mask",
    ):
        if getattr(first.address_plan, field_name) != getattr(
            current.address_plan, field_name
        ):
            return f"{current_path}.address_plan.{field_name}"
    if first.peer_group != current.peer_group:
        return f"{current_path}.peer_group"
    if first.port_assignment != current.port_assignment:
        return f"{current_path}.port_assignment"
    if _partition_advertisement_geometry(first) != _partition_advertisement_geometry(
        current
    ):
        return f"{current_path}.prefix_advertisements"
    return None


def _partition_advertisement_geometry(dg: DeviceGroupSpec) -> tuple[t.Any, ...]:
    return tuple(
        (
            advertisement.prefix_set,
            advertisement.allocation.prefixes_per_peer,
            advertisement.allocation.peer_distribution,
        )
        for advertisement in dg.prefix_advertisements
    )


def _validate_device_group_prefix_pools(
    dg: DeviceGroupSpec,
    path: str,
    issues: list[ValidationIssue],
) -> None:
    for index, prefix_pool in enumerate(dg.prefix_pools):
        if prefix_pool.afi != dg.afi:
            issues.append(
                _issue(
                    f"{path}.prefix_pools[{index}].afi",
                    "prefix_pool_afi_mismatch",
                    "prefix pool AFI must match device group AFI",
                )
            )
        _validate_prefix_pool(prefix_pool, f"{path}.prefix_pools[{index}]", issues)


def _validate_device_group_traffic_flows(
    dg: DeviceGroupSpec,
    path: str,
    traffic_flow_dg_names: set[str],
    traffic_flow_prefix_pool_names: set[str],
    issues: list[ValidationIssue],
) -> None:
    for index, traffic_flow in enumerate(dg.traffic_flows):
        _validate_traffic_flow(
            traffic_flow,
            f"{path}.traffic_flows[{index}]",
            traffic_flow_dg_names,
            traffic_flow_prefix_pool_names,
            issues,
        )


def _validate_address_plan(
    address_plan: AddressPlan,
    path: str,
    peer_count: int,
    expected_afi: str,
    issues: list[ValidationIssue],
) -> None:
    _validate_address_plan_afi(address_plan, path, expected_afi, issues)

    has_explicit = bool(address_plan.a_ips or address_plan.z_ips)
    has_parent = bool(address_plan.parent_network or address_plan.parent_network_key)
    has_auto = address_plan.auto_allocate

    _validate_address_plan_mode(
        path,
        has_explicit=has_explicit,
        has_parent=has_parent,
        has_auto=has_auto,
        issues=issues,
    )

    if has_explicit:
        _validate_explicit_addresses(
            address_plan,
            path,
            peer_count,
            expected_afi,
            issues,
        )

    if address_plan.parent_network:
        _validate_network_afi(
            address_plan.parent_network,
            expected_afi,
            f"{path}.parent_network",
            issues,
        )

    _validate_address_plan_offsets(address_plan, path, issues)
    _validate_prefix_length(
        address_plan.prefix_length,
        address_plan.mask,
        expected_afi,
        path,
        issues,
    )


def _validate_address_plan_afi(
    address_plan: AddressPlan,
    path: str,
    expected_afi: str,
    issues: list[ValidationIssue],
) -> None:
    if address_plan.afi not in VALID_AFIS:
        issues.append(
            _issue(
                f"{path}.afi",
                "unsupported_afi",
                f"unsupported AFI {address_plan.afi!r}",
            )
        )
    elif address_plan.afi != expected_afi:
        issues.append(
            _issue(
                f"{path}.afi",
                "address_plan_afi_mismatch",
                "address plan AFI must match device group AFI",
            )
        )


def _validate_address_plan_mode(
    path: str,
    *,
    has_explicit: bool,
    has_parent: bool,
    has_auto: bool,
    issues: list[ValidationIssue],
) -> None:
    mode_count = int(has_explicit) + int(has_parent) + int(has_auto)

    if mode_count == 0:
        issues.append(
            _issue(
                path,
                "address_mode_required",
                "address plan needs explicit IPs, parent network, or auto allocation",
            )
        )
    elif mode_count > 1:
        issues.append(
            _issue(
                path,
                "multiple_address_modes",
                "select exactly one address allocation mode",
            )
        )

    if has_auto:
        issues.append(
            _issue(
                f"{path}.auto_allocate",
                "auto_allocation_unsupported",
                "auto allocation is not enabled in Phase 1",
            )
        )


def _validate_explicit_addresses(
    address_plan: AddressPlan,
    path: str,
    peer_count: int,
    expected_afi: str,
    issues: list[ValidationIssue],
) -> None:
    if not address_plan.a_ips or not address_plan.z_ips:
        issues.append(
            _issue(
                path,
                "explicit_ip_pair_required",
                "explicit address mode requires both a_ips and z_ips",
            )
        )
        return
    if len(address_plan.a_ips) != peer_count:
        issues.append(
            _issue(
                f"{path}.a_ips",
                "ip_count_mismatch",
                f"expected {peer_count} A-side IPs",
            )
        )
    if len(address_plan.z_ips) != peer_count:
        issues.append(
            _issue(
                f"{path}.z_ips",
                "ip_count_mismatch",
                f"expected {peer_count} Z-side IPs",
            )
        )
    for attr, ips in (("a_ips", address_plan.a_ips), ("z_ips", address_plan.z_ips)):
        for index, ip in enumerate(ips):
            _validate_ip_afi(ip, expected_afi, f"{path}.{attr}[{index}]", issues)


def _validate_address_plan_offsets(
    address_plan: AddressPlan,
    path: str,
    issues: list[ValidationIssue],
) -> None:
    for attr in ("a_offset", "z_offset"):
        _validate_non_negative_offset(
            getattr(address_plan, attr), f"{path}.{attr}", issues
        )
    _validate_positive_offset(
        address_plan.stride,
        f"{path}.stride",
        issues,
        code="non_positive_stride",
        message="stride must be positive",
    )
    if address_plan.increment is not None:
        _validate_positive_offset(
            address_plan.increment,
            f"{path}.increment",
            issues,
            code="non_positive_increment",
            message="increment must be positive",
        )
    if address_plan.start_index < 0:
        issues.append(
            _issue(
                f"{path}.start_index",
                "negative_start_index",
                "start_index must be non-negative",
            )
        )


def _validate_peer_group(
    peer_group: BgpPeerGroup,
    path: str,
    issues: list[ValidationIssue],
) -> None:
    if not peer_group.name:
        issues.append(
            _issue(f"{path}.name", "name_required", "peer group name is required")
        )
    _validate_peer_group_asns(peer_group, path, issues)
    _validate_peer_group_timers(peer_group, path, issues)
    _validate_peer_group_route_limit(peer_group, path, issues)
    if peer_group.enable_graceful_restart is not None and not isinstance(
        peer_group.enable_graceful_restart, bool
    ):
        issues.append(
            _issue(
                f"{path}.enable_graceful_restart",
                "invalid_bool",
                "enable_graceful_restart must be a boolean or None",
            )
        )


def _validate_peer_group_asns(
    peer_group: BgpPeerGroup,
    path: str,
    issues: list[ValidationIssue],
) -> None:
    for attr in ("local_asn", "remote_asn"):
        value = getattr(peer_group, attr)
        if isinstance(value, bool):
            issues.append(
                _issue(
                    f"{path}.{attr}",
                    "invalid_asn",
                    "ASN values must be integers or named references",
                )
            )
        elif isinstance(value, int):
            if value <= 0:
                issues.append(
                    _issue(
                        f"{path}.{attr}",
                        "invalid_asn",
                        "ASN values must be positive",
                    )
                )
            elif value > IXIA_MAX_4BYTE_ASN:
                issues.append(
                    _issue(
                        f"{path}.{attr}",
                        "invalid_asn",
                        f"ASN values must be at most {IXIA_MAX_4BYTE_ASN}",
                    )
                )


def _validate_peer_group_timers(
    peer_group: BgpPeerGroup,
    path: str,
    issues: list[ValidationIssue],
) -> None:
    for attr in ("hold_timer_s", "keepalive_timer_s", "connect_retry_timer_s"):
        value = getattr(peer_group, attr)
        if isinstance(value, bool) or not isinstance(value, int):
            issues.append(
                _issue(
                    f"{path}.{attr}",
                    "invalid_timer",
                    "timer values must be integers",
                )
            )
        elif value < 0:
            issues.append(
                _issue(
                    f"{path}.{attr}",
                    "negative_timer",
                    "timer values must be non-negative",
                )
            )


def _validate_peer_group_route_limit(
    peer_group: BgpPeerGroup,
    path: str,
    issues: list[ValidationIssue],
) -> None:
    if isinstance(peer_group.route_limit, bool):
        issues.append(
            _issue(
                f"{path}.route_limit",
                "invalid_limit",
                "route_limit must be an integer or named reference",
            )
        )
    elif isinstance(peer_group.route_limit, int) and peer_group.route_limit < 0:
        issues.append(
            _issue(
                f"{path}.route_limit",
                "negative_limit",
                "route_limit must be non-negative",
            )
        )


def _validate_route_attribute_pool(  # noqa: C901
    attribute_pool: RouteAttributePool | None,
    path: str,
    issues: list[ValidationIssue],
) -> None:
    if attribute_pool is None:
        return
    if not isinstance(attribute_pool, RouteAttributePool):
        issues.append(
            _issue(path, "invalid_route_attribute_pool", "invalid route attribute pool")
        )
        return
    if not isinstance(attribute_pool.distribution, RouteAttributeDistribution):
        issues.append(
            _issue(
                f"{path}.distribution",
                "unsupported_route_attribute_distribution",
                "distribution must be a RouteAttributeDistribution",
            )
        )
    for row_index, row in enumerate(attribute_pool.community_rows):
        row_path = f"{path}.community_rows[{row_index}]"
        if not row:
            issues.append(_issue(row_path, "empty_route_attribute_row", "row is empty"))
        for index, community in enumerate(row):
            item_path = f"{row_path}[{index}]"
            if not isinstance(community, StandardCommunity):
                issues.append(
                    _issue(item_path, "invalid_standard_community", "invalid community")
                )
                continue
            _validate_attribute_integer(
                community.asn,
                f"{item_path}.asn",
                "invalid_standard_community_asn",
                1,
                BGP_STANDARD_COMMUNITY_FIELD_MAX,
                issues,
            )
            _validate_attribute_integer(
                community.value,
                f"{item_path}.value",
                "invalid_standard_community_value",
                0,
                BGP_STANDARD_COMMUNITY_FIELD_MAX,
                issues,
            )
    for row_index, row in enumerate(attribute_pool.extended_community_rows):
        row_path = f"{path}.extended_community_rows[{row_index}]"
        if not row:
            issues.append(_issue(row_path, "empty_route_attribute_row", "row is empty"))
        for index, community in enumerate(row):
            item_path = f"{row_path}[{index}]"
            if not isinstance(community, ExtendedCommunity):
                issues.append(
                    _issue(item_path, "invalid_extended_community", "invalid community")
                )
                continue
            if community.kind is not ExtendedCommunityKind.ROUTE_TARGET:
                issues.append(
                    _issue(
                        f"{item_path}.kind",
                        "unsupported_extended_community_kind",
                        "only route-target communities are supported",
                    )
                )
            _validate_attribute_integer(
                community.administrator,
                f"{item_path}.administrator",
                "invalid_extended_community_administrator",
                1,
                IXIA_MAX_4BYTE_ASN,
                issues,
            )
            _validate_attribute_integer(
                community.assigned_number,
                f"{item_path}.assigned_number",
                "invalid_extended_community_assigned_number",
                0,
                IXIA_MAX_4BYTE_ASN,
                issues,
            )
    for path_index, as_path in enumerate(attribute_pool.as_paths):
        item_path = f"{path}.as_paths[{path_index}]"
        if not isinstance(as_path, AsPathSequence):
            issues.append(_issue(item_path, "invalid_as_path", "invalid AS path"))
            continue
        if not as_path.asns:
            issues.append(
                _issue(f"{item_path}.asns", "empty_as_path", "AS path is empty")
            )
        for index, asn in enumerate(as_path.asns):
            _validate_attribute_integer(
                asn,
                f"{item_path}.asns[{index}]",
                "invalid_as_path_asn",
                1,
                IXIA_MAX_4BYTE_ASN,
                issues,
            )


def _validate_attribute_integer(
    value: t.Any,
    path: str,
    code: str,
    minimum: int,
    maximum: int,
    issues: list[ValidationIssue],
) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < minimum
        or value > maximum
    ):
        issues.append(
            _issue(path, code, f"value must be between {minimum} and {maximum}")
        )


def _validate_prefix_pool(
    prefix_pool: PrefixPool,
    path: str,
    issues: list[ValidationIssue],
) -> None:
    if not prefix_pool.name:
        issues.append(
            _issue(f"{path}.name", "name_required", "prefix pool name is required")
        )
    if prefix_pool.afi not in VALID_AFIS:
        issues.append(
            _issue(
                f"{path}.afi", "unsupported_afi", f"unsupported AFI {prefix_pool.afi!r}"
            )
        )
    if prefix_pool.route_count <= 0:
        issues.append(
            _issue(
                f"{path}.route_count",
                "invalid_route_count",
                "route_count must be positive",
            )
        )
    if not prefix_pool.route_file and not prefix_pool.prefixes:
        issues.append(
            _issue(
                path,
                "prefix_source_required",
                "prefix pool needs a route file or explicit prefixes",
            )
        )
    max_prefix = _max_prefix_for_afi(prefix_pool.afi)
    if prefix_pool.prefix_length is not None and max_prefix is not None:
        if prefix_pool.prefix_length < 0 or prefix_pool.prefix_length > max_prefix:
            issues.append(
                _issue(
                    f"{path}.prefix_length",
                    "invalid_prefix_length",
                    f"prefix_length must be between 0 and {max_prefix}",
                )
            )
    for index, prefix in enumerate(prefix_pool.prefixes):
        _validate_prefix_afi(
            prefix,
            prefix_pool.afi,
            f"{path}.prefixes[{index}]",
            issues,
        )


def _validate_traffic_flow(
    traffic_flow: TrafficFlowSpec,
    path: str,
    dg_names: set[str],
    prefix_pool_names: set[str],
    issues: list[ValidationIssue],
) -> None:
    if not traffic_flow.name:
        issues.append(
            _issue(f"{path}.name", "name_required", "traffic flow name is required")
        )
    _validate_traffic_flow_references(
        traffic_flow,
        path,
        dg_names,
        prefix_pool_names,
        issues,
    )
    _validate_traffic_flow_rates(traffic_flow, path, issues)


def _validate_traffic_flow_references(
    traffic_flow: TrafficFlowSpec,
    path: str,
    dg_names: set[str],
    prefix_pool_names: set[str],
    issues: list[ValidationIssue],
) -> None:
    if traffic_flow.src_dg not in dg_names:
        issues.append(
            _issue(
                f"{path}.src_dg",
                "unknown_device_group",
                f"source device group {traffic_flow.src_dg!r} is not declared",
            )
        )
    if traffic_flow.dst_dg is not None and traffic_flow.dst_dg not in dg_names:
        issues.append(
            _issue(
                f"{path}.dst_dg",
                "unknown_device_group",
                f"destination device group {traffic_flow.dst_dg!r} is not declared",
            )
        )
    if (
        traffic_flow.dst_prefix_pool is not None
        and traffic_flow.dst_prefix_pool not in prefix_pool_names
    ):
        issues.append(
            _issue(
                f"{path}.dst_prefix_pool",
                "unknown_prefix_pool",
                f"destination prefix pool {traffic_flow.dst_prefix_pool!r} is not declared",
            )
        )
    if traffic_flow.dst_dg is None and traffic_flow.dst_prefix_pool is None:
        issues.append(
            _issue(
                path,
                "missing_destination_selector",
                "traffic flow needs dst_dg or dst_prefix_pool",
            )
        )


def _validate_traffic_flow_rates(
    traffic_flow: TrafficFlowSpec,
    path: str,
    issues: list[ValidationIssue],
) -> None:
    if traffic_flow.rate_percent is not None and not (
        0 <= traffic_flow.rate_percent <= 100
    ):
        issues.append(
            _issue(
                f"{path}.rate_percent",
                "rate_percent_out_of_range",
                "rate_percent must be between 0 and 100",
            )
        )
    if traffic_flow.rate_bps is not None and traffic_flow.rate_bps < 0:
        issues.append(
            _issue(
                f"{path}.rate_bps",
                "negative_rate",
                "traffic rate must be non-negative",
            )
        )
    if traffic_flow.frame_size_bytes is not None and traffic_flow.frame_size_bytes < 0:
        issues.append(
            _issue(
                f"{path}.frame_size_bytes",
                "negative_frame_size",
                "frame size must be non-negative",
            )
        )


def collect_routing_device_config_issues(
    config: RoutingDeviceConfig,
    path: str = "device_config",
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    _validate_routing_device_config(config, path, issues)
    return issues


def _validate_routing_device_config(
    config: RoutingDeviceConfig,
    path: str,
    issues: list[ValidationIssue],
) -> None:
    for attr in (
        "update_group_enable",
        "enable_next_hop_tracking",
        "enable_dynamic_policy_evaluation",
    ):
        if not isinstance(getattr(config, attr), bool):
            issues.append(
                _issue(
                    f"{path}.{attr}",
                    "invalid_bool",
                    f"{attr} must be a bool",
                )
            )
    if not isinstance(config.openr_mode, OpenRMode):
        issues.append(
            _issue(
                f"{path}.openr_mode",
                "invalid_openr_mode",
                "openr_mode must be an OpenRMode member",
            )
        )
    logging_config_override = config.bgpcpp_logging_config_override
    if logging_config_override is not None and (
        not isinstance(logging_config_override, str)
        or not logging_config_override
        or any(char in logging_config_override for char in "\x00\r\n")
    ):
        issues.append(
            _issue(
                f"{path}.bgpcpp_logging_config_override",
                "invalid_logging_config",
                (
                    "bgpcpp_logging_config_override must be None or a non-empty "
                    "single-line string"
                ),
            )
        )
    for attr in ("route_limit", "prefix_limit", "per_peer_max_route_limit"):
        value = getattr(config, attr)
        if isinstance(value, bool):
            issues.append(
                _issue(
                    f"{path}.{attr}",
                    "invalid_limit",
                    f"{attr} must be an integer or named reference",
                )
            )
        elif isinstance(value, int) and value < 0:
            issues.append(
                _issue(
                    f"{path}.{attr}",
                    "negative_limit",
                    f"{attr} must be non-negative",
                )
            )
    for attr in (
        "bgp_hold_timer_s",
        "bgp_keepalive_timer_s",
        "bgp_connect_retry_timer_s",
        "graceful_restart_timer_s",
    ):
        value = getattr(config, attr)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, int):
            issues.append(
                _issue(
                    f"{path}.{attr}",
                    "invalid_timer",
                    f"{attr} must be an integer",
                )
            )
        elif value < 0:
            issues.append(
                _issue(
                    f"{path}.{attr}",
                    "negative_timer",
                    f"{attr} must be non-negative",
                )
            )


def _check_unique_names(
    *,
    issues: list[ValidationIssue],
    objects: t.Iterable[t.Any],
    path_prefix: str,
    code: str,
) -> set[str]:
    seen: dict[str, int] = {}
    names: set[str] = set()
    for index, obj in enumerate(objects):
        name = getattr(obj, "name", "")
        if not name:
            continue
        if name in seen:
            issues.append(
                _issue(
                    f"{path_prefix}[{index}].name",
                    code,
                    f"name {name!r} is already used at {path_prefix}[{seen[name]}]",
                )
            )
        else:
            seen[name] = index
            names.add(name)
    return names


def _check_prefix_pool_names(
    logical_topology: LogicalTopology,
    issues: list[ValidationIssue],
) -> set[str]:
    seen: dict[str, list[tuple[str, str, PrefixPool]]] = {}
    flagged_names: set[str] = set()
    names: set[str] = set()

    for namespace, path, prefix_pool in _iter_prefix_pools(logical_topology):
        if not prefix_pool.name:
            continue
        previous_entries = seen.setdefault(prefix_pool.name, [])
        same_namespace_entry = next(
            (
                (previous_path, previous_pool)
                for previous_namespace, previous_path, previous_pool in previous_entries
                if previous_namespace == namespace
            ),
            None,
        )
        incompatible_entry = next(
            (
                (previous_path, previous_pool)
                for previous_namespace, previous_path, previous_pool in previous_entries
                if previous_namespace != namespace and previous_pool != prefix_pool
            ),
            None,
        )
        duplicate_entry = same_namespace_entry or incompatible_entry
        if duplicate_entry is not None and prefix_pool.name not in flagged_names:
            first_path, _ = duplicate_entry
            issues.append(
                _issue(
                    f"{path}.name",
                    "duplicate_prefix_pool_name",
                    f"name {prefix_pool.name!r} is already used at {first_path}",
                )
            )
            flagged_names.add(prefix_pool.name)
        previous_entries.append((namespace, path, prefix_pool))
        names.add(prefix_pool.name)

    return names


def _iter_prefix_pools(
    logical_topology: LogicalTopology,
) -> t.Iterator[tuple[str, str, PrefixPool]]:
    for index, prefix_pool in enumerate(logical_topology.prefix_pools):
        yield "prefix_pools", f"prefix_pools[{index}]", prefix_pool
    for dg_index, dg in enumerate(logical_topology.device_groups):
        namespace = f"device_groups[{dg_index}].prefix_pools"
        for prefix_pool_index, prefix_pool in enumerate(dg.prefix_pools):
            yield (
                namespace,
                f"device_groups[{dg_index}].prefix_pools[{prefix_pool_index}]",
                prefix_pool,
            )


def _max_prefix_for_afi(expected_afi: str) -> int | None:
    if expected_afi == "v4":
        return 32
    if expected_afi == "v6":
        return 128
    return None


def _endpoint_is_dut(endpoint: EndpointSpec) -> bool:
    if not endpoint.role:
        return False
    return endpoint.role == "dut" or (
        endpoint.kind == "dut" and endpoint.role not in TRAFFIC_ENDPOINT_ROLES
    )


def _endpoint_is_ixia(endpoint: EndpointSpec | None) -> bool:
    return endpoint is not None and (
        endpoint.role in TRAFFIC_ENDPOINT_ROLES
        or (endpoint.kind in TRAFFIC_ENDPOINT_ROLES and endpoint.role != "dut")
    )


def _base_role(role: str) -> str:
    return role.split("_", 1)[0]


def _is_non_negative_int(value: t.Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and value >= 0


def _validate_ip_afi(
    value: str,
    expected_afi: str,
    path: str,
    issues: list[ValidationIssue],
) -> None:
    try:
        parsed = ipaddress.ip_address(value)
    except ValueError:
        issues.append(_issue(path, "invalid_ip", f"invalid IP address {value!r}"))
        return
    if expected_afi == "v4" and parsed.version != 4:
        issues.append(_issue(path, "ip_afi_mismatch", "expected IPv4 address"))
    if expected_afi == "v6" and parsed.version != 6:
        issues.append(_issue(path, "ip_afi_mismatch", "expected IPv6 address"))


def _validate_network_afi(
    value: str,
    expected_afi: str,
    path: str,
    issues: list[ValidationIssue],
) -> None:
    try:
        parsed = ipaddress.ip_network(value, strict=False)
    except ValueError:
        issues.append(_issue(path, "invalid_network", f"invalid IP network {value!r}"))
        return
    if expected_afi == "v4" and parsed.version != 4:
        issues.append(
            _issue(path, "parent_network_afi_mismatch", "expected IPv4 network")
        )
    if expected_afi == "v6" and parsed.version != 6:
        issues.append(
            _issue(path, "parent_network_afi_mismatch", "expected IPv6 network")
        )


def _validate_prefix_afi(
    value: str,
    expected_afi: str,
    path: str,
    issues: list[ValidationIssue],
) -> None:
    if "/" not in value:
        issues.append(_issue(path, "invalid_prefix", "prefix must use CIDR notation"))
        return
    try:
        parsed = ipaddress.ip_network(value)
    except ValueError:
        issues.append(_issue(path, "invalid_prefix", f"invalid IP prefix {value!r}"))
        return
    if expected_afi == "v4" and parsed.version != 4:
        issues.append(_issue(path, "prefix_afi_mismatch", "expected IPv4 prefix"))
    if expected_afi == "v6" and parsed.version != 6:
        issues.append(_issue(path, "prefix_afi_mismatch", "expected IPv6 prefix"))


def _validate_non_negative_offset(
    value: int | str | None,
    path: str,
    issues: list[ValidationIssue],
) -> None:
    if isinstance(value, int) and value < 0:
        issues.append(_issue(path, "negative_offset", "offset must be non-negative"))


def _validate_positive_offset(
    value: int | str,
    path: str,
    issues: list[ValidationIssue],
    *,
    code: str,
    message: str,
) -> None:
    if isinstance(value, int) and value <= 0:
        issues.append(_issue(path, code, message))


def _validate_prefix_length(
    prefix_length: int | None,
    mask: str | None,
    expected_afi: str,
    path: str,
    issues: list[ValidationIssue],
) -> None:
    if prefix_length is None and mask is None:
        return
    max_prefix = _max_prefix_for_afi(expected_afi)
    if max_prefix is None:
        return
    prefix_length_valid = prefix_length is None
    if prefix_length is not None:
        if prefix_length < 0 or prefix_length > max_prefix:
            issues.append(
                _issue(
                    f"{path}.prefix_length",
                    "invalid_prefix_length",
                    f"prefix_length must be between 0 and {max_prefix}",
                )
            )
        else:
            prefix_length_valid = True
    parsed_mask: int | None = None
    mask_valid = mask is None
    if mask is not None:
        try:
            parsed_mask = int(mask)
        except ValueError:
            issues.append(
                _issue(f"{path}.mask", "invalid_prefix_length", "mask must be numeric")
            )
            return
        if parsed_mask < 0 or parsed_mask > max_prefix:
            issues.append(
                _issue(
                    f"{path}.mask",
                    "invalid_prefix_length",
                    f"mask must be between 0 and {max_prefix}",
                )
            )
        else:
            mask_valid = True
    if (
        prefix_length is not None
        and parsed_mask is not None
        and prefix_length_valid
        and mask_valid
        and prefix_length != parsed_mask
    ):
        issues.append(
            _issue(
                f"{path}.mask",
                "prefix_length_mask_mismatch",
                "prefix_length and mask must match when both are set",
            )
        )


def _issue(
    path: str,
    code: str,
    message: str,
    hint: str | None = None,
) -> ValidationIssue:
    return ValidationIssue(path=path, code=code, message=message, hint=hint)
