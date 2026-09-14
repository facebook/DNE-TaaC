# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
import typing as t

from taac.constants import TestDevice
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
)
from taac.health_checks.healthcheck_definitions import (
    _is_same_device_name,
)
from taac.health_check.health_check import types as hc_types


# Reported in the run log, not gated on. The two classes fail differently -- an
# ``adj:`` database for a 64-spine fabric is ~51 KB and arrives as a
# multi-segment burst, so it is the class a control-plane policer drops, while
# ``prefix:`` databases are ~160 B and ride through as single packets -- so the
# split is worth logging even though the gate is now per-node.
DEFAULT_KEY_CLASSES: t.Dict[str, str] = {"adj": "adj:", "prefix": "prefix:"}

_OTHER = "other"
_TOTAL = "total"

_ADJ_KEY_PREFIX = "adj:"
_PREFIX_KEY_PREFIX = "prefix:"

# A wholesale miss would otherwise put one line per node in the result message.
_MAX_REPORTED_NODES = 20


def classify_kvstore_keys(
    keys_by_area: t.Mapping[str, t.Sequence[str]],
    key_classes: t.Mapping[str, str],
    area: t.Optional[str] = None,
) -> t.Dict[str, int]:
    """Count KvStore key names by key-class prefix.

    Args:
        keys_by_area: area -> key names, as returned by
            ``async_get_openr_kvstore_keys()``.
        key_classes: class label -> key-name prefix, e.g. ``{"adj": "adj:"}``.
            Prefixes are tested in the given order; the first match wins.
        area: restrict counting to this area. ``None`` aggregates every area.

    Returns:
        A dict with one entry per class label, plus ``other`` and ``total``.
    """
    counts: t.Dict[str, int] = dict.fromkeys(key_classes, 0)
    counts[_OTHER] = 0
    counts[_TOTAL] = 0
    for area_id, keys in keys_by_area.items():
        if area is not None and area_id != area:
            continue
        for key in keys:
            counts[_TOTAL] += 1
            for label, prefix in key_classes.items():
                if key.startswith(prefix):
                    counts[label] += 1
                    break
            else:
                counts[_OTHER] += 1
    return counts


def prefix_key_node(key: str) -> t.Optional[str]:
    """Return the originating node of a ``prefix:<node>:<area>:[<prefix>]`` key.

    ``None`` for anything that is not a well-formed prefix key, so a real
    device's unrelated keys cannot be attributed to a synthetic node.
    """
    if not key.startswith(_PREFIX_KEY_PREFIX):
        return None
    node, separator, _ = key[len(_PREFIX_KEY_PREFIX) :].partition(":")
    return node if separator else None


def audit_synthetic_nodes(
    keys_by_area: t.Mapping[str, t.Sequence[str]],
    expected_nodes: t.Sequence[str],
    area: t.Optional[str] = None,
) -> t.Tuple[t.List[str], t.Dict[str, int]]:
    """Audit the DUT's KvStore against the injected synthetic node names.

    Scoping to the expected node names is what makes this assertion immune to
    the DUT's own real keys: a lab box already holds thousands of genuine
    ``prefix:`` keys, so any total-based floor is satisfied by real traffic
    alone.

    Args:
        keys_by_area: area -> key names, as returned by
            ``async_get_openr_kvstore_keys()``.
        expected_nodes: synthetic node names the injector was told to build.
        area: restrict the audit to this area. ``None`` aggregates every area.

    Returns:
        ``(nodes with no adj: key, node -> count of its prefix: keys)``. Both
        are keyed only on ``expected_nodes``; surplus real keys are ignored.
    """
    present: t.Set[str] = set()
    prefix_counts: t.Dict[str, int] = dict.fromkeys(expected_nodes, 0)
    for area_id, keys in keys_by_area.items():
        if area is not None and area_id != area:
            continue
        for key in keys:
            present.add(key)
            node = prefix_key_node(key)
            if node in prefix_counts:
                prefix_counts[node] += 1
    missing_adj = [
        node for node in expected_nodes if f"{_ADJ_KEY_PREFIX}{node}" not in present
    ]
    return missing_adj, prefix_counts


class OpenrKvstoreKeysHealthCheck(
    AbstractDeviceHealthCheck[hc_types.BaseHealthCheckIn]
):
    """
    Asserts that a device's Open/R KvStore holds the specific keys an
    injected synthetic fabric should have put there.

    This is the pass/fail gate for Open/R scale injection. It asserts presence
    scoped to the injected node names rather than counting keys, for two
    reasons. Counts cannot distinguish injected keys from the DUT's own real
    ones -- a lab box already holds thousands of genuine ``prefix:`` keys, so
    any total-based floor passes on real traffic alone. And a count failure says
    "1,353 expected, 1,290 found", while a presence failure names the nodes that
    are absent.

    For every expected node the check asserts:

    * ``adj:<node>`` is present, and
    * exactly ``prefixes_per_node`` keys match ``prefix:<node>:``.

    Both expectations are supplied by the Open/R scale injection step, which
    derives the node list from the same topology flags it passes to the
    injector. A check with neither is a configuration error and FAILs -- a
    vacuous SKIP here is indistinguishable from a passing gate.

    check_params:
        expected_nodes (list[str]): synthetic node names that must be present,
            e.g. ``["spine-0", ..., "leaf-1", ..., "eb-site-0", ...]``.
        prefixes_per_node (int): exact number of ``prefix:`` keys each expected
            node must have, i.e. the injector's ``num_prefixes_per_node``.
        device_names (list[str]): restrict the check to these devices. Device
            health checks run across the whole topology, so a two-node scale
            rig needs this to keep the assertion on the DUT rather than also
            applying it to the helper. Default: run everywhere.
        area (str): restrict to one KvStore area. Default: aggregate all areas.
    """

    CHECK_NAME = hc_types.CheckName.OPENR_KVSTORE_KEYS_CHECK
    OPERATING_SYSTEMS = ["FBOSS", "EOS"]

    async def _run(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        device_names = check_params.get("device_names")
        # Tolerant comparison: an exact match would SKIP the DUT whenever the
        # configured name and obj.name differ only by FQDN suffix or case, and a
        # SKIP here is the vacuous pass this check exists to prevent.
        if device_names and not any(
            _is_same_device_name(obj.name, name) for name in device_names
        ):
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.SKIP,
                message=(
                    f"{obj.name}: KvStore key check is scoped to {sorted(device_names)}"
                ),
            )

        expected_nodes = [
            str(node) for node in check_params.get("expected_nodes") or []
        ]
        prefixes_per_node = check_params.get("prefixes_per_node")
        if not expected_nodes or prefixes_per_node is None:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=(
                    f"{obj.name}: KvStore key check has nothing to assert -- "
                    "expected_nodes and prefixes_per_node are both required "
                    "and are published by the Open/R scale injection step. A "
                    "check with no expectations is a configuration error, not "
                    f"a pass (got expected_nodes={len(expected_nodes)}, "
                    f"prefixes_per_node={prefixes_per_node!r})"
                ),
            )
        try:
            prefixes_per_node = int(prefixes_per_node)
        except (TypeError, ValueError):
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=(
                    f"{obj.name}: prefixes_per_node must be an integer, "
                    f"got {prefixes_per_node!r}"
                ),
            )
        area = check_params.get("area")

        keys_by_area = await self.driver.async_get_openr_kvstore_keys()
        missing_adj, prefix_counts = audit_synthetic_nodes(
            keys_by_area, expected_nodes, area
        )
        wrong_prefix_counts = {
            node: count
            for node, count in prefix_counts.items()
            if count != prefixes_per_node
        }

        summary = self._summary(keys_by_area, expected_nodes, area)
        if missing_adj or wrong_prefix_counts:
            failures = []
            if missing_adj:
                failures.append(
                    f"{len(missing_adj)} of {len(expected_nodes)} expected nodes "
                    f"have no adj: key ({self._abbreviate(missing_adj)})"
                )
            if wrong_prefix_counts:
                detail = self._abbreviate(
                    [
                        f"{node}={count}"
                        for node, count in sorted(wrong_prefix_counts.items())
                    ]
                )
                failures.append(
                    f"{len(wrong_prefix_counts)} of {len(expected_nodes)} expected "
                    f"nodes have the wrong prefix: key count, expected "
                    f"{prefixes_per_node} each ({detail})"
                )
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=(
                    f"{obj.name}: KvStore key check FAILED -- "
                    + "; ".join(failures)
                    + f". {summary}"
                ),
            )
        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
            message=(
                f"{obj.name}: KvStore holds adj: and {prefixes_per_node} prefix: "
                f"keys for all {len(expected_nodes)} expected nodes. {summary}"
            ),
        )

    @staticmethod
    def _abbreviate(items: t.Sequence[str]) -> str:
        shown = ", ".join(items[:_MAX_REPORTED_NODES])
        remaining = len(items) - _MAX_REPORTED_NODES
        return shown if remaining <= 0 else f"{shown}, and {remaining} more"

    @staticmethod
    def _summary(
        keys_by_area: t.Mapping[str, t.Sequence[str]],
        expected_nodes: t.Sequence[str],
        area: t.Optional[str],
    ) -> str:
        """Per-class totals, for the log only.

        Deliberately not gated on: these include the DUT's own real keys, which
        is exactly why a count-based gate could not work here.
        """
        counts = classify_kvstore_keys(keys_by_area, DEFAULT_KEY_CLASSES, area)
        scope = f"area {area}" if area is not None else "all areas"
        rendered = ", ".join(
            f"{label}={count}" for label, count in sorted(counts.items())
        )
        return (
            f"Whole-store counts including the DUT's own keys ({scope}): "
            f"{rendered}; {len(expected_nodes)} synthetic nodes expected"
        )
