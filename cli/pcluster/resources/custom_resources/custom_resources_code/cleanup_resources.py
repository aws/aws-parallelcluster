# Copyright 2018 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance with
#  the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
import logging
import time

import boto3
from botocore.config import Config
from crhelper import CfnResource

helper = CfnResource(json_logging=False, log_level="INFO", boto_level="ERROR", sleep_on_delete=0)
logger = logging.getLogger(__name__)
boto3_config = Config(retries={"max_attempts": 60})


def _delete_dns_records(event):
    """Delete all DNS entries from the private Route53 hosted zone created within the cluster."""
    hosted_zone_id = event["ResourceProperties"]["ClusterHostedZone"]
    if not hosted_zone_id:
        logger.error("Hosted Zone ID is empty")
        raise Exception("Hosted Zone ID is empty")

    try:
        logger.info("Deleting DNS records from %s", hosted_zone_id)
        route53 = boto3.client("route53", config=boto3_config)

        completed_successfully = False
        while not completed_successfully:
            completed_successfully = True
            for changes in _list_resource_record_sets_iterator(hosted_zone_id):
                if changes:
                    try:
                        route53.change_resource_record_sets(
                            HostedZoneId=hosted_zone_id, ChangeBatch={"Changes": changes}
                        )
                    except Exception as e:
                        logger.error("Failed when deleting DNS records from %s with error %s", hosted_zone_id, e)
                        completed_successfully = False
                        continue
                else:
                    logger.info("No DNS records to delete from %s.", hosted_zone_id)

            logger.info("Sleeping for 5 seconds before retrying DNS records deletion.")
            time.sleep(5)

        logger.info("DNS records deletion from %s: COMPLETED", hosted_zone_id)
    except Exception as e:
        logger.error("Failed when listing DNS records from %s with error %s", hosted_zone_id, e)
        raise


def _list_resource_record_sets_iterator(hosted_zone_id):
    route53 = boto3.client("route53", config=boto3_config)
    pagination_config = {"PageSize": 100}

    paginator = route53.get_paginator("list_resource_record_sets")
    for page in paginator.paginate(HostedZoneId=hosted_zone_id, PaginationConfig=pagination_config):
        changes = []
        for record_set in page.get("ResourceRecordSets", []):
            if record_set.get("Type") == "A":
                changes.append({"Action": "DELETE", "ResourceRecordSet": record_set})
        yield changes


def _delete_s3_bucket(event):
    """
    Empty and delete the bucket passed as argument.

    It exits gracefully if bucket doesn't exist.
    :param bucket_name: bucket to delete
    """
    bucket_name = event["ResourceProperties"]["ResourcesS3Bucket"]
    try:
        if bucket_name != "NONE":
            logger.info("S3 bucket %s deletion: STARTED" % bucket_name)
            bucket = boto3.resource("s3", config=boto3_config).Bucket(bucket_name)
            bucket.objects.all().delete()
            bucket.object_versions.delete()
            bucket.delete()
            logger.info("S3 bucket %s deletion: COMPLETED" % bucket_name)
    except boto3.client("s3").exceptions.NoSuchBucket as ex:
        logger.warning("S3 bucket %s not found. Bucket was probably manually deleted." % bucket_name)
        logger.warning(ex, exc_info=True)
    except Exception as e:
        logger.error("Failed when deleting bucket %s with error %s", bucket_name, e)
        raise


def _terminate_cluster_nodes(event):
    try:
        logger.info("Compute fleet clean-up: STARTED")
        stack_name = event["ResourceProperties"]["StackName"]
        ec2 = boto3.client("ec2", config=boto3_config)

        completed_successfully = False
        while not completed_successfully:
            completed_successfully = True
            for instance_ids in _describe_instance_ids_iterator(stack_name):
                logger.info("Terminating instances %s", instance_ids)
                if instance_ids:
                    try:
                        ec2.terminate_instances(InstanceIds=instance_ids)
                    except Exception as e:
                        logger.error("Failed when terminating instances with error %s", e)
                        completed_successfully = False
                        continue
            logger.info("Sleeping for 10 seconds to allow all instances to initiate shut-down")
            time.sleep(10)

        while len(next(_describe_instance_ids_iterator(stack_name, ["shutting-down"]))) > 0:
            logger.info("Waiting for all nodes to shut-down...")
            time.sleep(10)

        logger.info("Compute fleet clean-up: COMPLETED")
    except Exception as e:
        logger.error("Failed when terminating instances with error %s", e)
        raise


def _describe_instance_ids_iterator(stack_name, instance_state=("pending", "running", "stopping", "stopped")):
    ec2 = boto3.client("ec2", config=boto3_config)
    filters = [
        {"Name": "tag:Application", "Values": [stack_name]},
        {"Name": "instance-state-name", "Values": list(instance_state)},
    ]
    pagination_config = {"PageSize": 100}

    paginator = ec2.get_paginator("describe_instances")
    for page in paginator.paginate(Filters=filters, PaginationConfig=pagination_config):
        instances = []
        for reservation in page.get("Reservations", []):
            for instance in reservation.get("Instances", []):
                instances.append(instance.get("InstanceId"))
        yield instances


@helper.create
@helper.update
def no_op(_, __):
    pass


ACTION_HANDLERS = {
    "DELETE_S3_BUCKET": _delete_s3_bucket,
    "TERMINATE_EC2_INSTANCES": _terminate_cluster_nodes,
    "DELETE_DNS_RECORDS": _delete_dns_records,
}


@helper.delete
def delete(event, _):
    action = event["ResourceProperties"]["Action"]
    if action in ACTION_HANDLERS:
        ACTION_HANDLERS[action](event)
    else:
        raise Exception("Unsupported action %s", action)


def handler(event, context):
    helper(event, context)
