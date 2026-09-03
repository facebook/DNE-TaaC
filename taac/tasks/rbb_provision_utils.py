# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""Shared helpers for the RBB from-scratch FBOSS provisioning tasks.

Common, side-effecting glue the three ``provision_fboss_*`` tasks reuse: the
MORGAN800CC / asicType-15 hardware guard, an idempotent back-up-before-overwrite
that preserves the box's pristine original once, and the plan builder that turns
the run's topology + ``TAAC_RBB_*`` env into the per-DUT ``NodePlan``.

Everything is opt-in and reversible: the first provision of a file copies it to
``<path>.taac-orig`` (never overwritten again), so a later restore is a plain
copy-back. Nothing here runs unless a ``provision_fboss_*`` task is scheduled.
"""

from __future__ import annotations

import json
import typing as t

from taac.constants import TestCaseFailure
from taac.testconfigs.routing.util import bgp_rbb_constants as C
from taac.testconfigs.routing.util.bgp_rbb_topology import load_rbb_topology
from taac.testconfigs.routing.util.fboss_config_gen.platform_mapping import (
    parse_platform_mapping,
    PortEntry,
)
from taac.testconfigs.routing.util.fboss_config_gen.provision_plan import (
    build_rbb_provision_plan,
    NodePlan,
)

BACKUP_SUFFIX: str = ".taac-orig"


async def async_read_file_or_none(driver: t.Any, path: str) -> t.Optional[str]:
    """Return the file contents, or ``None`` if it does not exist on the box."""
    try:
        if not await driver.async_check_if_file_exists(path):
            return None
    except Exception:  # noqa: BLE001 — fall through to a best-effort read
        pass
    try:
        return await driver.async_read_file(path)
    except Exception:  # noqa: BLE001
        return None


async def async_read_agent_asic_type(
    driver: t.Any, agent_conf: t.Optional[t.Mapping[str, t.Any]] = None
) -> t.Optional[int]:
    """Read the DUT's asicType from ``switchSettings`` (None if undeterminable)."""
    if agent_conf is None:
        raw = await async_read_file_or_none(driver, C.AGENT_CONFIG_PATH)
        if not raw:
            return None
        try:
            agent_conf = json.loads(raw)
        except json.JSONDecodeError:
            return None
    ss = (agent_conf.get("sw") or {}).get("switchSettings") or {}
    info = ss.get("switchIdToSwitchInfo") or {}
    for sinfo in info.values():
        if isinstance(sinfo, dict) and "asicType" in sinfo:
            return int(sinfo["asicType"])
    return None


async def guard_hardware(
    driver: t.Any,
    hostname: str,
    logger: t.Any,
    agent_conf: t.Optional[t.Mapping[str, t.Any]] = None,
) -> None:
    """Hard-fail unless the DUT is the supported asicType (MORGAN800CC = 15).

    Provisioning writes a MORGAN800CC-shaped SwitchConfig; running it against any
    other platform would push an incompatible config, so refuse rather than risk
    bricking an unexpected box.
    """
    asic = await async_read_agent_asic_type(driver, agent_conf)
    if asic is None:
        raise TestCaseFailure(
            f"{hostname}: cannot confirm hardware (no readable {C.AGENT_CONFIG_PATH} "
            f"asicType); RBB provisioning refuses to run on an unverified platform."
        )
    if asic != C.PROVISION_ASIC_TYPE:
        raise TestCaseFailure(
            f"{hostname}: asicType {asic} is not the supported "
            f"{C.PROVISION_ASIC_TYPE} ({', '.join(C.PROVISION_HARDWARE_ALLOWLIST)}); "
            f"RBB provisioning is guarded to that hardware only."
        )
    logger.info(f"{hostname} -- hardware guard OK (asicType {asic})")


async def async_backup_before_overwrite(
    driver: t.Any, path: str, logger: t.Any, hostname: str, force: bool
) -> bool:
    """Idempotent backup. Returns True to proceed with the write, False to skip.

    * If a ``<path>.taac-orig`` backup already exists and ``force`` is False, the
      file was provisioned before -> skip (idempotent).
    * Otherwise, if the current file exists, copy it to the backup (only when the
      backup is absent, to preserve the pristine original), then proceed.
    """
    backup = path + BACKUP_SUFFIX
    backup_exists = False
    try:
        backup_exists = await driver.async_check_if_file_exists(backup)
    except Exception:  # noqa: BLE001
        backup_exists = False

    if backup_exists and not force:
        logger.info(
            f"{hostname} -- {path}: backup {backup} present and force=False; "
            f"skipping (already provisioned)."
        )
        return False

    current = await async_read_file_or_none(driver, path)
    if current is not None and not backup_exists:
        await driver.async_write_file_on_device(current, backup)
        logger.info(f"{hostname} -- backed up {path} -> {backup}")
    return True


async def async_resolve_platform_mapping_path(driver: t.Any) -> str:
    """Resolve the on-box platform-mapping file path for THIS image.

    The MORGAN800CC ``MetaGeneratedPlatformMapping_<date>.json`` filename is
    image-build-specific, so it is discovered on the DUT rather than hardcoded.
    Precedence:

    1. ``TAAC_RBB_PLATFORM_MAPPING_PATH`` (``C.PLATFORM_MAPPING_PATH``) — an
       explicit file path is used verbatim, skipping the device glob.
    2. Device glob of ``C.PLATFORM_MAPPING_DIR`` (``TAAC_RBB_PLATFORM_MAPPING_DIR``,
       default ``/opt/fboss/share``) for ``MetaGeneratedPlatformMapping*.json``,
       picking the newest/lexically-last match
       (``ls -1 <dir>/<glob> | sort | tail -1`` via the driver shell).
    3. ``C.PLATFORM_MAPPING_FALLBACK_PATH`` if the glob matches nothing.
    """
    if C.PLATFORM_MAPPING_PATH:
        return C.PLATFORM_MAPPING_PATH

    mapping_dir = C.PLATFORM_MAPPING_DIR.rstrip("/")
    cmd = f"ls -1 {mapping_dir}/{C.PLATFORM_MAPPING_GLOB} 2>/dev/null | sort | tail -1"
    try:
        out = await driver.async_run_cmd_on_shell(cmd)
    except Exception:  # noqa: BLE001 — degrade to the fallback below
        out = ""

    # Take the last non-empty line that looks like the mapping file; this ignores
    # any shell echo/prompt noise that some drivers include in the transcript.
    resolved = ""
    for line in (out or "").splitlines():
        candidate = line.strip()
        if candidate.endswith(".json") and "MetaGeneratedPlatformMapping" in candidate:
            resolved = candidate
    return resolved or C.PLATFORM_MAPPING_FALLBACK_PATH


async def load_port_map(
    driver: t.Any,
    mapping_path: t.Optional[str] = None,
) -> t.Optional[t.Dict[str, PortEntry]]:
    """Read + parse the on-box platform mapping (None if unavailable).

    ``mapping_path`` defaults to the device-resolved path from
    ``async_resolve_platform_mapping_path`` when not supplied.
    """
    path = mapping_path or await async_resolve_platform_mapping_path(driver)
    raw = await async_read_file_or_none(driver, path)
    if not raw:
        return None
    try:
        return parse_platform_mapping(json.loads(raw))
    except (json.JSONDecodeError, KeyError, ValueError):
        return None


def build_node_plan_for_role(
    role: str, port_map: t.Optional[t.Mapping[str, PortEntry]] = None
) -> NodePlan:
    """Build the ``NodePlan`` for ``role`` ("r1"/"r2") from topology + env."""
    topology = load_rbb_topology()
    plans = build_rbb_provision_plan(topology, port_map)
    if role not in plans:
        raise ValueError(f"unknown RBB role {role!r} (expected 'r1' or 'r2')")
    return plans[role]
