# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-strict
"""Unit tests for Open/R daemon gating in the BGP++ conveyor control-plane setup.

``_get_control_plane_tasks`` must enable the Open/R daemon only for the
``WITH_OPEN_R`` profile. For ``WITHOUT_OPEN_R`` no ``openr_config`` is deployed,
so the daemon is disabled (and never re-enabled) to avoid a config-less Open/R
daemon coring without contributing to BGP++ validation.
"""

import json
import unittest

from taac.constants import BgpPlusPlusProfile
from taac.testconfigs.routing.util.bgp_ebb_setup_tasks import (
    _get_control_plane_tasks,
)

_DEVICE = "bag012.ash6"


def _daemon_actions(tasks: list, daemon: str) -> list[str]:
    """Ordered list of actions issued against a given daemon."""
    actions: list[str] = []
    for task in tasks:
        if task.task_name != "arista_daemon_control":
            continue
        params = json.loads(task.params.json_params)
        if params["daemon_name"] == daemon:
            actions.append(str(params["action"]))
    return actions


class OpenRDaemonGatingTest(unittest.TestCase):
    def test_without_open_r_disables_and_does_not_enable(self) -> None:
        tasks = _get_control_plane_tasks(
            device_name=_DEVICE,
            profile=BgpPlusPlusProfile.BGP_PLUS_PLUS_WITHOUT_OPEN_R,
        )
        self.assertEqual(
            _daemon_actions(tasks, "Openr"),
            ["disable"],
            "WITHOUT_OPEN_R must disable Open/R and never re-enable it",
        )

    def test_with_open_r_bounces_daemon(self) -> None:
        tasks = _get_control_plane_tasks(
            device_name=_DEVICE,
            profile=BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R,
        )
        self.assertEqual(
            _daemon_actions(tasks, "Openr"),
            ["disable", "enable"],
            "WITH_OPEN_R must bounce Open/R (disable -> enable)",
        )

    def test_bgp_daemon_unaffected_by_gating(self) -> None:
        # Sanity: the Open/R gating must not change the Bgp daemon handling.
        # Bgp is bounced in the main daemon loop and again in the post-ACL
        # restart loop, for both profiles.
        for profile in (
            BgpPlusPlusProfile.BGP_PLUS_PLUS_WITHOUT_OPEN_R,
            BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R,
        ):
            tasks = _get_control_plane_tasks(device_name=_DEVICE, profile=profile)
            bgp_actions = _daemon_actions(tasks, "Bgp")
            self.assertIn("enable", bgp_actions, f"Bgp must be enabled ({profile})")
            self.assertIn("disable", bgp_actions, f"Bgp must be disabled ({profile})")
