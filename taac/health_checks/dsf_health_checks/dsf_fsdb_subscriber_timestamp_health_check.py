# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import datetime
import time
import typing as t

from taac.constants import TestDevice
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
)
from taac.health_check.health_check import types as hc_types

DEFAULT_SUBSCRIBER_NAMES = ["stress_test_client_path"]

# Max allowed seconds between agent start and FSDB session re-establishment
FSDB_SESSION_RECOVERY_TOLERANCE_SECONDS = 5


class DsfFsdbSubscriberTimestampHealthCheck(
    AbstractDeviceHealthCheck[hc_types.BaseHealthCheckIn]
):
    CHECK_NAME = hc_types.CheckName.FSDB_SUBSCRIBER_TIMESTAMP_CHECK
    OPERATING_SYSTEMS = ["FBOSS"]

    async def _run(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        target_device = check_params.get("target_device")
        if target_device and obj.name != target_device:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.SKIP,
                message=f"Skipping {obj.name}: check is targeted at {target_device}",
            )

        start_time = check_params.get("start_time")
        if start_time is None:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message="start_time not provided in check_params",
            )
        start_time = int(start_time)

        subscriber_names = check_params.get(
            "subscriber_names", DEFAULT_SUBSCRIBER_NAMES
        )
        if isinstance(subscriber_names, str):
            subscriber_names = [subscriber_names]

        is_validate_fsdb_session_after_agent_restart = check_params.get(
            "is_validate_fsdb_session_after_agent_restart", False
        )

        # Compute the reference time:
        # - Default: reference_time = start_time (subscribedSince must be before test start)
        # - Agent restart mode: reference_time = agent_start_time + tolerance
        #   (subscribedSince must be before agent_start + 5s, i.e. session recovered quickly)
        if is_validate_fsdb_session_after_agent_restart:
            # pyrefly: ignore [missing-attribute]
            agent_uptime_map = await self.driver.get_agents_uptime(["wedge_agent"])
            agent_uptime = agent_uptime_map.get("wedge_agent", 0)
            agent_start_time = int(time.time()) - agent_uptime
            reference_time = agent_start_time + FSDB_SESSION_RECOVERY_TOLERANCE_SECONDS
            agent_start_human = datetime.datetime.fromtimestamp(
                agent_start_time
            ).strftime("%Y-%m-%d %H:%M:%S")
            reference_label = (
                f"agent_start_time({agent_start_time} / {agent_start_human}) + "
                f"{FSDB_SESSION_RECOVERY_TOLERANCE_SECONDS}s tolerance"
            )
        else:
            reference_time = start_time
            start_time_human = datetime.datetime.fromtimestamp(start_time).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            reference_label = f"test_case_start_time({start_time} / {start_time_human})"

        # pyrefly: ignore [missing-attribute]
        all_subscribers = await self.driver.async_get_all_fsdb_subscribers()

        failures = []
        all_details = []

        for subscriber_name in subscriber_names:
            if subscriber_name not in all_subscribers:
                failures.append(
                    f"No client with subscriber ID '{subscriber_name}' "
                    f"is subscribed on {obj.name} FSDB"
                )
                all_details.append(f"'{subscriber_name}': NOT FOUND on {obj.name} FSDB")
                continue

            for info in all_subscribers[subscriber_name]:
                subscribed_since = info.subscribedSince
                if subscribed_since is None:
                    failures.append(f"'{subscriber_name}': subscribedSince=None")
                    all_details.append(f"'{subscriber_name}': subscribedSince=None")
                elif subscribed_since >= reference_time:
                    sub_human = datetime.datetime.fromtimestamp(
                        subscribed_since
                    ).strftime("%Y-%m-%d %H:%M:%S")
                    failures.append(
                        f"'{subscriber_name}': "
                        f"subscribedSince={subscribed_since} ({sub_human}) >= {reference_label}"
                    )
                    all_details.append(
                        f"'{subscriber_name}': "
                        f"subscribedSince={subscribed_since} ({sub_human}) "
                        f"(FAIL, subscribed after {reference_label})"
                    )
                else:
                    sub_human = datetime.datetime.fromtimestamp(
                        subscribed_since
                    ).strftime("%Y-%m-%d %H:%M:%S")
                    all_details.append(
                        f"'{subscriber_name}': "
                        f"subscribedSince={subscribed_since} ({sub_human}) "
                        f"(OK, subscribed before {reference_label})"
                    )

        details_str = "; ".join(all_details)

        if failures:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=f"FSDB subscriber timestamp check failed on {obj.name}. "
                f"Expectation: subscribedSince should be before {reference_label}. "
                f"Details: {details_str}",
            )

        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
            message=f"All subscribers {subscriber_names} on {obj.name} passed. "
            f"Expectation: subscribedSince should be before {reference_label}. "
            f"Details: {details_str}",
        )

    async def skip_check(self, obj: TestDevice) -> t.Tuple[bool, str | None]:
        supported_roles = ["RDSW", "FDSW", "EDSW"]
        if obj.attributes.role not in supported_roles:
            return True, f"{obj.name}'s device role is not in {supported_roles}"
        return False, None
