# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""MTIA EIBGP qualification TestConfig builder.

This module assembles the TestConfig used to qualify MTIA RDSW switches
under EIBGP scale on the SNC1 cluster ``u000.c054``. The DUT is
``rdsw002.u000.c054.snc1`` and the topology consists of:

  * 3 RDSWs (rdsw001/002/003) interconnected via the FDSW fabric.
  * 2 DTSWs (dtsw009, dtsw010) connected to the RDSWs.
  * IXIA chassis driving GPU emulation (8 EIBGP peers + NDP stressor +
    BGP prefix flap + BGP session flap groups) on the DUT, plus 2 EIBGP
    peers per IXIA-facing port on each DTSW.

Setup tasks register COOP patchers (BGP peer-group, policy statement,
switch prefix limit) on every device, then layer hundreds of parallel
iBGP sessions on the RDSW loopbacks via
``create_configure_parallel_bgp_peers_task`` so that the DUT runs at
realistic production fan-out.

Consumed by ``testconfigs/mtia/__init__.py`` and re-exported into
``testconfigs/internal/all.py``. The longevity playbook itself lives in
``playbooks.playbook_definitions.create_mtia_eibgp_longevity_playbook``.

Portmap Design document: https://fburl.com/gsheet/gm4oojut
"""

import json
import typing as t

from ixia.ixia import types as ixia_types
from taac.playbooks.playbook_definitions import (
    create_mtia_eibgp_longevity_playbook,
)
from taac.task_definitions import (
    create_configure_parallel_bgp_peers_task,
    create_coop_apply_patchers_task,
    create_coop_register_patcher_task,
    create_coop_unregister_patchers_task,
    create_wait_for_agent_convergence_task,
    create_wait_for_bgp_convergence_task,
)
from taac.test_as_a_config.types import (
    BasicPortConfig,
    BasicTrafficItemConfig,
    BgpConfig,
    DeviceGroupConfig,
    Endpoint,
    IpAddressesConfig,
    RouteScale,
    RouteScaleSpec,
    Task,
    TestConfig,
    TrafficEndpoint,
)

# IXIA Portss]
RDSW002_IXIA_PORTS = ["eth1/1/1", "eth1/1/5"]
DTSW_IXIA_PORTS = ["eth1/5/1", "eth1/21/1", "eth1/9/1", "eth1/25/1"]

MTIA_RDSW002_ENDPOINTS = [
    Endpoint(name="rdsw002.u000.c054.snc1", dut=True, ixia_ports=RDSW002_IXIA_PORTS),
]

MTIA_DTSW_ENDPOINTS = [
    Endpoint(name="dtsw009.snc1", dut=False, ixia_ports=DTSW_IXIA_PORTS),
    Endpoint(name="dtsw010.snc1", dut=False, ixia_ports=DTSW_IXIA_PORTS),
]

MTIA_ENDPOINTS = MTIA_RDSW002_ENDPOINTS + MTIA_DTSW_ENDPOINTS

# BGP Communities
RDSW_BGP_COMMUNITIES = []
DTSW_BGP_COMMUNITIES: list[str] = []


def create_peer_group_patcher(
    hostname: str,
    peergroup_name: str,
    description: str,
    ingress_policy_name: str,
    egress_policy_name: str,
    peer_tag: str,
) -> Task:
    """Build a COOP ``add_peer_group_patcher`` Task for ``bgpcpp``.

    Wraps ``create_coop_register_patcher_task`` with the canonical set of
    BGP peer-group patcher arguments used by the MTIA EIBGP qualification
    (IPv6-only, next-hop-self, hold=90s, keep-alive=30s, max-routes 90k
    with warning-only enforcement).

    Args:
        hostname: Device on which the patcher is registered.
        peergroup_name: Name of the BGP peer group to create
            (e.g. ``RDSW_TO_GPU``).
        description: Free-form description stored on the peer group.
        ingress_policy_name: Name of the ingress route-map applied to
            the peer group.
        egress_policy_name: Name of the egress route-map applied to
            the peer group.
        peer_tag: Logical peer-tag (e.g. ``"SUSW"``) used downstream by
            BGP next-hop selection.

    Returns:
        A ``Task`` ready to be appended to ``setup_tasks``.
    """
    return create_coop_register_patcher_task(
        hostname=hostname,
        config_name="bgpcpp",
        patcher_name="add_peer_group_patcher_" + peergroup_name,
        task_name="coop_register_patcher",
        patcher_args={
            "name": peergroup_name,
            "description": description,
            "next_hop_self": "True",
            "disable_ipv4_afi": "False",
            "disable_ipv6_afi": "True",
            "is_confed_peer": "False",
            "ingress_policy_name": ingress_policy_name,
            "egress_policy_name": egress_policy_name,
            "bgp_peer_timers_hold_time_seconds": "90",
            "bgp_peer_timers_keep_alive_seconds": "30",
            "bgp_peer_timers_out_delay_seconds": "7",
            "bgp_peer_timers_withdraw_unprog_delay_seconds": "0",
            "peer_tag": peer_tag,
            "max_routes": "90000",
            "warning_only": "True",
            "warning_limit": "0",
            "link_bandwidth_bps": "auto",
            "v4_over_v6_nexthop": "False",
            "is_passive": "False",
            "receive_link_bandwidth": "1",
        },
        py_func_name="add_peer_group_patcher",
    )


def create_policy_statement_patcher(
    hostname: str,
    policy_name: str,
    description: str,
) -> Task:
    """Build a COOP ``add_bgp_policy_statement`` Task for ``bgpcpp``.

    Registers a named (empty) BGP policy statement so that downstream
    peer groups can reference it as their ingress/egress policy.

    Args:
        hostname: Device on which the patcher is registered.
            (Note: the underlying call hard-codes
            ``rdsw001.u000.c054.snc1`` regardless of this argument; left
            as-is for backward compatibility.)
        policy_name: Name of the BGP policy statement (e.g.
            ``PROPAGATE_EVERYTHING``).
        description: Free-form description stored on the policy.

    Returns:
        A ``Task`` ready to be appended to ``setup_tasks``.
    """
    return create_coop_register_patcher_task(
        hostname="rdsw001.u000.c054.snc1",
        config_name="bgpcpp",
        patcher_name="a_add_bgp_policy_statement_" + policy_name,
        task_name="coop_register_patcher",
        patcher_args={
            "name": policy_name,
            "description": description,
        },
        py_func_name="add_bgp_policy_statement",
    )


def create_bgp_switch_limit_patcher(
    hostname: str,
    prefix_limit: int,
) -> Task:
    """Build a COOP ``configure_bgp_switch_limit`` Task for ``bgpcpp``.

    Sets the device-wide BGP prefix limit so that route imports beyond
    ``prefix_limit`` are rejected. Used to harden each MTIA test device
    at 74,000 prefixes during the qualification.

    Args:
        hostname: Device on which the patcher is registered.
        prefix_limit: Total number of BGP prefixes the switch will
            accept across all peers before enforcement triggers.

    Returns:
        A ``Task`` ready to be appended to ``setup_tasks``.
    """
    return create_coop_register_patcher_task(
        hostname=hostname,
        config_name="bgpcpp",
        patcher_name="configure_bgp_switch_limit",
        task_name="coop_register_patcher",
        patcher_args={
            "prefix_limit": str(prefix_limit),
        },
        py_func_name="configure_bgp_switch_limit",
    )


def create_setup_tasks() -> list[Task]:
    """Build the ordered list of MTIA EIBGP setup Tasks.

    Composes everything the test needs before traffic starts:

    * Peer-group + policy patchers on the DUT (``rdsw002``).
    * Switch-wide prefix-limit patchers on all 5 devices.
    * 127 extra iBGP loopback sessions on each RDSW pair to inflate
      session count to production-scale.
    * Per-port IXIA-side BGP peer creation on the DUT and both DTSWs
      (8 EIBGP peers per DUT IXIA port plus NDP / prefix-flap /
      session-flap peer groups).
    * Final ``coop_apply_patchers`` (with warmboot) and
      ``wait_for_agent_convergence`` / ``wait_for_bgp_convergence``
      across the full device set.

    Returns:
        Ordered ``list[Task]`` ready to plug into
        ``TestConfig.setup_tasks``.
    """
    setup_tasks = []
    # Tasks related to GPU emulation on RDSW002
    setup_tasks.append(
        create_peer_group_patcher(
            hostname="rdsw002.u000.c054.snc1",
            description="RDSW to GPU peer group",
            peergroup_name="RDSW_TO_GPU",
            ingress_policy_name="PROPAGATE_EVERYTHING",
            egress_policy_name="PROPAGATE_EVERYTHING",
            peer_tag="SUSW",
        ),
    )
    setup_tasks.append(
        create_policy_statement_patcher(
            hostname="rdsw002.u000.c054.snc1",
            policy_name="PROPAGATE_EVERYTHING",
            description="Propagate everything",
        ),
    )
    # Tasks for Switch Limit
    setup_tasks.append(
        create_bgp_switch_limit_patcher(
            hostname="rdsw001.u000.c054.snc1",
            prefix_limit=74000,
        ),
    )
    setup_tasks.append(
        create_bgp_switch_limit_patcher(
            hostname="rdsw002.u000.c054.snc1",
            prefix_limit=74000,
        ),
    )
    setup_tasks.append(
        create_bgp_switch_limit_patcher(
            hostname="rdsw003.u000.c054.snc1",
            prefix_limit=74000,
        ),
    )
    setup_tasks.append(
        create_bgp_switch_limit_patcher(
            hostname="dtsw009.snc1",
            prefix_limit=74000,
        ),
    )
    setup_tasks.append(
        create_bgp_switch_limit_patcher(
            hostname="dtsw010.snc1",
            prefix_limit=74000,
        ),
    )
    # Tasks to create iBGP sessions between RDSWs
    # Adding more 127 iBGP session on RDSW001 and RDSW003
    setup_tasks.append(
        create_configure_parallel_bgp_peers_task(
            hostname="rdsw002.u000.c054.snc1",
            configure_vlans_patcher_name="configure_vlans_patcher_loopback",
            add_bgp_peers_patcher_name="add_bgp_peers_patcher_loopback",
            config_json=json.dumps(
                {
                    "loop0": [
                        # 127 Extra iBGP sessions with RDSW001 loopback
                        {
                            "starting_ip": "2401:db00:e011:850:0:0:d:5402",
                            "increment_ip": "0:0:0:0::0",
                            "prefix_length": 128,
                            "description": "iBGP Peer with RDSW1",
                            "peer_group_name": "PEERGROUP_RDSW_RDSW_LOOP_V6",
                            "num_sessions": 127,
                            "remote_as_4_bytes": 1,
                            "remote_as_4_bytes_step": 0,
                            "gateway_starting_ip": "1000:1:1::0",
                            "gateway_increment_ip": "0:0:0:0::1",
                        },
                        # 127 Extra iBGP sessions with RDSW003 loopback
                        {
                            "starting_ip": "2401:db00:e011:850:0:0:d:5402",
                            "increment_ip": "0:0:0:0::0",
                            "prefix_length": 128,
                            "description": "iBGP Peer with RDSW3",
                            "peer_group_name": "PEERGROUP_RDSW_RDSW_LOOP_V6",
                            "num_sessions": 127,
                            "remote_as_4_bytes": 1,
                            "remote_as_4_bytes_step": 0,
                            "gateway_starting_ip": "1000:2:1::0",
                            "gateway_increment_ip": "0:0:0:0::1",
                        },
                    ],
                }
            ),
        )
    )
    # Adding more 127 iBGP session on RDSW001
    setup_tasks.append(
        create_configure_parallel_bgp_peers_task(
            hostname="rdsw001.u000.c054.snc1",
            configure_vlans_patcher_name="configure_vlans_patcher_loopback",
            add_bgp_peers_patcher_name="add_bgp_peers_patcher_loopback",
            config_json=json.dumps(
                {
                    "loop0": [
                        # 127 Extra iBGP sessions with RDSW001 loopback
                        {
                            "starting_ip": "1000:1:1::0",
                            "increment_ip": "0:0:0:0::1",
                            "prefix_length": 128,
                            "description": "iBGP Peer with RDSW1",
                            "peer_group_name": "PEERGROUP_RDSW_RDSW_LOOP_V6",
                            "num_sessions": 127,
                            "remote_as_4_bytes": 1,
                            "remote_as_4_bytes_step": 0,
                            "gateway_starting_ip": "2401:db00:e011:850:0:0:d:5402",
                            "gateway_increment_ip": "0:0:0:0::0",
                        },
                    ],
                }
            ),
        )
    )
    # Adding more 127 iBGP session on RDSW003
    setup_tasks.append(
        create_configure_parallel_bgp_peers_task(
            hostname="rdsw003.u000.c054.snc1",
            configure_vlans_patcher_name="configure_vlans_patcher_loopback",
            add_bgp_peers_patcher_name="add_bgp_peers_patcher_loopback",
            config_json=json.dumps(
                {
                    "loop0": [
                        # 127 Extra iBGP sessions with RDSW003 loopback
                        {
                            "starting_ip": "1000:2:1::0",
                            "increment_ip": "0:0:0:0::1",
                            "prefix_length": 128,
                            "description": "iBGP Peer with RDSW1",
                            "peer_group_name": "PEERGROUP_RDSW_RDSW_LOOP_V6",
                            "num_sessions": 127,
                            "remote_as_4_bytes": 1,
                            "remote_as_4_bytes_step": 0,
                            "gateway_starting_ip": "2401:db00:e011:850:0:0:d:5402",
                            "gateway_increment_ip": "0:0:0:0::0",
                        },
                    ],
                }
            ),
        )
    )
    # BGP sessions for traffic from IXIA
    setup_tasks.append(
        create_configure_parallel_bgp_peers_task(
            hostname="rdsw002.u000.c054.snc1",
            configure_vlans_patcher_name="configure_vlans_patcher_ixia",
            add_bgp_peers_patcher_name="add_bgp_peers_patcher_ixia",
            config_json=json.dumps(
                {
                    "eth1/1/1": [
                        # Traffic Items
                        {
                            "starting_ip": "2000:1:1::0",
                            "increment_ip": "0:0:0:0::2",
                            "prefix_length": 127,
                            "description": "BGP Peers to IXIA",
                            "peer_group_name": "RDSW_TO_GPU",
                            "num_sessions": 8,
                            "remote_as_4_bytes": 2,
                            "remote_as_4_bytes_step": 0,
                            "gateway_starting_ip": "2000:1:1::1",
                            "gateway_increment_ip": "0:0:0:0::2",
                        },
                        # NDP Stressor: JUST IP, NO BGP
                        {
                            "starting_ip": "2000:2:1::0",
                            "increment_ip": "0:0:0:0::0",
                            "prefix_length": 80,
                            "description": "NDP stressor",
                            "peer_group_name": "RDSW_TO_GPU",
                            "num_sessions": 1,
                            "remote_as_4_byte": 2,
                            "remote_as_4_byte_step": 1,
                            "gateway_starting_ip": "2000:2:1::1",
                            "gateway_increment_ip": "0:0:0:0::0",
                            "config_only_interface_ip": True,
                        },
                        # BGP Prefix Flap
                        {
                            "starting_ip": "2000:3:1::0",
                            "increment_ip": "0:0:0:0::2",
                            "prefix_length": 127,
                            "description": "BGP Prefix Flap",
                            "peer_group_name": "RDSW_TO_GPU",
                            "num_sessions": 10,
                            "remote_as_4_byte": 2,
                            "remote_as_4_byte_step": 1,
                            "gateway_starting_ip": "2000:3:1::0",
                            "gateway_increment_ip": "0:0:0:0::2",
                        },
                        # BGP Session Flap
                        {
                            "starting_ip": "2000:4:1::0",
                            "increment_ip": "0:0:0:0::2",
                            "prefix_length": 60,
                            "description": "BGP Prefix Flap",
                            "peer_group_name": "RDSW_TO_GPU",
                            "num_sessions": 10,
                            "remote_as_4_byte": 2,
                            "remote_as_4_byte_step": 1,
                            "gateway_starting_ip": "2000:4:1::0",
                            "gateway_increment_ip": "0:0:0:0::2",
                        },
                    ],
                    "eth1/1/5": [
                        # Traffic Items
                        {
                            "starting_ip": "2000:5:1::0",
                            "increment_ip": "0:0:0:0::1",
                            "prefix_length": 127,
                            "description": "BGP Peers to IXIA",
                            "peer_group_name": "RDSW_TO_GPU",
                            "num_sessions": 8,
                            "remote_as_4_bytes": 2,
                            "remote_as_4_bytes_step": 0,
                            "gateway_starting_ip": "2000:5:1::1",
                            "gateway_increment_ip": "0:0:0:0::1",
                        },
                    ],
                }
            ),
        )
    )
    setup_tasks.append(
        create_configure_parallel_bgp_peers_task(
            hostname="dtsw009.snc1",
            configure_vlans_patcher_name="configure_vlans_patcher_ixia",
            add_bgp_peers_patcher_name="add_bgp_peers_patcher_ixia",
            config_json=json.dumps(
                {
                    "eth1/5/1": [
                        # Traffic Items
                        {
                            "starting_ip": "3000:1:1::0",
                            "increment_ip": "0:0:0:0::2",
                            "prefix_length": 127,
                            "description": "BGP Peers to IXIA",
                            "peer_group_name": "PEERGROUP_DTSW_RDSW_V6",
                            "num_sessions": 2,
                            "remote_as_4_bytes": 3,
                            "remote_as_4_bytes_step": 0,
                            "gateway_starting_ip": "3000:1:1::1",
                            "gateway_increment_ip": "0:0:0:0::2",
                        },
                    ],
                    "eth1/21/5": [
                        # Traffic Items
                        {
                            "starting_ip": "3000:2:1::0",
                            "increment_ip": "0:0:0:0::2",
                            "prefix_length": 127,
                            "description": "BGP Peers to IXIA",
                            "peer_group_name": "PEERGROUP_DTSW_RDSW_V6",
                            "num_sessions": 2,
                            "remote_as_4_bytes": 3,
                            "remote_as_4_bytes_step": 0,
                            "gateway_starting_ip": "3000:2:1::1",
                            "gateway_increment_ip": "0:0:0:0::2",
                        },
                    ],
                    "eth1/9/1": [
                        # Traffic Items
                        {
                            "starting_ip": "3000:3:1::0",
                            "increment_ip": "0:0:0:0::2",
                            "prefix_length": 127,
                            "description": "BGP Peers to IXIA",
                            "peer_group_name": "PEERGROUP_DTSW_RDSW_V6",
                            "num_sessions": 2,
                            "remote_as_4_bytes": 3,
                            "remote_as_4_bytes_step": 0,
                            "gateway_starting_ip": "3000:3:1::1",
                            "gateway_increment_ip": "0:0:0:0::2",
                        },
                    ],
                    "eth1/25/5": [
                        # Traffic Items
                        {
                            "starting_ip": "3000:4:1::0",
                            "increment_ip": "0:0:0:0::2",
                            "prefix_length": 127,
                            "description": "BGP Peers to IXIA",
                            "peer_group_name": "PEERGROUP_DTSW_RDSW_V6",
                            "num_sessions": 2,
                            "remote_as_4_bytes": 3,
                            "remote_as_4_bytes_step": 0,
                            "gateway_starting_ip": "3000:4:1::1",
                            "gateway_increment_ip": "0:0:0:0::2",
                        },
                    ],
                }
            ),
        )
    )
    setup_tasks.append(
        create_configure_parallel_bgp_peers_task(
            hostname="dtsw010.snc1",
            configure_vlans_patcher_name="configure_vlans_patcher_ixia",
            add_bgp_peers_patcher_name="add_bgp_peers_patcher_ixia",
            config_json=json.dumps(
                {
                    "eth1/5/1": [
                        # Traffic Items
                        {
                            "starting_ip": "4000:1:1::0",
                            "increment_ip": "0:0:0:0::2",
                            "prefix_length": 127,
                            "description": "BGP Peers to IXIA",
                            "peer_group_name": "PEERGROUP_DTSW_RDSW_V6",
                            "num_sessions": 2,
                            "remote_as_4_bytes": 4,
                            "remote_as_4_bytes_step": 0,
                            "gateway_starting_ip": "4000:1:1::1",
                            "gateway_increment_ip": "0:0:0:0::2",
                        },
                    ],
                    "eth1/21/5": [
                        # Traffic Items
                        {
                            "starting_ip": "4000:2:1::0",
                            "increment_ip": "0:0:0:0::2",
                            "prefix_length": 127,
                            "description": "BGP Peers to IXIA",
                            "peer_group_name": "PEERGROUP_DTSW_RDSW_V6",
                            "num_sessions": 2,
                            "remote_as_4_bytes": 4,
                            "remote_as_4_bytes_step": 0,
                            "gateway_starting_ip": "4000:2:1::1",
                            "gateway_increment_ip": "0:0:0:0::2",
                        },
                    ],
                    "eth1/9/1": [
                        # Traffic Items
                        {
                            "starting_ip": "4000:3:1::0",
                            "increment_ip": "0:0:0:0::2",
                            "prefix_length": 127,
                            "description": "BGP Peers to IXIA",
                            "peer_group_name": "PEERGROUP_DTSW_RDSW_V6",
                            "num_sessions": 2,
                            "remote_as_4_bytes": 4,
                            "remote_as_4_bytes_step": 0,
                            "gateway_starting_ip": "4000:3:1::1",
                            "gateway_increment_ip": "0:0:0:0::2",
                        },
                    ],
                    "eth1/25/5": [
                        # Traffic Items
                        {
                            "starting_ip": "4000:4:1::0",
                            "increment_ip": "0:0:0:0::2",
                            "prefix_length": 127,
                            "description": "BGP Peers to IXIA",
                            "peer_group_name": "PEERGROUP_DTSW_RDSW_V6",
                            "num_sessions": 2,
                            "remote_as_4_bytes": 4,
                            "remote_as_4_bytes_step": 0,
                            "gateway_starting_ip": "4000:4:1::1",
                            "gateway_increment_ip": "0:0:0:0::2",
                        },
                    ],
                }
            ),
        )
    )
    # Tasks to apply patcher and wait for convergence
    setup_tasks.append(
        create_coop_apply_patchers_task(
            hostnames=[
                "rdsw001.u000.c054.snc1",
                "rdsw001.u000.c054.snc2",
                "rdsw003.u000.c054.snc1",
                "dtsw009.snc1",
                "dtsw010.snc1",
                "dtsw010.snc1",
            ],
            do_warmboot=True,
        ),
    )
    setup_tasks.append(
        create_wait_for_agent_convergence_task(
            hostnames=[
                "rdsw001.u000.c054.snc1",
                "rdsw001.u000.c054.snc2",
                "rdsw003.u000.c054.snc1",
                "dtsw009.snc1",
                "dtsw010.snc1",
                "dtsw010.snc1",
            ],
        ),
    )
    setup_tasks.append(
        create_wait_for_bgp_convergence_task(
            hostnames=[
                "rdsw001.u000.c054.snc1",
                "rdsw001.u000.c054.snc2",
                "rdsw003.u000.c054.snc1",
                "dtsw009.snc1",
                "dtsw010.snc1",
                "dtsw010.snc1",
            ],
        )
    )
    return setup_tasks


def create_rdsw_basic_port_config() -> BasicPortConfig:
    """Build the IXIA ``BasicPortConfig`` for the DUT RDSW (rdsw002).

    Generates 5 device groups on the DUT IXIA ports:

    1. ``RDSW_EIBGP_IXIA_1`` — 8 EIBGP peers feeding RDSW->DTSW9
       traffic with 50 IPv6 prefixes each (multiplier=8).
    2. ``RDSW_EIBGP_IXIA_2`` — 8 EIBGP peers feeding RDSW->DTSW10
       traffic with 50 IPv6 prefixes each (multiplier=8).
    3. ``NDP_STRESSOR`` — 10,000 IPv6-only endpoints (no BGP) used to
       stress NDP table scale.
    4. ``BGP_PREFIX_FLAP`` — 10 BGP peers that flap 10,000 prefixes
       (30s up / 30s down) to exercise prefix churn.
    5. ``BGP_SESSION_FLAP`` — 10 BGP peers that themselves flap
       (30s up / 30s down) carrying 10,000 prefixes each.

    Returns:
        A single ``BasicPortConfig`` for ``rdsw002.u000.c054.snc1``.
    """
    rdsw_basic_port_config = BasicPortConfig(
        endpoint="rdsw002.u000.c054.snc1",
        device_group_configs=[
            # Used for Traffic with DTSW009
            DeviceGroupConfig(
                device_group_index=0,
                tag_name="RDSW_EIBGP_IXIA_1",
                multiplier=8,
                v6_addresses_config=IpAddressesConfig(
                    starting_ip="2000:1:1::1",
                    increment_ip="0:0:0:0::2",
                    gateway_starting_ip="2000:1:1::0",
                    gateway_increment_ip="0:0:0:0::2",
                    mask=127,
                ),
                v6_bgp_config=BgpConfig(
                    local_as_4_bytes=2,
                    local_as_increment=0,
                    enable_4_byte_local_as=True,
                    bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                    enable_graceful_restart=True,
                    graceful_restart_timer=120,
                    advertise_end_of_rib=True,
                    route_scales=[
                        RouteScaleSpec(
                            network_group_index=0,
                            v6_route_scale=RouteScale(
                                multiplier=1,
                                prefix_count=50,
                                starting_prefixes="5000:1000::",
                                prefix_step="0:0:0:0::0",
                                prefix_length=48,
                                ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                bgp_communities=RDSW_BGP_COMMUNITIES,
                            ),
                        ),
                    ],
                ),
            ),
            # Used for Traffic with DTSW010
            DeviceGroupConfig(
                device_group_index=1,
                tag_name="RDSW_EIBGP_IXIA_2",
                multiplier=8,
                v6_addresses_config=IpAddressesConfig(
                    starting_ip="2000:5:1::1",
                    increment_ip="0:0:0:0::2",
                    gateway_starting_ip="2000:5:1::0",
                    gateway_increment_ip="0:0:0:0::2",
                    mask=127,
                ),
                v6_bgp_config=BgpConfig(
                    local_as_4_bytes=2,
                    local_as_increment=0,
                    enable_4_byte_local_as=True,
                    bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                    enable_graceful_restart=True,
                    graceful_restart_timer=120,
                    advertise_end_of_rib=True,
                    route_scales=[
                        RouteScaleSpec(
                            network_group_index=0,
                            v6_route_scale=RouteScale(
                                multiplier=1,
                                prefix_count=50,
                                starting_prefixes="5000:2000::",
                                prefix_step="0:0:0:0::0",
                                prefix_length=48,
                                ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                bgp_communities=RDSW_BGP_COMMUNITIES,
                            ),
                        ),
                    ],
                ),
            ),
            # NDP Stressor
            DeviceGroupConfig(
                device_group_index=2,
                tag_name="NDP_STRESSOR",
                multiplier=10000,
                v6_addresses_config=IpAddressesConfig(
                    starting_ip="2000:2:1::1",
                    increment_ip="0:0:0:0::2",
                    gateway_starting_ip="2000:2:1::0",
                    gateway_increment_ip="0:0:0:0::2",
                    mask=80,
                ),
            ),
            # BGP Prefix Flapping
            DeviceGroupConfig(
                device_group_index=3,
                tag_name="BGP_PREFIX_FLAP",
                multiplier=10,
                v6_addresses_config=IpAddressesConfig(
                    starting_ip="2000:3:1::1",
                    increment_ip="0:0:0:0::2",
                    gateway_starting_ip="2000:3:1::0",
                    gateway_increment_ip="0:0:0:0::2",
                    mask=127,
                ),
                v6_bgp_config=BgpConfig(
                    local_as_4_bytes=2,
                    local_as_increment=0,
                    enable_4_byte_local_as=True,
                    bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                    enable_graceful_restart=True,
                    graceful_restart_timer=120,
                    advertise_end_of_rib=True,
                    route_scales=[
                        RouteScaleSpec(
                            network_group_index=0,
                            v6_route_scale=RouteScale(
                                multiplier=1,
                                prefix_count=10000,
                                starting_prefixes="6000:1000::",
                                prefix_step="0:0:0:0::0",
                                prefix_length=48,
                                ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                bgp_communities=RDSW_BGP_COMMUNITIES,
                                prefix_flap_config=ixia_types.BgpFlapConfig(
                                    uptime_in_sec=30,
                                    downtime_in_sec=30,
                                ),
                            ),
                        ),
                    ],
                ),
            ),
            # BGP Session Flap
            DeviceGroupConfig(
                device_group_index=4,
                tag_name="BGP_SESSION_FLAP",
                multiplier=10,
                v6_addresses_config=IpAddressesConfig(
                    starting_ip="2000:4:1::1",
                    increment_ip="0:0:0:0::2",
                    gateway_starting_ip="2000:4:1::0",
                    gateway_increment_ip="0:0:0:0::2",
                    mask=127,
                ),
                v6_bgp_config=BgpConfig(
                    local_as_4_bytes=2,
                    local_as_increment=0,
                    enable_4_byte_local_as=True,
                    bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                    peer_flap_config=ixia_types.BgpFlapConfig(
                        uptime_in_sec=30,
                        downtime_in_sec=30,
                    ),
                    route_scales=[
                        RouteScaleSpec(
                            network_group_index=0,
                            v6_route_scale=RouteScale(
                                multiplier=1,
                                prefix_count=10000,
                                starting_prefixes="6000:2000::",
                                prefix_step="0:0:0:0::0",
                                prefix_length=86,
                                ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                bgp_communities=RDSW_BGP_COMMUNITIES,
                            ),
                        ),
                    ],
                ),
            ),
        ],
    )

    return rdsw_basic_port_config


def create_dtsw9_basic_port_config() -> BasicPortConfig:
    """Build the IXIA ``BasicPortConfig`` for ``dtsw009.snc1``.

    Generates 4 device groups (one per IXIA port) each with 2 EIBGP
    peers advertising 20 IPv6 prefixes anchored at ``7000:N000::``,
    matching the 4-port DTSW->IXIA fan-out used in the qualification.

    Returns:
        A single ``BasicPortConfig`` for ``dtsw009.snc1``.
    """
    return BasicPortConfig(
        endpoint="dtsw009.snc1",
        device_group_configs=[
            DeviceGroupConfig(
                device_group_index=0,
                tag_name="DTSW9_EIBGP_IXIA_1",
                multiplier=2,
                v6_addresses_config=IpAddressesConfig(
                    starting_ip="3000:1:1::1",
                    increment_ip="0:0:0:0::2",
                    gateway_starting_ip="3000:1:1::0",
                    gateway_increment_ip="0:0:0:0::2",
                    mask=127,
                ),
                v6_bgp_config=BgpConfig(
                    local_as_4_bytes=0,
                    local_as_increment=0,
                    enable_4_byte_local_as=True,
                    bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                    enable_graceful_restart=True,
                    graceful_restart_timer=120,
                    advertise_end_of_rib=True,
                    route_scales=[
                        RouteScaleSpec(
                            network_group_index=0,
                            v6_route_scale=RouteScale(
                                multiplier=1,
                                prefix_count=20,
                                starting_prefixes="7000:1000::",
                                prefix_step="0:0:0:0::0",
                                prefix_length=48,
                                ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                bgp_communities=DTSW_BGP_COMMUNITIES,
                            ),
                        ),
                    ],
                ),
            ),
            DeviceGroupConfig(
                device_group_index=1,
                tag_name="DTSW9_EIBGP_IXIA_2",
                multiplier=2,
                v6_addresses_config=IpAddressesConfig(
                    starting_ip="3000:2:1::1",
                    increment_ip="0:0:0:0::2",
                    gateway_starting_ip="3000:2:1::0",
                    gateway_increment_ip="0:0:0:0::2",
                    mask=127,
                ),
                v6_bgp_config=BgpConfig(
                    local_as_4_bytes=0,
                    local_as_increment=0,
                    enable_4_byte_local_as=True,
                    bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                    enable_graceful_restart=True,
                    graceful_restart_timer=120,
                    advertise_end_of_rib=True,
                    route_scales=[
                        RouteScaleSpec(
                            network_group_index=0,
                            v6_route_scale=RouteScale(
                                multiplier=1,
                                prefix_count=20,
                                starting_prefixes="7000:2000::",
                                prefix_step="0:0:0:0::0",
                                prefix_length=48,
                                ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                bgp_communities=DTSW_BGP_COMMUNITIES,
                            ),
                        ),
                    ],
                ),
            ),
            DeviceGroupConfig(
                device_group_index=2,
                tag_name="DTSW9_EIBGP_IXIA_3",
                multiplier=2,
                v6_addresses_config=IpAddressesConfig(
                    starting_ip="3000:3:1::1",
                    increment_ip="0:0:0:0::2",
                    gateway_starting_ip="3000:3:1::0",
                    gateway_increment_ip="0:0:0:0::2",
                    mask=127,
                ),
                v6_bgp_config=BgpConfig(
                    local_as_4_bytes=0,
                    local_as_increment=0,
                    enable_4_byte_local_as=True,
                    bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                    enable_graceful_restart=True,
                    graceful_restart_timer=120,
                    advertise_end_of_rib=True,
                    route_scales=[
                        RouteScaleSpec(
                            network_group_index=0,
                            v6_route_scale=RouteScale(
                                multiplier=1,
                                prefix_count=20,
                                starting_prefixes="7000:3000::",
                                prefix_step="0:0:0:0::0",
                                prefix_length=48,
                                ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                bgp_communities=DTSW_BGP_COMMUNITIES,
                            ),
                        ),
                    ],
                ),
            ),
            DeviceGroupConfig(
                device_group_index=3,
                tag_name="DTSW9_EIBGP_IXIA_4",
                multiplier=2,
                v6_addresses_config=IpAddressesConfig(
                    starting_ip="3000:4:1::1",
                    increment_ip="0:0:0:0::2",
                    gateway_starting_ip="3000:4:1::0",
                    gateway_increment_ip="0:0:0:0::2",
                    mask=127,
                ),
                v6_bgp_config=BgpConfig(
                    local_as_4_bytes=0,
                    local_as_increment=0,
                    enable_4_byte_local_as=True,
                    bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                    enable_graceful_restart=True,
                    graceful_restart_timer=120,
                    advertise_end_of_rib=True,
                    route_scales=[
                        RouteScaleSpec(
                            network_group_index=0,
                            v6_route_scale=RouteScale(
                                multiplier=1,
                                prefix_count=20,
                                starting_prefixes="7000:4000::",
                                prefix_step="0:0:0:0::0",
                                prefix_length=48,
                                ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                bgp_communities=DTSW_BGP_COMMUNITIES,
                            ),
                        ),
                    ],
                ),
            ),
        ],
    )


def create_dtsw10_basic_port_config() -> BasicPortConfig:
    """Build the IXIA ``BasicPortConfig`` for ``dtsw010.snc1``.

    Mirror of :func:`create_dtsw9_basic_port_config` for the second
    DTSW: 4 device groups (one per IXIA port), each with 2 EIBGP peers
    advertising 20 IPv6 prefixes anchored at ``8000:N000::``.

    Returns:
        A single ``BasicPortConfig`` for ``dtsw010.snc1``.
    """
    return BasicPortConfig(
        endpoint="dtsw010.snc1",
        device_group_configs=[
            DeviceGroupConfig(
                device_group_index=0,
                tag_name="DTSW10_EIBGP_IXIA_1",
                multiplier=2,
                v6_addresses_config=IpAddressesConfig(
                    starting_ip="4000:1:1::1",
                    increment_ip="0:0:0:0::2",
                    gateway_starting_ip="4000:1:1::0",
                    gateway_increment_ip="0:0:0:0::2",
                    mask=127,
                ),
                v6_bgp_config=BgpConfig(
                    local_as_4_bytes=0,
                    local_as_increment=0,
                    enable_4_byte_local_as=True,
                    bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                    enable_graceful_restart=True,
                    graceful_restart_timer=120,
                    advertise_end_of_rib=True,
                    route_scales=[
                        RouteScaleSpec(
                            network_group_index=0,
                            v6_route_scale=RouteScale(
                                multiplier=1,
                                prefix_count=20,
                                starting_prefixes="8000:1000::",
                                prefix_step="0:0:0:0::0",
                                prefix_length=48,
                                ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                bgp_communities=DTSW_BGP_COMMUNITIES,
                            ),
                        ),
                    ],
                ),
            ),
            DeviceGroupConfig(
                device_group_index=1,
                tag_name="DTSW10_EIBGP_IXIA_2",
                multiplier=2,
                v6_addresses_config=IpAddressesConfig(
                    starting_ip="4000:2:1::1",
                    increment_ip="0:0:0:0::2",
                    gateway_starting_ip="4000:2:1::0",
                    gateway_increment_ip="0:0:0:0::2",
                    mask=127,
                ),
                v6_bgp_config=BgpConfig(
                    local_as_4_bytes=0,
                    local_as_increment=0,
                    enable_4_byte_local_as=True,
                    bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                    enable_graceful_restart=True,
                    graceful_restart_timer=120,
                    advertise_end_of_rib=True,
                    route_scales=[
                        RouteScaleSpec(
                            network_group_index=0,
                            v6_route_scale=RouteScale(
                                multiplier=1,
                                prefix_count=20,
                                starting_prefixes="8000:2000::",
                                prefix_step="0:0:0:0::0",
                                prefix_length=48,
                                ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                bgp_communities=DTSW_BGP_COMMUNITIES,
                            ),
                        ),
                    ],
                ),
            ),
            DeviceGroupConfig(
                device_group_index=2,
                tag_name="DTSW10_EIBGP_IXIA_3",
                multiplier=2,
                v6_addresses_config=IpAddressesConfig(
                    starting_ip="4000:3:1::1",
                    increment_ip="0:0:0:0::2",
                    gateway_starting_ip="4000:3:1::0",
                    gateway_increment_ip="0:0:0:0::2",
                    mask=127,
                ),
                v6_bgp_config=BgpConfig(
                    local_as_4_bytes=0,
                    local_as_increment=0,
                    enable_4_byte_local_as=True,
                    bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                    enable_graceful_restart=True,
                    graceful_restart_timer=120,
                    advertise_end_of_rib=True,
                    route_scales=[
                        RouteScaleSpec(
                            network_group_index=0,
                            v6_route_scale=RouteScale(
                                multiplier=1,
                                prefix_count=20,
                                starting_prefixes="8000:3000::",
                                prefix_step="0:0:0:0::0",
                                prefix_length=48,
                                ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                bgp_communities=DTSW_BGP_COMMUNITIES,
                            ),
                        ),
                    ],
                ),
            ),
            DeviceGroupConfig(
                device_group_index=3,
                tag_name="DTSW10_EIBGP_IXIA_4",
                multiplier=2,
                v6_addresses_config=IpAddressesConfig(
                    starting_ip="4000:4:1::1",
                    increment_ip="0:0:0:0::2",
                    gateway_starting_ip="4000:4:1::0",
                    gateway_increment_ip="0:0:0:0::2",
                    mask=127,
                ),
                v6_bgp_config=BgpConfig(
                    local_as_4_bytes=0,
                    local_as_increment=0,
                    enable_4_byte_local_as=True,
                    bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                    enable_graceful_restart=True,
                    graceful_restart_timer=120,
                    advertise_end_of_rib=True,
                    route_scales=[
                        RouteScaleSpec(
                            network_group_index=0,
                            v6_route_scale=RouteScale(
                                multiplier=1,
                                prefix_count=20,
                                starting_prefixes="8000:4000::",
                                prefix_step="0:0:0:0::0",
                                prefix_length=48,
                                ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                bgp_communities=DTSW_BGP_COMMUNITIES,
                            ),
                        ),
                    ],
                ),
            ),
        ],
    )


def create_basic_port_configs() -> t.List[BasicPortConfig]:
    """Aggregate IXIA port configs for DUT + both DTSWs.

    Returns:
        ``[rdsw002, dtsw009, dtsw010]`` ``BasicPortConfig`` list ready
        to plug into ``TestConfig.basic_port_configs``.
    """
    return [
        create_rdsw_basic_port_config(),
        create_dtsw9_basic_port_config(),
        create_dtsw10_basic_port_config(),
    ]


def create_rdsw_dtsw_traffic_item(dtsw_idx: str) -> BasicTrafficItemConfig:
    """Build one IXIA ``BasicTrafficItemConfig`` from the DUT to a DTSW.

    Source = the DUT's first IXIA port (``eth1/1/1``, device group 0).
    Destinations = all 4 IXIA ports on the named DTSW
    (``DTSW_IXIA_PORTS``), full-mesh, IPv6 traffic at 99% line rate.

    Args:
        dtsw_idx: DTSW number as a string (``"9"`` or ``"10"``).
            Drives both the traffic item name and DTSW hostname.

    Returns:
        A unidirectional, full-mesh IPv6 traffic item named
        ``RDSW_DTSW{dtsw_idx}_TRAFFIC``.
    """
    return BasicTrafficItemConfig(
        name=f"RDSW_DTSW{dtsw_idx}_TRAFFIC",
        src_endpoints=[
            TrafficEndpoint(
                name="rdsw002.u000.c054.snc1:eth1/1/1",
                device_group_index=0,
                network_group_index=0,
            ),
        ],
        dest_endpoints=[
            TrafficEndpoint(
                name=f"dtsw{int(dtsw_idx):03d}.snc1:{DTSW_IXIA_PORTS[i]}",
                device_group_index=i,
                network_group_index=0,
            )
            for i in range(len(DTSW_IXIA_PORTS))
        ],
        line_rate=99,
        traffic_type=ixia_types.TrafficType.IPV6,
        merge_destinations=False,
        bidirectional=False,
        src_dest_mesh=ixia_types.SrcDestMeshType.FULL_MESH,
    )


def create_basic_traffic_item_configs() -> t.List[BasicTrafficItemConfig]:
    """Aggregate IXIA traffic items: DUT -> DTSW9 and DUT -> DTSW10.

    Returns:
        Two unidirectional IPv6 traffic items, one per DTSW.
    """
    return [create_rdsw_dtsw_traffic_item("9"), create_rdsw_dtsw_traffic_item("10")]


def create_mtia_eibgp_test_config(
    test_config_name: str = "MTIA_EIBGP_TEST_CONFIG",
    basset_pool: str = "networkai.test",
    longevity_duration: int = 3600,
) -> TestConfig:
    """Build the MTIA EIBGP qualification ``TestConfig``.

    Wires together every helper in this module: endpoints (DUT + 2
    DTSWs), IXIA per-port configs, IXIA traffic items, the full setup
    Task chain (peer-group / policy / switch-limit COOP patchers, 127
    extra iBGP loopback sessions per RDSW pair, parallel BGP peers on
    every IXIA-facing port, and warmboot + convergence waits), the
    teardown ``coop_unregister_patchers_task``, and the EIBGP longevity
    playbook.

    Args:
        test_config_name: Name registered in ``TestConfig.name`` and
            referenced by ``--test-config`` on the netcastle CLI.
        basset_pool: Basset pool used to reserve the lab devices.
        longevity_duration: Duration in seconds passed to
            ``create_mtia_eibgp_longevity_playbook``; controls how long
            the playbook holds steady-state traffic before postchecks.

    Returns:
        A fully populated ``TestConfig`` ready to register in
        ``INTERNAL_TEST_CONFIGS``.
    """
    return TestConfig(
        name=test_config_name,
        basset_pool=basset_pool,
        ixia_protocol_verification_timeout=300,
        endpoints=MTIA_ENDPOINTS,
        setup_tasks=create_setup_tasks(),
        teardown_tasks=[
            create_coop_unregister_patchers_task(
                hostnames=[
                    "rdsw001.u000.c054.snc1",
                    "rdsw001.u000.c054.snc2",
                    "rdsw003.u000.c054.snc1",
                    "dtsw009.snc1",
                    "dtsw010.snc1",
                    "dtsw010.snc1",
                ],
            ),
        ],
        basic_port_configs=create_basic_port_configs(),
        basic_traffic_item_configs=create_basic_traffic_item_configs(),
        traffic_items_to_start=["RDSW_DTSW9_TRAFFIC", "RDSW_DTSW10_TRAFFIC"],
        # Deprecated - define at playbook level
        # snapshot_checks=[
        #     SnapshotHealthCheck(name=hc_types.CheckName.CORE_DUMPS_CHECK),
        # ],
        # Deprecated - define at playbook level
        # postchecks=[
        #     PointInTimeHealthCheck(
        #         name=hc_types.CheckName.SYSTEMCTL_ACTIVE_STATE_CHECK,
        #     ),
        #     PointInTimeHealthCheck(
        #         name=hc_types.CheckName.DEVICE_CORE_DUMPS_CHECK,
        #         check_params=Params(
        #             jq_params={
        #                 "start_time": ".test_case_start_time",
        #             }
        #         ),
        #     ),
        #     PointInTimeHealthCheck(
        #         name=hc_types.CheckName.UNCLEAN_EXIT_CHECK,
        #         check_params=Params(
        #             jq_params={
        #                 "start_time": ".test_case_start_time",
        #             }
        #         ),
        #     ),
        #     PointInTimeHealthCheck(
        #         name=hc_types.CheckName.SERVICE_RESTART_CHECK,
        #         check_params=Params(
        #             jq_params={
        #                 "start_time": ".test_case_start_time",
        #             },
        #         ),
        #     ),
        # ],
        # Deprecated - define at playbook level
        # prechecks=[
        #     PointInTimeHealthCheck(
        #         name=hc_types.CheckName.SYSTEMCTL_ACTIVE_STATE_CHECK,
        #     ),
        #     PointInTimeHealthCheck(
        #         name=hc_types.CheckName.PREFIX_LIMIT_CHECK,
        #         check_params=Params(
        #             json_params=json.dumps(
        #                 {
        #                     "prefix_limit": 74000,
        #                 }
        #             )
        #         ),
        #     ),
        #     PointInTimeHealthCheck(
        #         name=hc_types.CheckName.UNCLEAN_EXIT_CHECK,
        #         check_params=Params(
        #             jq_params={
        #                 "start_time": ".test_case_start_time",
        #             }
        #         ),
        #     ),
        # ],
        playbooks=[
            create_mtia_eibgp_longevity_playbook(
                longevity_duration=longevity_duration,
            ),
        ],
    )
