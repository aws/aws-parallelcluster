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

from pcluster.api.models import CreateClusterResponseContent, DescribeClusterResponseContent
from pcluster.cli.entrypoint import run
from pcluster.cli.exceptions import APIOperationException
from tests.pcluster.aws.dummy_aws_api import mock_aws_api
from tests.utils import wire_translate


class TestCreateClusterCommand:
    def test_helper(self, test_datadir, run_cli, assert_out_err):
        command = ["pcluster", "create-cluster", "--help"]
        run_cli(command, expect_failure=False)

        assert_out_err(expected_out=(test_datadir / "pcluster-help.txt").read_text().strip(), expected_err="")

    @pytest.mark.parametrize(
        "args, error_message",
        [
            ({}, "error: the following arguments are required: -n/--cluster-name, -c/--cluster-configuration"),
            ({"--cluster-configuration": None}, "error: argument -c/--cluster-configuration: expected one argument"),
            ({"--cluster-name": None}, "error: argument -n/--cluster-name: expected one argument"),
            (
                {"--cluster-configuration": "file", "--cluster-name": "cluster", "--invalid": None},
                "Invalid arguments ['--invalid']",
            ),
            (
                {"--cluster-configuration": "file", "--cluster-name": "cluster", "--region": "eu-west-"},
                "Bad Request: invalid or unsupported region 'eu-west-'",
            ),
        ],
    )
    def test_invalid_args(self, args, error_message, run_cli, capsys, test_datadir):
        if args.get("--cluster-configuration"):
            args["--cluster-configuration"] = str(test_datadir / "config.yaml")
        args = self._build_args(args)
        command = ["pcluster", "create-cluster"] + args
        run_cli(command, expect_failure=True)

        out, err = capsys.readouterr()
        assert_that(out + err).contains(error_message)

    def test_execute_with_wait(self, mocker, test_datadir):
        response_dict = {
            "cluster": {
                "clusterName": "cluster",
                "cloudformationStackStatus": "CREATE_IN_PROGRESS",
                "cloudformationStackArn": "arn:aws:cloudformation:us-east-2:000000000000:stack/cluster/aa",
                "region": "eu-west-1",
                "version": "3.0.0",
                "clusterStatus": "CREATE_IN_PROGRESS",
            }
        }

        status_response_dict = {
            "creationTime": "2021-01-01 00:00:00.000000+00:00",
            "headNode": {
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

        create_response = CreateClusterResponseContent().from_dict(response_dict)
        create_cluster_mock = mocker.patch(
            "pcluster.api.controllers.cluster_operations_controller.create_cluster",
            return_value=create_response,
            autospec=True,
        )

        response = DescribeClusterResponseContent().from_dict(status_response_dict)
        describe_cluster_mock = mocker.patch(
            "pcluster.api.controllers.cluster_operations_controller.describe_cluster", return_value=response
        )
        cf_waiter_mock = mocker.patch("botocore.waiter.Waiter.wait")
        mock_aws_api(mocker)

        path = str(test_datadir / "config.yaml")
        command = ["create-cluster", "-n", "cluster", "-c", path, "-r", "eu-west-1", "--wait"]
        out = run(command)

        expected = wire_translate(response)
        assert_that(out).is_equal_to(expected)
        assert_that(create_cluster_mock.call_args).is_length(2)
        expected_args = {
            "suppress_validators": None,
            "validation_failure_level": None,
            "dryrun": None,
            "rollback_on_failure": None,
            "region": "eu-west-1",
            "create_cluster_request_content": {"clusterName": "cluster", "clusterConfiguration": ""},
        }
        create_cluster_mock.assert_called_with(**expected_args)
        assert_that(cf_waiter_mock.call_args[1]).is_equal_to({"StackName": "cluster"})
        describe_cluster_mock.assert_called_with(cluster_name="cluster")

    @pytest.mark.parametrize("cluster_name_arg, region_arg", [("--cluster-name", "--region"), ("-n", "-r")])
    def test_execute(self, cluster_name_arg, region_arg, mocker, test_datadir):
        response_dict = {
            "cluster": {
                "clusterName": "cluster",
                "cloudformationStackStatus": "CREATE_IN_PROGRESS",
                "cloudformationStackArn": "arn:aws:cloudformation:us-east-2:000000000000:stack/cluster/aa",
                "region": "eu-west-1",
                "version": "3.0.0",
                "clusterStatus": "CREATE_IN_PROGRESS",
            }
        }

        response = CreateClusterResponseContent().from_dict(response_dict)
        create_cluster_mock = mocker.patch(
            "pcluster.api.controllers.cluster_operations_controller.create_cluster",
            return_value=response,
            autospec=True,
        )

        path = str(test_datadir / "config.yaml")
        out = run(
            ["create-cluster", cluster_name_arg, "cluster", "--cluster-configuration", path, region_arg, "eu-west-1"]
        )
        assert_that(out).is_equal_to(response_dict)
        assert_that(create_cluster_mock.call_args).is_length(2)
        expected_args = {
            "suppress_validators": None,
            "validation_failure_level": None,
            "dryrun": None,
            "rollback_on_failure": None,
            "region": "eu-west-1",
            "create_cluster_request_content": {"clusterName": "cluster", "clusterConfiguration": ""},
        }
        create_cluster_mock.assert_called_with(**expected_args)

    def test_error(self, mocker, test_datadir):
        api_response = {"message": "error"}, 400
        mocker.patch(
            "pcluster.api.controllers.cluster_operations_controller.create_cluster",
            return_value=api_response,
            autospec=True,
        )

        path = str(test_datadir / "config.yaml")
        with pytest.raises(APIOperationException) as exc_info:
            command = [
                "create-cluster",
                "--region",
                "eu-west-1",
                "--cluster-configuration",
                path,
                "--cluster-name",
                "cluster",
            ]
            run(command)
        assert_that(exc_info.value.data).is_equal_to(api_response[0])

    def test_no_nodejs_error(self, mocker, test_datadir):
        """Test expected message is printed out if nodejs is not installed."""
        mocker.patch("pcluster.api.util.shutil.which", return_value=None)
        with pytest.raises(APIOperationException) as exc_info:
            run(
                [
                    "create-cluster",
                    "--region",
                    "eu-west-1",
                    "--cluster-configuration",
                    str(test_datadir / "config.yaml"),
                    "--cluster-name",
                    "cluster",
                ]
            )
        assert_that(exc_info.value.data.get("message")).matches("Node.js is required")

    def _build_args(self, args):
        args = [[k, v] if v is not None else [k] for k, v in args.items()]
        return list(itertools.chain(*args))
