# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
import time
import typing as t
import unittest
from unittest.mock import AsyncMock, MagicMock

from taac.libs.collectors.systemd_state_collector import (
    SystemdStateCollector,
    SystemdStateSample,
    SystemdUnitState,
    UNCLEAN_SYSTEMD_RESULTS,
)


def _make_driver(state_by_service: t.Dict[str, t.Dict[str, str]]) -> MagicMock:
    """Return a driver whose ``async_run_cmd_on_shell`` produces a batched
    ``systemctl show`` output — one blank-line-separated block per unit named
    in the command, keyed back to its unit via ``Id`` (matches the base
    class's block-matching contract). Each service maps to the property
    dict it will report; a missing service is reported as not-found/inactive.
    """
    driver = MagicMock()

    async def _run(cmd: str) -> str:
        units = cmd.split("systemctl show ", 1)[1].split(" -p ")[0].split()
        blocks = []
        for unit in units:
            props = state_by_service.get(unit)
            if props is None:
                blocks.append(
                    f"Id={unit}.service\nLoadState=not-found\n"
                    f"ActiveState=inactive"
                )
                continue
            body = "\n".join(f"{k}={v}" for k, v in props.items())
            blocks.append(f"Id={unit}.service\n{body}")
        return "\n\n".join(blocks)

    driver.async_run_cmd_on_shell = AsyncMock(side_effect=_run)
    return driver


def _healthy(active_enter_ts: str = "1000", n_restarts: str = "0") -> t.Dict[str, str]:
    return {
        "LoadState": "loaded",
        "ActiveState": "active",
        "Result": "success",
        "UnitFileState": "enabled",
        "ActiveEnterTimestampMonotonic": active_enter_ts,
        "NRestarts": n_restarts,
    }


def _unclean(
    result: str = "core-dump",
    active_state: str = "active",
    n_restarts: str = "1",
    active_enter_ts: str = "2000",
) -> t.Dict[str, str]:
    return {
        "LoadState": "loaded",
        "ActiveState": active_state,
        "Result": result,
        "UnitFileState": "enabled",
        "ActiveEnterTimestampMonotonic": active_enter_ts,
        "NRestarts": n_restarts,
    }


class TestSystemdUnitState(unittest.TestCase):
    def test_result_based_unclean(self) -> None:
        for result in UNCLEAN_SYSTEMD_RESULTS:
            self.assertTrue(
                SystemdUnitState(result=result, active_state="active").is_unclean,
                msg=f"Result={result} should be unclean",
            )

    def test_active_state_failed_is_unclean(self) -> None:
        self.assertTrue(
            SystemdUnitState(result="success", active_state="failed").is_unclean
        )

    def test_healthy_is_not_unclean(self) -> None:
        self.assertFalse(
            SystemdUnitState(result="success", active_state="active").is_unclean
        )

    def test_none_fields_are_not_unclean(self) -> None:
        # All-None sample = no signal; must not report as unclean or the
        # check would false-fail on the very first poll before any data arrives.
        self.assertFalse(SystemdUnitState().is_unclean)


class TestSystemdStateCollector(unittest.IsolatedAsyncioTestCase):
    async def test_poll_populates_all_fields(self) -> None:
        driver = _make_driver({"bgpd": _healthy(active_enter_ts="12345", n_restarts="3")})
        collector = SystemdStateCollector(
            driver=driver, services=["bgpd"], host="dut1", tmp_path="/dev/null"
        )
        await collector._poll_once()
        self.assertEqual(len(collector.rows), 1)
        state = collector.rows[0].per_service["bgpd"]
        self.assertEqual(state.load_state, "loaded")
        self.assertEqual(state.active_state, "active")
        self.assertEqual(state.result, "success")
        self.assertEqual(state.unit_file_state, "enabled")
        self.assertEqual(state.active_enter_ts, 12345)
        self.assertEqual(state.n_restarts, 3)

    async def test_poll_tolerates_missing_optional_properties(self) -> None:
        driver = _make_driver(
            {
                "bgpd": {
                    "LoadState": "loaded",
                    "ActiveState": "active",
                    "Result": "success",
                    # No ActiveEnterTimestampMonotonic, no NRestarts.
                }
            }
        )
        collector = SystemdStateCollector(
            driver=driver, services=["bgpd"], host="dut1", tmp_path="/dev/null"
        )
        await collector._poll_once()
        state = collector.rows[0].per_service["bgpd"]
        self.assertEqual(state.active_state, "active")
        self.assertIsNone(state.active_enter_ts)
        self.assertIsNone(state.n_restarts)

    async def test_poll_records_inactive_service_state(self) -> None:
        """Unlike CPU/memory, an inactive service produces a real
        ``SystemdUnitState`` (rather than ``None``): the inactive state IS
        the signal for the checks that consume this collector. The subclass
        disables the base's ``_SKIP_INACTIVE_UNITS`` filter — this exercises
        that override end-to-end."""
        driver = _make_driver({"bgpd": _healthy()})  # fsdb is not-found
        collector = SystemdStateCollector(
            driver=driver,
            services=["bgpd", "fsdb"],
            host="dut1",
            tmp_path="/dev/null",
        )
        await collector._poll_once()
        per_service = collector.rows[0].per_service
        self.assertIsInstance(per_service["bgpd"], SystemdUnitState)
        # fsdb's not-found/inactive state is recorded, not filtered away.
        fsdb_state = per_service["fsdb"]
        self.assertIsInstance(fsdb_state, SystemdUnitState)
        self.assertEqual(fsdb_state.load_state, "not-found")
        self.assertEqual(fsdb_state.active_state, "inactive")

    async def test_poll_records_failed_active_state(self) -> None:
        """Regression guard for the base class ``_SKIP_INACTIVE_UNITS``
        filter: a service whose ``ActiveState`` is ``failed`` must land in
        ``per_service`` as a real ``SystemdUnitState``. Prior to
        ``_SKIP_INACTIVE_UNITS = False`` on this subclass, the base filtered
        out every not-``active`` unit, so ``unclean_samples_in_window``
        silently returned nothing on a real ``systemctl show`` — the exact
        crash-then-recover signal the collector exists to catch."""
        driver = _make_driver(
            {
                "bgpd": {
                    "LoadState": "loaded",
                    "ActiveState": "failed",
                    "Result": "core-dump",
                    "UnitFileState": "enabled",
                    "ActiveEnterTimestampMonotonic": "12345",
                    "NRestarts": "1",
                }
            }
        )
        collector = SystemdStateCollector(
            driver=driver, services=["bgpd"], host="dut1", tmp_path="/dev/null"
        )
        await collector._poll_once()
        state = collector.rows[0].per_service["bgpd"]
        self.assertIsInstance(state, SystemdUnitState)
        self.assertEqual(state.active_state, "failed")
        self.assertEqual(state.result, "core-dump")
        self.assertTrue(state.is_unclean)
        # And the query API surfaces it.
        events = collector.unclean_samples_in_window(0, 1e12)
        self.assertEqual([e[0] for e in events], ["bgpd"])
        self.assertEqual([e[2] for e in events], ["core-dump"])

    def _fake_row(
        self,
        epoch: float,
        per_service: t.Dict[str, SystemdUnitState],
        timestamp: t.Optional[str] = None,
    ) -> SystemdStateSample:
        return SystemdStateSample(
            timestamp=timestamp or f"ts@{epoch:.0f}",
            epoch=epoch,
            per_service=per_service,
        )

    def test_unclean_samples_in_window_empty(self) -> None:
        collector = SystemdStateCollector(
            driver=MagicMock(),
            services=["bgpd"],
            host="dut1",
            tmp_path="/dev/null",
        )
        self.assertEqual(collector.unclean_samples_in_window(0, 100), [])

    def test_unclean_samples_in_window_reports_result(self) -> None:
        collector = SystemdStateCollector(
            driver=MagicMock(),
            services=["bgpd"],
            host="dut1",
            tmp_path="/dev/null",
        )
        collector.rows = [
            self._fake_row(
                10, {"bgpd": SystemdUnitState(result="core-dump", active_state="active")}
            )
        ]
        events = collector.unclean_samples_in_window(0, 100)
        self.assertEqual(events, [("bgpd", "ts@10", "core-dump")])

    def test_unclean_samples_in_window_reports_failed_state(self) -> None:
        collector = SystemdStateCollector(
            driver=MagicMock(),
            services=["bgpd"],
            host="dut1",
            tmp_path="/dev/null",
        )
        collector.rows = [
            self._fake_row(
                10, {"bgpd": SystemdUnitState(result="success", active_state="failed")}
            )
        ]
        events = collector.unclean_samples_in_window(0, 100)
        self.assertEqual(events, [("bgpd", "ts@10", "active-state:failed")])

    def test_unclean_samples_respects_services_filter(self) -> None:
        collector = SystemdStateCollector(
            driver=MagicMock(),
            services=["bgpd", "fsdb"],
            host="dut1",
            tmp_path="/dev/null",
        )
        collector.rows = [
            self._fake_row(
                10,
                {
                    "bgpd": SystemdUnitState(result="core-dump", active_state="active"),
                    "fsdb": SystemdUnitState(result="oom-kill", active_state="active"),
                },
            )
        ]
        # Only bgpd requested → fsdb's oom-kill is not reported.
        events = collector.unclean_samples_in_window(0, 100, services=["bgpd"])
        self.assertEqual([e[0] for e in events], ["bgpd"])

    def test_unclean_samples_window_bounds(self) -> None:
        collector = SystemdStateCollector(
            driver=MagicMock(),
            services=["bgpd"],
            host="dut1",
            tmp_path="/dev/null",
        )
        # Row @ epoch 5 is BEFORE the window [10, 20]; row @ 15 is inside.
        collector.rows = [
            self._fake_row(
                5, {"bgpd": SystemdUnitState(result="core-dump", active_state="active")}
            ),
            self._fake_row(
                15, {"bgpd": SystemdUnitState(result="watchdog", active_state="active")}
            ),
        ]
        events = collector.unclean_samples_in_window(10, 20)
        self.assertEqual(events, [("bgpd", "ts@15", "watchdog")])

    def test_services_ever_inactive_captures_first_bad_state(self) -> None:
        collector = SystemdStateCollector(
            driver=MagicMock(),
            services=["bgpd"],
            host="dut1",
            tmp_path="/dev/null",
        )
        collector.rows = [
            self._fake_row(1, {"bgpd": SystemdUnitState(active_state="active")}),
            self._fake_row(2, {"bgpd": SystemdUnitState(active_state="deactivating")}),
            self._fake_row(3, {"bgpd": SystemdUnitState(active_state="failed")}),
        ]
        self.assertEqual(
            collector.services_ever_inactive_in_window(0, 100), {"bgpd": "deactivating"}
        )

    def test_services_ever_inactive_skips_disabled_by_default(self) -> None:
        """A service that samples as UnitFileState=disabled must NOT be
        flagged — an intentionally-disabled unit is not an outage.
        Matches the semantics the pre-collector per-service SSH path used."""
        collector = SystemdStateCollector(
            driver=MagicMock(),
            services=["coop"],
            host="dut1",
            tmp_path="/dev/null",
        )
        collector.rows = [
            self._fake_row(
                1,
                {
                    "coop": SystemdUnitState(
                        load_state="loaded",
                        active_state="inactive",
                        unit_file_state="disabled",
                    )
                },
            )
        ]
        self.assertEqual(collector.services_ever_inactive_in_window(0, 100), {})
        # With the filter off, the service DOES surface (opt-in strict).
        self.assertEqual(
            collector.services_ever_inactive_in_window(
                0, 100, skip_disabled=False
            ),
            {"coop": "inactive"},
        )

    def test_services_ever_inactive_skips_not_loaded_by_default(self) -> None:
        """A unit that isn't present on this DUT image (LoadState=not-found)
        must NOT be flagged — matches the legacy per-service SSH path's
        behavior of returning ``True`` for absent units."""
        collector = SystemdStateCollector(
            driver=MagicMock(),
            services=["openr"],
            host="dut1",
            tmp_path="/dev/null",
        )
        collector.rows = [
            self._fake_row(
                1,
                {
                    "openr": SystemdUnitState(
                        load_state="not-found",
                        active_state="inactive",
                    )
                },
            )
        ]
        self.assertEqual(collector.services_ever_inactive_in_window(0, 100), {})
        self.assertEqual(
            collector.services_ever_inactive_in_window(
                0, 100, skip_not_loaded=False
            ),
            {"openr": "inactive"},
        )

    async def test_services_ever_inactive_end_to_end(self) -> None:
        """Regression: exercise the whole ``_poll_once → services_ever_inactive``
        path. Guards against a future base-class change silently re-enabling
        the LoadState/ActiveState filter that would swallow the very signal
        this query exists to surface."""
        driver = _make_driver(
            {
                "bgpd": _healthy(),
                # fsdb is currently active-but-with-a-failed-Result — not the
                # main scenario, but ActiveState=activating is what a real
                # DUT looks like mid-restart. Distinct from `active`, so
                # services_ever_inactive_in_window should surface it.
                "fsdb": {
                    "LoadState": "loaded",
                    "ActiveState": "activating",
                    "Result": "success",
                    "UnitFileState": "enabled",
                    "ActiveEnterTimestampMonotonic": "999",
                    "NRestarts": "0",
                },
            }
        )
        collector = SystemdStateCollector(
            driver=driver,
            services=["bgpd", "fsdb"],
            host="dut1",
            tmp_path="/dev/null",
        )
        await collector._poll_once()
        # Populate epoch on the row so the window query picks it up.
        collector.rows[-1].epoch = 50.0
        self.assertEqual(
            collector.services_ever_inactive_in_window(0, 100),
            {"fsdb": "activating"},
        )

    def test_services_ever_inactive_late_disabled_does_not_erase_earlier_flap(
        self,
    ) -> None:
        """Regression guard for the reviewer's finding: a service that
        samples as ``failed`` early and then gets disabled/masked later in
        the window must still surface. The previous ``skip.add + pop``
        implementation deleted the recorded flap when the later
        ``disabled`` sample arrived, silently PASSing a real outage."""
        collector = SystemdStateCollector(
            driver=MagicMock(),
            services=["bgpd"],
            host="dut1",
            tmp_path="/dev/null",
        )
        collector.rows = [
            self._fake_row(
                1,
                {
                    "bgpd": SystemdUnitState(
                        load_state="loaded",
                        unit_file_state="enabled",
                        active_state="failed",
                    )
                },
            ),
            self._fake_row(
                3,
                {
                    "bgpd": SystemdUnitState(
                        load_state="loaded",
                        unit_file_state="disabled",
                        active_state="inactive",
                    )
                },
            ),
        ]
        self.assertEqual(
            collector.services_ever_inactive_in_window(0, 100),
            {"bgpd": "failed"},
        )

    def test_services_ever_inactive_early_not_loaded_does_not_veto_later_flap(
        self,
    ) -> None:
        """The likelier direction of the same class of bug: a service that
        isn't loaded at the first poll (brought up mid-playbook, or
        started later than the collector) must not have its subsequent
        flaps silently exempted. The previous implementation set a
        persistent ``skip`` flag on the first not-loaded sample."""
        collector = SystemdStateCollector(
            driver=MagicMock(),
            services=["bgpd"],
            host="dut1",
            tmp_path="/dev/null",
        )
        collector.rows = [
            self._fake_row(1, {"bgpd": SystemdUnitState(load_state="not-found")}),
            self._fake_row(
                2,
                {
                    "bgpd": SystemdUnitState(
                        load_state="loaded",
                        unit_file_state="enabled",
                        active_state="failed",
                    )
                },
            ),
            self._fake_row(
                3,
                {
                    "bgpd": SystemdUnitState(
                        load_state="loaded",
                        unit_file_state="enabled",
                        active_state="failed",
                    )
                },
            ),
        ]
        self.assertEqual(
            collector.services_ever_inactive_in_window(0, 100),
            {"bgpd": "failed"},
        )

    def test_services_not_active_at_end_final_sample_wins(self) -> None:
        """``services_not_active_at_end`` reports services whose LAST
        in-window sample is non-active — used by checks that allow-list
        an intentional restart to still verify recovery. A transient
        ``deactivating`` earlier in the window must NOT surface here
        (that's what ``services_ever_inactive_in_window`` is for)."""
        collector = SystemdStateCollector(
            driver=MagicMock(),
            services=["fboss_sw_agent"],
            host="dut1",
            tmp_path="/dev/null",
        )
        collector.rows = [
            self._fake_row(
                1,
                {
                    "fboss_sw_agent": SystemdUnitState(
                        load_state="loaded",
                        active_state="deactivating",
                    )
                },
            ),
            self._fake_row(
                3,
                {
                    "fboss_sw_agent": SystemdUnitState(
                        load_state="loaded",
                        active_state="active",
                    )
                },
            ),
        ]
        # Ends active — no failure surfaced despite the transient.
        self.assertEqual(
            collector.services_not_active_at_end(0, 100), {}
        )

    def test_services_not_active_at_end_reports_stuck_final_state(self) -> None:
        """If the last sample is not ``active`` — the intentionally-
        restarted service never came back — the check MUST surface it."""
        collector = SystemdStateCollector(
            driver=MagicMock(),
            services=["fboss_sw_agent"],
            host="dut1",
            tmp_path="/dev/null",
        )
        collector.rows = [
            self._fake_row(
                1,
                {
                    "fboss_sw_agent": SystemdUnitState(
                        load_state="loaded",
                        active_state="deactivating",
                    )
                },
            ),
            self._fake_row(
                3,
                {
                    "fboss_sw_agent": SystemdUnitState(
                        load_state="loaded",
                        active_state="failed",
                    )
                },
            ),
        ]
        self.assertEqual(
            collector.services_not_active_at_end(0, 100),
            {"fboss_sw_agent": "failed"},
        )

    def test_services_not_active_at_end_skips_disabled_final(self) -> None:
        """A service whose final state is ``disabled`` has nothing to
        recover to — must not FAIL here."""
        collector = SystemdStateCollector(
            driver=MagicMock(),
            services=["coop"],
            host="dut1",
            tmp_path="/dev/null",
        )
        collector.rows = [
            self._fake_row(
                1,
                {
                    "coop": SystemdUnitState(
                        load_state="loaded",
                        unit_file_state="disabled",
                        active_state="inactive",
                    )
                },
            ),
        ]
        self.assertEqual(collector.services_not_active_at_end(0, 100), {})

    def test_services_ever_inactive_ignores_healthy_series(self) -> None:
        collector = SystemdStateCollector(
            driver=MagicMock(),
            services=["bgpd"],
            host="dut1",
            tmp_path="/dev/null",
        )
        collector.rows = [
            self._fake_row(1, {"bgpd": SystemdUnitState(active_state="active")}),
            self._fake_row(2, {"bgpd": SystemdUnitState(active_state="active")}),
        ]
        self.assertEqual(collector.services_ever_inactive_in_window(0, 100), {})

    def test_services_restarted_detects_n_restarts_bump(self) -> None:
        collector = SystemdStateCollector(
            driver=MagicMock(),
            services=["bgpd"],
            host="dut1",
            tmp_path="/dev/null",
        )
        collector.rows = [
            self._fake_row(
                1, {"bgpd": SystemdUnitState(n_restarts=0, active_enter_ts=1000)}
            ),
            self._fake_row(
                2, {"bgpd": SystemdUnitState(n_restarts=1, active_enter_ts=2000)}
            ),
        ]
        result = collector.services_restarted_in_window(0, 100)
        self.assertEqual(result, {"bgpd": (1, 1)})

    def test_services_restarted_detects_aet_change_alone(self) -> None:
        """Warmboot-style: NRestarts stays 0, but ActiveEnterTimestamp
        changes — that's still a restart signal we care about."""
        collector = SystemdStateCollector(
            driver=MagicMock(),
            services=["fboss_sw_agent"],
            host="dut1",
            tmp_path="/dev/null",
        )
        collector.rows = [
            self._fake_row(
                1,
                {
                    "fboss_sw_agent": SystemdUnitState(
                        n_restarts=0, active_enter_ts=1000
                    )
                },
            ),
            self._fake_row(
                2,
                {
                    "fboss_sw_agent": SystemdUnitState(
                        n_restarts=0, active_enter_ts=5000
                    )
                },
            ),
        ]
        result = collector.services_restarted_in_window(0, 100)
        self.assertEqual(result, {"fboss_sw_agent": (0, 1)})

    def test_services_restarted_skips_disabled_by_default(self) -> None:
        """A disabled service can't be running to restart — its restart-
        indicator fields must NOT be reported. Mirrors the filter added on
        services_ever_inactive_in_window."""
        collector = SystemdStateCollector(
            driver=MagicMock(),
            services=["coop"],
            host="dut1",
            tmp_path="/dev/null",
        )
        collector.rows = [
            self._fake_row(
                1,
                {
                    "coop": SystemdUnitState(
                        load_state="loaded",
                        active_state="active",
                        unit_file_state="disabled",
                        n_restarts=0,
                        active_enter_ts=1000,
                    )
                },
            ),
            self._fake_row(
                2,
                {
                    "coop": SystemdUnitState(
                        load_state="loaded",
                        active_state="active",
                        unit_file_state="disabled",
                        n_restarts=1,
                        active_enter_ts=5000,
                    )
                },
            ),
        ]
        self.assertEqual(collector.services_restarted_in_window(0, 100), {})
        # With the filter off, the restart DOES surface.
        self.assertEqual(
            collector.services_restarted_in_window(0, 100, skip_disabled=False),
            {"coop": (1, 1)},
        )

    def test_services_restarted_late_disabled_does_not_erase_earlier_restart(
        self,
    ) -> None:
        """Mirror of the ``services_ever_inactive`` regression guard: a
        real NRestarts / AET bump captured from loaded+enabled samples
        must NOT be erased by a later disabled / not-loaded sample."""
        collector = SystemdStateCollector(
            driver=MagicMock(),
            services=["bgpd"],
            host="dut1",
            tmp_path="/dev/null",
        )
        collector.rows = [
            self._fake_row(
                1,
                {
                    "bgpd": SystemdUnitState(
                        load_state="loaded",
                        unit_file_state="enabled",
                        n_restarts=0,
                        active_enter_ts=1000,
                    )
                },
            ),
            self._fake_row(
                2,
                {
                    "bgpd": SystemdUnitState(
                        load_state="loaded",
                        unit_file_state="enabled",
                        n_restarts=3,
                        active_enter_ts=9000,
                    )
                },
            ),
            self._fake_row(
                3,
                {
                    "bgpd": SystemdUnitState(
                        load_state="loaded",
                        unit_file_state="disabled",
                        n_restarts=3,
                        active_enter_ts=9000,
                    )
                },
            ),
        ]
        # NRestarts bumped from 0→3 and AET changed 1000→9000, so restart
        # is real — must surface despite the late disabled sample.
        self.assertEqual(
            collector.services_restarted_in_window(0, 100),
            {"bgpd": (3, 1)},
        )

    def test_services_restarted_skips_not_loaded_by_default(self) -> None:
        """A unit that isn't present on the DUT image can't restart —
        its fields must not be reported."""
        collector = SystemdStateCollector(
            driver=MagicMock(),
            services=["openr"],
            host="dut1",
            tmp_path="/dev/null",
        )
        collector.rows = [
            self._fake_row(
                1,
                {
                    "openr": SystemdUnitState(
                        load_state="not-found",
                        n_restarts=0,
                        active_enter_ts=1000,
                    )
                },
            ),
            self._fake_row(
                2,
                {
                    "openr": SystemdUnitState(
                        load_state="not-found",
                        n_restarts=1,
                        active_enter_ts=9000,
                    )
                },
            ),
        ]
        self.assertEqual(collector.services_restarted_in_window(0, 100), {})
        self.assertEqual(
            collector.services_restarted_in_window(0, 100, skip_not_loaded=False),
            {"openr": (1, 1)},
        )

    def test_services_restarted_empty_when_stable(self) -> None:
        collector = SystemdStateCollector(
            driver=MagicMock(),
            services=["bgpd"],
            host="dut1",
            tmp_path="/dev/null",
        )
        collector.rows = [
            self._fake_row(
                1, {"bgpd": SystemdUnitState(n_restarts=2, active_enter_ts=1000)}
            ),
            self._fake_row(
                2, {"bgpd": SystemdUnitState(n_restarts=2, active_enter_ts=1000)}
            ),
        ]
        self.assertEqual(collector.services_restarted_in_window(0, 100), {})

    async def test_poll_notes_carry_not_found_units(self) -> None:
        """A monitored unit that isn't installed on the DUT image must still
        show up in the row's ``notes`` field (``svc=not-found``) even though
        this subclass disables the base ``_SKIP_INACTIVE_UNITS`` filter — the
        annotation is the only trace of the missing-unit condition callers
        get from the ``.log``."""
        driver = _make_driver({"bgpd": _healthy()})  # ``coop`` is not-found
        collector = SystemdStateCollector(
            driver=driver,
            services=["bgpd", "coop"],
            host="dut1",
            tmp_path="/dev/null",
        )
        await collector._poll_once()
        self.assertIn("coop=not-found", collector.rows[0].notes)

    def test_services_ever_inactive_skips_not_loaded(self) -> None:
        """A unit that samples as ``LoadState=not-found`` throughout the
        window must NOT surface via ``services_ever_inactive_in_window`` —
        the caller's default ``services`` list can overspecify (includes
        units many OSS FBOSS images don't ship), and reporting the
        never-present state as an outage would false-fail every image."""
        collector = SystemdStateCollector(
            driver=MagicMock(),
            services=["coop"],
            host="dut1",
            tmp_path="/dev/null",
        )
        collector.rows = [
            self._fake_row(
                1,
                {
                    "coop": SystemdUnitState(
                        load_state="not-found", active_state="inactive"
                    )
                },
            ),
        ]
        self.assertEqual(
            collector.services_ever_inactive_in_window(0, 100), {}
        )

    def test_services_restarted_skips_not_loaded_from_query(self) -> None:
        """Regression guard mirroring
        ``test_services_ever_inactive_skips_not_loaded``: a not-loaded unit
        must not contribute a first/last state that later reads as a
        restart signal."""
        collector = SystemdStateCollector(
            driver=MagicMock(),
            services=["openr"],
            host="dut1",
            tmp_path="/dev/null",
        )
        collector.rows = [
            self._fake_row(
                1,
                {
                    "openr": SystemdUnitState(
                        load_state="not-found",
                        n_restarts=0,
                        active_enter_ts=1000,
                    )
                },
            ),
            self._fake_row(
                2,
                {
                    "openr": SystemdUnitState(
                        load_state="not-found",
                        n_restarts=1,
                        active_enter_ts=9000,
                    )
                },
            ),
        ]
        self.assertEqual(collector.services_restarted_in_window(0, 100), {})

    async def test_batched_poll_matches_units_by_id(self) -> None:
        """One SSH call requests all units; blocks come back keyed by Id."""
        driver = _make_driver(
            {"bgpd": _healthy(), "fsdb": _healthy(n_restarts="5")}
        )
        collector = SystemdStateCollector(
            driver=driver,
            services=["bgpd", "fsdb"],
            host="dut1",
            tmp_path="/dev/null",
        )
        await collector._poll_once()
        # One call, both units on the command line.
        self.assertEqual(driver.async_run_cmd_on_shell.await_count, 1)
        cmd = driver.async_run_cmd_on_shell.await_args.args[0]
        self.assertIn("bgpd", cmd)
        self.assertIn("fsdb", cmd)
        # Both parse into their own SystemdUnitState.
        per_service = collector.rows[0].per_service
        self.assertEqual(per_service["bgpd"].n_restarts, 0)
        self.assertEqual(per_service["fsdb"].n_restarts, 5)


if __name__ == "__main__":
    unittest.main()
