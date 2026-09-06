# Copyright (c) Meta Platforms, Inc. and affiliates.

from __future__ import annotations

import ipaddress
import unittest
from collections.abc import Mapping
from types import SimpleNamespace

from taac.libs.fpf.fpf_gar import (
    evaluate_gar_pair,
    GarDeviceSnapshot,
    summarize_agent_routes,
    summarize_bgp_entries,
)


PREFIX = "5000:ca::/64"


def _bgp_entry(
    path_count: int,
    capacity: int | None = None,
    *,
    topology_fields: Mapping[str, object] | None = None,
    communities: list[object] | None = None,
):
    network = ipaddress.ip_network(PREFIX)
    topology = dict(topology_fields or {})
    if capacity is not None:
        topology.update({"remote_rack_capacity": capacity, "spine_id": 1})
    return SimpleNamespace(
        prefix=SimpleNamespace(
            prefix_bin=network.network_address.packed,
            num_bits=network.prefixlen,
        ),
        best_group="best",
        paths={
            "best": [
                SimpleNamespace(
                    topologyInfo=topology,
                    communities=communities or [],
                    is_best_path=True,
                )
                for _ in range(path_count)
            ]
        },
    )


def _agent_route(
    *,
    client_count: int,
    forwarding_count: int,
    capacity: int | None = None,
    action: str = "Nexthops",
    topology_fields: dict[str, int] | None = None,
):
    network = ipaddress.ip_network(PREFIX)
    topology_values = dict(topology_fields or {})
    if capacity is not None:
        topology_values.update({"remote_rack_capacity": capacity, "spine_id": 1})
    topology = SimpleNamespace(**topology_values) if topology_values else None
    client_nexthops = [
        SimpleNamespace(topologyInfo=topology) for _ in range(client_count)
    ]
    return SimpleNamespace(
        dest=SimpleNamespace(
            ip=SimpleNamespace(addr=network.network_address.packed),
            prefixLength=network.prefixlen,
        ),
        nextHopMulti=[SimpleNamespace(nextHops=client_nexthops)],
        nextHops=[SimpleNamespace() for _ in range(forwarding_count)],
        action=action,
    )


class TestFpfGar(unittest.TestCase):
    def test_summarize_bgp_capacity(self) -> None:
        result = summarize_bgp_entries([_bgp_entry(36, 30)], {PREFIX})
        self.assertEqual(result[PREFIX].path_count, 36)
        self.assertEqual(result[PREFIX].capacities, {30})
        self.assertEqual(result[PREFIX].spine_ids, {1})

    def test_summarize_bgp_ignores_non_numeric_topology_values(self) -> None:
        result = summarize_bgp_entries(
            [
                _bgp_entry(
                    1,
                    topology_fields={
                        "remote_rack_capacity": "unknown",
                        "spine_id": "unknown",
                    },
                )
            ],
            {PREFIX},
        )
        self.assertEqual(result[PREFIX].capacities, set())
        self.assertEqual(result[PREFIX].spine_ids, set())

    def test_summarize_agent_pruning(self) -> None:
        result = summarize_agent_routes(
            [_agent_route(client_count=36, forwarding_count=30, capacity=30)],
            {PREFIX},
        )
        self.assertEqual(result[PREFIX].client_nexthop_count, 36)
        self.assertEqual(result[PREFIX].forwarding_nexthop_count, 30)
        self.assertEqual(result[PREFIX].capacities, {30})

    def test_evaluate_partial_capacity(self) -> None:
        source = GarDeviceSnapshot(
            bgp=summarize_bgp_entries([_bgp_entry(1)], {PREFIX}),
            agent=summarize_agent_routes(
                [
                    _agent_route(
                        client_count=0,
                        forwarding_count=0,
                        action="Drop",
                    )
                ],
                {PREFIX},
            ),
        )
        spine = GarDeviceSnapshot(
            bgp=summarize_bgp_entries([_bgp_entry(30)], {PREFIX}),
            agent=summarize_agent_routes(
                [_agent_route(client_count=30, forwarding_count=30)],
                {PREFIX},
            ),
        )
        observer = GarDeviceSnapshot(
            bgp=summarize_bgp_entries([_bgp_entry(36, 30)], {PREFIX}),
            agent=summarize_agent_routes(
                [_agent_route(client_count=36, forwarding_count=30, capacity=30)],
                {PREFIX},
            ),
        )
        issues, summary = evaluate_gar_pair(
            {
                "name": "pair-A",
                "source": "source",
                "spine": "spine",
                "observer": "observer",
                "expected_capacity": 30,
            },
            {"source": source, "spine": spine, "observer": observer},
            {PREFIX},
        )
        self.assertEqual(issues, [])
        self.assertIn("remote observer", summary)
        self.assertIn("best_paths={36: 1}", summary)
        self.assertIn("forwarding_nh={30: 1}", summary)
        self.assertIn("gar_capacity={'30': 1}", summary)

    def test_evaluate_vf_source_route(self) -> None:
        source = GarDeviceSnapshot(
            bgp=summarize_bgp_entries([_bgp_entry(1)], {PREFIX}),
            agent=summarize_agent_routes(
                [_agent_route(client_count=1, forwarding_count=1)],
                {PREFIX},
            ),
        )
        spine = GarDeviceSnapshot(
            bgp=summarize_bgp_entries([_bgp_entry(35)], {PREFIX}),
            agent=summarize_agent_routes(
                [_agent_route(client_count=35, forwarding_count=35)],
                {PREFIX},
            ),
        )
        observer = GarDeviceSnapshot(
            bgp=summarize_bgp_entries([_bgp_entry(36, 35)], {PREFIX}),
            agent=summarize_agent_routes(
                [_agent_route(client_count=36, forwarding_count=35, capacity=35)],
                {PREFIX},
            ),
        )
        issues, _summary = evaluate_gar_pair(
            {
                "name": "pair-A",
                "source": "source",
                "spine": "spine",
                "observer": "observer",
                "expected_capacity": 35,
                "source_route_mode": "vf",
            },
            {"source": source, "spine": spine, "observer": observer},
            {PREFIX},
        )
        self.assertEqual(issues, [])

    def test_evaluate_zero_capacity_requires_pruning(self) -> None:
        source = GarDeviceSnapshot(
            bgp=summarize_bgp_entries([_bgp_entry(1)], {PREFIX}),
            agent=summarize_agent_routes(
                [_agent_route(client_count=0, forwarding_count=0, action="Drop")],
                {PREFIX},
            ),
        )
        empty = GarDeviceSnapshot(bgp={}, agent={})
        issues, _summary = evaluate_gar_pair(
            {
                "name": "pair-A",
                "source": "source",
                "spine": "spine",
                "observer": "observer",
                "expected_capacity": 0,
            },
            {"source": source, "spine": empty, "observer": empty},
            {PREFIX},
        )
        self.assertEqual(issues, [])

    def test_zero_remote_capacity_can_keep_routes_on_drained_spine(self) -> None:
        source = GarDeviceSnapshot(
            bgp=summarize_bgp_entries([_bgp_entry(1)], {PREFIX}),
            agent=summarize_agent_routes(
                [_agent_route(client_count=0, forwarding_count=0, action="Drop")],
                {PREFIX},
            ),
        )
        spine = GarDeviceSnapshot(
            bgp=summarize_bgp_entries([_bgp_entry(36)], {PREFIX}),
            agent=summarize_agent_routes(
                [_agent_route(client_count=36, forwarding_count=36)],
                {PREFIX},
            ),
        )
        observer = GarDeviceSnapshot(bgp={}, agent={})

        issues, summary = evaluate_gar_pair(
            {
                "name": "drained-spine",
                "source": "source",
                "spine": "spine",
                "observer": "observer",
                "expected_capacity": 0,
                "expected_spine_capacity": 36,
            },
            {"source": source, "spine": spine, "observer": observer},
            {PREFIX},
        )

        self.assertEqual(issues, [])
        self.assertIn("expected spine capacity=36", summary)

    def test_device_drain_requires_topology_and_drain_community(self) -> None:
        source = GarDeviceSnapshot(
            bgp=summarize_bgp_entries([_bgp_entry(1)], {PREFIX}),
            agent=summarize_agent_routes(
                [_agent_route(client_count=1, forwarding_count=1)],
                {PREFIX},
            ),
        )
        spine_topology = {"rack_id": 1002}
        observer_topology = {
            "rack_id": 1002,
            "spine_id": 1,
            "remote_rack_capacity": 36,
        }
        spine = GarDeviceSnapshot(
            bgp=summarize_bgp_entries(
                [
                    _bgp_entry(
                        36,
                        topology_fields=spine_topology,
                        communities=["65446:10"],
                    )
                ],
                {PREFIX},
            ),
            agent=summarize_agent_routes(
                [
                    _agent_route(
                        client_count=36,
                        forwarding_count=36,
                        topology_fields=spine_topology,
                    )
                ],
                {PREFIX},
            ),
        )
        observer = GarDeviceSnapshot(
            bgp=summarize_bgp_entries(
                [
                    _bgp_entry(
                        36,
                        36,
                        topology_fields=observer_topology,
                        communities=["65446:10"],
                    )
                ],
                {PREFIX},
            ),
            agent=summarize_agent_routes(
                [
                    _agent_route(
                        client_count=36,
                        forwarding_count=36,
                        capacity=36,
                        topology_fields=observer_topology,
                    )
                ],
                {PREFIX},
            ),
        )
        issues, summary = evaluate_gar_pair(
            {
                "name": "device-drain",
                "source": "source",
                "spine": "spine",
                "observer": "observer",
                "expected_capacity": 36,
                "expected_spine_capacity": 36,
                "source_route_mode": "vf",
                "spine_required_bgp_topology_fields": ["rack_id"],
                "spine_required_agent_topology_fields": ["rack_id"],
                "observer_required_bgp_topology_fields": [
                    "rack_id",
                    "spine_id",
                    "remote_rack_capacity",
                ],
                "observer_required_agent_topology_fields": [
                    "rack_id",
                    "spine_id",
                    "remote_rack_capacity",
                ],
                "spine_required_communities": ["65446:10"],
                "observer_required_communities": ["65446:10"],
            },
            {"source": source, "spine": spine, "observer": observer},
            {PREFIX},
        )
        self.assertEqual(issues, [])
        self.assertIn("drain_community_paths=36/36", summary)

    def test_device_drain_fails_when_attribute_or_topology_is_missing(self) -> None:
        empty_topology = {}
        source = GarDeviceSnapshot(
            bgp=summarize_bgp_entries([_bgp_entry(1)], {PREFIX}),
            agent=summarize_agent_routes(
                [_agent_route(client_count=1, forwarding_count=1)],
                {PREFIX},
            ),
        )
        spine = GarDeviceSnapshot(
            bgp=summarize_bgp_entries(
                [_bgp_entry(36, topology_fields=empty_topology)], {PREFIX}
            ),
            agent=summarize_agent_routes(
                [_agent_route(client_count=36, forwarding_count=36)], {PREFIX}
            ),
        )
        observer = GarDeviceSnapshot(
            bgp=summarize_bgp_entries([_bgp_entry(36, 36)], {PREFIX}),
            agent=summarize_agent_routes(
                [_agent_route(client_count=36, forwarding_count=36, capacity=36)],
                {PREFIX},
            ),
        )
        issues, _summary = evaluate_gar_pair(
            {
                "name": "device-drain",
                "source": "source",
                "spine": "spine",
                "observer": "observer",
                "expected_capacity": 36,
                "expected_spine_capacity": 36,
                "source_route_mode": "vf",
                "spine_required_bgp_topology_fields": ["rack_id"],
                "spine_required_communities": ["65446:10"],
            },
            {"source": source, "spine": spine, "observer": observer},
            {PREFIX},
        )
        self.assertTrue(any("rack topology fields" in issue for issue in issues))
        self.assertTrue(any("required communities" in issue for issue in issues))

    def test_recovery_forbids_stale_drain_community(self) -> None:
        source = GarDeviceSnapshot(
            bgp=summarize_bgp_entries([_bgp_entry(1)], {PREFIX}),
            agent=summarize_agent_routes(
                [_agent_route(client_count=1, forwarding_count=1)],
                {PREFIX},
            ),
        )
        spine = GarDeviceSnapshot(
            bgp=summarize_bgp_entries(
                [_bgp_entry(36, communities=["65446:10"])], {PREFIX}
            ),
            agent=summarize_agent_routes(
                [_agent_route(client_count=36, forwarding_count=36)], {PREFIX}
            ),
        )
        observer = GarDeviceSnapshot(
            bgp=summarize_bgp_entries([_bgp_entry(36, 36)], {PREFIX}),
            agent=summarize_agent_routes(
                [_agent_route(client_count=36, forwarding_count=36, capacity=36)],
                {PREFIX},
            ),
        )
        issues, _summary = evaluate_gar_pair(
            {
                "name": "device-recovery",
                "source": "source",
                "spine": "spine",
                "observer": "observer",
                "expected_capacity": 36,
                "expected_spine_capacity": 36,
                "source_route_mode": "vf",
                "spine_forbidden_communities": ["65446:10"],
            },
            {"source": source, "spine": spine, "observer": observer},
            {PREFIX},
        )
        self.assertTrue(any("forbidden communities" in issue for issue in issues))

    def test_bgp_scope_does_not_require_agent_state(self) -> None:
        source = GarDeviceSnapshot(
            bgp=summarize_bgp_entries([_bgp_entry(1)], {PREFIX}),
            agent={},
        )
        spine = GarDeviceSnapshot(
            bgp=summarize_bgp_entries([_bgp_entry(36)], {PREFIX}),
            agent={},
        )
        observer = GarDeviceSnapshot(
            bgp=summarize_bgp_entries([_bgp_entry(36, 36)], {PREFIX}),
            agent={},
        )
        issues, _summary = evaluate_gar_pair(
            {
                "name": "pair-A",
                "source": "source",
                "spine": "spine",
                "observer": "observer",
                "expected_capacity": 36,
                "validation_scope": "bgp",
            },
            {"source": source, "spine": spine, "observer": observer},
            {PREFIX},
        )
        self.assertEqual(issues, [])

    def test_remote_scope_supports_asymmetric_observer_bundle(self) -> None:
        empty = GarDeviceSnapshot(bgp={}, agent={})
        observer = GarDeviceSnapshot(
            bgp=summarize_bgp_entries([_bgp_entry(34, 36)], {PREFIX}),
            agent=summarize_agent_routes(
                [_agent_route(client_count=34, forwarding_count=34, capacity=36)],
                {PREFIX},
            ),
        )
        issues, _summary = evaluate_gar_pair(
            {
                "name": "reverse-plane-3",
                "source": "source",
                "spine": "spine",
                "observer": "observer",
                "expected_capacity": 36,
                "observer_path_count": 34,
                "observer_forwarding_count": 34,
                "validation_scope": "remote_rib_fib",
            },
            {"source": empty, "spine": empty, "observer": observer},
            {PREFIX},
        )
        self.assertEqual(issues, [])


if __name__ == "__main__":
    unittest.main()
