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
import json
import os
import time
from typing import List

import untangle
from framework.metrics_publisher import Metric, MetricsPublisher
from junitparser import JUnitXml


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
        timestamp = datetime.datetime.combine(datetime.datetime.utcnow(), datetime.time())
    else:
        timestamp = datetime.datetime.utcnow()
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
