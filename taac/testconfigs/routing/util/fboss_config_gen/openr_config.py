# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""Build ``/opt/openr/openr.conf`` from scratch.

OpenR provides the IGP that resolves the iBGP loopback next-hops across the SRv6
core. The config is platform-generic except for ``node_name`` (the DUT role) --
domain ``fboss``, a single area 0 that adjacencies over ``^fboss[0-9]+$`` core
interfaces and redistributes ``^lo$`` / ``^fboss4000$`` (the loopback RIF), and
``fib_port`` 5909 (the split-agent thrift port). Shape mirrors the reference.
"""

from __future__ import annotations

import typing as t


def build_openr_config(
    *,
    node_name: str,
    domain: str = "fboss",
    area_id: str = "0",
    include_interface_regexes: t.Optional[t.Sequence[str]] = None,
    redistribute_interface_regexes: t.Optional[t.Sequence[str]] = None,
    openr_ctrl_port: int = 2018,
    fib_port: int = 5909,
    enable_v4: bool = True,
) -> t.Dict[str, t.Any]:
    """Build the openr.conf dict for one DUT (``node_name`` = its role)."""
    include = list(include_interface_regexes or ["^fboss[0-9]+$"])
    redistribute = list(redistribute_interface_regexes or ["^lo$", "^fboss4000$"])
    return {
        "node_name": node_name,
        "domain": domain,
        "areas": [
            {
                "area_id": area_id,
                "neighbor_regexes": [".*"],
                "include_interface_regexes": include,
                "exclude_interface_regexes": [],
                "redistribute_interface_regexes": redistribute,
            }
        ],
        "listen_addr": "::",
        "openr_ctrl_port": openr_ctrl_port,
        "enable_v4": enable_v4,
        "v4_over_v6_nexthop": True,
        "enable_netlink_fib_handler": False,
        "fib_port": fib_port,
        "thrift_server": {
            "openr_ctrl_port": openr_ctrl_port,
            "enable_secure_thrift_server": False,
            "workers": 4,
        },
        "kvstore_config": {"key_ttl_ms": 300000, "ttl_decrement_ms": 1},
        "link_monitor_config": {
            "linkflap_initial_backoff_ms": 1000,
            "linkflap_max_backoff_ms": 60000,
            "use_rtt_metric": False,
        },
        "spark_config": {
            "neighbor_discovery_port": 6666,
            "hello_time_s": 20,
            "fastinit_hello_time_ms": 500,
            "keepalive_time_s": 3,
            "hold_time_s": 30,
            "graceful_restart_time_s": 30,
        },
        "enable_watchdog": True,
        "watchdog_config": {
            "interval_s": 20,
            "thread_timeout_s": 300,
            "max_memory_mb": 512,
        },
        "prefix_forwarding_type": 0,
        "prefix_forwarding_algorithm": 0,
        "assume_drained": False,
    }
