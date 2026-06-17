# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""Unit tests for TmKernelStateSnapshotHealthCheck."""

import unittest
from unittest.mock import MagicMock

from neteng.netcastle.logger import ConsoleFileLogger
from taac.constants import TestDevice
from taac.health_checks.constants import Snapshot
from taac.health_checks.snapshot_health_checks.tm_kernel_state_snapshot_health_check import (
    TmKernelStateSnapshotHealthCheck,
)
from taac.health_check.health_check import types as hc_types


def _make_state(
    tun_intfs=None,
    tun_addrs=None,
    ip_rules_v4=None,
    ip_rules_v6=None,
    ip_addrs_v4=None,
    ip_addrs_v6=None,
    route_counts_v4=None,
    route_counts_v6=None,
    proto80_v4=None,
    proto80_v6=None,
    flaps=None,
):
    """Build a minimally-realistic kernel-state dict for tests."""
    return {
        "tun_interfaces": {
            "intfs": tun_intfs if tun_intfs is not None else ["fboss10", "fboss11"],
            "addrs": tun_addrs
            if tun_addrs is not None
            else {"fboss10": ["10.0.0.1/24"], "fboss11": ["10.0.0.2/24"]},
        },
        "ip_rules": {
            "v4": ip_rules_v4
            if ip_rules_v4 is not None
            else ["0:\tfrom all lookup main"],
            "v6": ip_rules_v6
            if ip_rules_v6 is not None
            else ["0:\tfrom all lookup main"],
        },
        "ip_addresses": {
            "v4": ip_addrs_v4
            if ip_addrs_v4 is not None
            else {"eth0": ["192.168.1.1/24"]},
            "v6": ip_addrs_v6 if ip_addrs_v6 is not None else {"eth0": ["fe80::1/64"]},
        },
        "route_counts": {
            "v4": route_counts_v4
            if route_counts_v4 is not None
            else {"80": 14, "bgp": 8200},
            "v6": route_counts_v6
            if route_counts_v6 is not None
            else {"80": 11, "bgp": 8200},
        },
        "proto80_routes": {
            "v4": proto80_v4
            if proto80_v4 is not None
            else [f"10.{i}.0.0/24 proto 80" for i in range(14)],
            "v6": proto80_v6
            if proto80_v6 is not None
            else [f"fd00::{i}/64 proto 80" for i in range(11)],
        },
        "flap_counters": flaps if flaps is not None else {"eth0": 0, "fboss10": 0},
    }


def _make_check():
    logger = MagicMock(spec=ConsoleFileLogger)
    check = TmKernelStateSnapshotHealthCheck(
        obj=MagicMock(spec=TestDevice),
        input=hc_types.BaseHealthCheckIn(),
        pre_snapshot_checkpoint_id="pre",
        post_snapshot_checkpoint_id="post",
        check_params={},
        logger=logger,
    )
    return check


class TestParseHelpers(unittest.TestCase):
    """Tests for the static shell-output parsers."""

    def test_parse_tun_link_strips_at_suffix(self):
        out = "fboss10@if5    UP   52:54:00:00:01:01\nfboss11@if6    UP   52:54:00:00:01:02"
        self.assertEqual(
            TmKernelStateSnapshotHealthCheck._parse_tun_link(out),
            ["fboss10", "fboss11"],
        )

    def test_parse_tun_link_ignores_blank_lines(self):
        out = "fboss10  UP   mac\n\n  \nfboss11  UP   mac"
        self.assertEqual(
            TmKernelStateSnapshotHealthCheck._parse_tun_link(out),
            ["fboss10", "fboss11"],
        )

    def test_parse_br_addr_strips_at_suffix(self):
        out = "fboss10@if5    UP   10.0.0.1/24\neth0    UP   192.168.1.1/24"
        self.assertEqual(
            TmKernelStateSnapshotHealthCheck._parse_br_addr(out),
            {"fboss10": ["10.0.0.1/24"], "eth0": ["192.168.1.1/24"]},
        )

    def test_parse_proto_counts(self):
        out = "     14 proto 80\n   8200 proto bgp\n    100 proto kernel"
        self.assertEqual(
            TmKernelStateSnapshotHealthCheck._parse_proto_counts(out),
            {"80": 14, "bgp": 8200, "kernel": 100},
        )

    def test_parse_flap_counters_skips_non_integer(self):
        out = "interface  flaps\neth0       0\nfboss10    3\nheader_line text"
        result = TmKernelStateSnapshotHealthCheck._parse_flap_counters(out)
        self.assertEqual(result.get("eth0"), 0)
        self.assertEqual(result.get("fboss10"), 3)


class TestCompareSnapshots(unittest.IsolatedAsyncioTestCase):
    """End-to-end verdict matrix tests over `compare_snapshots`."""

    async def _compare(self, pre_data, post_data, **check_params):
        check = _make_check()
        return await check.compare_snapshots(
            obj=MagicMock(spec=TestDevice),
            input=hc_types.BaseHealthCheckIn(),
            check_params=check_params,
            pre_snapshot=Snapshot(timestamp=0, data=pre_data),
            post_snapshot=Snapshot(timestamp=1, data=post_data),
        )

    async def test_identical_pre_post_returns_pass(self):
        state = _make_state()
        result = await self._compare(state, state)
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)
        self.assertIn("verdict=PASS", result.message)

    async def test_tun_drop_pure_restart_returns_fail(self):
        pre = _make_state()
        post = _make_state(
            tun_intfs=["fboss10"], tun_addrs={"fboss10": ["10.0.0.1/24"]}
        )
        result = await self._compare(pre, post)
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("MISSING", result.message)
        self.assertIn("fboss11", result.message)

    async def test_tun_addr_only_drift_pure_restart_returns_fail_with_diff(self):
        """Intf set identical but addresses changed → FAIL with per-intf diff."""
        pre = _make_state()
        post = _make_state(
            tun_addrs={"fboss10": ["10.0.0.99/24"], "fboss11": ["10.0.0.2/24"]}
        )
        result = await self._compare(pre, post)
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("addr drift", result.message)
        self.assertIn("fboss10", result.message)
        self.assertIn("10.0.0.99/24", result.message)

    async def test_tun_drop_expect_changes_returns_pass(self):
        pre = _make_state()
        post = _make_state(
            tun_intfs=["fboss10"], tun_addrs={"fboss10": ["10.0.0.1/24"]}
        )
        result = await self._compare(pre, post, expect_kernel_changes=True)
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)
        self.assertIn("removed=['fboss11']", result.message)

    async def test_ip_rule_drift_always_fails(self):
        pre = _make_state()
        post = _make_state(
            ip_rules_v4=["0:\tfrom all lookup main", "99:\tfrom 1.2.3.4 lookup 100"]
        )
        # Strict even when expect_kernel_changes=True
        result = await self._compare(pre, post, expect_kernel_changes=True)
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("ip_rules_v4:", result.message)
        # Priority stripped by default `ignore_ip_rule_priority=True`
        self.assertIn("from 1.2.3.4 lookup 100", result.message)

    async def test_ip_rule_priority_shift_alone_ignored_by_default(self):
        """Wedge agent restart re-installs same rules at shifted priorities → PASS."""
        pre = _make_state(
            ip_rules_v6=[
                "32689:\tfrom 2001:db8:1::1 lookup 209",
                "32690:\tfrom 2001:db8:1::2 lookup 208",
            ],
        )
        post = _make_state(
            ip_rules_v6=[
                "32678:\tfrom 2001:db8:1::1 lookup 209",
                "32679:\tfrom 2001:db8:1::2 lookup 208",
            ],
        )
        result = await self._compare(pre, post)
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)
        self.assertIn("ip_rules_v6: 2→2 preserved", result.message)

    async def test_ip_rule_priority_shift_fails_with_strict_priority(self):
        """`ignore_ip_rule_priority=False` treats the shift as drift."""
        pre = _make_state(
            ip_rules_v6=["32689:\tfrom 2001:db8:1::1 lookup 209"],
        )
        post = _make_state(
            ip_rules_v6=["32678:\tfrom 2001:db8:1::1 lookup 209"],
        )
        result = await self._compare(pre, post, ignore_ip_rule_priority=False)
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("ip_rules_v6:", result.message)

    async def test_proto80_drop_pure_restart_strict_returns_fail(self):
        pre = _make_state()
        # drop one proto-80 v4 route
        post = _make_state(
            proto80_v4=[f"10.{i}.0.0/24 proto 80" for i in range(13)],
            route_counts_v4={"80": 13, "bgp": 8200},
        )
        result = await self._compare(pre, post)
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("proto_80_v4", result.message)
        # drift now shows symmetric "-1 [..]" instead of "MISSING 1"
        self.assertIn("drift", result.message)
        self.assertIn("-1 [", result.message)

    async def test_proto80_drop_non_strict_returns_pass(self):
        pre = _make_state()
        post = _make_state(
            proto80_v4=[f"10.{i}.0.0/24 proto 80" for i in range(13)],
            route_counts_v4={"80": 13, "bgp": 8200},
        )
        result = await self._compare(pre, post, proto80_strict=False)
        # WARN tolerated as PASS
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)
        self.assertIn("verdict=WARN", result.message)
        self.assertIn("non-strict", result.message)

    async def test_proto80_drop_expect_changes_returns_pass(self):
        pre = _make_state()
        post = _make_state(
            proto80_v4=[f"10.{i}.0.0/24 proto 80" for i in range(13)],
            route_counts_v4={"80": 13, "bgp": 8200},
        )
        result = await self._compare(pre, post, expect_kernel_changes=True)
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)
        self.assertIn("removed=1", result.message)

    async def test_bgp_delta_within_tolerance_returns_pass(self):
        pre = _make_state()
        # 8200 → 8203 = 0.04% drift (well within 5%)
        post = _make_state(route_counts_v4={"80": 14, "bgp": 8203})
        result = await self._compare(pre, post)
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)
        self.assertIn("verdict=PASS", result.message)
        self.assertIn("route_v4: within tol", result.message)

    async def test_bgp_delta_beyond_tolerance_returns_pass_with_warn(self):
        pre = _make_state()
        # 8200 → 10000 = 21.95% drift (beyond 5%)
        post = _make_state(route_counts_v4={"80": 14, "bgp": 10000})
        result = await self._compare(pre, post)
        # WARN tolerated as PASS
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)
        self.assertIn("verdict=WARN", result.message)
        self.assertIn("beyond tol", result.message)

    async def test_flap_delta_returns_warn(self):
        pre = _make_state()
        post = _make_state(flaps={"eth0": 0, "fboss10": 3})
        result = await self._compare(pre, post)
        # WARN tolerated as PASS
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)
        self.assertIn("verdict=WARN", result.message)
        self.assertIn("flaps: delta=3", result.message)

    async def test_ip_address_non_tun_drift_with_expect_changes_returns_fail(self):
        pre = _make_state()
        # eth0 (non-TUN) loses its address
        post = _make_state(ip_addrs_v4={"eth0": []})
        result = await self._compare(pre, post, expect_kernel_changes=True)
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("non-TUN drift", result.message)


if __name__ == "__main__":
    unittest.main()
