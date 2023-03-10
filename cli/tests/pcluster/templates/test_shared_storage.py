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
from pcluster.schemas.cluster_schema import ClusterSchema
from pcluster.templates.cdk_builder import CDKTemplateBuilder
from pcluster.utils import load_yaml_dict
from tests.pcluster.aws.dummy_aws_api import _DummyAWSApi, _DummyInstanceTypeInfo, mock_aws_api
from tests.pcluster.models.dummy_s3_bucket import dummy_cluster_bucket, mock_bucket_object_utils
from tests.pcluster.utils import get_head_node_policy, get_resources, get_statement_by_sid


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

    for sg in ["HeadNodeSecurityGroup", "ComputeSecurityGroup", mount_target_sg_name]:
        rule_deletion_policy = deletion_policy if sg == mount_target_sg_name else None
        assert_sg_rule(
            generated_template,
            mount_target_sg_name,
            rule_type="ingress",
            protocol="-1",
            port_range=[0, 65535],
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

    for sg in ["HeadNodeSecurityGroup", "ComputeSecurityGroup", file_system_sg_name]:
        rule_deletion_policy = deletion_policy if sg == file_system_sg_name else None
        assert_sg_rule(
            generated_template,
            file_system_sg_name,
            rule_type="ingress",
            protocol="-1",
            port_range=[0, 65535],
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


def assert_sg_rule(
    generated_template: dict,
    sg_name: str,
    rule_type: str,
    protocol: str,
    port_range: list,
    target_sg: str,
    deletion_policy: str,
):
    constants = {
        "ingress": {"resource_type": "AWS::EC2::SecurityGroupIngress", "sg_field": "SourceSecurityGroupId"},
        "egress": {"resource_type": "AWS::EC2::SecurityGroupEgress", "sg_field": "DestinationSecurityGroupId"},
    }
    sg_rules = get_resources(
        generated_template,
        type=constants[rule_type]["resource_type"],
        deletion_policy=deletion_policy,
        properties={
            "GroupId": {"Ref": sg_name},
            "IpProtocol": protocol,
            "FromPort": port_range[0],
            "ToPort": port_range[1],
            constants[rule_type]["sg_field"]: {"Ref": target_sg},
        },
    )

    assert_that(sg_rules).is_length(1)


def test_non_happy_ontap_and_openzfs_mounting(mocker, test_datadir):
    dummy_api = _DummyAWSApi()
    dummy_api._fsx.set_non_happy_describe_volumes(
        AWSClientError(function_name="describe_volumes", message="describing volumes is unauthorized")
    )
    mocker.patch("pcluster.aws.aws_api.AWSApi.instance", return_value=dummy_api)
    mocker.patch("pcluster.aws.ec2.Ec2Client.get_instance_type_info", side_effect=_DummyInstanceTypeInfo)

    input_yaml = load_yaml_dict(test_datadir / "config.yaml")
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
