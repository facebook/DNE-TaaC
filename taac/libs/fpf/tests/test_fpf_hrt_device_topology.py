# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe

import io
import ipaddress
import os
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from taac.libs.fpf.fpf_hrt_bulk_tracker import (
    count_failed_per_lane,
)
from taac.libs.fpf.fpf_stress_checks import (
    HrtBulkCollector,
    HrtBulkRow,
    HrtFsdbSessionCollector,
    HrtFsdbSessionRow,
    HrtPlaneStatusCollector,
    HrtPlaneStatusRow,
    HrtRemoteFailureCollector,
    HrtRemoteFailureRow,
)
from taac.testconfigs.fpf.fpf_hardening_common import (
    fpf_hrt_device_ids,
    fpf_hrt_vf_device_ids,
    fpf_rf_vf_groups,
    hrt_device_plane_to_beth,
)


class _ClientContext:
    def __init__(self, client) -> None:
        self.client = client

    async def __aenter__(self):
        return self.client

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


class TestFpfHrtDeviceTopology(unittest.IsolatedAsyncioTestCase):
    def test_runtime_device_mapping_is_explicit_for_multi_device_hosts(self) -> None:
        with patch.dict(
            os.environ,
            {
                "FPF_HRT_DEVICE_IDS": "0,1,2,3,4,5,6,7",
                "FPF_HRT_VF1_DEVICE_IDS": "0,2,4,6",
                "FPF_HRT_VF2_DEVICE_IDS": "1,3,5,7",
            },
            clear=False,
        ):
            device_ids = fpf_hrt_device_ids()
            self.assertEqual(device_ids, list(range(8)))
            self.assertEqual(
                fpf_hrt_vf_device_ids(device_ids),
                ([0, 2, 4, 6], [1, 3, 5, 7]),
            )

    def test_multi_device_mode_rejects_implicit_vf_mapping(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("FPF_HRT_VF1_DEVICE_IDS", None)
            os.environ.pop("FPF_HRT_VF2_DEVICE_IDS", None)
            with self.assertRaisesRegex(ValueError, "requires explicit"):
                fpf_hrt_vf_device_ids(list(range(8)))

    def test_all_eight_devices_cover_all_32_beths(self) -> None:
        beths = {
            hrt_device_plane_to_beth(device_id, local_plane)
            for device_id in range(8)
            for local_plane in range(4)
        }

        self.assertEqual(beths, set(range(32)))

    def test_vf_mapping_uses_even_and_odd_devices_with_zero_baseline(self) -> None:
        groups = fpf_rf_vf_groups(
            active_lanes=[0, 1, 2, 3],
            device_ids_by_vf=([0, 2, 4, 6], [1, 3, 5, 7]),
        )

        self.assertEqual(groups[0]["device_ids"], [0, 2, 4, 6])
        self.assertEqual(groups[1]["device_ids"], [1, 3, 5, 7])
        self.assertEqual(groups[0]["lanes"], [0, 1, 2, 3])
        self.assertEqual(groups[1]["lanes"], [0, 1, 2, 3])
        self.assertNotIn("stable_expected_per_lane", groups[1])

    def test_bulk_evaluates_every_tuple_independently(self) -> None:
        hosts = ["host-a", "host-b"]
        collector = HrtBulkCollector(hosts=hosts, device_ids=list(range(8)))
        collector.rows = [
            HrtBulkRow(
                timestamp="2026-08-30 22:00:00+0000",
                host=host,
                device_id=device_id,
                lane_counts=[4032, 4032, 4032, 1]
                if (host, device_id) == ("host-b", 7)
                else [4032, 4032, 4032, 4032],
                unique=4032,
            )
            for host in hosts
            for device_id in range(8)
        ]

        results = collector.evaluate_per_lane(
            trigger_time=datetime(2026, 8, 30, 21, 59, 59, tzinfo=timezone.utc),
            lanes=[0, 1, 2, 3],
            expected_per_lane=dict.fromkeys(range(4), 4032),
        )

        self.assertEqual(len(results), 64)
        failures = [result for result in results if not result.passed]
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0].device, "host-b/dev7/L3")

    def test_remote_failure_evaluates_every_tuple_independently(self) -> None:
        hosts = ["host-a", "host-b"]
        collector = HrtRemoteFailureCollector(hosts=hosts, device_ids=[1, 3, 5, 7])
        collector.rows = [
            HrtRemoteFailureRow(
                timestamp="2026-08-30 22:00:00+0000",
                host=host,
                device_id=device_id,
                lane_counts=[0, 0, 0, 1]
                if (host, device_id) == ("host-b", 7)
                else [0, 0, 0, 0],
                unique=1 if (host, device_id) == ("host-b", 7) else 0,
            )
            for host in hosts
            for device_id in [1, 3, 5, 7]
        ]

        results = collector.evaluate_per_lane_stable(lanes=[0, 1, 2, 3])

        self.assertEqual(len(results), 32)
        failures = [result for result in results if not result.passed]
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0].device, "host-b/dev7/L3")

    async def test_collectors_make_one_snapshot_rpc_per_host(self) -> None:
        prefix_client = SimpleNamespace(
            getPrefixTable=AsyncMock(return_value=[]),
        )
        rf_client = SimpleNamespace(
            getRemoteFailures=AsyncMock(return_value=[]),
        )
        bulk = HrtBulkCollector(
            hosts=["host-a"],
            device_ids=list(range(8)),
            plane_ids=[0, 1, 2, 3],
        )
        remote_failure = HrtRemoteFailureCollector(
            hosts=["host-a"],
            device_ids=list(range(8)),
            plane_ids=[0, 1, 2, 3],
        )
        bulk._file = io.StringIO()
        remote_failure._file = io.StringIO()

        with patch(
            "neteng.test_infra.dne.taac.libs.fpf.fpf_stress_checks.get_hrt_client",
            AsyncMock(return_value=_ClientContext(prefix_client)),
        ):
            await bulk._poll_once()
        with patch(
            "neteng.test_infra.dne.taac.libs.fpf.fpf_stress_checks.get_hrt_client",
            AsyncMock(return_value=_ClientContext(rf_client)),
        ):
            await remote_failure._poll_once()

        prefix_client.getPrefixTable.assert_awaited_once()
        rf_client.getRemoteFailures.assert_awaited_once()
        self.assertEqual(len(bulk.rows), 8)
        self.assertEqual(len(remote_failure.rows), 8)
        self.assertTrue(all(len(row.lane_counts) == 4 for row in bulk.rows))
        self.assertTrue(all(len(row.lane_counts) == 4 for row in remote_failure.rows))
        self.assertTrue(all(row.plane_ids == [0, 1, 2, 3] for row in bulk.rows))

    def test_legacy_collectors_default_to_eight_planes(self) -> None:
        self.assertEqual(HrtBulkCollector(hosts=["host-a"]).plane_ids, list(range(8)))
        self.assertEqual(
            HrtRemoteFailureCollector(hosts=["host-a"]).plane_ids, list(range(8))
        )

    async def test_plane_status_makes_one_rpc_and_splits_all_devices(self) -> None:
        plane_client = SimpleNamespace(getPlaneStatus=AsyncMock(return_value=[]))
        collector = HrtPlaneStatusCollector(
            hosts=["host-a"], device_ids=list(range(8)), num_planes=4
        )
        collector._file = io.StringIO()

        with (
            patch(
                "neteng.test_infra.dne.taac.libs.fpf.fpf_stress_checks.get_hrt_client",
                AsyncMock(return_value=_ClientContext(plane_client)),
            ),
            patch(
                "neteng.test_infra.dne.taac.libs.fpf.fpf_stress_checks.build_plane_status_map",
                return_value={
                    device_id: dict.fromkeys(range(4), "UP") for device_id in range(8)
                },
            ),
        ):
            await collector._poll_once()

        plane_client.getPlaneStatus.assert_awaited_once()
        self.assertEqual(len(collector.rows), 8)
        self.assertEqual({row.device_id for row in collector.rows}, set(range(8)))

    def test_plane_status_evaluates_exact_tuple(self) -> None:
        collector = HrtPlaneStatusCollector(
            hosts=["host-a"], device_ids=[0, 1], num_planes=4
        )
        collector.rows = [
            HrtPlaneStatusRow(
                timestamp="2026-08-30 22:00:00+0000",
                host="host-a",
                device_id=device_id,
                plane_states={0: "DOWN" if device_id == 1 else "UP"},
            )
            for device_id in [0, 1]
        ]

        results = collector.evaluate_all_up_window(
            window_start=0,
            window_end=2_000_000_000,
            expected_planes=[0],
        )

        by_device = {result.device_id: result for result in results}
        self.assertTrue(by_device[0].passed)
        self.assertFalse(by_device[1].passed)

    def test_fsdb_session_stat_preserves_exact_tuple_churn(self) -> None:
        collector = HrtFsdbSessionCollector(hosts=["host-a"])
        collector.rows = [
            HrtFsdbSessionRow(
                timestamp="2026-08-30 22:00:00+0000",
                host="host-a",
                connected=31,
                expected=32,
                tuple_connected={"dev0/L0": 1, "dev1/L0": 0},
                tuple_total={"dev0/L0": 1, "dev1/L0": 1},
            )
        ]

        result = collector.evaluate_window(
            window_start=0,
            window_end=2_000_000_000,
            impacted_tuples_by_device={"1": [0]},
            host="host-a",
        )

        self.assertTrue(result.impacted_tuple_churn["dev1/L0"])
        self.assertNotIn("dev0/L0", result.impacted_tuple_churn)

    async def test_collector_error_is_explicit_for_every_requested_device(self) -> None:
        collector = HrtBulkCollector(hosts=["host-a"], device_ids=[0, 1])
        collector._file = io.StringIO()

        with patch(
            "neteng.test_infra.dne.taac.libs.fpf.fpf_stress_checks.get_hrt_client",
            AsyncMock(side_effect=RuntimeError("unavailable")),
        ):
            await collector._poll_once()

        self.assertEqual(len(collector.rows), 2)
        self.assertTrue(all(not row.valid for row in collector.rows))
        self.assertTrue(all(row.lane_counts == [] for row in collector.rows))
        self.assertTrue(all(row.notes.startswith("error:") for row in collector.rows))
        results = collector.evaluate_per_lane(
            trigger_time=datetime.now(timezone.utc),
            lanes=[0],
            expected_per_lane={0: 0},
        )
        self.assertTrue(all(not result.passed for result in results))

    def test_remote_failure_error_cannot_be_satisfied_by_another_device(self) -> None:
        collector = HrtRemoteFailureCollector(hosts=["host-a"], device_ids=[0, 1])
        collector.rows = [
            HrtRemoteFailureRow(
                timestamp="2026-08-30 22:00:00+0000",
                host="host-a",
                device_id=0,
                lane_counts=[],
                valid=False,
                notes="error: unavailable",
            ),
            HrtRemoteFailureRow(
                timestamp="2026-08-30 22:00:00+0000",
                host="host-a",
                device_id=1,
                lane_counts=[0, 0, 0, 0],
            ),
        ]

        results = collector.evaluate_per_lane_stable(lanes=[0])

        by_device = {result.device_id: result for result in results}
        self.assertFalse(by_device[0].passed)
        self.assertTrue(by_device[1].passed)

    def test_remote_failure_is_device_local_without_paired_device_fanout(self) -> None:
        failures = [
            SimpleNamespace(prefix="5000:dd::1/128", device_id=0, failed_planes=[0]),
            SimpleNamespace(
                prefix="5000:dd::1/128", device_id=1, failed_planes=[1, 2, 3]
            ),
        ]
        supernet = ipaddress.IPv6Network("5000:dd::/32")

        plane_ids = [0, 1, 2, 3]
        dev0, _ = count_failed_per_lane(failures, 0, supernet, plane_ids)
        dev1, _ = count_failed_per_lane(failures, 1, supernet, plane_ids)
        removed, unique = count_failed_per_lane([], 0, supernet, plane_ids)

        self.assertEqual(dev0, [1, 0, 0, 0])
        self.assertEqual(dev1, [0, 1, 1, 1])
        self.assertEqual(removed, [0, 0, 0, 0])
        self.assertEqual(unique, 0)


if __name__ == "__main__":
    unittest.main()
