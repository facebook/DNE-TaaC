# Copyright (c) Meta Platforms, Inc. and affiliates.

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from taac.ixia.ixia import Ixia


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
