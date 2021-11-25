#  Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
#  with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
#  or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
#  OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
#  limitations under the License.
import pytest
from assertpy import assert_that

from pcluster.api.models import DescribeImageResponseContent
from pcluster.cli.entrypoint import run
from pcluster.cli.exceptions import APIOperationException
from tests.utils import wire_translate


class TestDescribeImageCommand:
    def test_helper(self, test_datadir, run_cli, assert_out_err):
        command = ["pcluster", "describe-image", "--help"]
        run_cli(command, expect_failure=False)

        assert_out_err(expected_out=(test_datadir / "pcluster-help.txt").read_text().strip(), expected_err="")

    @pytest.mark.parametrize(
        "args, error_message",
        [
            ([""], "error: the following arguments are required: -i/--image-id"),
            (["--image-id"], "error: argument -i/--image-id: expected one argument"),
            (["--image-id", "image", "--invalid"], "Invalid arguments ['--invalid']"),
            (["--image-id", "image", "--region", "eu-west-"], "Bad Request: invalid or unsupported region 'eu-west-'"),
        ],
    )
    def test_invalid_args(self, args, error_message, run_cli, capsys):
        command = ["pcluster", "describe-image"] + args
        run_cli(command, expect_failure=True)

        out, err = capsys.readouterr()
        assert_that(out + err).contains(error_message)

    def test_execute(self, mocker):
        response_dict = {
            "imageConfiguration": {
                "url": "s3://parallelcluster-0000000000000000-v1-do-not-delete/parallelcluster/3.0.0/config.yaml"
            },
            "imageId": "aws-parallelcluster-3-0-0-ubuntu-1804-lts-hvm-arm64-202101010000",
            "creationTime": "2021-01-01T00:00:00.000Z",
            "imageBuildStatus": "BUILD_COMPLETE",
            "region": "eu-west-2",
            "ec2AmiInfo": {
                "amiName": "aws-parallelcluster-3.0.0-ubuntu-1804-lts-hvm-x86_64-202101010000 2021-01-01T00-00-00.000Z",
                "amiId": "ami-FEED0DEAD0BEEF000",
                "description": "AWS ParallelCluster AMI for ubuntu1804",
                "state": "AVAILABLE",
                "tags": [
                    {"key": "parallelcluster:lustre_version", "value": "5.4.0.1051.33"},
                    {"key": "parallelcluster:bootstrap_file", "value": "aws-parallelcluster-cookbook-3.0.0"},
                ],
                "architecture": "x86_64",
            },
            "version": "3.0.0",
        }

        response = DescribeImageResponseContent().from_dict(response_dict)
        describe_image_mock = mocker.patch(
            "pcluster.api.controllers.image_operations_controller.describe_image", return_value=response, autospec=True
        )

        out = run(["describe-image", "--image-id", "image"])
        assert_that(out).is_equal_to(wire_translate(response))
        assert_that(describe_image_mock.call_args).is_length(2)  # this is due to the decorator on list_clusters
        expected_args = {"region": None, "image_id": "image"}
        describe_image_mock.assert_called_with(**expected_args)

    def test_error(self, mocker):
        api_response = {"message": "error"}, 400
        mocker.patch(
            "pcluster.api.controllers.image_operations_controller.describe_image",
            return_value=api_response,
            autospec=True,
        )

        with pytest.raises(APIOperationException) as exc_info:
            command = ["describe-image", "--region", "eu-west-1", "--image-id", "name"]
            run(command)
        assert_that(exc_info.value.data).is_equal_to(api_response[0])
