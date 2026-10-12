# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""Tests for the OSS coop patcher's register / unregister / apply flow, against a
fake device that keeps its files in memory."""

import asyncio
import json
import logging
import os
import tempfile

from configerator.structs.neteng.fboss.bgp.bgp_config.thrift_types import (
    BgpConfig,
    PeerGroup,
)
from later.unittest import TestCase
from neteng.fboss.agent_config.thrift_types import AgentConfig
from neteng.fboss.switch_config.thrift_types import Port, SwitchConfig, VlanPort
from neteng.test_infra.dne.taac.driver import oss_coop_patcher as ocp
from taac.driver.config_modifiers import (
    deserialize_config,
    serialize_config,
)
from taac.driver.driver_constants import FbossSystemctlServiceName
from taac.driver.oss_patchers import PatcherError
from pyre_extensions import none_throws
from taac.test_as_a_config import types as taac_types

HOST = "dut1"
BGP_LIVE = ocp.CONFIG_SPECS["bgpcpp"].live_path
BGP_BASELINE = ocp.CONFIG_SPECS["bgpcpp"].baseline_path
AGENT_LIVE = ocp.CONFIG_SPECS["agent"].live_path
AGENT_BASELINE = ocp.CONFIG_SPECS["agent"].baseline_path
SOFTDRAIN_LIVE = ocp.CONFIG_SPECS["bgpcpp_softdrain"].live_path
SOFTDRAIN_BASELINE = ocp.CONFIG_SPECS["bgpcpp_softdrain"].baseline_path


class _FakeSwitch:
    """Just enough of FbossSwitch for oss_coop_patcher, over an in-memory fs.

    The shell understands only what the module and config_modifiers send:
    ``test -f``, ``cp -a``, ``mv -f``, ``rm -f`` and ``echo``, joined by ``&&``.
    """

    def __init__(self, files: dict) -> None:
        self.hostname = HOST
        self.logger = logging.getLogger(__name__)
        self.files = dict(files)
        self.reads = []
        self.events = []

    async def async_run_cmd_on_shell(self, cmd: str) -> str:
        cmd = cmd.split(" || ")[0]
        out = []
        for part in cmd.split(" && "):
            argv = part.split()
            if argv[:2] == ["test", "-f"]:
                ok = argv[2] in self.files
            elif argv[:2] == ["cp", "-a"]:
                ok = argv[2] in self.files
                if ok:
                    self.files[argv[3]] = self.files[argv[2]]
            elif argv[:2] == ["mv", "-f"]:
                ok = argv[2] in self.files
                if ok:
                    self.files[argv[3]] = self.files.pop(argv[2])
            elif argv[:2] == ["rm", "-f"]:
                self.files.pop(argv[2], None)
                ok = True
            elif argv[0] == "echo":
                out.append(argv[1])
                ok = True
            else:
                raise AssertionError(f"unexpected command: {part}")
            if not ok:
                break
        return "\n".join(out)

    async def async_read_file(self, path: str) -> str:
        self.reads.append(path)
        return self.files[path]

    async def async_write_file_on_device(self, text: str, path: str) -> None:
        self.events.append(("write", path))
        self.files[path] = text

    async def async_try_agent_config_reload(self) -> None:
        self.events.append(("reload_agent",))

    async def async_restart_service(self, service) -> None:
        self.events.append(("restart", service))

    async def async_wait_for_agent_configured(self) -> None:
        self.events.append(("wait_agent",))

    async def async_wait_for_bgp_convergence(self) -> None:
        self.events.append(("wait_bgp",))

    async def async_create_cold_boot_file(self) -> None:
        self.events.append(("cold_boot_file",))

    def bgp(self, path: str = BGP_LIVE) -> BgpConfig:
        return deserialize_config(BgpConfig, self.files[path], path)

    def agent(self, path: str = AGENT_LIVE) -> AgentConfig:
        return deserialize_config(AgentConfig, self.files[path], path)


def _baseline_bgp() -> BgpConfig:
    return BgpConfig(peer_groups=[PeerGroup(name="BASE")])


def _baseline_agent() -> AgentConfig:
    return AgentConfig(
        sw=SwitchConfig(
            ports=[Port(logicalID=1, name="eth1/1/1", ingressVlan=10)],
            vlanPorts=[VlanPort(vlanID=10, logicalPort=1)],
        )
    )


def _group_names(config: BgpConfig) -> list[str]:
    return [g.name for g in none_throws(config.peer_groups)]


def _peer_group(name: str, **args) -> ocp.OssPatcher:
    return ocp.OssPatcher(
        name=name,
        config_name="bgpcpp",
        py_func_name="add_peer_group_patcher",
        args={"name": name, **args},
    )


def _vlan_patcher() -> ocp.OssPatcher:
    return ocp.OssPatcher(
        name="vlan20",
        config_name="agent",
        py_func_name="configure_vlans",
        args={"vlan20": json.dumps({"vlan_id": 20, "ip_addresses": ["10.0.0.1/31"]})},
    )


class OssCoopPatcherTest(TestCase):
    def setUp(self) -> None:
        super().setUp()
        ocp.clear(HOST)
        self.addCleanup(ocp.clear, HOST)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.patcher_dir = tmp.name
        self.working_bgp = os.path.join(tmp.name, HOST, "bgpcpp.conf")
        self.switch = _FakeSwitch(
            {
                BGP_LIVE: serialize_config(_baseline_bgp()),
                AGENT_LIVE: serialize_config(_baseline_agent()),
            }
        )

    async def _register(self, patcher: ocp.OssPatcher) -> None:
        await ocp.async_register(self.switch, patcher, patcher_dir=self.patcher_dir)

    def _working_bgp(self) -> BgpConfig:
        with open(self.working_bgp) as f:
            return deserialize_config(BgpConfig, f.read(), self.working_bgp)

    async def test_first_register_snapshots_baseline_and_leaves_live_alone(
        self,
    ) -> None:
        await self._register(_peer_group("A"))

        self.assertEqual(self.switch.files[BGP_LIVE], self.switch.files[BGP_BASELINE])
        self.assertEqual(_baseline_bgp(), self.switch.bgp())
        self.assertEqual(["BASE", "A"], _group_names(self._working_bgp()))
        self.assertEqual([], self.switch.events)

    async def test_later_register_applies_only_the_new_patcher(self) -> None:
        await self._register(_peer_group("A"))
        await self._register(_peer_group("B"))

        self.assertEqual(["BASE", "A", "B"], _group_names(self._working_bgp()))
        # The baseline is read off the device once, at the first register.
        self.assertEqual([BGP_BASELINE], self.switch.reads)

    async def test_apply_installs_and_restarts_only_what_changed(self) -> None:
        await self._register(_peer_group("A"))
        await ocp.async_apply(self.switch)

        self.assertEqual(["BASE", "A"], _group_names(self.switch.bgp()))
        self.assertEqual(
            [
                ("write", BGP_LIVE),
                ("restart", FbossSystemctlServiceName.BGP),
                ("wait_bgp",),
            ],
            self.switch.events,
        )

        self.switch.events.clear()
        await ocp.async_apply(self.switch)
        self.assertEqual([], self.switch.events)

    async def test_unregister_rebuilds_from_baseline(self) -> None:
        await self._register(_peer_group("A"))
        await self._register(_peer_group("B"))

        self.assertTrue(await ocp.async_unregister(self.switch, "bgpcpp", "A"))

        self.assertEqual(["BASE", "B"], _group_names(self._working_bgp()))
        self.assertEqual(["B"], [p.name for p in ocp.list_patchers(HOST, "bgpcpp")])

    async def test_unregister_undoes_side_effects_on_unnamed_entries(self) -> None:
        # Moving a port rewrites its vlanPorts entry, which the patcher never
        # names; only a rebuild from the baseline gets the original back.
        vlan = ocp.OssPatcher(
            name="vlan20",
            config_name="agent",
            py_func_name="configure_vlans",
            args={
                "vlan20": json.dumps(
                    {"vlan_id": 20, "ip_addresses": ["10.0.0.1/31"], "ports": [1]}
                )
            },
        )
        await self._register(vlan)
        await self._register(_peer_group("A"))
        await ocp.async_apply(self.switch)
        self.assertEqual(20, self.switch.agent().sw.ports[0].ingressVlan)

        await ocp.async_unregister(self.switch, "agent", "vlan20")
        await ocp.async_apply(self.switch)

        sw = self.switch.agent().sw
        self.assertEqual(10, sw.ports[0].ingressVlan)
        self.assertEqual([10], [v.vlanID for v in sw.vlanPorts])
        self.assertNotIn(AGENT_BASELINE, self.switch.files)

    async def test_last_unregister_restores_baseline_on_device(self) -> None:
        await self._register(_peer_group("A"))
        await ocp.async_apply(self.switch)
        self.switch.events.clear()

        await ocp.async_unregister(self.switch, "bgpcpp", "A")

        self.assertEqual(_baseline_bgp(), self.switch.bgp())
        self.assertNotIn(BGP_BASELINE, self.switch.files)
        self.assertFalse(os.path.exists(self.working_bgp))
        self.assertEqual([], ocp.list_patchers(HOST, "bgpcpp"))

        await ocp.async_apply(self.switch)
        self.assertEqual(
            [("restart", FbossSystemctlServiceName.BGP), ("wait_bgp",)],
            self.switch.events,
        )

    async def test_reregistering_a_name_replaces_its_effect(self) -> None:
        await self._register(_peer_group("A", description="v1"))
        await self._register(_peer_group("B"))
        await self._register(_peer_group("A", description="v2"))

        groups = none_throws(self._working_bgp().peer_groups)
        self.assertEqual(["BASE", "A", "B"], [g.name for g in groups])
        self.assertEqual("v2", groups[1].description)

    async def test_existing_baseline_on_device_is_reused(self) -> None:
        # A run that never restored left the device patched.
        self.switch.files[BGP_BASELINE] = self.switch.files[BGP_LIVE]
        self.switch.files[BGP_LIVE] = serialize_config(
            BgpConfig(peer_groups=[PeerGroup(name="STALE")])
        )

        await self._register(_peer_group("A"))

        self.assertEqual(["BASE", "A"], _group_names(self._working_bgp()))

    async def test_failing_patcher_is_not_recorded(self) -> None:
        bad = ocp.OssPatcher(
            name="bad",
            config_name="bgpcpp",
            py_func_name="configure_bgp_peer_group",
            args={"name": "BASE", "attributes_to_update_json": '{"nope": 1}'},
        )
        with self.assertRaises(PatcherError):
            await self._register(bad)
        self.assertEqual([], ocp.list_patchers(HOST, "bgpcpp"))

    async def test_rejected_registrations(self) -> None:
        with self.assertRaises(NotImplementedError):
            await self._register(
                ocp.OssPatcher(name="x", config_name="bgpcpp", py_func_name="nope")
            )
        with self.assertRaises(ValueError):
            await self._register(
                ocp.OssPatcher(
                    name="x", config_name="agent", py_func_name="add_bgp_peers"
                )
            )
        with self.assertRaises(ValueError):
            await self._register(
                ocp.OssPatcher(
                    name="x", config_name="openr", py_func_name="add_bgp_peers"
                )
            )
        self.assertNotIn(BGP_BASELINE, self.switch.files)

    async def test_hard_drain_config_is_ignored(self) -> None:
        await self._register(
            ocp.OssPatcher(name="A", config_name="bgpcpp_drain", py_func_name="nope")
        )
        self.assertEqual({}, ocp._STATE.get(HOST, {}))

    async def test_softdrain_is_skipped_without_its_file(self) -> None:
        await self._register(
            ocp.OssPatcher(
                name="A",
                config_name="bgpcpp_softdrain",
                py_func_name="add_peer_group_patcher",
                args={"name": "A"},
            )
        )
        self.assertEqual([], ocp.list_patchers(HOST, "bgpcpp_softdrain"))
        self.assertNotIn(SOFTDRAIN_BASELINE, self.switch.files)

    async def test_patcher_sent_to_both_bgp_configs_patches_each(self) -> None:
        # What configure_parallel_bgp_peers does for a drainable host: one
        # register per config name, run concurrently.
        self.switch.files[SOFTDRAIN_LIVE] = serialize_config(
            BgpConfig(peer_groups=[PeerGroup(name="DRAIN_BASE")])
        )
        await asyncio.gather(
            *[
                self._register(
                    ocp.OssPatcher(
                        name="A",
                        config_name=config_name,
                        py_func_name="add_peer_group_patcher",
                        args={"name": "A"},
                    )
                )
                for config_name in ("bgpcpp", "bgpcpp_softdrain")
            ]
        )
        self.assertCountEqual(
            ["bgpcpp", "bgpcpp_softdrain"], ocp.find_configs(HOST, "A")
        )
        await ocp.async_apply(self.switch)

        self.assertEqual(["BASE", "A"], _group_names(self.switch.bgp()))
        self.assertEqual(
            ["DRAIN_BASE", "A"], _group_names(self.switch.bgp(SOFTDRAIN_LIVE))
        )
        self.assertEqual(
            [
                ("write", BGP_LIVE),
                ("write", SOFTDRAIN_LIVE),
                ("restart", FbossSystemctlServiceName.BGP),
                ("wait_bgp",),
            ],
            self.switch.events,
        )

        self.switch.events.clear()
        await ocp.async_restore_baselines(self.switch)
        self.assertEqual(["DRAIN_BASE"], _group_names(self.switch.bgp(SOFTDRAIN_LIVE)))
        self.assertNotIn(SOFTDRAIN_BASELINE, self.switch.files)
        self.assertEqual(
            [("restart", FbossSystemctlServiceName.BGP), ("wait_bgp",)],
            self.switch.events,
        )

    async def test_apply_methods(self) -> None:
        await ocp.async_apply(self.switch, taac_types.ApplyPatcherMethod.AGENT_WARMBOOT)
        self.assertEqual(
            [("restart", FbossSystemctlServiceName.AGENT), ("wait_agent",)],
            self.switch.events,
        )

        self.switch.events.clear()
        await ocp.async_apply(self.switch, coldboot=True)
        self.assertEqual(
            [
                ("cold_boot_file",),
                ("restart", FbossSystemctlServiceName.AGENT),
                ("wait_agent",),
            ],
            self.switch.events,
        )

    async def test_agent_change_reloads_by_default(self) -> None:
        await self._register(
            ocp.OssPatcher(
                name="vlan20",
                config_name="agent",
                py_func_name="configure_vlans",
                args={
                    "vlan20": json.dumps(
                        {"vlan_id": 20, "ip_addresses": ["10.0.0.1/31"]}
                    )
                },
            )
        )
        await ocp.async_apply(self.switch)
        self.assertEqual([("write", AGENT_LIVE), ("reload_agent",)], self.switch.events)

    async def test_agent_and_bgp_change_warmboots_the_agent_once(self) -> None:
        await self._register(_vlan_patcher())
        await self._register(_peer_group("A"))
        await ocp.async_apply(self.switch)

        self.assertEqual(
            [
                ("write", AGENT_LIVE),
                ("write", BGP_LIVE),
                ("restart", FbossSystemctlServiceName.AGENT),
                ("wait_agent",),
                ("wait_bgp",),
            ],
            self.switch.events,
        )

    async def test_agent_restart_covers_a_bgp_change(self) -> None:
        for method, coldboot in (
            (taac_types.ApplyPatcherMethod.AGENT_WARMBOOT, False),
            (None, True),
        ):
            with self.subTest(method=method, coldboot=coldboot):
                await self._register(_peer_group(f"A{coldboot}"))
                self.switch.events.clear()
                await ocp.async_apply(self.switch, method, coldboot=coldboot)
                self.assertNotIn(
                    ("restart", FbossSystemctlServiceName.BGP), self.switch.events
                )
                self.assertEqual(("wait_bgp",), self.switch.events[-1])

    async def test_agent_reload_still_restarts_bgp(self) -> None:
        await self._register(_vlan_patcher())
        await self._register(_peer_group("A"))
        await ocp.async_apply(self.switch, taac_types.ApplyPatcherMethod.AGENT_RELOAD)

        self.assertEqual(
            [
                ("write", AGENT_LIVE),
                ("write", BGP_LIVE),
                ("reload_agent",),
                ("restart", FbossSystemctlServiceName.BGP),
                ("wait_bgp",),
            ],
            self.switch.events,
        )

    async def test_restore_baselines_restores_and_restarts(self) -> None:
        await self._register(
            ocp.OssPatcher(
                name="vlan20",
                config_name="agent",
                py_func_name="configure_vlans",
                args={
                    "vlan20": json.dumps(
                        {"vlan_id": 20, "ip_addresses": ["10.0.0.1/31"], "ports": [1]}
                    )
                },
            )
        )
        await self._register(_peer_group("A"))
        await ocp.async_apply(self.switch)
        self.switch.events.clear()

        await ocp.async_restore_baselines(self.switch)

        self.assertEqual(_baseline_agent(), self.switch.agent())
        self.assertEqual(_baseline_bgp(), self.switch.bgp())
        self.assertNotIn(AGENT_BASELINE, self.switch.files)
        self.assertNotIn(BGP_BASELINE, self.switch.files)
        self.assertFalse(os.path.exists(self.working_bgp))
        self.assertEqual([], ocp.list_patchers(HOST, "agent"))
        self.assertEqual([], ocp.list_patchers(HOST, "bgpcpp"))
        # The agent warmboot restarts bgpd too (BindsTo=wedge_agent.service).
        self.assertEqual(
            [
                ("restart", FbossSystemctlServiceName.AGENT),
                ("wait_agent",),
                ("wait_bgp",),
            ],
            self.switch.events,
        )

    async def test_restore_baselines_restores_a_crashed_runs_baseline(self) -> None:
        # Nothing registered in this process; a dead run left bgpcpp patched.
        self.switch.files[BGP_BASELINE] = self.switch.files[BGP_LIVE]
        self.switch.files[BGP_LIVE] = serialize_config(
            BgpConfig(peer_groups=[PeerGroup(name="STALE")])
        )

        await ocp.async_restore_baselines(self.switch)

        self.assertEqual(_baseline_bgp(), self.switch.bgp())
        self.assertNotIn(BGP_BASELINE, self.switch.files)
        # The agent was never patched, so it is not warmbooted.
        self.assertEqual(
            [("restart", FbossSystemctlServiceName.BGP), ("wait_bgp",)],
            self.switch.events,
        )

    async def test_restore_baselines_retries_a_failed_activation(self) -> None:
        await self._register(_peer_group("A"))
        await ocp.async_apply(self.switch)
        self.switch.events.clear()
        restart = self.switch.async_restart_service

        async def fail_once(service) -> None:
            self.switch.async_restart_service = restart
            raise RuntimeError("bgpd did not restart")

        self.switch.async_restart_service = fail_once
        with self.assertRaisesRegex(RuntimeError, "did not restart"):
            await ocp.async_restore_baselines(self.switch)
        self.assertNotIn(BGP_BASELINE, self.switch.files)

        # The baseline is already back; the retry still restarts bgpd.
        await ocp.async_restore_baselines(self.switch)
        self.assertEqual(_baseline_bgp(), self.switch.bgp())
        self.assertEqual(
            [("restart", FbossSystemctlServiceName.BGP), ("wait_bgp",)],
            self.switch.events,
        )

    async def test_restore_baselines_on_a_clean_device_restarts_nothing(self) -> None:
        await ocp.async_restore_baselines(self.switch)
        self.assertEqual([], self.switch.events)

    async def test_restore_baselines_activates_an_unapplied_restore(self) -> None:
        # The last unregister restored the file but nobody applied it.
        await self._register(_peer_group("A"))
        await ocp.async_apply(self.switch)
        await ocp.async_unregister(self.switch, "bgpcpp", "A")
        self.switch.events.clear()

        await ocp.async_restore_baselines(self.switch)

        self.assertEqual(
            [("restart", FbossSystemctlServiceName.BGP), ("wait_bgp",)],
            self.switch.events,
        )
