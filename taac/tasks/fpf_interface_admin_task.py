# Copyright (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

from __future__ import annotations

import asyncio
import typing as t

from taac.internal.driver.fboss_switch_internal import (
    FbossSwitchInternal,
)
from taac.tasks.base_task import BaseTask

_DEFAULT_INTERFACE_ADMIN_TIMEOUT_SEC = 30.0


class _InterfaceEnableTarget(t.TypedDict):
    device: str
    interfaces: list[str]


class FpfEnsureInterfacesEnabledTask(BaseTask):
    """Best-effort teardown guard for interfaces held down by an FPF test.

    Enabling an already-enabled interface is idempotent. The task verifies the
    admin-state readback and logs every failure, but deliberately does not raise:
    a failed safety attempt must not prevent the remaining TestConfig teardown
    tasks from withdrawing prefixes, stopping collectors, and stopping traffic.
    Each target's mutation plus readback is bounded by ``timeout_sec`` (30s by
    default) so an unreachable device cannot stall teardown indefinitely.
    """

    NAME = "fpf_ensure_interfaces_enabled"

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        raw_targets = params.get("targets")
        if not isinstance(raw_targets, list) or not raw_targets:
            self.logger.error(
                "[FpfEnsureInterfacesEnabled] best-effort teardown skipped: "
                "missing or empty targets"
            )
            return
        try:
            timeout_sec = float(
                params.get("timeout_sec", _DEFAULT_INTERFACE_ADMIN_TIMEOUT_SEC)
            )
        except (TypeError, ValueError):
            self.logger.error(
                "[FpfEnsureInterfacesEnabled] best-effort teardown skipped: "
                f"invalid timeout_sec {params.get('timeout_sec')!r}"
            )
            return
        if timeout_sec <= 0:
            self.logger.error(
                "[FpfEnsureInterfacesEnabled] best-effort teardown skipped: "
                f"timeout_sec must be positive, got {timeout_sec}"
            )
            return

        targets: t.List[_InterfaceEnableTarget] = []
        for raw_target in raw_targets:
            if not isinstance(raw_target, dict):
                self.logger.error(
                    "[FpfEnsureInterfacesEnabled] best-effort teardown skipped "
                    f"malformed target: {raw_target!r}"
                )
                continue
            device = raw_target.get("device")
            interfaces = raw_target.get("interfaces")
            if (
                not isinstance(device, str)
                or not device
                or not isinstance(interfaces, list)
                or not interfaces
                or not all(isinstance(interface, str) for interface in interfaces)
            ):
                self.logger.error(
                    "[FpfEnsureInterfacesEnabled] best-effort teardown skipped "
                    f"malformed target: {raw_target!r}"
                )
                continue
            targets.append({"device": device, "interfaces": interfaces})

        if not targets:
            return

        async def _enable(target: _InterfaceEnableTarget) -> None:
            device = target["device"]
            interfaces = target["interfaces"]

            driver = FbossSwitchInternal(hostname=device, logger=self.logger)
            await driver.async_thrift_disable_enable_interfaces(
                interface_names=interfaces,
                is_enable_port=True,
            )
            admin = await driver.async_get_all_interfaces_admin_status()
            not_enabled = [
                interface
                for interface in interfaces
                if interface not in admin or not bool(admin[interface])
            ]
            if not_enabled:
                raise RuntimeError(
                    f"admin enable readback failed on {device}: {not_enabled}"
                )
            self.logger.info(
                f"[FpfEnsureInterfacesEnabled] confirmed ENABLED on {device}: "
                f"{interfaces}"
            )

        results = await asyncio.gather(
            *(
                asyncio.wait_for(_enable(target), timeout=timeout_sec)
                for target in targets
            ),
            return_exceptions=True,
        )
        for target, result in zip(targets, results):
            if isinstance(result, BaseException):
                detail = str(result) or type(result).__name__
                self.logger.error(
                    "[FpfEnsureInterfacesEnabled] best-effort teardown failed for "
                    f"{target['device']}:{target['interfaces']}: {detail}"
                )
