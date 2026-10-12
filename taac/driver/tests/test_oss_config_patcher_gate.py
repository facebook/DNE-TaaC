#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""The OSS file-based config patcher runs only in pure OSS.

Internal runs use COOP through ``FbossSwitchInternal``, and the
``TAAC_OSS_META_INTERNAL=1`` container targets COOP-managed Meta devices, so in
both the base ``FbossSwitch`` patcher methods raise without touching the device,
as they did before the OSS patcher existed.
"""

import contextlib
import logging
import typing as t
from unittest.mock import patch

from later.unittest import TestCase
from neteng.test_infra.dne.taac.driver import fboss_switch, oss_coop_patcher
from taac.driver.fboss_switch import FbossSwitch
from taac.utils import oss_taac_lib_utils

_INTERNAL = (False, False)
_CONTAINER = (True, True)
_PURE_OSS = (True, False)

_PATCHER_CALLS: t.Dict[str, t.Callable[[FbossSwitch], t.Awaitable[t.Any]]] = {
    "register": lambda s: s.async_register_python_patcher(
        "bgpcpp", "p", "remove_bgp_peers", {"delete_all": "True"}
    ),
    "list": lambda s: s.async_coop_list_patchers("bgpcpp"),
    "unregister": lambda s: s.async_coop_unregister_patchers("p", "bgpcpp"),
    "apply": lambda s: s.async_apply_patchers(),
    "restore": lambda s: s.async_restore_patched_configs(),
    "static_route": lambda s: s.async_add_static_route_patcher(
        {"10.0.0.0/24": ["10.0.0.1"]}, "p", is_patcher_name_uuid_needed=False
    ),
    "change_speed": lambda s: s.async_change_speed_patcher(
        ["eth1/1/1", "eth1/2/1"],
        "FOURHUNDREDG",
        "PROFILE_400G_4_PAM4_RS544X2N_OPTICAL",
        "speed",
    ),
    "unregister_python": lambda s: s.async_unregister_python_patcher("p", "agent"),
}


@contextlib.contextmanager
def _taac_env(taac_oss: bool, meta_internal: bool) -> t.Iterator[None]:
    """Drive the real gate through the module-level flags it reads."""
    with (
        patch.object(oss_taac_lib_utils, "TAAC_OSS", taac_oss),
        patch.object(oss_taac_lib_utils, "TAAC_OSS_META_INTERNAL", meta_internal),
    ):
        yield


@contextlib.contextmanager
def _mocked_backend() -> t.Iterator[t.Dict[str, t.Any]]:
    names = (
        "async_register",
        "list_patchers",
        "find_configs",
        "async_unregister",
        "async_apply",
        "async_restore_baselines",
    )
    with contextlib.ExitStack() as stack:
        yield {
            name: stack.enter_context(patch.object(oss_coop_patcher, name))
            for name in names
        }


class ConfigPatcherGateTest(TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.switch = FbossSwitch("dut1", logging.getLogger(__name__))

    def test_gate_is_pure_oss_only(self) -> None:
        for mode, expected in (
            (_INTERNAL, False),
            (_CONTAINER, False),
            (_PURE_OSS, True),
        ):
            with self.subTest(mode=mode), _taac_env(*mode):
                self.assertEqual(
                    expected, oss_taac_lib_utils.oss_config_patcher_enabled()
                )

    async def test_outside_pure_oss_every_patcher_method_raises(self) -> None:
        for mode in (_INTERNAL, _CONTAINER):
            with _taac_env(*mode), _mocked_backend() as backend:
                for name, call in _PATCHER_CALLS.items():
                    with self.subTest(mode=mode, method=name):
                        with self.assertRaises(NotImplementedError):
                            await call(self.switch)
                for name, mocked in backend.items():
                    with self.subTest(mode=mode, backend=name):
                        mocked.assert_not_called()

    async def test_pure_oss_delegates_to_the_oss_patcher(self) -> None:
        with _taac_env(*_PURE_OSS), _mocked_backend() as backend:
            backend["async_unregister"].return_value = True
            await _PATCHER_CALLS["register"](self.switch)
            await _PATCHER_CALLS["unregister"](self.switch)
            await _PATCHER_CALLS["apply"](self.switch)
            await _PATCHER_CALLS["restore"](self.switch)

        backend["async_register"].assert_awaited_once()
        backend["async_unregister"].assert_awaited_once_with(self.switch, "bgpcpp", "p")
        backend["async_apply"].assert_awaited_once_with(
            self.switch, None, False, activate=True
        )
        backend["async_restore_baselines"].assert_awaited_once_with(self.switch)

    async def test_pure_oss_change_speed_registers_coops_change_speed(self) -> None:
        with _taac_env(*_PURE_OSS), _mocked_backend() as backend:
            name = await _PATCHER_CALLS["change_speed"](self.switch)
            await self.switch.async_apply_patchers(restart_services=False)

        self.assertEqual("speed", name)
        (call,) = backend["async_register"].await_args_list
        patcher = call.args[1]
        self.assertEqual(
            ("agent", "speed", "change_speed"),
            (patcher.config_name, patcher.name, patcher.py_func_name),
        )
        self.assertEqual(
            {
                "intfs": "eth1/1/1,eth1/2/1",
                "speed": "FOURHUNDREDG",
                "profile_id": "PROFILE_400G_4_PAM4_RS544X2N_OPTICAL",
            },
            patcher.args,
        )
        backend["async_apply"].assert_awaited_once_with(
            self.switch, None, False, activate=False
        )

    def test_driver_reads_the_shared_gate(self) -> None:
        self.assertIs(
            oss_taac_lib_utils.oss_config_patcher_enabled,
            fboss_switch.oss_config_patcher_enabled,
        )
