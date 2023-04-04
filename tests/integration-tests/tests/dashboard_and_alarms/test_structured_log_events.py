# Copyright 2023 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License").
# You may not use this file except in compliance with the
# License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.

import boto3
import pytest
from remote_command_executor import RemoteCommandExecutor
from utils import test_cluster_health_metric

from tests.dashboard_and_alarms.structured_log_event_utils import assert_that_event_exists


@pytest.mark.usefixtures("instance", "os", "scheduler")
def test_custom_compute_action_failure(
    region,
    pcluster_config_reader,
    clusters_factory,
    test_datadir,
    s3_bucket_factory,
    scheduler_commands_factory,
):
    # Create S3 bucket for pre-install scripts
    bucket_name = s3_bucket_factory()

    bucket = boto3.resource("s3", region_name=region).Bucket(bucket_name)
    bad_script = "on_compute_configured_error.sh"
    bad_script_path = f"test_metric_logging/{bad_script}"
    bucket.upload_file(str(test_datadir / bad_script), bad_script_path)

    # Create S3 bucket for pre-install scripts
    cluster_config = pcluster_config_reader(bucket=bucket_name, bad_script_path=bad_script_path)
    cluster = clusters_factory(cluster_config)

    remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = scheduler_commands_factory(remote_command_executor)

    scheduler_commands.submit_command("hostname", nodes=1)
    assert_that_event_exists(cluster, r".+\.clustermgtd_events", "invalid-backing-instance-count")
    assert_that_event_exists(cluster, r".+\.clustermgtd_events", "protected-mode-error-count")
    assert_that_event_exists(cluster, r".+\.bootstrap_error_msg", "custom-action-error")

    test_cluster_health_metric(["OnNodeConfiguredRunErrors"], cluster.name, region)
