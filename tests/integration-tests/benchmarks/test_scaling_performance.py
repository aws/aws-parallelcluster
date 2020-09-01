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
import datetime
import logging

import pytest
from assertpy import assert_that
from benchmarks.common.metrics_reporter import (
    enable_asg_metrics,
    produce_benchmark_metrics_report,
    publish_compute_nodes_metric,
)
from benchmarks.common.util import get_instance_vcpus
from remote_command_executor import RemoteCommandExecutor
from time_utils import minutes

from tests.common.assertions import assert_no_errors_in_logs
from tests.common.schedulers_common import get_scheduler_commands


@pytest.mark.schedulers(["slurm", "sge", "torque"])
@pytest.mark.benchmarks
def test_scaling_performance(region, scheduler, os, instance, pcluster_config_reader, clusters_factory, request):
    """The test runs benchmarks for the scaling logic."""
    benchmarks_max_time = request.config.getoption("benchmarks_max_time")

    benchmark_params = {
        "region": region,
        "scheduler": scheduler,
        "os": os,
        "instance": instance,
        "scaling_target": request.config.getoption("benchmarks_target_capacity"),
        "scaledown_idletime": 2,
        "job_duration": 60,
    }

    cluster_config = pcluster_config_reader(
        scaledown_idletime=benchmark_params["scaledown_idletime"], scaling_target=benchmark_params["scaling_target"]
    )
    cluster = clusters_factory(cluster_config)
    remote_command_executor = RemoteCommandExecutor(cluster)
    scheduler_commands = get_scheduler_commands(scheduler, remote_command_executor)

    if cluster.asg:
        enable_asg_metrics(region, cluster)
    logging.info("Starting benchmark with following parameters: %s", benchmark_params)
    start_time = datetime.datetime.utcnow()
    if scheduler == "sge":
        kwargs = {"slots": get_instance_vcpus(region, instance) * benchmark_params["scaling_target"]}
    else:
        kwargs = {"nodes": benchmark_params["scaling_target"]}
    result = scheduler_commands.submit_command("sleep {0}".format(benchmark_params["job_duration"]), **kwargs)
    scheduler_commands.assert_job_submitted(result.stdout)
    compute_nodes_time_series, timestamps, end_time = publish_compute_nodes_metric(
        scheduler_commands,
        max_monitoring_time=minutes(benchmarks_max_time),
        region=region,
        cluster_name=cluster.cfn_name,
    )

    logging.info("Benchmark completed. Producing outputs and performing assertions.")
    benchmark_params["total_time"] = "{0}seconds".format(int((end_time - start_time).total_seconds()))
    produce_benchmark_metrics_report(
        benchmark_params,
        region,
        cluster.cfn_name,
        start_time.replace(tzinfo=datetime.timezone.utc).isoformat(),
        end_time.replace(tzinfo=datetime.timezone.utc).isoformat(),
        benchmark_params["scaling_target"],
        request,
    )
    assert_that(max(compute_nodes_time_series)).is_equal_to(benchmark_params["scaling_target"])
    assert_that(compute_nodes_time_series[-1]).is_equal_to(0)
    assert_no_errors_in_logs(remote_command_executor, scheduler)
