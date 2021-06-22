#  Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
#  with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
#  or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
#  OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
#  limitations under the License.
import os
import re
import time

import pytest
from assertpy import assert_that

from pcluster.models.common_resources import LogStream

BASE_COMMAND = ["pcluster", "get-cluster-log-events"]
REQUIRED_ARGS = {"cluster_name": "clustername", "log_stream_name": "log-stream-name"}


class TestGetClusterLogEventsCommand:
    def test_helper(self, test_datadir, run_cli, assert_out_err):
        command = BASE_COMMAND + ["--help"]
        run_cli(command, expect_failure=False)

        assert_out_err(expected_out=(test_datadir / "pcluster-help.txt").read_text().strip(), expected_err="")

    @pytest.mark.parametrize(
        "args, error_message",
        [({}, "the following arguments are required: cluster_name, --log-stream-name")],
    )
    def test_required_args(self, args, error_message, run_cli, capsys):
        command = BASE_COMMAND + self._build_cli_args(args)
        run_cli(command, expect_failure=True)

        out, err = capsys.readouterr()
        assert_that(out + err).contains(error_message)

    @pytest.mark.parametrize(
        "args, error_message",
        [
            ({"start_time": "wrong"}, "Start time and end time filters must be in the ISO 8601 format"),
            ({"end_time": "1622802790248"}, "Start time and end time filters must be in the ISO 8601 format"),
            ({"head": "wrong"}, "invalid int value"),
            ({"tail": "wrong"}, "invalid int value"),
            ({"stream_period": "wrong"}, "invalid int value"),
        ],
    )
    def test_invalid_args(self, args, error_message, run_cli, capsys):
        command = BASE_COMMAND + self._build_cli_args({**REQUIRED_ARGS, **args})
        run_cli(command, expect_failure=True)

        out, err = capsys.readouterr()
        assert_that(out + err).contains(error_message)

    @pytest.mark.parametrize(
        "args, expected_error",
        [
            # errors
            ({"tail": "2", "head": "5"}, "options cannot be set at the same time"),
            ({"stream": True, "next_token": "f/123456"}, "options cannot be set at the same time"),
            ({"stream": True, "head": "5"}, "options cannot be set at the same time"),
            ({"stream_period": "5"}, "can be used only with"),
            # success
            ({}, None),
            ({"tail": "6", "start_time": "2021-06-02", "end_time": "2021-06-02"}, None),
            (
                {
                    "head": "6",
                    "start_time": "2021-06-02T15:55:10+02:00",
                    "end_time": "2021-06-02T17:55:10+02:00",
                    "next_token": "f/1234",
                },
                None,
            ),
            ({"tail": "2", "stream": True, "stream_period": "6"}, None),
        ],
    )
    def test_execute(self, mocker, capsys, set_env, run_cli, test_datadir, assert_out_err, args, expected_error):
        mocked_result = [
            LogStream(
                "logstream",
                {
                    "events": [
                        {
                            "timestamp": 1622802790248,
                            "message": (
                                "2021-06-04 10:33:10,248 [DEBUG] CloudFormation client initialized "
                                "with endpoint https://cloudformation.eu-west-1.amazonaws.com"
                            ),
                            "ingestionTime": 1622802842382,
                        },
                        {
                            "timestamp": 1622802790248,
                            "message": (
                                "2021-06-04 10:33:10,248 [DEBUG] Describing resource HeadNodeLaunchTemplate in "
                                "stack test22"
                            ),
                            "ingestionTime": 1622802842382,
                        },
                        {
                            "timestamp": 1622802790390,
                            "message": (
                                "2021-06-04 10:33:10,390 [INFO] -----------------------Starting build"
                                "-----------------------"
                            ),
                            "ingestionTime": 1622802842382,
                        },
                    ],
                    "nextForwardToken": "f/3618",
                    "nextBackwardToken": "b/3619",
                    "ResponseMetadata": {},
                },
            )
        ] * 2 + [LogStream("logstream", {})]
        get_cluster_log_events_mock = mocker.patch(
            "pcluster.cli.commands.cluster.Cluster.get_log_events", side_effect=mocked_result
        )
        set_env("AWS_DEFAULT_REGION", "us-east-1")
        mocker.patch("pcluster.cli.commands.cluster.time.sleep")  # so we don't actually have to wait

        command = BASE_COMMAND + self._build_cli_args({**REQUIRED_ARGS, **args})

        if expected_error:
            run_cli(command, expect_failure=True, expect_message=expected_error)
        else:
            os.environ["TZ"] = "Europe/London"
            time.tzset()
            run_cli(command, expect_failure=False)
            expected_output = "pcluster-out-stream.txt" if args.get("stream") else "pcluster-out.txt"
            assert_out_err(expected_out=(test_datadir / expected_output).read_text().strip(), expected_err="")
            assert_that(get_cluster_log_events_mock.call_args).is_length(2)

            # verify arguments
            expected_params = {
                "log_stream_name": "log-stream-name",
                "start_time": args.get("start_time", None),
                "end_time": args.get("end_time", None),
                "start_from_head": True if args.get("head") else False,
                "limit": args.get("head") or args.get("tail") or None,
                "next_token": "f/3618" if args.get("stream") else args.get("next_token", None),
            }
            self._check_params(get_cluster_log_events_mock, expected_params, args)

    @staticmethod
    def _build_cli_args(args):
        cli_args = []
        if "cluster_name" in args:
            cli_args.extend([args["cluster_name"]])
        if "log_stream_name" in args:
            cli_args.extend(["--log-stream-name", args["log_stream_name"]])
        if "start_time" in args:
            cli_args.extend(["--start-time", args["start_time"]])
        if "end_time" in args:
            cli_args.extend(["--end-time", args["end_time"]])
        if "head" in args:
            cli_args.extend(["--head", args["head"]])
        if "tail" in args:
            cli_args.extend(["--tail", args["tail"]])
        if "next_token" in args:
            cli_args.extend(["--next-token", args["next_token"]])
        if "stream" in args:
            cli_args.extend(["--stream"])
        if "stream_period" in args:
            cli_args.extend(["--stream-period", args["stream_period"]])
        return cli_args

    @staticmethod
    def _check_params(list_logs_mock, expected_params, args):
        for param_key, expected_value in expected_params.items():
            for index in range(1, len(list_logs_mock.call_args)):
                call_param = list_logs_mock.call_args[index].get(param_key)

                if param_key != "limit" and param_key not in args and isinstance(expected_value, str):
                    assert_that(
                        re.search(expected_value, call_param), f"Expected: {expected_value}, value is: {call_param}"
                    ).is_true()
                else:
                    assert_that(str(call_param), f"Expected: {expected_value}, value is: {call_param}").is_equal_to(
                        str(expected_value)
                    )
