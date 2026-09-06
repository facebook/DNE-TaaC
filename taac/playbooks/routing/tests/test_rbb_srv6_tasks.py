# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""Unit tests for the RBB SRv6 qualification tasks.

Lives under ``taac/playbooks/routing/tests`` (not ``taac/tasks/tests``) because
the OSS pytest harness excludes the whole ``taac/tasks`` tree from collection
(``conftest.py`` ``_NON_OSS_TEST_DIRS``); placing the file here is what actually
gets it run. The modules under test are imported by absolute path, so their
real home in ``taac/tasks`` is unaffected.
"""

import copy
import ipaddress
import socket
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from taac.constants import TestCaseFailure
from taac.tasks.rbb_edge_ebgp_task import RbbEdgeEbgpTask
from taac.tasks.rbb_srv6_counter_delta_task import RbbSrv6CounterDeltaTask
from taac.tasks.rbb_srv6_direct_route_task import RbbSrv6DirectRouteTask
from taac.tasks.rbb_srv6_direct_route_task import _build_srv6_next_hop
from taac.tasks.rbb_srv6_verify_task import RbbSrv6VerifyTask
from taac.tasks.registry import TASK_NAME_TO_CLASS
from taac.testconfigs.routing.util.bgp_rbb_edge_config import (
    add_edge_ebgp_peer,
    EDGE_EBGP_PEER_GROUP,
    enable_ipv6_afi_on_ibgp,
)

_VERIFY_PATH = "taac.tasks.rbb_srv6_verify_task.async_get_device_driver"
_DIRECT_PATH = "taac.tasks.rbb_srv6_direct_route_task.async_get_device_driver"
_COUNTER_PATH = "taac.tasks.rbb_srv6_counter_delta_task.async_get_device_driver"
_EDGE_MOD = "taac.tasks.rbb_edge_ebgp_task"
_EDGE_PATH = f"{_EDGE_MOD}.async_get_device_driver"


def _ibgp_bgp_json() -> dict:
    """A minimal iBGP-only bgp.json shaped like the tail box (v6 AFI disabled)."""
    return {
        "local_as_4_byte": 65001,
        "router_id": "192.0.2.1",
        "networks4": [{"prefix": "192.0.2.1/32"}],
        "networks6": [],
        "peer_groups": [
            {
                "name": "CORE-IBGP-V4",
                "remote_as_4_byte": 65001,
                "next_hop_self": True,
                "disable_ipv4_afi": False,
                "disable_ipv6_afi": True,
            }
        ],
        "peers": [
            {
                "peer_addr": "192.0.2.2",
                "peer_group_name": "CORE-IBGP-V4",
                "local_addr": "192.0.2.1",
                "next_hop6": "::",
                "remote_as_4_byte": 65001,
            }
        ],
    }


class RbbTaskRegistrationTest(unittest.TestCase):
    def test_all_rbb_tasks_registered(self) -> None:
        for name in (
            "rbb_srv6_direct_route",
            "rbb_srv6_verify",
            "rbb_srv6_counter_delta",
            "rbb_edge_ebgp",
            "rbb_dut_bootstrap",
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

    async def test_interfaces_up_uses_driver_state(self) -> None:
        task = RbbSrv6VerifyTask(hostname="rbb-r1", logger=MagicMock())
        driver = self._driver("Port-Channel1 eth1/1")
        driver.async_get_interfaces_operational_state = AsyncMock(
            return_value={"eth1/1": True, "eth1/2": False}
        )
        with patch(_VERIFY_PATH, new_callable=AsyncMock, return_value=driver):
            with self.assertRaises(TestCaseFailure):
                await task.run(
                    {
                        "hostname": "rbb-r1",
                        "show_cmd": "fboss2 show aggregate-port",
                        "expect_contains": ["Port-Channel1"],
                        "interfaces_up": ["eth1/1", "eth1/2"],
                    }
                )

    async def test_exact_bgp_peer_check_is_scoped_to_requested_device(self) -> None:
        from types import SimpleNamespace

        task = RbbSrv6VerifyTask(hostname="rbb-r2", logger=MagicMock())
        driver = self._driver("")
        driver.async_get_bgp_sessions = AsyncMock(
            return_value=[
                SimpleNamespace(
                    peer_addr="192.0.2.1",
                    peer=SimpleNamespace(peer_state=SimpleNamespace(name="ESTABLISHED")),
                )
            ]
        )
        with patch(_VERIFY_PATH, new_callable=AsyncMock, return_value=driver):
            await task.run(
                {
                    "hostname": "rbb-r2",
                    "gate": "S07_r2_core_ibgp_established",
                    "bgp_peers_established": ["192.0.2.1"],
                }
            )
        driver.async_get_bgp_sessions.assert_awaited_once()
        driver.async_run_cmd_on_shell.assert_not_awaited()

    async def test_exact_bgp_peer_check_rejects_idle_peer(self) -> None:
        from types import SimpleNamespace

        task = RbbSrv6VerifyTask(hostname="rbb-r2", logger=MagicMock())
        driver = self._driver("")
        driver.async_get_bgp_sessions = AsyncMock(
            return_value=[
                SimpleNamespace(
                    peer_addr="192.0.2.1",
                    peer=SimpleNamespace(peer_state=SimpleNamespace(name="IDLE")),
                )
            ]
        )
        with patch(_VERIFY_PATH, new_callable=AsyncMock, return_value=driver):
            with self.assertRaisesRegex(TestCaseFailure, "not Established"):
                await task.run(
                    {
                        "hostname": "rbb-r2",
                        "bgp_peers_established": ["192.0.2.1"],
                    }
                )

    async def test_exact_fib_prefix_check_uses_agent_fib(self) -> None:
        from types import SimpleNamespace

        task = RbbSrv6VerifyTask(hostname="rbb-r1", logger=MagicMock())
        driver = self._driver("")
        driver.async_get_fib_table_entries_all = AsyncMock(
            return_value=[
                SimpleNamespace(
                    dest=SimpleNamespace(
                        ip=SimpleNamespace(
                            addr=ipaddress.ip_address("2001:db8:beef::").packed
                        ),
                        prefixLength=64,
                    )
                )
            ]
        )
        with patch(_VERIFY_PATH, new_callable=AsyncMock, return_value=driver):
            await task.run(
                {
                    "hostname": "rbb-r1",
                    "fib_prefixes": ["2001:db8:beef::/64"],
                }
            )
        driver.async_get_fib_table_entries_all.assert_awaited_once()
        driver.async_run_cmd_on_shell.assert_not_awaited()

    async def test_exact_fib_prefix_check_rejects_missing_prefix(self) -> None:
        task = RbbSrv6VerifyTask(hostname="rbb-r1", logger=MagicMock())
        driver = self._driver("")
        driver.async_get_fib_table_entries_all = AsyncMock(return_value=[])
        with patch(_VERIFY_PATH, new_callable=AsyncMock, return_value=driver):
            with self.assertRaisesRegex(TestCaseFailure, "absent from the FBOSS FIB"):
                await task.run(
                    {
                        "hostname": "rbb-r1",
                        "fib_prefixes": ["2001:db8:beef::/64"],
                    }
                )


class RbbSrv6DirectRouteTaskTest(unittest.IsolatedAsyncioTestCase):
    def test_next_hop_copy_accepts_older_read_schema(self) -> None:
        class WritableNextHop:
            address = None
            weight = None
            mplsAction = None
            disableTTLDecrement = None
            srv6SegmentList = None
            tunnelType = None
            tunnelId = None
            adjustedWeight = None
            topologyInfo = None
            cost = None
            role = None
            backupNexthops = None

            def __init__(self, **kwargs) -> None:
                self.values = kwargs

        # The live lab's route-table compatibility object does not expose the
        # newer role/backupNexthops fields.
        source = type(
            "OlderReadNextHop",
            (),
            {
                "address": "2001:db8::1",
                "weight": 7,
                "mplsAction": None,
                "disableTTLDecrement": True,
                "adjustedWeight": 9,
                "topologyInfo": None,
                "cost": 3,
            },
        )()

        result = _build_srv6_next_hop(
            WritableNextHop,
            "SRV6_ENCAP",
            source,
            ["2001:db8:1::1"],
            "srv6_tunnel",
        )

        self.assertEqual(result.values["address"], "2001:db8::1")
        self.assertEqual(result.values["weight"], 7)
        self.assertEqual(result.values["srv6SegmentList"], ["2001:db8:1::1"])
        self.assertEqual(result.values["tunnelType"], "SRV6_ENCAP")
        self.assertEqual(result.values["tunnelId"], "srv6_tunnel")
        self.assertNotIn("role", result.values)
        self.assertNotIn("backupNexthops", result.values)

    async def test_invalid_action_raises(self) -> None:
        task = RbbSrv6DirectRouteTask(hostname="rbb-r1", logger=MagicMock())
        with self.assertRaises(ValueError):
            await task.run({"hostname": "rbb-r1", "action": "bogus"})

    async def test_force_delete_rejects_string_boolean_before_device_contact(
        self,
    ) -> None:
        task = RbbSrv6DirectRouteTask(hostname="rbb-r1", logger=MagicMock())
        with patch(_DIRECT_PATH, new_callable=AsyncMock) as get_driver:
            with self.assertRaisesRegex(ValueError, "must be a JSON boolean"):
                await task.run(
                    {
                        "hostname": "rbb-r1",
                        "action": "delete",
                        "prefix": "2001:db8:beef::/64",
                        "force_delete": "false",
                    }
                )
        get_driver.assert_not_awaited()

    async def test_cleanup_does_not_delete_route_without_install_marker(self) -> None:
        driver = MagicMock()
        driver.async_agent_client = MagicMock()
        driver.async_agent_client.__aenter__ = AsyncMock()
        driver.async_agent_client.__aexit__ = AsyncMock()
        task = RbbSrv6DirectRouteTask(
            hostname="rbb-r1", logger=MagicMock(), shared_data={}
        )
        with patch(_DIRECT_PATH, new_callable=AsyncMock, return_value=driver):
            await task.run(
                {
                    "hostname": "rbb-r1",
                    "action": "delete",
                    "prefix": "2001:db8:beef::/64",
                }
            )
        driver.async_agent_client.__aenter__.assert_not_awaited()

    async def test_fboss_install_requires_explicit_srv6_segments(self) -> None:
        task = RbbSrv6DirectRouteTask(hostname="rbb-r1", logger=MagicMock())
        driver = MagicMock()
        with patch(_DIRECT_PATH, new_callable=AsyncMock, return_value=driver):
            with self.assertRaisesRegex(ValueError, "srv6_segments"):
                await task.run(
                    {
                        "hostname": "rbb-r1",
                        "action": "install",
                        "prefix": "2001:db8:beef::/64",
                    }
                )

    async def test_rejects_ipv4_prefix(self) -> None:
        task = RbbSrv6DirectRouteTask(hostname="rbb-r1", logger=MagicMock())
        with patch(_DIRECT_PATH, new_callable=AsyncMock, return_value=MagicMock()):
            with self.assertRaisesRegex(ValueError, "prefix must be IPv6"):
                await task.run(
                    {
                        "hostname": "rbb-r1",
                        "action": "install",
                        "prefix": "192.0.2.0/24",
                        "srv6_segments": ["2001:db8::1"],
                        "srv6_tunnel_id": "srv6_tunnel",
                    }
                )


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

    async def test_snapshot_fails_when_regex_does_not_match(self) -> None:
        spec = {
            "counter_cmd": "show port counters",
            "counter_regex": r"out\D*(\d+)",
            "direction": "encap",
        }
        with patch(
            _COUNTER_PATH,
            new_callable=AsyncMock,
            return_value=self._driver("counter unavailable"),
        ):
            with self.assertRaisesRegex(TestCaseFailure, "did not match"):
                await self._task({}).run(
                    {"hostname": "rbb-r1", "action": "snapshot", **spec}
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

    async def test_assert_rejects_non_positive_minimum_before_device_read(self) -> None:
        with patch(_COUNTER_PATH, new_callable=AsyncMock) as get_driver:
            with self.assertRaisesRegex(ValueError, "at least 1"):
                await self._task({}).run(
                    {
                        "hostname": "rbb-r1",
                        "action": "assert",
                        "counter_cmd": "show port counters",
                        "counter_regex": r"(\d+)",
                        "min_delta": 0,
                    }
                )
        get_driver.assert_not_awaited()


class BgpEdgeConfigHelperTest(unittest.TestCase):
    """Pure bgp.json mutation helpers (no device)."""

    def test_enable_ipv6_afi_flips_flag_and_sets_nexthop(self) -> None:
        cfg = _ibgp_bgp_json()
        enable_ipv6_afi_on_ibgp(cfg, ibgp_next_hop6="2001:db8:7fff::")
        pg = cfg["peer_groups"][0]
        self.assertFalse(pg["disable_ipv6_afi"])
        self.assertEqual(cfg["peers"][0]["next_hop6"], "2001:db8:7fff::")

    def test_enable_ipv6_afi_only_touches_ibgp_groups(self) -> None:
        cfg = _ibgp_bgp_json()
        # Add an eBGP group first; it must not have its next-hop rewritten.
        add_edge_ebgp_peer(
            cfg,
            peer_addr="2001:db8:a:10::2",
            remote_as=64513,
            local_addr="2001:db8:a:10::1",
        )
        enable_ipv6_afi_on_ibgp(cfg, ibgp_next_hop6="2001:db8:7fff::")
        edge_peer = next(
            p for p in cfg["peers"] if p["peer_addr"] == "2001:db8:a:10::2"
        )
        self.assertEqual(edge_peer["next_hop6"], "2001:db8:a:10::1")  # unchanged

    def test_enable_ipv6_afi_requires_an_ibgp_group(self) -> None:
        cfg = _ibgp_bgp_json()
        cfg["peer_groups"][0]["remote_as_4_byte"] = 64513
        with self.assertRaisesRegex(ValueError, "no iBGP peer group"):
            enable_ipv6_afi_on_ibgp(cfg, ibgp_next_hop6="2001:db8:7fff::")

    def test_enable_ipv6_afi_preserves_existing_usable_nexthop(self) -> None:
        cfg = _ibgp_bgp_json()
        cfg["peers"][0]["next_hop6"] = "2001:db8::1"
        enable_ipv6_afi_on_ibgp(cfg)
        self.assertFalse(cfg["peer_groups"][0]["disable_ipv6_afi"])
        self.assertEqual(cfg["peers"][0]["next_hop6"], "2001:db8::1")

    def test_enable_ipv6_afi_rejects_unspecified_existing_nexthop(self) -> None:
        cfg = _ibgp_bgp_json()
        before = copy.deepcopy(cfg)
        with self.assertRaisesRegex(ValueError, "no usable IPv6 next_hop6"):
            enable_ipv6_afi_on_ibgp(cfg)
        self.assertEqual(cfg, before)

    def test_enable_ipv6_afi_scopes_mutation_to_exact_core_peer(self) -> None:
        cfg = _ibgp_bgp_json()
        cfg["peer_groups"].append(
            {
                "name": "OPERATOR-IBGP",
                "remote_as_4_byte": 65001,
                "disable_ipv6_afi": True,
            }
        )
        cfg["peers"].append(
            {
                "peer_addr": "192.0.2.3",
                "peer_group_name": "OPERATOR-IBGP",
                "next_hop6": "2001:db8::7",
            }
        )
        enable_ipv6_afi_on_ibgp(
            cfg,
            ibgp_next_hop6="2001:db8:7fff::",
            ibgp_peer_addr="192.0.2.2",
        )
        self.assertFalse(cfg["peer_groups"][0]["disable_ipv6_afi"])
        self.assertTrue(cfg["peer_groups"][1]["disable_ipv6_afi"])
        self.assertEqual(cfg["peers"][1]["next_hop6"], "2001:db8::7")

    def test_enable_ipv6_afi_rejects_shared_core_peer_group(self) -> None:
        cfg = _ibgp_bgp_json()
        cfg["peers"].append(
            {
                "peer_addr": "192.0.2.3",
                "peer_group_name": "CORE-IBGP-V4",
                "next_hop6": "2001:db8::7",
            }
        )
        before = copy.deepcopy(cfg)
        with self.assertRaisesRegex(ValueError, "shares peer group"):
            enable_ipv6_afi_on_ibgp(
                cfg,
                ibgp_next_hop6="2001:db8:7fff::",
                ibgp_peer_addr="192.0.2.2",
            )
        self.assertEqual(cfg, before)

    def test_add_edge_ebgp_peer_adds_group_and_peer(self) -> None:
        cfg = _ibgp_bgp_json()
        add_edge_ebgp_peer(
            cfg,
            peer_addr="2001:db8:a:10::2",
            remote_as=64513,
            local_addr="2001:db8:a:10::1",
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
        cfg = _ibgp_bgp_json()
        add_edge_ebgp_peer(
            cfg,
            peer_addr="2001:db8:a:10::2",
            remote_as=64513,
            local_addr="2001:db8:a:10::1",
        )
        peer = next(p for p in cfg["peers"] if p["peer_addr"] == "2001:db8:a:10::2")
        self.assertEqual(peer["next_hop4"], "192.0.2.1")
        self.assertNotEqual(peer["next_hop4"], "")

    def test_v6_edge_peer_requires_router_id(self) -> None:
        cfg = _ibgp_bgp_json()
        cfg.pop("router_id", None)
        with self.assertRaisesRegex(ValueError, "valid IPv4 router_id"):
            add_edge_ebgp_peer(
                cfg,
                peer_addr="2001:db8:a:10::2",
                remote_as=64513,
                local_addr="2001:db8:a:10::1",
            )

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
            sum(
                1
                for p in cfg["peers"]
                if p["peer_addr"] == "2001:db8:a:10::2"
            ),
            1,
        )
        self.assertEqual(
            sum(
                1
                for pg in cfg["peer_groups"]
                if pg["name"] == EDGE_EBGP_PEER_GROUP
            ),
            1,
        )

    def test_add_edge_ebgp_peer_converges_owned_stale_values(self) -> None:
        cfg = _ibgp_bgp_json()
        add_edge_ebgp_peer(
            cfg,
            peer_addr="2001:db8:a:10::2",
            remote_as=64512,
            local_addr="2001:db8:a:10::9",
        )
        add_edge_ebgp_peer(
            cfg,
            peer_addr="2001:db8:a:10::2",
            remote_as=64513,
            local_addr="2001:db8:a:10::1",
            hold_time=90,
        )
        group = next(
            pg for pg in cfg["peer_groups"] if pg["name"] == EDGE_EBGP_PEER_GROUP
        )
        peer = next(
            p for p in cfg["peers"] if p["peer_addr"] == "2001:db8:a:10::2"
        )
        self.assertEqual(group["remote_as_4_byte"], 64513)
        self.assertEqual(group["bgp_peer_timers"]["hold_time_seconds"], 90)
        self.assertEqual(peer["local_addr"], "2001:db8:a:10::1")
        self.assertEqual(peer["remote_as_4_byte"], 64513)

    def test_add_edge_ebgp_peer_rejects_peer_owned_by_another_group(self) -> None:
        cfg = _ibgp_bgp_json()
        cfg["peers"].append(
            {
                "peer_addr": "2001:db8:a:10::2",
                "peer_group_name": "operator-owned",
            }
        )
        with self.assertRaisesRegex(ValueError, "already belongs"):
            add_edge_ebgp_peer(
                cfg,
                peer_addr="2001:db8:a:10::2",
                remote_as=64513,
                local_addr="2001:db8:a:10::1",
            )

    def test_add_edge_ebgp_peer_rejects_another_peer_in_owned_group(self) -> None:
        cfg = _ibgp_bgp_json()
        add_edge_ebgp_peer(
            cfg,
            peer_addr="2001:db8:a:10::9",
            remote_as=64513,
            local_addr="2001:db8:a:10::1",
        )
        before = copy.deepcopy(cfg)
        with self.assertRaisesRegex(ValueError, "already serves other peer"):
            add_edge_ebgp_peer(
                cfg,
                peer_addr="2001:db8:a:10::2",
                remote_as=64514,
                local_addr="2001:db8:a:10::1",
            )
        self.assertEqual(cfg, before)


class RbbEdgeEbgpTaskTest(unittest.IsolatedAsyncioTestCase):
    def _driver(self) -> MagicMock:
        driver = MagicMock()
        driver.async_write_file_on_device = AsyncMock()
        driver.async_restart_service = AsyncMock()
        driver.async_agent_config_reload = AsyncMock()
        driver.async_wait_for_agent_state_configured = AsyncMock()
        driver.async_check_if_file_exists = AsyncMock(return_value=True)
        driver.async_read_file = AsyncMock(return_value="restored-content")

        def command_result(command: str) -> str:
            if command == "id -u":
                return "0\n"
            if command.startswith("systemctl show "):
                return "LoadState=loaded\nActiveState=active\n"
            return ""

        driver.async_run_cmd_on_shell = AsyncMock(side_effect=command_result)
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
                    "interfaces": [
                        {"intfID": 2001, "vlanID": 2001, "ipAddresses": []}
                    ],
                    "vlans": [{"id": 2001, "ipAddresses": []}],
                    "vlanPorts": [{"vlanID": 2001, "logicalPort": 1}],
                    "ports": [
                        {
                            "name": "eth1/1/1",
                            "logicalID": 1,
                            "state": 0,
                            "ingressVlan": 2001,
                            "portType": 0,
                            "routable": True,
                        }
                    ],
                }
            }
        )
        with patch(_EDGE_PATH, new_callable=AsyncMock, return_value=driver), patch(
            f"{_EDGE_MOD}.async_read_file_or_none",
            new_callable=AsyncMock,
            side_effect=[bgp_raw, agent_raw],
        ), patch(
            f"{_EDGE_MOD}.async_guard_snapshot_set",
            new_callable=AsyncMock,
        ), patch(
            f"{_EDGE_MOD}.async_backup_before_overwrite",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            f"{_EDGE_MOD}.async_write_json_file",
            new_callable=AsyncMock,
        ) as write_json, patch(
            f"{_EDGE_MOD}.async_apply_backup_metadata",
            new_callable=AsyncMock,
        ) as preserve_metadata:
            # This test deliberately uses a minimal structural fixture for the
            # patch logic. Full generated SwitchConfig schema validation is
            # covered by the edge task's focused apply/restore assertions.
            with patch(
                "taac.utils.json_thrift_utils.json_to_thrift",
            ):
                await task.run(
                    {
                        "hostname": "rbb-r2",
                        "action": "apply",
                        "edge_peer_addr": "2001:db8:a:10::2",
                        "edge_remote_as": 64513,
                        "edge_local_addr": "2001:db8:a:10::1",
                        "enable_ipv6_afi": True,
                        "ibgp_peer_addr": "192.0.2.2",
                        "ibgp_srv6_nexthop": "2001:db8:7fff::",
                        "edge_rif_cidr": "2001:db8:a:10::1/64",
                        "edge_port_name": "eth1/1/1",
                    }
                )
        # bgp.json + agent.conf both written; bgpd restarted; agent reloaded.
        self.assertEqual(write_json.await_count, 2)
        self.assertEqual(preserve_metadata.await_count, 2)
        driver.async_restart_service.assert_awaited()
        driver.async_agent_config_reload.assert_awaited()
        # The written bgp.json carries the eBGP peer + SRv6 steer next-hop.
        written = [c.args[2] for c in write_json.await_args_list]
        cfg = next(w for w in written if "peers" in w)
        self.assertTrue(
            any(pg["name"] == EDGE_EBGP_PEER_GROUP for pg in cfg["peer_groups"])
        )
        self.assertEqual(cfg["peers"][0]["next_hop6"], "2001:db8:7fff::")
        # The edge RIF got added to the empty SVI.
        acfg = next(w for w in written if "sw" in w)
        self.assertIn(
            "2001:db8:a:10::1/64", acfg["sw"]["interfaces"][0]["ipAddresses"]
        )
        self.assertEqual(acfg["sw"]["vlans"][0]["ipAddresses"], [])
        # The disabled edge port was flipped to ENABLED (state 2).
        self.assertEqual(acfg["sw"]["ports"][0]["state"], 2)

    async def test_edge_rif_rejects_operator_owned_addresses(self) -> None:
        import json as _json

        task = RbbEdgeEbgpTask(hostname="rbb-r2", logger=MagicMock())
        driver = self._driver()
        existing = "2001:db8:a:10::99/64"
        agent_raw = _json.dumps(
            {
                "sw": {
                    "interfaces": [
                        {"intfID": 2001, "vlanID": 2001, "ipAddresses": [existing]}
                    ],
                    "vlans": [{"id": 2001, "ipAddresses": [existing]}],
                    "vlanPorts": [{"vlanID": 2001, "logicalPort": 1}],
                    "ports": [
                        {
                            "name": "eth1/1/1",
                            "logicalID": 1,
                            "state": 2,
                            "ingressVlan": 2001,
                            "portType": 0,
                            "routable": True,
                        }
                    ],
                }
            }
        )
        with patch(
            f"{_EDGE_MOD}.async_read_file_or_none",
            new_callable=AsyncMock,
            return_value=agent_raw,
        ):
            with self.assertRaisesRegex(TestCaseFailure, "operator-owned addresses"):
                await task._prepare_edge_rif(
                    driver,
                    "rbb-r2",
                    "2001:db8:a:10::1/64",
                    "eth1/1/1",
                    None,
                )

    async def test_edge_rif_preserves_preconfigured_dual_stack_interface(
        self,
    ) -> None:
        import json as _json

        task = RbbEdgeEbgpTask(hostname="rbb-r1", logger=MagicMock())
        driver = self._driver()
        addresses = ["101.1.0.1/24", "2001:db8:a:3::1/64"]
        agent_raw = _json.dumps(
            {
                "sw": {
                    "interfaces": [
                        {
                            "intfID": 2001,
                            "vlanID": 2001,
                            "ipAddresses": addresses,
                        }
                    ],
                    "vlans": [{"id": 2001, "ipAddresses": []}],
                    "vlanPorts": [{"vlanID": 2001, "logicalPort": 1}],
                    "ports": [
                        {
                            "name": "eth1/1/1",
                            "logicalID": 1,
                            "state": 2,
                            "ingressVlan": 2001,
                            "portType": 0,
                            "routable": True,
                        }
                    ],
                }
            }
        )
        with patch(
            f"{_EDGE_MOD}.async_read_file_or_none",
            new_callable=AsyncMock,
            return_value=agent_raw,
        ):
            cfg, changed = await task._prepare_edge_rif(
                driver,
                "rbb-r1",
                "2001:db8:a:3::1/64",
                "eth1/1/1",
                None,
            )

        self.assertFalse(changed)
        self.assertEqual(cfg["sw"]["interfaces"][0]["ipAddresses"], addresses)
        self.assertEqual(cfg["sw"]["vlans"][0]["ipAddresses"], [])

    async def test_apply_rejects_non_root_remote_session(self) -> None:
        task = RbbEdgeEbgpTask(hostname="rbb-r2", logger=MagicMock())
        driver = self._driver()
        driver.async_run_cmd_on_shell = AsyncMock(return_value="1000\n")
        with patch(_EDGE_PATH, new_callable=AsyncMock, return_value=driver):
            with self.assertRaisesRegex(TestCaseFailure, "requires a root SSH"):
                await task.run(
                    {
                        "hostname": "rbb-r2",
                        "action": "apply",
                        "edge_peer_addr": "2001:db8:a:10::2",
                        "edge_remote_as": 64513,
                        "edge_local_addr": "2001:db8:a:10::1",
                    }
                )
        driver.async_read_file.assert_not_awaited()

    async def test_apply_rejects_inactive_service_before_file_access(self) -> None:
        task = RbbEdgeEbgpTask(hostname="rbb-r2", logger=MagicMock())
        driver = self._driver()

        def command_result(command: str) -> str:
            if command == "id -u":
                return "0\n"
            return "LoadState=loaded\nActiveState=inactive\n"

        driver.async_run_cmd_on_shell = AsyncMock(side_effect=command_result)
        with patch(_EDGE_PATH, new_callable=AsyncMock, return_value=driver):
            with self.assertRaisesRegex(TestCaseFailure, "already be loaded and active"):
                await task.run(
                    {
                        "hostname": "rbb-r2",
                        "action": "apply",
                        "edge_peer_addr": "2001:db8:a:10::2",
                        "edge_remote_as": 64513,
                        "edge_local_addr": "2001:db8:a:10::1",
                    }
                )
        driver.async_read_file.assert_not_awaited()

    async def test_apply_rejects_string_boolean_parameters(self) -> None:
        task = RbbEdgeEbgpTask(hostname="rbb-r2", logger=MagicMock())
        driver = self._driver()
        with patch(_EDGE_PATH, new_callable=AsyncMock, return_value=driver):
            with self.assertRaisesRegex(ValueError, "force must be a JSON boolean"):
                await task.run(
                    {
                        "hostname": "rbb-r2",
                        "action": "apply",
                        "edge_peer_addr": "2001:db8:a:10::2",
                        "edge_remote_as": 64513,
                        "edge_local_addr": "2001:db8:a:10::1",
                        "force": "false",
                    }
                )
        driver.async_read_file.assert_not_awaited()

    async def test_restore_copies_backups_back(self) -> None:
        task = RbbEdgeEbgpTask(hostname="rbb-r2", logger=MagicMock())
        driver = self._driver()
        driver.async_check_if_file_exists = AsyncMock(
            side_effect=lambda path: path.endswith(".taac-rbb-edge-orig")
        )

        def command_result(command: str) -> str:
            if command == "id -u":
                return "0\n"
            if "then echo regular" in command:
                return "absent\n" if ".missing" in command else "regular\n"
            if command.startswith("if cp -p --"):
                return "restored\n"
            return "removed\n"

        driver.async_run_cmd_on_shell = AsyncMock(side_effect=command_result)
        with patch(_EDGE_PATH, new_callable=AsyncMock, return_value=driver):
            await task.run({"hostname": "rbb-r2", "action": "restore"})
        # Both backups are restored by remote metadata-preserving copies.
        driver.async_write_file_on_device.assert_not_awaited()
        restore_commands = [
            call.args[0]
            for call in driver.async_run_cmd_on_shell.await_args_list
            if call.args[0].startswith("if cp -p --")
        ]
        self.assertEqual(len(restore_commands), 2)
        driver.async_restart_service.assert_awaited()


if __name__ == "__main__":
    unittest.main()
