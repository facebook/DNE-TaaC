# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

"""Prefix profiling configuration for fsw004.p001.f01.qzd1."""

from taac.task_definitions import (
    create_run_commands_on_shell_task,
    create_wait_for_agent_convergence_task,
)
from taac.testconfigs.ai_bb.mp3n_prefix_profiling_ixia_config import (
    create_two_port_device_test_configs,
)


_IXIA_CHASSIS = "2401:db00:116:3006:21a:c5ff:fe01:314c"

(
    FSW004_P001_F01_QZD1_CONTIGUOUS_PREFIX_ALL,
    FSW004_P001_F01_QZD1_HYBRID_PREFIX_ALL,
    FSW004_P001_F01_QZD1_NON_CONTIGUOUS_PREFIX_ALL,
) = create_two_port_device_test_configs(
    device_name="fsw004.p001.f01.qzd1",
    remote_as=65301,
    peer_group="PEERGROUP_FSW_IXIA_V6",
    prefix_stresser=(
        "eth9/16/1",
        "2401:db00:e50d:1309",
        _IXIA_CHASSIS,
        "4/1",
    ),
    downlink=(
        "eth8/16/1",
        "2401:db00:e50d:1308",
        _IXIA_CHASSIS,
        "11/3",
    ),
    mac_address="c0:18:50:99:8b:8e",
    ingress_policy="PROPAGATE_FSW_IXIA_PREFIX_PROFILING_IN",
    egress_policy="PROPAGATE_FSW_IXIA_PREFIX_PROFILING_OUT",
    patcher_suffix="fsw004_p001_ixia",
    config_name_prefix="FSW004_P001_F01_QZD1_PREFIX_PROFILING_SCALE",
    basset_pool="dne.test",
    pre_setup_tasks=[
        create_run_commands_on_shell_task(
            hostname="fsw004.p001.f01.qzd1",
            cmds=[
                "fboss_local_drainer undrain && "
                "fboss_local_drainer is_drained; [ $? -eq 162 ]"
            ],
            validate_output=True,
        ),
    ],
    post_setup_tasks=[
        create_wait_for_agent_convergence_task(
            hostnames="fsw004.p001.f01.qzd1",
            timeout=600,
            interval=5,
        ),
    ],
)
