# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
import logging
import time
import typing as t
from contextlib import contextmanager

from taac.utils.oss_taac_lib_utils import (
    ConsoleFileLogger,
    get_root_logger,
)


SECTION_WIDTH: int = 80
SECTION_CHAR: str = "="
SUBSECTION_CHAR: str = "-"
PHASE_CHAR: str = "#"

# Log level used to suppress verbose console output while keeping file logging intact
_SUPPRESS_LEVEL: int = logging.WARNING


def log_section(
    title: str,
    logger: t.Optional[ConsoleFileLogger] = None,
    width: int = SECTION_WIDTH,
) -> None:
    """
    Log a major section header (e.g., TEST SETUP, TEST TEARDOWN).
    Renders as:
        ================================================================================
        =                            TEST CONFIG SETUP                                 =
        ================================================================================
    """
    _logger = logger or get_root_logger()
    width = max(width, len(title) + 4)
    border = SECTION_CHAR * width
    padding_total = width - len(title) - 2
    pad_left = padding_total // 2
    pad_right = padding_total - pad_left
    _logger.info(border)
    _logger.info(
        f"{SECTION_CHAR}{' ' * pad_left}{title}{' ' * pad_right}{SECTION_CHAR}"
    )
    _logger.info(border)


def log_playbook_header(
    playbook_name: str,
    device_name: str,
    logger: t.Optional[ConsoleFileLogger] = None,
    width: int = SECTION_WIDTH,
) -> None:
    """
    Log a playbook header section.
    Renders as:
        ################################################################################
        #                     PLAYBOOK: test_snake_warmboot                            #
        #                     Device: fboss153.99.snc1                                 #
        ################################################################################
    """
    _logger = logger or get_root_logger()
    title1 = f"PLAYBOOK: {playbook_name}"
    title2 = f"Device: {device_name}"
    width = max(width, max(len(title1), len(title2)) + 4)
    border = PHASE_CHAR * width

    def centered_line(text: str) -> str:
        padding_total = width - len(text) - 2
        pad_left = padding_total // 2
        pad_right = padding_total - pad_left
        return f"{PHASE_CHAR}{' ' * pad_left}{text}{' ' * pad_right}{PHASE_CHAR}"

    _logger.info(border)
    _logger.info(centered_line(title1))
    _logger.info(centered_line(title2))
    _logger.info(border)


def log_results_table(
    title: str,
    results: t.List[t.Dict[str, str]],
    logger: t.Optional[ConsoleFileLogger] = None,
) -> None:
    """
    Log a results table with columns: Check Name, Status, Message.

    Args:
        title: The title for the table section
        results: List of dicts with keys: 'check_name', 'status', 'message'
        logger: Optional logger instance

    Renders as:
        ================================================================================
        =                          POST-HEALTH CHECK RESULTS                           =
        ================================================================================
          Check Name                          Status      Message
          ---------------------------------------------------------------------------
          PORT_STATE_CHECK                    PASS
          LLDP_CHECK                          PASS
          IXIA_PACKET_LOSS_CHECK              FAIL        Packet loss > 0.01%
          ---------------------------------------------------------------------------
          Overall: 2 PASSED, 1 FAILED
    """
    _logger = logger or get_root_logger()
    if not results:
        return

    width = SECTION_WIDTH
    border = SECTION_CHAR * width
    padding_total = width - len(title) - 2
    pad_left = padding_total // 2
    pad_right = padding_total - pad_left

    _logger.info(border)
    _logger.info(
        f"{SECTION_CHAR}{' ' * pad_left}{title}{' ' * pad_right}{SECTION_CHAR}"
    )
    _logger.info(border)

    # Table header
    header = f"  {'Check Name':<35} {'Status':<10} {'Message'}"
    _logger.info(header)
    _logger.info("  " + "-" * (width - 4))

    passed = 0
    failed = 0
    for result in results:
        check_name = result.get("check_name", "Unknown")
        status = result.get("status", "UNKNOWN")
        message = result.get("message", "")
        _logger.info(f"  {check_name:<35} {status:<10} {message}")
        if status.upper() in ("PASS", "PASSED", "SUCCESS"):
            passed += 1
        else:
            failed += 1

    _logger.info("  " + "-" * (width - 4))
    overall = f"Overall: {passed} PASSED, {failed} FAILED"
    _logger.info(f"  {overall}")
    _logger.info("")


def log_subsection(
    title: str,
    logger: t.Optional[ConsoleFileLogger] = None,
    width: int = SECTION_WIDTH,
) -> None:
    """
    Log a subsection header (e.g., a playbook or step within a test).
    Renders as:
        --- Playbook: my_playbook on device01 ---
    """
    _logger = logger or get_root_logger()
    padding_total = max(0, width - len(title) - 8)
    pad_left = padding_total // 2
    pad_right = padding_total - pad_left
    _logger.info(
        f"{SUBSECTION_CHAR * 3} {' ' * pad_left}{title}{' ' * pad_right} {SUBSECTION_CHAR * 3}"
    )


def log_phase_start(
    phase: str,
    logger: t.Optional[ConsoleFileLogger] = None,
) -> None:
    """Log the start of a phase with a clear marker and timestamp."""
    _logger = logger or get_root_logger()
    _logger.info(f"[START] {phase}")


def log_phase_end(
    phase: str,
    duration_secs: t.Optional[float] = None,
    logger: t.Optional[ConsoleFileLogger] = None,
) -> None:
    """Log the end of a phase with optional duration."""
    _logger = logger or get_root_logger()
    if duration_secs is not None:
        _logger.info(f"[DONE]  {phase} (took {format_duration(duration_secs)})")
    else:
        _logger.info(f"[DONE]  {phase}")


def log_step_info(
    step_name: str,
    device_name: str,
    action: str = "Running",
    logger: t.Optional[ConsoleFileLogger] = None,
) -> None:
    """Log a step execution event in a concise, readable format."""
    _logger = logger or get_root_logger()
    _logger.info(f"  [{action}] Step: {step_name} | Device: {device_name}")


def log_health_check_info(
    check_name: str,
    status: str,
    device_name: t.Optional[str] = None,
    logger: t.Optional[ConsoleFileLogger] = None,
) -> None:
    """Log a health check result in a concise, readable format."""
    _logger = logger or get_root_logger()
    device_part = f" | Device: {device_name}" if device_name else ""
    _logger.info(f"  [HC] {check_name}: {status}{device_part}")


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


@contextmanager
def timed_phase(
    phase: str,
    logger: t.Optional[ConsoleFileLogger] = None,
):
    """Context manager that logs start/end of a phase with timing."""
    _logger = logger or get_root_logger()
    log_phase_start(phase, logger=_logger)
    start = time.time()
    try:
        yield
    finally:
        elapsed = time.time() - start
        log_phase_end(phase, duration_secs=elapsed, logger=_logger)


def log_key_value(
    key: str,
    value: t.Any,
    logger: t.Optional[ConsoleFileLogger] = None,
) -> None:
    """Log a key-value pair in a clean, aligned format."""
    _logger = logger or get_root_logger()
    _logger.info(f"  {key}: {value}")


@contextmanager
def suppress_console_logs(
    logger: t.Optional[ConsoleFileLogger] = None,
    suppress_level: int = _SUPPRESS_LEVEL,
):
    """
    Context manager to temporarily suppress console logs while keeping file logging intact.

    This is useful for suppressing verbose internal operations (like IXIA setup, device
    configuration, etc.) from the console output while still capturing them in the log file.

    The console log level is temporarily raised to `suppress_level` (default: WARNING),
    so only WARNING, ERROR, and CRITICAL messages will be shown on the console.
    All logs continue to be written to the file regardless.

    Usage:
        with suppress_console_logs(logger):
            # Verbose operations here - only WARNING+ shown on console
            do_verbose_operation()
        # After context exits, normal logging resumes

    Args:
        logger: The ConsoleFileLogger to modify. If None, uses the root logger.
        suppress_level: The log level to set on console. Default is WARNING.
    """
    _logger = logger or get_root_logger()

    # Get the current console log level
    original_level = None
    if hasattr(_logger, "_console_handler"):
        original_level = _logger._console_handler.level
        # If console is already set to DEBUG (via --debug flag), don't suppress
        if original_level > logging.DEBUG:
            _logger._console_handler.setLevel(suppress_level)

    try:
        yield
    finally:
        # Restore the original console log level
        if original_level is not None and hasattr(_logger, "_console_handler"):
            _logger._console_handler.setLevel(original_level)
