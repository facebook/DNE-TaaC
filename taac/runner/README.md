# TAAC OSS Entry Point CLI

## Table of Contents

- [Overview](#overview)
- [Quick Start](#quick-start)
- [Command-Line Arguments](#command-line-arguments)
- [Exit Codes](#exit-codes)
- [Usage Examples](#usage-examples)
- [Architecture](#architecture)
- [Test Coverage](#test-coverage)
- [Troubleshooting](#troubleshooting)
- [Related Documentation](#related-documentation)

---

## Overview

Standalone CLI for running TAAC tests in OSS environments.

**Key Features:**
- Multiple test configs and DUTs
- Retry logic for transient failures
- Exception classification with proper exit codes
- JSON and JUnit XML output formats
- Dry-run and list-tests modes

---

## Quick Start

The entry point runs inside the `fboss-taac` derived image (built via
`./docker/build-taac-image.sh` — see [`../../docker/README.md`](../../docker/README.md)
for prereqs and customization). Wrap each command below with
`docker run --rm fboss-taac` to invoke it; the image's entrypoint exports
`PYTHONPATH`, `LD_LIBRARY_PATH`, and `TAAC_OSS=1` for you. Mount your test
configs with `-v` as needed.

### Basic Test Execution

```bash
docker run --rm \
  -v "$PWD/my_test_config.py":/test_config.py \
  fboss-taac \
  python3 -m taac.runner.oss_entry_point \
    --test-configs /test_config.py \
    --dut device1.example.com \
    --ixia-api-server 10.0.0.100
```

### Validate Configuration (Dry-Run)

```bash
docker run --rm \
  -v "$PWD/my_test_config.py":/test_config.py \
  fboss-taac \
  python3 -m taac.runner.oss_entry_point \
    --test-configs /test_config.py \
    --dut dummy-device \
    --dry-run
```

### List Available Tests

```bash
docker run --rm \
  -v "$PWD/my_test_config.py":/test_config.py \
  fboss-taac \
  python3 -m taac.runner.oss_entry_point \
    --test-configs /test_config.py \
    --dut dummy-device \
    --list-tests
```

---



## Command-Line Arguments

### Required Arguments

| Argument | Type | Description |
|----------|------|-------------|
| `--test-configs` | str[] | Path(s) to Python test config files (can specify multiple) |
| `--dut` | str[] | Device Under Test hostname(s) (can specify multiple) |

### Conditionally Required Arguments

| Argument | Type | Description |
|----------|------|-------------|
| `--ixia-api-server` | str | IP address of IXIA chassis. **Required for tests that use IXIA traffic generation**. Optional for validation-only tests, `--dry-run`, and `--list-tests` modes |

### IXIA Configuration

| Argument | Type | Description |
|----------|------|-------------|
| `--ixia-session-id` | int | Reuse existing IXIA session ID |
| `--skip-ixia-setup` | flag | Skip IXIA initialization |
| `--skip-ixia-cleanup` | flag | Skip IXIA teardown |

### Test Execution Control

| Argument | Type | Description |
|----------|------|-------------|
| `--playbook` | str[] | Filter to specific playbooks (default: all) |
| `--skip-testbed-isolation` | flag | Skip testbed isolation checks |
| `--skip-setup-tasks` | flag | Skip setup tasks |
| `--skip-teardown-tasks` | flag | Skip teardown tasks |
| `--dry-run` | flag | Validate config without execution |
| `--timeout` | int | Global timeout in seconds (default: 3600 = 1 hour) |
| `--retry` | int | Number of retries for transient failures (default: 0) |
| `--list-tests` | flag | List available tests and exit |

### Logging and Output

| Argument | Type | Description |
|----------|------|-------------|
| `--log-level` | str | Logging level: DEBUG, INFO, WARNING, ERROR (default: INFO) |
| `--log-file` | str | Path to log file (default: taac_oss.log) |
| `--output-format` | str | Output format: json, junit, text (default: text) |
| `--json-output` | str | Path for JSON results (default: taac_results.json when --output-format=json) |
| `--junit-output` | str | Path for JUnit XML results (default: taac_results.xml when --output-format=junit) |

---

## Exit Codes

Exit codes follow POSIX convention:
- **0**: Success - all tests passed
- **1-127**: User errors (test failures, invalid input, configuration issues)
- **128+**: Infrastructure errors (device connectivity, IXIA issues, transient failures)

### Exit codes returned today

`OSSResultAggregator.get_exit_code()` is the single source of truth
for aggregated-result exit codes; the outer `try/except` in `main()`
handles fail-fast exits before any result is captured.

| Code | Name | Returned when |
|------|------|---------------|
| 0   | `SUCCESS`             | Every result is PASSED or skipped (SKIPPED/OMITTED/NOT_RUN/RETRIED) |
| 2   | `TEST_CASE_FAILURE`   | Any result is FAILED, or a non-transient ERROR. Real test regressions dominate infra-class signals — a run of 49 FAILED + 1 TIMEOUT exits `2`, not `131`. Transient-flagged ERRORs are excluded (they route to `130` below). Also the trailing catch-all for any other `.failed` status (e.g. TEARDOWN_FAILED) when no more specific bucket fires |
| 4   | `NO_TESTS_FOUND`      | The aggregator has zero results |
| 5   | `CONFIG_ERROR`        | `load_test_config()` raised `OSSConfigError` (bad/missing/malformed config file) |
| 128 | `INFRA_ERROR`         | Any result is SETUP_FAILED — and the outer `except OSSInfrastructureError` / `except Exception` in `main()` re-classifies unclassified or general-infra exceptions to this bucket |
| 129 | `TESTBED_ERROR`       | Any result is `TESTBED_FAILED` (`OSSTestbedError` raised during execution and recorded by the playbook executor) — or `OSSTestbedError` escaped past the executor and was caught by `main()`'s dedicated `except OSSTestbedError` handler |
| 130 | `TRANSIENT_ERROR`     | Any result has `is_transient=True` and no real test failure (FAILED / non-transient ERROR) exists (cleared on a successful retry, so a fully-recovered run still exits 0) |
| 131 | `TIMEOUT_ERROR`       | Any result is TIMEOUT and no real test failure exists (incl. firing of the `--timeout` `asyncio.wait_for` wrap in main()) |
| 132 | `CONNECTION_ERROR`    | Any result is `CONNECTION_FAILED` (`OSSConnectionError` raised during execution) — or `OSSConnectionError` escaped past the executor and was caught by `main()`'s dedicated `except OSSConnectionError` handler |

**Two paths produce 129/132.** Infra exceptions raised during a
playbook are caught by the executor, classified via `classify_exception`
to dedicated `TESTBED_FAILED` / `CONNECTION_FAILED` statuses, and
routed by `get_exit_code` to `129` / `132`. Infra exceptions raised
*before* any playbook runs (e.g. during config load or runner
construction) escape past the executor and are caught by `main()`'s
dedicated handlers, which return the same codes directly. Either way
the caller sees the right exit code.

### Exception → exit code

```python
# At the per-playbook layer, classify_exception() in
# oss_exception_classifier.py maps the raised exception → OSSTestStatus:
TestCaseFailure                          → FAILED              # TAAC raises this on health-check / postcheck regressions
AssertionError                           → FAILED
unittest.SkipTest                        → SKIPPED
TimeoutError / asyncio.TimeoutError      → TIMEOUT             # both — distinct on Python <3.11
OSSTestbedError                          → TESTBED_FAILED      # infra
OSSConnectionError                       → CONNECTION_FAILED   # infra
OSSTransientError                        → ERROR + is_transient=True
OSSSetupError                            → SETUP_FAILED
OSSTeardownError                         → TEARDOWN_FAILED
<anything else>                          → ERROR

# Then OSSResultAggregator.get_exit_code() folds the per-result statuses
# into the codes in the table above. Two-step mapping — there is no
# direct exception → exit-code shortcut.
```

---

## Usage Examples

### Run a Test Config

```bash
python3 -m taac.runner.oss_entry_point \
  --test-configs taac/examples/test_config_minimal.py \
  --dut rsw1af.21.abc1 \
  --ixia-api-server 10.1.2.3
```

**Note:** See `taac/examples/` for example test configs.

### Run Multiple Test Configs

```bash
python3 -m taac.runner.oss_entry_point \
  --test-configs test1.py test2.py test3.py \
  --dut device1 device2 \
  --ixia-api-server 10.1.2.3
```

### Run Specific Playbooks Only

```bash
python3 -m taac.runner.oss_entry_point \
  --test-configs my_test_config.py \
  --dut device1 \
  --ixia-api-server 10.1.2.3 \
  --playbook warmboot_test --playbook coldboot_test
```

### Dry-Run Mode (Validate Only)

```bash
python3 -m taac.runner.oss_entry_point \
  --test-configs my_test_config.py \
  --dut device1 \
  --ixia-api-server 10.1.2.3 \
  --dry-run
```

### List Available Tests

```bash
python3 -m taac.runner.oss_entry_point \
  --test-configs my_test_config.py \
  --dut device1 \
  --list-tests
```

### JSON Output for CI Integration

```bash
python3 -m taac.runner.oss_entry_point \
  --test-configs my_test_config.py \
  --dut device1 \
  --ixia-api-server 10.1.2.3 \
  --output-format json
# Results written to taac_results.json
```

### JUnit XML Output for Jenkins/CI

```bash
python3 -m taac.runner.oss_entry_point \
  --test-configs my_test_config.py \
  --dut device1 \
  --ixia-api-server 10.1.2.3 \
  --output-format junit \
  --junit-output results.xml
```

### Debug Mode with Verbose Logging

```bash
python3 -m taac.runner.oss_entry_point \
  --test-configs my_test_config.py \
  --dut device1 \
  --ixia-api-server 10.1.2.3 \
  --log-level DEBUG \
  --log-file debug.log
```

## Test Config File Format

Test config files must be Python modules that define a `test_config`, `TEST_CONFIG`, `config`, or `CONFIG` variable (or callable).

Example:

```python
# my_test_config.py
from taac.test_as_a_config import types as taac_types

test_config = taac_types.TestConfig(
    name="my_test",
    playbooks=[
        taac_types.Playbook(
            name="warmboot_test",
            # ... playbook configuration
        ),
    ],
)
```

---

## Architecture

### Component Diagram

The OSS Entry Point consists of 8 core modules:

```
┌─────────────────────────────────────────────────────────────┐
│                    oss_entry_point.py                        │
│  (Main orchestrator - loads configs, creates runner, etc.)   │
└────────────┬────────────────────────────────────────────────┘
             │
             ├──> cli_parser.py (Parse CLI arguments)
             │
             ├──> oss_test_executor.py (Execute playbooks via TaacRunner)
             │    └──> TaacRunner.run_tests([playbook], [dut])
             │
             ├──> oss_test_result.py (Test result dataclass)
             │
             ├──> result_formatter.py (Aggregate results, generate output)
             │    ├──> to_json()
             │    ├──> to_junit_xml()
             │    └──> print_summary()
             │
             ├──> oss_test_status.py (Test status enum)
             │
             ├──> oss_return_code.py (Exit code enum)
             │
             ├──> oss_exceptions.py (OSS exception classes)
             └──> oss_exception_classifier.py (Exception → status mapping)
```

### Execution Flow

1. **Parse CLI Arguments** (`cli_parser.py`)
   - Validate required args (--test-configs, --duts)
   - Set defaults for optional args
   - Return parsed `argparse.Namespace`

2. **Load Test Configs** (`oss_entry_point.py::load_test_config()`)
   - Import Python module from path
   - Extract `test_config` / `TEST_CONFIG` / `config` / `CONFIG` variable/callable
   - Validate structure

3. **Initialize TaacRunner** (`oss_entry_point.py::main()`)
   - Create `TaacRunner` with test config and IXIA args
   - Call `async_test_setUp()` for testbed initialization

4. **Execute Tests** (`oss_test_executor.py`)
   - For each playbook × DUT combination:
     - Call `TaacRunner.run_tests([playbook], [dut])`
     - Catch exceptions and classify them
     - Create `OSSTestResult` with status, duration, exception info
     - Handle retry logic for transient failures

5. **Aggregate Results** (`result_formatter.py`)
   - Collect all `OSSTestResult` objects
   - Count by status (passed, failed, error, timeout, etc.)
   - Determine exit code based on result priorities
   - Compute totals and summaries

6. **Generate Output** (`result_formatter.py`)
   - **Text format**: Human-readable summary to stdout
   - **JSON format**: Machine-readable JSON to file
   - **JUnit XML format**: Standard CI/CD format to file

7. **Teardown** (`oss_entry_point.py::main()`)
   - Call `async_test_tearDown()` for cleanup
   - Return exit code

### Module Responsibilities

| Module | Responsibility | Key Classes/Functions |
|--------|----------------|----------------------|
| `oss_entry_point.py` | Main orchestrator | `main()`, `load_test_config()` |
| `cli_parser.py` | CLI argument parsing | `create_argument_parser()`, `parse_args()` |
| `oss_test_executor.py` | Test execution wrapper | `OSSTestExecutor`, `execute_playbook()` |
| `oss_test_result.py` | Test result data model | `OSSTestResult` dataclass |
| `result_formatter.py` | Result aggregation & formatting | `OSSResultAggregator` |
| `oss_test_status.py` | Test status enumeration | `OSSTestStatus` enum |
| `oss_return_code.py` | Exit code enumeration | `OSSReturnCode` enum |
| `oss_exceptions.py` | OSS exception class hierarchy | `OSSConfigError`, `OSSTransientError`, `OSSTestbedError`, ... |
| `oss_exception_classifier.py` | Exception → status mapping | `classify_exception()`, `is_infra_error()`, `get_exception_to_status_map()` |

---

## Test Coverage

| Test File | Focus |
|-----------|-------|
| `test_oss_entry_point.py` | CLI parsing, output formats, mocked-executor main() incl. retry-loop + setup-crash coverage |
| `test_entry_point_integration.py` | File-based main() invocations (--list-tests / --dry-run / --help) |
| `test_oss_exceptions.py` | classify_exception mapping incl. TestCaseFailure → FAILED |
| `test_oss_test_executor.py` | TaacRunner integration, async executor exception paths |
| `test_oss_test_result.py` | Result dataclass fields + summary/detailed_message |
| `test_oss_test_status.py` | Status enum semantics + ANSI colors + is_skipped/failed |
| `test_retry_logic.py` | Executor-level retry pieces + retry data-model |

### Running Tests

Tests run inside the derived image and bind-mount the runner source so
local edits are picked up without a rebuild:

```bash
# Run all tests
docker run --rm \
  -v "$PWD/taac/runner":/taac/taac/runner \
  fboss-taac \
  python3 -m unittest discover -s /taac/taac/runner/tests

# Run a specific test file
docker run --rm \
  -v "$PWD/taac/runner":/taac/taac/runner \
  fboss-taac \
  python3 -m unittest taac.runner.tests.test_oss_entry_point

# With pytest + coverage (pytest-cov in requirements.txt)
docker run --rm \
  -v "$PWD/taac/runner":/taac/taac/runner \
  fboss-taac \
  python3 -m pytest /taac/taac/runner/tests/ \
    --cov=/taac/taac/runner \
    --cov-report=term-missing
```

The tests need the full TAAC thrift bindings (`taac.test_as_a_config`,
`taac.libs.taac_runner`, etc.), which ship inside the image — running them
on the host without the image will fail at import time.

---

## Related Documentation

- **Top-level usage:** [`../../README.md`](../../README.md)
- **Docker stack:** [`../../docker/README.md`](../../docker/README.md)
- **Example test configs:** [`../examples/`](../examples/)

---

## Troubleshooting

**`Config file not found`**
```bash
# Use absolute paths or bind-mount the config into the container
docker run --rm \
  -v "$PWD/my_test_config.py":/test_config.py \
  fboss-taac \
  python3 -m taac.runner.oss_entry_point \
    --test-configs /test_config.py --dut device1
```

**Exit code 129 (`TESTBED_ERROR`)** — DUT or IXIA unreachable from the
container. For DUTs on internal DNS, pass `--network host` to `docker run`.
Verify reachability directly:

```bash
ssh device1.example.com
curl http://10.1.2.3:11009/api/v1/sessions
```

**Exit code 5 (`CONFIG_ERROR`)** — config file doesn't export the expected
variable. The loader looks for one of: `test_config`, `TEST_CONFIG`,
`config`, `CONFIG`.

```bash
docker run --rm \
  -v "$PWD/my_test_config.py":/test_config.py \
  fboss-taac \
  python3 -c "from my_test_config import test_config; print(test_config)"
```
