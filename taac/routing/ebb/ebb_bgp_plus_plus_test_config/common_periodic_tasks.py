# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""
This module re-exports task creation functions from task_definitions.py for backward compatibility.

All task creation functions have been consolidated into task_definitions.py.
Import directly from task_definitions.py for new code.
"""

import typing as t

from neteng.test_infra.dne.taac.constants import ARISTA_7808_CPU_COUNT, Gigabyte
from taac.task_definitions import (
    create_cpu_only_periodic_tasks as _create_cpu_only_periodic_tasks,
    create_longevity_periodic_tasks as _create_longevity_periodic_tasks,
    create_standard_periodic_tasks as _create_standard_periodic_tasks,
)
from taac.test_as_a_config import types as taac_types


# Re-export for backward compatibility
def create_standard_periodic_tasks(
    device_name: str,
    cpu_load_threshold: float = 12.0,
    cpu_util_threshold: float = 40.0,
    memory_threshold: int = Gigabyte.GIG_10.value,
    interval: int = 60,
    cpu_load_terminate_on_error: bool = False,
    cpu_util_terminate_on_error: bool = False,
    memory_terminate_on_error: bool = False,
    cpu_count: int | None = ARISTA_7808_CPU_COUNT,
    enable_process_monitor: bool = True,
    process_filter: t.Optional[t.List[str]] = None,
    process_monitor_interval: int = 5,
) -> t.List[taac_types.PeriodicTask]:
    """
    Create standard periodic tasks for BGP tests.

    .. deprecated::
        Import from neteng.test_infra.dne.taac.task_definitions instead.
    """
    return _create_standard_periodic_tasks(
        device_name=device_name,
        cpu_load_threshold=cpu_load_threshold,
        cpu_util_threshold=cpu_util_threshold,
        memory_threshold=memory_threshold,
        interval=interval,
        cpu_load_terminate_on_error=cpu_load_terminate_on_error,
        cpu_util_terminate_on_error=cpu_util_terminate_on_error,
        memory_terminate_on_error=memory_terminate_on_error,
        cpu_count=cpu_count,
        enable_process_monitor=enable_process_monitor,
        process_filter=process_filter,
        process_monitor_interval=process_monitor_interval,
    )


def create_cpu_only_periodic_tasks(
    device_name: str,
    cpu_load_threshold: float = 12.0,
    interval: int = 60,
    terminate_on_error: bool = True,
) -> t.List[taac_types.PeriodicTask]:
    """
    Create CPU load monitoring only periodic tasks.

    .. deprecated::
        Import from neteng.test_infra.dne.taac.task_definitions instead.
    """
    return _create_cpu_only_periodic_tasks(
        device_name=device_name,
        cpu_load_threshold=cpu_load_threshold,
        interval=interval,
        terminate_on_error=terminate_on_error,
    )


def create_longevity_periodic_tasks(
    device_name: str,
    route_churn_frequency: int = 60,
    route_churn_prefix_pool_regex: str = ".*IBGP.*PLANE_1.*",
    route_churn_prefix_start_index: int = 0,
    route_churn_prefix_end_index: int = 20,
    local_pref_churn_frequency: int = 60,
    local_pref_prefix_pool_regex: str = ".*IBGP.*PLANE_2.*",
    local_pref_churn_prefix_start_index: int = 0,
    local_pref_churn_prefix_end_index: int = 20,
    local_pref_start: int = 90,
    local_pref_end: int = 111,
    as_path_drain_frequency: int = 60,
    as_path_drain_prefix_pool_regex: str = ".*IBGP.*PLANE_2.*DRAIN",
    as_path_drain_as_numbers: list[str] | None = None,
    origin_churn_frequency: int = 60,
    origin_prefix_pool_regex: str = ".*IBGP.*PLANE_3.*",
    origin_prefix_start_index: int = 0,
    origin_prefix_end_index: int = 20,
    community_churn_frequency: int = 60,
    community_prefix_pool_regex: str = ".*IBGP.*PLANE_4.*",
    community_count: int = 5,
    igp_cost_frequency: int = 60,
    start_ipv4s: list[str] | None = None,
    start_ipv6s: list[str] | None = None,
    local_link: dict | None = None,
    other_link: dict | None = None,
    count: int = 63,
    update_count: int = 50,
    restart_peers_frequency: int = 3600,
    restart_peers_ebgp_regex: str = ".*EBGP.*",
    restart_peers_ebgp_session_num: int = 8,
    restart_peers_ibgp_regex: str = ".*IBGP.*",
    restart_peers_ibgp_session_num: int = 2,
) -> t.List[taac_types.PeriodicTask]:
    """
    Create longevity test periodic tasks.

    .. deprecated::
        Import from neteng.test_infra.dne.taac.task_definitions instead.
    """
    return _create_longevity_periodic_tasks(
        device_name=device_name,
        route_churn_frequency=route_churn_frequency,
        route_churn_prefix_pool_regex=route_churn_prefix_pool_regex,
        route_churn_prefix_start_index=route_churn_prefix_start_index,
        route_churn_prefix_end_index=route_churn_prefix_end_index,
        local_pref_churn_frequency=local_pref_churn_frequency,
        local_pref_prefix_pool_regex=local_pref_prefix_pool_regex,
        local_pref_churn_prefix_start_index=local_pref_churn_prefix_start_index,
        local_pref_churn_prefix_end_index=local_pref_churn_prefix_end_index,
        local_pref_start=local_pref_start,
        local_pref_end=local_pref_end,
        as_path_drain_frequency=as_path_drain_frequency,
        as_path_drain_prefix_pool_regex=as_path_drain_prefix_pool_regex,
        as_path_drain_as_numbers=as_path_drain_as_numbers,
        origin_churn_frequency=origin_churn_frequency,
        origin_prefix_pool_regex=origin_prefix_pool_regex,
        origin_prefix_start_index=origin_prefix_start_index,
        origin_prefix_end_index=origin_prefix_end_index,
        community_churn_frequency=community_churn_frequency,
        community_prefix_pool_regex=community_prefix_pool_regex,
        community_count=community_count,
        igp_cost_frequency=igp_cost_frequency,
        start_ipv4s=start_ipv4s,
        start_ipv6s=start_ipv6s,
        local_link=local_link,
        other_link=other_link,
        count=count,
        update_count=update_count,
        restart_peers_frequency=restart_peers_frequency,
        restart_peers_ebgp_regex=restart_peers_ebgp_regex,
        restart_peers_ebgp_session_num=restart_peers_ebgp_session_num,
        restart_peers_ibgp_regex=restart_peers_ibgp_regex,
        restart_peers_ibgp_session_num=restart_peers_ibgp_session_num,
    )
