# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
import asyncio
import time
import typing as t

from neteng.fboss.bgp_thrift.types import BgpInitializationEvent
from taac.constants import TestDevice
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
)
from taac.health_check.health_check import types as hc_types


class BgpConvergenceHealthCheck(AbstractDeviceHealthCheck[hc_types.BaseHealthCheckIn]):
    CHECK_NAME = hc_types.CheckName.BGP_CONVERGENCE_CHECK
    OPERATING_SYSTEMS = [
        "FBOSS",
        "EOS",
    ]

    async def _run(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        convergence_threshold = check_params.get(
            "convergence_threshold", 150
        )  # 150 seconds
        start_event = check_params.get(
            "start_event", BgpInitializationEvent.AGENT_CONFIGURED.value
        )
        end_event = check_params.get(
            "end_event", BgpInitializationEvent.INITIALIZED.value
        )
        fail_on_eor_expired = check_params.get("fail_on_eor_expired", True)
        start_event_enum = BgpInitializationEvent(int(start_event))
        end_event_enum = BgpInitializationEvent(int(end_event))
        bgp_initialization_events = (
            # pyrefly: ignore [missing-attribute]
            await self.driver.async_get_bgp_initialization_events()
        )
        if (
            fail_on_eor_expired
            and BgpInitializationEvent.EOR_TIMER_EXPIRED in bgp_initialization_events
        ):
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=f"EOR timer expired on {obj.name} during BGP convergence",
            )
        if not bgp_initialization_events.get(
            end_event_enum
        ) or not bgp_initialization_events.get(start_event_enum):
            end_time = time.time() + convergence_threshold
            CHECK_INTERVAL = 5
            while time.time() < end_time:
                await asyncio.sleep(CHECK_INTERVAL)
                if hasattr(self.driver, "is_bgp_converged_fib_ready"):
                    converged = await self.driver.is_bgp_converged_fib_ready()
                elif hasattr(self.driver, "async_is_bgp_initialization_converged"):
                    converged = (
                        await self.driver.async_is_bgp_initialization_converged()
                    )
                else:
                    converged = False
                if converged:
                    break
            bgp_initialization_events = (
                # pyrefly: ignore [missing-attribute]
                await self.driver.async_get_bgp_initialization_events()
            )

        # Build detailed stage timing information
        def get_stage_details(events_dict):
            if not events_dict:
                return "No events recorded"

            sorted_events = sorted(
                [(event, timestamp) for event, timestamp in events_dict.items()],
                key=lambda x: x[1],
            )

            stage_times = []
            for i in range(len(sorted_events)):
                event, timestamp = sorted_events[i]
                if i == 0:
                    stage_times.append(f"{event.name}: {timestamp / 1000:.2f}s")
                else:
                    prev_timestamp = sorted_events[i - 1][1]
                    time_diff = (timestamp - prev_timestamp) / 1000
                    stage_times.append(f"{event.name}: +{time_diff:.2f}s")

            return ", ".join(stage_times)

        stage_details = get_stage_details(bgp_initialization_events)

        if (
            fail_on_eor_expired
            and BgpInitializationEvent.EOR_TIMER_EXPIRED in bgp_initialization_events
        ):
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=f"EOR timer expired on {obj.name} during BGP convergence. Stage times: {stage_details}",
            )
        if not bgp_initialization_events.get(
            start_event_enum
        ) or not bgp_initialization_events.get(end_event_enum):
            msg = (
                f"BGP did not publish {start_event_enum.name} and/or {end_event_enum.name} event on {obj.name} "
                f"within {convergence_threshold} seconds. Stage times: {stage_details}"
            )
            self.logger.debug(msg)
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=msg,
            )

        convergence_time_in_sec = (
            bgp_initialization_events[end_event_enum]
            - bgp_initialization_events[start_event_enum]
        ) / 1000
        if convergence_time_in_sec > convergence_threshold:
            msg = (
                f"BGP transitioned from event {start_event_enum.name} to {end_event_enum.name} on {obj.name} in "
                f"{convergence_time_in_sec:.2f} seconds which is more than the threshold of {convergence_threshold} seconds. "
                f"Stage times: {stage_details}"
            )
            self.logger.debug(msg)
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=msg,
            )
        self.logger.debug(
            f"BGP transitioned from event {start_event_enum.name} to {end_event_enum.name} on {obj.name} in {convergence_time_in_sec} seconds"
        )

        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
            message=f"BGP converged in {convergence_time_in_sec:.2f} seconds (from {start_event_enum.name} to {end_event_enum.name}). Stage times: {stage_details}",
        )
