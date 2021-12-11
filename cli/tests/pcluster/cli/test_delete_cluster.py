#  Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
#  with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
#  or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
#  OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
#  limitations under the License.
import pytest
from assertpy import assert_that

from pcluster.api.models import DeleteClusterResponseContent
from pcluster.cli.entrypoint import run
from pcluster.cli.exceptions import APIOperationException
from tests.pcluster.aws.dummy_aws_api import mock_aws_api
from tests.utils import wire_translate


class TestDeleteClusterCommand:
    def test_helper(self, test_datadir, run_cli, assert_out_err):
        command = ["pcluster", "delete-cluster", "--help"]
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
        command = ["pcluster", "delete-cluster"] + args
        run_cli(command, expect_failure=True)

        out, err = capsys.readouterr()
        assert_that(out + err).contains(error_message)

    def test_execute_with_wait(self, mocker):
        response_dict = {
            "cluster": {
                "clusterName": "cluster",
                "cloudformationStackStatus": "DELETE_IN_PROGRESS",
                "cloudformationStackArn": "arn:aws:cloudformation:us-east-2:000000000000:stack/cluster/aa",
                "region": "eu-west-1",
                "version": "3.0.0",
                "clusterStatus": "DELETE_IN_PROGRESS",
            }
        }

        delete_response_dict = {"message": "Successfully deleted cluster 'cluster'."}

        delete_response = DeleteClusterResponseContent().from_dict(response_dict)
        delete_cluster_mock = mocker.patch(
            "pcluster.api.controllers.cluster_operations_controller.delete_cluster",
            return_value=delete_response,
            autospec=True,
        )

        cf_waiter_mock = mocker.patch("botocore.waiter.Waiter.wait")
        mock_aws_api(mocker)

        command = ["delete-cluster", "--cluster-name", "cluster", "--wait"]
        out = run(command)

        assert_that(out).is_equal_to(delete_response_dict)
        assert_that(delete_cluster_mock.call_args).is_length(2)
        args_expected = {"region": None, "cluster_name": "cluster"}
        delete_cluster_mock.assert_called_with(**args_expected)
        assert_that(cf_waiter_mock.call_args[1]).is_equal_to({"StackName": "cluster"})

    def test_execute(self, mocker):
        response_dict = {
            "cluster": {
                "clusterName": "cluster",
                "cloudformationStackStatus": "DELETE_IN_PROGRESS",
                "cloudformationStackArn": "arn:aws:cloudformation:us-east-2:000000000000:stack/cluster/aa",
                "region": "eu-west-1",
                "version": "3.0.0",
                "clusterStatus": "DELETE_IN_PROGRESS",
            }
        }
        response = DeleteClusterResponseContent().from_dict(response_dict)

        delete_cluster_mock = mocker.patch(
            "pcluster.api.controllers.cluster_operations_controller.delete_cluster",
            return_value=response,
            autospec=True,
        )

        out = run(["delete-cluster", "--cluster-name", "cluster"])

        expected = wire_translate(response)
        assert_that(out).is_equal_to(expected)
        assert_that(delete_cluster_mock.call_args).is_length(2)
        args_expected = {"region": None, "cluster_name": "cluster"}
        delete_cluster_mock.assert_called_with(**args_expected)

    def test_error(self, mocker):
        api_response = {"message": "error"}, 400
        mocker.patch(
            "pcluster.api.controllers.cluster_operations_controller.delete_cluster",
            return_value=api_response,
            autospec=True,
        )

        with pytest.raises(APIOperationException) as exc_info:
            command = ["delete-cluster", "--region", "eu-west-1", "--cluster-name", "cluster"]
            run(command)
        assert_that(exc_info.value.data).is_equal_to(api_response[0])
