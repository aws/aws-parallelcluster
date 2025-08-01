# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.

import pytest
from assertpy import assert_that

from pcluster.api.errors import BadRequestException
from pcluster.templates.cdk_builder_utils import process_ultraserver_capacity_block_sizes
from tests.pcluster.aws.dummy_aws_api import mock_aws_api


class TestUltraserverClusterStack:
    """Test ultraserver-specific functionality in cluster stack."""

    @pytest.mark.parametrize(
        "capacity_block_statuses, expected_sizes_dict",
        [
            # No capacity blocks
            ([], {"p6e-gb200": ""}),
            # Single capacity block
            (
                [{"CapacityBlockId": "cr-123", "TotalCapacity": 18}],
                {"p6e-gb200": "18"},
            ),
            # Multiple capacity blocks with same size
            (
                [
                    {"CapacityBlockId": "cr-123", "TotalCapacity": 18},
                    {"CapacityBlockId": "cr-456", "TotalCapacity": 18},
                ],
                {"p6e-gb200": "18"},
            ),
            # Multiple capacity blocks with different allowed sizes
            (
                [
                    {"CapacityBlockId": "cr-123", "TotalCapacity": 9},
                    {"CapacityBlockId": "cr-456", "TotalCapacity": 18},
                ],
                {"p6e-gb200": "9, 18"},
            ),
        ],
    )
    def test_ultraserver_capacity_block_sizes_processing(self, mocker, capacity_block_statuses, expected_sizes_dict):
        """Test processing of ultraserver capacity block sizes for DNA JSON."""
        mock_aws_api(mocker)

        # Mock the describe_capacity_block_status API response
        mocker.patch(
            "pcluster.aws.ec2.Ec2Client.describe_capacity_block_status",
            return_value={"CapacityBlockStatuses": capacity_block_statuses},
        )

        # Mock cluster config with ultraserver capacity blocks
        mock_config = mocker.MagicMock()
        mock_config.ultraserver_capacity_block_dict = {
            "p6e-gb200": ["cr-123", "cr-456"] if capacity_block_statuses else []
        }

        cluster_ultraserver_capacity_block_dict = mock_config.ultraserver_capacity_block_dict
        cluster_ultraserver_capacity_block_sizes_dict = process_ultraserver_capacity_block_sizes(
            cluster_ultraserver_capacity_block_dict
        )

        # Verify the result
        assert_that(cluster_ultraserver_capacity_block_sizes_dict).is_equal_to(expected_sizes_dict)

    def test_ultraserver_capacity_block_sizes_validation_failure(self, mocker):
        """Test that invalid capacity block sizes raise BadRequestException."""
        mock_aws_api(mocker)

        # Mock API response with invalid size (not in allowed list)
        mocker.patch(
            "pcluster.aws.ec2.Ec2Client.describe_capacity_block_status",
            return_value={
                "CapacityBlockStatuses": [
                    {"CapacityBlockId": "cr-123", "TotalCapacity": 5},  # Invalid size
                    {"CapacityBlockId": "cr-456", "TotalCapacity": 10},  # Invalid size
                ]
            },
        )

        mock_config = mocker.MagicMock()
        mock_config.ultraserver_capacity_block_dict = {"p6e-gb200": ["cr-123", "cr-456"]}

        cluster_ultraserver_capacity_block_dict = mock_config.ultraserver_capacity_block_dict

        with pytest.raises(BadRequestException) as exc_info:
            process_ultraserver_capacity_block_sizes(cluster_ultraserver_capacity_block_dict)

        # Check the exception message
        exception_message = (
            exc_info.value.content.message
            if hasattr(exc_info.value.content, "message")
            else str(exc_info.value.content)
        )
        assert_that(exception_message).contains(
            "The capacity block sizes for ultraserver instance p6e-gb200 are [5, 10]"
        )
        assert_that(exception_message).contains("The sizes should be in [9, 18], but not")

    def test_dna_json_p6e_gb200_capacity_block_sizes_inclusion(self, mocker):
        """Test that p6e_gb200_capacity_block_sizes is correctly included in DNA JSON."""
        # Test the conditional inclusion logic for DNA JSON
        cluster_ultraserver_capacity_block_sizes_dict = {"p6e-gb200": "9, 18"}

        # Test when p6e-gb200 exists and has sizes
        result = (
            {"p6e_gb200_capacity_block_sizes": cluster_ultraserver_capacity_block_sizes_dict["p6e-gb200"]}
            if "p6e-gb200" in cluster_ultraserver_capacity_block_sizes_dict
            and cluster_ultraserver_capacity_block_sizes_dict["p6e-gb200"]
            else {}
        )

        assert_that(result).is_equal_to({"p6e_gb200_capacity_block_sizes": "9, 18"})

        # Test when p6e-gb200 exists but has no sizes
        cluster_ultraserver_capacity_block_sizes_dict["p6e-gb200"] = ""
        result = (
            {"p6e_gb200_capacity_block_sizes": cluster_ultraserver_capacity_block_sizes_dict["p6e-gb200"]}
            if "p6e-gb200" in cluster_ultraserver_capacity_block_sizes_dict
            and cluster_ultraserver_capacity_block_sizes_dict["p6e-gb200"]
            else {}
        )

        assert_that(result).is_equal_to({})

        # Test when p6e-gb200 doesn't exist
        cluster_ultraserver_capacity_block_sizes_dict = {}
        result = (
            {"p6e_gb200_capacity_block_sizes": cluster_ultraserver_capacity_block_sizes_dict["p6e-gb200"]}
            if "p6e-gb200" in cluster_ultraserver_capacity_block_sizes_dict
            and cluster_ultraserver_capacity_block_sizes_dict["p6e-gb200"]
            else {}
        )

        assert_that(result).is_equal_to({})
