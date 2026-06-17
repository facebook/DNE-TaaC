# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import json
import typing as t

from taac.utils.oss_taac_lib_utils import (
    ConsoleFileLogger,
    get_root_logger,
)
from pyre_extensions import JSON
from thrift.py3.serializer import deserialize, Protocol, serialize
from thrift.py3.types import Struct as TStruct


LOGGER: ConsoleFileLogger = get_root_logger()


def try_json_loads(serialized: t.Optional[str], fallback_value: t.Any = None) -> t.Any:
    if serialized is not None:
        try:
            return json.loads(serialized)
        except Exception:
            return serialized
    return fallback_value


def thrift_to_json(struct: TStruct) -> str:
    return serialize(struct, protocol=Protocol.JSON).decode()


def try_thrift_to_json(val: t.Any) -> str:
    try:
        if isinstance(val, list):
            return json.dumps([try_thrift_to_json(item) for item in val])
        elif isinstance(val, TStruct):
            return thrift_to_json(val)
    except Exception as e:
        LOGGER.debug(f"Failed to convert {val} to json: {e}")
    return val


def thrift_to_dict(struct: TStruct) -> dict[str, JSON]:
    return dict(json.loads(thrift_to_json(struct)))


def try_thrift_to_dict(struct: TStruct | None) -> dict[str, JSON]:
    if struct is None:
        return {}
    try:
        return thrift_to_dict(struct)
    except Exception:
        LOGGER.debug("Failed to convert thrift struct to dict", exc_info=True)
        return {}


TType = t.TypeVar("TType", bound=TStruct)


def json_to_thrift(data: t.Union[str, bytes], thrift_type: t.Type[TType]) -> TType:
    if isinstance(data, str):
        data = data.encode()
    return deserialize(thrift_type, data, protocol=Protocol.JSON)


def try_json_to_thrift(
    data: t.Union[str, bytes, dict], thrift_type: t.Type[TType]
) -> t.Union[TType, str, bytes, dict]:
    try:
        if isinstance(data, dict):
            return json_to_thrift(json.dumps(data), thrift_type)
        else:
            return json_to_thrift(data, thrift_type)
    except Exception:
        return data
