# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

"""TC57: TC40 rapid flaps plus unclean qsfp_service crashes.

All eight GTSWs run TC40's exact fail-closed 7s/7s flap contract for 30
minutes.  After flapping has been active for 10 minutes, qsfp_service receives
the canonical SIGKILL crash action on every GTSW at 10-minute cadence,
producing events at approximately +10 and +20 minutes.  Every crash must
automatically recover to systemd ACTIVE before the test proceeds.  TC40's
health checks, RDMA expectations, strict failure verdicts, cleanup, and final
300-second stability soak are unchanged.
"""

from taac.testconfigs.fpf.fpf_tc40_cont_interface_flaps import (
    create_fpf_cont_interface_flaps_test_config,
)
from taac.test_as_a_config import types as taac_types

TEST_NAME = "fpf_tc57_cont_flaps_qsfp_crash"
FLAP_DURATION_SEC = 1800
QSFP_CHURN_EVERY_SEC = 600
QSFP_CHURN_INITIAL_DELAY_SEC = 600
QSFP_RECOVERY_TIMEOUT_SEC = 120

TEST_CONFIG = create_fpf_cont_interface_flaps_test_config(
    test_name=TEST_NAME,
    flap_duration_sec=FLAP_DURATION_SEC,
    churn_service=taac_types.Service.QSFP_SERVICE,
    churn_action="crash",
    churn_every_sec=QSFP_CHURN_EVERY_SEC,
    churn_initial_delay_sec=QSFP_CHURN_INITIAL_DELAY_SEC,
    churn_recovery_timeout_sec=QSFP_RECOVERY_TIMEOUT_SEC,
)
