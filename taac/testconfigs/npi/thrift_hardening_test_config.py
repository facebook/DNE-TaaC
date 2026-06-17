# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""
NPI Thrift Hardening (THFT) Test Configuration

Drives a Pavan-design thrift-stress + qsfp-flap background on a FBOSS DUT
for `test_duration_s` seconds via `create_thrift_stress_periodic_task`. No
foreground triggers in THFT_000 — THFT_001..004 will layer process-restart
steps on top of this same background in a future diff.

Mirrors (does NOT import from) the NPI CPU-queue TestConfig's BGP peer
scaffolding so the validation chain has BGP sessions to assert against
(BGP_SESSION_ESTABLISH precheck + BGP_PEER_ROUTE snapshot). Intentionally
DROPS the cpu_queue testconfig's IXIA traffic items + prefix_limit_check —
THFT has no user-traffic to measure, just thrift load on the agent + qsfp
flaps on the fabric.

THFT TestConfigs are constructed from the centralized
`create_npi_thrift_hardening_test_config` factory below. Adding a new NPI
device under THFT coverage = add one factory call + re-export from this
package's `__init__.py`.
"""

import asyncio
import json

from ixia.ixia import types as ixia_types
from taac.playbooks.playbook_definitions import (
    add_common_checks_to_thft_playbooks,
    create_thft_playbooks,
)
from taac.task_definitions import (
    create_assert_thrift_rate_limit_enabled_task,
    create_configure_parallel_bgp_peers_task,
    create_coop_apply_patchers_task,
    create_coop_register_patcher_task,
    create_coop_unregister_patchers_task,
    create_wait_for_agent_convergence_task,
)
from taac.utils.netwhoami_utils import fetch_whoami
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import TestConfig


def _assert_fboss_platform(hostname: str) -> None:
    """Sanity-check that the DUT is a FBOSS platform supported by the THFT
    periodic-task payload (which calls FBOSS-only thrift APIs +
    wedge_qsfp_util)."""
    try:
        netwhoami = asyncio.run(fetch_whoami(hostname))
        hardware = netwhoami.hw.name if netwhoami.hw else ""
        if hardware not in (
            "MONTBLANC",  # Minipack3 (TH5)
            "MINIPACK3BA",  # Minipack3BA
            "ICECUBE800BC",  # IcePack TH6
            "MORGAN800CC",  # Kodiak3 (TH4)
        ):
            raise ValueError(
                f"Unsupported hardware '{hardware}' for {hostname}. "
                f"THFT periodic task uses FBOSS-only thrift APIs."
            )
    except Exception as e:
        if isinstance(e, ValueError):
            raise
        raise Exception(f"Failed to fetch netwhoami for {hostname}: {e}") from e


def create_npi_thrift_hardening_test_config(
    test_config_name: str,
    device_name: str,
    local_mac_address: str,
    ixia_downlink_interface: str,
    ixia_uplink_interface: str,
    peergroup_uplink_mimic_v6: str,
    peergroup_uplink_mimic_v4: str,
    peergroup_downlink_mimic_v6: str,
    peergroup_downlink_mimic_v4: str,
    route_map_uplink_ingress: str,
    route_map_uplink_egress: str,
    route_map_downlink_ingress: str,
    route_map_downlink_egress: str,
    ixia_downlink_ic_parent_network_v6: str,
    ixia_uplink_ic_parent_network_v6: str,
    ixia_downlink_ic_parent_network_v4: str,
    ixia_uplink_ic_parent_network_v4: str,
    unique_prefix_limit: str,
    per_peer_max_route_limit: str,
    downlink_peer_count: int,
    uplink_peer_count: int,
    remote_uplink_as_4byte: int,
    remote_downlink_as_4byte: int,
    remote_as_4_byte_step: int,
    is_uplink_peer_confed: str,
    is_downlink_peer_confed: str,
    ixia_downlink_prefix_count_v6: int,
    ixia_uplink_prefix_count_v6: int,
    ixia_downlink_prefix_count_v4: int,
    ixia_uplink_prefix_count_v4: int,
    ixia_downlink_communities: list,
    ixia_uplink_communities: list,
    uplink_peer_tag: str,
    downlink_peer_tag: str,
    stsw_flap_ports: list,
    test_duration_s: int = 600,
    restart_test_duration_s: int = 3600,
    restart_period_s: int = 300,
    requests_per_burst: int = 10000,
    burst_timeout_s: float = 60.0,
    direct_ixia_connections=None,
    basset_pool: str | None = None,
    service_restart_services: list | None = None,
):
    """Build the NPI Thrift Hardening (THFT) TestConfig.

    Args:
        test_config_name: Name to register in the TestConfig (CLI-callable).
        device_name: DUT hostname (FBOSS-only).
        local_mac_address: Local MAC address for the DUT side of IXIA peering.
        ixia_downlink_interface / ixia_uplink_interface: DUT-facing IXIA ports
            for the BGP peer groups. These two ports back the only Endpoint
            entry — THFT doesn't need a rogue interface.
        peergroup_*_mimic_v6 / _v4: BGP peer-group names per direction + AFI.
        route_map_*_ingress / _egress: Inbound/outbound policy per direction.
        ixia_*_ic_parent_network_v6 / _v4: IXIA-side parent IP per interface.
        unique_prefix_limit: Per-peer unique-prefix cap programmed on the DUT.
        per_peer_max_route_limit: Per-peer max-route guard.
        downlink_peer_count / uplink_peer_count: Mimic peer counts per direction.
        remote_uplink_as_4byte / remote_downlink_as_4byte: Remote AS numbers.
        remote_as_4_byte_step: Remote-AS increment between peers.
        is_uplink_peer_confed / is_downlink_peer_confed: "True"/"False" string.
        ixia_*_prefix_count_v6 / _v4: Prefix counts per direction + AFI.
        ixia_*_communities: BGP communities the IXIA mimics advertise.
        uplink_peer_tag / downlink_peer_tag: peer_tag values on the v4 groups.
        stsw_flap_ports: DUT-side ports the qsfp-flap entry will tx_disable/
            tx_enable. Caller-owned (e.g. STSW-adjacent uplinks for a GTSW,
            GTSW-adjacent uplinks for an STSW, etc.). EXCLUDE IXIA-facing
            ports — flapping those breaks IXIA peering and would invalidate
            the BGP_SESSION_ESTABLISH precheck.
        test_duration_s: THFT_001 baseline longevity duration (default 600s =
            10 min smoke). Production passes 14400 (4 hr).
        restart_test_duration_s: Per-playbook duration for THFT_002..005
            (each restart-variant). Default 3600s (1 hr) so the 4 restart
            variants total ~4hr — matches the THFT_001 4hr soak instead of
            blowing the campaign wall-time up to 5×4=20hr.
        direct_ixia_connections: Optional explicit direct-IXIA mapping.
        basset_pool: Optional override pool selection. Default "dne.test".
        service_restart_services: Override default service-restart-check list.

    Returns:
        TestConfig: The NPI THFT TestConfig.
    """
    _assert_fboss_platform(device_name)
    return TestConfig(
        name=test_config_name,
        ixia_protocol_verification_timeout=600,
        basset_pool=basset_pool or "dne.test",
        # IXIA cache opt-out — same pattern as cpu_queue testconfig. Tier 1
        # LoadConfig does NOT rehydrate Python-side `self.vport_indices`
        # (`ixia/ixia.py:4566`); any CustomStep that reads `vport_indices`
        # KeyErrors on cache hit. THFT periodic task doesn't read it today,
        # but the opt-out is cheap and matches the established convention.
        ixia_config_cache=taac_types.IxiaConfigCache(enabled=False),
        endpoints=[
            taac_types.Endpoint(
                name=device_name,
                ixia_ports=[
                    ixia_downlink_interface,
                    ixia_uplink_interface,
                ],
                dut=True,
                mac_address=local_mac_address,
                direct_ixia_connections=direct_ixia_connections or [],
            ),
        ],
        # Setup tasks: BGP peer scaffolding (mirrors NPI cpu_queue testconfig,
        # MINUS the rogue interface — THFT only needs downlink+uplink for
        # BGP_SESSION_ESTABLISH precheck + BGP_PEER_ROUTE snapshot).
        #
        # `create_assert_thrift_rate_limit_enabled_task` runs FIRST as a
        # fail-fast gate. It reads the COOP-materialized agent config at
        # `/etc/coop/agent/current` on the DUT and asserts that the
        # `thriftApiToRateLimitInQps` map is populated. Without this map
        # the THFT 70K-concurrent burst would peg `fboss_sw_agent` CPU at
        # 1339% and cascade into kernel OOMs (T275336067 / T275512222).
        # With D108220182 landed and confirmed working on gtsw001 (2026-06-11
        # — 140 APIs in the map, bgpd at 1% CPU under the storm), this
        # precheck should PASS on any TH6 IcePack device.
        setup_tasks=[
            create_assert_thrift_rate_limit_enabled_task(device_name),
            create_coop_unregister_patchers_task(device_name),
            # Remove all existing BGP peers first.
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name="a_remove_bgp_peers",
                task_name="coop_register_patcher",
                patcher_args={"delete_all": "True"},
                py_func_name="remove_bgp_peers",
            ),
            # Configure BGP switch prefix limit.
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name="configure_bgp_switch_limit",
                task_name="coop_register_patcher",
                patcher_args={"prefix_limit": unique_prefix_limit},
                py_func_name="configure_bgp_switch_limit",
            ),
            # Update existing v6 peer groups (downlink + uplink).
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name=f"update_peer_group_patcher_{peergroup_downlink_mimic_v6}",
                task_name="coop_register_patcher",
                patcher_args={
                    "name": peergroup_downlink_mimic_v6,
                    "attributes_to_update_json": json.dumps(
                        {
                            "disable_ipv4_afi": "True",
                            "v4_over_v6_nexthop": "False",
                            "is_passive": "False",
                            "max_routes": per_peer_max_route_limit,
                            "is_confed_peer": is_downlink_peer_confed,
                        }
                    ),
                },
                py_func_name="configure_bgp_peer_group",
            ),
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name=f"update_peer_group_patcher_{peergroup_uplink_mimic_v6}",
                task_name="coop_register_patcher",
                patcher_args={
                    "name": peergroup_uplink_mimic_v6,
                    "attributes_to_update_json": json.dumps(
                        {
                            "disable_ipv4_afi": "True",
                            "v4_over_v6_nexthop": "False",
                            "is_passive": "False",
                            "max_routes": per_peer_max_route_limit,
                            "is_confed_peer": is_uplink_peer_confed,
                        }
                    ),
                },
                py_func_name="configure_bgp_peer_group",
            ),
            # Add v4 peer groups (downlink + uplink) — these are net-new on
            # devices where the prod config has only v6 groups.
            create_coop_register_patcher_task(
                hostname=device_name,
                config_name="bgpcpp",
                patcher_name=f"add_peer_group_patcher_{peergroup_downlink_mimic_v4}",
                task_name="coop_register_patcher",
                patcher_args={
                    "name": peergroup_downlink_mimic_v4,
                    "description": "THFT downlink IPv4 BGP mimic",
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
                patcher_name=f"add_peer_group_patcher_{peergroup_uplink_mimic_v4}",
                task_name="coop_register_patcher",
                patcher_args={
                    "name": peergroup_uplink_mimic_v4,
                    "description": "THFT uplink IPv4 BGP mimic",
                    "next_hop_self": "True",
                    "disable_ipv4_afi": "False",
                    "disable_ipv6_afi": "False",
                    "is_confed_peer": is_uplink_peer_confed,
                    "ingress_policy_name": route_map_uplink_ingress,
                    "egress_policy_name": route_map_uplink_egress,
                    "bgp_peer_timers_hold_time_seconds": "30",
                    "bgp_peer_timers_keep_alive_seconds": "10",
                    "bgp_peer_timers_out_delay_seconds": "7",
                    "bgp_peer_timers_withdraw_unprog_delay_seconds": "0",
                    "peer_tag": uplink_peer_tag,
                    "warning_only": "True",
                    "max_routes": per_peer_max_route_limit,
                    "warning_limit": "0",
                    "link_bandwidth_bps": "auto",
                    "v4_over_v6_nexthop": "true",
                    "is_passive": "False",
                    "receive_link_bandwidth": "1",
                },
                py_func_name="add_peer_group_patcher",
            ),
            create_coop_apply_patchers_task(
                hostnames=[device_name],
                config_name="bgpcpp",
            ),
            # Configure IXIA-side parallel BGP peers on the downlink port.
            create_configure_parallel_bgp_peers_task(
                hostname=device_name,
                peer_configs=[
                    {
                        "configure_vlans_patcher_name": "configure_vlans_patcher_name_downlink",
                        "add_bgp_peers_patcher_name": "add_bgp_peers_patcher_name_downlink",
                        "config_json": json.dumps(
                            {
                                ixia_downlink_interface: [
                                    {
                                        "starting_ip": f"{ixia_downlink_ic_parent_network_v6}::10",
                                        "increment_ip": "0:0:0:0::2",
                                        "prefix_length": 127,
                                        "description": "THFT downlink IPv6 peers",
                                        "peer_group_name": peergroup_downlink_mimic_v6,
                                        "num_sessions": downlink_peer_count,
                                        "remote_as_4_byte": remote_downlink_as_4byte,
                                        "remote_as_4_byte_step": remote_as_4_byte_step,
                                        "gateway_starting_ip": f"{ixia_downlink_ic_parent_network_v6}::11",
                                        "gateway_increment_ip": "0:0:0:0::2",
                                    },
                                    {
                                        "starting_ip": f"{ixia_downlink_ic_parent_network_v4}.0",
                                        "increment_ip": "0.0.0.2",
                                        "prefix_length": 31,
                                        "description": "THFT downlink IPv4 peers",
                                        "peer_group_name": peergroup_downlink_mimic_v4,
                                        "num_sessions": downlink_peer_count,
                                        "remote_as_4_byte": remote_downlink_as_4byte,
                                        "remote_as_4_byte_step": remote_as_4_byte_step,
                                        "gateway_starting_ip": f"{ixia_downlink_ic_parent_network_v4}.1",
                                        "gateway_increment_ip": "0.0.0.2",
                                    },
                                ]
                            }
                        ),
                    }
                ],
            ),
            create_wait_for_agent_convergence_task(hostnames=[device_name]),
            # Configure IXIA-side parallel BGP peers on the uplink port.
            create_configure_parallel_bgp_peers_task(
                hostname=device_name,
                peer_configs=[
                    {
                        "configure_vlans_patcher_name": "configure_vlans_patcher_name_uplink",
                        "add_bgp_peers_patcher_name": "add_bgp_peers_patcher_name_uplink",
                        "config_json": json.dumps(
                            {
                                ixia_uplink_interface: [
                                    {
                                        "starting_ip": f"{ixia_uplink_ic_parent_network_v6}::10",
                                        "increment_ip": "0:0:0:0::2",
                                        "prefix_length": 127,
                                        "description": "THFT uplink IPv6 peers",
                                        "peer_group_name": peergroup_uplink_mimic_v6,
                                        "num_sessions": uplink_peer_count,
                                        "remote_as_4_byte": remote_uplink_as_4byte,
                                        "remote_as_4_byte_step": remote_as_4_byte_step,
                                        "gateway_starting_ip": f"{ixia_uplink_ic_parent_network_v6}::11",
                                        "gateway_increment_ip": "0:0:0:0::2",
                                    },
                                    {
                                        "starting_ip": f"{ixia_uplink_ic_parent_network_v4}.0",
                                        "increment_ip": "0.0.0.2",
                                        "prefix_length": 31,
                                        "description": "THFT uplink IPv4 peers",
                                        "peer_group_name": peergroup_uplink_mimic_v4,
                                        "num_sessions": uplink_peer_count,
                                        "remote_as_4_byte": remote_uplink_as_4byte,
                                        "remote_as_4_byte_step": remote_as_4_byte_step,
                                        "gateway_starting_ip": f"{ixia_uplink_ic_parent_network_v4}.1",
                                        "gateway_increment_ip": "0.0.0.2",
                                    },
                                ]
                            }
                        ),
                    }
                ],
            ),
            create_coop_apply_patchers_task(hostnames=[device_name]),
        ],
        teardown_tasks=[
            create_coop_unregister_patchers_task(device_name),
        ],
        # IXIA ports: downlink + uplink BGP scaffolding. Mirrors cpu_queue
        # but without the rogue interface.
        basic_port_configs=[
            taac_types.BasicPortConfig(
                endpoint=f"{device_name}:{ixia_downlink_interface}",
                device_group_configs=[
                    taac_types.DeviceGroupConfig(
                        device_group_index=0,
                        multiplier=downlink_peer_count,
                        v6_addresses_config=taac_types.IpAddressesConfig(
                            starting_ip=f"{ixia_downlink_ic_parent_network_v6}::11",
                            increment_ip="0:0:0:0::2",
                            gateway_starting_ip=f"{ixia_downlink_ic_parent_network_v6}::10",
                            gateway_increment_ip="0:0:0:0::2",
                        ),
                        v6_bgp_config=taac_types.BgpConfig(
                            local_as_4_bytes=remote_downlink_as_4byte,
                            local_as_increment=1,
                            enable_4_byte_local_as=True,
                            is_confed=is_downlink_peer_confed == "True",
                            bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                            route_scales=[
                                taac_types.RouteScaleSpec(
                                    network_group_index=0,
                                    v6_route_scale=taac_types.RouteScale(
                                        multiplier=1,
                                        prefix_count=ixia_downlink_prefix_count_v6,
                                        prefix_length=64,
                                        starting_prefixes="9000:1::",
                                        prefix_step="0:0:0:0::0",
                                        bgp_communities=ixia_downlink_communities,
                                        ip_address_family=ixia_types.IpAddressFamily.IPV6,
                                    ),
                                ),
                            ],
                        ),
                    ),
                    taac_types.DeviceGroupConfig(
                        device_group_index=1,
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
                            route_scales=[
                                taac_types.RouteScaleSpec(
                                    network_group_index=0,
                                    v4_route_scale=taac_types.RouteScale(
                                        multiplier=1,
                                        prefix_count=ixia_downlink_prefix_count_v4,
                                        prefix_length=24,
                                        starting_prefixes="101.1.0.0",
                                        prefix_step="0.0.0.0",
                                        bgp_communities=ixia_downlink_communities,
                                        ip_address_family=ixia_types.IpAddressFamily.IPV4,
                                    ),
                                ),
                            ],
                        ),
                    ),
                ],
            ),
            taac_types.BasicPortConfig(
                endpoint=f"{device_name}:{ixia_uplink_interface}",
                device_group_configs=[
                    taac_types.DeviceGroupConfig(
                        device_group_index=0,
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
                            local_as_increment=1,
                            enable_4_byte_local_as=True,
                            is_confed=is_uplink_peer_confed == "True",
                            bgp_capabilities=[ixia_types.BgpCapability.IpV6Unicast],
                            route_scales=[
                                taac_types.RouteScaleSpec(
                                    network_group_index=0,
                                    v6_route_scale=taac_types.RouteScale(
                                        multiplier=1,
                                        prefix_count=ixia_uplink_prefix_count_v6,
                                        prefix_length=64,
                                        starting_prefixes="8000:1::",
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
                            local_as_increment=1,
                            enable_4_byte_local_as=True,
                            is_confed=is_uplink_peer_confed == "True",
                            bgp_capabilities=[ixia_types.BgpCapability.IpV4Unicast],
                            route_scales=[
                                taac_types.RouteScaleSpec(
                                    network_group_index=0,
                                    v4_route_scale=taac_types.RouteScale(
                                        multiplier=1,
                                        prefix_count=ixia_uplink_prefix_count_v4,
                                        prefix_length=24,
                                        starting_prefixes="201.1.0.0",
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
        # No basic_traffic_item_configs — THFT has no user-traffic test plane;
        # the disruption is thrift load on the agent + qsfp flaps via the
        # periodic task attached to each playbook.
        playbooks=add_common_checks_to_thft_playbooks(
            create_thft_playbooks(
                device_name=device_name,
                stsw_flap_ports=stsw_flap_ports,
                test_duration_s=test_duration_s,
                restart_test_duration_s=restart_test_duration_s,
                restart_period_s=restart_period_s,
                requests_per_burst=requests_per_burst,
                burst_timeout_s=burst_timeout_s,
            ),
            service_restart_services=service_restart_services,
        ),
    )


# ---------------------------------------------------------------------------
# IcePack GTSW STSW-adjacent flap port list (128 ports across 8 STSW peers).
# Discovered live on `gtsw001.l1001.c085.ash6` via `fboss2 show interface`
# (rows with Description starting with `stsw001.s00X.l201.ash6`).
# ---------------------------------------------------------------------------

ICEPACK_GTSW_STSW_FLAP_PORTS = [
    # stsw001.s001.l201.ash6 — 16 ports
    "eth1/3/1",
    "eth1/3/3",
    "eth1/3/5",
    "eth1/3/7",
    "eth1/4/1",
    "eth1/4/3",
    "eth1/4/5",
    "eth1/4/7",
    "eth1/7/1",
    "eth1/7/3",
    "eth1/7/5",
    "eth1/7/7",
    "eth1/8/1",
    "eth1/8/3",
    "eth1/8/5",
    "eth1/8/7",
    # stsw001.s002.l201.ash6 — 16 ports
    "eth1/11/1",
    "eth1/11/3",
    "eth1/11/5",
    "eth1/11/7",
    "eth1/12/1",
    "eth1/12/3",
    "eth1/12/5",
    "eth1/12/7",
    "eth1/15/1",
    "eth1/15/3",
    "eth1/15/5",
    "eth1/15/7",
    "eth1/16/1",
    "eth1/16/3",
    "eth1/16/5",
    "eth1/16/7",
    # stsw001.s003.l201.ash6 — 16 ports
    "eth1/19/1",
    "eth1/19/3",
    "eth1/19/5",
    "eth1/19/7",
    "eth1/20/1",
    "eth1/20/3",
    "eth1/20/5",
    "eth1/20/7",
    "eth1/23/1",
    "eth1/23/3",
    "eth1/23/5",
    "eth1/23/7",
    "eth1/24/1",
    "eth1/24/3",
    "eth1/24/5",
    "eth1/24/7",
    # stsw001.s004.l201.ash6 — 16 ports
    "eth1/27/1",
    "eth1/27/3",
    "eth1/27/5",
    "eth1/27/7",
    "eth1/28/1",
    "eth1/28/3",
    "eth1/28/5",
    "eth1/28/7",
    "eth1/31/1",
    "eth1/31/3",
    "eth1/31/5",
    "eth1/31/7",
    "eth1/32/1",
    "eth1/32/3",
    "eth1/32/5",
    "eth1/32/7",
    # stsw001.s005.l201.ash6 — 16 ports
    "eth1/35/1",
    "eth1/35/3",
    "eth1/35/5",
    "eth1/35/7",
    "eth1/36/1",
    "eth1/36/3",
    "eth1/36/5",
    "eth1/36/7",
    "eth1/39/1",
    "eth1/39/3",
    "eth1/39/5",
    "eth1/39/7",
    "eth1/40/1",
    "eth1/40/3",
    "eth1/40/5",
    "eth1/40/7",
    # stsw001.s006.l201.ash6 — 16 ports
    "eth1/43/1",
    "eth1/43/3",
    "eth1/43/5",
    "eth1/43/7",
    "eth1/44/1",
    "eth1/44/3",
    "eth1/44/5",
    "eth1/44/7",
    "eth1/47/1",
    "eth1/47/3",
    "eth1/47/5",
    "eth1/47/7",
    "eth1/48/1",
    "eth1/48/3",
    "eth1/48/5",
    "eth1/48/7",
    # stsw001.s007.l201.ash6 — 16 ports
    "eth1/51/1",
    "eth1/51/3",
    "eth1/51/5",
    "eth1/51/7",
    "eth1/52/1",
    "eth1/52/3",
    "eth1/52/5",
    "eth1/52/7",
    "eth1/55/1",
    "eth1/55/3",
    "eth1/55/5",
    "eth1/55/7",
    "eth1/56/1",
    "eth1/56/3",
    "eth1/56/5",
    "eth1/56/7",
    # stsw001.s008.l201.ash6 — 16 ports
    "eth1/59/1",
    "eth1/59/3",
    "eth1/59/5",
    "eth1/59/7",
    "eth1/60/1",
    "eth1/60/3",
    "eth1/60/5",
    "eth1/60/7",
    "eth1/63/1",
    "eth1/63/3",
    "eth1/63/5",
    "eth1/63/7",
    "eth1/64/1",
    "eth1/64/3",
    "eth1/64/5",
    "eth1/64/7",
]
assert len(ICEPACK_GTSW_STSW_FLAP_PORTS) == 128


# ---------------------------------------------------------------------------
# TestConfig instantiations
#
# All NPI THFT TestConfigs are constructed below from the centralized
# `create_npi_thrift_hardening_test_config` factory. Adding a new NPI device
# under THFT coverage = add one factory call here + re-export from this
# package's `__init__.py`.
# ---------------------------------------------------------------------------

# NPI_DVT_ICEPACK_GTSW__THRIFT_HARDENING_TEST_CONFIG — IcePack GTSW
# (`gtsw001.l1001.c085.ash6.tfbnw.net`; TH6 ASIC; netwhoami
# `hw=ICECUBE800BC=70`, `chmodel=CHMODEL_ICEPACK_BCMTH6_GENERIC=3050`).
# Mirrors the BGP scaffolding params from
# `NPI_DVT_ICEPACK_GTSW__CPU_QUEUE_TEST_CONFIG` (which has been validated on
# the same DUT). Flap target = 128 STSW-adjacent uplinks (NOT the IXIA-facing
# `eth1/13/1`/`eth1/13/3` carrying BGP peers).
NPI_DVT_ICEPACK_GTSW__THRIFT_HARDENING_TEST_CONFIG = create_npi_thrift_hardening_test_config(
    test_config_name="NPI_DVT_ICEPACK_GTSW__THRIFT_HARDENING_TEST_CONFIG",
    device_name="gtsw001.l1001.c085.ash6",
    local_mac_address="02:00:00:00:0f:0c",
    ixia_downlink_interface="eth1/13/1",
    ixia_uplink_interface="eth1/13/3",
    peergroup_uplink_mimic_v6="PEERGROUP_GTSW_STSW_V6",
    peergroup_uplink_mimic_v4="PEERGROUP_GTSW_STSW_V4",
    peergroup_downlink_mimic_v6="PEERGROUP_GTSW_STSW_V6",
    peergroup_downlink_mimic_v4="PEERGROUP_GTSW_HOST_MIMIC_V4",
    route_map_uplink_ingress="PROPAGATE_GTSW_STSW_IN",
    route_map_uplink_egress="PROPAGATE_GTSW_STSW_OUT",
    route_map_downlink_ingress="PROPAGATE_GTSW_STSW_IN",
    route_map_downlink_egress="PROPAGATE_GTSW_STSW_OUT",
    ixia_downlink_ic_parent_network_v6="2401:db00:1ff:c108",
    ixia_uplink_ic_parent_network_v6="2401:db00:1ff:c109",
    ixia_downlink_ic_parent_network_v4="10.127.240",
    ixia_uplink_ic_parent_network_v4="10.127.241",
    unique_prefix_limit="5000",
    per_peer_max_route_limit="20000",
    downlink_peer_count=8,
    uplink_peer_count=8,
    remote_uplink_as_4byte=65272,
    remote_downlink_as_4byte=7001,
    remote_as_4_byte_step=1,
    is_uplink_peer_confed="False",
    is_downlink_peer_confed="False",
    ixia_downlink_prefix_count_v6=500,
    ixia_uplink_prefix_count_v6=500,
    ixia_downlink_prefix_count_v4=500,
    ixia_uplink_prefix_count_v4=500,
    ixia_downlink_communities=["65446:30", "65441:323", "65456:323"],
    ixia_uplink_communities=["65446:30", "65441:323", "65456:323"],
    downlink_peer_tag="HOST",
    uplink_peer_tag="STSW",
    stsw_flap_ports=ICEPACK_GTSW_STSW_FLAP_PORTS,
    test_duration_s=14400,  # THFT_001 = 4 hr prod (override to 600 = 10 min for smoke)
    restart_test_duration_s=3600,  # THFT_002..005 = 1 hr each → 4hr total
    # Scaled back to Pavan's original 10000 per API (= 70K concurrent calls
    # per burst across the 7 read-only APIs) after D108220182 enabled
    # server-side thrift API rate limiting on ICECUBE800BC. With
    # `thriftApiToRateLimitInQps` populated (~140 APIs at 2-8 qps each), the
    # agent throttles excess calls and CPU stays bounded even at the
    # original 70K burst scale. The new `assert_thrift_rate_limit_enabled`
    # setup-task (see setup_tasks above) fails fast if rate limiting is OFF,
    # so we won't accidentally hammer an unprotected agent at 70K again.
    # Prior history (pre-D108220182): 70K crashed `fboss_sw_agent` at
    # CPU 1339% in ~2.5 min and ticked `coop.unclean_exits` twice
    # (T275336067 — kernel OOM via workload.slice swap exhaustion).
    requests_per_burst=10000,
    basset_pool="dne.test",
    # IcePack backend GTSW does not run openr — drop from postcheck list
    # to avoid false-fail on INACTIVE (same rationale as cpu_queue config).
    service_restart_services=[
        "bgpd",
        "fboss_hw_agent@0",
        "fboss_sw_agent",
        "fsdb",
        "qsfp_service",
        "wedge_agent",
    ],
)
