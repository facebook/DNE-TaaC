# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import difflib
import hashlib
import os
from pathlib import Path

from taac.utils.json_thrift_utils import json_to_thrift
from taac.utils.oss_taac_lib_utils import memoize_forever
from taac.test_as_a_config import types as taac_types

TAAC_OSS = os.environ.get("TAAC_OSS", "").lower() in ("1", "true", "yes")

if not TAAC_OSS:
    from taac.testconfigs.internal.all import (
        INTERNAL_TEST_CONFIGS,
    )

    OSS_TEST_CONFIG_FACTORIES = []
else:
    from taac.otg.otg_basic_l3_test_config import (  # pyre-ignore[21]
        get_test_config as _get_otg_l3_config,
    )

    OSS_TEST_CONFIG_FACTORIES = [
        _get_otg_l3_config,
    ]
    INTERNAL_TEST_CONFIGS = []

TAAC_TEST_CONFIGS = INTERNAL_TEST_CONFIGS
EPHEMERAL_TEST_CONFIG_PATH_ENV = "TAAC_EPHEMERAL_TEST_CONFIG_PATH"
EPHEMERAL_TEST_CONFIG_SHA256_ENV = "TAAC_EPHEMERAL_TEST_CONFIG_SHA256"
MAX_EPHEMERAL_TEST_CONFIG_BYTES = 8 * 1024 * 1024


def _known_test_config_names() -> list[str]:
    # The runner matches --test-config against TestConfig.name, so the message
    # must list .name values (not the Python constant identifiers, which can
    # differ, e.g. by a trailing "_CONFIG").
    names = [tc.name for tc in TAAC_TEST_CONFIGS]
    for factory in OSS_TEST_CONFIG_FACTORIES:
        try:
            names.append(factory().name)
        except Exception:
            # A broken factory must not mask the real "config not found" error.
            continue
    return sorted(set(names))


def _unknown_test_config_message(test_config: str) -> str:
    known = _known_test_config_names()
    suggestions = difflib.get_close_matches(test_config, known, n=5, cutoff=0.4)

    lines = [
        f"TAAC test config '{test_config}' not found.",
        "",
        "--test-config must exactly match a TestConfig.name. Note the .name "
        "field can differ from the Python constant identifier (a common trap: "
        "the trailing '_CONFIG' is often NOT part of .name).",
    ]
    if suggestions:
        lines.append("")
        lines.append("Closest matches:")
        lines.extend(f"  {name}" for name in suggestions)
    lines.append("")
    lines.append(f"{len(known)} known test configs:")
    lines.extend(f"  {name}" for name in known)
    return "\n".join(lines)


def _load_ephemeral_test_config(
    requested_name: str,
) -> taac_types.TestConfig | None:
    path_value = os.environ.get(EPHEMERAL_TEST_CONFIG_PATH_ENV)
    expected_digest = os.environ.get(EPHEMERAL_TEST_CONFIG_SHA256_ENV)
    if path_value is None and expected_digest is None:
        return None
    if not path_value or not expected_digest:
        raise ValueError(
            "ephemeral TAAC config requires both path and SHA-256 environment values"
        )
    return _get_ephemeral_test_config(
        requested_name,
        path_value,
        expected_digest.lower(),
    )


@memoize_forever
def _get_ephemeral_test_config(
    requested_name: str,
    path_value: str,
    expected_digest: str,
) -> taac_types.TestConfig:
    path = Path(path_value)
    if not path.is_absolute():
        raise ValueError("ephemeral TAAC config path must be absolute")
    try:
        with path.open("rb") as handle:
            size = os.fstat(handle.fileno()).st_size
            if size <= 0 or size > MAX_EPHEMERAL_TEST_CONFIG_BYTES:
                raise ValueError("ephemeral TAAC config size is outside allowed bounds")
            content = handle.read(MAX_EPHEMERAL_TEST_CONFIG_BYTES + 1)
    except OSError as error:
        raise ValueError("ephemeral TAAC config is unavailable") from error
    if not content or len(content) > MAX_EPHEMERAL_TEST_CONFIG_BYTES:
        raise ValueError("ephemeral TAAC config size is outside allowed bounds")
    if hashlib.sha256(content).hexdigest() != expected_digest:
        raise ValueError("ephemeral TAAC config digest verification failed")
    try:
        config = json_to_thrift(content, taac_types.TestConfig)
    except Exception as error:
        raise ValueError("ephemeral TAAC config could not be decoded") from error
    if config.name != requested_name:
        raise ValueError("ephemeral TAAC config name does not match --test-config")
    return config


@memoize_forever
def _get_registered_test_config(test_config: str) -> taac_types.TestConfig:
    for test_config_obj in TAAC_TEST_CONFIGS:
        if test_config_obj.name == test_config:
            return test_config_obj

    for factory in OSS_TEST_CONFIG_FACTORIES:
        test_config_obj = factory()
        if test_config_obj.name == test_config:
            return test_config_obj

    if TAAC_OSS:
        raise ValueError(_unknown_test_config_message(test_config))

    from configerator.client import (
        ConfigeratorClient,
        ConfigeratorMissingConfigException,
    )
    from taac.constants import TAAC_TEST_CONFIG_CONFIGERATOR_PATH

    client = ConfigeratorClient()
    try:
        return client.get_config_contents_as_thrift(
            TAAC_TEST_CONFIG_CONFIGERATOR_PATH.format(test_config_name=test_config),
            taac_types.TestConfig,
        )
    except ConfigeratorMissingConfigException:
        # A missing Configerator entity here almost always means the name did not
        # match any in-memory TestConfig.name and is not a published config
        # either. The raw ConfigeratorMissingConfigException reads as an infra
        # failure (INFRA_ERROR); re-raise as a clear, actionable user error.
        raise ValueError(_unknown_test_config_message(test_config)) from None


def get_test_config(test_config: str) -> taac_types.TestConfig:
    """Load a registered or invocation-scoped ephemeral TestConfig by name."""
    ephemeral = _load_ephemeral_test_config(test_config)
    if ephemeral is not None:
        return ephemeral
    return _get_registered_test_config(test_config)
