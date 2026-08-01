# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-strict
"""Regression test for BGP++ conveyor daemon-restart ORDER.

BGP++ (the ``Bgp`` daemon) programs routes into ``FibAgentBgp`` and resolves
nexthops via the Open-R FIB agent. The control-plane setup must therefore
(re)start the FIB / Open-R agents BEFORE ``Bgp`` -- otherwise BGP++ comes up and
converges its full RIB before its FIB agent exists, and the FIB agent is then
restarted out from under it, leaving BGP++ unable to program at init
("Fib agent is not connected. Skipping fib batch programming."). See
T274256815. This pins the FibAgentBgp-before-Bgp invariant for every BGP++
profile, since the daemon restart is the shared control-plane setup used by all
conveyor-onboarded BGP++ tests.
"""

import json
import unittest

from taac.constants import BgpPlusPlusProfile
from taac.testconfigs.routing.util.bgp_ebb_constants import (
    ADD_INTERN_USER_IDS_CMD,
    BGPCPP_DAEMONS,
    UPDATE_GROUP_VERIFICATION_CMD,
)
from taac.testconfigs.routing.util.bgp_ebb_setup_tasks import (
    _get_control_plane_tasks,
    get_common_setup_tasks,
    get_teardown_tasks,
)

_DEVICE = "bag012.ash6"

# FIB agents and their gRPC backends that BGP++ depends on at runtime; each must
# be (re)started before Bgp. Openr is intentionally excluded: it is gated off
# (disable-only) for the WITHOUT_OPEN_R profile, so it has no enable to order
# against. RouteGrpc is excluded because it backs the EOS RouteAgent (route
# injection), not the BGP++ FIB-programming path.
_FIB_DEPENDENCY_DAEMONS = [
    "FibGrpc",
    "FibBgpGrpc",
    "FibAgent",
    "FibAgentBgp",
]


def _first_enable_index(tasks: list, daemon: str) -> int:
    """Position of the daemon's first ``enable`` action among the emitted
    ``arista_daemon_control`` tasks, or -1 if it is never enabled."""
    idx = 0
    for task in tasks:
        if task.task_name != "arista_daemon_control":
            continue
        params = json.loads(task.params.json_params)
        if params["daemon_name"] == daemon and params["action"] == "enable":
            return idx
        idx += 1
    return -1


def _daemon_actions(tasks: list) -> list[tuple[str, str]]:
    actions = []
    for task in tasks:
        if task.task_name != "arista_daemon_control":
            continue
        params = json.loads(task.params.json_params)
        actions.append((params["daemon_name"], params["action"]))
    return actions


def _shell_commands(task) -> list[str]:
    if task.task_name != "run_commands_on_shell":
        return []
    return json.loads(task.params.json_params)["cmds"]


class ConveyorDaemonRestartOrderTest(unittest.TestCase):
    def test_bgpcpp_daemons_lists_bgp_last(self) -> None:
        # Single source of truth for the order: Bgp must be last so its FIB /
        # Open-R dependencies are restarted first.
        self.assertEqual(
            BGPCPP_DAEMONS[-1],
            "Bgp",
            "Bgp must be the LAST entry in BGPCPP_DAEMONS so FibAgentBgp (and the "
            "other FIB/Open-R agents) are restarted before it",
        )
        for dep in ("FibAgent", "FibAgentBgp"):
            self.assertLess(
                BGPCPP_DAEMONS.index(dep),
                BGPCPP_DAEMONS.index("Bgp"),
                f"{dep} must come before Bgp in BGPCPP_DAEMONS",
            )

    def test_grpc_backends_listed_before_their_fib_agents(self) -> None:
        # Each EosSdkRpc gRPC backend must be (re)started before the FIB agent
        # that connects to it: FibBgpGrpc (9545) backs FibAgentBgp (5913), and
        # FibGrpc (9544) backs FibAgent (5912).
        for backend, agent in (("FibBgpGrpc", "FibAgentBgp"), ("FibGrpc", "FibAgent")):
            self.assertLess(
                BGPCPP_DAEMONS.index(backend),
                BGPCPP_DAEMONS.index(agent),
                f"{backend} must come before {agent} in BGPCPP_DAEMONS",
            )

    def test_routegrpc_excluded(self) -> None:
        # RouteGrpc backs the EOS RouteAgent (route injection), not the BGP++
        # FIB-programming path, so it must not be bounced by the BGP++ conveyor
        # control-plane setup. See T274256815.
        self.assertNotIn("RouteGrpc", BGPCPP_DAEMONS)

    def test_fib_agents_enabled_before_bgp_in_emitted_tasks(self) -> None:
        # End-to-end: the emitted arista_daemon_control tasks must enable Bgp
        # only after every FIB-dependency daemon has been enabled, for both
        # profiles.
        for profile in (
            BgpPlusPlusProfile.BGP_PLUS_PLUS_WITHOUT_OPEN_R,
            BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R,
        ):
            tasks = _get_control_plane_tasks(device_name=_DEVICE, profile=profile)
            bgp_enable = _first_enable_index(tasks, "Bgp")
            self.assertGreaterEqual(bgp_enable, 0, f"Bgp must be enabled ({profile})")
            for dep in _FIB_DEPENDENCY_DAEMONS:
                dep_enable = _first_enable_index(tasks, dep)
                self.assertGreaterEqual(
                    dep_enable, 0, f"{dep} must be enabled ({profile})"
                )
                self.assertLess(
                    dep_enable,
                    bgp_enable,
                    f"{dep} must be enabled before Bgp ({profile})",
                )

    def test_consolidated_acl_path_has_one_ordered_daemon_cycle(self) -> None:
        tasks = _get_control_plane_tasks(
            device_name=_DEVICE,
            profile=BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R,
            enable_update_group=True,
            consolidate_acl_restart=True,
        )

        daemon_actions = _daemon_actions(tasks)
        self.assertEqual(
            [(daemon, "disable") for daemon in reversed(BGPCPP_DAEMONS)]
            + [(daemon, "enable") for daemon in BGPCPP_DAEMONS],
            daemon_actions,
        )
        for daemon in ("FibAgent", "FibAgentBgp", "Openr", "Bgp"):
            self.assertEqual(
                ["disable", "enable"],
                [action for name, action in daemon_actions if name == daemon],
            )

    def test_explicit_rollback_path_retains_two_agent_and_bgp_cycles(self) -> None:
        tasks = _get_control_plane_tasks(
            device_name=_DEVICE,
            profile=BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R,
            consolidate_acl_restart=False,
        )
        daemon_actions = _daemon_actions(tasks)

        for daemon in ("FibAgent", "FibAgentBgp", "Bgp"):
            self.assertEqual(
                ["disable", "enable", "disable", "enable"],
                [action for name, action in daemon_actions if name == daemon],
            )
        self.assertEqual(
            ["disable", "enable"],
            [action for name, action in daemon_actions if name == "Openr"],
        )

    def test_consolidated_acl_path_patches_before_and_verifies_after(self) -> None:
        tasks = _get_control_plane_tasks(
            device_name=_DEVICE,
            profile=BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R,
            enable_update_group=True,
            consolidate_acl_restart=True,
        )

        first_daemon_index = next(
            index
            for index, task in enumerate(tasks)
            if task.task_name == "arista_daemon_control"
        )
        acl_patch_index = next(
            index
            for index, task in enumerate(tasks)
            if ADD_INTERN_USER_IDS_CMD in _shell_commands(task)
        )
        last_daemon_index = max(
            index
            for index, task in enumerate(tasks)
            if task.task_name == "arista_daemon_control"
        )
        update_group_verification_index = next(
            index
            for index, task in enumerate(tasks)
            if UPDATE_GROUP_VERIFICATION_CMD in _shell_commands(task)
        )

        self.assertLess(acl_patch_index, first_daemon_index)
        self.assertGreater(update_group_verification_index, last_daemon_index)
        self.assertEqual("run_commands_on_shell", tasks[-2].task_name)
        self.assertEqual("run_commands_on_shell", tasks[-1].task_name)
        self.assertEqual(
            [UPDATE_GROUP_VERIFICATION_CMD],
            _shell_commands(tasks[-1]),
        )

    def test_common_setup_exposes_consolidated_acl_path(self) -> None:
        tasks = get_common_setup_tasks(
            device_name=_DEVICE,
            bgp_asn=65000,
            ixia_interface_mimic_ebgp="Ethernet1/1",
            ixia_interface_mimic_ibgp="Ethernet1/2",
            bgpcpp_configerator_path="taac/test/bgpcpp_config",
            profile=BgpPlusPlusProfile.BGP_PLUS_PLUS_WITHOUT_OPEN_R,
            include_bgp_mon=False,
            enable_update_group=True,
        )
        daemon_actions = _daemon_actions(tasks)

        for daemon in ("FibAgent", "FibAgentBgp", "Bgp"):
            self.assertEqual(
                ["disable", "enable"],
                [action for name, action in daemon_actions if name == daemon],
            )

    def test_teardown_restores_whole_device_backups_in_reverse_order(self) -> None:
        tasks = get_teardown_tasks(
            ixia_interface_mimic_ebgp="Ethernet1/1",
            ixia_interface_mimic_ibgp="Ethernet1/2",
            ixia_interface_mimic_bgp_mon="Ethernet1/3",
            device_name=_DEVICE,
        )
        interfaces = []
        for task in tasks:
            json_params = task.params.json_params
            if json_params is None:
                raise AssertionError("teardown task is missing JSON parameters")
            interfaces.append(json.loads(json_params)["interfaces"][0])
        self.assertEqual(["Ethernet1/3", "Ethernet1/2", "Ethernet1/1"], interfaces)

        tasks = get_teardown_tasks(
            ixia_interface_mimic_ebgp="Ethernet1/1",
            ixia_interface_mimic_ibgp="Ethernet1/2",
            device_name=_DEVICE,
        )
        interfaces = []
        for task in tasks:
            json_params = task.params.json_params
            if json_params is None:
                raise AssertionError("teardown task is missing JSON parameters")
            interfaces.append(json.loads(json_params)["interfaces"][0])
        self.assertEqual(["Ethernet1/2", "Ethernet1/1"], interfaces)
