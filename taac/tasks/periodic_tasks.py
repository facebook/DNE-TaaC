# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import asyncio
import inspect
import math
import statistics
import time
import typing as t
from datetime import datetime

from taac.constants import PeriodicCheckResult
from taac.tasks.base_task import PeriodicTask
from taac.tasks.thrift_stress_payloads import (
    READ_ONLY_FBOSS_APIS,
    ThriftStressCall,
)
from taac.utils.arista_utils import (
    get_nexthop_group_summary,
    NexthopGroupSummary,
)
from taac.utils.common import (
    async_everpaste_file,
    format_everpaste_url,
)
from taac.utils.driver_factory import async_get_device_driver
from taac.health_check.health_check import types as hc_types

try:
    from configerator.client import ConfigeratorClient
    from neteng.fboss.ngt.link_parameter_thresholds.thrift_types import (
        LinkParametersMap,
    )

    _LINK_PARAMS_CFGR_PATH = "neteng/ngt/link/link_parameter_thresholds"
    _CONFIGERATOR_AVAILABLE = True
except ImportError:
    _CONFIGERATOR_AVAILABLE = False

_DEFAULT_TEMPERATURE_THRESHOLD: t.Tuple[float, float] = (7, 78)

try:
    import matplotlib

    matplotlib.use("Agg")  # Non-interactive backend
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False


def _parse_memory_value(mem_str: str) -> int:
    """
    Parse memory value from string format to KB.

    Handles formats like:
    - "288236" (KB)
    - "3.3g" (GB)
    - "1.5m" (MB)

    Args:
        mem_str: Memory value as string

    Returns:
        Memory value in KB
    """
    mem_str = mem_str.strip().lower()

    if mem_str.endswith("g"):
        # Convert GB to KB
        return int(float(mem_str[:-1]) * 1024 * 1024)
    elif mem_str.endswith("m"):
        # Convert MB to KB
        return int(float(mem_str[:-1]) * 1024)
    else:
        # Already in KB
        return int(mem_str)


def _process_lifetime_label(process_key: str) -> str:
    """Format a ``command_pid`` key for monitored-lifetime plot labels."""
    if process_key.isdigit():
        return f"PID {process_key} — full monitored PID lifetime"

    command, separator, pid = process_key.rpartition("_")
    if not separator or not pid.isdigit():
        return f"{process_key} — full monitored PID lifetime"
    return f"{command} PID {pid} — full monitored PID lifetime"


async def _generate_multi_series_plot(
    data_series: t.Dict[str, t.Dict[t.Any, t.Any]],
    title: str,
    ylabel: str,
    threshold: t.Optional[float] = None,
    output_path: t.Optional[str] = None,
    annotations: t.Optional[t.Dict[str, t.Any]] = None,
) -> t.Optional[str]:
    """
    Generate a time-series plot with multiple data series on the same graph.

    Args:
        data_series: Dictionary mapping series names to their data
                    (each data is a dict mapping timestamps to values)
        title: Plot title
        ylabel: Y-axis label
        threshold: Optional threshold line to draw
        output_path: Optional path to save plot (default: temp file)
        annotations: Optional dictionary of custom annotations to display on the plot.
                    Each key-value pair will be displayed as "key: value" in a text box.
                    Example: {"Max Groups Configured": 140, "Test Duration": "30 min"}

    Returns:
        Path to saved plot file, or None if matplotlib unavailable or no data
    """
    if not MATPLOTLIB_AVAILABLE:
        return None

    if not data_series:
        return None

    try:
        plt.figure(figsize=(12, 6))

        colors = ["blue", "green", "orange", "red", "purple", "brown", "pink", "gray"]
        markers = ["o", "s", "^", "D", "v", "<", ">", "p"]

        for idx, (series_name, data) in enumerate(data_series.items()):
            if not data:
                continue

            sorted_data = sorted(data.items(), key=lambda x: float(x[0]))
            timestamps = [datetime.fromtimestamp(float(ts)) for ts, _ in sorted_data]
            values = [val for _, val in sorted_data]

            color = colors[idx % len(colors)]
            marker = markers[idx % len(markers)]

            plt.plot(
                timestamps,
                values,
                marker=marker,
                linestyle="-",
                linewidth=2,
                markersize=6,
                label=series_name,
                color=color,
            )

        if threshold is not None:
            plt.axhline(
                y=threshold,
                color="r",
                linestyle="--",
                linewidth=2,
                label=f"Threshold: {threshold}",
            )

        plt.xlabel("Time", fontsize=12)
        plt.ylabel(ylabel, fontsize=12)
        plt.title(title, fontsize=14, fontweight="bold")
        plt.grid(True, alpha=0.3, linestyle=":", linewidth=0.5)
        plt.xticks(rotation=45, ha="right")
        plt.legend(loc="best")

        # Add custom annotations if provided
        if annotations:
            annotation_text = "\n".join(
                f"{key}: {value}" for key, value in annotations.items()
            )
            # Position the text box in the upper left corner
            plt.gca().text(
                0.02,
                0.98,
                annotation_text,
                transform=plt.gca().transAxes,
                fontsize=10,
                verticalalignment="top",
                horizontalalignment="left",
                bbox={"boxstyle": "round", "facecolor": "wheat", "alpha": 0.5},
            )

        plt.tight_layout()

        if output_path is None:
            import tempfile

            fd, output_path = tempfile.mkstemp(suffix=".png", prefix="periodic_task_")
            import os

            os.close(fd)

        plt.savefig(output_path, dpi=100, bbox_inches="tight")
        plt.close()

        return output_path
    except Exception as e:
        import logging

        logging.getLogger(__name__).warning(
            f"Failed to generate multi-series plot: {e}"
        )
        return None


async def _generate_plot(
    data: t.Dict[t.Any, t.Any],
    title: str,
    ylabel: str,
    threshold: t.Optional[float] = None,
    output_path: t.Optional[str] = None,
    y_axis_starts_at_zero: bool = False,
) -> t.Optional[str]:
    """
    Generate a time-series plot from collected data.

    Args:
        data: Dictionary mapping timestamps to values
        title: Plot title
        ylabel: Y-axis label
        threshold: Optional threshold line to draw
        output_path: Optional path to save plot (default: temp file)
        y_axis_starts_at_zero: Anchor the Y axis at zero.

    Returns:
        Path to saved plot file, or None if matplotlib unavailable or no data
    """
    if not MATPLOTLIB_AVAILABLE:
        return None

    if not data:
        return None

    try:
        # Sort data by timestamp (convert keys to float for proper numeric sorting)
        sorted_data = sorted(data.items(), key=lambda x: float(x[0]))
        timestamps = [datetime.fromtimestamp(float(ts)) for ts, _ in sorted_data]
        values = [val for _, val in sorted_data]

        # Create plot
        plt.figure(figsize=(12, 6))
        plt.plot(
            timestamps,
            values,
            marker="o",
            linestyle="-",
            linewidth=2,
            markersize=6,
            label="Measured Value",
        )

        # Add threshold line if provided
        if threshold is not None:
            plt.axhline(
                y=threshold,
                color="r",
                linestyle="--",
                linewidth=2,
                label=f"Threshold: {threshold}",
            )

        # Format plot
        plt.xlabel("Time", fontsize=12)
        plt.ylabel(ylabel, fontsize=12)
        plt.title(title, fontsize=14, fontweight="bold")
        plt.grid(True, alpha=0.3, linestyle=":", linewidth=0.5)
        plt.gca().xaxis.set_major_formatter(mdates.DateFormatter("%b %d %H:%M"))
        if y_axis_starts_at_zero:
            plt.ylim(bottom=0)
        plt.xticks(rotation=45, ha="right")
        plt.legend(loc="best")
        plt.tight_layout()

        # Save plot
        if output_path is None:
            import tempfile

            fd, output_path = tempfile.mkstemp(suffix=".png", prefix="periodic_task_")
            import os

            os.close(fd)

        plt.savefig(output_path, dpi=100, bbox_inches="tight")
        plt.close()

        return output_path
    except Exception as e:
        # Don't fail the check if plotting fails
        import logging

        logging.getLogger(__name__).warning(f"Failed to generate plot: {e}")
        return None


class CounterThresholdBreach(Exception):
    """Raised by CounterThresholdTask when a sampled counter exceeds its
    threshold mid-run and the task is configured with ``fail_on_breach=True``.

    It propagates to PeriodicTaskWorker, which — when the PeriodicTask has
    ``terminate_on_error=True`` — terminates the test as a failure.
    """


class CounterThresholdTask(PeriodicTask):
    NAME = "counter_utilization"
    _COLLECTION_ERROR_COUNT = "__collection_error_count"
    _LAST_COLLECTION_ERROR = "__last_collection_error"

    async def _run(self, params: t.Dict[str, t.Any]) -> None:
        error_count = self._params.get(self._COLLECTION_ERROR_COUNT, 0)
        last_error = self._params.get(self._LAST_COLLECTION_ERROR)
        self._params.clear()
        self._params.update(params)
        if error_count:
            self._params[self._COLLECTION_ERROR_COUNT] = error_count
        if last_error is not None:
            self._params[self._LAST_COLLECTION_ERROR] = last_error
        await self.run(params)

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        """
        Collects counter data and stores it for final check.

        Args:
            params:
                - hostname: Device hostname (required)
                - key: ODS key to query (required)
                - threshold: Threshold for counter utilization (required)
                - cpu_count: Number of CPU cores on the device. When provided,
                    the counter value is divided by this number to get
                    system-level CPU utilization percentage. Use this when the
                    counter reports per-core cumulative CPU
                    (e.g., bgpd.process.cpu.percent where 400 = 4 cores fully
                    used). Default: None (no normalization).
                - fail_on_breach: When True, raise ``CounterThresholdBreach``
                    the moment a sample exceeds ``threshold`` so the
                    PeriodicTaskWorker (with ``terminate_on_error=True``) fails
                    the test mid-run. When False (default), a breach only warns
                    and is left to the non-gating final check. Default: False.
        """
        hostname = params["hostname"]
        key = params["key"]
        threshold = params["threshold"]
        cpu_count = params.get("cpu_count", None)
        fail_on_breach = params.get("fail_on_breach", False)

        counter = None
        try:
            self.logger.info(f"Attempting to get counter {key} from {hostname}")
            driver = await async_get_device_driver(hostname)
            # pyre-fixme[16]: `AbstractSwitch` has no attribute `async_get_counter`.
            counter = await driver.async_get_counter(key)
            self.logger.info(f"Successfully got counter {key} raw value: {counter}")

            if cpu_count is not None:
                counter = counter / cpu_count
                self.logger.info(
                    f"Normalized {key} by {cpu_count} cores: {counter:.2f}%"
                )

            self.add_data(counter)
        except Exception as e:
            self._params[self._COLLECTION_ERROR_COUNT] = (
                int(self._params.get(self._COLLECTION_ERROR_COUNT, 0)) + 1
            )
            self._params[self._LAST_COLLECTION_ERROR] = f"{type(e).__name__}: {e}"
            self.logger.error(
                f"Error collecting counter data for {key}: {e}", exc_info=True
            )
            return

        # Threshold evaluation is intentionally OUTSIDE the collection
        # try/except: a fail_on_breach raise must propagate to the worker (which
        # terminates the test) rather than being swallowed as a collection error.
        if counter > threshold:
            if fail_on_breach:
                raise CounterThresholdBreach(
                    f"{key} value {counter} exceeded threshold {threshold} "
                    f"mid-run on {hostname}; failing test (fail_on_breach=True)."
                )

            self.logger.warning(
                f"{key} value {counter} exceeds threshold {threshold} (will check max at end)"
            )
        else:
            self.logger.info(f"{key} value {counter} is within threshold {threshold}")

    async def run_final_check(self) -> t.Optional[PeriodicCheckResult]:
        """
        Checks if the maximum collected counter value is above threshold.
        Optionally generates a time-series plot if enable_plotting param is True.

        Returns:
            PeriodicCheckResult with PASS if max is below/equal to threshold, FAIL otherwise
        """
        self.logger.info(
            f"run_final_check called: self._data has {len(self._data)} entries"
        )
        self.logger.info(
            f"run_final_check: self._data = {dict(self._data) if self._data else {}}"
        )
        if not self._data:
            return PeriodicCheckResult(
                # pyrefly: ignore [bad-argument-type]
                name=self.NAME,
                status=hc_types.HealthCheckStatus.ERROR,
                message=self._collection_summary(
                    "No data collected during periodic task execution"
                ),
            )

        max_counter = max(self._data.values())
        threshold = self._params.get("threshold")

        if threshold is None:
            return PeriodicCheckResult(
                # pyrefly: ignore [bad-argument-type]
                name=self.NAME,
                status=hc_types.HealthCheckStatus.ERROR,
                message="Threshold parameter not available for final check",
            )

        key = self._params.get("key", "counter")

        # Determine status and base message
        if max_counter > threshold:
            status = hc_types.HealthCheckStatus.FAIL
            message = f"Max {key} value {max_counter} exceeded threshold {threshold}"
        else:
            status = hc_types.HealthCheckStatus.PASS
            message = f"Max {key} value {max_counter} is within threshold {threshold}"

        message = self._collection_summary(message)

        # Generate plot if enabled via params
        enable_plotting = self._params.get("enable_plotting", False)
        if enable_plotting:
            plot_path = await _generate_plot(
                data=dict(self._data),
                title=f"Counter Utilization Over Time: {key}",
                ylabel=key,
                threshold=threshold,
                y_axis_starts_at_zero=True,
            )
            if plot_path:
                # Upload to everpaste
                try:
                    plot_url = format_everpaste_url(
                        await async_everpaste_file(plot_path, extension="png")
                    )
                    message += f"\nPlot: {plot_url}"
                    self.logger.info(f"Plot uploaded to: {plot_url}")
                except Exception as e:
                    self.logger.warning(f"Failed to upload plot: {e}")

        return PeriodicCheckResult(
            # pyrefly: ignore [bad-argument-type]
            name=self.NAME,
            status=status,
            message=message,
        )

    def _collection_summary(self, message: str) -> str:
        error_count = int(self._params.get(self._COLLECTION_ERROR_COUNT, 0))
        if not error_count:
            return message
        last_error = self._params.get(self._LAST_COLLECTION_ERROR, "unknown")
        return (
            f"{message}; collection_errors={error_count}; "
            f"last_collection_error={last_error}"
        )


def _unprogrammed_verdict(
    series: t.Dict[float, int],
    maximum: int,
    tolerance_samples: t.Optional[int],
) -> t.Tuple[bool, str]:
    """Verdict on the device's own "I could not program this group" counter.

    A max-over-the-run comparison is the wrong SHAPE here, and a hardware run
    proved it: across 391 samples of a five-cycle drain the counter read 0 in
    390 and 4 in exactly ONE, caught mid-rebuild with the group widths climbing
    1, 2, 3, 12, 13 ... 26 as peers returned to the next-hop sets. Five seconds
    later it was 0 again. Group creation and hardware programming are not
    atomic, so a poll landing inside a rebuild sees groups in flight, and
    ``max == 0`` asserts something an asynchronous pipeline cannot promise. One
    drain cycle hid this; five cycles are five rebuilds and five chances for the
    poll to land in one.

    What IS assertable is that groups do not STAY unprogrammed. One in flight
    for a poll interval is the pipeline working; one still unprogrammed seconds
    later is blackholing traffic. So this gates on the longest CONSECUTIVE run
    above the ceiling, not on the peak -- the same duration-not-magnitude
    principle the converged and recovery verdicts already use.

    With ``tolerance_samples`` unset the behaviour is exactly the old one: any
    exceedance at all is a breach.

    The empty-series case stays a FAILURE here rather than a guard at the call
    site. It is unreachable through ``run_final_check`` -- that series is filled
    in the same ``isinstance`` arm as the count series, whose emptiness already
    returned -- so at the call site it would be a branch no test could execute,
    and ``max()`` below would raise on it rather than report it.
    """
    if not series:
        return True, (
            "unprogrammed NOT EVALUATED: max_unprogrammed was set but no "
            "num_unprogrammed_groups samples were recorded, so the device's "
            "own hardware-rejection signal was never read"
        )
    ordered = [series[ts] for ts in sorted(series)]
    peak = max(ordered)
    longest = current = 0
    for value in ordered:
        current = current + 1 if value > maximum else 0
        longest = max(longest, current)
    detail = (
        f"peak {peak}, longest consecutive run above {maximum} = {longest} of "
        f"{len(ordered)} samples"
    )
    if longest == 0:
        return False, f"unprogrammed OK: never exceeded {maximum} ({detail})"
    if tolerance_samples is None:
        return (
            True,
            f"unprogrammed BREACH: {detail} -- the device could not program at "
            f"least one nexthop group",
        )
    if longest <= tolerance_samples:
        return (
            False,
            f"unprogrammed OK: exceeded {maximum} only transiently ({detail}), "
            f"within the {tolerance_samples}-sample tolerance -- consistent "
            f"with groups in flight during a rebuild",
        )
    return (
        True,
        f"unprogrammed BREACH: {detail}, beyond the {tolerance_samples}-sample "
        f"tolerance -- groups STAYED unprogrammed rather than being momentarily "
        f"in flight, so the device is failing to program them",
    )


def _count_multiway_groups(sizes: t.Dict[int, int], min_width: int) -> int:
    """Number of nexthop groups at least ``min_width`` next-hops wide.

    ``num_groups_configured`` counts EVERY group, including width-1 ones. A
    width-1 group is not an ECMP set -- it is a single next-hop that happens to
    be expressed as a group. Conflating the two makes the count report the wrong
    event: when a DUT sheds its ECMP structure into per-peer singletons the
    total *rises* sharply, so a "too many ECMP sets" gate fires on what is
    actually a loss of ECMP.

    Observed on bag013 (release 191): the healthy shape is ``{128: 2}`` -- two
    real 128-way sets, one per AFI -- and the count is 2. During the collapse
    the shape became ``{1: 256, 128: 2}`` and then ``{1: 256}``, so the count
    read 258 and then 256 while the number of genuine ECMP sets went 2 -> 2 -> 0.
    """
    return sum(count for width, count in sizes.items() if width >= min_width)


def _series_window(series: t.Dict[float, t.Any], count: int, last: bool) -> t.List:
    """First or last ``count`` values of a timestamp-keyed series, in time order."""
    ordered = [series[ts] for ts in sorted(series)]
    if count <= 0 or count >= len(ordered):
        return ordered
    return ordered[-count:] if last else ordered[:count]


def _checked_int(
    params: t.Mapping[str, t.Any],
    name: str,
    problems: t.List[str],
    *,
    minimum: int,
) -> t.Optional[int]:
    """``int(params[name])`` with a coercion failure turned into a verdict.

    A bare ``int()`` here was the one place the misconfiguration DETECTOR could
    itself crash: a non-numeric value raised ValueError straight out of
    ``run_final_check`` instead of being reported as the config breach it is.
    That is the exact failure mode this function exists to convert into a
    verdict, so it must not be the one that escapes as an exception.

    Returns None -- and records a problem -- when the value is unusable, so the
    caller can skip any further reasoning about it.
    """
    value = params.get(name)
    if value is None:
        return None
    try:
        coerced = int(value)
    except (TypeError, ValueError):
        problems.append(f"{name} must be an integer, got {value!r}")
        return None
    if coerced < minimum:
        problems.append(f"{name} must be >= {minimum}, got {coerced}")
        return None
    return coerced


def _misconfigured_params(params: t.Dict[str, t.Any]) -> t.List[str]:
    """Opt-in params that were requested but cannot produce a verdict.

    Silence is the wrong response to a misconfigured gate: the caller asked for
    an assertion and would otherwise get a green run with no assertion.
    """
    problems: t.List[str] = []
    if params.get("max_multiway_groups") is not None and (
        params.get("min_ecmp_width") is None
    ):
        problems.append(
            "max_multiway_groups was set without min_ecmp_width, so the "
            "ECMP-set ceiling cannot be evaluated"
        )
    if params.get("recovery_window_samples") is not None and (
        params.get("recovery_tolerance") is None
    ):
        problems.append(
            "recovery_window_samples was set without recovery_tolerance, so "
            "the recovery gate is inert"
        )
    _checked_int(params, "recovery_window_samples", problems, minimum=1)
    _checked_int(params, "min_samples", problems, minimum=1)
    # 0 is meaningful here: "no exceedance tolerated", i.e. the pre-tolerance
    # behaviour stated explicitly rather than by omission.
    _checked_int(params, "unprogrammed_tolerance_samples", problems, minimum=0)
    if params.get("unprogrammed_tolerance_samples") is not None and (
        params.get("max_unprogrammed") is None
    ):
        problems.append(
            "unprogrammed_tolerance_samples was set without max_unprogrammed, "
            "so there is no unprogrammed ceiling for it to soften"
        )
    _checked_int(params, "expected_converged_multiway_groups", problems, minimum=0)
    # The closing window must be ODD. statistics.median AVERAGES the two middle
    # values of an even-length window, so a window straddling 2 and 3 medians to
    # 2.5 -- and 2.5 never equals an integer expectation, so a HEALTHY device
    # breaches. This is not theoretical: the first fully green run logged
    # "settled at 2.0", a float, and passed only because all ten closing samples
    # happened to be identical. An odd window always medians to a real observed
    # sample.
    converged_window = _checked_int(
        params, "converged_window_samples", problems, minimum=1
    )
    if converged_window is not None and converged_window % 2 == 0:
        problems.append(
            f"converged_window_samples must be ODD, got {converged_window}: an "
            f"even window medians to the average of its two middle samples, so "
            f"a window straddling two values yields a half-integer that can "
            f"never equal the expected count -- a healthy device would breach"
        )
    if params.get("expected_converged_multiway_groups") is not None and (
        params.get("min_ecmp_width") is None
    ):
        problems.append(
            "expected_converged_multiway_groups was set without min_ecmp_width, "
            "so there is no multi-way series to settle"
        )
    # The recovery band is baseline/tolerance .. baseline*tolerance, so the
    # parameter is only meaningful at >= 1. Zero divides; anything in (0, 1)
    # INVERTS the band (low > high), which no value can satisfy, so the gate
    # would fail every run for a reason the message would not explain; and a
    # non-finite tolerance widens the band to admit everything.
    tolerance = params.get("recovery_tolerance")
    if tolerance is not None:
        try:
            numeric_tolerance = float(tolerance)
        except (TypeError, ValueError):
            problems.append(f"recovery_tolerance must be a number, got {tolerance!r}")
        else:
            if not math.isfinite(numeric_tolerance) or numeric_tolerance < 1:
                problems.append(
                    f"recovery_tolerance must be a finite value >= 1, got "
                    f"{tolerance}: 0 raises, 0 < tolerance < 1 inverts the "
                    f"recovery band so no value can satisfy it, and an infinite "
                    f"tolerance admits anything"
                )
    return problems


def _observation_verdict(observed_max: int, floor: int) -> t.Tuple[bool, str]:
    """Verdict on whether the metric observed anything plausible at all.

    An all-zero series is not empty, so it clears the empty-series guard and
    then satisfies any ceiling. On bag012 this metric read 0 for all 884
    samples and the suite passed repeatedly on a structurally blind gate.
    """
    if observed_max >= floor:
        return (
            False,
            f"observation OK: peak nexthop-group count {observed_max} reaches "
            f"the expected floor ({floor})",
        )
    return (
        True,
        f"observation BREACH: peak nexthop-group count {observed_max} never "
        f"reached the expected floor ({floor}) -- the metric is reporting "
        f"values but they are implausible for this topology, so any ceiling "
        f"above it is vacuous",
    )


def _ecmp_set_verdict(
    sizes_data: t.Dict[float, t.Dict[int, int]],
    min_ecmp_width: int,
    max_multiway_groups: t.Optional[int],
) -> t.Tuple[bool, str]:
    """Verdict on the number of REAL (multi-way) ECMP sets.

    Returns ``(is_failure, message)``. With no ceiling supplied this is
    observe-and-report, so a caller can land the measurement before committing
    to a number.
    """
    # An empty histogram is not evidence of zero ECMP sets -- it is evidence of
    # nothing parsed. The size table has no found-flag in the parser, so a
    # wording or column change yields sizes={} for every sample, which would
    # otherwise read as a confident "0 groups >= N wide" and PASS.
    if not any(sizes for sizes in sizes_data.values()):
        return (
            True,
            "ecmp-sets NOT EVALUATED: every sample reported an empty "
            "nexthop-group size histogram, so no ECMP set could be counted -- "
            "this is a parse or collection failure, not a device with no "
            "nexthop groups",
        )
    multiway = max(
        _count_multiway_groups(sizes, min_ecmp_width) for sizes in sizes_data.values()
    )
    singletons = max(sizes.get(1, 0) for sizes in sizes_data.values())
    detail = (
        f"max groups >= {min_ecmp_width}-wide = {multiway}, "
        f"max width-1 groups = {singletons}"
    )
    if multiway == 0:
        return (
            True,
            f"ecmp-sets BREACH: {detail} -- the device reported nexthop groups "
            f"but not one of them was {min_ecmp_width} next-hops wide, so ECMP "
            f"was never formed (or was entirely destroyed)",
        )
    if max_multiway_groups is None:
        return False, f"ecmp-sets OBSERVED: {detail}"
    if multiway <= max_multiway_groups:
        # The bound is rendered NEXT TO the quantity it bounds. Trailing it
        # after the whole detail put it immediately after the width-1 count,
        # where it read as a ceiling on singleton groups -- which it is not.
        return (
            False,
            f"ecmp-sets OK: max groups >= {min_ecmp_width}-wide = {multiway} "
            f"(allowed {max_multiway_groups}), "
            f"max width-1 groups = {singletons}",
        )
    return (
        True,
        f"ecmp-sets BREACH: {detail} exceeds the allowed maximum "
        f"({max_multiway_groups})",
    )


# ODD on purpose -- see the converged_window_samples check in
# _misconfigured_params. An even default would make the half-integer median trap
# reachable by every caller that does not think to override it.
_DEFAULT_CONVERGED_WINDOW_SAMPLES = 11
_DEFAULT_RECOVERY_WINDOW_SAMPLES = 10

# The fraction of the closing window that must agree with its own median before
# that median is treated as a SETTLED value. FITTED to observed shapes, not
# derived: a run that reaches its soak holds one value across the entire window
# (100%), while SC9 run 9 -- whose drain aborted mid-cycle, so the window
# covered a drained device, a rebuild and the recovered steady state -- split
# 17/11/3 across three values and its median held only 55%. Three quarters sits
# well clear of both and still tolerates a sampling artifact per four samples,
# which is the whole reason the verdict medians rather than reading the last
# sample.
_CONVERGED_WINDOW_DOMINANCE = 0.75


def _converged_verdict(
    series: t.Dict[float, int], expected: int, window: int, metric: str
) -> t.Tuple[bool, str]:
    """Verdict on whether ``metric`` SETTLED at its expected steady-state value.

    ``window`` must be ODD, which ``_misconfigured_params`` enforces for any
    caller that sets it and ``_DEFAULT_CONVERGED_WINDOW_SAMPLES`` guarantees for
    every caller that does not. The median of an even window is the AVERAGE of
    its two middle samples, so a window straddling two values produces a
    half-integer that cannot equal the integer expectation.

    Distinct from ``_recovery_verdict``, and usable where that one is not. The
    recovery check compares the closing window against the OPENING window, and
    the opening window is unreliable here: periodic tasks start in
    ``async_test_case_setUp``, before ``setup_steps``, so on a scale test the
    first samples predate convergence and the baseline reads zero. This compares
    the closing window against a LITERAL expected value instead, which needs no
    opening baseline at all.

    It is also the only thing that tests the steady state. Every other verdict
    on this task is a maximum over the whole run, so a device that idles at five
    ECMP sets is indistinguishable from one that idles at the two the topology
    should produce.

    Uses the MEDIAN of the closing window so one sampling artifact cannot decide
    the verdict, and requires that median to be DOMINANT within the window --
    see ``_CONVERGED_WINDOW_DOMINANCE`` -- so that a run which never reached a
    steady state is reported as unevaluated rather than as a device left in
    whatever state the run was interrupted in. Returns ``(is_failure, message)``.
    """
    ordered = sorted(series)
    if len(ordered) < window:
        return (
            True,
            f"converged NOT EVALUATED: {len(ordered)} samples is fewer than the "
            f"{window} needed for a closing window, so the settled value of "
            f"{metric} could not be assessed -- failing rather than passing an "
            f"unevaluated gate",
        )
    values = _series_window(series, window, last=True)
    final = statistics.median(values)
    # A median is only a SETTLED value if the window it came from had settled.
    # Without this, an aborted run reports the state it was interrupted in as
    # though the device had been left there: SC9 run 9's drain failed in cycle 3
    # of 5, so Stage C's soak never ran, the closing window covered the drained
    # and rebuilding device, and the verdict read "settled at 0" -- i.e. every
    # ECMP set destroyed -- about a device that was sitting at the correct
    # {128: 2} in its final samples.
    #
    # This can never convert a real BREACH into a pass. A device genuinely stuck
    # at the wrong value produces a FLAT closing window, which is dominant by
    # definition and still evaluated. It only abstains where the run did not end
    # in a steady state at all -- and per this file's policy, abstaining is
    # itself a failure, so nothing is laundered into a green run either.
    agreeing = values.count(final)
    dominance = agreeing / len(values)
    if dominance < _CONVERGED_WINDOW_DOMINANCE:
        return (
            True,
            f"converged NOT EVALUATED: only {agreeing} of {len(values)} closing "
            f"samples hold the median value {final} ({dominance:.0%}, floor "
            f"{_CONVERGED_WINDOW_DOMINANCE:.0%}), so the window never settled "
            f"and no steady-state value of {metric} can be read from it. This is "
            f"what an ABORTED run looks like -- the closing window covers "
            f"whatever the device was doing when the run stopped, not a "
            f"post-soak steady state -- so diagnose the step that aborted, not "
            f"this gate",
        )
    if final == expected:
        return (
            False,
            f"converged OK: {metric} settled at {final}, the expected steady state",
        )
    return (
        True,
        f"converged BREACH: {metric} settled at {final}, not the expected "
        f"{expected}. The closing window is post-soak, so this is the state the "
        f"device was LEFT in, not a transient -- a value above {expected} means "
        f"ECMP sets that never collapsed back, and below means sets that never "
        f"formed",
    )


def _recovery_verdict(
    series: t.Dict[float, int], tolerance: float, window: int, metric: str
) -> t.Tuple[bool, str]:
    """Verdict on whether ``metric`` returned to its opening baseline.

    A bounded transient collapses back; a structural regression does not. This
    separates the two by DURATION rather than magnitude, so it needs no
    calibrated ceiling. Returns ``(is_failure, message)``.

    The two windows must be DISJOINT. ``_series_window`` returns the whole
    series when the requested count exceeds its length, so on a short series
    the baseline and closing windows would be the same samples, making
    ``final == baseline`` and the gate pass for any tolerance >= 1 -- a
    vacuous pass of exactly the kind this check exists to prevent. Too few
    samples is therefore a FAILURE to evaluate, not a pass.
    """
    ordered = sorted(series)
    if len(ordered) < 2 * window:
        return (
            True,
            f"recovery NOT EVALUATED: {len(ordered)} samples is fewer than the "
            f"{2 * window} needed for disjoint baseline and closing windows of "
            f"{window}, so recovery of {metric} could not be assessed -- "
            f"failing rather than passing an unevaluated gate",
        )
    # Median, not max. A single spike inside the opening window would inflate
    # the baseline and make the whole gate permissive; a single spike in the
    # closing window would make a recovered run look broken.
    baseline = statistics.median(_series_window(series, window, last=False))
    final = statistics.median(_series_window(series, window, last=True))

    # A zero baseline means the opening window saw nothing to recover TO --
    # almost always because the poll starts in async_test_case_setUp, before
    # setup_steps and convergence. Any ratio against 0 is meaningless, so
    # refuse rather than produce a verdict that looks authoritative.
    if baseline <= 0:
        return (
            True,
            f"recovery NOT EVALUATED: the baseline window of {metric} is "
            f"{baseline}, so there is no steady state to compare against -- the "
            f"opening window most likely predates convergence. Start the poll "
            f"later or widen recovery_window_samples",
        )

    # TWO-SIDED. An upper bound alone passes a collapse: on the real bag013
    # series the multi-way count went 2 -> 0 and "settled at 0", which is every
    # ECMP set destroyed, yet 0 <= 2 * 1.5 and the gate said OK. Recovery means
    # returning to the steady state, not merely staying under it.
    low, high = baseline / tolerance, baseline * tolerance
    if low <= final <= high:
        return (
            False,
            f"recovery OK: {metric} settled at {final} against a baseline of "
            f"{baseline} (allowed {low:g}-{high:g}, window {window} samples)",
        )
    direction = "below" if final < low else "above"
    return (
        True,
        f"recovery BREACH: {metric} settled at {final}, {direction} the "
        f"allowed band {low:g}-{high:g} around its baseline of {baseline} -- it "
        f"never returned to its steady state, so this is a persistent change, "
        f"not a transient",
    )


class NexthopGroupPoll(PeriodicTask):
    NAME = "nexthop_group_poll"

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        """
        Collects nexthop group summary data from the device and stores it for final check.

        Args:
            params:
                - hostname: Device hostname (required)
                - threshold: Threshold for num_groups_configured (required)
        """
        hostname = params["hostname"]
        try:
            self.logger.info(f"Attempting to get nexthop group summary from {hostname}")
            driver = await async_get_device_driver(hostname)
            output: NexthopGroupSummary = await get_nexthop_group_summary(driver)
            self.logger.info(f"Successfully got nexthop group summary: {output}")

            # Log nexthop group sizes data
            if output.nexthop_group_sizes:
                self.logger.info("Nexthop group sizes breakdown:")
                for size, count in sorted(output.nexthop_group_sizes.items()):
                    self.logger.info(f"  Size {size}: {count} group(s) configured")
            else:
                self.logger.info("No nexthop group sizes data available")

            self.add_data(output)

            # Display max num_groups_configured across all collected data
            if self._data:
                max_num_groups = max(
                    summary.num_groups_configured
                    for summary in self._data.values()
                    if isinstance(summary, NexthopGroupSummary)
                )
                self.logger.info(
                    f"Current max num_groups_configured across all samples: {max_num_groups}"
                )

        except Exception as e:
            self.logger.error(
                f"Error collecting nexthop group summary data: {e}", exc_info=True
            )

    async def run_final_check(self) -> t.Optional[PeriodicCheckResult]:
        """
        Analyzes collected nexthop group data and generates a multi-series plot.

        Independent verdicts, reported separately so triage can tell them apart.
        Only the first is always on; every other one is opt-in via a param, so
        existing callers are unaffected until they ask for it:

        1. ``max(num_groups_configured) < threshold`` -- the transient ECMP-set
           ceiling.
        2. ``max(num_unprogrammed_groups) <= max_unprogrammed`` -- the device's
           own "I could not program this group" signal, i.e. the closest thing
           the box reports to "the hardware table is full".
        3. ``len(samples) >= min_samples`` -- the poll stayed alive.
        4. multi-way ECMP-set count and ceiling (``min_ecmp_width`` /
           ``max_multiway_groups``).
        5. the settled multi-way count (``expected_converged_multiway_groups``).
        6. a floor on what was observed at all (``min_observed_groups``).
        7. recovery to the opening baseline (``recovery_tolerance``).

        Collecting no data is a FAILURE, not a SKIP. ``run`` swallows every
        collection exception, so an empty series means every single poll failed
        -- reporting SKIP there let the check pass having proven nothing. An
        entirely empty series is caught below; a series that merely lost most of
        its samples is what ``min_samples`` is for.

        Returns:
            PeriodicCheckResult: PASS only when every enabled verdict passes.
        """
        self.logger.info(
            f"NexthopGroupPoll run_final_check: self._data has {len(self._data)} entries"
        )

        if not self._data:
            return PeriodicCheckResult(
                # pyrefly: ignore [bad-argument-type]
                name=self.NAME,
                status=hc_types.HealthCheckStatus.FAIL,
                message=(
                    "No nexthop-group data collected during the run. run() logs "
                    "and swallows every collection failure, so an empty series "
                    "means every poll failed and the ceiling was never measured "
                    "-- failing rather than reporting an unverified pass."
                ),
            )

        threshold = self._params.get("threshold")

        if threshold is None:
            return PeriodicCheckResult(
                # pyrefly: ignore [bad-argument-type]
                name=self.NAME,
                status=hc_types.HealthCheckStatus.ERROR,
                message="Threshold parameter not available for final check",
            )

        num_groups_configured_data: t.Dict[float, int] = {}
        num_unprogrammed_groups_data: t.Dict[float, int] = {}
        # Width histogram per sample, so the verdict can separate real ECMP sets
        # from width-1 groups. Without it the count conflates the two -- see
        # _count_multiway_groups.
        sizes_data: t.Dict[float, t.Dict[int, int]] = {}

        for timestamp, summary in self._data.items():
            if isinstance(summary, NexthopGroupSummary):
                num_groups_configured_data[timestamp] = summary.num_groups_configured
                num_unprogrammed_groups_data[timestamp] = (
                    summary.num_unprogrammed_groups
                )
                sizes_data[timestamp] = summary.nexthop_group_sizes or {}

        if not num_groups_configured_data:
            return PeriodicCheckResult(
                # pyrefly: ignore [bad-argument-type]
                name=self.NAME,
                status=hc_types.HealthCheckStatus.FAIL,
                message=(
                    "Samples were recorded but none was a NexthopGroupSummary, "
                    "so no nexthop-group count could be evaluated."
                ),
            )

        max_num_groups_configured = max(num_groups_configured_data.values())

        # Log the max value
        self.logger.info(
            f"Final max num_groups_configured across all samples: {max_num_groups_configured}"
        )

        # A gate that was asked for but cannot run must say so, not stay silent.
        # Each of these combinations previously produced no verdict at all, so a
        # typo in a TestConfig disabled the gate invisibly.
        #
        # This RETURNS rather than accumulating a failure and carrying on: a
        # parameter that failed validation must not then be used. Reporting
        # recovery_tolerance=0 as a breach and then passing that same 0 to
        # _recovery_verdict divides by it, so the config error escaped as a
        # ZeroDivisionError instead of a verdict. A broken gate needs a
        # corrected config and a re-run regardless, so the remaining verdicts
        # would be scored against a configuration nobody intended.
        problems = _misconfigured_params(self._params)
        if problems:
            return PeriodicCheckResult(
                # pyrefly: ignore [bad-argument-type]
                name=self.NAME,
                status=hc_types.HealthCheckStatus.FAIL,
                message="; ".join(f"config BREACH: {problem}" for problem in problems),
            )

        verdicts: t.List[str] = []
        failures: t.List[str] = []

        if max_num_groups_configured < threshold:
            verdicts.append(
                f"count OK: max num_groups_configured "
                f"({max_num_groups_configured}) is below threshold ({threshold})"
            )
        else:
            failures.append(
                f"count BREACH: max num_groups_configured "
                f"({max_num_groups_configured}) meets or exceeds threshold "
                f"({threshold})"
            )

        # Opt-in second verdict. `num_unprogrammed_groups` is the device's own
        # report that it could not program a group -- the most direct signal
        # available that a hardware table was exceeded. It has always been
        # sampled and plotted; until now nothing asserted on it. See
        # `_unprogrammed_verdict` for why the empty case is a failure and why
        # the check lives there rather than inline here.
        max_unprogrammed = self._params.get("max_unprogrammed")
        if max_unprogrammed is not None:
            tolerance = self._params.get("unprogrammed_tolerance_samples")
            failed, text = _unprogrammed_verdict(
                num_unprogrammed_groups_data,
                int(max_unprogrammed),
                None if tolerance is None else int(tolerance),
            )
            (failures if failed else verdicts).append(text)

        # Opt-in: a floor on HOW MANY samples the run collected at all. `run`
        # swallows every collection exception and the guard above fails only on
        # an ENTIRELY empty series, so a run that lost most of its polls still
        # evaluates every verdict here on the survivors -- and reports them with
        # exactly the same confidence as a complete series. The first clean SC9
        # run recorded 195 samples and nothing remarked on it either way.
        #
        # This is a liveness floor, not a completeness assertion: the exact count
        # is appended to every message regardless, so the number is always
        # visible even when this gate is not set.
        min_samples = self._params.get("min_samples")
        if min_samples is not None:
            collected = len(num_groups_configured_data)
            if collected >= min_samples:
                verdicts.append(
                    f"samples OK: collected {collected} nexthop-group samples "
                    f"(floor {min_samples})"
                )
            else:
                failures.append(
                    f"samples BREACH: collected only {collected} nexthop-group "
                    f"samples against a floor of {min_samples} -- the poll lost "
                    f"most of its reads, so every other verdict here was scored "
                    f"on an unrepresentative subset of the run"
                )

        # Opt-in third verdict: the ECMP-set ceiling measured on REAL sets only.
        # This is the quantity the "bounded number of programmed ECMP sets"
        # characteristic is actually about; the raw count above cannot tell a
        # genuine ECMP-set increase from a collapse into width-1 singletons.
        min_ecmp_width = self._params.get("min_ecmp_width")
        multiway_series: t.Optional[t.Dict[float, int]] = None
        if min_ecmp_width is not None and sizes_data:
            multiway_series = {
                ts: _count_multiway_groups(sizes, min_ecmp_width)
                for ts, sizes in sizes_data.items()
            }
            failed, text = _ecmp_set_verdict(
                sizes_data, min_ecmp_width, self._params.get("max_multiway_groups")
            )
            (failures if failed else verdicts).append(text)

        # Opt-in: the STEADY STATE, as opposed to every other verdict here,
        # which is a maximum over the whole run.
        expected_converged = self._params.get("expected_converged_multiway_groups")
        if expected_converged is not None and multiway_series is not None:
            failed, text = _converged_verdict(
                multiway_series,
                int(expected_converged),
                int(
                    self._params.get(
                        "converged_window_samples",
                        _DEFAULT_CONVERGED_WINDOW_SAMPLES,
                    )
                ),
                f"groups >= {min_ecmp_width}-wide",
            )
            (failures if failed else verdicts).append(text)

        # Opt-in: a floor on what was observed at all. An ALL-ZERO series is not
        # empty, so it survives the empty-series guard above and then satisfies
        # any "max below threshold" ceiling -- max(0) < 50 passes. That is not
        # hypothetical: on bag012 this metric read 0 for all 884 samples and the
        # suite passed 11 times on a gate that was structurally blind.
        min_observed = self._params.get("min_observed_groups")
        if min_observed is not None:
            failed, text = _observation_verdict(
                max(num_groups_configured_data.values()), min_observed
            )
            (failures if failed else verdicts).append(text)

        # Opt-in: RECOVERY. A bounded transient collapses back to the steady
        # state; a structural regression does not. Asserting recovery separates
        # the two by DURATION rather than magnitude, which means it needs no
        # calibrated ceiling -- deliberately, because the historical ceiling on
        # this task has never had a hardware derivation.
        recovery_tolerance = self._params.get("recovery_tolerance")
        if recovery_tolerance is not None:
            # Prefer the multi-way series when we have it: a collapse from
            # {128: 2} to {1: 2} leaves the RAW count at 2 and would "recover"
            # cleanly while every real ECMP set was destroyed. When
            # min_ecmp_width is set the multi-way series is always the one used:
            # sizes_data carries one entry per NexthopGroupSummary sample, so it
            # is falsy only when there were no summaries at all -- and that case
            # has already returned above. An all-empty histogram therefore
            # yields a populated all-zero series, which _ecmp_set_verdict flags
            # as a parse failure and the zero-baseline guard refuses to score.
            series = (
                multiway_series
                if multiway_series is not None
                else num_groups_configured_data
            )
            metric = (
                f"groups >= {min_ecmp_width}-wide"
                if multiway_series is not None
                else "nexthop-group count"
            )
            failed, text = _recovery_verdict(
                series,
                recovery_tolerance,
                int(
                    self._params.get(
                        "recovery_window_samples",
                        _DEFAULT_RECOVERY_WINDOW_SAMPLES,
                    )
                ),
                metric,
            )
            (failures if failed else verdicts).append(text)

        status = (
            hc_types.HealthCheckStatus.FAIL
            if failures
            else hc_types.HealthCheckStatus.PASS
        )
        # Sample COUNT is not sample COVERAGE, and `min_samples` only bounds the
        # former. `_converged_verdict` reads a positional tail -- the last N
        # samples -- so if collection wedges partway through (every poll raising
        # and being swallowed by `run`), the series simply stops growing and
        # that "closing window" is really a mid-run window. A drain-phase window
        # medians to 0, which reports as `converged BREACH ... settled at 0`:
        # instrument death wearing the costume of a device that destroyed every
        # ECMP set. Exactly the misattribution that made the rel-191 triage
        # wrong.
        #
        # Gating on it needs a threshold nobody has measured: workers are torn
        # down -- including everpaste upload -- BEFORE run_final_check, so even
        # a perfectly healthy run's newest sample is already minutes old here.
        # Reporting the SPAN costs nothing and is what makes that threshold
        # measurable: a span far short of the run's duration is a wedge, and it
        # is now visible in the message instead of having to be inferred from
        # the plot. Gate once there is a number.
        # float() on the keys is NOT defensive padding. In production `_data` is
        # a `_SharedDataView` over a multiprocessing Manager dict: `add_data`
        # casts the timestamp to int, but the view stores it as
        # `f"{prefix}{key}"` and hands it back as `key[prefix_len:]` -- a
        # concatenation and a slice -- so every key is a STR at runtime. Tests
        # construct the task with `shared_data=None`, which takes the plain-dict
        # branch and keeps int keys, so the whole suite exercises a key type
        # production never uses. Every verdict above survives that because it
        # only ever SORTS the keys (lexicographic order matches numeric order
        # for fixed-width epoch seconds); this is the first arithmetic on one.
        timestamps = sorted(float(ts) for ts in num_groups_configured_data)
        span_seconds = int(timestamps[-1] - timestamps[0]) if timestamps else 0
        message = "; ".join(failures + verdicts)
        message += f" [samples={len(num_groups_configured_data)}, span={span_seconds}s]"

        data_series = {
            "num_groups_configured": num_groups_configured_data,
            "num_unprogrammed_groups": num_unprogrammed_groups_data,
        }
        # The multi-way series is the one that shows the characteristic. The raw
        # count cannot distinguish "more ECMP sets" from "ECMP collapsed into
        # width-1 singletons" -- the latter makes it RISE -- so a triager
        # opening the plot to see the steady -> transient -> steady shape was
        # looking at the one series that cannot show it. Computed already; it
        # was simply never plotted.
        if multiway_series is not None:
            data_series[f"groups_>={min_ecmp_width}_wide"] = multiway_series

        # Create annotations with max num_groups_configured value
        plot_annotations = {
            "Max Groups Configured": max_num_groups_configured,
            "Samples Collected": len(self._data),
        }

        plot_path = await _generate_multi_series_plot(
            data_series=data_series,
            title="Nexthop Group Summary Over Time",
            ylabel="Count",
            threshold=threshold,
            annotations=plot_annotations,
        )

        if plot_path:
            try:
                plot_url = format_everpaste_url(
                    await async_everpaste_file(plot_path, extension="png")
                )
                message += f"\nPlot: {plot_url}"
                self.logger.info(f"Plot uploaded to: {plot_url}")
            except Exception as e:
                self.logger.warning(f"Failed to upload plot: {e}")

        return PeriodicCheckResult(
            # pyrefly: ignore [bad-argument-type]
            name=self.NAME,
            status=status,
            message=message,
        )


class ProcessMonitorTask(PeriodicTask):
    NAME = "process_monitor"

    # Default processes to monitor (BGP and Arista Fib related)
    DEFAULT_PROCESS_FILTER = [
        "bgpd_main",
        "AristaFibAgent",
        "EosSdkRpc-FibBg",
        "EosSdkRpc-FibGr",
    ]

    def _filter_processes(
        self,
        all_processes: t.Dict[str, t.Dict[str, t.Any]],
        process_filter: t.List[str],
    ) -> t.Dict[str, t.Dict[str, t.Any]]:
        """
        Filters processes based on process name filter list.

        Args:
            all_processes: Dictionary of all processes (pid -> process_data)
            process_filter: List of process name patterns to match

        Returns:
            Dictionary of filtered processes
        """
        filtered_processes = {}
        found_process_names = set()

        for pid, process_data in all_processes.items():
            cmd = process_data.get("cmd", "")
            if any(filter_name in cmd for filter_name in process_filter):
                filtered_processes[pid] = process_data
                found_process_names.add(cmd)

        # Log info about missing processes (e.g., during restart)
        for expected_name in process_filter:
            if not any(
                expected_name in found_name for found_name in found_process_names
            ):
                self.logger.info(
                    f"Process {expected_name} not found (possibly restarted or not running)"
                )

        return filtered_processes

    def _log_filtered_processes(
        self,
        filtered_processes: t.Dict[str, t.Dict[str, t.Any]],
        total_count: int,
        process_filter: t.List[str],
    ) -> None:
        """
        Logs details of filtered processes or warning if none found.

        Args:
            filtered_processes: Dictionary of filtered processes
            total_count: Total number of processes before filtering
            process_filter: List of process name patterns used for filtering
        """
        if not filtered_processes:
            self.logger.warning(
                f"No processes matching filter {process_filter} found out of {total_count} total processes"
            )
            return

        process_details = []
        for pid, proc in filtered_processes.items():
            cmd = proc.get("cmd", "unknown")
            cpu_pct = proc.get("cpuPct", 0)
            resident_mem = proc.get("residentMem", "0")
            process_details.append(
                f"{cmd} (PID: {pid}, CPU: {cpu_pct}%, ResidentMem: {resident_mem}KB)"
            )

        self.logger.info(
            f"Monitoring {len(filtered_processes)} processes out of {total_count} total:\n  "
            + "\n  ".join(process_details)
        )

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        """
        Collects process data from 'show processes top once | json' and stores it for final check.

        Args:
            params:
                - hostname: Device hostname (required)
                - process_filter: Optional list of process names to monitor (default: BGP and Arista Fib processes)
        """
        try:
            hostname = params["hostname"]
            self.logger.info(f"Attempting to get process data from {hostname}")
            driver = await async_get_device_driver(hostname)
            output = await driver.async_get_processes_top()
            self.logger.info(
                f"Successfully got process data with {len(output.get('processes', {}))} processes"
            )

            process_filter = params.get("process_filter", self.DEFAULT_PROCESS_FILTER)
            if process_filter:
                all_processes = output.get("processes", {})
                filtered_processes = self._filter_processes(
                    all_processes, process_filter
                )
                output["processes"] = filtered_processes
                self._log_filtered_processes(
                    filtered_processes, len(all_processes), process_filter
                )

            self.add_data(output)
        except Exception as e:
            self.logger.error(f"Error collecting process data: {e}", exc_info=True)
            # Store empty data to avoid breaking final check
            self.add_data({"processes": {}, "error": str(e)})

    def _find_peak_values(
        self,
    ) -> t.Tuple[float, str, float, str]:
        """
        Finds peak CPU and resident memory values across all collected data.

        Returns:
            Tuple of (max_cpu_value, max_cpu_process, max_resident_mem_value, max_resident_mem_process)
        """
        max_cpu_process = "unknown"
        max_cpu_value = 0.0
        max_resident_mem_process = "unknown"
        max_resident_mem_value = 0

        for _timestamp, data in self._data.items():
            processes = data.get("processes", {})
            for pid, process_data in processes.items():
                cpu_pct = float(process_data.get("cpuPct", 0))
                resident_mem_str = str(process_data.get("residentMem", "0"))
                resident_mem_kb = _parse_memory_value(resident_mem_str)
                resident_mem_mb = resident_mem_kb / 1024.0
                cmd = process_data.get("cmd", "unknown")

                if cpu_pct > max_cpu_value:
                    max_cpu_value = cpu_pct
                    max_cpu_process = f"{cmd} (PID: {pid})"

                if resident_mem_mb > max_resident_mem_value:
                    max_resident_mem_value = resident_mem_mb
                    max_resident_mem_process = f"{cmd} (PID: {pid})"

        return (
            max_cpu_value,
            max_cpu_process,
            max_resident_mem_value,
            max_resident_mem_process,
        )

    def _aggregate_process_data(
        self,
    ) -> t.Tuple[t.Dict[str, t.Dict[float, float]], t.Dict[str, t.Dict[float, float]]]:
        """
        Aggregates process data by (cmd, pid) for plotting.
        Each process instance gets its own plot line, identified by cmd_pid.

        Returns:
            Tuple of (process_cpu_data, process_mem_data_mb)
        """
        process_cpu_data: t.Dict[str, t.Dict[float, float]] = {}
        process_mem_data: t.Dict[str, t.Dict[float, float]] = {}

        for timestamp, data in self._data.items():
            processes = data.get("processes", {})
            for pid, process_data in processes.items():
                cmd = process_data.get("cmd", "unknown")
                cpu_pct = float(process_data.get("cpuPct", 0))
                resident_mem_str = str(process_data.get("residentMem", "0"))
                resident_mem_kb = _parse_memory_value(resident_mem_str)
                resident_mem_mb = resident_mem_kb / 1024.0

                # Use cmd_pid as key to distinguish multiple instances
                process_key = f"{cmd}_{pid}"

                if process_key not in process_cpu_data:
                    process_cpu_data[process_key] = {}
                    process_mem_data[process_key] = {}

                process_cpu_data[process_key][timestamp] = cpu_pct
                process_mem_data[process_key][timestamp] = resident_mem_mb

        return process_cpu_data, process_mem_data

    async def _generate_and_upload_plots(
        self,
        process_cpu_data: t.Dict[str, t.Dict[float, float]],
        process_mem_data: t.Dict[str, t.Dict[float, float]],
    ) -> str:
        """
        Generates and uploads CPU and memory plots for each process.

        Args:
            process_cpu_data: CPU data per process
            process_mem_data: Memory data per process

        Returns:
            String containing plot URLs to append to message
        """
        plot_urls = ""
        # Generate CPU plot for each process
        for process_name, cpu_data in process_cpu_data.items():
            process_label = _process_lifetime_label(process_name)
            cpu_plot_path = await _generate_plot(
                data=cpu_data,
                title=f"CPU Usage — {process_label}",
                ylabel="CPU %",
                y_axis_starts_at_zero=True,
            )
            if cpu_plot_path:
                try:
                    cpu_plot_url = format_everpaste_url(
                        await async_everpaste_file(cpu_plot_path, extension="png")
                    )
                    plot_urls += f"\n\nCPU Plot [{process_label}]: {cpu_plot_url}"
                    self.logger.info(f"CPU plot [{process_label}]: {cpu_plot_url}")
                except Exception as e:
                    self.logger.warning(
                        f"Failed to upload CPU plot for {process_name}: {e}"
                    )

        # Generate resident memory plot for each process
        for process_name, mem_data in process_mem_data.items():
            process_label = _process_lifetime_label(process_name)
            mem_plot_path = await _generate_plot(
                data=mem_data,
                title=f"Resident Memory — {process_label}",
                ylabel="Resident Memory (MB)",
                y_axis_starts_at_zero=True,
            )
            if mem_plot_path:
                try:
                    mem_plot_url = format_everpaste_url(
                        await async_everpaste_file(mem_plot_path, extension="png")
                    )
                    plot_urls += f"\nMemory Plot [{process_label}]: {mem_plot_url}"
                    self.logger.info(
                        f"Resident memory plot [{process_label}]: {mem_plot_url}"
                    )
                except Exception as e:
                    self.logger.warning(
                        f"Failed to upload resident memory plot for {process_name}: {e}"
                    )

        return plot_urls

    async def run_final_check(self) -> t.Optional[PeriodicCheckResult]:
        """
        Analyzes collected process data and generates plots for cpuPct and residentMem over time.

        Returns:
            PeriodicCheckResult with analysis results and plot URLs
        """
        self.logger.info(
            f"ProcessMonitor run_final_check: self._data has {len(self._data)} entries"
        )
        self.logger.info(
            f"ProcessMonitor run_final_check: self._data keys = {list(self._data.keys()) if self._data else []}"
        )
        if not self._data:
            return PeriodicCheckResult(
                # pyrefly: ignore [bad-argument-type]
                name=self.NAME,
                status=hc_types.HealthCheckStatus.SKIP,
                message="No data collected during periodic task execution",
            )

        enable_plotting = self._params.get("enable_plotting", True)

        (
            max_cpu_value,
            max_cpu_process,
            max_resident_mem_value,
            max_resident_mem_process,
        ) = self._find_peak_values()

        message = f"Peak CPU: {max_cpu_value}% by {max_cpu_process}\n"
        message += f"Peak ResidentMem: {max_resident_mem_value:.2f}MB by {max_resident_mem_process}"

        if enable_plotting:
            process_cpu_data, process_mem_data = self._aggregate_process_data()
            plot_urls = await self._generate_and_upload_plots(
                process_cpu_data, process_mem_data
            )
            message += plot_urls

        return PeriodicCheckResult(
            # pyrefly: ignore [bad-argument-type]
            name=self.NAME,
            status=hc_types.HealthCheckStatus.PASS,
            message=message,
        )


class CpuLoadAverageTask(PeriodicTask):
    NAME = "cpu_load_average"

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        """
        Collects CPU load average data and stores it for final check.

        Args:
            params:
                - hostname: Device hostname (required)
                - threshold: Threshold for CPU load average (required)
        """
        hostname = params["hostname"]
        threshold = params["threshold"]
        try:
            self.logger.info(f"Attempting to get CPU load average from {hostname}")
            driver = await async_get_device_driver(hostname)
            # pyre-fixme[16]: `AbstractSwitch` has no attribute
            #  `async_get_system_cpu_load_average`.
            output = await driver.async_get_system_cpu_load_average()
            self.logger.info(f"Successfully got CPU load average: {output}")

            max_load = max(output)
            self.add_data(max_load)

            if any(load_avg > threshold for load_avg in output):
                self.logger.warning(
                    f"CPU load average exceeds threshold {threshold}: 1 min: {output[0]}, 5 min: {output[1]}, 15 min: {output[2]} (will check max at end)"
                )
        except Exception as e:
            self.logger.error(
                f"Error collecting CPU load average data: {e}", exc_info=True
            )

    async def run_final_check(self) -> t.Optional[PeriodicCheckResult]:
        """
        Checks if the maximum collected CPU load average is above threshold.
        Optionally generates a time-series plot if enable_plotting param is True.

        Returns:
            PeriodicCheckResult with PASS if max is below/equal to threshold, FAIL otherwise
        """
        self.logger.info(
            f"CpuLoadAverage run_final_check: self._data has {len(self._data)} entries"
        )
        self.logger.info(
            f"CpuLoadAverage run_final_check: self._data = {dict(self._data) if self._data else {}}"
        )
        if not self._data:
            return PeriodicCheckResult(
                # pyrefly: ignore [bad-argument-type]
                name=self.NAME,
                status=hc_types.HealthCheckStatus.SKIP,
                message="No data collected during periodic task execution",
            )

        max_cpu_load = max(self._data.values())
        threshold = self._params.get("threshold")

        if threshold is None:
            return PeriodicCheckResult(
                # pyrefly: ignore [bad-argument-type]
                name=self.NAME,
                status=hc_types.HealthCheckStatus.ERROR,
                message="Threshold parameter not available for final check",
            )

        # Determine status and base message
        if max_cpu_load > threshold:
            status = hc_types.HealthCheckStatus.FAIL
            message = (
                f"Peak CPU load average {max_cpu_load} exceeded threshold {threshold}"
            )
        else:
            status = hc_types.HealthCheckStatus.PASS
            message = (
                f"Peak CPU load average {max_cpu_load} is within threshold {threshold}"
            )

        # Generate plot if enabled (from params)
        enable_plotting = self._params.get("enable_plotting", False)
        if enable_plotting:
            plot_path = await _generate_plot(
                data=dict(self._data),
                title="CPU Load Average Over Time",
                ylabel="CPU Load Average",
                threshold=threshold,
                y_axis_starts_at_zero=True,
            )
            if plot_path:
                # Upload to everpaste
                try:
                    plot_url = format_everpaste_url(
                        await async_everpaste_file(plot_path, extension="png")
                    )
                    message += f"\nPlot: {plot_url}"
                    self.logger.info(f"Plot uploaded to: {plot_url}")
                except Exception as e:
                    self.logger.warning(f"Failed to upload plot: {e}")

        return PeriodicCheckResult(
            # pyrefly: ignore [bad-argument-type]
            name=self.NAME,
            status=status,
            message=message,
        )


class OpticsTemperatureTask(PeriodicTask):
    NAME = "optics_temperature"

    def _get_ngt_thresholds(
        self,
    ) -> t.Dict[t.Any, t.Tuple[float, float]]:
        """
        Fetch per-MediaInterfaceCode temperature thresholds from NGT configerator.

        Returns:
            Dict mapping MediaInterfaceCode to (min_celsius, max_celsius) tuples.
            Empty dict if configerator is unavailable.
        """
        if not _CONFIGERATOR_AVAILABLE:
            self.logger.warning(
                "Configerator not available, using default temperature thresholds"
            )
            return {}

        try:
            link_params = ConfigeratorClient().get_config_contents_as_thrift(
                _LINK_PARAMS_CFGR_PATH, LinkParametersMap
            )
            thresholds = {}
            for media_code, connection_map in link_params.thresholds.items():
                for _connection, tcvr_thresh in connection_map.items():
                    # Use the most permissive threshold across connection types
                    min_c = tcvr_thresh.temperature_min_celsius
                    max_c = tcvr_thresh.temperature_max_celsius
                    if media_code in thresholds:
                        existing_min, existing_max = thresholds[media_code]
                        min_c = min(min_c, existing_min)
                        max_c = max(max_c, existing_max)
                    thresholds[media_code] = (min_c, max_c)
            self.logger.info(
                f"Loaded NGT temperature thresholds for {len(thresholds)} media types"
            )
            return thresholds
        except Exception as e:
            self.logger.warning(
                f"Failed to load NGT thresholds from configerator: {e}, "
                f"using default thresholds"
            )
            return {}

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        """
        Collects optics temperature data from all transceivers and stores for final check.

        Args:
            params:
                - hostname: Device hostname (required)
                - threshold: Optional explicit temperature threshold in Celsius.
                    If not provided, uses per-media-type NGT thresholds.
        """
        hostname = params["hostname"]
        explicit_threshold = params.get("threshold")

        try:
            self.logger.info(
                f"Attempting to get optics temperature data from {hostname}"
            )
            driver = await async_get_device_driver(hostname)
            # pyre-fixme[16]: `AbstractSwitch` has no attribute `_get_qsfp_info_map`.
            qsfp_info_map = await driver._get_qsfp_info_map()
            self.logger.info(
                f"Successfully got transceiver info for "
                f"{len(qsfp_info_map)} transceivers"
            )

            # Fetch NGT thresholds if no explicit threshold
            ngt_thresholds = {}
            if explicit_threshold is None:
                ngt_thresholds = self._get_ngt_thresholds()

            # Collect per-transceiver temperature and media type data
            per_tcvr_data = {}
            violations = []

            for transceiver_id, tcvr_info in qsfp_info_map.items():
                if not tcvr_info.tcvrState or not tcvr_info.tcvrState.present:
                    continue

                if not tcvr_info.tcvrStats or not tcvr_info.tcvrStats.sensor:
                    continue

                temp_sensor = tcvr_info.tcvrStats.sensor.temp
                if temp_sensor is None:
                    continue

                temp_value = temp_sensor.value
                media_code = tcvr_info.tcvrState.moduleMediaInterface
                media_type_name = (
                    media_code.name if media_code is not None else "UNKNOWN"
                )

                per_tcvr_data[transceiver_id] = {
                    "temp": temp_value,
                    "media_type": media_type_name,
                }

                # Determine threshold for this transceiver
                if explicit_threshold is not None:
                    max_thresh = explicit_threshold
                else:
                    _, max_thresh = ngt_thresholds.get(
                        media_code, _DEFAULT_TEMPERATURE_THRESHOLD
                    )

                if temp_value > max_thresh:
                    violations.append(
                        f"Transceiver {transceiver_id} ({media_type_name}): "
                        f"{temp_value}°C exceeds threshold {max_thresh}°C"
                    )
                    self.logger.warning(
                        f"Transceiver {transceiver_id} ({media_type_name}) "
                        f"temperature {temp_value}°C exceeds threshold "
                        f"{max_thresh}°C (will check max at end)"
                    )

            if per_tcvr_data:
                self.add_data(per_tcvr_data)
                max_temp = max(d["temp"] for d in per_tcvr_data.values())
                self.logger.info(
                    f"Max optics temperature across "
                    f"{len(per_tcvr_data)} transceivers: {max_temp}°C"
                )
            else:
                self.logger.warning(
                    "No valid temperature readings from any transceiver"
                )

            if violations:
                self.logger.warning(
                    f"{len(violations)} transceiver(s) exceeded temperature threshold"
                )

        except Exception as e:
            self.logger.error(
                f"Error collecting optics temperature data: {e}", exc_info=True
            )

    def _build_per_type_summary(
        self,
    ) -> t.Tuple[
        t.Dict[str, t.Dict[t.Any, t.Any]],
        t.Dict[str, t.Dict[str, t.Any]],
        t.Optional[float],
    ]:
        """
        Build per-transceiver time-series and per-type stats from collected data.

        Returns:
            Tuple of (per_tcvr_series, type_stats, overall_max_temp)
        """
        per_tcvr_series: t.Dict[str, t.Dict[t.Any, t.Any]] = {}
        type_stats: t.Dict[str, t.Dict[str, t.Any]] = {}
        overall_max_temp = None

        for timestamp, tcvr_data_map in self._data.items():
            if not isinstance(tcvr_data_map, dict):
                continue
            for tcvr_id, tcvr_data in tcvr_data_map.items():
                if not isinstance(tcvr_data, dict):
                    continue
                temp_value = tcvr_data["temp"]
                media_type = tcvr_data.get("media_type", "UNKNOWN")

                series_key = f"Transceiver {tcvr_id}"
                if series_key not in per_tcvr_series:
                    per_tcvr_series[series_key] = {}
                per_tcvr_series[series_key][timestamp] = temp_value

                if overall_max_temp is None or temp_value > overall_max_temp:
                    overall_max_temp = temp_value

                if media_type not in type_stats:
                    type_stats[media_type] = {
                        "max_temp": temp_value,
                        "tcvr_ids": set(),
                    }
                elif temp_value > type_stats[media_type]["max_temp"]:
                    type_stats[media_type]["max_temp"] = temp_value
                type_stats[media_type]["tcvr_ids"].add(tcvr_id)

        return per_tcvr_series, type_stats, overall_max_temp

    async def run_final_check(self) -> t.Optional[PeriodicCheckResult]:
        """
        Checks if any optics temperature exceeded the threshold.
        Groups results by optics type and generates a per-optics time-series plot.

        Returns:
            PeriodicCheckResult with PASS if within threshold, FAIL otherwise
        """
        self.logger.info(
            f"OpticsTemperature run_final_check: self._data has "
            f"{len(self._data)} entries"
        )
        if not self._data:
            return PeriodicCheckResult(
                # pyrefly: ignore [bad-argument-type]
                name=self.NAME,
                status=hc_types.HealthCheckStatus.SKIP,
                message="No data collected during periodic task execution",
            )

        explicit_threshold = self._params.get("threshold")
        if explicit_threshold is not None:
            threshold = explicit_threshold
        else:
            threshold = _DEFAULT_TEMPERATURE_THRESHOLD[1]

        per_tcvr_series, type_stats, overall_max_temp = self._build_per_type_summary()

        if overall_max_temp is None:
            return PeriodicCheckResult(
                # pyrefly: ignore [bad-argument-type]
                name=self.NAME,
                status=hc_types.HealthCheckStatus.SKIP,
                message="No valid temperature data collected",
            )

        if overall_max_temp > threshold:
            status = hc_types.HealthCheckStatus.FAIL
            message = (
                f"Max optics temperature {overall_max_temp}°C "
                f"exceeded threshold {threshold}°C"
            )
        else:
            status = hc_types.HealthCheckStatus.PASS
            message = (
                f"Max optics temperature {overall_max_temp}°C "
                f"is within threshold {threshold}°C"
            )

        # Append per-type summary grouped by optics type
        message += "\n\nBy optics type:"
        for media_type in sorted(type_stats.keys()):
            stats = type_stats[media_type]
            count = len(stats["tcvr_ids"])
            max_t = stats["max_temp"]
            message += f"\n  {media_type}: {count} optics, max {max_t}°C"

        # Generate per-optics plot
        plot_path = await _generate_multi_series_plot(
            data_series=per_tcvr_series,
            title="Optics Temperature Over Time",
            ylabel="Temperature (°C)",
            threshold=threshold,
            annotations={
                "Max Temperature": f"{overall_max_temp}°C",
                "Transceivers Monitored": len(per_tcvr_series),
            },
        )
        if plot_path:
            try:
                plot_url = format_everpaste_url(
                    await async_everpaste_file(plot_path, extension="png")
                )
                message += f"\nPlot: {plot_url}"
                self.logger.info(f"Plot uploaded to: {plot_url}")
            except Exception as e:
                self.logger.warning(f"Failed to upload plot: {e}")

        return PeriodicCheckResult(
            # pyrefly: ignore [bad-argument-type]
            name=self.NAME,
            status=status,
            message=message,
        )


class ThriftStressPeriodicTask(PeriodicTask):
    """Sustained high-volume thrift workload against a FBOSS DUT.

    Each invocation fires every `ThriftStressCall` in the payload concurrently
    (with `requests_per_burst` copies per call) via a single
    `asyncio.gather(...)`. The wrapping `PeriodicTaskWorker` loops `run()`
    back-to-back with `time.sleep(interval)` between bursts, which together
    reproduces the `while True: gather(...); sleep(5)` shape of
    `scripts/pavanpatil/thrift_call_disruptive.py:async_thrift_stress_call`.

    Payload selection happens at testconfig-build time via builders in
    `tasks/thrift_stress_payloads.py` — read-only baselines for any FBOSS
    device, plus per-platform variants that splice in disruptive calls like
    qsfp-driven rapid interface flaps. Read-only-only is the default; the
    disruptive variants are opt-in because they interfere with the
    IxiaPacketLossCheck postcheck on test ports.

    Backwards-compat: callers may pass `apis: List[str]` instead of `calls`,
    in which case each api name is wrapped in a default `ThriftStressCall`
    with the legacy `requests_per_api` request count (default 10000).

    `run_final_check()` always returns PASS — thrift exceptions are expected
    during the process-restart THFT variants (THFT_001-004) and the per-burst
    success/exception counts are logged for forensic review, not used to gate
    the test verdict.
    """

    NAME = "thrift_stress"
    DEFAULT_REQUESTS_PER_API: int = 10000
    # Burst timeout — if `asyncio.gather(...)` hasn't returned by this many
    # seconds, we cancel all pending coroutines, log a loud warning, record a
    # timed-out burst with the count, and return so the worker loop continues
    # to the next interval. Without this, an unresponsive agent (e.g. when
    # the storm we're firing pegs `fboss_sw_agent` CPU at 100%) causes
    # gather() to hang indefinitely — we'd never get a burst result, never
    # write to shared_data, and the test would terminate the worker with
    # `_data entries=0` and no diagnostic. 60s default is generous for
    # ~70K well-behaved concurrent calls (~5-30s normal) but tight enough
    # to surface trouble within one burst window.
    DEFAULT_BURST_TIMEOUT_S: float = 60.0

    @staticmethod
    def _resolve_calls(params: t.Dict[str, t.Any]) -> t.List[ThriftStressCall]:
        """Pull `calls` (preferred) or build from legacy `apis` shape.

        Use `is not None` (not truthiness) so an explicitly-empty `calls=[]`
        means "run zero calls", NOT "fall through to default baseline".
        """
        calls_raw = params.get("calls")
        if calls_raw is not None:
            return [ThriftStressCall.from_dict(d) for d in calls_raw]
        apis: t.Optional[t.List[str]] = params.get("apis")
        requests_per_api: int = params.get(
            "requests_per_api", ThriftStressPeriodicTask.DEFAULT_REQUESTS_PER_API
        )
        if apis is None:
            return [
                ThriftStressCall(
                    method=call.method,
                    args=call.args,
                    requests_per_burst=requests_per_api,
                )
                for call in READ_ONLY_FBOSS_APIS
            ]
        return [
            ThriftStressCall(method=api, requests_per_burst=requests_per_api)
            for api in apis
        ]

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        """Fire one burst of concurrent thrift calls.

        Args:
            params:
                - hostname: Device hostname (required).
                - calls: Preferred. List of `ThriftStressCall.to_dict()` entries
                    describing exactly what to call, with what args, how many
                    times concurrently per burst. Built by the catalog functions
                    in `tasks/thrift_stress_payloads.py`.
                - apis: Legacy. List of no-arg driver method names. Each is
                    wrapped in a default `ThriftStressCall`.
                - requests_per_api: Legacy. Only consulted when `apis` is set.
                    Default 10000.
        """
        hostname = params["hostname"]
        calls = self._resolve_calls(params)

        try:
            driver = await async_get_device_driver(hostname)
        except Exception as e:
            self.logger.error(
                f"thrift_stress: failed to get driver for {hostname}: {e}",
                exc_info=True,
            )
            return

        coros: t.List[t.Coroutine] = []
        skipped: t.List[str] = []
        scheduled_breakdown: t.List[str] = []
        for call in calls:
            method = getattr(driver, call.method, None)
            if not inspect.iscoroutinefunction(method):
                skipped.append(call.method)
                continue
            for _ in range(call.requests_per_burst):
                coros.append(method(*call.args))
            scheduled_breakdown.append(f"{call.method}x{call.requests_per_burst}")

        if skipped:
            self.logger.warning(
                f"thrift_stress: methods not async-callable on "
                f"{type(driver).__name__}: {skipped}"
            )

        if not coros:
            self.logger.warning(
                "thrift_stress: no thrift calls scheduled (all methods missing)"
            )
            return

        burst_timeout_s: float = float(
            params.get("burst_timeout_s", self.DEFAULT_BURST_TIMEOUT_S)
        )
        self.logger.info(
            f"thrift_stress: firing {len(coros)} concurrent calls "
            f"(timeout={burst_timeout_s:.0f}s) ({', '.join(scheduled_breakdown)})"
        )
        burst_start = time.time()
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*coros, return_exceptions=True),
                timeout=burst_timeout_s,
            )
        except asyncio.TimeoutError:
            elapsed = time.time() - burst_start
            # `asyncio.wait_for` cancels the pending gather on timeout,
            # which cancels each child coroutine. We can't recover partial
            # results, so we record a fully timed-out burst and continue.
            # The worker loop's outer `time.sleep(interval)` then fires,
            # then we try the next burst — if the agent has recovered we
            # see normal completion; if it's still unresponsive we keep
            # timing out, but at least we get a diagnostic per burst
            # instead of an indefinite hang that produces no data.
            self.logger.warning(
                f"thrift_stress: burst TIMED OUT after {elapsed:.1f}s "
                f"(limit {burst_timeout_s}s) — device likely unresponsive; "
                f"{len(coros)} coros cancelled, no per-call results"
            )
            self.add_data(
                {
                    "total": len(coros),
                    "success": 0,
                    "failures": 0,
                    "timed_out": len(coros),
                    "elapsed_s": elapsed,
                }
            )
            return
        elapsed = time.time() - burst_start

        success = sum(1 for r in results if not isinstance(r, BaseException))
        failures = len(results) - success
        self.add_data(
            {
                "total": len(results),
                "success": success,
                "failures": failures,
                "timed_out": 0,
                "elapsed_s": elapsed,
            }
        )
        self.logger.info(
            f"thrift_stress burst: {success}/{len(results)} ok, "
            f"{failures} exceptions, elapsed={elapsed:.1f}s"
        )

    async def run_final_check(self) -> t.Optional[PeriodicCheckResult]:
        """Summarize total/success/exception counts across all bursts.

        Returns PASS unconditionally: thrift exceptions during the
        process-restart THFT variants are expected (the restarting service
        drops in-flight calls). The forensic counts go in the result message.
        """
        if not self._data:
            return PeriodicCheckResult(
                # pyrefly: ignore [bad-argument-type]
                name=self.NAME,
                status=hc_types.HealthCheckStatus.SKIP,
                message="No thrift stress data collected",
            )

        batches = len(self._data)
        total = sum(d.get("total", 0) for d in self._data.values())
        success = sum(d.get("success", 0) for d in self._data.values())
        failures = sum(d.get("failures", 0) for d in self._data.values())
        timed_out = sum(d.get("timed_out", 0) for d in self._data.values())
        timed_out_bursts = sum(
            1 for d in self._data.values() if d.get("timed_out", 0) > 0
        )
        elapsed_total = sum(d.get("elapsed_s", 0.0) for d in self._data.values())
        avg_elapsed = elapsed_total / batches if batches else 0.0
        success_pct = (100.0 * success / total) if total else 0.0

        message = (
            f"thrift_stress: {batches} bursts "
            f"({timed_out_bursts} timed out), {total} total calls, "
            f"{success} ok ({success_pct:.1f}%), "
            f"{failures} exceptions, {timed_out} timed-out calls, "
            f"avg burst {avg_elapsed:.1f}s"
        )

        return PeriodicCheckResult(
            # pyrefly: ignore [bad-argument-type]
            name=self.NAME,
            status=hc_types.HealthCheckStatus.PASS,
            message=message,
        )
