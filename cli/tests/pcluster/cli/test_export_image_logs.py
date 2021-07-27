#  Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
#  with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
#  or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
#  OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
#  limitations under the License.

import pytest
from assertpy import assert_that

from pcluster.api.models import ExportImageLogsResponseContent
from pcluster.cli.entrypoint import run
from pcluster.utils import to_kebab_case
from tests.utils import wire_translate

BASE_COMMAND = ["pcluster", "export-image-logs"]
REQUIRED_ARGS = {"image_id": "id", "bucket": "bucketname"}


class TestExportImageLogsCommand:
    def test_helper(self, test_datadir, run_cli, assert_out_err):
        command = BASE_COMMAND + ["--help"]
        run_cli(command, expect_failure=False)

        assert_out_err(expected_out=(test_datadir / "pcluster-help.txt").read_text().strip(), expected_err="")

    @pytest.mark.parametrize(
        "args, error_message",
        [({"output": "path"}, "the following arguments are required: --image-id, --bucket")],
    )
    def test_required_args(self, args, error_message, run_cli, capsys):
        command = BASE_COMMAND + self._build_cli_args(args)
        run_cli(command, expect_failure=True)

        out, err = capsys.readouterr()
        assert_that(out + err).contains(error_message)

    @pytest.mark.parametrize(
        "args",
        [
            {},
            {"bucket": "bucket-name"},
            {"bucket": "bucket-name", "region": "us-east-1"},
            {"bucket": "bucket-name", "bucket_prefix": "test"},
            {
                "bucket": "bucket-name",
                "bucket_prefix": "test",
                "start_time": "2021-06-02T15:55:10+02:00",
                "end_time": "2021-06-07",
            },
            {
                "bucket": "bucket-name",
                "bucket_prefix": "test",
                "start_time": "2021-06-02T15:55:10+02:00",
                "end_time": "2021-06-07",
            },
        ],
    )
    def test_execute(self, mocker, set_env, args):
        set_env("AWS_DEFAULT_REGION", "us-east-1")
        response_dict = {
            "logEventsUrl": "s3://log-events-url",
            "logEventsTaskId": "log-events-task-id",
            "stackEventsUrl": "s3://",
            "message": "Success.",
        }
        response = ExportImageLogsResponseContent().from_dict(response_dict)

        export_logs_mock = mocker.patch(
            "pcluster.api.controllers.image_logs_controller.export_image_logs", return_value=response, autospec=True
        )

        command = ["export-image-logs"] + self._build_cli_args({**REQUIRED_ARGS, **args})
        out = run(command)

        assert_that(export_logs_mock.call_args).is_length(2)
        expected = wire_translate(out)
        assert_that(out).is_equal_to(expected)

        # verify arguments
        expected_params = {"bucket_prefix": None, "start_time": None, "end_time": None, "region": None}
        expected_params.update(REQUIRED_ARGS)
        expected_params.update(args)
        export_logs_mock.assert_called_with(**expected_params)

    @staticmethod
    def _build_cli_args(args):
        cli_args = []
        for k, val in args.items():
            val = " ".join(val) if k == "filters" else val
            cli_args.extend([f"--{to_kebab_case(k)}", val])
        return cli_args
