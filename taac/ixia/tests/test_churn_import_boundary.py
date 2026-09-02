# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-strict

"""Keep reusable IXIA churn operations independent of TAAC orchestration."""

from __future__ import annotations

import ast
import inspect
import types
import unittest

from taac.ixia.churn import (
    attribute_operations,
    attribute_runtime,
    attribute_state,
    attribute_targets,
)


_MODULES: tuple[types.ModuleType, ...] = (
    attribute_operations,
    attribute_runtime,
    attribute_state,
    attribute_targets,
)
_FORBIDDEN_PREFIXES = (
    "neteng.test_infra.dne.taac.internal",
    "neteng.test_infra.dne.taac.abstractions.churn",
)


class IxiaChurnImportBoundaryTest(unittest.TestCase):
    def test_ixia_churn_does_not_import_scenario_or_internal_layers(self) -> None:
        violations: list[str] = []
        for module in _MODULES:
            tree = ast.parse(inspect.getsource(module), filename=module.__name__)
            for node in ast.walk(tree):
                imported: tuple[str, ...]
                if isinstance(node, ast.Import):
                    imported = tuple(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    imported = (node.module or "",)
                else:
                    continue
                violations.extend(
                    f"{module.__name__}:{node.lineno}:{name}"
                    for name in imported
                    if name.startswith(_FORBIDDEN_PREFIXES)
                )
        self.assertEqual([], violations)
