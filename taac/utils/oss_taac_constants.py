# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""
OSS-compatible constants for TAAC framework.

Part of the TAAC OSS initiative to enable the framework to run in open-source
environments without Meta-internal dependencies.

These exception classes were originally in neteng.netcastle.teams.dne_regression.constants
but are migrated here to decouple TAAC from Meta-internal paths.
"""

import os

# Environment variable to control OSS mode
TAAC_OSS = os.environ.get("TAAC_OSS", "").lower() in ("1", "true", "yes")


class InsufficientInputError(Exception):
    """Raised when required inputs are missing or incomplete."""

    pass


class EmptyOutputError(Exception):
    """Raised when an expected output is empty or missing."""

    pass


class IxiaTestSetupError(Exception):
    """Raised when Ixia test setup fails."""

    pass
