# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
import time
import typing as t
import unittest
from unittest.mock import AsyncMock, MagicMock

from taac.libs.collectors.service_polling_collector import (
    ServicePollingCollector,
    UNAVAILABLE_COUNTER_VALUE,
)


class StubCollector(ServicePollingCollector):
    """Minimal concrete subclass for testing the base class."""

    def _systemd_properties(self) -> t.List[str]:
        return ["LoadState", "ActiveState", "MyCounter"]

    def _extract_value(
        self, unit_data: t.Dict[str, str], service: str
    ) -> t.Optional[int]:
        val = unit_data.get("MyCounter", "")
        if not val.isdigit():
            return None
        return int(val)


def _units_in(cmd: str) -> t.List[str]:
    return cmd.split("systemctl show ", 1)[1].split(" -p ")[0].split()


def _make_driver(responses: t.Dict[str, str]) -> MagicMock:
    """Driver whose async_run_cmd_on_shell returns one blank-line-separated
    ``systemctl show`` block per unit named in the (single, batched) command,
    matching real ``systemctl show unit1 unit2 ...`` output — including the
    ``Id`` property, which is how blocks are matched back to their unit."""
    driver = MagicMock()

    async def _run(cmd: str) -> str:
        blocks = [
            f"Id={unit}.service\n"
            + responses.get(unit, "LoadState=not-found\nActiveState=inactive")
            for unit in _units_in(cmd)
        ]
        return "\n\n".join(blocks)

    driver.async_run_cmd_on_shell = AsyncMock(side_effect=_run)
    return driver


LOADED_ACTIVE = "LoadState=loaded\nActiveState=active\nMyCounter={value}"
NOT_LOADED = "LoadState=not-found\nActiveState=inactive\nMyCounter="


class TestServicePollingCollector(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.driver = _make_driver(
            {
                "svcA": LOADED_ACTIVE.format(value="100"),
                "svcB": LOADED_ACTIVE.format(value="200"),
            }
        )
        self.collector = StubCollector(
            driver=self.driver,
            services=["svcA", "svcB"],
            host="dut1",
            tmp_path="/dev/null",
        )

    async def test_poll_once_stores_row(self) -> None:
        await self.collector._poll_once()
        self.assertEqual(len(self.collector.rows), 1)
        row = self.collector.rows[0]
        self.assertEqual(row.per_service["svcA"], 100)
        self.assertEqual(row.per_service["svcB"], 200)

    async def test_poll_not_loaded_produces_none(self) -> None:
        self.driver = _make_driver({"svcA": NOT_LOADED, "svcB": NOT_LOADED})
        self.collector = StubCollector(
            driver=self.driver,
            services=["svcA", "svcB"],
            host="dut1",
            tmp_path="/dev/null",
        )
        await self.collector._poll_once()
        row = self.collector.rows[0]
        self.assertIsNone(row.per_service["svcA"])
        self.assertIsNone(row.per_service["svcB"])

    async def test_max_per_service_in_window(self) -> None:
        now = time.time()
        self.driver = _make_driver(
            {
                "svcA": LOADED_ACTIVE.format(value="100"),
                "svcB": LOADED_ACTIVE.format(value="50"),
            }
        )
        self.collector = StubCollector(
            driver=self.driver,
            services=["svcA", "svcB"],
            host="dut1",
            tmp_path="/dev/null",
        )
        await self.collector._poll_once()

        self.collector.driver = _make_driver(
            {
                "svcA": LOADED_ACTIVE.format(value="300"),
                "svcB": LOADED_ACTIVE.format(value="50"),
            }
        )
        await self.collector._poll_once()

        result = self.collector.max_per_service_in_window(now - 10, now + 10)
        self.assertEqual(result["svcA"], 300)
        self.assertEqual(result["svcB"], 50)

    async def test_samples_per_service_in_window(self) -> None:
        now = time.time()
        await self.collector._poll_once()

        self.collector.driver = _make_driver(
            {
                "svcA": LOADED_ACTIVE.format(value="150"),
                "svcB": LOADED_ACTIVE.format(value="250"),
            }
        )
        await self.collector._poll_once()

        result = self.collector.samples_per_service_in_window(now - 10, now + 10)
        self.assertEqual(result["svcA"], [100, 150])
        self.assertEqual(result["svcB"], [200, 250])

    async def test_service_absent_from_window_omitted(self) -> None:
        now = time.time()
        self.driver = _make_driver(
            {"svcA": LOADED_ACTIVE.format(value="100"), "svcB": NOT_LOADED}
        )
        self.collector = StubCollector(
            driver=self.driver,
            services=["svcA", "svcB"],
            host="dut1",
            tmp_path="/dev/null",
        )
        await self.collector._poll_once()
        result = self.collector.max_per_service_in_window(now - 10, now + 10)
        self.assertIn("svcA", result)
        self.assertNotIn("svcB", result)

    async def test_poll_once_issues_a_single_batched_ssh_call(self) -> None:
        """Regardless of service count, one poll cycle must be one SSH call --
        a per-service round trip doesn't scale and was observed to trip
        sshd's MaxStartups under sustained polling."""
        self.collector.services = ["svcA", "svcB", "svcC"]
        self.driver = _make_driver(
            {
                "svcA": LOADED_ACTIVE.format(value="1"),
                "svcB": LOADED_ACTIVE.format(value="2"),
                "svcC": LOADED_ACTIVE.format(value="3"),
            }
        )
        self.collector.driver = self.driver
        await self.collector._poll_once()
        self.assertEqual(self.driver.async_run_cmd_on_shell.call_count, 1)
        row = self.collector.rows[0]
        self.assertEqual(row.per_service["svcA"], 1)
        self.assertEqual(row.per_service["svcB"], 2)
        self.assertEqual(row.per_service["svcC"], 3)

    async def test_ssh_error_marks_all_services_unmeasurable(self) -> None:
        self.driver.async_run_cmd_on_shell = AsyncMock(
            side_effect=RuntimeError("SSH timeout")
        )
        await self.collector._poll_once()
        row = self.collector.rows[0]
        self.assertIsNone(row.per_service["svcA"])
        self.assertIsNone(row.per_service["svcB"])
        self.assertIn("svcA=ssh-error", row.notes)
        self.assertIn("svcB=ssh-error", row.notes)

    def test_parse_counter_rejects_unusable_values(self) -> None:
        """A cumulative counter is only a real sample when it's numeric and not
        systemd's UINT64_MAX "unset" sentinel -- which is numeric, so it would
        otherwise sail through as an enormous, guaranteed-FAIL max."""
        parse = ServicePollingCollector._parse_counter
        self.assertEqual(parse("12345"), 12345)
        self.assertIsNone(parse(""))
        self.assertIsNone(parse("[not set]"))
        self.assertIsNone(parse(str(UNAVAILABLE_COUNTER_VALUE)))

    async def test_batched_command_always_requests_id(self) -> None:
        """``Id`` must be requested regardless of what the subclass declares --
        it's what lets each output block be matched back to its unit."""
        await self.collector._poll_once()
        cmd = self.driver.async_run_cmd_on_shell.call_args[0][0]
        self.assertIn("-p Id,LoadState,ActiveState,MyCounter", cmd)

    async def test_blocks_matched_by_id_not_by_position(self) -> None:
        """Blocks must be attributed by their Id. systemd returns them in the
        order asked for, but relying on that means any shift silently reports
        one service's counter as another's."""

        async def _reversed_order(cmd: str) -> str:
            blocks = [
                f"Id={unit}.service\n" + LOADED_ACTIVE.format(value=value)
                for unit, value in [("svcB", "200"), ("svcA", "100")]
            ]
            return "\n\n".join(blocks)

        self.driver.async_run_cmd_on_shell = AsyncMock(side_effect=_reversed_order)
        await self.collector._poll_once()
        row = self.collector.rows[0]
        self.assertEqual(row.per_service["svcA"], 100)
        self.assertEqual(row.per_service["svcB"], 200)

    async def test_none_output_degrades_to_ssh_error(self) -> None:
        """A driver may return None instead of raising (OSS FbossSwitch's
        `result.stdout if result else None`). That must still produce a row
        with per-service notes, not an AttributeError that _run_loop swallows
        into an unexplained gap."""
        self.driver.async_run_cmd_on_shell = AsyncMock(return_value=None)
        await self.collector._poll_once()
        self.assertEqual(len(self.collector.rows), 1)
        row = self.collector.rows[0]
        self.assertIsNone(row.per_service["svcA"])
        self.assertIn("svcA=ssh-error", row.notes)
        self.assertIn("svcB=ssh-error", row.notes)

    def test_parse_blocks_normalizes_crlf(self) -> None:
        """A PTY-backed transport yields \\r\\n, which would otherwise collapse
        the output into one block and fail every Id lookup."""
        output = (
            "Id=svcA.service\r\nMyCounter=100\r\n"
            "\r\n"
            "Id=svcB.service\r\nMyCounter=200\r\n"
        )
        blocks = ServicePollingCollector._parse_blocks_by_unit(output)
        self.assertEqual(set(blocks), {"svcA.service", "svcB.service"})
        self.assertEqual(blocks["svcB.service"]["MyCounter"], "200")

    def test_parse_blocks_skips_block_without_id(self) -> None:
        """A block carrying no Id (shell banner, warning line) isn't indexed, so
        it can neither shadow a real unit nor shift the ones after it -- which
        is what it would do if blocks were matched by position."""
        output = "\n\n".join(
            [
                "Warning: something unrelated",
                "Id=svcA.service\nMyCounter=100",
                "Id=svcB.service\nMyCounter=200",
            ]
        )
        blocks = ServicePollingCollector._parse_blocks_by_unit(output)
        self.assertEqual(set(blocks), {"svcA.service", "svcB.service"})
        self.assertEqual(blocks["svcA.service"]["MyCounter"], "100")

    async def test_unit_missing_from_output_is_ssh_error(self) -> None:
        """A truncated read says nothing about the service, so it must not be
        recorded as a measured 'not measurable' sample."""

        async def _only_svc_a(cmd: str) -> str:
            return "Id=svcA.service\n" + LOADED_ACTIVE.format(value="100")

        self.driver.async_run_cmd_on_shell = AsyncMock(side_effect=_only_svc_a)
        await self.collector._poll_once()
        row = self.collector.rows[0]
        self.assertEqual(row.per_service["svcA"], 100)
        self.assertIsNone(row.per_service["svcB"])
        self.assertIn("svcB=ssh-error", row.notes)
        self.assertNotIn("svcA=ssh-error", row.notes)

    async def test_unsuffixed_id_matches_requested_service(self) -> None:
        """Some unit types report Id without a '.service' suffix."""

        async def _unsuffixed(cmd: str) -> str:
            blocks = [
                f"Id={unit}\n" + LOADED_ACTIVE.format(value=value)
                for unit, value in [("svcA", "100"), ("svcB", "200")]
            ]
            return "\n\n".join(blocks)

        self.driver.async_run_cmd_on_shell = AsyncMock(side_effect=_unsuffixed)
        await self.collector._poll_once()
        row = self.collector.rows[0]
        self.assertEqual(row.per_service["svcA"], 100)
        self.assertEqual(row.per_service["svcB"], 200)

    async def test_get_rows_in_window_uses_row_epoch(self) -> None:
        """Windowing must key off the row's exact epoch, not a re-parse of the
        formatted timestamp string (which can silently drop rows)."""
        await self.collector._poll_once()
        row = self.collector.rows[0]
        row.timestamp = "not-a-parseable-timestamp"
        result = self.collector.max_per_service_in_window(row.epoch - 1, row.epoch + 1)
        self.assertEqual(result["svcA"], 100)


if __name__ == "__main__":
    unittest.main()
