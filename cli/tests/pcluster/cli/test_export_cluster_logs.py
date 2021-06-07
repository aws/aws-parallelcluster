#  Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
#  with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
#  or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
#  OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
#  limitations under the License.
import re

import pytest
from assertpy import assert_that

BASE_COMMAND = ["pcluster", "export-cluster-logs"]
REQUIRED_ARGS = {"cluster_name": "clustername", "bucket": "bucketname"}


class TestExportClusterLogsCommand:
    def test_helper(self, test_datadir, run_cli, assert_out_err):
        command = BASE_COMMAND + ["--help"]
        run_cli(command, expect_failure=False)

        assert_out_err(expected_out=(test_datadir / "pcluster-help.txt").read_text().strip(), expected_err="")

    @pytest.mark.parametrize(
        "args, error_message",
        [({"output": "path"}, "the following arguments are required: cluster_name, --bucket")],
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
        [
            {},
            {
                "output": "output-path",
            },
            {
                "bucket": "bucket-name",
                "bucket_prefix": "test",
                "keep_s3_objects": True,
            },
            {
                "filters": "Name=private-ip-address,Values=10.10.10.10",
            },
            {
                "output": "output-path",
                "bucket": "bucket-name",
                "bucket_prefix": "test",
                "keep_s3_objects": True,
                "filters": "Name=private-ip-address,Values=10.10.10.10 "
                "Name=start-time,Values=1623071000 "
                "Name=end-time,Values=1623071000",
            },
        ],
        ids=["required", "output", "bucket_options", "filters", "all"],
    )
    def test_execute(self, mocker, capsys, set_env, assert_out_err, run_cli, args):
        export_logs_mock = mocker.patch("pcluster.api.pcluster_api.PclusterApi.export_cluster_logs")
        set_env("AWS_DEFAULT_REGION", "us-east-1")

        command = BASE_COMMAND + self._build_cli_args({**REQUIRED_ARGS, **args})
        run_cli(command, expect_failure=False)

        assert_out_err(expected_out="Cluster's logs exported correctly", expected_err="")
        assert_that(export_logs_mock.call_args).is_length(2)

        # verify arguments
        expected_params = {
            "cluster_name": None,
            "region": r"[\w-]+",
            "output": r".*clustername-logs-.*\.tar\.gz",
            "bucket": None,
            "bucket_prefix": None,
            "keep_s3_objects": False,
            "filters": None,
        }
        expected_params.update(REQUIRED_ARGS)
        expected_params.update(args)

        self._check_params(export_logs_mock, expected_params, args)

    @staticmethod
    def _build_cli_args(args):
        cli_args = []
        if "cluster_name" in args:
            cli_args.extend([args["cluster_name"]])
        if "output" in args:
            cli_args.extend(["--output", args["output"]])
        if "bucket" in args:
            cli_args.extend(["--bucket", args["bucket"]])
        if "bucket_prefix" in args:
            cli_args.extend(["--bucket-prefix", args["bucket_prefix"]])
        if "keep_s3_objects" in args and args["keep_s3_objects"]:
            cli_args.extend(["--keep-s3-objects"])
        if "filters" in args:
            cli_args.extend(["--filters", args["filters"]])
        return cli_args

    @staticmethod
    def _check_params(export_logs_mock, expected_params, args):
        for param_key, expected_value in expected_params.items():
            call_param = export_logs_mock.call_args[1].get(param_key)
            check_regex = False

            if param_key == "output":
                expected_value = f".*{expected_value}"
                check_regex = True

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
