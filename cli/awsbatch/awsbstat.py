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
from __future__ import print_function

import argparse
import collections
import sys
from collections import OrderedDict

from awsbatch.common import AWSBatchCliConfig, Boto3ClientFactory, Output, config_logger
from awsbatch.utils import fail, convert_to_date, shell_join, is_job_array, get_job_definition_name_by_arn
from builtins import range


def _get_parser():
    """
    Parse input parameters and return the ArgumentParser object

    If the command is executed without the --cluster parameter, the command will use the default cluster_name
    specified in the [main] section of the user's awsbatch-cli.cfg configuration file and will search
    for the [cluster cluster-name] section, if the section doesn't exist, it will ask to CloudFormation
    the required information.

    If the --cluster parameter is set, the command will search for the [cluster cluster-name] section
    in the user's awsbatch-cli.cfg configuration file or, if the file doesn't exist, it will ask to CloudFormation
    the required information.

    :return: the ArgumentParser object
    """
    parser = argparse.ArgumentParser(description='Shows the jobs submitted in the cluster\'s Job Queue.')
    parser.add_argument('-c', '--cluster', help='Cluster to use')
    parser.add_argument('-s', '--status', help='Comma separated list of job status to ask, defaults to "active" jobs. '
                                               'Accepted values are: SUBMITTED, PENDING, RUNNABLE, STARTING, RUNNING, '
                                               'SUCCEEDED, FAILED, ALL',
                        default='SUBMITTED,PENDING,RUNNABLE,STARTING,RUNNING')
    parser.add_argument('-e', '--expand-arrays', help='Expand job arrays', action='store_true')
    parser.add_argument('-d', '--details', help='Show jobs details', action='store_true')
    parser.add_argument('-ll', '--log-level', help=argparse.SUPPRESS, default='ERROR')
    parser.add_argument('job_ids', help='A space separated list of job IDs to show in the output. If the job is a '
                                        'job array, all the children will be displayed. If a single job is requested '
                                        'it will be shown in a detailed version', nargs='*')
    return parser


def _compose_log_stream_url(region, log_stream):
    """
    Create logStream url
    :param region: the region on which the job has been submitted
    :param log_stream: the log stream name
    :return: an url
    """
    domain = 'amazonaws-us-gov' if region.startswith('us-gov') else 'aws'
    return "https://console.{0}.amazon.com/cloudwatch/home?" \
           "region={1}#logEventViewer:group=/aws/batch/job;stream={2}".format(domain, region, log_stream)


class Job(object):
    """
    Generic job object.
    """
    def __init__(self, job_id, name, creation_time, start_time, stop_time, status, status_reason, job_definition,
                 queue, command, reason, exit_code, vcpus, memory, nodes, log_stream, log_stream_url):
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


class AWSBstatCommand(object):
    """
    awsbstat command
    """
    def __init__(self, log, boto3_factory):
        """
        :param log: log
        :param boto3_factory: an initialized Boto3ClientFactory object
        """
        self.log = log
        mapping = collections.OrderedDict([
            ('jobId', 'id'),
            ('jobName', 'name'),
            ('createdAt', 'creation_time'),
            ('startedAt', 'start_time'),
            ('stoppedAt', 'stop_time'),
            ('status', 'status'),
            ('statusReason', 'status_reason'),
            ('jobDefinition', 'job_definition'),
            ('jobQueue', 'queue'),
            ('command', 'command'),
            ('exitCode', 'exit_code'),
            ('reason', 'reason'),
            ('vcpus', 'vcpus'),
            ('memory[MB]', 'memory'),
            ('nodes', 'nodes'),
            ('logStream', 'log_stream'),
            ('log', 'log_stream_url')
        ])
        self.output = Output(mapping=mapping)
        self.boto3_factory = boto3_factory
        self.batch_client = boto3_factory.get_client('batch')

    def run(self, job_status, expand_arrays, job_queue=None, job_ids=None, show_details=False):
        """
        print list of jobs, by filtering by queue or by ids
        """
        if job_ids:
            self.__populate_output_by_job_ids(job_status, job_ids, show_details or len(job_ids) == 1)
            # explicitly asking for job details,
            # or asking for a single job that is not an array (the output is not a list of jobs)
            details_required = show_details or (len(job_ids) == 1 and self.output.length() == 1)
        elif job_queue:
            self.__populate_output_by_queue(job_queue, job_status, expand_arrays, show_details)
            details_required = show_details
        else:
            fail("Error listing jobs from AWS Batch. job_ids or job_queue must be defined")

        if details_required:
            self.output.show()
        else:
            self.output.show_table(['jobId', 'jobName', 'status', 'startedAt', 'stoppedAt', 'exitCode'])

    def __populate_output_by_job_ids(self, job_status, job_ids, details):
        """
        Add Job item or jobs array children to the output
        :param job_status: list of job status to ask
        :param job_ids: job ids or ARNs
        :param details: ask for job details
        """
        try:
            if job_ids:
                self.log.info("Describing jobs (%s), details (%s)" % (job_ids, details))
                single_jobs = []
                job_array_ids = []
                jobs = self.batch_client.describe_jobs(jobs=job_ids)['jobs']
                for job in jobs:
                    if is_job_array(job):
                        job_array_ids.append(job['jobId'])
                    else:
                        single_jobs.append(job)

                # create output items for job array children
                self.__populate_output_by_array_ids(job_status, job_array_ids, details)

                # add single jobs to the output
                self.__add_jobs(single_jobs, details)
        except Exception as e:
            fail("Error describing jobs from AWS Batch. Failed with exception: %s" % e)

    def __populate_output_by_array_ids(self, job_status, job_array_ids, details):
        """
        Add jobs array children to the output
        :param job_status: list of job status to ask
        :param job_array_ids: job array ids to ask
        :param details: ask for job details
        """
        try:
            for job_array_id in job_array_ids:
                for status in job_status:
                    self.log.info("Listing job array children for job (%s) in status (%s)" % (job_array_id, status))
                    next_token = ''
                    while next_token is not None:
                        response = self.batch_client.list_jobs(jobStatus=status, arrayJobId=job_array_id,
                                                               nextToken=next_token)
                        # add single jobs to the output
                        self.__add_jobs(response['jobSummaryList'], details)
                        next_token = response.get('nextToken')
        except Exception as e:
            fail("Error listing job array children for job (%s). Failed with exception: %s" % (job_array_id, e))

    def __add_jobs(self, jobs, details):
        """
        Get job info from AWS Batch and add to the output
        :param jobs: list of jobs items (output of the list_jobs function)
        :param details: ask for job details
        """
        try:
            if jobs:
                self.log.debug("Adding jobs to the output (%s)" % jobs)
                if details:
                    self.log.info("Asking for jobs details")
                    jobs_to_show = []
                    for index in range(0, len(jobs), 100):
                        jobs_chunk = jobs[index:index + 100]
                        job_ids = []
                        for job in jobs_chunk:
                            job_ids.append(job['jobId'])
                        jobs_to_show.extend(self.batch_client.describe_jobs(jobs=job_ids)['jobs'])
                else:
                    jobs_to_show = jobs

                for job in jobs_to_show:
                    nodes = 1
                    if 'nodeProperties' in job:
                        # MNP job
                        container = job['nodeProperties']['nodeRangeProperties'][0]['container']
                        nodes = job['nodeProperties']['numNodes']
                    elif 'container' in job:
                        container = job['container']
                    else:
                        container = {}

                    if is_job_array(job):
                        # parent job array
                        job_id = '{0}[{1}]'.format(job['jobId'], job['arrayProperties']['size'])
                        log_stream = '-'
                        log_stream_url = '-'
                    else:
                        job_id = job['jobId']
                        if 'logStreamName' in container:
                            log_stream = container.get('logStreamName')
                            log_stream_url = _compose_log_stream_url(self.boto3_factory.region, log_stream)
                        else:
                            log_stream = '-'
                            log_stream_url = '-'

                    command = container.get('command', [])
                    self.log.debug("Adding job to the output (%s)", job)
                    job = Job(job_id=job_id,
                              name=job['jobName'],
                              creation_time=convert_to_date(job['createdAt']),
                              start_time=convert_to_date(job['startedAt']) if 'startedAt' in job else '-',
                              stop_time=convert_to_date(job['stoppedAt']) if 'stoppedAt' in job else '-',
                              status=job.get('status', 'UNKNOWN'),
                              status_reason=job.get('statusReason', '-'),
                              job_definition=get_job_definition_name_by_arn(job['jobDefinition'], version=True)
                              if 'jobQueue' in job else '-',
                              queue=job['jobQueue'].split('/')[1] if 'jobQueue' in job else '-',
                              command=shell_join(command) if command else '-',
                              reason=container.get('reason', '-'),
                              exit_code=container.get('exitCode', '-'),
                              vcpus=container.get('vcpus', '-'),
                              memory=container.get('memory', '-'),
                              nodes=nodes,
                              log_stream=log_stream,
                              log_stream_url=log_stream_url)
                    self.output.add(job)
        except KeyError as e:
            fail("Error building Job item. Key (%s) not found." % e)
        except Exception as e:
            fail("Error adding jobs to the output. Failed with exception: %s" % e)

    def __populate_output_by_queue(self, job_queue, job_status, expand_arrays, details):
        """
        Add Job items to the output asking for given queue and status
        :param job_queue: job queue name or ARN
        :param job_status: list of job status to ask
        :param expand_arrays: if True, the job array will be expanded by creating a row for each child
        :param details: ask for job details
        """
        try:
            for status in job_status:
                next_token = ''
                while next_token is not None:
                    response = self.batch_client.list_jobs(jobStatus=status, jobQueue=job_queue, nextToken=next_token)
                    single_jobs = []
                    job_array_ids = []
                    for job in response['jobSummaryList']:
                        if is_job_array(job) and expand_arrays is True:
                            job_array_ids.append(job['jobId'])
                        else:
                            single_jobs.append(job)

                    # create output items for job array children
                    self.__populate_output_by_job_ids(job_status, job_array_ids, details)

                    # add single jobs to the output
                    self.__add_jobs(single_jobs, details)

                    next_token = response.get('nextToken')
        except Exception as e:
            fail("Error listing jobs from AWS Batch. Failed with exception: %s" % e)


def main():
    aws_batch_job_status = ['SUBMITTED', 'PENDING', 'RUNNABLE', 'STARTING', 'RUNNING', 'SUCCEEDED', 'FAILED']

    try:
        # parse input parameters and config file
        args = _get_parser().parse_args()
        log = config_logger(args.log_level)
        log.info("Input parameters: %s" % args)
        config = AWSBatchCliConfig(log=log, cluster=args.cluster)
        boto3_factory = Boto3ClientFactory(region=config.region, proxy=config.proxy,
                                           aws_access_key_id=config.aws_access_key_id,
                                           aws_secret_access_key=config.aws_secret_access_key)

        job_status_set = OrderedDict((status.strip().upper(), '') for status in args.status.split(','))
        if 'ALL' in job_status_set:
            # add all the statuses in the list
            job_status_set = OrderedDict((status, '') for status in aws_batch_job_status)
        job_status = list(job_status_set)

        AWSBstatCommand(log, boto3_factory).run(job_status=job_status, expand_arrays=args.expand_arrays,
                                                job_ids=args.job_ids, job_queue=config.job_queue,
                                                show_details=args.details)

    except KeyboardInterrupt:
        print("Exiting...")
        sys.exit(0)
    except Exception as e:
        fail("Unexpected error. Command failed with exception: %s" % e)


if __name__ == '__main__':
    main()
