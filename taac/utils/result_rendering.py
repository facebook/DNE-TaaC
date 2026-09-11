# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-strict

# A leaf module: stdlib, tabulate and the generated thrift types only. The
# bastion spec server imports it to render a RunResult it deserialized, and it
# must not drag in the taac runtime (pyjq, libfb, netcastle, taac constants)
# to do so.

import typing as t
from datetime import datetime
from textwrap import wrap

from taac.health_check.health_check import types as hc_types
from taac.test_as_a_config import types as taac_types
from taac.test_run_result import types as trr_types
from tabulate import tabulate

PASSING_SECTION_STATUSES: t.FrozenSet[trr_types.SectionStatus] = frozenset(
    {trr_types.SectionStatus.PASS, trr_types.SectionStatus.SKIPPED}
)

PASSING_CHECK_STATUSES: t.FrozenSet[hc_types.HealthCheckStatus] = frozenset(
    {hc_types.HealthCheckStatus.PASS, hc_types.HealthCheckStatus.SKIP}
)

CHECK_RESULT_TABLE_COLUMNS: t.List[str] = [
    "HOSTNAMES",
    "TEST_CASE_NAME",
    "START_TIME",
    "END_TIME",
    "PLATFORMS",
    "CHECK_NAME",
    "CHECK_STAGE",
    "TEST_STATUS",
    "MESSAGE",
]

_SECTION_STATUS_DISPLAY: t.Dict[trr_types.SectionStatus, str] = {
    trr_types.SectionStatus.FAIL: "FAIL",
    trr_types.SectionStatus.INFRA_ERROR: "INFRA_ERROR",
    trr_types.SectionStatus.PASS: "PASS",
    trr_types.SectionStatus.SKIPPED: "SKIP",
}

MAX_REPORTED_MESSAGE_CHARS: int = 200


def section_failed(status: trr_types.SectionStatus) -> bool:
    """Whether a section counts against the run.

    Enumerating the passing values rather than the failing ones is what keeps
    two cases from reading as green: a section still IN_PROGRESS because the
    run was abandoned before its stage loop, and a status added to the enum
    after this consumer was built, which deserializes to a ``BadEnum`` that
    compares unequal to every member instead of raising.
    """
    return status not in PASSING_SECTION_STATUSES


def check_failed(status: hc_types.HealthCheckStatus) -> bool:
    """Whether a health check counts against the run.

    Fail-closed for the same reasons as [`section_failed`].
    """
    return status not in PASSING_CHECK_STATUSES


def format_duration(seconds: float) -> str:
    """Format seconds into a human-readable duration string."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    remaining_secs = seconds % 60
    if minutes < 60:
        return f"{minutes}m {remaining_secs:.0f}s"
    hours = int(minutes // 60)
    remaining_mins = minutes % 60
    return f"{hours}h {remaining_mins}m {remaining_secs:.0f}s"


def format_epoch_timestamp(epoch_s: int) -> str:
    return datetime.fromtimestamp(epoch_s).strftime("%m/%d/%Y-%H:%M:%S")


def truncate_message(message: str, max_length: int) -> str:
    """Truncate a message to max_length, appending '...' if truncated."""
    if len(message) > max_length:
        return message[:max_length] + "..."
    return message


def _collapse_and_truncate(message: str) -> str:
    collapsed = " ".join(message.split())
    if len(collapsed) <= MAX_REPORTED_MESSAGE_CHARS:
        return collapsed
    return collapsed[:MAX_REPORTED_MESSAGE_CHARS] + "..."


def check_stage_name(
    check_stage: t.Optional[taac_types.ValidationStage], absent: str = "-"
) -> str:
    """The stage's name, or ``absent`` for a check that carried no stage.

    Tested against None rather than truthiness: a zero-valued member added to
    ``ValidationStage`` later would otherwise render as if it were unset.
    """
    return absent if check_stage is None else check_stage.name


def message_with_url(message: t.Optional[str], message_url: t.Optional[str]) -> str:
    """The message text followed by the link to its untruncated form.

    ``message`` is a prefix whenever ``message_url`` is set, so dropping the
    link leaves a reader with text that stops mid-sentence and no way to
    reach the rest.
    """
    if not message_url:
        return message or ""
    if not message:
        return f"full message: {message_url}"
    return f"{message} (full message: {message_url})"


def _message_cell(result: trr_types.CheckResult) -> str:
    """The MESSAGE column: wrapped text, with any link on its own line.

    The link is kept out of ``wrap`` so the column never breaks a URL across
    lines and makes it unclickable.
    """
    lines = wrap(result.message) if result.message else []
    if result.message_url:
        lines.append(f"Full message: {result.message_url}")
    return "\n".join(lines)


def _check_result_row(result: trr_types.CheckResult) -> t.List[str]:
    return [
        "\n".join(result.hostnames),
        "\n".join(wrap(result.test_case_name, width=50)),
        format_epoch_timestamp(result.start_time_epoch_s),
        format_epoch_timestamp(result.end_time_epoch_s),
        "\n".join(
            f"{hostname}: {hardware}"
            for hostname, hardware in result.hardware_by_hostname.items()
        ),
        result.check_name,
        check_stage_name(result.check_stage, absent=""),
        result.status.name,
        _message_cell(result),
    ]


def check_results_table(
    results: t.Sequence[trr_types.CheckResult],
    no_header: bool = False,
) -> str:
    """Tabulate check results into a grid table."""
    rows: t.List[t.List[str]] = [_check_result_row(result) for result in results]
    if no_header:
        return tabulate(rows, tablefmt="grid")
    return tabulate(rows, headers=CHECK_RESULT_TABLE_COLUMNS, tablefmt="grid")


def section_status_string(status: trr_types.SectionStatus) -> str:
    """Convert a SectionStatus to its display string."""
    return _SECTION_STATUS_DISPLAY.get(status, "...")


def section_row_lines(section: trr_types.SectionResult) -> t.List[str]:
    """Format a single section as table row(s) including failure reason if applicable."""
    lines: t.List[str] = []
    indent = "  " * section.indent_level
    display_name = f"{indent}{section.name}"
    status_str = section_status_string(section.status)
    duration_str = (
        format_duration(section.duration_secs) if section.duration_secs > 0 else "-"
    )
    # "-" means "not uploaded separately", not "no logs". Passing sections
    # are covered by the full-log paste linked at the bottom of the summary.
    url = section.everpaste_url or "-"
    lines.append(f"  {display_name:<45} {status_str:<10} {duration_str:<15} {url}")
    if section_failed(section.status) and section.error_message:
        short_err = truncate_message(section.error_message, 80)
        lines.append(f"  {indent}  └─ REASON: {short_err}")
    return lines


def failure_detail_lines(
    failed_sections: t.Sequence[trr_types.SectionResult],
) -> t.List[str]:
    """Format the failure details section for failed sections."""
    lines: t.List[str] = []
    lines.append("=" * 100)
    lines.append(f"{'FAILURE DETAILS':^100}")
    lines.append("=" * 100)
    lines.append("")
    for s in failed_sections:
        lines.append(f"  ✗ {s.name}")
        lines.append(f"    Duration: {format_duration(s.duration_secs)}")
        lines.append(f"    Logs: {s.everpaste_url or 'N/A'}")
        if s.error_message:
            err = truncate_message(s.error_message, 500)
            lines.append(f"    Error: {err}")
        lines.append("")
    return lines


def section_table(sections: t.Sequence[trr_types.SectionResult]) -> str:
    """Render the execution-section table."""
    lines: t.List[str] = []
    lines.append("=" * 100)
    lines.append(f"{'TEST EXECUTION SUMMARY':^100}")
    lines.append("=" * 100)
    lines.append("")
    header = f"  {'Section':<45} {'Status':<10} {'Duration':<15} {'Logs'}"
    lines.append(header)
    lines.append("  " + "-" * 95)

    for section in sections:
        lines.extend(section_row_lines(section))

    failed = [section for section in sections if section_failed(section.status)]
    lines.append("  " + "-" * 95)
    overall = "SOME SECTIONS FAILED" if failed else "ALL SECTIONS PASSED"
    lines.append(f"  Overall: {overall}")
    lines.append("")

    if failed:
        lines.extend(failure_detail_lines(failed))

    return "\n".join(lines)


def playbook_table(playbooks: t.Sequence[trr_types.PlaybookResult]) -> str:
    """Render one row per playbook: name, DUT, iteration, status, check count."""
    lines = [
        f"  {'Playbook':<40} {'DUT':<26} {'Iter':<5} {'Status':<8} Checks",
        "  " + "-" * 92,
    ]
    for playbook in playbooks:
        lines.append(
            f"  {playbook.playbook_name:<40} {playbook.dut:<26} "
            f"{playbook.iteration:<5} {playbook.status.name:<8} "
            f"{len(playbook.results)}"
        )
    return "\n".join(lines)


def investigation_artifact_lines(
    artifacts: t.Sequence[trr_types.InvestigationArtifact],
) -> t.List[str]:
    """Render durable investigation transcripts with their execution scope."""
    lines: t.List[str] = []
    for artifact in artifacts:
        scope = (
            "Phase unknown"
            if artifact.phase == trr_types.InvestigationPhase.UNKNOWN
            else artifact.phase.name.replace("_", " ").title()
        )
        identity = " | ".join(
            value for value in (artifact.playbook_name, artifact.dut) if value
        )
        if identity:
            scope = f"{scope} | {identity}"
        lines.append(f"  {scope}")
        if artifact.headline:
            lines.append(f"    {artifact.headline}")
        lines.append(f"    Transcript: {artifact.transcript_url}")
    return lines


def investigation_artifacts_section(
    artifacts: t.Sequence[trr_types.InvestigationArtifact],
) -> str:
    """Render the compact investigation block shown beside failure details."""
    if not artifacts:
        return ""
    return "\n".join(
        [
            "=" * 100,
            f"{'INVESTIGATION SUMMARY':^100}",
            "=" * 100,
            "",
            *investigation_artifact_lines(artifacts),
        ]
    )


def _failing_check_lines(
    playbooks: t.Sequence[trr_types.PlaybookResult],
) -> t.List[str]:
    failures = [
        (playbook, check)
        for playbook in playbooks
        for check in playbook.results
        if check_failed(check.status)
    ]
    if not failures:
        return []
    lines = ["", f"Failing checks ({len(failures)}):"]
    for playbook, check in failures:
        stage = check_stage_name(check.check_stage)
        hosts = ", ".join(check.hostnames) or "-"
        message = message_with_url(
            _collapse_and_truncate(check.message) if check.message else None,
            check.message_url,
        )
        lines.append(
            f"  [{playbook.playbook_name}/{stage}] {check.check_name} "
            f"on {hosts}: {message or '-'}"
        )
    return lines


def format_run_report(run_result: trr_types.RunResult) -> str:
    """Render a RunResult as verbosely as the run itself logged it.

    An early failure (IXIA setup, device reservation) leaves ``playbooks``
    empty and ``sections`` holding the entire story, so the section table is
    not optional decoration -- on those runs it is the whole report.
    """
    duration_s = run_result.end_time_epoch_s - run_result.start_time_epoch_s
    lines = [
        f"Test config: {run_result.test_config}",
        f"Outcome: {run_result.outcome.name} (exit code {run_result.exit_code})",
        f"Duration: {format_duration(duration_s)}",
        f"DUTs: {', '.join(run_result.duts) or 'none'}",
    ]
    if run_result.error_message:
        lines.append(f"Error: {_collapse_and_truncate(run_result.error_message)}")
    if run_result.sections:
        lines.extend(["", "EXECUTION SECTIONS", section_table(run_result.sections)])
    investigation_summary = investigation_artifacts_section(
        run_result.investigation_artifacts
    )
    if investigation_summary:
        lines.extend(["", investigation_summary])
    if run_result.playbooks:
        lines.extend(["", "PLAYBOOKS", playbook_table(run_result.playbooks)])
    for playbook in run_result.playbooks:
        if not playbook.results:
            continue
        lines.extend(
            [
                "",
                f"Playbook: {playbook.playbook_name} | {playbook.dut} | "
                f"iteration {playbook.iteration} | {playbook.status.name}",
                check_results_table(playbook.results),
            ]
        )
    lines.extend(_failing_check_lines(run_result.playbooks))
    return "\n".join(lines)
