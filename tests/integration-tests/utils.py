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
from datetime import datetime, timedelta
from hashlib import sha1

import boto3
import requests
from assertpy import assert_that
from jinja2 import FileSystemLoader
from jinja2.sandbox import SandboxedEnvironment
from retrying import retry
from time_utils import minutes, seconds

DEFAULT_PARTITION = "aws"
PARTITION_MAP = {
    "cn": "aws-cn",
    "us-gov": "aws-us-gov",
    "us-iso-": "aws-iso",
    "us-isob": "aws-iso-b",
}


def _format_stack_error(message, stack_events=None, cluster_details=None) -> str:
    if cluster_details:
        if "message" in cluster_details:
            message += f"\n\n- Message:\n\t{cluster_details.get('message')}"

        if "configurationValidationErrors" in cluster_details:
            validation_string = "\n\t".join(
                [
                    f"* {validation.get('level')} - {validation.get('type')}:\n\t\t{validation.get('message')}"
                    for validation in cluster_details.get("configurationValidationErrors")
                ],
            )

            if validation_string:
                message += f"\n\n- Validation Failures:\n\t{validation_string}"

        if "failures" in cluster_details:
            details_string = "\n\t".join(
                [
                    f"* {failure.get('failureCode')}:\n\t\t{failure.get('failureReason')}"
                    for failure in cluster_details.get("failures")
                ],
            )
            if details_string:
                message += f"\n\n- Cluster Errors:\n\t{details_string}"

    if stack_events:
        events_string = "\n\t".join(
            [
                f"* {event.get('LogicalResourceId')}:\n\t\t{event.get('ResourceStatusReason')}"
                for event in stack_events
                if event.get("ResourceStatus") == "CREATE_FAILED"
            ]
        )
        if events_string:
            message += f"\n\n- Stack Events:\n\t{events_string}"
    return message


class StackError(BaseException):
    """Exception to throw when stack creation stack fails as part of a test."""

    def __init__(self, message, stack_events=None):
        message = message if message else "StackError has been raised"
        _stack_events = list(stack_events)  # resolve all events so that we can return them
        self.message = _format_stack_error(message, stack_events=_stack_events)
        self.stack_events = _stack_events

    def __str__(self):
        return f"StackError: {self.message}"


class SetupError(BaseException):
    """Exception to throw if an error occurred during test setup."""

    def __init__(self, message):
        self.message = message if message else "SetupError has been raised"

    def __str__(self):
        return f"SetupError: {self.message}"


class StackSetupError(SetupError):
    """Exception to throw when stack creation fails during test setup."""

    def __init__(self, message, stack_events):
        message = message if message else "StackSetupError has been raised"
        super().__init__(_format_stack_error(message, stack_events=stack_events))

    def __str__(self):
        return f"StackSetupError: {self.message}"


class ClusterCreationError(SetupError):
    """Exception to throw when cluster creation fails during test setup."""

    def __init__(self, message, stack_events=None, cluster_details=None):
        message = message if message else "ClusterCreationError has been raised"
        super().__init__(_format_stack_error(message, stack_events=stack_events, cluster_details=cluster_details))

    def __str__(self):
        return f"ClusterCreationError: {self.message}"


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


def run_command(
    command,
    capture_output=True,
    log_error=True,
    env=None,
    timeout=None,
    raise_on_error=True,
    shell=False,
):
    """Execute shell command."""
    if isinstance(command, str) and not shell:
        command = shlex.split(command)
    log_command = command if isinstance(command, str) else " ".join(str(arg) for arg in command)
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
    return prefix + "-{0}{1}{2}".format(random_alphanumeric(), "-" if suffix else "", suffix)


def kebab_case(instr):
    """Convert a snake case string to kebab case."""
    return instr.replace("_", "-")


def random_alphanumeric(size=16):
    """Generate a random alphanumeric string."""
    return "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(size))


def retrieve_cfn_parameters(stack_name, region):
    """Retrieve CloudFormation Stack Parameters from a given stack."""
    return _retrieve_cfn_data(stack_name, region, "Parameter")


def retrieve_cfn_outputs(stack_name, region):
    """Retrieve CloudFormation Stack Outputs from a given stack."""
    return _retrieve_cfn_data(stack_name, region, "Output")


def retrieve_tags(stack_name, region):
    """Retrieve CloudFormation Tags from a given stack."""
    cfn = boto3.client("cloudformation", region_name=region)
    stack = cfn.describe_stacks(StackName=stack_name).get("Stacks")[0]
    return stack.get("Tags", [])


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

    def _retrieve_cfn_resources(stack_name, region):
        for resource in get_cfn_resources(stack_name, region):
            if resource.get("ResourceType") == "AWS::CloudFormation::Stack":
                nested_stack_arn = resource.get("PhysicalResourceId")
                nested_stack_name = get_stack_name_from_stack_arn(nested_stack_arn)
                _retrieve_cfn_resources(nested_stack_name, region)
            else:
                resources[resource.get("LogicalResourceId")] = resource.get("PhysicalResourceId")

    _retrieve_cfn_resources(stack_name, region)
    return resources


def get_cfn_events(stack_name, region):
    """Retrieve CloudFormation Stack Events from a give stack."""
    if not stack_name:
        logging.warning("stack_name not provided when retrieving events")
        return []
    if region is None:
        region = os.environ.get("AWS_DEFAULT_REGION")
    try:
        logging.debug("Getting events for stack {}".format(stack_name))
        cfn = boto3.client("cloudformation", region_name=region)
        response = cfn.describe_stack_events(StackName=stack_name)
        while response:
            yield from response.get("StackEvents")
            next_token = response.get("NextToken")
            response = cfn.describe_stack_events(StackName=stack_name, NextToken=next_token) if next_token else None
    except Exception as e:
        logging.warning("Failed retrieving stack resources for stack {} with exception: {}".format(stack_name, e))
        raise
    return None


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


def get_cluster_nodes_instance_ids(stack_name, region, instance_types=None, node_type=None, queue_name=None):
    """Return a list of cluster Instances Id's."""
    try:
        instances = describe_cluster_instances(
            stack_name,
            region,
            filter_by_node_type=node_type,
            filter_by_instance_types=instance_types,
            filter_by_queue_name=queue_name,
        )
        return [instance["InstanceId"] for instance in instances]
    except Exception as e:
        logging.error("Failed retrieving instance ids with exception: %s", e)
        raise


def get_compute_nodes_instance_ips(stack_name, region):
    """Return a list of compute Instances Ip's."""
    try:
        instances = describe_cluster_instances(
            stack_name,
            region,
            filter_by_node_type="Compute",
        )
        return [instance["PrivateIpAddress"] for instance in instances]
    except Exception as e:
        logging.error("Failed retrieving instance ips for stack %s in region %s", stack_name, region)
        raise e


def describe_cluster_instances(
    stack_name,
    region,
    filter_by_node_type=None,
    filter_by_name=None,
    filter_by_instance_types=None,
    filter_by_queue_name=None,
    filter_by_compute_resource_name=None,
):
    ec2 = boto3.client("ec2", region_name=region)
    filters = [
        {"Name": "tag:parallelcluster:cluster-name", "Values": [stack_name]},
        {"Name": "instance-state-name", "Values": ["running"]},
    ]
    if filter_by_node_type:
        filters.append({"Name": "tag:parallelcluster:node-type", "Values": [filter_by_node_type]})
    if filter_by_queue_name:
        filters.append({"Name": "tag:parallelcluster:queue-name", "Values": [filter_by_queue_name]})
    if filter_by_name:
        filters.append({"Name": "tag:Name", "Values": [filter_by_name]})
    if filter_by_instance_types:
        filters.append({"Name": "instance-type", "Values": filter_by_instance_types})
    if filter_by_compute_resource_name:
        filters.append(
            {"Name": "tag:parallelcluster:compute-resource-name", "Values": [filter_by_compute_resource_name]}
        )
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


def to_pascal_case(snake_case_word):
    """Convert the given snake case word into a PascalCase one."""
    parts = iter(snake_case_word.split("_"))
    return "".join(word.title() for word in parts)


def to_pascal_from_kebab_case(kebab_case_word):
    """Convert the given kebab case word into a PascalCase one."""
    parts = iter(kebab_case_word.split("-"))
    return "".join(word.title() for word in parts)


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
        "rhel8": "ec2-user",
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


def check_head_node_security_group(region, cluster, port, expected_cidr):
    """Check CIDR restriction for a port is in the security group of the head node of the cluster"""
    security_group_id = cluster.cfn_resources.get("HeadNodeSecurityGroup")
    response = boto3.client("ec2", region_name=region).describe_security_groups(GroupIds=[security_group_id])

    ips = response["SecurityGroups"][0]["IpPermissions"]
    target = next(filter(lambda x: x.get("FromPort", -1) == port, ips), {})
    assert_that(target["IpRanges"][0]["CidrIp"]).is_equal_to(expected_cidr)


def check_status(cluster, cluster_status=None, head_node_status=None, compute_fleet_status=None):
    """Check the cluster's status and its head and compute status is as expected."""
    cluster_info = cluster.describe_cluster()
    if cluster_status:
        assert_that(cluster_info["clusterStatus"]).is_equal_to(cluster_status)
    if head_node_status:
        assert_that(cluster_info["headNode"]["state"]).is_equal_to(head_node_status)
    if compute_fleet_status:
        assert_that(cluster_info["computeFleetStatus"]).is_equal_to(compute_fleet_status)


@retry(wait_fixed=seconds(20), stop_max_delay=minutes(5))
def wait_for_computefleet_changed(cluster, desired_status):
    check_status(cluster, compute_fleet_status=desired_status)


def get_network_interfaces_count(instance_type, region_name=None):
    """Return the number of Network Interfaces for the provided instance type."""
    return get_instance_info(instance_type, region_name).get("NetworkInfo").get("MaximumNetworkCards", 1)


def get_root_volume_id(instance_id, region, os):
    """Return the root EBS volume's ID for the given EC2 instance."""
    logging.info("Getting root volume for instance %s", instance_id)
    instance = (
        boto3.client("ec2", region_name=region)
        .describe_instances(InstanceIds=[instance_id])
        .get("Reservations")[0]
        .get("Instances")[0]
    )

    root_device_name = instance.get("RootDeviceName")

    matching_devices = [
        device_mapping
        for device_mapping in instance.get("BlockDeviceMappings")
        if device_mapping.get("DeviceName") == root_device_name
    ]
    assert_that(matching_devices).is_length(1)
    return matching_devices[0].get("Ebs").get("VolumeId")


def get_metadata(metadata_path, raise_error=True):
    """
    Get EC2 instance metadata.

    :param raise_error: set to False if you want to return None in case of Exception (e.g. no EC2 instance)
    :param metadata_path: the metadata relative path
    :return: the metadata value.
    """
    metadata_value = None
    try:
        metadata_base_url = "http://169.254.169.254/latest"
        token = requests.put(
            f"{metadata_base_url}/api/token", headers={"X-aws-ec2-metadata-token-ttl-seconds": "300"}, timeout=3
        )

        headers = {}
        if token.status_code == requests.codes.ok:
            headers["X-aws-ec2-metadata-token"] = token.content
        elif token.status_code >= 300:
            raise Exception("Imds not reachable")
        metadata_value = requests.get(f"{metadata_base_url}/meta-data/{metadata_path}", headers=headers).text
    except Exception as e:
        error_msg = f"Unable to get {metadata_path} metadata. Failed with exception: {e}"
        logging.critical(error_msg)
        if raise_error:
            raise Exception(error_msg)

    logging.debug("%s=%s", metadata_path, metadata_value)
    return metadata_value


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
        with open(file, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logging.exception("Failed when reading json file %s", file)
        raise e


def get_stack_id_tag_filter(stack_arn):
    return {"Name": "tag:aws:cloudformation:stack-id", "Values": [stack_arn]}


def get_arn_partition(region):
    """Get partition for the given region. If region is None, consider the region set in the environment."""
    return next(
        (partition for region_prefix, partition in PARTITION_MAP.items() if region.startswith(region_prefix)),
        DEFAULT_PARTITION,
    )


def get_stack_name_from_stack_arn(arn):
    """
    Return the Stack Name from a Stack ARN
    E.g.
    Stack ARN: "arn:aws:cloudformation:<region>:<account-id>:stack/<stack-name>/<uuid>"
    :param arn:
    :return:
    """
    return arn.rsplit("/", 2)[-2] if arn else ""


def check_pcluster_list_cluster_log_streams(cluster, os, expected_log_streams=None):
    """Test pcluster list-cluster-logs functionality and return cfn-init log stream name."""
    logging.info("Testing that pcluster list-cluster-log-streams is working as expected")

    stream_names = cluster.get_all_log_stream_names()
    if not expected_log_streams:
        expected_log_streams = {
            "HeadNode": {"cfn-init", "cloud-init", "clustermgtd", "chef-client", "slurmctld", "supervisord"},
            "Compute": {"syslog" if os.startswith("ubuntu") else "system-messages", "computemgtd", "supervisord"},
        }

    # check there are the logs of all the instances
    cluster_info = cluster.describe_cluster()
    for instance in cluster.describe_cluster_instances():
        instance_type = "HeadNode" if instance["instanceId"] == cluster_info["headNode"]["instanceId"] else "Compute"
        for stream_name in expected_log_streams[instance_type]:
            assert_that(stream_names).contains(instance_stream_name(instance, stream_name))


def instance_stream_name(instance, stream_name):
    """Return a stream name given an instance."""
    ip_str = instance["privateIpAddress"].replace(".", "-")
    return "ip-{}.{}.{}".format(ip_str, instance["instanceId"], stream_name)


def render_jinja_template(template_file_path, **kwargs):
    file_loader = FileSystemLoader(str(os.path.dirname(template_file_path)))
    env = SandboxedEnvironment(loader=file_loader)
    rendered_template = env.get_template(os.path.basename(template_file_path)).render(**kwargs)
    logging.info("Writing the following to %s\n%s", template_file_path, rendered_template)
    with open(template_file_path, "w", encoding="utf-8") as f:
        f.write(rendered_template)
    return template_file_path


def create_hash_suffix(string_to_hash: str):
    """Create 16digit hash string."""
    return (
        string_to_hash
        if string_to_hash == "HeadNode"
        else sha1(string_to_hash.encode("utf-8")).hexdigest()[:16].capitalize()  # nosec nosemgrep
    )


def _generate_metric_data_queries(metric_name, cluster_name):
    return {
        "Id": metric_name.lower(),
        "MetricStat": {
            "Metric": {
                "Namespace": "ParallelCluster",
                "MetricName": metric_name,
                "Dimensions": [
                    {
                        "Name": "ClusterName",
                        "Value": cluster_name,
                    }
                ],
            },
            "Period": 60,
            "Stat": "Sum",
        },
    }


def retrieve_metric_data(
    cluster_name,
    metric_names,
    region,
    collection_time_min=20,
):
    """Create Boto3 get_metric_data request and output the results."""
    metric_queries = [_generate_metric_data_queries(name, cluster_name) for name in metric_names]

    client = boto3.client("cloudwatch", region)

    return client.get_metric_data(
        MetricDataQueries=metric_queries,
        StartTime=datetime.now() - timedelta(days=collection_time_min),
        EndTime=datetime.now() + timedelta(days=collection_time_min),
        ScanBy="TimestampDescending",
    )


def assert_metrics_has_data(response):
    """
    Iterates through get_metric_data query output and check for desired results,
    output in MetricDataResults format which is described here
    https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/cloudwatch.html#CloudWatch.Client.get_metric_data
    """
    list_of_responses = response["MetricDataResults"]
    for response in list_of_responses:
        assert_that(response["Values"]).is_not_empty()
        assert_that(max(response["Values"])).is_greater_than(0)


@retry(stop_max_attempt_number=8, wait_fixed=minutes(2))
def test_cluster_health_metric(metric_names, cluster_name, region):
    """Test metric value is greater than 0 when the compute node error happens."""
    if "us-iso" in region:
        return
    logging.info(f"Testing that {metric_names} have data.")
    response = retrieve_metric_data(cluster_name, metric_names, region)
    assert_metrics_has_data(response)


def is_dcv_supported(region: str):
    return "us-iso" not in region


def is_fsx_supported(region: str):
    return "us-iso" not in region


def is_directory_supported(region: str, directory_type: str):
    return False if "us-iso" in region and directory_type == "SimpleAD" else True
