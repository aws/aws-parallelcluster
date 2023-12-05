import logging
import statistics
from datetime import datetime

import boto3
import pytest
from dateutil.relativedelta import relativedelta
from utils import describe_cluster_instances

MINIMUM_DATASET_SIZE = 5


def evaluate_data(value, data):
    standard_deviation = statistics.stdev(data)
    mean = statistics.mean(data)
    logging.info(f"Mean: {mean}")
    logging.info(f"Standard deviation: {standard_deviation}")

    distance = abs(mean - value) / standard_deviation
    if value < (mean + 2 * standard_deviation) or value > (mean - 2 * standard_deviation):
        return False, distance
    return True, distance


def get_data(instance_type, os, cw_client):
    data = []
    dimensions = [{"Name": "InstanceType", "Value": instance_type}, {"Name": "OS", "Value": os}]

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


def get_metric(os, cluster, instance_type, instance_id, cw_client):
    value = None

    dimensions = [
        {"Name": "OS", "Value": os},
        {"Name": "InstanceID", "Value": instance_id},
        {"Name": "ClusterName", "Value": cluster.name},
        {"Name": "InstanceType", "Value": instance_type},
    ]

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

        value = get_metric(os, cluster, instance_type, instance_id, cw_client)
        logging.info(f"Value: {value}")

        # get historical data
        data = get_data(instance_type, os, cw_client)
        if value in data:
            data.remove(value)

        logging.info(f"Data of {instance_type}: {data}")

        # evaluate data
        if len(data) > MINIMUM_DATASET_SIZE and value:
            degradation, dist = evaluate_data(value, data)
            if degradation:
                performance_degradation[instance_type] = dist

    if performance_degradation:
        message = "Performance test results show performance degradation for the following instances: "
        for instance in performance_degradation.keys():
            message += f"{instance} ({performance_degradation[instance]} standard deviations from the mean), "
        pytest.fail(message[:-2])
    else:
        logging.info("Performance test results show no performance degradation")
