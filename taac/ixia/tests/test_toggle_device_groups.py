# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-strict

import unittest
from types import SimpleNamespace
from unittest.mock import call, MagicMock, patch

from taac.ixia.ixia import Ixia


def _ixia() -> tuple[Ixia, MagicMock]:
    with patch.object(Ixia, "__init__", lambda self: None):
        ixia = Ixia()
    ixia.logger = MagicMock()
    apply_changes = MagicMock()
    ixia.apply_changes = apply_changes
    return ixia, apply_changes


def _device_group(
    name: str,
    enabled_values: list[object],
    *,
    apply: bool = True,
) -> SimpleNamespace:
    enabled = SimpleNamespace(
        Values=enabled_values,
        Single=MagicMock(),
    )
    enabled.ValueList = MagicMock(
        side_effect=lambda values: setattr(enabled, "Values", list(values))
    )
    enabled.Single.side_effect = lambda value: (
        setattr(enabled, "Values", [value]) if apply else None
    )
    return SimpleNamespace(
        Name=name,
        Enabled=enabled,
    )


def _restartable_device_group(name: str = "ndp") -> SimpleNamespace:
    network_group = SimpleNamespace(Start=MagicMock())
    ipv6 = SimpleNamespace(BgpIpv6Peer=SimpleNamespace(find=MagicMock(return_value=[])))
    ethernet = SimpleNamespace(
        Ipv6=SimpleNamespace(find=MagicMock(return_value=[ipv6]))
    )
    group = _device_group(name, [True])
    group.NetworkGroup = SimpleNamespace(find=MagicMock(return_value=[network_group]))
    group.Ethernet = SimpleNamespace(find=MagicMock(return_value=[ethernet]))
    group.Start = MagicMock()
    group.update = MagicMock()
    return group


class _IntegerLikeReadback:
    def __init__(self, value: int) -> None:
        self.value = value

    def __index__(self) -> int:
        return self.value


class ToggleDeviceGroupsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.ixia, self.apply_changes = _ixia()

    @patch("neteng.test_infra.dne.taac.ixia.ixia.time.sleep")
    def test_single_group_toggle_applies_each_state_and_restarts_protocols(
        self, sleep: MagicMock
    ) -> None:
        group = _restartable_device_group()
        self.ixia._send_arp_ns_on_device_group = MagicMock()

        self.ixia.toggle_device_group(group, 5)

        self.assertEqual([call(False), call(True)], group.Enabled.Single.call_args_list)
        self.assertEqual(2, self.apply_changes.call_count)
        group.NetworkGroup.find.return_value[0].Start.assert_called_once_with()
        group.Start.assert_called_once_with()
        self.assertEqual([call(5), call(5)], sleep.call_args_list)
        self.ixia._send_arp_ns_on_device_group.assert_called_once_with(group)

    @patch("neteng.test_infra.dne.taac.ixia.ixia.time.sleep")
    def test_ipv6_resize_is_applied_before_group_restart(
        self, _sleep: MagicMock
    ) -> None:
        group = _restartable_device_group("downlink-ndp")
        events: list[object] = []
        group.update.side_effect = lambda **kwargs: events.append(("update", kwargs))
        self.apply_changes.side_effect = lambda: events.append("apply")
        self.ixia.toggle_device_group = MagicMock(
            side_effect=lambda _group, _sleep_s: events.append("restart")
        )
        self.ixia.find_device_groups = MagicMock(return_value=[group])

        self.ixia.configure_ipv6_entries(
            device_group_regex="downlink",
            prefix_count=40_000,
            toggle_matching_device_group=True,
            sleep_time_between_toggle_s=0,
        )

        self.assertEqual(
            [("update", {"Multiplier": 40_000}), "apply", "restart"], events
        )

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
            _device_group("v4", ["true"], apply=False),
            _device_group("v6", [True, True], apply=False),
            _device_group("numeric", [1], apply=False),
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
        group = _device_group("numeric", [_IntegerLikeReadback(1)], apply=False)
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
        group = _device_group("v4", [False], apply=False)
        self.ixia.find_device_groups = MagicMock(return_value=[group])

        with self.assertRaisesRegex(
            ValueError, "readback failed.*v4.*False.*restored exact original Values"
        ):
            self.ixia.toggle_device_groups(
                enable=True,
                device_group_name_regex=".*",
                require_match=True,
                verify_readback=True,
                sleep_time_before_applying_change=0,
            )

        sleep.assert_called_once_with(0)
        self.assertEqual(2, self.apply_changes.call_count)
        group.Enabled.ValueList.assert_called_once_with([False])

    @patch("neteng.test_infra.dne.taac.ixia.ixia.time.sleep")
    def test_validated_toggle_rejects_missing_readback(self, sleep: MagicMock) -> None:
        group = _device_group("v4", [], apply=False)
        self.ixia.find_device_groups = MagicMock(return_value=[group])

        with self.assertRaisesRegex(
            ValueError, "readback failed.*v4.*restored exact original Values"
        ):
            self.ixia.toggle_device_groups(
                enable=True,
                device_group_name_regex=".*",
                require_match=True,
                verify_readback=True,
                sleep_time_before_applying_change=0,
            )

        sleep.assert_called_once_with(0)
        self.assertEqual(2, self.apply_changes.call_count)
        group.Enabled.ValueList.assert_called_once_with([])

    @patch("neteng.test_infra.dne.taac.ixia.ixia.time.sleep")
    def test_validated_toggle_reports_all_readback_failures(
        self, sleep: MagicMock
    ) -> None:
        groups = [
            _device_group("missing", [], apply=False),
            _device_group("stale", [False], apply=False),
        ]
        self.ixia.find_device_groups = MagicMock(return_value=groups)

        with self.assertRaises(ValueError) as context:
            self.ixia.toggle_device_groups(
                enable=True,
                device_group_name_regex=".*",
                require_match=True,
                verify_readback=True,
                sleep_time_before_applying_change=0,
            )

        self.assertIn("('missing', ())", str(context.exception))
        self.assertIn("('stale', (False,))", str(context.exception))
        self.assertIn("restored exact original Values", str(context.exception))
        sleep.assert_called_once_with(0)
        self.assertEqual(2, self.apply_changes.call_count)

    @patch("neteng.test_infra.dne.taac.ixia.ixia.time.sleep")
    def test_toggle_ignores_exceptions_when_not_all_bgp_peers(
        self, sleep: MagicMock
    ) -> None:
        skipped = _device_group("skip-v4", [False])
        selected = _device_group("v6", [False])
        self.ixia.find_device_groups = MagicMock(return_value=[skipped, selected])

        with self.assertRaisesRegex(
            ValueError, "exception_device_groups requires all_bgp_peers=True"
        ):
            self.ixia.toggle_device_groups(
                enable=True,
                device_group_name_regex=".*",
                exception_device_groups=["skip"],
                sleep_time_before_applying_change=0,
            )

        skipped.Enabled.Single.assert_not_called()
        selected.Enabled.Single.assert_not_called()
        sleep.assert_not_called()
        self.apply_changes.assert_not_called()

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
