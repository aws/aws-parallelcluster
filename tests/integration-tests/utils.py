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
import os
import random
import re
import shlex
import socket
import string
import subprocess

import boto3
from assertpy import assert_that
from constants import OS_TO_ROOT_VOLUME_DEVICE
from retrying import retry


class InstanceTypesData:
    """Utility class to retrieve instance types information needed for integration tests."""

    # Additional instance types data provided via tests configuration
    additional_instance_types_data = {}
    additional_instance_types_map = {}

    @staticmethod
    def load_additional_instance_types_data(instance_types_data_file):
        """
        Load additional instance types data from configuration json file.
        The file must contain two keys:
          - "instance_types_data": The json structure to be passed to cluster configuration files
          - "instance_types_map": A dict containing logical instance types names (that can be used in cluster config
            files) vs real ones (e.g. "t2.micro")
        """
        instance_types_data_file_content = read_json_file(instance_types_data_file)
        InstanceTypesData.additional_instance_types_data = instance_types_data_file_content.get(
            "instance_types_data", {}
        )
        InstanceTypesData.additional_instance_types_map = instance_types_data_file_content.get("instance_types_map", {})
        logging.info(
            "Additional instance types data loaded: {0}".format(InstanceTypesData.additional_instance_types_data)
        )

    @staticmethod
    def get_instance_info(instance_type, region_name=None):
        """Return the results of calling EC2's DescribeInstanceTypes API for the given instance type."""
        if (
            InstanceTypesData.additional_instance_types_data
            and instance_type in InstanceTypesData.additional_instance_types_data.keys()
        ):
            instance_info = InstanceTypesData.additional_instance_types_data[instance_type]
        else:
            try:
                ec2_client = boto3.client("ec2", region_name=region_name)
                instance_info = ec2_client.describe_instance_types(InstanceTypes=[instance_type]).get("InstanceTypes")[
                    0
                ]
            except Exception as exception:
                logging.error(f"Failed to get instance type info for instance type: {exception}")
                raise

        return instance_info


def retry_if_subprocess_error(exception):
    """Return True if we should retry (in this case when it's a CalledProcessError), False otherwise"""
    return isinstance(exception, subprocess.CalledProcessError)


def run_command(command, capture_output=True, log_error=True, env=None, timeout=None, raise_on_error=True, shell=False):
    """Execute shell command."""
    if isinstance(command, str) and not shell:
        command = shlex.split(command)
    log_command = command if isinstance(command, str) else " ".join(command)
    logging.info("Executing command: {}".format(log_command))
    try:
        result = subprocess.run(
            command,
            capture_output=capture_output,
            universal_newlines=True,
            encoding="utf-8",
            env=env,
            timeout=timeout,
            shell=shell,
        )
        result.check_returncode()
    except subprocess.CalledProcessError:
        if log_error:
            logging.error(
                "Command {0} failed with error:\n{1}\nand output:\n{2}".format(
                    log_command, result.stderr, result.stdout
                )
            )
        if raise_on_error:
            raise
    except subprocess.TimeoutExpired:
        if log_error:
            logging.error("Command {0} timed out after {1} sec".format(log_command, timeout))
        if raise_on_error:
            raise

    return result


def generate_stack_name(prefix, suffix):
    """Generate a stack name with prefix, suffix, and a random string in the middle"""
    return prefix + "-{0}{1}{2}".format(
        random_alphanumeric(),
        "-" if suffix else "",
        suffix,
    )


def random_alphanumeric(size=16):
    """Generate a random alphanumeric string."""
    return "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(size))


def retrieve_cfn_parameters(stack_name, region):
    """Retrieve CloudFormation Stack Parameters from a given stack."""
    return _retrieve_cfn_data(stack_name, region, "Parameter")


def retrieve_cfn_outputs(stack_name, region):
    """Retrieve CloudFormation Stack Outputs from a given stack."""
    return _retrieve_cfn_data(stack_name, region, "Output")


@retry(wait_exponential_multiplier=500, wait_exponential_max=5000, stop_max_attempt_number=5)
def _retrieve_cfn_data(stack_name, region, data_type):
    logging.debug("Retrieving stack %s for stack %s", data_type, stack_name)
    try:
        cfn = boto3.client("cloudformation", region_name=region)
        stack = cfn.describe_stacks(StackName=stack_name).get("Stacks")[0]
        result = {}
        for output in stack.get(f"{data_type}s", []):
            result[output.get(f"{data_type}Key")] = output.get(f"{data_type}Value")
        return result
    except Exception as e:
        logging.warning("Failed retrieving stack %s for stack %s with exception: %s", data_type, stack_name, e)
        raise


@retry(wait_exponential_multiplier=500, wait_exponential_max=5000, stop_max_attempt_number=5)
def get_cfn_resources(stack_name, region=None):
    """Return the results of calling list_stack_resources for the given stack."""
    if region is None:
        region = os.environ.get("AWS_DEFAULT_REGION")
    try:
        logging.debug("Retrieving stack resources for stack {}".format(stack_name))
        cfn = boto3.client("cloudformation", region_name=region)
        return cfn.list_stack_resources(StackName=stack_name).get("StackResourceSummaries")
    except Exception as e:
        logging.warning("Failed retrieving stack resources for stack {} with exception: {}".format(stack_name, e))
        raise


def retrieve_cfn_resources(stack_name, region):
    """Retrieve CloudFormation Stack Resources from a given stack."""
    resources = {}
    for resource in get_cfn_resources(stack_name, region):
        resources[resource.get("LogicalResourceId")] = resource.get("PhysicalResourceId")
    return resources


def get_substacks(stack_name, region=None, sub_stack_name=None):
    """Return the PhysicalResourceIds for all substacks created by the given stack."""
    if region is None:
        region = os.environ.get("AWS_DEFAULT_REGION")
    stack_resources = get_cfn_resources(stack_name, region)

    stacks = [r for r in stack_resources if r.get("ResourceType") == "AWS::CloudFormation::Stack"]
    if sub_stack_name:
        stacks = filter(lambda r: r.get("LogicalResourceId") == sub_stack_name, stacks)
    return [r.get("PhysicalResourceId") for r in stacks]


def get_compute_nodes_count(stack_name, region, instance_types=None):
    return len(get_compute_nodes_instance_ids(stack_name, region, instance_types=instance_types))


def get_compute_nodes_instance_ids(stack_name, region, instance_types=None):
    """Return a list of Compute Instances Id's."""
    return get_cluster_nodes_instance_ids(stack_name, region, instance_types, node_type="Compute")


def get_cluster_nodes_instance_ids(stack_name, region, instance_types=None, node_type=None):
    """Return a list of cluster Instances Id's."""
    try:
        instances = _describe_cluster_instances(
            stack_name, region, filter_by_node_type=node_type, filter_by_instance_types=instance_types
        )
        instance_ids = []
        for instance in instances:
            instance_ids.append(instance.get("InstanceId"))
        return instance_ids
    except Exception as e:
        logging.error("Failed retrieving instance ids with exception: {}".format(e))
        raise


def _describe_cluster_instances(
    stack_name, region, filter_by_node_type=None, filter_by_name=None, filter_by_instance_types=None
):
    ec2 = boto3.client("ec2", region_name=region)
    filters = [
        {"Name": "tag:parallelcluster:cluster-name", "Values": [stack_name]},
        {"Name": "instance-state-name", "Values": ["running"]},
    ]
    if filter_by_node_type:
        filters.append({"Name": "tag:parallelcluster:node-type", "Values": [filter_by_node_type]})
    if filter_by_name:
        filters.append({"Name": "tag:Name", "Values": [filter_by_name]})
    if filter_by_instance_types:
        filters.append({"Name": "instance-type", "Values": filter_by_instance_types})
    instances = []
    for page in paginate_boto3(ec2.describe_instances, Filters=filters):
        instances.extend(page.get("Instances", []))
    return instances


def get_instance_ids_compute_hostnames_conversion_dict(instance_ids, id_to_hostname, region=None):
    """Return instanceIDs to hostnames dict if id_to_hostname=True, else return hostname to instanceID dict."""
    try:
        if not region:
            region = os.environ.get("AWS_DEFAULT_REGION")
        conversion_dict = {}
        ec2_client = boto3.client("ec2", region_name=region)
        response = ec2_client.describe_instances(InstanceIds=instance_ids).get("Reservations")
        for reservation in response:
            for instance in reservation.get("Instances"):
                instance_hostname = instance.get("PrivateDnsName").split(".")[0]
                instance_id = instance.get("InstanceId")
                if id_to_hostname:
                    conversion_dict[instance_id] = instance_hostname
                else:
                    conversion_dict[instance_hostname] = instance_id

        return conversion_dict
    except Exception as e:
        logging.error("Failed retrieving hostnames for instances {} with exception: {}".format(instance_ids, e))


def to_snake_case(input):
    """Convert a string into its snake case representation."""
    s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", input)
    return re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def create_s3_bucket(bucket_name, region):
    """
    Create a new S3 bucket.

    :param bucket_name: name of the S3 bucket to create
    :param region: region where the bucket is created
    """
    s3_client = boto3.client("s3", region_name=region)
    if region != "us-east-1":
        s3_client.create_bucket(Bucket=bucket_name, CreateBucketConfiguration={"LocationConstraint": region})
    else:
        s3_client.create_bucket(Bucket=bucket_name)
    # Enable versioning on bucket
    s3_client.put_bucket_versioning(Bucket=bucket_name, VersioningConfiguration={"Status": "Enabled"})


@retry(wait_exponential_multiplier=500, wait_exponential_max=5000, stop_max_attempt_number=3)
def delete_s3_bucket(bucket_name, region):
    """
    Delete an S3 bucket together with all stored objects.

    :param bucket_name: name of the S3 bucket to delete
    :param region: region of the bucket
    """
    try:
        bucket = boto3.resource("s3", region_name=region).Bucket(bucket_name)
        bucket.objects.all().delete()
        bucket.object_versions.all().delete()
        bucket.delete()
    except boto3.client("s3").exceptions.NoSuchBucket:
        pass


def set_credentials(region, credential_arg):
    """
    Set credentials for boto3 clients and cli commands

    :param region: region of the bucket
    :param credential_arg: credential list
    """
    if os.environ.get("AWS_CREDENTIALS_FOR_REGION", "no_region") == region:
        logging.info(f"AWS credentials are already set for region: {region}")
        return

    if credential_arg:
        # credentials = dict { region1: (endpoint1, arn1, external_id1),
        #                      region2: (endpoint2, arn2, external_id2),
        #                      [...],
        #                    }
        credentials = {
            region: (endpoint, arn, external_id)
            for region, endpoint, arn, external_id in [
                tuple(credential_tuple.strip().split(","))
                for credential_tuple in credential_arg
                if credential_tuple.strip()
            ]
        }

        if region in credentials:
            credential_endpoint, credential_arn, credential_external_id = credentials.get(region)
            aws_credentials = _retrieve_sts_credential(
                credential_endpoint, credential_arn, credential_external_id, region
            )

            logging.info(f"Setting AWS credentials for region: {region}")

            # Set credential for all boto3 client
            boto3.setup_default_session(
                aws_access_key_id=aws_credentials["AccessKeyId"],
                aws_secret_access_key=aws_credentials["SecretAccessKey"],
                aws_session_token=aws_credentials["SessionToken"],
            )

            # Set credential for all cli command e.g. pcluster create
            os.environ["AWS_ACCESS_KEY_ID"] = aws_credentials["AccessKeyId"]
            os.environ["AWS_SECRET_ACCESS_KEY"] = aws_credentials["SecretAccessKey"]
            os.environ["AWS_SESSION_TOKEN"] = aws_credentials["SessionToken"]
            os.environ["AWS_CREDENTIALS_FOR_REGION"] = region


def _retrieve_sts_credential(credential_endpoint, credential_arn, credential_external_id, region):
    match = re.search(r"https://sts\.(.*?)\.", credential_endpoint)
    endpoint_region = match.group(1)

    assert_that(credential_endpoint and endpoint_region and credential_arn and credential_external_id).is_true()

    sts = boto3.client("sts", region_name=endpoint_region, endpoint_url=credential_endpoint)
    assumed_role_object = sts.assume_role(
        RoleArn=credential_arn, ExternalId=credential_external_id, RoleSessionName=region + "_integration_tests_session"
    )
    aws_credentials = assumed_role_object["Credentials"]

    return aws_credentials


def unset_credentials():
    """Unset credentials"""
    # Unset credential for all boto3 client
    logging.info("Unsetting AWS credentials")
    boto3.setup_default_session()
    # Unset credential for cli command e.g. pcluster create
    if "AWS_ACCESS_KEY_ID" in os.environ:
        del os.environ["AWS_ACCESS_KEY_ID"]
    if "AWS_SECRET_ACCESS_KEY" in os.environ:
        del os.environ["AWS_SECRET_ACCESS_KEY"]
    if "AWS_SESSION_TOKEN" in os.environ:
        del os.environ["AWS_SESSION_TOKEN"]
    if "AWS_CREDENTIALS_FOR_REGION" in os.environ:
        del os.environ["AWS_CREDENTIALS_FOR_REGION"]


def set_logger_formatter(formatter):
    for handler in logging.getLogger().handlers:
        handler.setFormatter(formatter)


def paginate_boto3(method, **kwargs):
    """
    Return a generator for a boto3 call, this allows pagination over an arbitrary number of responses.

    :param method: boto3 method
    :param kwargs: arguments to method
    :return: generator with boto3 results
    """
    client = method.__self__
    paginator = client.get_paginator(method.__name__)
    for page in paginator.paginate(**kwargs).result_key_iters():
        for result in page:
            yield result


def get_vpc_snakecase_value(vpc_stack):
    """Return dict containing snakecase vpc variables."""
    vpc_output_dict = {}
    for key, value in vpc_stack.cfn_outputs.items():
        vpc_output_dict[to_snake_case(key)] = value
    return vpc_output_dict


def get_username_for_os(os):
    """Return username for a given os."""
    usernames = {
        "alinux2": "ec2-user",
        "centos7": "centos",
        "ubuntu1804": "ubuntu",
        "ubuntu2004": "ubuntu",
    }
    return usernames.get(os)


def add_keys_to_known_hosts(hostname, host_keys_file):
    """Add ssh key for a host to a known_hosts file."""
    os.system("ssh-keyscan -t rsa {0} >> {1}".format(hostname, host_keys_file))


def remove_keys_from_known_hosts(hostname, host_keys_file, env):
    """Remove ssh key for a host from a known_hosts file."""
    for host in hostname, "{0}.".format(hostname), socket.gethostbyname(hostname):
        run_command("ssh-keygen -R {0} -f {1}".format(host, host_keys_file), env=env)


def get_instance_info(instance_type, region_name=None):
    """Return the results of calling EC2's DescribeInstanceTypes API for the given instance type."""
    return InstanceTypesData.get_instance_info(instance_type, region_name)


def get_architecture_supported_by_instance_type(instance_type, region_name=None):
    """Return the architecture supported by the given instance type (which is also supported by ParallelCluster)."""
    pcluster_architectures = ["x86_64", "arm64"]
    instance_architectures = (
        get_instance_info(instance_type, region_name).get("ProcessorInfo").get("SupportedArchitectures")
    )

    # Some instance types support architectures that ParallelCluster does not (e.g., i386). Filter those out.
    instance_architectures = list(set(instance_architectures) & set(pcluster_architectures))

    # It's not possible for an instance type to support both arm64 and x86_64, and to be used with ParallelCluster
    # it must support one of those two.
    assert_that(len(instance_architectures)).is_equal_to(1)

    return instance_architectures[0]


def check_headnode_security_group(region, cluster, port, expected_cidr):
    """Check CIDR restriction for a port is in the security group of the head node of the cluster"""
    security_group_id = cluster.cfn_resources.get("HeadNodeSecurityGroup")
    response = boto3.client("ec2", region_name=region).describe_security_groups(GroupIds=[security_group_id])

    ips = response["SecurityGroups"][0]["IpPermissions"]
    target = next(filter(lambda x: x.get("FromPort", -1) == port, ips), {})
    assert_that(target["IpRanges"][0]["CidrIp"]).is_equal_to(expected_cidr)


def get_network_interfaces_count(instance_type, region_name=None):
    """Return the number of Network Interfaces for the provided instance type."""
    return get_instance_info(instance_type, region_name).get("NetworkInfo").get("MaximumNetworkCards", 1)


def get_root_volume_id(instance_id, region, os):
    """Return the root EBS volume's ID for the given EC2 instance."""
    logging.info("Getting root volume for instance %s", instance_id)
    block_device_mappings = (
        boto3.client("ec2", region_name=region)
        .describe_instances(InstanceIds=[instance_id])
        .get("Reservations")[0]
        .get("Instances")[0]
        .get("BlockDeviceMappings")
    )
    matching_devices = [
        device_mapping
        for device_mapping in block_device_mappings
        if device_mapping.get("DeviceName") == OS_TO_ROOT_VOLUME_DEVICE[os]
    ]
    assert_that(matching_devices).is_length(1)
    return matching_devices[0].get("Ebs").get("VolumeId")


def dict_has_nested_key(d, keys):
    """Check if *keys (nested) exists in d (dict)."""
    _d = d
    for key in keys:
        try:
            _d = _d[key]
        except KeyError:
            return False
    return True


def dict_add_nested_key(d, value, keys):
    _d = d
    for key in keys[:-1]:
        if key not in _d:
            _d[key] = {}
        _d = _d[key]
    _d[keys[-1]] = value


def read_json_file(file):
    """Read a Json file into a String and raise an exception if the file is invalid."""
    try:
        with open(file) as f:
            return json.load(f)
    except Exception as e:
        logging.exception("Failed when reading json file %s", file)
        raise e
