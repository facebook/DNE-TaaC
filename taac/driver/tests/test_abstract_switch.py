# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
import logging
import unittest
from collections import Counter
from unittest.mock import AsyncMock, patch

from taac.driver.abstract_switch import AbstractSwitch
from taac.driver.driver_constants import (
    BgpSessionState,
    describe_interface_state,
    InterfaceEventState,
    InterfaceState,
    SystemAvailability,
)


class _TestSwitch(AbstractSwitch):
    """Minimal concrete subclass for testing AbstractSwitch concrete methods."""

    async def async_get_interfaces_status(self, interface_names, skip_logging=False):
        return {}

    async def _async_modify_bgp_nbr(self, peer_ip_addr, bgp_peer_action):
        pass

    async def async_register_patcher_to_shut_ports_persistently(
        self, patcher_name, interfaces, additional_desc=None
    ):
        pass

    async def async_add_static_route_patcher(
        self,
        prefix_to_next_hops_map,
        patcher_name,
        patcher_desc="",
        is_patcher_name_uuid_needed=True,
    ):
        return patcher_name

    async def async_coop_unregister_patchers(self, patcher_name, config_name=None):
        pass

    async def async_unregister_patcher_to_shut_ports_persistently(
        self, patcher_name, interfaces
    ):
        pass

    async def async_get_fib_table_entries_count(self):
        return 0

    async def async_get_fib_table_entries(self):
        pass

    async def async_get_bgp_rx_prefix_count_per_intf(self, interface_name):
        return 0

    async def async_get_fboss_build_info_show(self):
        return ""

    async def async_read_file(self, file_location):
        return ""

    async def async_generate_everpaste_file_url(self, file_location):
        return None

    async def aysnc_collect_critical_core_dumps_logs(self, core_file_name):
        pass

    async def async_get_ip_route(self, ip, print_interfaces=True):
        return None

    async def _async_is_onbox_drained_helper(self):
        pass

    async def async_get_processes_top(self):
        return {}

    async def async_get_static_routes(self, address_family="both"):
        return {}

    async def async_get_multiple_intfs_bgp_session_state(self, interface_names):
        return {}


class TestAbstractSwitchInit(unittest.TestCase):
    def test_init_sets_hostname(self):
        """Test that __init__ correctly sets the hostname."""
        logger = logging.getLogger("test")
        switch = _TestSwitch("fsw001.p001.f01.snc1", logger=logger)
        self.assertEqual(switch.hostname, "fsw001.p001.f01.snc1")

    def test_init_generates_oob_hostname(self):
        """Test that OOB hostname is correctly generated."""
        logger = logging.getLogger("test")
        switch = _TestSwitch("fsw001.p001.f01.snc1", logger=logger)
        self.assertEqual(switch.oob_hostname, "fsw001-oob.p001.f01.snc1")

    def test_init_oob_hostname_already_oob(self):
        """Test that OOB hostname is not modified if already -oob."""
        logger = logging.getLogger("test")
        switch = _TestSwitch("fsw001-oob.p001.f01.snc1", logger=logger)
        self.assertEqual(switch.oob_hostname, "fsw001-oob.p001.f01.snc1")

    def test_init_raises_without_logger(self):
        """Test that __init__ raises if logger is None."""
        from taac.driver.abstract_switch import TestingException

        with self.assertRaises(TestingException):
            _TestSwitch("fsw001.p001.f01.snc1", logger=None)


class TestCheckSystemReachability(unittest.TestCase):
    def setUp(self):
        self.logger = logging.getLogger("test")
        self.switch = _TestSwitch("fsw001.p001.f01.snc1", logger=self.logger)

    @patch.object(_TestSwitch, "get_system_reachability_status", return_value=0)
    def test_reachable_passes(self, mock_status):
        """Test check_system_reachability passes when device is reachable."""
        self.switch.check_system_reachability(SystemAvailability.REACHABLE)
        mock_status.assert_called()

    @patch.object(_TestSwitch, "get_system_reachability_status", return_value=1)
    def test_unreachable_passes(self, mock_status):
        """Test check_system_reachability passes when device is unreachable."""
        self.switch.check_system_reachability(SystemAvailability.UNREACHABLE)
        mock_status.assert_called()


class TestCompareBgpNeighborStates(unittest.TestCase):
    def setUp(self):
        self.logger = logging.getLogger("test")
        self.switch = _TestSwitch("fsw001.p001.f01.snc1", logger=self.logger)

    @patch.object(_TestSwitch, "get_all_bgp_session_states")
    def test_stable_state_passes(self, mock_get_states):
        """Test compare_all_bgp_neighbor_states passes in STABLE state when sessions match."""
        bgp_sess_stable = Counter({"estab_peers": 10, "non_estab_peers": 0})
        mock_get_states.return_value = Counter(
            {"estab_peers": 10, "non_estab_peers": 0}
        )
        self.switch.compare_all_bgp_neighbor_states(
            bgp_sess_stable, BgpSessionState.STABLE
        )
        mock_get_states.assert_called()

    @patch.object(_TestSwitch, "get_all_bgp_session_states")
    def test_unstable_state_passes(self, mock_get_states):
        """Test compare_all_bgp_neighbor_states passes in UNSTABLE state."""
        bgp_sess_stable = Counter({"estab_peers": 10, "non_estab_peers": 0})
        mock_get_states.return_value = Counter({"estab_peers": 5, "non_estab_peers": 5})
        self.switch.compare_all_bgp_neighbor_states(
            bgp_sess_stable, BgpSessionState.UNSTABLE
        )
        mock_get_states.assert_called()


class TestAsyncCompareFibCounts(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.logger = logging.getLogger("test")
        self.switch = _TestSwitch("fsw001.p001.f01.snc1", logger=self.logger)

    async def test_fib_count_passes_when_above_threshold(self):
        """Test async_compare_fib_counts passes when current count >= expected."""
        self.switch.async_get_fib_table_entries_count = AsyncMock(return_value=1000)
        # FIB_COUNT_ALLOWED_OFFSET is 0.95 by default, so threshold = 950
        await self.switch.async_compare_fib_counts(expected_fib_count=1000)
        self.switch.async_get_fib_table_entries_count.assert_awaited_once()

    @patch("asyncio.sleep", new_callable=AsyncMock)
    async def test_fib_count_raises_when_below_threshold(self, mock_sleep):
        """Test async_compare_fib_counts raises TestingException when count too low."""
        from taac.driver.abstract_switch import TestingException

        self.switch.async_get_fib_table_entries_count = AsyncMock(return_value=100)
        with self.assertRaises(TestingException):
            await self.switch.async_compare_fib_counts(expected_fib_count=1000)


class TestIsCriticalCoreDumps(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.logger = logging.getLogger("test")
        self.switch = _TestSwitch("fsw001.p001.f01.snc1", logger=self.logger)

    async def test_critical_core_dump_detected(self):
        """Test that a core dump matching the allow list is detected."""
        result = await self.switch.async_is_critical_core_dumps(
            "wedge_agent.core.12345", ["wedge_agent"]
        )
        self.assertTrue(result)

    async def test_non_critical_core_dump(self):
        """Test that a core dump not matching the allow list is ignored."""
        result = await self.switch.async_is_critical_core_dumps(
            "some_random.core.12345", ["wedge_agent"]
        )
        self.assertFalse(result)


class TestDescribeInterfaceState(unittest.TestCase):
    def test_admin_enabled_and_oper_down_blames_the_far_end(self):
        """A port the device enabled but that never linked is not the device's fault."""
        described = describe_interface_state(
            InterfaceState(
                oper_up=False,
                admin_enabled=True,
                speed_mbps=400000,
                profile_id="PROFILE_400G_8_PAM4_RS544X2N_OPTICAL",
                has_transceiver=True,
            )
        )
        self.assertIn("admin=enabled oper=down", described)
        self.assertIn("speed=400000Mbps", described)
        self.assertIn("profile=PROFILE_400G_8_PAM4_RS544X2N_OPTICAL", described)
        self.assertIn("transceiver=present", described)
        self.assertIn("check the far end, the cable and the optics", described)

    def test_admin_disabled_and_oper_down_blames_the_device(self):
        """A port the device never enabled cannot be a far end problem."""
        described = describe_interface_state(
            InterfaceState(oper_up=False, admin_enabled=False, has_transceiver=True)
        )
        self.assertIn("admin=disabled oper=down", described)
        self.assertIn("The device never enabled the port", described)
        self.assertIn("COOP config that failed to activate", described)
        self.assertNotIn("check the far end", described)

    def test_missing_transceiver_is_called_out_separately(self):
        described = describe_interface_state(
            InterfaceState(oper_up=False, admin_enabled=True, has_transceiver=False)
        )
        self.assertIn("transceiver=absent", described)
        self.assertIn("reports no transceiver", described)

    def test_unknown_admin_state_is_reported_as_unknown(self):
        """An aggregated interface has no admin state, so none is invented."""
        described = describe_interface_state(InterfaceState(oper_up=False))
        self.assertIn("admin=unknown oper=down", described)
        self.assertIn("check its member ports", described)
        self.assertNotIn("admin=disabled", described)
        self.assertNotIn("admin=enabled", described)

    def test_up_interface_carries_no_cause_hint(self):
        described = describe_interface_state(
            InterfaceState(oper_up=True, admin_enabled=True, speed_mbps=400000)
        )
        self.assertEqual("admin=enabled oper=up speed=400000Mbps", described)

    def test_absent_optional_fields_are_omitted(self):
        described = describe_interface_state(
            InterfaceState(oper_up=True, admin_enabled=True)
        )
        self.assertEqual("admin=enabled oper=up", described)


@patch("asyncio.sleep", new_callable=AsyncMock)
class TestCheckInterfaceStatusMessage(unittest.IsolatedAsyncioTestCase):
    """The assertion message is the deliverable, so it is what gets asserted on."""

    def setUp(self):
        self.switch = _TestSwitch(
            "rsw001.p001.f01.snc1", logger=logging.getLogger("test")
        )

    def _observe(self, state: InterfaceState) -> None:
        self.switch.async_get_interfaces_state = AsyncMock(
            return_value={"eth1/1/1": state}
        )

    async def _expect_up_failure(self, state: InterfaceState) -> str:
        self._observe(state)
        with self.assertRaises(AssertionError) as raised:
            await self.switch.async_check_interface_status(
                "eth1/1/1", InterfaceEventState.STABLE
            )
        return str(raised.exception)

    async def test_admin_enabled_oper_down_names_the_far_end(self, _mock_sleep):
        message = await self._expect_up_failure(
            InterfaceState(
                oper_up=False,
                admin_enabled=True,
                speed_mbps=400000,
                profile_id="PROFILE_400G_8_PAM4_RS544X2N_OPTICAL",
                has_transceiver=True,
            )
        )
        self.assertIn(
            "rsw001.p001.f01.snc1:eth1/1/1 is not operationally up: "
            "admin=enabled oper=down speed=400000Mbps "
            "profile=PROFILE_400G_8_PAM4_RS544X2N_OPTICAL transceiver=present. "
            "The device has the port enabled, so the device side is configured; "
            "check the far end, the cable and the optics.",
            message,
        )

    async def test_admin_disabled_oper_down_names_the_device(self, _mock_sleep):
        message = await self._expect_up_failure(
            InterfaceState(oper_up=False, admin_enabled=False, has_transceiver=True)
        )
        self.assertIn(
            "rsw001.p001.f01.snc1:eth1/1/1 is not operationally up: "
            "admin=disabled oper=down transceiver=present. "
            "The device never enabled the port, so it cannot link up whatever "
            "the far end does; check the device configuration, for example a "
            "COOP config that failed to activate.",
            message,
        )

    async def test_aggregated_interface_reports_unknown_admin(self, _mock_sleep):
        message = await self._expect_up_failure(InterfaceState(oper_up=False))
        self.assertIn(
            "rsw001.p001.f01.snc1:eth1/1/1 is not operationally up: "
            "admin=unknown oper=down. "
            "Admin state is not reported for this kind of interface, so the "
            "cause cannot be attributed to a side; check its member ports.",
            message,
        )

    async def test_up_interface_passes_the_stable_check(self, _mock_sleep):
        self._observe(InterfaceState(oper_up=True, admin_enabled=True))
        await self.switch.async_check_interface_status(
            "eth1/1/1", InterfaceEventState.STABLE
        )

    async def test_unstable_check_reports_both_states(self, _mock_sleep):
        self._observe(InterfaceState(oper_up=True, admin_enabled=True))
        with self.assertRaises(AssertionError) as raised:
            await self.switch.async_check_interface_status(
                "eth1/1/1", InterfaceEventState.UNSTABLE
            )
        self.assertIn(
            "rsw001.p001.f01.snc1:eth1/1/1 is not operationally down: "
            "admin=enabled oper=up",
            str(raised.exception),
        )


@patch("asyncio.sleep", new_callable=AsyncMock)
class TestCheckInterfacesStatusMessage(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.switch = _TestSwitch(
            "rsw001.p001.f01.snc1", logger=logging.getLogger("test")
        )

    async def test_mismatch_lists_admin_and_oper_per_interface(self, _mock_sleep):
        self.switch.async_get_interfaces_state = AsyncMock(
            return_value={
                "eth1/1/1": InterfaceState(oper_up=False, admin_enabled=False),
                "eth1/1/2": InterfaceState(oper_up=False, admin_enabled=True),
                "eth1/1/3": InterfaceState(oper_up=True, admin_enabled=True),
            }
        )
        with self.assertRaises(Exception) as raised:
            await self.switch.async_check_interfaces_status(
                ["eth1/1/1", "eth1/1/2", "eth1/1/3"], True
            )
        message = str(raised.exception)
        self.assertIn(
            "Interface state mismatch on rsw001.p001.f01.snc1, expected oper=up",
            message,
        )
        self.assertIn("'eth1/1/1': 'admin=disabled oper=down.", message)
        self.assertIn("'eth1/1/2': 'admin=enabled oper=down.", message)
        self.assertNotIn("eth1/1/3", message)

    async def test_all_up_passes(self, _mock_sleep):
        self.switch.async_get_interfaces_state = AsyncMock(
            return_value={"eth1/1/1": InterfaceState(oper_up=True, admin_enabled=True)}
        )
        await self.switch.async_check_interfaces_status(["eth1/1/1"], True)


class TestAbstractSwitchInterfaceStateFallback(unittest.IsolatedAsyncioTestCase):
    async def test_driver_without_admin_state_reports_unknown(self):
        """Drivers that only expose oper state must not imply an admin state."""
        switch = _TestSwitch("rsw001.p001.f01.snc1", logger=logging.getLogger("test"))
        switch.async_get_interfaces_status = AsyncMock(
            return_value={"eth1/1/1": False, "eth1/1/2": True}
        )
        states = await switch.async_get_interfaces_state(["eth1/1/1", "eth1/1/2"])
        self.assertEqual(
            {
                "eth1/1/1": InterfaceState(oper_up=False),
                "eth1/1/2": InterfaceState(oper_up=True),
            },
            states,
        )
        self.assertIsNone(states["eth1/1/1"].admin_enabled)
