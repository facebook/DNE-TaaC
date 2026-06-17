# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from taac.tasks.periodic_tasks import ThriftStressPeriodicTask
from taac.tasks.thrift_stress_payloads import (
    fboss_with_qsfp_flaps,
    PAYLOAD_BUILDERS,
    READ_ONLY_FBOSS_APIS,
    ThriftStressCall,
)
from taac.health_check.health_check import types as hc_types


PERIODIC_TASKS_PATH = "neteng.test_infra.dne.taac.tasks.periodic_tasks"


def _make_fboss_driver(extra_apis=None) -> MagicMock:
    """Mock FBOSS driver with all READ_ONLY APIs (plus optional extras) as AsyncMocks.

    Uses spec to ensure attribute access raises AttributeError for unknown
    methods (so MagicMock's auto-attr behavior doesn't mask real bugs in our
    iscoroutinefunction filter).
    """
    method_names = [c.method for c in READ_ONLY_FBOSS_APIS] + (extra_apis or [])
    driver = MagicMock(spec=method_names)
    driver.__class__.__name__ = "FbossSwitch"
    for name in method_names:
        setattr(driver, name, AsyncMock(return_value=42))
    return driver


class ThriftStressCallTest(unittest.TestCase):
    """to_dict / from_dict round-trip and defaults."""

    def test_defaults(self) -> None:
        call = ThriftStressCall("get_bgp_table_length")
        self.assertEqual(call.method, "get_bgp_table_length")
        self.assertEqual(call.args, ())
        self.assertEqual(call.requests_per_burst, 10000)

    def test_to_dict_serializes_tuple_as_list(self) -> None:
        call = ThriftStressCall(
            method="async_do_rapid_interface_flaps",
            args=(("eth1/1/1", "eth1/2/1"), 4, 100),
            requests_per_burst=1,
        )
        d = call.to_dict()
        self.assertEqual(d["method"], "async_do_rapid_interface_flaps")
        # tuple should survive as list (JSON-safe)
        self.assertEqual(d["args"], [["eth1/1/1", "eth1/2/1"], 4, 100])
        self.assertEqual(d["requests_per_burst"], 1)

    def test_from_dict_restores_tuple(self) -> None:
        d = {"method": "foo", "args": [1, 2], "requests_per_burst": 3}
        call = ThriftStressCall.from_dict(d)
        self.assertEqual(call.method, "foo")
        # args should be tuple after rehydration
        self.assertIsInstance(call.args, tuple)
        self.assertEqual(call.args, (1, 2))
        self.assertEqual(call.requests_per_burst, 3)

    def test_from_dict_defaults_missing_fields(self) -> None:
        call = ThriftStressCall.from_dict({"method": "bar"})
        self.assertEqual(call.args, ())
        self.assertEqual(call.requests_per_burst, 10000)


class ThriftStressPayloadCatalogTest(unittest.TestCase):
    """Catalog builders return sensible payloads."""

    def test_read_only_baseline_size(self) -> None:
        self.assertEqual(len(READ_ONLY_FBOSS_APIS), 7)
        # All entries are no-arg, default request count
        for call in READ_ONLY_FBOSS_APIS:
            self.assertEqual(call.args, ())
            self.assertEqual(call.requests_per_burst, 10000)

    def test_fboss_with_qsfp_flaps_appends_flap_entry(self) -> None:
        interfaces = ["eth1/13/1", "eth1/13/3"]
        payload = fboss_with_qsfp_flaps(interfaces)
        # All 7 baseline + 1 flap = 8
        self.assertEqual(len(payload), 8)
        # First 7 == baseline
        self.assertEqual(payload[:7], list(READ_ONLY_FBOSS_APIS))
        # Last is the flap entry. Defaults match Pavan's original —
        # interval_to_link_up=4s, total_flaps=100 (~6.7 min of continuous
        # flapping per burst).
        flap = payload[-1]
        self.assertEqual(flap.method, "async_do_rapid_interface_flaps")
        self.assertEqual(flap.args, (("eth1/13/1", "eth1/13/3"), 4, 100))
        self.assertEqual(flap.requests_per_burst, 1)

    def test_fboss_with_qsfp_flaps_overrides(self) -> None:
        payload = fboss_with_qsfp_flaps(
            ["eth1/1/1"], interval_to_link_up=8, total_flaps=50
        )
        flap = payload[-1]
        self.assertEqual(flap.args, (("eth1/1/1",), 8, 50))

    def test_fboss_with_qsfp_flaps_works_for_any_platform(self) -> None:
        """Universality: same builder works for IcePack/STSW/MP3/KO3 etc."""
        icepack_ports = ["eth1/3/1", "eth1/3/3"]  # IcePack STSW-adjacent
        stsw_ports = ["eth1/5/1", "eth1/5/3"]  # STSW GTSW-adjacent
        ipayload = fboss_with_qsfp_flaps(icepack_ports)
        spayload = fboss_with_qsfp_flaps(stsw_ports)
        # Same structure, different interface tuples in the flap entry
        self.assertEqual(ipayload[:7], spayload[:7])
        self.assertEqual(ipayload[-1].args[0], tuple(icepack_ports))
        self.assertEqual(spayload[-1].args[0], tuple(stsw_ports))

    def test_payload_builders_keys(self) -> None:
        self.assertIn("fboss_readonly", PAYLOAD_BUILDERS)
        self.assertIn("fboss_with_qsfp_flaps", PAYLOAD_BUILDERS)
        # All builders are callable
        for k, builder in PAYLOAD_BUILDERS.items():
            self.assertTrue(callable(builder), f"{k} builder not callable")


class ThriftStressPeriodicTaskTest(unittest.IsolatedAsyncioTestCase):
    """Unit tests for ThriftStressPeriodicTask burst + final-check behavior."""

    def setUp(self) -> None:
        self.logger = MagicMock()
        self.task = ThriftStressPeriodicTask(
            hostname="gtsw001.l1001.c085.ash6",
            logger=self.logger,
        )

    # ---- New calls-shape path --------------------------------------------

    async def test_calls_path_fires_with_args_and_counts(self) -> None:
        """The calls path respects per-call args and requests_per_burst."""
        driver = _make_fboss_driver(extra_apis=["async_do_rapid_interface_flaps"])
        with patch(
            f"{PERIODIC_TASKS_PATH}.async_get_device_driver",
            AsyncMock(return_value=driver),
        ):
            payload = [
                ThriftStressCall("get_bgp_table_length", requests_per_burst=4),
                ThriftStressCall(
                    "async_do_rapid_interface_flaps",
                    args=(("eth1/1/1",), 1, 2),
                    requests_per_burst=1,
                ),
            ]
            await self.task.run(
                {
                    "hostname": "gtsw001.l1001.c085.ash6",
                    "calls": [c.to_dict() for c in payload],
                }
            )

        self.assertEqual(driver.get_bgp_table_length.call_count, 4)
        # flap method called once. Note: nested tuples deep-convert to lists
        # through to_dict()/from_dict() (matching the JSON round-trip the
        # factory does in production). The driver accepts a list — its body
        # does `" ".join(interface_names)` which works on either.
        flap = driver.async_do_rapid_interface_flaps
        self.assertEqual(flap.call_count, 1)
        flap.assert_called_once_with(["eth1/1/1"], 1, 2)
        burst = next(iter(self.task._data.values()))
        self.assertEqual(burst["total"], 5)
        self.assertEqual(burst["success"], 5)
        self.assertEqual(burst["failures"], 0)

    # ---- Legacy apis-shape path ------------------------------------------

    async def test_legacy_apis_shape_still_works(self) -> None:
        """Backwards-compat: `apis` + `requests_per_api` builds default calls."""
        driver = _make_fboss_driver()
        with patch(
            f"{PERIODIC_TASKS_PATH}.async_get_device_driver",
            AsyncMock(return_value=driver),
        ):
            await self.task.run(
                {
                    "hostname": "gtsw001.l1001.c085.ash6",
                    "apis": [
                        "async_get_fib_table_entries_count",
                        "get_bgp_table_length",
                    ],
                    "requests_per_api": 3,
                }
            )

        self.assertEqual(driver.async_get_fib_table_entries_count.call_count, 3)
        self.assertEqual(driver.get_bgp_table_length.call_count, 3)
        burst = next(iter(self.task._data.values()))
        self.assertEqual(burst["total"], 6)

    async def test_default_baseline_when_no_calls_or_apis(self) -> None:
        """No `calls`, no `apis` -> default to READ_ONLY_FBOSS_APIS x requests_per_api."""
        driver = _make_fboss_driver()
        with patch(
            f"{PERIODIC_TASKS_PATH}.async_get_device_driver",
            AsyncMock(return_value=driver),
        ):
            await self.task.run(
                {
                    "hostname": "gtsw001.l1001.c085.ash6",
                    "requests_per_api": 2,
                }
            )

        # 7 APIs * 2 = 14
        burst = next(iter(self.task._data.values()))
        self.assertEqual(burst["total"], 14)

    # ---- Error / skip behavior -------------------------------------------

    async def test_iscoroutinefunction_filters_non_async_methods(self) -> None:
        """Sync methods and missing methods both get filtered with a warning."""
        # Build a driver where one named method is a SYNC (not async) callable.
        driver = MagicMock(
            spec=["async_get_fib_table_entries_count", "sync_method_oops"]
        )
        driver.__class__.__name__ = "FbossSwitch"
        driver.async_get_fib_table_entries_count = AsyncMock(return_value=1)
        driver.sync_method_oops = MagicMock(return_value=1)  # sync — should skip

        with patch(
            f"{PERIODIC_TASKS_PATH}.async_get_device_driver",
            AsyncMock(return_value=driver),
        ):
            await self.task.run(
                {
                    "hostname": "gtsw001.l1001.c085.ash6",
                    "calls": [
                        ThriftStressCall(
                            "async_get_fib_table_entries_count",
                            requests_per_burst=2,
                        ).to_dict(),
                        ThriftStressCall(
                            "sync_method_oops", requests_per_burst=5
                        ).to_dict(),
                        ThriftStressCall(
                            "nonexistent_api", requests_per_burst=5
                        ).to_dict(),
                    ],
                }
            )

        # Only the async one should have run.
        burst = next(iter(self.task._data.values()))
        self.assertEqual(burst["total"], 2)
        self.assertEqual(driver.async_get_fib_table_entries_count.call_count, 2)
        self.assertEqual(driver.sync_method_oops.call_count, 0)
        # Warning should mention both skipped names.
        warnings_text = " ".join(
            str(call) for call in self.logger.warning.call_args_list
        )
        self.assertIn("sync_method_oops", warnings_text)
        self.assertIn("nonexistent_api", warnings_text)

    async def test_exceptions_counted_as_failures_not_raised(self) -> None:
        """An API that raises should be counted in failures, not propagated."""
        driver = _make_fboss_driver()
        driver.get_bgp_table_length = AsyncMock(
            side_effect=RuntimeError("thrift channel closed")
        )
        with patch(
            f"{PERIODIC_TASKS_PATH}.async_get_device_driver",
            AsyncMock(return_value=driver),
        ):
            await self.task.run(
                {
                    "hostname": "gtsw001.l1001.c085.ash6",
                    "requests_per_api": 2,  # uses default baseline
                }
            )

        burst = next(iter(self.task._data.values()))
        # 7 APIs * 2 = 14; 2 of them (get_bgp_table_length pair) raise.
        self.assertEqual(burst["total"], 14)
        self.assertEqual(burst["success"], 12)
        self.assertEqual(burst["failures"], 2)

    async def test_driver_failure_logs_and_returns(self) -> None:
        """If driver acquisition fails, run() should log and return cleanly."""
        with patch(
            f"{PERIODIC_TASKS_PATH}.async_get_device_driver",
            AsyncMock(side_effect=ConnectionError("device unreachable")),
        ):
            await self.task.run(
                {
                    "hostname": "gtsw001.l1001.c085.ash6",
                    "requests_per_api": 100,
                }
            )

        self.assertEqual(len(self.task._data), 0)
        self.logger.error.assert_called_once()

    # ---- Final check -----------------------------------------------------

    async def test_final_check_skip_when_no_data(self) -> None:
        result = await self.task.run_final_check()
        assert result is not None  # narrows Optional for type-check
        self.assertEqual(result.status, hc_types.HealthCheckStatus.SKIP)

    async def test_final_check_aggregates_across_bursts_and_passes(self) -> None:
        """run_final_check aggregates totals and returns PASS unconditionally."""
        self.task.add_data(
            {"total": 100, "success": 100, "failures": 0, "elapsed_s": 2.0},
            timestamp=1000,
        )
        self.task.add_data(
            {"total": 100, "success": 95, "failures": 5, "elapsed_s": 2.5},
            timestamp=1010,
        )
        self.task.add_data(
            {"total": 100, "success": 100, "failures": 0, "elapsed_s": 1.8},
            timestamp=1020,
        )

        result = await self.task.run_final_check()
        assert result is not None  # narrows Optional for type-check
        # PASS even with exceptions — by design.
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)
        self.assertIn("3 bursts", result.message)
        self.assertIn("300 total calls", result.message)
        self.assertIn("295 ok", result.message)
        self.assertIn("5 exceptions", result.message)

    async def test_burst_timeout_records_timed_out_burst(self) -> None:
        """If gather() exceeds burst_timeout_s, we cancel + log + record + return."""
        driver = _make_fboss_driver()

        # Make every API call hang forever to force a timeout.
        async def _hang(*args, **kwargs):
            await asyncio.sleep(3600)  # well past the test's 1s timeout

        for api_name in [c.method for c in READ_ONLY_FBOSS_APIS]:
            setattr(driver, api_name, AsyncMock(side_effect=_hang))

        with patch(
            f"{PERIODIC_TASKS_PATH}.async_get_device_driver",
            AsyncMock(return_value=driver),
        ):
            await self.task.run(
                {
                    "hostname": "gtsw001.l1001.c085.ash6",
                    "requests_per_api": 3,
                    "burst_timeout_s": 1.0,  # 1 second
                }
            )

        # One burst recorded, fully timed-out
        self.assertEqual(len(self.task._data), 1)
        burst = next(iter(self.task._data.values()))
        # 7 APIs * 3 = 21 coros, all hung -> 21 timed_out, 0 success
        self.assertEqual(burst["total"], 21)
        self.assertEqual(burst["timed_out"], 21)
        self.assertEqual(burst["success"], 0)
        self.assertEqual(burst["failures"], 0)
        # A loud WARNING was emitted for the timeout
        warning_calls = [
            call
            for call in self.logger.warning.call_args_list
            if "TIMED OUT" in str(call)
        ]
        self.assertTrue(warning_calls, "expected TIMED OUT warning")
