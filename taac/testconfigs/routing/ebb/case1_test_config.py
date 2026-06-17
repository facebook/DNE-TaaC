# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""
TCP Socket Experiment — Case 1 Test Configuration.

Case 1: 140 eBGP sessions (bag013 ↔ bag012) + 1 IXIA → bag012 with 15K prefixes.

Traffic Flow:
    IXIA ──(1 BGP session, 15K prefixes)──→ bag012 (BGP++)
        bag012 ──(redistributes via 140 eBGP sessions)──→ bag013 (ar-bgp)

Peer Configuration:
    bag012 (BGP++):  /mnt/flash/bgpcpp_config (JSON — created during setup)
    bag013 (ar-bgp): Standard EOS CLI (router bgp / neighbor)

Interface IP Addressing:
    - Interconnect links (Et3/1/1, Et3/2/1): 70 secondary IPs each (/127 subnets)
    - IXIA link on bag012: 1 secondary IP for single IXIA peer

All parameters are configurable via function arguments with defaults from constants.py.
"""

import base64 as _b64_mod
import json
import typing as t
from ipaddress import IPv4Address

from taac.playbooks.playbook_definitions import (
    create_case1_tcp_socket_data_collection_playbook,
)
from taac.routing.ebb.ebb_bgp_plus_plus_test_config.tcp_socket_experiment.cleanup import (
    create_full_cleanup_tasks,
)
from taac.routing.ebb.ebb_bgp_plus_plus_test_config.tcp_socket_experiment.constants import (
    ACL_COMMANDS,
    ARBGP_PEERGROUP_EBGP_V4,
    ARBGP_PEERGROUP_EBGP_V6,
    BAG012_BGPCPP_AS,
    BAG012_DEVICE_NAME,
    BAG012_INTERCONNECT_INTERFACES,
    BAG012_IXIA_INTERFACE_1,
    BAG012_IXIA_PORT_1,
    BAG012_LOCAL_AS,
    BAG012_ROUTER_ID,
    BAG013_DEVICE_NAME,
    BAG013_INTERCONNECT_INTERFACES,
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
    EBGP_SESSIONS_PER_LINK,
    FIBAGENT_BGP_CONF_DEPLOY_CMD,
    FIBAGENT_CONF_DEPLOY_CMD,
    INTERCONNECT_IPV4_BASES,
    INTERCONNECT_IPV4_START_OFFSET,
    INTERCONNECT_IPV6_BASE,
    INTERCONNECT_IPV6_START_OFFSET,
    IXIA_AS,
    IXIA_BAG012_IPV4_BASE,
    IXIA_BAG012_IPV6_BASE,
    IXIA_CHASSIS,
    IXIA_IBGP_COMMUNITIES,
    IXIA_PREFIX_COUNT,
    TCP_DATA_COLLECTION_SCRIPT,
    TCP_DATA_COLLECTION_SCRIPT_DEPLOY_CMD,
    TCP_DATA_CONVERGENCE_TIME_SECONDS,
    TCP_DATA_SAMPLE_INTERVAL_SECONDS,
)
from taac.routing.ebb.ebb_bgp_plus_plus_test_config.tcp_socket_experiment.ixia_config import (
    create_case1_basic_port_configs,
)
from taac.task_definitions import (
    create_arista_create_file_from_config_task,
    create_arista_daemon_control_task,
    create_interface_ip_configuration_task,
    create_run_commands_on_shell_task,
)
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import DirectIxiaConnection, Endpoint, Task, TestConfig


# =============================================================================
# Helper: Generate bgpcpp_config modification tasks
# =============================================================================
def _generate_bgpcpp_peers_modification_tasks(
    bgpcpp_device: str,
    router_id: t.Optional[str],
    peers: t.List[t.Dict[str, t.Any]],
    config_path: str = BGPCPP_CONFIG_PATH,
    local_as_4_byte: t.Optional[int] = None,
) -> t.List[Task]:
    """
    Generate tasks to modify the deployed bgpcpp_config.

    The base bgpcpp_config is first deployed from configerator (with all
    peer_groups, policies, communities, localprefs, etc.). These tasks
    replace ONLY the 'peers' and 'router_id' fields, preserving
    everything else (including local_as_4_byte from the base config,
    unless local_as_4_byte is explicitly provided for iBGP scenarios).

    Uses base64 encoding to avoid shell command length limits — the 282
    peers JSON is ~50KB which exceeds EOS shell limits when passed inline.

    Args:
        bgpcpp_device: BGP++ device hostname
        router_id: BGP router ID for bag012
        peers: List of peer dicts to replace in the config
        config_path: Path to bgpcpp_config on the device
        local_as_4_byte: If provided, override BGP++ AS (e.g., 65013 for
            Case 2 iBGP). If None, keep the base config's value (64981).

    Returns:
        List of Task objects (write peers file + run python3 merge script)
    """
    peers_json = json.dumps(peers)
    peers_b64 = _b64_mod.b64encode(peers_json.encode()).decode()

    # Chunk the base64 string into 20KB pieces to avoid EOS shell limits
    chunk_size = 20000
    chunks = [
        peers_b64[i : i + chunk_size] for i in range(0, len(peers_b64), chunk_size)
    ]

    tasks = []

    # Step 1: Write base64-encoded peers in chunks to a temp file
    chunk_cmds = []
    for i, chunk in enumerate(chunks):
        if i == 0:
            chunk_cmds.append(f"bash echo '{chunk}' > /tmp/peers.b64")
        else:
            chunk_cmds.append(f"bash echo '{chunk}' >> /tmp/peers.b64")
    # Decode the base64 file to JSON
    chunk_cmds.append("bash base64 -d /tmp/peers.b64 > /tmp/experiment_peers.json")
    chunk_cmds.append("bash rm -f /tmp/peers.b64")

    tasks.append(
        create_run_commands_on_shell_task(
            hostname=bgpcpp_device,
            cmds=chunk_cmds,
            ixia_needed=True,
        )
    )

    # Step 2: Short python3 script reads peers from temp file and merges
    local_as_line = ""
    if local_as_4_byte is not None:
        local_as_line = f"c['local_as_4_byte']={local_as_4_byte}; "
    # router_id is optional: when None we preserve the deployed config's
    # router_id (matching the legacy in-shell peer-replace behavior, which
    # only swapped the 'peers' field and never touched router_id).
    router_id_line = ""
    if router_id is not None:
        router_id_line = f"c['router_id']='{router_id}'; "
    merge_script = (
        f'python3 -c "'
        f"import json; "
        f"f=open('{config_path}'); c=json.load(f); f.close(); "
        f"p=open('/tmp/experiment_peers.json'); "
        f"c['peers']=json.load(p); p.close(); "
        f"{router_id_line}"
        f"{local_as_line}"
        f"f=open('{config_path}','w'); "
        f"json.dump(c,f,indent=2); f.close(); "
        f"print('Updated peers:',len(c['peers']),"
        f"'router_id:',c['router_id'],"
        f"'local_as_4_byte:',c.get('local_as_4_byte'))"
        f'"'
    )
    tasks.append(
        create_run_commands_on_shell_task(
            hostname=bgpcpp_device,
            cmds=[f"bash {merge_script}"],
            ixia_needed=True,
        )
    )

    return tasks


def _generate_peer_entries_for_interconnect(
    local_as: int,
    remote_as: int,
    interconnect_interfaces: t.List[str],
    sessions_per_link: int,
    ipv6_base: str,
    ipv4_bases: t.List[str],
    ipv6_start_offset: int,
    ipv4_start_offset: int,
    peer_group_v6: str,
    peer_group_v4: str,
    egress_policy_name: str = "",
    is_bgpcpp_side: bool = True,
) -> t.List[t.Dict[str, t.Any]]:
    """
    Generate BGP peer entries for the inter-device eBGP sessions.

    Creates secondary IP addressed peers across multiple physical links.
    For /127 subnets: BGP++ side gets even offsets, ar-bgp gets odd offsets.
    Uses separate IPv4 base network per link to avoid overflow past .255.

    Args:
        local_as: Local AS of this device
        remote_as: Remote AS of the peer device
        interconnect_interfaces: List of physical interfaces to distribute peers
        sessions_per_link: Number of sessions per physical link
        ipv6_base: IPv6 base network (e.g., "2401:db00:e700:11:8")
        ipv4_base: IPv4 base network (e.g., "10.200.28")
        ipv6_start_offset: Starting offset for IPv6 addresses
        ipv4_start_offset: Starting offset for IPv4 addresses
        peer_group_v6: Peer group name for IPv6 sessions
        peer_group_v4: Peer group name for IPv4 sessions
        is_bgpcpp_side: True if generating for BGP++ side (even addrs),
                       False for ar-bgp side (odd addrs)
    """
    peers = []
    # For /127: bgpcpp gets .10, .12, .14 ... ; ar-bgp gets .11, .13, .15 ...
    local_offset = 0 if is_bgpcpp_side else 1
    peer_offset = 1 if is_bgpcpp_side else 0

    session_idx = 0
    for _link_idx, _interface in enumerate(interconnect_interfaces):
        # Each link gets its own IPv4 base to avoid overflow past .255
        link_ipv4_base = ipv4_bases[_link_idx]
        for _i in range(sessions_per_link):
            # IPv4 offset resets per link, IPv6 continues incrementing
            link_local_idx = _i * 2
            v6_addr_idx = session_idx * 2
            v6_local = (
                f"{ipv6_base}::{ipv6_start_offset + v6_addr_idx + local_offset:x}"
            )
            v6_peer = f"{ipv6_base}::{ipv6_start_offset + v6_addr_idx + peer_offset:x}"
            v4_local_last = ipv4_start_offset + link_local_idx + local_offset
            v4_peer_last = ipv4_start_offset + link_local_idx + peer_offset

            # IPv6 peer
            peers.append(
                {
                    "remote_as_4_byte": remote_as,
                    "local_addr": v6_local,
                    "peer_addr": v6_peer,
                    "next_hop4": "0.0.0.0",
                    "next_hop6": v6_local,
                    "description": f"EBGP_V6_PEER_{session_idx + 1}",
                    "peer_id": v6_peer,
                    "peer_group_name": peer_group_v6,
                    "egress_policy_name": egress_policy_name,
                }
            )

            # IPv4 peer
            peers.append(
                {
                    "remote_as_4_byte": remote_as,
                    "local_addr": f"{link_ipv4_base}.{v4_local_last}",
                    "peer_addr": f"{link_ipv4_base}.{v4_peer_last}",
                    "next_hop4": f"{link_ipv4_base}.{v4_local_last}",
                    "next_hop6": "::",
                    "description": f"EBGP_V4_PEER_{session_idx + 1}",
                    "peer_id": f"{link_ipv4_base}.{v4_peer_last}",
                    "peer_group_name": peer_group_v4,
                    "egress_policy_name": egress_policy_name,
                }
            )

            session_idx += 1

    return peers


def _generate_ixia_peer_entries_for_bgpcpp(
    remote_as: int,
    ixia_ipv6_base: str,
    ixia_ipv4_base: str,
    peer_count: int,
    peer_group_v6: str,
    peer_group_v4: str,
    egress_policy_name: str = "",
) -> t.List[t.Dict[str, t.Any]]:
    """
    Generate BGP++ peer entries for IXIA-facing sessions.

    These are added to /mnt/flash/bgpcpp_config so BGP++ knows about
    the IXIA peers.

    Uses proper IPv4 arithmetic via ipaddress module to handle overflow
    past .255 when peer_count > ~122 (e.g., 140 IXIA peers in Case 2).

    Args:
        remote_as: IXIA's simulated AS number
        ixia_ipv6_base: IPv6 base for IXIA peering
        ixia_ipv4_base: IPv4 base for IXIA peering
        peer_count: Number of IXIA peers
        peer_group_v6: Peer group for IPv6 IXIA sessions
        peer_group_v4: Peer group for IPv4 IXIA sessions
        egress_policy_name: BGP++ egress policy name
    """
    peers = []
    v4_base = IPv4Address(f"{ixia_ipv4_base}.0")
    for i in range(peer_count):
        addr_idx = i * 2
        v6_local = f"{ixia_ipv6_base}::{10 + addr_idx:x}"
        v6_peer = f"{ixia_ipv6_base}::{11 + addr_idx:x}"
        v4_local = str(v4_base + 10 + addr_idx)
        v4_peer = str(v4_base + 11 + addr_idx)

        peers.append(
            {
                "remote_as_4_byte": remote_as,
                "local_addr": v6_local,
                "peer_addr": v6_peer,
                "next_hop4": "0.0.0.0",
                "next_hop6": v6_local,
                "description": f"IXIA_V6_PEER_{i + 1}",
                "peer_id": v6_peer,
                "peer_group_name": peer_group_v6,
                "egress_policy_name": egress_policy_name,
            }
        )

        peers.append(
            {
                "remote_as_4_byte": remote_as,
                "local_addr": v4_local,
                "peer_addr": v4_peer,
                "next_hop4": v4_local,
                "next_hop6": "::",
                "description": f"IXIA_V4_PEER_{i + 1}",
                "peer_id": v4_peer,
                "peer_group_name": peer_group_v4,
                "egress_policy_name": egress_policy_name,
            }
        )

    return peers


# =============================================================================
# Helper: Generate EOS CLI commands for ar-bgp neighbor config on bag013
# =============================================================================
def _generate_arbgp_neighbor_commands(
    local_as: int,  # noqa: F841
    remote_as: int,
    router_id: str,
    interconnect_interfaces: t.List[str],
    sessions_per_link: int,
    ipv6_base: str,
    ipv4_bases: t.List[str],
    ipv6_start_offset: int,
    ipv4_start_offset: int,
    peer_group_v6: str,
    peer_group_v4: str,
) -> t.List[str]:
    """
    Generate EOS CLI commands to configure BGP neighbors on bag013 (ar-bgp).

    Uses standard Arista EOS 'router bgp' / 'neighbor' configuration.
    Creates peer groups first, then adds individual neighbors.
    """
    cmds = []

    # Start BGP config block
    config_lines = [
        "configure",
        f"router bgp {local_as}",
        "maximum-paths 140 ecmp 140",
        "",
        # Create IPv6 peer group
        f"neighbor {peer_group_v6} peer group",
        f"neighbor {peer_group_v6} remote-as {remote_as}",
        "address-family ipv6",
        f"neighbor {peer_group_v6} activate",
        "!",
        "",
        # Create IPv4 peer group
        f"neighbor {peer_group_v4} peer group",
        f"neighbor {peer_group_v4} remote-as {remote_as}",
        "address-family ipv4",
        f"neighbor {peer_group_v4} activate",
        "!",
    ]

    # Add individual neighbors across all links
    session_idx = 0
    for _link_idx, _interface in enumerate(interconnect_interfaces):
        link_ipv4_base = ipv4_bases[_link_idx]
        for _i in range(sessions_per_link):
            link_local_idx = _i * 2
            v6_addr_idx = session_idx * 2
            # ar-bgp side = odd offset (local), bgppp side = even offset (peer)
            # Peer addresses point to bag012 (even offset)
            v6_peer = f"{ipv6_base}::{ipv6_start_offset + v6_addr_idx:x}"
            v4_peer_last = ipv4_start_offset + link_local_idx

            config_lines.append(f"neighbor {v6_peer} peer group {peer_group_v6}")
            config_lines.append(
                f"neighbor {link_ipv4_base}.{v4_peer_last} peer group {peer_group_v4}"
            )

            session_idx += 1

    config_lines.append("end")
    cmds.append("\n".join(config_lines))

    return cmds


# =============================================================================
# Main test config factory
# =============================================================================
def create_case1_test_config(
    bgpcpp_device: str = BAG012_DEVICE_NAME,
    arbgp_device: str = BAG013_DEVICE_NAME,
    bgpcpp_local_as: int = BAG012_LOCAL_AS,
    bgpcpp_as: int = BAG012_BGPCPP_AS,
    arbgp_local_as: int = BAG013_LOCAL_AS,
    bgpcpp_router_id: str = BAG012_ROUTER_ID,
    arbgp_router_id: str = BAG013_ROUTER_ID,
    ixia_as: int = IXIA_AS,
    sessions_per_link: int = EBGP_SESSIONS_PER_LINK,
    ixia_prefix_count: int = IXIA_PREFIX_COUNT,
    bgpcpp_interconnect_interfaces: t.Optional[t.List[str]] = None,
    arbgp_interconnect_interfaces: t.Optional[t.List[str]] = None,
    bgpcpp_ixia_interface: str = BAG012_IXIA_INTERFACE_1,
    bgpcpp_ixia_port: str = BAG012_IXIA_PORT_1,
    ixia_chassis: str = IXIA_CHASSIS,
    ipv6_base: str = INTERCONNECT_IPV6_BASE,
    ipv4_bases: t.Optional[t.List[str]] = None,
    ipv6_start_offset: int = INTERCONNECT_IPV6_START_OFFSET,
    ipv4_start_offset: int = INTERCONNECT_IPV4_START_OFFSET,
    ixia_ipv6_base: str = IXIA_BAG012_IPV6_BASE,
    ixia_ipv4_base: str = IXIA_BAG012_IPV4_BASE,
    bgpcpp_peergroup_ebgp_v6: str = BGPCPP_PEERGROUP_EBGP_V6,
    bgpcpp_peergroup_ebgp_v4: str = BGPCPP_PEERGROUP_EBGP_V4,
    bgpcpp_peergroup_ixia_v6: str = BGPCPP_PEERGROUP_IXIA_V6,
    bgpcpp_peergroup_ixia_v4: str = BGPCPP_PEERGROUP_IXIA_V4,
    bgpcpp_egress_policy_ebgp: str = BGPCPP_EGRESS_POLICY_EBGP,
    bgpcpp_egress_policy_ixia: str = BGPCPP_EGRESS_POLICY_IXIA,
    arbgp_peergroup_ebgp_v6: str = ARBGP_PEERGROUP_EBGP_V6,
    arbgp_peergroup_ebgp_v4: str = ARBGP_PEERGROUP_EBGP_V4,
    communities: str = IXIA_IBGP_COMMUNITIES,
    skip_infra_setup: bool = False,
    skip_teardown: bool = False,
    tcp_convergence_time: int = TCP_DATA_CONVERGENCE_TIME_SECONDS,
    tcp_sample_interval: int = TCP_DATA_SAMPLE_INTERVAL_SECONDS,
) -> TestConfig:
    """
    Create test configuration for Case 1.

    Case 1: 140 eBGP sessions between bag013 (ar-bgp) and bag012 (BGP++),
    plus 1 IXIA peer injecting 15K prefixes into bag012.

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
        ebgp_session_count: Total eBGP sessions between devices (default: 140)
        sessions_per_link: Sessions per physical link (default: 70)
        ixia_prefix_count: Prefixes injected by IXIA (default: 15000)
        bgpcpp_interconnect_interfaces: Interconnect interfaces on bag012
        arbgp_interconnect_interfaces: Interconnect interfaces on bag013
        bgpcpp_ixia_interface: IXIA interface on bag012
        bgpcpp_ixia_port: IXIA chassis port for bag012
        ixia_chassis: IXIA chassis hostname
        ipv6_base: IPv6 base for interconnect addressing
        ipv4_base: IPv4 base for interconnect addressing
        ipv6_start_offset: Starting offset for IPv6 addresses
        ipv4_start_offset: Starting offset for IPv4 addresses
        ixia_ipv6_base: IPv6 base for IXIA peering on bag012
        ixia_ipv4_base: IPv4 base for IXIA peering on bag012
        peergroup_ebgp_v6: Peer group name for eBGP IPv6
        peergroup_ebgp_v4: Peer group name for eBGP IPv4
        peergroup_ixia_v6: Peer group name for IXIA IPv6
        peergroup_ixia_v4: Peer group name for IXIA IPv4
        route_file_v6: Optional IXIA route file for IPv6
        route_file_v4: Optional IXIA route file for IPv4
        communities: BGP community string

    Returns:
        TestConfig for Case 1
    """
    if bgpcpp_interconnect_interfaces is None:
        bgpcpp_interconnect_interfaces = BAG012_INTERCONNECT_INTERFACES
    if arbgp_interconnect_interfaces is None:
        arbgp_interconnect_interfaces = BAG013_INTERCONNECT_INTERFACES
    if ipv4_bases is None:
        ipv4_bases = INTERCONNECT_IPV4_BASES

    # =========================================================================
    # 1. Generate BGP++ peer entries (for /mnt/flash/bgpcpp_config)
    # =========================================================================
    # Inter-device eBGP peers (140 sessions across 2 links)
    bgpcpp_ebgp_peers = _generate_peer_entries_for_interconnect(
        local_as=bgpcpp_local_as,
        remote_as=arbgp_local_as,
        interconnect_interfaces=bgpcpp_interconnect_interfaces,
        sessions_per_link=sessions_per_link,
        ipv6_base=ipv6_base,
        ipv4_bases=ipv4_bases,
        ipv6_start_offset=ipv6_start_offset,
        ipv4_start_offset=ipv4_start_offset,
        peer_group_v6=bgpcpp_peergroup_ebgp_v6,
        peer_group_v4=bgpcpp_peergroup_ebgp_v4,
        egress_policy_name=bgpcpp_egress_policy_ebgp,
        is_bgpcpp_side=True,
    )

    # IXIA-facing peers on bag012 (1 session for route injection)
    bgpcpp_ixia_peers = _generate_ixia_peer_entries_for_bgpcpp(
        remote_as=ixia_as,
        ixia_ipv6_base=ixia_ipv6_base,
        ixia_ipv4_base=ixia_ipv4_base,
        peer_count=1,
        peer_group_v6=bgpcpp_peergroup_ixia_v6,
        peer_group_v4=bgpcpp_peergroup_ixia_v4,
        egress_policy_name=bgpcpp_egress_policy_ixia,
    )

    all_bgpcpp_peers = bgpcpp_ebgp_peers + bgpcpp_ixia_peers

    # =========================================================================
    # 2. Generate ar-bgp EOS CLI commands for bag013
    # =========================================================================
    arbgp_neighbor_cmds = _generate_arbgp_neighbor_commands(
        local_as=arbgp_local_as,
        remote_as=bgpcpp_as,
        router_id=arbgp_router_id,
        interconnect_interfaces=arbgp_interconnect_interfaces,
        sessions_per_link=sessions_per_link,
        ipv6_base=ipv6_base,
        ipv4_bases=ipv4_bases,
        ipv6_start_offset=ipv6_start_offset,
        ipv4_start_offset=ipv4_start_offset,
        peer_group_v6=arbgp_peergroup_ebgp_v6,
        peer_group_v4=arbgp_peergroup_ebgp_v4,
    )

    # =========================================================================
    # 3. Build setup tasks
    # =========================================================================
    setup_tasks = []

    # --- PRE-IXIA: Configure IXIA interface so it's UP before IXIA connects ---
    # After device reload, interface config (speed, switchport) is lost.
    # This MUST run before IXIA setup (ixia_needed=False).
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

    if not skip_infra_setup:
        # --- Pre-cleanup: Remove any stale config from a previous run ---
        setup_tasks.extend(
            create_full_cleanup_tasks(
                bgpcpp_device=bgpcpp_device,
                arbgp_device=arbgp_device,
                bgpcpp_local_as=bgpcpp_local_as,
                arbgp_local_as=arbgp_local_as,
                bgpcpp_interconnect_interfaces=bgpcpp_interconnect_interfaces,
                arbgp_interconnect_interfaces=arbgp_interconnect_interfaces,
                bgpcpp_ixia_interfaces=[bgpcpp_ixia_interface],
            )
        )

    # --- bag012 (BGP++) setup ---

    if not skip_infra_setup:
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

        # 3b. Shutdown native EOS BGP on bag012 (required before starting BGP++)
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
            )
        )

        # 3d. Modify bgpcpp_config: replace peers and router_id only
        # Keeps local_as_4_byte (64981), peer_groups, policies, etc. from base
        # Uses base64 to avoid EOS shell command length limits
        setup_tasks.extend(
            _generate_bgpcpp_peers_modification_tasks(
                bgpcpp_device=bgpcpp_device,
                router_id=bgpcpp_router_id,
                peers=all_bgpcpp_peers,
            )
        )

        # 3e. FibAgent.json is already deployed with the EOS image
        # (arista_create_file_from_config silently fails on this device)
        # Verify: ssh bag012.ash6 "bash ls -la /usr/facebook/thrift_acls/FibAgent.json"

        # 3f. Deploy fib_agent_bgp.conf via embedded base64
        # (arista_create_file_from_config silently fails on this device)
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
                    ixia_needed=True,
                )
            )

        # 3f. Configure interconnect interfaces on bag012 (no switchport, mtu)
        intf_config_lines = ["configure"]
        for intf in bgpcpp_interconnect_interfaces:
            intf_config_lines.extend(
                [
                    f"interface {intf}",
                    "description TCP_EXP_INTERCONNECT",
                    "mtu 9000",
                    "no switchport",
                    "ipv6 enable",
                    "!",
                ]
            )
        intf_config_lines.extend(
            [
                f"interface {bgpcpp_ixia_interface}",
                "description TCP_EXP_IXIA",
                "mtu 9000",
                "no switchport",
                "ipv6 enable",
                "!",
                "end",
            ]
        )
        setup_tasks.append(
            create_run_commands_on_shell_task(
                hostname=bgpcpp_device,
                cmds=["\n".join(intf_config_lines)],
                ixia_needed=True,
            )
        )

        # 3g. Configure secondary IPs on bag012 interconnect interfaces
        for link_idx, intf in enumerate(bgpcpp_interconnect_interfaces):
            setup_tasks.append(
                create_interface_ip_configuration_task(
                    interface=intf,
                    peer_count=sessions_per_link,
                    ipv4_base_network=ipv4_bases[link_idx],
                    ipv6_base_network=ipv6_base,
                    address_families=["ipv4", "ipv6"],
                    ipv4_start_offset=ipv4_start_offset,
                    ipv6_start_offset=ipv6_start_offset
                    + (link_idx * sessions_per_link * 2),
                    hostname=bgpcpp_device,
                    ixia_needed=True,
                )
            )

        # 3h. Configure secondary IPs on bag012 IXIA interface (1 peer)
        setup_tasks.append(
            create_interface_ip_configuration_task(
                interface=bgpcpp_ixia_interface,
                peer_count=1,
                ipv4_base_network=ixia_ipv4_base,
                ipv6_base_network=ixia_ipv6_base,
                address_families=["ipv4", "ipv6"],
                ipv4_start_offset=10,
                ipv6_start_offset=10,
                hostname=bgpcpp_device,
                ixia_needed=True,
            )
        )

        # --- bag013 (ar-bgp) setup ---

        # 3i. Configure interconnect interfaces on bag013 (no switchport, mtu)
        arbgp_intf_config_lines = ["configure"]
        for intf in arbgp_interconnect_interfaces:
            arbgp_intf_config_lines.extend(
                [
                    f"interface {intf}",
                    "description TCP_EXP_INTERCONNECT",
                    "mtu 9000",
                    "no switchport",
                    "!",
                ]
            )
        arbgp_intf_config_lines.append("end")
        setup_tasks.append(
            create_run_commands_on_shell_task(
                hostname=arbgp_device,
                cmds=["\n".join(arbgp_intf_config_lines)],
                ixia_needed=True,
            )
        )

        # 3j. Configure secondary IPs on bag013 interconnect interfaces
        # bag013 (ar-bgp) gets odd offsets (+1) for /31 and /127 subnets
        # bag012 (BGP++) gets even offsets (no +1)
        for link_idx, intf in enumerate(arbgp_interconnect_interfaces):
            setup_tasks.append(
                create_interface_ip_configuration_task(
                    interface=intf,
                    peer_count=sessions_per_link,
                    ipv4_base_network=ipv4_bases[link_idx],
                    ipv6_base_network=ipv6_base,
                    address_families=["ipv4", "ipv6"],
                    ipv4_start_offset=ipv4_start_offset + 1,
                    ipv6_start_offset=ipv6_start_offset
                    + 1
                    + (link_idx * sessions_per_link * 2),
                    hostname=arbgp_device,
                    ixia_needed=True,
                )
            )

        # 3k. Configure BGP neighbors on bag013 via EOS CLI
        setup_tasks.append(
            create_run_commands_on_shell_task(
                hostname=arbgp_device,
                cmds=arbgp_neighbor_cmds,
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
            bgpcpp_interconnect_interfaces=bgpcpp_interconnect_interfaces,
            arbgp_interconnect_interfaces=arbgp_interconnect_interfaces,
            bgpcpp_ixia_interfaces=[bgpcpp_ixia_interface],
            include_interface_cleanup=True,
        )

    # =========================================================================
    # 5. Build and return TestConfig
    # =========================================================================
    return TestConfig(
        name="TCP_SOCKET_EXP_CASE1_140_EBGP_1_IXIA",
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
                ixia_ports=[],
                direct_ixia_connections=[],
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
        basic_port_configs=create_case1_basic_port_configs(
            device_name=bgpcpp_device,
            ixia_interface=bgpcpp_ixia_interface,
            ixia_peer_count=1,
            ixia_as=ixia_as,
            ixia_ipv6_base=ixia_ipv6_base,
            ixia_ipv4_base=ixia_ipv4_base,
            prefix_count=ixia_prefix_count,
            communities=communities,
        ),
        playbooks=[
            create_case1_tcp_socket_data_collection_playbook(
                bgpcpp_device=bgpcpp_device,
                tcp_data_collection_script=TCP_DATA_COLLECTION_SCRIPT,
                tcp_convergence_time=tcp_convergence_time,
                tcp_sample_interval=tcp_sample_interval,
            ),
        ],
    )


# Export a default instance for convenience
CASE1_TEST_CONFIG = create_case1_test_config(skip_teardown=True)
