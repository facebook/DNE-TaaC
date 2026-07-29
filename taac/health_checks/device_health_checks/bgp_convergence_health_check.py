# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
import typing as t

from neteng.fboss.bgp_thrift.types import BgpInitializationEvent
from taac.constants import TestDevice
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
)
from taac.health_checks.convergence_observer import (
    ConvergenceOutcome,
    ConvergenceResult,
    ConvergenceSample,
    observe_convergence,
)
from taac.health_check.health_check import types as hc_types


class BgpConvergenceHealthCheck(AbstractDeviceHealthCheck[hc_types.BaseHealthCheckIn]):
    CHECK_NAME = hc_types.CheckName.BGP_CONVERGENCE_CHECK
    # The observer owns transient retries; outer retries would discard its
    # measured duration and any failures latched during the observation.
    RETRY_ON_FAIL = False
    OPERATING_SYSTEMS = [
        "FBOSS",
        "EOS",
    ]

    # Canonical happy-path BGP++ initialization-event order. Excludes
    # EOR_TIMER_EXPIRED (the unhappy-path substitute for ALL_EOR_RECEIVED) and
    # FSDB_SUBSCRIBED (not emitted on EOS/bgpcpp devices). Used by the opt-in
    # `validate_sequence` check.
    EXPECTED_EVENT_SEQUENCE = [
        BgpInitializationEvent.INITIALIZING,
        BgpInitializationEvent.AGENT_CONFIGURED,
        BgpInitializationEvent.PEER_INFO_LOADED,
        BgpInitializationEvent.ALL_EOR_RECEIVED,
        BgpInitializationEvent.RIB_COMPUTED,
        BgpInitializationEvent.FIB_SYNCED,
        BgpInitializationEvent.EOR_SENT,
        BgpInitializationEvent.INITIALIZED,
    ]

    async def _run(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        try:
            convergence_threshold = float(
                check_params.get("convergence_threshold", 150)
            )
            hard_timeout_seconds = float(
                check_params.get("hard_timeout_seconds", convergence_threshold)
            )
            poll_interval_seconds = float(check_params.get("poll_interval_seconds", 5))
            stability_window_seconds = float(
                check_params.get("stability_window_seconds", 0)
            )
            raw_predicate_timeout = check_params.get("predicate_timeout_seconds")
            predicate_timeout_seconds = (
                float(raw_predicate_timeout)
                if raw_predicate_timeout is not None
                else None
            )
            start_event_enum = BgpInitializationEvent(
                int(
                    check_params.get(
                        "start_event",
                        BgpInitializationEvent.AGENT_CONFIGURED.value,
                    )
                )
            )
            end_event_enum = BgpInitializationEvent(
                int(
                    check_params.get(
                        "end_event",
                        BgpInitializationEvent.INITIALIZED.value,
                    )
                )
            )
        except (TypeError, ValueError) as error:
            return self._configuration_failure(obj.name, error)
        fail_on_eor_expired = check_params.get("fail_on_eor_expired", True)
        validate_sequence = check_params.get("validate_sequence", False)
        semantic_failures: t.Dict[str, str] = {}

        async def sample_initialization() -> ConvergenceSample:
            latest_events = (
                # pyrefly: ignore [missing-attribute]
                await self.driver.async_get_bgp_initialization_events()
            )
            stage_details = self._stage_details(latest_events)
            if (
                fail_on_eor_expired
                and BgpInitializationEvent.EOR_TIMER_EXPIRED in latest_events
            ):
                semantic_failures.setdefault(
                    "eor",
                    f"EOR timer expired on {obj.name} during BGP convergence",
                )
            endpoints_present = (
                start_event_enum in latest_events and end_event_enum in latest_events
            )
            if validate_sequence:
                sequence_error = self._validate_event_sequence(
                    latest_events,
                    obj.name,
                    require_initialized=endpoints_present,
                )
                if sequence_error is not None:
                    semantic_failures.setdefault("sequence", sequence_error)
            if not endpoints_present:
                return ConvergenceSample(converged=False, detail=stage_details)

            convergence_time = (
                latest_events[end_event_enum] - latest_events[start_event_enum]
            ) / 1000
            if convergence_time < 0:
                semantic_failures.setdefault(
                    "event_time",
                    f"BGP convergence event timestamps are reversed on {obj.name}: "
                    f"{start_event_enum.name}={latest_events[start_event_enum]}ms, "
                    f"{end_event_enum.name}={latest_events[end_event_enum]}ms",
                )
                return ConvergenceSample(
                    converged=False,
                    detail=stage_details,
                )
            return ConvergenceSample(
                converged=True,
                detail=stage_details,
                convergence_time_seconds=convergence_time,
            )

        try:
            observation = await observe_convergence(
                sample_initialization,
                soft_threshold_seconds=convergence_threshold,
                hard_timeout_seconds=hard_timeout_seconds,
                poll_interval_seconds=poll_interval_seconds,
                stability_window_seconds=stability_window_seconds,
                predicate_timeout_seconds=predicate_timeout_seconds,
            )
        except ValueError as error:
            return self._configuration_failure(obj.name, error)

        self._record_observation(observation)
        message = self._format_result_message(
            observation=observation,
            device_name=obj.name,
            start_event=start_event_enum,
            end_event=end_event_enum,
            semantic_failures=tuple(semantic_failures.values()),
        )
        status = (
            hc_types.HealthCheckStatus.PASS
            if observation.outcome is ConvergenceOutcome.WITHIN_SLA
            and not semantic_failures
            else hc_types.HealthCheckStatus.FAIL
        )
        if status is hc_types.HealthCheckStatus.PASS:
            self.logger.debug(message)
        else:
            self.logger.warning(message)
        return hc_types.HealthCheckResult(status=status, message=message)

    def _configuration_failure(
        self,
        device_name: str,
        error: TypeError | ValueError,
    ) -> hc_types.HealthCheckResult:
        message = f"Invalid BGP convergence configuration for {device_name}: {error}"
        self.add_data_to_log({"convergence_configuration_error": str(error)})
        self.logger.warning(message)
        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.FAIL,
            message=message,
        )

    def _record_observation(self, observation: ConvergenceResult) -> None:
        self.add_data_to_log(
            {
                "convergence_outcome": observation.outcome.value,
                "convergence_soft_threshold_seconds": (
                    observation.soft_threshold_seconds
                ),
                "convergence_hard_timeout_seconds": observation.hard_timeout_seconds,
                "convergence_elapsed_seconds": observation.elapsed_seconds,
                "convergence_time_seconds": observation.convergence_time_seconds,
                "convergence_confirmation_time_seconds": (
                    observation.confirmation_time_seconds
                ),
                "convergence_attempts": observation.attempts,
                "convergence_predicate_error_count": len(observation.predicate_errors),
            }
        )

    def _format_result_message(
        self,
        *,
        observation: ConvergenceResult,
        device_name: str,
        start_event: BgpInitializationEvent,
        end_event: BgpInitializationEvent,
        semantic_failures: t.Tuple[str, ...],
    ) -> str:
        convergence_time = observation.convergence_time_seconds
        soft_threshold = (
            "none"
            if observation.soft_threshold_seconds is None
            else f"{observation.soft_threshold_seconds:.2f}"
        )
        if observation.outcome is ConvergenceOutcome.NOT_CONVERGED:
            if observation.attempts > 0 and len(observation.predicate_errors) == (
                observation.attempts
            ):
                summary = (
                    f"BGP convergence could not be observed on {device_name}: all "
                    f"{observation.attempts} predicate attempts failed within the "
                    f"hard timeout of {observation.hard_timeout_seconds:.2f} seconds"
                )
            else:
                summary = (
                    f"BGP did not publish {start_event.name} and/or {end_event.name} "
                    f"event on {device_name} within the hard timeout of "
                    f"{observation.hard_timeout_seconds:.2f} seconds"
                )
        elif observation.outcome is ConvergenceOutcome.CONVERGED_LATE:
            summary = (
                f"BGP transitioned from event {start_event.name} to "
                f"{end_event.name} on {device_name} in "
                f"{t.cast(float, convergence_time):.2f} seconds, exceeding the "
                f"soft threshold of {soft_threshold} seconds"
            )
        else:
            summary = (
                f"BGP converged in {t.cast(float, convergence_time):.2f} seconds "
                f"(from {start_event.name} to {end_event.name})"
            )

        if semantic_failures:
            summary = f"{' ; '.join(semantic_failures)}. {summary}"
        error_summary = ""
        if observation.predicate_errors:
            last_error = observation.predicate_errors[-1]
            error_summary = (
                f" predicate_errors={len(observation.predicate_errors)} "
                f"last_error={last_error.error_type}: {last_error.message!r}"
            )
        return (
            f"{summary}. [convergence: outcome={observation.outcome.value} "
            f"soft_threshold_seconds={soft_threshold} "
            f"hard_timeout_seconds={observation.hard_timeout_seconds:.2f} "
            f"elapsed_seconds={observation.elapsed_seconds:.2f} "
            f"attempts={observation.attempts}{error_summary}] "
            f"Stage times: {observation.last_observation or 'No events recorded'}"
        )

    @staticmethod
    def _stage_details(
        events: t.Mapping[BgpInitializationEvent, int],
    ) -> str:
        """Format absolute protocol event timestamps in chronological order."""
        if not events:
            return "No events recorded"
        return ", ".join(
            f"{event.name}: {timestamp / 1000:.2f}s"
            for event, timestamp in sorted(events.items(), key=lambda item: item[1])
        )

    def _validate_event_sequence(
        self,
        events_dict: t.Mapping[BgpInitializationEvent, int],
        device_name: str,
        *,
        require_initialized: bool,
    ) -> t.Optional[str]:
        if (
            require_initialized
            and BgpInitializationEvent.INITIALIZED not in events_dict
        ):
            return (
                f"BGP did not reach INITIALIZED on {device_name}; "
                "initialization sequence incomplete"
            )
        return self._validate_present_event_order(events_dict, device_name)

    def _validate_present_event_order(
        self,
        events_dict: t.Mapping[BgpInitializationEvent, int],
        device_name: str,
    ) -> t.Optional[str]:
        present = [
            (event, events_dict[event])
            for event in self.EXPECTED_EVENT_SEQUENCE
            if event in events_dict
        ]
        for prev, curr in zip(present, present[1:]):
            if curr[1] < prev[1]:
                return (
                    f"BGP initialization events out of order on {device_name}: "
                    f"{prev[0].name} ({prev[1] / 1000:.2f}s) occurred after "
                    f"{curr[0].name} ({curr[1] / 1000:.2f}s)"
                )

        return None
