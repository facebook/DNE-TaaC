# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict

"""Lab device SSH password lookup for routing EBB test configs."""

import os

from taac.utils.oss_taac_lib_utils import TAAC_OSS

EBB_LAB_DEVICE_PASSWORD_ENV = "TAAC_EBB_LAB_DEVICE_PASSWORD"


def get_lab_device_password(env_var: str = EBB_LAB_DEVICE_PASSWORD_ENV) -> str:
    """Return the lab device SSH password from ``env_var``.

    When ``env_var`` is unset, internal runtimes fall back to the Meta-internal
    default; OSS runtimes have no default and get an empty string.
    """
    if env_var in os.environ:
        return os.environ[env_var]
    if not TAAC_OSS:
        from taac.internal.lab_credentials import (
            EBB_LAB_DEVICE_PASSWORD_DEFAULT,
        )

        return EBB_LAB_DEVICE_PASSWORD_DEFAULT
    return ""
