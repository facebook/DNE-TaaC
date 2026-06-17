# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import json
import typing as t

from ixia.ixia import types as ixia_types
from taac.test_as_a_config import types as taac_types


def create_query(
    regex: str,
    query_type: ixia_types.QueryType = ixia_types.QueryType.DISPLAY_NAME,
) -> ixia_types.Query:
    return ixia_types.Query(
        regex=regex,
        query_type=query_type,
    )


def create_field(
    field_regex: str,
    field_attrs: dict,
    references: t.Optional[dict[str, taac_types.Reference]] = None,
) -> taac_types.Field:
    return taac_types.Field(
        query=create_query(field_regex),
        attrs_json=json.dumps(field_attrs),
        references=references or None,
    )


def create_packet_header(
    stack_regex: str,
    append_to_stack_regex: t.Optional[str] = None,
    fields: t.Optional[list[taac_types.Field]] = None,
    remove_from_stack: bool = False,
) -> taac_types.PacketHeader:
    return taac_types.PacketHeader(
        query=create_query(
            regex=stack_regex, query_type=ixia_types.QueryType.STACK_TYPE_ID
        ),
        append_to_query=create_query(
            regex=append_to_stack_regex,
            query_type=ixia_types.QueryType.STACK_TYPE_ID,
        )
        if append_to_stack_regex
        else None,
        fields=fields or None,
        remove_from_stack=remove_from_stack,
    )
