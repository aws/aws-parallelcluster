#  Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
#  with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
#  or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
#  OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
#  limitations under the License.

# pylint: disable=W0613
import pytest
from assertpy import assert_that

from pcluster.cli.entrypoint import ParameterException, gen_parser
from pcluster.cli.middleware import queryable


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
        ret = {"body": body}
        ret.update(kwargs)
        return ret

    mocker.patch("pcluster.cli.model.get_function_from_name", return_value=_identity)


class TestCliMIddlware:
    def test_middleware(self, mocker, identity_dispatch):
        def op_middle(func, body, kwargs):
            body["param"] = 0.1
            kwargs["qparam"] = 7
            assert_that(kwargs).contains("body")
            return func(**kwargs)

        mocker.patch("pcluster.cli.entrypoint.middleware_hooks", return_value={"op": op_middle})

        model = _model(
            [
                {"body": False, "name": "qparam", "required": True, "type": "integer"},
                {"body": True, "name": "param", "required": False, "type": "number"},
            ]
        )

        ret = _run_model(model, ["op", "--qparam", "1", "--param", "0.0"])
        assert_that(ret["body"]["param"]).is_equal_to(0.1)
        assert_that(ret["qparam"]).is_equal_to(7)

    def test_query(self, mocker, identity_dispatch):
        def op_middle(func, _body, kwargs):
            return func(kwargs)["body"]

        mocker.patch("pcluster.cli.entrypoint.middleware_hooks", return_value={"op": queryable(op_middle)})

        model = _model(
            [
                {"body": True, "name": "param", "required": False, "type": "integer"},
            ]
        )
        ret = _run_model(model, ["op", "--param", "1", "--query", "body.param"])
        assert_that(ret).is_equal_to(1)

    def test_query_invalid(self, mocker, identity_dispatch):
        def op_middle(func, _body, kwargs):
            return func(kwargs)["body"]

        mocker.patch("pcluster.cli.entrypoint.middleware_hooks", return_value={"op": queryable(op_middle)})

        model = _model(
            [
                {"body": True, "name": "param", "required": False, "type": "integer"},
            ]
        )
        with pytest.raises(ParameterException) as exc_info:
            _run_model(model, ["op", "--param", "1", "--query", "["])
        assert_that(exc_info.value.data).is_equal_to({"message": "Invalid query string.", "query": "["})
