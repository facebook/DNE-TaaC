# pyre-unsafe

"""Ensure every OSS test config is loadable without runtime env vars.

Each config's factory function is called at discovery time — without
TAAC_DUT or other runtime env vars set.  Configs must handle that
gracefully (e.g. by falling back to placeholders) so that dry-run /
topology inspection never crashes on a missing env var.

This test discovers all .py config files under taac/testconfigs/oss/ and
asserts that loading each one succeeds and returns at least one TestConfig.
"""

import importlib.util
import os
import unittest
from pathlib import Path

_OSS_CONFIGS_DIR = Path(__file__).resolve().parents[2] / "testconfigs" / "oss"


def _load_configs_from_file(path: Path) -> list:
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    from taac.test_as_a_config import (
        thrift_types as _taac_thrift_types,
        types as _taac_types,
    )

    _testconfig_classes = (_taac_thrift_types.TestConfig, _taac_types.TestConfig)

    for attr_name in ["test_config", "TEST_CONFIG", "config", "CONFIG"]:
        if hasattr(module, attr_name):
            val = getattr(module, attr_name)
            if callable(val) and not isinstance(val, _testconfig_classes):
                if getattr(val, "_accepts_topology", False):
                    from taac.runner.testbed_topology import (
                        ConfigTopology,
                    )

                    val = val(topology=ConfigTopology())
                else:
                    val = val()
            if isinstance(val, _testconfig_classes):
                return [val]

    results = []
    for _, val in vars(module).items():
        if isinstance(val, _testconfig_classes):
            results.append(val)
        elif isinstance(val, (list, tuple)):
            for item in val:
                if isinstance(item, _testconfig_classes):
                    results.append(item)
    return results


class TestOssConfigDryRun(unittest.TestCase):
    def test_all_oss_configs_loadable_without_runtime_env(self):
        env = os.environ.copy()
        env.pop("TAAC_DUT", None)
        os.environ.clear()
        os.environ.update(env)

        config_files = sorted(_OSS_CONFIGS_DIR.glob("*.py"))
        config_files = [f for f in config_files if f.name != "__init__.py"]
        self.assertTrue(config_files, "No OSS config files found to test")

        for config_path in config_files:
            with self.subTest(config=config_path.name):
                configs = _load_configs_from_file(config_path)
                self.assertIsInstance(configs, list)
                self.assertGreater(
                    len(configs), 0, f"{config_path.name} returned no configs"
                )


if __name__ == "__main__":
    unittest.main()
