# pyre-strict
# Copyright (c) Meta Platforms, Inc. and affiliates.

from pathlib import Path
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from taac.ixia.diagnostics_client import (
    _flatten_components,
    _url_safe_host,
    IxiaDiagnosticsClient,
    IxiaDiagnosticsCollectionError,
)


class UrlSafeHostTest(IsolatedAsyncioTestCase):
    """RFC 3986: IPv6 literals must be bracket-wrapped in URLs.

    Regression coverage for the conveyor-discovered bug where bare IPv6
    chassis hosts (e.g. `2401:db00:2066:303b::3001`) caused aiohttp to raise
    `InvalidUrlClientError` on `https://{host}/...`.
    """

    def test_ipv6_literal_gets_bracketed(self):
        self.assertEqual(
            _url_safe_host("2401:db00:2066:303b::3001"),
            "[2401:db00:2066:303b::3001]",
        )

    def test_ipv6_compressed_form_gets_bracketed(self):
        self.assertEqual(_url_safe_host("::1"), "[::1]")

    def test_already_bracketed_passes_through(self):
        self.assertEqual(
            _url_safe_host("[2401:db00:2066:303b::3001]"),
            "[2401:db00:2066:303b::3001]",
        )

    def test_ipv4_passes_through_unchanged(self):
        self.assertEqual(_url_safe_host("10.0.0.1"), "10.0.0.1")

    def test_dns_name_passes_through_unchanged(self):
        self.assertEqual(
            _url_safe_host("ixia11.netcastle.ash6.example.com"),
            "ixia11.netcastle.ash6.example.com",
        )

    def test_client_constructor_normalizes_ipv6_chassis(self):
        """IxiaDiagnosticsClient stores the bracketed form on the instance."""
        client = IxiaDiagnosticsClient(
            chassis_hostname="2401:db00:2066:303b::3001",
            username="u",
            password="p",
        )
        self.assertEqual(client._chassis, "[2401:db00:2066:303b::3001]")

    def test_client_constructor_leaves_dns_unchanged(self):
        client = IxiaDiagnosticsClient(
            chassis_hostname="ixia.example.com",
            username="u",
            password="p",
        )
        self.assertEqual(client._chassis, "ixia.example.com")


class FlattenComponentsTest(IsolatedAsyncioTestCase):
    def test_empty_list_returns_empty(self):
        self.assertEqual(_flatten_components([]), [])

    def test_flat_list_returns_all_names(self):
        nodes = [
            {"componentName": "A", "subComponents": []},
            {"componentName": "B", "subComponents": []},
        ]
        self.assertEqual(_flatten_components(nodes), ["A", "B"])

    def test_one_level_nesting_includes_parent_and_children(self):
        nodes = [
            {
                "componentName": "Parent",
                "subComponents": [
                    {"componentName": "Child1", "subComponents": []},
                    {"componentName": "Child2", "subComponents": []},
                ],
            }
        ]
        # Parent listed BEFORE children — matches the live chassis response shape.
        self.assertEqual(_flatten_components(nodes), ["Parent", "Child1", "Child2"])

    def test_two_level_nesting(self):
        nodes = [
            {
                "componentName": "Root",
                "subComponents": [
                    {
                        "componentName": "Mid",
                        "subComponents": [
                            {"componentName": "Leaf", "subComponents": []},
                        ],
                    }
                ],
            }
        ]
        self.assertEqual(_flatten_components(nodes), ["Root", "Mid", "Leaf"])

    def test_missing_component_name_is_skipped(self):
        nodes = [
            {"subComponents": []},  # no componentName
            {"componentName": "Valid", "subComponents": []},
        ]
        self.assertEqual(_flatten_components(nodes), ["Valid"])

    def test_missing_subcomponents_treated_as_empty(self):
        nodes = [{"componentName": "Only"}]  # no subComponents key
        self.assertEqual(_flatten_components(nodes), ["Only"])


class ListComponentsTest(IsolatedAsyncioTestCase):
    @patch(
        "neteng.test_infra.dne.taac.ixia.diagnostics_client.async_make_ixia_api_call",
        new_callable=AsyncMock,
    )
    async def test_bare_list_response(self, mock_call):
        mock_call.return_value = [
            {"componentName": "A", "subComponents": []},
            {"componentName": "B", "subComponents": []},
        ]
        client = IxiaDiagnosticsClient("host", "u", "p")
        self.assertEqual(await client.list_components(), ["A", "B"])

    @patch(
        "neteng.test_infra.dne.taac.ixia.diagnostics_client.async_make_ixia_api_call",
        new_callable=AsyncMock,
    )
    async def test_dict_with_components_key_response(self, mock_call):
        mock_call.return_value = {
            "components": [
                {"componentName": "X", "subComponents": []},
            ]
        }
        client = IxiaDiagnosticsClient("host", "u", "p")
        self.assertEqual(await client.list_components(), ["X"])

    @patch(
        "neteng.test_infra.dne.taac.ixia.diagnostics_client.async_make_ixia_api_call",
        new_callable=AsyncMock,
    )
    async def test_unexpected_shape_raises(self, mock_call):
        mock_call.return_value = "garbage"
        client = IxiaDiagnosticsClient("host", "u", "p")
        with self.assertRaises(RuntimeError):
            await client.list_components()


class StartCollectionTest(IsolatedAsyncioTestCase):
    @patch(
        "neteng.test_infra.dne.taac.ixia.diagnostics_client.async_make_ixia_api_call",
        new_callable=AsyncMock,
    )
    async def test_returns_id_from_id_field(self, mock_call):
        mock_call.return_value = {"id": "943"}
        client = IxiaDiagnosticsClient("host", "u", "p")
        self.assertEqual(await client.start_collection(["IxNetwork"]), "943")

    @patch(
        "neteng.test_infra.dne.taac.ixia.diagnostics_client.async_make_ixia_api_call",
        new_callable=AsyncMock,
    )
    async def test_accepts_asyncId_field_name(self, mock_call):
        mock_call.return_value = {"asyncId": "abc-123"}
        client = IxiaDiagnosticsClient("host", "u", "p")
        self.assertEqual(await client.start_collection(["IxNetwork"]), "abc-123")

    @patch(
        "neteng.test_infra.dne.taac.ixia.diagnostics_client.async_make_ixia_api_call",
        new_callable=AsyncMock,
    )
    async def test_raises_when_no_id_returned(self, mock_call):
        mock_call.return_value = {"unrelated": "data"}
        client = IxiaDiagnosticsClient("host", "u", "p")
        with self.assertRaises(RuntimeError):
            await client.start_collection(["IxNetwork"])


class WaitForCompletionTest(IsolatedAsyncioTestCase):
    @patch(
        "neteng.test_infra.dne.taac.ixia.diagnostics_client.async_make_ixia_api_call",
        new_callable=AsyncMock,
    )
    async def test_returns_on_success_after_in_progress(self, mock_call):
        mock_call.side_effect = [
            {"state": "IN_PROGRESS", "progress": 0},
            {"state": "IN_PROGRESS", "progress": 50},
            {"state": "SUCCESS", "progress": 100},
        ]
        client = IxiaDiagnosticsClient("host", "u", "p")
        await client.wait_for_completion("943", timeout_s=30, poll_interval_s=0)
        self.assertEqual(mock_call.call_count, 3)

    @patch(
        "neteng.test_infra.dne.taac.ixia.diagnostics_client.async_make_ixia_api_call",
        new_callable=AsyncMock,
    )
    async def test_accepts_lowercase_success(self, mock_call):
        mock_call.return_value = {"state": "success", "progress": 100}
        client = IxiaDiagnosticsClient("host", "u", "p")
        await client.wait_for_completion("943", timeout_s=30, poll_interval_s=0)

    @patch(
        "neteng.test_infra.dne.taac.ixia.diagnostics_client.async_make_ixia_api_call",
        new_callable=AsyncMock,
    )
    async def test_raises_on_terminal_failure(self, mock_call):
        mock_call.return_value = {"state": "FAILED", "progress": 30}
        client = IxiaDiagnosticsClient("host", "u", "p")
        with self.assertRaises(IxiaDiagnosticsCollectionError):
            await client.wait_for_completion("943", timeout_s=30, poll_interval_s=0)

    @patch(
        "neteng.test_infra.dne.taac.ixia.diagnostics_client.async_make_ixia_api_call",
        new_callable=AsyncMock,
    )
    async def test_raises_timeout_when_never_terminates(self, mock_call):
        mock_call.return_value = {"state": "IN_PROGRESS", "progress": 50}
        client = IxiaDiagnosticsClient("host", "u", "p")
        with self.assertRaises(TimeoutError):
            await client.wait_for_completion("943", timeout_s=0, poll_interval_s=0)


class CollectAndDownloadTest(IsolatedAsyncioTestCase):
    """Verifies the try/finally cleanup contract — DELETE MUST always run."""

    @patch.object(IxiaDiagnosticsClient, "delete_archive", new_callable=AsyncMock)
    @patch.object(
        IxiaDiagnosticsClient, "download_archive_to_file", new_callable=AsyncMock
    )
    @patch.object(IxiaDiagnosticsClient, "wait_for_completion", new_callable=AsyncMock)
    @patch.object(IxiaDiagnosticsClient, "start_collection", new_callable=AsyncMock)
    async def test_happy_path_calls_all_four_in_order(
        self, mock_start, mock_wait, mock_download, mock_delete
    ):
        mock_start.return_value = "999"
        mock_download.return_value = 12345
        client = IxiaDiagnosticsClient("host", "u", "p")

        result = await client.collect_and_download(
            dest_path=Path("/tmp/x.tar.gz"), components=["IxNetwork"]
        )
        mock_start.assert_awaited_once()
        mock_wait.assert_awaited_once()
        mock_download.assert_awaited_once()
        mock_delete.assert_awaited_once_with("999")
        self.assertEqual(result.async_id, "999")
        self.assertEqual(result.size_bytes, 12345)
        self.assertEqual(result.path, Path("/tmp/x.tar.gz"))

    @patch.object(IxiaDiagnosticsClient, "delete_archive", new_callable=AsyncMock)
    @patch.object(
        IxiaDiagnosticsClient, "download_archive_to_file", new_callable=AsyncMock
    )
    @patch.object(IxiaDiagnosticsClient, "wait_for_completion", new_callable=AsyncMock)
    @patch.object(IxiaDiagnosticsClient, "start_collection", new_callable=AsyncMock)
    async def test_delete_runs_even_when_download_raises(
        self, mock_start, mock_wait, mock_download, mock_delete
    ):
        mock_start.return_value = "999"
        mock_download.side_effect = RuntimeError("network blip")
        client = IxiaDiagnosticsClient("host", "u", "p")

        with self.assertRaises(RuntimeError):
            await client.collect_and_download(
                dest_path=Path("/tmp/x.tar.gz"), components=["IxNetwork"]
            )
        # Even though download blew up, DELETE must have run — chassis cleanup.
        mock_delete.assert_awaited_once_with("999")

    @patch.object(IxiaDiagnosticsClient, "delete_archive", new_callable=AsyncMock)
    @patch.object(
        IxiaDiagnosticsClient, "download_archive_to_file", new_callable=AsyncMock
    )
    @patch.object(IxiaDiagnosticsClient, "wait_for_completion", new_callable=AsyncMock)
    @patch.object(IxiaDiagnosticsClient, "start_collection", new_callable=AsyncMock)
    async def test_delete_runs_even_when_polling_raises(
        self, mock_start, mock_wait, mock_download, mock_delete
    ):
        mock_start.return_value = "999"
        mock_wait.side_effect = IxiaDiagnosticsCollectionError("server error")
        client = IxiaDiagnosticsClient("host", "u", "p")

        with self.assertRaises(IxiaDiagnosticsCollectionError):
            await client.collect_and_download(
                dest_path=Path("/tmp/x.tar.gz"), components=["IxNetwork"]
            )
        mock_delete.assert_awaited_once_with("999")
        mock_download.assert_not_awaited()

    @patch.object(IxiaDiagnosticsClient, "delete_archive", new_callable=AsyncMock)
    @patch.object(
        IxiaDiagnosticsClient, "download_archive_to_file", new_callable=AsyncMock
    )
    @patch.object(IxiaDiagnosticsClient, "wait_for_completion", new_callable=AsyncMock)
    @patch.object(IxiaDiagnosticsClient, "start_collection", new_callable=AsyncMock)
    async def test_default_components_used_when_none(
        self, mock_start, mock_wait, mock_download, mock_delete
    ):
        mock_start.return_value = "999"
        mock_download.return_value = 1
        client = IxiaDiagnosticsClient("host", "u", "p")

        result = await client.collect_and_download(
            dest_path=Path("/tmp/x.tar.gz"), components=None
        )
        # The default tuple is materialized into a list and forwarded.
        called_components = mock_start.call_args.args[0]
        self.assertIn("IxNetwork Web Edition (System logs)", called_components)
        self.assertIn("Port logs", called_components)
        self.assertEqual(result.components, tuple(called_components))
