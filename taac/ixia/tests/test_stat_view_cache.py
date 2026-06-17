# pyre-unsafe
# Copyright (c) Meta Platforms, Inc. and affiliates.
"""Unit tests for TaacIxia.get_or_create_stat_view caching helper."""

import threading
import typing as t
import unittest
from unittest.mock import MagicMock, patch

from taac.ixia.taac_ixia import TaacIxia


def _create_taac_ixia():
    """Create a TaacIxia with mocked session/logger and an empty stat view cache."""
    with patch.object(TaacIxia, "__init__", lambda self: None):
        ixia = TaacIxia()
    ixia.logger = MagicMock()
    ixia.session = MagicMock()
    ixia.ixnetwork = MagicMock()
    ixia.is_uhd_chassis = False
    ixia._stat_view_cache = {}
    ixia._stat_view_index_lock = threading.Lock()
    ixia._stat_view_construction_locks = {}
    return ixia


class GetOrCreateStatViewTest(unittest.TestCase):
    """Tests for TaacIxia.get_or_create_stat_view."""

    def setUp(self):
        self.ixia = _create_taac_ixia()

    def test_first_call_constructs_assistant(self):
        """First call instantiates StatViewAssistant and caches it."""
        with patch(
            "neteng.test_infra.dne.taac.ixia.taac_ixia.IxnStatViewAssistant"
        ) as mock_cls:
            mock_cls.return_value = MagicMock(name="port_stats_view")
            result = self.ixia.get_or_create_stat_view("Port Statistics")
            mock_cls.assert_called_once_with(
                self.ixia.ixnetwork, "Port Statistics", Timeout=30
            )
            self.assertIs(result, mock_cls.return_value)
            self.assertIn("Port Statistics", self.ixia._stat_view_cache)

    def test_repeat_call_returns_cached_instance(self):
        """Second call for the SAME view_name returns the cached instance without constructing again."""
        with patch(
            "neteng.test_infra.dne.taac.ixia.taac_ixia.IxnStatViewAssistant"
        ) as mock_cls:
            mock_cls.return_value = MagicMock(name="port_stats_view")
            first = self.ixia.get_or_create_stat_view("Port Statistics")
            second = self.ixia.get_or_create_stat_view("Port Statistics")
            third = self.ixia.get_or_create_stat_view("Port Statistics")
            self.assertIs(first, second)
            self.assertIs(second, third)
            # Constructor called exactly once across three calls.
            self.assertEqual(mock_cls.call_count, 1)

    def test_different_view_names_cached_separately(self):
        """Different view_names produce different cached instances."""
        with patch(
            "neteng.test_infra.dne.taac.ixia.taac_ixia.IxnStatViewAssistant"
        ) as mock_cls:
            instances = [MagicMock(name=f"view_{i}") for i in range(3)]
            mock_cls.side_effect = instances
            port = self.ixia.get_or_create_stat_view("Port Statistics")
            protocols = self.ixia.get_or_create_stat_view("Protocols Summary")
            traffic = self.ixia.get_or_create_stat_view("Traffic Item Statistics")
            self.assertIs(port, instances[0])
            self.assertIs(protocols, instances[1])
            self.assertIs(traffic, instances[2])
            self.assertEqual(mock_cls.call_count, 3)

    def test_custom_timeout_forwarded(self):
        """timeout kwarg is forwarded to the StatViewAssistant constructor."""
        with patch(
            "neteng.test_infra.dne.taac.ixia.taac_ixia.IxnStatViewAssistant"
        ) as mock_cls:
            self.ixia.get_or_create_stat_view("Port Statistics", timeout=60)
            mock_cls.assert_called_once_with(
                self.ixia.ixnetwork, "Port Statistics", Timeout=60
            )

    def test_uhd_chassis_uses_uhd_class(self):
        """When is_uhd_chassis is True, the UHD class is used instead of IXN."""
        self.ixia.is_uhd_chassis = True
        with patch(
            "neteng.test_infra.dne.taac.ixia.taac_ixia.UhdStatViewAssistant"
        ) as mock_uhd:
            with patch(
                "neteng.test_infra.dne.taac.ixia.taac_ixia.IxnStatViewAssistant"
            ) as mock_ixn:
                self.ixia.get_or_create_stat_view("Port Statistics")
                mock_uhd.assert_called_once()
                mock_ixn.assert_not_called()

    def test_invalidate_specific_view(self):
        """invalidate_stat_view_cache(view_name) drops only that view."""
        with patch(
            "neteng.test_infra.dne.taac.ixia.taac_ixia.IxnStatViewAssistant"
        ) as mock_cls:
            mock_cls.side_effect = [MagicMock(name=f"v_{i}") for i in range(3)]
            self.ixia.get_or_create_stat_view("Port Statistics")
            self.ixia.get_or_create_stat_view("Protocols Summary")
            self.assertEqual(len(self.ixia._stat_view_cache), 2)
            self.ixia.invalidate_stat_view_cache("Port Statistics")
            self.assertNotIn("Port Statistics", self.ixia._stat_view_cache)
            self.assertIn("Protocols Summary", self.ixia._stat_view_cache)
            # Next call to invalidated view reconstructs.
            self.ixia.get_or_create_stat_view("Port Statistics")
            # Constructor called 3 times total (Port, Protocols, Port-again).
            self.assertEqual(mock_cls.call_count, 3)

    def test_invalidate_all_views(self):
        """invalidate_stat_view_cache(None) drops every entry."""
        with patch(
            "neteng.test_infra.dne.taac.ixia.taac_ixia.IxnStatViewAssistant"
        ) as mock_cls:
            mock_cls.side_effect = [MagicMock(name=f"v_{i}") for i in range(2)]
            self.ixia.get_or_create_stat_view("Port Statistics")
            self.ixia.get_or_create_stat_view("Protocols Summary")
            self.assertEqual(len(self.ixia._stat_view_cache), 2)
            self.ixia.invalidate_stat_view_cache()
            self.assertEqual(len(self.ixia._stat_view_cache), 0)

    def test_invalidate_missing_view_is_noop(self):
        """Invalidating a view that was never cached does not raise."""
        self.ixia.invalidate_stat_view_cache("Nonexistent View")
        # No exception is the assertion.
        self.assertEqual(len(self.ixia._stat_view_cache), 0)

    def test_concurrent_first_call_constructs_only_once(self):
        """N threads racing to get the same view see only one constructor call."""
        construct_count = {"n": 0}
        lock = threading.Lock()

        def _slow_construct(*args, **kwargs):
            with lock:
                construct_count["n"] += 1
            # Sleep to widen the race window.
            import time

            time.sleep(0.05)
            return MagicMock(name="cached_view")

        with patch(
            "neteng.test_infra.dne.taac.ixia.taac_ixia.IxnStatViewAssistant",
            side_effect=_slow_construct,
        ):
            threads = [
                threading.Thread(
                    target=lambda: self.ixia.get_or_create_stat_view("Port Statistics")
                )
                for _ in range(8)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        # All 8 threads ended up with the same cached view, and the
        # constructor was called exactly once (lock-protected critical section).
        self.assertEqual(construct_count["n"], 1)
        self.assertEqual(len(self.ixia._stat_view_cache), 1)

    def test_concurrent_first_call_distinct_views_run_in_parallel(self):
        """Construction of two DIFFERENT views happens in parallel, not serial.

        Validates the per-view-name lock fix: a slow construction of view A
        must NOT block construction of view B. Without per-view locks, both
        constructions would serialize on the single shared lock.
        """
        import time

        SLEEP = 0.2
        timings: t.Dict[str, t.Tuple[float, float]] = {}
        timings_lock = threading.Lock()

        def _slow_construct(_ixnetwork, view_name, **kwargs):
            start = time.monotonic()
            time.sleep(SLEEP)
            end = time.monotonic()
            with timings_lock:
                timings[view_name] = (start, end)
            return MagicMock(name=view_name)

        with patch(
            "neteng.test_infra.dne.taac.ixia.taac_ixia.IxnStatViewAssistant",
            side_effect=_slow_construct,
        ):
            threads = [
                threading.Thread(
                    target=lambda: self.ixia.get_or_create_stat_view("Port Statistics")
                ),
                threading.Thread(
                    target=lambda: self.ixia.get_or_create_stat_view(
                        "Protocols Summary"
                    )
                ),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        # Both constructions occurred.
        self.assertEqual(len(timings), 2)
        # Overlap check: the second-to-start began BEFORE the first-to-finish ended.
        # If they ran serially, second.start would be after first.end.
        port_start, port_end = timings["Port Statistics"]
        proto_start, proto_end = timings["Protocols Summary"]
        first_end = min(port_end, proto_end)
        last_start = max(port_start, proto_start)
        self.assertLess(
            last_start,
            first_end,
            "Distinct-view constructions must overlap (per-view lock); "
            f"port=({port_start:.3f},{port_end:.3f}) "
            f"proto=({proto_start:.3f},{proto_end:.3f})",
        )

    def test_timeout_only_honored_on_first_call(self):
        """Subsequent calls return the cached assistant; second `timeout` is ignored.

        Documents the caching contract (see docstring on `get_or_create_stat_view`).
        """
        with patch(
            "neteng.test_infra.dne.taac.ixia.taac_ixia.IxnStatViewAssistant"
        ) as mock_cls:
            mock_cls.return_value = MagicMock(name="cached_view")
            self.ixia.get_or_create_stat_view("Port Statistics", timeout=30)
            self.ixia.get_or_create_stat_view("Port Statistics", timeout=120)
            # Constructor called once with the FIRST timeout; second call is a
            # cache hit, the second timeout is silently dropped.
            mock_cls.assert_called_once_with(
                self.ixia.ixnetwork, "Port Statistics", Timeout=30
            )
