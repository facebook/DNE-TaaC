#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""OSS stand-in for Meta's COOP python-patcher mechanism.

In Meta mode a test config changes a DUT's config by registering Python patchers
with the COOP agent and applying them. OSS has no COOP, so this module serves the
same register / unregister / apply contract against the config files, using the
typed patchers in ``oss_patchers``.

Each patched config has two copies:

* The **baseline**, ``/etc/coop/<config>.baseline.conf`` on the device: the
  config before the first patcher was registered. Every rebuild replays from it,
  and the last unregister puts it back.
* The **working copy**, on the host running TAAC: the baseline with every
  registered patcher applied. ``apply`` installs it on the device.

``register`` applies only the new patcher to the working copy: while patchers are
only added, the working copy is always the baseline plus every patcher in order.
``unregister`` cannot undo a patcher in place -- a speed flip disables ports it
never named -- so it rebuilds from the baseline with the patchers that remain.
Re-registering a name rebuilds too, or the new version would land on top of the
old one's changes.

Nothing on the device changes before ``apply``, except that the first register
for a config snapshots the baseline and the last unregister restores it.
Teardown uses ``async_restore_baselines``, which also restarts the daemons.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import os
import tempfile
import typing as t

# @manual=//configerator/structs/neteng/fboss/bgp:bgp_config-python-types
# Same pin as config_modifiers: the OSS mirror target emits the same module.
from configerator.structs.neteng.fboss.bgp.bgp_config.thrift_types import BgpConfig
from neteng.fboss.agent_config.thrift_types import AgentConfig
from taac.driver import config_modifiers
from taac.driver.driver_constants import FbossSystemctlServiceName
from taac.driver.oss_patchers import (
    OssPatchApplier,
    PATCHER_CONFIG_TYPES,
)
from taac.test_as_a_config import types as taac_types
from thrift.python.types import StructOrUnion

logger: logging.Logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class ConfigSpec:
    live_path: str
    config_type: type[StructOrUnion]

    @property
    def baseline_path(self) -> str:
        stem, ext = os.path.splitext(self.live_path)
        return f"{stem}.baseline{ext}"


CONFIG_SPECS: t.Dict[str, ConfigSpec] = {
    "agent": ConfigSpec(config_modifiers.AGENT_CONFIG_PATH, AgentConfig),
    "bgpcpp": ConfigSpec(config_modifiers.LIVE_CONFIG_PATH, BgpConfig),
    # What bgpd runs while soft-drained (config_modifiers repoints its startup
    # symlink here), so it must carry the same patchers as bgpcpp.
    "bgpcpp_softdrain": ConfigSpec(config_modifiers.SOFTDRAIN_CONFIG_PATH, BgpConfig),
}
_BGP_CONFIGS: t.FrozenSet[str] = frozenset({"bgpcpp", "bgpcpp_softdrain"})

# Only exist once config_modifiers.setup_base_configs has run. Registering
# against a device without the file is skipped rather than failed: callers send
# drainable hosts' bgpcpp patchers here too, whether or not the host drains.
_OPTIONAL_CONFIGS: t.FrozenSet[str] = frozenset({"bgpcpp_softdrain"})

# Meta's hard-drain variant, which nothing creates in OSS.
IGNORED_CONFIGS: t.FrozenSet[str] = frozenset({"bgpcpp_drain"})

PATCHER_DIR_ENV = "TAAC_OSS_PATCHER_DIR"
# A config change that removes a port (e.g. a speed change subsuming a /5) can
# crash a running agent (T281221621), so such an apply cold boots the agent, as
# `fboss2 config interface ... profile` does. Set this to "1" to keep the
# requested method instead.
PORT_REMOVAL_WARMBOOT_ENV = "TAAC_OSS_PATCHER_PORT_REMOVAL_WARMBOOT"
# Internal COOP waits this long between an agent reload and the warmboot after it.
_RELOAD_TO_WARMBOOT_S = 30
# async_run_cmd_on_shell does not surface the exit status.
_OK = "__OSS_PATCHER_OK__"


@dataclasses.dataclass
class OssPatcher:
    """Mirrors the attribute surface callers read off a COOP patcher.

    ``tasks/all.py`` filters registered patchers by ``.name`` and ``.owner``.
    COOP stamps ``owner`` with the registering user; OSS has no such notion, and
    the OSS unregister path matches ``owner is None``.
    """

    name: str
    config_name: str
    py_func_name: str
    args: t.Dict[str, t.Any] = dataclasses.field(default_factory=dict)
    desc: str = ""
    owner: t.Optional[str] = None


@dataclasses.dataclass
class _ConfigState:
    working_path: str
    patchers: t.List[OssPatcher] = dataclasses.field(default_factory=list)


# Module-level rather than on the driver: async_get_device_driver builds a fresh
# driver for every step, so register, unregister and apply never share one.
# host -> config_name -> state, for configs with at least one patcher.
_STATE: t.Dict[str, t.Dict[str, _ConfigState]] = {}
# host -> configs whose device file must be (re)installed or reactivated.
_PENDING: t.Dict[str, t.Set[str]] = {}
# host -> names of ports the installed agent config dropped since the agent
# last started.
_REMOVED_PORTS: t.Dict[str, t.Set[str]] = {}
# host -> the agent's platform mapping, fetched once.
_PLATFORM_MAPPINGS: t.Dict[str, t.Any] = {}


class _SwitchInputs:
    """``PatcherInputs`` read off the device the patchers target."""

    def __init__(self, switch: t.Any) -> None:
        self._switch = switch

    async def platform_mapping(self) -> t.Any:
        host = self._switch.hostname
        if host not in _PLATFORM_MAPPINGS:
            _PLATFORM_MAPPINGS[host] = await self._switch.async_get_platform_mapping()
        return _PLATFORM_MAPPINGS[host]

    def hardware(self) -> t.Optional[str]:
        from taac.oss_topology_info.device_info_loader import (
            get_hardware_from_hostname_oss,
        )

        return get_hardware_from_hostname_oss(self._switch.hostname)


def _applier(switch: t.Any) -> OssPatchApplier:
    return OssPatchApplier(switch.logger, _SwitchInputs(switch))


def default_patcher_dir() -> str:
    """Working-copy directory: ``$TAAC_OSS_PATCHER_DIR``, else one per process."""
    return os.environ.get(PATCHER_DIR_ENV) or os.path.join(
        tempfile.gettempdir(), f"taac_oss_patchers.{os.getpid()}"
    )


def list_patchers(host: str, config_name: str) -> t.List[OssPatcher]:
    state = _STATE.get(host, {}).get(config_name)
    return list(state.patchers) if state else []


def find_configs(host: str, patcher_name: str) -> t.List[str]:
    """Every config a patcher name is registered against.

    More than one when a caller sent the same patcher to several configs, e.g.
    ``bgpcpp`` and ``bgpcpp_softdrain``.
    """
    return [
        config_name
        for config_name, state in _STATE.get(host, {}).items()
        if any(p.name == patcher_name for p in state.patchers)
    ]


def clear(host: str) -> None:
    """Forget a host's patchers without touching the device or working copies."""
    _STATE.pop(host, None)
    _PENDING.pop(host, None)
    _REMOVED_PORTS.pop(host, None)
    _PLATFORM_MAPPINGS.pop(host, None)


async def async_register(
    switch: t.Any, patcher: OssPatcher, patcher_dir: t.Optional[str] = None
) -> str:
    """Add ``patcher`` to its config's working copy and return that copy's path,
    or "" when the config is ignored or absent on the device.

    ``patcher_dir`` only takes effect on a config's first register; later
    registers reuse the working copy that one created.
    """
    host, config_name = switch.hostname, patcher.config_name
    if config_name in IGNORED_CONFIGS:
        switch.logger.info(f"[oss-patcher] ignoring {config_name} patcher on {host}")
        return ""
    spec = _spec(config_name)
    _check_patcher_targets(patcher, spec)

    applier = _applier(switch)
    state = _STATE.get(host, {}).get(config_name)
    snapshot_created = False
    if state is None:
        if (
            config_name in _OPTIONAL_CONFIGS
            and not await config_modifiers.async_file_exists(switch, spec.live_path)
        ):
            switch.logger.info(
                f"[oss-patcher] {host} has no {spec.live_path}; skipping "
                f"{patcher.name} for {config_name}"
            )
            return ""
        config, snapshot_created = await _async_snapshot_baseline(switch, spec)
        state = _ConfigState(
            os.path.join(
                patcher_dir or default_patcher_dir(), host, f"{config_name}.conf"
            )
        )
    else:
        config = _read_working_copy(state, spec)

    try:
        if any(p.name == patcher.name for p in state.patchers):
            patchers = [
                patcher if p.name == patcher.name else p for p in state.patchers
            ]
            config = await _async_rebuild(switch, spec, applier, patchers)
        else:
            patchers = [*state.patchers, patcher]
            config = await applier.async_apply(
                config, config_name, patcher.py_func_name, patcher.args
            )
    except Exception:
        # A rejected first patcher leaves nothing registered, so the snapshot it
        # took would only make teardown restart a daemon for an unchanged file.
        if snapshot_created:
            await _async_run_checked(switch, f"rm -f {spec.baseline_path}")
        raise

    # Record only once the patcher has applied cleanly, so a bad one is never
    # listed as registered.
    _write_working_copy(state.working_path, config)
    state.patchers = patchers
    _STATE.setdefault(host, {})[config_name] = state
    _PENDING.setdefault(host, set()).add(config_name)
    return state.working_path


async def async_unregister(switch: t.Any, config_name: str, patcher_name: str) -> bool:
    """Drop ``patcher_name`` from its config. Returns whether it was registered.

    With patchers left, the working copy is rebuilt from the baseline. With none
    left, the baseline goes back on the device now, so a daemon restart picks it
    up even if the caller never applies.
    """
    host = switch.hostname
    state = _STATE.get(host, {}).get(config_name)
    if state is None or all(p.name != patcher_name for p in state.patchers):
        return False

    spec = _spec(config_name)
    remaining = [p for p in state.patchers if p.name != patcher_name]
    if remaining:
        config = await _async_rebuild(switch, spec, _applier(switch), remaining)
        _write_working_copy(state.working_path, config)
        state.patchers = remaining
    else:
        if config_name == "agent":
            await _async_note_removed_ports(
                switch, await switch.async_read_file(spec.baseline_path)
            )
        await _async_restore_baseline(switch, spec)
        _remove_working_copy(state.working_path)
        del _STATE[host][config_name]
    _PENDING.setdefault(host, set()).add(config_name)
    return True


async def async_restore_baselines(switch: t.Any) -> None:
    """Put every config back to its baseline and restart what it runs (teardown).

    Driven by the baseline files on the device rather than by the registry, so a
    baseline left behind by a run that died before restoring is restored too.
    Each restored config is activated as ``async_apply`` would with no method --
    the agent reloaded, or warmbooted along with a bgp change, bgpd restarted --
    as is one an earlier unregister already restored but nobody applied.
    """
    host = switch.hostname
    changed = set(_PENDING.get(host, set()))
    for name, spec in CONFIG_SPECS.items():
        if await config_modifiers.async_file_exists(switch, spec.baseline_path):
            if name == "agent":
                await _async_note_removed_ports(
                    switch, await switch.async_read_file(spec.baseline_path)
                )
            await _async_restore_baseline(switch, spec)
            changed.add(name)
    for state in _STATE.get(host, {}).values():
        _remove_working_copy(state.working_path)
    coldboot = _coldboot_for_removed_ports(switch)
    clear(host)
    # The baselines are gone from the device now, so this is the only record of
    # what still needs activating: kept until the restarts succeed, so a retry
    # restarts them again instead of finding nothing to do.
    _PENDING[host] = changed

    if changed:
        switch.logger.info(f"[oss-patcher] restored {sorted(changed)} on {host}")
    # As the default apply: an agent-only change reloads, agent plus bgp is one
    # warmboot, and a restore that removes a port cold boots.
    await _async_activate(switch, changed, None, coldboot)
    _PENDING.pop(host, None)


async def async_apply(
    switch: t.Any,
    method: t.Optional[taac_types.ApplyPatcherMethod] = None,
    coldboot: bool = False,
    activate: bool = True,
) -> None:
    """Install the changed configs on the device, then activate them.

    Every changed config is written before any daemon restarts. ``method``
    follows COOP's ``ApplyPatcherMethod``; with none, a changed agent config is
    reloaded (falling back to a warmboot), as COOP's default apply does, unless
    a bgp config changed too, in which case the agent is warmbooted. A change to
    either bgp config restarts bgpd once; it has no reload. ``coldboot``
    overrides ``method`` for the agent, and is forced when the agent config
    drops a port (see ``PORT_REMOVAL_WARMBOOT_ENV``). With ``activate=False``
    the files are installed and nothing restarts: the caller activates them.
    """
    host = switch.hostname
    changed = set(_PENDING.get(host, set()))
    states = _STATE.get(host, {})
    to_install = {
        CONFIG_SPECS[name].live_path: _read_working_copy(
            states[name], CONFIG_SPECS[name]
        )
        for name in sorted(changed)
        if name in states
    }
    agent_config = to_install.get(CONFIG_SPECS["agent"].live_path)
    if agent_config is not None:
        await _async_note_removed_ports(
            switch, config_modifiers.serialize_config(agent_config)
        )
    if to_install:
        switch.logger.info(f"[oss-patcher] installing {sorted(to_install)} on {host}")
        await config_modifiers.async_write_configs(switch, to_install)
    if not activate:
        _PENDING.pop(host, None)
        switch.logger.info(f"[oss-patcher] {host}: installed without activating")
        return
    await _async_activate(
        switch, changed, method, coldboot or _coldboot_for_removed_ports(switch)
    )
    # Cleared only once activation succeeds, so a failed restart is retried by
    # the next apply rather than reported as nothing to do.
    _PENDING.pop(host, None)
    _REMOVED_PORTS.pop(host, None)


def _spec(config_name: str) -> ConfigSpec:
    try:
        return CONFIG_SPECS[config_name]
    except KeyError:
        raise ValueError(
            f"oss-patcher: unknown config_name {config_name!r} "
            f"(known: {sorted(CONFIG_SPECS)})"
        ) from None


def _check_patcher_targets(patcher: OssPatcher, spec: ConfigSpec) -> None:
    config_type = PATCHER_CONFIG_TYPES.get(patcher.py_func_name)
    if config_type is None:
        raise NotImplementedError(
            f"oss-patcher: py_func_name {patcher.py_func_name!r} is not ported to "
            f"OSS (supported: {sorted(PATCHER_CONFIG_TYPES)}). Port it in "
            "oss_patchers.py rather than letting the test run against an "
            "unconfigured device."
        )
    if config_type is not spec.config_type:
        raise ValueError(
            f"oss-patcher: {patcher.py_func_name} patches {config_type.__name__}, "
            f"but config {patcher.config_name!r} is {spec.config_type.__name__}"
        )


async def _async_snapshot_baseline(
    switch: t.Any, spec: ConfigSpec
) -> t.Tuple[t.Any, bool]:
    """The baseline config, and whether this call created its snapshot."""
    baseline = spec.baseline_path
    created = False
    if await config_modifiers.async_file_exists(switch, baseline):
        switch.logger.warning(
            f"[oss-patcher] {switch.hostname}:{baseline} already exists -- the "
            "device was not restored after an earlier run. Using it as the baseline."
        )
    else:
        await _async_run_checked(switch, f"cp -a {spec.live_path} {baseline}")
        created = True
    return await _async_read_baseline(switch, spec), created


async def _async_read_baseline(switch: t.Any, spec: ConfigSpec) -> t.Any:
    raw = await switch.async_read_file(spec.baseline_path)
    return config_modifiers.deserialize_config(
        spec.config_type, raw, f"{switch.hostname}:{spec.baseline_path}"
    )


async def _async_rebuild(
    switch: t.Any,
    spec: ConfigSpec,
    applier: OssPatchApplier,
    patchers: t.List[OssPatcher],
) -> t.Any:
    """Replay ``patchers`` in order onto the baseline read back from the device."""
    config = await _async_read_baseline(switch, spec)
    for patcher in patchers:
        config = await applier.async_apply(
            config, patcher.config_name, patcher.py_func_name, patcher.args
        )
    return config


async def _async_restore_baseline(switch: t.Any, spec: ConfigSpec) -> None:
    live, baseline = spec.live_path, spec.baseline_path
    # Staged copy + rename, so the daemon never reads a half-copied file.
    await _async_run_checked(
        switch,
        f"cp -a {baseline} {live}.restore && mv -f {live}.restore {live} "
        f"&& rm -f {baseline}",
    )


def _port_names(raw_agent_config: str) -> t.Dict[int, str]:
    ports = json.loads(raw_agent_config).get("sw", {}).get("ports", [])
    return {p["logicalID"]: p.get("name", str(p["logicalID"])) for p in ports}


async def _async_note_removed_ports(switch: t.Any, new_agent_config: str) -> None:
    """Record the ports ``new_agent_config`` lacks that the device's live agent
    config has, before it replaces that file."""
    live = await switch.async_read_file(CONFIG_SPECS["agent"].live_path)
    before, after = _port_names(live), _port_names(new_agent_config)
    removed = {name for port_id, name in before.items() if port_id not in after}
    if removed:
        _REMOVED_PORTS.setdefault(switch.hostname, set()).update(removed)


def _coldboot_for_removed_ports(switch: t.Any) -> bool:
    removed = _REMOVED_PORTS.get(switch.hostname)
    if not removed:
        return False
    if os.environ.get(PORT_REMOVAL_WARMBOOT_ENV) == "1":
        switch.logger.warning(
            f"[oss-patcher] {switch.hostname}: {sorted(removed)} removed without "
            f"a cold boot ({PORT_REMOVAL_WARMBOOT_ENV}=1); see T281221621"
        )
        return False
    switch.logger.info(
        f"[oss-patcher] {switch.hostname}: cold booting the agent, the config "
        f"removes {sorted(removed)} (T281221621)"
    )
    return True


async def _async_activate(
    switch: t.Any,
    changed: t.Set[str],
    method: t.Optional[taac_types.ApplyPatcherMethod],
    coldboot: bool,
) -> None:
    methods = taac_types.ApplyPatcherMethod
    agent_changed = "agent" in changed
    bgp_changed = bool(changed & _BGP_CONFIGS)
    agent_restarted = True
    if coldboot:
        await switch.async_create_cold_boot_file()
        await _async_restart_agent(switch)
    elif method == methods.AGENT_WARMBOOT or (
        method is None and agent_changed and bgp_changed
    ):
        await _async_restart_agent(switch)
    elif method == methods.AGENT_RELOAD_AND_WARMBOOT:
        await switch.async_try_agent_config_reload()
        await asyncio.sleep(_RELOAD_TO_WARMBOOT_S)
        await _async_restart_agent(switch)
    elif method == methods.AGENT_RELOAD or (method is None and agent_changed):
        await switch.async_try_agent_config_reload()
        agent_restarted = False
    else:
        agent_restarted = False
        if agent_changed:
            switch.logger.warning(
                f"[oss-patcher] agent config installed on {switch.hostname} but "
                f"not activated: {method} does not touch the agent"
            )
    if bgp_changed or method == methods.BGP_RESTART:
        await _async_activate_bgp(switch, agent_restarted)


async def _async_activate_bgp(switch: t.Any, agent_restarted: bool) -> None:
    # bgpd's unit has BindsTo=wedge_agent.service, so an agent restart already
    # restarted it.
    if not agent_restarted:
        await switch.async_restart_service(FbossSystemctlServiceName.BGP)
    await switch.async_wait_for_bgp_convergence()


async def _async_restart_agent(switch: t.Any) -> None:
    await switch.async_restart_service(FbossSystemctlServiceName.AGENT)
    await switch.async_wait_for_agent_configured()


async def _async_run_checked(switch: t.Any, cmd: str) -> None:
    out = await switch.async_run_cmd_on_shell(f"{cmd} && echo {_OK}")
    if _OK not in (out or ""):
        raise RuntimeError(
            f"[oss-patcher] {switch.hostname}: `{cmd}` failed: {(out or '').strip()!r}"
        )


def _read_working_copy(state: _ConfigState, spec: ConfigSpec) -> t.Any:
    with open(state.working_path) as f:
        raw = f.read()
    return config_modifiers.deserialize_config(
        spec.config_type, raw, state.working_path
    )


def _write_working_copy(path: str, config: t.Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    staged = f"{path}.tmp"
    with open(staged, "w") as f:
        f.write(config_modifiers.serialize_config(config))
    os.replace(staged, path)


def _remove_working_copy(path: str) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
