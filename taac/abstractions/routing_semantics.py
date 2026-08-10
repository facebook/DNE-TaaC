# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

from enum import Enum


class NetworkRole(str, Enum):
    EB = "EB"


class PeerRelationship(str, Enum):
    EXTERNAL = "external"
    INTERNAL = "internal"
    MONITOR = "monitor"


__all__ = (
    "NetworkRole",
    "PeerRelationship",
)
