#!/usr/bin/env python3
# pyre-unsafe

"""
OSS TAAC Entry Point

Main entry point for running TAAC tests under TAAC_OSS=1. Calls
TaacRunner directly.

Usage:
    python -m taac.runner.oss_entry_point \\
        --test-configs <config> --dut <device> [options]

Examples:
    # Run all tests in a config against a single DUT
    python -m taac.runner.oss_entry_point \\
        --test-configs my_config --dut switch1.example.com

    # Run specific playbooks against multiple DUTs
    python -m taac.runner.oss_entry_point \\
        --test-configs my_config --dut switch1 switch2 \\
        --playbook test_bgp test_agent

    # Enable debug logging
    python -m taac.runner.oss_entry_point \\
        --test-configs my_config --dut switch1 --debug
"""

import asyncio
import importlib.util
import logging
import os
import sys
import traceback
from pathlib import Path
from typing import List, Optional

from taac.libs.taac_runner import TaacRunner
from taac.runner.cli_parser import parse_args
from taac.runner.oss_exception_classifier import (
    classify_exception,
)
from taac.runner.oss_exceptions import (
    OSSConfigError,
    OSSConnectionError,
    OSSInfrastructureError,
    OSSTestbedError,
)
from taac.runner.oss_return_code import OSSReturnCode
from taac.runner.oss_test_executor import OSSTestExecutor
from taac.runner.oss_test_result import OSSTestResult
from taac.runner.oss_test_status import OSSTestStatus
from taac.runner.result_formatter import OSSResultAggregator
from taac.test_as_a_config.thrift_types import Endpoint


def load_test_config(config_path: str):
    """
    Load a test configuration from a Python file.

    Args:
        config_path: Path to the Python test config file

    Returns:
        TestConfig object

    Raises:
        OSSConfigError: If the config cannot be loaded
    """
    try:
        # Convert to Path object
        path = Path(config_path)

        # Check if file exists
        if not path.exists():
            raise OSSConfigError(f"Test config file not found: {config_path}")

        if not path.is_file():
            raise OSSConfigError(f"Test config path is not a file: {config_path}")

        if path.suffix != ".py":
            raise OSSConfigError(f"Test config file must be a .py file: {config_path}")

        # Load the module from file
        spec = importlib.util.spec_from_file_location(path.stem, path)
        if spec is None or spec.loader is None:
            raise OSSConfigError(f"Failed to load module spec from: {config_path}")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # Look for a TestConfig object or a function that returns one.
        # Try common naming conventions.
        #
        # IMPORTANT: gate the "call as factory" branch on
        # `not isinstance(config, TestConfig)`, not on bare callable().
        # thrift-python structs (taac.test_as_a_config.thrift_types) are
        # themselves callable — invoking an instance with kwargs returns
        # a copy with those fields replaced (immutable copy-with-override).
        # A naive callable(config) check therefore matches both a
        # module-level `test_config = TestConfig(...)` value *and* a
        # `def test_config(): ...` factory. A TestConfig instance called
        # with no kwargs returns a no-arg copy of itself, so this used
        # to be a silent no-op — but the next code reader who expects
        # their module-level value not to be invoked would be surprised.
        # Exclude instances explicitly so only real factories get called.
        #
        # Check both binding flavors: thrift_types (thrift-python, the
        # callable copy-with-override variant) and types (legacy
        # thrift-py3, used by Meta-internal configs).
        from taac.test_as_a_config import (
            thrift_types as _taac_thrift_types,
            types as _taac_types,
        )

        _testconfig_classes = (_taac_thrift_types.TestConfig, _taac_types.TestConfig)
        for attr_name in ["test_config", "TEST_CONFIG", "config", "CONFIG"]:
            if hasattr(module, attr_name):
                config = getattr(module, attr_name)
                if callable(config) and not isinstance(config, _testconfig_classes):
                    config = config()
                return config

        # If no config found, raise error
        raise OSSConfigError(
            f"No test config found in {config_path}. "
            f"Expected one of: test_config, TEST_CONFIG, config, CONFIG"
        )

    except OSSConfigError:
        raise
    except Exception as e:
        raise OSSConfigError(f"Failed to load test config from '{config_path}': {e}")


def filter_playbooks(config, playbook_names: Optional[List[str]] = None):
    """
    Filter playbooks from a test config.

    Args:
        config: TestConfig object
        playbook_names: List of playbook names to include (None = all enabled)

    Returns:
        List of playbooks to execute
    """
    playbooks = config.playbooks if hasattr(config, "playbooks") else []

    if playbook_names:
        # Filter by name, but only return enabled playbooks (mirrors the else
        # branch — a disabled playbook whose name matches shouldn't run).
        filtered = [pb for pb in playbooks if pb.name in playbook_names and pb.enabled]
        return filtered
    else:
        # Return all enabled playbooks
        return [pb for pb in playbooks if pb.enabled]


def main(argv: Optional[List[str]] = None) -> int:
    """
    Main entry point for OSS TAAC.

    Args:
        argv: Command line arguments (default: sys.argv)

    Returns:
        Exit code (0 for success, non-zero for failure)
    """
    # Set OSS mode environment variable
    os.environ["TAAC_OSS"] = "1"

    # Parse arguments
    args = parse_args(argv)

    # Wire --device-info-csv / --circuit-info-csv to the topology loader's
    # env vars BEFORE any taac.* import. The OSS topology loader
    # @memoize_forever-caches its lookups on first read, so a late export
    # leaves stale data behind for the rest of the process.
    if args.device_info_csv:
        os.environ["TAAC_DEVICE_INFO_PATH"] = os.path.abspath(args.device_info_csv)
    if args.circuit_info_csv:
        os.environ["TAAC_CIRCUIT_INFO_PATH"] = os.path.abspath(args.circuit_info_csv)

    # Setup logger (stdlib; structured-logger integration is a follow-up)
    log_level = logging.DEBUG if args.debug else getattr(logging, args.log_level)
    handlers: List[logging.Handler] = [logging.StreamHandler()]
    if args.log_file:
        handlers.append(logging.FileHandler(args.log_file))
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )
    logger = logging.getLogger("taac.oss")

    logger.info("=" * 60)
    logger.info("OSS TAAC Test Runner")
    logger.info("=" * 60)
    logger.info(f"Test Configs: {args.test_configs}")
    logger.info(f"DUTs: {args.duts}")
    if args.log_file:
        logger.info(f"Log File: {args.log_file}")

    # Create result aggregator
    aggregator = OSSResultAggregator()

    try:
        # Load all test configs
        configs = []
        for config_path in args.test_configs:
            logger.info(f"Loading test config from: {config_path}")
            config = load_test_config(config_path)
            configs.append((config_path, config))

        # Process each test config
        all_playbooks = []
        for config_path, config in configs:
            playbooks = filter_playbooks(config, args.playbooks)
            if playbooks:
                all_playbooks.extend([(config_path, config, pb) for pb in playbooks])

        if not all_playbooks:
            logger.error("No playbooks found to execute")
            return OSSReturnCode.NO_TESTS_FOUND

        logger.info(f"Total playbooks to execute: {len(all_playbooks)}")

        # List tests mode
        if args.list_tests:
            logger.info("\nAvailable Tests:")
            for config_path, config, pb in all_playbooks:
                logger.info(f"  - {Path(config_path).name}: {pb.name}")
            return OSSReturnCode.SUCCESS

        # Dry-run mode
        if args.dry_run:
            logger.info("Dry-run mode: All configurations validated successfully")
            return OSSReturnCode.SUCCESS

        # Execute playbooks from all configs. OSSTestExecutor wraps each
        # (playbook, dut) call so we capture an individual OSSTestResult
        # per execution rather than TaacRunner's collective pass/fail.
        logger.info("Starting test execution...")

        # Group playbooks by config
        configs_to_run = {}
        for config_path, config, playbook in all_playbooks:
            if not playbook.enabled:
                logger.info(f"Skipping disabled playbook: {playbook.name}")
                continue
            key = (config_path, config.name)
            if key not in configs_to_run:
                configs_to_run[key] = (config_path, config, [])
            configs_to_run[key][2].append(playbook)

        # Execute each config with all its playbooks and all DUTs
        for (config_path, config_name), (
            path,
            config,
            playbooks,
        ) in configs_to_run.items():
            logger.info(f"\n{'=' * 70}")
            logger.info(f"Executing test config: {config_name}")
            logger.info(f"  Config path: {path}")
            logger.info(f"  Playbooks: {[pb.name for pb in playbooks]}")
            logger.info(f"  DUTs: {args.duts}")
            logger.info(f"{'=' * 70}\n")

            # Ensure config.endpoints includes every --dut: TaacRunner builds
            # its topology from test_config.endpoints, so DUTs that aren't
            # listed there fail with "not found in topology". Append missing
            # --dut entries (don't overwrite endpoints the user already
            # declared, e.g. for traffic generators).
            existing_dut_names = {ep.name for ep in config.endpoints if ep.dut}
            missing_duts = [d for d in args.duts if d not in existing_dut_names]
            if missing_duts:
                new_endpoints = tuple(config.endpoints) + tuple(
                    Endpoint(name=d, dut=True) for d in missing_duts
                )
                # thrift struct copy-with-override: thrift-python structs are
                # callable with kwargs to produce a copy with the named fields
                # replaced (the original is immutable).
                config = config(endpoints=new_endpoints)

            # Create TaacRunner for this config
            taac_runner = TaacRunner(
                test_config=config,
                ixia_api_server=args.ixia_api_server,
                ixia_session_id=args.ixia_session_id,
                skip_ixia_setup=args.skip_ixia_setup,
                skip_ixia_cleanup=args.skip_ixia_cleanup,
                skip_testbed_isolation=args.skip_testbed_isolation,
                skip_setup_tasks=args.skip_setup_tasks,
                skip_teardown_tasks=args.skip_teardown_tasks,
                skip_post_setup_wait=args.skip_post_setup_wait,
            )

            # Create executor for this config
            executor = OSSTestExecutor(
                taac_runner=taac_runner,
                logger=logger,
            )

            # Run the full setUp → execute → tearDown lifecycle inside ONE
            # asyncio.run() so all three phases share the same event loop.
            # If setUp creates resources tied to the loop (connection pools,
            # async context managers, etc.), running it on a separate loop
            # from execute_playbook / tearDown produces "attached to a
            # different loop" errors or silent connection failures.
            async def _run_lifecycle() -> None:
                await taac_runner.async_test_setUp()
                try:
                    for playbook in playbooks:
                        for dut in args.duts:
                            logger.info(f"\nExecuting {playbook.name} on {dut}...")
                            result = await executor.execute_playbook(
                                playbook=playbook,
                                dut=dut,
                                test_config=config_name,
                            )
                            aggregator.add_result(result)

                            # Handle retries for transient failures
                            if (
                                args.retry
                                and result.is_transient
                                and result.status.failed
                            ):
                                for retry_attempt in range(args.retry):
                                    logger.info(
                                        f"Retry attempt {retry_attempt + 1}/{args.retry} for {playbook.name} on {dut}"
                                    )
                                    retry_result = await executor.execute_playbook(
                                        playbook=playbook,
                                        dut=dut,
                                        test_config=config_name,
                                    )
                                    retry_result.retry_count = retry_attempt + 1

                                    # If retry succeeded, mark original as RETRIED.
                                    # Also clear is_transient on the original so it
                                    # doesn't trip get_exit_code's `any(is_transient)`
                                    # check — a fully-recovered run must exit 0, not
                                    # TRANSIENT_ERROR (130), or --retry is pointless.
                                    if not retry_result.status.failed:
                                        result.status = OSSTestStatus.RETRIED
                                        result.is_transient = False
                                        aggregator.add_result(retry_result)
                                        break
                                    else:
                                        # Add failed retry result
                                        aggregator.add_result(retry_result)
                finally:
                    try:
                        logger.info("Running async_test_tearDown()...")
                        await taac_runner.async_test_tearDown()
                    except Exception as td_exc:
                        logger.error(f"Error during teardown: {td_exc}")
                        logger.exception(td_exc)

            # Enforce --timeout on the full setUp → execute → tearDown
            # lifecycle. `asyncio.wait_for` cancels the wrapped coroutine
            # (which lets the `finally:` inside _run_lifecycle run the
            # teardown) and re-raises asyncio.TimeoutError, which we map
            # to OSSTestStatus.TIMEOUT for any playbook×dut combos that
            # never produced a result. Wrap+run inside one asyncio.run()
            # so the timer and the lifecycle share a single event loop.
            async def _timed_lifecycle() -> None:
                await asyncio.wait_for(_run_lifecycle(), timeout=args.timeout)

            try:
                asyncio.run(_timed_lifecycle())
            except Exception as e:
                if isinstance(e, asyncio.TimeoutError):
                    logger.error(
                        f"Timeout after {args.timeout}s executing test config "
                        f"{config_name}"
                    )
                    status, is_transient = OSSTestStatus.TIMEOUT, False
                else:
                    logger.error(f"Error executing test config {config_name}: {e}")
                    logger.exception(e)
                    status, is_transient = classify_exception(e)
                # Mark remaining playbooks/duts as failed for this config
                for playbook in playbooks:
                    for dut in args.duts:
                        # Only add error result if we haven't already executed this combo
                        if not any(
                            r.playbook == playbook.name and r.dut == dut
                            for r in aggregator.results
                        ):
                            result = OSSTestResult(
                                test_config=config_name,
                                playbook=playbook.name,
                                dut=dut,
                                status=status,
                                duration=0.0,
                                message=str(e) or f"Timeout after {args.timeout}s",
                                exception_type=type(e).__name__,
                                exception_message=str(e),
                                is_transient=is_transient,
                                traceback=traceback.format_exc(),
                            )
                            aggregator.add_result(result)

        # Print summary
        aggregator.print_summary(logger)

        # Write output files based on format
        if args.output_format == "json" or args.json_output:
            json_path = args.json_output or "taac_results.json"
            aggregator.to_json(json_path)
            logger.info(f"JSON results written to {json_path}")

        if args.output_format == "junit" or args.junit_output:
            junit_path = args.junit_output or "taac_results.xml"
            aggregator.to_junit_xml(junit_path)
            logger.info(f"JUnit XML results written to {junit_path}")

        # Determine exit code
        exit_code = aggregator.get_exit_code()
        logger.info(f"Exit code: {exit_code}")

        return exit_code

    except OSSConfigError as e:
        logger.error(f"Configuration error: {e}")
        return OSSReturnCode.CONFIG_ERROR
    except OSSTestbedError as e:
        logger.error(f"Testbed error: {e}")
        return OSSReturnCode.TESTBED_ERROR
    except OSSConnectionError as e:
        logger.error(f"Connection error: {e}")
        return OSSReturnCode.CONNECTION_ERROR
    except OSSInfrastructureError as e:
        logger.error(f"Infrastructure error: {e}")
        return OSSReturnCode.INFRA_ERROR
    except Exception as e:
        # User-caused errors (bad config / bad args) are already caught by
        # the OSSConfigError / OSSInfrastructureError handlers above, so an
        # unhandled exception this far down is more likely an infra problem
        # than a user error.
        logger.error(f"Unexpected error: {e}")
        logger.debug("Traceback:", exc_info=True)
        return OSSReturnCode.INFRA_ERROR


if __name__ == "__main__":
    sys.exit(main())
