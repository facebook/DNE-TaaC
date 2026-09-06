# Copyright (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe

"""Import/config regression for the twshared1375 replacement client."""

import importlib
import json
import os
import unittest
from unittest.mock import patch

from taac.testconfigs.fpf import (
    fpf_hardening_common,
    fpf_shared_injection_suite,
    fpf_tc21_prod_prefix_drain_link,
    fpf_tc25_wedge_agent_restart,
)


HOSTS = ["twshared1352.03.mwg2", "twshared1375.03.mwg2"]
ENV = {
    "FPF_GPU_HOSTS": ",".join(HOSTS),
    "FPF_HRT_DEVICE_IDS": "0,1,2,3,4,5,6,7",
    "FPF_HRT_LANES": "0,1,2,3",
    "FPF_HRT_VF1_DEVICE_IDS": "0,2,4,6",
    "FPF_HRT_VF2_DEVICE_IDS": "1,3,5,7",
    "TAAC_FPF_LINK_DRAIN_INTERFACE": "eth1/41/5",
    "TAAC_FPF_SKIP_IB_TRAFFIC": "1",
    "TAAC_FPF_SKIP_SSH_DEPS": "0",
}


def _collector_params(config) -> dict:
    task = next(
        task for task in config.setup_tasks if task.task_name == "fpf_start_collectors"
    )
    return json.loads(task.params.json_params)


def _task_params(config, task_name: str) -> dict:
    task = next(task for task in config.setup_tasks if task.task_name == task_name)
    return json.loads(task.params.json_params)


def _ensure_traffic_params(config) -> list[dict]:
    params = []
    for playbook in config.playbooks:
        for stage in playbook.stages:
            for step in stage.steps or []:
                if step.step_params is None or step.step_params.json_params is None:
                    continue
                step_params = json.loads(step.step_params.json_params)
                if step_params.get("custom_step_name") == "fpf_ensure_traffic":
                    params.append(step_params)
    return params


class FpfReplacementClientTest(unittest.TestCase):
    def test_ib_binary_default_blank_and_relative_validation(self) -> None:
        with patch.dict(os.environ):
            os.environ.pop("TAAC_FPF_IB_BINARY", None)
            self.assertEqual(
                fpf_hardening_common.fpf_ib_binary(),
                "/usr/bin/ib_write_bw",
            )
        with patch.dict(os.environ, {"TAAC_FPF_IB_BINARY": "   "}):
            self.assertEqual(
                fpf_hardening_common.fpf_ib_binary(),
                "/usr/bin/ib_write_bw",
            )
        with patch.dict(
            os.environ,
            {"TAAC_FPF_IB_BINARY": "tmp/fpf_ib_write_bw"},
        ):
            with self.assertRaisesRegex(ValueError, "absolute path"):
                fpf_hardening_common.fpf_ib_binary()

    def test_binary_override_reaches_shared_and_tc25_setup_and_ensure(self) -> None:
        binary_path = "/tmp/fpf_ib_write_bw"
        traffic_env = {
            **ENV,
            "TAAC_FPF_SKIP_IB_TRAFFIC": "0",
            "TAAC_FPF_IB_BINARY": binary_path,
            "TAAC_FPF_IB_DEVICE": "mlx5_bveth0",
        }
        try:
            with patch.dict(os.environ, traffic_env):
                importlib.reload(fpf_hardening_common)
                importlib.reload(fpf_shared_injection_suite)
                importlib.reload(fpf_tc25_wedge_agent_restart)

                for config in (
                    fpf_shared_injection_suite.create_fpf_shared_injection_suite_test_config(),
                    fpf_tc25_wedge_agent_restart.create_fpf_tc25_test_config(),
                ):
                    with self.subTest(config=config.name):
                        setup = _task_params(config, "fpf_start_ib_traffic")
                        self.assertEqual(setup["binary_path"], binary_path)
                        self.assertEqual(setup["device"], "mlx5_bveth0")
                        ensure_params = _ensure_traffic_params(config)
                        self.assertTrue(ensure_params)
                        self.assertTrue(
                            all(
                                params["binary_path"] == binary_path
                                for params in ensure_params
                            )
                        )
                        self.assertTrue(
                            all(
                                params["device"] == "mlx5_bveth0"
                                for params in ensure_params
                            )
                        )
        finally:
            importlib.reload(fpf_hardening_common)
            importlib.reload(fpf_shared_injection_suite)
            importlib.reload(fpf_tc25_wedge_agent_restart)

    def test_exact_environment_imports_shared_tc25_and_global_tc21(self) -> None:
        try:
            with patch.dict(os.environ, ENV):
                importlib.reload(fpf_hardening_common)
                importlib.reload(fpf_shared_injection_suite)
                importlib.reload(fpf_tc25_wedge_agent_restart)
                importlib.reload(fpf_tc21_prod_prefix_drain_link)

                shared = fpf_shared_injection_suite.create_fpf_shared_injection_suite_test_config()
                tc25 = fpf_tc25_wedge_agent_restart.create_fpf_tc25_test_config()
                tc21 = fpf_tc21_prod_prefix_drain_link.create_fpf_tc21_test_config()

                self.assertEqual(fpf_shared_injection_suite.GPU_HOSTS, HOSTS)
                self.assertEqual(fpf_tc25_wedge_agent_restart.GPU_HOSTS, HOSTS)
                self.assertEqual(fpf_tc21_prod_prefix_drain_link.GPU_HOSTS, HOSTS)
                self.assertEqual(
                    fpf_tc21_prod_prefix_drain_link.REMOTE_PREFIXES,
                    ["2401:db00:292a:a150::/64"],
                )
                self.assertEqual(
                    fpf_tc21_prod_prefix_drain_link.ALL_PROD_PREFIXES,
                    [
                        "2401:db00:292a:a27c::/64",
                        "2401:db00:292a:a150::/64",
                    ],
                )

                shared_params = _collector_params(shared)
                self.assertEqual(shared_params["hosts"], HOSTS)
                self.assertNotIn("prod_prefixes", shared_params)
                self.assertEqual(
                    shared_params["prod_prefixes_by_host"],
                    {host: ["2401:db00:292a:a27c::/64"] for host in HOSTS},
                )

                tc25_params = _collector_params(tc25)
                self.assertEqual(tc25_params["hosts"], HOSTS)
                self.assertEqual(
                    tc25_params["prod_prefixes"],
                    ["2401:db00:292a:a27c::/64"],
                )
                self.assertNotIn("prod_prefixes_by_host", tc25_params)
                self.assertEqual(
                    _collector_params(tc21)["prod_prefixes"],
                    [
                        "2401:db00:292a:a27c::/64",
                        "2401:db00:292a:a150::/64",
                    ],
                )
        finally:
            importlib.reload(fpf_hardening_common)
            importlib.reload(fpf_shared_injection_suite)
            importlib.reload(fpf_tc25_wedge_agent_restart)
            importlib.reload(fpf_tc21_prod_prefix_drain_link)


if __name__ == "__main__":
    unittest.main()
