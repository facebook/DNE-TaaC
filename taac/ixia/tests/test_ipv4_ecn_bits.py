# Copyright (c) Meta Platforms, Inc. and affiliates.
"""An ECN-capable IPv4 stream carries its ECN bits, not just its DSCP."""

import unittest
from unittest.mock import MagicMock

from ixia.ixia import types as ixia_types
from taac.ixia.ixia import Ixia

V4 = ixia_types.IpAddressFamily.IPV4
V6 = ixia_types.IpAddressFamily.IPV6


def _ixia_and_element():
    ixia = object.__new__(Ixia)
    ixia.logger = MagicMock()
    fields = {}

    def _find(**kwargs):
        key = kwargs.get("FieldTypeId") or kwargs.get("DisplayName")
        return fields.setdefault(key, MagicMock(name=str(key)))

    stack = MagicMock()
    stack.Field.find.return_value.find.side_effect = _find
    stack.Field.find.side_effect = (
        lambda **kw: _find(**kw) if kw else stack.Field.find.return_value
    )
    element = MagicMock()
    element.Stack.find.return_value = stack
    return ixia, element, fields


def _qos(ecn, phb=ixia_types.PHBTypes.DEFAULT):
    return ixia_types.QoSConfig(phb_type=phb, dscp_value=10, ecn_capability=ecn)


class Ipv4EcnBitsTest(unittest.TestCase):
    ECN_ID = r"^ipv4\.header\.priority\.ds\.phb\.defaultPHB\.unused$"

    def test_ecn_capable_ipv4_sets_ect0_beside_the_dscp(self):
        ixia, element, fields = _ixia_and_element()
        ixia.configure_qos_config(
            element, _qos(ixia_types.EcnCapability.ECN_CAPABLE), V4
        )
        self.assertEqual(fields["Default PHB"].SingleValue, 10)
        self.assertEqual(fields[self.ECN_ID].SingleValue, 2)

    def test_mixed_ipv4_alternates_ect0_and_not_ect(self):
        ixia, element, fields = _ixia_and_element()
        ixia.configure_qos_config(element, _qos(ixia_types.EcnCapability.MIXED), V4)
        self.assertEqual(fields[self.ECN_ID].ValueList, [2, 0])

    def test_non_capable_ipv4_leaves_the_ecn_bits_alone(self):
        ixia, element, fields = _ixia_and_element()
        ixia.configure_qos_config(
            element, _qos(ixia_types.EcnCapability.ECN_NON_CAPABLE), V4
        )
        self.assertNotIn(self.ECN_ID, fields)

    def test_the_ecn_field_follows_the_phb(self):
        ixia, element, fields = _ixia_and_element()
        ixia.configure_qos_config(
            element,
            _qos(ixia_types.EcnCapability.ECN_CAPABLE, ixia_types.PHBTypes.AF),
            V4,
        )
        self.assertIn(
            r"^ipv4\.header\.priority\.ds\.phb\.assuredForwardingPHB\.unused$", fields
        )

    def test_ipv6_is_unchanged(self):
        ixia, element, fields = _ixia_and_element()
        qos = ixia_types.QoSConfig(
            phb_type=ixia_types.PHBTypes.TRAFFIC_CLASS,
            dscp_value=10,
            ecn_capability=ixia_types.EcnCapability.ECN_CAPABLE,
        )
        ixia.configure_qos_config(element, qos, V6)
        self.assertEqual(fields["Traffic Class"].SingleValue, 42)  # 001010 + 10
        self.assertEqual([k for k in fields if "unused" in str(k)], [])


if __name__ == "__main__":
    unittest.main()
