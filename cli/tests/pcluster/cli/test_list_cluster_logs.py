#  Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
#  with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
#  or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
#  OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
#  limitations under the License.
import re
from datetime import datetime

import pytest
from assertpy import assert_that
from dateutil import tz

from pcluster.models.common_resources import Logs

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
            ({"filters": "private-dns-name=test"}, "filters parameter must be in the form"),
        ],
    )
    def test_invalid_args(self, args, error_message, run_cli, capsys):
        command = BASE_COMMAND + self._build_cli_args({**REQUIRED_ARGS, **args})
        run_cli(command, expect_failure=True)

        out, err = capsys.readouterr()
        assert_that(out + err).contains(error_message)

    @pytest.mark.parametrize(
        "args, ",
        [
            {},
            {"filters": "Name=private-dns-name,Values=ip-10-10-10-10", "next_token": "123"},
            {"filters": "Name=node-type,Values=HeadNode"},
        ],
    )
    def test_execute(self, mocker, capsys, set_env, run_cli, args):
        logs = Logs()
        logs.cw_log_streams = {
            "logStreams": [
                {
                    "logStreamName": "ip-10-0-0-102.i-0717e670ad2549e72.cfn-init",
                    "creationTime": 1622802842228,
                    "firstEventTimestamp": 1622802790248,
                    "lastEventTimestamp": 1622802893126,
                    "lastIngestionTime": 1622802903119,
                    "uploadSequenceToken": "4961...",
                    "arn": (
                        "arn:aws:logs:eu-west-1:111:log-group:/aws/parallelcluster/"
                        "test22-202106041223:log-stream:ip-10-0-0-102.i-0717e670ad2549e72.cfn-init"
                    ),
                    "storedBytes": 0,
                },
                {
                    "logStreamName": "ip-10-0-0-102.i-0717e670ad2549e72.chef-client",
                    "creationTime": 1622802842207,
                    "firstEventTimestamp": 1622802837114,
                    "lastEventTimestamp": 1622802861226,
                    "lastIngestionTime": 1622802897558,
                    "uploadSequenceToken": "4962...",
                    "arn": (
                        "arn:aws:logs:eu-west-1:111:log-group:/aws/parallelcluster/"
                        "test22-202106041223:log-stream:ip-10-0-0-102.i-0717e670ad2549e72.chef-client"
                    ),
                    "storedBytes": 0,
                },
            ],
            "nextToken": "123-456",
            "ResponseMetadata": {},
        }
        logs.stack_log_streams = [
            {
                "Stack Events Stream": "cloudformation-stack-events",
                "Cluster Creation Time": "2021-06-04T10:23:20+00:00",
                "Last Update Time": "2021-06-04T10:23:20+00:00",
            }
        ]

        list_logs_mock = mocker.patch("pcluster.cli.commands.cluster.Cluster.list_logs", return_value=logs)
        set_env("AWS_DEFAULT_REGION", "us-east-1")

        command = BASE_COMMAND + self._build_cli_args({**REQUIRED_ARGS, **args})
        run_cli(command, expect_failure=False)

        out_err = capsys.readouterr()
        # cfn stack events are not displayed if next-token is passed
        expected_out = [] if "next_token" in args else ["cloudformation-stack-events", "2021-06-04T10:23:20+00:00"]
        expected_out += [
            "ip-10-0-0-102.i-0717e670ad2549e72.cfn-init",
            self._timestamp_to_date(1622802790248),
            self._timestamp_to_date(1622802893126),
            "ip-10-0-0-102.i-0717e670ad2549e72.chef-client",
            self._timestamp_to_date(1622802837114),
            self._timestamp_to_date(1622802861226),
        ]
        for item in expected_out:
            assert_that(out_err.out.strip()).contains(item)
        assert_that(list_logs_mock.call_args).is_length(2)

        # verify arguments
        expected_params = {"filters": None, "next_token": None}
        expected_params.update(args)
        self._check_params(list_logs_mock, expected_params, args)

    @staticmethod
    def _build_cli_args(args):
        cli_args = []
        if "cluster_name" in args:
            cli_args.extend([args["cluster_name"]])
        if "filters" in args:
            cli_args.extend(["--filters", args["filters"]])
        if "next_token" in args:
            cli_args.extend(["--next-token", args["next_token"]])
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

    @staticmethod
    def _timestamp_to_date(timestamp):
        return datetime.fromtimestamp(timestamp / 1000, tz=tz.tzlocal()).replace(microsecond=0).isoformat()
