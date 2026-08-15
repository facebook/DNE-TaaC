# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe
"""Unit tests for BgpMultipathNextHopCountHealthCheck.

Covers the measure-don't-assert discovery mode (modal-width selection +
optional sanity bounds), and width-relative validation mode
(use_discovered_width + peers_stopped_delta math).
"""

import socket
import unittest
from unittest.mock import AsyncMock, MagicMock

from neteng.netcastle.logger import ConsoleFileLogger
from taac.constants import TestDevice
from taac.health_checks.device_health_checks.bgp_multipath_next_hop_count_health_check import (
    _BaselineNotReady,
    BgpMultipathNextHopCountHealthCheck,
)
from taac.health_check.health_check import types as hc_types


def _packed_ip(addr: str) -> bytes:
    family = socket.AF_INET6 if ":" in addr else socket.AF_INET
    return socket.inet_pton(family, addr)


def _make_prefix(addr: str, num_bits: int):
    prefix = MagicMock()
    prefix.prefix_bin = _packed_ip(addr)
    prefix.num_bits = num_bits
    return prefix


def _make_path(next_hop_addr: str, as_path_value=None):
    """Build a path with a next-hop and (optionally) a non-empty AS_PATH.

    A non-empty AS_PATH marks the route as eBGP; otherwise it's treated as
    iBGP/local and discovery will skip it.
    """
    path = MagicMock()
    next_hop = MagicMock()
    next_hop.prefix_bin = _packed_ip(next_hop_addr)
    path.next_hop = next_hop
    # MagicMock auto-creates attrs; spec= None so hasattr() returns True for
    # everything. Set AS_PATH explicitly to control eBGP detection.
    path.as_path = as_path_value
    path.asPath = None
    path.as_path_segments = None
    path.aspath = None
    path.path_attributes = None
    return path


def _make_entry(prefix_addr: str, num_bits: int, next_hops, is_ebgp: bool = True):
    """Build a RIB entry whose best_group contains one path per next_hop addr."""
    entry = MagicMock()
    entry.prefix = _make_prefix(prefix_addr, num_bits)
    as_path = [65001] if is_ebgp else None
    entry.best_group = "bg"
    entry.paths = {"bg": [_make_path(nh, as_path) for nh in next_hops]}
    return entry


def _logger():
    return ConsoleFileLogger("test_bgp_multipath_hc")


def _make_hc():
    """Fresh HC with mocked driver. Baseline state is reset by every test."""
    device = MagicMock(spec=TestDevice)
    device.name = "test_dut"
    hc = BgpMultipathNextHopCountHealthCheck(logger=_logger())
    hc.driver = MagicMock()
    hc.driver.async_get_bgp_rib_entries = AsyncMock(return_value=[])
    hc.driver.async_get_bgp_originated_routes = AsyncMock(return_value=[])
    return hc, device


def _reset_baselines():
    BgpMultipathNextHopCountHealthCheck._discovered_baselines = {}


def _prime_baseline(device, prefixes, widths):
    BgpMultipathNextHopCountHealthCheck._discovered_baselines[device.name] = (
        set(prefixes),
        dict(widths),
    )


def _baseline_for(device):
    return BgpMultipathNextHopCountHealthCheck._discovered_baselines[device.name]


class BgpMultipathDiscoveryModeTest(unittest.IsolatedAsyncioTestCase):
    """Discovery mode: measure modal width + optional sanity bounds."""

    def setUp(self):
        _reset_baselines()

    async def test_modal_width_wins_in_mixed_distribution(self):
        """5 prefixes @ 4-way, 3 prefixes @ 8-way, 1 prefix @ 16-way → mode is 4."""
        hc, device = _make_hc()
        entries = []
        for i in range(5):
            entries.append(
                _make_entry(
                    f"10.0.{i}.0",
                    24,
                    [f"10.1.0.{j}" for j in range(4)],
                )
            )
        for i in range(3):
            entries.append(
                _make_entry(
                    f"10.2.{i}.0",
                    24,
                    [f"10.1.0.{j}" for j in range(8)],
                )
            )
        entries.append(_make_entry("10.3.0.0", 24, [f"10.1.0.{j}" for j in range(16)]))
        hc.driver.async_get_bgp_rib_entries = AsyncMock(return_value=entries)

        result = await hc._run(device, MagicMock(), {"discover_baseline": True})

        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS, result.message)
        prefixes, widths = _baseline_for(device)
        self.assertEqual(widths, {4: 4})
        self.assertEqual(len(prefixes), 5)

    async def test_single_nh_prefixes_excluded_by_min_multipath_width(self):
        """Default min_multipath_width=2 excludes single-NH prefixes."""
        hc, device = _make_hc()
        entries = [_make_entry(f"10.0.{i}.0", 24, ["10.1.0.1"]) for i in range(10)]
        hc.driver.async_get_bgp_rib_entries = AsyncMock(return_value=entries)

        result = await hc._run(device, MagicMock(), {"discover_baseline": True})

        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("No multipath eBGP prefixes", result.message)
        self.assertNotIn(
            device.name, BgpMultipathNextHopCountHealthCheck._discovered_baselines
        )

    async def test_empty_rib_fails(self):
        hc, device = _make_hc()

        result = await hc._run(device, MagicMock(), {"discover_baseline": True})

        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("No multipath eBGP prefixes", result.message)

    async def test_sanity_bound_below_min_fails(self):
        """Mode measures 4 but expected_min_baseline_width=8 → FAIL with reason."""
        hc, device = _make_hc()
        entries = [
            _make_entry(f"10.0.{i}.0", 24, [f"10.1.0.{j}" for j in range(4)])
            for i in range(5)
        ]
        hc.driver.async_get_bgp_rib_entries = AsyncMock(return_value=entries)

        result = await hc._run(
            device,
            MagicMock(),
            {"discover_baseline": True, "expected_min_baseline_width": 8},
        )

        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("expected_min_baseline_width", result.message)
        # Discovery failed sanity-check → state must not be written.
        self.assertNotIn(
            device.name, BgpMultipathNextHopCountHealthCheck._discovered_baselines
        )

    async def test_sanity_bound_above_max_fails(self):
        hc, device = _make_hc()
        entries = [
            _make_entry(f"10.0.{i}.0", 24, [f"10.1.0.{j}" for j in range(16)])
            for i in range(5)
        ]
        hc.driver.async_get_bgp_rib_entries = AsyncMock(return_value=entries)

        result = await hc._run(
            device,
            MagicMock(),
            {"discover_baseline": True, "expected_max_baseline_width": 8},
        )

        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("expected_max_baseline_width", result.message)

    async def test_legacy_baseline_nexthop_count_mismatch_fails(self):
        """Legacy exact-match selector: if supplied, measured width must equal it."""
        hc, device = _make_hc()
        entries = [
            _make_entry(f"10.0.{i}.0", 24, [f"10.1.0.{j}" for j in range(4)])
            for i in range(5)
        ]
        hc.driver.async_get_bgp_rib_entries = AsyncMock(return_value=entries)

        result = await hc._run(
            device,
            MagicMock(),
            {"discover_baseline": True, "baseline_nexthop_count": 140},
        )

        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("baseline_nexthop_count", result.message)

    async def test_ibgp_routes_excluded_by_default(self):
        """ebgp_only defaults to True; iBGP entries don't enter the distribution."""
        hc, device = _make_hc()
        entries = [
            _make_entry(
                f"10.0.{i}.0",
                24,
                [f"10.1.0.{j}" for j in range(4)],
                is_ebgp=False,
            )
            for i in range(5)
        ]
        hc.driver.async_get_bgp_rib_entries = AsyncMock(return_value=entries)

        result = await hc._run(device, MagicMock(), {"discover_baseline": True})

        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("No multipath eBGP prefixes", result.message)

    async def test_required_dual_stack_discovers_each_family_width(self):
        hc, device = _make_hc()
        entries = [
            _make_entry("10.0.0.0", 24, [f"10.1.0.{i}" for i in range(4)]),
            _make_entry("2001:db8::", 64, [f"2001:db8:1::{i}" for i in range(8)]),
        ]
        hc.driver.async_get_bgp_rib_entries = AsyncMock(return_value=entries)

        result = await hc._run(
            device,
            MagicMock(),
            {
                "discover_baseline": True,
                "required_address_families": ["ipv4", "ipv6"],
            },
        )

        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status)
        prefixes, widths = _baseline_for(device)
        self.assertEqual({4: 4, 6: 8}, widths)
        self.assertEqual({"10.0.0.0/24", "2001:db8::/64"}, prefixes)

    def test_afi_discovery_accepts_prefixes_with_host_bits(self):
        hc, _device = _make_hc()

        widths, prefixes = hc._discover_by_afi(
            {
                4: {"10.0.0.7/24"},
                8: {"2001:db8::1/64"},
            },
            (4, 6),
        )

        self.assertEqual({4: 4, 6: 8}, widths)
        self.assertEqual({"10.0.0.7/24", "2001:db8::1/64"}, prefixes)

    async def test_required_dual_stack_fails_when_one_family_is_missing(self):
        hc, device = _make_hc()
        hc.driver.async_get_bgp_rib_entries = AsyncMock(
            return_value=[
                _make_entry("10.0.0.0", 24, [f"10.1.0.{i}" for i in range(4)])
            ]
        )

        result = await hc._run(
            device,
            MagicMock(),
            {
                "discover_baseline": True,
                "required_address_families": ["ipv4", "ipv6"],
            },
        )

        self.assertEqual(hc_types.HealthCheckStatus.ERROR, result.status)
        self.assertIn("no IPv6", result.message)

    async def test_failed_discovery_clears_prior_state(self):
        hc, device = _make_hc()
        _prime_baseline(device, {"10.0.0.0/24"}, {4: 4})

        result = await hc._run(device, MagicMock(), {"discover_baseline": True})

        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertNotIn(
            device.name, BgpMultipathNextHopCountHealthCheck._discovered_baselines
        )

    async def test_discovery_state_is_isolated_by_device(self):
        first_hc, first_device = _make_hc()
        first_device.name = "first_dut"
        first_hc.driver.async_get_bgp_rib_entries = AsyncMock(
            return_value=[
                _make_entry("10.0.0.0", 24, [f"10.1.0.{i}" for i in range(4)])
            ]
        )
        second_hc, second_device = _make_hc()
        second_device.name = "second_dut"
        second_hc.driver.async_get_bgp_rib_entries = AsyncMock(
            return_value=[
                _make_entry("10.2.0.0", 24, [f"10.3.0.{i}" for i in range(8)])
            ]
        )

        await first_hc._run(first_device, MagicMock(), {"discover_baseline": True})
        await second_hc._run(second_device, MagicMock(), {"discover_baseline": True})

        self.assertEqual(_baseline_for(first_device), ({"10.0.0.0/24"}, {4: 4}))
        self.assertEqual(_baseline_for(second_device), ({"10.2.0.0/24"}, {4: 8}))


class BgpMultipathValidationModeTest(unittest.IsolatedAsyncioTestCase):
    """Validation mode: width-relative expected count and fail-closed state."""

    def setUp(self):
        _reset_baselines()

    async def test_use_discovered_width_without_prior_discovery_fails(self):
        """Validation fails closed when no measurement is stored."""
        hc, device = _make_hc()

        result = await hc._run(
            device,
            MagicMock(),
            {"use_discovered_width": True, "peers_stopped_delta": 3},
        )

        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("no baseline width discovered", result.message)

    async def test_delta_exceeds_width_errors(self):
        hc, device = _make_hc()
        _prime_baseline(device, {"10.0.0.0/24"}, {4: 4})

        result = await hc._run(
            device,
            MagicMock(),
            {
                "use_discovered_width": True,
                "use_discovered_prefixes": True,
                "peers_stopped_delta": 99,
            },
        )

        self.assertEqual(result.status, hc_types.HealthCheckStatus.ERROR)
        self.assertIn("exceeds", result.message)

    async def test_reduce_assertion_uses_measured_width_minus_delta(self):
        """Width=8, delta=3 → expected_nexthop_count=5. Entries with 5 NHs PASS."""
        hc, device = _make_hc()
        _prime_baseline(device, {"10.0.0.0/24", "10.0.1.0/24"}, {4: 8})
        entries = [
            _make_entry("10.0.0.0", 24, [f"10.1.0.{j}" for j in range(5)]),
            _make_entry("10.0.1.0", 24, [f"10.1.0.{j}" for j in range(5)]),
        ]
        hc.driver.async_get_bgp_rib_entries = AsyncMock(return_value=entries)

        result = await hc._run(
            device,
            MagicMock(),
            {
                "use_discovered_width": True,
                "use_discovered_prefixes": True,
                "peers_stopped_delta": 3,
            },
        )

        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS, result.message)

    async def test_reduce_assertion_fails_when_width_did_not_drop(self):
        """Width=8, delta=3 → expected 5. But RIB still has 8 → FAIL."""
        hc, device = _make_hc()
        _prime_baseline(device, {"10.0.0.0/24"}, {4: 8})
        entries = [_make_entry("10.0.0.0", 24, [f"10.1.0.{j}" for j in range(8)])]
        hc.driver.async_get_bgp_rib_entries = AsyncMock(return_value=entries)

        result = await hc._run(
            device,
            MagicMock(),
            {
                "use_discovered_width": True,
                "use_discovered_prefixes": True,
                "peers_stopped_delta": 3,
            },
        )

        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("expected exactly 5, got 8", result.message)

    async def test_restore_assertion_delta_zero_expects_baseline(self):
        """delta=0 (restore) → expected_nexthop_count=width=8. Entries with 8 NHs PASS."""
        hc, device = _make_hc()
        _prime_baseline(device, {"10.0.0.0/24"}, {4: 8})
        entries = [_make_entry("10.0.0.0", 24, [f"10.1.0.{j}" for j in range(8)])]
        hc.driver.async_get_bgp_rib_entries = AsyncMock(return_value=entries)

        result = await hc._run(
            device,
            MagicMock(),
            {
                "use_discovered_width": True,
                "use_discovered_prefixes": True,
                "peers_stopped_delta": 0,
            },
        )

        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS, result.message)

    async def test_validation_fails_when_a_discovered_prefix_disappears(self):
        hc, device = _make_hc()
        _prime_baseline(device, {"10.0.0.0/24", "10.0.1.0/24"}, {4: 4})
        hc.driver.async_get_bgp_rib_entries = AsyncMock(
            return_value=[
                _make_entry("10.0.0.0", 24, [f"10.1.0.{i}" for i in range(3)])
            ]
        )

        result = await hc._run(
            device,
            MagicMock(),
            {
                "use_discovered_width": True,
                "use_discovered_prefixes": True,
                "peers_stopped_delta": 1,
            },
        )

        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("10.0.1.0/24", result.message)

    async def test_validation_uses_each_address_family_baseline(self):
        hc, device = _make_hc()
        _prime_baseline(device, {"10.0.0.0/24", "2001:db8::/64"}, {4: 4, 6: 8})
        hc.driver.async_get_bgp_rib_entries = AsyncMock(
            return_value=[
                _make_entry("10.0.0.0", 24, [f"10.1.0.{i}" for i in range(3)]),
                _make_entry("2001:db8::", 64, [f"2001:db8:1::{i}" for i in range(7)]),
            ]
        )

        result = await hc._run(
            device,
            MagicMock(),
            {
                "use_discovered_width": True,
                "use_discovered_prefixes": True,
                "peers_stopped_delta": 1,
            },
        )

        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status, result.message)

    async def test_validation_fails_when_selected_afi_has_no_baseline_width(self):
        hc, device = _make_hc()
        _prime_baseline(device, {"10.0.0.0/24", "2001:db8::/64"}, {4: 4})
        hc.driver.async_get_bgp_rib_entries = AsyncMock(
            return_value=[
                _make_entry("10.0.0.0", 24, [f"10.1.0.{i}" for i in range(3)]),
                _make_entry("2001:db8::", 64, [f"2001:db8:1::{i}" for i in range(7)]),
            ]
        )

        result = await hc._run(
            device,
            MagicMock(),
            {
                "use_discovered_width": True,
                "use_discovered_prefixes": True,
                "peers_stopped_delta": 1,
            },
        )

        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("no discovered baseline width for IPv6", result.message)


class BgpMultipathDiscoveryPollingTest(unittest.IsolatedAsyncioTestCase):
    """Discovery can DETECT steady state instead of assuming it after a settle.

    These run against the real `observe_convergence` with sub-second budgets,
    so they exercise the actual integration rather than a patched stand-in.

    What they protect: the baseline stored here is what the SC9 recovery
    postcheck is scored against. A width captured mid-convergence is worse than
    a late one, because it lets a genuinely degraded run "recover" to a number
    that was never the steady state.
    """

    def setUp(self):
        _reset_baselines()

    @staticmethod
    def _poll_params(**kwargs):
        return {
            "discover_baseline": True,
            "expected_min_baseline_width": 8,
            "expected_max_baseline_width": 8,
            "convergence_hard_timeout_seconds": 5.0,
            "convergence_poll_interval_seconds": 0.01,
            "convergence_stability_window_seconds": 0.0,
            **kwargs,
        }

    @staticmethod
    def _v4(width, count=3):
        return [
            _make_entry(f"10.0.{i}.0", 24, [f"10.1.0.{j}" for j in range(width)])
            for i in range(count)
        ]

    @staticmethod
    def _v6(width, count=3):
        return [
            _make_entry(
                f"2001:db8:{i}::", 64, [f"2001:db8:ff::{j}" for j in range(width)]
            )
            for i in range(count)
        ]

    async def test_poll_waits_until_the_width_reaches_the_expected_value(self):
        """Two mid-convergence reads then a good one: the good one is stored."""
        hc, device = _make_hc()
        hc.driver.async_get_bgp_rib_entries = AsyncMock(
            side_effect=[self._v4(4), self._v4(4), self._v4(8)]
        )

        result = await hc._run(device, MagicMock(), self._poll_params())

        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status, result.message)
        _, widths = _baseline_for(device)
        self.assertEqual({4: 8}, widths)

    async def test_poll_fails_and_stores_nothing_when_the_width_never_settles(self):
        hc, device = _make_hc()
        hc.driver.async_get_bgp_rib_entries = AsyncMock(return_value=self._v4(4))

        result = await hc._run(
            device,
            MagicMock(),
            self._poll_params(convergence_hard_timeout_seconds=0.05),
        )

        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("did not reach a steady state", result.message)
        # The last thing actually observed, not a bare timeout.
        self.assertIn("sanity-check FAILED", result.message)
        self.assertNotIn(
            device.name, BgpMultipathNextHopCountHealthCheck._discovered_baselines
        )

    async def test_stability_window_rejects_a_width_that_does_not_hold(self):
        """A width that touches the expected value and falls back is not a
        steady state. This is the assertion a plain retry loop cannot make:
        the retry stops at the first PASS."""
        hc, device = _make_hc()
        hc.driver.async_get_bgp_rib_entries = AsyncMock(
            side_effect=[self._v4(8), self._v4(4)] * 100
        )

        result = await hc._run(
            device,
            MagicMock(),
            self._poll_params(
                convergence_hard_timeout_seconds=0.4,
                convergence_stability_window_seconds=0.15,
            ),
        )

        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("did not reach a steady state", result.message)
        self.assertNotIn(
            device.name, BgpMultipathNextHopCountHealthCheck._discovered_baselines
        )

    async def test_missing_address_family_is_retried_not_errored(self):
        """`_discover_by_afi` raises when a required AFI has no multipath
        prefixes yet -- the ordinary mid-convergence state on a dual-stack
        testbed, and the reason SC9 could not simply reuse the one-shot read."""
        hc, device = _make_hc()
        hc.driver.async_get_bgp_rib_entries = AsyncMock(
            side_effect=[self._v4(8), self._v4(8) + self._v6(8)]
        )

        result = await hc._run(
            device,
            MagicMock(),
            self._poll_params(required_address_families=["ipv4", "ipv6"]),
        )

        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status, result.message)
        _, widths = _baseline_for(device)
        self.assertEqual({4: 8, 6: 8}, widths)

    async def test_one_shot_discovery_still_errors_on_a_missing_address_family(self):
        """Behaviour preservation: without polling the ValueError must keep
        escaping to ERROR. The refactor must not quietly reclassify it as FAIL,
        which would also make the framework retry loop start engaging."""
        hc, device = _make_hc()
        hc.driver.async_get_bgp_rib_entries = AsyncMock(return_value=self._v4(8))

        result = await hc._run(
            device,
            MagicMock(),
            {"discover_baseline": True, "required_address_families": ["ipv4", "ipv6"]},
        )

        self.assertEqual(hc_types.HealthCheckStatus.ERROR, result.status)
        self.assertIn("no IPv6 multipath eBGP baseline prefixes", result.message)

    async def test_one_shot_empty_rib_message_is_unchanged(self):
        """The one-shot FAIL messages are reused verbatim as the poll's
        non-converged detail, so they are pinned here."""
        hc, device = _make_hc()
        hc.driver.async_get_bgp_rib_entries = AsyncMock(return_value=[])

        result = await hc._run(device, MagicMock(), {"discover_baseline": True})

        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("No multipath eBGP prefixes", result.message)

    async def test_unsupported_address_family_errors_instead_of_polling(self):
        """A deterministic error must not be retried into a timeout.

        Only `_BaselineNotReady` can heal by waiting. An unsupported
        `required_address_families` entry never can, so catching every
        ValueError as "not yet" spent the whole hard timeout and then reported
        `did not reach a steady state` -- a config typo disguised as a device
        that would not converge. The one-shot path always reported it as ERROR;
        the polling path now does too.
        """
        hc, device = _make_hc()
        hc.driver.async_get_bgp_rib_entries = AsyncMock(return_value=self._v4(8))

        result = await hc._run(
            device,
            MagicMock(),
            self._poll_params(
                required_address_families=["ipv4", "ipv7"],
                convergence_hard_timeout_seconds=30.0,
            ),
        )

        self.assertEqual(hc_types.HealthCheckStatus.ERROR, result.status)
        self.assertIn("unsupported required address family", result.message)
        self.assertNotIn("did not reach a steady state", result.message)
        # It also must not have burned the 30s budget getting there.
        self.assertNotIn(
            device.name, BgpMultipathNextHopCountHealthCheck._discovered_baselines
        )

    async def test_malformed_prefix_errors_instead_of_polling(self):
        """The other non-retryable ValueError reachable from a discovery
        attempt: `ipaddress.ip_network` on a prefix the device reported."""
        hc, device = _make_hc()
        # num_bits is formatted straight into the prefix string, so 99 yields
        # "10.0.0.0/99" and ip_network rejects it.
        bad = _make_entry("10.0.0.0", 99, [f"10.1.0.{j}" for j in range(8)])
        hc.driver.async_get_bgp_rib_entries = AsyncMock(return_value=[bad])

        result = await hc._run(
            device,
            MagicMock(),
            self._poll_params(convergence_hard_timeout_seconds=30.0),
        )

        self.assertEqual(hc_types.HealthCheckStatus.ERROR, result.status)
        self.assertNotIn("did not reach a steady state", result.message)

    def test_not_ready_is_a_value_error_subclass(self):
        """Pins the one-shot contract: the transient still escapes as a
        ValueError, so any caller catching that type is unaffected."""
        self.assertTrue(issubclass(_BaselineNotReady, ValueError))
