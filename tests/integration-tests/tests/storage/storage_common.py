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
import logging
import re
from datetime import datetime

import boto3
from assertpy import assert_that
from cfn_stacks_factory import CfnStack, CfnVpcStack
from clusters_factory import Cluster
from remote_command_executor import RemoteCommandExecutor
from retrying import retry
from time_utils import minutes, seconds
from troposphere import Base64, GetAtt, Ref, Sub, Template
from troposphere.ec2 import Instance, LaunchTemplate, LaunchTemplateSpecification
from troposphere.fsx import (
    ClientConfigurations,
    NfsExports,
    OntapConfiguration,
    OpenZFSConfiguration,
    RootVolumeConfiguration,
)
from troposphere.iam import InstanceProfile, Policy, Role
from utils import generate_stack_name, random_alphanumeric, retrieve_cfn_outputs

from tests.common.schedulers_common import SlurmCommands
from tests.common.utils import CLASSIC_AWS_DOMAIN, get_aws_domain, retrieve_latest_ami


def get_cluster_subnet_ids_groups(cluster: Cluster, scheduler: str, include_head_node: bool = True):
    """
    Returns a nested list of SubnetIds from the cluster configuration for each queue and headnode by default.
    Example: [[HeadNode SubnetId], [<queue-0-SubnetIds>], [<queue-1-SubnetIds>], ...]
    """
    head_node_subnet_id = cluster.config.get("HeadNode", {}).get("Networking", {}).get("SubnetId")
    if scheduler == "slurm":
        queues = cluster.config.get("Scheduling", {}).get("SlurmQueues", [])
    else:
        queues = cluster.config.get("Scheduling", {}).get("AwsBatchQueues", [])

    compute_subnet_ids = [queue.get("Networking", {}).get("SubnetIds", []) for queue in queues]
    if include_head_node:
        return [[head_node_subnet_id], *compute_subnet_ids]
    return compute_subnet_ids


def test_directory_correctly_shared_between_ln_and_hn(
    remote_command_executor_head_node, remote_command_executor_login_node, mount_dir, run_sudo=False
):
    """
    This test verifies if a shared directory is correctly shared between the HeadNode and the LoginNode.

    Preconditions:
    - An EBS volume is expected to be mounted at <HN_folder> on the HeadNode and exported through NFS.
    - The EBS volume is expected to be mounted at <LN_folder> on the LoginNode through NFS.

    Test Steps:
    1. Writes a file from the HeadNode to the shared volume.
    2. Writes a file from the LoginNode to the shared volume.
    3. Reads both files from both the HeadNode and the LoginNode to validate that shared volume is working correctly.

    Expected Result:
    - Both files can be successfully read from both the HeadNode and the LoginNode,
      proving that the shared volume is correctly shared between the two nodes.
    """
    logging.info("Testing FS correctly mounted on login nodes")
    head_node_file = random_alphanumeric()
    logging.info(f"Writing HeadNode File: {head_node_file}")
    remote_command_executor_head_node.run_remote_command(
        ("sudo " if run_sudo else "")
        + "touch {mount_dir}/{head_node_file} && cat {mount_dir}/{head_node_file}".format(
            mount_dir=mount_dir, head_node_file=head_node_file
        )
    )

    login_node_file = random_alphanumeric()
    logging.info(f"Writing LoginNode File: {login_node_file}")
    remote_command_executor_login_node.run_remote_command(
        ("sudo " if run_sudo else "")
        + "touch {mount_dir}/{login_node_file} && cat {mount_dir}/{login_node_file}".format(
            mount_dir=mount_dir, login_node_file=login_node_file
        )
    )

    files_to_read = [head_node_file, login_node_file]
    read_all_files_command = "cat {files_to_read}".format(
        files_to_read=" ".join([f"{mount_dir}/{target_file}" for target_file in files_to_read]),
    )
    # Attempt reading files from HeadNode
    logging.info(f"Reading Files: {files_to_read} from HeadNode")
    remote_command_executor_head_node.run_remote_command(read_all_files_command)

    # Attempt reading files from LoginNode
    logging.info(f"Reading Files: {files_to_read} from LoginNode")
    remote_command_executor_login_node.run_remote_command(read_all_files_command)


def verify_directory_correctly_shared(
    remote_command_executor, mount_dir, scheduler_commands, partitions=None, run_sudo=False
):
    """
    Confirm nodes can read and write to the FileSystem
    Example:
    - Partitions: ["A", "B"]
    While writing:
        "A" writes a file "A-<random_alphanumeric_characters>"
        "B" writes a file "B-<random_alphanumeric_characters>"
    While Reading:
        "A" reads files: ["A-<random_alphanumeric_characters>", "B-<random_alphanumeric_characters>"]
        "B" reads files: ["A-<random_alphanumeric_characters>", "B-<random_alphanumeric_characters>"]
    """
    executor_node_file = random_alphanumeric()
    logging.info(f"{remote_command_executor.get_target_host_type()}: Writing File: {executor_node_file}")
    remote_command_executor.run_remote_command(
        ("sudo " if run_sudo else "")
        + "touch {mount_dir}/{executor_node_file} && cat {mount_dir}/{executor_node_file}".format(
            mount_dir=mount_dir, executor_node_file=executor_node_file
        )
    )
    # Submit a "Write" job to each partition
    files_to_read = [executor_node_file]
    partitions = (
        partitions or scheduler_commands.get_partitions() if isinstance(scheduler_commands, SlurmCommands) else [None]
    )
    for partition in partitions:
        compute_file = "{}-{}".format(partition, random_alphanumeric())
        logging.info(f"Writing Compute File: {compute_file} from {partition}")
        job_command = (
            "sudo " if run_sudo else ""
        ) + "touch {mount_dir}/{compute_file} && cat {mount_dir}/{compute_file}".format(
            mount_dir=mount_dir, compute_file=compute_file
        )
        result = scheduler_commands.submit_command(job_command, partition=partition)
        job_id = scheduler_commands.assert_job_submitted(result.stdout)
        scheduler_commands.wait_job_completed(job_id)
        scheduler_commands.assert_job_succeeded(job_id)
        files_to_read.append(compute_file)

    read_all_files_command = "cat {files_to_read}".format(
        files_to_read=" ".join([f"{mount_dir}/{target_file}" for target_file in files_to_read]),
    )
    # Attempt reading files from executor node
    logging.info(f"{remote_command_executor.get_target_host_type()}: Reading Files: {files_to_read}")
    remote_command_executor.run_remote_command(read_all_files_command)

    # Submit a "Read" job to each partition
    for partition in partitions:
        logging.info(f"Reading Files: {files_to_read} from {partition}")
        result = scheduler_commands.submit_command(read_all_files_command, partition=partition)
        job_id = scheduler_commands.assert_job_submitted(result.stdout)
        scheduler_commands.wait_job_completed(job_id)
        scheduler_commands.assert_job_succeeded(job_id)


# for EBS


def test_ebs_correctly_mounted(remote_command_executor, mount_dir, volume_size):
    logging.info("Testing ebs {0} is correctly mounted".format(mount_dir))
    result = remote_command_executor.run_remote_command(
        "df -h -t ext4 | tail -n +2 | awk '{{print $2, $6}}' | grep '{0}'".format(mount_dir)
    )
    assert_that(result.stdout).matches(r"{size}G {mount_dir}".format(size=volume_size, mount_dir=mount_dir))

    result = remote_command_executor.run_remote_command("cat /etc/fstab")
    assert_that(result.stdout).matches(r"UUID=.* {mount_dir} ext4 _netdev 0 0".format(mount_dir=mount_dir))


# for RAID


def test_raid_correctly_configured(remote_command_executor, raid_type, volume_size, raid_devices):
    result = remote_command_executor.run_remote_command("sudo mdadm --detail /dev/md0")
    assert_that(result.stdout).contains("Raid Level : raid{0}".format(raid_type))
    assert_that(result.stdout).contains("Raid Devices : {0}".format(raid_devices))
    assert_that(result.stdout).contains("Active Devices : {0}".format(raid_devices))
    assert_that(result.stdout).contains("Failed Devices : 0")

    # Compare rounded size to match output from different mdadm version
    # Array Size : 41942912 (40.00 GiB 42.95 GB) --> on Centos7 with mdadm-4.1-4.el7
    array_size = re.search(r"Array Size : .*\((.*) GiB", result.stdout).group(1)
    expected_size = volume_size - 0.1
    assert_that(float(array_size)).is_greater_than_or_equal_to(expected_size)

    # ensure that the RAID array is reassembled automatically on boot
    expected_entry = remote_command_executor.run_remote_command("sudo mdadm --detail --scan").stdout
    mdadm_conf = remote_command_executor.run_remote_command(
        "sudo cat /etc/mdadm.conf || sudo cat /etc/mdadm/mdadm.conf"
    ).stdout
    # We remove from the mdadm scan output all the warning messages that are considered not problematic.
    sanitized_expected_entry = re.sub(
        r"mdadm: Value .* cannot be set as name\. Reason: Not POSIX compatible\. Value ignored\.\n?",
        "",
        expected_entry,
    )
    assert_that(mdadm_conf).contains(sanitized_expected_entry)


def test_raid_correctly_mounted(remote_command_executor, mount_dir, volume_size):
    logging.info("Testing raid {0} is correctly mounted".format(mount_dir))
    result = remote_command_executor.run_remote_command(
        "df -h -t ext4 | tail -n +2 | awk '{{print $2, $6}}' | grep '{0}'".format(mount_dir)
    )
    assert_that(result.stdout).matches(r"{size}G {mount_dir}".format(size=volume_size, mount_dir=mount_dir))

    result = remote_command_executor.run_remote_command("cat /etc/fstab")
    assert_that(result.stdout).matches(
        r"/dev/md0 {mount_dir} ext4 defaults,nofail,_netdev 0 0".format(mount_dir=mount_dir)
    )


# for EFS


def write_file_into_efs(
    region, vpc_stack: CfnVpcStack, efs_ids, request, key_name, cfn_stacks_factory, efs_mount_target_stack_factory, access_point_id=None
):
    """Write file stack contains an instance to write an empty file with random name into each of the efs in efs_ids."""
    write_file_template = Template()
    write_file_template.set_version("2010-09-09")
    write_file_template.set_description("Stack to write a file to the existing EFS")

    # Create mount targets so the instance can communicate with the file system
    mount_target_stack_name = efs_mount_target_stack_factory(efs_ids)

    random_file_names = []
    write_file_user_data = ""
    for efs_id in efs_ids:
        random_file_name = random_alphanumeric()
        write_file_user_data += _write_user_data(efs_id, random_file_name, access_point_id=access_point_id)
        random_file_names.append(random_file_name)
    user_data = f"""
        #cloud-config
        package_update: true
        package_upgrade: true
        runcmd:
        - yum install -y nfs-utils
        - yum install -y amazon-efs-utils
        {write_file_user_data}
        - opt/aws/bin/cfn-signal -e $? --stack ${{AWS::StackName}} --resource InstanceToWriteEFS --region ${{AWS::Region}}
        """  # noqa: E501
    role = write_file_template.add_resource(
        Role(
            "IAMTLS",
            AssumeRolePolicyDocument={
                "Version": "2012-10-17",
                "Statement": [
                    {"Effect": "Allow", "Principal": {"Service": "ec2.amazonaws.com"}, "Action": "sts:AssumeRole"}
                ],
            },
            Policies=[
                Policy(
                    PolicyName="EFSPolicy",
                    PolicyDocument={
                        "Version": "2012-10-17",
                        "Statement": [
                            {
                                "Sid": "VisualEditor0",
                                "Effect": "Allow",
                                "Action": "elasticfilesystem:*",
                                "Resource": "*",
                            }
                        ],
                    },
                )
            ],
        )
    )
    iam_instance_profile = write_file_template.add_resource(InstanceProfile("IamTlsProfile", Roles=[Ref(role)]))
    launch_template = LaunchTemplate.from_dict(
        "LaunchTemplateIMDSv2",
        {
            "LaunchTemplateData": {"MetadataOptions": {"HttpTokens": "required", "HttpEndpoint": "enabled"}},
        },
    )
    write_file_template.add_resource(launch_template)

    write_file_template.add_resource(
        Instance(
            "InstanceToWriteEFS",
            CreationPolicy={"ResourceSignal": {"Timeout": "PT10M"}},
            ImageId=retrieve_latest_ami(region, "alinux2"),
            InstanceType="c5.xlarge",
            LaunchTemplate=LaunchTemplateSpecification(
                LaunchTemplateId=Ref(launch_template), Version=GetAtt(launch_template, "LatestVersionNumber")
            ),
            SubnetId=vpc_stack.get_public_subnet(),
            UserData=Base64(Sub(user_data)),
            KeyName=key_name,
            IamInstanceProfile=Ref(iam_instance_profile),
        )
    )
    stack_name = generate_stack_name("integ-tests-efs-write-file", request.config.getoption("stackname_suffix"))
    write_file_stack = CfnStack(
        name=stack_name, region=region, template=write_file_template.to_json(), capabilities=["CAPABILITY_IAM"]
    )
    cfn_stacks_factory.create_stack(write_file_stack)

    # Delete created stacks so the instance and mount targets are deleted.
    # The goal is to make the content of this function consistent with its name
    cfn_stacks_factory.delete_stack(write_file_stack.name, region)
    cfn_stacks_factory.delete_stack(mount_target_stack_name, region)
    return random_file_names


def _write_user_data(efs_id, random_file_name, access_point_id=None):
    mount_dir = "/mnt/efs/fs"
    access_point_mount_parameter = f",accesspoint={access_point_id}" if access_point_id is not None else ""
    return f"""
        - mkdir -p {mount_dir}
        - mount -t efs -o tls,iam{access_point_mount_parameter} {efs_id}:/ {mount_dir} 
        - touch {mount_dir}/{random_file_name}
        - umount {mount_dir}
        """  # noqa: E501


def test_efs_correctly_mounted(remote_command_executor, mount_dir, tls=False, iam=False):
    # The value of the two parameters should be set according to cluster configuration parameters.
    logging.info("Checking efs {0} is correctly mounted".format(mount_dir))
    # Following EFS instruction to check https://docs.aws.amazon.com/efs/latest/ug/encryption-in-transit.html
    result = remote_command_executor.run_remote_command("mount")
    assert_that(result.stdout).contains(mount_dir)
    if tls:
        logging.info("Checking efs {0} enables in-transit encryption".format(mount_dir))
        assert_that(result.stdout).contains("127.0.0.1:/")
    logging.info("Checking efs {0} is successfully mounted in efs mount log".format(mount_dir))
    result = remote_command_executor.run_remote_command(
        f'sudo grep -E "Successfully mounted.*{mount_dir}" /var/log/amazon/efs/mount.log'
    )
    assert_that(result.stdout).contains(mount_dir)
    # Check fstab content according to https://docs.aws.amazon.com/efs/latest/ug/automount-with-efs-mount-helper.html
    logging.info("Checking efs {0} is correctly configured in fstab".format(mount_dir))
    result = remote_command_executor.run_remote_command("cat /etc/fstab")
    if tls and iam:  # Add a another check when tls and iam are enabled together
        assert_that(result.stdout).matches(rf".* {mount_dir} efs _netdev,noresvport,tls,iam 0 0")
    elif tls:
        assert_that(result.stdout).matches(rf".* {mount_dir} efs _netdev,noresvport,tls 0 0")
    else:
        assert_that(result.stdout).matches(rf".* {mount_dir} efs _netdev,noresvport 0 0")


def check_dra(
    cluster,
    region,
    num_associations,
    test,
    mount_dir,
):
    remote_command_executor = RemoteCommandExecutor(cluster)
    fsx = boto3.client("fsx", region_name=region)
    fsx_id = get_fsx_ids(cluster, region)[0]
    logging.info("FSX ID is: %s", fsx_id)
    associations = fsx.describe_data_repository_associations(Filters=[{"Name": "file-system-id", "Values": [fsx_id]}])[
        "Associations"
    ]
    logging.info(associations)
    assert_that(len(associations)).is_equal_to(num_associations)

    if test:
        result = remote_command_executor.run_remote_command(
            "cat {mount_dir}/{test}/s3_test_file".format(mount_dir=mount_dir, test=test)
        )
        assert_that(result.stdout).is_equal_to("Downloaded by FSx Lustre")


# for FSX


def check_fsx(
    cluster,
    region,
    scheduler_commands_factory,
    mount_dirs,
    bucket_name,
    headnode_only=False,
    file_cache_path=None,
    run_sudo=False,
):
    remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = scheduler_commands_factory(remote_command_executor)
    fsx_ids = get_fsx_ids(cluster, region)
    logging.info("Checking the length of mount dirs is the same as the length of FSXIDs")
    assert_that(len(mount_dirs)).is_equal_to(len(fsx_ids))

    fsx_lustre_mount_options = "defaults,_netdev,flock,user_xattr,noatime,noauto,x-systemd.automount"
    for mount_dir, fsx_id in zip(mount_dirs, fsx_ids):
        logging.info("Checking %s on %s", fsx_id, mount_dir)
        file_system_type = get_file_system_type(fsx_id, region)

        if file_system_type == "LUSTRE":
            mount_name = get_mount_name(fsx_id, region)
            if fsx_id.startswith("fc-"):
                assert_fsx_lustre_correctly_mounted(
                    remote_command_executor,
                    mount_dir,
                    mount_name=mount_name,
                    mount_options=fsx_lustre_mount_options + ",x-systemd.requires=network.service",
                    fsx_id=fsx_id,
                    region=region,
                )
                _test_import_path(remote_command_executor, mount_dir, file_cache_path=file_cache_path)
                _test_export_path(
                    remote_command_executor, mount_dir, bucket_name, region, file_cache_path=file_cache_path
                )
            else:
                assert_fsx_lustre_correctly_mounted(
                    remote_command_executor,
                    mount_dir,
                    mount_name=mount_name,
                    mount_options=fsx_lustre_mount_options,
                    fsx_id=fsx_id,
                    region=region,
                )
                if bucket_name:
                    _test_import_path(remote_command_executor, mount_dir)
                    _test_export_path(remote_command_executor, mount_dir, bucket_name, region)
                    _test_data_repository_task(remote_command_executor, mount_dir, bucket_name, fsx_id, region)
        elif file_system_type == "OPENZFS":
            assert_fsx_open_zfs_correctly_mounted(remote_command_executor, mount_dir, fsx_id)
        elif file_system_type == "ONTAP":
            assert_fsx_ontap_correctly_mounted(remote_command_executor, mount_dir, fsx_id)
        if not headnode_only:
            assert_fsx_correctly_shared(scheduler_commands, remote_command_executor, mount_dir, run_sudo=run_sudo)


def get_efs_ids(cluster, region):
    return retrieve_cfn_outputs(cluster.cfn_name, region).get("EFSIds").split(",")


def get_fsx_ids(cluster, region):
    return retrieve_cfn_outputs(cluster.cfn_name, region).get("FSXIds").split(",")


def get_file_system_type(fsx_id, region):
    fsx = boto3.client("fsx", region_name=region)
    if fsx_id.startswith("fs-"):
        logging.info("Getting file system type from DescribeFilesystems API.")
        return fsx.describe_file_systems(FileSystemIds=[fsx_id]).get("FileSystems")[0].get("FileSystemType")
    elif fsx_id.startswith("fc-"):
        logging.info("Getting file cache type from DescribeFileCache API.")
        return fsx.describe_file_caches(FileCacheIds=[fsx_id]).get("FileCaches")[0].get("FileCacheType")
    else:
        logging.info("Getting file system type from FSx DescribeVolumes API.")
        return fsx.describe_volumes(VolumeIds=[fsx_id]).get("Volumes")[0].get("VolumeType")


def assert_subnet_az_relations_from_config(
    region: str, scheduler: str, cluster: Cluster, expected_in_same_az: bool, include_head_node: bool = True
):
    # [["Subnet1"], ["Subnet2", "Subnet3"], ["Subnet1", "Subnet2"], ...]
    cluster_subnet_ids_groups = get_cluster_subnet_ids_groups(cluster, scheduler, include_head_node)

    # ["AZ1", "AZ2", "AZ3", "AZ1", "AZ2", ...]
    cluster_avail_zones = [
        boto3.resource("ec2", region_name=region).Subnet(subnet_id).availability_zone
        for subnet_ids_group in cluster_subnet_ids_groups
        for subnet_id in subnet_ids_group
    ]

    if expected_in_same_az:
        assert_that(set(cluster_avail_zones)).is_length(1)
    # If caller does not expect same az, we expect more availability zones.
    elif region == "us-isob-east-1":
        # us-isob-east-1 provides 2 availability zones.
        assert_that(len(set(cluster_avail_zones))).is_equal_to(2)
    else:
        # For other regions, we impose a strong check to make sure each subnet is in a different availability zone.
        assert_that(len(set(cluster_avail_zones))).is_equal_to(len(cluster_avail_zones))


def assert_fsx_correctly_shared(scheduler_commands, remote_command_executor, mount_dir, run_sudo=False):
    logging.info("Testing fsx correctly shared on HeadNode and Compute Nodes")
    verify_directory_correctly_shared(
        remote_command_executor,
        mount_dir,
        scheduler_commands,
        partitions=scheduler_commands.get_partitions(),
        run_sudo=run_sudo,
    )


def assert_fsx_ontap_correctly_mounted(remote_command_executor, mount_dir, volume_id):
    logging.info("Testing fsx Ontap is correctly mounted on the head node")
    result = remote_command_executor.run_remote_command("df -h -t nfs4")
    fsx_client = boto3.client("fsx")
    volume = fsx_client.describe_volumes(VolumeIds=[volume_id]).get("Volumes")[0]
    junction_path = volume["OntapConfiguration"]["JunctionPath"]
    storage_virtual_machine_id = volume["OntapConfiguration"]["StorageVirtualMachineId"]
    dns_name = boto3.client("fsx").describe_storage_virtual_machines(
        StorageVirtualMachineIds=[storage_virtual_machine_id]
    )["StorageVirtualMachines"][0]["Endpoints"]["Nfs"]["DNSName"]
    remote_path = f"{dns_name}:{junction_path}"
    assert_that(result.stdout).matches(rf"{remote_path} .* {mount_dir}")
    # example output: "svm-123456.fs-123456.fsx.us-west-2.amazonaws.com:/vol1 9.5G 448K 9.5G 1% /fsx_mount_dir1"""
    check_fstab_file(remote_command_executor, f"{remote_path} {mount_dir} nfs defaults 0 0")


def check_fstab_file(remote_command_executor, expected_entry):
    result = remote_command_executor.run_remote_command("cat /etc/fstab")
    assert_that(result.stdout).matches(expected_entry)


def assert_fsx_open_zfs_correctly_mounted(remote_command_executor, mount_dir, volume_id):
    logging.info("Testing fsx OpenZFS is correctly mounted on the head node")
    result = remote_command_executor.run_remote_command("df -h -t nfs4")
    fsx_client = boto3.client("fsx")
    volume = fsx_client.describe_volumes(VolumeIds=[volume_id]).get("Volumes")[0]
    volume_path = volume["OpenZFSConfiguration"]["VolumePath"]
    fs_id = volume["FileSystemId"]
    dns_name = fsx_client.describe_file_systems(FileSystemIds=[fs_id])["FileSystems"][0]["DNSName"]
    remote_path = f"{dns_name}:{volume_path}"
    assert_that(result.stdout).matches(rf"{remote_path} .* {mount_dir}")
    # example output: "fs-123456.fsx.us-west-2.amazonaws.com:/fsx 64G 256K 64G 1% /fsx_mount_dir0"""
    check_fstab_file(remote_command_executor, f"{remote_path} {mount_dir} nfs nfsvers=4.2 0 0")


@retry(
    retry_on_result=lambda result: result.get("Lifecycle") in ["PENDING", "EXECUTING", "CANCELLING"],
    wait_fixed=seconds(5),
    stop_max_delay=minutes(7),
)
def poll_on_data_export(task, fsx):
    logging.info(
        "Data Export Task {task_id}: {status}".format(task_id=task.get("TaskId"), status=task.get("Lifecycle"))
    )
    return fsx.describe_data_repository_tasks(TaskIds=[task.get("TaskId")]).get("DataRepositoryTasks")[0]


def _test_data_repository_task(remote_command_executor, mount_dir, bucket_name, fsx_fs_id, region):
    logging.info("Testing fsx lustre data repository task")
    file_name = f"file_to_export-{datetime.now().strftime('%Y-%m-%dT%H-%M-%S')}"
    file_contents = "Exported by FSx Lustre"
    remote_command_executor.run_remote_command(
        "echo '{file_contents}' > {mount_dir}/{file_name}".format(
            file_contents=file_contents, mount_dir=mount_dir, file_name=file_name
        )
    )

    # set file permissions
    remote_command_executor.run_remote_command(
        "sudo chmod 777 {mount_dir}/{file_name} && sudo chown 6666:6666 {mount_dir}/{file_name}".format(
            mount_dir=mount_dir, file_name=file_name
        )
    )

    fsx = boto3.client("fsx", region_name=region)
    task = fsx.create_data_repository_task(
        FileSystemId=fsx_fs_id, Type="EXPORT_TO_REPOSITORY", Paths=[file_name], Report={"Enabled": False}
    ).get("DataRepositoryTask")

    task = poll_on_data_export(task, fsx)

    assert_that(task.get("Lifecycle")).is_equal_to("SUCCEEDED")

    remote_command_executor.run_remote_command(
        "sudo aws s3 cp --region {region} s3://{bucket_name}/export_dir/{file_name} ./{file_name}".format(
            region=region, bucket_name=bucket_name, file_name=file_name
        )
    )
    result = remote_command_executor.run_remote_command("cat ./{file_name}".format(file_name=file_name))
    assert_that(result.stdout).is_equal_to(file_contents)

    # test s3 metadata
    s3 = boto3.client("s3", region_name=region)
    metadata = (
        s3.head_object(Bucket=bucket_name, Key="export_dir/{file_name}".format(file_name=file_name))
        .get("ResponseMetadata")
        .get("HTTPHeaders")
    )
    file_owner = metadata.get("x-amz-meta-file-owner")
    file_group = metadata.get("x-amz-meta-file-group")
    file_permissions = metadata.get("x-amz-meta-file-permissions")
    assert_that(file_owner).is_equal_to("6666")
    assert_that(file_group).is_equal_to("6666")
    assert_that(file_permissions).is_equal_to("0100777")


def _test_export_path(remote_command_executor, mount_dir, bucket_name, region, file_cache_path=None):
    logging.info("Testing fsx lustre export path")
    file_name = f"file_to_export-{datetime.now().strftime('%Y-%m-%dT%H-%M-%S')}"
    if file_cache_path:
        remote_command_executor.run_remote_command(
            "echo 'Exported by FSx Lustre' | sudo tee {mount_dir}{file_cache_path}{file_name}".format(
                mount_dir=mount_dir,
                file_cache_path=file_cache_path,
                file_name=file_name,
            )
        )
        remote_command_executor.run_remote_command(
            "sudo lfs hsm_archive {mount_dir}{file_cache_path}{file_name} && sleep 5".format(
                mount_dir=mount_dir,
                file_cache_path=file_cache_path,
                file_name=file_name,
            )
        )
        export_result = remote_command_executor.run_remote_command(
            "sudo lfs hsm_state {mount_dir}{file_cache_path}{file_name}".format(
                mount_dir=mount_dir,
                file_cache_path=file_cache_path,
                file_name=file_name,
            )
        )
        assert_that(export_result.stdout).is_equal_to(
            "{mount_dir}{file_cache_path}{file_name}: (0x00000009) exists archived, archive_id:1".format(
                mount_dir=mount_dir,
                file_cache_path=file_cache_path,
                file_name=file_name,
            )
        )

        remote_command_executor.run_remote_command(
            "sudo aws s3 cp --region {region} s3://{bucket_name}/{file_name} ./{file_name}".format(
                region=region,
                bucket_name=bucket_name,
                file_name=file_name,
            )
        )

    else:
        remote_command_executor.run_remote_command(
            "echo 'Exported by FSx Lustre' > {mount_dir}/{file_name}".format(
                mount_dir=mount_dir,
                file_name=file_name,
            )
        )
        remote_command_executor.run_remote_command(
            "sudo lfs hsm_archive {mount_dir}/{file_name} && sleep 5".format(mount_dir=mount_dir, file_name=file_name)
        )
        remote_command_executor.run_remote_command(
            "sudo aws s3 cp --region {region} s3://{bucket_name}/export_dir/{file_name} ./{file_name}".format(
                region=region,
                bucket_name=bucket_name,
                file_name=file_name,
            )
        )
    result = remote_command_executor.run_remote_command(
        "cat ./{file_name}".format(
            file_name=file_name,
        )
    )
    assert_that(result.stdout).is_equal_to("Exported by FSx Lustre")


def _test_import_path(remote_command_executor, mount_dir, file_cache_path=None):
    logging.info("Testing fsx lustre import path")
    if file_cache_path:
        result = remote_command_executor.run_remote_command(
            "cat {mount_dir}{file_cache_path}s3_test_file".format(mount_dir=mount_dir, file_cache_path=file_cache_path)
        )
    else:
        result = remote_command_executor.run_remote_command("cat {mount_dir}/s3_test_file".format(mount_dir=mount_dir))
    assert_that(result.stdout).is_equal_to("Downloaded by FSx Lustre")


def assert_fsx_lustre_correctly_mounted(
    remote_command_executor, mount_dir, region, fsx_id, mount_name=None, mount_options=None
):
    logging.info("Testing fsx lustre is correctly mounted on the head node")
    result = remote_command_executor.run_remote_command("df -h -t lustre | tail -n +2 | awk '{print $1, $2, $6}'")
    if not mount_name:
        mount_name = get_mount_name(fsx_id, region)
    if not mount_options:
        mount_options = "defaults,_netdev,flock,user_xattr,noatime,noauto,x-systemd.automount"
    assert_that(result.stdout).matches(
        r"[0-9\.]+@tcp:/{mount_name}\s+[15]\.[1278]T\s+{mount_dir}".format(mount_name=mount_name, mount_dir=mount_dir)
    )
    # example output: "192.168.46.168@tcp:/cg7k7bmv 1.7T /fsx_mount_dir"
    check_fstab_file(
        remote_command_executor,
        r"{fsx_id}\.fsx\.[a-z1-9\-]+\.{aws_domain_regex}@tcp:/{mount_name}"
        r" {mount_dir} lustre {mount_options} 0 0".format(
            fsx_id=fsx_id,
            mount_name=mount_name,
            mount_dir=mount_dir,
            mount_options=mount_options,
            aws_domain_regex=re.escape(get_aws_domain_for_fsx(region)),
        ),
    )


def get_aws_domain_for_fsx(region):
    # Return the AWS domain for FSx resources.
    # Notice that China and GovCloud use the Commercial domain.
    if "us-iso" in region:
        return get_aws_domain(region)
    else:
        return CLASSIC_AWS_DOMAIN


def get_mount_name(fsx_fs_id, region):
    fsx = boto3.client("fsx", region_name=region)
    if fsx_fs_id.startswith("fc-"):
        logging.info("Getting MountName from DescribeFileCache API.")
        return (
            fsx.describe_file_caches(FileCacheIds=[fsx_fs_id])
            .get("FileCaches")[0]
            .get("LustreConfiguration")
            .get("MountName")
        )
    else:
        logging.info("Getting MountName from DescribeFilesystem API.")
        return (
            fsx.describe_file_systems(FileSystemIds=[fsx_fs_id])
            .get("FileSystems")[0]
            .get("LustreConfiguration")
            .get("MountName")
        )


def create_fsx_ontap(fsx_factory, num, vpc=None, subnet=None):
    return fsx_factory(
        ports=[111, 635, 2049, 4046],
        ip_protocols=["tcp", "udp"],
        num=num,
        vpc=vpc,
        subnet=subnet,
        file_system_type="ONTAP",
        StorageCapacity=1024,
        OntapConfiguration=OntapConfiguration(DeploymentType="SINGLE_AZ_1", ThroughputCapacity=128),
    )


def create_fsx_open_zfs(fsx_factory, num, vpc=None, subnet=None):
    if num == 0:
        return []
    file_system_ids = fsx_factory(
        ports=[111, 2049, 20001, 20002, 20003],
        ip_protocols=["tcp", "udp"],
        num=num,
        vpc=vpc,
        subnet=subnet,
        file_system_type="OPENZFS",
        StorageCapacity=64,
        OpenZFSConfiguration=OpenZFSConfiguration(
            DeploymentType="SINGLE_AZ_1",
            ThroughputCapacity=64,
            RootVolumeConfiguration=RootVolumeConfiguration(
                NfsExports=[
                    NfsExports(
                        ClientConfigurations=[
                            ClientConfigurations(Clients="*", Options=["rw", "crossmnt", "no_root_squash"])
                        ]
                    )
                ]
            ),
        ),
    )
    volume_list = boto3.client("fsx").describe_volumes(Filters=[{"Name": "file-system-id", "Values": file_system_ids}])[
        "Volumes"
    ]
    return [volume["VolumeId"] for volume in volume_list]


def write_file(cluster, file_path, body="", run_sudo=False):
    """Write a file to a path in the cluster."""
    remote_command_executor = RemoteCommandExecutor(cluster)
    logging.info(f"Writing file {file_path}")
    sudo_cmd = "sudo" if run_sudo else ""
    remote_command_executor.run_remote_command(
        f"{sudo_cmd} mkdir -p $(dirname {file_path}) && {sudo_cmd} echo '{body}' > {file_path}"
    )


def assert_file_exists(cluster, file_path, run_sudo=False):
    """Assert that a file exists in the cluster."""
    remote_command_executor = RemoteCommandExecutor(cluster)
    logging.info(f"Asserting existence for file {file_path}")
    sudo_cmd = "sudo" if run_sudo else ""
    result = remote_command_executor.run_remote_command(f"{sudo_cmd} ls {file_path}", raise_on_error=False)
    assert_that(result.return_code).is_equal_to(0)
