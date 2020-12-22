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
from utils import random_alphanumeric


def verify_directory_correctly_shared(remote_command_executor, mount_dir, scheduler_commands):
    head_node_file = random_alphanumeric()
    compute_file = random_alphanumeric()
    remote_command_executor.run_remote_command(
        "touch {mount_dir}/{head_node_file}".format(mount_dir=mount_dir, head_node_file=head_node_file)
    )
    job_command = "cat {mount_dir}/{head_node_file} && touch {mount_dir}/{compute_file}".format(
        mount_dir=mount_dir, head_node_file=head_node_file, compute_file=compute_file
    )

    result = scheduler_commands.submit_command(job_command)
    job_id = scheduler_commands.assert_job_submitted(result.stdout)
    scheduler_commands.wait_job_completed(job_id)
    scheduler_commands.assert_job_succeeded(job_id)
    remote_command_executor.run_remote_command(
        "cat {mount_dir}/{compute_file}".format(mount_dir=mount_dir, compute_file=compute_file)
    )
