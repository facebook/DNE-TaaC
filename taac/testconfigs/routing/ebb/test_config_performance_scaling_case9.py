# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""Arista BGP++ performance scaling test case 9: bounded ECMP sets.

Builds a TestConfig that exercises Arista BGP++ ECMP set bounding logic
under IBGP + EBGP peering at production scale. Used to verify that the
DUT properly caps ECMP next-hop set size and recovers correctly when
peers come and go.
"""

import typing as t

from taac.playbooks.playbook_definitions import (
    create_bgp_plus_plus_arista_bounded_ecmp_sets_playbook,
)
from taac.routing.ebb.arista_bgp_plus_plus_performance_scaling_tests.ixia_configs_for_tests import (
    create_ebb_bounded_ecmp_sets_port_configs,
)
from taac.routing.ebb.ebb_bgp_plus_plus_test_config.ebb_bgp_plus_plus_conveyor.conveyor_common_tasks import (
    _generate_ixia_v4_peer_entries_for_bgpcpp,
    _generate_ixia_v6_peer_entries_for_bgpcpp,
)
from taac.routing.ebb.ebb_bgp_plus_plus_test_config.ebb_bgp_plus_plus_conveyor.conveyor_constants import (
    UPDATE_GROUP_CONFIG,
)
from taac.task_definitions import (
    create_arista_daemon_control_task,
    create_interface_ip_configuration_task,
    create_run_commands_on_shell_task,
    create_validate_bgpcpp_config_on_device_task,
)
from taac.testconfigs.routing.ebb.case1_test_config import (
    _generate_bgpcpp_peers_modification_tasks,
)
from taac.test_as_a_config.types import Endpoint, TestConfig


# bgpcpp on-device paths (Arista EOS).
_RUN_BGPCPP_SCRIPT_PATH = "/usr/sbin/run_bgpcpp.sh"
_BGPCPP_CONFIG_PATH = "/mnt/flash/bgpcpp_config"


def test_config_for_bgp_plus_plus_on_ebb_arista_bounded_ecmp_sets(
    test_config_name: str,
    device_name: str,
    ixia_interface_mimic_ebgp: str,
    ixia_interface_mimic_ibgp: str,
    ebgp_peer_count_v6: int,
    ibgp_peer_count_v6: int,
    ebgp_peer_count_v4: int,
    ibgp_peer_count_v4: int,
    ebgp_remote_as: int,
    ibgp_remote_as: int,
    ixia_ebgp_ic_parent_network_v6: str,
    ixia_ibgp_ic_parent_network_v6: str,
    ixia_ebgp_ic_parent_network_v4: str,
    ixia_ibgp_ic_parent_network_v4: str,
    prefix_count: int,
    direct_ixia_connections: list,
    log_collection_timeout=None,
    oss_mock_device_data=None,
    host_os_type_map=None,
    host_driver_args=None,
    ssh_user: str = "admin",
    ssh_password: str = "",
    peergroup_ebgp_v6: str = "EB-FA-V6",
    peergroup_ebgp_v4: str = "EB-FA-V4",
    peergroup_ibgp_v6: str = "EB-EB-V6",
    peergroup_ibgp_v4: str = "EB-EB-V4",
    enable_update_group: bool = False,
    update_group_config: t.Optional[t.Dict[str, t.Any]] = None,
    setup_tasks: t.Optional[list] = None,
):
    """Build the case-9 (bounded ECMP sets) BGP++ TestConfig.

    Configures EBGP + IBGP peer groups (v4 + v6) by patching the device's
    ``/mnt/flash/bgpcpp_config`` and ``/usr/sbin/run_bgpcpp.sh``, then runs
    ``create_bgp_plus_plus_arista_bounded_ecmp_sets_playbook`` to verify the
    DUT's ECMP set bounding behavior at production peer scale.

    Device setup runs entirely through netcastle's MANAGED device connection
    (``create_run_commands_on_shell_task`` / ``_generate_bgpcpp_peers_modification_tasks``
    / ``create_arista_daemon_control_task``) — the same mechanism BAG012 Update
    Packing and Constant Attribute Storage use — rather than opening a raw SSH
    session. This avoids depending on in-band ``admin`` SSH credentials.

    Args:
        test_config_name: Final name of the produced TestConfig.
        device_name: DUT hostname (Arista EBB).
        ixia_interface_mimic_ebgp / ixia_interface_mimic_ibgp: IXIA port
            names used as peer endpoints.
        ebgp_peer_count_v6 / ibgp_peer_count_v6 / ebgp_peer_count_v4 /
        ibgp_peer_count_v4: Per-AFI peer counts.
        ebgp_remote_as / ibgp_remote_as: Remote ASNs.
        ixia_*_ic_parent_network_v6/v4: Parent networks for IXIA-side prefix
            generation.
        prefix_count: Number of prefixes advertised per peer.
        direct_ixia_connections: Optional direct IXIA-port connection list.
        log_collection_timeout / oss_mock_device_data / host_os_type_map /
        host_driver_args: Optional overrides for OSS harness wiring.
        ssh_user / ssh_password: Unused. Setup now runs via the managed device
            connection (see above); retained only for caller compatibility and
            will be removed once all callers stop passing them.
        peergroup_*: Peer-group names (defaults match EB-FA/EB-EB).
        enable_update_group: When True, also patch ``bgp_setting_config`` in
            ``/mnt/flash/bgpcpp_config`` to enable BGP++ update grouping (plus
            the full ``update_group_config`` struct per D100093369) so the test
            qualifies the update-group feature.
        update_group_config: Optional override for the update_group struct;
            defaults to ``UPDATE_GROUP_CONFIG``. Only honored when
            ``enable_update_group=True`` and ``setup_tasks`` is not supplied.
        setup_tasks: Optional pre-built setup task list. When supplied -- the
            standard ``get_update_packing_setup_tasks`` path used by the bag012
            conveyor builder -- it is used verbatim and the in-shell managed
            fallback (plus the ``enable_update_group``/``update_group_config``
            handling above) is skipped. Callers without a configerator deploy
            path (e.g. the standalone eb02 config) leave this ``None`` to get
            the in-shell fallback.

    Returns:
        TestConfig: The case-9 bounded-ECMP-sets TestConfig (consumed via
        `testconfigs.routing.ebb`).
    """
    # ---- BGP++ device setup ----
    # When the caller supplies setup_tasks (the standard
    # get_update_packing_setup_tasks path used by the bag012 conveyor
    # builder), use them as-is. Otherwise fall back to the in-shell managed
    # setup below (callers without a configerator deploy path, e.g. the
    # standalone eb02 config).
    if setup_tasks is None:
        # 1. Device interface IPs: configure the per-peer secondary addresses on
        #    both IXIA-facing interfaces (v6 + v4) so every bgpcpp peer has a local
        #    source address. WITHOUT this the sessions stay IDLE -- only whatever
        #    addresses a prior run happened to leave on the interface come up.
        #    clear_existing wipes stale addresses first. Offsets default to v4=10 /
        #    v6=16, matching the peer local_addrs generated below, and the helper
        #    rolls v4 octets into the next /24 for large peer counts.
        setup_tasks = [
            create_interface_ip_configuration_task(
                interface=ixia_interface_mimic_ebgp,
                peer_count=ebgp_peer_count_v6,
                ipv4_base_network=ixia_ebgp_ic_parent_network_v4,
                ipv6_base_network=ixia_ebgp_ic_parent_network_v6,
                address_families=["ipv6", "ipv4"],
                clear_existing=True,
                hostname=device_name,
                ixia_needed=True,
            ),
            create_interface_ip_configuration_task(
                interface=ixia_interface_mimic_ibgp,
                peer_count=ibgp_peer_count_v6,
                ipv4_base_network=ixia_ibgp_ic_parent_network_v4,
                ipv6_base_network=ixia_ibgp_ic_parent_network_v6,
                address_families=["ipv6", "ipv4"],
                clear_existing=True,
                hostname=device_name,
                ixia_needed=True,
            ),
        ]

        # 2. bgpcpp startup flag(s): replicate ConfigureBgpcppStartupTask's
        #    run_bgpcpp.sh edits (idempotent remove, extend the --max_rss_size line
        #    with a continuation, then insert the flag after it). The sed strings
        #    are copied verbatim from that task so escaping is identical.
        startup_flags = {"agent_thrift_recv_timeout_ms": "160000"}
        startup_flag_cmds = []
        for flag_name, flag_value in startup_flags.items():
            startup_flag_cmds += [
                f"bash sudo sed -i '/{flag_name}/d' {_RUN_BGPCPP_SCRIPT_PATH}",
                f"bash sudo sed -i '/--max_rss_size/s/[^\\\\]$/& \\\\/' "
                f"{_RUN_BGPCPP_SCRIPT_PATH}",
                f"bash sudo sed -i '/--max_rss_size/a\\      "
                f"--{flag_name}={flag_value}' {_RUN_BGPCPP_SCRIPT_PATH}",
            ]
        setup_tasks.append(
            create_run_commands_on_shell_task(
                hostname=device_name,
                cmds=startup_flag_cmds,
                set_outer_hostname=True,
                ixia_needed=True,
            )
        )

        # 3. Replace the bgpcpp peers (eBGP + iBGP, v6 + v4) in bgpcpp_config.
        #    router_id=None preserves the deployed config's router_id (the legacy
        #    in-shell peer-replace only swapped the 'peers' field). v6 peers start
        #    at ::10 (offset 16); v4 peers at .10 (offset 10) to match the IXIA
        #    side configured by create_ebb_bounded_ecmp_sets_port_configs.
        peers = (
            _generate_ixia_v6_peer_entries_for_bgpcpp(
                remote_as=ebgp_remote_as,
                ixia_ipv6_base=ixia_ebgp_ic_parent_network_v6,
                peer_count=ebgp_peer_count_v6,
                peer_group_v6=peergroup_ebgp_v6,
                start_offset=16,
            )
            + _generate_ixia_v4_peer_entries_for_bgpcpp(
                remote_as=ebgp_remote_as,
                ixia_ipv4_base=ixia_ebgp_ic_parent_network_v4,
                peer_count=ebgp_peer_count_v4,
                peer_group_v4=peergroup_ebgp_v4,
                start_offset=10,
            )
            + _generate_ixia_v6_peer_entries_for_bgpcpp(
                remote_as=ibgp_remote_as,
                ixia_ipv6_base=ixia_ibgp_ic_parent_network_v6,
                peer_count=ibgp_peer_count_v6,
                peer_group_v6=peergroup_ibgp_v6,
                start_offset=16,
            )
            + _generate_ixia_v4_peer_entries_for_bgpcpp(
                remote_as=ibgp_remote_as,
                ixia_ipv4_base=ixia_ibgp_ic_parent_network_v4,
                peer_count=ibgp_peer_count_v4,
                peer_group_v4=peergroup_ibgp_v4,
                start_offset=10,
            )
        )
        setup_tasks.extend(
            _generate_bgpcpp_peers_modification_tasks(
                bgpcpp_device=device_name,
                router_id=None,
                peers=peers,
            )
        )

        # 4. Optionally enable BGP++ update_group in bgpcpp_config (mirrors the
        #    BAG012 deployment patch). Applied on the bgpcpp restart below.
        if enable_update_group:
            ug_config = (
                update_group_config
                if update_group_config is not None
                else UPDATE_GROUP_CONFIG
            )
            setup_tasks.append(
                create_run_commands_on_shell_task(
                    hostname=device_name,
                    cmds=[
                        'bash python3 -c "'
                        "import json; "
                        f"f=open('{_BGPCPP_CONFIG_PATH}'); c=json.load(f); f.close(); "
                        "s=c.setdefault('bgp_setting_config',{}); "
                        "s['enable_update_group']=True; "
                        f"s['update_group_config']={ug_config!r}; "
                        f"f=open('{_BGPCPP_CONFIG_PATH}','w'); "
                        "json.dump(c,f,indent=2); f.close(); "
                        "print('Patched bgp_setting_config update_group')"
                        '"',
                    ],
                    set_outer_hostname=True,
                    ixia_needed=True,
                )
            )

        # 5. Validate the freshly written bgpcpp_config with the production
        #    /usr/sbin/bgp_config_validator BEFORE restarting BGP++, so a broken
        #    config (e.g. a malformed peer address) fails the setup task with a
        #    clear error here instead of crash-looping bgpcpp after the restart
        #    (same fail-fast gate as D107615556's deployment path).
        setup_tasks.append(
            create_validate_bgpcpp_config_on_device_task(
                hostname=device_name,
                config_path=_BGPCPP_CONFIG_PATH,
                ixia_needed=True,
            )
        )

        # 6. Restart bgpcpp LAST so it relaunches via run_bgpcpp.sh (picking up the
        #    new startup flag) and re-reads bgpcpp_config (new peers + update_group).
        #    disable -> enable is the netcastle-managed daemon bounce that re-runs
        #    the Bgp exec script (matches _get_control_plane_tasks).
        setup_tasks.append(
            create_arista_daemon_control_task(
                hostname=device_name,
                daemon_name="Bgp",
                action="disable",
                ixia_needed=True,
            )
        )
        setup_tasks.append(
            create_arista_daemon_control_task(
                hostname=device_name,
                daemon_name="Bgp",
                action="enable",
                ixia_needed=True,
            )
        )

    return TestConfig(
        name=test_config_name,
        skip_ixia_protocol_verification=True,
        log_collection_timeout=log_collection_timeout,
        basset_pool="dne.test",
        endpoints=[
            Endpoint(
                name=device_name,
                dut=True,
                ixia_ports=[ixia_interface_mimic_ebgp],
                direct_ixia_connections=(
                    direct_ixia_connections if direct_ixia_connections else []
                ),
            ),
        ],
        host_driver_args=host_driver_args,
        oss_mock_device_data=oss_mock_device_data,
        host_os_type_map=host_os_type_map,
        startup_checks=[],
        setup_tasks=setup_tasks,
        teardown_tasks=[],
        # Deprecated - define at playbook level
        # prechecks=[],
        # postchecks=[],
        # snapshot_checks=[],
        basic_port_configs=create_ebb_bounded_ecmp_sets_port_configs(
            device_name=device_name,
            ixia_interface_mimic_ebgp=ixia_interface_mimic_ebgp,
            ixia_interface_mimic_ibgp=ixia_interface_mimic_ibgp,
            ebgp_peer_count_v6=ebgp_peer_count_v6,
            ebgp_peer_count_v4=ebgp_peer_count_v4,
            ibgp_peer_count_v6=ibgp_peer_count_v6,
            ibgp_peer_count_v4=ibgp_peer_count_v4,
            ebgp_remote_as=ebgp_remote_as,
            ibgp_remote_as=ibgp_remote_as,
            prefix_count=prefix_count,
            ixia_ebgp_ic_parent_network_v6=ixia_ebgp_ic_parent_network_v6,
            ixia_ebgp_ic_parent_network_v4=ixia_ebgp_ic_parent_network_v4,
            ixia_ibgp_ic_parent_network_v6=ixia_ibgp_ic_parent_network_v6,
            ixia_ibgp_ic_parent_network_v4=ixia_ibgp_ic_parent_network_v4,
        ),
        playbooks=[
            create_bgp_plus_plus_arista_bounded_ecmp_sets_playbook(
                device_name=device_name,
            ),
        ],
    )
