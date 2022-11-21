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
import datetime
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
from typing import NoReturn
from urllib.parse import urlparse

import dateutil.parser
import pkg_resources
import yaml
from pkg_resources import packaging
from yaml import SafeLoader
from yaml.constructor import ConstructorError
from yaml.resolver import BaseResolver

from pcluster.aws.common import get_region
from pcluster.constants import SUPPORTED_OSES_FOR_ARCHITECTURE, SUPPORTED_OSES_FOR_SCHEDULER

LOGGER = logging.getLogger(__name__)


def get_partition():
    """Get partition for the region set in the environment."""
    return next(("aws-" + partition for partition in ["us-gov", "cn"] if get_region().startswith(partition)), "aws")


def get_url_domain_suffix():
    """Get domain suffix."""
    if get_partition() == "aws-cn":
        return "amazonaws.com.cn"
    else:
        return "amazonaws.com"


def replace_url_parameters(url):
    """Replace ${Region} and ${URLSuffix} in url."""
    return url.replace("${Region}", get_region()).replace("${URLSuffix}", get_url_domain_suffix())


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
    :return: file handler pointing to the compressed archive.
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


def to_utc_datetime(time_in, default_timezone=datetime.timezone.utc) -> datetime.datetime:
    """
    Convert a given string, datetime or int into utc datetime.

    :param time_in: Time in a format that may be parsed, integers are assumed to
    be timestamps in UTC timezone.
    :param default_timezone: Timezone to assum in the event that the time is
    unspecified in the input parameter. This applies only for datetime and str inputs
    :return: time as a datetime in UTC timezone
    """
    if isinstance(time_in, int):
        if time_in > 1e12:
            time_in /= 1000
        time_ = datetime.datetime.utcfromtimestamp(time_in)
        time_ = time_.replace(tzinfo=datetime.timezone.utc)
    elif isinstance(time_in, str):
        time_ = dateutil.parser.parse(time_in)
    elif isinstance(time_in, datetime.date):
        time_ = time_in
    else:
        raise TypeError("to_utc_datetime object must be 'str', 'int' or 'datetime'.")
    if time_.tzinfo is None:
        time_ = time_.replace(tzinfo=default_timezone)
    return time_.astimezone(datetime.timezone.utc)


def to_iso_timestr(time_in: datetime.datetime) -> str:
    """
    Convert a given datetime ISO 8601 format with milliseconds.

    :param time_in: datetime to be converted
    :return: time in ISO 8601 UTC format with ms (e.g. 2021-07-15T01:22:02.655Z)
    """
    if time_in.tzinfo is None:
        time_ = time_in.replace(tzinfo=datetime.timezone.utc)
    else:
        time_ = time_in.astimezone(datetime.timezone.utc)
    return to_utc_datetime(time_).isoformat(timespec="milliseconds")[:-6] + "Z"


def datetime_to_epoch(datetime_in: datetime.datetime) -> int:
    """Convert UTC datetime to unix epoch datetime with milliseconds."""
    return int(datetime_in.timestamp() * 1000)


def to_camel_case(snake_case_word):
    """Convert the given snake case word into a camelCase one."""
    pascal = to_pascal_case(snake_case_word)
    return pascal[0].lower() + pascal[1:]


def to_pascal_case(snake_case_word):
    """Convert the given snake case word into a PascalCase one."""
    parts = iter(snake_case_word.split("_"))
    return "".join(word.title() for word in parts)


def to_kebab_case(input):
    """Convert a string into its kebab case representation."""
    str1 = re.sub("(.)([A-Z][a-z]+)", r"\1-\2", input).replace("_", "-")
    return re.sub("([a-z0-9])([A-Z])", r"\1-\2", str1).lower()


def to_snake_case(input):
    """Convert a string into its snake case representation."""
    str1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", input).replace("-", "_")
    return re.sub("([a-z0-9])([A-Z])", r"\1_\2", str1).lower()


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
        events = AWSApi.instance().cfn.get_stack_events(stack_name)["StackEvents"][0]
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


def get_templates_bucket_path():
    """Return a string containing the path of bucket."""
    region = get_region()
    s3_suffix = ".cn" if region.startswith("cn") else ""
    return (
        f"https://{region}-aws-parallelcluster.s3.{region}.amazonaws.com{s3_suffix}/"
        f"parallelcluster/{get_installed_version()}/templates/"
    )


def get_installed_version(base_version_only: bool = False):
    """Get the version of the installed aws-parallelcluster package."""
    pkg_distribution = pkg_resources.get_distribution("aws-parallelcluster")
    return pkg_distribution.version if not base_version_only else pkg_distribution.parsed_version.base_version


def check_if_latest_version():
    """Check if the current package version is the latest one."""
    try:
        pypi_url = "https://pypi.python.org/pypi/aws-parallelcluster/json"
        with urllib.request.urlopen(pypi_url) as url:  # nosec nosemgrep
            latest = json.loads(url.read())["info"]["version"]
        if packaging.version.parse(get_installed_version()) < packaging.version.parse(latest):
            print(f"Info: There is a newer version {latest} of AWS ParallelCluster available.")
    except Exception:  # nosec
        pass


def warn(message):
    """Print a warning message."""
    print(f"WARNING: {message}")


def error(message) -> NoReturn:
    """Raise SystemExit exception to the stderr."""
    sys.exit(f"ERROR: {message}")


def get_cli_log_file():
    default_log_file = os.path.expanduser(os.path.join("~", ".parallelcluster", "pcluster-cli.log"))
    return os.environ.get("PCLUSTER_LOG_FILE", default=default_log_file)


def ellipsize(text, max_length):
    """Truncate the provided text to max length, adding ellipsis."""
    # Convert input text to string, just in case
    text = str(text)
    return (text[: max_length - 3] + "...") if len(text) > max_length else text


def policy_name_to_arn(policy_name):
    return "arn:{0}:iam::aws:policy/{1}".format(get_partition(), policy_name)


def get_resource_name_from_resource_arn(resource_arn):
    return resource_arn.rsplit("/", 1)[-1] if resource_arn else ""


def split_resource_prefix(resource_prefix):
    if resource_prefix:
        split_index = resource_prefix.rfind("/") + 1
        return (
            None
            if split_index == 0
            else resource_prefix
            if split_index == len(resource_prefix)
            else resource_prefix[:split_index],
            None
            if split_index == len(resource_prefix)
            else resource_prefix
            if split_index == 0
            else resource_prefix[split_index:],
        )
    return None, None


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
    with open(file_path, encoding="utf-8") as conf_file:
        yaml_content = yaml_load(conf_file)

    # TODO use from cfn_flip import load_yaml
    return yaml_content


def load_json_dict(file_path):
    """Read the content of a json file."""
    with open(file_path, encoding="utf-8") as file:
        json_content = json.load(file)

    return json_content


def get_attr(obj, attributes, default=None):
    """Get nested object attribute and return default if attr does not exist."""
    for attribute in attributes.split("."):
        obj = getattr(obj, attribute, None)
        if obj is None:
            return default
    return obj


def yaml_load(stream):
    yaml.add_constructor(
        tag=BaseResolver.DEFAULT_MAPPING_TAG, constructor=yaml_no_duplicates_constructor, Loader=SafeLoader
    )
    return yaml.safe_load(stream)


def yaml_no_duplicates_constructor(loader, node, deep=False):
    """Check for duplicate keys."""
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        value = loader.construct_object(value_node, deep=deep)
        if key in mapping:
            raise ConstructorError(problem="Duplicate key found: %s" % key, problem_mark=key_node.start_mark)
        mapping[key] = value

    return loader.construct_mapping(node, deep)


def get_http_tokens_setting(imds_support):
    """Get http tokens settings for supported IMDS version."""
    return "required" if imds_support == "v2.0" else "optional"


def remove_none_values(original_dictionary):
    """Return a dictionary without entries with None value."""
    return {key: value for key, value in original_dictionary.items() if value is not None}
