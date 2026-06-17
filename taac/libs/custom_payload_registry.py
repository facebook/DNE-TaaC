# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe

"""Module-global registry mapping traffic item names to custom IxNetwork frame
payload byte patterns (hex string).

Lets a test config inject a structurally valid protocol body (e.g. a 28-byte
ARP request) into the trailing bytes of a RAW traffic item without extending
the TAAC Thrift schema. After the IxNetwork traffic item is created, the
wrapper calls `FramePayload.update(Type="custom", CustomPattern=<hex>)` for
any registered name, overriding the default `incrementByte` pattern.

Today the only consumer is the CPU-queue test config for the 3 ARP traffic
items. If usage grows, promote this to a `frame_payload_custom_hex` field on
`BasicTrafficItemConfig` in `configerator/source/neteng/taac/test_as_a_config.thrift`.
"""

import typing as t


_CUSTOM_FRAME_PAYLOADS: t.Dict[str, str] = {}


def register_custom_frame_payload(traffic_item_name: str, hex_pattern: str) -> None:
    """Register a custom IxNetwork FramePayload pattern keyed by traffic item name.

    Args:
        traffic_item_name: The `name` field of the BasicTrafficItemConfig.
        hex_pattern: Hex byte string (e.g. "0001080006040001...") to use as the
            IxNetwork CustomPattern. Bytes are placed at the start of the frame
            payload; IxNetwork pads the remaining bytes with zeros.
    """
    _CUSTOM_FRAME_PAYLOADS[traffic_item_name] = hex_pattern


def get_custom_frame_payload(traffic_item_name: str) -> t.Optional[str]:
    """Return the registered custom hex pattern for this traffic item, or None."""
    return _CUSTOM_FRAME_PAYLOADS.get(traffic_item_name)
