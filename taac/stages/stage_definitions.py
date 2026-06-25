# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe

"""Centralized factories for `taac_types.Stage` constructions.

A `Stage` groups one or more `Step`s into a sequenced unit (with optional
`iteration` count) that runs inside a `Playbook`. This file is the single
canonical home for all module-level `Stage(...)` constructions across TAAC,
established in Phase 5 of the restructuring effort. The `tests/test_no_inline_stage_construction`
gate enforces the rule by walking `sys.modules` and flagging any `Stage(...)`
construction outside this file.

Conventions:
- Factory naming: `create_<descriptor>_stage(...)` returning `Stage`.
- For generic step-list stages, prefer `create_steps_stage(stage_id, steps, iteration=...)`.
- Domain-specific stages (warmboot iteration, NDP toggle, route churn shape, etc.)
  get their own named factory so call sites stay declarative.
- Factories should accept the smallest set of parameters they need; default
  values that match the most common test pattern are encouraged so call sites
  read cleanly.
- Pure data composition only — no I/O, no async. Stages compose Steps;
  Steps live in `steps/step_definitions.py`.

When migrating an inline `Stage(...)` site:
1. Grep for an existing factory that matches the shape (`grep ^def create_.*_stage stage_definitions.py`).
2. Reuse if a match exists; widen the existing factory with optional kwargs only if needed.
3. Otherwise add a new `create_<descriptor>_stage` factory here.
4. Replace the inline construction at the call site with the factory call.
5. Verify the 8-test gate suite passes (regen golden manifest only if structural counts match but content order changes).
"""

import json
import random
import re
from dataclasses import dataclass
from typing import Any

from taac.constants import (
    DEFAULT_LOCAL_LINK,
    DEFAULT_OTHER_LINK,
    OpenRRouteAction,
)
from taac.health_checks.healthcheck_definitions import (
    create_bgp_session_establish_check,
    create_ixia_packet_loss_check,
)
from taac.steps.step_definitions import (
    create_advertise_withdraw_prefixes_step,
    create_bgp_prefixes_med_value_step,
    create_change_as_path_length_step,
    create_clear_traffic_stats_step,
    create_configure_as_path_pool_step,
    create_configure_bgp_flap_step,
    create_configure_community_pool_step,
    create_configure_extended_community_pool_step,
    create_configure_prefix_length_step,
    create_configure_random_mask_step,
    create_consolidated_convergence_report_step,
    create_daemon_control_step,
    create_drain_convergence_verification_step,
    create_interface_flap_step,
    create_interface_permanent_flap_step,
    create_ixia_device_group_toggle_step,
    create_ixia_packet_capture_step,
    create_longevity_step,
    create_modify_bgp_prefixes_origin_value_step,
    create_multipath_nexthop_count_health_check_step,
    create_openr_route_action_step,
    create_randomize_prefix_local_preference_step,
    create_register_port_channel_min_link_percentage_patcher_step,
    create_register_speed_flip_patcher_step_v2,
    create_revert_route_storm_attributes_step,
    create_route_convergence_health_check_step,
    create_service_convergence_step,
    create_service_interruption_step,
    create_set_bgp_prefixes_local_preference_step,
    create_set_peer_groups_policy_step,
    create_set_route_filter_step,
    create_start_stop_bgp_peers_step,
    create_start_traffic_step,
    create_stop_traffic_step,
    create_system_reboot_step,
    create_tcpdump_step,
    create_thread_cpu_monitoring_step,
    create_toggle_device_group_step,
    create_update_prefix_count_step,
    create_validation_step,
    create_verify_port_operational_state_step,
    create_verify_port_speed_step_v2,
    create_verify_received_routes_step,
)
from taac.health_check.health_check import types as hc_types
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import (
    ConcurrentStep,
    Params,
    PointInTimeHealthCheck,
    Service,
    ServiceInterruptionTrigger,
    Stage,
    Step,
    StepName,
)


def create_bgp_restart_test_stage(
    device_name: str,
    daemon_name: str = "Bgp",
    sleep_after_disable_seconds: int = 5,
    convergence_wait_seconds: int = 540,
    device_group_regex: str = ".*",
    enable_thread_cpu_monitoring: bool = False,
    thread_cpu_monitoring_interval_seconds: int = 5,
    thread_name_filter: list[str] | None = None,
    enable_bgp_events: bool = True,
    enable_perf_profiling: bool = False,
    enable_offcpu_profiling: bool = False,
    enable_socket_monitoring: bool = False,
) -> Stage:
    """
    Create a standard BGP restart test stage.

    This stage performs the following sequence:
    1. Disable BGP daemon
    2. Sleep for specified duration
    3. Toggle all device groups back to active
    4. Enable BGP daemon
    5. Monitor thread CPU during convergence (optional, starts immediately after BGP enable)

    Args:
        device_name: Name of the device
        daemon_name: Name of the daemon to restart (default: "Bgp")
        sleep_after_disable_seconds: Sleep duration after disabling daemon
        convergence_wait_seconds: Wait time for BGP convergence (default: 480s)
        device_group_regex: Regex pattern for device groups to enable
        enable_thread_cpu_monitoring: Enable BGP++ thread CPU monitoring (default: False)
        thread_cpu_monitoring_interval_seconds: CPU sampling interval (default: 5s)
        thread_name_filter: List of thread names to monitor
                           - None (default): Plot top 10 threads by CPU
                           - ["bgpcpp-fiber_bg", "bgpcpp-peer_man", "bgpcpp-rib"]: Core BGP++ threads
                           - ["bgpcpp-fiber_bg"]: Only specific thread(s)
        enable_bgp_events: Enable BGP initialization event tracking (default: True)
                          Events are annotated on the CPU plot timeline
        enable_perf_profiling: Enable perf-based profiling (default: False)
                              Requires flamegraph tools on device
                              Generates flame graphs and top functions reports
                              Includes phased analysis sliced by BGP events
        enable_offcpu_profiling: Enable off-CPU profiling (default: False)
                                Requires enable_perf_profiling=True
                                Captures blocking/waiting time in addition to on-CPU time
                                Generates latency reports and time histograms
                                Thread-level profiling has 5-10% overhead

    Returns:
        Stage object for BGP restart test

    Note:
        When thread CPU monitoring is enabled, it runs for the entire convergence period.
        The monitoring starts immediately after BGP daemon is enabled to capture startup behavior.

        When perf profiling is enabled (enable_perf_profiling=True):
        - Profiling runs concurrently with CPU monitoring
        - Generates overall flame graph and top functions report
        - If enable_bgp_events=True, also generates phased analysis:
          * Separate flame graphs for each BGP convergence phase
          * Phase-specific top functions reports
          * Starts from PEER_INFO_LOADED onwards (skips early init phases)
    """
    return Stage(
        steps=[
            # Step 1: Disable BGP daemon
            create_daemon_control_step(
                device_name=device_name,
                daemon_name=daemon_name,
                action="disable",
                description=f"Disable {daemon_name} daemon",
            ),
            # Step 2: Sleep after disable
            create_longevity_step(
                duration=sleep_after_disable_seconds,
                description=f"Sleep for {sleep_after_disable_seconds} seconds",
            ),
            # Step 3: Toggle all device groups back to active
            create_ixia_device_group_toggle_step(
                enable=True,
                device_group_name_regex=device_group_regex,
                description="Toggle all device groups back to active",
            ),
            # Step 4: Enable BGP daemon
            create_daemon_control_step(
                device_name=device_name,
                daemon_name=daemon_name,
                action="enable",
                description=f"Enable {daemon_name} daemon",
            ),
            # Step 5: Record the daemon restart time for post-test restart detection.
            # This timestamp is used by SERVICE_RESTART_CHECK with
            # expected_restarted_services to detect silent crashes after the
            # intentional restart (uptime should match time since this point).
            Step(
                name=StepName.CUSTOM_STEP,
                description="Record daemon restart completion time",
                step_params=Params(
                    json_params=json.dumps(
                        {
                            "custom_step_name": "record_jq_timestamp",
                            "var_name": "daemon_restart_time",
                        }
                    )
                ),
            ),
            # Step 6: Monitor thread CPU during convergence (optional)
            # If enabled, this runs for the full convergence period and captures
            # CPU utilization from the moment BGP starts up through convergence
            *(
                [
                    create_thread_cpu_monitoring_step(
                        device_name=device_name,
                        duration_minutes=convergence_wait_seconds // (60 * 4),
                        thread_cpu_monitoring_interval_seconds=thread_cpu_monitoring_interval_seconds,
                        thread_name_filter=thread_name_filter,
                        enable_bgp_events=enable_bgp_events,
                        enable_perf_profiling=enable_perf_profiling,
                        enable_offcpu_profiling=enable_offcpu_profiling,
                        enable_socket_monitoring=enable_socket_monitoring,
                    )
                ]
                if enable_thread_cpu_monitoring
                else [
                    # If monitoring is disabled, just wait for convergence
                    create_longevity_step(
                        duration=convergence_wait_seconds,
                        description=f"Wait for BGP convergence ({convergence_wait_seconds} seconds)",
                    )
                ]
            ),
        ],
    )


def create_cold_start_test_stage(
    device_name: str,
    daemon_name: str = "Bgp",
    sleep_after_disable_seconds: int = 30,
    convergence_wait_seconds: int = 500,
    device_group_regex: str = ".*",
    enable_thread_cpu_monitoring: bool = False,
    thread_cpu_monitoring_interval_seconds: int = 5,
    thread_name_filter: list[str] | None = None,
    enable_bgp_events: bool = True,
    enable_perf_profiling: bool = False,
    enable_offcpu_profiling: bool = False,
    enable_socket_monitoring: bool = False,
) -> Stage:
    """
    Create a BGP cold start test stage.

    This stage simulates a cold start scenario where BGP daemon initializes
    first without any peer sessions, then all device groups are enabled
    simultaneously to test session establishment from scratch.

    The sequence performed:
    1. Disable BGP daemon
    2. Sleep for specified duration
    3. Enable BGP daemon (initializes without sessions)
    4. Wait for BGP initial convergence to complete (no sessions active)
    5. Toggle all device groups to active (cold start - all sessions establish simultaneously)
    6. Monitor thread CPU during convergence (optional)

    Args:
        device_name: Name of the device
        daemon_name: Name of the daemon to cold start (default: "Bgp")
        sleep_after_disable_seconds: Sleep duration after disabling daemon
        convergence_wait_seconds: Wait time for BGP initialization without sessions
        device_group_regex: Regex pattern for device groups to enable for cold start
        enable_thread_cpu_monitoring: Enable BGP++ thread CPU monitoring (default: False)
        thread_cpu_monitoring_interval_seconds: CPU sampling interval (default: 5s)
        thread_name_filter: List of thread names to monitor
                           - None (default): Plot top 10 threads by CPU
                           - ["bgpcpp-fiber_bg", "bgpcpp-peer_man", "bgpcpp-rib"]: Core BGP++ threads
                           - ["bgpcpp-fiber_bg"]: Only specific thread(s)
        enable_bgp_events: Enable BGP initialization event tracking (default: True)
                          Events are annotated on the CPU plot timeline
        enable_perf_profiling: Enable perf-based profiling (default: False)
                              Requires flamegraph tools on device
                              Generates flame graphs and top functions reports
                              Includes phased analysis sliced by BGP events
        enable_offcpu_profiling: Enable off-CPU profiling (default: False)
                                Requires enable_perf_profiling=True
                                Captures blocking/waiting time in addition to on-CPU time
                                Generates latency reports and time histograms
                                Thread-level profiling has 5-10% overhead
        enable_socket_monitoring: Enable socket monitoring (default: False)

    Returns:
        Stage object for BGP cold start test

    Note:
        When thread CPU monitoring is enabled, it runs for the entire convergence period
        after device groups are enabled. The monitoring captures the cold start session
        establishment behavior.

        When perf profiling is enabled (enable_perf_profiling=True):
        - Profiling runs concurrently with CPU monitoring
        - Generates overall flame graph and top functions report
        - If enable_bgp_events=True, also generates phased analysis:
          * Separate flame graphs for each BGP convergence phase
          * Phase-specific top functions reports
          * Starts from PEER_INFO_LOADED onwards (skips early init phases)
    """
    return Stage(
        steps=[
            # Step 1: Disable BGP daemon
            create_daemon_control_step(
                device_name=device_name,
                daemon_name=daemon_name,
                action="disable",
                description=f"Disable {daemon_name} daemon",
            ),
            # Step 2: Sleep after disable
            create_longevity_step(
                duration=sleep_after_disable_seconds,
                description=f"Sleep for {sleep_after_disable_seconds} seconds",
            ),
            # Step 3: Enable BGP daemon
            create_daemon_control_step(
                device_name=device_name,
                daemon_name=daemon_name,
                action="enable",
                description=f"Enable {daemon_name} daemon",
            ),
            # Step 4: Record the daemon restart time for post-test restart detection.
            Step(
                name=StepName.CUSTOM_STEP,
                description="Record daemon restart completion time",
                step_params=Params(
                    json_params=json.dumps(
                        {
                            "custom_step_name": "record_jq_timestamp",
                            "var_name": "daemon_restart_time",
                        }
                    )
                ),
            ),
            # Step 5: Wait for EOR timer to expire
            create_longevity_step(
                duration=180,
                description=f"Wait for BGP convergence ({180} seconds)",
            ),
            # Step 5: Toggle device groups (cold start trigger)
            create_ixia_device_group_toggle_step(
                enable=True,
                device_group_name_regex=device_group_regex,
                description="Toggle all device groups back to active",
            ),
            # Step 6: Monitor thread CPU OR wait for convergence
            # If monitoring is enabled, it runs for the convergence duration
            # and captures CPU activity after the cold start trigger
            *(
                [
                    create_thread_cpu_monitoring_step(
                        device_name=device_name,
                        duration_minutes=convergence_wait_seconds // (60 * 4),
                        thread_cpu_monitoring_interval_seconds=thread_cpu_monitoring_interval_seconds,
                        thread_name_filter=thread_name_filter,
                        enable_bgp_events=enable_bgp_events,
                        enable_perf_profiling=enable_perf_profiling,
                        enable_offcpu_profiling=enable_offcpu_profiling,
                        enable_socket_monitoring=enable_socket_monitoring,
                    )
                ]
                if enable_thread_cpu_monitoring
                else [
                    create_longevity_step(
                        duration=convergence_wait_seconds,
                        description=f"Wait for BGP convergence ({convergence_wait_seconds} seconds)",
                    ),
                ]
            ),
        ],
    )


def create_bgp_session_oscillation_stage(
    ipv4_peer_regex: str,
    ipv6_peer_regex: str,
    test_duration_seconds: int = 3600,
    uptime_seconds: int = 30,
    downtime_seconds: int = 30,
    sessions_per_cycle: int | None = None,
    ipv4_session_count: int | None = None,
    ipv6_session_count: int | None = None,
) -> Stage:
    """
    Create BGP session oscillation stage with two modes:

    Mode 1 - Continuous flapping: IPv4/IPv6 sessions flap continuously
    Usage: create_bgp_session_oscillation_stage(
           ipv4_peer_regex=".*IPV4_EBGP.*",
           ipv6_peer_regex=".*IPV6_EBGP.*"
       )

    Mode 2 - Cycle-based disruption: Different subsets of IPv4/IPv6 sessions disrupted each cycle
    Usage: create_bgp_session_oscillation_stage(
        sessions_per_cycle=64,
        ipv4_peer_regex=".*IPV4_EBGP.*",
        ipv6_peer_regex=".*IPV6_EBGP.*",
        ipv4_session_count=100,
        ipv6_session_count=100,
    )

    Args:
        test_duration_seconds: Total test duration (default: 1 hour)
        uptime_seconds: Session up time per cycle (default: 30s)
        downtime_seconds: Session down time per cycle (default: 30s)
        ipv4_peer_regex: Regex to match IPv4 BGP peers (required for both modes)
        ipv6_peer_regex: Regex to match IPv6 BGP peers (required for both modes)
        sessions_per_cycle: Number of sessions to disrupt per cycle (cycle-based mode)
        ipv4_session_count: Total IPv4 sessions available (cycle-based mode)
        ipv6_session_count: Total IPv6 sessions available (cycle-based mode)

    Returns:
        Stage with BGP oscillation steps
    """
    if not ipv4_peer_regex or not ipv6_peer_regex:
        raise ValueError("Both ipv4_peer_regex and ipv6_peer_regex are required")

    if sessions_per_cycle is not None:
        # Cycle-based disruption mode - requires session counts
        if not ipv4_session_count or not ipv6_session_count:
            raise ValueError(
                "Cycle-based disruption requires both ipv4_session_count and ipv6_session_count"
            )

        return create_cycle_based_session_disruption_stage(
            ipv4_peer_regex=ipv4_peer_regex,
            ipv6_peer_regex=ipv6_peer_regex,
            test_duration_seconds=test_duration_seconds,
            uptime_seconds=uptime_seconds,
            downtime_seconds=downtime_seconds,
            sessions_per_cycle=sessions_per_cycle,
            ipv4_session_count=ipv4_session_count,
            ipv6_session_count=ipv6_session_count,
        )
    else:
        # Continuous flapping mode - IPv4/IPv6 dual regex
        return Stage(
            steps=[
                # Step 1: Enable IPv4 session flapping
                create_configure_bgp_flap_step(
                    peer_regex=ipv4_peer_regex,
                    enable=True,
                    uptime_seconds=uptime_seconds,
                    downtime_seconds=downtime_seconds,
                    description=f"Enable IPv4 BGP flapping: {uptime_seconds}s up, {downtime_seconds}s down",
                ),
                # Step 2: Enable IPv6 session flapping
                create_configure_bgp_flap_step(
                    peer_regex=ipv6_peer_regex,
                    enable=True,
                    uptime_seconds=uptime_seconds,
                    downtime_seconds=downtime_seconds,
                    description=f"Enable IPv6 BGP flapping: {uptime_seconds}s up, {downtime_seconds}s down",
                ),
                # Step 3: Let both IPv4 and IPv6 sessions flap for the duration
                create_longevity_step(
                    duration=test_duration_seconds,
                    description=f"Run IPv4 and IPv6 BGP oscillations for {test_duration_seconds} test_duration_seconds",
                ),
                # Step 4: Disable IPv4 session flapping
                create_configure_bgp_flap_step(
                    peer_regex=ipv4_peer_regex,
                    enable=False,
                    description="Disable IPv4 BGP flapping",
                ),
                # Step 5: Disable IPv6 session flapping
                create_configure_bgp_flap_step(
                    peer_regex=ipv6_peer_regex,
                    enable=False,
                    description="Disable IPv6 BGP flapping",
                ),
            ],
        )


# Helper functions for session disruption logic


def _calculate_session_indices(
    cycle: int,
    sessions_per_cycle: int,
    total_session_count: int,
) -> tuple[int, int]:
    """Calculate start and end indices for session disruption in a cycle.

    Note: IXIA BGP session indices are 1-based, not 0-based.
    """
    # Calculate 0-based indices first
    start_idx_0_based = (cycle * sessions_per_cycle) % total_session_count
    end_idx_0_based = start_idx_0_based + sessions_per_cycle - 1
    if end_idx_0_based >= total_session_count:
        end_idx_0_based = total_session_count - 1

    # Convert to 1-based indices for IXIA
    start_idx = start_idx_0_based + 1
    end_idx = end_idx_0_based + 1
    return start_idx, end_idx


def _create_session_disruption_cycle_steps(
    cycle_num: int,
    num_cycles: int,
    session_groups: list[dict[str, Any]],
    uptime_seconds: int,
    downtime_seconds: int,
    context_name: str = "",
) -> list[Step]:
    """
    Create the standard disruption cycle steps: stop sessions, wait, start sessions, wait.

    Args:
        cycle_num: Current cycle number (1-indexed)
        num_cycles: Total number of cycles
        session_groups: List of session group definitions, each containing:
            - 'peer_regex': Regex to match peers
            - 'start_idx': Start index for sessions
            - 'end_idx': End index for sessions
            - 'session_count': Number of sessions to disrupt
            - 'description': Description for the session type (e.g., "IPv4", "IPv6")
        uptime_seconds: Session up time
        downtime_seconds: Session down time
        context_name: Additional context for descriptions (e.g., plane name)

    Returns:
        List of steps for this disruption cycle
    """
    context_prefix = f"({context_name}) " if context_name else ""
    steps = []

    # Step 1 & 2: Disable all session groups
    for group in session_groups:
        steps.append(
            create_start_stop_bgp_peers_step(
                peer_regex=group["peer_regex"],
                start=False,
                start_idx=group["start_idx"],
                end_idx=group["end_idx"],
                description=f"Cycle {cycle_num}/{num_cycles} {context_prefix}: Stop {group['description']} sessions {group['start_idx']}-{group['end_idx']} ({group['session_count']} sessions)",
            )
        )

    # Step 3: Wait for downtime duration
    steps.append(
        create_longevity_step(
            duration=downtime_seconds,
            description=f"Cycle {cycle_num}/{num_cycles} {context_prefix}: Keep sessions DOWN for {downtime_seconds}s",
        )
    )

    # Step 4 & 5: Re-enable all session groups
    for group in session_groups:
        steps.append(
            create_start_stop_bgp_peers_step(
                peer_regex=group["peer_regex"],
                start=True,
                start_idx=group["start_idx"],
                end_idx=group["end_idx"],
                description=f"Cycle {cycle_num}/{num_cycles} {context_prefix}: Start {group['description']} sessions {group['start_idx']}-{group['end_idx']} ({group['session_count']} sessions)",
            )
        )

    # Step 6: Wait for uptime duration (skip for last cycle)
    steps.append(
        create_longevity_step(
            duration=uptime_seconds,
            description=f"Cycle {cycle_num}/{num_cycles} {context_prefix}: Keep sessions UP for {uptime_seconds}s",
        )
    )

    return steps


def create_cycle_based_session_disruption_stage(
    ipv4_peer_regex: str,
    ipv6_peer_regex: str,
    test_duration_seconds: int,
    uptime_seconds: int,
    downtime_seconds: int,
    sessions_per_cycle: int,
    ipv4_session_count: int,
    ipv6_session_count: int,
    convergence_wait_seconds: int = 120,
) -> Stage:
    """
    Create stage that cycles through different subsets of IPv4 and IPv6 BGP sessions for disruption.

    This approach disrupts both IPv4 and IPv6 sessions simultaneously using session start/end indices,
    splitting the sessions_per_cycle between the two address families.

    Args:
        ipv4_peer_regex: Regex to match IPv4 BGP peers
        ipv6_peer_regex: Regex to match IPv6 BGP peers
        test_duration_seconds: Total test duration
        uptime_seconds: Session up time per cycle
        downtime_seconds: Session down time per cycle
        sessions_per_cycle: Total number of sessions to disrupt per cycle (split between v4/v6)
        ipv4_session_count: Total IPv4 sessions available
        ipv6_session_count: Total IPv6 sessions available
        convergence_wait_seconds: Time to wait for sessions to re-establish after cycles (default: 120s)

    Returns:
        Stage with explicit cycle-based disruption steps for IPv4 and IPv6 sessions
    """
    cycle_duration = uptime_seconds + downtime_seconds
    num_cycles = test_duration_seconds // cycle_duration

    # Split sessions between IPv4 and IPv6 (roughly 50/50)
    ipv4_sessions_per_cycle = sessions_per_cycle // 2
    ipv6_sessions_per_cycle = sessions_per_cycle - ipv4_sessions_per_cycle

    steps = []

    for cycle in range(num_cycles):
        cycle_num = cycle + 1

        # Calculate session indices for both IPv4 and IPv6
        ipv4_start_idx, ipv4_end_idx = _calculate_session_indices(
            cycle, ipv4_sessions_per_cycle, ipv4_session_count
        )
        ipv6_start_idx, ipv6_end_idx = _calculate_session_indices(
            cycle, ipv6_sessions_per_cycle, ipv6_session_count
        )

        # Define session groups for this cycle
        session_groups = [
            {
                "peer_regex": ipv4_peer_regex,
                "start_idx": ipv4_start_idx,
                "end_idx": ipv4_end_idx,
                "session_count": ipv4_sessions_per_cycle,
                "description": "IPv4",
            },
            {
                "peer_regex": ipv6_peer_regex,
                "start_idx": ipv6_start_idx,
                "end_idx": ipv6_end_idx,
                "session_count": ipv6_sessions_per_cycle,
                "description": "IPv6",
            },
        ]

        # Create disruption steps for this cycle
        cycle_steps = _create_session_disruption_cycle_steps(
            cycle_num=cycle_num,
            num_cycles=num_cycles,
            session_groups=session_groups,
            uptime_seconds=uptime_seconds,
            downtime_seconds=downtime_seconds,
        )
        steps.extend(cycle_steps)

    # Re-enable ALL sessions to ensure clean state for postchecks
    steps.append(
        create_start_stop_bgp_peers_step(
            peer_regex=ipv4_peer_regex,
            start=True,
            start_idx=1,
            end_idx=ipv4_session_count,
            description=f"Re-enable ALL IPv4 sessions (1-{ipv4_session_count})",
        )
    )
    steps.append(
        create_start_stop_bgp_peers_step(
            peer_regex=ipv6_peer_regex,
            start=True,
            start_idx=1,
            end_idx=ipv6_session_count,
            description=f"Re-enable ALL IPv6 sessions (1-{ipv6_session_count})",
        )
    )
    # Wait for all sessions to re-establish
    steps.append(
        create_longevity_step(
            duration=convergence_wait_seconds,
            description=f"Wait for all BGP sessions to re-establish ({convergence_wait_seconds}s)",
        )
    )

    return Stage(steps=steps)


def create_plane_based_session_disruption_stage(
    plane_definitions: list[dict[str, Any]],
    test_duration_seconds: int,
    uptime_seconds: int,
    downtime_seconds: int,
    sessions_per_plane: int = 16,  # Default sessions per plane to disrupt
    convergence_wait_seconds: int = 120,
) -> Stage:
    """
    Create stage that cycles through different planes for BGP session disruption.

    This approach is designed for iBGP scenarios where sessions are organized by planes.
    It cycles through planes (e.g., DC plane1, DC plane2, MP plane1, etc.) and within
    each plane disrupts a subset of both IPv4 and IPv6 sessions.

    Args:
        plane_definitions: List of plane definitions, each containing:
            - 'name': Human-readable plane name (e.g., "DC Plane 1")
            - 'ipv4_regex': Regex to match IPv4 sessions for this plane
            - 'ipv6_regex': Regex to match IPv6 sessions for this plane
            - 'ipv4_session_count': Total IPv4 sessions in this plane
            - 'ipv6_session_count': Total IPv6 sessions in this plane
        test_duration_seconds: Total test duration
        uptime_seconds: Session up time per cycle
        downtime_seconds: Session down time per cycle
        sessions_per_plane: Number of sessions to disrupt per plane (split between v4/v6)
        convergence_wait_seconds: Time to wait for sessions to re-establish after cycles (default: 120s)

    Returns:
        Stage with plane-based session disruption steps

    Example usage:
        plane_definitions = [
            {
                'name': 'DC Plane 1',
                'ipv4_regex': '.*IBGP.*DC.*PLANE1.*IPV4.*',
                'ipv6_regex': '.*IBGP.*DC.*PLANE1.*IPV6.*',
                'ipv4_session_count': 50,
                'ipv6_session_count': 50,
            },
            {
                'name': 'DC Plane 2',
                'ipv4_regex': '.*IBGP.*DC.*PLANE2.*IPV4.*',
                'ipv6_regex': '.*IBGP.*DC.*PLANE2.*IPV6.*',
                'ipv4_session_count': 50,
                'ipv6_session_count': 50,
            },
            # ... more planes
        ]
    """
    cycle_duration = uptime_seconds + downtime_seconds
    num_cycles = test_duration_seconds // cycle_duration
    num_planes = len(plane_definitions)

    if num_planes == 0:
        raise ValueError("At least one plane definition is required")

    # Split sessions per plane between IPv4 and IPv6
    ipv4_sessions_per_plane = sessions_per_plane // 2
    ipv6_sessions_per_plane = sessions_per_plane - ipv4_sessions_per_plane

    steps = []

    for cycle in range(num_cycles):
        cycle_num = cycle + 1

        # Select which plane to target this cycle (round-robin through planes)
        plane_idx = cycle % num_planes
        plane = plane_definitions[plane_idx]
        plane_name = plane["name"]

        # Calculate session indices for this plane and cycle
        plane_cycle = (
            cycle // num_planes
        )  # How many times we've cycled through all planes

        # Calculate IPv4 and IPv6 session indices using helper function
        ipv4_start_idx, ipv4_end_idx = _calculate_session_indices(
            plane_cycle, ipv4_sessions_per_plane, plane["ipv4_session_count"]
        )
        ipv6_start_idx, ipv6_end_idx = _calculate_session_indices(
            plane_cycle, ipv6_sessions_per_plane, plane["ipv6_session_count"]
        )

        # Step 1: Disable IPv4 sessions in the target plane
        steps.append(
            create_start_stop_bgp_peers_step(
                peer_regex=plane["ipv4_regex"],
                start=False,
                start_idx=ipv4_start_idx,
                end_idx=ipv4_end_idx,
                description=f"Cycle {cycle_num}/{num_cycles} ({plane_name}): Stop IPv4 sessions {ipv4_start_idx}-{ipv4_end_idx} ({ipv4_sessions_per_plane} sessions)",
            )
        )

        # Step 2: Disable IPv6 sessions in the target plane
        steps.append(
            create_start_stop_bgp_peers_step(
                peer_regex=plane["ipv6_regex"],
                start=False,
                start_idx=ipv6_start_idx,
                end_idx=ipv6_end_idx,
                description=f"Cycle {cycle_num}/{num_cycles} ({plane_name}): Stop IPv6 sessions {ipv6_start_idx}-{ipv6_end_idx} ({ipv6_sessions_per_plane} sessions)",
            )
        )

        # Step 3: Wait for downtime duration
        steps.append(
            create_longevity_step(
                duration=downtime_seconds,
                description=f"Cycle {cycle_num}/{num_cycles} ({plane_name}): Keep sessions DOWN for {downtime_seconds}s",
            )
        )

        # Step 4: Re-enable IPv4 sessions in the target plane
        steps.append(
            create_start_stop_bgp_peers_step(
                peer_regex=plane["ipv4_regex"],
                start=True,
                start_idx=ipv4_start_idx,
                end_idx=ipv4_end_idx,
                description=f"Cycle {cycle_num}/{num_cycles} ({plane_name}): Start IPv4 sessions {ipv4_start_idx}-{ipv4_end_idx} ({ipv4_sessions_per_plane} sessions)",
            )
        )

        # Step 5: Re-enable IPv6 sessions in the target plane
        steps.append(
            create_start_stop_bgp_peers_step(
                peer_regex=plane["ipv6_regex"],
                start=True,
                start_idx=ipv6_start_idx,
                end_idx=ipv6_end_idx,
                description=f"Cycle {cycle_num}/{num_cycles} ({plane_name}): Start IPv6 sessions {ipv6_start_idx}-{ipv6_end_idx} ({ipv6_sessions_per_plane} sessions)",
            )
        )

        # Step 6: Wait for uptime duration (skip for last cycle)
        steps.append(
            create_longevity_step(
                duration=uptime_seconds,
                description=f"Cycle {cycle_num}/{num_cycles} ({plane_name}): Keep sessions UP for {uptime_seconds}s",
            )
        )

    # Re-enable ALL sessions across all planes to ensure clean state for postchecks
    for plane in plane_definitions:
        steps.append(
            create_start_stop_bgp_peers_step(
                peer_regex=plane["ipv4_regex"],
                start=True,
                start_idx=1,
                end_idx=plane["ipv4_session_count"],
                description=f"Re-enable ALL IPv4 sessions for {plane['name']} (1-{plane['ipv4_session_count']})",
            )
        )
        steps.append(
            create_start_stop_bgp_peers_step(
                peer_regex=plane["ipv6_regex"],
                start=True,
                start_idx=1,
                end_idx=plane["ipv6_session_count"],
                description=f"Re-enable ALL IPv6 sessions for {plane['name']} (1-{plane['ipv6_session_count']})",
            )
        )
    # Wait for all sessions to re-establish
    steps.append(
        create_longevity_step(
            duration=convergence_wait_seconds,
            description=f"Wait for all BGP sessions to re-establish ({convergence_wait_seconds}s)",
        )
    )

    return Stage(steps=steps)


def generate_tornado_plane_definitions(
    ipv4_peer_regex: str,
    ipv6_peer_regex: str,
    tornado_planes: list[int],
    session_type: str,
    ipv4_sessions_per_plane: int = 50,
    ipv6_sessions_per_plane: int = 50,
) -> list[dict[str, Any]]:
    """
    Generate tornado plane definitions for BGP sessions.

    This helper function creates plane definitions for both EB and MP variants
    based on the requested session types and tornado planes.

    Args:
        ipv4_peer_regex: Simple IPv4 regex pattern (e.g., ".*IPV4_IBGP.*")
        ipv6_peer_regex: Simple IPv6 regex pattern (e.g., ".*IPV6_IBGP.*")
        tornado_planes: List of tornado plane numbers (e.g., [1, 2, 3, 4])
        session_type: Type of sessions to generate - "eb", "mp", or "both"
        ipv4_sessions_per_plane: Number of IPv4 sessions per plane (for cycle-based mode)
        ipv6_sessions_per_plane: Number of IPv6 sessions per plane (for cycle-based mode)

    Returns:
        List of plane definitions, each containing:
            - 'name': Human-readable plane name (e.g., "Tornado Plane 1 EB")
            - 'ipv4_regex': Plane-specific IPv4 regex pattern
            - 'ipv6_regex': Plane-specific IPv6 regex pattern
            - 'ipv4_session_count': Number of IPv4 sessions (for cycle-based mode)
            - 'ipv6_session_count': Number of IPv6 sessions (for cycle-based mode)

    Example:
        generate_tornado_plane_definitions(
            ipv4_peer_regex=".*IPV4_IBGP.*",
            ipv6_peer_regex=".*IPV6_IBGP.*",
            tornado_planes=[1, 2],
            session_type="both",
        )
    """
    # Validate session_type parameter
    valid_session_types = {"eb", "mp", "both"}
    if session_type not in valid_session_types:
        raise ValueError(
            f"session_type must be one of {valid_session_types}, got: {session_type}"
        )

    plane_definitions = []

    # Generate tornado planes with requested session types
    for plane_num in tornado_planes:
        # Generate EB variant if requested
        if session_type in ("eb", "both"):
            ipv4_eb_regex = transform_to_plane_regex(
                ipv4_peer_regex, plane_num, "EB", "IPV4_IBGP"
            )
            ipv6_eb_regex = transform_to_plane_regex(
                ipv6_peer_regex, plane_num, "EB", "IPV6_IBGP"
            )

            plane_definitions.append(
                {
                    "name": f"Tornado Plane {plane_num} EB",
                    "ipv4_regex": ipv4_eb_regex,
                    "ipv6_regex": ipv6_eb_regex,
                    "ipv4_session_count": ipv4_sessions_per_plane,
                    "ipv6_session_count": ipv6_sessions_per_plane,
                }
            )

        # Generate MP variant if requested
        if session_type in ("mp", "both"):
            ipv4_mp_regex = transform_to_plane_regex(
                ipv4_peer_regex, plane_num, "MP", "IPV4_IBGP"
            )
            ipv6_mp_regex = transform_to_plane_regex(
                ipv6_peer_regex, plane_num, "MP", "IPV6_IBGP"
            )

            plane_definitions.append(
                {
                    "name": f"Tornado Plane {plane_num} MP",
                    "ipv4_regex": ipv4_mp_regex,
                    "ipv6_regex": ipv6_mp_regex,
                    "ipv4_session_count": ipv4_sessions_per_plane,
                    "ipv6_session_count": ipv6_sessions_per_plane,
                }
            )

    return plane_definitions


def transform_to_plane_regex(
    user_regex: str, plane_num: int, session_type: str, protocol: str
) -> str:
    """
    Transform a user-provided regex pattern into a plane-specific regex pattern.

    This function is more robust than simple string replacement and handles various
    user input patterns flexibly.

    Args:
        user_regex: User-provided regex pattern (e.g., ".*IPV4_IBGP.*", ".*IPV4_IBGP$")
        plane_num: Tornado plane number (e.g., 1, 2, 3, 4)
        session_type: Type of session ("EB" or "MP")
        protocol: Protocol identifier ("IPV4_IBGP" or "IPV6_IBGP")

    Returns:
        Plane-specific regex pattern (e.g., ".*IPV4_IBGP_PLANE_1_REMOTE_EB$")

    Examples:
        transform_to_plane_regex(".*IPV4_IBGP.*", 1, "EB", "IPV4_IBGP")
        -> ".*IPV4_IBGP_PLANE_1_REMOTE_EB$"

        transform_to_plane_regex(".*IPV4_IBGP$", 2, "MP", "IPV4_IBGP")
        -> ".*IPV4_IBGP_PLANE_2_REMOTE_MP$"

        transform_to_plane_regex("DEVICE_GROUP_IPV6_IBGP.*", 3, "EB", "IPV6_IBGP")
        -> "DEVICE_GROUP_IPV6_IBGP_PLANE_3_REMOTE_EB$"
    """

    # Create the target pattern we want to generate
    target_pattern = f".*{protocol}_PLANE_{plane_num}_REMOTE_{session_type}$"

    # Handle various user input patterns by finding the protocol and replacing appropriately
    if protocol in user_regex:
        # Find the protocol in the user regex and build the replacement
        # Handle patterns like: ".*IPV4_IBGP.*", ".*IPV4_IBGP$", "DEVICE_GROUP_IPV4_IBGP.*"

        # Find everything before the protocol
        match = re.search(f"(.*?){re.escape(protocol)}", user_regex)
        if match:
            prefix = match.group(1)
            # Build the new pattern with the same prefix
            return f"{prefix}{protocol}_PLANE_{plane_num}_REMOTE_{session_type}$"

    # Fallback: If we can't parse the pattern, return a sensible default
    # This shouldn't happen in normal usage but provides robustness
    return target_pattern


def create_plane_continuous_flapping_stage(
    plane_definitions: list[dict[str, Any]],
    test_duration_seconds: int,
    uptime_seconds: int,
    downtime_seconds: int,
) -> Stage:
    """
    Create a stage with continuous BGP flapping for all specified plane sessions.

    This helper function creates steps to enable flapping, run for duration, then disable flapping
    for all plane definitions provided.

    Args:
        plane_definitions: List of plane definitions, each containing:
            - 'name': Human-readable plane name (e.g., "Tornado Plane 1 EB")
            - 'ipv4_regex': Plane-specific IPv4 regex pattern
            - 'ipv6_regex': Plane-specific IPv6 regex pattern
        test_duration_seconds: Total test duration
        uptime_seconds: Session up time per flap cycle
        downtime_seconds: Session down time per flap cycle

    Returns:
        Stage with continuous flapping steps for all plane sessions

    Example:
        plane_definitions = [
            {
                "name": "Tornado Plane 1 EB",
                "ipv4_regex": ".*IPV4_IBGP_PLANE_1_REMOTE_EB$",
                "ipv6_regex": ".*IPV6_IBGP_PLANE_1_REMOTE_EB$",
            }
        ]
        stage = create_plane_continuous_flapping_stage(
            plane_definitions=plane_definitions,
            test_duration_seconds=3600,
            uptime_seconds=30,
            downtime_seconds=30,
        )
    """
    duration_minutes = test_duration_seconds // 60
    steps: list[Step] = []

    # Enable flapping for all plane regex patterns
    for plane_def in plane_definitions:
        steps.extend(
            [
                create_configure_bgp_flap_step(
                    peer_regex=plane_def["ipv4_regex"],
                    enable=True,
                    uptime_seconds=uptime_seconds,
                    downtime_seconds=downtime_seconds,
                    description=f"Enable {plane_def['name']} IPv4 BGP flapping: {uptime_seconds}s up, {downtime_seconds}s down",
                ),
                create_configure_bgp_flap_step(
                    peer_regex=plane_def["ipv6_regex"],
                    enable=True,
                    uptime_seconds=uptime_seconds,
                    downtime_seconds=downtime_seconds,
                    description=f"Enable {plane_def['name']} IPv6 BGP flapping: {uptime_seconds}s up, {downtime_seconds}s down",
                ),
            ]
        )

    # Let all plane sessions flap for the duration
    steps.append(
        create_longevity_step(
            duration=test_duration_seconds,
            description=f"Run plane-aware BGP continuous flapping for {duration_minutes} minutes",
        )
    )

    # Disable flapping for all plane regex patterns
    for plane_def in plane_definitions:
        steps.extend(
            [
                create_configure_bgp_flap_step(
                    peer_regex=plane_def["ipv4_regex"],
                    enable=False,
                    description=f"Disable {plane_def['name']} IPv4 BGP flapping",
                ),
                create_configure_bgp_flap_step(
                    peer_regex=plane_def["ipv6_regex"],
                    enable=False,
                    description=f"Disable {plane_def['name']} IPv6 BGP flapping",
                ),
            ]
        )

    return Stage(steps=steps)


def create_plane_aware_bgp_session_oscillation_stage(
    ipv4_peer_regex: str,
    ipv6_peer_regex: str,
    test_duration_seconds: int = 3600,
    uptime_seconds: int = 30,
    downtime_seconds: int = 30,
    sessions_per_plane: int | None = None,
    ipv4_sessions_per_plane: int = 50,
    ipv6_sessions_per_plane: int = 50,
    tornado_planes: list[int] | None = None,
    session_type: str = "both",
) -> Stage:
    """
    Create a plane-aware BGP session oscillation stage with two modes:

    Mode 1 - Continuous flapping: All plane sessions flap continuously
    Usage: create_plane_aware_bgp_session_oscillation_stage(
           ipv4_peer_regex=".*IPV4_IBGP.*",
           ipv6_peer_regex=".*IPV6_IBGP.*",
           session_type="eb"  # or "mp" or "both"
       )

    Mode 2 - Cycle-based disruption: Different planes disrupted each cycle
    Usage: create_plane_aware_bgp_session_oscillation_stage(
        sessions_per_plane=16,
        ipv4_peer_regex=".*IPV4_IBGP.*",
        ipv6_peer_regex=".*IPV6_IBGP.*",
        ipv4_sessions_per_plane=50,
        ipv6_sessions_per_plane=50,
        session_type="both"
    )

    Args:
        ipv4_peer_regex: Simple IPv4 regex pattern (e.g., ".*IPV4_IBGP.*")
        ipv6_peer_regex: Simple IPv6 regex pattern (e.g., ".*IPV6_IBGP.*")
        test_duration_seconds: Total test duration (default: 1 hour)
        uptime_seconds: Session up time per cycle (default: 30s)
        downtime_seconds: Session down time per cycle (default: 30s)
        sessions_per_plane: Number of sessions to disrupt per plane (cycle-based mode)
        ipv4_sessions_per_plane: Number of IPv4 sessions per plane
        ipv6_sessions_per_plane: Number of IPv6 sessions per plane
        tornado_planes: List of tornado plane numbers (default: [1, 2, 3, 4])
        session_type: Type of sessions to flap - "eb", "mp", or "both" (default: "both")

    Returns:
        Stage with plane-aware session disruption

    Example usage:
        # Continuous flapping mode - all EB sessions flap simultaneously
        create_plane_aware_bgp_session_oscillation_stage(
            ipv4_peer_regex=".*IPV4_IBGP.*",
            ipv6_peer_regex=".*IPV6_IBGP.*",
            session_type="eb",
        )

        # Cycle-based disruption mode - cycle through planes
        create_plane_aware_bgp_session_oscillation_stage(
            sessions_per_plane=16,
            ipv4_peer_regex=".*IPV4_IBGP.*",
            ipv6_peer_regex=".*IPV6_IBGP.*",
            ipv4_sessions_per_plane=50,
            ipv6_sessions_per_plane=50,
            session_type="both",
        )
    """
    if tornado_planes is None:
        tornado_planes = [1, 2, 3, 4]

    # Validate session_type parameter
    valid_session_types = {"eb", "mp", "both"}
    if session_type not in valid_session_types:
        raise ValueError(
            f"session_type must be one of {valid_session_types}, got: {session_type}"
        )

    # Use helper function to generate tornado plane definitions
    plane_definitions = generate_tornado_plane_definitions(
        ipv4_peer_regex=ipv4_peer_regex,
        ipv6_peer_regex=ipv6_peer_regex,
        tornado_planes=tornado_planes,
        session_type=session_type,
        ipv4_sessions_per_plane=ipv4_sessions_per_plane,
        ipv6_sessions_per_plane=ipv6_sessions_per_plane,
    )

    if sessions_per_plane is not None:
        # Cycle-based disruption mode - requires plane session counts
        return create_plane_based_session_disruption_stage(
            plane_definitions=plane_definitions,
            test_duration_seconds=test_duration_seconds,
            uptime_seconds=uptime_seconds,
            downtime_seconds=downtime_seconds,
            sessions_per_plane=sessions_per_plane,
        )
    else:
        # Continuous flapping mode - all plane sessions flap simultaneously
        return create_plane_continuous_flapping_stage(
            plane_definitions=plane_definitions,
            test_duration_seconds=test_duration_seconds,
            uptime_seconds=uptime_seconds,
            downtime_seconds=downtime_seconds,
        )


def create_bgp_igp_instability_unresolvable_pnhs_stage(
    device_name: str,
    start_ipv4s: list[str],
    start_ipv6s: list[str],
    tcp_dump_capture_interface: str = "any",
    count: int = 63,
    step: int = 2,
    delete_count: int = 20,
) -> Stage:
    """
    Create a test stage to verify BGP convergence behavior when IGP routes become unavailable.

    This stage tests BGP's handling of unresolvable Protocol Next-Hops (PNHs) by deleting
    Open/R routes that BGP uses to resolve next-hops. When these IGP routes are removed,
    BGP next-hops become unresolvable, simulating IGP instability. The test verifies that
    BGP converges properly and remains stable without continuous route updates.

    The test sequence:
    1. Delete Open/R routes sequentially to create unresolvable BGP next-hops
    2. Start tcpdump to capture BGP updates on monitoring interface
    3. Soak for 30 minutes to ensure sustained convergence
    4. Stop final tcpdump capture

    Args:
        device_name: Name of the device under test
        start_ipv4s: List of starting IPv4 addresses for Open/R route deletion
        start_ipv6s: List of starting IPv6 addresses for Open/R route deletion
        count: Number of routes created from start ips
        step: Step size for routes
        delete_count: Number of routes to delete (default: 20)

    Returns:
        Stage object for BGP IGP instability test with unresolvable PNHs

    Example:
        stage = create_bgp_igp_instability_unresolvable_pnhs_stage(
            device_name="rsw1ag.p001.f01.atn1",
            start_ipv4s=["10.1.1.0"],
            start_ipv6s=["2001:db8::"],
        )
    """
    steps = []

    # Step 1: Start tcpdump capture on BGP MON interface
    steps.append(
        create_tcpdump_step(
            device_name=device_name,
            mode="start_capture",
            message_type="Update",
            interface=tcp_dump_capture_interface,
        ),
    )

    # Step 2: Delete 20 routes, on Plane 1 Sequentially for IPV4/6
    steps.append(
        create_openr_route_action_step(
            device_name=device_name,
            start_ipv4s=start_ipv4s,
            start_ipv6s=start_ipv6s,
            local_link=DEFAULT_LOCAL_LINK,
            other_link=DEFAULT_OTHER_LINK,
            action=OpenRRouteAction.DELETE.value,
            count=count,
            step=2,
            sequential=True,
            delete_count=delete_count,
            description="Perform Open/R Route deletion using default Open/R configuration",
        ),
    )

    # Step 3: Wait 30 minutes
    steps.append(
        create_longevity_step(duration=1800),
    )

    # Step 4: Stop tcpdump capture
    steps.append(
        create_tcpdump_step(
            device_name=device_name,
            mode="stop_capture",
            description="Stop tcpdump capture",
        ),
    )
    return Stage(steps=steps)


def _create_route_oscillation_cycle_steps(
    device_name: str,
    withdraw_time: int,
    readvertise_time: int,
    prefix_pool_regex: str,
    prefix_start_index: int,
    prefix_end_index: int | None = None,
) -> list[Step]:
    """
    Create steps for a single route oscillation cycle.

    This helper function creates a sequence of steps that withdraw prefixes,
    wait for specified duration, then readvertise those prefixes.

    Args:
        device_name: Name of the device
        withdraw_time: Duration to wait after withdrawing prefixes (seconds)
        readvertise_time: Duration to wait after readvertising prefixes (seconds)
        prefix_pool_regex: Regex pattern to match prefix pools
        prefix_start_index: Starting index of the prefix range
        prefix_end_index: Ending index of the prefix range (optional)

    Returns:
        List of steps for one complete route oscillation cycle
    """
    steps = []
    # Step 1: Withdraw prefixes
    steps.append(
        create_advertise_withdraw_prefixes_step(
            device_name, False, prefix_pool_regex, prefix_start_index, prefix_end_index
        )
    )

    # Step 2: Wait {withdraw_time} seconds
    steps.append(
        create_longevity_step(
            duration=withdraw_time,
            description=f"Sleep for withdraw. {withdraw_time} seconds",
        )
    )
    # Step 3: Readvertise prefixes
    steps.append(
        create_advertise_withdraw_prefixes_step(
            device_name, True, prefix_pool_regex, prefix_start_index, prefix_end_index
        )
    )

    # Step 4: Wait {readvertise_time} seconds
    steps.append(
        create_longevity_step(
            duration=readvertise_time,
            description=f"Sleep for readvertising. {readvertise_time} seconds",
        )
    )
    return steps


def _create_route_oscillation_cycle_steps_spread(
    device_name: str,
    withdraw_time: int,
    readvertise_time: int,
    prefix_start_index: int,
    prefix_end_index: int | None = None,
) -> list[Step]:
    """
    Create steps for a single route oscillation cycle.

    This helper function creates a sequence of steps that withdraw prefixes,
    wait for specified duration, then readvertise those prefixes.

    The difference from _create_route_oscillation_cycle_steps is that this function can control
    prefix pools for different peers. So we can have one set of prefixes advertise/withdraw routes without affecting
    other peers. This is specifically created for T249042290. General implementation can be created later.

    Args:
        device_name: Name of the device
        withdraw_time: Duration to wait after withdrawing prefixes (seconds)
        readvertise_time: Duration to wait after readvertising prefixes (seconds)
        prefix_start_index: Starting index of the prefix range
        prefix_end_index: Ending index of the prefix range (optional)

    Returns:
        List of steps for one complete route oscillation cycle
    """
    steps = []
    # Step 1: Withdraw prefixes
    steps.append(
        create_advertise_withdraw_prefixes_step(
            device_name, False, ".*EBGP_SET1.*", prefix_start_index, prefix_end_index
        )
    )

    steps.append(
        create_advertise_withdraw_prefixes_step(
            device_name, False, ".*EBGP_SET2.*", prefix_start_index, prefix_end_index
        )
    )

    steps.append(
        create_advertise_withdraw_prefixes_step(
            device_name, False, ".*EBGP_SET3.*", prefix_start_index, prefix_end_index
        )
    )

    # Step 2: Wait {withdraw_time} seconds
    steps.append(
        create_longevity_step(
            duration=withdraw_time,
            description=f"Sleep for withdraw. {withdraw_time} seconds",
        )
    )
    # Step 3: Readvertise prefixes
    steps.append(
        create_advertise_withdraw_prefixes_step(
            device_name, True, ".*EBGP_SET1.*", prefix_start_index, prefix_end_index
        )
    )

    steps.append(
        create_advertise_withdraw_prefixes_step(
            device_name, True, ".*EBGP_SET2.*", prefix_start_index, prefix_end_index
        )
    )

    steps.append(
        create_advertise_withdraw_prefixes_step(
            device_name, True, ".*EBGP_SET3.*", prefix_start_index, prefix_end_index
        )
    )

    # Step 4: Wait {readvertise_time} seconds
    steps.append(
        create_longevity_step(
            duration=readvertise_time,
            description=f"Sleep for readvertising. {readvertise_time} seconds",
        )
    )
    return steps


def create_route_oscillations_stage(
    device_name: str,
    prefix_pool_regex: str,
    prefix_start_index: int,
    prefix_end_index: int | None = None,
    withdraw_time: int = 60,
    readvertise_time: int = 60,
    test_duration_seconds: int = 3600,
    spread: bool = False,
) -> Stage:
    """
    Create a stage that repeatedly oscillates BGP routes through withdraw and readvertise cycles.

    This stage tests BGP behavior under continuous route churn by repeatedly withdrawing
    and readvertising prefixes. Each cycle consists of withdrawing prefixes, waiting,
    then readvertising them back.

    Args:
        device_name: Name of the device
        prefix_pool_regex: Regex pattern to match prefix pools
        prefix_start_index: Starting index of the prefix range
        prefix_end_index: Ending index of the prefix range (optional)
        withdraw_time: Duration to keep prefixes withdrawn in each cycle (seconds, default: 60)
        readvertise_time: Duration to keep prefixes advertised in each cycle (seconds, default: 60)
        test_duration_seconds: Total test duration (default: 3600 seconds / 1 hour)
        spread: Spread the route oscillations across multiple prefix pools (default: False) to control different peers

    Returns:
        Stage with route oscillation steps
    """
    steps = []

    iterations = test_duration_seconds // (withdraw_time + readvertise_time)
    if spread:
        for _ in range(iterations):
            steps.extend(
                _create_route_oscillation_cycle_steps_spread(
                    device_name,
                    withdraw_time,
                    readvertise_time,
                    prefix_start_index,
                    prefix_end_index,
                )
            )
        return Stage(steps=steps)

    for _ in range(iterations):
        steps.extend(
            _create_route_oscillation_cycle_steps(
                device_name,
                withdraw_time,
                readvertise_time,
                prefix_pool_regex,
                prefix_start_index,
                prefix_end_index,
            )
        )
    return Stage(steps=steps)


def _create_local_pref_churn_cycle_steps(
    prefix_pool_regex: str,
    prefix_start_index: int,
    prefix_end_index: int | None = None,
    churn_time: int = 60,
    local_pref_iters: int = 5,
) -> list[Step]:
    """
    Create steps for BGP local preference attribute churn cycles.

    This helper function generates a sequence of steps that repeatedly randomize
    the local preference attribute on BGP prefixes, then revert to the default value.

    Args:
        prefix_pool_regex: Regex pattern to match prefix pools
        prefix_start_index: Starting index of the prefix range
        prefix_end_index: Ending index of the prefix range (optional)
        churn_time: Duration to wait between attribute changes (seconds, default: 60)
        local_pref_iters: Number of local preference churn iterations (default: 5)

    Returns:
        List of steps for local preference churn cycles
    """
    steps = []
    for _ in range(local_pref_iters):
        # Change local preference
        steps.append(
            create_randomize_prefix_local_preference_step(
                prefix_pool_regex, prefix_start_index, prefix_end_index
            )
        )
        # Wait {churn_time} seconds
        steps.append(
            create_longevity_step(
                duration=churn_time,
                description=f"Sleep for {churn_time} seconds",
            )
        )
    if local_pref_iters > 0:
        # Revert local pref (100)
        steps.append(
            create_randomize_prefix_local_preference_step(
                prefix_pool_regex, prefix_start_index, prefix_end_index, 100, 101
            )
        )

        # Wait {churn_time} seconds
        steps.append(
            create_longevity_step(
                duration=churn_time,
                description=f"Sleep for {churn_time} seconds",
            )
        )
    return steps


def _create_med_churn_cycle_steps(
    prefix_pool_regex: str,
    prefix_start_index: int,
    prefix_end_index: int | None = None,
    med_value: int = -1,
    churn_time: int = 60,
    med_iters: int = 5,
) -> list[Step]:
    """
    Create steps for BGP MED (Multi-Exit Discriminator) attribute churn cycles.

    This helper function generates a sequence of steps that repeatedly change
    the MED attribute on BGP prefixes, then revert to the default value.

    Args:
        prefix_pool_regex: Regex pattern to match prefix pools
        prefix_start_index: Starting index of the prefix range
        prefix_end_index: Ending index of the prefix range (optional)
        med_value: MED value to set during churn (-1 for random, default: -1)
        churn_time: Duration to wait between attribute changes (seconds, default: 60)
        med_iters: Number of MED churn iterations (default: 5)

    Returns:
        List of steps for MED churn cycles
    """
    steps = []
    for _ in range(med_iters):
        # Change MED
        steps.append(
            create_bgp_prefixes_med_value_step(
                prefix_pool_regex, prefix_start_index, prefix_end_index, med_value
            )
        )

        # Wait {churn_time} seconds
        steps.append(
            create_longevity_step(
                duration=churn_time,
                description=f"Sleep for {churn_time} seconds",
            )
        )
    if med_iters > 0:
        # Revert MED
        steps.append(
            create_bgp_prefixes_med_value_step(
                prefix_pool_regex, prefix_start_index, prefix_end_index, 0
            )
        )

        # Wait {churn_time} seconds
        steps.append(
            create_longevity_step(
                duration=churn_time,
                description=f"Sleep for {churn_time} seconds",
            )
        )
    return steps


def _create_origin_churn_cycle_steps(
    prefix_pool_regex: str,
    prefix_start_index: int,
    prefix_end_index: int | None = None,
    churn_time: int = 60,
    origin_iters: int = 5,
) -> list[Step]:
    """
    Create steps for BGP origin attribute churn cycles.

    This helper function generates a sequence of steps that repeatedly change
    the origin attribute on BGP prefixes between IGP, EGP, and Incomplete values,
    then revert to IGP.

    Args:
        prefix_pool_regex: Regex pattern to match prefix pools
        prefix_start_index: Starting index of the prefix range
        prefix_end_index: Ending index of the prefix range (optional)
        churn_time: Duration to wait between attribute changes (seconds, default: 60)
        origin_iters: Number of origin churn iterations (default: 5)

    Returns:
        List of steps for origin attribute churn cycles
    """
    steps = []
    for _ in range(origin_iters):
        # Change Origin between IGP and EGP and Incomplete
        origin_value = random.choice(["igp", "egp", "incomplete"])
        steps.append(
            create_modify_bgp_prefixes_origin_value_step(
                prefix_pool_regex, prefix_start_index, origin_value, prefix_end_index
            )
        )
        # Wait {churn_time} seconds
        steps.append(
            create_longevity_step(
                duration=churn_time,
                description=f"Sleep for {churn_time} seconds",
            )
        )
    if origin_iters > 0:
        # Change Origin back to igp
        steps.append(
            create_modify_bgp_prefixes_origin_value_step(
                prefix_pool_regex, prefix_start_index, "igp", prefix_end_index
            )
        )
        # Wait {churn_time} seconds
        steps.append(
            create_longevity_step(
                duration=churn_time,
                description=f"Sleep for {churn_time} seconds",
            )
        )
    return steps


def _create_change_as_path_length_step(
    prefix_pool_regex: str,
    as_path_length_max: int = 1,
    churn_time: int = 60,
    as_path_iters: int = 5,
) -> list[Step]:
    """
    This helper function generates steps to change the AS path length of BGP prefixes.
    """
    steps = []
    for _ in range(as_path_iters):
        as_path_length = 1
        if as_path_length_max > 1:
            as_path_length = random.randint(2, as_path_length_max + 1)

        # Change AS path
        steps.append(
            create_change_as_path_length_step(prefix_pool_regex, as_path_length)
        )
        # Wait {churn_time} seconds
        steps.append(
            create_longevity_step(
                duration=churn_time,
                description=f"Sleep for {churn_time} seconds",
            )
        )

    if as_path_iters > 0:
        # Revert AS path
        steps.append(create_change_as_path_length_step(prefix_pool_regex, 1))

        # Wait {churn_time} seconds
        steps.append(
            create_longevity_step(
                duration=churn_time,
                description=f"Sleep for {churn_time} seconds",
            )
        )

    return steps


def create_attribute_churn_stage(
    prefix_pool_regex: str,
    prefix_pool_regex_as_path: str,
    prefix_start_index: int,
    prefix_end_index: int | None = None,
    med_value: int = -1,
    as_path_length_max: int = 10,
    churn_time: int = 60,
    local_pref_iters: int = 5,
    med_iters: int = 5,
    origin_iters: int = 5,
    as_path_iters: int = 5,
) -> Stage:
    """
    Create a stage that performs comprehensive BGP attribute churn testing.

    This stage tests BGP behavior under continuous BGP attribute changes by sequentially
    churning different BGP path attributes: local preference, MED (Multi-Exit Discriminator),
    and origin. Each attribute type is churned for specified number of iterations before
    moving to the next attribute type.

    Args:
        prefix_pool_regex: Regex pattern to match prefix pools
        prefix_pool_regex_as_path: Regex pattern to match prefix pools for AS path churn (a different one is used because we need to stop session to change as path)
        prefix_start_index: Starting index of the prefix range
        prefix_end_index: Ending index of the prefix range (optional)
        med_value: MED value to use during MED churn (-1 for random, default: -1)
        as_path_length_max: Max length of as path
        churn_time: Duration to wait between attribute changes (seconds, default: 60)
        local_pref_iters: Number of local preference churn iterations (default: 5)
        med_iters: Number of MED churn iterations (default: 5)
        origin_iters: Number of origin attribute churn iterations (default: 5)
        as_path_iters: Number of AS path churn iterations (default: 5, currently unused)

    Returns:
        Stage with comprehensive BGP attribute churn steps
    """
    steps = []
    steps.extend(
        _create_local_pref_churn_cycle_steps(
            prefix_pool_regex,
            prefix_start_index,
            prefix_end_index,
            churn_time,
            local_pref_iters,
        )
    )

    steps.extend(
        _create_med_churn_cycle_steps(
            prefix_pool_regex,
            prefix_start_index,
            prefix_end_index,
            med_value,
            churn_time,
            med_iters,
        )
    )

    steps.extend(
        _create_origin_churn_cycle_steps(
            prefix_pool_regex,
            prefix_start_index,
            prefix_end_index,
            churn_time,
            origin_iters,
        )
    )

    steps.extend(
        _create_change_as_path_length_step(
            prefix_pool_regex_as_path,
            as_path_length_max,
            churn_time,
            as_path_iters,
        )
    )

    return Stage(steps=steps)


def create_fauu_drain_undrain_stage(  # noqa: C901
    device_name: str,
    prefix_pool_regex: str,
    prefix_start_index: int = 0,
    prefix_end_index: int | None = 96,
    tcp_dump_capture_interface_ebgp: str | None = None,
    tcp_dump_capture_interface_bgpmon: str = "any",
    tcp_dump_capture_interface_ibgp: str | None = None,
    soak_time_seconds: int = 1800,
) -> Stage:
    """
    Create a test stage to verify BGP FAUU drain/undrain behavior on specific peers.

    This stage tests BGP's handling of attribute changes at the peer level by:
    1. Starting IXIA packet capture for drain phase on all configured interfaces
    2. Draining: Set local preference to 120 for specified peers
    3. Draining: Set origin to incomplete for specified peers
    4. Soak for specified duration after drain
    5. Save IXIA packet capture for drain phase
    6. Verify drain convergence inline (max 5 minutes)
    7. Start IXIA packet capture for undrain phase on all configured interfaces
    8. Undrain: Revert local preference to 100 for specified peers
    9. Undrain: Revert origin to IGP for specified peers
    10. Soak for specified duration after undrain
    11. Save IXIA packet capture for undrain phase
    12. Verify undrain convergence inline (max 5 minutes)
    13. Generate consolidated convergence report from all PCAP files

    Captures on up to 3 interfaces:
    - bgp_fauu_drain_ebgp.pcap / bgp_fauu_undrain_ebgp.pcap (eBGP SOURCE - where attributes originate)
    - bgp_fauu_drain_bgpmon.pcap / bgp_fauu_undrain_bgpmon.pcap (BGP monitor - observer)
    - bgp_fauu_drain_ibgp.pcap / bgp_fauu_undrain_ibgp.pcap (iBGP RECEIVER - attribute propagation)

    Args:
        device_name: Name of the device under test
        prefix_pool_regex: Regex pattern to match prefix pool names
        prefix_start_index: Starting index within the network group multiplier.
        prefix_end_index: Ending index within the network group multiplier. If None, use all.
        tcp_dump_capture_interface_ebgp: Optional interface for IXIA packet capture on eBGP (SOURCE) (default: None)
        tcp_dump_capture_interface_bgpmon: Interface for IXIA packet capture on BGP monitor (default: "any")
        tcp_dump_capture_interface_ibgp: Optional interface for IXIA packet capture on iBGP (RECEIVER) (default: None)
        soak_time_seconds: Soak duration after drain and undrain (default: 1800 / 30 minutes)

    Returns:
        Stage object for BGP FAUU drain/undrain test

    Example:
        # Drain/undrain on 96 EBGP prefixes, capture on all three interfaces
        stage = create_fauu_drain_undrain_stage(
            device_name="rsw1ag.p001.f01.atn1",
            prefix_pool_regex=".*EBGP.*",
            prefix_start_index=0,
            prefix_end_index=96,
            tcp_dump_capture_interface_ebgp="Ethernet1",  # eBGP interface (SOURCE)
            tcp_dump_capture_interface_bgpmon="Ethernet2",  # BGP monitor interface
            tcp_dump_capture_interface_ibgp="Ethernet3",  # iBGP interface (RECEIVER)
        )
    """
    steps = []

    # Step 1: Start IXIA packet capture on eBGP interface for drain (if provided)
    if tcp_dump_capture_interface_ebgp:
        steps.append(
            create_ixia_packet_capture_step(
                device_name=device_name,
                interface=tcp_dump_capture_interface_ebgp,
                mode="start",
                capture_id="fauu_drain_ebgp",
                description="Start IXIA packet capture for drain phase (eBGP SOURCE)",
            ),
        )

    # Step 2: Start IXIA packet capture on BGP monitor interface for drain
    steps.append(
        create_ixia_packet_capture_step(
            device_name=device_name,
            interface=tcp_dump_capture_interface_bgpmon,
            mode="start",
            capture_id="fauu_drain_bgpmon",
            description="Start IXIA packet capture for drain phase (BGP monitor)",
        ),
    )

    # Step 3: Start IXIA packet capture on iBGP interface for drain (if provided)
    if tcp_dump_capture_interface_ibgp:
        steps.append(
            create_ixia_packet_capture_step(
                device_name=device_name,
                interface=tcp_dump_capture_interface_ibgp,
                mode="start",
                capture_id="fauu_drain_ibgp",
                description="Start IXIA packet capture for drain phase (iBGP RECEIVER)",
            ),
        )

    # Step 4: Brief pause to ensure capture is ready
    steps.append(
        create_longevity_step(
            duration=5,
            description="Brief pause to ensure IXIA capture is ready (5 seconds)",
        ),
    )

    # Step 5: Drain - Change local preference
    steps.append(
        create_set_bgp_prefixes_local_preference_step(
            prefix_pool_regex=prefix_pool_regex,
            local_pref_value=120,
            prefix_start_index=prefix_start_index,
            prefix_end_index=prefix_end_index,
        ),
    )

    # Step 3: Drain - Change origin to incomplete for specified peers
    steps.append(
        create_modify_bgp_prefixes_origin_value_step(
            prefix_pool_regex=prefix_pool_regex,
            origin_value="incomplete",
            prefix_start_index=prefix_start_index,
            prefix_end_index=prefix_end_index,
        ),
    )

    # Step 7: Soak after drain
    steps.append(
        create_longevity_step(
            duration=soak_time_seconds,
            description=f"Soak after drain for {soak_time_seconds} seconds",
        ),
    )

    # Step 8: Stop IXIA packet capture for drain phase (eBGP)
    if tcp_dump_capture_interface_ebgp:
        steps.append(
            create_ixia_packet_capture_step(
                device_name=device_name,
                interface=tcp_dump_capture_interface_ebgp,
                mode="stop",
                capture_id="fauu_drain_ebgp",
                description="Stop IXIA packet capture for drain phase (eBGP SOURCE)",
            ),
        )

    # Step 9: Stop IXIA packet capture for drain phase (BGP monitor)
    steps.append(
        create_ixia_packet_capture_step(
            device_name=device_name,
            interface=tcp_dump_capture_interface_bgpmon,
            mode="stop",
            capture_id="fauu_drain_bgpmon",
            description="Stop IXIA packet capture for drain phase (BGP monitor)",
        ),
    )

    # Step 10: Stop IXIA packet capture for drain phase (iBGP)
    if tcp_dump_capture_interface_ibgp:
        steps.append(
            create_ixia_packet_capture_step(
                device_name=device_name,
                interface=tcp_dump_capture_interface_ibgp,
                mode="stop",
                capture_id="fauu_drain_ibgp",
                description="Stop IXIA packet capture for drain phase (iBGP RECEIVER)",
            ),
        )

    # Step 11: Save IXIA packet capture for drain phase (eBGP)
    if tcp_dump_capture_interface_ebgp:
        steps.append(
            create_ixia_packet_capture_step(
                device_name=device_name,
                interface=tcp_dump_capture_interface_ebgp,
                mode="save",
                pcap_filename="bgp_fauu_drain_ebgp.pcap",
                capture_id="fauu_drain_ebgp",
                description="Save IXIA packet capture for drain phase (eBGP SOURCE)",
            ),
        )

    # Step 12: Save IXIA packet capture for drain phase (BGP monitor)
    steps.append(
        create_ixia_packet_capture_step(
            device_name=device_name,
            interface=tcp_dump_capture_interface_bgpmon,
            mode="save",
            pcap_filename="bgp_fauu_drain_bgpmon.pcap",
            capture_id="fauu_drain_bgpmon",
            description="Save IXIA packet capture for drain phase (BGP monitor)",
        ),
    )

    # Step 13: Save IXIA packet capture for drain phase (iBGP)
    if tcp_dump_capture_interface_ibgp:
        steps.append(
            create_ixia_packet_capture_step(
                device_name=device_name,
                interface=tcp_dump_capture_interface_ibgp,
                mode="save",
                pcap_filename="bgp_fauu_drain_ibgp.pcap",
                capture_id="fauu_drain_ibgp",
                description="Save IXIA packet capture for drain phase (iBGP RECEIVER)",
            ),
        )

    # Step 14: Verify drain convergence (eBGP)
    if tcp_dump_capture_interface_ebgp:
        steps.append(
            create_drain_convergence_verification_step(
                pcap_filename="bgp_fauu_drain_ebgp.pcap",
                max_convergence_time_seconds=300,  # 5 minutes for FAUU
                expected_as_path_asn=None,
                phase="drain (eBGP SOURCE)",
            ),
        )

    # Step 15: Verify drain convergence (BGP monitor)
    steps.append(
        create_drain_convergence_verification_step(
            pcap_filename="bgp_fauu_drain_bgpmon.pcap",
            max_convergence_time_seconds=300,  # 5 minutes for FAUU
            expected_as_path_asn=None,  # No AS_PATH check since we removed prepend
            phase="drain (BGP monitor)",
        ),
    )

    # Step 16: Verify drain convergence (iBGP)
    if tcp_dump_capture_interface_ibgp:
        steps.append(
            create_drain_convergence_verification_step(
                pcap_filename="bgp_fauu_drain_ibgp.pcap",
                max_convergence_time_seconds=300,  # 5 minutes for FAUU
                expected_as_path_asn=None,
                phase="drain (iBGP RECEIVER)",
            ),
        )

    # Step 16A: Generate consolidated drain convergence report
    pcap_files_drain = {"bgp_monitor": "bgp_fauu_drain_bgpmon.pcap"}
    if tcp_dump_capture_interface_ebgp:
        pcap_files_drain["ebgp_source"] = "bgp_fauu_drain_ebgp.pcap"
    if tcp_dump_capture_interface_ibgp:
        pcap_files_drain["ibgp_receiver"] = "bgp_fauu_drain_ibgp.pcap"

    steps.append(
        create_consolidated_convergence_report_step(
            phase="drain",
            pcap_files=pcap_files_drain,
            description="Generate consolidated drain convergence report",
        ),
    )

    # Step 17: Start new IXIA packet capture for undrain phase (eBGP)
    if tcp_dump_capture_interface_ebgp:
        steps.append(
            create_ixia_packet_capture_step(
                device_name=device_name,
                interface=tcp_dump_capture_interface_ebgp,
                mode="start",
                capture_id="fauu_undrain_ebgp",
                description="Start IXIA packet capture for undrain phase (eBGP SOURCE)",
            ),
        )

    # Step 18: Start new IXIA packet capture for undrain phase (BGP monitor)
    steps.append(
        create_ixia_packet_capture_step(
            device_name=device_name,
            interface=tcp_dump_capture_interface_bgpmon,
            mode="start",
            capture_id="fauu_undrain_bgpmon",
            description="Start IXIA packet capture for undrain phase (BGP monitor)",
        ),
    )

    # Step 19: Start new IXIA packet capture for undrain phase (iBGP)
    if tcp_dump_capture_interface_ibgp:
        steps.append(
            create_ixia_packet_capture_step(
                device_name=device_name,
                interface=tcp_dump_capture_interface_ibgp,
                mode="start",
                capture_id="fauu_undrain_ibgp",
                description="Start IXIA packet capture for undrain phase (iBGP RECEIVER)",
            ),
        )

    # Step 20: Brief pause to ensure capture is ready
    steps.append(
        create_longevity_step(
            duration=5,
            description="Brief pause to ensure IXIA capture is ready (5 seconds)",
        ),
    )

    # Step 21: Undrain

    # Step 21: Undrain - Revert local preference to 100 for specified peers
    steps.append(
        create_set_bgp_prefixes_local_preference_step(
            prefix_pool_regex=prefix_pool_regex,
            local_pref_value=100,
            prefix_start_index=prefix_start_index,
            prefix_end_index=prefix_end_index,
        ),
    )

    # Step 22: Undrain - Revert origin to IGP for specified peers
    steps.append(
        create_modify_bgp_prefixes_origin_value_step(
            prefix_pool_regex=prefix_pool_regex,
            origin_value="igp",
            prefix_start_index=prefix_start_index,
            prefix_end_index=prefix_end_index,
        ),
    )

    # Step 23: Soak after undrain
    steps.append(
        create_longevity_step(
            duration=soak_time_seconds,
            description=f"Soak after undrain for {soak_time_seconds} seconds",
        ),
    )

    # Step 24: Stop IXIA packet capture for undrain phase (eBGP)
    if tcp_dump_capture_interface_ebgp:
        steps.append(
            create_ixia_packet_capture_step(
                device_name=device_name,
                interface=tcp_dump_capture_interface_ebgp,
                mode="stop",
                capture_id="fauu_undrain_ebgp",
                description="Stop IXIA packet capture for undrain phase (eBGP SOURCE)",
            ),
        )

    # Step 25: Stop IXIA packet capture for undrain phase (BGP monitor)
    steps.append(
        create_ixia_packet_capture_step(
            device_name=device_name,
            interface=tcp_dump_capture_interface_bgpmon,
            mode="stop",
            capture_id="fauu_undrain_bgpmon",
            description="Stop IXIA packet capture for undrain phase (BGP monitor)",
        ),
    )

    # Step 26: Stop IXIA packet capture for undrain phase (iBGP)
    if tcp_dump_capture_interface_ibgp:
        steps.append(
            create_ixia_packet_capture_step(
                device_name=device_name,
                interface=tcp_dump_capture_interface_ibgp,
                mode="stop",
                capture_id="fauu_undrain_ibgp",
                description="Stop IXIA packet capture for undrain phase (iBGP RECEIVER)",
            ),
        )

    # Step 27: Save IXIA packet capture for undrain phase (eBGP)
    if tcp_dump_capture_interface_ebgp:
        steps.append(
            create_ixia_packet_capture_step(
                device_name=device_name,
                interface=tcp_dump_capture_interface_ebgp,
                mode="save",
                pcap_filename="bgp_fauu_undrain_ebgp.pcap",
                capture_id="fauu_undrain_ebgp",
                description="Save IXIA packet capture for undrain phase (eBGP SOURCE)",
            ),
        )

    # Step 28: Save IXIA packet capture for undrain phase (BGP monitor)
    steps.append(
        create_ixia_packet_capture_step(
            device_name=device_name,
            interface=tcp_dump_capture_interface_bgpmon,
            mode="save",
            pcap_filename="bgp_fauu_undrain_bgpmon.pcap",
            capture_id="fauu_undrain_bgpmon",
            description="Save IXIA packet capture for undrain phase (BGP monitor)",
        ),
    )

    # Step 29: Save IXIA packet capture for undrain phase (iBGP)
    if tcp_dump_capture_interface_ibgp:
        steps.append(
            create_ixia_packet_capture_step(
                device_name=device_name,
                interface=tcp_dump_capture_interface_ibgp,
                mode="save",
                pcap_filename="bgp_fauu_undrain_ibgp.pcap",
                capture_id="fauu_undrain_ibgp",
                description="Save IXIA packet capture for undrain phase (iBGP RECEIVER)",
            ),
        )

    # Step 30: Verify undrain convergence (eBGP)
    if tcp_dump_capture_interface_ebgp:
        steps.append(
            create_drain_convergence_verification_step(
                pcap_filename="bgp_fauu_undrain_ebgp.pcap",
                max_convergence_time_seconds=300,  # 5 minutes for FAUU
                expected_as_path_asn=None,
                phase="undrain (eBGP SOURCE)",
            ),
        )

    # Step 31: Verify undrain convergence (BGP monitor)
    steps.append(
        create_drain_convergence_verification_step(
            pcap_filename="bgp_fauu_undrain_bgpmon.pcap",
            max_convergence_time_seconds=300,  # 5 minutes for FAUU
            expected_as_path_asn=65099,  # Should NOT contain 65099 after undrain
            phase="undrain (BGP monitor)",
        ),
    )

    # Step 32: Verify undrain convergence (iBGP)
    if tcp_dump_capture_interface_ibgp:
        steps.append(
            create_drain_convergence_verification_step(
                pcap_filename="bgp_fauu_undrain_ibgp.pcap",
                max_convergence_time_seconds=300,  # 5 minutes for FAUU
                expected_as_path_asn=None,
                phase="undrain (iBGP RECEIVER)",
            ),
        )

    # Step 32A: Generate consolidated undrain convergence report
    pcap_files_undrain = {"bgp_monitor": "bgp_fauu_undrain_bgpmon.pcap"}
    if tcp_dump_capture_interface_ebgp:
        pcap_files_undrain["ebgp_source"] = "bgp_fauu_undrain_ebgp.pcap"
    if tcp_dump_capture_interface_ibgp:
        pcap_files_undrain["ibgp_receiver"] = "bgp_fauu_undrain_ibgp.pcap"

    steps.append(
        create_consolidated_convergence_report_step(
            phase="undrain",
            pcap_files=pcap_files_undrain,
            description="Generate consolidated undrain convergence report",
        ),
    )

    return Stage(steps=steps)


def create_plane_drain_undrain_stage(  # noqa: C901
    device_name: str,
    prefix_pool_regex: str = ".*IBGP.*PLANE_1.*",
    prefix_start_index: int = 0,
    prefix_end_index: int | None = None,
    tcp_dump_capture_interface_bgpmon: str = "any",
    tcp_dump_capture_interface_ebgp: str | None = None,
    tcp_dump_capture_interface_ibgp: str | None = None,
    soak_time_seconds: int = 1800,
) -> list[Stage]:
    """
    Create a test stage to verify BGP plane drain/undrain behavior.

    This stage tests BGP's handling of plane-level drain/undrain operations by
    changing BGP attributes on prefixes for a specific plane. The test captures
    BGP updates during both drain and undrain phases to verify proper convergence.

    Three-interface capture strategy:
    1. iBGP Plane interface (SOURCE): Captures drain updates being SENT with modified attributes
       - This is the reference point for when drain actually starts/completes
    2. BGP Monitor interface: Captures when BGP++ receives and processes the updates
       - Measures BGP++ processing latency (source → BGP monitor)
    3. eBGP interface (FA-UU): Captures when best-path changes are advertised externally
       - Measures end-to-end convergence including path selection

    The test sequence:
    1. Start IXIA packet capture on all three interfaces for drain phase
    2. Drain: Change origin attribute to incomplete for specified prefixes
    3. Drain: Prepend AS_PATH with ASN 65099
    4. Soak for specified duration after drain
    5. Save IXIA packet captures for drain phase (all interfaces)
    6. Verify drain convergence inline (max 10 minutes)
    7. Start IXIA packet capture on all three interfaces for undrain phase
    8. Undrain: Revert origin attribute for specified prefixes
    9. Undrain: Remove AS_PATH prepend
    10. Soak for specified duration after undrain
    11. Save IXIA packet captures for undrain phase (all interfaces)
    12. Verify undrain convergence inline (max 10 minutes)

    Args:
        device_name: Name of the device under test
        prefix_pool_regex: Regex pattern to match prefix pool names (default: ".*IBGP.*PLANE_1.*")
        prefix_start_index: Starting index within the network group multiplier (default: 0)
        prefix_end_index: Ending index within the network group multiplier. If None, use all (default: None)
        tcp_dump_capture_interface_bgpmon: Interface for IXIA packet capture on BGP monitor (default: "any")
        tcp_dump_capture_interface_ebgp: Optional interface for IXIA packet capture on eBGP (FA-UU) to verify best-path changes (default: None)
        tcp_dump_capture_interface_ibgp: Optional interface for IXIA packet capture on iBGP Plane (SOURCE) to measure drain start/end reference point (default: None)
        soak_time_seconds: Soak duration after drain and undrain operations (default: 1800 / 30 minutes)

    Returns:
        List of 6 Stage objects for BGP plane drain/undrain test:
        - Stage 1: Pre-drain setup (sequential)
        - Stage 2: Drain operations (concurrent - IXIA and DUT)
        - Stage 3: Post-drain verification (sequential)
        - Stage 4: Pre-undrain setup (sequential)
        - Stage 5: Undrain operations (concurrent - IXIA and DUT)
        - Stage 6: Post-undrain verification (sequential)

    Example:
        # Drain/undrain on Plane 1 iBGP prefixes with three-interface capture
        stage = create_plane_drain_undrain_stage(
            device_name="rsw1ag.p001.f01.atn1",
            prefix_pool_regex=".*IBGP.*PLANE_1.*",
            tcp_dump_capture_interface_bgpmon=ixia_interface_mimic_bgp_mon,   # BGP monitor
            tcp_dump_capture_interface_ebgp=ixia_interface_mimic_ebgp,        # eBGP to FA-UU
            tcp_dump_capture_interface_ibgp=ixia_interface_mimic_ibgp,        # iBGP Plane (source)
        )
    """
    steps_pre_drain = []

    # Step 1: Start IXIA packet capture on BGP monitor interface for drain
    steps_pre_drain.append(
        create_ixia_packet_capture_step(
            device_name=device_name,
            interface=tcp_dump_capture_interface_bgpmon,
            mode="start",
            capture_id="plane_drain_bgpmon",
            description="Start IXIA packet capture for drain phase (BGP monitor)",
        ),
    )

    # Step 1B: Start IXIA packet capture on eBGP interface for drain (if provided)
    if tcp_dump_capture_interface_ebgp:
        steps_pre_drain.append(
            create_ixia_packet_capture_step(
                device_name=device_name,
                interface=tcp_dump_capture_interface_ebgp,
                mode="start",
                capture_id="plane_drain_ebgp",
                description="Start IXIA packet capture for drain phase (eBGP to FA-UU)",
            ),
        )

    # Step 1C: Start IXIA packet capture on iBGP Plane interface for drain (if provided)
    if tcp_dump_capture_interface_ibgp:
        steps_pre_drain.append(
            create_ixia_packet_capture_step(
                device_name=device_name,
                interface=tcp_dump_capture_interface_ibgp,
                mode="start",
                capture_id="plane_drain_ibgp_source",
                description="Start IXIA packet capture for drain phase (iBGP Plane - SOURCE)",
            ),
        )

    # Step 1A: Brief pause to ensure capture is ready
    steps_pre_drain.append(
        create_longevity_step(
            duration=5,
            description="Brief pause to ensure IXIA capture is ready (5 seconds)",
        ),
    )

    # Create Stage 1: All steps before drain
    stage_1_pre_drain = Stage(
        steps=steps_pre_drain, description="Plane Drain - Pre-drain setup"
    )

    # Step 2 & 2A: Drain - IXIA and DUT policy changes (run concurrently)
    # These will be in a separate concurrent stage
    drain_policies = {
        "EB-FA-V6": {"OUT": "EB-FA-OUT-DRAIN"},
        "EB-FA-V4": {"OUT": "EB-FA-OUT-DRAIN"},
        "EB-EB-V6": {"OUT": "EB-EB-OUT-DRAIN"},
        "EB-EB-V4": {"OUT": "EB-EB-OUT-DRAIN"},
    }

    # Create the two drain steps that will run concurrently
    ixia_drain_step = create_modify_bgp_prefixes_origin_value_step(
        prefix_pool_regex=prefix_pool_regex,
        origin_value="incomplete",
        prefix_start_index=prefix_start_index,
        prefix_end_index=prefix_end_index,
    )
    dut_drain_step = create_set_peer_groups_policy_step(
        device_name=device_name,
        peer_groups_policy=drain_policies,
        description="Apply drain policies to peer groups (EB-FA and EB-EB)",
    )

    # Create Stage 2: Drain operations (concurrent)
    stage_2_drain_concurrent = Stage(
        concurrent=True,
        concurrent_steps=[
            ConcurrentStep(steps=[ixia_drain_step]),
            ConcurrentStep(steps=[dut_drain_step]),
        ],
        description="Plane Drain - Execute IXIA and DUT drain in parallel",
    )

    # Stage 3 will contain all steps after drain (sequential)
    steps_after_drain = []

    # Step 3: Soak after drain
    steps_after_drain.append(
        create_longevity_step(
            duration=soak_time_seconds,
            description=f"Soak after drain for {soak_time_seconds} seconds",
        ),
    )

    # Step 4: Stop IXIA packet capture for drain phase (BGP monitor)
    steps_after_drain.append(
        create_ixia_packet_capture_step(
            device_name=device_name,
            interface=tcp_dump_capture_interface_bgpmon,
            mode="stop",
            capture_id="plane_drain_bgpmon",
            description="Stop IXIA packet capture for drain phase (BGP monitor)",
        ),
    )

    # Step 4B: Stop IXIA packet capture for drain phase (eBGP)
    if tcp_dump_capture_interface_ebgp:
        steps_after_drain.append(
            create_ixia_packet_capture_step(
                device_name=device_name,
                interface=tcp_dump_capture_interface_ebgp,
                mode="stop",
                capture_id="plane_drain_ebgp",
                description="Stop IXIA packet capture for drain phase (eBGP)",
            ),
        )

    # Step 4C: Stop IXIA packet capture for drain phase (iBGP Plane)
    if tcp_dump_capture_interface_ibgp:
        steps_after_drain.append(
            create_ixia_packet_capture_step(
                device_name=device_name,
                interface=tcp_dump_capture_interface_ibgp,
                mode="stop",
                capture_id="plane_drain_ibgp_source",
                description="Stop IXIA packet capture for drain phase (iBGP Plane - SOURCE)",
            ),
        )

    # Step 5: Save IXIA packet capture for drain phase (BGP monitor)
    steps_after_drain.append(
        create_ixia_packet_capture_step(
            device_name=device_name,
            interface=tcp_dump_capture_interface_bgpmon,
            mode="save",
            pcap_filename="bgp_plane_drain_bgpmon.pcap",
            capture_id="plane_drain_bgpmon",
            description="Save IXIA packet capture for drain phase (BGP monitor)",
        ),
    )

    # Step 5B: Save IXIA packet capture for drain phase (eBGP)
    if tcp_dump_capture_interface_ebgp:
        steps_after_drain.append(
            create_ixia_packet_capture_step(
                device_name=device_name,
                interface=tcp_dump_capture_interface_ebgp,
                mode="save",
                pcap_filename="bgp_plane_drain_ebgp.pcap",
                capture_id="plane_drain_ebgp",
                description="Save IXIA packet capture for drain phase (eBGP to FA-UU)",
            ),
        )

    # Step 5C: Save IXIA packet capture for drain phase (iBGP Plane - SOURCE)
    if tcp_dump_capture_interface_ibgp:
        steps_after_drain.append(
            create_ixia_packet_capture_step(
                device_name=device_name,
                interface=tcp_dump_capture_interface_ibgp,
                mode="save",
                pcap_filename="bgp_plane_drain_ibgp_source.pcap",
                capture_id="plane_drain_ibgp_source",
                description="Save IXIA packet capture for drain phase (iBGP Plane - SOURCE)",
            ),
        )

    # Step 5A: Verify drain convergence (iBGP Plane SOURCE - FIRST as reference point)
    if tcp_dump_capture_interface_ibgp:
        steps_after_drain.append(
            create_drain_convergence_verification_step(
                pcap_filename="bgp_plane_drain_ibgp_source.pcap",
                max_convergence_time_seconds=600,  # 10 minutes for Plane
                expected_as_path_asn=None,
                phase="drain (iBGP Plane SOURCE)",
            ),
        )

    # Step 5B: Verify drain convergence (BGP monitor)
    steps_after_drain.append(
        create_drain_convergence_verification_step(
            pcap_filename="bgp_plane_drain_bgpmon.pcap",
            max_convergence_time_seconds=600,  # 10 minutes for Plane
            expected_as_path_asn=None,  # No AS_PATH check since we removed prepend
            phase="drain (BGP monitor)",
        ),
    )

    # Step 5C: Verify drain convergence (eBGP to FA-UU)
    if tcp_dump_capture_interface_ebgp:
        steps_after_drain.append(
            create_drain_convergence_verification_step(
                pcap_filename="bgp_plane_drain_ebgp.pcap",
                max_convergence_time_seconds=600,  # 10 minutes for Plane
                expected_as_path_asn=None,
                phase="drain (eBGP to FA-UU)",
            ),
        )

    # Step 5D: Generate consolidated drain convergence report
    pcap_files_drain = {"bgp_monitor": "bgp_plane_drain_bgpmon.pcap"}
    if tcp_dump_capture_interface_ibgp:
        pcap_files_drain["ibgp_source"] = "bgp_plane_drain_ibgp_source.pcap"
    if tcp_dump_capture_interface_ebgp:
        pcap_files_drain["ebgp"] = "bgp_plane_drain_ebgp.pcap"

    steps_after_drain.append(
        create_consolidated_convergence_report_step(
            phase="drain",
            pcap_files=pcap_files_drain,
            description="Generate consolidated drain convergence report with latency analysis",
        ),
    )

    # Create Stage 3: Post-drain verification (sequential)
    stage_3_post_drain = Stage(
        steps=steps_after_drain,
        description="Plane Drain - Post-drain verification",
    )

    # ===== UNDRAIN SECTION =====
    # Stage 4: Pre-undrain setup (packet captures)
    steps_pre_undrain = []

    # Step 6: Start new IXIA packet capture for undrain phase (BGP monitor)
    steps_pre_undrain.append(
        create_ixia_packet_capture_step(
            device_name=device_name,
            interface=tcp_dump_capture_interface_bgpmon,
            mode="start",
            capture_id="plane_undrain_bgpmon",
            description="Start IXIA packet capture for undrain phase (BGP monitor)",
        ),
    )

    # Step 6B: Start new IXIA packet capture for undrain phase (eBGP)
    if tcp_dump_capture_interface_ebgp:
        steps_pre_undrain.append(
            create_ixia_packet_capture_step(
                device_name=device_name,
                interface=tcp_dump_capture_interface_ebgp,
                mode="start",
                capture_id="plane_undrain_ebgp",
                description="Start IXIA packet capture for undrain phase (eBGP to FA-UU)",
            ),
        )

    # Step 6C: Start new IXIA packet capture for undrain phase (iBGP Plane - SOURCE)
    if tcp_dump_capture_interface_ibgp:
        steps_pre_undrain.append(
            create_ixia_packet_capture_step(
                device_name=device_name,
                interface=tcp_dump_capture_interface_ibgp,
                mode="start",
                capture_id="plane_undrain_ibgp_source",
                description="Start IXIA packet capture for undrain phase (iBGP Plane - SOURCE)",
            ),
        )

    # Step 6A: Brief pause to ensure capture is ready
    steps_pre_undrain.append(
        create_longevity_step(
            duration=5,
            description="Brief pause to ensure IXIA capture is ready (5 seconds)",
        ),
    )

    # Create Stage 4: Pre-undrain setup
    stage_4_pre_undrain = Stage(
        steps=steps_pre_undrain,
        description="Plane Undrain - Pre-undrain setup",
    )

    # Stage 5: Undrain operations (concurrent)
    # Create the two undrain steps that will run concurrently

    # Step 7: Undrain - Revert ORIGIN to IGP on IXIA
    ixia_undrain_step = create_modify_bgp_prefixes_origin_value_step(
        prefix_pool_regex=prefix_pool_regex,
        origin_value="igp",
        prefix_start_index=prefix_start_index,
        prefix_end_index=prefix_end_index,
    )

    # Step 7A: Undrain - Revert to original policies on DUT peer groups
    # Revert ORIGIN and AS_PATH back to normal by applying original OUT policies
    undrain_policies = {
        "EB-FA-V6": {"OUT": "EB-FA-OUT"},
        "EB-FA-V4": {"OUT": "EB-FA-OUT"},
        "EB-EB-V6": {"OUT": "EB-EB-OUT"},
        "EB-EB-V4": {"OUT": "EB-EB-OUT"},
    }
    dut_undrain_step = create_set_peer_groups_policy_step(
        device_name=device_name,
        peer_groups_policy=undrain_policies,
        description="Revert to original OUT policies for peer groups (EB-FA and EB-EB)",
    )

    # Create Stage 5: Undrain operations (concurrent)
    stage_5_undrain_concurrent = Stage(
        concurrent=True,
        concurrent_steps=[
            ConcurrentStep(steps=[ixia_undrain_step]),
            ConcurrentStep(steps=[dut_undrain_step]),
        ],
        description="Plane Undrain - Execute IXIA and DUT undrain in parallel",
    )

    # Stage 6: Post-undrain verification
    steps_post_undrain = []

    # Step 8: Soak after undrain
    steps_post_undrain.append(
        create_longevity_step(
            duration=soak_time_seconds,
            description=f"Soak after undrain for {soak_time_seconds} seconds",
        ),
    )

    # Step 9: Stop IXIA packet capture for undrain phase (BGP monitor)
    steps_post_undrain.append(
        create_ixia_packet_capture_step(
            device_name=device_name,
            interface=tcp_dump_capture_interface_bgpmon,
            mode="stop",
            capture_id="plane_undrain_bgpmon",
            description="Stop IXIA packet capture for undrain phase (BGP monitor)",
        ),
    )

    # Step 9B: Stop IXIA packet capture for undrain phase (eBGP)
    if tcp_dump_capture_interface_ebgp:
        steps_post_undrain.append(
            create_ixia_packet_capture_step(
                device_name=device_name,
                interface=tcp_dump_capture_interface_ebgp,
                mode="stop",
                capture_id="plane_undrain_ebgp",
                description="Stop IXIA packet capture for undrain phase (eBGP)",
            ),
        )

    # Step 9C: Stop IXIA packet capture for undrain phase (iBGP Plane - SOURCE)
    if tcp_dump_capture_interface_ibgp:
        steps_post_undrain.append(
            create_ixia_packet_capture_step(
                device_name=device_name,
                interface=tcp_dump_capture_interface_ibgp,
                mode="stop",
                capture_id="plane_undrain_ibgp_source",
                description="Stop IXIA packet capture for undrain phase (iBGP Plane - SOURCE)",
            ),
        )

    # Step 10: Save IXIA packet capture for undrain phase (BGP monitor)
    steps_post_undrain.append(
        create_ixia_packet_capture_step(
            device_name=device_name,
            interface=tcp_dump_capture_interface_bgpmon,
            mode="save",
            pcap_filename="bgp_plane_undrain_bgpmon.pcap",
            capture_id="plane_undrain_bgpmon",
            description="Save IXIA packet capture for undrain phase (BGP monitor)",
        ),
    )

    # Step 10B: Save IXIA packet capture for undrain phase (eBGP)
    if tcp_dump_capture_interface_ebgp:
        steps_post_undrain.append(
            create_ixia_packet_capture_step(
                device_name=device_name,
                interface=tcp_dump_capture_interface_ebgp,
                mode="save",
                pcap_filename="bgp_plane_undrain_ebgp.pcap",
                capture_id="plane_undrain_ebgp",
                description="Save IXIA packet capture for undrain phase (eBGP to FA-UU)",
            ),
        )

    # Step 10C: Save IXIA packet capture for undrain phase (iBGP Plane - SOURCE)
    if tcp_dump_capture_interface_ibgp:
        steps_post_undrain.append(
            create_ixia_packet_capture_step(
                device_name=device_name,
                interface=tcp_dump_capture_interface_ibgp,
                mode="save",
                pcap_filename="bgp_plane_undrain_ibgp_source.pcap",
                capture_id="plane_undrain_ibgp_source",
                description="Save IXIA packet capture for undrain phase (iBGP Plane - SOURCE)",
            ),
        )

    # Step 10A: Verify undrain convergence (iBGP Plane SOURCE - FIRST as reference point)
    if tcp_dump_capture_interface_ibgp:
        steps_post_undrain.append(
            create_drain_convergence_verification_step(
                pcap_filename="bgp_plane_undrain_ibgp_source.pcap",
                max_convergence_time_seconds=600,  # 10 minutes for Plane
                expected_as_path_asn=None,
                phase="undrain (iBGP Plane SOURCE)",
            ),
        )

    # Step 10B: Verify undrain convergence (BGP monitor)
    steps_post_undrain.append(
        create_drain_convergence_verification_step(
            pcap_filename="bgp_plane_undrain_bgpmon.pcap",
            max_convergence_time_seconds=600,  # 10 minutes for Plane
            expected_as_path_asn=65099,  # Should NOT contain 65099 after undrain
            phase="undrain (BGP monitor)",
        ),
    )

    # Step 10C: Verify undrain convergence (eBGP to FA-UU)
    if tcp_dump_capture_interface_ebgp:
        steps_post_undrain.append(
            create_drain_convergence_verification_step(
                pcap_filename="bgp_plane_undrain_ebgp.pcap",
                max_convergence_time_seconds=600,  # 10 minutes for Plane
                expected_as_path_asn=None,
                phase="undrain (eBGP to FA-UU)",
            ),
        )

    # Step 10D: Generate consolidated undrain convergence report
    pcap_files_undrain = {"bgp_monitor": "bgp_plane_undrain_bgpmon.pcap"}
    if tcp_dump_capture_interface_ibgp:
        pcap_files_undrain["ibgp_source"] = "bgp_plane_undrain_ibgp_source.pcap"
    if tcp_dump_capture_interface_ebgp:
        pcap_files_undrain["ebgp"] = "bgp_plane_undrain_ebgp.pcap"

    steps_post_undrain.append(
        create_consolidated_convergence_report_step(
            phase="undrain",
            pcap_files=pcap_files_undrain,
            description="Generate consolidated undrain convergence report with latency analysis",
        ),
    )

    # Create Stage 6: Post-undrain verification (sequential)
    stage_6_post_undrain = Stage(
        steps=steps_post_undrain,
        description="Plane Undrain - Post-undrain verification",
    )

    # Return all six stages
    return [
        stage_1_pre_drain,
        stage_2_drain_concurrent,
        stage_3_post_drain,
        stage_4_pre_undrain,
        stage_5_undrain_concurrent,
        stage_6_post_undrain,
    ]


def create_multipath_group_oscillation_stage(
    ipv4_peer_regex: str = ".*IPV4_EBGP$",
    ipv6_peer_regex: str = ".*IPV6_EBGP$",
    ipv4_session_count: int = 100,
    ipv6_session_count: int = 100,  # noqa: F841 - IPv6 multipath validation TBD
    test_duration_seconds: int = 1800,
    oscillation_interval_seconds: int = 60,
    min_peers_to_stop: int = 1,
    max_peers_to_stop: int = 11,
    prefix_subnets: list[str] | None = None,
) -> Stage:
    """
    Create a test stage to verify BGP stability during multipath group oscillations.

    Test Case: 5.2.4 BGP Instability: Multipath group oscillations

    Purpose:
        Verify the stability of a BGP++ powered EB device in case of anycast route
        multipath oscillations. This test fluctuates BGP multipath groups for eBGP
        routes by stopping and starting BGP sessions from varying numbers of
        emulated FA-UU peers.

    Pre-Conditions (verified by playbook prechecks):
        - All BGP sessions between DUT and traffic generators are Established and not flapping
        - CPU and memory utilization are stable and within baseline levels
        - CPU load-average is stable and within baseline levels
        - IAR is enabled

    Test Steps:
        1. Discover baseline: Query BGP RIB to find all prefixes with full multipath group
        2. For one hour, every minute fluctuate BGP multipath group for eBGP routes:
           a. Stop N (where N varies from 1 to max_peers_to_stop) of the eBGP sessions
              to reduce the multipath group
           b. Verify multipath group for discovered prefixes is reduced proportionally
           c. Restart the stopped sessions to restore the multipath group
           d. Verify multipath group for discovered prefixes is restored

    Args:
        ipv4_peer_regex: Regex pattern to match IPv4 eBGP peers (default: ".*IPV4_EBGP$")
        ipv6_peer_regex: Regex pattern to match IPv6 eBGP peers (default: ".*IPV6_EBGP$")
        ipv4_session_count: Total number of IPv4 eBGP sessions (default: 100)
        ipv6_session_count: Total number of IPv6 eBGP sessions (default: 100)
        test_duration_seconds: Total test duration in seconds (default: 3600 / 1 hour)
        oscillation_interval_seconds: Interval between oscillations (default: 60 / 1 minute)
        min_peers_to_stop: Minimum number of peers to stop per cycle (default: 1)
        max_peers_to_stop: Maximum number of peers to stop per cycle (default: 11)
        prefix_subnets: Optional list of prefix subnets to check for multipath groups.
                        If None, baseline discovery will find prefixes automatically.
                        Example: ["10.200.0.0/16", "2001:db8:200::/48"]

    Returns:
        Stage object for BGP multipath group oscillation test

    Example:
        stage = create_multipath_group_oscillation_stage(
            ipv4_peer_regex=".*IPV4_EBGP$",
            ipv6_peer_regex=".*IPV6_EBGP$",
            ipv4_session_count=12,
            ipv6_session_count=12,
            test_duration_seconds=3600,
            oscillation_interval_seconds=60,
        )
    """
    steps = []

    # Step 0: Baseline discovery - find prefixes with full multipath group
    # This queries the BGP RIB and discovers all prefixes that currently have
    # ipv4_session_count next-hops (full multipath group). These prefixes
    # are stored and used for validation throughout the oscillation test.
    steps.append(
        create_multipath_nexthop_count_health_check_step(
            prefix_subnets=prefix_subnets,
            discover_baseline=True,
            baseline_nexthop_count=ipv4_session_count,
            description=f"Baseline: Discover prefixes with full {ipv4_session_count}-way multipath group",
        )
    )

    num_cycles = test_duration_seconds // oscillation_interval_seconds

    for cycle in range(num_cycles):
        cycle_num = cycle + 1

        # Calculate how many peers to stop this cycle
        # Vary N from min to max in a cycling pattern
        n_peers_to_stop = (cycle % max_peers_to_stop) + min_peers_to_stop
        if n_peers_to_stop > max_peers_to_stop:
            n_peers_to_stop = max_peers_to_stop

        # Step 1: Stop N IPv4 eBGP sessions (reduce multipath group)
        steps.append(
            create_start_stop_bgp_peers_step(
                peer_regex=ipv4_peer_regex,
                start=False,
                start_idx=1,
                end_idx=n_peers_to_stop,
                description=f"Cycle {cycle_num}/{num_cycles}: Stop IPv4 eBGP sessions 1-{n_peers_to_stop} (reduce multipath group)",
            )
        )

        # Step 2: Stop N IPv6 eBGP sessions (reduce multipath group)
        steps.append(
            create_start_stop_bgp_peers_step(
                peer_regex=ipv6_peer_regex,
                start=False,
                start_idx=1,
                end_idx=n_peers_to_stop,
                description=f"Cycle {cycle_num}/{num_cycles}: Stop IPv6 eBGP sessions 1-{n_peers_to_stop} (reduce multipath group)",
            )
        )

        # Step 3: Wait for half the oscillation interval for routes to converge
        convergence_wait = oscillation_interval_seconds // 2
        steps.append(
            create_longevity_step(
                duration=convergence_wait,
                description=f"Cycle {cycle_num}/{num_cycles}: Wait {convergence_wait}s for multipath group reduction to converge",
            )
        )

        # Step 3a: Health check

        # Step 3a: Health check to verify multipath group reduced after stopping sessions
        # Uses discovered baseline prefixes for validation
        expected_after_stop = ipv4_session_count - n_peers_to_stop
        steps.append(
            create_multipath_nexthop_count_health_check_step(
                use_discovered_prefixes=True,
                expected_nexthop_count=expected_after_stop,
                description=f"Cycle {cycle_num}/{num_cycles}: Verify multipath group reduced to {expected_after_stop} next-hops",
            )
        )

        # Step 4: Restart N IPv4 eBGP sessions (restore multipath group)
        steps.append(
            create_start_stop_bgp_peers_step(
                peer_regex=ipv4_peer_regex,
                start=True,
                start_idx=1,
                end_idx=n_peers_to_stop,
                description=f"Cycle {cycle_num}/{num_cycles}: Start IPv4 eBGP sessions 1-{n_peers_to_stop} (restore multipath group)",
            )
        )

        # Step 5: Restart N IPv6 eBGP sessions (restore multipath group)
        steps.append(
            create_start_stop_bgp_peers_step(
                peer_regex=ipv6_peer_regex,
                start=True,
                start_idx=1,
                end_idx=n_peers_to_stop,
                description=f"Cycle {cycle_num}/{num_cycles}: Start IPv6 eBGP sessions 1-{n_peers_to_stop} (restore multipath group)",
            )
        )

        # Step 6: Wait for remaining interval for routes to re-converge
        remaining_wait = oscillation_interval_seconds - convergence_wait
        steps.append(
            create_longevity_step(
                duration=remaining_wait,
                description=f"Cycle {cycle_num}/{num_cycles}: Wait {remaining_wait}s for multipath group restoration to converge",
            )
        )

        # Step 6a: Health check

        # Step 6a: Health check to verify multipath group restored after restarting sessions
        # Uses discovered baseline prefixes for validation
        steps.append(
            create_multipath_nexthop_count_health_check_step(
                use_discovered_prefixes=True,
                expected_nexthop_count=ipv4_session_count,
                description=f"Cycle {cycle_num}/{num_cycles}: Verify multipath group restored to {ipv4_session_count} next-hops",
            )
        )

    return Stage(steps=steps)


def create_route_registry_runtime_update_stage(
    device_name: str,
    ebgp_peer_description: str = "EBGP",
    prefix_pool_regex: str = ".*EBGP.*",
    prefix_start_index: int = 0,
    prefix_end_index: int = 100,
    soak_time_seconds: int = 600,
    baseline_route_count: int = 650,
) -> Stage:
    """
    Create a test stage to verify route registry runtime update behavior for prefix-lists.

    This stage tests BGP's handling of prefix-list runtime updates without restarting BGP++ by:
    1. Starting to advertise 100 additional prefixes (per-AFI) from FAUU to DUT
    2. Verifying these prefixes are denied by prefix-list on EB-FA peer-groups
    3. Add these 100 prefixes to prefix-list using setRouteFilterPolicy
    4. Soak for stability verification
    5. Verify route count increased to baseline + added prefixes (e.g., 750)
    6. Remove the 100 prefixes from prefix-list using setRouteFilterPolicy
    7. Soak for stability verification
    8. Verify route count returned to baseline (e.g., 650)

    Args:
        device_name: Name of the device under test
        ebgp_peer_description: Description substring to match EBGP peers (default: "EBGP")
        prefix_pool_regex: Regex pattern to match prefix pool names (default: ".*EBGP.*")
        prefix_start_index: Starting index for the additional prefixes (default: 0)
        prefix_end_index: Ending index for the additional prefixes (default: 100)
        soak_time_seconds: Soak duration for BGP stability verification (default: 600 / 10 minutes)
        baseline_route_count: Expected baseline route count (default: 650)

    Returns:
        Stage object for route registry runtime update test
    """
    steps = []

    # Step 1: Start advertising additional prefixes (per-AFI) from FAUU to DUT
    # These prefixes should be denied by prefix-list configured on EB-FA peer-groups
    steps.append(
        create_advertise_withdraw_prefixes_step(
            device_name=device_name,
            advertise=True,
            prefix_pool_regex=prefix_pool_regex,
            prefix_start_index=prefix_start_index,
            prefix_end_index=prefix_end_index,
            description=f"Start advertising {prefix_end_index - prefix_start_index} prefixes (per-AFI) from FAUU to DUT",
        ),
    )

    # Step 2: Verify these prefixes are denied by prefix-list on EB-FA peer-groups
    # Check that the route count hasn't increased (should still be at baseline)
    steps.append(
        create_verify_received_routes_step(
            device_name=device_name,
            descriptions_to_check=[ebgp_peer_description],
            max_count=baseline_route_count,
            description=f"Verify {prefix_end_index - prefix_start_index} additional prefixes are denied by prefix-list on {ebgp_peer_description} peers",
        ),
    )

    # Step 3: Add these prefixes to prefix-list using setRouteFilterPolicy
    steps.append(
        create_set_route_filter_step(
            device_name=device_name,
            config_path="taac/test_bgp_policies/ebb_route_registry_prefix_list_750.json",
            description=f"Add {prefix_end_index - prefix_start_index} prefixes to prefix-list using setRouteFilterPolicy (750 config)",
        ),
    )

    # Step 4: Soak for stability verification
    steps.append(
        create_longevity_step(
            duration=soak_time_seconds,
            description=f"Soak for {soak_time_seconds} seconds with all BGP sessions in Established state",
        ),
    )

    # Step 5: Verify route count increased to baseline + added prefixes
    steps.append(
        create_verify_received_routes_step(
            device_name=device_name,
            descriptions_to_check=[ebgp_peer_description],
            expected_count=baseline_route_count
            + (prefix_end_index - prefix_start_index),
            description=f"Verify {prefix_end_index - prefix_start_index} prefixes were accepted after adding to prefix-list on {ebgp_peer_description} peers",
        ),
    )

    # Step 6: Remove the prefixes from prefix-list using setRouteFilterPolicy
    steps.append(
        create_set_route_filter_step(
            device_name=device_name,
            config_path="taac/test_bgp_policies/ebb_route_registry_prefix_list_650.json",
            description=f"Remove {prefix_end_index - prefix_start_index} prefixes from prefix-list using setRouteFilterPolicy (650 config)",
        ),
    )

    # Step 7: Soak for stability verification
    steps.append(
        create_longevity_step(
            duration=soak_time_seconds,
            description=f"Final soak for {soak_time_seconds} seconds with all BGP sessions in Established state",
        ),
    )

    # Step 8: Verify route count returned to baseline
    steps.append(
        create_verify_received_routes_step(
            device_name=device_name,
            descriptions_to_check=[ebgp_peer_description],
            expected_count=baseline_route_count,
            description=f"Verify {prefix_end_index - prefix_start_index} prefixes were denied after removing from prefix-list on {ebgp_peer_description} peers",
        ),
    )

    # Step 9: Verify all BGP sessions are still established
    # This catches any actual session flaps that occurred during the test,
    # independent of the snapshot uptime check (which is skipped due to
    # BGP daemon restart during setup resetting all session uptimes).
    steps.append(
        create_validation_step(
            point_in_time_checks=[create_bgp_session_establish_check()],
            stage=taac_types.ValidationStage.POST_TEST,
            description="Post-stage: Verify all BGP sessions are still Established (catch actual flaps)",
        ),
    )

    return Stage(steps=steps)


def create_service_restart_trigger_stage(
    service: taac_types.Service,
    trigger: taac_types.ServiceInterruptionTrigger = taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
    convergence_services: list[taac_types.Service] | None = None,
    timeout: int = 600,
    longevity_duration: int | None = None,
    iteration: int = 1,
    create_cold_boot_file: bool = False,
    stage_id: str | None = None,
) -> Stage:
    """
    Create a unified service restart stage: interrupt + convergence + optional longevity.

    Covers warmboot, coldboot, BGP restart, service crash, and any other
    service restart pattern by parameterizing the service, trigger, and
    convergence services.

    Args:
        service: Service to restart (e.g., Service.AGENT, Service.BGP)
        trigger: How to interrupt the service (SYSTEMCTL_RESTART, CRASH, etc.)
        convergence_services: Services to wait for convergence (default: [AGENT])
        timeout: Convergence timeout in seconds
        longevity_duration: If set, append a longevity step with this duration
        iteration: Number of times to repeat the stage
        create_cold_boot_file: If True, create cold boot file (for agent coldboot)
        stage_id: Optional stage identifier

    Returns:
        Stage with service restart steps
    """
    if convergence_services is None:
        convergence_services = [taac_types.Service.AGENT]
    steps = [
        create_service_interruption_step(
            service=service,
            trigger=trigger,
            create_cold_boot_file=create_cold_boot_file,
        ),
        create_service_convergence_step(services=convergence_services, timeout=timeout),
    ]
    if longevity_duration is not None:
        steps.append(create_longevity_step(duration=longevity_duration))
    return Stage(id=stage_id, steps=steps, iteration=iteration)


def create_warmboot_trigger_stage(
    services: list[taac_types.Service] | None = None,
    timeout: int = 600,
    longevity_duration: int | None = None,
    iteration: int = 1,
    stage_id: str | None = None,
) -> Stage:
    """Convenience wrapper for agent warmboot. See create_service_restart_trigger_stage."""
    return create_service_restart_trigger_stage(
        service=taac_types.Service.AGENT,
        convergence_services=services,
        timeout=timeout,
        longevity_duration=longevity_duration,
        iteration=iteration,
        stage_id=stage_id,
    )


def create_coldboot_trigger_stage(
    services: list[taac_types.Service] | None = None,
    timeout: int = 900,
    longevity_duration: int | None = None,
    iteration: int = 1,
    stage_id: str | None = None,
) -> Stage:
    """Convenience wrapper for agent coldboot. See create_service_restart_trigger_stage."""
    return create_service_restart_trigger_stage(
        service=taac_types.Service.AGENT,
        convergence_services=services,
        timeout=timeout,
        longevity_duration=longevity_duration,
        iteration=iteration,
        create_cold_boot_file=True,
        stage_id=stage_id,
    )


def create_bgp_restart_trigger_stage(
    services: list[taac_types.Service] | None = None,
    timeout: int = 600,
    longevity_duration: int | None = None,
    iteration: int = 1,
    stage_id: str | None = None,
) -> Stage:
    """Convenience wrapper for BGP restart. See create_service_restart_trigger_stage."""
    if services is None:
        services = [taac_types.Service.AGENT, taac_types.Service.BGP]
    return create_service_restart_trigger_stage(
        service=taac_types.Service.BGP,
        convergence_services=services,
        timeout=timeout,
        longevity_duration=longevity_duration,
        iteration=iteration,
        stage_id=stage_id,
    )


def create_service_crash_stage(
    service: taac_types.Service,
    convergence_services: list[taac_types.Service] | None = None,
    longevity_duration: int = 180,
    stage_id: str | None = None,
) -> Stage:
    """Convenience wrapper for service crash. See create_service_restart_trigger_stage."""
    return create_service_restart_trigger_stage(
        service=service,
        trigger=taac_types.ServiceInterruptionTrigger.CRASH,
        convergence_services=convergence_services,
        longevity_duration=longevity_duration,
        stage_id=stage_id,
    )


def create_device_reboot_stage(
    trigger: taac_types.SystemRebootTrigger = taac_types.SystemRebootTrigger.FULL_SYSTEM_REBOOT,
    convergence_services: list[taac_types.Service] | None = None,
    timeout: int = 600,
    longevity_duration: int = 300,
    stage_id: str | None = None,
) -> Stage:
    """
    Create a device reboot stage: system reboot + convergence + longevity.

    Args:
        trigger: Reboot trigger type
        convergence_services: Services to wait for convergence (default: [AGENT])
        timeout: Convergence timeout in seconds
        longevity_duration: Duration in seconds for post-reboot longevity soak
        stage_id: Optional stage identifier

    Returns:
        Stage with device reboot steps
    """
    if convergence_services is None:
        convergence_services = [taac_types.Service.AGENT]
    return Stage(
        id=stage_id,
        steps=[
            create_system_reboot_step(trigger=trigger),
            create_service_convergence_step(
                services=convergence_services,
                timeout=timeout,
            ),
            create_longevity_step(duration=longevity_duration),
        ],
    )


def create_speed_flip_stage(
    speed_flip_ports: list[str],
    original_speed: int,
    new_speed: int,
    apply_patcher_method: Any,
) -> Stage:
    """
    Create a stage for speed flip testing.

    This stage verifies original speed, flips to new speed, verifies,
    then flips back to original speed.

    Args:
        speed_flip_ports: List of ports to test
        original_speed: Original speed in Gbps
        new_speed: New speed to flip to in Gbps
        apply_patcher_method: Patcher method to use

    Returns:
        Stage object for speed flip testing
    """
    return Stage(
        steps=[
            create_verify_port_operational_state_step(
                interfaces=speed_flip_ports, operational_state=True
            ),
            create_verify_port_speed_step_v2(
                ports=speed_flip_ports,
                speed_to_verify=original_speed,
            ),
            create_register_speed_flip_patcher_step_v2(
                ports=speed_flip_ports,
                apply_patcher_method=apply_patcher_method,
                register_patcher=True,
                speed_in_gbps=new_speed,
            ),
            create_verify_port_operational_state_step(
                interfaces=speed_flip_ports, operational_state=True
            ),
            create_verify_port_speed_step_v2(
                ports=speed_flip_ports,
                speed_to_verify=new_speed,
            ),
            create_register_speed_flip_patcher_step_v2(
                ports=speed_flip_ports,
                apply_patcher_method=apply_patcher_method,
                register_patcher=False,
            ),
            create_verify_port_operational_state_step(
                interfaces=speed_flip_ports, operational_state=True
            ),
            create_verify_port_speed_step_v2(
                ports=speed_flip_ports,
                speed_to_verify=original_speed,
            ),
        ]
    )


def create_steps_stage(
    steps: list[Step] | None = None,
    iteration: int = 1,
    concurrent: bool | None = None,
    concurrent_steps: list[ConcurrentStep] | None = None,
    description: str | None = None,
    stage_id: str | None = None,
) -> Stage:
    """
    Generic Stage factory wrapping a caller-supplied list of pre-built Steps.

    Used when steps are produced externally (constants, registry-derived,
    runtime-built). Provides a single canonical construction site that
    satisfies the no-inline-Stage-construction gate.

    Either `steps` (sequential) or `concurrent_steps` (a list of
    ConcurrentStep objects) must be provided, but not both.
    """
    if steps is None and concurrent_steps is None:
        raise ValueError(
            "create_steps_stage requires either `steps` or `concurrent_steps` to be provided"
        )
    if steps is not None and concurrent_steps is not None:
        raise ValueError(
            "create_steps_stage requires exactly one of `steps` or `concurrent_steps`, not both"
        )
    kwargs: dict[str, Any] = {
        "id": stage_id,
        "iteration": iteration,
    }
    if steps is not None:
        kwargs["steps"] = steps
    if concurrent_steps is not None:
        kwargs["concurrent_steps"] = concurrent_steps
    if concurrent is not None:
        kwargs["concurrent"] = concurrent
    if description is not None:
        kwargs["description"] = description
    return Stage(**kwargs)


def create_longevity_stage(
    duration: int = 60,
    stage_id: str | None = None,
) -> Stage:
    """
    Create a stage with a single longevity step.

    Args:
        duration: Duration in seconds to wait
        stage_id: Optional stage identifier

    Returns:
        Stage with a longevity step
    """
    return Stage(
        id=stage_id,
        steps=[create_longevity_step(duration=duration)],
    )


def create_periodic_service_restart_stage(
    service: Service,
    service_label: str,
    period_s: int = 300,
    iteration_index: int = 0,
    total_iterations: int = 1,
    trigger: ServiceInterruptionTrigger = ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
) -> Stage:
    """Single iteration of a periodic service-restart cycle.

    Each call produces ONE Stage = [service-interruption step, longevity
    step]. The longevity step sleeps `period_s` AFTER the restart so the
    next iteration fires `period_s` later. Use by repeating across N
    iterations to build a periodic restart pattern (e.g. THFT_002..005:
    48 iterations × 300s = 4hr of one restart every 5 min).

    Args:
        service: `taac_types.Service` enum value (e.g. `Service.AGENT`,
            `Service.BGP`, `Service.QSFP_SERVICE`, `Service.FSDB`).
        service_label: Human-readable name used in the stage id + step
            description (e.g. "wedge_agent"). Must be unique per service.
        period_s: Seconds to sleep after the restart before this stage
            ends. Default 300 (5 min). The next restart fires when the
            next stage starts.
        iteration_index: 0-based index of this iteration. Used to make
            stage id unique across a multi-iteration sequence.
        total_iterations: Total iterations in the parent sequence. Used
            in the stage id for human-readable progress.
        trigger: How to interrupt the service. Default
            `SYSTEMCTL_RESTART` (graceful systemctl restart).
    """
    return Stage(
        id=(
            f"restart_{service_label}_iter_{iteration_index + 1}_of_{total_iterations}"
        ),
        steps=[
            create_service_interruption_step(
                service=service,
                trigger=trigger,
                description=(
                    f"systemctl restart {service_label} "
                    f"(iter {iteration_index + 1}/{total_iterations})"
                ),
            ),
            create_longevity_step(duration=period_s),
        ],
    )


def create_port_channel_concurrent_flap_stage(
    interfaces_to_flap: list[str],
    iteration: int = 5,
    cold_boot: bool = False,
) -> Stage:
    """
    Create a concurrent stage for port channel link flapping with agent restart.

    This stage runs interface flapping and agent restart concurrently.

    Args:
        interfaces_to_flap: List of interfaces to flap
        iteration: Number of iterations to run
        cold_boot: If True, perform cold boot instead of warm boot

    Returns:
        Stage object for concurrent port channel flapping
    """
    flap_hold_duration = 50 if cold_boot else 15
    return Stage(
        iteration=iteration,
        concurrent=True,
        concurrent_steps=[
            ConcurrentStep(
                steps=[
                    create_interface_flap_step(
                        enable=False,
                        interfaces=interfaces_to_flap,
                        interface_flap_method=taac_types.InterfaceFlapMethod.THRIFT_PORT_STATE_CHANGE,
                    ),
                    create_longevity_step(duration=flap_hold_duration),
                    create_interface_flap_step(
                        enable=True,
                        interfaces=interfaces_to_flap,
                        interface_flap_method=taac_types.InterfaceFlapMethod.THRIFT_PORT_STATE_CHANGE,
                    ),
                ]
            ),
            ConcurrentStep(
                steps=[
                    create_service_interruption_step(
                        service=taac_types.Service.AGENT,
                        trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                        create_cold_boot_file=cold_boot,
                    ),
                    create_service_convergence_step(),
                ],
            ),
        ],
    )


def create_port_channel_flap_only_stage(
    interfaces_to_flap: list[str],
    iteration: int = 1,
) -> Stage:
    """
    Create a stage for port channel link flapping without agent restart.

    Args:
        interfaces_to_flap: List of interfaces to flap
        iteration: Number of iterations to run

    Returns:
        Stage object for port channel flapping only
    """
    return Stage(
        iteration=iteration,
        steps=[
            create_interface_flap_step(
                enable=False,
                interfaces=interfaces_to_flap,
                interface_flap_method=taac_types.InterfaceFlapMethod.THRIFT_PORT_STATE_CHANGE,
            ),
            create_longevity_step(duration=15),
            create_interface_flap_step(
                enable=True,
                interfaces=interfaces_to_flap,
                interface_flap_method=taac_types.InterfaceFlapMethod.THRIFT_PORT_STATE_CHANGE,
            ),
        ],
    )


def create_port_channel_cross_flap_stage(
    dut_flap_interfaces: list[str],
    remote_flap_interfaces: list[str],
    dut_name: str,
    remote_name: str,
    iterations: int = 1,
) -> Stage:
    """
    Create a stage for port channel cross link flapping on both sides.

    Args:
        dut_flap_interfaces: List of interfaces to flap on DUT
        remote_flap_interfaces: List of interfaces to flap on remote device
        dut_name: Name of the DUT device
        remote_name: Name of the remote device
    """
    return Stage(
        iteration=iterations,
        steps=[
            create_interface_flap_step(
                enable=False,
                interfaces=dut_flap_interfaces,
                device_name=dut_name,
                interface_flap_method=taac_types.InterfaceFlapMethod.THRIFT_PORT_STATE_CHANGE,
            ),
            create_interface_flap_step(
                enable=False,
                interfaces=remote_flap_interfaces,
                device_name=remote_name,
                interface_flap_method=taac_types.InterfaceFlapMethod.THRIFT_PORT_STATE_CHANGE,
            ),
            create_longevity_step(duration=20),
            create_interface_flap_step(
                enable=True,
                interfaces=dut_flap_interfaces,
                device_name=dut_name,
                interface_flap_method=taac_types.InterfaceFlapMethod.THRIFT_PORT_STATE_CHANGE,
            ),
            create_interface_flap_step(
                enable=True,
                interfaces=remote_flap_interfaces,
                device_name=remote_name,
                interface_flap_method=taac_types.InterfaceFlapMethod.THRIFT_PORT_STATE_CHANGE,
            ),
        ],
    )


def create_port_channel_concurrent_cross_flap_stage(
    dut_flap_interfaces: list[str],
    remote_flap_interfaces: list[str],
    dut_name: str,
    remote_name: str,
    iterations: int = 1,
    cold_boot: bool = False,
) -> Stage:
    """
    Create a stage for port channel concurrent cross link flapping on both sides with agent restart/agent coldboot.

    Args:
        dut_flap_interfaces: List of interfaces to flap on DUT
        remote_flap_interfaces: List of interfaces to flap on remote device
        dut_name: Name of the DUT device
        remote_name: Name of the remote device
        iterations: Number of iterations to run
        cold_boot: If True, perform cold boot instead of warm boot
    """
    return Stage(
        iteration=iterations,
        concurrent=True,
        concurrent_steps=[
            ConcurrentStep(
                steps=[
                    create_interface_flap_step(
                        enable=False,
                        interfaces=dut_flap_interfaces,
                        device_name=dut_name,
                        interface_flap_method=taac_types.InterfaceFlapMethod.THRIFT_PORT_STATE_CHANGE,
                    ),
                    create_interface_flap_step(
                        enable=False,
                        interfaces=remote_flap_interfaces,
                        device_name=remote_name,
                        interface_flap_method=taac_types.InterfaceFlapMethod.THRIFT_PORT_STATE_CHANGE,
                    ),
                    create_longevity_step(duration=20),
                    create_interface_flap_step(
                        enable=True,
                        interfaces=dut_flap_interfaces,
                        device_name=dut_name,
                        interface_flap_method=taac_types.InterfaceFlapMethod.THRIFT_PORT_STATE_CHANGE,
                    ),
                    create_interface_flap_step(
                        enable=True,
                        interfaces=remote_flap_interfaces,
                        device_name=remote_name,
                        interface_flap_method=taac_types.InterfaceFlapMethod.THRIFT_PORT_STATE_CHANGE,
                    ),
                ]
            ),
            ConcurrentStep(
                steps=[
                    create_service_interruption_step(
                        service=taac_types.Service.AGENT,
                        trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                        create_cold_boot_file=cold_boot,
                    ),
                    create_service_convergence_step(),
                ],
            ),
        ],
    )


def create_port_channel_permanent_teardown_stage(
    portchannel_health_check: PointInTimeHealthCheck,
    interfaces_to_enable: list[str],
) -> Stage:
    """
    Create the teardown stage for port channel testing.

    This stage verifies the expected port operational state, enables all interfaces,
    then verifies the port channel is up.

    Args:
        port_channel_name: Name of the port channel to verify
        interfaces_to_enable: List of interfaces to enable

    Returns:
        Stage object for port channel teardown
    """
    return Stage(
        steps=[
            create_verify_port_operational_state_step(
                interfaces=interfaces_to_enable,
                operational_state=False,
            ),
            create_interface_permanent_flap_step(
                register_patcher=False, enable=True, interfaces=interfaces_to_enable
            ),
            create_service_interruption_step(
                service=taac_types.Service.AGENT,
                trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
            ),
            create_service_convergence_step(),
            create_longevity_step(duration=30),
            create_verify_port_operational_state_step(
                interfaces=interfaces_to_enable,
                operational_state=True,
            ),
            create_validation_step(
                point_in_time_checks=[portchannel_health_check],
                description="Validate port channel health",
            ),
        ]
    )


def create_port_channel_teardown_stage(
    portchannel_health_check: PointInTimeHealthCheck,
    interfaces_to_enable: list[str],
) -> Stage:
    """
    Create the teardown stage for port channel testing.

    This stage verifies the expected port operational state, enables all interfaces,
    then verifies the port channel is up.

    Args:
        port_channel_name: Name of the port channel to verify
        interfaces_to_enable: List of interfaces to enable
        expected_port_operational_state: Expected operational state before enabling interfaces

    Returns:
        Stage object for port channel teardown
    """
    return Stage(
        steps=[
            create_verify_port_operational_state_step(
                interfaces=interfaces_to_enable,
                operational_state=False,
            ),
            create_interface_flap_step(
                enable=True,
                interfaces=interfaces_to_enable,
                interface_flap_method=taac_types.InterfaceFlapMethod.THRIFT_PORT_STATE_CHANGE,
            ),
            create_verify_port_operational_state_step(
                interfaces=interfaces_to_enable,
                operational_state=True,
            ),
            create_validation_step(
                point_in_time_checks=[portchannel_health_check],
                description="Validate port channel health",
            ),
        ]
    )


def create_port_channel_all_link_flaps_stage(
    port_channel_name: str,
    port_channel_member_ports: list[str],
) -> Stage:
    """
    Create a concurrent stage for flapping all port channel links with agent restart.

    Args:
        port_channel_name: Name of the port channel
        port_channel_member_ports: List of all member ports

    Returns:
        Stage object for all link flaps
    """
    return Stage(
        iteration=1,
        concurrent=True,
        concurrent_steps=[
            ConcurrentStep(
                steps=[
                    create_interface_flap_step(
                        enable=False, interfaces=port_channel_member_ports
                    ),
                    create_verify_port_operational_state_step(
                        interfaces=[port_channel_name],
                        operational_state=False,
                    ),
                    create_interface_flap_step(
                        enable=True, interfaces=port_channel_member_ports
                    ),
                    create_verify_port_operational_state_step(
                        interfaces=[port_channel_name],
                        operational_state=True,
                    ),
                ]
            ),
            ConcurrentStep(
                steps=[
                    create_service_interruption_step(
                        service=taac_types.Service.AGENT,
                        trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                    ),
                    create_service_convergence_step(),
                ],
            ),
        ],
    )


def create_register_port_channel_patcher_stage(
    port_channel_name: str,
    min_link_percentage: float | None = None,
    register_patchers: bool = True,
) -> Stage:
    """
    Create a stage to register or unregister port channel min link percentage patcher.

    Args:
        port_channel_name: Name of the port channel
        min_link_percentage: Min link percentage (required when registering)
        register_patchers: True to register, False to unregister

    Returns:
        Stage object for patcher registration/unregistration
    """
    return Stage(
        steps=[
            create_register_port_channel_min_link_percentage_patcher_step(
                port_channel_name=port_channel_name,
                min_link_percentage=min_link_percentage,
                register_patchers=register_patchers,
            ),
            create_verify_port_operational_state_step(
                interfaces=[port_channel_name], operational_state=True
            ),
        ]
    )


def create_port_channel_initial_setup_stage_with_permanent_disable(
    portchannel_health_check: PointInTimeHealthCheck,
    interfaces_to_disable: list[str],
) -> Stage:
    """
    Create the initial setup stage for port channel testing.

    This stage verifies the port channel is up, disables specified interfaces,
    then verifies the expected port operational state.

    Args:
        port_channel_name: Name of the port channel to verify
        interfaces_to_disable: List of interfaces to disable
        expected_port_operational_state: Expected operational state after disabling interfaces

    Returns:
        Stage object for port channel initial setup
    """
    return Stage(
        steps=[
            create_verify_port_operational_state_step(
                interfaces=interfaces_to_disable, operational_state=True
            ),
            create_interface_permanent_flap_step(
                enable=False, interfaces=interfaces_to_disable
            ),
            create_service_interruption_step(
                service=taac_types.Service.AGENT,
                trigger=taac_types.ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
            ),
            create_service_convergence_step(),
            create_longevity_step(duration=30),
            create_verify_port_operational_state_step(
                interfaces=interfaces_to_disable,
                operational_state=False,
            ),
            create_validation_step(
                point_in_time_checks=[portchannel_health_check],
                description="Validate port channel health",
            ),
        ]
    )


def create_port_channel_initial_setup_stage(
    portchannel_health_check: PointInTimeHealthCheck,
    interfaces_to_disable: list[str],
) -> Stage:
    """
    Create the initial setup stage for port channel testing.

    This stage verifies the port channel is up, disables specified interfaces,
    then verifies the expected port operational state.

    Args:
        port_channel_name: Name of the port channel to verify
        interfaces_to_disable: List of interfaces to disable
        expected_port_operational_state: Expected operational state after disabling interfaces

    Returns:
        Stage object for port channel initial setup
    """
    return Stage(
        steps=[
            create_verify_port_operational_state_step(
                interfaces=interfaces_to_disable, operational_state=True
            ),
            create_interface_flap_step(
                enable=False,
                interfaces=interfaces_to_disable,
                interface_flap_method=taac_types.InterfaceFlapMethod.THRIFT_PORT_STATE_CHANGE,
            ),
            create_verify_port_operational_state_step(
                interfaces=interfaces_to_disable,
                operational_state=False,
            ),
            create_validation_step(
                point_in_time_checks=[portchannel_health_check],
                description="Validate port channel health",
            ),
        ]
    )


def create_revert_route_storm_stage(
    device_name: str,
    interface: str,
    device_group_regex: str = ".*",
) -> Stage:
    """
    Create a stage that reverts route storm attributes to defaults.

    Wraps create_revert_route_storm_attributes_step in a Stage for convenience.

    Args:
        device_name: Name of the device
        interface: IXIA interface to revert attributes on
        device_group_regex: Regex to filter IXIA device groups by name (default: ".*")

    Returns:
        Stage with revert route storm attributes step
    """
    return Stage(
        steps=[
            create_revert_route_storm_attributes_step(
                device_name=device_name,
                interface=interface,
                device_group_regex=device_group_regex,
            )
        ],
        description="Revert route storm attributes to defaults",
    )


def create_route_storm_stage(
    device_name: str,
    interface: str,
    prefix_pool_regex: str,
    prefix_start_index: int,
    prefix_end_index: int | None = None,
    as_path_pool: list[str] | None = None,
    community_combinations: list[list[str]] | None = None,
    extended_community_combinations: list[list[str]] | None = None,
    as_path_length: int = 255,
    num_communities: int = 32,
    num_extended_communities: int = 16,
    device_group_regex: str = ".*",
    advertise_time: int = 60,
    withdraw_time: int = 60,
    test_duration_seconds: int = 3600,
) -> Stage:
    """
    Create a stage that stress-tests BGP with route storms using real attribute values.

    Configures BGP attributes (AS path pool, community pool, extended community pool)
    on IXIA using the ValueList pool APIs, then runs advertise->wait->withdraw->wait
    cycles for the specified duration.

    Supports two modes:
    - Explicit: pass as_path_pool, community_combinations, extended_community_combinations
      directly for full control over the attribute values.
    - Auto-generate: omit the explicit lists and pass as_path_length, num_communities,
      num_extended_communities to auto-generate sensible values using the attribute
      pool generator helpers.
    """
    from taac.routing.ebb.arista_bgp_plus_plus_performance_scaling_tests.attribute_pool_generator import (
        generate_as_path_pool,
        generate_community_combinations_for_prefixes,
        generate_community_pool,
        generate_extended_community_combinations_for_prefixes,
        generate_extended_community_pool,
    )

    prefix_count = (prefix_end_index or 1000) - prefix_start_index
    resolved_as_path_pool = as_path_pool or generate_as_path_pool(
        count=10, as_path_length=as_path_length
    )
    resolved_community_combinations = community_combinations
    if resolved_community_combinations is None:
        pool = generate_community_pool(count=num_communities)
        resolved_community_combinations = generate_community_combinations_for_prefixes(
            community_pool=pool,
            prefix_count=prefix_count,
            communities_per_prefix=num_communities,
        )
    resolved_ext_community_combinations = extended_community_combinations
    if resolved_ext_community_combinations is None:
        ext_pool = generate_extended_community_pool(count=num_extended_communities)
        resolved_ext_community_combinations = (
            generate_extended_community_combinations_for_prefixes(
                extended_community_pool=ext_pool,
                prefix_count=prefix_count,
                extended_communities_per_prefix=num_extended_communities,
            )
        )

    steps: list[Step] = []
    steps.append(
        create_configure_as_path_pool_step(
            device_name=device_name,
            interface=interface,
            as_path_pool=resolved_as_path_pool,
            device_group_regex=device_group_regex,
        )
    )
    steps.append(
        create_configure_community_pool_step(
            device_name=device_name,
            interface=interface,
            community_combinations=resolved_community_combinations,
            device_group_regex=device_group_regex,
        )
    )
    steps.append(
        create_configure_extended_community_pool_step(
            device_name=device_name,
            interface=interface,
            extended_community_combinations=resolved_ext_community_combinations,
            device_group_regex=device_group_regex,
        )
    )
    iterations = test_duration_seconds // (advertise_time + withdraw_time)
    for _ in range(iterations):
        steps.append(
            create_advertise_withdraw_prefixes_step(
                device_name,
                True,
                prefix_pool_regex,
                prefix_start_index,
                prefix_end_index,
            )
        )
        steps.append(
            create_longevity_step(
                duration=advertise_time,
                description=f"Sleep for advertise phase. {advertise_time} seconds",
            )
        )
        steps.append(
            create_advertise_withdraw_prefixes_step(
                device_name,
                False,
                prefix_pool_regex,
                prefix_start_index,
                prefix_end_index,
            )
        )
        steps.append(
            create_longevity_step(
                duration=withdraw_time,
                description=f"Sleep for withdraw phase. {withdraw_time} seconds",
            )
        )

    return Stage(steps=steps)


# =============================================================================
# MP3N PREFIX PROFILING STAGES (migrated from ai_bb/dsf/mp3n_playbook_stages.py)
# =============================================================================
@dataclass
class StageConfig:
    """Configuration for stage creation."""

    distribution_type: str
    prefix_length: int
    device_name: str
    uplink_interface: str


def create_enable_and_configure_stage(
    stage_id_prefix: str,
    distribution_type: str,
    prefix_length: int,
    device_name: str,
    uplink_interface: str,
    prefix_count: int,
    network_group_regex: str,
    fixed_prefix: str | None = None,
    random_mask: str | None = None,
    seed: int | None = None,
    random_mask_count: int | None = None,
) -> Stage:
    """Stage 1: Disable other device groups, enable target, configure prefixes."""
    steps = []

    for other_type in ["contiguous", "hybrid", "non_contiguous"]:
        if other_type != distribution_type:
            steps.append(create_toggle_device_group_step(other_type, enable=False))

    steps.append(create_toggle_device_group_step(distribution_type, enable=True))

    steps.append(
        create_update_prefix_count_step(
            device_name=device_name,
            interface=uplink_interface,
            prefix_count=prefix_count,
            distribution_type=distribution_type,
        )
    )

    if (
        fixed_prefix
        and random_mask
        and seed is not None
        and random_mask_count is not None
    ):
        steps.append(
            create_configure_random_mask_step(
                network_group_regex=network_group_regex,
                fixed_prefix=fixed_prefix,
                random_mask=random_mask,
                seed=seed,
                count=random_mask_count,
                distribution_type=distribution_type,
                prefix_length=prefix_length,
            )
        )
    else:
        steps.append(
            create_configure_prefix_length_step(
                network_group_regex=network_group_regex,
                prefix_length=prefix_length,
                distribution_type=distribution_type,
            )
        )

    return create_steps_stage(
        stage_id=f"{stage_id_prefix}_{distribution_type}_{prefix_length}",
        steps=steps,
    )


def create_start_traffic_stage(
    stage_id_prefix: str,
    distribution_type: str,
    prefix_length: int,
) -> Stage:
    """Stage 2: Start traffic."""
    return create_steps_stage(
        stage_id=f"{stage_id_prefix}_{distribution_type}_{prefix_length}",
        steps=[create_start_traffic_step()],
    )


def create_mp3n_warmboot_trigger_stage(
    distribution_type: str,
    prefix_length: int,
    timeout: int = 600,
) -> Stage:
    """Stage 4: Warmboot trigger (agent restart). MP3N variant."""
    return create_steps_stage(
        stage_id=f"warmboot_{distribution_type}_{prefix_length}",
        steps=[
            create_service_interruption_step(
                service=Service.AGENT,
                trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
            ),
            create_service_convergence_step(
                services=[Service.AGENT, Service.BGP],
                timeout=timeout,
            ),
        ],
    )


def create_mp3n_bgp_restart_trigger_stage(
    distribution_type: str,
    prefix_length: int,
    timeout: int = 600,
) -> Stage:
    """Stage 4: BGP restart trigger (bgpd restart). MP3N variant."""
    return create_steps_stage(
        stage_id=f"bgp_restart_{distribution_type}_{prefix_length}",
        steps=[
            create_service_interruption_step(
                service=Service.BGP,
                trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
            ),
            create_service_convergence_step(
                services=[Service.BGP],
                timeout=timeout,
            ),
        ],
    )


def create_mp3n_coldboot_trigger_stage(
    distribution_type: str,
    prefix_length: int,
    timeout: int = 900,
) -> Stage:
    """Stage 4: Coldboot trigger (full device reboot). MP3N variant."""
    return create_steps_stage(
        stage_id=f"coldboot_{distribution_type}_{prefix_length}",
        steps=[
            create_service_interruption_step(
                service=Service.AGENT,
                trigger=ServiceInterruptionTrigger.SYSTEMCTL_RESTART,
                create_cold_boot_file=True,
            ),
            create_service_convergence_step(
                services=[Service.AGENT, Service.BGP],
                timeout=timeout,
            ),
        ],
    )


def create_wait_convergence_stage(
    stage_id_prefix: str,
    distribution_type: str,
    prefix_length: int,
    duration: int = 120,
) -> Stage:
    """Stage 5: Wait for convergence (routes to re-establish)."""
    return create_steps_stage(
        stage_id=f"{stage_id_prefix}_{distribution_type}_{prefix_length}",
        steps=[create_longevity_step(duration)],
    )


def create_toggle_and_analyze_stage(
    network_group_regex: str,
    iterations: int = 5,
    time_threshold: int = 35,
    wait_time_seconds: int = 60,
    stage_id: str | None = None,
) -> Stage:
    """Toggle BGP prefixes and analyze route convergence timing."""
    return create_steps_stage(
        stage_id=stage_id or "toggle_and_analyze",
        steps=[
            create_route_convergence_health_check_step(
                network_group_regex=network_group_regex,
                iterations=iterations,
                time_threshold=time_threshold,
                wait_time_seconds=wait_time_seconds,
            ),
        ],
    )


def create_stop_traffic_stage(
    stage_id_prefix: str,
    distribution_type: str,
    prefix_length: int,
) -> Stage:
    """Final stage: Stop traffic."""
    return create_steps_stage(
        stage_id=f"{stage_id_prefix}_{distribution_type}_{prefix_length}",
        steps=[create_stop_traffic_step()],
    )


def create_clear_stats_stage(
    stage_id_prefix: str,
    distribution_type: str,
    prefix_length: int,
) -> Stage:
    """Stage to clear traffic stats."""
    return create_steps_stage(
        stage_id=f"{stage_id_prefix}_{distribution_type}_{prefix_length}",
        steps=[create_clear_traffic_stats_step()],
    )


def create_packet_loss_validation_stage(
    stage_id_prefix: str,
    distribution_type: str,
    prefix_length: int,
    traffic_item_names: list[str],
    description: str = "Validate zero packet loss",
) -> Stage:
    """Validate zero packet loss for specified traffic items."""
    return create_steps_stage(
        stage_id=f"{stage_id_prefix}_{distribution_type}_{prefix_length}",
        steps=[
            create_validation_step(
                point_in_time_checks=[
                    create_ixia_packet_loss_check(
                        thresholds=[
                            hc_types.PacketLossThreshold(
                                names=traffic_item_names,
                                str_value="0.3",
                                expect_packet_loss=False,
                                metric=hc_types.PacketLossMetric.DURATION,
                            ),
                        ],
                    ),
                ],
                description=description,
            ),
        ],
    )


def create_fpf_stress_concurrent_stage(
    gtsws: list[str],
    hosts: list[str],
    trigger_stsws: list[str],
    baseline_delay_sec: int = 120,
    collection_duration_sec: int = 720,
    poll_interval_sec: int = 5,
    subnet_prefix: str = "5000:dd::/32",
    prefix_count: int = 20000,
    community_list: str = "stsw",
    lanes: list[int] | None = None,
) -> Stage:
    """FPF stress stage: concurrent collector + (baseline delay → injection) tracks.

    Track 1 polls FSDB ribMap / HRT bulk / BGP RIB for `collection_duration_sec`.
    Track 2 sleeps `baseline_delay_sec` then injects `prefix_count` prefixes on
    `trigger_stsws`. Stage completes when the slowest track (collector) finishes.
    """
    from taac.steps.step_definitions import (
        create_fpf_bgp_prefix_injection_step,
        create_fpf_continuous_collector_step,
        create_longevity_step,
    )

    resolved_lanes = lanes if lanes is not None else [0, 1]
    return Stage(
        concurrent=True,
        concurrent_steps=[
            ConcurrentStep(
                steps=[
                    create_fpf_continuous_collector_step(
                        gtsws=gtsws,
                        hosts=hosts,
                        subnet_prefix=subnet_prefix,
                        poll_interval_sec=poll_interval_sec,
                        collection_duration_sec=collection_duration_sec,
                        lanes=resolved_lanes,
                        fsdb_expected=prefix_count,
                        bgp_expected=prefix_count,
                        trigger_delay_sec=baseline_delay_sec,
                    ),
                ],
            ),
            ConcurrentStep(
                steps=[
                    create_longevity_step(
                        duration=baseline_delay_sec,
                        description="Baseline collection delay before prefix injection",
                    ),
                    create_fpf_bgp_prefix_injection_step(
                        devices=trigger_stsws,
                        count=prefix_count,
                        community_list=community_list,
                        description=f"Inject {prefix_count} BGP prefixes on {', '.join(trigger_stsws)}",
                    ),
                ],
            ),
        ],
    )


def create_fpf_hardening_concurrent_stage(
    gtsws: list[str],
    hosts: list[str],
    trigger_stsws: list[str],
    disruption_steps: list[Step],
    pre_disruption_delay_sec: int,
    disruption_duration_sec: int,
    recovery_wait_sec: int = 300,
    baseline_delay_sec: int = 120,
    poll_interval_sec: int = 5,
    subnet_prefix: str = "5000:dd::/32",
    prefix_count: int = 70000,
    community_list: str = "stsw",
    lanes: list[int] | None = None,
    concurrent_disruption_steps: list[Step] | None = None,
) -> Stage:
    """FPF hardening stage: 3-track (or 4-track) concurrent execution.

    Track 1 (collector): Polls FSDB ribMap / HRT bulk / BGP RIB for the full
        duration covering injection, stabilization, disruption, and recovery.
    Track 2 (injection): Baseline delay then prefix injection.
    Track 3 (disruption): Waits for injection + stabilization, then runs
        the test-case-specific disruption steps.
    Track 4 (optional): If `concurrent_disruption_steps` is provided, runs
        a second set of disruption steps in parallel with Track 3 (used for
        combined stress + trigger tests like TC33).

    The collector duration auto-sizes to cover the full lifecycle:
        collection_duration = pre_disruption_delay + disruption_duration + recovery_wait
    """
    from taac.steps.step_definitions import (
        create_fpf_bgp_prefix_injection_step,
        create_fpf_continuous_collector_step,
        create_longevity_step,
    )

    resolved_lanes = lanes if lanes is not None else [0, 1]

    collection_duration_sec = (
        pre_disruption_delay_sec + disruption_duration_sec + recovery_wait_sec
    )
    if collection_duration_sec < pre_disruption_delay_sec:
        raise ValueError(
            f"collection_duration_sec ({collection_duration_sec}) must be >= "
            f"pre_disruption_delay_sec ({pre_disruption_delay_sec})"
        )

    concurrent_steps = [
        # Track 1: continuous collector
        ConcurrentStep(
            steps=[
                create_fpf_continuous_collector_step(
                    gtsws=gtsws,
                    hosts=hosts,
                    subnet_prefix=subnet_prefix,
                    poll_interval_sec=poll_interval_sec,
                    collection_duration_sec=collection_duration_sec,
                    lanes=resolved_lanes,
                    fsdb_expected=prefix_count,
                    bgp_expected=prefix_count,
                    trigger_delay_sec=baseline_delay_sec,
                ),
            ],
        ),
        # Track 2: baseline delay then prefix injection
        ConcurrentStep(
            steps=[
                create_longevity_step(
                    duration=baseline_delay_sec,
                    description="Baseline collection delay before prefix injection",
                ),
                create_fpf_bgp_prefix_injection_step(
                    devices=trigger_stsws,
                    count=prefix_count,
                    community_list=community_list,
                    description=(
                        f"Inject {prefix_count} BGP prefixes on "
                        f"{', '.join(trigger_stsws)}"
                    ),
                ),
            ],
        ),
        # Track 3: wait for stable state, then execute disruption
        ConcurrentStep(
            steps=[
                create_longevity_step(
                    duration=pre_disruption_delay_sec,
                    description=(
                        "Wait for prefix injection + stabilization before "
                        "disruptive event"
                    ),
                ),
                *disruption_steps,
            ],
        ),
    ]

    if concurrent_disruption_steps:
        concurrent_steps.append(
            ConcurrentStep(
                steps=[
                    create_longevity_step(
                        duration=pre_disruption_delay_sec,
                        description=(
                            "Wait for stable state before concurrent disruption track"
                        ),
                    ),
                    *concurrent_disruption_steps,
                ],
            ),
        )

    return Stage(concurrent=True, concurrent_steps=concurrent_steps)
