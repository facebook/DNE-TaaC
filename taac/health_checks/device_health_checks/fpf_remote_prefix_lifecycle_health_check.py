# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""Exact, phase-aware lifecycle validation for a filtered FPF prefix set."""

import asyncio
import time
import typing as t

from taac.constants import TestDevice
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
)
from taac.libs.fpf.fpf_collector_registry import (
    everpaste_details_suffix,
    get_collector,
    get_disruption_time,
    get_mutation_time,
    get_recovery_completion_time,
    get_recovery_start_time,
    get_restart_completion_time,
    get_test_case_start_time,
)
from taac.libs.fpf.fpf_stress_checks import (
    _parse_ts,
    evaluate_exact_lifecycle_series,
)
from taac.health_check.health_check import types as hc_types


def _short_name(name: str) -> str:
    return name.removesuffix(".facebook.com").removesuffix(".tfbnw.net")


def _row_epoch(row: t.Any) -> t.Optional[float]:
    try:
        epoch = float(getattr(row, "request_end_epoch", 0.0) or 0.0)
        return epoch if epoch > 0 else _parse_ts(str(row.timestamp)).timestamp()
    except (AttributeError, TypeError, ValueError):
        return None


def _allowed_error_interval(
    rows: t.Sequence[t.Any], outage_start: float, service_start: float
) -> t.Sequence[t.Tuple[float, float]]:
    """Allow endpoint errors only through its first successful post-start row."""
    if outage_start <= 0 or service_start <= 0:
        return ()
    timestamped_rows = [
        (epoch, row) for row in rows if (epoch := _row_epoch(row)) is not None
    ]
    first_success = next(
        (
            epoch
            for epoch, row in sorted(timestamped_rows, key=lambda item: item[0])
            if epoch >= service_start
            and bool(getattr(row, "valid", True))
            and not str(getattr(row, "notes", "") or "").startswith("error:")
        ),
        service_start,
    )
    return ((outage_start, first_success),)


def _is_fresh_valid_row(
    row: t.Any,
    *,
    anchor_ts: float,
    matcher: t.Callable[[t.Any], bool],
) -> bool:
    """Return whether ``row`` is fresh, successful, and in the requested scope."""
    try:
        epoch = _row_epoch(row)
        return (
            matcher(row)
            and epoch is not None
            and epoch >= anchor_ts
            and bool(getattr(row, "valid", True))
            and not str(getattr(row, "notes", "") or "").startswith("error:")
        )
    except (TypeError, ValueError, AttributeError):
        return False


async def wait_for_fresh_lifecycle_samples(
    requirements: t.Sequence[t.Tuple[str, t.Any, t.Callable[[t.Any], bool]]],
    *,
    anchor_ts: float,
    timeout_sec: float,
    poll_interval_sec: float,
) -> t.Tuple[bool, t.List[str]]:
    """Wait for one fresh successful row for every lifecycle endpoint.

    This is a collector synchronization barrier, not a verdict relaxation.
    Exact values are evaluated only after the barrier, and a requirement that
    never produces a fresh valid row remains a fail-closed no-data failure.
    """
    deadline = time.monotonic() + max(0.0, timeout_sec)
    while True:
        missing = [
            label
            for label, collector, matcher in requirements
            if not any(
                _is_fresh_valid_row(
                    row,
                    anchor_ts=anchor_ts,
                    matcher=matcher,
                )
                for row in list(getattr(collector, "rows", []))
            )
        ]
        if not missing:
            return True, []
        if time.monotonic() >= deadline:
            return False, missing
        await asyncio.sleep(max(0.001, poll_interval_sec))


class FpfRemotePrefixLifecycleHealthCheck(
    AbstractDeviceHealthCheck[hc_types.BaseHealthCheckIn]
):
    """Validate exact scalar and host/device/local-plane prefix counts.

    Error rows never provide count evidence. The only tolerated errors are for
    endpoints explicitly named in ``outage_tolerant_collectors``, beginning at
    a recorded outage and ending with that endpoint's first successful sample
    after service restoration.
    """

    CHECK_NAME = hc_types.CheckName.FPF_REMOTE_PREFIX_LIFECYCLE_CHECK
    CHECK_SCOPE = hc_types.Scope.DEFAULT
    OPERATING_SYSTEMS = ["FBOSS"]

    async def _run(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        del input
        runner = check_params.get("runner_device")
        if runner and _short_name(str(obj.name)) != _short_name(str(runner)):
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.SKIP,
                message=f"Lifecycle check is owned by {runner}",
            )

        mode = str(check_params.get("mode", "present"))
        deadline_sec = float(check_params.get("deadline_sec", 120.0))
        check_started = time.time()
        if mode == "present":
            playbook_start = get_test_case_start_time()
            anchor = playbook_start or (
                check_started - float(check_params.get("baseline_window_sec", 20.0))
            )
            transition = False
        elif mode == "withdrawn":
            anchor = get_restart_completion_time()
            transition = True
        elif mode == "recovery":
            anchor = get_recovery_start_time()
            transition = True
        else:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=f"Unknown lifecycle mode {mode!r}",
            )
        if anchor <= 0:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=f"No recorded anchor timestamp for lifecycle mode {mode}",
            )

        collectors: t.Dict[str, t.Any] = {}
        failures: t.List[str] = []
        details: t.List[str] = []
        tolerant = set(check_params.get("outage_tolerant_collectors", []))

        def _collector(name: str) -> t.Any:
            if name not in collectors:
                collectors[name] = get_collector(name)
            return collectors[name]

        def _intervals(name: str, endpoint: str, rows: t.Sequence[t.Any]):
            if name not in tolerant and f"{name}@{endpoint}" not in tolerant:
                return ()
            if mode == "withdrawn":
                return _allowed_error_interval(
                    rows, get_disruption_time(), get_restart_completion_time()
                )
            if mode == "recovery":
                return _allowed_error_interval(
                    rows, get_mutation_time(), get_recovery_completion_time()
                )
            return ()

        def _evaluate(
            label: str,
            endpoint: str,
            collector_name: str,
            rows: t.Sequence[t.Any],
            expected: int,
            getter: t.Callable[[t.Any], t.Optional[int]],
        ) -> None:
            result = evaluate_exact_lifecycle_series(
                rows,
                expected=expected,
                anchor_ts=anchor,
                deadline_sec=deadline_sec,
                value_getter=getter,
                transition=transition,
                window_end_ts=now,
                allowed_error_intervals=_intervals(collector_name, endpoint, rows),
            )
            line = (
                f"[{('PASS' if result.passed else 'FAIL')}] {label}: "
                f"{result.detail}; valid={result.valid_count}, "
                f"errors={result.error_count}, ignored_errors="
                f"{result.ignored_error_count}"
            )
            details.append(line)
            if not result.passed:
                failures.append(line)

        hrt_expectations = list(check_params.get("hrt_expectations", []))
        # Named fields keep config artifacts self-describing and preserve the
        # exact manual-characterization contract.
        for key, collector_name in (
            ("a_hrt_positive_expected", "hrt"),
            ("a_hrt_remote_failure_expected", "hrt_remote_failure"),
            ("b_hrt_positive_expected", "hrt_remote_b"),
            ("b_hrt_remote_failure_expected", "hrt_remote_failure_remote_b"),
        ):
            if check_params.get(key):
                hrt_expectations.append(
                    {"collector": collector_name, "expected": check_params[key]}
                )

        if mode == "present":
            requirements: t.List[t.Tuple[str, t.Any, t.Callable[[t.Any], bool]]] = []
            for collector_name, device, _expected in check_params.get(
                "scalar_expectations", []
            ):
                collector = _collector(collector_name)
                if collector is not None:
                    requirements.append(
                        (
                            f"{collector_name}@{device}",
                            collector,
                            lambda row, device=device: _short_name(
                                str(getattr(row, "gtsw", ""))
                            )
                            == _short_name(str(device)),
                        )
                    )
            for expectation in hrt_expectations:
                collector_name = expectation["collector"]
                collector = _collector(collector_name)
                if collector is None:
                    continue
                for host, devices in expectation["expected"].items():
                    for device_id in devices:
                        requirements.append(
                            (
                                f"{collector_name}@{host}/dev{device_id}",
                                collector,
                                lambda row, host=host, device_id=device_id: (
                                    _short_name(str(getattr(row, "host", "")))
                                    == _short_name(str(host))
                                    and int(getattr(row, "device_id", -1))
                                    == int(device_id)
                                ),
                            )
                        )
            fresh, missing = await wait_for_fresh_lifecycle_samples(
                requirements,
                anchor_ts=check_started,
                timeout_sec=float(check_params.get("fresh_sample_timeout_sec", 30.0)),
                poll_interval_sec=float(
                    check_params.get("fresh_sample_poll_interval_sec", 0.25)
                ),
            )
            if not fresh:
                preview = ", ".join(missing[:12])
                if len(missing) > 12:
                    preview += f", ... (+{len(missing) - 12} more)"
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.FAIL,
                    message=(
                        "Collector synchronization timed out waiting for fresh "
                        f"valid lifecycle samples: {preview}"
                    ),
                )

        # Capture the evaluation window end only after the baseline barrier so
        # rows published while slower scalar checks run are not excluded.
        now = time.time()

        for collector_name, device, expected in check_params.get(
            "scalar_expectations", []
        ):
            collector = _collector(collector_name)
            if collector is None:
                failures.append(f"missing collector {collector_name}")
                continue
            rows = [
                row
                for row in collector.rows
                if _short_name(str(getattr(row, "gtsw", "")))
                == _short_name(str(device))
            ]
            _evaluate(
                f"{collector_name}@{device}",
                str(device),
                collector_name,
                rows,
                int(expected),
                lambda row: getattr(row, "matched", None),
            )

        for expectation in hrt_expectations:
            collector_name = expectation["collector"]
            collector = _collector(collector_name)
            if collector is None:
                failures.append(f"missing collector {collector_name}")
                continue
            for host, devices in expectation["expected"].items():
                for device_id, plane_counts in devices.items():
                    tuple_rows = [
                        row
                        for row in collector.rows
                        if _short_name(str(getattr(row, "host", "")))
                        == _short_name(str(host))
                        and int(getattr(row, "device_id", -1)) == int(device_id)
                    ]
                    for local_plane, expected in enumerate(plane_counts):
                        plane_rows = [
                            row
                            for row in tuple_rows
                            if local_plane in list(getattr(row, "plane_ids", []))
                        ]

                        def _plane_value(row: t.Any, plane: int = local_plane):
                            plane_ids = list(getattr(row, "plane_ids", []))
                            counts = list(getattr(row, "lane_counts", []))
                            if plane not in plane_ids:
                                return None
                            index = plane_ids.index(plane)
                            return counts[index] if index < len(counts) else None

                        _evaluate(
                            f"{collector_name}@{host}/dev{device_id}/lp{local_plane}",
                            str(host),
                            collector_name,
                            plane_rows,
                            int(expected),
                            _plane_value,
                        )

        unique_collectors = [
            collector for collector in collectors.values() if collector is not None
        ]
        suffix = await everpaste_details_suffix(
            f"FPF remote-prefix lifecycle ({mode})",
            details,
            collectors=unique_collectors,
        )
        if failures:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=f"{len(failures)} exact lifecycle assertion(s) failed{suffix}",
            )
        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
            message=f"All {len(details)} exact lifecycle assertions passed{suffix}",
        )
