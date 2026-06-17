# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""
OSS IXIA utilities for credential management and IXIA chassis configuration.

In OSS mode, IXIA credentials are loaded from:
  CSV file: oss_topology_info/ixia_credentials.csv

This module has zero Meta-internal dependencies.
"""

import csv
import os
import typing as t


DEFAULT_IXIA_CREDS_PATH = os.path.join(
    os.path.dirname(__file__), "../oss_topology_info/ixia_credentials.csv"
)

IXIA_CREDS_PATH_ENV = "TAAC_IXIA_CREDENTIALS_PATH"


def get_oss_ixia_password(
    chassis_ip: t.Optional[str] = None,
) -> t.Tuple[str, str]:
    """
    Get IXIA chassis credentials for OSS mode.

    Looks up credentials from ixia_credentials.csv.
    If chassis_ip is provided, matches that specific chassis.
    Otherwise returns the first entry.

    Args:
        chassis_ip: Optional IXIA chassis IP to look up in CSV.

    Returns:
        Tuple of (username, password).

    Raises:
        ValueError: If no credentials are configured.
    """
    creds_path = os.environ.get(IXIA_CREDS_PATH_ENV, DEFAULT_IXIA_CREDS_PATH)
    if os.path.exists(creds_path):
        with open(creds_path, "r") as f:
            reader = csv.reader(f)
            for row in reader:
                if not row or row[0].startswith("#"):
                    continue
                if len(row) >= 3:
                    if chassis_ip and row[0].strip() == chassis_ip:
                        return row[1].strip(), row[2].strip()
                    elif not chassis_ip:
                        return row[1].strip(), row[2].strip()

    raise ValueError(
        "IXIA credentials not configured. "
        "Populate ixia_credentials.csv with: chassis_ip,username,password"
    )
