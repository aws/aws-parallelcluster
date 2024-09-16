# Copyright 2019 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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
import json
import logging
import time
from collections import namedtuple

import boto3
from fabric import Connection
from retrying import retry
from time_utils import minutes, seconds
from utils import random_alphanumeric

SnapshotConfig = namedtuple("ClusterConfig", ["ssh_key", "key_name", "vpc_id", "head_node_subnet_id"])


class EBSSnapshotsFactory:
    """Manage creation and destruction of volume snapshots."""

    def __init__(self):
        self.cluster_name = None
        self.iam = None
        self.config = None
        self.instance = None
        self.volume = None
        self.snapshot = None
        self.security_group_id = None
        self._snapshot_instance_profile = None
        self._snapshot_instance_role = None
        self.ec2_resource = None
        self.iam = None
        self.ec2_client = None

    def _initialize_aws_clients(self, region):
        self.ec2_resource = boto3.resource("ec2", region_name=region)
        self.iam = boto3.client("iam", region_name=region)
        self.ec2_client = boto3.client("ec2", region_name=region)

    def create_snapshot(self, request, subnet_id, region):
        """
        Create a snapshot in a given region.
        :param request: The current request
        :param subnet_id: The subnet id where to get the snapshot
        :param region: The region where to get the snapshot
        """
        # Only one snapshot creation per factory allowed
        if self.snapshot:
            raise Exception("Snapshot already created")

        self._initialize_aws_clients(region)

        snapshot_config = SnapshotConfig(
            request.config.getoption("key_path"),
            request.config.getoption("key_name"),
            self.ec2_resource.Subnet(subnet_id).vpc_id,
            subnet_id,
        )
        self.snapshot = self._create_snapshot(region, snapshot_config)
        return self.snapshot.id

    def create_existing_volume(self, request, subnet_id, region):
        """
        Create a volume in a given region.
        :param request: The current request
        :param subnet_id: The subnet id where to get the snapshot
        :param region: The region where to get the snapshot
        """
        # Only one volume creation per factory allowed
        if self.volume:
            raise Exception("Volume already created")

        self._initialize_aws_clients(region)
        volume_config = SnapshotConfig(
            request.config.getoption("key_path"),
            request.config.getoption("key_name"),
            self.ec2_resource.Subnet(subnet_id).vpc_id,
            subnet_id,
        )
        self._create_volume_process(region, volume_config)
        return self.volume.id

    def _create_volume_process(self, region, snapshot_config):
        self.config = snapshot_config
        ami_id = self._get_amazonlinux2_ami()

        self.security_group_id = self._get_security_group_id()

        subnet = self.ec2_resource.Subnet(self.config.head_node_subnet_id)

        # Create a new volume and attach to the instance
        self.volume = self._create_volume(subnet)
        self.instance = self._launch_instance(ami_id, subnet)
        self._attach_volume()
        # Open ssh connection
        self.ssh_conn = self._open_ssh_connection()

        # Partitions the disk with a gpt table and 1 single partition inside
        self._format_volume(self.ssh_conn)

        # Stops the instance before taking the snapshot
        self._release_instance()

    def _create_snapshot(self, region, snapshot_config):
        self._create_volume_process(region, snapshot_config)
        self.snapshot = self._create_volume_snapshot()
        return self.snapshot

    def _create_volume_snapshot(self):
        logging.info("creating snapshot...")
        snapshot = self.ec2_resource.create_snapshot(
            Description="parallelcluster-test-snapshot", VolumeId=self.volume.id
        )
        while snapshot.state == "pending":
            time.sleep(10)
            snapshot = self.ec2_resource.Snapshot(snapshot.id)
        logging.info("Snapshot ready: %s" % snapshot.id)
        return snapshot

    def _format_volume(self, ssh_conn):
        logging.info("Partitioning device...")
        ssh_conn.run("sudo sh -c 'echo -e \"g\nn\np\n1\n\n\nw\" | fdisk /dev/sdf'", warn=True, pty=False, hide=False)
        # Finds out the device name of the volume
        logging.info("Finding device name...")
        device_name = ssh_conn.run("readlink -f /dev/sdf").stdout.strip()
        # formats the 1st partition of disk
        logging.info("Formatting 1st partition...")
        ssh_conn.run(f"sudo sh -c 'mkfs.ext4 {device_name}'")
        logging.info("Mounting partition...")
        ssh_conn.run("sudo mkdir /mnt/tmp")
        ssh_conn.run(f"sudo mount {device_name} /mnt/tmp")
        logging.info("Writing test data...")
        ssh_conn.run("echo 'hello world' | sudo tee -a /mnt/tmp/test.txt")
        logging.info("Device ready")

    def _open_ssh_connection(self):
        tries = 5
        logging.info("Connecting to instance %s " % self.instance.public_ip_address)
        logging.info("ssh_key: %s " % self.config.ssh_key)
        ssh_conn = None

        while tries > 0:
            try:
                ssh_conn = Connection(
                    host=self.instance.public_ip_address,
                    user="ec2-user",
                    forward_agent=False,
                    connect_kwargs={"key_filename": [self.config.ssh_key]},
                )
                ssh_conn.open()
                tries = 0
            except BaseException:  # noqa: B036
                logging.info("SSH connection error - retrying...")
                tries -= 1
                time.sleep(20)

        if (ssh_conn is None) or (not ssh_conn.is_connected):
            raise ConnectionError()
        return ssh_conn

    @retry(retry_on_result=lambda state: state != "attached", wait_fixed=seconds(2), stop_max_delay=minutes(5))
    def _wait_volume_attached(self):
        vol = self.ec2_resource.Volume(self.volume.id)
        attachment_state = next(
            (attachment["State"] for attachment in vol.attachments if attachment["InstanceId"] == self.instance.id), ""
        )
        return attachment_state

    def _attach_volume(self):
        result = self.volume.attach_to_instance(InstanceId=self.instance.id, Device="/dev/sdf")
        logging.info("Attach Volume Result: %s", result)
        self._wait_volume_attached()
        logging.info("Volume attached")

    def _create_volume(self, subnet):
        vol = self.ec2_resource.create_volume(
            Size=10,
            Encrypted=False,
            AvailabilityZone=subnet.availability_zone,
            TagSpecifications=[
                {"ResourceType": "volume", "Tags": [{"Key": "name", "Value": "parallel-cluster-test-volume"}]}
            ],
        )
        logging.info("Volume Id: %s" % vol.id)
        # We can check if the volume is now ready and available:
        logging.info("Waiting for the volume to be ready...")
        while vol.state == "creating":
            vol = self.ec2_resource.Volume(vol.id)
            time.sleep(2)
        logging.info("Volume ready")
        return vol

    def _get_security_group_id(self):
        security_group_id = self.ec2_client.create_security_group(
            Description="security group for snapshot instance node",
            GroupName="snapshot-" + random_alphanumeric(),
            VpcId=self.config.vpc_id,
        )["GroupId"]

        self.ec2_client.authorize_security_group_ingress(
            GroupId=security_group_id,
            IpPermissions=[{"IpProtocol": "tcp", "FromPort": 22, "ToPort": 22, "IpRanges": [{"CidrIp": "0.0.0.0/0"}]}],
        )

        return security_group_id

    def _create_snapshot_instance_profile(self):
        iam_resources_suffix = random_alphanumeric()
        snapshot_instance_role_name = f"SnapshotInstanceRole-{iam_resources_suffix}"
        snapshot_instance_profile_name = f"SnapshotInstanceProfile-{iam_resources_suffix}"
        if not self._snapshot_instance_role:
            trust_policy = {
                "Version": "2012-10-17",
                "Statement": [
                    {"Effect": "Allow", "Principal": {"Service": "ec2.amazonaws.com"}, "Action": "sts:AssumeRole"}
                ],
            }
            logging.info("Creating role (%s).", snapshot_instance_role_name)
            self._snapshot_instance_role = self.iam.create_role(
                RoleName=snapshot_instance_role_name,
                AssumeRolePolicyDocument=json.dumps(trust_policy),
            )
        if not self._snapshot_instance_profile:
            self.iam.attach_role_policy(
                RoleName=snapshot_instance_role_name, PolicyArn="arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
            )
            logging.info("Creating profile (%s).", snapshot_instance_profile_name)
            self._snapshot_instance_profile = self.iam.create_instance_profile(
                InstanceProfileName=snapshot_instance_profile_name
            )
            logging.info(
                "Adding role (%s) to instance profile (%s)", snapshot_instance_role_name, snapshot_instance_profile_name
            )
        self.iam.add_role_to_instance_profile(
            InstanceProfileName=snapshot_instance_profile_name, RoleName=snapshot_instance_role_name
        )

    def _launch_instance(self, ami_id, subnet):
        self._create_snapshot_instance_profile()
        instance = retry(stop_max_attempt_number=5, wait_fixed=minutes(1))(self.ec2_resource.create_instances)(
            ImageId=ami_id,
            KeyName=self.config.key_name,
            MinCount=1,
            MaxCount=1,
            InstanceType="t3.micro",
            MetadataOptions={"HttpTokens": "required", "HttpEndpoint": "enabled"},
            NetworkInterfaces=[
                {
                    "SubnetId": subnet.id,
                    "DeviceIndex": 0,
                    "AssociatePublicIpAddress": True,
                    "Groups": [self.security_group_id],
                }
            ],
            TagSpecifications=[
                {"ResourceType": "instance", "Tags": [{"Key": "Name", "Value": "pcluster-snapshot-instance"}]}
            ],
            IamInstanceProfile={"Name": self._snapshot_instance_profile["InstanceProfile"]["InstanceProfileName"]},
        )[0]
        logging.info("Waiting for instance to be running...")
        while instance.state["Name"] == "pending":
            time.sleep(10)
            instance = self.ec2_resource.Instance(instance.id)

        logging.info("Instance state: %s" % instance.state)
        logging.info("Public dns: %s" % instance.public_dns_name)
        return instance

    def _get_amazonlinux2_ami(self):
        # Finds most recent alinux2 ami in region
        response = self.ec2_client.describe_images(
            Owners=["amazon"],
            Filters=[
                {"Name": "name", "Values": ["amzn2-ami-hvm-*"]},
                {"Name": "description", "Values": ["Amazon Linux 2 AMI*"]},
                {"Name": "architecture", "Values": ["x86_64"]},
                {"Name": "root-device-type", "Values": ["ebs"]},
                {"Name": "state", "Values": ["available"]},
            ],
        )

        amis = sorted(response["Images"], key=lambda x: x["CreationDate"], reverse=True)
        return amis[0]["ImageId"]

    def release_all(self):
        """Release all resources"""
        self._release_instance()
        self._release_instance_iam()
        self._release_security_group()
        self._release_volume()
        self._release_snapshot()

    @retry(stop_max_attempt_number=5, wait_fixed=5000)
    def _release_snapshot(self):
        if self.snapshot:
            logging.info("Deleting snapshot %s" % self.snapshot.id)
            self.snapshot.delete()
            logging.info("Snapshot %s deleted" % self.snapshot.id)

    @retry(stop_max_attempt_number=5, wait_fixed=5000)
    def _release_instance(self):
        if self.instance:
            self.instance.terminate()
            logging.info("Waiting for instance to be terminated...")
            while self.instance.state["Name"] != "terminated":
                time.sleep(10)
                self.instance = self.ec2_resource.Instance(self.instance.id)
            logging.info("Instance terminated")

        self.instance = None

    def _release_instance_iam(self):
        instance_profile_name = self._snapshot_instance_profile["InstanceProfile"]["InstanceProfileName"]
        instance_role_name = self._snapshot_instance_role["Role"]["RoleName"]
        if self._snapshot_instance_role:
            role_name = self._snapshot_instance_role["Role"]["RoleName"]
            self.iam.detach_role_policy(
                RoleName=instance_role_name, PolicyArn="arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
            )
            logging.info("Deleting role: %s", role_name)
            self.iam.remove_role_from_instance_profile(
                InstanceProfileName=instance_profile_name, RoleName=instance_role_name
            )
            retry(stop_max_attempt_number=5, wait_fixed=minutes(1))(self.iam.delete_role)(
                RoleName=self._snapshot_instance_role["Role"]["RoleName"]
            )
            self._snapshot_instance_role = None
        if self._snapshot_instance_profile:
            logging.info(
                "Deleting instance profile: %s",
                self._snapshot_instance_profile["InstanceProfile"]["InstanceProfileName"],
            )
            retry(stop_max_attempt_number=5, wait_fixed=minutes(1))(self.iam.delete_instance_profile)(
                InstanceProfileName=self._snapshot_instance_profile["InstanceProfile"]["InstanceProfileName"]
            )
            self._snapshot_instance_profile = None

    @retry(stop_max_attempt_number=5, wait_fixed=5000)
    def _release_volume(self):
        if self.volume:
            logging.info("Deleting volume %s" % self.volume.id)
            self.volume.delete()
            logging.info("Volume %s deleted" % self.volume.id)
        self.volume = None

    def _release_security_group(self):
        if self.security_group_id:
            logging.info("Deleting security group %s" % self.security_group_id)
            self.ec2_client.delete_security_group(GroupId=self.security_group_id)
            logging.info("Security group %s deleted" % self.security_group_id)
        self.security_group_id = None
