# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

import unittest

from taac.internal.tasks.openr_scale_cold_boot_monitor import (
    CPU_COUNTER,
    OpenRScaleColdBootMonitor,
    QUEUE_DRAIN_COUNTER,
    QUEUE_DRAIN_SECONDS_COUNTER,
    QUEUE_MAX_COUNTER,
    RSS_COUNTER,
)


GATES = [
    {"counter": QUEUE_MAX_COUNTER, "threshold": 10_000},
    {"counter": QUEUE_DRAIN_COUNTER, "threshold": 100},
    {"counter": QUEUE_DRAIN_SECONDS_COUNTER, "threshold": 60},
    {"counter": RSS_COUNTER, "threshold": 2 * 1024**3},
    {"counter": CPU_COUNTER, "threshold": 80},
]


def _sample(
    timestamp: float,
    uptime: float,
    queue: float = 0,
    cpu: float = 10,
) -> dict:
    return {
        "timestamp": timestamp,
        "ok": True,
        "uptime": uptime,
        "rss": 1024,
        "cpu": cpu,
        "queues": {
            "messaging.rw_queue.test": queue,
            "watchdog.evb_queue_size.test": queue,
            "kvstore.ttl_countdown_queue_size.test": queue,
        },
    }


class OpenRScaleColdBootMonitorTest(unittest.TestCase):
    def test_passes_two_reset_downtimes_and_sixty_drained_samples(self) -> None:
        samples = [_sample(0, 100), _sample(1, 101)]
        samples.append(
            {"timestamp": 2, "ok": False, "kind": "unavailable", "error": "down"}
        )
        samples.extend([_sample(3, 1), _sample(4, 2)])
        samples.append(
            {"timestamp": 5, "ok": False, "kind": "unavailable", "error": "down"}
        )
        samples.extend(_sample(6 + index, 1 + index) for index in range(60))
        failures, summary = OpenRScaleColdBootMonitor.evaluate_samples(samples, GATES)
        self.assertEqual([], failures)
        self.assertEqual(2, summary["uptime_resets"])
        self.assertEqual(60, summary["post_reboot_samples"])

    def test_fails_queue_peak_and_drain(self) -> None:
        samples = [_sample(0, 100)]
        samples.append(
            {"timestamp": 1, "ok": False, "kind": "unavailable", "error": "down"}
        )
        samples.extend([_sample(2, 1), _sample(3, 2)])
        samples.append(
            {"timestamp": 4, "ok": False, "kind": "unavailable", "error": "down"}
        )
        samples.extend(_sample(5 + index, 1 + index, queue=101) for index in range(60))
        samples[10]["queues"]["messaging.rw_queue.test"] = 10_001
        failures, _ = OpenRScaleColdBootMonitor.evaluate_samples(samples, GATES)
        self.assertTrue(any("maximum queue depth" in failure for failure in failures))
        self.assertTrue(any("did not remain below" in failure for failure in failures))

    def test_fails_missing_telemetry_outside_restart(self) -> None:
        samples = [
            _sample(0, 100),
            {"timestamp": 1, "ok": False, "kind": "unavailable", "error": "down"},
            _sample(2, 1),
            {"timestamp": 3, "ok": False, "kind": "telemetry", "error": "missing"},
            _sample(4, 2),
            {"timestamp": 5, "ok": False, "kind": "unavailable", "error": "down"},
        ]
        samples.extend(_sample(6 + index, 1 + index) for index in range(60))
        failures, _ = OpenRScaleColdBootMonitor.evaluate_samples(samples, GATES)
        self.assertTrue(any("incomplete outside" in failure for failure in failures))

    def test_fails_extra_restart(self) -> None:
        samples = [_sample(0, 100)]
        samples.append(
            {"timestamp": 1, "ok": False, "kind": "unavailable", "error": "down"}
        )
        samples.extend([_sample(2, 1), _sample(3, 2)])
        samples.append(
            {"timestamp": 4, "ok": False, "kind": "unavailable", "error": "down"}
        )
        samples.extend([_sample(5, 1), _sample(6, 2), _sample(7, 1)])
        failures, _ = OpenRScaleColdBootMonitor.evaluate_samples(samples, GATES)
        self.assertTrue(any("exactly 2" in failure for failure in failures))

    def test_fails_without_sampled_downtime(self) -> None:
        samples = [_sample(0, 100)]
        samples.extend([_sample(1, 1), _sample(2, 0)])
        samples.extend(_sample(3 + index, 1 + index) for index in range(60))
        failures, _ = OpenRScaleColdBootMonitor.evaluate_samples(samples, GATES)
        self.assertTrue(any("downtime transition" in failure for failure in failures))

    def test_ignores_cpu_spike_before_stabilized_window(self) -> None:
        samples = [_sample(0, 100)]
        samples.append(
            {"timestamp": 1, "ok": False, "kind": "unavailable", "error": "down"}
        )
        samples.extend([_sample(2, 1), _sample(3, 2)])
        samples.append(
            {"timestamp": 4, "ok": False, "kind": "unavailable", "error": "down"}
        )
        samples.append(_sample(5, 1, cpu=99))
        samples.extend(_sample(6 + index, 2 + index) for index in range(120))

        failures, summary = OpenRScaleColdBootMonitor.evaluate_samples(samples, GATES)

        self.assertEqual([], failures)
        self.assertEqual(10, summary["max_stabilized_cpu_pct_avg_60"])

    def test_fails_cpu_spike_in_stabilized_window(self) -> None:
        samples = [_sample(0, 100)]
        samples.append(
            {"timestamp": 1, "ok": False, "kind": "unavailable", "error": "down"}
        )
        samples.extend([_sample(2, 1), _sample(3, 2)])
        samples.append(
            {"timestamp": 4, "ok": False, "kind": "unavailable", "error": "down"}
        )
        samples.extend(_sample(5 + index, 1 + index) for index in range(120))
        samples[-1]["cpu"] = 99

        failures, _ = OpenRScaleColdBootMonitor.evaluate_samples(samples, GATES)

        self.assertTrue(any("post-boot CPU 99 exceeds 80" in item for item in failures))
