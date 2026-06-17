# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

from taac.testconfigs.fpf.fpf_stress_test_config import (
    TEST_CONFIG as FPF_STRESS_TEST_CONFIG,
)
from taac.testconfigs.fpf.fpf_tc15_interface_disable import (
    TEST_CONFIG as FPF_TC15_INTERFACE_DISABLE,
)
from taac.testconfigs.fpf.fpf_tc16_interface_enable import (
    TEST_CONFIG as FPF_TC16_INTERFACE_ENABLE,
)
from taac.testconfigs.fpf.fpf_tc17_link_drain import (
    TEST_CONFIG as FPF_TC17_LINK_DRAIN,
)
from taac.testconfigs.fpf.fpf_tc19_device_drain import (
    TEST_CONFIG as FPF_TC19_DEVICE_DRAIN,
)
from taac.testconfigs.fpf.fpf_tc20_device_undrain import (
    TEST_CONFIG as FPF_TC20_DEVICE_UNDRAIN,
)
from taac.testconfigs.fpf.fpf_tc21_prod_prefix_drain_link import (
    TEST_CONFIG as FPF_TC21_PROD_PREFIX_DRAIN_LINK,
)
from taac.testconfigs.fpf.fpf_tc22_prod_prefix_drain_device import (
    TEST_CONFIG as FPF_TC22_PROD_PREFIX_DRAIN_DEVICE,
)
from taac.testconfigs.fpf.fpf_tc23_bgp_restart import (
    TEST_CONFIG as FPF_TC23_BGP_RESTART,
)
from taac.testconfigs.fpf.fpf_tc24_fsdb_restart import (
    TEST_CONFIG as FPF_TC24_FSDB_RESTART,
)
from taac.testconfigs.fpf.fpf_tc25_wedge_agent_restart import (
    TEST_CONFIG as FPF_TC25_WEDGE_AGENT_RESTART,
)
from taac.testconfigs.fpf.fpf_tc26_qsfp_service_restart import (
    TEST_CONFIG as FPF_TC26_QSFP_SERVICE_RESTART,
)
from taac.testconfigs.fpf.fpf_tc27_agent_coldboot import (
    TEST_CONFIG as FPF_TC27_AGENT_COLDBOOT,
)

__all__ = [
    "FPF_STRESS_TEST_CONFIG",
    "FPF_TC15_INTERFACE_DISABLE",
    "FPF_TC16_INTERFACE_ENABLE",
    "FPF_TC17_LINK_DRAIN",
    "FPF_TC19_DEVICE_DRAIN",
    "FPF_TC20_DEVICE_UNDRAIN",
    "FPF_TC21_PROD_PREFIX_DRAIN_LINK",
    "FPF_TC22_PROD_PREFIX_DRAIN_DEVICE",
    "FPF_TC23_BGP_RESTART",
    "FPF_TC24_FSDB_RESTART",
    "FPF_TC25_WEDGE_AGENT_RESTART",
    "FPF_TC26_QSFP_SERVICE_RESTART",
    "FPF_TC27_AGENT_COLDBOOT",
]
