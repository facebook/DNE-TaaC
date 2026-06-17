# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import json
import typing as t

from taac.transform_functions import (
    lookup_transformation_function,
)
from taac.utils.common import eval_jq
from taac.utils.json_thrift_utils import (
    try_json_loads,
    try_thrift_to_json,
)
from taac.utils.oss_taac_lib_utils import get_root_logger
from taac.test_as_a_config import types as taac_types


class ParameterEvaluator:
    def __init__(
        self,
        jq_vars: t.Optional[t.Dict[str, t.Any]] = None,
        dynamic_vars: t.Optional[t.Dict[str, str]] = None,
    ) -> None:
        self.jq_vars = jq_vars if jq_vars is not None else {}
        self.dynamic_vars = dynamic_vars if dynamic_vars is not None else {}
        self.logger = get_root_logger()
        self.cache_uuid = None

    def evaluate(
        self,
        params: t.Optional[taac_types.Params] = None,
        dynamic_vars: t.Optional[t.Dict[str, str]] = None,
    ) -> t.Dict[str, t.Any]:
        params_dict: t.Dict[str, t.Any] = {}
        if not params:
            return params_dict
        self._eval_static_params(params, params_dict)
        self._eval_json_params(params, params_dict)
        self._eval_jq_params(params, params_dict, dynamic_vars)
        self._eval_transform_params(params, params_dict)
        self._cache_params(params, params_dict)
        return params_dict

    def set_cache_uuid(self, cache_uuid: str) -> None:
        self.cache_uuid = cache_uuid
        self.jq_vars[self.cache_uuid] = {"cached": {}}

    def _eval_static_params(
        self, params: taac_types.Params, params_dict: t.Dict[str, t.Any]
    ) -> None:
        if params.static_params:
            for name, param in params.static_params.items():
                params_dict[name] = param.value

    def _eval_json_params(
        self, params: taac_types.Params, params_dict: t.Dict[str, t.Any]
    ) -> None:
        if params.json_params:
            params_dict.update(json.loads(params.json_params))

    def _eval_jq_params(
        self,
        params: taac_types.Params,
        params_dict: t.Dict[str, t.Any],
        dynamic_vars: t.Optional[t.Dict[str, str]] = None,
    ) -> None:
        dynamic_vars = self.dynamic_vars | (dynamic_vars or {})
        if params.jq_params and self.jq_vars:
            for name, jq_expr in params.jq_params.items():
                jq_expr = jq_expr.format(**dynamic_vars)
                params_dict[name] = self._run_jq_lib(jq_expr)

    def _run_jq_lib(self, jq_expr: str) -> t.Any:
        jq_vars = self.jq_vars
        if "cached" in jq_expr.split("."):
            # pyrefly: ignore [bad-index]
            jq_vars = self.jq_vars[self.cache_uuid]
        return eval_jq(jq_expr, jq_vars)

    def _eval_transform_params(
        self, params: taac_types.Params, params_dict: t.Dict[str, t.Any]
    ) -> None:
        if params.transform_params:
            for name, transform_functions in params.transform_params.items():
                transformed_val = params_dict.get(name)
                if transformed_val:
                    transformed_val = try_json_loads(transformed_val)
                for transform_function in transform_functions:
                    transform_callable = lookup_transformation_function(
                        transform_function.name
                    )
                    transform_args: t.Dict[str, t.Any] = self._get_transform_args(
                        transform_function
                    )
                    transformed_val = transform_callable(
                        transformed_val, transform_args
                    )
                transformed_val = try_thrift_to_json(transformed_val)
                params_dict[name] = transformed_val
                self.logger.debug(f"Transformed {name} to {transformed_val}")

    def _get_transform_args(
        self, transform_function: taac_types.TransformFunction
    ) -> t.Dict[str, t.Any]:
        transform_args: t.Dict[str, t.Any] = {}
        if transform_function.static_params:
            for name, param in transform_function.static_params.items():
                transform_args[name] = param.value
        if transform_function.json_params:
            transform_args.update(json.loads(transform_function.json_params))
        return transform_args

    def _cache_params(
        self, params: taac_types.Params, params_dict: t.Dict[str, t.Any]
    ) -> None:
        if not params.cache_params or not self.cache_uuid:
            return
        for param_name, cache_id in params.cache_params.items():
            if param_val := params_dict.get(param_name):
                self.jq_vars[self.cache_uuid]["cached"][cache_id] = param_val
