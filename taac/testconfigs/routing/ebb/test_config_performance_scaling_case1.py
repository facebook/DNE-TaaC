# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""Simplified BGP++ EBB egress-peer sweep test config.

Builds ONE TestConfig containing ONE Playbook with N+1 Stages:

  - N measurement Stages, one per entry in ``egress_peer_counts``. Each
    stage stops any prior IBGP sessions on both AFs, starts ``n`` v6 + ``n``
    v4 IBGP sessions via IXIA, then runs the convergence step (which
    enables 50K v6 + 50K v4 EBGP prefixes, restarts ``bgpcpp``, and
    measures initial convergence time).
  - 1 final aggregator Stage that consolidates the per-Stage convergence
    measurements into ONE plot of convergence-time vs total-peer-count
    (everpaste link in step output).

The test is pure-IXIA at runtime — no device-side ``bgpcpp_config``
patching. Stage X-axis labels use ``total_peer_count = 2 * n`` because v6
and v4 IBGP peers run simultaneously (200 / 400 / 600 / 800 / 1000 for
the default sweep).
"""

from typing import Optional

from taac.playbooks.playbook_definitions import (
    create_performance_scaling_egress_peer_sweep_playbook,
    PerIterationSetupStepsFactory,
)
from taac.routing.ebb.arista_bgp_plus_plus_performance_scaling_tests.ixia_configs_for_tests import (
    create_ebb_performance_scale_basic_port_configs,
)
from taac.test_as_a_config.types import Endpoint, TestConfig


def test_config_for_bgp_plus_plus_on_ebb_arista_performance_scaling(
    test_config_name: str,
    device_name: str,
    host_driver_args,
    oss_mock_device_data,
    host_os_type_map,
    ixia_interface_mimic_ebgp: str,
    ixia_interface_mimic_ibgp: str,
    direct_ixia_connections: list,
    egress_peer_counts=None,
    prefix_count: int = 50000,
    ebgp_peer_count: int = 1,
    ebgp_remote_as: int = 65334,
    ibgp_remote_as: int = 64981,
    ixia_ebgp_ic_parent_network_v6: str = "2401:db00:e50d:11:8",
    ixia_ebgp_ic_parent_network_v4: str = "10.163.28",
    ixia_ibgp_ic_parent_network_v6: str = "2401:db00:e50d:11:9",
    ixia_ibgp_ic_parent_network_v4: str = "10.164.28",
    log_collection_timeout=None,
    setup_tasks: Optional[list] = None,
    teardown_tasks: Optional[list] = None,
    per_iteration_setup_steps_factory: Optional[PerIterationSetupStepsFactory] = None,
):
    """BGP++ EBB egress-peer sweep TestConfig.

    For each entry ``n`` in ``egress_peer_counts`` (default
    ``[100, 200, 300, 400, 500]``):
      1. Stop any prior IBGP v6 + v4 sessions on IXIA.
      2. Start ``n`` v6 + ``n`` v4 IBGP sessions on IXIA.
      3. Run the convergence step which enables ``prefix_count`` v6 +
         ``prefix_count`` v4 EBGP prefixes, restarts ``bgpcpp``, and
         measures the initial convergence time.

    A final aggregator Stage produces ONE consolidated plot of
    convergence-time vs total-peer-count (and uploads it to everpaste).
    """
    if egress_peer_counts is None:
        egress_peer_counts = [100, 200, 300, 400, 500]
    max_n = max(egress_peer_counts)

    return TestConfig(
        name=test_config_name,
        skip_ixia_protocol_verification=True,
        log_collection_timeout=log_collection_timeout,
        basset_pool="dne.test",
        endpoints=[
            Endpoint(
                name=device_name,
                dut=True,
                ixia_ports=[
                    ixia_interface_mimic_ebgp,
                    ixia_interface_mimic_ibgp,
                ],
                direct_ixia_connections=direct_ixia_connections or [],
            ),
        ],
        host_driver_args=host_driver_args,
        oss_mock_device_data=oss_mock_device_data,
        host_os_type_map=host_os_type_map,
        startup_checks=[],
        # Default: pure-IXIA test, no device-side reconfig in setup. Caller
        # may supply conveyor setup_tasks (e.g. bag012 BGP++ deployment).
        setup_tasks=setup_tasks if setup_tasks is not None else [],
        teardown_tasks=teardown_tasks if teardown_tasks is not None else [],
        # Pre-size IXIA for the maximum requested egress scale on both AFs.
        # Each Stage activates its own subset at runtime.
        basic_port_configs=create_ebb_performance_scale_basic_port_configs(
            device_name=device_name,
            ixia_interface_mimic_ebgp=ixia_interface_mimic_ebgp,
            ixia_interface_mimic_ibgp=ixia_interface_mimic_ibgp,
            ebgp_peer_count_v6=ebgp_peer_count,
            ebgp_peer_count_v4=ebgp_peer_count,
            ibgp_peer_count_v6=max_n,
            ibgp_peer_count_v4=max_n,
            ebgp_remote_as=ebgp_remote_as,
            ibgp_remote_as=ibgp_remote_as,
            ixia_ebgp_ic_parent_network_v6=ixia_ebgp_ic_parent_network_v6,
            ixia_ebgp_ic_parent_network_v4=ixia_ebgp_ic_parent_network_v4,
            ixia_ibgp_ic_parent_network_v6=ixia_ibgp_ic_parent_network_v6,
            ixia_ibgp_ic_parent_network_v4=ixia_ibgp_ic_parent_network_v4,
        ),
        playbooks=[
            create_performance_scaling_egress_peer_sweep_playbook(
                device_name=device_name,
                egress_peer_counts=egress_peer_counts,
                prefix_count=prefix_count,
                ebgp_peer_count=ebgp_peer_count,
                per_iteration_setup_steps_factory=per_iteration_setup_steps_factory,
            ),
        ],
    )
