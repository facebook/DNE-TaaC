# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import asyncio
import time
import typing as t

from ixia.ixia import types as ixia_types
from taac.health_checks.abstract_health_check import (
    AbstractIxiaHealthCheck,
)
from taac.health_checks.common_utils import evaluate_comparison
from taac.ixia.taac_ixia import (  # oss-rewrite (force ShipIt re-export to taac.* root)
    TaacIxia as Ixia,
)
from taac.utils.common import async_everpaste_str
from taac.utils.json_thrift_utils import try_thrift_to_dict
from taac.health_check.health_check import types as hc_types
from tabulate import tabulate

_IXIA_SNAPSHOT_BUSY_ERROR = "Snapshot DefaultSnapshotSettings already in progress"
_IXIA_SNAPSHOT_RETRY_ATTEMPTS = 6
_IXIA_SNAPSHOT_RETRY_DELAY_SECONDS = 5


class IxiaPacketLossHealthCheck(
    AbstractIxiaHealthCheck[hc_types.IxiaPacketLossHealthCheckIn]
):
    CHECK_NAME = hc_types.CheckName.IXIA_PACKET_LOSS_CHECK
    DEFAULT_PRIORITY = 40

    async def _run(
        self,
        obj: Ixia,
        input: hc_types.IxiaPacketLossHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        if not obj.has_traffic_items():
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.SKIP,
                message="No traffic items found in the ixia setup.",
            )
        if not self._is_traffic_tracking_enabled(obj):
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.SKIP,
                message="Traffic item tracking is not enabled for any running traffic items",
            )

        if input.clear_traffic_stats:
            obj.clear_traffic_stats()

        # make sure the traffic is running for at least the specified sleep time
        while time.time() - obj.get_traffic_start_time() < input.sleep_time:
            time.sleep(0.1)
        since_time = time.time()
        # this is necessary to allow in-flight traffic to arrive at the destination
        obj.stop_traffic()
        await asyncio.sleep(input.sleep_time)
        latest_stats = await self._get_latest_stats(obj, since_time)
        violations: t.List[hc_types.PacketLossViolation] = []
        missing_identifiers: t.List[str] = []
        all_identifiers = {stat["identifier"] for stat in latest_stats}
        specified_identifiers = set().union(
            *(set(t.names) if t.names else all_identifiers for t in input.thresholds)
        )
        remaining_identifiers = all_identifiers - specified_identifiers
        # Exclude explicitly skipped traffic items from the catch-all default
        skip_items = set(check_params.get("skip_traffic_items", []))
        remaining_identifiers -= skip_items
        if remaining_identifiers:
            # Add a default threshold with 0 packet loss expected for any identifiers not explicitly specified
            all_thresholds = list(input.thresholds) + [
                hc_types.PacketLossThreshold(
                    names=sorted(remaining_identifiers), str_value="0"
                ),
            ]
        else:
            all_thresholds = list(input.thresholds)
        if not latest_stats and any(
            not threshold.names for threshold in all_thresholds
        ):
            missing_identifiers.append("<all traffic items>")
        for threshold in all_thresholds:
            if threshold.names:
                missing_identifiers.extend(
                    sorted(set(threshold.names) - all_identifiers - skip_items)
                )
            violations.extend(
                self.verify_packet_loss_threshold(latest_stats, threshold)
            )
        violations_dict = [try_thrift_to_dict(violation) for violation in violations]
        if violations or missing_identifiers:
            result = await self._failure_result(violations_dict, missing_identifiers)
        else:
            result = hc_types.HealthCheckResult(status=hc_types.HealthCheckStatus.PASS)
        # Only clear traffic stats if not explicitly disabled.
        if not check_params.get("skip_clear_stats_at_end", False):
            obj.clear_traffic_stats()
        return result

    async def _failure_result(
        self,
        violations: t.List[t.Dict[str, t.Any]],
        missing_identifiers: t.List[str],
    ) -> hc_types.HealthCheckResult:
        unique_missing = sorted(set(missing_identifiers))
        details = ""
        if unique_missing:
            details += (
                "Missing traffic items from IXIA statistics: "
                + ", ".join(unique_missing)
                + "\n"
            )
        if violations:
            details += tabulate(violations, headers="keys", tablefmt="simple_grid")
        # Everpaste URLs are already clickable; avoid the throttled fburl tier.
        everpaste_url = await async_everpaste_str(details)

        rendered: t.List[str] = []
        if unique_missing:
            rendered.extend(f"missing={item}" for item in unique_missing[:5])
        remaining_slots = max(0, 5 - len(rendered))
        rendered.extend(
            f"{violation.get('name', 'unknown')}: "
            f"observed={violation.get('str_value', '?')}"
            for violation in violations[:remaining_slots]
        )
        total_count = len(unique_missing) + len(violations)
        suffix = (
            f" (+{total_count - len(rendered)} more)"
            if total_count > len(rendered)
            else ""
        )
        if violations and unique_missing:
            prefix = "Packet-loss violations and missing traffic items"
        elif violations:
            prefix = "Packet loss violated the defined threshold(s)"
        else:
            prefix = "Expected traffic items were missing from IXIA statistics"
        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.FAIL,
            message=f"{prefix}: {rendered}{suffix}. Full details: {everpaste_url}",
        )

    async def _get_latest_stats(
        self, obj: Ixia, since_time: float
    ) -> t.List[t.Dict[str, t.Any]]:
        """Read IXIA stats while tolerating transient chassis snapshot contention."""
        for attempt in range(1, _IXIA_SNAPSHOT_RETRY_ATTEMPTS + 1):
            try:
                return obj.get_latest_stats(since_time=since_time)
            except Exception as error:
                # RESTPy surfaces snapshot contention through multiple exception
                # classes across releases. Retry only this exact chassis error
                # and immediately re-raise every other exception.
                if (
                    _IXIA_SNAPSHOT_BUSY_ERROR not in str(error)
                    or attempt == _IXIA_SNAPSHOT_RETRY_ATTEMPTS
                ):
                    raise
                self.logger.warning(
                    "IXIA statistics snapshot is busy; retrying in "
                    f"{_IXIA_SNAPSHOT_RETRY_DELAY_SECONDS}s "
                    f"({attempt}/{_IXIA_SNAPSHOT_RETRY_ATTEMPTS})"
                )
                await asyncio.sleep(_IXIA_SNAPSHOT_RETRY_DELAY_SECONDS)
        raise AssertionError("unreachable")

    def verify_packet_loss_threshold(
        self,
        latest_stats: t.List[t.Dict[str, t.Any]],
        threshold: hc_types.PacketLossThreshold,
    ) -> t.List[hc_types.PacketLossViolation]:
        violations: t.List[hc_types.PacketLossViolation] = []
        for statistic in latest_stats:
            entity_id = statistic["identifier"]
            if not threshold.names or entity_id in threshold.names:
                key = hc_types.PACKET_LOSS_METRIC_MAP[threshold.metric]
                if key not in statistic:
                    self.logger.error(
                        f"Skipping threshold for {entity_id} as {key} is not present"
                    )
                    continue

                self.logger.info(
                    f"For {entity_id}, observed packet loss - "
                    + "".join(
                        f"{key}: {statistic[key]} "
                        for key in hc_types.PACKET_LOSS_METRIC_MAP.values()
                    )
                )
                metric_value = statistic[key]
                if threshold.expect_packet_loss:
                    if metric_value == 0:
                        violations.append(
                            hc_types.PacketLossViolation(
                                name=entity_id,
                                str_value=str(metric_value),
                                threshold=threshold,
                            )
                        )
                elif not evaluate_comparison(
                    metric_value,
                    threshold.comparison,
                    threshold.str_value,
                    lower_bound_str=threshold.lower_bound,
                    upper_bound_str=threshold.upper_bound,
                ):
                    violations.append(
                        hc_types.PacketLossViolation(
                            name=entity_id,
                            str_value=str(metric_value),
                            threshold=threshold,
                        )
                    )
        return violations

    def _default_input(self, obj: Ixia) -> hc_types.IxiaPacketLossHealthCheckIn:
        return hc_types.IxiaPacketLossHealthCheckIn(
            thresholds=[
                hc_types.PacketLossThreshold(
                    str_value="0",
                )
            ],
        )

    def _is_traffic_tracking_enabled(self, ixia: Ixia) -> bool:
        traffic_items = ixia.get_traffic_items()
        if not traffic_items:
            return False
        # OTG returns flow name strings — always tracked
        if isinstance(traffic_items[0], str):
            return True
        # restpy returns TrafficItem objects with .Enabled and .Tracking
        enabled_traffic_items = [ti for ti in traffic_items if ti.Enabled]
        for traffic_item in enabled_traffic_items:
            if (
                ixia_types.TRAFFIC_STATS_TRACKING_TYPE_MAP[
                    ixia_types.TrafficStatsTrackingType.TRAFFIC_ITEM
                ]
                in traffic_item.Tracking.find().TrackBy
            ):
                return True
        return False
