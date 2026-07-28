# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-strict

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import html
import importlib.resources
import logging
import re
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from html.parser import HTMLParser
from pathlib import Path
from typing import Protocol

import markdown
import yaml
from taac.playbooks.routing.catalog import load_catalog_text
from taac.playbooks.routing.catalog_renderer import render_catalog
from security.frameworks.python.exec.subprocess import TrustedSubprocessWithList


logger: logging.Logger = logging.getLogger(__name__)

_PACKAGE = "neteng.test_infra.dne.taac.playbooks.routing"
_DEFAULT_REGISTRY = "catalog_gdoc_sync.yaml"
_DOCUMENT_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]+")
_TAB_ID_PATTERN = re.compile(r"t\.[A-Za-z0-9_-]+")
_TARGET_ID_PATTERN = re.compile(r"[a-z][a-z0-9_]*")
_TABLE_PATTERN = re.compile(r"<table>(?P<contents>.*?)</table>", re.DOTALL)
_LIST_CLOSE_PATTERN = re.compile(r"(</(?:ol|ul)>)(?!\s*(?:<p>\s*</p>|</li>))")
_BODY_OPEN_PATTERN = re.compile(r"<body(?:\s[^>]*)?>", re.IGNORECASE)
_BODY_CLOSE_PATTERN = re.compile(r"</body>", re.IGNORECASE)
_TABLE_COLUMN_WIDTHS: dict[tuple[str, ...], str] = {
    ("ID", "Status", "Artifact", "Description"): "70,55,360,215",
    (
        "ID",
        "Test Case",
        "Playbook",
        "Gate2 Coverage",
        "Topology",
        "Enforcement",
    ): "45,105,220,90,145,95",
    ("Requirement", "Catalog Cases", "Current Coverage"): "80,180,440",
    (
        "ID",
        "Test Case",
        "Health-check Coverage",
        "Remaining Gap",
    ): "55,145,105,395",
    (
        "Phase",
        "Chain ID",
        "Implemented Health Checks",
        "Notes",
    ): "65,125,315,195",
    (
        "Required Validation",
        "Implemented By",
        "Coverage",
        "Gap",
    ): "200,145,75,280",
}


class CatalogSyncError(RuntimeError):
    pass


@dataclasses.dataclass(frozen=True)
class CatalogSyncTarget:
    id: str
    enabled: bool
    catalog: str
    markdown: str
    document_id: str
    tab_id: str
    document_mode: str


@dataclasses.dataclass(frozen=True)
class SyncResult:
    target_id: str
    status: str
    url: str


class DocsClient(Protocol):
    def fetch_ghtml(self, target: CatalogSyncTarget, destination: Path) -> None: ...

    def format_document(self, target: CatalogSyncTarget) -> None: ...

    def replace_ghtml(
        self,
        target: CatalogSyncTarget,
        source: Path,
        *,
        dry_run: bool,
    ) -> None: ...


class MetaDocsClient:
    def _run(self, args: Sequence[str], *, timeout: int = 180) -> str:
        try:
            result = TrustedSubprocessWithList.run(
                executable="meta",
                cmd_args=list(args),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise CatalogSyncError(f"meta CLI failed to run: {error}") from error
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip()
            raise CatalogSyncError(
                f"meta {' '.join(args[:2])} failed with code "
                f"{result.returncode}: {detail[:1200]}"
            )
        return result.stdout

    def fetch_ghtml(self, target: CatalogSyncTarget, destination: Path) -> None:
        self._run(
            [
                "google.docs",
                "get",
                f"--id={target.document_id}",
                "--output=ghtml",
                f"--tab-id={target.tab_id}",
                "--no-comments",
                f"--dest=file://{destination}",
            ]
        )
        if not destination.is_file():
            raise CatalogSyncError("meta google.docs get did not write GHTML")

    def format_document(self, target: CatalogSyncTarget) -> None:
        self._run(
            [
                "google.docs.format",
                "document",
                f"--id={target.document_id}",
                f"--tab-id={target.tab_id}",
                f"--document-mode={target.document_mode}",
            ]
        )

    def replace_ghtml(
        self,
        target: CatalogSyncTarget,
        source: Path,
        *,
        dry_run: bool,
    ) -> None:
        args = [
            "google.docs.advanced",
            "replace",
            f"--id={target.document_id}",
            f"--tab-id={target.tab_id}",
            f"--file=file://{source}",
        ]
        if dry_run:
            args.append("--dry-run")
        self._run(args, timeout=300)


class _GhtmlTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "p":
            self.parts.append("\n")


class _TableHeaderExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.headers: list[str] = []
        self._in_header = False
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "th":
            self._in_header = True
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._in_header:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "th" and self._in_header:
            self.headers.append("".join(self._parts).strip())
            self._in_header = False


def _string(value: object, location: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CatalogSyncError(f"{location} must be a non-empty string")
    return value.strip()


def _parse_target(raw_target: object, location: str) -> CatalogSyncTarget:
    expected_fields = {
        "id",
        "enabled",
        "catalog",
        "markdown",
        "document_id",
        "tab_id",
        "document_mode",
    }
    if not isinstance(raw_target, Mapping) or set(raw_target) != expected_fields:
        raise CatalogSyncError(f"{location} has invalid fields")
    target_id = _string(raw_target["id"], f"{location}.id")
    document_id = _string(raw_target["document_id"], f"{location}.document_id")
    tab_id = _string(raw_target["tab_id"], f"{location}.tab_id")
    enabled = raw_target["enabled"]
    if _TARGET_ID_PATTERN.fullmatch(target_id) is None:
        raise CatalogSyncError(f"{location}.id has invalid format")
    if _DOCUMENT_ID_PATTERN.fullmatch(document_id) is None:
        raise CatalogSyncError(f"{location}.document_id has invalid format")
    if _TAB_ID_PATTERN.fullmatch(tab_id) is None:
        raise CatalogSyncError(f"{location}.tab_id has invalid format")
    if not isinstance(enabled, bool):
        raise CatalogSyncError(f"{location}.enabled must be a boolean")
    document_mode = _string(raw_target["document_mode"], f"{location}.document_mode")
    if document_mode not in {"pageless", "pages"}:
        raise CatalogSyncError(f"{location}.document_mode must be pageless or pages")
    return CatalogSyncTarget(
        id=target_id,
        enabled=enabled,
        catalog=_string(raw_target["catalog"], f"{location}.catalog"),
        markdown=_string(raw_target["markdown"], f"{location}.markdown"),
        document_id=document_id,
        tab_id=tab_id,
        document_mode=document_mode,
    )


def _load_registry_text(text: str, *, source: str) -> tuple[CatalogSyncTarget, ...]:
    try:
        root = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise CatalogSyncError(f"{source} is not valid YAML: {error}") from error
    if not isinstance(root, Mapping) or set(root) != {"schema_version", "targets"}:
        raise CatalogSyncError(
            f"{source} must contain exactly schema_version and targets"
        )
    if root["schema_version"] != 1:
        raise CatalogSyncError(f"{source}.schema_version must be 1")
    raw_targets = root["targets"]
    if not isinstance(raw_targets, list) or not raw_targets:
        raise CatalogSyncError(f"{source}.targets must be a non-empty list")
    targets = tuple(
        _parse_target(raw_target, f"{source}.targets[{index}]")
        for index, raw_target in enumerate(raw_targets)
    )
    target_ids = [target.id for target in targets]
    if len(target_ids) != len(set(target_ids)):
        raise CatalogSyncError(f"{source}.targets contains duplicate IDs")
    destinations = [(target.document_id, target.tab_id) for target in targets]
    if len(destinations) != len(set(destinations)):
        raise CatalogSyncError(
            f"{source}.targets contains duplicate document and tab destinations"
        )
    return targets


def _markdown_to_ghtml(markdown_text: str, target_id: str) -> tuple[str, str]:
    body = markdown.markdown(
        markdown_text,
        extensions=["tables", "fenced_code", "sane_lists"],
        output_format="html",
    )
    body = _apply_table_width_hints(body)
    body = _LIST_CLOSE_PATTERN.sub(r"\1\n<p></p>", body)
    fingerprint = hashlib.sha256(body.encode("utf-8")).hexdigest()
    marker = html.escape(f"{target_id}@sha256:{fingerprint}")
    body = f"<p><strong>Catalog sync:</strong> <code>{marker}</code></p>\n{body}"
    return body, fingerprint


def _apply_table_width_hints(body: str) -> str:
    def add_widths(match: re.Match[str]) -> str:
        parser = _TableHeaderExtractor()
        parser.feed(match.group(0))
        parser.close()
        widths = _TABLE_COLUMN_WIDTHS.get(tuple(parser.headers))
        if widths is None:
            return match.group(0)
        return match.group(0).replace(
            "<table>", f'<table data-col-widths="{widths}">', 1
        )

    return _TABLE_PATTERN.sub(add_widths, body)


def _replace_ghtml_body(ghtml: str, body: str) -> str:
    openings = tuple(_BODY_OPEN_PATTERN.finditer(ghtml))
    closings = tuple(_BODY_CLOSE_PATTERN.finditer(ghtml))
    if (
        len(openings) != 1
        or len(closings) != 1
        or openings[0].end() > closings[0].start()
    ):
        raise CatalogSyncError("Google Docs GHTML must contain exactly one body")
    return f"{ghtml[: openings[0].end()]}\n{body}\n{ghtml[closings[0].start() :]}"


def _has_fingerprint(ghtml: str, target_id: str, fingerprint: str) -> bool:
    parser = _GhtmlTextExtractor()
    parser.feed(ghtml)
    parser.close()
    markers = re.findall(
        rf"{re.escape(target_id)}@sha256:([0-9a-f]+)",
        "".join(parser.parts),
    )
    if len(markers) > 1:
        raise CatalogSyncError(
            f"{target_id}: multiple fingerprint markers detected; "
            "manual cleanup is required"
        )
    return markers == [fingerprint]


def _target_url(target: CatalogSyncTarget) -> str:
    return (
        f"https://docs.google.com/document/d/{target.document_id}/edit"
        f"?tab={target.tab_id}"
    )


def _load_sources(target: CatalogSyncTarget, registry_path: Path | None) -> str:
    if registry_path is None:
        resources = importlib.resources.files(_PACKAGE)
        catalog_text = resources.joinpath(target.catalog).read_text(encoding="utf-8")
        markdown_text = resources.joinpath(target.markdown).read_text(encoding="utf-8")
    else:
        catalog_text = (registry_path.parent / target.catalog).read_text(
            encoding="utf-8"
        )
        markdown_text = (registry_path.parent / target.markdown).read_text(
            encoding="utf-8"
        )
    rendered = render_catalog(load_catalog_text(catalog_text, source=target.catalog))
    if markdown_text != rendered:
        raise CatalogSyncError(
            f"{target.id}: {target.markdown} is stale; render it before syncing"
        )
    return markdown_text


def _fetch_published_with_retry(
    target: CatalogSyncTarget,
    destination: Path,
    client: DocsClient,
) -> str:
    for attempt in range(2):
        try:
            client.fetch_ghtml(target, destination)
            return destination.read_text(encoding="utf-8")
        except (CatalogSyncError, OSError, UnicodeDecodeError) as error:
            if attempt == 0:
                logger.warning(
                    "catalog sync target %s verification failed; retrying: %s",
                    target.id,
                    error,
                )
                time.sleep(1)
                continue
            raise CatalogSyncError(
                f"{target.id}: verification failed after update; manual "
                f"verification is required at {_target_url(target)}: {error}"
            ) from error
    raise AssertionError("verification retry loop did not return or raise")


def sync_target(
    target: CatalogSyncTarget,
    markdown_text: str,
    client: DocsClient,
    *,
    check: bool,
    dry_run: bool,
) -> SyncResult:
    body, fingerprint = _markdown_to_ghtml(markdown_text, target.id)
    with tempfile.TemporaryDirectory(prefix=f"catalog-gdoc-{target.id}-") as directory:
        current_snapshot = Path(directory) / "current.ghtml"
        desired = Path(directory) / "desired.ghtml"
        client.fetch_ghtml(target, current_snapshot)
        current = current_snapshot.read_text(encoding="utf-8")
        if _has_fingerprint(current, target.id, fingerprint):
            return SyncResult(target.id, "current", _target_url(target))
        if check:
            return SyncResult(target.id, "stale", _target_url(target))
        desired.write_text(_replace_ghtml_body(current, body), encoding="utf-8")
        client.replace_ghtml(
            target,
            desired,
            dry_run=dry_run,
        )
        if not dry_run:
            client.format_document(target)
            published = Path(directory) / "published.ghtml"
            published_text = _fetch_published_with_retry(target, published, client)
            if not _has_fingerprint(published_text, target.id, fingerprint):
                raise CatalogSyncError(
                    f"{target.id}: published tab failed fingerprint verification"
                )
    return SyncResult(
        target.id, "dry-run" if dry_run else "updated", _target_url(target)
    )


def sync_targets(
    targets: Sequence[CatalogSyncTarget],
    load_sources: Callable[[CatalogSyncTarget], str],
    client: DocsClient,
    *,
    check: bool,
    dry_run: bool,
) -> tuple[list[SyncResult], list[str]]:
    results = []
    failures = []
    for target in targets:
        try:
            markdown_text = load_sources(target)
            results.append(
                sync_target(
                    target,
                    markdown_text,
                    client,
                    check=check,
                    dry_run=dry_run,
                )
            )
        except (CatalogSyncError, OSError, UnicodeDecodeError) as error:
            logger.exception("catalog sync target %s failed", target.id)
            failures.append(f"{target.id}: {type(error).__name__}: {error}")
    return results, failures


def _load_registry(path: Path | None) -> tuple[CatalogSyncTarget, ...]:
    if path is None:
        text = (
            importlib.resources.files(_PACKAGE)
            .joinpath(_DEFAULT_REGISTRY)
            .read_text(encoding="utf-8")
        )
        return _load_registry_text(text, source=_DEFAULT_REGISTRY)
    return _load_registry_text(path.read_text(encoding="utf-8"), source=str(path))


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync generated TAAC playbook catalogs to Google Docs tabs."
    )
    parser.add_argument("--registry", type=Path, help="Override sync registry path")
    parser.add_argument("--target", action="append", help="Sync only this target ID")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check", action="store_true", help="Exit nonzero when a remote tab is stale"
    )
    mode.add_argument(
        "--dry-run", action="store_true", help="Preview the merge without writing"
    )
    return parser.parse_args(argv)


def _sync_exit_code(results: Sequence[SyncResult], failures: Sequence[str]) -> int:
    if failures:
        return 2
    return 1 if any(result.status == "stale" for result in results) else 0


def _select_targets(
    targets: Sequence[CatalogSyncTarget], selected: set[str]
) -> tuple[CatalogSyncTarget, ...]:
    known = {target.id for target in targets}
    unknown = sorted(selected - known)
    if unknown:
        raise CatalogSyncError(f"unknown sync targets: {unknown}")
    enabled = {target.id for target in targets if target.enabled}
    disabled = sorted(selected - enabled)
    if disabled:
        raise CatalogSyncError(f"disabled sync targets: {disabled}")
    selected_targets = tuple(
        target
        for target in targets
        if target.enabled and (not selected or target.id in selected)
    )
    if not selected_targets:
        raise CatalogSyncError("no enabled catalog sync targets selected")
    return selected_targets


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        targets = _load_registry(args.registry)
        selected = set(args.target or [])
        selected_targets = _select_targets(targets, selected)
    except (CatalogSyncError, OSError, UnicodeDecodeError) as error:
        print(f"catalog sync failed: {error}", file=sys.stderr)
        return 2

    results, failures = sync_targets(
        selected_targets,
        lambda target: _load_sources(target, args.registry),
        MetaDocsClient(),
        check=args.check,
        dry_run=args.dry_run,
    )
    for result in results:
        print(f"{result.target_id}: {result.status} - {result.url}")
    for failure in failures:
        print(f"catalog sync failed: {failure}", file=sys.stderr)
    return _sync_exit_code(results, failures)


if __name__ == "__main__":
    raise SystemExit(main())
