# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

"""
TAAC task that generates a device's live and soft-drain BGP configs.

Wraps ``config_modifiers.setup_base_configs``: reads the device's current BGP
config, replaces whatever policies it had with the three generalized propagate
policies, and writes back a live copy and a soft-drain copy that differ only in
their egress policy and drain state. Leaves the device undrained.

Run this before any drain/undrain in the same test -- ``drain_device`` and
``undrain_device`` only select between the two files this produces, and fail if
they are missing.

Idempotent: running it twice produces the same two files, because the transform
rewrites the policy section wholesale rather than appending to it.

Usage in test configs::

    Task(
        task_name="setup_base_configs",
        hostname="<device>",
        params=Params(json_params=json.dumps({"restart_bgp": True})),
    )

Params (all optional):
    hostname:     device to configure. Overrides ``Task.hostname``; one of the
                  two must be set.
    restart_bgp:  restart bgpd so the live config takes effect (default True).
                  False stages both files without disturbing a running session,
                  for batching several changes before one restart.

FBOSS-only, and OSS-only in practice. The underlying driver call rejects
non-FBOSS drivers, and on a Meta-internal device COOP owns
``/etc/coop/bgpcpp/current`` and will re-materialize its own version over
anything written here.
"""

import typing as t

from taac.driver.config_modifiers import setup_base_configs
from taac.tasks.base_task import BaseTask
from taac.utils.driver_factory import async_get_device_driver


class SetupBaseConfigsTask(BaseTask):
    """Generate the live and soft-drain BGP configs on a device."""

    NAME = "setup_base_configs"

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        hostname = params.get("hostname") or self.hostname
        if not hostname:
            raise ValueError(
                "setup_base_configs requires a hostname, either on the Task or "
                "in params. It configures one specific device."
            )

        restart_bgp = params.get("restart_bgp", True)

        self.logger.info(
            f"Generating base BGP configs on {hostname} (restart_bgp={restart_bgp})"
        )
        driver = await async_get_device_driver(hostname)
        await setup_base_configs(driver, restart_bgp=restart_bgp)
        self.logger.info(
            f"{hostname}: live and soft-drain configs written; device left undrained"
        )
