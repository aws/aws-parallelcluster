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

from pcluster.aws.aws_resources import ImageInfo
from pcluster.constants import (
    PCLUSTER_IMAGE_BUILD_LOG_TAG,
    PCLUSTER_IMAGE_CONFIG_TAG,
    PCLUSTER_IMAGE_ID_TAG,
    PCLUSTER_S3_BUCKET_TAG,
    PCLUSTER_S3_IMAGE_DIR_TAG,
    PCLUSTER_VERSION_TAG,
)
from pcluster.models.imagebuilder import ImageBuilderStack
from pcluster.utils import get_installed_version
from tests.pcluster.aws.dummy_aws_api import mock_aws_api

FAKE_IMAGEBUILDER_STACK_NAME = "pcluster1"


@pytest.mark.parametrize(
    "stack_resources_response, describe_image_response, expected_image_property_value",
    [
        (
            {
                "StackResourceDetail": {
                    "PhysicalResourceId": "arn:aws:imagebuilder:us-east-1:xxxxxxxxxxxx:image"
                    "/parallelclusterimagerecipe-7473d4s2otwynhxr/2.10.1/1"
                }
            },
            {
                "Architecture": "x86_64",
                "CreationDate": "2021-03-02T22:00:22.000Z",
                "ImageId": "ami-043568239021c18cb",
                "ImageLocation": "xxxxxxxxxxxx/pcluster1 2021-03-02T21-28-19.945Z",
                "ImageType": "machine",
                "Public": False,
                "OwnerId": "xxxxxxxxxxxx",
                "PlatformDetails": "Linux/UNIX",
                "UsageOperation": "RunInstances",
                "State": "available",
                "BlockDeviceMappings": [
                    {
                        "DeviceName": "/dev/xvda",
                        "Ebs": {
                            "DeleteOnTermination": True,
                            "SnapshotId": "snap-0d34320a1c1683c70",
                            "VolumeSize": 65,
                            "VolumeType": "gp2",
                            "Encrypted": False,
                        },
                    },
                    {"DeviceName": "/dev/sdb", "VirtualName": "ephemeral0"},
                    {"DeviceName": "/dev/sdc", "VirtualName": "ephemeral1"},
                ],
                "Description": "AWS ParallelCluster AMI for alinux2, kernel-4.14.203-156.332.amzn2.x86_64, "
                "lustre-client-2.10.8-5.amzn2.x86_64, nice-dcv-server-2020.2.9662-1.el7.x86_64, "
                "slurm-20.02.4, nvidia-450.80.02",
                "EnaSupport": True,
                "Hypervisor": "xen",
                "Name": "pcluster1 2021-03-02T21-28-19.945Z",
                "RootDeviceName": "/dev/xvda",
                "RootDeviceType": "ebs",
                "SriovNetSupport": "simple",
                "Tags": [
                    {"Key": "parallelcluster_os", "Value": "alinux2"},
                    {"Key": "CreatedBy", "Value": "EC2 Image Builder"},
                    {"Key": "parallelcluster_dcv_server", "Value": "nice-dcv-server-2020.2.9662-1.el7.x86_64"},
                    {"Key": "parallelcluster_efa_profile", "Value": "efa-profile-1.1-1.amzn2.noarch"},
                    {"Key": "parallelcluster_munge", "Value": "munge-0.5.14"},
                    {
                        "Key": "Ec2ImageBuilderArn",
                        "Value": "arn:aws:imagebuilder:us-east-1:xxxxxxxxxxxx:image/parallelclusterimagerecipe-"
                        "87ofwi610f0aiktu/2.10.1/1",
                    },
                    {"Key": "parallelcluster_bootstrap_file", "Value": "aws-parallelcluster-cookbook-2.10.1"},
                    {"Key": "parallelcluster_nvidia", "Value": "nvidia-450.80.02"},
                    {"Key": "parallelcluster_version", "Value": "2.10.1"},
                    {"Key": "parallelcluster_pmix", "Value": "pmix-3.1.5"},
                    {"Key": "parallelcluster_efa_openmpi40_aws", "Value": "openmpi40-aws-4.0.5-1.amzn2.x86_64"},
                    {"Key": "parallelcluster_kernel", "Value": "4.14.203-156.332.amzn2.x86_64"},
                    {"Key": "parallelcluster_dcv_xdcv", "Value": "nice-xdcv-2020.2.359-1.el7.x86_64"},
                    {"Key": "parallelcluster_efa_rdma_core", "Value": "rdma-core-31.amzn0-1.amzn2.x86_64"},
                    {"Key": "parallelcluster_sudo", "Value": "sudo-1.8.23-10.amzn2.1.x86_64"},
                    {"Key": "parallelcluster_slurm", "Value": "slurm-20.02.4"},
                    {"Key": "parallelcluster_lustre", "Value": "lustre-client-2.10.8-5.amzn2.x86_64"},
                    {"Key": "parallelcluster_efa_config", "Value": "efa-config-1.5-1.amzn2.noarch"},
                    {"Key": PCLUSTER_S3_BUCKET_TAG, "Value": "my_bucket"},
                    {"Key": PCLUSTER_S3_IMAGE_DIR_TAG, "Value": "parallelcluster/images/image-abced"},
                    {"Key": PCLUSTER_IMAGE_BUILD_LOG_TAG, "Value": "arn:aws:log:us-east-1:1111111111111:log-group"},
                    {"Key": PCLUSTER_VERSION_TAG, "Value": get_installed_version()},
                    {"Key": PCLUSTER_IMAGE_ID_TAG, "Value": FAKE_IMAGEBUILDER_STACK_NAME},
                    {"Key": PCLUSTER_IMAGE_CONFIG_TAG, "Value": "s3://my_bucket/config_key"},
                ],
                "VirtualizationType": "hvm",
            },
            {
                "snapshot_ids": ["snap-0d34320a1c1683c70"],
                "volume_size": 65,
                "device_name": "/dev/xvda",
                "s3_bucket_name": "my_bucket",
                "s3_artifact_directory": "parallelcluster/images/image-abced",
                "build_log": "arn:aws:log:us-east-1:1111111111111:log-group",
                "version": get_installed_version(),
                "pcluster_image_id": FAKE_IMAGEBUILDER_STACK_NAME,
                "config_url": "s3://my_bucket/config_key",
            },
        )
    ],
)
def test_image(mocker, stack_resources_response, describe_image_response, expected_image_property_value):
    mock_aws_api(mocker)
    mocker.patch(
        "pcluster.aws.cfn.CfnClient.describe_stack_resource",
        return_value=stack_resources_response,
    )
    mocker.patch("pcluster.aws.imagebuilder.ImageBuilderClient.get_image_id", return_value="ami-06b66530ba9f43a96")
    mocker.patch("pcluster.aws.ec2.Ec2Client.describe_image", return_value=ImageInfo(describe_image_response))
    imagebuilder_stack = ImageBuilderStack({"StackName": FAKE_IMAGEBUILDER_STACK_NAME})
    image = imagebuilder_stack.image
    for p in image.__dir__():
        if not p.startswith("_"):
            if p not in expected_image_property_value.keys():
                assert_that(getattr(image, p) in describe_image_response.values()).is_equal_to(True)
            else:
                assert_that(getattr(image, p)).is_equal_to(expected_image_property_value.get(p))
