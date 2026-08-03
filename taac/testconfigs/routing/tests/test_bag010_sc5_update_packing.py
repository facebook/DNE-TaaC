# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
import json
import unittest

from taac.testconfigs.routing.adhoc_bgp_ebb_characteristic import (
    BAG010_ASH6_SC5_UPDATE_PACKING_TEST_UPDATE_GROUP_CONFIG,
)
from taac.testconfigs.routing.cicd_ebb_int_tc import (
    BAG012_UPDATE_PACKING_TEST_CONFIG_UG,
)
from taac.testconfigs.routing.physical_inventory import (
    BAG010_ASH6,
)

_SC5 = BAG010_ASH6_SC5_UPDATE_PACKING_TEST_UPDATE_GROUP_CONFIG
# Pin to the CI-SCHEDULED bag012 config, not the ad-hoc ixia11 alias: the
# thing SC5 must not drift from is the test that actually runs in CI.
_BAG012 = BAG012_UPDATE_PACKING_TEST_CONFIG_UG
_PACKING_STEP = "test_bgp_update_packing_eos_bgp_plus_plus"


def _custom_step_params(config) -> list:
    """Params of every CUSTOM_STEP across the config's playbooks."""
    found = []
    for pb in config.playbooks or []:
        for stage in getattr(pb, "stages", None) or []:
            for step in stage.steps or []:
                step_params = getattr(step, "step_params", None)
                raw = getattr(step_params, "json_params", None) if step_params else None
                if raw:
                    params = json.loads(raw)
                    if params.get("custom_step_name"):
                        found.append(params)
    return found


class Sc5NameTest(unittest.TestCase):
    """SC5 is the bag010 mirror of the BAG012 update-packing test, so it needs an
    explicit SC-numbered name rather than the factory's derived one."""

    def test_sc5_name(self) -> None:
        self.assertEqual(_SC5.name, "BAG010_ASH6_SC5_UPDATE_PACKING_TEST_UPDATE_GROUP")


class Sc5MirrorsBag012Test(unittest.TestCase):
    """Mirror means MIRROR: same factory, same custom step, same scale and the
    same hard packing gate. Only the physical inventory differs. If BAG012's
    knobs are retuned, this test fails and forces SC5 to be retuned with it
    rather than silently drifting into a different test."""

    def test_same_custom_step_and_scale(self) -> None:
        sc5 = _custom_step_params(_SC5)
        bag012 = _custom_step_params(_BAG012)
        self.assertTrue(sc5, "SC5 must run a custom step")
        self.assertEqual(len(sc5), len(bag012))
        for a, b in zip(sc5, bag012):
            self.assertEqual(a.get("custom_step_name"), b.get("custom_step_name"))
            # Every knob except device identity and the per-config
            # anti-vacuousness floor must match BAG012. The floor is
            # deliberately NOT shared: it is calibrated per device, and pinning
            # bag012 to bag010's number is exactly the regression this diff
            # avoids (see Sc5AntiVacuousnessFloorIsPerConfigTest).
            for key in sorted(set(a) | set(b)):
                if key in ("hostname", "device_name", "min_advertised_nlri"):
                    continue
                self.assertEqual(a.get(key), b.get(key), f"knob {key} drifted")

    def test_runs_the_update_packing_step(self) -> None:
        names = {p.get("custom_step_name") for p in _custom_step_params(_SC5)}
        self.assertIn(_PACKING_STEP, names)


class Sc5WiringTest(unittest.TestCase):
    """The packing test is directional -- eBGP senders inject, a single iBGP peer
    captures what the DUT re-advertises -- so it needs bag010's two IXIA ports
    bound in that order."""

    def test_binds_bag010_two_port_wiring(self) -> None:
        # Assert membership, not order: the Endpoint's ixia_ports listing order
        # is not the eBGP/iBGP role order the factory passes them in.
        self.assertTrue(_SC5.endpoints, "SC5 must bind at least one endpoint")
        endpoint = (_SC5.endpoints or [])[0]
        self.assertEqual(endpoint.name, BAG010_ASH6.device_name)
        self.assertEqual(
            set(endpoint.ixia_ports or []),
            {BAG010_ASH6.ixia_ports[0][0], BAG010_ASH6.ixia_ports[1][0]},
        )


class Sc5AntiVacuousnessFloorIsPerConfigTest(unittest.TestCase):
    """The packing custom step is SHARED with the CI-scheduled bag012 config, so
    a floor calibrated on bag010 must not reach it. The step defaults the floor
    to 0 (gate evaluates, never breaches) and each config opts in with its own
    calibrated number -- otherwise landing this would silently gate an already
    scheduled test against a device it was never measured on.

    The floor counts ADVERTISED PREFIXES, not UPDATEs: UPDATE count falls as
    packing improves, so an UPDATE-count floor would fail a device that got
    better at the very thing this test measures."""

    def _floor(self, config):
        for params in _custom_step_params(config):
            if params.get("custom_step_name") == _PACKING_STEP:
                return params.get("min_advertised_nlri", 0)
        return None

    def test_sc5_opts_into_its_calibrated_floor(self) -> None:
        # bag010 advertised 99,875 prefixes; 50K floor is ~2x headroom.
        self.assertEqual(self._floor(_SC5), 50000)

    def test_bag012_is_not_gated_by_bag010_calibration(self) -> None:
        self.assertEqual(self._floor(_BAG012), 0)
