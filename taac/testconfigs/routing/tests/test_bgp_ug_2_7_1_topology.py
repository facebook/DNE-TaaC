# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""Shared coverage for the canonical EBB full-scale UG 2.7 topology."""

import typing as t

from later.unittest import TestCase
from taac.abstractions.physical_inventory import BAG012_ASH6
from taac.testconfigs.routing.factories import (
    bgp_ebb_full_scale as factory,
)

_RUNTIME_POOL_NAMES = {
    "PREFIX_POOL_IBGP_IPV4_UG_2_7_RUNTIME",
    "PREFIX_POOL_IBGP_IPV6_UG_2_7_RUNTIME",
    "PREFIX_POOL_IPV4_EBGP_UG_2_7_RUNTIME",
    "PREFIX_POOL_IPV6_EBGP_UG_2_7_RUNTIME",
}


def _device_groups(config) -> list:
    return [
        group
        for port in config.basic_port_configs or []
        for group in port.device_group_configs or []
    ]


def _route_specs(
    config,
    pool_names: t.Collection[str],
) -> list[tuple[str, str, int, int, str, tuple[str, ...]]]:
    specs = []
    for group in _device_groups(config):
        for bgp_config in (group.v4_bgp_config, group.v6_bgp_config):
            if bgp_config is None:
                continue
            for route in bgp_config.route_scales or []:
                scale = route.v4_route_scale or route.v6_route_scale
                if scale is None or scale.prefix_name not in pool_names:
                    continue
                specs.append(
                    (
                        group.device_group_name,
                        scale.prefix_name,
                        route.network_group_index,
                        scale.prefix_count,
                        scale.starting_prefixes,
                        tuple(scale.communities or ()),
                    )
                )
    return sorted(specs)


def _runtime_route_specs(
    config, case: str | None = None
) -> list[tuple[str, str, int, int, str, tuple[str, ...]]]:
    specs = _route_specs(config, _RUNTIME_POOL_NAMES)
    return [spec for spec in specs if case is None or case in spec[1]]


class BgpUg27SharedTopologyTest(TestCase):
    def test_runtime_prefix_index_must_stay_inside_canonical_inventory(self) -> None:
        for index in (-1, True, 750):
            with self.subTest(index=index):
                with self.assertRaisesRegex(ValueError, "outside"):
                    factory._prefix_at_index(factory.EBB_EBGP_V4_PREFIX_SET, index)

    def test_unrelated_selection_does_not_add_recovery_route_intent(self) -> None:
        config = factory.create_bgp_ebb_full_scale_test_config(
            BAG012_ASH6,
            name="BAG012_UNRELATED_TEST",
            playbooks_selected=["bgp_ebb_longevity_playbook"],
        )

        self.assertEqual([], _runtime_route_specs(config))
