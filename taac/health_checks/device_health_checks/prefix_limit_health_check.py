# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""PREFIX_LIMIT_CHECK — assert the DUT's BGP switch prefix limit.

``create_prefix_limit_check()`` has existed in ``healthcheck_definitions.py``
for a while, but no class ever claimed ``CheckName.PREFIX_LIMIT_CHECK``. Since
the registry is built as ``{cls.CHECK_NAME: cls for cls in
POINT_IN_TIME_HEALTH_CHECKS}``, requesting the check raised a bare
``KeyError(CheckName.PREFIX_LIMIT_CHECK)`` -- surfacing to the user as the
uninformative ``Step ValidationStep failed on <dut>:
<CheckName.PREFIX_LIMIT_CHECK: 23>``, because the exception's message *is* the
key. Any config listing this check (the NPI cpu-queue family, the BGP/platform
hardening conveyors, snc_single_node_topology_mimic_fauu) therefore failed
validation on a DUT that was otherwise healthy.

What it validates: the prefix limit bgpd is actually running with, read back
from ``getRunningConfig()`` via ``async_get_bgp_prefix_limit()``, matches what
the test expects. In the NPI flow a setup patcher writes
``switch_limit_config.prefix_limit`` and this check confirms the write landed,
so a silently-dropped patcher fails the test rather than letting it run against
the wrong scale ceiling.
"""

import typing as t

from taac.constants import TestDevice
from taac.health_checks.abstract_health_check import AbstractDeviceHealthCheck
from taac.health_check.health_check import types as hc_types
from taac.utils.driver_factory import async_get_device_driver


class PrefixLimitHealthCheck(AbstractDeviceHealthCheck[hc_types.BaseHealthCheckIn]):
    CHECK_NAME = hc_types.CheckName.PREFIX_LIMIT_CHECK
    OPERATING_SYSTEMS = ["FBOSS"]
    # Reads a static config value: a real mismatch means the config on the box
    # is wrong, which retrying cannot change.
    RETRY_ON_FAIL = False

    async def _run(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        expected = check_params.get("prefix_limit")
        if expected is None:
            # Bare create_prefix_limit_check() -- nothing to compare against.
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

        driver = await async_get_device_driver(obj.name)
        actual = await driver.async_get_bgp_prefix_limit()

        if actual is None:
            # The accessor regex-matches switch_limit_config out of the running
            # config; None means bgpd reported no such stanza at all, which is
            # a real finding -- the limit is unset, not merely different.
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
                    f"{obj.name}: BGP prefix limit is {actual}, expected "
                    f"{expected_int}"
                ),
            )
        return hc_types.HealthCheckResult(status=hc_types.HealthCheckStatus.PASS)
