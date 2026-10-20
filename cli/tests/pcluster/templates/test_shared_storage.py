# Copyright 2022 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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

from pcluster.aws.common import AWSClientError
from pcluster.config.cluster_config import ExistingFileCache, ExistingFsxOpenZfs
from pcluster.schemas.cluster_schema import ClusterSchema
from pcluster.templates.cdk_builder import CDKTemplateBuilder
from pcluster.utils import load_yaml_dict
from tests.pcluster.aws.dummy_aws_api import _DummyAWSApi, _DummyInstanceTypeInfo, mock_aws_api
from tests.pcluster.models.dummy_s3_bucket import dummy_cluster_bucket, mock_bucket_object_utils
from tests.pcluster.utils import assert_sg_rule, get_head_node_policy, get_resources, get_statement_by_sid


@pytest.mark.parametrize(
    "config_file_name, storage_name, deletion_policy",
    [
        ("config.yaml", "shared-ebs-managed-1", "Delete"),
        ("config.yaml", "shared-ebs-managed-2", "Delete"),
        ("config.yaml", "shared-ebs-managed-3", "Retain"),
    ],
)
def test_shared_storage_ebs(mocker, test_datadir, config_file_name, storage_name, deletion_policy):
    mock_aws_api(mocker)
    mock_bucket_object_utils(mocker)

    input_yaml = load_yaml_dict(test_datadir / config_file_name)

    cluster_config = ClusterSchema(cluster_name="clustername").load(input_yaml)

    generated_template, _ = CDKTemplateBuilder().build_cluster_template(
        cluster_config=cluster_config, bucket=dummy_cluster_bucket(), stack_name="clustername"
    )

    volumes = get_resources(
        generated_template, type="AWS::EC2::Volume", properties={"Tags": [{"Key": "Name", "Value": storage_name}]}
    )
    assert_that(volumes).is_length(1)

    volume = next(iter(volumes.values()))
    assert_that(volume["DeletionPolicy"]).is_equal_to(deletion_policy)
    assert_that(volume["UpdateReplacePolicy"]).is_equal_to(deletion_policy)


@pytest.mark.parametrize(
    "config_file_name, storage_name, deletion_policy",
    [
        ("config.yaml", "shared-efs-managed-1", "Delete"),
        ("config.yaml", "shared-efs-managed-2", "Delete"),
        ("config.yaml", "shared-efs-managed-3", "Retain"),
        ("config-custom-sg.yaml", "shared-efs-managed-1", "Delete"),
    ],
)
def test_shared_storage_efs(mocker, test_datadir, config_file_name, storage_name, deletion_policy):
    mock_aws_api(mocker)
    mock_bucket_object_utils(mocker)

    input_yaml = load_yaml_dict(test_datadir / config_file_name)

    cluster_config = ClusterSchema(cluster_name="clustername").load(input_yaml)

    generated_template, _ = CDKTemplateBuilder().build_cluster_template(
        cluster_config=cluster_config, bucket=dummy_cluster_bucket(), stack_name="clustername"
    )
    file_systems = get_resources(
        generated_template,
        type="AWS::EFS::FileSystem",
        properties={"FileSystemTags": [{"Key": "Name", "Value": storage_name}]},
    )

    assert_that(file_systems).is_length(1)

    file_system_name = next(iter(file_systems.keys()))
    file_system = file_systems[file_system_name]
    assert_that(file_system["DeletionPolicy"]).is_equal_to(deletion_policy)
    assert_that(file_system["UpdateReplacePolicy"]).is_equal_to(deletion_policy)

    mount_targets = get_resources(
        generated_template, type="AWS::EFS::MountTarget", properties={"FileSystemId": {"Ref": file_system_name}}
    )

    assert_that(mount_targets).is_length(1)

    mount_target = next(iter(mount_targets.values()))
    assert_that(mount_target["DeletionPolicy"]).is_equal_to(deletion_policy)
    assert_that(mount_target["UpdateReplacePolicy"]).is_equal_to(deletion_policy)

    mount_target_sg_name = mount_target["Properties"]["SecurityGroups"][0]["Ref"]
    mount_target_sg = generated_template["Resources"][mount_target_sg_name]
    assert_that(mount_target_sg["DeletionPolicy"]).is_equal_to(deletion_policy)
    assert_that(mount_target_sg["UpdateReplacePolicy"]).is_equal_to(deletion_policy)

    login_nodes_networking = cluster_config.login_nodes.pools[0].networking
    login_nodes_sg_name = (
        login_nodes_networking.security_groups[0]
        if login_nodes_networking.security_groups
        else f"{cluster_config.login_nodes.pools[0].name}LoginNodesSecurityGroup"
    )
    for sg in ["HeadNodeSecurityGroup", "ComputeSecurityGroup", login_nodes_sg_name, mount_target_sg_name]:
        ingress_ip_protocol = "tcp" if sg == login_nodes_sg_name else "-1"
        ingress_port_range = [2049, 2049] if sg == login_nodes_sg_name else [0, 65535]
        rule_deletion_policy = deletion_policy if sg == mount_target_sg_name else None
        assert_sg_rule(
            generated_template,
            mount_target_sg_name,
            rule_type="ingress",
            protocol=ingress_ip_protocol,
            port_range=ingress_port_range,
            target_sg=sg,
            deletion_policy=rule_deletion_policy,
        )
        assert_sg_rule(
            generated_template,
            mount_target_sg_name,
            rule_type="egress",
            protocol="-1",
            port_range=[0, 65535],
            target_sg=sg,
            deletion_policy=rule_deletion_policy,
        )


@pytest.mark.parametrize(
    "config_file_name, storage_name, fs_type, deletion_policy",
    [
        ("config.yaml", "shared-fsx-lustre-managed-1", "LUSTRE", "Delete"),
        ("config.yaml", "shared-fsx-lustre-managed-2", "LUSTRE", "Delete"),
        ("config.yaml", "shared-fsx-lustre-managed-3", "LUSTRE", "Retain"),
        ("config-custom-sg.yaml", "shared-fsx-lustre-managed-1", "LUSTRE", "Delete"),
    ],
)
def test_shared_storage_fsx(mocker, test_datadir, config_file_name, storage_name, fs_type, deletion_policy):
    mock_aws_api(mocker)
    mock_bucket_object_utils(mocker)

    input_yaml = load_yaml_dict(test_datadir / config_file_name)

    cluster_config = ClusterSchema(cluster_name="clustername").load(input_yaml)

    generated_template, _ = CDKTemplateBuilder().build_cluster_template(
        cluster_config=cluster_config, bucket=dummy_cluster_bucket(), stack_name="clustername"
    )

    file_systems = get_resources(
        generated_template, type="AWS::FSx::FileSystem", properties={"Tags": [{"Key": "Name", "Value": storage_name}]}
    )
    assert_that(file_systems).is_length(1)

    file_system = next(iter(file_systems.values()))
    assert_that(file_system["Properties"]["FileSystemType"]).is_equal_to(fs_type)
    assert_that(file_system["DeletionPolicy"]).is_equal_to(deletion_policy)
    assert_that(file_system["UpdateReplacePolicy"]).is_equal_to(deletion_policy)

    file_system_sg_name = file_system["Properties"]["SecurityGroupIds"][0]["Ref"]
    file_system_sg = generated_template["Resources"][file_system_sg_name]
    assert_that(file_system_sg["DeletionPolicy"]).is_equal_to(deletion_policy)
    assert_that(file_system_sg["UpdateReplacePolicy"]).is_equal_to(deletion_policy)

    login_nodes_networking = cluster_config.login_nodes.pools[0].networking
    login_nodes_sg_name = (
        login_nodes_networking.security_groups[0]
        if login_nodes_networking.security_groups
        else f"{cluster_config.login_nodes.pools[0].name}LoginNodesSecurityGroup"
    )
    for sg in ["HeadNodeSecurityGroup", "ComputeSecurityGroup", login_nodes_sg_name, file_system_sg_name]:
        ingress_ip_protocol = "tcp" if sg == login_nodes_sg_name else "-1"
        ingress_port_range = [988, 988] if sg == login_nodes_sg_name else [0, 65535]
        rule_deletion_policy = deletion_policy if sg == file_system_sg_name else None
        assert_sg_rule(
            generated_template,
            file_system_sg_name,
            rule_type="ingress",
            protocol=ingress_ip_protocol,
            port_range=ingress_port_range,
            target_sg=sg,
            deletion_policy=rule_deletion_policy,
        )
        assert_sg_rule(
            generated_template,
            file_system_sg_name,
            rule_type="egress",
            protocol="-1",
            port_range=[0, 65535],
            target_sg=sg,
            deletion_policy=rule_deletion_policy,
        )


@pytest.mark.parametrize(
    "config_file_name",
    [
        ("unmanaged_config.yaml"),
    ],
)
def test_unmanaged_shared_storage_fsx(mocker, test_datadir, config_file_name):
    # Check dna.json has DNS Name, FSx Id's and Mount Name for Unmanaed storage
    mock_aws_api(mocker)
    mock_bucket_object_utils(mocker)

    input_yaml = load_yaml_dict(test_datadir / config_file_name)

    cluster_config = ClusterSchema(cluster_name="clustername").load(input_yaml)

    generated_template, _ = CDKTemplateBuilder().build_cluster_template(
        cluster_config=cluster_config, bucket=dummy_cluster_bucket(), stack_name="clustername"
    )

    head_node_dna_json_file = (
        generated_template.get("Resources")
        .get("HeadNodeLaunchTemplate")
        .get("Metadata")
        .get("AWS::CloudFormation::Init")
        .get("deployConfigFiles")
        .get("files")
        .get("/opt/parallelcluster/tmp/dna.json")
        .get("content")
        .get("Fn::Join")[1][4]
    )
    for storage in cluster_config.shared_storage:
        if storage.existing_dns_name:
            assert_that(storage.existing_dns_name in head_node_dna_json_file).is_true()
        if isinstance(storage, ExistingFileCache):
            assert_that(storage.file_cache_id in head_node_dna_json_file).is_true()
            assert_that(storage.file_cache_mount_name in head_node_dna_json_file).is_true()
            assert_that(storage.file_cache_id in generated_template.get("Outputs").get("FSXIds").get("Value")).is_true()
        else:
            assert_that(storage.volume_id in head_node_dna_json_file).is_true()
            if isinstance(storage, ExistingFsxOpenZfs):
                assert_that(storage.volume_path in head_node_dna_json_file).is_true()
            else:
                assert_that(storage.junction_path in head_node_dna_json_file).is_true()


@pytest.mark.parametrize(
    "config_file_name",
    [("config.yaml"), ("file_cache_config.yaml")],
)
def test_non_happy_storage(mocker, test_datadir, config_file_name):
    dummy_api = _DummyAWSApi()
    if config_file_name == "file_cache_config.yaml":
        # Check for Non-Existence of File cache
        dummy_api._fsx.set_non_happy_describe_storage(
            AWSClientError(
                function_name="describe_file_caches", message="The cache with cache ID 'fc-12345678' does not exist."
            )
        )
    else:
        # Check for Non-Happy Storage Mounting
        dummy_api._fsx.set_non_happy_describe_storage(
            AWSClientError(function_name="describe_volumes", message="describing volumes is unauthorized")
        )
    mocker.patch("pcluster.aws.aws_api.AWSApi.instance", return_value=dummy_api)
    mocker.patch("pcluster.aws.ec2.Ec2Client.get_instance_type_info", side_effect=_DummyInstanceTypeInfo)

    input_yaml = load_yaml_dict(test_datadir / config_file_name)
    cluster_config = ClusterSchema(cluster_name="clustername").load(input_yaml)

    with pytest.raises(AWSClientError):
        CDKTemplateBuilder().build_cluster_template(
            cluster_config=cluster_config, bucket=dummy_cluster_bucket(), stack_name="clustername"
        )


@pytest.mark.parametrize(
    "config_file_name",
    [
        ("config.yaml"),
    ],
)
def test_efs_permissions(mocker, test_datadir, config_file_name):
    mock_aws_api(mocker)
    mock_bucket_object_utils(mocker)

    input_yaml = load_yaml_dict(test_datadir / config_file_name)

    cluster_config = ClusterSchema(cluster_name="clustername").load(input_yaml)

    generated_template, _ = CDKTemplateBuilder().build_cluster_template(
        cluster_config=cluster_config, bucket=dummy_cluster_bucket(), stack_name="clustername"
    )

    head_node_policy = get_head_node_policy(generated_template)
    statement = get_statement_by_sid(policy=head_node_policy, sid="Efs")

    assert_that(statement["Effect"]).is_equal_to("Allow")
    assert_that(statement["Action"]).contains_only(
        "elasticfilesystem:ClientMount", "elasticfilesystem:ClientRootAccess", "elasticfilesystem:ClientWrite"
    )


@pytest.mark.parametrize(
    "existing_az1_subnet, expected_az1_subnets",
    [
        # Without an existing mount target, any compute subnet of the AZ can be chosen
        pytest.param(None, ["subnet-1111111a", "subnet-2222222a"], id="new mount target"),
        pytest.param("subnet-2222222a", ["subnet-2222222a"], id="existing mount target in a compute subnet"),
        pytest.param("subnet-0000000a", ["subnet-0000000a"], id="existing mount target in the head node subnet"),
        pytest.param("subnet-9999999a", ["subnet-9999999a"], id="existing mount target subnet no longer used"),
    ],
)
def test_efs_mount_target_subnets(mocker, test_datadir, existing_az1_subnet, expected_az1_subnets):
    mock_aws_api(mocker)
    mock_bucket_object_utils(mocker)
    subnet_azs = {
        "subnet-0000000a": "us-east-1a",
        "subnet-1111111a": "us-east-1a",
        "subnet-2222222a": "us-east-1a",
        "subnet-2222222b": "us-east-1b",
    }
    mocker.patch(
        "pcluster.aws.ec2.Ec2Client.get_subnet_avail_zone", side_effect=lambda subnet_id: subnet_azs[subnet_id]
    )

    cluster_config = ClusterSchema(cluster_name="clustername").load(load_yaml_dict(test_datadir / "config.yaml"))

    def _get_mount_target_subnets(existing_efs_mount_target_subnets=None):
        # During update, the subnets of the deployed mount targets are set in the config by the Cluster model
        cluster_config.existing_efs_mount_target_subnets = existing_efs_mount_target_subnets or {}
        generated_template, _ = CDKTemplateBuilder().build_cluster_template(
            cluster_config=cluster_config, bucket=dummy_cluster_bucket(), stack_name="clustername"
        )
        mount_targets = get_resources(generated_template, type="AWS::EFS::MountTarget")
        return {key: mount_target["Properties"]["SubnetId"] for key, mount_target in mount_targets.items()}

    mount_target_subnets = _get_mount_target_subnets()
    az1_mount_target, az2_mount_target = (
        next(key for key in mount_target_subnets if key.endswith(f"MT{az.replace('-', '')}"))
        for az in ["us-east-1a", "us-east-1b"]
    )
    existing_mount_target_subnets = {az2_mount_target: "subnet-2222222b"}
    if existing_az1_subnet:
        existing_mount_target_subnets[az1_mount_target] = existing_az1_subnet

    # The mount target of each AZ must stay in the subnet where it already exists,
    # because EFS does not allow to create a second mount target in the same AZ during the stack update.
    mount_target_subnets = _get_mount_target_subnets(existing_mount_target_subnets)
    assert_that(mount_target_subnets).contains_only(az1_mount_target, az2_mount_target)
    assert_that(expected_az1_subnets).contains(mount_target_subnets[az1_mount_target])
    assert_that(mount_target_subnets[az2_mount_target]).is_equal_to("subnet-2222222b")


def _get_test_subnet_az(subnet_id):
    """Return the AZ encoded in the test subnet id, e.g. subnet-b0000001 is in us-east-1b."""
    return f"us-east-1{subnet_id[len('subnet-')]}"


@pytest.mark.parametrize(
    "head_node_subnet, queues_subnets, login_pools_subnets",
    [
        pytest.param("subnet-a0000001", [["subnet-a0000002"]], [["subnet-a0000003"]], id="single AZ"),
        pytest.param("subnet-a0000001", [["subnet-b0000001"]], [["subnet-c0000001"]], id="each node type in its AZ"),
        pytest.param("subnet-a0000001", [["subnet-a0000002"]], [["subnet-b0000001"]], id="AZ used only by login"),
        pytest.param("subnet-a0000001", [["subnet-b0000001"]], [], id="AZ used only by head node, no login nodes"),
        pytest.param(
            "subnet-a0000001",
            [["subnet-b0000001", "subnet-c0000001"], ["subnet-a0000002"]],
            [["subnet-a0000003"]],
            id="multi-AZ queue",
        ),
        pytest.param(
            "subnet-a0000001",
            [["subnet-b0000001"], ["subnet-b0000002"]],
            [["subnet-c0000001"], ["subnet-d0000001"], ["subnet-c0000002"]],
            id="multiple subnets per AZ and multiple login pools",
        ),
    ],
)
def test_efs_mount_targets_in_all_cluster_azs(mocker, head_node_subnet, queues_subnets, login_pools_subnets):
    mock_aws_api(mocker)
    mock_bucket_object_utils(mocker)
    mocker.patch("pcluster.aws.ec2.Ec2Client.get_subnet_avail_zone", side_effect=_get_test_subnet_az)

    cluster_config = _get_efs_test_cluster_config(head_node_subnet, queues_subnets, login_pools_subnets)
    file_systems_mount_targets = _get_efs_mount_targets(cluster_config)

    cluster_subnets = {head_node_subnet}.union(*queues_subnets, *login_pools_subnets)
    cluster_azs = {_get_test_subnet_az(subnet) for subnet in cluster_subnets}
    # One file system for the internal shared storage and one for the managed shared storage
    assert_that(file_systems_mount_targets).is_length(2)
    for mount_targets in file_systems_mount_targets.values():
        mount_target_azs = [_get_test_subnet_az(subnet) for subnet in mount_targets.values()]
        # Every AZ used by head node, compute nodes or login nodes has exactly one mount target,
        # placed in one of the cluster subnets of that AZ
        assert_that(mount_target_azs).is_length(len(cluster_azs))
        assert_that(set(mount_target_azs)).is_equal_to(cluster_azs)
        assert_that(cluster_subnets.issuperset(mount_targets.values())).is_true()


@pytest.mark.parametrize(
    "queues_subnets, login_pools_subnets_before, login_pools_subnets_after, expected_mount_target_subnets",
    [
        pytest.param(
            [["subnet-b0000001"]],
            [],
            [["subnet-c0000001"]],
            {"a": "subnet-a0000001", "b": "subnet-b0000001", "c": "subnet-c0000001"},
            id="login pool added in a new AZ",
        ),
        pytest.param(
            [["subnet-b0000001"]],
            [["subnet-c0000001"]],
            [["subnet-c0000002"]],
            {"a": "subnet-a0000001", "b": "subnet-b0000001", "c": "subnet-c0000001"},
            id="existing mount target in a login only AZ kept",
        ),
        pytest.param(
            [["subnet-b0000001"]],
            [["subnet-c0000001"]],
            [["subnet-b0000002"]],
            {"a": "subnet-a0000001", "b": "subnet-b0000001"},
            id="login pool moved to an AZ with a mount target",
        ),
        pytest.param(
            [["subnet-b0000001"], ["subnet-c0000002"]],
            [["subnet-c0000001"]],
            [["subnet-c0000001"]],
            {"a": "subnet-a0000001", "b": "subnet-b0000001", "c": "subnet-c0000001"},
            id="compute subnet added in a login AZ",
        ),
    ],
)
def test_efs_mount_targets_in_all_cluster_azs_on_update(
    mocker, queues_subnets, login_pools_subnets_before, login_pools_subnets_after, expected_mount_target_subnets
):
    mock_aws_api(mocker)
    mock_bucket_object_utils(mocker)
    mocker.patch("pcluster.aws.ec2.Ec2Client.get_subnet_avail_zone", side_effect=_get_test_subnet_az)
    head_node_subnet = "subnet-a0000001"

    # The mount targets of the deployed stack, generated from the configuration before the update
    deployed_mount_targets = _get_efs_mount_targets(
        _get_efs_test_cluster_config(head_node_subnet, [["subnet-b0000001"]], login_pools_subnets_before)
    )
    # During update, the subnets of the deployed mount targets are set in the config by the Cluster model
    cluster_config = _get_efs_test_cluster_config(head_node_subnet, queues_subnets, login_pools_subnets_after)
    cluster_config.existing_efs_mount_target_subnets = {
        logical_id: subnet
        for mount_targets in deployed_mount_targets.values()
        for logical_id, subnet in mount_targets.items()
    }
    file_systems_mount_targets = _get_efs_mount_targets(cluster_config)

    assert_that(file_systems_mount_targets).is_length(2)
    for file_system_name, mount_targets in file_systems_mount_targets.items():
        # Mount target logical ids end with the AZ (e.g. ...MTuseast1c): existing mount targets keep their subnet,
        # a mount target is created in the AZs that do not have one yet
        assert_that({logical_id[-1]: subnet for logical_id, subnet in mount_targets.items()}).is_equal_to(
            expected_mount_target_subnets
        )
        for logical_id, subnet in mount_targets.items():
            if logical_id in deployed_mount_targets[file_system_name]:
                assert_that(subnet).is_equal_to(deployed_mount_targets[file_system_name][logical_id])


def _get_efs_test_cluster_config(head_node_subnet, queues_subnets, login_pools_subnets):
    """Return a cluster config with internal EFS and managed EFS, using the given head, queues and login subnets."""
    config = {
        "Image": {"Os": "alinux2023"},
        "HeadNode": {
            "InstanceType": "t3.micro",
            "Networking": {"SubnetId": head_node_subnet},
            "SharedStorageType": "Efs",
        },
        "Scheduling": {
            "Scheduler": "slurm",
            "SlurmQueues": [
                {
                    "Name": f"queue{index}",
                    "Networking": {"SubnetIds": subnets},
                    "ComputeResources": [{"Name": "compute-resource", "InstanceType": "c5.2xlarge"}],
                }
                for index, subnets in enumerate(queues_subnets)
            ],
        },
        "SharedStorage": [{"MountDir": "/opt/shared/efs/managed", "Name": "shared-efs-managed", "StorageType": "Efs"}],
    }
    if login_pools_subnets:
        config["LoginNodes"] = {
            "Pools": [
                {"Name": f"login{index}", "InstanceType": "t3.small", "Count": 1, "Networking": {"SubnetIds": subnets}}
                for index, subnets in enumerate(login_pools_subnets)
            ]
        }
    return ClusterSchema(cluster_name="clustername").load(config)


def _get_efs_mount_targets(cluster_config):
    """Return {file system logical id: {mount target logical id: subnet id}} from the generated template."""
    generated_template, _ = CDKTemplateBuilder().build_cluster_template(
        cluster_config=cluster_config, bucket=dummy_cluster_bucket(), stack_name="clustername"
    )
    return {
        file_system_name: {
            logical_id: mount_target["Properties"]["SubnetId"]
            for logical_id, mount_target in get_resources(
                generated_template, type="AWS::EFS::MountTarget", properties={"FileSystemId": {"Ref": file_system_name}}
            ).items()
        }
        for file_system_name in get_resources(generated_template, type="AWS::EFS::FileSystem")
    }


@pytest.mark.parametrize(
    "queues_subnets_after, pin_deployed_subnets, expected_subnet_ids",
    [
        # Reproducer of the managed FSx replacement: all the queues in subnet A are removed and a queue in subnet B
        # is added. The update policies and validators accept the change, so the subnet must be kept by the template.
        pytest.param({"queue2": "subnet-a0000002"}, True, ["subnet-a0000001"], id="queues moved to another subnet"),
        pytest.param({"queue1": "subnet-a0000001"}, True, ["subnet-a0000001"], id="queues unchanged"),
        pytest.param({"queue2": "subnet-a0000002"}, False, ["subnet-a0000002"], id="new file system"),
    ],
)
def test_managed_fsx_subnets_on_update(mocker, queues_subnets_after, pin_deployed_subnets, expected_subnet_ids):
    mock_aws_api(mocker)
    mock_bucket_object_utils(mocker)
    mocker.patch("pcluster.aws.ec2.Ec2Client.get_subnet_avail_zone", side_effect=_get_test_subnet_az)

    # The file system of the deployed stack, generated from the configuration before the update
    deployed_fsx_subnets = _get_managed_fsx_subnets(_get_fsx_test_cluster_config({"queue1": "subnet-a0000001"}))
    # During update, the subnets of the deployed file systems are set in the config by the Cluster model
    cluster_config = _get_fsx_test_cluster_config(queues_subnets_after)
    if pin_deployed_subnets:
        cluster_config.existing_fsx_file_system_subnets = deployed_fsx_subnets
    fsx_subnets = _get_managed_fsx_subnets(cluster_config)

    # Changing the subnets of an FSx replaces the file system, deleting the existing one and its data
    assert_that(fsx_subnets).is_length(1)
    assert_that(fsx_subnets.keys()).is_equal_to(deployed_fsx_subnets.keys())
    assert_that(list(fsx_subnets.values())[0]).is_equal_to(expected_subnet_ids)


def _get_fsx_test_cluster_config(queues_subnets):
    """Return a cluster config with a managed FSx for Lustre, using the given {queue name: subnet id}."""
    config = {
        "Image": {"Os": "alinux2023"},
        "HeadNode": {"InstanceType": "t3.micro", "Networking": {"SubnetId": "subnet-a0000003"}},
        "Scheduling": {
            "Scheduler": "slurm",
            "SlurmQueues": [
                {
                    "Name": queue_name,
                    "Networking": {"SubnetIds": [subnet]},
                    "ComputeResources": [{"Name": "compute-resource", "InstanceType": "c5.2xlarge"}],
                }
                for queue_name, subnet in queues_subnets.items()
            ],
        },
        "SharedStorage": [
            {
                "MountDir": "/opt/shared/fsx/managed",
                "Name": "shared-fsx-managed",
                "StorageType": "FsxLustre",
                "FsxLustreSettings": {"StorageCapacity": 1200},
            }
        ],
    }
    return ClusterSchema(cluster_name="clustername").load(config)


def _get_managed_fsx_subnets(cluster_config):
    """Return {file system logical id: subnet ids} from the generated template."""
    generated_template, _ = CDKTemplateBuilder().build_cluster_template(
        cluster_config=cluster_config, bucket=dummy_cluster_bucket(), stack_name="clustername"
    )
    return {
        logical_id: file_system["Properties"]["SubnetIds"]
        for logical_id, file_system in get_resources(generated_template, type="AWS::FSx::FileSystem").items()
    }
