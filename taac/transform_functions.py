# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import random
import typing as t

from taac.constants import TestDevice
from taac.utils.json_thrift_utils import try_json_to_thrift
from taac.utils.oss_taac_lib_utils import (
    ConsoleFileLogger,
    get_root_logger,
)
from taac.test_as_a_config import types as taac_types

LOGGER: ConsoleFileLogger = get_root_logger()


def lookup_transformation_function(select_name: str):
    return {
        "SELECT_SWITCH_INTERFACES": select_switch_interfaces,
        "SELECT_INTERFACES_BY_SLICING": select_interfaces_by_slicing,
        "SELECT_SAMPLE": select_sample,
        "SELECT_INTERFACES_BY_NEIGHBORS": select_interfaces_by_neighbors,
    }.get(select_name, None)


def select_switch_interfaces(
    val: t.Any, params: t.Dict[str, t.Any]
) -> t.List[taac_types.TestInterface]:
    test_device: TestDevice = val
    return test_device.interfaces


def select_interfaces_by_slicing(
    val: t.Any, params: t.Dict[str, t.Any]
) -> t.List[taac_types.TestInterface]:
    interfaces: t.List[taac_types.TestInterface] = val
    slicing_expression = params["slicing_expression"]
    slice_obj = slice(
        *map(lambda x: int(x) if x else None, slicing_expression.split(":"))
    )
    selected_interfaces = interfaces[slice_obj]
    return selected_interfaces


def select_interfaces_by_neighbors(
    val: t.Any, params: t.Dict[str, t.Any]
) -> t.List[taac_types.TestInterface]:
    interfaces: t.List[taac_types.TestInterface] = [  # pyre-ignore
        try_json_to_thrift(interface, taac_types.TestInterface) for interface in val
    ]
    neighbors = params["neighbors"]
    selected_interfaces = []
    for interface in interfaces:
        if interface.neighbor_switch_name in neighbors:
            selected_interfaces.append(interface)
    return selected_interfaces


def select_sample(val: t.List[t.Any], params: t.Dict[str, t.Any]) -> t.List[t.Any]:
    return random.sample(val, params["sample_size"])
