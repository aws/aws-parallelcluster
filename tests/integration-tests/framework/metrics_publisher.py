#  Copyright 2024 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
#  with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
#  or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
#  OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
#  limitations under the License.

import logging
from dataclasses import dataclass
from typing import List

import boto3
import botocore.exceptions


@dataclass
class Metric:
    """Data Class representing a CloudWatch Metric."""

    name: str
    value: float
    unit: str
    dimensions: List[dict[str, str]] = None
    timestamp: str = None

    def generate_metric_data_entry(self):
        """Returns a Metric Data dictionary used when describing a CloudWatch Metric Data item."""
        metric_data_entry = {"MetricName": self.name, "Value": self.value, "Unit": self.unit}
        try:
            if self.dimensions:
                metric_data_entry["Dimensions"] = [
                    {"Name": dimension["Name"], "Value": str(dimension["Value"])} for dimension in self.dimensions
                ]
            if self.timestamp:
                metric_data_entry["Timestamp"] = self.timestamp
        except KeyError:
            logging.error("Error in Dimensions.  Each dimension must include a 'Name' and 'Value' key")
        return metric_data_entry


# A MetricsPublisher class
@dataclass
class MetricsPublisher:
    """Data Class representing a Metrics Publisher. Can be used to quickly push metrics to Cloudwatch"""

    client = None

    def __init__(self, region=None):
        self.client = boto3.client("cloudwatch", region_name=region)

    def publish_metrics_to_cloudwatch(self, namespace: str, metrics: List[Metric]):
        """Pushes a list of metrics to cloudwatch using a single namespace."""
        try:
            logging.info(
                f"publishing metrics to cloudwatch {[metric.generate_metric_data_entry() for metric in metrics]}"
            )
            self.client.put_metric_data(
                Namespace=namespace,
                MetricData=[metric.generate_metric_data_entry() for metric in metrics],
            )
        except botocore.exceptions.ParamValidationError:
            logging.error("Invalid params for metric")
        except Exception as exc:
            logging.error(f"A {type(exc)} occurred with {exc}")
