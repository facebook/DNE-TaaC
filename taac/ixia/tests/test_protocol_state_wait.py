# pyre-unsafe
# Copyright (c) Meta Platforms, Inc. and affiliates.
"""Unit tests for the protocol-state settle wait shared by the pool configurators.

``StopAllProtocols(Arg1="sync")`` returns once the stop is QUEUED, not once it
has been applied. A property write issued in that window is rejected by
IxNetwork with "Changing the property in a started element is not permitted",
which is why every configurator that mutates a non-on-the-fly property must wait
on the observed ``DeviceGroup.Status`` rather than on a guessed duration.
"""

import typing as t
import unittest
from unittest.mock import MagicMock, patch

from taac.ixia.ixia import (
    _PROTOCOL_STATE_SETTLE_TIMEOUT_SECONDS,
    Ixia,
    IxiaOperationTimeoutError,
)

_MODULE = "neteng.test_infra.dne.taac.ixia.ixia"

# The six per-route Multivalues one extended community decomposes into.
_EXT_COMMUNITY_FIELDS = (
    "Type",
    "SubType",
    "AsNumber2Bytes",
    "AssignedNumber4Bytes",
    "AsNumber4Bytes",
    "AssignedNumber2Bytes",
)


def _create_ixia() -> Ixia:
    """An Ixia with mocked session/logger and no real transport."""
    with patch.object(Ixia, "__init__", lambda self: None):
        ixia = Ixia()
    ixia.logger = MagicMock()
    ixia.ixnetwork = MagicMock()
    return ixia


def _device_group(name: str, statuses: t.Sequence[str]) -> MagicMock:
    """A device group whose Status returns each value in turn, then repeats the last.

    Modelling Status as a SEQUENCE is the point: a wait that only ever reads it
    once cannot tell a settled element from a transitioning one.
    """
    group = MagicMock()
    group.Name = name
    remaining = list(statuses)

    def _status() -> str:
        return remaining.pop(0) if len(remaining) > 1 else remaining[0]

    type(group).Status = property(lambda _self: _status())
    return group


def _with_device_groups(ixia: Ixia, groups: t.Sequence[MagicMock]) -> None:
    topology = MagicMock()
    topology.DeviceGroup.find.return_value = list(groups)
    ixia.ixnetwork.Topology.find.return_value = [topology]


class WaitForProtocolsStoppedTest(unittest.TestCase):
    def setUp(self) -> None:
        self.ixia = _create_ixia()

    def test_returns_immediately_when_already_stopped(self) -> None:
        _with_device_groups(self.ixia, [_device_group("DG", ["notStarted"])])
        with patch(f"{_MODULE}.time.sleep") as mock_sleep:
            self.ixia.wait_for_protocols_stopped()
        mock_sleep.assert_not_called()

    def test_configured_also_counts_as_stopped(self) -> None:
        _with_device_groups(self.ixia, [_device_group("DG", ["configured"])])
        with patch(f"{_MODULE}.time.sleep") as mock_sleep:
            self.ixia.wait_for_protocols_stopped()
        mock_sleep.assert_not_called()

    def test_polls_until_the_state_actually_flips(self) -> None:
        """The regression: `stopping` is NOT stopped.

        This is the exact state a queued-but-unapplied StopAllProtocols leaves
        behind. Treating it as stopped is what let the AS-path write be issued
        into a started element.
        """
        group = _device_group("DG", ["started", "stopping", "stopping", "notStarted"])
        _with_device_groups(self.ixia, [group])
        with patch(f"{_MODULE}.time.sleep") as mock_sleep:
            self.ixia.wait_for_protocols_stopped()
        # Three non-stopped reads => three waits before the fourth read returns.
        self.assertEqual(3, mock_sleep.call_count)

    def test_waits_for_the_slowest_device_group(self) -> None:
        _with_device_groups(
            self.ixia,
            [
                _device_group("FAST", ["notStarted"]),
                _device_group("SLOW", ["started", "notStarted"]),
            ],
        )
        with patch(f"{_MODULE}.time.sleep") as mock_sleep:
            self.ixia.wait_for_protocols_stopped()
        self.assertEqual(1, mock_sleep.call_count)

    def test_timeout_raises_and_names_the_offending_element(self) -> None:
        _with_device_groups(
            self.ixia, [_device_group("DEVICE_GROUP_IPV6_EBGP", ["stopping"])]
        )
        # Deadline arithmetic uses time.monotonic; step it past the timeout.
        clock = iter([0.0, 0.0, float(_PROTOCOL_STATE_SETTLE_TIMEOUT_SECONDS + 1)])
        with (
            patch(f"{_MODULE}.time.sleep"),
            patch(f"{_MODULE}.time.monotonic", side_effect=lambda: next(clock)),
        ):
            with self.assertRaises(IxiaOperationTimeoutError) as context:
                self.ixia.wait_for_protocols_stopped()
        message = str(context.exception)
        self.assertIn("DEVICE_GROUP_IPV6_EBGP", message)
        self.assertIn("stopping", message)
        self.assertTrue(context.exception.deadline_expired)

    def test_error_state_is_not_treated_as_stopped(self) -> None:
        """A broken element must surface as a named timeout, not a silent pass."""
        _with_device_groups(self.ixia, [_device_group("DG", ["error"])])
        clock = iter([0.0, 0.0, float(_PROTOCOL_STATE_SETTLE_TIMEOUT_SECONDS + 1)])
        with (
            patch(f"{_MODULE}.time.sleep"),
            patch(f"{_MODULE}.time.monotonic", side_effect=lambda: next(clock)),
        ):
            with self.assertRaises(IxiaOperationTimeoutError):
                self.ixia.wait_for_protocols_stopped()


class StopProtocolsAndWaitTest(unittest.TestCase):
    def setUp(self) -> None:
        self.ixia = _create_ixia()

    def test_stops_then_waits(self) -> None:
        _with_device_groups(self.ixia, [_device_group("DG", ["notStarted"])])
        with (
            patch.object(Ixia, "stop_protocols") as mock_stop,
            patch.object(Ixia, "wait_for_protocols_stopped") as mock_wait,
        ):
            self.ixia.stop_protocols_and_wait()
        mock_stop.assert_called_once()
        mock_wait.assert_called_once()

    def test_wait_failure_propagates(self) -> None:
        """A stop that never settles must fail the caller, not be swallowed --
        proceeding would issue the write into a started element."""
        _with_device_groups(self.ixia, [_device_group("DG", ["stopping"])])
        clock = iter([0.0, 0.0, float(_PROTOCOL_STATE_SETTLE_TIMEOUT_SECONDS + 1)])
        with (
            patch.object(Ixia, "stop_protocols"),
            patch(f"{_MODULE}.time.sleep"),
            patch(f"{_MODULE}.time.monotonic", side_effect=lambda: next(clock)),
        ):
            with self.assertRaises(IxiaOperationTimeoutError):
                self.ixia.stop_protocols_and_wait()


class WriteMultivalueTest(unittest.TestCase):
    """A per-route Multivalue write must collapse to `Single()` when the column
    is constant.

    An extended community decomposes into SIX per-route Multivalues, and for a
    pool of the form ``<asn>:<n>`` with a two-byte ASN only ONE of them varies.
    Uploading the other five per-row costs tens of megabytes of REST body to
    express five scalars.
    """

    def setUp(self) -> None:
        self.ixia = _create_ixia()

    def test_constant_column_uses_single(self) -> None:
        field = MagicMock()
        self.ixia._write_multivalue(field, ["routetarget"] * 800_000, "SubType")
        field.Single.assert_called_once_with("routetarget")
        field.ValueList.assert_not_called()

    def test_constant_integer_column_uses_single(self) -> None:
        field = MagicMock()
        self.ixia._write_multivalue(field, [0] * 1_000, "AsNumber4Bytes")
        field.Single.assert_called_once_with(0)
        field.ValueList.assert_not_called()

    def test_varying_column_still_uses_value_list(self) -> None:
        """The collapse must not change what a genuinely varying column sends."""
        values = [index % 100 for index in range(1_000)]
        field = MagicMock()
        self.ixia._write_multivalue(field, values, "AssignedNumber4Bytes")
        field.ValueList.assert_called_once_with(values)
        field.Single.assert_not_called()

    def test_single_row_is_constant(self) -> None:
        field = MagicMock()
        self.ixia._write_multivalue(field, ["rt"], "Type")
        field.Single.assert_called_once_with("rt")

    def test_two_distinct_values_is_not_constant(self) -> None:
        """Boundary: one differing entry anywhere must defeat the collapse."""
        values = [7] * 999 + [8]
        field = MagicMock()
        self.ixia._write_multivalue(field, values, "AsNumber2Bytes")
        field.ValueList.assert_called_once_with(values)
        field.Single.assert_not_called()

    def test_empty_values_raises(self) -> None:
        field = MagicMock()
        with self.assertRaises(ValueError):
            self.ixia._write_multivalue(field, [], "Type")
        field.Single.assert_not_called()
        field.ValueList.assert_not_called()


class ExtendedCommunityWriteVolumeTest(unittest.TestCase):
    """End-to-end on the real SC2 shape: how many per-route arrays actually ship."""

    def setUp(self) -> None:
        self.ixia = _create_ixia()

    def test_sc2_pool_ships_exactly_one_per_route_array(self) -> None:
        """SC2's pool is ``55001:<n>`` with a two-byte ASN, so five of the six
        extended-community fields are constant and only AssignedNumber4Bytes
        varies. Regression guard on the 25-minute upload."""
        rows = 8_000
        combinations = [[f"55001:{index % 100 + 1}"] for index in range(rows)]
        values = self.ixia._build_extended_community_position_values(combinations, 0)

        position = MagicMock()
        self.ixia._write_extended_community_position(position, values, 0, 1, rows)

        # Exactly one field takes the per-route path; the other five are scalars.
        value_list_calls = [
            name
            for name in _EXT_COMMUNITY_FIELDS
            if getattr(position, name).ValueList.called
        ]
        single_calls = [
            name
            for name in _EXT_COMMUNITY_FIELDS
            if getattr(position, name).Single.called
        ]
        self.assertEqual(["AssignedNumber4Bytes"], value_list_calls)
        self.assertEqual(5, len(single_calls))
        self.assertNotIn("AssignedNumber4Bytes", single_calls)
