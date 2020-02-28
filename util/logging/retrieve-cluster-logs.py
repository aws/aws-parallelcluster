#!/usr/bin/env python
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
#
# Future enhancements:
#   * Catch KeyboardInterrupt exceptions while waiting for export tasks to start or finish and clean up accordingly.

import gzip
import json
import logging
import os
import sys
import tarfile
import tempfile
import time
from datetime import datetime

import argparse
import boto3

logging.basicConfig(level=logging.INFO)
LOGGER = logging.getLogger(__file__)

DEFAULT_BUCKET_PREFIX_FORMAT = "{{cluster_name}}-logs-{timestamp}".format(timestamp=datetime.now().timestamp())
DEFAULT_TARBALL_PATH_FORMAT = "{bucket_prefix_format}.tar.gz".format(bucket_prefix_format=DEFAULT_BUCKET_PREFIX_FORMAT)


def err_and_exit(message):
    """Log the given error message and exit nonzero."""
    LOGGER.error(message)
    sys.exit(1)


def get_log_group(args):
    """Get log group for args.cluster."""
    log_group_name = "/aws/parallelcluster/{}".format(args.cluster)
    logs = boto3.client("logs", region_name=args.region)
    paginator = logs.get_paginator("describe_log_groups")
    for result in paginator.paginate(logGroupNamePrefix=log_group_name):
        for group in result.get("logGroups"):
            if group.get("logGroupName") == log_group_name:
                return group
    err_and_exit(
        "Unable to find log group in region {region} for cluster {cluster}. "
        "Expected to find one named {log_group_name}".format(
            region=args.region, cluster=args.cluster, log_group_name=log_group_name
        )
    )


def verify_bucket_exists_in_region(args):
    """Verify that bucket exists."""
    bucket = boto3.resource("s3", region_name=args.region).Bucket(args.bucket)
    if bucket.creation_date is None:
        err_and_exit("s3 bucket {} does not exist.".format(args.bucket))
    bucket_region = bucket.meta.client.get_bucket_location(Bucket=bucket.name).get("LocationConstraint")
    expected_region = args.region if args.region != "us-east-1" else None
    if bucket_region != expected_region:
        err_and_exit(
            "CloudWatch requires buckets to use for exporting logs to be in the same region as the log group. "
            "The given cluster's log group is in {region}, but the given bucket's region is {bucket_region} ".format(
                region=expected_region, bucket_region=bucket_region
            )
        )


def verify_times(args):
    """Verify that the start and end times represent a window containing at least one log event."""
    if args.from_time >= args.to_time:
        err_and_exit("Start time must be earlier than end time.")
    logs_client = boto3.client("logs", region_name=args.region)
    event_in_window = logs_client.filter_log_events(
        logGroupName=args.log_group.get("logGroupName"),
        startTime=int(1000 * args.from_time.timestamp()),
        endTime=int(1000 * args.to_time.timestamp()),
        limit=1,
    ).get("events")
    if not event_in_window:
        err_and_exit(
            "No log events in the log group {log_group} in interval starting at {start} and ending at {end}".format(
                log_group=args.log_group.get("logGroupName"), start=args.from_time, end=args.to_time
            )
        )


def verify_tarball_path(path):
    """Verify that a tarball can be written to the given path."""
    tarball_dir = os.path.dirname(path)
    if not os.path.isdir(tarball_dir):
        try:
            os.makedirs(tarball_dir)
        except Exception as exception:
            err_and_exit(
                "Failed to create parent directory {directory} for cluster's logs archive. Reason: {reason}".format(
                    directory=tarball_dir, reason=exception
                )
            )
    if not os.access(tarball_dir, os.W_OK):
        err_and_exit(
            "Cannot write cluster's log archive to {path}. {directory} isn't writeable.".format(
                path=path, directory=tarball_dir
            )
        )


def parse_args():
    """Parse command line args."""  # noqa: D202

    def timestamp_from_arg(arg):
        """Convert arg into a UNIX timestamp."""
        return datetime.fromtimestamp(int(arg))

    parser = argparse.ArgumentParser(description="Create an archive for a ParallelCluster's CloudWatch logs.")
    parser.add_argument("--bucket", required=True, help="s3 bucket to export CloudWatch logs data to.")
    parser.add_argument("--cluster", required=True, help="Name of cluster whose logs to get.")
    parser.add_argument(
        "--bucket-prefix",
        help="Keypath under which exported CloudWatch logs data will be stored in s3 bucket. Also serves as top-level "
        "directory in resulting archive.",
    )
    parser.add_argument(
        "--keep-s3-objects",
        action="store_true",
        help="Keep the objects CloudWatch exports to S3. The default behavior is to delete them.",
    )
    parser.add_argument(
        "--from-time",
        type=timestamp_from_arg,
        help="Start time of interval of interest for log events, as number of seconds since the epoch. Deafults to "
        "cluster's start time.",
    )
    parser.add_argument("--region", required=True, help="Region in which the CloudWatch log group exists.")
    parser.add_argument("--tarball-path", help="Path to save log file archive to.", type=os.path.realpath)
    parser.add_argument(
        "--to-time",
        type=timestamp_from_arg,
        help="End time of interval of interest for log events, as number of seconds since the epoch. Defaults to the "
        "current time.",
    )
    args = parser.parse_args()

    # Set defaults that require other args
    # Don't set default for bucket prefix here because logic in main changes depending on if default is used
    if not args.tarball_path:
        args.tarball_path = os.path.realpath(DEFAULT_TARBALL_PATH_FORMAT.format(cluster_name=args.cluster))
    args.log_group = get_log_group(args)
    if args.from_time is None:
        args.from_time = datetime.fromtimestamp(args.log_group.get("creationTime") / 1000)
    if args.to_time is None:
        args.to_time = datetime.now()

    # Verify args
    verify_bucket_exists_in_region(args)
    verify_times(args)
    verify_tarball_path(args.tarball_path)

    return args


def start_export_task(logs_client, args):
    """Start the task that will export the cluster's logs to an s3 bucket, and return the task ID."""
    LOGGER.info(
        "Starting export of logs from log group {log_group} to s3 bucket {bucket}".format(
            log_group=args.log_group.get("logGroupName"), bucket=args.bucket
        )
    )
    try:
        response = logs_client.create_export_task(
            logGroupName=args.log_group.get("logGroupName"),
            fromTime=int(1000 * args.from_time.timestamp()),
            to=int(1000 * args.to_time.timestamp()),
            destination=args.bucket,
            destinationPrefix=args.bucket_prefix,
        )
    except Exception as err:
        if "Please check if CloudWatch Logs has been granted permission to perform this operation." in str(err):
            err_and_exit(
                "CloudWatch Logs needs GetBucketAcl and PutObject permisson for the s3 bucket {bucket}. See {url} for "
                "more details.".format(
                    bucket=args.bucket,
                    url="https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/S3ExportTasks.html#S3Permissions",
                )
            )
        else:
            err_and_exit("Unexpected error when starting export task: {}".format(err))
    return response.get("taskId")


def get_status_for_export_task(logs_client, task_id):
    """Get the status for the CloudWatch export task with the given task_id."""
    tasks = logs_client.describe_export_tasks(taskId=task_id).get("exportTasks")
    if not tasks:
        err_and_exit("Unable to get status for CloudWatch logs export task with ID={}".format(task_id))
    elif len(tasks) > 2:
        err_and_exit(
            "More than one CloudWatch logs export task with ID={task_id}:\n{tasks}".format(
                task_id=task_id, tasks=json.dumps(tasks, indent=2)
            )
        )
    return tasks[0].get("status").get("code")


def wait_for_task_completion(logs_client, task_id):
    """Wait for the CloudWatch logs export task given by task_id to finish."""
    LOGGER.info("Waiting for export task with task ID {} to finish.".format(task_id))
    status = "PENDING"
    still_running_statuses = ("PENDING", "PENDING_CANCEL", "RUNNING")
    while status in still_running_statuses:
        time.sleep(1)
        status = get_status_for_export_task(logs_client, task_id)
    return status


def export_logs_to_s3(args):
    """Export the contents of a cluster's CloudWatch log group to an s3 bucket."""
    logs_client = boto3.client("logs", region_name=args.region)
    task_id = start_export_task(logs_client, args)
    result_status = wait_for_task_completion(logs_client, task_id)
    if result_status != "COMPLETED":
        err_and_exit(
            "CloudWatch logs export task {task_id} failed with status: {result_status}".format(
                task_id=task_id, result_status=result_status
            )
        )
        sys.exit(1)
    return task_id


def download_all_objects_with_prefix(bucket, prefix, destdir):
    """Download all object in bucket with given prefix into destdir."""
    LOGGER.info(
        "Downloading exported logs from s3 bucket {bucket} (under key {prefix}) to {destdir}".format(
            bucket=bucket.name, prefix=prefix, destdir=destdir
        )
    )
    for log_archive_object in bucket.objects.filter(Prefix=prefix):
        decompressed_path = os.path.dirname(os.path.join(destdir, log_archive_object.key))
        decompressed_path = decompressed_path.replace(
            r"{unwanted_path_segment}{sep}".format(unwanted_path_segment=prefix, sep=os.path.sep), ""
        )
        compressed_path = "{}.gz".format(decompressed_path)
        LOGGER.debug(
            "Downloading object with key={key} to {compressed}".format(
                key=log_archive_object.key, compressed=compressed_path
            )
        )
        os.makedirs(os.path.dirname(compressed_path), exist_ok=True)
        bucket.download_file(log_archive_object.key, compressed_path)

        # Create a decompressed copy of the downloaded archive and remove the original
        LOGGER.debug(
            "Extracting object at {compressed_path} to {decompressed_path}".format(
                compressed_path=compressed_path, decompressed_path=decompressed_path
            )
        )
        with gzip.open(compressed_path) as gfile, open(decompressed_path, "wb") as outfile:
            outfile.write(gfile.read())
        os.remove(compressed_path)


def archive_dir(src, dest, bucket_prefix):
    """Create a gzipped tarball archive for the directory at src and save it to dest."""
    LOGGER.info("Creating archive of logs at {src} and saving it to {dest}".format(src=src, dest=dest))
    with tarfile.open(dest, "w:gz") as tar:
        tar.add(src, arcname=bucket_prefix)


def download_and_archive_logs_from_s3(args, task_id):
    """Download logs from s3 bucket."""
    bucket = boto3.resource("s3", region_name=args.region).Bucket(args.bucket)
    prefix = "{explicit_prefix}/{task_id}".format(explicit_prefix=args.bucket_prefix, task_id=task_id)
    with tempfile.TemporaryDirectory() as parent_tempdir:
        tempdir = os.path.join(parent_tempdir, args.bucket_prefix)
        download_all_objects_with_prefix(bucket, prefix, tempdir)
        archive_dir(tempdir, args.tarball_path, args.bucket_prefix)


def prefix_contains_objects(bucket, prefix):
    """Return boolean describing whether the given bucket has any objects under the given key prefix."""
    bucket = boto3.resource("s3").Bucket(bucket)
    return any(bucket.objects.filter(Prefix=prefix).limit(1))


def delete_s3_objects(bucket, key):
    """Delete all objects in the given bucket under the given key."""
    LOGGER.info("Deleting all objects in {bucket} under {key}".format(bucket=bucket, key=key))
    bucket = boto3.resource("s3").Bucket(bucket).objects.filter(Prefix=key).delete()


def main():
    """Run the script."""
    args = parse_args()

    # If the default bucket prefix is being used and there's nothing underneath that prefix already then we can delete
    # everything under that prefix after downloading the data (unless --keep-s3-objects is specified).
    delete_everything_under_prefix = False
    if not args.bucket_prefix:
        args.bucket_prefix = DEFAULT_BUCKET_PREFIX_FORMAT.format(cluster_name=args.cluster)
        delete_everything_under_prefix = not prefix_contains_objects(args.bucket, args.bucket_prefix)

    task_id = export_logs_to_s3(args)
    try:
        download_and_archive_logs_from_s3(args, task_id)
        LOGGER.info(
            "Archive of CloudWatch logs from cluster {cluster} saved to {archive_path}".format(
                cluster=args.cluster, archive_path=args.tarball_path
            )
        )
    finally:
        if not args.keep_s3_objects:
            if delete_everything_under_prefix:
                delete_key = args.bucket_prefix
            else:
                delete_key = "/".join((args.bucket_prefix, task_id))
            delete_s3_objects(args.bucket, delete_key)


if __name__ == "__main__":
    main()
