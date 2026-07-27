# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

from __future__ import annotations

import dataclasses
import importlib.resources
import re
from collections.abc import Mapping

import yaml


_CATALOG_ID_PATTERN = re.compile(r"CICD-(\d{2})")
_REQUIREMENT_ID_PATTERN = re.compile(r"G2-(\d+)")
_COVERAGE_ROLES = frozenset({"direct", "proxy", "supplemental"})
_ENFORCEMENT_MODES = frozenset({"blocking", "calibrating", "informational"})
_TOPOLOGY_STATUSES = frozenset({"modeled", "legacy"})


class CatalogValidationError(ValueError):
    pass


@dataclasses.dataclass(frozen=True)
class CatalogSuite:
    id: str
    title: str
    owner: str
    summary: str
    playbook_module: str
    required_requirements: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class CatalogSource:
    id: str
    title: str
    url: str


@dataclasses.dataclass(frozen=True)
class CatalogCategory:
    id: str
    title: str


@dataclasses.dataclass(frozen=True)
class CatalogTopology:
    id: str
    status: str
    artifact: str | None
    description: str


@dataclasses.dataclass(frozen=True)
class CatalogCoverageNote:
    requirement: str
    title: str
    summary: str
    asserted: tuple[str, ...]
    exercised: tuple[str, ...]
    gaps: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class RequirementCoverage:
    id: str
    role: str
    coverage: str


@dataclasses.dataclass(frozen=True)
class CatalogEntry:
    id: str
    title: str
    category: str
    playbook_name: str
    requirements: tuple[RequirementCoverage, ...]
    required_topology: str
    purpose: str
    stimulus: str
    scale: str
    blocking_signals: tuple[str, ...]
    expected_runtime: str
    cadence: str
    enforcement: str
    triage_signals: tuple[str, ...]
    artifacts: tuple[str, ...]
    qualification_delta: str

    @property
    def factory_name(self) -> str:
        return f"get_{self.playbook_name}"


@dataclasses.dataclass(frozen=True)
class PlaybookCatalog:
    schema_version: int
    suite: CatalogSuite
    sources: tuple[CatalogSource, ...]
    coverage_notes: tuple[CatalogCoverageNote, ...]
    categories: tuple[CatalogCategory, ...]
    topologies: tuple[CatalogTopology, ...]
    entries: tuple[CatalogEntry, ...]

    def entry_by_playbook_name(self) -> dict[str, CatalogEntry]:
        return {entry.playbook_name: entry for entry in self.entries}


def _mapping(value: object, location: str) -> Mapping[str, object]:
    if not isinstance(value, dict) or not all(
        isinstance(key, str) for key in value.keys()
    ):
        raise CatalogValidationError(f"{location} must be a string-keyed mapping")
    return value


def _sequence(value: object, location: str) -> list[object]:
    if not isinstance(value, list):
        raise CatalogValidationError(f"{location} must be a list")
    return value


def _string(value: object, location: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CatalogValidationError(f"{location} must be a non-empty string")
    return value.strip()


def _optional_string(value: object, location: str) -> str | None:
    if value is None:
        return None
    return _string(value, location)


def _string_list(value: object, location: str) -> tuple[str, ...]:
    values = _sequence(value, location)
    result = tuple(
        _string(item, f"{location}[{index}]") for index, item in enumerate(values)
    )
    if not result:
        raise CatalogValidationError(f"{location} must not be empty")
    return result


def _check_keys(
    value: Mapping[str, object],
    location: str,
    expected: frozenset[str],
) -> None:
    actual = frozenset(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise CatalogValidationError(
            f"{location} has invalid fields; missing={missing}, extra={extra}"
        )


def _unique(values: list[str], location: str) -> None:
    duplicates = sorted({value for value in values if values.count(value) > 1})
    if duplicates:
        raise CatalogValidationError(f"{location} contains duplicates: {duplicates}")


def _parse_suite(value: object) -> CatalogSuite:
    mapping = _mapping(value, "suite")
    _check_keys(
        mapping,
        "suite",
        frozenset(
            {
                "id",
                "title",
                "owner",
                "summary",
                "playbook_module",
                "required_requirements",
            }
        ),
    )
    requirements = _string_list(
        mapping["required_requirements"], "suite.required_requirements"
    )
    _unique(list(requirements), "suite.required_requirements")
    for requirement in requirements:
        if _REQUIREMENT_ID_PATTERN.fullmatch(requirement) is None:
            raise CatalogValidationError(
                f"suite.required_requirements has invalid ID {requirement!r}"
            )
    return CatalogSuite(
        id=_string(mapping["id"], "suite.id"),
        title=_string(mapping["title"], "suite.title"),
        owner=_string(mapping["owner"], "suite.owner"),
        summary=_string(mapping["summary"], "suite.summary"),
        playbook_module=_string(mapping["playbook_module"], "suite.playbook_module"),
        required_requirements=requirements,
    )


def _parse_sources(value: object) -> tuple[CatalogSource, ...]:
    result = []
    for index, item in enumerate(_sequence(value, "sources")):
        location = f"sources[{index}]"
        mapping = _mapping(item, location)
        _check_keys(mapping, location, frozenset({"id", "title", "url"}))
        result.append(
            CatalogSource(
                id=_string(mapping["id"], f"{location}.id"),
                title=_string(mapping["title"], f"{location}.title"),
                url=_string(mapping["url"], f"{location}.url"),
            )
        )
    if not result:
        raise CatalogValidationError("sources must not be empty")
    _unique([source.id for source in result], "source IDs")
    return tuple(result)


def _parse_categories(value: object) -> tuple[CatalogCategory, ...]:
    result = []
    for index, item in enumerate(_sequence(value, "categories")):
        location = f"categories[{index}]"
        mapping = _mapping(item, location)
        _check_keys(mapping, location, frozenset({"id", "title"}))
        result.append(
            CatalogCategory(
                id=_string(mapping["id"], f"{location}.id"),
                title=_string(mapping["title"], f"{location}.title"),
            )
        )
    if not result:
        raise CatalogValidationError("categories must not be empty")
    _unique([category.id for category in result], "category IDs")
    return tuple(result)


def _parse_coverage_notes(value: object) -> tuple[CatalogCoverageNote, ...]:
    result = []
    for index, item in enumerate(_sequence(value, "coverage_notes")):
        location = f"coverage_notes[{index}]"
        mapping = _mapping(item, location)
        _check_keys(
            mapping,
            location,
            frozenset(
                {"requirement", "title", "summary", "asserted", "exercised", "gaps"}
            ),
        )
        requirement = _string(mapping["requirement"], f"{location}.requirement")
        if _REQUIREMENT_ID_PATTERN.fullmatch(requirement) is None:
            raise CatalogValidationError(
                f"{location}.requirement has invalid ID {requirement!r}"
            )
        result.append(
            CatalogCoverageNote(
                requirement=requirement,
                title=_string(mapping["title"], f"{location}.title"),
                summary=_string(mapping["summary"], f"{location}.summary"),
                asserted=_string_list(mapping["asserted"], f"{location}.asserted"),
                exercised=_string_list(mapping["exercised"], f"{location}.exercised"),
                gaps=_string_list(mapping["gaps"], f"{location}.gaps"),
            )
        )
    _unique([note.requirement for note in result], "coverage-note requirements")
    return tuple(result)


def _parse_topologies(value: object) -> tuple[CatalogTopology, ...]:
    result = []
    for index, item in enumerate(_sequence(value, "topologies")):
        location = f"topologies[{index}]"
        mapping = _mapping(item, location)
        _check_keys(
            mapping,
            location,
            frozenset({"id", "status", "artifact", "description"}),
        )
        status = _string(mapping["status"], f"{location}.status")
        if status not in _TOPOLOGY_STATUSES:
            raise CatalogValidationError(
                f"{location}.status must be one of {sorted(_TOPOLOGY_STATUSES)}"
            )
        artifact = _optional_string(mapping["artifact"], f"{location}.artifact")
        if status == "modeled" and artifact is None:
            raise CatalogValidationError(
                f"{location}.artifact is required for a modeled topology"
            )
        result.append(
            CatalogTopology(
                id=_string(mapping["id"], f"{location}.id"),
                status=status,
                artifact=artifact,
                description=_string(mapping["description"], f"{location}.description"),
            )
        )
    if not result:
        raise CatalogValidationError("topologies must not be empty")
    _unique([topology.id for topology in result], "topology IDs")
    return tuple(result)


def _parse_requirements(
    value: object, location: str
) -> tuple[RequirementCoverage, ...]:
    result = []
    for index, item in enumerate(_sequence(value, location)):
        item_location = f"{location}[{index}]"
        mapping = _mapping(item, item_location)
        _check_keys(mapping, item_location, frozenset({"id", "role", "coverage"}))
        requirement_id = _string(mapping["id"], f"{item_location}.id")
        if _REQUIREMENT_ID_PATTERN.fullmatch(requirement_id) is None:
            raise CatalogValidationError(
                f"{item_location}.id has invalid requirement ID {requirement_id!r}"
            )
        role = _string(mapping["role"], f"{item_location}.role")
        if role not in _COVERAGE_ROLES:
            raise CatalogValidationError(
                f"{item_location}.role must be one of {sorted(_COVERAGE_ROLES)}"
            )
        result.append(
            RequirementCoverage(
                id=requirement_id,
                role=role,
                coverage=_string(mapping["coverage"], f"{item_location}.coverage"),
            )
        )
    if not result:
        raise CatalogValidationError(f"{location} must not be empty")
    _unique([requirement.id for requirement in result], f"{location} IDs")
    return tuple(result)


def _parse_entries(value: object) -> tuple[CatalogEntry, ...]:
    expected_fields = frozenset(
        {
            "id",
            "title",
            "category",
            "playbook_name",
            "requirements",
            "required_topology",
            "purpose",
            "stimulus",
            "scale",
            "blocking_signals",
            "expected_runtime",
            "cadence",
            "enforcement",
            "triage_signals",
            "artifacts",
            "qualification_delta",
        }
    )
    result = []
    for index, item in enumerate(_sequence(value, "entries")):
        location = f"entries[{index}]"
        mapping = _mapping(item, location)
        _check_keys(mapping, location, expected_fields)
        catalog_id = _string(mapping["id"], f"{location}.id")
        match = _CATALOG_ID_PATTERN.fullmatch(catalog_id)
        expected_number = index + 1
        if match is None or int(match.group(1)) != expected_number:
            raise CatalogValidationError(
                f"{location}.id must be CICD-{expected_number:02d}, got {catalog_id!r}"
            )
        playbook_name = _string(mapping["playbook_name"], f"{location}.playbook_name")
        if re.fullmatch(r"[a-z0-9_]+_playbook", playbook_name) is None:
            raise CatalogValidationError(
                f"{location}.playbook_name has invalid format {playbook_name!r}"
            )
        enforcement = _string(mapping["enforcement"], f"{location}.enforcement")
        if enforcement not in _ENFORCEMENT_MODES:
            raise CatalogValidationError(
                f"{location}.enforcement must be one of {sorted(_ENFORCEMENT_MODES)}"
            )
        result.append(
            CatalogEntry(
                id=catalog_id,
                title=_string(mapping["title"], f"{location}.title"),
                category=_string(mapping["category"], f"{location}.category"),
                playbook_name=playbook_name,
                requirements=_parse_requirements(
                    mapping["requirements"], f"{location}.requirements"
                ),
                required_topology=_string(
                    mapping["required_topology"], f"{location}.required_topology"
                ),
                purpose=_string(mapping["purpose"], f"{location}.purpose"),
                stimulus=_string(mapping["stimulus"], f"{location}.stimulus"),
                scale=_string(mapping["scale"], f"{location}.scale"),
                blocking_signals=_string_list(
                    mapping["blocking_signals"], f"{location}.blocking_signals"
                ),
                expected_runtime=_string(
                    mapping["expected_runtime"], f"{location}.expected_runtime"
                ),
                cadence=_string(mapping["cadence"], f"{location}.cadence"),
                enforcement=enforcement,
                triage_signals=_string_list(
                    mapping["triage_signals"], f"{location}.triage_signals"
                ),
                artifacts=_string_list(mapping["artifacts"], f"{location}.artifacts"),
                qualification_delta=_string(
                    mapping["qualification_delta"], f"{location}.qualification_delta"
                ),
            )
        )
    if not result:
        raise CatalogValidationError("entries must not be empty")
    _unique([entry.id for entry in result], "catalog IDs")
    _unique([entry.title for entry in result], "catalog titles")
    _unique([entry.playbook_name for entry in result], "playbook names")
    return tuple(result)


def load_catalog_text(text: str, *, source: str = "<memory>") -> PlaybookCatalog:
    try:
        root = _mapping(yaml.safe_load(text), source)
    except yaml.YAMLError as error:
        raise CatalogValidationError(f"{source} is not valid YAML: {error}") from error
    _check_keys(
        root,
        source,
        frozenset(
            {
                "schema_version",
                "suite",
                "sources",
                "coverage_notes",
                "categories",
                "topologies",
                "entries",
            }
        ),
    )
    schema_version = root["schema_version"]
    if schema_version != 1:
        raise CatalogValidationError(
            f"{source}.schema_version must be 1, got {schema_version!r}"
        )

    suite = _parse_suite(root["suite"])
    sources = _parse_sources(root["sources"])
    coverage_notes = _parse_coverage_notes(root["coverage_notes"])
    categories = _parse_categories(root["categories"])
    topologies = _parse_topologies(root["topologies"])
    entries = _parse_entries(root["entries"])

    category_ids = {category.id for category in categories}
    topology_ids = {topology.id for topology in topologies}
    covered_requirements = {
        requirement.id for entry in entries for requirement in entry.requirements
    }
    unknown_coverage_notes = sorted(
        {note.requirement for note in coverage_notes} - set(suite.required_requirements)
    )
    if unknown_coverage_notes:
        raise CatalogValidationError(
            f"coverage notes reference requirements outside suite scope: "
            f"{unknown_coverage_notes}"
        )
    for entry in entries:
        if entry.category not in category_ids:
            raise CatalogValidationError(
                f"{entry.id}.category references unknown category {entry.category!r}"
            )
        if entry.required_topology not in topology_ids:
            raise CatalogValidationError(
                f"{entry.id}.required_topology references unknown topology "
                f"{entry.required_topology!r}"
            )
    missing_requirements = sorted(
        set(suite.required_requirements) - covered_requirements,
        key=lambda requirement: int(requirement.removeprefix("G2-")),
    )
    if missing_requirements:
        raise CatalogValidationError(
            f"catalog does not cover required requirements: {missing_requirements}"
        )

    return PlaybookCatalog(
        schema_version=1,
        suite=suite,
        sources=sources,
        coverage_notes=coverage_notes,
        categories=categories,
        topologies=topologies,
        entries=entries,
    )


def load_packaged_catalog(package: str, filename: str) -> PlaybookCatalog:
    try:
        resource = importlib.resources.files(package).joinpath(filename)
        text = resource.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise CatalogValidationError(f"{filename}: {error}") from error
    return load_catalog_text(text, source=filename)
