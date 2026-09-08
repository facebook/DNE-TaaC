# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""Reversible, opt-in bootstrap for a freshly imaged RBB FBOSS pair.

The task reads the image-installed AgentConfig/BGP/OpenR JSON, builds all three
logical patches in memory, validates the resulting SwitchConfig and BGP config
against the TAAC image's bundled Thrift schemas, and only then snapshots and
writes. It starts an inactive service for the test but never enables it
persistently. Teardown restores the original file contents, modes, numeric
owners, and active/inactive service states.

Recovery artifacts deliberately survive interruption:

* ``<config>.taac-rbb-bootstrap-orig`` contains each original file.
* ``/var/tmp/taac-rbb-bootstrap-state.json`` records service state and modes.

A later apply fails closed while any artifact exists; it never overwrites the
only recovery point from an interrupted run.
"""

from __future__ import annotations

import asyncio
import json
import re
import shlex
import typing as t

from taac.constants import TestCaseFailure
from taac.driver.driver_constants import FbossSystemctlServiceName
from taac.tasks.base_task import BaseTask
from taac.tasks.rbb_edge_config_utils import (
    async_backup_before_overwrite,
    async_discard_backup,
    async_guard_snapshot_set,
    async_read_file_or_none,
    async_remove_file,
    async_restore_backup,
    async_write_json_file,
)
from taac.testconfigs.routing.util import bgp_rbb_constants as C
from taac.testconfigs.routing.util.bgp_rbb_bootstrap_config import (
    build_bootstrap_documents,
    validate_bootstrap_device_paths,
)
from taac.testconfigs.routing.util.bgp_rbb_topology import CorePortChannel
from taac.utils.driver_factory import async_get_device_driver
from taac.utils.oss_taac_lib_utils import ConsoleFileLogger

BOOTSTRAP_BACKUP_SUFFIX = ".taac-rbb-bootstrap-orig"
_APPLY = "apply"
_RESTORE = "restore"
_STATE_VERSION = 1
_CONTROL_PLANE_TIMEOUT_SEC = 120
_CONTROL_PLANE_POLL_SEC = 5
_CONFIG_PATHS = (C.AGENT_CONFIG_PATH, C.OPENR_CONFIG_PATH, C.BGP_CONFIG_PATH)
_SERVICES = {
    "agent": FbossSystemctlServiceName.FBOSS_SW_AGENT,
    "openr": FbossSystemctlServiceName.OPENR,
    "bgp": FbossSystemctlServiceName.BGP,
}


class RbbDutBootstrapTask(BaseTask):
    """Patch/restore the RBB core, OpenR, iBGP, and SRv6 base configuration."""

    # pyrefly: ignore [bad-override-mutable-attribute]
    NAME: str = "rbb_dut_bootstrap"

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
        hostname = params.get("hostname") or self.hostname
        if not hostname:
            raise ValueError("rbb_dut_bootstrap requires 'hostname'")
        action = params.get("action", _APPLY)
        if action not in (_APPLY, _RESTORE):
            raise ValueError(
                f"rbb_dut_bootstrap action must be {_APPLY!r} or {_RESTORE!r}"
            )
        all_paths = (*_CONFIG_PATHS, C.BGP_POLICY_PATH, C.BOOTSTRAP_STATE_PATH)
        validate_bootstrap_device_paths(all_paths)

        if action == _APPLY:
            role = str(params.get("role") or "").lower()
            if role not in ("r1", "r2"):
                raise ValueError("rbb_dut_bootstrap apply requires role='r1' or 'r2'")
            core_pcs = self._parse_core_pcs(params.get("core_port_channels"))
            include_traffic = params.get("include_traffic", False)
            if not isinstance(include_traffic, bool):
                raise ValueError("include_traffic must be a JSON boolean")

        driver = await async_get_device_driver(hostname)
        await self._require_root(driver, hostname)
        if action == _RESTORE:
            await self._restore(driver, hostname)
            return

        await self._apply(
            driver,
            hostname,
            role,
            core_pcs,
            include_traffic=include_traffic,
        )

    @staticmethod
    def _parse_core_pcs(value: t.Any) -> t.Tuple[CorePortChannel, ...]:
        if not isinstance(value, list) or not value:
            raise ValueError(
                "rbb_dut_bootstrap apply requires a non-empty "
                "core_port_channels list"
            )
        result: t.List[CorePortChannel] = []
        for item in value:
            if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                raise ValueError("core_port_channels contains an invalid entry")
            members = item.get("members")
            if not isinstance(members, list) or not all(
                isinstance(member, str) and member.strip() for member in members
            ):
                raise ValueError(
                    f"core port-channel {item.get('name')!r} has invalid members"
                )
            result.append(
                CorePortChannel(
                    name=item["name"].strip(),
                    members=tuple(member.strip() for member in members),
                )
            )
        return tuple(result)

    @staticmethod
    async def _require_root(driver: t.Any, hostname: str) -> None:
        uid = str(await driver.async_run_cmd_on_shell("id -u") or "").strip()
        if uid != "0":
            raise TestCaseFailure(
                f"{hostname}: --setup-duts requires a root SSH account; "
                f"the remote session reported uid {uid or 'unknown'}"
            )

    @staticmethod
    async def _path_entry_exists(driver: t.Any, hostname: str, path: str) -> bool:
        """Detect any filesystem entry, including a dangling symlink."""
        quoted = shlex.quote(path)
        output = await driver.async_run_cmd_on_shell(
            f"if [ -e {quoted} ] || [ -L {quoted} ]; "
            "then echo present; else echo absent; fi"
        )
        result = str(output or "").strip()
        if result not in ("present", "absent"):
            raise TestCaseFailure(
                f"{hostname}: could not safely inspect recovery path {path}"
            )
        return result == "present"

    async def _read_json(
        self, driver: t.Any, hostname: str, path: str
    ) -> t.Dict[str, t.Any]:
        raw = await async_read_file_or_none(driver, path)
        if raw is None:
            raise TestCaseFailure(
                f"{hostname}: required image-installed config is missing: {path}"
            )
        try:
            document = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise TestCaseFailure(f"{hostname}: {path} is not valid JSON: {exc}") from exc
        if not isinstance(document, dict):
            raise TestCaseFailure(f"{hostname}: {path} must contain a JSON object")
        return document

    async def _active_state(
        self, driver: t.Any, hostname: str, service: FbossSystemctlServiceName
    ) -> str:
        output = await driver.async_run_cmd_on_shell(
            f"systemctl show {service.value} "
            "--property=LoadState --property=ActiveState"
        )
        fields = {}
        for line in str(output or "").splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                fields[key.strip()] = value.strip()
        if fields.get("LoadState") != "loaded":
            raise TestCaseFailure(
                f"{hostname}: required service {service.value} is not installed "
                f"and loaded (LoadState={fields.get('LoadState') or 'unknown'})"
            )
        state = fields.get("ActiveState")
        if state not in ("active", "inactive"):
            raise TestCaseFailure(
                f"{hostname}: {service.value} must be active or inactive before "
                f"bootstrap; found {state or 'unknown'}"
            )
        return state

    async def _file_mode(self, driver: t.Any, hostname: str, path: str) -> str:
        quoted = shlex.quote(path)
        output = await driver.async_run_cmd_on_shell(
            f"if [ -f {quoted} ] && [ ! -L {quoted} ]; "
            f"then stat -c %a -- {quoted}; fi"
        )
        mode = str(output or "").strip()
        if re.fullmatch(r"[0-7]{3,4}", mode) is None:
            raise TestCaseFailure(
                f"{hostname}: {path} must be a regular, non-symlink file with "
                "a readable mode"
            )
        return mode

    async def _set_file_mode(
        self, driver: t.Any, hostname: str, path: str, mode: str
    ) -> None:
        output = await driver.async_run_cmd_on_shell(
            f"chmod {mode} -- {shlex.quote(path)} && "
            f"stat -c %a -- {shlex.quote(path)}"
        )
        if str(output or "").strip() != mode:
            raise TestCaseFailure(
                f"{hostname}: could not preserve file mode {mode} for {path}"
            )

    async def _file_owner(self, driver: t.Any, hostname: str, path: str) -> str:
        quoted = shlex.quote(path)
        output = await driver.async_run_cmd_on_shell(
            f"if [ -f {quoted} ] && [ ! -L {quoted} ]; "
            f"then stat -c %u:%g -- {quoted}; fi"
        )
        owner = str(output or "").strip()
        if re.fullmatch(r"[0-9]+:[0-9]+", owner) is None:
            raise TestCaseFailure(
                f"{hostname}: {path} must be a regular, non-symlink file with "
                "a readable numeric owner"
            )
        return owner

    async def _set_file_owner(
        self, driver: t.Any, hostname: str, path: str, owner: str
    ) -> None:
        output = await driver.async_run_cmd_on_shell(
            f"chown {owner} -- {shlex.quote(path)} && "
            f"stat -c %u:%g -- {shlex.quote(path)}"
        )
        if str(output or "").strip() != owner:
            raise TestCaseFailure(
                f"{hostname}: could not preserve numeric owner {owner} for {path}"
            )

    async def _apply(
        self,
        driver: t.Any,
        hostname: str,
        role: str,
        core_pcs: t.Sequence[CorePortChannel],
        *,
        include_traffic: bool,
    ) -> None:
        if await driver.async_check_if_file_exists(
            C.BOOTSTRAP_STATE_PATH
        ) or await self._path_entry_exists(
            driver, hostname, C.BOOTSTRAP_STATE_PATH
        ):
            raise TestCaseFailure(
                f"{hostname}: bootstrap recovery state already exists at "
                f"{C.BOOTSTRAP_STATE_PATH}; restore or inspect the interrupted "
                "run before applying again"
            )
        for path in _CONFIG_PATHS:
            for artifact in (
                path + BOOTSTRAP_BACKUP_SUFFIX,
                path + BOOTSTRAP_BACKUP_SUFFIX + ".missing",
            ):
                if await self._path_entry_exists(driver, hostname, artifact):
                    raise TestCaseFailure(
                        f"{hostname}: bootstrap recovery artifact already exists "
                        f"at {artifact}; restore or inspect the interrupted run "
                        "before applying again"
                    )
        await async_guard_snapshot_set(
            driver,
            _CONFIG_PATHS,
            hostname,
            backup_suffix=BOOTSTRAP_BACKUP_SUFFIX,
        )

        # Read and build the complete transaction before creating a snapshot.
        base_agent = await self._read_json(driver, hostname, C.AGENT_CONFIG_PATH)
        base_openr = await self._read_json(driver, hostname, C.OPENR_CONFIG_PATH)
        base_bgp = await self._read_json(driver, hostname, C.BGP_CONFIG_PATH)
        policy = await self._read_json(driver, hostname, C.BGP_POLICY_PATH)
        if not all(
            isinstance(policy.get(key), dict)
            for key in ("policies", "prefix_sets", "as_path_sets", "community_sets")
        ):
            raise TestCaseFailure(
                f"{hostname}: {C.BGP_POLICY_PATH} is not the expected bgpd policy object"
            )
        try:
            documents = build_bootstrap_documents(
                base_agent=base_agent,
                base_bgp=base_bgp,
                base_openr=base_openr,
                role=role,
                core_pcs=core_pcs,
                include_traffic=include_traffic,
            )
        except ValueError as exc:
            raise TestCaseFailure(f"{hostname}: unsafe bootstrap input: {exc}") from exc

        # Validate against the exact FBOSS/BGP Thrift schemas bundled in this
        # image, including tunnel field names and map/list representation.
        from configerator.structs.neteng.fboss.bgp.bgp_config.thrift_types import (
            BgpConfig,
        )
        from neteng.fboss.switch_config.thrift_types import SwitchConfig
        from taac.utils.json_thrift_utils import json_to_thrift

        try:
            json_to_thrift(json.dumps(documents.agent["sw"]), SwitchConfig)
            json_to_thrift(json.dumps(documents.bgp), BgpConfig)
        except Exception as exc:  # noqa: BLE001
            raise TestCaseFailure(
                f"{hostname}: generated bootstrap config does not match the "
                f"bundled FBOSS/BGP Thrift schema: {exc}"
            ) from exc

        desired = {
            C.AGENT_CONFIG_PATH: documents.agent,
            C.OPENR_CONFIG_PATH: documents.openr,
            C.BGP_CONFIG_PATH: documents.bgp,
        }
        originals = {
            C.AGENT_CONFIG_PATH: base_agent,
            C.OPENR_CONFIG_PATH: base_openr,
            C.BGP_CONFIG_PATH: base_bgp,
        }
        changed_paths = [
            path for path in _CONFIG_PATHS if desired[path] != originals[path]
        ]
        service_states = {
            name: await self._active_state(driver, hostname, service)
            for name, service in _SERVICES.items()
        }
        file_modes = {
            path: await self._file_mode(driver, hostname, path)
            for path in _CONFIG_PATHS
        }
        file_owners = {
            path: await self._file_owner(driver, hostname, path)
            for path in _CONFIG_PATHS
        }
        state_document = {
            "version": _STATE_VERSION,
            "hostname": hostname,
            "phase": "snapshotting",
            "changed_paths": changed_paths,
            "service_active_state": service_states,
            "file_modes": file_modes,
            "file_owners": file_owners,
        }

        created_snapshots: t.List[str] = []
        state_created = False
        try:
            await async_write_json_file(
                driver,
                C.BOOTSTRAP_STATE_PATH,
                state_document,
                hostname=hostname,
            )
            state_created = True
            for path in changed_paths:
                if await async_backup_before_overwrite(
                    driver,
                    path,
                    self.logger,
                    hostname,
                    backup_suffix=BOOTSTRAP_BACKUP_SUFFIX,
                ):
                    created_snapshots.append(path)
                snapshot = await self._read_json(
                    driver, hostname, path + BOOTSTRAP_BACKUP_SUFFIX
                )
                if snapshot != originals[path]:
                    raise TestCaseFailure(
                        f"{hostname}: {path} changed while bootstrap was "
                        "snapshotting; no live config was written"
                    )
                if await self._file_mode(driver, hostname, path) != file_modes[path]:
                    raise TestCaseFailure(
                        f"{hostname}: mode of {path} changed while bootstrap was "
                        "snapshotting; no live config was written"
                    )
                if await self._file_owner(driver, hostname, path) != file_owners[path]:
                    raise TestCaseFailure(
                        f"{hostname}: owner of {path} changed while bootstrap was "
                        "snapshotting; no live config was written"
                    )
            for name, service in _SERVICES.items():
                if (
                    await self._active_state(driver, hostname, service)
                    != service_states[name]
                ):
                    raise TestCaseFailure(
                        f"{hostname}: state of {service.value} changed while "
                        "bootstrap was snapshotting; no live config was written"
                    )
            # No live write is permitted until this durable phase transition.
            # If the process dies earlier, restore knows partial snapshots can
            # be discarded because every original config is still in place.
            state_document["phase"] = "ready"
            await async_write_json_file(
                driver,
                C.BOOTSTRAP_STATE_PATH,
                state_document,
                hostname=hostname,
            )
        except Exception:
            for path in created_snapshots:
                await async_discard_backup(
                    driver, path, backup_suffix=BOOTSTRAP_BACKUP_SUFFIX
                )
            if state_created:
                await async_remove_file(driver, C.BOOTSTRAP_STATE_PATH)
            raise

        try:
            if C.AGENT_CONFIG_PATH in changed_paths:
                await async_write_json_file(
                    driver,
                    C.AGENT_CONFIG_PATH,
                    documents.agent,
                    hostname=hostname,
                )
                await self._set_file_owner(
                    driver,
                    hostname,
                    C.AGENT_CONFIG_PATH,
                    file_owners[C.AGENT_CONFIG_PATH],
                )
                await self._set_file_mode(
                    driver,
                    hostname,
                    C.AGENT_CONFIG_PATH,
                    file_modes[C.AGENT_CONFIG_PATH],
                )
            await self._activate_agent(
                driver, service_states["agent"] == "active"
            )

            if C.OPENR_CONFIG_PATH in changed_paths:
                await async_write_json_file(
                    driver,
                    C.OPENR_CONFIG_PATH,
                    documents.openr,
                    hostname=hostname,
                )
                await self._set_file_owner(
                    driver,
                    hostname,
                    C.OPENR_CONFIG_PATH,
                    file_owners[C.OPENR_CONFIG_PATH],
                )
                await self._set_file_mode(
                    driver,
                    hostname,
                    C.OPENR_CONFIG_PATH,
                    file_modes[C.OPENR_CONFIG_PATH],
                )
            await self._activate_service(
                driver,
                FbossSystemctlServiceName.OPENR,
                service_states["openr"] == "active",
            )

            if C.BGP_CONFIG_PATH in changed_paths:
                await async_write_json_file(
                    driver, C.BGP_CONFIG_PATH, documents.bgp, hostname=hostname
                )
                await self._set_file_owner(
                    driver,
                    hostname,
                    C.BGP_CONFIG_PATH,
                    file_owners[C.BGP_CONFIG_PATH],
                )
                await self._set_file_mode(
                    driver,
                    hostname,
                    C.BGP_CONFIG_PATH,
                    file_modes[C.BGP_CONFIG_PATH],
                )
            await self._activate_service(
                driver,
                FbossSystemctlServiceName.BGP,
                service_states["bgp"] == "active",
            )
            # R2 is applied after R1.  Do not release setup to the playbook
            # until the pair's physical core and loopback iBGP have actually
            # converged; systemd "active" alone only proves the daemons started.
            if role == "r2":
                await self._wait_for_pair_convergence(driver, hostname, core_pcs)
        except Exception as exc:  # noqa: BLE001
            try:
                await self._restore(driver, hostname)
            except Exception as rollback_exc:  # noqa: BLE001
                raise TestCaseFailure(
                    f"{hostname}: DUT bootstrap failed ({exc}); automatic rollback "
                    f"also failed ({rollback_exc}); recovery snapshots were retained"
                ) from exc
            raise TestCaseFailure(
                f"{hostname}: DUT bootstrap failed and was rolled back: {exc}"
            ) from exc
        self.logger.info(
            f"{hostname} -- temporary RBB core/OpenR/iBGP/SRv6 bootstrap applied"
        )

    async def _wait_for_pair_convergence(
        self,
        driver: t.Any,
        hostname: str,
        core_pcs: t.Sequence[CorePortChannel],
    ) -> None:
        """Bound setup on R2 by core-link and reciprocal iBGP convergence."""
        members = [member for pc in core_pcs for member in pc.members]
        expected_peer = C.R1_ROUTER_ID
        loop = asyncio.get_running_loop()
        deadline = loop.time() + _CONTROL_PLANE_TIMEOUT_SEC
        last_detail = "no observation"
        while True:
            try:
                states = await driver.async_get_interfaces_operational_state(members)
                links_up = all(states.get(member) is True for member in members)
                sessions = await driver.async_get_bgp_sessions()
                established = set()
                for session in sessions:
                    state = getattr(
                        getattr(session, "peer", None), "peer_state", None
                    )
                    state_name = getattr(state, "name", str(state)).rsplit(".", 1)[-1]
                    if state_name.upper() == "ESTABLISHED":
                        established.add(str(session.peer_addr))
                peer_up = expected_peer in established
                last_detail = (
                    f"links_up={links_up}, established_peers={sorted(established)}"
                )
                if links_up and peer_up:
                    self.logger.info(
                        f"{hostname} -- core links and iBGP peer {expected_peer} "
                        "converged"
                    )
                    return
            except Exception as exc:  # noqa: BLE001
                last_detail = f"read failed: {exc}"
            if loop.time() >= deadline:
                raise TestCaseFailure(
                    f"{hostname}: RBB bootstrap did not converge within "
                    f"{_CONTROL_PLANE_TIMEOUT_SEC}s ({last_detail})"
                )
            await asyncio.sleep(_CONTROL_PLANE_POLL_SEC)

    async def _activate_agent(self, driver: t.Any, was_active: bool) -> None:
        if was_active:
            try:
                await driver.async_agent_config_reload()
            except Exception as reload_exc:  # noqa: BLE001
                self.logger.info(
                    f"agent reload failed ({reload_exc}); restarting "
                    f"{FbossSystemctlServiceName.FBOSS_SW_AGENT.value}"
                )
                await driver.async_restart_service(
                    FbossSystemctlServiceName.FBOSS_SW_AGENT
                )
        else:
            await driver.async_start_service(FbossSystemctlServiceName.FBOSS_SW_AGENT)
        await driver.async_wait_for_agent_state_configured()

    @staticmethod
    async def _activate_service(
        driver: t.Any, service: FbossSystemctlServiceName, was_active: bool
    ) -> None:
        if was_active:
            await driver.async_restart_service(service)
        else:
            await driver.async_start_service(service)

    async def _restore(self, driver: t.Any, hostname: str) -> None:
        raw_state = await async_read_file_or_none(driver, C.BOOTSTRAP_STATE_PATH)
        state_entry_exists = await self._path_entry_exists(
            driver, hostname, C.BOOTSTRAP_STATE_PATH
        )
        snapshots_exist = False
        for path in _CONFIG_PATHS:
            backup = path + BOOTSTRAP_BACKUP_SUFFIX
            if await driver.async_check_if_file_exists(
                backup
            ) or await driver.async_check_if_file_exists(
                backup + ".missing"
            ) or await self._path_entry_exists(
                driver, hostname, backup
            ) or await self._path_entry_exists(
                driver, hostname, backup + ".missing"
            ):
                snapshots_exist = True
                break
        if raw_state is None:
            if state_entry_exists:
                raise TestCaseFailure(
                    f"{hostname}: bootstrap recovery path "
                    f"{C.BOOTSTRAP_STATE_PATH} is not a readable regular file; "
                    "refusing an inexact restore"
                )
            if snapshots_exist:
                raise TestCaseFailure(
                    f"{hostname}: bootstrap snapshots exist but "
                    f"{C.BOOTSTRAP_STATE_PATH} is missing; refusing an inexact restore"
                )
            self.logger.info(f"{hostname} -- no DUT bootstrap recovery state to restore")
            return
        try:
            state = json.loads(raw_state)
            if (
                not isinstance(state, dict)
                or state.get("version") != _STATE_VERSION
                or state.get("hostname") != hostname
            ):
                raise ValueError("identity/version mismatch")
            changed_paths = state["changed_paths"]
            service_states = state["service_active_state"]
            file_modes = state["file_modes"]
            file_owners = state["file_owners"]
            phase = state.get("phase")
            if (
                not isinstance(changed_paths, list)
                or not set(changed_paths).issubset(_CONFIG_PATHS)
                or len(changed_paths) != len(set(changed_paths))
                or not isinstance(service_states, dict)
                or set(service_states) != set(_SERVICES)
                or not isinstance(file_modes, dict)
                or set(file_modes) != set(_CONFIG_PATHS)
                or not isinstance(file_owners, dict)
                or set(file_owners) != set(_CONFIG_PATHS)
                or any(
                    not isinstance(file_modes[path], str)
                    or re.fullmatch(r"[0-7]{3,4}", file_modes[path]) is None
                    for path in _CONFIG_PATHS
                )
                or any(
                    not isinstance(file_owners[path], str)
                    or re.fullmatch(r"[0-9]+:[0-9]+", file_owners[path]) is None
                    for path in _CONFIG_PATHS
                )
                or any(
                    service_states.get(name) not in ("active", "inactive")
                    for name in _SERVICES
                )
                or phase not in ("snapshotting", "ready", "restored")
            ):
                raise ValueError("invalid fields")
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise TestCaseFailure(
                f"{hostname}: invalid bootstrap recovery state; refusing restore"
            ) from exc

        if phase == "snapshotting":
            # The apply path marks "ready" before its first live write, so a
            # snapshotting transaction can be safely abandoned as a whole.
            for path in changed_paths:
                await async_discard_backup(
                    driver, path, backup_suffix=BOOTSTRAP_BACKUP_SUFFIX
                )
            await async_remove_file(driver, C.BOOTSTRAP_STATE_PATH)
            self.logger.info(
                f"{hostname} -- discarded incomplete pre-write bootstrap snapshot"
            )
            return
        if phase == "restored":
            # Files and services already passed exact restoration; only an
            # interrupted artifact cleanup remains.
            for path in changed_paths:
                await async_discard_backup(
                    driver, path, backup_suffix=BOOTSTRAP_BACKUP_SUFFIX
                )
            await async_remove_file(driver, C.BOOTSTRAP_STATE_PATH)
            self.logger.info(f"{hostname} -- completed bootstrap artifact cleanup")
            return

        # Stop services that were originally inactive before putting their old
        # files back; this avoids briefly loading a restored placeholder file.
        for name in ("bgp", "openr"):
            if service_states[name] == "inactive":
                await driver.async_stop_service(_SERVICES[name])
        if service_states["agent"] == "inactive":
            await driver.async_stop_service(FbossSystemctlServiceName.FBOSS_SW_AGENT)

        for path in (C.BGP_CONFIG_PATH, C.OPENR_CONFIG_PATH, C.AGENT_CONFIG_PATH):
            if path in changed_paths:
                restored = await async_restore_backup(
                    driver,
                    path,
                    self.logger,
                    hostname,
                    backup_suffix=BOOTSTRAP_BACKUP_SUFFIX,
                    consume=False,
                )
                if not restored:
                    raise TestCaseFailure(
                        f"{hostname}: missing bootstrap snapshot for changed file {path}"
                    )
                await self._set_file_owner(
                    driver, hostname, path, file_owners[path]
                )
                await self._set_file_mode(
                    driver, hostname, path, file_modes[path]
                )

        if service_states["agent"] == "active":
            await self._activate_agent(driver, was_active=True)
        if service_states["openr"] == "active":
            await driver.async_restart_service(FbossSystemctlServiceName.OPENR)
        if service_states["bgp"] == "active":
            await driver.async_restart_service(FbossSystemctlServiceName.BGP)

        state["phase"] = "restored"
        await async_write_json_file(
            driver, C.BOOTSTRAP_STATE_PATH, state, hostname=hostname
        )
        for path in changed_paths:
            await async_discard_backup(
                driver, path, backup_suffix=BOOTSTRAP_BACKUP_SUFFIX
            )
        await async_remove_file(driver, C.BOOTSTRAP_STATE_PATH)
        self.logger.info(f"{hostname} -- DUT bootstrap restore complete")


__all__ = ["BOOTSTRAP_BACKUP_SUFFIX", "RbbDutBootstrapTask"]
