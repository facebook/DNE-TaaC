# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
"""Open/R Decision->Fib update-loss playbook (one factory = one test case).

Regression coverage for S696505: while Fib is stalled and not draining the
Decision->Fib queue, a later disjoint-or-empty rebuild must not discard a
still-pending route update. On builds where rebuilds are mislabeled FULL_SYNC
with push-time coalescing enabled, the pending update is silently lost and Fib
plus EOS keep stale values while Decision moves on; this playbook fails in
exactly that case and passes when every update is delivered.

Naming: ``Playbook.name = openr_update_loss_playbook`` and the public factory
is exactly ``get_{playbook_name}``. See README.md for the routing suite
contract.
"""

import typing as t

from taac.health_checks.healthcheck_definitions import (
    create_service_restart_check,
)
from taac.stages.stage_definitions import create_steps_stage
from taac.steps.step_definitions import (
    create_longevity_step,
    create_openr_fibagent_pause_step,
    create_openr_scale_injection_step,
    create_openr_update_loss_validation_step,
    create_validation_step,
)
from taac.test_as_a_config.types import Playbook


__all__ = [
    "get_openr_update_loss_playbook",
]


def _asymmetric_burst_cmd(
    full_interface: str,
    disjoint_interface: str,
    full_metric_first: int,
    full_metric_second: int,
    disjoint_metric: int,
) -> str:
    """Three local metric rebuilds: full, full, then disjoint-narrow.

    Two updates can never lose anything: Fib dequeues the first within
    milliseconds and only blocks afterwards, so the second merely queues behind
    it and both get programmed. The loss needs a victim that is still queued
    when the replacer arrives: the first full-table update is consumed and
    blocks Fib on the frozen FibAgent, the second full-table update sits
    pending, and the disjoint (second-link-only, possibly empty) rebuild
    replaces it in the coalesced queue. Fib then programs first + third only,
    and every fabric route stays at the first update's values while Decision
    moved on.

    Decision's debounce max is 250ms; the sleeps guarantee three separate
    rebuildRoutes pushes, all inside the freeze window.
    """
    return (
        f"timeout 60 breeze lm increase-link-metric --yes --quiet "
        f"{full_interface} {full_metric_first} >/dev/null 2>&1"
        "; sleep 2; "
        f"timeout 60 breeze lm increase-link-metric --yes --quiet "
        f"{full_interface} {full_metric_second} >/dev/null 2>&1"
        "; sleep 2; "
        f"timeout 60 breeze lm increase-link-metric --yes --quiet "
        f"{disjoint_interface} {disjoint_metric} >/dev/null 2>&1"
    )


def get_openr_update_loss_playbook(
    *,
    dut_name: str,
    helper_name: str,
    dut_inband_address: str,
    dut_mgmt_addresses: t.Optional[t.List[str]] = None,
    full_interface: str = "po1910",
    disjoint_interface: str = "po1911",
    full_metric_first: int = 50,
    full_metric_second: int = 60,
    disjoint_metric: int = 70,
    pause_tail_seconds: float = 1.0,
    settle_seconds: int = 20,
    num_spines: int = 4,
    num_leaves: int = 10,
    num_sites: int = 2,
    ecmp_width: int = 1,
    prefixes_per_node: int = 4,
    prefix_seed: int = 20250903,
    scale_tester_remote_path: str = "/mnt/flash/scale_test_server",
    scale_tester_log_path: str = "/mnt/flash/openr_update_loss.log",
    injector_watchdog_seconds: int = 1800,
    ready_timeout_seconds: int = 600,
) -> Playbook:
    """Freeze FibAgent through full, full, disjoint metric rebuilds.

    The helper simulates a small fabric with every neighbor on
    ``full_interface`` only, so every fabric route's nexthop is there and only
    the peer's own routes (if any) can use ``disjoint_interface``. FibAgent
    rejects next hops on ``<interface>.<vlan>`` subinterfaces, so both
    interfaces must be plain LAGs. The stall is forced with SIGSTOP, so the
    loss mechanism needs no scale: the small fabric keeps the run fast while
    the queue mechanics are identical to a large one.
    """
    burst_cmd = _asymmetric_burst_cmd(
        full_interface,
        disjoint_interface,
        full_metric_first,
        full_metric_second,
        disjoint_metric,
    )
    return Playbook(
        name="openr_update_loss_playbook",
        prechecks=[],
        postchecks=[],
        snapshot_checks=[],
        stages=[
            create_steps_stage(
                stage_id="openr_update_loss",
                description=(
                    f"Detect Decision->Fib update loss on {dut_name} under a "
                    "FibAgent freeze"
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
                        num_super_spines=0,
                        prefix_seed=prefix_seed,
                        extra_flags=[
                            f"--num_pods={ecmp_width}",
                            "--num_fake_keys_per_node=0",
                            "--fake_key_version_bump_interval_sec=0",
                        ],
                        simulate_neighbors=True,
                        verify_routes=False,
                        interfaces=[full_interface],
                        remote_path=scale_tester_remote_path,
                        run_duration_sec=injector_watchdog_seconds,
                        background=True,
                        background_log_path=scale_tester_log_path,
                        jq_var_prefix="openr_update_loss",
                    ),
                    create_openr_update_loss_validation_step(
                        dut_name=dut_name,
                        action="ready",
                        timeout_seconds=ready_timeout_seconds,
                    ),
                    create_openr_fibagent_pause_step(
                        dut_name=dut_name,
                        pause_seconds=pause_tail_seconds,
                        during_pause_shell_cmd=burst_cmd,
                        description=(
                            "Freeze FibAgent through full, full, disjoint "
                            f"metric rebuilds on {full_interface}/"
                            f"{disjoint_interface}"
                        ),
                    ),
                    create_longevity_step(
                        duration=settle_seconds,
                        start_traffic=False,
                        description=(
                            f"Let Open/R and FibAgent settle for {settle_seconds}s"
                        ),
                    ),
                    create_openr_update_loss_validation_step(
                        dut_name=dut_name,
                        action="validate",
                        min_moved_prefixes=1,
                        stimulus_cmd=burst_cmd,
                    ),
                    # A step, not a postcheck, so it runs on the DUT only;
                    # services=[] skips the default agent list this platform
                    # never runs. A restart would resync Fib and mask the bug.
                    create_validation_step(
                        point_in_time_checks=[
                            create_service_restart_check(
                                services=[], daemons=["FibAgent", "Openr"]
                            )
                        ],
                        description="FibAgent and Openr were not restarted",
                        start_traffic=False,
                        fail_on_failure=True,
                    ),
                ],
            )
        ],
    )
