# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""
Consolidated task definitions for TAAC test configurations.

This module provides:
1. Reusable Task constants for common operations
2. Task factory functions to create parameterized tasks
3. Helper functions to create lists of related tasks

Import from this module instead of creating inline Task objects in test configs.
"""

import base64
import json
import typing as t

from taac.constants import (
    ARISTA_7808_CPU_COUNT,
    DEFAULT_LOCAL_LINK,
    DEFAULT_OPENR_START_IPV4S,
    DEFAULT_OPENR_START_IPV6S,
    DEFAULT_OTHER_LINK,
    Gigabyte,
    OpenRRouteAction,
)
from taac.tasks.thrift_stress_payloads import ThriftStressCall
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import Params, PeriodicTask, Task


def create_fpf_ensure_interfaces_enabled_task(
    interfaces_by_device: t.Mapping[str, t.Sequence[str]],
) -> Task:
    """Create an idempotent TestConfig-teardown guard for held-down ports."""
    empty_devices = sorted(
        device for device, interfaces in interfaces_by_device.items() if not interfaces
    )
    if empty_devices:
        raise ValueError(
            "Every interface-enable target must contain at least one interface; "
            f"empty targets: {empty_devices}"
        )
    targets = [
        {"device": device, "interfaces": sorted(set(interfaces))}
        for device, interfaces in sorted(interfaces_by_device.items())
    ]
    if not targets:
        raise ValueError("At least one device/interface target is required")
    return Task(
        task_name="fpf_ensure_interfaces_enabled",
        description="Best-effort restore of FPF interface admin state",
        params=Params(json_params=json.dumps({"targets": targets})),
    )


# =============================================================================
# EOS IMAGE DEPLOYMENT TASK FACTORY
# =============================================================================


def create_deploy_eos_image_task(
    hostname: str,
    eos_image_id: str,
    skip_reload: bool = False,
    skip_wait_for_boot: bool = False,
) -> Task:
    """
    Create a task to deploy an EOS image to an Arista device.

    This task downloads and installs an EOS image on the device using fbpkg
    directly on the device. It handles:
    1. Downloading the image via fbpkg on the device
    2. Untarring and installing the image
    3. Setting the boot config
    4. Reloading the device
    5. Waiting for the device to boot

    IMPORTANT: This task should run as a PRE-IXIA task (ixia_needed=False) so it
    executes BEFORE any config tasks. Config tasks should have ixia_needed=True
    to run AFTER EOS deployment.

    Args:
        hostname: Device hostname
        eos_image_id: EOS image ID in fbpkg format, e.g.,
            "neteng.arista_fboss.bag:tag" or full UUID
        skip_reload: Skip reload after image installation (default: False)
        skip_wait_for_boot: Skip waiting for boot (default: False)

    Returns:
        Task object for EOS image deployment
    """
    return Task(
        task_name="deploy_eos_image",
        ixia_needed=False,  # MUST be False to run BEFORE config tasks
        params=Params(
            json_params=json.dumps(
                {
                    "hostname": hostname,
                    "eos_image_id": eos_image_id,
                    "skip_reload": skip_reload,
                    "skip_wait_for_boot": skip_wait_for_boot,
                }
            )
        ),
    )


# =============================================================================
# TASK FACTORY FUNCTIONS - Create parameterized Task objects
# =============================================================================


def create_coop_unregister_patchers_task(
    hostnames: t.List[str] | str,
    config_names: t.Optional[t.List[str]] = None,
) -> Task:
    """
    Create a task to unregister all patchers for the given host(s).

    Args:
        hostnames: Single hostname or list of hostnames to unregister patchers from
        config_names: Optional list of config names to scope the unregister
            (e.g. ["bgpcpp", "agent"]). If None, unregisters all configs.

    Returns:
        Task object to unregister patchers
    """
    if isinstance(hostnames, str):
        params: t.Dict[str, t.Any] = {"hostname": hostnames}
    else:
        params = {"hostnames": hostnames}
    if config_names is not None:
        params["config_names"] = config_names

    return Task(
        task_name="coop_unregister_patchers",
        params=Params(json_params=json.dumps(params)),
    )


def create_coop_register_patcher_task(
    hostname: str,
    patcher_name: str,
    config_name: t.Optional[str] = None,
    config_names: t.Optional[t.List[str]] = None,
    task_name: t.Optional[str] = None,
    patcher_args: t.Optional[t.Dict[str, t.Any]] = None,
    py_func_name: t.Optional[str] = None,
) -> Task:
    """
    Create a task to register a coop patcher on a device.

    Args:
        hostname: Name of the device to register patcher on
        patcher_name: Unique name for this patcher
        config_name: Config type (e.g., "bgpcpp", "agent"). Mutually exclusive with config_names.
        config_names: List of config types (used when patcher applies across multiple configs).
        task_name: Task name that this patcher performs (optional — many call sites omit it
            and rely on py_func_name as the dispatch key).
        patcher_args: Optional arguments for the patcher (serialized via inner json.dumps)
        py_func_name: Optional Python function name for the patcher

    Returns:
        Task object to register the patcher
    """
    # Preserve original key insertion order (hostname, config_name, patcher_name,
    # task_name) for byte-equivalence with pre-Phase-8 callers' JSON serialization.
    params: t.Dict[str, t.Any] = {"hostname": hostname}
    if config_name is not None:
        params["config_name"] = config_name
    if config_names is not None:
        params["config_names"] = config_names
    params["patcher_name"] = patcher_name
    if task_name is not None:
        params["task_name"] = task_name
    if patcher_args is not None:
        params["patcher_args"] = json.dumps(patcher_args)
    if py_func_name is not None:
        params["py_func_name"] = py_func_name

    return Task(
        task_name="coop_register_patcher",
        params=Params(json_params=json.dumps(params)),
    )


def create_coop_apply_patchers_task(
    hostnames: t.List[str],
    config_name: str = "bgpcpp",
    do_warmboot: bool = False,
    do_coldboot: bool = False,
) -> Task:
    """
    Create a task to apply registered patchers on device(s).

    Args:
        hostnames: List of hostnames to apply patchers on
        config_name: Config type to apply (default: "bgpcpp")
        do_warmboot: Whether to perform a warmboot after applying (default: False)
        do_coldboot: Whether to perform a coldboot after applying (default: False).
            Required for port-channel agent patchers (min-link, agg-port creation, etc.)

    Returns:
        Task object to apply patchers
    """
    params: t.Dict[str, t.Any] = {
        "hostnames": hostnames,
        "config_name": config_name,
    }
    if do_coldboot:
        params["do_coldboot"] = True
    elif do_warmboot:
        params["do_warmboot"] = True

    return Task(
        task_name="coop_apply_patchers",
        params=Params(json_params=json.dumps(params)),
    )


def create_coop_apply_patchers_v2_task(
    hostnames: t.List[str],
    apply_patcher_method: t.Optional[int] = None,
) -> Task:
    """
    Create a task to apply registered patchers on device(s) using v2 API.

    Args:
        hostnames: List of hostnames to apply patchers on
        apply_patcher_method: The ApplyPatcherMethod enum value to use

    Returns:
        Task object to apply patchers v2
    """
    params: t.Dict[str, t.Any] = {
        "hostnames": hostnames,
    }
    if apply_patcher_method is not None:
        params["apply_patcher_method"] = apply_patcher_method

    return Task(
        task_name="coop_apply_patchers_v2",
        params=Params(json_params=json.dumps(params)),
    )


def create_wait_for_agent_convergence_task(
    hostnames: t.List[str] | str,
    timeout: t.Optional[int] = None,
    interval: t.Optional[int] = None,
) -> Task:
    """
    Create a task to wait for agent convergence.

    Args:
        hostnames: Single hostname or list of hostnames to wait for
        timeout: Optional convergence timeout (seconds). When set, caps how
            long the task polls before failing. Defaults to None, in which
            case the underlying WaitForAgentConvergenceTask uses its own
            default (600s). Useful for quick validation runs that want to
            fail fast instead of waiting the full ceiling.
        interval: Optional poll interval (seconds). Defaults to None
            (underlying task default, 5s).

    Returns:
        Task object to wait for agent convergence
    """
    if isinstance(hostnames, str):
        hostnames = [hostnames]

    task_params: t.Dict[str, t.Any] = {"hostnames": hostnames}
    if timeout is not None:
        task_params["timeout"] = timeout
    if interval is not None:
        task_params["interval"] = interval

    return Task(
        task_name="wait_for_agent_convergence",
        params=Params(json_params=json.dumps(task_params)),
    )


def create_assert_thrift_rate_limit_enabled_task(
    hostname: str,
) -> Task:
    """Setup-gate task: assert `thriftApiToRateLimitInQps` is non-empty
    in the DUT's running agent config before any THFT playbook starts.

    Fails fast (raises in the underlying task's `run()`) if the
    configerator-side rate limit map (set via D108220182 for IcePack TH6
    / ICECUBE800BC) hasn't shipped or COOP hasn't re-applied the agent
    config. This prevents burning a 4-hour THFT soak only to discover at
    postcheck time that the agent had no server-side throttling and got
    pegged at >1000% CPU.

    Args:
        hostname: DUT hostname (FBOSS-only — `getRunningConfig()` is a
            FBOSS thrift API).

    Returns:
        Task object that runs `AssertThriftRateLimitEnabledTask` at
        setup time.
    """
    return Task(
        task_name="assert_thrift_rate_limit_enabled",
        params=Params(json_params=json.dumps({"hostname": hostname})),
    )


def create_wait_for_bgp_convergence_task(
    hostnames: t.List[str] | str,
    num_tries: int = 120,
    sleep: int = 10,
) -> Task:
    """
    Create a task to wait for BGP convergence.

    Args:
        hostname: Hostname to wait for
        num_tries: Number of attempts before timeout
        sleep: Seconds between retry attempts

    Returns:
        Task object to wait for BGP convergence
    """
    return Task(
        task_name="wait_for_bgp_convergence",
        params=Params(
            json_params=json.dumps(
                {
                    "hostnames": hostnames,
                    "num_tries": num_tries,
                    "sleep": sleep,
                }
            )
        ),
    )


def create_configure_parallel_bgp_peers_task(
    hostname: str,
    peer_configs: t.Optional[t.List[t.Dict[str, t.Any]]] = None,
    configure_vlans_patcher_name: t.Optional[str] = None,
    add_bgp_peers_patcher_name: t.Optional[str] = None,
    config_json: t.Optional[str] = None,
) -> Task:
    """
    Create a task to configure parallel BGP peers.

    Args:
        hostname: Hostname to configure peers on
        peer_configs: List of peer configuration dictionaries (simple mode)
        configure_vlans_patcher_name: Name of the VLAN patcher to use
        add_bgp_peers_patcher_name: Name of the BGP peers patcher to use
        config_json: JSON string with per-interface peer configurations

    Returns:
        Task object to configure BGP peers
    """
    params: t.Dict[str, t.Any] = {
        "hostname": hostname,
    }
    if peer_configs is not None:
        params["peer_configs"] = peer_configs
    if configure_vlans_patcher_name is not None:
        params["configure_vlans_patcher_name"] = configure_vlans_patcher_name
    if add_bgp_peers_patcher_name is not None:
        params["add_bgp_peers_patcher_name"] = add_bgp_peers_patcher_name
    if config_json is not None:
        params["config_json"] = config_json

    return Task(
        task_name="configure_parallel_bgp_peers",
        params=Params(json_params=json.dumps(params)),
    )


def create_configure_eos_parallel_bgp_peers_task(
    hostname: str,
    config_json: str,
    peer_configs: t.Optional[t.List[t.Dict[str, t.Any]]] = None,
) -> Task:
    """
    Create a task to configure parallel BGP peers on an Arista EOS device.

    This is the EOS equivalent of create_configure_parallel_bgp_peers_task. Instead
    of COOP patchers, it directly configures the Arista switch via the driver to
    assign IP addresses to interfaces and create BGP neighbors.

    Args:
        hostname: Hostname of the EOS device to configure
        config_json: JSON string with per-interface peer configurations. Format:
            {
                "Ethernet3/25/1": [
                    {
                        "starting_ip": "2401:db00:e50d:11:8::10",
                        "increment_ip": "::2",
                        "gateway_starting_ip": "2401:db00:e50d:11:8::11",
                        "gateway_increment_ip": "::2",
                        "num_sessions": 100,
                        "remote_as_4_byte": 65000,
                        "peer_group_name": "PEERGROUP_EBGP_V6",
                        "prefix_length": 127,
                    }
                ]
            }
        peer_configs: Optional list of peer config dicts for merge mode

    Returns:
        Task object to configure EOS BGP peers
    """
    params: t.Dict[str, t.Any] = {
        "hostname": hostname,
        "config_json": config_json,
    }
    if peer_configs is not None:
        params["peer_configs"] = peer_configs

    return Task(
        task_name="configure_eos_parallel_bgp_peers",
        params=Params(json_params=json.dumps(params)),
    )


def create_eos_bgp_peer_group_task(
    hostname: str,
    peer_group_name: str,
    register: bool = True,
    remote_as: t.Optional[int] = None,
    description: t.Optional[str] = None,
    update_source: t.Optional[str] = None,
    activate: bool = True,
    ipv4_unicast: bool = True,
    ipv6_unicast: bool = False,
    route_map_in: t.Optional[str] = None,
    route_map_out: t.Optional[str] = None,
    next_hop_self: bool = False,
    out_delay: t.Optional[int] = None,
    timers_keepalive: t.Optional[int] = None,
    timers_holdtime: t.Optional[int] = None,
    send_community: bool = False,
    maximum_routes: t.Optional[int] = None,
    maximum_routes_warning_limit: t.Optional[int] = None,
    maximum_routes_warning_only: bool = False,
    local_as: t.Optional[int] = None,
    local_as_no_prepend: bool = False,
    local_as_replace_as: bool = False,
    local_as_fallback: bool = False,
    graceful_restart_helper: bool = False,
    send_community_link_bandwidth: bool = False,
    link_bandwidth_aggregate: t.Optional[str] = None,
) -> Task:
    """
    Create a task to create or remove a BGP peer group on an Arista EOS device.

    This is the EOS ar-bgp equivalent of the FBOSS add_peer_group_patcher COOP
    patcher. It wraps AristaSwitch.async_create_bgp_peer_group() to configure
    peer groups via EOS CLI commands.

    When register=False, the task removes the peer group by calling
    AristaSwitch.async_remove_bgp_peer_group(). Only hostname and
    peer_group_name are needed for removal.

    Args:
        hostname: Hostname of the EOS device
        peer_group_name: Name of the BGP peer group (e.g., "PEERGROUP_BAG_STSW_V6")
        register: If True (default), create the peer group. If False, remove it.
        remote_as: Remote AS number for the peer group
        description: Description for the peer group
        update_source: Interface to use as source for BGP packets
        activate: Whether to activate the peer group in the address family
        ipv4_unicast: Configure for IPv4 unicast address family
        ipv6_unicast: Configure for IPv6 unicast address family
        route_map_in: Inbound route-map name (ingress policy)
        route_map_out: Outbound route-map name (egress policy)
        next_hop_self: Whether to set next-hop-self
        out_delay: Out delay in seconds
        timers_keepalive: BGP keepalive timer in seconds
        timers_holdtime: BGP hold timer in seconds
        send_community: Whether to send community attribute
        maximum_routes: Maximum number of routes to accept
        maximum_routes_warning_limit: Warning limit for maximum routes
        maximum_routes_warning_only: Whether to only warn when max routes exceeded
        local_as: Local AS number override
        local_as_no_prepend: Do not prepend local AS to AS path
        local_as_replace_as: Replace AS number with local AS
        local_as_fallback: Use local AS as fallback
        graceful_restart_helper: Enable graceful restart helper mode
        send_community_link_bandwidth: Send community link bandwidth
        link_bandwidth_aggregate: Link bandwidth aggregate value

    Returns:
        Task object to create or remove the EOS BGP peer group
    """
    params: t.Dict[str, t.Any] = {
        "hostname": hostname,
        "peer_group_name": peer_group_name,
    }

    if not register:
        params["register"] = False
        return Task(
            task_name="create_eos_bgp_peer_group",
            params=Params(json_params=json.dumps(params)),
        )

    optional_params = {
        "remote_as": remote_as,
        "description": description,
        "update_source": update_source,
        "route_map_in": route_map_in,
        "route_map_out": route_map_out,
        "out_delay": out_delay,
        "timers_keepalive": timers_keepalive,
        "timers_holdtime": timers_holdtime,
        "maximum_routes": maximum_routes,
        "maximum_routes_warning_limit": maximum_routes_warning_limit,
        "local_as": local_as,
        "link_bandwidth_aggregate": link_bandwidth_aggregate,
    }
    for key, value in optional_params.items():
        if value is not None:
            params[key] = value

    bool_params = {
        "activate": (activate, True),
        "ipv4_unicast": (ipv4_unicast, True),
        "ipv6_unicast": (ipv6_unicast, False),
        "next_hop_self": (next_hop_self, False),
        "send_community": (send_community, False),
        "maximum_routes_warning_only": (maximum_routes_warning_only, False),
        "local_as_no_prepend": (local_as_no_prepend, False),
        "local_as_replace_as": (local_as_replace_as, False),
        "local_as_fallback": (local_as_fallback, False),
        "graceful_restart_helper": (graceful_restart_helper, False),
        "send_community_link_bandwidth": (send_community_link_bandwidth, False),
    }
    for key, (value, default) in bool_params.items():
        if value != default:
            params[key] = value

    return Task(
        task_name="create_eos_bgp_peer_group",
        params=Params(json_params=json.dumps(params)),
    )


def create_eos_bgp_prefix_list_task(
    hostname: str,
    prefix_list_name: str,
    peer_group_name: str | t.List[str] | None = None,
    prefix: t.Optional[str] = None,
    direction: str = "in",
    prefix_length: t.Optional[int] = None,
    seq: t.Optional[int] = None,
    register: bool = True,
    is_ipv6: bool = True,
    route_map_name: str | t.List[str] | None = None,
    route_map_seq: t.Optional[int] = None,
) -> Task:
    """
    Create a task to add or remove a prefix-list on EOS, attaching it to
    route-map(s) or peer group(s).

    When route_map_name is provided, adds a permit entry to the specified
    route-map(s) matching the prefix-list. When peer_group_name is provided
    (legacy), attaches the prefix-list directly to peer group(s).

    Args:
        hostname: Hostname of the EOS device
        prefix_list_name: Name of the prefix-list
        peer_group_name: Peer group(s) for direct attachment (legacy mode)
        prefix: IP prefix to permit (e.g., "5000::/16"). Required when register=True.
        direction: "in" or "out" for inbound/outbound filtering
        prefix_length: Max prefix length for the "le" keyword
        seq: Sequence number for the prefix-list entry
        register: If True, create and attach. If False, remove.
        is_ipv6: IPv6 flag (only for removal when prefix not provided)
        route_map_name: Route-map(s) to add a permit entry to
        route_map_seq: Sequence number for the route-map permit entry
    """
    params: t.Dict[str, t.Any] = {
        "hostname": hostname,
        "prefix_list_name": prefix_list_name,
    }

    if peer_group_name is not None:
        params["peer_group_name"] = peer_group_name
    if route_map_name is not None:
        params["route_map_name"] = route_map_name
    if route_map_seq is not None:
        params["route_map_seq"] = route_map_seq

    if not register:
        params["register"] = False
        params["direction"] = direction
        if prefix is not None:
            params["prefix"] = prefix
        else:
            params["is_ipv6"] = is_ipv6
        return Task(
            task_name="add_eos_bgp_prefix_list_to_peer_group",
            params=Params(json_params=json.dumps(params)),
        )

    if prefix is None:
        raise ValueError("prefix is required when register=True")

    params["prefix"] = prefix
    params["direction"] = direction
    if prefix_length is not None:
        params["prefix_length"] = prefix_length
    if seq is not None:
        params["seq"] = seq

    return Task(
        task_name="add_eos_bgp_prefix_list_to_peer_group",
        params=Params(json_params=json.dumps(params)),
    )


def create_run_commands_on_shell_task(
    hostname: str,
    cmds: t.List[str],
    set_outer_hostname: bool = False,
    ixia_needed: bool = False,
    validate_output: bool = False,
) -> Task:
    """
    Create a task to run shell commands on a device.

    Args:
        hostname: Hostname to run commands on (always serialized into params dict)
        cmds: List of shell commands to execute
        set_outer_hostname: If True, also set Task.hostname (the outer Thrift field).
            Some legacy call sites set this for runner-side scoping.
        ixia_needed: If True, the task runs after IXIA setup with an Ixia instance available.
        validate_output: If True, reject EOS parser, authorization, and shell-exit errors.

    Returns:
        Task object to run shell commands
    """
    params: t.Dict[str, t.Any] = {
        "hostname": hostname,
        "cmds": cmds,
    }
    if validate_output:
        params["validate_output"] = True
    return Task(
        task_name="run_commands_on_shell",
        hostname=hostname if set_outer_hostname else None,
        ixia_needed=ixia_needed,
        params=Params(json_params=json.dumps(params)),
    )


def create_bgp_clear_route_filter_task(
    hostname: str,
    set_outer_hostname: bool = False,
    ixia_needed: bool = False,
) -> Task:
    """
    Create a task to clear the BGP route filter policy (CRF) on a device.

    Removes the ingress route-filter ("route registry") so no inbound eBGP
    prefixes are blocked; the clear also deletes the persisted rp_state_file, so
    the daemon stays CRF-free across restarts. Used by scale tests that inject
    arbitrary prefixes not in the device's baked-in registry.

    Args:
        hostname: Name of the device to clear the route filter on
        set_outer_hostname: If True, also set Task.hostname (the outer Thrift
            field) for runner-side scoping, matching sibling managed setup tasks.
        ixia_needed: If True, the task runs after IXIA setup with the device
            driver ready, for phasing parity with sibling managed setup tasks.

    Returns:
        Task object for clearing the BGP route filter
    """
    task_kwargs: t.Dict[str, t.Any] = {
        "task_name": "bgp_clear_route_filter",
        "params": Params(json_params=json.dumps({"hostname": hostname})),
    }
    if set_outer_hostname:
        task_kwargs["hostname"] = hostname
    if ixia_needed:
        task_kwargs["ixia_needed"] = ixia_needed

    return Task(**task_kwargs)


def create_full_reboot_task(
    hostname: str,
    reboot_cmd: t.Optional[str] = None,
    ssh_user: t.Optional[str] = None,
    ssh_password: t.Optional[str] = None,
    down_max_s: t.Optional[int] = None,
    up_max_s: t.Optional[int] = None,
) -> Task:
    """Create a task to perform a full host reboot via SSH.

    Issues `sudo systemctl reboot` over SSH to `hostname`, waits for the host to
    become SSH-unreachable (confirming the reboot took effect), then waits for
    it to come back online. Built for Phase 4-1 TC5 ("U-server reboot" in the
    bash harness, which is in fact a full reboot of the DUT switch as a Linux
    host). Generic over any SSH-reachable host.

    Args:
        hostname: FQDN of the host to reboot.
        reboot_cmd: Override the default `sudo systemctl reboot` if needed.
        ssh_user: SSH username; falls back to the default identity.
        ssh_password: SSH password if not using key auth.
        down_max_s: Max seconds to wait for host to go down (default 120).
        up_max_s: Max seconds to wait for host to come back (default 600).

    Returns:
        Task with `task_name="full_reboot"` carrying the params above.
    """
    payload: t.Dict[str, t.Any] = {"hostname": hostname}
    if reboot_cmd is not None:
        payload["reboot_cmd"] = reboot_cmd
    if ssh_user is not None:
        payload["ssh_user"] = ssh_user
    if ssh_password is not None:
        payload["ssh_password"] = ssh_password
    if down_max_s is not None:
        payload["down_max_s"] = down_max_s
    if up_max_s is not None:
        payload["up_max_s"] = up_max_s
    return Task(
        task_name="full_reboot",
        params=Params(json_params=json.dumps(payload)),
    )


def create_invoke_ixia_api_task(
    api_name: str,
    args_dict: t.Dict[str, t.Any],
) -> Task:
    """
    Create a task to invoke an Ixia API.

    Args:
        api_name: Name of the Ixia API to call
        args_dict: Arguments to pass to the API

    Returns:
        Task object to invoke Ixia API
    """
    return Task(
        task_name="invoke_ixia_api",
        ixia_needed=True,
        params=Params(
            json_params=json.dumps(
                {
                    "api_name": api_name,
                    "args_json": json.dumps(args_dict),
                }
            )
        ),
    )


def create_periodic_task_shell(
    task_name: str,
    ixia_needed: bool = False,
) -> Task:
    """Create a Task shell (no params) for use inside `taac_types.PeriodicTask`.

    A `PeriodicTask` supplies its own per-invocation params via the `params_list`
    field, so the wrapped Task only needs `task_name` (and optionally
    `ixia_needed`). This factory exists so that those Task() constructions can
    be migrated out of test_config files without inventing a per-task_name
    factory variant for every periodic call site.
    """
    return Task(task_name=task_name, ixia_needed=ixia_needed)


_UNSET_PREFIX_END_INDEX: t.Any = object()


def create_ixia_enable_disable_bgp_prefixes_task(
    enable: bool,
    prefix_pool_regex: str = ".*",
    prefix_start_index: int = 0,
    prefix_end_index: t.Any = _UNSET_PREFIX_END_INDEX,
    hostname: t.Optional[str] = None,
) -> Task:
    """
    Create a task to enable/disable BGP prefixes on Ixia.

    Args:
        enable: Whether to enable or disable prefixes
        prefix_pool_regex: Regex pattern to match prefix pools
        prefix_start_index: Starting index of prefixes
        prefix_end_index: Ending index of prefixes. When unset (the sentinel
            default), defaults to 20 for backward byte-equivalence with
            historical callers. Pass None explicitly to OMIT the key from the
            params dict (so the runtime task disables/enables the full range).
        hostname: Optional hostname to scope the operation. When supplied, it is
            included as the FIRST key in the params dict so byte-equivalence is
            preserved for callers that pass hostname. Default is None which
            preserves byte-equivalence for existing callers that omit hostname.

    Returns:
        Task object to toggle BGP prefixes
    """
    params: t.Dict[str, t.Any] = {}
    if hostname is not None:
        params["hostname"] = hostname
    params["enable"] = enable
    params["prefix_pool_regex"] = prefix_pool_regex
    params["prefix_start_index"] = prefix_start_index
    if prefix_end_index is _UNSET_PREFIX_END_INDEX:
        params["prefix_end_index"] = 20
    elif prefix_end_index is not None:
        params["prefix_end_index"] = prefix_end_index
    return Task(
        task_name="ixia_enable_disable_bgp_prefixes",
        ixia_needed=True,
        params=Params(json_params=json.dumps(params)),
    )


def create_ixia_restart_bgp_sessions_task(
    bgp_peer_regex: str = ".*",
    random_session_num: int = 2,
) -> Task:
    """
    Create a task to restart BGP sessions on Ixia.

    Args:
        bgp_peer_regex: Regex pattern to match BGP peers
        random_session_num: Number of random sessions to restart

    Returns:
        Task object to restart BGP sessions
    """
    return Task(
        task_name="ixia_restart_bgp_sessions",
        ixia_needed=True,
        params=Params(
            json_params=json.dumps(
                {
                    "bgp_peer_regex": bgp_peer_regex,
                    "random_session_num": random_session_num,
                }
            )
        ),
    )


def create_ixia_randomize_bgp_prefix_local_preference_task(
    prefix_pool_regex: str,
    prefix_start_index: int = 0,
    prefix_end_index: int = 20,
    start_value: int = 90,
    end_value: int = 111,
) -> Task:
    """
    Create a task to randomize BGP prefix local preference on Ixia.

    Args:
        prefix_pool_regex: Regex pattern to match prefix pools
        prefix_start_index: Starting index of prefixes
        prefix_end_index: Ending index of prefixes
        start_value: Minimum local preference value
        end_value: Maximum local preference value

    Returns:
        Task object to randomize local preference
    """
    return Task(
        task_name="ixia_randomize_bgp_prefix_local_preference",
        ixia_needed=True,
        params=Params(
            json_params=json.dumps(
                {
                    "prefix_pool_regex": prefix_pool_regex,
                    "prefix_start_index": prefix_start_index,
                    "prefix_end_index": prefix_end_index,
                    "start_value": start_value,
                    "end_value": end_value,
                }
            )
        ),
    )


def create_ixia_modify_bgp_prefixes_origin_value_task(
    prefix_pool_regex: str,
    prefix_start_index: int = 0,
    prefix_end_index: int = 20,
    origin_value: str = "igp",
) -> Task:
    """
    Create a task to modify BGP prefix origin value on Ixia.

    Args:
        prefix_pool_regex: Regex pattern to match prefix pools
        prefix_start_index: Starting index of prefixes
        prefix_end_index: Ending index of prefixes
        origin_value: Origin value ("igp", "egp", "incomplete")

    Returns:
        Task object to modify origin value
    """
    return Task(
        task_name="ixia_modify_bgp_prefixes_origin_value",
        ixia_needed=True,
        params=Params(
            json_params=json.dumps(
                {
                    "prefix_pool_regex": prefix_pool_regex,
                    "prefix_start_index": prefix_start_index,
                    "prefix_end_index": prefix_end_index,
                    "origin_value": origin_value,
                }
            )
        ),
    )


def create_ixia_drain_undrain_bgp_peers_task(
    prefix_pool_regex: str,
    as_numbers: t.List[str],
    drain: bool,
) -> Task:
    """
    Create a task to drain/undrain BGP peers on Ixia.

    Args:
        prefix_pool_regex: Regex pattern to match prefix pools
        as_numbers: List of AS numbers to prepend for draining
        drain: Whether to drain (True) or undrain (False)

    Returns:
        Task object to drain/undrain peers
    """
    return Task(
        task_name="ixia_drain_undrain_bgp_peers",
        ixia_needed=True,
        params=Params(
            json_params=json.dumps(
                {
                    "prefix_pool_regex": prefix_pool_regex,
                    "as_numbers": as_numbers,
                    "drain": drain,
                }
            )
        ),
    )


def create_ixia_modify_communities_task(
    prefix_pool_regex: str,
    count: int,
    to_add: bool,
    community_values: t.Optional[t.List[str]] = None,
    broadcast_to_all_slots: bool = False,
) -> Task:
    """
    Create a task to add/remove BGP communities on Ixia (peer-scoped — only
    flaps the BGP peer owning the matched prefix pool, NOT chassis-wide).

    Args:
        prefix_pool_regex: Regex pattern to match prefix pools.
        count: Number of communities to add (when ``to_add=True``) or remove
            (when ``to_add=False``). The peer's ``NoOfCommunities`` is
            incremented/decremented by this amount.
        to_add: Whether to add (True) or remove (False) communities.
        community_values: Optional list of community values in canonical
            ``"<asn>:<value>"`` string form (e.g. ``["65529:99999"]``). When
            provided, the task ALSO writes these specific values onto the
            peer's ``BgpCommunitiesList`` slots starting at index 0, enabling
            a true value-level swap (e.g. swap from ``"65529:34814"`` to
            ``"65529:99999"`` on the same prefix range without resetting
            chassis-wide BGP sessions). When None (default), legacy
            count-only behavior is preserved.
        broadcast_to_all_slots: When True (and ``community_values`` has
            exactly one entry), replicate that single value across ALL
            ``BgpCommunitiesList`` slots on the prefix pool. Needed when the
            IXIA setup seeded the initial community across multiple slots
            per route via ``configure_community_pool`` round-robin (each
            route may carry its initial value in slot 0, 1, 2, ... N), so
            a slot-0-only overwrite leaves stragglers in higher slots. When
            False (default), each entry in ``community_values`` writes to
            its own successive slot (legacy behavior).

    Returns:
        Task object to modify communities
    """
    params: t.Dict[str, t.Any] = {
        "prefix_pool_regex": prefix_pool_regex,
        "count": count,
        "to_add": to_add,
    }
    if community_values is not None:
        params["community_values"] = community_values
    if broadcast_to_all_slots:
        params["broadcast_to_all_slots"] = True
    return Task(
        task_name="ixia_modify_communities",
        ixia_needed=True,
        params=Params(json_params=json.dumps(params)),
    )


def create_arista_daemon_control_task(
    hostname: str,
    daemon_name: str = "Bgp",
    action: str = "enable",
    ixia_needed: bool = False,
) -> Task:
    """
    Create a task to control a daemon on Arista device.

    Args:
        hostname: Hostname of the Arista device
        daemon_name: Name of the daemon (default: "Bgp")
        action: Action to perform ("enable", "disable", "restart")
        ixia_needed: If True, task runs after IXIA setup (default: False).
            BGP++ conveyor configs set this to True so daemon enable runs
            after IXIA peering is established.

    Returns:
        Task object to control daemon
    """
    return Task(
        task_name="arista_daemon_control",
        ixia_needed=ixia_needed,
        params=Params(
            json_params=json.dumps(
                {
                    "hostname": hostname,
                    "daemon_name": daemon_name,
                    "action": action,
                }
            )
        ),
    )


def create_cpu_load_average_task(
    hostname: str,
    threshold: float = 12.0,
    enable_plotting: bool = True,
) -> Task:
    """
    Create a task to check CPU load average.

    Args:
        hostname: Hostname of the device
        threshold: CPU load threshold
        enable_plotting: Whether to enable plotting

    Returns:
        Task object to check CPU load
    """
    return Task(
        task_name="cpu_load_average",
        params=Params(
            json_params=json.dumps(
                {
                    "hostname": hostname,
                    "threshold": threshold,
                    "enable_plotting": enable_plotting,
                }
            )
        ),
    )


def create_counter_utilization_task(
    hostname: str,
    key: str,
    threshold: float,
    enable_plotting: bool = True,
    cpu_count: t.Optional[int] = None,
    fail_on_breach: bool = False,
) -> Task:
    """
    Create a task to check counter utilization.

    Args:
        hostname: Hostname of the device
        key: Counter key to check
        threshold: Utilization threshold
        enable_plotting: Whether to enable plotting
        cpu_count: Optional CPU count for normalization
        fail_on_breach: When True, the task raises the moment a sampled value
            exceeds ``threshold`` mid-run. Combined with the PeriodicTask's
            ``terminate_on_error=True`` this fails the test immediately instead
            of only recording a non-gating final-check result. Left out of the
            serialized params when False to preserve golden byte-equivalence.

    Returns:
        Task object to check counter utilization
    """
    params = {
        "hostname": hostname,
        "key": key,
        "threshold": threshold,
        "enable_plotting": enable_plotting,
    }
    if cpu_count is not None:
        params["cpu_count"] = cpu_count
    if fail_on_breach:
        params["fail_on_breach"] = fail_on_breach

    return Task(
        task_name="counter_utilization",
        params=Params(json_params=json.dumps(params)),
    )


def create_process_monitor_task(
    hostname: str,
    process_filter: t.Optional[t.List[str]] = None,
) -> Task:
    """
    Create a task to monitor processes.

    Args:
        hostname: Hostname of the device
        process_filter: Optional list of process names to filter

    Returns:
        Task object to monitor processes
    """
    params: t.Dict[str, t.Any] = {"hostname": hostname}
    if process_filter is not None:
        params["process_filter"] = process_filter

    return Task(
        task_name="process_monitor",
        params=Params(json_params=json.dumps(params)),
    )


def create_optics_temperature_task(
    hostname: str,
    threshold: t.Optional[float] = None,
) -> Task:
    """
    Create a task to check optics temperature.

    If threshold is not provided, uses per-media-type NGT thresholds
    defined in the OpticsTemperatureTask.

    Args:
        hostname: Hostname of the device
        threshold: Optional explicit temperature threshold in Celsius

    Returns:
        Task object to check optics temperature
    """
    params: t.Dict[str, t.Any] = {
        "hostname": hostname,
    }
    if threshold is not None:
        params["threshold"] = threshold

    return Task(
        task_name="optics_temperature",
        params=Params(json_params=json.dumps(params)),
    )


def create_device_provisioning_task(
    hostname: str,
    provision_params: t.Optional[t.Dict[str, t.Any]] = None,
) -> Task:
    """
    Create a task for device provisioning.

    Args:
        hostname: Hostname of the device
        provision_params: Additional provisioning parameters

    Returns:
        Task object for device provisioning
    """
    params = {"hostname": hostname}
    if provision_params:
        params.update(provision_params)

    return Task(
        task_name="device_provisioning",
        params=Params(json_params=json.dumps(params)),
    )


def create_eos_os_upgrade_task(
    device_name: str,
    netcode_package: str,
    image_file: t.Optional[str] = None,
    expected_version: t.Optional[str] = None,
    skip_if_current: bool = True,
    clear_flash: bool = True,
    stop_after_download: bool = False,
    download_timeout_s: t.Optional[int] = None,
    ssh_wait_s: t.Optional[int] = None,
    warmup_timeout_s: t.Optional[int] = None,
    post_reload_settle_s: t.Optional[int] = None,
    drain: bool = False,
    task_id: t.Optional[str] = None,
) -> Task:
    """Create the `eos_os_upgrade` task: install a netcode SWI on an EOS device.

    Ports the image-swap half of PWM's EOSUpgradePhase. Downloads the named
    netcode package to /mnt/flash, verifies its md5, points boot-config at it,
    reloads, and asserts the device came back on the expected version. Does NOT
    re-run config, chef, optics firmware, or vendor audits — see
    `internal/tasks/eos_os_upgrade_task.py`.

    Args:
        device_name: DUT hostname, e.g. "cpr002.qzp1".
        netcode_package: netcode package to install, e.g.
            "arista_eos_4.36.2f-dpe-ctnr". The package supplies the file name,
            download URL, md5, and version.
        image_file: explicit .swi within the package; only needed when the
            package publishes more than one.
        expected_version: what `show version` should report afterwards.
            Defaults to the netcode Package.version, which does not always
            match the CLI string.
        skip_if_current: when True (default), a device already on the target
            version is a no-op instead of a failure.
        clear_flash: when True (default), clear deletable files from
            /mnt/flash before downloading. That glob includes the running
            image, so pass False when the device has room for both and a
            failed download should be harmless.
        stop_after_download: download and md5-verify, then stop without
            writing boot-config or reloading. Use to prove the download path
            on hardware without changing what the device boots.
        download_timeout_s: per-attempt wget timeout. Task default is 900.
        ssh_wait_s: post-reload SSH wait. Task default is 1800, sized for a
            chassis.
        warmup_timeout_s: EOS `wait-for-warmup` timeout. Task default is 900.
        post_reload_settle_s: bounded settle after `wait-for-warmup` returns,
            before the task hands back to the postchecks. Task default is 180,
            sized for a chassis: warmup reports "agents are up" before the
            linecard ASICs finish initializing, so postchecks that run
            immediately see a device with no links. Pass 0 on a fixed-config
            device, where there is nothing to wait for.
        drain: when True, NDS-drain before upgrading. Requires `task_id`.
        task_id: task number recorded against the drain.

    Returns:
        Task object for the EOS OS upgrade.
    """
    params: t.Dict[str, t.Any] = {
        "device_name": device_name,
        "netcode_package": netcode_package,
        "skip_if_current": skip_if_current,
        "clear_flash": clear_flash,
        "stop_after_download": stop_after_download,
        "drain": drain,
    }
    if image_file is not None:
        params["image_file"] = image_file
    if expected_version is not None:
        params["expected_version"] = expected_version
    if download_timeout_s is not None:
        params["download_timeout_s"] = download_timeout_s
    if ssh_wait_s is not None:
        params["ssh_wait_s"] = ssh_wait_s
    if warmup_timeout_s is not None:
        params["warmup_timeout_s"] = warmup_timeout_s
    # `is not None` rather than a truthiness test: 0 is the meaningful value
    # for a fixed-config device and must still reach the task.
    if post_reload_settle_s is not None:
        params["post_reload_settle_s"] = post_reload_settle_s
    if task_id is not None:
        params["task_id"] = task_id

    return Task(
        task_name="eos_os_upgrade",
        hostname=device_name,
        params=Params(json_params=json.dumps(params)),
    )


def create_eos_compiler_lifecycle_task(
    hostname: str,
    action: str = "physical_apply",
    ixia_needed: bool = False,
    **action_params: object,
) -> Task:
    """Create one backend-owned EOS compiler lifecycle operation."""
    return Task(
        task_name="eos_compiler_lifecycle",
        hostname=hostname,
        ixia_needed=ixia_needed,
        params=Params(
            json_params=json.dumps(
                {"action": action, "hostname": hostname, **action_params},
                sort_keys=True,
            )
        ),
    )


def create_scp_file_task(
    hostname: str,
    source_path: str,
    dest_path: str,
    direction: str = "to_device",
) -> Task:
    """
    Create a task to SCP a file to/from a device.

    Args:
        hostname: Hostname of the device
        source_path: Source file path
        dest_path: Destination file path
        direction: "to_device" or "from_device"

    Returns:
        Task object for SCP operation
    """
    return Task(
        task_name="scp_file",
        params=Params(
            json_params=json.dumps(
                {
                    "hostname": hostname,
                    "source_path": source_path,
                    "dest_path": dest_path,
                    "direction": direction,
                }
            )
        ),
    )


def create_bgp_tcpdump_task(
    hostname: str,
    mode: str,
    interface: str = "any",
    capture_file_path: str = "/tmp/bgp_capture.txt",
    message_type: str = "Update",
) -> Task:
    """
    Create a task to start/stop BGP tcpdump capture.

    Args:
        hostname: Hostname of the device
        mode: "start_capture" or "stop_capture"
        interface: Network interface to capture on
        capture_file_path: Path to save capture file
        message_type: BGP message type to capture

    Returns:
        Task object for tcpdump
    """
    return Task(
        task_name="bgp_tcpdump",
        params=Params(
            json_params=json.dumps(
                {
                    "hostname": hostname,
                    "mode": mode,
                    "interface": interface,
                    "capture_file_path": capture_file_path,
                    "message_type": message_type,
                }
            )
        ),
    )


def create_add_stress_static_routes_task(
    hostname: str,
    route_count: t.Optional[int] = None,
    next_hop: t.Optional[str] = None,
    **extra_params: t.Any,
) -> Task:
    """
    Create a task to add stress static routes.

    Args:
        hostname: Hostname of the device
        route_count: Number of routes to add
        next_hop: Optional next hop address
        **extra_params: Additional parameters to include (e.g.,
            max_ecmp_group, max_ecmp_members, nh_prefix_1,
            lb_prefix_agg, device_group_count)

    Returns:
        Task object to add static routes
    """
    params: t.Dict[str, t.Any] = {
        "hostname": hostname,
    }
    if route_count is not None:
        params["route_count"] = route_count
    if next_hop:
        params["next_hop"] = next_hop
    params.update(extra_params)

    return Task(
        task_name="add_stress_static_routes",
        params=Params(json_params=json.dumps(params)),
    )


def create_replace_bgp_peers_task(
    hostname: str,
    peer_configs: t.List[t.Dict[str, t.Any]],
    ssh_user: str = "admin",
    ssh_password: str = "",
) -> Task:
    """
    Create a task to replace BGP peers.

    Args:
        hostname: Hostname of the device
        peer_configs: List of peer configurations
        ssh_user: SSH username (default: admin)
        ssh_password: SSH password (default: empty)

    Returns:
        Task object to replace BGP peers
    """
    return Task(
        task_name="replace_bgp_peers",
        params=Params(
            json_params=json.dumps(
                {
                    "hostname": hostname,
                    "peer_groups": peer_configs,
                    "ssh_user": ssh_user,
                    "ssh_password": ssh_password,
                }
            )
        ),
    )


def create_replace_bgp_peers_with_groups_task(
    hostname: str,
    peer_groups: t.List[t.Dict[str, t.Any]],
    ssh_user: str,
    ssh_password: str,
    preserve_peer_groups: t.List[str],
) -> Task:
    """
    Create a task to replace BGP peers using the peer-group schema.

    This is the peer-group variant of `create_replace_bgp_peers_task`. The
    runtime `replace_bgp_peers` task accepts both the per-peer (`peer_configs`)
    and per-group (`peer_groups` + ssh creds + `preserve_peer_groups`) schemas
    via duck-typing; this factory targets the latter form.

    Args:
        hostname: Hostname of the device
        peer_groups: List of peer-group configuration dictionaries
        ssh_user: SSH username for device login
        ssh_password: SSH password for device login
        preserve_peer_groups: List of peer-group names to preserve

    Returns:
        Task object to replace BGP peers (peer-group schema)
    """
    return Task(
        task_name="replace_bgp_peers",
        params=Params(
            json_params=json.dumps(
                {
                    "hostname": hostname,
                    "peer_groups": peer_groups,
                    "ssh_user": ssh_user,
                    "ssh_password": ssh_password,
                    "preserve_peer_groups": preserve_peer_groups,
                }
            )
        ),
    )


def create_restore_bgp_peers_task(
    hostname: str,
    ssh_user: str = "admin",
    ssh_password: str = "",
) -> Task:
    """
    Create a task to restore original BGP peers.

    Args:
        hostname: Hostname of the device
        ssh_user: SSH username (default: admin)
        ssh_password: SSH password (default: empty)

    Returns:
        Task object to restore BGP peers
    """
    return Task(
        task_name="restore_bgp_peers",
        params=Params(
            json_params=json.dumps(
                {
                    "hostname": hostname,
                    "ssh_user": ssh_user,
                    "ssh_password": ssh_password,
                }
            )
        ),
    )


def create_allocate_cgroup_slice_memory_task(
    hostname: str,
    memory_limit_gb: t.Optional[int] = None,
    slice_name: str = "bgp",
    run_post_ixia_setup: bool = False,
    **extra_params: t.Any,
) -> Task:
    """
    Create a task to allocate cgroup slice memory.

    Args:
        hostname: Hostname of the device
        memory_limit_gb: Memory limit in GB
        slice_name: Name of the cgroup slice
        run_post_ixia_setup: Whether to run this task post IXIA setup
        **extra_params: Additional parameters (e.g.,
            workload_slice_based_total_memory_decimal)

    Returns:
        Task object to allocate memory
    """
    params: t.Dict[str, t.Any] = {
        "hostname": hostname,
        "slice_name": slice_name,
    }
    if memory_limit_gb is not None:
        params["memory_limit_gb"] = memory_limit_gb
    params.update(extra_params)

    return Task(
        task_name="allocate_cgroup_slice_memory",
        params=Params(json_params=json.dumps(params)),
        run_post_ixia_setup=run_post_ixia_setup,
    )


# =============================================================================
# TASK LIST BUILDERS - Create lists of related tasks
# =============================================================================


def create_standard_setup_tasks(
    hostnames: t.List[str],
    config_name: str = "bgpcpp",
) -> t.List[Task]:
    """
    Create standard setup tasks for test configurations.

    Args:
        hostnames: List of hostnames to setup
        config_name: Config type to apply

    Returns:
        List of setup tasks [unregister, apply]
    """
    return [
        create_coop_unregister_patchers_task(hostnames),
    ]


def create_standard_teardown_tasks(
    hostnames: t.List[str],
) -> t.List[Task]:
    """
    Create standard teardown tasks for test configurations.

    Args:
        hostnames: List of hostnames to cleanup

    Returns:
        List of teardown tasks
    """
    return [
        create_coop_unregister_patchers_task(hostnames),
    ]


def create_bgp_peer_group_patcher_task(
    hostname: str,
    peer_group_name: str,
    patcher_name: str,
    attributes_to_update: t.Dict[str, str],
) -> Task:
    """
    Create a task to configure a BGP peer group.

    Args:
        hostname: Hostname of the device
        peer_group_name: Name of the peer group
        patcher_name: Name for the patcher
        attributes_to_update: Dictionary of attributes to update

    Returns:
        Task object to configure peer group
    """
    return create_coop_register_patcher_task(
        hostname=hostname,
        config_name="bgpcpp",
        patcher_name=patcher_name,
        task_name="configure_bgp_peer_group",
        patcher_args={
            "name": peer_group_name,
            "attributes_to_update_json": json.dumps(attributes_to_update),
        },
    )


def create_bgp_switch_limit_patcher_task(
    hostname: str,
    prefix_limit: int,
    patcher_name: str = "configure_bgp_switch_limit",
) -> Task:
    """
    Create a task to configure BGP switch prefix limit.

    Args:
        hostname: Hostname of the device
        prefix_limit: Prefix limit value
        patcher_name: Name for the patcher

    Returns:
        Task object to configure switch limit
    """
    return create_coop_register_patcher_task(
        hostname=hostname,
        config_name="bgpcpp",
        patcher_name=patcher_name,
        task_name="configure_bgp_switch_limit",
        patcher_args={"prefix_limit": str(prefix_limit)},
        py_func_name="configure_bgp_switch_limit",
    )


def create_remove_bgp_peers_patcher_task(
    hostname: str,
    delete_all: bool = True,
    patcher_name: str = "a_remove_bgp_peers",
) -> Task:
    """
    Create a task to remove BGP peers.

    Args:
        hostname: Hostname of the device
        delete_all: Whether to delete all peers
        patcher_name: Name for the patcher

    Returns:
        Task object to remove peers
    """
    return create_coop_register_patcher_task(
        hostname=hostname,
        config_name="bgpcpp",
        patcher_name=patcher_name,
        task_name="remove_bgp_peers",
        patcher_args={"delete_all": str(delete_all)},
    )


def create_change_port_vlan_patcher_task(
    hostname: str,
    port_id: str,
    vlan_id: str,
    patcher_name: str,
) -> Task:
    """
    Create a task to change port VLAN.

    Args:
        hostname: Hostname of the device
        port_id: Port ID to change
        vlan_id: Target VLAN ID
        patcher_name: Name for the patcher

    Returns:
        Task object to change VLAN
    """
    return create_coop_register_patcher_task(
        hostname=hostname,
        config_name="agent",
        patcher_name=patcher_name,
        task_name="change_port_vlan",
        patcher_args={port_id: vlan_id},
    )


def create_allow_all_v4_peer_group_patcher_tasks(
    hostname: str,
    peer_group_name: str,
    peer_tag: str,
    is_confed_peer: str = "False",
    per_peer_max_route_limit: str = "25000",
    policy_entries_json: str = "[]",
) -> t.List[Task]:
    """
    Create tasks to add a V4 BGP peer group with allow-all ingress/egress policies.

    Args:
        hostname: Hostname of the device
        peer_group_name: Name of the peer group (e.g., "PEERGROUP_RB_XSW_V4")
        peer_tag: Peer tag (e.g., "XSW", "RB")
        is_confed_peer: Whether peer is confederation peer
        per_peer_max_route_limit: Max routes per peer
        policy_entries_json: JSON-serialized policy entries for the allow-all policy

    Returns:
        List of tasks to register the allow-all peer group
    """
    ingress_policy = f"PROPAGATE_EVERYTHING_{peer_group_name}_IN"
    egress_policy = f"PROPAGATE_EVERYTHING_{peer_group_name}_OUT"

    return [
        create_coop_register_patcher_task(
            hostname=hostname,
            config_name="bgpcpp",
            patcher_name=f"a_add_bgp_policy_statement_{ingress_policy}",
            task_name="coop_register_patcher",
            patcher_args={
                "name": ingress_policy,
                "description": f"Allow all ingress for {peer_group_name}",
                "policy_entries": policy_entries_json,
            },
            py_func_name="add_bgp_policy_statement",
        ),
        create_coop_register_patcher_task(
            hostname=hostname,
            config_name="bgpcpp",
            patcher_name=f"a_add_bgp_policy_statement_{egress_policy}",
            task_name="coop_register_patcher",
            patcher_args={
                "name": egress_policy,
                "description": f"Allow all egress for {peer_group_name}",
                "policy_entries": policy_entries_json,
            },
            py_func_name="add_bgp_policy_statement",
        ),
        create_coop_register_patcher_task(
            hostname=hostname,
            config_name="bgpcpp",
            patcher_name=f"a_add_peer_group_patcher_{peer_group_name}",
            task_name="coop_register_patcher",
            patcher_args={
                "name": peer_group_name,
                "description": f"Peergroup for {peer_tag}-{peer_tag} iBGP peering, IPv4 sessions",
                "next_hop_self": "True",
                "disable_ipv4_afi": "False",
                "disable_ipv6_afi": "True",
                "is_confed_peer": is_confed_peer,
                "peer_tag": peer_tag,
                "ingress_policy_name": ingress_policy,
                "egress_policy_name": egress_policy,
                "bgp_peer_timers_hold_time_seconds": "15",
                "bgp_peer_timers_keep_alive_seconds": "5",
                "bgp_peer_timers_out_delay_seconds": "2",
                "bgp_peer_timers_withdraw_unprog_delay_seconds": "0",
                "max_routes": per_peer_max_route_limit,
                "warning_only": "True",
                "warning_limit": "0",
                "link_bandwidth_bps": "auto",
                "v4_over_v6_nexthop": "False",
                "is_passive": "False",
            },
            py_func_name="add_peer_group_patcher",
        ),
    ]


# =============================================================================
# PERIODIC TASK BUILDERS - Create lists of periodic tasks
# =============================================================================


def create_standard_periodic_tasks(
    device_name: str,
    cpu_load_threshold: float = 12.0,
    cpu_util_threshold: float = 40.0,
    memory_threshold: int = Gigabyte.GIG_10.value,
    interval: int = 60,
    cpu_load_terminate_on_error: bool = False,
    cpu_util_terminate_on_error: bool = False,
    memory_terminate_on_error: bool = False,
    cpu_count: t.Optional[int] = ARISTA_7808_CPU_COUNT,
    enable_process_monitor: bool = True,
    process_filter: t.Optional[t.List[str]] = None,
    process_monitor_interval: int = 5,
    enable_queue_backpressure_monitor: bool = True,
) -> t.List[taac_types.PeriodicTask]:
    """
    Create standard periodic tasks for monitoring during tests.

    Args:
        device_name: Name of the device to monitor
        cpu_load_threshold: CPU load average threshold
        cpu_util_threshold: CPU utilization percentage threshold
        memory_threshold: Memory utilization threshold in bytes
        interval: Interval between checks in seconds
        cpu_load_terminate_on_error: Whether to terminate test on CPU load errors
        cpu_util_terminate_on_error: Whether to terminate test on CPU util errors
        memory_terminate_on_error: Whether to terminate test on memory errors
        cpu_count: CPU count for normalization
        enable_process_monitor: Whether to enable process monitoring
        process_filter: Optional list of process names to monitor
        process_monitor_interval: Interval for process monitoring
        enable_queue_backpressure_monitor: Whether to poll BGP++ egress-queue
            backpressure counters (permissive, observe-only). Generic bgpd
            health signal, like CPU/memory; the poll no-ops on daemons that do
            not implement getPeerEgressStats.

    Returns:
        List of standard periodic monitoring tasks
    """
    tasks = [
        taac_types.PeriodicTask(
            name="bgpd_cpu_load_average_check",
            interval=interval,
            task=create_cpu_load_average_task(
                hostname=device_name,
                threshold=cpu_load_threshold,
                enable_plotting=True,
            ),
            retryable=False,
            terminate_on_error=cpu_load_terminate_on_error,
        ),
        taac_types.PeriodicTask(
            name="bgpd_cpu_util_check",
            interval=interval,
            task=create_counter_utilization_task(
                hostname=device_name,
                key="bgpd.process.cpu.percent",
                threshold=cpu_util_threshold,
                enable_plotting=True,
                cpu_count=cpu_count,
            ),
            retryable=False,
            terminate_on_error=cpu_util_terminate_on_error,
        ),
        taac_types.PeriodicTask(
            name="bgpd_mem_util_check",
            interval=interval,
            task=create_counter_utilization_task(
                hostname=device_name,
                key="bgpd.process.memory.rss.bytes",
                threshold=memory_threshold,
                enable_plotting=True,
                fail_on_breach=memory_terminate_on_error,
            ),
            retryable=False,
            terminate_on_error=memory_terminate_on_error,
        ),
    ]

    if enable_process_monitor:
        tasks.append(
            taac_types.PeriodicTask(
                name="process_monitor_check",
                interval=process_monitor_interval,
                task=create_process_monitor_task(
                    hostname=device_name,
                    process_filter=process_filter,
                ),
                retryable=False,
                terminate_on_error=False,
            )
        )

    if enable_queue_backpressure_monitor:
        # Generic bgpd health signal alongside CPU/memory: observe egress-queue
        # backpressure (cumulative block-count delta) under load. Permissive
        # (terminate_on_error defaults False); no-ops if getPeerEgressStats is
        # unavailable on the daemon.
        tasks.append(create_bgp_queue_backpressure_poll_periodic_task(device_name))

    return tasks


# =============================================================================
# INTERFACE IP CONFIGURATION TASK FACTORIES
# =============================================================================


def create_interface_ip_configuration_task(
    interface: str,
    peer_count: int,
    ipv4_base_network: t.Optional[str] = None,
    ipv6_base_network: t.Optional[str] = None,
    address_families: t.Optional[t.List[str]] = None,
    clear_existing: bool = True,
    ipv4_start_offset: int = 10,
    ipv6_start_offset: int = 0x10,
    task_name: t.Optional[str] = None,
    ixia_needed: bool = False,
    hostname: t.Optional[str] = None,
    all_secondary: t.Optional[bool] = None,
    save_running_config_backup: bool = True,
) -> Task:
    """
    Create a task to configure secondary IP addresses on an Arista interface.

    This task is useful for tests requiring many BGP peers (e.g., 140+ EBGP peers,
    500+ IBGP peers), where manual IP configuration is error-prone.

    Args:
        interface: Interface name (e.g., "Ethernet3/1/1")
        peer_count: Number of BGP peers (determines IP address count)
        ipv4_base_network: IPv4 base network (e.g., "10.163.28")
        ipv6_base_network: IPv6 base network (e.g., "2401:db00:e50d:11:8")
        address_families: List of address families (["ipv4"], ["ipv6"], or both).
                         Defaults to ["ipv6"] if not specified.
        clear_existing: Clear existing IPs before configuring (default: True)
        ipv4_start_offset: Starting offset for IPv4 addresses (default: 10)
        ipv6_start_offset: Starting offset for IPv6 addresses (default: 0x10)
        task_name: Custom task name (default: "configure_<interface>_ips")
        save_running_config_backup: Save the full running configuration before
            changing the interface. Disable this when teardown removes the
            interface addresses directly.

    Returns:
        Task object for interface IP configuration
    """
    if address_families is None:
        address_families = ["ipv6"]

    params: t.Dict[str, t.Any] = {
        "interface": interface,
        "peer_count": peer_count,
        "address_families": address_families,
        "clear_existing": clear_existing,
        "ipv4_start_offset": ipv4_start_offset,
        "ipv6_start_offset": ipv6_start_offset,
    }

    if ipv4_base_network is not None:
        params["ipv4_base_network"] = ipv4_base_network
    if ipv6_base_network is not None:
        params["ipv6_base_network"] = ipv6_base_network
    if all_secondary is not None:
        params["all_secondary"] = all_secondary
    if not save_running_config_backup:
        params["save_running_config_backup"] = False

    # Generate default task name from interface if not provided
    if task_name is None:
        # Convert "Ethernet3/25/1" to "configure_et3_25_1_ips"
        interface_short = interface.replace("Ethernet", "et").replace("/", "_")
        task_name = f"configure_{interface_short}_ips"

    return Task(
        task_name="interface_ip_configuration",
        ixia_needed=ixia_needed,
        hostname=hostname,
        params=Params(json_params=json.dumps(params)),
    )


def create_interface_ip_cleanup_task(
    interfaces: t.List[str],
    restore_from_backup: bool = True,
    keep_primary: bool = False,
    delete_backup: bool = True,
    task_name: t.Optional[str] = None,
    hostname: t.Optional[str] = None,
) -> Task:
    """
    Create a task to clean up secondary IP addresses from interfaces.

    Can either restore from backup (recommended) or manually remove IPs.

    Args:
        interfaces: List of interface names to clean up (e.g., ["Ethernet3/1/1"])
        restore_from_backup: If True, restore config from backup (recommended).
                            Uses backup saved by InterfaceIpConfigurationTask.
        keep_primary: If True, only remove secondary IPs (ignored if restore_from_backup)
        delete_backup: If True, delete backup file after restore (default: True)
        task_name: Custom task name (default: "cleanup_<first_interface>_ips")

    Returns:
        Task object for interface IP cleanup
    """
    params: t.Dict[str, t.Any] = {
        "interfaces": interfaces,
    }

    if restore_from_backup:
        params["restore_from_backup"] = True
        params["delete_backup"] = delete_backup
    else:
        params["keep_primary"] = keep_primary

    # Generate default task name from first interface if not provided
    if task_name is None:
        first_interface = interfaces[0] if interfaces else "unknown"
        interface_short = first_interface.replace("Ethernet", "et").replace("/", "_")
        task_name = f"cleanup_{interface_short}_ips"

    return Task(
        task_name="interface_ip_cleanup",
        hostname=hostname,
        params=Params(json_params=json.dumps(params)),
    )


def create_deploy_tls_certs_task(
    hostname: str,
    cert_dir: str = "/mnt/fb/certs",
    cert_names: t.Optional[t.List[str]] = None,
) -> Task:
    """
    Create a task to generate self-signed TLS certs for BGP++ daemons.

    FibAgent and BGP++ require TLS certs at specific paths. On test
    devices these may not exist, so this task generates a self-signed
    cert and copies it to the required paths.

    Args:
        hostname: Device hostname
        cert_dir: Directory to store certs (default: "/mnt/fb/certs")
        cert_names: List of cert filenames (default:
            ["AristaFibAgent_server.pem", "Bgpcpp_server.pem"])

    Returns:
        Task object for cert deployment
    """
    from taac.utils.arista_utils import (
        generate_self_signed_tls_certs_commands,
    )

    cmds = generate_self_signed_tls_certs_commands(
        cert_dir=cert_dir,
        cert_names=cert_names,
    )
    return create_run_commands_on_shell_task(
        hostname=hostname,
        cmds=cmds,
        ixia_needed=True,
    )


def create_configure_bgpcpp_startup_task(
    hostname: str,
    flags: t.Dict[str, str],
    ssh_user: t.Optional[str] = None,
    ssh_password: t.Optional[str] = None,
    restart_bgp: bool = False,
    use_managed_shell: bool = False,
    set_outer_hostname: bool = False,
    ixia_needed: bool = False,
) -> Task:
    """
    Create a task to configure bgpcpp startup flags on a device.

    This task modifies the /usr/sbin/run_bgpcpp.sh script to add or update
    bgpcpp startup flags. Changes are idempotent.

    Args:
        hostname: Name of the device to configure
        flags: Dictionary of startup flags to set
               (e.g., {"agent_thrift_recv_timeout_ms": "160000"})
        ssh_user: SSH username for the device
        ssh_password: SSH password for the device
        restart_bgp: Whether to restart BGP daemon after applying (default: False)
        use_managed_shell: If True, apply the flag edits over the managed device
            driver (async shell) instead of raw SSH. Use for pipelines that run
            under a netcastle reservation and pass no SSH credentials (e.g. the
            perf-scaling sweep). The caller must restart BGP separately.
        set_outer_hostname: If True, also set Task.hostname (the outer Thrift
            field) for runner-side scoping, matching sibling managed setup tasks.
        ixia_needed: If True, the task runs after IXIA setup with the device
            driver ready, for phasing parity with sibling managed setup tasks.

    Returns:
        Task object for configuring bgpcpp startup
    """
    params: t.Dict[str, t.Any] = {
        "hostname": hostname,
        "flags": flags,
    }
    if ssh_user is not None:
        params["ssh_user"] = ssh_user
    if ssh_password is not None:
        params["ssh_password"] = ssh_password
    if restart_bgp:
        params["restart_bgp"] = restart_bgp
    if use_managed_shell:
        params["use_managed_shell"] = use_managed_shell

    # Only set the outer Task fields when requested so existing raw-SSH callers
    # produce byte-identical Tasks (no golden manifest churn).
    task_kwargs: t.Dict[str, t.Any] = {
        "task_name": "configure_bgpcpp_startup",
        "params": Params(json_params=json.dumps(params)),
    }
    if set_outer_hostname:
        task_kwargs["hostname"] = hostname
    if ixia_needed:
        task_kwargs["ixia_needed"] = ixia_needed

    return Task(**task_kwargs)


def create_inject_bgp_policy_statements_task(
    hostname: str,
    config_path: str,
    config_name: str = "bgpcpp",
) -> Task:
    """
    Create a task to inject BGP policy statements into a device.

    This task fetches BGP policy statements from configerator or directly from
    a file and applies them to the specified device using the
    add_bgp_policy_statement patcher.

    Args:
        hostname: Name of the device to inject policies into
        config_path: Path to the policy config file
                     (e.g., "taac/test_bgp_policies/ebb_policy_in_fboss_format.json")
        config_name: Config type (default: "bgpcpp")

    Returns:
        Task object for injecting BGP policy statements
    """
    return Task(
        task_name="inject_bgp_policy_statements",
        params=Params(
            json_params=json.dumps(
                {
                    "hostname": hostname,
                    "config_path": config_path,
                    "config_name": config_name,
                }
            )
        ),
    )


def create_cpu_only_periodic_tasks(
    device_name: str,
    cpu_load_threshold: float = 12.0,
    interval: int = 60,
    terminate_on_error: bool = True,
) -> t.List[taac_types.PeriodicTask]:
    """
    Create CPU load monitoring only periodic tasks.

    Args:
        device_name: Name of the device to monitor
        cpu_load_threshold: CPU load average threshold
        interval: Interval between checks in seconds
        terminate_on_error: Whether to terminate test on CPU load errors

    Returns:
        List containing single CPU load periodic task
    """
    return [
        taac_types.PeriodicTask(
            name="cpu_load_check",
            interval=interval,
            task=create_cpu_load_average_task(
                hostname=device_name,
                threshold=cpu_load_threshold,
                enable_plotting=True,
            ),
            retryable=False,
            terminate_on_error=terminate_on_error,
        )
    ]


def _create_route_churn_task(
    route_churn_frequency: int,
    route_churn_prefix_pool_regex: str,
    route_churn_prefix_start_index: int,
    route_churn_prefix_end_index: int,
) -> taac_types.PeriodicTask:
    return taac_types.PeriodicTask(
        name="advertise_withdraw_prefixes",
        interval=route_churn_frequency,
        task=Task(task_name="ixia_enable_disable_bgp_prefixes", ixia_needed=True),
        params_list=[
            Params(
                json_params=json.dumps(
                    {
                        "enable": False,
                        "prefix_pool_regex": route_churn_prefix_pool_regex,
                        "prefix_start_index": route_churn_prefix_start_index,
                        "prefix_end_index": route_churn_prefix_end_index,
                    }
                )
            ),
            Params(
                json_params=json.dumps(
                    {
                        "enable": True,
                        "prefix_pool_regex": route_churn_prefix_pool_regex,
                        "prefix_start_index": route_churn_prefix_start_index,
                        "prefix_end_index": route_churn_prefix_end_index,
                    }
                )
            ),
        ],
    )


def _create_local_pref_churn_task(
    local_pref_churn_frequency: int,
    local_pref_prefix_pool_regex: str,
    local_pref_churn_prefix_start_index: int,
    local_pref_churn_prefix_end_index: int,
    local_pref_start: int,
    local_pref_end: int,
) -> taac_types.PeriodicTask:
    return taac_types.PeriodicTask(
        name="local_pref_churn",
        interval=local_pref_churn_frequency,
        task=Task(
            task_name="ixia_randomize_bgp_prefix_local_preference",
            ixia_needed=True,
        ),
        params_list=[
            Params(
                json_params=json.dumps(
                    {
                        "prefix_pool_regex": local_pref_prefix_pool_regex,
                        "prefix_start_index": local_pref_churn_prefix_start_index,
                        "prefix_end_index": local_pref_churn_prefix_end_index,
                        "start_value": local_pref_start,
                        "end_value": local_pref_end,
                    }
                )
            ),
        ],
    )


def _create_as_path_drain_task(
    as_path_drain_frequency: int,
    as_path_drain_prefix_pool_regex: str,
    as_path_drain_as_numbers: t.List[str],
) -> taac_types.PeriodicTask:
    return taac_types.PeriodicTask(
        name="as_path_drain_undrain",
        interval=as_path_drain_frequency,
        task=Task(task_name="ixia_drain_undrain_bgp_peers", ixia_needed=True),
        params_list=[
            Params(
                json_params=json.dumps(
                    {
                        "prefix_pool_regex": as_path_drain_prefix_pool_regex,
                        "as_numbers": as_path_drain_as_numbers,
                        "drain": True,
                    }
                )
            ),
            Params(
                json_params=json.dumps(
                    {
                        "prefix_pool_regex": as_path_drain_prefix_pool_regex,
                        "as_numbers": as_path_drain_as_numbers,
                        "drain": False,
                    }
                )
            ),
        ],
    )


def _create_origin_churn_task(
    origin_churn_frequency: int,
    origin_prefix_pool_regex: str,
    origin_prefix_start_index: int,
    origin_prefix_end_index: int,
) -> taac_types.PeriodicTask:
    return taac_types.PeriodicTask(
        name="origin_churn",
        interval=origin_churn_frequency,
        task=Task(task_name="ixia_modify_bgp_prefixes_origin_value", ixia_needed=True),
        params_list=[
            Params(
                json_params=json.dumps(
                    {
                        "prefix_pool_regex": origin_prefix_pool_regex,
                        "prefix_start_index": origin_prefix_start_index,
                        "prefix_end_index": origin_prefix_end_index,
                        "origin_value": "incomplete",
                    }
                )
            ),
            Params(
                json_params=json.dumps(
                    {
                        "prefix_pool_regex": origin_prefix_pool_regex,
                        "prefix_start_index": origin_prefix_start_index,
                        "prefix_end_index": origin_prefix_end_index,
                        "origin_value": "egp",
                    }
                )
            ),
            Params(
                json_params=json.dumps(
                    {
                        "prefix_pool_regex": origin_prefix_pool_regex,
                        "prefix_start_index": origin_prefix_start_index,
                        "prefix_end_index": origin_prefix_end_index,
                        "origin_value": "igp",
                    }
                )
            ),
        ],
    )


def _create_community_churn_task(
    community_churn_frequency: int,
    community_prefix_pool_regex: str,
    community_count: int,
) -> taac_types.PeriodicTask:
    return taac_types.PeriodicTask(
        name="community_add_remove",
        interval=community_churn_frequency,
        task=Task(task_name="ixia_modify_communities", ixia_needed=True),
        params_list=[
            Params(
                json_params=json.dumps(
                    {
                        "prefix_pool_regex": community_prefix_pool_regex,
                        "count": community_count,
                        "to_add": True,
                    }
                )
            ),
            Params(
                json_params=json.dumps(
                    {
                        "prefix_pool_regex": community_prefix_pool_regex,
                        "count": community_count,
                        "to_add": False,
                    }
                )
            ),
        ],
    )


def _create_igp_cost_task(
    device_name: str,
    igp_cost_frequency: int,
    start_ipv4s: t.List[str],
    start_ipv6s: t.List[str],
    local_link: t.Dict[str, t.Any],
    other_link: t.Dict[str, t.Any],
    count: int,
    update_count: int,
) -> taac_types.PeriodicTask:
    return taac_types.PeriodicTask(
        name="igp_cost_fluctuation",
        interval=igp_cost_frequency,
        task=Task(task_name="openr_route_action"),
        params_list=[
            Params(
                json_params=json.dumps(
                    {
                        "hostname": device_name,
                        "action": "update",
                        "start_ipv4s": start_ipv4s,
                        "start_ipv6": start_ipv6s,
                        "local_link": local_link,
                        "other_link": other_link,
                        "count": count,
                        "update_count": update_count,
                    }
                )
            ),
        ],
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
    as_path_drain_as_numbers: t.Optional[t.List[str]] = None,
    origin_churn_frequency: int = 60,
    origin_prefix_pool_regex: str = ".*IBGP.*PLANE_3.*",
    origin_prefix_start_index: int = 0,
    origin_prefix_end_index: int = 20,
    community_churn_frequency: int = 60,
    community_prefix_pool_regex: str = ".*IBGP.*PLANE_4.*",
    community_count: int = 5,
    igp_cost_frequency: int = 60,
    start_ipv4s: t.Optional[t.List[str]] = None,
    start_ipv6s: t.Optional[t.List[str]] = None,
    local_link: t.Optional[t.Dict[str, t.Any]] = None,
    other_link: t.Optional[t.Dict[str, t.Any]] = None,
    count: int = 63,
    update_count: int = 50,
    restart_peers_frequency: int = 3600,
    restart_peers_ebgp_regex: str = ".*EBGP.*",
    restart_peers_ebgp_session_num: int = 8,
    restart_peers_ibgp_regex: str = ".*IBGP.*",
    restart_peers_ibgp_session_num: int = 2,
) -> t.List[taac_types.PeriodicTask]:
    """
    Create longevity test periodic tasks for route churn and instability testing.

    Args:
        device_name: Name of the device
        Various parameters for configuring different churn patterns

    Returns:
        List of longevity periodic tasks
    """
    tasks: t.List[taac_types.PeriodicTask] = []

    # Route Churn Task
    if route_churn_frequency > 0:
        tasks.append(
            _create_route_churn_task(
                route_churn_frequency=route_churn_frequency,
                route_churn_prefix_pool_regex=route_churn_prefix_pool_regex,
                route_churn_prefix_start_index=route_churn_prefix_start_index,
                route_churn_prefix_end_index=route_churn_prefix_end_index,
            )
        )

    # Local Pref Churn Task
    if local_pref_churn_frequency > 0:
        tasks.append(
            _create_local_pref_churn_task(
                local_pref_churn_frequency=local_pref_churn_frequency,
                local_pref_prefix_pool_regex=local_pref_prefix_pool_regex,
                local_pref_churn_prefix_start_index=local_pref_churn_prefix_start_index,
                local_pref_churn_prefix_end_index=local_pref_churn_prefix_end_index,
                local_pref_start=local_pref_start,
                local_pref_end=local_pref_end,
            )
        )

    # AS Path Drain Task
    if as_path_drain_frequency > 0:
        if as_path_drain_as_numbers is None:
            as_path_drain_as_numbers = ["65099"]
        tasks.append(
            _create_as_path_drain_task(
                as_path_drain_frequency=as_path_drain_frequency,
                as_path_drain_prefix_pool_regex=as_path_drain_prefix_pool_regex,
                as_path_drain_as_numbers=as_path_drain_as_numbers,
            )
        )

    # Origin Churn Task
    if origin_churn_frequency > 0:
        tasks.append(
            _create_origin_churn_task(
                origin_churn_frequency=origin_churn_frequency,
                origin_prefix_pool_regex=origin_prefix_pool_regex,
                origin_prefix_start_index=origin_prefix_start_index,
                origin_prefix_end_index=origin_prefix_end_index,
            )
        )

    # Community add/remove Task
    if community_churn_frequency > 0:
        tasks.append(
            _create_community_churn_task(
                community_churn_frequency=community_churn_frequency,
                community_prefix_pool_regex=community_prefix_pool_regex,
                community_count=community_count,
            )
        )

    # IGP Cost Fluctuation Task
    if igp_cost_frequency > 0:
        if start_ipv4s is None:
            start_ipv4s = DEFAULT_OPENR_START_IPV4S
        if start_ipv6s is None:
            start_ipv6s = DEFAULT_OPENR_START_IPV6S
        if local_link is None:
            local_link = DEFAULT_LOCAL_LINK
        if other_link is None:
            other_link = DEFAULT_OTHER_LINK

        tasks.append(
            _create_igp_cost_task(
                device_name=device_name,
                igp_cost_frequency=igp_cost_frequency,
                start_ipv4s=start_ipv4s,
                start_ipv6s=start_ipv6s,
                local_link=local_link,
                other_link=other_link,
                count=count,
                update_count=update_count,
            )
        )

    # Restart Peers Tasks
    if restart_peers_frequency > 0:
        if restart_peers_ebgp_session_num > 0:
            tasks.append(
                taac_types.PeriodicTask(
                    name="restart_ebgp_peers",
                    interval=restart_peers_frequency,
                    task=Task(task_name="ixia_restart_bgp_sessions", ixia_needed=True),
                    params_list=[
                        Params(
                            json_params=json.dumps(
                                {
                                    "bgp_peer_regex": restart_peers_ebgp_regex,
                                    "random_session_num": restart_peers_ebgp_session_num,
                                }
                            )
                        ),
                    ],
                ),
            )
        if restart_peers_ibgp_session_num > 0:
            tasks.append(
                taac_types.PeriodicTask(
                    name="restart_ibgp_peers",
                    interval=restart_peers_frequency,
                    task=Task(task_name="ixia_restart_bgp_sessions", ixia_needed=True),
                    params_list=[
                        Params(
                            json_params=json.dumps(
                                {
                                    "bgp_peer_regex": restart_peers_ibgp_regex,
                                    "random_session_num": restart_peers_ibgp_session_num,
                                }
                            )
                        ),
                    ],
                ),
            )

    return tasks


# =============================================================================
# CPU STRESS TASK FACTORIES
# =============================================================================

CPU_STRESS_REMOTE_PATH = "/tmp/cpu_stress.py"

CPU_STRESS_SCRIPT = (
    "#!/usr/bin/env python3\n"
    "import sys, time\n"
    "def n2_compute(n):\n"
    "    total = 0\n"
    "    for i in range(n):\n"
    "        for j in range(n):\n"
    "            total += (i * j) % 997\n"
    "    return total\n"
    "if __name__ == '__main__':\n"
    "    n = int(sys.argv[1]) if len(sys.argv) > 1 else 5000\n"
    "    duration = int(sys.argv[2]) if len(sys.argv) > 2 else 0\n"
    "    start = time.time()\n"
    "    iteration = 0\n"
    "    while True:\n"
    "        n2_compute(n)\n"
    "        iteration += 1\n"
    "        elapsed = time.time() - start\n"
    "        if duration > 0 and elapsed >= duration:\n"
    "            break\n"
    "        if duration == 0:\n"
    "            break\n"
)


def create_cpu_stress_setup_tasks(
    hostname: str,
    n: int = 5000,
    duration_seconds: int = 300,
) -> t.List[Task]:
    """
    Create tasks to deploy and launch a CPU stress script on a device.

    Writes an O(N^2) computation script via chunked base64 transfer
    (to avoid EOS CLI line-length limits) and launches it in the background.

    Args:
        hostname: Device hostname
        n: Matrix size for O(N^2) computation (default: 5000)
        duration_seconds: How long to run the stress in seconds (default: 300)

    Returns:
        List containing a single run_commands_on_shell Task
    """
    b64 = base64.b64encode(CPU_STRESS_SCRIPT.encode()).decode()

    chunk_size = 120
    chunks = [b64[i : i + chunk_size] for i in range(0, len(b64), chunk_size)]
    cmds = []
    for i, chunk in enumerate(chunks):
        op = ">" if i == 0 else ">>"
        cmds.append(f"bash echo '{chunk}' {op} /tmp/cpu_stress.b64")
    cmds.append(f"bash base64 -d /tmp/cpu_stress.b64 > {CPU_STRESS_REMOTE_PATH}")
    cmds.append("bash rm -f /tmp/cpu_stress.b64")
    cmds.append(f"bash chmod +x {CPU_STRESS_REMOTE_PATH}")
    cmds.append(
        f"bash sudo su\n"
        f"nohup python3 {CPU_STRESS_REMOTE_PATH} {n} {duration_seconds}"
        f" > /tmp/cpu_stress.log 2>&1 &\n"
        f"exit"
    )
    return [
        Task(
            task_name="run_commands_on_shell",
            params=Params(json_params=json.dumps({"hostname": hostname, "cmds": cmds})),
        ),
    ]


def create_cpu_stress_teardown_task(hostname: str) -> Task:
    """Create a task to stop the CPU stress script on a device.

    Pairs with `create_cpu_stress_setup_tasks` — kills any running
    `/tmp/cpu_stress.py` process via `pkill` and removes the script file from
    `/tmp/`. Safe to call even if the script is no longer running (uses
    `|| true` to ignore pkill failure).

    Args:
        hostname: Device hostname where the stress script was deployed.

    Returns:
        A `Task` with `task_name="run_commands_on_shell"` that issues the
        teardown shell commands.
    """
    return Task(
        task_name="run_commands_on_shell",
        params=Params(
            json_params=json.dumps(
                {
                    "hostname": hostname,
                    "cmds": [
                        f"bash sudo su\npkill -f {CPU_STRESS_REMOTE_PATH} || true\nexit",
                        f"bash rm -f {CPU_STRESS_REMOTE_PATH}",
                    ],
                }
            )
        ),
    )


def create_deploy_exabgp_task(
    hostname: str,
    remote_path: str = "/tmp/exabgpd.par",
    fbpkg_name: str = "exabgp",
) -> Task:
    """Deploy ExaBGP PAR file from fbpkg to a FBOSS device.

    Fetches the exabgp fbpkg on the test runner, then SCPs the
    exabgpd.par binary to the device via Paramiko SFTP.
    """
    return Task(
        task_name="deploy_exabgp",
        params=Params(
            json_params=json.dumps(
                {
                    "hostname": hostname,
                    "remote_path": remote_path,
                    "fbpkg_name": fbpkg_name,
                }
            )
        ),
    )


def create_ixia_preflight_task(
    chassis_hostname: str,
    max_cpu: float = 80.0,
    max_memory: float = 80.0,
    max_sessions: int = 8,
    test_ports: t.Optional[t.List[str]] = None,
) -> Task:
    """Pre-flight health check for an IXIA chassis.

    Runs before IXIA session setup to validate the chassis is healthy.
    Fails the test early if the chassis is down, has no active cards,
    or has active CRC errors on ports used by the test.
    Warns (but continues) if CPU/memory is high or too many sessions exist.

    Args:
        chassis_hostname: IXIA chassis hostname
        max_cpu: CPU warning threshold (default 80%)
        max_memory: Memory warning threshold (default 80%)
        max_sessions: Max active sessions warning threshold (default 8)
        test_ports: IXIA slot/port pairs used by this test (e.g., ["7/1", "7/2"]).
            CRC errors on these ports are blockers. CRC on other ports is informational.
    """
    return Task(
        task_name="ixia_preflight",
        ixia_needed=False,
        params=Params(
            json_params=json.dumps(
                {
                    "chassis_hostname": chassis_hostname,
                    "max_cpu": max_cpu,
                    "max_memory": max_memory,
                    "max_sessions": max_sessions,
                    "test_ports": test_ports or [],
                }
            )
        ),
    )


def create_cleanup_exabgp_task(
    hostname: str,
    restart_bgpd: bool = True,
    remote_path: str = "/tmp/exabgpd.par",
    config_path: str = "/tmp/exabgp.conf",
) -> Task:
    """Stop ExaBGP and clean up deployed files on a FBOSS device.

    Kills the ExaBGP process, removes all deployed files, and
    optionally restarts BGP++ to restore the device to its original state.
    """
    return Task(
        task_name="cleanup_exabgp",
        params=Params(
            json_params=json.dumps(
                {
                    "hostname": hostname,
                    "remote_path": remote_path,
                    "config_path": config_path,
                    "restart_bgpd": restart_bgpd,
                }
            )
        ),
    )


def create_backup_running_config_task(
    hostname: str,
    backup_file: t.Optional[str] = None,
) -> Task:
    """
    Create a task to backup the running config of an Arista EOS device.

    The backup is saved to the device's flash storage via
    ``copy running-config flash:<name>``. If no backup_file is provided,
    a timestamp-based name is auto-generated.

    Args:
        hostname: Hostname of the EOS device
        backup_file: Optional backup filename (without ``flash:`` prefix).
            If not provided, a timestamp-based name is generated automatically.

    Returns:
        Task object to backup the running config
    """
    params: t.Dict[str, t.Any] = {"hostname": hostname}
    if backup_file is not None:
        params["backup_file"] = backup_file

    return Task(
        task_name="backup_running_config",
        params=Params(json_params=json.dumps(params)),
    )


def create_restore_running_config_task(
    hostname: str,
    backup_file: str,
) -> Task:
    """
    Create a task to restore the running config of an Arista EOS device.

    Restores the configuration via ``configure replace flash:<name>``,
    atomically replacing the running config with the backup.

    Args:
        hostname: Hostname of the EOS device
        backup_file: Backup filename to restore from, e.g.
            ``flash:taac_backup_20251114_162530``

    Returns:
        Task object to restore the running config
    """
    return Task(
        task_name="restore_running_config",
        params=Params(
            json_params=json.dumps(
                {
                    "hostname": hostname,
                    "backup_file": backup_file,
                }
            )
        ),
    )


def create_set_port_channel_min_link_patcher_task(
    hostname: str,
    port_channel_name: str,
    min_link_percentage: t.Union[int, float],
    min_link_up_percentage: t.Optional[t.Union[int, float]] = None,
    description: t.Optional[str] = "Register port channel min link percentage patcher",
    patcher_name: str = "configure_port_channel_min_link_percentage",
) -> Task:
    """Create a task to register a port-channel min-link percentage patcher.

    Wraps the `set_port_channel_min_link_patcher` runtime task to install a
    COOP agent patcher that sets the min-link / min-link-up thresholds for a
    LAG (port-channel). Used in EBB BGP++ test configs to tune LAG quorum
    behavior under member-port flap scenarios.

    Args:
        hostname: Device hostname where the patcher is registered.
        port_channel_name: Port-channel (LAG) name (e.g. `"Port-Channel100"`).
        min_link_percentage: Minimum percentage of member links required for
            the LAG to remain up (e.g. `50` for 50%).
        min_link_up_percentage: Optional minimum percentage of member links
            that must be in the UP state. If None, only `min_link_percentage`
            governs LAG state.
        description: Human-readable description recorded with the patcher
            registration. Default describes it as a min-link patcher.
        patcher_name: Unique patcher name on the device.

    Returns:
        A `Task` with `task_name="set_port_channel_min_link_patcher"`.
    """
    params_dict: t.Dict[str, t.Any] = {
        "hostname": hostname,
        "port_channel_name": port_channel_name,
        "patcher_name": patcher_name,
        "description": description,
        "min_link_percentage": min_link_percentage,
        "min_link_up_percentage": min_link_up_percentage,
    }
    return Task(
        task_name="set_port_channel_min_link_patcher",
        params=Params(json_params=json.dumps(params_dict)),
    )


def create_bgp_route_registry_cleanup_task(
    hostname: str,
    prefix_pool_names: t.Sequence[str],
    prefix_start_index: int,
    prefix_end_index: int,
    expanded_policy_path: str,
    expected_route_count: int,
    ebgp_peer_description: str = "EBGP",
    exact_peer_group_names: t.Optional[t.Sequence[str]] = None,
    expected_established_sessions: t.Optional[int] = None,
    parent_prefixes_to_ignore: t.Sequence[str] = (),
    convergence_soft_threshold_seconds: float = 60,
    convergence_hard_timeout_seconds: float = 300,
    convergence_poll_interval_seconds: float = 5,
) -> Task:
    """Build the failure-safe CICD-EBB-12 cleanup task."""
    params: t.Dict[str, t.Any] = {
        "hostname": hostname,
        "prefix_pool_names": list(prefix_pool_names),
        "prefix_start_index": prefix_start_index,
        "prefix_end_index": prefix_end_index,
        "expanded_policy_path": expanded_policy_path,
        "expected_route_count": expected_route_count,
        "ebgp_peer_description": ebgp_peer_description,
        "expected_established_sessions": expected_established_sessions,
        "parent_prefixes_to_ignore": list(parent_prefixes_to_ignore),
        "convergence_soft_threshold_seconds": convergence_soft_threshold_seconds,
        "convergence_hard_timeout_seconds": convergence_hard_timeout_seconds,
        "convergence_poll_interval_seconds": convergence_poll_interval_seconds,
        "session_hard_timeout_seconds": convergence_hard_timeout_seconds,
        "session_poll_interval_seconds": convergence_poll_interval_seconds,
    }
    if exact_peer_group_names is not None:
        params["exact_peer_group_names"] = list(exact_peer_group_names)
    return Task(
        task_name="bgp_route_registry_cleanup",
        ixia_needed=True,
        params=Params(json_params=json.dumps(params)),
    )


# =============================================================================
# GENERIC TASK BUILDER (used by step factories that wrap a Task into a Step)
# =============================================================================


def create_run_task(
    task_name: str,
    params_dict: t.Optional[t.Dict[str, t.Any]] = None,
    ixia_needed: bool = False,
) -> Task:
    """Build a Task struct from a task_name + JSON-serializable params dict.

    Used by step factories (e.g. `create_run_task_step`) that wrap a Task
    into a Step's RunTaskInput.
    """
    return Task(
        task_name=task_name,
        ixia_needed=ixia_needed,
        params=Params(json_params=json.dumps(params_dict or {})),
    )


# =============================================================================
# OPEN/R ROUTE ACTION TASK (migrated from steps/step_definitions.py — Phase 8-1)
# =============================================================================


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
    ixia_needed: bool = False,
    set_outer_hostname: bool = False,
) -> Task:
    """Configurable Open/R route action task (inject, delete, metric_oscillation).

    Args:
        ixia_needed: If True, sets outer ``Task.ixia_needed`` so the task runs
            after IXIA setup. Defaults to False to preserve byte-equivalence
            for existing callers.
        set_outer_hostname: If True, also sets the outer ``Task.hostname``
            field (some legacy/runner-side scoping requires this). Defaults to
            False to preserve byte-equivalence for existing callers.
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
        hostname=device_name if set_outer_hostname else None,
        ixia_needed=ixia_needed,
        params=Params(json_params=json.dumps(params)),
    )


def create_ixia_diagnostics_collection_task(
    components: t.Optional[t.List[str]] = None,
    poll_timeout_s: int = 300,
    download_timeout_s: int = 600,
    manifold_bucket: t.Optional[str] = None,
    run_id: t.Optional[str] = None,
) -> Task:
    """Factory for the Ixia diagnostics collection teardown task.

    The runner invokes this task automatically unless
    ``--no-collect-ixia-diagnostics`` is passed on the netcastle CLI, so most
    TestConfigs do NOT need to add it to ``teardown_tasks`` explicitly. This
    factory exists so a TestConfig CAN add it by hand for tighter control (e.g.,
    custom component list per testbed).

    Args:
        components: Keysight DiagnosticService component display names to
            collect. None uses the framework default (IxNetwork app + Port logs).
            Enumerate available components with the
            ``discover_ixia_diagnostics_components`` script.
        poll_timeout_s: Max wall-clock to wait for the chassis to finish
            building the archive. Default 5 min.
        download_timeout_s: Max wall-clock for the binary download. Default
            10 min — large archives can take a while.
        manifold_bucket: Override the default bucket
            (``taac_ixia_diagnostics``). Useful for sandbox/dev buckets.
        run_id: Override the run id used in the Manifold key. None falls back
            to ``test_config.name`` (runner-side default).
    """
    params: t.Dict[str, t.Any] = {
        "poll_timeout_s": poll_timeout_s,
        "download_timeout_s": download_timeout_s,
    }
    if components is not None:
        params["components"] = components
    if manifold_bucket is not None:
        params["manifold_bucket"] = manifold_bucket
    if run_id is not None:
        params["run_id"] = run_id
    return Task(
        task_name="ixia_diagnostics_collection",
        params=Params(json_params=json.dumps(params)),
    )


# =============================================================================
# PERIODIC TASK FACTORIES
# =============================================================================


def create_arista_create_file_from_config_task(
    hostname: str,
    configerator_path: str,
    file_path: str,
    ixia_needed: bool = True,
) -> Task:
    """Copy a configerator file to a path on an Arista EOS device.

    Reads a configerator-managed text blob on the test runner and writes it to
    the target file path on the Arista device via base64-encoded `echo`
    commands (mirroring the COOP create_file pattern). Used to seed BGP++
    configs, route policies, etc. without needing a COOP patcher.

    Args:
        hostname: Arista EOS device hostname.
        configerator_path: Configerator path of the source file
            (e.g. `"taac/test_bgp_policies/foo.json"`).
        file_path: Destination absolute path on the device
            (e.g. `"/etc/bgpcpp/foo.json"`).
        ixia_needed: If True (default), task runs after IXIA setup. Set False
            for tasks that must run before IXIA peering.

    Returns:
        A `Task` with `task_name="arista_create_file_from_config"`.
    """
    return Task(
        task_name="arista_create_file_from_config",
        ixia_needed=ixia_needed,
        params=Params(
            json_params=json.dumps(
                {
                    "hostname": hostname,
                    "configerator_path": configerator_path,
                    "file_path": file_path,
                }
            )
        ),
    )


def create_validate_bgpcpp_config_on_device_task(
    hostname: str,
    config_path: str,
    policy_path: t.Optional[str] = None,
    ixia_needed: bool = True,
) -> Task:
    """Validate BGP++ config on an Arista device using the production validator.

    Runs ``/usr/sbin/bgp_config_validator`` (installed via the fb-bgpcpp RPM)
    on the device to verify the config file is valid JSON, deserializes into
    the Thrift BgpConfig struct, and has no dangling policy references.

    Args:
        hostname: Arista EOS device hostname.
        config_path: Absolute path to bgpcpp_config on the device.
        policy_path: Optional absolute path to bgpcpp_policy on the device.
        ixia_needed: If True (default), task runs after IXIA setup.

    Returns:
        A ``Task`` with ``task_name="validate_bgpcpp_config_on_device"``.
    """
    params = {
        "hostname": hostname,
        "config_path": config_path,
    }
    if policy_path is not None:
        params["policy_path"] = policy_path
    return Task(
        task_name="validate_bgpcpp_config_on_device",
        ixia_needed=ixia_needed,
        params=Params(json_params=json.dumps(params)),
    )


def create_validate_bgpcpp_update_group_state_task(
    hostname: str,
    expect_enabled: bool,
    ixia_needed: bool = True,
) -> Task:
    """Validate the live BGP++ Update Group state through its Thrift API."""
    return Task(
        task_name="validate_bgpcpp_update_group_state",
        hostname=hostname,
        ixia_needed=ixia_needed,
        params=Params(
            json_params=json.dumps(
                {
                    "hostname": hostname,
                    "expect_enabled": expect_enabled,
                }
            )
        ),
    )


def create_scp_file_template_task(
    hostname: str,
    remote_path: str,
    file_template: str,
    template_params: t.Dict[str, str],
) -> Task:
    """SCP a *templated* file to a remote host (used for systemd unit overrides).

    This is distinct from `create_scp_file_task` (line 984), which transfers a
    raw file by source/dest path. This variant renders a named template
    (`file_template`) with `template_params` substitutions on the runner side
    before transfer.
    """
    return Task(
        task_name="scp_file",
        params=Params(
            json_params=json.dumps(
                {
                    "hostname": hostname,
                    "remote_path": remote_path,
                    "file_template": file_template,
                    "template_params": template_params,
                }
            )
        ),
    )


def create_add_bgp_weight_policy_task(
    hostname: str,
    target_policy: str,
    community_weight_map: t.Dict[str, int],
    ssh_user: str,
    ssh_password: str,
    reload_bgp: bool = True,
) -> Task:
    """Add weight policy entries to a target BGP policy via SSH.

    Logs in to the Arista device over SSH and edits the named route-map /
    BGP policy in-place to set per-community `weight` values for inbound BGP
    best-path selection. Used by the BGP weight feature test config.

    Args:
        hostname: Arista device hostname.
        target_policy: Name of the existing BGP policy / route-map to amend.
        community_weight_map: Mapping of community string (e.g. `"65000:100"`)
            to the integer `weight` value to assign for matching routes.
        ssh_user: SSH username for the device login.
        ssh_password: SSH password for the device login.
        reload_bgp: If True (default), restart BGP after applying so the new
            weights take effect on existing sessions.

    Returns:
        A `Task` with `task_name="add_bgp_weight_policy"`.
    """
    return Task(
        task_name="add_bgp_weight_policy",
        params=Params(
            json_params=json.dumps(
                {
                    "hostname": hostname,
                    "target_policy": target_policy,
                    "community_weight_map": community_weight_map,
                    "ssh_user": ssh_user,
                    "ssh_password": ssh_password,
                    "reload_bgp": reload_bgp,
                }
            )
        ),
    )


def create_disable_med_comparison_task(
    hostname: str,
    ssh_user: str,
    ssh_password: str,
    reload_bgp: bool = True,
) -> Task:
    """Disable BGP MED comparison on the device via SSH.

    SSHes into the Arista device and clears the `bgp always-compare-med`
    setting (and equivalents) so MED is no longer used as a tiebreaker in
    best-path selection. Used by the BGP MED feature test config to baseline
    the device before enabling the feature under test.

    Args:
        hostname: Arista device hostname.
        ssh_user: SSH username for the device login.
        ssh_password: SSH password for the device login.
        reload_bgp: If True (default), restart BGP after disabling so the
            change takes effect immediately on established sessions.

    Returns:
        A `Task` with `task_name="disable_med_comparison"`.
    """
    return Task(
        task_name="disable_med_comparison",
        params=Params(
            json_params=json.dumps(
                {
                    "hostname": hostname,
                    "ssh_user": ssh_user,
                    "ssh_password": ssh_password,
                    "reload_bgp": reload_bgp,
                }
            )
        ),
    )


def create_set_peer_group_enforce_first_as_task(
    hostname: str,
    peer_groups: t.List[str],
    enforce_first_as: bool,
    ssh_user: str,
    ssh_password: str,
    reload_bgp: bool = True,
) -> Task:
    """Toggle the BGP enforce-first-as setting on the given peer groups via SSH.

    SSHes into the Arista device and applies (or removes) the
    `enforce-first-as` requirement on each named peer group. When enforced,
    inbound BGP UPDATEs whose first AS in the AS_PATH does not match the
    peer's configured AS are dropped. Used by the BGP enforce-first-as
    feature test config to verify both the enabled and disabled behavior.

    Args:
        hostname: Arista device hostname.
        peer_groups: Names of the BGP peer groups to toggle (e.g.
            `["PEERGROUP_RB_XSW_V4"]`).
        enforce_first_as: True to enable enforcement, False to disable.
        ssh_user: SSH username for the device login.
        ssh_password: SSH password for the device login.
        reload_bgp: If True (default), restart BGP after applying so the
            change takes effect on established sessions.

    Returns:
        A `Task` with `task_name="set_peer_group_enforce_first_as"`.
    """
    return Task(
        task_name="set_peer_group_enforce_first_as",
        params=Params(
            json_params=json.dumps(
                {
                    "hostname": hostname,
                    "peer_groups": peer_groups,
                    "enforce_first_as": enforce_first_as,
                    "ssh_user": ssh_user,
                    "ssh_password": ssh_password,
                    "reload_bgp": reload_bgp,
                }
            )
        ),
    )


def create_set_bgp_setting_config_task(
    hostname: str,
    settings: t.Dict[str, t.Any],
    reload_bgp: bool = False,
) -> Task:
    """Set BGP setting config on an Arista BGP++ device.

    Applies a dict of arbitrary `BgpSettingConfig` field overrides on a
    BGP++-enabled Arista device. Used to flip global BGP++ knobs (e.g.
    add-path, best-path tuning) before exercising a feature.

    Args:
        hostname: Arista BGP++ device hostname. Also serialized as the outer
            `Task.hostname` for runner-side scoping.
        settings: Dict of `BgpSettingConfig` field name → value (e.g.
            `{"enable_add_path": True}`). Values are passed through verbatim.
        reload_bgp: If True, restart BGP++ after applying so the new settings
            take effect immediately. Default False (caller controls reload
            timing explicitly).

    Returns:
        A `Task` with `task_name="set_bgp_setting_config"`.
    """
    return Task(
        task_name="set_bgp_setting_config",
        hostname=hostname,
        ixia_needed=False,
        params=Params(
            json_params=json.dumps(
                {
                    "hostname": hostname,
                    "settings": settings,
                    "reload_bgp": reload_bgp,
                }
            )
        ),
    )


def create_vip_injectors_task(
    hostname: str,
    vip_injector_count: int,
    num_vips_per_injector: int,
    starting_vip_ip: str,
    vip_prefix_len: int,
    starting_nexthop: str,
    vip_scope: str,
    vip_preference: int,
    vip_increment_ip: str = "0:0:1:0:0::0",
    nexthop_increment_ip: str = "0:0:0:0::2",
) -> Task:
    """Configure VIP injectors on the DUT (used by FBOSS VIP hardening tests).

    Programs N synthetic VIP "injectors" on the device, each advertising a
    range of IPv6 VIPs with a configured next-hop. Used by FBOSS VIP
    hardening test configs to drive realistic VIP-scale advertisement
    patterns into the agent and verify churn / programming behavior.

    Args:
        hostname: Device hostname where injectors are programmed.
        vip_injector_count: Number of injector instances to create.
        num_vips_per_injector: How many VIP prefixes each injector advertises.
        starting_vip_ip: First VIP IPv6 address in the range.
        vip_prefix_len: VIP prefix length (e.g. `128` for host routes).
        starting_nexthop: First next-hop IPv6 address.
        vip_scope: VIP scope tag (FBOSS-defined string).
        vip_preference: Preference value for advertised VIPs.
        vip_increment_ip: Amount to increment the VIP address per VIP within
            an injector. Default `"0:0:1:0:0::0"`.
        nexthop_increment_ip: Amount to increment the next-hop per injector.
            Default `"0:0:0:0::2"`.

    Returns:
        A `Task` with `task_name="create_vip_injectors"`.
    """
    return Task(
        task_name="create_vip_injectors",
        params=Params(
            json_params=json.dumps(
                {
                    "hostname": hostname,
                    "vip_injector_count": vip_injector_count,
                    "num_vips_per_injector": num_vips_per_injector,
                    "starting_vip_ip": starting_vip_ip,
                    "vip_increment_ip": vip_increment_ip,
                    "vip_prefix_len": vip_prefix_len,
                    "starting_nexthop": starting_nexthop,
                    "nexthop_increment_ip": nexthop_increment_ip,
                    "vip_scope": vip_scope,
                    "vip_preference": vip_preference,
                }
            )
        ),
    )


def create_nexthop_group_poll_periodic_task(
    device_name: str,
    threshold: int = 50,
    interval: int = 5,
    enable_plotting: bool = True,
    max_unprogrammed: t.Optional[int] = None,
    unprogrammed_tolerance_samples: t.Optional[int] = None,
    min_ecmp_width: t.Optional[int] = None,
    max_multiway_groups: t.Optional[int] = None,
    recovery_tolerance: t.Optional[float] = None,
    recovery_window_samples: t.Optional[int] = None,
    min_observed_groups: t.Optional[int] = None,
    expected_converged_multiway_groups: t.Optional[int] = None,
    converged_window_samples: t.Optional[int] = None,
    min_samples: t.Optional[int] = None,
) -> PeriodicTask:
    """Periodic task to poll nexthop-group count against a threshold.

    Wraps the `nexthop_group_poll` runtime task in a `PeriodicTask` that
    samples the device's current nexthop-group (ECMP group) count every
    `interval` seconds and records the value for later check / plotting.

    Non-terminating MID-RUN: a threshold breach does not abort the test while
    it is running, so the full series is always recorded. It does, however,
    FAIL the test case at teardown -- `run_final_check` returns a FAIL
    PeriodicCheckResult, `async_run_periodic_task_checks` appends it to
    `test_case_results`, and `check_failure` raises `TestCaseFailure`.

    `terminate_on_error` governs a different thing: the worker aborts the run
    only if the poll ITSELF raises. `NexthopGroupPoll.run` catches almost
    everything, so it rarely fires -- but not never. The `params["hostname"]`
    lookup sits above that try, and `ParameterEvaluator.evaluate` plus the
    shared-dict update in `PeriodicTask._run` execute outside `run` entirely,
    inside the worker's own handler. Leave it False: a threshold breach should
    surface as a verdict at teardown with the full series intact, not as a
    mid-run abort.

    Args:
        device_name: Device hostname to poll.
        threshold: Ceiling for the nexthop-group count; the check FAILs when
            the observed max meets or exceeds it. Default `50`. NB this default
            has no hardware derivation -- see the SC9 plan; prefer passing a
            value anchored to the device-reported ECMP capacity.
        interval: Polling interval in seconds. Default `5`. A transient shorter
            than this is invisible to the sampler.
        enable_plotting: If True (default), recorded values are published for
            plotting in the test artifact view.
        max_unprogrammed: Optional ceiling for `num_unprogrammed_groups`, the
            device's own report that it failed to program a group. `0` asserts
            that every group the device tried to program was accepted, which is
            the most direct available expression of "within the hardware
            limit". Omitted (None) = not asserted, preserving existing
            callers' behaviour.
        unprogrammed_tolerance_samples: How many CONSECUTIVE samples may exceed
            `max_unprogrammed` before it is a breach. Omitted = any exceedance
            breaches, the original behaviour. Group creation and hardware
            programming are not atomic, so a poll landing inside a rebuild sees
            groups legitimately in flight -- a five-cycle drain caught exactly
            one such sample in 391. Set this to gate on groups STAYING
            unprogrammed rather than on an instantaneous peak.
        min_ecmp_width: Minimum next-hop count for a group to be counted as a
            real ECMP set. Set it (e.g. `2`) to have the check report, and
            optionally gate, the number of genuine multi-way sets rather than
            the raw group count -- the raw count includes width-1 groups, so a
            DUT that sheds its ECMP structure into per-peer singletons makes the
            count RISE, and a naive ceiling then fires on a loss of ECMP.
        max_multiway_groups: Optional ceiling for that multi-way count. Requires
            `min_ecmp_width`. Omitted = observe-and-report only.
        recovery_tolerance: Optional multiplier asserting the group count
            returns to its opening baseline by the end of the run: the final
            window's max must be <= baseline * tolerance. This separates a
            bounded transient from a persistent structural change by DURATION
            rather than magnitude, so it needs no calibrated ceiling. Omitted =
            not asserted.
        recovery_window_samples: How many samples define the opening baseline
            and the closing window for `recovery_tolerance`. Default 10. The
            run must produce at least twice this many samples, otherwise the
            two windows would overlap and the check FAILs as unevaluated.
        expected_converged_multiway_groups: Optional exact steady-state count of
            multi-way ECMP sets, asserted against the MEDIAN of the closing
            window. Requires min_ecmp_width. This is the only verdict on this
            task that looks at the settled state -- every other one is a maximum
            over the whole run, so without it a device idling at five ECMP sets
            reads the same as one idling at the expected two. It compares
            against a literal rather than an opening baseline on purpose:
            periodic tasks start before setup_steps, so the opening window
            predates convergence.
        converged_window_samples: Size of that closing window (default 11).
            Must be ODD, and is rejected as a config breach otherwise: the
            median of an even window is the AVERAGE of its two middle samples,
            so a window straddling two values yields a half-integer that can
            never equal the integer expectation and a healthy device breaches.
        min_samples: Optional floor on how many samples the run collected. The
            poll swallows every collection failure and only an ENTIRELY empty
            series fails, so without this a run that lost most of its reads
            still evaluates every verdict above on the survivors and reports
            them as confidently as a complete series. A liveness floor, not a
            completeness assertion.
        min_observed_groups: Optional floor on the peak nexthop-group count. An
            all-zero series is not empty, so it passes the empty-series guard
            and then satisfies any ceiling (`max(0) < threshold`). Setting this
            (e.g. `1`) asserts the metric actually observed something. Not
            hypothetical: on bag012 this metric read 0 for all 884 samples and
            the suite passed repeatedly on a structurally blind gate.

    Returns:
        A `PeriodicTask` named `"nexthop_group_check"` wrapping
        `task_name="nexthop_group_poll"`.
    """
    json_payload: t.Dict[str, t.Any] = {
        "hostname": device_name,
        "threshold": threshold,
        "enable_plotting": enable_plotting,
    }
    # Emitted only when requested, so every existing caller's serialized config
    # -- and therefore its golden hash -- is unchanged.
    for key, value in (
        ("max_unprogrammed", max_unprogrammed),
        ("unprogrammed_tolerance_samples", unprogrammed_tolerance_samples),
        ("min_ecmp_width", min_ecmp_width),
        ("max_multiway_groups", max_multiway_groups),
        ("recovery_tolerance", recovery_tolerance),
        ("recovery_window_samples", recovery_window_samples),
        ("min_observed_groups", min_observed_groups),
        ("expected_converged_multiway_groups", expected_converged_multiway_groups),
        ("converged_window_samples", converged_window_samples),
        ("min_samples", min_samples),
    ):
        if value is not None:
            json_payload[key] = value

    return PeriodicTask(
        name="nexthop_group_check",
        interval=interval,
        task=Task(task_name="nexthop_group_poll"),
        retryable=False,
        terminate_on_error=False,
        params_list=[Params(json_params=json.dumps(json_payload))],
    )


def create_bgp_queue_backpressure_poll_periodic_task(
    device_name: str,
    threshold: int = 1000,
    interval: int = 10,
    terminate_on_error: bool = False,
) -> PeriodicTask:
    """Periodic task to poll BGP++ egress-queue backpressure against a threshold.

    Wraps the `bgp_queue_backpressure_poll` runtime task in a `PeriodicTask` that
    samples the device's per-peer CUMULATIVE queue-block counters
    (`adjribout_queue_blocks` + `send_queue_blocks`, summed across peers) every
    `interval` seconds and gates on the DELTA accumulated over the test window. A
    growing delta means BGP's egress pipeline is backpressured (falling behind),
    which is the direct "keeping up under churn/scale" signal -- unlike the
    instantaneous fiber-queue depth, these cumulative counters survive between
    samples. Non-terminating by default: a breach is recorded but does not abort
    the test until a test author flips `terminate_on_error` after calibration.

    Args:
        device_name: Device hostname to poll.
        threshold: Max allowed queue-block delta over the run. Default `1000`
            (deliberately generous / observe-first until calibrated).
        interval: Polling interval in seconds. Default `10`.
        terminate_on_error: If True, a threshold breach produces a blocking
            final result. Default False records the breach as observation.

    Returns:
        A `PeriodicTask` named `"bgp_queue_backpressure_check"` wrapping
        `task_name="bgp_queue_backpressure_poll"`.
    """
    return PeriodicTask(
        name="bgp_queue_backpressure_check",
        interval=interval,
        task=Task(task_name="bgp_queue_backpressure_poll"),
        retryable=False,
        terminate_on_error=terminate_on_error,
        params_list=[
            Params(
                json_params=json.dumps(
                    {
                        "hostname": device_name,
                        "threshold": threshold,
                        "fail_on_breach": terminate_on_error,
                    }
                )
            )
        ],
    )


def create_thrift_stress_periodic_task(
    device_name: str,
    interval: int = 5,
    calls: t.Optional[t.List[ThriftStressCall]] = None,
    requests_per_api: int = 10000,
    apis: t.Optional[t.List[str]] = None,
    burst_timeout_s: float = 60.0,
    name: str = "thrift_stress_check",
) -> PeriodicTask:
    """Periodic task that drives a sustained thrift workload.

    Each burst fires every entry in `calls` (or the default read-only FBOSS
    baseline) via `asyncio.gather`. The wrapping `PeriodicTaskWorker` loops
    back-to-back with `time.sleep(interval)` between bursts — the
    `while True: gather(...); sleep(N)` shape from
    `scripts/pavanpatil/thrift_call_disruptive.py`.

    Use this as
    `Playbook.periodic_tasks=[create_thrift_stress_periodic_task(dut, calls=...)]`
    on the THFT (thrift-hardening) test configs. For the THFT_001..004 variants
    the playbook also runs `create_service_interruption_step` every 5 min in
    the foreground; combined, they exercise the device under thrift pressure
    with concurrent process restarts.

    Payload selection happens via builders in
    `tasks/thrift_stress_payloads.py` — pass a `READ_ONLY_FBOSS_APIS` list or
    a `icepack_th6_with_qsfp_flaps(interfaces=...)` result here. If neither
    `calls` nor `apis` is set, the default read-only baseline is used with
    `requests_per_api` invocations per call (legacy shape).

    Args:
        device_name: DUT hostname (must be a FBOSS device — the default APIs
            are FBOSS-only).
        interval: Sleep between bursts in seconds. Default 5.
        calls: Preferred. List of `ThriftStressCall` describing each method
            to call, args, and per-burst concurrency. Mutually exclusive with
            `apis`.
        requests_per_api: Legacy. Per-call concurrency when using `apis` or
            the default baseline. Default 10000 matches the original script.
            For dry-runs dial down to 100-1000.
        apis: Legacy. List of no-arg driver method names. Mutually exclusive
            with `calls`. Each name is wrapped in a default `ThriftStressCall`
            using `requests_per_api`.
        name: `PeriodicTask.name`, used for the log line and thread/process
            label. Override when a playbook attaches MORE THAN ONE of these
            (e.g. THFT runs a thrift-storm task and a qsfp-flap task side by
            side) so the two are distinguishable in the logs.

    Returns:
        A `PeriodicTask` named `name` (default `"thrift_stress_check"`)
        wrapping `task_name="thrift_stress"`.

    Raises:
        ValueError: If both `calls` and `apis` are supplied.
    """
    if calls is not None and apis is not None:
        raise ValueError(
            "create_thrift_stress_periodic_task: pass `calls` OR `apis`, not both"
        )
    params: t.Dict[str, t.Any] = {
        "hostname": device_name,
        "burst_timeout_s": burst_timeout_s,
    }
    if calls is not None:
        params["calls"] = [c.to_dict() for c in calls]
    elif apis is not None:
        params["apis"] = apis
        params["requests_per_api"] = requests_per_api
    else:
        params["requests_per_api"] = requests_per_api
    return PeriodicTask(
        name=name,
        interval=interval,
        task=Task(task_name="thrift_stress"),
        retryable=False,
        terminate_on_error=False,
        params_list=[Params(json_params=json.dumps(params))],
    )


# =============================================================================
# FPF Collector Tasks
# =============================================================================


def create_fpf_start_collectors_task(
    gtsws: t.List[str],
    hosts: t.List[str],
    subnet_prefix: str = "5000:dd::/32",
    poll_interval_sec: float = 5.0,
    baseline_collection_sec: int = 120,
    prod_prefixes: t.Optional[t.List[str]] = None,
    prod_prefix_host: t.Optional[str] = None,
    prod_prefix_device_id: int = 0,
    prod_prefixes_by_host: t.Optional[t.Dict[str, t.List[str]]] = None,
    fsdb_mode: str = "ribmap",
    allow_baseline_failures: bool = False,
    enable_fsdb_session_collector: bool = True,
    fsdb_session_host: t.Optional[str] = None,
    fsdb_session_hosts: t.Optional[t.List[str]] = None,
    fsdb_session_poll_interval_sec: float = 3.0,
    fsdb_session_expected: int = 32,
    rf_vf_groups: t.Optional[t.List[t.Dict[str, t.Any]]] = None,
    hrt_device_ids: t.Optional[t.List[int]] = None,
    hrt_plane_ids: t.Optional[t.List[int]] = None,
) -> Task:
    """Create a setup task that starts long-lived FPF collectors.

    ``fsdb_mode`` selects the FSDB ribMap read path: "ribmap" (bgp/ribMap, valid
    on the current GTSWs) or "canonical" (bgp/canonicalRib, newer schema that
    returns INVALID_PATH on GTSWs not exposing it). Default "ribmap".

    Starts the injected-prefix collectors (FSDB ribMap, HRT bulk, BGP RIB,
    HRT remote-failure) and waits for baseline data collection. FSDB expands
    ``gtsws`` to all local plane switches plus explicitly supplied observers;
    BGP polls only the supplied observer list because only those devices are
    consumed by BGP health checks. Prefix injection is NOT done here — it is a
    stage step in the playbook so test_case_start_time aligns with injection.

    ``hrt_device_ids`` selects the independent HRT devices whose local planes
    are recorded by the bulk and aggregate remote-failure collectors. It
    defaults compatibly to dev0 when omitted. Per-VF collector entries may carry
    their own ``device_ids`` mapping.
    ``hrt_plane_ids`` selects the local plane IDs emitted for every requested
    device. It defaults to legacy 0..7; new-SDK paired-device hosts pass 0..3.

    When ``prod_prefixes`` is supplied, a fifth collector
    (ProdHrtPrefixCollector) is also started to monitor steady-state
    per-prefix plane reachability of those production VF prefixes on
    ``prod_prefix_host`` (defaults to hosts[0]) GPU ``prod_prefix_device_id``.
    This is the collector validated by FpfProdHrtPrefixStabilityHealthCheck.

    The HRT FSDB-session-count collector (HrtFsdbSessionCollector) is started by
    default whenever rtptest GPU hosts are present (``enable_fsdb_session_collector``,
    default True), polling ``getFsdbSessions()`` every
    ``fsdb_session_poll_interval_sec`` (default 3s) to record the CONNECTED census
    + per-lane breakdown consumed by FpfHrtSessionStatHealthCheck.

    The FSDB-session / prod-prefix / plane-status signals are each ONE collector
    holding ALL monitored hosts (one file with a host column). ``fsdb_session_hosts``
    ([host, ...]) selects which hosts the session collector monitors (default: all
    GPU hosts). ``prod_prefixes_by_host`` ({host: [prefixes]}) gives each host its
    configured query prefixes for the prod-prefix collector; multiple hosts may
    observe the same conditional route. The legacy ``prod_prefixes`` +
    ``prod_prefix_host`` folds into a one-host map. The matching health checks read
    the single collector and iterate its hosts internally, asserting every host
    independently. ``fsdb_session_host`` (singular) is
    accepted for back-compat and, when the plural form is not given, folded into
    a one-entry ``fsdb_session_hosts`` list to preserve single-host intent.
    """
    params: t.Dict[str, t.Any] = {
        "gtsws": gtsws,
        "hosts": hosts,
        "subnet_prefix": subnet_prefix,
        "poll_interval_sec": poll_interval_sec,
        "baseline_collection_sec": baseline_collection_sec,
        "fsdb_mode": fsdb_mode,
        "allow_baseline_failures": allow_baseline_failures,
        "enable_fsdb_session_collector": enable_fsdb_session_collector,
        "fsdb_session_poll_interval_sec": fsdb_session_poll_interval_sec,
        "fsdb_session_expected": fsdb_session_expected,
    }
    if rf_vf_groups:
        params["rf_vf_groups"] = rf_vf_groups
    if hrt_device_ids and hrt_device_ids != [0]:
        params["hrt_device_ids"] = hrt_device_ids
    if hrt_plane_ids and hrt_plane_ids != list(range(8)):
        params["hrt_plane_ids"] = hrt_plane_ids
    if fsdb_session_hosts:
        params["fsdb_session_hosts"] = fsdb_session_hosts
    elif fsdb_session_host is not None:
        # Legacy singular form: fold into the plural list the task actually reads
        # (fpf_collector_tasks only consumes fsdb_session_hosts). Preserves the
        # caller's single-host intent instead of silently defaulting to all GPU
        # hosts.
        params["fsdb_session_hosts"] = [fsdb_session_host]
    if prod_prefixes_by_host:
        params["prod_prefixes_by_host"] = prod_prefixes_by_host
        params["prod_prefix_device_id"] = prod_prefix_device_id
    elif prod_prefixes:
        params["prod_prefixes"] = prod_prefixes
        params["prod_prefix_host"] = prod_prefix_host or (hosts[0] if hosts else "")
        params["prod_prefix_device_id"] = prod_prefix_device_id
    return Task(
        task_name="fpf_start_collectors",
        params=Params(json_params=json.dumps(params)),
    )


def create_fpf_start_ib_traffic_task(
    server: str,
    clients: t.List[str],
    binary_path: t.Optional[str] = None,
    device: str = "mlx5_34",
    gid_iface: str = "bveth0",
    gid_prefix: str = "2401",
    gid_index: t.Optional[int] = None,
    port: int = 15000,
    min_egress_gbps: float = 10.0,
    settle_sec: int = 120,
    ods_window_sec: int = 120,
    msg_size: t.Optional[int] = None,
    qp: t.Optional[int] = None,
    tclass: t.Optional[int] = None,
    iters: t.Optional[int] = None,
    key_desc: t.Optional[str] = None,
    reduce_desc: t.Optional[str] = None,
    transform_desc: t.Optional[str] = None,
) -> Task:
    """Create a setup task that starts ib_write_bw RDMA traffic and validates egress.

    SSHes to ``server`` and each host in ``clients``, validates the configured
    ``binary_path`` (default /usr/bin/ib_write_bw), starts long-lived
    ``ib_write_bw`` (server then clients) on RDMA ``device`` (default mlx5_34 /
    VF1), confirms the processes are up, waits ``settle_sec`` (default 120s),
    then queries ODS to confirm each host is egressing more than
    ``min_egress_gbps`` (default 10 Gbps cumulative across beth0-3). The task
    RAISES (failing setup, aborting the test) with a clear per-host message if
    traffic is not flowing. On success the traffic is left running for the test;
    pair with ``create_fpf_stop_ib_traffic_task`` as a teardown task.

    The RoCEv2 GID index (``-x``) is discovered per host at runtime from
    ``show_gids`` (selecting the ``gid_iface`` v2 GID whose address matches
    ``gid_prefix``, e.g. ``show_gids | grep bveth0 | grep v2 | grep 2401`` ->
    index in the 3rd field). Pass ``gid_index`` only to override the probe.

    Only explicitly-provided optional params are emitted; the rest fall back to
    the task's own defaults.
    """
    params: t.Dict[str, t.Any] = {
        "server": server,
        "clients": clients,
        "device": device,
        "gid_iface": gid_iface,
        "gid_prefix": gid_prefix,
        "port": port,
        "min_egress_gbps": min_egress_gbps,
        "settle_sec": settle_sec,
        "ods_window_sec": ods_window_sec,
    }
    if binary_path is not None:
        params["binary_path"] = binary_path
    if gid_index is not None:
        params["gid_index"] = gid_index
    if msg_size is not None:
        params["msg_size"] = msg_size
    if qp is not None:
        params["qp"] = qp
    if tclass is not None:
        params["tclass"] = tclass
    if iters is not None:
        params["iters"] = iters
    if key_desc is not None:
        params["key_desc"] = key_desc
    if reduce_desc is not None:
        params["reduce_desc"] = reduce_desc
    if transform_desc is not None:
        params["transform_desc"] = transform_desc
    return Task(
        task_name="fpf_start_ib_traffic",
        params=Params(json_params=json.dumps(params)),
    )


def create_fpf_stop_ib_traffic_task(
    server: str,
    clients: t.List[str],
) -> Task:
    """Create a teardown task that stops ib_write_bw traffic on server + clients."""
    return Task(
        task_name="fpf_stop_ib_traffic",
        params=Params(json_params=json.dumps({"server": server, "clients": clients})),
    )


def create_fpf_stop_collectors_task(
    trigger_stsws: t.List[str],
    prefix_count: int = 70000,
    prefix_base: str = "5000:dd::/64",
    increment_step: str = "0:0:1::",
    community_list: str = "stsw",
    withdraw: bool = True,
) -> Task:
    """Create a teardown task that stops FPF collectors and (optionally) withdraws prefixes.

    Pass ``withdraw=False`` to stop the collectors ONLY, without withdrawing any
    prefixes — used by configs whose prefixes are cleared another way (e.g. the
    8-STSW split-per-VF configs restart bgpd on the STSWs at teardown via
    ``create_fpf_restart_service_task``, which drops the runtime-injected
    networks). This replaces the earlier ``prefix_count=0`` sentinel.
    """
    stop_params: t.Dict[str, t.Any] = {
        "trigger_stsws": trigger_stsws,
        "prefix_count": prefix_count,
        "prefix_base": prefix_base,
        "increment_step": increment_step,
        "community_list": community_list,
    }
    # Only emit the key when disabling withdrawal, so existing callers (default
    # withdraw=True) keep byte-identical params (stable golden manifest); the
    # runtime defaults to withdraw=True when the key is absent.
    if not withdraw:
        stop_params["withdraw"] = False
    return Task(
        task_name="fpf_stop_collectors",
        params=Params(json_params=json.dumps(stop_params)),
    )


def create_fpf_restart_service_task(
    devices: t.List[str],
    service: str = "BGP",
    wait_for_convergence: bool = False,
) -> Task:
    """Create a task that restarts a systemd service (default bgpd) on ``devices``.

    Used at teardown to clear runtime BGP-injected prefixes off the STSWs: a
    ``bgpd`` restart reloads persistent config (no injected networks), dropping
    them — and also clears any leftover injected state, keeping the testbed clean
    run-to-run. ``service`` is a ``FbossSystemctlServiceName`` member name (e.g.
    "BGP" -> bgpd, "AGENT" -> wedge_agent). Best-effort (never fails teardown).
    """
    return Task(
        task_name="fpf_restart_service",
        params=Params(
            json_params=json.dumps(
                {
                    "devices": devices,
                    "service": service,
                    "wait_for_convergence": wait_for_convergence,
                }
            )
        ),
    )


def create_fpf_inject_vf_groups_task(
    groups: t.List[t.Dict[str, t.Any]],
    settle_sec: int = 0,
) -> Task:
    """Create a SETUP task that injects one or more BGP prefix groups.

    ``groups`` is a list of group dicts (devices, prefix_base, count,
    community_list) — e.g. the 8-STSW split-per-VF spec from
    ``fpf_vf_injection_groups()``. The injection runs on every (device, group)
    pair in parallel and, on success, settles ``settle_sec`` for the prefixes to
    program on the GTSW/HRT. Any injection failure aborts the test setup. This
    keeps a netcastle run self-contained — no external inject script.
    """
    return Task(
        task_name="fpf_inject_bgp_prefixes",
        params=Params(
            json_params=json.dumps(
                {
                    "groups": groups,
                    "withdraw": False,
                    "settle_sec": settle_sec,
                }
            )
        ),
    )


def create_fpf_withdraw_vf_groups_task(
    groups: t.List[t.Dict[str, t.Any]],
) -> Task:
    """Create a TEARDOWN task that withdraws the injected prefix groups.

    Pairs with ``create_fpf_inject_vf_groups_task``. Best-effort — a withdrawal
    error is logged but never masks the test result.
    """
    return Task(
        task_name="fpf_inject_bgp_prefixes",
        params=Params(
            json_params=json.dumps(
                {
                    "groups": groups,
                    "withdraw": True,
                }
            )
        ),
    )


def create_fpf_withdraw_stale_prefixes_task(
    trigger_stsws: t.List[str],
    prefix_count: int = 70000,
    prefix_base: str = "5000:dd::/64",
    increment_step: str = "0:0:1::",
) -> Task:
    """Create a SETUP task that clears leftover synthetic test prefixes.

    Place this FIRST in ``setup_tasks`` (before ``create_fpf_start_collectors_task``
    and before any playbook injection step) to guarantee a clean ``5000:dd``
    baseline regardless of how the previous run ended. Withdraws a superset
    (default 70000 — ≥ the max any FPF config injects, incl. the v1 hardening
    configs) of ``prefix_base`` on the trigger STSWs. Idempotent (no-op when
    nothing is present).
    """
    return Task(
        task_name="fpf_withdraw_stale_prefixes",
        params=Params(
            json_params=json.dumps(
                {
                    "trigger_stsws": trigger_stsws,
                    "prefix_count": prefix_count,
                    "prefix_base": prefix_base,
                    "increment_step": increment_step,
                }
            )
        ),
    )


def create_setup_base_configs_task(
    hostname: t.Optional[str] = None,
    restart_bgp: bool = True,
) -> Task:
    """Create a task that generates a device's live and soft-drain BGP configs.

    Installs a generalized BGP policy set so a drain produces an observable
    signal, and writes the two config files that ``DRAIN_UNDRAIN_STEP`` selects
    between. Run it before any drain in the same test -- drain/undrain fail if
    the files are missing.

    OSS-only in practice: the underlying driver call rejects non-FBOSS drivers,
    and on a Meta-internal device COOP owns the config it writes.

    Normally there is no need to call this directly. It is in the default OSS
    setup-task list, so an OSS run gets it for free; declare it explicitly only
    to retune it -- for one device, or with ``restart_bgp=False``.

    Args:
        hostname: Device to configure. Leave unset when declaring this in
            ``TestConfig.oss_setup_tasks`` and it runs on every endpoint.
        restart_bgp: Restart bgpd so the live config takes effect. False stages
            both files without disturbing a running session, for batching
            several changes before one restart.

    Returns:
        Task object to generate the base BGP configs.
    """
    return Task(
        task_name="setup_base_configs",
        hostname=hostname,
        params=Params(json_params=json.dumps({"restart_bgp": restart_bgp})),
    )
