#!/usr/bin/env fbpython
# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

"""Exercise OS-aware TAAC health-check paths on Classic and NetOS devices."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import typing as t
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from enum import Enum

from taac.driver.driver_constants import (
    FbossOsType,
    FbossSystemctlServiceName,
)
from taac.health_checks.device_health_checks.log_parsing_health_check import (
    LogParsingHealthCheck,
)
from taac.health_checks.device_health_checks.route_convergence_time_health_check import (
    RouteConvergenceMetrics,
    RouteConvergenceTimeHealthCheck,
)
from taac.health_checks.device_health_checks.systemctl_active_state_health_check import (
    SystemctlActiveStateHealthCheck,
)
from taac.utils.driver_factory import async_get_device_driver
from taac.health_check.health_check import types as hc_types


DEFAULT_DEVICES: tuple[str, ...] = (
    "rsw004.p005.f01.qza1.tfbnw.net",
    "rsw001.p006.f01.qzd1",
    "fsw001.p001.f01.qzd1",
)
DEFAULT_SERVICES: tuple[str, ...] = (
    FbossSystemctlServiceName.AGENT.value,
    FbossSystemctlServiceName.BGP.value,
    FbossSystemctlServiceName.QSFP.value,
    FbossSystemctlServiceName.FSDB.value,
)
AGENT_LOG_PATH: str = "/var/facebook/logs/fboss/wedge_agent.log"
NO_MATCH_SENTINEL: str = "__TAAC_HEALTHCHECK_COMPATIBILITY_SENTINEL__"


class _Driver(t.Protocol):
    async def async_get_fboss_os_type(self) -> FbossOsType: ...

    async def async_get_log_source_command(
        self, log_file_path: str, start_time: str | None = None
    ) -> str: ...

    async def async_read_log_file(
        self,
        log_file_path: str,
        *,
        start_time: int | None = None,
        end_time: int | None = None,
        grep_pattern: str | None = None,
        tail_lines: int | None = None,
    ) -> str: ...

    async def async_get_systemctl_service_name(self, service: object) -> str: ...

    async def async_run_cmd_on_shell(self, command: str) -> str: ...

    async def async_restart_service(
        self, service: FbossSystemctlServiceName
    ) -> None: ...

    async def async_wait_for_bgp_convergence(self, timeout: int) -> None: ...


class CheckStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"
    NO_EVENTS = "NO_EVENTS"


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: CheckStatus
    details: str


@dataclass(frozen=True)
class DeviceResult:
    hostname: str
    os_type: str
    checks: tuple[CheckResult, ...]

    @property
    def passed(self) -> bool:
        return all(check.status is CheckStatus.PASS for check in self.checks)


@dataclass(frozen=True)
class _Device:
    name: str


def _health_check_logger(hostname: str) -> logging.Logger:
    return logging.getLogger(f"netos-healthcheck-compatibility.{hostname}")


def _window(
    now: datetime,
    lookback_seconds: int,
) -> tuple[int, int, str, str]:
    start = now - timedelta(seconds=lookback_seconds)
    return (
        int(start.timestamp()),
        int(now.timestamp()),
        start.strftime("%Y%m%d%H%M"),
        start.strftime("%H:%M:%S.%f"),
    )


async def _run_check(
    name: str,
    operation: t.Callable[[], t.Awaitable[CheckResult]],
) -> CheckResult:
    try:
        return await operation()
    except Exception as error:
        return CheckResult(name, CheckStatus.ERROR, f"{type(error).__name__}: {error}")


async def _check_journal_mapping(
    driver: _Driver,
    os_type: FbossOsType,
    start_stamp: str,
) -> CheckResult:
    source = await driver.async_get_log_source_command(
        AGENT_LOG_PATH, start_time=start_stamp
    )
    uses_journal = source.lstrip().startswith("journalctl ")
    expects_journal = os_type is FbossOsType.NETOS_NATIVE
    if uses_journal != expects_journal:
        return CheckResult(
            "journal_mapping",
            CheckStatus.FAIL,
            f"os={os_type.value}, unexpected source={source}",
        )
    sample = await driver.async_run_cmd_on_shell(f"{source} | tail -n 1")
    if not sample.strip():
        return CheckResult(
            "journal_mapping",
            CheckStatus.FAIL,
            f"os={os_type.value}, source returned no log lines",
        )
    source_kind = "journald" if uses_journal else "file"
    return CheckResult(
        "journal_mapping",
        CheckStatus.PASS,
        f"os={os_type.value}, source={source_kind}, sample_bytes={len(sample)}",
    )


async def _check_log_parsing(
    hostname: str,
    driver: _Driver,
    start_epoch: int,
    end_epoch: int,
) -> CheckResult:
    check = LogParsingHealthCheck(logger=t.cast(t.Any, _health_check_logger(hostname)))
    check.driver = t.cast(t.Any, driver)
    result = await check._run(
        t.cast(t.Any, _Device(hostname)),
        hc_types.BaseHealthCheckIn(),
        {
            "log_file_path": AGENT_LOG_PATH,
            "exclude_regex": NO_MATCH_SENTINEL,
            "start_time": start_epoch,
            "end_time": end_epoch,
            "tail_lines": 2000,
        },
    )
    status = (
        CheckStatus.PASS
        if result.status is hc_types.HealthCheckStatus.PASS
        else CheckStatus.FAIL
    )
    return CheckResult("log_parsing", status, result.message or "")


async def _route_metrics(
    check: RouteConvergenceTimeHealthCheck,
    start_stamp: str,
    start_time: str,
) -> tuple[RouteConvergenceMetrics | None, RouteConvergenceMetrics | None]:
    add = await check._get_route_convergence_metrics(
        [AGENT_LOG_PATH],
        "ADD",
        start_time,
        3600,
        start_stamp=start_stamp,
    )
    delete = await check._get_route_convergence_metrics(
        [AGENT_LOG_PATH],
        "DELETE",
        start_time,
        3600,
        start_stamp=start_stamp,
    )
    return add, delete


async def _check_route_convergence(
    hostname: str,
    driver: _Driver,
    start_stamp: str,
    start_time: str,
    *,
    generate_route_events: bool,
    timeout: int,
) -> CheckResult:
    check = RouteConvergenceTimeHealthCheck(
        logger=t.cast(t.Any, _health_check_logger(hostname)),
        ixia=None,
    )
    check.driver = t.cast(t.Any, driver)
    add, delete = await _route_metrics(check, start_stamp, start_time)
    generated = False
    if (add is None or delete is None) and generate_route_events:
        generated = True
        event_start = datetime.now()
        await driver.async_restart_service(FbossSystemctlServiceName.BGP)
        await driver.async_wait_for_bgp_convergence(timeout=timeout)
        _, _, start_stamp, start_time = _window(event_start, 0)
        add, delete = await _route_metrics(check, start_stamp, start_time)

    if add is None and delete is None:
        generated_detail = f", generated={generated}" if generated else ""
        return CheckResult(
            "route_convergence",
            CheckStatus.NO_EVENTS,
            f"parser executed; no route events in window{generated_detail}",
        )

    if add is None or delete is None:
        missing = [
            operation
            for operation, metrics in (("ADD", add), ("DELETE", delete))
            if metrics is None
        ]
        return CheckResult(
            "route_convergence",
            CheckStatus.PASS,
            (
                f"parser executed with live events; missing={','.join(missing)}, "
                f"generated={generated}, "
                f"added={add.total_routes_added if add else 0}, "
                f"deleted={delete.total_routes_deleted if delete else 0}"
            ),
        )

    return CheckResult(
        "route_convergence",
        CheckStatus.PASS,
        (
            f"generated={generated}, added={add.total_routes_added}, "
            f"deleted={delete.total_routes_deleted}, "
            f"add_batches={add.num_batches}, delete_batches={delete.num_batches}"
        ),
    )


async def _check_service_health(
    hostname: str,
    driver: _Driver,
    services: tuple[str, ...],
) -> CheckResult:
    check = SystemctlActiveStateHealthCheck(
        logger=t.cast(t.Any, _health_check_logger(hostname))
    )
    check.driver = t.cast(t.Any, driver)
    result = await check._run(
        t.cast(t.Any, _Device(hostname)),
        hc_types.SystemctlActiveStateHealthCheckIn(),
        {"services": list(services)},
    )
    status = (
        CheckStatus.PASS
        if result.status is hc_types.HealthCheckStatus.PASS
        else CheckStatus.FAIL
    )
    return CheckResult("service_health", status, result.message or "all active")


async def run_device_checks(
    hostname: str,
    driver: _Driver,
    *,
    now: datetime | None = None,
    lookback_seconds: int,
    generate_route_events: bool,
    timeout: int = 300,
    services: tuple[str, ...] = DEFAULT_SERVICES,
) -> DeviceResult:
    """Run every OS-sensitive health-check path against one live driver."""
    os_type = await driver.async_get_fboss_os_type()
    start_epoch, end_epoch, start_stamp, start_time = _window(
        now or datetime.now(), lookback_seconds
    )

    checks = (
        await _run_check(
            "journal_mapping",
            lambda: _check_journal_mapping(driver, os_type, start_stamp),
        ),
        await _run_check(
            "log_parsing",
            lambda: _check_log_parsing(hostname, driver, start_epoch, end_epoch),
        ),
        await _run_check(
            "route_convergence",
            lambda: _check_route_convergence(
                hostname,
                driver,
                start_stamp,
                start_time,
                generate_route_events=generate_route_events,
                timeout=timeout,
            ),
        ),
        await _run_check(
            "service_health",
            lambda: _check_service_health(hostname, driver, services),
        ),
    )
    return DeviceResult(hostname, os_type.value, checks)


def _result_to_dict(result: DeviceResult) -> dict[str, object]:
    return {
        "hostname": result.hostname,
        "os_type": result.os_type,
        "passed": result.passed,
        "checks": [
            {**asdict(check), "status": check.status.value} for check in result.checks
        ],
    }


async def run_checks(args: argparse.Namespace) -> int:
    os.environ["TAAC_SSH_VIA_LAB_SSH"] = "1"
    devices = tuple(args.device or DEFAULT_DEVICES)
    results: list[DeviceResult] = []
    for hostname in devices:
        logging.info("Running health-check compatibility probes on %s", hostname)
        try:
            raw_driver = await async_get_device_driver(hostname)
            results.append(
                await run_device_checks(
                    hostname,
                    t.cast(_Driver, raw_driver),
                    lookback_seconds=args.lookback_seconds,
                    generate_route_events=args.generate_route_events,
                    timeout=args.timeout,
                )
            )
        except Exception as error:
            logging.exception("%s: failed before health checks completed", hostname)
            results.append(
                DeviceResult(
                    hostname,
                    "unknown",
                    (
                        CheckResult(
                            "driver_setup",
                            CheckStatus.ERROR,
                            f"{type(error).__name__}: {error}",
                        ),
                    ),
                )
            )

    print(
        json.dumps(
            {
                "compatible": all(result.passed for result in results),
                "results": [_result_to_dict(result) for result in results],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if all(result.passed for result in results) else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate OS-aware TAAC log parsing, journal mapping, route-log "
            "parsing, and service health across FBOSS OS variants."
        ),
        fromfile_prefix_chars="@",
    )
    parser.add_argument(
        "--device",
        action="append",
        help="Device to check. Repeat to override the built-in three-device matrix.",
    )
    parser.add_argument(
        "--lookback-seconds",
        type=int,
        default=21600,
        help="Live log lookback window (default: 21600 / six hours).",
    )
    parser.add_argument(
        "--generate-route-events",
        action="store_true",
        help=(
            "Restart BGP only when route ADD/DELETE events are absent, then "
            "wait for convergence and retry the parser."
        ),
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Seconds to wait for BGP convergence after event generation.",
    )
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    sys.exit(asyncio.run(run_checks(parse_args())))


if __name__ == "__main__":
    main()
