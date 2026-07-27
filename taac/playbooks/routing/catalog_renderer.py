# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

from taac.playbooks.routing.catalog import (
    CatalogEntry,
    CatalogValidationError,
    load_catalog_text,
    PlaybookCatalog,
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


def render_catalog(catalog: PlaybookCatalog) -> str:
    topology_by_id = {topology.id: topology for topology in catalog.topologies}
    lines = [
        f"# {catalog.suite.title}",
        "",
        "<!-- Generated from the adjacent YAML catalog. Do not edit directly. -->",
        "",
        catalog.suite.summary,
        "",
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
    lines.extend(
        _table(
            [
                "ID",
                "Test Case",
                "Playbook",
                "Gate2 Coverage",
                "Topology",
                "Enforcement",
            ],
            (
                (
                    entry.id,
                    entry.title,
                    f"`{entry.playbook_name}`",
                    _requirement_label(entry),
                    f"`{entry.required_topology}`",
                    entry.enforcement,
                )
                for entry in catalog.entries
            ),
        )
    )

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

    lines.extend(["## Test Cases", ""])
    for category in catalog.categories:
        lines.extend([f"### {category.title}", ""])
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
                    f"#### {entry.id}: {entry.title}",
                    "",
                    f"- **Playbook:** `{entry.playbook_name}`",
                    f"- **Factory:** `{entry.factory_name}`",
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
