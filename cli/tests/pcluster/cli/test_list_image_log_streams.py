#  Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
#  with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
#  or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
#  OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
#  limitations under the License.

import pytest
from assertpy import assert_that

from pcluster.cli.entrypoint import run
from pcluster.models.common import LogStreams
from pcluster.utils import to_iso_timestr, to_kebab_case, to_utc_datetime

BASE_COMMAND = ["pcluster", "list-image-log-streams", "--region", "eu-west-1"]
REQUIRED_ARGS = {"image_id": "id"}


class TestListImageLogStreamsCommand:
    def test_helper(self, test_datadir, run_cli, assert_out_err):
        command = BASE_COMMAND + ["--help"]
        run_cli(command, expect_failure=False)

        assert_out_err(expected_out=(test_datadir / "pcluster-help.txt").read_text().strip(), expected_err="")

    @pytest.mark.parametrize("args, error_message", [({}, "the following arguments are required: -i/--image-id")])
    def test_required_args(self, args, error_message, run_cli, capsys):
        command = BASE_COMMAND + self._build_cli_args(args)
        run_cli(command, expect_failure=True)

        out, err = capsys.readouterr()
        assert_that(out + err).contains(error_message)

    @pytest.mark.parametrize("args", [{}, {"next_token": "123"}])
    def test_execute(self, mocker, set_env, args):
        logs = LogStreams()
        logs.log_streams = [
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
        ]

        logs.next_token = "123-456"

        list_log_streams_mock = mocker.patch(
            "pcluster.api.controllers.image_logs_controller.ImageBuilder.list_log_streams", return_value=logs
        )
        set_env("AWS_DEFAULT_REGION", "us-east-1")

        base_args = ["list-image-log-streams"]
        command = base_args + self._build_cli_args({**REQUIRED_ARGS, **args})

        out = run(command)
        # cfn stack events are not displayed if next-token is passed
        expected_out = [
            {
                "logStreamName": "ip-10-0-0-102.i-0717e670ad2549e72.cfn-init",
                "firstEventTimestamp": to_iso_timestr(to_utc_datetime(1622802790248)),
                "lastEventTimestamp": to_iso_timestr(to_utc_datetime(1622802893126)),
            },
            {
                "logStreamName": "ip-10-0-0-102.i-0717e670ad2549e72.chef-client",
                "firstEventTimestamp": to_iso_timestr(to_utc_datetime(1622802837114)),
                "lastEventTimestamp": to_iso_timestr(to_utc_datetime(1622802861226)),
            },
        ]
        assert_that(out["nextToken"]).is_equal_to(logs.next_token)
        for i in range(len(logs.log_streams)):
            select_keys = {"logStreamName", "firstEventTimestamp", "lastEventTimestamp"}
            out_select = {k: v for k, v in out["logStreams"][i].items() if k in select_keys}
            assert_that(out_select).is_equal_to(expected_out[i])
        assert_that(list_log_streams_mock.call_args).is_length(2)

        # verify arguments
        kwargs = {"next_token": None}
        kwargs.update(args)
        list_log_streams_mock.assert_called_with(**kwargs)

    @staticmethod
    def _build_cli_args(args):
        cli_args = []
        for k, val in args.items():
            val = " ".join(val) if k == "filters" else val
            cli_args.extend([f"--{to_kebab_case(k)}", val])
        return cli_args
