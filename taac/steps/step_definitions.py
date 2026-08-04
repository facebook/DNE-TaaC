# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""
Consolidated step definitions for TAAC test configurations.

This module provides reusable helper functions for creating Step objects
used in TAAC test playbooks.
"""

import asyncio
import ipaddress
import itertools
import json
import math
import os
import time
import typing as t
import uuid
from collections import defaultdict
from dataclasses import dataclass

TAAC_OSS = os.environ.get("TAAC_OSS", "").lower() in ("1", "true", "yes")

if not TAAC_OSS:
    from libfb.py.asyncio.await_utils import convert_to_async
else:

    async def convert_to_async(fn, *args, **kwargs):  # type: ignore
        """OSS stub - libfb's convert_to_async wraps a sync callable in a thread."""
        raise NotImplementedError(
            "convert_to_async requires Meta-internal libfb; not available in OSS mode."
        )


from neteng.fboss.ctrl.thrift_types import DsfSessionState
from neteng.fboss.switch_config.thrift_mutable_types import PortSpeed
from neteng.fboss.switch_config.thrift_types import SwitchDrainState

if not TAAC_OSS:
    from neteng.netcastle.exceptions import TestbedError
else:

    class TestbedError(Exception):  # type: ignore
        """OSS stub - netcastle TestbedError isn't shipped."""

        pass


if not TAAC_OSS:
    from neteng.netcastle.utils.health_check_utils import async_get_fboss_versions
else:

    async def async_get_fboss_versions(hostname):  # type: ignore
        """OSS stub - netcastle health-check helper isn't shipped."""
        raise NotImplementedError(
            "async_get_fboss_versions requires Meta-internal netcastle; not available in OSS mode."
        )


if not TAAC_OSS:
    from neteng.netcastle.utils.reachability_utils import wait_for_ping_reachable
else:

    async def wait_for_ping_reachable(*args, **kwargs):  # type: ignore
        """OSS stub - netcastle reachability helper isn't shipped."""
        raise NotImplementedError(
            "wait_for_ping_reachable requires Meta-internal netcastle; not available in OSS mode."
        )


from taac.constants import (
    FAILED_HC_STATUSES,
    OpenRRouteAction,
    TAAC_HEALTH_CHECK_SCUBA_TABLE,
    TestCaseFailure,
)
from taac.driver.driver_constants import (
    AristaCriticalAgents,
    FbossSystemctlServiceName,
    OtherSystemctlServiceName,
    Service as DriverService,
)
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
    AbstractIxiaHealthCheck,
    AbstractTopologyHealthCheck,
)
from taac.health_checks.all_health_checks import (
    HEALTH_CHECK_NAME_TO_INPUT,
    NAME_TO_POINT_IN_TIME_HEALTH_CHECK,
)
from taac.health_checks.healthcheck_definitions import (
    create_next_hop_count_check,
)

if not TAAC_OSS:
    from taac.internal.coop_utils import async_unregister_patcher
else:

    async def async_unregister_patcher(*args, **kwargs):  # type: ignore
        """OSS stub - taac.internal.coop_utils isn't shipped."""
        raise NotImplementedError(
            "async_unregister_patcher requires Meta-internal taac.internal.coop_utils."
        )


if not TAAC_OSS:
    from taac.internal.drainer_utils import async_nds_drain
else:

    async def async_nds_drain(*args, **kwargs):  # type: ignore
        """OSS stub - taac.internal.drainer_utils isn't shipped."""
        raise NotImplementedError(
            "async_nds_drain requires Meta-internal taac.internal.drainer_utils."
        )


if t.TYPE_CHECKING or not TAAC_OSS:
    from taac.internal.utils.openr_route_utils import (
        OpenRRouteManager,
    )
else:

    class OpenRRouteManager:  # type: ignore
        """OSS stub - taac.internal.utils.openr_route_utils isn't shipped."""

        def __init__(self, *args, **kwargs):
            raise NotImplementedError(
                "OpenRRouteManager requires Meta-internal taac.internal.utils.openr_route_utils."
            )


from taac.steps.step import (  # oss-rewrite (force ShipIt re-export to taac.* root)
    Step as StepBase,
)
from taac.tasks.utils import run_task
from taac.utils.common import (
    async_write_test_result,
    run_in_thread,
)
from taac.utils.driver_factory import async_get_device_driver
from taac.utils.file_verification_utils import (
    verify_file_modification_time,
)
from taac.utils.flap_timing_utils import (
    apply_flap_timing,
    pick_flap_timing,
)
from taac.utils.health_check_utils import (
    generate_prefix_nh_list_map,
)
from taac.utils.json_thrift_utils import (
    json_to_thrift,
    thrift_to_json,
    try_json_loads,
    try_json_to_thrift,
)
from taac.utils.oss_taac_lib_utils import (
    async_retryable,
    none_throws,
)
from taac.utils.system_stress_utils import (
    async_get_memory_current_pct,
)
from taac.utils.taac_log_formatter import log_results_table

if t.TYPE_CHECKING or not TAAC_OSS:
    from rfe.scubadata.scubadata_py3 import Sample, ScubaData
else:

    class Sample:  # type: ignore
        """OSS stub - rfe.scubadata.scubadata_py3.Sample isn't shipped."""

        def __init__(self, *args, **kwargs):
            raise NotImplementedError(
                "rfe.scubadata.scubadata_py3.Sample is Meta-internal; not shipped under OSS."
            )

    class ScubaData:  # type: ignore
        """OSS stub - rfe.scubadata.scubadata_py3.ScubaData isn't shipped."""

        TIME_COLUMN = "time"  # constant used by callers; harmless under OSS

        def __init__(self, *args, **kwargs):
            raise NotImplementedError(
                "rfe.scubadata.scubadata_py3.ScubaData is Meta-internal; not shipped under OSS."
            )


if not TAAC_OSS:
    from service_automation.fboss.remediations.utils.bmc_helper import (
        run_bmc_cmd_hwcontrol,
    )
else:

    def run_bmc_cmd_hwcontrol(*args, **kwargs):  # type: ignore
        """OSS stub - service_automation.fboss.remediations isn't shipped."""
        raise NotImplementedError(
            "run_bmc_cmd_hwcontrol requires Meta-internal service_automation; not shipped under OSS."
        )


from taac.health_check.health_check import types as hc_types
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import (
    Params,
    RunTaskInput,
    Step,
    StepName,
    ValidationInput,
)


# Re-export the centralized HC factory for backward compat with callers that
# imported it from this module pre-Phase-6-v2.
__all_hc_reexports__ = ["create_next_hop_count_check"]


# =============================================================================
# STEP BUILDERS - Create steps for test playbooks
# =============================================================================


def create_custom_step(
    params_dict: t.Dict[str, t.Any],
    description: t.Optional[str] = None,
) -> Step:
    """
    Create a custom step with arbitrary parameters.

    Args:
        params_dict: Parameters to pass to the custom step (must include "custom_step_name")
        description: Custom description for the step

    Returns:
        Step object for the custom step
    """
    return Step(
        name=StepName.CUSTOM_STEP,
        step_params=Params(json_params=json.dumps(params_dict)),
        description=description,
    )


def create_bgp_agent_log_artifact_step(
    device_name: str,
    action: str,
    state_key: str,
    *,
    case_id: str,
) -> Step:
    """Capture or publish durable EOS ``Bgp-<pid>`` evidence for one Playbook."""
    if action not in {"capture", "publish"}:
        raise ValueError(
            f"BGP agent-log artifact action must be capture or publish, got {action!r}"
        )
    if not device_name or not state_key or not case_id:
        raise ValueError(
            "BGP agent-log artifact requires device_name, state_key, and case_id"
        )
    return create_custom_step(
        params_dict={
            "custom_step_name": "bgp_agent_log_artifact",
            "hostname": device_name,
            "action": action,
            "state_key": state_key,
        },
        description=(f"{case_id} {action} time-bounded DUT Bgp-<pid> log evidence"),
    )


def _validate_persisted_step_key(name: str, value: str) -> None:
    """Reject non-UUID keys before a persisted custom step reaches runtime."""
    try:
        uuid.UUID(value)
    except (AttributeError, TypeError, ValueError) as error:
        raise ValueError(f"{name} must be a UUID string, got {value!r}") from error


def _require_custom_action_params(
    component: str,
    action: str,
    params: t.Mapping[str, t.Any],
    required: t.Collection[str],
) -> None:
    missing = sorted(name for name in required if name not in params)
    if missing:
        raise ValueError(f"{component} action {action!r} requires {missing}")


def _require_positive_custom_action_param(
    component: str,
    action: str,
    params: t.Mapping[str, t.Any],
    name: str,
) -> None:
    if name not in params:
        return
    value = params[name]
    try:
        numeric_value = float(value)
    except (TypeError, ValueError):
        numeric_value = float("nan")
    if (
        isinstance(value, bool)
        or not math.isfinite(numeric_value)
        or numeric_value <= 0
    ):
        raise ValueError(
            f"{component} action {action!r} requires {name} to be positive"
        )


def _require_nonnegative_custom_action_param(
    component: str,
    action: str,
    params: t.Mapping[str, t.Any],
    name: str,
) -> None:
    if name not in params:
        return
    value = params[name]
    try:
        numeric_value = float(value)
    except (TypeError, ValueError):
        numeric_value = float("nan")
    if isinstance(value, bool) or not math.isfinite(numeric_value) or numeric_value < 0:
        raise ValueError(
            f"{component} action {action!r} requires {name} to be non-negative"
        )


def create_bgp_update_group_state_step(
    device_name: str,
    action: str,
    state_key: str,
    *,
    action_params: t.Optional[t.Mapping[str, t.Any]] = None,
    description: t.Optional[str] = None,
) -> Step:
    """Create a persisted semantic Update Group state step.

    Supported actions are ``capture``, ``compare``, ``monitor``,
    ``wait_monitor_armed``, ``formation_monitor``, and ``clear``. ``monitor``
    requires ``case`` and ``duration_seconds`` in ``action_params``. Monitor
    waits and formation actions accept positive ``timeout_seconds``; monitor and
    formation actions accept positive ``poll_interval_seconds``. Comparison
    actions may select ``none``, ``group_id``, or ``group_id_and_generation``
    operational continuity.
    """
    actions = {
        "capture",
        "clear",
        "compare",
        "formation_monitor",
        "monitor",
        "wait_monitor_armed",
    }
    if action not in actions:
        raise ValueError(
            f"Unsupported BGP Update Group state action {action!r}; "
            f"expected one of {sorted(actions)}"
        )
    _validate_persisted_step_key("state_key", state_key)
    params = dict(action_params or {})
    if action == "monitor":
        _require_custom_action_params(
            "BGP Update Group state", action, params, ("case", "duration_seconds")
        )
        _require_positive_custom_action_param(
            "BGP Update Group state", action, params, "duration_seconds"
        )
        cases = {
            "fibagent_restart",
            "link_down",
            "peer_flap",
            "recovery",
            "strict",
            "sustained_link_flap",
        }
        if params["case"] not in cases:
            raise ValueError(f"monitor case must be one of {sorted(cases)}")
    for name in ("expected_group_count", "expected_session_count"):
        _require_positive_custom_action_param(
            "BGP Update Group state", action, params, name
        )
    _require_positive_custom_action_param(
        "BGP Update Group state", action, params, "poll_interval_seconds"
    )
    if action == "verify_zero":
        _require_nonnegative_custom_action_param(
            "BGP Update Group state", action, params, "timeout_seconds"
        )
    else:
        _require_positive_custom_action_param(
            "BGP Update Group state", action, params, "timeout_seconds"
        )
    continuity = str(params.get("operational_continuity", "none"))
    continuity_modes = {"none", "group_id", "group_id_and_generation"}
    if continuity not in continuity_modes:
        raise ValueError(
            f"operational_continuity must be one of {sorted(continuity_modes)}"
        )
    payload = {
        "custom_step_name": "bgp_update_group_state",
        "hostname": device_name,
        "action": action,
        "state_key": state_key,
        **params,
    }
    return create_custom_step(
        params_dict=payload,
        description=description or f"BGP Update Group state: {action}",
    )


_DEFAULT_MAX_HARDWARE_CURRENT_DELTA = 100
_DEFAULT_MAX_HARDWARE_HIGH_WATERMARK_INCREASE = 100


def create_hardware_capacity_delta_step(
    device_name: str,
    action: str,
    state_key: str,
    *,
    max_current_delta: int = _DEFAULT_MAX_HARDWARE_CURRENT_DELTA,
    max_high_watermark_increase: int = (_DEFAULT_MAX_HARDWARE_HIGH_WATERMARK_INCREASE),
    description: t.Optional[str] = None,
) -> Step:
    """Create a keyed capture, compare, or clear capacity-delta action."""
    actions = {"capture", "compare", "clear"}
    if action not in actions:
        raise ValueError(
            f"Unsupported hardware-capacity delta action {action!r}; "
            f"expected one of {sorted(actions)}"
        )
    _validate_persisted_step_key("state_key", state_key)
    payload: t.Dict[str, t.Any] = {
        "custom_step_name": "hardware_capacity_delta",
        "hostname": device_name,
        "action": action,
        "state_key": state_key,
    }
    thresholds = (
        ("max_current_delta", max_current_delta),
        ("max_high_watermark_increase", max_high_watermark_increase),
    )
    for name, value in thresholds:
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(f"{name} must be a non-negative integer")
    default_thresholds = {
        "max_current_delta": _DEFAULT_MAX_HARDWARE_CURRENT_DELTA,
        "max_high_watermark_increase": (_DEFAULT_MAX_HARDWARE_HIGH_WATERMARK_INCREASE),
    }
    if action != "compare" and any(
        value != default_thresholds[name] for name, value in thresholds
    ):
        raise ValueError(
            "hardware-capacity thresholds are supported only for compare actions"
        )
    if action == "compare":
        for name, value in thresholds:
            payload[name] = value
    return create_custom_step(
        params_dict=payload,
        description=description or f"Hardware-capacity delta: {action}",
    )


def _validate_disruption_route_verifier(
    action: str,
    params: t.Mapping[str, t.Any],
    pool_param: str,
) -> None:
    if not params.get(pool_param):
        raise ValueError(
            f"BGP Update Group disruption action {action!r} requires non-empty "
            f"{pool_param}"
        )
    if "verify_down_route_delta" in params and not isinstance(
        params["verify_down_route_delta"], bool
    ):
        raise ValueError(
            "BGP Update Group disruption verify_down_route_delta must be a boolean"
        )
    if action == "link_flap_recovery":
        _require_custom_action_params(
            "BGP Update Group disruption",
            action,
            params,
            (
                "recovered_receiver_parent_prefixes",
                "expected_recovered_receiver_count",
                "expected_route_delta",
            ),
        )
        if not params["recovered_receiver_parent_prefixes"]:
            raise ValueError(
                "link_flap_recovery recovered_receiver_parent_prefixes must be "
                "non-empty"
            )
        _require_positive_custom_action_param(
            "BGP Update Group disruption",
            action,
            params,
            "expected_recovered_receiver_count",
        )
        if not params.get("verify_down_route_delta", True):
            return
        _require_custom_action_params(
            "BGP Update Group disruption",
            action,
            params,
            (
                "down_route_receiver_addresses",
                "expected_down_receiver_count",
                "expected_down_route_delta",
                "expected_failed_ebgp_prefix_count",
            ),
        )
        if not params["down_route_receiver_addresses"]:
            raise ValueError(
                "link_flap_recovery down_route_receiver_addresses must be non-empty"
            )
        _require_positive_custom_action_param(
            "BGP Update Group disruption",
            action,
            params,
            "expected_down_receiver_count",
        )
        _require_positive_custom_action_param(
            "BGP Update Group disruption",
            action,
            params,
            "expected_failed_ebgp_prefix_count",
        )
        return
    _require_custom_action_params(
        "BGP Update Group disruption",
        action,
        params,
        (
            "receiver_parent_prefixes",
            "expected_receiver_count",
            "expected_route_delta",
        ),
    )


def _validate_sustained_disruption(action: str, params: t.Mapping[str, t.Any]) -> None:
    tracks = params["port_tracks"]
    track_roles = {
        str(track.get("role", "")) for track in tracks if isinstance(track, t.Mapping)
    }
    required_roles = {"bgp_mon", "ebgp", "ibgp"}
    if track_roles != required_roles or len(tracks) != len(required_roles):
        raise ValueError(
            "sustained_link_flap port_tracks must contain exactly one "
            "ebgp, ibgp, and bgp_mon track"
        )
    for track in tracks:
        _require_custom_action_params(
            "BGP Update Group disruption port track",
            action,
            track,
            ("interface", "target_peer_subnets"),
        )
    scenarios = params["heartbeat_scenarios"]
    expected_down_roles = {
        frozenset({"ebgp"}),
        frozenset({"ibgp"}),
        frozenset({"bgp_mon"}),
        frozenset({"ebgp", "bgp_mon"}),
        frozenset({"ibgp", "bgp_mon"}),
    }
    actual_down_roles = {
        frozenset(scenario.get("down_roles", ()))
        for scenario in scenarios
        if isinstance(scenario, t.Mapping)
    }
    if actual_down_roles != expected_down_roles or len(scenarios) != len(
        expected_down_roles
    ):
        raise ValueError(
            "sustained_link_flap heartbeat_scenarios do not cover the "
            "five required planned-down states"
        )
    for scenario in scenarios:
        _require_custom_action_params(
            "BGP Update Group disruption heartbeat",
            action,
            scenario,
            (
                "expected_receiver_count",
                "expected_route_delta",
                "receiver_parent_prefixes",
                "source_prefix_pool_regexes",
            ),
        )


def create_bgp_update_group_disruption_step(
    device_name: str,
    action: str,
    *,
    action_params: t.Mapping[str, t.Any],
    description: t.Optional[str] = None,
) -> Step:
    """Create a verified Update Group disruption step.

    ``fibagent_restart`` resolves and verifies the EOS L3 forwarding agent.
    ``fibagent_active`` polls that same exact agent to ACTIVE without restarting it.
    ``link_flap_recovery`` requires exact full-scale peer and timer contracts.
    ``sustained_link_flap`` requires ``port_tracks`` and
    ``heartbeat_scenarios``. ``fixed_peer_flap`` requires ``peer_regex`` and
    deterministic ``seed``. Route-producing link/peer actions must also supply
    receiver scope, receiver count, and expected route delta.
    """
    required_by_action = {
        "fibagent_active": set(),
        "fibagent_restart": set(),
        "link_flap_recovery": {
            "bgp_hold_timer_seconds",
            "expected_target_peer_count",
            "interface",
            "target_peer_subnets",
        },
        "sustained_link_flap": {"heartbeat_scenarios", "port_tracks"},
        "fixed_peer_flap": {"peer_regex", "seed"},
    }
    if action not in required_by_action:
        raise ValueError(
            f"Unsupported BGP Update Group disruption action {action!r}; "
            f"expected one of {sorted(required_by_action)}"
        )
    params = dict(action_params)
    _require_custom_action_params(
        "BGP Update Group disruption",
        action,
        params,
        required_by_action[action],
    )
    if action == "link_flap_recovery" and not params["target_peer_subnets"]:
        raise ValueError("link_flap_recovery target_peer_subnets must be non-empty")
    if action == "fixed_peer_flap" and not params["peer_regex"]:
        raise ValueError("fixed_peer_flap peer_regex must be non-empty")
    for name in (
        "active_timeout_seconds",
        "bgp_hold_timer_seconds",
        "down_seconds",
        "event_timeout_seconds",
        "expected_target_peer_count",
        "flap_count",
        "poll_interval_seconds",
        "restart_timeout_seconds",
        "restore_timeout_seconds",
        "route_verification_timeout_seconds",
        "transition_timeout_seconds",
        "up_seconds",
    ):
        _require_positive_custom_action_param(
            "BGP Update Group disruption", action, params, name
        )
    if action == "fixed_peer_flap":
        duration = int(params.get("duration_seconds", 1800))
        if duration <= 0 or duration % 10:
            raise ValueError(
                "fixed_peer_flap duration_seconds must be positive and divisible by 10"
            )
        _validate_disruption_route_verifier(action, params, "churn_prefix_pool_regexes")
    elif action == "link_flap_recovery":
        _validate_disruption_route_verifier(
            action, params, "first_down_prefix_pool_regexes"
        )
    elif action == "sustained_link_flap":
        _validate_sustained_disruption(action, params)
    payload = {
        "custom_step_name": "bgp_update_group_disruption",
        "hostname": device_name,
        "action": action,
        **params,
    }
    return create_custom_step(
        params_dict=payload,
        description=description or f"BGP Update Group disruption: {action}",
    )


def create_verified_fibagent_restart_step(
    device_name: str,
    *,
    restart_timeout_seconds: float = 300.0,
    poll_interval_seconds: float = 1.0,
    require_uptime_change: bool = False,
    description: t.Optional[str] = None,
) -> Step:
    """Create an EOS FibAgent restart with status-transition verification."""
    if not isinstance(require_uptime_change, bool):
        raise ValueError("require_uptime_change must be a boolean")
    return create_bgp_update_group_disruption_step(
        device_name,
        "fibagent_restart",
        action_params={
            "restart_timeout_seconds": restart_timeout_seconds,
            "poll_interval_seconds": poll_interval_seconds,
            "require_uptime_change": require_uptime_change,
        },
        description=description or "Restart and verify EOS FibAgent",
    )


def create_verify_fibagent_active_step(
    device_name: str,
    *,
    active_timeout_seconds: float = 300.0,
    poll_interval_seconds: float = 1.0,
    description: t.Optional[str] = None,
) -> Step:
    """Poll the one EOS L3 forwarding agent until it reports ACTIVE."""
    return create_bgp_update_group_disruption_step(
        device_name,
        "fibagent_active",
        action_params={
            "active_timeout_seconds": active_timeout_seconds,
            "poll_interval_seconds": poll_interval_seconds,
        },
        description=description or "Verify EOS FibAgent is active",
    )


def _normalize_bgp_attribute_churn_pool_names(
    prefix_pool_names: t.Mapping[str, t.Mapping[str, str]],
) -> t.Dict[str, t.Dict[str, str]]:
    expected_afis = {"ipv4", "ipv6"}
    expected_planes = {"1", "2", "3", "4"}
    if set(prefix_pool_names) != expected_afis:
        raise ValueError("prefix_pool_names must contain exactly ipv4 and ipv6")

    normalized: t.Dict[str, t.Dict[str, str]] = {}
    for afi in sorted(expected_afis):
        pools = prefix_pool_names[afi]
        if set(pools) != expected_planes or any(not value for value in pools.values()):
            raise ValueError(
                f"prefix_pool_names[{afi!r}] must contain non-empty planes 1-4"
            )
        normalized[afi] = {plane: pools[plane] for plane in sorted(expected_planes)}
    return normalized


def _normalize_bgp_attribute_churn_matrix(
    attribute_matrix: t.Mapping[str, t.Mapping[str, t.Any]],
) -> t.Dict[str, t.Dict[str, t.Any]]:
    expected_families = {"local_pref", "med", "origin", "as_path"}
    expected_values = {
        "plane_1_preferred",
        "reference",
        "plane_1_nonpreferred",
    }
    if set(attribute_matrix) != expected_families:
        raise ValueError(
            "attribute_matrix must contain local_pref, med, origin, and as_path"
        )

    normalized: t.Dict[str, t.Dict[str, t.Any]] = {}
    for family in sorted(expected_families):
        values = attribute_matrix[family]
        if set(values) != expected_values:
            raise ValueError(
                f"attribute_matrix[{family!r}] must contain preferred, reference, "
                "and nonpreferred values"
            )
        normalized[family] = {key: values[key] for key in sorted(expected_values)}
    return normalized


def _validate_bgp_attribute_churn_geometry(
    numeric_params: t.Mapping[str, int],
) -> None:
    if numeric_params["quiet_window_seconds"] < 0:
        raise ValueError("quiet_window_seconds must be non-negative")
    if any(
        value <= 0
        for name, value in numeric_params.items()
        if name != "quiet_window_seconds"
    ):
        raise ValueError(
            "BGP attribute-churn numeric parameters other than "
            "quiet_window_seconds must be positive"
        )
    if (
        numeric_params["selected_block_count_per_afi"]
        > numeric_params["peer_count_per_plane"]
    ):
        raise ValueError("selected block count cannot exceed peers per plane")
    if numeric_params["selected_block_count_per_afi"] < 2:
        raise ValueError("selected_block_count_per_afi must be at least 2")
    if numeric_params["samples_per_block"] > numeric_params["routes_per_block"]:
        raise ValueError("samples per block cannot exceed routes per block")
    if numeric_params["convergence_hard_timeout_seconds"] <= max(
        numeric_params["transition_timeout_seconds"],
        numeric_params["reference_setup_timeout_seconds"],
    ):
        raise ValueError(
            "convergence_hard_timeout_seconds must exceed transition and "
            "reference setup timeouts"
        )


def create_bgp_attribute_churn_step(
    *,
    hostname: str,
    prefix_pool_names: t.Mapping[str, t.Mapping[str, str]],
    observer_peer_parent_prefix: str,
    peer_count_per_plane: int,
    selected_block_count_per_afi: int,
    samples_per_block: int,
    routes_per_block: int,
    iterations_per_family: int,
    cadence_seconds: int,
    poll_interval_seconds: int,
    transition_timeout_seconds: int,
    reference_setup_timeout_seconds: int,
    restore_timeout_seconds: int,
    quiet_window_seconds: int,
    max_lookup_concurrency: int,
    attribute_matrix: t.Mapping[str, t.Mapping[str, t.Any]],
    convergence_hard_timeout_seconds: int = 300,
    description: str | None = None,
) -> Step:
    """Create the audited CICD-EBB-10 dual-stack attribute-churn workflow."""
    numeric_params = {
        "peer_count_per_plane": peer_count_per_plane,
        "selected_block_count_per_afi": selected_block_count_per_afi,
        "samples_per_block": samples_per_block,
        "routes_per_block": routes_per_block,
        "iterations_per_family": iterations_per_family,
        "cadence_seconds": cadence_seconds,
        "poll_interval_seconds": poll_interval_seconds,
        "transition_timeout_seconds": transition_timeout_seconds,
        "convergence_hard_timeout_seconds": convergence_hard_timeout_seconds,
        "reference_setup_timeout_seconds": reference_setup_timeout_seconds,
        "restore_timeout_seconds": restore_timeout_seconds,
        "quiet_window_seconds": quiet_window_seconds,
        "max_lookup_concurrency": max_lookup_concurrency,
    }
    if not hostname or not observer_peer_parent_prefix:
        raise ValueError("hostname and observer_peer_parent_prefix must be non-empty")
    _validate_bgp_attribute_churn_geometry(numeric_params)

    params: t.Dict[str, t.Any] = {
        "custom_step_name": "bgp_attribute_churn",
        "hostname": hostname,
        "prefix_pool_names": _normalize_bgp_attribute_churn_pool_names(
            prefix_pool_names
        ),
        "observer_peer_parent_prefix": observer_peer_parent_prefix,
        "attribute_matrix": _normalize_bgp_attribute_churn_matrix(attribute_matrix),
        **numeric_params,
    }
    return create_custom_step(
        params_dict=params,
        description=description or "Run audited dual-stack BGP attribute churn",
    )


def create_bgp_route_storm_step(
    *,
    hostname: str,
    ixia_interface_mimic_ibgp: str,
    expected_established_sessions: int,
    observer_peer_parent_prefix: str,
    prefix_pool_names: t.Mapping[str, str],
    peer_count_per_plane: int,
    selected_peer_rows: t.Sequence[int],
    routes_per_peer: int,
    samples_per_block: int,
    cycles: int,
    advertise_seconds: int,
    withdraw_seconds: int,
    poll_interval_seconds: int,
    transition_timeout_seconds: int,
    session_establish_timeout_seconds: int,
    restore_timeout_seconds: int,
    quiet_window_seconds: int,
    max_lookup_concurrency: int,
    as_path_pool_size: int,
    as_path_length: int,
    communities_per_route: int,
    extended_communities_per_route: int,
    convergence_hard_timeout_seconds: int = 300,
    description: str | None = None,
) -> Step:
    """Create the audited CICD-EBB-11 route-storm workflow."""
    if not hostname or not ixia_interface_mimic_ibgp or not observer_peer_parent_prefix:
        raise ValueError(
            "hostname, IXIA iBGP interface, and observer prefix must be non-empty"
        )
    if set(prefix_pool_names) != {"ipv4", "ipv6"} or any(
        not name for name in prefix_pool_names.values()
    ):
        raise ValueError("prefix_pool_names must define non-empty ipv4 and ipv6 pools")

    rows = list(selected_peer_rows)
    if rows != sorted(set(rows)) or any(
        row < 0 or row >= peer_count_per_plane for row in rows
    ):
        raise ValueError("selected_peer_rows must be unique, sorted, and in range")
    if len(rows) * routes_per_peer * 2 != 10_500:
        raise ValueError("CICD-EBB-11 requires exactly 10,500 dual-stack route paths")
    numeric_params = {
        "expected_established_sessions": expected_established_sessions,
        "peer_count_per_plane": peer_count_per_plane,
        "routes_per_peer": routes_per_peer,
        "samples_per_block": samples_per_block,
        "cycles": cycles,
        "advertise_seconds": advertise_seconds,
        "withdraw_seconds": withdraw_seconds,
        "poll_interval_seconds": poll_interval_seconds,
        "transition_timeout_seconds": transition_timeout_seconds,
        "convergence_hard_timeout_seconds": convergence_hard_timeout_seconds,
        "session_establish_timeout_seconds": session_establish_timeout_seconds,
        "restore_timeout_seconds": restore_timeout_seconds,
        "quiet_window_seconds": quiet_window_seconds,
        "max_lookup_concurrency": max_lookup_concurrency,
        "as_path_pool_size": as_path_pool_size,
        "as_path_length": as_path_length,
        "communities_per_route": communities_per_route,
        "extended_communities_per_route": extended_communities_per_route,
    }
    if any(value <= 0 for value in numeric_params.values()):
        raise ValueError("BGP route-storm numeric parameters must be positive")
    if convergence_hard_timeout_seconds <= transition_timeout_seconds:
        raise ValueError(
            "convergence_hard_timeout_seconds must exceed transition_timeout_seconds"
        )
    if extended_communities_per_route != 1:
        raise ValueError(
            "CICD-EBB-11 currently requires exactly one extended community pending "
            "isolated IXIA capability validation"
        )

    return create_custom_step(
        params_dict={
            "custom_step_name": "bgp_route_storm",
            "hostname": hostname,
            "ixia_interface_mimic_ibgp": ixia_interface_mimic_ibgp,
            "observer_peer_parent_prefix": observer_peer_parent_prefix,
            "prefix_pool_names": dict(prefix_pool_names),
            "selected_peer_rows": rows,
            **numeric_params,
        },
        description=description or "Run audited dual-stack BGP route storm",
    )


def create_snapshot_bgp_sent_route_counts_step(
    hostname: str,
    snapshot_key: str,
    peer_addrs: t.Optional[t.List[str]] = None,
    peer_group_filter: t.Optional[str] = None,
    peer_parent_prefixes: t.Optional[t.List[str]] = None,
    description: t.Optional[str] = None,
) -> Step:
    """Snapshot ``postpolicy_sent_prefix_count`` for a set of BGP peers on the
    DUT, tagged with ``snapshot_key`` for later look-up by
    ``create_verify_bgp_sent_route_count_delta_step``. Backs the spec-loyal
    "storm delivery" gate for BGP++ UG backpressure tests -- the check asserts
    that peer receive-counts grew by at least ``storm_prefix_count`` between
    snapshot and verify, independent of whatever baseline RIB fanout the DUT
    is doing.

    Peers are selected by ONE of: ``peer_parent_prefixes`` (subnets — every
    session whose peer address falls inside one, AFI-specific; the reliable way
    to scope to a whole AFI update group on bag011, where the per-session
    peer-group field is not the AFI peer-group name), ``peer_group_filter`` (a
    peer-group substring, for testbeds that expose it per session), or explicit
    ``peer_addrs``. At least one must be supplied; if more than one is set they
    are resolved by precedence (peer_parent_prefixes > peer_group_filter >
    peer_addrs), so pass just the one you intend.

    Args:
        hostname: Device hostname (bgpcpp source of truth).
        snapshot_key: Unique key across the playbook; the matching verify step
            must use the same string.
        peer_addrs: Peer IPs to snapshot.
        peer_group_filter: Peer-group substring to snapshot every member of.
        peer_parent_prefixes: Subnets; snapshot every peer whose address is in
            one (e.g. the iBGP v4 plane /16s or v6 plane /80s).
        description: Optional custom description.
    """
    if (
        peer_addrs is None
        and peer_group_filter is None
        and peer_parent_prefixes is None
    ):
        raise ValueError(
            "create_snapshot_bgp_sent_route_counts_step: pass peer_addrs, "
            "peer_group_filter, or peer_parent_prefixes"
        )
    if description is None:
        _who = (
            f"peers under {peer_parent_prefixes}"
            if peer_parent_prefixes
            else f"peer-group ~{peer_group_filter!r}"
            if peer_group_filter
            else f"{len(peer_addrs or [])} peer(s)"
        )
        description = (
            f"Snapshot BGP sent-count for {_who} on {hostname} (key={snapshot_key})"
        )
    params: t.Dict[str, t.Any] = {
        "custom_step_name": "snapshot_bgp_sent_route_counts",
        "hostname": hostname,
        "snapshot_key": snapshot_key,
    }
    if peer_addrs is not None:
        params["peer_addrs"] = list(peer_addrs)
    if peer_group_filter is not None:
        params["peer_group_filter"] = peer_group_filter
    if peer_parent_prefixes is not None:
        params["peer_parent_prefixes"] = list(peer_parent_prefixes)
    return create_custom_step(params_dict=params, description=description)


def create_snapshot_bgp_dut_best_path_as_path_step(
    hostname: str,
    snapshot_key: str,
    test_prefix_parents: t.List[str],
    discriminator_asn: int,
    expected_prefix_count: int,
    test_prefix_length: t.Optional[int] = None,
    description: t.Optional[str] = None,
) -> Step:
    """Baseline the DUT's selected best-path AS-PATH for the 2.9.1 test prefixes
    while ONLY the loser set is advertised, so the paired
    ``create_verify_bgp_dut_best_path_as_path_converged_step`` can assert
    convergence to the winner without hard-coding absolute AS-PATH values.

    Records, per test prefix, the count of ``discriminator_asn`` in the DUT
    Loc-RIB best path (uniform at baseline). Reads the RIB (Loc-RIB / best-path
    selection), which is correct under Update Group -- unlike adj-RIB-out
    (T271301144) -- and needs no BGP flap.

    Args:
        hostname: DUT hostname (bgpcpp source of truth).
        snapshot_key: Unique key; the matching verify step must reuse it.
        test_prefix_parents: CIDRs the test prefixes fall under (e.g. the /15
            covering the 500 competing /24s).
        discriminator_asn: ASN whose occurrence-count distinguishes the sets (the
            loser prepends it N more times than the winner).
        expected_prefix_count: number of test prefixes expected in the RIB.
        description: Optional custom description.
    """
    if not test_prefix_parents:
        raise ValueError(
            "create_snapshot_bgp_dut_best_path_as_path_step: test_prefix_parents "
            "must be non-empty"
        )
    if description is None:
        description = (
            f"Baseline DUT best-path AS{discriminator_asn} count for "
            f"{expected_prefix_count} test prefixes on {hostname} "
            f"(key={snapshot_key})"
        )
    params: t.Dict[str, t.Any] = {
        "custom_step_name": "snapshot_bgp_dut_best_path_as_path",
        "hostname": hostname,
        "snapshot_key": snapshot_key,
        "test_prefix_parents": list(test_prefix_parents),
        "discriminator_asn": int(discriminator_asn),
        "expected_prefix_count": int(expected_prefix_count),
    }
    if test_prefix_length is not None:
        params["test_prefix_length"] = int(test_prefix_length)
    return create_custom_step(params_dict=params, description=description)


def create_verify_bgp_dut_best_path_as_path_converged_step(
    hostname: str,
    snapshot_key: str,
    test_prefix_parents: t.List[str],
    discriminator_asn: int,
    expected_prefix_count: int,
    expected_as_path_delta: int = 3,
    tolerance: int = 0,
    expected_fail: bool = False,
    expected_fail_reason: t.Optional[str] = None,
    test_prefix_length: t.Optional[int] = None,
    description: t.Optional[str] = None,
) -> Step:
    """Strict criterion-1 for 2.9.1: assert the DUT converged EVERY test prefix's
    best path to the winner set (best-path AS-PATH ``discriminator_asn`` count ==
    baseline - ``expected_as_path_delta``). Any prefix still at the baseline count
    is reported as stuck on the loser (best-path change did not complete /
    split-brain). Raises ``TestCaseFailure`` if more than ``tolerance`` prefixes
    violate, or if the baseline snapshot is missing / test prefixes are absent
    (never vacuous).

    SCOPE: this verifies the DUT best-path SELECTION converged to the winner for
    every prefix (read from Loc-RIB). Under Update Group the DUT distributes that
    one best path to all group members by construction; it does NOT independently
    read each peer, so a per-peer split-brain (DUT selects the winner but fails to
    re-advertise it to a member) is out of scope pending the deferred per-peer
    reader (T271301144).

    Requires the paired ``create_snapshot_bgp_dut_best_path_as_path_step`` to have
    run earlier under the same ``snapshot_key``.

    Args:
        hostname: DUT hostname (bgpcpp source of truth).
        snapshot_key: must match the paired snapshot step.
        test_prefix_parents: CIDRs the test prefixes fall under.
        discriminator_asn: ASN whose occurrence-count distinguishes the sets.
        expected_prefix_count: number of test prefixes expected in the RIB.
        expected_as_path_delta: extra ``discriminator_asn`` prepends the loser
            carries vs the winner (2.9.1 Set A prepends it 3 more times).
        tolerance: prefixes allowed to violate before failing.
        expected_fail / expected_fail_reason: XFAIL handling.
        description: Optional custom description.
    """
    if not test_prefix_parents:
        raise ValueError(
            "create_verify_bgp_dut_best_path_as_path_converged_step: "
            "test_prefix_parents must be non-empty"
        )
    if description is None:
        description = (
            f"Verify DUT converged {expected_prefix_count} test prefixes to the "
            f"winning best path on {hostname} (key={snapshot_key})"
        )
    params: t.Dict[str, t.Any] = {
        "custom_step_name": "verify_bgp_dut_best_path_as_path_converged",
        "hostname": hostname,
        "snapshot_key": snapshot_key,
        "test_prefix_parents": list(test_prefix_parents),
        "discriminator_asn": int(discriminator_asn),
        "expected_prefix_count": int(expected_prefix_count),
        "expected_as_path_delta": int(expected_as_path_delta),
        "tolerance": int(tolerance),
        "expected_fail": expected_fail,
    }
    if expected_fail_reason is not None:
        params["expected_fail_reason"] = expected_fail_reason
    if test_prefix_length is not None:
        params["test_prefix_length"] = int(test_prefix_length)
    return create_custom_step(params_dict=params, description=description)


def create_snapshot_bgp_peer_advertised_as_path_step(
    hostname: str,
    snapshot_key: str,
    peer_parent_prefixes: t.List[str],
    test_prefix_parents: t.List[str],
    discriminator_asn: int,
    expected_prefix_count: int,
    max_concurrency: int = 20,
    expected_fail: bool = False,
    expected_fail_reason: t.Optional[str] = None,
    test_prefix_length: t.Optional[int] = None,
    description: t.Optional[str] = None,
) -> Step:
    """Per-peer baseline: while only the loser set is up, record the (uniform) count of
    ``discriminator_asn`` in the AS-PATH the DUT ADVERTISED to each in-scope iBGP peer
    (``getPostfilterAdvertisedNetworks``, readable under UG since D109395098) for the
    test prefixes. Paired with
    ``create_verify_bgp_peer_advertised_as_path_converged_step``. This is the true
    per-peer distribution baseline (vs the DUT's single best-path selection). With
    ``expected_fail`` it logs + skips storing on any problem (XFAIL / measure-first)."""
    if not peer_parent_prefixes or not test_prefix_parents:
        raise ValueError(
            "create_snapshot_bgp_peer_advertised_as_path_step: peer_parent_prefixes "
            "and test_prefix_parents must be non-empty"
        )
    if description is None:
        description = (
            f"Baseline per-peer advertised AS{discriminator_asn} count for "
            f"{expected_prefix_count} test prefixes on {hostname} (key={snapshot_key})"
        )
    params: t.Dict[str, t.Any] = {
        "custom_step_name": "snapshot_bgp_peer_advertised_as_path",
        "hostname": hostname,
        "snapshot_key": snapshot_key,
        "peer_parent_prefixes": list(peer_parent_prefixes),
        "test_prefix_parents": list(test_prefix_parents),
        "discriminator_asn": int(discriminator_asn),
        "expected_prefix_count": int(expected_prefix_count),
        "max_concurrency": int(max_concurrency),
        "expected_fail": expected_fail,
    }
    if expected_fail_reason is not None:
        params["expected_fail_reason"] = expected_fail_reason
    if test_prefix_length is not None:
        params["test_prefix_length"] = int(test_prefix_length)
    return create_custom_step(params_dict=params, description=description)


def create_verify_bgp_peer_advertised_as_path_converged_step(
    hostname: str,
    snapshot_key: str,
    peer_parent_prefixes: t.List[str],
    test_prefix_parents: t.List[str],
    discriminator_asn: int,
    expected_prefix_count: int,
    expected_as_path_delta: int = 3,
    max_concurrency: int = 20,
    tolerance: int = 0,
    expected_fail: bool = False,
    expected_fail_reason: t.Optional[str] = None,
    test_prefix_length: t.Optional[int] = None,
    description: t.Optional[str] = None,
) -> Step:
    """Strict per-peer criterion-1: assert EVERY in-scope iBGP peer was advertised the
    winner set for EVERY test prefix (advertised-AS-PATH ``discriminator_asn`` count ==
    baseline - ``expected_as_path_delta``), catching a per-peer split-brain the
    DUT-side Loc-RIB check cannot see. Reads ``getPostfilterAdvertisedNetworks`` per
    peer (all peers, async-batched). Requires the paired snapshot; honors
    ``expected_fail`` (XFAIL) for the measure-first first run; never vacuous."""
    if not peer_parent_prefixes or not test_prefix_parents:
        raise ValueError(
            "create_verify_bgp_peer_advertised_as_path_converged_step: "
            "peer_parent_prefixes and test_prefix_parents must be non-empty"
        )
    if description is None:
        description = (
            f"Verify all in-scope iBGP peers were advertised the winning path for "
            f"{expected_prefix_count} test prefixes on {hostname} (key={snapshot_key})"
        )
    params: t.Dict[str, t.Any] = {
        "custom_step_name": "verify_bgp_peer_advertised_as_path_converged",
        "hostname": hostname,
        "snapshot_key": snapshot_key,
        "peer_parent_prefixes": list(peer_parent_prefixes),
        "test_prefix_parents": list(test_prefix_parents),
        "discriminator_asn": int(discriminator_asn),
        "expected_prefix_count": int(expected_prefix_count),
        "expected_as_path_delta": int(expected_as_path_delta),
        "max_concurrency": int(max_concurrency),
        "tolerance": int(tolerance),
        "expected_fail": expected_fail,
    }
    if expected_fail_reason is not None:
        params["expected_fail_reason"] = expected_fail_reason
    if test_prefix_length is not None:
        params["test_prefix_length"] = int(test_prefix_length)
    return create_custom_step(params_dict=params, description=description)


def _describe_bgp_sent_route_count_delta(
    *,
    hostname: str,
    snapshot_key: str,
    min_delta: int,
    max_delta: t.Optional[int],
    tolerance: int,
    peer_addrs: t.Optional[t.List[str]],
    peer_group_filter: t.Optional[str],
    peer_parent_prefixes: t.Optional[t.List[str]],
) -> str:
    bound = (
        f"in [{min_delta}, {max_delta}]" if max_delta is not None else f">= {min_delta}"
    )
    if peer_parent_prefixes:
        scope = f"peers under {peer_parent_prefixes}"
    elif peer_group_filter:
        scope = f"peer-group ~{peer_group_filter!r}"
    else:
        scope = f"{len(peer_addrs or [])} peer(s)"
    return (
        f"Verify BGP sent-count delta {bound} on {scope} on {hostname} "
        f"(key={snapshot_key}, tol={tolerance})"
    )


def _add_bgp_sent_route_delta_optional_params(
    params: t.Dict[str, t.Any],
    *,
    peer_addrs: t.Optional[t.List[str]],
    peer_group_filter: t.Optional[str],
    peer_parent_prefixes: t.Optional[t.List[str]],
    max_delta: t.Optional[int],
    min_baseline: int,
    expected_fail: bool,
    expected_fail_reason: t.Optional[str],
) -> None:
    if peer_addrs is not None:
        params["peer_addrs"] = list(peer_addrs)
    if peer_group_filter is not None:
        params["peer_group_filter"] = peer_group_filter
    if peer_parent_prefixes is not None:
        params["peer_parent_prefixes"] = list(peer_parent_prefixes)
    if max_delta is not None:
        params["max_delta"] = max_delta
    if min_baseline:
        params["min_baseline"] = min_baseline
    if expected_fail:
        params["expected_fail"] = True
        if expected_fail_reason is not None:
            params["expected_fail_reason"] = expected_fail_reason


def _add_bgp_sent_route_delta_convergence_params(
    params: t.Dict[str, t.Any],
    *,
    hard_timeout_seconds: t.Optional[float],
    poll_interval_seconds: t.Optional[float],
    stability_window_seconds: t.Optional[float],
    soft_threshold_seconds: t.Optional[float],
) -> None:
    if hard_timeout_seconds is None:
        return
    params["convergence_hard_timeout_seconds"] = hard_timeout_seconds
    for name, value in (
        ("convergence_poll_interval_seconds", poll_interval_seconds),
        ("convergence_stability_window_seconds", stability_window_seconds),
        ("convergence_soft_threshold_seconds", soft_threshold_seconds),
    ):
        if value is not None:
            params[name] = value


def create_verify_bgp_sent_route_count_delta_step(
    hostname: str,
    snapshot_key: str,
    min_delta: int,
    peer_addrs: t.Optional[t.List[str]] = None,
    peer_group_filter: t.Optional[str] = None,
    peer_parent_prefixes: t.Optional[t.List[str]] = None,
    max_delta: t.Optional[int] = None,
    tolerance: int = 0,
    min_baseline: int = 0,
    expected_fail: bool = False,
    expected_fail_reason: t.Optional[str] = None,
    # Opt-in convergence polling (default None = one-shot read, byte-identical
    # params). When ``convergence_hard_timeout_seconds`` is set, the step POLLS the
    # per-peer delta until it satisfies the constraint and holds for
    # ``convergence_stability_window_seconds``, up to the hard timeout -- instead of
    # relying on a fixed pre-read settle step.
    convergence_hard_timeout_seconds: t.Optional[float] = None,
    convergence_poll_interval_seconds: t.Optional[float] = None,
    convergence_stability_window_seconds: t.Optional[float] = None,
    convergence_soft_threshold_seconds: t.Optional[float] = None,
    description: t.Optional[str] = None,
    convergence_trigger_time_jq_var: t.Optional[str] = None,
) -> Step:
    """Verify each peer's ``postpolicy_sent_prefix_count`` moved by the expected
    delta since the matching ``create_snapshot_bgp_sent_route_counts_step`` step:
    at least ``min_delta`` and (optionally) at most ``max_delta``. Raises
    ``TestCaseFailure`` if more than ``tolerance`` peers violate. Paired with
    a snapshot step to close the spec-loyalty gap left by dropping absolute
    anchor counts on UG backpressure equality gates.

    ``min_delta``/``max_delta`` bound the SIGNED delta, so this expresses
    advertise (``min_delta=490, max_delta=510`` for +500), withdraw
    (``min_delta=-210, max_delta=-190`` for a ~200 drop), and "unchanged"
    (``min_delta=0, max_delta=0``) -- the three shapes the dual-stack-isolation
    (2.9.4) per-AFI distribution + isolation checks need.

    Peers are selected by ``peer_parent_prefixes`` (subnets),
    ``peer_group_filter`` (peer-group substring), or ``peer_addrs`` -- and the
    selector MUST match the one the paired snapshot used (the verify re-queries
    with it; a mismatch fails loudly). At least one must be supplied; if more
    than one is set they are resolved by precedence (peer_parent_prefixes >
    peer_group_filter > peer_addrs).

    Args:
        hostname: Device hostname.
        snapshot_key: Key from the matching snapshot step.
        min_delta: Minimum per-peer signed count change (inclusive).
        peer_addrs: Peer IPs to verify.
        peer_group_filter: Peer-group substring.
        peer_parent_prefixes: Subnets; verify every peer whose address is in one.
        max_delta: Optional maximum per-peer signed count change (inclusive).
        tolerance: Peers allowed to violate before the step fails
            (default 0 -- all must satisfy).
        min_baseline: Skip peers whose snapshot-time (baseline) count is below
            this -- e.g. peers not yet Established when the snapshot was taken
            (default 0 -- check every peer).
        description: Optional custom description.
    """
    if (
        peer_addrs is None
        and peer_group_filter is None
        and peer_parent_prefixes is None
    ):
        raise ValueError(
            "create_verify_bgp_sent_route_count_delta_step: pass peer_addrs, "
            "peer_group_filter, or peer_parent_prefixes"
        )
    if description is None:
        description = _describe_bgp_sent_route_count_delta(
            hostname=hostname,
            snapshot_key=snapshot_key,
            min_delta=min_delta,
            max_delta=max_delta,
            tolerance=tolerance,
            peer_addrs=peer_addrs,
            peer_group_filter=peer_group_filter,
            peer_parent_prefixes=peer_parent_prefixes,
        )
    params: t.Dict[str, t.Any] = {
        "custom_step_name": "verify_bgp_sent_route_count_delta",
        "hostname": hostname,
        "snapshot_key": snapshot_key,
        "min_delta": min_delta,
        "tolerance": tolerance,
    }
    _add_bgp_sent_route_delta_optional_params(
        params,
        peer_addrs=peer_addrs,
        peer_group_filter=peer_group_filter,
        peer_parent_prefixes=peer_parent_prefixes,
        max_delta=max_delta,
        min_baseline=min_baseline,
        expected_fail=expected_fail,
        expected_fail_reason=expected_fail_reason,
    )
    _add_bgp_sent_route_delta_convergence_params(
        params,
        hard_timeout_seconds=convergence_hard_timeout_seconds,
        poll_interval_seconds=convergence_poll_interval_seconds,
        stability_window_seconds=convergence_stability_window_seconds,
        soft_threshold_seconds=convergence_soft_threshold_seconds,
    )
    if convergence_trigger_time_jq_var is not None:
        if convergence_hard_timeout_seconds is None:
            raise ValueError(
                "convergence_trigger_time_jq_var requires convergence polling"
            )
        if not convergence_trigger_time_jq_var:
            raise ValueError("convergence_trigger_time_jq_var must be non-empty")
        return Step(
            name=StepName.CUSTOM_STEP,
            step_params=Params(
                json_params=json.dumps(params),
                jq_params={
                    "convergence_trigger_time_seconds": (
                        f".{convergence_trigger_time_jq_var}"
                    )
                },
            ),
            description=description,
        )
    return create_custom_step(params_dict=params, description=description)


def create_snapshot_bgp_vmhwm_step(
    hostname: str,
    snapshot_key: str,
    process_name: t.Optional[str] = None,
    description: t.Optional[str] = None,
) -> Step:
    """Snapshot the BGP++ (``bgpcpp``) VmHWM (peak RSS) on the DUT, tagged with
    ``snapshot_key`` for later look-up by ``create_verify_bgp_vmhwm_growth_step``.

    This is the snapshot-before half of a whole-test memory-growth bracket: it
    lets a long test snapshot VmHWM before an EMERGENT-length flap window and
    verify the growth after, so the measurement auto-matches however long the
    flap emergently runs -- unlike the fixed-duration spanning
    ``bgp_vmhwm_growth_monitor``. Reuses the same bgpcpp VmHWM read primitive.

    Args:
        hostname: DUT hostname (bgpcpp source of truth).
        snapshot_key: Unique key across the playbook; the matching verify step
            must use the same string.
        process_name: Optional BGP++ process name (default "bgpcpp").
        description: Optional custom description.
    """
    if description is None:
        description = (
            f"Snapshot BGP++ VmHWM baseline on {hostname} (key={snapshot_key})"
        )
    params: t.Dict[str, t.Any] = {
        "custom_step_name": "snapshot_bgp_vmhwm",
        "hostname": hostname,
        "snapshot_key": snapshot_key,
    }
    if process_name is not None:
        params["process_name"] = process_name
    return create_custom_step(params_dict=params, description=description)


def create_verify_bgp_vmhwm_growth_step(
    hostname: str,
    snapshot_key: str,
    growth_threshold_bytes: int,
    expected_fail: bool = False,
    expected_fail_reason: t.Optional[str] = None,
    process_name: t.Optional[str] = None,
    description: t.Optional[str] = None,
) -> Step:
    """Verify the BGP++ (``bgpcpp``) VmHWM grew by less than
    ``growth_threshold_bytes`` since the matching ``create_snapshot_bgp_vmhwm_step``
    -- the verify-after half of a whole-test memory-growth bracket.

    Same semantics as the spanning ``bgp_vmhwm_growth_monitor``: a DECREASE
    (VmHWM went down => bgpcpp restarted) hard-fails ALWAYS; growth over the
    threshold fails, unless ``expected_fail`` is set (then it logs a loud XFAIL
    and the test continues); otherwise PASS.

    Args:
        hostname: DUT hostname (bgpcpp source of truth).
        snapshot_key: Key from the matching snapshot step.
        growth_threshold_bytes: Max allowed VmHWM growth (current - baseline)
            in bytes (e.g. 500 * 1024**2 for "growth < 500 MB").
        expected_fail: When True, an over-threshold growth is a KNOWN discrepancy
            (XFAIL) -- logged loudly and marked, but the step does NOT raise (a
            DECREASE still hard-fails). Default False.
        expected_fail_reason: Reason surfaced in the XFAIL banner. Ignored unless
            ``expected_fail`` is True.
        process_name: Optional BGP++ process name (default "bgpcpp").
        description: Optional custom description.
    """
    if description is None:
        description = (
            f"Verify BGP++ VmHWM growth < "
            f"{growth_threshold_bytes / (1024 * 1024):.1f} MiB on {hostname} "
            f"(key={snapshot_key})"
        )
    params: t.Dict[str, t.Any] = {
        "custom_step_name": "verify_bgp_vmhwm_growth",
        "hostname": hostname,
        "snapshot_key": snapshot_key,
        "growth_threshold_bytes": int(growth_threshold_bytes),
    }
    if expected_fail:
        params["expected_fail"] = True
        if expected_fail_reason is not None:
            params["expected_fail_reason"] = expected_fail_reason
    if process_name is not None:
        params["process_name"] = process_name
    return create_custom_step(params_dict=params, description=description)


def create_verify_bgp_sent_route_counts_uniform_step(
    hostname: str,
    peer_addrs: t.Optional[t.List[str]] = None,
    peer_group_filter: t.Optional[str] = None,
    peer_parent_prefixes: t.Optional[t.List[str]] = None,
    min_count: int = 1,
    max_spread: int = 0,
    tolerance: int = 0,
    min_count_tolerance: t.Optional[int] = None,
    expected_fail: bool = False,
    expected_fail_reason: t.Optional[str] = None,
    description: t.Optional[str] = None,
) -> Step:
    """Verify every selected peer's ``postpolicy_sent_prefix_count`` is NON-ZERO
    and UNIFORM (max-min spread <= ``max_spread``).

    The UG-safe "all peers received the same route set / no peer is missing
    routes" gate (spec 2.9.6 criteria 1-2, or any "route counts identical on all
    peers" criterion). Reads the live PS gauge -- which works under Update Group --
    NOT ``getPostfilterAdvertisedNetworks`` (vacuous under UG, T271301144), so it
    cannot be fooled into a vacuous pass. Unlike the delta step this needs no prior
    snapshot -- it queries the current counts and asserts uniformity directly.

    Peers are selected by ``peer_parent_prefixes`` (subnets), ``peer_group_filter``
    (peer-group substring), or ``peer_addrs`` (precedence in that order; at least
    one required; a dynamic selector matching 0 sessions fails loudly).

    Args:
        hostname: Device hostname.
        peer_addrs / peer_group_filter / peer_parent_prefixes: peer selection.
        min_count: each peer's PS must be >= this -- a NON-ZERO floor that catches
            a peer that received nothing (default 1).
        max_spread: permitted (max - min) across peers; 0 = exactly equal.
        tolerance: peers allowed to violate before the step fails (default 0).
            With ``min_count_tolerance`` set this budget covers ONLY the spread
            violations; otherwise (default) it covers both violation classes.
        min_count_tolerance: OPT-IN split accounting. None (default) keeps the
            historical single-``tolerance`` budget for both below-min_count and
            spread violations -- byte-identical params, so existing callers/goldens
            are unchanged and this key is omitted. When set, below-min_count /
            non-zero-floor violations are checked against this budget while spread
            violations are checked against ``tolerance`` (fail if EITHER is
            exceeded). Pass 0 to require every peer non-zero (e.g. enforce a single
            recovered peer's advertised count) while still allowing spread slack.
        expected_fail: mark XFAIL (logged loudly + non-fatal) for a documented
            external uncertainty (e.g. the v6 cold-start next-hop-resolution
            slowness); warns if it unexpectedly passes. Default False.
        expected_fail_reason: reason surfaced in the XFAIL banner.
        description: optional custom description.
    """
    if (
        peer_addrs is None
        and peer_group_filter is None
        and peer_parent_prefixes is None
    ):
        raise ValueError(
            "create_verify_bgp_sent_route_counts_uniform_step: pass peer_addrs, "
            "peer_group_filter, or peer_parent_prefixes"
        )
    if description is None:
        _who = (
            f"peers under {peer_parent_prefixes}"
            if peer_parent_prefixes
            else f"peer-group ~{peer_group_filter!r}"
            if peer_group_filter
            else f"{len(peer_addrs or [])} peer(s)"
        )
        description = (
            f"Verify BGP sent-count uniform (>= {min_count}, spread <= {max_spread}) "
            f"on {_who} on {hostname} (tol={tolerance})"
        )
    params: t.Dict[str, t.Any] = {
        "custom_step_name": "verify_bgp_sent_route_counts_uniform",
        "hostname": hostname,
        "min_count": min_count,
        "max_spread": max_spread,
        "tolerance": tolerance,
    }
    if peer_addrs is not None:
        params["peer_addrs"] = list(peer_addrs)
    if peer_group_filter is not None:
        params["peer_group_filter"] = peer_group_filter
    if peer_parent_prefixes is not None:
        params["peer_parent_prefixes"] = list(peer_parent_prefixes)
    # Only serialize the split-accounting key when opted in, so existing callers
    # produce byte-identical params (no golden regression).
    if min_count_tolerance is not None:
        params["min_count_tolerance"] = min_count_tolerance
    if expected_fail:
        params["expected_fail"] = True
        if expected_fail_reason is not None:
            params["expected_fail_reason"] = expected_fail_reason
    return create_custom_step(params_dict=params, description=description)


def create_verify_bgp_update_group_member_addresses_step(
    hostname: str,
    ebgp_v4_peer_regex: str,
    ebgp_v6_peer_regex: str,
    ebgp_v4_peer_group: str,
    ebgp_v6_peer_group: str,
    flap_start_idx: int = 1,
    flap_end_idx: int = 32,
    expected_peer_state: str = "JOINED_RUNNING",
    assert_bit_position_unique: bool = False,
    description: t.Optional[str] = None,
) -> Step:
    """Verify the SPECIFIC flapped eBGP peers rejoined the CORRECT update group --
    literal criterion-1 identity parity for spec 2.6.1.

    Resolves the exact peer addresses of the flapped session range (``[flap_start_idx,
    flap_end_idx]`` per AFI) at RUNTIME via ``get_bgp_session_addresses`` (never
    re-derived arithmetically -- that is the start_index/DutIp offset bug), then
    asserts each target peer is (a) a member of an update group whose
    ``peer_group_name`` matches the expected eBGP peer-group (substring) AND whose
    negotiated AFI matches, (b) ESTABLISHED (getBgpSessions), and (c) in
    ``expected_peer_state`` (``peer_state_update_group``, default
    ``JOINED_RUNNING``). Unlike the aggregate 140/AFI member-count proxy this
    catches a duplicated / stale / wrong-identity member. Reports every violation
    together; a vacuous run (0 resolved addresses) FAILS loudly.

    Args:
        hostname: Device hostname.
        ebgp_v4_peer_regex / ebgp_v6_peer_regex: IXIA peer-name regexes for the
            flapped eBGP device groups (per AFI).
        ebgp_v4_peer_group / ebgp_v6_peer_group: expected update-group
            ``peer_group_name`` (matched as a substring) per AFI.
        flap_start_idx / flap_end_idx: inclusive 1-based session index range that
            was flapped, per AFI (default 1..32). Must match the flap track.
        expected_peer_state: required ``peer_state_update_group`` for every target
            peer (default "JOINED_RUNNING").
        assert_bit_position_unique: also assert each targeted eBGP update group
            allocated a DISTINCT ``bit_position`` to its members (a direct-ish
            bit-allocation signal). Skipped (warning, not failure) when
            bit_position looks like a vacuous stub. Default False.
        description: Optional custom description.
    """
    if description is None:
        description = (
            f"Verify flapped eBGP peers [{flap_start_idx}, {flap_end_idx}]/AFI "
            f"rejoined the correct update group (v4 ~{ebgp_v4_peer_group!r}, v6 "
            f"~{ebgp_v6_peer_group!r}) in {expected_peer_state} on {hostname}"
        )
    params: t.Dict[str, t.Any] = {
        "custom_step_name": "verify_bgp_update_group_member_addresses",
        "hostname": hostname,
        "ebgp_v4_peer_regex": ebgp_v4_peer_regex,
        "ebgp_v6_peer_regex": ebgp_v6_peer_regex,
        "ebgp_v4_peer_group": ebgp_v4_peer_group,
        "ebgp_v6_peer_group": ebgp_v6_peer_group,
        "flap_start_idx": flap_start_idx,
        "flap_end_idx": flap_end_idx,
        "expected_peer_state": expected_peer_state,
    }
    # Only serialize the bit-uniqueness opt-in when set, so existing callers /
    # goldens stay byte-identical.
    if assert_bit_position_unique:
        params["assert_bit_position_unique"] = True
    return create_custom_step(params_dict=params, description=description)


def create_log_bgp_route_distribution_probe_step(
    hostname: str,
    label: str = "",
    received_parent_prefixes: t.Optional[t.List[str]] = None,
    sent_parent_prefixes: t.Optional[t.List[str]] = None,
    description: t.Optional[str] = None,
) -> Step:
    """Diagnostic step (NEVER fails): log per-peer RECEIVED + SENT route counts.

    For crit-2 distribution debugging -- logs, for the inject-SOURCE peers
    (``received_parent_prefixes`` -> ``prepolicy_rcvd_prefix_count``) and the
    re-advertise targets (``sent_parent_prefixes`` -> ``postpolicy_sent_prefix_count``),
    each scope's peers/min/max/sum. Run before/after the inject and after the settle
    to see whether the DUT received the inject and how the re-advertisement climbs,
    disambiguating settle-too-short (sent climbs toward received) vs egress (received
    > 0, sent stays 0) vs inject-not-received (received == 0). Pure logging; raises
    nothing, so it never affects the run verdict.

    Args:
        hostname: Device hostname.
        label: free-text marker for the log line (e.g. "after-settle").
        received_parent_prefixes: peer-address subnets of the inject-source peers.
        sent_parent_prefixes: peer-address subnets of the re-advertise targets.
        description: Optional custom description.
    """
    if description is None:
        description = (
            f"Probe BGP route distribution ({label}) on {hostname}: received vs sent"
        )
    params: t.Dict[str, t.Any] = {
        "custom_step_name": "log_bgp_route_distribution_probe",
        "hostname": hostname,
        "label": label,
    }
    if received_parent_prefixes is not None:
        params["received_parent_prefixes"] = received_parent_prefixes
    if sent_parent_prefixes is not None:
        params["sent_parent_prefixes"] = sent_parent_prefixes
    return create_custom_step(params_dict=params, description=description)


def create_verify_bgp_advertised_nlris_step(
    hostname: str,
    peer_parent_prefixes: t.List[str],
    min_count: int = 1,
    require_identical: bool = True,
    expected_prefixes: t.Optional[t.List[str]] = None,
    max_concurrency: int = 20,
    tolerance: int = 0,
    expected_fail: bool = False,
    expected_fail_reason: t.Optional[str] = None,
    description: t.Optional[str] = None,
) -> Step:
    """Verify per-peer ADVERTISED NLRIs across every peer under
    ``peer_parent_prefixes``: each advertises >= ``min_count`` NLRIs and (default)
    all advertise the IDENTICAL set -- the Update Group guarantee, checked on ALL
    members via ``getPostfilterAdvertisedNetworks`` rather than a two-peer on-wire
    dump. Reads the per-peer post-policy adj-RIB-out (populated under UG on the
    fixed binary, T271301144/T281417842).

    Args:
        hostname: Device hostname (bgpcpp source of truth).
        peer_parent_prefixes: Subnets; every session whose peer address is inside
            one is checked (they should all belong to ONE update group for the
            identity assertion to be meaningful). A selector matching 0 sessions
            fails loudly (no vacuous pass).
        min_count: NON-ZERO floor -- each peer must advertise at least this many
            NLRIs (default 1; catches a peer that received nothing).
        require_identical: assert every peer advertises the identical NLRI set
            (default True -- the UG guarantee).
        expected_prefixes: optional CIDR list; each peer's set must contain all of
            them.
        max_concurrency: bound on concurrent per-peer reads (default 20).
        tolerance: peers allowed to violate before the step fails (default 0).
        expected_fail: mark XFAIL (logged loudly + non-fatal) for a documented
            external uncertainty; warns if it unexpectedly passes. Default False.
        expected_fail_reason: reason surfaced in the XFAIL banner.
        description: optional custom description.
    """
    if not peer_parent_prefixes:
        raise ValueError(
            "create_verify_bgp_advertised_nlris_step: peer_parent_prefixes is required"
        )
    if description is None:
        description = (
            f"Verify per-peer advertised NLRIs (identical={require_identical}, "
            f">= {min_count}) for peers under {peer_parent_prefixes} on {hostname} "
            f"(tol={tolerance})"
        )
    params: t.Dict[str, t.Any] = {
        "custom_step_name": "verify_bgp_advertised_nlris",
        "hostname": hostname,
        "peer_parent_prefixes": list(peer_parent_prefixes),
        "min_count": min_count,
        "require_identical": require_identical,
        "tolerance": tolerance,
    }
    if expected_prefixes is not None:
        params["expected_prefixes"] = list(expected_prefixes)
    # Only serialize non-default max_concurrency so existing/typical callers stay
    # byte-identical (no golden churn from the tuning knob).
    if max_concurrency != 20:
        params["max_concurrency"] = max_concurrency
    if expected_fail:
        params["expected_fail"] = True
        if expected_fail_reason is not None:
            params["expected_fail_reason"] = expected_fail_reason
    return create_custom_step(params_dict=params, description=description)


def create_verify_bgp_notification_occurred_step(
    hostname: str,
    snapshot_key: str,
    mode: str = "verify",
    peer_addrs: t.Optional[t.List[str]] = None,
    peer_group_filter: t.Optional[str] = None,
    peer_parent_prefixes: t.Optional[t.List[str]] = None,
    expected_notified_peers: int = 1,
    notified_tolerance: int = 0,
    reason_substrings: t.Optional[t.List[str]] = None,
    expected_fail: bool = False,
    expected_fail_reason: t.Optional[str] = None,
    description: t.Optional[str] = None,
) -> Step:
    """Assert a BGP hold-timer NOTIFICATION isolated to the targeted peer(s).

    Two modes over the SAME scope (``snapshot_key`` pairs them):

    - ``mode="snapshot"``: record each in-scope peer's ``num_resets`` baseline
      BEFORE the trigger (spec 2.9.3 step 2).
    - ``mode="verify"`` (default): re-read; the peers whose ``num_resets`` grew
      since the snapshot are the ones that reset in-window. Assert (a) at least
      ``expected_notified_peers`` and at most ``expected_notified_peers +
      notified_tolerance`` peers reset (spec "NOTIFICATION to ONE peer"), (b)
      each reset peer's ``last_reset_reason`` matches a hold-timer substring (a
      Hold-Timer-Expired NOTIFICATION, not some other reset), and (c) every
      in-scope peer that did NOT reset is still Established (intra-group
      isolation -- the other peers in the group are undisturbed).

    Peers are selected by ``peer_parent_prefixes`` (subnets, e.g. the eBGP AFI
    parent), ``peer_group_filter``, or ``peer_addrs`` (same precedence + vacuous
    guard as the PS-gauge steps). ``reason_substrings`` defaults to the
    hold-timer-expiry phrasings; ``expected_fail`` is the XFAIL escape hatch.
    """
    if (
        peer_addrs is None
        and peer_group_filter is None
        and peer_parent_prefixes is None
    ):
        raise ValueError(
            "create_verify_bgp_notification_occurred_step: pass peer_addrs, "
            "peer_group_filter, or peer_parent_prefixes"
        )
    if mode not in ("snapshot", "verify"):
        raise ValueError(
            f"create_verify_bgp_notification_occurred_step: mode must be "
            f"'snapshot' or 'verify', got {mode!r}"
        )
    if description is None:
        _who = (
            f"peers under {peer_parent_prefixes}"
            if peer_parent_prefixes
            else f"peer-group ~{peer_group_filter!r}"
            if peer_group_filter
            else f"{len(peer_addrs or [])} peer(s)"
        )
        if mode == "snapshot":
            description = (
                f"Snapshot BGP reset baseline for {_who} on {hostname} "
                f"(key={snapshot_key})"
            )
        else:
            description = (
                f"Verify hold-timer NOTIFICATION isolated to "
                f"{expected_notified_peers} peer(s) among {_who} on {hostname} "
                f"(key={snapshot_key})"
            )
    params: t.Dict[str, t.Any] = {
        "custom_step_name": "verify_bgp_notification_occurred",
        "hostname": hostname,
        "snapshot_key": snapshot_key,
        "mode": mode,
    }
    if peer_addrs is not None:
        params["peer_addrs"] = list(peer_addrs)
    if peer_group_filter is not None:
        params["peer_group_filter"] = peer_group_filter
    if peer_parent_prefixes is not None:
        params["peer_parent_prefixes"] = list(peer_parent_prefixes)
    if mode == "verify":
        params["expected_notified_peers"] = expected_notified_peers
        params["notified_tolerance"] = notified_tolerance
        if reason_substrings is not None:
            params["reason_substrings"] = list(reason_substrings)
        if expected_fail:
            params["expected_fail"] = True
            if expected_fail_reason is not None:
                params["expected_fail_reason"] = expected_fail_reason
    return create_custom_step(params_dict=params, description=description)


def create_verify_bgp_peers_joined_running_step(
    hostname: str,
    peer_addrs: t.Optional[t.List[str]] = None,
    peer_group_filter: t.Optional[str] = None,
    peer_parent_prefixes: t.Optional[t.List[str]] = None,
    expected_state: str = "JOINED_RUNNING",
    tolerance: int = 0,
    expected_fail: bool = False,
    expected_fail_reason: t.Optional[str] = None,
    description: t.Optional[str] = None,
) -> Step:
    """Verify every selected peer's update-group state is ``JOINED_RUNNING``.

    Reads ``TBgpSession.peer_state_update_group`` (the reliable per-session UG
    state under next-hop-self) via ``getBgpSessions`` and asserts each selected
    peer equals ``expected_state`` -- the "recovered peer + its group-mates
    re-synced into the update group" gate (spec 2.9.3 step 8). Scope the whole
    update group with ``peer_parent_prefixes`` (the eBGP AFI parent). Vacuous
    guard + XFAIL escape hatch match the PS-gauge steps.
    """
    if (
        peer_addrs is None
        and peer_group_filter is None
        and peer_parent_prefixes is None
    ):
        raise ValueError(
            "create_verify_bgp_peers_joined_running_step: pass peer_addrs, "
            "peer_group_filter, or peer_parent_prefixes"
        )
    if description is None:
        _who = (
            f"peers under {peer_parent_prefixes}"
            if peer_parent_prefixes
            else f"peer-group ~{peer_group_filter!r}"
            if peer_group_filter
            else f"{len(peer_addrs or [])} peer(s)"
        )
        description = (
            f"Verify update-group state {expected_state} on {_who} on {hostname} "
            f"(tol={tolerance})"
        )
    params: t.Dict[str, t.Any] = {
        "custom_step_name": "verify_bgp_peers_joined_running",
        "hostname": hostname,
        "expected_state": expected_state,
        "tolerance": tolerance,
    }
    if peer_addrs is not None:
        params["peer_addrs"] = list(peer_addrs)
    if peer_group_filter is not None:
        params["peer_group_filter"] = peer_group_filter
    if peer_parent_prefixes is not None:
        params["peer_parent_prefixes"] = list(peer_parent_prefixes)
    if expected_fail:
        params["expected_fail"] = True
        if expected_fail_reason is not None:
            params["expected_fail_reason"] = expected_fail_reason
    return create_custom_step(params_dict=params, description=description)


def create_snapshot_ixia_bgp_rx_stats_step(
    hostname: str,
    interface: str,
    snapshot_key: str,
    description: t.Optional[str] = None,
) -> Step:
    """Snapshot IXIA-side wire-received BGP counters (Rx Total Messages,
    Rx Updates, Routes Rx) on the given DUT-facing port. Pair with
    ``create_verify_ixia_bgp_rx_stats_delta_step`` to assert DUT sent
    updates on wire during a test window. Bypasses DUT-side egress-
    policy blind spots (spec 2.3.1 wire-side observability)."""
    if description is None:
        description = (
            f"Snapshot IXIA-side wire BGP RX stats on {hostname}:{interface} "
            f"(key={snapshot_key})"
        )
    return create_custom_step(
        params_dict={
            "custom_step_name": "snapshot_ixia_bgp_rx_stats",
            "hostname": hostname,
            "interface": interface,
            "snapshot_key": snapshot_key,
        },
        description=description,
    )


def create_snapshot_bgp_update_sent_counter_step(
    hostname: str,
    snapshot_key: str,
) -> Step:
    """Snapshot BGP++'s cumulative sent-UPDATE counter before a trigger."""
    return create_custom_step(
        params_dict={
            "custom_step_name": "snapshot_bgp_update_sent_counter",
            "hostname": hostname,
            "snapshot_key": snapshot_key,
        },
        description=(
            f"Snapshot BGP++ sent-UPDATE counter on {hostname} (key={snapshot_key})"
        ),
    )


def create_mark_bgp_update_trigger_step(
    hostname: str,
    snapshot_key: str,
) -> Step:
    """Record the start of an Open/R trigger for BGP convergence timing."""
    return create_custom_step(
        params_dict={
            "custom_step_name": "mark_bgp_update_trigger",
            "hostname": hostname,
            "snapshot_key": snapshot_key,
        },
        description=f"Start BGP UPDATE convergence timer on {hostname}",
    )


def create_verify_openr_pnh_route_state_step(
    hostname: str,
    start_ipv4s: t.Sequence[str],
    start_ipv6s: t.Sequence[str],
    count: int,
    step: int,
    expected_present: bool,
    timeout_seconds: int = 30,
    poll_interval_seconds: int = 2,
) -> Step:
    """Verify selected Open/R PNH routes in FibAgent and hardware FIB."""
    expected_state = "present" if expected_present else "absent"
    return create_custom_step(
        params_dict={
            "custom_step_name": "verify_openr_pnh_route_state",
            "hostname": hostname,
            "start_ipv4s": list(start_ipv4s),
            "start_ipv6s": list(start_ipv6s),
            "count": count,
            "step": step,
            "expected_present": expected_present,
            "timeout_seconds": timeout_seconds,
            "poll_interval_seconds": poll_interval_seconds,
        },
        description=(
            f"Verify selected Open/R PNH routes are {expected_state} on {hostname}"
        ),
    )


def create_wait_for_bgp_update_sent_step(
    hostname: str,
    snapshot_key: str,
    timeout_seconds: int = 60,
    poll_interval_seconds: int = 5,
    late_observation_timeout_seconds: int = 0,
) -> Step:
    """Require an UPDATE in-window and optionally observe late UPDATEs."""
    return create_custom_step(
        params_dict={
            "custom_step_name": "wait_for_bgp_update_sent",
            "hostname": hostname,
            "snapshot_key": snapshot_key,
            "timeout_seconds": timeout_seconds,
            "poll_interval_seconds": poll_interval_seconds,
            "late_observation_timeout_seconds": late_observation_timeout_seconds,
        },
        description=(
            f"Require BGP++ to send an UPDATE on {hostname} within {timeout_seconds}s; "
            f"observe late UPDATEs for {late_observation_timeout_seconds}s"
        ),
    )


def create_verify_bgp_update_send_quiet_step(
    hostname: str,
    snapshot_key: str,
) -> Step:
    """Verify BGP++ sent no UPDATEs after the trigger window."""
    return create_custom_step(
        params_dict={
            "custom_step_name": "verify_bgp_update_send_quiet",
            "hostname": hostname,
            "snapshot_key": snapshot_key,
        },
        description=(
            f"Verify sustained BGP UPDATE stability on {hostname} (key={snapshot_key})"
        ),
    )


def create_snapshot_bgp_withdraw_sent_counter_step(
    hostname: str,
    snapshot_key: str,
) -> Step:
    """Snapshot BGP++'s cumulative sent-withdrawal counter."""
    return create_custom_step(
        params_dict={
            "custom_step_name": "snapshot_bgp_withdraw_sent_counter",
            "hostname": hostname,
            "snapshot_key": snapshot_key,
        },
        description=(
            f"Snapshot BGP++ sent-withdrawal counter on {hostname} (key={snapshot_key})"
        ),
    )


def create_verify_bgp_withdraw_send_quiet_step(
    hostname: str,
    snapshot_key: str,
) -> Step:
    """Verify BGP++ sent no withdrawals during metric oscillation."""
    return create_custom_step(
        params_dict={
            "custom_step_name": "verify_bgp_withdraw_send_quiet",
            "hostname": hostname,
            "snapshot_key": snapshot_key,
        },
        description=f"Verify BGP++ sent no withdrawals on {hostname}",
    )


def create_verify_ixia_bgp_rx_stats_delta_step(
    hostname: str,
    interface: str,
    snapshot_key: str,
    min_rx_delta: int = 1,
    counter_name: str = "rx_total_messages",
    description: t.Optional[str] = None,
) -> Step:
    """Verify IXIA-side wire-received BGP ``counter_name`` grew by at
    least ``min_rx_delta`` since the matching snapshot. Proves DUT
    actively sent BGP traffic to fast peers on-wire during storm --
    spec 2.3.1 wire-side observability that works even under restrictive
    DUT egress policy (keepalives always pass)."""
    if description is None:
        description = (
            f"Verify IXIA-side wire BGP {counter_name} delta >= "
            f"{min_rx_delta} on {hostname}:{interface} "
            f"(key={snapshot_key})"
        )
    return create_custom_step(
        params_dict={
            "custom_step_name": "verify_ixia_bgp_rx_stats_delta",
            "hostname": hostname,
            "interface": interface,
            "snapshot_key": snapshot_key,
            "min_rx_delta": min_rx_delta,
            "counter_name": counter_name,
        },
        description=description,
    )


def create_snapshot_per_peer_bgp_rx_stats_step(
    hostname: str,
    interface: str,
    snapshot_key: str,
    peer_addrs: t.List[str],
    counter_name: str = "rx_total_messages",
    description: t.Optional[str] = None,
) -> Step:
    """Snapshot IXIA-side per-peer wire-received BGP counters. Reads the
    same ``BGP+ Peer Per Port`` StatView as the aggregate G3 snapshot but
    keeps per-peer rows indexed by neighbor peer IP. Pair with
    ``create_verify_per_peer_bgp_rx_asymmetry_step`` to prove fast peers
    receive more wire updates than slow peers in the same UG (spec 2.3.1
    wire-side asymmetry -- complement to the DUT-internal queue-depth
    asymmetry proof in ``verify_fast_peer_queue_shallower``)."""
    if description is None:
        description = (
            f"Snapshot IXIA-side per-peer BGP {counter_name} on "
            f"{hostname}:{interface} for {len(peer_addrs)} peer(s) "
            f"(key={snapshot_key})"
        )
    return create_custom_step(
        params_dict={
            "custom_step_name": "snapshot_per_peer_bgp_rx_stats",
            "hostname": hostname,
            "interface": interface,
            "snapshot_key": snapshot_key,
            "peer_addrs": peer_addrs,
            "counter_name": counter_name,
        },
        description=description,
    )


def create_verify_per_peer_bgp_rx_asymmetry_step(
    hostname: str,
    interface: str,
    snapshot_key: str,
    fast_peer_addrs: t.List[str],
    slow_peer_addrs: t.List[str],
    min_ratio: float = 1.0,
    counter_name: str = "rx_total_messages",
    description: t.Optional[str] = None,
) -> Step:
    """Verify median IXIA-side wire-received ``counter_name`` on
    ``fast_peer_addrs`` is at least ``min_ratio`` times median on
    ``slow_peer_addrs`` since the matching snapshot. Wire-side proof of
    the spec 2.3.1 central claim: fast peers, in the same UG as slow
    peers, receive more BGP messages on wire during storm -- DUT drains
    fast independently of slow inside the UG. Median (not mean) for
    outlier robustness against a flapping peer."""
    if description is None:
        description = (
            f"Verify IXIA per-peer BGP {counter_name} asymmetry on "
            f"{hostname}:{interface}: median(fast)/median(slow) >= "
            f"{min_ratio} across {len(fast_peer_addrs)} fast + "
            f"{len(slow_peer_addrs)} slow peer(s) (key={snapshot_key})"
        )
    return create_custom_step(
        params_dict={
            "custom_step_name": "verify_per_peer_bgp_rx_asymmetry",
            "hostname": hostname,
            "interface": interface,
            "snapshot_key": snapshot_key,
            "fast_peer_addrs": fast_peer_addrs,
            "slow_peer_addrs": slow_peer_addrs,
            "min_ratio": min_ratio,
            "counter_name": counter_name,
        },
        description=description,
    )


def create_snapshot_peer_egress_stats_step(
    hostname: str,
    peer_addrs: t.List[str],
    snapshot_key: str,
    description: t.Optional[str] = None,
) -> Step:
    """Snapshot per-peer ``TPeerEgressStats`` backpressure counters
    (``adjribout_queue_blocks``, ``send_queue_blocks``,
    ``total_async_socket_buffered``) for later delta verification via
    ``create_verify_backpressure_observed_step``. DUT-internal signal --
    works regardless of egress-policy filtering that would blind a wire-
    side probe (spec 2.3.1)."""
    if description is None:
        description = (
            f"Snapshot per-peer egress stats on {hostname} for "
            f"{len(peer_addrs)} peer(s) (key={snapshot_key})"
        )
    return create_custom_step(
        params_dict={
            "custom_step_name": "snapshot_peer_egress_stats",
            "hostname": hostname,
            "peer_addrs": list(peer_addrs),
            "snapshot_key": snapshot_key,
        },
        description=description,
    )


def create_verify_backpressure_observed_step(
    hostname: str,
    peer_addrs: t.List[str],
    snapshot_key: str,
    min_peers_with_block: int = 1,
    description: t.Optional[str] = None,
) -> Step:
    """Verify at least ``min_peers_with_block`` of ``peer_addrs`` show an
    ``adjribout_queue_blocks`` delta > 0 since the matching snapshot. Spec
    2.3.1 pre-condition: the storm actually stressed DUT's UG send path.
    If this fires with 0 blocks the workload didn't induce backpressure
    and the rest of the 2.3.1 asymmetry assertion is not meaningfully
    testable."""
    if description is None:
        description = (
            f"Verify backpressure observed on {hostname}: >= "
            f"{min_peers_with_block} of {len(peer_addrs)} peer(s) with "
            f"adjribout_queue_blocks delta (key={snapshot_key})"
        )
    return create_custom_step(
        params_dict={
            "custom_step_name": "verify_backpressure_observed",
            "hostname": hostname,
            "peer_addrs": list(peer_addrs),
            "snapshot_key": snapshot_key,
            "min_peers_with_block": min_peers_with_block,
        },
        description=description,
    )


def create_verify_ug_queue_recovered_step(
    hostname: str,
    peer_addrs: t.List[str],
    max_queue_size: int = 0,
    num_samples: int = 3,
    sample_interval_s: float = 10,
    description: t.Optional[str] = None,
) -> Step:
    """Verify per-peer ``total_async_socket_buffered`` <= ``max_queue_size``
    PERSISTENTLY across ``num_samples`` samples ``sample_interval_s`` apart.
    Spec 2.3.1 "no peer PERMANENTLY stuck" — a transient in-flight byte at
    one instant is normal traffic, not stuck state. Only peers > max in
    EVERY sample fail. No tolerance knob — strict spec loyalty."""
    if description is None:
        description = (
            f"Verify UG queues recovered on {hostname}: {len(peer_addrs)} "
            f"peer(s) persistently <= {max_queue_size} across "
            f"{num_samples} samples ({sample_interval_s}s apart)"
        )
    return create_custom_step(
        params_dict={
            "custom_step_name": "verify_ug_queue_recovered",
            "hostname": hostname,
            "peer_addrs": list(peer_addrs),
            "max_queue_size": max_queue_size,
            "num_samples": num_samples,
            "sample_interval_s": sample_interval_s,
        },
        description=description,
    )


def create_verify_fast_peer_queue_shallower_step(
    hostname: str,
    fast_peer_addrs: t.List[str],
    slow_peer_addrs: t.List[str],
    snapshot_key: str,
    min_delta: float = 0,
    description: t.Optional[str] = None,
) -> Step:
    """Verify avg ``adjribout_queue_blocks`` DELTA on ``fast_peer_addrs``
    is at least ``min_delta`` less than avg DELTA on ``slow_peer_addrs``
    since the matching ``snapshot_peer_egress_stats`` step (spec 2.3.1
    central claim -- run mid-storm). Positive delta proves DUT blocks
    on slow peers MORE than fast peers within the same UG."""
    if description is None:
        description = (
            f"Verify fast peers shallower than slow peers on {hostname} "
            f"(fast={len(fast_peer_addrs)}, slow={len(slow_peer_addrs)}, "
            f"key={snapshot_key}, min_delta={min_delta})"
        )
    return create_custom_step(
        params_dict={
            "custom_step_name": "verify_fast_peer_queue_shallower",
            "hostname": hostname,
            "fast_peer_addrs": list(fast_peer_addrs),
            "slow_peer_addrs": list(slow_peer_addrs),
            "snapshot_key": snapshot_key,
            "min_delta": min_delta,
        },
        description=description,
    )


def create_verify_dut_received_from_peer_group_step(
    hostname: str,
    sender_peer_addr_prefix: str,
    min_prefix_count: int,
    description: t.Optional[str] = None,
) -> Step:
    """Verify DUT's ingress RIB has received at least ``min_prefix_count``
    prefixes from sender peers whose ``peer_addr`` starts with
    ``sender_peer_addr_prefix``. Spec-loyal "storm arrived at DUT" probe --
    decoupled from egress-policy filtering, which controls what DUT then
    re-advertises OUT to other peers (some topologies drop heavy-attr storms
    at egress, making per-peer ``sent_prefix_count`` an unreliable
    "storm delivered" signal). Ingress RIB inspection is topology-agnostic.

    Filters by peer address prefix rather than DUT-side ``peer_group`` name
    because DUT-side peer_group values reflect BGP peer-group naming (e.g.
    ``EB-EB``) not IXIA topology names.

    Args:
        hostname: Device hostname.
        sender_peer_addr_prefix: String prefix of storm-sender peer IPv6
            addresses (e.g. ``"2401:db00:e50d:11:9"`` for iBGP plane 1).
        min_prefix_count: Assert total ``prepolicy_rcvd_prefix_count`` across
            matching peers >= this. Raises ``TestCaseFailure`` otherwise.
        description: Optional custom description.
    """
    if description is None:
        description = (
            f"Verify DUT {hostname} ingress RIB received >= "
            f"{min_prefix_count} prefix(es) from peers with peer_addr "
            f"starting with {sender_peer_addr_prefix!r}"
        )
    return create_custom_step(
        params_dict={
            "custom_step_name": "verify_dut_received_prefixes_from_peer_group",
            "hostname": hostname,
            "sender_peer_addr_prefix": sender_peer_addr_prefix,
            "min_prefix_count": min_prefix_count,
        },
        description=description,
    )


def create_record_jq_timestamp_step(
    var_name: str,
    description: t.Optional[str] = None,
) -> Step:
    """
    Create a step to record the current timestamp as a jq variable.

    Args:
        var_name: Name of the jq variable to store the timestamp in
        description: Custom description for the step

    Returns:
        Step object for recording a jq timestamp
    """
    return Step(
        name=StepName.CUSTOM_STEP,
        description=description or f"Record timestamp as '{var_name}'",
        step_params=Params(
            json_params=json.dumps(
                {
                    "custom_step_name": "record_jq_timestamp",
                    "var_name": var_name,
                }
            )
        ),
    )


def create_fpf_set_interface_admin_step(
    interfaces: t.List[str],
    enable: bool,
    description: t.Optional[str] = None,
) -> Step:
    """Disable/enable interface(s) on the live agent via thrift (held).

    Unlike ``create_interface_permanent_flap_step`` (COOP change_port_admin_state
    config patcher — only patches config, does not shut the running port without
    a reload/warmboot), this sets the agent port admin state immediately via
    ``setPortState`` and holds it until changed. Use it for FPF interface-disable
    tests that must have the port actually down during the assertion window; pair
    a disable (enable=False) with an enable (enable=True) to restore.
    """
    return Step(
        name=StepName.CUSTOM_STEP,
        description=description
        or f"{'Enable' if enable else 'Disable'} {interfaces} (thrift admin state)",
        step_params=Params(
            json_params=json.dumps(
                {
                    "custom_step_name": "fpf_set_interface_admin",
                    "interfaces": interfaces,
                    "is_enable": enable,
                }
            )
        ),
    )


def create_fpf_drain_interface_step(
    interfaces: t.Optional[t.List[str]],
    drain: bool,
    description: t.Optional[str] = None,
) -> Step:
    """Soft-drain / undrain via the on-box LOCAL_DRAINER, calling the driver
    directly. With ``interfaces`` -> per-port (``async_softdrain_interface`` /
    ``async_undrain_interface``); with EMPTY/None ``interfaces`` -> device-level
    soft-drain of the whole DUT (``async_onbox_softdrain_device`` /
    ``async_onbox_undrain_device``).

    Unlike ``create_drain_undrain_step(interfaces=...)`` (whose LOCAL_DRAINER path
    resolves the interface against the discovered fabric topology and raises
    "Interface not found" for the GPU-facing GTSW port), the per-port path here
    passes the name straight to the drainer — the GPU-facing port is a real agent
    port but is not in the fabric-discovered interface list. And unlike the
    generic device path (which HARD-drains via ``async_onbox_drain_device``), the
    device path here SOFT-drains for the control-up/data-drains contract. Use for
    FPF link drain/undrain (per-port) and device drain/undrain (no interfaces).
    """
    intfs = interfaces or []
    if intfs:
        default_desc = f"{'Soft-drain' if drain else 'Undrain'} {intfs} (local drainer)"
    else:
        default_desc = f"{'Soft-drain' if drain else 'Undrain'} DEVICE (local drainer)"
    return Step(
        name=StepName.CUSTOM_STEP,
        description=description or default_desc,
        step_params=Params(
            json_params=json.dumps(
                {
                    "custom_step_name": "fpf_drain_interface",
                    "interfaces": intfs,
                    "is_drain": drain,
                }
            )
        ),
    )


def create_fpf_verify_disruption_step(
    interfaces: t.List[str],
    expect_admin_enabled: bool = False,
    expect_oper_up: bool = False,
    mode: str = "admin_oper",
    expect_drained: bool = True,
    fail_if_ineffective: bool = False,
    description: t.Optional[str] = None,
) -> Step:
    """Disruption-effectiveness gate: verify the disrupted interface(s) actually
    changed state on the live agent and record the verdict so downstream lane
    checks SKIP (inconclusive) instead of FAILing when the disruption did not
    take. Place right after the disrupt/longevity.

    mode="admin_oper" (default): verify admin/oper state via wedge_agent thrift.
    Defaults expect the port DOWN (admin DISABLED, oper DOWN), i.e. a disable.

    mode="drain": verify each port's ``isDrained`` flag (getPortInfo) matches
    ``expect_drained`` — the correct signal for a link DRAIN, where the port
    stays admin=ENABLED / oper=UP by design (control up, data depreferenced).

    fail_if_ineffective=True RAISES (fails the step / aborts the playbook) when
    the disruption did not take, instead of only recording it for downstream
    SKIP. Use for a disable, where a no-op makes the whole test meaningless.
    """
    return Step(
        name=StepName.CUSTOM_STEP,
        description=description or f"Verify disruption effective on {interfaces}",
        step_params=Params(
            json_params=json.dumps(
                {
                    "custom_step_name": "fpf_verify_disruption",
                    "interfaces": interfaces,
                    "mode": mode,
                    "expect_admin_enabled": expect_admin_enabled,
                    "expect_oper_up": expect_oper_up,
                    "expect_drained": expect_drained,
                    "fail_if_ineffective": fail_if_ineffective,
                }
            )
        ),
    )


def create_fpf_record_disruption_time_step(
    description: t.Optional[str] = None,
) -> Step:
    """Record the FPF disruption wall-clock time into the collector registry.

    Place immediately before the interface flap / link drain in a link-event
    disrupt playbook. The prod/broad-prefix transition health check then measures
    the reachable->unreachable transition from this exact moment (30s SLA),
    rather than from test_case_start (which precedes the long stabilization).
    """
    return Step(
        name=StepName.CUSTOM_STEP,
        description=description or "Record FPF disruption time",
        step_params=Params(
            json_params=json.dumps({"custom_step_name": "record_fpf_disruption_time"})
        ),
    )


def create_fpf_repeated_service_crash_step(
    service: taac_types.Service,
    every_sec: int = 1,
    duration_sec: int = 60,
    device_regexes: t.Optional[t.List[str]] = None,
    description: t.Optional[str] = None,
) -> Step:
    """Repeatedly crash a service (SIGKILL) over a window on the target device.

    Drives ``async_crash_service`` (``pkill -9``) every ``every_sec`` for
    ``duration_sec`` on the in-scope device (``device_regexes``, typically the
    DUT GTSW). For the FSDB unclean-exit FPF test: kill ``fsdb`` every 1s for 60s
    so the daemon never exits gracefully and the recovery path is exercised under
    sustained churn. Implemented as a CUSTOM_STEP (no new StepName enum).

    Args:
        service: The service to crash (e.g. ``taac_types.Service.FSDB``).
        every_sec: Seconds between successive kills (default 1).
        duration_sec: Total crash window in seconds (default 60).
        device_regexes: Optional device-regex scope (e.g. the DUT GTSW).
        description: Custom step description.
    """
    return Step(
        name=StepName.CUSTOM_STEP,
        description=description
        or f"Crash {service.name} every {every_sec}s for {duration_sec}s",
        step_params=Params(
            json_params=json.dumps(
                {
                    "custom_step_name": "fpf_repeated_service_crash",
                    "service": int(service.value),
                    "every_sec": every_sec,
                    "duration_sec": duration_sec,
                }
            )
        ),
        device_regexes=device_regexes,
    )


def create_fpf_ndp_clear_loop_step(
    every_sec: int = 1,
    duration_sec: int = 120,
    device_regexes: t.Optional[t.List[str]] = None,
    description: t.Optional[str] = None,
) -> Step:
    """Repeatedly clear the NDP table over a window on the target GTSW.

    Runs ``fboss2 clear ndp`` every ``every_sec`` for ``duration_sec`` — a
    persistent NDP flush that exercises neighbor re-resolution under sustained
    clearing during a NIC-side link-flap FPF test. Implemented as a CUSTOM_STEP
    (no new StepName enum).

    Args:
        every_sec: Seconds between successive clears (default 1).
        duration_sec: Total clearing window in seconds (default 120).
        device_regexes: Optional device-regex scope (e.g. the DUT GTSW).
        description: Custom step description.
    """
    return Step(
        name=StepName.CUSTOM_STEP,
        description=description or f"Clear NDP every {every_sec}s for {duration_sec}s",
        step_params=Params(
            json_params=json.dumps(
                {
                    "custom_step_name": "fpf_ndp_clear_loop",
                    "every_sec": every_sec,
                    "duration_sec": duration_sec,
                }
            )
        ),
        device_regexes=device_regexes,
    )


def create_fpf_rapid_flap_step(
    interfaces_by_device: t.Dict[str, t.List[str]],
    duration_sec: int,
    flap_interval_sec: int = 1,
    device_regexes: t.Optional[t.List[str]] = None,
    description: t.Optional[str] = None,
) -> Step:
    """Rapidly flap per-device interfaces over a window.

    Wraps the driver's ``async_do_rapid_interface_flaps`` (tx_disable -> sleep
    0.1 -> tx_enable per flap). At runtime the step picks the entry in
    ``interfaces_by_device`` matching the DUT it runs on and flaps those ports
    ``duration_sec // flap_interval_sec`` times. Used for the all-downlinks /
    all-uplinks rapid-flap FPF tests; the interface map is supplied by the config
    (e.g. via LLDP discovery). Implemented as a CUSTOM_STEP (no new StepName).

    Args:
        interfaces_by_device: {device_name: [interface, ...]} resolved map.
        duration_sec: Total flap window in seconds.
        flap_interval_sec: Seconds between flaps (== interval_to_link_up); also
            the per-flap cost used to derive the flap count (default 1).
        device_regexes: Optional device-regex scope.
        description: Custom step description.
    """
    return Step(
        name=StepName.CUSTOM_STEP,
        description=description
        or f"Rapid-flap interfaces for {duration_sec}s "
        f"({', '.join(interfaces_by_device.keys())})",
        step_params=Params(
            json_params=json.dumps(
                {
                    "custom_step_name": "fpf_rapid_flap",
                    "interfaces_by_device": interfaces_by_device,
                    "duration_sec": duration_sec,
                    "flap_interval_sec": flap_interval_sec,
                }
            )
        ),
        device_regexes=device_regexes,
    )


def create_fpf_rapid_flap_step_lldp(
    neighbor_pattern: t.Optional[str] = None,
    duration_sec: int = 0,
    flap_interval_sec: int = 1,
    neighbor_hosts: t.Optional[t.List[str]] = None,
    flap_down_time_sec: float = 6.0,
    flap_up_time_sec: float = 6.0,
    device_regexes: t.Optional[t.List[str]] = None,
    description: t.Optional[str] = None,
) -> Step:
    """Rapid-flap variant that resolves interfaces from LLDP at run time.

    Unlike ``create_fpf_rapid_flap_step``, which takes a pre-resolved
    ``{device: [interface]}`` map (configs build at import time with no device
    access), this variant defers interface selection to step execution: the
    handler calls ``async_get_lldp_neighbors`` on the DUT driver and picks the
    local interfaces whose LLDP remote system name matches either an explicit
    ``neighbor_hosts`` set (exact match, preferred) or a ``neighbor_pattern``
    (fnmatch shell glob, fallback).

    The handler flaps the resolved set on a WALL-CLOCK bound: it keeps issuing
    single flaps until ``duration_sec`` elapses, so the step always stops on
    time even when each flap of many ports takes minutes. ``flap_down_time_sec``
    controls how long each port is held tx_disabled per flap.

    Use this for tc32/tc33-style downlink/uplink flap tests when the testbed
    wiring may change — pass an explicit ``neighbor_hosts`` list (e.g. the
    configured ``GPU_HOSTS``) to scope precisely, or a stable PATTERN (e.g.
    ``"stsw*"`` for the spine) instead of hardcoding lane breakouts.

    Args:
        neighbor_pattern: fnmatch glob matched (case-insensitive) against the
            LLDP remote system name. Drivers strip ``.tfbnw.net`` /
            ``.facebook.com`` before exposing the name. Used only when
            ``neighbor_hosts`` is not set.
        duration_sec: Total flap window in seconds (wall-clock bound).
        flap_interval_sec: Seconds between flaps / link-up settle; default 1.
        neighbor_hosts: explicit list of remote system names to match exactly
            (domain-stripped, case-insensitive). Preferred over the glob.
        flap_down_time_sec: Seconds the port is held tx_disabled per cycle;
            default 6.
        flap_up_time_sec: Seconds the port is held tx_enabled (UP) per cycle;
            default 6. Each flap cycle is a full on-box loop —
            ``tx_enable -> sleep up -> tx_disable -> sleep down`` — and the
            handler leaves the link UP at the end. ``flap_interval_sec`` is
            unused with the symmetric cycle.
        device_regexes: Optional device-regex scope (e.g. the DUT GTSW).
        description: Custom step description.
    """
    return Step(
        name=StepName.CUSTOM_STEP,
        description=description
        or (
            "Rapid-flap LLDP-resolved interfaces "
            f"(neighbors~={neighbor_hosts or neighbor_pattern!r}) "
            f"for {duration_sec}s"
        ),
        step_params=Params(
            json_params=json.dumps(
                {
                    "custom_step_name": "fpf_rapid_flap_lldp",
                    "neighbor_pattern": neighbor_pattern,
                    "neighbor_hosts": neighbor_hosts,
                    "duration_sec": duration_sec,
                    "flap_interval_sec": flap_interval_sec,
                    "down_time_sec": flap_down_time_sec,
                    "up_time_sec": flap_up_time_sec,
                }
            )
        ),
        device_regexes=device_regexes,
    )


def create_fpf_multi_gtsw_rapid_flap_step(
    gtsws: t.List[str],
    duration_sec: int,
    neighbor_hosts: t.Optional[t.List[str]] = None,
    neighbor_pattern: t.Optional[str] = None,
    flap_down_time_sec: float = 7.0,
    flap_up_time_sec: float = 7.0,
    flap_interval_sec: int = 1,
    churn_service: t.Optional[taac_types.Service] = None,
    churn_action: str = "restart",
    churn_every_sec: int = 120,
    churn_devices: t.Optional[t.List[str]] = None,
    uniform_interface_discovery: bool = False,
    description: t.Optional[str] = None,
) -> Step:
    """Flap the links facing a GPU host across MANY GTSWs CONCURRENTLY.

    Single CUSTOM_STEP that, for every GTSW in ``gtsws``, builds that GTSW's
    driver, resolves (at run time, via LLDP) the local interfaces facing
    ``neighbor_hosts`` (the chosen rtptest GPU host), and runs a wall-clock
    bounded symmetric flap loop on them. All GTSWs flap in PARALLEL
    (``asyncio.gather`` inside the handler) — the runner's per-Step device
    fan-out is sequential, so cross-GTSW parallelism lives in the handler.

    Optionally runs a CONCURRENT service-churn loop for the same window: when
    ``churn_service`` is set, every ``churn_every_sec`` it ``restart``s
    (graceful) or ``crash``es (SIGKILL) the service across ``churn_devices``
    (defaults to ``gtsws``) in parallel. Models "flap all GTSWs AND restart
    bgpd/fsdb/wedge_agent every 2 min in parallel".

    Args:
        gtsws: GTSW hostnames to flap (each gets its own driver).
        duration_sec: total flap window in seconds (wall-clock bound).
        neighbor_hosts: GPU host(s) whose facing links are flapped (exact match).
        neighbor_pattern: fnmatch glob fallback when neighbor_hosts is empty.
        flap_down_time_sec: per-cycle link-down hold (default 7).
        flap_up_time_sec: per-cycle link-up hold (default 7).
        flap_interval_sec: interval_to_link_up passed to the driver (default 1).
        churn_service: optional service to churn in parallel; omit for pure flap.
        churn_action: "restart" (default) or "crash".
        churn_every_sec: seconds between churn rounds (default 120 = 2 min).
        churn_devices: devices to churn (defaults to ``gtsws``).
        description: Custom step description.
    """
    params: t.Dict[str, t.Any] = {
        "custom_step_name": "fpf_multi_gtsw_rapid_flap",
        "gtsws": gtsws,
        "neighbor_hosts": neighbor_hosts,
        "neighbor_pattern": neighbor_pattern,
        "duration_sec": duration_sec,
        "down_time_sec": flap_down_time_sec,
        "up_time_sec": flap_up_time_sec,
        "flap_interval_sec": flap_interval_sec,
        "churn_every_sec": churn_every_sec,
        "churn_action": churn_action,
        "churn_devices": churn_devices,
        "uniform_interface_discovery": uniform_interface_discovery,
    }
    if churn_service is not None:
        params["churn_service"] = int(churn_service.value)
    return Step(
        name=StepName.CUSTOM_STEP,
        description=description
        or (
            f"Concurrently flap {len(gtsws)} GTSW(s) facing "
            f"{neighbor_hosts or neighbor_pattern} for {duration_sec}s"
            + (
                f" + {churn_action} {churn_service.name} every {churn_every_sec}s"
                if churn_service is not None
                else ""
            )
        ),
        step_params=Params(json_params=json.dumps(params)),
    )


def create_fpf_multi_device_drain_step(
    devices: t.List[str],
    drain: bool,
    description: t.Optional[str] = None,
) -> Step:
    """Drain or undrain MULTIPLE devices simultaneously (on-box soft-drain).

    Single CUSTOM_STEP that builds each device's driver and issues the on-box
    device soft-drain (or undrain) across all of them in PARALLEL via
    ``asyncio.gather`` — so e.g. gtsw001 and gtsw005 drain "at the same time"
    rather than the runner's sequential per-device Step fan-out.

    Args:
        devices: device hostnames to drain/undrain.
        drain: True to drain, False to undrain.
        description: Custom step description.
    """
    return Step(
        name=StepName.CUSTOM_STEP,
        description=description
        or f"{'Drain' if drain else 'Undrain'} {len(devices)} device(s): {devices}",
        step_params=Params(
            json_params=json.dumps(
                {
                    "custom_step_name": "fpf_multi_device_drain",
                    "devices": devices,
                    "is_drain": drain,
                }
            )
        ),
    )


def create_fpf_nic_mstreg_flap_step(
    host: str,
    dev: int,
    lane: int,
    iterations: int = 5,
    interval_sec: float = 2.0,
    description: t.Optional[str] = None,
) -> Step:
    """Real NIC-side mstreg PAOS flap of a single beth lane on a GPU host.

    Issues the same admin_status DOWN/UP sequence that
    ``scripts/pavanpatil/fpf_host_signal_test.py --flap-dev/--flap-lane`` runs
    against the GPU NIC. The handler computes the PCIe BDF deterministically
    from ``dev`` + ``lane`` (no ethtool probe), then loops ``iterations`` times,
    each round running

      DOWN: mstreg -d <BDF> --reg_name PAOS \\
              --set "admin_status=2,ase=1,fd=1" -i "local_port=1"
      UP:   mstreg -d <BDF> --reg_name PAOS \\
              --set "admin_status=1,ase=1,fd=1" -i "local_port=1"

    with ``interval_sec`` between the DOWN and the UP (and after the UP before
    the next round). This is a real link-down event on the NIC side (the GTSW
    sees NDP go away on the peer port and withdraws the VF on that lane), so it
    is the genuine trigger for the tc37 NIC-side link-flap test rather than the
    thrift-admin placeholder previously used there.

    The BDF is ``"<DEV_BLOCK>:03:00.<LANE>"`` where ``DEV_BLOCK`` is fixed per
    GPU/dev index (dev0=0000, dev1=0002, dev2=0010, dev3=0012), the middle block
    ``03`` is constant, and the PCIe function ``00.<LANE>`` carries the lane id.
    Example: dev0 lane1 -> ``0000:03:00.1``; dev2 lane7 -> ``0010:03:00.7``.

    The step runs HOST-SIDE, not on a switch DUT: the rtptest GPU hosts are not
    FBOSS devices, are not in ``endpoints`` as DUTs, and have no per-driver SSH
    plumbing in TAAC. So ``device_regexes`` is not set; the handler always SSHes
    to the supplied ``host`` (via the same ``ssh`` CLI + Meta-SSH-CA pattern
    used by ``fpf_ib_traffic_task.async_ssh_run`` — asyncssh-key auth does NOT
    carry the root cert, but the caller's SSH cert/agent does, exactly like
    ``fpf_host_signal_test.py``).

    Args:
        host: GPU host (e.g. ``"rtptest1555.mwg2"``) to flap a beth lane on.
        dev: GPU device index (0..3). Maps to the PCIe DEV_BLOCK.
        lane: Lane within the GPU device (0..7). Maps to the PCIe function.
        iterations: Number of DOWN/UP cycles (default 5).
        interval_sec: Seconds between DOWN and UP, and between successive
            cycles (default 2.0).
        description: Custom step description.
    """
    return Step(
        name=StepName.CUSTOM_STEP,
        description=description
        or (
            f"NIC-side mstreg PAOS flap on {host}: dev={dev} lane={lane}, "
            f"{iterations} iteration(s) every {interval_sec}s"
        ),
        step_params=Params(
            json_params=json.dumps(
                {
                    "custom_step_name": "fpf_nic_mstreg_flap",
                    "host": host,
                    "dev": int(dev),
                    "lane": int(lane),
                    "iterations": int(iterations),
                    "interval_sec": float(interval_sec),
                }
            )
        ),
    )


def create_fpf_restart_ib_traffic_step(
    server: str,
    clients: t.List[str],
    description: t.Optional[str] = None,
) -> Step:
    """Kill + restart the long-lived ``ib_write_bw`` flow on server + clients.

    Host-side CUSTOM_STEP (no switch DUT) that mirrors ``FpfStartIbTrafficTask``:
    it pkills any existing ib_write_bw on every host, restarts the server then
    each client, and confirms the processes are up. Use it at the HEAD of a
    longevity playbook (before the soak) to recover from a flap-wedged per-lane
    QP (e.g. beth0 egress stuck at 0) — a traffic-tooling artifact — so the
    longevity host-spray check observes real egress. The command, GID discovery
    and SSH transport are reused verbatim from the ib-traffic task, so the
    restarted flow is byte-identical to the setup flow.

    Args:
        server: server host (e.g. ``"rtptest1544.mwg2"``).
        clients: client host(s) (non-empty).
        description: Custom step description.
    """
    return Step(
        name=StepName.CUSTOM_STEP,
        description=description
        or f"Restart ib_write_bw: server={server} clients={clients}",
        step_params=Params(
            json_params=json.dumps(
                {
                    "custom_step_name": "fpf_restart_ib_traffic",
                    "server": server,
                    "clients": clients,
                }
            )
        ),
    )


def create_fpf_ensure_traffic_step(
    server: str,
    clients: t.List[str],
    traffic_floor_gbps: t.Optional[float] = None,
    description: t.Optional[str] = None,
) -> Step:
    """STRICT per-playbook traffic precheck (host-side CUSTOM_STEP).

    Verifies all 4 RDMA traffic planes (beth0-3) carry traffic on server+clients
    by sampling ``/sys/class/net/bethN/statistics/tx_bytes`` directly (no ODS).
    If any plane is below the floor it restarts ib_write_bw and re-checks; if a
    plane STILL can't carry traffic it raises (fail fast) — converting a silent
    plane wedge (e.g. the DUT not learning that plane's prefixes) into an early,
    loud failure instead of a contaminated run. Place at the HEAD of each playbook
    stage so every test case starts from verified-healthy traffic.

    Args:
        server: server host (e.g. ``"rtptest1544.mwg2"``).
        clients: client host(s) (non-empty).
        traffic_floor_gbps: per-plane egress floor in Gbps (default 50.0 in the
            handler — catches a dead/0 plane while tolerating normal variation).
        description: Custom step description.
    """
    payload: t.Dict[str, t.Any] = {
        "custom_step_name": "fpf_ensure_traffic",
        "server": server,
        "clients": clients,
    }
    if traffic_floor_gbps is not None:
        payload["traffic_floor_gbps"] = traffic_floor_gbps
    return Step(
        name=StepName.CUSTOM_STEP,
        description=description
        or f"Ensure traffic on all 4 planes: server={server} clients={clients}",
        step_params=Params(json_params=json.dumps(payload)),
    )


def create_fpf_restart_hrt_step(
    hosts: t.List[str],
    description: t.Optional[str] = None,
) -> Step:
    """Restart the HostReachTracker (HRT) service on the GPU/BE host(s).

    Host-side CUSTOM_STEP (no switch DUT) that SSHes to each rtptest BE node and
    runs ``systemctl restart metalos.wds.hostreachtracker``, then confirms the
    unit is ``active``. HRT runs on the GPU host (not a FBOSS switch), so this
    uses the host-SSH transport like the ib-traffic / NIC-flap steps rather than
    the FbossSwitchInternal driver. Pair it with a longevity (settle) step so HRT
    re-subscribes to FSDB and rebuilds its 32 sessions before postchecks run.

    Args:
        hosts: GPU/BE host(s) to restart HRT on (e.g. ``["rtptest1544.mwg2"]``).
        description: Custom step description.
    """
    return Step(
        name=StepName.CUSTOM_STEP,
        description=description or f"Restart HostReachTracker on {hosts}",
        step_params=Params(
            json_params=json.dumps(
                {
                    "custom_step_name": "fpf_restart_hrt",
                    "hosts": hosts,
                }
            )
        ),
    )


def create_fpf_lldp_batched_set_interface_admin_step(
    neighbor_pattern: str,
    enable: bool,
    device_regexes: t.Optional[t.List[str]] = None,
    description: t.Optional[str] = None,
) -> Step:
    """Resolve interfaces from LLDP at runtime, then batch admin-enable/disable.

    Variant of ``create_fpf_set_interface_admin_step`` that defers interface
    selection until step execution: the handler enumerates LLDP neighbors on
    the DUT and matches the remote system name against ``neighbor_pattern``
    (fnmatch shell glob), then issues a SINGLE batched
    ``async_thrift_disable_enable_interfaces`` call over the resolved tuple.

    "Batched" here means ONE open ``async_agent_client`` context with sequential
    per-port ``setPortState`` calls inside it (FBOSS exposes no thrift RPC
    taking a list of port IDs); this is the same primitive used by the
    existing held-admin-down step, so semantics match. Use this for
    tc36-style "shut all neighbor links at once" disruption where the member
    set is testbed-specific and not knowable at config import time.

    Args:
        neighbor_pattern: fnmatch glob matched (case-insensitive) against the
            LLDP remote system name on the DUT (e.g. ``"gtsw001*"``).
        enable: True to enable (no-shut), False to disable (held admin-down).
        device_regexes: Optional device-regex scope (e.g. the DUT STSW).
        description: Custom step description.
    """
    return Step(
        name=StepName.CUSTOM_STEP,
        description=description
        or (
            f"{'Enable' if enable else 'Disable'} ALL LLDP-resolved interfaces "
            f"(neighbors~={neighbor_pattern!r}) in one batched thrift call"
        ),
        step_params=Params(
            json_params=json.dumps(
                {
                    "custom_step_name": "fpf_lldp_batched_set_interface_admin",
                    "neighbor_pattern": neighbor_pattern,
                    "is_enable": enable,
                }
            )
        ),
        device_regexes=device_regexes,
    )


def create_fpf_stsw_drain_and_reinject_steps(
    stsw: str,
    drained: bool,
    trigger_stsws: t.List[str],
    prefix_count: int,
    community_list: str,
    drain_community: t.Optional[str] = None,
) -> t.List[Step]:
    """Drain (or undrain) an STSW plane, then re-inject the FPF prefixes.

    Composition (no new step type): drains/undrains ``stsw`` via the existing
    LOCAL_DRAINER drain/undrain step, then re-injects ``prefix_count`` prefixes
    on ``trigger_stsws`` via ``create_fpf_bgp_prefix_injection_step``. When
    draining, an optional ``drain_community`` is appended to ``community_list`` so
    the re-injected prefixes carry the extra drain-marker community; when
    undraining, the base ``community_list`` is used unchanged.

    Used by the cascaded STSW-plane-drain + GTSW-device-drain FPF configs.

    Args:
        stsw: The STSW device to drain/undrain (LOCAL_DRAINER, device-scoped).
        drained: True to drain, False to undrain.
        trigger_stsws: Devices to (re-)inject prefixes on after the drain action.
        prefix_count: Number of prefixes to inject.
        community_list: Base community list string for the injection.
        drain_community: Optional extra community appended to ``community_list``
            when draining (ignored on undrain).

    Returns:
        Ordered [drain/undrain step, prefix-injection step].
    """
    if drained and drain_community:
        injected_communities = f"{community_list} {drain_community}"
    else:
        injected_communities = community_list

    action = "Drain" if drained else "Undrain"
    return [
        create_drain_undrain_step(
            drain=drained,
            drain_handler=taac_types.DrainHandler.LOCAL_DRAINER,
            description=f"{action} STSW {stsw} (local drainer)",
        ),
        create_fpf_bgp_prefix_injection_step(
            devices=trigger_stsws,
            count=prefix_count,
            community_list=injected_communities,
            description=f"Re-inject {prefix_count} prefixes on "
            f"{', '.join(trigger_stsws)} after {action.lower()} of {stsw}",
        ),
    ]


def create_bgp_lifecycle_convergence_step(
    device_name: str,
    expected_established_sessions: int,
    parent_prefixes_to_ignore: t.Sequence[str],
    convergence_hard_timeout_seconds: float,
    convergence_poll_interval_seconds: float,
    *,
    require_initialized: bool = True,
    convergence_soft_threshold_seconds: float | None = None,
    convergence_trigger_time_jq_var: str | None = None,
    description: str = "Observe exact BGP lifecycle convergence",
) -> Step:
    params: t.Dict[str, t.Any] = {
        "custom_step_name": "test_bgp_lifecycle_convergence",
        "hostname": device_name,
        "expected_established_sessions": expected_established_sessions,
        "parent_prefixes_to_ignore": list(parent_prefixes_to_ignore),
        "require_initialized": require_initialized,
        "convergence_hard_timeout_seconds": convergence_hard_timeout_seconds,
        "convergence_poll_interval_seconds": convergence_poll_interval_seconds,
    }
    if convergence_soft_threshold_seconds is not None:
        params["convergence_soft_threshold_seconds"] = (
            convergence_soft_threshold_seconds
        )
    if convergence_trigger_time_jq_var is not None:
        if not convergence_trigger_time_jq_var:
            raise ValueError("convergence_trigger_time_jq_var must be non-empty")
        return Step(
            name=StepName.CUSTOM_STEP,
            description=description,
            step_params=Params(
                json_params=json.dumps(params),
                jq_params={
                    "convergence_trigger_time_seconds": (
                        f".{convergence_trigger_time_jq_var}"
                    )
                },
            ),
        )
    return create_custom_step(params_dict=params, description=description)


def create_thread_cpu_monitoring_step(
    device_name: str,
    duration_minutes: int,
    thread_cpu_monitoring_interval_seconds: int = 5,
    thread_name_filter: t.Optional[t.List[str]] = None,
    enable_bgp_events: bool = True,
    enable_perf_profiling: bool = False,
    enable_offcpu_profiling: bool = False,
    enable_socket_monitoring: bool = False,
    convergence_soft_threshold_seconds: float | None = None,
    convergence_hard_timeout_seconds: float | None = None,
    convergence_poll_interval_seconds: float | None = None,
    expected_established_sessions: int | None = None,
    parent_prefixes_to_ignore: t.Sequence[str] | None = None,
    convergence_trigger_time_jq_var: str | None = None,
) -> Step:
    """
    Create a BGP++ thread CPU monitoring step.

    Args:
        device_name: Name of the device to monitor
        duration_minutes: Monitoring duration in minutes
        thread_cpu_monitoring_interval_seconds: CPU sampling interval (default: 5s)
        thread_name_filter: List of thread names to monitor (None = top 10 by CPU)
        enable_bgp_events: Enable BGP event tracking (default: True)
        enable_perf_profiling: Enable perf-based profiling (default: False)
        enable_offcpu_profiling: Enable off-CPU profiling (default: False)
        enable_socket_monitoring: Enable socket monitoring (default: False)

    Returns:
        Step object for BGP++ thread CPU monitoring
    """
    convergence_params = (
        convergence_soft_threshold_seconds,
        convergence_hard_timeout_seconds,
        convergence_poll_interval_seconds,
        expected_established_sessions,
    )
    convergence_enabled = any(value is not None for value in convergence_params)
    if convergence_enabled and not all(
        value is not None for value in convergence_params
    ):
        raise ValueError("adaptive convergence parameters must be supplied together")

    params: t.Dict[str, t.Any] = {
        "custom_step_name": "test_bgp_thread_cpu_monitor_eos_bgp_plus_plus",
        "hostname": device_name,
        "duration_minutes": duration_minutes,
        "interval_seconds": thread_cpu_monitoring_interval_seconds,
        "thread_name_filter": thread_name_filter,
        "enable_bgp_events": enable_bgp_events,
        "enable_perf_profiling": enable_perf_profiling,
        "enable_offcpu_profiling": enable_offcpu_profiling,
        "enable_socket_monitoring": enable_socket_monitoring,
    }
    if convergence_enabled:
        params.update(
            {
                "observe_lifecycle_convergence": True,
                "convergence_soft_threshold_seconds": (
                    convergence_soft_threshold_seconds
                ),
                "convergence_hard_timeout_seconds": (convergence_hard_timeout_seconds),
                "convergence_poll_interval_seconds": (
                    convergence_poll_interval_seconds
                ),
                "expected_established_sessions": expected_established_sessions,
                "parent_prefixes_to_ignore": list(parent_prefixes_to_ignore or ()),
                "require_initialized": True,
            }
        )
        if convergence_trigger_time_jq_var is not None:
            params["convergence_trigger_time_jq_var"] = convergence_trigger_time_jq_var

    return Step(
        name=StepName.CUSTOM_STEP,
        description="Monitor BGP++ thread CPU during convergence",
        step_params=Params(json_params=json.dumps(params)),
    )


def create_run_task_step(
    task_name: str,
    params_dict: t.Dict[str, t.Any],
    description: t.Optional[str] = None,
    ixia_needed: bool = False,
) -> Step:
    """
    Create a generic step to run a task.

    Args:
        task_name: Name of the task to run
        params_dict: Parameters to pass to the task
        description: Custom description for the step
        ixia_needed: Whether the task requires Ixia

    Returns:
        Step object for running the task
    """
    if description is None:
        description = f"Run task: {task_name}"

    from taac.task_definitions import create_run_task

    return Step(
        name=StepName.RUN_TASK_STEP,
        description=description,
        input_json=thrift_to_json(
            RunTaskInput(
                task=create_run_task(
                    task_name=task_name,
                    params_dict=params_dict,
                    ixia_needed=ixia_needed,
                )
            )
        ),
    )


def create_ixia_api_step(
    api_name: str,
    args_dict: t.Dict[str, t.Any],
    description: t.Optional[str] = None,
) -> Step:
    """
    Create an Ixia API step.

    Args:
        api_name: Name of the Ixia API to call
        args_dict: Arguments to pass to the API
        description: Custom description for the step

    Returns:
        Step object for Ixia API call
    """
    if description is None:
        description = f"Call Ixia API: {api_name}"

    return Step(
        name=StepName.INVOKE_IXIA_API_STEP,
        description=description,
        step_params=Params(
            json_params=json.dumps(
                {
                    "api_name": api_name,
                    "args_json": json.dumps(args_dict),
                }
            )
        ),
    )


def create_ixia_device_group_toggle_step(
    enable: bool,
    device_group_name_regex: str,
    description: t.Optional[str] = None,
    require_match: bool = False,
    verify_readback: bool = False,
) -> Step:
    """
    Create a step to enable or disable IXIA device groups.

    Args:
        enable: True to enable device groups, False to disable
        device_group_name_regex: Regex pattern to match device group names
        description: Custom description for the step
        require_match: Fail when the regex selects no device groups
        verify_readback: Re-read and verify every selected group's Enabled value

    Returns:
        Step object for IXIA device group toggle
    """
    if description is None:
        action = "Enable" if enable else "Disable"
        description = (
            f"{action} IXIA device groups matching '{device_group_name_regex}'"
        )
    args_dict: t.Dict[str, t.Any] = {
        "enable": enable,
        "device_group_name_regex": device_group_name_regex,
    }
    if require_match:
        args_dict["require_match"] = True
    if verify_readback:
        args_dict["verify_readback"] = True
    return create_ixia_api_step(
        api_name="toggle_device_groups",
        args_dict=args_dict,
        description=description,
    )


def create_daemon_control_step(
    device_name: str,
    daemon_name: str = "Bgp",
    action: str = "enable",
    description: t.Optional[str] = None,
) -> Step:
    """
    Create a step to control daemon on a device.

    Args:
        device_name: Name of the device
        daemon_name: Name of the daemon to control
        action: Action to perform ("enable", "disable", "restart")
        description: Custom description for the step

    Returns:
        Step object for daemon control
    """
    if description is None:
        description = f"{action.title()} {daemon_name} daemon on {device_name}"

    return create_run_task_step(
        task_name="arista_daemon_control",
        params_dict={
            "hostname": device_name,
            "daemon_name": daemon_name,
            "action": action,
        },
        description=description,
    )


def create_run_ssh_command_step(
    cmd: str,
    description: t.Optional[str] = None,
    step_id: t.Optional[str] = None,
) -> Step:
    """Run an arbitrary shell command on the DUT via SSH.

    Used in playbooks when no purpose-built step exists for the operation
    (e.g. ad-hoc CLI invocations, bespoke scripts, or commands that have
    not been wrapped in a typed step). The command runs against the
    primary device under test using the standard SSH driver; stdout/stderr
    is captured into test logs but no parsing is performed.

    Args:
        cmd: Shell command string to execute on the DUT.
        description: Optional human-readable description shown in test
            logs. If omitted, no description is rendered.
        step_id: Optional step id, used by downstream stages to reference
            this step's output via jq.

    Returns:
        A `Step` with `step_name=StepName.RUN_SSH_COMMAND_STEP`.
    """
    return Step(
        name=StepName.RUN_SSH_COMMAND_STEP,
        step_params=Params(json_params=json.dumps({"cmd": cmd})),
        description=description,
        id=step_id,
    )


def create_longevity_step(
    duration: int,
    description: t.Optional[str] = None,
    step_id: t.Optional[str] = None,
) -> Step:
    """
    Create a longevity step that waits for a specified duration.

    Args:
        duration: Duration in seconds to wait
        description: Custom description for the step
        step_id: Optional step ID

    Returns:
        Step object for longevity/wait
    """
    params_dict: t.Dict[str, t.Any] = {"duration": duration}
    if description:
        params_dict["description"] = description
    return Step(
        name=StepName.LONGEVITY_STEP,
        step_params=Params(json_params=json.dumps(params_dict)),
        description=description,
        id=step_id,
    )


def create_service_interruption_step(
    service: taac_types.Service,
    trigger: taac_types.ServiceInterruptionTrigger = taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
    create_cold_boot_file: bool = False,
    description: t.Optional[str] = None,
    step_id: t.Optional[str] = None,
    device_regexes: t.Optional[t.List[str]] = None,
) -> Step:
    """
    Create a step to interrupt a service (restart, crash, etc.).

    Args:
        service: The service to interrupt (e.g., Service.AGENT, Service.BGP)
        trigger: The trigger type (SYSTEMCTL_RESTART, CRASH, etc.)
        create_cold_boot_file: Whether to create a cold boot file
        description: Custom description for the step
        step_id: Optional step ID

    Returns:
        Step object for service interruption
    """
    input_obj = taac_types.ServiceInterruptionInput(
        name=service,
        trigger=trigger,
        create_cold_boot_file=create_cold_boot_file,
    )

    return Step(
        name=StepName.SERVICE_INTERRUPTION_STEP,
        input_json=thrift_to_json(input_obj),
        description=description,
        id=step_id,
        device_regexes=device_regexes,
    )


def create_service_convergence_step(
    services: t.Optional[t.List[taac_types.Service]] = None,
    description: t.Optional[str] = None,
    timeout: t.Optional[int] = None,
    service_convergence_timeout: t.Optional[t.Dict[taac_types.Service, int]] = None,
    step_id: t.Optional[str] = None,
    device_regexes: t.Optional[t.List[str]] = None,
) -> Step:
    """
    Create a step to wait for service convergence.

    Args:
        services: List of services to wait for convergence (default: [AGENT])
        description: Custom description for the step
        timeout: Optional timeout in seconds for convergence (simple timeout)
        service_convergence_timeout: Optional dict mapping services to their timeout values
        step_id: Optional step ID

    Returns:
        Step object for service convergence
    """
    if services is None:
        services = [taac_types.Service.AGENT]

    if service_convergence_timeout is not None:
        convergence_input = taac_types.ServiceConvergenceInput(
            services=services, service_convergence_timeout=service_convergence_timeout
        )
    elif timeout is not None:
        convergence_input = taac_types.ServiceConvergenceInput(
            services=services, timeout=timeout
        )
    else:
        convergence_input = taac_types.ServiceConvergenceInput(services=services)

    return Step(
        name=StepName.SERVICE_CONVERGENCE_STEP,
        input_json=thrift_to_json(convergence_input),
        description=description,
        id=step_id,
        device_regexes=device_regexes,
    )


def create_interface_flap_step(
    enable: bool,
    interfaces: t.Optional[t.Union[str, t.List[str]]] = None,
    description: t.Optional[str] = None,
    jq_params: t.Optional[t.Dict[str, str]] = None,
    cache_params: t.Optional[t.Dict[str, str]] = None,
    transform_params: t.Optional[t.Dict[str, t.Any]] = None,
    interface_flap_method: t.Optional[int] = None,
    delay: t.Optional[int] = None,
    device_name: t.Optional[str] = None,
    step_id: t.Optional[str] = None,
) -> Step:
    """
    Create a step to enable or disable interfaces.

    Args:
        enable: True to enable interfaces, False to disable
        interfaces: Interface name(s) or jq expression (optional if using jq_params)
        description: Custom description for the step
        jq_params: Optional jq parameters for dynamic interface resolution
        cache_params: Optional cache parameters
        transform_params: Optional transform parameters for interface selection
        interface_flap_method: Optional interface flap method (e.g., 1 for thrift API, 4 for SSH)
        delay: Optional delay between interface operations in seconds
        device_name: Optional device name for the interface flap (used with SSH method)
        step_id: Optional step ID

    Returns:
        Step object for interface flap
    """
    params_dict: t.Dict[str, t.Any] = {"enable": enable}
    if interfaces is not None:
        params_dict["interfaces"] = interfaces
    if interface_flap_method is not None:
        params_dict["interface_flap_method"] = interface_flap_method
    if delay is not None:
        params_dict["delay"] = delay
    if device_name is not None:
        params_dict["device_name"] = device_name

    params = Params(
        json_params=json.dumps(params_dict),
        jq_params=jq_params,
        cache_params=cache_params,
        transform_params=transform_params,
    )

    return Step(
        name=StepName.INTERFACE_FLAP_STEP,
        step_params=params,
        description=description,
        id=step_id,
    )


def create_system_reboot_step(
    trigger: taac_types.SystemRebootTrigger,
    description: t.Optional[str] = None,
) -> Step:
    """
    Create a step to reboot the system.

    Args:
        trigger: The reboot trigger type (FULL_SYSTEM_REBOOT, BMC_POWER_RESET, etc.)
        description: Custom description for the step

    Returns:
        Step object for system reboot
    """
    return Step(
        name=StepName.SYSTEM_REBOOT_STEP,
        input_json=thrift_to_json(taac_types.SystemRebootInput(trigger=trigger)),
        description=description,
    )


def create_validation_step(
    point_in_time_checks: t.List[taac_types.PointInTimeHealthCheck],
    stage: taac_types.ValidationStage = taac_types.ValidationStage.MID_TEST,
    description: t.Optional[str] = None,
) -> Step:
    """
    Create a validation step with point-in-time health checks.

    Args:
        point_in_time_checks: List of health checks to perform
        stage: Validation stage (PRE_TEST, MID_TEST, POST_TEST)
        description: Custom description for the step

    Returns:
        Step object for validation
    """
    return Step(
        name=StepName.VALIDATION_STEP,
        input_json=thrift_to_json(
            taac_types.ValidationInput(
                point_in_time_checks=point_in_time_checks,
                stage=stage,
            )
        ),
        description=description,
    )


def create_verify_port_operational_state_step(
    interfaces: t.List[str],
    operational_state: bool,
    description: t.Optional[str] = None,
) -> Step:
    """
    Create a step to verify port operational state.

    Args:
        interfaces: List of interface names to verify
        operational_state: Expected operational state (True=up, False=down)
        description: Custom description for the step

    Returns:
        Step object for port state verification
    """
    return Step(
        name=StepName.VERIFY_PORT_OPERATIONAL_STATE,
        step_params=Params(
            json_params=json.dumps(
                {
                    "interfaces": interfaces,
                    "operational_state": operational_state,
                }
            )
        ),
        description=description,
    )


def create_toggle_ixia_prefix_session_flap_churn_step(
    churn_mode: str,
    churn_duration_s: int,
    enable_prefix_flap: t.Optional[bool] = None,
    enable_session_flap: t.Optional[bool] = None,
    is_all_prefix_groups: t.Optional[bool] = None,
    is_all_session_groups: t.Optional[bool] = None,
    prefix_flap_tag_names: t.Optional[t.List[str]] = None,
    session_flap_tag_names: t.Optional[t.List[str]] = None,
    description: t.Optional[str] = None,
) -> Step:
    """
    Create a TOGGLE_IXIA_PREFIX_SESSION_FLAP step with the churn_mode shape
    used by routing/dc_routing/bgp_dc/common.py sequences.

    Builds json_params with only the kwargs explicitly set (omits None values
    to preserve byte-equivalence with hand-written sequences).
    """
    payload: t.Dict[str, t.Any] = {"churn_mode": churn_mode}
    if enable_prefix_flap is not None:
        payload["enable_prefix_flap"] = enable_prefix_flap
    if enable_session_flap is not None:
        payload["enable_session_flap"] = enable_session_flap
    if is_all_prefix_groups is not None:
        payload["is_all_prefix_groups"] = is_all_prefix_groups
    if is_all_session_groups is not None:
        payload["is_all_session_groups"] = is_all_session_groups
    if prefix_flap_tag_names is not None:
        payload["prefix_flap_tag_names"] = prefix_flap_tag_names
    if session_flap_tag_names is not None:
        payload["session_flap_tag_names"] = session_flap_tag_names
    payload["churn_duration_s"] = churn_duration_s
    return Step(
        name=StepName.TOGGLE_IXIA_PREFIX_SESSION_FLAP,
        step_params=Params(json_params=json.dumps(payload)),
        description=description,
    )


def create_toggle_ixia_prefix_session_flap_step(
    bgp_peer_group_name_regex: str,
    stable_state_duration_hours: float,
    prefix_flapping_duration_hours: t.Optional[float] = None,
    network_group_name_regex: t.Optional[str] = None,
    description: t.Optional[str] = None,
) -> Step:
    """
    Create a step to toggle IXIA BGP prefix/session flapping.

    Args:
        bgp_peer_group_name_regex: Regex to match BGP peer group names
        stable_state_duration_hours: Duration of stable state in hours
        prefix_flapping_duration_hours: Duration of flapping in hours (variant 1)
        network_group_name_regex: Regex for network groups (variant 2 — used by hardening conveyor)
        description: Custom description for the step
    """
    payload: t.Dict[str, t.Any] = {
        "bgp_peer_group_name_regex": bgp_peer_group_name_regex,
    }
    if network_group_name_regex is not None:
        payload["network_group_name_regex"] = network_group_name_regex
    if prefix_flapping_duration_hours is not None:
        payload["prefix_flapping_duration_hours"] = prefix_flapping_duration_hours
    payload["stable_state_duration_hours"] = stable_state_duration_hours
    return Step(
        name=StepName.TOGGLE_IXIA_PREFIX_SESSION_FLAP,
        step_params=Params(json_params=json.dumps(payload)),
        description=description,
    )


def create_mass_bgp_peer_toggle_step(
    device_group_name_regex: str,
    total_step_time_hours: float,
    peer_toggle_duration_hours: t.Optional[float] = None,
    toggle_time_interval_s: t.Optional[int] = None,
    description: t.Optional[str] = None,
) -> Step:
    """
    Create a step for mass BGP peer toggling.

    Args:
        device_group_name_regex: Regex to match device group names
        total_step_time_hours: Total step time in hours
        peer_toggle_duration_hours: Duration of peer toggle in hours (variant 1)
        toggle_time_interval_s: Toggle interval in seconds (variant 2 — used by hardening conveyor)
        description: Custom description for the step
    """
    payload: t.Dict[str, t.Any] = {
        "device_group_name_regex": device_group_name_regex,
    }
    if toggle_time_interval_s is not None:
        payload["toggle_time_interval_s"] = toggle_time_interval_s
    if peer_toggle_duration_hours is not None:
        payload["peer_toggle_duration_hours"] = peer_toggle_duration_hours
    payload["total_step_time_hours"] = total_step_time_hours
    return Step(
        name=StepName.MASS_BGP_PEER_TOGGLE,
        step_params=Params(json_params=json.dumps(payload)),
        description=description,
    )


def create_allocate_cgroup_memory_step(
    total_memory_pct_decimal: float,
    cgroup_slice_name: t.Optional[str] = None,
    cgroup_unit_name: t.Optional[str] = None,
    oom_score_adj: int = 1000,
    description: t.Optional[str] = None,
    slice_name: t.Optional[str] = None,
    duration: t.Optional[int] = None,
    minimum_memory_allocation: t.Optional[int] = None,
) -> Step:
    """
    Create a step to allocate cgroup slice memory.

    Args:
        total_memory_pct_decimal: Memory percentage as decimal (e.g., 0.25 for 25%)
        cgroup_slice_name: Name of the cgroup slice (variant 1)
        cgroup_unit_name: Name of the cgroup unit (variant 1)
        oom_score_adj: OOM score adjustment value
        slice_name: Alternative slice name kwarg (variant 2 — used by hardening conveyor)
        duration: Optional duration in seconds (variant 2)
        minimum_memory_allocation: Optional minimum memory bytes (variant 2)
        description: Custom description for the step
    """
    payload: t.Dict[str, t.Any] = {
        "total_memory_pct_decimal": total_memory_pct_decimal,
    }
    if slice_name is not None:
        payload["slice_name"] = slice_name
    if duration is not None:
        payload["duration"] = duration
    if minimum_memory_allocation is not None:
        payload["minimum_memory_allocation"] = minimum_memory_allocation
    if cgroup_slice_name is not None:
        payload["cgroup_slice_name"] = cgroup_slice_name
    if cgroup_unit_name is not None:
        payload["cgroup_unit_name"] = cgroup_unit_name
    payload["oom_score_adj"] = oom_score_adj
    return Step(
        name=StepName.ALLOCATE_CGROUP_SLICE_MEMORY_STEP,
        step_params=Params(json_params=json.dumps(payload)),
        description=description,
    )


def create_ecmp_member_static_route_step(
    max_ecmp_group: t.Optional[int] = None,
    max_ecmp_members: t.Optional[int] = None,
    nh_prefix_1: t.Optional[str] = None,
    lb_prefix_agg: t.Optional[str] = None,
    device_group_count: t.Optional[int] = None,
    delete_patcher_and_exit_step: bool = False,
    description: t.Optional[str] = None,
) -> Step:
    """
    Create a step for ECMP member static route configuration.

    Args:
        max_ecmp_group: Maximum ECMP group size
        max_ecmp_members: Maximum ECMP members per group
        nh_prefix_1: Next-hop prefix
        lb_prefix_agg: Load-balanced prefix aggregate
        device_group_count: Number of device groups
        delete_patcher_and_exit_step: Whether to delete patcher and exit
        description: Custom description for the step
    """
    params_dict: t.Dict[str, t.Any] = {}
    if max_ecmp_group is not None:
        params_dict["max_ecmp_group"] = max_ecmp_group
    if max_ecmp_members is not None:
        params_dict["max_ecmp_members"] = max_ecmp_members
    if nh_prefix_1 is not None:
        params_dict["nh_prefix_1"] = nh_prefix_1
    if lb_prefix_agg is not None:
        params_dict["lb_prefix_agg"] = lb_prefix_agg
    if device_group_count is not None:
        params_dict["device_group_count"] = device_group_count
    params_dict["delete_patcher_and_exit_step"] = delete_patcher_and_exit_step

    return Step(
        name=StepName.ECMP_MEMBER_STATIC_ROUTE,
        step_params=Params(json_params=json.dumps(params_dict)),
        description=description,
    )


def create_service_restart_steps(
    service: taac_types.Service,
    convergence_services: t.Optional[t.List[taac_types.Service]] = None,
) -> t.List[Step]:
    """
    Create a list of steps to restart a service and wait for convergence.

    Args:
        service: The service to restart
        convergence_services: Services to wait for convergence (default: [AGENT, BGP])

    Returns:
        List of Step objects for service restart and convergence
    """
    if convergence_services is None:
        convergence_services = [taac_types.Service.AGENT, taac_types.Service.BGP]

    return [
        create_service_interruption_step(
            service=service,
            trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
        ),
        create_service_convergence_step(services=convergence_services),
    ]


def create_drain_undrain_step(
    drain: bool,
    drain_handler: t.Optional[taac_types.DrainHandler] = None,
    interfaces: t.Optional[t.List[str]] = None,
    description: t.Optional[str] = None,
) -> Step:
    """
    Create a step to drain or undrain a device, or specific interfaces.

    Args:
        drain: True to drain, False to undrain
        drain_handler: Optional drain handler (e.g., LOCAL_DRAINER)
        interfaces: Optional list of interface names to scope the drain to
            specific links instead of the whole device. With LOCAL_DRAINER each
            interface is soft-drained on-box (BGP depreference, data plane stays
            up); with NDS the interface list is passed through to the NDS drain.
            When omitted, the whole device is drained.
        description: Custom description for the step

    Returns:
        Step object for drain/undrain operation
    """
    input_kwargs: t.Dict[str, t.Any] = {"drain": drain}
    if drain_handler is not None:
        input_kwargs["drain_handler"] = drain_handler

    step_params = None
    if interfaces:
        step_params = Params(json_params=json.dumps({"interfaces": interfaces}))

    return Step(
        name=StepName.DRAIN_UNDRAIN_STEP,
        description=description,
        input_json=thrift_to_json(taac_types.DrainUndrainInput(**input_kwargs)),
        step_params=step_params,
    )


def create_module_power_toggle_step(
    modules: t.List[str],
    enable: bool,
    sequential: bool = False,
    description: t.Optional[str] = None,
) -> Step:
    """
    Create a step to toggle module power on/off.

    Args:
        modules: List of module names to toggle
        enable: True to enable (power on), False to disable (power off)
        sequential: Whether to toggle modules sequentially
        description: Custom description for the step

    Returns:
        Step object for module power toggle
    """
    return Step(
        name=StepName.MODULE_POWER_TOGGLE_STEP,
        step_params=Params(
            json_params=json.dumps(
                {
                    "modules": modules,
                    "enable": enable,
                    "sequential": sequential,
                }
            )
        ),
        description=description,
    )


def create_arista_custom_agents_service_interruption_step(
    agents: t.List[str],
    trigger: taac_types.ServiceInterruptionTrigger,
    description: t.Optional[str] = None,
) -> Step:
    """
    Create a step to interrupt Arista custom agents.

    Args:
        agents: List of agent names to interrupt
        trigger: The trigger type (SYSTEMCTL_RESTART, CRASH, etc.)
        description: Custom description for the step

    Returns:
        Step object for service interruption of Arista custom agents
    """
    input_obj = taac_types.ServiceInterruptionInput(
        name=taac_types.Service.ARISTA_CUSTOM_AGENTS,
        trigger=trigger,
        agents=agents,
    )

    return Step(
        name=StepName.SERVICE_INTERRUPTION_STEP,
        input_json=thrift_to_json(input_obj),
        description=description,
    )


def create_verify_port_speed_step_v2(
    ports: t.List[str],
    speed_to_verify: int,
    description: t.Optional[str] = None,
) -> Step:
    """
    Create a step to verify port speed.

    Args:
        ports: List of port names to verify
        speed_to_verify: Expected speed in Gbps
        description: Custom description for the step

    Returns:
        Step object for port speed verification
    """
    return Step(
        name=StepName.VERIFY_PORT_SPEED,
        step_params=Params(
            json_params=json.dumps(
                {
                    "ports": ports,
                    "speed_to_verify": speed_to_verify,
                }
            )
        ),
        description=description,
    )


def create_register_speed_flip_patcher_step(
    register_patcher: bool,
    port_state_change: t.Any,
    patcher_name: str,
    endpoints: t.Any,
    speed_in_gbps: int,
    description: t.Optional[str] = None,
    target_port_cage_count: int = 4,
) -> Step:
    """
    Create a step to register/unregister speed flip patcher (v3 shape used by speed_flip_test_configs).

    Args:
        register_patcher: True to register, False to unregister
        port_state_change: Port state change descriptor
        patcher_name: Name of the patcher
        endpoints: List of endpoints
        speed_in_gbps: Target speed in Gbps
        description: Custom description for the step
        target_port_cage_count: Minimum number of distinct dual-cage ports that
            must be supplied per device in ``endpoints``. Enforced at test
            runtime (see ``RegisterSpeedFlipPatcherStep.run``). The onus is on
            the POC configuring/running the test to supply at least this many
            cages per device; defaults to 4.
    """
    return Step(
        name=StepName.REGISTER_SPEED_FLIP_PATCHER,
        step_params=Params(
            json_params=json.dumps(
                {
                    "register_patcher": register_patcher,
                    "port_state_change": port_state_change,
                    "patcher_name": patcher_name,
                    "endpoints": endpoints,
                    "speed_in_gbps": speed_in_gbps,
                    "target_port_cage_count": target_port_cage_count,
                }
            )
        ),
        description=description,
    )


def create_register_speed_flip_patcher_step_v2(
    ports: t.List[str],
    apply_patcher_method: t.Any,
    register_patcher: bool,
    speed_in_gbps: t.Optional[int] = None,
    description: t.Optional[str] = None,
) -> Step:
    """
    Create a step to register/unregister speed flip patcher.

    Args:
        ports: List of port names for speed flip
        apply_patcher_method: Method to apply patcher (enum value)
        register_patcher: True to register, False to unregister
        speed_in_gbps: Target speed in Gbps (required when registering)
        description: Custom description for the step

    Returns:
        Step object for speed flip patcher registration
    """
    params_dict: t.Dict[str, t.Any] = {
        "ports": ports,
        "apply_patcher_method": apply_patcher_method,
        "register_patcher": register_patcher,
    }
    if speed_in_gbps is not None:
        params_dict["speed_in_gbps"] = speed_in_gbps

    return Step(
        name=StepName.REGISTER_SPEED_FLIP_PATCHER,
        step_params=Params(json_params=json.dumps(params_dict)),
        description=description,
    )


def create_prefix_flap_step(
    enable: bool,
    tag_names: t.Optional[t.List[str]] = None,
    is_all_groups: bool = False,
    duration_s: int = 30,
    uptime_range: t.Optional[t.Tuple[int, int]] = None,
    downtime_range: t.Optional[t.Tuple[int, int]] = None,
    rerandomize_interval_s: int = 0,
    description: t.Optional[str] = None,
) -> Step:
    """
    Create a step to enable or disable IXIA prefix flapping.

    Args:
        enable: True to start prefix flaps, False to stop
        tag_names: Device group tag names to target (e.g. ["CONTROL"]).
            Required when enable=True.
        is_all_groups: If True, target all prefix groups (used when disabling)
        duration_s: Duration of the churn operation in seconds
        uptime_range: (min, max) seconds for randomized uptime (default: (15, 15))
        downtime_range: (min, max) seconds for randomized downtime (default: (15, 15))
        rerandomize_interval_s: Re-randomize flap timing every N seconds
            during the churn duration. 0 means no re-randomization.
        description: Custom description for the step

    Returns:
        Step object for prefix flap toggle
    """
    params: t.Dict[str, t.Any] = {
        "churn_mode": "prefix_flap",
        "enable_prefix_flap": enable,
        "churn_duration_s": duration_s,
    }
    if tag_names is not None:
        params["prefix_flap_tag_names"] = tag_names
    if is_all_groups:
        params["is_all_prefix_groups"] = True
    if uptime_range is not None:
        params["uptime_min_sec"] = uptime_range[0]
        params["uptime_max_sec"] = uptime_range[1]
    if downtime_range is not None:
        params["downtime_min_sec"] = downtime_range[0]
        params["downtime_max_sec"] = downtime_range[1]
    if rerandomize_interval_s > 0:
        params["rerandomize_interval_s"] = rerandomize_interval_s

    return Step(
        name=StepName.TOGGLE_IXIA_PREFIX_SESSION_FLAP,
        step_params=Params(json_params=json.dumps(params)),
        description=description,
    )


def create_session_flap_step(
    enable: bool,
    tag_names: t.Optional[t.List[str]] = None,
    is_all_groups: bool = False,
    duration_s: int = 30,
    uptime_range: t.Optional[t.Tuple[int, int]] = None,
    downtime_range: t.Optional[t.Tuple[int, int]] = None,
    rerandomize_interval_s: int = 0,
    description: t.Optional[str] = None,
) -> Step:
    """
    Create a step to enable or disable IXIA session flapping.

    Args:
        enable: True to start session flaps, False to stop
        tag_names: Device group tag names to target (e.g. ["CONTROL"]).
            Required when enable=True.
        is_all_groups: If True, target all session groups (used when disabling)
        duration_s: Duration of the churn operation in seconds
        uptime_range: (min, max) seconds for randomized uptime (default: (15, 15))
        downtime_range: (min, max) seconds for randomized downtime (default: (15, 15))
        rerandomize_interval_s: Re-randomize flap timing every N seconds
            during the churn duration. 0 means no re-randomization.
        description: Custom description for the step

    Returns:
        Step object for session flap toggle
    """
    params: t.Dict[str, t.Any] = {
        "churn_mode": "session_flap",
        "enable_session_flap": enable,
        "churn_duration_s": duration_s,
    }
    if tag_names is not None:
        params["session_flap_tag_names"] = tag_names
    if is_all_groups:
        params["is_all_session_groups"] = True
    if uptime_range is not None:
        params["uptime_min_sec"] = uptime_range[0]
        params["uptime_max_sec"] = uptime_range[1]
    if downtime_range is not None:
        params["downtime_min_sec"] = downtime_range[0]
        params["downtime_max_sec"] = downtime_range[1]
    if rerandomize_interval_s > 0:
        params["rerandomize_interval_s"] = rerandomize_interval_s

    return Step(
        name=StepName.TOGGLE_IXIA_PREFIX_SESSION_FLAP,
        step_params=Params(json_params=json.dumps(params)),
        description=description,
    )


def create_combined_flap_step(
    enable: bool,
    tag_names: t.Optional[t.List[str]] = None,
    is_all_groups: bool = False,
    duration_s: int = 30,
    uptime_range: t.Optional[t.Tuple[int, int]] = None,
    downtime_range: t.Optional[t.Tuple[int, int]] = None,
    rerandomize_interval_s: int = 0,
    description: t.Optional[str] = None,
) -> Step:
    """
    Create a step to enable or disable both IXIA prefix and session flapping.

    Args:
        enable: True to start flaps, False to stop
        tag_names: Device group tag names to target (e.g. ["EXPERIMENT"]).
        is_all_groups: If True, target all groups (used when disabling)
        duration_s: Duration of the churn operation in seconds
        uptime_range: (min, max) seconds for randomized uptime (default: (15, 15))
        downtime_range: (min, max) seconds for randomized downtime (default: (15, 15))
        rerandomize_interval_s: Re-randomize flap timing every N seconds
            during the churn duration. 0 means no re-randomization.
        description: Custom description for the step

    Returns:
        Step object for combined prefix+session flap toggle
    """
    params: t.Dict[str, t.Any] = {
        "churn_mode": "prefix_session_flap",
        "enable_prefix_flap": enable,
        "enable_session_flap": enable,
        "churn_duration_s": duration_s,
    }
    if tag_names is not None:
        params["prefix_flap_tag_names"] = tag_names
        params["session_flap_tag_names"] = tag_names
    if is_all_groups:
        params["is_all_prefix_groups"] = True
        params["is_all_session_groups"] = True
    if uptime_range is not None:
        params["uptime_min_sec"] = uptime_range[0]
        params["uptime_max_sec"] = uptime_range[1]
    if downtime_range is not None:
        params["downtime_min_sec"] = downtime_range[0]
        params["downtime_max_sec"] = downtime_range[1]
    if rerandomize_interval_s > 0:
        params["rerandomize_interval_s"] = rerandomize_interval_s

    return Step(
        name=StepName.TOGGLE_IXIA_PREFIX_SESSION_FLAP,
        step_params=Params(json_params=json.dumps(params)),
        description=description,
    )


def create_register_port_channel_min_link_percentage_patcher_step(
    port_channel_name: str,
    min_link_percentage: t.Optional[t.Union[int, float]] = None,
    min_link_up_percentage: t.Optional[t.Union[int, float]] = None,
    patcher_name: t.Optional[str] = None,
    description: t.Optional[str] = "Register port channel min link percentage patcher",
    register_patchers: bool = True,
) -> Step:
    """
    Create a step to register or unregister the port channel min link percentage patcher.
    Args:
        register_patcher: True to register the patcher, False to unregister it
        port_channel_name: Name of the port channel to configure
        min_link_percentage: Minimum link capacity percentage to set
        min_link_up_percentage: Minimum link up percentage to set (optional)
        description: Custom description for the step
        patcher_name: Name of the patcher to register (optional)
    """
    params_dict: t.Dict[str, t.Any] = {
        "port_channel_name": port_channel_name,
    }
    if min_link_percentage is not None:
        params_dict["min_link_percentage"] = min_link_percentage
    if not register_patchers:
        params_dict["register_patchers"] = register_patchers
    if min_link_up_percentage is not None:
        params_dict["min_link_up_percentage"] = min_link_up_percentage
    if patcher_name is not None:
        params_dict["patcher_name"] = patcher_name
    if description is not None:
        params_dict["description"] = description

    return Step(
        name=StepName.REGISTER_PORT_CHANNEL_MIN_LINK_PERCENTAGE_PATCHERS,
        step_params=Params(
            json_params=json.dumps(params_dict),
        ),
        description=description,
    )


def create_modify_bgp_prefixes_origin_value_step(
    prefix_pool_regex: str,
    prefix_start_index: int,
    origin_value: t.Optional[str] = None,
    prefix_end_index: t.Optional[int] = None,
    description: t.Optional[str] = None,
    origin_values: t.Optional[t.List[str]] = None,
) -> Step:
    """Create a step to modify BGP prefix origin value.

    Supply either ``origin_value`` (scalar, applied uniformly) OR
    ``origin_values`` (list, cycled per-slot for spec-loyal per-prefix
    variety). ``origin_values`` takes precedence when both are set.

    Args:
        prefix_pool_regex: Regex pattern to match prefix pool names
        prefix_start_index: Starting index for prefix modification
        origin_value: Single origin value to broadcast (e.g., "igp")
        prefix_end_index: Ending index for prefix modification (optional)
        description: Custom description for the step
        origin_values: List of origin values to cycle per-slot (e.g.,
            ``["igp", "egp", "incomplete"]``). Enables spec 2.3.x
            "random Origin per route" without touching the thrift enum.

    Returns:
        Step object for BGP prefix origin value modification
    """
    if description is None:
        description = (
            f"Modify BGP prefix origin value on pool regex {prefix_pool_regex}"
        )
    params_dict: t.Dict[str, t.Any] = {
        "prefix_pool_regex": prefix_pool_regex,
        "prefix_start_index": prefix_start_index,
    }
    if origin_values:
        params_dict["origin_values"] = list(origin_values)
    else:
        params_dict["origin_value"] = origin_value or "igp"

    if prefix_end_index is not None:
        params_dict["prefix_end_index"] = prefix_end_index

    return create_run_task_step(
        task_name="ixia_modify_bgp_prefixes_origin_value",
        params_dict=params_dict,
        description=description,
        ixia_needed=True,
    )


def create_bgp_prefixes_med_value_step(
    prefix_pool_regex: str,
    prefix_start_index: int,
    prefix_end_index: t.Optional[int] = None,
    med_value: int = -1,
    description: t.Optional[str] = None,
) -> Step:
    """
    Create a step to modify BGP prefix MED value.

    Args:
        prefix_pool_regex: Regex pattern to match prefix pool names
        prefix_start_index: Starting index for prefix modification
        prefix_end_index: Ending index for prefix modification (optional)
        med_value: MED value to set (default: -1)
        description: Custom description for the step

    Returns:
        Step object for BGP prefix MED value modification
    """
    if description is None:
        description = f"Modify BGP prefix MED value on pool regex {prefix_pool_regex}"
    params_dict: t.Dict[str, t.Any] = {
        "prefix_pool_regex": prefix_pool_regex,
        "prefix_start_index": prefix_start_index,
        "med_value": med_value,
    }

    if prefix_end_index is not None:
        params_dict["prefix_end_index"] = prefix_end_index

    return create_run_task_step(
        task_name="ixia_modify_bgp_prefixes_med_value",
        params_dict=params_dict,
        description=description,
        ixia_needed=True,
    )


def create_change_as_path_length_step(
    prefix_pool_regex: str,
    as_path_length: int = 1,
    description: t.Optional[str] = None,
) -> Step:
    """
    Create a step to modify the AS_PATH attribute by changing its length.

    Args:
        prefix_pool_regex: Regex pattern to match prefix pool names
        as_path_length: as path length
        description: Custom step description (optional)

    Returns:
        Step object for AS_PATH modification
    """

    if description is None:
        description = f"AS Segment length change on pool regex {prefix_pool_regex} to {as_path_length}"

    params_dict: t.Dict[str, t.Any] = {
        "prefix_pool_regex": prefix_pool_regex,
        "as_path_length": as_path_length,
    }

    return create_run_task_step(
        task_name="ixia_change_as_path_length",
        params_dict=params_dict,
        description=description,
        ixia_needed=True,
    )


def create_configure_bgp_peer_tcp_window_size_step(
    hostname: str,
    interface: str,
    device_group_regex: str,
    tcp_window_size_bytes: int,
    description: t.Optional[str] = None,
) -> Step:
    """Reduce TCP receive window on all Ethernet stacks in DGs matching
    ``device_group_regex`` to induce DUT adj-RIB-out backpressure on the
    slow-peer subset (spec 2.3.1 fast/slow asymmetry test)."""
    if description is None:
        description = (
            f"Throttle TCP WindowSize={tcp_window_size_bytes} on IXIA "
            f"DGs matching {device_group_regex!r} on {hostname}:{interface}"
        )
    return create_ixia_api_step(
        api_name="configure_bgp_peer_tcp_window_size",
        args_dict={
            "hostname": hostname,
            "interface": interface,
            "device_group_regex": device_group_regex,
            "tcp_window_size_bytes": tcp_window_size_bytes,
        },
        description=description,
    )


def create_configure_as_path_pool_step(
    device_name: str,
    interface: str,
    as_path_pool: list[str],
    device_group_regex: str = ".*",
    description: str | None = None,
    stop_protocols: bool = True,
) -> Step:
    """
    Create a step to configure an AS path pool on IXIA prefix pools.

    Uses the IXIA ValueList API to distribute AS paths cyclically across routes.

    Args:
        device_name: Hostname of the device
        interface: Interface to configure AS path pool on
        as_path_pool: List of AS path strings (e.g. ["65001 65002", "65003 65004"])
        device_group_regex: Regex to filter device groups by name (default: ".*")
        description: Custom step description (optional)
        stop_protocols: Whether the IXIA wrapper should call ``stop_protocols()``
            before the config write (default: True). Default preserves legacy
            behavior. Set to False ONLY when the caller knows the topology can
            absorb the config change in-place -- the unconditional stop in
            ``ixia.py::configure_as_path_pool`` can cascade-reset every BGP TCP
            session on the chassis at scale.

    Returns:
        Step object for AS path pool configuration
    """
    return create_ixia_api_step(
        api_name="configure_as_path_pool",
        args_dict={
            "hostname": device_name,
            "interface": interface,
            "as_path_pool": as_path_pool,
            "restart_protocols": False,
            "device_group_regex": device_group_regex,
            "stop_protocols": stop_protocols,
        },
        description=description or "Configure AS path pool on IXIA",
    )


def create_configure_community_pool_step(
    device_name: str,
    interface: str,
    community_combinations: list[list[str]],
    device_group_regex: str = ".*",
    description: str | None = None,
    stop_protocols: bool = True,
) -> Step:
    """
    Create a step to configure a community pool on IXIA prefix pools.

    Uses the IXIA ValueList API to distribute community combinations across routes.

    Args:
        device_name: Hostname of the device
        interface: Interface to configure community pool on
        community_combinations: List of community lists per prefix
        device_group_regex: Regex to filter device groups by name (default: ".*")
        description: Custom step description (optional)
        stop_protocols: Whether the IXIA wrapper should call ``stop_protocols()``
            before the config write (default: True). Default preserves legacy
            behavior. Set to False ONLY when the caller knows the topology can
            absorb the config change in-place -- the unconditional stop in
            ``ixia.py::configure_community_pool`` can cascade-reset every BGP TCP
            session on the chassis at scale.

    Returns:
        Step object for community pool configuration
    """
    return create_ixia_api_step(
        api_name="configure_community_pool",
        args_dict={
            "hostname": device_name,
            "interface": interface,
            "community_combinations": community_combinations,
            "restart_protocols": False,
            "device_group_regex": device_group_regex,
            "stop_protocols": stop_protocols,
        },
        description=description or "Configure community pool on IXIA",
    )


def create_configure_extended_community_pool_step(
    device_name: str,
    interface: str,
    extended_community_combinations: list[list[str]],
    device_group_regex: str = ".*",
    description: str | None = None,
    stop_protocols: bool = True,
) -> Step:
    """
    Create a step to configure an extended community pool on IXIA prefix pools.

    Uses the IXIA ValueList API to distribute extended community combinations across routes.

    Args:
        device_name: Hostname of the device
        interface: Interface to configure extended community pool on
        extended_community_combinations: List of extended community lists per prefix
        device_group_regex: Regex to filter device groups by name (default: ".*")
        description: Custom step description (optional)
        stop_protocols: Whether the IXIA wrapper should call ``stop_protocols()``
            before the config write (default: True). Default preserves legacy
            behavior. Set to False ONLY when the caller knows the topology can
            absorb the config change in-place -- the unconditional stop in
            ``ixia.py::configure_extended_community_pool`` can cascade-reset
            every BGP TCP session on the chassis at scale.

    Returns:
        Step object for extended community pool configuration
    """
    return create_ixia_api_step(
        api_name="configure_extended_community_pool",
        args_dict={
            "hostname": device_name,
            "interface": interface,
            "extended_community_combinations": extended_community_combinations,
            "restart_protocols": False,
            "device_group_regex": device_group_regex,
            "stop_protocols": stop_protocols,
        },
        description=description or "Configure extended community pool on IXIA",
    )


def create_revert_route_storm_attributes_step(
    device_name: str,
    interface: str,
    device_group_regex: str = ".*",
    description: str | None = None,
) -> Step:
    """
    Create a step to revert "New Year Tree" BGP attributes on IXIA to defaults.

    Resets AS path segments, MED, local preference, ORIGIN, communities,
    and extended communities back to their default/disabled state after
    route storm testing.

    Args:
        device_name: Hostname of the device
        interface: Interface to revert attributes on
        device_group_regex: Regex to filter device groups by name (default: ".*")
        description: Custom step description (optional)

    Returns:
        Step object for reverting route storm attributes
    """
    return create_ixia_api_step(
        api_name="revert_route_storm_attributes",
        args_dict={
            "hostname": device_name,
            "interface": interface,
            "device_group_regex": device_group_regex,
        },
        description=description
        or "Revert route storm (New Year Tree) attributes to defaults on IXIA",
    )


def create_set_bgp_prefixes_local_preference_step(
    prefix_pool_regex: str,
    local_pref_value: int,
    prefix_start_index: int = 0,
    prefix_end_index: t.Optional[int] = None,
    description: t.Optional[str] = None,
) -> Step:
    """
    Create a step to set BGP local preference for prefixes within a specified range.

    This function modifies the local preference attribute for prefixes in the
    specified prefix pool. Local preference is a well-known BGP attribute
    used to prefer certain paths over others within an autonomous system.

    Args:
        prefix_pool_regex: Regex pattern to match prefix pool names
        local_pref_value: Local preference value to set
        prefix_start_index: Starting index (inclusive) within the network group multiplier. Defaults to 0.
        prefix_end_index: Ending index (exclusive) within the network group multiplier. If None, uses the network group multiplier value (all remaining prefixes).
        description: Custom description for the step

    Returns:
        Step object for BGP prefix local preference modification
    """
    if description is None:
        index_range = (
            f"{prefix_start_index}-{prefix_end_index}"
            if prefix_end_index
            else f"{prefix_start_index}+"
        )
        description = f"Set local preference to {local_pref_value} for prefix indices {index_range} matching '{prefix_pool_regex}'"

    params_dict: t.Dict[str, t.Any] = {
        "prefix_pool_regex": prefix_pool_regex,
        "local_pref_value": local_pref_value,
        "prefix_start_index": prefix_start_index,
    }
    if prefix_end_index is not None:
        params_dict["prefix_end_index"] = prefix_end_index

    return create_run_task_step(
        task_name="ixia_set_bgp_prefixes_local_preference",
        params_dict=params_dict,
        description=description,
        ixia_needed=True,
    )


def create_set_route_filter_step(
    device_name: str,
    config_path: t.Optional[str] = None,
    source: str = "configerator",
    json_file_path: t.Optional[str] = None,
    description: t.Optional[str] = None,
) -> Step:
    """
    Create a step to set BGP route filter policy using setRouteFilterPolicy.

    This function applies a route filter policy to a BGP router by loading it from
    either Configerator or a JSON file and calling the setRouteFilterPolicy API.

    Args:
        device_name: Name of the device to apply the route filter policy to
        config_path: Configerator path to the route filter policy
                     (default: "taac/test_bgp_policies/ebb_route_registry_prefix_list_750.json")
        source: Policy source - "configerator" or "json" (default: "configerator")
        json_file_path: Path to JSON file containing the route filter policy
                        (required if source="json")
        description: Custom description for the step

    Returns:
        Step object for setting BGP route filter policy
    """
    if description is None:
        if source == "configerator":
            path = (
                config_path
                or "taac/test_bgp_policies/ebb_route_registry_prefix_list_750.json"
            )
            description = (
                f"Set route filter policy on {device_name} from Configerator: {path}"
            )
        else:
            description = f"Set route filter policy on {device_name} from JSON file: {json_file_path}"

    params_dict: t.Dict[str, t.Any] = {
        "hostname": device_name,
        "source": source,
    }

    if config_path is not None:
        params_dict["config_path"] = config_path

    if json_file_path is not None:
        params_dict["json_file_path"] = json_file_path

    return create_run_task_step(
        task_name="bgp_set_route_filter",
        params_dict=params_dict,
        description=description,
    )


def create_set_peer_groups_policy_step(
    device_name: str,
    peer_groups_policy: t.Dict[str, t.Dict[str, str]],
    description: t.Optional[str] = None,
) -> Step:
    """
    Create a step to set BGP policies for peer groups using setPeerGroupsPolicy.

    This function applies routing policies to BGP peer groups, typically used for
    drain/undrain operations where policies modify BGP attributes like ORIGIN and AS_PATH.

    Args:
        device_name: Name of the device to apply the policies to
        peer_groups_policy: Dictionary mapping peer group names to direction->policy mappings
                            Example: {
                                "EB-FA-V6": {"OUT": "EB-FA-OUT-DRAIN"},
                                "EB-FA-V4": {"OUT": "EB-FA-OUT-DRAIN"},
                                "EB-EB-V6": {"OUT": "EB-EB-OUT-DRAIN"},
                                "EB-EB-V4": {"OUT": "EB-EB-OUT-DRAIN"},
                            }
        description: Custom description for the step

    Returns:
        Step object for setting peer group policies

    Example:
        >>> drain_policies = {
        ...     "EB-FA-V6": {"OUT": "EB-FA-OUT-DRAIN"},
        ...     "EB-FA-V4": {"OUT": "EB-FA-OUT-DRAIN"},
        ... }
        >>> step = create_set_peer_groups_policy_step(
        ...     device_name="rsw1ag.p001.f01.atn1",
        ...     peer_groups_policy=drain_policies,
        ... )
    """
    if description is None:
        peer_group_names = ", ".join(peer_groups_policy.keys())
        description = (
            f"Set policies for peer groups on {device_name}: {peer_group_names}"
        )

    params_dict: t.Dict[str, t.Any] = {
        "hostname": device_name,
        "peer_groups_policy": peer_groups_policy,
    }

    return create_run_task_step(
        task_name="bgp_set_peer_groups_policy",
        params_dict=params_dict,
        description=description,
    )


def _validated_route_stability_params(
    *,
    expected_count: t.Optional[int],
    min_count: t.Optional[int],
    max_count: t.Optional[int],
    convergence_enabled: bool,
    duration_seconds: t.Optional[float],
    hard_timeout_seconds: t.Optional[float],
    poll_interval_seconds: t.Optional[float],
) -> t.Dict[str, float]:
    params = {
        "stability_duration_seconds": duration_seconds,
        "stability_hard_timeout_seconds": hard_timeout_seconds,
        "stability_poll_interval_seconds": poll_interval_seconds,
    }
    values = tuple(params.values())
    if not any(value is not None for value in values):
        return {}
    if (
        duration_seconds is None
        or hard_timeout_seconds is None
        or poll_interval_seconds is None
    ):
        raise ValueError(
            "stability_duration_seconds, stability_hard_timeout_seconds, and "
            "stability_poll_interval_seconds must be provided together"
        )
    if convergence_enabled:
        raise ValueError("convergence and stability observation are mutually exclusive")
    if expected_count is None or min_count is not None or max_count is not None:
        raise ValueError(
            "stability observation requires expected_count and does not support "
            "min_count or max_count"
        )
    duration = float(duration_seconds)
    hard_timeout = float(hard_timeout_seconds)
    poll_interval = float(poll_interval_seconds)
    if duration <= 0 or poll_interval <= 0:
        raise ValueError("stability duration and poll interval must be positive")
    if hard_timeout <= duration:
        raise ValueError(
            "stability_hard_timeout_seconds must exceed stability_duration_seconds"
        )
    return {
        "stability_duration_seconds": duration,
        "stability_hard_timeout_seconds": hard_timeout,
        "stability_poll_interval_seconds": poll_interval,
    }


def create_verify_received_routes_step(
    device_name: str,
    expected_count: t.Optional[int] = None,
    min_count: t.Optional[int] = None,
    max_count: t.Optional[int] = None,
    descriptions_to_check: t.Optional[t.List[str]] = None,
    descriptions_to_ignore: t.Optional[t.List[str]] = None,
    direction: str = "received",
    policy_type: str = "post_policy",
    description: t.Optional[str] = None,
    convergence_soft_threshold_seconds: t.Optional[float] = None,
    convergence_hard_timeout_seconds: t.Optional[float] = None,
    convergence_poll_interval_seconds: t.Optional[float] = None,
    stability_duration_seconds: t.Optional[float] = None,
    stability_hard_timeout_seconds: t.Optional[float] = None,
    stability_poll_interval_seconds: t.Optional[float] = None,
) -> Step:
    """
    Create a step to verify BGP received routes count from peers.

    This function checks the number of routes received from BGP peers after
    policy filtering using the prefilter/postfilter APIs. This is useful
    for verifying that route filter policies (prefix-lists) are working correctly.

    Args:
        device_name: Name of the device to check received routes on
        expected_count: Expected exact number of received routes (optional)
        min_count: Minimum expected routes (optional)
        max_count: Maximum expected routes (optional)
        descriptions_to_check: List of description substrings to match peers (optional)
        descriptions_to_ignore: List of description substrings to ignore peers (optional)
        direction: "received" or "advertised" (default: "received")
        policy_type: "pre_policy" or "post_policy" (default: "post_policy")
        description: Custom description for the step
        convergence_soft_threshold_seconds: Optional exact-count convergence SLA
        convergence_hard_timeout_seconds: Optional exact-count observation timeout
        convergence_poll_interval_seconds: Optional exact-count polling interval
        stability_duration_seconds: Optional continuous exact stability duration
        stability_hard_timeout_seconds: Optional stability operational hard timeout
        stability_poll_interval_seconds: Optional stability polling interval

    Returns:
        Step object for verifying BGP received routes count
    """
    if description is None:
        peer_filter = ""
        if descriptions_to_check:
            peer_filter = f" from peers matching {descriptions_to_check}"
        if expected_count is not None:
            description = f"Verify {device_name} receives exactly {expected_count} routes{peer_filter}"
        elif max_count is not None:
            description = (
                f"Verify {device_name} receives at most {max_count} routes{peer_filter}"
            )
        elif min_count is not None:
            description = f"Verify {device_name} receives at least {min_count} routes{peer_filter}"
        else:
            description = f"Check received routes count on {device_name}{peer_filter}"

    params_dict: t.Dict[str, t.Any] = {
        "hostname": device_name,
        "direction": direction,
        "policy_type": policy_type,
    }

    if descriptions_to_check is not None:
        params_dict["descriptions_to_check"] = descriptions_to_check

    if descriptions_to_ignore is not None:
        params_dict["descriptions_to_ignore"] = descriptions_to_ignore

    if expected_count is not None:
        params_dict["expected_count"] = expected_count

    if min_count is not None:
        params_dict["min_count"] = min_count

    if max_count is not None:
        params_dict["max_count"] = max_count

    convergence_params = {
        "convergence_soft_threshold_seconds": convergence_soft_threshold_seconds,
        "convergence_hard_timeout_seconds": convergence_hard_timeout_seconds,
        "convergence_poll_interval_seconds": convergence_poll_interval_seconds,
    }
    params_dict.update(
        {key: value for key, value in convergence_params.items() if value is not None}
    )

    params_dict.update(
        _validated_route_stability_params(
            expected_count=expected_count,
            min_count=min_count,
            max_count=max_count,
            convergence_enabled=any(
                value is not None for value in convergence_params.values()
            ),
            duration_seconds=stability_duration_seconds,
            hard_timeout_seconds=stability_hard_timeout_seconds,
            poll_interval_seconds=stability_poll_interval_seconds,
        )
    )

    return create_run_task_step(
        task_name="bgp_verify_received_routes",
        params_dict=params_dict,
        description=description,
    )


def create_file_from_config_step(
    device_name: str,
    configerator_path: str,
    file_path: str,
    description: t.Optional[str] = None,
) -> Step:
    """
    Create a step to create a file from a Configerator config on an Arista device.

    Args:
        device_name: Name of the device (hostname)
        configerator_path: Path to the config in Configerator
        file_path: Path where the file should be created on the device
        description: Custom description for the step

    Returns:
        Step object for creating a file from config
    """
    if description is None:
        description = f"Create file from config on {device_name}: {file_path}"

    return create_run_task_step(
        task_name="arista_create_file_from_config",
        params_dict={
            "hostname": device_name,
            "configerator_path": configerator_path,
            "file_path": file_path,
        },
        description=description,
    )


def create_run_commands_on_shell_step(
    device_name: str,
    cmds: t.List[str],
    description: t.Optional[str] = None,
) -> Step:
    """
    Create a step to run shell commands on a device.

    Args:
        device_name: Name of the device (hostname)
        cmds: List of shell commands to execute
        description: Custom description for the step

    Returns:
        Step object for running shell commands
    """
    if description is None:
        description = f"Run shell commands on {device_name}"

    return create_run_task_step(
        task_name="run_commands_on_shell",
        params_dict={
            "hostname": device_name,
            "cmds": cmds,
        },
        description=description,
    )


def create_configure_bgp_flap_step(
    peer_regex: str,
    enable: bool,
    uptime_seconds: int = 30,
    downtime_seconds: int = 30,
    description: t.Optional[str] = None,
) -> Step:
    """Enable or disable IXIA-side BGP session flapping for matching peers.

    Wraps the IXIA `configure_bgp_peers_flap` API. When `enable=True`,
    matching peers oscillate up/down with the configured uptime/downtime
    intervals; when `enable=False`, flapping is stopped (uptime/downtime
    args are ignored). Used in scale/longevity tests to drive sustained
    session churn against the DUT.

    Args:
        peer_regex: Regex matching the IXIA BGP peer names to flap.
        enable: True to start flapping, False to stop it.
        uptime_seconds: Time peers stay UP between flaps (only when
            enable=True). Default 30s.
        downtime_seconds: Time peers stay DOWN between flaps (only when
            enable=True). Default 30s.
        description: Custom description for the step. If omitted, a
            sensible default is generated from the args.

    Returns:
        A `Step` with `step_name=StepName.INVOKE_IXIA_API_STEP` calling
        `configure_bgp_peers_flap`.
    """
    if description is None:
        if enable:
            description = (
                f"Enable BGP flapping: {uptime_seconds}s up, {downtime_seconds}s down"
            )
        else:
            description = f"Disable BGP flapping for {peer_regex}"

    if enable:
        args_dict = {
            "regex": peer_regex,
            "enable": enable,
            "uptime_in_sec": uptime_seconds,
            "downtime_in_sec": downtime_seconds,
        }
    else:
        args_dict = {
            "regex": peer_regex,
            "enable": enable,
        }

    return create_ixia_api_step(
        api_name="configure_bgp_peers_flap",
        args_dict=args_dict,
        description=description,
    )


def create_start_stop_bgp_peers_step(
    peer_regex: str,
    start: bool,
    start_idx: int,
    end_idx: int,
    description: t.Optional[str] = None,
) -> Step:
    """Start or stop a contiguous range of IXIA BGP peer sessions.

    Wraps the IXIA `start_bgp_peers` API. Useful when a test wants to
    bring up only a subset of configured peers (e.g. to scale up traffic
    in waves, or to repeatedly bounce a specific session block to drive
    targeted churn) rather than toggling an entire device-group.

    Args:
        peer_regex: Regex matching the IXIA BGP peer (group) name.
        start: True to start sessions, False to stop them.
        start_idx: Index of the first session in the range (inclusive).
        end_idx: Index of the last session in the range (inclusive).
        description: Custom description for the step. If omitted, a
            default is generated counting the affected sessions.

    Returns:
        A `Step` with `step_name=StepName.INVOKE_IXIA_API_STEP` calling
        `start_bgp_peers`.
    """
    if description is None:
        action = "Start" if start else "Stop"
        session_count = end_idx - start_idx + 1
        description = (
            f"{action} sessions {start_idx}-{end_idx} ({session_count} sessions)"
        )

    return create_ixia_api_step(
        api_name="start_bgp_peers",
        args_dict={
            "start": start,
            "regex": peer_regex,
            "session_start_idx": start_idx,
            "session_end_idx": end_idx,
        },
        description=description,
    )


def create_validated_bgp_session_oscillation_step(
    device_name: str,
    session_groups: t.Sequence[t.Mapping[str, t.Any]],
    cycle_schedule: t.Sequence[t.Sequence[str]],
    expected_established_sessions: int,
    test_duration_seconds: int,
    uptime_seconds: int,
    downtime_seconds: int,
    parent_prefixes_to_ignore: t.Sequence[str] = (),
    description: t.Optional[str] = None,
) -> Step:
    """Create a blocking session-oscillation workload with per-trigger checks."""
    return create_custom_step(
        params_dict={
            "custom_step_name": "bgp_session_oscillation",
            "hostname": device_name,
            "session_groups": list(session_groups),
            "cycle_schedule": [list(groups) for groups in cycle_schedule],
            "expected_established_sessions": expected_established_sessions,
            "test_duration_seconds": test_duration_seconds,
            "uptime_seconds": uptime_seconds,
            "downtime_seconds": downtime_seconds,
            "parent_prefixes_to_ignore": list(parent_prefixes_to_ignore),
        },
        description=description or "Run validated BGP session oscillations",
    )


def create_stop_bgp_keepalive_step(
    peer_regex: str,
    session_index: t.Optional[int] = None,
    ignore_case: bool = False,
    description: t.Optional[str] = None,
) -> Step:
    """Stop KeepAlive on one (or all) IXIA BGP peer session(s).

    Wraps the IXIA ``stop_bgp_keepalive`` API: the peer goes silent while the
    session stays materialized, so the DUT hits hold-timer expiry on that
    neighbor and originates a Hold-Timer-Expired NOTIFICATION (the 2.9.3
    trigger). Pass ``session_index`` (1-based) to isolate ONE session; omit it to
    silence every session of the matched peer(s). A combined ``v4|v6`` regex
    hits the same session on both AFIs.

    Args:
        peer_regex: Regex matched against the IXIA BGP peer (group) .Name.
        session_index: 1-based session to silence; ``None`` -> all sessions.
        ignore_case: Case-insensitive name match.
        description: Custom description; a default is generated if omitted.
    """
    if description is None:
        _which = (
            f"session {session_index}" if session_index is not None else "all sessions"
        )
        description = f"Stop BGP KeepAlive on {_which} of ~{peer_regex!r}"
    args_dict: t.Dict[str, t.Any] = {"regex": peer_regex}
    if session_index is not None:
        args_dict["session_index"] = session_index
    if ignore_case:
        args_dict["ignore_case"] = True
    return create_ixia_api_step(
        api_name="stop_bgp_keepalive",
        args_dict=args_dict,
        description=description,
    )


def create_resume_bgp_keepalive_step(
    peer_regex: str,
    session_index: t.Optional[int] = None,
    ignore_case: bool = False,
    description: t.Optional[str] = None,
) -> Step:
    """Resume KeepAlive on one (or all) IXIA BGP peer session(s).

    Recovery counterpart to ``create_stop_bgp_keepalive_step``: the peer resumes
    sending KeepAlive so the DUT re-establishes the session and the update group
    re-syncs (2.9.3 recovery). Same ``peer_regex`` / ``session_index`` grammar.
    """
    if description is None:
        _which = (
            f"session {session_index}" if session_index is not None else "all sessions"
        )
        description = f"Resume BGP KeepAlive on {_which} of ~{peer_regex!r}"
    args_dict: t.Dict[str, t.Any] = {"regex": peer_regex}
    if session_index is not None:
        args_dict["session_index"] = session_index
    if ignore_case:
        args_dict["ignore_case"] = True
    return create_ixia_api_step(
        api_name="resume_bgp_keepalive",
        args_dict=args_dict,
        description=description,
    )


def create_tcpdump_step(
    device_name: str,
    mode: str,
    interface: str = "any",
    capture_file_path: str = "/tmp/bgp_capture.txt",
    description: t.Optional[str] = None,
    message_type: str = "Update",
) -> Step:
    """
    Create a step to start or stop tcpdump capture.

    Args:
        device_name: Name of the device to run tcpdump on
        mode: Either "start_capture" or "stop_capture"
        interface: Network interface to capture on (default: "any")
        capture_file_path: Path where to save the capture file
        description: Custom description for the step
        message_type: Message type to capture (default: "Update")
    Returns:
        Step object for tcpdump operation
    """
    if description is None:
        action = "Start" if mode == "start_capture" else "Stop"
        description = f"{action} tcpdump capture on {device_name}"

    return create_run_task_step(
        task_name="bgp_tcpdump",
        params_dict={
            "hostname": device_name,
            "mode": mode,
            "interface": interface,
            "capture_file_path": capture_file_path,
            "message_type": message_type,
        },
        description=description,
    )


def create_advertise_withdraw_prefixes_step(
    device_name: str,
    advertise: bool,
    prefix_pool_regex: str,
    prefix_start_index: int,
    prefix_end_index: t.Optional[int] = None,
    description: t.Optional[str] = None,
    expected_prefix_pool_count: t.Optional[int] = None,
    expected_number_of_addresses: t.Optional[int] = None,
    runtime_route_operation: bool = False,
) -> Step:
    """
    Create a step to advertise or withdraw BGP prefixes from matching prefix pools.

    Args:
        advertise: True to advertise prefixes, False to withdraw them
        prefix_pool_regex: Regex pattern to match prefix pool names
        prefix_start_index: Starting index (inclusive) in the prefix range
        prefix_end_index: Ending index in the prefix range. If None, uses the network group multiplier value (all remaining prefixes).
        description: Custom description for the step
        expected_prefix_pool_count: Exact number of matching IXIA prefix pools.
        expected_number_of_addresses: Exact compact-pool route capacity.
        runtime_route_operation: Stop/start the selected physical route-property
            rows around the Active mutation. Requires exactly one matched pool.

    Returns:
        Step object for BGP prefix advertisement/withdrawal
    """
    if description is None:
        action = "Advertise" if advertise else "withdraw"
        description = f"{action} prefixes"

    params_dicts: t.Dict[str, t.Any] = {
        "hostname": device_name,
        "enable": advertise,
        "prefix_pool_regex": prefix_pool_regex,
        "prefix_start_index": prefix_start_index,
    }
    if prefix_end_index is not None:
        params_dicts["prefix_end_index"] = prefix_end_index
    if expected_prefix_pool_count is not None:
        params_dicts["expected_prefix_pool_count"] = expected_prefix_pool_count
    if expected_number_of_addresses is not None:
        params_dicts["expected_number_of_addresses"] = expected_number_of_addresses
    if runtime_route_operation:
        params_dicts["runtime_route_operation"] = True

    return create_run_task_step(
        task_name="ixia_enable_disable_bgp_prefixes",
        params_dict=params_dicts,
        description=description,
        ixia_needed=True,
    )


def create_validated_bgp_route_oscillation_step(
    device_name: str,
    prefix_pool_regex: str,
    expected_prefix_pool_names: t.Sequence[str],
    expected_established_sessions: int,
    prefix_start_index: int,
    prefix_end_index: int,
    withdraw_time: int,
    readvertise_time: int,
    test_duration_seconds: int,
    parent_prefixes_to_ignore: t.Sequence[str] = (),
    description: t.Optional[str] = None,
) -> Step:
    """Create route oscillations with IXIA, source, and exact-RIB verdicts."""
    return create_custom_step(
        params_dict={
            "custom_step_name": "bgp_route_oscillation",
            "hostname": device_name,
            "prefix_pool_regex": prefix_pool_regex,
            "expected_prefix_pool_names": list(expected_prefix_pool_names),
            "expected_established_sessions": expected_established_sessions,
            "prefix_start_index": prefix_start_index,
            "prefix_end_index": prefix_end_index,
            "withdraw_time": withdraw_time,
            "readvertise_time": readvertise_time,
            "test_duration_seconds": test_duration_seconds,
            "parent_prefixes_to_ignore": list(parent_prefixes_to_ignore),
        },
        description=description or "Run validated dual-stack BGP route oscillations",
    )


def create_validated_igp_pnh_metric_oscillation_step(
    device_name: str,
    start_ipv4s: t.Sequence[str],
    start_ipv6s: t.Sequence[str],
    local_link: t.Mapping[str, t.Any],
    other_link: t.Mapping[str, t.Any],
    count: int,
    step: int,
    duration: int,
    frequency: int,
) -> Step:
    """Create acknowledged Open/R-to-BGP PNH metric oscillations."""
    return create_custom_step(
        params_dict={
            "custom_step_name": "bgp_igp_pnh_metric_oscillation",
            "hostname": device_name,
            "start_ipv4s": list(start_ipv4s),
            "start_ipv6s": list(start_ipv6s),
            "local_link": dict(local_link),
            "other_link": dict(other_link),
            "count": count,
            "step": step,
            "duration": duration,
            "frequency": frequency,
        },
        description="Run acknowledged Open/R PNH metric oscillations",
    )


def create_validated_igp_unresolvable_pnh_step(
    device_name: str,
    start_ipv4s: t.Sequence[str],
    start_ipv6s: t.Sequence[str],
    restore_start_ipv4s: t.Sequence[str],
    restore_start_ipv6s: t.Sequence[str],
    local_link: t.Mapping[str, t.Any],
    other_link: t.Mapping[str, t.Any],
    count: int,
    step: int,
    delete_count: int,
    update_timeout_seconds: int,
    stability_duration_seconds: int,
) -> Step:
    """Create a failure-safe, acknowledged unresolvable-PNH workflow."""
    return create_custom_step(
        params_dict={
            "custom_step_name": "bgp_igp_unresolvable_pnh",
            "hostname": device_name,
            "start_ipv4s": list(start_ipv4s),
            "start_ipv6s": list(start_ipv6s),
            "restore_start_ipv4s": list(restore_start_ipv4s),
            "restore_start_ipv6s": list(restore_start_ipv6s),
            "local_link": dict(local_link),
            "other_link": dict(other_link),
            "count": count,
            "step": step,
            "delete_count": delete_count,
            "update_timeout_seconds": update_timeout_seconds,
            "stability_duration_seconds": stability_duration_seconds,
        },
        description="Run validated unresolvable Open/R PNH workflow",
    )


def create_prepare_compact_bgp_prefix_pool_step(
    *,
    device_name: str,
    prefix_pool_regex: str,
    target_number_of_addresses: int,
    allowed_current_number_of_addresses: t.Sequence[int],
    safe_number_of_addresses: int,
    description: t.Optional[str] = None,
) -> Step:
    """Withdraw, resize, and freshly verify one compact BGP prefix pool."""
    return create_run_task_step(
        task_name="ixia_enable_disable_bgp_prefixes",
        params_dict={
            "hostname": device_name,
            "enable": False,
            "prefix_pool_regex": prefix_pool_regex,
            "prefix_start_index": 0,
            "expected_prefix_pool_count": 1,
            "target_number_of_addresses": target_number_of_addresses,
            "allowed_current_number_of_addresses": list(
                allowed_current_number_of_addresses
            ),
            "safe_number_of_addresses": safe_number_of_addresses,
            "runtime_route_operation": True,
        },
        description=description or "Prepare compact BGP prefix pool",
        ixia_needed=True,
    )


def create_randomize_prefix_local_preference_step(
    prefix_pool_regex: str,
    prefix_start_index: int,
    prefix_end_index: t.Optional[int] = None,
    start_value: int = 10,
    end_value: int = 101,
    description: t.Optional[str] = None,
) -> Step:
    """
    Create a step to randomize BGP prefix local preference values for prefixes within a specified range.

    Args:
        prefix_pool_regex: Regex pattern to match prefix pool names
        prefix_start_index: Starting index (inclusive) in the prefix range
        prefix_end_index: Ending index in the prefix range
        start_value: Minimum local preference value (inclusive)
        end_value: Maximum local preference value (exclusive)
        description: Custom description for the step

    Returns:
        Step object for randomizing
    """
    if description is None:
        description = (
            f"Randomize BGP prefix local preference on pool regex {prefix_pool_regex}"
        )
    params_dicts: t.Dict[str, t.Any] = {
        "prefix_pool_regex": prefix_pool_regex,
        "prefix_start_index": prefix_start_index,
        "start_value": start_value,
        "end_value": end_value,
    }
    if prefix_end_index is not None:
        params_dicts["prefix_end_index"] = prefix_end_index

    return create_run_task_step(
        task_name="ixia_randomize_bgp_prefix_local_preference",
        params_dict=params_dicts,
        description=description,
        ixia_needed=True,
    )


def create_openr_route_action_step(
    device_name: str,
    start_ipv4s: t.List[str],
    start_ipv6s: t.List[str],
    local_link: t.Dict[str, t.Any],
    other_link: t.Dict[str, t.Any],
    action: str = OpenRRouteAction.INJECT.value,
    count: int = 63,
    step: int = 2,
    mask: int = -1,
    delete_count: int = 0,
    duration: t.Optional[int] = None,
    frequency: t.Optional[int] = None,
    sequential: t.Optional[bool] = None,
    description: t.Optional[str] = None,
) -> Step:
    """
    Create a configurable Open/R route action step (inject, delete, metric_oscillation).

    Args:
        device_name: Name of the device to perform Open/R route actions on
        start_ipv4s: List of starting IPv4 addresses for Open/R routes
        start_ipv6s: List of starting IPv6 addresses for Open/R routes
        local_link: Information about the local link.
        other_link: Informaiton about the other side of the link.
        action: Open/R route action (OpenRRouteAction.INJECT.value, OpenRRouteAction.DELETE.value, OpenRRouteAction.METRIC_OSCILLATION.value)
        count: Number of IPs to create per start_ip (default: 63)
        step: The step size to increment the IP address by (default: 2)
        mask: The mask/prefix length of the IP address (default: -1)
        duration: Duration in seconds for metric_oscillation actions (optional)
        frequency: Frequency in seconds for metric_oscillation actions (optional)
        sequential: Sequential thrift calls for deleting actions (optional)
        description: Custom description for the step

    Returns:
        Step object for the specified Open/R route action
    """
    if description is None:
        if action == OpenRRouteAction.METRIC_OSCILLATION.value:
            desc_duration = duration or 3600
            desc_frequency = frequency or 60
            description = f"Open/R metric oscillation on {device_name} for {desc_duration}s (every {desc_frequency}s)"
        elif action == OpenRRouteAction.INJECT.value:
            description = f"Inject Open/R routes on {device_name}"
        elif action == OpenRRouteAction.DELETE.value:
            description = f"Delete Open/R routes on {device_name}"
        else:
            description = f"Open/R route action '{action}' on {device_name}"

    params = {
        "hostname": device_name,
        "start_ipv4s": start_ipv4s,
        "start_ipv6s": start_ipv6s,
        "count": count,
        "step": step,
        "local_link": local_link,
        "other_link": other_link,
        "mask": mask,
        "action": action,
    }

    if action == OpenRRouteAction.METRIC_OSCILLATION.value:
        if duration is not None:
            params["duration"] = duration
        if frequency is not None:
            params["frequency"] = frequency
    if action == OpenRRouteAction.DELETE.value:
        if sequential is not None:
            params["sequential"] = sequential
        params["delete_count"] = delete_count

    return Step(
        name=StepName.INJECT_ROUTES_STEP,
        description=description,
        step_params=Params(json_params=json.dumps(params)),
    )


def create_drain_convergence_verification_step(
    pcap_filename: str,
    max_convergence_time_seconds: int = 600,
    expected_as_path_asn: t.Optional[int] = None,
    phase: str = "drain",
    description: t.Optional[str] = None,
) -> Step:
    """
    Create a step to verify drain/undrain convergence from PCAP analysis.

    This step verifies:
    - Convergence time is within threshold
    - Routes have expected BGP attributes (AS_PATH, ORIGIN)
    - No BGP withdrawal messages during convergence

    Args:
        pcap_filename: Name of PCAP file on IXIA server
        max_convergence_time_seconds: Maximum allowed convergence time (default: 600s/10min)
        expected_as_path_asn: Expected ASN in AS_PATH (default: None, skips AS_PATH check)
        phase: "drain" or "undrain" for proper ORIGIN verification
        description: Custom description for the step

    Returns:
        Step object for drain convergence verification
    """
    if description is None:
        description = f"Verify {phase} convergence from {pcap_filename} (max {max_convergence_time_seconds}s)"

    params = {
        "custom_step_name": "verify_drain_convergence",
        "pcap_filename": pcap_filename,
        "max_convergence_time_seconds": max_convergence_time_seconds,
        "expected_as_path_asn": expected_as_path_asn,
        "verify_origin_incomplete": True,
        "phase": phase,
    }

    return Step(
        name=StepName.CUSTOM_STEP,
        step_params=Params(json_params=json.dumps(params)),
        description=description,
    )


def create_consolidated_convergence_report_step(
    phase: str = "drain",
    pcap_files: t.Optional[t.Dict[str, str]] = None,
    description: t.Optional[str] = None,
) -> Step:
    """
    Create a step to generate a consolidated convergence report across all interfaces.

    This step collects convergence data from all three interfaces (iBGP SOURCE,
    BGP Monitor, eBGP to FA-UU) and generates a unified report showing:
    - Timeline comparison across interfaces
    - Latency calculations (SOURCE→Monitor, SOURCE→eBGP, Monitor→eBGP)
    - UPDATE message counts at each interface

    Args:
        phase: "drain" or "undrain" for the report title
        pcap_files: Dict mapping interface name to PCAP filename, e.g.:
            {
                "ibgp_source": "bgp_plane_drain_ibgp_source.pcap",
                "bgp_monitor": "bgp_plane_drain_bgpmon.pcap",
                "ebgp": "bgp_plane_drain_ebgp.pcap"
            }
        description: Custom description for the step

    Returns:
        Step object for consolidated convergence report
    """
    if description is None:
        description = (
            f"Generate consolidated {phase} convergence report across all interfaces"
        )

    if pcap_files is None:
        pcap_files = {}

    params = {
        "custom_step_name": "generate_consolidated_convergence_report",
        "phase": phase,
        "pcap_files": pcap_files,
    }

    return Step(
        name=StepName.CUSTOM_STEP,
        step_params=Params(json_params=json.dumps(params)),
        description=description,
    )


def create_ixia_packet_capture_step(
    device_name: str,
    interface: str,
    mode: str,
    capture_filter: str = "tcp port 179",
    pcap_filename: t.Optional[str] = None,
    capture_id: t.Optional[str] = None,
    description: t.Optional[str] = None,
) -> Step:
    """
    Create a step to start/stop/save packet capture on IXIA port.

    This captures BGP messages at the IXIA BGP monitor (receiver side),
    providing accurate convergence time measurements as per test spec.

    Args:
        device_name: Name of the device under test (for port lookup)
        interface: Interface name on device (e.g., "Ethernet3/1/1")
        mode: "start", "stop", or "save"
        capture_filter: BPF filter for capture (default: "tcp port 179" for BGP)
        pcap_filename: Filename for saved PCAP (required for save mode)
        capture_id: Unique ID to track capture across steps (default: device:interface)
        description: Custom description for the step

    Returns:
        Step object for IXIA packet capture operation

    Example:
        # Start capture
        create_ixia_packet_capture_step(
            device_name="eb04.lab.ash6",
            interface="Ethernet3/1/1",
            mode="start",
            capture_id="drain_phase",
        )

        # Save and stop capture
        create_ixia_packet_capture_step(
            device_name="eb04.lab.ash6",
            interface="Ethernet3/1/1",
            mode="save",
            pcap_filename="bgp_drain.pcap",
            capture_id="drain_phase",
        )
    """
    if description is None:
        if mode == "start":
            description = f"Start IXIA packet capture on {interface} (BGP monitor)"
        elif mode == "stop":
            description = f"Stop IXIA packet capture on {interface}"
        elif mode == "save":
            description = f"Save IXIA packet capture to {pcap_filename}"
        else:
            description = f"IXIA packet capture operation: {mode}"

    params_dict: t.Dict[str, t.Any] = {
        "hostname": device_name,
        "interface": interface,
        "mode": mode,
        "capture_filter": capture_filter,
    }

    if pcap_filename is not None:
        params_dict["pcap_filename"] = pcap_filename

    if capture_id is not None:
        params_dict["capture_id"] = capture_id

    return create_run_task_step(
        task_name="ixia_packet_capture",
        params_dict=params_dict,
        description=description,
        ixia_needed=True,
    )


def create_multipath_nexthop_count_health_check_step(
    prefix_subnets: t.Optional[t.List[str]] = None,
    expected_nexthop_count: t.Optional[int] = None,
    min_nexthop_count: t.Optional[int] = None,
    max_nexthop_count: t.Optional[int] = None,
    discover_baseline: bool = False,
    baseline_nexthop_count: t.Optional[int] = None,
    expected_min_baseline_width: t.Optional[int] = None,
    expected_max_baseline_width: t.Optional[int] = None,
    min_multipath_width: t.Optional[int] = None,
    use_discovered_prefixes: bool = False,
    use_discovered_width: bool = False,
    peers_stopped_delta: t.Optional[int] = None,
    description: t.Optional[str] = None,
) -> Step:
    """
    Create a health check step to verify BGP multipath group (next-hop count) for prefixes.

    This step runs the BgpMultipathNextHopCountHealthCheck to validate that prefixes
    have the expected number of next-hops in their multipath group. This is essential
    for verifying that BGP session oscillations correctly affect the multipath group size.

    Supports two modes:
        1. Discovery mode (discover_baseline=True): Measures the modal eBGP NH-count
           distribution and stores the prefix set + width as the baseline. Optional
           sanity bounds (expected_min/max_baseline_width) fail loudly if the
           measurement is implausible for the testbed.
        2. Validation mode (default): Validates that prefixes have the expected
           number of next-hops. With ``use_discovered_width=True``, the expected
           count is derived from the stored width minus ``peers_stopped_delta``.

    Args:
        prefix_subnets: Optional list of prefix subnets to check (e.g., ["10.0.0.0/8", "2001:db8::/32"])
        expected_nexthop_count: Optional exact number of next-hops expected
        min_nexthop_count: Optional minimum number of next-hops expected
        max_nexthop_count: Optional maximum number of next-hops expected
        discover_baseline: If True, run in discovery mode (measure baseline width)
        baseline_nexthop_count: DEPRECATED legacy exact-match selector. If supplied,
            measured width must match (sanity bound). Prefer the *_baseline_width args.
        expected_min_baseline_width: Optional lower bound for the measured width
        expected_max_baseline_width: Optional upper bound for the measured width
        min_multipath_width: Floor for distribution scan (default 2)
        use_discovered_prefixes: If True, validate against discovered baseline prefixes
        use_discovered_width: If True, derive expected_nexthop_count from the
            stored baseline width minus peers_stopped_delta
        peers_stopped_delta: Peers currently stopped (default 0 / restore phase)
        description: Custom description for the step

    Returns:
        Step object for running the BGP multipath next-hop count health check

    Example:
        # Step 1: Discover the live ECMP baseline width — testbed-portable
        discovery_step = create_multipath_nexthop_count_health_check_step(
            discover_baseline=True,
            expected_min_baseline_width=2,    # sanity: must be multipath
            expected_max_baseline_width=200,  # sanity: not an unbounded leak
            description="Discover baseline multipath group width",
        )

        # Step 2: After stopping 3 sessions, verify width drops by 3
        validation_step = create_multipath_nexthop_count_health_check_step(
            use_discovered_prefixes=True,
            use_discovered_width=True,
            peers_stopped_delta=3,
            description="Verify multipath group reduced by 3",
        )
    """
    if description is None:
        if discover_baseline:
            description = "Discover baseline multipath group width"
        elif use_discovered_width:
            if peers_stopped_delta:
                description = (
                    f"Verify multipath group reduced by {peers_stopped_delta} "
                    "(width-relative)"
                )
            else:
                description = "Verify multipath group restored to baseline width"
        elif expected_nexthop_count is not None:
            description = (
                f"Verify multipath group has exactly {expected_nexthop_count} next-hops"
            )
        elif min_nexthop_count is not None and max_nexthop_count is not None:
            description = (
                f"Verify multipath group has {min_nexthop_count}-{max_nexthop_count} "
                "next-hops"
            )
        elif min_nexthop_count is not None:
            description = (
                f"Verify multipath group has at least {min_nexthop_count} next-hops"
            )
        elif max_nexthop_count is not None:
            description = (
                f"Verify multipath group has at most {max_nexthop_count} next-hops"
            )
        else:
            description = "Verify BGP multipath group next-hop count"

    return Step(
        name=StepName.VALIDATION_STEP,
        description=description,
        input_json=thrift_to_json(
            ValidationInput(
                point_in_time_checks=[
                    create_next_hop_count_check(
                        discover_baseline=discover_baseline,
                        baseline_nexthop_count=baseline_nexthop_count,
                        expected_min_baseline_width=expected_min_baseline_width,
                        expected_max_baseline_width=expected_max_baseline_width,
                        min_multipath_width=min_multipath_width,
                        use_discovered_prefixes=use_discovered_prefixes,
                        use_discovered_width=use_discovered_width,
                        peers_stopped_delta=peers_stopped_delta,
                        prefix_subnets=prefix_subnets,
                        expected_nexthop_count=expected_nexthop_count,
                        min_nexthop_count=min_nexthop_count,
                        max_nexthop_count=max_nexthop_count,
                    )
                ],
            )
        ),
    )


def create_performance_scaling_convergence_step(
    device_name: str,
    prefix_counts: t.List[int],
    prefix_pool_regex_v6: str = "PREFIX_POOL_IPV6_EBGP",
    prefix_pool_regex_v4: str = "PREFIX_POOL_IPV4_EBGP",
    address_families: t.Optional[t.List[str]] = None,
    total_peer_count: int = 0,
    ibgp_peer_count: int = 0,
    ebgp_peer_count: int = 0,
    convergence_wait_seconds: int = 600,
    soak_seconds: int = 120,
    test_name: str = "BGP_PLUS_PLUS_PERFORMANCE_SCALING_CONVERGENCE",
    description: t.Optional[str] = None,
) -> Step:
    """
    Create a custom step that iterates all prefix counts for a given peer count,
    measures BGP convergence time for each, and plots convergence time vs prefix count.

    This replaces separate per-prefix-count playbooks with a single step that
    sequentially tests each prefix count and generates consolidated results.

    Args:
        device_name: Name of the device under test
        prefix_counts: List of prefix counts to test (e.g., [5000, 10000, 15000, 20000, 25000])
        prefix_pool_regex_v6: Regex for IPv6 prefix pool (default: "PREFIX_POOL_IPV6_EBGP")
        prefix_pool_regex_v4: Regex for IPv4 prefix pool (default: "PREFIX_POOL_IPV4_EBGP")
        address_families: Address families to advertise prefixes on. Accepts
            ["ipv4"], ["ipv6"], or ["ipv4", "ipv6"] (default).
            - ["ipv6"]:        IPv6 only — only the v6 prefix pool is touched
                               and ``total_prefixes == prefix_count`` (no x2
                               doubling). Use for IPv6-only conveyor setups
                               (e.g. bag012).
            - ["ipv4"]:        IPv4 only — only the v4 prefix pool is touched.
            - ["ipv4","ipv6"]: both AFs (legacy default) — both pools are
                               enabled and ``total_prefixes == prefix_count*2``.
        total_peer_count: Total peer count for labeling/Scuba
        ibgp_peer_count: IBGP peer count for Scuba logging
        ebgp_peer_count: EBGP peer count for Scuba logging
        convergence_wait_seconds: Maximum wait for convergence per iteration (default: 600)
        soak_seconds: Soak period after convergence per iteration (default: 120)
        test_name: Scuba logging label
        description: Custom description for the step

    Returns:
        Step object for the performance scaling convergence custom step
    """
    if description is None:
        description = (
            f"Measure convergence across prefix counts "
            f"{prefix_counts} with {total_peer_count} peers"
        )

    step_params: t.Dict[str, t.Any] = {
        "custom_step_name": "measure_performance_scaling_convergence",
        "hostname": device_name,
        "prefix_counts": prefix_counts,
        "prefix_pool_regex_v6": prefix_pool_regex_v6,
        "prefix_pool_regex_v4": prefix_pool_regex_v4,
        "total_peer_count": total_peer_count,
        "ibgp_peer_count": ibgp_peer_count,
        "ebgp_peer_count": ebgp_peer_count,
        "convergence_wait_seconds": convergence_wait_seconds,
        "soak_seconds": soak_seconds,
        "test_name": test_name,
    }
    if address_families is not None:
        step_params["address_families"] = address_families

    return Step(
        name=StepName.CUSTOM_STEP,
        description=description,
        step_params=Params(json_params=json.dumps(step_params)),
    )


def create_performance_scaling_egress_sweep_aggregator_step(
    test_name: str = "BGP_PLUS_PLUS_PERFORMANCE_SCALING_CONVERGENCE",
    prefix_count: t.Optional[int] = None,
    description: t.Optional[str] = None,
) -> Step:
    """
    Create a custom step that aggregates per-stage convergence results from
    a single Playbook's egress-peer sweep and produces ONE consolidated plot
    showing convergence-time vs total-peer-count.

    The companion ``aggregate_performance_scaling_egress_sweep_plot`` custom
    step reads every ``performance_scaling_<N>_peers`` entry from
    ``CustomStep._convergence_data_storage`` (populated by each per-Stage
    ``measure_performance_scaling_convergence`` run) and renders one chart
    with N data points (one per egress peer-count Stage).

    Args:
        test_name: Scuba logging label (matches the per-stage convergence
            step's ``test_name`` for cross-referencing).
        prefix_count: When the per-Stage convergence step iterated multiple
            prefix counts, pick which one to plot. When ``None`` (default)
            and only one prefix count was tested per Stage, that single
            value is used automatically.
        description: Custom description for the step.

    Returns:
        Step object for the egress-sweep aggregator custom step.
    """
    if description is None:
        description = (
            "Aggregate per-Stage convergence results into a single plot"
            " of convergence-time vs total-peer-count"
        )
    step_params: t.Dict[str, t.Any] = {
        "custom_step_name": "aggregate_performance_scaling_egress_sweep_plot",
        "test_name": test_name,
    }
    if prefix_count is not None:
        step_params["prefix_count"] = prefix_count
    return Step(
        name=StepName.CUSTOM_STEP,
        description=description,
        step_params=Params(json_params=json.dumps(step_params)),
    )


# =============================================================================
# EBB BGP++ TEST SETUP STEP HELPERS
# =============================================================================


def create_standard_setup_steps(
    device_name: str,
    disable_all_device_groups: bool = True,
    enable_all_device_groups: bool = False,
    enable_bgp_daemon: bool = True,
    daemon_name: str = "Bgp",
    validate_device_group_toggle: bool = False,
) -> t.List[Step]:
    """
    Create standard setup steps for BGP tests.

    Args:
        device_name: Name of the device
        disable_all_device_groups: Whether to disable all Ixia device groups
        enable_all_device_groups: Whether to enable all Ixia device groups (takes precedence over disable)
        enable_bgp_daemon: Whether to enable BGP daemon
        daemon_name: Name of the daemon to enable
        validate_device_group_toggle: Require a nonempty device-group match and
            verify the Enabled readback after each IXIA toggle.

    Returns:
        List of standard setup steps
    """
    steps = []

    if enable_all_device_groups:
        steps.append(
            create_ixia_device_group_toggle_step(
                enable=True,
                device_group_name_regex=".*",
                description="Enable all device groups for established sessions",
                require_match=validate_device_group_toggle,
                verify_readback=validate_device_group_toggle,
            )
        )
    elif disable_all_device_groups:
        steps.append(
            create_ixia_device_group_toggle_step(
                enable=False,
                device_group_name_regex=".*",
                description="Disable all device groups",
                require_match=validate_device_group_toggle,
                verify_readback=validate_device_group_toggle,
            )
        )

    if enable_bgp_daemon:
        steps.append(
            create_daemon_control_step(
                device_name=device_name,
                daemon_name=daemon_name,
                action="enable",
                description=f"Enable {daemon_name} daemon",
            )
        )

    return steps


def create_bgp_restart_setup_steps(
    device_name: str,
    *,
    start_with_active_peers: bool = False,
    expected_established_sessions: int | None = None,
    parent_prefixes_to_ignore: t.Sequence[str] = (),
    readiness_hard_timeout_seconds: float = 600,
    readiness_poll_interval_seconds: float = 5,
    validate_device_group_toggle: bool = False,
) -> t.List[Step]:
    """
    Create setup steps specifically for BGP restart tests.

    Args:
        device_name: Name of the device
        start_with_active_peers: Enable all IXIA device groups and wait for BGP
            readiness instead of beginning with device groups disabled.
        expected_established_sessions: Exact established-session count required
            when ``start_with_active_peers`` is enabled.
        parent_prefixes_to_ignore: Parent prefixes excluded from BGP readiness
            validation.
        readiness_hard_timeout_seconds: Maximum time to wait for BGP readiness.
        readiness_poll_interval_seconds: Interval between readiness checks.
        validate_device_group_toggle: Require a nonempty device-group match and
            verify the Enabled readback after each IXIA toggle.

    Returns:
        List of setup steps for BGP restart tests
    """
    steps = create_standard_setup_steps(
        device_name=device_name,
        disable_all_device_groups=not start_with_active_peers,
        enable_all_device_groups=start_with_active_peers,
        enable_bgp_daemon=True,
        validate_device_group_toggle=validate_device_group_toggle,
    )
    if start_with_active_peers:
        if expected_established_sessions is None:
            raise ValueError(
                "expected_established_sessions is required for active-peer setup"
            )
        steps.append(
            create_bgp_lifecycle_convergence_step(
                device_name=device_name,
                expected_established_sessions=expected_established_sessions,
                parent_prefixes_to_ignore=parent_prefixes_to_ignore,
                require_initialized=True,
                convergence_hard_timeout_seconds=readiness_hard_timeout_seconds,
                convergence_poll_interval_seconds=readiness_poll_interval_seconds,
                description="Wait for exact steady-state BGP readiness",
            )
        )
    return steps


def create_bgp_instability_setup_steps(
    device_name: str, convergence_wait_seconds: int = 300
) -> t.List[Step]:
    """
    Create setup steps for BGP instability tests where sessions should be pre-established.

    This setup ensures BGP daemon is enabled and device groups are active,
    then waits for full BGP convergence before the instability test begins.

    Args:
        device_name: Name of the device
        convergence_wait_seconds: Time to wait for BGP convergence (default: 5 minutes)

    Returns:
        List of setup steps for BGP instability tests
    """
    steps = create_standard_setup_steps(
        device_name=device_name,
        enable_all_device_groups=True,
        enable_bgp_daemon=True,
    )

    steps.append(
        create_longevity_step(
            duration=convergence_wait_seconds,
            description=f"Wait for BGP session establishment and convergence ({convergence_wait_seconds}s)",
        )
    )

    return steps


def create_route_registry_prefix_list_setup_steps(
    device_name: str,
    convergence_wait_seconds: int = 300,
    prefix_start_index: int = 0,
    prefix_end_index: int = 100,
    baseline_policy_path: str = "taac/test_bgp_policies/ebb_route_registry_prefix_list_650.json",
    expected_route_count: int | None = None,
    convergence_soft_threshold_seconds: float | None = None,
    convergence_hard_timeout_seconds: float | None = None,
    convergence_poll_interval_seconds: float | None = None,
) -> t.List[Step]:
    """
    Create setup steps for BGP route registry prefix list runtime update testing.

    These setup steps establish the baseline state before runtime policy updates.
    The adaptive path disables the test slice and loads the baseline policy
    before peer startup, then polls the exact baseline count. Legacy callers
    retain the original startup, fixed wait, withdrawal, and policy order.

    Args:
        device_name: Name of the device
        convergence_wait_seconds: Time to wait for BGP convergence (default: 5 minutes)
        prefix_start_index: First runtime-update prefix index (inclusive)
        prefix_end_index: Last runtime-update prefix index (exclusive)
        baseline_policy_path: Route-filter policy that excludes the test slice
        expected_route_count: Optional exact baseline count to observe
        convergence_soft_threshold_seconds: Optional exact-count SLA
        convergence_hard_timeout_seconds: Optional observation timeout
        convergence_poll_interval_seconds: Optional polling interval

    Returns:
        List of setup steps for route registry prefix list runtime update tests
    """
    convergence_params = (
        convergence_soft_threshold_seconds,
        convergence_hard_timeout_seconds,
        convergence_poll_interval_seconds,
    )
    convergence_enabled = any(value is not None for value in convergence_params)
    if convergence_enabled and (
        expected_route_count is None
        or not all(value is not None for value in convergence_params)
    ):
        raise ValueError(
            "expected_route_count and all convergence parameters must be "
            "provided together"
        )
    standard_steps = create_standard_setup_steps(
        device_name=device_name,
        enable_all_device_groups=True,
        enable_bgp_daemon=True,
    )
    default_policy_path = (
        "taac/test_bgp_policies/ebb_route_registry_prefix_list_650.json"
    )
    withdraw_description = (
        "Withdraw 100 prefixes (0-100) that will be tested for runtime updates"
        if prefix_start_index == 0 and prefix_end_index == 100
        else f"Withdraw {prefix_end_index - prefix_start_index} prefixes "
        f"({prefix_start_index}-{prefix_end_index}) that will be tested for runtime updates"
    )
    policy_description = (
        "Load baseline route filter policy without test prefixes "
        "(RP state file 650.json)"
        if baseline_policy_path == default_policy_path
        else f"Load baseline route filter policy without test prefixes ({baseline_policy_path})"
    )

    withdraw_step = create_advertise_withdraw_prefixes_step(
        device_name=device_name,
        advertise=False,
        prefix_pool_regex=".*EBGP.*",
        prefix_start_index=prefix_start_index,
        prefix_end_index=prefix_end_index,
        description=withdraw_description,
    )
    baseline_policy_step = create_set_route_filter_step(
        device_name=device_name,
        config_path=baseline_policy_path,
        description=policy_description,
    )

    if convergence_enabled:
        steps = [withdraw_step, baseline_policy_step, *standard_steps]
        steps.append(
            create_verify_received_routes_step(
                device_name=device_name,
                descriptions_to_check=["EBGP"],
                expected_count=expected_route_count,
                convergence_soft_threshold_seconds=(convergence_soft_threshold_seconds),
                convergence_hard_timeout_seconds=(convergence_hard_timeout_seconds),
                convergence_poll_interval_seconds=(convergence_poll_interval_seconds),
                description=f"Observe exact baseline route-count convergence to {expected_route_count}",
            )
        )
    else:
        steps = [
            *standard_steps,
            create_longevity_step(
                duration=convergence_wait_seconds,
                description=f"Wait for BGP session establishment and convergence ({convergence_wait_seconds}s)",
            ),
            withdraw_step,
            baseline_policy_step,
        ]

    return steps


def create_sc_8_setup_steps(
    device_name: str,
    configerator_path: str = "taac/arista_performance_scaling_test_bgpcpp_configs/bgpcpp_config_test_case8_eb_fa_in_no_prefix",
) -> t.List[Step]:
    """
    Create setup steps for SC8 BGP tests that load config and restart BGP.

    Args:
        device_name: Name of the device
        configerator_path: Path to configerator file for BGP config

    Returns:
        List of setup steps for loading config and restarting BGP
    """
    daemon_name = "BGP"
    steps = []

    steps.append(
        create_daemon_control_step(
            device_name=device_name,
            daemon_name=daemon_name,
            action="disable",
            description=f"Disable {daemon_name} daemon",
        )
    )

    steps.append(
        create_advertise_withdraw_prefixes_step(
            device_name=device_name,
            advertise=False,
            prefix_pool_regex="PREFIX_POOL_IPV4_EBGP",
            prefix_start_index=0,
        )
    )
    steps.append(
        create_advertise_withdraw_prefixes_step(
            device_name=device_name,
            advertise=False,
            prefix_pool_regex="PREFIX_POOL_IPV6_EBGP",
            prefix_start_index=0,
        )
    )

    steps.append(
        create_file_from_config_step(
            device_name=device_name,
            configerator_path=configerator_path,
            file_path="/mnt/flash/new_config.json",
            description="Load BGP config from configerator",
        )
    )

    steps.append(
        create_run_commands_on_shell_step(
            device_name=device_name,
            cmds=["bash sudo cp /mnt/flash/new_config.json /mnt/flash/bgpcpp_config"],
            description="Copy BGP config to bgpcpp_config location",
        )
    )

    steps.append(
        create_daemon_control_step(
            device_name=device_name,
            daemon_name=daemon_name,
            action="enable",
            description=f"Enable {daemon_name} daemon",
        )
    )

    steps.append(
        create_longevity_step(
            duration=300,
            description="Wait for BGP session establishment and convergence",
        )
    )

    return steps


def create_sc_8_steps(
    device_name: str,
    prefix_count: int = 10000,
    policy_name: str = "EB-FA-IN",
    plot_policy_stats: bool = False,
) -> t.List[Step]:
    """
    Create test steps for SC8 BGP tests (excluding setup steps).

    This includes advertising prefixes, waiting for convergence,
    verifying routes, and printing policy statistics.

    Args:
        device_name: Name of the device
        prefix_count: Number of prefixes to advertise
        policy_name: Name of policy to look at
        plot_policy_stats: Whether to generate a plot of policy stats (default: False)

    Returns:
        List of test steps
    """
    steps = []
    daemon_name = "Bgp"

    steps.append(
        create_daemon_control_step(
            device_name=device_name,
            daemon_name=daemon_name,
            action="disable",
            description=f"Enable {daemon_name} daemon",
        )
    )

    steps.append(
        create_advertise_withdraw_prefixes_step(
            device_name=device_name,
            advertise=True,
            prefix_pool_regex="PREFIX_POOL_IPV4_EBGP",
            prefix_start_index=0,
            prefix_end_index=prefix_count,
            description=f"Advertise {prefix_count} v4 prefixes to EBGP peers",
        ),
    )

    steps.append(
        create_advertise_withdraw_prefixes_step(
            device_name=device_name,
            advertise=True,
            prefix_pool_regex="PREFIX_POOL_IPV6_EBGP",
            prefix_start_index=0,
            prefix_end_index=prefix_count,
            description=f"Advertise {prefix_count} v6 prefixes to EBGP peers",
        ),
    )

    steps.append(
        create_daemon_control_step(
            device_name=device_name,
            daemon_name=daemon_name,
            action="enable",
            description=f"Enable {daemon_name} daemon",
        )
    )

    steps.append(
        create_longevity_step(
            duration=300,
            description="Wait for BGP session establishment and convergence",
        )
    )

    steps.append(
        create_verify_received_routes_step(
            device_name=device_name,
            expected_count=prefix_count,
            direction="received",
            policy_type="post_policy",
            description=f"Verify received post-policy routes count is {prefix_count}",
        ),
    )

    steps.append(
        Step(
            name=StepName.CUSTOM_STEP,
            description="Print policy statistics for EB-FA-IN policies",
            step_params=Params(
                json_params=json.dumps(
                    {
                        "custom_step_name": "print_policy_stats",
                        "name": policy_name,
                        "prefix_count": prefix_count,
                        "plot": plot_policy_stats,
                    }
                ),
            ),
        )
    )

    return steps


# =============================================================================
# GENERIC PATCHER STEPS
# =============================================================================


def create_unregister_patcher_step(
    patcher_name: str,
    config_name: str = "agent",
    description: t.Optional[str] = None,
    device_regexes: t.Optional[t.List[str]] = None,
) -> Step:
    """
    Create a step to unregister a COOP patcher.

    Args:
        patcher_name: Name of the patcher to unregister
        config_name: Config the patcher is registered against (default: "agent")
        description: Custom description for the step

    Returns:
        Step object that unregisters the patcher
    """
    return Step(
        name=StepName.REGISTER_PATCHER_STEP,
        input_json=thrift_to_json(
            taac_types.RegisterPatcherInput(
                register_patcher=False,
                name=patcher_name,
                config_name=config_name,
            )
        ),
        device_regexes=device_regexes,
        description=description or f"Unregister patcher '{patcher_name}'",
    )


def create_register_patcher_step(
    patcher_name: str,
    py_func_name: str,
    kwargs: dict[str, str],
    config_name: str = "agent",
    description: t.Optional[str] = None,
    device_regexes: t.Optional[t.List[str]] = None,
) -> Step:
    """
    Create a step to register a COOP patcher.
    """
    return Step(
        name=StepName.REGISTER_PATCHER_STEP,
        input_json=thrift_to_json(
            taac_types.RegisterPatcherInput(
                register_patcher=True,
                name=patcher_name,
                py_func_name=py_func_name,
                kwargs=kwargs,
                config_name=config_name,
            )
        ),
        device_regexes=device_regexes,
        description=description or f"Register patcher '{patcher_name}'",
    )


# =============================================================================
# LOOPBACK SHUTDOWN STEPS
# =============================================================================


def create_shutdown_loopback_step(
    register_patcher: bool = True,
    loopback_name: str = "fbossLoopback0",
    patcher_name: str = "shutdown_loopback_test",
    description: t.Optional[str] = None,
) -> Step:
    """
    Create a step to shut or unshut a loopback interface via the COOP
    shutdown_loopback patcher. Used for NHT convergence testing.

    When register_patcher=True (shut): removes all IP addresses from the
    loopback in the FBOSS agent config, making it unreachable.

    When register_patcher=False (unshut): unregisters the patcher so COOP
    regenerates the original config with loopback IPs restored.

    Args:
        register_patcher: True to shut loopback, False to restore it
        loopback_name: Name of the loopback interface (default: fbossLoopback0)
        patcher_name: Name to register/unregister the patcher as
        description: Custom description for the step

    Returns:
        Step object that registers or unregisters the shutdown_loopback patcher
    """
    if register_patcher:
        return Step(
            name=StepName.REGISTER_PATCHER_STEP,
            input_json=thrift_to_json(
                taac_types.RegisterPatcherInput(
                    register_patcher=True,
                    config_name="agent",
                    name=patcher_name,
                    py_func_name="shutdown_loopback",
                    kwargs={"loopback_name": loopback_name},
                    description=description or f"Shutdown loopback {loopback_name}",
                )
            ),
            description=description or f"Shutdown loopback {loopback_name}",
        )
    else:
        return Step(
            name=StepName.REGISTER_PATCHER_STEP,
            input_json=thrift_to_json(
                taac_types.RegisterPatcherInput(
                    register_patcher=False,
                    config_name="agent",
                    name=patcher_name,
                )
            ),
            description=description or "Restore loopback (unregister patcher)",
        )


def create_interface_permanent_flap_step(
    interfaces: list[str],
    register_patcher: bool = True,
    enable: bool = True,
    patcher_name: str = "permanently_disable_interface_patcher",
    description: t.Optional[str] = "Permanently disable interface",
) -> Step:
    """
    Create a step to shut or unshut a interface via the COOP
    change_port_admin_state patcher.

    Args:
        register_patcher: True to shut interface, False to restore it
        interfaces: Name of the interface
        patcher_name: Name to register/unregister the patcher as (default: permanently_disable_interface_patcher)
        description: Custom description for the step

    returns:
        Step object that registers or unregisters the permanently_disable_interface_patcher patcher
    """
    kwargs = {}
    for interface in interfaces:
        kwargs[interface] = "enable" if enable else "disable"

    if register_patcher:
        return Step(
            name=StepName.REGISTER_PATCHER_STEP,
            input_json=thrift_to_json(
                taac_types.RegisterPatcherInput(
                    register_patcher=True,
                    config_name="agent",
                    name=patcher_name,
                    py_func_name="change_port_admin_state",
                    kwargs=kwargs,
                    description=description,
                )
            ),
        )
    else:
        return Step(
            name=StepName.REGISTER_PATCHER_STEP,
            input_json=thrift_to_json(
                taac_types.RegisterPatcherInput(
                    register_patcher=False,
                    config_name="agent",
                    name=patcher_name,
                )
            ),
        )


# =============================================================================
# OPENR PATCHER STEPS
# =============================================================================


def _create_openr_patcher_step(
    py_func_name: str,
    kwargs: t.Dict[str, str],
    patcher_name: t.Optional[str],
    description: t.Optional[str],
    register_patcher: bool = True,
) -> Step:
    if patcher_name is None:
        patcher_name = f"{py_func_name}_config"

    if not register_patcher:
        return Step(
            name=StepName.REGISTER_PATCHER_STEP,
            input_json=thrift_to_json(
                taac_types.RegisterPatcherInput(
                    register_patcher=False,
                    config_name="openr",
                    name=patcher_name,
                )
            ),
        )

    return Step(
        name=StepName.REGISTER_PATCHER_STEP,
        input_json=thrift_to_json(
            taac_types.RegisterPatcherInput(
                register_patcher=True,
                config_name="openr",
                name=patcher_name,
                py_func_name=py_func_name,
                kwargs=kwargs,
                description=description,
            )
        ),
    )


def create_update_openr_area_id_step(
    area_updates: t.List[t.Dict[str, str]],
    register_patcher: bool = True,
    patcher_name: str = "update_openr_area_id_config",
    description: t.Optional[str] = "Update OpenR area IDs",
) -> Step:
    """
    Create a step to update OpenR area IDs via the COOP update_openr_area_id
    patcher. Used for OpenR Qualification.

    When register_patcher=True (update): registers the patcher with the given
    area updates, which will be applied to the OpenR config.

    When register_patcher=False (restore): unregisters the patcher so COOP
    regenerates the original config with the original area IDs.

    Args:
        area_updates: List of area updates to apply
            Format:
                area_updates = [
                    {
                        "old_area_id": "area1",
                        "new_area_id": "area2",
                    },
                    {
                        "old_area_id": "area3",
                        "new_area_id": "area4",
                    },
                ]
        register_patcher: True to update area IDs, False to restore them
        patcher_name: Name to register/unregister the patcher as
        description: Custom description for the step

    Returns:
        Step object that registers or unregisters the update_openr_area_id patcher


    Patcher takes input in the form of comma-separated key-value pairs.
    Example:
        Above area_updates would be passed as:
        "area_map": "area1:area2,area3:area4"
    """
    if register_patcher:
        if area_updates is None or len(area_updates) == 0:
            raise ValueError(
                "No area updates provided for update_openr_area_id patcher. Provide the input as a list of dictionaries with keys 'old_area_id' and 'new_area_id' for each area update. Example: [{'old_area_id': 'area1', 'new_area_id': 'area2'}, {'old_area_id': 'area3', 'new_area_id': 'area4'}]"
            )

        area_map = []
        for update in area_updates:
            if "old_area_id" not in update or "new_area_id" not in update:
                raise ValueError(
                    "Invalid area update provided. Each update must have keys 'old_area_id' and 'new_area_id'. Example: [{'old_area_id': 'area1', 'new_area_id': 'area2'}, {'old_area_id': 'area3', 'new_area_id': 'area4'}]"
                )
            area_map.append(f"{update['old_area_id']}:{update['new_area_id']}")
        kwargs = {"area_map": ",".join(area_map)}
    else:
        kwargs = {}

    return _create_openr_patcher_step(
        py_func_name="update_openr_area_id",
        kwargs=kwargs,
        register_patcher=register_patcher,
        patcher_name=patcher_name,
        description=description,
    )


def create_update_openr_watchdog_step(
    register_patcher: bool = True,
    interval_s: t.Optional[str] = None,
    thread_timeout_s: t.Optional[str] = None,
    max_memory_mb: t.Optional[str] = None,
    patcher_name: str = "update_openr_watchdog_config",
    description: t.Optional[str] = "Update OpenR watchdog config",
) -> Step:
    """
    Create a step to update OpenR watchdog config via the COOP
    update_openr_watchdog patcher.

    Only updates fields that are explicitly provided; others are left unchanged.
    Always enables watchdog.

    Args:
        register_patcher: True to update watchdog, False to restore
        interval_s: Watchdog check interval in seconds
        thread_timeout_s: Thread timeout in seconds
        max_memory_mb: Max memory in MB
        patcher_name: Name to register/unregister the patcher as
        description: Custom description for the step
    """
    kwargs = {}
    if interval_s is not None:
        kwargs["interval_s"] = interval_s
    if thread_timeout_s is not None:
        kwargs["thread_timeout_s"] = thread_timeout_s
    if max_memory_mb is not None:
        kwargs["max_memory_mb"] = max_memory_mb

    if register_patcher and not kwargs:
        raise ValueError(
            "At least one of 'interval_s', 'thread_timeout_s', or 'max_memory_mb' "
            "must be provided for update_openr_watchdog patcher."
        )

    return _create_openr_patcher_step(
        py_func_name="update_openr_watchdog",
        kwargs=kwargs,
        register_patcher=register_patcher,
        patcher_name=patcher_name,
        description=description,
    )


def create_update_openr_kvstore_key_ttl_step(
    register_patcher: bool = True,
    key_ttl_ms: t.Optional[str] = None,
    patcher_name: str = "update_openr_kvstore_key_ttl_config",
    description: t.Optional[str] = "Update OpenR kvstore key TTL",
) -> Step:
    """
    Create a step to update OpenR kvstore key TTL via the COOP
    update_openr_kvstore_key_ttl patcher.

    Args:
        register_patcher: True to update key TTL, False to restore
        key_ttl_ms: Key TTL in milliseconds
        patcher_name: Name to register/unregister the patcher as
        description: Custom description for the step
    """
    if register_patcher and not key_ttl_ms:
        raise ValueError(
            "'key_ttl_ms' must be provided for update_openr_kvstore_key_ttl patcher."
        )

    return _create_openr_patcher_step(
        py_func_name="update_openr_kvstore_key_ttl",
        kwargs={"key_ttl_ms": key_ttl_ms} if key_ttl_ms else {},
        register_patcher=register_patcher,
        patcher_name=patcher_name,
        description=description,
    )


def create_update_openr_spark_gr_timer_step(
    register_patcher: bool = True,
    graceful_restart_time_s: t.Optional[str] = None,
    patcher_name: str = "update_openr_spark_gr_timer_config",
    description: t.Optional[str] = "Update OpenR spark GR timer",
) -> Step:
    """
    Create a step to update OpenR spark graceful restart timer via the COOP
    update_openr_spark_gr_timer patcher.

    Args:
        register_patcher: True to update GR timer, False to restore
        graceful_restart_time_s: Graceful restart time in seconds
        patcher_name: Name to register/unregister the patcher as
        description: Custom description for the step
    """
    if register_patcher and not graceful_restart_time_s:
        raise ValueError(
            "'graceful_restart_time_s' must be provided for "
            "update_openr_spark_gr_timer patcher."
        )

    return _create_openr_patcher_step(
        py_func_name="update_openr_spark_gr_timer",
        kwargs=(
            {"graceful_restart_time_s": graceful_restart_time_s}
            if graceful_restart_time_s
            else {}
        ),
        register_patcher=register_patcher,
        patcher_name=patcher_name,
        description=description,
    )


def create_update_openr_decision_debounce_step(
    register_patcher: bool = True,
    debounce_min_ms: t.Optional[str] = None,
    debounce_max_ms: t.Optional[str] = None,
    patcher_name: str = "update_openr_decision_debounce_config",
    description: t.Optional[str] = "Update OpenR decision debounce timers",
) -> Step:
    """
    Create a step to update OpenR decision debounce timers via the COOP
    update_openr_decision_debounce patcher.

    Only updates fields that are explicitly provided; others are left unchanged.

    Args:
        register_patcher: True to update debounce timers, False to restore
        debounce_min_ms: Minimum debounce time in milliseconds
        debounce_max_ms: Maximum debounce time in milliseconds
        patcher_name: Name to register/unregister the patcher as
        description: Custom description for the step
    """
    kwargs = {}
    if debounce_min_ms is not None:
        kwargs["debounce_min_ms"] = debounce_min_ms
    if debounce_max_ms is not None:
        kwargs["debounce_max_ms"] = debounce_max_ms

    if register_patcher and not kwargs:
        raise ValueError(
            "At least one of 'debounce_min_ms' or 'debounce_max_ms' "
            "must be provided for update_openr_decision_debounce patcher."
        )

    return _create_openr_patcher_step(
        py_func_name="update_openr_decision_debounce",
        kwargs=kwargs,
        register_patcher=register_patcher,
        patcher_name=patcher_name,
        description=description,
    )


def create_update_openr_link_monitor_config_step(
    register_patcher: bool = True,
    linkflap_initial_backoff_ms: t.Optional[str] = None,
    linkflap_max_backoff_ms: t.Optional[str] = None,
    use_rtt_metric: t.Optional[str] = None,
    enable_perf_measurement: t.Optional[str] = None,
    enable_link_status_measurement: t.Optional[str] = None,
    patcher_name: str = "update_openr_link_monitor_config_config",
    description: t.Optional[str] = "Update OpenR link monitor config",
) -> Step:
    """
    Create a step to update OpenR link_monitor_config fields via the COOP
    update_openr_link_monitor_config patcher.

    Only updates fields that are explicitly provided; others are left unchanged.

    Args:
        register_patcher: True to update link monitor config, False to restore
        linkflap_initial_backoff_ms: Initial backoff time in milliseconds
        linkflap_max_backoff_ms: Maximum backoff time in milliseconds
        use_rtt_metric: Whether to use RTT as a link metric ("true"/"false")
        enable_perf_measurement: Enable convergence perf measurement ("true"/"false")
        enable_link_status_measurement: Enable link status measurement ("true"/"false")
        patcher_name: Name to register/unregister the patcher as
        description: Custom description for the step
    """
    field_map: t.Dict[str, t.Optional[str]] = {
        "linkflap_initial_backoff_ms": linkflap_initial_backoff_ms,
        "linkflap_max_backoff_ms": linkflap_max_backoff_ms,
        "use_rtt_metric": use_rtt_metric,
        "enable_perf_measurement": enable_perf_measurement,
        "enable_link_status_measurement": enable_link_status_measurement,
    }
    kwargs = {k: v for k, v in field_map.items() if v is not None}

    if register_patcher and not kwargs:
        raise ValueError(
            "At least one link_monitor_config field must be provided. "
            f"Valid fields: {sorted(field_map.keys())}"
        )

    return _create_openr_patcher_step(
        py_func_name="update_openr_link_monitor_config",
        kwargs=kwargs,
        register_patcher=register_patcher,
        patcher_name=patcher_name,
        description=description,
    )


# =============================================================================
# CTE UCMP STEPS (migrated from routing/cte_ucmp_test_configs/cte_ucmp_common_steps.py)
# Helper factories for CTE UCMP DC bring-up scenarios — wrap the generic
# factories above with CTE UCMP-specific defaults / descriptions.
# =============================================================================


def create_enable_dc_vip_step(dc_number: int) -> Step:
    """Enable the IXIA advertiser device group for one DC.

    Activates the device group named `.*DC{N}_ADVERTISER`, which causes
    the IXIA to begin advertising both VIP and non-VIP prefixes for that
    DC. Used by CTE UCMP DC bring-up scenarios to script a controlled
    multi-DC convergence sequence.

    Args:
        dc_number: DC index (1, 2, 3) corresponding to the
            `DC{N}_ADVERTISER` device-group naming convention.

    Returns:
        A `Step` with `step_name=StepName.INVOKE_IXIA_API_STEP` calling
        `toggle_device_groups` with `enable=True`.
    """
    return create_ixia_api_step(
        api_name="toggle_device_groups",
        args_dict={
            "device_group_name_regex": f".*DC{dc_number}_ADVERTISER",
            "enable": True,
        },
        description=f"Enable DC{dc_number} device group for VIP and non-VIP advertisements",
    )


def create_enable_dc_all_step(dc_number: int) -> Step:
    """Enable every IXIA advertiser device group belonging to one DC.

    Broader-match variant of `create_enable_dc_vip_step`: matches
    `.*DC{N}.*ADVERTISER.*` so it activates all advertiser groups
    associated with the DC, including any subgroups beyond the primary
    `_ADVERTISER` group. Used in CTE UCMP DC bring-up.

    Args:
        dc_number: DC index (1, 2, 3) used to build the regex.

    Returns:
        A `Step` with `step_name=StepName.INVOKE_IXIA_API_STEP` calling
        `toggle_device_groups` with `enable=True`.
    """
    return create_ixia_api_step(
        api_name="toggle_device_groups",
        args_dict={
            "device_group_name_regex": f".*DC{dc_number}.*ADVERTISER.*",
            "enable": True,
        },
        description=f"Enable DC{dc_number} all device groups (VIP + non-VIP)",
    )


def create_disable_dc_vip_step(dc_number: int) -> Step:
    """Disable the IXIA advertiser device group for one DC.

    Inverse of `create_enable_dc_vip_step`: deactivates `.*DC{N}_ADVERTISER`
    so the IXIA withdraws both VIP and non-VIP advertisements for that
    DC, simulating a DC drain. Used in CTE UCMP DC drain/undrain
    scenarios to drive the DUT through controlled convergence events.

    Args:
        dc_number: DC index (1, 2, 3) used to build the regex.

    Returns:
        A `Step` with `step_name=StepName.INVOKE_IXIA_API_STEP` calling
        `toggle_device_groups` with `enable=False`.
    """
    return create_ixia_api_step(
        api_name="toggle_device_groups",
        args_dict={
            "device_group_name_regex": f".*DC{dc_number}_ADVERTISER",
            "enable": False,
        },
        description=f"Disable DC{dc_number} device group (withdraw all advertisements)",
    )


def create_record_agent_state_step(service: str = "wedge_agent") -> Step:
    """Snapshot the FBOSS agent's PID/uptime/status into the jq context.

    Captures the current state of the named agent (default: `wedge_agent`)
    so a follow-up `create_verify_agent_restarted_step` can compare and
    confirm the process restarted. FBOSS-only — relies on the
    RecordAgentStateStepImpl custom step which queries systemd. Typically
    paired with a warmboot/coldboot trigger between record and verify.

    Args:
        service: Name of the systemd service to snapshot. Default
            `wedge_agent`.

    Returns:
        A `Step` with `step_name=StepName.CUSTOM_STEP` dispatching to
        `RecordAgentStateStepImpl`.
    """
    return create_custom_step(
        params_dict={
            "custom_step_name": "RecordAgentStateStepImpl",
            "service_name": service,
        },
        description=f"Record {service} state (PID, uptime, status)",
    )


def create_verify_bgp_uptime_stable_step(tolerance_seconds: int = 30) -> Step:
    """Assert BGP session uptimes did not regress within a tolerance window.

    Compares current BGP session uptimes against a previously-recorded
    snapshot and fails if any session's uptime dropped (which would
    indicate it flapped). Used to confirm that a disruptive operation
    (e.g. warmboot) did not unexpectedly cause BGP sessions to re-establish.

    Args:
        tolerance_seconds: Allowed slack in the uptime comparison
            (default 30s). Sessions whose uptime regressed by more than
            this margin trigger a failure.

    Returns:
        A `Step` with `step_name=StepName.CUSTOM_STEP` dispatching to
        `VerifyBgpUptimeStableStepImpl`.
    """
    return create_custom_step(
        params_dict={
            "custom_step_name": "VerifyBgpUptimeStableStepImpl",
            "tolerance_seconds": tolerance_seconds,
        },
        description=f"Verify BGP session uptimes stable (tolerance: {tolerance_seconds}s)",
    )


def create_verify_agent_restarted_step(
    max_uptime_seconds: int = 300,
    service: str = "wedge_agent",
) -> Step:
    """Assert the FBOSS agent restarted recently (uptime below threshold).

    Pairs with `create_record_agent_state_step` to confirm a warmboot or
    coldboot trigger actually caused the agent process to restart.
    Failure indicates the trigger did not take effect (e.g. systemd
    declined the restart, or the wrong service was hit). FBOSS-only.

    Args:
        max_uptime_seconds: Maximum acceptable agent uptime (in seconds)
            for the assertion to pass. Default 300s.
        service: Name of the systemd service to check. Default
            `wedge_agent`.

    Returns:
        A `Step` with `step_name=StepName.CUSTOM_STEP` dispatching to
        `VerifyAgentRestartedStepImpl`.
    """
    return create_custom_step(
        params_dict={
            "custom_step_name": "VerifyAgentRestartedStepImpl",
            "max_uptime_seconds": max_uptime_seconds,
            "service_name": service,
        },
        description=f"Verify {service} restarted (uptime < {max_uptime_seconds}s)",
    )


def create_service_interption_step(service: str = "SYSTEMCTL_RESTART") -> Step:
    """Trigger FBOSS agent warmboot/coldboot restart via service interruption.

    NOTE: name retains historical typo ("interption") for source compatibility.
    """
    if service == "COLD_BOOT":
        return create_service_interruption_step(
            service=taac_types.Service.AGENT,
            create_cold_boot_file=True,
        )
    return create_service_interruption_step(
        service=taac_types.Service.AGENT,
        description="Triggering the agent Warmboot",
    )


def create_bgp_convergence_wait_step(wait_seconds: int = 30) -> Step:
    """Sleep `wait_seconds` to let BGP reconverge after a topology change.

    Thin semantic wrapper over `create_longevity_step` that signals the
    pause's purpose in test logs. Use after operations that perturb BGP
    (interface flap, peer drain, route advertisement) and before
    downstream verification steps that assume steady state.

    Args:
        wait_seconds: Hold time in seconds. Default 30s.

    Returns:
        A `Step` with `step_name=StepName.LONGEVITY_STEP`.
    """
    return create_longevity_step(
        duration=wait_seconds,
        description=f"Wait for BGP convergence ({wait_seconds}s)",
    )


def create_traffic_duration_step(duration_seconds: int = 300) -> Step:
    """Hold the test for `duration_seconds` while traffic runs.

    Thin semantic wrapper over `create_longevity_step` used in IXIA
    traffic-driven tests to mark a steady-state window during which
    traffic counters accumulate before being sampled.

    Args:
        duration_seconds: Hold time in seconds. Default 300s.

    Returns:
        A `Step` with `step_name=StepName.LONGEVITY_STEP`.
    """
    return create_longevity_step(
        duration=duration_seconds,
        description=f"Run traffic for {duration_seconds}s",
    )


def create_clear_traffic_stats_step() -> Step:
    """Zero out IXIA traffic counters before a measurement window.

    Wraps the IXIA `clear_traffic_stats` API. Run after a topology change
    or convergence event so the next packet-loss / throughput check
    measures only the post-change window rather than including pre-change
    transients. IXIA-required.

    Returns:
        A `Step` with `step_name=StepName.INVOKE_IXIA_API_STEP` calling
        `clear_traffic_stats`.
    """
    return create_ixia_api_step(
        api_name="clear_traffic_stats",
        args_dict={},
        description="Clear traffic statistics",
    )


def create_cte_ucmp_interface_flap_step(
    neighbor_hostname: str,
    num_interfaces: int,
    enable: bool,
    interface_flap_method: int = 1,
    cache_name: t.Optional[str] = None,
    use_cached_interfaces: bool = False,
) -> Step:
    """Flap a sample of DUT interfaces facing one specific neighbor.

    CTE UCMP variant of `create_interface_flap_step`: builds the jq /
    transform parameters that select `num_interfaces` random interfaces
    on the DUT facing `neighbor_hostname`. Used to bring down a partial
    set of links to a peer DC and validate UCMP weight redistribution.
    Caches the selected interface set under `cache_name` (if provided)
    so a follow-up call can flap the *same* interfaces back up via
    `use_cached_interfaces=True`.

    Args:
        neighbor_hostname: Hostname of the peer device whose facing
            interfaces are candidates for flapping.
        num_interfaces: Number of interfaces to sample.
        enable: True to bring interfaces UP, False to bring them DOWN.
        interface_flap_method: 1=Thrift API (default), 4=SSH.
        cache_name: jq cache key used to remember the selected interface
            set (so a later step can flap the same ones).
        use_cached_interfaces: If True, skips selection and reuses
            interfaces previously cached under `cache_name`. Requires
            `cache_name` to be set.

    Returns:
        A `Step` with `step_name=StepName.INTERFACE_FLAP_STEP`.
    """
    transform_params = None
    cache_params = None
    if use_cached_interfaces:
        if not cache_name:
            raise ValueError(
                "cache_name must be provided when use_cached_interfaces=True"
            )
        jq_params = {"interfaces": f".cached.{cache_name}"}
    else:
        jq_params = {"interfaces": '."{dut}".interfaces'}
        transform_params = {
            "interfaces": [
                taac_types.TransformFunction(
                    name="SELECT_INTERFACES_BY_NEIGHBORS",
                    json_params=json.dumps({"neighbors": [neighbor_hostname]}),
                ),
                taac_types.TransformFunction(
                    name="SELECT_SAMPLE",
                    json_params=json.dumps({"sample_size": num_interfaces}),
                ),
            ]
        }
        if cache_name:
            cache_params = {"interfaces": cache_name}

    return create_interface_flap_step(
        enable=enable,
        interface_flap_method=interface_flap_method,
        jq_params=jq_params,
        cache_params=cache_params,
        transform_params=transform_params,
        description=f"{'Enable' if enable else 'Disable'} {num_interfaces} interface(s) to {neighbor_hostname}",
    )


def create_ucmp_policy_config_step(
    vip_community: str,
    dc1_asn: int,
    dc2_asn: int,
    dc3_asn: int,
    dc1_weight: int,
    dc2_weight: int,
    dc3_weight: int,
    action: str = "set",
    fallback_to_ecmp: bool = False,
    auto_verify: bool = True,
) -> Step:
    """Install or remove a CTE UCMP routing policy on the DUT.

    Pushes an AS_PATH-based UCMP policy that assigns each DC's ASN a
    relative weight, applied only to routes carrying the target VIP
    community. When `action="set"`, weights are written; when `"unset"`,
    the policy is cleared. Optionally falls back to ECMP (equal weights)
    if any DC ASN is missing, and can auto-verify the policy was
    installed correctly. CTE UCMP-specific.

    Args:
        vip_community: BGP community whose tagged routes the policy
            should match.
        dc1_asn, dc2_asn, dc3_asn: ASNs for DC1/DC2/DC3.
        dc1_weight, dc2_weight, dc3_weight: Per-DC UCMP weights (only
            used when `action="set"`).
        action: `"set"` to install, anything else (typically `"unset"`)
            to remove.
        fallback_to_ecmp: If True, missing DC ASNs fall back to equal
            ECMP weights instead of failing.
        auto_verify: If True, the step verifies the policy is in place
            after writing it.

    Returns:
        A `Step` with `step_name=StepName.CUSTOM_STEP` dispatching to
        `UcmpPolicyConfigCustomStep`.
    """
    params_dict: t.Dict[str, t.Any] = {
        "custom_step_name": "UcmpPolicyConfigCustomStep",
        "step_params": {
            "action": action,
            "target_community": vip_community,
            "fallback_to_ecmp": fallback_to_ecmp,
            "auto_verify": auto_verify,
        },
    }
    if action == "set":
        params_dict["step_params"]["as_path_weights"] = [
            {"asn": dc1_asn, "weight": dc1_weight},
            {"asn": dc2_asn, "weight": dc2_weight},
            {"asn": dc3_asn, "weight": dc3_weight},
        ]
    return create_custom_step(
        params_dict=params_dict,
        description=f"{'Configure' if action == 'set' else 'Remove'} UCMP policy for VIP community {vip_community}",
    )


def create_ucmp_validation_step(
    vip_community: str,
    vip_v6: str,
    expected_rib_weights: t.Dict[int, int],
    expected_as_weights: t.Dict[int, int],
    expected_fib_weights: t.Dict[int, int],
    tolerance_percent: int = 5,
    expected_traffic_distribution: t.Optional[t.Dict[str, float]] = None,
    require_ucmp: bool = True,
) -> Step:
    """Validate that UCMP weights propagated correctly from policy to FIB.

    Builds a `VALIDATION_STEP` that runs two health checks: (1) BGP RIB
    weight check confirming the per-DC weights are present in the RIB
    for the target prefix, and (2) FIB traffic-distribution check
    confirming the dataplane actually splits traffic in the expected
    ratio. Optionally requires UCMP (vs. ECMP fallback) to be active.
    CTE UCMP-specific. Run after `create_ucmp_policy_config_step` and
    a convergence wait.

    Args:
        vip_community: BGP community tagged on the VIP routes.
        vip_v6: Target IPv6 VIP prefix being validated.
        expected_rib_weights: Map of `dc_asn → weight` expected in the BGP RIB.
        expected_as_weights: Map of `dc_asn → AS-path weight` expected.
        expected_fib_weights: Map of `dc_asn → FIB weight` expected.
        tolerance_percent: Allowed deviation between observed and
            expected FIB weights / traffic distribution. Default 5%.
        expected_traffic_distribution: Optional `iface → fraction` map
            for IXIA-side traffic distribution validation.
        require_ucmp: If True, fails if UCMP fell back to ECMP.

    Returns:
        A `Step` with `step_name=StepName.VALIDATION_STEP`.
    """
    from taac.health_checks.healthcheck_definitions import (
        create_bgp_rib_weight_check,
        create_fib_traffic_distribution_check,
    )

    fib_check_params: t.Dict[str, t.Any] = {
        "target_prefix": vip_v6,
        "expected_fib_weights": expected_fib_weights,
        "tolerance_percent": tolerance_percent,
    }
    if expected_traffic_distribution:
        fib_check_params["expected_traffic_distribution"] = (
            expected_traffic_distribution
        )

    return create_validation_step(
        stage=taac_types.ValidationStage.MID_TEST,
        point_in_time_checks=[
            create_bgp_rib_weight_check(
                target_community=vip_community,
                target_prefix=vip_v6,
                expected_weights=expected_rib_weights,
                expected_as_weights=expected_as_weights,
                require_ucmp=require_ucmp,
            ),
            create_fib_traffic_distribution_check(**fib_check_params),
        ],
    )


def create_bgp_service_restart_step() -> Step:
    """Trigger a clean systemctl restart of the BGP daemon on the DUT.

    Thin wrapper over `create_service_interruption_step` for
    `Service.BGP` with `SYSTEMCTL_RESTART` trigger. Use to simulate the
    BGP-restart half of a software upgrade or planned reboot. Pair with
    `create_bgp_service_convergence_step` to wait for sessions to come
    back up.

    Returns:
        A `Step` with `step_name=StepName.SERVICE_INTERRUPTION_STEP`.
    """
    return create_service_interruption_step(
        service=taac_types.Service.BGP,
        description="Restart BGP service (simulates device reboot/software upgrade)",
    )


def create_bgp_service_crash_step() -> Step:
    """Crash the BGP daemon with SIGKILL to simulate an unexpected fault.

    Thin wrapper over `create_service_interruption_step` for
    `Service.BGP` with the `CRASH` trigger (SIGKILL — no graceful
    shutdown). Use to validate the recovery path when BGP dies abruptly
    (no goodbye/notification messages sent to peers). Pair with
    `create_bgp_service_convergence_step` to wait for re-establishment.

    Returns:
        A `Step` with `step_name=StepName.SERVICE_INTERRUPTION_STEP`.
    """
    return create_service_interruption_step(
        service=taac_types.Service.BGP,
        trigger=taac_types.ServiceInterruptionTrigger.CRASH,
        description="Crash BGP service with SIGKILL (simulates process crash)",
    )


def create_bgp_service_convergence_step(wait_seconds: int = 60) -> Step:
    """Wait for the BGP daemon to reconverge after a restart or crash.

    Thin wrapper over `create_service_convergence_step` scoped to
    `Service.BGP`. Polls until the BGP service reports healthy
    (sessions established, no pending messages) or `wait_seconds`
    elapses. Use after `create_bgp_service_restart_step` or
    `create_bgp_service_crash_step`.

    Args:
        wait_seconds: Maximum time to wait for convergence in seconds.
            Default 60s. (Note: this value is reflected in the step
            description but the underlying convergence step uses its
            own internal timeout policy.)

    Returns:
        A `Step` with `step_name=StepName.SERVICE_CONVERGENCE_STEP`.
    """
    return create_service_convergence_step(
        services=[taac_types.Service.BGP],
        description=f"Wait for BGP service convergence (up to {wait_seconds}s)",
    )


def create_cte_ucmp_drain_undrain_step(device_name: str, drain: bool) -> Step:
    """Drain or undrain a device using the LOCAL_DRAINER handler.

    CTE UCMP variant of `create_drain_undrain_step` that pins the drain
    handler to `LOCAL_DRAINER` (no external drainer service involved).
    Used in CTE UCMP DC-bring-up scenarios where each DC's RR is drained
    in turn to script convergence events.

    Args:
        device_name: Hostname of the device to drain/undrain (only used
            for the step description; the underlying drain action targets
            the playbook's DUT).
        drain: True to drain, False to undrain.

    Returns:
        A `Step` with `step_name=StepName.DRAIN_UNDRAIN_STEP`.
    """
    return create_drain_undrain_step(
        drain=drain,
        drain_handler=taac_types.DrainHandler.LOCAL_DRAINER,
        description=f"{'Drain' if drain else 'Undrain'} device {device_name}",
    )


def system_health_validation_step() -> Step:
    """Validate system health via SYSTEM_HEALTH_CHECK_STEP."""
    from taac.health_checks.healthcheck_definitions import (
        create_system_health_check,
    )

    return create_validation_step(
        point_in_time_checks=[
            *create_system_health_check(),
        ],
    )


def packetloss_validation_step() -> Step:
    """Validate packet loss via PACKETLOSS_HEALTH_CHECK."""
    from taac.health_checks.healthcheck_definitions import (
        create_packetloss_health_check,
    )

    return create_validation_step(
        point_in_time_checks=[
            create_packetloss_health_check(),
        ],
    )


# =============================================================================
# MP3N PREFIX PROFILING STEPS (migrated from ai_bb/dsf/mp3n_playbook_stages.py)
# Helper factories for MP3N (Massive Parallel 3-Node) prefix profiling tests.
# Uses .*PREFIX_STRESSER_{DISTRIBUTION_TYPE}.* network-group naming convention.
# =============================================================================


def create_toggle_device_group_step(
    distribution_type: str,
    enable: bool,
    description: t.Optional[str] = None,
) -> Step:
    """Toggle the IXIA `PREFIX_STRESSER_*` device group on or off.

    MP3N prefix-profiling helper. Targets device groups named
    `.*PREFIX_STRESSER_{distribution_type}.*` (matches the MP3N
    naming convention) and either enables or disables them, which
    starts/stops BGP session establishment for that group's peers.
    IXIA-required.

    Args:
        distribution_type: Distribution type (e.g. `CONTIGUOUS`,
            `HYBRID`, `NON_CONTIGUOUS`); embedded into the regex.
        enable: True to enable the device group, False to disable.
        description: Custom description for the step. If omitted, a
            default is generated from the args.

    Returns:
        A `Step` with `step_name=StepName.INVOKE_IXIA_API_STEP` calling
        `toggle_device_groups`.
    """
    desc = (
        description
        or f"{'Enable' if enable else 'Disable'} {distribution_type} device group"
    )
    return create_ixia_api_step(
        api_name="toggle_device_groups",
        args_dict={
            "enable": enable,
            "device_group_name_regex": f".*PREFIX_STRESSER_{distribution_type.upper()}.*",
        },
        description=desc,
    )


def create_toggle_bgp_prefix_step(
    distribution_type: str,
    enable: bool,
    description: t.Optional[str] = None,
) -> Step:
    """Activate or deactivate BGP prefix advertisements for an MP3N network group.

    Wraps the IXIA `activate_deactivate_bgp_prefix` API. Unlike
    `create_toggle_device_group_step` (which controls peer
    establishment), this drives BGP UPDATE / WITHDRAW messages for the
    prefixes already configured under the matching network group while
    keeping the BGP session itself up. Used in MP3N prefix-profiling
    tests to drive route churn without session churn.

    Args:
        distribution_type: Distribution type used to build the
            `.*PREFIX_STRESSER_{TYPE}.*` regex.
        enable: True to advertise (UPDATE), False to withdraw.
        description: Custom description for the step. If omitted, a
            default is generated from the args.

    Returns:
        A `Step` with `step_name=StepName.INVOKE_IXIA_API_STEP` calling
        `activate_deactivate_bgp_prefix`.
    """
    desc = (
        description
        or f"{'Activate' if enable else 'Deactivate'} {distribution_type} BGP prefixes"
    )
    return create_ixia_api_step(
        api_name="activate_deactivate_bgp_prefix",
        args_dict={
            "active": enable,
            "network_group_name_regex": f".*PREFIX_STRESSER_{distribution_type.upper()}.*",
        },
        description=desc,
    )


def create_update_prefix_count_step(
    device_name: str,
    interface: str,
    prefix_count: int,
    distribution_type: str,
    network_group_multiplier: t.Optional[int] = None,
) -> Step:
    """Resize the prefix block advertised by an IXIA port for one device.

    Wraps the IXIA `update_prefix_counts_by_port` API. Used in MP3N
    prefix-profiling tests to scale the announced prefix count up or
    down on a per-port basis while traffic is running, exercising the
    DUT's RIB scaling behavior.

    Args:
        device_name: Hostname of the IXIA-attached device.
        interface: Interface name on `device_name` to target.
        prefix_count: Target prefix count to advertise (per network group,
            i.e. the pool's NumberOfAddresses).
        distribution_type: Distribution-type label used for the step
            description (does not affect the API call).

    Returns:
        A `Step` with `step_name=StepName.INVOKE_IXIA_API_STEP` calling
        `update_prefix_counts_by_port`.
    """
    return create_ixia_api_step(
        api_name="update_prefix_counts_by_port",
        args_dict={
            "hostname": device_name,
            "interface": interface,
            "prefix_count": prefix_count,
            "network_group_multiplier": network_group_multiplier,
        },
        description=f"Update prefix count={prefix_count} for {distribution_type} network group",
    )


def create_configure_random_mask_step(
    network_group_regex: str,
    fixed_prefix: str,
    random_mask: str,
    seed: int,
    count: int,
    distribution_type: str,
    prefix_length: t.Optional[int] = None,
) -> Step:
    """Configure pseudo-random masked prefixes for HYBRID/NON_CONTIGUOUS dists.

    Wraps the IXIA `configure_random_mask_prefixes` API. The IXIA
    generates `count` prefixes of `prefix_length` by combining the
    `fixed_prefix` (preserved bits) with random bits sampled per the
    `random_mask` and the deterministic `seed`. Used in MP3N
    prefix-profiling tests to produce a reproducible non-contiguous
    prefix set.

    Args:
        network_group_regex: Regex matching the IXIA network groups to
            reconfigure.
        fixed_prefix: Address whose bits marked by 1 in `random_mask`
            are preserved verbatim.
        random_mask: Bitmask defining which bits of `fixed_prefix` are
            randomized.
        seed: PRNG seed for reproducibility.
        count: Number of prefixes to generate.
        distribution_type: Label for the step description (`HYBRID`
            or `NON_CONTIGUOUS`).
        prefix_length: Optional explicit prefix length; if omitted, the
            IXIA's default for this group applies.

    Returns:
        A `Step` with `step_name=StepName.INVOKE_IXIA_API_STEP` calling
        `configure_random_mask_prefixes`.
    """
    args: t.Dict[str, t.Any] = {
        "network_group_regex": network_group_regex,
        "fixed_value": fixed_prefix,
        "mask_value": random_mask,
        "seed": seed,
        "prefix_count": count,
    }
    if prefix_length is not None:
        args["prefix_length"] = prefix_length
    return create_ixia_api_step(
        api_name="configure_random_mask_prefixes",
        args_dict=args,
        description=f"Configure RANDOM_MASK pattern for {distribution_type} (/{prefix_length})",
    )


def create_configure_prefix_length_step(
    network_group_regex: str,
    prefix_length: int,
    distribution_type: str,
) -> Step:
    """Set the advertised prefix length for a CONTIGUOUS-distribution group.

    Wraps the IXIA `configure_advertised_prefixes` API, used in MP3N
    prefix-profiling tests with the INCREMENT pattern. Adjusting the
    prefix length resizes the address space the IXIA walks when
    incrementing through prefixes. Pair with `create_update_prefix_count_step`
    to scale both length and count.

    Args:
        network_group_regex: Regex matching the IXIA network groups to
            reconfigure.
        prefix_length: New prefix length (e.g. 24, 32, 48, 64, 128).
        distribution_type: Label for the step description (typically
            `CONTIGUOUS`).

    Returns:
        A `Step` with `step_name=StepName.INVOKE_IXIA_API_STEP` calling
        `configure_advertised_prefixes`.
    """
    return create_ixia_api_step(
        api_name="configure_advertised_prefixes",
        args_dict={
            "network_group_regex": network_group_regex,
            "prefix_length": prefix_length,
        },
        description=f"Configure prefix length for {distribution_type} (/{prefix_length})",
    )


def create_start_traffic_step() -> Step:
    """Begin IXIA traffic generation across all configured traffic items.

    Wraps the IXIA `start_traffic` API. Run after sessions are
    established and any pre-traffic configuration is applied. Pair with
    `create_stop_traffic_step` at the end of the measurement window.
    IXIA-required.

    Returns:
        A `Step` with `step_name=StepName.INVOKE_IXIA_API_STEP` calling
        `start_traffic`.
    """
    return create_ixia_api_step(api_name="start_traffic", args_dict={})


def create_regenerate_traffic_step() -> Step:
    """Regenerate IXIA traffic items so destinations match the current config.

    Wraps the IXIA `regenerate_traffic_items` API, which stops traffic (if
    running), calls `Generate()` on each traffic item, then restarts it —
    re-expanding the traffic endpoints from the current state of the
    topology they are bound to (device groups, network groups, route
    ranges, etc.).

    Run this after any runtime change that alters what a traffic item
    should target, and before the measurement window, so traffic uses the
    updated endpoints instead of the stale ones the traffic item was last
    generated with.

    A dedicated step is required because the base `Step._run` pre-hook
    (`steps/step.py`) starts traffic before every step body. By the time
    the `start_traffic` step runs, traffic is already running, so
    `start_traffic` early-returns and silently skips its
    `regenerate_traffic_items` flag. Calling `regenerate_traffic_items`
    directly bypasses that early-return and forces the `Generate()`.
    IXIA-required.

    Returns:
        A `Step` with `step_name=StepName.INVOKE_IXIA_API_STEP` calling
        `regenerate_traffic_items`.
    """
    return create_ixia_api_step(api_name="regenerate_traffic_items", args_dict={})


def create_stop_traffic_step() -> Step:
    """Halt IXIA traffic generation across all configured traffic items.

    Wraps the IXIA `stop_traffic` API. Counterpart to
    `create_start_traffic_step`. Counters remain queryable after stop;
    use `create_clear_traffic_stats_step` to reset them. IXIA-required.

    Returns:
        A `Step` with `step_name=StepName.INVOKE_IXIA_API_STEP` calling
        `stop_traffic`.
    """
    return create_ixia_api_step(api_name="stop_traffic", args_dict={})


def create_weight_policy_setup_step(
    device_name: str,
    target_policy: str,
    weight_low: int,
    weight_high: int,
    weight_low_community: str,
    weight_high_community: str,
    ssh_user: str = "admin",
    ssh_password: str = "",
) -> Step:
    """Append community→weight mappings to an existing BGP policy on the DUT.

    Runs the `add_bgp_weight_policy` task over SSH to add two
    community-keyed weight entries (`weight_low_community→weight_low`,
    `weight_high_community→weight_high`) to the named policy and reload
    BGP. Used as a setup step in weighted-ECMP tests. Arista-only —
    relies on EOS routing-policy CLI.

    Args:
        device_name: Hostname of the DUT to configure.
        target_policy: Name of the existing BGP routing policy to
            append entries to.
        weight_low: Weight assigned to routes carrying
            `weight_low_community`.
        weight_high: Weight assigned to routes carrying
            `weight_high_community`.
        weight_low_community: BGP community string for the lower-weight
            class.
        weight_high_community: BGP community string for the
            higher-weight class.
        ssh_user: SSH username (default `admin`).
        ssh_password: SSH password (default empty — relies on key auth).

    Returns:
        A `Step` with `step_name=StepName.RUN_TASK_STEP` invoking
        `add_bgp_weight_policy`.
    """
    return create_run_task_step(
        task_name="add_bgp_weight_policy",
        params_dict={
            "hostname": device_name,
            "target_policy": target_policy,
            "community_weight_map": {
                weight_low_community: weight_low,
                weight_high_community: weight_high,
            },
            "ssh_user": ssh_user,
            "ssh_password": ssh_password,
            "reload_bgp": True,
        },
        description=f"Add weight policy entries to {target_policy}",
    )


def create_replace_peers_setup_step(
    device_name: str,
    ebgp_remote_as: int,
    ibgp_local_as: int,
    ixia_ebgp_ic_parent_network_v6: str,
    ixia_ebgp_ic_parent_network_v4: str,
    ixia_ibgp_ic_parent_network_v6: str,
    ixia_ibgp_ic_parent_network_v4: str,
    ebgp_peer_count: int,
    ibgp_peer_count: int,
    test_address_families: t.List[str],
    ssh_user: str = "admin",
    ssh_password: str = "",
) -> Step:
    """Replace production BGP peers with a minimal test peer set on the DUT.

    Setup step that wipes the DUT's existing BGP eBGP/iBGP peers and
    installs a small, deterministic set of test peers facing the IXIA
    ingress/egress networks for the requested address families. The
    `BGP-MON` peer group is intentionally preserved so monitoring
    pipelines stay alive. Arista-only — uses the SSH-based BGP config
    flow. Used as a setup step in EBB / scaling tests where production
    peer configs would be too noisy.

    Args:
        device_name: Hostname of the DUT to reconfigure.
        ebgp_remote_as: ASN to use for the synthetic eBGP peers.
        ibgp_local_as: Local ASN used for the iBGP peer block.
        ixia_ebgp_ic_parent_network_v6 / _v4: IPv6 / IPv4 parent
            networks the eBGP peer addresses are derived from.
        ixia_ibgp_ic_parent_network_v6 / _v4: IPv6 / IPv4 parent
            networks the iBGP peer addresses are derived from.
        ebgp_peer_count: Number of eBGP test peers to install per AF.
        ibgp_peer_count: Number of iBGP test peers to install per AF.
        test_address_families: Subset of `["ipv4", "ipv6"]` to
            configure; AFs not listed are skipped.
        ssh_user: SSH username (default `admin`).
        ssh_password: SSH password (default empty — relies on key auth).

    Returns:
        A `Step` with `step_name=StepName.RUN_TASK_STEP` invoking the
        peer-replacement task.
    """
    peer_groups: t.List[t.Dict[str, t.Any]] = []

    if "ipv6" in test_address_families:
        peer_groups.append(
            {
                "peer_group_name": "EB-FA-V6",
                "remote_as": ebgp_remote_as,
                "base_network": ixia_ebgp_ic_parent_network_v6,
                "is_v6": True,
                "peer_count": ebgp_peer_count,
                "description_prefix": "Test eBGP V6 Peer",
            }
        )
        peer_groups.append(
            {
                "peer_group_name": "EB-EB-V6",
                "remote_as": ibgp_local_as,
                "base_network": ixia_ibgp_ic_parent_network_v6,
                "is_v6": True,
                "peer_count": ibgp_peer_count,
                "description_prefix": "Test iBGP V6 Peer",
            }
        )

    if "ipv4" in test_address_families:
        peer_groups.append(
            {
                "peer_group_name": "EB-FA-V4",
                "remote_as": ebgp_remote_as,
                "base_network": ixia_ebgp_ic_parent_network_v4,
                "is_v6": False,
                "peer_count": ebgp_peer_count,
                "description_prefix": "Test eBGP V4 Peer",
            }
        )
        peer_groups.append(
            {
                "peer_group_name": "EB-EB-V4",
                "remote_as": ibgp_local_as,
                "base_network": ixia_ibgp_ic_parent_network_v4,
                "is_v6": False,
                "peer_count": ibgp_peer_count,
                "description_prefix": "Test iBGP V4 Peer",
            }
        )

    return create_run_task_step(
        task_name="replace_bgp_peers",
        params_dict={
            "hostname": device_name,
            "peer_groups": peer_groups,
            "start_offset": 16,
            "ssh_user": ssh_user,
            "ssh_password": ssh_password,
            "reload_bgp": True,
            "preserve_peer_groups": ["BGP-MON"],
        },
        description="Replace BGP peers with minimal test peers",
    )


# =============================================================================
# BGP DC SHARED STEP HELPERS (migrated from routing/dc_routing/bgp_dc/common.py)
# Duration scalars + step list sequences + the do_continuous_sequence utility.
# Stages and the SKIP_BGPD_MAIN_CORE_DUMP_CHECK constant remain in
# bgp_dc/common.py (domain-specific stage/HC composition).
# =============================================================================

# Duration constants - shared across BGP DC test playbooks.
duration_all_prefix_flaps_s = 1000
duration_all_session_flaps_s = 3600
duration_only_rogue_session_prefix_flaps_s = 1000
duration_no_prefix_session_flaps_s = 1000
wait_time_after_disable_churn_s = 30
bgp_restart_count = 25
duration_toggle_device_group_prefixes_s = 3600
duration_activate_deactivate_all_prefixes_s = 600
duration_frequent_best_path_computation_s = 3600
duration_cold_start_variants_s = 3600
local_pref_churn_interval_s = 10


def do_continuous_sequence(
    sequence,
    total_duration=None,
    sequence_duration=None,
    number_of_iterations=None,
):
    """Repeat a sequence of steps continuously for a duration or N iterations."""
    mode1 = total_duration is not None and sequence_duration is not None
    mode2 = number_of_iterations is not None
    assert mode1 ^ mode2, (
        "Provide either (total_duration and sequence_duration) or "
        "(number_of_iterations), but not both."
    )
    if mode1:
        number_of_iterations = total_duration // sequence_duration
    return [step for _ in range(number_of_iterations) for step in sequence]


# One cycle: disable all prefix groups (v4+v6) → wait 120s → enable all → wait 120s.
ACTIVE_DEACTIVE_PREFIX_GROUPS_SINGLE_SEQUENCE = [
    create_toggle_ixia_prefix_session_flap_churn_step(
        churn_mode="activate_deactivate_prefix",
        enable_prefix_flap=False,
        is_all_prefix_groups=True,
        churn_duration_s=wait_time_after_disable_churn_s,
    ),
    create_longevity_step(duration=120),
    create_toggle_ixia_prefix_session_flap_churn_step(
        churn_mode="activate_deactivate_prefix",
        enable_prefix_flap=True,
        is_all_prefix_groups=True,
        churn_duration_s=wait_time_after_disable_churn_s,
    ),
    create_longevity_step(duration=120),
]

# IPv4-only prefix oscillation for cold-start variants.
ACTIVATE_DEACTIVATE_IPV4_PREFIX_GROUPS_SINGLE_SEQUENCE = [
    create_toggle_ixia_prefix_session_flap_churn_step(
        churn_mode="activate_deactivate_prefix",
        enable_prefix_flap=False,
        prefix_flap_tag_names=["PREFIX_FLAP_TRAFFIC_LOSS_EXPECTED"],
        churn_duration_s=wait_time_after_disable_churn_s,
    ),
    create_longevity_step(duration=120),
    create_toggle_ixia_prefix_session_flap_churn_step(
        churn_mode="activate_deactivate_prefix",
        enable_prefix_flap=True,
        prefix_flap_tag_names=["PREFIX_FLAP_TRAFFIC_LOSS_EXPECTED"],
        churn_duration_s=wait_time_after_disable_churn_s,
    ),
    create_longevity_step(duration=120),
]

# IPv6-only session oscillation for cold-start variants.
ACTIVATE_DEACTIVATE_IPV6_SESSION_GROUPS_SINGLE_SEQUENCE = [
    create_toggle_ixia_prefix_session_flap_churn_step(
        churn_mode="session_flap",
        enable_session_flap=False,
        session_flap_tag_names=["SESSION_FLAP_TRAFFIC_LOSS_EXPECTED"],
        churn_duration_s=wait_time_after_disable_churn_s,
    ),
    create_longevity_step(duration=120),
    create_toggle_ixia_prefix_session_flap_churn_step(
        churn_mode="session_flap",
        enable_session_flap=True,
        session_flap_tag_names=["SESSION_FLAP_TRAFFIC_LOSS_EXPECTED"],
        churn_duration_s=wait_time_after_disable_churn_s,
    ),
    create_longevity_step(duration=120),
]

# Toggle rogue device groups on/off every 2 minutes.
DISABLE_ROGUE_DEVICE_GROUPS_EVERY_2_MIN = [
    create_ixia_api_step(
        api_name="toggle_device_groups",
        args_dict={
            "enable": True,
            "device_group_name_regex": "ROGUE|NO_PACKET_LOSS_EXPECTED|ECMP_1|ARP|NDP",
        },
    ),
    create_longevity_step(duration=120),
    create_ixia_api_step(
        api_name="toggle_device_groups",
        args_dict={
            "enable": False,
            "device_group_name_regex": "ROGUE|NO_PACKET_LOSS_EXPECTED|ECMP_1|ARP|NDP",
        },
    ),
    create_longevity_step(duration=120),
]

# Re-enable rogue prefix and session flaps after a test (cleanup).
ROGUE_PREFIX_SESSION_FLAP_STEPS = [
    create_toggle_ixia_prefix_session_flap_churn_step(
        churn_mode="prefix_flap",
        enable_prefix_flap=True,
        prefix_flap_tag_names=["ROGUE_PREFIX_FLAP"],
        churn_duration_s=wait_time_after_disable_churn_s,
    ),
    create_toggle_ixia_prefix_session_flap_churn_step(
        churn_mode="session_flap",
        enable_session_flap=True,
        session_flap_tag_names=["ROGUE_SESSION_FLAP"],
        churn_duration_s=wait_time_after_disable_churn_s,
    ),
]

# Revert local preference to default (100) after best-path-computation tests.
REVERT_LOCAL_PREFERENCE_STEPS = [
    create_set_bgp_prefixes_local_preference_step(
        prefix_pool_regex=".*",
        local_pref_value=100,
        prefix_start_index=0,
        description="Revert local preference to default (100)",
    ),
]

# Pre-composed continuous sequences ready for use as Stage(steps=...).
TOGGLE_ROGUE_DEVICE_GROUP_STEPS_CONTIUOUSLY = do_continuous_sequence(
    sequence=DISABLE_ROGUE_DEVICE_GROUPS_EVERY_2_MIN,
    total_duration=duration_toggle_device_group_prefixes_s,
    sequence_duration=300,
)

CONTINUOUSLY_ACTIVATE_DEACTIVATE_ALL_PREFIXES = do_continuous_sequence(
    sequence=ACTIVE_DEACTIVE_PREFIX_GROUPS_SINGLE_SEQUENCE,
    total_duration=duration_activate_deactivate_all_prefixes_s,
    sequence_duration=300,
)

# Cold-start oscillation: 9 cycles alternating IPv4 prefix-flaps / IPv6 session-flaps.
COLD_START_PREFIX_OSCILLATIONS = [
    step
    for _ in range(9)
    for step in (
        ACTIVATE_DEACTIVATE_IPV4_PREFIX_GROUPS_SINGLE_SEQUENCE
        if _ % 2 == 0
        else ACTIVATE_DEACTIVATE_IPV6_SESSION_GROUPS_SINGLE_SEQUENCE
    )
]


def create_route_convergence_health_check_step(
    network_group_regex: str,
    iterations: int = 5,
    time_threshold: int = 35,
    wait_time_seconds: int = 60,
) -> Step:
    """Run the Route Convergence health check N times to measure converge time.

    Builds a `VALIDATION_STEP` that wraps `create_route_convergence_time_check`,
    which repeatedly withdraws then re-advertises the routes belonging to
    the matching IXIA network groups and measures how long the DUT takes
    to install / remove them in the FIB. Fails if any iteration exceeds
    `time_threshold` seconds. IXIA-required.

    Args:
        network_group_regex: Regex matching the IXIA network groups
            whose routes are flapped.
        iterations: Number of DELETE→ADD iterations per check (default 5).
        time_threshold: Per-iteration convergence-time SLO in seconds
            (default 35s).
        wait_time_seconds: Pause between iterations (default 60s) so the
            DUT settles before the next round.

    Returns:
        A `Step` with `step_name=StepName.VALIDATION_STEP` running the
        Route Convergence health check at `MID_TEST` stage.
    """
    from taac.health_checks.healthcheck_definitions import (
        create_route_convergence_time_check,
    )

    return create_validation_step(
        point_in_time_checks=[
            create_route_convergence_time_check(
                network_group_regex=network_group_regex,
                iterations=iterations,
                time_threshold=time_threshold,
                wait_time_seconds=wait_time_seconds,
            ),
        ],
        stage=taac_types.ValidationStage.MID_TEST,
        description=f"Route Convergence Check ({iterations} iterations of DELETE→ADD) - threshold: {time_threshold}s",
    )


# =============================================================================
# CONCRETE STEP RUNTIME CLASSES
# =============================================================================
# Phase 7-B23+: Concrete `Step[Input]` ABC subclasses are migrated here from
# their per-file homes in `taac/steps/*_step.py`. They co-locate with the
# factory functions above so test authors and framework maintainers can find
# both the declarative (factory) and runtime (class) sides of a step in one
# file. The ABC base class still lives in `taac/steps/step.py` and is imported
# above as `StepBase`.
# =============================================================================


class DummyStep(StepBase[taac_types.BaseInput]):
    STEP_NAME = taac_types.StepName.DUMMY_STEP

    async def run(
        self,
        input: taac_types.BaseInput,
        params: t.Dict[str, t.Any],
    ) -> None:
        self.logger.info("Executing dummy step")


class LongevityStep(StepBase[taac_types.BaseInput]):
    STEP_NAME = taac_types.StepName.LONGEVITY_STEP

    async def run(
        self,
        input: taac_types.BaseInput,
        params: t.Dict[str, t.Any],
    ):
        duration = params["duration"]
        label = params.get("description", "LONGEVITY_STEP")
        total_min = duration // 60
        total_sec = duration % 60
        total_str = f"{total_min}m {total_sec}s" if total_min else f"{total_sec}s"
        self.logger.info(f"[Wait] {label} — waiting {total_str}")
        start_time = time.time()
        seconds_passed = 0
        while seconds_passed < duration:
            sleep_time = min(60, duration - seconds_passed)
            await asyncio.sleep(sleep_time)
            seconds_passed = int(time.time() - start_time)
            seconds_remaining = max(0, duration - seconds_passed)
            elapsed_min = seconds_passed // 60
            remaining_min = seconds_remaining // 60
            remaining_sec = seconds_remaining % 60
            self.logger.info(
                f"[Wait] {label} — {elapsed_min}m elapsed, "
                f"{remaining_min}m {remaining_sec}s remaining"
            )
        elapsed = time.time() - start_time
        self.logger.info(f"[Wait] {label} — complete ({elapsed:.1f}s)")


class RunSSHCmdStep(StepBase[taac_types.BaseInput]):
    STEP_NAME = taac_types.StepName.RUN_SSH_COMMAND_STEP

    async def run(
        self,
        input: taac_types.BaseInput,
        params: t.Dict[str, t.Any],
    ) -> None:
        cmd = params["cmd"]
        log_output = params.get("log_output", False)
        output = await self.driver.async_run_cmd_on_shell(cmd)
        if log_output and output:
            self.logger.info(f"Command output:\n{output}")


class DrainUndrainStep(StepBase[taac_types.DrainUndrainInput]):
    STEP_NAME = taac_types.StepName.DRAIN_UNDRAIN_STEP

    async def run(
        self,
        input: taac_types.DrainUndrainInput,
        params: t.Dict[str, t.Any],
    ) -> None:
        interfaces = params.get("interfaces", [])
        if interfaces:
            interfaces = [
                try_json_to_thrift(interface, taac_types.TestInterface)
                for interface in try_json_loads(interfaces)
            ]
            interfaces = [
                (
                    self.device.get_interface_by_name(interface)
                    if isinstance(interface, str)
                    else interface
                )
                for interface in interfaces
            ]
        interface_names = [interface.interface_name for interface in interfaces]
        if input.drain_handler == taac_types.DrainHandler.LOCAL_DRAINER:
            if interface_names:
                # Per-port (link) drain: soft-drain each interface on-box
                # (depreferences BGP advertisements without bringing the link
                # down at the data plane). undrain_interface reverses it.
                # softdrain/undrain_interface are FbossSwitch-only; cast to Any
                # to avoid importing FbossSwitch here (keeps the BUCK target light).
                fboss_driver = t.cast(t.Any, self.driver)
                for name in interface_names:
                    if input.drain:
                        await fboss_driver.async_softdrain_interface(name)
                    else:
                        await fboss_driver.async_undrain_interface(name)
            elif input.drain:
                await self.driver.async_onbox_drain_device()
            else:
                await self.driver.async_onbox_undrain_device()
        elif input.drain_handler == taac_types.DrainHandler.NDS:
            await async_nds_drain(
                self.device.name,
                force_undrain=not input.drain,
                interfaces=interface_names,
            )
        else:
            raise


class ServiceConvergenceStep(StepBase[taac_types.ServiceConvergenceInput]):
    STEP_NAME = taac_types.StepName.SERVICE_CONVERGENCE_STEP

    async def run(
        self,
        input: taac_types.ServiceConvergenceInput,
        params: t.Dict[str, t.Any],
    ) -> None:
        if any(
            agent in [taac_types.Service.AGENT, taac_types.Service.FBOSS_SW_AGENT]
            for agent in input.services
        ):
            timeout = (
                input.service_convergence_timeout.get(taac_types.Service.AGENT)
                or input.service_convergence_timeout.get(
                    taac_types.Service.FBOSS_SW_AGENT
                )
                or input.timeout
            )
            start_time = time.time()
            await self.driver.async_wait_for_agent_configured(timeout)
            end_time = time.time()
            self.logger.info(
                f"Agent reached configured state in {end_time - start_time} seconds"
            )
        if taac_types.Service.BGP in input.services:
            if self.ixia and "rsw" in self.hostname:
                self.ixia.restart_bgp_peers([self.hostname.upper()])
            timeout = (
                input.service_convergence_timeout.get(taac_types.Service.BGP)
                or input.timeout
            )
            start_time = time.time()
            await self.driver.async_wait_for_bgp_convergence(timeout)
            end_time = time.time()
            self.logger.info(f"Bgpd converged in {end_time - start_time} seconds")
        if taac_types.Service.QSFP_SERVICE in input.services and self.is_fboss:
            timeout = (
                input.service_convergence_timeout.get(taac_types.Service.QSFP_SERVICE)
                or input.timeout
            )
            start_time = time.time()
            # pyre-ignore
            await self.driver.async_wait_for_qsfp_service_state_active(timeout)
            end_time = time.time()
            self.logger.info(
                f"qsfp_service reached active state in {end_time - start_time} seconds"
            )
        if taac_types.Service.FSDB in input.services and self.is_fboss:
            timeout = (
                input.service_convergence_timeout.get(taac_types.Service.FSDB)
                or input.timeout
            )
            start_time = time.time()
            # pyre-ignore
            await self.driver.async_wait_for_fsdb_state_active(timeout)
            end_time = time.time()
            self.logger.info(
                f"fsdb reached active state in {end_time - start_time} seconds"
            )


class ServiceInterruptionStep(StepBase[taac_types.ServiceInterruptionInput]):
    STEP_NAME = taac_types.StepName.SERVICE_INTERRUPTION_STEP

    def service_factory(self, service: taac_types.Service) -> DriverService:
        service_value = taac_types.SERVICE_NAME_MAP[service]
        arista_service_names = {
            member.value: member.name for member in AristaCriticalAgents
        }
        other_systemctl_service_names = {
            member.value: member.name for member in OtherSystemctlServiceName
        }
        fboss_systemctl_service_names = {
            member.value: member.name for member in FbossSystemctlServiceName
        }
        if service_value in fboss_systemctl_service_names:
            return FbossSystemctlServiceName[
                fboss_systemctl_service_names[service_value]
            ]
        elif service_value in other_systemctl_service_names:
            return OtherSystemctlServiceName[
                other_systemctl_service_names[service_value]
            ]
        elif service_value in arista_service_names:
            return AristaCriticalAgents[arista_service_names[service_value]]
        raise

    async def run(
        self,
        input: taac_types.ServiceInterruptionInput,
        params: t.Dict[str, t.Any],
    ) -> None:
        service = self.service_factory(input.name)
        agents = list(input.agents) if input.agents is not None else None

        if input.create_cold_boot_file and self.is_fboss:
            await self.driver.async_run_cmd_on_shell(
                "touch /dev/shm/fboss/warm_boot/cold_boot_once_0"
            )
        match input.trigger:
            case taac_types.ServiceInterruptionTrigger.SYSTEMCTL_STOP:
                await self.driver.async_stop_service(service, agents)
            case taac_types.ServiceInterruptionTrigger.SYSTEMCTL_START:
                await self.driver.async_start_service(service, agents)
            case taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART:
                await self.driver.async_restart_service(service, agents)
            case taac_types.ServiceInterruptionTrigger.CRASH:
                await self.driver.async_crash_service(service, agents)


class InvokeIxiaApiStep(StepBase[taac_types.BaseInput]):
    STEP_NAME = taac_types.StepName.INVOKE_IXIA_API_STEP

    async def run(
        self,
        input: taac_types.BaseInput,
        params: t.Dict[str, t.Any],
    ) -> None:
        ixia = none_throws(self.ixia)
        api_name = params["api_name"]
        api_func = getattr(ixia, api_name)
        if not api_func:
            raise ValueError(f"Invalid ixia API name: {api_name}")
        args = json.loads(params.get("args_json", "{}"))
        assert isinstance(args, dict), (
            f"Invalid args_json: {args}: {type(args)}. Args must be a dict"
        )
        api_func(**args)


class RunTaskStep(StepBase[taac_types.RunTaskInput]):
    STEP_NAME = taac_types.StepName.RUN_TASK_STEP

    async def run(
        self,
        input: taac_types.RunTaskInput,
        params: t.Dict[str, t.Any],
    ) -> None:
        task = input.task
        dict_params = self.parameter_evaluator.evaluate(task.params)
        if input.blocking:
            await run_task(task, dict_params, self.ixia, self.logger)
        else:
            run_in_thread(run_task, task, dict_params, self.ixia, self.logger)


_PERCENT_ECMP_MEMBERS_VALID_BGP = 0.25
_ECMP_GROUP_USAGE_FOR_MEMBER_STRESS = 1300


class EcmpMemberStaticRouteStep(StepBase[taac_types.BaseInput]):
    STEP_NAME = taac_types.StepName.ECMP_MEMBER_STATIC_ROUTE

    async def run(
        self,
        input: taac_types.BaseInput,
        params: t.Dict[str, t.Any],
    ) -> None:
        static_route_patcher_name = "ecmp_nh_stressor_patcher"
        dut_driver_class = self.driver
        delete_patcher_and_exit_step = params.get("delete_patcher_and_exit_step", False)
        await dut_driver_class.async_coop_unregister_patchers(static_route_patcher_name)
        if delete_patcher_and_exit_step:
            return

        nh_common_last_hextet = "a000"
        max_ecmp_group = params["max_ecmp_group"]
        max_ecmp_members = params["max_ecmp_members"]
        nh_prefix_1 = params["nh_prefix_1"]
        lb_prefix_agg = params["lb_prefix_agg"]
        device_group_count = params["device_group_count"]
        sleep_time_route_add_s = params.get("sleep_time_route_add_s", 60)
        dut_driver_class = self.driver

        current_ecmp_member = (
            await dut_driver_class.async_verify_ecmp_nexthop_group_member_count()
        )
        self.driver.logger.info(
            f"Intended ECMP member with current + static routes: {max_ecmp_members}"
        )
        self.driver.logger.info(f"Current ECMP member: {current_ecmp_member}")
        current_ecmp_group = len(
            await dut_driver_class.async_get_ecmp_groups_snapshot()
        )
        self.driver.logger.info(f"Current ECMP group: {current_ecmp_group}")
        static_based_ecmp_group = max_ecmp_group - current_ecmp_group
        self.driver.logger.info(
            f"Applying static route to additionally add {static_based_ecmp_group=} groups"
        )
        static_based_ecmp_member = max_ecmp_members - current_ecmp_member
        self.driver.logger.info(
            f"Applying static route to additionally add {static_based_ecmp_member=} members"
        )

        network_1 = ipaddress.IPv6Network(nh_prefix_1, strict=False)
        base_increment = int(nh_common_last_hextet, 16)
        nh_list = [
            str(network_1.network_address + base_increment + i)
            for i in range(device_group_count)
        ]
        lb_network = ipaddress.IPv6Network(lb_prefix_agg, strict=False)
        lb_prefix_len = 128
        lb_subnets_iterator = lb_network.subnets(new_prefix=lb_prefix_len)
        lb_subnets = list(
            itertools.islice(lb_subnets_iterator, static_based_ecmp_group)
        )
        lb_prefix_list = [
            f"{subnet.network_address}/{lb_prefix_len}" for subnet in lb_subnets
        ]
        ecmp_combinations_list = generate_prefix_nh_list_map(
            nh_list, static_based_ecmp_member, static_based_ecmp_group
        )
        prefix_to_nexthops = {
            prefix: list(combination)
            for prefix, combination in zip(lb_prefix_list, ecmp_combinations_list)
        }
        self.driver.logger.info(
            f"Number of unique ecmp combinations: {len(ecmp_combinations_list)}"
        )
        expected_ecmp_member_count = sum(
            len(nh_set) for nh_set in ecmp_combinations_list
        )
        self.driver.logger.info(f"Total ECMP members: {expected_ecmp_member_count}")

        await dut_driver_class.async_add_static_route_patcher(
            prefix_to_nexthops,
            static_route_patcher_name,
            is_patcher_name_uuid_needed=False,
        )
        self.driver.logger.info(
            f"Sleeping {sleep_time_route_add_s}s after addition of new static route patcher"
        )
        await asyncio.sleep(sleep_time_route_add_s)
        self.driver.logger.info(
            f"Current member count: {await dut_driver_class.async_verify_ecmp_nexthop_group_member_count()} "
            f"Current Group  count: {len(await dut_driver_class.async_get_ecmp_groups_snapshot())}"
        )


_SLEEP_TIME_AFTER_STABLIZING_S = 120


class MassBgpPeerToggle(StepBase[taac_types.BaseInput]):
    STEP_NAME = taac_types.StepName.MASS_BGP_PEER_TOGGLE

    async def run(
        self,
        input: taac_types.BaseInput,
        params: t.Dict[str, t.Any],
    ) -> None:
        ixia = none_throws(self.ixia)
        device_group_name_regex = params["device_group_name_regex"]
        toggle_time_interval_s = int(params["toggle_time_interval_s"])
        total_step_time_hours = int(params["total_step_time_hours"])
        is_enable = False
        start_time = time.time()
        while True:
            ixia.toggle_device_groups(
                enable=is_enable, device_group_name_regex=device_group_name_regex
            )
            mode_str = "enable" if is_enable else "disable"
            ixia.logger.info(
                f"Waiting {toggle_time_interval_s}s before flipping rogue device groups to {mode_str}"
            )
            await asyncio.sleep(toggle_time_interval_s)
            is_enable = not is_enable
            elapsed_time = time.time() - start_time
            if elapsed_time >= total_step_time_hours * 3600:
                break
        ixia.toggle_device_groups(
            enable=True, device_group_name_regex=device_group_name_regex
        )
        ixia.logger.info(
            f"Waiting for the {_SLEEP_TIME_AFTER_STABLIZING_S}s after enabling device groups"
        )
        await asyncio.sleep(_SLEEP_TIME_AFTER_STABLIZING_S)


class ModulePowerToggleStep(StepBase[taac_types.BaseInput]):
    STEP_NAME = taac_types.StepName.MODULE_POWER_TOGGLE_STEP

    async def run(
        self,
        input: taac_types.BaseInput,
        params: t.Dict[str, t.Any],
    ) -> None:
        modules = params["modules"]
        enable = params["enable"]
        sequential = params.get("sequential", False)
        delay = params.get("delay", 5)
        try:
            await self.async_toggle_modules(modules, enable, sequential)
        except Exception as e:
            self.logger.error(f"Failed to toggle modules: {e}")
            raise e
        if delay:
            self.logger.info(f"Sleeping for {delay} seconds...")
            await asyncio.sleep(delay)

    async def async_toggle_modules(
        self,
        modules: t.List[str],
        enable: bool,
        sequential: bool,
    ) -> None:
        # Lazy import to keep step_definitions.py BUCK target light.
        from taac.internal.driver.arista_switch import (
            AristaSwitch,
        )
        from taac.internal.driver.cisco_switch import CiscoSwitch

        if isinstance(self.driver, (AristaSwitch, CiscoSwitch)):
            driver = self.driver
        else:
            raise NotImplementedError(
                "Module power toggle only supported for Arista and Cisco switches"
            )

        coroutines = []
        for module in modules:
            if enable:
                coroutines.append(driver.enable_location(module))
            else:
                coroutines.append(driver.disable_location(module))

        if sequential:
            for coro in coroutines:
                await coro
        else:
            await asyncio.gather(*coroutines)

        action = "enabled" if enable else "disabled"
        self.logger.info(f"Successfully {action} modules: {modules}")


class VerifyFileModificationTimeStep(StepBase[taac_types.BaseInput]):
    STEP_NAME = taac_types.StepName.VERIFY_FILE_MODIFICATION_TIME_STEP
    OPERATING_SYSTEMS = ["EOS"]

    async def run(
        self, input: taac_types.BaseInput, params: t.Dict[str, t.Any]
    ) -> None:
        file_path = params["file_path"]
        expected_last_mod_time = params["expected_last_mod_time"]

        result = await verify_file_modification_time(
            driver=self.driver,
            file_path=file_path,
            expected_last_mod_time=expected_last_mod_time,
            logger=self.logger,
        )

        if not result.success:
            self.add_failure(result.message)

        self.raise_failure_if_exists()


class VerifyPortSpeedStep(StepBase[taac_types.BaseInput]):
    STEP_NAME = taac_types.StepName.VERIFY_PORT_SPEED

    async def run(
        self,
        input: taac_types.BaseInput,
        params: t.Dict[str, t.Any],
    ) -> None:
        ports = params["ports"]
        speed_to_verify = params["speed_to_verify"]
        self.logger.info(
            f"Verifying that ports {ports} are running at {speed_to_verify}Gbps"
        )
        port_to_speed = await self.driver.async_get_interfaces_speed_in_Gbps(ports)
        for port, speed_in_gbps in port_to_speed.items():
            if speed_in_gbps != speed_to_verify:
                self.add_failure(
                    f"Speed verification failed for port {self.hostname}:{port}. Expected speed: {speed_to_verify}Gbps, Actual speed: {speed_in_gbps}Gbps"
                )
        self.raise_failure_if_exists()
        self.logger.info(
            f"Successfully verified that ports {ports} are operating at {speed_to_verify}Gbps"
        )


class VerifyPortOperationalStateStep(StepBase[taac_types.BaseInput]):
    """Verify the operational state (UP/DOWN) of network interfaces."""

    STEP_NAME = taac_types.StepName.VERIFY_PORT_OPERATIONAL_STATE

    async def run(
        self,
        input: taac_types.BaseInput,
        params: t.Dict[str, t.Any],
    ) -> None:
        interfaces: t.List[str] = params["interfaces"]
        # pyrefly: ignore [bad-assignment]
        operational_state: bool = params.get("operational_state")
        operational_state_map: t.Dict[str, bool] = params.get(
            "operational_state_map", {}
        )
        await self.async_check_interfaces_operational_state(
            interfaces, operational_state, operational_state_map
        )
        self.logger.info("All interfaces are in the desired operational state")

    @async_retryable(retries=30, sleep_time=6, exceptions=(Exception,))
    async def async_check_interfaces_operational_state(
        self,
        interfaces: t.List[str],
        operational_state: t.Optional[bool],
        operational_state_map: t.Optional[t.Dict[str, bool]],
    ) -> None:
        operational_state_map = operational_state_map or {}
        actual_interface_state_map = await self.driver.async_get_interfaces_status(
            interfaces
        )
        missing_interfaces = [
            interface
            for interface in interfaces
            if interface not in actual_interface_state_map
        ]
        if missing_interfaces:
            raise TestCaseFailure(
                f"Failed to fetch operational state for interfaces not found: {missing_interfaces}"
            )
        mismatched_interface_state_map = {
            interface: actual_state
            for interface, actual_state in actual_interface_state_map.items()
            if actual_state
            != (operational_state_map.get(interface) or none_throws(operational_state))
        }
        if mismatched_interface_state_map:
            err_msg = f"Operational state mismatch for interfaces: {mismatched_interface_state_map}"
            self.logger.debug(err_msg)
            raise TestCaseFailure(err_msg)


class RegisterPatcherStep(StepBase[taac_types.RegisterPatcherInput]):
    STEP_NAME = taac_types.StepName.REGISTER_PATCHER_STEP
    OPERATING_SYSTEMS = ["FBOSS"]

    def __init__(self, *args, **kwargs) -> None:
        super(RegisterPatcherStep, self).__init__(*args, **kwargs)
        self.registered_patcher_name: t.Optional[str] = None

    async def run(
        self,
        input: taac_types.RegisterPatcherInput,
        params: t.Dict[str, t.Any],
    ) -> None:
        if input.register_patcher:
            # pyre-fixme[16]
            await self.driver.async_register_python_patcher(
                input.config_name,
                patcher_name=input.name,
                py_func_name=input.py_func_name,
                patcher_args=dict(input.kwargs) if input.kwargs else {},
                patcher_desc=input.description,
            )
            self.registered_patcher_name = input.name
        else:
            # pyre-fixme[16]
            await self.driver.async_unregister_python_patcher(
                config_name=input.config_name,
                patcher_name=input.name,
            )

    async def cleanUp(
        self, input: taac_types.RegisterPatcherInput, params: t.Dict[str, t.Any]
    ) -> None:
        if self.registered_patcher_name:
            await async_unregister_patcher(
                self.hostname,
                input.config_name,
                self.registered_patcher_name,
            )


class AllocateCgroupSliceMemory(StepBase[taac_types.BaseInput]):
    STEP_NAME = taac_types.StepName.ALLOCATE_CGROUP_SLICE_MEMORY_STEP

    async def run(
        self,
        input: taac_types.BaseInput,
        params: t.Dict[str, t.Any],
    ) -> None:
        executable_path = params.get("executable_path", "/opt/memory_pressure")
        slice_name = params["slice_name"]
        keep_alive = params.get("keep_alive", False)
        initial_memory_allocation = params.get("initial_memory_allocation")
        ods_query_duration = params.get("ods_query_duration", 300)
        duration = params.get("duration", 300)
        minimum_memory_allocation = params.get("minimum_memory_allocation", 0)
        oom_score_adj = params.get("oom_score_adj", 0)

        # pyre-ignore
        if not await self.driver.async_check_if_file_exists(executable_path):
            raise Exception(
                f"Memory pressure script does not exist at {executable_path} on {self.hostname}"
            )

        end_time = int(time.time())
        start_time = end_time - ods_query_duration
        p90_memory_current = await async_get_memory_current_pct(
            self.hostname,
            slice_name,
            start_time,
            end_time,
        )

        if params.get("total_memory_pct_decimal") is not None:
            total_memory_pct = float(params["total_memory_pct_decimal"])
            memory_total = await self.driver.async_get_memory_total()  # pyre-ignore
            target_memory = total_memory_pct * memory_total
            self.driver.logger.info(
                f"Using total memory logic: total_memory_pct={total_memory_pct}, "
                f"memory_total={memory_total / (1024**3):.2f}GB, target_memory={target_memory / (1024**3):.2f}GB, "
                f"p90_memory_current={p90_memory_current / (1024**3):.2f}GB"
            )
            memory_to_allocate = max(
                int((target_memory - p90_memory_current) / 1024**2),
                minimum_memory_allocation,
            )
            self.driver.logger.info(
                f"Total memory logic result: memory_to_allocate={memory_to_allocate / (1024):.2f}GB"
            )
        elif params.get("workload_slice_based_total_memory_decimal") is not None:
            workload_slice_based_total_memory_decimal = float(
                params["workload_slice_based_total_memory_decimal"]
            )
            workload_max_mem = (
                await self.driver.async_get_workload_slice_max_allocated_memory()
            )
            target_memory = (
                workload_max_mem / 0.75
            ) * workload_slice_based_total_memory_decimal
            self.driver.logger.info(
                f"Using workload slice logic: workload_slice_based_total_memory_decimal={workload_slice_based_total_memory_decimal}, "
                f"workload_max_mem={workload_max_mem / (1024**3):.2f}GB, target_memory={target_memory / (1024**3):.2f}GB, "
                f"p90_memory_current={p90_memory_current / (1024**3):.2f}GB"
            )
            memory_to_allocate = max(
                int((target_memory - p90_memory_current) / 1024**2),
                minimum_memory_allocation,
            )
            self.driver.logger.info(
                f"Workload slice logic result: memory_to_allocate={memory_to_allocate / (1024):.2f}GB"
            )
        else:
            raise ValueError(
                "Either 'total_memory_pct_decimal' or 'workload_slice_based_total_memory_decimal' must be provided"
            )
        if memory_to_allocate <= 0:
            self.driver.logger.info(
                f"No memory allocation needed, calculated value: {memory_to_allocate}"
            )
            return
        allocate_memory_cmds = [
            f"{executable_path}",
            "-c",
            f"{slice_name}.slice",
            "-m",
            memory_to_allocate,
            "-t",
            duration,
        ]
        if keep_alive:
            allocate_memory_cmds.append("-k")
        if initial_memory_allocation:
            allocate_memory_cmds.extend(["-i", initial_memory_allocation])
        if oom_score_adj:
            allocate_memory_cmds.extend(["-s", oom_score_adj])
        allocate_memory_cmds = [str(cmd) for cmd in allocate_memory_cmds]
        run_in_thread(
            self.driver.async_run_cmd_on_shell, cmd=" ".join(allocate_memory_cmds)
        )


class ChronosNode(StepBase[taac_types.BaseInput]):
    STEP_NAME = taac_types.StepName.TOGGLE_IXIA_PREFIX_SESSION_FLAP

    def get_bgp_peer_regex(self, tag_names: t.List[str]) -> str:
        ixia = none_throws(self.ixia)
        bgp_peer_name = []
        device_group_objs = self.get_device_group_obj_from_tags(tag_names=tag_names)
        for device_group in device_group_objs:
            for ethernet in device_group.Ethernet.find():
                for ipv6 in ethernet.Ipv6.find():
                    bgp_peer = ipv6.BgpIpv6Peer.find()
                    if not bgp_peer:
                        continue
                    bgp_peer_name.append(bgp_peer.Name)
                for ipv4 in ethernet.Ipv4.find():
                    bgp_peer = ipv4.BgpIpv4Peer.find()
                    if not bgp_peer:
                        continue
                    bgp_peer_name.append(bgp_peer.Name)
        ixia.logger.info(f"BGP peer names under purview: {bgp_peer_name}")
        return "|".join(bgp_peer_name)

    def _collect_all_device_groups(self, device_group, all_dgs):
        all_dgs.append(device_group)
        for child_dg in device_group.DeviceGroup.find():
            self._collect_all_device_groups(child_dg, all_dgs)

    def get_device_group_obj_from_tags(self, tag_names: t.List[str]):
        ignored_golden_tag_names = ["NO_V6_PACKET_LOSS_EXPECTED"]
        ixia = none_throws(self.ixia)
        topologies = ixia.ixnetwork.Topology.find()
        device_group_objs = []
        for topology in topologies:
            all_dgs = []
            for device_group in topology.DeviceGroup.find():
                self._collect_all_device_groups(device_group, all_dgs)
            if not tag_names:
                ixia.logger.info(
                    f"No tag names provided. Flapping all device groups except with tag_name {ignored_golden_tag_names}"
                )
                for device_group in all_dgs:
                    ignored = False
                    for ignored_golden_tag_name in ignored_golden_tag_names:
                        if ignored_golden_tag_name in device_group.Name:
                            ixia.logger.info(
                                f"Ignoring device group {device_group.Name} with tag {ignored_golden_tag_name}"
                            )
                            ignored = True
                            break
                    if not ignored:
                        device_group_objs.append(device_group)
            else:
                for tag_name in tag_names:
                    for device_group in all_dgs:
                        if tag_name in device_group.Name:
                            ixia.logger.info(
                                f"For tag {tag_name} found {device_group.Name}"
                            )
                            device_group_objs.append(device_group)
        return device_group_objs

    def _collect_network_groups_from_dg(self, device_group, network_groups):
        for network_group in device_group.NetworkGroup.find():
            network_groups.append(network_group)
        for child_dg in device_group.DeviceGroup.find():
            self._collect_network_groups_from_dg(child_dg, network_groups)

    def get_network_group_name_regex(self, tag_names: t.List[str]):
        network_group_names = []
        ixia = none_throws(self.ixia)
        device_group_objs = self.get_device_group_obj_from_tags(tag_names=tag_names)
        for device_group_obj in device_group_objs:
            network_groups = []
            self._collect_network_groups_from_dg(device_group_obj, network_groups)
            for network_group in network_groups:
                network_group_names.append(network_group.Name)
        ixia.logger.info(f"Network group names: {network_group_names}")
        return "|".join(network_group_names)

    def _resolve_prefix_regex(
        self,
        prefix_flap_tag_names: t.Optional[t.List[str]],
        is_all_prefix_groups: bool,
    ) -> str:
        regex = ""
        if prefix_flap_tag_names:
            regex += self.get_network_group_name_regex(tag_names=prefix_flap_tag_names)
        elif is_all_prefix_groups:
            regex = self.get_network_group_name_regex(tag_names=[])
        if not regex:
            raise ValueError(
                "No network groups found for prefix flap. "
                f"prefix_flap_tag_names={prefix_flap_tag_names}, "
                f"is_all_prefix_groups={is_all_prefix_groups}"
            )
        return regex

    def _resolve_session_regex(
        self,
        session_flap_tag_names: t.Optional[t.List[str]],
        is_all_session_groups: bool,
    ) -> str:
        regex = ""
        if session_flap_tag_names:
            regex += self.get_bgp_peer_regex(tag_names=session_flap_tag_names)
        if is_all_session_groups is True:
            regex += self.get_bgp_peer_regex(tag_names=[])
        if not regex:
            raise ValueError(
                "No BGP peers found for session flap. "
                f"session_flap_tag_names={session_flap_tag_names}, "
                f"is_all_session_groups={is_all_session_groups}"
            )
        return regex

    async def run(
        self,
        input: taac_types.BaseInput,
        params: t.Dict[str, t.Any],
    ) -> None:
        ixia = none_throws(self.ixia)
        churn_mode = params["churn_mode"]
        enable_prefix_flap = params.get("enable_prefix_flap", False)
        enable_session_flap = params.get("enable_session_flap", False)
        is_all_prefix_groups = params.get("is_all_prefix_groups", False)
        is_all_session_groups = params.get("is_all_session_groups", False)
        session_flap_tag_names = params.get("session_flap_tag_names", None)
        prefix_flap_tag_names = params.get("prefix_flap_tag_names", None)
        churn_duration_s = params["churn_duration_s"]
        uptime_min_sec = params.get("uptime_min_sec", 15)
        uptime_max_sec = params.get("uptime_max_sec", 15)
        downtime_min_sec = params.get("downtime_min_sec", 15)
        downtime_max_sec = params.get("downtime_max_sec", 15)
        rerandomize_interval_s = params.get("rerandomize_interval_s", 0)
        uptime_sec, downtime_sec = pick_flap_timing(
            uptime_min_sec, uptime_max_sec, downtime_min_sec, downtime_max_sec
        )
        self.logger.info(
            f"Flap timing: uptime={uptime_sec}s, downtime={downtime_sec}s "
            f"(range [{uptime_min_sec}-{uptime_max_sec}] / [{downtime_min_sec}-{downtime_max_sec}])"
        )
        prefix_flap_network_group_regex = None
        session_flap_bgp_peer_regex_resolved = None
        if "prefix" in churn_mode:
            prefix_flap_network_group_regex = self._resolve_prefix_regex(
                prefix_flap_tag_names, is_all_prefix_groups
            )
        if "session" in churn_mode:
            session_flap_bgp_peer_regex_resolved = self._resolve_session_regex(
                session_flap_tag_names, is_all_session_groups
            )
        apply_flap_timing(
            ixia=ixia,
            churn_mode=churn_mode,
            uptime_sec=uptime_sec,
            downtime_sec=downtime_sec,
            enable_prefix_flap=enable_prefix_flap,
            prefix_flap_network_group_regex=prefix_flap_network_group_regex,
            enable_session_flap=enable_session_flap,
            session_flap_bgp_peer_regex=session_flap_bgp_peer_regex_resolved,
        )
        if churn_duration_s > 0 and rerandomize_interval_s > 0:
            start = time.time()
            while (time.time() - start) < churn_duration_s:
                sleep_time = min(
                    rerandomize_interval_s, churn_duration_s - (time.time() - start)
                )
                if sleep_time <= 0:
                    break
                await asyncio.sleep(sleep_time)
                uptime_sec, downtime_sec = pick_flap_timing(
                    uptime_min_sec,
                    uptime_max_sec,
                    downtime_min_sec,
                    downtime_max_sec,
                )
                self.logger.info(
                    f"Re-randomizing flap timing: uptime={uptime_sec}s, downtime={downtime_sec}s"
                )
                apply_flap_timing(
                    ixia=ixia,
                    churn_mode=churn_mode,
                    uptime_sec=uptime_sec,
                    downtime_sec=downtime_sec,
                    enable_prefix_flap=enable_prefix_flap,
                    prefix_flap_network_group_regex=prefix_flap_network_group_regex,
                    enable_session_flap=enable_session_flap,
                    session_flap_bgp_peer_regex=session_flap_bgp_peer_regex_resolved,
                )
        elif churn_duration_s > 0:
            self.logger.info(
                f"Flap operation completed. Sleeping for {churn_duration_s} seconds"
            )
            await asyncio.sleep(churn_duration_s)
        else:
            self.logger.info("Flap operation completed (non-blocking).")


class InterfaceFlapStep(StepBase[taac_types.BaseInput]):
    STEP_NAME = taac_types.StepName.INTERFACE_FLAP_STEP

    async def run(
        self,
        input: taac_types.BaseInput,
        params: t.Dict[str, t.Any],
    ) -> None:
        interfaces = params["interfaces"]
        device_name = params.get("device_name", self.device.name)
        self.driver = await async_get_device_driver(device_name)
        raw_interfaces = try_json_loads(interfaces)
        parsed_names = []
        for iface in raw_interfaces:
            parsed = try_json_to_thrift(iface, taac_types.TestInterface)
            if isinstance(parsed, taac_types.TestInterface):
                parsed_names.append(parsed.interface_name)
            elif isinstance(parsed, str):
                parsed_names.append(parsed)
            else:
                raise TypeError(
                    f"Cannot parse interface {iface!r} as TestInterface or string"
                )
        interfaces = parsed_names
        delay = params.get("delay", 5)
        enable = params["enable"]
        sequential = params.get("sequential", False)
        interface_flap_method = taac_types.InterfaceFlapMethod(
            params["interface_flap_method"]
        )
        await self.async_flap_interfaces(
            device_name,
            interfaces,
            interface_flap_method,
            enable,
            sequential,
        )
        if delay:
            self.logger.info(f"Sleeping for {delay} seconds...")
            await asyncio.sleep(delay)

    async def async_flap_interfaces(
        self,
        hostname: str,
        interface_names: t.List[str],
        interface_flap_method: taac_types.InterfaceFlapMethod,
        enable: bool,
        sequential: bool,
    ) -> None:
        # Lazy import of internal driver class.
        from taac.internal.driver.arista_switch import (
            AristaSwitch,
        )

        if (
            isinstance(self.driver, AristaSwitch)
            and interface_flap_method
            != taac_types.InterfaceFlapMethod.SSH_PORT_STATE_CHANGE
        ):
            raise NotImplementedError(
                f"Interface flap method {interface_flap_method} not supported for EOS devices. "
                "Only SSH_PORT_STATE_CHANGE is supported for EOS devices"
            )
        if (
            interface_flap_method
            == taac_types.InterfaceFlapMethod.THRIFT_PORT_STATE_CHANGE
        ):
            success: bool = await self.flap_with_thrift(
                interface_names, enable, sequential
            )
            if not success:
                await self.flap_with_ssh(interface_names, enable, sequential)
        elif (
            interface_flap_method
            == taac_types.InterfaceFlapMethod.FBOSS_WEDGE_QSFP_UTIL_TX
        ):
            subcmd: str = "--tx_enable" if enable else "--tx_disable"
            await self.flap_with_shell_cmd(interface_names, subcmd, sequential)
        elif (
            interface_flap_method
            == taac_types.InterfaceFlapMethod.FBOSS_WEDGE_QSFP_UTIL_POWER
        ):
            subcmd: str = "--clear_low_power" if enable else "--set_low_power"
            await self.flap_with_shell_cmd(interface_names, subcmd, sequential)
        elif (
            interface_flap_method
            == taac_types.InterfaceFlapMethod.SSH_PORT_STATE_CHANGE
        ):
            await self.flap_with_ssh(interface_names, enable, sequential)
        elif (
            interface_flap_method
            == taac_types.InterfaceFlapMethod.FBOSS_WEDGE_QSFP_RESET
        ):
            subcmd: str = "--qsfp-reset"
            await self.flap_with_shell_cmd(interface_names, subcmd, sequential)
        else:
            raise NotImplementedError(
                f"Interface flap method {interface_flap_method} not supported"
            )
        action: str = "enabled" if enable else "disabled"
        self.logger.info(
            f"Successfully {action} interfaces {interface_names} via {interface_flap_method.name}"
        )

    async def run_coroutines(
        self,
        coros: t.List[t.Coroutine],
        sequential: bool,
    ) -> None:
        if sequential:
            for coro in coros:
                try:
                    await coro
                except Exception as e:
                    self.logger.debug(f"Error during interface flap: {e}")
                    raise
        else:
            results = await asyncio.gather(*coros, return_exceptions=True)
            for result in results:
                if isinstance(result, Exception):
                    self.logger.debug(f"Error during interface flap: {result}")
                    raise result

    async def flap_with_thrift(
        self,
        interface_names: t.List[str],
        enable: bool,
        sequential: bool,
    ) -> bool:
        try:
            interfaces_info = (
                # pyre-ignore
                await self.driver.async_get_all_interfaces_info()
            )
            coros = [
                # pyre-ignore
                self.driver.async_set_port_state(interfaces_info[iface].port_id, enable)
                for iface in interface_names
            ]
            await self.run_coroutines(coros, sequential)
            return True
        except Exception as e:
            self.logger.debug(
                f"THRIFT_PORT_STATE_CHANGE failed: {e}. Falling back to SSH_PORT_STATE_CHANGE."
            )
            return False

    async def flap_with_ssh(
        self,
        interface_names: t.List[str],
        enable: bool,
        sequential: bool,
    ) -> None:
        coros = [
            self.driver.async_enable_ports_via_ssh([iface], enable)
            for iface in interface_names
        ]
        await self.run_coroutines(coros, sequential)

    async def flap_with_shell_cmd(
        self,
        interface_names: t.List[str],
        subcmd: str,
        sequential: bool,
    ) -> None:
        coros = []
        if not sequential:
            ifaces = " ".join(interface_names)
            coros = [
                self.driver.async_run_cmd_on_shell(f"wedge_qsfp_util {subcmd} {ifaces}")
            ]
        else:
            coros = [
                self.driver.async_run_cmd_on_shell(f"wedge_qsfp_util {subcmd} {iface}")
                for iface in interface_names
            ]
        await self.run_coroutines(coros, sequential)


PATCHER_NAME = "configure_port_channel_min_link_percentage"
PATCHER_DESCRIPTION = "Configuration of port channel minimum link capacity percentage for DNE Solution Test"
AGENT_CONFIG = "agent"


class RegisterPortChannelMinLinkPercentagePatchers(StepBase[taac_types.BaseInput]):
    """Register patchers for port channel min link capacity percentage."""

    STEP_NAME = taac_types.StepName.REGISTER_PORT_CHANNEL_MIN_LINK_PERCENTAGE_PATCHERS

    async def run(
        self,
        input: taac_types.BaseInput,
        params: t.Dict[str, t.Any],
    ) -> None:
        port_channel_name = params["port_channel_name"]
        min_link_percentage = params.get("min_link_percentage")
        min_link_up_percentage = params.get("min_link_up_percentage")
        patcher_name = params.get("patcher_name", PATCHER_NAME)
        register_patchers = params.get("register_patchers", True)
        neighbor_hostname, neighbor_interface = none_throws(
            await self.driver.async_get_interface_neighbor(port_channel_name)
        )
        await self._register_and_apply_port_channel_min_link_percentage_patcher(
            self.driver,
            register_patchers,
            patcher_name,
            port_channel_name,
            min_link_percentage,
            min_link_up_percentage,
        )
        if "eb" not in neighbor_hostname:
            neighbor_driver = await async_get_device_driver(neighbor_hostname)
            neighbor_aggregated_interfaces = (
                # pyre-fixme[16]
                await neighbor_driver.async_get_all_aggregated_interfaces()
            )
            neighbor_port_channel_name = none_throws(
                next(
                    (
                        agg_name
                        for agg_name, member_ports in neighbor_aggregated_interfaces.items()
                        if neighbor_interface in member_ports
                    ),
                    None,
                )
            )
            await self._register_and_apply_port_channel_min_link_percentage_patcher(
                neighbor_driver,
                register_patchers,
                patcher_name,
                # pyrefly: ignore [bad-argument-type]
                neighbor_port_channel_name,
                min_link_percentage,
                min_link_up_percentage,
            )

    def _build_patcher_args(
        self,
        port_channel_name: str,
        min_link_percentage: float,
        min_link_up_percentage: t.Optional[float] = None,
    ):
        patcher_args = {
            "link_percentage": str(min_link_percentage),
            "port_channel_name": port_channel_name,
        }
        if min_link_up_percentage is not None:
            patcher_args["min_link_up_percentage"] = str(min_link_up_percentage)
        return patcher_args

    async def _register_and_apply_port_channel_min_link_percentage_patcher(
        self,
        driver: t.Any,  # FbossSwitch — typed loosely to keep BUCK target light
        register_patcher: bool,
        patcher_name: str,
        port_channel_name: str,
        min_link_percentage: t.Optional[float],
        min_link_up_percentage: t.Optional[float] = None,
    ):
        if register_patcher:
            await driver.async_register_python_patcher(
                patcher_name=patcher_name,
                patcher_args=self._build_patcher_args(
                    port_channel_name,
                    none_throws(min_link_percentage),
                    min_link_up_percentage,
                ),
                config_name=AGENT_CONFIG,
                py_func_name="set_port_channel_min_link_capacity",
                patcher_desc=PATCHER_DESCRIPTION,
            )
        else:
            await driver.async_unregister_python_patcher(patcher_name, AGENT_CONFIG)
        await driver.async_create_cold_boot_file()
        await driver.async_restart_service(FbossSystemctlServiceName.AGENT)
        await driver.async_wait_for_agent_configured()


_SPEED_FLIP_PATCHER_NAME = "test_speed_flip_patcher"
_SUPPORTED_51T_SPEED_COMBINATIONS = {
    (100, 100),
    (200, 400),
    (200, 200),
    (400, 400),
}
_PLATFORM_SPEED_PROFILE_MAPPING = {
    "MONTBLANC": {
        PortSpeed.EIGHTHUNDREDG: "PROFILE_800G_8_PAM4_RS544X2N_OPTICAL",
        PortSpeed.FOURHUNDREDG: "PROFILE_400G_4_PAM4_RS544X2N_OPTICAL",
        PortSpeed.TWOHUNDREDG: "PROFILE_200G_4_PAM4_RS544X2N_OPTICAL",
        PortSpeed.HUNDREDG: "PROFILE_100G_4_NRZ_RS528_OPTICAL",
    },
    "MORGAN800CC": {
        PortSpeed.EIGHTHUNDREDG: "PROFILE_800G_8_PAM4_RS544X2N_OPTICAL",
        PortSpeed.FOURHUNDREDG: "PROFILE_400G_4_PAM4_RS544X2N_OPTICAL",
        PortSpeed.TWOHUNDREDG: "PROFILE_200G_4_PAM4_RS544X2N_OPTICAL",
        PortSpeed.HUNDREDG: "PROFILE_100G_4_NRZ_RS528_OPTICAL",
    },
    "WEDGE400C": {
        PortSpeed.FOURHUNDREDG: "PROFILE_400G_8_PAM4_RS544X2N_OPTICAL",
        PortSpeed.HUNDREDG: "PROFILE_100G_4_NRZ_RS528_OPTICAL",
        PortSpeed.TWOHUNDREDG: "PROFILE_200G_4_PAM4_RS544X2N_OPTICAL",
    },
    "WEDGE400": {
        PortSpeed.FOURHUNDREDG: "PROFILE_400G_8_PAM4_RS544X2N_OPTICAL",
        PortSpeed.HUNDREDG: "PROFILE_100G_4_NRZ_RS528_OPTICAL",
        PortSpeed.TWOHUNDREDG: "PROFILE_200G_4_PAM4_RS544X2N_OPTICAL",
    },
    "ELBERT": {
        PortSpeed.FOURHUNDREDG: "PROFILE_400G_8_PAM4_RS544X2N_OPTICAL",
        PortSpeed.HUNDREDG: "PROFILE_100G_4_NRZ_RS528_OPTICAL",
        PortSpeed.TWOHUNDREDG: "PROFILE_200G_4_PAM4_RS544X2N_OPTICAL",
    },
    "FUJI": {
        PortSpeed.FOURHUNDREDG: "PROFILE_400G_8_PAM4_RS544X2N_OPTICAL",
        PortSpeed.HUNDREDG: "PROFILE_100G_4_NRZ_RS528_OPTICAL",
        PortSpeed.TWOHUNDREDG: "PROFILE_200G_4_PAM4_RS544X2N_OPTICAL",
    },
    "DARWIN": {
        PortSpeed.FOURHUNDREDG: "PROFILE_400G_8_PAM4_RS544X2N_OPTICAL",
        PortSpeed.HUNDREDG: "PROFILE_100G_4_NRZ_RS528_OPTICAL",
        PortSpeed.TWOHUNDREDG: "PROFILE_200G_4_PAM4_RS544X2N_OPTICAL",
    },
    "YAMP": {
        PortSpeed.HUNDREDG: "PROFILE_100G_4_NRZ_RS528_OPTICAL",
        PortSpeed.TWOHUNDREDG: "PROFILE_200G_4_PAM4_RS544X2N_OPTICAL",
    },
    "MINIPACK": {
        PortSpeed.HUNDREDG: "PROFILE_100G_4_NRZ_RS528_OPTICAL",
        PortSpeed.TWOHUNDREDG: "PROFILE_200G_4_PAM4_RS544X2N_OPTICAL",
    },
}


class UnsupportedSpeedCombinationError(Exception):
    pass


@dataclass(frozen=True)
class _SpeedFlipDeviceInfo:
    ports: t.List[str]
    driver: t.Any  # FbossSwitch (not imported here to keep BUCK target light)
    hostname: str
    hardware_type: str


class RegisterSpeedFlipPatcherStep(StepBase[taac_types.BaseInput]):
    STEP_NAME = taac_types.StepName.REGISTER_SPEED_FLIP_PATCHER
    OPERATING_SYSTEMS = ["FBOSS"]

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.registered_patcher_name: t.Optional[str] = None

    async def run(
        self,
        input: taac_types.BaseInput,
        params: t.Dict[str, t.Any],
    ) -> None:
        register_patcher = params["register_patcher"]
        port_state_change = params["port_state_change"]
        patcher_name = params.get("patcher_name", _SPEED_FLIP_PATCHER_NAME)
        endpoints = params["endpoints"]
        target_port_cage_count = params.get("target_port_cage_count", 4)
        self._assert_target_port_cage_count(endpoints, target_port_cage_count)
        device_infos = await self._gather_device_infos(endpoints)
        speed_in_gbps = params.get("speed_in_gbps", 0)

        if port_state_change:
            await self._disable_device_ports(device_infos)

        if register_patcher:
            await self._register_speed_flip_patchers(
                device_infos=device_infos,
                speed_in_gbps=speed_in_gbps,
                patcher_name=patcher_name,
            )
        else:
            await self._unregister_speed_flip_patchers(
                patcher_name=patcher_name,
                device_infos=device_infos,
            )

        await self._warmboot_agent(device_infos=device_infos)

    def _assert_target_port_cage_count(
        self,
        endpoints: t.Dict[str, t.List[str]],
        target_port_cage_count: int,
    ) -> None:
        """Enforce that each device supplies >= ``target_port_cage_count`` dual-cage ports.

        A dual-cage port is identified by its cage base (the interface name minus
        the trailing subport, e.g. ``eth1/17/1`` and ``eth1/17/5`` both belong to
        cage ``eth1/17``). This is a runtime gate: the onus is on the POC
        configuring/running the speed-flip test to supply at least the target
        number of cages per device. It is intentionally generic so it applies to
        any speed-flip TestConfig, not just the ones in speed_flip_test_configs.
        """
        for hostname, ports in endpoints.items():
            cages = {port.rsplit("/", 1)[0] for port in ports}
            if len(cages) < target_port_cage_count:
                raise AssertionError(
                    f"Speed-flip requires at least {target_port_cage_count} "
                    f"dual-cage ports on {hostname}, but only {len(cages)} "
                    f"were supplied (cages={sorted(cages)}, ports={ports}). "
                    f"Provide at least {target_port_cage_count} distinct cages."
                )

    async def _gather_device_infos(
        self, endpoints: t.Dict[str, t.List[str]]
    ) -> t.List[_SpeedFlipDeviceInfo]:
        device_infos = []
        for hostname, ports in endpoints.items():
            if not ports:
                self.logger.warning(
                    f"No ports specified for {hostname} in endpoints. Skipping speed flip patcher."
                )
                continue
            device_driver = await async_get_device_driver(hostname)
            await device_driver.async_wait_for_agent_configured()
            hardware_type = self.device.attributes.hardware
            device_infos.append(
                _SpeedFlipDeviceInfo(
                    ports=ports,
                    driver=device_driver,
                    hostname=hostname,
                    hardware_type=hardware_type,
                )
            )
        return device_infos

    async def _disable_device_ports(
        self, device_infos: t.List[_SpeedFlipDeviceInfo]
    ) -> None:
        await asyncio.gather(
            *[
                device_info.driver.async_thrift_disable_enable_interfaces(
                    interface_names=device_info.ports, is_enable_port=False
                )
                for device_info in device_infos
            ]
        )

    async def _warmboot_agent(self, device_infos: t.List[_SpeedFlipDeviceInfo]) -> None:
        await asyncio.gather(
            *[
                device_info.driver.async_apply_patchers(
                    taac_types.ApplyPatcherMethod.AGENT_WARMBOOT
                )
                for device_info in device_infos
            ]
        )
        await asyncio.gather(
            *[
                device_info.driver.async_wait_for_agent_configured()
                for device_info in device_infos
            ]
        )

    async def _register_speed_flip_patchers(
        self,
        device_infos: t.List[_SpeedFlipDeviceInfo],
        speed_in_gbps: int,
        patcher_name: str,
    ) -> None:
        speed_in_mbps = speed_in_gbps * 1000
        coros = []
        for device_info in device_infos:
            profile_id = _PLATFORM_SPEED_PROFILE_MAPPING.get(
                device_info.hardware_type,
                {},
                # pyrefly: ignore [bad-index]
            )[speed_in_mbps]
            coros.append(
                device_info.driver.async_change_speed_patcher(
                    device_info.ports,
                    desired_speed=PortSpeed(speed_in_mbps).name,
                    profile_id=profile_id,
                    patcher_name=patcher_name,
                )
            )
        await asyncio.gather(*coros)

    async def _unregister_speed_flip_patchers(
        self,
        patcher_name: str,
        device_infos: t.List[_SpeedFlipDeviceInfo],
    ) -> None:
        await asyncio.gather(
            *[
                device_info.driver.async_coop_unregister_patchers(patcher_name)
                for device_info in device_infos
            ]
        )

    async def validate_speed_flip_ports(
        self, device_info: _SpeedFlipDeviceInfo, speed: int
    ) -> None:
        SUPPORTED_HARDWARE = {"MONTBLANC", "MORGAN800CC"}
        if device_info.hardware_type not in SUPPORTED_HARDWARE:
            return
        port_to_adjacent = {
            port: self._get_51t_adjacent_port(port) for port in device_info.ports
        }
        adjacent_ports = list(port_to_adjacent.values())
        adjacent_speeds = await device_info.driver.async_get_interfaces_speed_in_Gbps(
            adjacent_ports
        )
        violations = []
        for port, adjacent_port in port_to_adjacent.items():
            adjacent_speed = adjacent_speeds[adjacent_port]
            if (speed, adjacent_speed) not in _SUPPORTED_51T_SPEED_COMBINATIONS and (
                adjacent_speed,
                speed,
            ) not in _SUPPORTED_51T_SPEED_COMBINATIONS:
                violations.append(
                    f"Speed flip not supported for {port} <-> {adjacent_port} "
                    f"with speeds {speed} and {adjacent_speed}"
                )
        if violations:
            raise UnsupportedSpeedCombinationError(
                "Speed flip is not supported due to the following violations:\n"
                + "\n".join(violations)
            )

    def _get_51t_adjacent_port(self, port: str) -> str:
        pim, slot, num = port.split("/")
        if num == "1":
            return f"{pim}/{slot}/5"
        return f"{pim}/{slot}/1"


# =============================================================================
# CONCRETE STEP RUNTIME CLASSES (migrated from internal/steps/)
# =============================================================================

_WEDGE_POWER_CMD: str = "/usr/local/bin/wedge_power.sh"


class SystemRebootStep(StepBase[taac_types.SystemRebootInput]):
    STEP_NAME = taac_types.StepName.SYSTEM_REBOOT_STEP

    async def run(
        self,
        input: taac_types.SystemRebootInput,
        params: t.Dict[str, t.Any],
    ) -> None:
        start_time = time.time()
        sleep_time_after_reboot = params.get("sleep_time_after_reboot", 0)
        if input.trigger == taac_types.SystemRebootTrigger.FULL_SYSTEM_REBOOT:
            await self.driver.async_full_system_reboot()
            self.logger.info(
                f"Sleeping 120 seconds for {self.device.name} to gracefully shut down..."
            )
            await asyncio.sleep(120)
        elif (
            input.trigger == taac_types.SystemRebootTrigger.BMC_POWER_RESET
            and self.is_fboss
        ):
            wedge_power_reset = f"{_WEDGE_POWER_CMD} reset"
            run_bmc_cmd_hwcontrol(self.device.name, wedge_power_reset)
            self.logger.info(
                f"Successfully initiated the system reboot via the BMC command: {wedge_power_reset}"
            )
        elif (
            input.trigger == taac_types.SystemRebootTrigger.BMC_MICROSERVER_ONLY_RESET
            and self.is_fboss
        ):
            wedge_power_microserver_reset = f"{_WEDGE_POWER_CMD} reset -s"
            run_bmc_cmd_hwcontrol(self.device.name, wedge_power_microserver_reset)
            self.logger.info(
                f"Successfully initiated the system reboot via the BMC command: {wedge_power_microserver_reset}"
            )
        if sleep_time_after_reboot > 0:
            self.logger.info(
                f"Waiting for {sleep_time_after_reboot} seconds after reboot"
            )
            await asyncio.sleep(sleep_time_after_reboot)

        self.logger.info(f"Waiting for {self.device.name} to be pingable...")
        await convert_to_async(wait_for_ping_reachable, ssh_entity=self.device.name)
        self.logger.info(
            f"{self.device.name} is pingable {time.time() - start_time} seconds after {input.trigger.name}"
        )
        self.logger.info("Waiting for device to be ssh-able...")
        await self.driver.wait_for_ssh_reachable()
        self.logger.debug(
            f"{self.device.name} is ssh-able {time.time() - start_time} seconds after {input.trigger.name}"
        )


class InjectRoutesStep(StepBase[taac_types.BaseInput]):
    STEP_NAME = taac_types.StepName.INJECT_ROUTES_STEP

    async def run(
        self, input: taac_types.BaseInput, params: t.Dict[str, t.Any]
    ) -> None:
        hostname = params["hostname"]
        port = params.get("port", None)
        start_ipv4s = params.get("start_ipv4s", [])
        start_ipv6s = params.get("start_ipv6s", [])
        count = params.get("count", 1)
        step_param = params.get("step", 1)
        local_link = params.get("local_link", {})
        other_link = params.get("other_link", {})
        mask = params.get("mask", -1)
        action = params.get("action", "inject")
        duration = params.get("duration", None)
        frequency = params.get("frequency", None)
        delete_count = params.get("delete_count", 0)
        sequential = params.get("sequential", None)
        update_count = params.get("update_count", -1)

        route_manager = OpenRRouteManager(logger=self.logger)
        try:
            await route_manager.execute_route_action_openr(
                hostname=hostname,
                action=action,
                start_ipv4s=start_ipv4s,
                start_ipv6s=start_ipv6s,
                local_link=local_link,
                other_link=other_link,
                count=count,
                step=step_param,
                mask=mask,
                port=port,
                duration=duration,
                frequency=frequency,
                delete_count=delete_count,
                sequential=sequential,
                update_count=update_count,
            )
        except Exception as e:
            self.add_failure(str(e))
        self.raise_failure_if_exists()


class ValidationStep(StepBase[taac_types.ValidationInput]):
    STEP_NAME = taac_types.StepName.VALIDATION_STEP

    async def _run(
        self,
        input: taac_types.ValidationInput,
        params: t.Dict[str, t.Any],
    ) -> None:
        try:
            await super()._run(input, params)
        except (TestbedError, TestCaseFailure) as e:
            raise e

    async def run(  # noqa: C901
        self,
        input: taac_types.ValidationInput,
        params: t.Dict[str, t.Any],
    ) -> None:
        if input.stage == taac_types.ValidationStage.PRE_TEST:
            exception_cls = TestbedError
        elif input.stage == taac_types.ValidationStage.POST_TEST:
            exception_cls = TestCaseFailure
        else:
            exception_cls = None
        all_check_results = []
        all_check_device_names = []
        all_check_ids = []
        priority_to_hcs = defaultdict(list)
        for check in input.point_in_time_checks:
            check_impl = NAME_TO_POINT_IN_TIME_HEALTH_CHECK[check.name]
            check_priority = check.priority or check_impl.DEFAULT_PRIORITY
            priority_to_hcs[check_priority].append(check)
        priority_to_hcs = dict(sorted(priority_to_hcs.items()))

        for priority, checks in priority_to_hcs.items():
            check_names = [c.name.name for c in checks]
            self.logger.info(
                f"Running {len(checks)} check(s) at priority {priority}: {check_names}"
            )
            checks_to_run = []
            for check in checks:
                check_impl = NAME_TO_POINT_IN_TIME_HEALTH_CHECK[check.name]
                check_impl_obj = check_impl(self.logger, self.ixia)  # pyre-ignore
                input_struct = HEALTH_CHECK_NAME_TO_INPUT[check.name]
                check_input = (
                    json_to_thrift(check.input_json, input_struct)
                    if check.input_json
                    else None
                )
                default_input = input_struct()
                check_params = self.parameter_evaluator.evaluate(check.check_params)
                if issubclass(check_impl, AbstractIxiaHealthCheck):
                    if not self.ixia:
                        self.logger.info(
                            f"Ixia setup not found. Skipping Ixia health check {check.name}"
                        )
                        continue
                    checks_to_run.append(
                        (
                            check_impl_obj.run_wrapper(
                                # pyrefly: ignore [bad-argument-type]
                                self.ixia,
                                check_input,
                                default_input,
                                check_params,
                            ),
                            [self.device],
                        )
                    )
                elif issubclass(check_impl, AbstractDeviceHealthCheck):
                    devices = (
                        self.topology.devices
                        if (check.check_scope or check_impl.CHECK_SCOPE)
                        == hc_types.Scope.TOPOLOGY
                        else [self.device]
                    )
                    checks_to_run.extend(
                        [
                            (
                                check_impl(  # pyre-ignore[45]
                                    self.logger, self.ixia
                                ).run_wrapper(
                                    device, check_input, default_input, check_params
                                ),
                                [device],
                            )
                            for device in devices
                        ]
                    )
                elif issubclass(check_impl, AbstractTopologyHealthCheck):
                    checks_to_run.append(
                        (
                            check_impl_obj.run_wrapper(
                                # pyrefly: ignore [bad-argument-type]
                                self.topology,
                                check_input,
                                default_input,
                                check_params,
                            ),
                            self.topology.devices,
                        )
                    )
            check_results = await asyncio.gather(
                *[check_to_run[0] for check_to_run in checks_to_run],
            )
            for check_result, devices in zip(
                check_results, [check_to_run[1] for check_to_run in checks_to_run]
            ):
                test_result = await async_write_test_result(
                    self.test_case_name,
                    devices=devices,
                    test_status=check_result.status,
                    start_time=self.test_case_start_time,
                    check_name=check_result.name.name,
                    check_stage=input.stage,
                    message=check_result.message,
                )
                self.test_case_results.append(test_result)
            failed_checks = self.check_failure(check_results)  # pyre-ignore[6]
            if failed_checks and input.fail_fast and exception_cls:
                raise exception_cls(
                    f"Health check(s) {[check.name for check in failed_checks]} failed."
                )
            for check_result, check_to_run in zip(check_results, checks_to_run):
                all_check_results.append(check_result)
                devices = check_to_run[1]
                all_check_device_names.append(", ".join(d.name for d in devices))

            for check in checks:
                all_check_ids.append(getattr(check, "check_id", None))

        stage_name = input.stage.name if input.stage else "HEALTH CHECK"
        summary_results = []
        for result, device_name, check_id in zip(
            all_check_results, all_check_device_names, all_check_ids
        ):
            status_str = result.status.name if result.status else "UNKNOWN"
            if status_str in ("PASS", "PASSED", "SUCCESS"):
                display_status = "PASS"
            elif status_str in ("FAIL", "FAILED", "FAILURE"):
                display_status = "FAIL"
            else:
                display_status = status_str
            msg = result.message or ""
            if "\n" in msg:
                msg = msg.split("\n")[0]
            check_display = result.name.name
            if check_id and result.name == hc_types.CheckName.GENERIC_ODS_CHECK:
                check_display = f"{check_display} ({check_id})"
            summary_results.append(
                {
                    "check_name": f"{device_name}: {check_display}",
                    "status": display_status,
                    "message": msg[:60],
                }
            )
        log_results_table(
            title=f"{stage_name} HEALTH CHECK RESULTS",
            results=summary_results,
            logger=self.logger,
        )

        failed_checks = self.check_failure(all_check_results)
        if failed_checks and exception_cls:
            raise exception_cls(
                f"Health check(s) {[check.name for check in failed_checks]} failed."
            )

    def check_failure(
        self, check_results: t.List[hc_types.HealthCheckResult]
    ) -> t.List[hc_types.HealthCheckResult]:
        return [
            check_result
            for check_result in check_results
            if check_result.status in FAILED_HC_STATUSES
        ]

    async def log_to_scuba(
        self,
        hostname: str,
        hc_obj: AbstractDeviceHealthCheck,
        check_result: hc_types.HealthCheckResult,
    ) -> None:
        if not hc_obj.__class__.LOG_TO_SCUBA:
            return
        fboss_versions = await async_get_fboss_versions(hostname)
        sample = Sample()
        sample.addTimestamp(ScubaData.TIME_COLUMN, int(time.time()))
        sample.addNormalValue("hostname", hostname)
        sample.addNormalValue("check_name", hc_obj.__class__.__name__)
        sample.addNormalValue("check_status", check_result.status.name)
        relevant_activities = [
            "fboss_qsfp_service",
            "fboss_agent",
            "fboss_bgp",
            "fboss_fsdb",
        ]
        for version in fboss_versions:
            if version.activity in relevant_activities:
                sample.addNormalValue(version.activity, str(version.versions.current))
        data_to_log_json = json.dumps(hc_obj.data_to_log)
        sample.addNormalValue("additional_data", data_to_log_json)
        with ScubaData(TAAC_HEALTH_CHECK_SCUBA_TABLE) as scubadata:
            try:
                scubadata.add_sample(sample)
            except Exception as ex:
                self.logger.error(f"Error logging result to scuba: {ex}")


# =============================================================================
# FILE-LOCAL HELPERS PROMOTED TO CENTRAL (Phase 7-B30)
# Previously file-local underscore-private helpers in test configs / playbooks.
# Centralized here for discoverability per the step-helper centralization mandate.
# =============================================================================


def create_lag_cleanup_steps(
    all_member_interfaces: t.List[str],
) -> t.List[Step]:
    """Build the teardown step list for a LAG / port-channel test.

    Returns two steps in order: (1) re-enable every interface in
    `all_member_interfaces`, then (2) verify the port-channel itself is
    operationally UP. Use as the tail of any playbook that flapped LAG
    members so the testbed is left in a clean state.

    Args:
        port_channel_name: Name of the port-channel interface to verify.
        all_member_interfaces: All physical members of the port-channel
            that should be re-enabled.

    Returns:
        A list of two `Step`s — one `INTERFACE_FLAP_STEP` and one
        `VERIFY_PORT_OPERATIONAL_STATE` — ready to inline into a
        teardown stage.
    """
    return [
        create_interface_flap_step(enable=True, interfaces=all_member_interfaces),
        create_verify_port_operational_state_step(
            interfaces=all_member_interfaces, operational_state=True
        ),
    ]


def create_lag_permanent_cleanup_steps() -> list[taac_types.Step]:
    return [
        create_unregister_patcher_step(
            patcher_name="permanently_disable_interface_patcher", config_name="agent"
        ),
    ]


def create_port_speed_validation_step(
    health_check_params: t.Dict[str, t.Any],
) -> Step:
    """Build a validation step around the PORT_SPEED_CHECK health check.

    Wraps `create_port_speed_check` in a `VALIDATION_STEP` so it can be
    dropped into a stage's mid-test verification slot. Used by speed-flip
    test configs to assert that ports are operating at the expected
    line rate after a speed-toggle event.

    Args:
        health_check_params: Raw dict passed verbatim to
            `create_port_speed_check`. Typically contains the target
            interfaces and expected speeds (Gbps).

    Returns:
        A `Step` with `step_name=StepName.VALIDATION_STEP` running
        `PORT_SPEED_CHECK`.
    """
    from taac.health_checks.healthcheck_definitions import (
        create_port_speed_check,
    )

    return create_validation_step(
        point_in_time_checks=[create_port_speed_check(health_check_params)],
    )


def create_best_path_baseline_step(
    device_name: str,
    churn_prefix_patterns: t.List[str],
    max_probes: int = 50,
) -> Step:
    """Snapshot pre-churn best-path selections for later comparison.

    Runs the `verify_best_path_changes` task in `baseline` mode, sampling
    up to `max_probes` BGP best-paths matching `churn_prefix_patterns`
    on the DUT and stashing them in shared task state. Pair with
    `create_best_path_verify_step` (run after churn) to assert the
    expected fraction of best-paths actually changed. Used in
    best-path-eval test configs.

    Args:
        device_name: Hostname of the DUT to probe.
        churn_prefix_patterns: List of prefix patterns whose best-paths
            should be sampled (typically the prefix groups under churn).
        max_probes: Cap on the number of prefixes sampled. Default 50.

    Returns:
        A `Step` with `step_name=StepName.RUN_TASK_STEP` invoking
        `verify_best_path_changes` in baseline mode.
    """
    return create_run_task_step(
        task_name="verify_best_path_changes",
        params_dict={
            "hostname": device_name,
            "mode": "baseline",
            "churn_patterns": churn_prefix_patterns,
            "max_probes": max_probes,
        },
        description="Capture best-path baseline before churn",
    )


def create_best_path_verify_step(
    device_name: str,
    churn_prefix_patterns: t.List[str],
    max_probes: int = 50,
    min_changed_ratio: float = 0.3,
) -> Step:
    """Assert at least `min_changed_ratio` of best-paths changed post-churn.

    Counterpart to `create_best_path_baseline_step`. Re-samples the same
    prefix set, compares against the baseline, and fails if fewer than
    `min_changed_ratio` of the probed best-paths changed (which would
    indicate the churn step did not actually move best-path selection,
    e.g. because LOCAL_PREF / MED churn was clamped). Used in
    best-path-eval test configs.

    Args:
        device_name: Hostname of the DUT to probe.
        churn_prefix_patterns: Same prefix patterns used in the
            baseline step.
        max_probes: Cap on the number of prefixes sampled. Default 50.
        min_changed_ratio: Minimum fraction of probes that must show a
            different best-path post-churn for the step to pass.
            Default 0.3 (30%).

    Returns:
        A `Step` with `step_name=StepName.RUN_TASK_STEP` invoking
        `verify_best_path_changes` in verify mode.
    """
    return create_run_task_step(
        task_name="verify_best_path_changes",
        params_dict={
            "hostname": device_name,
            "mode": "verify",
            "churn_patterns": churn_prefix_patterns,
            "max_probes": max_probes,
            "min_changed_ratio": min_changed_ratio,
        },
        description="Verify best paths changed after churn",
    )


def create_cte_ucmp_custom_step(
    action: str,
    target_community: str,
    dc_asns: t.List[int],
    peers_per_dc: int,
    weight_min: int = 1,
    weight_max: int = 5,
) -> Step:
    """Apply random per-peer UCMP weights for CTE UCMP stand-alone tests.

    Dispatches to the `UcmpRandomWeightCustomStep` custom step which
    walks each DC's peers and assigns each a random weight in
    `[weight_min, weight_max]`, scoped to routes carrying
    `target_community`. Used in CTE UCMP stand-alone tests (i.e.
    without the broader DC-bring-up scaffolding) to exercise weight
    propagation under non-uniform per-peer weights.

    Args:
        action: Operation tag forwarded to the custom step (e.g. `set`,
            `unset`, `randomize`).
        target_community: BGP community whose routes the weights apply to.
        dc_asns: List of DC ASNs to iterate over.
        peers_per_dc: Number of peers per DC the step expects.
        weight_min: Inclusive lower bound for random weight selection
            (default 1).
        weight_max: Inclusive upper bound for random weight selection
            (default 5).

    Returns:
        A `Step` with `step_name=StepName.CUSTOM_STEP` dispatching to
        `UcmpRandomWeightCustomStep`.
    """
    return create_custom_step(
        params_dict={
            "custom_step_name": "UcmpRandomWeightCustomStep",
            "step_params": {
                "action": action,
                "target_community": target_community,
                "dc_asns": dc_asns,
                "peers_per_dc": peers_per_dc,
                "weight_min": weight_min,
                "weight_max": weight_max,
            },
        },
        description=f"UCMP stand-alone: {action}",
    )


def create_cte_ucmp_dynamic_rib_validation_step(
    target_community: str,
    target_prefix: str,
) -> Step:
    """Validate UCMP RIB weights against expected values resolved at runtime.

    Builds a `VALIDATION_STEP` wrapping `create_dynamic_bgp_rib_weight_check`
    which, unlike `create_ucmp_validation_step`, pulls the expected
    weight map from jq variables populated earlier in the playbook
    (e.g. by `create_cte_ucmp_custom_step` randomizing weights).
    Used in CTE UCMP stand-alone tests where expected weights are not
    known statically. CTE UCMP-specific.

    Args:
        target_community: BGP community whose routes should match.
        target_prefix: Specific prefix to validate the RIB weights for.

    Returns:
        A `Step` with `step_name=StepName.VALIDATION_STEP` running the
        dynamic RIB-weight health check.
    """
    from taac.health_checks.healthcheck_definitions import (
        create_dynamic_bgp_rib_weight_check,
    )

    return create_validation_step(
        point_in_time_checks=[
            create_dynamic_bgp_rib_weight_check(
                target_community=target_community,
                target_prefix=target_prefix,
            ),
        ],
        description="Verify UCMP RIB weights match expected (dynamic)",
    )


# =============================================================================
# CUSTOM STEP IMPLEMENTATIONS (registered by name via internal/steps/custom_step.py
# dispatch). These have STEP_NAME=CUSTOM_STEP and are constructed by the
# custom_step plugin host, not by the TaacRunner Step registry directly.
# =============================================================================

_DSF_SLEEP_TIME_AFTER_PORT_UPDATE = 60
_DSF_PORT_BATCH_SIZE = 3
_DSF_PORT_BATCH_DELAY = 5  # seconds between batches to avoid FBOSS agent rate limiting


class VerifyDsfMinLinkCustomStep(StepBase[taac_types.CustomStepInput]):
    """Verify FSDB session state and DSF drain state based on number of enabled fabric links on a RDSW."""

    STEP_NAME = taac_types.StepName.CUSTOM_STEP

    def __init__(self, step_obj: StepBase) -> None:
        for k, v in step_obj.__dict__.items():
            setattr(self, k, v)
        self.name = "test_dsf_min_link"
        self.fdsw_drivers = {}

    async def _set_ports_state(self, driver, ports: list[str], enable: bool) -> None:
        """Enable/disable ports in batches to avoid FBOSS agent rate limiting."""
        for i in range(0, len(ports), _DSF_PORT_BATCH_SIZE):
            batch = ports[i : i + _DSF_PORT_BATCH_SIZE]
            await driver.async_enable_ports_via_ssh(batch, enable)
            if i + _DSF_PORT_BATCH_SIZE < len(ports):
                await asyncio.sleep(_DSF_PORT_BATCH_DELAY)

    async def run(
        self, input: taac_types.CustomStepInput, params: t.Dict[str, t.Any]
    ) -> None:
        pass

    async def verify_at_and_below_min_links_to_remain(self) -> None:  # noqa: C901
        """Verify correct DSF state for threshold minLinksToRemain on a RDSW."""
        failures = []
        min_links_to_remain, min_links_to_join = await self._get_min_link_count()

        if min_links_to_remain <= 1:
            self.logger.warning(
                f"minLinksToRemainInVOQDomain is set to {min_links_to_remain}. Cannot go to DSF drain state 'DRAINED' "
            )
            return

        enabled_fabric_links, all_ports = await self._find_enabled_fabric_links()

        if len(enabled_fabric_links) < min_links_to_remain:
            self.logger.warning(
                f"Not enough enabled fabric links ({len(enabled_fabric_links)}) to test. "
                f"Need at least {min_links_to_remain} to perform the test."
            )
            return

        self.logger.debug(
            f"""minLinksToRemainInVOQDomain: {min_links_to_remain},
            minLinksToJoinVOQDomain: {min_links_to_join},
            num_enabled_fabric_links: {len(enabled_fabric_links)},
            enabled_fabric_links: {enabled_fabric_links}"""
        )

        if min_links_to_remain % 2 == 0:
            disable_idx = min_links_to_remain
        else:
            disable_idx = min_links_to_remain + 1

        ports_to_disable = all_ports[disable_idx:]
        enabled_ports = all_ports[:disable_idx]

        await self._set_ports_state(self.driver, ports_to_disable, False)
        await asyncio.sleep(_DSF_SLEEP_TIME_AFTER_PORT_UPDATE)
        self.logger.debug(
            f"Threshhold to remain in connection is {min_links_to_remain} and {len(enabled_ports)} ports are enabled: {enabled_ports}"
        )

        matched, msg = await self._verify_dsf_state(
            SwitchDrainState.UNDRAINED, DsfSessionState.ESTABLISHED, min_links_to_remain
        )
        if not matched:
            failures.append(msg)

        num_ports_to_disable = 2 if min_links_to_remain % 2 != 0 else 1
        self.logger.debug(f"Disabling port(s): {enabled_ports[num_ports_to_disable:]}")

        await self._set_ports_state(
            self.driver, enabled_ports[num_ports_to_disable:], False
        )
        await asyncio.sleep(_DSF_SLEEP_TIME_AFTER_PORT_UPDATE)

        matched, msg = await self._verify_dsf_state(
            SwitchDrainState.DRAINED, DsfSessionState.CONNECT, min_links_to_remain - 1
        )
        if not matched:
            failures.append(msg)

        disabled_ports = enabled_ports[num_ports_to_disable:] + ports_to_disable
        enabled_ports = enabled_ports[:num_ports_to_disable]

        ports_to_enable = disabled_ports[:2]
        disabled_ports = disabled_ports[2:]
        fdsw_devices_ports_to_disable = [
            enabled_fabric_links[port] for port in ports_to_enable
        ]
        enabled_ports = enabled_ports + ports_to_enable

        await self._set_ports_state(self.driver, ports_to_enable, True)
        await self._update_fdsw_devices_ports(
            fdsw_devices_ports_to_disable, enable=False
        )
        await asyncio.sleep(_DSF_SLEEP_TIME_AFTER_PORT_UPDATE)

        matched, msg = await self._verify_dsf_state(
            SwitchDrainState.DRAINED, DsfSessionState.CONNECT, min_links_to_remain - 1
        )
        if not matched:
            failures.append(msg)

        await self._set_ports_state(self.driver, disabled_ports, True)
        await self._update_fdsw_devices_ports(
            fdsw_devices_ports_to_disable, enable=True
        )
        await asyncio.sleep(_DSF_SLEEP_TIME_AFTER_PORT_UPDATE)

        matched, msg = await self._verify_dsf_state(
            SwitchDrainState.UNDRAINED,
            DsfSessionState.ESTABLISHED,
            len(enabled_fabric_links),
        )
        if not matched:
            failures.append(msg)

        if failures:
            raise TestCaseFailure("\n".join(failures))

    async def verify_below_and_at_min_links_to_join(self) -> None:  # noqa: C901
        """Verify correct DSF state for threshold minLinksToJoin on a RDSW."""
        failures = []
        min_links_to_remain, min_links_to_join = await self._get_min_link_count()

        if min_links_to_remain == 1:
            self.logger.warning(
                "minLinksToRemainInVOQDomain is set to 1. Cannot go to DSF drain state 'DRAINED' "
            )
            return

        _, all_ports = await self._find_enabled_fabric_links()

        self.logger.debug(
            f"""minLinksToRemainInVOQDomain: {min_links_to_remain},
            minLinksToJoinVOQDomain: {min_links_to_join},
            num_enabled_fabric_links: {len(all_ports)},
            enabled_fabric_links: {all_ports}"""
        )

        if len(all_ports) < min_links_to_join:
            self.logger.warning(
                f"Not enough enabled fabric links ({len(all_ports)}) to test. "
                f"Need at least {min_links_to_join} to perform the test."
            )
            return

        ports_to_disable = all_ports[min_links_to_remain - 1 :]

        await self._set_ports_state(self.driver, ports_to_disable, False)
        await asyncio.sleep(_DSF_SLEEP_TIME_AFTER_PORT_UPDATE)
        self.logger.debug(f"Disabled ports: {ports_to_disable}")

        matched, msg = await self._verify_dsf_state(
            SwitchDrainState.DRAINED, DsfSessionState.CONNECT, min_links_to_remain - 1
        )
        if not matched:
            failures.append(msg)

        ports_to_enable = ports_to_disable[: min_links_to_join - min_links_to_remain]
        ports_disabled = ports_to_disable[min_links_to_join - min_links_to_remain :]

        await self._set_ports_state(self.driver, ports_to_enable, True)
        await asyncio.sleep(_DSF_SLEEP_TIME_AFTER_PORT_UPDATE)
        self.logger.debug(f"Enabled ports: {ports_to_enable}")

        matched, msg = await self._verify_dsf_state(
            SwitchDrainState.DRAINED, DsfSessionState.CONNECT, min_links_to_join - 1
        )
        if not matched:
            failures.append(msg)

        num_ports_to_enable = 2 if ((min_links_to_join % 2) != 0) else 1
        self.logger.debug(
            f"Enabling {num_ports_to_enable} more ports: {ports_disabled[:num_ports_to_enable]} so that we have {min_links_to_join} or more enabled links"
        )

        await self._set_ports_state(
            self.driver, ports_disabled[:num_ports_to_enable], True
        )
        ports_disabled = ports_disabled[num_ports_to_enable:]
        await asyncio.sleep(_DSF_SLEEP_TIME_AFTER_PORT_UPDATE)

        matched, msg = await self._verify_dsf_state(
            SwitchDrainState.UNDRAINED,
            DsfSessionState.ESTABLISHED,
            (
                (min_links_to_join + 1)
                if ((min_links_to_join % 2) != 0)
                else min_links_to_join
            ),
        )
        if not matched:
            failures.append(msg)

        await self._set_ports_state(self.driver, ports_disabled, True)
        await asyncio.sleep(_DSF_SLEEP_TIME_AFTER_PORT_UPDATE)

        if failures:
            raise TestCaseFailure("\n".join(failures))

    async def _get_min_link_count(self) -> t.Tuple[int, int]:
        # pyre-ignore[16]
        async with self.driver.async_agent_client as client:
            running_config = await client.getRunningConfig()
        config = json.loads(running_config)
        min_links_to_remain = config["sw"]["switchSettings"][
            "minLinksToRemainInVOQDomain"
        ]
        min_links_to_join = config["sw"]["switchSettings"]["minLinksToJoinVOQDomain"]
        assert min_links_to_remain <= min_links_to_join, (
            "minLinksToRemain must be <= minLinksToJoin"
        )
        return min_links_to_remain, min_links_to_join

    async def _find_enabled_fabric_links(  # noqa: C901
        self,
    ) -> t.Tuple[t.Dict[str, str], t.List[str]]:
        (
            rdsw_fabric_connectivity,
            fdsw_fabric_connectivity,
        ) = await self._get_cluster_fabric_connectivity()

        is_fdsw_drained = {}
        for fdsw_name in fdsw_fabric_connectivity:
            is_fdsw_drained[fdsw_name] = await self._check_if_device_drained(fdsw_name)

        enabled_fabric_links = {}
        switch_id_to_port_mapping = defaultdict(list)
        for rdsw_port, connection_info in rdsw_fabric_connectivity.items():
            if connection_info.isAttached:
                fdsw_name = connection_info.switchName
                fdsw_port_name = connection_info.portName

                if fdsw_name in fdsw_fabric_connectivity:
                    fdsw_connections = fdsw_fabric_connectivity[fdsw_name]
                    fdsw_connection_info = fdsw_connections[fdsw_port_name]

                    if (
                        not is_fdsw_drained[fdsw_name]
                        and fdsw_connection_info.isAttached
                        and fdsw_connection_info.switchName == self.hostname
                        and fdsw_connection_info.portName == rdsw_port
                    ):
                        enabled_fabric_links[rdsw_port] = (
                            f"{fdsw_name}:{fdsw_port_name}"
                        )
                        switch_id_to_port_mapping[connection_info.switchId].append(
                            rdsw_port
                        )

        list_of_ports = [
            item
            for key in sorted(switch_id_to_port_mapping)
            for item in switch_id_to_port_mapping[key]
        ]
        self.logger.info(f"Enabled fabric links: {enabled_fabric_links}")
        return enabled_fabric_links, list_of_ports

    async def _check_if_device_drained(self, fdsw_name: str) -> bool:
        driver = self.fdsw_drivers[fdsw_name]
        is_switch_drained = await driver.async_is_switch_drained()
        dsf_drain_state = await driver.async_get_actual_switch_drain_state()
        is_drained = is_switch_drained or any(
            drain_state != SwitchDrainState.UNDRAINED
            for drain_state in dsf_drain_state.values()
        )
        return is_drained

    async def _get_cluster_fabric_connectivity(
        self,
    ) -> t.Tuple[t.Dict, t.Dict]:
        # pyre-ignore[16]
        switch_id_mapping = await self.driver.async_get_dsf_cluster_switch_id_mapping()
        fdsw_names = [
            hostname
            for hostname in switch_id_mapping.values()
            if hostname.startswith("fdsw") and hostname in self.topology.device_names
        ]
        # pyre-ignore[16]
        rdsw_fabric_connectivity = await self.driver.async_get_fabric_connectivity()
        fdsw_fabric_connectivity = {}
        for fdsw_name in fdsw_names:
            driver = await async_get_device_driver(fdsw_name)
            self.fdsw_drivers[fdsw_name] = driver
            fdsw_fabric_connectivity[
                fdsw_name
                # pyrefly: ignore [missing-attribute]
            ] = await driver.async_get_fabric_connectivity()
        return rdsw_fabric_connectivity, fdsw_fabric_connectivity

    async def _update_fdsw_devices_ports(
        self, fdsw_devices_ports: list[str], enable: bool
    ):
        for fdsw_device_port in fdsw_devices_ports:
            fdsw_device_name, fdsw_port = fdsw_device_port.split(":")
            await self._set_ports_state(
                self.fdsw_drivers[fdsw_device_name], [fdsw_port], enable
            )

    async def _verify_dsf_state(
        self,
        expected_drain_state: SwitchDrainState,
        expected_session_state: DsfSessionState,
        num_enabled_links: int,
    ) -> t.Tuple[bool, str]:
        matched = True
        msg = ""

        # pyre-ignore[16]
        drain_states = await self.driver.async_get_actual_switch_drain_state()
        assert len(drain_states) == 1, (
            f"Expected exactly one drain state entry, got {len(drain_states)}"
        )
        self.logger.debug(f"Drain states: {drain_states}")

        drain_state = next(iter(drain_states.values()))
        if drain_state != expected_drain_state:
            matched = False
            msg = (
                f"With {num_enabled_links=}, expected switch to be in {expected_drain_state} state, "
                f"but got {drain_state}. "
            )

        # pyre-ignore[16]
        dsf_sessions = await self.driver.async_get_dsf_sessions()
        self.logger.debug(f"FSDB sessions: {dsf_sessions}")

        for session in dsf_sessions:
            if session.state != expected_session_state:
                matched = False
                remote_rdsw = session.remoteName.split("::")[0]
                msg += (
                    f"With {num_enabled_links=}, expected FSDB session to {remote_rdsw} to be in {expected_session_state} state, "
                    f"but got {session.state}. "
                )

        if matched:
            self.logger.debug(
                f"With {num_enabled_links=}, successfully verified that DSF drain state is in {expected_drain_state} and FSDB sessions are in {expected_session_state}"
            )

        return matched, msg


def create_fpf_bgp_prefix_injection_step(
    devices: t.List[str],
    prefix_base: str = "5000:dd::/64",
    count: int = 1,
    increment_step: str = "0:0:1::",
    community_list: t.Optional[str] = None,
    communities: t.Optional[t.List[str]] = None,
    withdraw_only: bool = False,
    description: t.Optional[str] = None,
) -> Step:
    """Inject or withdraw BGP prefixes on one or more FBOSS devices.

    See `steps/fpf_bgp_prefix_injection_step.py` for param semantics.
    """
    params: t.Dict[str, t.Any] = {
        "devices": devices,
        "prefix_base": prefix_base,
        "count": count,
        "increment_step": increment_step,
        "withdraw_only": withdraw_only,
    }
    if community_list is not None:
        params["community_list"] = community_list
    if communities is not None:
        params["communities"] = communities
    return Step(
        name=StepName.FPF_BGP_PREFIX_INJECTION_STEP,
        step_params=Params(json_params=json.dumps(params)),
        description=description
        or f"Inject {count} BGP prefixes on {', '.join(devices)}",
    )


def create_fpf_continuous_collector_step(
    gtsws: t.List[str],
    hosts: t.List[str],
    subnet_prefix: str = "5000:dd::/32",
    poll_interval_sec: int = 5,
    collection_duration_sec: int = 720,
    lanes: t.Optional[t.List[int]] = None,
    fsdb_expected: int = 20000,
    bgp_expected: int = 20000,
    hrt_thresholds: t.Optional[t.Dict[int, int]] = None,
    trigger_delay_sec: int = 120,
    description: t.Optional[str] = None,
) -> Step:
    """Run three continuous-polling collectors (FSDB ribMap, HRT bulk, BGP RIB).

    See `steps/fpf_continuous_collector_step.py` for param semantics.
    """
    resolved_lanes = lanes if lanes is not None else [0, 1]
    params: t.Dict[str, t.Any] = {
        "gtsws": gtsws,
        "hosts": hosts,
        "subnet_prefix": subnet_prefix,
        "poll_interval_sec": poll_interval_sec,
        "collection_duration_sec": collection_duration_sec,
        "lanes": resolved_lanes,
        "fsdb_expected": fsdb_expected,
        "bgp_expected": bgp_expected,
        "hrt_thresholds": hrt_thresholds
        or {lane: fsdb_expected for lane in resolved_lanes},
        "trigger_delay_sec": trigger_delay_sec,
    }
    return Step(
        name=StepName.FPF_CONTINUOUS_COLLECTOR_STEP,
        step_params=Params(json_params=json.dumps(params)),
        description=description
        or f"Continuous collector ({collection_duration_sec}s, {len(gtsws)} GTSWs, {len(hosts)} hosts)",
    )


def create_rss_start_step(
    device_name: str,
    session_key: str,
    interval_seconds: float = 3.0,
    process_name: str = "bgpcpp",
    baseline_settle_max_seconds: float = 90.0,
    description: t.Optional[str] = None,
) -> Step:
    """START of an embeddable bgpcpp RSS delta bracket.

    Drop this at a settled point before the phase you want to characterize and
    pair it with ``create_rss_stop_step`` (same ``session_key``) after it. START
    waits for RSS to plateau (so the baseline is a SETTLED footprint, not a
    mid-startup snapshot), samples the baseline, and begins a background VmRSS
    sampler that runs across the sequential steps in between (for the peak).
    Reusable in ANY playbook.

    Args:
        device_name: DUT under test.
        session_key: unique id tying this START to its matching STOP.
        interval_seconds: background sampling interval (default 3.0s).
        process_name: BGP++ process name (default "bgpcpp").
        baseline_settle_max_seconds: cap on the plateau wait before baselining
            (default 90.0); the wait ends early once RSS stops climbing.
        description: optional step description override.
    """
    params: t.Dict[str, t.Any] = {
        "custom_step_name": "bgp_rss_start",
        "hostname": device_name,
        "session_key": session_key,
        "interval_seconds": interval_seconds,
        "process_name": process_name,
        "baseline_settle_max_seconds": baseline_settle_max_seconds,
    }
    return Step(
        name=StepName.CUSTOM_STEP,
        step_params=Params(json_params=json.dumps(params)),
        description=(
            description or f"Start bgpcpp RSS delta sampling (session {session_key})"
        ),
    )


def create_rss_stop_step(
    session_key: str,
    summary_jq_var: t.Optional[str] = None,
    description: t.Optional[str] = None,
) -> Step:
    """STOP of an embeddable bgpcpp RSS delta bracket.

    Ends the sampler started by ``create_rss_start_step`` with the same
    ``session_key``, samples the settled current RSS, computes growth over the
    baseline and the peak VmRSS across the window, and stashes the summary into
    ``summary_jq_var`` for the RSS_DELTA_CHECK postcheck to report/gate.

    Args:
        session_key: id matching the START step that began the bracket.
        summary_jq_var: jq var to stash the {baseline, current, peak, growth}
            summary into.
        description: optional step description override.
    """
    params: t.Dict[str, t.Any] = {
        "custom_step_name": "bgp_rss_stop",
        "session_key": session_key,
        "summary_jq_var": summary_jq_var,
    }
    return Step(
        name=StepName.CUSTOM_STEP,
        step_params=Params(json_params=json.dumps(params)),
        description=(
            description
            or f"Stop bgpcpp RSS delta sampling and emit growth/peak "
            f"(session {session_key})"
        ),
    )


def create_cpu_percentile_start_step(
    device_name: str,
    session_key: str,
    interval_seconds: float = 2.0,
    process_name: str = "bgpcpp",
    description: t.Optional[str] = None,
) -> Step:
    """START of an embeddable bgpcpp CPU percentile bracket.

    Drop this before the phase you want to characterize and pair it with
    ``create_cpu_percentile_stop_step`` (same ``session_key``) after it. START
    begins a background ``/proc/<pid>/stat`` sampler that keeps running across
    the sequential steps in between, so the window is exactly START..STOP -- no
    ConcurrentStep needed. Reusable in ANY playbook (convergence, churn, mass
    advertisement, steady state).

    Args:
        device_name: DUT under test.
        session_key: unique id tying this START to its matching STOP.
        interval_seconds: sampling interval (default 2.0s).
        process_name: BGP++ process name (default "bgpcpp").
        description: optional step description override.
    """
    params: t.Dict[str, t.Any] = {
        "custom_step_name": "bgp_cpu_percentile_start",
        "hostname": device_name,
        "session_key": session_key,
        "interval_seconds": interval_seconds,
        "process_name": process_name,
    }
    return Step(
        name=StepName.CUSTOM_STEP,
        step_params=Params(json_params=json.dumps(params)),
        description=(
            description
            or f"Start bgpcpp CPU percentile sampling (session {session_key})"
        ),
    )


def create_cpu_percentile_stop_step(
    session_key: str,
    percentiles: t.Optional[t.Sequence[float]] = None,
    threshold_pct: float = 40.0,
    normalize_per_core: bool = True,
    gate: bool = False,
    gate_percentile: float = 95.0,
    gate_threshold_pct: t.Optional[float] = None,
    summary_jq_var: t.Optional[str] = None,
    description: t.Optional[str] = None,
) -> Step:
    """STOP of an embeddable bgpcpp CPU percentile bracket.

    Ends the sampler started by ``create_cpu_percentile_start_step`` with the
    same ``session_key`` and emits the percentile distribution (p70/p80/p95/p99,
    raw summed + per-core) over the START..STOP window. Log-only unless ``gate``
    is set.

    Args:
        session_key: id matching the START step that began the bracket.
        percentiles: percentiles to emit (default [70, 80, 95, 99]).
        threshold_pct: informational threshold shown in the log line.
        normalize_per_core: also emit a per-core (/nproc) view (default True).
        gate: fail the test if the gated percentile is exceeded (default False).
        gate_percentile: percentile to gate on when gating (default 95.0).
        gate_threshold_pct: gate threshold (defaults to ``threshold_pct``).
        description: optional step description override.
    """
    params: t.Dict[str, t.Any] = {
        "custom_step_name": "bgp_cpu_percentile_stop",
        "session_key": session_key,
        "percentiles": list(percentiles) if percentiles else [70.0, 80.0, 95.0, 99.0],
        "threshold_pct": threshold_pct,
        "normalize_per_core": normalize_per_core,
        "gate": gate,
        "gate_percentile": gate_percentile,
        "gate_threshold_pct": (
            gate_threshold_pct if gate_threshold_pct is not None else threshold_pct
        ),
        "summary_jq_var": summary_jq_var,
    }
    return Step(
        name=StepName.CUSTOM_STEP,
        step_params=Params(json_params=json.dumps(params)),
        description=(
            description
            or f"Stop bgpcpp CPU percentile sampling and emit percentiles "
            f"(session {session_key})"
        ),
    )
