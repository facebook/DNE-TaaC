# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""
Consolidated step definitions for TAAC test configurations.

This module provides reusable helper functions for creating Step objects
used in TAAC test playbooks.
"""

import json
import typing as t

from taac.constants import OpenRRouteAction
from taac.utils.json_thrift_utils import thrift_to_json
from taac.health_check.health_check import types as hc_types
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import (
    Params,
    PointInTimeHealthCheck,
    RunTaskInput,
    Step,
    StepName,
    Task,
    ValidationInput,
)


# =============================================================================
# HEALTH CHECK HELPER - Moved from health_check_definitions.py
# =============================================================================


def create_next_hop_count_check(
    discover_baseline: bool = False,
    baseline_nexthop_count: t.Optional[int] = None,
    use_discovered_prefixes: bool = False,
    prefix_subnets: t.Optional[t.List[str]] = None,
    expected_nexthop_count: t.Optional[int] = None,
    min_nexthop_count: t.Optional[int] = None,
    max_nexthop_count: t.Optional[int] = None,
    check_id: t.Optional[str] = None,
) -> PointInTimeHealthCheck:
    """
    Create a BGP multipath next-hop count health check.

    This check validates the number of next-hops (multipath routes) for BGP prefixes.
    It supports two modes:
    1. Discovery mode: Find prefixes with a specific baseline next-hop count
    2. Validation mode: Verify discovered prefixes have the expected next-hop count

    Args:
        discover_baseline: If True, discover prefixes with baseline_nexthop_count next-hops
        baseline_nexthop_count: Number of next-hops to look for during discovery
        use_discovered_prefixes: If True, validate against previously discovered prefixes
        prefix_subnets: Optional list of prefix subnets to check
        expected_nexthop_count: Expected exact number of next-hops
        min_nexthop_count: Minimum acceptable number of next-hops
        max_nexthop_count: Maximum acceptable number of next-hops
        check_id: Optional unique identifier for the check

    Returns:
        PointInTimeHealthCheck object for next-hop count check
    """
    check_params: t.Dict[str, t.Any] = {}

    if discover_baseline:
        check_params["discover_baseline"] = True
        if baseline_nexthop_count is not None:
            check_params["baseline_nexthop_count"] = baseline_nexthop_count

    if use_discovered_prefixes:
        check_params["use_discovered_prefixes"] = True

    if prefix_subnets is not None:
        check_params["prefix_subnets"] = prefix_subnets

    if expected_nexthop_count is not None:
        check_params["expected_nexthop_count"] = expected_nexthop_count

    if min_nexthop_count is not None:
        check_params["min_nexthop_count"] = min_nexthop_count

    if max_nexthop_count is not None:
        check_params["max_nexthop_count"] = max_nexthop_count

    return PointInTimeHealthCheck(
        name=hc_types.CheckName.NEXT_HOP_COUNT_CHECK,
        check_params=Params(
            json_params=json.dumps(check_params),
        )
        if check_params
        else None,
        check_id=check_id,
    )


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


def create_thread_cpu_monitoring_step(
    device_name: str,
    duration_minutes: int,
    thread_cpu_monitoring_interval_seconds: int = 5,
    thread_name_filter: t.Optional[t.List[str]] = None,
    enable_bgp_events: bool = True,
    enable_perf_profiling: bool = False,
    enable_offcpu_profiling: bool = False,
    enable_socket_monitoring: bool = False,
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
    return Step(
        name=StepName.CUSTOM_STEP,
        description="Monitor BGP++ thread CPU during convergence",
        step_params=Params(
            json_params=json.dumps(
                {
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
            )
        ),
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

    return Step(
        name=StepName.RUN_TASK_STEP,
        description=description,
        input_json=thrift_to_json(
            RunTaskInput(
                task=Task(
                    task_name=task_name,
                    ixia_needed=ixia_needed,
                    params=Params(json_params=json.dumps(params_dict)),
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
) -> Step:
    """
    Create a step to enable or disable IXIA device groups.

    Args:
        enable: True to enable device groups, False to disable
        device_group_name_regex: Regex pattern to match device group names
        description: Custom description for the step

    Returns:
        Step object for IXIA device group toggle
    """
    if description is None:
        action = "Enable" if enable else "Disable"
        description = (
            f"{action} IXIA device groups matching '{device_group_name_regex}'"
        )
    return create_ixia_api_step(
        api_name="toggle_device_groups",
        args_dict={
            "enable": enable,
            "device_group_name_regex": device_group_name_regex,
        },
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
    return Step(
        name=StepName.LONGEVITY_STEP,
        step_params=Params(json_params=json.dumps({"duration": duration})),
        description=description,
        id=step_id,
    )


def create_service_interruption_step(
    service: taac_types.Service,
    trigger: taac_types.ServiceInterruptionTrigger = taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
    create_cold_boot_file: bool = False,
    description: t.Optional[str] = None,
    step_id: t.Optional[str] = None,
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
    )


def create_service_convergence_step(
    services: t.Optional[t.List[taac_types.Service]] = None,
    description: t.Optional[str] = None,
    timeout: t.Optional[int] = None,
    service_convergence_timeout: t.Optional[t.Dict[taac_types.Service, int]] = None,
    step_id: t.Optional[str] = None,
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


def create_toggle_ixia_prefix_session_flap_step(
    bgp_peer_group_name_regex: str,
    prefix_flapping_duration_hours: float,
    stable_state_duration_hours: float,
    description: t.Optional[str] = None,
) -> Step:
    """
    Create a step to toggle IXIA BGP prefix/session flapping.

    Args:
        bgp_peer_group_name_regex: Regex to match BGP peer group names
        prefix_flapping_duration_hours: Duration of flapping in hours
        stable_state_duration_hours: Duration of stable state in hours
        description: Custom description for the step

    Returns:
        Step object for prefix/session flapping
    """
    return Step(
        name=StepName.TOGGLE_IXIA_PREFIX_SESSION_FLAP,
        step_params=Params(
            json_params=json.dumps(
                {
                    "bgp_peer_group_name_regex": bgp_peer_group_name_regex,
                    "prefix_flapping_duration_hours": prefix_flapping_duration_hours,
                    "stable_state_duration_hours": stable_state_duration_hours,
                }
            )
        ),
        description=description,
    )


def create_mass_bgp_peer_toggle_step(
    device_group_name_regex: str,
    peer_toggle_duration_hours: float,
    total_step_time_hours: float,
    description: t.Optional[str] = None,
) -> Step:
    """
    Create a step for mass BGP peer toggling.

    Args:
        device_group_name_regex: Regex to match device group names
        peer_toggle_duration_hours: Duration of peer toggle in hours
        total_step_time_hours: Total step time in hours
        description: Custom description for the step

    Returns:
        Step object for mass BGP peer toggle
    """
    return Step(
        name=StepName.MASS_BGP_PEER_TOGGLE,
        step_params=Params(
            json_params=json.dumps(
                {
                    "device_group_name_regex": device_group_name_regex,
                    "peer_toggle_duration_hours": peer_toggle_duration_hours,
                    "total_step_time_hours": total_step_time_hours,
                }
            )
        ),
        description=description,
    )


def create_allocate_cgroup_memory_step(
    total_memory_pct_decimal: float,
    cgroup_slice_name: str,
    cgroup_unit_name: str,
    oom_score_adj: int = 1000,
    description: t.Optional[str] = None,
) -> Step:
    """
    Create a step to allocate cgroup slice memory.

    Args:
        total_memory_pct_decimal: Memory percentage as decimal (e.g., 0.25 for 25%)
        cgroup_slice_name: Name of the cgroup slice
        cgroup_unit_name: Name of the cgroup unit
        oom_score_adj: OOM score adjustment value
        description: Custom description for the step

    Returns:
        Step object for cgroup memory allocation
    """
    return Step(
        name=StepName.ALLOCATE_CGROUP_SLICE_MEMORY_STEP,
        step_params=Params(
            json_params=json.dumps(
                {
                    "total_memory_pct_decimal": total_memory_pct_decimal,
                    "cgroup_slice_name": cgroup_slice_name,
                    "cgroup_unit_name": cgroup_unit_name,
                    "oom_score_adj": oom_score_adj,
                }
            )
        ),
        description=description,
    )


def create_ecmp_member_static_route_step(
    max_ecmp_group: t.Optional[int] = None,
    delete_patcher_and_exit_step: bool = False,
    description: t.Optional[str] = None,
) -> Step:
    """
    Create a step for ECMP member static route configuration.

    Args:
        max_ecmp_group: Maximum ECMP group size
        delete_patcher_and_exit_step: Whether to delete patcher and exit
        description: Custom description for the step

    Returns:
        Step object for ECMP member static route
    """
    params_dict: t.Dict[str, t.Any] = {
        "delete_patcher_and_exit_step": delete_patcher_and_exit_step
    }
    if max_ecmp_group is not None:
        params_dict["max_ecmp_group"] = max_ecmp_group

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
    description: t.Optional[str] = None,
) -> Step:
    """
    Create a step to drain or undrain a device.

    Args:
        drain: True to drain, False to undrain
        drain_handler: Optional drain handler (e.g., LOCAL_DRAINER)
        description: Custom description for the step

    Returns:
        Step object for drain/undrain operation
    """
    input_kwargs: t.Dict[str, t.Any] = {"drain": drain}
    if drain_handler is not None:
        input_kwargs["drain_handler"] = drain_handler

    return Step(
        name=StepName.DRAIN_UNDRAIN_STEP,
        description=description,
        input_json=thrift_to_json(taac_types.DrainUndrainInput(**input_kwargs)),
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
    origin_value: str,
    prefix_end_index: t.Optional[int] = None,
    description: t.Optional[str] = None,
) -> Step:
    """
    Create a step to modify BGP prefix origin value.

    Args:
        prefix_pool_regex: Regex pattern to match prefix pool names
        prefix_start_index: Starting index for prefix modification
        origin_value: Origin value to set (e.g., "igp", "egp", "incomplete")
        prefix_end_index: Ending index for prefix modification (optional)
        description: Custom description for the step

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
        "origin_value": origin_value,
    }

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


def create_configure_as_path_pool_step(
    device_name: str,
    interface: str,
    as_path_pool: list[str],
    device_group_regex: str = ".*",
    description: str | None = None,
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
        },
        description=description or "Configure AS path pool on IXIA",
    )


def create_configure_community_pool_step(
    device_name: str,
    interface: str,
    community_combinations: list[list[str]],
    device_group_regex: str = ".*",
    description: str | None = None,
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
        },
        description=description or "Configure community pool on IXIA",
    )


def create_configure_extended_community_pool_step(
    device_name: str,
    interface: str,
    extended_community_combinations: list[list[str]],
    device_group_regex: str = ".*",
    description: str | None = None,
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
    """Create a step to configure BGP session flapping (enable or disable)."""
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
    """Create a step to start or stop specific BGP peer sessions by index range."""
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
) -> Step:
    """
    Create a step to advertise or withdraw BGP prefixes from matching prefix pools.

    Args:
        advertise: True to advertise prefixes, False to withdraw them
        prefix_pool_regex: Regex pattern to match prefix pool names
        prefix_start_index: Starting index (inclusive) in the prefix range
        prefix_end_index: Ending index in the prefix range. If None, uses the network group multiplier value (all remaining prefixes).
        description: Custom description for the step

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

    return create_run_task_step(
        task_name="ixia_enable_disable_bgp_prefixes",
        params_dict=params_dicts,
        description=description,
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


def create_openr_route_action_task(
    device_name: str,
    start_ipv4s: t.List[str],
    start_ipv6s: t.List[str],
    local_link: t.Dict[str, t.Any],
    other_link: t.Dict[str, t.Any],
    action: str = OpenRRouteAction.INJECT.value,
    count: int = 63,
    step: int = 2,
    mask: int = -1,
    duration: t.Optional[int] = None,
    frequency: t.Optional[int] = None,
    description: t.Optional[str] = None,
) -> Task:
    """
    Create a configurable Open/R route action task (inject, delete, metric_oscillation) for use in setup_tasks.

    This uses the shared OpenRRouteManager utility to avoid code duplication with InjectRoutesStep.

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
        description: Custom description for the task

    Returns:
        Task object for the specified Open/R route action (for use in setup_tasks)
    """
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

    return Task(
        task_name="openr_route_action",
        params=Params(json_params=json.dumps(params)),
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
    use_discovered_prefixes: bool = False,
    description: t.Optional[str] = None,
) -> Step:
    """
    Create a health check step to verify BGP multipath group (next-hop count) for prefixes.

    This step runs the BgpMultipathNextHopCountHealthCheck to validate that prefixes
    have the expected number of next-hops in their multipath group. This is essential
    for verifying that BGP session oscillations correctly affect the multipath group size.

    Supports two modes:
        1. Discovery mode (discover_baseline=True): Queries the BGP RIB and discovers
           all prefixes that have the expected baseline next-hop count. The discovered
           prefixes are stored for use in subsequent validation.
        2. Validation mode (default): Validates that prefixes have the expected
           number of next-hops. Can use discovered prefixes (use_discovered_prefixes=True)
           or filter by prefix_subnets.

    Args:
        prefix_subnets: Optional list of prefix subnets to check (e.g., ["10.0.0.0/8", "2001:db8::/32"])
        expected_nexthop_count: Optional exact number of next-hops expected
        min_nexthop_count: Optional minimum number of next-hops expected
        max_nexthop_count: Optional maximum number of next-hops expected
        discover_baseline: If True, run in discovery mode to find prefixes with baseline next-hop count
        baseline_nexthop_count: Required when discover_baseline=True - the expected baseline next-hop count
        use_discovered_prefixes: If True, validate against previously discovered baseline prefixes
        description: Custom description for the step

    Returns:
        Step object for running the BGP multipath next-hop count health check

    Example:
        # Step 1: Before oscillations, discover prefixes with 12 next-hops (full multipath group)
        discovery_step = create_multipath_nexthop_count_health_check_step(
            discover_baseline=True,
            baseline_nexthop_count=12,
            description="Discover prefixes with full 12-way multipath group",
        )

        # Step 2: After stopping 3 sessions, verify discovered prefixes have 9 next-hops
        validation_step = create_multipath_nexthop_count_health_check_step(
            use_discovered_prefixes=True,
            expected_nexthop_count=9,
            description="Verify multipath group reduced to 9 next-hops",
        )
    """
    if description is None:
        if discover_baseline:
            description = (
                f"Discover prefixes with {baseline_nexthop_count} next-hops (baseline)"
            )
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
                        use_discovered_prefixes=use_discovered_prefixes,
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

    return Step(
        name=StepName.CUSTOM_STEP,
        description=description,
        step_params=Params(
            json_params=json.dumps(
                {
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
            )
        ),
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
) -> t.List[Step]:
    """
    Create standard setup steps for BGP tests.

    Args:
        device_name: Name of the device
        disable_all_device_groups: Whether to disable all Ixia device groups
        enable_all_device_groups: Whether to enable all Ixia device groups (takes precedence over disable)
        enable_bgp_daemon: Whether to enable BGP daemon
        daemon_name: Name of the daemon to enable

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
            )
        )
    elif disable_all_device_groups:
        steps.append(
            create_ixia_device_group_toggle_step(
                enable=False,
                device_group_name_regex=".*",
                description="Disable all device groups",
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


def create_bgp_restart_setup_steps(device_name: str) -> t.List[Step]:
    """
    Create setup steps specifically for BGP restart tests.

    Args:
        device_name: Name of the device

    Returns:
        List of setup steps for BGP restart tests
    """
    return create_standard_setup_steps(
        device_name=device_name,
        disable_all_device_groups=True,
        enable_bgp_daemon=True,
    )


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
    device_name: str, convergence_wait_seconds: int = 300
) -> t.List[Step]:
    """
    Create setup steps for BGP route registry prefix list runtime update testing.

    These setup steps establish the baseline state before runtime policy updates:
    First we create standard setup steps (enable all device groups, then start start bgp)
    1. Wait for convergence.
    2. Withdraw the 100 test prefixes (0-100) that will be used for verification
    3. Load the baseline route filter policy without these prefixes

    Args:
        device_name: Name of the device
        convergence_wait_seconds: Time to wait for BGP convergence (default: 5 minutes)

    Returns:
        List of setup steps for route registry prefix list runtime update tests
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

    steps.append(
        create_advertise_withdraw_prefixes_step(
            device_name=device_name,
            advertise=False,
            prefix_pool_regex=".*EBGP.*",
            prefix_start_index=0,
            prefix_end_index=100,
            description="Withdraw 100 prefixes (0-100) that will be tested for runtime updates",
        )
    )

    steps.append(
        create_set_route_filter_step(
            device_name=device_name,
            config_path="taac/test_bgp_policies/ebb_route_registry_prefix_list_650.json",
            description="Load baseline route filter policy without test prefixes (RP state file 650.json)",
        )
    )

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
        description=description or f"Unregister patcher '{patcher_name}'",
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
                    py_func_name="shutdown_loopback",
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
        kwargs={"graceful_restart_time_s": graceful_restart_time_s}
        if graceful_restart_time_s
        else {},
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


def create_update_openr_linkflap_backoff_step(
    register_patcher: bool = True,
    linkflap_initial_backoff_ms: t.Optional[str] = None,
    linkflap_max_backoff_ms: t.Optional[str] = None,
    patcher_name: str = "update_openr_linkflap_backoff_config",
    description: t.Optional[str] = "Update OpenR linkflap backoff timers",
) -> Step:
    """
    Create a step to update OpenR linkflap backoff timers via the COOP
    update_openr_linkflap_backoff patcher.

    Only updates fields that are explicitly provided; others are left unchanged.

    Args:
        register_patcher: True to update backoff timers, False to restore
        linkflap_initial_backoff_ms: Initial backoff time in milliseconds
        linkflap_max_backoff_ms: Maximum backoff time in milliseconds
        patcher_name: Name to register/unregister the patcher as
        description: Custom description for the step
    """
    kwargs = {}
    if linkflap_initial_backoff_ms is not None:
        kwargs["linkflap_initial_backoff_ms"] = linkflap_initial_backoff_ms
    if linkflap_max_backoff_ms is not None:
        kwargs["linkflap_max_backoff_ms"] = linkflap_max_backoff_ms

    if register_patcher and not kwargs:
        raise ValueError(
            "At least one of 'linkflap_initial_backoff_ms' or 'linkflap_max_backoff_ms' "
            "must be provided for update_openr_linkflap_backoff patcher."
        )

    return _create_openr_patcher_step(
        py_func_name="update_openr_linkflap_backoff",
        kwargs=kwargs,
        register_patcher=register_patcher,
        patcher_name=patcher_name,
        description=description,
    )
