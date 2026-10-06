# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
import json
import unittest

from taac.testconfigs.routing.util.bgp_ebb_constants import (
    BGPCPP_DAEMONS,
    FIBAGENT_BGP_CONF_DEVICE_PATH,
    FIBAGENT_CONF_DEVICE_PATH,
    THRIFT_ACL_FILES,
)
from taac.testconfigs.routing.util.bgp_ebb_setup_tasks import (
    BGP_RP_STATE_PATH,
    BGPCPP_CONFIG_PATH,
    BGPCPP_STARTUP_PATH,
    get_ebb_device_state_guard_tasks,
)


def _params(task) -> dict[str, object]:
    assert task.params is not None
    assert task.params.json_params is not None
    return json.loads(task.params.json_params)


class BgpEbbStateGuardTasksTest(unittest.TestCase):
    def test_snapshots_precede_one_dependency_aware_restore(self) -> None:
        setup_tasks, teardown_tasks = get_ebb_device_state_guard_tasks(
            device_name="bag012.ash6",
            operation_namespace="sc4",
        )

        self.assertEqual(
            "routing_component_snapshot", _params(setup_tasks[0])["action"]
        )
        self.assertTrue(
            all(
                _params(task)["action"] == "routing_config_snapshot"
                for task in setup_tasks[1:]
            )
        )
        self.assertEqual(1, len(teardown_tasks))
        self.assertEqual(
            "routing_component_restore",
            _params(teardown_tasks[0])["action"],
        )
        self.assertTrue(
            all(not task.ixia_needed for task in (*setup_tasks, *teardown_tasks))
        )

    def test_guard_preserves_files_and_ordered_daemon_state(self) -> None:
        setup_tasks, teardown_tasks = get_ebb_device_state_guard_tasks(
            device_name="bag012.ash6",
            operation_namespace="sc6",
        )

        component_snapshot = _params(setup_tasks[0])
        self.assertEqual(BGPCPP_STARTUP_PATH, component_snapshot["startup_path"])
        self.assertEqual(
            [*BGPCPP_DAEMONS, "BgpTcpdump"],
            component_snapshot["daemon_names"],
        )
        self.assertEqual(
            [
                BGPCPP_CONFIG_PATH,
                BGP_RP_STATE_PATH,
                "/usr/facebook/thrift_acls/auth_kill_switch_file",
                FIBAGENT_BGP_CONF_DEVICE_PATH,
                FIBAGENT_CONF_DEVICE_PATH,
                *THRIFT_ACL_FILES,
                "/mnt/fb/certs/AristaFibAgent_server.pem",
                "/mnt/fb/certs/Bgpcpp_server.pem",
                "/mnt/fb/certs/fb-openr_server.pem",
                "/tmp/peers.b64",
                "/tmp/experiment_peers.json",
            ],
            [_params(task)["destination"] for task in setup_tasks[1:]],
        )

        self.assertEqual(
            [
                "/usr/facebook/thrift_acls",
                "/mnt/fb/agent_configs",
                "/mnt/fb/certs",
            ],
            component_snapshot["directory_paths"],
        )
        self.assertEqual(
            [
                {"family": "ipv4", "chain": "EOS_BGP"},
                {"family": "ipv6", "chain": "EOS_BGP"},
            ],
            component_snapshot["firewall_chains"],
        )

        restore = _params(teardown_tasks[0])
        self.assertEqual(["Bgp"], restore["force_restart_daemons"])
        self.assertEqual(
            [
                {
                    "operation_id": _params(task)["operation_id"],
                    "destination": _params(task)["destination"],
                }
                for task in setup_tasks[1:]
            ],
            restore["file_restores"],
        )

    def test_guard_requires_operation_namespace(self) -> None:
        with self.assertRaisesRegex(ValueError, "operation_namespace"):
            get_ebb_device_state_guard_tasks(
                device_name="bag012.ash6",
                operation_namespace="",
            )
