# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import asyncio
import sys
import time
import typing as t

from ixia.ixia import types as ixia_types
from taac.health_checks.abstract_health_check import (
    AbstractIxiaHealthCheck,
)
from taac.health_checks.common_utils import evaluate_comparison
from neteng.test_infra.dne.taac.ixia.taac_ixia import TaacIxia as Ixia
from taac.utils.common import async_everpaste_str
from taac.utils.json_thrift_utils import try_thrift_to_dict
from taac.health_check.health_check import types as hc_types
from tabulate import tabulate


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
        while time.time() - obj.traffic_items_start_time < input.sleep_time:
            time.sleep(0.1)
        since_time = time.time()
        # this is necessary to allow in-flight traffic to arrive at the destination
        obj.stop_traffic()
        await asyncio.sleep(input.sleep_time)
        latest_stats = obj.get_latest_stats(since_time=since_time)
        violations = []
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
                    names=list(remaining_identifiers), str_value="0"
                ),
            ]
        else:
            all_thresholds = list(input.thresholds)
        for threshold in all_thresholds:
            violations.extend(
                self.verify_packet_loss_threshold(latest_stats, threshold)
            )
        # pyrefly: ignore [bad-argument-type]
        violations_dict = [try_thrift_to_dict(violation) for violation in violations]
        if violations:
            # Use the Everpaste URL directly; it is already a clickable internalfb.com
            # link, so the throttled fburl tier (createFBUrl) is unnecessary here.
            everpaste_url = await async_everpaste_str(
                tabulate(violations_dict, headers="keys", tablefmt="simple_grid")
            )
            inline_summary = [
                f"{v.get('name', 'unknown')}: observed={v.get('str_value', '?')}"
                for v in violations_dict[:5]
            ]
            suffix = (
                f" (+{len(violations_dict) - 5} more)"
                if len(violations_dict) > 5
                else ""
            )
            result = hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=f"Packet loss violated the defined threshold(s): "
                f"{inline_summary}{suffix}. Full details: {everpaste_url}",
            )
        else:
            result = hc_types.HealthCheckResult(status=hc_types.HealthCheckStatus.PASS)
        # Only clear traffic stats if not explicitly disabled.
        if not check_params.get("skip_clear_stats_at_end", False):
            obj.clear_traffic_stats()
        return result

    def verify_packet_loss_threshold(
        self,
        latest_stats: t.List[t.Dict[str, t.Any]],
        threshold: hc_types.PacketLossThreshold,
    ) -> t.List[t.Dict[str, t.Any]]:
        violations = []
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

        # pyrefly: ignore [bad-return]
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
        enabled_traffic_items = [
            traffic_item
            for traffic_item in ixia.get_traffic_items()
            if traffic_item.Enabled
        ]
        for traffic_item in enabled_traffic_items:
            if (
                ixia_types.TRAFFIC_STATS_TRACKING_TYPE_MAP[
                    ixia_types.TrafficStatsTrackingType.TRAFFIC_ITEM
                ]
                in traffic_item.Tracking.find().TrackBy
            ):
                return True
        return False
