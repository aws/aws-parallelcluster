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

from pcluster.api.models import BuildImageResponseContent
from pcluster.cli.entrypoint import run
from pcluster.cli.exceptions import APIOperationException


class TestBuildImageCommand:
    def test_helper(self, test_datadir, run_cli, assert_out_err):
        command = ["pcluster", "build-image", "--help"]
        run_cli(command, expect_failure=False)

        assert_out_err(
            expected_out=(test_datadir / "pcluster-help.txt").read_text().strip(),
            expected_err="",
        )

    @pytest.mark.parametrize(
        "args, error_message",
        [
            ({}, "error: the following arguments are required: --image-configuration, --image-id"),
            (
                {"--image-configuration": None},
                "error: argument --image-configuration: expected one argument",
            ),
            (
                {"--image-id": None},
                "error: argument --image-id: expected one argument",
            ),
            (
                {"--image-configuration": "file", "--image-id": "id", "--invalid": None},
                "Invalid arguments ['--invalid']",
            ),
            (
                {"--image-configuration": "file", "--image-id": "id", "--region": "eu-west-"},
                "Bad Request: invalid or unsupported region 'eu-west-'",
            ),
        ],
    )
    def test_invalid_args(self, args, error_message, run_cli, capsys, test_datadir):
        if args.get("--image-configuration"):
            args["--image-configuration"] = str(test_datadir / "file")
        args = self._build_args(args)
        command = ["pcluster", "build-image"] + args
        run_cli(command, expect_failure=True)

        out, err = capsys.readouterr()
        assert_that(out + err).contains(error_message)

    def test_execute(self, mocker, test_datadir):
        response_dict = {
            "image": {
                "imageId": "image-id",
                "imageBuildStatus": "BUILD_IN_PROGRESS",
                "cloudformationStackStatus": "CREATE_IN_PROGRESS",
                "cloudformationStackArn": "arn:aws:cloudformation:eu-west-1:000000000000:stack/image-id/aaa",
                "region": "eu-west-1",
                "version": "3.0.0",
            }
        }

        response = BuildImageResponseContent().from_dict(response_dict)
        describe_clusters_mock = mocker.patch(
            "pcluster.api.controllers.image_operations_controller.build_image",
            return_value=response,
            autospec=True,
        )

        path = str(test_datadir / "config.yaml")
        out = run(["build-image", "--image-configuration", path, "--image-id", "image-id", "--region", "eu-west-1"])
        assert_that(out).is_equal_to(response_dict)
        assert_that(describe_clusters_mock.call_args).is_length(2)  # this is due to the decorator on list_clusters
        expected_args = {
            "suppress_validators": None,
            "validation_failure_level": None,
            "dryrun": None,
            "rollback_on_failure": None,
            "region": "eu-west-1",
            "build_image_request_content": {"image-id": "image-id", "imageConfiguration": ""},
        }
        describe_clusters_mock.assert_called_with(**expected_args)

    def test_error(self, mocker, test_datadir):
        api_response = {"message": "error"}, 400
        mocker.patch(
            "pcluster.api.controllers.image_operations_controller.build_image",
            return_value=api_response,
            autospec=True,
        )

        path = str(test_datadir / "config.yaml")
        with pytest.raises(APIOperationException) as exc_info:
            command = [
                "build-image",
                "--region",
                "eu-west-1",
                "--image-configuration",
                path,
                "--image-id",
                "image-id",
            ]
            run(command)
        assert_that(exc_info.value.data).is_equal_to(api_response[0])

    def _build_args(self, args):
        args = [[k, v] if v is not None else [k] for k, v in args.items()]
        return list(itertools.chain(*args))
