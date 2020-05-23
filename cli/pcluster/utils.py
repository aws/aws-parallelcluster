# Copyright 2018 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance with
# the License. A copy of the License is located at
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
import logging
import os
import random
import re
import string
import sys
import time
import urllib.request
import zipfile
from io import BytesIO

import boto3
import pkg_resources
from botocore.exceptions import ClientError

from pcluster.constants import PCLUSTER_ISSUES_LINK, PCLUSTER_STACK_PREFIX, SUPPORTED_ARCHITECTURES

LOGGER = logging.getLogger(__name__)

STACK_TYPE = "AWS::CloudFormation::Stack"


def get_stack_name(cluster_name):
    return PCLUSTER_STACK_PREFIX + cluster_name


def get_stack_template(stack_name):
    """Get the template used for the given stack."""
    try:
        template = boto3.client("cloudformation").get_template(StackName=stack_name).get("TemplateBody")
    except ClientError as client_err:
        error(
            "Unable to get template for stack {stack_name}.\n{err_msg}".format(
                stack_name=stack_name, err_msg=client_err.response.get("Error").get("Message")
            )
        )
    if not template:
        error("Unable to get template for stack {0}.".format(stack_name))
    return template


def get_stack_version(stack):
    return next(iter([tag["Value"] for tag in stack.get("Tags") if tag["Key"] == "Version"]), None)


def _wait_for_update(stack_name):
    """Wait for the given stack to be finished updating."""
    while get_stack(stack_name).get("StackStatus") == "UPDATE_IN_PROGRESS":
        time.sleep(5)


def update_stack_template(stack_name, updated_template, cfn_parameters):
    """Update stack_name's template to that represented by updated_template."""
    try:
        boto3.client("cloudformation").update_stack(
            StackName=stack_name,
            TemplateBody=json.dumps(updated_template, indent=2),  # Indent so it looks nice in the console
            Parameters=cfn_parameters,
            Capabilities=["CAPABILITY_IAM"],
        )
        _wait_for_update(stack_name)
    except ClientError as client_err:
        if "no updates are to be performed" in client_err.response.get("Error").get("Message").lower():
            return  # If updated_template was the same as the stack's current one, consider the update a success
        error(
            "Unable to update stack template for stack {stack_name}: {emsg}".format(
                stack_name=stack_name, emsg=client_err.response.get("Error").get("Message")
            )
        )


def get_region():
    """Get AWS_DEFAULT_REGION from the environment."""
    return os.environ.get("AWS_DEFAULT_REGION")


def get_partition():
    """Get partition for the AWS_DEFAULT_REGION set in the environment."""
    region = get_region()
    return next(("aws-" + partition for partition in ["us-gov", "cn"] if region.startswith(partition)), "aws")


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


def generate_random_bucket_name(bucket_name_prefix):
    """
    Generate a random bucket name, with the given prefix.

    Bucket name must be at least 3 and no more than 63 characters long.
    Example: <bucket_name_prefix>-4htvo26lchkqeho1
    """
    random_string = "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(16))
    s3_bucket_name = "-".join([bucket_name_prefix.lower()[: 63 - len(random_string) - 1], random_string])
    return s3_bucket_name


def create_s3_bucket(bucket_name, region):
    """
    Create a new S3 bucket.

    :param bucket_name: name of the S3 bucket to create
    :param region: aws region
    :raise ClientError if bucket creation fails
    """
    s3_client = boto3.client("s3")
    """ :type : pyboto3.s3 """
    if region != "us-east-1":
        s3_client.create_bucket(Bucket=bucket_name, CreateBucketConfiguration={"LocationConstraint": region})
    else:
        s3_client.create_bucket(Bucket=bucket_name)


def delete_s3_bucket(bucket_name):
    """
    Delete an S3 bucket together with all stored objects.

    :param bucket_name: name of the S3 bucket to delete
    """
    try:
        bucket = boto3.resource("s3").Bucket(bucket_name)
        bucket.objects.all().delete()
        bucket.delete()
    except boto3.client("s3").exceptions.NoSuchBucket:
        pass
    except ClientError as client_err:
        LOGGER.warning(
            "Failed to delete S3 bucket %s with error %s. Please delete it manually.",
            bucket_name,
            client_err.response.get("Error").get("Message"),
        )


def zip_dir(path):
    """
    Create a zip archive containing all files and dirs rooted in path.

    The archive is created in memory and a file handler is returned by the function.
    :param path: directory containing the resources to archive.
    :return file handler pointing to the compressed archive.
    """
    file_out = BytesIO()
    with zipfile.ZipFile(file_out, "w", zipfile.ZIP_DEFLATED) as ziph:
        for root, _, files in os.walk(path):
            for file in files:
                ziph.write(os.path.join(root, file), os.path.relpath(os.path.join(root, file), start=path))
    file_out.seek(0)
    return file_out


def upload_resources_artifacts(bucket_name, root):
    """
    Upload to the specified S3 bucket the content of the directory rooted in root path.

    All dirs contained in root dir will be uploaded as zip files to $bucket_name/$dir_name/artifacts.zip.
    All files contained in root dir will be uploaded to $bucket_name.

    :param bucket_name: name of the S3 bucket where files are uploaded
    :param root: root directory containing the resources to upload.
    """
    bucket = boto3.resource("s3").Bucket(bucket_name)
    for res in os.listdir(root):
        if os.path.isdir(os.path.join(root, res)):
            bucket.upload_fileobj(zip_dir(os.path.join(root, res)), "%s/artifacts.zip" % res)
        elif os.path.isfile(os.path.join(root, res)):
            bucket.upload_file(os.path.join(root, res), res)


def _get_json_from_s3(region, file_name):
    """
    Get pricing file (if none) and parse content as json.

    :param region: AWS Region
    :param file_name the object name to get
    :return: a json object representing the file content
    :raises ClientError if unable to download the file
    :raises ValueError if unable to decode the file content
    """
    bucket_name = "{0}-aws-parallelcluster".format(region)

    file_contents = boto3.resource("s3").Object(bucket_name, file_name).get()["Body"].read().decode("utf-8")
    return json.loads(file_contents)


def get_supported_features(region, feature):
    """
    Get a json object containing the attributes supported by a feature, for example.

    {
        "Features": {
            "efa": {
                "instances": ["c5n.18xlarge", "p3dn.24xlarge", "i3en.24xlarge"],
                "baseos": ["alinux", "centos7"],
                "schedulers": ["sge", "slurm", "torque"]
            },
            "batch": {
                "instances": ["r3.8xlarge", ..., "m5.4xlarge"]
            }
        }
    }

    :param region: AWS Region
    :param feature: the feature to search for, i.e. "efa" "awsbatch"
    :return: json object containing all the attributes supported by feature
    """
    try:
        features = _get_json_from_s3(region, "features/feature_whitelist.json")
        supported_features = features.get("Features").get(feature)
    except (ValueError, ClientError, KeyError) as e:
        if isinstance(e, ClientError):
            code = e.response.get("Error").get("Code")
            if code == "InvalidAccessKeyId":
                error(e.response.get("Error").get("Message"))
        error(
            "Failed validate {0}. This is probably a bug on our end. "
            "Please submit an issue {1}".format(feature, PCLUSTER_ISSUES_LINK)
        )

    return supported_features


def get_instance_vcpus(region, instance_type):
    """
    Get number of vcpus for the given instance type.

    :param region: AWS Region
    :param instance_type: the instance type to search for.
    :return: the number of vcpus or -1 if the instance type cannot be found
    or the pricing file cannot be retrieved/parsed
    """
    try:
        instances = _get_json_from_s3(region, "instances/instances.json")
        vcpus = int(instances[instance_type]["vcpus"])
    except (KeyError, ValueError, ClientError):
        vcpus = -1

    return vcpus


def get_supported_instance_types():
    """
    Get supported instance types.

    :return: the list of supported instance types
    """
    try:
        instances = _get_json_from_s3(get_region(), "instances/instances.json")
        return instances.keys()
    except (ValueError, ClientError):
        error("Unable to retrieve the list of supported instance types.")


def get_supported_compute_instance_types(scheduler):
    """
    Get supported instance types (and families in awsbatch case).

    :param scheduler: the scheduler for which we want to know the supported compute instance types or families
    :return: the list of supported instance types and families
    """
    instances = (
        get_supported_features(get_region(), "batch").get("instances")
        if scheduler == "awsbatch"
        else get_supported_instance_types()
    )
    return instances


def get_supported_os_for_scheduler(scheduler):
    """
    Return an array containing the list of OSes supported by parallelcluster for the specific scheduler.

    :param scheduler: the scheduler for which we want to know the supported os
    :return: an array of strings of the supported OSes
    """
    oses = ["alinux", "alinux2"]
    if scheduler != "awsbatch":
        oses.extend(["centos6", "centos7", "ubuntu1604", "ubuntu1804"])
    return list(oses)


def get_supported_os_for_architecture(architecture):
    """Return list of supported OSes for the specified architecture."""
    oses = ["alinux2", "ubuntu1604", "ubuntu1804"]
    if architecture == "x86_64":
        oses.extend(["centos6", "centos7", "alinux"])
    return oses


def get_supported_schedulers():
    """
    Return a tuple of the scheduler supported by parallelcluster.

    :return: a tuple of strings of the supported scheduler
    """
    return "sge", "torque", "slurm", "awsbatch"


def get_stack_output_value(stack_outputs, output_key):
    """
    Get output value from Cloudformation Stack Output.

    :param stack_outputs: Cloudformation Stack Outputs
    :param output_key: Output Key
    :return: OutputValue if that output exists, otherwise None
    """
    return next((o.get("OutputValue") for o in stack_outputs if o.get("OutputKey") == output_key), None)


def get_stack(stack_name, cfn_client=None, raise_on_error=False):
    """
    Get the output for a DescribeStacks action for the given Stack.

    :param stack_name: the CFN Stack name
    :param cfn_client: boto3 cloudformation client
    :return: the Stack data type
    """
    try:
        if not cfn_client:
            cfn_client = boto3.client("cloudformation")
        return retry_on_boto3_throttling(cfn_client.describe_stacks, StackName=stack_name).get("Stacks")[0]
    except ClientError as e:
        if raise_on_error:
            raise
        error(e.response.get("Error").get("Message"))


def stack_exists(stack_name):
    """Return a boolean describing whether or not a stack by the given name exists."""
    try:
        get_stack(stack_name)
        return True
    except SystemExit as sys_exit:
        if "Stack with id {0} does not exist".format(stack_name) in str(sys_exit):
            return False
        raise


def get_stack_resources(stack_name):
    """Get the given stack's resources."""
    cfn_client = boto3.client("cloudformation")
    try:
        return retry_on_boto3_throttling(cfn_client.describe_stack_resources, StackName=stack_name).get(
            "StackResources"
        )
    except ClientError as client_err:
        error(
            "Unable to get {stack_name}'s resources: {reason}".format(
                stack_name=stack_name, reason=client_err.response.get("Error").get("Message")
            )
        )


def get_stack_events(stack_name, raise_on_error=False):
    cfn_client = boto3.client("cloudformation")
    try:
        return retry_on_boto3_throttling(cfn_client.describe_stack_events, StackName=stack_name).get("StackEvents")
    except ClientError as client_err:
        if raise_on_error:
            raise
        error(
            "Unable to get {stack_name}'s events: {reason}".format(
                stack_name=stack_name, reason=client_err.response.get("Error").get("Message")
            )
        )


def get_cluster_substacks(cluster_name):
    """Return stack objects with names that match the given prefix."""
    resources = get_stack_resources(get_stack_name(cluster_name))
    return [get_stack(r.get("PhysicalResourceId")) for r in resources if r.get("ResourceType") == STACK_TYPE]


def verify_stack_creation(stack_name, cfn_client):
    """
    Wait for the stack creation to be completed and notify if the stack creation fails.

    :param stack_name: the stack name that we should verify
    :param cfn_client: the CloudFormation client to use to verify stack status
    :return: True if the creation was successful, false otherwise.
    """
    status = get_stack(stack_name, cfn_client).get("StackStatus")
    resource_status = ""
    while status == "CREATE_IN_PROGRESS":
        status = get_stack(stack_name, cfn_client).get("StackStatus")
        events = get_stack_events(stack_name, raise_on_error=True)[0]
        resource_status = ("Status: %s - %s" % (events.get("LogicalResourceId"), events.get("ResourceStatus"))).ljust(
            80
        )
        sys.stdout.write("\r%s" % resource_status)
        sys.stdout.flush()
        time.sleep(5)
    # print the last status update in the logs
    if resource_status != "":
        LOGGER.debug(resource_status)
    if status != "CREATE_COMPLETE":
        LOGGER.critical("\nCluster creation failed.  Failed events:")
        _log_stack_failure_recursive(stack_name)
        return False
    return True


def _log_stack_failure_recursive(stack_name, indent=2):
    """Log stack failures in recursive manner, until there is no substack layer."""
    events = get_stack_events(stack_name, raise_on_error=True)
    for event in events:
        if event.get("ResourceStatus") == "CREATE_FAILED":
            _log_failed_cfn_event(event, indent)
            if event.get("ResourceType") == "AWS::CloudFormation::Stack":
                # Sample substack error:
                # "Embedded stack arn:aws:cloudformation:us-east-2:704743599507:stack/
                # parallelcluster-fsx-fail-FSXSubstack-65ITLJEZJ0DQ/
                # 3a4ecf00-51e7-11ea-8e3e-022fd555c652 was not successfully created:
                # The following resource(s) failed to create: [FileSystem]."
                substack_error = re.search(
                    ".+/({0}.+)/".format(PCLUSTER_STACK_PREFIX), event.get("ResourceStatusReason")
                )
                substack_name = substack_error.group(1) if substack_error else None
                if substack_name:
                    _log_stack_failure_recursive(substack_name, indent=indent + 2)


def _log_failed_cfn_event(event, indent):
    """Log failed CFN events."""
    LOGGER.info(
        "%s- %s %s %s",
        " " * indent,
        event.get("ResourceType"),
        event.get("LogicalResourceId"),
        event.get("ResourceStatusReason"),
    )


def get_templates_bucket_path():
    """Return a string containing the path of bucket."""
    region = get_region()
    s3_suffix = ".cn" if region.startswith("cn") else ""
    return "https://{REGION}-aws-parallelcluster.s3.{REGION}.amazonaws.com{S3_SUFFIX}/templates/".format(
        REGION=region, S3_SUFFIX=s3_suffix
    )


def get_installed_version():
    """Get the version of the installed aws-parallelcluster package."""
    return pkg_resources.get_distribution("aws-parallelcluster").version


def check_if_latest_version():
    """Check if the current package version is the latest one."""
    try:
        latest = json.loads(urllib.request.urlopen("https://pypi.python.org/pypi/aws-parallelcluster/json").read())[
            "info"
        ]["version"]
        if get_installed_version() < latest:
            print("Info: There is a newer version %s of AWS ParallelCluster available." % latest)
    except Exception:
        pass


def warn(message):
    """Print a warning message."""
    print("WARNING: {0}".format(message))


def error(message, fail_on_error=True):
    """Print an error message and Raise SystemExit exception to the stderr if fail_on_error is true."""
    if fail_on_error:
        sys.exit("ERROR: {0}".format(message))
    else:
        print("ERROR: {0}".format(message))


def get_cfn_param(params, key_name):
    """
    Get parameter value from Cloudformation Stack Parameters.

    :param params: Cloudformation Stack Parameters
    :param key_name: Parameter Key
    :return: ParameterValue if that parameter exists, otherwise None
    """
    param_value = next((i.get("ParameterValue") for i in params if i.get("ParameterKey") == key_name), "NONE")
    return param_value.strip()


def get_efs_mount_target_id(efs_fs_id, avail_zone):
    """
    Search for a Mount Target Id in given availability zone for the given EFS file system id.

    :param efs_fs_id: EFS file system Id
    :param avail_zone: Availability zone to verify
    :return: the mount_target_id or None
    """
    mount_target_id = None
    if efs_fs_id:
        mount_targets = boto3.client("efs").describe_mount_targets(FileSystemId=efs_fs_id)

        for mount_target in mount_targets.get("MountTargets"):
            # Check to see if there is an existing mt in the az of the stack
            mount_target_subnet = mount_target.get("SubnetId")
            if avail_zone == get_avail_zone(mount_target_subnet):
                mount_target_id = mount_target.get("MountTargetId")

    return mount_target_id


def get_avail_zone(subnet_id):
    avail_zone = None
    try:
        avail_zone = (
            boto3.client("ec2").describe_subnets(SubnetIds=[subnet_id]).get("Subnets")[0].get("AvailabilityZone")
        )
    except ClientError as e:
        LOGGER.debug(
            "Unable to detect availability zone for subnet {0}.\n{1}".format(
                subnet_id, e.response.get("Error").get("Message")
            )
        )
    return avail_zone


def get_master_server_id(stack_name):
    """Return the physical id of the master server, or [] if no master server."""
    try:
        resources = boto3.client("cloudformation").describe_stack_resource(
            StackName=stack_name, LogicalResourceId="MasterServer"
        )
        return resources.get("StackResourceDetail").get("PhysicalResourceId")
    except ClientError as e:
        error(e.response.get("Error").get("Message"))


def _get_master_server_ip(stack_name):
    """
    Get the IP Address of the MasterServer.

    :param stack_name: The name of the cloudformation stack
    :param config: Config object
    :return private/public ip address
    """
    ec2 = boto3.client("ec2")

    master_id = get_master_server_id(stack_name)
    if not master_id:
        error("MasterServer not running. Can't SSH")
    instance = ec2.describe_instances(InstanceIds=[master_id]).get("Reservations")[0].get("Instances")[0]
    ip_address = instance.get("PublicIpAddress")
    if ip_address is None:
        ip_address = instance.get("PrivateIpAddress")
    state = instance.get("State").get("Name")
    if state != "running" or ip_address is None:
        error("MasterServer: {0}\nCannot get ip address.".format(state.upper()))
    return ip_address


def get_master_ip_and_username(cluster_name):
    cfn = boto3.client("cloudformation")
    try:
        stack_name = get_stack_name(cluster_name)

        stack_result = cfn.describe_stacks(StackName=stack_name).get("Stacks")[0]
        stack_status = stack_result.get("StackStatus")
        valid_status = ["CREATE_COMPLETE", "UPDATE_COMPLETE", "UPDATE_ROLLBACK_COMPLETE"]
        invalid_status = ["DELETE_COMPLETE", "DELETE_IN_PROGRESS"]

        if stack_status in invalid_status:
            error("Unable to retrieve master_ip and username for a stack in the status: {0}".format(stack_status))
        elif stack_status in valid_status:
            outputs = stack_result.get("Outputs")
            master_ip = get_stack_output_value(outputs, "MasterPublicIP") or _get_master_server_ip(stack_name)
            username = get_stack_output_value(outputs, "ClusterUser")
        else:
            # Stack is in CREATING, CREATED_FAILED, or ROLLBACK_COMPLETE but MasterServer is running
            master_ip = _get_master_server_ip(stack_name)
            template = cfn.get_template(StackName=stack_name)
            mappings = template.get("TemplateBody").get("Mappings").get("OSFeatures")
            base_os = get_cfn_param(stack_result.get("Parameters"), "BaseOS")
            username = mappings.get(base_os).get("User")

        if not master_ip:
            error("Failed to get cluster {0} ip.".format(cluster_name))
        if not username:
            error("Failed to get cluster {0} username.".format(cluster_name))

    except ClientError as e:
        error(e.response.get("Error").get("Message"))

    return master_ip, username


def get_master_server_state(stack_name):
    """
    Get the State of the MasterServer.

    :param stack_name: The name of the cloudformation stack
    :return master server state name
    """
    master_id = get_master_server_id(stack_name)
    instance = (
        boto3.client("ec2").describe_instances(InstanceIds=[master_id]).get("Reservations")[0].get("Instances")[0]
    )
    return instance.get("State").get("Name")


def get_info_for_amis(ami_ids):
    """Get information returned by EC2's describe-images API for the given list of AMIs."""
    try:
        return boto3.client("ec2").describe_images(ImageIds=ami_ids).get("Images")
    except ClientError as e:
        error(e.response.get("Error").get("Message"))


def get_supported_architectures_for_instance_type(instance_type):
    """Get a list of architectures supported for the given instance type."""
    # "optimal" compute instance type (when using batch) implies the use of instances from the
    # C, M, and R instance families, and thus an x86_64 architecture.
    # see https://docs.aws.amazon.com/batch/latest/userguide/compute_environment_parameters.html
    if instance_type == "optimal":
        return ["x86_64"]

    try:
        ec2_client = boto3.client("ec2")
        instance_info = ec2_client.describe_instance_types(InstanceTypes=[instance_type]).get("InstanceTypes")[0]
    except ClientError as e:
        error(
            "Unable to get architectures supported by instance type {0}: {1}".format(
                instance_type, e.response.get("Error").get("Message")
            )
        )
    supported_architectures = instance_info.get("ProcessorInfo").get("SupportedArchitectures")
    if not supported_architectures:
        error("Unable to get architectures supported by instance type {0}".format(instance_type))

    # Some instance types support multiple architectures (x86_64 and i386). Filter unsupported ones.
    supported_architectures = list(set(supported_architectures) & set(SUPPORTED_ARCHITECTURES))
    return supported_architectures


def get_cli_log_file():
    return os.path.expanduser(os.path.join("~", ".parallelcluster", "pcluster-cli.log"))


def retry(func, func_args, attempts=1, wait=0):
    """
    Call function and re-execute it if it raises an Exception.

    :param func: the function to execute.
    :param func_args: the positional arguments of the function.
    :param attempts: the maximum number of attempts. Default: 1.
    :param wait: delay between attempts. Default: 0.
    :returns: the result of the function.
    """
    while attempts:
        try:
            return func(*func_args)
        except Exception as e:
            attempts -= 1
            if not attempts:
                raise e

            LOGGER.debug("{0}, retrying in {1} seconds..".format(e, wait))
            time.sleep(wait)


def get_asg_name(stack_name):
    try:
        resources = boto3.client("cloudformation").describe_stack_resources(StackName=stack_name).get("StackResources")
        return [r for r in resources if r.get("LogicalResourceId") == "ComputeFleet"][0].get("PhysicalResourceId")
    except ClientError as e:
        LOGGER.critical(e.response.get("Error").get("Message"))
        sys.stdout.flush()
        sys.exit(1)
    except IndexError:
        LOGGER.critical("Stack %s does not have a ComputeFleet", stack_name)
        sys.exit(1)


def set_asg_limits(asg_name, min, max, desired):
    asg = boto3.client("autoscaling")
    asg.update_auto_scaling_group(
        AutoScalingGroupName=asg_name, MinSize=int(min), MaxSize=int(max), DesiredCapacity=int(desired)
    )


def get_asg_instances(stack):
    asg = boto3.client("autoscaling")
    asg_name = get_asg_name(stack)
    auto_scaling_groups = asg.describe_auto_scaling_groups(AutoScalingGroupNames=[asg_name]).get("AutoScalingGroups")
    if not auto_scaling_groups:
        LOGGER.error("Unable to retrieve ASG info. Please check cluster status.")
        sys.exit(1)
    asg = auto_scaling_groups[0]
    name = [tag.get("Value") for tag in asg.get("Tags") if tag.get("Key") == "aws:cloudformation:logical-id"][0]

    temp_instances = []
    for instance in asg.get("Instances"):
        temp_instances.append([name, instance.get("InstanceId")])

    return temp_instances


def get_batch_ce(stack_name):
    """
    Get name of the AWS Batch Compute Environment.

    :param stack_name: name of the master stack
    :param config: config
    :return: ce_name or exit if not found
    """
    outputs = get_stack(stack_name).get("Outputs")
    return get_stack_output_value(outputs, "BatchComputeEnvironmentArn")


def get_batch_ce_capacity(stack_name):
    client = boto3.client("batch")

    return (
        client.describe_compute_environments(computeEnvironments=[get_batch_ce(stack_name)])
        .get("computeEnvironments")[0]
        .get("computeResources")
        .get("desiredvCpus")
    )


def retry_on_boto3_throttling(func, wait=5, *args, **kwargs):
    while True:
        try:
            return func(*args, **kwargs)
        except ClientError as e:
            if e.response["Error"]["Code"] != "Throttling":
                raise
            LOGGER.debug("Throttling when calling %s function. Will retry in %d seconds.", func.__name__, wait)
            time.sleep(wait)


def get_asg_settings(stack_name):
    try:
        asg_name = get_asg_name(stack_name)
        asg_client = boto3.client("autoscaling")
        return asg_client.describe_auto_scaling_groups(AutoScalingGroupNames=[asg_name]).get("AutoScalingGroups")[0]
    except Exception as e:
        LOGGER.error("Failed when retrieving data for ASG %s with exception %s", asg_name, e)
        raise


def ellipsize(text, max_length):
    """Truncate the provided text to max length, adding ellipsis."""
    # Convert input text to string, just in case
    text = str(text)
    return (text[: max_length - 3] + "...") if len(text) > max_length else text


def policy_name_to_arn(policy_name):
    return "arn:{0}:iam::aws:policy/{1}".format(get_partition(), policy_name)


def get_base_additional_iam_policies():
    return [
        policy_name_to_arn("CloudWatchAgentServerPolicy"),
        policy_name_to_arn("AWSBatchFullAccess"),
    ]


def get_cluster_capacity(stack_name):
    stack = get_stack(stack_name)
    scheduler = get_cfn_param(stack.get("Parameters", []), "Scheduler")
    return (
        get_batch_ce_capacity(stack_name)
        if scheduler == "awsbatch"
        else get_asg_settings(stack_name).get("DesiredCapacity")
    )
