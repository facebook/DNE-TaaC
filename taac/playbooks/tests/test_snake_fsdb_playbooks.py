#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-strict

import unittest

from taac.playbooks.playbook_definitions import (
    gen_snake_playbooks,
)


class SnakeFsdbPlaybooksTest(unittest.TestCase):
    def test_fsdb_disruptions_are_not_generated(self) -> None:
        playbook_names = {
            playbook.name
            for playbook in gen_snake_playbooks(hostname="dut1", iteration=1)
        }

        self.assertTrue(
            {"test_snake_fsdb_restart", "test_snake_fsdb_crash"}.isdisjoint(
                playbook_names
            )
        )


if __name__ == "__main__":
    unittest.main()
