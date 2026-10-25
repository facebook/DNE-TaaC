"""EOS/BGP++ spelling and command compatibility data."""

import base64
import json
import shlex
import typing as t

from taac.abstractions.validation import (
    validate_fibagent_bgp_nhg_watermarks,
)


# =============================================================================
# BGP Peer Group Names (Standard EBB naming convention)
# =============================================================================
PEERGROUP_IBGP_V6 = "EB-EB-V6"
PEERGROUP_IBGP_V4 = "EB-EB-V4"
PEERGROUP_EBGP_V6 = "EB-FA-V6"
PEERGROUP_EBGP_V4 = "EB-FA-V4"
PEERGROUP_BGP_MON = "BGP-MON"


# =============================================================================
# BGP++ Daemon Names (for arista_daemon_control tasks)
#
# ORDER MATTERS -- this list is the sequential (re)start order, and it follows
# the FIB-programming dependency chain so each daemon's downstream target is
# already up before it starts:
#
#   FibGrpc / FibBgpGrpc  (EosSdkRpc gRPC backends, ports 9544 / 9545)
#     -> FibAgent / FibAgentBgp  (FIB agents, thrift 5912 / 5913)
#       -> Openr / Bgp  (routing daemons)
#
# Bgp MUST be last: BGP++ (the ``Bgp`` daemon) programs routes into
# ``FibAgentBgp`` (thrift 5913 -> FibBgpGrpc 9545) and resolves nexthops via the
# Open-R FIB agent, so those agents/backends must be (re)started BEFORE ``Bgp``.
# If ``Bgp`` starts first it converges its full RIB before its FIB agent exists,
# the FIB agent is then restarted out from under it, and at init BGP++ has
# nothing to program to ("Fib agent is not connected. Skipping fib batch
# programming.") -- forcing a churny resync. See T274256815.
#
# ``Openr`` is enabled only for profiles that require it (see
# _get_control_plane_tasks). ``RouteGrpc`` (EosSdkRpc backing the EOS RouteAgent,
# port 9547) is intentionally excluded: it is not on the BGP++ FIB-programming
# path and nothing in the BGP++ conveyor health/post checks uses it.
# =============================================================================
BGPCPP_DAEMONS = [
    "FibGrpc",
    "FibBgpGrpc",
    "FibAgent",
    "FibAgentBgp",
    "Openr",
    "Bgpcpp",
]

# Ordered phase-3 control-plane recipe. Keep the lists ordered because their
# repr is embedded in the on-device script and daemon startup is order-sensitive.
THRIFT_ACL_FILES = [
    "/usr/facebook/thrift_acls/Bgpd_lab.json",
    "/usr/facebook/thrift_acls/FibAgent.json",
    "/usr/facebook/thrift_acls/FibAgent_lab.json",
]

# BAG images carry the authoritative, release-matched production ACL schemas,
# but some images do not materialize their lab aliases.  The policy-evaluation
# qualification profile uses these image-local files only as schema seeds and
# then adds the existing TAAC user allowlist to every permission below.
LAB_THRIFT_ACL_SOURCE_CANDIDATES = {
    "/usr/facebook/thrift_acls/Bgpd_lab.json": (
        "/usr/facebook/thrift_acls/Bgpd_prod_plane1.json",
    ),
    "/usr/facebook/thrift_acls/FibAgent.json": (
        "/usr/facebook/thrift_acls/FibAgent_prod_plane1.json",
    ),
    "/usr/facebook/thrift_acls/FibAgent_lab.json": (
        "/usr/facebook/thrift_acls/FibAgent_prod_plane1.json",
    ),
}
POLICY_EVALUATION_THRIFT_ACL_MARKER = (
    "/tmp/taac_policy_evaluation_created_thrift_acls.json"
)

# Some BAG images install the fb-bgpcpp RPM and binary but omit the package's
# launcher.  ProcMgr still points the Bgp daemon at this path, so daemon enable
# otherwise reports success while the process never starts.  Keep the fallback
# byte-for-byte compatible with the package launcher shape expected by
# ``configure_bgpcpp_startup`` (in particular, the final --max_rss_size line).
POLICY_EVALUATION_BGPCPP_STARTUP_PATH = "/usr/sbin/run_bgpcpp.sh"
POLICY_EVALUATION_BGPCPP_BINARY_PATH = "/usr/sbin/bgpcpp"
POLICY_EVALUATION_BGPCPP_STARTUP_MARKER = (
    "/tmp/taac_policy_evaluation_created_bgpcpp_startup.json"
)
POLICY_EVALUATION_BGPCPP_STARTUP_FLAGS = {
    "bgp_resolve_nexthops_from_interface_state": "true",
}
POLICY_EVALUATION_BGPCPP_STARTUP_CONTENT = """\
#!/bin/bash
# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

export CONFIGERATOR_PRETEND_NOT_PROD=1
export LC_ALL="C"

BGPCPP="bgpcpp"
CONFIG=/mnt/flash/bgpcpp_config
POLICY=/mnt/flash/bgpcpp_policy
ROUTE_REGISTRY_PREFIX_LIST=/mnt/flash/bgpcpp_route_registry_prefix_list
CONFIG_BACKUP=/mnt/flash/bgpcpp_config_backup
LOGGING='DBG1;default:async=true'
VERBOSITY=1
MAX_RSS_SIZE=20
POLICY_CACHE_SIZE=200000
FIB_AGENT_RCVD_TIMEOUT=80000
FIB_AGENT_PORT=5913

echo "Starting bgp++ daemon..."
exec "${BGPCPP}" \\
      --fbwhoami_strict=false \\
      --fd_soft_limit=4096 \\
      --agent_thrift_port="${FIB_AGENT_PORT}" \\
      --agent_thrift_recv_timeout_ms="${FIB_AGENT_RCVD_TIMEOUT}" \\
      --config="${CONFIG}" \\
      --policy="${POLICY}" \\
      --rp_state_file="${ROUTE_REGISTRY_PREFIX_LIST}"\\
      --bgp_config_backup="${CONFIG_BACKUP}" \\
      --logging="${LOGGING}" \\
      --v "${VERBOSITY}" \\
      --bgp_policy_cache_size="${POLICY_CACHE_SIZE}" \\
      --platform=ebb \\
      --bgp_coro_profiler_enabled=true \\
      --bgp_coro_profiler_export_ods=true \\
      --enable_well_known_community_filter=true \\
      --max_rss_size="${MAX_RSS_SIZE}"
"""

INTERN_USER_IDS = [
    "1179835461009564",
    "1414546347",
    "1531998838006730",
]

_ADD_INTERN_USER_IDS_SCRIPT = f"""\
import json
import os
import sys

UIDS = {repr(INTERN_USER_IDS)}
FILES = {repr(THRIFT_ACL_FILES)}

for f in FILES:
    if not os.path.exists(f):
        print(f"SKIP {{f}}: does not exist")
        continue
    try:
        with open(f) as fh:
            data = json.load(fh)
        modified = False
        for perm in data.get("permissions", []):
            entries = perm.setdefault("entries", [])
            existing_ids = set(
                e.get("identity", {{}}).get("id_data") for e in entries
            )
            for uid in UIDS:
                if uid not in existing_ids:
                    entries.append({{"identity": {{"id_type": "USER", "id_data": uid}}}})
                    modified = True
        if modified:
            with open(f, "w") as fh:
                json.dump(data, fh, indent=4)
            print(f"UPDATED {{f}}")
        else:
            print(f"OK {{f}}: all uids already present")
    except Exception as e:
        print(f"ERROR {{f}}: {{e}}", file=sys.stderr)
        sys.exit(1)
"""

_ADD_INTERN_USER_IDS_SCRIPT_B64 = base64.b64encode(
    _ADD_INTERN_USER_IDS_SCRIPT.encode("utf-8")
).decode("utf-8")
ADD_INTERN_USER_IDS_CMD = (
    f"bash printf '%s' {shlex.quote(_ADD_INTERN_USER_IDS_SCRIPT_B64)} "
    "| base64 -d | sudo python3 -"
)


def _on_device_python_command(script: str) -> str:
    encoded_script = base64.b64encode(script.encode("utf-8")).decode("ascii")
    return (
        f"bash printf '%s' {shlex.quote(encoded_script)} | base64 -d | sudo python3 -"
    )


def _ownership_receipt_script_prelude(
    *,
    marker_path: str,
    receipt_kind: str,
    allowed_paths: t.Iterable[str],
) -> str:
    return "\n".join(
        [
            "import hashlib",
            "import json",
            "import os",
            "import stat",
            "import tempfile",
            "import uuid",
            "from pathlib import Path",
            f"legacy_marker = Path({marker_path!r})",
            f"receipt_kind = {receipt_kind!r}",
            f"allowed_paths = set({tuple(allowed_paths)!r})",
            'receipt_prefix = legacy_marker.name.removesuffix(".json")',
            'receipt_glob = f"{receipt_prefix}.*.receipt.json"',
            "def remove_legacy_marker():",
            "    try:",
            "        metadata = legacy_marker.lstat()",
            "    except FileNotFoundError:",
            "        return",
            "    if stat.S_ISDIR(metadata.st_mode):",
            '        raise RuntimeError(f"legacy marker is a directory: {legacy_marker}")',
            "    legacy_marker.unlink()",
            "def metadata_guard(metadata):",
            "    return (",
            "        metadata.st_dev,",
            "        metadata.st_ino,",
            "        stat.S_IMODE(metadata.st_mode),",
            "        metadata.st_size,",
            "        metadata.st_mtime_ns,",
            "        metadata.st_ctime_ns,",
            "    )",
            "def inspect_file(path):",
            "    descriptor = os.open(",
            "        path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK",
            "    )",
            "    try:",
            "        before = os.fstat(descriptor)",
            "        if not stat.S_ISREG(before.st_mode):",
            '            raise RuntimeError(f"not a regular file: {path}")',
            "        digest = hashlib.sha256()",
            "        while chunk := os.read(descriptor, 1024 * 1024):",
            "            digest.update(chunk)",
            "        after = os.fstat(descriptor)",
            "    finally:",
            "        os.close(descriptor)",
            "    if metadata_guard(before) != metadata_guard(after):",
            '        raise RuntimeError(f"file changed while hashing: {path}")',
            "    current_path = os.lstat(path)",
            "    if (current_path.st_dev, current_path.st_ino) != (",
            "        after.st_dev,",
            "        after.st_ino,",
            "    ):",
            '        raise RuntimeError(f"file identity changed while hashing: {path}")',
            "    return (",
            "        {",
            '            "dev": after.st_dev,',
            '            "ino": after.st_ino,',
            '            "mode": stat.S_IMODE(after.st_mode),',
            '            "uid": after.st_uid,',
            '            "gid": after.st_gid,',
            '            "size": after.st_size,',
            '            "mtime_ns": after.st_mtime_ns,',
            '            "sha256": digest.hexdigest(),',
            "        },",
            "        metadata_guard(after),",
            "    )",
            "def write_receipt(artifacts):",
            "    receipt_id = uuid.uuid4().hex",
            "    receipt = legacy_marker.with_name(",
            '        f"{receipt_prefix}.{receipt_id}.receipt.json"',
            "    )",
            "    payload = (",
            "        json.dumps(",
            "            {",
            '                "version": 1,',
            '                "receipt_id": receipt_id,',
            '                "kind": receipt_kind,',
            '                "artifacts": artifacts,',
            "            },",
            "            sort_keys=True,",
            '            separators=(",", ":"),',
            "        ).encode()",
            '        + b"\\n"',
            "    )",
            "    descriptor, temporary_name = tempfile.mkstemp(",
            '        prefix=f".{receipt.name}.", dir=receipt.parent',
            "    )",
            "    temporary = Path(temporary_name)",
            "    try:",
            "        os.fchmod(descriptor, 0o600)",
            "        view = memoryview(payload)",
            "        while view:",
            "            view = view[os.write(descriptor, view):]",
            "        os.fsync(descriptor)",
            "        os.close(descriptor)",
            "        descriptor = -1",
            "        os.link(temporary, receipt)",
            "    finally:",
            "        if descriptor >= 0:",
            "            os.close(descriptor)",
            "        temporary.unlink(missing_ok=True)",
            "    return receipt",
            "def restore_tombstone(path, tombstone):",
            "    try:",
            "        os.link(tombstone, path, follow_symlinks=False)",
            "    except OSError as error:",
            "        return str(error)",
            "    tombstone.unlink()",
            "    return None",
            "def remove_owned_file(path, expected):",
            "    tombstone = path.with_name(",
            '        f".{path.name}.taac-cleanup.{uuid.uuid4().hex}"',
            "    )",
            "    try:",
            "        path.rename(tombstone)",
            "    except FileNotFoundError:",
            "        return False",
            "    try:",
            "        moved, _ = inspect_file(tombstone)",
            "    except (OSError, RuntimeError) as error:",
            "        restore_error = restore_tombstone(path, tombstone)",
            "        raise RuntimeError(",
            '            f"moved object could not be verified: {path}; "',
            '            f"restore_error={restore_error}"',
            "        ) from error",
            "    if moved != expected:",
            "        restore_error = restore_tombstone(path, tombstone)",
            "        raise RuntimeError(",
            '            f"moved object ownership changed: {path}; "',
            '            f"restore_error={restore_error}"',
            "        )",
            "    tombstone.unlink()",
            "    return True",
            "def rollback_installed(installed):",
            "    refused = []",
            "    for path_string, expected in installed.items():",
            "        path = Path(path_string)",
            "        try:",
            "            remove_owned_file(path, expected)",
            "        except RuntimeError as error:",
            '            refused.append(f"{path}: {error}")',
            "    if refused:",
            '        raise RuntimeError(f"refused materialization rollback: {refused}")',
            "def valid_artifact_record(record):",
            "    if not isinstance(record, dict) or set(record) != {",
            '        "dev",',
            '        "ino",',
            '        "mode",',
            '        "uid",',
            '        "gid",',
            '        "size",',
            '        "mtime_ns",',
            '        "sha256",',
            "    }:",
            "        return False",
            "    if any(",
            "        type(record[field]) is not int or record[field] < 0",
            "        for field in (",
            '            "dev",',
            '            "ino",',
            '            "mode",',
            '            "uid",',
            '            "gid",',
            '            "size",',
            '            "mtime_ns",',
            "        )",
            "    ):",
            "        return False",
            '    digest = record["sha256"]',
            "    return (",
            "        isinstance(digest, str)",
            "        and len(digest) == 64",
            '        and set(digest) <= set("0123456789abcdef")',
            "    )",
            "def load_receipt(receipt):",
            "    descriptor = os.open(",
            "        receipt, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK",
            "    )",
            "    try:",
            "        before = os.fstat(descriptor)",
            "        if (",
            "            not stat.S_ISREG(before.st_mode)",
            "            or stat.S_IMODE(before.st_mode) != 0o600",
            "            or before.st_uid != os.geteuid()",
            "            or before.st_nlink != 1",
            "            or before.st_size > 65536",
            "        ):",
            '            raise RuntimeError(f"invalid receipt file: {receipt}")',
            "        payload = os.read(descriptor, 65537)",
            "        after = os.fstat(descriptor)",
            "    finally:",
            "        os.close(descriptor)",
            "    if len(payload) > 65536 or metadata_guard(before) != metadata_guard(after):",
            '        raise RuntimeError(f"receipt changed while reading: {receipt}")',
            "    current_path = os.lstat(receipt)",
            "    if (current_path.st_dev, current_path.st_ino) != (",
            "        after.st_dev,",
            "        after.st_ino,",
            "    ):",
            '        raise RuntimeError(f"receipt identity changed while reading: {receipt}")',
            "    data = json.loads(payload)",
            "    if not isinstance(data, dict) or set(data) != {",
            '        "version",',
            '        "receipt_id",',
            '        "kind",',
            '        "artifacts",',
            "    }:",
            '        raise RuntimeError(f"invalid receipt schema: {receipt}")',
            '    if data["version"] != 1 or data["kind"] != receipt_kind:',
            '        raise RuntimeError(f"unexpected receipt identity: {receipt}")',
            '    receipt_id = data["receipt_id"]',
            "    try:",
            "        canonical_id = uuid.UUID(hex=receipt_id).hex",
            "    except (AttributeError, TypeError, ValueError) as error:",
            '        raise RuntimeError(f"invalid receipt id: {receipt}") from error',
            '    expected_name = f"{receipt_prefix}.{canonical_id}.receipt.json"',
            "    if receipt_id != canonical_id or receipt.name != expected_name:",
            '        raise RuntimeError(f"receipt name/id mismatch: {receipt}")',
            '    artifacts = data["artifacts"]',
            "    if not isinstance(artifacts, dict) or not artifacts:",
            '        raise RuntimeError(f"empty receipt: {receipt}")',
            "    unexpected = set(artifacts) - allowed_paths",
            "    if unexpected:",
            '        raise RuntimeError(f"unexpected receipt paths: {sorted(unexpected)}")',
            "    if not all(valid_artifact_record(record) for record in artifacts.values()):",
            '        raise RuntimeError(f"invalid artifact record: {receipt}")',
            "    return artifacts",
            "def quarantine_receipt(receipt):",
            "    conflict = receipt.with_name(",
            '        f"{receipt.name}.{uuid.uuid4().hex}.conflict"',
            "    )",
            "    receipt.replace(conflict)",
            "    return conflict",
            "",
        ]
    )


def _build_cleanup_materialized_files_script(
    *,
    allowed_paths: t.Iterable[str],
    marker_path: str,
    receipt_kind: str,
    label: str,
) -> str:
    return "\n".join(
        [
            _ownership_receipt_script_prelude(
                marker_path=marker_path,
                receipt_kind=receipt_kind,
                allowed_paths=allowed_paths,
            ),
            "remove_legacy_marker()",
            "receipts = sorted(legacy_marker.parent.glob(receipt_glob))",
            "if not receipts:",
            f'    print("No TAAC-created {label} receipts to clean")',
            "receipt_artifacts = {}",
            "for receipt in receipts:",
            "    try:",
            "        receipt_artifacts[receipt] = load_receipt(receipt)",
            "    except (OSError, RuntimeError, ValueError) as error:",
            "        conflict = quarantine_receipt(receipt)",
            "        raise RuntimeError(",
            '            f"quarantined invalid receipt {conflict}: {error}"',
            "        ) from error",
            "records_by_path = {}",
            "receipts_by_path = {}",
            "for receipt, artifacts in receipt_artifacts.items():",
            "    for path_string, expected in artifacts.items():",
            "        records_by_path.setdefault(path_string, []).append(expected)",
            "        receipts_by_path.setdefault(path_string, set()).add(receipt)",
            "preflight = {}",
            "conflict_paths = {}",
            "for path_string, expected_records in records_by_path.items():",
            "    path = Path(path_string)",
            "    try:",
            "        current, guard = inspect_file(path)",
            "    except FileNotFoundError:",
            "        preflight[path_string] = None",
            "        continue",
            "    except (OSError, RuntimeError) as error:",
            "        conflict_paths[path_string] = str(error)",
            "        continue",
            "    matching = [record for record in expected_records if record == current]",
            "    if not matching:",
            '        conflict_paths[path_string] = "ownership changed"',
            "        continue",
            "    preflight[path_string] = matching[0]",
            "if conflict_paths:",
            "    conflict_receipts = {",
            "        receipt",
            "        for path_string in conflict_paths",
            "        for receipt in receipts_by_path[path_string]",
            "    }",
            "    quarantined = [",
            "        quarantine_receipt(receipt) for receipt in conflict_receipts",
            "    ]",
            "    raise RuntimeError(",
            '        f"refused cleanup for {conflict_paths}; quarantined {quarantined}"',
            "    )",
            "for path_string, expected in preflight.items():",
            "    if expected is None:",
            "        continue",
            "    path = Path(path_string)",
            "    try:",
            "        removed = remove_owned_file(path, expected)",
            "    except RuntimeError as error:",
            "        conflicts = [",
            "            quarantine_receipt(receipt)",
            "            for receipt in receipts_by_path[path_string]",
            "        ]",
            "        raise RuntimeError(",
            '            f"refused cleanup after concurrent change; receipts {conflicts}"',
            "        ) from error",
            "    if removed:",
            f'        print(f"REMOVED TAAC-created {label} {{path}}")',
            "for receipt in receipts:",
            "    receipt.unlink()",
            "",
        ]
    )


def _build_cleanup_materialized_files_cmd(
    *,
    allowed_paths: t.Iterable[str],
    marker_path: str,
    receipt_kind: str,
    label: str,
) -> str:
    return _on_device_python_command(
        _build_cleanup_materialized_files_script(
            allowed_paths=allowed_paths,
            marker_path=marker_path,
            receipt_kind=receipt_kind,
            label=label,
        )
    )


def _bgpcpp_startup_content_with_flags(
    content: str,
    startup_flags: t.Mapping[str, str],
) -> str:
    lines = content.splitlines(keepends=True)
    for flag_name, flag_value in startup_flags.items():
        if not flag_name or any(
            not (character.isalnum() or character == "_") for character in flag_name
        ):
            raise ValueError(f"invalid BGP++ startup flag name: {flag_name!r}")
        if not flag_value or any(character in "\x00\r\n\\" for character in flag_value):
            raise ValueError(f"invalid BGP++ startup flag value: {flag_value!r}")
        assignment = f"--{flag_name}="
        lines = [line for line in lines if not line.lstrip().startswith(assignment)]
        anchors = [
            index
            for index, line in enumerate(lines)
            if line.lstrip().startswith("--max_rss_size=")
        ]
        if len(anchors) != 1:
            raise ValueError(
                "BGP++ startup content must have one --max_rss_size anchor"
            )
        lines.insert(anchors[0], f"      --{flag_name}={flag_value} \\\n")
    return "".join(lines)


def build_materialize_missing_lab_thrift_acl_files_cmd(
    *,
    destination_sources: t.Mapping[str, t.Sequence[str]] = (
        LAB_THRIFT_ACL_SOURCE_CANDIDATES
    ),
    marker_path: str = POLICY_EVALUATION_THRIFT_ACL_MARKER,
) -> str:
    """Materialize missing lab ACL aliases and record object ownership."""
    normalized_sources = {
        destination: tuple(sources)
        for destination, sources in destination_sources.items()
    }
    script = "\n".join(
        [
            _ownership_receipt_script_prelude(
                marker_path=marker_path,
                receipt_kind="lab_thrift_acl",
                allowed_paths=normalized_sources,
            ),
            "import shutil",
            f"destination_sources = {normalized_sources!r}",
            f"user_ids = {INTERN_USER_IDS!r}",
            "remove_legacy_marker()",
            "installed = {}",
            "try:",
            "    for destination, candidates in destination_sources.items():",
            "        destination_path = Path(destination)",
            "        try:",
            "            existing = destination_path.lstat()",
            "        except FileNotFoundError:",
            "            existing = None",
            "        if existing is not None:",
            "            if not stat.S_ISREG(existing.st_mode):",
            '                raise RuntimeError(f"ACL destination is not a regular file: {destination}")',
            '            print(f"KEEP {destination}: already present")',
            "            continue",
            "        source_path = next(",
            "            (",
            "                Path(candidate)",
            "                for candidate in candidates",
            "                if Path(candidate).is_file()",
            "            ),",
            "            None,",
            "        )",
            "        if source_path is None:",
            '            raise RuntimeError(f"no image ACL schema for {destination}: {candidates}")',
            "        descriptor, temporary_name = tempfile.mkstemp(",
            '            prefix=f".{destination_path.name}.taac-policy-evaluation.",',
            "            dir=destination_path.parent,",
            "        )",
            "        os.close(descriptor)",
            "        temporary_path = Path(temporary_name)",
            "        claimed = False",
            "        try:",
            "            shutil.copy2(source_path, temporary_path)",
            "            data = json.loads(temporary_path.read_text())",
            "            modified = False",
            '            for permission in data.get("permissions", []):',
            '                entries = permission.setdefault("entries", [])',
            "                existing_ids = {",
            '                    entry.get("identity", {}).get("id_data")',
            "                    for entry in entries",
            "                }",
            "                for user_id in user_ids:",
            "                    if user_id not in existing_ids:",
            "                        entries.append(",
            "                            {",
            '                                "identity": {',
            '                                    "id_type": "USER",',
            '                                    "id_data": user_id,',
            "                                }",
            "                            }",
            "                        )",
            "                        modified = True",
            "            if modified:",
            "                temporary_path.write_text(json.dumps(data, indent=4))",
            "            expected, _ = inspect_file(temporary_path)",
            "            try:",
            "                os.link(temporary_path, destination_path)",
            "                claimed = True",
            "                installed[destination] = expected",
            "            except FileExistsError:",
            "                raced = destination_path.lstat()",
            "                if not stat.S_ISREG(raced.st_mode):",
            '                    raise RuntimeError(f"ACL destination is not a regular file: {destination}")',
            '                print(f"KEEP {destination}: created concurrently")',
            "            if claimed:",
            "                current, _ = inspect_file(destination_path)",
            "                if current != expected:",
            "                    raise RuntimeError(",
            '                        f"ACL ownership changed during materialization: {destination}"',
            "                    )",
            '                print(f"MATERIALIZED {destination} from {source_path}")',
            "        finally:",
            "            temporary_path.unlink(missing_ok=True)",
            "    if installed:",
            "        write_receipt(installed)",
            "except Exception as error:",
            "    try:",
            "        rollback_installed(installed)",
            "    except RuntimeError as rollback_error:",
            "        raise rollback_error from error",
            "    raise",
            "",
        ]
    )
    return _on_device_python_command(script)


def build_cleanup_materialized_lab_thrift_acl_files_cmd(
    *,
    destinations: t.Iterable[str] | None = None,
    marker_path: str = POLICY_EVALUATION_THRIFT_ACL_MARKER,
) -> str:
    """Remove only lab ACL aliases whose ownership receipts still match."""
    allowed_destinations = tuple(
        LAB_THRIFT_ACL_SOURCE_CANDIDATES if destinations is None else destinations
    )
    return _build_cleanup_materialized_files_cmd(
        allowed_paths=allowed_destinations,
        marker_path=marker_path,
        receipt_kind="lab_thrift_acl",
        label="ACL alias",
    )


def build_materialize_missing_bgpcpp_startup_cmd(
    *,
    startup_path: str = POLICY_EVALUATION_BGPCPP_STARTUP_PATH,
    binary_path: str = POLICY_EVALUATION_BGPCPP_BINARY_PATH,
    marker_path: str = POLICY_EVALUATION_BGPCPP_STARTUP_MARKER,
    content: str = POLICY_EVALUATION_BGPCPP_STARTUP_CONTENT,
    startup_flags: t.Mapping[str, str] | None = None,
) -> str:
    """Create the package-compatible launcher and record object ownership."""
    materialized_content = (
        content
        if startup_flags is None
        else _bgpcpp_startup_content_with_flags(content, startup_flags)
    )
    script = "\n".join(
        [
            _ownership_receipt_script_prelude(
                marker_path=marker_path,
                receipt_kind="bgpcpp_startup",
                allowed_paths=(startup_path,),
            ),
            f"startup = Path({startup_path!r})",
            f"binary = Path({binary_path!r})",
            f"content = {materialized_content!r}",
            "remove_legacy_marker()",
            "installed = {}",
            "try:",
            "    try:",
            "        existing = startup.lstat()",
            "    except FileNotFoundError:",
            "        existing = None",
            "    if existing is not None:",
            "        if not stat.S_ISREG(existing.st_mode):",
            '            raise RuntimeError(f"BGP++ startup path is not a regular file: {startup}")',
            '        print(f"KEEP {startup}: already present")',
            "    else:",
            "        if not binary.is_file() or not os.access(binary, os.X_OK):",
            '            raise RuntimeError(f"missing executable BGP++ binary: {binary}")',
            "        descriptor, temporary_name = tempfile.mkstemp(",
            '            prefix=f".{startup.name}.taac-policy-evaluation.",',
            "            dir=startup.parent,",
            "        )",
            "        os.close(descriptor)",
            "        temporary = Path(temporary_name)",
            "        claimed = False",
            "        try:",
            "            temporary.write_text(content)",
            "            temporary.chmod(0o755)",
            "            expected, _ = inspect_file(temporary)",
            "            try:",
            "                os.link(temporary, startup)",
            "                claimed = True",
            "                installed[str(startup)] = expected",
            "            except FileExistsError:",
            "                raced = startup.lstat()",
            "                if not stat.S_ISREG(raced.st_mode):",
            '                    raise RuntimeError(f"BGP++ startup path is not a regular file: {startup}")',
            '                print(f"KEEP {startup}: created concurrently")',
            "            if claimed:",
            "                current, _ = inspect_file(startup)",
            "                if current != expected:",
            "                    raise RuntimeError(",
            '                        f"launcher ownership changed during materialization: {startup}"',
            "                    )",
            '                print(f"MATERIALIZED {startup} for {binary}")',
            "        finally:",
            "            temporary.unlink(missing_ok=True)",
            "    if installed:",
            "        write_receipt(installed)",
            "except Exception as error:",
            "    try:",
            "        rollback_installed(installed)",
            "    except RuntimeError as rollback_error:",
            "        raise rollback_error from error",
            "    raise",
            "",
        ]
    )
    return _on_device_python_command(script)


def build_cleanup_materialized_bgpcpp_startup_cmd(
    *,
    startup_path: str = POLICY_EVALUATION_BGPCPP_STARTUP_PATH,
    marker_path: str = POLICY_EVALUATION_BGPCPP_STARTUP_MARKER,
) -> str:
    """Remove only a launcher whose ownership receipt still matches."""
    return _build_cleanup_materialized_files_cmd(
        allowed_paths=(startup_path,),
        marker_path=marker_path,
        receipt_kind="bgpcpp_startup",
        label="BGP++ launcher",
    )


def build_cleanup_materialized_policy_evaluation_files_cmd(
    *,
    startup_path: str = POLICY_EVALUATION_BGPCPP_STARTUP_PATH,
    startup_marker_path: str = POLICY_EVALUATION_BGPCPP_STARTUP_MARKER,
    acl_destinations: t.Iterable[str] | None = None,
    acl_marker_path: str = POLICY_EVALUATION_THRIFT_ACL_MARKER,
) -> str:
    """Attempt launcher and ACL cleanup independently, then report failures."""
    allowed_acl_destinations = tuple(
        LAB_THRIFT_ACL_SOURCE_CANDIDATES
        if acl_destinations is None
        else acl_destinations
    )
    cleanup_scripts = (
        (
            "BGP++ launcher",
            _build_cleanup_materialized_files_script(
                allowed_paths=(startup_path,),
                marker_path=startup_marker_path,
                receipt_kind="bgpcpp_startup",
                label="BGP++ launcher",
            ),
        ),
        (
            "ACL aliases",
            _build_cleanup_materialized_files_script(
                allowed_paths=allowed_acl_destinations,
                marker_path=acl_marker_path,
                receipt_kind="lab_thrift_acl",
                label="ACL alias",
            ),
        ),
    )
    script = "\n".join(
        [
            "import traceback",
            f"cleanup_scripts = {cleanup_scripts!r}",
            "failures = []",
            "for cleanup_label, cleanup_script in cleanup_scripts:",
            "    try:",
            "        exec(compile(cleanup_script, cleanup_label, 'exec'), {})",
            "    except Exception as error:",
            "        failures.append(",
            "            f'{cleanup_label}: {type(error).__name__}: {error}\\n'",
            "            + traceback.format_exc()",
            "        )",
            "if failures:",
            "    raise RuntimeError(",
            "        'policy-evaluation cleanup failed after all attempts: '",
            "        + '; '.join(failures)",
            "    )",
            "",
        ]
    )
    return _on_device_python_command(script)


_REQUIRE_THRIFT_ACL_FILES_SCRIPT = "\n".join(
    [
        "from pathlib import Path",
        f"paths = {THRIFT_ACL_FILES!r}",
        "missing = [path for path in paths if not Path(path).is_file()]",
        "if missing:",
        '    raise RuntimeError(f"missing required Thrift ACL files: {missing}")',
        'print(f"Found required Thrift ACL files: {paths}")',
        "",
    ]
)
REQUIRE_THRIFT_ACL_FILES_CMD = _on_device_python_command(
    _REQUIRE_THRIFT_ACL_FILES_SCRIPT
)

_VERIFY_THRIFT_ACL_USER_IDS_SCRIPT = "\n".join(
    [
        "import json",
        "from pathlib import Path",
        f"paths = {THRIFT_ACL_FILES!r}",
        f"expected = set({INTERN_USER_IDS!r})",
        "errors = []",
        "for path in paths:",
        "    permissions = json.loads(Path(path).read_text()).get('permissions', [])",
        "    if not permissions:",
        '        errors.append(f"{path}: no permissions")',
        "        continue",
        "    for index, permission in enumerate(permissions):",
        "        actual = {",
        "            entry.get('identity', {}).get('id_data')",
        "            for entry in permission.get('entries', [])",
        "        }",
        "        missing = sorted(expected - actual)",
        "        if missing:",
        '            errors.append(f"{path}: permissions[{index}] missing {missing}")',
        "if errors:",
        '    raise RuntimeError("; ".join(errors))',
        'print("Verified required user IDs in all Thrift ACL permissions")',
        "",
    ]
)
VERIFY_THRIFT_ACL_USER_IDS_CMD = _on_device_python_command(
    _VERIFY_THRIFT_ACL_USER_IDS_SCRIPT
)

POST_ACL_RESTART_DAEMONS = ["FibAgent", "FibAgentBgp", "Bgpcpp"]

EBB_BGPCPP_LOGGING_CONFIG = "DBG5;default:async=true"


def build_update_group_setting_override_cmd(
    enable_update_group: bool,
    *,
    config_path: str = "/mnt/flash/bgpcpp_config",
) -> str:
    enabled_literal = repr(enable_update_group)
    script = "\n".join(
        [
            "import json",
            "import os",
            "import shutil",
            "import tempfile",
            "from pathlib import Path",
            f"config_path = Path({config_path!r})",
            "config = json.loads(config_path.read_text())",
            "bgp_settings = config.setdefault('bgp_setting_config', {})",
            f"bgp_settings['enable_update_group'] = {enabled_literal}",
            "updated_content = (json.dumps(config, indent=2) + '\\n').encode()",
            "metadata = config_path.stat()",
            "fd, temporary_name = tempfile.mkstemp(",
            "    dir=config_path.parent, prefix=f'.{config_path.name}.'",
            ")",
            "temporary_path = Path(temporary_name)",
            "try:",
            "    with os.fdopen(fd, 'wb') as temporary_file:",
            "        temporary_file.write(updated_content)",
            "        temporary_file.flush()",
            "        os.fsync(temporary_file.fileno())",
            "    temporary_metadata = temporary_path.stat()",
            "    if (temporary_metadata.st_uid, temporary_metadata.st_gid) != (",
            "        metadata.st_uid, metadata.st_gid",
            "    ):",
            "        os.chown(temporary_path, metadata.st_uid, metadata.st_gid)",
            "    shutil.copymode(config_path, temporary_path)",
            "    os.replace(temporary_path, config_path)",
            "finally:",
            "    temporary_path.unlink(missing_ok=True)",
            "if config_path.read_bytes() != updated_content:",
            "    raise RuntimeError('failed to verify BGP++ config replacement')",
            f"print('Set bgp_setting_config.enable_update_group={str(enable_update_group).lower()}')",
            "",
        ]
    )
    return _on_device_python_command(script)


# =============================================================================
# BGP++ Update Group Config (UpdateGroupConfig thrift struct, D100093369)
# Field names are camelCase to match the on-device JSON serialization of the
# thrift struct (UpdateGroupConfig in bgp_config.thrift).
# Used by the *_UPDATE_GROUP variants of the conveyor test configs.
# =============================================================================
UPDATE_GROUP_ALLOW_SLOW_PEER_DETACH = False
UPDATE_GROUP_SLOW_PEER_TIME_THRESHOLD_MS = 50000
UPDATE_GROUP_SLOW_PEER_BLOCK_COUNT_THRESHOLD = 10
UPDATE_GROUP_SLOW_PEER_BLOCK_COUNT_WINDOW_MS = 1000
UPDATE_GROUP_ENABLE_SERIALIZE_GROUP_PDU = True

UPDATE_GROUP_CONFIG: t.Dict[str, t.Any] = {
    "allowSlowPeerDetach": UPDATE_GROUP_ALLOW_SLOW_PEER_DETACH,
    "slowPeerTimeThresholdMs": UPDATE_GROUP_SLOW_PEER_TIME_THRESHOLD_MS,
    "slowPeerBlockCountThreshold": UPDATE_GROUP_SLOW_PEER_BLOCK_COUNT_THRESHOLD,
    "slowPeerBlockCountWindowMs": UPDATE_GROUP_SLOW_PEER_BLOCK_COUNT_WINDOW_MS,
    "enableSerializeGroupPdu": UPDATE_GROUP_ENABLE_SERIALIZE_GROUP_PDU,
}


# =============================================================================
# BGP++ Supporting Agent Config Files (required for FibAgent daemons)
# Deployed via embedded base64 to avoid arista_create_file_from_config
# which silently fails on some devices.
# Generated from: configerator/raw_configs/taac/ebb_ci_cd_configs/
# To regenerate: cat <file> | base64 -w0
# =============================================================================
FIBAGENT_BGP_CONF_DEVICE_PATH = "/mnt/fb/agent_configs/fib_agent_bgp.conf"
FIBAGENT_BGP_CONF_B64 = "eyIxIjp7InJlYyI6eyIxIjp7ImkzMiI6NjAxMDB9LCIyIjp7ImkzMiI6NDh9LCIzIjp7ImkzMiI6NX0sIjQiOnsiaTMyIjoxNX0sIjUiOnsic3RyIjoiIn0sIjYiOnsic3RyIjoiL3BlcnNpc3Qvc2VjdXJlL2NhcGkucGVtIn0sIjciOnsic3RyIjoiL3BlcnNpc3Qvc2VjdXJlL2NhcGlrZXkucGVtIn0sIjgiOnsic3RyIjoiL21udC9mYi9jZXJ0cy9BcmlzdGFGaWJBZ2VudF9zZXJ2ZXIucGVtIn0sIjkiOnsiaTMyIjo1OTEzfSwiMTAiOnsic3RyIjoiL3Zhci9mYWNlYm9vay9yb290Y2FuYWwvY2EucGVtIn0sIjExIjp7InRmIjoxfSwiMTIiOnsidGYiOjF9LCIxMyI6eyJzdHIiOiJGaWJTZXJ2aWNlIn0sIjE0Ijp7ImkzMiI6MX0sIjE1Ijp7ImkzMiI6MX0sIjE2Ijp7InRmIjoxfSwiMTciOnsidGYiOjF9LCIxOCI6eyJzdHIiOiIvdXNyL2ZhY2Vib29rL3RocmlmdF9hY2xzL0ZpYkFnZW50X2xhYi5qc29uIn0sIjE5Ijp7InN0ciI6Ii91c3IvZmFjZWJvb2svdGhyaWZ0X2FjbHMvYXV0aF9raWxsX3N3aXRjaF9maWxlIn0sIjIwIjp7InRmIjowfSwiMjEiOnsiaTMyIjo3MjAwfSwiMjIiOnsidGYiOjF9LCIyMyI6eyJ0ZiI6MX0sIjI0Ijp7ImkzMiI6LTF9LCIyNSI6eyJzdHIiOiJGaWIgYWdlbnQgaXMgZGVzaWduZWQgdG8gZXhlY3V0ZSByZW1vdGUgcHJvZ3JhbW1pbmcgcmVxdWVzdHMgZnJvbSBPcGVuL1IgdG8gY2hhbmdlIE9wZW4vUiByb3V0ZXMgYWRtaW4gZGlzdGFuY2VzIHRvIGluZmx1ZW5jZSBiZXN0IHBhdGggc2VsZWN0aW9ucy4ifSwiMjYiOnsiaTMyIjo5NTQ1fSwiMjciOnsic3RyIjoiIn0sIjI4Ijp7InRmIjoxfSwiMjkiOnsidGYiOjB9LCIzMCI6eyJpMzIiOjB9LCIzMSI6eyJ0ZiI6MH0sIjMyIjp7InRmIjowfSwiMzMiOnsidGYiOjB9LCIzNCI6eyJpMzIiOjYwfSwiMzUiOnsidGYiOjB9LCIzNiI6eyJpMzIiOjEwMH19fSwiMiI6eyJ0ZiI6MH0sIjMiOnsidGYiOjF9LCI0Ijp7ImkzMiI6Nzg3fSwiNSI6eyJpMzIiOjIwMH0sIjYiOnsiaTMyIjo0MH0sIjciOnsidGYiOjF9LCI4Ijp7ImkzMiI6MjAwfSwiOSI6eyJpMzIiOjIwMH0sIjExIjp7InRmIjowfSwiMTIiOnsic3RyIjoiYmdwZ3JwXyJ9LCIxMyI6eyJ0ZiI6MH0sIjE0Ijp7ImkzMiI6MX19Cg=="  # noqa: E501
FIBAGENT_BGP_CONF_DEPLOY_CMD = (
    f"bash echo '{FIBAGENT_BGP_CONF_B64}' | base64 -d > {FIBAGENT_BGP_CONF_DEVICE_PATH}"
)


def _build_atomic_config_replace_cmd(
    *,
    path: str,
    content: bytes,
    success_message: str,
) -> str:
    encoded_content = base64.b64encode(content).decode("ascii")
    script = "\n".join(
        [
            "import base64",
            "import os",
            "import shutil",
            "import tempfile",
            "from pathlib import Path",
            f"path = Path({path!r})",
            f"updated_content = base64.b64decode({encoded_content!r})",
            "path.parent.mkdir(parents=True, exist_ok=True)",
            "metadata = path.stat() if path.exists() else None",
            "fd, temporary_name = tempfile.mkstemp(",
            "    dir=path.parent, prefix=f'.{path.name}.'",
            ")",
            "temporary_path = Path(temporary_name)",
            "try:",
            "    with os.fdopen(fd, 'wb') as temporary_file:",
            "        temporary_file.write(updated_content)",
            "        temporary_file.flush()",
            "        os.fsync(temporary_file.fileno())",
            "    if metadata is None:",
            "        os.chmod(temporary_path, 0o644)",
            "    else:",
            "        temporary_metadata = temporary_path.stat()",
            "        if (temporary_metadata.st_uid, temporary_metadata.st_gid) != (",
            "            metadata.st_uid, metadata.st_gid",
            "        ):",
            "            os.chown(temporary_path, metadata.st_uid, metadata.st_gid)",
            "        shutil.copymode(path, temporary_path)",
            "    os.replace(temporary_path, path)",
            "    directory_fd = os.open(path.parent, os.O_RDONLY)",
            "    try:",
            "        os.fsync(directory_fd)",
            "    finally:",
            "        os.close(directory_fd)",
            "finally:",
            "    temporary_path.unlink(missing_ok=True)",
            "if path.read_bytes() != updated_content:",
            "    raise RuntimeError('failed to verify atomic config replacement')",
            f"print({success_message!r})",
            "",
        ]
    )
    return _on_device_python_command(script)


def build_fibagent_bgp_config_deploy_cmd(
    *,
    next_hop_group_watermark_high: int | None = None,
    next_hop_group_watermark_low: int | None = None,
) -> str:
    watermarks = validate_fibagent_bgp_nhg_watermarks(
        next_hop_group_watermark_high,
        next_hop_group_watermark_low,
    )
    if watermarks is None:
        return FIBAGENT_BGP_CONF_DEPLOY_CMD
    next_hop_group_watermark_high, next_hop_group_watermark_low = watermarks

    config = _fibagent_bgp_config(
        next_hop_group_watermark_high,
        next_hop_group_watermark_low,
    )
    return _build_atomic_config_replace_cmd(
        path=FIBAGENT_BGP_CONF_DEVICE_PATH,
        content=(json.dumps(config, separators=(",", ":")) + "\n").encode("utf-8"),
        success_message="Atomically installed FibAgentBgp NHG watermark config",
    )


def build_fibagent_bgp_config_restore_cmd() -> str:
    return _build_atomic_config_replace_cmd(
        path=FIBAGENT_BGP_CONF_DEVICE_PATH,
        content=base64.b64decode(FIBAGENT_BGP_CONF_B64),
        success_message="Atomically restored default FibAgentBgp config",
    )


def build_fibagent_bgp_config_verify_cmd(
    *,
    next_hop_group_watermark_high: int | None = None,
    next_hop_group_watermark_low: int | None = None,
) -> str:
    watermarks = validate_fibagent_bgp_nhg_watermarks(
        next_hop_group_watermark_high,
        next_hop_group_watermark_low,
    )
    expected = (
        _fibagent_bgp_config(*watermarks)
        if watermarks is not None
        else _fibagent_bgp_config()
    )
    script = "\n".join(
        [
            "import json",
            "from pathlib import Path",
            f"path = Path({FIBAGENT_BGP_CONF_DEVICE_PATH!r})",
            f"expected = {expected!r}",
            "actual = json.loads(path.read_text())",
            "if actual != expected:",
            "    raise RuntimeError(",
            "        f'FibAgentBgp config readback mismatch: {actual!r}'",
            "    )",
            "print('Verified FibAgentBgp config readback')",
            "",
        ]
    )
    return _on_device_python_command(script)


def _fibagent_bgp_config(high: int | None = None, low: int | None = None) -> t.Any:
    config = json.loads(base64.b64decode(FIBAGENT_BGP_CONF_B64))
    if high is None or low is None:
        return config
    config["10"] = {
        "rec": {
            "1": {"i32": high},
            "2": {"i32": low},
        }
    }
    return config


FIBAGENT_CONF_DEVICE_PATH = "/mnt/fb/agent_configs/fib_agent.conf"
FIBAGENT_CONF_B64 = "eyIxIjp7InJlYyI6eyIxIjp7ImkzMiI6NjAxMDB9LCIyIjp7ImkzMiI6NDh9LCIzIjp7ImkzMiI6NX0sIjQiOnsiaTMyIjoxNX0sIjUiOnsic3RyIjoiIn0sIjYiOnsic3RyIjoiL3BlcnNpc3Qvc2VjdXJlL2NhcGkucGVtIn0sIjciOnsic3RyIjoiL3BlcnNpc3Qvc2VjdXJlL2NhcGlrZXkucGVtIn0sIjgiOnsic3RyIjoiL21udC9mYi9jZXJ0cy9BcmlzdGFGaWJBZ2VudF9zZXJ2ZXIucGVtIn0sIjkiOnsiaTMyIjo1OTEyfSwiMTAiOnsic3RyIjoiL3Zhci9mYWNlYm9vay9yb290Y2FuYWwvY2EucGVtIn0sIjExIjp7InRmIjoxfSwiMTIiOnsidGYiOjF9LCIxMyI6eyJzdHIiOiJGaWJTZXJ2aWNlIn0sIjE0Ijp7ImkzMiI6MX0sIjE1Ijp7ImkzMiI6MX0sIjE2Ijp7InRmIjoxfSwiMTciOnsidGYiOjF9LCIxOCI6eyJzdHIiOiIvdXNyL2ZhY2Vib29rL3RocmlmdF9hY2xzL0ZpYkFnZW50X2xhYi5qc29uIn0sIjE5Ijp7InN0ciI6Ii91c3IvZmFjZWJvb2svdGhyaWZ0X2FjbHMvYXV0aF9raWxsX3N3aXRjaF9maWxlIn0sIjIwIjp7InRmIjowfSwiMjEiOnsiaTMyIjo3MjAwfSwiMjIiOnsidGYiOjF9LCIyMyI6eyJ0ZiI6MX0sIjI0Ijp7ImkzMiI6LTF9LCIyNSI6eyJzdHIiOiJGaWIgYWdlbnQgaXMgZGVzaWduZWQgdG8gZXhlY3V0ZSByZW1vdGUgcHJvZ3JhbW1pbmcgcmVxdWVzdHMgZnJvbSBPcGVuL1IgdG8gY2hhbmdlIE9wZW4vUiByb3V0ZXMgYWRtaW4gZGlzdGFuY2VzIHRvIGluZmx1ZW5jZSBiZXN0IHBhdGggc2VsZWN0aW9ucy4ifSwiMjYiOnsiaTMyIjo5NTQ0fSwiMjciOnsic3RyIjoiIn19fSwiMiI6eyJ0ZiI6MH0sIjMiOnsidGYiOjF9LCI0Ijp7ImkzMiI6Nzg2fSwiNSI6eyJpMzIiOjEwfSwiNiI6eyJpMzIiOjQwfSwiNyI6eyJ0ZiI6MH19"  # noqa: E501
FIBAGENT_CONF_DEPLOY_CMD = (
    f"bash echo '{FIBAGENT_CONF_B64}' | base64 -d > {FIBAGENT_CONF_DEVICE_PATH}"
)


# =============================================================================
# Control Plane ACLs
# These ACLs permit BGP++, FibAgent, and other control plane traffic.
# =============================================================================
ACL_COMMANDS = (
    "configure\n"
    "ipv6 access-list aiv6-control-plane-acl\n"
    "counters per-entry\n"
    "10 permit icmpv6 any any\n"
    "20 permit ipv6 any any tracked\n"
    "30 permit udp any any eq bfd hop-limit eq 255\n"
    "40 permit udp any any eq bfd-echo hop-limit eq 254\n"
    "50 permit udp any any eq multihop-bfd\n"
    "60 permit udp any any eq micro-bfd\n"
    "70 permit udp any any eq sbfd\n"
    "80 permit udp any eq sbfd any eq sbfd-initiator\n"
    "90 permit 51 any any\n"
    "100 permit 50 any any\n"
    "110 permit tcp any any eq ssh www snmp bgp https gnmi\n"
    "120 permit udp any any eq bootps bootpc ntp snmp\n"
    "130 permit tcp any any range 5900 5910\n"
    "140 permit tcp any any range 50000 50100\n"
    "150 permit udp any any range 51000 51100\n"
    "160 permit udp any any eq dhcpv6-client dhcpv6-server\n"
    "170 permit tcp any eq bgp any\n"
    "180 permit tcp any any eq 6040\n"
    "200 permit tcp any any eq 9200\n"
    "245 permit tcp any any eq 6909\n"
    "300 permit tcp any any eq 2018\n"
    "310 permit udp any any eq 6666\n"
    "320 permit tcp any any eq 5921\n"
    "340 permit tcp any any eq 10701\n"
    "350 permit tcp any any eq 1610\n"
    "360 permit tcp any any eq 12112\n"
    "370 permit tcp any any range 5911 5919\n"
    "!\n"
    "ipv6 access-list ebbv6-control-plane-acl\n"
    "counters per-entry\n"
    "10 permit icmpv6 any any\n"
    "20 permit ipv6 any any tracked\n"
    "30 permit udp any any eq bfd hop-limit eq 255\n"
    "40 permit udp any any eq bfd-echo hop-limit eq 254\n"
    "50 permit udp any any eq multihop-bfd\n"
    "60 permit udp any any eq micro-bfd\n"
    "70 permit ospf any any\n"
    "80 permit 51 any any\n"
    "90 permit 50 any any\n"
    "100 permit tcp any any eq ssh snmp bgp https 1610\n"
    "110 permit udp any any eq bootps bootpc ntp snmp\n"
    "120 permit tcp any any eq mlag hop-limit eq 255\n"
    "130 permit udp any any eq mlag hop-limit eq 255\n"
    "140 permit tcp any any range 5900 5910\n"
    "145 permit tcp any any range 5911 5919\n"
    "150 permit tcp any any range 50000 50100\n"
    "160 permit udp any any range 51000 51100\n"
    "170 permit udp any any eq dhcpv6-client dhcpv6-server\n"
    "180 permit tcp any eq bgp any\n"
    "190 permit tcp any any eq nat hop-limit eq 255\n"
    "200 permit udp any any eq nat hop-limit eq 255\n"
    "210 permit rsvp any any\n"
    "220 permit pim any any\n"
    "230 permit udp any any eq 6666\n"
    "240 permit tcp any any eq 2018\n"
    "245 permit tcp any any eq 6909\n"
    "250 permit tcp any any eq 6666\n"
    "260 permit tcp any any eq 60001\n"
    "270 permit tcp any any eq 60002\n"
    "280 permit tcp any any eq 60006\n"
    "290 permit tcp any any eq 60009\n"
    "300 permit tcp any any eq 60100\n"
    "310 permit tcp any any eq 60101\n"
    "330 permit udp any eq lsp-ping any\n"
    "340 permit tcp any any eq 9543\n"
    "!\n"
    "ip access-list ebb-control-plane-acl\n"
    "counters per-entry\n"
    "10 permit icmp any any\n"
    "20 permit ip any any tracked\n"
    "30 permit udp any any eq bfd ttl eq 255\n"
    "40 permit udp any any eq bfd-echo ttl eq 254\n"
    "50 permit udp any any eq multihop-bfd\n"
    "60 permit udp any any eq micro-bfd\n"
    "70 permit ospf any any\n"
    "80 permit tcp any any eq ssh snmp bgp https msdp ldp netconf-ssh gnmi\n"
    "90 permit udp any any eq bootps bootpc ntp snmp rip ldp\n"
    "100 permit tcp any any eq mlag ttl eq 255\n"
    "110 permit udp any any eq mlag ttl eq 255\n"
    "120 permit vrrp any any\n"
    "130 permit ahp any any\n"
    "140 permit pim any any\n"
    "150 permit igmp any any\n"
    "160 permit tcp any any range 5900 5910\n"
    "165 permit tcp any any range 5911 5919\n"
    "170 permit tcp any any range 50000 50100\n"
    "180 permit udp any any range 51000 51100\n"
    "190 permit tcp any any eq 3333\n"
    "200 permit tcp any any eq nat ttl eq 255\n"
    "210 permit tcp any eq bgp any\n"
    "220 permit rsvp any any\n"
    "230 permit tcp any any eq 6666\n"
    "240 permit tcp any any eq 60101\n"
    "245 permit tcp any any eq 6909\n"
    "260 permit udp any eq lsp-ping any\n"
    "!\n"
    "end"
)
