#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""Tests for the ``_eval_jq_simple`` dot-path jq fallback.

pyjq is incompatible with Python 3.12+, so OSS runs never load it and every
``jq_params`` expression goes through this fallback instead of real jq. The
playbook suite addresses per-device data with a QUOTED host key --
``."{hostname}".interfaces`` (18 sites in playbook_definitions.py) -- so the
fallback has to agree with jq on two points: a quoted key is stripped of its
quotes, and the dots inside it are part of the name. Getting either wrong
returns None, which reaches a transform as ``None[::2]`` and fails the step
with "'NoneType' object is not subscriptable" long after the real mistake.
"""

import unittest

from taac.utils.common import _eval_jq_simple, _split_jq_path


class TestSplitJqPath(unittest.TestCase):
    def test_plain_path(self) -> None:
        self.assertEqual(
            _split_jq_path(".dut1.interfaces"), ["dut1", "interfaces"]
        )

    def test_quoted_key_loses_its_quotes(self) -> None:
        self.assertEqual(
            _split_jq_path('."dut1".interfaces'), ["dut1", "interfaces"]
        )

    def test_dots_inside_a_quoted_key_are_part_of_the_name(self) -> None:
        """The case plain str.split(".") gets wrong: an FQDN host key."""
        self.assertEqual(
            _split_jq_path('."fboss159.99.ash6".interfaces'),
            ["fboss159.99.ash6", "interfaces"],
        )

    def test_single_segment(self) -> None:
        self.assertEqual(
            _split_jq_path(".test_case_start_time"), ["test_case_start_time"]
        )

    def test_leading_and_repeated_dots_produce_no_empty_segments(self) -> None:
        self.assertEqual(_split_jq_path(".a..b"), ["a", "b"])


class TestEvalJqSimple(unittest.TestCase):
    def setUp(self) -> None:
        # Shaped like TaacRunner.populate_jq_vars(): host name -> interfaces.
        self.jq_vars = {
            "dut1": {"interfaces": [{"interface_name": "eth1/1/1"}]},
            "fboss159.99.ash6": {"interfaces": [{"interface_name": "eth1/64/1"}]},
            "test_case_start_time": 1234,
        }

    def test_quoted_host_key_resolves(self) -> None:
        """The expression the snake toggle playbooks actually emit."""
        self.assertEqual(
            _eval_jq_simple('."dut1".interfaces', self.jq_vars),
            [{"interface_name": "eth1/1/1"}],
        )

    def test_quoted_fqdn_host_key_resolves(self) -> None:
        self.assertEqual(
            _eval_jq_simple('."fboss159.99.ash6".interfaces', self.jq_vars),
            [{"interface_name": "eth1/64/1"}],
        )

    def test_unquoted_key_still_resolves(self) -> None:
        self.assertEqual(
            _eval_jq_simple(".dut1.interfaces", self.jq_vars),
            [{"interface_name": "eth1/1/1"}],
        )

    def test_single_segment_resolves(self) -> None:
        """Health-check jq params are bare single segments."""
        self.assertEqual(
            _eval_jq_simple(".test_case_start_time", self.jq_vars), 1234
        )

    def test_missing_key_returns_none(self) -> None:
        self.assertIsNone(_eval_jq_simple('."nosuchhost".interfaces', self.jq_vars))

    def test_missing_leaf_returns_none(self) -> None:
        self.assertIsNone(_eval_jq_simple('."dut1".nosuchfield', self.jq_vars))

    def test_non_dot_expression_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _eval_jq_simple("dut1", self.jq_vars)

    def test_navigating_into_non_dict_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _eval_jq_simple(".test_case_start_time.nope", self.jq_vars)


if __name__ == "__main__":
    unittest.main()
