# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""OSS interface drain: a persistent ``interface-drain-<iface>`` bgpcpp patcher
in place of the local drainer, pure OSS only."""

import contextlib
import ipaddress
import json
import logging
import typing as t
from unittest.mock import AsyncMock, MagicMock, patch

# @manual=//configerator/structs/neteng/fboss/bgp:bgp_config-python-types
from configerator.structs.neteng.fboss.bgp.bgp_config.thrift_types import BgpConfig
from facebook.network.Address.types import BinaryAddress
from later.unittest import TestCase
from neteng.fboss.ctrl.types import InterfaceDetail, IpPrefix, PortInfoThrift
from neteng.fboss.switch_config.types import InterfaceType
from taac.driver import (
    config_modifiers,
    fboss_switch,
    oss_coop_patcher,
)
from taac.driver.fboss_switch import FbossSwitch
from taac.utils import oss_taac_lib_utils


def _ip_prefix(cidr: str) -> IpPrefix:
    network = ipaddress.ip_interface(cidr).network
    return IpPrefix(
        ip=BinaryAddress(addr=network.network_address.packed),
        prefixLength=network.prefixlen,
    )


HOST = "dut1"


def _ports() -> t.Dict[int, PortInfoThrift]:
    return {
        1: PortInfoThrift(portId=1, name="eth1/1/1", vlans=[2001]),
        2: PortInfoThrift(portId=2, name="eth1/2/1", vlans=[2002]),
        3: PortInfoThrift(portId=3, name="eth1/3/1", vlans=[2000]),
        4: PortInfoThrift(portId=4, name="eth1/4/1", vlans=[2000]),
    }


def _vlan_interface(vlan: int, *cidrs: str) -> InterfaceDetail:
    return InterfaceDetail(
        interfaceName=f"fboss{vlan}",
        interfaceId=vlan,
        vlanId=vlan,
        interfaceType=InterfaceType.VLAN,
        address=[_ip_prefix(cidr) for cidr in cidrs],
    )


def _interfaces() -> t.Dict[int, InterfaceDetail]:
    return {
        2001: _vlan_interface(2001, "2001:db8:1::/127", "10.0.0.0/31", "fe80::/64"),
        2002: _vlan_interface(2002, "2001:db8:2::/127"),
        2000: _vlan_interface(2000, "2001:db8:100::/64"),
    }


def _registered(*interfaces: str) -> t.List[oss_coop_patcher.OssPatcher]:
    return [
        oss_coop_patcher.OssPatcher(
            name=f"interface-drain-{i}",
            config_name="bgpcpp",
            py_func_name="drain_interface",
        )
        for i in interfaces
    ]


class OssInterfaceDrainTest(TestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        for flag, value in (("TAAC_OSS", True), ("TAAC_OSS_META_INTERNAL", False)):
            stack.enter_context(patch.object(oss_taac_lib_utils, flag, value))
        self.switch = FbossSwitch(HOST, logging.getLogger(__name__))
        self.drained = stack.enter_context(
            patch.object(
                config_modifiers,
                "async_is_device_drained",
                AsyncMock(return_value=False),
            )
        )
        self.listed = stack.enter_context(
            patch.object(oss_coop_patcher, "list_patchers", return_value=[])
        )
        self.unregister = stack.enter_context(
            patch.object(oss_coop_patcher, "async_unregister", AsyncMock())
        )
        for name, value in (
            ("async_get_all_port_info", _ports()),
            ("async_get_all_interfaces", _interfaces()),
        ):
            stack.enter_context(
                patch.object(self.switch, name, AsyncMock(return_value=value))
            )
        self.register = stack.enter_context(
            patch.object(self.switch, "async_register_python_patcher", AsyncMock())
        )
        self.apply = stack.enter_context(
            patch.object(self.switch, "async_apply_patchers", AsyncMock())
        )
        self.verify = stack.enter_context(
            patch.object(self.switch, "_async_verify_interfaces_drained", AsyncMock())
        )

    async def test_drain_registers_one_patcher_per_interface_and_applies_once(
        self,
    ) -> None:
        await self.switch.async_softdrain_interfaces(["eth1/1/1", "eth1/2/1"])

        self.assertEqual(2, self.register.await_count)
        config_name, name, py_func, args, _ = self.register.await_args_list[0].args
        self.assertEqual(
            ("bgpcpp", "interface-drain-eth1/1/1", "drain_interface"),
            (config_name, name, py_func),
        )
        self.assertEqual("eth1/1/1", args["interface_name"])
        # The link-local address is skipped: every interface carries one.
        self.assertEqual(
            ["2001:db8:1::/127", "10.0.0.0/31"], json.loads(args["networks"])
        )
        self.assertEqual(["interface_name", "networks"], sorted(args))
        self.apply.assert_awaited_once_with()
        self.verify.assert_awaited_once_with(["eth1/1/1", "eth1/2/1"], True)

    async def test_already_drained_interface_is_left_alone(self) -> None:
        self.listed.return_value = _registered("eth1/1/1")

        await self.switch.async_softdrain_interface("eth1/1/1")

        self.register.assert_not_awaited()
        self.apply.assert_not_awaited()

    async def test_undrain_unregisters_and_applies_once(self) -> None:
        self.listed.return_value = _registered("eth1/1/1", "eth1/2/1")

        await self.switch.async_undrain_interfaces(["eth1/1/1", "eth1/2/1"])

        self.assertEqual(
            [
                (self.switch, "bgpcpp", "interface-drain-eth1/1/1"),
                (self.switch, "bgpcpp", "interface-drain-eth1/2/1"),
            ],
            [c.args for c in self.unregister.await_args_list],
        )
        self.apply.assert_awaited_once_with()
        self.verify.assert_awaited_once_with(["eth1/1/1", "eth1/2/1"], False)

    async def test_undrain_of_an_undrained_interface_is_a_no_op(self) -> None:
        await self.switch.async_undrain_interface("eth1/1/1")

        self.unregister.assert_not_awaited()
        self.apply.assert_not_awaited()

    async def test_drain_and_undrain_are_refused_while_the_device_is_drained(
        self,
    ) -> None:
        self.drained.return_value = True
        self.listed.return_value = _registered("eth1/2/1")

        with self.assertRaisesRegex(config_modifiers.ConfigModifierError, "drained"):
            await self.switch.async_softdrain_interface("eth1/1/1")
        with self.assertRaisesRegex(config_modifiers.ConfigModifierError, "drained"):
            await self.switch.async_undrain_interface("eth1/2/1")

        self.register.assert_not_awaited()
        self.unregister.assert_not_awaited()
        self.apply.assert_not_awaited()

    async def test_refused_patcher_unregisters_the_batch_and_applies_nothing(
        self,
    ) -> None:
        self.register.side_effect = [None, RuntimeError("no BGP peer")]

        with self.assertRaisesRegex(RuntimeError, "no BGP peer"):
            await self.switch.async_softdrain_interfaces(["eth1/1/1", "eth1/2/1"])

        self.unregister.assert_awaited_once_with(
            self.switch, "bgpcpp", "interface-drain-eth1/1/1"
        )
        self.apply.assert_not_awaited()

    async def test_shared_vlan_is_refused(self) -> None:
        with self.assertRaisesRegex(fboss_switch.InvalidInputError, "eth1/4/1"):
            await self.switch.async_softdrain_interface("eth1/3/1")

        self.register.assert_not_awaited()

    async def test_hard_drain_is_not_available(self) -> None:
        with self.assertRaisesRegex(NotImplementedError, "soft drain"):
            await self.switch.async_drain_interfaces(["eth1/1/1"])

        self.register.assert_not_awaited()


class VerifyInterfacesDrainedTest(TestCase):
    async def test_live_config_must_record_the_drain(self) -> None:
        switch = FbossSwitch(HOST, logging.getLogger(__name__))
        live = config_modifiers.serialize_config(
            BgpConfig(drained_interfaces=["eth1/1/1"])
        )
        with patch.object(switch, "async_read_file", AsyncMock(return_value=live)):
            await switch._async_verify_interfaces_drained(["eth1/1/1"], True)
            await switch._async_verify_interfaces_drained(["eth1/2/1"], False)
            with self.assertRaisesRegex(
                config_modifiers.ConfigModifierError, "eth1/2/1"
            ):
                await switch._async_verify_interfaces_drained(["eth1/2/1"], True)


class InterfaceDrainGateTest(TestCase):
    """Internal runs and the Meta container keep the local drainer."""

    async def test_local_drainer_outside_pure_oss(self) -> None:
        for taac_oss, meta_internal in ((False, False), (True, True)):
            with self.subTest(taac_oss=taac_oss, meta_internal=meta_internal):
                switch = FbossSwitch(HOST, logging.getLogger(__name__))
                client = MagicMock()
                client.softdrain_interfaces = AsyncMock()
                client.undrain_interfaces = AsyncMock()
                drainer = MagicMock()
                drainer.__aenter__ = AsyncMock(return_value=client)
                drainer.__aexit__ = AsyncMock(return_value=False)
                oss = AsyncMock()
                with (
                    patch.object(oss_taac_lib_utils, "TAAC_OSS", taac_oss),
                    patch.object(
                        oss_taac_lib_utils, "TAAC_OSS_META_INTERNAL", meta_internal
                    ),
                    patch.object(
                        switch, "get_async_local_drainer_client", return_value=drainer
                    ),
                    patch.object(switch, "_async_oss_set_interfaces_drained", oss),
                ):
                    await switch.async_softdrain_interfaces(["eth1/1/1"])
                    await switch.async_undrain_interfaces(["eth1/1/1"])

                client.softdrain_interfaces.assert_awaited_once_with(["eth1/1/1"], 0)
                client.undrain_interfaces.assert_awaited_once_with(["eth1/1/1"])
                oss.assert_not_awaited()
