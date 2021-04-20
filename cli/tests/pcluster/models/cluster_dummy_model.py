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
from typing import List
from unittest.mock import PropertyMock

from pcluster.config.cluster_config import (
    AwsBatchClusterConfig,
    AwsBatchComputeResource,
    AwsBatchQueue,
    AwsBatchScheduling,
    ClusterIam,
    Dcv,
    HeadNode,
    HeadNodeNetworking,
    Iam,
    Image,
    QueueNetworking,
    Raid,
    S3Access,
    SharedEbs,
    SharedEfs,
    SharedFsx,
    SlurmClusterConfig,
    SlurmComputeResource,
    SlurmQueue,
    SlurmScheduling,
    Ssh,
    Tag,
)
from pcluster.config.common import Resource, S3Bucket


class _DummySlurmClusterConfig(SlurmClusterConfig):
    """Generate dummy Slurm cluster config."""

    def __init__(self, scheduling: SlurmScheduling, **kwargs):
        super().__init__(scheduling, **kwargs)

    @property
    def region(self):
        return "us-east-1"

    @property
    def partition(self):
        return "aws"

    @property
    def vpc_id(self):
        return "dummy_vpc_id"


class _DummyAwsBatchClusterConfig(AwsBatchClusterConfig):
    """Generate dummy Slurm cluster config."""

    def __init__(self, scheduling: AwsBatchScheduling, **kwargs):
        super().__init__(scheduling, **kwargs)

    @property
    def region(self):
        return "us-east-1"

    @property
    def partition(self):
        return "aws"

    @property
    def vpc_id(self):
        return "dummy_vpc_id"


def dummy_cluster_bucket(
    bucket_name="parallelcluster-a69601b5ee1fc2f2-v1-do-not-delete",
    artifact_directory="parallelcluster/clusters/dummy-cluster-randomstring123",
    service_name="dummy-cluster",
):
    """Generate dummy cluster bucket."""
    return S3Bucket(
        name=bucket_name,
        stack_name=f"parallelcluster-{service_name}",
        service_name=service_name,
        artifact_directory=artifact_directory,
    )


def mock_bucket(
    mocker,
):
    """Mock cluster bucket initialization."""
    mocker.patch("pcluster.config.common.get_partition", return_value="fake_partition")
    mocker.patch("pcluster.config.common.get_region", return_value="fake-region")
    mocker.patch("common.boto3.sts.StsClient.get_account_id", return_value="fake-id")


def mock_bucket_utils(
    mocker,
    bucket_name="parallelcluster-a69601b5ee1fc2f2-v1-do-not-delete",
    root_service_dir="dummy-cluster-randomstring123",
    check_bucket_exists_side_effect=None,
    create_bucket_side_effect=None,
    configure_bucket_side_effect=None,
):
    get_bucket_name_mock = mocker.patch("pcluster.config.common.S3Bucket.get_bucket_name", return_value=bucket_name)
    create_bucket_mock = mocker.patch(
        "pcluster.config.common.S3Bucket.create_bucket", side_effect=create_bucket_side_effect
    )
    check_bucket_exists_mock = mocker.patch(
        "pcluster.config.common.S3Bucket.check_bucket_exists", side_effect=check_bucket_exists_side_effect
    )
    mocker.patch("pcluster.config.common.S3Bucket.generate_s3_bucket_hash_suffix", return_value=root_service_dir)
    configure_s3_bucket_mock = mocker.patch(
        "pcluster.config.common.S3Bucket.configure_s3_bucket", side_effect=configure_bucket_side_effect
    )
    mock_dict = {
        "get_bucket_name": get_bucket_name_mock,
        "create_bucket": create_bucket_mock,
        "check_bucket_exists": check_bucket_exists_mock,
        "configure_s3_bucket": configure_s3_bucket_mock,
    }
    return mock_dict


def mock_bucket_object_utils(
    mocker,
    upload_config_side_effect=None,
    get_config_side_effect=None,
    upload_template_side_effect=None,
    get_template_side_effect=None,
    upload_resources_side_effect=None,
    delete_s3_artifacts_side_effect=None,
    upload_bootstrapped_file_side_effect=None,
    check_bucket_is_bootstrapped_side_effect=None,
):
    # mock call from config
    fake_config = {"Image": "image"}
    upload_config_mock = mocker.patch(
        "pcluster.config.common.S3Bucket.upload_config", side_effect=upload_config_side_effect
    )
    get_config_mock = mocker.patch(
        "pcluster.config.common.S3Bucket.get_config", return_value=fake_config, side_effect=get_config_side_effect
    )

    # mock call from template
    fake_template = {"Resources": "fake_resource"}
    upload_cfn_template_mock = mocker.patch(
        "pcluster.config.common.S3Bucket.upload_cfn_template", side_effect=upload_template_side_effect
    )
    get_cfn_template_mock = mocker.patch(
        "pcluster.config.common.S3Bucket.get_cfn_template",
        return_value=fake_template,
        side_effect=get_template_side_effect,
    )

    # mock calls from custom resources
    upload_resources_mock = mocker.patch(
        "pcluster.config.common.S3Bucket.upload_resources", side_effect=upload_resources_side_effect
    )

    # mock delete_s3_artifacts
    delete_s3_artifacts_mock = mocker.patch(
        "pcluster.config.common.S3Bucket.delete_s3_artifacts", side_effect=delete_s3_artifacts_side_effect
    )

    # mock bootstrapped_file
    upload_bootstrapped_file_mock = mocker.patch(
        "pcluster.config.common.S3Bucket.upload_bootstrapped_file", side_effect=upload_bootstrapped_file_side_effect
    )
    check_bucket_is_bootstrapped_mock = mocker.patch(
        "pcluster.config.common.S3Bucket.check_bucket_is_bootstrapped",
        side_effect=check_bucket_is_bootstrapped_side_effect,
    )

    mock_dict = {
        "upload_config": upload_config_mock,
        "get_config": get_config_mock,
        "upload_cfn_template": upload_cfn_template_mock,
        "get_cfn_template": get_cfn_template_mock,
        "upload_resources": upload_resources_mock,
        "delete_s3_artifacts": delete_s3_artifacts_mock,
        "upload_bootstrapped_file": upload_bootstrapped_file_mock,
        "check_bucket_is_bootstrapped": check_bucket_is_bootstrapped_mock,
    }

    return mock_dict


def dummy_head_node(mocker):
    """Generate dummy head node."""
    mocker.patch(
        "pcluster.config.cluster_config.HeadNodeNetworking.availability_zone",
        new_callable=PropertyMock(return_value="us-east-1a"),
    )
    head_node_networking = HeadNodeNetworking(subnet_id="dummy-subnet-1")
    head_node_networking.assign_public_ip = True
    head_node_networking.additional_security_groups = ["additional-dummy-sg-1"]
    head_node_dcv = Dcv(enabled=True, port=1024)
    ssh = Ssh(key_name="test")

    head_node = HeadNode(instance_type="fake", networking=head_node_networking, ssh=ssh, dcv=head_node_dcv)

    disable_ht_cpu_opts_mock = mocker.PropertyMock(return_value="true")
    mocker.patch(
        "pcluster.config.cluster_config.HeadNode.disable_simultaneous_multithreading_via_cpu_options",
        new_callable=disable_ht_cpu_opts_mock,
    )
    return head_node


def dummy_slurm_cluster_config(mocker):
    """Generate dummy cluster."""
    image = Image(os="alinux2")
    head_node = dummy_head_node(mocker)
    queue_iam = Iam(
        s3_access=[
            S3Access("dummy-readonly-bucket", enable_write_access=True),
            S3Access("dummy-readwrite-bucket"),
        ]
    )
    compute_resources = [SlurmComputeResource(name="dummy_compute_resource1", instance_type="dummyc5.xlarge")]
    queue_networking1 = QueueNetworking(subnet_ids=["dummy-subnet-1"], security_groups=["sg-1", "sg-2"])
    queue_networking2 = QueueNetworking(subnet_ids=["dummy-subnet-1"], security_groups=["sg-1", "sg-3"])
    queue_networking3 = QueueNetworking(subnet_ids=["dummy-subnet-1"], security_groups=None)
    queues = [
        SlurmQueue(name="queue1", networking=queue_networking1, compute_resources=compute_resources, iam=queue_iam),
        SlurmQueue(name="queue2", networking=queue_networking2, compute_resources=compute_resources),
        SlurmQueue(name="queue3", networking=queue_networking3, compute_resources=compute_resources),
    ]
    scheduling = SlurmScheduling(queues=queues)
    # shared storage
    shared_storage: List[Resource] = []
    shared_storage.append(dummy_fsx())
    shared_storage.append(dummy_ebs("/ebs1"))
    shared_storage.append(dummy_ebs("/ebs2", volume_id="vol-abc"))
    shared_storage.append(dummy_ebs("/ebs3", raid=Raid(raid_type=1, number_of_volumes=5)))
    shared_storage.append(dummy_efs("/efs1", file_system_id="fs-efs-1"))
    shared_storage.append(dummy_raid("/raid1"))

    cluster = _DummySlurmClusterConfig(
        image=image, head_node=head_node, scheduling=scheduling, shared_storage=shared_storage
    )
    cluster.custom_s3_bucket = "s3://dummy-s3-bucket"
    cluster.additional_resources = "https://additional.template.url"
    cluster.config_version = "1.0"
    cluster.iam = ClusterIam()

    cluster.tags = [Tag(key="test", value="testvalue")]
    return cluster


def dummy_awsbatch_cluster_config(mocker):
    """Generate dummy cluster."""
    image = Image(os="alinux2")
    head_node = dummy_head_node(mocker)
    compute_resources = [
        AwsBatchComputeResource(name="dummy_compute_resource1", instance_types="dummyc5.xlarge,optimal")
    ]
    queue_networking = QueueNetworking(subnet_ids=["dummy-subnet-1"], security_groups=["sg-1", "sg-2"])
    queues = [AwsBatchQueue(name="queue1", networking=queue_networking, compute_resources=compute_resources)]
    scheduling = AwsBatchScheduling(queues=queues)
    # shared storage
    shared_storage: List[Resource] = []
    shared_storage.append(dummy_fsx())
    shared_storage.append(dummy_ebs("/ebs1"))
    shared_storage.append(dummy_ebs("/ebs2", volume_id="vol-abc"))
    shared_storage.append(dummy_ebs("/ebs3", raid=Raid(raid_type=1, number_of_volumes=5)))
    shared_storage.append(dummy_efs("/efs1", file_system_id="fs-efs-1"))
    shared_storage.append(dummy_raid("/raid1"))

    cluster = _DummyAwsBatchClusterConfig(
        image=image, head_node=head_node, scheduling=scheduling, shared_storage=shared_storage
    )
    cluster.custom_s3_bucket = "s3://dummy-s3-bucket"
    cluster.additional_resources = "https://additional.template.url"
    cluster.config_version = "1.0"
    cluster.iam = ClusterIam()

    cluster.tags = [Tag(key="test", value="testvalue")]
    return cluster


def dummy_fsx(file_system_id=None, mount_dir="/shared", name="name"):
    """Generate dummy fsx."""
    return SharedFsx(
        mount_dir=mount_dir,
        name=name,
        file_system_id=file_system_id,
        storage_capacity=300,
        deployment_type="SCRATCH_1",
        imported_file_chunk_size=1024,
        export_path="s3://bucket/folder",
        import_path="s3://bucket/folder",
        weekly_maintenance_start_time="1:00:00",
        automatic_backup_retention_days=0,
        copy_tags_to_backups=True,
        daily_automatic_backup_start_time="01:03",
        per_unit_storage_throughput=200,
        backup_id="backup-fedcba98",
        kms_key_id="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
        auto_import_policy="NEW",
        drive_cache_type="READ",
        fsx_storage_type="HDD",
    )


def dummy_ebs(mount_dir, name="name", volume_id=None, raid=None):
    return SharedEbs(
        mount_dir=mount_dir,
        name=name,
        kms_key_id="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
        snapshot_id="snapshot-abdcef76",
        volume_type="gp2",
        throughput=300,
        volume_id=volume_id,
        raid=raid,
    )


def dummy_raid(mount_dir, name="name", volume_id=None):
    return SharedEbs(
        mount_dir=mount_dir,
        name="name",
        kms_key_id="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
        snapshot_id="snapshot-abdcef76",
        volume_type="gp2",
        throughput=300,
        volume_id=volume_id,
        raid=Raid(raid_type=1),
    )


def dummy_efs(mount_dir, name="name", file_system_id=None):
    return SharedEfs(
        mount_dir=mount_dir,
        name=name,
        encrypted=False,
        kms_key_id="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
        performance_mode="generalPurpose",
        throughput_mode="provisioned",
        provisioned_throughput=500,
        file_system_id=file_system_id,
    )
