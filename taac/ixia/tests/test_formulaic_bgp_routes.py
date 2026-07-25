# Copyright (c) Meta Platforms, Inc. and affiliates.

import unittest
from unittest import mock

from taac.ixia.taac_ixia import TaacIxia


class _LifecycleObject:
    def __init__(
        self, *, multiplier: int | None = None, fail_stop: bool = False
    ) -> None:
        self.Multiplier = multiplier
        self.fail_stop = fail_stop
        self.stop_count = 0
        self.start_count = 0

    def Stop(self) -> None:
        self.stop_count += 1
        if self.fail_stop:
            raise RuntimeError("stop failed")

    def Start(self) -> None:
        self.start_count += 1


class _Pool:
    NumberOfAddresses = 2


class _Harness(TaacIxia):
    def __init__(self, shell: tuple[object, object, object, object]) -> None:
        self.shell = shell

    def _find_formulaic_bgp_route_shell(
        self,
        device_group_name: str,
        prefix_pool_name: str,
        afi: str,
    ) -> tuple[object, object, object, object]:
        return self.shell


def _mutation(attributes: dict[str, object]) -> dict[str, object]:
    return {
        "device_group_name": "dg",
        "prefix_pool_name": "pool",
        "afi": "v4",
        "peer_count": 1,
        "prefixes_per_peer": 2,
        "prefix": {
            "start": "11.0.0.0",
            "step": 1 << 8,
            "count": 2,
            "excluded_indices": [],
            "distribution": "shared",
        },
        "next_hop": None,
        "attributes": attributes,
    }


class FormulaicBgpRoutesTest(unittest.TestCase):
    def test_sparse_prefix_inventory_skips_excluded_source_indices(self) -> None:
        self.assertEqual(
            ["11.0.0.0", "11.0.2.0", "11.0.4.0", "11.0.5.0"],
            TaacIxia._formulaic_prefix_values(
                {
                    "start": "11.0.0.0",
                    "step": 1 << 8,
                    "count": 4,
                    "excluded_indices": [1, 3],
                }
            ),
        )

    def test_formulaic_per_peer_next_hops_repeat_for_each_peer_pool(self) -> None:
        self.assertEqual(
            ["10.0.0.1"] * 3 + ["10.0.0.3"] * 3,
            TaacIxia._formulaic_next_hop_values(
                {
                    "peer_count": 2,
                    "prefixes_per_peer": 3,
                    "prefix": {"distribution": "disjoint"},
                    "next_hop": {
                        "kind": "formulaic",
                        "start": "10.0.0.1",
                        "step": 2,
                        "distribution": "per_peer",
                    },
                }
            ),
        )

    def test_explicit_per_peer_next_hops_preserve_authored_order(self) -> None:
        self.assertEqual(
            ["10.0.0.10"] * 2 + ["10.0.0.100"] * 2,
            TaacIxia._formulaic_next_hop_values(
                {
                    "peer_count": 2,
                    "prefixes_per_peer": 2,
                    "prefix": {"distribution": "shared"},
                    "next_hop": {
                        "kind": "explicit",
                        "addresses": ["10.0.0.10", "10.0.0.100"],
                        "distribution": "per_peer",
                    },
                }
            ),
        )

    def test_explicit_next_hop_cardinality_is_preflighted(self) -> None:
        mutation = {
            "peer_count": 2,
            "prefixes_per_peer": 2,
            "prefix": {"distribution": "shared"},
            "next_hop": {
                "kind": "explicit",
                "addresses": ["10.0.0.10"],
                "distribution": "per_peer",
            },
        }

        with self.assertRaisesRegex(
            ValueError,
            "explicit next-hop cardinality mismatch: expected 2, got 1",
        ):
            TaacIxia._formulaic_next_hop_values(mutation)

    def test_unknown_next_hop_distribution_is_rejected(self) -> None:
        mutation = {
            "peer_count": 1,
            "prefixes_per_peer": 1,
            "prefix": {"distribution": "shared"},
            "next_hop": {
                "kind": "formulaic",
                "start": "10.0.0.1",
                "step": 1,
                "distribution": "unknown",
            },
        }

        with self.assertRaisesRegex(
            ValueError,
            "unsupported next-hop distribution 'unknown'",
        ):
            TaacIxia._formulaic_next_hop_values(mutation)

    def test_per_prefix_indexing_tracks_shared_or_disjoint_membership(self) -> None:
        base = {
            "peer_count": 2,
            "prefixes_per_peer": 2,
            "next_hop": {
                "kind": "formulaic",
                "start": "2001:db8::1",
                "step": 1,
                "distribution": "per_prefix",
            },
        }
        self.assertEqual(
            ["2001:db8::1", "2001:db8::2"] * 2,
            TaacIxia._formulaic_next_hop_values(
                {**base, "prefix": {"distribution": "shared"}}
            ),
        )
        self.assertEqual(
            ["2001:db8::1", "2001:db8::2", "2001:db8::3", "2001:db8::4"],
            TaacIxia._formulaic_next_hop_values(
                {**base, "prefix": {"distribution": "disjoint"}}
            ),
        )

    def test_preflight_finishes_before_any_route_shell_is_stopped(self) -> None:
        device_group = _LifecycleObject(multiplier=1)
        network_group = _LifecycleObject()
        harness = _Harness((device_group, network_group, _Pool(), object()))

        with self.assertRaisesRegex(ValueError, "missing route attribute"):
            harness.configure_formulaic_bgp_routes([_mutation({})])

        self.assertEqual(0, device_group.stop_count)
        self.assertEqual(0, network_group.stop_count)

    def test_empty_mutation_batch_has_no_ixia_side_effects(self) -> None:
        device_group = _LifecycleObject(multiplier=1)
        network_group = _LifecycleObject()
        harness = _Harness((device_group, network_group, _Pool(), object()))

        with mock.patch.object(harness, "apply_changes") as apply_changes:
            harness.configure_formulaic_bgp_routes([])

        apply_changes.assert_not_called()
        self.assertEqual(0, device_group.stop_count)
        self.assertEqual(0, device_group.start_count)
        self.assertEqual(0, network_group.stop_count)
        self.assertEqual(0, network_group.start_count)

    def test_med_none_is_unset_but_zero_is_programmed(self) -> None:
        for med, enabled, expected_calls in ((None, False, 0), (0, True, 1)):
            with self.subTest(med=med):
                route = mock.MagicMock()
                TaacIxia._apply_formulaic_bgp_route(
                    _mutation({"med": med, "local_pref": 100, "origin": "igp"}),
                    (object(), object(), object(), route),
                    None,
                    None,
                )

                route.EnableMultiExitDiscriminator.Single.assert_called_once_with(
                    enabled
                )
                self.assertEqual(
                    expected_calls,
                    route.MultiExitDiscriminator.Single.call_count,
                )
                if expected_calls:
                    route.MultiExitDiscriminator.Single.assert_called_once_with(0)

    def test_partial_stop_failure_restarts_the_target(self) -> None:
        device_group = _LifecycleObject(multiplier=1)
        network_group = _LifecycleObject(fail_stop=True)
        harness = _Harness((device_group, network_group, _Pool(), object()))

        with self.assertRaisesRegex(RuntimeError, "stop failed"):
            harness.configure_formulaic_bgp_routes(
                [_mutation({"med": 0, "local_pref": 100, "origin": "igp"})]
            )

        self.assertEqual(1, device_group.start_count)
        self.assertEqual(0, network_group.start_count)
