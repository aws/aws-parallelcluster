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
    AwsBatchQueueNetworking,
    AwsBatchScheduling,
    ClusterIam,
    CustomAction,
    CustomActions,
    Dcv,
    HeadNode,
    HeadNodeNetworking,
    HeadNodeSsh,
    Iam,
    Image,
    Imds,
    LoginNodes,
    LoginNodesNetworking,
    LoginNodesPool,
    LoginNodesSsh,
    Proxy,
    Raid,
    S3Access,
    SharedEbs,
    SharedEfs,
    SharedFsxLustre,
    SlurmClusterConfig,
    SlurmComputeResource,
    SlurmQueue,
    SlurmQueueNetworking,
    SlurmScheduling,
    Tag,
)
from pcluster.config.common import Resource


class _DummySlurmClusterConfig(SlurmClusterConfig):
    """Generate dummy Slurm cluster config."""

    def __init__(self, scheduling: SlurmScheduling, login_nodes: LoginNodes, **kwargs):
        super().__init__("clustername", scheduling, login_nodes, **kwargs)

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
        super().__init__("clustername", scheduling, **kwargs)

    @property
    def region(self):
        return "us-east-1"

    @property
    def partition(self):
        return "aws"

    @property
    def vpc_id(self):
        return "dummy_vpc_id"


def dummy_head_node(mocker):
    """Generate dummy head node."""
    mocker.patch(
        "pcluster.config.cluster_config.HeadNodeNetworking.availability_zone",
        new_callable=PropertyMock(return_value="us-east-1a"),
    )
    head_node_networking = HeadNodeNetworking(
        subnet_id="dummy-subnet-1", proxy=Proxy(http_proxy_address="http://10.0.0.164:3129")
    )
    head_node_networking.additional_security_groups = ["additional-dummy-sg-1"]
    head_node_dcv = Dcv(enabled=True, port=1024)
    head_node_imds = Imds(secured=True)
    ssh = HeadNodeSsh(key_name="test")

    custom_actions = CustomActions(
        on_node_start=[
            CustomAction(script="https://tests1", args=["arg1", "arg2"]),
            CustomAction(script="https://tests2", args=["arg1", "arg2"]),
        ],
        on_node_updated=CustomAction(script="https://testus", args=["arg1", "arg2"]),
        on_node_configured=None,
    )

    head_node = HeadNode(
        instance_type="fake",
        networking=head_node_networking,
        ssh=ssh,
        dcv=head_node_dcv,
        imds=head_node_imds,
        custom_actions=custom_actions,
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
    queue_networking1 = SlurmQueueNetworking(subnet_ids=["dummy-subnet-1"], security_groups=["sg-1", "sg-2"])
    queue_networking2 = SlurmQueueNetworking(subnet_ids=["dummy-subnet-1"], security_groups=["sg-1", "sg-3"])
    queue_networking3 = SlurmQueueNetworking(subnet_ids=["dummy-subnet-1"], security_groups=None)
    queues = [
        SlurmQueue(name="queue1", networking=queue_networking1, compute_resources=compute_resources, iam=queue_iam),
        SlurmQueue(name="queue2", networking=queue_networking2, compute_resources=compute_resources),
        SlurmQueue(name="queue3", networking=queue_networking3, compute_resources=compute_resources),
    ]
    scheduling = SlurmScheduling(queues=queues)
    pools = [
        LoginNodesPool(
            name="loginnode1",
            instance_type="t2.micro",
            networking=LoginNodesNetworking(subnet_ids=["subnet-12345678"]),
            count=1,
            ssh=LoginNodesSsh(key_name="validkeyname"),
        )
    ]
    login_nodes = LoginNodes(pools=pools)
    # shared storage
    shared_storage: List[Resource] = []
    shared_storage.append(dummy_fsx())
    shared_storage.append(dummy_ebs("/ebs1"))
    shared_storage.append(dummy_ebs("/ebs2", volume_id="vol-abc"))
    shared_storage.append(dummy_ebs("/ebs3", raid=Raid(raid_type=1, number_of_volumes=5)))
    shared_storage.append(dummy_efs("/efs1", file_system_id="fs-efs-1"))
    shared_storage.append(dummy_raid("/raid1"))

    cluster = _DummySlurmClusterConfig(
        image=image, head_node=head_node, scheduling=scheduling, login_nodes=login_nodes, shared_storage=shared_storage
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
        AwsBatchComputeResource(name="dummy_compute_resource1", instance_types=["dummyc5.xlarge", "optimal"])
    ]
    queue_networking = AwsBatchQueueNetworking(subnet_ids=["dummy-subnet-1"], security_groups=["sg-1", "sg-2"])
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
    return SharedFsxLustre(
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
