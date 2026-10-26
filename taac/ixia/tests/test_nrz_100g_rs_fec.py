# Copyright (c) Meta Platforms, Inc. and affiliates.

"""Unit tests for the 100G NRZ RS-FEC default applied after port assignment."""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from neteng.test_infra.dne.taac.ixia.ixia import DESIRED_VPORT_NAME, Ixia

NRZ_MODE = "aresOne-M-TwoByOneHundredGigNRZ-26G"
PAM4_MODE = "aresOne-M-EightByOneHundredGigPAM4-106G"
CARD_HREF = "/api/v1/sessions/1/ixnetwork/availableHardware/chassis/1/card/1"


def _make_vport(
    name: str,
    port_id: int = 261,
    speed: str = "speed100g",
    ieee_defaults: bool = True,
    rs_fec: bool = False,
    current_type: str = "aresOneM",
):
    settings = SimpleNamespace(
        Speed=speed, IeeeL1Defaults=ieee_defaults, EnableRsFec=rs_fec
    )
    vport = MagicMock()
    vport.Name = name
    vport.ConnectedTo = f"{CARD_HREF}/port/{port_id}"
    vport.L1Config.CurrentType = current_type
    vport.L1Config.AresOneM = settings
    vport.refresh.return_value = vport
    vport.ConnectionState = "connectedLinkDown"
    return vport


def _make_card(modes_by_port, card_mode: str = "mixed"):
    card = MagicMock()
    card.Aggregation.find.return_value = [
        SimpleNamespace(ActivePorts=[f"{CARD_HREF}/port/{port_id}"], Mode=mode)
        for port_id, mode in modes_by_port.items()
    ]
    card.AggregationMode = card_mode
    return card


def _create_ixia_instance(vports, card):
    with patch.object(Ixia, "__init__", lambda self: None):
        ixia = Ixia()
    ixia.logger = MagicMock()
    ixia.is_uhd_chassis = False
    ixia.auto_nrz_100g_rs_fec = True
    by_name = {vport.Name: vport for vport in vports}
    ixia.ixnetwork = MagicMock()
    ixia.ixnetwork.Vport.find.side_effect = lambda Name: by_name[Name]
    ixia.session = MagicMock()
    ixia.session.Session.GetObjectFromHref.return_value = card
    return ixia


def _port_config(port_name: str):
    return SimpleNamespace(port_name=port_name)


def _vport_name(port_name: str) -> str:
    return DESIRED_VPORT_NAME.format(
        port_identifier=Ixia.get_port_identifier(port_name)
    )


class ConfigureNrz100gRsFecTest(unittest.TestCase):
    def _setup(self, port_names, modes=None, **vport_kwargs):
        names = [_vport_name(p) for p in port_names]
        vports = [
            _make_vport(name, port_id=261 + i, **vport_kwargs)
            for i, name in enumerate(names)
        ]
        modes = modes or {261 + i: NRZ_MODE for i in range(len(names))}
        ixia = _create_ixia_instance(vports, _make_card(modes))
        return ixia, vports

    def test_down_nrz_port_comes_up_with_rs_fec(self):
        ixia, (vport,) = self._setup(["PORT_A"])
        ixia._wait_for_vports_link_up = MagicMock(side_effect=[set(), {vport.Name}])

        ixia.configure_nrz_100g_rs_fec([_port_config("PORT_A")])

        settings = vport.L1Config.AresOneM
        self.assertFalse(settings.IeeeL1Defaults)
        self.assertTrue(settings.EnableRsFec)

    def test_still_down_with_rs_fec_restores_ieee_defaults(self):
        ixia, (vport,) = self._setup(["PORT_A"])
        ixia._wait_for_vports_link_up = MagicMock(side_effect=[set(), set()])

        ixia.configure_nrz_100g_rs_fec([_port_config("PORT_A")])

        settings = vport.L1Config.AresOneM
        self.assertTrue(settings.IeeeL1Defaults)
        self.assertFalse(settings.EnableRsFec)
        ixia.logger.warning.assert_called_once()

    def test_port_up_on_ieee_defaults_is_left_alone(self):
        ixia, (vport,) = self._setup(["PORT_A"])
        ixia._wait_for_vports_link_up = MagicMock(return_value={vport.Name})

        ixia.configure_nrz_100g_rs_fec([_port_config("PORT_A")])

        settings = vport.L1Config.AresOneM
        self.assertTrue(settings.IeeeL1Defaults)
        self.assertFalse(settings.EnableRsFec)
        ixia._wait_for_vports_link_up.assert_called_once()

    def test_only_down_ports_get_rs_fec(self):
        ixia, (up_vport, down_vport) = self._setup(["PORT_A", "PORT_B"])
        ixia._wait_for_vports_link_up = MagicMock(
            side_effect=[{up_vport.Name}, {down_vport.Name}]
        )

        ixia.configure_nrz_100g_rs_fec([_port_config("PORT_A"), _port_config("PORT_B")])

        self.assertFalse(up_vport.L1Config.AresOneM.EnableRsFec)
        self.assertTrue(down_vport.L1Config.AresOneM.EnableRsFec)
        self.assertEqual(
            ixia._wait_for_vports_link_up.call_args_list[1].args[0], [down_vport]
        )

    def test_skipped_ports_never_wait(self):
        cases = {
            "pam4": {"modes": {261: PAM4_MODE}},
            "400g": {"speed": "speed400g"},
            "test_l1_settings": {"ieee_defaults": False},
            "rs_fec_already_on": {"rs_fec": True},
        }
        for label, kwargs in cases.items():
            with self.subTest(label):
                ixia, (vport,) = self._setup(["PORT_A"], **kwargs)
                ixia._wait_for_vports_link_up = MagicMock()

                ixia.configure_nrz_100g_rs_fec([_port_config("PORT_A")])

                ixia._wait_for_vports_link_up.assert_not_called()

    def test_disabled_or_uhd_does_nothing(self):
        for attribute, value in (
            ("auto_nrz_100g_rs_fec", False),
            ("is_uhd_chassis", True),
        ):
            with self.subTest(attribute):
                ixia, _ = self._setup(["PORT_A"])
                setattr(ixia, attribute, value)

                ixia.configure_nrz_100g_rs_fec([_port_config("PORT_A")])

                ixia.ixnetwork.Vport.find.assert_not_called()

    def test_lookup_failure_is_skipped_not_raised(self):
        ixia, _ = self._setup(["PORT_A"])
        ixia.ixnetwork.Vport.find.side_effect = RuntimeError("boom")
        ixia._wait_for_vports_link_up = MagicMock()

        ixia.configure_nrz_100g_rs_fec([_port_config("PORT_A")])

        ixia._wait_for_vports_link_up.assert_not_called()

    def test_configuration_failure_is_logged_not_raised(self):
        ixia, _ = self._setup(["PORT_A"])
        ixia._wait_for_vports_link_up = MagicMock(
            side_effect=[set(), RuntimeError("boom")]
        )

        ixia.configure_nrz_100g_rs_fec([_port_config("PORT_A")])

        ixia.logger.warning.assert_called_once()


class NrzDetectionTest(unittest.TestCase):
    def test_fcoe_type_uses_base_settings(self):
        vport = _make_vport("VPORT", current_type="aresOneMFcoe")
        ixia = _create_ixia_instance([vport], _make_card({261: NRZ_MODE}))

        self.assertIs(ixia._get_l1_speed_settings(vport), vport.L1Config.AresOneM)

    def test_resource_group_mode_of_active_port(self):
        vport = _make_vport("VPORT", port_id=263)
        ixia = _create_ixia_instance(
            [vport], _make_card({261: PAM4_MODE, 263: NRZ_MODE})
        )

        self.assertEqual(ixia._get_resource_group_mode(vport), NRZ_MODE)

    def test_resource_group_mode_falls_back_to_card_mode(self):
        vport = _make_vport("VPORT")
        ixia = _create_ixia_instance(
            [vport], _make_card({}, card_mode="novusHundredGigNonFanOut")
        )

        self.assertEqual(
            ixia._get_resource_group_mode(vport), "novusHundredGigNonFanOut"
        )
        self.assertTrue(ixia._is_nrz_100g_on_ieee_defaults(vport))


class WaitForVportsLinkUpTest(unittest.TestCase):
    @patch("neteng.test_infra.dne.taac.ixia.ixia.time")
    def test_returns_ports_that_came_up_before_timeout(self, mock_time):
        mock_time.monotonic.side_effect = [0, 0, 10, 40]
        up_later = _make_vport("UP_LATER")
        never_up = _make_vport("NEVER_UP")
        states = iter(["connectedLinkDown", "connectedLinkUp"])
        up_later.refresh.side_effect = lambda: SimpleNamespace(
            ConnectionState=next(states)
        )
        ixia = _create_ixia_instance([up_later, never_up], _make_card({}))

        up = ixia._wait_for_vports_link_up([up_later, never_up], timeout_seconds=30)

        self.assertEqual(up, {"UP_LATER"})


if __name__ == "__main__":
    unittest.main()
