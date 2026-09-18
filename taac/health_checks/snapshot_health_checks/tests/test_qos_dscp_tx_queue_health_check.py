# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from taac.constants import TestTopology
from taac.health_checks.constants import Snapshot
from taac.health_checks.snapshot_health_checks.qos_dscp_tx_queue_health_check import (
    DEFAULT_QUEUE_OFFSET_BYTES,
    QoSDscpTxQueueHealthCheck,
)
from taac.utils.oss_taac_lib_utils import ConsoleFileLogger
from taac.utils.qos_constants import ClassOfService
from taac.health_check.health_check import types as hc_types


_HOSTNAME = "switch.example"
_INTERFACE = "eth1/1/1"
_KEY_DESC = "out_bytes.sum"


def _cos_key(cos: ClassOfService) -> str:
    descriptions = {
        ClassOfService.BRONZE: "queue1.bronze",
        ClassOfService.SILVER: "queue2.silver",
        ClassOfService.GOLD: "queue3.gold",
        ClassOfService.ICP: "queue6.icp",
        ClassOfService.NC: "queue7.nc",
    }
    return f"{_INTERFACE}.{descriptions[cos]}.{_KEY_DESC}"


def _queue_desc_key(description: str) -> str:
    return f"{_INTERFACE}.{description}.{_KEY_DESC}"


def _make_check(input_: hc_types.QoSDscpTxQueueHealthCheckIn):
    return QoSDscpTxQueueHealthCheck(
        obj=MagicMock(spec=TestTopology),
        input=input_,
        pre_snapshot_checkpoint_id="pre",
        post_snapshot_checkpoint_id="post",
        check_params={},
        logger=MagicMock(spec=ConsoleFileLogger),
    )


def _cos_input(
    cos: ClassOfService,
    *,
    enforce_exclusivity: bool = False,
) -> hc_types.QoSDscpTxQueueHealthCheckIn:
    return hc_types.QoSDscpTxQueueHealthCheckIn(
        tx_queue_info_list=[
            hc_types.TxQueueInfo(
                hostname=_HOSTNAME,
                interface=_INTERFACE,
                cos_list=[int(cos)],
                key_desc=_KEY_DESC,
                val=0,
                comparison=hc_types.ComparisonType.GREATER_THAN,
                enforce_exclusivity=enforce_exclusivity,
            )
        ]
    )


def _queue_desc_input(
    description: str,
    *,
    enforce_exclusivity: bool = False,
) -> hc_types.QoSDscpTxQueueHealthCheckIn:
    return hc_types.QoSDscpTxQueueHealthCheckIn(
        tx_queue_info_list=[
            hc_types.TxQueueInfo(
                hostname=_HOSTNAME,
                interface=_INTERFACE,
                queue_desc_list=[description],
                key_desc=_KEY_DESC,
                val=0,
                comparison=hc_types.ComparisonType.GREATER_THAN,
                enforce_exclusivity=enforce_exclusivity,
            )
        ]
    )


class QoSDscpTxQueueHealthCheckTest(unittest.IsolatedAsyncioTestCase):
    async def _compare(
        self,
        input_: hc_types.QoSDscpTxQueueHealthCheckIn,
        pre_counters: dict[str, int],
        post_counters: dict[str, int],
    ) -> hc_types.HealthCheckResult:
        check = _make_check(input_)
        return await check.compare_snapshots(
            obj=MagicMock(spec=TestTopology),
            input=input_,
            check_params={},
            pre_snapshot=Snapshot(data={_HOSTNAME: pre_counters}, timestamp=1),
            post_snapshot=Snapshot(data={_HOSTNAME: post_counters}, timestamp=2),
        )

    async def test_active_cos_counter_decrease_is_explicit_failure(self) -> None:
        result = await self._compare(
            _cos_input(ClassOfService.GOLD),
            {_cos_key(ClassOfService.GOLD): 100},
            {_cos_key(ClassOfService.GOLD): 90},
        )

        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        message = result.message or ""
        self.assertIn("counter decreased", message.lower())
        self.assertIn("could not be verified", message)

    async def test_exclusivity_cos_counter_decrease_fails_closed(self) -> None:
        result = await self._compare(
            _cos_input(ClassOfService.GOLD, enforce_exclusivity=True),
            {
                _cos_key(ClassOfService.GOLD): 0,
                _cos_key(ClassOfService.SILVER): 100,
            },
            {
                _cos_key(ClassOfService.GOLD): DEFAULT_QUEUE_OFFSET_BYTES + 1,
                _cos_key(ClassOfService.SILVER): 90,
            },
        )

        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        message = result.message or ""
        self.assertIn("counter decreased", message.lower())
        self.assertIn("SILVER", message)

    async def test_active_queue_description_decrease_is_explicit_failure(self) -> None:
        description = "queue2.rdma"
        result = await self._compare(
            _queue_desc_input(description),
            {_queue_desc_key(description): 100},
            {_queue_desc_key(description): 90},
        )

        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        message = result.message or ""
        self.assertIn("counter decreased", message.lower())
        self.assertIn(description, message)

    async def test_exclusivity_queue_description_decrease_fails_closed(self) -> None:
        active_description = "queue2.rdma"
        idle_description = "queue6.monitoring"
        result = await self._compare(
            _queue_desc_input(active_description, enforce_exclusivity=True),
            {
                _queue_desc_key(active_description): 0,
                _queue_desc_key(idle_description): 100,
            },
            {
                _queue_desc_key(active_description): DEFAULT_QUEUE_OFFSET_BYTES + 1,
                _queue_desc_key(idle_description): 90,
            },
        )

        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        message = result.message or ""
        self.assertIn("counter decreased", message.lower())
        self.assertIn(idle_description, message)

    async def test_monotonic_delta_still_applies_noise_offset(self) -> None:
        result = await self._compare(
            _cos_input(ClassOfService.GOLD),
            {_cos_key(ClassOfService.GOLD): 100},
            {_cos_key(ClassOfService.GOLD): 100 + DEFAULT_QUEUE_OFFSET_BYTES + 1},
        )

        self.assertEqual(result.status, hc_types.HealthCheckStatus.PASS)

    async def test_missing_active_counter_still_fails(self) -> None:
        result = await self._compare(
            _cos_input(ClassOfService.GOLD),
            {},
            {},
        )

        self.assertEqual(result.status, hc_types.HealthCheckStatus.FAIL)
        self.assertIn("did not export", result.message or "")
