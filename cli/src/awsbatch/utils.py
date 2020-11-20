#!/usr/bin/env python2.6

# Copyright 2018 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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
from __future__ import print_function

import pipes
import re
import sys
from datetime import datetime

from dateutil import tz


def fail(error_message):
    """
    Print error message and exit(1).

    :param error_message: message to print
    """
    print(error_message, file=sys.stderr)
    exit(1)


def get_region_by_stack_id(stack_id):
    """
    Parse Cloudformation stack arn and get region.

    :param stack_id: something like arn:aws:cloudformation:<region>:<account-id>:stack/<stack-name>/<id>'
    :return: region
    """
    return re.search(r"^arn:aws.*?:cloudformation:([^:]*).*", stack_id).group(1)


def get_job_definition_name_by_arn(job_definition_arn, version=False):
    """
    Parse Job Definition arn and get name.

    :param job_definition_arn: something like arn:aws:batch:<region>:<account-id>:job-definition/<name>:<version>
    :param version: set to true if
    :return: the job definition name
    """
    pattern = r".*/(.*)" if version else r".*/(.*):(.*)"
    return re.search(pattern, job_definition_arn).group(1)


def convert_to_date(timestamp, timezone=None):
    """
    Convert timestamp to a readable date.

    :param timestamp: timestamp to convert
    :param timezone: timezone to use when converting. Defaults to local.
    :return: the converted date
    """
    if not timezone:
        timezone = tz.tzlocal()
    # Forcing microsecond to 0 to avoid having them displayed.
    return datetime.fromtimestamp(timestamp / 1000, tz=timezone).replace(microsecond=0).isoformat()


def hide_keys(dictionary, keys_to_hide, new_value="xxx"):
    """
    Return a copy of the given dictionary on which specified keys will be replaced by the new_value word (or 'xxx').

    :param dictionary: a dictionary
    :param keys_to_hide: keys to hide in the output dictionary
    :param new_value: replacement string for keys to hide
    :return: the new dictionary with hidden items
    """
    _new_dict = {}
    for key, value in dictionary.items():
        _new_dict[key] = new_value if key in keys_to_hide else value
    return _new_dict


def shell_join(array):
    """
    Return a shell-quoted version of the input array.

    :param array: input array
    :return: the shell-quoted string
    """
    return " ".join(pipes.quote(item) for item in array)


def is_job_array(job):
    """
    Check if the given job is an array.

    :param job: the job dictionary returned by AWS Batch api
    :return: true if the job is an array, false otherwise
    """
    return "arrayProperties" in job and "size" in job["arrayProperties"]


def is_mnp_job(job):
    """
    Check if the given job is an MNP job.

    :param job: the job dictionary returned by AWS Batch api
    :return: true if the job is mnp, false otherwise
    """
    return "nodeProperties" in job and "numNodes" in job["nodeProperties"]


def get_job_type(job):
    """
    Get the type of the job.

    Job type is of type string and not enum since enums have been introduced
    since Python 3.4.

    :param job: the job dictionary returned by AWS Batch api
    :return: one of ["SIMPLE", "ARRAY", "MNP"]
    """
    if is_job_array(job):
        return "ARRAY"
    if is_mnp_job(job):
        return "MNP"
    return "SIMPLE"


class S3Uploader(object):
    """S3 uploader."""

    def __init__(self, boto3_factory, s3_bucket, default_folder=""):
        """Initialize the object.

        :param boto3_factory: initialized Boto3ClientFactory object
        :param s3_bucket: S3 bucket to use
        :param default_folder: S3 folder on which put the files (optional)
        """
        self.s3_client = boto3_factory.get_client("s3")
        self.s3_bucket = s3_bucket
        self.default_folder = default_folder
        if default_folder:
            self.__create_folder(default_folder)

    def __create_folder(self, folder):
        """
        Create an empty pseudo-folder in the S3 bucket.

        :param folder: the path to create
        """
        if not folder.endswith("/"):
            folder = folder + "/"

        self.s3_client.put_object(Bucket=self.s3_bucket, Key=folder, Body="")

    def put_file(self, file_path, key_name, folder=None):
        """
        Upload a file to an s3 bucket.

        :param file_path: file to upload
        :param key_name: S3 key to create
        :param folder: S3 folder on which put the files (optional)
        """
        s3_folder = folder if folder else self.default_folder
        self.s3_client.upload_file(file_path, self.s3_bucket, s3_folder + key_name)
