# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-strict

import typing as t
from enum import Enum

from neteng.test_infra.dne.taac.constants import ARISTA_DAEMON_EXEC_SCRIPTS, BGP_PORT
from taac.tasks.all import AristaDaemonControlTask
from taac.tasks.base_task import BaseTask


class CaptureMode(Enum):
    """Capture modes."""

    START_CAPTURE = "start_capture"
    STOP_CAPTURE = "stop_capture"


class BgpTcpdumpTask(BaseTask):
    """BGP packet capture using existing daemon control infrastructure."""

    NAME = "bgp_tcpdump"
    DAEMON_NAME = "BgpTcpdump"

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        """
        Main entry point.
        params:
            - hostname: Device hostname
            - mode: Capture mode (start_capture/stop_capture)
            start_capture args:
            - interface: Interface to capture on (default: any)
            - bgp_port: BGP port to capture on (default: 179)
            - capture_file_path: Path to save the capture file (default: /tmp/bgp_capture.txt)
            - exec_script: Custom exec script to use (default: None)
            - message_type: Message type to capture (default: Update)
            stop_capture args:
            - capture_file_path: Captured file path
            - keep_capture_file: Keep capture file after stopping (default: True)

        """
        hostname = params.get("hostname") or self.hostname
        if not hostname:
            raise ValueError("hostname is required in params for BGP tcpdump task")

        self.hostname = hostname
        await self._setup()

        mode = params.get("mode", "start_capture")

        if mode == CaptureMode.START_CAPTURE.value:
            await self._start_capture(params)
        elif mode == CaptureMode.STOP_CAPTURE.value:
            await self._stop_capture(params)
        else:
            raise ValueError(f"Invalid mode: {mode}")

    async def _run_daemon_action(
        self, action: str, exec_script: t.Optional[str] = None
    ) -> None:
        """Run daemon action (enable/disable) with common setup."""
        daemon_task = AristaDaemonControlTask(hostname=self.hostname)
        daemon_task.logger = self.logger
        await daemon_task._setup()

        params = {
            "hostname": self.hostname,
            "daemon_name": self.DAEMON_NAME,
            "action": action,
        }

        if exec_script:
            params["exec_script"] = exec_script

        await daemon_task.run(params)

    async def _start_capture(self, params: t.Dict[str, t.Any]) -> t.Dict[str, t.Any]:
        """Start BGP capture using daemon control."""
        interface = params.get("interface", "any")
        bgp_port = params.get("bgp_port", BGP_PORT)
        capture_file = params.get("capture_file_path", "/tmp/bgp_capture.txt")
        custom_exec_script = params.get("exec_script")
        message_type = params.get("message_type", "Update")

        self.logger.info(
            f"Starting BGP capture daemon '{self.DAEMON_NAME}' on {self.hostname}"
        )

        # Kill any leftover tcpdump from a previous run before starting fresh
        await self.driver().async_execute_show_or_configure_cmd_on_shell(
            "bash sudo pkill -9 tcpdump || true"
        )

        # Clean up any existing capture file
        await self.driver().async_execute_show_or_configure_cmd_on_shell(
            f"bash sudo rm -f {capture_file}"
        )

        # Use custom exec script if provided, otherwise create from template
        if custom_exec_script:
            exec_script = custom_exec_script
            self.logger.info(f"Using custom exec script: {exec_script}")
        else:
            exec_script = ARISTA_DAEMON_EXEC_SCRIPTS[self.DAEMON_NAME].format(
                interface=interface,
                bgp_port=bgp_port,
                message_type=message_type,
                capture_file=capture_file,
            )

        # Enable daemon using common helper
        await self._run_daemon_action("enable", exec_script)

        self.logger.info(
            f"BGP capture daemon '{self.DAEMON_NAME}' started successfully"
        )
        return {"daemon_name": self.DAEMON_NAME, "capture_file": capture_file}

    async def _stop_capture(self, params: t.Dict[str, t.Any]) -> t.Dict[str, t.Any]:
        """Stop BGP capture daemon."""
        capture_file = params.get("capture_file_path", "/tmp/bgp_capture.txt")
        keep_capture = params.get("keep_capture_file", True)

        self.logger.info(
            f"Stopping BGP capture daemon '{self.DAEMON_NAME}' on {self.hostname}"
        )

        # Disable daemon using common helper
        await self._run_daemon_action("disable")
        await self.driver().async_execute_show_or_configure_cmd_on_shell(
            "bash sudo pkill -9 tcpdump"
        )

        if not keep_capture:
            await self.driver().async_execute_show_or_configure_cmd_on_shell(
                f"bash rm -f {capture_file}"
            )
            self.logger.info("BGP capture stopped and capture file cleaned up")
            capture_file = None
        else:
            self.logger.info(f"BGP capture stopped, capture saved to {capture_file}")

        return {
            "capture_file_path": capture_file,
            "hostname": self.hostname,
        }
