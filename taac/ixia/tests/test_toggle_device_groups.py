# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-strict

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from taac.ixia.ixia import Ixia


def _ixia() -> tuple[Ixia, MagicMock]:
    with patch.object(Ixia, "__init__", lambda self: None):
        ixia = Ixia()
    ixia.logger = MagicMock()
    apply_changes = MagicMock()
    ixia.apply_changes = apply_changes
    return ixia, apply_changes


def _device_group(name: str, enabled_values: list[object]) -> SimpleNamespace:
    return SimpleNamespace(
        Name=name,
        Enabled=SimpleNamespace(
            Values=enabled_values,
            Single=MagicMock(),
        ),
    )


class _IntegerLikeReadback:
    def __init__(self, value: int) -> None:
        self.value = value

    def __index__(self) -> int:
        return self.value


class ToggleDeviceGroupsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.ixia, self.apply_changes = _ixia()

    @patch("neteng.test_infra.dne.taac.ixia.ixia.time.sleep")
    def test_validated_toggle_requires_match(self, sleep: MagicMock) -> None:
        self.ixia.find_device_groups = MagicMock(return_value=[])

        with self.assertRaisesRegex(ValueError, "selected no device groups"):
            self.ixia.toggle_device_groups(
                enable=True,
                device_group_name_regex="missing",
                require_match=True,
                verify_readback=True,
            )

        sleep.assert_not_called()
        self.apply_changes.assert_not_called()

    @patch("neteng.test_infra.dne.taac.ixia.ixia.time.sleep")
    def test_validated_toggle_accepts_exact_readback(self, sleep: MagicMock) -> None:
        groups = [
            _device_group("v4", ["Enabled"]),
            _device_group("v6", [True, True]),
            _device_group("numeric", [1]),
        ]
        self.ixia.find_device_groups = MagicMock(return_value=groups)

        self.ixia.toggle_device_groups(
            enable=True,
            device_group_name_regex=".*",
            require_match=True,
            verify_readback=True,
            sleep_time_before_applying_change=0,
        )

        for group in groups:
            group.Enabled.Single.assert_called_once_with(True)
        sleep.assert_called_once_with(0)
        self.apply_changes.assert_called_once_with()

    @patch("neteng.test_infra.dne.taac.ixia.ixia.time.sleep")
    def test_validated_toggle_accepts_integer_like_readback(
        self, sleep: MagicMock
    ) -> None:
        group = _device_group("numeric", [_IntegerLikeReadback(1)])
        self.ixia.find_device_groups = MagicMock(return_value=[group])

        self.ixia.toggle_device_groups(
            enable=True,
            device_group_name_regex=".*",
            require_match=True,
            verify_readback=True,
            sleep_time_before_applying_change=0,
        )

        group.Enabled.Single.assert_called_once_with(True)
        sleep.assert_called_once_with(0)
        self.apply_changes.assert_called_once_with()

    @patch("neteng.test_infra.dne.taac.ixia.ixia.time.sleep")
    def test_validated_toggle_rejects_stale_readback(self, sleep: MagicMock) -> None:
        group = _device_group("v4", [False])
        self.ixia.find_device_groups = MagicMock(return_value=[group])

        with self.assertRaisesRegex(RuntimeError, "Enabled readback mismatch"):
            self.ixia.toggle_device_groups(
                enable=True,
                device_group_name_regex=".*",
                require_match=True,
                verify_readback=True,
                sleep_time_before_applying_change=0,
            )

        sleep.assert_called_once_with(0)
        self.apply_changes.assert_called_once_with()

    @patch("neteng.test_infra.dne.taac.ixia.ixia.time.sleep")
    def test_validated_toggle_rejects_missing_readback(self, sleep: MagicMock) -> None:
        group = _device_group("v4", [])
        self.ixia.find_device_groups = MagicMock(return_value=[group])

        with self.assertRaisesRegex(RuntimeError, "readback missing"):
            self.ixia.toggle_device_groups(
                enable=True,
                device_group_name_regex=".*",
                require_match=True,
                verify_readback=True,
                sleep_time_before_applying_change=0,
            )

        sleep.assert_called_once_with(0)
        self.apply_changes.assert_called_once_with()

    @patch("neteng.test_infra.dne.taac.ixia.ixia.time.sleep")
    def test_validated_toggle_reports_all_readback_failures(
        self, sleep: MagicMock
    ) -> None:
        groups = [
            _device_group("missing", []),
            _device_group("stale", [False]),
        ]
        self.ixia.find_device_groups = MagicMock(return_value=groups)

        with self.assertRaises(RuntimeError) as context:
            self.ixia.toggle_device_groups(
                enable=True,
                device_group_name_regex=".*",
                require_match=True,
                verify_readback=True,
                sleep_time_before_applying_change=0,
            )

        self.assertIn("readback missing for missing", str(context.exception))
        self.assertIn("readback mismatch for stale", str(context.exception))
        sleep.assert_called_once_with(0)
        self.apply_changes.assert_called_once_with()

    @patch("neteng.test_infra.dne.taac.ixia.ixia.time.sleep")
    def test_toggle_ignores_exceptions_when_not_all_bgp_peers(
        self, sleep: MagicMock
    ) -> None:
        skipped = _device_group("skip-v4", [False])
        selected = _device_group("v6", [False])
        self.ixia.find_device_groups = MagicMock(return_value=[skipped, selected])

        self.ixia.toggle_device_groups(
            enable=True,
            device_group_name_regex=".*",
            exception_device_groups=["skip"],
            sleep_time_before_applying_change=0,
        )

        skipped.Enabled.Single.assert_called_once_with(True)
        selected.Enabled.Single.assert_called_once_with(True)
        sleep.assert_called_once_with(0)

    @patch("neteng.test_infra.dne.taac.ixia.ixia.time.sleep")
    def test_toggle_filters_exceptions_for_all_bgp_peers(
        self, sleep: MagicMock
    ) -> None:
        skipped = _device_group("skip-v4", [False])
        selected = _device_group("v6", [False])
        self.ixia.find_device_groups = MagicMock(return_value=[skipped, selected])

        self.ixia.toggle_device_groups(
            enable=True,
            device_group_name_regex=".*",
            all_bgp_peers=True,
            exception_device_groups=["skip"],
            sleep_time_before_applying_change=0,
        )

        skipped.Enabled.Single.assert_not_called()
        selected.Enabled.Single.assert_called_once_with(True)
        sleep.assert_called_once_with(0)
