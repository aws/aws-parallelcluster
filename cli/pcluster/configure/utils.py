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

LOGGER = logging.getLogger(__name__)
unsupported_regions = ["ap-northeast-3"]


def handle_client_exception(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except (BotoCoreError, ClientError) as e:
            LOGGER.error("Failed with error: %s" % e)
            LOGGER.error("Hint: please check your AWS credentials.")
            LOGGER.error("Run `aws configure` or set the credentials as environment variables.")
            sys.exit(1)

    return wrapper


def get_default_suggestion(parameter, options):
    """
    Provide default values for parameters without one defined in the config file.

    Note that options is assumed to be a list, tuple, or None.
    """
    # For these parameters, steer users towards a default value rather than selecting the first
    # from the available set of options.
    opinionated_suggestions = {
        "Scheduler": "slurm",
        "Operating System": "alinux2",
    }

    if parameter in opinionated_suggestions:
        default = opinionated_suggestions.get(parameter)
    elif isinstance(options, (list, tuple)) and isinstance(options[0], (list, tuple)):
        default = options[0][0]
    elif isinstance(options, (list, tuple)):
        default = options[0]
    else:
        default = ""
    return default


def prompt(message, validator=lambda x: True, input_to_option=lambda x: x, default_value=None, options_to_print=None):
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
    :param options: the list of tuple
    :param default_value: the default value
    :return: the validated value
    """
    if not options:
        LOGGER.error("ERROR: No options found for {0}".format(message))
        sys.exit(1)
    is_tuple = isinstance(options[0], (list, tuple))

    if default_value is None:
        default_value = get_default_suggestion(message, options)

    def input_to_parameter(user_input):
        try:
            if user_input.isdigit() and user_input != "0":
                option_value = options[int(user_input) - 1][0] if is_tuple else options[int(user_input) - 1]
            else:
                option_value = user_input
        except (ValueError, IndexError):
            option_value = user_input
        return option_value

    if is_tuple:
        valid_options = [item[0] for item in options]
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
        if isinstance(item, (list, tuple)):
            output.append("{0}. {1}".format(iterator, " | ".join(item)))
        else:
            output.append("{0}. {1}".format(iterator, item))
    return output


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
