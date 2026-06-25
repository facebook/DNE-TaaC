# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe
"""Unit tests for the EBB standard pre/post-check wiring in common_health_checks.

Locks the RIB-FIB consistency retry budget: the precheck and postcheck must
retry long enough (exponential backoff) to ride out post-restart RIB->FIB
re-convergence (~117.8s observed on bag011) instead of failing a transient
recovery race.
"""

import json
import unittest

from taac.routing.ebb.ebb_bgp_plus_plus_test_config.common_health_checks import (
    create_standard_postchecks,
    create_standard_prechecks,
)
from taac.health_check.health_check import types as hc_types


def _find_check(checks, check_id):
    for check in checks:
        if check.check_id == check_id:
            return check
    raise AssertionError(f"No check with check_id={check_id!r}")


def _json_params(check):
    return json.loads(check.check_params.json_params)


class CommonHealthChecksRibFibRetryTest(unittest.TestCase):
    PRECHECK_ID = "rib_fib_consistency_precheck"
    POSTCHECK_ID = "rib_fib_consistency_postcheck"

    def test_precheck_rib_fib_retry_budget(self):
        """Precheck rides out the ~117.8s post-restart heal via 5x30s exp-backoff."""
        checks = create_standard_prechecks(
            peergroup_ibgp_v6="EB-EB-V6",
            peergroup_ibgp_v4="EB-EB-V4",
        )
        check = _find_check(checks, self.PRECHECK_ID)
        self.assertEqual(check.name, hc_types.CheckName.BGP_RIB_FIB_CONSISTENCY_CHECK)
        params = _json_params(check)
        # 5 retries from a 30s base with 1.5x backoff -> re-checks at
        # ~30/75/142/244/396s, covering the ~117.8s daemon-restart heal.
        self.assertEqual(params["retry_count"], 5)
        self.assertEqual(params["retry_delay_seconds"], 30)
        # Heal-latency probe stays on so any residual FAIL self-classifies.
        self.assertTrue(params["rib_fib_record_heal_latency"])
        self.assertEqual(params["rib_fib_heal_latency_max_sec"], 480)

    def test_postcheck_rib_fib_retry_budget(self):
        """Postcheck uses the same budget as the precheck (unified mechanism)."""
        checks = create_standard_postchecks()
        check = _find_check(checks, self.POSTCHECK_ID)
        self.assertEqual(check.name, hc_types.CheckName.BGP_RIB_FIB_CONSISTENCY_CHECK)
        params = _json_params(check)
        self.assertEqual(params["retry_count"], 5)
        self.assertEqual(params["retry_delay_seconds"], 30.0)
        self.assertTrue(params["rib_fib_record_heal_latency"])
        self.assertEqual(params["rib_fib_heal_latency_max_sec"], 480)

    def test_precheck_retry_budget_is_overridable(self):
        """Callers can still tune the budget per playbook."""
        checks = create_standard_prechecks(
            peergroup_ibgp_v6="EB-EB-V6",
            peergroup_ibgp_v4="EB-EB-V4",
            rib_fib_precheck_retry_count=2,
            rib_fib_precheck_retry_delay_seconds=7,
        )
        params = _json_params(_find_check(checks, self.PRECHECK_ID))
        self.assertEqual(params["retry_count"], 2)
        self.assertEqual(params["retry_delay_seconds"], 7)

    def test_precheck_can_be_skipped(self):
        """skip_rib_fib_precheck drops the baseline check entirely."""
        checks = create_standard_prechecks(
            peergroup_ibgp_v6="EB-EB-V6",
            peergroup_ibgp_v4="EB-EB-V4",
            skip_rib_fib_precheck=True,
        )
        self.assertFalse(any(c.check_id == self.PRECHECK_ID for c in checks))


class CommonHealthChecksBgpConvergenceTest(unittest.TestCase):
    PRECHECK_ID = "startup_bgp_convergence"
    POSTCHECK_ID = "postcheck_bgp_convergence_time"

    def test_precheck_bgp_convergence_strict_assertions_relaxed(self):
        """The startup convergence precheck is wired in, but its strict
        canonical-sequence and EOR-timer-expiry assertions are TEMPORARILY
        relaxed pending the BGP++ cold-start EOR-timer fix (cold start always
        trips the prematurely-started timer). It still gates on reaching
        INITIALIZED within the convergence threshold."""
        checks = create_standard_prechecks(
            peergroup_ibgp_v6="EB-EB-V6",
            peergroup_ibgp_v4="EB-EB-V4",
        )
        check = _find_check(checks, self.PRECHECK_ID)
        self.assertEqual(check.name, hc_types.CheckName.BGP_CONVERGENCE_CHECK)
        params = _json_params(check)
        self.assertFalse(params["validate_sequence"])
        self.assertFalse(params["fail_on_eor_expired"])
        self.assertEqual(params["convergence_threshold"], 600)

    def test_postcheck_convergence_sequence_validation_relaxed(self):
        """The convergence postcheck no longer validates the canonical sequence
        (temporarily disabled pending the BGP++ cold-start EOR-timer fix). Its
        pre-existing fail_on_eor_expired default is left untouched."""
        checks = create_standard_postchecks()
        check = _find_check(checks, self.POSTCHECK_ID)
        self.assertEqual(check.name, hc_types.CheckName.BGP_CONVERGENCE_CHECK)
        params = _json_params(check)
        self.assertFalse(params["validate_sequence"])
        self.assertTrue(params["fail_on_eor_expired"])

    def test_bgp_convergence_precheck_can_be_skipped(self):
        """check_bgp_convergence=False drops the convergence precheck."""
        checks = create_standard_prechecks(
            peergroup_ibgp_v6="EB-EB-V6",
            peergroup_ibgp_v4="EB-EB-V4",
            check_bgp_convergence=False,
        )
        self.assertFalse(any(c.check_id == self.PRECHECK_ID for c in checks))


if __name__ == "__main__":
    unittest.main()
