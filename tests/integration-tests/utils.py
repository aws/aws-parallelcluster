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
import logging
import random
import shlex
import string
import subprocess


def retry_if_subprocess_error(exception):
    """Return True if we should retry (in this case when it's a CalledProcessError), False otherwise"""
    return isinstance(exception, subprocess.CalledProcessError)


def run_command(command, capture_output=True, log_error=True):
    """Execute shell command."""
    if isinstance(command, str):
        command = shlex.split(command)
    logging.info("Executing command: " + " ".join(command))
    result = subprocess.run(command, capture_output=capture_output, universal_newlines=True, encoding="utf-8")
    try:
        result.check_returncode()
    except subprocess.CalledProcessError:
        if log_error:
            logging.error(
                "Command {0} failed with error:\n{1}\nand output:\n{2}".format(command, result.stderr, result.stdout)
            )
        raise

    return result


def random_alphanumeric(size=16):
    """Generate a random alphanumeric string."""
    return "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(size))
