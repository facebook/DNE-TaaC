# Copyright (c) Meta Platforms, Inc. and affiliates.

import unittest
from unittest.mock import MagicMock

from ixia.ixia import types as ixia_types
from taac.ixia.ixia import Ixia


class BurstTransmissionControlTest(unittest.TestCase):
    def test_continuous_mode_does_not_send_burst_only_property(self) -> None:
        config_element = MagicMock()

        Ixia._configure_transmission_control(
            config_element,
            ixia_types.TransmissionControl(
                type=ixia_types.TransmissionControlType.CONTINUOUS,
            ),
        )

        config_element.TransmissionControl.update.assert_called_once_with(
            Type="continuous",
        )

    def test_native_repetition_programs_inter_burst_gap(self) -> None:
        config_element = MagicMock()

        Ixia._configure_transmission_control(
            config_element,
            ixia_types.TransmissionControl(
                type=ixia_types.TransmissionControlType.BURST_FIXED_DURATION,
                duration=60,
                burst_packet_count=2250,
                inter_burst_gap_ms=1500,
            ),
            repeat_burst_count=33,
        )

        config_element.TransmissionControl.update.assert_called_once_with(
            Type="burstFixedDuration",
            Duration=60,
            EnableInterBurstGap=True,
            BurstPacketCount=2250,
            InterBurstGap=1500,
            InterBurstGapUnits="milliseconds",
            RepeatBurst=33,
        )

    def test_existing_burst_mode_keeps_inter_burst_gap_enabled(self) -> None:
        config_element = MagicMock()

        Ixia._configure_transmission_control(
            config_element,
            ixia_types.TransmissionControl(
                type=ixia_types.TransmissionControlType.BURST_FIXED_DURATION,
                duration=60,
                burst_packet_count=2250,
            ),
        )

        config_element.TransmissionControl.update.assert_called_once_with(
            Type="burstFixedDuration",
            Duration=60,
            EnableInterBurstGap=True,
            BurstPacketCount=2250,
            RepeatBurst=1,
        )

    def test_explicit_zero_inter_burst_gap_clears_stale_value(self) -> None:
        config_element = MagicMock()

        Ixia._configure_transmission_control(
            config_element,
            ixia_types.TransmissionControl(
                type=ixia_types.TransmissionControlType.BURST_FIXED_DURATION,
                duration=60,
                burst_packet_count=2250,
                inter_burst_gap_ms=0,
            ),
        )

        config_element.TransmissionControl.update.assert_called_once_with(
            Type="burstFixedDuration",
            Duration=60,
            EnableInterBurstGap=True,
            BurstPacketCount=2250,
            RepeatBurst=1,
            InterBurstGap=0,
            InterBurstGapUnits="milliseconds",
        )

    def test_repeat_burst_requires_sequential_transmit_mode(self) -> None:
        ixia = object.__new__(Ixia)

        with self.assertRaisesRegex(ValueError, "requires transmit_mode='sequential'"):
            ixia.set_transmission_control(
                traffic_item_regex="pause",
                transmission_type="burstFixedDuration",
                burst_packet_count=2250,
                repeat_burst_count=33,
            )

    def test_repeat_burst_sets_sequential_transmit_mode(self) -> None:
        ixia = object.__new__(Ixia)
        traffic_item = MagicMock()
        traffic_item.Name = "pause"
        config_element = MagicMock()
        traffic_item.ConfigElement.find.return_value = [config_element]
        ixia.ixnetwork = MagicMock()
        ixia.ixnetwork.Traffic.TrafficItem.find.return_value = [traffic_item]
        ixia.logger = MagicMock()
        ixia.is_traffic_running = MagicMock(return_value=False)

        ixia.set_transmission_control(
            traffic_item_regex="pause",
            transmission_type="burstFixedDuration",
            duration=60,
            burst_packet_count=2250,
            inter_burst_gap_ms=1500,
            repeat_burst_count=33,
            transmit_mode="sequential",
        )

        traffic_item.update.assert_called_once_with(TransmitMode="sequential")
        config_element.TransmissionControl.update.assert_called_once_with(
            Type="burstFixedDuration",
            Duration=60,
            EnableInterBurstGap=True,
            BurstPacketCount=2250,
            InterBurstGap=1500,
            InterBurstGapUnits="milliseconds",
            RepeatBurst=33,
        )
        traffic_item.Generate.assert_called_once_with()
