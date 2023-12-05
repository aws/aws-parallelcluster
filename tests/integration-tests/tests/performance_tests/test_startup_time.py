import logging
import statistics
from datetime import datetime

import boto3
import pytest
from dateutil.relativedelta import relativedelta
from utils import describe_cluster_instances

MINIMUM_DATASET_SIZE = 2


def evaluate_data(value, data):
    standard_deviation = statistics.stdev(data)
    mean = statistics.mean(data)
    logging.info(f"Standard deviation: {standard_deviation}")

    if value < (mean + 2 * standard_deviation) or value > (mean - 2 * standard_deviation):
        return False
    return True


def get_data(dimensions, cw_client):
    data = []

    cluster_metrics = cw_client.list_metrics(
        Namespace="ParallelCluster", MetricName="StartupTime", Dimensions=dimensions
    )

    logging.info(f"Metrics: {cluster_metrics}")

    for metric in cluster_metrics["Metrics"]:
        result = cw_client.get_metric_statistics(
            Namespace="ParallelCluster",
            MetricName="StartupTime",
            Dimensions=metric["Dimensions"],
            StartTime=datetime.now() - relativedelta(years=1),
            EndTime=datetime.now(),
            Period=30000,
            Statistics=["Average"],
            Unit="None",
        )

        logging.info(f"Results: {result}")

        if result["Datapoints"]:
            value = result["Datapoints"][0].get("Average")
            data.append(value)
    return data


def get_metric(dimensions, cw_client):
    value = None

    result = cw_client.get_metric_statistics(
        Namespace="ParallelCluster",
        MetricName="StartupTime",
        Dimensions=dimensions,
        StartTime=datetime.now() - relativedelta(years=1),
        EndTime=datetime.now(),
        Period=30000,
        Statistics=["Average"],
        Unit="None",
    )

    logging.info(f"Results: {result}")

    if result["Datapoints"]:
        value = result["Datapoints"][0].get("Average")
    return value


def test_startup_time(pcluster_config_reader, clusters_factory, test_datadir, region, instance, os, scheduler):
    cluster_config = pcluster_config_reader()
    cluster = clusters_factory(cluster_config)
    logging.info("Cluster Created")

    cw_client = boto3.client("cloudwatch", region_name=region)

    instances = describe_cluster_instances(
        cluster.name,
        region,
        filter_by_node_type="Compute",
    )

    performance_degradation = {}

    for instance in instances:
        instance_type = instance["InstanceType"]
        instance_id = instance["InstanceId"]
        logging.info(f"Type: {instance_type}")

        # get new startup time

        dimensions = [
            {"Name": "OS", "Value": os},
            {"Name": "InstanceID", "Value": instance_id},
            {"Name": "ClusterName", "Value": cluster.name},
            {"Name": "InstanceType", "Value": instance_type},
        ]

        value = get_metric(dimensions, cw_client)
        logging.info(f"Value: {value}")

        # get historical data
        dimensions = [{"Name": "InstanceType", "Value": instance_type}, {"Name": "OS", "Value": os}]
        data = get_data(dimensions, cw_client)
        if value in data:
            data.remove(value)

        logging.info(f"Data of {instance_type}: {data}")

        # evaluate data
        if len(data) > MINIMUM_DATASET_SIZE and value:
            degradation = evaluate_data(value, data)
            if degradation:
                performance_degradation[instance_type] = value

    if performance_degradation:
        degraded_instances = performance_degradation.keys()
        pytest.fail(
            f"Performance test results show performance degradation for the following instances: {degraded_instances}"
        )
    else:
        logging.info("Performance test results show no performance degradation")
