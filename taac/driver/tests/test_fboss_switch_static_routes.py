# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

import ipaddress
import logging
import os
import unittest
from unittest import mock

TAAC_OSS = os.environ.get("TAAC_OSS", "").lower() in ("1", "true", "yes")

FBOSS_SWITCH_MODULE = (
    "taac.driver.fboss_switch"
    if TAAC_OSS
    else "neteng.test_infra.dne.taac.driver.fboss_switch"
)

import importlib

fboss_switch = importlib.import_module(FBOSS_SWITCH_MODULE)
FbossSwitch = fboss_switch.FbossSwitch


class _FakeAgentClient:
    def __init__(self):
        self.added = []
        self.deleted = []

    async def addUnicastRoutes(self, client_id, routes):
        self.added.append((client_id, routes))

    async def deleteUnicastRoutes(self, client_id, prefixes):
        self.deleted.append((client_id, prefixes))


class _FakeAgentCtx:
    def __init__(self, client):
        self._client = client

    async def __aenter__(self):
        return self._client

    async def __aexit__(self, *exc_info):
        return False


class StaticRoutePatcherTest(unittest.IsolatedAsyncioTestCase):
    """OSS static-route patcher: thrift routes in place of a COOP patcher."""

    def setUp(self):
        fboss_switch._STATIC_ROUTE_PREFIXES.clear()
        self.addCleanup(fboss_switch._STATIC_ROUTE_PREFIXES.clear)
        self.switch = FbossSwitch("dut1", logging.getLogger(__name__))
        self.client = _FakeAgentClient()
        patcher = mock.patch.object(
            FbossSwitch,
            "async_agent_client",
            property(lambda _self: _FakeAgentCtx(self.client)),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_add_programs_routes_with_static_route_client_id(self):
        name = await self.switch.async_add_static_route_patcher(
            {"2001:db8:dead::/64": ["2001:db8::1", "2001:db8::2"]},
            "ecmp_nh_stressor_patcher",
            is_patcher_name_uuid_needed=False,
        )
        self.assertEqual(name, "ecmp_nh_stressor_patcher")
        self.assertEqual(len(self.client.added), 1)

        client_id, routes = self.client.added[0]
        self.assertEqual(client_id, int(fboss_switch.ClientID.STATIC_ROUTE))
        self.assertEqual(len(routes), 1)
        self.assertEqual(routes[0].dest.prefixLength, 64)
        self.assertEqual(
            routes[0].dest.ip.addr,
            ipaddress.ip_address("2001:db8:dead::").packed,
        )
        self.assertEqual(
            [nh.addr for nh in routes[0].nextHopAddrs],
            [
                ipaddress.ip_address("2001:db8::1").packed,
                ipaddress.ip_address("2001:db8::2").packed,
            ],
        )

    async def test_v4_prefix_is_packed_as_four_bytes(self):
        await self.switch.async_add_static_route_patcher(
            {"10.99.0.0/24": ["10.0.0.1"]},
            "v4_patcher",
            is_patcher_name_uuid_needed=False,
        )
        _, routes = self.client.added[0]
        self.assertEqual(routes[0].dest.prefixLength, 24)
        self.assertEqual(len(routes[0].dest.ip.addr), 4)

    async def test_unregister_withdraws_exactly_what_was_added(self):
        await self.switch.async_add_static_route_patcher(
            {"2001:db8:1::/64": ["2001:db8::1"]},
            "p1",
            is_patcher_name_uuid_needed=False,
        )
        await self.switch.async_add_static_route_patcher(
            {"2001:db8:2::/64": ["2001:db8::1"]},
            "p2",
            is_patcher_name_uuid_needed=False,
        )
        await self.switch.async_coop_unregister_patchers("p1")

        self.assertEqual(len(self.client.deleted), 1)
        client_id, prefixes = self.client.deleted[0]
        self.assertEqual(client_id, int(fboss_switch.ClientID.STATIC_ROUTE))
        self.assertEqual(
            [p.ip.addr for p in prefixes],
            [ipaddress.ip_address("2001:db8:1::").packed],
        )

        # p2 survives its sibling's withdrawal
        await self.switch.async_coop_unregister_patchers("p2")
        self.assertEqual(
            [p.ip.addr for p in self.client.deleted[1][1]],
            [ipaddress.ip_address("2001:db8:2::").packed],
        )

    async def test_unregister_unknown_patcher_is_a_noop(self):
        """EcmpMemberStaticRouteStep unregisters before it adds anything."""
        await self.switch.async_coop_unregister_patchers("never_registered")
        self.assertEqual(self.client.deleted, [])

    async def test_withdrawal_survives_a_new_driver_instance(self):
        """The step that withdraws is never the one that added.

        async_get_device_driver builds a fresh FbossSwitch per step, so a
        per-instance registry would make the withdrawal path dead code.
        """
        await self.switch.async_add_static_route_patcher(
            {"2001:db8:9::/64": ["2001:db8::1"]},
            "ecmp_nh_stressor_patcher",
            is_patcher_name_uuid_needed=False,
        )
        later_step_driver = FbossSwitch("dut1", logging.getLogger(__name__))
        await later_step_driver.async_coop_unregister_patchers(
            "ecmp_nh_stressor_patcher"
        )
        self.assertEqual(len(self.client.deleted), 1)
        self.assertEqual(
            [p.ip.addr for p in self.client.deleted[0][1]],
            [ipaddress.ip_address("2001:db8:9::").packed],
        )

    async def test_registry_is_scoped_per_host(self):
        await self.switch.async_add_static_route_patcher(
            {"2001:db8:a::/64": ["2001:db8::1"]},
            "shared_name",
            is_patcher_name_uuid_needed=False,
        )
        other_host = FbossSwitch("dut2", logging.getLogger(__name__))
        await other_host.async_coop_unregister_patchers("shared_name")
        # dut2 never registered it, so dut1's routes must survive
        self.assertEqual(self.client.deleted, [])

    async def test_uuid_name_contract_is_refused_not_faked(self):
        with self.assertRaises(NotImplementedError):
            await self.switch.async_add_static_route_patcher(
                {"2001:db8:b::/64": ["2001:db8::1"]}, "p"
            )

    async def test_config_patcher_path_still_delegates(self):
        """The other half of the collapsed method must keep working."""
        from taac.driver import oss_coop_patcher as ocp

        # Patch the function on the real module rather than swapping the module
        # into sys.modules: the driver does `from taac.driver import
        # oss_coop_patcher`, which resolves by getattr on the package as soon as
        # anything has imported the submodule, so the sys.modules entry is never
        # consulted and the mock is silently bypassed.
        with mock.patch.object(ocp, "unregister") as unregister:
            await self.switch.async_coop_unregister_patchers(
                "vlan_patcher", "agent"
            )
        unregister.assert_called_once_with("dut1", "agent", "vlan_patcher")
        self.assertEqual(self.client.deleted, [])

    def test_add_static_route_patcher_has_a_reachable_docstring(self):
        """The docstring caveat must sit above the guard clause, not below it,
        or it becomes a discarded expression statement and __doc__ is None."""
        doc = FbossSwitch.async_add_static_route_patcher.__doc__ or ""
        self.assertIn("config reload", doc)


if __name__ == "__main__":
    unittest.main()
