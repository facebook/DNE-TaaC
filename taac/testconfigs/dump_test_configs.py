# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""Serialize TAAC TestConfigs to JSONL, one config per line.

Usage:
    buck2 run fbcode//neteng/test_infra/dne/taac/testconfigs:dump_test_configs -- \
        --output /tmp/taac_test_configs.jsonl
"""

import argparse

from neteng.test_infra.dne.taac.test_configs import get_test_config, get_test_configs
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
    parser.add_argument(
        "--test-config",
        help="Write only the TestConfig with this name.",
    )
    args = parser.parse_args()

    configs = (
        (get_test_config(args.test_config),)
        if args.test_config is not None
        else get_test_configs()
    )
    with open(args.output, "w") as payload_file:
        for config in configs:
            payload_file.write(thrift_to_json(config))
            payload_file.write("\n")
