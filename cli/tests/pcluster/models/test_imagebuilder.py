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
import datetime
import json
from urllib.error import URLError

import pytest
from assertpy import assert_that, soft_assertions
from dateutil import tz

from pcluster.aws.aws_resources import ImageInfo
from pcluster.aws.common import AWSClientError, BadRequestError, LimitExceededError
from pcluster.config.imagebuilder_config import Build, ImageBuilderConfig, ImageBuilderExtraChefAttributes
from pcluster.models.common import BadRequest
from pcluster.models.imagebuilder import (
    BadRequestImageBuilderActionError,
    ImageBuilder,
    ImageBuilderActionError,
    LimitExceededImageBuilderActionError,
)
from pcluster.models.imagebuilder_resources import ImageBuilderStack
from pcluster.validators.common import FailureLevel
from tests.pcluster.aws.dummy_aws_api import mock_aws_api
from tests.pcluster.config.dummy_imagebuilder_config import imagebuilder_factory
from tests.pcluster.config.test_common import assert_validation_result
from tests.pcluster.test_imagebuilder_utils import FAKE_ID
from tests.pcluster.test_utils import FAKE_NAME


@pytest.mark.parametrize(
    "resource, ami_response, ami_side_effect, expected_failure_messages, expected_failure_levels",
    [
        (
            {
                "imagebuilder": {
                    "image": {
                        "root_volume": {"size": 25, "kms_key_id": "key_id"},
                        "tags": [
                            {"key": "name", "value": "pcluster"},
                            {"key": "date", "value": "2022.1.1"},
                        ],
                    },
                    "build": {
                        "parent_image": "ami-0185634c5a8a37250",
                        "instance_type": "c5.xlarge",
                    },
                }
            },
            {
                "Architecture": "x86_64",
                "BlockDeviceMappings": [
                    {
                        "DeviceName": "/dev/xvda",
                        "Ebs": {
                            "DeleteOnTermination": True,
                            "SnapshotId": "snap-0a20b6671bc5e3ead",
                            "VolumeSize": 50,
                            "VolumeType": "gp2",
                            "Encrypted": False,
                        },
                    }
                ],
                "Description": "AWS ParallelCluster AMI for alinux2",
            },
            None,
            [
                "Kms Key Id key_id is specified, the encrypted state must be True.",
                "Root volume size 25 GB is less than the minimum required size 50 GB that equals parent ami"
                + " volume size.",
            ],
            [FailureLevel.ERROR, FailureLevel.ERROR],
        )
    ],
)
def test_imagebuilder_kms_key_id_encrypted_validator_and_ami_volume_size_validator(
    mocker, resource, ami_response, ami_side_effect, expected_failure_messages, expected_failure_levels
):
    """Test KmsKeyIdEncryptedValidator and AMIVolumeSizeValidator."""
    fake_instance_response = ["c5.xlarge", "m6g.xlarge"]
    fake_supported_architecture = ["x86_64"]
    _test_imagebuilder(
        mocker,
        resource,
        ami_response,
        ami_side_effect,
        fake_instance_response,
        True,
        None,
        None,
        fake_supported_architecture,
        expected_failure_messages,
        expected_failure_levels,
    )


@pytest.mark.parametrize(
    "resource, url_response, url_side_effect, url_open_side_effect, expected_failure_messages, expected_failure_levels",
    [
        (
            {
                "dev_settings": {
                    "cookbook": {"chef_cookbook": "https:///test/aws-parallelcluster-cookbook-3.0.tgz"},
                    "node_package": "s3://test/aws-parallelcluster-node-3.0.tgz",
                    "aws_batch_cli_package": "ftp://test/aws-parallelcluster-batch-3.0.tgz",
                },
            },
            True,
            AWSClientError(
                function_name="head_object",
                message="Failed when accessing object 'aws-parallelcluster-node-3.0.tgz' from bucket 'test'. "
                "This can be due to 'aws-parallelcluster-node-3.0.tgz' not found in 'test'",
            ),
            URLError("[Errno 2] No such file or directory: '/test/aws-parallelcluster-cookbook-3.0.tgz'"),
            [
                "The url 'https:///test/aws-parallelcluster-cookbook-3.0.tgz' causes URLError, the error reason is "
                + "'[Errno 2] No such file or directory: '/test/aws-parallelcluster-cookbook-3.0.tgz''",
                "Failed when accessing object 'aws-parallelcluster-node-3.0.tgz' from bucket 'test'. This can be due "
                + "to 'aws-parallelcluster-node-3.0.tgz' not found in 'test'",
                "The value 'ftp://test/aws-parallelcluster-batch-3.0.tgz' is not a valid URL, choose URL with "
                + "'https' or 's3' prefix.",
            ],
            [FailureLevel.WARNING, FailureLevel.WARNING, FailureLevel.ERROR],
        ),
    ],
)
def test_imagebuilder_url_validator(
    mocker,
    resource,
    url_response,
    url_side_effect,
    url_open_side_effect,
    expected_failure_messages,
    expected_failure_levels,
):
    """Test URLValidator."""
    _test_dev_settings(
        mocker,
        resource,
        url_response,
        url_side_effect,
        url_open_side_effect,
        expected_failure_messages,
        expected_failure_levels,
    )


@pytest.mark.parametrize(
    "resource, dna_json",
    [
        (
            {
                "imagebuilder": {
                    "build": {
                        "parent_image": "ami-0185634c5a8a37250",
                        "instance_type": "c5.xlarge",
                        "update_os_packages": {"enabled": True},
                    },
                    "dev_settings": {
                        "node_package": "s3://test/aws-parallelcluster-node-3.0.tgz",
                        "aws_batch_cli_package": "https://test/aws-parallelcluster-3.0.tgz",
                        "disable_kernel_update": "true",
                    },
                }
            },
            {
                "cluster": {
                    "base_os": "{{ build.OperatingSystemName.outputs.stdout }}",
                    "custom_awsbatchcli_package": "https://test/aws-parallelcluster-3.0.tgz",
                    "custom_node_package": "s3://test/aws-parallelcluster-node-3.0.tgz",
                    "disable_kernel_update": "true",
                    "is_official_ami_build": "false",
                    "nvidia": {"enabled": "no"},
                    "lustre": {"enabled": "yes"},
                    "region": "{{ build.AWSRegion.outputs.stdout }}",
                    "slurm_patches_s3_archive": "",
                }
            },
        ),
        (
            {
                "imagebuilder": {
                    "build": {
                        "parent_image": "ami-0185634c5a8a37250",
                        "instance_type": "c5.xlarge",
                        "installation": {"lustre_client": {"enabled": False}},
                    },
                    "dev_settings": {
                        "cookbook": {
                            "chef_cookbook": "https://test/aws-parallelcluster-cookbook-3.0.tgz",
                            "extra_chef_attributes": '{"cluster": {"nvidia": { "enabled" : "yes" }, "dcv" :"no"}}',
                        },
                        "node_package": "s3://test/aws-parallelcluster-node-3.0.tgz",
                    },
                }
            },
            {
                "cluster": {
                    "base_os": "{{ build.OperatingSystemName.outputs.stdout }}",
                    "custom_awsbatchcli_package": "",
                    "custom_node_package": "s3://test/aws-parallelcluster-node-3.0.tgz",
                    "dcv": "no",
                    "disable_kernel_update": "false",
                    "is_official_ami_build": "false",
                    "lustre": {"enabled": "no"},
                    "nvidia": {"enabled": "yes"},
                    "region": "{{ build.AWSRegion.outputs.stdout }}",
                    "slurm_patches_s3_archive": "",
                }
            },
        ),
        (
            {
                "imagebuilder": {
                    "build": {
                        "parent_image": "ami-0185634c5a8a37250",
                        "instance_type": "c5.xlarge",
                        "installation": {"lustre_client": {"enabled": True}},
                    },
                    "dev_settings": {
                        "cookbook": {
                            "chef_cookbook": "https://test/aws-parallelcluster-cookbook-3.0.tgz",
                            "extra_chef_attributes": '{"cluster": {"nvidia": { "enabled" : "yes" }, "dcv" :"no"}, '
                            '"nfs": "true"}',
                        },
                        "aws_batch_cli_package": "https://test/aws-parallelcluster-3.0.tgz",
                    },
                },
            },
            {
                "cluster": {
                    "base_os": "{{ build.OperatingSystemName.outputs.stdout }}",
                    "custom_awsbatchcli_package": "https://test/aws-parallelcluster-3.0.tgz",
                    "custom_node_package": "",
                    "dcv": "no",
                    "disable_kernel_update": "false",
                    "is_official_ami_build": "false",
                    "nvidia": {"enabled": "yes"},
                    "lustre": {"enabled": "yes"},
                    "region": "{{ build.AWSRegion.outputs.stdout }}",
                    "slurm_patches_s3_archive": "",
                },
                "nfs": "true",
            },
        ),
        (
            {
                "imagebuilder": {
                    "build": {
                        "parent_image": "ami-0185634c5a8a37250",
                        "instance_type": "c5.xlarge",
                        "installation": {"nvidia_software": {"enabled": True}},
                    },
                    "dev_settings": {
                        "cookbook": {
                            "chef_cookbook": "https://test/aws-parallelcluster-cookbook-3.0.tgz",
                            "extra_chef_attributes": '{"cluster": {"is_official_ami_build": "true"},"nfs": "true"}',
                        },
                        "aws_batch_cli_package": "https://test/aws-parallelcluster-3.0.tgz",
                    },
                },
            },
            {
                "cluster": {
                    "base_os": "{{ build.OperatingSystemName.outputs.stdout }}",
                    "custom_awsbatchcli_package": "https://test/aws-parallelcluster-3.0.tgz",
                    "custom_node_package": "",
                    "disable_kernel_update": "false",
                    "is_official_ami_build": "true",
                    "nvidia": {"enabled": "yes"},
                    "lustre": {"enabled": "yes"},
                    "region": "{{ build.AWSRegion.outputs.stdout }}",
                    "slurm_patches_s3_archive": "",
                },
                "nfs": "true",
            },
        ),
        # Test case with URL for Slurm patches from S3
        (
            {
                "imagebuilder": {
                    "build": {
                        "parent_image": "ami-0185634c5a8a37250",
                        "instance_type": "c5.xlarge",
                        "installation": {"nvidia_software": {"enabled": False}},
                    },
                    "dev_settings": {
                        "cookbook": {
                            "extra_chef_attributes": "{"
                            '"cluster": {'
                            '"slurm_patches_s3_archive": "s3://example-s3-bucket/example-archive.tgz"'
                            "}"
                            "}"
                        },
                    },
                }
            },
            {
                "cluster": {
                    "base_os": "{{ build.OperatingSystemName.outputs.stdout }}",
                    "custom_awsbatchcli_package": "",
                    "custom_node_package": "",
                    "disable_kernel_update": "false",
                    "is_official_ami_build": "false",
                    "nvidia": {"enabled": "no"},
                    "lustre": {"enabled": "yes"},
                    "region": "{{ build.AWSRegion.outputs.stdout }}",
                    "slurm_patches_s3_archive": "s3://example-s3-bucket/example-archive.tgz",
                }
            },
        ),
    ],
)
def test_imagebuilder_extra_chef_attributes(resource, dna_json):
    config = imagebuilder_factory(resource).get("imagebuilder")
    chef_attributes = ImageBuilderExtraChefAttributes(config).dump_json()
    assert_that(json.loads(chef_attributes)).is_equal_to(dna_json)


def _test_imagebuilder(
    mocker,
    resource,
    ami_response,
    ami_side_effect,
    instance_response,
    url_response,
    url_side_effect,
    url_open_side_effect,
    supported_architecture,
    expected_failure_messages,
    expected_failure_levels,
):
    mocker.patch("pcluster.imagebuilder_utils.get_ami_id", return_value="ami-0185634c5a8a37250")
    mock_aws_api(mocker)
    mocker.patch("pcluster.aws.ec2.Ec2Client.get_supported_architectures", return_value=supported_architecture)
    mocker.patch(
        "pcluster.aws.ec2.Ec2Client.describe_image", return_value=ImageInfo(ami_response), side_effect=ami_side_effect
    )
    mocker.patch("pcluster.aws.ec2.Ec2Client.list_instance_types", return_value=instance_response)
    mocker.patch("pcluster.aws.s3.S3Client.head_object", return_value=url_response, side_effect=url_side_effect)
    mocker.patch("pcluster.validators.s3_validators.urlopen", side_effect=url_open_side_effect)
    mocker.patch("pcluster.aws.kms.KmsClient.describe_key", return_value=None)

    imagebuilder = imagebuilder_factory(resource).get("imagebuilder")
    validation_failures = imagebuilder.validate()
    for validation_failure, expected_failure_level, expected_failure_message in zip(
        validation_failures, expected_failure_levels, expected_failure_messages
    ):
        assert_validation_result(validation_failure, expected_failure_level, expected_failure_message)


def _test_image(resource, expected_failure_messages, expected_failure_levels):
    image = imagebuilder_factory(resource).get("image")
    validation_failures = image.validate()
    for validation_failure, expected_failure_level, expected_failure_message in zip(
        validation_failures, expected_failure_levels, expected_failure_messages
    ):
        assert_validation_result(validation_failure, expected_failure_level, expected_failure_message)


def _test_build(
    mocker,
    resource,
    ami_response,
    ami_side_effect,
    instance_response,
    supported_architecture,
    expected_failure_messages,
    expected_failure_levels,
):
    mocker.patch("pcluster.imagebuilder_utils.get_ami_id", return_value="ami-0185634c5a8a37250")
    mocker.patch("pcluster.utils.get_supported_architectures_for_instance_type", return_value=supported_architecture)
    mock_aws_api(mocker)
    mocker.patch("pcluster.aws.ec2.Ec2Client.describe_image", return_value=ami_response, side_effect=ami_side_effect)
    mocker.patch("pcluster.aws.ec2.Ec2Client.list_instance_types", return_value=instance_response)

    build = imagebuilder_factory(resource).get("build")
    validation_failures = build.validate()
    for validation_failure, expected_failure_level, expected_failure_message in zip(
        validation_failures, expected_failure_levels, expected_failure_messages
    ):
        assert_validation_result(validation_failure, expected_failure_level, expected_failure_message)


def _test_dev_settings(
    mocker,
    resource,
    url_response,
    url_side_effect,
    url_open_side_effect,
    expected_failure_messages,
    expected_failure_levels,
):
    mock_aws_api(mocker)
    mocker.patch("pcluster.aws.s3.S3Client.head_object", return_value=url_response, side_effect=url_side_effect)
    mocker.patch("pcluster.validators.s3_validators.urlopen", side_effect=url_open_side_effect)

    dev_settings = imagebuilder_factory(resource).get("dev_settings")
    validation_failures = dev_settings.validate()
    for validation_failure, expected_failure_level, expected_failure_message in zip(
        validation_failures, expected_failure_levels, expected_failure_messages
    ):
        assert_validation_result(validation_failure, expected_failure_level, expected_failure_message)


@pytest.mark.parametrize(
    "error, returned_error",
    [
        (BadRequestError(function_name="image_exists", message="test error"), BadRequestImageBuilderActionError),
        (LimitExceededError(function_name="image_exists", message="test error"), LimitExceededImageBuilderActionError),
        (AWSClientError(function_name="image_exists", message="test error"), ImageBuilderActionError),
    ],
)
def test_delete_with_ec2_error(mocker, error, returned_error):
    with pytest.raises(returned_error):
        mock_aws_api(mocker)
        mocker.patch("pcluster.aws.cfn.CfnClient.stack_exists", return_value=False)
        mocker.patch("pcluster.aws.ec2.Ec2Client.image_exists", side_effect=(error))
        ImageBuilder("imageId").delete(force=True)


@pytest.mark.parametrize(
    "error, returned_error",
    [
        (BadRequestError(function_name="image_exists", message="test error"), BadRequestImageBuilderActionError),
        (LimitExceededError(function_name="image_exists", message="test error"), LimitExceededImageBuilderActionError),
        (AWSClientError(function_name="image_exists", message="test error"), ImageBuilderActionError),
    ],
)
def test_delete_with_cfn_error(mocker, error, returned_error):
    with pytest.raises(returned_error):
        mock_aws_api(mocker)
        mocker.patch("pcluster.aws.cfn.CfnClient.stack_exists", side_effect=(error))
        ImageBuilder("imageId").delete(force=True)


@pytest.mark.parametrize(
    "config, expected_result, expected_error_message",
    [
        (None, None, None),
        ("notAYamldict", None, "Configuration must be a valid YAML document"),
        ("malformed\n\nyaml", None, "Configuration must be a valid YAML document"),
        (
            "Build:\n  InstanceType: instanceType\n  ParentImage: arn:parentImage",
            ImageBuilderConfig(build=Build(instance_type="instanceType", parent_image="arn:parentImage")),
            None,
        ),
    ],
    ids=["config text is None", "not a YAML dict", "config text is not valid YAML", "valid config text"],
)
def test_config_object_initialization(config, expected_result, expected_error_message):
    if expected_error_message:
        with pytest.raises(BadRequest, match=expected_error_message):
            _ = ImageBuilder(config=config).config
    elif config is None:
        result = ImageBuilder(config=config).config
        assert_that(result).is_none()
    else:
        result = ImageBuilder(config=config).config
        with soft_assertions():
            assert_that(result.build.instance_type).is_equal_to(expected_result.build.instance_type)
            assert_that(result.build.parent_image).is_equal_to(expected_result.build.parent_image)


class TestImageBuilder:
    @pytest.fixture()
    def image_builder(self, set_env):
        set_env("AWS_DEFAULT_REGION", "us-east-2")
        return ImageBuilder(
            image_id=FAKE_ID,
            stack=ImageBuilderStack({"StackName": FAKE_NAME, "CreationTime": "2021-06-04 10:23:20.199000+00:00"}),
        )

    @pytest.mark.parametrize(
        "stack_exists, expected_error, next_token",
        [
            (False, "Image .* does not exist", None),
            (True, "", None),
            (True, "", "next_token"),
        ],
    )
    def test_get_stack_events(self, image_builder, mocker, stack_exists, expected_error, next_token):
        mock_events = {
            "NextToken": "nxttkn",
            "ResponseMetadata": {
                "HTTPHeaders": {
                    "content-length": "1234",
                    "content-type": "text/xml",
                    "date": "Sun, 25 Jul 2021 21:49:36 GMT",
                    "vary": "accept-encoding",
                    "x-amzn-requestid": "00000000-0000-0000-aaaa-010101010101",
                },
                "HTTPStatusCode": 200,
                "RequestId": "00000000-0000-0000-aaaa-010101010101",
                "RetryAttempts": 0,
            },
            "StackEvents": [
                {
                    "EventId": "44444444-eeee-1111-aaaa-000000000000",
                    "LogicalResourceId": "img",
                    "PhysicalResourceId": "arn:aws:cloudformation:us-east-1:000000000000:stack/img",
                    "ResourceStatus": "UPDATE_COMPLETE",
                    "ResourceType": "AWS::CloudFormation::Stack",
                    "StackId": "arn:aws:cloudformation:us-east-1:000000000000:stack/img",
                    "StackName": "img",
                    "Timestamp": datetime.datetime(2021, 7, 13, 2, 20, 20, 0o00000, tzinfo=tz.tzutc()),
                }
            ],
        }
        stack_exists_mock = mocker.patch(
            "pcluster.models.imagebuilder.ImageBuilder._stack_exists", return_value=stack_exists
        )
        stack_events_mock = mocker.patch("pcluster.aws.cfn.CfnClient.get_stack_events", return_value=mock_events)
        if not stack_exists:
            with pytest.raises(ImageBuilderActionError, match=expected_error):
                image_builder.get_stack_events(next_token)
            stack_exists_mock.assert_called_with()
        else:
            events = image_builder.get_stack_events(next_token)
            stack_events_mock.assert_called_with(image_builder.stack.name, next_token=next_token)
            assert_that(events).is_equal_to(mock_events)

    @pytest.mark.parametrize(
        "stack_exists, log_group_exists, expected_error, kwargs",
        [
            (False, False, "", {}),
            (True, False, "", {}),
            (True, True, "", {}),
            (False, True, "", {}),
            (True, False, "", {"keep_s3_objects": True}),
            (True, True, "", {"output_file": "path"}),
            (True, False, "", {"bucket_prefix": "test_prefix"}),
            (True, True, "", {"bucket_prefix": "test_prefix"}),
        ],
    )
    def test_export_logs(
        self,
        mocker,
        image_builder,
        stack_exists,
        log_group_exists,
        expected_error,
        kwargs,
    ):
        mock_aws_api(mocker)
        stack_exists_mock = mocker.patch(
            "pcluster.models.imagebuilder.ImageBuilder._stack_exists", return_value=stack_exists
        )
        mocker.patch("pcluster.aws.logs.LogsClient.log_group_exists", return_value=log_group_exists)
        download_stack_events_mock = mocker.patch("pcluster.models.imagebuilder.export_stack_events")
        create_logs_archive_mock = mocker.patch("pcluster.models.imagebuilder.create_logs_archive")
        upload_archive_mock = mocker.patch("pcluster.models.imagebuilder.upload_archive")
        presign_mock = mocker.patch("pcluster.models.imagebuilder.create_s3_presigned_url")

        # Following mocks are used only if CW loggins is enabled
        logs_filter_mock = mocker.patch(
            "pcluster.models.imagebuilder.ImageBuilder._init_export_logs_filters",
            return_value=_MockExportImageLogsFiltersParser(),
        )
        cw_logs_exporter_mock = mocker.patch("pcluster.models.imagebuilder.CloudWatchLogsExporter", autospec=True)

        kwargs.update({"bucket": "bucket_name"})
        if expected_error:
            with pytest.raises(ImageBuilderActionError, match=expected_error):
                image_builder.export_logs(**kwargs)
        else:
            image_builder.export_logs(**kwargs)
            stack_exists_mock.assert_called()
            if stack_exists:
                download_stack_events_mock.assert_called()
            else:
                download_stack_events_mock.assert_not_called()

            if log_group_exists:
                cw_logs_exporter_mock.assert_called()
                logs_filter_mock.assert_called()
            else:
                cw_logs_exporter_mock.assert_not_called()
                logs_filter_mock.assert_not_called()
            create_logs_archive_mock.assert_called()

        if "output_file" not in kwargs:
            upload_archive_mock.assert_called()
            presign_mock.assert_called()

    @pytest.mark.parametrize(
        "log_group_exists, client_error, expected_error",
        [
            (False, False, ""),
            (True, False, ""),
            (False, True, ""),
        ],
    )
    def test_list_log_streams(self, image_builder, mocker, log_group_exists, client_error, expected_error):
        mock_aws_api(mocker)
        cw_log_exists_mock = mocker.patch(
            "pcluster.aws.logs.LogsClient.log_group_exists", return_value=log_group_exists
        )
        describe_log_streams_mock = mocker.patch(
            "pcluster.aws.logs.LogsClient.describe_log_streams",
            side_effect=AWSClientError("describe_log_streams", "error") if client_error else None,
        )

        if expected_error or not log_group_exists:
            with pytest.raises(ImageBuilderActionError, match=expected_error):
                image_builder.list_log_streams()
        else:
            # Note: client error for describe_log_streams doesn't raise an exception
            image_builder.list_log_streams()

        # check steps
        cw_log_exists_mock.assert_called()
        if log_group_exists:
            describe_log_streams_mock.assert_called()
        else:
            describe_log_streams_mock.assert_not_called()

    @pytest.mark.parametrize(
        "log_stream_name, stack_exists, client_error, expected_error",
        [
            ("log-stream", False, False, ""),
            ("log-stream", True, True, "Unexpected error when retrieving log events"),
            ("log-stream", True, False, ""),
        ],
    )
    def test_get_log_events(self, image_builder, mocker, log_stream_name, stack_exists, client_error, expected_error):
        mock_aws_api(mocker)
        stack_exists_mock = mocker.patch(
            "pcluster.models.imagebuilder.ImageBuilder._stack_exists", return_value=stack_exists
        )
        get_stack_events_mock = mocker.patch(
            "pcluster.aws.cfn.CfnClient.get_stack_events",
            side_effect=AWSClientError("get_log_events", "error") if client_error else None,
        )
        get_log_events_mock = mocker.patch(
            "pcluster.aws.logs.LogsClient.get_log_events",
            side_effect=AWSClientError("get_log_events", "error") if client_error else None,
        )

        if expected_error or client_error:
            with pytest.raises(ImageBuilderActionError, match=expected_error):
                image_builder.get_log_events(log_stream_name)
        else:
            image_builder.get_log_events(log_stream_name)

        if log_stream_name == f"{FAKE_ID}-cfn-events":
            stack_exists_mock.assert_called()
            if stack_exists:
                get_stack_events_mock.assert_called()
            else:
                get_stack_events_mock.assert_not_called()
        else:
            stack_exists_mock.assert_not_called()
            get_stack_events_mock.assert_not_called()
            get_log_events_mock.assert_called()


class _MockExportImageLogsFiltersParser:
    def __init__(self):
        self._log_group_name = None
        self.log_stream_prefix = None
        self.start_time = 0
        self.end_time = 0
