# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict
import typing as t

from taac.health_check.health_check import types as hc_types
from taac.test_run_result import types as trr_types

_STATUS_PRECEDENCE: t.Tuple[hc_types.HealthCheckStatus, ...] = (
    hc_types.HealthCheckStatus.ERROR,
    hc_types.HealthCheckStatus.FAIL,
    hc_types.HealthCheckStatus.UNKNOWN,
    hc_types.HealthCheckStatus.PASS,
    hc_types.HealthCheckStatus.SKIP,
)


def worst_check_status(
    results: t.Iterable[trr_types.CheckResult],
) -> hc_types.HealthCheckStatus:
    """Reduce check results to the single status that decides their verdict.

    PASS outranks SKIP. A device health check whose OPERATING_SYSTEMS exclude
    the device returns SKIP, so on a mixed-vendor testbed a fully passing
    playbook carries far more SKIPs than PASSes. One real PASS makes the
    playbook a PASS; only a playbook that measured nothing at all is a SKIP.

    Returns UNKNOWN for an empty input: nothing was measured, so there is no
    evidence to call it a pass.
    """
    statuses = {result.status for result in results}
    for status in _STATUS_PRECEDENCE:
        if status in statuses:
            return status
    return hc_types.HealthCheckStatus.UNKNOWN


def build_run_result(
    *,
    test_config: str,
    outcome: trr_types.RunOutcome,
    exit_code: int,
    start_time_epoch_s: int,
    end_time_epoch_s: int,
    duts: t.Sequence[str],
    playbooks: t.Sequence[trr_types.PlaybookResult],
    sections: t.Sequence[trr_types.SectionResult],
    error_message: t.Optional[str] = None,
    log_file: t.Optional[str] = None,
) -> trr_types.RunResult:
    return trr_types.RunResult(
        test_config=test_config,
        outcome=outcome,
        exit_code=exit_code,
        start_time_epoch_s=start_time_epoch_s,
        end_time_epoch_s=end_time_epoch_s,
        duts=list(duts),
        playbooks=list(playbooks),
        sections=list(sections),
        error_message=error_message,
        log_file=log_file,
    )
