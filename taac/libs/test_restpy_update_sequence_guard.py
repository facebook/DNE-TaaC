# pyre-unsafe
# Copyright (c) Meta Platforms, Inc. and affiliates.
"""The restpy backend cannot send a raw BGP UPDATE sequence.

`BgpUpdateSequence` reaches this backend through the same thrift `BgpConfig` the
OTG backend uses, but IxNetwork has no equivalent primitive, so the field would
otherwise be dropped in silence: the session establishes, the sequence is never
sent, and a test whose whole point is those bytes passes having exercised
nothing.  Failing at config time is the only honest option.

Lives here rather than in taac/ixia/tests/ because conftest.py excludes that
whole directory from OSS collection; this test has no internal dependencies,
and a guard that never runs is no guard.
"""

import unittest
from unittest.mock import MagicMock, patch

from taac.ixia.ixia import Ixia


def _create_ixia_instance():
    with patch.object(Ixia, "__init__", lambda self: None):
        ixia = Ixia()
    ixia.logger = MagicMock()
    ixia.session = MagicMock()
    ixia.apply_changes = MagicMock()
    return ixia


def _bgp_config(update_sequence=None):
    cfg = MagicMock()
    cfg.update_sequence = update_sequence
    cfg.bgp_prefix_configs = None
    cfg.import_bgp_routes_params_list = None
    return cfg


class UpdateSequenceUnsupportedTest(unittest.TestCase):
    def setUp(self):
        self.ixia = _create_ixia_instance()
        self.ixia.create_bgp_peer = MagicMock()
        self.ixia.create_bgp_prefixes = MagicMock()
        self.ixia.import_bgp_routes = MagicMock()
        self.ixia.configure_custom_network_groups = MagicMock()

    def _call(self, bgp_config):
        self.ixia.create_bgp_stacks(
            port_identifier="1/1/1",
            bgp_config=bgp_config,
            device_group_obj=MagicMock(),
            ip_address_obj=MagicMock(),
            device_group_index=0,
        )

    def test_raises_when_an_update_sequence_is_present(self):
        seq = MagicMock()
        seq.updates = [MagicMock(update_bytes="ffff0013", time_gap_ms=0)]
        with self.assertRaises(NotImplementedError) as ctx:
            self._call(_bgp_config(update_sequence=seq))
        self.assertIn("update_sequence", str(ctx.exception))

    def test_no_peer_is_built_when_it_raises(self):
        seq = MagicMock()
        seq.updates = [MagicMock(update_bytes="ffff0013", time_gap_ms=0)]
        with self.assertRaises(NotImplementedError):
            self._call(_bgp_config(update_sequence=seq))
        self.ixia.create_bgp_peer.assert_not_called()

    def test_absent_update_sequence_is_unaffected(self):
        self._call(_bgp_config(update_sequence=None))
        self.ixia.create_bgp_peer.assert_called_once()

    def test_empty_update_sequence_is_unaffected(self):
        seq = MagicMock()
        seq.updates = []
        self._call(_bgp_config(update_sequence=seq))
        self.ixia.create_bgp_peer.assert_called_once()


if __name__ == "__main__":
    unittest.main()



class UpdateSequenceSurvivesThriftRevertTest(unittest.TestCase):
    """`BgpUpdateSequence` is a local thrift addition; a sync removes it.

    The passthrough reads the field off the taac struct and forwards it as a
    kwarg to the ixia struct, so a revert breaks BOTH sides — AttributeError on
    the read, TypeError on the kwarg — for EVERY BGP config, not only the one
    profile that uses a sequence. Configs that never set one must keep working;
    the profile that needs it still fails loudly, in _malformed_bgp_device_group.
    """

    def _generator(self):
        from taac.libs.traffic_generator import TrafficGenerator

        with patch.object(TrafficGenerator, "__init__", lambda self: None):
            gen = TrafficGenerator()
        gen.logger = MagicMock()
        gen.create_bgp_prefix_configs = MagicMock(return_value=[])
        from ixia.ixia import types as ixia_types

        # Thrift validates every field's type, so the collaborators must return
        # real structs -- which is what makes this test prove the construction
        # actually succeeds rather than that a mock accepted a kwarg.
        gen._create_bgp_peer_config = MagicMock(
            return_value=ixia_types.BgpPeerConfig()
        )
        return gen

    @staticmethod
    def _reverted_bgp_config():
        """A taac BgpConfig from before the local thrift addition."""
        cfg = MagicMock(spec=["route_scales", "local_as", "local_as_4_bytes",
                              "enable_4_byte_local_as", "custom_network_group_configs",
                              "import_bgp_routes_params_list"])
        cfg.route_scales = []
        cfg.local_as = 0
        cfg.local_as_4_bytes = 65001
        cfg.enable_4_byte_local_as = True
        cfg.custom_network_group_configs = None
        cfg.import_bgp_routes_params_list = None
        return cfg

    def test_a_config_without_the_field_still_builds(self):
        import asyncio

        gen = self._generator()
        cfg = self._reverted_bgp_config()
        self.assertFalse(hasattr(cfg, "update_sequence"))
        from ixia.ixia import types as ixia_types

        result = asyncio.run(
            gen.async_create_bgp_config_thrift(
                hostname="dut",
                bgp_config=cfg,
                ip_address_info=MagicMock(),
                ip_address_family=ixia_types.IpAddressFamily.IPV4,
            )
        )
        self.assertIsNotNone(result)
