# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe
"""Trigger -> HC-expectation SIMULATION tests for the FPF disruption configs.

Behaviour-level validation distinct from the structural config-build tests in
``testconfigs/fpf/tests``: for each disruption TRIGGER (tc28, tc29, tc36, tc37,
tc38) these tests feed the health checks the collector data the trigger would
ACTUALLY produce, then assert the documented PASS/FAIL verdict.

Mocking pattern follows the canonical ``test_fpf_hrt_session_stat_health_check``
/ ``test_fpf_host_spray_health_check`` tests:
  - ``get_collector`` is patched to a synthetic collector,
  - ``async_query_ods`` is patched for the ODS-backed checks,
  - the network-bound ``everpaste_details_suffix`` / ``async_get_fburl*`` helpers
    are patched to no-ops.

Cases already covered elsewhere (and therefore NOT duplicated here) are noted in
the per-class docstrings:
  - tc28/tc29 session-stat 32->28->recover PASS + never-recover FAIL: covered by
    ``test_fpf_fsdb_disruption_session_stat.TestFpfFsdbDisruptionSessionStat``.
  - tc30 stable@28 PASS + climb-back-to-32 FAIL: same file.
  - generic-ods informational discard breach -> PASS: covered by
    ``test_generic_ods_health_check.test_informational_breach_reports_pass``.
The genuinely-missing simulations are added below.
"""

import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from taac.constants import TestDevice
from taac.health_checks.device_health_checks.fpf_hrt_bulk_convergence_health_check import (
    FpfHrtBulkConvergenceHealthCheck,
)
from taac.health_checks.device_health_checks.fpf_hrt_remote_failure_convergence_health_check import (
    FpfHrtRemoteFailureConvergenceHealthCheck,
)
from taac.health_checks.device_health_checks.fpf_hrt_session_stat_health_check import (
    FpfHrtSessionStatHealthCheck,
)
from taac.health_checks.device_health_checks.fpf_prod_hrt_prefix_stability_health_check import (
    FpfProdHrtPrefixStabilityHealthCheck,
)
from taac.health_checks.device_health_checks.generic_ods_health_check import (
    GenericOdsHealthCheck,
)
from taac.libs.fpf.fpf_prod_hrt_prefix import PrefixReachability
from taac.libs.fpf.fpf_stress_checks import (
    FsdbSessionWindowResult,
    HrtBulkRow,
    PerLaneResult,
    ProdHrtPrefixRow,
)
from taac.health_check.health_check import types as hc_types

SESSION_MODULE = (
    "neteng.test_infra.dne.taac.health_checks.device_health_checks"
    ".fpf_hrt_session_stat_health_check"
)
BULK_MODULE = (
    "neteng.test_infra.dne.taac.health_checks.device_health_checks"
    ".fpf_hrt_bulk_convergence_health_check"
)
REMOTE_MODULE = (
    "neteng.test_infra.dne.taac.health_checks.device_health_checks"
    ".fpf_hrt_remote_failure_convergence_health_check"
)
PROD_MODULE = (
    "neteng.test_infra.dne.taac.health_checks.device_health_checks"
    ".fpf_prod_hrt_prefix_stability_health_check"
)
ODS_MODULE = (
    "neteng.test_infra.dne.taac.health_checks.device_health_checks."
    "generic_ods_health_check"
)

GPU_HOST = "rtptest1555.mwg2"
PROD_PREFIX = "2401:db00:eef0:1100::/56"


def _ts_str(epoch: float) -> str:
    """Render an epoch as the collector's timestamp string (parseable by _parse_ts)."""
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S.%f"
    )[:-3] + datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%z")


# A fixed window the synthetic rows live inside.
WINDOW_START = 1_700_000_000.0
WINDOW_END = WINDOW_START + 300.0


# ---------------------------------------------------------------------------
# Session-stat helpers (mirror the canonical session-stat test)
# ---------------------------------------------------------------------------


def _make_session_collector(
    window_result: FsdbSessionWindowResult,
    recovery=(True, 90.0, "recovered to 32 and held for 90.0s (>= floor)"),
    timeout_count: int = 0,
) -> MagicMock:
    collector = MagicMock()
    collector.host = GPU_HOST
    collector.evaluate_window.return_value = window_result
    collector.evaluate_recovery_hold.return_value = recovery
    collector.timeout_count_in_window.return_value = timeout_count
    collector.format_window_table.return_value = "(table)"
    return collector


class _SessionStatBase(unittest.IsolatedAsyncioTestCase):
    """Shared setup/run helper for the session-stat-driven triggers."""

    def setUp(self):
        self.health_check = FpfHrtSessionStatHealthCheck(logger=MagicMock())
        self.device = MagicMock(spec=TestDevice)
        self.device.name = "gtsw001.l1002.c087.mwg2"
        for target, kw in (
            (
                f"{SESSION_MODULE}.everpaste_details_suffix",
                {"new": AsyncMock(return_value="")},
            ),
            (f"{SESSION_MODULE}.disruption_inconclusive_skip", {"return_value": None}),
            (
                f"{SESSION_MODULE}.get_test_case_start_time",
                {"return_value": WINDOW_START},
            ),
        ):
            p = patch(target, **kw)
            self.addCleanup(p.stop)
            p.start()

    async def _run(self, collector, params):
        with patch(f"{SESSION_MODULE}.get_collector", return_value=collector):
            return await self.health_check._run(
                self.device, hc_types.BaseHealthCheckIn(), params
            )


# ---------------------------------------------------------------------------
# TC28 — FSDB kill (SIGKILL every 1s for 60s on gtsw001 -> lane 0 of all GPUs)
#   Session-stat disruption mode: 32 -> 28 during kill, recover to 32 held >=60s.
# ---------------------------------------------------------------------------


class Tc28FsdbKillSessionStatSimulationTest(_SessionStatBase):
    """tc28 FSDB kill -> session-stat (disruption mode).

    The 32->28->recover PASS and never-recover FAIL transitions already have
    direct coverage in ``test_fpf_fsdb_disruption_session_stat``. This class adds
    the gap the spec calls out explicitly: the **never-drops-below-32** variant
    (disruption ineffective) must FAIL on Signal 1, AND the exact tc28 params
    (expected_connected=32, _during=28, impacted_lanes=[0], recovery_min_sec=60).
    """

    TC28_PARAMS = {
        "mode": "disruption",
        "expected_connected": 32,
        "expected_connected_during": 28,
        "impacted_lanes": [0],
        "recovery_min_sec": 60,
    }

    async def test_tc28_drop_to_28_then_recover_pass(self):
        """All 4 GPUs lose lane 0: 32->28 with L0 churn, recover to 32 held 90s -> PASS."""
        res = FsdbSessionWindowResult(
            host=GPU_HOST,
            samples=40,
            error_samples=0,
            min_connected=28,
            max_connected=32,
            last_connected=32,
            reached_expected=True,
            impacted_lane_churn={0: True},
            detail="connected min=28 max=32 last=32",
        )
        result = await self._run(_make_session_collector(res), self.TC28_PARAMS)
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)

    async def test_tc28_never_returns_to_32_fail(self):
        """Census dropped to 28 with churn but never recovered to 32 -> FAIL (Signal2)."""
        res = FsdbSessionWindowResult(
            host=GPU_HOST,
            samples=40,
            error_samples=0,
            min_connected=28,
            max_connected=31,
            last_connected=28,
            reached_expected=False,
            impacted_lane_churn={0: True},
            detail="connected min=28 max=31 last=28",
        )
        collector = _make_session_collector(
            res,
            recovery=(
                False,
                0.0,
                "did not recover by window end (last=28, expected 32)",
            ),
        )
        result = await self._run(collector, self.TC28_PARAMS)
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("Signal2", result.message)

    async def test_tc28_never_drops_below_32_fail(self):
        """The kill never took effect: stayed at 32, no L0 churn -> FAIL (Signal1)."""
        res = FsdbSessionWindowResult(
            host=GPU_HOST,
            samples=40,
            error_samples=0,
            min_connected=32,
            max_connected=32,
            last_connected=32,
            reached_expected=True,
            impacted_lane_churn={0: False},
            detail="connected min=32 max=32 last=32",
        )
        result = await self._run(_make_session_collector(res), self.TC28_PARAMS)
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("Signal1", result.message)


# ---------------------------------------------------------------------------
# TC29 — FSDB stop 30s / re-enable (within GR grace window)
#   (a) session-stat disruption: brief 32->28 drop + recover (hold >=30s) -> PASS.
#   (b) host-spray all_samples: a transient dip below floor during the 30s stop
#       FAILs in all_samples mode but PASSes in default latest-only mode.
# ---------------------------------------------------------------------------


class Tc29FsdbStop30SessionStatSimulationTest(_SessionStatBase):
    """tc29 FSDB stop30-reenable -> session-stat disruption (recovery_min_sec=30)."""

    async def test_tc29_brief_drop_then_recover_pass(self):
        """32->28 for the ~30s stop, recovers to 32 and holds >=30s -> PASS."""
        res = FsdbSessionWindowResult(
            host=GPU_HOST,
            samples=50,
            error_samples=0,
            min_connected=28,
            max_connected=32,
            last_connected=32,
            reached_expected=True,
            impacted_lane_churn={0: True},
            detail="connected min=28 max=32 last=32",
        )
        collector = _make_session_collector(
            res,
            recovery=(True, 40.0, "recovered to 32 and held for 40.0s (>= 30s floor)"),
        )
        result = await self._run(
            collector,
            {
                "mode": "disruption",
                "expected_connected": 32,
                "expected_connected_during": 28,
                "impacted_lanes": [0],
                "recovery_min_sec": 30,
            },
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)


def _spray_key(lane: int) -> str:
    return f"system.beth{lane}.tx-bytes-phy.rate"


class Tc29HostSprayAllSamplesSimulationTest(unittest.IsolatedAsyncioTestCase):
    """tc29 host-spray all_samples=True -> a per-sample dip during the 30s stop.

    The data plane should stay clean (GR holds forwarding), but the contract the
    config asserts is the per-sample sustained floor: if ANY sample on ANY beth
    dips below the floor, all_samples mode must FAIL — while the default
    latest-only mode would PASS (it only reads the recovered final sample). This
    proves all_samples catches the transient the latest-only mode misses.
    """

    HOST_A = "rtptest1555.mwg2"
    HOST_B = "rtptest1575.mwg2"

    def setUp(self):
        from taac.health_checks.device_health_checks.fpf_host_spray_health_check import (
            FpfHostSprayHealthCheck,
        )

        self._module = (
            "neteng.test_infra.dne.taac.health_checks.device_health_checks"
            ".fpf_host_spray_health_check"
        )
        self.health_check = FpfHostSprayHealthCheck(logger=MagicMock())
        self.device = MagicMock(spec=TestDevice)
        self.device.name = "gtsw001.l1002.c087.mwg2"

    async def _run(self, ods_data, params):
        with (
            patch(
                f"{self._module}.async_query_ods",
                new=AsyncMock(return_value=ods_data),
            ),
            patch(
                f"{self._module}.async_generate_ods_url",
                new=AsyncMock(return_value="raw_url"),
            ),
            patch(
                f"{self._module}.async_get_fburl",
                new=AsyncMock(return_value="https://fburl"),
            ),
            patch(
                f"{self._module}.get_test_case_start_time",
                new=MagicMock(return_value=0.0),
            ),
            patch(
                f"{self._module}.get_allow_baseline_failures",
                new=MagicMock(return_value=False),
            ),
        ):
            return await self.health_check._run(
                self.device, hc_types.BaseHealthCheckIn(), params
            )

    def _series_with_dip(self) -> dict:
        # beth0 dips to 2.0 at the MIDDLE sample (the 30s stop) then recovers.
        return {
            self.HOST_A: {
                _spray_key(0): {1000: 98.0, 2000: 2.0, 3000: 98.0},
                _spray_key(1): {1000: 98.0, 2000: 98.5, 3000: 98.2},
                _spray_key(2): {1000: 98.0, 2000: 99.0, 3000: 98.1},
                _spray_key(3): {1000: 98.0, 2000: 98.2, 3000: 98.3},
            },
            self.HOST_B: {
                _spray_key(0): {1000: 97.0, 2000: 97.4, 3000: 97.2},
                _spray_key(1): {1000: 97.2, 2000: 97.6, 3000: 97.1},
                _spray_key(2): {1000: 97.1, 2000: 97.5, 3000: 97.3},
                _spray_key(3): {1000: 97.3, 2000: 97.7, 3000: 97.0},
            },
        }

    async def test_tc29_all_samples_catches_transient_dip_fail(self):
        """all_samples=True FAILS on the mid-window dip during the 30s stop."""
        result = await self._run(
            self._series_with_dip(),
            {"hosts": [self.HOST_A, self.HOST_B], "all_samples": True},
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)

    async def test_tc29_default_latest_mode_misses_transient_pass(self):
        """Default (latest-only) mode reads only the recovered final sample -> PASS."""
        result = await self._run(
            self._series_with_dip(),
            {"hosts": [self.HOST_A, self.HOST_B]},
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)


# ---------------------------------------------------------------------------
# TC36 / TC37 — link events: the impacted lane's VF prefixes are ABSENT from the
#   bulk + prod collectors but PRESENT in the remote-failure collector.
# ---------------------------------------------------------------------------


def _make_remote_collector(per_lane_results, timeout_count: int = 0) -> MagicMock:
    collector = MagicMock()
    collector.host = GPU_HOST
    collector.evaluate_per_lane_window.return_value = per_lane_results
    collector.timeout_count_in_window.return_value = timeout_count
    collector.format_window_table.return_value = "(table)"
    return collector


def _make_bulk_collector(per_lane_results, withdrawn_rows, timeout_count: int = 0):
    collector = MagicMock()
    collector.host = GPU_HOST
    collector.evaluate_per_lane_window.return_value = per_lane_results
    collector.get_rows_in_window.return_value = withdrawn_rows
    collector.timeout_count_in_window.return_value = timeout_count
    collector.format_window_table.return_value = "(table)"
    return collector


class _LinkEventBase(unittest.IsolatedAsyncioTestCase):
    def _patch(self, module, **extra):
        patchers = [
            patch(f"{module}.everpaste_details_suffix", new=AsyncMock(return_value="")),
            patch(f"{module}.disruption_inconclusive_skip", return_value=None),
            patch(f"{module}.get_test_case_start_time", return_value=WINDOW_START),
        ]
        for p in patchers:
            self.addCleanup(p.stop)
            p.start()


class Tc36Tc37RemoteFailureSimulationTest(_LinkEventBase):
    """tc36/tc37 -> remote-failure convergence: the impacted lane shows the
    negative-route rise (0->prefix_count) on the impacted host -> PASS; if the
    impacted lane does NOT rise (stays 0), the drain assertion FAILs."""

    def setUp(self):
        self._patch(REMOTE_MODULE)
        self.health_check = FpfHrtRemoteFailureConvergenceHealthCheck(
            logger=MagicMock()
        )
        self.device = MagicMock(spec=TestDevice)
        self.device.name = "gtsw001.l1002.c087.mwg2"

    async def _run(self, collector, params):
        with patch(f"{REMOTE_MODULE}.get_collector", return_value=collector):
            return await self.health_check._run(
                self.device, hc_types.BaseHealthCheckIn(), params
            )

    def _params(self):
        return {
            "use_live_collectors": True,
            "lanes": [0],
            "expected_per_lane": {0: 1000},
            "direction": "drain",
            "only_hosts": [GPU_HOST],
        }

    async def test_impacted_lane_appears_in_remote_failure_pass(self):
        """Impacted lane 0 rises 0->1000 in the remote-failure view -> PASS."""
        per_lane = [
            PerLaneResult(
                lane=0,
                device="HRT neg L0",
                check_type="HRT remote_failure drain",
                passed=True,
                expected=1000,
                actual=1000,
                convergence_sec=5.0,
                detail="0->1000 in 5.0s (SLA 120s)",
            )
        ]
        result = await self._run(_make_remote_collector(per_lane), self._params())
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)

    async def test_impacted_lane_never_rises_fail(self):
        """Impacted lane 0 never shows the negative route (stays 0) -> FAIL."""
        per_lane = [
            PerLaneResult(
                lane=0,
                device="HRT neg L0",
                check_type="HRT remote_failure drain",
                passed=False,
                expected=1000,
                actual=0,
                convergence_sec=None,
                detail="never reached 1000 (last=0)",
            )
        ]
        result = await self._run(_make_remote_collector(per_lane), self._params())
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)


class Tc36Tc37BulkWithdrawnSimulationTest(_LinkEventBase):
    """tc36/tc37 -> bulk convergence: the impacted lane is treated as
    EXPECTED-IMPACTED (``impacted_lanes=[0]``), so its withdrawal from the bulk
    view is the EXPECTED outcome -> the check PASSES (it is NOT failed). A
    regression on a non-impacted injected lane still FAILs."""

    def setUp(self):
        self._patch(BULK_MODULE)
        self.health_check = FpfHrtBulkConvergenceHealthCheck(logger=MagicMock())
        self.device = MagicMock(spec=TestDevice)
        self.device.name = "gtsw001.l1002.c087.mwg2"

    async def _run(self, collector, params):
        with patch(f"{BULK_MODULE}.get_collector", return_value=collector):
            return await self.health_check._run(
                self.device, hc_types.BaseHealthCheckIn(), params
            )

    def _withdrawn_row(self, lane0_count: int, lane1_count: int) -> HrtBulkRow:
        # A single latest in-window sample on (host, dev0). lane0 is the impacted
        # lane; lane1 is the surviving injected lane.
        counts = [0, 0, 0, 0, 0, 0, 0, 0]
        counts[0] = lane0_count
        counts[1] = lane1_count
        return HrtBulkRow(
            timestamp=_ts_str(WINDOW_START + 100.0),
            host=GPU_HOST,
            device_id=0,
            lane_counts=counts,
            unique=lane0_count + lane1_count,
        )

    async def test_impacted_lane_withdrawn_is_expected_pass(self):
        """Impacted lane 0 withdrawn (count 0) + lane 1 converged -> PASS (expected)."""
        normal_lane1 = [
            PerLaneResult(
                lane=1,
                device="HRT L1",
                check_type="HRT bulk",
                passed=True,
                expected=1000,
                actual=1000,
                convergence_sec=10.0,
                detail="reached 1000 in 10.0s",
                signal1_e2e_sec=10.0,
                signal2_local_sec=2.0,
                signal3_stability_duration_sec=60.0,
            )
        ]
        collector = _make_bulk_collector(
            normal_lane1, [self._withdrawn_row(lane0_count=0, lane1_count=1000)]
        )
        result = await self._run(
            collector,
            {
                "use_live_collectors": True,
                "lanes": [0, 1],
                "expected_per_lane": {0: 1000, 1: 1000},
                "impacted_lanes": [0],
                "withdrawn_max_count": 0,
                "only_hosts": [GPU_HOST],
            },
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)

    async def test_impacted_lane_not_withdrawn_fail(self):
        """If the impacted lane 0 still carries prefixes (not withdrawn) -> FAIL."""
        normal_lane1 = [
            PerLaneResult(
                lane=1,
                device="HRT L1",
                check_type="HRT bulk",
                passed=True,
                expected=1000,
                actual=1000,
                convergence_sec=10.0,
                detail="reached 1000 in 10.0s",
                signal1_e2e_sec=10.0,
                signal2_local_sec=2.0,
                signal3_stability_duration_sec=60.0,
            )
        ]
        collector = _make_bulk_collector(
            normal_lane1, [self._withdrawn_row(lane0_count=1000, lane1_count=1000)]
        )
        result = await self._run(
            collector,
            {
                "use_live_collectors": True,
                "lanes": [0, 1],
                "expected_per_lane": {0: 1000, 1: 1000},
                "impacted_lanes": [0],
                "withdrawn_max_count": 0,
                "only_hosts": [GPU_HOST],
            },
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)


def _prefix_row(epoch: float, reachable, drained, unreachable) -> ProdHrtPrefixRow:
    rb = PrefixReachability(
        reachable_planes=list(reachable),
        drained_planes=list(drained),
        unreachable_planes=list(unreachable),
        plane_up=[0, 1, 2, 3, 4, 5, 6, 7],
        plane_down=[],
        device_ids=[0],
    )
    return ProdHrtPrefixRow(
        timestamp=_ts_str(epoch), host=GPU_HOST, prefixes={PROD_PREFIX: rb}
    )


class Tc36Tc37ProdPrefixTransitionSimulationTest(unittest.IsolatedAsyncioTestCase):
    """tc36/tc37 -> prod-prefix stability in transition mode: the impacted plane
    (0) goes reachable->unreachable within the SLA on the impacted host -> PASS;
    a plane that never leaves reachable (disable did not take) -> FAIL."""

    def setUp(self):
        self.health_check = FpfProdHrtPrefixStabilityHealthCheck(logger=MagicMock())
        self.device = MagicMock(spec=TestDevice)
        self.device.name = "gtsw001.l1002.c087.mwg2"
        for target, kw in (
            (
                f"{PROD_MODULE}.everpaste_details_suffix",
                {"new": AsyncMock(return_value="")},
            ),
            (f"{PROD_MODULE}.disruption_inconclusive_skip", {"return_value": None}),
            (f"{PROD_MODULE}.get_test_case_start_time", {"return_value": WINDOW_START}),
            (f"{PROD_MODULE}.get_disruption_time", {"return_value": 0.0}),
        ):
            p = patch(target, **kw)
            self.addCleanup(p.stop)
            p.start()

    async def _run(self, collector, params):
        with patch(
            f"{PROD_MODULE}.discover_prod_collectors",
            return_value=[(GPU_HOST, collector)],
        ):
            return await self.health_check._run(
                self.device, hc_types.BaseHealthCheckIn(), params
            )

    def _make_collector(self, rows) -> MagicMock:
        collector = MagicMock()
        collector.host = GPU_HOST
        collector.get_rows_in_window.return_value = rows
        collector.timeout_count_in_window.return_value = 0
        collector.format_window_table.return_value = "(table)"
        return collector

    def _params(self):
        return {
            "mode": "transition",
            "window_start": WINDOW_START,
            "window_end": WINDOW_END,
            "prefixes": [PROD_PREFIX],
            "impacted_planes_by_host": {GPU_HOST: [0]},
            "max_transition_sec": 30.0,
            "disruption_ts": WINDOW_START + 10.0,
        }

    async def test_impacted_plane_goes_unreachable_pass(self):
        """Plane 0 reachable at baseline, then unreachable within SLA -> PASS."""
        rows = [
            _prefix_row(WINDOW_START + 5.0, [0, 1, 2, 3], [], [4, 5, 6, 7]),
            _prefix_row(WINDOW_START + 20.0, [1, 2, 3], [], [0, 4, 5, 6, 7]),
            _prefix_row(WINDOW_START + 200.0, [1, 2, 3], [], [0, 4, 5, 6, 7]),
        ]
        result = await self._run(self._make_collector(rows), self._params())
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)

    async def test_impacted_plane_never_leaves_reachable_fail(self):
        """Plane 0 stays reachable across the whole window (disable did not take) -> FAIL."""
        rows = [
            _prefix_row(WINDOW_START + 5.0, [0, 1, 2, 3], [], [4, 5, 6, 7]),
            _prefix_row(WINDOW_START + 20.0, [0, 1, 2, 3], [], [4, 5, 6, 7]),
            _prefix_row(WINDOW_START + 200.0, [0, 1, 2, 3], [], [4, 5, 6, 7]),
        ]
        result = await self._run(self._make_collector(rows), self._params())
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)


class Tc36DiscardsCongestionSimulationTest(unittest.IsolatedAsyncioTestCase):
    """tc36 ODS contract: a DISCARD breach is INFORMATIONAL (PASS with
    [INFORMATIONAL]), but a CONGESTION breach (informational=False) still FAILs.

    The informational-PASS direction is already covered by
    ``test_generic_ods_health_check.test_informational_breach_reports_pass``;
    this adds the congestion-still-fails counterpart on the same aggregate=max
    "assert a transient breach happened" path the link-event playbook uses.
    """

    def setUp(self):
        self.check = GenericOdsHealthCheck(logger=MagicMock())
        self.device = MagicMock(spec=TestDevice)
        self.device.name = "dev1"

    async def _run(self, ods_data, params):
        with (
            patch(
                f"{ODS_MODULE}.async_query_ods", new=AsyncMock(return_value=ods_data)
            ),
            patch(
                f"{ODS_MODULE}.async_generate_ods_url",
                new=AsyncMock(return_value="https://ods/raw"),
            ),
            patch(
                f"{ODS_MODULE}.async_get_fburl_retry",
                new=AsyncMock(return_value="https://fburl.com/x"),
            ),
        ):
            return await self.check._run(
                self.device, hc_types.BaseHealthCheckIn(), params
            )

    async def test_discard_breach_informational_pass(self):
        """A discard breach with informational=True -> PASS with [INFORMATIONAL].

        The discard check carries a hard ceiling (``< 100``); the measured peak
        of 5000 breaches it, but informational=True surfaces the breach as a
        PASS-with-[INFORMATIONAL] instead of a FAIL.
        """
        ods_data = {"dev1": {"fboss.in_discards.rate": {"100": 5000.0}}}
        params = {
            "key_desc": "fboss.in_discards.rate",
            "sleep_timer": 0,
            "validation_expr": "< 100",
            "informational": True,
        }
        result = await self._run(ods_data, params)
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)
        self.assertIn("[INFORMATIONAL]", result.message or "")

    async def test_congestion_breach_still_fails(self):
        """A congestion breach with informational=False (hard) still -> FAIL.

        Hard threshold ``< 100`` over a measured peak of 5000 -> per-sample
        violation path FAILs (the two CONGESTION checks stay hard in tc36).
        """
        ods_data = {"dev1": {"fboss.pg_congestion.rate": {"100": 5000.0}}}
        params = {
            "key_desc": "fboss.pg_congestion.rate",
            "sleep_timer": 0,
            "validation_expr": "< 100",
            "informational": False,
        }
        result = await self._run(ods_data, params)
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)


# ---------------------------------------------------------------------------
# TC37 — NIC flap (mstreg PAOS flap dev0/lane1 -> lane-0 churn + recover)
#   session-stat disruption: lane-0 churn during the flap then recovery -> PASS;
#   FAIL if the impacted lane does NOT show the expected churn.
# ---------------------------------------------------------------------------


class Tc37NicFlapSessionStatSimulationTest(_SessionStatBase):
    """tc37 NIC flap -> session-stat disruption (flip_fsdb_session=True)."""

    PARAMS = {
        "mode": "disruption",
        "expected_connected": 32,
        "expected_connected_during": 28,
        "impacted_lanes": [0],
        "recovery_min_sec": 30,
    }

    async def test_tc37_lane0_churn_and_recover_pass(self):
        """NIC flap churns lane 0 (32->28), recovers to 32 held -> PASS."""
        res = FsdbSessionWindowResult(
            host=GPU_HOST,
            samples=60,
            error_samples=0,
            min_connected=28,
            max_connected=32,
            last_connected=32,
            reached_expected=True,
            impacted_lane_churn={0: True},
            detail="connected min=28 max=32 last=32",
        )
        collector = _make_session_collector(
            res,
            recovery=(True, 50.0, "recovered to 32 and held for 50.0s (>= 30s floor)"),
        )
        result = await self._run(collector, self.PARAMS)
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)

    async def test_tc37_no_lane0_churn_fail(self):
        """If lane 0 shows NO churn during the flap -> FAIL (Signal1 churn)."""
        res = FsdbSessionWindowResult(
            host=GPU_HOST,
            samples=60,
            error_samples=0,
            min_connected=32,
            max_connected=32,
            last_connected=32,
            reached_expected=True,
            impacted_lane_churn={0: False},
            detail="connected min=32 max=32 last=32",
        )
        result = await self._run(_make_session_collector(res), self.PARAMS)
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("Signal1", result.message)


# ---------------------------------------------------------------------------
# TC38 — persistent NDP clear (provisional stable-state)
#   session-stat stable mode: steady 32 -> PASS. Kept minimal (provisional).
# ---------------------------------------------------------------------------


class Tc38NdpClearSessionStatSimulationTest(_SessionStatBase):
    """tc38 NDP clear -> session-stat STABLE mode steady at 32 -> PASS (provisional)."""

    async def test_tc38_steady_32_stable_pass(self):
        res = FsdbSessionWindowResult(
            host=GPU_HOST,
            samples=50,
            error_samples=0,
            min_connected=32,
            max_connected=32,
            last_connected=32,
            reached_expected=True,
            detail="connected min=32 max=32 last=32",
        )
        result = await self._run(
            _make_session_collector(res),
            {"mode": "stable", "expected_connected": 32},
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)


if __name__ == "__main__":
    unittest.main()
