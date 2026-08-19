# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
import asyncio
import os
import time
import typing as t

from taac.constants import TestDevice
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
)
from taac.health_checks.constants import (
    DAILY_TABLE_TRANSFORM_DESC,
)
from taac.libs.collectors.registry import get_collector
from taac.libs.collectors.systemd_state_collector import (
    SystemdStateCollector,
)
from taac.utils.health_check_utils import (
    async_query_journalctl_unclean_exits,
    collector_window_start,
)
from taac.health_check.health_check import types as hc_types

TAAC_OSS = os.environ.get("TAAC_OSS", "").lower() in ("1", "true", "yes")

if t.TYPE_CHECKING or not TAAC_OSS:
    from taac.internal.ods_utils import (
        async_generate_ods_url,
        async_query_ods,
    )


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
        if TAAC_OSS:
            return await self._run_oss(obj, check_params)

        start_time = check_params["start_time"]
        services = check_params.get("services", DEFAULT_SERVICE_NAMES)
        exclude_services = check_params.get("exclude_services", [])
        if exclude_services:
            services = [s for s in services if s not in exclude_services]
        # wait x seconds before checking ods data
        sleep_timer = check_params.get("sleep_timer", 120)
        if sleep_timer > 0:
            await asyncio.sleep(sleep_timer)
        end_time = time.time()
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

    async def _run_oss(
        self,
        obj: TestDevice,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        """OSS path — no ODS.

        Requires a ``SystemdStateCollector`` started by
        ``CollectorsTestHandler`` and registered under ``"systemd_state"``.
        Queries the collector's ``unclean_samples_in_window`` to detect any
        unclean exit *during* the check window rather than relying on the
        unit's last-run ``Result``. This closes the crash-then-recover
        blindspot of the previous one-shot SSH implementation: systemd's
        ``Result`` reflects the *last* run only, so a service that crashed
        and was auto-restarted would report ``Result=success`` by the time
        a postcheck read it. A periodic sample catches the crash before the
        restart overwrites it.

        Window defaults to ``[test_case_start_time, now]`` — the current
        playbook iteration — and can be overridden per-check via
        ``check_params["window_start"]`` / ``["window_end"]``.
        ``exclude_services`` still lets a playbook drop services it
        intentionally restarts.
        """
        services = check_params.get("services", DEFAULT_SERVICE_NAMES)
        exclude_services = check_params.get("exclude_services", [])
        if exclude_services:
            services = [s for s in services if s not in exclude_services]

        # Optional grace period — extends the window's tail so post-recovery
        # samples the collector took after the playbook returned are included
        # in the query below. The collector's own polling continues while we
        # sleep; no data is fetched here.
        sleep_timer = check_params.get("sleep_timer", 5)
        if sleep_timer > 0:
            await asyncio.sleep(sleep_timer)

        return await self._run_oss_via_collector(obj, services, check_params)

    async def _run_oss_via_collector(
        self,
        obj: TestDevice,
        services: t.Sequence[str],
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        """Window-based unclean-exit check backed by a live collector.

        Query window defaults to the current playbook iteration
        (``[test_case_start_time, now]``). Fallback: if
        ``test_case_start_time`` is unset, use
        ``[now - lookback_sec, now]`` (``lookback_sec=900``). Callers can
        override either endpoint via ``check_params``.
        """
        collector = get_collector("systemd_state")
        if not isinstance(collector, SystemdStateCollector):
            # CollectorsTestHandler starts collectors for every OSS test
            # config, so a missing one here is unexpected. SKIP (not FAIL)
            # per registry.get_collector's contract, but warn loudly --
            # silently losing this check's coverage is exactly the failure
            # mode SKIP is meant to make visible.
            self.logger.warning(
                "No SystemdStateCollector registered under 'systemd_state' -- "
                "CollectorsTestHandler runs by default under TAAC_OSS, so "
                "this means either no FBOSS device in the topology, the "
                "'no_oss_collectors' opt-out tag, or a failed handler setUp. "
                "Skipping."
            )
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.SKIP,
                message=(
                    "No SystemdStateCollector registered under "
                    "'systemd_state'. The test config didn't start one — "
                    "this check has nothing to evaluate."
                ),
            )
        if collector.host != obj.name:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.SKIP,
                message=(
                    f"Registered SystemdStateCollector is bound to host "
                    f"'{collector.host}', not '{obj.name}' — multi-DUT "
                    "collector support isn't implemented; skipping this "
                    "device."
                ),
            )

        now = time.time()
        window_end = check_params.get("window_end", now)
        lookback_sec = check_params.get("lookback_sec", 900)
        window_start = check_params.get(
            "window_start",
            collector_window_start(check_params, window_end, lookback_sec),
        )

        missing_from_collector = [s for s in services if s not in collector.services]
        if missing_from_collector:
            self.logger.warning(
                f"Requested services not monitored by the running "
                f"SystemdStateCollector (started with services="
                f"{collector.services}): {missing_from_collector}. These "
                f"will not be checked."
            )

        unclean = collector.unclean_samples_in_window(
            window_start, window_end, services=services
        )

        # journalctl fallback: catches unclean exits that completed AND were
        # auto-restarted between two collector polls (typically 5s apart) --
        # a SIGKILL to a fast-restarting service like bgpd can slip through
        # the sampler entirely. journalctl persists the ``Failed with result
        # '<reason>'`` message regardless of whether the process restarted,
        # so it closes the sampler's temporal-resolution gap.
        journal_unclean = await async_query_journalctl_unclean_exits(
            self.driver, services, window_start, window_end
        )

        # Coalesce both signals by (service, reason). Track which sources saw
        # each pairing so a reviewer can distinguish "caught by the sampler
        # AND the journal" (typical) from "caught only by journalctl"
        # (sampler missed it -- the exact gap this fallback exists to close)
        # from "caught only by the sampler" (Result flipped back to success
        # before journalctl was queried, or the Failed line was outside the
        # window).
        events: t.Dict[t.Tuple[str, str], t.Set[str]] = {}
        for service, _timestamp, reason in unclean:
            events.setdefault((service, reason), set()).add("collector")
        for service, per_svc_events in journal_unclean.items():
            for _timestamp, reason in per_svc_events:
                events.setdefault((service, reason), set()).add("journalctl")

        if not events:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.PASS,
            )

        lines: t.List[str] = []
        for (service, reason), sources in sorted(events.items()):
            sources_str = "+".join(sorted(sources))
            lines.append(f"{service}: {reason} (via {sources_str})")
        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.FAIL,
            message=(
                f"Unclean exit(s) detected on {obj.name} during the check "
                f"window [{window_start:.0f}, {window_end:.0f}]:\n" + "\n".join(lines)
            ),
        )
