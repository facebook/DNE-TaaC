# Copyright (c) Meta Platforms, Inc. and affiliates.

import logging
import threading
import typing as t
import unittest
from unittest import mock

from ixia.ixia import types as ixia_types
from taac.ixia.ixia import IxiaSessionQuarantinedError
from taac.ixia.taac_ixia import TaacIxia


class _LifecycleObject:
    def __init__(
        self,
        *,
        multiplier: int | None = None,
        fail_stop: bool = False,
        fail_start: bool = False,
        href: str | None = None,
    ) -> None:
        self.Multiplier = multiplier
        self.fail_stop = fail_stop
        self.fail_start = fail_start
        self.stop_count = 0
        self.start_count = 0
        self.href = href or f"/test/lifecycle/{id(self)}"

    def Stop(self) -> None:
        self.stop_count += 1
        if self.fail_stop:
            raise RuntimeError("stop failed")

    def Start(self) -> None:
        self.start_count += 1
        if self.fail_start:
            raise RuntimeError("start failed")


class _RetryMultiplierNetworkGroup:
    def __init__(self) -> None:
        self._multiplier = 1
        self.href = "/test/retry-multiplier-network-group"
        self.multiplier_write_count = 0
        self.stop_count = 0

    @property
    def Multiplier(self) -> int:
        return self._multiplier

    @Multiplier.setter
    def Multiplier(self, value: int) -> None:
        self.multiplier_write_count += 1
        if self.multiplier_write_count == 1:
            raise RuntimeError("Changing the Multiplier in a started Network Group")
        self._multiplier = value

    def Stop(self) -> None:
        self.stop_count += 1


class _Pool:
    def __init__(self) -> None:
        self.NumberOfAddresses = 2
        self.NetworkAddress = mock.MagicMock()


class _ActiveField:
    def __init__(self, readback: list[object] | None = None) -> None:
        self._readback = readback
        self._written: list[bool] = []
        self.ValueList = mock.Mock(side_effect=self._write)

    def _write(self, values: list[bool]) -> None:
        self._written = list(values)

    @property
    def Values(self) -> list[object]:
        if self._readback is not None:
            return list(self._readback)
        return [str(value).lower() for value in self._written]


class _Harness(TaacIxia):
    def __init__(
        self,
        shell: tuple[object, object, object, object],
        *,
        shells: dict[tuple[str, str, str], tuple[object, object, object, object]]
        | None = None,
    ) -> None:
        self.shell = shell
        self.shells = shells or {}
        self.attribute_configs: list[ixia_types.BgpAttributeConfig] = []
        self.configure_attribute_calls = 0
        self.quarantine_reasons: list[str] = []
        self.logger = logging.getLogger("formulaic-bgp-routes-test")
        self._bounded_apply_lock = threading.RLock()
        self._session_quarantine_reason: str | None = None
        self._scenario_quarantine_record = None

    def _find_formulaic_bgp_route_shell(
        self,
        device_group_name: str,
        prefix_pool_name: str,
        afi: str,
    ) -> tuple[object, object, object, object]:
        return self.shells.get(
            (device_group_name, prefix_pool_name, afi),
            self.shell,
        )

    def _quarantine_session(self, reason: str) -> None:
        self._session_quarantine_reason = reason
        self.quarantine_reasons.append(reason)

    def configure_bgp_attributes(
        self,
        bgp_ip_route_property: object,
        bgp_attribute_configs: t.Sequence[ixia_types.BgpAttributeConfig],
    ) -> None:
        self.configure_attribute_calls += 1
        self.attribute_configs.extend(bgp_attribute_configs)


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


def _masked_mutation(
    blocks: object,
) -> dict[str, object]:
    mutation = _mutation({"med": 0, "local_pref": 100, "origin": "igp"})
    mutation.update(
        {
            "peer_count": 2,
            "prefixes_per_peer": 4,
            "flat_prefix_geometry": True,
            "inactive_peer_prefix_blocks": blocks,
        }
    )
    mutation["prefix"] = {
        "start": "11.0.0.0",
        "step": 1 << 8,
        "count": 4,
        "excluded_indices": [],
        "distribution": "shared",
    }
    return mutation


def _named_masked_mutation(
    device_group_name: str,
    prefix_pool_name: str,
) -> dict[str, object]:
    mutation = _masked_mutation(
        [
            {
                "prefix_start_index": 1,
                "prefix_count": 1,
                "peer_indices": [0],
            }
        ]
    )
    mutation.update(
        {
            "device_group_name": device_group_name,
            "prefix_pool_name": prefix_pool_name,
        }
    )
    return mutation


class FormulaicBgpRoutesTest(unittest.TestCase):
    def test_missing_component_href_fails_before_ixia_side_effects(self) -> None:
        device_group = _LifecycleObject(multiplier=1)
        del device_group.href
        network_group = _LifecycleObject(multiplier=1)
        pool = _Pool()
        route = mock.MagicMock()
        harness = _Harness((device_group, network_group, pool, route))

        with (
            mock.patch.object(harness, "apply_changes") as apply_changes,
            self.assertRaisesRegex(RuntimeError, "lacks a stable IXIA href"),
        ):
            harness.configure_formulaic_bgp_routes(
                [_mutation({"med": 0, "local_pref": 100, "origin": "igp"})]
            )

        apply_changes.assert_not_called()
        self.assertEqual(0, device_group.stop_count)
        self.assertEqual(0, network_group.stop_count)

    def test_quarantined_session_rejects_mutation_before_preparation(self) -> None:
        harness = _Harness((object(), object(), object(), object()))
        harness._session_quarantine_reason = "previous Active-mask verification failed"

        with (
            mock.patch.object(harness, "_prepare_formulaic_bgp_routes") as prepare,
            mock.patch.object(harness, "apply_changes") as apply_changes,
            self.assertRaisesRegex(IxiaSessionQuarantinedError, "previous Active-mask"),
        ):
            harness.configure_formulaic_bgp_routes([_mutation({})])

        prepare.assert_not_called()
        apply_changes.assert_not_called()

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

    def test_formulaic_per_peer_next_hops_emit_one_value_per_peer(self) -> None:
        self.assertEqual(
            ["10.0.0.1", "10.0.0.3"],
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
            ["10.0.0.10", "10.0.0.100"],
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

    def test_prepare_sparse_disjoint_route_uses_flat_child_geometry(self) -> None:
        device_group = _LifecycleObject(multiplier=2)
        network_group = _LifecycleObject()
        harness = _Harness((device_group, network_group, _Pool(), object()))
        mutation = {
            "device_group_name": "dg",
            "prefix_pool_name": "pool",
            "afi": "v4",
            "peer_count": 2,
            "prefixes_per_peer": 2,
            "prefix": {
                "start": "11.0.0.0",
                "step": 1 << 8,
                "count": 4,
                "excluded_indices": [1],
                "distribution": "disjoint",
            },
            "next_hop": {
                "kind": "explicit",
                "addresses": ["10.0.0.10", "10.0.0.100"],
                "distribution": "per_peer",
            },
            "attributes": {"med": 0, "local_pref": 100, "origin": "igp"},
        }

        prepared = harness._prepare_formulaic_bgp_routes([mutation])

        self.assertEqual(
            ["11.0.0.0", "11.0.2.0", "11.0.3.0", "11.0.4.0"],
            prepared[0][2],
        )
        self.assertEqual(
            ["10.0.0.10"] * 2 + ["10.0.0.100"] * 2,
            prepared[0][3],
        )

    def test_prepare_dense_shared_route_uses_requested_flat_geometry(self) -> None:
        device_group = _LifecycleObject(multiplier=2)
        network_group = _LifecycleObject(multiplier=1)
        harness = _Harness((device_group, network_group, _Pool(), object()))
        mutation = {
            **_mutation({"med": 0, "local_pref": 100, "origin": "igp"}),
            "peer_count": 2,
            "flat_prefix_geometry": True,
        }

        prepared = harness._prepare_formulaic_bgp_routes([mutation])

        self.assertEqual(
            ["11.0.0.0", "11.0.1.0"] * 2,
            prepared[0][2],
        )
        self.assertIsNone(prepared[0][3])

    def test_dense_route_without_flat_request_stays_compact(self) -> None:
        device_group = _LifecycleObject(multiplier=1)
        network_group = _LifecycleObject(multiplier=1)
        harness = _Harness((device_group, network_group, _Pool(), object()))

        prepared = harness._prepare_formulaic_bgp_routes(
            [_mutation({"med": 0, "local_pref": 100, "origin": "igp"})]
        )

        self.assertIsNone(prepared[0][2])
        self.assertIsNone(prepared[0][3])

    def test_dense_route_flattening_is_idempotent(self) -> None:
        device_group = _LifecycleObject(multiplier=2)
        network_group = _LifecycleObject(multiplier=1)
        pool = _Pool()
        route = mock.MagicMock()
        harness = _Harness((device_group, network_group, pool, route))
        mutation = {
            **_mutation({"med": 0, "local_pref": 100, "origin": "igp"}),
            "peer_count": 2,
            "flat_prefix_geometry": True,
        }

        with mock.patch.object(harness, "apply_changes"):
            harness.configure_formulaic_bgp_routes([mutation])
            harness.configure_formulaic_bgp_routes([mutation])

        self.assertEqual(2, network_group.Multiplier)
        self.assertEqual(1, pool.NumberOfAddresses)
        pool.NetworkAddress.ValueList.assert_called_with(["11.0.0.0", "11.0.1.0"] * 2)

    def test_sparse_route_flattening_is_idempotent(self) -> None:
        device_group = _LifecycleObject(multiplier=2)
        network_group = _LifecycleObject(multiplier=1)
        pool = _Pool()
        route = mock.MagicMock()
        harness = _Harness((device_group, network_group, pool, route))
        mutation = {
            "device_group_name": "dg",
            "prefix_pool_name": "pool",
            "afi": "v4",
            "peer_count": 2,
            "prefixes_per_peer": 2,
            "prefix": {
                "start": "11.0.0.0",
                "step": 1 << 8,
                "count": 4,
                "excluded_indices": [1],
                "distribution": "disjoint",
            },
            "next_hop": {
                "kind": "explicit",
                "addresses": ["10.0.0.10", "10.0.0.100"],
                "distribution": "per_peer",
            },
            "attributes": {"med": 0, "local_pref": 100, "origin": "igp"},
        }

        with mock.patch.object(harness, "apply_changes"):
            harness.configure_formulaic_bgp_routes([mutation])
            harness.configure_formulaic_bgp_routes([mutation])

        self.assertEqual(2, network_group.Multiplier)
        self.assertEqual(1, pool.NumberOfAddresses)
        pool.NetworkAddress.ValueList.assert_called_with(
            ["11.0.0.0", "11.0.2.0", "11.0.3.0", "11.0.4.0"]
        )
        route.Ipv4NextHop.ValueList.assert_called_with(
            ["10.0.0.10"] * 2 + ["10.0.0.100"] * 2
        )

    def test_sparse_route_multiplier_write_retries_after_stopping_groups(self) -> None:
        device_group = _LifecycleObject(multiplier=2)
        network_group = _RetryMultiplierNetworkGroup()
        pool = _Pool()
        route = mock.MagicMock()
        harness = _Harness((device_group, network_group, pool, route))
        mutation = {
            "afi": "v4",
            "prefixes_per_peer": 2,
            "attributes": {"med": 0, "local_pref": 100, "origin": "igp"},
        }

        with mock.patch(
            "neteng.test_infra.dne.taac.ixia.taac_ixia.time.sleep"
        ) as sleep:
            harness._apply_formulaic_bgp_route(
                mutation,
                harness.shell,
                ["11.0.0.0", "11.0.2.0"],
                ["10.0.0.10", "10.0.0.10"],
            )

        self.assertEqual(2, network_group.multiplier_write_count)
        self.assertEqual(2, network_group.Multiplier)
        self.assertEqual(1, device_group.stop_count)
        self.assertEqual(1, network_group.stop_count)
        sleep.assert_called_once_with(3)

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

    def test_inactive_blocks_program_exact_peer_major_active_mask(self) -> None:
        device_group = _LifecycleObject(multiplier=2)
        network_group = _LifecycleObject(multiplier=1)
        pool = _Pool()
        pool.NumberOfAddresses = 4
        route = mock.MagicMock()
        route.Active = _ActiveField()
        harness = _Harness((device_group, network_group, pool, route))
        mutation = _masked_mutation(
            [
                {
                    "prefix_start_index": 1,
                    "prefix_count": 2,
                    "peer_indices": [0],
                },
                {
                    "prefix_start_index": 3,
                    "prefix_count": 1,
                    "peer_indices": [1],
                },
            ]
        )

        with mock.patch.object(harness, "apply_changes") as apply_changes:
            harness.configure_formulaic_bgp_routes([mutation])

        expected = [True, False, False, True, True, True, True, False]
        route.Active.ValueList.assert_called_once_with(expected)
        apply_changes.assert_called_once_with()
        self.assertEqual(1, device_group.stop_count)
        self.assertEqual(1, network_group.stop_count)
        self.assertEqual(1, device_group.start_count)
        self.assertEqual(1, network_group.start_count)

    def test_empty_inactive_blocks_reset_every_cell_active(self) -> None:
        device_group = _LifecycleObject(multiplier=2)
        network_group = _LifecycleObject(multiplier=1)
        pool = _Pool()
        pool.NumberOfAddresses = 4
        route = mock.MagicMock(Active=_ActiveField())
        harness = _Harness((device_group, network_group, pool, route))

        with mock.patch.object(harness, "apply_changes"):
            harness.configure_formulaic_bgp_routes([_masked_mutation([])])

        route.Active.ValueList.assert_called_once_with([True] * 8)

    def test_invalid_inactive_blocks_have_no_ixia_side_effects(self) -> None:
        invalid_cases = {
            "not flat": (
                {"flat_prefix_geometry": False},
                [
                    {
                        "prefix_start_index": 0,
                        "prefix_count": 1,
                        "peer_indices": [0],
                    }
                ],
            ),
            "not shared": (
                {"prefix": {"count": 8, "distribution": "disjoint"}},
                [
                    {
                        "prefix_start_index": 0,
                        "prefix_count": 1,
                        "peer_indices": [0],
                    }
                ],
            ),
            "zero count": (
                {},
                [
                    {
                        "prefix_start_index": 0,
                        "prefix_count": 0,
                        "peer_indices": [0],
                    }
                ],
            ),
            "prefix out of bounds": (
                {},
                [
                    {
                        "prefix_start_index": 3,
                        "prefix_count": 2,
                        "peer_indices": [0],
                    }
                ],
            ),
            "empty peers": (
                {},
                [
                    {
                        "prefix_start_index": 0,
                        "prefix_count": 1,
                        "peer_indices": [],
                    }
                ],
            ),
            "unsorted peers": (
                {},
                [
                    {
                        "prefix_start_index": 0,
                        "prefix_count": 1,
                        "peer_indices": [1, 0],
                    }
                ],
            ),
            "duplicate peers": (
                {},
                [
                    {
                        "prefix_start_index": 0,
                        "prefix_count": 1,
                        "peer_indices": [0, 0],
                    }
                ],
            ),
            "peer out of bounds": (
                {},
                [
                    {
                        "prefix_start_index": 0,
                        "prefix_count": 1,
                        "peer_indices": [2],
                    }
                ],
            ),
            "all peers": (
                {},
                [
                    {
                        "prefix_start_index": 0,
                        "prefix_count": 1,
                        "peer_indices": [0, 1],
                    }
                ],
            ),
            "overlapping blocks": (
                {},
                [
                    {
                        "prefix_start_index": 0,
                        "prefix_count": 2,
                        "peer_indices": [0],
                    },
                    {
                        "prefix_start_index": 1,
                        "prefix_count": 1,
                        "peer_indices": [1],
                    },
                ],
            ),
            "unsorted blocks": (
                {},
                [
                    {
                        "prefix_start_index": 2,
                        "prefix_count": 1,
                        "peer_indices": [0],
                    },
                    {
                        "prefix_start_index": 0,
                        "prefix_count": 1,
                        "peer_indices": [1],
                    },
                ],
            ),
        }

        for name, (overrides, blocks) in invalid_cases.items():
            with self.subTest(name=name):
                device_group = _LifecycleObject(multiplier=2)
                network_group = _LifecycleObject(multiplier=1)
                pool = _Pool()
                pool.NumberOfAddresses = 4
                harness = _Harness(
                    (device_group, network_group, pool, mock.MagicMock())
                )
                mutation = _masked_mutation(blocks)
                if "prefix" in overrides:
                    prefix = t.cast(dict[str, object], mutation["prefix"])
                    prefix_overrides = t.cast(dict[str, object], overrides["prefix"])
                    prefix.update(prefix_overrides)
                else:
                    mutation.update(overrides)

                with mock.patch.object(harness, "apply_changes") as apply_changes:
                    with self.assertRaises(ValueError):
                        harness.configure_formulaic_bgp_routes([mutation])

                apply_changes.assert_not_called()
                self.assertEqual(0, device_group.stop_count)
                self.assertEqual(0, device_group.start_count)
                self.assertEqual(0, network_group.stop_count)
                self.assertEqual(0, network_group.start_count)

    def test_active_readback_refreshes_route_property_before_verification(self) -> None:
        device_group = _LifecycleObject(multiplier=2)
        network_group = _LifecycleObject(multiplier=1)
        pool = _Pool()
        pool.NumberOfAddresses = 4
        active = _ActiveField(readback=["true"] * 8)
        route = mock.MagicMock(Active=active)
        expected = [True, False, True, True, True, True, True, True]
        route.refresh.side_effect = lambda: setattr(
            active,
            "_readback",
            [str(value).lower() for value in expected],
        )
        harness = _Harness((device_group, network_group, pool, route))
        mutation = _masked_mutation(
            [
                {
                    "prefix_start_index": 1,
                    "prefix_count": 1,
                    "peer_indices": [0],
                }
            ]
        )

        with mock.patch.object(harness, "apply_changes"):
            harness.configure_formulaic_bgp_routes([mutation])

        route.refresh.assert_called_once_with()
        self.assertEqual(1, device_group.start_count)
        self.assertEqual(1, network_group.start_count)

    def test_active_readback_normalizes_boolean_representations(self) -> None:
        device_group = _LifecycleObject(multiplier=2)
        network_group = _LifecycleObject(multiplier=1)
        pool = _Pool()
        pool.NumberOfAddresses = 4
        route = mock.MagicMock(
            Active=_ActiveField(
                readback=[
                    True,
                    False,
                    " TRUE ",
                    "true",
                    True,
                    " TRUE ",
                    True,
                    "true",
                ]
            )
        )
        harness = _Harness((device_group, network_group, pool, route))

        with mock.patch.object(harness, "apply_changes"):
            harness.configure_formulaic_bgp_routes(
                [
                    _masked_mutation(
                        [
                            {
                                "prefix_start_index": 1,
                                "prefix_count": 1,
                                "peer_indices": [0],
                            }
                        ]
                    )
                ]
            )

        self.assertEqual(1, device_group.start_count)
        self.assertEqual(1, network_group.start_count)

    def test_active_readback_rejects_undocumented_boolean_aliases(self) -> None:
        for value in (0, 1, "0", "1", "enabled", "disabled", "on", "off", None, ""):
            with (
                self.subTest(value=value),
                self.assertRaisesRegex(ValueError, "at index 3"),
            ):
                TaacIxia._normalize_formulaic_active_value(value, index=3)

    def test_active_readback_rejects_unknown_boolean_representation(self) -> None:
        device_group = _LifecycleObject(multiplier=2)
        network_group = _LifecycleObject(multiplier=1)
        pool = _Pool()
        pool.NumberOfAddresses = 4
        route = mock.MagicMock(Active=_ActiveField(readback=["maybe"] * 8))
        harness = _Harness((device_group, network_group, pool, route))

        with mock.patch.object(harness, "apply_changes"):
            with self.assertRaisesRegex(
                RuntimeError,
                "unsupported IXIA boolean value",
            ):
                harness.configure_formulaic_bgp_routes(
                    [
                        _masked_mutation(
                            [
                                {
                                    "prefix_start_index": 1,
                                    "prefix_count": 1,
                                    "peer_indices": [0],
                                }
                            ]
                        )
                    ]
                )

        self.assertEqual(0, device_group.start_count)
        self.assertEqual(0, network_group.start_count)
        self.assertEqual(1, len(harness.quarantine_reasons))

    def test_active_readback_mismatch_leaves_groups_stopped(self) -> None:
        device_group = _LifecycleObject(multiplier=2)
        network_group = _LifecycleObject(multiplier=1)
        pool = _Pool()
        pool.NumberOfAddresses = 4
        route = mock.MagicMock()
        route.Active = _ActiveField(readback=["true"] * 8)
        harness = _Harness((device_group, network_group, pool, route))
        mutation = _masked_mutation(
            [
                {
                    "prefix_start_index": 1,
                    "prefix_count": 1,
                    "peer_indices": [0],
                }
            ]
        )

        with mock.patch.object(harness, "apply_changes") as apply_changes:
            with self.assertRaisesRegex(RuntimeError, "Active readback mismatch"):
                harness.configure_formulaic_bgp_routes([mutation])

        apply_changes.assert_called_once_with()
        self.assertEqual(0, device_group.start_count)
        self.assertEqual(0, network_group.start_count)
        self.assertEqual(1, len(harness.quarantine_reasons))

    def test_later_readback_failure_restarts_independently_verified_route(
        self,
    ) -> None:
        verified_device_group = _LifecycleObject(multiplier=2)
        verified_network_group = _LifecycleObject(multiplier=1)
        verified_pool = _Pool()
        verified_pool.NumberOfAddresses = 4
        verified_route = mock.MagicMock(Active=_ActiveField())
        pending_device_group = _LifecycleObject(multiplier=2)
        pending_network_group = _LifecycleObject(multiplier=1)
        pending_pool = _Pool()
        pending_pool.NumberOfAddresses = 4
        pending_route = mock.MagicMock(Active=_ActiveField(readback=["true"] * 8))
        verified_shell = (
            verified_device_group,
            verified_network_group,
            verified_pool,
            verified_route,
        )
        pending_shell = (
            pending_device_group,
            pending_network_group,
            pending_pool,
            pending_route,
        )
        harness = _Harness(
            verified_shell,
            shells={
                ("verified-dg", "verified-pool", "v4"): verified_shell,
                ("pending-dg", "pending-pool", "v4"): pending_shell,
            },
        )

        with mock.patch.object(harness, "apply_changes"):
            with self.assertRaisesRegex(RuntimeError, "Active readback mismatch"):
                harness.configure_formulaic_bgp_routes(
                    [
                        _named_masked_mutation("verified-dg", "verified-pool"),
                        _named_masked_mutation("pending-dg", "pending-pool"),
                    ]
                )

        self.assertEqual(1, verified_device_group.start_count)
        self.assertEqual(1, verified_network_group.start_count)
        self.assertEqual(0, pending_device_group.start_count)
        self.assertEqual(0, pending_network_group.start_count)
        self.assertEqual(1, len(harness.quarantine_reasons))

    def test_later_lookup_failure_restarts_independently_verified_route(
        self,
    ) -> None:
        verified_device_group = _LifecycleObject(multiplier=2)
        verified_network_group = _LifecycleObject(multiplier=1)
        verified_pool = _Pool()
        verified_pool.NumberOfAddresses = 4
        verified_shell = (
            verified_device_group,
            verified_network_group,
            verified_pool,
            mock.MagicMock(Active=_ActiveField()),
        )
        pending_device_group = _LifecycleObject(multiplier=2)
        pending_network_group = _LifecycleObject(multiplier=1)
        pending_pool = _Pool()
        pending_pool.NumberOfAddresses = 4
        pending_shell = (
            pending_device_group,
            pending_network_group,
            pending_pool,
            mock.MagicMock(Active=_ActiveField()),
        )
        pending_key = ("pending-dg", "pending-pool", "v4")
        harness = _Harness(
            verified_shell,
            shells={
                ("verified-dg", "verified-pool", "v4"): verified_shell,
                pending_key: pending_shell,
            },
        )
        original_lookup = harness._find_formulaic_bgp_route_shell
        lookup_counts: dict[tuple[str, str, str], int] = {}

        def lookup(device_group_name: str, prefix_pool_name: str, afi: str):
            key = (device_group_name, prefix_pool_name, afi)
            lookup_counts[key] = lookup_counts.get(key, 0) + 1
            if key == pending_key and lookup_counts[key] == 2:
                raise RuntimeError("verification lookup failed")
            return original_lookup(*key)

        with (
            mock.patch.object(
                harness,
                "_find_formulaic_bgp_route_shell",
                side_effect=lookup,
            ),
            mock.patch.object(harness, "apply_changes"),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "Active readback failed.*verification lookup failed",
            ):
                harness.configure_formulaic_bgp_routes(
                    [
                        _named_masked_mutation("verified-dg", "verified-pool"),
                        _named_masked_mutation(*pending_key[:2]),
                    ]
                )

        self.assertEqual(1, verified_device_group.start_count)
        self.assertEqual(1, verified_network_group.start_count)
        self.assertEqual(0, pending_device_group.start_count)
        self.assertEqual(0, pending_network_group.start_count)
        self.assertEqual(1, len(harness.quarantine_reasons))
        self.assertNotIn("verified-pool", harness.quarantine_reasons[0])
        self.assertIn("pending-pool", harness.quarantine_reasons[0])

    def test_early_lookup_failure_still_verifies_and_restarts_later_route(
        self,
    ) -> None:
        failing_device_group = _LifecycleObject(multiplier=2)
        failing_network_group = _LifecycleObject(multiplier=1)
        failing_pool = _Pool()
        failing_pool.NumberOfAddresses = 4
        failing_shell = (
            failing_device_group,
            failing_network_group,
            failing_pool,
            mock.MagicMock(Active=_ActiveField()),
        )
        verified_device_group = _LifecycleObject(multiplier=2)
        verified_network_group = _LifecycleObject(multiplier=1)
        verified_pool = _Pool()
        verified_pool.NumberOfAddresses = 4
        verified_shell = (
            verified_device_group,
            verified_network_group,
            verified_pool,
            mock.MagicMock(Active=_ActiveField()),
        )
        failing_key = ("failing-dg", "failing-pool", "v4")
        harness = _Harness(
            failing_shell,
            shells={
                failing_key: failing_shell,
                ("verified-dg", "verified-pool", "v4"): verified_shell,
            },
        )
        original_lookup = harness._find_formulaic_bgp_route_shell
        lookup_counts: dict[tuple[str, str, str], int] = {}

        def lookup(device_group_name: str, prefix_pool_name: str, afi: str):
            key = (device_group_name, prefix_pool_name, afi)
            lookup_counts[key] = lookup_counts.get(key, 0) + 1
            if key == failing_key and lookup_counts[key] == 2:
                raise RuntimeError("verification lookup failed")
            return original_lookup(*key)

        with (
            mock.patch.object(
                harness,
                "_find_formulaic_bgp_route_shell",
                side_effect=lookup,
            ),
            mock.patch.object(harness, "apply_changes"),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "Active readback failed.*verification lookup failed",
            ):
                harness.configure_formulaic_bgp_routes(
                    [
                        _named_masked_mutation(*failing_key[:2]),
                        _named_masked_mutation("verified-dg", "verified-pool"),
                    ]
                )

        self.assertEqual(0, failing_device_group.start_count)
        self.assertEqual(0, failing_network_group.start_count)
        self.assertEqual(1, verified_device_group.start_count)
        self.assertEqual(1, verified_network_group.start_count)
        self.assertEqual(1, len(harness.quarantine_reasons))
        self.assertIn("failing-pool", harness.quarantine_reasons[0])
        self.assertNotIn("verified-pool", harness.quarantine_reasons[0])

    def test_later_readback_failure_retains_shared_href_parent_only(self) -> None:
        first_shared_device_group = _LifecycleObject(
            multiplier=2,
            href="/api/v1/sessions/1/ixnetwork/topology/1/deviceGroup/1",
        )
        second_shared_device_group = _LifecycleObject(
            multiplier=2,
            href="/api/v1/sessions/1/ixnetwork/topology/1/deviceGroup/1",
        )
        verified_network_group = _LifecycleObject(multiplier=1)
        verified_pool = _Pool()
        verified_pool.NumberOfAddresses = 4
        verified_route = mock.MagicMock(Active=_ActiveField())
        pending_network_group = _LifecycleObject(multiplier=1)
        pending_pool = _Pool()
        pending_pool.NumberOfAddresses = 4
        pending_route = mock.MagicMock(Active=_ActiveField(readback=["true"] * 8))
        verified_shell = (
            first_shared_device_group,
            verified_network_group,
            verified_pool,
            verified_route,
        )
        pending_shell = (
            second_shared_device_group,
            pending_network_group,
            pending_pool,
            pending_route,
        )
        harness = _Harness(
            verified_shell,
            shells={
                ("shared-dg", "verified-pool", "v4"): verified_shell,
                ("shared-dg", "pending-pool", "v4"): pending_shell,
            },
        )

        with mock.patch.object(harness, "apply_changes"):
            with self.assertRaisesRegex(RuntimeError, "Active readback mismatch"):
                harness.configure_formulaic_bgp_routes(
                    [
                        _named_masked_mutation("shared-dg", "verified-pool"),
                        _named_masked_mutation("shared-dg", "pending-pool"),
                    ]
                )

        self.assertEqual(1, first_shared_device_group.stop_count)
        self.assertEqual(0, second_shared_device_group.stop_count)
        self.assertEqual(0, first_shared_device_group.start_count)
        self.assertEqual(0, second_shared_device_group.start_count)
        self.assertEqual(1, verified_network_group.start_count)
        self.assertEqual(0, pending_network_group.start_count)
        self.assertEqual(1, len(harness.quarantine_reasons))
        self.assertNotIn("verified-pool", harness.quarantine_reasons[0])
        self.assertIn("pending-pool", harness.quarantine_reasons[0])

    def test_shared_href_parent_is_stopped_and_started_once(self) -> None:
        shared_href = "/api/v1/sessions/1/ixnetwork/topology/1/deviceGroup/1"
        first_shared_device_group = _LifecycleObject(
            multiplier=2,
            href=shared_href,
        )
        second_shared_device_group = _LifecycleObject(
            multiplier=2,
            href=shared_href,
        )
        first_network_group = _LifecycleObject(multiplier=1)
        first_pool = _Pool()
        first_pool.NumberOfAddresses = 4
        first_shell = (
            first_shared_device_group,
            first_network_group,
            first_pool,
            mock.MagicMock(Active=_ActiveField()),
        )
        second_network_group = _LifecycleObject(multiplier=1)
        second_pool = _Pool()
        second_pool.NumberOfAddresses = 4
        second_shell = (
            second_shared_device_group,
            second_network_group,
            second_pool,
            mock.MagicMock(Active=_ActiveField()),
        )
        harness = _Harness(
            first_shell,
            shells={
                ("shared-dg", "first-pool", "v4"): first_shell,
                ("shared-dg", "second-pool", "v4"): second_shell,
            },
        )

        with mock.patch.object(harness, "apply_changes"):
            harness.configure_formulaic_bgp_routes(
                [
                    _named_masked_mutation("shared-dg", "first-pool"),
                    _named_masked_mutation("shared-dg", "second-pool"),
                ]
            )

        self.assertEqual(1, first_shared_device_group.stop_count)
        self.assertEqual(1, first_shared_device_group.start_count)
        self.assertEqual(0, second_shared_device_group.stop_count)
        self.assertEqual(0, second_shared_device_group.start_count)
        self.assertEqual(1, first_network_group.start_count)
        self.assertEqual(1, second_network_group.start_count)
        self.assertEqual([], harness.quarantine_reasons)

    def test_active_apply_failure_leaves_groups_stopped(self) -> None:
        device_group = _LifecycleObject(multiplier=2)
        network_group = _LifecycleObject(multiplier=1)
        pool = _Pool()
        pool.NumberOfAddresses = 4
        route = mock.MagicMock()
        route.Active = _ActiveField()
        harness = _Harness((device_group, network_group, pool, route))
        mutation = _masked_mutation(
            [
                {
                    "prefix_start_index": 1,
                    "prefix_count": 1,
                    "peer_indices": [0],
                }
            ]
        )

        with mock.patch.object(
            harness,
            "apply_changes",
            side_effect=RuntimeError("apply failed"),
        ):
            with self.assertRaisesRegex(RuntimeError, "apply failed"):
                harness.configure_formulaic_bgp_routes([mutation])

        self.assertEqual(0, device_group.start_count)
        self.assertEqual(0, network_group.start_count)
        self.assertEqual(1, len(harness.quarantine_reasons))

    def test_first_active_write_failure_restarts_unattempted_masked_route(
        self,
    ) -> None:
        failing_device_group = _LifecycleObject(multiplier=2)
        failing_network_group = _LifecycleObject(multiplier=1)
        failing_pool = _Pool()
        failing_pool.NumberOfAddresses = 4
        failing_active = _ActiveField()
        failing_active.ValueList.side_effect = RuntimeError("Active write failed")
        failing_shell = (
            failing_device_group,
            failing_network_group,
            failing_pool,
            mock.MagicMock(Active=failing_active),
        )
        unattempted_device_group = _LifecycleObject(multiplier=2)
        unattempted_network_group = _LifecycleObject(multiplier=1)
        unattempted_pool = _Pool()
        unattempted_pool.NumberOfAddresses = 4
        unattempted_shell = (
            unattempted_device_group,
            unattempted_network_group,
            unattempted_pool,
            mock.MagicMock(Active=_ActiveField()),
        )
        harness = _Harness(
            failing_shell,
            shells={
                ("failing-dg", "failing-pool", "v4"): failing_shell,
                (
                    "unattempted-dg",
                    "unattempted-pool",
                    "v4",
                ): unattempted_shell,
            },
        )

        with self.assertRaisesRegex(RuntimeError, "Active write failed"):
            harness.configure_formulaic_bgp_routes(
                [
                    _named_masked_mutation("failing-dg", "failing-pool"),
                    _named_masked_mutation(
                        "unattempted-dg",
                        "unattempted-pool",
                    ),
                ]
            )

        self.assertEqual(0, failing_device_group.start_count)
        self.assertEqual(0, failing_network_group.start_count)
        self.assertEqual(1, unattempted_device_group.start_count)
        self.assertEqual(1, unattempted_network_group.start_count)
        self.assertEqual(1, len(harness.quarantine_reasons))
        self.assertIn("failing-pool", harness.quarantine_reasons[0])
        self.assertNotIn("unattempted-pool", harness.quarantine_reasons[0])

    def test_masked_route_failure_before_active_write_restarts_groups(self) -> None:
        device_group = _LifecycleObject(multiplier=2)
        network_group = _LifecycleObject(multiplier=1)
        pool = _Pool()
        pool.NumberOfAddresses = 4
        route = mock.MagicMock()
        route.Active = _ActiveField()
        harness = _Harness((device_group, network_group, pool, route))
        mutation = _masked_mutation(
            [
                {
                    "prefix_start_index": 1,
                    "prefix_count": 1,
                    "peer_indices": [0],
                }
            ]
        )

        with mock.patch.object(
            harness,
            "_apply_formulaic_bgp_route",
            side_effect=RuntimeError("route mutation failed"),
        ):
            with self.assertRaisesRegex(RuntimeError, "route mutation failed"):
                harness.configure_formulaic_bgp_routes([mutation])

        self.assertEqual(1, device_group.start_count)
        self.assertEqual(1, network_group.start_count)
        self.assertEqual([], harness.quarantine_reasons)

    def test_active_apply_failure_restarts_mask_free_groups(self) -> None:
        masked_device_group = _LifecycleObject(multiplier=2)
        masked_network_group = _LifecycleObject(multiplier=1)
        masked_pool = _Pool()
        masked_pool.NumberOfAddresses = 4
        masked_route = mock.MagicMock(Active=_ActiveField())
        safe_device_group = _LifecycleObject(multiplier=1)
        safe_network_group = _LifecycleObject(multiplier=1)
        safe_shell = (
            safe_device_group,
            safe_network_group,
            _Pool(),
            mock.MagicMock(),
        )
        masked_shell = (
            masked_device_group,
            masked_network_group,
            masked_pool,
            masked_route,
        )
        harness = _Harness(
            masked_shell,
            shells={
                ("dg", "pool", "v4"): masked_shell,
                ("safe-dg", "safe-pool", "v4"): safe_shell,
            },
        )
        masked_mutation = _masked_mutation(
            [
                {
                    "prefix_start_index": 1,
                    "prefix_count": 1,
                    "peer_indices": [0],
                }
            ]
        )
        safe_mutation = _mutation({"med": 0, "local_pref": 100, "origin": "igp"})
        safe_mutation.update(
            {
                "device_group_name": "safe-dg",
                "prefix_pool_name": "safe-pool",
            }
        )

        with (
            mock.patch.object(harness, "_apply_formulaic_bgp_route"),
            mock.patch.object(
                harness,
                "apply_changes",
                side_effect=RuntimeError("apply failed"),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "apply failed"):
                harness.configure_formulaic_bgp_routes([masked_mutation, safe_mutation])

        self.assertEqual(0, masked_device_group.start_count)
        self.assertEqual(0, masked_network_group.start_count)
        self.assertEqual(1, safe_device_group.start_count)
        self.assertEqual(1, safe_network_group.start_count)
        self.assertEqual(1, len(harness.quarantine_reasons))

    def test_active_apply_failure_retains_shared_masked_parent(self) -> None:
        shared_device_group = _LifecycleObject(multiplier=2)
        masked_network_group = _LifecycleObject(multiplier=1)
        masked_pool = _Pool()
        masked_pool.NumberOfAddresses = 4
        masked_route = mock.MagicMock(Active=_ActiveField())
        safe_network_group = _LifecycleObject(multiplier=1)
        masked_shell = (
            shared_device_group,
            masked_network_group,
            masked_pool,
            masked_route,
        )
        safe_shell = (
            shared_device_group,
            safe_network_group,
            _Pool(),
            mock.MagicMock(),
        )
        harness = _Harness(
            masked_shell,
            shells={
                ("dg", "pool", "v4"): masked_shell,
                ("dg", "safe-pool", "v4"): safe_shell,
            },
        )
        masked_mutation = _masked_mutation(
            [
                {
                    "prefix_start_index": 1,
                    "prefix_count": 1,
                    "peer_indices": [0],
                }
            ]
        )
        safe_mutation = _mutation({"med": 0, "local_pref": 100, "origin": "igp"})
        safe_mutation["prefix_pool_name"] = "safe-pool"
        safe_mutation["peer_count"] = 2

        with (
            mock.patch.object(harness, "_apply_formulaic_bgp_route"),
            mock.patch.object(
                harness,
                "apply_changes",
                side_effect=RuntimeError("apply failed"),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "apply failed"):
                harness.configure_formulaic_bgp_routes([masked_mutation, safe_mutation])

        self.assertEqual(0, shared_device_group.start_count)
        self.assertEqual(0, masked_network_group.start_count)
        self.assertEqual(1, safe_network_group.start_count)
        self.assertEqual(1, len(harness.quarantine_reasons))

    def test_mask_free_apply_failure_restarts_all_groups(self) -> None:
        device_group = _LifecycleObject(multiplier=1)
        network_group = _LifecycleObject(multiplier=1)
        harness = _Harness((device_group, network_group, _Pool(), mock.MagicMock()))
        mutation = _mutation({"med": 0, "local_pref": 100, "origin": "igp"})

        with (
            mock.patch.object(harness, "_apply_formulaic_bgp_route"),
            mock.patch.object(
                harness,
                "apply_changes",
                side_effect=RuntimeError("apply failed"),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "apply failed"):
                harness.configure_formulaic_bgp_routes([mutation])

        self.assertEqual(1, device_group.start_count)
        self.assertEqual(1, network_group.start_count)
        self.assertEqual([], harness.quarantine_reasons)

    def test_verified_active_mask_start_failure_recovers_without_quarantine(
        self,
    ) -> None:
        device_group = _LifecycleObject(multiplier=2, fail_start=True)
        network_group = _LifecycleObject(multiplier=1)
        pool = _Pool()
        pool.NumberOfAddresses = 4
        route = mock.MagicMock(Active=_ActiveField())
        harness = _Harness((device_group, network_group, pool, route))
        mutation = _masked_mutation(
            [
                {
                    "prefix_start_index": 1,
                    "prefix_count": 1,
                    "peer_indices": [0],
                }
            ]
        )

        with mock.patch.object(harness, "apply_changes"):
            with self.assertRaisesRegex(RuntimeError, "start failed"):
                harness.configure_formulaic_bgp_routes([mutation])

        self.assertEqual(2, device_group.start_count)
        self.assertEqual(1, network_group.start_count)
        self.assertEqual([], harness.quarantine_reasons)

    def test_med_none_is_unset_but_zero_is_programmed(self) -> None:
        for med, enabled, expected_calls in ((None, False, 0), (0, True, 1)):
            with self.subTest(med=med):
                route = mock.MagicMock()
                harness = _Harness((object(), object(), object(), route))
                harness._apply_formulaic_bgp_route(
                    _mutation({"med": med, "local_pref": 100, "origin": "igp"}),
                    harness.shell,
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

    def test_typed_community_rows_use_existing_attribute_configuration(self) -> None:
        harness = _Harness((object(), object(), object(), object()))
        mutation = _mutation({"med": 0, "local_pref": 100, "origin": "igp"})
        mutation["route_attributes"] = {
            "distribution": "round_robin",
            "community_rows": [["65531:50300", "65529:30000"]],
            "extended_community_rows": [["rt:65529:40000"]],
        }

        harness._apply_formulaic_bgp_route(
            mutation,
            harness.shell,
            prefix_values=None,
            next_hop_values=None,
        )

        self.assertEqual(2, len(harness.attribute_configs))
        self.assertEqual(1, harness.configure_attribute_calls)
        self.assertEqual(
            [
                [["65531:50300", "65529:30000"]],
                [["rt:65529:40000"]],
            ],
            [config.value_lists for config in harness.attribute_configs],
        )

    def test_empty_typed_attribute_rows_skip_runtime_configuration(self) -> None:
        harness = _Harness((object(), object(), object(), object()))
        mutation = _mutation({"med": None, "local_pref": 100, "origin": "igp"})
        mutation["route_attributes"] = {
            "distribution": "round_robin",
            "community_rows": [],
            "extended_community_rows": [],
        }

        harness._apply_formulaic_bgp_route(
            mutation,
            harness.shell,
            prefix_values=None,
            next_hop_values=None,
        )

        self.assertEqual(0, harness.configure_attribute_calls)
        self.assertEqual([], harness.attribute_configs)

    def test_inconsistent_typed_community_width_fails_before_stop(self) -> None:
        device_group = _LifecycleObject(multiplier=1)
        network_group = _LifecycleObject()
        harness = _Harness((device_group, network_group, _Pool(), object()))
        mutation = _mutation({"med": 0, "local_pref": 100, "origin": "igp"})
        mutation["route_attributes"] = {
            "distribution": "round_robin",
            "community_rows": [["65531:50300"], ["65531:50300", "65529:30000"]],
            "extended_community_rows": [],
        }

        with self.assertRaisesRegex(ValueError, "inconsistent community_rows"):
            harness.configure_formulaic_bgp_routes([mutation])

        self.assertEqual(0, device_group.stop_count)
        self.assertEqual(0, network_group.stop_count)
