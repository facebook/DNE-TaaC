# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe

from unittest.mock import AsyncMock, MagicMock, patch

import later.unittest
from taac.tasks.periodic_tasks import (
    _generate_plot,
    _process_lifetime_label,
    ProcessMonitorTask,
)

_MODULE = "neteng.test_infra.dne.taac.tasks.periodic_tasks"


class ProcessLifetimeLabelTest(later.unittest.TestCase):
    def test_bare_pid_is_labeled_as_pid(self) -> None:
        process_pid = "24236"

        self.assertEqual(
            f"PID {process_pid} — full monitored PID lifetime",
            _process_lifetime_label(process_pid),
        )


class ProcessMonitorPlotTest(later.unittest.TestCase):
    async def test_time_axis_includes_month_and_y_axis_starts_at_zero(self) -> None:
        axis = MagicMock()
        formatter = MagicMock()
        with (
            patch(f"{_MODULE}.MATPLOTLIB_AVAILABLE", True),
            patch(f"{_MODULE}.plt.figure"),
            patch(f"{_MODULE}.plt.plot"),
            patch(f"{_MODULE}.plt.axhline"),
            patch(f"{_MODULE}.plt.xlabel"),
            patch(f"{_MODULE}.plt.ylabel"),
            patch(f"{_MODULE}.plt.title"),
            patch(f"{_MODULE}.plt.grid"),
            patch(f"{_MODULE}.plt.gca", return_value=axis),
            patch(f"{_MODULE}.plt.ylim") as ylim,
            patch(f"{_MODULE}.plt.xticks"),
            patch(f"{_MODULE}.plt.legend"),
            patch(f"{_MODULE}.plt.tight_layout"),
            patch(f"{_MODULE}.plt.savefig"),
            patch(f"{_MODULE}.plt.close"),
            patch(f"{_MODULE}.mdates.DateFormatter", return_value=formatter) as date,
        ):
            path = await _generate_plot(
                data={1.0: 559.3},
                title="Stable RSS",
                ylabel="MB",
                output_path="/tmp/rss.png",
                y_axis_starts_at_zero=True,
            )

        self.assertEqual("/tmp/rss.png", path)
        date.assert_called_once_with("%b %d %H:%M")
        axis.xaxis.set_major_formatter.assert_called_once_with(formatter)
        ylim.assert_called_once_with(bottom=0)

    async def test_full_lifetime_plots_use_zero_baseline_and_clickable_urls(
        self,
    ) -> None:
        task = ProcessMonitorTask(hostname="bag010.ash6", logger=MagicMock())
        task._params.update({"enable_plotting": True})
        task.add_data(
            {
                "processes": {
                    "24236": {
                        "cmd": "bgpd_main",
                        "cpuPct": 200.0,
                        "residentMem": "572760",
                    }
                }
            },
            timestamp=1.0,
        )

        generate_plot = AsyncMock(side_effect=["/tmp/cpu.png", "/tmp/rss.png"])
        upload = AsyncMock(side_effect=["cpu-handle", "rss-handle"])
        with (
            patch(f"{_MODULE}._generate_plot", new=generate_plot),
            patch(f"{_MODULE}.async_everpaste_file", new=upload),
        ):
            result = await task.run_final_check()

        if result is None:
            raise AssertionError("process monitor final check returned no result")
        process_label = "bgpd_main PID 24236 — full monitored PID lifetime"
        self.assertIn(process_label, result.message)
        self.assertIn(
            "https://www.internalfb.com/intern/everpaste/?handle=cpu-handle",
            result.message,
        )
        self.assertIn(
            "https://www.internalfb.com/intern/everpaste/?handle=rss-handle",
            result.message,
        )
        self.assertEqual(2, generate_plot.await_count)
        for call in generate_plot.await_args_list:
            self.assertTrue(call.kwargs["y_axis_starts_at_zero"])
            self.assertIn(process_label, call.kwargs["title"])
        self.assertEqual(
            ["png", "png"],
            [call.kwargs["extension"] for call in upload.await_args_list],
        )
