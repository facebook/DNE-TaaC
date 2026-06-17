# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe
"""Unit tests for BgpUpdateGroupHealthCheck."""

import json
import unittest
from unittest.mock import AsyncMock, MagicMock

from neteng.fboss.bgp_thrift.types import TBgpPeerState
from neteng.netcastle.logger import ConsoleFileLogger
from taac.constants import TestDevice
from taac.health_checks.device_health_checks.bgp_update_group_health_check import (
    BgpUpdateGroupHealthCheck,
)
from taac.health_checks.healthcheck_definitions import (
    create_bgp_update_group_check,
)
from taac.health_check.health_check import types as hc_types


# Peer-group description substrings used across the tests.
IBGP = "EB-EB-V6"
EBGP = "EB-FA-V6"
MON = "BGP-MON"


def _make_peer(
    peer_addr,
    description,
    state=TBgpPeerState.ESTABLISHED,
    entry_count=100,
):
    peer = MagicMock()
    peer.peer_addr = peer_addr
    peer.description = description
    peer.session_state = state
    peer.entry_count = entry_count
    return peer


def _make_group(
    group_id,
    peers,
    egress_policy_name="POLICY",
    member_count=None,
    peer_group_name="PG",
    group_state="READY",
):
    group = MagicMock()
    group.group_id = group_id
    group.peers = peers
    group.member_count = member_count if member_count is not None else len(peers)
    group.group_state = group_state
    group.group_key = MagicMock()
    group.group_key.egress_policy_name = egress_policy_name
    group.group_key.peer_group_name = peer_group_name
    return group


def _make_resp(groups, enabled=True):
    resp = MagicMock()
    resp.enable_update_group = enabled
    resp.update_groups = groups
    return resp


def _make_session(peer_addr, established=True):
    """Build a TBgpSession-like mock as returned by getBgpSessions."""
    session = MagicMock()
    session.peer_addr = peer_addr
    session.peer = MagicMock()
    session.peer.peer_state = (
        TBgpPeerState.ESTABLISHED if established else TBgpPeerState.ACTIVE
    )
    return session


def _all_peer_addrs(groups):
    return [p.peer_addr for g in groups for p in (g.peers or [])]


def _default_groups():
    """Three distinct, well-formed update groups: iBGP, eBGP, BGP-MON."""
    return [
        _make_group(
            1,
            [
                _make_peer("2401:db00::1", IBGP, entry_count=100),
                _make_peer("2401:db00::2", IBGP, entry_count=100),
            ],
            egress_policy_name="IBGP-V6-EGRESS",
            peer_group_name=IBGP,
        ),
        _make_group(
            2,
            [
                _make_peer("2401:db00::3", EBGP, entry_count=50),
                _make_peer("2401:db00::4", EBGP, entry_count=50),
            ],
            egress_policy_name="EBGP-V6-EGRESS",
            peer_group_name=EBGP,
        ),
        _make_group(
            3,
            [_make_peer("2401:db00::5", MON, entry_count=10)],
            egress_policy_name="BGP-MON-EGRESS",
            peer_group_name=MON,
        ),
    ]


class TestBgpUpdateGroupHealthCheck(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.logger = MagicMock(spec=ConsoleFileLogger)
        self.health_check = BgpUpdateGroupHealthCheck(logger=self.logger)
        self.health_check.driver = AsyncMock()
        self.device = MagicMock(spec=TestDevice)
        self.device.name = "eb03.lab.ash6"
        self.input = hc_types.BaseHealthCheckIn()

    def _set_resp(self, groups, enabled=True, established_addrs=None):
        """Wire both thrift calls. By default every peer in ``groups`` is
        ESTABLISHED (per getBgpSessions); pass ``established_addrs`` to restrict
        which peer addresses count as established."""
        self.health_check.driver.async_get_update_group_info = AsyncMock(
            return_value=_make_resp(groups, enabled=enabled)
        )
        if established_addrs is None:
            established_addrs = _all_peer_addrs(groups)
        established_addrs = set(established_addrs)
        sessions = [
            _make_session(addr, established=addr in established_addrs)
            for addr in _all_peer_addrs(groups)
        ]
        self.health_check.driver.async_get_bgp_sessions = AsyncMock(
            return_value=sessions
        )

    # --- feature enabled (assertion 1) ---

    async def test_default_callable_enabled_only_pass(self):
        """No params: only assert the feature is enabled -> PASS."""
        self._set_resp(_default_groups())
        result = await self.health_check._run(self.device, self.input, {})
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)

    async def test_feature_disabled_returns_fail(self):
        """expect_enabled (default) with feature off -> FAIL."""
        self._set_resp(_default_groups(), enabled=False)
        result = await self.health_check._run(self.device, self.input, {})
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("not enabled", result.message.lower())

    async def test_disabled_but_not_expected_enabled_pass(self):
        """If expect_enabled=False, a disabled feature is tolerated."""
        self._set_resp(_default_groups(), enabled=False)
        result = await self.health_check._run(
            self.device, self.input, {"expect_enabled": False}
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)

    # --- membership: each peer-group -> exactly one group (assertion 2) ---

    async def test_membership_pass(self):
        self._set_resp(_default_groups())
        result = await self.health_check._run(
            self.device,
            self.input,
            {"peer_group_substrings": [IBGP, EBGP, MON]},
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)

    async def test_membership_no_match_returns_fail(self):
        self._set_resp(_default_groups())
        result = await self.health_check._run(
            self.device,
            self.input,
            {"peer_group_substrings": ["DOES-NOT-EXIST"]},
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("DOES-NOT-EXIST", result.message)

    async def test_membership_spans_two_groups_is_allowed(self):
        """A peer-group split across two update groups is NOT a failure."""
        groups = [
            _make_group(1, [_make_peer("2401:db00::1", IBGP)]),
            _make_group(2, [_make_peer("2401:db00::2", IBGP)]),
        ]
        self._set_resp(groups)
        result = await self.health_check._run(
            self.device, self.input, {"peer_group_substrings": [IBGP]}
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)

    async def test_non_established_peers_excluded_via_session_xref(self):
        """Only members ESTABLISHED per getBgpSessions count (session_state in
        getUpdateGroupInfo is unreliable, so we cross-reference)."""
        groups = [
            _make_group(
                1,
                [
                    _make_peer("2401:db00::1", IBGP),
                    _make_peer("2401:db00::2", IBGP),
                ],
            )
        ]
        # Only ::1 is established per getBgpSessions; ::2 is not.
        self._set_resp(groups, established_addrs=["2401:db00::1"])
        result = await self.health_check._run(
            self.device,
            self.input,
            {
                "peer_group_substrings": [IBGP],
                "expected_member_counts": {IBGP: 1},  # only the established one
            },
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)

    async def test_no_established_sessions_returns_fail(self):
        """If no member is established (per getBgpSessions), presence FAILs."""
        groups = _default_groups()
        self._set_resp(groups, established_addrs=[])  # nothing established
        result = await self.health_check._run(
            self.device, self.input, {"peer_group_substrings": [IBGP]}
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("established member", result.message)

    # --- member count (total across all of a peer-group's update groups) ---

    async def test_member_count_pass(self):
        self._set_resp(_default_groups())
        result = await self.health_check._run(
            self.device,
            self.input,
            {"expected_member_counts": {IBGP: 2, EBGP: 2, MON: 1}},
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)

    async def test_member_count_sums_across_split_groups(self):
        """member count is the TOTAL across all update groups the pg forms."""
        groups = [
            _make_group(1, [_make_peer("2401:db00::1", IBGP)], member_count=1),
            _make_group(2, [_make_peer("2401:db00::2", IBGP)], member_count=1),
        ]
        self._set_resp(groups)
        result = await self.health_check._run(
            self.device, self.input, {"expected_member_counts": {IBGP: 2}}
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)

    async def test_member_count_mismatch_returns_fail(self):
        self._set_resp(_default_groups())
        result = await self.health_check._run(
            self.device, self.input, {"expected_member_counts": {IBGP: 5}}
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("members", result.message)

    # --- policy name (must match every update group the peer-group forms) ---

    async def test_policy_name_pass(self):
        self._set_resp(_default_groups())
        result = await self.health_check._run(
            self.device,
            self.input,
            {
                "expected_policy_names": {
                    IBGP: ["IBGP-V6-EGRESS"],
                    MON: ["BGP-MON-EGRESS"],
                }
            },
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)

    async def test_policy_name_mismatch_returns_fail(self):
        self._set_resp(_default_groups())
        result = await self.health_check._run(
            self.device,
            self.input,
            {"expected_policy_names": {IBGP: ["WRONG-POLICY"]}},
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("egress polic", result.message)

    async def test_policy_name_single_policy_across_two_groups_pass(self):
        """A peer-group whose two groups share one policy -> set is {that policy}."""
        groups = [
            _make_group(
                1,
                [_make_peer("2401:db00::1", IBGP)],
                egress_policy_name="IBGP-V6-EGRESS",
            ),
            _make_group(
                2,
                [_make_peer("2401:db00::2", IBGP)],
                egress_policy_name="IBGP-V6-EGRESS",
            ),
        ]
        self._set_resp(groups)
        result = await self.health_check._run(
            self.device,
            self.input,
            {"expected_policy_names": {IBGP: ["IBGP-V6-EGRESS"]}},
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)

    async def test_policy_name_multiple_policies_set_pass(self):
        """A peer-group with two egress policies -> expected set of both passes."""
        groups = [
            _make_group(
                1,
                [_make_peer("2401:db00::1", IBGP)],
                egress_policy_name="POLICY-A",
            ),
            _make_group(
                2,
                [_make_peer("2401:db00::2", IBGP)],
                egress_policy_name="POLICY-B",
            ),
        ]
        self._set_resp(groups)
        result = await self.health_check._run(
            self.device,
            self.input,
            {"expected_policy_names": {IBGP: ["POLICY-A", "POLICY-B"]}},
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)

    async def test_policy_name_set_mismatch_returns_fail(self):
        """Expected set differs from the actual policy set -> FAIL."""
        groups = [
            _make_group(
                1,
                [_make_peer("2401:db00::1", IBGP)],
                egress_policy_name="IBGP-V6-EGRESS",
            ),
            _make_group(
                2,
                [_make_peer("2401:db00::2", IBGP)],
                egress_policy_name="OTHER-EGRESS",
            ),
        ]
        self._set_resp(groups)
        result = await self.health_check._run(
            self.device,
            self.input,
            {"expected_policy_names": {IBGP: ["IBGP-V6-EGRESS"]}},
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)

    # --- total group count ---

    async def test_group_count_pass(self):
        self._set_resp(_default_groups())
        result = await self.health_check._run(
            self.device, self.input, {"expected_group_count": 3}
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)

    async def test_group_count_mismatch_returns_fail(self):
        self._set_resp(_default_groups())
        result = await self.health_check._run(
            self.device, self.input, {"expected_group_count": 99}
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("99", result.message)

    # --- combined 2.1.1-style check ---

    async def test_full_initial_dump_pass(self):
        """All assertions enabled together against a healthy topology."""
        self._set_resp(_default_groups())
        result = await self.health_check._run(
            self.device,
            self.input,
            {
                "peer_group_substrings": [IBGP, EBGP, MON],
                "expected_member_counts": {IBGP: 2, EBGP: 2, MON: 1},
                "expected_policy_names": {
                    IBGP: ["IBGP-V6-EGRESS"],
                    EBGP: ["EBGP-V6-EGRESS"],
                    MON: ["BGP-MON-EGRESS"],
                },
                "expected_group_count": 3,
            },
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)
        # The PASS summary surfaces the things we care about.
        self.assertIn("members", result.message)
        self.assertIn("policies", result.message)

    # --- failure accumulation ---

    async def test_multiple_failures_reported_together(self):
        """All failing assertions are combined into one result, not just the first."""
        self._set_resp(_default_groups())
        result = await self.health_check._run(
            self.device,
            self.input,
            {
                "expected_member_counts": {IBGP: 99},  # wrong (actual 2)
                "expected_policy_names": {EBGP: ["WRONG"]},  # wrong
                "expected_group_count": 42,  # wrong (actual 3)
            },
        )
        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("3 failure(s)", result.message)
        self.assertIn("members", result.message)
        self.assertIn("egress polic", result.message)
        self.assertIn("42", result.message)

    # --- driver error ---

    async def test_driver_error_returns_error(self):
        self.health_check.driver.async_get_update_group_info = AsyncMock(
            side_effect=RuntimeError("thrift down")
        )
        result = await self.health_check._run(self.device, self.input, {})
        self.assertEqual(result.status, hc_types.HealthCheckStatus.ERROR)
        self.assertIn("thrift down", result.message)

    async def test_bgp_sessions_error_returns_error(self):
        self.health_check.driver.async_get_update_group_info = AsyncMock(
            return_value=_make_resp(_default_groups())
        )
        self.health_check.driver.async_get_bgp_sessions = AsyncMock(
            side_effect=RuntimeError("sessions down")
        )
        result = await self.health_check._run(self.device, self.input, {})
        self.assertEqual(result.status, hc_types.HealthCheckStatus.ERROR)
        self.assertIn("sessions down", result.message)


class TestCreateBgpUpdateGroupCheck(unittest.TestCase):
    """Tests for the create_bgp_update_group_check factory."""

    def test_factory_default_callable(self):
        """Factory is callable with no args (drained from coverage allowlist)."""
        check = create_bgp_update_group_check()
        self.assertEqual(check.name, hc_types.CheckName.BGP_UPDATE_GROUP_CHECK)
        self.assertIsNotNone(check.check_params)
        payload = json.loads(check.check_params.json_params)
        self.assertEqual(payload["peer_group_substrings"], [])
        self.assertEqual(payload["expected_member_counts"], {})
        self.assertEqual(payload["expected_policy_names"], {})

    def test_factory_serializes_params(self):
        check = create_bgp_update_group_check(
            peer_group_substrings=[IBGP, EBGP, MON],
            expected_member_counts={IBGP: 2, MON: 1},
            expected_policy_names={IBGP: ["IBGP-V6-EGRESS"]},
            expected_group_count=3,
            check_id="eb03_2_1_1",
        )
        self.assertEqual(check.check_id, "eb03_2_1_1")
        payload = json.loads(check.check_params.json_params)
        self.assertEqual(payload["peer_group_substrings"], [IBGP, EBGP, MON])
        self.assertEqual(payload["expected_member_counts"], {IBGP: 2, MON: 1})
        self.assertEqual(payload["expected_policy_names"], {IBGP: ["IBGP-V6-EGRESS"]})
        self.assertEqual(payload["expected_group_count"], 3)

    def test_factory_omits_group_count_when_unset(self):
        check = create_bgp_update_group_check(peer_group_substrings=[IBGP])
        payload = json.loads(check.check_params.json_params)
        self.assertNotIn("expected_group_count", payload)


if __name__ == "__main__":
    unittest.main()
