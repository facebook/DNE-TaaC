# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""Serialize every TAAC TestConfig to JSONL, one config per line.

Usage:
    buck2 run fbcode//neteng/test_infra/dne/taac/testconfigs:dump_test_configs -- \
        --output /tmp/taac_test_configs.jsonl
"""

import argparse

from taac.test_configs import TAAC_TEST_CONFIGS
from taac.utils.json_thrift_utils import thrift_to_json


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Dump every TAAC TestConfig as JSONL, one config per line."
    )
    # stdout is not a usable transport here: buck2 writes its own output to the
    # console, importing the config graph installs a console logger, and some
    # configs carry an ssh_password field.
    parser.add_argument(
        "--output",
        required=True,
        help="File to write the JSONL payload to.",
    )
    args = parser.parse_args()

    with open(args.output, "w") as payload_file:
        for config in TAAC_TEST_CONFIGS:
            payload_file.write(thrift_to_json(config))
            payload_file.write("\n")
