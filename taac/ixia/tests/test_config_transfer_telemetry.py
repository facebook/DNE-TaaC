# Copyright (c) Meta Platforms, Inc. and affiliates.

import logging
import typing as t
import unittest
from unittest.mock import MagicMock, patch

from ixia.ixia import types as ixia_types
from neteng.test_infra.dne.taac.ixia import taac_ixia as taac_ixia_module
from taac.ixia.ixia import IxiaSetupError
from taac.ixia.taac_ixia import TaacIxia


def _make_ixia() -> tuple[TaacIxia, MagicMock, MagicMock]:
    ixia = object.__new__(TaacIxia)
    resource_manager = MagicMock()
    session = MagicMock()
    session.Ixnetwork.ResourceManager = resource_manager
    ixia.session = t.cast(t.Any, session)
    logger = MagicMock(spec=logging.Logger)
    ixia.logger = t.cast(t.Any, logger)
    return ixia, resource_manager, logger


class ConfigTransferTelemetryTest(unittest.TestCase):
    def test_cached_config_rehydrates_local_index_before_protocol_start(self) -> None:
        ixia, _resource_manager, logger = _make_ixia()
        ixnetwork = MagicMock()
        t.cast(t.Any, ixia.session).Ixnetwork = ixnetwork
        port_configs = [ixia_types.PortConfig(port_name="test-port")]
        ixia.ixia_config = ixia_types.IxiaConfig(port_configs=port_configs)
        ixia.rehydrate_vport_indices = MagicMock()
        ixia.start_and_verify_protocols = MagicMock()

        loaded = ixia.load_config_from_chassis("/tmp/cached.ixncfg")

        self.assertTrue(loaded)
        ixnetwork.AssignPorts.assert_called_once_with(True)
        ixia.rehydrate_vport_indices.assert_called_once_with(port_configs)
        ixia.start_and_verify_protocols.assert_called_once_with()

    def test_rehydration_failure_turns_cache_hit_into_cold_setup_miss(self) -> None:
        ixia, _resource_manager, logger = _make_ixia()
        ixnetwork = MagicMock()
        t.cast(t.Any, ixia.session).Ixnetwork = ixnetwork
        ixia.ixia_config = ixia_types.IxiaConfig(
            port_configs=[ixia_types.PortConfig(port_name="test-port")]
        )
        ixia.rehydrate_vport_indices = MagicMock(
            side_effect=IxiaSetupError("missing topology metadata")
        )
        ixia.start_and_verify_protocols = MagicMock()

        loaded = ixia.load_config_from_chassis("/tmp/cached.ixncfg")

        self.assertFalse(loaded)
        ixia.start_and_verify_protocols.assert_not_called()
        logger.warning.assert_called_once_with(
            "Cached IXIA topology is incompatible with the requested "
            "declarative config: missing topology metadata. Rejecting the "
            "cache hit so the caller can rebuild from scratch."
        )

    def test_native_config_operations_share_server_filename(self) -> None:
        ixia, _resource_manager, _logger = _make_ixia()
        ixia.ixia_config = ixia_types.IxiaConfig(port_configs=[])
        ixia.rehydrate_vport_indices = MagicMock()
        ixia.start_and_verify_protocols = MagicMock()
        session = t.cast(t.Any, ixia.session)
        config_path = "/root/.local/share/Ixia/sdmStreamManager/common/baseline.ixncfg"

        self.assertTrue(ixia.save_config_to_chassis(config_path))
        self.assertTrue(ixia.load_config_from_chassis(config_path))
        self.assertTrue(ixia.remove_config_from_chassis(config_path))

        saved_file = session.Ixnetwork.SaveConfig.call_args.args[0]
        loaded_file = session.Ixnetwork.LoadConfig.call_args.args[0]
        self.assertEqual("baseline.ixncfg", saved_file.file_name)
        self.assertEqual("baseline.ixncfg", loaded_file.file_name)
        session.Ixnetwork.AssignPorts.assert_called_once_with(True)
        ixia.start_and_verify_protocols.assert_called_once_with()
        session.Session.RemoveFile.assert_called_once_with(
            remote_filename="baseline.ixncfg"
        )

    def test_native_config_cleanup_retries_a_transient_failure(self) -> None:
        ixia, _resource_manager, _logger = _make_ixia()
        session = t.cast(t.Any, ixia.session)
        session.Session.RemoveFile.side_effect = [RuntimeError("busy"), None]

        with patch.object(taac_ixia_module.time, "sleep") as sleep:
            removed = ixia.remove_config_from_chassis("/remote/baseline.ixncfg")

        self.assertTrue(removed)
        self.assertEqual(2, session.Session.RemoveFile.call_count)
        sleep.assert_called_once_with(1.0)

    def test_native_config_cleanup_exhausts_retries(self) -> None:
        ixia, _resource_manager, _logger = _make_ixia()
        session = t.cast(t.Any, ixia.session)
        session.Session.RemoveFile.side_effect = RuntimeError("busy")

        with patch.object(taac_ixia_module.time, "sleep") as sleep:
            removed = ixia.remove_config_from_chassis("/remote/baseline.ixncfg")

        self.assertFalse(removed)
        self.assertEqual(3, session.Session.RemoveFile.call_count)
        self.assertEqual(2, sleep.call_count)

    def test_native_config_load_failure_does_not_assume_recovery(self) -> None:
        ixia, _resource_manager, logger = _make_ixia()
        session = t.cast(t.Any, ixia.session)
        session.Ixnetwork.LoadConfig.side_effect = RuntimeError("load failed")

        loaded = ixia.load_config_from_chassis("/remote/baseline.ixncfg")

        self.assertFalse(loaded)
        logger.info.assert_called_with(
            "Could not load IXIA config from /remote/baseline.ixncfg: load failed"
        )

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
