# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""RBB SRv6 verification task.

Runs a device ``show`` command and asserts expected substrings are present
and/or absent, raising ``TestCaseFailure`` (a FAIL verdict, not an ERROR) on
mismatch. Used for the SRv6-specific stage gates that have no shipped
``CheckName`` health check:

- S10  PC162 global IPv6 present
- S11  SRv6 tunnels programmed
- S22-S23  tail prefix owned by TE_AGENT with the expected decap SID
- S26  SRv6 encap/decap counter deltas present
- S28  after direct-route delete, prefix owned by BGPD (not TE_AGENT)

Verification is a registered Task (not a new health-check class) on purpose:
adding a ``CheckName`` enum value is a Thrift change that must be regenerated
and coordinated with a maintainer (§11). This keeps the OSS slice importable
and schema-stable while staying factory-built (§5.1).
"""

import typing as t

from taac.constants import TestCaseFailure
from taac.tasks.base_task import BaseTask
from taac.utils.driver_factory import async_get_device_driver
from taac.utils.oss_taac_lib_utils import ConsoleFileLogger


class RbbSrv6VerifyTask(BaseTask):
    """Assert expected substrings in a device show-command output."""

    # pyrefly: ignore [bad-override-mutable-attribute]
    NAME: str = "rbb_srv6_verify"

    def __init__(
        self,
        hostname: t.Optional[str] = None,
        description: t.Optional[str] = None,
        ixia: t.Optional[t.Any] = None,
        logger: t.Optional[ConsoleFileLogger] = None,
        shared_data: t.Optional[t.Dict[t.Any, t.Any]] = None,
    ) -> None:
        super().__init__(hostname, description, ixia, logger, shared_data)

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        """Run ``show_cmd`` and assert content.

        params:
            hostname: DUT to query (required).
            show_cmd: command whose stdout is inspected (required).
            expect_contains: substrings that MUST all appear (optional).
            expect_absent: substrings that must NOT appear (optional).
            gate: human-readable gate label for logs/failure (optional).
        """
        hostname = params.get("hostname") or self.hostname
        if not hostname:
            raise ValueError("rbb_srv6_verify requires 'hostname'")
        show_cmd = params.get("show_cmd")
        if not show_cmd:
            raise ValueError("rbb_srv6_verify requires 'show_cmd'")
        expect_contains: t.List[str] = params.get("expect_contains", [])
        expect_absent: t.List[str] = params.get("expect_absent", [])
        gate = params.get("gate", "rbb_srv6_verify")

        driver = await async_get_device_driver(hostname)
        self.logger.info(f"{hostname} -- [{gate}] verify: {show_cmd}")
        output = await driver.async_run_cmd_on_shell(show_cmd) or ""

        missing = [s for s in expect_contains if s not in output]
        unexpected = [s for s in expect_absent if s in output]

        if missing or unexpected:
            raise TestCaseFailure(
                f"[{gate}] SRv6 verification failed on {hostname} "
                f"(cmd={show_cmd!r}): missing={missing} unexpected_present={unexpected}"
            )
        self.logger.info(f"{hostname} -- [{gate}] verification passed")
