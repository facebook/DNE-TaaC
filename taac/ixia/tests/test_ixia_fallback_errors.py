# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-ignore-all-errors
#
# Broad suppression justified: the `Ixia` class attributes exposed via mocks
# (`session`, `ixnetwork`, etc.) are typed as concrete `SessionAssistant` /
# `Ixnetwork` classes from `ixnetwork_restpy`. Constructing a real instance
# in a unit test is prohibitive, so the tests inject `SimpleNamespace` / `MagicMock`
# stubs that are structurally compatible but nominally incompatible. Targeted
# `
# safety. Aligns with `test_ixia_fallback.py` for the same reason.

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from ixia.ixia import types as ixia_types
from taac.ixia.ixia import Ixia
from taac.utils.oss_taac_constants import (
    IxiaPortUnavailableError,
    IxiaSessionUnavailableError,
)


class IxiaFallbackErrorTest(unittest.TestCase):
    def _make_ixia(self) -> Ixia:
        with patch.object(Ixia, "__init__", lambda self: None):
            ixia = Ixia()
        ixia.logger = MagicMock()
        ixia.is_uhd_chassis = False
        ixia.force_take_port_ownership = True
        ixia.vport_indices = {}
        return ixia

    def test_port_connect_failure_preserves_typed_cause(self) -> None:
        ixia = self._make_ixia()
        port_map = MagicMock()
        original_error = RuntimeError("port is already owned")
        port_map.Connect.side_effect = original_error
        ixia.session = SimpleNamespace(
            PortMapAssistant=MagicMock(return_value=port_map)
        )
        ixia.ixnetwork = SimpleNamespace(Vport=MagicMock())
        port_config = ixia_types.PortConfig(
            port_name="dut1:eth1/1/1",
            phy_port_config=ixia_types.PhyPortConfig(
                chassis_ip="192.0.2.10",
                slot_number=1,
                port_number=1,
            ),
        )

        with self.assertRaises(IxiaPortUnavailableError) as context:
            ixia.assign_ports([port_config])

        self.assertIs(context.exception.__cause__, original_error)
        port_map.Connect.assert_called_once_with(ForceOwnership=True)

    def test_typed_setup_failure_and_orchestrator_cleanup_delete_once(self) -> None:
        ixia = self._make_ixia()
        remove = MagicMock()
        ixia.session = SimpleNamespace(Session=SimpleNamespace(remove=remove))
        ixia.session_id = 42
        ixia.session_name = "fallback-test"
        ixia.teardown_session = True
        ixia._teardown_complete = False
        ixia.cleanup_failed_setup = True
        ixia.is_existing_session = False
        ixia._create_basic_setup = MagicMock(
            side_effect=IxiaPortUnavailableError("port unavailable")
        )

        with self.assertRaises(IxiaPortUnavailableError):
            ixia.create_basic_setup()

        # This is the second cleanup call made by candidate orchestration.
        ixia.tear_down()

        remove.assert_called_once_with()

    @patch("neteng.test_infra.dne.taac.ixia.ixia.IxnSessionAssistant")
    def test_unrecovered_session_5xx_remains_fallback_eligible(
        self, session_assistant
    ) -> None:
        ixia = self._make_ixia()
        original_error = RuntimeError("HTTP 503 Service Unavailable")
        session_assistant.side_effect = original_error
        ixia.primary_chassis_ip = "192.0.2.10"
        ixia.session_id = None
        ixia.session_name = "fallback-test"
        ixia.cleanup_config = True
        ixia.is_existing_session = False
        ixia.username = "admin"
        ixia.password = "password"
        ixia.ApiKey = None
        ixia._ixia_recovery_attempts_remaining = 1
        ixia._should_attempt_recovery = MagicMock(return_value=True)
        ixia._attempt_inband_recovery = MagicMock(return_value=False)

        with self.assertRaises(IxiaSessionUnavailableError) as context:
            ixia.connect()

        self.assertIs(context.exception.__cause__, original_error)
