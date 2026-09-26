# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""Wedge800 (W800) NPI snake TestConfigs.

Single-DUT loopback qualification for the W800 NPI program.

The WEDGE800CACT 400G testbed is cabled as ONE continuous serpentine
rather than the per-subport chains the Minipack3/Kodiak3 snakes use:
``eth1/N/5`` is jumpered to ``eth1/(N+1)/1`` and each OSFP cage forwards
``/1`` to ``/5`` internally, so a single chain walks all 64 ports
(32 cages x 2 subports, VLANs 2000-2031) between the two IXIA ports.
That ordering is fixed by the landed static topology
``static_topologies/fboss338726358_ash6.cconf``, and it is why each
config here declares one ``SnakeConfig`` instead of two.

``W800_NPI_SNAKE_TEST_CONFIGS`` is collected by
``testconfigs/internal/all.py``.
"""

from taac.testconfigs.snake.test_test_config import (
    gen_snake_test_config,
)
from taac.test_as_a_config import types as taac_types


# Everything gen_snake_playbooks emits except test_72hr_longevity (3-day soak,
# run on its own once the short soaks are clean) and the three system-reboot
# playbooks (need BMC reachability from the test host). Spelled as an allowlist
# rather than playbooks_to_skip because gen_snake_test_config validates
# playbooks_to_include against the generated set and raises on an unknown name.
_W800_NPI_CORE_PLAYBOOKS = [
    "test_one_min_longevity",
    "test_ten_min_longevity",
    "test_one_hour_longevity",
    "test_snake_interface_toggle_with_thrift_api",
    "test_snake_half_interface_toggle_with_thrift_api",
    "test_snake_interface_toggle_with_qsfp_util_disable",
    "test_snake_interface_toggle_with_qsfp_util_low_power",
    "test_snake_interface_reset_with_qsfp_reset",
    "test_snake_agent_warmboot",
    "test_snake_agent_coldboot",
    "test_snake_agent_crash",
    "test_snake_qsfp_service_restart",
    "test_snake_qsfp_service_crash",
    "test_snake_fsdb_restart",
    "test_snake_fsdb_crash",
]


WEDGE800CACT_NPI_SNAKE_TEST_CONFIG_400G = gen_snake_test_config(
    name="WEDGE800CACT_NPI_SNAKE_TEST_CONFIG_400G",
    basset_pool="dne.standalone",
    snake_configs=[
        taac_types.SnakeConfig(
            source="fboss338726358.ash6:eth1/1/1",
            destination="fboss338726358.ash6:eth1/32/5",
            source_ip="5000:1::1/64",
            destination_ip="5000:1::2/64",
        ),
    ],
    hostname="fboss338726358.ash6",
    line_rate=99,
    playbooks_to_include=_W800_NPI_CORE_PLAYBOOKS,
)


W800_NPI_SNAKE_TEST_CONFIGS = [
    WEDGE800CACT_NPI_SNAKE_TEST_CONFIG_400G,
]
