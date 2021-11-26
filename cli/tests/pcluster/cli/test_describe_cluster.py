#  Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
#  with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
#  or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
#  OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
#  limitations under the License.
import pytest
from assertpy import assert_that

from pcluster.api.models import DescribeClusterResponseContent
from pcluster.cli.entrypoint import run
from pcluster.cli.exceptions import APIOperationException
from tests.utils import wire_translate


class TestDescribeClusterCommand:
    def test_helper(self, test_datadir, run_cli, assert_out_err):
        command = ["pcluster", "describe-cluster", "--help"]
        run_cli(command, expect_failure=False)

        assert_out_err(expected_out=(test_datadir / "pcluster-help.txt").read_text().strip(), expected_err="")

    @pytest.mark.parametrize(
        "args, error_message",
        [
            ([""], "error: the following arguments are required: -n/--cluster-name"),
            (["--cluster-name"], "error: argument -n/--cluster-name: expected one argument"),
            (["--cluster-name", "cluster", "--invalid"], "Invalid arguments ['--invalid']"),
            (
                ["--cluster-name", "cluster", "--region", "eu-west-"],
                "Bad Request: invalid or unsupported region 'eu-west-'",
            ),
        ],
    )
    def test_invalid_args(self, args, error_message, run_cli, capsys):
        command = ["pcluster", "describe-cluster"] + args
        run_cli(command, expect_failure=True)

        out, err = capsys.readouterr()
        assert_that(out + err).contains(error_message)

    def test_execute(self, mocker):
        response_dict = {
            "creationTime": "2021-01-01 00:00:00.000000+00:00",
            "head_node": {
                "launchTime": "2021-01-01T00:00:00+00:00",
                "instanceId": "i-099aaaaa7000ccccc",
                "publicIpAddress": "18.118.18.18",
                "instanceType": "t2.micro",
                "state": "running",
                "privateIpAddress": "10.0.0.32",
            },
            "version": "3.0.0",
            "clusterConfiguration": {
                "url": (
                    "https://parallelcluster-v1-do-not-delete.s3.amazonaws.com/parallelcluster/3.0.0/clusters/cluster/"
                    "configs/cluster-config.yaml"
                )
            },
            "tags": [{"value": "3.0.0", "key": "parallelcluster:version"}],
            "cloudFormationStackStatus": "CREATE_COMPLETE",
            "clusterName": "cluster",
            "computeFleetStatus": "RUNNING",
            "cloudformationStackArn": "arn:aws:cloudformation:us-east-2:000000000000:stack/name/0",
            "lastUpdatedTime": "2021-01-01 00:00:00.000000+00:00",
            "region": "us-west-2",
            "clusterStatus": "CREATE_COMPLETE",
        }

        response = DescribeClusterResponseContent().from_dict(response_dict)
        describe_clusters_mock = mocker.patch(
            "pcluster.api.controllers.cluster_operations_controller.describe_cluster",
            return_value=response,
            autospec=True,
        )

        out = run(["describe-cluster", "--cluster-name", "cluster"])
        expected = wire_translate(response)
        assert_that(out).is_equal_to(expected)
        assert_that(describe_clusters_mock.call_args).is_length(2)  # this is due to the decorator on list_clusters
        expected_args = {"region": None, "cluster_name": "cluster"}
        describe_clusters_mock.assert_called_with(**expected_args)

    def test_error(self, mocker):
        api_response = {"message": "error"}, 400
        mocker.patch(
            "pcluster.api.controllers.cluster_operations_controller.describe_cluster",
            return_value=api_response,
            autospec=True,
        )

        with pytest.raises(APIOperationException) as exc_info:
            command = ["describe-cluster", "--region", "eu-west-1", "--cluster-name", "name"]
            run(command)
        assert_that(exc_info.value.data).is_equal_to(api_response[0])
