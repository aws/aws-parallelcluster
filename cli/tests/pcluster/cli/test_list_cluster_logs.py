#  Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
#  with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
#  or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
#  OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
#  limitations under the License.
import re
import time

import pytest
from assertpy import assert_that

BASE_COMMAND = ["pcluster", "list-cluster-logs"]
REQUIRED_ARGS = {"cluster_name": "clustername"}


class TestListClusterLogsCommand:
    def test_helper(self, test_datadir, run_cli, assert_out_err):
        command = BASE_COMMAND + ["--help"]
        run_cli(command, expect_failure=False)

        assert_out_err(expected_out=(test_datadir / "pcluster-help.txt").read_text().strip(), expected_err="")

    @pytest.mark.parametrize(
        "args, error_message",
        [({}, "the following arguments are required: cluster_name")],
    )
    def test_required_args(self, args, error_message, run_cli, capsys):
        command = BASE_COMMAND + self._build_cli_args(args)
        run_cli(command, expect_failure=True)

        out, err = capsys.readouterr()
        assert_that(out + err).contains(error_message)

    @pytest.mark.parametrize(
        "args, error_message",
        [
            ({"filters": "Name=wrong,Value=test"}, "filters parameter must be in the form"),
            ({"filters": "private-ip-address=test"}, "filters parameter must be in the form"),
        ],
    )
    def test_invalid_args(self, args, error_message, run_cli, capsys):
        command = BASE_COMMAND + self._build_cli_args({**REQUIRED_ARGS, **args})
        run_cli(command, expect_failure=True)

        out, err = capsys.readouterr()
        assert_that(out + err).contains(error_message)

    @pytest.mark.parametrize(
        "args",
        [{}, {"filters": "Name=private-ip-address,Values=10.10.10.10"}],
        ids=["required", "all"],
    )
    def test_execute(self, mocker, capsys, set_env, run_cli, args):
        mocked_result = [
            {
                "logStreamName": "ip-10-0-0-184.i-085e4292f0f85bb5b.cloud-init",
                "firstEventTimestamp": 1623071664893,
                "lastEventTimestamp": 1623071692892,
            },
            {
                "logStreamName": "ip-10-0-0-184.i-085e4292f0f85bb5b.cloud-init-output",
                "firstEventTimestamp": 1623071664892,
                "lastEventTimestamp": 1623071692892,
            },
        ]
        list_logs_mock = mocker.patch(
            "pcluster.api.pcluster_api.PclusterApi.list_cluster_logs", return_value=mocked_result
        )
        set_env("AWS_DEFAULT_REGION", "us-east-1")

        command = BASE_COMMAND + self._build_cli_args({**REQUIRED_ARGS, **args})
        run_cli(command, expect_failure=False)

        out_err = capsys.readouterr()
        expected_out = [
            "ip-10-0-0-184.i-085e4292f0f85bb5b.cloud-init",
            "ip-10-0-0-184.i-085e4292f0f85bb5b.cloud-init-output",
            time.strftime("%d %b %Y %H:%M:%S %Z", time.localtime(1623071664892 / 1000)),
            time.strftime("%d %b %Y %H:%M:%S %Z", time.localtime(1623071692892 / 1000)),
        ]
        for item in expected_out:
            assert_that(out_err.out.strip()).contains(item)
        assert_that(list_logs_mock.call_args).is_length(2)

        # verify arguments
        expected_params = {"cluster_name": None, "region": r"[\w-]+", "filters": None}
        expected_params.update(REQUIRED_ARGS)
        expected_params.update(args)
        self._check_params(list_logs_mock, expected_params, args)

    @staticmethod
    def _build_cli_args(args):
        cli_args = []
        if "cluster_name" in args:
            cli_args.extend([args["cluster_name"]])
        if "filters" in args:
            cli_args.extend(["--filters", args["filters"]])
        return cli_args

    @staticmethod
    def _check_params(list_logs_mock, expected_params, args):
        for param_key, expected_value in expected_params.items():
            call_param = list_logs_mock.call_args[1].get(param_key)
            check_regex = False

            if param_key not in args and isinstance(expected_value, str):
                check_regex = True

            if check_regex:
                assert_that(
                    re.search(expected_value, call_param), f"Expected: {expected_value}, value is: {call_param}"
                ).is_true()
            else:
                assert_that(call_param, f"Expected: {expected_value}, value is: {call_param}").is_equal_to(
                    expected_value
                )
