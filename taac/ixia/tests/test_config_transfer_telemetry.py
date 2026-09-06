# Copyright (c) Meta Platforms, Inc. and affiliates.

import logging
import types
import typing as t
import unittest
from unittest.mock import MagicMock, patch

from neteng.test_infra.dne.taac.ixia import taac_ixia as taac_ixia_module
from taac.ixia.taac_ixia import TaacIxia


def _make_ixia() -> tuple[TaacIxia, MagicMock, MagicMock]:
    ixia = object.__new__(TaacIxia)
    resource_manager = MagicMock()
    ixia.session = t.cast(
        t.Any,
        types.SimpleNamespace(
            Ixnetwork=types.SimpleNamespace(ResourceManager=resource_manager)
        ),
    )
    logger = MagicMock(spec=logging.Logger)
    ixia.logger = t.cast(t.Any, logger)
    return ixia, resource_manager, logger


class ConfigTransferTelemetryTest(unittest.TestCase):
    def test_export_logs_duration(self) -> None:
        ixia, resource_manager, logger = _make_ixia()
        resource_manager.ExportConfig.return_value = '{"name":"baseline"}'
        clock = MagicMock()
        clock.monotonic.side_effect = [10.0, 145.2]

        with patch.object(taac_ixia_module, "time", clock):
            exported = ixia.export_json_config(baseline_invocation_id="invocation-1")

        self.assertEqual('{"name":"baseline"}', exported)
        logger.info.assert_any_call(
            "[IXIA CONFIG] Export started (invocation_id=invocation-1)"
        )
        logger.info.assert_any_call(
            "[IXIA CONFIG] Export completed in 135.2s (invocation_id=invocation-1)"
        )

    def test_export_logs_failure_duration_and_reraises(self) -> None:
        ixia, resource_manager, logger = _make_ixia()
        export_error = RuntimeError("export failed")
        resource_manager.ExportConfig.side_effect = export_error
        clock = MagicMock()
        clock.monotonic.side_effect = [10.0, 12.5]

        with (
            patch.object(taac_ixia_module, "time", clock),
            self.assertRaises(RuntimeError) as raised,
        ):
            ixia.export_json_config(baseline_invocation_id="invocation-1")

        self.assertIs(export_error, raised.exception)
        logger.exception.assert_called_once_with(
            "[IXIA CONFIG] Export failed after 2.5s (invocation_id=invocation-1)"
        )

    def test_import_logs_duration(self) -> None:
        ixia, resource_manager, logger = _make_ixia()
        ixia.start_and_verify_protocols = MagicMock()
        ixia.enable_traffic = MagicMock()
        ixia.start_traffic = MagicMock()
        ixia.stop_traffic = MagicMock()
        clock = MagicMock()
        clock.monotonic.side_effect = [20.0, 172.7, 180.0, 190.0]

        with patch.object(taac_ixia_module, "time", clock):
            ixia.import_json_config(
                '{"name":"baseline"}', baseline_invocation_id="invocation-1"
            )

        resource_manager.ImportConfig.assert_called_once_with(
            '{"name":"baseline"}', False
        )
        logger.info.assert_any_call(
            "[IXIA CONFIG] Import started (invocation_id=invocation-1)"
        )
        logger.info.assert_any_call(
            "[IXIA CONFIG] Import completed in 152.7s (invocation_id=invocation-1)"
        )
        logger.info.assert_any_call(
            "[IXIA CONFIG] Post-import activation completed in 10.0s "
            "(invocation_id=invocation-1)"
        )

    def test_import_logs_failure_duration_and_reraises(self) -> None:
        ixia, resource_manager, logger = _make_ixia()
        import_error = RuntimeError("import failed")
        resource_manager.ImportConfig.side_effect = import_error
        clock = MagicMock()
        clock.monotonic.side_effect = [20.0, 23.5]

        with (
            patch.object(taac_ixia_module, "time", clock),
            self.assertRaises(RuntimeError) as raised,
        ):
            ixia.import_json_config(
                '{"name":"baseline"}', baseline_invocation_id="invocation-1"
            )

        self.assertIs(import_error, raised.exception)
        logger.exception.assert_called_once_with(
            "[IXIA CONFIG] Import failed after 3.5s (invocation_id=invocation-1)"
        )

    def test_post_import_failure_is_not_labeled_as_import_failure(self) -> None:
        ixia, _resource_manager, logger = _make_ixia()
        activation_error = RuntimeError("protocol startup failed")
        ixia.start_and_verify_protocols = MagicMock(side_effect=activation_error)
        ixia.enable_traffic = MagicMock()
        ixia.start_traffic = MagicMock()
        ixia.stop_traffic = MagicMock()
        clock = MagicMock()
        clock.monotonic.side_effect = [20.0, 25.0, 25.0, 29.0]

        with (
            patch.object(taac_ixia_module, "time", clock),
            self.assertRaises(RuntimeError) as raised,
        ):
            ixia.import_json_config(
                '{"name":"baseline"}', baseline_invocation_id="invocation-1"
            )

        self.assertIs(activation_error, raised.exception)
        logger.info.assert_any_call(
            "[IXIA CONFIG] Import completed in 5.0s (invocation_id=invocation-1)"
        )
        logger.exception.assert_called_once_with(
            "[IXIA CONFIG] Post-import activation failed after 4.0s "
            "(invocation_id=invocation-1)"
        )
