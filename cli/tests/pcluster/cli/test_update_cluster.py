#  Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
#  with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
#  or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
#  OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
#  limitations under the License.
import itertools

import pytest
from assertpy import assert_that

from pcluster.api.models import UpdateClusterResponseContent
from pcluster.cli.entrypoint import run
from pcluster.cli.exceptions import APIOperationException


class TestUpdateClusterCommand:
    def test_helper(self, test_datadir, run_cli, assert_out_err):
        command = ["pcluster", "update-cluster", "--help"]
        run_cli(command, expect_failure=False)

        assert_out_err(
            expected_out=(test_datadir / "pcluster-help.txt").read_text().strip(),
            expected_err="",
        )

    @pytest.mark.parametrize(
        "args, error_message",
        [
            (
                {},
                "error: the following arguments are required: --cluster-name, --cluster-configuration",
            ),
            (
                {"--cluster-configuration": None},
                "error: argument --cluster-configuration: expected one argument",
            ),
            (
                {"--cluster-name": None},
                "error: argument --cluster-name: expected one argument",
            ),
            (
                {
                    "--cluster-configuration": "file",
                    "--cluster-name": "cluster",
                    "--invalid": None,
                },
                "Invalid arguments ['--invalid']",
            ),
            (
                {
                    "--cluster-configuration": "file",
                    "--cluster-name": "cluster",
                    "--region": "eu-west-",
                },
                "Bad Request: invalid or unsupported region 'eu-west-'",
            ),
        ],
    )
    def test_invalid_args(self, args, error_message, run_cli, capsys, test_datadir):
        if args.get("--cluster-configuration"):
            args["--cluster-configuration"] = str(test_datadir / "config.yaml")
        args = self._build_args(args)
        command = ["pcluster", "update-cluster"] + args
        run_cli(command, expect_failure=True)

        out, err = capsys.readouterr()
        assert_that(out + err).contains(error_message)

    def test_execute(self, mocker, test_datadir):
        response_dict = {
            "cluster": {
                "clusterName": "cluster",
                "cloudformationStackStatus": "UPDATE_IN_PROGRESS",
                "cloudformationStackArn": "arn:aws:cloudformation:us-east-2:000000000000:stack/cluster/aa",
                "region": "eu-west-1",
                "version": "3.0.0",
                "clusterStatus": "UPDATE_IN_PROGRESS",
            },
            # TODO: add better values here
            "changeSet": [],
        }

        response = UpdateClusterResponseContent().from_dict(response_dict)
        describe_clusters_mock = mocker.patch(
            "pcluster.api.controllers.cluster_operations_controller.update_cluster",
            return_value=response,
            autospec=True,
        )

        path = str(test_datadir / "config.yaml")
        out = run(
            [
                "update-cluster",
                "--cluster-name",
                "cluster",
                "--cluster-configuration",
                path,
            ]
        )
        assert_that(out).is_equal_to(response_dict)
        assert_that(describe_clusters_mock.call_args).is_length(2)  # this is due to the decorator on list_clusters
        expected_args = {"region": None, "cluster_name": "cluster"}
        describe_clusters_mock.assert_called_with(**expected_args)

    def test_error(self, mocker, test_datadir):
        api_response = {"message": "error"}, 400
        mocker.patch(
            "pcluster.api.controllers.cluster_operations_controller.update_cluster",
            return_value=api_response,
            autospec=True,
        )

        path = str(test_datadir / "config.yaml")
        with pytest.raises(APIOperationException) as exc_info:
            command = [
                "update-cluster",
                "--region",
                "eu-west-1",
                "--cluster-name",
                "name",
                "--cluster-configuration",
                path,
            ]
            run(command)
        assert_that(exc_info.value.data).is_equal_to(api_response[0])

    def _build_args(self, args):
        args = [[k, v] if v is not None else [k] for k, v in args.items()]
        return list(itertools.chain(*args))
