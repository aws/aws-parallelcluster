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

from pcluster.api.models import ListImagesResponseContent
from pcluster.cli.entrypoint import run
from pcluster.cli.exceptions import APIOperationException


class TestListImagesCommand:
    def test_helper(self, test_datadir, run_cli, assert_out_err):
        command = ["pcluster", "list-images", "--help"]
        run_cli(command, expect_failure=False)

        assert_out_err(
            expected_out=(test_datadir / "pcluster-help.txt").read_text().strip(),
            expected_err="",
        )

    @pytest.mark.parametrize(
        "args, error_message",
        [
            ([""], "error: the following arguments are required: --image-status"),
            (
                ["--image-status"],
                "error: argument --image-status: expected one argument",
            ),
            (
                ["--image-status", "invalid"],
                r"argument --image-status: invalid choice: 'invalid' "
                r"\(choose from .*AVAILABLE.*, .*PENDING.*, .*FAILED.*\)",
            ),
            (
                ["--image-status", "AVAILABLE", "--invalid"],
                "Invalid arguments ['--invalid']",
            ),
            (
                ["--image-status", "AVAILABLE", "--region", "eu-west-"],
                "Bad Request: invalid or unsupported region 'eu-west-'",
            ),
        ],
    )
    def test_invalid_args(self, args, error_message, run_cli, capsys):
        command = ["pcluster", "list-images"] + args
        run_cli(command, expect_failure=True)

        out, err = capsys.readouterr()
        assert_that(re.search(error_message, out + err) or error_message in out + err).is_true()

    def test_execute(self, mocker):
        response_dict = {
            "images": [
                {
                    "imageId": "aws-parallelcluster-3-0-0-amzn2-hvm-x86-64-202107121836",
                    "imageBuildStatus": "BUILD_COMPLETE",
                    "region": "us-east-2",
                    "version": "3.0.0",
                },
                {
                    # "imageId": "dlami-aws-parallelcluster-3-0-0-amzn2-hvm-x86-64-202106181651",
                    "imageId": "dlami-aws-parallelcluster-3-0-0-truncated",
                    "imageBuildStatus": "BUILD_COMPLETE",
                    "region": "us-east-2",
                    "version": "3.0.0",
                },
            ]
        }

        response = ListImagesResponseContent().from_dict(response_dict)
        list_images_mock = mocker.patch(
            "pcluster.api.controllers.image_operations_controller.list_images",
            return_value=response,
            autospec=True,
        )

        out = run(["list-images", "--image-status", "AVAILABLE"])
        assert_that(out).is_equal_to(response_dict)
        assert_that(list_images_mock.call_args).is_length(2)  # this is due to the decorator on list_clusters
        expected_args = {"region": None, "next_token": None, "image_status": "AVAILABLE"}
        list_images_mock.assert_called_with(**expected_args)

    def test_error(self, mocker):
        api_response = {"message": "error"}, 400
        mocker.patch(
            "pcluster.api.controllers.image_operations_controller.list_images",
            return_value=api_response,
            autospec=True,
        )

        with pytest.raises(APIOperationException) as exc_info:
            command = [
                "list-images",
                "--region",
                "eu-west-1",
                "--image-status",
                "AVAILABLE",
            ]
            run(command)
        assert_that(exc_info.value.data).is_equal_to(api_response[0])
