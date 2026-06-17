# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
"""TAAC Task: full host reboot of a network device (or any SSH-reachable Linux host).

Issues `sudo systemctl reboot` over SSH to a hostname, then waits for the host
to become SSH-unreachable (confirming the reboot took effect) and waits for it
to come back up. Built for Phase 4-1 TC5 "U-server reboot" — which in the bash
harness rebootss the DUT switch as a Linux host (not a separate paired server).

The Task is generic over any SSH-reachable host: it bypasses the TAAC switch
driver factory by talking to `ParamikoClient(hostname)` directly. This makes it
usable for both DUT switch reboots and any non-topology host that needs the
same issue → wait-down → wait-up lifecycle.
"""

import asyncio
import time
import typing as t

import paramiko
from neteng.netcastle.utils.paramiko_utils import ParamikoClient
from taac.tasks.base_task import BaseTask
from taac.utils.oss_driver_utils import (
    is_host_ssh_reachable,
    wait_for_ssh_reachable,
)


_DEFAULT_REBOOT_CMD = "sudo systemctl reboot"
_DEFAULT_TIMEOUT_S = 600
_DEFAULT_DOWN_POLL_S = 5
_DEFAULT_DOWN_MAX_S = 120

# Expected exception types when the reboot causes the SSH channel to drop
# mid-command. Narrower than a bare `Exception` so genuine bugs (e.g.,
# AttributeError, programming errors) still surface.
_EXPECTED_POST_REBOOT_EXCEPTIONS = (
    ConnectionError,
    EOFError,
    OSError,  # also covers socket.error
    paramiko.SSHException,
)


class FullRebootTask(BaseTask):
    """Reboot a host via SSH and wait for it to come back up.

    Parameters (via `params` dict):
        hostname: FQDN of the host to reboot. Required.
        reboot_cmd: Override the default `sudo systemctl reboot`. Optional.
        ssh_user: SSH username. Optional; falls back to the default identity.
        ssh_password: SSH password if not using key auth. Optional.
        down_max_s: Max seconds to wait for host to go down. Default 120.
        up_max_s: Max seconds to wait for host to come back. Default 600.
    """

    NAME = "full_reboot"

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        hostname = params["hostname"]
        reboot_cmd = params.get("reboot_cmd", _DEFAULT_REBOOT_CMD)
        ssh_user = params.get("ssh_user")
        ssh_password = params.get("ssh_password")
        down_max_s = int(params.get("down_max_s", _DEFAULT_DOWN_MAX_S))
        up_max_s = int(params.get("up_max_s", _DEFAULT_TIMEOUT_S))

        self.logger.info(f"[full_reboot] issuing reboot on {hostname}")

        # SSH connect must succeed — if it doesn't, the host wasn't reachable
        # in the first place and we have nothing to validate. Let it raise.
        # All paramiko calls are sync/blocking; offload to a thread so the
        # asyncio event loop stays responsive (matters when multiple Tasks run
        # concurrently in a playbook).
        client = ParamikoClient(
            hostname,
            username=ssh_user,
            password=ssh_password,
        )
        # Wrap the bound methods in lambdas so Pyre sees a single callable type
        # rather than the Union returned by `ParamikoClient(...)` (which can be
        # either AsyncSSHClient or ParamikoClientLegacy).
        await asyncio.to_thread(lambda: client.connect())
        # ParamikoClient.run is sync — by the time the call returns the box
        # has typically already started rebooting and the channel hangs up,
        # which manifests as an exception. Catch THAT specifically and treat
        # as success. Always disconnect (in `finally`) to avoid leaking the
        # paramiko channel if the run raises a non-expected exception.
        try:
            await asyncio.to_thread(lambda: client.run(reboot_cmd))
        except _EXPECTED_POST_REBOOT_EXCEPTIONS as e:
            self.logger.info(
                f"[full_reboot] reboot cmd raised "
                f"{type(e).__name__} (expected post-reboot): {e!r}"
            )
        finally:
            try:
                await asyncio.to_thread(lambda: client.disconnect())
            except _EXPECTED_POST_REBOOT_EXCEPTIONS:
                # Disconnect after a half-closed channel can itself raise;
                # the channel is dead anyway.
                pass

        # Phase 2: wait for the host to actually go down. This guards against
        # the case where the reboot cmd succeeded but the box never restarted —
        # without this check, the up-wait would immediately succeed on the
        # still-running pre-reboot box and we'd never know.
        self.logger.info(
            f"[full_reboot] waiting up to {down_max_s}s for {hostname} "
            f"to become SSH-unreachable"
        )
        down_at = await self._wait_for_unreachable(
            hostname, ssh_user, ssh_password, down_max_s, _DEFAULT_DOWN_POLL_S
        )
        if down_at is None:
            raise TimeoutError(
                f"[full_reboot] {hostname} did not become SSH-unreachable "
                f"within {down_max_s}s — reboot may not have taken effect"
            )
        self.logger.info(
            f"[full_reboot] {hostname} unreachable after "
            f"{down_at:.0f}s; waiting for it to come back"
        )

        # Phase 3: wait for it to come back up. Note: `wait_for_ssh_reachable`
        # does not accept a `username` kwarg (helper limitation); the SSH probe
        # uses the default identity, which is fine for lab DUTs and the typical
        # `ssh_user` overrides used by Phase 4-1 playbooks. The helper itself
        # is synchronous — offload to a thread to avoid blocking the loop for
        # up to `up_max_s` (default 600s).
        await asyncio.to_thread(
            wait_for_ssh_reachable,
            ssh_entity=hostname,
            max_duration=up_max_s,
            password=ssh_password,
        )
        self.logger.info(f"[full_reboot] {hostname} back up")

    @staticmethod
    async def _wait_for_unreachable(
        hostname: str,
        username: t.Optional[str],
        password: t.Optional[str],
        max_s: int,
        poll_s: int,
    ) -> t.Optional[float]:
        """Poll until host stops responding to SSH. Returns elapsed seconds or None.

        Async-friendly: the per-probe `is_host_ssh_reachable` call is offloaded
        to a thread (sync SSH connect under the hood) and the inter-poll wait
        uses `asyncio.sleep` so the event loop stays responsive.
        """
        start = time.monotonic()
        while time.monotonic() - start < max_s:
            reachable = await asyncio.to_thread(
                is_host_ssh_reachable, hostname, username=username, password=password
            )
            if not reachable:
                return time.monotonic() - start
            await asyncio.sleep(poll_s)
        return None
