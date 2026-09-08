# Copyright (c) Meta Platforms, Inc. and affiliates.

import typing as t
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from ixia.ixia import types as ixia_types
from neteng.test_infra.dne.taac.ixia.ixia import Ixia, IxnIxNetworkError


class _ScriptedMultivalue:
    """Small behavioral fake for the external IxNetwork Multivalue API."""

    def __init__(
        self,
        value: object | None = "65535",
        *,
        pattern_type: str = "Single",
        update_on_write: bool = True,
        write_error: Exception | None = None,
        pre_write_reads: tuple[object | Exception, ...] = (),
        post_write_reads: tuple[object | Exception, ...] = (),
    ) -> None:
        self.value = value
        self.PatternType = pattern_type
        self.update_on_write = update_on_write
        self.write_error = write_error
        self._reads = list(pre_write_reads)
        self._post_write_reads = post_write_reads
        self.single_calls: list[object] = []
        self.pattern_read_count = 0

    @property
    def Values(self) -> list[object]:
        raise AssertionError("slow-peer programming must not expand Values")

    @property
    def Pattern(self) -> object | None:
        self.pattern_read_count += 1
        if self._reads:
            result = self._reads.pop(0)
            if isinstance(result, Exception):
                raise result
            return result
        return self.value

    def Single(self, *, value: object) -> None:
        self.single_calls.append(value)
        if self.write_error is not None:
            raise self.write_error
        if self.update_on_write:
            self.value = str(value)
        self.PatternType = "Single"
        self._reads = list(self._post_write_reads)


class _Setting:
    def Single(self, *args: object, **kwargs: object) -> None:
        pass

    def Increment(self, *args: object, **kwargs: object) -> None:
        pass


class _Peer:
    def __init__(
        self,
        multivalue: _ScriptedMultivalue,
        *,
        name: str = "BGP_SLOW",
        name_error: Exception | None = None,
        property_error: Exception | None = None,
    ) -> None:
        self._name = name
        self._name_error = name_error
        self._multivalue = multivalue
        self._property_error = property_error

    @property
    def Name(self) -> str:
        if self._name_error is not None:
            raise self._name_error
        return self._name

    @property
    def TcpWindowSizeInBytes(self) -> _ScriptedMultivalue:
        if self._property_error is not None:
            raise self._property_error
        return self._multivalue

    def __getattr__(self, name: str) -> _Setting:
        if name == "TcpWindowSizeInBytes" and self._property_error is not None:
            raise self._property_error
        setting = _Setting()
        setattr(self, name, setting)
        return setting


class _DynamicPropertyPeer:
    Name = "BGP_SLOW"

    def __init__(self, multivalue: _ScriptedMultivalue) -> None:
        self._multivalue = multivalue

    def __getattr__(self, name: str) -> object:
        if name == "TcpWindowSizeInBytes":
            return self._multivalue
        raise AttributeError(name)


class _FindCollection:
    def __init__(self, items: object) -> None:
        self.items = items

    def find(self, **kwargs: object) -> object:
        return self.items


class _PeerCollection(_FindCollection):
    def __init__(self, existing: object, added: object | None = None) -> None:
        super().__init__(existing)
        self.added = added

    def add(self, **kwargs: object) -> object:
        if self.added is None:
            raise AssertionError("test did not provide a peer to add")
        return self.added


def _ixia() -> Ixia:
    with patch.object(Ixia, "__init__", lambda self: None):
        ixia = Ixia()
    ixia.logger = MagicMock()
    ixia._tracer = None
    ixia.teardown_session = True
    return ixia


class BgpPeerTcpWindowTest(unittest.TestCase):
    """Verify the IXIA adapter contract without a network dependency.

    Physical IXIA setup runs cover the transport and chassis behavior. These
    tests isolate declarative and imperative adapter decisions and failures.
    """

    def _create_peer(
        self,
        *,
        ixia: Ixia,
        peer: object,
        window: int | None,
        existing: bool = True,
    ) -> object:
        collection = _PeerCollection(
            existing=peer if existing else None,
            added=None if existing else peer,
        )
        ip_address = SimpleNamespace(BgpIpv4Peer=collection)
        return ixia.create_bgp_peer(
            port_identifier="dut:Ethernet1",
            ip_address_family=ixia_types.IpAddressFamily.IPV4,
            bgp_peer_config=ixia_types.BgpPeerConfig(
                bgp_peer_name="BGP_SLOW" if window is not None else "BGP_NORMAL",
                tcp_window_size_bytes=window,
            ),
            ip_addr_obj=t.cast(t.Any, ip_address),
        )

    def _configure_imperative_peers(
        self,
        *,
        ixia: Ixia,
        peers: list[object],
        tcp_window_size_bytes: int = 1500,
    ) -> int:
        ipv4 = SimpleNamespace(BgpIpv4Peer=_FindCollection(peers))
        ipv6 = SimpleNamespace(BgpIpv6Peer=_FindCollection([]))
        ethernet = SimpleNamespace(
            Ipv4=_FindCollection([ipv4]),
            Ipv6=_FindCollection([ipv6]),
        )
        device_group = SimpleNamespace(
            Name="DEVICE_GROUP_IPV4_EBGP_SLOW",
            Ethernet=_FindCollection([ethernet]),
        )
        with patch.object(ixia, "find_device_groups", return_value=[device_group]):
            return ixia.configure_bgp_peer_tcp_window_size(
                hostname="dut.example.com",
                interface="Ethernet1",
                device_group_regex="^DEVICE_GROUP_IPV4_EBGP_SLOW$",
                tcp_window_size_bytes=tcp_window_size_bytes,
            )

    def test_standard_peer_preserves_ixia_state(self) -> None:
        for existing in (False, True):
            with self.subTest(existing=existing):
                ixia = _ixia()
                multivalue = _ScriptedMultivalue()
                peer = _Peer(multivalue, name="BGP_NORMAL")

                result = self._create_peer(
                    ixia=ixia,
                    peer=peer,
                    window=None,
                    existing=existing,
                )

                self.assertIs(peer, result)
                self.assertEqual([], multivalue.single_calls)
                self.assertEqual(0, multivalue.pattern_read_count)

    def test_declared_window_applies_to_existing_and_new_peers(self) -> None:
        for existing in (False, True):
            with self.subTest(existing=existing):
                ixia = _ixia()
                multivalue = _ScriptedMultivalue()
                peer = _Peer(multivalue)

                result = self._create_peer(
                    ixia=ixia,
                    peer=peer,
                    window=1500,
                    existing=existing,
                )

                self.assertIs(peer, result)
                self.assertEqual([1500], multivalue.single_calls)
                self.assertEqual("1500", multivalue.value)
                self.assertEqual("Single", multivalue.PatternType)

    def test_matching_single_window_skips_write(self) -> None:
        ixia = _ixia()
        multivalue = _ScriptedMultivalue("1500")
        peer = _Peer(multivalue)

        result = self._create_peer(ixia=ixia, peer=peer, window=1500)

        self.assertIs(peer, result)
        self.assertEqual([], multivalue.single_calls)
        self.assertEqual(1, multivalue.pattern_read_count)

    def test_non_single_pattern_is_normalized_without_expanding_values(self) -> None:
        ixia = _ixia()
        multivalue = _ScriptedMultivalue("1500", pattern_type="ValueList")
        peer = _Peer(multivalue)

        result = self._create_peer(ixia=ixia, peer=peer, window=1500)

        self.assertIs(peer, result)
        self.assertEqual([1500], multivalue.single_calls)
        self.assertEqual("Single", multivalue.PatternType)

    def test_window_readback_mismatch_fails_setup(self) -> None:
        ixia = _ixia()
        multivalue = _ScriptedMultivalue(update_on_write=False)

        with (
            patch("neteng.test_infra.dne.taac.ixia.ixia.time.sleep"),
            self.assertRaisesRegex(RuntimeError, "readback mismatch"),
        ):
            self._create_peer(ixia=ixia, peer=_Peer(multivalue), window=1500)

        self.assertEqual([1500], multivalue.single_calls)

    def test_transient_readback_failure_is_retried(self) -> None:
        ixia = _ixia()
        multivalue = _ScriptedMultivalue(
            post_write_reads=(IxnIxNetworkError("REST read failed"), "1500")
        )

        with patch("neteng.test_infra.dne.taac.ixia.ixia.time.sleep") as sleep:
            result = self._create_peer(
                ixia=ixia,
                peer=_Peer(multivalue),
                window=1500,
            )

        self.assertIsInstance(result, _Peer)
        self.assertEqual([1500], multivalue.single_calls)
        sleep.assert_called_once()

    def test_mismatch_is_retained_when_later_readbacks_fail(self) -> None:
        ixia = _ixia()
        read_error = IxnIxNetworkError("REST read failed")
        multivalue = _ScriptedMultivalue(
            update_on_write=False,
            post_write_reads=("65535", read_error, read_error, read_error),
        )

        with (
            patch("neteng.test_infra.dne.taac.ixia.ixia.time.sleep"),
            self.assertRaisesRegex(
                RuntimeError,
                "readback mismatch.*last observed='65535'.*last read error",
            ),
        ):
            self._create_peer(ixia=ixia, peer=_Peer(multivalue), window=1500)

    def test_unavailable_readback_fails_after_retries(self) -> None:
        ixia = _ixia()
        pre_error = IxnIxNetworkError("REST pre-write read failed")
        read_error = IxnIxNetworkError("REST read failed")
        multivalue = _ScriptedMultivalue(
            pre_write_reads=(pre_error,),
            post_write_reads=(read_error,) * 4,
        )

        with (
            patch("neteng.test_infra.dne.taac.ixia.ixia.time.sleep") as sleep,
            self.assertRaisesRegex(
                RuntimeError, "could not verify the readback"
            ) as context,
        ):
            self._create_peer(ixia=ixia, peer=_Peer(multivalue), window=1500)

        self.assertIs(context.exception.__cause__, read_error)
        self.assertEqual(3, sleep.call_count)

    def test_write_failures_use_the_documented_runtime_error(self) -> None:
        for error in (
            IxnIxNetworkError("REST write failed"),
            IndexError("missing value"),
            KeyError("missing value"),
        ):
            with self.subTest(error=type(error).__name__):
                ixia = _ixia()
                multivalue = _ScriptedMultivalue(write_error=error)

                with self.assertRaisesRegex(RuntimeError, "Could not set") as context:
                    self._create_peer(
                        ixia=ixia,
                        peer=_Peer(multivalue),
                        window=1500,
                    )

                self.assertIs(context.exception.__cause__, error)

    def test_empty_readback_fails_after_retries(self) -> None:
        ixia = _ixia()
        multivalue = _ScriptedMultivalue(None, update_on_write=False)

        with (
            patch("neteng.test_infra.dne.taac.ixia.ixia.time.sleep"),
            self.assertRaisesRegex(RuntimeError, "empty Pattern value"),
        ):
            self._create_peer(ixia=ixia, peer=_Peer(multivalue), window=1500)

    def test_read_error_is_retained_when_later_readbacks_are_empty(self) -> None:
        ixia = _ixia()
        read_error = IxnIxNetworkError("REST read failed")
        multivalue = _ScriptedMultivalue(
            None,
            update_on_write=False,
            post_write_reads=(read_error, None, None, None),
        )

        with (
            patch("neteng.test_infra.dne.taac.ixia.ixia.time.sleep"),
            self.assertRaisesRegex(RuntimeError, "REST read failed") as context,
        ):
            self._create_peer(ixia=ixia, peer=_Peer(multivalue), window=1500)

        self.assertIs(context.exception.__cause__, read_error)

    def test_expected_read_errors_use_the_operation_error(self) -> None:
        for error in (
            ValueError("invalid readback"),
            AttributeError("missing Pattern"),
            IndexError("missing value"),
            KeyError("missing value"),
        ):
            with self.subTest(error=type(error).__name__):
                ixia = _ixia()
                multivalue = _ScriptedMultivalue(
                    post_write_reads=(error,) * 4,
                )

                with (
                    patch("neteng.test_infra.dne.taac.ixia.ixia.time.sleep"),
                    self.assertRaisesRegex(
                        RuntimeError, "could not verify the readback"
                    ) as context,
                ):
                    self._create_peer(
                        ixia=ixia,
                        peer=_Peer(multivalue),
                        window=1500,
                    )

                self.assertIs(context.exception.__cause__, error)

    def test_programming_error_in_readback_is_not_retried(self) -> None:
        ixia = _ixia()
        multivalue = _ScriptedMultivalue(
            post_write_reads=(AssertionError("unexpected programming error"),)
        )

        with (
            patch("neteng.test_infra.dne.taac.ixia.ixia.time.sleep") as sleep,
            self.assertRaisesRegex(AssertionError, "unexpected programming error"),
        ):
            self._create_peer(ixia=ixia, peer=_Peer(multivalue), window=1500)

        sleep.assert_not_called()

    def test_programming_error_in_prewrite_pattern_is_not_swallowed(self) -> None:
        ixia = _ixia()
        multivalue = _ScriptedMultivalue(
            pre_write_reads=(AssertionError("unexpected programming error"),)
        )

        with self.assertRaisesRegex(AssertionError, "unexpected programming error"):
            self._create_peer(ixia=ixia, peer=_Peer(multivalue), window=1500)

        self.assertEqual([], multivalue.single_calls)

    def test_missing_ixia_property_fails_setup(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "does not support"):
            self._create_peer(ixia=_ixia(), peer=object(), window=1500)

    def test_property_read_failure_is_not_treated_as_unsupported(self) -> None:
        read_error = AttributeError("REST property read failed")
        peer = _Peer(_ScriptedMultivalue(), property_error=read_error)

        with self.assertRaisesRegex(RuntimeError, "Could not read") as context:
            self._create_peer(ixia=_ixia(), peer=peer, window=1500)

        self.assertIs(context.exception.__cause__, read_error)

    def test_invalid_window_reports_peer_context(self) -> None:
        with self.assertRaisesRegex(
            RuntimeError,
            "dut:Ethernet1.*BGP_SLOW.*must be positive",
        ):
            self._create_peer(
                ixia=_ixia(),
                peer=_Peer(_ScriptedMultivalue()),
                window=0,
            )

    def test_dynamic_window_property_receives_the_declared_window(self) -> None:
        ixia = _ixia()
        multivalue = _ScriptedMultivalue()
        peer = _DynamicPropertyPeer(multivalue)

        result = self._create_peer(ixia=ixia, peer=peer, window=1500)

        self.assertIs(peer, result)
        self.assertEqual([1500], multivalue.single_calls)

    def test_imperative_api_uses_validated_verified_write_path(self) -> None:
        ixia = _ixia()
        multivalue = _ScriptedMultivalue()

        touched = self._configure_imperative_peers(
            ixia=ixia,
            peers=[_Peer(multivalue)],
        )

        self.assertEqual(1, touched)
        self.assertEqual([1500], multivalue.single_calls)
        self.assertEqual("1500", multivalue.value)

    def test_imperative_api_reports_partial_transport_failure(self) -> None:
        ixia = _ixia()
        failed = _ScriptedMultivalue(write_error=IxnIxNetworkError("REST write failed"))
        successful = _ScriptedMultivalue()

        with self.assertRaisesRegex(
            RuntimeError,
            r"2 supported peer\(s\), but only 1 peer\(s\) accepted and "
            r"verified.*Successful peer writes remain applied",
        ):
            self._configure_imperative_peers(
                ixia=ixia,
                peers=[
                    _Peer(failed, name="BGP_SLOW_1"),
                    _Peer(successful, name="BGP_SLOW_2"),
                ],
            )

        self.assertEqual([1500], failed.single_calls)
        self.assertEqual([1500], successful.single_calls)
        t.cast(t.Any, ixia.logger.warning).assert_called_once()

    def test_imperative_api_retries_transient_read_failure(self) -> None:
        ixia = _ixia()
        multivalue = _ScriptedMultivalue(
            post_write_reads=(IxnIxNetworkError("REST read failed"), "1500")
        )

        with patch("neteng.test_infra.dne.taac.ixia.ixia.time.sleep") as sleep:
            touched = self._configure_imperative_peers(
                ixia=ixia,
                peers=[_Peer(multivalue)],
            )

        self.assertEqual(1, touched)
        sleep.assert_called_once_with(0.05)

    def test_imperative_api_isolates_peer_property_failure(self) -> None:
        ixia = _ixia()
        successful = _ScriptedMultivalue()
        failed_peer = _Peer(
            _ScriptedMultivalue(),
            name="BGP_SLOW_1",
            property_error=IxnIxNetworkError("REST property read failed"),
        )

        with self.assertRaisesRegex(
            RuntimeError,
            r"2 supported peer\(s\), but only 1 peer\(s\) accepted and verified",
        ):
            self._configure_imperative_peers(
                ixia=ixia,
                peers=[failed_peer, _Peer(successful, name="BGP_SLOW_2")],
            )

        self.assertEqual([1500], successful.single_calls)
        t.cast(t.Any, ixia.logger.warning).assert_called_once()

    def test_imperative_api_isolates_peer_name_transport_failure(self) -> None:
        ixia = _ixia()
        successful = _ScriptedMultivalue()
        failed_peer = _Peer(
            _ScriptedMultivalue(),
            name_error=IxnIxNetworkError("REST name read failed"),
        )

        with self.assertRaisesRegex(
            RuntimeError,
            r"2 supported peer\(s\), but only 1 peer\(s\) accepted and verified",
        ):
            self._configure_imperative_peers(
                ixia=ixia,
                peers=[failed_peer, _Peer(successful, name="BGP_SLOW_2")],
            )

        self.assertEqual([1500], successful.single_calls)
        t.cast(t.Any, ixia.logger.warning).assert_called_once()

    def test_imperative_api_does_not_mask_name_lookup_failures(self) -> None:
        for error in (IndexError("missing name"), KeyError("missing name")):
            with self.subTest(error=type(error).__name__):
                successful = _ScriptedMultivalue()

                with self.assertRaises(type(error)) as context:
                    self._configure_imperative_peers(
                        ixia=_ixia(),
                        peers=[
                            _Peer(_ScriptedMultivalue(), name_error=error),
                            _Peer(successful, name="BGP_SLOW_2"),
                        ],
                    )

                self.assertIs(context.exception, error)
                self.assertEqual([], successful.single_calls)

    def test_imperative_api_reports_unsupported_and_unverified_peers(self) -> None:
        ixia = _ixia()
        failed_peer = _Peer(
            _ScriptedMultivalue(),
            property_error=IxnIxNetworkError("REST property read failed"),
        )

        with self.assertRaisesRegex(
            RuntimeError,
            r"1 peer\(s\) do not support TcpWindowSizeInBytes and "
            r"1 supported peer\(s\) did not verify",
        ):
            self._configure_imperative_peers(
                ixia=ixia,
                peers=[object(), failed_peer],
            )

    def test_imperative_api_rejects_only_unsupported_peers(self) -> None:
        ixia = _ixia()

        with self.assertRaisesRegex(RuntimeError, "none of their BGP peers support"):
            self._configure_imperative_peers(
                ixia=ixia,
                peers=[object(), object()],
            )

        self.assertEqual(2, t.cast(t.Any, ixia.logger.warning).call_count)

    def test_imperative_api_rejects_a_device_group_without_bgp_peers(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "contain no BGP peers"):
            self._configure_imperative_peers(ixia=_ixia(), peers=[])

    def test_imperative_api_rejects_a_device_group_regex_without_matches(
        self,
    ) -> None:
        ixia = _ixia()

        with (
            patch.object(ixia, "find_device_groups", return_value=[]) as find_groups,
            self.assertRaisesRegex(RuntimeError, "no DGs match"),
        ):
            ixia.configure_bgp_peer_tcp_window_size(
                hostname="dut.example.com",
                interface="Ethernet1",
                device_group_regex="^MISSING$",
                tcp_window_size_bytes=1500,
            )

        find_groups.assert_called_once_with(regex="^MISSING$")

    def test_imperative_api_validates_before_topology_lookup(self) -> None:
        ixia = _ixia()

        with (
            patch.object(ixia, "find_device_groups") as find_groups,
            self.assertRaisesRegex(RuntimeError, "must not exceed 65535"),
        ):
            ixia.configure_bgp_peer_tcp_window_size(
                hostname="dut.example.com",
                interface="Ethernet1",
                device_group_regex=".*",
                tcp_window_size_bytes=65_536,
            )

        find_groups.assert_not_called()

    def test_imperative_api_requires_session_teardown(self) -> None:
        ixia = _ixia()
        ixia.teardown_session = False

        with (
            patch.object(ixia, "find_device_groups") as find_groups,
            self.assertRaisesRegex(RuntimeError, "set teardown_session=True"),
        ):
            ixia.configure_bgp_peer_tcp_window_size(
                hostname="dut.example.com",
                interface="Ethernet1",
                device_group_regex=".*",
                tcp_window_size_bytes=1500,
            )

        find_groups.assert_not_called()
