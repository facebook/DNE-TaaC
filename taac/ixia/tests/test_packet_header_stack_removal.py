# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-strict

import unittest
from typing import Any
from unittest.mock import MagicMock, patch

from ixia.ixia import types as ixia_types
from ixnetwork_restpy.errors import NotFoundError
from ixnetwork_restpy.testplatform.sessions.ixnetwork.traffic.trafficitem.configelement.stack.stack import (
    Stack,
)
from taac.ixia.ixia import Ixia


def _stack_query(regex: str) -> ixia_types.Query:
    return ixia_types.Query(regex=regex, query_type=ixia_types.QueryType.STACK_TYPE_ID)


def _removal_header(regex: str) -> ixia_types.PacketHeader:
    return ixia_types.PacketHeader(query=_stack_query(regex), remove_from_stack=True)


class PacketHeaderStackRemovalTest(unittest.TestCase):
    def setUp(self) -> None:
        with patch.object(Ixia, "__init__", lambda self: None):
            self.ixia: Any = Ixia()
        self.ixia.logger = MagicMock()
        self.config_element = MagicMock()
        self.traffic_item = MagicMock(Name="RDMA_IB_TRAFFIC")
        self.traffic_item.ConfigElement.find.return_value = [self.config_element]

    def test_unmatched_stack_find_is_falsy_and_raises_on_remove(self) -> None:
        stack = Stack(None)

        self.assertEqual(len(stack), 0)
        self.assertFalse(stack)
        with self.assertRaises(NotFoundError):
            stack.Remove()

    def test_absent_stack_removal_does_not_raise(self) -> None:
        self.config_element.Stack.find.return_value = Stack(None)

        self.ixia.modify_packet_headers(self.traffic_item, [_removal_header("^tcp$")])

    def test_absent_stack_removal_does_not_call_remove(self) -> None:
        self.config_element.Stack.find.return_value = Stack(None)

        with patch.object(Stack, "Remove") as remove:
            self.ixia.modify_packet_headers(
                self.traffic_item, [_removal_header("^tcp$")]
            )

        remove.assert_not_called()

    def test_present_stack_is_removed_exactly_once(self) -> None:
        present_stack = MagicMock()
        self.config_element.Stack.find.return_value = present_stack

        self.ixia.modify_packet_headers(self.traffic_item, [_removal_header("^tcp$")])

        present_stack.Remove.assert_called_once_with()

    def test_absent_stack_removal_continues_with_remaining_headers(self) -> None:
        present_stack = MagicMock()
        self.config_element.Stack.find.side_effect = [Stack(None), present_stack]

        self.ixia.modify_packet_headers(
            self.traffic_item,
            [_removal_header("^tcp$"), _removal_header("^vlan$")],
        )

        present_stack.Remove.assert_called_once_with()
