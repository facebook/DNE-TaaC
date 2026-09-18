# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""Open/R scale playbook factories (one factory = one test case).

Naming: ``Playbook.name = openr_scale_<case>_playbook`` and each public factory
is exactly ``get_{playbook_name}``. See README.md for the routing suite
contract.
"""

import typing as t

from taac.stages.stage_definitions import create_steps_stage
from taac.steps.step_definitions import (
    create_openr_scale_injection_step,
    create_openr_scale_kvstore_state_cleanup_step,
    create_openr_scale_kvstore_state_step,
)
from openr.tests.scale.scripts.scale_key_names import (
    bbf_simple_node_names,
    expected_key_set,
)
from taac.test_as_a_config.types import Playbook


__all__ = [
    "get_openr_scale_kvstore_injection_playbook",
    "get_openr_scale_kvstore_merge_playbook",
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
    1. Trigger: run ``scale_test_server`` on the helper, injecting a synthetic
       ``num_spines``/``num_leaves`` fabric into the DUT's KvStore over the
       DUT's inband address.
    2. Delivery acknowledgement: the injection step samples
       ``kvstore.received_key_vals`` on the DUT immediately before and after the
       injector runs, and fails unless the increase is exactly the number of
       key-values the fabric should have sent.
    3. Semantic validation: the next ordered step derives every expected key
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

    Nothing else is gated. There are no resource ceilings -- a 4,068 key-value
    injection legitimately spikes Open/R CPU while flooding converges, and an
    arbitrary ceiling would pre-empt the result this test exists to produce --
    and no core-dump snapshot, because a crash that matters here already breaks
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
                    create_openr_scale_injection_step(
                        **common_injection,
                        prefix_seed=seed_a,
                        expected_updated_key_vals_delta=expected_updated_a,
                        jq_var_prefix="openr_scale_merge_a",
                    ),
                    create_openr_scale_kvstore_state_step(
                        **common_validation,
                        seeds=[seed_a],
                        checkpoint="after_a",
                    ),
                    create_openr_scale_injection_step(
                        **common_injection,
                        prefix_seed=seed_b,
                        expected_updated_key_vals_delta=expected_updated_b,
                        jq_var_prefix="openr_scale_merge_b",
                    ),
                    create_openr_scale_kvstore_state_step(
                        **common_validation,
                        seeds=[seed_a, seed_b],
                        checkpoint="after_b",
                    ),
                ],
            )
        ],
        cleanup_steps=[create_openr_scale_kvstore_state_cleanup_step(state_key)],
    )
