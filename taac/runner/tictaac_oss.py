# Copyright (c) Meta Platforms, Inc. and affiliates.

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, BinaryIO, TYPE_CHECKING

from taac.constants import TestCaseFailure
from taac.libs.run_result import build_run_result
from taac.utils.json_thrift_utils import (
    json_to_thrift,
    thrift_to_json,
)
from taac.utils.oss_taac_lib_utils import (
    ConsoleFileLogger,
    get_root_logger,
)
from result import Err, Ok, Result
from taac.test_as_a_config import types as taac_types
from taac.test_run_result import types as trr_types

if TYPE_CHECKING:
    from taac.libs.taac_runner import TaacRunner

STDIN_SOURCE = "-"
PROGRAM_NAME = "tictaac"
DEVICE_INFO_PATH_ENV = "TAAC_DEVICE_INFO_PATH"
CIRCUIT_INFO_PATH_ENV = "TAAC_CIRCUIT_INFO_PATH"


class _UnwrappedVersionAction(argparse.Action):
    def __init__(
        self,
        option_strings: list[str],
        dest: str,
        *,
        version: str,
        **kwargs: Any,
    ) -> None:
        super().__init__(option_strings, dest, nargs=0, **kwargs)
        self._version = version

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        _namespace: argparse.Namespace,
        _values: object,
        _option_string: str | None = None,
    ) -> None:
        print(self._version)
        parser.exit()


def _version_info() -> str:
    return json.dumps({"program": PROGRAM_NAME}, indent=4, sort_keys=True)


def _source_description(source: str) -> str:
    return "stdin" if source == STDIN_SOURCE else f"'{source}'"


def _read_test_config_json(source: str, stdin: BinaryIO) -> Result[bytes, str]:
    try:
        if source == STDIN_SOURCE:
            return Ok(stdin.read())
        return Ok(Path(source).read_bytes())
    except (OSError, ValueError) as error:
        return Err(
            f"Failed to read test config JSON from {_source_description(source)}: "
            f"{type(error).__name__}: {error}"
        )


def _load_test_config_json(
    source: str, stdin: BinaryIO
) -> Result[taac_types.TestConfig, str]:
    payload = _read_test_config_json(source, stdin)
    if isinstance(payload, Err):
        return payload
    description = _source_description(source)
    if not payload.ok_value.strip():
        return Err(f"Test config JSON from {description} is empty.")
    try:
        test_config = json_to_thrift(payload.ok_value, taac_types.TestConfig)
    except Exception as error:
        return Err(
            f"Failed to deserialize a TestConfig from {description}: "
            f"{type(error).__name__}"
        )
    if not test_config.name:
        return Err(f"TestConfig from {description} has an empty name.")
    return Ok(test_config)


def _load_taac_runner() -> type[TaacRunner]:
    # Some test configs call asyncio.run() while being imported, so the TAAC
    # runtime must finish loading before the command event loop starts.
    from taac.libs.taac_runner import TaacRunner

    return TaacRunner


class ErrorKind(Enum):
    InvalidConfig = 1
    TestFailed = 2
    NothingRan = 3
    InfraError = 128


@dataclass(frozen=True)
class TicTaacError:
    kind: ErrorKind
    msg: str


@dataclass(frozen=True)
class _Verdict:
    outcome: trr_types.RunOutcome
    exit_code: int


_PASS_VERDICT = _Verdict(trr_types.RunOutcome.PASS, 0)
_VERDICT_BY_ERROR_KIND: dict[ErrorKind, _Verdict] = {
    ErrorKind.InvalidConfig: _Verdict(trr_types.RunOutcome.INVALID_CONFIG, 1),
    ErrorKind.TestFailed: _Verdict(trr_types.RunOutcome.TEST_FAILED, 1),
    ErrorKind.NothingRan: _Verdict(trr_types.RunOutcome.NOTHING_RAN, 1),
    ErrorKind.InfraError: _Verdict(trr_types.RunOutcome.INFRA_ERROR, 128),
}

_NOTHING_RAN_MESSAGE: str = (
    "The run completed without error but executed zero playbooks. Check that "
    "the test config still has enabled playbooks and that their device "
    "filters and device_regexes still match the DUTs."
)


@dataclass(frozen=True)
class _RunOptions:
    requested_playbooks: list[str]
    requested_duts: list[str]
    skip_testbed_isolation: bool
    skip_ixia_setup: bool
    skip_fboss_rsyslog: bool
    skip_package_update: bool
    continue_on_precheck_failure: bool
    setup_only: bool
    ixia_api_server: str | None


def _select_playbooks(
    test_config: taac_types.TestConfig,
    requested_names: list[str],
    logger: ConsoleFileLogger,
) -> Result[list[taac_types.Playbook], str]:
    if not requested_names:
        logger.info(
            f"No --playbook given, selecting all {len(test_config.playbooks)} "
            f"playbooks of '{test_config.name}'"
        )
        return Ok(list(test_config.playbooks))
    playbooks_by_name = {playbook.name: playbook for playbook in test_config.playbooks}
    unknown_names = [name for name in requested_names if name not in playbooks_by_name]
    if unknown_names:
        message = (
            f"Test config '{test_config.name}' has no playbook named "
            f"{', '.join(unknown_names)}. Available playbooks: "
            f"{', '.join(sorted(playbooks_by_name))}."
        )
        logger.error(message)
        return Err(message)
    logger.info(f"Selected playbooks: {', '.join(requested_names)}")
    return Ok([playbooks_by_name[name] for name in requested_names])


def _build_runner(
    test_config: taac_types.TestConfig,
    logger: ConsoleFileLogger,
    taac_runner_type: type[TaacRunner],
    options: _RunOptions,
) -> Result[TaacRunner, str]:
    try:
        runner = taac_runner_type(
            test_config=test_config,
            logger=logger,
            skip_testbed_isolation=options.skip_testbed_isolation,
            skip_basset_reservation=False,
            skip_ixia_setup=options.skip_ixia_setup,
            skip_ixia_cleanup=False,
            skip_fboss_rsyslog=options.skip_fboss_rsyslog,
            skip_package_update=options.skip_package_update,
            desired_pkg_versions={},
            dsf_sequential_update=False,
            continue_on_precheck_failure=options.continue_on_precheck_failure,
            setup_only=options.setup_only,
            # Netcastle passes True because its own framework repeats each test
            # case. Nothing iterates above this entry point, so False is what
            # makes _get_test_case_iteration_count honor playbook.iteration.
            is_autotester_run=False,
            call_investigation_agent=False,
            ixia_api_server=options.ixia_api_server,
        )
    except Exception as e:
        message = (
            f"Failed to construct the TAAC runner for '{test_config.name}': "
            f"{type(e).__name__}: {e}"
        )
        logger.error(message)
        return Err(message)
    return Ok(runner)


async def _teardown(
    runner: TaacRunner,
    logger: ConsoleFileLogger,
) -> Result[None, TicTaacError]:
    try:
        await runner.async_test_tearDown()
        return Ok(None)
    except Exception as e:
        error = TicTaacError(
            kind=ErrorKind.InfraError,
            msg=f"Teardown failed with {type(e).__name__}: {e}",
        )
        logger.error(error.msg)
        return Err(error)


async def _run_playbooks(
    runner: TaacRunner,
    playbooks: list[taac_types.Playbook],
    duts: list[str],
    logger: ConsoleFileLogger,
) -> Result[None, TicTaacError]:
    from taac.libs.taac_runner import TestbedError

    requested: list[str | taac_types.Playbook] = list(playbooks)
    logger.info(f"Playbooks: {len(playbooks)}")
    logger.info(f"DUTs: {', '.join(duts)}")

    run_error: TicTaacError | None = None
    teardown_error: Result[None, TicTaacError] = Ok(None)
    setup_done = False
    try:
        await runner.async_test_setUp()
        setup_done = True
        await runner.run_tests(requested, duts)
    except TestbedError as e:
        run_error = TicTaacError(ErrorKind.InfraError, f"Testbed error: {e}")
    except TestCaseFailure as e:
        kind = (
            ErrorKind.InfraError
            if not setup_done or isinstance(e.__cause__, TestbedError)
            else ErrorKind.TestFailed
        )
        run_error = TicTaacError(kind, str(e))
    except Exception as e:
        kind = ErrorKind.InfraError if not setup_done else ErrorKind.TestFailed
        run_error = TicTaacError(kind, f"{type(e).__name__}: {e}")
    finally:
        teardown_error = await _teardown(runner, logger)

    if run_error is None:
        return teardown_error
    if isinstance(teardown_error, Err):
        run_error = TicTaacError(
            run_error.kind, f"{run_error.msg}; {teardown_error.err_value.msg}"
        )
    logger.error(run_error.msg)
    return Err(run_error)


def _result_without_runner(
    test_config_name: str,
    error: TicTaacError,
    duts: list[str],
    start_time_epoch_s: int,
    logger: ConsoleFileLogger,
) -> trr_types.RunResult:
    verdict = _VERDICT_BY_ERROR_KIND[error.kind]
    return build_run_result(
        test_config=test_config_name,
        outcome=verdict.outcome,
        exit_code=verdict.exit_code,
        start_time_epoch_s=start_time_epoch_s,
        end_time_epoch_s=int(time.time()),
        duts=duts,
        playbooks=[],
        sections=[],
        error_message=error.msg,
        log_file=logger.get_log_file(),
    )


def _nothing_ran_error(runner: TaacRunner) -> TicTaacError | None:
    if runner.setup_only or runner.playbook_results:
        return None
    return TicTaacError(ErrorKind.NothingRan, _NOTHING_RAN_MESSAGE)


def _result_from_runner(
    test_config_name: str,
    error: TicTaacError | None,
    runner: TaacRunner,
    duts: list[str],
    start_time_epoch_s: int,
    logger: ConsoleFileLogger,
) -> trr_types.RunResult:
    verdict = _PASS_VERDICT if error is None else _VERDICT_BY_ERROR_KIND[error.kind]
    return build_run_result(
        test_config=test_config_name,
        outcome=verdict.outcome,
        exit_code=verdict.exit_code,
        start_time_epoch_s=start_time_epoch_s,
        end_time_epoch_s=int(time.time()),
        duts=duts,
        playbooks=runner.playbook_results,
        sections=runner.test_summary.build_section_results(),
        investigation_artifacts=runner.investigation_artifacts,
        artifacts=runner.run_artifacts,
        error_message=None if error is None else error.msg,
        log_file=logger.get_log_file(),
    )


async def _run_test_config(
    test_config: taac_types.TestConfig,
    options: _RunOptions,
    logger: ConsoleFileLogger,
    taac_runner_type: type[TaacRunner],
    start_time_epoch_s: int,
) -> trr_types.RunResult:
    requested_duts = options.requested_duts
    dut_count = sum(1 for endpoint in test_config.endpoints if endpoint.dut)
    logger.info(
        f"Test config '{test_config.name}': {len(test_config.playbooks)} playbooks, "
        f"{dut_count} endpoints marked dut"
    )
    config_duts = requested_duts or [
        endpoint.name for endpoint in test_config.endpoints if endpoint.dut
    ]

    selected = _select_playbooks(test_config, options.requested_playbooks, logger)
    if isinstance(selected, Err):
        return _result_without_runner(
            test_config.name,
            TicTaacError(ErrorKind.InvalidConfig, selected.err_value),
            config_duts,
            start_time_epoch_s,
            logger,
        )

    built = _build_runner(test_config, logger, taac_runner_type, options)
    if isinstance(built, Err):
        return _result_without_runner(
            test_config.name,
            TicTaacError(ErrorKind.InfraError, built.err_value),
            config_duts,
            start_time_epoch_s,
            logger,
        )
    runner = built.ok_value

    duts = requested_duts or runner.duts
    outcome = await _run_playbooks(runner, selected.ok_value, duts, logger)
    return _result_from_runner(
        test_config.name,
        (outcome.err_value if isinstance(outcome, Err) else _nothing_ran_error(runner)),
        runner,
        duts,
        start_time_epoch_s,
        logger,
    )


async def _run(
    args: argparse.Namespace,
    logger: ConsoleFileLogger,
    taac_runner_type: type[TaacRunner],
) -> trr_types.RunResult:
    start_time_epoch_s = int(time.time())
    source: str = args.test_config_json
    loaded = _load_test_config_json(source, sys.stdin.buffer)
    if isinstance(loaded, Err):
        logger.error(loaded.err_value)
        return _result_without_runner(
            "<stdin>" if source == STDIN_SOURCE else source,
            TicTaacError(ErrorKind.InvalidConfig, loaded.err_value),
            args.dut,
            start_time_epoch_s,
            logger,
        )
    options = _RunOptions(
        requested_playbooks=args.playbook,
        requested_duts=args.dut,
        skip_testbed_isolation=args.skip_testbed_isolation,
        skip_ixia_setup=args.skip_ixia_setup,
        skip_fboss_rsyslog=args.skip_fboss_rsyslog,
        skip_package_update=args.skip_package_update,
        continue_on_precheck_failure=args.continue_on_precheck_failure,
        setup_only=args.setup_only,
        ixia_api_server=args.ixia_api_server,
    )
    return await _run_test_config(
        loaded.ok_value, options, logger, taac_runner_type, start_time_epoch_s
    )


def _format_human_summary(run_result: trr_types.RunResult) -> str:
    ran_count = len({playbook.playbook_name for playbook in run_result.playbooks})
    return (
        f"{run_result.test_config}: ran {ran_count} playbook(s) on "
        f"{len(run_result.duts)} DUT(s) ({', '.join(run_result.duts)})"
    )


def _add_run_arguments(run: argparse.ArgumentParser) -> None:
    run.add_argument(
        "--test-config-json",
        metavar="SOURCE",
        required=True,
        help="Read a serialized TestConfig from a file, or '-' for stdin.",
    )
    run.add_argument(
        "--playbook",
        action="append",
        default=[],
        metavar="NAME",
        help="Run only the named playbook. Repeatable. Defaults to every "
        "playbook in the test config.",
    )
    run.add_argument(
        "--dut",
        action="append",
        default=[],
        metavar="HOSTNAME",
        help="Run against the named DUT. Repeatable. Defaults to the DUT "
        "endpoints declared by the test config.",
    )
    run.add_argument(
        "--skip-testbed-isolation",
        action="store_true",
        default=False,
        help="Skip the testbed isolation.",
    )
    run.add_argument(
        "--skip-ixia-setup",
        action="store_true",
        default=False,
        help="Skip the IXIA setup when ixia is not required for the test.",
    )
    run.add_argument(
        "--skip-fboss-rsyslog",
        action="store_true",
        default=False,
        help="Skip FBOSS rsyslog configuration setup and teardown.",
    )
    run.add_argument(
        "--skip-package-update",
        action="store_true",
        default=False,
        help="Skip the FBOSS package update during testbed setup.",
    )
    run.add_argument(
        "--continue-on-precheck-failure",
        action="store_true",
        default=False,
        help="Continue executing playbook stages even if prechecks fail.",
    )
    run.add_argument(
        "--setup-only",
        action="store_true",
        default=False,
        help="Complete setup and normal teardown without running playbooks.",
    )
    run.add_argument(
        "--ixia-api-server",
        metavar="HOST",
        help="IXIA API server to drive traffic through.",
    )
    run.add_argument(
        "--device-info-csv",
        type=Path,
        metavar="PATH",
        help="device_info.csv describing each device's OS and role.",
    )
    run.add_argument(
        "--circuit-info-csv",
        type=Path,
        metavar="PATH",
        help="circuit_info.csv describing the links between devices.",
    )
    run.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Emit the run result as a single JSON object on stdout.",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROGRAM_NAME,
        description="Test Invocation CLI for Test As A Config",
    )
    parser.add_argument(
        "--version",
        action=_UnwrappedVersionAction,
        version=_version_info(),
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=False,
        help="Log debug output to the console. The log file always records "
        "debug output regardless of this flag.",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    _add_run_arguments(
        subcommands.add_parser("run", help="Run a serialized test config.")
    )
    return parser


def _export_topology_paths(args: argparse.Namespace) -> None:
    topology_paths: tuple[tuple[str, Path | None], ...] = (
        (DEVICE_INFO_PATH_ENV, args.device_info_csv),
        (CIRCUIT_INFO_PATH_ENV, args.circuit_info_csv),
    )
    for variable, path in topology_paths:
        if path is not None:
            os.environ[variable] = str(path.resolve())


def main() -> None:
    args = _build_parser().parse_args()
    _export_topology_paths(args)

    logger = get_root_logger()
    if args.debug:
        logger.set_console_log_level(logging.DEBUG)
    logger.info(f"Log file: {logger.get_log_file()}")

    taac_runner_type = _load_taac_runner()
    run_result = asyncio.run(_run(args, logger, taac_runner_type))
    if args.json:
        print(thrift_to_json(run_result))
    elif run_result.outcome == trr_types.RunOutcome.PASS:
        print(_format_human_summary(run_result))
    else:
        print(run_result.error_message, file=sys.stderr)
    sys.exit(run_result.exit_code)
