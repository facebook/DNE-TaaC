# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import typing as t

from taac.health_checks.abstract_health_check import (
    AbstractIxiaHealthCheck,
)
from neteng.test_infra.dne.taac.ixia.taac_ixia import TaacIxia as Ixia
from taac.utils.common import async_everpaste_str
from taac.health_check.health_check import types as hc_types
from tabulate import tabulate


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
        less_than_thresholds = []
        all_thresholds = list(input.thresholds)

        for threshold in all_thresholds:
            less_than_thresholds.extend(
                self.verify_traffic_rate_threshold(latest_stats, threshold)
            )

        if less_than_thresholds:
            # Use the Everpaste URL directly; it is already a clickable internalfb.com
            # link, so the throttled fburl tier (createFBUrl) is unnecessary here.
            everpaste_url = await async_everpaste_str(
                tabulate(less_than_thresholds, headers="keys", tablefmt="simple_grid")
            )
            inline_summary = [
                f"{t['identifier']}: Tx={t['Tx Rate (Gbps)']}Gbps, Rx={t['Rx Rate (Gbps)']}Gbps"
                for t in less_than_thresholds[:5]
            ]
            suffix = (
                f" (+{len(less_than_thresholds) - 5} more)"
                if len(less_than_thresholds) > 5
                else ""
            )
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=f"Traffic rate lower than the defined threshold(s): "
                f"{inline_summary}{suffix}. Full details: {everpaste_url}",
            )
        return hc_types.HealthCheckResult(status=hc_types.HealthCheckStatus.PASS)

    def verify_traffic_rate_threshold(
        self,
        latest_stats: t.List[t.Dict[str, t.Any]],
        threshold: hc_types.TrafficRateThreshold,
    ) -> t.List[t.Dict[str, t.Any]]:
        """
        Verify if the port stats exceed the given threshold.

        Args:
            latest_stats: A list of port statistics.
            threshold: The threshold value to compare against (default is 0.0).

        Returns:
            A list of dictionaries containing the ports that exceeded the threshold.
        """
        less_than_thresholds = []

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
            base_bandwidth_gbps = 400.0  # Assuming 400 Gbps base bandwidth

            if value_type == hc_types.ThresholdType.PERCENT:
                tx_rate_threshold_gbps = base_bandwidth_gbps * (threshold_value / 100.0)
                rx_rate_threshold_gbps = base_bandwidth_gbps * (threshold_value / 100.0)

            else:
                tx_rate_threshold_gbps = threshold_value
                rx_rate_threshold_gbps = threshold_value

            # Check if the TX or RX rates exceed the threshold
            if (
                tx_rate_gbps <= tx_rate_threshold_gbps
                or rx_rate_gbps <= rx_rate_threshold_gbps
            ):
                less_than_thresholds.append(
                    {
                        "identifier": identifier,
                        "Tx Rate (Gbps)": tx_rate_gbps,
                        "Rx Rate (Gbps)": rx_rate_gbps,
                    }
                )

        return less_than_thresholds
