# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
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
                rate and requires both TX and RX to remain within this percentage
                above or below it. When omitted, preserves the historical
                lower-bound-only behavior.

        Returns:
            A list of dictionaries containing the ports that exceeded the threshold.
        """
        rate_tolerance_percent = self._validate_rate_tolerance_percent(
            rate_tolerance_percent
        )
        rate_violations = []

        threshold_value = threshold.value
        value_type = threshold.threshold_type

        for stat in latest_stats:
            identifier = stat["identifier"]

            # If traffic item names are specified, make sure the identifier matches one of them
            if threshold.names and identifier not in threshold.names:
                continue

            tx_rate = stat.get("Tx Rate")
            rx_rate = stat.get("Rx Rate")
            if tx_rate is None and rx_rate is None:
                continue
            # Convert the tx_rate and rx_rate from Mbps to Gbps
            # pyrefly: ignore [unsupported-operation]
            tx_rate_gbps = tx_rate / 1000.0
            # pyrefly: ignore [unsupported-operation]
            rx_rate_gbps = rx_rate / 1000.0

            self.logger.info(
                f"For {identifier} observed traffic rate - Tx Rate: {tx_rate_gbps} Gbps, Rx Rate: {rx_rate_gbps} Gbps"
            )

            if value_type == hc_types.ThresholdType.PERCENT:
                tx_rate_threshold_gbps = base_bandwidth_gbps * (threshold_value / 100.0)
                rx_rate_threshold_gbps = base_bandwidth_gbps * (threshold_value / 100.0)

            else:
                tx_rate_threshold_gbps = threshold_value
                rx_rate_threshold_gbps = threshold_value

            if rate_tolerance_percent is None:
                rate_is_invalid = (
                    tx_rate_gbps <= tx_rate_threshold_gbps
                    or rx_rate_gbps <= rx_rate_threshold_gbps
                )
                minimum_rate_gbps = tx_rate_threshold_gbps
                maximum_rate_gbps = None
            else:
                tolerance = rate_tolerance_percent / 100.0
                minimum_rate_gbps = tx_rate_threshold_gbps * (1.0 - tolerance)
                maximum_rate_gbps = tx_rate_threshold_gbps * (1.0 + tolerance)
                rate_is_invalid = not (
                    minimum_rate_gbps <= tx_rate_gbps <= maximum_rate_gbps
                    and minimum_rate_gbps <= rx_rate_gbps <= maximum_rate_gbps
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
                rate_violations.append(violation)

        return rate_violations

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
