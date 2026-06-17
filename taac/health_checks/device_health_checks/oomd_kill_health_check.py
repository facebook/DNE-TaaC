# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
import re
import time
import typing as t
from collections import defaultdict

from taac.constants import TestDevice
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
)
from taac.health_checks.constants import FB_OOMD_LOG_PATH
from taac.health_check.health_check import types as hc_types


class OomdKillHealthCheck(AbstractDeviceHealthCheck[hc_types.BaseHealthCheckIn]):
    CHECK_NAME = hc_types.CheckName.OOMD_KILL_CHECK

    async def _run(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        start_time = check_params["start_time"]
        start_time = int(time.time() - 3600 * 24)
        end_time = int(check_params.get("end_time", time.time()))
        expected_oom_kills = check_params.get(
            "expected_oom_kills", {}
        )  # { slice_1: [process_1, ...] }
        formatted_times = [
            time.strftime("%b %e %H:%M", time.localtime(t))
            for t in range(start_time, end_time, 60)
        ]
        regex = r"\(" + r"\|".join(formatted_times) + r"\)"
        cmd = f'cat {FB_OOMD_LOG_PATH} | grep -ia "{regex}"'
        # pyrefly: ignore [missing-attribute]
        fb_oomd_log_content = await self.driver.async_run_cmd_on_shell(cmd)
        pattern = r"Trying to kill (?P<cgroup_path>/sys/fs/cgroup/[^ ]+)"
        observed_oom_kills = defaultdict(list)
        for log_entry in fb_oomd_log_content.split("\n"):
            match = re.search(pattern, log_entry)
            if match:
                cgroup_path = match.group("cgroup_path")
                parts = cgroup_path.split("/")
                process = parts[-1]
                slice = parts[-2]
                observed_oom_kills[slice].append(process)
        undetected_oom_kills = {}
        for slice in expected_oom_kills:
            undetected = [
                process
                for process in observed_oom_kills[slice]
                if process not in expected_oom_kills.get(slice, [])
            ]
            if undetected:
                undetected_oom_kills[slice] = undetected
        self.logger.debug(f"expected oom kils: {expected_oom_kills}")
        self.logger.debug(f"observed oom kils: {observed_oom_kills}")
        if undetected_oom_kills:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=f"Oom kills not detected: {undetected_oom_kills}",
            )
        return hc_types.HealthCheckResult(status=hc_types.HealthCheckStatus.PASS)
