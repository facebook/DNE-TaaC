# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""PREFIX_LIMIT_CHECK — validate the DUT's BGP prefix limit.

Internal and OSS builds check different things under this one CheckName:

* Internal: the BGP-learned FIB entries (agent BGP routes minus locally
  originated ones) do not exceed ``prefix_limit`` from check_params, falling
  back to bgpd's configured limit.
* OSS (``TAAC_OSS``): the prefix limit bgpd is running with, read back from
  ``getRunningConfig()``, equals ``prefix_limit``. A setup patcher writes
  ``switch_limit_config.prefix_limit`` and this confirms the write landed, so
  a silently dropped patcher fails the test rather than letting it run against
  the wrong scale ceiling.
"""

import os
import typing as t

from taac.constants import TestDevice
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
)
from taac.utils.common import async_custom_retry
from taac.health_check.health_check import types as hc_types

TAAC_OSS = os.environ.get("TAAC_OSS", "").lower() in ("1", "true", "yes")

if t.TYPE_CHECKING or not TAAC_OSS:
    from openr.thrift.Platform.thrift_types import FibClient


class PrefixLimitHealthCheck(AbstractDeviceHealthCheck[hc_types.BaseHealthCheckIn]):
    CHECK_NAME = hc_types.CheckName.PREFIX_LIMIT_CHECK
    OPERATING_SYSTEMS = ["FBOSS"] if TAAC_OSS else ["FBOSS", "EOS"]
    # The OSS variant reads a static config value: a real mismatch means the
    # config on the box is wrong, which retrying cannot change.
    RETRY_ON_FAIL = not TAAC_OSS

    async def _run(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        if TAAC_OSS:
            return await self._async_check_configured_limit(obj, check_params)
        return await self._async_check_fib_within_limit(check_params)

    async def _async_check_fib_within_limit(
        self, check_params: t.Dict[str, t.Any]
    ) -> hc_types.HealthCheckResult:
        # Use the user-provided limit if given, else the configured one.
        prefix_limit = int(
            check_params.get("prefix_limit")
            or await self.driver.async_get_bgp_prefix_limit()
        )
        try:
            fib_entries_recived_via_bgp = await self.async_get_fib_table_entries_count()
        except Exception as ex:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=f"Unable to get fib entry count details: {ex}",
            )
        if fib_entries_recived_via_bgp > prefix_limit:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=f"Number of FIB entries ({fib_entries_recived_via_bgp}) exceeds the prefix limit with buffer: {prefix_limit}",
            )
        return hc_types.HealthCheckResult(status=hc_types.HealthCheckStatus.PASS)

    @async_custom_retry(max_attempts=5, delay_seconds=30)
    async def async_get_fib_table_entries_count(self) -> int:
        originated_routes = await self.driver.async_get_bgp_originated_routes()
        agent_fib_entries = await self.driver.async_get_route_table_by_client(
            FibClient.BGP.value
        )
        return int(len(agent_fib_entries)) - int(len(originated_routes))

    async def _async_check_configured_limit(
        self, obj: TestDevice, check_params: t.Dict[str, t.Any]
    ) -> hc_types.HealthCheckResult:
        expected = check_params.get("prefix_limit")
        if expected is None:
            # SKIP rather than invent a default: a wrong default would either
            # pass everything or fail everything.
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.SKIP,
                message=(
                    "No 'prefix_limit' in check_params; nothing to assert. "
                    "Pass create_prefix_limit_check(prefix_limit=N)."
                ),
            )
        try:
            # check_params values arrive as strings from json_params.
            expected_int = int(expected)
        except (TypeError, ValueError):
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.ERROR,
                message=f"prefix_limit {expected!r} is not an integer",
            )

        # FBOSS-driver-specific; not on AbstractSwitch.
        get_prefix_limit = getattr(self.driver, "async_get_bgp_prefix_limit", None)
        if get_prefix_limit is None:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.ERROR,
                message=f"{obj.name} driver exposes no BGP prefix limit accessor",
            )
        actual = await get_prefix_limit()

        if actual is None:
            # The accessor regex-matches switch_limit_config out of the running
            # config; None means bgpd reported no such stanza at all -- the
            # limit is unset, not merely different.
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=(
                    f"{obj.name}: bgpd's running config has no "
                    f"switch_limit_config.prefix_limit (expected {expected_int})"
                ),
            )
        if int(actual) != expected_int:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=(
                    f"{obj.name}: BGP prefix limit is {actual}, expected {expected_int}"
                ),
            )
        return hc_types.HealthCheckResult(status=hc_types.HealthCheckStatus.PASS)
