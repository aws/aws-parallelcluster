#  Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
#  with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
#  or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
#  OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
#  limitations under the License.

import pytest
from assertpy import assert_that

from pcluster.cli.entrypoint import ParameterException, gen_parser


def _model(params):
    return {"op": {"func": "", "body_name": "body", "params": params}}


def _run_model(model, params):
    parser, _parser_map = gen_parser(model)
    args, _ = parser.parse_known_args(params)
    del args.__dict__["debug"]
    return args.func(args)


@pytest.fixture
def identity_dispatch(mocker):
    def _identity(body, **kwargs):
        return {"body": body, **kwargs}

    mocker.patch("pcluster.cli.model.get_function_from_name", return_value=_identity)


class TestCliModel:
    @pytest.mark.parametrize("args, expected", [(["op"], None), (["op", "--query-param", "test"], "test")])
    def test_dispatch_query(self, identity_dispatch, args, expected):
        model = _model([{"body": False, "name": "query-param", "required": False, "type": "string"}])
        assert_that(_run_model(model, args)["query_param"]).is_equal_to(expected)

    def test_re_param_validation(self, identity_dispatch):
        model = _model(
            [{"body": True, "name": "string-re", "pattern": "^[a-z]*$", "required": False, "type": "string"}]
        )
        ret = _run_model(model, ["op", "--string-re", "aazz"])
        assert_that(ret["body"]["stringRe"]).is_equal_to("aazz")

    @pytest.mark.parametrize(
        "arg_name, arg, expected",
        [
            ("boolean", "true", True),
            ("boolean", "True", True),
            ("boolean", "TRUE", True),
            ("boolean", "false", False),
            ("boolean", "False", False),
            ("boolean", "FALSE", False),
            ("integer", "0", 0),
            ("integer", "172", 172),
            ("number", "0.7", 0.7),
            ("number", "3", 3.0),
        ],
    )
    def test_param_validation(self, identity_dispatch, arg_name, arg, expected):
        model = _model([{"body": True, "name": arg_name, "required": False, "type": arg_name}])
        ret = _run_model(model, ["op", f"--{arg_name}", arg])["body"][arg_name]
        assert_that(ret).is_equal_to(expected)

    @pytest.mark.parametrize(
        "param",
        [
            ({"type": "boolean"}),
            ({"type": "number"}),
            ({"type": "integer"}),
            ({"type": "string", "pattern": "^[a-z]*$"}),
        ],
    )
    def test_param_errors(self, identity_dispatch, param):
        param.update({"body": True, "name": "param", "required": False})
        model = _model([param])
        with pytest.raises(ParameterException):
            _run_model(model, ["op", "--param", "Z"])

    def test_required(self, identity_dispatch, test_datadir):
        model = _model([{"body": False, "name": "query-param", "required": True, "type": "string"}])
        with pytest.raises(SystemExit):
            _run_model(model, ["op"])

    def test_file(self, identity_dispatch, test_datadir):
        model = _model([{"body": False, "name": "file", "required": True, "type": "file"}])
        path = str(test_datadir / "file.txt")
        ret = _run_model(model, ["op", "--file", path])
        file_data = "asdf\n"
        assert_that(ret["file"]).is_equal_to(file_data)
        path = str(test_datadir / "notfound")
        with pytest.raises(ParameterException):
            _run_model(model, ["op", "--file", path])
