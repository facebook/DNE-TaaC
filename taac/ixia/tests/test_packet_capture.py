# Copyright (c) Meta Platforms, Inc. and affiliates.

import unittest
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock, patch

from taac.ixia.ixia import Ixia


class PacketCaptureTest(unittest.TestCase):
    def setUp(self) -> None:
        with patch.object(Ixia, "__init__", lambda self: None):
            self.ixia: Any = Ixia()
        self.capture = SimpleNamespace()
        self.vport = SimpleNamespace(
            href="/vport/1",
            Name="VPORT_BAG012.ASH6:ETHERNET3/36/1",
            Capture=self.capture,
        )
        self.vports = MagicMock()
        self.vports.find.return_value = self.vport
        self.start_capture = MagicMock()
        self.save_capture_files = MagicMock()
        cast(Any, self.ixia).ixnetwork = SimpleNamespace(
            Vport=self.vports,
            StartCapture=self.start_capture,
            SaveCaptureFiles=self.save_capture_files,
        )
        self.ixia.logger = MagicMock()
        self.ixia.get_port_identifier = MagicMock(return_value="1/1")
        self.ixia._capture_stopped = True

    def _start(self, **kwargs):
        return self.ixia.start_packet_capture(
            hostname="bag012.ash6",
            interface="Ethernet3/36/1",
            **kwargs,
        )

    def test_default_control_buffer_preserves_thirty_percent(self) -> None:
        self.assertEqual(self._start(), "/vport/1")
        self.assertEqual(self.capture.ControlBufferSize, 30)

    def test_control_buffer_override_accepts_supported_maximum(self) -> None:
        self.assertEqual(
            self._start(control_buffer_percent=70),
            "/vport/1",
        )
        self.assertEqual(self.capture.ControlBufferSize, 70)

    def test_control_buffer_override_accepts_supported_minimum(self) -> None:
        self.assertEqual(
            self._start(control_buffer_percent=5),
            "/vport/1",
        )
        self.assertEqual(self.capture.ControlBufferSize, 5)

    def test_batch_configures_all_vports_before_one_session_start(self) -> None:
        captures = [SimpleNamespace() for _ in range(3)]
        vports = [
            SimpleNamespace(href=f"/vport/{index}", Capture=capture)
            for index, capture in enumerate(captures, start=1)
        ]
        self.vports.find.side_effect = vports
        self.ixia.get_port_identifier.side_effect = ["8/1", "8/2", "8/3"]
        interfaces = ["Ethernet3/36/1", "Ethernet3/36/2", "Ethernet3/36/3"]

        def verify_configuration_before_start() -> None:
            self.assertTrue(
                all(capture.ControlBufferSize == 70 for capture in captures)
            )

        self.start_capture.side_effect = verify_configuration_before_start

        result = self.ixia.start_packet_captures(
            hostname="bag012.ash6",
            interfaces=interfaces,
            control_buffer_percent=70,
        )

        self.assertEqual(
            result,
            {
                interface: f"/vport/{index}"
                for index, interface in enumerate(interfaces, 1)
            },
        )
        self.start_capture.assert_called_once_with()
        self.assertTrue(all(capture.ControlBufferSize == 70 for capture in captures))
        self.assertFalse(self.ixia._capture_stopped)

    def test_batch_rejects_duplicate_interfaces_before_ixia_access(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicates"):
            self.ixia.start_packet_captures(
                hostname="bag012.ash6",
                interfaces=["Ethernet3/36/1", "Ethernet3/36/1"],
            )
        self.ixia.get_port_identifier.assert_not_called()
        self.start_capture.assert_not_called()

    def test_invalid_control_buffer_fails_before_ixia_access(self) -> None:
        for value in (4, 0, -1, 71, 101, True, 1.5, "30"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "integer from 5 through 70"):
                    self._start(control_buffer_percent=value)
        self.ixia.get_port_identifier.assert_not_called()
        self.start_capture.assert_not_called()

    def test_successful_start_resets_stop_latch(self) -> None:
        self._start()
        self.assertFalse(self.ixia._capture_stopped)
        self.start_capture.assert_called_once_with()

    def test_failed_start_preserves_stop_latch(self) -> None:
        self.start_capture.side_effect = RuntimeError("start failed")
        with self.assertRaisesRegex(ValueError, "Failed to start packet capture"):
            self._start(control_buffer_percent=30)
        self.assertTrue(self.ixia._capture_stopped)

    def test_batch_save_exports_once_and_maps_every_vport_exactly(self) -> None:
        interfaces = ["Ethernet3/36/1", "Ethernet3/36/2", "Ethernet3/36/3"]
        vports = [
            SimpleNamespace(
                href=f"/vport/{index}",
                Name=f"VPORT_BAG012.ASH6:ETHERNET3/36/{index}",
            )
            for index in range(1, 4)
        ]
        self.vports.find.return_value = vports
        saved_files = [
            f"captures/obs/VPORT_BAG012.ASH6-ETHERNET3-36-{index}_SW.cap"
            for index in range(1, 4)
        ]
        self.save_capture_files.return_value = saved_files

        result = self.ixia.save_packet_captures(
            vport_hrefs={
                interface: f"/vport/{index}"
                for index, interface in enumerate(interfaces, 1)
            },
            capture_name="observer_123",
        )

        self.assertEqual(result, dict(zip(interfaces, saved_files)))
        self.save_capture_files.assert_called_once_with("observer_123")

    def test_verify_packet_captures_active_requires_both_running_flags(self) -> None:
        active_capture = SimpleNamespace(
            IsCaptureRunning=True,
            IsControlCaptureRunning=True,
            ControlCaptureState="capturing",
        )
        inactive_capture = SimpleNamespace(
            IsCaptureRunning=True,
            IsControlCaptureRunning=False,
            ControlCaptureState="stopped",
        )
        vports = [
            SimpleNamespace(href="/vport/1", Capture=active_capture),
            SimpleNamespace(href="/vport/2", Capture=inactive_capture),
        ]
        self.vports.find.return_value = vports
        self.ixia._capture_stopped = False
        hrefs = {"Ethernet3/36/1": "/vport/1", "Ethernet3/36/2": "/vport/2"}

        with self.assertRaisesRegex(ValueError, "Ethernet3/36/2"):
            self.ixia.verify_packet_captures_active(hrefs)

        inactive_capture.IsControlCaptureRunning = True
        self.ixia.verify_packet_captures_active(hrefs)

    def test_verify_packet_captures_active_rejects_stop_latch(self) -> None:
        self.capture.IsCaptureRunning = True
        self.capture.IsControlCaptureRunning = True
        self.capture.ControlCaptureState = "capturing"
        self.vports.find.return_value = [self.vport]
        self.ixia._capture_stopped = True

        with self.assertRaisesRegex(ValueError, "stop_latch=True"):
            self.ixia.verify_packet_captures_active({"Ethernet3/36/1": "/vport/1"})

    def test_batch_save_rejects_missing_or_ambiguous_vport_file(self) -> None:
        self.vports.find.return_value = [self.vport]
        for saved_files in (
            ["captures/obs/OTHER_SW.cap"],
            [
                "captures/obs/VPORT_BAG012.ASH6-ETHERNET3-36-1_SW.cap",
                "captures/obs/VPORT_BAG012.ASH6-ETHERNET3-36-1_HW.cap",
            ],
        ):
            with self.subTest(saved_files=saved_files):
                self.save_capture_files.return_value = saved_files
                with self.assertRaisesRegex(ValueError, "exactly one"):
                    self.ixia.save_packet_captures(
                        vport_hrefs={"Ethernet3/36/1": "/vport/1"},
                        capture_name="observer_123",
                    )


class BgpSessionAddressBulkLookupTest(unittest.TestCase):
    def setUp(self) -> None:
        with patch.object(Ixia, "__init__", lambda self: None):
            self.ixia: Any = Ixia()
        self.ixia.logger = MagicMock()
        self.peer = SimpleNamespace(
            Name="EB-FA-V4",
            DutIp=SimpleNamespace(Values=["192.0.2.1", "192.0.2.3", "192.0.2.5"]),
            parent=SimpleNamespace(
                Address=SimpleNamespace(Values=["192.0.2.2", "192.0.2.4", "192.0.2.6"])
            ),
        )
        self.second_peer = SimpleNamespace(
            Name="EB-FA-V6",
            DutIp=SimpleNamespace(Values=["2001:db8::1", "2001:db8::3"]),
            parent=SimpleNamespace(
                Address=SimpleNamespace(Values=["2001:db8::2", "2001:db8::4"])
            ),
        )
        self.ixia.find_bgp_peers = MagicMock(return_value=[self.peer])

    def test_bulk_lookup_scans_once_and_returns_requested_slice(self) -> None:
        addresses = self.ixia.get_bgp_session_addresses_bulk(
            regex="EB-FA-V4",
            session_start_index=2,
            session_count=2,
        )
        self.assertEqual(
            addresses,
            [("192.0.2.4", "192.0.2.3"), ("192.0.2.6", "192.0.2.5")],
        )
        self.ixia.find_bgp_peers.assert_called_once_with("EB-FA-V4", False)

    def test_bulk_lookup_rejects_ambiguous_peer_regex(self) -> None:
        self.ixia.find_bgp_peers.return_value = [self.peer, self.peer]
        with self.assertRaisesRegex(ValueError, "exactly one"):
            self.ixia.get_bgp_session_addresses_bulk(
                regex="EB-FA",
                session_start_index=1,
                session_count=1,
            )

    def test_bulk_lookup_reports_one_based_out_of_range(self) -> None:
        with self.assertRaisesRegex(ValueError, "Session range 2-4"):
            self.ixia.get_bgp_session_addresses_bulk(
                regex="EB-FA-V4",
                session_start_index=2,
                session_count=3,
            )

    def test_multi_range_lookup_scans_once_and_preserves_request_order(self) -> None:
        self.ixia.find_bgp_peers.return_value = [self.second_peer, self.peer]

        addresses = self.ixia.get_bgp_session_address_ranges(
            [
                (r"^EB-FA-V4$", 2, 2),
                (r"^EB-FA-V6$", 1, 1),
            ]
        )

        self.assertEqual(
            addresses,
            [
                [("192.0.2.4", "192.0.2.3"), ("192.0.2.6", "192.0.2.5")],
                [("2001:db8::2", "2001:db8::1")],
            ],
        )
        self.ixia.find_bgp_peers.assert_called_once_with()

    def test_multi_range_lookup_contextualizes_ambiguous_regex(self) -> None:
        self.ixia.find_bgp_peers.return_value = [self.peer, self.second_peer]

        with self.assertRaisesRegex(ValueError, r"observer_groups\[0\].*exactly one"):
            self.ixia.get_bgp_session_address_ranges(
                [(r"^EB-FA-", 1, 1)],
                request_label="observer_groups",
            )

    def test_multi_range_lookup_contextualizes_out_of_range(self) -> None:
        self.ixia.find_bgp_peers.return_value = [self.peer, self.second_peer]

        with self.assertRaisesRegex(
            ValueError, r"observer_groups\[1\].*Session range 2-4"
        ):
            self.ixia.get_bgp_session_address_ranges(
                [
                    (r"^EB-FA-V6$", 1, 1),
                    (r"^EB-FA-V4$", 2, 3),
                ],
                request_label="observer_groups",
            )

    def test_multi_range_lookup_validates_all_requests_before_scan(self) -> None:
        with self.assertRaisesRegex(ValueError, r"observer_groups\[1\].*invalid regex"):
            self.ixia.get_bgp_session_address_ranges(
                [
                    (r"^EB-FA-V4$", 1, 1),
                    ("(", 1, 1),
                ],
                request_label="observer_groups",
            )

        self.ixia.find_bgp_peers.assert_not_called()
