#!/usr/bin/env fbpython
# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

"""Exercise the complete inherited public FbossSwitchInternal API on one DUT.

The script intentionally treats every invocation as an independent experiment:
an exception or timeout is recorded and the sweep continues.  Driver SSH calls
are forced through lab-ssh by setting TAAC_SSH_VIA_LAB_SSH before the driver is
created.  Mutating probes use unique names and best-effort recovery.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import csv
import inspect
import io
import json
import logging
import os
import shlex
import time
import traceback
import uuid
from collections.abc import AsyncIterator, Awaitable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from configerator.structs.neteng.fboss.features.types import (
    ConfigPatcher,
    PythonPatcher,
)
from coop_thrift.coop.types import CoopConfigPatcher
from neteng.fboss.lib.hostname_utils import get_role_from_hostname
from neteng.models.network_topology.types import Role
from taac.driver.driver_constants import (
    AGENT_CONFIG_PATCHER_NAME,
    BGP_CONFIG_PATCHER_NAME,
    DNE_TEST_REGRESSION_NAME,
    FbossSystemctlServiceName,
    InterfaceFlapMethod,
    SystemAvailability,
    SystemctlServiceStatus,
    SystemRebootMethod,
)
from taac.internal.driver.fboss_switch_internal import (
    FbossSwitchInternal,
)
from taac.utils.driver_factory import async_get_device_driver
from taac.test_as_a_config import types as taac_types


DEFAULT_PEER_GROUP: str = "PEERGROUP_SSW_FSW_V6"
DEFAULT_TIMEOUT_SECONDS: float = 45.0
AUTO_PROBE_TIMEOUT_SECONDS: float = 20.0
REBOOT_TIMEOUT_SECONDS: float = 1_200.0
SERVICE_CONFIGS: tuple[str, ...] = ("agent", "bgpcpp", "openr", "qsfp")


class UncallableProbe(RuntimeError):
    """A public method exists but its device-specific inputs cannot be derived."""


class RecoveryFailed(RuntimeError):
    """A probe's paired recovery failed, optionally after a primary failure."""

    def __init__(
        self,
        description: str,
        primary_error: BaseException | None,
        cleanup_error: Exception,
    ) -> None:
        self.primary_error = primary_error
        self.cleanup_error = cleanup_error
        primary = (
            f"; primary={type(primary_error).__name__}: {primary_error}"
            if primary_error is not None
            else ""
        )
        super().__init__(
            f"{description}: {type(cleanup_error).__name__}: {cleanup_error}{primary}"
        )


@dataclass(frozen=True)
class ProbeSpec:
    method_name: str
    service_type: str
    handler: str = "default"
    args: tuple[Any, ...] = ()
    kwargs: Mapping[str, Any] = field(default_factory=dict)
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS


@dataclass
class ProbeResult:
    device: str
    service_type: str
    method_name: str
    case_name: str
    response: str
    raw_start_line: int
    raw_end_line: int
    works_as_expected: str
    status: str
    duration_seconds: float
    error: str = ""


@dataclass
class RunContext:
    device: str
    interface: str
    peer_group: str
    run_id: str
    output_dir: Path

    def patcher_name(self, suffix: str) -> str:
        return f"taac_driver_tester_{self.run_id}_{suffix}"

    @property
    def remote_dir(self) -> str:
        return f"/tmp/taac_driver_tester_{self.run_id}"


class RawArtifact:
    """Append-only record writer that returns exact one-based line ranges."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            with self.path.open(encoding="utf-8") as source:
                self._line_count = sum(1 for _ in source)
        else:
            self.path.touch()
            self._line_count = 0

    def append(self, method_name: str, record: Mapping[str, Any]) -> tuple[int, int]:
        lines = [
            f"===== BEGIN {method_name} =====",
            *json.dumps(serialize(record), indent=2, sort_keys=True).splitlines(),
            f"===== END {method_name} =====",
        ]
        start = self._line_count + 1
        with self.path.open("a", encoding="utf-8") as sink:
            sink.write("\n".join(lines))
            sink.write("\n")
        self._line_count += len(lines)
        return start, self._line_count


class InvocationLogHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []
        self.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(self.format(record))


def serialize(value: Any) -> Any:
    """Convert Thrift/Python results to deterministic JSON-compatible values."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, Mapping):
        return {
            str(key): serialize(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (set, frozenset)):
        return [serialize(item) for item in sorted(value, key=repr)]
    if isinstance(value, (list, tuple)):
        return [serialize(item) for item in value]
    if hasattr(value, "to_python"):
        try:
            return serialize(value.to_python())
        except Exception:
            pass
    if hasattr(value, "_asdict"):
        return serialize(value._asdict())
    if hasattr(value, "__dict__"):
        return {
            key: serialize(item)
            for key, item in vars(value).items()
            if not key.startswith("_")
        }
    return repr(value)


def public_driver_api() -> set[str]:
    """Return callable methods and properties across the complete driver MRO."""
    return {
        name
        for name, value in inspect.getmembers_static(FbossSwitchInternal)
        if not name.startswith("_") and (callable(value) or isinstance(value, property))
    }


# Ordered so read paths run before mutation and reboot paths run last.
CURATED_PROBES: tuple[ProbeSpec, ...] = (
    ProbeSpec(
        "async_get_systemctl_service_name",
        "ssh",
        args=(FbossSystemctlServiceName.AGENT,),
    ),
    ProbeSpec("async_get_qsfp_client", "qsfp", handler="qsfp_client"),
    ProbeSpec("get_async_get_sr_client", "coop", handler="coop_client"),
    ProbeSpec("bgp", "bgp", handler="bgp_client"),
    ProbeSpec("get_sw_agent_client", "agent", handler="sw_agent_client"),
    ProbeSpec("get_hw_agent_client", "agent", handler="hw_agent_client"),
    ProbeSpec("async_agent_client", "agent", handler="agent_property"),
    # Reloading the current Agent config does not introduce persistent test
    # state, so it can be exercised directly without a paired recovery action.
    ProbeSpec(
        "async_agent_config_reload",
        "agent",
        timeout_seconds=180,
    ),
    ProbeSpec("async_get_fsdb_client", "fsdb", handler="fsdb_client"),
    ProbeSpec("get_async_local_drainer_client", "drainer", handler="drainer_client"),
    ProbeSpec("async_coop_list_patchers", "coop"),
    ProbeSpec("async_is_coop_patcher_registered", "coop", handler="is_missing_patcher"),
    ProbeSpec(
        "async_is_agent_patcher_registered", "coop", handler="is_missing_agent_patcher"
    ),
    ProbeSpec(
        "async_get_agent_config_attribute", "agent", handler="agent_config_attribute"
    ),
    ProbeSpec("get_specific_interface_info", "agent", handler="interface"),
    ProbeSpec("async_get_ip_route", "agent", args=("2001:4860:4860::8888", False)),
    ProbeSpec("async_get_netwhoami", "inventory"),
    ProbeSpec("async_get_lldp_neighbors_based_on_role", "agent", handler="lldp_role"),
    ProbeSpec("async_get_neighbor_names_based_on_role", "agent", handler="lldp_role"),
    ProbeSpec(
        "async_run_cmd_on_shell",
        "ssh",
        args=("printf taac-driver-compatibility-ok",),
        kwargs={"timeout": 30},
    ),
    ProbeSpec(
        "async_execute_show_or_configure_cmd_on_shell",
        "ssh",
        args=("printf taac-driver-command-ok",),
        kwargs={"timeout": 30},
    ),
    ProbeSpec("is_mnpu", "coop", handler="sync_method"),
    ProbeSpec("async_is_mnpu", "coop"),
    ProbeSpec(
        "async_read_log_file",
        "ssh",
        args=("/var/facebook/logs/fboss/wedge_agent.log",),
    ),
    ProbeSpec(
        "async_get_log_source_command",
        "ssh",
        args=("/var/facebook/logs/fboss/wedge_agent.log",),
    ),
    ProbeSpec("async_check_current_is_dirty_flag", "ssh"),
    ProbeSpec("async_get_fboss_build_info_show", "ssh"),
    ProbeSpec("async_get_fboss_os_type", "ssh"),
    ProbeSpec("async_is_netos", "ssh"),
    ProbeSpec("async_check_if_file_exists", "ssh", args=("/etc/os-release",)),
    ProbeSpec(
        "wait_for_ssh_reachable", "ssh", kwargs={"max_duration": 60, "sleep_time": 2}
    ),
    ProbeSpec("async_get_optical_power", "qsfp", handler="interface_list"),
    ProbeSpec("async_create_dir_if_not_exists", "ssh", handler="create_remote_dir"),
    ProbeSpec("async_write_file_on_device", "ssh", handler="write_remote_file"),
    ProbeSpec("async_copy_file_to_device", "ssh", handler="copy_remote_file"),
    ProbeSpec(
        "async_register_python_patcher", "coop", handler="register_python_patcher"
    ),
    ProbeSpec("async_coop_register_patchers", "coop", handler="register_typed_patcher"),
    ProbeSpec(
        "async_coop_unregister_patchers", "coop", handler="unregister_missing_patcher"
    ),
    ProbeSpec(
        "async_unregister_python_patcher", "coop", handler="unregister_python_patcher"
    ),
    ProbeSpec(
        "async_register_patcher_to_shut_ports_persistently",
        "coop",
        handler="persistent_port_shutdown",
    ),
    ProbeSpec(
        "async_unregister_patcher_to_shut_ports_persistently",
        "coop",
        handler="persistent_port_unshutdown",
    ),
    ProbeSpec("async_isolate_test_bed_connectivity", "coop", handler="isolate_restore"),
    ProbeSpec(
        "async_restore_test_bed_connectivity", "coop", handler="restore_after_isolate"
    ),
    ProbeSpec("async_add_static_route_patcher", "coop", handler="static_route_patcher"),
    ProbeSpec(
        "async_apply_patchers",
        "coop",
        args=(taac_types.ApplyPatcherMethod.AGENT_RELOAD,),
        timeout_seconds=60,
    ),
    ProbeSpec(
        "async_modify_minlink", "coop", handler="modify_minlink", timeout_seconds=60
    ),
    ProbeSpec(
        "async_change_speed_patcher",
        "coop",
        handler="change_speed",
        timeout_seconds=60,
    ),
    ProbeSpec(
        "async_change_mtu_patcher", "coop", handler="change_mtu", timeout_seconds=60
    ),
    ProbeSpec(
        "async_set_port_channel_min_link_capacity_patcher",
        "coop",
        handler="set_minlink",
        timeout_seconds=60,
    ),
    ProbeSpec(
        "async_create_bgp_peer_group_patcher",
        "bgp",
        handler="bgp_peer_group_patcher",
        timeout_seconds=60,
    ),
    ProbeSpec(
        "async_set_all_port_channel_min_link_capacity_patcher",
        "coop",
        handler="set_all_minlink",
        timeout_seconds=60,
    ),
    ProbeSpec("async_coop_generate_configs", "coop", args=(False,), timeout_seconds=60),
    ProbeSpec(
        "remediate_coop_failure",
        "coop",
        args=(RuntimeError("compatibility probe no-op remediation input"),),
    ),
    ProbeSpec(
        "async_setup_agg_port", "coop", handler="setup_agg_port", timeout_seconds=60
    ),
    ProbeSpec(
        "async_remove_agg_port", "coop", handler="remove_agg_port", timeout_seconds=60
    ),
    ProbeSpec("async_is_device_drained", "drainer"),
    ProbeSpec(
        "async_local_drainer_drain",
        "drainer",
        handler="local_drain_cycle",
        timeout_seconds=60,
    ),
    ProbeSpec(
        "async_onbox_drain_device",
        "drainer",
        handler="onbox_drain_cycle",
        timeout_seconds=60,
    ),
    ProbeSpec(
        "async_onbox_softdrain_device",
        "drainer",
        handler="onbox_softdrain_cycle",
        timeout_seconds=60,
    ),
    ProbeSpec(
        "async_onbox_undrain_device",
        "drainer",
        handler="onbox_undrain",
        timeout_seconds=60,
    ),
    ProbeSpec(
        "async_restart_service", "system", handler="restart_bgp", timeout_seconds=180
    ),
    ProbeSpec(
        "async_crash_service", "system", handler="crash_bgp", timeout_seconds=180
    ),
    ProbeSpec(
        "async_coop_reset", "coop", handler="coop_reset_restore", timeout_seconds=180
    ),
    ProbeSpec(
        "async_full_system_reboot",
        "system",
        handler="full_reboot",
        timeout_seconds=REBOOT_TIMEOUT_SECONDS,
    ),
    ProbeSpec(
        "async_reboot_switch",
        "system",
        handler="reboot_switch",
        timeout_seconds=REBOOT_TIMEOUT_SECONDS,
    ),
)


def _service_type(method_name: str) -> str:
    lowered = method_name.lower()
    for keyword, service in (
        ("qsfp", "qsfp"),
        ("transceiver", "qsfp"),
        ("bgp", "bgp"),
        ("openr", "openr"),
        ("fsdb", "fsdb"),
        ("coop", "coop"),
        ("patcher", "coop"),
        ("drain", "drainer"),
        ("route", "routing"),
        ("fib", "routing"),
        ("port", "agent"),
        ("interface", "agent"),
        ("agent", "agent"),
        ("service", "system"),
        ("system", "system"),
        ("file", "ssh"),
        ("disk", "ssh"),
        ("process", "ssh"),
        ("ssh", "ssh"),
    ):
        if keyword in lowered:
            return service
    return "driver"


def _is_observational(method_name: str) -> bool:
    return method_name.startswith(
        (
            "async_get_",
            "async_is_",
            "async_check_",
            "async_validate_",
            "async_wait_",
            "get_",
            "is_",
            "check_",
            "count_",
            "calculate_",
            "classify_",
            "extract_",
            "verify_",
            "validate_",
            "ip_ntop",
        )
    )


def build_probe_matrix() -> tuple[ProbeSpec, ...]:
    """Combine deliberate probes with generated coverage for inherited methods."""
    curated_names = {spec.method_name for spec in CURATED_PROBES}
    generated = [
        ProbeSpec(
            method_name=name,
            service_type=_service_type(name),
            handler="auto",
            timeout_seconds=AUTO_PROBE_TIMEOUT_SECONDS,
        )
        for name in sorted(public_driver_api() - curated_names)
    ]
    observational = [spec for spec in generated if _is_observational(spec.method_name)]
    mutating = [spec for spec in generated if not _is_observational(spec.method_name)]
    return (*observational, *mutating, *CURATED_PROBES)


def validate_probe_coverage(specs: Sequence[ProbeSpec] | None = None) -> None:
    specs = tuple(specs or build_probe_matrix())
    expected = public_driver_api()
    actual = {spec.method_name for spec in specs}
    duplicates = sorted(
        name for name in actual if sum(spec.method_name == name for spec in specs) > 1
    )
    if duplicates or expected != actual:
        raise RuntimeError(
            "Probe matrix does not exactly cover inherited FbossSwitchInternal API: "
            f"missing={sorted(expected - actual)}, extra={sorted(actual - expected)}, "
            f"duplicates={duplicates}"
        )


async def _call(method: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    if inspect.iscoroutinefunction(method):
        return await method(*args, **kwargs)
    result = await asyncio.to_thread(method, *args, **kwargs)
    return await result if inspect.isawaitable(result) else result


@contextlib.asynccontextmanager
async def _recover_without_masking(
    cleanup: Callable[[], Awaitable[Any]], description: str
) -> AsyncIterator[None]:
    """Run cleanup while preserving a primary probe failure or cancellation."""
    primary_error: BaseException | None = None
    try:
        yield
    except BaseException as error:
        primary_error = error
        raise
    finally:
        try:
            await cleanup()
        except Exception as cleanup_error:
            logging.getLogger(__name__).exception(
                "%s failed: %s", description, cleanup_error
            )
            if primary_error is not None and not isinstance(primary_error, Exception):
                raise primary_error
            recovery_failure = RecoveryFailed(description, primary_error, cleanup_error)
            if isinstance(primary_error, Exception):
                raise recovery_failure from primary_error
            raise recovery_failure from cleanup_error


async def _auto_value(  # noqa: C901
    driver: Any,
    context: RunContext,
    method_name: str,
    parameter: inspect.Parameter,
) -> Any:
    """Best-effort live-device value for a required reflected parameter."""
    name = parameter.name
    if name in {"args", "kwds"}:
        return ()
    if name == "kwargs":
        return {}
    if name in {"interface", "interface_name", "intf_name"}:
        return context.interface
    if name in {
        "interface_names",
        "intf_names",
        "interfaces",
        "desired_interfaces",
        "egress_interfaces",
        "ingress_interfaces",
        "port_names",
    }:
        return (context.interface,)
    if name == "disabled_interfaces":
        return ()
    if name == "enabled_interfaces":
        return (context.interface,)
    if name in {"hostname", "device", "device_name", "node"}:
        return context.device
    if name == "nodes":
        return (context.device,)
    if name in {"service", "services"}:
        service = FbossSystemctlServiceName.BGP
        return (service,) if name == "services" else service
    if name == "agent_name":
        return "bgpd"
    if name in {"file_location", "file_path", "remote_path"}:
        return f"{context.remote_dir}/driver_tester.txt"
    if name in {"local_path"}:
        local = context.output_dir / "driver-tester-source.txt"
        local.write_text("taac-driver-tester\n", encoding="utf-8")
        return str(local)
    if name in {"content", "contents"}:
        return "taac-driver-tester"
    if name in {"log_file_path", "path"}:
        return "/var/facebook/logs/fboss/wedge_agent.log"
    if name in {"prefix", "prefix_str", "route", "monitored_prefix_supernet"}:
        return "2001:db8:ffff::/64"
    if name == "network":
        return "2001:db8::/32"
    if name == "ip":
        return "2001:4860:4860::8888"
    if name in {"patcher_name", "subscriber_id"}:
        return context.patcher_name(method_name)
    if name == "config_name":
        return AGENT_CONFIG_PATCHER_NAME
    if name in {"py_func_name"}:
        return "configure_bgp_peer_group"
    if name in {"patcher_args"}:
        return {"name": context.peer_group, "attributes_to_update_json": "{}"}
    if name in {"prefix_to_next_hops_map", "data", "keys_list"}:
        return {}
    if name == "coop_config_patcher":
        return _noop_bgp_patcher(context.patcher_name("auto_typed"), context.peer_group)
    if name in {"peer_group", "name"}:
        return context.peer_group
    if name in {"attr"}:
        return await _first_scalar_config_path(driver)
    if name in {"agg_intf_name", "aggregated_interface_name", "port_channel_name"}:
        return await _first_port_channel(driver)
    if name == "port_channel_id":
        return "65535"
    if name == "port_id":
        info = await driver.get_specific_interface_info(context.interface)
        return int(getattr(info, "portId", getattr(info, "port_id", 0)))
    if name == "vlan_id":
        info = await driver.async_get_interface_name_to_port_id_and_vlan_id(
            context.interface
        )
        return int(getattr(info, "vlan_id", getattr(info, "vlanId", 0)))
    if name in {"state", "desired_interface_state", "is_enable_port", "enable"}:
        return True
    if name == "desired_status":
        return SystemctlServiceStatus.ACTIVE
    if name == "expected_state":
        return SystemAvailability.REACHABLE
    if name == "flap_method":
        return InterfaceFlapMethod.THRIFT_PORT_STATE_CHANGE
    if name == "reboot_method":
        return SystemRebootMethod.FULL_SYSTEM_REBOOT
    if name == "apply_patcher_method":
        return taac_types.ApplyPatcherMethod.AGENT_RELOAD
    if name == "rule":
        operation = "-D" if "remove" in method_name else "-I"
        return f"{operation} INPUT -p udp --dport 65534 -j ACCEPT"
    if name == "core_file_name" or name == "core_dump_file":
        return "/tmp/taac_driver_tester_missing.core"
    if name == "allow_listed_files":
        return ()
    if name in {"process", "process_id"}:
        return "wedge_agent" if name == "process" else "1"
    if name == "filesystem":
        return "/"
    if name == "counter":
        return "ActiveState"
    if name in {"afi", "address_family"}:
        return "ipv6"
    if name == "direction":
        return "decrease"
    if name == "transceiver_ids":
        return ()
    if name == "n_workers":
        return "1"
    if name == "bytes_per_worker":
        return "1M"
    if name == "file_size":
        return 1
    if name in {"asn", "value"}:
        return 0
    if name in {
        "expected_fib_count",
        "expected_rx_prefix_loss",
        "task_id",
        "group_id",
        "client_id",
        "metric_increment",
        "threshold_value",
        "total_flaps",
        "interval_to_link_up",
    }:
        return 0 if name != "total_flaps" else 1
    annotation = str(parameter.annotation).lower()
    if "bool" in annotation:
        return False
    if "int" in annotation:
        return 0
    if "float" in annotation:
        return 0.0
    if any(
        container in annotation for container in ("list", "tuple", "sequence", "set")
    ):
        return ()
    if any(container in annotation for container in ("dict", "mapping")):
        return {}
    if "str" in annotation:
        return "driver_tester"
    return None


def _auto_recovery_spec(
    context: RunContext, method_name: str
) -> tuple[str, tuple[Any, ...]] | None:
    """Return the paired recovery for an auto-generated mutating probe."""
    recovery: dict[str, tuple[str, tuple[Any, ...]]] = {
        "async_add_iptables_rule": (
            "async_remove_iptables_rule",
            ("-D INPUT -p udp --dport 65534 -j ACCEPT",),
        ),
        "async_create_cold_boot_file": (
            "async_run_cmd_on_shell",
            ("rm -f /dev/shm/fboss/warm_boot/cold_boot_once_0",),
        ),
        "async_disable_agent": ("enable_agent", ("bgpd",)),
        "disable_bgp_neighborship": (
            "enable_bgp_neighborship",
            (context.interface,),
        ),
        "disable_chef": ("enable_chef", ()),
        "disable_port": (
            "enable_port",
            (context.interface, InterfaceFlapMethod.THRIFT_PORT_STATE_CHANGE),
        ),
        "fill_disk": ("unfill_disk", ()),
        "crash_service": ("restart_service", (FbossSystemctlServiceName.BGP,)),
        "shutdown_all_bgp_sessions": ("start_all_bgp_sessions", ()),
        "stop_service": ("start_service", (FbossSystemctlServiceName.BGP,)),
        "async_stop_service": (
            "async_start_service",
            (FbossSystemctlServiceName.BGP,),
        ),
        "async_openr_advertise_prefix": (
            "async_openr_withdraw_prefix",
            ("2001:db8:ffff::/64",),
        ),
        "async_set_openr_link_metric_increment": (
            "async_unset_openr_link_metric_increment",
            ((context.interface,),),
        ),
        "async_set_openr_link_overload": (
            "async_unset_openr_link_overload",
            (context.interface,),
        ),
        "async_set_openr_node_metric_increment": (
            "async_unset_openr_node_metric_increment",
            (),
        ),
        "async_set_openr_node_overload": ("async_unset_openr_node_overload", ()),
        "async_drain_device": ("async_undrain_device", ()),
        "async_drain_interfaces": (
            "async_undrain_interfaces",
            ((context.interface,),),
        ),
        "async_softdrain_interface": (
            "async_undrain_interface",
            (context.interface,),
        ),
        "async_softdrain_interfaces": (
            "async_undrain_interfaces",
            ((context.interface,),),
        ),
    }
    if method_name in {"async_create_file_with_content", "async_write_file_on_device"}:
        return (
            "async_delete_file",
            (f"{context.remote_dir}/driver_tester.txt",),
        )
    return recovery.get(method_name)


async def _auto_invoke(driver: Any, context: RunContext, method: Any) -> Any:
    method_name = method.__name__
    if (
        not _is_observational(method_name)
        and _auto_recovery_spec(context, method_name) is None
    ):
        raise UncallableProbe(
            f"Generated mutating probe {method_name} has no paired recovery"
        )

    signature = inspect.signature(method)
    kwargs: dict[str, Any] = {}
    for parameter in signature.parameters.values():
        if parameter.kind in {
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        }:
            continue
        if parameter.default is not inspect.Parameter.empty:
            continue
        kwargs[parameter.name] = await _auto_value(
            driver, context, method_name, parameter
        )

    result = await _call(method, **kwargs)
    if hasattr(result, "__aenter__") and hasattr(result, "__aexit__"):
        async with result as client:
            return {"client_type": type(client).__name__, "connected": True}
    return result


async def _auto_recovery(driver: Any, context: RunContext, method_name: str) -> None:
    """Restore paired state after a generated mutating probe."""
    recovery_spec = _auto_recovery_spec(context, method_name)
    if recovery_spec is None:
        return
    recovery_name, args = recovery_spec
    await _call(getattr(driver, recovery_name), *args)


async def _cleanup_patcher(driver: Any, patcher_name: str, config_name: str) -> str:
    try:
        await driver.async_coop_unregister_patchers(patcher_name, config_name)
        if config_name == AGENT_CONFIG_PATCHER_NAME:
            await driver.async_try_agent_config_reload()
        return "cleanup succeeded"
    except Exception as error:
        return f"cleanup failed: {type(error).__name__}: {error}"


async def _require_patcher_cleanup(
    driver: Any, patchers: Sequence[tuple[str, str]]
) -> None:
    """Attempt every requested cleanup and fail if any patcher remains."""
    failures = []
    for patcher_name, config_name in patchers:
        outcome = await _cleanup_patcher(driver, patcher_name, config_name)
        logging.getLogger(__name__).info(outcome)
        if outcome.startswith("cleanup failed"):
            failures.append(f"{patcher_name}: {outcome}")
    if failures:
        raise RuntimeError("; ".join(failures))


async def _cleanup_owned_patchers(driver: Any, run_id: str) -> dict[str, Any]:
    """Remove every patcher created by this run, including UUID-suffixed names."""
    prefix = f"taac_driver_tester_{run_id}_"
    cleanup: dict[str, Any] = {}
    for config_name in SERVICE_CONFIGS:
        try:
            patchers = await driver.async_coop_list_patchers(config_name)
            names = [
                patcher.name for patcher in patchers if patcher.name.startswith(prefix)
            ]
            cleanup[config_name] = {}
            for name in names:
                cleanup[config_name][name] = await _cleanup_patcher(
                    driver, name, config_name
                )
        except Exception as error:
            cleanup[config_name] = f"{type(error).__name__}: {error}"
    return cleanup


async def _restart_bgp_and_wait(driver: Any) -> None:
    await driver.async_restart_service(FbossSystemctlServiceName.BGP)
    await driver.async_wait_for_bgp_convergence()


async def _create_coop_snapshot(driver: Any, context: RunContext) -> str:
    snapshot = f"{context.remote_dir}/coop_backup.bundle"
    await driver.async_run_cmd_on_shell(
        "set -e; "
        f"rm -f {shlex.quote(snapshot)}; "
        f"git -C /etc/coop bundle create {shlex.quote(snapshot)} HEAD; "
        f"git bundle verify {shlex.quote(snapshot)}"
    )
    return snapshot


async def _restore_coop_snapshot(driver: Any, snapshot: str) -> None:
    """Restore the exact COOP Git worktree after the destructive reset probe."""
    coop_service = await driver.async_get_systemctl_service_name(
        FbossSystemctlServiceName.COOP
    )
    coop_dir_output = await driver.async_run_cmd_on_shell("readlink -f /etc/coop")
    if coop_dir_output is None:
        raise RuntimeError("Unable to resolve the COOP directory from /etc/coop")
    coop_dir = coop_dir_output.strip()
    if not coop_dir.startswith("/"):
        raise RuntimeError(
            f"Invalid COOP directory resolved from /etc/coop: {coop_dir}"
        )
    quoted_snapshot = shlex.quote(snapshot)
    staging = shlex.quote(f"{snapshot}.restore")
    rollback = shlex.quote(f"{snapshot}.rollback")
    quoted_coop_dir = shlex.quote(coop_dir)
    quoted_coop_service = shlex.quote(coop_service)
    restore_script = (
        "set -e; "
        "restore_on_error() { "
        "status=$?; trap - ERR; set +e; "
        f"if test -d {rollback}; then "
        f"rm -rf {quoted_coop_dir}; "
        f"mv {rollback} {quoted_coop_dir}; "
        "fi; "
        f"systemctl start {quoted_coop_service}; "
        'exit "$status"; '
        "}; "
        "trap restore_on_error ERR; "
        f"rm -rf {staging} {rollback}; "
        f"git clone {quoted_snapshot} {staging}; "
        f"git -C {staging} fsck --no-dangling; "
        f"test -s {staging}/agent/current; "
        f"systemctl stop {quoted_coop_service}; "
        f"mv {quoted_coop_dir} {rollback}; "
        f"mv {staging} {quoted_coop_dir}; "
        f"chown -R coop:switching {quoted_coop_dir}; "
        f"systemctl start {quoted_coop_service}; "
        "trap - ERR; "
        f"rm -rf {rollback}"
    )
    command = (
        "systemd-run --wait --collect --service-type=exec "
        f"/bin/bash -c {shlex.quote(restore_script)}"
    )
    await driver.async_run_cmd_on_shell(command, timeout=600)
    await driver.async_agent_config_reload()
    await driver.async_wait_for_agent_state_configured()
    await driver.async_wait_for_bgp_convergence()


def _noop_bgp_patcher(name: str, peer_group: str) -> CoopConfigPatcher:
    return CoopConfigPatcher(
        name=name,
        patcher=ConfigPatcher(
            py_function=PythonPatcher(
                name="configure_bgp_peer_group",
                kwargs={"name": peer_group, "attributes_to_update_json": "{}"},
            )
        ),
        description="TAAC FBOSS driver compatibility no-op patcher",
        owner=DNE_TEST_REGRESSION_NAME,
        persistent=True,
    )


async def _first_neighbor_role(driver: Any) -> Any:
    neighbors = await driver.async_get_lldp_neighbors()
    for neighbor in neighbors.values():
        remote_name = getattr(neighbor, "remote_device_name", "")
        if remote_name:
            try:
                return get_role_from_hostname(remote_name)
            except Exception:
                continue
    return Role.FSW


async def _first_scalar_config_path(driver: Any) -> str:
    async with driver.async_agent_client as client:
        config = json.loads(await client.getRunningConfig())

    def walk(value: Any, prefix: str = "") -> str | None:
        if isinstance(value, dict):
            for key in sorted(value):
                path = f"{prefix}.{key}" if prefix else key
                found = walk(value[key], path)
                if found:
                    return found
        elif isinstance(value, (str, int, float)) and prefix:
            return prefix
        return None

    path = walk(config)
    if path is None:
        raise UncallableProbe("Running Agent config contains no scalar attribute")
    return path


async def _first_port_channel(driver: Any) -> str:
    aggregates = await driver.async_get_all_aggregated_interfaces()
    if not aggregates:
        raise UncallableProbe("Device has no aggregate interface for min-link probe")
    return sorted(aggregates)[0]


async def _current_speed_args(driver: Any, interface: str) -> tuple[str, str]:
    speeds = await driver.async_get_interfaces_speed_in_Gbps([interface])
    profiles = await driver.async_get_interfaces_speed_profile_id([interface])
    speed_names = {
        1: "ONEG",
        10: "TENG",
        25: "TWENTYFIVEG",
        40: "FORTYG",
        50: "FIFTYG",
        100: "HUNDREDG",
        200: "TWOHUNDREDG",
        400: "FOURHUNDREDG",
        800: "EIGHTHUNDREDG",
    }
    speed = speeds.get(interface)
    profile = profiles.get(interface)
    if speed not in speed_names or not profile:
        raise UncallableProbe(
            f"Cannot derive current speed/profile for {interface}: {speed=}, {profile=}"
        )
    return speed_names[speed], profile


async def invoke_probe(  # noqa: C901
    driver: Any, context: RunContext, spec: ProbeSpec
) -> Any:
    method = getattr(driver, spec.method_name, None)
    if method is None:
        raise UncallableProbe(f"{type(driver).__name__} has no {spec.method_name}")

    if spec.handler == "auto":
        return await _auto_invoke(driver, context, method)
    if spec.handler == "default":
        return await _call(method, *spec.args, **dict(spec.kwargs))
    if spec.handler == "sync_method":
        return await asyncio.to_thread(method)
    if spec.handler == "interface":
        return await _call(method, context.interface)
    if spec.handler == "interface_list":
        return await _call(method, [context.interface])
    if spec.handler == "qsfp_client":
        async with await method() as client:
            return await client.getPortTransceiverIDs()
    if spec.handler == "coop_client":
        async with await method() as client:
            return await client.listPatchers(AGENT_CONFIG_PATCHER_NAME)
    if spec.handler == "bgp_client":
        helper = await method()
        return await helper.async_get_health_report()
    if spec.handler == "sw_agent_client":
        async with await method() as client:
            return await client.getSwitchRunState()
    if spec.handler == "hw_agent_client":
        async with await method(switch_index=0) as client:
            return await client.listHwObjects([], cached=True)
    if spec.handler == "agent_property":
        async with method as client:
            return await client.getSwitchRunState()
    if spec.handler == "fsdb_client":
        async with await method() as client:
            return await client.getAllOperPublisherInfos()
    if spec.handler == "drainer_client":
        async with method() as client:
            return await client.is_drained()
    if spec.handler == "is_missing_patcher":
        return await method(context.patcher_name("missing"), AGENT_CONFIG_PATCHER_NAME)
    if spec.handler == "is_missing_agent_patcher":
        return await method(context.patcher_name("missing"))
    if spec.handler == "agent_config_attribute":
        path = await _first_scalar_config_path(driver)
        return {"attribute": path, "value": await method(path)}
    if spec.handler == "lldp_role":
        return await method(await _first_neighbor_role(driver))
    if spec.handler == "create_remote_dir":
        await method(context.remote_dir)
        return context.remote_dir
    if spec.handler == "write_remote_file":
        remote = f"{context.remote_dir}/written.txt"
        await method("taac-driver-compatibility\n", remote)
        observed = await driver.async_run_cmd_on_shell(f"cat {remote}")
        await driver.async_run_cmd_on_shell(f"rm -f {remote}")
        return observed
    if spec.handler == "copy_remote_file":
        local = context.output_dir / "copy-source.txt"
        local.write_text("taac-driver-copy-compatibility\n", encoding="utf-8")
        remote = f"{context.remote_dir}/copied.txt"
        await method(str(local), remote)
        observed = await driver.async_run_cmd_on_shell(f"cat {remote}")
        await driver.async_run_cmd_on_shell(f"rm -f {remote}")
        return observed
    if spec.handler in {"register_python_patcher", "register_typed_patcher"}:
        name = context.patcher_name(spec.handler)
        async with _recover_without_masking(
            lambda: _require_patcher_cleanup(
                driver, ((name, BGP_CONFIG_PATCHER_NAME),)
            ),
            "BGP patcher cleanup",
        ):
            if spec.handler == "register_python_patcher":
                result = await method(
                    BGP_CONFIG_PATCHER_NAME,
                    name,
                    "configure_bgp_peer_group",
                    {"name": context.peer_group, "attributes_to_update_json": "{}"},
                    "TAAC driver compatibility no-op",
                )
            else:
                result = await method(
                    BGP_CONFIG_PATCHER_NAME,
                    _noop_bgp_patcher(name, context.peer_group),
                )
            return {"result": result, "cleanup": "deferred to finally"}
    if spec.handler == "unregister_missing_patcher":
        return await method(
            context.patcher_name("never_registered"), AGENT_CONFIG_PATCHER_NAME
        )
    if spec.handler == "unregister_python_patcher":
        name = context.patcher_name("unregister_python")
        await driver.async_coop_register_patchers(
            BGP_CONFIG_PATCHER_NAME, _noop_bgp_patcher(name, context.peer_group)
        )
        return await method(name, BGP_CONFIG_PATCHER_NAME)
    if spec.handler in {"persistent_port_shutdown", "persistent_port_unshutdown"}:
        name = context.patcher_name(spec.handler)
        if spec.handler == "persistent_port_unshutdown":
            await driver.async_register_patcher_to_shut_ports_persistently(
                name, [context.interface]
            )
            return await method(name, [context.interface])
        async with _recover_without_masking(
            lambda: _require_patcher_cleanup(
                driver, ((name, AGENT_CONFIG_PATCHER_NAME),)
            ),
            "persistent port patcher cleanup",
        ):
            return await method(name, [context.interface])
    if spec.handler in {"isolate_restore", "restore_after_isolate"}:
        name = context.patcher_name(spec.handler)
        if spec.handler == "restore_after_isolate":
            await driver.async_isolate_test_bed_connectivity([context.interface], name)
            return await method([context.interface], name)
        async with _recover_without_masking(
            lambda: driver.async_restore_test_bed_connectivity(
                [context.interface], name
            ),
            "isolation cleanup",
        ):
            return await method([context.interface], name)
    if spec.handler == "static_route_patcher":
        name = context.patcher_name("static_route")
        async with _recover_without_masking(
            lambda: _require_patcher_cleanup(
                driver, ((name, AGENT_CONFIG_PATCHER_NAME),)
            ),
            "static route patcher cleanup",
        ):
            return await method({}, name, is_patcher_name_uuid_needed=False)
    if spec.handler in {"modify_minlink", "set_minlink", "set_all_minlink"}:
        port_channel = await _first_port_channel(driver)
        name = context.patcher_name(spec.handler)
        registered_name = name
        async with _recover_without_masking(
            lambda: _require_patcher_cleanup(
                driver, (((registered_name or name), AGENT_CONFIG_PATCHER_NAME),)
            ),
            "min-link patcher cleanup",
        ):
            if spec.handler == "modify_minlink":
                registered_name = await method(
                    port_channel, 100.0, name, is_patcher_name_uuid_needed=False
                )
            elif spec.handler == "set_minlink":
                registered_name = await method(
                    {"port_channel_name": port_channel, "link_percentage": "100"}, name
                )
            else:
                registered_name = await method({"link_percentage": "100"}, name)
            return registered_name
    if spec.handler == "change_speed":
        speed, profile = await _current_speed_args(driver, context.interface)
        name = context.patcher_name("speed")
        async with _recover_without_masking(
            lambda: _require_patcher_cleanup(
                driver, ((name, AGENT_CONFIG_PATCHER_NAME),)
            ),
            "speed patcher cleanup",
        ):
            return await method([context.interface], speed, profile, name)
    if spec.handler == "change_mtu":
        info = await driver.get_specific_interface_info(context.interface)
        mtu = int(getattr(info, "maxFrameSize", 9412) or 9412)
        name = context.patcher_name("mtu")
        async with _recover_without_masking(
            lambda: _require_patcher_cleanup(
                driver, ((name, AGENT_CONFIG_PATCHER_NAME),)
            ),
            "MTU patcher cleanup",
        ):
            return await method([context.interface], mtu, name)
    if spec.handler == "bgp_peer_group_patcher":
        name = context.patcher_name("bgp_peer_group")
        registered_name = name
        async with _recover_without_masking(
            lambda: _require_patcher_cleanup(
                driver, (((registered_name or name), BGP_CONFIG_PATCHER_NAME),)
            ),
            "BGP peer-group patcher cleanup",
        ):
            registered_name = await method(
                {"name": context.peer_group, "attributes_to_update_json": "{}"}, name
            )
            return registered_name
    if spec.handler in {"setup_agg_port", "remove_agg_port"}:
        setup_name = context.patcher_name(f"{spec.handler}_setup")
        remove_name = context.patcher_name(f"{spec.handler}_remove")
        port_channel_id = "65535"
        async with _recover_without_masking(
            lambda: _require_patcher_cleanup(
                driver,
                (
                    (remove_name, AGENT_CONFIG_PATCHER_NAME),
                    (setup_name, AGENT_CONFIG_PATCHER_NAME),
                ),
            ),
            "aggregate-port patcher cleanup",
        ):
            if spec.handler == "setup_agg_port":
                return await method([context.interface], port_channel_id, setup_name)
            await driver.async_setup_agg_port(
                [context.interface], port_channel_id, setup_name
            )
            return await method(port_channel_id, remove_name)
    if spec.handler == "local_drain_cycle":
        async with _recover_without_masking(
            lambda: driver.async_local_drainer_drain(False),
            "local undrain cleanup",
        ):
            return await method(True)
    if spec.handler in {"onbox_drain_cycle", "onbox_softdrain_cycle"}:
        async with _recover_without_masking(
            driver.async_onbox_undrain_device,
            "on-box undrain cleanup",
        ):
            return await method()
    if spec.handler == "onbox_undrain":
        await driver.async_onbox_drain_device()
        async with _recover_without_masking(
            lambda: driver.async_local_drainer_drain(False),
            "final undrain cleanup",
        ):
            return await method()
    if spec.handler == "restart_bgp":
        await method(FbossSystemctlServiceName.BGP)
        await driver.async_wait_for_bgp_convergence()
        return "BGP restarted and converged"
    if spec.handler == "crash_bgp":
        async with _recover_without_masking(
            lambda: _restart_bgp_and_wait(driver),
            "BGP restart cleanup",
        ):
            await method(FbossSystemctlServiceName.BGP)
        return "BGP crash observed; service restarted and converged"
    if spec.handler == "coop_reset_restore":
        snapshot = await _create_coop_snapshot(driver, context)
        async with _recover_without_masking(
            lambda: _restore_coop_snapshot(driver, snapshot),
            "COOP snapshot restore",
        ):
            await method()
            return {"reset": "completed", "snapshot": snapshot}
    if spec.handler == "full_reboot":
        await method()
        await driver.wait_for_ssh_reachable(max_duration=900, sleep_time=5)
        await driver.async_wait_for_agent_state_configured()
        return "full reboot completed; SSH and Agent recovered"
    if spec.handler == "reboot_switch":
        return await method(
            SystemRebootMethod.FULL_SYSTEM_REBOOT,
            wait_till_eor=False,
            skip_undrain=False,
        )
    raise UncallableProbe(f"Unknown probe handler: {spec.handler}")


async def execute_probe(
    driver: Any,
    context: RunContext,
    spec: ProbeSpec,
    artifact: RawArtifact,
) -> ProbeResult:
    started = time.monotonic()
    stdout = io.StringIO()
    stderr = io.StringIO()
    log_handler = InvocationLogHandler()
    root_logger = logging.getLogger()
    root_logger.addHandler(log_handler)
    status = "PASS"
    works = "yes"
    error_text = ""
    result: Any = None
    try:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = await asyncio.wait_for(
                invoke_probe(driver, context, spec), timeout=spec.timeout_seconds
            )
    except asyncio.TimeoutError:
        status = "TIMEOUT"
        works = "no"
        error_text = f"Timed out after {spec.timeout_seconds:.1f}s"
    except RecoveryFailed as error:
        status = "FAIL" if error.primary_error is not None else "RECOVERY_FAILED"
        works = "no"
        error_text = str(error)
        stderr.write(traceback.format_exc())
    except UncallableProbe as error:
        status = "SKIPPED_UNCALLABLE"
        works = "no"
        error_text = str(error)
    except Exception as error:
        status = "FAIL"
        works = "no"
        error_text = f"{type(error).__name__}: {error}"
        stderr.write(traceback.format_exc())
    finally:
        if spec.handler == "auto" and status != "SKIPPED_UNCALLABLE":
            try:
                await asyncio.wait_for(
                    _auto_recovery(driver, context, spec.method_name),
                    timeout=60,
                )
            except Exception as cleanup_error:
                cleanup_message = (
                    "automatic recovery failed: "
                    f"{type(cleanup_error).__name__}: {cleanup_error}"
                )
                log_handler.messages.append(cleanup_message)
                error_text = (
                    f"{error_text}; {cleanup_message}"
                    if error_text
                    else cleanup_message
                )
                if status == "PASS":
                    status = "RECOVERY_FAILED"
                    works = "no"
        root_logger.removeHandler(log_handler)
    duration = time.monotonic() - started
    record = {
        "device": context.device,
        "service_type": spec.service_type,
        "method_name": spec.method_name,
        "case_name": spec.handler,
        "status": status,
        "works_as_expected": works,
        "duration_seconds": round(duration, 3),
        "result": result,
        "error": error_text,
        "stdout": stdout.getvalue(),
        "stderr": stderr.getvalue(),
        "logs": log_handler.messages,
    }
    start_line, end_line = artifact.append(spec.method_name, record)
    return ProbeResult(
        device=context.device,
        service_type=spec.service_type,
        method_name=spec.method_name,
        case_name=spec.handler,
        response=f"{artifact.path.name}:L{start_line}-L{end_line}",
        raw_start_line=start_line,
        raw_end_line=end_line,
        works_as_expected=works,
        status=status,
        duration_seconds=round(duration, 3),
        error=error_text,
    )


async def run_probe_specs(
    driver: Any,
    context: RunContext,
    artifact: RawArtifact,
    specs: Iterable[ProbeSpec],
) -> list[ProbeResult]:
    results = []
    for spec in specs:
        print(f"[{spec.service_type}] {spec.method_name} ...", flush=True)
        result = await execute_probe(driver, context, spec, artifact)
        results.append(result)
        print(f"  {result.status} ({result.response})", flush=True)
    return results


def write_summaries(results: Sequence[ProbeResult], output_dir: Path) -> None:
    fields = (
        list(asdict(results[0]).keys())
        if results
        else list(ProbeResult.__annotations__)
    )
    with (output_dir / "summary.csv").open("w", newline="", encoding="utf-8") as sink:
        writer = csv.DictWriter(sink, fieldnames=fields)
        writer.writeheader()
        writer.writerows(asdict(result) for result in results)
    (output_dir / "summary.json").write_text(
        json.dumps([asdict(result) for result in results], indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    header = (
        "| Device | Service type | Method / case | Response | Works as expected | "
        "Status | Duration (s) | Error |"
    )
    separator = "|---|---|---|---|---|---:|---:|---|"
    rows = [header, separator]
    for result in results:
        error = result.error.replace("|", "\\|").replace("\n", " ")
        rows.append(
            f"| {result.device} | {result.service_type} | "
            f"`{result.method_name}` / `{result.case_name}` | "
            f"`{result.response}` | {result.works_as_expected} | {result.status} | "
            f"{result.duration_seconds:.3f} | {error} |"
        )
    (output_dir / "summary.md").write_text("\n".join(rows) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run every inherited public FbossSwitchInternal API and record results",
        fromfile_prefix_chars="@",
    )
    parser.add_argument("--device", required=True)
    parser.add_argument(
        "--interface",
        help="Probe interface. Defaults to the first admin-up and oper-up interface.",
    )
    parser.add_argument("--peer-group", default=DEFAULT_PEER_GROUP)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        help="Run only a named method; repeatable. Coverage is still reported in metadata.",
    )
    parser.add_argument("--fail-on-error", action="store_true")
    return parser.parse_args()


async def async_main(args: argparse.Namespace) -> int:
    os.environ["TAAC_SSH_VIA_LAB_SSH"] = "1"
    probe_matrix = build_probe_matrix()
    validate_probe_coverage(probe_matrix)
    run_id = time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
    output_dir = args.output_dir or Path.cwd() / f"driver_tester_{run_id}"
    output_dir.mkdir(parents=True, exist_ok=True)
    driver: Any = await async_get_device_driver(args.device)
    interface = args.interface
    if interface is None:
        admin_states, operational_states = await asyncio.gather(
            driver.async_get_all_interfaces_admin_status(),
            driver.async_get_all_interfaces_operational_status(),
        )
        interface = next(
            (
                name
                for name in sorted(operational_states)
                if operational_states[name] and admin_states.get(name, False)
            ),
            None,
        )
        if interface is None:
            raise RuntimeError("No admin-up and oper-up interface found on device")
    context = RunContext(
        device=args.device,
        interface=interface,
        peer_group=args.peer_group,
        run_id=run_id,
        output_dir=output_dir,
    )
    artifact = RawArtifact(output_dir / "raw_output.log")
    specs = tuple(
        spec for spec in probe_matrix if not args.only or spec.method_name in args.only
    )
    unknown = sorted(set(args.only) - {spec.method_name for spec in probe_matrix})
    if unknown:
        raise ValueError(f"Unknown --only methods: {unknown}")

    metadata = {
        "device": args.device,
        "driver_ssh_transport": "lab-ssh",
        "TAAC_SSH_VIA_LAB_SSH": os.environ["TAAC_SSH_VIA_LAB_SSH"],
        "interface": interface,
        "interface_source": "explicit" if args.interface else "auto-selected-active",
        "peer_group": args.peer_group,
        "run_id": run_id,
        "started_epoch_seconds": time.time(),
        "public_driver_api": sorted(public_driver_api()),
        "public_driver_api_count": len(public_driver_api()),
        "curated_probe_count": len(CURATED_PROBES),
        "generated_probe_count": len(probe_matrix) - len(CURATED_PROBES),
        "selected_methods": [spec.method_name for spec in specs],
    }
    (output_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    await driver.async_create_dir_if_not_exists(context.remote_dir)
    results = await run_probe_specs(driver, context, artifact, specs)
    cleanup_record: dict[str, Any] = {}
    try:
        cleanup_record["owned_patchers"] = await _cleanup_owned_patchers(driver, run_id)
        try:
            await driver.async_onbox_undrain_device()
            cleanup_record["undrain"] = "succeeded"
        except Exception as error:
            cleanup_record["undrain"] = f"{type(error).__name__}: {error}"
        await driver.async_run_cmd_on_shell(f"rm -rf {context.remote_dir}")
        cleanup_record["remote_dir"] = "removed"
    except Exception as error:
        cleanup_record["final_cleanup_error"] = f"{type(error).__name__}: {error}"
    artifact.append("FINAL_CLEANUP", cleanup_record)
    write_summaries(results, output_dir)
    failures = sum(result.works_as_expected != "yes" for result in results)
    metadata.update(
        {
            "ended_epoch_seconds": time.time(),
            "status_counts": {
                status: sum(result.status == status for result in results)
                for status in sorted({result.status for result in results})
            },
        }
    )
    (output_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Artifacts: {output_dir}")
    print(
        f"Methods: {len(results)}, passed: {len(results) - failures}, failed: {failures}"
    )
    return 1 if args.fail_on_error and failures else 0


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(asyncio.run(async_main(parse_args())))


if __name__ == "__main__":
    main()
