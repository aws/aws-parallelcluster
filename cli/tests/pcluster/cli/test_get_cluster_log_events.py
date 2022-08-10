#  Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
#  with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
#  or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
#  OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
#  limitations under the License.
import json
import os
import time

import pytest
from assertpy import assert_that

from pcluster.cli.entrypoint import run
from pcluster.models.common import LogStream
from pcluster.utils import to_kebab_case, to_utc_datetime
from tests.pcluster.test_utils import FAKE_NAME

BASE_COMMAND = ["pcluster", "get-cluster-log-events", "--region", "us-east-1"]
REQUIRED_ARGS = {"cluster_name": FAKE_NAME, "log_stream_name": "log-stream-name"}


class TestGetClusterLogEventsCommand:
    def test_helper(self, test_datadir, run_cli, assert_out_err):
        command = BASE_COMMAND + ["--help"]
        run_cli(command, expect_failure=False)

        assert_out_err(expected_out=(test_datadir / "pcluster-help.txt").read_text().strip(), expected_err="")

    @pytest.mark.parametrize(
        "args, error_message", [({}, "the following arguments are required: -n/--cluster-name, --log-stream-name")]
    )
    def test_required_args(self, args, error_message, run_cli, capsys):
        command = BASE_COMMAND + self._build_cli_args(args)
        run_cli(command, expect_failure=True)

        out, err = capsys.readouterr()
        assert_that(out + err).contains(error_message)

    @pytest.mark.parametrize(
        "args, error_message",
        [
            ({"start_time": "wrong"}, "start_time filter must be in the ISO 8601 format"),
            ({"end_time": "1622802790248"}, "end_time filter must be in the ISO 8601 format"),
            ({"start_from_head": "wrong"}, "expected 'boolean' for parameter 'start-from-head'"),
            ({"limit": "wrong"}, "expected 'int' for parameter 'limit'"),
            (
                {"start_time": "2021-06-02", "end_time": "2021-06-02"},
                "start_time filter must be earlier than end_time filter.",
            ),
        ],
    )
    def test_invalid_args(self, args, error_message, run_cli, capsys):
        command = BASE_COMMAND + self._build_cli_args({**REQUIRED_ARGS, **args})
        run_cli(command, expect_failure=True)

        out, err = capsys.readouterr()
        assert_that(out + err).contains(error_message)

    @pytest.mark.parametrize(
        "args",
        [
            ({}),
            ({"limit": "6", "start_time": "2021-06-02", "end_time": "2021-06-03"}),
            (
                {
                    "start_from_head": "true",
                    "limit": "6",
                    "start_time": "2021-06-02T15:55:10+02:00",
                    "end_time": "2021-06-02T17:56:10+02:00",
                    "next_token": "f/1234",
                }
            ),
        ],
    )
    def test_execute(self, mocker, mock_cluster_stack, set_env, test_datadir, args):
        mocked_result = [
            LogStream(
                FAKE_NAME,
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
        ] * 2 + [LogStream(FAKE_NAME, "logstream", {})]
        get_cluster_log_events_mock = mocker.patch(
            "pcluster.api.controllers.cluster_logs_controller.Cluster.get_log_events", side_effect=mocked_result
        )

        set_env("AWS_DEFAULT_REGION", "us-east-1")
        mock_cluster_stack()
        base_args = ["get-cluster-log-events"]
        command = base_args + self._build_cli_args({**REQUIRED_ARGS, **args})

        os.environ["TZ"] = "Europe/London"
        time.tzset()
        out = run(command)

        expected = json.loads((test_datadir / "pcluster-out.txt").read_text().strip())
        assert_that(expected).is_equal_to(out)
        assert_that(get_cluster_log_events_mock.call_args).is_length(2)

        if args.get("limit", None):
            limit_val = get_cluster_log_events_mock.call_args[1].get("limit")
            assert_that(limit_val).is_type_of(int)

        # verify arguments
        kwargs = {
            "log_stream_name": "log-stream-name",
            "start_time": args.get("start_time", None) and to_utc_datetime(args["start_time"]),
            "end_time": args.get("end_time", None) and to_utc_datetime(args["end_time"]),
            "start_from_head": True if args.get("start_from_head", None) else None,
            "limit": int(args["limit"]) if args.get("limit", None) else None,
            "next_token": args.get("next_token", None),
        }
        get_cluster_log_events_mock.assert_called_with(**kwargs)

    @staticmethod
    def _build_cli_args(args):
        cli_args = []
        for k, val in args.items():
            cli_args.extend([f"--{to_kebab_case(k)}", val])
        return cli_args
