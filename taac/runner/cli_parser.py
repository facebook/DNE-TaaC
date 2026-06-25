# pyre-unsafe

"""
OSS CLI Argument Parser

Defines the command-line interface for the OSS TAAC entry point.
"""

import argparse
from typing import List, Optional


def create_argument_parser() -> argparse.ArgumentParser:
    """
    Create CLI argument parser for OSS TAAC entry point.

    Returns:
        Configured argument parser
    """
    parser = argparse.ArgumentParser(
        prog="oss_taac",
        description="OSS TAAC Test Runner",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    # Required arguments
    parser.add_argument(
        "--test-configs",
        nargs="+",
        required=True,
        help="Path(s) to Python test config files",
    )

    # Topology fixtures. Exposed as CLI flags rather than env vars so a user
    # running the entry point against a live environment doesn't need to
    # script `export TAAC_*_PATH=...` around every invocation. main() sets
    # the corresponding env vars before importing taac so the topology
    # loader (which @memoize_forever-caches on first read) lands on the
    # right paths.
    parser.add_argument(
        "--device-info-csv",
        help=(
            "Path to a device_info.csv file. Sets TAAC_DEVICE_INFO_PATH "
            "so the OSS topology loader picks up your environment's "
            "device list (hostname → OS / role / vendor)."
        ),
    )
    parser.add_argument(
        "--circuit-info-csv",
        help=(
            "Path to a circuit_info.csv file. Sets TAAC_CIRCUIT_INFO_PATH "
            "so the OSS topology loader picks up your environment's links."
        ),
    )

    # Device selection
    parser.add_argument(
        "--dut",
        "--device",
        dest="duts",
        nargs="+",
        required=True,
        help="Device(s) under test (hostname or IP)",
    )

    # Playbook selection
    parser.add_argument(
        "--playbook",
        dest="playbooks",
        nargs="+",
        help="Specific playbook(s) to run (default: all enabled playbooks)",
    )

    # IXIA configuration
    # Note: the design spec lists this as required, but we make it optional
    # to support non-traffic test modes (--list-tests, --dry-run,
    # validation-only tests). Runtime validation will check if IXIA is
    # needed based on the test config.
    parser.add_argument(
        "--ixia-api-server",
        help="IP address of IXIA chassis (required for tests using IXIA traffic generation)",
    )
    parser.add_argument(
        "--ixia-session-id",
        type=int,
        help="Reuse existing IXIA session ID",
    )
    parser.add_argument(
        "--skip-ixia-setup",
        action="store_true",
        help="Skip IXIA initialization",
    )
    parser.add_argument(
        "--skip-ixia-cleanup",
        action="store_true",
        help="Skip IXIA teardown",
    )

    # Test execution options
    parser.add_argument(
        "--skip-testbed-isolation",
        action="store_true",
        help="Skip testbed isolation checks",
    )
    parser.add_argument(
        "--skip-setup-tasks",
        action="store_true",
        help="Skip setup tasks",
    )
    parser.add_argument(
        "--skip-teardown-tasks",
        action="store_true",
        help="Skip teardown tasks",
    )
    parser.add_argument(
        "--skip-post-setup-wait",
        action="store_true",
        help=(
            "Skip the 180s interface-stabilization sleep after testbed "
            "setup. Useful against pre-existing devices that aren't being "
            "rebooted (default: False, i.e. sleep)"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate configuration without executing tests",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=3600,
        help="Global timeout in seconds (default: 3600 = 1 hour)",
    )
    parser.add_argument(
        "--retry",
        type=int,
        default=0,
        help="Number of retries for transient failures",
    )

    # Logging options
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Logging level",
    )
    parser.add_argument(
        "--log-file",
        help="Path to log file (default: auto-generated)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging (shortcut for --log-level DEBUG)",
    )

    # Output options
    parser.add_argument(
        "--output-format",
        choices=["json", "junit", "text"],
        default="text",
        help="Output format for test results (default: text)",
    )
    parser.add_argument(
        "--json-output",
        help="Path to write JSON results (default: taac_results.json)",
    )
    parser.add_argument(
        "--junit-output",
        help="Path to write JUnit XML results (default: taac_results.xml)",
    )
    parser.add_argument(
        "--list-tests",
        action="store_true",
        help="List available tests and exit",
    )

    return parser


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """
    Parse command line arguments.

    Args:
        argv: Command line arguments (default: sys.argv)

    Returns:
        Parsed arguments
    """
    parser = create_argument_parser()
    return parser.parse_args(argv)
