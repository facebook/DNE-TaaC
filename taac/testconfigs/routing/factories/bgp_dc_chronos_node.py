# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""BGP-DC chronos_node factory (Wave 3B).

Absorbed from the pre-Wave-3B module
``testconfigs/routing/fboss_bgp_plus_plus_chronos_node_test_config.py``
(which is being removed as part of this migration). Two public factory
surfaces live here:

* ``build_bgp_dc_test_config`` — the legacy 90-arg builder. Preserved
  verbatim so byte-for-byte-identical TestConfigs continue to fall out
  of every catalog binding + external consumer (kodiak RBB, the deleted
  ``internal_test_configs.py`` inline list, etc.).

* ``create_bgp_dc_chronos_node_test_config(physical_inventory, *, name, **overrides)``
  — the framework-shaped wrapper. Fills in per-inventory knobs from
  ``PhysicalInventory.extras`` and the factory-wide chronos defaults, then delegates
  to ``build_bgp_dc_test_config`` so both paths emit identical output.

The playbook-assembly + playbook-category-registry lives on this module too
(``get_bgp_dc_playbooks`` + ``PLAYBOOK_CATEGORY_REGISTRY``) and stays
unchanged from the pre-Wave-3B source; Wave 3C-3E will split them further.
"""

from __future__ import annotations

import json

from ixia.ixia import types as ixia_types
from taac.health_checks.healthcheck_definitions import (
    create_core_dumps_snapshot_check,
)
from taac.playbooks.playbook_definitions import (
    get_longevity_playbooks,
    get_platform_hardening_playbooks,
    get_restart_playbooks,
)
from taac.task_definitions import (
    create_add_stress_static_routes_task,
    create_allow_all_v4_peer_group_patcher_tasks,
    create_configure_parallel_bgp_peers_task,
    create_coop_apply_patchers_task,
    create_coop_register_patcher_task,
    create_coop_unregister_patchers_task,
    create_run_commands_on_shell_task,
    create_wait_for_agent_convergence_task,
)
from taac.testconfigs.routing.physical_inventory import (
    PhysicalInventory,
)
from taac.testconfigs.routing.util.bgp_dc_tc_checks import (
    _apply_tc_checks_to_playbooks,
    _PERMIT_ALL_POLICY_TERM,
    build_bgp_dc_tc_postchecks,
    build_bgp_dc_tc_prechecks,
)
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import TestConfig


# =============================================================================
# Playbook Category Registry
# =============================================================================
# Maps category names to their getter functions. Each getter accepts **kwargs
# and extracts the parameters it needs. See the pre-Wave-3B module docstring
# for the historical rationale + how to add a new category.
PLAYBOOK_CATEGORY_REGISTRY = {
    "restart": get_restart_playbooks,
    "longevity": get_longevity_playbooks,
    "platform_hardening": get_platform_hardening_playbooks,
}


def get_bgp_dc_playbooks(
    playbook_categories=None,
    wedge_agent_restart_no_of_interations=None,
    **device_params,
):
    """Assemble the list of bgp_dc playbooks for a conveyor run.

    Iterates ``PLAYBOOK_CATEGORY_REGISTRY`` in insertion order (or the
    caller-supplied subset), calling each getter with the shared device
    params. The ``wedge_agent_restart_no_of_interations`` knob is routed
    only to the restart getter — passing it to
    ``get_platform_hardening_playbooks`` would perturb an unrelated default.
    """
    if playbook_categories is None:
        playbook_categories = list(PLAYBOOK_CATEGORY_REGISTRY.keys())

    playbooks = []
    for category in playbook_categories:
        if category not in PLAYBOOK_CATEGORY_REGISTRY:
            raise ValueError(
                f"Unknown playbook category: '{category}'. "
                f"Valid categories: {list(PLAYBOOK_CATEGORY_REGISTRY.keys())}"
            )
        getter = PLAYBOOK_CATEGORY_REGISTRY[category]
        # Route the agent-restart iteration override ONLY to the restart
        # getter so it never perturbs get_platform_hardening_playbooks
        # (which has its own independent default). When None, all getters
        # use their own defaults => byte-identical to the legacy behavior.
        if category == "restart" and wedge_agent_restart_no_of_interations is not None:
            playbooks.extend(
                getter(
                    wedge_agent_restart_no_of_interations=wedge_agent_restart_no_of_interations,
                    **device_params,
                )
            )
        else:
            playbooks.extend(getter(**device_params))

    return playbooks


def build_bgp_dc_test_config(
    test_config_name,
    device_name,
    local_mac_address,
    ixia_downlink_interface,
    ixia_uplink_interface,
    ixia_rogue_interface,
    peergroup_uplink_mimic_v6,
    peergroup_uplink_mimic_v4,
    peergroup_downlink_mimic_v6,
    peergroup_downlink_mimic_v4,
    peergroup_rogue_mimic_v6,
    peergroup_rogue_mimic_v4,
    route_map_uplink_ingress,
    route_map_uplink_egress,
    route_map_downlink_ingress,
    route_map_downlink_egress,
    route_map_rogue_ingress,
    route_map_rogue_egress,
    ixia_downlink_ic_parent_network_v6,
    ixia_uplink_ic_parent_network_v6,
    ixia_rogue_ic_parent_network_v6,
    ixia_downlink_ic_parent_network_v4,
    ixia_uplink_ic_parent_network_v4,
    ixia_rogue_ic_parent_network_v4,
    good_ndp_entry_network_v6,
    rogue_ndp_entry_network_v6,
    good_arp_entry_network_v4,
    rogue_arp_entry_network_v4,
    prefix_limit,
    per_peer_max_route_limit,
    downlink_peer_count,
    uplink_peer_count,
    rogue_peer_count,
    remote_downlink_as_4byte,
    remote_uplink_as_4byte,
    remote_rogue_as_4byte,
    is_uplink_peer_confed,
    is_downlink_peer_confed,
    is_rogue_peer_confed,
    ixia_downlink_prefix_count_v6,
    ixia_uplink_prefix_count_v6,
    ixia_rogue_prefix_count_v6,
    ixia_downlink_prefix_count_v4,
    ixia_uplink_prefix_count_v4,
    ixia_rogue_prefix_count_v4,
    ixia_downlink_communities,
    ixia_uplink_communities,
    uplink_peer_tag,
    downlink_peer_tag,
    ecmp_group_limit,
    good_ndp_entries_uplink,
    good_ndp_entries_downlink,
    rogue_ndp_entries,
    good_arp_entries,
    rogue_arp_entries,
    good_mac_entry_count,
    rogue_mac_entry_count,
    bgp_induced_ecmp_group_count,
    ixia_uplink_good_ndp_network,
    ixia_downlink_good_ndp_network,
    basset_pool,
    playbooks_selected=None,
    playbook_categories=None,
    direct_ixia_connections=None,
    ecmp_group_overflow_prefix="7000",  # 7000:1:f::/64
    v6_uplink_prefix="6000",
    v4_session_flapping_prefix="103",
    v6_prefix_flapping_prefix="6000",
    v4_uplink_prefix="102",
    v4_downlink_prefix="101",
    v6_downlink_prefix="3000",
    ecmp_member_limit=11500,
    additional_setup_tasks=None,
    allow_all_v4_policies=False,
    uplink_bgp_peer_type=None,
    skip_playbooks=None,
    # Quick-validation knobs (all default None => legacy behavior preserved):
    #   wedge_agent_restart_no_of_interations: override the agent-restart loop
    #     count for the test_agent_restart playbook (legacy default is 10).
    #   convergence_wait_timeout / _interval: cap the agent-convergence waits
    #     in setup_tasks so a slow/unhealthy device fails fast instead of
    #     hanging on the full per-task ceiling.
    wedge_agent_restart_no_of_interations=None,
    convergence_wait_timeout=None,
    convergence_wait_interval=None,
):
    """Build the full conveyor test configuration for a BGP++ Chronos node.

    Preserved verbatim (signature + body) from the pre-Wave-3B module so
    every existing consumer path produces byte-for-byte-identical output.
    Byte-identity is enforced by the golden manifest test.
    """
    # Collect device-specific params to forward to the playbook getters.
    # Each getter accepts **kwargs and extracts only the parameters it needs.
    # We exclude params that are not relevant to playbook generation (these
    # are either filter controls, builder defaults, or local config knobs).
    _NON_PLAYBOOK_PARAMS = (
        "playbooks_selected",
        "playbook_categories",
        "direct_ixia_connections",
        "ecmp_group_overflow_prefix",
        "v6_uplink_prefix",
        "v4_session_flapping_prefix",
        "v6_prefix_flapping_prefix",
        "v4_uplink_prefix",
        "v4_downlink_prefix",
        "v6_downlink_prefix",
        "ecmp_member_limit",
        "additional_setup_tasks",
        "allow_all_v4_policies",
        "uplink_bgp_peer_type",
        "skip_playbooks",
        # Builder-only knobs: routed explicitly below, not via **device_params.
        "wedge_agent_restart_no_of_interations",
        "convergence_wait_timeout",
        "convergence_wait_interval",
    )
    device_params = {k: v for k, v in locals().items() if k not in _NON_PLAYBOOK_PARAMS}
    playbooks = get_bgp_dc_playbooks(
        playbook_categories=playbook_categories,
        wedge_agent_restart_no_of_interations=wedge_agent_restart_no_of_interations,
        **device_params,
    )

    if playbooks_selected:
        playbooks = [
            playbook for playbook in playbooks if playbook.name in playbooks_selected
        ]

    ixia_downlink_source_ipv6 = f"{ixia_downlink_ic_parent_network_v6}::11"

    tc_snapshot_checks = [
        create_core_dumps_snapshot_check(),
    ]
    tc_postchecks = build_bgp_dc_tc_postchecks(
        prefix_limit, include_traffic_check=False
    )
    tc_prechecks = build_bgp_dc_tc_prechecks(prefix_limit, include_traffic_check=False)

    return TestConfig(
        name=test_config_name,
        ixia_protocol_verification_timeout=300,
        skip_ixia_protocol_verification=True,
        basset_pool=basset_pool,
        endpoints=[
            taac_types.Endpoint(
                name=device_name,
                ixia_ports=[
                    ixia_downlink_interface,
                    ixia_uplink_interface,
                ],
                dut=True,
                mac_address=local_mac_address,
                direct_ixia_connections=(
                    direct_ixia_connections if direct_ixia_connections else []
                ),
            ),
        ],
        setup_tasks=[
            create_run_commands_on_shell_task(
                hostname=device_name,
                cmds=["systemctl restart bgpd", "systemctl daemon-reload"],
            ),
            create_wait_for_agent_convergence_task(
                [device_name],
                timeout=convergence_wait_timeout,
                interval=convergence_wait_interval,
            ),
            create_coop_unregister_patchers_task(device_name),
            create_coop_apply_patchers_task(
                hostnames=[device_name],
            ),
            create_wait_for_agent_convergence_task(
                [device_name],
                timeout=convergence_wait_timeout,
                interval=convergence_wait_interval,
            ),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name="a_remove_bgp_peers",
                task_name="coop_register_patcher",
                patcher_args={"delete_all": "True"},
                py_func_name="remove_bgp_peers",
            ),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name="configure_bgp_switch_limit",
                task_name="coop_register_patcher",
                patcher_args={
                    "prefix_limit": prefix_limit,
                },
                py_func_name="configure_bgp_switch_limit",
            ),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="agent",
                patcher_name="enable_port_all_ixia_ports",
                task_name="coop_register_patcher",
                patcher_args={
                    f"{ixia_uplink_interface}": "enable",
                    f"{ixia_downlink_interface}": "enable",
                },
                py_func_name="change_port_admin_state",
            ),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="agent",
                patcher_name="configure_sflow_mirror_sampling",
                task_name="coop_register_patcher",
                patcher_args={
                    "name": "sflow_mirror",
                    "destination_ip": ixia_downlink_source_ipv6,
                    "sample_rate": "100",
                    "udp_src_port": "6343",
                    "udp_dst_port": "6343",
                },
                py_func_name="configure_ingress_sflow_mirror_sampling",
            ),
            # PROPAGATE_EVERYTHING ingress/egress policies for downlink
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name=f"a_add_bgp_policy_statement_PROPAGATE_EVERYTHING_{peergroup_downlink_mimic_v6}_IN",
                task_name="coop_register_patcher",
                patcher_args={
                    "name": f"PROPAGATE_EVERYTHING_{peergroup_downlink_mimic_v6}_IN",
                    "description": "Ingress policy - accept all prefixes",
                    "policy_entries": json.dumps([_PERMIT_ALL_POLICY_TERM]),
                },
                py_func_name="add_bgp_policy_statement",
            ),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name=f"a_add_bgp_policy_statement_PROPAGATE_EVERYTHING_{peergroup_downlink_mimic_v6}_OUT",
                task_name="coop_register_patcher",
                patcher_args={
                    "name": f"PROPAGATE_EVERYTHING_{peergroup_downlink_mimic_v6}_OUT",
                    "description": "Egress policy - advertise all prefixes",
                    "policy_entries": json.dumps([_PERMIT_ALL_POLICY_TERM]),
                },
                py_func_name="add_bgp_policy_statement",
            ),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name="update_peer_group_patcher_V6_Downlink",
                task_name="coop_register_patcher",
                patcher_args={
                    "name": peergroup_downlink_mimic_v6,
                    "attributes_to_update_json": json.dumps(
                        {
                            "disable_ipv4_afi": "True",
                            "v4_over_v6_nexthop": "False",
                            "is_passive": "False",
                            "is_confed_peer": is_downlink_peer_confed,
                            "max_routes": per_peer_max_route_limit,
                            "ingress_policy_name": f"PROPAGATE_EVERYTHING_{peergroup_downlink_mimic_v6}_IN",
                            "egress_policy_name": f"PROPAGATE_EVERYTHING_{peergroup_downlink_mimic_v6}_OUT",
                        }
                    ),
                },
                py_func_name="configure_bgp_peer_group",
            ),
            # PROPAGATE_EVERYTHING ingress/egress policies for uplink
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name=f"a_add_bgp_policy_statement_PROPAGATE_EVERYTHING_{peergroup_uplink_mimic_v6}_IN",
                task_name="coop_register_patcher",
                patcher_args={
                    "name": f"PROPAGATE_EVERYTHING_{peergroup_uplink_mimic_v6}_IN",
                    "description": "Ingress policy - accept all prefixes",
                    "policy_entries": json.dumps([_PERMIT_ALL_POLICY_TERM]),
                },
                py_func_name="add_bgp_policy_statement",
            ),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name=f"a_add_bgp_policy_statement_PROPAGATE_EVERYTHING_{peergroup_uplink_mimic_v6}_OUT",
                task_name="coop_register_patcher",
                patcher_args={
                    "name": f"PROPAGATE_EVERYTHING_{peergroup_uplink_mimic_v6}_OUT",
                    "description": "Egress policy - advertise all prefixes",
                    "policy_entries": json.dumps([_PERMIT_ALL_POLICY_TERM]),
                },
                py_func_name="add_bgp_policy_statement",
            ),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name=f"update_peer_group_patcher_{peergroup_uplink_mimic_v6}_Uplink",
                task_name="coop_register_patcher",
                patcher_args={
                    "name": peergroup_uplink_mimic_v6,
                    "attributes_to_update_json": json.dumps(
                        {
                            "disable_ipv4_afi": "True",
                            "v4_over_v6_nexthop": "False",
                            "is_passive": "False",
                            "is_confed_peer": is_uplink_peer_confed,
                            "max_routes": per_peer_max_route_limit,
                            "ingress_policy_name": f"PROPAGATE_EVERYTHING_{peergroup_uplink_mimic_v6}_IN",
                            "egress_policy_name": f"PROPAGATE_EVERYTHING_{peergroup_uplink_mimic_v6}_OUT",
                        }
                    ),
                },
                py_func_name="configure_bgp_peer_group",
            ),
            *(
                create_allow_all_v4_peer_group_patcher_tasks(
                    hostname=device_name,
                    peer_group_name=peergroup_uplink_mimic_v4,
                    peer_tag=uplink_peer_tag,
                    is_confed_peer=is_uplink_peer_confed,
                    per_peer_max_route_limit=per_peer_max_route_limit,
                    policy_entries_json=json.dumps([_PERMIT_ALL_POLICY_TERM]),
                )
                + create_allow_all_v4_peer_group_patcher_tasks(
                    hostname=device_name,
                    peer_group_name=peergroup_downlink_mimic_v4,
                    peer_tag=downlink_peer_tag,
                    is_confed_peer=is_downlink_peer_confed,
                    per_peer_max_route_limit=per_peer_max_route_limit,
                    policy_entries_json=json.dumps([_PERMIT_ALL_POLICY_TERM]),
                )
                if allow_all_v4_policies
                else [
                    create_coop_register_patcher_task(
                        hostname=device_name,
                        config_name="bgpcpp",
                        patcher_name=f"add_peer_group_patcher_{peergroup_uplink_mimic_v4}",
                        task_name="coop_register_patcher",
                        patcher_args={
                            "name": peergroup_uplink_mimic_v4,
                            "description": "BGP peering from SSW to FSW, IPv4 sessions",
                            "next_hop_self": "True",
                            "disable_ipv4_afi": "False",
                            "disable_ipv6_afi": "True",
                            "is_confed_peer": is_uplink_peer_confed,
                            "peer_tag": uplink_peer_tag,
                            "ingress_policy_name": route_map_uplink_ingress,
                            "egress_policy_name": route_map_uplink_egress,
                            "bgp_peer_timers_hold_time_seconds": "30",
                            "bgp_peer_timers_keep_alive_seconds": "10",
                            "bgp_peer_timers_out_delay_seconds": "7",
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
                    create_coop_register_patcher_task(
                        hostname=device_name,
                        config_name="bgpcpp",
                        patcher_name=f"add_peer_group_patcher_{peergroup_downlink_mimic_v4}",
                        task_name="coop_register_patcher",
                        patcher_args={
                            "name": peergroup_downlink_mimic_v4,
                            "description": "BGP peering from RSW to FSW, IPv4 sessions",
                            "next_hop_self": "True",
                            "disable_ipv4_afi": "False",
                            "disable_ipv6_afi": "True",
                            "is_confed_peer": is_downlink_peer_confed,
                            "ingress_policy_name": route_map_downlink_ingress,
                            "egress_policy_name": route_map_downlink_egress,
                            "bgp_peer_timers_hold_time_seconds": "30",
                            "bgp_peer_timers_keep_alive_seconds": "10",
                            "bgp_peer_timers_out_delay_seconds": "7",
                            "bgp_peer_timers_withdraw_unprog_delay_seconds": "0",
                            "peer_tag": downlink_peer_tag,
                            "max_routes": per_peer_max_route_limit,
                            "warning_only": "True",
                            "warning_limit": "0",
                            "link_bandwidth_bps": "auto",
                            "v4_over_v6_nexthop": "False",
                            "is_passive": "False",
                        },
                        py_func_name="add_peer_group_patcher",
                    ),
                    create_coop_register_patcher_task(
                        hostname=device_name,
                        config_name="bgpcpp",
                        patcher_name=f"add_bgp_policy_match_prefix_to_propagate_routes_{route_map_downlink_ingress}",
                        task_name="coop_register_patcher",
                        patcher_args={
                            "matching_prefix": f"{ecmp_group_overflow_prefix}::/16",
                            "in_stmt_name": route_map_downlink_ingress,
                            "out_stmt_name": "RANDOM",
                        },
                        py_func_name="add_bgp_policy_match_prefix_to_propagate_routes",
                    ),
                    create_coop_register_patcher_task(
                        hostname=device_name,
                        config_name="bgpcpp",
                        patcher_name=f"add_bgp_policy_match_prefix_to_propagate_routes_{route_map_uplink_ingress}",
                        task_name="coop_register_patcher",
                        patcher_args={
                            "matching_prefix": f"{ecmp_group_overflow_prefix}::/16",
                            "in_stmt_name": route_map_uplink_ingress,
                            "out_stmt_name": "RANDOM",
                        },
                        py_func_name="add_bgp_policy_match_prefix_to_propagate_routes",
                    ),
                ]
            ),
            create_add_stress_static_routes_task(
                hostname=device_name,
                max_ecmp_group=ecmp_group_limit,
                max_ecmp_members=ecmp_member_limit,
                nh_prefix_1=f"{ixia_uplink_good_ndp_network}::/80",
                lb_prefix_agg="6000:ab::/32",
                device_group_count=good_ndp_entries_uplink,
            ),
            create_configure_parallel_bgp_peers_task(
                hostname=device_name,
                configure_vlans_patcher_name="configure_vlans_patcher_name_downlink",
                add_bgp_peers_patcher_name="add_bgp_peers_patcher_name_downlink",
                config_json=json.dumps(
                    {
                        ixia_downlink_interface: [
                            {
                                "starting_ip": f"{ixia_downlink_ic_parent_network_v6}::10",
                                "increment_ip": "0:0:0:0::2",
                                "prefix_length": 127,
                                "description": "Downlink IPv6 Peers",
                                "peer_group_name": peergroup_downlink_mimic_v6,
                                "num_sessions": downlink_peer_count,
                                "remote_as_4_byte": remote_downlink_as_4byte,
                                "remote_as_4_byte_step": 1,
                                "gateway_starting_ip": f"{ixia_downlink_ic_parent_network_v6}::11",
                                "gateway_increment_ip": "0:0:0:0::2",
                            },
                            {
                                "starting_ip": f"{ixia_downlink_good_ndp_network}::1",
                                "increment_ip": "0:0:0:0::0",
                                "prefix_length": 80,
                                "description": "Downlink IPv6 NDP Peers",
                                "peer_group_name": peergroup_downlink_mimic_v6,
                                "num_sessions": 1,
                                "remote_as_4_byte": remote_downlink_as_4byte,
                                "remote_as_4_byte_step": 0,
                                "gateway_starting_ip": f"{ixia_downlink_good_ndp_network}::2",
                                "gateway_increment_ip": "0:0:0:0::2",
                                "config_only_interface_ip": True,
                            },
                            {
                                "starting_ip": f"{ixia_downlink_ic_parent_network_v4}.0",
                                "increment_ip": "0.0.0.2",
                                "prefix_length": 31,
                                "description": "Downlink IPv4 Peers",
                                "peer_group_name": peergroup_downlink_mimic_v4,
                                "num_sessions": downlink_peer_count,
                                "remote_as_4_byte": remote_downlink_as_4byte,
                                "remote_as_4_byte_step": 1,
                                "gateway_starting_ip": f"{ixia_downlink_ic_parent_network_v4}.1",
                                "gateway_increment_ip": "0.0.0.2",
                            },
                            {
                                "starting_ip": f"{rogue_arp_entry_network_v4}.0.1",
                                "increment_ip": "0.0.0.1",
                                "prefix_length": 16,
                                "description": "Downlink IPv4 Address Creation for ROGUE ARP",
                                "peer_group_name": peergroup_downlink_mimic_v4,
                                "num_sessions": 1,
                                "remote_as_4_byte": remote_downlink_as_4byte,
                                "gateway_starting_ip": f"{rogue_arp_entry_network_v4}.0.1",
                                "gateway_increment_ip": "0.0.0.1",
                                "config_only_interface_ip": True,
                            },
                        ]
                    }
                ),
            ),
            create_configure_parallel_bgp_peers_task(
                hostname=device_name,
                configure_vlans_patcher_name="configure_vlans_patcher_name_uplink",
                add_bgp_peers_patcher_name="add_bgp_peers_patcher_name_uplink",
                config_json=json.dumps(
                    {
                        ixia_uplink_interface: [
                            {
                                "starting_ip": f"{ixia_uplink_ic_parent_network_v6}::10",
                                "increment_ip": "0:0:0:0::2",
                                "prefix_length": 127,
                                "description": "Uplink IPv6 Peers",
                                "peer_group_name": peergroup_uplink_mimic_v6,
                                "num_sessions": uplink_peer_count,
                                "remote_as_4_byte": remote_uplink_as_4byte,
                                "remote_as_4_byte_step": 0,
                                "gateway_starting_ip": f"{ixia_uplink_ic_parent_network_v6}::11",
                                "gateway_increment_ip": "0:0:0:0::2",
                            },
                            {
                                "starting_ip": f"{ixia_uplink_good_ndp_network}::1",
                                "increment_ip": "0:0:0:0::0",
                                "prefix_length": 80,
                                "description": "NDP stressor",
                                "peer_group_name": peergroup_uplink_mimic_v6,
                                "num_sessions": 1,
                                "remote_as_4_byte": remote_uplink_as_4byte,
                                "remote_as_4_byte_step": 0,
                                "gateway_starting_ip": f"{ixia_uplink_ic_parent_network_v6}::2",
                                "gateway_increment_ip": "0:0:0:0::0",
                                "config_only_interface_ip": True,
                            },
                            {
                                "starting_ip": f"{ixia_uplink_ic_parent_network_v6}::400",
                                "increment_ip": "0:0:0:0::2",
                                "prefix_length": 127,
                                "description": "Uplink IPv6 Peers - for BGP Induced ECMP - 1 ",
                                "peer_group_name": peergroup_uplink_mimic_v6,
                                "num_sessions": bgp_induced_ecmp_group_count,
                                "remote_as_4_byte": remote_uplink_as_4byte,
                                "remote_as_4_byte_step": 0,
                                "gateway_starting_ip": f"{ixia_uplink_ic_parent_network_v6}::401",
                                "gateway_increment_ip": "0:0:0:0::2",
                            },
                            {
                                "starting_ip": f"{ixia_uplink_ic_parent_network_v6}::500",
                                "increment_ip": "0:0:0:0::2",
                                "prefix_length": 127,
                                "description": "Uplink IPv6 Peers - for BGP Induced ECMP - 2",
                                "peer_group_name": peergroup_uplink_mimic_v6,
                                "num_sessions": bgp_induced_ecmp_group_count,
                                "remote_as_4_byte": remote_uplink_as_4byte,
                                "remote_as_4_byte_step": 0,
                                "gateway_starting_ip": f"{ixia_uplink_ic_parent_network_v6}::501",
                                "gateway_increment_ip": "0:0:0:0::2",
                            },
                            {
                                "starting_ip": f"{ixia_uplink_ic_parent_network_v4}.0",
                                "increment_ip": "0.0.0.2",
                                "prefix_length": 31,
                                "description": "Uplink IPv4 Peers",
                                "peer_group_name": peergroup_uplink_mimic_v4,
                                "num_sessions": uplink_peer_count,
                                "remote_as_4_byte": remote_uplink_as_4byte,
                                "remote_as_4_byte_step": 0,
                                "gateway_starting_ip": f"{ixia_uplink_ic_parent_network_v4}.1",
                                "gateway_increment_ip": "0.0.0.2",
                            },
                            {
                                "starting_ip": f"{good_arp_entry_network_v4}.0.1",
                                "increment_ip": "0.0.0.1",
                                "prefix_length": 16,
                                "description": "Downlink IPv4 Address Creation for GOOD ARP",
                                "peer_group_name": peergroup_uplink_mimic_v4,
                                "num_sessions": 1,
                                "remote_as_4_byte": remote_uplink_as_4byte,
                                "gateway_starting_ip": f"{good_arp_entry_network_v4}.0.1",
                                "gateway_increment_ip": "0.0.0.1",
                                "config_only_interface_ip": True,
                            },
                            {
                                "starting_ip": f"{ixia_rogue_ic_parent_network_v6}::10",
                                "increment_ip": "0:0:0:0::2",
                                "prefix_length": 127,
                                "description": "Rogue IPv6 Peers",
                                "peer_group_name": peergroup_rogue_mimic_v6,
                                "num_sessions": rogue_peer_count,
                                "remote_as_4_byte": remote_rogue_as_4byte,
                                "remote_as_4_byte_step": 1,
                                "gateway_starting_ip": f"{ixia_rogue_ic_parent_network_v6}::11",
                                "gateway_increment_ip": "0:0:0:0::2",
                            },
                            {
                                "starting_ip": f"{ixia_rogue_ic_parent_network_v4}.0",
                                "increment_ip": "0.0.0.2",
                                "prefix_length": 31,
                                "description": "Rogue IPv4 Peers",
                                "peer_group_name": peergroup_rogue_mimic_v4,
                                "num_sessions": rogue_peer_count,
                                "remote_as_4_byte": remote_rogue_as_4byte,
                                "remote_as_4_byte_step": 1,
                                "gateway_starting_ip": f"{ixia_rogue_ic_parent_network_v4}.1",
                                "gateway_increment_ip": "0.0.0.2",
                            },
                        ]
                    }
                ),
            ),
            *(additional_setup_tasks or []),
            create_coop_apply_patchers_task(
                hostnames=[device_name],
            ),
            create_wait_for_agent_convergence_task(
                [device_name],
                timeout=convergence_wait_timeout,
                interval=convergence_wait_interval,
            ),
        ],
        teardown_tasks=[
            create_coop_unregister_patchers_task(device_name),
            create_run_commands_on_shell_task(
                hostname=device_name,
                cmds=["pkill memory_pressure"],
            ),
        ],
        basic_port_configs=[
            taac_types.BasicPortConfig(
                endpoint=f"{device_name}:{ixia_downlink_interface}",
                device_group_configs=[
                    # downlink Ipv6
                    taac_types.DeviceGroupConfig(
                        device_group_index=0,
                        tag_name="NO_V6_PACKET_LOSS_EXPECTED",
                        multiplier=downlink_peer_count,
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=ixia_downlink_source_ipv6,
                            increment_ip="0:0:0:0::2",
                            gateway_starting_ip=f"{ixia_downlink_ic_parent_network_v6}::10",
                            gateway_increment_ip="0:0:0:0::2",
                            mask=127,
                        ),
                        v6_bgp_config=taac_types.BgpConfig(
                            local_as_4_bytes=remote_downlink_as_4byte,
                            local_as_increment=1,
                            enable_4_byte_local_as=True,
                            is_confed=is_downlink_peer_confed == "True",
                            bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                            hold_timer=30,
                            keepalive_timer=10,
                            route_scales=[
                                taac_types.RouteScaleSpec(
                                    network_group_index=0,
                                    v6_route_scale=taac_types.RouteScale(
                                        multiplier=1,
                                        prefix_count=ixia_downlink_prefix_count_v6,
                                        prefix_length=64,
                                        starting_prefixes=f"{v6_downlink_prefix}:1::",
                                        prefix_step="0:0:0:0::0",
                                        bgp_communities=ixia_downlink_communities,
                                        ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                    ),
                                ),
                            ],
                        ),
                    ),
                    # Downlink IPv4
                    taac_types.DeviceGroupConfig(
                        device_group_index=1,
                        tag_name="NO_PACKET_LOSS_EXPECTED",
                        multiplier=downlink_peer_count,
                        v4_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{ixia_downlink_ic_parent_network_v4}.1",
                            increment_ip="0.0.0.2",
                            gateway_starting_ip=f"{ixia_downlink_ic_parent_network_v4}.0",
                            gateway_increment_ip="0.0.0.2",
                            mask=31,
                        ),
                        v4_bgp_config=taac_types.BgpConfig(
                            local_as_4_bytes=remote_downlink_as_4byte,
                            local_as_increment=1,
                            enable_4_byte_local_as=True,
                            is_confed=is_downlink_peer_confed == "True",
                            bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                            hold_timer=30,
                            keepalive_timer=10,
                            route_scales=[
                                taac_types.RouteScaleSpec(
                                    network_group_index=0,
                                    v4_route_scale=taac_types.RouteScale(
                                        multiplier=1,
                                        prefix_count=ixia_downlink_prefix_count_v4,
                                        prefix_length=24,
                                        starting_prefixes=f"{v4_downlink_prefix}.1.0.0",
                                        prefix_step="0.0.0.0",
                                        bgp_communities=ixia_downlink_communities,
                                        ip_address_family=ixia_types.IpAddressFamily.IPV4,
                                    ),
                                ),
                            ],
                        ),
                    ),
                    # NDP stressor downlink (kept — supports BGP NDP setup; no traffic items)
                    taac_types.DeviceGroupConfig(
                        device_group_index=2,
                        tag_name="DOWNLINK_NDP_STRESSOR",
                        multiplier=good_ndp_entries_downlink,
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{ixia_downlink_good_ndp_network}::a000",
                            increment_ip="::1",
                            gateway_starting_ip=f"{ixia_downlink_good_ndp_network}::1",
                            mask=80,
                        ),
                    ),
                    # ARP stressor downlink
                    taac_types.DeviceGroupConfig(
                        device_group_index=3,
                        tag_name="DOWNLINK_ARP_STRESSOR",
                        multiplier=1,
                        v4_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{rogue_arp_entry_network_v4}.0.100",
                            increment_ip="0.0.0.1",
                            gateway_starting_ip=f"{rogue_arp_entry_network_v4}.0.1",
                            mask=16,
                        ),
                    ),
                ],
            ),
            taac_types.BasicPortConfig(
                endpoint=f"{device_name}:{ixia_uplink_interface}",
                device_group_configs=[
                    taac_types.DeviceGroupConfig(
                        device_group_index=0,
                        tag_name="NO_V6_PACKET_LOSS_EXPECTED",
                        multiplier=uplink_peer_count,
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{ixia_uplink_ic_parent_network_v6}::11",
                            increment_ip="0:0:0:0::2",
                            gateway_starting_ip=f"{ixia_uplink_ic_parent_network_v6}::10",
                            gateway_increment_ip="0:0:0:0::2",
                            mask=127,
                        ),
                        v6_bgp_config=taac_types.BgpConfig(
                            local_as_4_bytes=remote_uplink_as_4byte,
                            local_as_increment=0,
                            enable_4_byte_local_as=True,
                            is_confed=is_uplink_peer_confed == "True",
                            bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                            hold_timer=30,
                            keepalive_timer=10,
                            bgp_peer_type=uplink_bgp_peer_type,
                            route_scales=[
                                taac_types.RouteScaleSpec(
                                    network_group_index=0,
                                    v6_route_scale=taac_types.RouteScale(
                                        multiplier=1,
                                        prefix_count=ixia_uplink_prefix_count_v6,
                                        prefix_length=64,
                                        starting_prefixes=f"{v6_uplink_prefix}:1::",
                                        prefix_step="0:0:0:0::0",
                                        bgp_communities=ixia_uplink_communities,
                                        ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                    ),
                                ),
                            ],
                        ),
                    ),
                    taac_types.DeviceGroupConfig(
                        device_group_index=1,
                        tag_name="NO_PACKET_LOSS_EXPECTED",
                        multiplier=uplink_peer_count,
                        v4_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{ixia_uplink_ic_parent_network_v4}.1",
                            increment_ip="0.0.0.2",
                            gateway_starting_ip=f"{ixia_uplink_ic_parent_network_v4}.0",
                            gateway_increment_ip="0.0.0.2",
                            mask=31,
                        ),
                        v4_bgp_config=taac_types.BgpConfig(
                            local_as_4_bytes=remote_uplink_as_4byte,
                            local_as_increment=0,
                            enable_4_byte_local_as=True,
                            is_confed=is_uplink_peer_confed == "True",
                            bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                            hold_timer=30,
                            keepalive_timer=10,
                            bgp_peer_type=uplink_bgp_peer_type,
                            route_scales=[
                                taac_types.RouteScaleSpec(
                                    network_group_index=0,
                                    v4_route_scale=taac_types.RouteScale(
                                        multiplier=1,
                                        prefix_count=ixia_uplink_prefix_count_v4,
                                        prefix_length=24,
                                        starting_prefixes=f"{v4_uplink_prefix}.1.0.0",
                                        prefix_step="0.0.0.0",
                                        bgp_communities=ixia_uplink_communities,
                                        ip_address_family=ixia_types.IpAddressFamily.IPV4,
                                    ),
                                ),
                            ],
                        ),
                    ),
                    taac_types.DeviceGroupConfig(
                        device_group_index=2,
                        tag_name="UPLINK_NDP_STRESSOR",
                        multiplier=good_ndp_entries_uplink,
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{ixia_uplink_good_ndp_network}::a000",
                            increment_ip="::1",
                            gateway_starting_ip=f"{ixia_uplink_good_ndp_network}::1",
                            mask=80,
                        ),
                    ),
                    taac_types.DeviceGroupConfig(
                        device_group_index=3,
                        tag_name="UPLINK_ARP_STRESSOR",
                        multiplier=good_arp_entries,
                        v4_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{good_arp_entry_network_v4}.0.100",
                            increment_ip="0.0.0.1",
                            gateway_starting_ip=f"{good_arp_entry_network_v4}.0.1",
                            mask=16,
                        ),
                    ),
                    taac_types.DeviceGroupConfig(
                        device_group_index=4,
                        tag_name="UPLINK_BGP_INDUCED_ECMP_1",
                        enable=True,
                        multiplier=bgp_induced_ecmp_group_count,
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{ixia_uplink_ic_parent_network_v6}::401",
                            increment_ip="0:0:0:0::2",
                            gateway_starting_ip=f"{ixia_uplink_ic_parent_network_v6}::400",
                            gateway_increment_ip="0:0:0:0::2",
                            mask=80,
                        ),
                        v6_bgp_config=taac_types.BgpConfig(
                            local_as_4_bytes=remote_uplink_as_4byte,
                            local_as_increment=0,
                            enable_4_byte_local_as=True,
                            bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                            hold_timer=30,
                            keepalive_timer=10,
                            bgp_peer_type=uplink_bgp_peer_type,
                            route_scales=[
                                taac_types.RouteScaleSpec(
                                    network_group_index=0,
                                    v6_route_scale=taac_types.RouteScale(
                                        multiplier=1,
                                        prefix_count=1,
                                        prefix_length=64,
                                        starting_prefixes=f"{ecmp_group_overflow_prefix}:1:f::",
                                        prefix_step="0:0:0:1::0",
                                        bgp_communities=ixia_uplink_communities,
                                        ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                    ),
                                ),
                            ],
                        ),
                    ),
                    taac_types.DeviceGroupConfig(
                        device_group_index=5,
                        tag_name="UPLINK_BGP_INDUCED_ECMP_2",
                        enable=False,
                        multiplier=bgp_induced_ecmp_group_count,
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{ixia_uplink_ic_parent_network_v6}::501",
                            increment_ip="0:0:0:0::2",
                            gateway_starting_ip=f"{ixia_uplink_ic_parent_network_v6}::500",
                            gateway_increment_ip="0:0:0:0::2",
                            mask=80,
                        ),
                        v6_bgp_config=taac_types.BgpConfig(
                            local_as_4_bytes=remote_uplink_as_4byte,
                            local_as_increment=0,
                            enable_4_byte_local_as=True,
                            bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                            hold_timer=30,
                            keepalive_timer=10,
                            bgp_peer_type=uplink_bgp_peer_type,
                            route_scales=[
                                taac_types.RouteScaleSpec(
                                    network_group_index=0,
                                    v6_route_scale=taac_types.RouteScale(
                                        multiplier=1,
                                        prefix_count=1,
                                        prefix_length=64,
                                        starting_prefixes=f"{ecmp_group_overflow_prefix}:1:f::",
                                        prefix_step="0:0:0:1::0",
                                        bgp_communities=ixia_uplink_communities,
                                        ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                    ),
                                ),
                            ],
                        ),
                    ),
                    taac_types.DeviceGroupConfig(
                        device_group_index=6,
                        tag_name="ROGUE_PREFIX_FLAP",
                        multiplier=rogue_peer_count,
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{ixia_rogue_ic_parent_network_v6}::11",
                            increment_ip="0:0:0:0::2",
                            gateway_starting_ip=f"{ixia_rogue_ic_parent_network_v6}::10",
                            gateway_increment_ip="0:0:0:0::2",
                            mask=127,
                        ),
                        v6_bgp_config=taac_types.BgpConfig(
                            local_as_4_bytes=remote_rogue_as_4byte,
                            local_as_increment=1,
                            enable_4_byte_local_as=True,
                            is_confed=is_rogue_peer_confed == "True",
                            bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                            hold_timer=30,
                            keepalive_timer=10,
                            route_scales=[
                                taac_types.RouteScaleSpec(
                                    network_group_index=0,
                                    v6_route_scale=taac_types.RouteScale(
                                        multiplier=1,
                                        prefix_count=ixia_rogue_prefix_count_v6,
                                        prefix_length=64,
                                        starting_prefixes=f"{v6_prefix_flapping_prefix}:f::",
                                        prefix_step="0:0:0:0::0",
                                        bgp_communities=ixia_uplink_communities,
                                        ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                        prefix_flap_config=ixia_types.BgpFlapConfig(
                                            uptime_in_sec=15, downtime_in_sec=15
                                        ),
                                    ),
                                ),
                            ],
                        ),
                    ),
                    taac_types.DeviceGroupConfig(
                        device_group_index=7,
                        tag_name="ROGUE_SESSION_FLAP",
                        multiplier=rogue_peer_count,
                        v4_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{ixia_rogue_ic_parent_network_v4}.1",
                            increment_ip="0.0.0.2",
                            gateway_starting_ip=f"{ixia_rogue_ic_parent_network_v4}.0",
                            gateway_increment_ip="0.0.0.2",
                            mask=31,
                        ),
                        v4_bgp_config=taac_types.BgpConfig(
                            local_as_4_bytes=remote_rogue_as_4byte,
                            local_as_increment=1,
                            enable_4_byte_local_as=True,
                            is_confed=is_rogue_peer_confed == "True",
                            bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                            hold_timer=30,
                            keepalive_timer=10,
                            peer_flap_config=ixia_types.BgpFlapConfig(
                                uptime_in_sec=120, downtime_in_sec=15
                            ),
                            route_scales=[
                                taac_types.RouteScaleSpec(
                                    network_group_index=0,
                                    v4_route_scale=taac_types.RouteScale(
                                        multiplier=1,
                                        prefix_count=ixia_rogue_prefix_count_v4,
                                        prefix_length=24,
                                        starting_prefixes=f"{v4_session_flapping_prefix}.1.0.0",
                                        prefix_step="0.0.0.0",
                                        bgp_communities=ixia_uplink_communities,
                                        ip_address_family=ixia_types.IpAddressFamily.IPV4,
                                    ),
                                ),
                            ],
                        ),
                    ),
                ],
            ),
        ],
        # No basic_traffic_item_configs and no traffic_items_to_start —
        # this BGP DC builder runs setup + playbooks only, with no IXIA
        # traffic generation.
        traffic_items_to_start=[],
        basic_traffic_item_configs=[],
        playbooks=_apply_tc_checks_to_playbooks(
            playbooks=[pb for pb in playbooks if pb.name not in (skip_playbooks or [])],
            tc_prechecks=tc_prechecks,
            tc_postchecks=tc_postchecks,
            tc_snapshot_checks=tc_snapshot_checks,
        ),
    )


# =============================================================================
# Framework-shaped wrapper (Wave 3B)
# =============================================================================

# Shared BGP-DC chronos scale + tagging defaults. Every full-scale chronos
# binding used these values before Wave 3B (verified across all 4
# pre-migration bindings). The FRAMEWORK_VALIDATION binding overrides
# select subsets to reduce scale for its smoke-test profile. Deliberately
# ``str`` for the two peer-route limits and ``int`` everywhere else, to
# match how the legacy source spelled them.
_CHRONOS_DEFAULTS = {
    "prefix_limit": "75000",
    "per_peer_max_route_limit": "25000",
    "downlink_peer_count": 20,
    "uplink_peer_count": 20,
    "rogue_peer_count": 20,
    "ixia_downlink_prefix_count_v6": 10000,
    "ixia_uplink_prefix_count_v6": 10000,
    "ixia_rogue_prefix_count_v6": 17500,
    "ixia_downlink_prefix_count_v4": 7500,
    "ixia_uplink_prefix_count_v4": 7500,
    "ixia_rogue_prefix_count_v4": 17500,
    "downlink_peer_tag": "RSW",
    "uplink_peer_tag": "SSW",
    "ecmp_group_limit": 1520,
    "good_ndp_entries_uplink": 250,
    "good_ndp_entries_downlink": 200,
    "rogue_ndp_entries": 10000,
    "good_arp_entries": 500,
    "rogue_arp_entries": 1500,
    "good_mac_entry_count": 100,
    "rogue_mac_entry_count": 200,
    "bgp_induced_ecmp_group_count": 50,
    "basset_pool": "dne.test",
}

# ``extras`` keys pulled from PhysicalInventory. Ordering doesn't matter; the mapping
# just enumerates every knob the wrapper resolves from PhysicalInventory.extras.
_PHYSICAL_INVENTORY_EXTRA_KEYS = (
    "ixia_downlink_interface",
    "ixia_uplink_interface",
    "ixia_rogue_interface",
    "peergroup_uplink_mimic_v6",
    "peergroup_uplink_mimic_v4",
    "peergroup_downlink_mimic_v6",
    "peergroup_downlink_mimic_v4",
    "peergroup_rogue_mimic_v6",
    "peergroup_rogue_mimic_v4",
    "route_map_uplink_ingress",
    "route_map_uplink_egress",
    "route_map_downlink_ingress",
    "route_map_downlink_egress",
    "route_map_rogue_ingress",
    "route_map_rogue_egress",
    "ixia_downlink_ic_parent_network_v6",
    "ixia_uplink_ic_parent_network_v6",
    "ixia_rogue_ic_parent_network_v6",
    "ixia_downlink_ic_parent_network_v4",
    "ixia_uplink_ic_parent_network_v4",
    "ixia_rogue_ic_parent_network_v4",
    "good_ndp_entry_network_v6",
    "rogue_ndp_entry_network_v6",
    "good_arp_entry_network_v4",
    "rogue_arp_entry_network_v4",
    "ixia_uplink_good_ndp_network",
    "ixia_downlink_good_ndp_network",
    "remote_downlink_as_4byte",
    "remote_uplink_as_4byte",
    "remote_rogue_as_4byte",
    "is_uplink_peer_confed",
    "is_downlink_peer_confed",
    "is_rogue_peer_confed",
    "ixia_downlink_communities",
    "ixia_uplink_communities",
)


def create_bgp_dc_chronos_node_test_config(
    physical_inventory: PhysicalInventory,
    *,
    name: str,
    **overrides,
) -> TestConfig:
    """Build a BGP-DC chronos_node TestConfig from a PhysicalInventory + per-binding overrides.

    Wave-3B wrapper around :func:`build_bgp_dc_test_config`. Pulls every
    per-inventory knob from ``physical_inventory.extras`` (see ``_PHYSICAL_INVENTORY_EXTRA_KEYS``),
    layers the shared chronos scale defaults from ``_CHRONOS_DEFAULTS`` on
    top, then applies ``**overrides`` (playbook selections + any scale
    tweaks) last. The final dict is unpacked into the legacy 90-arg builder,
    so output is byte-for-byte-identical to the pre-Wave-3B path.
    """
    kwargs: dict = {
        "test_config_name": name,
        "device_name": physical_inventory.device_name,
        "local_mac_address": physical_inventory.mac_address,
    }
    for key in _PHYSICAL_INVENTORY_EXTRA_KEYS:
        if key in physical_inventory.extras:
            kwargs[key] = physical_inventory.extras[key]
    for key, value in _CHRONOS_DEFAULTS.items():
        kwargs.setdefault(key, value)
    kwargs.update(overrides)
    return build_bgp_dc_test_config(**kwargs)
