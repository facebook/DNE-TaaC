# Copyright (c) Meta Platforms, Inc. and affiliates.

"""Critical-services single-box TestConfig for fsw001.p001.f01.qzd1."""

from taac.playbooks.playbook_definitions import (
    get_critical_services_single_box_playbooks,
)
from taac.testconfigs.fboss_solution_tests.chronos_node_fsw_p001_qzd1_test_config import (
    create_chronos_node_fsw_p001_qzd1_test_config,
)


CHRONOS_NODE_FSW_P001_QZD1_CRITICAL_SERVICES_TEST_CONFIG = (
    create_chronos_node_fsw_p001_qzd1_test_config(
        test_config_name="CHRONOS_NODE_FSW_P001_QZD1_CRITICAL_SERVICES",
        playbooks=get_critical_services_single_box_playbooks(
            iteration=5,
            ixia_rogue_ic_parent_network_v6="2401:db00:e50d:11:10",
            ixia_rogue_ic_parent_network_v4="10.165.28",
        ),
    )
)
