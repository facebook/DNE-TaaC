# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe
import asyncio
import contextlib
import ipaddress
import json
import time
import typing as t
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from facebook.network.Address.types import BinaryAddress
from neteng.fboss.ctrl.types import NdpEntryThrift
from taac.constants import (  # oss-rewrite (force ShipIt re-export to taac.* root)
    TestCaseFailure,
    TestDevice,
    TestTopology,
)
from taac.driver.driver_constants import (
    SwitchLldpData,
    SystemctlServiceStatus,
)
from taac.internal.steps.custom_step import (
    _nic_mstreg_bdf,
    CustomStep,
)
from taac.libs.fpf.fpf_collector_registry import (
    clear_drain_mutations,
    get_drain_mutation,
    mark_drain_mutation,
)
from taac.libs.parameter_evaluator import ParameterEvaluator
from taac.steps.step_definitions import (
    create_fpf_conditional_undrain_step,
    create_fpf_drain_interface_step,
    create_fpf_gar_set_links_step,
    create_fpf_gar_validate_step,
    create_fpf_lldp_batched_set_interface_admin_step,
    create_fpf_multi_gtsw_rapid_flap_step,
    create_fpf_ndp_clear_loop_step,
    create_fpf_nic_mstreg_flap_step,
    create_fpf_rapid_flap_step,
    create_fpf_rapid_flap_step_lldp,
    create_fpf_repeated_service_crash_step,
    create_fpf_repeated_sw_hw_agent_crash_step,
    create_fpf_stsw_drain_and_reinject_steps,
    create_fpf_verify_recovered_state_step,
)
from taac.test_as_a_config.types import Service, Step, StepName, TestConfig


def _make_custom_step(hostname: str = "gtsw001.l1001.c085.ash6") -> CustomStep:
    """Build a CustomStep wired with a mocked driver (no real DUT)."""
    device = MagicMock(spec=TestDevice)
    device.name = hostname
    attributes = MagicMock()
    attributes.operating_system = "FBOSS"
    attributes.role = ""
    attributes.device_name = hostname
    attributes.hardware = ""
    attributes.ai_zone = ""
    device.attributes = attributes

    cs = CustomStep(
        name="step",
        device=device,
        topology=MagicMock(spec=TestTopology),
        test_case_results=[],
        test_config=MagicMock(spec=TestConfig),
        test_case_name="case",
        test_case_start_time=time.time(),
        parameter_evaluator=MagicMock(spec=ParameterEvaluator),
        step=MagicMock(spec=Step),
    )
    cs.hostname = hostname
    cs.driver = AsyncMock()
    cs.logger = MagicMock()
    return cs


def _driver_mock(custom_step: CustomStep) -> AsyncMock:
    """Expose the concrete test double behind CustomStep's driver interface."""
    return t.cast(AsyncMock, custom_step.driver)


def _params(step: Step) -> dict:
    # `step.step_params` and `.json_params` are typed as Optional in the
    # generated Thrift; assert both exist in test context (factories always
    # populate them).
    assert step.step_params is not None
    assert step.step_params.json_params is not None
    return json.loads(step.step_params.json_params)


class TestFpfRecoveredStateGate(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _timestamp(epoch: float) -> str:
        return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S.%f%z"
        )

    def _collectors(self) -> dict[str, MagicMock]:
        now = time.strftime("%Y-%m-%d %H:%M:%S.000%z")
        hosts = ["server", "client"]
        device_ids = [0, 1]
        local_planes = [0, 1, 2, 3]

        def rows(**kwargs):
            return [SimpleNamespace(timestamp=now, valid=True, notes="", **kwargs)]

        bulk = MagicMock()
        bulk.rows = [
            row
            for host in hosts
            for device_id in device_ids
            for row in rows(
                host=host,
                device_id=device_id,
                lane_counts=[4032, 4032, 4032, 4032],
                plane_ids=local_planes,
            )
        ]
        plane = MagicMock()
        plane.rows = [
            row
            for host in hosts
            for device_id in device_ids
            for row in rows(
                host=host,
                device_id=device_id,
                plane_states={0: "UP", 1: "UP", 2: "UP", 3: "UP"},
            )
        ]
        sessions = MagicMock()
        sessions.rows = [row for host in hosts for row in rows(host=host, connected=32)]
        remote_vf1 = MagicMock()
        remote_vf1.rows = [
            row
            for host in hosts
            for row in rows(
                host=host,
                device_id=0,
                lane_counts=[0, 0, 0, 0],
                plane_ids=local_planes,
            )
        ]
        remote_vf2 = MagicMock()
        remote_vf2.rows = [
            row
            for host in hosts
            for row in rows(
                host=host,
                device_id=1,
                lane_counts=[0, 0, 0, 0],
                plane_ids=local_planes,
            )
        ]
        reachability = SimpleNamespace(
            device_ids=[0],
            reachable_planes=[0, 1, 2, 3],
            drained_planes=[],
            unreachable_planes=[],
            plane_up=[0, 1, 2, 3],
            plane_down=[],
        )
        prod = MagicMock()
        prod.rows = [
            row
            for host in hosts
            for row in rows(host=host, prefixes={"2401:db00::/64": reachability})
        ]
        collectors = {
            "hrt": bulk,
            "hrt_plane_status": plane,
            "hrt_fsdb_session": sessions,
            "hrt_remote_failure_vf1": remote_vf1,
            "hrt_remote_failure_vf2": remote_vf2,
            "prod_hrt_prefix": prod,
        }
        for collector in collectors.values():
            collector.POLL_TIMEOUT_SEC = 1.0
            collector.interval_sec = 0.1
        return collectors

    async def _verify(
        self,
        collectors: dict[str, MagicMock],
        params: dict,
        refresh: t.Optional[t.Callable[[], None]] = None,
        monotonic_side_effect: t.Optional[t.List[float]] = None,
    ) -> None:
        initial_rows = {
            name: tuple(collector.rows) for name, collector in collectors.items()
        }
        refreshed = False

        async def _refresh(_delay: float) -> None:
            nonlocal refreshed
            if refreshed:
                return
            refreshed = True
            if refresh is not None:
                refresh()
                return
            for name, collector in collectors.items():
                collector.rows.extend(initial_rows[name])

        patches = [
            patch(
                "neteng.test_infra.dne.taac.libs.fpf.fpf_collector_registry.get_collector",
                side_effect=collectors.get,
            ),
            patch(
                "neteng.test_infra.dne.taac.internal.steps.custom_step.asyncio.sleep",
                side_effect=_refresh,
            ),
        ]
        if monotonic_side_effect is not None:
            patches.append(
                patch(
                    "neteng.test_infra.dne.taac.internal.steps.custom_step.time.monotonic",
                    side_effect=monotonic_side_effect,
                )
            )
        with contextlib.ExitStack() as stack:
            for patcher in patches:
                stack.enter_context(patcher)
            await _make_custom_step().fpf_verify_recovered_state(params)

    def _params(self) -> dict:
        prod_expectation = {
            "device_ids": [0],
            "reachable_planes": [0, 1, 2, 3],
            "drained_planes": [],
            "unreachable_planes": [],
            "plane_up": [0, 1, 2, 3],
            "plane_down": [],
        }
        return {
            "device_planes_by_host": {
                host: {"0": [0, 1, 2, 3], "1": [0, 1, 2, 3]}
                for host in ("server", "client")
            },
            "expected_count": 4032,
            "expected_sessions": 32,
            "prod_prefix_expectations_by_host": {
                host: {"2401:db00::/64": prod_expectation}
                for host in ("server", "client")
            },
            "rf_vf_groups": [
                {"suffix": "vf1", "device_ids": [0], "lanes": [0, 1, 2, 3]},
                {"suffix": "vf2", "device_ids": [1], "lanes": [0, 1, 2, 3]},
            ],
            "max_age_sec": 30,
        }

    async def test_factory_and_exact_both_host_gate(self):
        params = self._params()
        step = create_fpf_verify_recovered_state_step(**params)
        self.assertEqual(
            _params(step)["custom_step_name"], "fpf_verify_recovered_state"
        )
        self.assertEqual(_params(step)["future_timestamp_grace_sec"], 1.0)
        collectors = self._collectors()
        await self._verify(collectors, params)

    async def test_post_gate_append_accepts_request_timestamp_36s_old(self):
        collectors = self._collectors()
        request_start = time.time() - 36.0
        for collector in collectors.values():
            for row in collector.rows:
                row.timestamp = self._timestamp(request_start)

        await self._verify(collectors, self._params())

    async def test_post_gate_refresh_timeout_reports_missing_keys_and_contract(self):
        collectors = self._collectors()

        with self.assertRaisesRegex(
            RuntimeError,
            "timed out.*hrt:client/dev0.*timeout1s\\+interval0.1s",
        ):
            await self._verify(
                collectors,
                self._params(),
                refresh=lambda: None,
                monotonic_side_effect=[0.0, 0.0, 3.0],
            )

    async def test_first_fresh_bad_row_fails_without_later_good_masking(self):
        collectors = self._collectors()
        initial_rows = {
            name: tuple(collector.rows) for name, collector in collectors.items()
        }

        def _append_bad_then_good() -> None:
            bad_bulk = SimpleNamespace(**vars(initial_rows["hrt"][0]))
            bad_bulk.lane_counts = [4031, 4032, 4032, 4032]
            collectors["hrt"].rows.append(bad_bulk)
            for name, collector in collectors.items():
                collector.rows.extend(initial_rows[name])

        with self.assertRaisesRegex(RuntimeError, "bad planes=\\{0: 4031\\}"):
            await self._verify(
                collectors,
                self._params(),
                refresh=_append_bad_then_good,
            )

    async def test_missing_control_prefix_fails_closed(self):
        collectors = self._collectors()
        collectors["prod_hrt_prefix"].rows = collectors["prod_hrt_prefix"].rows[:1]
        with self.assertRaisesRegex(RuntimeError, "prod_hrt_prefix:client"):
            await self._verify(
                collectors,
                self._params(),
                monotonic_side_effect=[0.0, 3.0],
            )

    async def test_missing_client_session_fails_closed(self):
        collectors = self._collectors()
        collectors["hrt_fsdb_session"].rows = collectors["hrt_fsdb_session"].rows[:1]
        with self.assertRaisesRegex(RuntimeError, "hrt_fsdb_session:client"):
            await self._verify(
                collectors,
                self._params(),
                monotonic_side_effect=[0.0, 3.0],
            )

    async def test_plane_counts_are_keyed_by_declared_plane_ids(self):
        collectors = self._collectors()
        first = collectors["hrt"].rows[0]
        first.plane_ids = [3, 2, 1, 0]
        first.lane_counts = [4032, 4032, 4032, 4031]
        with self.assertRaisesRegex(RuntimeError, "bad planes=\\{0: 4031\\}"):
            await self._verify(collectors, self._params())

    async def test_prod_prefix_wrong_device_fails_closed(self):
        collectors = self._collectors()
        collectors["prod_hrt_prefix"].rows[0].prefixes["2401:db00::/64"].device_ids = [
            1
        ]
        with self.assertRaisesRegex(RuntimeError, "actual="):
            await self._verify(collectors, self._params())

    async def test_legacy_rf_rows_keep_full_plane_vector_but_check_each_vf_half(
        self,
    ):
        collectors = self._collectors()
        collectors["hrt"].rows = [
            SimpleNamespace(
                timestamp=self._timestamp(time.time()),
                valid=True,
                notes="",
                host="server",
                device_id=0,
                lane_counts=[4032] * 8,
                plane_ids=list(range(8)),
            )
        ]
        collectors["hrt_plane_status"].rows = [
            SimpleNamespace(
                timestamp=self._timestamp(time.time()),
                valid=True,
                notes="",
                host="server",
                device_id=0,
                plane_states=dict.fromkeys(range(8), "UP"),
            )
        ]
        collectors["hrt_fsdb_session"].rows = [
            SimpleNamespace(
                timestamp=self._timestamp(time.time()),
                valid=True,
                notes="",
                host="server",
                connected=32,
            )
        ]
        collectors["hrt_remote_failure_vf1"].rows = [
            SimpleNamespace(
                timestamp=self._timestamp(time.time()),
                valid=True,
                notes="",
                host="server",
                device_id=0,
                lane_counts=[0, 0, 0, 0, 4032, 4032, 4032, 4032],
                plane_ids=list(range(8)),
            )
        ]
        collectors["hrt_remote_failure_vf2"].rows = [
            SimpleNamespace(
                timestamp=self._timestamp(time.time()),
                valid=True,
                notes="",
                host="server",
                device_id=0,
                lane_counts=[4032, 4032, 4032, 4032, 0, 0, 0, 0],
                plane_ids=list(range(8)),
            )
        ]
        reachability = collectors["prod_hrt_prefix"].rows[0].prefixes["2401:db00::/64"]
        reachability.unreachable_planes = [4, 5, 6, 7]
        reachability.plane_up = list(range(8))
        collectors["prod_hrt_prefix"].rows = [
            SimpleNamespace(
                timestamp=self._timestamp(time.time()),
                valid=True,
                notes="",
                host="server",
                prefixes={"2401:db00::/64": reachability},
            )
        ]
        params = self._params()
        params["device_planes_by_host"] = {"server": {"0": list(range(8))}}
        params["prod_prefix_expectations_by_host"] = {
            "server": {
                "2401:db00::/64": {
                    "device_ids": [0],
                    "reachable_planes": [0, 1, 2, 3],
                    "drained_planes": [],
                    "unreachable_planes": [4, 5, 6, 7],
                    "plane_up": list(range(8)),
                    "plane_down": [],
                }
            }
        }
        params["rf_vf_groups"] = [
            {"suffix": "vf1", "lanes": [0, 1, 2, 3]},
            {"suffix": "vf2", "lanes": [4, 5, 6, 7]},
        ]

        await self._verify(collectors, params)

    async def test_rf_row_missing_full_collector_plane_fails_closed(self):
        collectors = self._collectors()
        row = collectors["hrt_remote_failure_vf1"].rows[0]
        row.plane_ids = [0, 1, 2]
        row.lane_counts = [0, 0, 0]

        with self.assertRaisesRegex(RuntimeError, "full collector planes"):
            await self._verify(collectors, self._params())

    async def test_small_future_timestamp_within_grace_is_fresh(self):
        collectors = self._collectors()
        for collector in collectors.values():
            for row in collector.rows:
                row.timestamp = self._timestamp(1000.1)
        params = self._params()
        params["future_timestamp_grace_sec"] = 0.5

        with (
            patch(
                "neteng.test_infra.dne.taac.libs.fpf.fpf_collector_registry.get_collector",
                side_effect=collectors.get,
            ),
            patch(
                "neteng.test_infra.dne.taac.internal.steps.custom_step.time.time",
                return_value=1000.0,
            ),
        ):
            await self._verify(collectors, params)

    async def test_future_timestamp_beyond_grace_fails_distinctly(self):
        collectors = self._collectors()
        for collector in collectors.values():
            for row in collector.rows:
                row.timestamp = self._timestamp(1001.1)
        params = self._params()
        params["future_timestamp_grace_sec"] = 1.0

        with (
            patch(
                "neteng.test_infra.dne.taac.libs.fpf.fpf_collector_registry.get_collector",
                side_effect=collectors.get,
            ),
            patch(
                "neteng.test_infra.dne.taac.internal.steps.custom_step.time.time",
                return_value=1000.0,
            ),
            self.assertRaisesRegex(RuntimeError, "in the future \\(grace 1s\\)"),
        ):
            await self._verify(collectors, params)


class TestRepeatedServiceCrashStep(unittest.IsolatedAsyncioTestCase):
    def test_factory_shape(self):
        step = create_fpf_repeated_service_crash_step(
            service=Service.FSDB,
            every_sec=1,
            duration_sec=60,
            device_regexes=["gtsw001.*"],
        )
        self.assertEqual(step.name, StepName.CUSTOM_STEP)
        self.assertEqual(list(step.device_regexes), ["gtsw001.*"])
        p = _params(step)
        self.assertEqual(p["custom_step_name"], "fpf_repeated_service_crash")
        self.assertEqual(p["service"], int(Service.FSDB.value))
        self.assertEqual(p["every_sec"], 1)
        self.assertEqual(p["duration_sec"], 60)

    async def test_crashes_expected_number_of_times(self):
        """Kill fsdb every 1s for 60s -> ~60 SIGKILLs.

        time.time() is faked so the wall clock advances deterministically and
        the loop terminates without real sleeping.
        """
        cs = _make_custom_step()
        # Each loop iteration reads time.time() once (while-condition). Feed a
        # monotonically increasing clock: 60 iterations then a value past the
        # deadline. start is read first.
        ticks = [1000.0] + [1000.0 + i for i in range(60)] + [1100.0]
        sleeps = []

        async def fake_sleep(d):
            sleeps.append(d)

        with (
            patch("time.time", side_effect=ticks),
            patch("asyncio.sleep", side_effect=fake_sleep),
        ):
            await cs.fpf_repeated_service_crash(
                {"service": int(Service.FSDB.value), "every_sec": 1, "duration_sec": 60}
            )

        self.assertEqual(cs.driver.async_crash_service.await_count, 60)
        # Slept 1s between each kill.
        self.assertTrue(all(s == 1 for s in sleeps))
        self.assertEqual(len(sleeps), 60)
        # The driver service resolved from FSDB has the fsdb systemctl value.
        called_service = cs.driver.async_crash_service.await_args_list[0].args[0]
        self.assertEqual(called_service.value, "fsdb")


class TestRepeatedSwHwAgentCrashStep(unittest.IsolatedAsyncioTestCase):
    def test_factory_has_exact_narrow_scope_and_actual_timing(self):
        step = create_fpf_repeated_sw_hw_agent_crash_step(
            device_regexes=["gtsw001"],
        )
        self.assertEqual(step.name, StepName.CUSTOM_STEP)
        self.assertEqual(list(step.device_regexes), ["gtsw001"])
        params = _params(step)
        self.assertEqual(params["custom_step_name"], "fpf_repeated_sw_hw_agent_crash")
        self.assertEqual(params["process_names"], ["fboss_sw_agent", "fboss_hw_agent"])
        self.assertEqual(
            params["recovery_services"],
            [
                int(Service.FBOSS_SW_AGENT.value),
                int(Service.FBOSS_HW_AGENT_0.value),
            ],
        )
        self.assertEqual(params["every_sec"], 15)
        self.assertEqual(params["duration_sec"], 300)
        self.assertEqual(params["recovery_timeout_sec"], 120)

    async def test_attempts_both_exact_kills_and_collects_first_error(self):
        cs = _make_custom_step()
        cs.driver.async_run_cmd_on_shell.side_effect = [
            RuntimeError("sw kill failed"),
            "",
        ]
        cs.driver.async_get_service_status.return_value = SystemctlServiceStatus.ACTIVE
        with (
            self.assertRaisesRegex(
                TestCaseFailure,
                "failed after attempting both targets.*sw kill failed",
            ),
            patch("time.time", side_effect=[0.0, 1.0]),
        ):
            await cs.fpf_repeated_sw_hw_agent_crash(
                _params(create_fpf_repeated_sw_hw_agent_crash_step())
            )

        self.assertEqual(
            [call.args[0] for call in cs.driver.async_run_cmd_on_shell.await_args_list],
            ["pkill -9 fboss_sw_agent", "pkill -9 fboss_hw_agent"],
        )
        recovered = [
            call.args[0] for call in cs.driver.async_get_service_status.await_args_list
        ]
        self.assertEqual(
            [service.value for service in recovered],
            ["fboss_sw_agent", "fboss_hw_agent@0"],
        )

    async def test_successful_cycle_never_uses_broad_or_qsfp_match(self):
        cs = _make_custom_step()
        cs.driver.async_get_service_status.return_value = SystemctlServiceStatus.ACTIVE
        sleeps = []

        async def fake_sleep(duration):
            sleeps.append(duration)

        with (
            patch("time.time", side_effect=[0.0, 1.0, 1000.0]),
            patch("asyncio.sleep", side_effect=fake_sleep),
        ):
            await cs.fpf_repeated_sw_hw_agent_crash(
                _params(create_fpf_repeated_sw_hw_agent_crash_step())
            )

        commands = [
            call.args[0] for call in cs.driver.async_run_cmd_on_shell.await_args_list
        ]
        self.assertEqual(
            commands,
            ["pkill -9 fboss_sw_agent", "pkill -9 fboss_hw_agent"],
        )
        self.assertFalse(any("-f" in command for command in commands))
        self.assertFalse(any("qsfp" in command for command in commands))
        self.assertEqual(sleeps, [15])


class TestNdpClearLoopStep(unittest.IsolatedAsyncioTestCase):
    TARGET_INTERFACE = "eth1/41/5"
    NEIGHBOR_HOST = "twshared1352.03.mwg2"

    @staticmethod
    def _ndp_entry(
        address: str,
        *,
        port: int = 205,
        mac: str = "ba:ce:00:00:00:e8",
        interface_id: int = 2093,
        vlan_name: str = "downlink_93",
        state: str = "REACHABLE",
    ) -> NdpEntryThrift:
        return NdpEntryThrift(
            ip=BinaryAddress(addr=ipaddress.IPv6Address(address).packed),
            mac=mac,
            port=port,
            state=state,
            interfaceID=interface_id,
            vlanName=vlan_name,
        )

    def _params(self, *, every_sec: float = 4, duration_sec: float = 120) -> dict:
        return {
            "target_interface": self.TARGET_INTERFACE,
            "neighbor_host": self.NEIGHBOR_HOST,
            "every_sec": every_sec,
            "duration_sec": duration_sec,
        }

    def _configure_live_shape(
        self, cs: CustomStep
    ) -> tuple[AsyncMock, AsyncMock, MagicMock]:
        driver = _driver_mock(cs)
        driver.async_get_lldp_neighbors.return_value = {
            self.TARGET_INTERFACE: SimpleNamespace(
                remote_device_name=self.NEIGHBOR_HOST
            )
        }
        driver.async_get_interface_name_to_port_id_and_vlan_id.return_value = (
            SimpleNamespace(port_id=205, vlan_id=2093)
        )
        unrelated = [
            self._ndp_entry(f"2401:db00:ffff::{index}", port=99)
            for index in range(1, 412)
        ]
        driver.async_get_ndp_table.return_value = [
            *unrelated,
            self._ndp_entry("2401:db00:292a:8154:bace::b"),
            self._ndp_entry("fe80::b8ce:ff:fe00:e8"),
            self._ndp_entry("2401:db00:292a:8154:bace::d", state="DYNAMIC"),
        ]
        client = AsyncMock()
        client.getStatus.return_value = "ALIVE"
        client_context = MagicMock()
        client_context.__aenter__ = AsyncMock(return_value=client)
        client_context.__aexit__ = AsyncMock(return_value=False)
        driver.get_sw_agent_client.return_value = client_context
        return driver, client, client_context

    async def _run_with_fake_clock(
        self,
        cs: CustomStep,
        params: dict,
        client: AsyncMock,
        *,
        latencies: t.Sequence[float],
        first_flush_count: int = 2,
    ) -> float:
        clock = 0.0
        call_index = 0
        active = 0

        def fake_monotonic() -> float:
            return clock

        async def fake_sleep(delay: float) -> None:
            nonlocal clock
            clock += max(0.0, delay)

        async def flush(_entries: list) -> int:
            nonlocal active, call_index, clock
            self.assertEqual(active, 0)
            active += 1
            latency = latencies[call_index % len(latencies)]
            call_index += 1
            clock += latency
            active -= 1
            return first_flush_count if call_index == 1 else 0

        client.flushNeighborEntries.side_effect = flush
        with (
            patch(
                "neteng.test_infra.dne.taac.internal.steps.custom_step.time.monotonic",
                side_effect=fake_monotonic,
            ),
            patch(
                "neteng.test_infra.dne.taac.internal.steps.custom_step.asyncio.sleep",
                side_effect=fake_sleep,
            ),
        ):
            await cs.fpf_ndp_clear_loop(params)
        self.assertEqual(active, 0)
        return clock

    def test_factory_shape(self):
        step = create_fpf_ndp_clear_loop_step(
            target_interface=self.TARGET_INTERFACE,
            neighbor_host=self.NEIGHBOR_HOST,
            every_sec=4,
            duration_sec=120,
            device_regexes=["gtsw001.*"],
        )
        self.assertEqual(step.name, StepName.CUSTOM_STEP)
        p = _params(step)
        self.assertEqual(p["custom_step_name"], "fpf_ndp_clear_loop")
        self.assertEqual(p["every_sec"], 4)
        self.assertEqual(p["duration_sec"], 120)
        self.assertEqual(p["target_interface"], self.TARGET_INTERFACE)
        self.assertEqual(p["neighbor_host"], self.NEIGHBOR_HOST)
        self.assertNotIn("rpc_timeout_sec", p)

        with self.assertRaisesRegex(ValueError, "exact multiple"):
            create_fpf_ndp_clear_loop_step(
                target_interface=self.TARGET_INTERFACE,
                neighbor_host=self.NEIGHBOR_HOST,
                every_sec=0.1,
                duration_sec=0.31,
            )

    async def test_capacity_calibrated_trace_completes_30_slots_at_t120(self):
        cs = _make_custom_step()
        driver, client, client_context = self._configure_live_shape(cs)

        clock = await self._run_with_fake_clock(
            cs,
            self._params(),
            client,
            latencies=[1.082, 2.980, 2.365, 1.109, 1.097, 1.064],
        )

        self.assertEqual(client.flushNeighborEntries.await_count, 30)
        self.assertAlmostEqual(clock, 120.0)
        first_payload = client.flushNeighborEntries.await_args_list[0].args[0]
        self.assertEqual(
            {str(ipaddress.IPv6Address(entry.ip.addr)) for entry in first_payload},
            {"2401:db00:292a:8154:bace::b", "fe80::b8ce:ff:fe00:e8"},
        )
        self.assertEqual({entry.interfaceID for entry in first_payload}, {2093})
        client.getStatus.assert_awaited_once()
        client_context.__aenter__.assert_awaited_once()
        client_context.__aexit__.assert_awaited_once()
        driver.async_run_cmd_on_shell.assert_not_awaited()
        self.assertTrue(
            any(
                '"expected_attempts": 30' in str(call)
                and '"max_outstanding": 1' in str(call)
                for call in t.cast(MagicMock, cs.logger.info).call_args_list
            )
        )

    async def test_rpc_at_four_second_boundary_fails_closed(self):
        cs = _make_custom_step()
        _driver, client, client_context = self._configure_live_shape(cs)

        with self.assertRaisesRegex(RuntimeError, "completed at/after the next 4s"):
            await self._run_with_fake_clock(
                cs,
                self._params(duration_sec=4),
                client,
                latencies=[4.0],
            )

        client.flushNeighborEntries.assert_awaited_once()
        client_context.__aexit__.assert_awaited_once()

    async def test_rpc_just_before_four_second_boundary_passes(self):
        cs = _make_custom_step()
        _driver, client, client_context = self._configure_live_shape(cs)

        clock = await self._run_with_fake_clock(
            cs,
            self._params(duration_sec=4),
            client,
            latencies=[3.999],
        )

        self.assertEqual(client.flushNeighborEntries.await_count, 1)
        self.assertAlmostEqual(clock, 4.0)
        client_context.__aexit__.assert_awaited_once()

    async def test_real_wait_for_enforces_next_slot_deadline(self):
        cs = _make_custom_step()
        _driver, client, client_context = self._configure_live_shape(cs)
        never = asyncio.Event()

        async def blocked_flush(_entries: list) -> int:
            await never.wait()
            return 0

        client.flushNeighborEntries.side_effect = blocked_flush
        with self.assertRaisesRegex(RuntimeError, "next 0.01s request boundary"):
            await cs.fpf_ndp_clear_loop(self._params(every_sec=0.01, duration_sec=0.01))

        client.flushNeighborEntries.assert_awaited_once()
        client_context.__aexit__.assert_awaited_once()

    async def test_warmup_failure_closes_client_without_mutation(self):
        cs = _make_custom_step()
        _driver, client, client_context = self._configure_live_shape(cs)
        client.getStatus.side_effect = RuntimeError("not ready")

        with self.assertRaisesRegex(RuntimeError, "open/warm failed: not ready"):
            await cs.fpf_ndp_clear_loop(self._params(duration_sec=4))

        client.flushNeighborEntries.assert_not_awaited()
        client_context.__aexit__.assert_awaited_once()

    async def test_warmup_timeout_closes_client_without_mutation(self):
        cs = _make_custom_step()
        _driver, client, client_context = self._configure_live_shape(cs)
        never = asyncio.Event()
        client.getStatus.side_effect = never.wait

        with (
            patch(
                "neteng.test_infra.dne.taac.internal.steps.custom_step."
                "_FPF_NDP_CLIENT_WARMUP_TIMEOUT_SEC",
                0.02,
            ),
            self.assertRaisesRegex(RuntimeError, "open/warm timed out"),
        ):
            await cs.fpf_ndp_clear_loop(self._params(duration_sec=4))

        client.flushNeighborEntries.assert_not_awaited()
        client_context.__aexit__.assert_awaited_once()

    async def test_rpc_error_closes_client(self):
        cs = _make_custom_step()
        _driver, client, client_context = self._configure_live_shape(cs)
        client.flushNeighborEntries.side_effect = RuntimeError("agent rejected flush")

        with self.assertRaisesRegex(RuntimeError, "RPC failed: agent rejected flush"):
            await cs.fpf_ndp_clear_loop(self._params(duration_sec=4))

        client_context.__aexit__.assert_awaited_once()
        self.assertTrue(
            any(
                '"outcome": "error"' in str(call)
                and "agent rejected flush" in str(call)
                for call in t.cast(MagicMock, cs.logger.info).call_args_list
            )
        )

    async def test_controller_missed_cadence_fails_without_second_rpc(self):
        cs = _make_custom_step()
        _driver, client, client_context = self._configure_live_shape(cs)
        clock = 0.0
        overslept = False

        def fake_monotonic() -> float:
            return clock

        async def fake_sleep(delay: float) -> None:
            nonlocal clock, overslept
            clock += delay
            if delay > 0 and not overslept:
                clock += 4.0
                overslept = True

        client.flushNeighborEntries.return_value = 1
        with (
            patch(
                "neteng.test_infra.dne.taac.internal.steps.custom_step.time.monotonic",
                side_effect=fake_monotonic,
            ),
            patch(
                "neteng.test_infra.dne.taac.internal.steps.custom_step.asyncio.sleep",
                side_effect=fake_sleep,
            ),
            self.assertRaisesRegex(RuntimeError, "controller missed slot 2/2"),
        ):
            await cs.fpf_ndp_clear_loop(self._params(duration_sec=8))

        client.flushNeighborEntries.assert_awaited_once()
        client_context.__aexit__.assert_awaited_once()

    async def test_lldp_mismatch_fails_before_clear(self):
        cs = _make_custom_step()
        driver, _client, _client_context = self._configure_live_shape(cs)
        driver.async_get_lldp_neighbors.return_value[
            self.TARGET_INTERFACE
        ].remote_device_name = "wrong-host.mwg2"

        with self.assertRaisesRegex(RuntimeError, "LLDP neighbor=wrong-host"):
            await cs.fpf_ndp_clear_loop(self._params())

        driver.get_sw_agent_client.assert_not_awaited()

    async def test_empty_ambiguous_and_nonflushable_scope_fail(self):
        cs = _make_custom_step()
        driver, _client, _client_context = self._configure_live_shape(cs)
        driver.async_get_ndp_table.return_value = []
        with self.assertRaisesRegex(RuntimeError, "no flushable IPv6 NDP entries"):
            await cs.fpf_ndp_clear_loop(self._params())

        cs = _make_custom_step()
        driver, _client, _client_context = self._configure_live_shape(cs)
        driver.async_get_ndp_table.return_value.append(
            self._ndp_entry("2401:db00:292a:8154:bace::c", mac="00:11:22:33:44:55")
        )
        with self.assertRaisesRegex(RuntimeError, "ambiguous NDP scope"):
            await cs.fpf_ndp_clear_loop(self._params())

        cs = _make_custom_step()
        driver, _client, _client_context = self._configure_live_shape(cs)
        driver.async_get_ndp_table.return_value = [
            self._ndp_entry("2401:db00:292a:8154:bace::b", state="DYNAMIC"),
            self._ndp_entry("fe80::b8ce:ff:fe00:e8", state="STATIC"),
        ]
        with self.assertRaisesRegex(RuntimeError, "no flushable IPv6 NDP entries"):
            await cs.fpf_ndp_clear_loop(self._params())

    async def test_entry_interface_id_drives_rpc_not_port_vlan(self):
        cs = _make_custom_step()
        driver, client, _client_context = self._configure_live_shape(cs)
        driver.async_get_ndp_table.return_value = [
            self._ndp_entry("2401:db00:292a:8154:bace::b", interface_id=9999)
        ]
        await self._run_with_fake_clock(
            cs,
            self._params(duration_sec=4),
            client,
            latencies=[1.0],
        )

        payload = client.flushNeighborEntries.await_args_list[0].args[0]
        self.assertEqual([entry.interfaceID for entry in payload], [9999])

    async def test_missing_port_vlan_is_diagnostic_only(self):
        cs = _make_custom_step()
        driver, client, _client_context = self._configure_live_shape(cs)
        driver.async_get_interface_name_to_port_id_and_vlan_id.return_value = (
            SimpleNamespace(port_id=205)
        )
        await self._run_with_fake_clock(
            cs,
            self._params(duration_sec=4),
            client,
            latencies=[1.0],
        )

        client.flushNeighborEntries.assert_awaited_once()

    async def test_invalid_state_interface_id_and_count_fail(self):
        for entry, expected in (
            (self._ndp_entry("2401:db00::1", state=""), "invalid state"),
            (
                self._ndp_entry("2401:db00::1", interface_id=-1),
                "invalid interfaceID=-1",
            ),
        ):
            with self.subTest(expected=expected):
                cs = _make_custom_step()
                driver, _client, _client_context = self._configure_live_shape(cs)
                driver.async_get_ndp_table.return_value = [entry]
                with self.assertRaisesRegex(RuntimeError, expected):
                    await cs.fpf_ndp_clear_loop(self._params())
                driver.get_sw_agent_client.assert_not_awaited()

        for result in (-1, True, "2"):
            with self.subTest(result=result):
                cs = _make_custom_step()
                _driver, client, client_context = self._configure_live_shape(cs)
                client.flushNeighborEntries.return_value = result
                with self.assertRaisesRegex(RuntimeError, "invalid flush count"):
                    await cs.fpf_ndp_clear_loop(self._params(duration_sec=4))
                client_context.__aexit__.assert_awaited_once()

    async def test_zero_total_flush_fails_exact_rate_contract(self):
        cs = _make_custom_step()
        _driver, client, _client_context = self._configure_live_shape(cs)
        with self.assertRaisesRegex(RuntimeError, "total_flushed=0"):
            await self._run_with_fake_clock(
                cs,
                self._params(duration_sec=8),
                client,
                latencies=[1.0],
                first_flush_count=0,
            )

    async def test_cancelled_clear_closes_client_and_reraises(self):
        cs = _make_custom_step()
        driver, client, client_context = self._configure_live_shape(cs)

        async def flush(_entries: list) -> int:
            raise asyncio.CancelledError

        client.flushNeighborEntries.side_effect = flush
        with self.assertRaises(asyncio.CancelledError):
            await cs.fpf_ndp_clear_loop(self._params())

        client.flushNeighborEntries.assert_awaited_once()
        client_context.__aexit__.assert_awaited_once()
        driver.async_run_cmd_on_shell.assert_not_awaited()


class TestOwnedDrainCleanup(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        clear_drain_mutations()

    def tearDown(self) -> None:
        clear_drain_mutations()

    def test_factories_retain_exact_target_and_scope(self) -> None:
        drain = create_fpf_drain_interface_step(
            interfaces=["eth1/41/5"],
            drain=True,
            target_device="gtsw001.l1002.c087.mwg2",
            mutation_token="tc17",
        )
        self.assertEqual(
            _params(drain),
            {
                "custom_step_name": "fpf_drain_interface",
                "interfaces": ["eth1/41/5"],
                "is_drain": True,
                "target_device": "gtsw001.l1002.c087.mwg2",
                "mutation_token": "tc17",
            },
        )
        cleanup = create_fpf_conditional_undrain_step(
            interfaces=[],
            target_device="gtsw002.l1002.c087.mwg2",
            mutation_token="tc19",
            best_effort=True,
        )
        self.assertEqual(_params(cleanup)["interfaces"], [])
        self.assertEqual(_params(cleanup)["target_device"], "gtsw002.l1002.c087.mwg2")
        self.assertIs(_params(cleanup)["best_effort"], True)

    async def test_no_marker_cleanup_is_noop(self) -> None:
        cs = _make_custom_step()
        driver = _driver_mock(cs)
        await cs.fpf_conditional_undrain(
            {
                "interfaces": ["eth1/41/5"],
                "mutation_token": "tc17",
            }
        )
        driver.async_undrain_interface.assert_not_awaited()
        driver.async_onbox_undrain_device.assert_not_awaited()
        self.assertTrue(
            any(
                "SKIPPED: no mutation marker" in str(call)
                for call in t.cast(MagicMock, cs.logger.info).call_args_list
            )
        )

    async def test_marker_restores_only_exact_interface(self) -> None:
        cs = _make_custom_step()
        driver = _driver_mock(cs)
        mark_drain_mutation("tc17", cs.hostname, ["eth1/41/5"])
        driver.get_specific_interface_info.return_value = SimpleNamespace(
            isDrained=False
        )

        await cs.fpf_conditional_undrain(
            {
                "interfaces": ["eth1/41/5"],
                "mutation_token": "tc17",
            }
        )

        driver.async_undrain_interface.assert_awaited_once_with("eth1/41/5")
        driver.async_onbox_undrain_device.assert_not_awaited()
        self.assertIsNone(get_drain_mutation("tc17"))

    async def test_device_clean_rejects_preexisting_port_drain(self) -> None:
        cs = _make_custom_step()
        driver = _driver_mock(cs)
        driver.async_is_device_drained.return_value = False
        driver.async_get_all_interfaces_info.return_value = {
            "eth1/1/4": SimpleNamespace(isDrained=True),
            "eth1/41/5": SimpleNamespace(isDrained=False),
        }

        with self.assertRaisesRegex(RuntimeError, "eth1/1/4"):
            await cs.fpf_verify_disruption(
                {
                    "interfaces": [],
                    "mode": "device_clean",
                    "fail_if_ineffective": True,
                }
            )

        driver.async_onbox_undrain_device.assert_not_awaited()
        driver.async_undrain_interface.assert_not_awaited()

    async def test_cancelled_drain_leaves_marker_for_cleanup(self) -> None:
        cs = _make_custom_step()
        driver = _driver_mock(cs)
        driver.async_softdrain_interface.side_effect = asyncio.CancelledError()
        params = {
            "interfaces": ["eth1/41/5"],
            "is_drain": True,
            "mutation_token": "tc17",
        }

        with self.assertRaises(asyncio.CancelledError):
            await cs.fpf_drain_interface(params)

        self.assertEqual(
            get_drain_mutation("tc17"),
            (cs.hostname, ("eth1/41/5",)),
        )
        driver.async_softdrain_interface.side_effect = None
        driver.get_specific_interface_info.return_value = SimpleNamespace(
            isDrained=False
        )
        await cs.fpf_conditional_undrain(
            {
                "interfaces": ["eth1/41/5"],
                "mutation_token": "tc17",
            }
        )
        self.assertIsNone(get_drain_mutation("tc17"))

    async def test_marker_restores_whole_target_device(self) -> None:
        cs = _make_custom_step()
        target = "gtsw002.l1002.c087.mwg2"
        target_driver = AsyncMock()
        target_driver.async_is_device_drained.return_value = False
        mark_drain_mutation("tc19", target, [])

        with patch(
            "neteng.test_infra.dne.taac.internal.steps.custom_step.async_get_device_driver",
            new=AsyncMock(return_value=target_driver),
        ) as get_driver:
            await cs.fpf_conditional_undrain(
                {
                    "interfaces": [],
                    "target_device": target,
                    "mutation_token": "tc19",
                }
            )

        t.cast(AsyncMock, get_driver).assert_awaited_once_with(target, cs.logger)
        target_driver.async_onbox_undrain_device.assert_awaited_once()
        self.assertIsNone(get_drain_mutation("tc19"))

    async def test_drain_and_readback_use_explicit_target_device(self) -> None:
        cs = _make_custom_step()
        target = "gtsw002.l1002.c087.mwg2"
        target_driver = AsyncMock()
        target_driver.async_is_device_drained.return_value = True

        with patch(
            "neteng.test_infra.dne.taac.internal.steps.custom_step.async_get_device_driver",
            new=AsyncMock(return_value=target_driver),
        ) as get_driver:
            await cs.fpf_drain_interface(
                {
                    "interfaces": [],
                    "is_drain": True,
                    "target_device": target,
                    "mutation_token": "tc19",
                }
            )
            await cs.fpf_verify_disruption(
                {
                    "interfaces": [],
                    "mode": "device_drain",
                    "expect_drained": True,
                    "fail_if_ineffective": True,
                    "target_device": target,
                }
            )

        self.assertEqual(t.cast(AsyncMock, get_driver).await_count, 2)
        target_driver.async_onbox_softdrain_device.assert_awaited_once()
        target_driver.async_is_device_drained.assert_awaited_once()
        _driver_mock(cs).async_onbox_softdrain_device.assert_not_awaited()


class TestGarSteps(unittest.IsolatedAsyncioTestCase):
    def test_factories(self):
        targets = [{"device": "gtsw001", "interfaces": ["eth1/2/1"]}]
        link_step = create_fpf_gar_set_links_step(
            targets=targets,
            mode="admin",
            disrupt=True,
            device_regexes=["gtsw001"],
        )
        self.assertEqual(link_step.name, StepName.CUSTOM_STEP)
        self.assertEqual(list(link_step.device_regexes), ["gtsw001"])
        link_params = _params(link_step)
        self.assertEqual(link_params["custom_step_name"], "fpf_gar_set_links")
        self.assertEqual(link_params["targets"], targets)

        validate_step = create_fpf_gar_validate_step(
            pairs=[
                {
                    "name": "pair-A",
                    "source": "gtsw001",
                    "spine": "stsw001",
                    "observer": "gtsw001.remote",
                    "expected_capacity": 35,
                }
            ],
            prefix_base="5000:ca::/64",
            prefix_count=1000,
        )
        validate_params = _params(validate_step)
        self.assertEqual(validate_params["custom_step_name"], "fpf_gar_validate")
        self.assertEqual(validate_params["prefix_count"], 1000)

    @patch(
        "neteng.test_infra.dne.taac.internal.steps.custom_step.async_get_device_driver"
    )
    async def test_multi_device_admin_disruption(self, mock_get_driver):
        cs = _make_custom_step()
        driver_a = AsyncMock()
        driver_a.async_get_all_interfaces_admin_status.return_value = {
            "eth1/2/1": False
        }
        driver_b = AsyncMock()
        driver_b.async_get_all_interfaces_admin_status.return_value = {
            "eth1/2/5": False
        }
        mock_get_driver.side_effect = [driver_a, driver_b]

        await cs.fpf_gar_set_links(
            {
                "mode": "admin",
                "disrupt": True,
                "targets": [
                    {"device": "gtsw001", "interfaces": ["eth1/2/1"]},
                    {"device": "gtsw004", "interfaces": ["eth1/2/5"]},
                ],
            }
        )

        driver_a.async_thrift_disable_enable_interfaces.assert_awaited_once_with(
            interface_names=["eth1/2/1"], is_enable_port=False
        )
        driver_b.async_thrift_disable_enable_interfaces.assert_awaited_once_with(
            interface_names=["eth1/2/5"], is_enable_port=False
        )

    @patch(
        "neteng.test_infra.dne.taac.internal.steps.custom_step.async_get_device_driver"
    )
    async def test_admin_readback_rejects_missing_interface(self, mock_get_driver):
        cs = _make_custom_step()
        driver = AsyncMock()
        driver.async_get_all_interfaces_admin_status.return_value = {}
        mock_get_driver.return_value = driver

        with self.assertRaisesRegex(RuntimeError, "read-back failed"):
            await cs.fpf_gar_set_links(
                {
                    "mode": "admin",
                    "disrupt": True,
                    "targets": [{"device": "gtsw001", "interfaces": ["eth1/2/1"]}],
                }
            )

    @patch(
        "neteng.test_infra.dne.taac.libs.fpf.fpf_collector_registry.set_disruption_time"
    )
    @patch(
        "neteng.test_infra.dne.taac.internal.steps.custom_step.async_get_device_driver"
    )
    async def test_admin_recovery_preserves_disruption_time(
        self, mock_get_driver, mock_set_disruption_time
    ):
        cs = _make_custom_step()
        driver = AsyncMock()
        driver.async_get_all_interfaces_admin_status.return_value = {"eth1/2/1": True}
        mock_get_driver.return_value = driver

        await cs.fpf_gar_set_links(
            {
                "mode": "admin",
                "disrupt": False,
                "targets": [{"device": "gtsw001", "interfaces": ["eth1/2/1"]}],
            }
        )

        mock_set_disruption_time.assert_not_called()

    @patch(
        "neteng.test_infra.dne.taac.internal.steps.custom_step.async_get_device_driver"
    )
    async def test_softdrain_uses_one_bulk_request_per_device(self, mock_get_driver):
        cs = _make_custom_step()
        driver = AsyncMock()
        driver.get_specific_interface_info.side_effect = [
            type("InterfaceInfo", (), {"isDrained": True})(),
            type("InterfaceInfo", (), {"isDrained": True})(),
        ]
        mock_get_driver.return_value = driver

        interfaces = ["eth1/2/1", "eth1/2/5"]
        await cs.fpf_gar_set_links(
            {
                "mode": "softdrain",
                "disrupt": True,
                "targets": [{"device": "gtsw001", "interfaces": interfaces}],
            }
        )

        driver.async_softdrain_interfaces.assert_awaited_once_with(interfaces)
        driver.async_softdrain_interface.assert_not_awaited()

    @patch(
        "neteng.test_infra.dne.taac.internal.steps.custom_step.async_get_device_driver"
    )
    async def test_undrain_uses_one_bulk_request_per_device(self, mock_get_driver):
        cs = _make_custom_step()
        driver = AsyncMock()
        driver.get_specific_interface_info.side_effect = [
            type("InterfaceInfo", (), {"isDrained": False})(),
            type("InterfaceInfo", (), {"isDrained": False})(),
        ]
        mock_get_driver.return_value = driver

        interfaces = ["eth1/2/1", "eth1/2/5"]
        await cs.fpf_gar_set_links(
            {
                "mode": "softdrain",
                "disrupt": False,
                "targets": [{"device": "gtsw001", "interfaces": interfaces}],
            }
        )

        driver.async_undrain_interfaces.assert_awaited_once_with(interfaces)
        driver.async_undrain_interface.assert_not_awaited()

    @patch(
        "neteng.test_infra.dne.taac.libs.fpf.fpf_gar.wait_for_gar_pairs",
        new_callable=AsyncMock,
    )
    async def test_gar_validation_delegates_to_library(self, mock_wait):
        mock_wait.return_value = ["pair-A: capacity=35"]
        cs = _make_custom_step()
        params = {
            "pairs": [{"name": "pair-A"}],
            "prefix_base": "5000:ca::/64",
            "prefix_count": 1000,
        }
        await cs.fpf_gar_validate(params)
        mock_wait.assert_awaited_once()


class TestRapidFlapStep(unittest.IsolatedAsyncioTestCase):
    def test_factory_shape(self):
        step = create_fpf_rapid_flap_step(
            interfaces_by_device={"gtsw001.l1001.c085.ash6": ["eth1/1/1", "eth1/2/1"]},
            duration_sec=900,
            flap_interval_sec=1,
        )
        self.assertEqual(step.name, StepName.CUSTOM_STEP)
        p = _params(step)
        self.assertEqual(p["custom_step_name"], "fpf_rapid_flap")
        self.assertEqual(p["duration_sec"], 900)
        self.assertEqual(p["flap_interval_sec"], 1)

    async def test_flaps_with_right_interfaces_and_count(self):
        host = "gtsw001.l1001.c085.ash6"
        cs = _make_custom_step(hostname=host)
        await cs.fpf_rapid_flap(
            {
                "interfaces_by_device": {host: ["eth1/1/1", "eth1/2/1"]},
                "duration_sec": 900,
                "flap_interval_sec": 1,
            }
        )
        cs.driver.async_do_rapid_interface_flaps.assert_awaited_once_with(
            interface_names=("eth1/1/1", "eth1/2/1"),
            interval_to_link_up=1,
            total_flaps=900,
        )

    async def test_no_matching_device_is_noop(self):
        cs = _make_custom_step(hostname="gtsw001.l1001.c085.ash6")
        await cs.fpf_rapid_flap(
            {
                "interfaces_by_device": {"stsw099.s001.c085.ash6": ["eth1/1/1"]},
                "duration_sec": 60,
                "flap_interval_sec": 1,
            }
        )
        cs.driver.async_do_rapid_interface_flaps.assert_not_awaited()

    async def test_total_flaps_derived_from_interval(self):
        host = "gtsw001"
        cs = _make_custom_step(hostname=host)
        await cs.fpf_rapid_flap(
            {
                "interfaces_by_device": {host: ["eth1/1/1"]},
                "duration_sec": 30,
                "flap_interval_sec": 5,
            }
        )
        cs.driver.async_do_rapid_interface_flaps.assert_awaited_once_with(
            interface_names=("eth1/1/1",),
            interval_to_link_up=5,
            total_flaps=6,
        )


def _lldp_table() -> dict:
    """Fake LLDP neighbor table for the LLDP-resolver tests."""
    return {
        "eth1/1/1": SwitchLldpData(
            remote_device_name="gtsw001.l1002.c087.mwg2",
            remote_intf_name="eth1/41/5",
        ),
        "eth1/2/1": SwitchLldpData(
            remote_device_name="gtsw001.l1002.c087.mwg2",
            remote_intf_name="eth1/41/6",
        ),
        "eth1/3/1": SwitchLldpData(
            remote_device_name="gtsw002.l1002.c087.mwg2",
            remote_intf_name="eth1/41/5",
        ),
        "eth1/4/1": SwitchLldpData(
            remote_device_name="rtptest1555.mwg2",
            remote_intf_name="beth0",
        ),
        "eth1/5/1": SwitchLldpData(
            remote_device_name="stsw099.s001.l202.mwg2",
            remote_intf_name="eth1/9/1",
        ),
    }


class TestResolveLldpInterfaces(unittest.IsolatedAsyncioTestCase):
    async def test_filters_by_glob_and_dedups(self):
        cs = _make_custom_step()
        cs.driver.async_get_lldp_neighbors.return_value = _lldp_table()
        out = await cs._resolve_lldp_interfaces("gtsw001*")
        # Sorted, only gtsw001 neighbors.
        self.assertEqual(out, ["eth1/1/1", "eth1/2/1"])

    async def test_pattern_matches_multiple_neighbor_classes(self):
        cs = _make_custom_step()
        cs.driver.async_get_lldp_neighbors.return_value = _lldp_table()
        out = await cs._resolve_lldp_interfaces("gtsw*")
        self.assertEqual(out, ["eth1/1/1", "eth1/2/1", "eth1/3/1"])

    async def test_no_match_returns_empty(self):
        cs = _make_custom_step()
        cs.driver.async_get_lldp_neighbors.return_value = _lldp_table()
        out = await cs._resolve_lldp_interfaces("doesnotexist*")
        self.assertEqual(out, [])

    async def test_neighbor_hosts_exact_match_domain_stripped(self):
        cs = _make_custom_step()
        cs.driver.async_get_lldp_neighbors.return_value = _lldp_table()
        # Exact match against the domain-stripped configured host set; "gtsw001"
        # exact-matches the gtsw001.* neighbors but NOT gtsw002.
        out = await cs._resolve_lldp_interfaces(neighbor_hosts=["gtsw001"])
        self.assertEqual(out, ["eth1/1/1", "eth1/2/1"])

    async def test_neighbor_hosts_takes_precedence_over_pattern(self):
        cs = _make_custom_step()
        cs.driver.async_get_lldp_neighbors.return_value = _lldp_table()
        # neighbor_hosts is honored even when a broad glob is also passed.
        out = await cs._resolve_lldp_interfaces(
            neighbor_pattern="gtsw*", neighbor_hosts=["rtptest1555"]
        )
        self.assertEqual(out, ["eth1/4/1"])


class TestRapidFlapStepLldp(unittest.IsolatedAsyncioTestCase):
    def test_factory_shape(self):
        step = create_fpf_rapid_flap_step_lldp(
            neighbor_pattern="rtptest*",
            duration_sec=900,
            flap_interval_sec=1,
            device_regexes=["gtsw001.*"],
        )
        self.assertEqual(step.name, StepName.CUSTOM_STEP)
        self.assertEqual(list(step.device_regexes), ["gtsw001.*"])
        p = _params(step)
        self.assertEqual(p["custom_step_name"], "fpf_rapid_flap_lldp")
        self.assertEqual(p["neighbor_pattern"], "rtptest*")
        self.assertEqual(p["duration_sec"], 900)
        self.assertEqual(p["flap_interval_sec"], 1)
        # neighbor_hosts unset -> None; default symmetric 6s up / 6s down.
        self.assertIsNone(p["neighbor_hosts"])
        self.assertEqual(p["down_time_sec"], 6.0)
        self.assertEqual(p["up_time_sec"], 6.0)
        # No pre-resolved interface map.
        self.assertNotIn("interfaces_by_device", p)

    def test_factory_shape_with_neighbor_hosts(self):
        step = create_fpf_rapid_flap_step_lldp(
            neighbor_hosts=["rtptest1555", "rtptest1575"],
            neighbor_pattern="rtptest*",
            duration_sec=900,
            flap_interval_sec=1,
            flap_down_time_sec=6,
            device_regexes=["gtsw001.*"],
        )
        p = _params(step)
        self.assertEqual(p["neighbor_hosts"], ["rtptest1555", "rtptest1575"])
        # Exact hosts are authoritative; do not retain a broader fallback glob.
        self.assertIsNone(p["neighbor_pattern"])
        self.assertEqual(p["down_time_sec"], 6.0)

    def test_factory_serializes_opt_in_fail_closed_contract(self):
        step = create_fpf_rapid_flap_step_lldp(
            neighbor_hosts=["twshared1352.03.mwg2"],
            duration_sec=900,
            fail_closed=True,
            expected_interfaces=["eth1/41/5"],
            require_exact_neighbor_hosts=True,
            final_up_timeout_sec=60,
            final_up_poll_interval_sec=5,
            nic_recovery_by_interface={
                "eth1/41/5": {
                    "host": "twshared1352.03.mwg2",
                    "dev": 0,
                    "lane": 0,
                },
            },
        )
        p = _params(step)
        self.assertTrue(p["fail_closed"])
        self.assertEqual(p["expected_interfaces"], ["eth1/41/5"])
        self.assertTrue(p["require_exact_neighbor_hosts"])
        self.assertEqual(
            p["nic_recovery_by_interface"],
            {
                "eth1/41/5": {
                    "host": "twshared1352.03.mwg2",
                    "dev": 0,
                    "lane": 0,
                }
            },
        )

    def test_fail_closed_factories_require_exact_interface_scope(self):
        with self.assertRaisesRegex(ValueError, "expected_interfaces"):
            create_fpf_rapid_flap_step_lldp(
                neighbor_hosts=["twshared1352.03.mwg2"],
                duration_sec=900,
                fail_closed=True,
            )
        with self.assertRaisesRegex(ValueError, "expected_interfaces"):
            create_fpf_multi_gtsw_rapid_flap_step(
                gtsws=["gtsw001.l1002.c087.mwg2"],
                neighbor_hosts=["twshared1352.03.mwg2"],
                duration_sec=900,
                fail_closed=True,
                expected_interfaces=[],
            )

    async def test_flaps_lldp_resolved_tuple_wall_clock_bounded(self):
        """The handler loops single flaps until duration_sec elapses.

        time.time() is faked so the loop runs exactly two iterations then exits.
        """
        cs = _make_custom_step()
        cs.driver.async_get_lldp_neighbors.return_value = _lldp_table()
        # start=0.0 (read first), then two iterations under the 30s deadline,
        # then a value past the deadline to terminate.
        ticks = [0.0, 1.0, 2.0, 100.0]
        with patch("time.time", side_effect=ticks):
            await cs.fpf_rapid_flap_lldp(
                {
                    "neighbor_pattern": "gtsw001*",
                    "duration_sec": 30,
                    "flap_interval_sec": 5,
                    "down_time_sec": 6,
                }
            )
        # Two symmetric-cycle iterations, each total_flaps=1 with up=down=6
        # (up_time_sec defaults to down_time_sec when not passed).
        self.assertEqual(cs.driver.async_do_rapid_interface_flaps.await_count, 2)
        for call in cs.driver.async_do_rapid_interface_flaps.await_args_list:
            self.assertEqual(
                call.kwargs,
                {
                    "interface_names": ("eth1/1/1", "eth1/2/1"),
                    "interval_to_link_up": 5,
                    "total_flaps": 1,
                    "down_time_sec": 6.0,
                    "up_time_sec": 6.0,
                },
            )

    async def test_flaps_lldp_resolved_by_neighbor_hosts_exact_match(self):
        """neighbor_hosts exact-match resolves only the configured GPU hosts."""
        cs = _make_custom_step()
        cs.driver.async_get_lldp_neighbors.return_value = _lldp_table()
        # The table maps eth1/4/1 -> rtptest1555.mwg2. Domain-stripped exact
        # match on "rtptest1555" picks ONLY that interface (a "rtptest*" glob
        # would also match, but exact-match guards against over-broad scope).
        # start=0.0 -> while-check 1.0 < 30 (flap once) -> while-check 100.0 >= 30 (exit).
        ticks = [0.0, 1.0, 100.0]
        with patch("time.time", side_effect=ticks):
            await cs.fpf_rapid_flap_lldp(
                {
                    "neighbor_hosts": ["rtptest1555", "rtptest1575"],
                    "neighbor_pattern": "rtptest*",
                    "duration_sec": 30,
                    "flap_interval_sec": 1,
                }
            )
        self.assertEqual(cs.driver.async_do_rapid_interface_flaps.await_count, 1)
        call = cs.driver.async_do_rapid_interface_flaps.await_args_list[0]
        self.assertEqual(call.kwargs["interface_names"], ("eth1/4/1",))

    async def test_no_match_is_noop(self):
        cs = _make_custom_step()
        cs.driver.async_get_lldp_neighbors.return_value = _lldp_table()
        await cs.fpf_rapid_flap_lldp(
            {
                "neighbor_pattern": "nomatch*",
                "duration_sec": 30,
                "flap_interval_sec": 1,
            }
        )
        cs.driver.async_do_rapid_interface_flaps.assert_not_awaited()

    async def test_fail_closed_rejects_inexact_lldp_before_flap(self):
        cs = _make_custom_step()
        cs.driver.async_get_lldp_neighbors.return_value = _lldp_table()
        with self.assertRaisesRegex(Exception, "LLDP interface scope mismatch"):
            await cs.fpf_rapid_flap_lldp(
                {
                    "neighbor_hosts": ["rtptest1555"],
                    "duration_sec": 30,
                    "fail_closed": True,
                    "expected_interfaces": ["eth1/41/5"],
                    "require_exact_neighbor_hosts": True,
                }
            )
        cs.driver.async_do_rapid_interface_flaps.assert_not_awaited()

    async def test_fail_closed_handler_requires_exact_interface_scope(self):
        cs = _make_custom_step()
        cs.driver.async_get_lldp_neighbors.return_value = _lldp_table()
        with self.assertRaisesRegex(Exception, "exact expected_interfaces scope"):
            await cs.fpf_rapid_flap_lldp(
                {
                    "neighbor_hosts": ["rtptest1555"],
                    "duration_sec": 30,
                    "fail_closed": True,
                    "require_exact_neighbor_hosts": True,
                }
            )
        cs.driver.async_do_rapid_interface_flaps.assert_not_awaited()

    async def test_multi_gtsw_rejected_scope_does_not_run_cleanup(self):
        cs = _make_custom_step()
        driver = AsyncMock()
        driver.async_get_lldp_neighbors.return_value = _lldp_table()
        cleanup = AsyncMock()
        with (
            self.assertRaisesRegex(Exception, "one or more GTSWs failed"),
            patch(
                "neteng.test_infra.dne.taac.internal.steps.custom_step."
                "async_get_device_driver",
                new=AsyncMock(return_value=driver),
            ),
            patch.object(cs, "_restore_rapid_flap_interfaces", new=cleanup),
        ):
            await cs.fpf_multi_gtsw_rapid_flap(
                {
                    "gtsws": ["gtsw001.l1002.c087.mwg2"],
                    "neighbor_hosts": ["rtptest1555"],
                    "duration_sec": 30,
                    "fail_closed": True,
                    "expected_interfaces": ["eth1/41/5"],
                    "require_exact_neighbor_hosts": True,
                }
            )
        driver.async_do_rapid_interface_flaps.assert_not_awaited()
        cleanup.assert_not_awaited()

    async def test_fail_closed_restores_and_verifies_after_flap_failure(self):
        cs = _make_custom_step()
        cs.driver.async_get_lldp_neighbors.return_value = _lldp_table()
        cs.driver.async_do_rapid_interface_flaps.side_effect = RuntimeError("boom")
        cs.driver.async_get_all_interfaces_admin_status.return_value = {
            "eth1/4/1": True
        }
        cs.driver.async_get_all_interfaces_operational_status.return_value = {
            "eth1/4/1": True
        }
        with (
            self.assertRaisesRegex(RuntimeError, "boom"),
            patch("time.time", return_value=0.0),
        ):
            await cs.fpf_rapid_flap_lldp(
                {
                    "neighbor_hosts": ["rtptest1555"],
                    "duration_sec": 30,
                    "fail_closed": True,
                    "expected_interfaces": ["eth1/4/1"],
                    "require_exact_neighbor_hosts": True,
                }
            )
        cs.driver.async_run_cmd_on_shell.assert_awaited_once_with(
            "wedge_qsfp_util -tx_enable eth1/4/1"
        )
        cs.driver.async_thrift_disable_enable_interfaces.assert_awaited_once_with(
            interface_names=("eth1/4/1",), is_enable_port=True
        )

    async def test_restore_failure_chains_original_flap_failure(self):
        cs = _make_custom_step()
        cs.driver.async_get_lldp_neighbors.return_value = _lldp_table()
        cs.driver.async_do_rapid_interface_flaps.side_effect = RuntimeError(
            "flap failed"
        )
        cleanup = AsyncMock(side_effect=ValueError("restore failed"))
        with (
            self.assertRaisesRegex(ValueError, "restore failed") as raised,
            patch("time.time", return_value=0.0),
            patch.object(cs, "_restore_rapid_flap_interfaces", new=cleanup),
        ):
            await cs.fpf_rapid_flap_lldp(
                {
                    "neighbor_hosts": ["rtptest1555"],
                    "duration_sec": 30,
                    "fail_closed": True,
                    "expected_interfaces": ["eth1/4/1"],
                    "require_exact_neighbor_hosts": True,
                }
            )
        self.assertIsInstance(raised.exception.__cause__, RuntimeError)
        self.assertEqual(str(raised.exception.__cause__), "flap failed")


class TestMultiGtswRapidFlapStep(unittest.IsolatedAsyncioTestCase):
    def test_factory_serializes_fail_closed_scope(self):
        interfaces = [f"eth1/41/{channel}" for channel in range(5, 9)]
        recovery = {
            "gtsw001": {
                interface: {
                    "host": "twshared1352.03.mwg2",
                    "dev": gpu,
                    "lane": 0,
                }
                for gpu, interface in enumerate(interfaces)
            }
        }
        step = create_fpf_multi_gtsw_rapid_flap_step(
            gtsws=["gtsw001"],
            neighbor_hosts=["twshared1352.03.mwg2"],
            duration_sec=900,
            fail_closed=True,
            expected_interfaces=interfaces,
            require_exact_neighbor_hosts=True,
            nic_recovery_by_gtsw_interface=recovery,
        )
        params = _params(step)
        self.assertTrue(params["fail_closed"])
        self.assertEqual(params["expected_interfaces"], interfaces)
        self.assertEqual(params["nic_recovery_by_gtsw_interface"], recovery)

    def test_factory_serializes_delayed_strict_qsfp_churn(self):
        step = create_fpf_multi_gtsw_rapid_flap_step(
            gtsws=["gtsw001"],
            neighbor_hosts=["twshared1352.03.mwg2"],
            duration_sec=1800,
            churn_service=Service.QSFP_SERVICE,
            churn_action="crash",
            churn_every_sec=600,
            churn_initial_delay_sec=600,
            churn_recovery_timeout_sec=120,
            fail_closed=True,
            expected_interfaces=["eth1/41/5"],
        )
        params = _params(step)
        self.assertEqual(params["churn_service"], int(Service.QSFP_SERVICE.value))
        self.assertEqual(params["churn_action"], "crash")
        self.assertEqual(params["churn_every_sec"], 600)
        self.assertEqual(params["churn_initial_delay_sec"], 600)
        self.assertEqual(params["churn_recovery_timeout_sec"], 120)
        self.assertEqual(params["churn_recovery_poll_interval_sec"], 5)

    def test_factory_rejects_unknown_churn_action(self):
        with self.assertRaisesRegex(ValueError, "Unsupported service churn action"):
            create_fpf_multi_gtsw_rapid_flap_step(
                gtsws=["gtsw001"],
                duration_sec=1800,
                churn_service=Service.QSFP_SERVICE,
                churn_action="stop",
            )

    def test_factory_preserves_poll_interval_without_recovery_timeout(self):
        step = create_fpf_multi_gtsw_rapid_flap_step(
            gtsws=["gtsw001"],
            duration_sec=1800,
            churn_service=Service.QSFP_SERVICE,
            churn_recovery_poll_interval_sec=7,
        )

        self.assertEqual(_params(step)["churn_recovery_poll_interval_sec"], 7)

    async def test_qsfp_crash_recovery_waits_until_service_is_active(self):
        cs = _make_custom_step()
        driver = AsyncMock()
        driver.async_get_service_status.side_effect = [
            SystemctlServiceStatus.FAILED,
            SystemctlServiceStatus.TRANSITIONING,
            SystemctlServiceStatus.ACTIVE,
        ]
        with (
            patch("time.monotonic", side_effect=[0.0, 1.0, 2.0]),
            patch("asyncio.sleep", new=AsyncMock()) as sleep,
        ):
            await cs._wait_for_fpf_service_active(
                driver=driver,
                device="gtsw001",
                service=cs._resolve_driver_service(Service.QSFP_SERVICE),
                timeout_sec=120,
                poll_interval_sec=5,
            )
        self.assertEqual(driver.async_get_service_status.await_count, 3)
        self.assertEqual([call.args for call in sleep.await_args_list], [(5,), (5,)])

    async def test_qsfp_crash_recovery_timeout_is_strict(self):
        cs = _make_custom_step()
        driver = AsyncMock()
        driver.async_get_service_status.return_value = (
            SystemctlServiceStatus.TRANSITIONING
        )
        with (
            self.assertRaisesRegex(RuntimeError, "did not recover ACTIVE within 120s"),
            patch("time.monotonic", side_effect=[0.0, 120.0]),
        ):
            await cs._wait_for_fpf_service_active(
                driver=driver,
                device="gtsw001",
                service=cs._resolve_driver_service(Service.QSFP_SERVICE),
                timeout_sec=120,
                poll_interval_sec=5,
            )

    async def test_fail_closed_crash_path_uses_sigkill_and_verifies_recovery(self):
        cs = _make_custom_step()
        driver = AsyncMock()
        driver.async_get_service_status.return_value = SystemctlServiceStatus.ACTIVE
        qsfp_service = cs._resolve_driver_service(Service.QSFP_SERVICE)
        errors = await cs._run_fpf_service_churn_action(
            driver=driver,
            device="gtsw001",
            service=Service.QSFP_SERVICE,
            driver_service=qsfp_service,
            action="crash",
            recovery_timeout_sec=120,
            recovery_poll_interval_sec=5,
        )
        self.assertEqual(errors, [])
        driver.async_crash_service.assert_awaited_once_with(qsfp_service)
        driver.async_restart_service.assert_not_awaited()
        driver.async_get_service_status.assert_awaited_once_with(qsfp_service)

    async def test_churn_action_failure_does_not_attempt_recovery(self):
        cs = _make_custom_step()
        driver = AsyncMock()
        driver.async_crash_service.side_effect = RuntimeError("boom")
        qsfp_service = cs._resolve_driver_service(Service.QSFP_SERVICE)

        errors = await cs._run_fpf_service_churn_action(
            driver=driver,
            device="gtsw001",
            service=Service.QSFP_SERVICE,
            driver_service=qsfp_service,
            action="crash",
            recovery_timeout_sec=120,
            recovery_poll_interval_sec=5,
        )

        self.assertEqual(
            errors,
            ["gtsw001: crash QSFP_SERVICE failed: boom"],
        )
        driver.async_get_service_status.assert_not_awaited()

    async def test_fail_closed_propagates_gtsw_failure_after_cleanup(self):
        cs = _make_custom_step()
        driver = AsyncMock()
        driver.async_get_lldp_neighbors.return_value = {
            "eth1/41/5": SwitchLldpData(
                remote_device_name="twshared1352.03.mwg2",
                remote_intf_name="beth0",
            )
        }
        driver.async_do_rapid_interface_flaps.side_effect = RuntimeError("boom")
        driver.async_get_all_interfaces_admin_status.return_value = {"eth1/41/5": True}
        driver.async_get_all_interfaces_operational_status.return_value = {
            "eth1/41/5": True
        }
        with (
            self.assertRaisesRegex(Exception, "one or more GTSWs failed.*boom"),
            patch("time.time", return_value=0.0),
            patch(
                "neteng.test_infra.dne.taac.internal.steps.custom_step."
                "async_get_device_driver",
                new=AsyncMock(return_value=driver),
            ),
        ):
            await cs.fpf_multi_gtsw_rapid_flap(
                {
                    "gtsws": ["gtsw001"],
                    "neighbor_hosts": ["twshared1352.03.mwg2"],
                    "duration_sec": 30,
                    "fail_closed": True,
                    "expected_interfaces": ["eth1/41/5"],
                    "require_exact_neighbor_hosts": True,
                    "final_up_timeout_sec": 0,
                }
            )
        driver.async_thrift_disable_enable_interfaces.assert_awaited_once_with(
            interface_names=("eth1/41/5",), is_enable_port=True
        )

    async def test_fail_closed_uses_scoped_paos_for_admin_up_oper_down(self):
        cs = _make_custom_step()
        cs.driver.async_get_lldp_neighbors.return_value = _lldp_table()
        cs.driver.async_get_all_interfaces_admin_status.side_effect = [
            {"eth1/4/1": True},
            {"eth1/4/1": True},
        ]
        cs.driver.async_get_all_interfaces_operational_status.side_effect = [
            {"eth1/4/1": False},
            {"eth1/4/1": True},
        ]
        ticks = iter([0.0, 100.0])
        with (
            self.assertRaisesRegex(
                Exception,
                r"natural interface recovery exceeded 0s.*restored \['eth1/4/1'\]",
            ),
            patch("time.time", side_effect=lambda: next(ticks, 100.0)),
            patch(
                "neteng.test_infra.dne.taac.internal.steps.custom_step."
                "_fpf_async_ssh_run",
                new=AsyncMock(return_value=(0, "PAOS enabled", "")),
            ) as ssh,
        ):
            await cs.fpf_rapid_flap_lldp(
                {
                    "neighbor_hosts": ["rtptest1555"],
                    "duration_sec": 30,
                    "fail_closed": True,
                    "expected_interfaces": ["eth1/4/1"],
                    "require_exact_neighbor_hosts": True,
                    "final_up_timeout_sec": 0,
                    "nic_recovery_by_interface": {
                        "eth1/4/1": {
                            "host": "rtptest1555",
                            "dev": 0,
                            "lane": 0,
                        }
                    },
                }
            )
        self.assertEqual(ssh.await_count, 2)
        down, up = [call.args for call in ssh.await_args_list]
        self.assertEqual(down[0], "rtptest1555")
        self.assertEqual(up[0], "rtptest1555")
        self.assertIn("mstreg --yes -d 0000:03:00.0 --reg_name PAOS", down[1])
        self.assertIn("admin_status=2", down[1])
        self.assertIn("mstreg --yes -d 0000:03:00.0 --reg_name PAOS", up[1])
        self.assertIn("admin_status=1", up[1])

    async def test_scoped_paos_down_command_timeout_is_strict_failure(self):
        cs = _make_custom_step()
        interface = "eth1/41/5"
        cs.driver.async_get_all_interfaces_admin_status.return_value = {interface: True}
        cs.driver.async_get_all_interfaces_operational_status.return_value = {
            interface: False
        }
        with (
            self.assertRaisesRegex(
                RuntimeError,
                r"scoped NIC PAOS-DOWN failed.*rc=124.*timed out",
            ),
            patch(
                "neteng.test_infra.dne.taac.internal.steps.custom_step."
                "_fpf_async_ssh_run",
                new=AsyncMock(
                    side_effect=[
                        (124, "", "timed out"),
                        (0, "PAOS up", ""),
                    ]
                ),
            ) as ssh,
        ):
            await cs._restore_rapid_flap_interfaces(
                driver=cs.driver,
                device="gtsw001.l1002.c087.mwg2",
                interface_hosts={interface: "twshared1352"},
                final_up_timeout_sec=0,
                final_up_poll_interval_sec=0,
                nic_recovery_by_interface={
                    interface: {
                        "host": "twshared1352.03.mwg2",
                        "dev": 0,
                        "lane": 0,
                    }
                },
            )
        self.assertEqual(ssh.await_count, 2)
        _, command = ssh.await_args_list[0].args
        self.assertEqual(
            command,
            "mstreg --yes -d 0000:03:00.0 --reg_name PAOS "
            '--set "admin_status=2,ase=1,fd=1" -i "local_port=1"',
        )
        self.assertIn("mstreg --yes", ssh.await_args_list[1].args[1])
        self.assertIn("admin_status=1", ssh.await_args_list[1].args[1])

    async def test_scoped_paos_up_failure_retries_up_and_remains_failure(self):
        cs = _make_custom_step()
        interface = "eth1/41/5"
        cs.driver.async_get_all_interfaces_admin_status.return_value = {interface: True}
        cs.driver.async_get_all_interfaces_operational_status.side_effect = [
            {interface: False},
            {interface: True},
        ]
        with (
            self.assertRaisesRegex(
                RuntimeError,
                r"PAOS-UP failed.*rc=124.*final switch-state readback: all "
                r"touched interfaces UP",
            ),
            patch(
                "neteng.test_infra.dne.taac.internal.steps.custom_step."
                "_fpf_async_ssh_run",
                new=AsyncMock(
                    side_effect=[
                        (0, "PAOS down", ""),
                        (124, "", "timed out"),
                        (0, "PAOS up", ""),
                    ]
                ),
            ) as ssh,
        ):
            await cs._restore_rapid_flap_interfaces(
                driver=cs.driver,
                device="gtsw001.l1002.c087.mwg2",
                interface_hosts={interface: "twshared1352"},
                final_up_timeout_sec=0,
                final_up_poll_interval_sec=0,
                nic_recovery_by_interface={
                    interface: {
                        "host": "twshared1352.03.mwg2",
                        "dev": 0,
                        "lane": 0,
                    }
                },
            )
        self.assertEqual(ssh.await_count, 3)
        commands = [call.args[1] for call in ssh.await_args_list]
        self.assertIn("admin_status=2", commands[0])
        self.assertIn("admin_status=1", commands[1])
        self.assertIn("admin_status=1", commands[2])
        self.assertTrue(all("mstreg --yes" in command for command in commands))

    async def test_scoped_paos_recovers_every_latched_interface_on_same_host(self):
        cs = _make_custom_step()
        interfaces = [f"eth1/41/{channel}" for channel in range(5, 9)]
        interface_hosts = dict.fromkeys(interfaces, "twshared1352")
        cs.driver.async_get_all_interfaces_admin_status.side_effect = [
            dict.fromkeys(interfaces, True),
            dict.fromkeys(interfaces, True),
        ]
        cs.driver.async_get_all_interfaces_operational_status.side_effect = [
            dict.fromkeys(interfaces, False),
            dict.fromkeys(interfaces, True),
        ]
        recovery = {
            interface: {
                "host": "twshared1352.03.mwg2",
                "dev": gpu,
                "lane": 0,
            }
            for gpu, interface in enumerate(interfaces)
        }
        with (
            self.assertRaisesRegex(
                Exception,
                r"natural interface recovery exceeded 0s.*eth1/41/5.*eth1/41/8",
            ),
            patch(
                "neteng.test_infra.dne.taac.internal.steps.custom_step."
                "_fpf_async_ssh_run",
                new=AsyncMock(return_value=(0, "PAOS enabled", "")),
            ) as ssh,
        ):
            await cs._restore_rapid_flap_interfaces(
                driver=cs.driver,
                device="gtsw001.l1002.c087.mwg2",
                interface_hosts=interface_hosts,
                final_up_timeout_sec=0,
                final_up_poll_interval_sec=0,
                nic_recovery_by_interface=recovery,
            )
        self.assertEqual(ssh.await_count, 8)
        commands = [call.args[1] for call in ssh.await_args_list]
        for bdf in (
            "0000:03:00.0",
            "0002:03:00.0",
            "0010:03:00.0",
            "0012:03:00.0",
        ):
            self.assertTrue(
                any(f"mstreg --yes -d {bdf}" in command for command in commands)
            )
        for down, up in zip(commands[::2], commands[1::2]):
            self.assertIn("admin_status=2", down)
            self.assertIn("admin_status=1", up)

    async def test_fail_closed_cleanup_survives_cancellation(self):
        cs = _make_custom_step()
        cs.driver.async_get_lldp_neighbors.return_value = _lldp_table()
        cs.driver.async_do_rapid_interface_flaps.side_effect = asyncio.CancelledError
        cs.driver.async_get_all_interfaces_admin_status.return_value = {
            "eth1/4/1": True
        }
        cs.driver.async_get_all_interfaces_operational_status.return_value = {
            "eth1/4/1": True
        }
        with (
            self.assertRaises(asyncio.CancelledError),
            patch("time.time", return_value=0.0),
        ):
            await cs.fpf_rapid_flap_lldp(
                {
                    "neighbor_hosts": ["rtptest1555"],
                    "duration_sec": 30,
                    "fail_closed": True,
                    "expected_interfaces": ["eth1/4/1"],
                    "require_exact_neighbor_hosts": True,
                }
            )
        cs.driver.async_thrift_disable_enable_interfaces.assert_awaited_once_with(
            interface_names=("eth1/4/1",), is_enable_port=True
        )


class TestLldpBatchedSetInterfaceAdminStep(unittest.IsolatedAsyncioTestCase):
    def test_factory_shape(self):
        step = create_fpf_lldp_batched_set_interface_admin_step(
            neighbor_pattern="gtsw001*",
            enable=False,
            device_regexes=["stsw001.s001.l202.mwg2"],
        )
        self.assertEqual(step.name, StepName.CUSTOM_STEP)
        self.assertEqual(list(step.device_regexes), ["stsw001.s001.l202.mwg2"])
        p = _params(step)
        self.assertEqual(p["custom_step_name"], "fpf_lldp_batched_set_interface_admin")
        self.assertEqual(p["neighbor_pattern"], "gtsw001*")
        self.assertFalse(p["is_enable"])
        # No pre-resolved interface list.
        self.assertNotIn("interfaces", p)

    async def test_batched_disable_calls_thrift_once_with_resolved_list(self):
        cs = _make_custom_step()
        cs.driver.async_get_lldp_neighbors.return_value = _lldp_table()
        await cs.fpf_lldp_batched_set_interface_admin(
            {"neighbor_pattern": "gtsw001*", "is_enable": False}
        )
        # ONE batched thrift call over the resolved set.
        cs.driver.async_thrift_disable_enable_interfaces.assert_awaited_once_with(
            interface_names=("eth1/1/1", "eth1/2/1"),
            is_enable_port=False,
        )

    async def test_batched_enable_calls_thrift_once(self):
        cs = _make_custom_step()
        cs.driver.async_get_lldp_neighbors.return_value = _lldp_table()
        await cs.fpf_lldp_batched_set_interface_admin(
            {"neighbor_pattern": "rtptest*", "is_enable": True}
        )
        cs.driver.async_thrift_disable_enable_interfaces.assert_awaited_once_with(
            interface_names=("eth1/4/1",),
            is_enable_port=True,
        )

    async def test_no_match_raises(self):
        cs = _make_custom_step()
        cs.driver.async_get_lldp_neighbors.return_value = _lldp_table()
        with self.assertRaises(RuntimeError):
            await cs.fpf_lldp_batched_set_interface_admin(
                {"neighbor_pattern": "nomatch*", "is_enable": False}
            )
        cs.driver.async_thrift_disable_enable_interfaces.assert_not_awaited()


class TestNicMstregFlapStep(unittest.IsolatedAsyncioTestCase):
    def test_factory_shape(self):
        step = create_fpf_nic_mstreg_flap_step(
            host="rtptest1555.mwg2",
            dev=0,
            lane=0,
            iterations=5,
            interval_sec=2.0,
        )
        self.assertEqual(step.name, StepName.CUSTOM_STEP)
        # Host-side step — no device_regexes (GPU hosts aren't FBOSS DUTs).
        self.assertFalse(list(step.device_regexes or []))
        p = _params(step)
        self.assertEqual(p["custom_step_name"], "fpf_nic_mstreg_flap")
        self.assertEqual(p["host"], "rtptest1555.mwg2")
        self.assertEqual(p["dev"], 0)
        self.assertEqual(p["lane"], 0)
        self.assertEqual(p["iterations"], 5)
        self.assertEqual(p["interval_sec"], 2.0)

    def test_bdf_mapping_for_several_dev_lane_pairs(self):
        # The handler computes the BDF deterministically (no ethtool) via
        # _nic_mstreg_bdf: BDF = "<DEV_BLOCK>:03:00.<LANE>".
        self.assertEqual(_nic_mstreg_bdf(0, 1), "0000:03:00.1")
        self.assertEqual(_nic_mstreg_bdf(2, 7), "0010:03:00.7")
        self.assertEqual(_nic_mstreg_bdf(1, 0), "0002:03:00.0")
        self.assertEqual(_nic_mstreg_bdf(3, 3), "0012:03:00.3")

    def test_bdf_mapping_raises_out_of_range(self):
        with self.assertRaises(ValueError):
            _nic_mstreg_bdf(4, 0)  # dev > 3
        with self.assertRaises(ValueError):
            _nic_mstreg_bdf(-1, 0)  # dev < 0
        with self.assertRaises(ValueError):
            _nic_mstreg_bdf(0, 8)  # lane > 7
        with self.assertRaises(ValueError):
            _nic_mstreg_bdf(0, -1)  # lane < 0

    async def test_handler_runs_mstreg_cycles_with_deterministic_bdf(self):
        cs = _make_custom_step()
        # Capture every ssh-run call (host, cmd): alternating mstreg DOWN/UP.
        # No ethtool probe — the BDF is computed deterministically.
        calls: list[tuple[str, str]] = []

        async def fake_ssh(host, cmd, timeout_sec=30):
            calls.append((host, cmd))
            return (0, "", "")

        sleeps: list[float] = []

        async def fake_sleep(d):
            sleeps.append(d)

        cs._ssh_run_host = fake_ssh

        with patch("asyncio.sleep", side_effect=fake_sleep):
            await cs.fpf_nic_mstreg_flap(
                {
                    "host": "rtptest1555.mwg2",
                    "dev": 0,
                    "lane": 1,
                    "iterations": 3,
                    "interval_sec": 2.0,
                }
            )

        # No ethtool: 6 mstreg (3 DOWN + 3 UP) = 6 total ssh calls.
        self.assertEqual(len(calls), 6)
        self.assertFalse(any("ethtool" in cmd for _, cmd in calls))

        # dev=0 lane=1 -> BDF 0000:03:00.1; calls alternate DOWN then UP.
        expected_bdf = "0000:03:00.1"
        expected_down = (
            f"mstreg -d {expected_bdf} --reg_name PAOS "
            f'--set "admin_status=2,ase=1,fd=1" -i "local_port=1"'
        )
        expected_up = (
            f"mstreg -d {expected_bdf} --reg_name PAOS "
            f'--set "admin_status=1,ase=1,fd=1" -i "local_port=1"'
        )
        self.assertEqual(calls[0], ("rtptest1555.mwg2", expected_down))
        self.assertEqual(calls[1], ("rtptest1555.mwg2", expected_up))
        self.assertEqual(calls[2], ("rtptest1555.mwg2", expected_down))
        self.assertEqual(calls[3], ("rtptest1555.mwg2", expected_up))
        self.assertEqual(calls[4], ("rtptest1555.mwg2", expected_down))
        self.assertEqual(calls[5], ("rtptest1555.mwg2", expected_up))

        # One sleep after every DOWN and after every UP -> 6 sleeps of 2.0s.
        self.assertEqual(sleeps, [2.0] * 6)

    async def test_handler_uses_bdf_for_dev2_lane7(self):
        cs = _make_custom_step()
        seen_cmds = []

        async def fake_ssh(host, cmd, timeout_sec=30):
            seen_cmds.append(cmd)
            return (0, "", "")

        cs._ssh_run_host = fake_ssh
        with patch("asyncio.sleep", new=AsyncMock()):
            await cs.fpf_nic_mstreg_flap(
                {
                    "host": "rtptest1555.mwg2",
                    "dev": 2,
                    "lane": 7,
                    "iterations": 1,
                    "interval_sec": 0.0,
                }
            )
        # dev=2 lane=7 -> BDF 0010:03:00.7; every mstreg cmd carries it.
        self.assertTrue(seen_cmds)
        self.assertTrue(all("-d 0010:03:00.7 " in cmd for cmd in seen_cmds))

    async def test_handler_raises_on_out_of_range_dev_or_lane(self):
        cs = _make_custom_step()

        async def fake_ssh(host, cmd, timeout_sec=30):
            return (0, "", "")

        cs._ssh_run_host = fake_ssh
        with self.assertRaises(ValueError):
            await cs.fpf_nic_mstreg_flap(
                {
                    "host": "rtptest1555.mwg2",
                    "dev": 4,
                    "lane": 0,
                    "iterations": 1,
                    "interval_sec": 0.0,
                }
            )
        with self.assertRaises(ValueError):
            await cs.fpf_nic_mstreg_flap(
                {
                    "host": "rtptest1555.mwg2",
                    "dev": 0,
                    "lane": 8,
                    "iterations": 1,
                    "interval_sec": 0.0,
                }
            )


class TestStswDrainAndReinjectSteps(unittest.IsolatedAsyncioTestCase):
    def test_split_vf_groups_keep_prefix_bases_and_target_scope(self):
        stsw = "stsw001.s001.c085.ash6"
        steps = create_fpf_stsw_drain_and_reinject_steps(
            stsw=stsw,
            drained=True,
            trigger_stsws=[stsw],
            prefix_count=1000,
            community_list="stsw",
            drain_community="65446:10",
            injection_groups=[
                {
                    "devices": ["stsw001.s001.c085.ash6"],
                    "prefix_base": "5000:dd::/64",
                    "count": 4032,
                    "batch_size": 252,
                },
                {
                    "devices": ["stsw001.s005.c085.ash6"],
                    "prefix_base": "5000:ee::/64",
                    "count": 4032,
                    "batch_size": 252,
                },
            ],
        )
        self.assertEqual(len(steps), 3)
        self.assertEqual(list(steps[0].device_regexes or []), [stsw])
        injections = [_params(step) for step in steps[1:]]
        self.assertEqual(
            [params["prefix_base"] for params in injections],
            ["5000:dd::/64", "5000:ee::/64"],
        )
        self.assertTrue(
            all(params["community_list"] == "stsw 65446:10" for params in injections)
        )
        self.assertTrue(all(params["batch_size"] == 252 for params in injections))

    def test_drain_appends_drain_community_and_orders_steps(self):
        steps = create_fpf_stsw_drain_and_reinject_steps(
            stsw="stsw001.s001.c085.ash6",
            drained=True,
            trigger_stsws=["stsw001.s001.c085.ash6"],
            prefix_count=20000,
            community_list="65000:1",
            drain_community="65000:999",
        )
        self.assertEqual(len(steps), 2)
        # First step: drain/undrain (LOCAL_DRAINER).
        self.assertEqual(steps[0].name, StepName.DRAIN_UNDRAIN_STEP)
        # Second step: prefix injection with the appended drain community.
        self.assertEqual(steps[1].name, StepName.FPF_BGP_PREFIX_INJECTION_STEP)
        inj = _params(steps[1])
        self.assertEqual(inj["community_list"], "65000:1 65000:999")
        self.assertEqual(inj["count"], 20000)
        self.assertEqual(inj["devices"], ["stsw001.s001.c085.ash6"])

    def test_undrain_uses_base_community_only(self):
        steps = create_fpf_stsw_drain_and_reinject_steps(
            stsw="stsw001.s001.c085.ash6",
            drained=False,
            trigger_stsws=["stsw001.s001.c085.ash6"],
            prefix_count=20000,
            community_list="65000:1",
            drain_community="65000:999",
        )
        self.assertEqual(steps[0].name, StepName.DRAIN_UNDRAIN_STEP)
        inj = _params(steps[1])
        # Undrain: drain_community is ignored.
        self.assertEqual(inj["community_list"], "65000:1")


if __name__ == "__main__":
    unittest.main()
