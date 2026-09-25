# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

from unittest.mock import AsyncMock, MagicMock, patch

import later.unittest
from taac.driver.fboss_switch import FbossSwitch

_MODULE = "neteng.test_infra.dne.taac.driver.fboss_switch"


class FbossOpenRResetRecvToAdvertiseTest(later.unittest.TestCase):
    def _switch(self) -> FbossSwitch:
        switch = object.__new__(FbossSwitch)
        switch.hostname = "switch.example.com"
        switch.logger = MagicMock()
        return switch

    async def test_forwards_exact_rpc(self) -> None:
        client = AsyncMock()
        context = AsyncMock()
        context.__aenter__.return_value = client
        with patch(f"{_MODULE}.get_openr_ctrl_cpp_client", return_value=context):
            await self._switch().async_reset_openr_recv_to_advertise_max()
        client.resetRecvToAdvertiseMax.assert_awaited_once_with()

    async def test_rpc_failure_propagates(self) -> None:
        client = AsyncMock()
        client.resetRecvToAdvertiseMax.side_effect = RuntimeError("reset rejected")
        context = AsyncMock()
        context.__aenter__.return_value = client
        with patch(f"{_MODULE}.get_openr_ctrl_cpp_client", return_value=context):
            with self.assertRaisesRegex(RuntimeError, "reset rejected"):
                await self._switch().async_reset_openr_recv_to_advertise_max()

    async def test_oss_is_explicitly_unsupported(self) -> None:
        with patch(f"{_MODULE}.TAAC_OSS", True):
            with self.assertRaisesRegex(NotImplementedError, "OpenR"):
                await self._switch().async_reset_openr_recv_to_advertise_max()
