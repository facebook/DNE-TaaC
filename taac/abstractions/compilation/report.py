# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

from taac.abstractions.compilation.model import ResourceId


class ResourceDisposition(str, Enum):
    EMITTED = "emitted"
    BORROWED = "borrowed"
    SKIPPED = "skipped"
    UNSUPPORTED = "unsupported"


class RendererLane(str, Enum):
    DUT = "dut"
    TRAFFIC_GENERATOR = "traffic_generator"
    ARTIFACT_ADAPTER = "artifact_adapter"


class RendererDisposition(str, Enum):
    NATIVE = "native"
    COMPATIBILITY_DELEGATED = "compatibility_delegated"


class CompileReportValidationError(ValueError):
    pass


class UnsupportedRequiredIntentError(ValueError):
    def __init__(self, reports: tuple[ResourceReport, ...]) -> None:
        self.reports = reports
        details = ", ".join(
            f"{report.resource_id} ({report.reason})" for report in reports
        )
        super().__init__(f"required compilation resources are unsupported: {details}")


@dataclass(frozen=True)
class ResourceReport:
    resource_id: ResourceId
    required: bool
    disposition: ResourceDisposition
    reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.resource_id, ResourceId):
            raise TypeError("resource report identity must be a ResourceId")
        if self.disposition is not ResourceDisposition.EMITTED and not _has_reason(
            self.reason
        ):
            raise ValueError(
                f"{self.disposition.value} resource {self.resource_id} requires a reason"
            )


@dataclass(frozen=True)
class RendererReport:
    lane: RendererLane
    disposition: RendererDisposition
    reason: str | None = None

    def __post_init__(self) -> None:
        if (
            self.disposition is RendererDisposition.COMPATIBILITY_DELEGATED
            and not _has_reason(self.reason)
        ):
            raise ValueError(
                f"compatibility-delegated renderer {self.lane.value} requires a reason"
            )


@dataclass(frozen=True)
class CompileReport:
    resource_reports: tuple[ResourceReport, ...] = ()
    renderer_reports: tuple[RendererReport, ...] = ()

    def __post_init__(self) -> None:
        duplicate_resources = _duplicate_resource_report_ids(self.resource_reports)
        if duplicate_resources:
            rendered = ", ".join(
                str(resource_id) for resource_id in duplicate_resources
            )
            raise CompileReportValidationError(
                f"resource report contains duplicate IDs: {rendered}"
            )
        duplicate_renderers = _duplicate_renderer_lanes(self.renderer_reports)
        if duplicate_renderers:
            rendered = ", ".join(lane.value for lane in duplicate_renderers)
            raise CompileReportValidationError(
                f"renderer report contains duplicate lanes: {rendered}"
            )

    def with_resource_reports(self, *reports: ResourceReport) -> CompileReport:
        return CompileReport(
            resource_reports=(*self.resource_reports, *reports),
            renderer_reports=self.renderer_reports,
        )

    def with_renderer_reports(self, *reports: RendererReport) -> CompileReport:
        return CompileReport(
            resource_reports=self.resource_reports,
            renderer_reports=(*self.renderer_reports, *reports),
        )

    def validate(
        self,
        expected_resource_ids: Iterable[ResourceId],
        expected_renderer_lanes: Iterable[RendererLane] = (),
    ) -> None:
        expected_resources = tuple(expected_resource_ids)
        duplicate_expected_resources = _duplicate_resource_ids(expected_resources)
        if duplicate_expected_resources:
            rendered = ", ".join(
                str(resource_id) for resource_id in duplicate_expected_resources
            )
            raise CompileReportValidationError(
                f"expected compilation resources contain duplicate IDs: {rendered}"
            )

        actual_resources = tuple(report.resource_id for report in self.resource_reports)
        missing_resources = tuple(
            resource_id
            for resource_id in expected_resources
            if resource_id not in actual_resources
        )
        unexpected_resources = tuple(
            resource_id
            for resource_id in actual_resources
            if resource_id not in expected_resources
        )
        if missing_resources or unexpected_resources:
            raise CompileReportValidationError(
                _accounting_message(
                    "resource",
                    tuple(str(resource_id) for resource_id in missing_resources),
                    tuple(str(resource_id) for resource_id in unexpected_resources),
                )
            )

        expected_renderers = tuple(expected_renderer_lanes)
        if not expected_renderers:
            return
        duplicate_expected_renderers = _duplicate_renderer_values(expected_renderers)
        if duplicate_expected_renderers:
            rendered = ", ".join(lane.value for lane in duplicate_expected_renderers)
            raise CompileReportValidationError(
                f"expected renderer lanes contain duplicates: {rendered}"
            )
        actual_renderers = tuple(report.lane for report in self.renderer_reports)
        missing_renderers = tuple(
            lane for lane in expected_renderers if lane not in actual_renderers
        )
        unexpected_renderers = tuple(
            lane for lane in actual_renderers if lane not in expected_renderers
        )
        if missing_renderers or unexpected_renderers:
            raise CompileReportValidationError(
                _accounting_message(
                    "renderer",
                    tuple(lane.value for lane in missing_renderers),
                    tuple(lane.value for lane in unexpected_renderers),
                )
            )

    def assert_renderable(
        self,
        expected_resource_ids: Iterable[ResourceId],
        expected_renderer_lanes: Iterable[RendererLane] = (),
    ) -> None:
        self.validate(expected_resource_ids, expected_renderer_lanes)
        unsupported = tuple(
            report
            for report in self.resource_reports
            if report.required and report.disposition is ResourceDisposition.UNSUPPORTED
        )
        if unsupported:
            raise UnsupportedRequiredIntentError(unsupported)


def _has_reason(reason: str | None) -> bool:
    return reason is not None and bool(reason.strip())


def _duplicate_resource_report_ids(
    reports: tuple[ResourceReport, ...],
) -> tuple[ResourceId, ...]:
    return _duplicate_resource_ids(tuple(report.resource_id for report in reports))


def _duplicate_resource_ids(
    resource_ids: tuple[ResourceId, ...],
) -> tuple[ResourceId, ...]:
    seen: set[ResourceId] = set()
    duplicates: list[ResourceId] = []
    for resource_id in resource_ids:
        if resource_id in seen and resource_id not in duplicates:
            duplicates.append(resource_id)
        seen.add(resource_id)
    return tuple(duplicates)


def _duplicate_renderer_lanes(
    reports: tuple[RendererReport, ...],
) -> tuple[RendererLane, ...]:
    return _duplicate_renderer_values(tuple(report.lane for report in reports))


def _duplicate_renderer_values(
    lanes: tuple[RendererLane, ...],
) -> tuple[RendererLane, ...]:
    seen: set[RendererLane] = set()
    duplicates: list[RendererLane] = []
    for lane in lanes:
        if lane in seen and lane not in duplicates:
            duplicates.append(lane)
        seen.add(lane)
    return tuple(duplicates)


def _accounting_message(
    subject: str,
    missing: tuple[str, ...],
    unexpected: tuple[str, ...],
) -> str:
    parts: list[str] = []
    if missing:
        parts.append(f"missing {subject}s: {', '.join(missing)}")
    if unexpected:
        parts.append(f"unexpected {subject}s: {', '.join(unexpected)}")
    return f"compile report {subject} accounting is incomplete; {'; '.join(parts)}"
