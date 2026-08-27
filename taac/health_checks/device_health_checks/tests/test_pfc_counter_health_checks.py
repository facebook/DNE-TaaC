# Copyright (c) Meta Platforms, Inc. and affiliates.

from unittest.mock import AsyncMock, MagicMock, patch

from later.unittest import TestCase
from taac.constants import TestDevice
from taac.health_checks.device_health_checks.clear_counters_health_check import (
    ClearCountersHealthCheck,
)
from taac.health_checks.device_health_checks.pfc_wd_health_check import (
    PfcWdHealthCheck,
)
from taac.health_checks.device_health_checks.port_counters_health_check import (
    PortCountersHealthCheck,
)
from taac.health_checks.dsf_health_checks.dsf_pfc_health_check import (
    DsfPfcHealthCheck,
)
from taac.utils.health_check_utils import (
    is_same_device,
    normalize_device_name,
)
from taac.utils.oss_taac_lib_utils import ConsoleFileLogger
from taac.health_check.health_check import types as hc_types


def _make_device(name: str = "gtsw001.example", os: str = "FBOSS") -> TestDevice:
    device = MagicMock(spec=TestDevice)
    device.name = name
    device.attributes = MagicMock()
    device.attributes.operating_system = os
    device.attributes.role = "GTSW"
    return device


class TestPfcCounterHealthChecks(TestCase):
    def setUp(self) -> None:
        self.logger = MagicMock(spec=ConsoleFileLogger)
        DsfPfcHealthCheck._snapshots.clear()
        DsfPfcHealthCheck._snapshot_created_at.clear()
        PfcWdHealthCheck._snapshots.clear()
        PfcWdHealthCheck._snapshot_created_at.clear()

    @staticmethod
    def _wd_key(
        interface: str = "eth1/1/1", snapshot_id: str = "legacy"
    ) -> tuple[str, str, str]:
        return (snapshot_id, "gtsw001.example", interface)

    @staticmethod
    def _dsf_key(snapshot_id: str = "legacy") -> tuple[str, str, str, int]:
        return (
            snapshot_id,
            "gtsw001.example",
            "eth1/1/1",
            int(hc_types.Priority.PRIORITY_2),
        )

    def _pfc_wd_input(
        self,
        *,
        deadlock_threshold: int = 0,
        recovery_threshold: int = 0,
        comparison: hc_types.ComparisonType = hc_types.ComparisonType.GREATER_THAN,
    ) -> hc_types.PfcWdHealthCheckIn:
        return hc_types.PfcWdHealthCheckIn(
            thresholds=[
                hc_types.PfcWdThreshold(
                    interfaces=["gtsw001.example:eth1/1/1"],
                    deadlock_threshold=deadlock_threshold,
                    recovery_threshold=recovery_threshold,
                    comparison=comparison,
                )
            ]
        )

    @patch(
        "neteng.test_infra.dne.taac.health_checks.device_health_checks."
        "pfc_wd_health_check.time.monotonic",
        return_value=100_000,
    )
    def test_pfc_wd_prunes_only_expired_snapshots(
        self, _mock_monotonic: MagicMock
    ) -> None:
        stale_key = self._wd_key(snapshot_id="stale-run")
        live_key = self._wd_key(snapshot_id="live-run")
        PfcWdHealthCheck._snapshots[stale_key] = (1, 1)
        PfcWdHealthCheck._snapshots[live_key] = (2, 2)
        PfcWdHealthCheck._snapshot_created_at[stale_key] = (
            100_000 - PfcWdHealthCheck._SNAPSHOT_TTL_SECONDS - 1
        )
        PfcWdHealthCheck._snapshot_created_at[live_key] = 100_000

        PfcWdHealthCheck._prune_expired_snapshots()

        self.assertNotIn(stale_key, PfcWdHealthCheck._snapshots)
        self.assertIn(live_key, PfcWdHealthCheck._snapshots)

    async def test_pfc_wd_unsupported_mode_is_configuration_error(self) -> None:
        result = await PfcWdHealthCheck(logger=self.logger)._run(
            _make_device(), self._pfc_wd_input(), {"mode": "unsupported"}
        )

        self.assertEqual(hc_types.HealthCheckStatus.ERROR, result.status)

    async def test_pfc_wd_invalid_max_difference_is_configuration_error(
        self,
    ) -> None:
        result = await PfcWdHealthCheck(logger=self.logger)._run(
            _make_device(),
            self._pfc_wd_input(),
            {"mode": "check", "max_detection_recovery_difference": -1},
        )

        self.assertEqual(hc_types.HealthCheckStatus.ERROR, result.status)

    @patch(
        "neteng.test_infra.dne.taac.health_checks.device_health_checks."
        "pfc_wd_health_check.get_fb303_client",
        new_callable=AsyncMock,
    )
    async def test_pfc_wd_snapshot_keeps_max_monotonic_sample(
        self, mock_get_client: AsyncMock
    ) -> None:
        client = AsyncMock()
        client.getSelectedCounters.side_effect = [
            {
                "eth1/1/1.pfc_deadlock_detection.sum": 10,
                "eth1/1/1.pfc_deadlock_recovery.sum": 9,
            },
            {
                "eth1/1/1.pfc_deadlock_detection.sum": 0,
                "eth1/1/1.pfc_deadlock_recovery.sum": 0,
            },
            {
                "eth1/1/1.pfc_deadlock_detection.sum": 11,
                "eth1/1/1.pfc_deadlock_recovery.sum": 10,
            },
        ]
        mock_get_client.return_value.__aenter__.return_value = client
        check = PfcWdHealthCheck(logger=self.logger)

        result = await check._run(
            _make_device(), self._pfc_wd_input(), {"mode": "snapshot"}
        )

        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status)
        self.assertEqual(
            (11, 10),
            PfcWdHealthCheck._snapshots[self._wd_key()],
        )

    @patch(
        "neteng.test_infra.dne.taac.health_checks.device_health_checks."
        "pfc_wd_health_check.get_fb303_client",
        new_callable=AsyncMock,
    )
    async def test_pfc_wd_repeat_snapshot_keeps_existing_high_watermark(
        self, mock_get_client: AsyncMock
    ) -> None:
        key = self._wd_key(snapshot_id="current-run")
        PfcWdHealthCheck._snapshots[key] = (12, 11)
        client = AsyncMock()
        client.getSelectedCounters.return_value = {
            "eth1/1/1.pfc_deadlock_detection.sum": 10,
            "eth1/1/1.pfc_deadlock_recovery.sum": 9,
        }
        mock_get_client.return_value.__aenter__.return_value = client
        check = PfcWdHealthCheck(logger=self.logger)

        result = await check._run(
            _make_device(),
            self._pfc_wd_input(),
            {"mode": "snapshot", "snapshot_id": "current-run"},
        )

        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status)
        self.assertEqual((12, 11), PfcWdHealthCheck._snapshots[key])

    @patch(
        "neteng.test_infra.dne.taac.health_checks.device_health_checks."
        "pfc_wd_health_check.get_fb303_client",
        new_callable=AsyncMock,
    )
    async def test_pfc_wd_replace_snapshot_overwrites_same_run_baseline(
        self, mock_get_client: AsyncMock
    ) -> None:
        key = self._wd_key(snapshot_id="current-run")
        PfcWdHealthCheck._snapshots[key] = (12, 11)
        client = AsyncMock()
        client.getSelectedCounters.return_value = {
            "eth1/1/1.pfc_deadlock_detection.sum": 3,
            "eth1/1/1.pfc_deadlock_recovery.sum": 2,
        }
        mock_get_client.return_value.__aenter__.return_value = client

        result = await PfcWdHealthCheck(logger=self.logger)._run(
            _make_device(),
            self._pfc_wd_input(),
            {
                "mode": "snapshot",
                "snapshot_id": "current-run",
                "replace_snapshot": True,
            },
        )

        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status)
        self.assertEqual((3, 2), PfcWdHealthCheck._snapshots[key])

    @patch(
        "neteng.test_infra.dne.taac.health_checks.device_health_checks."
        "pfc_wd_health_check.get_fb303_client",
        new_callable=AsyncMock,
    )
    async def test_failed_snapshot_preserves_other_run_baseline(
        self, mock_get_client: AsyncMock
    ) -> None:
        stale_key = self._wd_key(snapshot_id="prior-run")
        current_key = self._wd_key(snapshot_id="current-run")
        PfcWdHealthCheck._snapshots[stale_key] = (999, 999)
        mock_get_client.side_effect = RuntimeError("fetch failed")
        check = PfcWdHealthCheck(logger=self.logger)

        result = await check._run(
            _make_device(),
            self._pfc_wd_input(),
            {"mode": "snapshot", "snapshot_id": "current-run"},
        )

        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertEqual((999, 999), PfcWdHealthCheck._snapshots[stale_key])
        self.assertNotIn(current_key, PfcWdHealthCheck._snapshots)

    @patch(
        "neteng.test_infra.dne.taac.health_checks.device_health_checks."
        "pfc_wd_health_check.asyncio.sleep",
        new_callable=AsyncMock,
    )
    @patch(
        "neteng.test_infra.dne.taac.health_checks.device_health_checks."
        "pfc_wd_health_check.get_fb303_client",
        new_callable=AsyncMock,
    )
    async def test_pfc_wd_snapshot_accepts_zero_baseline_without_retry(
        self, mock_get_client: AsyncMock, mock_sleep: AsyncMock
    ) -> None:
        client = AsyncMock()
        zero = {
            "eth1/1/1.pfc_deadlock_detection.sum": 0,
            "eth1/1/1.pfc_deadlock_recovery.sum": 0,
        }
        client.getSelectedCounters.return_value = zero
        mock_get_client.return_value.__aenter__.return_value = client
        check = PfcWdHealthCheck(logger=self.logger)

        result = await check._run(
            _make_device(), self._pfc_wd_input(), {"mode": "snapshot"}
        )

        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status)
        self.assertEqual(
            (0, 0),
            PfcWdHealthCheck._snapshots[self._wd_key()],
        )
        self.assertEqual(3, client.getSelectedCounters.await_count)
        mock_sleep.assert_not_awaited()
        self.logger.warning.assert_not_called()

    @patch(
        "neteng.test_infra.dne.taac.health_checks.device_health_checks."
        "pfc_wd_health_check.asyncio.sleep",
        new_callable=AsyncMock,
    )
    @patch(
        "neteng.test_infra.dne.taac.health_checks.device_health_checks."
        "pfc_wd_health_check.get_fb303_client",
        new_callable=AsyncMock,
    )
    async def test_pfc_wd_snapshot_retries_racy_zero_when_requested(
        self, mock_get_client: AsyncMock, mock_sleep: AsyncMock
    ) -> None:
        client = AsyncMock()
        zero = {
            "eth1/1/1.pfc_deadlock_detection.sum": 0,
            "eth1/1/1.pfc_deadlock_recovery.sum": 0,
        }
        nonzero = {
            "eth1/1/1.pfc_deadlock_detection.sum": 10,
            "eth1/1/1.pfc_deadlock_recovery.sum": 9,
        }
        client.getSelectedCounters.side_effect = [zero] * 3 + [nonzero] * 3
        mock_get_client.return_value.__aenter__.return_value = client

        result = await PfcWdHealthCheck(logger=self.logger)._run(
            _make_device(),
            self._pfc_wd_input(),
            {"mode": "snapshot", "snapshot_retry_on_zero": True},
        )

        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status)
        self.assertEqual((10, 9), PfcWdHealthCheck._snapshots[self._wd_key()])
        mock_sleep.assert_awaited_once_with(0.2)

    @patch(
        "neteng.test_infra.dne.taac.health_checks.device_health_checks."
        "pfc_wd_health_check.asyncio.sleep",
        new_callable=AsyncMock,
    )
    @patch(
        "neteng.test_infra.dne.taac.health_checks.device_health_checks."
        "pfc_wd_health_check.get_fb303_client",
        new_callable=AsyncMock,
    )
    async def test_pfc_wd_requires_both_counter_keys_in_each_attempt(
        self, mock_get_client: AsyncMock, mock_sleep: AsyncMock
    ) -> None:
        client = AsyncMock()
        both_zero = {
            "eth1/1/1.pfc_deadlock_detection.sum": 0,
            "eth1/1/1.pfc_deadlock_recovery.sum": 0,
        }
        detection_only = {"eth1/1/1.pfc_deadlock_detection.sum": 1}
        client.getSelectedCounters.side_effect = [both_zero] * 3 + [detection_only] * 12
        mock_get_client.return_value.__aenter__.return_value = client

        with self.assertRaisesRegex(RuntimeError, "counters missing"):
            await PfcWdHealthCheck(
                logger=self.logger
            )._get_fboss_monotonic_pfc_wd_counters(
                device="gtsw001.example",
                interface="eth1/1/1",
                baseline=(0, 0),
                retry_on_regression=False,
                retry_on_zero=True,
            )

        self.assertEqual(4, mock_sleep.await_count)

    @patch(
        "neteng.test_infra.dne.taac.health_checks.device_health_checks."
        "pfc_wd_health_check.get_fb303_client",
        new_callable=AsyncMock,
    )
    async def test_pfc_wd_snapshot_fails_when_counter_keys_are_missing(
        self, mock_get_client: AsyncMock
    ) -> None:
        client = AsyncMock()
        client.getSelectedCounters.return_value = {}
        mock_get_client.return_value.__aenter__.return_value = client

        result = await PfcWdHealthCheck(logger=self.logger)._run(
            _make_device(), self._pfc_wd_input(), {"mode": "snapshot"}
        )

        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("counters missing", result.message or "")
        self.assertNotIn(self._wd_key(), PfcWdHealthCheck._snapshots)

    async def test_pfc_wd_normalizes_known_fqdn_suffixes(self) -> None:
        self.assertEqual(
            "gtsw001.l1001.c085.ash6",
            normalize_device_name("GTSW001.L1001.C085.ASH6.facebook.com."),
        )
        self.assertEqual(
            "gtsw001.l1001.c085.ash6",
            normalize_device_name("gtsw001.l1001.c085.ash6.tfbnw.net"),
        )

    @patch(
        "neteng.test_infra.dne.taac.health_checks.device_health_checks."
        "pfc_wd_health_check.asyncio.sleep",
        new_callable=AsyncMock,
    )
    @patch(
        "neteng.test_infra.dne.taac.health_checks.device_health_checks."
        "pfc_wd_health_check.get_fb303_client",
        new_callable=AsyncMock,
    )
    async def test_pfc_wd_check_retries_regression_and_uses_deltas(
        self, mock_get_client: AsyncMock, mock_sleep: AsyncMock
    ) -> None:
        PfcWdHealthCheck._snapshots[self._wd_key()] = (100, 100)
        client = AsyncMock()
        below_baseline = {
            "eth1/1/1.pfc_deadlock_detection.sum": 0,
            "eth1/1/1.pfc_deadlock_recovery.sum": 0,
        }
        current = {
            "eth1/1/1.pfc_deadlock_detection.sum": 105,
            "eth1/1/1.pfc_deadlock_recovery.sum": 104,
        }
        client.getSelectedCounters.side_effect = [
            below_baseline,
            below_baseline,
            below_baseline,
            current,
            current,
            current,
        ]
        mock_get_client.return_value.__aenter__.return_value = client
        check = PfcWdHealthCheck(logger=self.logger)

        result = await check._run(
            _make_device(),
            self._pfc_wd_input(deadlock_threshold=4, recovery_threshold=3),
            {"mode": "check", "max_detection_recovery_difference": 1},
        )

        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status)
        mock_sleep.assert_awaited_once_with(0.2)
        self.assertNotIn(self._wd_key(), PfcWdHealthCheck._snapshots)

    @patch(
        "neteng.test_infra.dne.taac.health_checks.device_health_checks."
        "pfc_wd_health_check.asyncio.sleep",
        new_callable=AsyncMock,
    )
    @patch(
        "neteng.test_infra.dne.taac.health_checks.device_health_checks."
        "pfc_wd_health_check.get_fb303_client",
        new_callable=AsyncMock,
    )
    async def test_pfc_wd_check_fails_persistent_counter_regression(
        self, mock_get_client: AsyncMock, mock_sleep: AsyncMock
    ) -> None:
        key = self._wd_key()
        PfcWdHealthCheck._snapshots[key] = (100, 100)
        client = AsyncMock()
        client.getSelectedCounters.return_value = {
            "eth1/1/1.pfc_deadlock_detection.sum": 1,
            "eth1/1/1.pfc_deadlock_recovery.sum": 1,
        }
        mock_get_client.return_value.__aenter__.return_value = client
        check = PfcWdHealthCheck(logger=self.logger)

        result = await check._run(
            _make_device(), self._pfc_wd_input(), {"mode": "check"}
        )

        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("remained below the snapshot baseline", result.message or "")
        self.assertEqual(4, mock_sleep.await_count)
        self.assertIn(key, PfcWdHealthCheck._snapshots)

    @patch(
        "neteng.test_infra.dne.taac.health_checks.device_health_checks."
        "pfc_wd_health_check.async_everpaste_str",
        new_callable=AsyncMock,
    )
    @patch(
        "neteng.test_infra.dne.taac.health_checks.device_health_checks."
        "pfc_wd_health_check.get_fb303_client",
        new_callable=AsyncMock,
    )
    async def test_pfc_wd_check_rejects_excess_detection_recovery_difference(
        self, mock_get_client: AsyncMock, mock_everpaste: AsyncMock
    ) -> None:
        PfcWdHealthCheck._snapshots[self._wd_key()] = (100, 100)
        client = AsyncMock()
        client.getSelectedCounters.return_value = {
            "eth1/1/1.pfc_deadlock_detection.sum": 106,
            "eth1/1/1.pfc_deadlock_recovery.sum": 103,
        }
        mock_get_client.return_value.__aenter__.return_value = client
        mock_everpaste.return_value = "https://www.internalfb.com/intern/everpaste/test"
        check = PfcWdHealthCheck(logger=self.logger)

        result = await check._run(
            _make_device(),
            self._pfc_wd_input(),
            {"mode": "check", "max_detection_recovery_difference": 2},
        )

        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("difference 3 exceeds configured maximum 2", result.message or "")

    @patch(
        "neteng.test_infra.dne.taac.health_checks.device_health_checks."
        "pfc_wd_health_check.get_fb303_client",
        new_callable=AsyncMock,
    )
    async def test_pfc_wd_check_does_not_require_balance_without_limit(
        self, mock_get_client: AsyncMock
    ) -> None:
        key = self._wd_key()
        PfcWdHealthCheck._snapshots[key] = (100, 100)
        client = AsyncMock()
        client.getSelectedCounters.return_value = {
            "eth1/1/1.pfc_deadlock_detection.sum": 106,
            "eth1/1/1.pfc_deadlock_recovery.sum": 103,
        }
        mock_get_client.return_value.__aenter__.return_value = client
        check = PfcWdHealthCheck(logger=self.logger)

        result = await check._run(
            _make_device(),
            self._pfc_wd_input(deadlock_threshold=2, recovery_threshold=2),
            {"mode": "check"},
        )

        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status)
        self.assertNotIn(key, PfcWdHealthCheck._snapshots)

    @patch(
        "neteng.test_infra.dne.taac.health_checks.device_health_checks."
        "pfc_wd_health_check.async_everpaste_str",
        new_callable=AsyncMock,
    )
    @patch(
        "neteng.test_infra.dne.taac.health_checks.device_health_checks."
        "pfc_wd_health_check.get_fb303_client",
        new_callable=AsyncMock,
    )
    async def test_pfc_wd_thresholds_apply_to_snapshot_deltas(
        self, mock_get_client: AsyncMock, mock_everpaste: AsyncMock
    ) -> None:
        PfcWdHealthCheck._snapshots[self._wd_key()] = (1000, 1000)
        client = AsyncMock()
        client.getSelectedCounters.return_value = {
            "eth1/1/1.pfc_deadlock_detection.sum": 1002,
            "eth1/1/1.pfc_deadlock_recovery.sum": 1002,
        }
        mock_get_client.return_value.__aenter__.return_value = client
        mock_everpaste.return_value = "https://www.internalfb.com/intern/everpaste/test"
        check = PfcWdHealthCheck(logger=self.logger)

        result = await check._run(
            _make_device(),
            self._pfc_wd_input(deadlock_threshold=5, recovery_threshold=5),
            {"mode": "check", "max_detection_recovery_difference": 0},
        )

        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("Observed Deadlock: 2, Recovery: 2", result.message or "")

    @patch(
        "neteng.test_infra.dne.taac.health_checks.device_health_checks."
        "pfc_wd_health_check.get_fb303_client",
        new_callable=AsyncMock,
    )
    async def test_pfc_wd_check_reuses_snapshot_for_same_endpoint_thresholds(
        self, mock_get_client: AsyncMock
    ) -> None:
        key = self._wd_key()
        PfcWdHealthCheck._snapshots[key] = (100, 100)
        client = AsyncMock()
        client.getSelectedCounters.return_value = {
            "eth1/1/1.pfc_deadlock_detection.sum": 105,
            "eth1/1/1.pfc_deadlock_recovery.sum": 105,
        }
        mock_get_client.return_value.__aenter__.return_value = client
        threshold = hc_types.PfcWdThreshold(
            interfaces=["gtsw001.example:eth1/1/1"],
            deadlock_threshold=4,
            recovery_threshold=4,
            comparison=hc_types.ComparisonType.GREATER_THAN,
        )
        check = PfcWdHealthCheck(logger=self.logger)

        result = await check._run(
            _make_device(),
            hc_types.PfcWdHealthCheckIn(thresholds=[threshold, threshold]),
            {"mode": "check"},
        )

        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status)
        self.assertEqual(6, client.getSelectedCounters.await_count)
        self.assertNotIn(key, PfcWdHealthCheck._snapshots)

    @patch(
        "neteng.test_infra.dne.taac.health_checks.device_health_checks."
        "pfc_wd_health_check.async_everpaste_str",
        new_callable=AsyncMock,
    )
    @patch(
        "neteng.test_infra.dne.taac.health_checks.device_health_checks."
        "pfc_wd_health_check.get_fb303_client",
        new_callable=AsyncMock,
    )
    async def test_pfc_wd_failure_retains_all_selected_snapshots_for_retry(
        self, mock_get_client: AsyncMock, mock_everpaste: AsyncMock
    ) -> None:
        first_key = self._wd_key()
        second_key = self._wd_key(interface="eth1/2/1")
        PfcWdHealthCheck._snapshots[first_key] = (100, 100)
        PfcWdHealthCheck._snapshots[second_key] = (200, 200)
        client = AsyncMock()
        client.getSelectedCounters.return_value = {
            "eth1/1/1.pfc_deadlock_detection.sum": 101,
            "eth1/1/1.pfc_deadlock_recovery.sum": 101,
        }
        mock_get_client.return_value.__aenter__.return_value = client
        mock_everpaste.return_value = "https://www.internalfb.com/intern/everpaste/test"
        check = PfcWdHealthCheck(logger=self.logger)
        first_threshold = hc_types.PfcWdThreshold(
            interfaces=["gtsw001.example:eth1/1/1"],
            deadlock_threshold=5,
            recovery_threshold=5,
            comparison=hc_types.ComparisonType.GREATER_THAN,
        )
        second_threshold = hc_types.PfcWdThreshold(
            interfaces=["gtsw001.example:eth1/2/1"],
            deadlock_threshold=0,
            recovery_threshold=0,
            comparison=hc_types.ComparisonType.GREATER_THAN,
        )

        result = await check._run(
            _make_device(),
            hc_types.PfcWdHealthCheckIn(thresholds=[first_threshold, second_threshold]),
            {"mode": "check"},
        )

        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn(first_key, PfcWdHealthCheck._snapshots)
        self.assertIn(second_key, PfcWdHealthCheck._snapshots)

    @patch(
        "neteng.test_infra.dne.taac.health_checks.device_health_checks."
        "pfc_wd_health_check.get_fb303_client",
        new_callable=AsyncMock,
    )
    async def test_pfc_wd_framework_retry_reuses_then_consumes_snapshot(
        self, mock_get_client: AsyncMock
    ) -> None:
        snapshot_id = "test-run"
        key = self._wd_key(snapshot_id=snapshot_id)
        PfcWdHealthCheck._snapshots[key] = (100, 100)
        first = {
            "eth1/1/1.pfc_deadlock_detection.sum": 101,
            "eth1/1/1.pfc_deadlock_recovery.sum": 101,
        }
        second = {
            "eth1/1/1.pfc_deadlock_detection.sum": 110,
            "eth1/1/1.pfc_deadlock_recovery.sum": 110,
        }
        client = AsyncMock()
        client.getSelectedCounters.side_effect = [first] * 3 + [second] * 3
        mock_get_client.return_value.__aenter__.return_value = client
        check = PfcWdHealthCheck(logger=self.logger)
        check_input = self._pfc_wd_input(deadlock_threshold=5, recovery_threshold=5)

        result = await check.run(
            _make_device(),
            check_input,
            check_input,
            {
                "mode": "check",
                "snapshot_id": snapshot_id,
                "retry_count": 1,
                "retry_delay_seconds": 0,
            },
        )

        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status)
        self.assertEqual(6, client.getSelectedCounters.await_count)
        self.assertNotIn(key, PfcWdHealthCheck._snapshots)

    async def test_pfc_wd_check_uses_captured_baseline_after_concurrent_eviction(
        self,
    ) -> None:
        snapshot_id = "test-run"
        key = self._wd_key(snapshot_id=snapshot_id)
        PfcWdHealthCheck._snapshots[key] = (100, 100)
        check = PfcWdHealthCheck(logger=self.logger)

        async def fetch_and_evict(**_kwargs: object) -> tuple[int, int]:
            PfcWdHealthCheck._snapshots.pop(key)
            return (110, 110)

        with patch.object(
            check,
            "_get_fboss_monotonic_pfc_wd_counters",
            new_callable=AsyncMock,
            side_effect=fetch_and_evict,
        ):
            result = await check._run(
                _make_device(),
                self._pfc_wd_input(),
                {"mode": "check", "snapshot_id": snapshot_id},
            )

        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status)

    async def test_pfc_wd_check_requires_snapshot(self) -> None:
        check = PfcWdHealthCheck(logger=self.logger)
        PfcWdHealthCheck._snapshots[self._wd_key(snapshot_id="prior-run")] = (
            100,
            100,
        )

        result = await check._run(
            _make_device(),
            self._pfc_wd_input(),
            {"mode": "check", "snapshot_id": "current-run"},
        )

        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("requires a prior snapshot", result.message or "")

    async def test_pfc_wd_rejects_malformed_endpoint(self) -> None:
        result = await PfcWdHealthCheck(logger=self.logger)._run(
            _make_device(),
            hc_types.PfcWdHealthCheckIn(
                thresholds=[
                    hc_types.PfcWdThreshold(
                        interfaces=["missing-interface-separator"],
                        deadlock_threshold=0,
                        recovery_threshold=0,
                        comparison=hc_types.ComparisonType.EQUAL_TO,
                    )
                ]
            ),
            {"mode": "snapshot"},
        )

        self.assertEqual(hc_types.HealthCheckStatus.ERROR, result.status)
        self.assertIn("expected 'device:interface'", result.message or "")

    async def test_pfc_wd_supports_gtsw(self) -> None:
        check = PfcWdHealthCheck(logger=self.logger)

        should_skip, reason = await check.skip_check(_make_device())

        self.assertFalse(should_skip)
        self.assertIsNone(reason)

    async def test_pfc_wd_snapshot_mode_rejects_eos(self) -> None:
        result = await PfcWdHealthCheck(logger=self.logger)._run(
            _make_device(os="EOS"),
            self._pfc_wd_input(),
            {"mode": "snapshot"},
        )

        self.assertEqual(hc_types.HealthCheckStatus.ERROR, result.status)
        self.assertIn("requires FBOSS", result.message or "")

    @patch(
        "neteng.test_infra.dne.taac.health_checks.dsf_health_checks."
        "dsf_pfc_health_check.get_fb303_client",
        new_callable=AsyncMock,
    )
    async def test_dsf_pfc_snapshot_reads_remote_target_device(
        self, mock_get_client: AsyncMock
    ) -> None:
        client = AsyncMock()
        client.getSelectedCounters.return_value = {
            "eth1/1/1.out_pfc_frames.priority2.sum": 11,
            "eth1/1/1.in_pfc_frames.priority2.sum": 12,
        }
        mock_get_client.return_value.__aenter__.return_value = client
        threshold = hc_types.DsfPfcThreshold(
            interfaces=["gtsw002.example:eth1/1/1"],
            out_pfc=0,
            comparison=hc_types.ComparisonType.EQUAL_TO,
            priority=hc_types.Priority.PRIORITY_2,
        )
        check = DsfPfcHealthCheck(logger=self.logger)

        stale_key = (
            "prior-run",
            "gtsw002.example",
            "eth1/1/1",
            int(hc_types.Priority.PRIORITY_2),
        )
        key = (
            "current-run",
            "gtsw002.example",
            "eth1/1/1",
            int(hc_types.Priority.PRIORITY_2),
        )
        DsfPfcHealthCheck._snapshots[stale_key] = (999, 999)
        result = await check._run(
            _make_device(),
            hc_types.DsfPfcHealthCheckIn(thresholds=[threshold]),
            {
                "mode": "snapshot",
                "executor_device": "gtsw001.example",
                "replace_snapshot": True,
                "snapshot_id": "current-run",
            },
        )

        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status)
        mock_get_client.assert_awaited_once_with("gtsw002.example")
        self.assertEqual(
            (11, 12),
            DsfPfcHealthCheck._snapshots[key],
        )
        self.assertEqual((999, 999), DsfPfcHealthCheck._snapshots[stale_key])

    @patch(
        "neteng.test_infra.dne.taac.health_checks.dsf_health_checks."
        "dsf_pfc_health_check.time.monotonic",
        return_value=100_000,
    )
    def test_dsf_pfc_prunes_only_expired_snapshots(
        self, _mock_monotonic: MagicMock
    ) -> None:
        stale_key = self._dsf_key(snapshot_id="stale-run")
        live_key = self._dsf_key(snapshot_id="live-run")
        DsfPfcHealthCheck._snapshots[stale_key] = (1, 1)
        DsfPfcHealthCheck._snapshots[live_key] = (2, 2)
        DsfPfcHealthCheck._snapshot_created_at[stale_key] = (
            100_000 - DsfPfcHealthCheck._SNAPSHOT_TTL_SECONDS - 1
        )
        DsfPfcHealthCheck._snapshot_created_at[live_key] = 100_000

        DsfPfcHealthCheck._prune_expired_snapshots()

        self.assertNotIn(stale_key, DsfPfcHealthCheck._snapshots)
        self.assertIn(live_key, DsfPfcHealthCheck._snapshots)

    @patch(
        "neteng.test_infra.dne.taac.health_checks.dsf_health_checks."
        "dsf_pfc_health_check.get_fb303_client",
        new_callable=AsyncMock,
    )
    async def test_dsf_pfc_replace_snapshot_with_duplicate_endpoint_keeps_max(
        self, mock_get_client: AsyncMock
    ) -> None:
        key = self._dsf_key(snapshot_id="current-run")
        DsfPfcHealthCheck._snapshots[key] = (100, 200)
        first = {
            "eth1/1/1.out_pfc_frames.priority2.sum": 10,
            "eth1/1/1.in_pfc_frames.priority2.sum": 20,
        }
        second = {
            "eth1/1/1.out_pfc_frames.priority2.sum": 9,
            "eth1/1/1.in_pfc_frames.priority2.sum": 19,
        }
        client = AsyncMock()
        client.getSelectedCounters.side_effect = [first] * 3 + [second] * 3
        mock_get_client.return_value.__aenter__.return_value = client
        threshold = hc_types.DsfPfcThreshold(
            interfaces=["gtsw001.example:eth1/1/1"],
            out_pfc=0,
            comparison=hc_types.ComparisonType.EQUAL_TO,
            priority=hc_types.Priority.PRIORITY_2,
        )

        result = await DsfPfcHealthCheck(logger=self.logger)._run(
            _make_device(),
            hc_types.DsfPfcHealthCheckIn(thresholds=[threshold, threshold]),
            {
                "mode": "snapshot",
                "snapshot_id": "current-run",
                "replace_snapshot": True,
            },
        )

        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status)
        self.assertEqual((10, 20), DsfPfcHealthCheck._snapshots[key])

    @patch(
        "neteng.test_infra.dne.taac.health_checks.dsf_health_checks."
        "dsf_pfc_health_check.get_fb303_client",
        new_callable=AsyncMock,
    )
    async def test_dsf_pfc_snapshot_preserves_monotonic_baseline_by_default(
        self, mock_get_client: AsyncMock
    ) -> None:
        key = self._dsf_key()
        DsfPfcHealthCheck._snapshots[key] = (100, 200)
        client = AsyncMock()
        client.getSelectedCounters.return_value = {
            "eth1/1/1.out_pfc_frames.priority2.sum": 10,
            "eth1/1/1.in_pfc_frames.priority2.sum": 20,
        }
        mock_get_client.return_value.__aenter__.return_value = client
        threshold = hc_types.DsfPfcThreshold(
            interfaces=["gtsw001.example:eth1/1/1"],
            out_pfc=0,
            comparison=hc_types.ComparisonType.EQUAL_TO,
            priority=hc_types.Priority.PRIORITY_2,
        )

        result = await DsfPfcHealthCheck(logger=self.logger)._run(
            _make_device(),
            hc_types.DsfPfcHealthCheckIn(thresholds=[threshold]),
            {"mode": "snapshot"},
        )

        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status)
        self.assertEqual((100, 200), DsfPfcHealthCheck._snapshots[key])

    @patch(
        "neteng.test_infra.dne.taac.health_checks.dsf_health_checks."
        "dsf_pfc_health_check.asyncio.sleep",
        new_callable=AsyncMock,
    )
    @patch(
        "neteng.test_infra.dne.taac.health_checks.dsf_health_checks."
        "dsf_pfc_health_check.get_fb303_client",
        new_callable=AsyncMock,
    )
    async def test_dsf_pfc_snapshot_warns_when_out_pfc_remains_zero(
        self, mock_get_client: AsyncMock, mock_sleep: AsyncMock
    ) -> None:
        client = AsyncMock()
        client.getSelectedCounters.return_value = {
            "eth1/1/1.out_pfc_frames.priority2.sum": 0,
            "eth1/1/1.in_pfc_frames.priority2.sum": 0,
        }
        mock_get_client.return_value.__aenter__.return_value = client

        counters = await DsfPfcHealthCheck(
            logger=self.logger
        )._get_fboss_monotonic_pfc_counters(
            device="gtsw001.example",
            interface="eth1/1/1",
            priority=2,
            endpoint="gtsw001.example:eth1/1/1",
            baseline=(0, 0),
            mode="snapshot",
            max_attempts=2,
            snapshot_retry_out_pfc_on_zero=True,
        )

        self.assertEqual((0, 0), counters)
        mock_sleep.assert_awaited_once_with(0.2)
        self.logger.warning.assert_called_once()
        self.assertIn(
            "remained zero",
            self.logger.warning.call_args.args[0],
        )

    @patch(
        "neteng.test_infra.dne.taac.health_checks.dsf_health_checks."
        "dsf_pfc_health_check.asyncio.sleep",
        new_callable=AsyncMock,
    )
    @patch(
        "neteng.test_infra.dne.taac.health_checks.dsf_health_checks."
        "dsf_pfc_health_check.get_fb303_client",
        new_callable=AsyncMock,
    )
    async def test_dsf_pfc_requires_both_counter_keys_in_each_attempt(
        self, mock_get_client: AsyncMock, mock_sleep: AsyncMock
    ) -> None:
        client = AsyncMock()
        both_zero = {
            "eth1/1/1.out_pfc_frames.priority2.sum": 0,
            "eth1/1/1.in_pfc_frames.priority2.sum": 0,
        }
        out_only = {"eth1/1/1.out_pfc_frames.priority2.sum": 1}
        client.getSelectedCounters.side_effect = [both_zero] * 3 + [out_only] * 3
        mock_get_client.return_value.__aenter__.return_value = client

        with self.assertRaisesRegex(RuntimeError, "counters missing"):
            await DsfPfcHealthCheck(
                logger=self.logger
            )._get_fboss_monotonic_pfc_counters(
                device="gtsw001.example",
                interface="eth1/1/1",
                priority=2,
                endpoint="gtsw001.example:eth1/1/1",
                baseline=(0, 0),
                mode="snapshot",
                max_attempts=2,
                snapshot_retry_out_pfc_on_zero=True,
            )

        mock_sleep.assert_awaited_once_with(0.2)

    @patch(
        "neteng.test_infra.dne.taac.health_checks.dsf_health_checks."
        "dsf_pfc_health_check.get_fb303_client",
        new_callable=AsyncMock,
    )
    async def test_dsf_pfc_snapshot_fails_when_counter_keys_are_missing(
        self, mock_get_client: AsyncMock
    ) -> None:
        client = AsyncMock()
        client.getSelectedCounters.return_value = {}
        mock_get_client.return_value.__aenter__.return_value = client
        threshold = hc_types.DsfPfcThreshold(
            interfaces=["gtsw001.example:eth1/1/1"],
            out_pfc=0,
            in_pfc=0,
            comparison=hc_types.ComparisonType.EQUAL_TO,
            priority=hc_types.Priority.PRIORITY_2,
        )

        result = await DsfPfcHealthCheck(logger=self.logger)._run(
            _make_device(),
            hc_types.DsfPfcHealthCheckIn(thresholds=[threshold]),
            {"mode": "snapshot"},
        )

        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("counters missing", result.message or "")

    @patch(
        "neteng.test_infra.dne.taac.health_checks.dsf_health_checks."
        "dsf_pfc_health_check.get_fb303_client",
        new_callable=AsyncMock,
    )
    async def test_dsf_pfc_remote_target_requires_selected_executor(
        self, mock_get_client: AsyncMock
    ) -> None:
        threshold = hc_types.DsfPfcThreshold(
            interfaces=["gtsw002.example:eth1/1/1"],
            out_pfc=0,
            comparison=hc_types.ComparisonType.EQUAL_TO,
            priority=hc_types.Priority.PRIORITY_2,
        )
        check = DsfPfcHealthCheck(logger=self.logger)

        result = await check._run(
            _make_device(),
            hc_types.DsfPfcHealthCheckIn(thresholds=[threshold]),
            {"mode": "snapshot"},
        )

        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status)
        mock_get_client.assert_not_awaited()

    async def test_dsf_pfc_executor_mismatch_is_benign_noop(self) -> None:
        threshold = hc_types.DsfPfcThreshold(
            interfaces=["gtsw002.example:eth1/1/1"],
            out_pfc=0,
            comparison=hc_types.ComparisonType.EQUAL_TO,
            priority=hc_types.Priority.PRIORITY_2,
        )
        check = DsfPfcHealthCheck(logger=self.logger)

        result = await check._run(
            _make_device(),
            hc_types.DsfPfcHealthCheckIn(thresholds=[threshold]),
            {"mode": "snapshot", "executor_device": "gtsw002.example"},
        )

        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status)
        self.assertIn("Skipping DSF PFC check", result.message or "")

    async def test_dsf_pfc_rejects_malformed_endpoint(self) -> None:
        threshold = hc_types.DsfPfcThreshold(
            interfaces=["missing-interface-separator"],
            out_pfc=0,
            comparison=hc_types.ComparisonType.EQUAL_TO,
            priority=hc_types.Priority.PRIORITY_2,
        )

        result = await DsfPfcHealthCheck(logger=self.logger)._run(
            _make_device(),
            hc_types.DsfPfcHealthCheckIn(thresholds=[threshold]),
            {"mode": "snapshot"},
        )

        self.assertEqual(hc_types.HealthCheckStatus.ERROR, result.status)
        self.assertIn("expected 'device:interface'", result.message or "")

    @patch(
        "neteng.test_infra.dne.taac.health_checks.device_health_checks."
        "pfc_wd_health_check.get_fb303_client",
        new_callable=AsyncMock,
    )
    async def test_pfc_wd_monotonic_skips_unmatched_dut(
        self, mock_get_client: AsyncMock
    ) -> None:
        result = await PfcWdHealthCheck(logger=self.logger)._run(
            _make_device(name="gtsw002.example"),
            self._pfc_wd_input(),
            {"mode": "snapshot"},
        )

        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status)
        self.assertIn("Skipping PFC watchdog check", result.message or "")
        mock_get_client.assert_not_awaited()

    @patch(
        "neteng.test_infra.dne.taac.health_checks.device_health_checks."
        "pfc_wd_health_check.get_fb303_client",
        new_callable=AsyncMock,
    )
    async def test_pfc_wd_executor_reads_remote_target_device(
        self, mock_get_client: AsyncMock
    ) -> None:
        client = AsyncMock()
        client.getSelectedCounters.return_value = {
            "eth1/1/1.pfc_deadlock_detection.sum": 3,
            "eth1/1/1.pfc_deadlock_recovery.sum": 2,
        }
        mock_get_client.return_value.__aenter__.return_value = client
        threshold = hc_types.PfcWdThreshold(
            interfaces=["gtsw002.example:eth1/1/1"],
            deadlock_threshold=0,
            recovery_threshold=0,
            comparison=hc_types.ComparisonType.EQUAL_TO,
        )

        result = await PfcWdHealthCheck(logger=self.logger)._run(
            _make_device(),
            hc_types.PfcWdHealthCheckIn(thresholds=[threshold]),
            {
                "mode": "snapshot",
                "executor_device": "gtsw001.example",
                "snapshot_id": "current-run",
            },
        )

        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status)
        mock_get_client.assert_awaited_once_with("gtsw002.example")
        self.assertEqual(
            (3, 2),
            PfcWdHealthCheck._snapshots[("current-run", "gtsw002.example", "eth1/1/1")],
        )

    async def test_dsf_pfc_check_rejects_prior_run_snapshot(self) -> None:
        DsfPfcHealthCheck._snapshots[self._dsf_key(snapshot_id="prior-run")] = (
            100,
            100,
        )
        threshold = hc_types.DsfPfcThreshold(
            interfaces=["gtsw001.example:eth1/1/1"],
            out_pfc=0,
            comparison=hc_types.ComparisonType.EQUAL_TO,
            priority=hc_types.Priority.PRIORITY_2,
        )

        result = await DsfPfcHealthCheck(logger=self.logger)._run(
            _make_device(),
            hc_types.DsfPfcHealthCheckIn(thresholds=[threshold]),
            {"mode": "check", "snapshot_id": "current-run"},
        )

        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("requires a prior snapshot", result.message or "")

    async def test_dsf_pfc_device_matching_is_strict_after_suffix_normalization(
        self,
    ) -> None:
        self.assertTrue(
            is_same_device(
                "gtsw001.l1001.c085.ash6.facebook.com",
                "gtsw001.l1001.c085.ash6",
            )
        )
        self.assertTrue(
            is_same_device(
                "gtsw001.l1001.c085.ash6.tfbnw.net",
                "gtsw001.l1001.c085.ash6",
            )
        )
        self.assertFalse(is_same_device("gtsw001", "gtsw001.otherpod.facebook.com"))
        self.assertFalse(is_same_device("gtsw001.example", "gtsw002.example"))

    @patch(
        "neteng.test_infra.dne.taac.health_checks.dsf_health_checks."
        "dsf_pfc_health_check.asyncio.sleep",
        new_callable=AsyncMock,
    )
    @patch(
        "neteng.test_infra.dne.taac.health_checks.dsf_health_checks."
        "dsf_pfc_health_check.get_fb303_client",
        new_callable=AsyncMock,
    )
    async def test_dsf_pfc_check_fails_persistent_counter_regression(
        self, mock_get_client: AsyncMock, mock_sleep: AsyncMock
    ) -> None:
        key = self._dsf_key()
        DsfPfcHealthCheck._snapshots[key] = (100, 100)
        client = AsyncMock()
        client.getSelectedCounters.return_value = {
            "eth1/1/1.out_pfc_frames.priority2.sum": 1,
            "eth1/1/1.in_pfc_frames.priority2.sum": 1,
        }
        mock_get_client.return_value.__aenter__.return_value = client
        threshold = hc_types.DsfPfcThreshold(
            interfaces=["gtsw001.example:eth1/1/1"],
            out_pfc=0,
            comparison=hc_types.ComparisonType.EQUAL_TO,
            priority=hc_types.Priority.PRIORITY_2,
        )
        check = DsfPfcHealthCheck(logger=self.logger)

        result = await check._run(
            _make_device(),
            hc_types.DsfPfcHealthCheckIn(thresholds=[threshold]),
            {"mode": "check"},
        )

        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("remained below the snapshot baseline", result.message or "")
        self.assertEqual(4, mock_sleep.await_count)
        self.assertIn(key, DsfPfcHealthCheck._snapshots)

    async def test_dsf_pfc_snapshot_mode_rejects_eos(self) -> None:
        threshold = hc_types.DsfPfcThreshold(
            interfaces=["gtsw001.example:eth1/1/1"],
            out_pfc=0,
            comparison=hc_types.ComparisonType.EQUAL_TO,
            priority=hc_types.Priority.PRIORITY_2,
        )

        result = await DsfPfcHealthCheck(logger=self.logger)._run(
            _make_device(os="EOS"),
            hc_types.DsfPfcHealthCheckIn(thresholds=[threshold]),
            {"mode": "snapshot"},
        )

        self.assertEqual(hc_types.HealthCheckStatus.ERROR, result.status)
        self.assertIn("requires FBOSS", result.message or "")

    @patch(
        "neteng.test_infra.dne.taac.health_checks.dsf_health_checks."
        "dsf_pfc_health_check.get_fb303_client",
        new_callable=AsyncMock,
    )
    async def test_dsf_pfc_framework_retry_reuses_then_consumes_snapshot(
        self, mock_get_client: AsyncMock
    ) -> None:
        snapshot_id = "test-run"
        key = self._dsf_key(snapshot_id=snapshot_id)
        DsfPfcHealthCheck._snapshots[key] = (100, 100)
        first = {
            "eth1/1/1.out_pfc_frames.priority2.sum": 101,
            "eth1/1/1.in_pfc_frames.priority2.sum": 101,
        }
        second = {
            "eth1/1/1.out_pfc_frames.priority2.sum": 110,
            "eth1/1/1.in_pfc_frames.priority2.sum": 110,
        }
        client = AsyncMock()
        client.getSelectedCounters.side_effect = [first] * 3 + [second] * 3
        mock_get_client.return_value.__aenter__.return_value = client
        threshold = hc_types.DsfPfcThreshold(
            interfaces=["gtsw001.example:eth1/1/1"],
            out_pfc=5,
            in_pfc=5,
            comparison=hc_types.ComparisonType.GREATER_THAN,
            priority=hc_types.Priority.PRIORITY_2,
        )
        check_input = hc_types.DsfPfcHealthCheckIn(thresholds=[threshold])

        result = await DsfPfcHealthCheck(logger=self.logger).run(
            _make_device(),
            check_input,
            check_input,
            {
                "mode": "check",
                "snapshot_id": snapshot_id,
                "retry_count": 1,
                "retry_delay_seconds": 0,
            },
        )

        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status)
        self.assertEqual(6, client.getSelectedCounters.await_count)
        self.assertNotIn(key, DsfPfcHealthCheck._snapshots)

    async def test_dsf_pfc_check_uses_captured_baseline_after_concurrent_eviction(
        self,
    ) -> None:
        snapshot_id = "test-run"
        key = self._dsf_key(snapshot_id=snapshot_id)
        DsfPfcHealthCheck._snapshots[key] = (100, 100)
        check = DsfPfcHealthCheck(logger=self.logger)

        async def fetch_and_evict(*_args: object, **_kwargs: object) -> tuple[int, int]:
            DsfPfcHealthCheck._snapshots.pop(key)
            return (110, 110)

        threshold = hc_types.DsfPfcThreshold(
            interfaces=["gtsw001.example:eth1/1/1"],
            out_pfc=0,
            in_pfc=0,
            comparison=hc_types.ComparisonType.GREATER_THAN,
            priority=hc_types.Priority.PRIORITY_2,
        )
        with patch.object(
            check,
            "_get_fboss_monotonic_pfc_counters",
            new_callable=AsyncMock,
            side_effect=fetch_and_evict,
        ):
            result = await check._run(
                _make_device(),
                hc_types.DsfPfcHealthCheckIn(thresholds=[threshold]),
                {"mode": "check", "snapshot_id": snapshot_id},
            )

        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status)

    @patch(
        "neteng.test_infra.dne.taac.health_checks.device_health_checks."
        "clear_counters_health_check.asyncio.sleep",
        new_callable=AsyncMock,
    )
    async def test_fboss_clear_stops_and_restarts_traffic(
        self, mock_sleep: AsyncMock
    ) -> None:
        check = ClearCountersHealthCheck(logger=self.logger)
        check.driver = AsyncMock()
        ixia = MagicMock()
        check.ixia = ixia

        result = await check._run(_make_device(), hc_types.BaseHealthCheckIn(), {})

        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status)
        ixia.stop_traffic.assert_called_once_with()
        check.driver.async_run_cmd_on_shell.assert_awaited_once_with(
            "fboss2 clear interface counters"
        )
        check.driver.async_execute_show_or_configure_cmd_on_shell.assert_not_awaited()
        ixia.start_traffic.assert_called_once_with()
        self.assertEqual(2, mock_sleep.await_count)

    @patch(
        "neteng.test_infra.dne.taac.health_checks.device_health_checks."
        "clear_counters_health_check.asyncio.sleep",
        new_callable=AsyncMock,
    )
    async def test_clear_rejects_unsupported_os_and_restarts_traffic(
        self, mock_sleep: AsyncMock
    ) -> None:
        check = ClearCountersHealthCheck(logger=self.logger)
        check.driver = AsyncMock()
        ixia = MagicMock()
        check.ixia = ixia

        result = await check._run(
            _make_device(os="UNKNOWN"), hc_types.BaseHealthCheckIn(), {}
        )

        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("Unsupported operating system: UNKNOWN", result.message or "")
        check.driver.async_run_cmd_on_shell.assert_not_awaited()
        check.driver.async_execute_show_or_configure_cmd_on_shell.assert_not_awaited()
        ixia.start_traffic.assert_called_once_with()
        self.assertEqual(2, mock_sleep.await_count)

    @patch(
        "neteng.test_infra.dne.taac.health_checks.device_health_checks."
        "port_counters_health_check.async_get_device_driver",
        new_callable=AsyncMock,
    )
    async def test_remote_target_device_is_checked(
        self, mock_get_driver: AsyncMock
    ) -> None:
        check = PortCountersHealthCheck(logger=self.logger)
        check.driver = AsyncMock()
        remote_driver = AsyncMock()
        remote_driver.async_get_multiple_port_stats.return_value = []
        mock_get_driver.return_value = remote_driver
        threshold = hc_types.PortCountersThreshold(
            interfaces=["gtsw002.example:eth1/1/1"],
            out_discards=0,
            comparison=hc_types.ComparisonType.EQUAL_TO,
        )

        result = await check._run(
            _make_device(),
            hc_types.PortCountersHealthCheckIn(thresholds=[threshold]),
            {},
        )

        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status)
        check.driver.async_get_multiple_port_stats.assert_not_awaited()
        mock_get_driver.assert_awaited_once_with("gtsw002.example")
        remote_driver.async_get_multiple_port_stats.assert_awaited_once_with(
            ["eth1/1/1"]
        )

    async def test_unqualified_interface_targets_current_device(self) -> None:
        check = PortCountersHealthCheck(logger=self.logger)
        check.driver = AsyncMock()
        check.driver.async_get_multiple_port_stats.return_value = []
        threshold = hc_types.PortCountersThreshold(
            interfaces=["eth1/1/1"],
            out_discards=0,
            comparison=hc_types.ComparisonType.EQUAL_TO,
        )

        result = await check._run(
            _make_device(),
            hc_types.PortCountersHealthCheckIn(thresholds=[threshold]),
            {},
        )

        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status)
        check.driver.async_get_multiple_port_stats.assert_awaited_once_with(
            ["eth1/1/1"]
        )

    async def test_target_device_matches_fully_qualified_hostname(self) -> None:
        check = PortCountersHealthCheck(logger=self.logger)
        check.driver = AsyncMock()
        check.driver.async_get_multiple_port_stats.return_value = []
        threshold = hc_types.PortCountersThreshold(
            interfaces=["gtsw001.example:eth1/1/1"],
            out_discards=0,
            comparison=hc_types.ComparisonType.EQUAL_TO,
        )

        result = await check._run(
            _make_device(name="gtsw001.example.facebook.com"),
            hc_types.PortCountersHealthCheckIn(thresholds=[threshold]),
            {},
        )

        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status)
        check.driver.async_get_multiple_port_stats.assert_awaited_once_with(
            ["eth1/1/1"]
        )

    @patch(
        "neteng.test_infra.dne.taac.health_checks.device_health_checks."
        "port_counters_health_check.async_get_device_driver",
        new_callable=AsyncMock,
    )
    async def test_short_hostname_targets_current_device(
        self, mock_get_driver: AsyncMock
    ) -> None:
        check = PortCountersHealthCheck(logger=self.logger)
        check.driver = AsyncMock()
        check.driver.async_get_multiple_port_stats.return_value = []
        threshold = hc_types.PortCountersThreshold(
            interfaces=["gtsw001:eth1/1/1"],
            out_discards=0,
            comparison=hc_types.ComparisonType.EQUAL_TO,
        )

        result = await check._run(
            _make_device(name="gtsw001.l1001.c085.ash6"),
            hc_types.PortCountersHealthCheckIn(thresholds=[threshold]),
            {},
        )

        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status)
        mock_get_driver.assert_not_awaited()
        check.driver.async_get_multiple_port_stats.assert_awaited_once_with(
            ["eth1/1/1"]
        )

    @patch(
        "neteng.test_infra.dne.taac.health_checks.device_health_checks."
        "clear_counters_health_check.asyncio.sleep",
        new_callable=AsyncMock,
    )
    async def test_fboss_clear_failure_still_restarts_traffic(
        self, _mock_sleep
    ) -> None:
        check = ClearCountersHealthCheck(logger=self.logger)
        check.driver = AsyncMock()
        check.driver.async_run_cmd_on_shell.side_effect = RuntimeError("clear failed")
        ixia = MagicMock()
        check.ixia = ixia

        result = await check._run(_make_device(), hc_types.BaseHealthCheckIn(), {})

        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        ixia.stop_traffic.assert_called_once_with()
        ixia.start_traffic.assert_called_once_with()

    @patch(
        "neteng.test_infra.dne.taac.health_checks.device_health_checks."
        "clear_counters_health_check.asyncio.sleep",
        new_callable=AsyncMock,
    )
    async def test_clear_and_restart_failures_are_both_reported(
        self, _mock_sleep
    ) -> None:
        check = ClearCountersHealthCheck(logger=self.logger)
        check.driver = AsyncMock()
        check.driver.async_run_cmd_on_shell.side_effect = RuntimeError("clear failed")
        check.ixia = MagicMock()
        check.ixia.start_traffic.side_effect = RuntimeError("restart failed")

        result = await check._run(_make_device(), hc_types.BaseHealthCheckIn(), {})

        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        message = result.message or ""
        self.assertIn("clear failed", message)
        self.assertIn("restart failed", message)
