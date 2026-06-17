# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
import json
import time
import typing as t

from taac.constants import TestDevice
from taac.health_checks.abstract_snapshot_health_check import (
    AbstractDeviceSnapshotHealthCheck,
)
from taac.health_checks.constants import (
    EOS_CORE_DUMP_FILENAME_REGEX,
    EOS_CORE_DUMP_PATH,
    Snapshot,
)
from taac.utils.health_check_utils import (
    async_find_critical_core_dumps,
    format_timestamp,
)
from taac.health_check.health_check import types as hc_types


def _parse_eos_core_dump_timestamp(filename: str) -> int:
    """Extract the epoch timestamp from an EOS core dump filename.

    Arista core dump filenames follow the pattern:
        core.<pid>.<epoch_timestamp>.<exec_name>.gz
    e.g. core.4020.1725628991.Bgp-main.gz

    Returns the embedded epoch timestamp, or current time if parsing fails.
    """
    match = EOS_CORE_DUMP_FILENAME_REGEX.match(filename)
    if match:
        return int(match.group("timestamp"))
    return int(time.time())


def _format_core_dump_details(core_dumps: t.Dict[str, int]) -> str:
    """Format core dump filenames and timestamps for human-readable output."""
    details = []
    for filename, ts in core_dumps.items():
        match = EOS_CORE_DUMP_FILENAME_REGEX.match(filename)
        if match:
            exec_name = match.group("exec_name")
            pid = match.group("pid")
            details.append(
                f"  - {filename} (process={exec_name}, pid={pid}, "
                f"time={format_timestamp(ts)})"
            )
        else:
            details.append(f"  - {filename} (time={format_timestamp(ts)})")
    return "\n".join(details)


class CoreDumpsHealthCheck(
    AbstractDeviceSnapshotHealthCheck[hc_types.BaseHealthCheckIn],
):
    CHECK_NAME = hc_types.CheckName.CORE_DUMPS_CHECK
    OPERATING_SYSTEMS = [
        "FBOSS",
        "EOS",
    ]

    async def _async_find_all_eos_core_dumps(
        self,
        obj: TestDevice,
    ) -> t.Dict[str, int]:
        """
        Find ALL core dump files on an EOS device under /var/core/.
        Uses ls -ltr for detailed listing with timestamps for logging.
        Parses real timestamps from the core dump filename pattern
        (core.<pid>.<epoch>.<exec>.gz) instead of using current time.

        Returns:
            Dictionary mapping core dump filenames to their actual timestamps
        """
        cmd = f"bash ls -ltr {EOS_CORE_DUMP_PATH}"
        # pyrefly: ignore [missing-attribute]
        output = await self.driver.async_execute_show_or_configure_cmd_on_shell(cmd)

        core_dumps = {}
        for line in (output or "").splitlines():
            line = line.strip()
            if not line or line.startswith("total"):
                continue
            # ls -ltr output: permissions links owner group size month day time filename
            # e.g.: -rw-r--r-- 1 root root 12345 Apr  3 08:23 core.12089.1775290587.arista_server#n.gz
            parts = line.split()
            if len(parts) < 9:
                continue
            filename = parts[-1]
            if not filename:
                continue
            # Extract the real timestamp from the filename pattern
            ts = _parse_eos_core_dump_timestamp(filename)
            core_dumps[filename] = ts

        self.logger.debug(f"EOS core dump listing on {obj.name}:\n{output}")

        return core_dumps

    async def _async_find_core_dumps(
        self,
        obj: TestDevice,
    ) -> t.Dict[str, int]:
        """
        Find core dumps based on device OS.
        EOS: returns ALL files under /var/core/ (no filtering).
        FBOSS: returns only critical core dumps (existing behavior).
        """
        if obj.attributes.operating_system == "EOS":
            return await self._async_find_all_eos_core_dumps(obj)
        return await async_find_critical_core_dumps(obj.name)

    async def capture_pre_snapshot(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
        timestamp: int,
    ) -> Snapshot:
        core_dumps = await self._async_find_core_dumps(obj)
        self.logger.info(f"Pre-snapshot on {obj.name}: {len(core_dumps)} core dumps")
        if core_dumps:
            self.logger.info(
                f"Pre-existing core dumps on {obj.name}:\n"
                f"{_format_core_dump_details(core_dumps)}"
            )
        return Snapshot(data=core_dumps, timestamp=timestamp)

    async def capture_post_snapshot(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
        timestamp: int,
    ) -> Snapshot:
        core_dumps = await self._async_find_core_dumps(obj)
        self.logger.info(f"Post-snapshot on {obj.name}: {len(core_dumps)} core dumps")
        return Snapshot(data=core_dumps, timestamp=timestamp)

    async def compare_snapshots(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
        pre_snapshot: Snapshot,
        post_snapshot: Snapshot,
    ) -> hc_types.HealthCheckResult:
        core_dumps_to_ignore = json.loads(
            check_params.get("core_dumps_to_ignore", "[]")
        )
        new_core_dumps = {
            k: post_snapshot.data[k]
            for k in set(post_snapshot.data) - set(pre_snapshot.data)
            if k not in core_dumps_to_ignore
        }
        if new_core_dumps:
            details = _format_core_dump_details(new_core_dumps)
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=(f"New core dumps found on {obj.name} during test:\n{details}"),
            )
        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
        )
