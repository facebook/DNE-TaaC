# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import os

from taac.utils.oss_taac_lib_utils import memoize_forever
from taac.test_as_a_config import types as taac_types

TAAC_OSS = os.environ.get("TAAC_OSS", "").lower() in ("1", "true", "yes")

if not TAAC_OSS:
    from taac.testconfigs.internal.all import (
        INTERNAL_TEST_CONFIGS,
    )
    OSS_TEST_CONFIG_FACTORIES = []
else:
    from taac.otg.otg_basic_l3_test_config import (
        get_test_config as _get_otg_l3_config
    )
    OSS_TEST_CONFIG_FACTORIES = [
        _get_otg_l3_config,
    ]
    INTERNAL_TEST_CONFIGS = []

TAAC_TEST_CONFIGS = INTERNAL_TEST_CONFIGS


@memoize_forever
def get_test_config(test_config: str) -> taac_types.TestConfig:
    """
    Load a test config by name.
    First checks in-memory TAAC_TEST_CONFIGS, then OSS factory configs.
    In internal mode, falls back to Configerator if not found.
    In OSS mode, raises an error if not found (no Configerator fallback).
    """
    for test_config_obj in TAAC_TEST_CONFIGS:
        if test_config_obj.name == test_config:
            return test_config_obj

    for factory in OSS_TEST_CONFIG_FACTORIES:
        test_config_obj = factory()
        if test_config_obj.name == test_config:
            return test_config_obj

    if TAAC_OSS:
        raise ValueError(
            f"Test config '{test_config}' not found. "
            "In OSS mode, all test configs must be defined in TAAC_TEST_CONFIGS. "
            "Configerator fallback is not available."
        )

    from configerator.client import ConfigeratorClient
    from taac.constants import TAAC_TEST_CONFIG_CONFIGERATOR_PATH

    client = ConfigeratorClient()
    test_config_obj = client.get_config_contents_as_thrift(
        TAAC_TEST_CONFIG_CONFIGERATOR_PATH.format(test_config_name=test_config),
        taac_types.TestConfig,
    )
    return test_config_obj
