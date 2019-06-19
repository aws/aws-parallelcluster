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
# fmt: off
import logging
import sys
from builtins import input

LOGGER = logging.getLogger("pcluster.pcluster")


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
    user_prompt = "{0} [{1}]: ".format(message, default_value or "")

    valid_user_input = False
    result = default_value
    # We give the user the possibility to try again if wrong
    while not valid_user_input:
        sys.stdin.flush()
        user_input = input(user_prompt).strip()
        if user_input == "":
            user_input = default_value
        result = input_to_option(user_input)
        if validator(result):
            valid_user_input = True
        else:
            print("ERROR: {0} is not an acceptable value for {1}".format(user_input, message))
    return result


def _prompt_a_list(message, options, default_value=None):
    """
    Wrap prompt to use it for list.

    :param message: the message to show the user
    :param options: the list of item to show the user
    :param default_value: the default value
    :return: the validate value
    """
    if not options:
        LOGGER.error("ERROR: No options found for {0}".format(message))
        sys.exit(1)
    if not default_value:
        default_value = options[0]

    def input_to_parameter(to_transform):
        try:
            if to_transform.isdigit() and to_transform != "0":
                item = options[int(to_transform) - 1]
            else:
                item = to_transform
        except (ValueError, IndexError):
            item = to_transform
        return item

    return prompt(
        message,
        validator=lambda x: x in options,
        input_to_option=lambda x: input_to_parameter(x),
        default_value=default_value,
        options_to_print=_to_printable_list(options),
    )


def _prompt_a_list_of_tuple(message, options, default_value=None):
    """
    Wrap prompt to use it over a list of tuple.

    The correct item will be the first element of each tuple.
    :param message: the message to show to the user
    :param options: the list of tuple
    :param default_value: the default value
    :return: the validated value
    """
    if not options:
        LOGGER.error("ERROR: No options found for {0}".format(message))
        sys.exit(1)
    if not default_value:
        default_value = options[0][0]

    def input_to_parameter(to_transform):
        try:
            if to_transform.isdigit() and to_transform != "0":
                item = options[int(to_transform) - 1][0]
            else:
                item = to_transform
        except (ValueError, IndexError):
            item = to_transform
        return item

    valid_options = [item[0] for item in options]

    return prompt(
        message,
        validator=lambda x: x in valid_options,
        input_to_option=lambda x: input_to_parameter(x),
        default_value=default_value,
        options_to_print=_to_printable_list(options),
    )


def _to_printable_list(items):
    output = []
    for iterator, item in enumerate(items, start=1):
        if isinstance(item, (list, tuple)):
            output.append("{0}. {1}".format(iterator, " | ".join(item)))
        else:
            output.append("{0}. {1}".format(iterator, item))
    return output
