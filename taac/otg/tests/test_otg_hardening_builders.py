# pyre-unsafe
"""Unit tests for taac/otg/otg_hardening_builders.py.

Focused on the failure mode that would otherwise produce a *green* run: a
malformed speaker that silently advertises nothing.
"""

import unittest
from unittest.mock import patch

from taac.otg import otg_hardening_builders as hb


def _thrift_has_update_sequence() -> bool:
    return getattr(hb.ixia_types, "BgpUpdateSequence", None) is not None


class MalformedSpeakerRequiresThriftSupportTest(unittest.TestCase):
    """`BgpUpdateSequence` is a local thrift addition, so it can go missing.

    An upstream sync reverts the `.thrift` source, and a checkout without
    regenerated thrift never had it. The failure has to be loud: this speaker
    declares no route_scales, so without the sequence it establishes, advertises
    nothing, and the malformed profile passes having tested no malformation.
    """

    def test_raises_a_clear_error_when_the_thrift_struct_is_missing(self):
        # create=True so this runs whether or not the struct is present here.
        with patch.object(hb.ixia_types, "BgpUpdateSequence", None, create=True):
            with self.assertRaises(RuntimeError) as ctx:
                hb._malformed_bgp_device_group(0)
        message = str(ctx.exception)
        self.assertIn("BgpUpdateSequence", message)
        self.assertIn("--regen-thrift", message)

    @unittest.skipUnless(
        _thrift_has_update_sequence(),
        "generated thrift lacks BgpUpdateSequence; run with --regen-thrift",
    )
    def test_builds_the_replay_sequence_when_the_struct_is_present(self):
        dg = hb._malformed_bgp_device_group(0)
        self.assertTrue(dg.v4_bgp_config.update_sequence.updates)

    @unittest.skipUnless(
        _thrift_has_update_sequence(),
        "generated thrift lacks BgpUpdateSequence; run with --regen-thrift",
    )
    def test_the_speaker_advertises_nothing_declaratively(self):
        """Why the guard matters: there is no fallback advertisement."""
        dg = hb._malformed_bgp_device_group(0)
        self.assertFalse(dg.v4_bgp_config.route_scales)


if __name__ == "__main__":
    unittest.main()


class MalformedSpeakerDiffersOnlyInBytesTest(unittest.TestCase):
    """The malformed speaker must negotiate what every other peer negotiates.

    Its whole purpose is that the UPDATEs it replays are the only variable. A
    different capability set changes which bgpd code paths are reachable, so a
    reaction could be attributed to the malformation when it came from the
    capability difference.
    """

    def test_capabilities_match_the_measured_peers(self):
        dg = hb._malformed_bgp_device_group(0)
        self.assertEqual(
            list(dg.v4_bgp_config.bgp_capabilities),
            list(hb._bgp_capabilities()),
        )
