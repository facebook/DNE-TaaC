# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

import unittest
from unittest import mock

from taac.health_checks.snapshot_health_checks.qos_dscp_tx_queue_health_check import (
    COS_QUEUE_FB303_COUNTER_DESC,
    QoSDscpTxQueueHealthCheck,
    RE_QUEUE_INDEX,
)


class _Stats:
    def __init__(self, queue_bytes):
        self.queueOutBytes_ = queue_bytes


class _Ctx:
    def __init__(self, client):
        self._client = client

    async def __aenter__(self):
        return self._client

    async def __aexit__(self, *exc):
        return False


class _Client:
    def __init__(self, stats):
        self._stats = stats

    async def getHwPortStats(self):
        return self._stats


class _Info:
    def __init__(self, hostname, interface, key_desc, queue_desc_list=None):
        self.hostname = hostname
        self.interface = interface
        self.key_desc = key_desc
        self.queue_desc_list = queue_desc_list or []


class _In:
    def __init__(self, infos):
        self.tx_queue_info_list = infos


def _check(stats, raises=False):
    chk = QoSDscpTxQueueHealthCheck.__new__(QoSDscpTxQueueHealthCheck)
    chk.logger = mock.MagicMock()
    driver = mock.MagicMock()
    driver.async_agent_client = _Ctx(_Client(stats))

    async def _get(_host):
        if raises:
            raise RuntimeError("agent unreachable")
        return driver

    return chk, _get


class QueueByteCounterTest(unittest.IsolatedAsyncioTestCase):
    """Per-queue out_bytes comes from queueOutBytes_, not an fb303 counter."""

    async def test_queue_index_drives_the_lookup(self):
        stats = {"eth1/32/1": _Stats({0: 5, 1: 10, 2: 20, 3: 30, 6: 60, 7: 70})}
        chk, getter = _check(stats)
        info = _Info("dut1", "eth1/32/1", "out_bytes.sum.60")
        with mock.patch(
            "taac.health_checks.snapshot_health_checks."
            "qos_dscp_tx_queue_health_check.async_get_device_driver",
            getter,
        ):
            out = await chk._queue_byte_counters("dut1", _In([info]))

        # silver is queue2 -> 20, gold is queue3 -> 30
        self.assertEqual(out["eth1/32/1.queue2.silver.out_bytes.sum.60"], 20)
        self.assertEqual(out["eth1/32/1.queue3.gold.out_bytes.sum.60"], 30)
        self.assertEqual(out["eth1/32/1.queue7.nc.out_bytes.sum.60"], 70)

    async def test_missing_queue_is_absent_not_zero(self):
        # queue 6 (icp) absent from the stats -> no key, so the check can tell
        # "never exported" from "exported as zero"
        stats = {"eth1/32/1": _Stats({1: 10, 2: 20})}
        chk, getter = _check(stats)
        info = _Info("dut1", "eth1/32/1", "out_bytes.sum.60")
        with mock.patch(
            "taac.health_checks.snapshot_health_checks."
            "qos_dscp_tx_queue_health_check.async_get_device_driver",
            getter,
        ):
            out = await chk._queue_byte_counters("dut1", _In([info]))
        self.assertNotIn("eth1/32/1.queue6.icp.out_bytes.sum.60", out)
        self.assertIn("eth1/32/1.queue2.silver.out_bytes.sum.60", out)

    async def test_backend_queue_descs_are_honoured(self):
        stats = {"eth1/1/1": _Stats({0: 1, 2: 2, 6: 3})}
        chk, getter = _check(stats)
        info = _Info(
            "dut1",
            "eth1/1/1",
            "out_bytes.sum.60",
            queue_desc_list=["queue0.be", "queue2.rdma", "queue6.monitoring"],
        )
        with mock.patch(
            "taac.health_checks.snapshot_health_checks."
            "qos_dscp_tx_queue_health_check.async_get_device_driver",
            getter,
        ):
            out = await chk._queue_byte_counters("dut1", _In([info]))
        self.assertEqual(out["eth1/1/1.queue2.rdma.out_bytes.sum.60"], 2)
        self.assertEqual(out["eth1/1/1.queue0.be.out_bytes.sum.60"], 1)

    async def test_unreachable_agent_degrades_to_fb303_only(self):
        chk, getter = _check({}, raises=True)
        info = _Info("dut1", "eth1/32/1", "out_bytes.sum.60")
        with mock.patch(
            "taac.health_checks.snapshot_health_checks."
            "qos_dscp_tx_queue_health_check.async_get_device_driver",
            getter,
        ):
            out = await chk._queue_byte_counters("dut1", _In([info]))
        self.assertEqual(out, {})
        self.assertTrue(chk.logger.warning.called)

    def test_every_cos_desc_carries_a_parsable_queue_index(self):
        for desc in COS_QUEUE_FB303_COUNTER_DESC.values():
            self.assertIsNotNone(RE_QUEUE_INDEX.match(desc), desc)


if __name__ == "__main__":
    unittest.main()
