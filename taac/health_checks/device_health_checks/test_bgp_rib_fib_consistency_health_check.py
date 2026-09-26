# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import socket
import unittest
from unittest.mock import AsyncMock, MagicMock

from neteng.fboss.ctrl.types import ClientID
from taac.constants import TestDevice
from taac.health_checks.device_health_checks.bgp_rib_fib_consistency_health_check import (
    BgpRibFibConsistencyHealthCheck,
    drop_ignored,
)
from taac.health_check.health_check import types as hc_types


def _rib(cidr: str, best: bool = True) -> MagicMock:
    net, bits = cidr.split("/")
    fam = socket.AF_INET6 if ":" in net else socket.AF_INET
    e = MagicMock()
    e.prefix.prefix_bin = socket.inet_pton(fam, net)
    e.prefix.num_bits = int(bits)
    e.best_path = MagicMock() if best else None
    return e


def _fib(cidr: str, client: ClientID = ClientID.BGPD) -> MagicMock:
    net, bits = cidr.split("/")
    fam = socket.AF_INET6 if ":" in net else socket.AF_INET
    r = MagicMock()
    r.dest.ip.addr = socket.inet_pton(fam, net)
    r.dest.prefixLength = int(bits)
    r.nextHopMulti = [MagicMock(clientId=int(client))]
    return r


class TestBgpRibFibConsistencyHealthCheck(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.check = BgpRibFibConsistencyHealthCheck(logger=MagicMock())
        self.check.driver = AsyncMock()
        self.dev = MagicMock(spec=TestDevice)
        self.dev.name = "dut1"

    async def _run(self, rib, fib, params=None):
        self.check.driver.async_get_bgp_rib_entries.return_value = rib
        self.check.driver.async_get_route_table_details.return_value = fib
        return await self.check._run(self.dev, hc_types.BaseHealthCheckIn(), params or {})

    async def test_consistent_passes_and_ignores_non_bgp_fib(self):
        res = await self._run(
            [_rib("10.0.0.0/24"), _rib("2001:db8::/64"), _rib("10.9.0.0/16", best=False)],
            [_fib("10.0.0.0/24"), _fib("2001:db8::/64"),
             _fib("192.168.0.0/24", ClientID.INTERFACE_ROUTE)],
        )
        self.assertEqual(res.status, hc_types.HealthCheckStatus.PASS)

    async def test_rib_best_path_covered_by_another_owner_is_not_drift(self):
        res = await self._run(
            [_rib("2803:6084:5c10::/64")],
            [_fib("2803:6084:5c10::/64", ClientID.STATIC_ROUTE)],
        )
        self.assertEqual(res.status, hc_types.HealthCheckStatus.PASS)

    async def test_drift_fails_both_directions(self):
        res = await self._run([_rib("10.0.0.0/24"), _rib("10.1.0.0/24")], [_fib("10.0.0.0/24"), _fib("10.2.0.0/24")])
        self.assertEqual(res.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("10.1.0.0/24", res.message)
        self.assertIn("10.2.0.0/24", res.message)

    async def test_parent_prefixes_to_ignore(self):
        res = await self._run(
            [_rib("103.1.0.0/24"), _rib("6000:1:2::/64")],
            [],
            {"parent_prefixes_to_ignore": ["103.0.0.0/8", "6000:1::/32"]},
        )
        self.assertEqual(res.status, hc_types.HealthCheckStatus.PASS)

    def test_drop_ignored_is_family_aware(self):
        self.assertEqual(drop_ignored({"10.0.0.0/24", "::/0"}, ["10.0.0.0/8"]), {"::/0"})

    async def test_fib_rows_without_owner_are_logged(self) -> None:
        orphan = _fib("10.1.0.0/24")
        orphan.nextHopMulti = []
        await self._run([_rib("10.1.0.0/24")], [orphan])
        self.check.logger.warning.assert_called_once()
        self.assertIn("1/1 FIB rows", self.check.logger.warning.call_args.args[0])
