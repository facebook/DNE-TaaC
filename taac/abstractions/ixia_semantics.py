# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

from enum import Enum


# Maximum value represented by the unscaled 16-bit TCP window field.
_MAX_TCP_WINDOW_SIZE_BYTES = (1 << 16) - 1


def validate_ixia_bgp_tcp_window_size_bytes(value: object) -> None:
    """Validate the TCP receive-window value for an IXIA BGP session.

    DICE accepts one-byte windows for deliberate extreme-backpressure tests.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("IXIA BGP TCP window size must be an integer")
    if value <= 0:
        raise ValueError("IXIA BGP TCP window size must be positive")
    if value > _MAX_TCP_WINDOW_SIZE_BYTES:
        raise ValueError(
            "IXIA BGP TCP window size must not exceed "
            f"{_MAX_TCP_WINDOW_SIZE_BYTES} bytes"
        )


class IxiaBgpCapability(str, Enum):
    IPV4_UNICAST = "ipv4_unicast"
    IPV6_UNICAST = "ipv6_unicast"
    IPV4_UNICAST_ADD_PATH = "ipv4_unicast_add_path"
    IPV6_UNICAST_ADD_PATH = "ipv6_unicast_add_path"
    NEXT_HOP_ENCODING = "next_hop_encoding"


class IxiaEndpointPortLabelStyle(str, Enum):
    DUT_INTERFACE = "dut_interface"
    CHASSIS_PORT = "chassis_port"


__all__ = (
    "IxiaBgpCapability",
    "IxiaEndpointPortLabelStyle",
    "validate_ixia_bgp_tcp_window_size_bytes",
)
