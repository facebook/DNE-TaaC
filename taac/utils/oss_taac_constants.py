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
import typing as t

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


class IxiaCandidateSetupError(IxiaTestSetupError):
    """Base error for a failed IXIA candidate setup."""

    pass


class IxiaChassisUnavailableError(IxiaCandidateSetupError):
    """Raised when an IXIA chassis or API server cannot be reached."""

    pass


class IxiaSessionUnavailableError(IxiaCandidateSetupError):
    """Raised when an IXIA session cannot be created after recovery."""

    pass


class IxiaPortUnavailableError(IxiaCandidateSetupError):
    """Raised when IXIA physical ports cannot be assigned."""

    pass


class IxiaFallbackExhaustedError(IxiaTestSetupError):
    """Raised after every configured IXIA candidate fails setup."""

    def __init__(self, failures: t.Sequence[t.Tuple[str, BaseException]]) -> None:
        self.failures = tuple(failures)
        details = "; ".join(
            f"{name}: {type(error).__name__}: {error}" for name, error in failures
        )
        super().__init__(f"All IXIA setup candidates failed: {details}")
