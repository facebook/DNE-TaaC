# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

"""TC58: broad multi-FBOSS-process SIGKILL every 15s for 5 minutes.

This preserves the historical TC50 trigger exactly: on a multi-switch GTSW,
``Service.AGENT`` expands to ``pkill -9 -f fboss_``. Live inventory confirmed
that this broad full-command-line match includes BGP, qsfp_service, sw-agent,
hw-agent, local-drainer, updater, and matching logging helper processes. It
does not match the wedge_agent supervisor or fsdb.

The setup, disrupted-state checks, traffic expectations, recovery waits,
strict verdicts, and stable-state longevity playbook remain the former TC50
contract; only the identity now describes the actual blast radius and timing.
"""

from taac.testconfigs.fpf.fpf_tc50_wedge_agent_kill_5s_10min import (
    create_fpf_agent_kill_test_config,
)

TEST_NAME = "fpf_tc58_multi_fboss_process_kill_15s_5min"

TEST_CONFIG = create_fpf_agent_kill_test_config(
    test_name=TEST_NAME,
    broad_multi_fboss_process_kill=True,
)
