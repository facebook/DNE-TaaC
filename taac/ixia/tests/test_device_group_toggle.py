# Copyright (c) Meta Platforms, Inc. and affiliates.

from unittest.mock import MagicMock, patch

import later.unittest
from taac.ixia.ixia import Ixia


class _Enabled:
    def __init__(
        self,
        value: bool = True,
        *,
        apply: bool = True,
        setter_error: Exception | None = None,
        rollback_error: Exception | None = None,
        read_errors: dict[int, Exception] | None = None,
    ) -> None:
        self._values: list[object] = [value]
        self.apply = apply
        self.setter_error = setter_error
        self.rollback_error = rollback_error
        self.read_errors = read_errors or {}
        self.value_read_count = 0
        self.calls: list[bool] = []
        self.value_list_calls: list[list[object]] = []

    @property
    def Values(self) -> list[object]:
        self.value_read_count += 1
        if error := self.read_errors.get(self.value_read_count):
            raise error
        return self._values

    @Values.setter
    def Values(self, values: list[object]) -> None:
        self._values = values

    def Single(self, value: bool) -> None:
        self.calls.append(value)
        if self.setter_error is not None:
            raise self.setter_error
        if self.apply:
            self._values = [value]

    def ValueList(self, values: list[object]) -> None:
        self.value_list_calls.append(values)
        if self.rollback_error is not None:
            raise self.rollback_error
        self._values = list(values)


class _DeviceGroup:
    def __init__(
        self,
        index: int,
        *,
        apply: bool = True,
        setter_error: Exception | None = None,
        rollback_error: Exception | None = None,
        read_errors: dict[int, Exception] | None = None,
    ) -> None:
        self.Name = f"BAG012-DG-{index:02d}"
        self.Enabled = _Enabled(
            apply=apply,
            setter_error=setter_error,
            rollback_error=rollback_error,
            read_errors=read_errors,
        )


class DeviceGroupToggleTest(later.unittest.TestCase):
    def _ixia(self, groups: list[_DeviceGroup]) -> tuple[Ixia, MagicMock, MagicMock]:
        with patch.object(Ixia, "__init__", lambda self: None):
            ixia = Ixia()
        ixia.logger = MagicMock()
        find_device_groups = MagicMock(return_value=groups)
        ixia.find_device_groups = find_device_groups
        apply_changes = MagicMock()
        ixia.apply_changes = apply_changes
        return ixia, apply_changes, find_device_groups

    def test_expected_match_count_18_19_20_is_fail_closed(self) -> None:
        for expected in (18, 19, 20):
            with self.subTest(expected=expected):
                groups = [_DeviceGroup(index) for index in range(19)]
                ixia, apply_changes, _find_device_groups = self._ixia(groups)
                if expected == 19:
                    ixia.toggle_device_groups(
                        False,
                        "BAG012-DG-.*",
                        sleep_time_before_applying_change=0,
                        expected_match_count=expected,
                    )
                    self.assertTrue(
                        all(group.Enabled.calls == [False] for group in groups)
                    )
                    apply_changes.assert_called_once_with()
                else:
                    with self.assertRaisesRegex(ValueError, f"expected {expected}"):
                        ixia.toggle_device_groups(
                            False,
                            "BAG012-DG-.*",
                            sleep_time_before_applying_change=0,
                            expected_match_count=expected,
                        )
                    self.assertTrue(all(not group.Enabled.calls for group in groups))
                    apply_changes.assert_not_called()

    def test_exceptions_require_all_bgp_peers(self) -> None:
        groups = [_DeviceGroup(index) for index in range(2)]
        ixia, apply_changes, find_device_groups = self._ixia(groups)

        with self.assertRaisesRegex(
            ValueError, "exception_device_groups requires all_bgp_peers=True"
        ):
            ixia.toggle_device_groups(
                False,
                "BAG012-DG-.*",
                exception_device_groups=["DG-01"],
                sleep_time_before_applying_change=0,
                expected_match_count=1,
            )

        find_device_groups.assert_not_called()
        self.assertTrue(all(not group.Enabled.calls for group in groups))
        apply_changes.assert_not_called()

    def test_exclusions_precede_expected_match_count(self) -> None:
        groups = [_DeviceGroup(index) for index in range(2)]
        ixia, apply_changes, _find_device_groups = self._ixia(groups)

        ixia.toggle_device_groups(
            False,
            "BAG012-DG-.*",
            all_bgp_peers=True,
            exception_device_groups=["DG-01"],
            sleep_time_before_applying_change=0,
            expected_match_count=1,
        )

        self.assertEqual([False], groups[0].Enabled.calls)
        self.assertEqual([], groups[1].Enabled.calls)
        apply_changes.assert_called_once_with()

    def test_readback_mismatch_restores_original_values_and_applies(self) -> None:
        groups = [_DeviceGroup(index) for index in range(19)]
        groups[7] = _DeviceGroup(7, apply=False)
        ixia, apply_changes, _find_device_groups = self._ixia(groups)

        with self.assertRaisesRegex(
            ValueError, "readback failed.*restored exact original Values"
        ) as raised:
            ixia.toggle_device_groups(
                False,
                "BAG012-DG-.*",
                sleep_time_before_applying_change=0,
                expected_match_count=19,
            )

        self.assertEqual(2, apply_changes.call_count)
        self.assertTrue(
            all(group.Enabled.value_list_calls == [[True]] for group in groups)
        )
        self.assertTrue(all(group.Enabled.Values == [True] for group in groups))
        self.assertEqual([False], groups[7].Enabled.calls)
        self.assertIsNone(raised.exception.__cause__)

    def test_readback_rollback_aggregates_all_phase_failures(self) -> None:
        rollback_error = RuntimeError("DG-01 restore failed")
        apply_error = RuntimeError("rollback apply failed")
        readback_error = RuntimeError("DG-02 fresh readback failed")
        groups = [
            _DeviceGroup(0, apply=False),
            _DeviceGroup(1, rollback_error=rollback_error),
            _DeviceGroup(2, read_errors={3: readback_error}),
        ]
        ixia, apply_changes, _find_device_groups = self._ixia(groups)
        apply_changes.side_effect = [None, apply_error]

        with self.assertRaisesRegex(
            ValueError,
            "rollback failures.*restore BAG012-DG-01.*apply_changes.*"
            "readback BAG012-DG-01.*readback BAG012-DG-02",
        ) as raised:
            ixia.toggle_device_groups(
                False,
                "BAG012-DG-.*",
                sleep_time_before_applying_change=0,
                expected_match_count=3,
            )

        self.assertEqual(2, apply_changes.call_count)
        self.assertTrue(
            all(group.Enabled.value_list_calls == [[True]] for group in groups)
        )
        self.assertIsInstance(raised.exception.__cause__, ExceptionGroup)
        rollback_causes = raised.exception.__cause__.exceptions
        self.assertEqual(4, len(rollback_causes))
        self.assertIs(rollback_error, rollback_causes[0])
        self.assertIs(apply_error, rollback_causes[1])
        self.assertIsInstance(rollback_causes[2], ValueError)
        self.assertIn("BAG012-DG-01 expected original Values", str(rollback_causes[2]))
        self.assertIs(readback_error, rollback_causes[3])

    def test_desired_apply_failure_rolls_back_and_preserves_primary_error(self) -> None:
        apply_error = RuntimeError("desired apply failed")
        rollback_error = RuntimeError("DG-01 restore failed")
        groups = [
            _DeviceGroup(0),
            _DeviceGroup(1, rollback_error=rollback_error),
        ]
        ixia, apply_changes, _find_device_groups = self._ixia(groups)
        apply_changes.side_effect = [apply_error, None]

        with self.assertRaisesRegex(
            ValueError,
            "desired apply failed.*rollback failures.*restore BAG012-DG-01",
        ) as raised:
            ixia.toggle_device_groups(
                False,
                "BAG012-DG-.*",
                sleep_time_before_applying_change=0,
                expected_match_count=2,
            )

        self.assertEqual(2, apply_changes.call_count)
        self.assertTrue(
            all(group.Enabled.value_list_calls == [[True]] for group in groups)
        )
        self.assertIsInstance(raised.exception.__cause__, ExceptionGroup)
        causes = raised.exception.__cause__.exceptions
        self.assertIs(apply_error, causes[0])
        self.assertIs(rollback_error, causes[1])
        self.assertIsInstance(causes[2], ValueError)
        self.assertIn("BAG012-DG-01 expected original Values", str(causes[2]))

    def test_desired_read_error_rolls_back_and_preserves_primary_error(self) -> None:
        read_error = RuntimeError("desired Values read failed")
        rollback_apply_error = RuntimeError("rollback apply failed")
        groups = [
            _DeviceGroup(0),
            _DeviceGroup(1, read_errors={2: read_error}),
        ]
        ixia, apply_changes, _find_device_groups = self._ixia(groups)
        apply_changes.side_effect = [None, rollback_apply_error]

        with self.assertRaisesRegex(
            ValueError,
            "desired-state readback failed.*rollback failures.*apply_changes",
        ) as raised:
            ixia.toggle_device_groups(
                False,
                "BAG012-DG-.*",
                sleep_time_before_applying_change=0,
                expected_match_count=2,
            )

        self.assertEqual(2, apply_changes.call_count)
        self.assertTrue(
            all(group.Enabled.value_list_calls == [[True]] for group in groups)
        )
        self.assertTrue(all(group.Enabled.Values == [True] for group in groups))
        self.assertIsInstance(raised.exception.__cause__, ExceptionGroup)
        self.assertEqual(
            (read_error, rollback_apply_error),
            raised.exception.__cause__.exceptions,
        )

    def test_setter_failure_attempts_all_and_rolls_back_before_apply(self) -> None:
        setter_error = RuntimeError("DG-01 setter failed")
        groups = [
            _DeviceGroup(0),
            _DeviceGroup(1, setter_error=setter_error),
            _DeviceGroup(2),
        ]
        ixia, apply_changes, _find_device_groups = self._ixia(groups)

        with self.assertRaisesRegex(
            ValueError, "setter failures.*BAG012-DG-01"
        ) as raised:
            ixia.toggle_device_groups(
                False,
                "BAG012-DG-.*",
                sleep_time_before_applying_change=0,
                expected_match_count=3,
            )

        self.assertTrue(all(group.Enabled.calls == [False] for group in groups))
        self.assertTrue(
            all(group.Enabled.value_list_calls == [[True]] for group in groups)
        )
        self.assertTrue(all(group.Enabled.Values == [True] for group in groups))
        apply_changes.assert_not_called()
        self.assertIsInstance(raised.exception.__cause__, ExceptionGroup)
        self.assertEqual((setter_error,), raised.exception.__cause__.exceptions)

    def test_multiple_setter_and_rollback_failures_are_aggregated(self) -> None:
        first_setter_error = RuntimeError("DG-00 setter failed")
        second_setter_error = RuntimeError("DG-01 setter failed")
        rollback_error = RuntimeError("DG-02 rollback failed")
        groups = [
            _DeviceGroup(0, setter_error=first_setter_error),
            _DeviceGroup(1, setter_error=second_setter_error),
            _DeviceGroup(2, rollback_error=rollback_error),
        ]
        ixia, apply_changes, _find_device_groups = self._ixia(groups)

        with self.assertRaisesRegex(
            ValueError,
            "setter failures.*BAG012-DG-00.*BAG012-DG-01.*"
            "rollback failures.*BAG012-DG-02.*partially staged.*reset",
        ) as raised:
            ixia.toggle_device_groups(
                False,
                "BAG012-DG-.*",
                sleep_time_before_applying_change=0,
                expected_match_count=3,
            )

        self.assertTrue(all(group.Enabled.calls == [False] for group in groups))
        self.assertTrue(
            all(group.Enabled.value_list_calls == [[True]] for group in groups)
        )
        self.assertEqual([True], groups[0].Enabled.Values)
        self.assertEqual([True], groups[1].Enabled.Values)
        self.assertEqual([False], groups[2].Enabled.Values)
        self.assertIn(
            "restored groups: ['BAG012-DG-00', 'BAG012-DG-01']",
            str(raised.exception),
        )
        apply_changes.assert_not_called()
        self.assertIsInstance(raised.exception.__cause__, ExceptionGroup)
        self.assertEqual(
            (first_setter_error, second_setter_error, rollback_error),
            raised.exception.__cause__.exceptions,
        )

    def test_numeric_boolean_readback_is_accepted(self) -> None:
        for raw_value, enable in (
            (1, True),
            (0, False),
            (1.0, True),
            (0.0, False),
            ("1", True),
            ("0", False),
            ("1.0", True),
            ("0.0", False),
            ("true", True),
            ("false", False),
        ):
            with self.subTest(raw_value=raw_value):
                group = _DeviceGroup(0, apply=False)
                group.Enabled.Values = [raw_value]
                ixia, apply_changes, _find_device_groups = self._ixia([group])

                ixia.toggle_device_groups(
                    enable,
                    "BAG012-DG-.*",
                    sleep_time_before_applying_change=0,
                    expected_match_count=1,
                )

                self.assertEqual([enable], group.Enabled.calls)
                apply_changes.assert_called_once_with()

    def test_unknown_boolean_readback_is_rejected(self) -> None:
        for raw_value in (None, "enabled"):
            with self.subTest(raw_value=raw_value):
                group = _DeviceGroup(0, apply=False)
                group.Enabled.Values = [raw_value]
                ixia, _apply_changes, _find_device_groups = self._ixia([group])

                with self.assertRaisesRegex(ValueError, "readback failed"):
                    ixia.toggle_device_groups(
                        True,
                        "BAG012-DG-.*",
                        sleep_time_before_applying_change=0,
                        expected_match_count=1,
                    )
