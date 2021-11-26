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

from pcluster.api.models import DescribeClusterResponseContent, UpdateClusterResponseContent
from pcluster.cli.entrypoint import run
from pcluster.cli.exceptions import APIOperationException
from tests.pcluster.aws.dummy_aws_api import mock_aws_api
from tests.utils import wire_translate


class TestUpdateClusterCommand:
    def test_helper(self, test_datadir, run_cli, assert_out_err):
        command = ["pcluster", "update-cluster", "--help"]
        run_cli(command, expect_failure=False)

        assert_out_err(expected_out=(test_datadir / "pcluster-help.txt").read_text().strip(), expected_err="")

    @pytest.mark.parametrize(
        "args, error_message",
        [
            ({}, "error: the following arguments are required: -n/--cluster-name, -c/--cluster-configuration"),
            ({"--cluster-configuration": None}, "error: argument -c/--cluster-configuration: expected one argument"),
            ({"--cluster-name": None}, "error: argument -n/--cluster-name: expected one argument"),
            ({"-c": "file", "-n": "cluster", "--invalid": None}, "Invalid arguments ['--invalid']"),
            (
                {"-c": "file", "-n": "cluster", "-r": "eu-west-"},
                "Bad Request: invalid or unsupported region 'eu-west-'",
            ),
        ],
    )
    def test_invalid_args(self, args, error_message, run_cli, capsys, test_datadir):
        if args.get("-c"):
            args["-c"] = str(test_datadir / "config.yaml")
        args = self._build_args(args)
        command = ["pcluster", "update-cluster"] + args
        run_cli(command, expect_failure=True)

        out, err = capsys.readouterr()
        assert_that(out + err).contains(error_message)

    def test_execute_with_wait(self, mocker, test_datadir):
        response_dict = {
            "cluster": {
                "clusterName": "cluster",
                "cloudformationStackStatus": "UPDATE_IN_PROGRESS",
                "cloudformationStackArn": "arn:aws:cloudformation:us-east-2:000000000000:stack/cluster/aa",
                "region": "eu-west-1",
                "version": "3.0.0",
                "clusterStatus": "UPDATE_IN_PROGRESS",
            },
            "changeSet": [
                {
                    "parameter": "Scheduling.SlurmQueues[queue0].ComputeResources[queue0-i0].MaxCount",
                    "requestedValue": "100",
                    "currentValue": "20",
                }
            ],
        }

        status_response_dict = {
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

        update_response = UpdateClusterResponseContent().from_dict(response_dict)
        update_cluster_mock = mocker.patch(
            "pcluster.api.controllers.cluster_operations_controller.update_cluster",
            return_value=update_response,
            autospec=True,
        )

        response = DescribeClusterResponseContent().from_dict(status_response_dict)
        describe_cluster_mock = mocker.patch(
            "pcluster.api.controllers.cluster_operations_controller.describe_cluster", return_value=response
        )

        cf_waiter_mock = mocker.patch("botocore.waiter.Waiter.wait")
        mock_aws_api(mocker)

        path = str(test_datadir / "config.yaml")
        command = ["update-cluster", "--cluster-name", "cluster", "--cluster-configuration", path, "--wait"]
        out = run(command)

        expected = wire_translate(response)
        assert_that(out).is_equal_to(expected)
        assert_that(update_cluster_mock.call_args).is_length(2)
        expected_args = {
            "update_cluster_request_content": {"clusterConfiguration": ""},
            "cluster_name": "cluster",
            "dryrun": None,
            "force_update": None,
            "region": None,
            "suppress_validators": None,
            "validation_failure_level": None,
        }
        update_cluster_mock.assert_called_with(**expected_args)
        assert_that(cf_waiter_mock.call_args[1]).is_equal_to({"StackName": "cluster"})
        describe_cluster_mock.assert_called_with(cluster_name="cluster")

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
            "changeSet": [
                {
                    "parameter": "Scheduling.SlurmQueues[queue0].ComputeResources[queue0-i0].MaxCount",
                    "requestedValue": "100",
                    "currentValue": "20",
                }
            ],
        }

        response = UpdateClusterResponseContent().from_dict(response_dict)
        update_cluster_mock = mocker.patch(
            "pcluster.api.controllers.cluster_operations_controller.update_cluster",
            return_value=response,
            autospec=True,
        )

        path = str(test_datadir / "config.yaml")
        command = ["update-cluster", "--cluster-name", "cluster", "--cluster-configuration", path]
        out = run(command)
        assert_that(out).is_equal_to(response_dict)
        assert_that(update_cluster_mock.call_args).is_length(2)
        expected_args = {
            "update_cluster_request_content": {"clusterConfiguration": ""},
            "cluster_name": "cluster",
            "dryrun": None,
            "force_update": None,
            "region": None,
            "suppress_validators": None,
            "validation_failure_level": None,
        }
        update_cluster_mock.assert_called_with(**expected_args)

    def test_error(self, mocker, test_datadir):
        api_response = {"message": "error"}, 400
        mocker.patch(
            "pcluster.api.controllers.cluster_operations_controller.update_cluster",
            return_value=api_response,
            autospec=True,
        )

        path = str(test_datadir / "config.yaml")
        with pytest.raises(APIOperationException) as exc_info:
            command = ["update-cluster", "-r", "eu-west-1", "-n", "name", "-c", path]
            run(command)
        assert_that(exc_info.value.data).is_equal_to(api_response[0])

    def test_no_nodejs_error(self, mocker, test_datadir):
        """Test expected message is printed out if nodejs is not installed."""
        mocker.patch("pcluster.api.util.shutil.which", return_value=None)
        with pytest.raises(APIOperationException) as exc_info:
            run(["update-cluster", "-r", "eu-west-1", "-n", "name", "-c", str(test_datadir / "config.yaml")])
        assert_that(exc_info.value.data.get("message")).matches("Node.js is required")

    def _build_args(self, args):
        args = [[k, v] if v is not None else [k] for k, v in args.items()]
        return list(itertools.chain(*args))
