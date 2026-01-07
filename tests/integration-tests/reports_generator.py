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
import ast
import datetime
import json
import os
import time
from collections import defaultdict
from typing import List

import boto3
import matplotlib.pyplot as plt
import pandas as pd
import untangle
from framework.metrics_publisher import Metric, MetricsPublisher
from junitparser import JUnitXml

from pcluster.constants import SUPPORTED_OSES

SECONDS_PER_YEAR = 365 * 24 * 60 * 60


def generate_cw_report(test_results_dir, namespace, aws_region, timestamp_day_start=False, start_timestamp=None):
    """
    Publish tests results to CloudWatch
    :param test_results_dir: dir containing the tests outputs.
    :param namespace: namespace for the CW metric.
    :param aws_region: region where to push the metric.
    :param timestamp_day_start: timestamp of the CW metric equal to the start of the current day (midnight).
    :param start_timestamp: timestamp value to use instead of generating one
    """
    test_report_file = os.path.join(test_results_dir, "test_report.xml")
    if not os.path.isfile(test_report_file):
        generate_junitxml_merged_report(test_results_dir)
    report = generate_json_report(test_results_dir=test_results_dir, save_to_file=False)
    metric_pub = MetricsPublisher(region=aws_region)

    if start_timestamp is not None:
        timestamp = datetime.datetime.fromtimestamp(start_timestamp)
    elif timestamp_day_start:
        timestamp = datetime.datetime.combine(datetime.datetime.now(datetime.timezone.utc), datetime.time())
    else:
        timestamp = datetime.datetime.now(datetime.timezone.utc)
    for category, dictionary in report.items():
        if category == "all":
            _put_metrics(metric_pub, namespace, dictionary, [], timestamp)
        else:
            for dimension, metrics in dictionary.items():
                dimensions = [{"Name": category, "Value": dimension}]
                _put_metrics(metric_pub, namespace, metrics, dimensions, timestamp)


def generate_junitxml_merged_report(test_results_dir):
    """
    Merge all junitxml generated reports in a single one.
    :param test_results_dir: output dir containing the junitxml reports to merge.
    """
    merged_xml = JUnitXml()
    for dir, _, files in os.walk(test_results_dir):
        for file in files:
            if file.endswith("results.xml"):
                merged_xml += JUnitXml.fromfile(os.path.join(dir, file))

    merged_xml.write("{0}/test_report.xml".format(test_results_dir), pretty=True)


def generate_json_report(test_results_dir, save_to_file=True):
    """
    Generate a json report containing a summary of the tests results with details
    for each dimension.
    :param test_results_dir: dir containing the tests outputs.
    :param save_to_file:  True to save to file
    :return: a dictionary containing the computed report.
    """
    test_report_file = os.path.join(test_results_dir, "test_report.xml")
    if not os.path.isfile(test_report_file):
        generate_junitxml_merged_report(test_results_dir)

    result_to_label_mapping = {"skipped": "skipped", "failure": "failures", "error": "errors"}
    results = {"all": _empty_results_dict()}
    xml = untangle.parse(test_report_file)
    for testsuite in xml.testsuites.children:
        for testcase in testsuite.children:
            label = "succeeded"
            for key, value in result_to_label_mapping.items():
                if hasattr(testcase, key):
                    label = value
                    break
            results["all"][label] += 1
            results["all"]["total"] += 1

            if hasattr(testcase, "properties"):
                for property in testcase.properties.children:
                    if property["name"] not in ["region", "os", "instance", "scheduler", "feature"]:
                        continue
                    _record_result(results, property["name"], property["value"], label)

    if save_to_file:
        with open("{0}/test_report.json".format(test_results_dir), "w", encoding="utf-8") as out_f:
            out_f.write(json.dumps(results, indent=4))

    return results


def _record_result(results_dict, dimension, dimension_value, label):
    if dimension not in results_dict:
        results_dict[dimension] = {}
    if dimension_value not in results_dict[dimension]:
        results_dict[dimension].update({dimension_value: _empty_results_dict()})
    results_dict[dimension][dimension_value][label] += 1
    results_dict[dimension][dimension_value]["total"] += 1


def _empty_results_dict():
    return {"total": 0, "skipped": 0, "failures": 0, "errors": 0, "succeeded": 0}


def _put_metrics(
    metric_publisher: MetricsPublisher,
    namespace: str,
    metrics: dict[str, int],
    dimensions: List[dict[str, str]],
    timestamp,
):
    # CloudWatch PutMetric API has a TPS of 150. Setting a rate of 60 metrics per second
    put_metric_sleep_interval = 1.0 / 60
    for key, value in metrics.items():
        metric_publisher.publish_metrics_to_cloudwatch(
            namespace,
            [Metric(key, value, "Count", dimensions)],
        )
        time.sleep(put_metric_sleep_interval)

    failures_errors = metrics["failures"] + metrics["errors"]
    failure_rate = float(failures_errors) / metrics["total"] * 100 if metrics["total"] > 0 else 0
    additional_metrics = [
        {"name": "failures_errors", "value": failures_errors, "unit": "Count"},
        {"name": "failure_rate", "value": failure_rate, "unit": "Percent"},
    ]
    for item in additional_metrics:
        metric_publisher.publish_metrics_to_cloudwatch(
            namespace,
            [Metric(item["name"], item["value"], item["unit"], dimensions, timestamp)],
        )
        time.sleep(put_metric_sleep_interval)


def _scan_dynamodb_table(
    table_name, projection_expression, expression_attribute_names, filter_expression, expression_attribute_values
):
    """Scan a DynamoDB table with pagination and return all items."""
    dynamodb_client = boto3.client("dynamodb", region_name="us-east-1")
    all_items = []
    last_evaluated_key = None
    while True:
        scan_params = {
            "TableName": table_name,
            "ProjectionExpression": projection_expression,
            "FilterExpression": filter_expression,
            "ExpressionAttributeNames": expression_attribute_names,
            "ExpressionAttributeValues": expression_attribute_values,
        }

        # Add ExclusiveStartKey if we're not on the first iteration
        if last_evaluated_key:
            scan_params["ExclusiveStartKey"] = last_evaluated_key

        response = dynamodb_client.scan(**scan_params)
        all_items.extend(response.get("Items", []))

        # Check if there are more items to fetch
        last_evaluated_key = response.get("LastEvaluatedKey")
        if not last_evaluated_key:
            break
    return all_items


def generate_launch_time_report(reports_output_dir):
    current_time = int(time.time())
    one_year_ago = current_time - SECONDS_PER_YEAR

    all_items = _scan_dynamodb_table(
        table_name="ParallelCluster-IntegTest-Metadata",
        projection_expression="#status, #avg_launch, #max_launch, #min_launch, #creation_time, #name, #os, #start_time",
        expression_attribute_names={
            "#call_start_time": "call_start_time",
            "#status": "call_status",
            "#avg_launch": "compute_average_launch_time",
            "#max_launch": "compute_max_launch_time",
            "#min_launch": "compute_min_launch_time",
            "#creation_time": "cluster_creation_time",
            "#name": "name",
            "#os": "os",
            "#start_time": "call_start_time",
        },
        filter_expression="#call_start_time >= :one_year_ago",
        expression_attribute_values={":one_year_ago": {"N": str(one_year_ago)}},
    )
    all_items.sort(key=lambda x: x["call_start_time"]["N"], reverse=True)
    for category_name in ["os", "name"]:
        # Analyze the data by os and by name.
        # Therefore, we can see which os is taking long, or which test is taking long.
        category_name_processing = None
        if category_name == "name":
            category_name_processing = _remove_os_from_string
        for statistics_name in [
            "cluster_creation_time",
            "compute_average_launch_time",
            "compute_min_launch_time",
            "compute_max_launch_time",
        ]:
            if statistics_name in ["cluster_creation_time", "compute_average_launch_time"]:
                statistics_processing = _mean
            elif statistics_name in ["compute_max_launch_time"]:
                statistics_processing = max
            else:
                statistics_processing = min
            result = _get_statistics_by_category(
                all_items,
                category_name,
                statistics_name,
                category_name_processing=category_name_processing,
                statistics_processing=statistics_processing,
            )
            create_report(result, [statistics_name, category_name], reports_output_dir)


def generate_performance_report(reports_output_dir):
    current_time = int(time.time())
    one_year_ago = current_time - SECONDS_PER_YEAR

    all_items = _scan_dynamodb_table(
        table_name="ParallelCluster-PerformanceTest-Metadata",
        projection_expression="#instance, #name, #os, #result, #timestamp, #mpi_variation, #num_instances",
        expression_attribute_names={
            "#instance": "instance",
            "#name": "name",
            "#os": "os",
            "#result": "result",
            "#timestamp": "timestamp",
            "#mpi_variation": "mpi_variation",
            "#num_instances": "num_instances",
        },
        filter_expression="#timestamp >= :one_year_ago",
        expression_attribute_values={":one_year_ago": {"N": str(one_year_ago)}},
    )
    all_items.sort(key=lambda x: x["timestamp"]["N"], reverse=True)
    items_by_name = defaultdict(list)
    category_names = [("name", "S"), ("mpi_variation", "S"), ("num_instances", "N")]
    for item in all_items:
        keys = []
        for category_name, value_type in category_names:
            keys += [item.get(category_name, {}).get(value_type, "")]
        key = "_".join(keys)
        items_by_name[key].append(item)
    result = defaultdict(dict)
    for name, items in items_by_name.items():
        result[name] = _get_statistics_from_result(items, name, reports_output_dir)


def _append_performance_data(target_dict, os_key, performance, timestamp):
    os_time_key = f"{os_key}-time"
    if os_key not in target_dict:
        target_dict[os_key] = []
        target_dict[os_time_key] = []
    target_dict[os_key].append(float(performance))
    target_dict[os_time_key].append(datetime.datetime.fromtimestamp(int(timestamp)).strftime("%Y-%m-%d %H:%M:%S"))


def _get_statistics_from_result(all_items, name, reports_output_dir):
    result = {}
    result_with_single_layer = {}
    for item in all_items:
        this_result = ast.literal_eval(item["result"]["S"])
        # The result can contain different format because we historical development of the test data collection.
        # 1. The result can be empty or empty list because testing didn't successfully push data in the initial coding.
        # 2. The result can be a list of tuples or a dictionary. For example, the following result shows OSU latency
        # number of corresponding to different packet sizes
        # [('0', '16'), ('1', '16'), ('2', '16'), ... , ('4194304', '1368')]
        # 3. The result can be a single number.
        # For example, OSU barrier test returns a single number without any consideration of packet sizes.
        # The following logic handles all the differences
        if not this_result:
            continue
        os_key = item["os"]["S"]
        timestamp = item["timestamp"]["N"]
        if isinstance(this_result, (dict, list)):
            for key, performance in this_result:
                if key not in result:
                    result[key] = {}
                _append_performance_data(result[key], os_key, performance, timestamp)
        else:
            _append_performance_data(result_with_single_layer, os_key, this_result, timestamp)
    for key, node_num_result in result.items():
        create_report(node_num_result, [name, key], reports_output_dir)
    if result_with_single_layer:
        create_report(result_with_single_layer, [name], reports_output_dir)
    return result


def _mean(x):
    return sum(x) / len(x)


def _remove_os_from_string(x):
    for os_key in SUPPORTED_OSES:
        x = x.replace(os_key, "")
    return x


def _get_statistics_by_category(  # noqa C901
    all_items, category_name, statistics_name, category_name_processing=None, statistics_processing=None
):
    # This function is used to get "cluster_creation_time", "compute_average_launch_time",
    # "compute_min_launch_time", and "compute_max_launch_time",
    # This function uses a window of the number of operating systems,
    # so that the statistics are more stable when os rotation is in place.
    more_data = True
    latest_time = float(all_items[0]["call_start_time"]["N"])
    window_length = len(SUPPORTED_OSES)
    result = {}
    while more_data:
        more_data = False
        os_cluster_creation_times = {}
        for item in all_items:
            if item["call_status"]["S"] != "passed":
                continue
            if statistics_name not in item:
                continue
            if float(item["call_start_time"]["N"]) < latest_time - (window_length * 24 * 60 * 60):
                more_data = True
                continue
            if float(item["call_start_time"]["N"]) > latest_time:
                continue
            cluster_creation_time = item[statistics_name]["N"]
            if cluster_creation_time == "0":
                continue
            os_key = item[category_name]["S"]
            if category_name_processing:
                os_key = category_name_processing(os_key)
            if os_key not in os_cluster_creation_times:
                os_cluster_creation_times[os_key] = [float(cluster_creation_time)]
            else:
                os_cluster_creation_times[os_key].append(float(cluster_creation_time))
        for os_key, cluster_creation_times in os_cluster_creation_times.items():
            if os_key not in result:
                result[os_key] = []
            os_time_key = f"{os_key}-time"
            if os_time_key not in result:
                result[os_time_key] = []
            result[os_key].insert(0, sum(cluster_creation_times) / len(cluster_creation_times))
            result[os_time_key].insert(0, datetime.datetime.fromtimestamp(latest_time).strftime("%Y-%m-%d"))
        if os_cluster_creation_times:
            more_data = True
        latest_time = latest_time - 24 * 60 * 60

    return result


def plot_statistics(result, name_prefix):
    plt.figure(figsize=(40, 12))

    # Collect and sort all unique time points
    all_times = set()
    for category, values in result.items():
        if "-time" in category:
            all_times.update(values)
    sorted_times = sorted(all_times)
    time_to_index = {time: i for i, time in enumerate(sorted_times)}

    # Plot each category using numeric x positions
    for category, values in result.items():
        if "-time" in category:
            continue
        x_values = result[f"{category}-time"]
        x_positions = [time_to_index[time] for time in x_values]
        plt.plot(x_positions, values, marker="o", label=category)

    plt.title(f"{name_prefix}")
    plt.xlabel("Latest timestamp")
    plt.ylabel("Value")
    plt.grid(True, linestyle="--", alpha=0.7)
    plt.legend()
    plt.xticks(range(len(sorted_times)), sorted_times, rotation=45)
    plt.tight_layout()
    plt.show()


def create_excel_files(result, name_prefix, reports_output_dir):
    # Collect and sort all unique time points
    filename = os.path.join(reports_output_dir, f"{name_prefix}_statistics.xlsx")
    print(f"Creating Excel file: {filename}...")
    all_times = set()
    for category, values in result.items():
        if "-time" in category:
            all_times.update(values)
    sorted_times = sorted(all_times)

    df_data = {}

    # Add each category as a column
    for category, values in result.items():
        if "-time" in category:
            continue
        x_values = result[f"{category}-time"]
        # Create series and aggregate duplicates by taking the mean
        category_series = pd.Series(index=x_values, data=values).groupby(level=0).mean()
        df_data[category] = category_series.reindex(sorted_times)

    df = pd.DataFrame(df_data)

    # Write to Excel
    with pd.ExcelWriter(filename, engine="openpyxl") as writer:
        df.T.to_excel(writer, index=True)

    print(f"Excel file saved: {filename}")


def _get_launch_time(logs, instance_id):
    for log in logs:
        if instance_id in log["message"]:
            return log["timestamp"]


def create_report(result, labels, reports_output_dir, create_graphs=False, create_excel=True):
    name_prefix = "_".join(map(str, labels))
    if create_excel:
        create_excel_files(result, name_prefix, reports_output_dir)
    if create_graphs:
        plot_statistics(result, name_prefix)
