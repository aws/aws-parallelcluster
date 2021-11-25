#  Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
#  with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
#  or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
#  OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
#  limitations under the License.
import pytest
from assertpy import assert_that

from pcluster.api.models import GetImageStackEventsResponseContent
from pcluster.cli.entrypoint import run
from pcluster.cli.exceptions import APIOperationException


class TestGetImageStackEventsCommand:
    def test_helper(self, test_datadir, run_cli, assert_out_err):
        command = ["pcluster", "get-image-stack-events", "--help"]
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
        command = ["pcluster", "get-image-stack-events"] + args
        run_cli(command, expect_failure=True)

        out, err = capsys.readouterr()
        assert_that(out + err).contains(error_message)

    def test_execute(self, mocker):
        response_dict = {
            "nextToken": "99/nexttoken",
            "events": [
                {
                    "eventId": "00000000-aaaa-1111-bbbb-000000000000",
                    "physicalResourceId": "arn:aws:cloudformation:eu-west-1:000000000000:stack/image/aa",
                    "resourceStatus": "UPDATE_COMPLETE",
                    "stackId": "arn:aws:cloudformation:eu-west-1:000000000000:stack/image/aaa",
                    "stackName": "image",
                    "logicalResourceId": "image",
                    "resourceType": "AWS::CloudFormation::Stack",
                    "timestamp": "2021-01-01T00:00:00.000Z",
                }
            ],
        }

        response = GetImageStackEventsResponseContent().from_dict(response_dict)
        get_image_stack_events_mock = mocker.patch(
            "pcluster.api.controllers.image_logs_controller.get_image_stack_events",
            return_value=response,
            autospec=True,
        )

        out = run(["get-image-stack-events", "--image-id", "image"])
        assert_that(out).is_equal_to(response_dict)
        assert_that(get_image_stack_events_mock.call_args).is_length(2)  # this is due to the decorator on list_clusters
        expected_args = {"region": None, "image_id": "image", "next_token": None}
        get_image_stack_events_mock.assert_called_with(**expected_args)

    def test_error(self, mocker):
        api_response = {"message": "error"}, 400
        mocker.patch(
            "pcluster.api.controllers.image_logs_controller.get_image_stack_events",
            return_value=api_response,
            autospec=True,
        )

        with pytest.raises(APIOperationException) as exc_info:
            command = ["get-image-stack-events", "--region", "eu-west-1", "--image-id", "image-id"]
            run(command)
        assert_that(exc_info.value.data).is_equal_to(api_response[0])
