# Copyright 2013-2018 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the 'License'). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the 'LICENSE.txt' file accompanying this file. This file is distributed on an 'AS IS' BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
import functools
import logging
import sys
from builtins import input

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from tabulate import tabulate

LOGGER = logging.getLogger(__name__)
unsupported_regions = ["ap-northeast-3"]


def handle_client_exception(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except (BotoCoreError, ClientError) as e:
            LOGGER.error("Failed with error: %s" % e)
            if isinstance(e, ClientError) and "credentials" in str(e):
                LOGGER.error("To set the credentials, run 'aws configure' or set them as environment variables")

    return wrapper


def get_default_suggestion(parameter, options):
    """
    Provide default values for parameters without one defined in the config file.

    Note that options is assumed to be a list, tuple, or None.
    """
    # For these parameters, steer users towards a default value rather than selecting the first
    # from the available set of options.
    opinionated_suggestions = {"Scheduler": "slurm", "Operating System": "alinux2"}

    if parameter in opinionated_suggestions:
        default = opinionated_suggestions.get(parameter)
    elif isinstance(options, (list, tuple)):
        default = options[0]["id"] if isinstance(options[0], dict) else options[0]
    else:
        default = ""
    return default


def prompt(
    message,
    validator=lambda x: True,
    input_to_option=lambda x: x,
    default_value=None,
    options_to_print=None,
    table_header=None,
):
    """
    Prompt the user a message with optionally some options.

    :param message: the message to show to the user
    :param validator: a function that predicates if the input is correct
    :param input_to_option: a function that given the input transforms it in something else
    :param default_value: the value to return as the default if the user doesn't insert anything
    :param options_to_print: the options to print if necessary
    :return: the value inserted by the user validated
    """
    if options_to_print:
        print("Allowed values for {0}:".format(message))
        if table_header:
            print(tabulate(options_to_print, table_header))
        else:
            for item in options_to_print:
                print(item)
    user_prompt = "{0} [{1}]: ".format(
        message, default_value if default_value is not None else get_default_suggestion(message, options_to_print)
    )

    valid_user_input = False
    result = default_value
    # Give the user the possibility to try again if wrong
    while not valid_user_input:
        user_input = input(user_prompt).strip() or default_value
        result = input_to_option(user_input)
        if validator(result):
            valid_user_input = True
        else:
            print("ERROR: {0} is not an acceptable value for {1}".format(user_input, message))
    return result


def prompt_iterable(message, options, default_value=None):
    """
    Wrap prompt to use it over a list or a list of tuple.

    The selected option will be the first element of the selected tuple.
    :param message: the message to show to the user
    :param options: a list of strings or dicts. dicts must have id as one of the keys
    :param default_value: the default value
    :return: the validated value
    """
    if not options:
        LOGGER.error("ERROR: No options found for {0}".format(message))
        sys.exit(1)
    is_dict = isinstance(options[0], dict)
    valid_options = [option["id"] for option in options] if is_dict else options
    if default_value not in valid_options:
        # If default value is not allowed, change default value to the first item of the options
        default_value = get_default_suggestion(message, valid_options)

    def input_to_parameter(user_input):
        try:
            if user_input.isdigit() and user_input != "0":
                option_value = options[int(user_input) - 1]["id"] if is_dict else options[int(user_input) - 1]
            else:
                option_value = user_input
        except (ValueError, IndexError):
            option_value = user_input
        return option_value

    if is_dict:
        valid_options = [item["id"] for item in options]
        rows, header = get_rows_and_header(options)
        return prompt(
            message,
            validator=lambda x: x in valid_options,
            input_to_option=lambda x: input_to_parameter(x),
            default_value=default_value,
            options_to_print=rows,
            table_header=header,
        )
    else:
        valid_options = options
        return prompt(
            message,
            validator=lambda x: x in valid_options,
            input_to_option=lambda x: input_to_parameter(x),
            default_value=default_value,
            options_to_print=generate_printable_list(options),
        )


def generate_printable_list(items):
    output = []
    for iterator, item in enumerate(items, start=1):
        output.append("{0}. {1}".format(iterator, item))
    return output


def get_rows_and_header(items):
    """
     Return rows and header to print using tabulate.

     :param items: list of dicts
     :return: rows are all values in items. header is keys of dict

     Example:
     If items is a list of vpc dicts:
     [
         {"id":vpc-id1, "name":name1, "number_of_subnets": 6},
         {"id":vpc-id2, "name":name2, "number_of_subnets": 1}
         {"id":vpc-id3, "name":name2, "number_of_subnets": 2}
     ]
     Return is:
      (
         [
             [1, vpc-id1, name1, 6],
             [2, vpc-id2, name2, 1],
             [3, vpc-id3, name3, 2]
         ],
         ["#", "id", "name", "number_of_subnets"]
      )
     Finally, tabulate(rows header) prints:
      #  id         name       number_of_subnets
    ---  --------  ---------  -------------------
      1  vpc-id1    name1                    6
      2  vpc-id2    name2                    1
      3  vpc-id3    name3                    2
    """
    header = list(items[0].keys())
    header.insert(0, "#")
    rows = []
    for iterator, item in enumerate(items, start=1):
        row = list(item.values())
        row.insert(0, str(iterator))
        rows.append(row)
    return rows, header


@handle_client_exception
def get_regions():
    ec2 = boto3.client("ec2")
    regions = ec2.describe_regions().get("Regions")
    regions = [region.get("RegionName") for region in regions if region.get("RegionName") not in unsupported_regions]
    regions.sort()
    return regions


def get_resource_tag(resource, tag_name):
    tags = resource.get("Tags", [])
    return next((item.get("Value") for item in tags if item.get("Key") == tag_name), None)
