# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-strict

"""Protect DICE churn contracts from acquiring concrete runtime dependencies."""

from __future__ import annotations

import ast
import inspect
import types
import unittest

from taac.abstractions.churn import (
    action,
    context,
    geometry,
    observations,
    policies,
    resolver,
    result,
    runner,
    selectors,
    specs,
    verification,
)


_CORE_MODULES: tuple[types.ModuleType, ...] = (
    action,
    context,
    geometry,
    observations,
    policies,
    resolver,
    result,
    runner,
    selectors,
    specs,
    verification,
)
_STDLIB_ALLOWED = {
    "__future__",
    "asyncio",
    "bisect",
    "dataclasses",
    "enum",
    "ipaddress",
    "time",
    "typing",
}


class ChurnCoreImportBoundaryTest(unittest.TestCase):
    def test_core_imports_only_stdlib_or_sibling_modules(self) -> None:
        violations: list[str] = []
        for module in _CORE_MODULES:
            tree = ast.parse(inspect.getsource(module), filename=module.__name__)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    roots = tuple(alias.name.partition(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    if node.level > 0:
                        continue
                    roots = ((node.module or "").partition(".")[0],)
                else:
                    continue
                violations.extend(
                    f"{module.__name__}:{node.lineno}:{root}"
                    for root in roots
                    if root not in _STDLIB_ALLOWED
                )
        self.assertEqual([], violations)

    def test_core_does_not_use_any_annotations(self) -> None:
        violations: list[str] = []
        for module in _CORE_MODULES:
            tree = ast.parse(inspect.getsource(module), filename=module.__name__)
            violations.extend(
                f"{module.__name__}:{node.lineno}"
                for node in ast.walk(tree)
                if isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id in {"t", "typing"}
                and node.attr == "Any"
            )
        self.assertEqual([], violations)
