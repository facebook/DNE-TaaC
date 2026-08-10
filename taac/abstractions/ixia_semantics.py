# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

from enum import Enum


class IxiaBgpCapability(str, Enum):
    IPV4_UNICAST = "ipv4_unicast"
    IPV6_UNICAST = "ipv6_unicast"
    IPV4_UNICAST_ADD_PATH = "ipv4_unicast_add_path"
    IPV6_UNICAST_ADD_PATH = "ipv6_unicast_add_path"
    NEXT_HOP_ENCODING = "next_hop_encoding"


__all__ = ("IxiaBgpCapability",)
