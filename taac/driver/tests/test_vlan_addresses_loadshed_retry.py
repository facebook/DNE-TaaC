# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

import ipaddress
import logging
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, call, patch

from taac.driver.fboss_switch import FbossSwitch
from thrift.python.exceptions import ApplicationError, ApplicationErrorType


def _intf(vlan_id: int, cidr: str) -> SimpleNamespace:
    net = ipaddress.ip_interface(cidr)
    addr = SimpleNamespace(
        ip=SimpleNamespace(addr=net.ip.packed), prefixLength=net.network.prefixlen
    )
    return SimpleNamespace(vlanId=vlan_id, address=[addr])


# what the agent's thrift rate limiter answers
_RATE_LIMITED = ApplicationError(
    ApplicationErrorType.LOADSHEDDING, "ThriftMethoRateLimit"
)


class VlanAddressesRateLimitRetryTest(unittest.IsolatedAsyncioTestCase):
    def _switch(self, side_effect) -> FbossSwitch:
        sw = FbossSwitch("dut1", logging.getLogger(__name__))
        sw.async_get_all_interfaces = AsyncMock(side_effect=side_effect)
        return sw

    async def test_rate_limit_is_retried(self) -> None:
        sw = self._switch(
            [_RATE_LIMITED, _RATE_LIMITED, {1: _intf(2100, "2001:db8::1/64")}]
        )
        with patch("asyncio.sleep", new=AsyncMock()) as sleep:
            self.assertEqual(
                ["2001:db8::1/64"], await sw.async_get_vlan_addresses(2100)
            )
        self.assertEqual(3, sw.async_get_all_interfaces.await_count)
        self.assertEqual([call(1), call(1)], sleep.await_args_list)

    async def test_gives_up_after_30_tries(self) -> None:
        sw = self._switch(_RATE_LIMITED)
        with patch("asyncio.sleep", new=AsyncMock()):
            with self.assertRaises(ApplicationError) as raised:
                await sw.async_get_vlan_addresses(2100)
        self.assertIs(_RATE_LIMITED, raised.exception)
        self.assertEqual(30, sw.async_get_all_interfaces.await_count)

    async def test_other_errors_raise(self) -> None:
        for err in (
            ApplicationError(ApplicationErrorType.UNKNOWN, "boom"),
            ApplicationError(ApplicationErrorType.LOADSHEDDING, "queue full"),
        ):
            with self.subTest(err=err):
                sw = self._switch([err])
                with self.assertRaises(ApplicationError):
                    await sw.async_get_vlan_addresses(2100)
                self.assertEqual(1, sw.async_get_all_interfaces.await_count)
