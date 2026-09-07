# pyre-unsafe
"""Hand-built BGP UPDATE messages for protocol-hardening tests.

The declarative route-range model can only describe *conformant* BGP, so testing
malformed-input handling needs exact bytes on the wire — what
``ixia.BgpUpdateSequence`` provides.  This module builds them, each malformation
labelled with the RFC rule it breaks and the required receiver behaviour, so a
failure reads against the spec rather than a hex blob.

Wire format (RFC 4271 section 4.1, 4.3)::

    +-----------------+  16 bytes, all ones
    | Marker          |
    +-----------------+  2 bytes, total message length including header
    | Length          |
    +-----------------+  1 byte, 2 = UPDATE
    | Type            |
    +-----------------+  2 bytes
    | Withdrawn len   |
    +-----------------+
    | Withdrawn routes|
    +-----------------+  2 bytes
    | Path attr len   |
    +-----------------+
    | Path attributes |
    +-----------------+  remainder of message
    | NLRI            |
    +-----------------+

Length fields are computed, never hand-written — an accidental stale length is
itself a malformation and would silently change what a test exercises.  Where one
is deliberately wrong, it says so (:func:`bad_attribute_length_update`).
"""

import typing as t

BGP_MARKER = b"\xff" * 16
BGP_UPDATE_TYPE = 2
BGP_HEADER_LEN = 19  # marker + length + type

# Path attribute flags (RFC 4271 section 4.3)
FLAG_OPTIONAL = 0x80
FLAG_TRANSITIVE = 0x40
FLAG_PARTIAL = 0x20
FLAG_EXTENDED_LEN = 0x10

# Well-known attribute type codes
ATTR_ORIGIN = 1
ATTR_AS_PATH = 2
ATTR_NEXT_HOP = 3
ATTR_MULTI_EXIT_DISC = 4

# ORIGIN values (RFC 4271 section 5.1.1) — 0..2 are the only valid ones
ORIGIN_IGP = 0
ORIGIN_EGP = 1
ORIGIN_INCOMPLETE = 2

# AS_PATH segment types (RFC 4271 section 5.1.2)
AS_SET = 1
AS_SEQUENCE = 2


def _attribute(attr_type: int, value: bytes, flags: int = FLAG_TRANSITIVE) -> bytes:
    """Encode one path attribute with a correct length octet."""
    if len(value) > 0xFF:
        raise ValueError(
            f"attribute {attr_type} value is {len(value)} bytes; use the "
            f"extended-length form"
        )
    return bytes([flags, attr_type, len(value)]) + value


def _origin(value: int = ORIGIN_IGP) -> bytes:
    return _attribute(ATTR_ORIGIN, bytes([value]))


AS_OCTETS = 4
"""ASN width on the wire.

The speaker declares ``enable_4_byte_local_as`` and snappi's ``as_number_width``
defaults to ``'four'``, so AS4 (RFC 6793) is negotiated and the receiver parses
AS_PATH as 4-octet ASNs.  Encoding 2 octets would make *every* segment here
malformed — the count octet promises N*4 bytes and only N*2 arrive — so the
receiver would reject on AS_PATH before reaching the defect each update exists to
isolate, and the well-formed control would not be a control.
"""


def _as_path(as_numbers: t.Optional[t.Sequence[int]] = None) -> bytes:
    """AS_PATH holding a single AS_SEQUENCE, or empty (valid for iBGP)."""
    if not as_numbers:
        return _attribute(ATTR_AS_PATH, b"")
    body = bytes([AS_SEQUENCE, len(as_numbers)])
    for asn in as_numbers:
        if not 0 <= asn <= 0xFFFFFFFF:
            raise ValueError(f"AS_PATH cannot hold ASN {asn}")
        body += asn.to_bytes(AS_OCTETS, "big")
    return _attribute(ATTR_AS_PATH, body)


def _next_hop(address: str) -> bytes:
    octets = [int(o) for o in address.split(".")]
    if len(octets) != 4 or any(not 0 <= o <= 255 for o in octets):
        raise ValueError(f"not an IPv4 address: {address!r}")
    return _attribute(ATTR_NEXT_HOP, bytes(octets))


def _nlri(prefix: str, prefix_len: int) -> bytes:
    """Encode one NLRI entry: length octet plus the minimum whole octets."""
    if not 0 <= prefix_len <= 32:
        raise ValueError(f"IPv4 prefix length out of range: {prefix_len}")
    octets = [int(o) for o in prefix.split(".")]
    if len(octets) != 4:
        raise ValueError(f"not an IPv4 address: {prefix!r}")
    significant = (prefix_len + 7) // 8
    return bytes([prefix_len]) + bytes(octets[:significant])


def build_update(
    path_attributes: bytes = b"",
    nlri: bytes = b"",
    withdrawn_routes: bytes = b"",
    override_path_attr_len: t.Optional[int] = None,
) -> str:
    """Assemble a BGP UPDATE and return it as a lowercase hex string.

    Args:
        path_attributes: Concatenated encoded path attributes.
        nlri: Concatenated encoded NLRI entries.
        withdrawn_routes: Concatenated encoded withdrawn-route entries.
        override_path_attr_len: Write this value as the path-attribute length
            instead of the true one.  Only for tests that deliberately need an
            inconsistent length; leave unset otherwise.

    Returns:
        Hex string suitable for ``BgpUpdateSequenceEntry.update_bytes``.
    """
    attr_len = (
        len(path_attributes)
        if override_path_attr_len is None
        else override_path_attr_len
    )
    body = (
        len(withdrawn_routes).to_bytes(2, "big")
        + withdrawn_routes
        + attr_len.to_bytes(2, "big")
        + path_attributes
        + nlri
    )
    total_len = BGP_HEADER_LEN + len(body)
    message = (
        BGP_MARKER + total_len.to_bytes(2, "big") + bytes([BGP_UPDATE_TYPE]) + body
    )
    return message.hex()


# ---------------------------------------------------------------------------
# Conformant baseline
# ---------------------------------------------------------------------------


def well_formed_update(
    prefix: str = "198.51.100.0",
    prefix_len: int = 24,
    next_hop: str = "10.0.1.1",
    as_numbers: t.Sequence[int] = (65001,),
) -> str:
    """A fully conformant UPDATE, as a control.

    If a test fails on this one too, the problem is the harness or the session,
    not the DUT's malformed-input handling.
    """
    return build_update(
        path_attributes=_origin() + _as_path(as_numbers) + _next_hop(next_hop),
        nlri=_nlri(prefix, prefix_len),
    )


# ---------------------------------------------------------------------------
# Malformations, each keyed to the rule it breaks
# ---------------------------------------------------------------------------


def missing_next_hop_update(
    prefix: str = "198.51.100.0",
    prefix_len: int = 25,
    as_numbers: t.Sequence[int] = (65001,),
) -> str:
    """Omit NEXT_HOP, a well-known mandatory attribute.

    Breaks RFC 4271 section 5 — NEXT_HOP is well-known mandatory in any UPDATE
    carrying NLRI.  Expected: RFC 7606 section 3 treat-as-withdraw (a missing well-known
    mandatory attribute; section 7.3 covers a NEXT_HOP that is present but
    malformed), and the
    receiver must NOT reset the session (4271 alone required a NOTIFICATION; 7606
    softened it).  The OTG equivalent of upstream's
    ``bounce_bgp_next_hop_attribute(enable=False)``.
    """
    return build_update(
        path_attributes=_origin() + _as_path(as_numbers),
        nlri=_nlri(prefix, prefix_len),
    )


def malformed_as_path_update(
    prefix: str = "198.51.100.128",
    prefix_len: int = 25,
    next_hop: str = "10.0.1.1",
) -> str:
    """AS_PATH whose segment claims more ASNs than the segment contains.

    Breaks RFC 4271 section 5.1.2 — segment length must match the ASNs present.
    Expected: RFC 7606 section 7.2 treat-as-withdraw.
    """
    # Segment header says 4 ASNs, i.e. 4 * AS_OCTETS bytes; one ASN follows.
    truncated_segment = bytes([AS_SEQUENCE, 4]) + (65001).to_bytes(AS_OCTETS, "big")
    return build_update(
        path_attributes=(
            _origin()
            + _attribute(ATTR_AS_PATH, truncated_segment)
            + _next_hop(next_hop)
        ),
        nlri=_nlri(prefix, prefix_len),
    )


def bad_attribute_length_update(
    prefix: str = "198.51.100.0",
    prefix_len: int = 26,
    next_hop: str = "10.0.1.1",
) -> str:
    """Path-attribute length field that overruns the attribute block.

    Breaks RFC 4271 section 4.3 — the total path-attribute length must match the
    attributes present.  Expected: RFC 7606 section 3 — an unlocalisable length
    error makes the UPDATE malformed; session handling is implementation-defined
    but bgpd must not crash.
    """
    attributes = _origin() + _as_path((65001,)) + _next_hop(next_hop)
    return build_update(
        path_attributes=attributes,
        nlri=_nlri(prefix, prefix_len),
        # Claim 20 bytes more than are present, running the parser off the end
        # of the attribute block and into the NLRI.
        override_path_attr_len=len(attributes) + 20,
    )


def invalid_origin_update(
    prefix: str = "198.51.100.64",
    prefix_len: int = 26,
    next_hop: str = "10.0.1.1",
    origin_value: int = 7,
) -> str:
    """ORIGIN carrying a value outside the defined range.

    Breaks RFC 4271 section 5.1.1 — ORIGIN is defined only for 0, 1, 2.
    Expected: RFC 7606 section 7.1 treat-as-withdraw.
    """
    return build_update(
        path_attributes=(
            _attribute(ATTR_ORIGIN, bytes([origin_value]))
            + _as_path((65001,))
            + _next_hop(next_hop)
        ),
        nlri=_nlri(prefix, prefix_len),
    )


# Conformant UPDATEs bracket the suite: the first proves the session is good
# before anything malformed, the last that the peer can still advertise after.
#
# Each entry advertises a DISTINCT prefix so a RIB effect is attributable to one
# malformation.  NLRI encodes only a prefix's significant octets, so
# 198.51.100.0/24 and .1/24 are the SAME NLRI — distinctness comes from differing
# prefix LENGTHS within 198.51.100.0/24 (RFC 5737 TEST-NET-2), not host octets.
def rfc7606_malformation_suite(next_hop: str = "10.0.1.1") -> t.List[str]:
    """Malformed UPDATEs covering the error-handling paths of RFC 7606.

    Order is load-bearing.  A malformation the receiver answers with a
    NOTIFICATION tears the session down partway through the replay, so every
    entry after it is never sent — and because OTG restarts the sequence from the
    top on each re-establishment, those entries are never evaluated at all, on any
    cycle.  So everything the receiver is expected to survive goes first, and the
    one update it is expected to reset on goes last.

    Bracketed by conformant updates: the first proves the session accepts good
    input before anything bad arrives, the last non-resetting one proves it still
    does after the treat-as-withdraw cases.
    """
    # Expected to be survivable — RFC 7606 treat-as-withdraw, session stays up.
    non_resetting = [
        well_formed_update(next_hop=next_hop),
        missing_next_hop_update(),
        malformed_as_path_update(next_hop=next_hop),
        invalid_origin_update(next_hop=next_hop),
        well_formed_update(
            prefix="198.51.100.192", prefix_len=26, next_hop=next_hop
        ),
    ]
    # Expected to end the session — RFC 7606 section 3, an unlocalisable length
    # error cannot be scoped to one route, so the receiver resets.  Anything
    # appended after this would be dead weight.
    resetting = [
        bad_attribute_length_update(next_hop=next_hop),
    ]
    return non_resetting + resetting
