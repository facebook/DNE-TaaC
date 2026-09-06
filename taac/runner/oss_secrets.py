#!/usr/bin/env python3
# pyre-unsafe

"""Strict loader for adopter-owned OSS TAAC credentials.

The loader deliberately supports a very small JSON schema. It translates the
file into the environment variables already consumed by TAAC's OSS drivers,
so internal credential providers and callers that export variables continue
to work unchanged. Secret values are never returned in an exception or log.
"""

import json
import os
import stat
from pathlib import Path
from typing import Dict, List, Set, Tuple

from taac.runner.oss_exceptions import OSSConfigError


_MAX_SECRETS_FILE_BYTES = 64 * 1024
_SCHEMA_VERSION = 1
_FIELD_TO_ENV: Dict[Tuple[str, str], str] = {
    ("dut", "username"): "TAAC_SSH_USER",
    ("dut", "password"): "TAAC_SSH_PASSWORD",
    ("ixia", "username"): "TAAC_IXIA_USERNAME",
    ("ixia", "password"): "TAAC_IXIA_PASSWORD",
}


def _object_without_duplicate_keys(
    pairs: List[Tuple[str, object]],
) -> Dict[str, object]:
    result: Dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate key '{key}'")
        result[key] = value
    return result


def _read_json(path: Path) -> Dict[str, object]:
    try:
        file_stat = path.stat()
    except OSError as exc:
        raise OSSConfigError(f"Cannot access secrets file '{path}': {exc}") from exc

    if not stat.S_ISREG(file_stat.st_mode):
        raise OSSConfigError(f"Secrets path is not a regular file: {path}")
    if file_stat.st_size > _MAX_SECRETS_FILE_BYTES:
        raise OSSConfigError(
            f"Secrets file '{path}' exceeds {_MAX_SECRETS_FILE_BYTES} bytes"
        )

    # The OSS container is Linux-based. Reject group/world access instead of
    # merely warning: a credential file should fail closed when copied with a
    # permissive umask. Existing environment-only credential flows are not
    # affected because this check runs only when --secrets-file is supplied.
    if stat.S_IMODE(file_stat.st_mode) & 0o077:
        raise OSSConfigError(
            f"Secrets file '{path}' is accessible by group or other users; "
            f"run: chmod 600 '{path}'"
        )

    try:
        with path.open("r", encoding="utf-8") as secrets_stream:
            data = json.load(
                secrets_stream,
                object_pairs_hook=_object_without_duplicate_keys,
            )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        # JSON parser messages contain syntax context, never JSON values. Do
        # not include a source excerpt here: it could contain a password.
        raise OSSConfigError(
            f"Secrets file '{path}' is not valid JSON: {type(exc).__name__}"
        ) from exc

    if not isinstance(data, dict):
        raise OSSConfigError(f"Secrets file '{path}' must contain a JSON object")
    return data


def load_oss_secrets(secrets_file: str) -> Set[str]:
    """Validate *secrets_file* and populate TAAC's OSS credential variables.

    Non-empty values from the file are applied with ``setdefault`` so an
    explicitly exported environment variable remains the highest-precedence
    one-run override. The returned set contains environment-variable names,
    never their values.
    """

    path = Path(secrets_file).expanduser()
    data = _read_json(path)

    allowed_top_level = {"version", "dut", "ixia"}
    unknown_top_level = sorted(set(data) - allowed_top_level)
    if unknown_top_level:
        raise OSSConfigError(
            f"Secrets file '{path}' has unsupported top-level field(s)"
        )

    version = data.get("version")
    if version != _SCHEMA_VERSION or isinstance(version, bool):
        raise OSSConfigError(
            f"Secrets file '{path}' must set integer version={_SCHEMA_VERSION}"
        )

    populated: Set[str] = set()
    for section_name in ("dut", "ixia"):
        section = data.get(section_name, {})
        if not isinstance(section, dict):
            raise OSSConfigError(
                f"Secrets file '{path}' field '{section_name}' must be an object"
            )

        allowed_fields = {
            field for section_key, field in _FIELD_TO_ENV if section_key == section_name
        }
        unknown_fields = sorted(set(section) - allowed_fields)
        if unknown_fields:
            raise OSSConfigError(
                f"Secrets file '{path}' section '{section_name}' has unsupported "
                "field(s)"
            )

        for field_name in allowed_fields:
            value = section.get(field_name, "")
            if not isinstance(value, str):
                raise OSSConfigError(
                    f"Secrets file '{path}' field "
                    f"'{section_name}.{field_name}' must be a string"
                )
            if "\x00" in value:
                raise OSSConfigError(
                    f"Secrets file '{path}' field "
                    f"'{section_name}.{field_name}' must not contain a NUL byte"
                )
            if not value:
                continue
            env_name = _FIELD_TO_ENV[(section_name, field_name)]
            os.environ.setdefault(env_name, value)
            populated.add(env_name)

    return populated
