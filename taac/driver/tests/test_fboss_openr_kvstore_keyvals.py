# Copyright (c) Meta Platforms, Inc. and affiliates.
import logging
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import later.unittest
from taac.driver.fboss_switch import FbossSwitch
from openr.thrift.KvStore import thrift_types as kv_store_types


_MODULE = "neteng.test_infra.dne.taac.driver.fboss_switch"
_KEYS = ("adj:leaf-1", "prefix:leaf-1:[fc00::1/128]", "missing:key")
_AREA = "area-7"


def _publication() -> kv_store_types.Publication:
    return kv_store_types.Publication(
        keyVals={
            _KEYS[0]: kv_store_types.Value(
                version=7,
                originatorId="leaf-1",
                value=b"\x00\xffadjacency-payload",
                ttl=-2147483648,
                ttlVersion=3,
                hash=-8675309,
            ),
            _KEYS[1]: kv_store_types.Value(
                version=11,
                originatorId="leaf-1",
                value=b"\x80\x00prefix-payload",
                ttl=4567,
                ttlVersion=9,
                hash=424242,
            ),
        },
        expiredKeys=["expired:key"],
        nodeIds=["node-a", "node-b"],
        tobeUpdatedKeys=["peer:key"],
        area=_AREA,
        timestamp_ms=123456789,
    )


def _make_switch() -> FbossSwitch:
    switch = FbossSwitch.__new__(FbossSwitch)
    switch.hostname = "dut-test.example"
    switch.logger = logging.getLogger("test_fboss_openr_kvstore_keyvals")
    return switch


class FbossOpenrKvstoreKeyvalsTest(later.unittest.TestCase):
    async def test_returns_unmodified_publication_for_exact_keys_and_area(self) -> None:
        publication = _publication()
        client = AsyncMock()
        client.getKvStoreKeyValsArea = AsyncMock(return_value=publication)
        received_hosts = []

        @asynccontextmanager
        async def client_factory(hostname):
            received_hosts.append(hostname)
            yield client

        with patch(f"{_MODULE}.to_fb_fqdn", return_value="resolved-dut"):
            with patch(f"{_MODULE}.get_openr_ctrl_cpp_client", client_factory):
                result = await _make_switch().async_get_openr_kvstore_keyvals(
                    _KEYS, _AREA
                )

        self.assertEqual(publication, result)
        self.assertEqual(_AREA, result.area)
        self.assertEqual(b"\x00\xffadjacency-payload", result.keyVals[_KEYS[0]].value)
        self.assertEqual(["resolved-dut"], received_hosts)
        client.getKvStoreKeyValsArea.assert_awaited_once_with(list(_KEYS), _AREA)
