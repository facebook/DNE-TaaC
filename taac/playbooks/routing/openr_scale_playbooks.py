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
)
from taac.test_as_a_config.types import Playbook


__all__ = [
    "get_openr_scale_kvstore_injection_playbook",
]


def get_openr_scale_kvstore_injection_playbook(
    helper_name: str,
    dut_name: str,
    dut_inband_address: str,
    num_spines: int,
    num_leaves: int,
    dut_mgmt_addresses: t.Optional[t.List[str]] = None,
    dut_role: str = "leaf",
    dut_port: int = 2018,
    scale_tester_remote_path: str = "/mnt/flash/scale_test_server",
    num_prefixes_per_node: t.Optional[int] = None,
    injection_run_duration_sec: t.Optional[int] = None,
    injection_timeout_sec: int = 240,
) -> Playbook:
    """
    Build the Open/R scale KvStore injection and key-receipt test.

    See ``fbcode/neteng/test_infra/routing_qualification/catalogs/taac/openr_scale_catalog.yaml``
    for the test contract and triage guidance.

    Sequence:
    1. Trigger: run ``scale_test_server`` on the helper, injecting a synthetic
       ``num_spines``/``num_leaves`` fabric into the DUT's KvStore over the
       DUT's inband address.
    2. Behavioural validation: the injection step samples
       ``kvstore.received_key_vals`` on the DUT immediately before and after the
       injector runs, and fails when the increase falls short of the key-values
       the fabric should have sent.

    The gate is on key-values *received*, read from the DUT's own Open/R over
    Thrift. The DUT is a real lab box already holding thousands of its own
    genuine keys, and every earlier run leaves an infinite-TTL residue behind,
    so no assertion over resident KvStore *state* can establish that this run's
    keys arrived. A receive counter sampled across the injection can.
    ``kvstore.updated_key_vals`` is logged over the same window; the merged
    subset is gated by the KvStore-merge test, which carries the clean-store
    precondition that makes exact per-node counts meaningful.

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
        dut_role: ``leaf`` (neighbors are spines) or ``spine``.
        num_prefixes_per_node: prefixes each synthetic node advertises, and so
            part of the expected send count.
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
                    f"fabric into {dut_name} and verify it received every key"
                ),
                steps=[
                    create_openr_scale_injection_step(
                        helper_name=helper_name,
                        dut_name=dut_name,
                        dut_host=dut_inband_address,
                        forbidden_dut_hosts=dut_mgmt_addresses,
                        num_spines=num_spines,
                        num_leaves=num_leaves,
                        num_prefixes_per_node=num_prefixes_per_node,
                        dut_role=dut_role,
                        dut_port=dut_port,
                        remote_path=scale_tester_remote_path,
                        run_duration_sec=injection_run_duration_sec,
                        run_timeout_sec=injection_timeout_sec,
                    ),
                ],
            ),
        ],
    )
