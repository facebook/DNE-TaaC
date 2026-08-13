# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ConfigArtifactProvider(str, Enum):
    CONFIGERATOR = "configerator"


@dataclass(frozen=True)
class ConfigArtifactRef:
    provider: ConfigArtifactProvider
    path: str

    def __post_init__(self) -> None:
        if not isinstance(self.provider, ConfigArtifactProvider):
            raise TypeError("config artifact provider must be typed")
        if not isinstance(self.path, str):
            raise TypeError("config artifact path must be a string")
        if not self.path:
            raise ValueError("config artifact path must be nonempty")


__all__ = (
    "ConfigArtifactProvider",
    "ConfigArtifactRef",
)
