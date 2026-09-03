# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""Unit tests for the RBB SRv6 qualification tasks.

Lives under ``taac/playbooks/routing/tests`` (not ``taac/tasks/tests``) because
the OSS pytest harness excludes the whole ``taac/tasks`` tree from collection
(``conftest.py`` ``_NON_OSS_TEST_DIRS``); placing the file here is what actually
gets it run. The modules under test are imported by absolute path, so their
real home in ``taac/tasks`` is unaffected.
"""

import socket
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from taac.constants import TestCaseFailure
from taac.tasks.rbb_core_interface_setup_task import RbbCoreInterfaceSetupTask
from taac.tasks.rbb_edge_ebgp_task import RbbEdgeEbgpTask
from taac.tasks.rbb_srv6_counter_delta_task import RbbSrv6CounterDeltaTask
from taac.tasks.rbb_srv6_direct_route_task import RbbSrv6DirectRouteTask
from taac.tasks.rbb_srv6_program_task import RbbSrv6ProgramTask
from taac.tasks.rbb_srv6_verify_task import RbbSrv6VerifyTask
from taac.tasks.registry import TASK_NAME_TO_CLASS
from taac.testconfigs.routing.util.fboss_config_gen.bgp_config import (
    add_edge_ebgp_peer,
    EDGE_EBGP_PEER_GROUP,
    enable_ipv6_afi_on_ibgp,
)

_VERIFY_PATH = "taac.tasks.rbb_srv6_verify_task.async_get_device_driver"
_PROGRAM_PATH = "taac.tasks.rbb_srv6_program_task.async_get_device_driver"
_DIRECT_PATH = "taac.tasks.rbb_srv6_direct_route_task.async_get_device_driver"
_CORE_PATH = "taac.tasks.rbb_core_interface_setup_task.async_get_device_driver"
_COUNTER_PATH = "taac.tasks.rbb_srv6_counter_delta_task.async_get_device_driver"
_EDGE_MOD = "taac.tasks.rbb_edge_ebgp_task"
_EDGE_PATH = f"{_EDGE_MOD}.async_get_device_driver"


def _ibgp_bgp_json() -> dict:
    """A minimal iBGP-only bgp.json shaped like the tail box (v6 AFI disabled)."""
    return {
        "local_as_4_byte": 65001,
        "router_id": "8.8.8.8",
        "networks4": [{"prefix": "8.8.8.8/32"}],
        "networks6": [],
        "peer_groups": [
            {
                "name": "C8501-SIMPLE-IBGP-V4",
                "remote_as_4_byte": 65001,
                "next_hop_self": True,
                "disable_ipv4_afi": False,
                "disable_ipv6_afi": True,
            }
        ],
        "peers": [
            {
                "peer_addr": "9.9.9.9",
                "peer_group_name": "C8501-SIMPLE-IBGP-V4",
                "local_addr": "8.8.8.8",
                "next_hop6": "::",
                "remote_as_4_byte": 65001,
            }
        ],
    }


class RbbTaskRegistrationTest(unittest.TestCase):
    def test_all_rbb_tasks_registered(self) -> None:
        for name in (
            "rbb_core_interface_setup",
            "rbb_srv6_program",
            "rbb_srv6_direct_route",
            "rbb_ixia_edge_l3",
            "rbb_srv6_verify",
            "rbb_srv6_counter_delta",
            "rbb_edge_ebgp",
            "provision_fboss_agent_config",
            "provision_fboss_bgp_config",
            "provision_fboss_openr_config",
        ):
            self.assertIn(name, TASK_NAME_TO_CLASS)


class RbbSrv6VerifyTaskTest(unittest.IsolatedAsyncioTestCase):
    def _driver(self, output: str) -> MagicMock:
        driver = MagicMock()
        driver.async_run_cmd_on_shell = AsyncMock(return_value=output)
        return driver

    async def test_passes_when_expected_present(self) -> None:
        task = RbbSrv6VerifyTask(hostname="rbb-r2", logger=MagicMock())
        driver = self._driver("route 2001:db8:cafe::/48 owner te_agent via ...")
        with patch(_VERIFY_PATH, new_callable=AsyncMock, return_value=driver):
            await task.run(
                {
                    "hostname": "rbb-r2",
                    "show_cmd": "show ipv6 route",
                    "expect_contains": ["te_agent"],
                    "expect_absent": ["bgp"],
                }
            )
        driver.async_run_cmd_on_shell.assert_awaited_once_with("show ipv6 route")

    async def test_raises_when_expected_missing(self) -> None:
        task = RbbSrv6VerifyTask(hostname="rbb-r2", logger=MagicMock())
        driver = self._driver("route 2001:db8:cafe::/48 owner bgp via ...")
        with patch(_VERIFY_PATH, new_callable=AsyncMock, return_value=driver):
            with self.assertRaises(TestCaseFailure):
                await task.run(
                    {
                        "hostname": "rbb-r2",
                        "show_cmd": "show ipv6 route",
                        "expect_contains": ["te_agent"],
                    }
                )

    async def test_raises_when_unexpected_present(self) -> None:
        task = RbbSrv6VerifyTask(hostname="rbb-r2", logger=MagicMock())
        driver = self._driver("route owned by te_agent")
        with patch(_VERIFY_PATH, new_callable=AsyncMock, return_value=driver):
            with self.assertRaises(TestCaseFailure):
                await task.run(
                    {
                        "hostname": "rbb-r2",
                        "show_cmd": "show ipv6 route",
                        "expect_absent": ["te_agent"],
                    }
                )


class RbbSrv6ProgramTaskTest(unittest.IsolatedAsyncioTestCase):
    async def test_runs_each_cmd(self) -> None:
        task = RbbSrv6ProgramTask(hostname="rbb-r1", logger=MagicMock())
        driver = MagicMock()
        driver.async_run_cmd_on_shell = AsyncMock()
        with patch(_PROGRAM_PATH, new_callable=AsyncMock, return_value=driver):
            await task.run({"hostname": "rbb-r1", "cmds": ["cmd-a", "cmd-b"]})
        self.assertEqual(driver.async_run_cmd_on_shell.await_count, 2)


class RbbSrv6DirectRouteTaskTest(unittest.IsolatedAsyncioTestCase):
    async def test_install_selects_install_cmds(self) -> None:
        task = RbbSrv6DirectRouteTask(hostname="rbb-r1", logger=MagicMock())
        driver = MagicMock()
        driver.async_run_cmd_on_shell = AsyncMock()
        with patch(_DIRECT_PATH, new_callable=AsyncMock, return_value=driver):
            await task.run(
                {
                    "hostname": "rbb-r1",
                    "action": "install",
                    "install_cmds": ["route add"],
                    "delete_cmds": ["route del"],
                }
            )
        driver.async_run_cmd_on_shell.assert_awaited_once_with("route add")

    async def test_invalid_action_raises(self) -> None:
        task = RbbSrv6DirectRouteTask(hostname="rbb-r1", logger=MagicMock())
        with self.assertRaises(ValueError):
            await task.run({"hostname": "rbb-r1", "action": "bogus"})


class RbbCoreInterfaceSetupTaskTest(unittest.IsolatedAsyncioTestCase):
    async def test_runs_each_cmd(self) -> None:
        task = RbbCoreInterfaceSetupTask(hostname="rbb-r1", logger=MagicMock())
        driver = MagicMock()
        driver.async_run_cmd_on_shell = AsyncMock()
        with patch(_CORE_PATH, new_callable=AsyncMock, return_value=driver):
            await task.run({"hostname": "rbb-r1", "cmds": ["a", "b", "c"]})
        self.assertEqual(driver.async_run_cmd_on_shell.await_count, 3)


class RbbSrv6CounterDeltaTaskTest(unittest.IsolatedAsyncioTestCase):
    def _driver(self, output: str) -> MagicMock:
        driver = MagicMock()
        driver.async_run_cmd_on_shell = AsyncMock(return_value=output)
        return driver

    def _task(self, shared):
        return RbbSrv6CounterDeltaTask(
            hostname="rbb-r1", logger=MagicMock(), shared_data=shared
        )

    async def test_snapshot_then_assert_passes_on_increase(self) -> None:
        shared: dict = {}
        spec = {
            "counter_cmd": "show port counters",
            "counter_regex": r"out\D*(\d+)",
            "direction": "encap",
        }
        # Snapshot baseline = 100.
        with patch(
            _COUNTER_PATH, new_callable=AsyncMock, return_value=self._driver("out 100")
        ):
            await self._task(shared).run(
                {"hostname": "rbb-r1", "action": "snapshot", **spec}
            )
        # Assert now = 1100 → delta 1000 >= min_delta.
        with patch(
            _COUNTER_PATH,
            new_callable=AsyncMock,
            return_value=self._driver("out 1100"),
        ):
            await self._task(shared).run(
                {"hostname": "rbb-r1", "action": "assert", "min_delta": 1, **spec}
            )

    async def test_assert_fails_when_no_increase(self) -> None:
        shared: dict = {}
        spec = {
            "counter_cmd": "show port counters",
            "counter_regex": r"out\D*(\d+)",
            "direction": "encap",
        }
        with patch(
            _COUNTER_PATH, new_callable=AsyncMock, return_value=self._driver("out 500")
        ):
            await self._task(shared).run(
                {"hostname": "rbb-r1", "action": "snapshot", **spec}
            )
        with patch(
            _COUNTER_PATH, new_callable=AsyncMock, return_value=self._driver("out 500")
        ):
            with self.assertRaises(TestCaseFailure):
                await self._task(shared).run(
                    {"hostname": "rbb-r1", "action": "assert", **spec}
                )

    async def test_invalid_action_raises(self) -> None:
        with self.assertRaises(ValueError):
            await self._task({}).run(
                {
                    "hostname": "rbb-r1",
                    "action": "bogus",
                    "counter_cmd": "x",
                    "counter_regex": r"(\d+)",
                }
            )


class BgpEdgeConfigHelperTest(unittest.TestCase):
    """Pure bgp.json mutation helpers (no device)."""

    def test_enable_ipv6_afi_flips_flag_and_sets_nexthop(self) -> None:
        cfg = _ibgp_bgp_json()
        enable_ipv6_afi_on_ibgp(cfg, ibgp_next_hop6="fdad:ffff:7fff::")
        pg = cfg["peer_groups"][0]
        self.assertFalse(pg["disable_ipv6_afi"])
        self.assertEqual(cfg["peers"][0]["next_hop6"], "fdad:ffff:7fff::")

    def test_enable_ipv6_afi_only_touches_ibgp_groups(self) -> None:
        cfg = _ibgp_bgp_json()
        # Add an eBGP group first; it must not have its next-hop rewritten.
        add_edge_ebgp_peer(
            cfg,
            peer_addr="2001:db8:a:10::2",
            remote_as=64513,
            local_addr="2001:db8:a:10::1",
        )
        enable_ipv6_afi_on_ibgp(cfg, ibgp_next_hop6="fdad:ffff:7fff::")
        edge_peer = next(p for p in cfg["peers"] if p["peer_addr"] == "2001:db8:a:10::2")
        self.assertEqual(edge_peer["next_hop6"], "2001:db8:a:10::1")  # unchanged

    def test_add_edge_ebgp_peer_adds_group_and_peer(self) -> None:
        cfg = _ibgp_bgp_json()
        add_edge_ebgp_peer(
            cfg, peer_addr="2001:db8:a:10::2", remote_as=64513, local_addr="2001:db8:a:10::1"
        )
        self.assertTrue(
            any(pg["name"] == EDGE_EBGP_PEER_GROUP for pg in cfg["peer_groups"])
        )
        peer = next(p for p in cfg["peers"] if p["peer_addr"] == "2001:db8:a:10::2")
        self.assertEqual(peer["remote_as_4_byte"], 64513)
        self.assertEqual(peer["next_hop6"], "2001:db8:a:10::1")

    def test_v6_edge_peer_next_hop4_is_valid_ipv4_not_empty(self) -> None:
        # Regression: bgpd parses next_hop4 as IPv4 unconditionally and aborts on
        # an empty string ("Invalid IPv4 address ''"), crash-looping bgpd and
        # black-holing all forwarding. A v6 edge peer must carry a valid IPv4
        # next_hop4 (the box router-id), never "".
        cfg = _ibgp_bgp_json()  # router_id 8.8.8.8
        add_edge_ebgp_peer(
            cfg, peer_addr="2001:db8:a:10::2", remote_as=64513, local_addr="2001:db8:a:10::1"
        )
        peer = next(p for p in cfg["peers"] if p["peer_addr"] == "2001:db8:a:10::2")
        self.assertEqual(peer["next_hop4"], "8.8.8.8")
        self.assertNotEqual(peer["next_hop4"], "")

    def test_v6_edge_peer_next_hop4_falls_back_when_no_router_id(self) -> None:
        cfg = _ibgp_bgp_json()
        cfg.pop("router_id", None)
        add_edge_ebgp_peer(
            cfg, peer_addr="2001:db8:a:10::2", remote_as=64513, local_addr="2001:db8:a:10::1"
        )
        peer = next(p for p in cfg["peers"] if p["peer_addr"] == "2001:db8:a:10::2")
        self.assertEqual(peer["next_hop4"], "0.0.0.0")

    def test_add_edge_ebgp_peer_is_idempotent(self) -> None:
        cfg = _ibgp_bgp_json()
        for _ in range(3):
            add_edge_ebgp_peer(
                cfg,
                peer_addr="2001:db8:a:10::2",
                remote_as=64513,
                local_addr="2001:db8:a:10::1",
            )
        self.assertEqual(
            sum(1 for p in cfg["peers"] if p["peer_addr"] == "2001:db8:a:10::2"), 1
        )
        self.assertEqual(
            sum(1 for pg in cfg["peer_groups"] if pg["name"] == EDGE_EBGP_PEER_GROUP), 1
        )


class RbbEdgeEbgpTaskTest(unittest.IsolatedAsyncioTestCase):
    def _driver(self) -> MagicMock:
        driver = MagicMock()
        driver.async_write_file_on_device = AsyncMock()
        driver.async_restart_service = AsyncMock()
        driver.async_agent_config_reload = AsyncMock()
        driver.async_wait_for_agent_state_configured = AsyncMock()
        driver.async_check_if_file_exists = AsyncMock(return_value=True)
        driver.async_read_file = AsyncMock(return_value="restored-content")
        return driver

    async def test_invalid_action_raises(self) -> None:
        task = RbbEdgeEbgpTask(hostname="rbb-r2", logger=MagicMock())
        with patch(_EDGE_PATH, new_callable=AsyncMock, return_value=self._driver()):
            with self.assertRaises(ValueError):
                await task.run({"hostname": "rbb-r2", "action": "bogus"})

    async def test_apply_edits_bgp_json_and_restarts_bgpd(self) -> None:
        import json as _json

        task = RbbEdgeEbgpTask(hostname="rbb-r2", logger=MagicMock())
        driver = self._driver()
        bgp_raw = _json.dumps(_ibgp_bgp_json())
        agent_raw = _json.dumps(
            {
                "sw": {
                    "interfaces": [{"intfID": 2001, "ipAddresses": []}],
                    "ports": [{"name": "eth1/1/1", "state": 0}],
                }
            }
        )
        with patch(_EDGE_PATH, new_callable=AsyncMock, return_value=driver), patch(
            f"{_EDGE_MOD}.async_read_file_or_none",
            new_callable=AsyncMock,
            side_effect=[bgp_raw, agent_raw],
        ), patch(
            f"{_EDGE_MOD}.async_backup_before_overwrite",
            new_callable=AsyncMock,
            return_value=True,
        ):
            await task.run(
                {
                    "hostname": "rbb-r2",
                    "action": "apply",
                    "edge_peer_addr": "2001:db8:a:10::2",
                    "edge_remote_as": 64513,
                    "edge_local_addr": "2001:db8:a:10::1",
                    "enable_ipv6_afi": True,
                    "ibgp_srv6_nexthop": "fdad:ffff:7fff::",
                    "edge_rif_cidr": "2001:db8:a:10::1/64",
                    "edge_intf_id": 2001,
                    "edge_port_name": "eth1/1/1",
                }
            )
        # bgp.json + agent.conf both written; bgpd restarted; agent reloaded.
        self.assertGreaterEqual(driver.async_write_file_on_device.await_count, 2)
        driver.async_restart_service.assert_awaited()
        driver.async_agent_config_reload.assert_awaited()
        # The written bgp.json carries the eBGP peer + SRv6 steer next-hop.
        written = [c.args[0] for c in driver.async_write_file_on_device.await_args_list]
        bgp_written = next(w for w in written if "2001:db8:a:10::2" in w)
        cfg = _json.loads(bgp_written)
        self.assertTrue(
            any(pg["name"] == EDGE_EBGP_PEER_GROUP for pg in cfg["peer_groups"])
        )
        self.assertEqual(cfg["peers"][0]["next_hop6"], "fdad:ffff:7fff::")
        # The edge RIF got added to the empty SVI.
        agent_written = next(w for w in written if "intfID" in w)
        acfg = _json.loads(agent_written)
        self.assertIn(
            "2001:db8:a:10::1/64", acfg["sw"]["interfaces"][0]["ipAddresses"]
        )
        # The disabled edge port was flipped to ENABLED (state 2).
        self.assertEqual(acfg["sw"]["ports"][0]["state"], 2)

    async def test_restore_copies_backups_back(self) -> None:
        task = RbbEdgeEbgpTask(hostname="rbb-r2", logger=MagicMock())
        driver = self._driver()
        with patch(_EDGE_PATH, new_callable=AsyncMock, return_value=driver):
            await task.run({"hostname": "rbb-r2", "action": "restore"})
        # Both backups restored (bgp.json + agent.conf) and bgpd bounced.
        self.assertEqual(driver.async_write_file_on_device.await_count, 2)
        driver.async_restart_service.assert_awaited()


if __name__ == "__main__":
    unittest.main()
