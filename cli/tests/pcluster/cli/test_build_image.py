#  Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
#  with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
#  or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
#  OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
#  limitations under the License.
import itertools

import pytest
from assertpy import assert_that


class TestBuildImageCommand:
    def test_helper(self, test_datadir, run_cli, assert_out_err):
        command = ["pcluster", "build-image", "--help"]
        run_cli(command, expect_failure=False)

        assert_out_err(
            expected_out=(test_datadir / "pcluster-help.txt").read_text().strip(),
            expected_err="",
        )

    @pytest.mark.parametrize(
        "args, error_message",
        [
            ({}, "error: the following arguments are required: --image-configuration, --id"),
            (
                {"--image-configuration": None},
                "error: argument --image-configuration: expected one argument",
            ),
            (
                {"--id": None},
                "error: argument --id: expected one argument",
            ),
            (
                {"--image-configuration": "file", "--id": "id", "--invalid": None},
                "Invalid arguments ['--invalid']",
            ),
            (
                {"--image-configuration": "file", "--id": "id", "--region": "eu-west-"},
                "Bad Request: invalid or unsupported region 'eu-west-'",
            ),
        ],
    )
    def test_invalid_args(self, args, error_message, run_cli, capsys, test_datadir):
        if args.get("--image-configuration"):
            args["--image-configuration"] = str(test_datadir / "file")
        args = self._build_args(args)
        command = ["pcluster", "build-image"] + args
        run_cli(command, expect_failure=True)

        out, err = capsys.readouterr()
        assert_that(out + err).contains(error_message)

    def _build_args(self, args):
        args = [[k, v] if v is not None else [k] for k, v in args.items()]
        return list(itertools.chain(*args))
