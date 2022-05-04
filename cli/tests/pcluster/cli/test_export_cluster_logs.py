#  Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
#  with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
#  or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
#  OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
#  limitations under the License.

import os.path

import pytest
from assertpy import assert_that

from pcluster.cli.entrypoint import run
from pcluster.utils import to_kebab_case, to_utc_datetime

BASE_COMMAND = ["pcluster", "export-cluster-logs"]
REQUIRED_ARGS = {"cluster-name": "clustername", "bucket": "bucketname"}


class TestExportClusterLogsCommand:
    def test_helper(self, test_datadir, run_cli, assert_out_err):
        command = BASE_COMMAND + ["--help"]
        run_cli(command, expect_failure=False)

        assert_out_err(expected_out=(test_datadir / "pcluster-help.txt").read_text().strip(), expected_err="")

    @pytest.mark.parametrize(
        "args, error_message",
        [({"output_file": "path"}, "the following arguments are required: -n/--cluster-name, --bucket")],
    )
    def test_required_args(self, args, error_message, run_cli, capsys):
        command = BASE_COMMAND + self._build_cli_args(args)
        run_cli(command, expect_failure=True)

        out, err = capsys.readouterr()
        assert_that(out + err).contains(error_message)

    @pytest.mark.parametrize(
        "args, error_message",
        [
            ({"filters": ["Name=wrong,Value=test"]}, "filters parameter must be in the form"),
            ({"filters": ["private-dns-name=test"]}, "filters parameter must be in the form"),
            ({"filters": "private-dns-name=test"}, "filters parameter must be in the form"),
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
            {},
            {"output_file": "output-path"},
            {"bucket": "bucket-name", "keep_s3_objects": True},
            {"bucket": "bucket-name", "bucket_prefix": "test", "keep_s3_objects": True},
            {"filters": "Name=private-dns-name,Values=ip-10-10-10-10"},
            {
                "output_file": "output-path",
                "bucket": "bucket-name",
                "bucket_prefix": "test",
                "keep_s3_objects": True,
                "start_time": "2021-06-02T00:00:00Z",
                "end_time": "2021-06-08T00:00:00Z",
                "filters": "Name=private-dns-name,Values=ip-10-10-10-10",
            },
            {
                "bucket": "bucket-name",
                "bucket_prefix": "test",
                "keep_s3_objects": True,
                "start_time": "2021-06-02T15:55:10+02:00",
                "end_time": "2021-06-07",
                "filters": "Name=private-dns-name,Values=ip-10-10-10-10",
            },
            {
                "bucket": "bucket-name",
                "bucket_prefix": "test",
                "keep_s3_objects": False,
                "start_time": "2021-06-02T15:55:10+02:00",
                "end_time": "2021-06-07",
                "filters": "Name=node-type,Values=HeadNode",
            },
        ],
    )
    def test_execute(self, mocker, set_env, args):
        export_logs_mock = mocker.patch(
            "pcluster.cli.commands.cluster_logs.Cluster.export_logs",
            return_value=args.get("output_file", "https://u.r.l."),
        )
        set_env("AWS_DEFAULT_REGION", "us-east-1")

        command = ["export-cluster-logs"] + self._build_cli_args({**REQUIRED_ARGS, **args})
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
            "filters": None,
            "start_time": None,
            "end_time": None,
            "filters": None,
        }
        expected_params.update(args)
        expected_params.update(
            {
                "output_file": args.get("output_file") and os.path.realpath(args.get("output_file")),
                "start_time": args.get("start_time") and to_utc_datetime(args["start_time"]),
                "end_time": args.get("end_time") and to_utc_datetime(args["end_time"]),
                "filters": [args.get("filters")] if args.get("filters") else None,
            }
        )
        export_logs_mock.assert_called_with(**expected_params)

    @staticmethod
    def _build_cli_args(args):
        cli_args = []
        for k, val in args.items():
            cli_args.extend([f"--{to_kebab_case(k)}", str(val)])
        return cli_args
