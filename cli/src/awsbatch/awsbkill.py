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

import sys

import argparse

from awsbatch.common import AWSBatchCliConfig, Boto3ClientFactory, config_logger
from awsbatch.utils import fail


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
    parser = argparse.ArgumentParser(description="Cancels/terminates jobs submitted in the cluster.")
    parser.add_argument("-c", "--cluster", help="Cluster to use")
    parser.add_argument(
        "-r",
        "--reason",
        help="A message to attach to the job that explains the reason for canceling it",
        default="Terminated by the user",
    )
    parser.add_argument("-ll", "--log-level", help=argparse.SUPPRESS, default="ERROR")
    parser.add_argument("job_ids", help="A space separated list of job IDs to cancel/terminate", nargs="+")
    return parser


class AWSBkillCommand(object):
    """awsbkill command."""

    def __init__(self, log, boto3_factory):
        """
        Initialize the object.

        :param log: log
        :param boto3_factory: an initialized Boto3ClientFactory object
        """
        self.log = log
        self.boto3_factory = boto3_factory
        self.batch_client = boto3_factory.get_client("batch")

    def run(self, job_ids, reason):
        """
        Kill/cancel the jobs.

        :param job_ids: list of job ids
        :param reason: optional reason
        """
        jobs = self.batch_client.describe_jobs(jobs=job_ids)["jobs"]
        self.log.debug(jobs)

        if len(jobs) != len(job_ids):
            available_job_ids = []
            for job in jobs:
                available_job_ids.append(job["jobId"])
            for job_id in job_ids:
                if job_id not in available_job_ids:
                    print("Job (%s) not found." % job_id)
        self.__kill_jobs(jobs, reason)

    def __kill_jobs(self, jobs, reason):
        """
        Kill given jobs.

        :param jobs: a list of jobs ids
        :param reason: reason for canceling the job
        """
        for job in jobs:
            status = job["status"]
            job_id = job["jobId"]
            if status == "FAILED" or status == "SUCCEEDED":
                print("Job (%s) is already in (%s) status." % (job_id, status))
            else:
                try:
                    self.batch_client.terminate_job(jobId=job_id, reason=reason)
                    if status == "SUBMITTED" or status == "PENDING" or status == "RUNNABLE":
                        action = "cancellation"
                    else:
                        # status == 'STARTING' or status == 'RUNNING'
                        action = "termination"
                    print(
                        "Your job %s request for job (%s) in status (%s) has been submitted." % (action, job_id, status)
                    )
                except Exception as e:
                    print("Error killing job (%s). Failed with exception: %s" % e)
                    pass


def main():
    """Command entrypoint."""
    try:
        # parse input parameters and config file
        args = _get_parser().parse_args()
        log = config_logger(args.log_level)
        log.info("Input parameters: %s" % args)
        config = AWSBatchCliConfig(log=log, cluster=args.cluster)
        boto3_factory = Boto3ClientFactory(
            region=config.region,
            proxy=config.proxy,
            aws_access_key_id=config.aws_access_key_id,
            aws_secret_access_key=config.aws_secret_access_key,
        )
        AWSBkillCommand(log, boto3_factory).run(job_ids=args.job_ids, reason=args.reason)

    except KeyboardInterrupt:
        print("Exiting...")
        sys.exit(0)
    except Exception as e:
        fail("Unexpected error. Command failed with exception: %s" % e)


if __name__ == "__main__":
    main()
