# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
import asyncio
import time
import typing as t

from taac.constants import TestDevice
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
)
from taac.health_checks.constants import (
    DAILY_TABLE_TRANSFORM_DESC,
)
from taac.internal.ods_utils import (
    async_generate_ods_url,
    async_query_ods,
)
from taac.health_check.health_check import types as hc_types


UNCLEAN_EXIT_KEY_DESC = "{service}.unclean_exits"
DEFAULT_SERVICE_NAMES = [
    "wedge_agent",
    "bgpd",
    "netstate",
    "fsdb",
    "qsfp_service",
    "openr",
    "fan",
    "fboss_sw_agent",
    "fboss_hw_agent@0",
    "fboss_hw_agent@1",
    "coop",
]


class UncleanExitHealthCheck(AbstractDeviceHealthCheck[hc_types.BaseHealthCheckIn]):
    CHECK_NAME = hc_types.CheckName.UNCLEAN_EXIT_CHECK
    OPERATING_SYSTEMS = ["FBOSS"]

    async def _run(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        start_time = check_params["start_time"]
        services = check_params.get("services", DEFAULT_SERVICE_NAMES)
        exclude_services = check_params.get("exclude_services", [])
        if exclude_services:
            services = [s for s in services if s not in exclude_services]
        # wait x seconds before checking ods data
        sleep_timer = check_params.get("sleep_timer", 120)
        if sleep_timer > 0:
            await asyncio.sleep(sleep_timer)
        end_time = check_params.get("end_time", time.time())
        key_desc = ",".join(
            [UNCLEAN_EXIT_KEY_DESC.format(service=service) for service in services]
        )
        try:
            ods_data = await async_query_ods(
                entity_desc=obj.name,
                key_desc=key_desc,
                transform_desc=DAILY_TABLE_TRANSFORM_DESC,
                start_time=int(start_time),
                end_time=int(end_time),
            )
        except Exception as e:
            # ODS counter-side throttling is a transient infra issue, not a
            # DUT-side problem. Treat as SKIP so the playbook doesn't
            # false-error (the next playbook retries naturally after backoff).
            # Mirrors the sibling fix in CpuUtilizationHealthCheck +
            # MemoryUtilizationHealthCheck (D107783972 family).
            err_msg = str(e)
            if "throttling your requests" in err_msg.lower():
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.SKIP,
                    message=(
                        f"ODS counter throttled — skipping this iteration of "
                        f"UncleanExitHealthCheck (will retry on next "
                        f"playbook). Underlying error: {err_msg}"
                    ),
                )
            raise

        if not ods_data:
            ods_query_url = await async_generate_ods_url(
                entity_desc=obj.name,
                key_desc=key_desc,
                start_time=int(start_time),
                end_time=int(end_time),
            )
            msg = f"ODS query returned no data: {ods_query_url}"
            self.logger.debug(msg)
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.SKIP,
                message=msg,
            )
        unclean_exits_data = ods_data[obj.name]

        unclean_exits = []
        for key_desc, data in unclean_exits_data.items():
            for timestamp, value in data.items():
                if value != 0.0:
                    msg = f"Unclean exit detected for {key_desc} at {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(int(timestamp)))}"
                    self.logger.debug(msg)
                    unclean_exits.append(msg)
        if unclean_exits:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=f"Unclean exits found: {unclean_exits}",
            )
        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
        )
