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
from retrying import retry

from remote_command_executor import RemoteCommandExecutionError
from time_utils import minutes, seconds


@retry(
    retry_on_exception=lambda exception: isinstance(exception, RemoteCommandExecutionError),
    wait_fixed=seconds(30),
    stop_max_delay=minutes(10),
)
def wait_compute_log(remote_command_executor):
    remote_command_executor.run_remote_command("test -d /home/logs/compute", log_error=False)
    # return instance-id
    return remote_command_executor.run_remote_command(
        "find /home/logs/compute/ -type f -printf '%f\\n' -quit  | head -1 | cut -d. -f1", log_error=False
    ).stdout
