# Copyright 2020 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License").
# You may not use this file except in compliance with the License.
# A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file.
# This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, express or implied.
# See the License for the specific language governing permissions and limitations under the License.
import boto3
import pytest
from remote_command_executor import RemoteCommandExecutor

from tests.common.utils import retrieve_latest_ami


@pytest.mark.dimensions("eu-west-1", "m6g.xlarge", "alinux2", "slurm")
@pytest.mark.usefixtures("instance", "scheduler")
def test_runtime_bake(
    request,
    scheduler,
    os,
    region,
    pcluster_config_reader,
    clusters_factory,
    test_datadir,
    architecture,
    s3_bucket_factory,
    amis_dict,
):
    """Test cluster creation with runtime bake."""
    # Remarkable AMIs are not available for ARM yet
    # Disable centos7 remarkable AMIs, because FPGA AMI's volume size is not enough.
    # Use official AMI with ubuntu2004 because DLAMI is not available yet
    if architecture == "x86_64" and os not in ["centos7", "ubuntu2004"]:
        custom_ami = retrieve_latest_ami(region, os, ami_type="remarkable", architecture=architecture)
    else:
        custom_ami = retrieve_latest_ami(region, os, architecture=architecture)

    # Custom Cookbook and Node
    custom_cookbook = request.config.getoption("createami_custom_chef_cookbook")
    custom_node = request.config.getoption("createami_custom_node_package")

    # Create S3 bucket for pre install scripts, to remove epel package if it is installed
    bucket_name = s3_bucket_factory()
    bucket = boto3.resource("s3", region_name=region).Bucket(bucket_name)
    bucket.upload_file(str(test_datadir / "pre-install.sh"), "scripts/pre-install.sh")

    cluster_config = pcluster_config_reader(
        bucket_name=bucket_name,
        custom_ami=custom_ami,
        custom_cookbook=custom_cookbook if custom_cookbook else "",
        custom_node=custom_node if custom_node else "",
    )
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)

    # Verify epel installed on centos during runtime bake
    if os in ["centos7"]:
        remote_command_executor.run_remote_script(str(test_datadir / "verify_epel.sh"))
