#  Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
#  with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
#  or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
#  OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
#  limitations under the License.
import pytest
from assertpy import assert_that


class TestDescribeClusterInstancesCommand:
    def test_helper(self, test_datadir, run_cli, assert_out_err):
        command = ["pcluster", "describe-cluster-instances", "--help"]
        run_cli(command, expect_failure=False)

        assert_out_err(
            expected_out=(test_datadir / "pcluster-help.txt").read_text().strip(),
            expected_err="",
        )

    @pytest.mark.parametrize(
        "args, error_message",
        [
            ([""], "error: the following arguments are required: --cluster-name"),
            (
                ["--cluster-name"],
                "error: argument --cluster-name: expected one argument",
            ),
            (
                ["--cluster-name", "cluster", "--invalid"],
                "Invalid arguments ['--invalid']",
            ),
            (
                ["--cluster-name", "cluster", "--node-type", "invalid"],
                "error: argument --node-type: invalid choice: 'invalid' (choose from 'HEAD', 'COMPUTE')",
            ),
            (
                ["--cluster-name", "cluster", "--region", "eu-west-"],
                "Bad Request: invalid or unsupported region 'eu-west-'",
            ),
        ],
    )
    def test_invalid_args(self, args, error_message, run_cli, capsys):
        command = ["pcluster", "describe-cluster-instances"] + args
        run_cli(command, expect_failure=True)

        out, err = capsys.readouterr()
        assert_that(out + err).contains(error_message)
