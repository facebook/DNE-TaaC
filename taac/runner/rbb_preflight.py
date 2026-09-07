#!/usr/bin/env python3
# pyre-unsafe

"""Preflight checks for the OSS RBB SRv6 runner.

This module intentionally uses only the Python standard library and TAAC's
OSS-safe topology helpers. It runs inside the TAAC image before the test, so
adopter mistakes are reported without reserving IXIA ports or contacting a DUT.
"""

from __future__ import annotations

import argparse
import csv
import ipaddress
import os
import re
import stat
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

from taac.runner.oss_exceptions import OSSConfigError
from taac.runner.oss_secrets import get_oss_dut_credentials, load_oss_secrets


_MAX_INPUT_BYTES = 1024 * 1024
_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_CREDENTIAL_ENV_NAMES = {
    "_TAAC_OSS_DUT_HOST_CREDENTIALS",
    "TAAC_SSH_USER",
    "TAAC_SSH_PASSWORD",
    "TAAC_IXIA_USERNAME",
    "TAAC_IXIA_PASSWORD",
}
_DEVICE_COLUMNS = 7
_CIRCUIT_COLUMNS = 10
_DOCUMENTATION_V4_NETWORKS = tuple(
    ipaddress.ip_network(prefix)
    for prefix in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24")
)
_DOCUMENTATION_V6_NETWORK = ipaddress.ip_network("2001:db8::/32")


def _regular_file(path: Path, description: str) -> None:
    try:
        file_stat = path.stat()
    except OSError as exc:
        raise OSSConfigError(f"Cannot access {description} '{path}': {exc}") from exc
    if not stat.S_ISREG(file_stat.st_mode):
        raise OSSConfigError(
            f"{description.capitalize()} is not a regular file: {path}"
        )
    if file_stat.st_size > _MAX_INPUT_BYTES:
        raise OSSConfigError(
            f"{description.capitalize()} '{path}' exceeds {_MAX_INPUT_BYTES} bytes"
        )


def _load_env_profile(path: Path) -> Dict[str, str]:
    """Parse the deliberately small KEY=value subset used by docker --env-file."""

    _regular_file(path, "environment profile")
    values: Dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise OSSConfigError(f"Cannot read environment profile '{path}'") from exc

    for line_number, raw_line in enumerate(lines, start=1):
        if "\x00" in raw_line:
            raise OSSConfigError(
                f"Environment profile '{path}' line {line_number} contains a NUL byte"
            )
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise OSSConfigError(
                f"Environment profile '{path}' line {line_number} must be KEY=value"
            )
        name, value = line.split("=", 1)
        name = name.strip()
        if not _ENV_NAME_RE.fullmatch(name):
            raise OSSConfigError(
                f"Environment profile '{path}' line {line_number} has an invalid name"
            )
        if name in values:
            raise OSSConfigError(
                f"Environment profile '{path}' defines '{name}' more than once"
            )
        if name in _CREDENTIAL_ENV_NAMES:
            raise OSSConfigError(
                f"Environment profile '{path}' must not contain credentials; "
                "use secrets.json or a secret-manager environment override"
            )
        values[name] = value
    return values


def _csv_rows(path: Path, expected_columns: int, description: str) -> List[List[str]]:
    _regular_file(path, description)
    rows: List[List[str]] = []
    try:
        with path.open("r", encoding="utf-8", newline="") as csv_stream:
            for line_number, row in enumerate(csv.reader(csv_stream), start=1):
                if not row or not any(value.strip() for value in row):
                    continue
                if row[0].lstrip().startswith("#"):
                    continue
                if len(row) != expected_columns:
                    raise OSSConfigError(
                        f"{description.capitalize()} '{path}' line {line_number} "
                        f"has {len(row)} columns; expected {expected_columns}"
                    )
                rows.append([value.strip() for value in row])
    except (OSError, UnicodeError, csv.Error) as exc:
        raise OSSConfigError(f"Cannot parse {description} '{path}'") from exc
    if not rows:
        raise OSSConfigError(f"{description.capitalize()} '{path}' has no data rows")
    return rows


def _require_values(names: Iterable[str]) -> None:
    missing = sorted(name for name in names if not os.environ.get(name, "").strip())
    if missing:
        raise OSSConfigError("Missing required setting(s): " + ", ".join(missing))


def _validate_dut_credentials(
    hostnames: Iterable[str], setup_option: str = ""
) -> None:
    for hostname in hostnames:
        username, password = get_oss_dut_credentials(hostname)
        missing = []
        if not username or not username.strip():
            missing.append("username")
        if not password:
            missing.append("password")
        if missing:
            raise OSSConfigError(
                f"Missing DUT SSH {', '.join(missing)} for configured DUT "
                f"'{hostname}'"
            )
        if setup_option and username.strip() != "root":
            raise OSSConfigError(
                f"{setup_option} requires dut.username 'root' for every DUT "
                "because it writes system configuration and does not use a "
                f"sudo wrapper; credential for '{hostname}' is not root"
            )


def _is_endpoint_placeholder(value: str) -> bool:
    normalized = value.strip().lower()
    if not normalized or "<" in normalized or ">" in normalized:
        return True
    if normalized in {"changeme", "example", "localhost"} or normalized.endswith(
        (".example", ".example.com", ".example.net", ".example.org")
    ):
        return True
    try:
        address = ipaddress.ip_address(normalized)
    except ValueError:
        return False
    if address.version == 4:
        return any(address in network for network in _DOCUMENTATION_V4_NETWORKS)
    return address in _DOCUMENTATION_V6_NETWORK


def _validate_device_info(path: Path, r1_host: str, r2_host: str) -> None:
    rows = _csv_rows(path, _DEVICE_COLUMNS, "device-info CSV")
    devices: Dict[str, Sequence[str]] = {}
    for row in rows:
        hostname = row[0].lower()
        if hostname == "hostname":
            raise OSSConfigError(
                f"Device-info CSV '{path}' must not contain an uncommented header"
            )
        if not hostname:
            raise OSSConfigError(f"Device-info CSV '{path}' contains an empty hostname")
        if hostname in devices:
            raise OSSConfigError(
                f"Device-info CSV '{path}' contains duplicate hostname '{row[0]}'"
            )
        devices[hostname] = row

    for hostname in (r1_host, r2_host):
        row = devices.get(hostname.lower())
        if row is None:
            raise OSSConfigError(
                f"Device-info CSV '{path}' has no row for configured DUT '{hostname}'"
            )
        if row[5].upper() != "FBOSS":
            raise OSSConfigError(
                f"Device-info CSV '{path}' must identify DUT '{hostname}' as FBOSS"
            )


def _validate_circuit_shape(path: Path) -> None:
    rows = _csv_rows(path, _CIRCUIT_COLUMNS, "circuit-info CSV")
    for row in rows:
        if row[0].lower() == "hostname":
            raise OSSConfigError(
                f"Circuit-info CSV '{path}' must not contain an uncommented header"
            )
        if not row[0] or not row[1] or not row[4] or not row[5]:
            raise OSSConfigError(
                f"Circuit-info CSV '{path}' contains a row without both endpoints"
            )


def _validate_traffic_contract() -> None:
    try:
        advertised_start = ipaddress.ip_address(
            os.environ["TAAC_RBB_IXIA_TAIL_PREFIX"]
        )
        advertised = ipaddress.ip_network(
            f"{advertised_start}/"
            f"{os.environ['TAAC_RBB_IXIA_TAIL_PREFIX_LEN']}",
            strict=False,
        )
        steered = ipaddress.ip_network(
            os.environ["TAAC_RBB_TAIL_PREFIX"], strict=True
        )
        count = int(os.environ["TAAC_RBB_IXIA_TAIL_PREFIX_COUNT"])
    except (KeyError, ValueError) as exc:
        raise OSSConfigError("The IXIA tail-prefix contract is not valid") from exc
    if advertised.version != 6 or steered.version != 6:
        raise OSSConfigError("The IXIA tail-prefix contract must use IPv6")
    if advertised_start != advertised.network_address:
        raise OSSConfigError(
            "TAAC_RBB_IXIA_TAIL_PREFIX must be the network address for "
            "TAAC_RBB_IXIA_TAIL_PREFIX_LEN"
        )
    if advertised != steered or count != 1:
        raise OSSConfigError(
            "TAAC_RBB_TAIL_PREFIX must equal the single prefix advertised by IXIA"
        )


def run_preflight(
    config_dir: Path,
    *,
    with_traffic: bool,
    setup_duts: bool = False,
    setup_dut_edges: bool = False,
) -> Tuple[str, str]:
    """Validate local inputs and return the configured DUT names."""

    config_dir = config_dir.expanduser().resolve()
    if not config_dir.is_dir():
        raise OSSConfigError(f"Configuration directory does not exist: {config_dir}")

    profile_path = config_dir / "rbb.env"
    secrets_path = config_dir / "secrets.json"
    device_path = config_dir / "device_info.csv"
    circuit_path = config_dir / "circuit_info.csv"

    profile = _load_env_profile(profile_path)
    for name, value in profile.items():
        # Matches docker/run_taac_docker.sh: an explicitly exported host value
        # has precedence over the non-secret profile.
        os.environ.setdefault(name, value)

    load_oss_secrets(str(secrets_path))
    required = {
        "TAAC_RBB_R1_HOST",
        "TAAC_RBB_R2_HOST",
    }
    if with_traffic:
        required.update(
            {
                "TAAC_RBB_IXIA_CHASSIS",
                "TAAC_IXIA_API_SERVER",
                "TAAC_IXIA_USERNAME",
                "TAAC_IXIA_PASSWORD",
                "TAAC_RBB_IXIA_TAIL_PREFIX",
                "TAAC_RBB_IXIA_TAIL_PREFIX_LEN",
                "TAAC_RBB_IXIA_TAIL_PREFIX_COUNT",
                "TAAC_RBB_TAIL_PREFIX",
            }
        )
    _require_values(required)
    if setup_dut_edges and not with_traffic:
        raise OSSConfigError("--setup-dut-edges requires --with-traffic")
    if setup_duts and with_traffic and not setup_dut_edges:
        raise OSSConfigError(
            "fresh-image traffic requires --setup-dut-edges"
        )
    r1_host = os.environ["TAAC_RBB_R1_HOST"].strip()
    r2_host = os.environ["TAAC_RBB_R2_HOST"].strip()
    if r1_host.lower() == r2_host.lower():
        raise OSSConfigError("TAAC_RBB_R1_HOST and TAAC_RBB_R2_HOST must differ")
    for name, value in (
        ("TAAC_RBB_R1_HOST", r1_host),
        ("TAAC_RBB_R2_HOST", r2_host),
    ):
        if _is_endpoint_placeholder(value):
            raise OSSConfigError(f"Replace the placeholder value for {name}")

    setup_option = ""
    if setup_duts or setup_dut_edges:
        setup_option = "--setup-duts" if setup_duts else "--setup-dut-edges"
    _validate_dut_credentials((r1_host, r2_host), setup_option)

    if with_traffic:
        for name in ("TAAC_RBB_IXIA_CHASSIS", "TAAC_IXIA_API_SERVER"):
            if _is_endpoint_placeholder(os.environ[name]):
                raise OSSConfigError(f"Replace the placeholder value for {name}")
        _validate_traffic_contract()

    _validate_device_info(device_path, r1_host, r2_host)
    _validate_circuit_shape(circuit_path)

    # Reuse the qualification's topology builder so --check and the live run
    # enforce one wiring contract. Import only after applying the profile,
    # because the RBB constants intentionally resolve environment overrides at
    # module import time.
    try:
        from taac.testconfigs.routing.util.bgp_rbb_topology import load_rbb_topology

        topology = load_rbb_topology(
            r1_host=r1_host,
            r2_host=r2_host,
            circuit_info_path=str(circuit_path),
            ixia_chassis=os.environ.get("TAAC_RBB_IXIA_CHASSIS", ""),
            allow_placeholder=False,
            require_ixia=with_traffic,
        )
        if setup_duts or setup_dut_edges:
            from taac.testconfigs.routing.util import bgp_rbb_constants as C
            from taac.testconfigs.routing.util.bgp_rbb_bootstrap_config import (
                validate_bootstrap_device_paths,
                validate_bootstrap_topology,
            )

            config_paths = [C.AGENT_CONFIG_PATH, C.BGP_CONFIG_PATH]
            if setup_duts:
                config_paths.extend(
                    (
                        C.OPENR_CONFIG_PATH,
                        C.BGP_POLICY_PATH,
                        C.BOOTSTRAP_STATE_PATH,
                    )
                )
            validate_bootstrap_device_paths(config_paths)
        if setup_duts:
            validate_bootstrap_topology(topology)
    except ValueError as exc:
        raise OSSConfigError(str(exc)) from exc

    return r1_host, r2_host


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate an OSS RBB SRv6 lab profile")
    parser.add_argument("--config-dir", required=True)
    parser.add_argument("--with-traffic", action="store_true")
    parser.add_argument("--setup-duts", action="store_true")
    parser.add_argument("--setup-dut-edges", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _argument_parser().parse_args(argv)
    try:
        r1_host, r2_host = run_preflight(
            Path(args.config_dir),
            with_traffic=args.with_traffic,
            setup_duts=args.setup_duts,
            setup_dut_edges=args.setup_dut_edges,
        )
    except OSSConfigError as exc:
        print(f"Configuration check failed: {exc}", file=sys.stderr)
        return 1

    mode = "live IXIA traffic" if args.with_traffic else "device path (no IXIA)"
    if args.setup_duts:
        mode += ", temporary DUT bootstrap"
    if args.setup_dut_edges:
        mode += ", temporary DUT-edge setup"
    print(f"Configuration check passed: {Path(args.config_dir).resolve()}")
    print(f"Mode: {mode}")
    print(f"DUTs: {r1_host}, {r2_host}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
