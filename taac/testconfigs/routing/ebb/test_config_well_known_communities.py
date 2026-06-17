# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

"""
RFC 1997 Well-Known Community Egress Filtering Test for EOS BGP++

RFC 1997 Behavior Matrix (on EBB, non-confederation):
    NO_EXPORT (65535:65281)         -> suppressed to EBGP peers only
    NO_ADVERTISE (65535:65282)      -> suppressed to ALL peers
    NO_EXPORT_SUBCONFED (65535:65283) -> suppressed to EBGP peers only

Test Design:
    - 5 eBGP peers + 5 iBGP peers, sessions always up
    - All prefix pools disabled at setup
    - Per stage: enable one community's prefix pools → wait → verify → disable
    - 1 playbook with 4 stages (one per community)
    - Separate playbook for flag-off regression (needs daemon restart)
"""

from collections.abc import Mapping, Sequence

from taac.health_checks.healthcheck_definitions import (
    create_bgp_rib_fib_consistency_check,
    create_core_dumps_snapshot_check,
)
from taac.playbooks.playbook_definitions import (
    build_bgp_well_known_community_playbook,
)
from taac.routing.ebb.arista_feature_testing.ixia_configs_for_well_known_community_test import (
    create_well_known_community_test_basic_port_configs,
)
from taac.stages.stage_definitions import create_steps_stage
from taac.steps.step_definitions import (
    create_advertise_withdraw_prefixes_step,
    create_custom_step,
    create_ixia_device_group_toggle_step,
    create_longevity_step,
    create_run_task_step,
)
from taac.task_definitions import (
    create_invoke_ixia_api_task,
    create_ixia_enable_disable_bgp_prefixes_task,
    create_replace_bgp_peers_task,
    create_restore_bgp_peers_task,
)
from taac.test_as_a_config.types import (
    DeviceOsType,
    DirectIxiaConnection,
    Endpoint,
    Task,
    TestConfig,
)


def test_config_for_well_known_communities(
    test_config_name: str,
    device_name: str,
    ixia_interface_ebgp: str,
    ebgp_remote_as: int,
    ixia_ebgp_ic_parent_network_v6: str,
    ixia_ebgp_ic_parent_network_v4: str,
    ixia_interface_ibgp: str,
    ibgp_local_as: int,
    ixia_ibgp_ic_parent_network_v6: str,
    ixia_ibgp_ic_parent_network_v4: str,
    ssh_user: str = "admin",
    ssh_password: str = "",
    ebgp_peer_count: int = 5,
    ibgp_peer_count: int = 5,
    prefix_count: int = 100,
    ebgp_route_acceptance_communities: list[str] | None = None,
    test_address_families: list[str] | None = None,
    convergence_wait_seconds: int = 60,
    direct_ixia_connections: Sequence[DirectIxiaConnection] | None = None,
    log_collection_timeout: int | None = None,
    setup_tasks: list[Task] | None = None,
    # pyre-fixme[24]: Generic type `dict` expects 2 type parameters, use
    #  `typing.Dict[<key type>, <value type>]` to avoid runtime subscripting errors.
    oss_mock_device_data: dict | None = None,
    host_os_type_map: Mapping[str, DeviceOsType] | None = None,
    host_driver_args: dict[str, str] | None = None,
) -> TestConfig:
    """
    Create a test config for RFC 1997 well-known community filtering.

    5 eBGP + 5 iBGP peers, sessions always up. Per stage: enable one
    community's prefix pools, wait for convergence, verify, then disable.
    """
    if test_address_families is None:
        test_address_families = ["ipv6"]
    if ebgp_route_acceptance_communities is None:
        ebgp_route_acceptance_communities = ["65529:39744"]

    num_afs = len(test_address_families)
    _total_peers = (ebgp_peer_count + ibgp_peer_count) * num_afs  # noqa: F841

    peer_groups = []
    if "ipv6" in test_address_families:
        peer_groups.extend(
            [
                {
                    "peer_group_name": "EB-FA-V6",
                    "remote_as": ebgp_remote_as,
                    "base_network": ixia_ebgp_ic_parent_network_v6,
                    "is_v6": True,
                    "peer_count": ebgp_peer_count,
                    "description_prefix": "eBGP V6 Peer",
                },
                {
                    "peer_group_name": "EB-EB-V6",
                    "remote_as": ibgp_local_as,
                    "base_network": ixia_ibgp_ic_parent_network_v6,
                    "is_v6": True,
                    "peer_count": ibgp_peer_count,
                    "description_prefix": "iBGP V6 Peer",
                },
            ]
        )
    if "ipv4" in test_address_families:
        peer_groups.extend(
            [
                {
                    "peer_group_name": "EB-FA-V4",
                    "remote_as": ebgp_remote_as,
                    "base_network": ixia_ebgp_ic_parent_network_v4,
                    "is_v6": False,
                    "peer_count": ebgp_peer_count,
                    "description_prefix": "eBGP V4 Peer",
                },
                {
                    "peer_group_name": "EB-EB-V4",
                    "remote_as": ibgp_local_as,
                    "base_network": ixia_ibgp_ic_parent_network_v4,
                    "is_v6": False,
                    "peer_count": ibgp_peer_count,
                    "description_prefix": "iBGP V4 Peer",
                },
            ]
        )

    # Setup: replace peers + disable ALL prefix pools
    all_setup_tasks: list[Task] = list(setup_tasks or [])
    all_setup_tasks.extend(
        [
            create_replace_bgp_peers_task(
                hostname=device_name,
                peer_configs=peer_groups,
                ssh_user=ssh_user,
                ssh_password=ssh_password,
            ),
            create_ixia_enable_disable_bgp_prefixes_task(
                enable=False,
                prefix_pool_regex="PREFIX_POOL_.*",
                prefix_start_index=0,
            ),
        ]
    )

    # ======================================================================
    # Playbook 1: Per-stage community verification
    # ======================================================================
    # Sessions stay up throughout. Each stage:
    #   1. Enable this community's prefix pools (eBGP + iBGP)
    #   2. Wait for routes to converge
    #   3. Verify filtering via custom step
    #   4. Disable this community's prefix pools (clean slate)

    # (community_name, ebgp_prefix_regex, ibgp_prefix_regex,
    #  suppress_to_ebgp, suppress_to_ibgp)
    community_checks = [
        (
            "NO_EXPORT",
            "PREFIX_POOL_.*EBGP_NO_EXPORT$",
            "PREFIX_POOL_.*IBGP_NO_EXPORT$",
            True,
            False,
        ),
        (
            "NO_ADVERTISE",
            "PREFIX_POOL_.*EBGP_NO_ADVERTISE$",
            "PREFIX_POOL_.*IBGP_NO_ADVERTISE$",
            True,
            True,
        ),
        (
            "NO_EXPORT_SUBCONFED",
            "PREFIX_POOL_.*EBGP_NO_EXPORT_SUBCONFED$",
            "PREFIX_POOL_.*IBGP_NO_EXPORT_SUBCONFED$",
            True,
            False,
        ),
        (
            "BASELINE",
            "PREFIX_POOL_.*EBGP_BASELINE$",
            "PREFIX_POOL_.*IBGP_BASELINE$",
            False,
            False,
        ),
    ]

    verification_stages = []
    for stage_idx, (
        community_name,
        ebgp_regex,
        ibgp_regex,
        suppress_ebgp,
        suppress_ibgp,
    ) in enumerate(community_checks, start=1):
        verification_stages.append(
            create_steps_stage(
                iteration=stage_idx,
                steps=[
                    # 1. Enable this community's prefix pools
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=True,
                        prefix_pool_regex=ebgp_regex,
                        prefix_start_index=0,
                        description=f"Enable eBGP {community_name} prefixes",
                    ),
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=True,
                        prefix_pool_regex=ibgp_regex,
                        prefix_start_index=0,
                        description=f"Enable iBGP {community_name} prefixes",
                    ),
                    # 2. Wait for convergence
                    create_longevity_step(
                        duration=convergence_wait_seconds,
                        description=f"Wait {convergence_wait_seconds}s for {community_name} convergence",
                    ),
                    # 3. Verify filtering
                    create_custom_step(
                        params_dict={
                            "custom_step_name": "verify_well_known_community_filtering",
                            "hostname": device_name,
                            "community_name": community_name,
                            "expect_suppressed_to_ebgp": suppress_ebgp,
                            "expect_suppressed_to_ibgp": suppress_ibgp,
                        },
                        description=f"Verify {community_name} filtering",
                    ),
                    # 4. Disable this community's prefix pools
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=False,
                        prefix_pool_regex=ebgp_regex,
                        prefix_start_index=0,
                        description=f"Disable eBGP {community_name} prefixes",
                    ),
                    create_advertise_withdraw_prefixes_step(
                        device_name=device_name,
                        advertise=False,
                        prefix_pool_regex=ibgp_regex,
                        prefix_start_index=0,
                        description=f"Disable iBGP {community_name} prefixes",
                    ),
                ],
            ),
        )

    playbook_community_filter = build_bgp_well_known_community_playbook(
        name="EB03_RFC1997_WELL_KNOWN_COMMUNITY_FILTER",
        setup_steps=[
            create_ixia_device_group_toggle_step(
                enable=True,
                device_group_name_regex=".*",
                description="Enable all device groups",
            ),
            create_longevity_step(
                duration=30,
                description="Wait for BGP sessions to establish",
            ),
        ],
        periodic_tasks=[],
        prechecks=[],
        snapshot_checks=[
            create_core_dumps_snapshot_check(),
        ],
        postchecks=[
            create_bgp_rib_fib_consistency_check(),
        ],
        stages=verification_stages,
    )

    # ======================================================================
    # Playbook 2: Feature Flag Off Regression
    # ======================================================================
    _playbook_flag_off_regression = build_bgp_well_known_community_playbook(  # noqa: F841
        name="EB03_RFC1997_FLAG_OFF_REGRESSION",
        setup_steps=[
            create_run_task_step(
                task_name="set_bgp_setting_config",
                params_dict={
                    "hostname": device_name,
                    "settings": {"enable_well_known_community_filter": False},
                    "ssh_user": ssh_user,
                    "ssh_password": ssh_password,
                    "reload_bgp": True,
                },
                description="Disable well-known community filter (flag off)",
            ),
            create_longevity_step(duration=30, description="Wait for BGP restart"),
            create_ixia_device_group_toggle_step(
                enable=True,
                device_group_name_regex=".*",
                description="Enable all device groups",
            ),
            create_advertise_withdraw_prefixes_step(
                device_name=device_name,
                advertise=True,
                prefix_pool_regex="PREFIX_POOL_.*NO_ADVERTISE$",
                prefix_start_index=0,
                description="Enable NO_ADVERTISE prefixes (filter disabled)",
            ),
        ],
        periodic_tasks=[],
        prechecks=[],
        snapshot_checks=[create_core_dumps_snapshot_check()],
        postchecks=[create_bgp_rib_fib_consistency_check()],
        stages=[
            create_steps_stage(
                iteration=1,
                steps=[
                    create_longevity_step(
                        duration=convergence_wait_seconds,
                        description=f"Wait {convergence_wait_seconds}s for convergence",
                    ),
                    create_custom_step(
                        params_dict={
                            "custom_step_name": "verify_well_known_community_filtering",
                            "hostname": device_name,
                            "community_name": "NO_ADVERTISE",
                            "expect_suppressed_to_ebgp": False,
                            "expect_suppressed_to_ibgp": False,
                        },
                        description="Verify NO_ADVERTISE NOT suppressed (flag off)",
                    ),
                    create_run_task_step(
                        task_name="set_bgp_setting_config",
                        params_dict={
                            "hostname": device_name,
                            "settings": {"enable_well_known_community_filter": True},
                            "ssh_user": ssh_user,
                            "ssh_password": ssh_password,
                            "reload_bgp": True,
                        },
                        description="Re-enable well-known community filter",
                    ),
                ],
            ),
        ],
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
                ixia_ports=[ixia_interface_ebgp, ixia_interface_ibgp],
                direct_ixia_connections=direct_ixia_connections or [],
            ),
        ],
        host_driver_args=host_driver_args,
        oss_mock_device_data=oss_mock_device_data,
        host_os_type_map=host_os_type_map,
        startup_checks=[],
        setup_tasks=all_setup_tasks,
        teardown_tasks=[
            create_invoke_ixia_api_task(
                api_name="toggle_device_groups",
                args_dict={"enable": False, "device_group_name_regex": ".*"},
            ),
            create_restore_bgp_peers_task(
                hostname=device_name,
                ssh_user=ssh_user,
                ssh_password=ssh_password,
            ),
        ],
        basic_port_configs=create_well_known_community_test_basic_port_configs(
            device_name=device_name,
            ixia_interface_ebgp=ixia_interface_ebgp,
            ebgp_peer_count=ebgp_peer_count,
            ebgp_remote_as=ebgp_remote_as,
            ixia_ebgp_ic_parent_network_v6=ixia_ebgp_ic_parent_network_v6,
            ixia_ebgp_ic_parent_network_v4=ixia_ebgp_ic_parent_network_v4,
            ixia_interface_ibgp=ixia_interface_ibgp,
            ibgp_peer_count=ibgp_peer_count,
            ibgp_local_as=ibgp_local_as,
            ixia_ibgp_ic_parent_network_v6=ixia_ibgp_ic_parent_network_v6,
            ixia_ibgp_ic_parent_network_v4=ixia_ibgp_ic_parent_network_v4,
            prefix_count=prefix_count,
            ebgp_route_acceptance_communities=ebgp_route_acceptance_communities,
            test_address_families=test_address_families,
        ),
        playbooks=[
            playbook_community_filter,
        ],
    )
