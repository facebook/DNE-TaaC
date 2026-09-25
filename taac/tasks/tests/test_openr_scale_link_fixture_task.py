# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

import json
from unittest.mock import AsyncMock, MagicMock, patch

from later.unittest import TestCase
from taac.internal.tasks.openr_scale_link_fixture_task import (
    OpenRScaleLinkFixtureTask,
)
from taac.task_definitions import (
    create_openr_scale_link_fixture_task,
)
from taac.tasks.registry import TASK_NAME_TO_CLASS


_MODULE = "neteng.test_infra.dne.taac.internal.tasks.openr_scale_link_fixture_task"


class _FakeEosDriver:
    def __init__(self, group: int, unexpected_test_member: str | None = None) -> None:
        self.group = group
        self.configs: list[str] = []
        self.test_port_channel_exists = group == 1911
        self.unexpected_test_member = unexpected_test_member

    async def async_execute_show_or_configure_cmd_on_shell(
        self, command: str, *, configure: bool = False
    ) -> str:
        if not configure:
            return (
                f"interface Ethernet3/10/1\n   channel-group {self.group} mode active"
            )
        self.configs.append(command)
        if "channel-group 1911 mode active" in command:
            self.group = 1911
            self.test_port_channel_exists = True
        if "channel-group 1910 mode active" in command:
            self.group = 1910
        if "no interface Port-Channel1911" in command:
            self.test_port_channel_exists = False
            self.unexpected_test_member = None
        return ""

    async def async_get_port_channel_detailed_info(self) -> dict:
        port_channels = {
            f"Port-Channel{self.group}": {
                "activePorts": {"Ethernet3/10/1": {}},
                "inactiveLag": False,
            }
        }
        if self.test_port_channel_exists and self.group != 1911:
            port_channels["Port-Channel1911"] = {
                "activePorts": {},
                "inactiveLag": True,
            }
        if self.unexpected_test_member is not None:
            port_channels["Port-Channel1911"] = {
                "activePorts": {self.unexpected_test_member: {}},
                "inactivePorts": {},
                "inactiveLag": False,
            }
        return {"portChannels": port_channels}


def _params(action: str) -> dict[str, object]:
    return {
        "action": action,
        "ipv4_cidrs_by_device": {
            "eb02.lab.ash6": "10.165.28.12/31",
            "eb04.lab.ash6": "10.165.28.13/31",
        },
        "member_interface": "Ethernet3/10/1",
        "original_port_channel_id": 1910,
        "test_port_channel_id": 1911,
        "description": "second eb02-eb04 OpenR test link",
        "timeout_seconds": 120,
    }


class OpenRScaleLinkFixtureTaskTest(TestCase):
    def test_factory_serializes_the_reversible_fixture(self) -> None:
        task = create_openr_scale_link_fixture_task(
            action="setup",
            ipv4_cidrs_by_device={
                "eb02.lab.ash6": "10.165.28.12/31",
                "eb04.lab.ash6": "10.165.28.13/31",
            },
        )

        self.assertEqual("openr_scale_link_fixture", task.task_name)
        self.assertEqual(_params("setup"), json.loads(task.params.json_params or "{}"))

    def test_registered_as_an_internal_task(self) -> None:
        self.assertIs(
            OpenRScaleLinkFixtureTask,
            TASK_NAME_TO_CLASS["openr_scale_link_fixture"],
        )

    async def test_setup_splits_the_member_and_configures_both_addresses(self) -> None:
        eb02 = _FakeEosDriver(group=1910)
        eb04 = _FakeEosDriver(group=1910)
        with patch(
            f"{_MODULE}.async_get_device_driver",
            new=AsyncMock(side_effect=[eb02, eb04]),
        ):
            await OpenRScaleLinkFixtureTask(logger=MagicMock()).run(_params("setup"))

        self.assertEqual(1911, eb02.group)
        self.assertEqual(1911, eb04.group)
        self.assertIn("ip address 10.165.28.12/31", eb02.configs[0])
        self.assertIn("ip address 10.165.28.13/31", eb04.configs[0])
        for driver in (eb02, eb04):
            self.assertIn("no channel-group 1910", driver.configs[0])
            self.assertIn("channel-group 1911 mode active", driver.configs[0])

    async def test_cleanup_restores_the_original_two_member_port_channel(self) -> None:
        eb02 = _FakeEosDriver(group=1911)
        eb04 = _FakeEosDriver(group=1911)
        with patch(
            f"{_MODULE}.async_get_device_driver",
            new=AsyncMock(side_effect=[eb02, eb04]),
        ):
            await OpenRScaleLinkFixtureTask(logger=MagicMock()).run(_params("cleanup"))

        for driver in (eb02, eb04):
            self.assertEqual(1910, driver.group)
            self.assertFalse(driver.test_port_channel_exists)
            self.assertIn("no channel-group 1911", driver.configs[0])
            self.assertIn("channel-group 1910 mode active", driver.configs[0])
            self.assertIn("no interface Port-Channel1911", driver.configs[0])

    async def test_cleanup_attempts_both_devices_before_reporting_failure(self) -> None:
        eb02 = _FakeEosDriver(group=2000)
        eb04 = _FakeEosDriver(group=1911)
        with patch(
            f"{_MODULE}.async_get_device_driver",
            new=AsyncMock(side_effect=[eb02, eb04]),
        ):
            with self.assertRaisesRegex(RuntimeError, "eb02.lab.ash6"):
                await OpenRScaleLinkFixtureTask(logger=MagicMock()).run(
                    _params("cleanup")
                )

        self.assertEqual(1910, eb04.group)
        self.assertFalse(eb04.test_port_channel_exists)

    async def test_cleanup_does_not_apply_setup_availability_guard(self) -> None:
        eb02 = _FakeEosDriver(group=1911, unexpected_test_member="Ethernet1/1")
        eb04 = _FakeEosDriver(group=1911)
        with patch(
            f"{_MODULE}.async_get_device_driver",
            new=AsyncMock(side_effect=[eb02, eb04]),
        ):
            await OpenRScaleLinkFixtureTask(logger=MagicMock()).run(_params("cleanup"))

        self.assertEqual(1910, eb02.group)
        self.assertEqual(1910, eb04.group)

    async def test_refuses_to_repurpose_a_test_lag_with_another_member(self) -> None:
        eb02 = _FakeEosDriver(group=1910, unexpected_test_member="Ethernet1/1")
        eb04 = _FakeEosDriver(group=1910)
        with patch(
            f"{_MODULE}.async_get_device_driver",
            new=AsyncMock(side_effect=[eb02, eb04]),
        ):
            with self.assertRaisesRegex(RuntimeError, "cannot be safely repurposed"):
                await OpenRScaleLinkFixtureTask(logger=MagicMock()).run(
                    _params("setup")
                )

        self.assertEqual([], eb02.configs)
        self.assertEqual([], eb04.configs)

    async def test_refuses_to_repurpose_a_memberless_existing_lag(self) -> None:
        eb02 = _FakeEosDriver(group=1910)
        eb02.test_port_channel_exists = True
        eb04 = _FakeEosDriver(group=1910)
        with patch(
            f"{_MODULE}.async_get_device_driver",
            new=AsyncMock(side_effect=[eb02, eb04]),
        ):
            with self.assertRaisesRegex(RuntimeError, "cannot be safely repurposed"):
                await OpenRScaleLinkFixtureTask(logger=MagicMock()).run(
                    _params("setup")
                )

        self.assertEqual([], eb02.configs)
        self.assertEqual([], eb04.configs)

    async def test_setup_refuses_to_take_a_member_from_an_unrelated_lag(self) -> None:
        eb02 = _FakeEosDriver(group=2000)
        eb04 = _FakeEosDriver(group=1910)
        with patch(
            f"{_MODULE}.async_get_device_driver",
            new=AsyncMock(side_effect=[eb02, eb04]),
        ):
            with self.assertRaisesRegex(RuntimeError, "observed channel-group 2000"):
                await OpenRScaleLinkFixtureTask(logger=MagicMock()).run(
                    _params("setup")
                )

        self.assertEqual(2000, eb02.group)
        self.assertEqual([], eb02.configs)
