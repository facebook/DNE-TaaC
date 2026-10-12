# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

import json
import logging
import os
import unittest
from unittest import mock

TAAC_OSS = os.environ.get("TAAC_OSS", "").lower() in ("1", "true", "yes")

_PACKAGE = "taac" if TAAC_OSS else "neteng.test_infra.dne.taac"

import importlib

fboss_switch = importlib.import_module(f"{_PACKAGE}.driver.fboss_switch")
oss_coop_patcher = importlib.import_module(f"{_PACKAGE}.driver.oss_coop_patcher")
oss_taac_lib_utils = importlib.import_module(f"{_PACKAGE}.utils.oss_taac_lib_utils")
FbossSwitch = fboss_switch.FbossSwitch


class StaticRoutePatcherTest(unittest.IsolatedAsyncioTestCase):
    """OSS static routes: COOP's add_static_routes agent patcher, then a reload."""

    def setUp(self):
        # The OSS patchers are pure-OSS only; see test_oss_config_patcher_gate.
        for flag, value in (("TAAC_OSS", True), ("TAAC_OSS_META_INTERNAL", False)):
            flag_patcher = mock.patch.object(oss_taac_lib_utils, flag, value)
            flag_patcher.start()
            self.addCleanup(flag_patcher.stop)
        self.switch = FbossSwitch("dut1", logging.getLogger(__name__))
        self.register = mock.AsyncMock(return_value="/tmp/agent.conf")
        self.apply = mock.AsyncMock()
        for name, value in (
            ("async_register", self.register),
            ("async_apply", self.apply),
        ):
            patcher = mock.patch.object(oss_coop_patcher, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    async def test_registers_add_static_routes_on_the_agent_then_reloads(self):
        name = await self.switch.async_add_static_route_patcher(
            {"2001:db8:dead::/64": ["2001:db8::1", "2001:db8::2"]},
            "ecmp_nh_stressor_patcher",
            is_patcher_name_uuid_needed=False,
        )

        self.assertEqual("ecmp_nh_stressor_patcher", name)
        (switch, patcher), _ = self.register.await_args
        self.assertIs(self.switch, switch)
        self.assertEqual(
            ("ecmp_nh_stressor_patcher", "agent", "add_static_routes"),
            (patcher.name, patcher.config_name, patcher.py_func_name),
        )
        self.assertEqual(
            ["2001:db8::1", "2001:db8::2"],
            json.loads(patcher.args["2001:db8:dead::/64"]),
        )
        self.apply.assert_awaited_once()
        self.assertEqual(
            fboss_switch.taac_types.ApplyPatcherMethod.AGENT_RELOAD,
            self.apply.await_args.args[1],
        )

    async def test_uuid_suffix_makes_the_name_unique(self):
        first = await self.switch.async_add_static_route_patcher(
            {"2001:db8:b::/64": ["2001:db8::1"]}, "p"
        )
        second = await self.switch.async_add_static_route_patcher(
            {"2001:db8:b::/64": ["2001:db8::1"]}, "p"
        )
        self.assertTrue(first.startswith("p") and len(first) > 1)
        self.assertNotEqual(first, second)

    async def test_unregister_delegates_to_the_config_patcher(self):
        with mock.patch.object(
            oss_coop_patcher, "async_unregister", return_value=True
        ) as unregister:
            await self.switch.async_coop_unregister_patchers("vlan_patcher", "agent")
        unregister.assert_awaited_once_with(self.switch, "agent", "vlan_patcher")

    async def test_unregister_without_config_drops_every_config_holding_it(self):
        """A patcher sent to bgpcpp and bgpcpp_softdrain under one name."""
        with (
            mock.patch.object(
                oss_coop_patcher,
                "find_configs",
                return_value=["bgpcpp", "bgpcpp_softdrain"],
            ),
            mock.patch.object(
                oss_coop_patcher, "async_unregister", return_value=True
            ) as unregister,
        ):
            await self.switch.async_coop_unregister_patchers("add_bgp_peers")
        self.assertEqual(
            [
                mock.call(self.switch, "bgpcpp", "add_bgp_peers"),
                mock.call(self.switch, "bgpcpp_softdrain", "add_bgp_peers"),
            ],
            unregister.await_args_list,
        )

    async def test_unregister_unknown_patcher_is_a_noop(self):
        """EcmpMemberStaticRouteStep unregisters before it adds anything."""
        with mock.patch.object(oss_coop_patcher, "find_configs", return_value=[]):
            await self.switch.async_coop_unregister_patchers("never_registered")


if __name__ == "__main__":
    unittest.main()
