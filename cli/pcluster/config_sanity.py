# Copyright 2013-2014 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
# fmt: off
from __future__ import absolute_import, print_function  # isort:skip
from future import standard_library  # isort:skip
standard_library.install_aliases()
# fmt: on

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from urllib.parse import urlparse

import boto3
from botocore.exceptions import ClientError


class ResourceValidator(object):
    """Utility class to check resource sanity."""

    def __init__(self, region, aws_access_key_id, aws_secret_access_key):
        """
        Initialize a ResourceValidator object.

        :param region: AWS Region
        :param aws_access_key_id: AWS access key
        :param aws_secret_access_key: AWS secret access key
        """
        self.region = region
        self.aws_access_key_id = aws_access_key_id
        self.aws_secret_access_key = aws_secret_access_key

    def __get_partition(self):
        if self.region.startswith("us-gov"):
            return "aws-us-gov"
        return "aws"

    @staticmethod
    def __check_sg_rules_for_port(rule, port_to_check):
        """
        Verify if the security group rule accepts connections to the given port.

        :param rule: The rule to check
        :param port_to_check: The port to check
        :return: True if the rule accepts connection, False otherwise
        """
        port = rule.get("FromPort")
        ip_rules = rule.get("IpRanges")
        group = rule.get("UserIdGroupPairs")

        is_valid = False
        for ip_rule in ip_rules:
            ip = ip_rule.get("CidrIp")
            # An existing rule is valid for EFS if, it allows all traffic(0.0.0.0/0)
            # from all ports or the given port, and does not have a security group restriction
            if (not port or port == port_to_check) and ip == "0.0.0.0/0" and not group:
                is_valid = True
                break

        return is_valid

    def __check_efs_fs_id(self, ec2, efs, resource_value):  # noqa: C901 FIXME!!!
        try:
            # Check to see if there is any existing mt on the fs
            mt = efs.describe_mount_targets(FileSystemId=resource_value[0])
            # Get the availability zone of the stack
            availability_zone = (
                ec2.describe_subnets(SubnetIds=[resource_value[1]]).get("Subnets")[0].get("AvailabilityZone")
            )
            mt_id = None
            for item in mt.get("MountTargets"):
                # Check to see if there is an existing mt in the az of the stack
                mt_subnet = item.get("SubnetId")
                if availability_zone == ec2.describe_subnets(SubnetIds=[mt_subnet]).get("Subnets")[0].get(
                    "AvailabilityZone"
                ):
                    mt_id = item.get("MountTargetId")
            # If there is an existing mt in the az, need to check the inbound and outbound rules of the security groups
            if mt_id:
                nfs_access = False
                in_access = False
                out_access = False
                # Get list of security group IDs of the mount target
                sg_ids = efs.describe_mount_target_security_groups(MountTargetId=mt_id).get("SecurityGroups")
                for sg in ec2.describe_security_groups(GroupIds=sg_ids).get("SecurityGroups"):
                    # Check all inbound rules
                    in_rules = sg.get("IpPermissions")
                    for rule in in_rules:
                        if self.__check_sg_rules_for_port(rule, 2049):
                            in_access = True
                            break
                    out_rules = sg.get("IpPermissionsEgress")
                    for rule in out_rules:
                        if self.__check_sg_rules_for_port(rule, 2049):
                            out_access = True
                            break
                    if in_access and out_access:
                        nfs_access = True
                        break
                if not nfs_access:
                    self.__fail(
                        "EFSFSId",
                        "There is an existing Mount Target %s in the Availability Zone %s for EFS %s, "
                        "and it does not have a security group with inbound and outbound rules that support NFS. "
                        "Please modify the Mount Target's security group, or delete the Mount Target."
                        % (mt_id, availability_zone, resource_value[0]),
                    )
        except ClientError as e:
            self.__fail("EFSFSId", e.response.get("Error").get("Message"))

    def __check_nfs_access(self, ec2, network_interfaces):
        nfs_access = False
        for network_interface in network_interfaces:
            in_access = False
            out_access = False
            # Get list of security group IDs
            sg_ids = [i.get("GroupId") for i in network_interface.get("Groups")]
            # Check each sg to see if the rules are valid
            for sg in ec2.describe_security_groups(GroupIds=sg_ids).get("SecurityGroups"):
                # Check all inbound rules
                in_rules = sg.get("IpPermissions")
                for rule in in_rules:
                    if self.__check_sg_rules_for_port(rule, 988):
                        in_access = True
                        break
                out_rules = sg.get("IpPermissionsEgress")
                for rule in out_rules:
                    if self.__check_sg_rules_for_port(rule, 988):
                        out_access = True
                        break
                if in_access and out_access:
                    nfs_access = True
                    break
            if nfs_access:
                return True

        return nfs_access

    def __check_fsx_fs_id(self, ec2, fsx, resource_value):
        try:
            # Check to see if there is any existing mt on the fs
            fs = fsx.describe_file_systems(FileSystemIds=[resource_value[0]]).get("FileSystems")[0]
            stack_vpc = ec2.describe_subnets(SubnetIds=[resource_value[1]]).get("Subnets")[0].get("VpcId")
            # Check to see if fs is in the same VPC as the stack
            if fs.get("VpcId") != stack_vpc:
                self.__fail(
                    "VpcId",
                    "Currently only support using FSx file system that is in the same VPC as the stack. "
                    "The file system provided is in %s" % fs.get("VpcId"),
                )
            # If there is an existing mt in the az, need to check the inbound and outbound rules of the security groups
            network_interface_ids = fs.get("NetworkInterfaceIds")
            network_interface_responses = ec2.describe_network_interfaces(
                NetworkInterfaceIds=network_interface_ids
            ).get("NetworkInterfaces")
            network_interfaces = [i for i in network_interface_responses if i.get("VpcId") == stack_vpc]
            nfs_access = self.__check_nfs_access(ec2, network_interfaces)
            if not nfs_access:
                self.__fail(
                    "FSXFSId",
                    "The current security group settings on file system %s does not satisfy "
                    "mounting requirement. The file system must be associated to a security group that allows "
                    "inbound and outbound TCP traffic from 0.0.0.0/0 through port 988." % resource_value[0],
                )
            return True
        except ClientError as e:
            self.__fail("FSXFSId", e.response.get("Error").get("Message"))

    def __validate_fsx_parameters(self, resource_type, resource_value):
        # FSX FS Id check
        if resource_type == "fsx_fs_id":
            try:
                ec2 = boto3.client(
                    "ec2",
                    region_name=self.region,
                    aws_access_key_id=self.aws_access_key_id,
                    aws_secret_access_key=self.aws_secret_access_key,
                )
                fsx = boto3.client(
                    "fsx",
                    region_name=self.region,
                    aws_access_key_id=self.aws_access_key_id,
                    aws_secret_access_key=self.aws_secret_access_key,
                )
                self.__check_fsx_fs_id(ec2, fsx, resource_value)
            except ClientError as e:
                self.__fail(resource_type, e.response.get("Error").get("Message"))
        # FSX capacity size check
        elif resource_type == "FSx_storage_capacity":
            if int(resource_value) % 3600 != 0 or int(resource_value) < 0:
                self.__fail(
                    resource_type, "Capacity for FSx lustre filesystem, minimum of 3,600 GB, increments of 3,600 GB"
                )
        # Check to see if import_path is specified with imported_file_chunk_size and export_path
        elif resource_type in ["FSx_imported_file_chunk_size", "FSx_export_path"]:
            if resource_value[1] is None:
                self.__fail(resource_type, "import_path must be specified.")
        # FSX file chunk size check
        elif resource_type == "FSx_imported_file_chunk_size":
            # 1,024 MiB (1 GiB) and can go as high as 512,000 MiB
            if not (1 <= int(resource_value[0]) <= 512000):
                self.__fail(resource_type, "has a minimum size of 1 MiB, and max size of 512,000 MiB")

    def validate(self, resource_type, resource_value):  # noqa: C901 FIXME
        """
        Validate the given resource. Print an error and exit in case of error.

        :param resource_type: Resource type
        :param resource_value: Resource value
        """
        # Loop over all supported resource checks
        if resource_type == "EC2KeyPair":
            try:
                ec2 = boto3.client(
                    "ec2",
                    region_name=self.region,
                    aws_access_key_id=self.aws_access_key_id,
                    aws_secret_access_key=self.aws_secret_access_key,
                )
                ec2.describe_key_pairs(KeyNames=[resource_value])
            except ClientError as e:
                self.__fail(resource_type, e.response.get("Error").get("Message"))
        if resource_type == "EC2IAMRoleName":
            try:
                iam = boto3.client(
                    "iam",
                    region_name=self.region,
                    aws_access_key_id=self.aws_access_key_id,
                    aws_secret_access_key=self.aws_secret_access_key,
                )

                arn = iam.get_role(RoleName=resource_value).get("Role").get("Arn")
                account_id = (
                    boto3.client(
                        "sts",
                        region_name=self.region,
                        aws_access_key_id=self.aws_access_key_id,
                        aws_secret_access_key=self.aws_secret_access_key,
                    )
                    .get_caller_identity()
                    .get("Account")
                )

                partition = self.__get_partition()

                iam_policy = [
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
                        "arn:%s:sqs:%s:%s:parallelcluster-*" % (partition, self.region, account_id),
                    ),
                    (
                        [
                            "autoscaling:DescribeAutoScalingGroups",
                            "autoscaling:TerminateInstanceInAutoScalingGroup",
                            "autoscaling:SetDesiredCapacity",
                            "autoscaling:DescribeTags",
                            "autoScaling:UpdateAutoScalingGroup",
                        ],
                        "*",
                    ),
                    (
                        [
                            "dynamodb:PutItem",
                            "dynamodb:Query",
                            "dynamodb:GetItem",
                            "dynamodb:DeleteItem",
                            "dynamodb:DescribeTable",
                        ],
                        "arn:%s:dynamodb:%s:%s:table/parallelcluster-*" % (partition, self.region, account_id),
                    ),
                    (
                        ["cloudformation:DescribeStacks"],
                        "arn:%s:cloudformation:%s:%s:stack/parallelcluster-*" % (partition, self.region, account_id),
                    ),
                    (["s3:GetObject"], "arn:%s:s3:::%s-aws-parallelcluster/*" % (partition, self.region)),
                    (["sqs:ListQueues"], "*"),
                ]

                for actions, resource_arn in iam_policy:
                    response = iam.simulate_principal_policy(
                        PolicySourceArn=arn, ActionNames=actions, ResourceArns=[resource_arn]
                    )
                    for decision in response.get("EvaluationResults"):
                        if decision.get("EvalDecision") != "allowed":
                            print(
                                "IAM role error on user provided role %s: action %s is %s"
                                % (resource_value, decision.get("EvalActionName"), decision.get("EvalDecision"))
                            )
                            print("See https://aws-parallelcluster.readthedocs.io/en/latest/iam.html")
                            sys.exit(1)
            except ClientError as e:
                self.__fail(resource_type, e.response.get("Error").get("Message"))
        # VPC Id
        elif resource_type == "VPC":
            try:
                ec2 = boto3.client(
                    "ec2",
                    region_name=self.region,
                    aws_access_key_id=self.aws_access_key_id,
                    aws_secret_access_key=self.aws_secret_access_key,
                )
                ec2.describe_vpcs(VpcIds=[resource_value])
            except ClientError as e:
                self.__fail(resource_type, e.response.get("Error").get("Message"))
            # Check for DNS support in the VPC
            if (
                not ec2.describe_vpc_attribute(VpcId=resource_value, Attribute="enableDnsSupport")
                .get("EnableDnsSupport")
                .get("Value")
            ):
                self.__fail(resource_type, "DNS Support is not enabled in %s" % resource_value)
            if (
                not ec2.describe_vpc_attribute(VpcId=resource_value, Attribute="enableDnsHostnames")
                .get("EnableDnsHostnames")
                .get("Value")
            ):
                self.__fail(resource_type, "DNS Hostnames not enabled in %s" % resource_value)
        # VPC Subnet Id
        elif resource_type == "VPCSubnet":
            try:
                ec2 = boto3.client(
                    "ec2",
                    region_name=self.region,
                    aws_access_key_id=self.aws_access_key_id,
                    aws_secret_access_key=self.aws_secret_access_key,
                )
                ec2.describe_subnets(SubnetIds=[resource_value])
            except ClientError as e:
                self.__fail(resource_type, e.response.get("Error").get("Message"))
        # VPC Security Group
        elif resource_type == "VPCSecurityGroup":
            try:
                ec2 = boto3.client(
                    "ec2",
                    region_name=self.region,
                    aws_access_key_id=self.aws_access_key_id,
                    aws_secret_access_key=self.aws_secret_access_key,
                )
                ec2.describe_security_groups(GroupIds=[resource_value])
            except ClientError as e:
                self.__fail(resource_type, e.response.get("Error").get("Message"))
        # EC2 AMI Id
        elif resource_type == "EC2Ami":
            try:
                ec2 = boto3.client(
                    "ec2",
                    region_name=self.region,
                    aws_access_key_id=self.aws_access_key_id,
                    aws_secret_access_key=self.aws_secret_access_key,
                )
                ec2.describe_images(ImageIds=[resource_value])
            except ClientError as e:
                self.__fail(resource_type, e.response.get("Error").get("Message"))
        # EC2 Placement Group
        elif resource_type == "EC2PlacementGroup":
            if resource_value == "DYNAMIC":
                pass
            else:
                try:
                    ec2 = boto3.client(
                        "ec2",
                        region_name=self.region,
                        aws_access_key_id=self.aws_access_key_id,
                        aws_secret_access_key=self.aws_secret_access_key,
                    )
                    ec2.describe_placement_groups(GroupNames=[resource_value])
                except ClientError as e:
                    self.__fail(resource_type, e.response.get("Error").get("Message"))
        # URL
        elif resource_type == "URL":
            scheme = urlparse(resource_value).scheme
            if scheme == "s3":
                pass
            else:
                try:
                    urllib.request.urlopen(resource_value)
                except urllib.error.HTTPError as e:
                    self.__fail(resource_type, "%s %s %s" % (resource_value, e.code, e.reason))
                except urllib.error.URLError as e:
                    self.__fail(resource_type, "%s %s" % (resource_value, e.reason))
        # EC2 EBS Snapshot Id
        elif resource_type == "EC2Snapshot":
            try:
                ec2 = boto3.client(
                    "ec2",
                    region_name=self.region,
                    aws_access_key_id=self.aws_access_key_id,
                    aws_secret_access_key=self.aws_secret_access_key,
                )
                test = ec2.describe_snapshots(SnapshotIds=[resource_value]).get("Snapshots")[0]
                if test.get("State") != "completed":
                    self.__fail(
                        resource_type,
                        "Snapshot %s is in state '%s' not 'completed'" % (resource_value, test.get("State")),
                    )
            except ClientError as e:
                self.__fail(resource_type, e.response.get("Error").get("Message"))
        # EC2 EBS Volume Id
        elif resource_type == "EC2Volume":
            try:
                ec2 = boto3.client(
                    "ec2",
                    region_name=self.region,
                    aws_access_key_id=self.aws_access_key_id,
                    aws_secret_access_key=self.aws_secret_access_key,
                )
                test = ec2.describe_volumes(VolumeIds=[resource_value]).get("Volumes")[0]
                if test.get("State") != "available":
                    self.__fail(
                        resource_type,
                        "Volume %s is in state '%s' not 'available'" % (resource_value, test.get("State")),
                    )
            except ClientError as e:
                if (
                    e.response.get("Error")
                    .get("Message")
                    .endswith("parameter volumes is invalid. Expected: 'vol-...'.")
                ):
                    self.__fail(resource_type, "Volume %s does not exist." % resource_value)

                self.__fail(resource_type, e.response.get("Error").get("Message"))
        # EFS file system Id
        elif resource_type == "EFSFSId":
            try:
                ec2 = boto3.client(
                    "ec2",
                    region_name=self.region,
                    aws_access_key_id=self.aws_access_key_id,
                    aws_secret_access_key=self.aws_secret_access_key,
                )
                efs = boto3.client(
                    "efs",
                    region_name=self.region,
                    aws_access_key_id=self.aws_access_key_id,
                    aws_secret_access_key=self.aws_secret_access_key,
                )
                self.__check_efs_fs_id(ec2, efs, resource_value)
            except ClientError as e:
                self.__fail(resource_type, e.response.get("Error").get("Message"))
        # EFS Performance Mode check
        elif resource_type == "EFSPerfMode":
            if resource_value != "generalPurpose" and resource_value != "maxIO":
                self.__fail(
                    resource_type,
                    "Invalid value for 'performance_mode'! "
                    "Acceptable values for 'performance_mode' are generalPurpose and maxIO",
                )
        # EFS Throughput check
        elif resource_type == "EFSThroughput":
            throughput_mode = resource_value[0]
            provisioned_throughput = resource_value[1]
            if throughput_mode and (throughput_mode != "provisioned" and throughput_mode != "bursting"):
                self.__fail(
                    resource_type,
                    "Invalid value for 'throughput_mode'! "
                    "Acceptable values for 'throughput_mode' are bursting and provisioned",
                )
            if provisioned_throughput is not None:
                if throughput_mode != "provisioned":
                    self.__fail(
                        resource_type,
                        "When specifying 'provisioned_throughput', the 'throughput_mode' must be set to provisioned",
                    )
            else:
                if throughput_mode == "provisioned":
                    self.__fail(
                        resource_type,
                        "When specifying 'throughput_mode' to provisioned, "
                        "the 'provisioned_throughput' option must be specified",
                    )
        # RAID EBS IOPS
        elif resource_type == "RAIDIOPS":
            raid_iops = float(resource_value[0])
            raid_vol_size = float(resource_value[1])
            if raid_iops > raid_vol_size * 50:
                self.__fail(
                    resource_type,
                    "IOPS to volume size ratio of %s is too high; maximum is 50." % (raid_iops / raid_vol_size),
                )
        # RAID Array Type
        elif resource_type == "RAIDType":
            if resource_value != "0" and resource_value != "1":
                self.__fail(resource_type, "Invalid raid_type, only RAID 0 and RAID 1 are currently supported.")
        # Number of RAID Volumes Requested
        elif resource_type == "RAIDNumVol":
            if int(resource_value) > 5 or int(resource_value) < 2:
                self.__fail(
                    resource_type,
                    "Invalid num_of_raid_volumes. "
                    "Needs min of 2 volumes for RAID and max of 5 EBS volumes are currently supported.",
                )
        # FSX FS Id check
        elif resource_type in ["fsx_fs_id", "FSx_storage_capacity", "FSx_imported_file_chunk_size", "FSx_export_path"]:
            self.__validate_fsx_parameters(resource_type, resource_value)
        # Batch Parameters
        elif resource_type == "AWSBatch_Parameters":
            # Check region
            if self.region in [
                "ap-northeast-3",
                "eu-north-1",
                "cn-north-1",
                "cn-northwest-1",
                "us-gov-east-1",
                "us-gov-west-1",
            ]:
                self.__fail(resource_type, "Region %s is not supported with batch scheduler" % self.region)

            # Check compute instance types
            if "ComputeInstanceType" in resource_value:
                try:
                    s3 = boto3.resource("s3", region_name=self.region)
                    bucket_name = "%s-aws-parallelcluster" % self.region
                    file_name = "instances/batch_instances.json"
                    try:
                        file_contents = s3.Object(bucket_name, file_name).get()["Body"].read().decode("utf-8")
                        supported_instances = json.loads(file_contents)
                        for instance in resource_value["ComputeInstanceType"].split(","):
                            if not instance.strip() in supported_instances:
                                self.__fail(
                                    resource_type, "Instance type %s not supported by batch in this region" % instance
                                )
                    except ClientError as e:
                        self.__fail(resource_type, e.response.get("Error").get("Message"))
                except ClientError as e:
                    self.__fail(resource_type, e.response.get("Error").get("Message"))

            # Check spot bid percentage
            if "SpotPrice" in resource_value:
                if int(resource_value["SpotPrice"]) > 100 or int(resource_value["SpotPrice"]) < 0:
                    self.__fail(resource_type, "Spot bid percentage needs to be between 0 and 100")

            # Check sanity on desired, min and max vcpus
            if "DesiredSize" in resource_value and "MinSize" in resource_value:
                if int(resource_value["DesiredSize"]) < int(resource_value["MinSize"]):
                    self.__fail(resource_type, "Desired vcpus must be greater than or equal to min vcpus")

            if "DesiredSize" in resource_value and "MaxSize" in resource_value:
                if int(resource_value["DesiredSize"]) > int(resource_value["MaxSize"]):
                    self.__fail(resource_type, "Desired vcpus must be fewer than or equal to max vcpus")

            if "MaxSize" in resource_value and "MinSize" in resource_value:
                if int(resource_value["MaxSize"]) < int(resource_value["MinSize"]):
                    self.__fail(resource_type, "Max vcpus must be greater than or equal to min vcpus")

            # Check custom batch url
            if "CustomAWSBatchTemplateURL" in resource_value:
                self.validate("URL", resource_value["CustomAWSBatchTemplateURL"])

    @staticmethod
    def __fail(resource_type, message):
        """
        Print an error and exit.

        :param resource_type: Resource on which the config sanity check failed
        :param message: the message to print
        """
        print("Config sanity error on resource %s: %s" % (resource_type, message))
        sys.exit(1)
