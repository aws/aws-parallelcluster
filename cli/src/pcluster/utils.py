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
from datetime import datetime
from io import BytesIO
from shlex import quote
from typing import NoReturn
from urllib.parse import urlparse

import pkg_resources
import yaml
from dateutil import tz
from dateutil.parser import parse
from pkg_resources import packaging

from pcluster.aws.common import get_region
from pcluster.constants import SUPPORTED_OSES_FOR_ARCHITECTURE, SUPPORTED_OSES_FOR_SCHEDULER

LOGGER = logging.getLogger(__name__)


def default_config_file_path():
    """Return the default path for the ParallelCluster configuration file."""
    return os.path.expanduser(os.path.join("~", ".parallelcluster", "config"))


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


def verify_stack_status(stack_name, waiting_states, successful_states):
    """
    Wait for the stack creation to be completed and notify if the stack creation fails.

    :param stack_name: the stack name that we should verify
    :param waiting_states: list of status to wait for
    :param successful_states: list of final status considered as successful
    :return: True if the final status is in the successful_states list, False otherwise.
    """
    from pcluster.aws.aws_api import AWSApi  # pylint: disable=import-outside-toplevel

    status = AWSApi.instance().cfn.describe_stack(stack_name).get("StackStatus")
    resource_status = ""
    while status in waiting_states:
        status = AWSApi.instance().cfn.describe_stack(stack_name).get("StackStatus")
        events = AWSApi.instance().cfn.get_stack_events(stack_name)[0]
        resource_status = ("Status: %s - %s" % (events.get("LogicalResourceId"), events.get("ResourceStatus"))).ljust(
            80
        )
        sys.stdout.write("\r%s" % resource_status)
        sys.stdout.flush()
        time.sleep(5)
    # print the last status update in the logs
    if resource_status != "":
        LOGGER.debug(resource_status)
    return status in successful_states


def log_stack_failure_recursive(stack_name, failed_states=None, indent=2):
    """Log stack failures in recursive manner, until there is no substack layer."""
    if not failed_states:
        failed_states = ["CREATE_FAILED"]

    from pcluster.aws.aws_api import AWSApi  # pylint: disable=import-outside-toplevel

    events = AWSApi.instance().cfn.get_stack_events(stack_name)
    for event in events:
        if event.get("ResourceStatus") in failed_states:
            _log_cfn_event(event, indent)
            if event.get("ResourceType") == "AWS::CloudFormation::Stack":
                # Sample substack error:
                # "Embedded stack arn:aws:cloudformation:us-east-2:704743599507:stack/
                # parallelcluster-fsx-fail-FSXSubstack-65ITLJEZJ0DQ/
                # 3a4ecf00-51e7-11ea-8e3e-022fd555c652 was not successfully created:
                # The following resource(s) failed to create: [FileSystem]."
                substack_error = re.search(".+ (arn:aws:cloudformation[^ ]+) ", event.get("ResourceStatusReason"))
                substack_name = substack_error.group(1) if substack_error else None
                if substack_name:
                    log_stack_failure_recursive(substack_name, indent=indent + 2)


def _log_cfn_event(event, indent):
    """Log failed CFN events."""
    from pcluster.aws.aws_api import AWSApi  # pylint: disable=import-outside-toplevel

    print("{}- {}".format(" " * indent, AWSApi.instance().cfn.format_event(event)))


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
        with urllib.request.urlopen(pypi_url) as url:  # nosec nosemgrep
            latest = json.loads(url.read())["info"]["version"]
        if packaging.version.parse(get_installed_version()) < packaging.version.parse(latest):
            print("Info: There is a newer version %s of AWS ParallelCluster available." % latest)
    except Exception:  # nosec
        pass


def warn(message):
    """Print a warning message."""
    print("WARNING: {0}".format(message))


def error(message) -> NoReturn:
    """Raise SystemExit exception to the stderr."""
    sys.exit("ERROR: {0}".format(message))


def get_cli_log_file():
    return os.path.expanduser(os.path.join("~", ".parallelcluster", "pcluster-cli.log"))


def ellipsize(text, max_length):
    """Truncate the provided text to max length, adding ellipsis."""
    # Convert input text to string, just in case
    text = str(text)
    return (text[: max_length - 3] + "...") if len(text) > max_length else text


def policy_name_to_arn(policy_name):
    return "arn:{0}:iam::aws:policy/{1}".format(get_partition(), policy_name)


def grouper(iterable, size):
    """Slice iterable into chunks of size."""
    itr = iter(iterable)
    while True:
        chunk = tuple(itertools.islice(itr, size))
        if not chunk:
            return
        yield chunk


def join_shell_args(args_list):
    return " ".join(quote(arg) for arg in args_list)


def get_url_scheme(url):
    """Parse url to get scheme."""
    return urlparse(url).scheme


def load_yaml_dict(file_path):
    """Read the content of a yaml file."""
    with open(file_path) as conf_file:
        yaml_content = yaml.safe_load(conf_file)

    # TODO use from cfn_flip import load_yaml
    return yaml_content


def timestamp_to_isoformat(timestamp, timezone=None):
    """
    Convert timestamp to a readable date.

    :param timestamp: timestamp to convert
    :param timezone: timezone to use when converting. Defaults to local.
    :return: the converted date
    """
    if not timezone:
        timezone = tz.tzlocal()
    # Forcing microsecond to 0 to avoid having them displayed.
    return datetime.fromtimestamp(timestamp / 1000, tz=timezone).isoformat(timespec="seconds")


def isoformat_to_epoch(time_isoformat):
    """Convert iso8601 date format to unix epoch datetime with milliseconds."""
    return int(parse(time_isoformat).timestamp() * 1000)


def load_json_dict(file_path):
    """Read the content of a json file."""
    with open(file_path) as file:
        json_content = json.load(file)

    return json_content
