# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import math
import typing as t

from taac.health_checks.abstract_health_check import (
    AbstractIxiaHealthCheck,
)
from taac.ixia.taac_ixia import (  # oss-rewrite (force ShipIt re-export to taac.* root)
    TaacIxia as Ixia,
)
from taac.utils.common import async_everpaste_str
from taac.health_check.health_check import types as hc_types
from tabulate import tabulate

# Reference bandwidth a PERCENT threshold is scaled against when
# ``check_params["base_bandwidth_gbps"]`` is absent. 400G for back-compat with
# configs written against 400G ports.
DEFAULT_BASE_BANDWIDTH_GBPS: float = 400.0
_RATE_KEYS = {"tx_rate": "Tx Rate", "rx_rate": "Rx Rate"}


class IxiaTrafficRateHealthCheck(
    AbstractIxiaHealthCheck[hc_types.IxiaTrafficRateHealthCheckIn]
):
    CHECK_NAME = hc_types.CheckName.IXIA_TRAFFIC_RATE_CHECK

    async def _run(
        self,
        obj: Ixia,
        input: hc_types.IxiaTrafficRateHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        if not obj.has_traffic_items():
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.SKIP,
                message="No traffic items found in the ixia setup.",
            )
        latest_stats = obj.get_latest_stats_traffic()
        rate_violations = []
        all_thresholds = list(input.thresholds)

        # Callers may override the PERCENT-mode reference bandwidth via
        # ``check_params["base_bandwidth_gbps"]`` (e.g. pass 200 for a 200G
        # port). Omitting the param preserves the historical 400G default.
        base_bandwidth_gbps = float(
            check_params.get("base_bandwidth_gbps", DEFAULT_BASE_BANDWIDTH_GBPS)
        )
        try:
            rate_tolerance_percent = self._validate_rate_tolerance_percent(
                check_params.get("rate_tolerance_percent")
            )
            rate_metrics = self._validate_rate_metrics(check_params.get("rate_metrics"))
        except ValueError as error:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.ERROR,
                message=str(error),
            )

        for threshold in all_thresholds:
            rate_violations.extend(
                self.verify_traffic_rate_threshold(
                    latest_stats,
                    threshold,
                    base_bandwidth_gbps,
                    rate_tolerance_percent,
                    rate_metrics,
                )
            )

        if rate_violations:
            # Use the Everpaste URL directly; it is already a clickable internalfb.com
            # link, so the throttled fburl tier (createFBUrl) is unnecessary here.
            everpaste_url = await async_everpaste_str(
                tabulate(rate_violations, headers="keys", tablefmt="simple_grid")
            )
            inline_summary = [
                f"{t['identifier']}: Tx={t['Tx Rate (Gbps)']}Gbps, Rx={t['Rx Rate (Gbps)']}Gbps"
                for t in rate_violations[:5]
            ]
            suffix = (
                f" (+{len(rate_violations) - 5} more)"
                if len(rate_violations) > 5
                else ""
            )
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=f"Traffic rate outside the defined threshold(s): "
                f"{inline_summary}{suffix}. Full details: {everpaste_url}",
            )
        return hc_types.HealthCheckResult(status=hc_types.HealthCheckStatus.PASS)

    def verify_traffic_rate_threshold(
        self,
        latest_stats: t.List[t.Dict[str, t.Any]],
        threshold: hc_types.TrafficRateThreshold,
        base_bandwidth_gbps: float = DEFAULT_BASE_BANDWIDTH_GBPS,
        rate_tolerance_percent: float | None = None,
        rate_metrics: t.Sequence[str] | None = None,
    ) -> t.List[t.Dict[str, t.Any]]:
        """
        Verify if the port stats exceed the given threshold.

        Args:
            latest_stats: A list of port statistics.
            threshold: The threshold value to compare against (default is 0.0).
            base_bandwidth_gbps: Reference bandwidth (Gbps) used when
                ``threshold.threshold_type == PERCENT``. Defaults to 400.0 for
                back-compat with configs written against 400G ports; pass the
                real port speed (e.g. 200 for 200G, 800 for 800G) via
                ``check_params["base_bandwidth_gbps"]``.
            rate_tolerance_percent: When set, treats the threshold as an expected
                rate and requires the selected rates to remain within this percentage
                above or below it. When omitted, preserves the historical
                lower-bound-only behavior.
            rate_metrics: Optional ``["tx_rate"]``, ``["rx_rate"]``, or both.
                Omitting it preserves checks of both directions. This selection
                is independent of the legacy threshold.metric field.

        Returns:
            A list of dictionaries containing the ports that exceeded the threshold.
        """
        rate_tolerance_percent = self._validate_rate_tolerance_percent(
            rate_tolerance_percent
        )
        rate_metrics = self._validate_rate_metrics(rate_metrics)
        rate_violations = []

        threshold_value = threshold.value
        value_type = threshold.threshold_type
        expected_rate_gbps = (
            base_bandwidth_gbps * (threshold_value / 100.0)
            if value_type == hc_types.ThresholdType.PERCENT
            else threshold_value
        )
        tolerance = (rate_tolerance_percent or 0) / 100.0
        minimum_rate_gbps = expected_rate_gbps * (1.0 - tolerance)
        maximum_rate_gbps = (
            expected_rate_gbps * (1.0 + tolerance)
            if rate_tolerance_percent is not None
            else None
        )
        observed_identifiers = set()

        for stat in latest_stats:
            identifier = stat["identifier"]

            # If traffic item names are specified, make sure the identifier matches one of them
            if threshold.names and identifier not in threshold.names:
                continue
            observed_identifiers.add(identifier)

            rates: dict[str, float | None] = {}
            for metric, key in _RATE_KEYS.items():
                try:
                    rates[metric] = float(stat[key]) / 1000.0
                except (KeyError, TypeError, ValueError):
                    rates[metric] = None
            tx_rate_gbps = rates["tx_rate"]
            rx_rate_gbps = rates["rx_rate"]

            self.logger.info(
                f"For {identifier} observed traffic rate - Tx Rate: {tx_rate_gbps} Gbps, Rx Rate: {rx_rate_gbps} Gbps"
            )

            invalid_metrics = []
            selected_rates: list[float] = []
            for metric in rate_metrics:
                rate = rates[metric]
                if rate is None or not math.isfinite(rate):
                    invalid_metrics.append(metric)
                else:
                    selected_rates.append(rate)
            if invalid_metrics:
                rate_is_invalid = True
            elif rate_tolerance_percent is None:
                rate_is_invalid = any(
                    rate <= minimum_rate_gbps for rate in selected_rates
                )
            else:
                assert maximum_rate_gbps is not None
                rate_is_invalid = not all(
                    minimum_rate_gbps <= rate <= maximum_rate_gbps
                    for rate in selected_rates
                )

            if rate_is_invalid:
                violation = {
                    "identifier": identifier,
                    "Tx Rate (Gbps)": tx_rate_gbps,
                    "Rx Rate (Gbps)": rx_rate_gbps,
                    "Minimum Rate (Gbps)": minimum_rate_gbps,
                }
                if maximum_rate_gbps is not None:
                    violation["Maximum Rate (Gbps)"] = maximum_rate_gbps
                if invalid_metrics:
                    violation["Reason"] = (
                        "Missing or nonfinite selected rate(s): "
                        + ", ".join(invalid_metrics)
                    )
                rate_violations.append(violation)

        missing_identifiers = (
            set(threshold.names) - observed_identifiers
            if threshold.names
            else ({"<all traffic items>"} if not observed_identifiers else set())
        )
        for identifier in sorted(missing_identifiers):
            rate_violations.append(
                {
                    "identifier": identifier,
                    "Tx Rate (Gbps)": None,
                    "Rx Rate (Gbps)": None,
                    "Minimum Rate (Gbps)": minimum_rate_gbps,
                    "Reason": "Expected traffic item missing from rate statistics",
                }
            )
        return rate_violations

    @staticmethod
    def _validate_rate_metrics(value: t.Any) -> tuple[str, ...]:
        if value is None:
            return ("tx_rate", "rx_rate")
        if (
            not isinstance(value, (list, tuple))
            or not value
            or any(
                not isinstance(metric, str) or metric not in _RATE_KEYS
                for metric in value
            )
            or len(set(value)) != len(value)
        ):
            raise ValueError(
                "rate_metrics must be a nonempty list of unique 'tx_rate' or 'rx_rate' values"
            )
        return tuple(value)

    @staticmethod
    def _validate_rate_tolerance_percent(value: t.Any) -> float | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(
                "rate_tolerance_percent must be a number between 0 and 100"
            )
        tolerance = float(value)
        if not 0 <= tolerance <= 100:
            raise ValueError("rate_tolerance_percent must be between 0 and 100")
        return tolerance
