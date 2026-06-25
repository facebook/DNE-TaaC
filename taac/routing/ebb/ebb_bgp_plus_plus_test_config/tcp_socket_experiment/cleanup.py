# pyre-unsafe
"""
Shared cleanup utilities for TCP Socket Experiment.

Provides cleanup task generators used in both setup (clean slate before test)
and teardown (restore device state after test).

Ensures no stale config remains when switching between Case 1 and Case 2:
    - Removes /mnt/flash/bgpcpp_config on bag012 (BGP++)
    - Disables all BGP++ daemons on bag012
    - Removes BGP config on bag013 (ar-bgp) via 'no router bgp'
    - Cleans secondary IPs on all interfaces
"""

import typing as t

from taac.routing.ebb.ebb_bgp_plus_plus_test_config.tcp_socket_experiment.constants import (
    BAG012_DEVICE_NAME,
    BAG012_INTERCONNECT_INTERFACES,
    BAG012_IXIA_INTERFACE_1,
    BAG012_IXIA_INTERFACE_2,
    BAG012_IXIA_INTERFACE_3,
    BAG012_LOCAL_AS,
    BAG013_DEVICE_NAME,
    BAG013_INTERCONNECT_INTERFACES,
    BAG013_IXIA_INTERFACE_1,
    BAG013_IXIA_INTERFACE_2,
    BAG013_IXIA_INTERFACE_3,
    BAG013_LOCAL_AS,
    BGPCPP_CONFIG_PATH,
    BGPCPP_DAEMONS,
)
from taac.task_definitions import (
    create_arista_daemon_control_task,
    create_interface_ip_cleanup_task,
    create_run_commands_on_shell_task,
)
from taac.test_as_a_config.types import Task


def create_bgpcpp_cleanup_tasks(
    bgpcpp_device: str = BAG012_DEVICE_NAME,
    bgpcpp_local_as: int = BAG012_LOCAL_AS,
    daemons: t.Optional[t.List[str]] = None,
) -> t.List[Task]:
    """
    Create tasks to clean up BGP++ state on bag012.

    Steps:
    1. Disable all BGP++ daemons
    2. Remove /mnt/flash/bgpcpp_config
    3. Shutdown native EOS BGP (in case it was re-enabled)

    Args:
        bgpcpp_device: BGP++ device hostname
        bgpcpp_local_as: Local AS number (for 'router bgp <AS> / shutdown')
        daemons: List of daemon names to disable
    """
    if daemons is None:
        daemons = BGPCPP_DAEMONS

    tasks = []

    # Disable all BGP++ daemons
    for daemon in daemons:
        tasks.append(
            create_arista_daemon_control_task(
                hostname=bgpcpp_device,
                daemon_name=daemon,
                action="disable",
                ixia_needed=False,
            )
        )

    # Remove bgpcpp_config file
    tasks.append(
        create_run_commands_on_shell_task(
            hostname=bgpcpp_device,
            cmds=[
                f"bash rm -f {BGPCPP_CONFIG_PATH}",
            ],
            ixia_needed=False,
        )
    )

    # Shutdown native EOS BGP (safe even if already shut)
    tasks.append(
        create_run_commands_on_shell_task(
            hostname=bgpcpp_device,
            cmds=["configure\nrouter bgp {}\nshutdown\nend".format(bgpcpp_local_as)],
            ixia_needed=False,
        )
    )

    return tasks


def create_arbgp_cleanup_tasks(
    arbgp_device: str = BAG013_DEVICE_NAME,
    arbgp_local_as: int = BAG013_LOCAL_AS,
    peergroup_ebgp_v6: str = "TCP-EXP-EBGP-V6",
    peergroup_ebgp_v4: str = "TCP-EXP-EBGP-V4",
    peergroup_ixia_v6: str = "TCP-EXP-IXIA-V6",
    peergroup_ixia_v4: str = "TCP-EXP-IXIA-V4",
) -> t.List[Task]:
    """
    Create tasks to clean up ar-bgp (EOS BGP) experiment config on bag013.

    IMPORTANT: bag013 has an existing production BGP config (router bgp 65013).
    We do NOT 'no router bgp' — that would destroy the standard config.
    Instead we remove only the experiment's peer groups (which also removes
    all neighbors under those peer groups).

    Args:
        arbgp_device: ar-bgp device hostname
        arbgp_local_as: Local AS number
        peergroup_ebgp_v6: Experiment eBGP IPv6 peer group to remove
        peergroup_ebgp_v4: Experiment eBGP IPv4 peer group to remove
        peergroup_ixia_v6: Experiment IXIA IPv6 peer group to remove
        peergroup_ixia_v4: Experiment IXIA IPv4 peer group to remove
    """
    cleanup_cmds = [
        "configure",
        f"router bgp {arbgp_local_as}",
        f"no neighbor {peergroup_ebgp_v6} peer group",
        f"no neighbor {peergroup_ebgp_v4} peer group",
        f"no neighbor {peergroup_ixia_v6} peer group",
        f"no neighbor {peergroup_ixia_v4} peer group",
        "end",
    ]
    return [
        create_run_commands_on_shell_task(
            hostname=arbgp_device,
            cmds=["\n".join(cleanup_cmds)],
            ixia_needed=False,
        )
    ]


def create_interface_cleanup_tasks(
    bgpcpp_device: str = BAG012_DEVICE_NAME,
    arbgp_device: str = BAG013_DEVICE_NAME,
    bgpcpp_interconnect_interfaces: t.Optional[t.List[str]] = None,
    arbgp_interconnect_interfaces: t.Optional[t.List[str]] = None,
    bgpcpp_ixia_interfaces: t.Optional[t.List[str]] = None,
    arbgp_ixia_interfaces: t.Optional[t.List[str]] = None,
) -> t.List[Task]:
    """
    Create tasks to restore interface IP configs from backup on both devices.

    Args:
        bgpcpp_device: BGP++ device hostname
        arbgp_device: ar-bgp device hostname
        bgpcpp_interconnect_interfaces: Interconnect interfaces on bag012
        arbgp_interconnect_interfaces: Interconnect interfaces on bag013
        bgpcpp_ixia_interfaces: IXIA interfaces on bag012
        arbgp_ixia_interfaces: IXIA interfaces on bag013
    """
    if bgpcpp_interconnect_interfaces is None:
        bgpcpp_interconnect_interfaces = BAG012_INTERCONNECT_INTERFACES
    if arbgp_interconnect_interfaces is None:
        arbgp_interconnect_interfaces = BAG013_INTERCONNECT_INTERFACES
    if bgpcpp_ixia_interfaces is None:
        bgpcpp_ixia_interfaces = [
            BAG012_IXIA_INTERFACE_1,
            BAG012_IXIA_INTERFACE_2,
            BAG012_IXIA_INTERFACE_3,
        ]
    if arbgp_ixia_interfaces is None:
        arbgp_ixia_interfaces = [
            BAG013_IXIA_INTERFACE_1,
            BAG013_IXIA_INTERFACE_2,
            BAG013_IXIA_INTERFACE_3,
        ]

    tasks = []

    # Clean bag012 interfaces
    all_bgpcpp_interfaces = bgpcpp_interconnect_interfaces + bgpcpp_ixia_interfaces
    for intf in all_bgpcpp_interfaces:
        tasks.append(
            create_interface_ip_cleanup_task(
                interfaces=[intf],
                restore_from_backup=True,
            )
        )

    # Clean bag013 interfaces
    all_arbgp_interfaces = arbgp_interconnect_interfaces + arbgp_ixia_interfaces
    for intf in all_arbgp_interfaces:
        tasks.append(
            create_interface_ip_cleanup_task(
                interfaces=[intf],
                restore_from_backup=True,
            )
        )

    return tasks


def create_full_cleanup_tasks(
    bgpcpp_device: str = BAG012_DEVICE_NAME,
    arbgp_device: str = BAG013_DEVICE_NAME,
    bgpcpp_local_as: int = BAG012_LOCAL_AS,
    arbgp_local_as: int = BAG013_LOCAL_AS,
    bgpcpp_interconnect_interfaces: t.Optional[t.List[str]] = None,
    arbgp_interconnect_interfaces: t.Optional[t.List[str]] = None,
    bgpcpp_ixia_interfaces: t.Optional[t.List[str]] = None,
    arbgp_ixia_interfaces: t.Optional[t.List[str]] = None,
    include_interface_cleanup: bool = False,
) -> t.List[Task]:
    """
    Create a complete set of cleanup tasks for both devices.

    Used at the START of setup (clean slate) and in teardown.
    Order: disable daemons → remove configs → (optionally) restore interfaces.

    IMPORTANT: interface cleanup requires interface_ip_configuration to have
    run first (creates backups). Set include_interface_cleanup=True only in
    teardown, NOT in pre-setup cleanup.

    Args:
        bgpcpp_device: BGP++ device hostname
        arbgp_device: ar-bgp device hostname
        bgpcpp_local_as: BGP++ device AS number
        arbgp_local_as: ar-bgp device AS number
        bgpcpp_interconnect_interfaces: Interconnect interfaces on bag012
        arbgp_interconnect_interfaces: Interconnect interfaces on bag013
        bgpcpp_ixia_interfaces: IXIA interfaces on bag012
        arbgp_ixia_interfaces: IXIA interfaces on bag013
        include_interface_cleanup: If True, restore interface IPs from backup.
            Only set True in teardown (after interface_ip_configuration ran).
    """
    tasks = []

    # 1. Disable BGP++ daemons and remove bgpcpp_config
    tasks.extend(
        create_bgpcpp_cleanup_tasks(
            bgpcpp_device=bgpcpp_device,
            bgpcpp_local_as=bgpcpp_local_as,
        )
    )

    # 2. Remove ar-bgp experiment peer groups
    tasks.extend(
        create_arbgp_cleanup_tasks(
            arbgp_device=arbgp_device,
            arbgp_local_as=arbgp_local_as,
        )
    )

    # 3. Restore interface IPs from backup (only in teardown)
    if include_interface_cleanup:
        tasks.extend(
            create_interface_cleanup_tasks(
                bgpcpp_device=bgpcpp_device,
                arbgp_device=arbgp_device,
                bgpcpp_interconnect_interfaces=bgpcpp_interconnect_interfaces,
                arbgp_interconnect_interfaces=arbgp_interconnect_interfaces,
                bgpcpp_ixia_interfaces=bgpcpp_ixia_interfaces,
                arbgp_ixia_interfaces=arbgp_ixia_interfaces,
            )
        )

    return tasks
