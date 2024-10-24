#  Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
#  with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
#  or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
#  OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
#  limitations under the License.

import os.path

import pytest
from assertpy import assert_that, fail

from pcluster.api.errors import BadRequestException
from pcluster.cli.entrypoint import run
from pcluster.cli.exceptions import APIOperationException
from pcluster.constants import Operation
from pcluster.utils import to_kebab_case, to_utc_datetime

BASE_COMMAND = ["pcluster", "export-image-logs"]
REQUIRED_ARGS = {"image-id": "id", "bucket": "bucketname"}


class TestExportImageLogsCommand:
    def test_helper(self, test_datadir, run_cli, assert_out_err):
        command = BASE_COMMAND + ["--help"]
        run_cli(command, expect_failure=False)

        assert_out_err(expected_out=(test_datadir / "pcluster-help.txt").read_text().strip(), expected_err="")

    @pytest.mark.parametrize(
        "args, error_message",
        [({"output_file": "path"}, "the following arguments are required: -i/--image-id")],
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
            {"output_file": "output-path"},
            {"bucket": "bucket-name", "bucket_prefix": "test", "keep_s3_objects": True},
            {
                "output_file": "output-path",
                "bucket": "bucket-name",
                "bucket_prefix": "test",
                "keep_s3_objects": True,
                "start_time": "2021-06-02T15:55:10+02:00",
                "end_time": "2021-06-07",
            },
            {
                "output_file": "output-path",
                "bucket": "bucket-name",
                "bucket_prefix": "test",
                "keep_s3_objects": False,
                "start_time": "2021-06-02T15:55:10+02:00",
                "end_time": "2021-06-07",
            },
        ],
    )
    def test_execute(self, mocker, set_env, args):
        mocked_assert_supported_operation = mocker.patch("pcluster.cli.commands.image_logs.assert_supported_operation")
        export_logs_mock = mocker.patch(
            "pcluster.cli.commands.image_logs.ImageBuilder.export_logs",
            return_value=args.get("output_file", "https://u.r.l."),
        )
        set_env("AWS_DEFAULT_REGION", "us-east-1")

        command = ["export-image-logs"] + self._build_cli_args({**REQUIRED_ARGS, **args})
        out = run(command)
        if args.get("output_file") is not None:
            expected = {"path": os.path.realpath(args.get("output_file"))}
        else:
            expected = {"url": "https://u.r.l."}
        assert_that(out).is_equal_to(expected)
        assert_that(export_logs_mock.call_args).is_length(2)

        # verify arguments
        expected_params = {
            "bucket": "bucketname",
            "bucket_prefix": None,
            "keep_s3_objects": False,
            "start_time": None,
            "end_time": None,
        }
        expected_params.update(args)
        expected_params.update(
            {
                "output_file": args.get("output_file") and os.path.realpath(args.get("output_file")),
                "start_time": args.get("start_time") and to_utc_datetime(args["start_time"]),
                "end_time": args.get("end_time") and to_utc_datetime(args["end_time"]),
            }
        )
        export_logs_mock.assert_called_with(**expected_params)
        mocked_assert_supported_operation.assert_called_once()
        mocked_assert_supported_operation.assert_called_with(operation=Operation.EXPORT_IMAGE_LOGS, region="us-east-1")

    @pytest.mark.parametrize("is_operation_supported", [True, False])
    def test_operation_support(self, mocker, set_env, is_operation_supported):
        set_env("AWS_DEFAULT_REGION", "us-east-1")

        mocked_assert_supported_operation = mocker.patch(
            "pcluster.cli.commands.image_logs.assert_supported_operation",
            side_effect=None if is_operation_supported else BadRequestException("ERROR MESSAGE"),
        )

        mocked_export_logs = mocker.patch("pcluster.cli.commands.image_logs.ImageBuilder.export_logs")

        command = ["export-image-logs"] + self._build_cli_args(
            {**REQUIRED_ARGS},
        )

        try:
            run(command)
            if not is_operation_supported:
                fail("Expected to fail due to operation being unsupported.")
        except Exception as exc:
            assert_that(exc).is_instance_of(APIOperationException)
            assert_that(exc.data).is_equal_to(dict(message="Bad Request: ERROR MESSAGE"))

        mocked_assert_supported_operation.assert_called_once()
        mocked_assert_supported_operation.assert_called_with(operation=Operation.EXPORT_IMAGE_LOGS, region="us-east-1")

        if is_operation_supported:
            mocked_export_logs.assert_called_once()
        else:
            mocked_export_logs.assert_not_called()

    @staticmethod
    def _build_cli_args(args):
        cli_args = []
        for k, val in args.items():
            cli_args.extend([f"--{to_kebab_case(k)}", str(val)])
        return cli_args
