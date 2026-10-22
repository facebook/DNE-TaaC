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
    fib_prefixes,
    rib_prefixes,
)
from taac.health_check.health_check import types as hc_types


def _rib(cidr: str, best: bool = True, local: bool = False) -> MagicMock:
    """A RIB entry; ``local`` makes its best path the locally originated one."""
    net, bits = cidr.split("/")
    fam = socket.AF_INET6 if ":" in net else socket.AF_INET
    e = MagicMock()
    e.prefix.prefix_bin = socket.inet_pton(fam, net)
    e.prefix.num_bits = int(bits)
    if not best:
        e.best_path = None
        return e
    # bgpd marks a local route with the unspecified next hop; anything else
    # is a path learned from a peer.
    peer_next_hop = "2001:db8::1" if fam == socket.AF_INET6 else "192.0.2.254"
    e.best_path.next_hop.prefix_bin = (
        bytes(16 if fam == socket.AF_INET6 else 4)
        if local
        else socket.inet_pton(fam, peer_next_hop)
    )
    return e


def _originated(cidr: str, install_to_fib: bool = False) -> MagicMock:
    net, bits = cidr.split("/")
    fam = socket.AF_INET6 if ":" in net else socket.AF_INET
    r = MagicMock()
    r.prefix.prefix_bin = socket.inet_pton(fam, net)
    r.prefix.num_bits = int(bits)
    r.install_to_fib = install_to_fib
    return r


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
        # Held separately from check.logger: the attribute is typed as a real
        # Logger, so the mock's assertion helpers are only visible through this.
        self.logger = MagicMock()
        self.check = BgpRibFibConsistencyHealthCheck(logger=self.logger)
        self.check.driver = AsyncMock()
        self.dev = MagicMock(spec=TestDevice)
        self.dev.name = "dut1"
        self.check.driver.async_get_bgp_originated_routes.return_value = []

    async def _run(self, rib, fib, params=None, originated=None):
        if originated is not None:
            self.check.driver.async_get_bgp_originated_routes.return_value = originated
        self.check.driver.async_get_bgp_rib_entries.return_value = rib
        self.check.driver.async_get_route_table_details.return_value = fib
        return await self.check._run(
            self.dev, hc_types.BaseHealthCheckIn(), params or {}
        )

    async def test_consistent_passes_and_ignores_non_bgp_fib(self):
        res = await self._run(
            [
                _rib("10.0.0.0/24"),
                _rib("2001:db8::/64"),
                _rib("10.9.0.0/16", best=False),
            ],
            [
                _fib("10.0.0.0/24"),
                _fib("2001:db8::/64"),
                _fib("192.168.0.0/24", ClientID.INTERFACE_ROUTE),
            ],
        )
        self.assertEqual(res.status, hc_types.HealthCheckStatus.PASS)

    async def test_rib_best_path_covered_by_another_owner_is_not_drift(self):
        res = await self._run(
            [_rib("2803:6084:5c10::/64")],
            [_fib("2803:6084:5c10::/64", ClientID.STATIC_ROUTE)],
        )
        self.assertEqual(res.status, hc_types.HealthCheckStatus.PASS)

    async def test_drift_fails_both_directions(self):
        res = await self._run(
            [_rib("10.0.0.0/24"), _rib("10.1.0.0/24")],
            [_fib("10.0.0.0/24"), _fib("10.2.0.0/24")],
        )
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
        self.assertEqual(
            drop_ignored({"10.0.0.0/24", "::/0"}, ["10.0.0.0/8"]), {"::/0"}
        )

    def test_both_sides_format_a_prefix_identically(self):
        for cidr in ("10.0.0.0/24", "2001:db8::/64"):
            self.assertEqual(rib_prefixes([_rib(cidr)]), fib_prefixes([_fib(cidr)]))

    def test_address_of_unexpected_width_is_rejected(self):
        bad = _rib("10.0.0.0/24")
        bad.prefix.prefix_bin = b"\x0a\x00\x00"
        with self.assertRaises(ValueError):
            rib_prefixes([bad])

    async def test_fib_rows_without_owner_are_logged(self) -> None:
        orphan = _fib("10.1.0.0/24")
        orphan.nextHopMulti = []
        await self._run([_rib("10.1.0.0/24")], [orphan])
        self.logger.warning.assert_called_once()
        self.assertIn("1/1 FIB rows", self.logger.warning.call_args.args[0])

    async def test_not_installed_originated_networks_are_excluded(self) -> None:
        # A device's own advertise-only aggregates are best paths with
        # install_to_fib false, so the FIB never has them.
        res = await self._run(
            [
                _rib("198.51.100.0/24", local=True),
                _rib("2001:db8:1::/48", local=True),
                _rib("10.0.0.0/24"),
            ],
            [_fib("10.0.0.0/24")],
            originated=[_originated("198.51.100.0/24"), _originated("2001:db8:1::/48")],
        )
        self.assertEqual(res.status, hc_types.HealthCheckStatus.PASS)

    async def test_exclusion_does_not_mask_other_missing_best_paths(self) -> None:
        res = await self._run(
            [_rib("198.51.100.0/24", local=True), _rib("10.1.0.0/24")],
            [],
            originated=[_originated("198.51.100.0/24")],
        )
        self.assertEqual(res.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("1 RIB best paths not in FIB", res.message)
        self.assertIn("10.1.0.0/24", res.message)
        self.assertNotIn("198.51.100.0/24", res.message)

    async def test_installed_originated_route_missing_from_fib_fails(self) -> None:
        res = await self._run(
            [_rib("198.51.100.0/24", local=True)],
            [],
            originated=[_originated("198.51.100.0/24", True)],
        )
        self.assertEqual(res.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("198.51.100.0/24", res.message)

    async def test_learned_best_path_for_a_not_installed_network_must_be_in_the_fib(
        self,
    ) -> None:
        # bgpd skips the FIB only while the local route is best; a learned
        # path that wins is programmed, so its absence is drift.
        res = await self._run(
            [_rib("198.51.100.0/24")], [], originated=[_originated("198.51.100.0/24")]
        )
        self.assertEqual(res.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("198.51.100.0/24", res.message)

    async def test_exclusion_does_not_apply_to_fib_routes_missing_from_rib(
        self,
    ) -> None:
        # The exclusion only answers "why is this best path not programmed";
        # a BGP FIB route with no RIB entry is still drift.
        res = await self._run(
            [], [_fib("198.51.100.0/24")], originated=[_originated("198.51.100.0/24")]
        )
        self.assertEqual(res.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("1 BGP FIB routes not in RIB", res.message)

    async def test_failed_originated_routes_lookup_excludes_nothing_and_warns(
        self,
    ) -> None:
        self.check.driver.async_get_bgp_originated_routes.side_effect = RuntimeError(
            "bgpd down"
        )
        res = await self._run([_rib("198.51.100.0/24")], [])
        self.assertEqual(res.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("198.51.100.0/24", res.message)
        self.logger.warning.assert_called_once()
        self.assertIn(
            "no install_to_fib=false network is excluded",
            self.logger.warning.call_args.args[0],
        )
