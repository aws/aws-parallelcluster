#  Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
#  with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
#  or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
#  OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
#  limitations under the License.
from unittest.mock import ANY

import pytest
from assertpy import assert_that

from pcluster.api.models import ListClustersResponseContent
from pcluster.cli.entrypoint import run
from pcluster.cli.exceptions import APIOperationException


class TestListClustersCommand:
    def test_helper(self, test_datadir, run_cli, assert_out_err):
        command = ["pcluster", "list-clusters", "--help"]
        run_cli(command, expect_failure=False)

        assert_out_err(expected_out=(test_datadir / "pcluster-help.txt").read_text().strip(), expected_err="")

    @pytest.mark.parametrize(
        "args, error_message",
        [
            (["--invalid"], "Invalid arguments ['--invalid']"),
            (["--region", "eu-west-"], "Bad Request: invalid or unsupported region 'eu-west-'"),
            (["--cluster-status", "invalid"], "argument --cluster-status: invalid choice: 'invalid'"),
        ],
    )
    def test_invalid_args(self, args, error_message, run_cli, capsys):
        command = ["pcluster", "list-clusters"] + args
        run_cli(command, expect_failure=True)

        out, err = capsys.readouterr()
        assert_that(out + err).contains(error_message)

    @pytest.mark.parametrize(
        "args, mocked_api_response, expected_cli_response",
        [
            (
                {
                    "cluster_status": ["DELETE_IN_PROGRESS", "CREATE_IN_PROGRESS"],
                    "next_token": "token",
                    "region": "us-east-1",
                },
                ListClustersResponseContent(items=[], next_token="token"),
                {"items": [], "nextToken": "token"},
            ),
            (
                {
                    "region": "us-east-1",
                },
                ListClustersResponseContent(items=[], next_token="token"),
                {"items": [], "nextToken": "token"},
            ),
            (
                {
                    "cluster_status": ["DELETE_IN_PROGRESS", "DELETE_IN_PROGRESS"],
                    "region": "us-east-1",
                },
                ListClustersResponseContent(items=[], next_token="token"),
                {"items": [], "nextToken": "token"},
            ),
        ],
        ids=["all", "required", "duplicated_status"],
    )
    def test_execute(self, mocker, args, mocked_api_response, expected_cli_response):
        list_clusters_mock = mocker.patch(
            "pcluster.api.controllers.cluster_operations_controller.list_clusters",
            return_value=mocked_api_response,
            autospec=True,
        )

        out = run(["list-clusters"] + self._build_cli_args(args))
        assert_that(out).is_equal_to(expected_cli_response)
        assert_that(list_clusters_mock.call_args).is_length(2)  # this is due to the decorator on list_clusters
        if "cluster_status" in args:
            # Asserting the cluster_status list separately because the order is not preserved
            assert_that(list_clusters_mock.call_args[1].get("cluster_status")).contains_only(
                *args.get("cluster_status")
            )
            args["cluster_status"] = ANY
        base_args = {"region": None, "next_token": None, "cluster_status": None}
        list_clusters_mock.assert_called_with(**{**base_args, **args})

    def test_error(self, mocker):
        api_response = {"message": "error"}, 400
        mocker.patch(
            "pcluster.api.controllers.cluster_operations_controller.list_clusters",
            return_value=api_response,
            autospec=True,
        )

        with pytest.raises(APIOperationException) as exc_info:
            command = ["list-clusters", "--region", "eu-west-1"]
            run(command)
        assert_that(exc_info.value.data).is_equal_to(api_response[0])

    @staticmethod
    def _build_cli_args(args):
        cli_args = []
        if "region" in args:
            cli_args.extend(["--region", args["region"]])
        if "next_token" in args:
            cli_args.extend(["--next-token", args["next_token"]])
        if "cluster_status" in args:
            cli_args.extend(["--cluster-status"])
            cli_args.extend(args["cluster_status"])
        return cli_args
