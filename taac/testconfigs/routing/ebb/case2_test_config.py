# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""
TCP Socket Experiment — Case 2 Test Configuration.

Case 2: 1 eBGP session (bag013 → bag012) + 140 IXIA sessions on bag012.

Traffic Flow:
    IXIA ──(1 session, 15K prefixes)──→ bag013 (ar-bgp)
        bag013 ──(1 eBGP session, advertises 15K)──→ bag012 (BGP++)
            bag012 ──(redistributes to 140 IXIA sessions)──→ IXIA

Peer Configuration:
    bag012 (BGP++):  /mnt/flash/bgpcpp_config (JSON — created during setup)
    bag013 (ar-bgp): Standard EOS CLI (router bgp / neighbor)

Interface IP Addressing:
    - Interconnect link (Et3/1/1 only): 1 secondary IP each (/127 subnet)
    - IXIA link on bag012: 140 secondary IPs for 140 IXIA peers
    - IXIA link on bag013: 1 secondary IP for 1 IXIA peer (route injection)

All parameters are configurable via function arguments with defaults from constants.py.
"""

import typing as t

from taac.playbooks.playbook_definitions import (
    create_case2_tcp_socket_data_collection_playbook,
)
from taac.routing.ebb.ebb_bgp_plus_plus_test_config.tcp_socket_experiment.cleanup import (
    create_full_cleanup_tasks,
)
from taac.routing.ebb.ebb_bgp_plus_plus_test_config.tcp_socket_experiment.constants import (
    ACL_COMMANDS,
    ARBGP_PEERGROUP_EBGP_V4,
    ARBGP_PEERGROUP_EBGP_V6,
    ARBGP_PEERGROUP_IXIA_V4,
    ARBGP_PEERGROUP_IXIA_V6,
    BAG012_BGPCPP_AS,
    BAG012_DEVICE_NAME,
    BAG012_INTERCONNECT_INTERFACES,
    BAG012_IXIA_INTERFACE_1,
    BAG012_IXIA_PORT_1,
    BAG012_LOCAL_AS,
    BAG012_ROUTER_ID,
    BAG013_DEVICE_NAME,
    BAG013_INTERCONNECT_INTERFACES,
    BAG013_IXIA_INTERFACE_1,
    BAG013_IXIA_PORT_1,
    BAG013_LOCAL_AS,
    BAG013_ROUTER_ID,
    BGPCPP_BASE_CONFIG_CONFIGERATOR_PATH,
    BGPCPP_CONFIG_PATH,
    BGPCPP_DAEMONS,
    BGPCPP_EGRESS_POLICY_EBGP,
    BGPCPP_EGRESS_POLICY_IXIA,
    BGPCPP_PEERGROUP_EBGP_V4,
    BGPCPP_PEERGROUP_EBGP_V6,
    BGPCPP_PEERGROUP_IXIA_V4,
    BGPCPP_PEERGROUP_IXIA_V6,
    FIBAGENT_BGP_CONF_DEPLOY_CMD,
    FIBAGENT_CONF_DEPLOY_CMD,
    INTERCONNECT_IPV4_BASES,
    INTERCONNECT_IPV4_START_OFFSET,
    INTERCONNECT_IPV6_BASE,
    INTERCONNECT_IPV6_START_OFFSET,
    IXIA_AS,
    IXIA_BAG012_IPV4_BASE,
    IXIA_BAG012_IPV6_BASE,
    IXIA_BAG013_IPV4_BASE,
    IXIA_BAG013_IPV6_BASE,
    IXIA_CHASSIS,
    IXIA_IBGP_COMMUNITIES,
    IXIA_PREFIX_COUNT,
    TCP_DATA_COLLECTION_SCRIPT,
    TCP_DATA_COLLECTION_SCRIPT_DEPLOY_CMD,
    TCP_DATA_CONVERGENCE_TIME_SECONDS,
    TCP_DATA_SAMPLE_INTERVAL_SECONDS,
)
from taac.routing.ebb.ebb_bgp_plus_plus_test_config.tcp_socket_experiment.ixia_config import (
    create_case2_basic_port_configs,
)
from taac.task_definitions import (
    create_arista_create_file_from_config_task,
    create_arista_daemon_control_task,
    create_interface_ip_configuration_task,
    create_run_commands_on_shell_task,
)
from taac.testconfigs.routing.ebb.case1_test_config import (
    _generate_bgpcpp_peers_modification_tasks,
    _generate_ixia_peer_entries_for_bgpcpp,
    _generate_peer_entries_for_interconnect,
)
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import DirectIxiaConnection, Endpoint, TestConfig


def _generate_arbgp_case2_commands(
    local_as: int,
    remote_as: int,
    ixia_as: int,
    router_id: str,
    interconnect_interface: str,
    ipv6_base: str,
    ipv4_bases: t.List[str],
    ipv6_start_offset: int,
    ipv4_start_offset: int,
    peergroup_ebgp_v6: str,
    peergroup_ebgp_v4: str,
    ixia_interface: str,
    ixia_ipv6_base: str,
    ixia_ipv4_base: str,
    peergroup_ixia_v6: str,
    peergroup_ixia_v4: str,
) -> t.List[str]:
    """
    Generate EOS CLI commands for bag013 (ar-bgp) in Case 2.

    Configures:
    - 1 eBGP session towards bag012 (BGP++)
    - 1 IXIA-facing session (for route injection — IXIA sends 15K routes in)
    """
    # For 1 session: bgpcpp side gets even offset (.10), ar-bgp gets odd (.11)
    v6_peer = f"{ipv6_base}::{ipv6_start_offset:x}"
    v4_peer_last = ipv4_start_offset

    config_lines = [
        "configure",
        f"router bgp {local_as}",
        "maximum-paths 140 ecmp 140",
        "",
        # eBGP peer group towards bag012
        f"neighbor {peergroup_ebgp_v6} peer group",
        f"neighbor {peergroup_ebgp_v6} remote-as {remote_as}",
        "address-family ipv6",
        f"neighbor {peergroup_ebgp_v6} activate",
        "!",
        f"neighbor {peergroup_ebgp_v4} peer group",
        f"neighbor {peergroup_ebgp_v4} remote-as {remote_as}",
        "address-family ipv4",
        f"neighbor {peergroup_ebgp_v4} activate",
        "!",
        # Single eBGP neighbor towards bag012
        f"neighbor {v6_peer} peer group {peergroup_ebgp_v6}",
        f"neighbor {ipv4_bases[0]}.{v4_peer_last} peer group {peergroup_ebgp_v4}",
        "",
        # IXIA-facing peer group (for route injection into bag013)
        f"neighbor {peergroup_ixia_v6} peer group",
        f"neighbor {peergroup_ixia_v6} remote-as {ixia_as}",
        "address-family ipv6",
        f"neighbor {peergroup_ixia_v6} activate",
        "!",
        f"neighbor {peergroup_ixia_v4} peer group",
        f"neighbor {peergroup_ixia_v4} remote-as {ixia_as}",
        "address-family ipv4",
        f"neighbor {peergroup_ixia_v4} activate",
        "!",
        # Single IXIA neighbor
        f"neighbor {ixia_ipv6_base}::b peer group {peergroup_ixia_v6}",
        f"neighbor {ixia_ipv4_base}.11 peer group {peergroup_ixia_v4}",
        "end",
    ]

    return ["\n".join(config_lines)]


def create_case2_test_config(
    bgpcpp_device: str = BAG012_DEVICE_NAME,
    arbgp_device: str = BAG013_DEVICE_NAME,
    bgpcpp_local_as: int = BAG012_LOCAL_AS,
    bgpcpp_as: int = BAG012_BGPCPP_AS,
    arbgp_local_as: int = BAG013_LOCAL_AS,
    bgpcpp_router_id: str = BAG012_ROUTER_ID,
    arbgp_router_id: str = BAG013_ROUTER_ID,
    ixia_as: int = IXIA_AS,
    ixia_peer_count_to_bgpcpp: int = 140,
    ixia_prefix_count: int = IXIA_PREFIX_COUNT,
    bgpcpp_interconnect_interface: t.Optional[str] = None,
    arbgp_interconnect_interface: t.Optional[str] = None,
    bgpcpp_ixia_interface: str = BAG012_IXIA_INTERFACE_1,
    bgpcpp_ixia_port: str = BAG012_IXIA_PORT_1,
    arbgp_ixia_interface: str = BAG013_IXIA_INTERFACE_1,
    arbgp_ixia_port: str = BAG013_IXIA_PORT_1,
    ixia_chassis: str = IXIA_CHASSIS,
    ipv6_base: str = INTERCONNECT_IPV6_BASE,
    ipv4_bases: t.Optional[t.List[str]] = None,
    ipv6_start_offset: int = INTERCONNECT_IPV6_START_OFFSET,
    ipv4_start_offset: int = INTERCONNECT_IPV4_START_OFFSET,
    ixia_bgpcpp_ipv6_base: str = IXIA_BAG012_IPV6_BASE,
    ixia_bgpcpp_ipv4_base: str = IXIA_BAG012_IPV4_BASE,
    ixia_arbgp_ipv6_base: str = IXIA_BAG013_IPV6_BASE,
    ixia_arbgp_ipv4_base: str = IXIA_BAG013_IPV4_BASE,
    bgpcpp_peergroup_ebgp_v6: str = BGPCPP_PEERGROUP_EBGP_V6,
    bgpcpp_peergroup_ebgp_v4: str = BGPCPP_PEERGROUP_EBGP_V4,
    bgpcpp_peergroup_ixia_v6: str = BGPCPP_PEERGROUP_IXIA_V6,
    bgpcpp_peergroup_ixia_v4: str = BGPCPP_PEERGROUP_IXIA_V4,
    bgpcpp_egress_policy_ebgp: str = BGPCPP_EGRESS_POLICY_EBGP,
    bgpcpp_egress_policy_ixia: str = BGPCPP_EGRESS_POLICY_IXIA,
    arbgp_peergroup_ebgp_v6: str = ARBGP_PEERGROUP_EBGP_V6,
    arbgp_peergroup_ebgp_v4: str = ARBGP_PEERGROUP_EBGP_V4,
    arbgp_peergroup_ixia_v6: str = ARBGP_PEERGROUP_IXIA_V6,
    arbgp_peergroup_ixia_v4: str = ARBGP_PEERGROUP_IXIA_V4,
    communities: str = IXIA_IBGP_COMMUNITIES,
    skip_infra_setup: bool = False,
    skip_teardown: bool = False,
    tcp_convergence_time: int = TCP_DATA_CONVERGENCE_TIME_SECONDS,
    tcp_sample_interval: int = TCP_DATA_SAMPLE_INTERVAL_SECONDS,
) -> TestConfig:
    """
    Create test configuration for Case 2.

    Case 2: 1 eBGP session between bag013 (ar-bgp) and bag012 (BGP++),
    plus 140 IXIA peers on bag012. IXIA injects 15K routes into bag013,
    bag013 advertises them to bag012 via the single eBGP session, and
    bag012 redistributes to 140 IXIA peers.

    Incremental Run Support:
        skip_infra_setup=True: Skips all device setup (daemons, interfaces,
            IPs, peers). Use when infra from a previous run is still valid
            and you only need to change IXIA parameters (e.g., prefix count).
            The IXIA BasicPortConfig is always regenerated.
        skip_teardown=True: Skips cleanup after the test, keeping all
            device config in place for the next run.

    Args:
        bgpcpp_device: BGP++ device hostname
        arbgp_device: ar-bgp device hostname
        bgpcpp_local_as: Local AS for BGP++ device
        arbgp_local_as: Local AS for ar-bgp device
        bgpcpp_router_id: Router ID for BGP++ device
        arbgp_router_id: Router ID for ar-bgp device
        ixia_as: IXIA simulated AS
        ixia_peer_count_to_bgpcpp: IXIA sessions towards bag012 (default: 140)
        ixia_prefix_count: Prefixes injected by IXIA into bag013 (default: 15000)
        bgpcpp_interconnect_interface: Interconnect interface on bag012
        arbgp_interconnect_interface: Interconnect interface on bag013
        bgpcpp_ixia_interface: IXIA interface on bag012
        bgpcpp_ixia_port: IXIA chassis port for bag012
        arbgp_ixia_interface: IXIA interface on bag013
        arbgp_ixia_port: IXIA chassis port for bag013
        ixia_chassis: IXIA chassis hostname
        ipv6_base: IPv6 base for interconnect addressing
        ipv4_base: IPv4 base for interconnect addressing
        ipv6_start_offset: Starting offset for IPv6 addresses
        ipv4_start_offset: Starting offset for IPv4 addresses
        ixia_bgpcpp_ipv6_base: IPv6 base for IXIA↔bag012 peering
        ixia_bgpcpp_ipv4_base: IPv4 base for IXIA↔bag012 peering
        ixia_arbgp_ipv6_base: IPv6 base for IXIA↔bag013 peering
        ixia_arbgp_ipv4_base: IPv4 base for IXIA↔bag013 peering
        peergroup_ebgp_v6: Peer group name for eBGP IPv6
        peergroup_ebgp_v4: Peer group name for eBGP IPv4
        peergroup_ixia_v6: Peer group name for IXIA IPv6
        peergroup_ixia_v4: Peer group name for IXIA IPv4
        route_file_v6: Optional IXIA route file for IPv6
        route_file_v4: Optional IXIA route file for IPv4
        communities: BGP community string

    Returns:
        TestConfig for Case 2
    """
    # Use first interconnect link only (1 eBGP session)
    if bgpcpp_interconnect_interface is None:
        bgpcpp_interconnect_interface = BAG012_INTERCONNECT_INTERFACES[0]
    if arbgp_interconnect_interface is None:
        arbgp_interconnect_interface = BAG013_INTERCONNECT_INTERFACES[0]
    if ipv4_bases is None:
        ipv4_bases = INTERCONNECT_IPV4_BASES

    # =========================================================================
    # 1. Generate BGP++ peer entries (for /mnt/flash/bgpcpp_config)
    # =========================================================================
    # 1 inter-device iBGP peer (single session on first link)
    # Case 2 uses EB-EB (iBGP) for interconnect — route source comes via iBGP
    bgpcpp_ebgp_peers = _generate_peer_entries_for_interconnect(
        local_as=bgpcpp_local_as,
        remote_as=arbgp_local_as,
        interconnect_interfaces=[bgpcpp_interconnect_interface],
        sessions_per_link=1,
        ipv6_base=ipv6_base,
        ipv4_bases=[ipv4_bases[0]],
        ipv6_start_offset=ipv6_start_offset,
        ipv4_start_offset=ipv4_start_offset,
        peer_group_v6=bgpcpp_peergroup_ixia_v6,
        peer_group_v4=bgpcpp_peergroup_ixia_v4,
        egress_policy_name=bgpcpp_egress_policy_ixia,
        is_bgpcpp_side=True,
    )

    # 140 IXIA-facing peers on bag012 (redistribute routes via eBGP)
    # Case 2 uses EB-FA (eBGP) for IXIA — route distribution via eBGP
    bgpcpp_ixia_peers = _generate_ixia_peer_entries_for_bgpcpp(
        remote_as=ixia_as,
        ixia_ipv6_base=ixia_bgpcpp_ipv6_base,
        ixia_ipv4_base=ixia_bgpcpp_ipv4_base,
        peer_count=ixia_peer_count_to_bgpcpp,
        peer_group_v6=bgpcpp_peergroup_ebgp_v6,
        peer_group_v4=bgpcpp_peergroup_ebgp_v4,
        egress_policy_name=bgpcpp_egress_policy_ebgp,
    )

    all_bgpcpp_peers = bgpcpp_ebgp_peers + bgpcpp_ixia_peers

    # =========================================================================
    # 2. Generate ar-bgp EOS CLI commands for bag013
    # =========================================================================
    arbgp_cmds = _generate_arbgp_case2_commands(
        local_as=arbgp_local_as,
        remote_as=bgpcpp_as,
        ixia_as=ixia_as,
        router_id=arbgp_router_id,
        interconnect_interface=arbgp_interconnect_interface,
        ipv6_base=ipv6_base,
        ipv4_bases=[ipv4_bases[0]],
        ipv6_start_offset=ipv6_start_offset,
        ipv4_start_offset=ipv4_start_offset,
        peergroup_ebgp_v6=arbgp_peergroup_ebgp_v6,
        peergroup_ebgp_v4=arbgp_peergroup_ebgp_v4,
        ixia_interface=arbgp_ixia_interface,
        ixia_ipv6_base=ixia_arbgp_ipv6_base,
        ixia_ipv4_base=ixia_arbgp_ipv4_base,
        peergroup_ixia_v6=arbgp_peergroup_ixia_v6,
        peergroup_ixia_v4=arbgp_peergroup_ixia_v4,
    )

    # =========================================================================
    # 3. Build setup tasks
    # =========================================================================
    setup_tasks = []

    # --- PRE-IXIA: Configure IXIA interfaces so they're UP before IXIA connects ---
    # After device reload, interface config (speed, switchport) is lost.
    # These MUST run before IXIA setup (ixia_needed=False).
    # bag012 IXIA interface
    setup_tasks.append(
        create_run_commands_on_shell_task(
            hostname=bgpcpp_device,
            cmds=[
                "configure\n"
                f"interface {bgpcpp_ixia_interface}\n"
                "description IXIA_TCP_EXP\n"
                "no shutdown\n"
                "speed 100g-2\n"
                "no switchport\n"
                "ipv6 enable\n"
                "end",
            ],
            ixia_needed=False,
        )
    )
    # bag013 IXIA interface
    setup_tasks.append(
        create_run_commands_on_shell_task(
            hostname=arbgp_device,
            cmds=[
                "configure\n"
                f"interface {arbgp_ixia_interface}\n"
                "description IXIA_TCP_EXP\n"
                "no shutdown\n"
                "speed 100g-2\n"
                "no switchport\n"
                "ipv6 enable\n"
                "end",
            ],
            ixia_needed=False,
        )
    )

    if not skip_infra_setup:
        # --- Pre-cleanup: Remove any stale config from a previous run ---
        setup_tasks.extend(
            create_full_cleanup_tasks(
                bgpcpp_device=bgpcpp_device,
                arbgp_device=arbgp_device,
                bgpcpp_local_as=bgpcpp_local_as,
                arbgp_local_as=arbgp_local_as,
                bgpcpp_ixia_interfaces=[bgpcpp_ixia_interface],
                arbgp_ixia_interfaces=[arbgp_ixia_interface],
            )
        )

        # 3a. Create required directories on bag012
        setup_tasks.append(
            create_run_commands_on_shell_task(
                hostname=bgpcpp_device,
                cmds=[
                    "bash mkdir -p /usr/facebook/thrift_acls",
                    "bash mkdir -p /mnt/fb/agent_configs",
                ],
                ixia_needed=True,
            )
        )

        # 3b. Shutdown native EOS BGP on bag012
        setup_tasks.append(
            create_run_commands_on_shell_task(
                hostname=bgpcpp_device,
                cmds=[
                    "configure\nrouter bgp {}\nshutdown\nend".format(bgpcpp_local_as)
                ],
                ixia_needed=True,
            )
        )

        # 3c. Deploy base bgpcpp_config from configerator to bag012
        # This gives us all peer_groups, policies, communities, localprefs, etc.
        setup_tasks.append(
            create_arista_create_file_from_config_task(
                hostname=bgpcpp_device,
                configerator_path=BGPCPP_BASE_CONFIG_CONFIGERATOR_PATH,
                file_path=BGPCPP_CONFIG_PATH,
                ixia_needed=True,
            )
        )

        # 3d. Modify bgpcpp_config: replace peers, router_id, and local_as_4_byte
        # For Case 2 iBGP: set local_as_4_byte to match bag013 AS (65013)
        # Uses base64 to avoid EOS shell command length limits
        setup_tasks.extend(
            _generate_bgpcpp_peers_modification_tasks(
                bgpcpp_device=bgpcpp_device,
                router_id=bgpcpp_router_id,
                peers=all_bgpcpp_peers,
                local_as_4_byte=bgpcpp_as,
            )
        )

        # 3e. FibAgent.json is already deployed with the EOS image
        # (arista_create_file_from_config silently fails on this device)

        # 3f. Deploy fib_agent_bgp.conf via embedded base64
        setup_tasks.append(
            create_run_commands_on_shell_task(
                hostname=bgpcpp_device,
                cmds=[FIBAGENT_BGP_CONF_DEPLOY_CMD],
                ixia_needed=True,
            )
        )

        # 3f-2. Deploy fib_agent.conf via embedded base64
        setup_tasks.append(
            create_run_commands_on_shell_task(
                hostname=bgpcpp_device,
                cmds=[FIBAGENT_CONF_DEPLOY_CMD],
                ixia_needed=True,
            )
        )

        # 3g. Add control plane ACLs on bag012
        setup_tasks.append(
            create_run_commands_on_shell_task(
                hostname=bgpcpp_device,
                cmds=[ACL_COMMANDS],
                ixia_needed=True,
            )
        )

        # 3g-2. Add control plane ACLs on bag013
        setup_tasks.append(
            create_run_commands_on_shell_task(
                hostname=arbgp_device,
                cmds=[ACL_COMMANDS],
                ixia_needed=True,
            )
        )

        # 3g-3. Flush EOS_BGP iptables chain on bag012 to allow BGP++ connections
        # Native EOS BGP's BGPSACL creates iptables DROP rules that block BGP++.
        # Since BGP++ manages its own peers, we flush EOS_BGP and set ACCEPT.
        setup_tasks.append(
            create_run_commands_on_shell_task(
                hostname=bgpcpp_device,
                cmds=[
                    'bash -c "iptables -F EOS_BGP && iptables -A EOS_BGP -j ACCEPT"',
                    'bash -c "ip6tables -F EOS_BGP && ip6tables -A EOS_BGP -j ACCEPT"',
                ],
                ixia_needed=True,
            )
        )

        # 3h. Deploy collect_tcp_data.sh script to bag012
        setup_tasks.append(
            create_run_commands_on_shell_task(
                hostname=bgpcpp_device,
                cmds=[TCP_DATA_COLLECTION_SCRIPT_DEPLOY_CMD],
                ixia_needed=True,
            )
        )

        # 3e. Enable BGP++ daemons on bag012
        for daemon in BGPCPP_DAEMONS:
            setup_tasks.append(
                create_arista_daemon_control_task(
                    hostname=bgpcpp_device,
                    daemon_name=daemon,
                    action="enable",
                    ixia_needed=True,
                )
            )

        # 3f. Configure interfaces on bag012 (interconnect + IXIA)
        intf_config_lines = [
            "configure",
            f"interface {bgpcpp_interconnect_interface}",
            "description TCP_EXP_INTERCONNECT",
            "mtu 9000",
            "no switchport",
            "ipv6 enable",
            "!",
            f"interface {bgpcpp_ixia_interface}",
            "description TCP_EXP_IXIA_140_PEERS",
            "mtu 9000",
            "no switchport",
            "ipv6 enable",
            "!",
            "end",
        ]
        setup_tasks.append(
            create_run_commands_on_shell_task(
                hostname=bgpcpp_device,
                cmds=["\n".join(intf_config_lines)],
                ixia_needed=True,
            )
        )

        # 3g. Configure secondary IPs on bag012 interconnect (1 peer)
        setup_tasks.append(
            create_interface_ip_configuration_task(
                interface=bgpcpp_interconnect_interface,
                peer_count=1,
                ipv4_base_network=ipv4_bases[0],
                ipv6_base_network=ipv6_base,
                address_families=["ipv4", "ipv6"],
                clear_existing=True,
                ipv4_start_offset=ipv4_start_offset,
                ipv6_start_offset=ipv6_start_offset,
                hostname=bgpcpp_device,
                ixia_needed=True,
            )
        )

        # 3h. Configure secondary IPs on bag012 IXIA interface (140 peers)
        setup_tasks.append(
            create_interface_ip_configuration_task(
                interface=bgpcpp_ixia_interface,
                peer_count=ixia_peer_count_to_bgpcpp,
                ipv4_base_network=ixia_bgpcpp_ipv4_base,
                ipv6_base_network=ixia_bgpcpp_ipv6_base,
                address_families=["ipv4", "ipv6"],
                clear_existing=True,
                ipv4_start_offset=10,
                ipv6_start_offset=10,
                hostname=bgpcpp_device,
                ixia_needed=True,
            )
        )

        # --- bag013 (ar-bgp) setup ---

        # 3i. Configure interfaces on bag013 (interconnect + IXIA)
        arbgp_intf_config_lines = [
            "configure",
            f"interface {arbgp_interconnect_interface}",
            "description TCP_EXP_INTERCONNECT",
            "mtu 9000",
            "no switchport",
            "ipv6 enable",
            "!",
            f"interface {arbgp_ixia_interface}",
            "description TCP_EXP_IXIA_ROUTE_INJECT",
            "mtu 9000",
            "no switchport",
            "ipv6 enable",
            "!",
            "end",
        ]
        setup_tasks.append(
            create_run_commands_on_shell_task(
                hostname=arbgp_device,
                cmds=["\n".join(arbgp_intf_config_lines)],
                ixia_needed=True,
            )
        )

        # 3j. Configure secondary IPs on bag013 interconnect (1 peer)
        # bag013 (ar-bgp) gets odd offsets (+1) for /31 and /127 subnets
        setup_tasks.append(
            create_interface_ip_configuration_task(
                interface=arbgp_interconnect_interface,
                peer_count=1,
                ipv4_base_network=ipv4_bases[0],
                ipv6_base_network=ipv6_base,
                address_families=["ipv4", "ipv6"],
                clear_existing=True,
                ipv4_start_offset=ipv4_start_offset + 1,
                ipv6_start_offset=ipv6_start_offset + 1,
                hostname=arbgp_device,
                ixia_needed=True,
            )
        )

        # 3k. Configure secondary IPs on bag013 IXIA interface (1 peer)
        setup_tasks.append(
            create_interface_ip_configuration_task(
                interface=arbgp_ixia_interface,
                peer_count=1,
                ipv4_base_network=ixia_arbgp_ipv4_base,
                ipv6_base_network=ixia_arbgp_ipv6_base,
                address_families=["ipv4", "ipv6"],
                clear_existing=True,
                ipv4_start_offset=10,
                ipv6_start_offset=10,
                hostname=arbgp_device,
                ixia_needed=True,
            )
        )

        # 3l. Configure BGP on bag013 via EOS CLI (1 eBGP + 1 IXIA peer)
        setup_tasks.append(
            create_run_commands_on_shell_task(
                hostname=arbgp_device,
                cmds=arbgp_cmds,
                ixia_needed=True,
            )
        )

    # =========================================================================
    # 4. Build teardown tasks — full cleanup so next case starts clean
    #    Set skip_teardown=True to keep infra in place for a re-run
    # =========================================================================
    if skip_teardown:
        teardown_tasks = []
    else:
        teardown_tasks = create_full_cleanup_tasks(
            bgpcpp_device=bgpcpp_device,
            arbgp_device=arbgp_device,
            bgpcpp_local_as=bgpcpp_local_as,
            arbgp_local_as=arbgp_local_as,
            bgpcpp_ixia_interfaces=[bgpcpp_ixia_interface],
            arbgp_ixia_interfaces=[arbgp_ixia_interface],
            include_interface_cleanup=True,
        )

    # =========================================================================
    # 5. Build and return TestConfig
    # =========================================================================
    return TestConfig(
        name="TCP_SOCKET_EXP_CASE2_1_EBGP_140_IXIA",
        skip_ixia_protocol_verification=True,
        log_collection_timeout=600,
        basset_pool="dne.test",
        endpoints=[
            Endpoint(
                name=bgpcpp_device,
                dut=True,
                ixia_ports=[bgpcpp_ixia_interface],
                direct_ixia_connections=[
                    DirectIxiaConnection(
                        interface=bgpcpp_ixia_interface,
                        ixia_chassis_ip=ixia_chassis,
                        ixia_port=bgpcpp_ixia_port,
                    ),
                ],
            ),
            Endpoint(
                name=arbgp_device,
                dut=False,
                ixia_ports=[arbgp_ixia_interface],
                direct_ixia_connections=[
                    DirectIxiaConnection(
                        interface=arbgp_ixia_interface,
                        ixia_chassis_ip=ixia_chassis,
                        ixia_port=arbgp_ixia_port,
                    ),
                ],
            ),
        ],
        host_os_type_map={
            bgpcpp_device: taac_types.DeviceOsType.ARISTA_FBOSS,
            arbgp_device: taac_types.DeviceOsType.ARISTA_OS,
        },
        startup_checks=[],
        setup_tasks=setup_tasks,
        teardown_tasks=teardown_tasks,
        # Deprecated - define at playbook level
        # prechecks=[],
        # postchecks=[],
        # snapshot_checks=[],
        basic_port_configs=create_case2_basic_port_configs(
            bgpcpp_device_name=bgpcpp_device,
            bgpcpp_ixia_interface=bgpcpp_ixia_interface,
            arbgp_device_name=arbgp_device,
            arbgp_ixia_interface=arbgp_ixia_interface,
            ixia_peer_count_to_bgpcpp=ixia_peer_count_to_bgpcpp,
            ixia_peer_count_to_arbgp=1,
            ixia_as=ixia_as,
            ixia_bgpcpp_ipv6_base=ixia_bgpcpp_ipv6_base,
            ixia_bgpcpp_ipv4_base=ixia_bgpcpp_ipv4_base,
            ixia_arbgp_ipv6_base=ixia_arbgp_ipv6_base,
            ixia_arbgp_ipv4_base=ixia_arbgp_ipv4_base,
            prefix_count=ixia_prefix_count,
            communities=communities,
        ),
        playbooks=[
            create_case2_tcp_socket_data_collection_playbook(
                bgpcpp_device=bgpcpp_device,
                tcp_data_collection_script=TCP_DATA_COLLECTION_SCRIPT,
                tcp_convergence_time=tcp_convergence_time,
                tcp_sample_interval=tcp_sample_interval,
            ),
        ],
    )


# Export a default instance for convenience
# bgpcpp_as=BAG013_LOCAL_AS sets local_as_4_byte to 65013 in bgpcpp_config
# so BGP++ uses the same AS as bag013 — making the interconnect iBGP
CASE2_TEST_CONFIG = create_case2_test_config(bgpcpp_as=BAG013_LOCAL_AS)
