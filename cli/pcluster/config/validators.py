# Copyright 2019 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
import re
import urllib.error
import urllib.request
from urllib.parse import urlparse

import boto3
from botocore.exceptions import ClientError

from pcluster.dcv.utils import get_supported_dcv_os, get_supported_dcv_partition
from pcluster.utils import (
    get_efs_mount_target_id,
    get_instance_vcpus,
    get_partition,
    get_region,
    get_supported_features,
    list_ec2_instance_types,
)


def _get_sts_endpoint():
    """Get regionalized STS endpoint."""
    region = get_region()
    return "https://sts.{0}.{1}".format(region, "amazonaws.com.cn" if region.startswith("cn-") else "amazonaws.com")


def _check_sg_rules_for_port(rule, port_to_check):
    """
    Verify if the security group rule accepts connections on the given port.

    :param rule: The rule to check
    :param port_to_check: The port to check
    :return: True if the rule accepts connection, False otherwise
    """
    from_port = rule.get("FromPort")
    to_port = rule.get("ToPort")
    ip_protocol = rule.get("IpProtocol")

    # if ip_protocol is -1, all ports are allowed
    if ip_protocol == "-1":
        return True
    # tcp == protocol 6,
    # if the ip_protocol is tcp, from_port and to_port must >= 0 and <= 65535
    if (ip_protocol in ["tcp", "6"]) and (from_port <= port_to_check <= to_port):
        return True

    return False


def efs_id_validator(param_key, param_value, pcluster_config):
    errors = []
    warnings = []
    try:
        # Get master availability zone
        master_avail_zone = pcluster_config.get_master_availability_zone()
        mount_target_id = get_efs_mount_target_id(efs_fs_id=param_value, avail_zone=master_avail_zone)
        # If there is an existing mt in the az, need to check the inbound and outbound rules of the security groups
        if mount_target_id:
            # Get list of security group IDs of the mount target
            sg_ids = (
                boto3.client("efs")
                .describe_mount_target_security_groups(MountTargetId=mount_target_id)
                .get("SecurityGroups")
            )
            if not _check_in_out_access(sg_ids, port=2049):
                warnings.append(
                    "There is an existing Mount Target {0} in the Availability Zone {1} for EFS {2}, "
                    "but it does not have a security group that allows inbound and outbound rules to support NFS. "
                    "Please modify the Mount Target's security group, to allow traffic on port 2049.".format(
                        mount_target_id, master_avail_zone, param_value
                    )
                )
    except ClientError as e:
        errors.append(e.response.get("Error").get("Message"))

    return errors, warnings


def _check_in_out_access(security_groups_ids, port):
    """
    Verify given list of security groups to check if they allow in and out access on the given port.

    :param security_groups_ids: list of security groups to verify
    :param port: port to verify
    :return true if
    :raise: ClientError if a given security group doesn't exist
    """
    in_out_access = False
    in_access = False
    out_access = False

    for sec_group in boto3.client("ec2").describe_security_groups(GroupIds=security_groups_ids).get("SecurityGroups"):

        # Check all inbound rules
        for rule in sec_group.get("IpPermissions"):
            if _check_sg_rules_for_port(rule, port):
                in_access = True
                break

        # Check all outbound rules
        for rule in sec_group.get("IpPermissionsEgress"):
            if _check_sg_rules_for_port(rule, port):
                out_access = True
                break

        if in_access and out_access:
            in_out_access = True
            break

    return in_out_access


def fsx_validator(section_key, section_label, pcluster_config):
    errors = []
    warnings = []

    fsx_section = pcluster_config.get_section(section_key, section_label)
    fsx_import_path = fsx_section.get_param_value("import_path")

    fsx_imported_file_chunk_size = fsx_section.get_param_value("imported_file_chunk_size")
    if fsx_imported_file_chunk_size and not fsx_import_path:
        errors.append("When specifying 'imported_file_chunk_size', the 'import_path' option must be specified")

    fsx_export_path = fsx_section.get_param_value("export_path")
    if fsx_export_path and not fsx_import_path:
        errors.append("When specifying 'export_path', the 'import_path' option must be specified")

    return errors, warnings


def fsx_id_validator(param_key, param_value, pcluster_config):
    errors = []
    warnings = []

    try:
        ec2 = boto3.client("ec2")

        # Check to see if there is any existing mt on the fs
        file_system = boto3.client("fsx").describe_file_systems(FileSystemIds=[param_value]).get("FileSystems")[0]

        subnet_id = pcluster_config.get_section("vpc").get_param_value("master_subnet_id")
        vpc_id = ec2.describe_subnets(SubnetIds=[subnet_id]).get("Subnets")[0].get("VpcId")

        # Check to see if fs is in the same VPC as the stack
        if file_system.get("VpcId") != vpc_id:
            errors.append(
                "Currently only support using FSx file system that is in the same VPC as the stack. "
                "The file system provided is in {0}".format(file_system.get("VpcId"))
            )
        # If there is an existing mt in the az, need to check the inbound and outbound rules of the security groups
        network_interface_ids = file_system.get("NetworkInterfaceIds")
        network_interface_responses = ec2.describe_network_interfaces(NetworkInterfaceIds=network_interface_ids).get(
            "NetworkInterfaces"
        )
        fs_access = False
        network_interfaces = [i for i in network_interface_responses if i.get("VpcId") == vpc_id]
        for network_interface in network_interfaces:
            # Get list of security group IDs
            sg_ids = [i.get("GroupId") for i in network_interface.get("Groups")]
            if _check_in_out_access(sg_ids, port=988):
                fs_access = True
                break
        if not fs_access:
            errors.append(
                "The current security group settings on file system %s does not satisfy "
                "mounting requirement. The file system must be associated to a security group that allows "
                "inbound and outbound TCP traffic through port 988." % param_value
            )
    except ClientError as e:
        errors.append(e.response.get("Error").get("Message"))

    return errors, warnings


def fsx_storage_capacity_validator(param_key, param_value, pcluster_config):
    errors = []
    warnings = []

    if int(param_value) > 0 and not (
        int(param_value) == 1200 or int(param_value) == 2400 or int(param_value) % 3600 == 0
    ):
        errors.append("Capacity for FSx lustre filesystem, 1,200 GB, 2,400 GB or increments of 3,600 GB")

    return errors, warnings


def disable_hyperthreading_validator(param_key, param_value, pcluster_config):
    errors = []
    warnings = []

    if param_value:
        # Check to see if cfn_scheduler_slots is set
        cluster_section = pcluster_config.get_section("cluster")
        extra_json = cluster_section.get_param_value("extra_json")
        if extra_json and extra_json.get("cluster") and extra_json.get("cluster").get("cfn_scheduler_slots"):
            errors.append("cfn_scheduler_slots cannot be set in addition to disable_hyperthreading = true")

    return errors, warnings


def dcv_enabled_validator(param_key, param_value, pcluster_config):
    errors = []
    warnings = []

    cluster_section = pcluster_config.get_section("cluster")
    if param_value == "master":

        allowed_oses = get_supported_dcv_os()
        if cluster_section.get_param_value("base_os") not in allowed_oses:
            errors.append(
                "NICE DCV can be used with one of the following operating systems: {0}. "
                "Please double check the 'base_os' configuration parameter".format(allowed_oses)
            )

        if get_partition() not in get_supported_dcv_partition():
            errors.append("NICE DCV is not supported in the selected region '{0}'".format(get_region()))

    return errors, warnings


def fsx_imported_file_chunk_size_validator(param_key, param_value, pcluster_config):
    errors = []
    warnings = []

    if not 1 <= int(param_value) <= 512000:
        errors.append("'{0}' has a minimum size of 1 MiB, and max size of 512,000 MiB".format(param_key))

    return errors, warnings


def efa_validator(param_key, param_value, pcluster_config):
    errors = []
    warnings = []

    cluster_section = pcluster_config.get_section("cluster")
    supported_features = get_supported_features(pcluster_config.region, "efa")
    allowed_instances = supported_features.get("instances")
    if cluster_section.get_param_value("compute_instance_type") not in allowed_instances:
        errors.append(
            "When using 'enable_efa = {0}' it is required to set the 'compute_instance_type' parameter "
            "to one of the following values : {1}".format(param_value, allowed_instances)
        )

    allowed_oses = ["alinux", "centos7", "ubuntu1604", "ubuntu1804"]
    if cluster_section.get_param_value("base_os") not in allowed_oses:
        errors.append(
            "When using 'enable_efa = {0}' it is required to set the 'base_os' parameter "
            "to one of the following values : {1}".format(param_value, allowed_oses)
        )

    allowed_schedulers = ["sge", "slurm", "torque"]
    if cluster_section.get_param_value("scheduler") not in allowed_schedulers:
        errors.append(
            "When using 'enable_efa = {0}' it is required to set the 'scheduler' parameter "
            "to one of the following values : {1}".format(param_value, allowed_schedulers)
        )

    if cluster_section.get_param_value("placement_group") is None:
        errors.append(
            "When using 'enable_efa = {0}' it is required to set the 'placement_group' parameter "
            "to DYNAMIC or to an existing EC2 cluster placement group name".format(param_value)
        )

    _validate_efa_sg(pcluster_config, errors)

    return errors, warnings


def _validate_efa_sg(pcluster_config, errors):
    vpc_security_group_id = pcluster_config.get_section("vpc").get_param_value("vpc_security_group_id")
    if vpc_security_group_id:
        try:
            sg = boto3.client("ec2").describe_security_groups(GroupIds=[vpc_security_group_id]).get("SecurityGroups")[0]
            allowed_in = False
            allowed_out = False

            # check inbound rules
            for rule in sg.get("IpPermissions"):
                # UserIdGroupPairs is always of length 1, so grabbing 0th object is ok
                if (
                    rule.get("IpProtocol") == "-1"
                    and rule.get("UserIdGroupPairs")
                    and rule.get("UserIdGroupPairs")[0].get("GroupId") == vpc_security_group_id
                ):
                    allowed_in = True
                    break

            # check outbound rules
            for rule in sg.get("IpPermissionsEgress"):
                if (
                    rule.get("IpProtocol") == "-1"
                    and rule.get("UserIdGroupPairs")
                    and rule.get("UserIdGroupPairs")[0].get("GroupId") == vpc_security_group_id
                ):
                    allowed_out = True
                    break

            if not (allowed_in and allowed_out):
                errors.append(
                    "The VPC Security Group '{0}' set in the vpc_security_group_id parameter "
                    "must allow all traffic in and out from itself. "
                    "See https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/efa-start.html#efa-start-security".format(
                        vpc_security_group_id
                    )
                )
        except ClientError as e:
            errors.append(e.response.get("Error").get("Message"))


def ec2_key_pair_validator(param_key, param_value, pcluster_config):
    errors = []
    warnings = []
    try:
        boto3.client("ec2").describe_key_pairs(KeyNames=[param_value])
    except ClientError as e:
        errors.append(e.response.get("Error").get("Message"))

    return errors, warnings


def ec2_iam_role_validator(param_key, param_value, pcluster_config):
    errors = []
    warnings = []
    try:
        iam = boto3.client("iam")
        arn = iam.get_role(RoleName=param_value).get("Role").get("Arn")
        account_id = boto3.client("sts", endpoint_url=_get_sts_endpoint()).get_caller_identity().get("Account")

        iam_policy = _get_pcluster_user_policy(get_partition(), get_region(), account_id)

        for actions, resource_arn in iam_policy:
            response = iam.simulate_principal_policy(
                PolicySourceArn=arn, ActionNames=actions, ResourceArns=[resource_arn]
            )
            for decision in response.get("EvaluationResults"):
                if decision.get("EvalDecision") != "allowed":
                    errors.append(
                        "IAM role error on user provided role {0}: action {1} is {2}.\n"
                        "See https://docs.aws.amazon.com/parallelcluster/latest/ug/iam.html".format(
                            param_value, decision.get("EvalActionName"), decision.get("EvalDecision")
                        )
                    )
    except ClientError as e:
        errors.append(e.response.get("Error").get("Message"))

    return errors, warnings


def ec2_iam_policies_validator(param_key, param_value, pcluster_config):
    errors = []
    warnings = []
    try:
        if param_value:
            iam = boto3.client("iam")
            for iam_policy in param_value:
                iam.get_policy(PolicyArn=iam_policy.strip())
    except ClientError as e:
        errors.append(e.response.get("Error").get("Message"))

    return errors, warnings


def _get_pcluster_user_policy(partition, region, account_id):
    return [
        (
            [
                "ec2:DescribeVolumes",
                "ec2:AttachVolume",
                "ec2:DescribeInstanceAttribute",
                "ec2:DescribeInstanceStatus",
                "ec2:DescribeInstances",
            ],
            "*",
        ),
        (["dynamodb:ListTables"], "*"),
        (
            [
                "sqs:SendMessage",
                "sqs:ReceiveMessage",
                "sqs:ChangeMessageVisibility",
                "sqs:DeleteMessage",
                "sqs:GetQueueUrl",
            ],
            "arn:%s:sqs:%s:%s:parallelcluster-*" % (partition, region, account_id),
        ),
        (
            [
                "autoscaling:DescribeAutoScalingGroups",
                "autoscaling:TerminateInstanceInAutoScalingGroup",
                "autoscaling:SetDesiredCapacity",
                "autoscaling:DescribeTags",
                "autoScaling:UpdateAutoScalingGroup",
                "autoScaling:SetInstanceHealth",
            ],
            "*",
        ),
        (
            ["dynamodb:PutItem", "dynamodb:Query", "dynamodb:GetItem", "dynamodb:DeleteItem", "dynamodb:DescribeTable"],
            "arn:%s:dynamodb:%s:%s:table/parallelcluster-*" % (partition, region, account_id),
        ),
        (
            ["cloudformation:DescribeStacks", "cloudformation:DescribeStackResource"],
            "arn:%s:cloudformation:%s:%s:stack/parallelcluster-*/*" % (partition, region, account_id),
        ),
        (["s3:GetObject"], "arn:%s:s3:::%s-aws-parallelcluster/*" % (partition, region)),
        (["sqs:ListQueues"], "*"),
    ]


def ec2_instance_type_validator(param_key, param_value, pcluster_config):
    errors = []
    warnings = []

    try:
        if param_value not in list_ec2_instance_types():
            errors.append(
                "The instance type '{0}' used for the '{1}' parameter is not supported by EC2.".format(
                    param_value, param_key
                )
            )

    except ClientError as e:
        errors.append(e.response.get("Error").get("Message"))

    return errors, warnings


def ec2_vpc_id_validator(param_key, param_value, pcluster_config):
    errors = []
    warnings = []
    try:
        ec2 = boto3.client("ec2")
        ec2.describe_vpcs(VpcIds=[param_value])

        # Check for DNS support in the VPC
        if (
            not ec2.describe_vpc_attribute(VpcId=param_value, Attribute="enableDnsSupport")
            .get("EnableDnsSupport")
            .get("Value")
        ):
            errors.append("DNS Support is not enabled in the VPC %s" % param_value)
        if (
            not ec2.describe_vpc_attribute(VpcId=param_value, Attribute="enableDnsHostnames")
            .get("EnableDnsHostnames")
            .get("Value")
        ):
            errors.append("DNS Hostnames not enabled in the VPC %s" % param_value)

    except ClientError as e:
        errors.append(e.response.get("Error").get("Message"))

    return errors, warnings


def ec2_subnet_id_validator(param_key, param_value, pcluster_config):
    errors = []
    warnings = []
    try:
        boto3.client("ec2").describe_subnets(SubnetIds=[param_value])
    except ClientError as e:
        errors.append(e.response.get("Error").get("Message"))

    return errors, warnings


def ec2_security_group_validator(param_key, param_value, pcluster_config):
    errors = []
    warnings = []
    try:
        boto3.client("ec2").describe_security_groups(GroupIds=[param_value])
    except ClientError as e:
        errors.append(e.response.get("Error").get("Message"))

    return errors, warnings


def ec2_ami_validator(param_key, param_value, pcluster_config):
    errors = []
    warnings = []
    try:
        boto3.client("ec2").describe_images(ImageIds=[param_value])
    except ClientError as e:
        errors.append(e.response.get("Error").get("Message"))

    return errors, warnings


def ec2_placement_group_validator(param_key, param_value, pcluster_config):
    errors = []
    warnings = []

    if param_value == "DYNAMIC":
        pass
    else:
        try:
            boto3.client("ec2").describe_placement_groups(GroupNames=[param_value])
        except ClientError as e:
            errors.append(e.response.get("Error").get("Message"))

    return errors, warnings


def url_validator(param_key, param_value, pcluster_config):
    errors = []
    warnings = []

    if urlparse(param_value).scheme == "s3":
        try:
            match = re.match(r"s3://(.*?)/(.*)", param_value)
            if not match or len(match.groups()) < 2:
                errors.append("S3 url is invalid.")
            bucket, key = match.group(1), match.group(2)
            boto3.client("s3").head_object(Bucket=bucket, Key=key)
        except ClientError:
            warnings.append("The S3 object does not exist or you do not have access to it.")
    else:
        try:
            urllib.request.urlopen(param_value)
        except urllib.error.HTTPError as e:
            warnings.append("{0} {1} {2}".format(param_value, e.code, e.reason))
        except urllib.error.URLError as e:
            warnings.append("{0} {1}".format(param_value, e.reason))
        except ValueError:
            errors.append(
                "The value '{0}' used for the parameter '{1}' is not a valid URL".format(param_value, param_key)
            )

    return errors, warnings


def ec2_ebs_snapshot_validator(param_key, param_value, pcluster_config):
    errors = []
    warnings = []
    try:
        test = boto3.client("ec2").describe_snapshots(SnapshotIds=[param_value]).get("Snapshots")[0]
        if test.get("State") != "completed":
            warnings.append("Snapshot {0} is in state '{1}' not 'completed'".format(param_value, test.get("State")))
    except ClientError as e:
        errors.append(e.response.get("Error").get("Message"))

    return errors, warnings


def ec2_volume_validator(param_key, param_value, pcluster_config):
    errors = []
    warnings = []
    try:
        test = boto3.client("ec2").describe_volumes(VolumeIds=[param_value]).get("Volumes")[0]
        if test.get("State") != "available":
            warnings.append("Volume {0} is in state '{1}' not 'available'".format(param_value, test.get("State")))
    except ClientError as e:
        if e.response.get("Error").get("Message").endswith("parameter volumes is invalid. Expected: 'vol-...'."):
            errors.append("Volume {0} does not exist".format(param_value))
        else:
            errors.append(e.response.get("Error").get("Message"))

    return errors, warnings


def efs_validator(section_key, section_label, pcluster_config):
    errors = []
    warnings = []

    section = pcluster_config.get_section(section_key, section_label)
    throughput_mode = section.get_param_value("throughput_mode")
    provisioned_throughput = section.get_param_value("provisioned_throughput")

    if throughput_mode != "provisioned" and provisioned_throughput:
        errors.append("When specifying 'provisioned_throughput', the 'throughput_mode' must be set to 'provisioned'")

    if throughput_mode == "provisioned" and not provisioned_throughput:
        errors.append(
            "When specifying 'throughput_mode' to 'provisioned', the 'provisioned_throughput' option must be specified"
        )

    return errors, warnings


def raid_volume_iops_validator(param_key, param_value, pcluster_config):
    errors = []
    warnings = []

    raid_iops = float(param_value)
    raid_vol_size = float(pcluster_config.get_section("raid").get_param_value("volume_size"))
    if raid_iops > raid_vol_size * 50:
        errors.append("IOPS to volume size ratio of {0} is too high; maximum is 50.".format(raid_iops / raid_vol_size))

    return errors, warnings


def scheduler_validator(param_key, param_value, pcluster_config):
    errors = []
    warnings = []

    if param_value == "awsbatch":
        if pcluster_config.region in ["ap-northeast-3", "us-gov-east-1", "us-gov-west-1"]:
            errors.append("'awsbatch' scheduler is not supported in the '{0}' region".format(pcluster_config.region))

    return errors, warnings


def cluster_validator(section_key, section_label, pcluster_config):
    errors = []
    warnings = []

    section = pcluster_config.get_section(section_key, section_label)
    if section.get_param_value("scheduler") == "awsbatch":
        min_size = section.get_param_value("min_vcpus")
        desired_size = section.get_param_value("desired_vcpus")
        max_size = section.get_param_value("max_vcpus")

        if desired_size < min_size:
            errors.append("desired_vcpus must be greater than or equal to min_vcpus")

        if desired_size > max_size:
            errors.append("desired_vcpus must be fewer than or equal to max_vcpus")

        if max_size < min_size:
            errors.append("max_vcpus must be greater than or equal to min_vcpus")
    else:
        min_size = (
            section.get_param_value("initial_queue_size") if section.get_param_value("maintain_initial_size") else 0
        )
        desired_size = section.get_param_value("initial_queue_size")
        max_size = section.get_param_value("max_queue_size")

        if desired_size > max_size:
            errors.append("initial_queue_size must be fewer than or equal to max_queue_size")

        if max_size < min_size:
            errors.append("max_queue_size must be greater than or equal to initial_queue_size")

    return errors, warnings


def compute_instance_type_validator(param_key, param_value, pcluster_config):
    errors = []
    warnings = []

    cluster_config = pcluster_config.get_section("cluster")
    if cluster_config.get_param_value("scheduler") == "awsbatch":

        try:
            supported_instances = get_supported_features(pcluster_config.region, "batch").get("instances")
            if supported_instances:
                for instance in param_value.split(","):
                    if not instance.strip() in supported_instances:
                        errors.append(
                            "compute_instance_type '{0}' is not supported by awsbatch in region '{1}'".format(
                                instance, pcluster_config.region
                            )
                        )
            else:
                warnings.append(
                    "Unable to get instance types supported by awsbatch. Skipping compute_instance_type validation"
                )

            if "," not in param_value and "." in param_value:
                # if the type is not a list, and contains dot (nor optimal, nor a family)
                # validate instance type against max_vcpus limit
                vcpus = get_instance_vcpus(pcluster_config.region, param_value)
                if vcpus <= 0:
                    warnings.append(
                        "Unable to get the number of vcpus for the compute_instance_type '{0}'. "
                        "Skipping instance type against max_vcpus validation".format(param_value)
                    )
                else:
                    if cluster_config.get_param_value("max_vcpus") < vcpus:
                        errors.append(
                            "max_vcpus must be greater than or equal to {0}, that is the number of vcpus "
                            "available for the {1} that you selected as compute_instance_type".format(
                                vcpus, param_value
                            )
                        )
        except ClientError as e:
            errors.append(e.response.get("Error").get("Message"))

    else:
        errors, warnings = ec2_instance_type_validator(param_key, param_value, pcluster_config)

    return errors, warnings
