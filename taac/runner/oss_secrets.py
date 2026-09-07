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
from typing import Dict, List, Optional, Set, Tuple

from taac.runner.oss_exceptions import OSSConfigError


_MAX_SECRETS_FILE_BYTES = 64 * 1024
_SCHEMA_VERSION = 1
_FIELD_TO_ENV: Dict[Tuple[str, str], str] = {
    ("dut", "username"): "TAAC_SSH_USER",
    ("dut", "password"): "TAAC_SSH_PASSWORD",
    ("ixia", "username"): "TAAC_IXIA_USERNAME",
    ("ixia", "password"): "TAAC_IXIA_PASSWORD",
}
_CREDENTIAL_FIELDS = ("username", "password")
_DUT_HOST_CREDENTIALS_ENV = "_TAAC_OSS_DUT_HOST_CREDENTIALS"


def _normalize_dut_hostname(hostname: str) -> str:
    """Normalize a DUT lookup key without changing addresses or aliases."""

    return hostname.strip().lower().rstrip(".")


def get_oss_dut_credentials(
    hostname: str,
) -> Tuple[Optional[str], Optional[str]]:
    """Return the effective SSH username/password for *hostname*.

    Explicit ``TAAC_SSH_*`` environment variables retain their existing
    highest-precedence behavior. Otherwise, a non-empty per-host value wins
    over the shared ``dut`` value loaded into that environment variable. A
    per-host entry may override only one field and inherit the other.

    The lookup is deliberately exact apart from DNS case and a trailing dot.
    Keys under ``dut.hosts`` should therefore match the values passed through
    ``--dut`` (for RBB, ``TAAC_RBB_R1_HOST`` / ``TAAC_RBB_R2_HOST``).
    """

    try:
        credentials_by_host = json.loads(
            os.environ.get(_DUT_HOST_CREDENTIALS_ENV, "{}")
        )
    except (TypeError, json.JSONDecodeError):
        credentials_by_host = {}
    if not isinstance(credentials_by_host, dict):
        credentials_by_host = {}
    credentials = credentials_by_host.get(_normalize_dut_hostname(hostname), {})
    if not isinstance(credentials, dict):
        credentials = {}

    def effective(field: str, env_name: str) -> Optional[str]:
        environment_value = os.environ.get(env_name) or None
        return credentials.get(field) or environment_value

    return (
        effective("username", "TAAC_SSH_USER"),
        effective("password", "TAAC_SSH_PASSWORD"),
    )


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
    one-run override. Per-host DUT credentials are stored in a private worker
    environment value and selected by the SSH clients using their destination
    hostname. The returned set contains public environment-variable names,
    never secret values or hostnames.
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

    # Parse and validate the complete document before changing process state.
    parsed_fields: Dict[Tuple[str, str], str] = {}
    parsed_host_credentials: Dict[str, Dict[str, str]] = {}
    populated: Set[str] = set()
    for section_name in ("dut", "ixia"):
        section = data.get(section_name, {})
        if not isinstance(section, dict):
            raise OSSConfigError(
                f"Secrets file '{path}' field '{section_name}' must be an object"
            )

        allowed_fields: Set[str] = {
            field for section_key, field in _FIELD_TO_ENV if section_key == section_name
        }
        if section_name == "dut":
            allowed_fields.add("hosts")
        unknown_fields = sorted(set(section) - allowed_fields)
        if unknown_fields:
            raise OSSConfigError(
                f"Secrets file '{path}' section '{section_name}' has unsupported "
                "field(s)"
            )

        for field_name in _CREDENTIAL_FIELDS:
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
            parsed_fields[(section_name, field_name)] = value

    dut_section = data.get("dut", {})
    assert isinstance(dut_section, dict)
    hosts = dut_section.get("hosts", {})
    if not isinstance(hosts, dict):
        raise OSSConfigError(
            f"Secrets file '{path}' field 'dut.hosts' must be an object"
        )
    for hostname, credentials in hosts.items():
        normalized_hostname = _normalize_dut_hostname(hostname)
        if not normalized_hostname:
            raise OSSConfigError(
                f"Secrets file '{path}' contains an empty dut.hosts key"
            )
        if normalized_hostname in parsed_host_credentials:
            raise OSSConfigError(
                f"Secrets file '{path}' contains duplicate normalized DUT host keys"
            )
        if not isinstance(credentials, dict):
            raise OSSConfigError(
                f"Secrets file '{path}' contains a non-object dut.hosts entry"
            )
        unknown_fields = sorted(set(credentials) - set(_CREDENTIAL_FIELDS))
        if unknown_fields:
            raise OSSConfigError(
                f"Secrets file '{path}' contains unsupported dut.hosts field(s)"
            )
        parsed_credentials: Dict[str, str] = {}
        for field_name in _CREDENTIAL_FIELDS:
            value = credentials.get(field_name, "")
            if not isinstance(value, str):
                raise OSSConfigError(
                    f"Secrets file '{path}' contains a non-string dut.hosts "
                    f"credential field"
                )
            if "\x00" in value:
                raise OSSConfigError(
                    f"Secrets file '{path}' contains a NUL byte in a "
                    f"dut.hosts credential field"
                )
            if value:
                parsed_credentials[field_name] = value
        parsed_host_credentials[normalized_hostname] = parsed_credentials

    # Capture overrides before applying shared file values. This lets an
    # explicitly exported TAAC_SSH_* value override even a per-host entry.
    explicit_dut_env = {
        env_name
        for env_name in ("TAAC_SSH_USER", "TAAC_SSH_PASSWORD")
        if os.environ.get(env_name)
    }
    for credentials in parsed_host_credentials.values():
        if "TAAC_SSH_USER" in explicit_dut_env:
            credentials.pop("username", None)
        if "TAAC_SSH_PASSWORD" in explicit_dut_env:
            credentials.pop("password", None)
    for field_key, value in parsed_fields.items():
        if not value:
            continue
        env_name = _FIELD_TO_ENV[field_key]
        os.environ.setdefault(env_name, value)
        populated.add(env_name)
    # Workers may start with multiprocessing's forkserver/spawn modes, where
    # Python module globals are not inherited. Keep the validated host map in
    # one private environment variable so those workers resolve credentials in
    # exactly the same way as the parent process. Existing TAAC credentials are
    # already environment-backed; this variable is likewise never logged.
    os.environ[_DUT_HOST_CREDENTIALS_ENV] = json.dumps(
        parsed_host_credentials, separators=(",", ":"), sort_keys=True
    )

    return populated
