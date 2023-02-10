# Copyright 2023 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not
# use this file except in compliance with the License. A copy of the License is
# located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed
# on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, express or
# implied. See the License for the specific language governing permissions and
# limitations under the License.


import pytest
from assertpy import assert_that

from pcluster.cli.exceptions import ParameterException
from pcluster.lib import lib as pcluster


def _gen_model(funcs):
    def _gen_func_def(func, params):
        has_body = any(x["body"] for x in params)
        return {"func": func, "params": params, **({"body_name": "body"} if has_body else {})}

    return {func: _gen_func_def(func, ps) for func, ps in funcs.items()}


class TestParallelClusterLib:
    @pytest.mark.parametrize(
        "model, func, kwargs, expected",
        [
            (
                {
                    "op": [
                        {"body": False, "name": "param", "required": True, "type": "number"},
                        {"body": True, "name": "body_param", "required": False, "type": "number"},
                    ]
                },
                lambda body, param=None: [body, param],
                {"param": 1, "body_param": 2},
                [{"bodyParam": 2}, 1],
            ),
            (
                {
                    "op": [
                        {"body": False, "name": "param", "required": True, "type": "number"},
                        {"body": True, "name": "body_param", "required": False, "type": "number"},
                    ]
                },
                lambda body, param=None: [body, param],
                {"param": 1},
                [{"bodyParam": None}, 1],
            ),
            (
                {"op": [{"body": False, "name": "param", "required": False, "type": "number"}]},
                lambda param=None: param,
                {"param": 1},
                1,
            ),
            (
                {"op": [{"body": False, "name": "param", "required": False, "type": "number"}]},
                lambda param=None: param,
                {},
                None,
            ),
            (
                {"op": [{"body": False, "name": "param", "required": True, "type": "number"}]},
                lambda param: param,
                {"param": 1},
                1,
            ),
            (
                {
                    "op": [
                        {"body": False, "name": "param", "required": True, "type": "number"},
                        {"body": False, "name": "param2", "required": True, "type": "number"},
                    ]
                },
                lambda param, param2: [param, param2],
                {"param": 1, "param2": 2},
                [1, 2],
            ),
            ({"op": []}, lambda: True, {}, True),
        ],
    )
    def test_args(self, mocker, model, func, kwargs, expected):
        mocker.patch("pcluster.cli.model.get_function_from_name", return_value=func)
        model = _gen_model(model)
        pcluster._add_functions(model, pcluster)  # pylint: disable=protected-access
        assert_that(pcluster.op(**kwargs)).is_equal_to(expected)

    @pytest.mark.parametrize(
        "model, func, kwargs",
        [
            (
                {
                    "op": [
                        {"body": False, "name": "param", "required": True, "type": "number"},
                        {"body": True, "name": "body_param", "required": False, "type": "number"},
                    ]
                },
                lambda body, param=None: [body, param],
                {"param_extra": 3},
            ),
            (
                {
                    "op": [
                        {"body": False, "name": "param", "required": True, "type": "number"},
                        {"body": True, "name": "body_param", "required": False, "type": "number"},
                    ]
                },
                lambda body, param=None: [body, param],
                {"body_param": 2, "param_extra": 3},
            ),
            (
                {"op": [{"body": False, "name": "param", "required": True, "type": "number"}]},
                lambda param: param,
                {"param_extra": 1},
            ),
            ({"op": [{"body": False, "name": "param", "required": True, "type": "number"}]}, lambda param: param, {}),
        ],
    )
    def test_args_missing(self, mocker, model, func, kwargs):
        mocker.patch("pcluster.cli.model.get_function_from_name", return_value=func)
        model = _gen_model(model)
        pcluster._add_functions(model, pcluster)  # pylint: disable=protected-access

        # flake8: noqa
        with pytest.raises(TypeError) as exc_info:
            pcluster.op(**kwargs)
        assert_that(str(exc_info.value)).starts_with("<op> missing required arguments")

    @pytest.mark.parametrize(
        "model, func, kwargs",
        [
            (
                {
                    "op": [
                        {"body": False, "name": "param", "required": True, "type": "number"},
                        {"body": True, "name": "body_param", "required": False, "type": "number"},
                    ]
                },
                lambda body, param=None: [body, param],
                {"param": 1, "body_param": 2, "param_extra": 3},
            ),
            (
                {
                    "op": [
                        {"body": False, "name": "param", "required": True, "type": "number"},
                        {"body": True, "name": "body_param", "required": False, "type": "number"},
                    ]
                },
                lambda body, param=None: [body, param],
                {"param": 1, "param_extra": 3},
            ),
            (
                {"op": [{"body": False, "name": "param", "required": False, "type": "number"}]},
                lambda param=None: param,
                {"param": 1, "param_extra": 2},
            ),
            (
                {"op": [{"body": False, "name": "param", "required": False, "type": "number"}]},
                lambda param=None: param,
                {"param_extra": 1},
            ),
            (
                {
                    "op": [
                        {"body": False, "name": "param", "required": True, "type": "number"},
                        {"body": False, "name": "param2", "required": True, "type": "number"},
                    ]
                },
                lambda param, param2: [param, param2],
                {"param": 1, "param2": 2, "param_extra": 3},
            ),
            ({"op": []}, lambda: True, {"param_extra": 2}),
        ],
    )
    def test_args_unexcpected(self, mocker, model, func, kwargs):
        mocker.patch("pcluster.cli.model.get_function_from_name", return_value=func)
        model = _gen_model(model)
        pcluster._add_functions(model, pcluster)  # pylint: disable=protected-access
        with pytest.raises(TypeError) as exc_info:
            pcluster.op(**kwargs)
        assert_that(str(exc_info.value)).starts_with("<op> got unexpected arguments")

    @pytest.mark.parametrize(
        "type_, input_, expected",
        [
            ({"type": "number"}, 1.0, 1.0),
            ({"type": "number"}, 0, 0.0),
            ({"type": "number"}, "0.0", 0.0),
            ({"type": "integer"}, 0, 0),
            ({"type": "integer"}, "0", 0),
            ({"type": "boolean"}, "True", True),
            ({"type": "boolean"}, "False", False),
            ({"type": "boolean"}, "true", True),
            ({"type": "boolean"}, "false", False),
            ({"type": "boolean"}, True, True),
            ({"type": "boolean"}, False, False),
            ({"type": "string"}, "asdf", "asdf"),
            ({"type": "string", "pattern": "^(ALL|type:[A-Za-z0-9]+)$"}, "ALL", "ALL"),
            ({"type": "string", "pattern": "^(ALL|type:[A-Za-z0-9]+)$"}, "type:ASDF", "type:ASDF"),
            ({"type": "file"}, {"a": 1, "b": [2, 3]}, "a: 1\nb:\n- 2\n- 3\n"),
            ({"type": "file"}, "filename", "filedata"),
        ],
    )
    def test_parameter_checks(self, mocker, type_, input_, expected):
        mocker.patch("pcluster.cli.model.get_function_from_name", return_value=lambda x: x)
        mocker.patch("pcluster.cli.entrypoint.read_file", return_value="filedata")
        model = _gen_model({"op": [{"name": "x", "required": True, "body": False, **type_}]})
        pcluster._add_functions(model, pcluster)  # pylint: disable=protected-access
        assert_that(pcluster.op(x=input_)).is_equal_to(expected)

    @pytest.mark.parametrize(
        "type_, input_",
        [
            ({"type": "number"}, "a"),
            ({"type": "number"}, lambda: True),
            ({"type": "number"}, {"a": 0}),
            ({"type": "integer"}, "4.5"),
            ({"type": "integer"}, "a"),
            ({"type": "integer"}, lambda: True),
            ({"type": "integer"}, {"a": 0}),
            ({"type": "boolean"}, "a"),
            ({"type": "boolean"}, "4.5"),
            ({"type": "boolean"}, "a"),
            ({"type": "boolean"}, lambda: True),
            ({"type": "boolean"}, {"a": 0}),
        ],
    )
    def test_parameter_invalid_type(self, mocker, type_, input_):
        mocker.patch("pcluster.cli.model.get_function_from_name", return_value=lambda x: x)
        model = _gen_model({"op": [{"name": "x", "required": True, "body": False, **type_}]})
        pcluster._add_functions(model, pcluster)  # pylint: disable=protected-access
        with pytest.raises((ParameterException, TypeError)) as exc_info:
            pcluster.op(x=input_)

    @pytest.mark.parametrize(
        "type_, input_",
        [
            ({"type": "string", "pattern": "^(ALL|type:[A-Za-z0-9]+)$"}, "ALL|"),
            ({"type": "string", "pattern": "^(ALL|type:[A-Za-z0-9]+)$"}, "type"),
            ({"type": "string", "pattern": "^(ALL|type:[A-Za-z0-9]+)$"}, "type:"),
            ({"type": "string", "pattern": "^(ALL|type:[A-Za-z0-9]+)$"}, "type:-"),
        ],
    )
    def test_parameter_invalid_regex(self, mocker, type_, input_):
        mocker.patch("pcluster.cli.model.get_function_from_name", return_value=lambda x: x)
        model = _gen_model({"op": [{"name": "x", "required": True, "body": False, **type_}]})
        pcluster._add_functions(model, pcluster)  # pylint: disable=protected-access
        # with pytest.raises( (ParameterException, TypeError) ) as exc_info:
        with pytest.raises(ParameterException) as exc_info:
            pcluster.op(x=input_)
