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
import sys

import argparse

from awsbatch.common import AWSBatchCliConfig, Boto3ClientFactory, Output, config_logger
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
    parser = argparse.ArgumentParser(description="Shows the Job Queue associated to the cluster.")
    parser.add_argument("-c", "--cluster", help="Cluster to use")
    parser.add_argument("-d", "--details", help="Show queues details", action="store_true")
    parser.add_argument("-ll", "--log-level", help=argparse.SUPPRESS, default="ERROR")
    parser.add_argument(
        "job_queues",
        help="A space separated list of queues names to show. If a single queue is "
        "requested it will be shown in a detailed version",
        nargs="*",
    )
    return parser


class Queue(object):
    """Generic queue object."""

    def __init__(self, arn, name, priority, status, status_reason):
        """Initialize the object."""
        self.arn = arn
        self.name = name
        self.priority = priority
        self.status = status
        self.status_reason = status_reason


class AWSBqueuesCommand(object):
    """awsbqueues command."""

    def __init__(self, log, boto3_factory):
        """
        Initialize the object.

        :param log: log
        :param boto3_factory: an initialized Boto3ClientFactory object
        """
        self.log = log
        mapping = collections.OrderedDict(
            [
                ("jobQueueArn", "arn"),
                ("jobQueueName", "name"),
                ("priority", "priority"),
                ("status", "status"),
                ("statusReason", "status_reason"),
            ]
        )
        self.output = Output(mapping=mapping)
        self.boto3_factory = boto3_factory

    def run(self, job_queues, show_details=False):
        """Print list of queues."""
        self.__init_output(job_queues)
        if show_details:
            self.output.show()
        else:
            self.output.show_table(["jobQueueName", "status"])

    def __init_output(self, job_queues):
        """
        Initialize queues output by asking for given queues.

        :param job_queues: a list of job queues
        """
        try:
            # connect to batch and get queues
            batch_client = self.boto3_factory.get_client("batch")
            queues = batch_client.describe_job_queues(jobQueues=job_queues)["jobQueues"]
            self.log.info("Job Queues: %s" % job_queues)
            self.log.debug(queues)

            for queue in queues:
                self.output.add(self.__new_queue(queue=queue))

        except Exception as e:
            fail("Error listing queues from AWS Batch. Failed with exception: %s" % e)

    @staticmethod
    def __new_queue(queue):
        """
        Parse jobQueue and return a Queue object.

        :param queue: the jobQueue object to parse
        :return: a Queue object
        """
        try:
            return Queue(
                arn=queue["jobQueueArn"],
                name=queue["jobQueueName"],
                priority=queue["priority"],
                status=queue["status"],
                status_reason=queue["statusReason"],
            )
        except KeyError as e:
            fail("Error building Queue item. Key (%s) not found." % e)


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

        if args.job_queues:
            job_queues = args.job_queues
            show_details = True
        else:
            job_queues = [config.job_queue]
            show_details = args.details
        AWSBqueuesCommand(log, boto3_factory).run(job_queues=job_queues, show_details=show_details)

    except KeyboardInterrupt:
        print("Exiting...")
        sys.exit(0)
    except Exception as e:
        fail("Unexpected error. Command failed with exception: %s" % e)


if __name__ == "__main__":
    main()
