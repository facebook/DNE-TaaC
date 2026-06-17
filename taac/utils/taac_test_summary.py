# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
import enum
import logging
import time
import typing as t
from contextlib import contextmanager
from dataclasses import dataclass, field

from neteng.test_infra.dne.taac.utils.common import async_everpaste_str, async_get_fburl
from taac.utils.taac_log_formatter import (
    format_duration,
    log_phase_end,
    log_phase_start,
)


class SectionStatus(enum.Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    SKIPPED = "SKIPPED"
    IN_PROGRESS = "IN_PROGRESS"


@dataclass
class SectionResult:
    name: str
    status: SectionStatus = SectionStatus.IN_PROGRESS
    duration_secs: float = 0.0
    log_lines: t.List[str] = field(default_factory=list)
    everpaste_url: str = ""
    error_message: str = ""
    indent_level: int = 0
    start_time: float = 0.0


class _SectionLogHandler(logging.Handler):
    """Logging handler that captures messages into per-section buffers and a global buffer."""

    def __init__(self) -> None:
        super().__init__()
        self._all_logs: t.List[str] = []
        self._active_sections: t.List[t.List[str]] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            self._all_logs.append(msg)
            for section_logs in self._active_sections:
                section_logs.append(msg)
        except Exception:
            self.handleError(record)

    def add_section(self, log_lines: t.List[str]) -> None:
        self._active_sections.append(log_lines)

    def remove_section(self, log_lines: t.List[str]) -> None:
        if log_lines in self._active_sections:
            self._active_sections.remove(log_lines)

    def get_all_logs(self) -> str:
        return "\n".join(self._all_logs)


class TaacTestSummary:
    """
    Tracks test execution sections with per-section log capture, pass/fail status,
    timing, and everpaste URL generation.

    Usage:
        summary = TaacTestSummary(logger)

        # Option 1: Context manager (replaces timed_phase for tracked phases)
        with summary.tracked_section("Setup Phase"):
            do_setup()

        # Option 2: Explicit start/end (for complex control flow)
        section = summary.start_section("My Stage", indent_level=1)
        try:
            run_stage()
            summary.end_section(section, SectionStatus.PASS)
        except Exception as e:
            summary.end_section(section, SectionStatus.FAIL, str(e))
            raise

        # Generate and upload summary
        url = await summary.async_upload_and_log_summary()
    """

    def __init__(self, logger: t.Any = None) -> None:
        self._logger = logger
        self.sections: t.List[SectionResult] = []
        self._log_handler = _SectionLogHandler()
        self._log_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        )
        self._attached_logger: t.Optional[logging.Logger] = None
        self._attach_handler()

    def _attach_handler(self) -> None:
        """Attach the log capture handler to the underlying Python logger."""
        logger = self._logger
        if isinstance(logger, logging.Logger):
            logger.addHandler(self._log_handler)
            self._attached_logger = logger
            return
        for attr in ("logger", "_logger"):
            underlying = getattr(logger, attr, None)
            if isinstance(underlying, logging.Logger):
                underlying.addHandler(self._log_handler)
                self._attached_logger = underlying
                return
        if hasattr(logger, "addHandler"):
            logger.addHandler(self._log_handler)
            self._attached_logger = logger
            return
        root = logging.getLogger()
        root.addHandler(self._log_handler)
        self._attached_logger = root

    def cleanup(self) -> None:
        """Remove the log capture handler."""
        if self._attached_logger:
            try:
                self._attached_logger.removeHandler(self._log_handler)
            except Exception:
                pass

    def start_section(self, name: str, indent_level: int = 0) -> SectionResult:
        """Begin tracking a new section."""
        section = SectionResult(
            name=name, indent_level=indent_level, start_time=time.time()
        )
        self.sections.append(section)
        self._log_handler.add_section(section.log_lines)
        return section

    def end_section(
        self,
        section: SectionResult,
        status: SectionStatus = SectionStatus.PASS,
        error_message: str = "",
    ) -> None:
        """Finalize a section with status and duration."""
        section.duration_secs = time.time() - section.start_time
        section.status = status
        section.error_message = error_message
        self._log_handler.remove_section(section.log_lines)

    @contextmanager
    def tracked_section(
        self,
        name: str,
        indent_level: int = 0,
    ):
        """
        Context manager that tracks a section with timing, status, and log capture.
        Also logs phase start/end markers (replaces timed_phase).
        """
        section = self.start_section(name, indent_level=indent_level)
        log_phase_start(name, logger=self._logger)
        try:
            yield section
        except Exception as e:
            elapsed = time.time() - section.start_time
            log_phase_end(name, duration_secs=elapsed, logger=self._logger)
            self.end_section(section, SectionStatus.FAIL, error_message=str(e))
            raise
        else:
            elapsed = time.time() - section.start_time
            log_phase_end(name, duration_secs=elapsed, logger=self._logger)
            self.end_section(section, SectionStatus.PASS)

    async def async_upload_section_logs(self, section: SectionResult) -> str:
        """Upload a section's captured logs to everpaste."""
        if not section.log_lines:
            return ""
        header = (
            f"=== Section: {section.name} ===\n"
            f"Status: {section.status.value}\n"
            f"Duration: {format_duration(section.duration_secs)}\n"
            f"{'=' * 60}\n\n"
        )
        content = header + "\n".join(section.log_lines)
        try:
            everpaste_url = await async_everpaste_str(content)
            section.everpaste_url = await async_get_fburl(everpaste_url)
        except Exception as e:
            if self._logger:
                self._logger.error(
                    f"Failed to upload logs for section '{section.name}': {e}"
                )
            section.everpaste_url = f"Upload failed: {e}"
        return section.everpaste_url

    def _get_status_string(self, status: SectionStatus) -> str:
        """Convert a SectionStatus to its display string."""
        status_map = {
            SectionStatus.FAIL: "FAIL",
            SectionStatus.PASS: "PASS",
            SectionStatus.SKIPPED: "SKIP",
        }
        return status_map.get(status, "...")

    def _truncate_message(self, message: str, max_length: int) -> str:
        """Truncate a message to max_length, appending '...' if truncated."""
        if len(message) > max_length:
            return message[:max_length] + "..."
        return message

    def _format_section_row(self, section: SectionResult) -> t.List[str]:
        """Format a single section as table row(s) including failure reason if applicable."""
        lines = []
        indent = "  " * section.indent_level
        display_name = f"{indent}{section.name}"
        status_str = self._get_status_string(section.status)
        duration_str = (
            format_duration(section.duration_secs) if section.duration_secs > 0 else "-"
        )
        url = section.everpaste_url or "-"
        lines.append(f"  {display_name:<45} {status_str:<10} {duration_str:<15} {url}")
        if section.status == SectionStatus.FAIL and section.error_message:
            short_err = self._truncate_message(section.error_message, 80)
            lines.append(f"  {indent}  └─ REASON: {short_err}")
        return lines

    def _format_failure_details(
        self, failed_sections: t.List[SectionResult]
    ) -> t.List[str]:
        """Format the failure details section for failed sections."""
        lines = []
        lines.append("=" * 100)
        lines.append(f"{'FAILURE DETAILS':^100}")
        lines.append("=" * 100)
        lines.append("")
        for s in failed_sections:
            # pyrefly: ignore [bad-argument-type]
            lines.append(f"  ✗ {s.name}")
            # pyrefly: ignore [bad-argument-type]
            lines.append(f"    Duration: {format_duration(s.duration_secs)}")
            # pyrefly: ignore [bad-argument-type]
            lines.append(f"    Logs: {s.everpaste_url or 'N/A'}")
            if s.error_message:
                err = self._truncate_message(s.error_message, 500)
                # pyrefly: ignore [bad-argument-type]
                lines.append(f"    Error: {err}")
            lines.append("")
        # pyrefly: ignore [bad-return]
        return lines

    async def async_generate_summary(self) -> str:
        """
        Generate a summary table of all tracked sections and upload per-section logs.
        Returns the formatted summary text.
        """
        for section in self.sections:
            if section.log_lines and not section.everpaste_url:
                await self.async_upload_section_logs(section)

        lines = []
        lines.append("=" * 100)
        lines.append(f"{'TEST EXECUTION SUMMARY':^100}")
        lines.append("=" * 100)
        lines.append("")
        header = f"  {'Section':<45} {'Status':<10} {'Duration':<15} {'Logs'}"
        lines.append(header)
        lines.append("  " + "-" * 95)

        all_pass = True
        for section in self.sections:
            if section.status == SectionStatus.FAIL:
                all_pass = False
            # pyrefly: ignore [bad-argument-type]
            lines.extend(self._format_section_row(section))

        lines.append("  " + "-" * 95)
        overall = "ALL SECTIONS PASSED" if all_pass else "SOME SECTIONS FAILED"
        # pyrefly: ignore [bad-argument-type]
        lines.append(f"  Overall: {overall}")
        lines.append("")

        failed = [s for s in self.sections if s.status == SectionStatus.FAIL]
        if failed:
            # pyrefly: ignore [bad-argument-type]
            lines.extend(self._format_failure_details(failed))

        return "\n".join(lines)

    async def async_upload_and_log_summary(self) -> str:
        """
        Generate the summary, upload full logs to everpaste, log everything,
        and return the summary everpaste URL.
        """
        summary_text = await self.async_generate_summary()

        all_logs = self._log_handler.get_all_logs()
        full_logs_url = ""
        if all_logs:
            try:
                everpaste_url = await async_everpaste_str(all_logs)
                full_logs_url = await async_get_fburl(everpaste_url)
            except Exception as e:
                if self._logger:
                    self._logger.error(f"Failed to upload full logs: {e}")

        if full_logs_url:
            summary_text += f"\n  Full detailed logs: {full_logs_url}\n"

        if self._logger:
            self._logger.info(f"\n{summary_text}")

        summary_url = ""
        try:
            everpaste_url = await async_everpaste_str(summary_text)
            summary_url = await async_get_fburl(everpaste_url)
            if self._logger:
                self._logger.info(f"Test summary URL: {summary_url}")
        except Exception as e:
            if self._logger:
                self._logger.error(f"Failed to upload summary: {e}")

        return summary_url
