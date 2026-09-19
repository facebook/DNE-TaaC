# pyre-unsafe
"""Tasks that behave differently under TAAC_OSS=1."""
import base64
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import taac.tasks.all as all_tasks
from taac.tasks.all import AllocateCgroupSliceMemory, AssertThriftRateLimitEnabledTask


class OssGatingTest(unittest.IsolatedAsyncioTestCase):
    async def test_allocate_cgroup_slice_memory_is_a_no_op_under_oss(self) -> None:
        task = AllocateCgroupSliceMemory(hostname="dut1", logger=MagicMock())
        with (
            patch.object(all_tasks, "TAAC_OSS", True),
            patch.object(
                all_tasks, "async_get_device_driver", new_callable=AsyncMock
            ) as get_driver,
        ):
            await task.run({"hostname": "dut1", "slice_name": "workload"})
        get_driver.assert_not_awaited()
        task.logger.warning.assert_called_once()

    def test_thrift_rate_limit_probe_reads_the_oss_agent_config(self) -> None:
        for oss, expected in (
            (True, "/etc/coop/agent.conf"),
            (False, "/etc/coop/agent/current"),
        ):
            with patch.object(all_tasks, "TAAC_OSS", oss):
                self.assertEqual(AssertThriftRateLimitEnabledTask.agent_config_path(), expected)
                b64 = AssertThriftRateLimitEnabledTask._build_probe_cmd().split()[1]
                self.assertIn(expected, base64.b64decode(b64).decode())
