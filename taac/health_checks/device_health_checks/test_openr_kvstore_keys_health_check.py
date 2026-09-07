# Copyright (c) Meta Platforms, Inc. and affiliates.

"""Unit tests for OpenrKvstoreKeysHealthCheck.

The topology throughout is the one the shipped test injects: a 64-spine/40-leaf
``bbf-simple`` fabric with ``dut_role=leaf``. ``leaf-0`` is replaced by the DUT
and removed from the generated topology, so 64 spines + 39 leaves + 20 eb-site
nodes = 123 synthetic nodes, each advertising 11 prefixes for 1,353 ``prefix:``
keys and 1,476 keys in total.
"""

import json
import unittest
from unittest.mock import AsyncMock, MagicMock

from taac.constants import TestDevice
from taac.health_checks.device_health_checks.openr_kvstore_keys_health_check import (
    audit_synthetic_nodes,
    classify_kvstore_keys,
    DEFAULT_KEY_CLASSES,
    OpenrKvstoreKeysHealthCheck,
    prefix_key_node,
)
from taac.health_checks.healthcheck_definitions import (
    create_openr_kvstore_keys_check,
)
from taac.utils.oss_taac_lib_utils import ConsoleFileLogger
from taac.health_check.health_check import types as hc_types


PREFIXES_PER_NODE = 11

# 64 spines + 39 leaves (leaf-0 is the DUT) + 20 eb-sites = 123 nodes.
EXPECTED_NODES: list = [
    *(f"spine-{index}" for index in range(64)),
    *(f"leaf-{index}" for index in range(1, 40)),
    *(f"eb-site-{index}" for index in range(20)),
]
EXPECTED_PREFIX_KEYS = len(EXPECTED_NODES) * PREFIXES_PER_NODE


def _injected_keys(
    nodes: list | None = None, prefixes_per_node: int = PREFIXES_PER_NODE
) -> list:
    """Build the key names a healthy injection of ``nodes`` produces."""
    nodes = EXPECTED_NODES if nodes is None else nodes
    keys = []
    for node in nodes:
        keys.append(f"adj:{node}")
        keys.extend(
            f"prefix:{node}:0:[fc00:{index}::/64]" for index in range(prefixes_per_node)
        )
    return keys


# The DUT's own pre-existing state. Scoping the assertion to the synthetic node
# names is what makes these irrelevant; a total-based floor would be satisfied
# by them alone.
_DUT_REAL_KEYS: list = [
    "adj:dut-test.example",
    *(f"prefix:dut-test.example:0:[2001:db8:{index}::/64]" for index in range(4092)),
]


class PrefixKeyNodeTest(unittest.TestCase):
    def test_node_is_extracted_from_a_well_formed_prefix_key(self):
        self.assertEqual("spine-17", prefix_key_node("prefix:spine-17:0:[fc00::/64]"))

    def test_non_prefix_key_yields_none(self):
        self.assertIsNone(prefix_key_node("adj:spine-17"))

    def test_prefix_key_without_a_node_separator_yields_none(self):
        """A malformed key must not be attributed to a node."""
        self.assertIsNone(prefix_key_node("prefix:spine-17"))


class AuditSyntheticNodesTest(unittest.TestCase):
    def test_healthy_injection_reports_nothing_missing(self):
        missing_adj, prefix_counts = audit_synthetic_nodes(
            {"0": _injected_keys()}, EXPECTED_NODES
        )
        self.assertEqual([], missing_adj)
        self.assertEqual({PREFIXES_PER_NODE}, set(prefix_counts.values()))

    def test_missing_adj_key_is_named(self):
        """The class a policed path drops: the large adj: databases."""
        keys = [key for key in _injected_keys() if key != "adj:spine-17"]
        missing_adj, _ = audit_synthetic_nodes({"0": keys}, EXPECTED_NODES)
        self.assertEqual(["spine-17"], missing_adj)

    def test_partial_prefix_population_is_counted_per_node(self):
        keys = [
            key for key in _injected_keys() if key != "prefix:eb-site-3:0:[fc00:0::/64]"
        ]
        _, prefix_counts = audit_synthetic_nodes({"0": keys}, EXPECTED_NODES)
        self.assertEqual(PREFIXES_PER_NODE - 1, prefix_counts["eb-site-3"])
        self.assertEqual(PREFIXES_PER_NODE, prefix_counts["eb-site-4"])

    def test_the_duts_own_keys_are_ignored(self):
        """Presence assertions must be blind to real state; this is the property
        that removed the need for a pre-injection baseline and a delta basis."""
        missing_adj, prefix_counts = audit_synthetic_nodes(
            {"0": [*_DUT_REAL_KEYS, *_injected_keys()]}, EXPECTED_NODES
        )
        self.assertEqual([], missing_adj)
        self.assertEqual({PREFIXES_PER_NODE}, set(prefix_counts.values()))

    def test_similar_node_names_are_not_conflated(self):
        """`leaf-1` and `leaf-11` share a name prefix; the trailing colon in
        `prefix:<node>:` is what keeps their key counts separate."""
        _, prefix_counts = audit_synthetic_nodes(
            {"0": _injected_keys(nodes=["leaf-1"])}, ["leaf-1", "leaf-11"]
        )
        self.assertEqual(PREFIXES_PER_NODE, prefix_counts["leaf-1"])
        self.assertEqual(0, prefix_counts["leaf-11"])

    def test_area_filter_restricts_the_audit(self):
        missing_adj, _ = audit_synthetic_nodes(
            {"0": _injected_keys(nodes=["spine-0"]), "1": []},
            ["spine-0"],
            area="1",
        )
        self.assertEqual(["spine-0"], missing_adj)

    def test_empty_kvstore_reports_every_node_missing(self):
        missing_adj, prefix_counts = audit_synthetic_nodes({"0": []}, EXPECTED_NODES)
        self.assertEqual(EXPECTED_NODES, missing_adj)
        self.assertEqual({0}, set(prefix_counts.values()))


class ClassifyKvstoreKeysTest(unittest.TestCase):
    def test_counts_adj_prefix_and_other_separately(self):
        counts = classify_kvstore_keys(
            {"0": ["adj:leaf-1", "prefix:leaf-1:0:[fc00::/64]", "fakekey:leaf-1"]},
            DEFAULT_KEY_CLASSES,
        )
        self.assertEqual({"adj": 1, "prefix": 1, "other": 1, "total": 3}, counts)

    def test_aggregates_across_areas_by_default(self):
        counts = classify_kvstore_keys(
            {"0": ["adj:leaf-1"], "1": ["adj:leaf-2", "prefix:leaf-2:0:[fc00::/64]"]},
            DEFAULT_KEY_CLASSES,
        )
        self.assertEqual({"adj": 2, "prefix": 1, "other": 0, "total": 3}, counts)

    def test_area_filter_restricts_to_one_area(self):
        counts = classify_kvstore_keys(
            {"0": ["adj:leaf-1"], "1": ["adj:leaf-2", "adj:leaf-3"]},
            DEFAULT_KEY_CLASSES,
            area="1",
        )
        self.assertEqual({"adj": 2, "prefix": 0, "other": 0, "total": 2}, counts)

    def test_empty_kvstore_counts_zero_rather_than_erroring(self):
        counts = classify_kvstore_keys({"0": []}, DEFAULT_KEY_CLASSES)
        self.assertEqual({"adj": 0, "prefix": 0, "other": 0, "total": 0}, counts)


class OpenrKvstoreKeysHealthCheckTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.logger = MagicMock(spec=ConsoleFileLogger)
        self.health_check = OpenrKvstoreKeysHealthCheck(logger=self.logger)
        self.health_check.driver = AsyncMock()
        self.device = MagicMock(spec=TestDevice)
        self.device.name = "dut-test.example"
        self.input = hc_types.BaseHealthCheckIn()

    def _set_keys(self, keys: list) -> None:
        self.health_check.driver.async_get_openr_kvstore_keys.return_value = {"0": keys}

    def _params(self, **overrides) -> dict:
        params = {
            "expected_nodes": EXPECTED_NODES,
            "prefixes_per_node": PREFIXES_PER_NODE,
        }
        params.update(overrides)
        return params

    async def test_complete_injection_returns_pass(self):
        self._set_keys([*_DUT_REAL_KEYS, *_injected_keys()])
        result = await self.health_check._run(self.device, self.input, self._params())
        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status)
        self.assertIn("all 123 expected nodes", result.message)

    async def test_missing_adj_keys_fail_and_are_named(self):
        """The failure this check exists for, and the reason it names nodes: a
        count would only have said 122 of 123."""
        keys = [key for key in _injected_keys() if key != "adj:spine-17"]
        self._set_keys(keys)
        result = await self.health_check._run(self.device, self.input, self._params())
        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("no adj: key", result.message)
        self.assertIn("spine-17", result.message)

    async def test_short_prefix_population_fails_naming_the_node_and_count(self):
        keys = [
            key for key in _injected_keys() if not key.startswith("prefix:eb-site-3:")
        ]
        self._set_keys(keys)
        result = await self.health_check._run(self.device, self.input, self._params())
        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("wrong prefix: key count", result.message)
        self.assertIn("eb-site-3=0", result.message)
        self.assertIn(f"expected {PREFIXES_PER_NODE} each", result.message)

    async def test_the_duts_real_keys_alone_do_not_satisfy_the_gate(self):
        """The concrete reason counting was abandoned: the lab DUT already holds
        ~4,092 real prefix: keys, which clears any total-based floor on its own.
        Presence scoped to the synthetic nodes must still FAIL here."""
        self._set_keys(_DUT_REAL_KEYS)
        result = await self.health_check._run(self.device, self.input, self._params())
        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("123 of 123 expected nodes have no adj: key", result.message)

    async def test_failure_report_is_capped(self):
        """A wholesale miss must produce a readable message, not 123 lines."""
        self._set_keys([])
        result = await self.health_check._run(self.device, self.input, self._params())
        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("and 103 more", result.message)

    async def test_surplus_prefix_keys_for_an_expected_node_fail(self):
        """An exact per-node count, not a floor: a node advertising more than it
        was built with means the expectation and the injector disagree."""
        self._set_keys([*_injected_keys(), "prefix:spine-0:0:[fc00:ff::/64]"])
        result = await self.health_check._run(self.device, self.input, self._params())
        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn(f"spine-0={PREFIXES_PER_NODE + 1}", result.message)

    async def test_no_expectations_fails_rather_than_skipping(self):
        """The bug this replaces: with nothing published the old check returned
        SKIP, so the gate was vacuous and no run could ever fail it."""
        result = await self.health_check._run(self.device, self.input, {})
        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("nothing to assert", result.message)
        self.health_check.driver.async_get_openr_kvstore_keys.assert_not_called()

    async def test_missing_prefixes_per_node_fails(self):
        result = await self.health_check._run(
            self.device, self.input, {"expected_nodes": EXPECTED_NODES}
        )
        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("prefixes_per_node", result.message)

    async def test_non_numeric_prefixes_per_node_fails(self):
        result = await self.health_check._run(
            self.device,
            self.input,
            self._params(prefixes_per_node="eleven"),
        )

        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("prefixes_per_node", result.message)
        self.assertIn("'eleven'", result.message)
        self.health_check.driver.async_get_openr_kvstore_keys.assert_not_called()

    async def test_device_outside_scope_is_skipped(self):
        """The helper also runs Open/R; the gate belongs on the DUT only."""
        self.device.name = "helper-test.example"
        result = await self.health_check._run(
            self.device, self.input, self._params(device_names=["dut-test.example"])
        )
        self.assertEqual(hc_types.HealthCheckStatus.SKIP, result.status)
        self.health_check.driver.async_get_openr_kvstore_keys.assert_not_called()

    async def test_device_inside_scope_is_asserted(self):
        self._set_keys(_injected_keys())
        result = await self.health_check._run(
            self.device, self.input, self._params(device_names=["dut-test.example"])
        )
        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status)

    async def test_scoping_tolerates_fqdn_and_case_differences(self):
        """Scoping must not fail open. An exact match would SKIP the DUT when the
        inventory and the device disagree only on FQDN suffix or case, turning the
        gate into the vacuous pass this check exists to prevent.
        """
        self._set_keys(_injected_keys())
        for configured in (
            "dut-test.example.facebook.com",
            "DUT-Test.example",
            "dut-test.example.",
        ):
            with self.subTest(configured=configured):
                result = await self.health_check._run(
                    self.device, self.input, self._params(device_names=[configured])
                )
                self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status)

    async def test_area_filter_scopes_the_assertion(self):
        self.health_check.driver.async_get_openr_kvstore_keys.return_value = {
            "0": [],
            "1": _injected_keys(nodes=["spine-0"]),
        }
        result = await self.health_check._run(
            self.device,
            self.input,
            {
                "expected_nodes": ["spine-0"],
                "prefixes_per_node": PREFIXES_PER_NODE,
                "area": "1",
            },
        )
        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status)
        self.assertIn("area 1", result.message)


class CreateOpenrKvstoreKeysCheckFactoryTest(unittest.TestCase):
    def test_static_expectations_serialize_into_json_params(self):
        check = create_openr_kvstore_keys_check(
            expected_nodes=["spine-0", "leaf-1"],
            prefixes_per_node=PREFIXES_PER_NODE,
            device_names=["dut-test.example"],
            retry_count=6,
        )
        self.assertEqual(hc_types.CheckName.OPENR_KVSTORE_KEYS_CHECK, check.name)
        self.assertEqual(
            {
                "expected_nodes": ["spine-0", "leaf-1"],
                "prefixes_per_node": PREFIXES_PER_NODE,
                "device_names": ["dut-test.example"],
                "retry_count": 6,
            },
            json.loads(check.check_params.json_params),
        )

    def test_jq_vars_become_jq_params(self):
        """The shipped wiring: both expectations come from the injection step,
        which derives them from the flags it passed to the injector."""
        check = create_openr_kvstore_keys_check(
            expected_nodes_jq_var="openr_scale_expected_nodes",
            prefixes_per_node_jq_var="openr_scale_prefixes_per_node",
        )
        self.assertEqual(
            {
                "expected_nodes": ".openr_scale_expected_nodes",
                "prefixes_per_node": ".openr_scale_prefixes_per_node",
            },
            dict(check.check_params.jq_params),
        )

    def test_static_expectation_overrides_the_jq_source(self):
        """The gate-verification lever: pin an expectation the run cannot meet
        without rewiring the injection step."""
        check = create_openr_kvstore_keys_check(
            expected_nodes=["spine-999"],
            expected_nodes_jq_var="openr_scale_expected_nodes",
            prefixes_per_node_jq_var="openr_scale_prefixes_per_node",
        )
        self.assertEqual(
            ["spine-999"], json.loads(check.check_params.json_params)["expected_nodes"]
        )
        self.assertNotIn("expected_nodes", dict(check.check_params.jq_params))
        self.assertEqual(
            ".openr_scale_prefixes_per_node",
            dict(check.check_params.jq_params)["prefixes_per_node"],
        )

    def test_no_arguments_produces_no_check_params(self):
        check = create_openr_kvstore_keys_check()
        self.assertIsNone(check.check_params)
