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
import threading
from concurrent.futures.thread import ThreadPoolExecutor

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
def test_scheduler_performance(region, scheduler, os, instance, pcluster_config_reader, clusters_factory, request):
    """The test runs a stress test to verify scheduler behaviour with many submitted jobs."""
    benchmarks_max_time = request.config.getoption("benchmarks_max_time")
    instance_slots = get_instance_vcpus(region, instance)

    benchmark_params = {
        "region": region,
        "scheduler": scheduler,
        "os": os,
        "instance": instance,
        "scaling_target": request.config.getoption("benchmarks_target_capacity"),
        "scaledown_idletime": 2,
        "job_duration": 60,
        "jobs_to_submit": 2 * instance_slots * request.config.getoption("benchmarks_target_capacity"),
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
    _submit_jobs(benchmark_params, scheduler_commands, instance_slots, cluster)
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
        cluster.asg,
        start_time.replace(tzinfo=datetime.timezone.utc).isoformat(),
        end_time.replace(tzinfo=datetime.timezone.utc).isoformat(),
        benchmark_params["scaling_target"],
        request,
    )
    assert_that(max(compute_nodes_time_series)).is_equal_to(benchmark_params["scaling_target"])
    assert_that(compute_nodes_time_series[-1]).is_equal_to(0)
    _assert_jobs_completed(remote_command_executor, benchmark_params["jobs_to_submit"])
    assert_no_errors_in_logs(remote_command_executor, scheduler)


def _submit_jobs(benchmark_params, scheduler_commands, instance_slots, cluster):
    """
    Submit 1 job to make the cluster scale to scaling_target and then a series of very small jobs
    to test scheduler performance.
    """
    if benchmark_params["scheduler"] == "sge":
        kwargs = {"slots": instance_slots * benchmark_params["scaling_target"]}
    else:
        kwargs = {"nodes": benchmark_params["scaling_target"]}
    result = scheduler_commands.submit_command("sleep 1", **kwargs)
    job_id = scheduler_commands.assert_job_submitted(result.stdout)

    with ThreadPoolExecutor(max_workers=10) as executor:
        # allows to keep thread local data that gets reused for all tasks executed by the thread
        local_data = threading.local()

        def _submit_one_slot_job():
            if not hasattr(local_data, "scheduler_commands"):
                local_data.scheduler_commands = get_scheduler_commands(
                    benchmark_params["scheduler"], RemoteCommandExecutor(cluster)
                )
            local_data.scheduler_commands.submit_command(
                "sleep {0}; mkdir -p /shared/job-results; mktemp /shared/job-results/job.XXXXXXXX".format(
                    benchmark_params["job_duration"]
                ),
                slots=1,
                after_ok=job_id,
            )

        for _ in range(0, benchmark_params["jobs_to_submit"]):
            executor.submit(_submit_one_slot_job)


def _assert_jobs_completed(remote_command_executor, expected_completed_jobs_count):
    result = remote_command_executor.run_remote_command("ls /shared/job-results | wc -l")
    completed_jobs_count = int(result.stdout.strip())
    assert_that(completed_jobs_count).is_equal_to(expected_completed_jobs_count)
