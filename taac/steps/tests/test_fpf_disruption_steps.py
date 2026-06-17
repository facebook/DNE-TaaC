# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe
import json
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from neteng.test_infra.dne.taac.constants import TestDevice, TestTopology
from taac.driver.driver_constants import SwitchLldpData
from taac.internal.steps.custom_step import (
    _nic_mstreg_bdf,
    CustomStep,
)
from taac.libs.parameter_evaluator import ParameterEvaluator
from taac.steps.step_definitions import (
    create_fpf_lldp_batched_set_interface_admin_step,
    create_fpf_ndp_clear_loop_step,
    create_fpf_nic_mstreg_flap_step,
    create_fpf_rapid_flap_step,
    create_fpf_rapid_flap_step_lldp,
    create_fpf_repeated_service_crash_step,
    create_fpf_stsw_drain_and_reinject_steps,
)
from taac.test_as_a_config.thrift_types import Service, Step, StepName, TestConfig


def _make_custom_step(hostname: str = "gtsw001.l1001.c085.ash6"):
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


def _params(step: Step) -> dict:
    # `step.step_params` and `.json_params` are typed as Optional in the
    # generated Thrift; assert both exist in test context (factories always
    # populate them).
    # pyrefly: ignore [missing-attribute]
    assert step.step_params is not None
    assert step.step_params.json_params is not None
    return json.loads(step.step_params.json_params)


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


class TestNdpClearLoopStep(unittest.IsolatedAsyncioTestCase):
    def test_factory_shape(self):
        step = create_fpf_ndp_clear_loop_step(
            every_sec=1, duration_sec=120, device_regexes=["gtsw001.*"]
        )
        self.assertEqual(step.name, StepName.CUSTOM_STEP)
        p = _params(step)
        self.assertEqual(p["custom_step_name"], "fpf_ndp_clear_loop")
        self.assertEqual(p["every_sec"], 1)
        self.assertEqual(p["duration_sec"], 120)

    async def test_clears_expected_number_of_times(self):
        cs = _make_custom_step()
        ticks = [0.0] + [float(i) for i in range(120)] + [1000.0]

        async def fake_sleep(d):
            pass

        with (
            patch("time.time", side_effect=ticks),
            patch("asyncio.sleep", side_effect=fake_sleep),
        ):
            await cs.fpf_ndp_clear_loop({"every_sec": 1, "duration_sec": 120})

        self.assertEqual(cs.driver.async_run_cmd_on_shell.await_count, 120)
        for call in cs.driver.async_run_cmd_on_shell.await_args_list:
            self.assertEqual(call.args[0], "fboss2 clear ndp")


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
        # neighbor_hosts unset -> None; default flap down-time 6s passed through.
        self.assertIsNone(p["neighbor_hosts"])
        self.assertEqual(p["down_time_sec"], 6.0)
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
        # The glob is still carried as a fallback.
        self.assertEqual(p["neighbor_pattern"], "rtptest*")
        self.assertEqual(p["down_time_sec"], 6.0)

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
        # Two single-flap iterations, each with total_flaps=1 and down_time=6.
        self.assertEqual(cs.driver.async_do_rapid_interface_flaps.await_count, 2)
        for call in cs.driver.async_do_rapid_interface_flaps.await_args_list:
            self.assertEqual(
                call.kwargs,
                {
                    "interface_names": ("eth1/1/1", "eth1/2/1"),
                    "interval_to_link_up": 5,
                    "total_flaps": 1,
                    "down_time_sec": 6.0,
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
