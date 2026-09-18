# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""Restart ordering when the OSS coop patcher applies an ``agent`` config.

A lone ``systemctl restart fboss_sw_agent`` wedges a split-agent DUT: the sw
agent comes back and reconnects while the hw agent was never reset, so it hangs
in init and every port drops. ``configure_dut.sh`` avoids this by stopping the
whole stack and starting it together; the patcher apply path must not
reintroduce it.
"""

import importlib
import logging
import os
import unittest
from unittest import mock

TAAC_OSS = os.environ.get("TAAC_OSS", "").lower() in ("1", "true", "yes")

FBOSS_SWITCH_MODULE = (
    "taac.driver.fboss_switch"
    if TAAC_OSS
    else "neteng.test_infra.dne.taac.driver.fboss_switch"
)

fboss_switch = importlib.import_module(FBOSS_SWITCH_MODULE)
FbossSwitch = fboss_switch.FbossSwitch

from taac.driver import oss_coop_patcher as ocp
from taac.driver.config_modifiers import PREDRAIN_CONFIG_PATH


class CoopApplyRestartOrderingTest(unittest.IsolatedAsyncioTestCase):
    """``async_apply_patchers`` must not restart the sw agent on its own."""

    def setUp(self):
        self.host = "dut.example.com"
        ocp.clear(self.host)
        self.addCleanup(ocp.clear, self.host)

        self.switch = FbossSwitch(self.host, logging.getLogger(__name__))
        self.commands = []

        # Patched onto the class, so the bound instance arrives as the first
        # positional argument. The apply path gates on marker strings in the
        # output; emit all of them so the gates pass and the assertions can be
        # about which commands were issued, not about output parsing.
        # Which configs the DUT should look like it has applied. The restore
        # path probes for <stem>.patched.conf, so this decides whether teardown
        # restores a config or skips it as never-patched.
        self.patched_on_dut = {"agent", "bgpcpp"}

        async def fake_shell(_self, cmd, *args, **kwargs):
            self.commands.append(cmd)
            if cmd.startswith("[ -f "):
                # Derived from the registry rather than hardcoded, so a new
                # config name cannot silently probe as never-patched. Longest
                # first: "bgpcpp" is a prefix of "bgpcpp_softdrain".
                stem = next(
                    (
                        c
                        for c in sorted(ocp.CONFIG_FILES, key=len, reverse=True)
                        if f"{c}.patched.conf" in cmd
                    ),
                    None,
                )
                return "PATCHED\n" if stem in self.patched_on_dut else "CLEAN\n"
            return "OK 1 patcher(s)\nACTIVATED\nRESTARTED\n"

        self._stub("async_run_cmd_on_shell", fake_shell)
        self._stub_return("async_wait_for_agent_state_configured", None)
        # Split-agent restart primitives: stubbed so the real ordering logic
        # in async_restart_split_agents runs against a recorded command list.
        self._stub_return("async_is_multi_switch", True)
        self._stub_return("async_get_hw_agent_switch_indices", [0])
        self._stub_return("async_wait_for_service_exit", None)
        self._stub_return("async_wait_for_hw_agent_ready", 4242)
        self._stub_return("async_assert_hw_agent_stable", None)
        self._monotonic = iter(range(1, 100))
        self._stub(
            "async_get_service_monotonic_start_time",
            lambda *a, **k: self._next_monotonic(),
        )

    async def _next_monotonic(self):
        return next(self._monotonic)

    def _stub(self, name, fn):
        p = mock.patch.object(FbossSwitch, name, fn)
        p.start()
        self.addCleanup(p.stop)

    def _stub_return(self, name, value):
        async def _fn(*args, **kwargs):
            return value

        self._stub(name, _fn)

    def _register_agent_patcher(self):
        ocp.register(
            self.host,
            "agent",
            ocp.OssPatcher(
                name="configure_vlans",
                config_name="agent",
                py_func_name="configure_vlans",
                args={"vlan_id": "2100", "addresses": "[]"},
            ),
        )

    def _systemctl(self):
        return [c for c in self.commands if "systemctl" in c]

    async def test_agent_apply_does_not_bare_restart_sw_agent(self):
        self._register_agent_patcher()

        await self.switch.async_apply_patchers()

        bare = [
            c
            for c in self._systemctl()
            if "restart" in c and "fboss_sw_agent" in c
        ]
        self.assertEqual(
            bare,
            [],
            "agent config apply issued a lone sw-agent restart, which wedges a "
            f"split-agent DUT; commands were {self._systemctl()}",
        )

    async def test_agent_apply_stops_sw_agent_before_hw_agent(self):
        self._register_agent_patcher()

        await self.switch.async_apply_patchers()

        cmds = self._systemctl()
        stop_sw = next(
            i for i, c in enumerate(cmds) if "stop" in c and "fboss_sw_agent" in c
        )
        stop_hw = next(
            i for i, c in enumerate(cmds) if "stop" in c and "fboss_hw_agent@0" in c
        )
        self.assertLess(stop_sw, stop_hw, cmds)

    async def test_agent_apply_starts_hw_agent_before_sw_agent(self):
        self._register_agent_patcher()

        await self.switch.async_apply_patchers()

        cmds = self._systemctl()
        start_hw = next(
            i for i, c in enumerate(cmds) if "start" in c and "fboss_hw_agent@0" in c
        )
        start_sw = next(
            i for i, c in enumerate(cmds) if "start" in c and "fboss_sw_agent" in c
        )
        self.assertLess(start_hw, start_sw, cmds)

    async def test_restore_does_not_bare_restart_sw_agent(self):
        """Teardown restores every APPLIED config, so it hits the agent unit."""
        await self.switch.async_restore_patched_configs()

        # Guard against this negative assertion passing vacuously: the restore
        # must actually have run for the agent config.
        self.assertTrue(
            any("agent.baseline.conf" in c for c in self.commands),
            f"restore never ran for the agent config: {self.commands}",
        )

        bare = [
            c
            for c in self._systemctl()
            if "restart" in c and "fboss_sw_agent" in c
        ]
        self.assertEqual(
            bare,
            [],
            "teardown issued a lone sw-agent restart; commands were "
            f"{self._systemctl()}",
        )

    async def test_bgpcpp_apply_still_uses_a_plain_bgpd_restart(self):
        """bgpcpp is not the split-agent case; keep the cheap restart."""
        ocp.register(
            self.host,
            "bgpcpp",
            ocp.OssPatcher(
                name="configure_bgp_switch_limit",
                config_name="bgpcpp",
                py_func_name="configure_bgp_switch_limit",
                args={"prefix_limit": "100000"},
            ),
        )

        await self.switch.async_apply_patchers()

        self.assertIn(
            "systemctl restart bgpd && echo RESTARTED",
            self.commands,
        )


class CoopAgentColdBootTest(CoopApplyRestartOrderingTest):
    """An agent-config apply must COLD boot, not warm boot.

    A patcher that changes port config leaves warm-boot state that no longer
    matches the restored config; the sw agent aborts on warm-boot replay and
    crash-loops -- observed on hardware with status=6/ABRT, recovered
    only by configure_dut.sh's restore, which clears warm-boot state.
    The original trigger was configure_vlans moving ports between vlans at
    runtime; the IXIA vlans now ship in the testbed baseline, so that patcher
    is a no-op there. The hazard is NOT gone -- change_port_queue_config still
    rewrites port config -- so the cold boot stays.
    async_restart_split_agents is deliberately warmboot-SAFE, so the coop path
    has to clear the markers itself.
    """

    WARM_BOOT_GLOB = "/dev/shm/fboss/warm_boot/can_warm_boot"

    async def test_agent_apply_clears_warm_boot_state(self):
        self._register_agent_patcher()
        await self.switch.async_apply_patchers()
        clears = [c for c in self.commands if self.WARM_BOOT_GLOB in c and "rm " in c]
        self.assertTrue(
            clears,
            f"agent apply did not clear warm-boot state; commands were {self.commands}",
        )

    async def test_warm_boot_cleared_between_the_stops_and_the_starts(self):
        """Placement matters. Clearing before the stops is not enough: the hw
        agent regenerates warm-boot state when it starts, and the sw agent then
        warm-boots into the same mismatch. That is what left the DUT with one
        core-dump per teardown even after the first version of this fix.
        configure_dut.sh's restart_stack clears between stop-all and start-all;
        do the same.
        """
        self._register_agent_patcher()
        await self.switch.async_apply_patchers()
        idx = lambda pred: next(
            i for i, c in enumerate(self.commands) if pred(c)
        )
        stop_hw = idx(lambda c: "systemctl stop" in c and "fboss_hw_agent@0" in c)
        clear = idx(lambda c: self.WARM_BOOT_GLOB in c and "rm " in c)
        start_hw = idx(lambda c: "systemctl start" in c and "fboss_hw_agent@0" in c)
        self.assertLess(stop_hw, clear, f"clear must follow the stops: {self.commands}")
        self.assertLess(clear, start_hw, f"clear must precede the starts: {self.commands}")

    async def test_clear_agent_warm_boot_false_keeps_the_boot_warm(self):
        """The caller owning the boot type must reach async_restart_service.

        ``async_apply_patchers`` absorbs ``**kwargs``, so a misspelled or
        renamed ``clear_agent_warm_boot`` is discarded in silence and the
        default cold boot applies -- the exact silent warm-to-cold downgrade
        the keyword exists to prevent. Assert the plumbing, not the signature.
        """
        self._register_agent_patcher()
        await self.switch.async_apply_patchers(clear_agent_warm_boot=False)
        self.assertEqual(
            [c for c in self.commands if self.WARM_BOOT_GLOB in c],
            [],
            f"warm-boot state was cleared anyway; commands were {self.commands}",
        )
        # Guard against a vacuous pass: the agent still has to be restarted.
        self.assertTrue(
            any("systemctl start fboss_sw_agent" in c for c in self.commands),
            f"agent was never restarted at all: {self._systemctl()}",
        )

    async def test_clear_agent_warm_boot_false_does_not_refuse_on_monolithic(self):
        """The cold-boot refusal must not fire when no cold boot was asked for.

        A monolithic DUT (or async_is_multi_switch swallowing a transient
        thrift error) takes the single-service path, which raises for a cold
        boot. A warm boot there is legitimate: systemctl restart warm boots.
        """
        self._stub_return("async_is_multi_switch", False)
        self._register_agent_patcher()
        await self.switch.async_apply_patchers(clear_agent_warm_boot=False)
        self.assertTrue(
            any("systemctl restart wedge_agent" in c for c in self.commands),
            f"agent was not restarted on the single-service path: {self.commands}",
        )
        self.assertEqual(
            [c for c in self.commands if self.WARM_BOOT_GLOB in c], []
        )

    async def test_bgpcpp_apply_does_not_touch_warm_boot_state(self):
        """bgpd carries no warm-boot state; clearing it would force a needless
        cold boot of the data plane."""
        ocp.register(
            self.host,
            "bgpcpp",
            ocp.OssPatcher(
                name="configure_bgp_switch_limit",
                config_name="bgpcpp",
                py_func_name="configure_bgp_switch_limit",
                args={"prefix_limit": "100000"},
            ),
        )
        await self.switch.async_apply_patchers()
        self.assertEqual(
            [c for c in self.commands if self.WARM_BOOT_GLOB in c], []
        )

    async def test_cold_boot_refused_when_split_path_not_taken(self):
        """A cold boot that cannot be honoured must RAISE, not warm boot.

        Only the split-agent path can force a cold boot: the agent rewrites
        can_warm_boot as it shuts down, so clearing around a single
        `systemctl restart` is undone before the process comes up. On an
        all-split-agent fleet, reaching the single-service path means
        `async_is_multi_switch` returned False -- and it swallows every
        exception, so a transient thrift failure during a coop apply looks
        identical to monolithic hardware. Failing loudly beats warm-booting
        into a config the restored agent no longer has.
        """
        self._stub_return("async_is_multi_switch", False)
        self._register_agent_patcher()
        with self.assertRaises(RuntimeError) as ctx:
            await self.switch.async_apply_patchers()
        self.assertIn("cold boot requested", str(ctx.exception))
        # Nothing may have been cleared, and the agent must not have been
        # restarted behind the refusal.
        self.assertEqual(
            [c for c in self.commands if self.WARM_BOOT_GLOB in c], []
        )

    async def test_non_agent_restart_still_uses_single_service_path(self):
        """The refusal is scoped to cold-boot requests only."""
        self._stub_return("async_is_multi_switch", False)
        await self.switch.async_restart_service(
            fboss_switch.FbossSystemctlServiceName.BGP
        )
        self.assertTrue(
            any("systemctl restart bgpd" in c for c in self.commands),
            f"expected a plain bgpd restart: {self.commands}",
        )

    async def test_restore_skips_a_config_that_was_never_applied(self):
        """A bgpcpp-only test must not pay an agent cold boot on teardown.

        The registry is cleared by teardown, so the applied set is read off the
        DUT: <stem>.patched.conf is written only by an apply.
        """
        self.patched_on_dut = {"bgpcpp"}
        await self.switch.async_restore_patched_configs()

        self.assertFalse(
            any("agent.baseline.conf" in c for c in self.commands),
            f"restored an agent config that was never applied: {self.commands}",
        )
        self.assertEqual(
            [c for c in self.commands if self.WARM_BOOT_GLOB in c],
            [],
            f"cold-booted the agent for a bgpcpp-only run: {self.commands}",
        )
        self.assertTrue(
            any("bgpcpp.baseline.conf" in c for c in self.commands),
            f"bgpcpp was applied and must still be restored: {self.commands}",
        )


def test_unregister_python_patcher_delegates_to_coop(monkeypatch):
    """RegisterPatcherStep calls this name; OSS only had the coop variant."""
    import asyncio
    from unittest.mock import AsyncMock
    from taac.driver.fboss_switch import FbossSwitch

    sw = FbossSwitch.__new__(FbossSwitch)
    sw.async_coop_unregister_patchers = AsyncMock()
    # positional order must match step_definitions.py:10579
    asyncio.run(sw.async_unregister_python_patcher("p1", "agent"))
    sw.async_coop_unregister_patchers.assert_awaited_once_with(
        patcher_name="p1", config_name="agent"
    )
    # and the keyword form used at step_definitions.py:9986
    sw.async_coop_unregister_patchers.reset_mock()
    asyncio.run(sw.async_unregister_python_patcher(config_name="agent", patcher_name="p2"))
    sw.async_coop_unregister_patchers.assert_awaited_once_with(
        patcher_name="p2", config_name="agent"
    )


def test_apply_patchers_can_skip_the_restart():
    """restart_services=False must still write+activate, but not restart."""
    import asyncio, inspect
    from taac.driver.fboss_switch import FbossSwitch

    sig = inspect.signature(FbossSwitch.async_apply_patchers)
    assert "restart_services" in sig.parameters
    assert sig.parameters["restart_services"].default is True


class CoopRestoreNonRunningConfigTest(CoopApplyRestartOrderingTest):
    """Teardown for a config no service reads: remove it, do not restore it.

    It did not exist before the run, so a restored baseline is a leftover -- and
    the apply seeds it only when absent, so the next run would rebase on this
    run's output instead of on a fresh copy of the live config.
    """

    def setUp(self):
        super().setUp()
        self.patched_on_dut = {"agent", "bgpcpp", "bgpcpp_softdrain"}

    def _removals(self):
        return [c for c in self.commands if c.startswith("rm -f ")]

    async def test_softdrain_config_and_its_variants_are_removed(self):
        await self.switch.async_restore_patched_configs()

        live, baseline, patched = ocp.variant_paths("bgpcpp_softdrain")
        removed = " ".join(self._removals())
        for path in (live, baseline, patched):
            self.assertIn(path, removed, f"{path} left behind: {self._removals()}")

    async def test_softdrain_config_is_not_restored_from_a_baseline(self):
        await self.switch.async_restore_patched_configs()

        _, baseline, _ = ocp.variant_paths("bgpcpp_softdrain")
        restores = [c for c in self.commands if c.startswith("if [ -f ")]
        self.assertFalse(
            [c for c in restores if baseline in c],
            f"teardown restored a config no service reads: {restores}",
        )

    async def test_no_service_is_restarted_for_it(self):
        # bgpd is running the live config; restarting it to tear down a file it
        # never opened would bounce sessions for nothing.
        self.patched_on_dut = {"bgpcpp_softdrain"}
        self.commands.clear()

        await self.switch.async_restore_patched_configs()

        # Guard against this negative assertion passing vacuously. Without it
        # the test is green even with the removal branch deleted, because the
        # pre-existing `elif service is not None` already suppresses the
        # restart -- so it would pin a contract this change does not own.
        live, _, _ = ocp.variant_paths("bgpcpp_softdrain")
        self.assertTrue(
            [c for c in self._removals() if live in c],
            f"the removal branch never ran: {self.commands}",
        )
        self.assertEqual(
            [], [c for c in self.commands if "restart" in c], self.commands
        )

    async def test_the_parked_undrained_config_is_removed(self):
        # A run that died between drain and undrain leaves it behind, and the
        # restore above has just put the pristine config back.
        await self.switch.async_restore_patched_configs()

        self.assertTrue(
            [c for c in self._removals() if PREDRAIN_CONFIG_PATH in c],
            f"parked config left behind: {self._removals()}",
        )

    async def test_the_parked_config_survives_when_bgpcpp_was_not_restored(self):
        # Removing it while the device may still be drained would discard the
        # only copy of the undrained config.
        self.patched_on_dut = {"bgpcpp_softdrain"}
        self.commands.clear()

        await self.switch.async_restore_patched_configs()

        self.assertFalse(
            [c for c in self._removals() if PREDRAIN_CONFIG_PATH in c],
            f"parked config removed without restoring bgpcpp: {self._removals()}",
        )
