# pyre-unsafe
"""Unit tests for the hand-built BGP UPDATE messages in
``taac/otg/otg_bgp_malformed_updates.py``.

These are pure bytes — no mocks, no thrift, no snappi.  Each test decodes the
generated message with an independent parser written here rather than reusing
the builder's own helpers, so a bug in the builder cannot hide behind a
symmetric bug in the assertion.

The point of these tests is that a malformation must be *exactly* the one
claimed.  An UPDATE that is accidentally malformed in a second way, or
accidentally well-formed, silently changes which DUT code path the hardening
test exercises.
"""

import unittest

from taac.otg import otg_bgp_malformed_updates as mu


# -- an independent decoder ---------------------------------------------------


AS_OCTETS = 4
"""ASN width on the wire for this speaker.

The peer declares `enable_4_byte_local_as=True` and snappi's `as_number_width`
defaults to 'four', so AS4 is negotiated and the receiver parses AS_PATH as
4-octet ASNs.  Encoding 2-octet ASNs makes every segment malformed: the count
octet promises N*4 bytes and only N*2 arrive.
"""


def decode(hex_update):
    """Parse a BGP UPDATE hex string into its parts, without trusting lengths."""
    raw = bytes.fromhex(hex_update)
    out = {
        "raw": raw,
        "marker": raw[:16],
        "declared_total_len": int.from_bytes(raw[16:18], "big"),
        "actual_total_len": len(raw),
        "type": raw[18],
    }
    withdrawn_len = int.from_bytes(raw[19:21], "big")
    offset = 21 + withdrawn_len
    out["withdrawn_len"] = withdrawn_len
    out["declared_attr_len"] = int.from_bytes(raw[offset : offset + 2], "big")
    offset += 2
    out["attr_offset"] = offset
    out["bytes_after_attr_len"] = len(raw) - offset
    return out


def decode_attributes(hex_update):
    """Walk the path-attribute block, honoring the DECLARED length.

    Returns (attributes, overran) where overran is True if the declared length
    reaches past the end of the message.
    """
    d = decode(hex_update)
    raw, offset = d["raw"], d["attr_offset"]
    end = offset + d["declared_attr_len"]
    overran = end > len(raw)
    attributes = {}
    i = offset
    limit = min(end, len(raw))
    while i + 3 <= limit:
        flags, attr_type, attr_len = raw[i], raw[i + 1], raw[i + 2]
        attributes[attr_type] = {
            "flags": flags,
            "declared_len": attr_len,
            "value": raw[i + 3 : i + 3 + attr_len],
        }
        i += 3 + attr_len
    return attributes, overran


def nlri_of(hex_update):
    d = decode(hex_update)
    return d["raw"][d["attr_offset"] + d["declared_attr_len"] :]


# -- header framing, common to every message ----------------------------------


class UpdateFramingTest(unittest.TestCase):
    """Every message, malformed or not, must be a syntactically locatable
    UPDATE — otherwise the DUT rejects it at the header and the specific
    malformation under test is never reached."""

    def all_updates(self):
        return {
            "well_formed": mu.well_formed_update(),
            "missing_next_hop": mu.missing_next_hop_update(),
            "malformed_as_path": mu.malformed_as_path_update(),
            "bad_attribute_length": mu.bad_attribute_length_update(),
            "invalid_origin": mu.invalid_origin_update(),
        }

    def test_marker_is_all_ones(self):
        for name, u in self.all_updates().items():
            self.assertEqual(decode(u)["marker"], b"\xff" * 16, name)

    def test_declared_length_matches_actual(self):
        """The header length is computed, so it must always be right — even for
        the message whose *attribute* length is deliberately wrong."""
        for name, u in self.all_updates().items():
            d = decode(u)
            self.assertEqual(d["declared_total_len"], d["actual_total_len"], name)

    def test_message_type_is_update(self):
        for name, u in self.all_updates().items():
            self.assertEqual(decode(u)["type"], 2, name)

    def test_all_are_lowercase_hex(self):
        for name, u in self.all_updates().items():
            self.assertTrue(all(c in "0123456789abcdef" for c in u), name)

    def test_all_fit_snappi_update_bytes_limit(self):
        """snappi caps update_bytes at 8154 hex chars."""
        for name, u in self.all_updates().items():
            self.assertLessEqual(len(u), 8154, name)

    def test_no_withdrawn_routes_by_default(self):
        for name, u in self.all_updates().items():
            self.assertEqual(decode(u)["withdrawn_len"], 0, name)


# -- the conformant control ---------------------------------------------------


class WellFormedUpdateTest(unittest.TestCase):
    def test_carries_all_three_mandatory_attributes(self):
        attrs, overran = decode_attributes(mu.well_formed_update())
        self.assertFalse(overran)
        self.assertEqual(
            sorted(attrs), [mu.ATTR_ORIGIN, mu.ATTR_AS_PATH, mu.ATTR_NEXT_HOP]
        )

    def test_origin_is_valid(self):
        attrs, _ = decode_attributes(mu.well_formed_update())
        self.assertIn(attrs[mu.ATTR_ORIGIN]["value"][0], (0, 1, 2))

    def test_next_hop_round_trips(self):
        attrs, _ = decode_attributes(mu.well_formed_update(next_hop="192.0.2.7"))
        self.assertEqual(
            ".".join(str(b) for b in attrs[mu.ATTR_NEXT_HOP]["value"]), "192.0.2.7"
        )

    def test_as_path_segment_is_self_consistent(self):
        attrs, _ = decode_attributes(
            mu.well_formed_update(as_numbers=(65001, 65002, 65003))
        )
        seg = attrs[mu.ATTR_AS_PATH]["value"]
        self.assertEqual(seg[0], mu.AS_SEQUENCE)
        self.assertEqual(seg[1], 3, "declared ASN count")
        self.assertEqual(len(seg) - 2, 3 * AS_OCTETS, "actual ASN bytes")

    def test_nlri_encodes_only_significant_octets(self):
        """A /24 carries 3 octets, not 4 (RFC 4271 section 4.3)."""
        self.assertEqual(
            nlri_of(mu.well_formed_update(prefix="198.51.100.0", prefix_len=24)),
            bytes([24, 198, 51, 100]),
        )

    def test_nlri_for_shorter_prefix(self):
        self.assertEqual(
            nlri_of(mu.well_formed_update(prefix="10.0.0.0", prefix_len=8)),
            bytes([8, 10]),
        )


# -- each malformation is exactly the one claimed ------------------------------


class MissingNextHopTest(unittest.TestCase):
    """Breaks RFC 4271 section 5; expects RFC 7606 section 4 treat-as-withdraw."""

    def test_next_hop_absent(self):
        attrs, overran = decode_attributes(mu.missing_next_hop_update())
        self.assertNotIn(mu.ATTR_NEXT_HOP, attrs)
        self.assertFalse(overran)

    def test_other_mandatory_attributes_still_present(self):
        """Only NEXT_HOP may be missing — otherwise the DUT could reject on a
        different rule and the test would not prove what it claims."""
        attrs, _ = decode_attributes(mu.missing_next_hop_update())
        self.assertIn(mu.ATTR_ORIGIN, attrs)
        self.assertIn(mu.ATTR_AS_PATH, attrs)

    def test_still_carries_nlri(self):
        """NEXT_HOP is only mandatory when NLRI is present; without NLRI this
        would not be a violation at all."""
        self.assertTrue(len(nlri_of(mu.missing_next_hop_update())) > 0)

    def test_attribute_length_is_honest(self):
        d = decode(mu.missing_next_hop_update())
        attrs, _ = decode_attributes(mu.missing_next_hop_update())
        consumed = sum(3 + a["declared_len"] for a in attrs.values())
        self.assertEqual(d["declared_attr_len"], consumed)


class MalformedAsPathTest(unittest.TestCase):
    """Breaks RFC 4271 section 5.1.2; expects section 5.2 treat-as-withdraw."""

    def test_segment_claims_more_asns_than_present(self):
        attrs, _ = decode_attributes(mu.malformed_as_path_update())
        seg = attrs[mu.ATTR_AS_PATH]["value"]
        declared = seg[1]
        actual = (len(seg) - 2) // AS_OCTETS
        self.assertGreater(declared, actual, f"declared {declared}, actual {actual}")

    def test_outer_attribute_framing_stays_valid(self):
        """The defect is INSIDE AS_PATH.  If the outer framing were also broken
        the DUT would fail earlier and never parse the segment."""
        attrs, overran = decode_attributes(mu.malformed_as_path_update())
        self.assertFalse(overran)
        self.assertEqual(
            sorted(attrs), [mu.ATTR_ORIGIN, mu.ATTR_AS_PATH, mu.ATTR_NEXT_HOP]
        )


class BadAttributeLengthTest(unittest.TestCase):
    """Breaks RFC 4271 section 4.3 — declared length overruns the message."""

    def test_declared_attr_len_exceeds_available_bytes(self):
        d = decode(mu.bad_attribute_length_update())
        self.assertGreater(d["declared_attr_len"], d["bytes_after_attr_len"])

    def test_parser_overruns_the_message(self):
        _, overran = decode_attributes(mu.bad_attribute_length_update())
        self.assertTrue(overran)

    def test_header_length_remains_correct(self):
        """Only the attribute length is wrong.  A wrong header length too would
        make this a different (header-level) test."""
        d = decode(mu.bad_attribute_length_update())
        self.assertEqual(d["declared_total_len"], d["actual_total_len"])


class InvalidOriginTest(unittest.TestCase):
    """Breaks RFC 4271 section 5.1.1; expects section 5.1 treat-as-withdraw."""

    def test_origin_value_outside_defined_range(self):
        attrs, _ = decode_attributes(mu.invalid_origin_update())
        self.assertNotIn(attrs[mu.ATTR_ORIGIN]["value"][0], (0, 1, 2))

    def test_everything_else_is_well_formed(self):
        attrs, overran = decode_attributes(mu.invalid_origin_update())
        self.assertFalse(overran)
        self.assertIn(mu.ATTR_AS_PATH, attrs)
        self.assertIn(mu.ATTR_NEXT_HOP, attrs)
        self.assertEqual(attrs[mu.ATTR_ORIGIN]["declared_len"], 1)


# -- AS_PATH width, which decides whether any of the above is attributable ----


def as_path_segment(hex_update):
    """The AS_PATH segment's type, declared ASN count, and actual body length."""
    attrs, _ = decode_attributes(hex_update)
    seg = attrs[mu.ATTR_AS_PATH]["value"]
    return {"type": seg[0], "declared": seg[1], "body_len": len(seg) - 2}


class AsPathWidthTest(unittest.TestCase):
    """Only the intended malformation may be present in each update.

    If AS_PATH itself is malformed everywhere, bgpd hits that error first and the
    four malformations stop being individually attributable — and the well-formed
    control stops being a control.  Blast-radius assertions cannot detect this,
    so it is asserted here.
    """

    def test_as_path_encodes_four_octet_asns(self):
        seg = as_path_segment(mu.well_formed_update(as_numbers=(65001, 65002)))
        self.assertEqual(seg["declared"], 2)
        self.assertEqual(seg["body_len"], 2 * AS_OCTETS)

    def test_well_formed_control_has_a_conformant_as_path(self):
        seg = as_path_segment(mu.well_formed_update())
        self.assertEqual(
            seg["body_len"],
            seg["declared"] * AS_OCTETS,
            "the control update must not itself carry a malformed AS_PATH",
        )

    def test_other_malformations_carry_a_conformant_as_path(self):
        for name, update in (
            ("missing_next_hop", mu.missing_next_hop_update()),
            ("bad_attribute_length", mu.bad_attribute_length_update()),
            ("invalid_origin", mu.invalid_origin_update()),
        ):
            with self.subTest(malformation=name):
                seg = as_path_segment(update)
                self.assertEqual(
                    seg["body_len"],
                    seg["declared"] * AS_OCTETS,
                    f"{name} must break only its own rule",
                )

    def test_as_path_malformation_is_still_malformed_under_as4(self):
        seg = as_path_segment(mu.malformed_as_path_update())
        self.assertNotEqual(seg["body_len"], seg["declared"] * AS_OCTETS)


# -- the suite the playbook actually replays ----------------------------------


class MalformationSuiteTest(unittest.TestCase):
    def setUp(self):
        self.suite = mu.rfc7606_malformation_suite()

    def test_the_survivable_run_is_bracketed_by_conformant_updates(self):
        """Opening conformant proves the session accepts good input before
        anything bad arrives; a conformant update immediately before the
        session-resetting one proves it still does after the treat-as-withdraw
        cases. The final entry is deliberately NOT conformant — it is the reset.
        """
        reset_index = next(
            i for i, u in enumerate(self.suite) if decode_attributes(u)[1]
        )
        survivable = self.suite[:reset_index]
        for label, update in (
            ("first", survivable[0]),
            ("last before the reset", survivable[-1]),
        ):
            with self.subTest(position=label):
                attrs, _ = decode_attributes(update)
                self.assertEqual(
                    sorted(attrs),
                    [mu.ATTR_ORIGIN, mu.ATTR_AS_PATH, mu.ATTR_NEXT_HOP],
                )

    def test_the_session_resetting_update_is_last(self):
        """Ordering is load-bearing, not cosmetic.

        A malformation the receiver answers with a NOTIFICATION tears the session
        down mid-replay, so every entry after it is never sent — and OTG restarts
        the sequence from the top on each re-establishment, so those entries are
        never evaluated at all. The one update whose declared attribute length
        overruns the message is that case (RFC 7606 section 3, unlocalisable
        length), so it has to come last.
        """
        overrunning = [
            i for i, u in enumerate(self.suite) if decode_attributes(u)[1]
        ]
        self.assertEqual(
            overrunning,
            [len(self.suite) - 1],
            "exactly one update may overrun, and it must be the final entry",
        )

    def test_every_other_malformation_precedes_the_reset(self):
        """The treat-as-withdraw cases must all be reachable."""
        reset_index = next(
            i for i, u in enumerate(self.suite) if decode_attributes(u)[1]
        )
        for name, update in (
            ("missing_next_hop", mu.missing_next_hop_update()),
            ("malformed_as_path", mu.malformed_as_path_update()),
            ("invalid_origin", mu.invalid_origin_update()),
        ):
            with self.subTest(malformation=name):
                self.assertLess(self.suite.index(update), reset_index)

    def test_contains_every_malformation(self):
        self.assertIn(mu.missing_next_hop_update(), self.suite)
        self.assertIn(mu.malformed_as_path_update(), self.suite)
        self.assertIn(mu.bad_attribute_length_update(), self.suite)
        self.assertIn(mu.invalid_origin_update(), self.suite)

    def test_entries_advertise_distinct_prefixes(self):
        """Reusing one prefix would let a later UPDATE mask an earlier one's
        effect on the DUT's RIB, confusing attribution."""
        nlris = [nlri_of(u) for u in self.suite if nlri_of(u)]
        self.assertEqual(len(nlris), len(set(nlris)), nlris)

    def test_next_hop_is_threaded_through(self):
        suite = mu.rfc7606_malformation_suite(next_hop="203.0.113.9")
        for update in suite:
            attrs, _ = decode_attributes(update)
            if mu.ATTR_NEXT_HOP in attrs:
                self.assertEqual(
                    ".".join(str(b) for b in attrs[mu.ATTR_NEXT_HOP]["value"]),
                    "203.0.113.9",
                )


# -- builder input validation -------------------------------------------------


class BuilderValidationTest(unittest.TestCase):
    def test_rejects_bad_prefix_length(self):
        with self.assertRaises(ValueError):
            mu.well_formed_update(prefix_len=33)

    def test_rejects_non_ipv4_next_hop(self):
        with self.assertRaises(ValueError):
            mu.well_formed_update(next_hop="2001:db8::1")

    def test_accepts_a_real_four_byte_asn(self):
        """70000 needs AS4, which this speaker negotiates, so it must encode."""
        seg = as_path_segment(mu.well_formed_update(as_numbers=(70000,)))
        self.assertEqual(seg["body_len"], AS_OCTETS)

    def test_rejects_asn_too_large_for_four_octets(self):
        with self.assertRaises(ValueError):
            mu.well_formed_update(as_numbers=(0x1_0000_0000,))

    def test_rejects_oversized_attribute_value(self):
        with self.assertRaises(ValueError):
            mu._attribute(mu.ATTR_ORIGIN, b"\x00" * 300)


if __name__ == "__main__":
    unittest.main()
