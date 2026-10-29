# Copyright (c) Meta Platforms, Inc. and affiliates.

import itertools
import typing as t
import unittest
from types import SimpleNamespace
from unittest.mock import ANY, MagicMock, patch

from neteng.test_infra.dne.taac.ixia.ixia import Ixia, IxiaPortUnavailableError


def _ixia() -> Ixia:
    with patch.object(Ixia, "__init__", lambda self: None):
        ixia = Ixia()
    ixia.logger = MagicMock()
    return ixia


class _FakeL1Family:
    """Records update() kwargs; mimics e.g. AresOneM with RS-FEC knobs."""

    EnableRsFec = False

    def __init__(self) -> None:
        self.update_kwargs: dict[str, object] = {}

    def update(self, **kwargs: object) -> None:
        self.update_kwargs = dict(kwargs)


def _make_vport(current_type: str, family: object) -> SimpleNamespace:
    return SimpleNamespace(
        Name="vport-1",
        L1Config=SimpleNamespace(CurrentType=current_type, AresOneM=family),
    )


def _make_l1_config(enable_rs_fec: bool) -> SimpleNamespace:
    return SimpleNamespace(
        enable_fcoe=False,
        flow_control_config=None,
        enable_rs_fec=enable_rs_fec,
    )


class TestConfigureL1RsFec(unittest.TestCase):
    def test_applies_rs_fec_when_enabled(self) -> None:
        ixia = _ixia()
        family = _FakeL1Family()
        vport = _make_vport("aresOneMFcoe", family)
        ixia.configure_l1_settings(vport, _make_l1_config(True))  # type: ignore[arg-type]
        self.assertEqual(
            family.update_kwargs,
            {
                "IeeeL1Defaults": False,
                "EnableRsFec": True,
                "RsFecForceOn": True,
            },
        )

    def test_skips_rs_fec_when_disabled(self) -> None:
        ixia = _ixia()
        family = _FakeL1Family()
        vport = _make_vport("aresOneMFcoe", family)
        ixia.configure_l1_settings(vport, _make_l1_config(False))  # type: ignore[arg-type]
        self.assertEqual(family.update_kwargs, {})

    def test_skips_family_without_fec_knobs(self) -> None:
        ixia = _ixia()
        vport = _make_vport("aresOneMFcoe", SimpleNamespace())
        ixia.configure_l1_settings(vport, _make_l1_config(True))  # type: ignore[arg-type]


def _make_port_config(
    l1_config: object, port_name: str = "host:Ethernet1", port_number: int = 261
) -> t.Any:
    return SimpleNamespace(
        port_name=port_name,
        phy_port_config=SimpleNamespace(
            chassis_ip="10.0.0.1", slot_number=1, port_number=port_number
        ),
        l1_config=l1_config,
    )


def _vport_name(port_name: str) -> str:
    return "VPORT_" + port_name.upper()


def _assign_ixia(ixia: Ixia, vports: list[SimpleNamespace]) -> MagicMock:
    portmap = MagicMock()
    session = MagicMock()
    session.PortMapAssistant.return_value = portmap
    ixnetwork = MagicMock()
    ixnetwork.Vport.find.side_effect = lambda Name=None: (
        [vp for vp in vports if Name is None or vp.Name == Name]
    )
    ixia.session = session
    ixia.ixnetwork = ixnetwork
    ixia.vport_indices = {}
    ixia.force_take_port_ownership = True
    ixia.is_uhd_chassis = False
    return portmap


class TestAssignPortsRsFecOrdering(unittest.TestCase):
    def test_skips_link_gate_and_pushes_fec_when_requested(self) -> None:
        ixia = _ixia()
        vport = SimpleNamespace(Name="VPORT_HOST:ETHERNET1", ConnectionState="")
        portmap = _assign_ixia(ixia, [vport])
        l1 = _make_l1_config(True)
        with patch.object(ixia, "configure_l1_settings") as cfg:
            vport.ConnectionState = "connectedLinkUp"
            ixia.assign_ports([_make_port_config(l1)])
        _, kwargs = portmap.Connect.call_args
        self.assertTrue(kwargs.get("IgnoreLinkUp"))
        cfg.assert_called_once_with(vport, l1)

    def test_keeps_link_gate_without_fec_request(self) -> None:
        ixia = _ixia()
        vport = SimpleNamespace(Name="VPORT_HOST:ETHERNET1", ConnectionState="")
        portmap = _assign_ixia(ixia, [vport])
        with patch.object(ixia, "configure_l1_settings") as cfg:
            ixia.assign_ports([_make_port_config(_make_l1_config(False))])
        # Non-FEC batches must call Connect exactly as before (no new kwarg).
        portmap.Connect.assert_called_once_with(ForceOwnership=True)
        cfg.assert_not_called()

    def test_mixed_batch_verifies_non_fec_port_link(self) -> None:
        ixia = _ixia()
        fec_vport = SimpleNamespace(
            Name=_vport_name("host:Ethernet1"), ConnectionState="connectedLinkUp"
        )
        plain_vport = SimpleNamespace(
            Name=_vport_name("host:Ethernet2"), ConnectionState="down"
        )
        portmap = _assign_ixia(ixia, [fec_vport, plain_vport])
        with (
            patch.object(ixia, "configure_l1_settings") as cfg,
            patch(
                "neteng.test_infra.dne.taac.ixia.ixia.time.sleep",
            ),
            patch(
                "neteng.test_infra.dne.taac.ixia.ixia.time.time",
                side_effect=itertools.count(0, 1000),
            ),
            self.assertRaises(IxiaPortUnavailableError),
        ):
            ixia.assign_ports(
                [
                    _make_port_config(_make_l1_config(True), "host:Ethernet1"),
                    _make_port_config(
                        _make_l1_config(False), "host:Ethernet2", port_number=262
                    ),
                ]
            )
        # FEC push ran only for the FEC port, but the down non-FEC port
        # still fails the restored gate.
        cfg.assert_called_once_with(fec_vport, ANY)
        portmap.Connect.assert_called_once_with(ForceOwnership=True, IgnoreLinkUp=True)

    def test_mixed_batch_passes_when_all_links_up(self) -> None:
        ixia = _ixia()
        fec_vport = SimpleNamespace(
            Name=_vport_name("host:Ethernet1"), ConnectionState="connectedLinkUp"
        )
        plain_vport = SimpleNamespace(
            Name=_vport_name("host:Ethernet2"), ConnectionState="connectedLinkUp"
        )
        portmap = _assign_ixia(ixia, [fec_vport, plain_vport])
        with patch.object(ixia, "configure_l1_settings") as cfg:
            ixia.assign_ports(
                [
                    _make_port_config(_make_l1_config(True), "host:Ethernet1"),
                    _make_port_config(
                        _make_l1_config(False), "host:Ethernet2", port_number=262
                    ),
                ]
            )
        _, kwargs = portmap.Connect.call_args
        self.assertTrue(kwargs.get("IgnoreLinkUp"))
        cfg.assert_called_once_with(fec_vport, ANY)

    def test_raises_when_fec_link_never_comes_up(self) -> None:
        ixia = _ixia()
        vport = SimpleNamespace(Name="VPORT_HOST:ETHERNET1", ConnectionState="down")
        _assign_ixia(ixia, [vport])
        with (
            patch.object(ixia, "configure_l1_settings"),
            patch(
                "neteng.test_infra.dne.taac.ixia.ixia.time.sleep",
            ),
            patch(
                "neteng.test_infra.dne.taac.ixia.ixia.time.time",
                side_effect=itertools.count(0, 1000),
            ),
            self.assertRaises(IxiaPortUnavailableError),
        ):
            ixia.assign_ports([_make_port_config(_make_l1_config(True))])
