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
from datetime import datetime


def fail(error_message):
    """
    Print error message and exit(1)
    :param error_message: message to print
    """
    print(error_message)
    exit(1)


def get_region_by_stack_id(stack_id):
    """
    Parse Cloudformation stack arn and get region
    :param stack_id: something like arn:aws:cloudformation:<region>:<account-id>:stack/<stack-name>/<id>'
    :return: region
    """
    return re.search('arn:aws(\-us\-gov)?:cloudformation:([^:]*).*', stack_id).group(1)


def get_job_definition_name_by_arn(job_definition_arn, version=False):
    """
    Parse Job Definition arn and get name
    :param job_definition_arn: something like arn:aws:batch:<region>:<account-id>:job-definition/<name>:<version>
    :param version: set to true if
    :return: the job definition name
    """
    pattern = r'.*/(.*)' if version else r'.*/(.*):(.*)'
    return re.search(pattern, job_definition_arn).group(1)


def convert_to_date(timestamp):
    """
    Convert timestamp to a readable date
    :param timestamp: timestamp to convert
    :return: the converted date
    """
    return datetime.fromtimestamp(timestamp / 1000).strftime('%Y-%m-%d %H:%M:%S')


def hide_keys(dictionary, keys_to_hide, new_value='xxx'):
    """
    Return a copy of the given dictionary on which specified keys will be replaced by the new_value word (or 'xxx')
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
    Return a shell-quoted version of the input array
    :param array: input array
    :return: the shell-quoted string
    """
    return ' '.join(pipes.quote(arg) for arg in array)


def is_job_array(job):
    """
    Check if the given job is an array
    :param job: the job dictionary returned by AWS Batch api
    :return: true if the job is an array, false otherwise
    """
    return 'arrayProperties' in job and 'size' in job['arrayProperties']

