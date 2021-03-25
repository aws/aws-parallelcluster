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

import sys
import time

import argparse

from awsbatch.common import AWSBatchCliConfig, Boto3ClientFactory, config_logger
from awsbatch.utils import convert_to_date, fail, get_job_type


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
    parser = argparse.ArgumentParser(description="Shows the output of the given Job.")
    parser.add_argument("-c", "--cluster", help="Cluster to use")
    parser.add_argument("-hd", "--head", help="Gets the first <head> lines of the job output", type=int)
    parser.add_argument("-t", "--tail", help="Gets the last <tail> lines of the job output", type=int)
    parser.add_argument(
        "-s",
        "--stream",
        help="Gets the job output and waits for additional output to be produced. "
        "It can be used in conjunction with --tail to start from the "
        "latest <tail> lines of the job output",
        action="store_true",
    )
    parser.add_argument("-sp", "--stream-period", help="Sets the streaming period. Default is 5", type=int)
    parser.add_argument("-ll", "--log-level", help=argparse.SUPPRESS, default="ERROR")
    parser.add_argument("job_id", help="The job ID")
    return parser


def _validate_parameters(args):
    """
    Validate input parameters.

    :param args: args variable
    """
    if args.head:
        if args.tail:
            fail("Parameters validation error: --tail and --head option cannot be set at the same time")
        if args.stream:
            fail("Parameters validation error: --stream and --head option cannot be set at the same time")

    if args.stream_period and not args.stream:
        fail("Parameters validation error: --stream-period can be used only with --stream option")


class AWSBoutCommand(object):
    """awsbout command."""

    def __init__(self, log, boto3_factory):
        """
        Initialize the object.

        :param log: log
        :param boto3_factory: an initialized Boto3ClientFactory object
        """
        self.log = log
        self.boto3_factory = boto3_factory

    def run(self, job_id, head=None, tail=None, stream=None, stream_period=None):
        """Print job output."""
        log_stream = self.__get_log_stream(job_id)
        if log_stream:
            self.log.info("Log stream is (%s)" % log_stream)
            self.__print_log_stream(log_stream, head, tail, stream, stream_period)

    def __get_log_stream(self, job_id):
        """
        Get log stream for the given job.

        :param job_id: job id (ARN)
        :return: the log_stream if there, or None
        """
        log_stream = None
        try:
            batch_client = self.boto3_factory.get_client("batch")
            jobs = batch_client.describe_jobs(jobs=[job_id])["jobs"]
            if len(jobs) == 1:
                job = jobs[0]
                self.log.debug(job)

                if "nodeProperties" in job:
                    # MNP job
                    container = job["nodeProperties"]["nodeRangeProperties"][0]["container"]
                elif "container" in job:
                    container = job["container"]
                else:
                    container = {}

                if get_job_type(job) != "SIMPLE":
                    fail("No output available for the Job (%s). Please ask for its children." % job["jobId"])
                else:
                    if "logStreamName" in container:
                        log_stream = container.get("logStreamName")
                    else:
                        print("No log stream found for job (%s) in the status (%s)" % (job_id, job["status"]))
            else:
                fail("Error asking job output for job (%s). Job not found." % job_id)
        except Exception as e:
            fail("Error listing jobs from AWS Batch. Failed with exception: %s" % e)
        return log_stream

    def __print_log_stream(self, log_stream, head=None, tail=None, stream=None, stream_period=None):  # noqa: C901 FIXME
        """
        Ask for log stream and print it.

        :param log_stream: job log stream
        """
        logs_client = self.boto3_factory.get_client("logs")
        try:
            # The maximum number of log events returned by the get_log_events function is as many log events
            # as can fit in a response size of 1 MB, up to 10,000 log events
            max_limit = 10000
            if head:
                limit = head
                start_from_head = True
            elif tail:
                limit = tail
                start_from_head = False
            else:
                limit = max_limit
                start_from_head = False

            response = logs_client.get_log_events(
                logGroupName="/aws/batch/job", logStreamName=log_stream, limit=limit, startFromHead=start_from_head
            )
            events = response["events"]
            self.log.debug(response)
            if not events:
                print("No events found.")

            self.__print_events(events)
            if limit == max_limit or stream:
                # get paginated items
                next_token = response["nextForwardToken"]
                while next_token is not None or stream:
                    self.log.info("Next Forward Token is (%s)" % next_token)
                    if stream:
                        period = stream_period if stream_period else 5
                        self.log.info("Waiting other %s seconds..." % period)
                        time.sleep(period)
                    response = logs_client.get_log_events(
                        logGroupName="/aws/batch/job", logStreamName=log_stream, nextToken=next_token
                    )
                    self.__print_events(response["events"])
                    # if nextForwardToken is the same we passed in, we reached the end of the stream
                    if stream:
                        next_token = response["nextForwardToken"]
                    else:
                        next_token = (
                            response["nextForwardToken"] if response["nextForwardToken"] != next_token else None
                        )
        except KeyboardInterrupt:
            self.log.info("Interrupted by the user")
            exit(0)
        except Exception as e:
            fail("Error listing jobs from AWS Batch. Failed with exception: %s" % e)

    @staticmethod
    def __print_events(events):
        """
        Print given events.

        :param events: events to print
        """
        for event in events:
            print("{0}: {1}".format(convert_to_date(event["timestamp"]), event["message"]))


def main():
    """Command entrypoint."""
    try:
        # parse input parameters and config file
        args = _get_parser().parse_args()
        _validate_parameters(args)
        log = config_logger(args.log_level)
        log.info("Input parameters: %s" % args)
        config = AWSBatchCliConfig(log=log, cluster=args.cluster)
        boto3_factory = Boto3ClientFactory(
            region=config.region,
            proxy=config.proxy,
            aws_access_key_id=config.aws_access_key_id,
            aws_secret_access_key=config.aws_secret_access_key,
        )

        AWSBoutCommand(log, boto3_factory).run(
            job_id=args.job_id, head=args.head, tail=args.tail, stream=args.stream, stream_period=args.stream_period
        )

    except KeyboardInterrupt:
        print("Exiting...")
        sys.exit(0)
    except Exception as e:
        fail("Unexpected error. Command failed with exception: %s" % e)


if __name__ == "__main__":
    main()
