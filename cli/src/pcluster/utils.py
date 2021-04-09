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

import functools
import itertools
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
from shlex import quote

import boto3
import pkg_resources
from botocore.exceptions import ClientError
from pkg_resources import packaging

from pcluster.constants import PCLUSTER_STACK_PREFIX, SUPPORTED_OSES_FOR_ARCHITECTURE, SUPPORTED_OSES_FOR_SCHEDULER

LOGGER = logging.getLogger(__name__)


def default_config_file_path():
    """Return the default path for the ParallelCluster configuration file."""
    return os.path.expanduser(os.path.join("~", ".parallelcluster", "config"))


def get_region():
    """
    Get region used internally for all the AWS calls.

    The region from the env has higher priority because it can be explicitly set from the code (e.g. unit test).
    """
    return os.environ.get("AWS_DEFAULT_REGION") or boto3.session.Session().region_name


def get_partition():
    """Get partition for the region set in the environment."""
    return next(("aws-" + partition for partition in ["us-gov", "cn"] if get_region().startswith(partition)), "aws")


def generate_random_name_with_prefix(name_prefix):
    """
    Generate a random name that is no more than 63 characters long, with the given prefix.

    Example: <name_prefix>-4htvo26lchkqeho1
    """
    random_string = generate_random_prefix()
    output_name = "-".join([name_prefix.lower()[: 63 - len(random_string) - 1], random_string])  # nosec
    return output_name


def generate_random_prefix():
    """
    Generate a random prefix that is 16 characters long.

    Example: 4htvo26lchkqeho1
    """
    return "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(16))  # nosec


def _add_file_to_zip(zip_file, path, arcname):
    """
    Add the file at path under the name arcname to the archive represented by zip_file.

    :param zip_file: zipfile.ZipFile object
    :param path: string; path to file being added
    :param arcname: string; filename to put bytes from path under in created archive
    """
    with open(path, "rb") as input_file:
        zinfo = zipfile.ZipInfo(filename=arcname)
        zinfo.external_attr = 0o644 << 16
        zip_file.writestr(zinfo, input_file.read())


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
                _add_file_to_zip(
                    ziph,
                    os.path.join(root, file),
                    os.path.relpath(os.path.join(root, file), start=path),
                )
    file_out.seek(0)
    return file_out


def get_supported_os_for_scheduler(scheduler):
    """
    Return an array containing the list of OSes supported by parallelcluster for the specific scheduler.

    :param scheduler: the scheduler for which we want to know the supported os
    :return: an array of strings of the supported OSes
    """
    return SUPPORTED_OSES_FOR_SCHEDULER.get(scheduler, [])


def get_supported_os_for_architecture(architecture):
    """Return list of supported OSes for the specified architecture."""
    return SUPPORTED_OSES_FOR_ARCHITECTURE.get(architecture, [])


def camelcase(snake_case_word):
    """Convert the given snake case word into a camel case one."""
    parts = iter(snake_case_word.split("_"))
    return "".join(word.title() for word in parts)


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
        error(
            "Could not retrieve CloudFormation stack data. Failed with error: {0}".format(
                e.response.get("Error").get("Message")
            )
        )


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


def verify_stack_status(stack_name, waiting_states, successful_state, cfn_client=None):
    """
    Wait for the stack creation to be completed and notify if the stack creation fails.

    :param stack_name: the stack name that we should verify
    :param cfn_client: the CloudFormation client to use to verify stack status
    :return: True if the creation was successful, false otherwise.
    """
    if not cfn_client:
        cfn_client = boto3.client("cloudformation")
    status = get_stack(stack_name, cfn_client).get("StackStatus")
    resource_status = ""
    while status in waiting_states:
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
    if status != successful_state:
        return False
    return True


def log_stack_failure_recursive(stack_name, indent=2):
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
                    log_stack_failure_recursive(substack_name, indent=indent + 2)


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
        pypi_url = "https://pypi.python.org/pypi/aws-parallelcluster/json"
        latest = json.loads(urllib.request.urlopen(pypi_url).read())["info"]["version"]  # nosec nosemgrep
        if packaging.version.parse(get_installed_version()) < packaging.version.parse(latest):
            print("Info: There is a newer version %s of AWS ParallelCluster available." % latest)
    except Exception:  # nosec
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


def get_cli_log_file():
    return os.path.expanduser(os.path.join("~", ".parallelcluster", "pcluster-cli.log"))


def retry_on_boto3_throttling(func, wait=5, *args, **kwargs):
    while True:
        try:
            return func(*args, **kwargs)
        except ClientError as e:
            if e.response["Error"]["Code"] != "Throttling":
                raise
            LOGGER.debug("Throttling when calling %s function. Will retry in %d seconds.", func.__name__, wait)
            time.sleep(wait)


def ellipsize(text, max_length):
    """Truncate the provided text to max length, adding ellipsis."""
    # Convert input text to string, just in case
    text = str(text)
    return (text[: max_length - 3] + "...") if len(text) > max_length else text


def policy_name_to_arn(policy_name):
    return "arn:{0}:iam::aws:policy/{1}".format(get_partition(), policy_name)


def get_ebs_snapshot_info(ebs_snapshot_id, raise_exceptions=False):
    """
    Return a dict described the information of an EBS snapshot returned by EC2's DescribeSnapshots API.

    Example of output:
    {
        "Description": "This is my snapshot",
        "Encrypted": False,
        "VolumeId": "vol-049df61146c4d7901",
        "State": "completed",
        "VolumeSize": 120,
        "StartTime": "2014-02-28T21:28:32.000Z",
        "Progress": "100%",
        "OwnerId": "012345678910",
        "SnapshotId": "snap-1234567890abcdef0",
    }
    """
    try:
        return boto3.client("ec2").describe_snapshots(SnapshotIds=[ebs_snapshot_id]).get("Snapshots")[0]
    except ClientError as e:
        if raise_exceptions:
            raise
        error(
            "Failed when calling DescribeSnapshot for {0}: {1}".format(
                ebs_snapshot_id, e.response.get("Error").get("Message")
            )
        )


class Cache:
    """Simple utility class providing a cache mechanism for expensive functions."""

    _caches = []

    @staticmethod
    def is_enabled():
        """Tell if the cache is enabled."""
        return not os.environ.get("PCLUSTER_CACHE_DISABLED")

    @staticmethod
    def clear_all():
        """Clear the content of all caches."""
        for cache in Cache._caches:
            cache.clear()

    @staticmethod
    def _make_key(args, kwargs):
        key = args
        if kwargs:
            for item in kwargs.items():
                key += item
        return hash(key)

    @staticmethod
    def cached(function):
        """
        Decorate a function to make it use a results cache based on passed arguments.

        Note: all arguments must be hashable for this function to work properly.
        """
        cache = {}
        Cache._caches.append(cache)

        @functools.wraps(function)
        def wrapper(*args, **kwargs):
            cache_key = Cache._make_key(args, kwargs)

            if Cache.is_enabled() and cache_key in cache:
                return cache[cache_key]
            else:
                return_value = function(*args, **kwargs)
                if Cache.is_enabled():
                    cache[cache_key] = return_value
                return return_value

        return wrapper


def grouper(iterable, n):
    """Slice iterable into chunks of size n."""
    it = iter(iterable)
    while True:
        chunk = tuple(itertools.islice(it, n))
        if not chunk:
            return
        yield chunk


def join_shell_args(args_list):
    return " ".join(quote(arg) for arg in args_list)
