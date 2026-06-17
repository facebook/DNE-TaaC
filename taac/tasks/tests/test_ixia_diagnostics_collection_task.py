# pyre-strict
# Copyright (c) Meta Platforms, Inc. and affiliates.

from pathlib import Path
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

from taac.internal.tasks.ixia_diagnostics_collection_task import (
    DEFAULT_MANIFOLD_BUCKET,
    IxiaDiagnosticsCollectionTask,
    SHARED_DATA_URL_KEY,
)
from taac.ixia.diagnostics_client import DiagnosticsArchive


# Module-level constant — using a fresh Path() in a function default would be
# B008 (function call evaluated at definition time, shared across all calls).
_DEFAULT_ARCHIVE_PATH = Path("/tmp/x.tar.gz")


def _make_ixia_mock(chassis_ip="ixia11.example.com", username="admin", password="x"):
    ixia = MagicMock()
    ixia.primary_chassis_ip = chassis_ip
    ixia.username = username
    ixia.password = password
    return ixia


def _make_task(ixia=None, shared_data=None):
    return IxiaDiagnosticsCollectionTask(
        hostname="ixia11.example.com",
        description="test",
        ixia=ixia or _make_ixia_mock(),
        logger=MagicMock(),
        shared_data=shared_data,
    )


# Mock targets are at the IMPORT location (the task module), per the python_tests
# rule — not at the definition module.
_PATCH_CLIENT = (
    "neteng.test_infra.dne.taac.internal.tasks.ixia_diagnostics_collection_task."
    "IxiaDiagnosticsClient"
)
_PATCH_UPLOAD = (
    "neteng.test_infra.dne.taac.internal.tasks.ixia_diagnostics_collection_task."
    "async_upload_file_to_manifold"
)


def _make_archive(path=_DEFAULT_ARCHIVE_PATH, size=12345, async_id="999"):
    return DiagnosticsArchive(
        async_id=async_id,
        path=path,
        size_bytes=size,
        components=("IxNetwork Web Edition (System logs)",),
    )


class IxiaDiagnosticsCollectionTaskTest(IsolatedAsyncioTestCase):
    @patch(_PATCH_UPLOAD, new_callable=AsyncMock)
    @patch(_PATCH_CLIENT)
    async def test_happy_path_uploads_and_returns_none(
        self, mock_client_cls, mock_upload
    ):
        mock_client = MagicMock()
        mock_client.collect_and_download = AsyncMock(return_value=_make_archive())
        mock_client_cls.return_value = mock_client
        mock_upload.return_value = "https://manifold.../foo.tar.gz"
        task = _make_task()

        result = await task.run({"run_id": "BAG012_TEST"})

        self.assertIsNone(result)
        mock_client.collect_and_download.assert_awaited_once()
        mock_upload.assert_awaited_once()

    @patch(_PATCH_UPLOAD, new_callable=AsyncMock)
    @patch(_PATCH_CLIENT)
    async def test_url_stashed_in_shared_data(self, mock_client_cls, mock_upload):
        mock_client = MagicMock()
        mock_client.collect_and_download = AsyncMock(return_value=_make_archive())
        mock_client_cls.return_value = mock_client
        mock_upload.return_value = "https://manifold.../foo.tar.gz"
        # Use a plain dict — _SharedDataView wraps it.
        shared_data = {}
        task = _make_task(shared_data=shared_data)

        await task.run({"run_id": "BAG012_TEST"})

        # _SharedDataView prefixes keys with __<NAME>__:
        prefixed_key = f"__{IxiaDiagnosticsCollectionTask.NAME}__:{SHARED_DATA_URL_KEY}"
        self.assertEqual(shared_data[prefixed_key], "https://manifold.../foo.tar.gz")

    @patch(_PATCH_UPLOAD, new_callable=AsyncMock)
    @patch(_PATCH_CLIENT)
    async def test_url_stored_in_local_dict_when_no_shared_data(
        self, mock_client_cls, mock_upload
    ):
        """When the runner passes shared_data=None (older callers), the URL is
        still recorded on the task's local dict so the task body can read it."""
        mock_client = MagicMock()
        mock_client.collect_and_download = AsyncMock(return_value=_make_archive())
        mock_client_cls.return_value = mock_client
        mock_upload.return_value = "https://manifold.../foo.tar.gz"
        task = _make_task(shared_data=None)

        await task.run({"run_id": "X"})

        self.assertEqual(
            task._data[SHARED_DATA_URL_KEY], "https://manifold.../foo.tar.gz"
        )

    @patch(_PATCH_UPLOAD, new_callable=AsyncMock)
    @patch(_PATCH_CLIENT)
    async def test_manifold_key_format(self, mock_client_cls, mock_upload):
        mock_client = MagicMock()
        mock_client.collect_and_download = AsyncMock(return_value=_make_archive())
        mock_client_cls.return_value = mock_client
        mock_upload.return_value = "https://manifold.../foo.tar.gz"
        task = _make_task()

        await task.run({"run_id": "MY_RUN_ID"})

        bucket, key, path = mock_upload.call_args.args
        self.assertEqual(bucket, DEFAULT_MANIFOLD_BUCKET)
        # flat/ namespace (Manifold convention, see manifold_utils docstring)
        self.assertTrue(key.startswith("flat/"))
        # Bucket rejects `/` characters after the `flat/` prefix — confirmed
        # empirically against the live taac_ixia_diagnostics bucket which
        # returns HTTP 400 on nested slashes.
        self.assertEqual(
            key.count("/"),
            1,
            f"key must have exactly one `/` (the flat/ prefix), got: {key!r}",
        )
        # Chassis hostname and run_id in the key for discoverability
        self.assertIn("ixia11.example.com", key)
        self.assertIn("MY_RUN_ID", key)
        # tar.gz extension preserved
        self.assertTrue(key.endswith(".tar.gz"))

    @patch(_PATCH_UPLOAD, new_callable=AsyncMock)
    @patch(_PATCH_CLIENT)
    async def test_custom_components_forwarded(self, mock_client_cls, mock_upload):
        mock_client = MagicMock()
        mock_client.collect_and_download = AsyncMock(return_value=_make_archive())
        mock_client_cls.return_value = mock_client
        mock_upload.return_value = "https://..."
        task = _make_task()

        custom = ["Chassis (System logs)"]
        await task.run({"components": custom, "run_id": "X"})

        call_kwargs = mock_client.collect_and_download.call_args.kwargs
        self.assertEqual(call_kwargs["components"], custom)

    @patch(_PATCH_UPLOAD, new_callable=AsyncMock)
    @patch(_PATCH_CLIENT)
    async def test_custom_bucket_forwarded(self, mock_client_cls, mock_upload):
        mock_client = MagicMock()
        mock_client.collect_and_download = AsyncMock(return_value=_make_archive())
        mock_client_cls.return_value = mock_client
        mock_upload.return_value = "https://..."
        task = _make_task()

        await task.run({"manifold_bucket": "my_custom_bucket", "run_id": "X"})

        bucket, _, _ = mock_upload.call_args.args
        self.assertEqual(bucket, "my_custom_bucket")

    @patch(_PATCH_UPLOAD, new_callable=AsyncMock)
    @patch(_PATCH_CLIENT)
    async def test_swallows_collect_exception(self, mock_client_cls, mock_upload):
        """Best-effort guarantee: a chassis-side failure must NOT raise."""
        mock_client = MagicMock()
        mock_client.collect_and_download = AsyncMock(
            side_effect=RuntimeError("chassis 500")
        )
        mock_client_cls.return_value = mock_client
        task = _make_task()

        # Must NOT raise.
        result = await task.run({"run_id": "X"})

        self.assertIsNone(result)
        mock_upload.assert_not_awaited()

    @patch(_PATCH_UPLOAD, new_callable=AsyncMock)
    @patch(_PATCH_CLIENT)
    async def test_swallows_upload_exception(self, mock_client_cls, mock_upload):
        """Best-effort guarantee: a Manifold ACL miss must NOT raise."""
        mock_client = MagicMock()
        mock_client.collect_and_download = AsyncMock(return_value=_make_archive())
        mock_client_cls.return_value = mock_client
        mock_upload.side_effect = PermissionError("403 forbidden")
        task = _make_task()

        # Must NOT raise.
        result = await task.run({"run_id": "X"})

        self.assertIsNone(result)
