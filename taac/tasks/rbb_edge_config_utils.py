# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""Recovery-safe file helpers for optional RBB configuration tasks.

The SRv6 qualification's opt-in bootstrap and edge overlay both patch existing
device JSON rather than replacing hardware-owned configuration wholesale.
These helpers snapshot each original file, verify writes, and restore the exact
pre-run state during teardown.
"""

from __future__ import annotations

import json
import shlex
import typing as t

from taac.constants import TestCaseFailure

EDGE_BACKUP_SUFFIX: str = ".taac-rbb-edge-orig"
_MISSING_MARKER_SUFFIX: str = ".missing"
_MISSING_MARKER_CONTENT: str = "TAAC_ORIGINAL_FILE_WAS_ABSENT\n"


async def _async_path_kind(driver: t.Any, path: str) -> str:
    """Classify a remote path without following a dangling or live symlink."""
    quoted = shlex.quote(path)
    output = await driver.async_run_cmd_on_shell(
        f"if [ -f {quoted} ] && [ ! -L {quoted} ]; then echo regular; "
        f"elif [ ! -e {quoted} ] && [ ! -L {quoted} ]; then echo absent; "
        "else echo invalid; fi"
    )
    result = str(output or "").strip()
    if result not in ("regular", "absent", "invalid"):
        raise TestCaseFailure(f"could not safely inspect on-device path {path}")
    return result


async def async_read_file_or_none(driver: t.Any, path: str) -> t.Optional[str]:
    """Return file contents, or ``None`` only when the file does not exist."""
    if not await driver.async_check_if_file_exists(path):
        return None
    return await driver.async_read_file(path)


async def async_backup_before_overwrite(
    driver: t.Any,
    path: str,
    logger: t.Any,
    hostname: str,
    force: bool = False,
    *,
    backup_suffix: str = EDGE_BACKUP_SUFFIX,
) -> bool:
    """Create and verify one recovery snapshot before a live file write.

    Existing snapshots are preserved because they may be the only copy left by
    an interrupted run.  A marker records an originally absent source file so
    restoration can remove a file created by the task.
    """
    backup = path + backup_suffix
    missing_marker = backup + _MISSING_MARKER_SUFFIX
    try:
        backup_kind = await _async_path_kind(driver, backup)
        marker_kind = await _async_path_kind(driver, missing_marker)
    except Exception as exc:  # noqa: BLE001
        raise TestCaseFailure(
            f"{hostname}: cannot verify recovery snapshot state for {path}: {exc}"
        ) from exc

    if "invalid" in (backup_kind, marker_kind) or (
        backup_kind != "absent" and marker_kind != "absent"
    ):
        raise TestCaseFailure(
            f"{hostname}: recovery artifacts for {path} are ambiguous or not "
            "regular, non-symlink files; refusing to overwrite live config"
        )
    if backup_kind != "absent" or marker_kind != "absent":
        if not force:
            raise TestCaseFailure(
                f"{hostname}: pre-run snapshot already exists for {path}; a "
                "previous run may have been interrupted. Restore or inspect "
                f"the {backup_suffix} snapshot before applying edge config "
                "again, or pass force=true to preserve it and reapply."
            )
        logger.info(f"{hostname} -- preserving existing snapshot for {path}")
        return False

    try:
        source_kind = await _async_path_kind(driver, path)
    except Exception as exc:  # noqa: BLE001
        raise TestCaseFailure(
            f"{hostname}: cannot determine whether {path} exists before overwrite: "
            f"{exc}"
        ) from exc

    if source_kind == "invalid":
        raise TestCaseFailure(
            f"{hostname}: {path} must be a regular, non-symlink file before overwrite"
        )
    if source_kind == "regular":
        try:
            current = await driver.async_read_file(path)
            copied = await driver.async_run_cmd_on_shell(
                f"if cp -p -- {shlex.quote(path)} {shlex.quote(backup)}; "
                "then echo copied; else echo failed; fi"
            )
            if str(copied or "").strip() != "copied":
                raise OSError("remote metadata-preserving copy failed")
            snapshot = await driver.async_read_file(backup)
        except Exception as exc:  # noqa: BLE001
            raise TestCaseFailure(
                f"{hostname}: cannot create recovery snapshot {backup}: {exc}"
            ) from exc
        if snapshot != current:
            raise TestCaseFailure(
                f"{hostname}: recovery snapshot {backup} failed readback "
                f"validation; refusing to overwrite {path}"
            )
        logger.info(f"{hostname} -- backed up {path} -> {backup}")
    else:
        try:
            await driver.async_write_file_on_device(
                _MISSING_MARKER_CONTENT, missing_marker
            )
            marker = await driver.async_read_file(missing_marker)
        except Exception as exc:  # noqa: BLE001
            raise TestCaseFailure(
                f"{hostname}: cannot create recovery marker {missing_marker}: {exc}"
            ) from exc
        if marker != _MISSING_MARKER_CONTENT:
            raise TestCaseFailure(
                f"{hostname}: recovery marker {missing_marker} failed readback "
                f"validation; refusing to overwrite {path}"
            )
        logger.info(f"{hostname} -- recorded that {path} was originally absent")
    return True


async def async_guard_snapshot_set(
    driver: t.Any,
    paths: t.Iterable[str],
    hostname: str,
    force: bool = False,
    *,
    backup_suffix: str = EDGE_BACKUP_SUFFIX,
) -> None:
    """Reject stale artifacts across a multi-file edit before snapshotting."""
    blocked: t.List[str] = []
    for path in paths:
        backup = path + backup_suffix
        marker = backup + _MISSING_MARKER_SUFFIX
        try:
            backup_kind = await _async_path_kind(driver, backup)
            marker_kind = await _async_path_kind(driver, marker)
            if "invalid" in (backup_kind, marker_kind) or (
                backup_kind != "absent" and marker_kind != "absent"
            ):
                raise TestCaseFailure(
                    f"{hostname}: recovery artifacts for {path} are ambiguous or "
                    "not regular, non-symlink files"
                )
            if backup_kind != "absent" or marker_kind != "absent":
                blocked.append(path)
        except Exception as exc:  # noqa: BLE001
            raise TestCaseFailure(
                f"{hostname}: could not verify recovery snapshot state for "
                f"{path}: {exc}"
            ) from exc
    if blocked and not force:
        raise TestCaseFailure(
            f"{hostname}: pre-run snapshot already exists for "
            f"{', '.join(blocked)}; restore or inspect the {backup_suffix} "
            "snapshot set before applying edge config again, or pass force=true "
            "to preserve it and reapply."
        )


async def async_write_json_file(
    driver: t.Any,
    path: str,
    document: t.Mapping[str, t.Any],
    *,
    hostname: str,
) -> None:
    """Write valid JSON through the driver and verify semantic readback."""
    contents = json.dumps(document, indent=2)
    expected = json.loads(contents)
    await driver.async_write_file_on_device(contents, path)
    readback = await async_read_file_or_none(driver, path)
    if readback is None:
        raise TestCaseFailure(f"{hostname}: {path} disappeared after config write")
    try:
        actual = json.loads(readback)
    except json.JSONDecodeError as exc:
        raise TestCaseFailure(
            f"{hostname}: {path} readback is not valid JSON after write: {exc}"
        ) from exc
    if actual != expected:
        raise TestCaseFailure(
            f"{hostname}: {path} readback differs from the generated config"
        )


async def async_apply_backup_metadata(
    driver: t.Any,
    path: str,
    hostname: str,
    *,
    backup_suffix: str = EDGE_BACKUP_SUFFIX,
) -> None:
    """Apply the saved numeric owner and mode to a newly written live file."""
    backup = path + backup_suffix
    quoted_path = shlex.quote(path)
    quoted_backup = shlex.quote(backup)
    output = await driver.async_run_cmd_on_shell(
        f"if [ -f {quoted_path} ] && [ ! -L {quoted_path} ] && "
        f"[ -f {quoted_backup} ] && [ ! -L {quoted_backup} ] && "
        f"chown --reference={quoted_backup} -- {quoted_path} && "
        f"chmod --reference={quoted_backup} -- {quoted_path}; "
        "then echo preserved; else echo failed; fi"
    )
    if str(output or "").strip() != "preserved":
        raise TestCaseFailure(
            f"{hostname}: could not preserve owner/mode for generated file {path}"
        )


async def async_remove_file(driver: t.Any, path: str) -> None:
    """Remove one explicitly resolved on-device file and verify its absence."""
    quoted = shlex.quote(path)
    output = await driver.async_run_cmd_on_shell(
        f"if rm -f -- {quoted} && [ ! -e {quoted} ] && [ ! -L {quoted} ]; "
        "then echo removed; else echo present; fi"
    )
    if str(output or "").strip() != "removed":
        raise TestCaseFailure(f"failed to remove on-device file {path}")


async def async_restore_backup(
    driver: t.Any,
    path: str,
    logger: t.Any,
    hostname: str,
    *,
    backup_suffix: str = EDGE_BACKUP_SUFFIX,
    consume: bool = True,
) -> bool:
    """Restore one snapshot (or original absence); return whether it existed."""
    backup = path + backup_suffix
    missing_marker = backup + _MISSING_MARKER_SUFFIX
    try:
        backup_kind = await _async_path_kind(driver, backup)
        marker_kind = await _async_path_kind(driver, missing_marker)
    except Exception as exc:  # noqa: BLE001
        raise TestCaseFailure(
            f"{hostname}: cannot verify recovery snapshot state for {path}: {exc}"
        ) from exc

    if backup_kind == "invalid" or marker_kind == "invalid":
        raise TestCaseFailure(
            f"{hostname}: recovery artifact for {path} is not a regular, "
            "non-symlink file"
        )
    if backup_kind == "regular" and marker_kind == "regular":
        raise TestCaseFailure(
            f"{hostname}: ambiguous recovery state for {path}: both {backup} and "
            f"{missing_marker} exist"
        )

    if backup_kind == "regular":
        content = await driver.async_read_file(backup)
        staging = path + ".taac_tmp"
        output = await driver.async_run_cmd_on_shell(
            f"if cp -p -- {shlex.quote(backup)} {shlex.quote(staging)} && "
            f"mv -f -- {shlex.quote(staging)} {shlex.quote(path)}; "
            "then echo restored; else echo failed; fi"
        )
        if str(output or "").strip() != "restored":
            raise TestCaseFailure(
                f"{hostname}: metadata-preserving restore failed for {path}; "
                f"keeping {backup} for recovery"
            )
        restored = await driver.async_read_file(path)
        if restored != content:
            raise TestCaseFailure(
                f"{hostname}: restored {path} failed readback validation; keeping "
                f"{backup} for recovery"
            )
        logger.info(f"{hostname} -- restored {path} from {backup}")
    elif marker_kind == "regular":
        marker = await driver.async_read_file(missing_marker)
        if marker != _MISSING_MARKER_CONTENT:
            raise TestCaseFailure(
                f"{hostname}: invalid recovery marker {missing_marker}; refusing "
                f"to remove {path}"
            )
        await async_remove_file(driver, path)
        if await _async_path_kind(driver, path) != "absent":
            raise TestCaseFailure(
                f"{hostname}: failed to remove {path} while restoring original absence"
            )
        logger.info(f"{hostname} -- removed {path} (absent before the run)")
    else:
        return False

    if consume:
        await async_remove_file(driver, backup)
        await async_remove_file(driver, missing_marker)
    return True


async def async_discard_backup(
    driver: t.Any, path: str, *, backup_suffix: str = EDGE_BACKUP_SUFFIX
) -> None:
    """Consume snapshot artifacts after a verified restore."""
    backup = path + backup_suffix
    await async_remove_file(driver, backup)
    await async_remove_file(driver, backup + _MISSING_MARKER_SUFFIX)
