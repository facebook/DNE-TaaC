# pyre-strict
import importlib
import os
import unittest

TAAC_OSS: bool = os.environ.get("TAAC_OSS", "").lower() in ("1", "true", "yes")

# ShipIt rewrites import *statements* on export
# (neteng.test_infra.dne.taac. -> taac.) but not string literals, so the
# module name importlib is handed has to be chosen at runtime.
FBOSS_SWITCH_MODULE: str = (
    "taac.driver.fboss_switch"
    if TAAC_OSS
    else "neteng.test_infra.dne.taac.driver.fboss_switch"
)


class FbossSwitchImportTest(unittest.TestCase):
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
