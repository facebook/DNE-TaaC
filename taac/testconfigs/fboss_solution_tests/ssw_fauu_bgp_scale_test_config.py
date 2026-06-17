# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""SSW_FAUU_BGP_SCALE TestConfig.

Multi-node BGP scale test on QZD1 SSW + 8 FAUU + 2 FADU devices. Sets up
PROPAGATE_FAUU_EB_IN/OUT BGP policy statements via COOP patchers, runs
warmboot/coldboot/FSDB-restart/QSPF-restart/BGPD-restart playbooks against
heavy multi-node BGP traffic.
"""

from ixia.ixia import types as ixia_types
from taac.end_points_definitions import (
    QZD_FAUU_HIGHER_LAYER_TESTING_ENPOINTS,
    QZD_SSW_HIGHER_LAYER_TESTING_ENPOINTS,
)
from taac.health_checks.healthcheck_definitions import (
    create_bare_health_check,
)
from taac.playbooks.playbook_definitions import (
    build_ssw_fauu_bgp_scale_playbook,
    TEST_AGENT_WARMBOOT_AND_FSDB_RESTART_PLAYBOOK,
    TEST_AGENT_WARMBOOT_PLAYBOOK,
    TEST_BGPD_RESTART_PLAYBOOK,
    TEST_FSDB_RESTART_PLAYBOOK,
    TEST_QSPF_RESTART_PLAYBOOK,
)
from taac.task_definitions import (
    create_coop_apply_patchers_task,
    create_coop_register_patcher_task,
    create_coop_unregister_patchers_task,
)
from taac.health_check.health_check import types as hc_types
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import TestConfig


SSW_FAUU_BGP_SCALE_TEST_CONFIG = TestConfig(
    name="SSW_FAUU_BGP_SCALE",
    basset_pool="dne.test",
    endpoints=[
        taac_types.Endpoint(
            name="ssw002.s002.f01.qzd1",
            dut=True,
            ixia_ports=["eth8/16/1"],
        ),
        taac_types.Endpoint(
            name="fa002-uu001.qzd1",
            dut=True,
            ixia_ports=["eth6/13/1"],
        ),
        taac_types.Endpoint(
            name="fa002-uu002.qzd1",
            dut=True,
            ixia_ports=["eth6/13/1"],
        ),
        taac_types.Endpoint(
            name="fa002-uu003.qzd1",
            dut=True,
            ixia_ports=["eth6/13/1"],
        ),
        taac_types.Endpoint(
            name="fa002-uu004.qzd1",
            dut=True,
            ixia_ports=["eth6/13/1"],
        ),
        taac_types.Endpoint(
            name="fa001-uu001.qzd1",
            dut=True,
            ixia_ports=["eth6/13/1"],
        ),
        taac_types.Endpoint(
            name="fa001-uu002.qzd1",
            dut=True,
            ixia_ports=["eth6/15/1"],
        ),
        taac_types.Endpoint(
            name="fa001-uu003.qzd1",
            dut=True,
            ixia_ports=["eth6/13/1"],
        ),
        taac_types.Endpoint(
            name="fa001-uu004.qzd1",
            dut=True,
            ixia_ports=["eth6/13/1"],
        ),
        taac_types.Endpoint(
            name="fa001-du002.qzd1",
            dut=True,
        ),
        taac_types.Endpoint(
            name="fa002-du002.qzd1",
            dut=True,
        ),
    ],
    setup_tasks=[
        create_coop_unregister_patchers_task(
            [
                "ssw002.s002.f01.qzd1",
                "fa002-uu001.qzd1",
                "fa002-uu002.qzd1",
                "fa002-uu003.qzd1",
                "fa002-uu004.qzd1",
                "fa001-uu001.qzd1",
                "fa001-uu002.qzd1",
                "fa001-uu003.qzd1",
                "fa001-uu004.qzd1",
                "fa001-du002.qzd1",
                "fa002-du002.qzd1",
            ]
        ),
        create_coop_register_patcher_task(
            hostname="fa001-uu004.qzd1",
            config_name="bgpcpp",
            patcher_name="a_add_bgp_policy_statement_PROPAGATE_FAUU_EB_IN",
            task_name="add_bgp_policy_statement",
            patcher_args={
                "name": "PROPAGATE_FAUU_EB_IN",
                "description": "Policy for EB IN",
            },
            py_func_name="add_bgp_policy_statement",
        ),
        create_coop_register_patcher_task(
            hostname="fa001-uu003.qzd1",
            config_name="bgpcpp",
            patcher_name="a_add_bgp_policy_statement_PROPAGATE_FAUU_EB_IN",
            task_name="add_bgp_policy_statement",
            patcher_args={
                "name": "PROPAGATE_FAUU_EB_IN",
                "description": "Policy for EB IN",
            },
            py_func_name="add_bgp_policy_statement",
        ),
        create_coop_register_patcher_task(
            hostname="fa001-uu002.qzd1",
            config_name="bgpcpp",
            patcher_name="a_add_bgp_policy_statement_PROPAGATE_FAUU_EB_IN",
            task_name="add_bgp_policy_statement",
            patcher_args={
                "name": "PROPAGATE_FAUU_EB_IN",
                "description": "Policy for EB IN",
            },
            py_func_name="add_bgp_policy_statement",
        ),
        create_coop_register_patcher_task(
            hostname="fa001-uu001.qzd1",
            config_name="bgpcpp",
            patcher_name="a_add_bgp_policy_statement_PROPAGATE_FAUU_EB_IN",
            task_name="add_bgp_policy_statement",
            patcher_args={
                "name": "PROPAGATE_FAUU_EB_IN",
                "description": "Policy for EB IN",
            },
            py_func_name="add_bgp_policy_statement",
        ),
        create_coop_register_patcher_task(
            hostname="fa002-uu004.qzd1",
            config_name="bgpcpp",
            patcher_name="a_add_bgp_policy_statement_PROPAGATE_FAUU_EB_IN",
            task_name="add_bgp_policy_statement",
            patcher_args={
                "name": "PROPAGATE_FAUU_EB_IN",
                "description": "Policy for EB IN",
            },
            py_func_name="add_bgp_policy_statement",
        ),
        create_coop_register_patcher_task(
            hostname="fa002-uu003.qzd1",
            config_name="bgpcpp",
            patcher_name="a_add_bgp_policy_statement_PROPAGATE_FAUU_EB_IN",
            task_name="add_bgp_policy_statement",
            patcher_args={
                "name": "PROPAGATE_FAUU_EB_IN",
                "description": "Policy for EB IN",
            },
            py_func_name="add_bgp_policy_statement",
        ),
        create_coop_register_patcher_task(
            hostname="fa002-uu002.qzd1",
            config_name="bgpcpp",
            patcher_name="a_add_bgp_policy_statement_PROPAGATE_FAUU_EB_IN",
            task_name="add_bgp_policy_statement",
            patcher_args={
                "name": "PROPAGATE_FAUU_EB_IN",
                "description": "Policy for EB IN",
            },
            py_func_name="add_bgp_policy_statement",
        ),
        create_coop_register_patcher_task(
            hostname="fa002-uu001.qzd1",
            config_name="bgpcpp",
            patcher_name="a_add_bgp_policy_statement_PROPAGATE_FAUU_EB_IN",
            task_name="add_bgp_policy_statement",
            patcher_args={
                "name": "PROPAGATE_FAUU_EB_IN",
                "description": "Policy for EB IN",
            },
            py_func_name="add_bgp_policy_statement",
        ),
        create_coop_register_patcher_task(
            hostname="fa001-uu004.qzd1",
            config_name="bgpcpp",
            patcher_name="a_add_bgp_policy_statement_PROPAGATE_FAUU_EB_OUT",
            task_name="add_bgp_policy_statement",
            patcher_args={
                "name": "PROPAGATE_FAUU_EB_OUT",
                "description": "Policy for EB OUT",
            },
            py_func_name="add_bgp_policy_statement",
        ),
        create_coop_register_patcher_task(
            hostname="fa001-uu003.qzd1",
            config_name="bgpcpp",
            patcher_name="a_add_bgp_policy_statement_PROPAGATE_FAUU_EB_OUT",
            task_name="add_bgp_policy_statement",
            patcher_args={
                "name": "PROPAGATE_FAUU_EB_OUT",
                "description": "Policy for EB OUT",
            },
            py_func_name="add_bgp_policy_statement",
        ),
        create_coop_register_patcher_task(
            hostname="fa001-uu002.qzd1",
            config_name="bgpcpp",
            patcher_name="a_add_bgp_policy_statement_PROPAGATE_FAUU_EB_OUT",
            task_name="add_bgp_policy_statement",
            patcher_args={
                "name": "PROPAGATE_FAUU_EB_OUT",
                "description": "Policy for EB OUT",
            },
            py_func_name="add_bgp_policy_statement",
        ),
        create_coop_register_patcher_task(
            hostname="fa001-uu001.qzd1",
            config_name="bgpcpp",
            patcher_name="a_add_bgp_policy_statement_PROPAGATE_FAUU_EB_OUT",
            task_name="add_bgp_policy_statement",
            patcher_args={
                "name": "PROPAGATE_FAUU_EB_OUT",
                "description": "Policy for EB OUT",
            },
            py_func_name="add_bgp_policy_statement",
        ),
        create_coop_register_patcher_task(
            hostname="fa002-uu004.qzd1",
            config_name="bgpcpp",
            patcher_name="a_add_bgp_policy_statement_PROPAGATE_FAUU_EB_OUT",
            task_name="add_bgp_policy_statement",
            patcher_args={
                "name": "PROPAGATE_FAUU_EB_OUT",
                "description": "Policy for EB OUT",
            },
            py_func_name="add_bgp_policy_statement",
        ),
        create_coop_register_patcher_task(
            hostname="fa002-uu003.qzd1",
            config_name="bgpcpp",
            patcher_name="a_add_bgp_policy_statement_PROPAGATE_FAUU_EB_OUT",
            task_name="add_bgp_policy_statement",
            patcher_args={
                "name": "PROPAGATE_FAUU_EB_OUT",
                "description": "Policy for EB OUT",
            },
            py_func_name="add_bgp_policy_statement",
        ),
        create_coop_register_patcher_task(
            hostname="fa002-uu002.qzd1",
            config_name="bgpcpp",
            patcher_name="a_add_bgp_policy_statement_PROPAGATE_FAUU_EB_OUT",
            task_name="add_bgp_policy_statement",
            patcher_args={
                "name": "PROPAGATE_FAUU_EB_OUT",
                "description": "Policy for EB OUT",
            },
            py_func_name="add_bgp_policy_statement",
        ),
        create_coop_register_patcher_task(
            hostname="fa002-uu001.qzd1",
            config_name="bgpcpp",
            patcher_name="a_add_bgp_policy_statement_PROPAGATE_FAUU_EB_OUT",
            task_name="add_bgp_policy_statement",
            patcher_args={
                "name": "PROPAGATE_FAUU_EB_OUT",
                "description": "Policy for EB OUT",
            },
            py_func_name="add_bgp_policy_statement",
        ),
        # adding policy entries
        create_coop_register_patcher_task(
            hostname="fa002-uu001.qzd1",
            config_name="bgpcpp",
            patcher_name="add_bgp_policy_match_prefix_to_propagate_routes_PROPAGATE_FAUU_EB_IN",
            task_name="add_bgp_policy_match_prefix_to_propagate_routes",
            patcher_args={
                "matching_prefix": "6000::/16",
                "in_stmt_name": "PROPAGATE_FAUU_EB_IN",
                "out_stmt_name": "RANDOM",
            },
            py_func_name="add_bgp_policy_match_prefix_to_propagate_routes",
        ),
        create_coop_register_patcher_task(
            hostname="fa002-uu002.qzd1",
            config_name="bgpcpp",
            patcher_name="add_bgp_policy_match_prefix_to_propagate_routes_PROPAGATE_FAUU_EB_IN",
            task_name="add_bgp_policy_match_prefix_to_propagate_routes",
            patcher_args={
                "matching_prefix": "6000::/16",
                "in_stmt_name": "PROPAGATE_FAUU_EB_IN",
                "out_stmt_name": "RANDOM",
            },
            py_func_name="add_bgp_policy_match_prefix_to_propagate_routes",
        ),
        create_coop_register_patcher_task(
            hostname="fa002-uu003.qzd1",
            config_name="bgpcpp",
            patcher_name="add_bgp_policy_match_prefix_to_propagate_routes_PROPAGATE_FAUU_EB_IN",
            task_name="add_bgp_policy_match_prefix_to_propagate_routes",
            patcher_args={
                "matching_prefix": "6000::/16",
                "in_stmt_name": "PROPAGATE_FAUU_EB_IN",
                "out_stmt_name": "RANDOM",
            },
            py_func_name="add_bgp_policy_match_prefix_to_propagate_routes",
        ),
        create_coop_register_patcher_task(
            hostname="fa002-uu004.qzd1",
            config_name="bgpcpp",
            patcher_name="add_bgp_policy_match_prefix_to_propagate_routes_PROPAGATE_FAUU_EB_IN",
            task_name="add_bgp_policy_match_prefix_to_propagate_routes",
            patcher_args={
                "matching_prefix": "6000::/16",
                "in_stmt_name": "PROPAGATE_FAUU_EB_IN",
                "out_stmt_name": "RANDOM",
            },
            py_func_name="add_bgp_policy_match_prefix_to_propagate_routes",
        ),
        create_coop_register_patcher_task(
            hostname="fa001-uu001.qzd1",
            config_name="bgpcpp",
            patcher_name="add_bgp_policy_match_prefix_to_propagate_routes_PROPAGATE_FAUU_EB_IN",
            task_name="add_bgp_policy_match_prefix_to_propagate_routes",
            patcher_args={
                "matching_prefix": "6000::/16",
                "in_stmt_name": "PROPAGATE_FAUU_EB_IN",
                "out_stmt_name": "RANDOM",
            },
            py_func_name="add_bgp_policy_match_prefix_to_propagate_routes",
        ),
        create_coop_register_patcher_task(
            hostname="fa001-uu002.qzd1",
            config_name="bgpcpp",
            patcher_name="add_bgp_policy_match_prefix_to_propagate_routes_PROPAGATE_FAUU_EB_IN",
            task_name="add_bgp_policy_match_prefix_to_propagate_routes",
            patcher_args={
                "matching_prefix": "6000::/16",
                "in_stmt_name": "PROPAGATE_FAUU_EB_IN",
                "out_stmt_name": "RANDOM",
            },
            py_func_name="add_bgp_policy_match_prefix_to_propagate_routes",
        ),
        create_coop_register_patcher_task(
            hostname="fa001-uu003.qzd1",
            config_name="bgpcpp",
            patcher_name="add_bgp_policy_match_prefix_to_propagate_routes_PROPAGATE_FAUU_EB_IN",
            task_name="add_bgp_policy_match_prefix_to_propagate_routes",
            patcher_args={
                "matching_prefix": "6000::/16",
                "in_stmt_name": "PROPAGATE_FAUU_EB_IN",
                "out_stmt_name": "RANDOM",
            },
            py_func_name="add_bgp_policy_match_prefix_to_propagate_routes",
        ),
        create_coop_register_patcher_task(
            hostname="fa001-uu004.qzd1",
            config_name="bgpcpp",
            patcher_name="add_bgp_policy_match_prefix_to_propagate_routes_PROPAGATE_FAUU_EB_IN",
            task_name="add_bgp_policy_match_prefix_to_propagate_routes",
            patcher_args={
                "matching_prefix": "6000::/16",
                "in_stmt_name": "PROPAGATE_FAUU_EB_IN",
                "out_stmt_name": "RANDOM",
            },
            py_func_name="add_bgp_policy_match_prefix_to_propagate_routes",
        ),
        create_coop_register_patcher_task(
            hostname="fa002-uu001.qzd1",
            config_name="bgpcpp",
            patcher_name="add_bgp_policy_match_prefix_to_propagate_routes_PROPAGATE_FAUU_EB_OUT",
            task_name="add_bgp_policy_match_prefix_to_propagate_routes",
            patcher_args={
                "matching_prefix": "4000::/16",
                "in_stmt_name": "RANDOM",
                "out_stmt_name": "PROPAGATE_FAUU_EB_OUT",
            },
            py_func_name="add_bgp_policy_match_prefix_to_propagate_routes",
        ),
        create_coop_register_patcher_task(
            hostname="fa002-uu002.qzd1",
            config_name="bgpcpp",
            patcher_name="add_bgp_policy_match_prefix_to_propagate_routes_PROPAGATE_FAUU_EB_OUT",
            task_name="add_bgp_policy_match_prefix_to_propagate_routes",
            patcher_args={
                "matching_prefix": "4000::/16",
                "in_stmt_name": "RANDOM",
                "out_stmt_name": "PROPAGATE_FAUU_EB_OUT",
            },
            py_func_name="add_bgp_policy_match_prefix_to_propagate_routes",
        ),
        create_coop_register_patcher_task(
            hostname="fa002-uu003.qzd1",
            config_name="bgpcpp",
            patcher_name="add_bgp_policy_match_prefix_to_propagate_routes_PROPAGATE_FAUU_EB_OUT",
            task_name="add_bgp_policy_match_prefix_to_propagate_routes",
            patcher_args={
                "matching_prefix": "4000::/16",
                "in_stmt_name": "RANDOM",
                "out_stmt_name": "PROPAGATE_FAUU_EB_OUT",
            },
            py_func_name="add_bgp_policy_match_prefix_to_propagate_routes",
        ),
        create_coop_register_patcher_task(
            hostname="fa002-uu004.qzd1",
            config_name="bgpcpp",
            patcher_name="add_bgp_policy_match_prefix_to_propagate_routes_PROPAGATE_FAUU_EB_OUT",
            task_name="add_bgp_policy_match_prefix_to_propagate_routes",
            patcher_args={
                "matching_prefix": "4000::/16",
                "in_stmt_name": "RANDOM",
                "out_stmt_name": "PROPAGATE_FAUU_EB_OUT",
            },
            py_func_name="add_bgp_policy_match_prefix_to_propagate_routes",
        ),
        create_coop_register_patcher_task(
            hostname="fa001-uu001.qzd1",
            config_name="bgpcpp",
            patcher_name="add_bgp_policy_match_prefix_to_propagate_routes_PROPAGATE_FAUU_EB_OUT",
            task_name="add_bgp_policy_match_prefix_to_propagate_routes",
            patcher_args={
                "matching_prefix": "4000::/16",
                "in_stmt_name": "RANDOM",
                "out_stmt_name": "PROPAGATE_FAUU_EB_OUT",
            },
            py_func_name="add_bgp_policy_match_prefix_to_propagate_routes",
        ),
        create_coop_register_patcher_task(
            hostname="fa001-uu002.qzd1",
            config_name="bgpcpp",
            patcher_name="add_bgp_policy_match_prefix_to_propagate_routes_PROPAGATE_FAUU_EB_OUT",
            task_name="add_bgp_policy_match_prefix_to_propagate_routes",
            patcher_args={
                "matching_prefix": "4000::/16",
                "in_stmt_name": "RANDOM",
                "out_stmt_name": "PROPAGATE_FAUU_EB_OUT",
            },
            py_func_name="add_bgp_policy_match_prefix_to_propagate_routes",
        ),
        create_coop_register_patcher_task(
            hostname="fa001-uu003.qzd1",
            config_name="bgpcpp",
            patcher_name="add_bgp_policy_match_prefix_to_propagate_routes_PROPAGATE_FAUU_EB_OUT",
            task_name="add_bgp_policy_match_prefix_to_propagate_routes",
            patcher_args={
                "matching_prefix": "4000::/16",
                "in_stmt_name": "RANDOM",
                "out_stmt_name": "PROPAGATE_FAUU_EB_OUT",
            },
            py_func_name="add_bgp_policy_match_prefix_to_propagate_routes",
        ),
        create_coop_register_patcher_task(
            hostname="fa001-uu004.qzd1",
            config_name="bgpcpp",
            patcher_name="add_bgp_policy_match_prefix_to_propagate_routes_PROPAGATE_FAUU_EB_OUT",
            task_name="add_bgp_policy_match_prefix_to_propagate_routes",
            patcher_args={
                "matching_prefix": "4000::/16",
                "in_stmt_name": "RANDOM",
                "out_stmt_name": "PROPAGATE_FAUU_EB_OUT",
            },
            py_func_name="add_bgp_policy_match_prefix_to_propagate_routes",
        ),
        create_coop_apply_patchers_task(
            hostnames=[
                "fa001-uu001.qzd1",
                "fa001-uu002.qzd1",
                "fa001-uu003.qzd1",
                "fa001-uu004.qzd1",
                "fa002-uu001.qzd1",
                "fa002-uu002.qzd1",
                "fa002-uu003.qzd1",
                "fa002-uu004.qzd1",
            ],
        ),
        # adding peer group
        create_coop_register_patcher_task(
            hostname="fa001-uu004.qzd1",
            config_name="bgpcpp",
            patcher_name="add_peer_group_patcher_PEERGROUP_FAUU_EB_V6",
            task_name="add_peer_group_patcher",
            patcher_args={
                "name": "PEERGROUP_FAUU_EB_V6",
                "description": "BGP peering from FAUU to EB, IPV6 sessions",
                "next_hop_self": "True",
                "disable_ipv4_afi": "False",
                "disable_ipv6_afi": "False",
                "is_confed_peer": "False",
                "ingress_policy_name": "PROPAGATE_FAUU_EB_IN",
                "egress_policy_name": "PROPAGATE_FAUU_EB_OUT",
                "bgp_peer_timers_hold_time_seconds": "30",
                "bgp_peer_timers_keep_alive_seconds": "10",
                "bgp_peer_timers_out_delay_seconds": "7",
                "bgp_peer_timers_withdraw_unprog_delay_seconds": "0",
                "peer_tag": "EB",
                "max_routes": "45000",
                "warning_only": "True",
                "warning_limit": "0",
                "link_bandwidth_bps": "auto",
                "v4_over_v6_nexthop": "true",
                "is_passive": "False",
                "receive_link_bandwidth": "1",
            },
            py_func_name="add_peer_group_patcher",
        ),
        create_coop_register_patcher_task(
            hostname="fa001-uu003.qzd1",
            config_name="bgpcpp",
            patcher_name="add_peer_group_patcher_PEERGROUP_FAUU_EB_V6",
            task_name="add_peer_group_patcher",
            patcher_args={
                "name": "PEERGROUP_FAUU_EB_V6",
                "description": "BGP peering from FAUU to EB, IPV6 sessions",
                "next_hop_self": "True",
                "disable_ipv4_afi": "False",
                "disable_ipv6_afi": "False",
                "is_confed_peer": "False",
                "ingress_policy_name": "PROPAGATE_FAUU_EB_IN",
                "egress_policy_name": "PROPAGATE_FAUU_EB_OUT",
                "bgp_peer_timers_hold_time_seconds": "30",
                "bgp_peer_timers_keep_alive_seconds": "10",
                "bgp_peer_timers_out_delay_seconds": "7",
                "bgp_peer_timers_withdraw_unprog_delay_seconds": "0",
                "peer_tag": "EB",
                "max_routes": "45000",
                "warning_only": "True",
                "warning_limit": "0",
                "link_bandwidth_bps": "auto",
                "v4_over_v6_nexthop": "true",
                "is_passive": "False",
                "receive_link_bandwidth": "1",
            },
            py_func_name="add_peer_group_patcher",
        ),
        create_coop_register_patcher_task(
            hostname="fa001-uu002.qzd1",
            config_name="bgpcpp",
            patcher_name="add_peer_group_patcher_PEERGROUP_FAUU_EB_V6",
            task_name="add_peer_group_patcher",
            patcher_args={
                "name": "PEERGROUP_FAUU_EB_V6",
                "description": "BGP peering from FAUU to EB, IPV6 sessions",
                "next_hop_self": "True",
                "disable_ipv4_afi": "False",
                "disable_ipv6_afi": "False",
                "is_confed_peer": "False",
                "ingress_policy_name": "PROPAGATE_FAUU_EB_IN",
                "egress_policy_name": "PROPAGATE_FAUU_EB_OUT",
                "bgp_peer_timers_hold_time_seconds": "30",
                "bgp_peer_timers_keep_alive_seconds": "10",
                "bgp_peer_timers_out_delay_seconds": "7",
                "bgp_peer_timers_withdraw_unprog_delay_seconds": "0",
                "peer_tag": "EB",
                "max_routes": "45000",
                "warning_only": "True",
                "warning_limit": "0",
                "link_bandwidth_bps": "auto",
                "v4_over_v6_nexthop": "true",
                "is_passive": "False",
                "receive_link_bandwidth": "1",
            },
            py_func_name="add_peer_group_patcher",
        ),
        create_coop_register_patcher_task(
            hostname="fa001-uu001.qzd1",
            config_name="bgpcpp",
            patcher_name="add_peer_group_patcher_PEERGROUP_FAUU_EB_V6",
            task_name="add_peer_group_patcher",
            patcher_args={
                "name": "PEERGROUP_FAUU_EB_V6",
                "description": "BGP peering from FAUU to EB, IPV6 sessions",
                "next_hop_self": "True",
                "disable_ipv4_afi": "False",
                "disable_ipv6_afi": "False",
                "is_confed_peer": "False",
                "ingress_policy_name": "PROPAGATE_FAUU_EB_IN",
                "egress_policy_name": "PROPAGATE_FAUU_EB_OUT",
                "bgp_peer_timers_hold_time_seconds": "30",
                "bgp_peer_timers_keep_alive_seconds": "10",
                "bgp_peer_timers_out_delay_seconds": "7",
                "bgp_peer_timers_withdraw_unprog_delay_seconds": "0",
                "peer_tag": "EB",
                "max_routes": "45000",
                "warning_only": "True",
                "warning_limit": "0",
                "link_bandwidth_bps": "auto",
                "v4_over_v6_nexthop": "true",
                "is_passive": "False",
                "receive_link_bandwidth": "1",
            },
            py_func_name="add_peer_group_patcher",
        ),
        create_coop_register_patcher_task(
            hostname="fa002-uu001.qzd1",
            config_name="bgpcpp",
            patcher_name="add_peer_group_patcher_PEERGROUP_FAUU_EB_V6",
            task_name="add_peer_group_patcher",
            patcher_args={
                "name": "PEERGROUP_FAUU_EB_V6",
                "description": "BGP peering from FAUU to EB, IPV6 sessions",
                "next_hop_self": "True",
                "disable_ipv4_afi": "False",
                "disable_ipv6_afi": "False",
                "is_confed_peer": "False",
                "ingress_policy_name": "PROPAGATE_FAUU_EB_IN",
                "egress_policy_name": "PROPAGATE_FAUU_EB_OUT",
                "bgp_peer_timers_hold_time_seconds": "30",
                "bgp_peer_timers_keep_alive_seconds": "10",
                "bgp_peer_timers_out_delay_seconds": "7",
                "bgp_peer_timers_withdraw_unprog_delay_seconds": "0",
                "peer_tag": "EB",
                "max_routes": "45000",
                "warning_only": "True",
                "warning_limit": "0",
                "link_bandwidth_bps": "auto",
                "v4_over_v6_nexthop": "true",
                "is_passive": "False",
                "receive_link_bandwidth": "1",
            },
            py_func_name="add_peer_group_patcher",
        ),
        create_coop_register_patcher_task(
            hostname="fa002-uu002.qzd1",
            config_name="bgpcpp",
            patcher_name="add_peer_group_patcher_PEERGROUP_FAUU_EB_V6",
            task_name="add_peer_group_patcher",
            patcher_args={
                "name": "PEERGROUP_FAUU_EB_V6",
                "description": "BGP peering from FAUU to EB, IPV6 sessions",
                "next_hop_self": "True",
                "disable_ipv4_afi": "False",
                "disable_ipv6_afi": "False",
                "is_confed_peer": "False",
                "ingress_policy_name": "PROPAGATE_FAUU_EB_IN",
                "egress_policy_name": "PROPAGATE_FAUU_EB_OUT",
                "bgp_peer_timers_hold_time_seconds": "30",
                "bgp_peer_timers_keep_alive_seconds": "10",
                "bgp_peer_timers_out_delay_seconds": "7",
                "bgp_peer_timers_withdraw_unprog_delay_seconds": "0",
                "peer_tag": "EB",
                "max_routes": "45000",
                "warning_only": "True",
                "warning_limit": "0",
                "link_bandwidth_bps": "auto",
                "v4_over_v6_nexthop": "true",
                "is_passive": "False",
                "receive_link_bandwidth": "1",
            },
            py_func_name="add_peer_group_patcher",
        ),
        create_coop_register_patcher_task(
            hostname="fa002-uu003.qzd1",
            config_name="bgpcpp",
            patcher_name="add_peer_group_patcher_PEERGROUP_FAUU_EB_V6",
            task_name="add_peer_group_patcher",
            patcher_args={
                "name": "PEERGROUP_FAUU_EB_V6",
                "description": "BGP peering from FAUU to EB, IPV6 sessions",
                "next_hop_self": "True",
                "disable_ipv4_afi": "False",
                "disable_ipv6_afi": "False",
                "is_confed_peer": "False",
                "ingress_policy_name": "PROPAGATE_FAUU_EB_IN",
                "egress_policy_name": "PROPAGATE_FAUU_EB_OUT",
                "bgp_peer_timers_hold_time_seconds": "30",
                "bgp_peer_timers_keep_alive_seconds": "10",
                "bgp_peer_timers_out_delay_seconds": "7",
                "bgp_peer_timers_withdraw_unprog_delay_seconds": "0",
                "peer_tag": "EB",
                "max_routes": "45000",
                "warning_only": "True",
                "warning_limit": "0",
                "link_bandwidth_bps": "auto",
                "v4_over_v6_nexthop": "true",
                "is_passive": "False",
                "receive_link_bandwidth": "1",
            },
            py_func_name="add_peer_group_patcher",
        ),
        create_coop_register_patcher_task(
            hostname="fa002-uu004.qzd1",
            config_name="bgpcpp",
            patcher_name="add_peer_group_patcher_PEERGROUP_FAUU_EB_V6",
            task_name="add_peer_group_patcher",
            patcher_args={
                "name": "PEERGROUP_FAUU_EB_V6",
                "description": "BGP peering from FAUU to EB, IPV6 sessions",
                "next_hop_self": "True",
                "disable_ipv4_afi": "False",
                "disable_ipv6_afi": "False",
                "is_confed_peer": "False",
                "ingress_policy_name": "PROPAGATE_FAUU_EB_IN",
                "egress_policy_name": "PROPAGATE_FAUU_EB_OUT",
                "bgp_peer_timers_hold_time_seconds": "30",
                "bgp_peer_timers_keep_alive_seconds": "10",
                "bgp_peer_timers_out_delay_seconds": "7",
                "bgp_peer_timers_withdraw_unprog_delay_seconds": "0",
                "peer_tag": "EB",
                "max_routes": "45000",
                "warning_only": "True",
                "warning_limit": "0",
                "link_bandwidth_bps": "auto",
                "v4_over_v6_nexthop": "True",
                "is_passive": "False",
                "receive_link_bandwidth": "1",
            },
            py_func_name="add_peer_group_patcher",
        ),
        create_coop_apply_patchers_task(
            hostnames=[
                "fa001-uu001.qzd1",
                "fa001-uu002.qzd1",
                "fa001-uu003.qzd1",
                "fa001-uu004.qzd1",
                "fa002-uu001.qzd1",
                "fa002-uu002.qzd1",
                "fa002-uu003.qzd1",
                "fa002-uu004.qzd1",
            ],
        ),
    ],
    # Deprecated - define at playbook level
    # postchecks=[...],
    # Deprecated - define at playbook level
    # prechecks=[...],
    basic_port_configs=[
        taac_types.BasicPortConfig(
            endpoint="ssw002.s002.f01.qzd1:eth8/16/1",
            device_group_configs=[
                taac_types.DeviceGroupConfig(
                    device_group_index=0,
                    v6_bgp_config=taac_types.BgpConfig(
                        route_scales=[
                            taac_types.RouteScaleSpec(
                                v6_route_scale=taac_types.RouteScale(
                                    multiplier=25,
                                    prefix_count=20000,
                                    prefix_length=64,
                                    starting_prefixes="4000:2::",
                                    bgp_communities=[
                                        "65529:34814",
                                        "65441:131",
                                    ],
                                    ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                ),
                            )
                        ],
                        graceful_restart_timer=180,
                    ),
                )
            ],
        ),
        taac_types.BasicPortConfig(
            endpoint="fa001-uu001.qzd1:eth6/13/1",
            device_group_configs=[
                taac_types.DeviceGroupConfig(
                    device_group_index=0,
                    v6_bgp_config=taac_types.BgpConfig(
                        route_scales=[
                            taac_types.RouteScaleSpec(
                                v6_route_scale=taac_types.RouteScale(
                                    multiplier=25,
                                    prefix_count=20000,
                                    prefix_length=64,
                                    starting_prefixes="6000:2::",
                                    bgp_communities=[
                                        "65529:666",
                                    ],
                                    ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                ),
                            )
                        ],
                        graceful_restart_timer=180,
                        local_as=64981,
                        enable_4_byte_local_as=True,
                        local_as_4_bytes=64981,
                    ),
                )
            ],
        ),
        taac_types.BasicPortConfig(
            endpoint="fa001-uu002.qzd1:eth6/15/1",
            device_group_configs=[
                taac_types.DeviceGroupConfig(
                    device_group_index=0,
                    v6_bgp_config=taac_types.BgpConfig(
                        route_scales=[
                            taac_types.RouteScaleSpec(
                                v6_route_scale=taac_types.RouteScale(
                                    multiplier=25,
                                    prefix_count=20000,
                                    prefix_length=64,
                                    starting_prefixes="6000:2::",
                                    bgp_communities=[
                                        "65529:666",
                                    ],
                                    ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                ),
                            )
                        ],
                        graceful_restart_timer=180,
                        local_as=64981,
                        enable_4_byte_local_as=True,
                        local_as_4_bytes=64981,
                    ),
                )
            ],
        ),
        taac_types.BasicPortConfig(
            endpoint="fa001-uu003.qzd1:eth6/13/1",
            device_group_configs=[
                taac_types.DeviceGroupConfig(
                    device_group_index=0,
                    v6_bgp_config=taac_types.BgpConfig(
                        route_scales=[
                            taac_types.RouteScaleSpec(
                                v6_route_scale=taac_types.RouteScale(
                                    multiplier=25,
                                    prefix_count=20000,
                                    prefix_length=64,
                                    starting_prefixes="6000:2::",
                                    bgp_communities=[
                                        "65529:666",
                                    ],
                                    ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                ),
                            )
                        ],
                        graceful_restart_timer=180,
                        local_as=64981,
                        enable_4_byte_local_as=True,
                        local_as_4_bytes=64981,
                    ),
                )
            ],
        ),
        taac_types.BasicPortConfig(
            endpoint="fa001-uu004.qzd1:eth6/13/1",
            device_group_configs=[
                taac_types.DeviceGroupConfig(
                    device_group_index=0,
                    v6_bgp_config=taac_types.BgpConfig(
                        route_scales=[
                            taac_types.RouteScaleSpec(
                                v6_route_scale=taac_types.RouteScale(
                                    multiplier=25,
                                    prefix_count=20000,
                                    prefix_length=64,
                                    starting_prefixes="6000:2::",
                                    bgp_communities=[
                                        "65529:666",
                                    ],
                                    ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                ),
                            )
                        ],
                        graceful_restart_timer=180,
                        local_as=64981,
                        enable_4_byte_local_as=True,
                        local_as_4_bytes=64981,
                    ),
                )
            ],
        ),
        taac_types.BasicPortConfig(
            endpoint="fa002-uu001.qzd1:eth6/13/1",
            device_group_configs=[
                taac_types.DeviceGroupConfig(
                    device_group_index=0,
                    v6_bgp_config=taac_types.BgpConfig(
                        route_scales=[
                            taac_types.RouteScaleSpec(
                                v6_route_scale=taac_types.RouteScale(
                                    multiplier=25,
                                    prefix_count=20000,
                                    prefix_length=64,
                                    starting_prefixes="6000:2::",
                                    bgp_communities=[
                                        "65529:666",
                                    ],
                                    ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                ),
                            )
                        ],
                        graceful_restart_timer=180,
                        local_as=64981,
                        enable_4_byte_local_as=True,
                        local_as_4_bytes=64981,
                    ),
                )
            ],
        ),
        taac_types.BasicPortConfig(
            endpoint="fa002-uu002.qzd1:eth6/13/1",
            device_group_configs=[
                taac_types.DeviceGroupConfig(
                    device_group_index=0,
                    v6_bgp_config=taac_types.BgpConfig(
                        route_scales=[
                            taac_types.RouteScaleSpec(
                                v6_route_scale=taac_types.RouteScale(
                                    multiplier=25,
                                    prefix_count=20000,
                                    prefix_length=64,
                                    starting_prefixes="6000:2::",
                                    bgp_communities=[
                                        "65529:666",
                                    ],
                                    ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                ),
                            )
                        ],
                        graceful_restart_timer=180,
                        local_as=64981,
                        enable_4_byte_local_as=True,
                        local_as_4_bytes=64981,
                    ),
                )
            ],
        ),
        taac_types.BasicPortConfig(
            endpoint="fa002-uu003.qzd1:eth6/13/1",
            device_group_configs=[
                taac_types.DeviceGroupConfig(
                    device_group_index=0,
                    v6_bgp_config=taac_types.BgpConfig(
                        route_scales=[
                            taac_types.RouteScaleSpec(
                                v6_route_scale=taac_types.RouteScale(
                                    multiplier=25,
                                    prefix_count=20000,
                                    prefix_length=64,
                                    starting_prefixes="6000:2::",
                                    bgp_communities=[
                                        "65529:666",
                                    ],
                                    ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                ),
                            )
                        ],
                        graceful_restart_timer=180,
                        local_as=64981,
                        enable_4_byte_local_as=True,
                        local_as_4_bytes=64981,
                    ),
                )
            ],
        ),
        taac_types.BasicPortConfig(
            endpoint="fa002-uu004.qzd1:eth6/13/1",
            device_group_configs=[
                taac_types.DeviceGroupConfig(
                    device_group_index=0,
                    v6_bgp_config=taac_types.BgpConfig(
                        route_scales=[
                            taac_types.RouteScaleSpec(
                                v6_route_scale=taac_types.RouteScale(
                                    multiplier=25,
                                    prefix_count=20000,
                                    prefix_length=64,
                                    starting_prefixes="6000:2::",
                                    bgp_communities=[
                                        "65529:666",
                                    ],
                                    ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                ),
                            )
                        ],
                        graceful_restart_timer=180,
                        local_as=64981,
                        enable_4_byte_local_as=True,
                        local_as_4_bytes=64981,
                    ),
                )
            ],
        ),
    ],
    basic_traffic_item_configs=[
        taac_types.BasicTrafficItemConfig(
            bidirectional=False,
            merge_destinations=True,
            line_rate=80,
            src_dest_mesh=ixia_types.SrcDestMeshType.MANY_TO_MANY,
            src_endpoints=QZD_SSW_HIGHER_LAYER_TESTING_ENPOINTS,
            dest_endpoints=QZD_FAUU_HIGHER_LAYER_TESTING_ENPOINTS,
            tracking_types=[ixia_types.TrafficStatsTrackingType.TRAFFIC_ITEM],
        ),
        taac_types.BasicTrafficItemConfig(
            bidirectional=False,
            merge_destinations=True,
            src_dest_mesh=ixia_types.SrcDestMeshType.MANY_TO_MANY,
            src_endpoints=QZD_FAUU_HIGHER_LAYER_TESTING_ENPOINTS,
            dest_endpoints=QZD_SSW_HIGHER_LAYER_TESTING_ENPOINTS,
            tracking_types=[ixia_types.TrafficStatsTrackingType.TRAFFIC_ITEM],
        ),
    ],
    playbooks=[
        build_ssw_fauu_bgp_scale_playbook(
            name=TEST_AGENT_WARMBOOT_PLAYBOOK.name,
            device_regexes=[
                "fa001-du002.qzd1",
                "fa002-du002.qzd1",
            ],
            stages=TEST_AGENT_WARMBOOT_PLAYBOOK.stages,
            prechecks=[
                create_bare_health_check(hc_types.CheckName.IXIA_PACKET_LOSS_CHECK),
            ],
            postchecks=[
                create_bare_health_check(hc_types.CheckName.IXIA_PACKET_LOSS_CHECK),
            ],
        ),
        build_ssw_fauu_bgp_scale_playbook(
            name=TEST_QSPF_RESTART_PLAYBOOK.name,
            device_regexes=[
                "fa001-du002.qzd1",
                "fa002-du002.qzd1",
            ],
            stages=TEST_QSPF_RESTART_PLAYBOOK.stages,
            prechecks=[
                create_bare_health_check(hc_types.CheckName.IXIA_PACKET_LOSS_CHECK),
            ],
            postchecks=[
                create_bare_health_check(hc_types.CheckName.IXIA_PACKET_LOSS_CHECK),
            ],
        ),
        build_ssw_fauu_bgp_scale_playbook(
            name=TEST_BGPD_RESTART_PLAYBOOK.name,
            device_regexes=[
                "fa001-du002.qzd1",
                "fa002-du002.qzd1",
            ],
            stages=TEST_BGPD_RESTART_PLAYBOOK.stages,
            prechecks=[
                create_bare_health_check(hc_types.CheckName.IXIA_PACKET_LOSS_CHECK),
            ],
            postchecks=[
                create_bare_health_check(hc_types.CheckName.IXIA_PACKET_LOSS_CHECK),
            ],
        ),
        build_ssw_fauu_bgp_scale_playbook(
            name=TEST_FSDB_RESTART_PLAYBOOK.name,
            device_regexes=[
                "fa001-du002.qzd1",
                "fa002-du002.qzd1",
            ],
            stages=TEST_FSDB_RESTART_PLAYBOOK.stages,
            prechecks=[
                create_bare_health_check(hc_types.CheckName.IXIA_PACKET_LOSS_CHECK),
            ],
            postchecks=[
                create_bare_health_check(hc_types.CheckName.IXIA_PACKET_LOSS_CHECK),
            ],
        ),
        build_ssw_fauu_bgp_scale_playbook(
            name=TEST_AGENT_WARMBOOT_AND_FSDB_RESTART_PLAYBOOK.name,
            device_regexes=[
                "fa001-du002.qzd1",
                "fa002-du002.qzd1",
            ],
            stages=TEST_AGENT_WARMBOOT_AND_FSDB_RESTART_PLAYBOOK.stages,
            prechecks=[
                create_bare_health_check(hc_types.CheckName.IXIA_PACKET_LOSS_CHECK),
            ],
            postchecks=[
                create_bare_health_check(hc_types.CheckName.IXIA_PACKET_LOSS_CHECK),
            ],
        ),
    ],
)
