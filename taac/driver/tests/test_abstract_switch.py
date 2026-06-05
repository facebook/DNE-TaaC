# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe
import logging
import unittest
from collections import Counter
from unittest.mock import AsyncMock, patch

from taac.driver.abstract_switch import AbstractSwitch
from taac.driver.driver_constants import (
    BgpSessionState,
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
