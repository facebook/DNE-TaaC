# pyre-strict
import importlib
import importlib.util
import logging
import os
import typing as t
import unittest
from unittest.mock import patch

TAAC_OSS: bool = os.environ.get("TAAC_OSS", "").lower() in ("1", "true", "yes")

# ShipIt rewrites import *statements* on export
# (neteng.test_infra.dne.taac. -> taac.) but not string literals, so the
# module name importlib is handed has to be chosen at runtime.
# Internal Buck retains the source-tree package even when exercising an OSS-mode
# process; ShipIt rewrites it to taac.driver in the public tree.
_HAS_EXPORTED_DRIVER_PACKAGE = (
    TAAC_OSS and importlib.util.find_spec("taac.driver") is not None
)
FBOSS_SWITCH_MODULE: str = (
    "taac.driver.fboss_switch"
    if _HAS_EXPORTED_DRIVER_PACKAGE
    else "neteng.test_infra.dne.taac.driver.fboss_switch"
)


class FbossSwitchImportTest(unittest.IsolatedAsyncioTestCase):
    """Regression guard for fboss_switch_lib's runtime dependency closure.

    This target depends ONLY on ``:fboss_switch_lib`` — never directly on the
    modules that ``fboss_switch.py`` imports. A python_library does not validate
    imports at build time, so a missing dep only surfaces at runtime in
    consumers (e.g. the PWM statemachine worker crashed with
    ``ModuleNotFoundError: ...taac.utils.client_factory_interface``).

    Importing the module here, with fboss_switch_lib as the sole dependency,
    forces every top-level import of fboss_switch.py to be satisfied by
    fboss_switch_lib's own deps. If one is missing, this test fails instead of
    the failure leaking to production.
    """

    def test_import_fboss_switch(self) -> None:
        module = importlib.import_module(FBOSS_SWITCH_MODULE)
        self.assertTrue(hasattr(module, "FbossSwitch"))

    async def test_exact_kvstore_read_respects_oss_boundary(self) -> None:
        module = importlib.import_module(FBOSS_SWITCH_MODULE)
        method = module.FbossSwitch.async_get_openr_kvstore_keyvals
        self.assertTrue(callable(method))

        if TAAC_OSS:
            switch = module.FbossSwitch.__new__(module.FbossSwitch)
            switch.hostname = "oss-dut.example"
            switch.logger = logging.getLogger("test_fboss_switch_import")

            with patch.object(
                module,
                "get_openr_ctrl_cpp_client",
                create=True,
            ) as client_factory:
                with self.assertRaisesRegex(
                    NotImplementedError,
                    "OpenR KvStore operations require Meta-internal OpenR infrastructure",
                ):
                    await t.cast(
                        t.Coroutine[t.Any, t.Any, t.Any],
                        method(switch, ["adj:leaf-1"], "0"),
                    )

            client_factory.assert_not_called()
        else:
            self.assertEqual(
                "neteng.test_infra.dne.taac.driver.fboss_switch",
                module.__name__,
            )
