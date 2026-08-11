# pyre-unsafe
# Copyright (c) Meta Platforms, Inc. and affiliates.
"""Unit tests for the in-band IXIA 5xx auto-recovery wiring.

Covers two seams:
  1. `@external_api` decorator — emits an `inband_502_observed` Scuba row;
     502/503 invoke `_attempt_inband_recovery` and retry once, while an
     operation-scoped 504 propagates without an application-wide restart.
  2. `Ixia.ensure_ixia_alive` — between-playbook health gate; only fires
     recovery when health classifies as `API_DOWN_502` or `API_DOWN_OTHER`.

The recovery lib is lazy-imported inside the recovery methods, so we stub
it via `sys.modules` rather than taking a Buck dep on it (depending on
both `:ixia` and `:ixia_recovery_lib` pulls two incompatible variants of
the bgp_config thrift python types into a single binary — same constraint
as `test_ixia_layer2_recovery.py` in the original D108952271 design).
"""

import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from neteng.test_infra.dne.taac.ixia.ixia import external_api, Ixia  # oss-rewrite-touch


_LIB_PATH = "neteng.test_infra.dne.taac.internal.utils.ixia_recovery_lib"


class _HealthStatus:
    HEALTHY = "HEALTHY"
    API_DOWN_502 = "API_DOWN_502"
    API_DOWN_OTHER = "API_DOWN_OTHER"
    CHASSIS_DOWN = "CHASSIS_DOWN"
    AUTH_FAILED = "AUTH_FAILED"
    UNREACHABLE = "UNREACHABLE"


def _make_fake_lib() -> types.ModuleType:
    """Stand-in ixia_recovery_lib with the symbols the recovery methods import."""
    mod = types.ModuleType(_LIB_PATH)
    attrs = {
        "HealthStatus": _HealthStatus,
        "restart_ixnetwork": MagicMock(name="restart_ixnetwork"),
        "classify_health": MagicMock(name="classify_health"),
        "emit_inband_502_scuba": MagicMock(name="emit_inband_502_scuba"),
    }
    for name, value in attrs.items():
        setattr(mod, name, value)
    return mod


class _FakeIxNetError(Exception):
    """Stands in for ixnetwork-restpy's wrapped HTTPError (carries 5xx text)."""


def _err_502() -> _FakeIxNetError:
    return _FakeIxNetError("HTTP 502 Bad Gateway from /api/v1/...")


def _err_504() -> _FakeIxNetError:
    return _FakeIxNetError("HTTP 504 Gateway Timeout from /api/v1/...")


def _mkfn(name: str, **kwargs) -> MagicMock:
    """Build a MagicMock with `__name__` set (mocks don't supply __name__
    by default — `functools.wraps` and `func.__name__` would AttributeError).
    """
    fn = MagicMock(**kwargs)
    fn.__name__ = name
    return fn


class _RecoveryTestBase(unittest.TestCase):
    def setUp(self):
        self.lib = _make_fake_lib()
        self._modpatch = patch.dict(sys.modules, {_LIB_PATH: self.lib})
        self._modpatch.start()
        # Also patch TAAC_OSS=False so the OSS guards in _attempt_inband_recovery
        # / ensure_ixia_alive don't short-circuit the test.
        self._oss_patch = patch("neteng.test_infra.dne.taac.ixia.ixia.TAAC_OSS", False)
        self._oss_patch.start()

    def tearDown(self):
        self._modpatch.stop()
        self._oss_patch.stop()

    def _make_ixia(
        self,
        enabled: bool = True,
        attempts_remaining: int = 3,
        session_id: int | None = 108,
    ) -> Ixia:
        """Build an Ixia with __init__ bypassed; only recovery state set."""
        with patch.object(Ixia, "__init__", lambda self: None):
            ix = Ixia()
        ix.logger = MagicMock()
        ix.ixia_recovery = SimpleNamespace(enabled=enabled, cooldown_minutes=30)
        ix._ixia_recovery_attempts_remaining = attempts_remaining
        ix._current_playbook_name = "BAG011_cold_start"
        ix._current_testconfig_name = "BGP_PLUS_PLUS_BAG011"
        ix.primary_chassis_ip = "ixia11.netcastle.ash6"
        ix.username = "admin"
        ix.password = "pw"
        ix.session_id = session_id
        return ix


class ExternalApiDecoratorTest(_RecoveryTestBase):
    """The @external_api decorator: observe 5xx and recover only 502/503."""

    def test_healthy_call_is_plain_passthrough(self):
        ix = self._make_ixia()
        fn = _mkfn("get_stats", return_value="OK")
        wrapped = external_api(fn)
        self.assertEqual(wrapped(ix, "a", k=1), "OK")
        fn.assert_called_once_with(ix, "a", k=1)
        self.lib.restart_ixnetwork.assert_not_called()
        self.lib.emit_inband_502_scuba.assert_not_called()

    def test_non_5xx_is_reraised_without_recovery(self):
        ix = self._make_ixia()
        fn = _mkfn("select", side_effect=ValueError("400 bad request"))
        wrapped = external_api(fn)
        with self.assertRaises(ValueError):
            wrapped(ix)
        self.lib.restart_ixnetwork.assert_not_called()
        self.lib.emit_inband_502_scuba.assert_not_called()

    def test_disabled_recovery_means_5xx_passthrough(self):
        ix = self._make_ixia(enabled=False)
        fn = _mkfn("stop_protocols", side_effect=_err_502())
        wrapped = external_api(fn)
        with self.assertRaises(_FakeIxNetError):
            wrapped(ix)
        self.lib.restart_ixnetwork.assert_not_called()

    def test_502_recovers_and_retries(self):
        ix = self._make_ixia()
        fn = _mkfn(
            "stop_protocols",
            side_effect=[_err_502(), "OK-after-retry"],
        )
        # restart_ixnetwork succeeds — _attempt_inband_recovery returns True.
        self.lib.restart_ixnetwork.return_value = {"success": True}
        wrapped = external_api(fn)
        result = wrapped(ix)
        self.assertEqual(result, "OK-after-retry")
        self.assertEqual(fn.call_count, 2)
        self.lib.restart_ixnetwork.assert_called_once()
        # Scuba row fired BEFORE recovery, with the right op_name + source.
        self.lib.emit_inband_502_scuba.assert_called_once()
        kw = self.lib.emit_inband_502_scuba.call_args.kwargs
        self.assertEqual(kw["op_name"], "stop_protocols")
        self.assertEqual(kw["source"], "inband_api_call")
        self.assertEqual(kw["http_status"], 502)

    def test_502_recovery_refused_reraises_original(self):
        ix = self._make_ixia()
        fn = _mkfn("apply_changes", side_effect=_err_502())
        # restart_ixnetwork refuses (e.g. cooldown) — recovery returns False.
        self.lib.restart_ixnetwork.return_value = {
            "success": False,
            "blocked_reason": "cooldown",
        }
        wrapped = external_api(fn)
        with self.assertRaises(_FakeIxNetError):
            wrapped(ix)
        # Original 5xx propagates; only ONE attempt — no silent retry.
        self.assertEqual(fn.call_count, 1)
        # Inband telemetry still fires (we want the underlying-502 rate
        # even when recovery is budget-blocked).
        self.lib.emit_inband_502_scuba.assert_called_once()

    def test_operation_504_is_observed_without_restart(self):
        ix = self._make_ixia()
        fn = _mkfn("start_bgp_peers", side_effect=_err_504())
        wrapped = external_api(fn)

        with self.assertRaises(_FakeIxNetError):
            wrapped(ix)

        fn.assert_called_once_with(ix)
        self.lib.restart_ixnetwork.assert_not_called()
        self.lib.emit_inband_502_scuba.assert_called_once()
        kw = self.lib.emit_inband_502_scuba.call_args.kwargs
        self.assertEqual(kw["http_status"], 504)
        self.assertIn("operation-scoped 504", ix.logger.warning.call_args.args[0])

    def test_retry_after_recovery_raises_session_gone_propagates(self):
        ix = self._make_ixia()
        # First call → 5xx, recovery succeeds, retry → session-gone error.
        fn = _mkfn(
            "start_traffic",
            side_effect=[_err_502(), KeyError("session 108 not found")],
        )
        self.lib.restart_ixnetwork.return_value = {"success": True}
        wrapped = external_api(fn)
        with self.assertRaises(KeyError):
            wrapped(ix)
        # No second recovery + retry — the session-gone is non-5xx so it
        # propagates honestly, marking the playbook FAILED.
        self.assertEqual(fn.call_count, 2)


class AttemptInbandRecoveryTest(_RecoveryTestBase):
    """`_attempt_inband_recovery` surfaces the chassis's refusal body in its
    warning log so the everpaste shows WHY a soft-restart POST was rejected."""

    def test_post_status_refusal_logs_body_snippet(self):
        ix = self._make_ixia()
        self.lib.restart_ixnetwork.return_value = {
            "success": False,
            "blocked_reason": "restart_post_status_400",
            "details": {
                "restart_post_status": 400,
                "restart_url": "/chassis/api/v2/ixos/operations/restart/1",
                "restart_post_body_snippet": "ixnetworkweb is already restarting",
            },
        }
        self.assertFalse(ix._attempt_inband_recovery())
        msg = ix.logger.warning.call_args.args[0]
        self.assertIn("restart_post_status_400", msg)
        self.assertIn("post=400", msg)
        self.assertIn("body_snippet=", msg)
        self.assertIn("ixnetworkweb is already restarting", msg)

    def test_non_post_refusal_omits_body_snippet_suffix(self):
        ix = self._make_ixia()
        self.lib.restart_ixnetwork.return_value = {
            "success": False,
            "blocked_reason": "cooldown",
        }
        self.assertFalse(ix._attempt_inband_recovery())
        msg = ix.logger.warning.call_args.args[0]
        self.assertIn("cooldown", msg)
        self.assertNotIn("body_snippet=", msg)


class EnsureIxiaAliveTest(_RecoveryTestBase):
    """Cross-playbook gate: probe + recover only on Jetty-wedge classifications."""

    def test_no_session_skips_probe_but_updates_context(self):
        ix = self._make_ixia(session_id=None)
        ix.ensure_ixia_alive(playbook_name="route_storm", testconfig_name="BAG010")
        self.assertEqual(ix._current_playbook_name, "route_storm")
        self.assertEqual(ix._current_testconfig_name, "BAG010")
        self.lib.classify_health.assert_not_called()
        self.lib.restart_ixnetwork.assert_not_called()

    def test_healthy_chassis_is_noop(self):
        ix = self._make_ixia()
        self.lib.classify_health.return_value = {"status": _HealthStatus.HEALTHY}
        ix.ensure_ixia_alive(playbook_name="pb")
        self.lib.restart_ixnetwork.assert_not_called()
        self.lib.emit_inband_502_scuba.assert_not_called()

    def test_api_down_502_fires_recovery(self):
        ix = self._make_ixia()
        self.lib.classify_health.return_value = {
            "status": _HealthStatus.API_DOWN_502,
            "sessions_endpoint": {"status_code": 502},
        }
        self.lib.restart_ixnetwork.return_value = {"success": True}
        ix.ensure_ixia_alive(playbook_name="route_storm")
        self.lib.restart_ixnetwork.assert_called_once()
        # Inband telemetry fires with the gate's source.
        kw = self.lib.emit_inband_502_scuba.call_args.kwargs
        self.assertEqual(kw["source"], "between_playbook_gate")
        self.assertEqual(kw["op_name"], "ensure_ixia_alive")

    def test_api_down_504_fires_recovery(self):
        ix = self._make_ixia()
        self.lib.classify_health.return_value = {
            "status": _HealthStatus.API_DOWN_OTHER,
            "sessions_endpoint": {"status_code": 504},
        }
        self.lib.restart_ixnetwork.return_value = {"success": True}

        ix.ensure_ixia_alive(playbook_name="route_storm")

        self.lib.restart_ixnetwork.assert_called_once()
        kw = self.lib.emit_inband_502_scuba.call_args.kwargs
        self.assertEqual(kw["http_status"], 504)

    def test_chassis_down_does_not_soft_restart(self):
        # CHASSIS_DOWN is a hardware issue — a Jetty restart won't fix it.
        ix = self._make_ixia()
        self.lib.classify_health.return_value = {"status": _HealthStatus.CHASSIS_DOWN}
        ix.ensure_ixia_alive(playbook_name="pb")
        self.lib.restart_ixnetwork.assert_not_called()

    def test_auth_failed_does_not_soft_restart(self):
        # AUTH_FAILED means the server answered — chassis isn't wedged.
        ix = self._make_ixia()
        self.lib.classify_health.return_value = {"status": _HealthStatus.AUTH_FAILED}
        ix.ensure_ixia_alive(playbook_name="pb")
        self.lib.restart_ixnetwork.assert_not_called()

    def test_classify_health_raising_is_swallowed(self):
        ix = self._make_ixia()
        self.lib.classify_health.side_effect = RuntimeError("network blip")
        # Must not raise — the per-RPC wrapper is the last line of defense.
        ix.ensure_ixia_alive(playbook_name="pb")
        self.lib.restart_ixnetwork.assert_not_called()


class SourceConstantsTest(unittest.TestCase):
    """Pin the locally-mirrored Scuba `source` constants in `ixia.py`
    equal to the canonical values in `ixia_recovery_lib`. Rename on either
    side breaks the build instead of silently splitting the Scuba dataset.
    """

    def test_inband_source_constants_match_lib(self):
        from taac.internal.utils import ixia_recovery_lib
        from taac.ixia import ixia

        self.assertEqual(
            ixia._INBAND_SOURCE_API_CALL,
            ixia_recovery_lib.SOURCE_INBAND_API_CALL,
        )
        self.assertEqual(
            ixia._INBAND_SOURCE_BETWEEN_PLAYBOOK_GATE,
            ixia_recovery_lib.SOURCE_BETWEEN_PLAYBOOK_GATE,
        )


class BudgetGatingTest(_RecoveryTestBase):
    """The per-RPC wrapper must NOT share the connect-time
    `_ixia_recovery_attempts_remaining` budget. A single connect-time
    recovery would otherwise exhaust the counter and silently block
    every subsequent mid-test recovery for the rest of the run
    (Devmate review of D109398929 V1).
    """

    def test_per_rpc_recovery_fires_even_when_connect_budget_exhausted(self):
        ix = self._make_ixia()
        ix._ixia_recovery_attempts_remaining = 0  # connect-time budget spent
        fn = _mkfn(
            "stop_protocols",
            side_effect=[_err_502(), "OK-after-retry"],
        )
        self.lib.restart_ixnetwork.return_value = {"success": True}
        wrapped = external_api(fn)
        # Per-RPC recovery must still fire — budget is only for the
        # connect-retry loop in `_create_basic_setup`.
        self.assertEqual(wrapped(ix), "OK-after-retry")
        self.assertEqual(fn.call_count, 2)
        self.lib.restart_ixnetwork.assert_called_once()

    def test_connect_time_504_remains_recovery_eligible(self):
        ix = self._make_ixia()
        self.assertTrue(ix._should_attempt_recovery(_err_504()))
