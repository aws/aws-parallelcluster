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
import os
import pathlib
from time import sleep

import boto3
from jinja2 import FileSystemLoader
from jinja2.sandbox import SandboxedEnvironment
from retrying import RetryError, retry
from time_utils import seconds
from utils import describe_cluster_instances

METRIC_WIDGET_TEMPLATE = """
    {{
        "metrics": [
            [ "ParallelCluster/benchmarking/{cluster_name}", "ComputeNodesCount", {{ "stat": "Maximum", "label": \
"ComputeNodesCount Max" }} ],
            [ "...", {{ "stat": "Minimum", "label": "ComputeNodesCount Min" }} ],
            [ "ParallelCluster/benchmarking/{cluster_name}", "EC2NodesCount", {{ "stat": "Maximum", "label": \
"EC2NodesCount Max" }} ],
            [ "...", {{ "stat": "Minimum", "label": "EC2NodesCount Min" }} ]
        ],
        "view": "timeSeries",
        "stacked": false,
        "stat": "Maximum",
        "period": 1,
        "title": "{title}",
        "width": 1400,
        "height": 700,
        "start": "{graph_start_time}",
        "end": "{graph_end_time}",
        "annotations": {{
            "horizontal": [
                {{
                    "label": "Scaling Target",
                    "value": {scaling_target}
                }}
            ],
            "vertical": [
                {{
                    "label": "Start Time",
                    "value": "{start_time}"
                }},
                {{
                    "label": "End Time",
                    "value": "{end_time}"
                }}
            ]
        }},
        "yAxis": {{
            "left": {{
                "showUnits": false,
                "label": "Count"
            }},
            "right": {{
                "showUnits": true
            }}
        }}
    }}"""


def publish_compute_nodes_metric(scheduler_commands, max_monitoring_time, region, cluster_name):
    logging.info("Monitoring scheduler status and publishing metrics")
    cw_client = boto3.client("cloudwatch", region_name=region)
    compute_nodes_time_series = []
    ec2_nodes_time_series = []
    timestamps = [datetime.datetime.utcnow()]

    @retry(
        # Retry until EC2 and Scheduler capacities scale down to 0
        # Also make sure cluster scaled up before scaling down
        retry_on_result=lambda _: ec2_nodes_time_series[-1] != 0
        or compute_nodes_time_series[-1] != 0
        or max(ec2_nodes_time_series) == 0
        or max(compute_nodes_time_series) == 0,
        wait_fixed=seconds(20),
        stop_max_delay=max_monitoring_time,
    )
    def _watch_compute_nodes_allocation():
        try:
            compute_nodes = scheduler_commands.compute_nodes_count()
            logging.info("Publishing scheduler compute metric: count={0}".format(compute_nodes))
            cw_client.put_metric_data(
                Namespace="ParallelCluster/benchmarking/{cluster_name}".format(cluster_name=cluster_name),
                MetricData=[{"MetricName": "ComputeNodesCount", "Value": compute_nodes, "Unit": "Count"}],
            )
            ec2_instances_count = len(describe_cluster_instances(cluster_name, region, filter_by_node_type="Compute"))
            logging.info("Publishing EC2 compute metric: count={0}".format(ec2_instances_count))
            cw_client.put_metric_data(
                Namespace="ParallelCluster/benchmarking/{cluster_name}".format(cluster_name=cluster_name),
                MetricData=[{"MetricName": "EC2NodesCount", "Value": ec2_instances_count, "Unit": "Count"}],
            )
            # add values only if there is a transition.
            if (
                len(ec2_nodes_time_series) == 0
                or ec2_nodes_time_series[-1] != ec2_instances_count
                or compute_nodes_time_series[-1] != compute_nodes
            ):
                ec2_nodes_time_series.append(ec2_instances_count)
                compute_nodes_time_series.append(compute_nodes)
                timestamps.append(datetime.datetime.utcnow())
        except Exception as e:
            logging.warning("Failed while watching nodes allocation with exception: %s", e)
            raise

    try:
        _watch_compute_nodes_allocation()
    except RetryError:
        # ignoring this error in order to perform assertions on the collected data.
        pass

    end_time = datetime.datetime.utcnow()
    logging.info(
        "Monitoring completed: compute_nodes_time_series [ %s ], timestamps [ %s ]",
        " ".join(map(str, compute_nodes_time_series)),
        " ".join(map(str, timestamps)),
    )
    logging.info("Sleeping for 3 minutes to wait for the metrics to propagate...")
    sleep(180)

    return compute_nodes_time_series, timestamps, end_time


def generate_metric_widget(**kwargs):
    config_dir = pathlib.Path(__file__).parent
    file_loader = FileSystemLoader(config_dir)
    env = SandboxedEnvironment(loader=file_loader)
    return env.get_template("scaling_metrics_source.jinja").render(**kwargs)


def produce_benchmark_metrics_report(
    title, region, cluster_name, start_time, end_time, scaling_target, request, scaling_target_time=None
):
    graph_start_time = start_time - datetime.timedelta(minutes=2)
    graph_end_time = end_time + datetime.timedelta(minutes=2)
    widget_metric = generate_metric_widget(
        cluster_name=cluster_name,
        start_time=start_time.isoformat(),
        end_time=end_time.isoformat(),
        title=title,
        graph_start_time=graph_start_time.isoformat(),
        graph_end_time=graph_end_time.isoformat(),
        scaling_target=scaling_target,
        scaling_target_time=scaling_target_time.isoformat() if scaling_target_time else "",
    )
    logging.info(widget_metric)
    cw_client = boto3.client("cloudwatch", region_name=region)
    response = cw_client.get_metric_widget_image(MetricWidget=widget_metric)
    _write_results_to_outdir(request, response["MetricWidgetImage"], image_name_prefix=f"{scaling_target}-nodes")


def _to_datetime(timestamp):
    return datetime.datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%S.%f%z")


def _write_results_to_outdir(request, image_bytes, image_name_prefix):
    out_dir = request.config.getoption("output_dir")
    os.makedirs("{out_dir}/benchmarks".format(out_dir=out_dir), exist_ok=True)
    graph_dst = "{out_dir}/benchmarks/{test_name}-{image_name_prefix}.png".format(
        out_dir=out_dir,
        test_name=os.path.basename(request.node.nodeid.replace("::", "-")),
        image_name_prefix=image_name_prefix,
    )
    with open(graph_dst, "wb") as image:
        image.write(image_bytes)
