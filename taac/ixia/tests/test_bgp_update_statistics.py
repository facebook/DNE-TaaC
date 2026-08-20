# Copyright (c) Meta Platforms, Inc. and affiliates.

import threading
import unittest
from unittest.mock import MagicMock, patch

from neteng.test_infra.dne.taac.ixia.ixia import _filter_bgp_stats_by_port, Ixia


class _Row(dict):
    @property
    def Columns(self):
        return list(self)


class _View:
    def __init__(self, view_name: str) -> None:
        self.Rows = [
            _Row(
                {
                    "Port Name": "10.0.0.1:1/1",
                    "Updates Tx": "7",
                    "Routes Advertised": "5",
                    "Routes Withdrawn": "2",
                }
            )
        ]
        self.view_name = view_name

    def CheckCondition(self, *_args) -> None:
        return None


def _make_ixia() -> Ixia:
    ixia = Ixia.__new__(Ixia)
    ixia.logger = MagicMock()
    ixia._snapshot_lock = threading.RLock()
    ixia.ixnetwork = MagicMock()
    ixia.is_uhd_chassis = False
    ixia.get_port_identifier = MagicMock(return_value="1/1")
    return ixia


class BgpUpdateStatisticsTest(unittest.TestCase):
    def test_filter_uses_ixnetwork_port_name_column(self) -> None:
        stats = [
            {"Port Name": "10.0.0.1:1/1", "Updates Tx": "7"},
            {"Port Name": "10.0.0.1:1/2", "Updates Tx": "8"},
        ]

        self.assertEqual([stats[0]], _filter_bgp_stats_by_port(stats, "1/1"))

    def test_filter_accepts_legacy_port_column(self) -> None:
        stats = [{"Port": "10.0.0.1:1/1", "Updates Tx": "7"}]

        self.assertEqual(stats, _filter_bgp_stats_by_port(stats, "1/1"))

    def test_strict_snapshot_returns_both_address_families(self) -> None:
        ixia = _make_ixia()

        with patch(
            "neteng.test_infra.dne.taac.ixia.ixia.IxnStatViewAssistant",
            side_effect=lambda _ixnetwork, view_name: _View(view_name),
        ):
            stats = ixia.get_bgp_update_statistics_strict(
                hostname="dut.example.com",
                interface="Ethernet1",
            )

        self.assertEqual(
            {"BGP Peer Per Port", "BGP+ Peer Per Port"},
            {row["View"] for row in stats},
        )

    def test_best_effort_snapshot_keeps_available_view(self) -> None:
        ixia = _make_ixia()

        def build_view(_ixnetwork, view_name):
            if view_name == "BGP Peer Per Port":
                raise RuntimeError("IPv4 view unavailable")
            return _View(view_name)

        with patch(
            "neteng.test_infra.dne.taac.ixia.ixia.IxnStatViewAssistant",
            side_effect=build_view,
        ):
            stats = ixia.get_bgp_update_statistics()

        self.assertEqual(["BGP+ Peer Per Port"], [row["View"] for row in stats])

    def test_strict_snapshot_retries_transient_busy_view(self) -> None:
        ixia = _make_ixia()
        calls = 0

        def build_view(_ixnetwork, view_name):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError(
                    "Snapshot DefaultSnapshotSettings already in progress"
                )
            return _View(view_name)

        with (
            patch(
                "neteng.test_infra.dne.taac.ixia.ixia.IxnStatViewAssistant",
                side_effect=build_view,
            ),
            patch(
                "neteng.test_infra.dne.taac.utils.oss_taac_lib_utils.time.sleep"
            ) as sleep,
        ):
            stats = ixia.get_bgp_update_statistics_strict()

        self.assertEqual(4, calls)
        sleep.assert_called_once_with(2)
        self.assertEqual(2, len(stats))

    def test_strict_snapshot_rejects_persistent_missing_afi(self) -> None:
        ixia = _make_ixia()

        def build_view(_ixnetwork, view_name):
            if view_name == "BGP+ Peer Per Port":
                raise RuntimeError(
                    "Snapshot DefaultSnapshotSettings already in progress"
                )
            return _View(view_name)

        with (
            patch(
                "neteng.test_infra.dne.taac.ixia.ixia.IxnStatViewAssistant",
                side_effect=build_view,
            ),
            patch("neteng.test_infra.dne.taac.utils.oss_taac_lib_utils.time.sleep"),
            self.assertRaisesRegex(RuntimeError, "BGP\\+ Peer Per Port"),
        ):
            ixia.get_bgp_update_statistics_strict()

    def test_strict_snapshot_rejects_missing_counter(self) -> None:
        ixia = _make_ixia()

        def build_view(_ixnetwork, view_name):
            view = _View(view_name)
            if view_name == "BGP Peer Per Port":
                view.Rows[0]["Updates Tx"] = None
            return view

        with (
            patch(
                "neteng.test_infra.dne.taac.ixia.ixia.IxnStatViewAssistant",
                side_effect=build_view,
            ),
            patch("neteng.test_infra.dne.taac.utils.oss_taac_lib_utils.time.sleep"),
            self.assertRaisesRegex(RuntimeError, "Updates Tx"),
        ):
            ixia.get_bgp_update_statistics_strict()

    def test_strict_snapshot_waits_for_session_snapshot_lock(self) -> None:
        ixia = _make_ixia()
        entered = threading.Event()
        completed = threading.Event()

        def build_view(_ixnetwork, view_name):
            entered.set()
            return _View(view_name)

        def read_snapshot() -> None:
            ixia.get_bgp_update_statistics_strict()
            completed.set()

        with patch(
            "neteng.test_infra.dne.taac.ixia.ixia.IxnStatViewAssistant",
            side_effect=build_view,
        ):
            ixia._snapshot_lock.acquire()
            thread = threading.Thread(target=read_snapshot)
            thread.start()
            try:
                self.assertFalse(entered.wait(timeout=0.05))
            finally:
                ixia._snapshot_lock.release()
            thread.join(timeout=2)

        self.assertFalse(thread.is_alive())
        self.assertTrue(completed.is_set())

    def test_filter_falls_back_from_empty_port_name(self) -> None:
        stats = [
            {
                "Port Name": "",
                "Port": "10.0.0.1:1/1",
                "Updates Tx": "7",
            }
        ]

        self.assertEqual(stats, _filter_bgp_stats_by_port(stats, "1/1"))


if __name__ == "__main__":
    unittest.main()
