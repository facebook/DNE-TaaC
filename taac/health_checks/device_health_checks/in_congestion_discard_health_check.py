# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import operator
import typing as t

from taac.constants import TestDevice
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
)
from taac.utils.common import async_everpaste_str, async_get_fburl
from taac.utils.health_check_utils import get_fb303_client
from taac.health_check.health_check import types as hc_types

# FBOSS exports in-congestion discards as a *port* monotonic counter, and
# optionally one counter per ingress priority group. See
# fboss/agent/hw/bcm/BcmPort.cpp (reinitPortStat(kInCongestionDiscards(),
# portName) plus getPriorityGroupStatsKey(), which appends ".pg<N>") and
# HwPortFb303Stats::kPriorityGroupMonotonicCounterStatKeys(). There is no
# per-egress-queue variant of this counter.
_COUNTER_BASE = "in_congestion_discards"
_COUNTER_SUFFIX = "sum.60"


def _port_counter_key(interface: str) -> str:
    return f"{interface}.{_COUNTER_BASE}.{_COUNTER_SUFFIX}"


def _pg_counter_key(interface: str, pg: int) -> str:
    return f"{interface}.{_COUNTER_BASE}.pg{pg}.{_COUNTER_SUFFIX}"


class InCongestionDiscardHealthCheck(
    AbstractDeviceHealthCheck[hc_types.BaseHealthCheckIn]
):
    """Check ASIC in-congestion discard counters via fb303 (FBOSS only).

    check_params (JSON):
        priority_groups: list[int] — ingress priority groups to check in
            addition to the port total. Omit to check only the port counter.
        threshold: int — discard count the comparison is applied against
            (default: 0)
        comparison: str — a ``ComparisonType`` member name (default:
            "EQUAL_TO"). Unknown names are a configuration error, not a
            silent fallback.
    """

    CHECK_NAME: hc_types.CheckName = hc_types.CheckName.IN_CONGESTION_DISCARD_CHECK

    # Maps a ComparisonType onto "is the observation acceptable?". BETWEEN
    # needs a second bound this check does not model, so it is rejected up
    # front rather than silently treated as healthy.
    _COMPARATORS: t.Mapping[hc_types.ComparisonType, t.Callable[[int, int], bool]] = {
        hc_types.ComparisonType.EQUAL_TO: operator.eq,
        hc_types.ComparisonType.LESS_THAN: operator.lt,
        hc_types.ComparisonType.GREATER_THAN: operator.gt,
        hc_types.ComparisonType.LESS_THAN_EQUAL_TO: operator.le,
        hc_types.ComparisonType.GREATER_THAN_EQUAL_TO: operator.ge,
    }

    def _extract_params(
        self, obj: TestDevice, check_params: t.Dict[str, t.Any]
    ) -> t.Tuple[t.List[str], t.List[int], int, hc_types.ComparisonType]:
        priority_groups = check_params.get("priority_groups") or []
        threshold = check_params.get("threshold", 0)
        # check_params comes from JSON, so `comparison` need not be a string.
        # str() first: .strip() on an int would raise AttributeError past the
        # KeyError handler and crash the check instead of reporting a config
        # error.
        comparison_str = str(check_params.get("comparison", "EQUAL_TO"))
        try:
            comparison = hc_types.ComparisonType[comparison_str.strip()]
        except KeyError as e:
            raise ValueError(
                f"Unknown comparison {comparison_str!r}; expected one of "
                f"{sorted(c.name for c in self._COMPARATORS)}"
            ) from e
        if comparison not in self._COMPARATORS:
            raise ValueError(
                f"{comparison.name} is not supported by "
                f"{self.CHECK_NAME.name}; expected one of "
                f"{sorted(c.name for c in self._COMPARATORS)}"
            )
        interfaces = [f"{obj.name}:{intf.interface_name}" for intf in obj.interfaces]
        return interfaces, list(priority_groups), threshold, comparison

    async def _run(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        raise NotImplementedError("Use _run_fboss or _run_arista via run_wrapper")

    async def _run_fboss(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        try:
            interfaces, priority_groups, threshold, comparison = self._extract_params(
                obj, check_params
            )
        except ValueError as e:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.ERROR,
                message=str(e),
            )

        if not interfaces:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=(
                    f"{obj.name} reports no interfaces, so no in-congestion "
                    "discard counter could be read."
                ),
            )

        for endpoint in interfaces:
            device, interface = endpoint.split(":")
            wanted = {"port": _port_counter_key(interface)}
            for pg in priority_groups:
                wanted[f"pg{pg}"] = _pg_counter_key(interface, pg)
            try:
                async with await get_fb303_client(device) as client:
                    counters = await client.getSelectedCounters(list(wanted.values()))
            except Exception as e:
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.ERROR,
                    message=(
                        f"Failed to fetch {_COUNTER_BASE} for {device} {interface}: {e}"
                    ),
                )

            # A counter that the agent never exported comes back absent. Reading
            # that as 0 would let the check pass without observing anything, so
            # it is a failure instead.
            missing = [key for key in wanted.values() if key not in counters]
            if missing:
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.FAIL,
                    message=(
                        f"{device} did not export {', '.join(sorted(missing))}; "
                        "in-congestion discards could not be verified."
                    ),
                )

            for scope, key in wanted.items():
                value = counters[key]
                self.logger.info(f"At {endpoint} {scope} {_COUNTER_BASE}: {value}")
                if not self._COMPARATORS[comparison](value, threshold):
                    return await self._fail(
                        device, interface, scope, comparison, value, threshold
                    )

        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
        )

    async def _run_arista(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        # EOS has no counter equivalent to HwPortStats.inCongestionDiscards that
        # we can read through a verified show-command schema. Skipping is
        # explicit; the previous implementation parsed a schema EOS does not
        # return and turned every absent field into 0, so the check passed
        # without ever reading a counter.
        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.SKIP,
            message=(
                f"{obj.name} runs EOS; {self.CHECK_NAME.name} reads FBOSS "
                "fb303 ASIC counters and has no EOS equivalent."
            ),
        )

    async def _fail(
        self,
        device: str,
        interface: str,
        scope: str,
        comparison: hc_types.ComparisonType,
        observed: int,
        expected: int,
    ) -> hc_types.HealthCheckResult:
        everpaste_url = await async_everpaste_str(
            f"{_COUNTER_BASE} {scope}: {observed}"
        )
        everpaste_fburl = await async_get_fburl(everpaste_url)
        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.FAIL,
            message=(
                f"In-congestion discards on {device} {interface} ({scope}): "
                f"observed={observed}, expected {comparison.name} {expected}. "
                f"Report: {everpaste_fburl}"
            ),
        )

    async def skip_check(self, obj: TestDevice) -> t.Tuple[bool, t.Optional[str]]:
        supported_roles = ["RDSW", "FDSW", "EDSW", "DTSW", "RTSW", "SUSW", "BAG"]
        if obj.attributes.role not in supported_roles:
            return True, f"{obj.name}'s device role is not in {supported_roles}"
        return False, None
