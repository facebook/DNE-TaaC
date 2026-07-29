# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

from taac.playbooks.routing.catalog import (
    CatalogEntry,
    CatalogValidationError,
    EntryValidation,
    load_catalog_text,
    PlaybookCatalog,
    ValidationChain,
    ValidationPhase,
)


def _escape_table_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _table(headers: Sequence[str], rows: Iterable[Sequence[str]]) -> list[str]:
    result = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _header in headers) + " |",
    ]
    result.extend(
        "| " + " | ".join(_escape_table_cell(value) for value in row) + " |"
        for row in rows
    )
    return result


def _bullets(values: Iterable[str]) -> list[str]:
    return [f"- {value}" for value in values]


def _requirement_label(entry: CatalogEntry) -> str:
    return ", ".join(
        f"{requirement.id} ({requirement.role})" for requirement in entry.requirements
    )


def _validation_coverage_status(validation: EntryValidation) -> str:
    coverages = {mapping.coverage for mapping in validation.spec_vs_implemented}
    if coverages <= {"implemented", "not_applicable"}:
        return "Complete"
    if coverages.isdisjoint({"implemented", "partial"}):
        return "Missing"
    return "Partial"


def _validation_remaining_gap(validation: EntryValidation) -> str:
    gaps = dict.fromkeys(
        mapping.gap
        for mapping in validation.spec_vs_implemented
        if mapping.coverage not in {"implemented", "not_applicable"} and mapping.gap
    )
    return " ".join(gaps) or "None"


def _render_validation(
    validation: EntryValidation,
    chain: ValidationChain,
    phase_by_id: dict[str, ValidationPhase],
) -> list[str]:
    profile = f"`CheckProfile.{chain.check_profile}`" if chain.check_profile else "None"
    lines = [
        "**Outcome validation traceability**",
        "",
        f"- **Health-check chain:** `{chain.id}`",
        f"- **Check profile:** {profile}",
        f"- **Implementation:** `{chain.implementation}`",
        "",
        "The chain below contains only playbook-level health checks. Trigger, step, task, and periodic-monitor assertions are not counted as health-check coverage.",
        "",
    ]
    if chain.phases:
        lines.extend(
            _table(
                ["Phase", "Chain ID", "Implemented Health Checks", "Notes"],
                (
                    (
                        phase_by_id[phase_id].phase,
                        f"`{phase_id}`",
                        ", ".join(
                            f"`{healthcheck}`"
                            for healthcheck in phase_by_id[phase_id].healthchecks
                        ),
                        phase_by_id[phase_id].notes,
                    )
                    for phase_id in chain.phases
                ),
            )
        )
    else:
        lines.append("No playbook-level health-check chain is implemented.")
    lines.extend(["", "**Specification vs. implemented health checks**", ""])
    lines.extend(
        _table(
            ["Required Validation", "Implemented By", "Coverage", "Gap"],
            (
                (
                    mapping.spec,
                    ", ".join(f"`{item}`" for item in mapping.implemented_by) or "None",
                    mapping.coverage,
                    mapping.gap or "None",
                )
                for mapping in validation.spec_vs_implemented
            ),
        )
    )
    lines.extend(["", "**Validations outside the health-check chain**", ""])
    if validation.non_chain_validations:
        lines.extend(_bullets(validation.non_chain_validations))
    else:
        lines.append("- None.")
    return lines


def render_catalog(catalog: PlaybookCatalog) -> str:
    topology_by_id = {topology.id: topology for topology in catalog.topologies}
    phase_by_id = {phase.id: phase for phase in catalog.validation_phases}
    chain_by_id = {chain.id: chain for chain in catalog.validation_chains}
    show_implementation_status = any(
        entry.implementation_status != "implemented" for entry in catalog.entries
    )
    lines = [
        f"# {catalog.suite.title}",
        "",
        "<!-- Generated from the adjacent YAML catalog. Do not edit directly. -->",
        "",
        catalog.suite.summary,
        "",
        f"- **Type:** `{catalog.suite.type}`",
        f"- **Owner:** `{catalog.suite.owner}`",
        f"- **Playbook module:** `{catalog.suite.playbook_module}`",
        "",
        "## Sources",
        "",
    ]
    lines.extend(f"- [{source.title}]({source.url})" for source in catalog.sources)

    lines.extend(["", "## Required Topologies", ""])
    lines.extend(
        _table(
            ["ID", "Status", "Artifact", "Description"],
            (
                (
                    f"`{topology.id}`",
                    topology.status,
                    f"`{topology.artifact}`" if topology.artifact else "Not modeled",
                    topology.description,
                )
                for topology in catalog.topologies
            ),
        )
    )

    lines.extend(["", "## Catalog at a Glance", ""])
    glance_headers = ["ID", "Test Case", "Playbook"]
    if show_implementation_status:
        glance_headers.append("Status")
    glance_headers.extend(["Requirement Coverage", "Topology", "Enforcement"])
    glance_rows = []
    for entry in catalog.entries:
        row = [entry.id, entry.title, f"`{entry.playbook_name}`"]
        if show_implementation_status:
            row.append(entry.implementation_status)
        row.extend(
            [
                _requirement_label(entry),
                f"`{entry.required_topology}`",
                entry.enforcement,
            ]
        )
        glance_rows.append(row)
    lines.extend(_table(glance_headers, glance_rows))

    lines.extend(["", "## Requirement Coverage", ""])
    coverage_rows = []
    for requirement_id in catalog.suite.required_requirements:
        matching = [
            (entry, requirement)
            for entry in catalog.entries
            for requirement in entry.requirements
            if requirement.id == requirement_id
        ]
        coverage_rows.append(
            (
                requirement_id,
                ", ".join(
                    f"{entry.id} ({requirement.role})"
                    for entry, requirement in matching
                ),
                " ".join(requirement.coverage for _entry, requirement in matching),
            )
        )
    lines.extend(
        _table(["Requirement", "Catalog Cases", "Current Coverage"], coverage_rows)
    )

    lines.extend(["", "## Outcome Validation Coverage", ""])
    lines.extend(
        [
            "This summary compares catalog-required blocking signals with the playbook-level health-check chains currently implemented. Step-local assertions and periodic monitors are reported separately and never upgrade health-check coverage.",
            "",
        ]
    )
    lines.extend(
        _table(
            ["ID", "Test Case", "Health-check Coverage", "Remaining Gap"],
            (
                (
                    entry.id,
                    entry.title,
                    _validation_coverage_status(entry.validation),
                    _validation_remaining_gap(entry.validation),
                )
                for entry in catalog.entries
            ),
        )
    )

    if catalog.coverage_notes:
        lines.extend(["", "## Coverage Notes", ""])
        for note in catalog.coverage_notes:
            lines.extend(
                [
                    f"### {note.title}",
                    "",
                    note.summary,
                    "",
                    "**Asserted**",
                    "",
                    *_bullets(note.asserted),
                    "",
                    "**Exercised but not feature-complete**",
                    "",
                    *_bullets(note.exercised),
                    "",
                    "**Gaps**",
                    "",
                    *_bullets(note.gaps),
                    "",
                ]
            )

    lines.extend(["# Test Cases", ""])
    for category in catalog.categories:
        lines.extend([f"## {category.title}", ""])
        for entry in catalog.entries:
            if entry.category != category.id:
                continue
            topology = topology_by_id.get(entry.required_topology)
            if topology is None:
                raise CatalogValidationError(
                    f"{entry.id} references unknown topology "
                    f"{entry.required_topology!r}"
                )
            topology_artifact = (
                f"`{topology.artifact}`"
                if topology.artifact is not None
                else f"`{topology.id}` (legacy; no artifact yet)"
            )
            lines.extend(
                [
                    f"### {entry.id}: {entry.title}",
                    "",
                    f"- **Playbook:** `{entry.playbook_name}`",
                    f"- **Factory:** `{entry.factory_name}`",
                    *(
                        [f"- **Implementation status:** {entry.implementation_status}"]
                        if show_implementation_status
                        else []
                    ),
                    f"- **Requirements:** {_requirement_label(entry)}",
                    f"- **Required topology:** {topology_artifact}",
                    f"- **Cadence:** {entry.cadence}",
                    f"- **Enforcement:** {entry.enforcement}",
                    "",
                    f"**Purpose:** {entry.purpose}",
                    "",
                    f"**Stimulus:** {entry.stimulus}",
                    "",
                    f"**Scale:** {entry.scale}",
                    "",
                    "**Blocking signals**",
                    "",
                    *_bullets(entry.blocking_signals),
                    "",
                    *_render_validation(
                        entry.validation,
                        chain_by_id[entry.validation.chain],
                        phase_by_id,
                    ),
                    "",
                    f"**Expected runtime:** {entry.expected_runtime}",
                    "",
                    "**Primary triage signals**",
                    "",
                    *_bullets(entry.triage_signals),
                    "",
                    "**Artifacts**",
                    "",
                    *_bullets(entry.artifacts),
                    "",
                    f"**Qualification difference:** {entry.qualification_delta}",
                    "",
                ]
            )

    return "\n".join(lines).rstrip() + "\n"


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render a TAAC playbook YAML catalog as Markdown."
    )
    parser.add_argument("catalog", type=Path, help="Input YAML catalog")
    parser.add_argument("output", type=Path, help="Generated Markdown output")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail instead of writing when the output is missing or stale",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    catalog = load_catalog_text(
        args.catalog.read_text(encoding="utf-8"), source=str(args.catalog)
    )
    rendered = render_catalog(catalog)
    if args.check:
        current = (
            args.output.read_text(encoding="utf-8") if args.output.exists() else None
        )
        if current != rendered:
            print(
                f"{args.output} is stale; regenerate it from {args.catalog}",
                file=sys.stderr,
            )
            return 1
        return 0

    args.output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
