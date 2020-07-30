# Copyright 2019 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
from remote_command_executor import RemoteCommandExecutionError
from retrying import retry
from time_utils import minutes, seconds


@retry(
    retry_on_exception=lambda exception: isinstance(exception, RemoteCommandExecutionError),
    wait_fixed=seconds(30),
    stop_max_delay=minutes(15),
)
def wait_compute_log(remote_command_executor, expected_num_nodes=1):
    """Return list of compute node instance_ids in case of failure."""
    remote_command_executor.run_remote_command("test -d /home/logs/compute", log_error=False)
    output = remote_command_executor.run_remote_command("ls /home/logs/compute/", log_error=False).stdout
    # sample output: "i-049ce596aa69ac988.tar.gz  i-064f07c373d926ba4.tar.gz"
    instance_ids = [instance.replace(".tar.gz", "") for instance in output.split()]
    # make sure we got all the expected failing compute nodes
    if len(instance_ids) != expected_num_nodes:
        raise RemoteCommandExecutionError(result="Not enough nodes in /home/logs/compute/")
    return instance_ids
