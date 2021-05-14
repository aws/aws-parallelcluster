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

import errno
import logging
import os
from logging.handlers import RotatingFileHandler

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError, ParamValidationError
from configparser import ConfigParser, NoOptionError, NoSectionError
from tabulate import tabulate

from awsbatch.utils import fail, get_region_by_stack_id, hide_keys
from pcluster.config.pcluster_config import default_config_file_path

PCLUSTER_STACK_PREFIX = "parallelcluster-"


def _get_stack_name(cluster_name):
    return PCLUSTER_STACK_PREFIX + cluster_name


class Output(object):
    """Generic Output object."""

    def __init__(self, mapping, items=None):
        """
        Create a table of generic items.

        :param items: list of items
        :param mapping: association between keys and item attributes
        """
        self.items = items if items else []
        self.mapping = mapping
        self.keys = []
        for key in mapping.keys():
            self.keys.append(key)

    def add(self, items):
        """Add items to output."""
        if type(items) == list:
            self.items.extend(items)
        else:
            self.items.append(items)

    def show_table(self, keys=None, sort_keys_function=None):
        """
        Print the items table.

        :param keys: show a specific list of keys (optional)
        :param sort_keys_function: function to sort table rows (optional)
        """
        rows = []
        output_keys = keys or self.keys

        for item in self.__get_items(sort_keys_function):
            row = []
            for output_key in output_keys:
                row.append(getattr(item, self.mapping[output_key]))
            rows.append(row)
        print(tabulate(rows, output_keys))

    def show(self, keys=None, sort_keys_function=None):
        """
        Print the items in a key value format.

        :param keys: show a specific list of keys (optional)
        """
        output_keys = keys or self.keys
        if not self.items:
            print("No items to show")
        else:
            for item in self.__get_items(sort_keys_function):
                for output_key in output_keys:
                    print("{0:25}: {1!s}".format(output_key, getattr(item, self.mapping[output_key])))
                print("-" * 25)

    def length(self):
        """Return number of items in Output."""
        return len(self.items)

    def __get_items(self, sort_keys_function=None):
        """Return a sorted copy of self.items if sort_keys_function is given, a reference to self.items otherwise."""
        if sort_keys_function:
            return sorted(list(self.items), key=sort_keys_function)
        return self.items


class Boto3ClientFactory(object):
    """Boto3 configuration object."""

    def __init__(self, region, aws_access_key_id, aws_secret_access_key, proxy="NONE"):
        """Initialize the object."""
        self.region = region
        self.aws_access_key_id = aws_access_key_id
        self.aws_secret_access_key = aws_secret_access_key
        self.proxy_config = Config()
        if not proxy == "NONE":
            self.proxy_config = Config(proxies={"https": proxy})

    def get_client(self, service):
        """
        Initialize the boto3 client for a given service.

        :param service: boto3 service.
        :return: the boto3 client
        """
        try:
            return boto3.client(
                service,
                region_name=self.region,
                aws_access_key_id=self.aws_access_key_id,
                aws_secret_access_key=self.aws_secret_access_key,
                config=self.proxy_config,
            )
        except ClientError as e:
            fail("AWS %s service failed with exception: %s" % (service, e))


class AWSBatchCliConfig(object):
    """AWS ParallelCluster AWS Batch CLI configuration object."""

    def __init__(self, log, cluster):
        """
        Initialize the object.

        Search for the [cluster cluster-name] section in the /etc/awsbatch-cli.cfg configuration file, if there
        or ask to the pcluster status.

        :param log: log
        :param cluster: cluster name
        """
        # Check if credentials and region have been provided in parallelcluster config
        self.aws_access_key_id = None
        self.aws_secret_access_key = None
        self.region = None
        self.env_blacklist = None
        parallelcluster_config_file = default_config_file_path()
        if os.path.isfile(parallelcluster_config_file):
            self.__init_from_parallelcluster_config(parallelcluster_config_file, log)

        # search for awsbatch-cli config
        cli_config_file = os.path.expanduser(os.path.join("~", ".parallelcluster", "awsbatch-cli.cfg"))
        if os.path.isfile(cli_config_file):
            self.__init_from_config(cli_config_file, cluster, log)
        elif cluster:
            self.__init_from_stack(cluster, log)

        else:
            fail("Error: cluster parameter is required")

        self.__verify_initialization(log)

    def __str__(self):
        return "{0}({1})".format(
            self.__class__.__name__, hide_keys(self.__dict__, ["aws_access_key_id", "aws_secret_access_key"])
        )

    def __verify_initialization(self, log):
        try:
            log.debug("stack_name = %s", self.stack_name)
            log.debug("region = %s", self.region)
            log.debug("s3_bucket = %s", self.s3_bucket)
            log.debug("compute_environment = %s", self.compute_environment)
            log.debug("job_queue = %s", self.job_queue)
            log.debug("job_definition = %s", self.job_definition)
            log.debug("master_ip = %s", self.head_node_ip)
            log.info(self)
        except AttributeError as e:
            fail(
                "Error getting cluster information from AWS CloudFormation."
                "Missing attribute (%s) from the output CloudFormation stack." % e
            )

    def __init_from_parallelcluster_config(self, parallelcluster_config_file, log):
        """
        Init credentials object attributes from aws-parallelcluster configuration file.

        :param parallelcluster_config_file: aws-parallelcluster config
        :param log: log
        """
        with open(parallelcluster_config_file) as config_file:
            parallelcluster_config = ConfigParser()
            parallelcluster_config.read_file(config_file)
            log.info(
                "Looking for AWS credentials and region in the AWS ParallelCluster configuration file %s"
                % parallelcluster_config_file
            )
            try:
                self.aws_access_key_id = parallelcluster_config.get("aws", "aws_access_key_id")
            except (NoOptionError, NoSectionError):
                pass
            try:
                self.aws_secret_access_key = parallelcluster_config.get("aws", "aws_secret_access_key")
            except (NoOptionError, NoSectionError):
                pass
            try:
                self.region = parallelcluster_config.get("aws", "aws_region_name")
            except (NoOptionError, NoSectionError):
                pass

    def __init_from_config(self, cli_config_file, cluster, log):  # noqa: C901 FIXME
        """
        Init object attributes from awsbatch-cli configuration file.

        :param cli_config_file: awsbatch-cli config
        :param cluster: cluster name
        :param log: log
        """
        with open(cli_config_file) as config_file:
            log.info("Searching for configuration file %s" % cli_config_file)
            config = ConfigParser()
            config.read_file(config_file)

            # use cluster if there or search for default value in [main] section of the config file
            try:
                cluster_name = cluster if cluster else config.get("main", "cluster_name")
            except NoSectionError as e:
                fail("Error getting the section [%s] from the configuration file (%s)" % (e.section, cli_config_file))
            except NoOptionError as e:
                fail(
                    "Error getting the option (%s) from the section [%s] of the configuration file (%s)"
                    % (e.option, e.section, cli_config_file)
                )
            cluster_section = "cluster {0}".format(cluster_name)
            try:
                self.region = config.get("main", "region")
            except NoOptionError:
                pass
            try:
                self.env_blacklist = config.get("main", "env_blacklist")
            except NoOptionError:
                pass

            try:
                self.stack_name = _get_stack_name(cluster_name)
                log.info("Stack name is (%s)" % self.stack_name)
                # if region is set for the current stack, override the region from the AWS ParallelCluster config file
                # or the region from the [main] section
                self.region = config.get(cluster_section, "region")
                self.s3_bucket = config.get(cluster_section, "s3_bucket")
                self.artifact_directory = config.get(cluster_section, "artifact_directory")
                self.compute_environment = config.get(cluster_section, "compute_environment")
                self.job_queue = config.get(cluster_section, "job_queue")
                self.job_definition = config.get(cluster_section, "job_definition")
                try:
                    self.job_definition_mnp = config.get(cluster_section, "job_definition_mnp")
                except NoOptionError:
                    pass
                self.head_node_ip = config.get(cluster_section, "master_ip")

                # get proxy
                self.proxy = config.get(cluster_section, "proxy")
                if not self.proxy == "NONE":
                    log.info("Configured proxy is: %s" % self.proxy)
            except NoSectionError:
                # initialize by getting stack info
                self.__init_from_stack(cluster_name, log)
            except NoOptionError as e:
                fail(
                    "Error getting the option (%s) from the section [%s] of the configuration file (%s)"
                    % (e.option, e.section, cli_config_file)
                )

    def __init_from_stack(self, cluster, log):  # noqa: C901 FIXME
        """
        Init object attributes by asking to the stack.

        :param cluster: cluster name
        :param log: log
        """
        try:
            self.stack_name = _get_stack_name(cluster)
            log.info("Describing stack (%s)" % self.stack_name)
            # get required values from the output of the describe-stack command
            # don't use proxy because we are in the client and use default region
            boto3_factory = Boto3ClientFactory(
                region=self.region,
                aws_access_key_id=self.aws_access_key_id,
                aws_secret_access_key=self.aws_secret_access_key,
            )
            cfn_client = boto3_factory.get_client("cloudformation")
            stack = cfn_client.describe_stacks(StackName=self.stack_name).get("Stacks")[0]
            log.debug(stack)
            if self.region is None:
                self.region = get_region_by_stack_id(stack.get("StackId"))
            self.proxy = "NONE"

            stack_status = stack.get("StackStatus")
            if stack_status in ["CREATE_COMPLETE", "UPDATE_COMPLETE"]:
                for output in stack.get("Outputs", []):
                    output_key = output.get("OutputKey")
                    output_value = output.get("OutputValue")
                    if output_key == "ResourcesS3Bucket":
                        self.s3_bucket = output_value
                    elif output_key == "ArtifactS3RootDirectory":
                        self.artifact_directory = output_value
                    elif output_key == "BatchComputeEnvironmentArn":
                        self.compute_environment = output_value
                    elif output_key == "BatchJobQueueArn":
                        self.job_queue = output_value
                    elif output_key == "BatchJobDefinitionArn":
                        self.job_definition = output_value
                    elif output_key == "MasterPrivateIP":
                        self.head_node_ip = output_value
                    elif output_key == "BatchJobDefinitionMnpArn":
                        self.job_definition_mnp = output_value

                for parameter in stack.get("Parameters", []):
                    if parameter.get("ParameterKey") == "ProxyServer":
                        self.proxy = parameter.get("ParameterValue")
                        if not self.proxy == "NONE":
                            log.info("Configured proxy is: %s" % self.proxy)
                        break
            else:
                fail("The cluster is in the (%s) status." % stack_status)

        except (ClientError, ParamValidationError) as e:
            fail("Error getting cluster information from AWS CloudFormation. Failed with exception: %s" % e)


def config_logger(log_level):
    """
    Define a logger for aws-parallelcluster-awsbatch-cli.

    :param log_level logging level
    :return: the logger
    """
    try:
        logfile = os.path.expanduser(os.path.join("~", ".parallelcluster", "awsbatch-cli.log"))
        logdir = os.path.dirname(logfile)
        os.makedirs(logdir)
    except OSError as e:
        if e.errno == errno.EEXIST and os.path.isdir(logdir):
            pass
        else:
            fail("Cannot create log file (%s). Failed with exception: %s" % (logfile, e))

    formatter = logging.Formatter("%(asctime)s %(levelname)s [%(module)s:%(funcName)s] %(message)s")

    logfile_handler = RotatingFileHandler(logfile, maxBytes=5 * 1024 * 1024, backupCount=1)
    logfile_handler.setFormatter(formatter)

    logger = logging.getLogger("awsbatch-cli")
    logger.addHandler(logfile_handler)
    try:
        logger.setLevel(log_level.upper())
    except (TypeError, ValueError) as e:
        fail("Error setting log level. Failed with exception: %s" % e)

    return logger
