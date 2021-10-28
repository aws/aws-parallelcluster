# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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

import datetime
import re

import boto3
import pytest
from remote_command_executor import RemoteCommandExecutor

from tests.common.osu_common import run_osu_benchmarks
from tests.common.schedulers_common import get_scheduler_commands


def get_infra_stack_outputs(directory_type):
    cfn = boto3.client("cloudformation")
    stack_name = f"MultiUserInfraStack{directory_type}"
    return {
        entry.get("OutputKey"): entry.get("OutputValue")
        for entry in cfn.describe_stacks(StackName=stack_name)["Stacks"][0]["Outputs"]
    }


def get_ad_config_param_vals(directory_type, bucket_name, post_install_script_name):
    """Return a dict used to set values for config file parameters."""
    # TODO: probably do this via a fixture when there's more certainty as to how the
    #       the AD's lifecycle will be managed.
    infra_stack_outputs = get_infra_stack_outputs(directory_type)
    ldap_search_base = ",".join(
        [f"dc={domain_component}" for domain_component in infra_stack_outputs.get("DomainName").split(".")]
    )
    read_only_username = infra_stack_outputs.get("ReadOnlyUserName")
    return {
        "post_install_script_uri": f"s3://{bucket_name}/{post_install_script_name}",
        "ldap_uri": infra_stack_outputs.get("LdapUris").split(",")[0],
        "ldap_search_base": ldap_search_base,
        # TODO: is the CN=Users portion of this a valid assumption?
        "ldap_default_bind_dn": f"CN={read_only_username},CN=Users,{ldap_search_base}",
        "ldap_client_password": infra_stack_outputs.get("Password"),
    }


# @pytest.mark.parametrize("directory_type", ["SimpleAD", "MicrosoftAD", None])
# @pytest.mark.parametrize("directory_type", ["MicrosoftAD"])
@pytest.mark.parametrize("directory_type", ["SimpleAD"])
# @pytest.mark.parametrize("directory_type", [None])
def test_ad_integration(
    region,
    scheduler,
    instance,
    os,
    pcluster_config_reader,
    clusters_factory,
    directory_type,
    test_datadir,
    s3_bucket_factory,
):
    """Verify AD integration works as expected."""
    compute_instance_type_info = {"name": "c5.xlarge", "num_cores": 4}
    config_params = {"compute_instance_type": compute_instance_type_info.get("name")}
    if directory_type:
        post_install_script_name = "all-nodes-ldap.sh"
        bucket_name = s3_bucket_factory()
        bucket = boto3.resource("s3", region_name=region).Bucket(bucket_name)
        bucket.upload_file(str(test_datadir / post_install_script_name), post_install_script_name)
        config_params.update(get_ad_config_param_vals(directory_type, bucket_name, post_install_script_name))
    cluster_config = pcluster_config_reader(**config_params)
    cluster = clusters_factory(cluster_config)

    # Publish compute node count metric every minute via cron job
    # TODO: use metrics reporter from the benchmarks module
    remote_command_executor = RemoteCommandExecutor(cluster)
    metric_publisher_script = "publish_compute_node_count_metric.sh"
    remote_metric_publisher_script_path = f"/shared/{metric_publisher_script}"
    crontab_expression = f"* * * * * {remote_metric_publisher_script_path} &> {remote_metric_publisher_script_path}.log"
    remote_command_executor.run_remote_command(
        f"echo '{crontab_expression}' | crontab -",
        additional_files={str(test_datadir / metric_publisher_script): remote_metric_publisher_script_path},
    )

    # Run all-to-all benchmark across increasingly large number of nodes.
    scheduler_commands = get_scheduler_commands(scheduler, remote_command_executor)
    cloudwatch_client = boto3.client("cloudwatch")
    for benchmark_name in [
        "osu_allgather",
        "osu_allreduce",
        "osu_alltoall",
        "osu_barrier",
        "osu_bcast",
        "osu_gather",
        "osu_reduce",
        "osu_reduce_scatter",
        "osu_scatter",
    ]:
        common_metric_dimensions = {
            "MpiFlavor": "openmpi",
            "BenchmarkGroup": "collective",
            "BenchmarkName": benchmark_name,
            "HeadNodeInstanceType": instance,
            "ComputeInstanceType": compute_instance_type_info.get("name"),
            "ProcessesPerNode": 1,
            "Os": os,
            "DirectoryType": directory_type,
        }
        metric_publishing_timestamp = datetime.datetime.now()
        for num_nodes in [100, 250, 500, 1000, 2000]:
            metric_data = []
            output = run_osu_benchmarks(
                mpi_version=common_metric_dimensions.get("MpiFlavor"),
                benchmark_group=common_metric_dimensions.get("BenchmarkGroup"),
                benchmark_name=common_metric_dimensions.get("BenchmarkName"),
                partition=None,
                remote_command_executor=remote_command_executor,
                scheduler_commands=scheduler_commands,
                num_of_instances=num_nodes,
                slots_per_instance=common_metric_dimensions.get("ProcessesPerNode"),
                test_datadir=test_datadir,
                timeout=120,
            )
            for packet_size, latency in re.findall(r"(\d+)\s+(\d+)\.", output):
                dimensions = {**common_metric_dimensions, "NumNodes": num_nodes, "PacketSize": packet_size}
                metric_data.append(
                    {
                        "MetricName": "Latency",
                        "Dimensions": [{"Name": name, "Value": str(value)} for name, value in dimensions.items()],
                        "Value": int(latency),
                        "Timestamp": metric_publishing_timestamp,
                        "Unit": "Microseconds",
                    }
                )
            cloudwatch_client.put_metric_data(Namespace="ParallelCluster/AdIntegration", MetricData=metric_data)
