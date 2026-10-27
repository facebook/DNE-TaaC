# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

import unittest

from taac.testconfigs.routing import cicd_ebb_int_tc
from taac.test_as_a_config import types as taac_types


class BgpcppStackDeclarationTest(unittest.TestCase):
    def test_bgpcpp_dut_configs_declare_arista_fboss(self) -> None:
        """BGP health checks read BGP++ only for devices declared ARISTA_FBOSS;
        an undeclared BGP++ DUT falls back to native EOS BGP's empty table."""
        for config in (
            cicd_ebb_int_tc.NRQEB006_STAGE1_FULL_SCALE_TEST_CONFIG_UG,
            cicd_ebb_int_tc.NRQEB008_STAGE1_FULL_SCALE_TEST_CONFIG_UG,
            cicd_ebb_int_tc.NRQEB009_STAGE1_FULL_SCALE_TEST_CONFIG_UG,
            cicd_ebb_int_tc.NRQEB009_SC9_BOUNDED_ECMP_SETS_TEST_CONFIG_UG,
        ):
            with self.subTest(config=config.name):
                declared = set((config.host_os_type_map or {}).values())
                self.assertEqual({taac_types.DeviceOsType.ARISTA_FBOSS}, declared)
