# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""Single source of truth: RTP test host -> GPU device_id -> originated prefix.

Every FPF config that needs a production HRT prefix (test configs, the
standalone health-check driver, etc.) should look it up here instead of
hardcoding a prefix string inline. If the lab wiring / addressing changes, you
only edit THIS file and every consumer picks it up.

Model
-----
Each RTP test host (BE Node) has four GPU devices: 0, 1, 2, 3. Each device
originates one production /64 prefix (its VF1 prefix, reachable on planes 0-3).
The mapping is therefore:

    host -> {device_id: prefix}

Default device is 0 (``DEFAULT_DEVICE_ID``).

Usage
-----
    from taac.libs.fpf.fpf_prod_prefix_map import (
        get_prefix,
        DEFAULT_DEVICE_ID,
    )

    # In a test config:
    LOCAL_HOST = "rtptest1544.mwg2"
    REMOTE_HOST = "rtptest1575.mwg2"
    PROD_PREFIXES = [
        get_prefix(LOCAL_HOST),                 # device 0 by default
        get_prefix(REMOTE_HOST),
    ]

Maintenance
-----------
Fill in HOST_DEVICE_PREFIX with the full host -> device -> prefix mapping. The
two entries below are the values confirmed during MWG2 FPF testing; replace /
extend with the authoritative lab list (devices 0-3 for every host). Missing
lookups raise a clear KeyError rather than silently returning a wrong value.
"""

import typing as t

# Default GPU device when a caller does not specify one.
DEFAULT_DEVICE_ID: int = 0

# Number of GPU devices per RTP test host (BE Node).
DEVICES_PER_HOST: int = 4

# ── Source of truth ────────────────────────────────────────────────────────
# host -> {device_id (0-3) -> originated /64 prefix}.
#
# The block between the GENERATED markers below is produced by
# scripts/pavanpatil/fpf_gen_prefix_map.py, which SSHes to each host, reads the
# device's bveth interface IPv6 address (ip -6 addr show), and computes the /64
# network. Regenerate with:
#   buck2 run fbcode//scripts/pavanpatil:fpf_gen_prefix_map -- \
#       --hosts rtptest1544.mwg2 rtptest1575.mwg2 --devices 0 1 2 3 --write
# Hand-edits inside the markers are overwritten on the next regen.
# === GENERATED:BEGIN host-device-prefix (regen: fpf_gen_prefix_map.py) ===
HOST_DEVICE_PREFIX: t.Dict[str, t.Dict[int, str]] = {
    "rtptest1544.mwg2": {
        0: "2401:db00:292a:a27c::/64",
    },
    "rtptest1555.mwg2": {
        0: "2401:db00:292a:a284::/64",
    },
    "rtptest1575.mwg2": {
        0: "2401:db00:292a:a16c::/64",
    },
    "rtptest1599.mwg2": {
        0: "2401:db00:292a:a124::/64",
    },
}
# === GENERATED:END host-device-prefix ===


def known_hosts() -> t.List[str]:
    """All RTP test hosts present in the map."""
    return sorted(HOST_DEVICE_PREFIX)


def get_host_prefixes(host: str) -> t.Dict[int, str]:
    """Return the {device_id: prefix} mapping for a host (raises if unknown)."""
    try:
        return HOST_DEVICE_PREFIX[host]
    except KeyError:
        raise KeyError(
            f"No prod-prefix mapping for host {host!r}. Known hosts: "
            f"{known_hosts()}. Add it to HOST_DEVICE_PREFIX in "
            f"libs/fpf/fpf_prod_prefix_map.py."
        )


def get_prefix(host: str, device_id: int = DEFAULT_DEVICE_ID) -> str:
    """Return the prefix originated by ``host`` GPU ``device_id``.

    Raises a clear KeyError if the host or device is not in the map, so missing
    constants fail loudly instead of silently using a wrong prefix.
    """
    devices = get_host_prefixes(host)
    try:
        return devices[device_id]
    except KeyError:
        raise KeyError(
            f"No prod-prefix mapping for host {host!r} device {device_id}. "
            f"Known devices for this host: {sorted(devices)}. Add it to "
            f"HOST_DEVICE_PREFIX in libs/fpf/fpf_prod_prefix_map.py."
        )


def get_all_prefixes(host: str) -> t.List[str]:
    """All prefixes for a host, ordered by device_id."""
    devices = get_host_prefixes(host)
    return [devices[d] for d in sorted(devices)]
