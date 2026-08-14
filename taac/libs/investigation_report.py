# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict
from __future__ import annotations

import functools
from importlib import resources

from pydantic import BaseModel, Field

_PROMPT_RESOURCE_NAME: str = "investigation_prompt.xml"

_BLOCK_HEADER: str = "===== INVESTIGATION REPORT ====="
_NO_REPORT: str = "The investigation agent produced no structured report."
_NO_FINDINGS: str = "no referenced findings"
_NO_PRIOR_ART: str = "nothing found"
_INDENT: str = "  "
_FIELD_INDENT: str = "     "


class Reproduce(BaseModel):
    """A recipe for a human or a later job. The harness never runs it."""

    host: str = Field(description="The reserved device the command runs on.")
    command: str = Field(
        description="The command, exactly as an engineer would paste it."
    )
    expect: str = Field(description="What the output shows if the claim holds.")


class Finding(BaseModel):
    claim: str = Field(
        description="One statement about this failure, in the voice of an observation."
    )
    referent: str = Field(
        description=(
            "The artifact backing the claim, which has to exist independently "
            "of this report: a D-number, a task, a SEV, a wiki URL, a "
            "file:line, a counter name read with its value, or an everpaste "
            "URL. A claim with no referent is an open lead, not a finding."
        )
    )
    reproduce: Reproduce | None = Field(
        default=None,
        description="The recipe that re-derives the claim, where one exists.",
    )


class InvestigationReport(BaseModel):
    """Every list defaults to empty: a model that found no prior art omits the
    key, and a report discarded over a missing key costs the whole
    investigation."""

    headline: str = Field(
        description=(
            "One imperative line naming the artifact to act on. It has to "
            "stand alone, without the appendix."
        )
    )
    recommended_action: str = Field(
        description="What to do next, naming a concrete artifact."
    )
    prior_art: list[str] = Field(
        default_factory=list,
        description=(
            "The references found for this failure on this test config, this "
            "check, or this platform. Empty only after a search that found "
            "nothing, with that search stated in the appendix."
        ),
    )
    findings: list[Finding] = Field(
        default_factory=list,
        description=(
            "The claims carrying a referent, the one supporting the "
            "recommended action first. There is no ranking and no score."
        ),
    )
    open_leads: list[str] = Field(
        default_factory=list,
        description=(
            "What no referent could be produced for, each with the diagnostic "
            "that would close it."
        ),
    )
    appendix: str = Field(
        description=(
            "The full narrative: the reasoning, the axis comparison, the "
            "control groups, and the timestamped sequence over the "
            "disruptive-operation window."
        )
    )


@functools.cache
def investigation_task() -> str:
    """The investigation task text, read once out of this module's package.

    Resolved through ``importlib.resources`` so the same call works from the
    source tree and from inside a packaged binary.
    """
    package = __name__.rpartition(".")[0]
    return resources.files(package).joinpath(_PROMPT_RESOURCE_NAME).read_text()


def render_report_lines(report: InvestigationReport | None) -> list[str]:
    """Render the decision and everything backing it, for the run log.

    The appendix is left out: it reaches the everpaste through the transcript,
    and the run log wants the decision rather than the narrative.
    """
    if report is None:
        return [_BLOCK_HEADER, _INDENT + _NO_REPORT]
    lines: list[str] = [_BLOCK_HEADER, f"{_INDENT}{report.headline.strip()}", ""]
    lines.append(f"{_INDENT}Do next: {report.recommended_action.strip()}")
    lines.append("")
    lines.extend(_list_lines("Prior art", report.prior_art or [_NO_PRIOR_ART]))
    lines.append("")
    lines.append(f"{_INDENT}Findings:")
    if not report.findings:
        lines.append(f"{_FIELD_INDENT}- {_NO_FINDINGS}")
    for rank, finding in enumerate(report.findings, start=1):
        lines.extend(_finding_lines(rank, finding))
    lines.extend(_list_lines("Open leads", report.open_leads))
    return lines


def render_headline(report: InvestigationReport | None) -> str:
    """The one line compact listings carry. Empty when there is no report."""
    if report is None:
        return ""
    return report.headline.strip()


def _finding_lines(rank: int, finding: Finding) -> list[str]:
    lines = [
        f"{_INDENT}{rank}. {finding.claim}",
        f"{_FIELD_INDENT}ref:    {finding.referent}",
    ]
    if finding.reproduce is not None:
        lines.extend(_reproduce_lines(finding.reproduce))
    lines.append("")
    return lines


def _reproduce_lines(reproduce: Reproduce) -> list[str]:
    return [
        f"{_FIELD_INDENT}repro:  [{reproduce.host}] {reproduce.command}",
        f"{_FIELD_INDENT}expect: {reproduce.expect}",
    ]


def _list_lines(label: str, values: list[str]) -> list[str]:
    if not values:
        return []
    return [f"{_INDENT}{label}:", *(f"{_FIELD_INDENT}- {value}" for value in values)]
