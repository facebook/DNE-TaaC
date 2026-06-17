# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
import typing as t

from taac.constants import TestDevice
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
)
from taac.health_checks.constants import (
    EOS_CORE_DUMP_FILENAME_REGEX,
)
from taac.utils.health_check_utils import (
    async_find_critical_core_dumps,
    format_timestamp,
)
from taac.health_check.health_check import types as hc_types


class DeviceCoreDumpsHealthCheck(AbstractDeviceHealthCheck[hc_types.BaseHealthCheckIn]):
    CHECK_NAME = hc_types.CheckName.DEVICE_CORE_DUMPS_CHECK
    OPERATING_SYSTEMS = ["FBOSS", "EOS"]

    async def _run(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        start_time = check_params.get("start_time", 0)
        core_dumps_to_ignore = check_params.get("core_dumps_to_ignore", [])
        self.logger.info(
            f"Checking for new core dumps on {obj.name} since {start_time}"
        )
        core_dumps = await async_find_critical_core_dumps(obj.name)
        self.logger.info(
            f"Found {len(core_dumps)} core dumps on {obj.name}: {core_dumps}"
        )
        new_core_dumps = []
        for core_dump, timestamp in core_dumps.items():
            if timestamp > start_time and core_dump not in core_dumps_to_ignore:
                new_core_dumps.append(core_dump)
        if new_core_dumps:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=f"New Critical core dumps found on {obj.name}: {new_core_dumps}",
            )
        return hc_types.HealthCheckResult(status=hc_types.HealthCheckStatus.PASS)

    async def _run_arista(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        start_time = check_params.get("start_time", 0)
        core_dumps_to_ignore = check_params.get("core_dumps_to_ignore", [])
        self.logger.info(
            f"Checking for new core dumps on EOS device {obj.name} "
            f"since {format_timestamp(start_time) if start_time else 'epoch'}"
        )
        core_dumps = await async_find_critical_core_dumps(
            obj.name, start_time=start_time
        )
        self.logger.info(
            f"Found {len(core_dumps)} critical core dumps on {obj.name}: {core_dumps}"
        )
        new_core_dumps = {}
        for core_dump, timestamp in core_dumps.items():
            if core_dump in core_dumps_to_ignore:
                continue
            # Parse the real timestamp from the filename if possible
            match = EOS_CORE_DUMP_FILENAME_REGEX.match(core_dump)
            if match:
                file_ts = int(match.group("timestamp"))
            else:
                file_ts = timestamp
            if file_ts > start_time:
                new_core_dumps[core_dump] = file_ts

        if new_core_dumps:
            details = []
            for filename, ts in new_core_dumps.items():
                match = EOS_CORE_DUMP_FILENAME_REGEX.match(filename)
                if match:
                    details.append(
                        f"  - {filename} (process={match.group('exec_name')}, "
                        f"pid={match.group('pid')}, time={format_timestamp(ts)})"
                    )
                else:
                    details.append(f"  - {filename} (time={format_timestamp(ts)})")
            detail_str = "\n".join(details)
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=(
                    f"New critical core dumps found on {obj.name} "
                    f"since {format_timestamp(start_time)}:\n{detail_str}"
                ),
            )
        return hc_types.HealthCheckResult(status=hc_types.HealthCheckStatus.PASS)
