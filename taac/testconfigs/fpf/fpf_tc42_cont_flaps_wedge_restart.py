# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

"""TC42: TC40 rapid flaps plus wedge_agent restarts every two minutes."""

from taac.testconfigs.fpf.fpf_tc40_cont_interface_flaps import (
    create_fpf_cont_interface_flaps_test_config,
)
from taac.test_as_a_config import types as taac_types

TEST_NAME = "fpf_tc42_cont_flaps_wedge_restart"
FLAP_DURATION_SEC = 300
RESTART_EVERY_SEC = 120

TEST_CONFIG = create_fpf_cont_interface_flaps_test_config(
    test_name=TEST_NAME,
    flap_duration_sec=FLAP_DURATION_SEC,
    churn_service=taac_types.Service.AGENT,
    churn_action="restart",
    churn_every_sec=RESTART_EVERY_SEC,
    retry_final_cleanup_after_churn=True,
    observe_prod_prefix_on_all_hosts=True,
)
