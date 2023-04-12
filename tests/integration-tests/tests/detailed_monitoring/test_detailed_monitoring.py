# Copyright 2020 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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

import boto3
import pytest
from assertpy import assert_that


@pytest.mark.usefixtures("instance", "os", "scheduler")
@pytest.mark.parametrize("detailed_monitoring_enabled", [True, False])
def test_detailed_monitoring(
    detailed_monitoring_enabled,
    region,
    pcluster_config_reader,
    clusters_factory,
    test_datadir,
):
    cluster_config = pcluster_config_reader(detailed_monitoring_enabled=str(detailed_monitoring_enabled).lower())
    cluster = clusters_factory(cluster_config)
    ec2_clinet = boto3.client("ec2", region_name=region)
    compute_instance_ids = cluster.get_cluster_instance_ids(node_type="Compute")
    assert_that(compute_instance_ids).is_not_empty()

    ec2_response = ec2_clinet.describe_instances(InstanceIds=compute_instance_ids)
    monitoring_states = [
        instance.get('Monitoring').get('State')
        for reservation in ec2_response.get("Reservations")
        for instance in reservation.get("Instances")
    ]
    assert_that(monitoring_states).is_not_empty()
    assert_that(set(monitoring_states)).is_length(1)
    assert_that(monitoring_states[0]).is_equal_to("enabled" if detailed_monitoring_enabled else "disabled")
