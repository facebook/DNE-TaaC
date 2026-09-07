# pyre-unsafe
"""Pytest collection configuration for OSS-compatible unit tests.

Many test files under taac/ depend on internal (non-OSS) modules such as
``neteng.*``, ``taac.internal``, or ``taac.health_check``.  These cannot
be collected in the open-source Docker image and are excluded below so
that ``python3 -m pytest`` exits cleanly.

When a test file is ported to work without internal dependencies, remove
its entry (or its parent directory) from the appropriate list.
"""

import importlib
import os

# Pytest's importlib mode may materialize the source-side ``taac`` namespace
# before collection and omit namespace contributors from the generated thrift
# install tree.  Preload the two generated roots while the full namespace path
# is still intact so OSS tests can import their ``types``/``thrift_types``
# children normally.  A source-only checkout can still collect the tests that
# do not require generated bindings.
for _generated_root in ("taac.health_check", "taac.test_as_a_config"):
    try:
        importlib.import_module(_generated_root)
    except ModuleNotFoundError as exc:
        # A source-only checkout legitimately lacks the generated root. Do not
        # hide a missing transitive import inside a root that was found.
        if exc.name != _generated_root:
            raise

# ---------------------------------------------------------------------------
# Directories where *every* test depends on non-OSS modules.
# ---------------------------------------------------------------------------
_NON_OSS_TEST_DIRS = [
    "taac/health_checks",
    "taac/ixia/tests",
    "taac/libs/fpf/tests",
    "taac/steps/tests",
    "taac/tasks",
]

# ---------------------------------------------------------------------------
# Individual files that are either non-OSS tests or non-test modules
# (production code whose ``test_`` prefix causes pytest to pick them up).
# ---------------------------------------------------------------------------
_NON_OSS_TEST_FILES = [
    # Non-test modules (production code with test_ prefix)
    "taac/test_configs.py",
    "taac/libs/test_setup_orchestrator.py",
    "taac/utils/test_config_utils.py",
]

# Build absolute paths relative to this conftest's directory (repo root).
_HERE = os.path.dirname(__file__)

collect_ignore = [os.path.join(_HERE, f) for f in _NON_OSS_TEST_FILES]
collect_ignore_glob = [os.path.join(_HERE, d, "**") for d in _NON_OSS_TEST_DIRS]
