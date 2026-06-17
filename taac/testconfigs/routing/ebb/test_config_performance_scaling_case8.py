# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""Arista BGP++ performance scaling test case 8: separable policy.

Builds a TestConfig that exercises Arista BGP++ inbound policy evaluation
performance with both a separable policy (EB-FA-IN with prefix matching)
and a default ACCEPT_ALL policy across increasing prefix counts (10K-50K).
Used to compare per-policy CPU/memory overhead at scale.
"""

from taac.constants import Gigabyte
from taac.health_checks.healthcheck_definitions import (
    create_bgp_session_establish_check,
    create_bgp_session_snapshot_check,
    create_core_dumps_snapshot_check,
)
from taac.playbooks.playbook_definitions import (
    build_case8_playbook,
)
from taac.routing.ebb.arista_bgp_plus_plus_performance_scaling_tests.ixia_configs_for_tests import (
    create_ebb_performance_scale_basic_port_configs,
)
from taac.routing.ebb.ebb_bgp_plus_plus_test_config.common_periodic_tasks import (
    create_standard_periodic_tasks,
)
from taac.stages.stage_definitions import create_steps_stage
from taac.steps.step_definitions import (
    create_sc_8_setup_steps,
    create_sc_8_steps,
)
from taac.task_definitions import (
    create_configure_bgpcpp_startup_task,
    create_replace_bgp_peers_task,
)
from taac.test_as_a_config.types import Endpoint, TestConfig


def test_config_for_bgp_plus_plus_on_ebb_arista_separable_policy(
    test_config_name: str,
    device_name: str,
    ixia_interface_mimic_ebgp: str,
    ebgp_peer_count_v6: int,
    ebgp_peer_count_v4: int,
    ebgp_remote_as: int,
    ixia_ebgp_ic_parent_network_v6: str,
    ixia_ebgp_ic_parent_network_v4: str,
    prefix_count: int,
    direct_ixia_connections: list,
    log_collection_timeout=None,
    oss_mock_device_data=None,
    host_os_type_map=None,
    host_driver_args=None,
    # Dynamic peer configuration (optional)
    ssh_user: str | None = None,
    ssh_password: str | None = None,
    peergroup_ebgp_v6: str = "EB-FA-V6",
    peergroup_ebgp_v4: str = "EB-FA-V4",
):
    """Build the case-8 (separable policy) BGP++ TestConfig.

    Configures EBGP-only peering on a single IXIA port (no IBGP), then
    runs two playbooks back-to-back via `build_case8_playbook`: one with
    a separable inbound policy (EB-FA-IN prefix matching) and one with
    a wide-open ACCEPT_ALL policy. Each playbook sweeps prefix counts
    of 10K, 20K, 30K, 40K, 50K and plots policy-evaluation stats at the
    final iteration to compare per-policy CPU/memory cost.

    Args:
        test_config_name: Final name of the produced TestConfig.
        device_name: DUT hostname (Arista EBB).
        ixia_interface_mimic_ebgp: IXIA port name used as the EBGP endpoint.
        ebgp_peer_count_v6 / ebgp_peer_count_v4: Per-AFI EBGP peer counts.
        ebgp_remote_as: EBGP remote ASN.
        ixia_ebgp_ic_parent_network_v6 / ixia_ebgp_ic_parent_network_v4:
            Parent networks for IXIA-side prefix generation.
        prefix_count: Prefix count knob (currently swept internally; see
            inline `create_sc_8_steps` calls).
        direct_ixia_connections: Optional direct IXIA-port connection list.
        log_collection_timeout / oss_mock_device_data / host_os_type_map /
        host_driver_args: Optional overrides for OSS harness wiring.
        ssh_user / ssh_password: When both supplied, use dynamic bgpcpp peer
            replacement; otherwise rely on pre-existing config.
        peergroup_ebgp_v6 / peergroup_ebgp_v4: EBGP peer-group names.

    Returns:
        TestConfig: The case-8 separable-policy TestConfig (consumed via
        `testconfigs.routing.ebb`).
    """
    # Build setup_tasks based on whether dynamic peer config is provided
    if ssh_user is not None and ssh_password is not None:
        setup_tasks = [
            create_configure_bgpcpp_startup_task(
                hostname=device_name,
                flags={
                    "agent_thrift_recv_timeout_ms": "160000",
                },
                ssh_user=ssh_user,
                ssh_password=ssh_password,
            ),
            create_replace_bgp_peers_task(
                hostname=device_name,
                peer_configs=[
                    {
                        "peer_group_name": peergroup_ebgp_v6,
                        "remote_as": ebgp_remote_as,
                        "base_network": ixia_ebgp_ic_parent_network_v6,
                        "is_v6": True,
                        "peer_count": ebgp_peer_count_v6,
                        "start_offset": 16,
                    },
                    {
                        "peer_group_name": peergroup_ebgp_v4,
                        "remote_as": ebgp_remote_as,
                        "base_network": ixia_ebgp_ic_parent_network_v4,
                        "is_v6": False,
                        "peer_count": ebgp_peer_count_v4,
                        "start_offset": 16,
                    },
                ],
            ),
        ]
    else:
        setup_tasks = []

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
                direct_ixia_connections=direct_ixia_connections
                if direct_ixia_connections
                else [],
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
        basic_port_configs=create_ebb_performance_scale_basic_port_configs(
            device_name=device_name,
            ixia_interface_mimic_ebgp=ixia_interface_mimic_ebgp,
            ixia_interface_mimic_ibgp="",
            ebgp_peer_count_v6=ebgp_peer_count_v6,
            ebgp_peer_count_v4=ebgp_peer_count_v4,
            ibgp_peer_count_v6=0,
            ibgp_peer_count_v4=0,
            ebgp_remote_as=ebgp_remote_as,
            ibgp_remote_as=0,
            ixia_ebgp_ic_parent_network_v6=ixia_ebgp_ic_parent_network_v6,
            ixia_ebgp_ic_parent_network_v4=ixia_ebgp_ic_parent_network_v4,
            ixia_ibgp_ic_parent_network_v6="",
            ixia_ibgp_ic_parent_network_v4="",
            same_community=True,
        ),
        playbooks=[
            build_case8_playbook(
                name="bgp_plus_plus_arista_separable_policy_eb_fa_in_test",
                description="Test BGP++ performance with separable policy",
                snapshot_checks=[
                    create_core_dumps_snapshot_check(),
                    create_bgp_session_snapshot_check(
                        skip_flap_check=True, skip_uptime_check=True
                    ),
                ],
                periodic_tasks=create_standard_periodic_tasks(
                    device_name=device_name,
                    memory_threshold=Gigabyte.GIG_5.value,
                    cpu_util_terminate_on_error=False,
                    memory_terminate_on_error=False,
                ),
                postchecks=[
                    create_bgp_session_establish_check(),
                ],
                setup_steps=create_sc_8_setup_steps(
                    device_name=device_name,
                    configerator_path="taac/arista_performance_scaling_test_bgpcpp_configs/bgpcpp_config_test_case8_eb_fa_in_no_prefix",
                ),
                stages=[
                    create_steps_stage(
                        steps=create_sc_8_steps(
                            device_name=device_name,
                            prefix_count=10000,
                            plot_policy_stats=False,
                        )
                        + create_sc_8_steps(
                            device_name=device_name,
                            prefix_count=20000,
                            plot_policy_stats=False,
                        )
                        + create_sc_8_steps(
                            device_name=device_name,
                            prefix_count=30000,
                            plot_policy_stats=False,
                        )
                        + create_sc_8_steps(
                            device_name=device_name,
                            prefix_count=40000,
                            plot_policy_stats=False,
                        )
                        + create_sc_8_steps(
                            device_name=device_name,
                            prefix_count=50000,
                            plot_policy_stats=True,
                        )
                    )
                ],
            ),
            build_case8_playbook(
                name="bgp_plus_plus_arista_default_policy_test",
                description="Test BGP++ performance with default policy",
                snapshot_checks=[
                    create_core_dumps_snapshot_check(),
                    create_bgp_session_snapshot_check(
                        skip_flap_check=True, skip_uptime_check=True
                    ),
                ],
                periodic_tasks=create_standard_periodic_tasks(
                    device_name=device_name,
                    memory_threshold=Gigabyte.GIG_5.value,
                    cpu_util_terminate_on_error=False,
                    memory_terminate_on_error=False,
                ),
                postchecks=[
                    create_bgp_session_establish_check(),
                ],
                setup_steps=create_sc_8_setup_steps(
                    device_name=device_name,
                    configerator_path="taac/arista_performance_scaling_test_bgpcpp_configs/bgpcpp_config_test_case8_accept_all",
                ),
                stages=[
                    create_steps_stage(
                        steps=create_sc_8_steps(
                            device_name=device_name,
                            prefix_count=10000,
                            policy_name="ACCEPT_ALL",
                            plot_policy_stats=False,
                        )
                        + create_sc_8_steps(
                            device_name=device_name,
                            prefix_count=20000,
                            policy_name="ACCEPT_ALL",
                            plot_policy_stats=False,
                        )
                        + create_sc_8_steps(
                            device_name=device_name,
                            prefix_count=30000,
                            policy_name="ACCEPT_ALL",
                            plot_policy_stats=False,
                        )
                        + create_sc_8_steps(
                            device_name=device_name,
                            prefix_count=40000,
                            policy_name="ACCEPT_ALL",
                            plot_policy_stats=False,
                        )
                        + create_sc_8_steps(
                            device_name=device_name,
                            prefix_count=50000,
                            policy_name="ACCEPT_ALL",
                            plot_policy_stats=True,
                        )
                    )
                ],
            ),
        ],
    )
