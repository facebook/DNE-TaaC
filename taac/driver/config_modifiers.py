#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""
OSS-safe BGP config modifiers for FBOSS devices.

Soft-drain and undrain a device without any Meta-internal dependency -- no
LocalDrainer, no config_selector, no COOP. The only primitive we rely on is the
launch convention: bgpd reads ``--config /dev/shm/fboss/bgpcpp_startup_config``,
which is a symlink.

A drain is therefore three things:

1. Update the ``/dev/shm/fboss`` drain markers.
2. Repoint the startup-config symlink at the corresponding config file.
3. Restart bgpd.

Both config files (live and soft-drain) must already exist on the device; they
are produced by the base-config generation step. Drain/undrain never creates
them.

Call these from a TAAC step or task with the device's driver::

    # step: Step.setUp already populated self.driver
    await drain_device(self.driver)

    # task: build one from the hostname
    driver = await async_get_device_driver(hostname)
    await drain_device(driver)
"""

from taac.driver.abstract_switch import AbstractSwitch
from taac.driver.driver_constants import FbossSystemctlServiceName


# Drain markers and the bgpd startup-config symlink. Mirrors the layout in
# neteng/fboss/config_selector/fboss_config_selector.py so a device that does run
# the internal selector stays consistent with what we do here.
#
# This is not our choice of location: bgpd is launched with
# --config /dev/shm/fboss/bgpcpp_startup_config, so the path is a fixed FBOSS
# on-device contract we interoperate with rather than a scratch area we picked.
# patternlint-disable-next-line no-dev-shm-usage
FBOSS_DRAIN_DIR: str = "/dev/shm/fboss"
STARTUP_CONFIG_SYMLINK: str = f"{FBOSS_DRAIN_DIR}/bgpcpp_startup_config"
# Staging name for the atomic symlink swap, matching the selector's own
# ".{daemon}_startup_config" convention.
_HIDDEN_STARTUP_CONFIG_SYMLINK: str = f"{FBOSS_DRAIN_DIR}/.bgpcpp_startup_config"

MARKER_UNDRAINED: str = f"{FBOSS_DRAIN_DIR}/UNDRAINED"
MARKER_SOFT_DRAINED: str = f"{FBOSS_DRAIN_DIR}/SOFT_DRAINED"

COOP_DIR: str = "/etc/coop"
LIVE_CONFIG_PATH: str = f"{COOP_DIR}/bgpcpp/current"
SOFTDRAIN_CONFIG_PATH: str = f"{COOP_DIR}/bgpcpp_softdrain/current"

_UNDRAIN: str = "undrain"
_SOFT_DRAIN: str = "soft-drain"

# Emitted by the file-existence probe. `test -f` alone communicates via exit code,
# which does not survive every driver transport, so echo a sentinel instead.
_FILE_EXISTS_SENTINEL: str = "__FILE_EXISTS__"


class ConfigModifierError(Exception):
    """A drain/undrain precondition failed, or the transition did not take effect."""


def _fboss_switch_cls() -> type:
    """Resolve FbossSwitch lazily.

    Imported inside a function rather than at module scope for two reasons: it
    keeps ``config_modifiers_lib`` from pulling the driver in at import time, and
    it stays cycle-safe if drain/undrain is ever exposed as a driver method. By
    the time this runs the class is already imported anyway -- the caller is
    holding an instance of it.
    """
    from taac.driver.fboss_switch import FbossSwitch

    return FbossSwitch


def _assert_fboss_device(switch: AbstractSwitch, state_name: str) -> None:
    """Reject drivers whose devices do not use the FBOSS bgpd launch convention.

    Everything here -- the ``/dev/shm/fboss`` markers, the ``/etc/coop/bgpcpp*``
    configs, ``systemctl restart bgpd`` -- is specific to a device running FBOSS
    bgpcpp under systemd. On an Arista or Cisco driver these commands are
    meaningless, and without this check the failure surfaces as a confusing shell
    error partway through instead of a clear rejection up front.

    ``FbossSwitchInternal`` subclasses ``FbossSwitch``, so internal runs pass.
    ``AristaFbossSwitch`` deliberately does not: it subclasses ``AristaSwitch``
    and drives bgpcpp through /mnt/flash + run_bgpcpp.sh under Arista daemon
    control, so none of the paths below apply to it.
    """
    if not isinstance(switch, _fboss_switch_cls()):
        raise ConfigModifierError(
            f"Cannot {state_name} {switch.hostname}: {type(switch).__name__} is not "
            "an FbossSwitch. Drain/undrain drives the FBOSS bgpd launch convention "
            "(/dev/shm/fboss markers, /etc/coop/bgpcpp* configs, systemctl bgpd), "
            "which does not apply to this device."
        )


async def _async_file_exists(switch: AbstractSwitch, path: str) -> bool:
    """Check for a regular file using only the AbstractSwitch API.

    ``FbossSwitch.async_check_if_file_exists`` would be the obvious call, but it
    is not on ``AbstractSwitch`` -- and steps and tasks hold their driver as an
    ``AbstractSwitch``, so depending on it would push a type-ignore onto every
    call site. The shell probe below is what the internal driver mixin falls back
    to for the same reason: ``test -f`` reports through its exit code, which does
    not survive every transport, so echo a sentinel and look for that instead.
    """
    output = await switch.async_run_cmd_on_shell(
        f"test -f {path} && echo {_FILE_EXISTS_SENTINEL} || true"
    )
    return _FILE_EXISTS_SENTINEL in (output or "")


async def _verify_startup_config(
    switch: AbstractSwitch, expected_config: str, state_name: str
) -> None:
    """Confirm the startup-config symlink still points where we put it.

    On a device that runs the internal ``config_selector`` at bgpd's
    ``ExecStartPre``, the selector re-derives this symlink from the drain markers
    on every restart. It forces the undrained config when the device reports as
    non-drainable, which would silently undo a drain. Reading the link back after
    the restart turns that into a loud failure instead of a test that quietly
    measured nothing.
    """
    # Plain readlink, not readlink -f: we want the literal target we set, and the
    # coop "current" paths are themselves symlinks that -f would resolve through.
    actual = await switch.async_run_cmd_on_shell(f"readlink {STARTUP_CONFIG_SYMLINK}")
    actual = (actual or "").strip()

    if actual != expected_config:
        raise ConfigModifierError(
            f"{state_name} of {switch.hostname} did not take effect: "
            f"{STARTUP_CONFIG_SYMLINK} points at {actual or '<nothing>'}, expected "
            f"{expected_config}. If an on-device config_selector runs at bgpd "
            "ExecStartPre, it may have re-derived the symlink from the drain "
            "markers -- check whether this device reports as drainable."
        )


async def drain_device(switch: AbstractSwitch, restart_bgp: bool = True) -> None:
    """Soft-drain a device: advertise DRAIN-tagged routes instead of LIVE.

    Routes are re-tagged, never withdrawn, so the drained path stays a viable
    backup while neighbours depreference it.

    Args:
        switch: driver for the device to drain.
        restart_bgp: restart bgpd so the new config takes effect. Pass False to
            batch several changes and restart once at the end -- until bgpd is
            restarted the device is still running its previous config.

    Raises:
        ConfigModifierError: the soft-drain config is missing, or the symlink did
            not survive the restart (see ``_verify_startup_config``).
    """
    await _apply_drain_state(
        switch,
        target_marker=MARKER_SOFT_DRAINED,
        opposite_marker=MARKER_UNDRAINED,
        target_config=SOFTDRAIN_CONFIG_PATH,
        state_name=_SOFT_DRAIN,
        restart_bgp=restart_bgp,
    )


async def undrain_device(switch: AbstractSwitch, restart_bgp: bool = True) -> None:
    """Undrain a device: return to advertising LIVE-tagged routes.

    Args:
        switch: driver for the device to undrain.
        restart_bgp: restart bgpd so the new config takes effect.

    Raises:
        ConfigModifierError: the live config is missing, or the symlink did not
            survive the restart.
    """
    await _apply_drain_state(
        switch,
        target_marker=MARKER_UNDRAINED,
        opposite_marker=MARKER_SOFT_DRAINED,
        target_config=LIVE_CONFIG_PATH,
        state_name=_UNDRAIN,
        restart_bgp=restart_bgp,
    )


async def _apply_drain_state(
    switch: AbstractSwitch,
    *,
    target_marker: str,
    opposite_marker: str,
    target_config: str,
    state_name: str,
    restart_bgp: bool,
) -> None:
    """Shared drain/undrain worker. The two directions differ only in arguments.

    Keyword-only (the bare ``*``) because four of the five arguments are plain
    strings and two of them are near-identical marker paths -- a positional call
    that transposed target_marker and opposite_marker would produce a "drain"
    that silently leaves the device live.
    """
    hostname = switch.hostname
    _assert_fboss_device(switch, state_name)

    if not await _async_file_exists(switch, target_config):
        raise ConfigModifierError(
            f"Cannot {state_name} {hostname}: BGP config {target_config} is missing. "
            "Generate the base configs first -- drain/undrain only selects between "
            "configs that already exist on the device."
        )

    # Order matters and is not merely defensive: the selector resolves markers as
    # UNDRAINED > WARM_DRAINED > SOFT_DRAINED > DRAINED, so leaving UNDRAINED in
    # place while adding SOFT_DRAINED would silently keep the device live. Removing
    # the opposite marker and setting the target in one invocation also avoids a
    # window where both or neither marker exists.
    switch.logger.info(
        f"[{state_name}] {hostname}: clearing {opposite_marker}, setting {target_marker}"
    )
    await switch.async_run_cmd_on_shell(
        f"rm -f {opposite_marker} && touch {target_marker}"
    )

    # Symlink into a staging name, then rename over the real one. rename(2) is
    # atomic, so bgpd can never observe a missing or half-written symlink -- this
    # is the same symlink_to()-then-rename() idiom fboss_config_selector.py uses.
    # `ln -sf` alone would not do: it unlinks the destination before recreating it.
    #
    # -n on the ln so an existing symlink-to-directory is replaced rather than
    # dereferenced (without it, ln would create the link *inside* that directory),
    # and -T on the mv for the same reason.
    switch.logger.info(
        f"[{state_name}] {hostname}: pointing {STARTUP_CONFIG_SYMLINK} at {target_config}"
    )
    await switch.async_run_cmd_on_shell(
        f"ln -sfn {target_config} {_HIDDEN_STARTUP_CONFIG_SYMLINK} && "
        f"mv -Tf {_HIDDEN_STARTUP_CONFIG_SYMLINK} {STARTUP_CONFIG_SYMLINK}"
    )

    if restart_bgp:
        switch.logger.info(f"[{state_name}] {hostname}: restarting bgpd")
        await switch.async_restart_service(FbossSystemctlServiceName.BGP)

    await _verify_startup_config(switch, target_config, state_name)
