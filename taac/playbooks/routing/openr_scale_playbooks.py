# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""Open/R scale playbook factories (one factory = one test case).

Naming: ``Playbook.name = openr_scale_<case>_playbook`` and each public factory
is exactly ``get_{playbook_name}``. See README.md for the routing suite
contract.
"""

import typing as t

from taac.health_checks.healthcheck_definitions import (
    create_core_dumps_snapshot_check,
    create_openr_spark_neighbor_check,
    create_port_channel_expected_state_check,
)
from taac.stages.stage_definitions import create_steps_stage
from taac.steps.step_definitions import (
    create_interface_flap_step,
    create_longevity_step,
    create_openr_scale_cold_boot_step,
    create_openr_scale_injection_step,
    create_openr_scale_kvstore_state_cleanup_step,
    create_openr_scale_kvstore_state_step,
    create_openr_scale_performance_cleanup_step,
    create_openr_scale_performance_step,
    create_system_reboot_step,
    create_validation_step,
)
from taac.task_definitions import (
    create_openr_scale_cold_boot_monitor_task,
)
from openr.tests.scale.scripts.scale_key_names import (
    bbf_simple_node_names,
    expected_key_set,
)
from taac.health_check.health_check import types as hc_types
from taac.test_as_a_config import types as taac_types
from taac.test_as_a_config.types import Playbook


__all__ = [
    "get_openr_scale_dut_cold_boot_playbook",
    "get_openr_scale_ipv4_ipv6_prefix_injection_playbook",
    "get_openr_scale_kvstore_injection_playbook",
    "get_openr_scale_kvstore_merge_playbook",
    "get_openr_scale_physical_link_flap_playbook",
]


def get_openr_scale_kvstore_injection_playbook(
    helper_name: str,
    dut_name: str,
    dut_inband_address: str,
    num_spines: int,
    num_leaves: int,
    num_control_nodes: int,
    num_sites: int,
    ecmp_width: int,
    prefixes_per_node: int,
    dut_role: t.Literal["leaf", "spine"],
    area: str,
    prefix_seed: int,
    dut_mgmt_addresses: t.Optional[t.List[str]] = None,
    dut_port: int = 2018,
    scale_tester_remote_path: str = "/mnt/flash/scale_test_server",
    injection_run_duration_sec: t.Optional[int] = None,
    injection_timeout_sec: int = 240,
) -> Playbook:
    """
    Build the Open/R scale KvStore injection and semantic-state test.

    See ``fbcode/neteng/test_infra/routing_qualification/catalogs/taac/openr_scale_catalog.yaml``
    for the test contract and triage guidance.

    Sequence:
    1. Performance baseline: load the required Configerator thresholds, capture
       pre-operation CPU/RSS, and reset the KvStore convergence maximum.
    2. Trigger: run ``scale_test_server`` on the helper, injecting a synthetic
       ``num_spines``/``num_leaves`` fabric into the DUT's KvStore over the
       DUT's inband address.
    3. Delivery acknowledgement: the injection step samples
       ``kvstore.received_key_vals`` on the DUT immediately before and after the
       injector runs, and fails unless the increase is exactly the number of
       key-values the fabric should have sent.
    4. Performance validation: wait for a fresh Open/R counter publication and
       enforce CPU, RSS, and convergence thresholds.
    5. Semantic validation: the final ordered step derives every expected key
       and Value independently from the fixed seed and topology, reads only
       those keys, and compares the outer Value and decoded payload fields.

    The two barriers answer different questions. The counter proves this run
    delivered the expected number of key-values; it cannot identify them. The
    semantic barrier proves every expected resident key and payload is correct;
    it deliberately tolerates surplus synthetic and operational keys already on
    this real lab DUT, so resident state alone cannot attribute delivery to this
    run.

    There is no Open/R liveness precheck or postcheck. On EOS Open/R is a
    configured daemon, not a systemd unit, so ``SYSTEMCTL_ACTIVE_STATE_CHECK``
    (``OPERATING_SYSTEMS = ["FBOSS"]``) never runs here and would have recorded a
    pass for a check that cannot fire. Liveness is carried by the assertion
    itself: the counters are read over Open/R Thrift, so a daemon that died
    under the load fails the step.

    60-second mean CPU, RSS, and convergence are gated by the runtime Configerator policy. There
    is no core-dump snapshot, because a crash that matters here already breaks
    the measurement: a restarted KvStore full-syncs from its peer, which lands
    in the same receive counter and fails the exact-equality assertion.

    Args:
        helper_name: device running the injector. The binary is expected to be
            pre-staged there; this test does not build, copy or remove it.
        dut_name: device running real Open/R, whose KvStore is measured.
        dut_inband_address: address the injector connects to.
        dut_mgmt_addresses: mgmt addresses that must never be used for
            injection. The mgmt path is control-plane policed and resets the
            large ``adj:`` requests mid-flight; listing them here turns that
            mistake into an explicit precondition failure.
        num_spines / num_leaves: fabric size.
        num_control_nodes: BBF control-node count, passed to the injector as
            ``num_super_spines``.
        num_sites: number of BBF sites.
        ecmp_width: adjacency width expected in decoded payloads.
        prefixes_per_node: prefixes each synthetic node advertises.
        dut_role: ``leaf`` (neighbors are spines) or ``spine``.
        area: KvStore and payload area to validate.
        prefix_seed: fixed positive seed shared by injection and validation.
        injection_run_duration_sec: how long the injector serves the fabric
            before exiting. The injected keys outlive it.
        injection_timeout_sec: cap on the injector command; must exceed the run
            duration.

    Returns:
        Playbook named ``openr_scale_kvstore_injection_playbook``.
    """
    return Playbook(
        name="openr_scale_kvstore_injection_playbook",
        prechecks=[],
        postchecks=[],
        snapshot_checks=[],
        stages=[
            create_steps_stage(
                stage_id="openr_scale_kvstore_injection",
                description=(
                    f"Inject a {num_spines}-spine/{num_leaves}-leaf Open/R "
                    f"fabric into {dut_name} and validate every expected Value"
                ),
                steps=[
                    create_openr_scale_performance_step(
                        dut_name=dut_name,
                        profile="kvstore_injection",
                        phase="single",
                        state_key="openr_scale_test_2_performance",
                        action="start",
                    ),
                    create_openr_scale_injection_step(
                        helper_name=helper_name,
                        dut_name=dut_name,
                        dut_host=dut_inband_address,
                        forbidden_dut_hosts=dut_mgmt_addresses,
                        num_spines=num_spines,
                        num_leaves=num_leaves,
                        num_prefixes_per_node=prefixes_per_node,
                        num_sites=num_sites,
                        num_super_spines=num_control_nodes,
                        prefix_seed=prefix_seed,
                        extra_flags=[f"--num_pods={ecmp_width}"],
                        dut_role=dut_role,
                        area=area,
                        dut_port=dut_port,
                        remote_path=scale_tester_remote_path,
                        run_duration_sec=injection_run_duration_sec,
                        run_timeout_sec=injection_timeout_sec,
                    ),
                    create_openr_scale_performance_step(
                        dut_name=dut_name,
                        profile="kvstore_injection",
                        phase="single",
                        state_key="openr_scale_test_2_performance",
                        action="validate",
                    ),
                    create_openr_scale_kvstore_state_step(
                        dut_name=dut_name,
                        seeds=[prefix_seed],
                        num_spines=num_spines,
                        num_leaves=num_leaves,
                        num_control_nodes=num_control_nodes,
                        num_sites=num_sites,
                        ecmp_width=ecmp_width,
                        prefixes_per_node=prefixes_per_node,
                        dut_role=dut_role,
                        area=area,
                        checkpoint="single",
                    ),
                ],
            ),
        ],
        cleanup_steps=[
            create_openr_scale_performance_cleanup_step(
                dut_name=dut_name,
                profile="kvstore_injection",
                phase="single",
                state_key="openr_scale_test_2_performance",
            )
        ],
    )


def get_openr_scale_ipv4_ipv6_prefix_injection_playbook(
    helper_name: str,
    dut_name: str,
    dut_inband_address: str,
    num_spines: int,
    num_leaves: int,
    num_control_nodes: int,
    num_sites: int,
    ecmp_width: int,
    prefixes_per_family_per_node: int,
    dut_role: t.Literal["leaf", "spine"],
    area: str,
    prefix_seed: int,
    dut_mgmt_addresses: t.Optional[t.List[str]] = None,
    dut_port: int = 2018,
    scale_tester_remote_path: str = "/mnt/flash/scale_test_server",
    injection_run_duration_sec: int = 5,
    injection_timeout_sec: int = 240,
) -> Playbook:
    """Build the isolated full-scale IPv4/IPv6 prefix-injection case."""
    node_names = bbf_simple_node_names(
        num_spines,
        num_leaves,
        num_control_nodes,
        num_sites,
        dut_role,
    )
    expected_keys = expected_key_set(
        node_names,
        prefix_seed,
        prefixes_per_family_per_node,
        generate_ipv4_prefixes=True,
    )
    performance_state_key = "openr_scale_ipv4_ipv6_prefix_injection_performance"

    return Playbook(
        name="openr_scale_ipv4_ipv6_prefix_injection_playbook",
        prechecks=[],
        postchecks=[],
        snapshot_checks=[],
        stages=[
            create_steps_stage(
                stage_id="openr_scale_ipv4_ipv6_prefix_injection",
                description=(
                    f"Inject equal IPv4/IPv6 prefix populations into {dut_name} "
                    "and validate the exact KvStore state"
                ),
                steps=[
                    create_openr_scale_performance_step(
                        dut_name=dut_name,
                        profile="kvstore_injection",
                        phase="single",
                        state_key=performance_state_key,
                        action="start",
                    ),
                    create_openr_scale_injection_step(
                        helper_name=helper_name,
                        dut_name=dut_name,
                        dut_host=dut_inband_address,
                        forbidden_dut_hosts=dut_mgmt_addresses,
                        num_spines=num_spines,
                        num_leaves=num_leaves,
                        num_prefixes_per_node=prefixes_per_family_per_node,
                        generate_ipv4_prefixes=True,
                        num_sites=num_sites,
                        num_super_spines=num_control_nodes,
                        prefix_seed=prefix_seed,
                        extra_flags=[f"--num_pods={ecmp_width}"],
                        dut_role=dut_role,
                        area=area,
                        dut_port=dut_port,
                        remote_path=scale_tester_remote_path,
                        run_duration_sec=injection_run_duration_sec,
                        run_timeout_sec=injection_timeout_sec,
                        expected_updated_key_vals_delta=len(expected_keys),
                        jq_var_prefix="openr_scale_ipv4_ipv6",
                    ),
                    create_openr_scale_performance_step(
                        dut_name=dut_name,
                        profile="kvstore_injection",
                        phase="single",
                        state_key=performance_state_key,
                        action="validate",
                    ),
                    create_openr_scale_kvstore_state_step(
                        dut_name=dut_name,
                        seeds=[prefix_seed],
                        num_spines=num_spines,
                        num_leaves=num_leaves,
                        num_control_nodes=num_control_nodes,
                        num_sites=num_sites,
                        ecmp_width=ecmp_width,
                        prefixes_per_node=prefixes_per_family_per_node,
                        generate_ipv4_prefixes=True,
                        dut_role=dut_role,
                        area=area,
                        checkpoint="single",
                        exact_scope=True,
                    ),
                ],
            )
        ],
        cleanup_steps=[
            create_openr_scale_performance_cleanup_step(
                dut_name=dut_name,
                profile="kvstore_injection",
                phase="single",
                state_key=performance_state_key,
            )
        ],
    )


def get_openr_scale_kvstore_merge_playbook(
    helper_name: str,
    dut_name: str,
    dut_inband_address: str,
    num_spines: int,
    num_leaves: int,
    num_control_nodes: int,
    num_sites: int,
    ecmp_width: int,
    prefixes_per_node: int,
    seed_a: int,
    seed_b: int,
    area: str,
    state_key: str,
    dut_mgmt_addresses: t.Optional[t.List[str]] = None,
    dut_role: t.Literal["leaf", "spine"] = "leaf",
    dut_port: int = 2018,
    scale_tester_remote_path: str = "/mnt/flash/scale_test_server",
    injection_run_duration_sec: int = 5,
    injection_timeout_sec: int = 120,
) -> Playbook:
    """Build the isolated two-injection KvStore merge lifecycle."""
    node_names_a = bbf_simple_node_names(
        num_spines,
        num_leaves,
        num_control_nodes,
        num_sites,
        dut_role,
    )
    node_names_b = bbf_simple_node_names(
        num_spines,
        num_leaves,
        num_control_nodes,
        num_sites,
        dut_role,
    )
    expected_a = expected_key_set(node_names_a, seed_a, prefixes_per_node)
    expected_b = expected_key_set(node_names_b, seed_b, prefixes_per_node)
    expected_updated_a = len(expected_a)
    expected_updated_b = len(expected_b - expected_a)
    common_injection = {
        "helper_name": helper_name,
        "dut_name": dut_name,
        "dut_host": dut_inband_address,
        "forbidden_dut_hosts": dut_mgmt_addresses,
        "num_spines": num_spines,
        "num_leaves": num_leaves,
        "num_prefixes_per_node": prefixes_per_node,
        "num_sites": num_sites,
        "num_super_spines": num_control_nodes,
        "dut_role": dut_role,
        "dut_port": dut_port,
        "topology_type": "bbf-simple",
        "extra_flags": [f"--num_pods={ecmp_width}"],
        "remote_path": scale_tester_remote_path,
        "run_duration_sec": injection_run_duration_sec,
        "run_timeout_sec": injection_timeout_sec,
        "area": area,
    }
    common_validation = {
        "dut_name": dut_name,
        "num_spines": num_spines,
        "num_leaves": num_leaves,
        "num_control_nodes": num_control_nodes,
        "num_sites": num_sites,
        "ecmp_width": ecmp_width,
        "prefixes_per_node": prefixes_per_node,
        "dut_role": dut_role,
        "area": area,
        "state_key": state_key,
    }

    return Playbook(
        name="openr_scale_kvstore_merge_playbook",
        prechecks=[],
        postchecks=[],
        snapshot_checks=[],
        stages=[
            create_steps_stage(
                stage_id="openr_scale_kvstore_merge",
                description="Inject two deterministic fabrics and validate KvStore merge semantics",
                steps=[
                    create_openr_scale_performance_step(
                        dut_name=dut_name,
                        profile="kvstore_merge",
                        phase="after_a",
                        state_key=f"{state_key}_performance",
                        action="start",
                    ),
                    create_openr_scale_injection_step(
                        **common_injection,
                        prefix_seed=seed_a,
                        expected_updated_key_vals_delta=expected_updated_a,
                        jq_var_prefix="openr_scale_merge_a",
                    ),
                    create_openr_scale_performance_step(
                        dut_name=dut_name,
                        profile="kvstore_merge",
                        phase="after_a",
                        state_key=f"{state_key}_performance",
                        action="validate",
                    ),
                    create_openr_scale_kvstore_state_step(
                        **common_validation,
                        seeds=[seed_a],
                        checkpoint="after_a",
                    ),
                    create_openr_scale_performance_step(
                        dut_name=dut_name,
                        profile="kvstore_merge",
                        phase="after_b",
                        state_key=f"{state_key}_performance",
                        action="start",
                    ),
                    create_openr_scale_injection_step(
                        **common_injection,
                        prefix_seed=seed_b,
                        expected_updated_key_vals_delta=expected_updated_b,
                        jq_var_prefix="openr_scale_merge_b",
                    ),
                    create_openr_scale_performance_step(
                        dut_name=dut_name,
                        profile="kvstore_merge",
                        phase="after_b",
                        state_key=f"{state_key}_performance",
                        action="validate",
                    ),
                    create_openr_scale_kvstore_state_step(
                        **common_validation,
                        seeds=[seed_a, seed_b],
                        checkpoint="after_b",
                    ),
                ],
            )
        ],
        cleanup_steps=[
            create_openr_scale_kvstore_state_cleanup_step(state_key),
            create_openr_scale_performance_cleanup_step(
                dut_name=dut_name,
                profile="kvstore_merge",
                phase="after_b",
                state_key=f"{state_key}_performance",
            ),
            create_openr_scale_performance_cleanup_step(
                dut_name=dut_name,
                profile="kvstore_merge",
                phase="after_a",
                state_key=f"{state_key}_performance",
            ),
        ],
    )


def get_openr_scale_physical_link_flap_playbook(
    helper_name: str,
    dut_name: str,
    dut_inband_address: str,
    num_spines: int,
    num_leaves: int,
    num_control_nodes: int,
    num_sites: int,
    ecmp_width: int,
    prefixes_per_node: int,
    prefix_seed: int,
    area: str,
    test_port_channel: str = "Port-Channel1911",
    dut_mgmt_addresses: t.Optional[t.List[str]] = None,
    dut_role: t.Literal["leaf", "spine"] = "leaf",
    dut_port: int = 2018,
    scale_tester_remote_path: str = "/mnt/flash/scale_test_server",
    scale_tester_log_path: str = "/mnt/flash/openr_scale_link_flap.log",
    injection_run_duration_sec: int = 900,
    injection_ready_timeout_sec: int = 90,
    link_down_hold_seconds: int = 305,
) -> Playbook:
    """Run one physical port-channel down/up cycle under injected BBF scale."""
    spark_baseline = create_openr_spark_neighbor_check(
        expected_neighbor_count=2,
        check_scope=hc_types.Scope.TOPOLOGY,
        retry_count=20,
        retry_delay_seconds=2,
    )
    spark_degraded = create_openr_spark_neighbor_check(
        expected_neighbor_count=1,
        check_scope=hc_types.Scope.TOPOLOGY,
        retry_count=20,
        retry_delay_seconds=2,
    )
    port_channel_names = {
        helper_name: [test_port_channel],
        dut_name: [test_port_channel],
    }
    lag_down = create_port_channel_expected_state_check(
        json_params={
            "port_channel_names": port_channel_names,
            "expected_up": False,
            "retry_count": 20,
            "retry_delay_seconds": 2,
        },
        check_scope=hc_types.Scope.TOPOLOGY,
    )
    lag_up = create_port_channel_expected_state_check(
        json_params={
            "port_channel_names": port_channel_names,
            "expected_up": True,
            "retry_count": 20,
            "retry_delay_seconds": 2,
        },
        check_scope=hc_types.Scope.TOPOLOGY,
    )
    return Playbook(
        name="openr_scale_physical_link_flap_playbook",
        prechecks=[],
        postchecks=[],
        snapshot_checks=[],
        stages=[
            create_steps_stage(
                stage_id="openr_scale_physical_link_flap",
                description=(
                    f"Flap {test_port_channel} once while a {num_spines}-spine/"
                    f"{num_leaves}-leaf scale session remains active"
                ),
                steps=[
                    create_validation_step(
                        point_in_time_checks=[spark_baseline],
                        description="Verify both physical Open/R adjacencies",
                        start_traffic=False,
                    ),
                    create_openr_scale_injection_step(
                        helper_name=helper_name,
                        dut_name=dut_name,
                        dut_host=dut_inband_address,
                        forbidden_dut_hosts=dut_mgmt_addresses,
                        num_spines=num_spines,
                        num_leaves=num_leaves,
                        num_prefixes_per_node=prefixes_per_node,
                        num_sites=num_sites,
                        num_super_spines=num_control_nodes,
                        prefix_seed=prefix_seed,
                        extra_flags=[
                            f"--num_pods={ecmp_width}",
                            "--fake_key_version_bump_interval_sec=0",
                        ],
                        dut_role=dut_role,
                        area=area,
                        dut_port=dut_port,
                        remote_path=scale_tester_remote_path,
                        run_duration_sec=injection_run_duration_sec,
                        background=True,
                        background_log_path=scale_tester_log_path,
                        background_ready_timeout_sec=injection_ready_timeout_sec,
                        jq_var_prefix="openr_scale_link_flap",
                    ),
                    create_openr_scale_performance_step(
                        dut_name=dut_name,
                        profile="physical_link_down",
                        phase="link_down",
                        state_key="openr_scale_test_4_performance",
                        action="start",
                    ),
                    create_interface_flap_step(
                        enable=False,
                        interfaces=[test_port_channel],
                        interface_flap_method=4,
                        device_name=helper_name,
                        delay=0,
                        start_traffic=False,
                        description=f"Shut {test_port_channel} on {helper_name}",
                    ),
                    create_validation_step(
                        point_in_time_checks=[lag_down],
                        description=f"Verify {test_port_channel} down on both devices",
                        start_traffic=False,
                    ),
                    create_validation_step(
                        point_in_time_checks=[spark_degraded],
                        description="Verify only the stable Po1910 adjacency remains",
                        start_traffic=False,
                    ),
                    create_openr_scale_performance_step(
                        dut_name=dut_name,
                        profile="physical_link_down",
                        phase="link_down",
                        state_key="openr_scale_test_4_performance",
                        action="validate",
                    ),
                    create_longevity_step(
                        duration=link_down_hold_seconds,
                        description=(
                            "Hold the test link down until LinkMonitor dampening "
                            "has expired"
                        ),
                        start_traffic=False,
                    ),
                    create_openr_scale_performance_step(
                        dut_name=dut_name,
                        profile="physical_link_up",
                        phase="link_up",
                        state_key="openr_scale_test_4_performance",
                        action="start",
                    ),
                    create_interface_flap_step(
                        enable=True,
                        interfaces=[test_port_channel],
                        interface_flap_method=4,
                        device_name=helper_name,
                        delay=0,
                        start_traffic=False,
                        description=f"No-shut {test_port_channel} on {helper_name}",
                    ),
                    create_validation_step(
                        point_in_time_checks=[lag_up],
                        description=f"Verify {test_port_channel} up on both devices",
                        start_traffic=False,
                    ),
                    create_validation_step(
                        point_in_time_checks=[spark_baseline],
                        description="Verify the second Open/R adjacency is restored",
                        start_traffic=False,
                    ),
                    create_openr_scale_performance_step(
                        dut_name=dut_name,
                        profile="physical_link_up",
                        phase="link_up",
                        state_key="openr_scale_test_4_performance",
                        action="validate",
                    ),
                    create_openr_scale_kvstore_state_step(
                        dut_name=dut_name,
                        seeds=[prefix_seed],
                        num_spines=num_spines,
                        num_leaves=num_leaves,
                        num_control_nodes=num_control_nodes,
                        num_sites=num_sites,
                        ecmp_width=ecmp_width,
                        prefixes_per_node=prefixes_per_node,
                        dut_role=dut_role,
                        area=area,
                        checkpoint="single",
                    ),
                ],
            )
        ],
        cleanup_steps=[
            create_openr_scale_performance_cleanup_step(
                dut_name=dut_name,
                profile="physical_link_up",
                phase="link_up",
                state_key="openr_scale_test_4_performance",
            ),
            create_openr_scale_performance_cleanup_step(
                dut_name=dut_name,
                profile="physical_link_down",
                phase="link_down",
                state_key="openr_scale_test_4_performance",
            ),
        ],
    )


def get_openr_scale_dut_cold_boot_playbook(
    *,
    helper_name: str,
    dut_name: str,
    dut_inband_address: str,
    num_spines: int = 64,
    num_leaves: int = 256,
    num_control_nodes: int = 0,
    num_sites: int = 20,
    ecmp_width: int = 8,
    prefixes_per_node: int = 11,
    prefix_seed: int = 20250903,
    area: str = "0",
    dut_role: t.Literal["leaf", "spine"] = "leaf",
    interface: str = "po1910",
    start_vlan: int = 100,
    dut_mgmt_addresses: t.Optional[t.List[str]] = None,
    dut_port: int = 2018,
    scale_tester_remote_path: str = "/mnt/flash/scale_test_server",
    scale_tester_log_path: str = "/mnt/flash/openr_scale_dut_cold_boot.log",
    injector_watchdog_seconds: int = 1800,
    injector_ready_timeout_seconds: int = 120,
    stable_seconds: int = 60,
    state_key: str = "openr_scale_dut_cold_boot",
    profile: str = "cold_boot_64_256_leaf",
) -> Playbook:
    """Reboot only the DUT under a persistent full-fabric Open/R session."""

    injector_jq_var_prefix = "openr_scale_cold_boot"
    if dut_role == "leaf":
        synthetic_neighbors = [
            *(f"spine-{index}" for index in range(num_spines)),
            *(["eb-site-0"] if num_sites else []),
        ]
    else:
        synthetic_neighbors = [
            *(f"leaf-{index}" for index in range(num_leaves)),
            *(f"control-{index}" for index in range(num_control_nodes)),
        ]
    num_subinterfaces = len(synthetic_neighbors) - 1
    if num_subinterfaces <= 0:
        raise ValueError("cold-boot scale requires at least two synthetic neighbors")
    if start_vlan <= 0 or start_vlan + num_subinterfaces - 1 > 4094:
        raise ValueError("cold-boot subinterface VLAN range must be within 1..4094")
    # Keep the deterministic route probe (spine-0) on the physical LAG so
    # FibAgent can program its next hop into EOS. Give every remaining fake
    # neighbor a unique subinterface; concentrating all of them on one Spark
    # interface can leave one adjacency absent at this scale.
    scale_interfaces = [
        interface,
        *(f"{interface}.{start_vlan + index}" for index in range(num_subinterfaces)),
    ]
    common_state = {
        "dut_name": dut_name,
        "helper_name": helper_name,
        "num_spines": num_spines,
        "num_leaves": num_leaves,
        "num_control_nodes": num_control_nodes,
        "num_sites": num_sites,
        "prefixes_per_node": prefixes_per_node,
        "prefix_seed": prefix_seed,
        "dut_role": dut_role,
        "area": area,
        "interface": interface,
        "scale_interfaces": scale_interfaces,
        "injector_jq_var_prefix": injector_jq_var_prefix,
        "state_key": state_key,
        "profile": profile,
    }
    dut_neighbor_interfaces = dict(
        zip(synthetic_neighbors, scale_interfaces, strict=True)
    )
    return Playbook(
        name="openr_scale_dut_cold_boot_playbook",
        prechecks=[],
        postchecks=[],
        # This lab image enables fb-config.service without provisioning its
        # required fb_config_agent.conf, so FbConfigAgent aborts during every
        # boot. Keep every other newly created core blocking.
        snapshot_checks=[
            create_core_dumps_snapshot_check(core_dumps_to_ignore=["FbConfigAgent"])
        ],
        periodic_tasks=[
            create_openr_scale_cold_boot_monitor_task(
                device_name=dut_name,
                profile=profile,
            )
        ],
        stages=[
            create_steps_stage(
                stage_id="openr_scale_dut_cold_boot",
                description=(
                    f"Cold reboot {dut_name} under a persistent "
                    f"{num_spines}-spine/{num_leaves}-leaf Open/R fabric"
                ),
                steps=[
                    create_openr_scale_injection_step(
                        helper_name=helper_name,
                        dut_name=dut_name,
                        dut_host=dut_inband_address,
                        forbidden_dut_hosts=dut_mgmt_addresses,
                        num_spines=num_spines,
                        num_leaves=num_leaves,
                        num_prefixes_per_node=prefixes_per_node,
                        num_sites=num_sites,
                        num_super_spines=num_control_nodes,
                        prefix_seed=prefix_seed,
                        extra_flags=[
                            f"--num_pods={ecmp_width}",
                            "--num_fake_keys_per_node=0",
                            "--fake_key_version_bump_interval_sec=0",
                        ],
                        dut_role=dut_role,
                        area=area,
                        dut_port=dut_port,
                        simulate_neighbors=True,
                        # Route/FIB correctness is validated below from the DUT's
                        # Thrift state and the complete EOS RIB. The injector's
                        # verify flag only sleeps and logs counts, so enabling it
                        # adds delay without a gate.
                        verify_routes=False,
                        interfaces=scale_interfaces,
                        remote_path=scale_tester_remote_path,
                        run_duration_sec=injector_watchdog_seconds,
                        background=True,
                        background_log_path=scale_tester_log_path,
                        background_ready_timeout_sec=injector_ready_timeout_seconds,
                        jq_var_prefix=injector_jq_var_prefix,
                    ),
                    create_openr_scale_kvstore_state_step(
                        dut_name=dut_name,
                        seeds=[prefix_seed],
                        num_spines=num_spines,
                        num_leaves=num_leaves,
                        num_control_nodes=num_control_nodes,
                        num_sites=num_sites,
                        ecmp_width=ecmp_width,
                        prefixes_per_node=prefixes_per_node,
                        dut_role=dut_role,
                        area=area,
                        dut_neighbor_interfaces=dut_neighbor_interfaces,
                    ),
                    create_openr_scale_cold_boot_step(
                        action="baseline",
                        **common_state,
                    ),
                    create_openr_scale_cold_boot_step(
                        action="mark_reboot",
                        **common_state,
                    ),
                    create_system_reboot_step(
                        trigger=taac_types.SystemRebootTrigger.FULL_SYSTEM_REBOOT,
                        device_regexes=[dut_name],
                        description=f"Cold reboot only {dut_name}",
                    ),
                    create_openr_scale_cold_boot_step(
                        action="activate",
                        **common_state,
                    ),
                    create_openr_scale_cold_boot_step(
                        action="recover",
                        **common_state,
                    ),
                    create_longevity_step(
                        duration=stable_seconds,
                        start_traffic=False,
                        description=(
                            f"Require {stable_seconds}s of stable post-boot "
                            "Open/R telemetry"
                        ),
                    ),
                    create_openr_scale_kvstore_state_step(
                        dut_name=dut_name,
                        seeds=[prefix_seed],
                        num_spines=num_spines,
                        num_leaves=num_leaves,
                        num_control_nodes=num_control_nodes,
                        num_sites=num_sites,
                        ecmp_width=ecmp_width,
                        prefixes_per_node=prefixes_per_node,
                        dut_role=dut_role,
                        area=area,
                        dut_neighbor_interfaces=dut_neighbor_interfaces,
                    ),
                    create_openr_scale_cold_boot_step(
                        action="finalize",
                        **common_state,
                    ),
                ],
            )
        ],
        cleanup_steps=[
            create_openr_scale_cold_boot_step(action="cleanup", **common_state),
        ],
    )
