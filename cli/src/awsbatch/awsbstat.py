#!/usr/bin/env python2.6

# Copyright 2018 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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

import collections
import re
import sys
from builtins import range
from collections import OrderedDict

import argparse

from awsbatch.common import AWSBatchCliConfig, Boto3ClientFactory, Output, config_logger
from awsbatch.utils import (
    convert_to_date,
    fail,
    get_job_definition_name_by_arn,
    get_job_type,
    is_job_array,
    is_mnp_job,
    shell_join,
)

AWS_BATCH_JOB_STATUS = ["SUBMITTED", "PENDING", "RUNNABLE", "STARTING", "RUNNING", "SUCCEEDED", "FAILED"]


def _get_parser():
    """
    Parse input parameters and return the ArgumentParser object.

    If the command is executed without the --cluster parameter, the command will use the default cluster_name
    specified in the [main] section of the user's awsbatch-cli.cfg configuration file and will search
    for the [cluster cluster-name] section, if the section doesn't exist, it will ask to CloudFormation
    the required information.

    If the --cluster parameter is set, the command will search for the [cluster cluster-name] section
    in the user's awsbatch-cli.cfg configuration file or, if the file doesn't exist, it will ask to CloudFormation
    the required information.

    :return: the ArgumentParser object
    """
    parser = argparse.ArgumentParser(description="Shows the jobs submitted in the cluster's Job Queue.")
    parser.add_argument("-c", "--cluster", help="Cluster to use")
    parser.add_argument(
        "-s",
        "--status",
        help='Comma separated list of job status to ask, defaults to "active" jobs. '
        "Accepted values are: SUBMITTED, PENDING, RUNNABLE, STARTING, RUNNING, "
        "SUCCEEDED, FAILED, ALL",
        default="SUBMITTED,PENDING,RUNNABLE,STARTING,RUNNING",
    )
    parser.add_argument(
        "-e", "--expand-children", help="Expand jobs with children (array and MNP)", action="store_true"
    )
    parser.add_argument("-d", "--details", help="Show jobs details", action="store_true")
    parser.add_argument("-ll", "--log-level", help=argparse.SUPPRESS, default="ERROR")
    parser.add_argument(
        "job_ids",
        help="A space separated list of job IDs to show in the output. If the job is a "
        "job array, all the children will be displayed. If a single job is requested "
        "it will be shown in a detailed version",
        nargs="*",
    )
    return parser


class Job(object):
    """Generic job object."""

    def __init__(
        self,
        job_id,
        name,
        creation_time,
        start_time,
        stop_time,
        status,
        status_reason,
        job_definition,
        queue,
        command,
        reason,
        exit_code,
        vcpus,
        memory,
        nodes,
        log_stream,
        log_stream_url,
        s3_folder_url,
    ):
        """Initialize the object."""
        self.id = job_id
        self.name = name
        self.creation_time = creation_time
        self.start_time = start_time
        self.stop_time = stop_time
        self.status = status
        self.status_reason = status_reason
        self.job_definition = job_definition
        self.queue = queue
        self.command = command
        self.reason = reason
        self.exit_code = exit_code
        self.vcpus = vcpus
        self.memory = memory
        self.nodes = nodes
        self.log_stream = log_stream
        self.log_stream_url = log_stream_url
        self.s3_folder_url = s3_folder_url


class JobConverter(object):
    """Converter for AWS Batch simple job data object."""

    def convert(self, job):
        """
        Convert a job from AWS Batch representation.

        :param job: the job dictionary returned by AWS Batch api.
        :return: a Job object containing the parsed data.
        """
        container = self._get_container(job)
        log_stream, log_stream_url = self._get_log_stream(container, self._get_job_region(job))
        return Job(
            job_id=self._get_job_id(job),
            name=job["jobName"],
            creation_time=convert_to_date(job["createdAt"]),
            start_time=convert_to_date(job["startedAt"]) if "startedAt" in job else "-",
            stop_time=convert_to_date(job["stoppedAt"]) if "stoppedAt" in job else "-",
            status=job.get("status", "UNKNOWN"),
            status_reason=job.get("statusReason", "-"),
            job_definition=self._get_job_definition(job),
            queue=self._get_job_queue(job),
            command=self._get_command(container),
            reason=container.get("reason", "-"),
            exit_code=container.get("exitCode", "-"),
            vcpus=container.get("vcpus", "-"),
            memory=container.get("memory", "-"),
            nodes=self._get_number_of_nodes(job),
            log_stream=log_stream,
            log_stream_url=log_stream_url,
            s3_folder_url=self._get_s3_folder_url(container),
        )

    def _get_job_id(self, job):
        return job["jobId"]

    def _get_number_of_nodes(self, job):
        return 1

    def _get_log_stream(self, container, region):
        log_stream = "-"
        log_stream_url = "-"
        if container and "logStreamName" in container:
            log_stream = container["logStreamName"]
            log_stream_url = self._compose_log_stream_url(region, log_stream)

        return log_stream, log_stream_url

    def _get_container(self, job):
        return job.get("container", {})

    @staticmethod
    def _get_command(container):
        command = container.get("command", [])
        if not command:
            return "-"
        return shell_join(command)

    @staticmethod
    def _get_job_definition(job):
        if "jobQueue" in job:
            return get_job_definition_name_by_arn(job["jobDefinition"], version=True)
        return "-"

    @staticmethod
    def _get_job_queue(job):
        if "jobQueue" in job:
            return job["jobQueue"].split("/")[1]
        return "-"

    @staticmethod
    def _compose_log_stream_url(region, log_stream):
        """
        Create logStream url.

        :param region: the region on which the job has been submitted
        :param log_stream: the log stream name
        :return: an url
        """
        domain = "amazonaws-us-gov" if region.startswith("us-gov") else "aws"
        return (
            "https://console.{0}.amazon.com/cloudwatch/home?"
            "region={1}#logEventViewer:group=/aws/batch/job;stream={2}".format(domain, region, log_stream)
        )

    @staticmethod
    def _get_job_region(job):
        if "jobQueue" in job:
            return re.search(r"^arn:aws.*?:batch:(.*?):", job["jobQueue"]).group(1)
        return "-"

    @staticmethod
    def _get_s3_folder_url(container):
        for env_var in container.get("environment", []):
            if env_var.get("name") == "PCLUSTER_JOB_S3_URL":
                return env_var.get("value")
        return "-"


class MNPJobConverter(JobConverter):
    """Converter for AWS Batch mnp job data object."""

    def _get_number_of_nodes(self, job):
        return job["nodeProperties"]["numNodes"]

    def _get_job_id(self, job):
        return "{0} *{1}".format(job["jobId"], job["nodeProperties"]["numNodes"])

    def _get_log_stream(self, job, region):
        return "-", "-"

    def _get_container(self, job):
        if "nodeRangeProperties" in job["nodeProperties"]:
            return job["nodeProperties"]["nodeRangeProperties"][0]["container"]
        return {}


class ArrayJobConverter(JobConverter):
    """Converter for AWS Batch array job data object."""

    def _get_job_id(self, job):
        return "{0} [{1}]".format(job["jobId"], job["arrayProperties"]["size"])

    def _get_log_stream(self, job, region):
        return "-", "-"


class AWSBstatCommand(object):
    """awsbstat command."""

    __JOB_CONVERTERS = {"SIMPLE": JobConverter(), "ARRAY": ArrayJobConverter(), "MNP": MNPJobConverter()}

    def __init__(self, log, boto3_factory):
        """
        Initialize the object.

        :param log: log
        :param boto3_factory: an initialized Boto3ClientFactory object
        """
        self.log = log
        mapping = collections.OrderedDict(
            [
                ("jobId", "id"),
                ("jobName", "name"),
                ("createdAt", "creation_time"),
                ("startedAt", "start_time"),
                ("stoppedAt", "stop_time"),
                ("status", "status"),
                ("statusReason", "status_reason"),
                ("jobDefinition", "job_definition"),
                ("jobQueue", "queue"),
                ("command", "command"),
                ("exitCode", "exit_code"),
                ("reason", "reason"),
                ("vcpus", "vcpus"),
                ("memory[MB]", "memory"),
                ("nodes", "nodes"),
                ("logStream", "log_stream"),
                ("log", "log_stream_url"),
                ("s3FolderUrl", "s3_folder_url"),
            ]
        )
        self.output = Output(mapping=mapping)
        self.boto3_factory = boto3_factory
        self.batch_client = boto3_factory.get_client("batch")

    def run(self, job_status, expand_children, job_queue=None, job_ids=None, show_details=False):
        """Print list of jobs, by filtering by queue or by ids."""
        if job_ids:
            self.__populate_output_by_job_ids(job_ids, show_details or len(job_ids) == 1, include_parents=True)
            # explicitly asking for job details,
            # or asking for a single simple job (the output is not a list of jobs)
            details_required = show_details or (len(job_ids) == 1 and self.output.length() == 1)
        elif job_queue:
            self.__populate_output_by_queue(job_queue, job_status, expand_children, show_details)
            details_required = show_details
        else:
            fail("Error listing jobs from AWS Batch. job_ids or job_queue must be defined")

        sort_keys_function = self.__sort_by_status_startedat_jobid() if not job_ids else self.__sort_by_key(job_ids)
        if details_required:
            self.output.show(sort_keys_function=sort_keys_function)
        else:
            self.output.show_table(
                keys=["jobId", "jobName", "status", "startedAt", "stoppedAt", "exitCode"],
                sort_keys_function=sort_keys_function,
            )

    @staticmethod
    def __sort_by_key(ordered_keys):  # noqa: D202
        """
        Build a function to sort the output by key.

        :param ordered_keys: list containing the sorted keys.
        :return: a function to be used as key argument of the sorted function.
        """

        def _sort_by_key(item):
            job_id = item.id
            try:
                # in case the parent id was provided as input, sort children based on parent id position
                parent_id = re.findall(r"[\w-]+", job_id)[0]
                job_position = ordered_keys.index(parent_id)

            except ValueError:
                # in case the child id was provided as input, use its position in the list
                job_position = ordered_keys.index(job_id)

            return (
                # sort by id according to the order in the keys_order list
                job_position,
                # sort by full id (needed to have parent before children)
                job_id,
            )

        return _sort_by_key

    @staticmethod
    def __sort_by_status_startedat_jobid():
        """
        Build a function to sort the output by (status, startedAt, jobId).

        :return: a function to be used as key argument of the sorted function.
        """
        return lambda item: (
            # sort by status. Status order is defined by AWS_BATCH_JOB_STATUS.
            AWS_BATCH_JOB_STATUS.index(item.status),
            # sort by startedAt column.
            item.start_time,
            # sort by jobId column.
            item.id,
        )

    def __populate_output_by_job_ids(self, job_ids, details, include_parents=False):
        """
        Add Job item or jobs array children to the output.

        :param job_ids: job ids or ARNs
        :param details: ask for job details
        """
        try:
            if job_ids:
                self.log.info("Describing jobs (%s), details (%s)" % (job_ids, details))
                parent_jobs = []
                jobs_with_children = []
                jobs = self.__chunked_describe_jobs(job_ids)
                for job in jobs:
                    # always add parent job
                    if include_parents or get_job_type(job) == "SIMPLE":
                        parent_jobs.append(job)
                    if is_job_array(job):
                        jobs_with_children.append((job["jobId"], ":", job["arrayProperties"]["size"]))
                    elif is_mnp_job(job):
                        jobs_with_children.append((job["jobId"], "#", job["nodeProperties"]["numNodes"]))

                # add parent jobs to the output
                self.__add_jobs(parent_jobs)

                # create output items for jobs' children
                self.__populate_output_by_parent_ids(jobs_with_children)
        except Exception as e:
            fail("Error describing jobs from AWS Batch. Failed with exception: %s" % e)

    def __populate_output_by_parent_ids(self, parent_jobs):
        """
        Add jobs children to the output.

        :param parent_jobs: list of triplets (job_id, job_id_separator, job_size)
        """
        try:
            expanded_job_ids = []
            for parent_job in parent_jobs:
                expanded_job_ids.extend(
                    [
                        "{JOB_ID}{SEPARATOR}{INDEX}".format(JOB_ID=parent_job[0], SEPARATOR=parent_job[1], INDEX=i)
                        for i in range(0, parent_job[2])
                    ]
                )

            if expanded_job_ids:
                jobs = self.__chunked_describe_jobs(expanded_job_ids)

                # forcing details to be False since already retrieved.
                self.__add_jobs(jobs)
        except Exception as e:
            fail("Error listing job children. Failed with exception: %s" % e)

    def __chunked_describe_jobs(self, job_ids):
        """
        Submit calls to describe_jobs in batches of 100 elements each.

        describe_jobs API call has a hard limit on the number of job that can be
        retrieved with a single call. In case job_ids has more than 100 items, this function
        distributes the describe_jobs call across multiple requests.

        :param job_ids: list of ids for the jobs to describe.
        :return: list of described jobs.
        """
        jobs = []
        for index in range(0, len(job_ids), 100):
            jobs_chunk = job_ids[index : index + 100]  # noqa: E203
            jobs.extend(self.batch_client.describe_jobs(jobs=jobs_chunk)["jobs"])
        return jobs

    def __add_jobs(self, jobs, details=False):
        """
        Get job info from AWS Batch and add to the output.

        :param jobs: list of jobs items (output of the list_jobs function)
        :param details: ask for job details
        """
        try:
            if jobs:
                self.log.debug("Adding jobs to the output (%s)" % jobs)
                if details:
                    self.log.info("Asking for jobs details")
                    jobs_to_show = self.__chunked_describe_jobs([job["jobId"] for job in jobs])
                else:
                    jobs_to_show = jobs

                for job in jobs_to_show:
                    self.log.debug("Adding job to the output (%s)", job)

                    job_converter = self.__JOB_CONVERTERS[get_job_type(job)]

                    self.output.add(job_converter.convert(job))
        except KeyError as e:
            fail("Error building Job item. Key (%s) not found." % e)
        except Exception as e:
            fail("Error adding jobs to the output. Failed with exception: %s" % e)

    def __populate_output_by_queue(self, job_queue, job_status, expand_children, details):
        """
        Add Job items to the output asking for given queue and status.

        :param job_queue: job queue name or ARN
        :param job_status: list of job status to ask
        :param expand_children: if True, the job with children will be expanded by creating a row for each child
        :param details: ask for job details
        """
        try:
            single_jobs = []
            jobs_with_children = []
            for status in job_status:
                next_token = ""  # nosec
                while next_token is not None:
                    response = self.batch_client.list_jobs(jobStatus=status, jobQueue=job_queue, nextToken=next_token)

                    for job in response["jobSummaryList"]:
                        if get_job_type(job) != "SIMPLE" and expand_children is True:
                            jobs_with_children.append(job["jobId"])
                        else:
                            single_jobs.append(job)
                    next_token = response.get("nextToken")

            # create output items for job array children
            self.__populate_output_by_job_ids(jobs_with_children, details)

            # add single jobs to the output
            self.__add_jobs(single_jobs, details)

        except Exception as e:
            fail("Error listing jobs from AWS Batch. Failed with exception: %s" % e)


def main(argv=None):
    """Command entrypoint."""
    try:
        # parse input parameters and config file
        args = _get_parser().parse_args(argv)
        log = config_logger(args.log_level)
        log.info("Input parameters: %s" % args)
        config = AWSBatchCliConfig(log=log, cluster=args.cluster)
        boto3_factory = Boto3ClientFactory(
            region=config.region,
            proxy=config.proxy,
            aws_access_key_id=config.aws_access_key_id,
            aws_secret_access_key=config.aws_secret_access_key,
        )

        job_status_set = OrderedDict((status.strip().upper(), "") for status in args.status.split(","))
        if "ALL" in job_status_set:
            # add all the statuses in the list
            job_status_set = OrderedDict((status, "") for status in AWS_BATCH_JOB_STATUS)
        job_status = list(job_status_set)

        AWSBstatCommand(log, boto3_factory).run(
            job_status=job_status,
            expand_children=args.expand_children,
            job_ids=args.job_ids,
            job_queue=config.job_queue,
            show_details=args.details,
        )

    except KeyboardInterrupt:
        print("Exiting...")
        sys.exit(0)
    except Exception as e:
        fail("Unexpected error. Command failed with exception: %s" % e)


if __name__ == "__main__":
    main()
