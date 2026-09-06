# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-strict

"""Deadline primitives shared by churn abstractions and TAAC adapters."""

from __future__ import annotations

import dataclasses
import time


class DeadlineExceeded(TimeoutError):
    pass


@dataclasses.dataclass(frozen=True)
class Deadline:
    phase: str
    expires_at_monotonic: float

    def remaining(self, maximum_seconds: float) -> float:
        remaining_seconds = self.expires_at_monotonic - time.monotonic()
        if remaining_seconds <= 0:
            raise DeadlineExceeded(f"{self.phase}: no deadline budget remains")
        return min(maximum_seconds, remaining_seconds)

    def ensure_remaining(self, maximum_seconds: float) -> None:
        self.remaining(maximum_seconds)
