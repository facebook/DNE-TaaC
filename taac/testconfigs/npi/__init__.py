# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""NPI testconfigs package — re-exports from member modules.

Allows callers to use the package-level path:
    from taac.testconfigs.npi import (
        NPI_DVT_ICEPACK_GTSW__CPU_QUEUE_TEST_CONFIG,
    )

instead of the deeper module path.
"""

from taac.testconfigs.npi.cpu_queue_test_config import (
    create_dctypef_npi_cpu_queue_test_config,
    create_npi_cpu_queue_test_config,
    get_cpu_queue_constants,
    NPI_51T_DVT_KO3_SSW_CPU_QUEUE_TEST_CONFIG,
    NPI_51T_DVT_MP3_XSW_CPU_QUEUE_TEST_CONFIG,
    NPI_DVT_ICEPACK_GTSW__CPU_QUEUE_TEST_CONFIG,
)
from taac.testconfigs.npi.dlb_hardening_test_config import (
    build_dlb_hardening_testconfig,
    NPI_DVT_ICEPACK_GTSW__DLB_HARDENING,
    NPI_DVT_ICEPACK_GTSW__DLB_LONGEVITY,
)
from taac.testconfigs.npi.icepack_ecmp_resource_testing_config import (
    NPI_DVT_ICEPACK_GTSW__ECMP_RESOURCE_TESTING,
    test_config_for_icepack_ecmp_resource_testing,
)
from taac.testconfigs.npi.multinode_pfc_test_config import (
    NPI_DVT_ICEPACK_GTSW__MULTI_NODE_PFC_TEST_CONFIG,
)
from taac.testconfigs.npi.thrift_hardening_test_config import (
    create_npi_thrift_hardening_test_config,
    ICEPACK_GTSW_STSW_FLAP_PORTS,
    NPI_DVT_ICEPACK_GTSW__THRIFT_HARDENING_TEST_CONFIG,
)
from taac.testconfigs.npi.wedge800_npi_test_config import (
    W800_BGP_HARDENING_TEST_CONFIG,
    W800_CPU_QUEUE_TEST_CONFIG,
    W800_LONGEVITY_TEST_CONFIG,
    W800_SPEED_FLIP_SUBSUME_CHURN_TEST_CONFIG,
    W800_THRIFT_HARDENING_TEST_CONFIG,
)

__all__ = [
    "ICEPACK_GTSW_STSW_FLAP_PORTS",
    "NPI_51T_DVT_KO3_SSW_CPU_QUEUE_TEST_CONFIG",
    "NPI_51T_DVT_MP3_XSW_CPU_QUEUE_TEST_CONFIG",
    "NPI_DVT_ICEPACK_GTSW__CPU_QUEUE_TEST_CONFIG",
    "NPI_DVT_ICEPACK_GTSW__DLB_HARDENING",
    "NPI_DVT_ICEPACK_GTSW__DLB_LONGEVITY",
    "NPI_DVT_ICEPACK_GTSW__ECMP_RESOURCE_TESTING",
    "NPI_DVT_ICEPACK_GTSW__MULTI_NODE_PFC_TEST_CONFIG",
    "NPI_DVT_ICEPACK_GTSW__THRIFT_HARDENING_TEST_CONFIG",
    "W800_BGP_HARDENING_TEST_CONFIG",
    "W800_CPU_QUEUE_TEST_CONFIG",
    "W800_LONGEVITY_TEST_CONFIG",
    "W800_SPEED_FLIP_SUBSUME_CHURN_TEST_CONFIG",
    "W800_THRIFT_HARDENING_TEST_CONFIG",
    "build_dlb_hardening_testconfig",
    "create_dctypef_npi_cpu_queue_test_config",
    "create_npi_cpu_queue_test_config",
    "create_npi_thrift_hardening_test_config",
    "get_cpu_queue_constants",
    "test_config_for_icepack_ecmp_resource_testing",
]
