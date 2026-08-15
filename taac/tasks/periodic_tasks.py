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
from taac.utils.common import async_everpaste_file
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
) -> t.Optional[str]:
    """
    Generate a time-series plot from collected data.

    Args:
        data: Dictionary mapping timestamps to values
        title: Plot title
        ylabel: Y-axis label
        threshold: Optional threshold line to draw
        output_path: Optional path to save plot (default: temp file)

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
                status=hc_types.HealthCheckStatus.SKIP,
                message="No data collected during periodic task execution",
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

        # Generate plot if enabled via params
        enable_plotting = self._params.get("enable_plotting", False)
        if enable_plotting:
            plot_path = await _generate_plot(
                data=dict(self._data),
                title=f"Counter Utilization Over Time: {key}",
                ylabel=key,
                threshold=threshold,
            )
            if plot_path:
                # Upload to everpaste
                try:
                    plot_url = await async_everpaste_file(plot_path)
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


def _unprogrammed_verdict(
    series: t.Dict[float, int], maximum: int
) -> t.Tuple[bool, str]:
    """Verdict on the device's own "I could not program this group" counter.

    Returns ``(failed, message)``.

    A module-level function rather than an inline block for one reason: the
    empty-series case is not reachable through ``run_final_check``. That series
    is filled in the same ``isinstance`` arm of the same loop as the count
    series, and an empty count series already returns before any verdict runs,
    so no input to the poll can produce it. Left inline it would be a branch no
    test could execute and no reader could check. Here it is callable with
    ``{}`` directly.

    That case is a FAILURE, not a skip. Guarding the caller on the series being
    truthy is the natural way to write this and is wrong: it reads as a safety
    belt but encodes "silently drop a gate the caller asked for" -- the vacuous
    pass this whole check exists to close -- and it is indistinguishable at
    runtime from the correct form precisely BECAUSE the case is unreachable. It
    stops being unreachable the moment the collection loop stops filling the two
    series together, and only one of the two forms survives that.
    """
    if not series:
        return True, (
            "unprogrammed NOT EVALUATED: max_unprogrammed was set but no "
            "num_unprogrammed_groups samples were recorded, so the device's "
            "own hardware-rejection signal was never read"
        )
    observed = max(series.values())
    if observed <= maximum:
        return False, (
            f"unprogrammed OK: max num_unprogrammed_groups ({observed}) is "
            f"within the allowed maximum ({maximum})"
        )
    return True, (
        f"unprogrammed BREACH: max num_unprogrammed_groups ({observed}) "
        f"exceeds the allowed maximum ({maximum}) -- the device could not "
        f"program at least one nexthop group"
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
    window = params.get("recovery_window_samples")
    if window is not None and int(window) <= 0:
        problems.append(
            f"recovery_window_samples must be positive, got {window}",
        )
    # The recovery band is baseline/tolerance .. baseline*tolerance, so the
    # parameter is only meaningful at >= 1. Zero divides; anything in (0, 1)
    # INVERTS the band (low > high), which no value can satisfy, so the gate
    # would fail every run for a reason the message would not explain; and a
    # non-finite tolerance widens the band to admit everything.
    tolerance = params.get("recovery_tolerance")
    if tolerance is not None and (
        not math.isfinite(float(tolerance)) or float(tolerance) < 1
    ):
        problems.append(
            f"recovery_tolerance must be a finite value >= 1, got {tolerance}: "
            f"0 raises, 0 < tolerance < 1 inverts the recovery band so no "
            f"value can satisfy it, and an infinite tolerance admits anything"
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
        return False, f"ecmp-sets OK: {detail} (allowed {max_multiway_groups})"
    return (
        True,
        f"ecmp-sets BREACH: {detail} exceeds the allowed maximum "
        f"({max_multiway_groups})",
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

        Two independent verdicts, reported separately so triage can tell them
        apart:

        1. ``max(num_groups_configured) < threshold`` -- the transient ECMP-set
           ceiling.
        2. ``max(num_unprogrammed_groups) <= max_unprogrammed`` -- the device's
           own "I could not program this group" signal, i.e. the closest thing
           the box reports to "the hardware table is full". Opt-in via the
           ``max_unprogrammed`` param so existing callers are unaffected.

        Collecting no data is a FAILURE, not a SKIP. ``run`` swallows every
        collection exception, so an empty series means every single poll failed
        -- reporting SKIP there let the check pass having proven nothing.

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
            failed, text = _unprogrammed_verdict(
                num_unprogrammed_groups_data, int(max_unprogrammed)
            )
            (failures if failed else verdicts).append(text)

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
                int(self._params.get("recovery_window_samples", 10)),
                metric,
            )
            (failures if failed else verdicts).append(text)

        status = (
            hc_types.HealthCheckStatus.FAIL
            if failures
            else hc_types.HealthCheckStatus.PASS
        )
        message = "; ".join(failures + verdicts)
        message += f" [samples={len(num_groups_configured_data)}]"

        data_series = {
            "num_groups_configured": num_groups_configured_data,
            "num_unprogrammed_groups": num_unprogrammed_groups_data,
        }

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
                plot_url = await async_everpaste_file(plot_path)
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
            cpu_plot_path = await _generate_plot(
                data=cpu_data,
                title=f"CPU Usage Over Time: {process_name}",
                ylabel="CPU %",
            )
            if cpu_plot_path:
                try:
                    cpu_plot_url = await async_everpaste_file(cpu_plot_path)
                    plot_urls += f"\n\nCPU Plot [{process_name}]: {cpu_plot_url}"
                    self.logger.info(
                        f"CPU plot for {process_name} uploaded to: {cpu_plot_url}"
                    )
                except Exception as e:
                    self.logger.warning(
                        f"Failed to upload CPU plot for {process_name}: {e}"
                    )

        # Generate resident memory plot for each process
        for process_name, mem_data in process_mem_data.items():
            mem_plot_path = await _generate_plot(
                data=mem_data,
                title=f"Resident Memory Usage Over Time: {process_name}",
                ylabel="Resident Memory (MB)",
            )
            if mem_plot_path:
                try:
                    mem_plot_url = await async_everpaste_file(mem_plot_path)
                    plot_urls += f"\nMemory Plot [{process_name}]: {mem_plot_url}"
                    self.logger.info(
                        f"Resident memory plot for {process_name} uploaded to: {mem_plot_url}"
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
            )
            if plot_path:
                # Upload to everpaste
                try:
                    plot_url = await async_everpaste_file(plot_path)
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
                plot_url = await async_everpaste_file(plot_path)
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
