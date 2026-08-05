# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

from __future__ import annotations

from dataclasses import dataclass


AddressOffset = int | str


@dataclass(frozen=True)
class AddressPlan:
    """Logical peer address layout before physical inventory binding."""

    afi: str = "v6"
    a_ips: tuple[str, ...] = ()
    z_ips: tuple[str, ...] = ()
    parent_network_key: str | None = None
    parent_network: str | None = None
    a_offset: AddressOffset | None = None
    z_offset: AddressOffset | None = None
    stride: AddressOffset = 2
    increment: AddressOffset | None = None
    mask: str | None = None
    prefix_length: int | None = None
    start_index: int = 0
    auto_allocate: bool = False
