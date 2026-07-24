# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

import dataclasses
import typing as t
from collections import Counter

from ixia.ixia import types as ixia_types
from taac.test_as_a_config import types as taac_types


IXIA_PROFILE_MODES: tuple[str, ...] = ("auto", "primary", "secondary")
_T = t.TypeVar("_T")


@dataclasses.dataclass(frozen=True)
class IxiaCandidate:
    name: str
    api_server_ip: str | None
    endpoints: tuple[taac_types.Endpoint, ...]
    setup_tasks: tuple[taac_types.Task, ...]
    teardown_tasks: tuple[taac_types.Task, ...]
    basic_port_configs: tuple[taac_types.BasicPortConfig, ...]
    basic_traffic_item_configs: tuple[taac_types.BasicTrafficItemConfig, ...]
    default_basic_port_config: taac_types.BasicPortConfig | None
    user_defined_traffic_items: tuple[ixia_types.TrafficItem, ...]
    snake_configs: tuple[taac_types.SnakeConfig, ...]
    ptp_configs: tuple[ixia_types.PTPConfig, ...]


def _as_tuple(values: t.Iterable[_T] | None) -> tuple[_T, ...]:
    return tuple(values or ())


def _validate_endpoint_contract(
    primary: IxiaCandidate, secondary: IxiaCandidate
) -> None:
    primary_endpoints = {endpoint.name for endpoint in primary.endpoints}
    secondary_endpoints = {endpoint.name for endpoint in secondary.endpoints}
    if primary_endpoints != secondary_endpoints:
        raise ValueError(
            "Primary and secondary IXIA profiles must define the same endpoint "
            f"names: primary={sorted(primary_endpoints)}, "
            f"secondary={sorted(secondary_endpoints)}"
        )

    primary_duts = {endpoint.name for endpoint in primary.endpoints if endpoint.dut}
    secondary_duts = {endpoint.name for endpoint in secondary.endpoints if endpoint.dut}
    if primary_duts != secondary_duts:
        raise ValueError(
            "Primary and secondary IXIA profiles must define the same DUTs: "
            f"primary={sorted(primary_duts)}, secondary={sorted(secondary_duts)}"
        )

    # Pre-IXIA task PAYLOADS may differ when the two profiles bind different
    # DUT interfaces (e.g., BAG013 primary=Et3/35/*, secondary=Et3/36/*). Only
    # the task COUNT is validated here; the runner executes the first
    # candidate's pre-IXIA tasks. Configure DUT-side setup to be
    # interface-agnostic in dual-chassis configs.
    primary_pre_ixia = tuple(
        task for task in primary.setup_tasks if not task.ixia_needed
    )
    secondary_pre_ixia = tuple(
        task for task in secondary.setup_tasks if not task.ixia_needed
    )
    if len(primary_pre_ixia) != len(secondary_pre_ixia):
        raise ValueError(
            "Primary and secondary profiles must define the same number of "
            "non-IXIA setup tasks; "
            f"got {len(primary_pre_ixia)} primary vs "
            f"{len(secondary_pre_ixia)} secondary"
        )

    primary_needs_ixia = any(
        endpoint.ixia_needed or endpoint.direct_ixia_connections or endpoint.ixia_ports
        for endpoint in primary.endpoints
    )
    secondary_needs_ixia = any(
        endpoint.ixia_needed or endpoint.direct_ixia_connections or endpoint.ixia_ports
        for endpoint in secondary.endpoints
    )
    if primary_needs_ixia != secondary_needs_ixia:
        raise ValueError(
            "Primary and secondary profiles must either both require IXIA or "
            "both omit IXIA-bearing endpoints"
        )


def _validate_port_contract(primary: IxiaCandidate, secondary: IxiaCandidate) -> None:
    # Per-config `endpoint` embeds each profile's DUT interface, so byte
    # equality would over-constrain. Compiler-side _basic_port_signature
    # covers logical-role equivalence.
    if len(primary.basic_port_configs) != len(secondary.basic_port_configs):
        raise ValueError(
            "Primary and secondary profiles must define the same number of "
            "basic port configurations; "
            f"got {len(primary.basic_port_configs)} primary vs "
            f"{len(secondary.basic_port_configs)} secondary"
        )


def _traffic_names(
    candidate: IxiaCandidate,
) -> tuple[tuple[str | None, ...], tuple[str | None, ...]]:
    return (
        tuple(item.name for item in candidate.basic_traffic_item_configs),
        tuple(item.name for item in candidate.user_defined_traffic_items),
    )


def _validate_traffic_contract(
    primary: IxiaCandidate,
    secondary: IxiaCandidate,
    traffic_items_to_start: t.Sequence[str],
) -> None:
    secondary_basic_traffic_names, secondary_user_traffic_names = _traffic_names(
        secondary
    )
    primary_basic, primary_user = _traffic_names(primary)
    # Compare as multisets so declaration order is not part of the identity
    # contract (matching the "identities" wording) while still catching a
    # differing count or a renamed/missing item.
    if Counter(primary_basic) != Counter(secondary_basic_traffic_names) or Counter(
        primary_user
    ) != Counter(secondary_user_traffic_names):
        raise ValueError(
            "Primary and secondary profiles must define the same traffic item "
            "identities (basic + user-defined); interface-specific fields may "
            "differ across profiles."
        )

    secondary_traffic_names = {
        name
        for name in (
            *secondary_basic_traffic_names,
            *secondary_user_traffic_names,
        )
        if name is not None
    }
    missing_traffic_items = set(traffic_items_to_start) - secondary_traffic_names
    if missing_traffic_items:
        raise ValueError(
            "secondary_ixia_profile is missing parent traffic_items_to_start: "
            f"{sorted(missing_traffic_items)}"
        )


def _validate_protocol_contract(
    primary: IxiaCandidate, secondary: IxiaCandidate
) -> None:
    if len(primary.snake_configs) != len(secondary.snake_configs):
        raise ValueError(
            "Primary and secondary profiles must define the same number of "
            "snake configurations; interface-specific fields may differ."
        )
    if len(primary.ptp_configs) != len(secondary.ptp_configs):
        raise ValueError(
            "Primary and secondary profiles must define the same number of "
            "PTP configurations; interface-specific fields may differ."
        )


def _validate_secondary_candidate(
    primary: IxiaCandidate,
    secondary: IxiaCandidate,
    traffic_items_to_start: t.Sequence[str],
) -> None:
    if not secondary.name.strip():
        raise ValueError("secondary_ixia_profile.name must not be empty")
    _validate_endpoint_contract(primary, secondary)
    _validate_port_contract(primary, secondary)
    _validate_traffic_contract(primary, secondary, traffic_items_to_start)
    _validate_protocol_contract(primary, secondary)


def normalize_ixia_candidates(
    test_config: taac_types.TestConfig,
    primary_api_server_ip: str | None = None,
    skip_ptp_setup: bool = False,
) -> tuple[IxiaCandidate, ...]:
    primary = IxiaCandidate(
        name="primary",
        api_server_ip=primary_api_server_ip,
        endpoints=tuple(test_config.endpoints),
        setup_tasks=_as_tuple(test_config.setup_tasks),
        teardown_tasks=_as_tuple(test_config.teardown_tasks),
        basic_port_configs=_as_tuple(test_config.basic_port_configs),
        basic_traffic_item_configs=_as_tuple(test_config.basic_traffic_item_configs),
        default_basic_port_config=test_config.default_basic_port_config,
        user_defined_traffic_items=_as_tuple(test_config.user_defined_traffic_items),
        snake_configs=_as_tuple(test_config.snake_configs),
        ptp_configs=() if skip_ptp_setup else _as_tuple(test_config.ptp_configs),
    )
    secondary_profile = test_config.secondary_ixia_profile
    if secondary_profile is None:
        return (primary,)
    if test_config.traffic_generator_backend == taac_types.TrafficGeneratorBackend.OTG:
        raise ValueError(
            "secondary_ixia_profile is currently supported only by the RESTPY "
            "traffic generator backend"
        )

    secondary = IxiaCandidate(
        name=secondary_profile.name,
        api_server_ip=secondary_profile.api_server_ip,
        endpoints=tuple(secondary_profile.endpoints),
        setup_tasks=_as_tuple(secondary_profile.setup_tasks),
        teardown_tasks=_as_tuple(secondary_profile.teardown_tasks),
        basic_port_configs=_as_tuple(secondary_profile.basic_port_configs),
        basic_traffic_item_configs=_as_tuple(
            secondary_profile.basic_traffic_item_configs
        ),
        default_basic_port_config=secondary_profile.default_basic_port_config,
        user_defined_traffic_items=_as_tuple(
            secondary_profile.user_defined_traffic_items
        ),
        snake_configs=_as_tuple(secondary_profile.snake_configs),
        ptp_configs=(
            () if skip_ptp_setup else _as_tuple(secondary_profile.ptp_configs)
        ),
    )
    _validate_secondary_candidate(
        primary,
        secondary,
        tuple(test_config.traffic_items_to_start or ()),
    )
    return (primary, secondary)


def select_ixia_candidates(
    candidates: tuple[IxiaCandidate, ...],
    profile_mode: str,
    explicit_ixia_override: bool,
) -> tuple[IxiaCandidate, ...]:
    if profile_mode not in IXIA_PROFILE_MODES:
        raise ValueError(
            f"Invalid IXIA profile {profile_mode!r}; expected one of "
            f"{', '.join(IXIA_PROFILE_MODES)}"
        )
    if not candidates:
        raise ValueError("At least one IXIA candidate is required")
    if profile_mode == "primary":
        return (candidates[0],)
    if profile_mode == "secondary":
        if explicit_ixia_override:
            raise ValueError(
                "--ixia-profile secondary cannot be combined with an explicit "
                "IXIA API server or session ID"
            )
        if len(candidates) < 2:
            raise ValueError("--ixia-profile secondary requires secondary_ixia_profile")
        return (candidates[1],)
    if explicit_ixia_override:
        return (candidates[0],)
    return candidates
