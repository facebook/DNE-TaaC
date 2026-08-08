# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

import typing as t
from unittest import TestCase

from taac.steps.step_definitions import (
    _validate_fixed_peer_disruption,
    create_bgp_update_group_disruption_step,
)


class BgpUpdateGroupDisruptionStepDefinitionsTest(TestCase):
    @staticmethod
    def _fixed_peer_params() -> dict[str, t.Any]:
        return {
            "peer_regex": "EBGP-V6$",
            "duration_seconds": 1800,
            "churn_prefix_pool_regexes": ["V4_RUNTIME", "V6_RUNTIME"],
            "receiver_parent_prefixes": ["2401:db00::1/128"],
            "expected_receiver_count": 1,
            "expected_route_delta": 20,
            "route_active_seconds": 10,
            "route_period_seconds": 60,
            "expected_route_cycles": 30,
        }

    @staticmethod
    def _params(*, verify_down_route_delta: bool = False) -> dict[str, t.Any]:
        params: dict[str, t.Any] = {
            "interface": "Ethernet3/36/1",
            "target_peer_subnets": ["192.0.2.0/24"],
            "expected_target_peer_count": 280,
            "bgp_hold_timer_seconds": 180,
            "first_down_prefix_pool_regexes": ["IBGP_RUNTIME$"],
            "recovered_receiver_parent_prefixes": ["2001:db8::/64"],
            "expected_recovered_receiver_count": 280,
            "expected_route_delta": 50,
            "verify_down_route_delta": verify_down_route_delta,
        }
        if verify_down_route_delta:
            params.update(
                {
                    "down_route_receiver_addresses": [
                        "2001:db8::1",
                    ],
                    "expected_down_receiver_count": 992,
                    "expected_down_route_delta": -650,
                    "expected_failed_ebgp_prefix_count": 650,
                }
            )
        return params

    def _create(self, params: t.Mapping[str, t.Any]) -> None:
        create_bgp_update_group_disruption_step(
            "bag012.ash6",
            "link_flap_recovery",
            action_params=params,
        )

    def test_false_mode_accepts_only_recovery_route_contract(self) -> None:
        self._create(self._params())

    def test_default_true_mode_accepts_exact_down_contract(self) -> None:
        params = self._params(verify_down_route_delta=True)
        params.pop("verify_down_route_delta")

        self._create(params)

    def test_requires_unconditional_runtime_contract(self) -> None:
        for name in (
            "expected_target_peer_count",
            "bgp_hold_timer_seconds",
            "first_down_prefix_pool_regexes",
            "recovered_receiver_parent_prefixes",
            "expected_recovered_receiver_count",
            "expected_route_delta",
        ):
            params = self._params()
            params.pop(name)
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, name):
                self._create(params)

    def test_default_true_mode_requires_down_runtime_contract(self) -> None:
        for name in (
            "down_route_receiver_addresses",
            "expected_down_receiver_count",
            "expected_down_route_delta",
            "expected_failed_ebgp_prefix_count",
        ):
            params = self._params(verify_down_route_delta=True)
            params.pop("verify_down_route_delta")
            params.pop(name)
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, name):
                self._create(params)

    def test_rejects_empty_route_scopes(self) -> None:
        for name in (
            "first_down_prefix_pool_regexes",
            "recovered_receiver_parent_prefixes",
        ):
            params = self._params()
            params[name] = []
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, name):
                self._create(params)

        params = self._params(verify_down_route_delta=True)
        params["down_route_receiver_addresses"] = []
        with self.assertRaisesRegex(ValueError, "down_route_receiver_addresses"):
            self._create(params)

    def test_rejects_nonboolean_down_verification_flag(self) -> None:
        params = self._params()
        params["verify_down_route_delta"] = 0

        with self.assertRaisesRegex(ValueError, "must be a boolean"):
            self._create(params)

    def test_rejects_nonpositive_required_counts_and_timer(self) -> None:
        cases = {
            "expected_target_peer_count": 0,
            "bgp_hold_timer_seconds": 0,
            "expected_recovered_receiver_count": 0,
            "expected_down_receiver_count": 0,
            "expected_failed_ebgp_prefix_count": 0,
        }
        for name, value in cases.items():
            params = self._params(verify_down_route_delta=True)
            params[name] = value
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, name):
                self._create(params)

    def test_fixed_peer_rejects_empty_churn_pool(self) -> None:
        with self.assertRaisesRegex(ValueError, "churn_prefix_pool_regexes"):
            create_bgp_update_group_disruption_step(
                "bag012.ash6",
                "fixed_peer_flap",
                action_params={
                    "peer_regex": "EBGP",
                    "seed": 7,
                    "churn_prefix_pool_regexes": [],
                    "route_active_seconds": 10,
                    "route_period_seconds": 60,
                    "expected_route_cycles": 30,
                },
            )

    def test_fixed_peer_route_timing_requires_positive_integers(self) -> None:
        for name in (
            "route_active_seconds",
            "route_period_seconds",
            "expected_route_cycles",
        ):
            for value in (0, -1, True, 1.5, "1"):
                params = self._fixed_peer_params()
                params[name] = value
                with (
                    self.subTest(name=name, value=value),
                    self.assertRaisesRegex(ValueError, "positive integers"),
                ):
                    _validate_fixed_peer_disruption("fixed_peer_flap", params)

    def test_fixed_peer_route_timing_accepts_qualification_cadence(self) -> None:
        params = self._fixed_peer_params()
        expected = dict(params)

        _validate_fixed_peer_disruption("fixed_peer_flap", params)

        self.assertEqual(expected, params)

    def test_fixed_peer_duration_requires_positive_divisible_integer(self) -> None:
        for value in (0, -10, 11, True, 1800.5, "1800"):
            params = self._fixed_peer_params()
            params["duration_seconds"] = value
            with (
                self.subTest(value=value),
                self.assertRaisesRegex(ValueError, "positive integer divisible"),
            ):
                _validate_fixed_peer_disruption("fixed_peer_flap", params)

    def test_fixed_peer_duration_must_cover_all_route_cycles(self) -> None:
        params = self._fixed_peer_params()
        params["duration_seconds"] = 1790

        with self.assertRaisesRegex(
            ValueError,
            r"duration_seconds \(1790\).*route_period_seconds.*\(1800\)",
        ):
            _validate_fixed_peer_disruption("fixed_peer_flap", params)

    def test_fixed_peer_active_window_cannot_exceed_period(self) -> None:
        params = self._fixed_peer_params()
        params["route_active_seconds"] = 61

        with self.assertRaisesRegex(ValueError, "must not exceed"):
            _validate_fixed_peer_disruption("fixed_peer_flap", params)
