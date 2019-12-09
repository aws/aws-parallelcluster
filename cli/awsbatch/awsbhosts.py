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
    parser = argparse.ArgumentParser(description="Shows the hosts belonging to the cluster's Compute Environment.")
    parser.add_argument("-c", "--cluster", help="Cluster to use")
    parser.add_argument("-d", "--details", help="Show hosts details", action="store_true")
    parser.add_argument("-ll", "--log-level", help=argparse.SUPPRESS, default="ERROR")
    parser.add_argument(
        "instance_ids",
        help="A space separated list of instances IDs. If a single instance is "
        "requested it will be shown in a detailed version",
        nargs="*",
    )
    return parser


class Host(object):
    """Generic host object."""

    def __init__(
        self,
        container_instance_arn,
        status,
        ec2_instance,
        instance_type,
        private_ip_address,
        public_ip_address,
        private_dns_name,
        public_dns_name,
        running_jobs,
        pending_jobs,
        cpu_registered,
        mem_registered,
        cpu_avail,
        mem_avail,
    ):
        """Initialize the object."""
        self.container_instance_arn = container_instance_arn
        self.status = status
        self.ec2_instance = ec2_instance
        self.instance_type = instance_type
        self.private_ip_address = private_ip_address
        self.public_ip_address = public_ip_address
        self.private_dns_name = private_dns_name
        self.public_dns_name = public_dns_name
        self.running_jobs = running_jobs
        self.pending_jobs = pending_jobs
        self.cpu_registered = cpu_registered
        self.mem_registered = mem_registered
        self.cpu_avail = cpu_avail
        self.mem_avail = mem_avail


class AWSBhostsCommand(object):
    """awsbhosts command."""

    def __init__(self, log, boto3_factory):
        """
        Initialize the object.

        :param log: log
        :param boto3_factory: an initialized Boto3ClientFactory object
        """
        self.log = log
        mapping = collections.OrderedDict(
            [
                ("ec2InstanceId", "ec2_instance"),
                ("containerInstanceArn", "container_instance_arn"),
                ("status", "status"),
                ("instanceType", "instance_type"),
                ("privateIpAddress", "private_ip_address"),
                ("publicIpAddress", "public_ip_address"),
                ("privateDnsName", "private_dns_name"),
                ("publicDnsName", "public_dns_name"),
                ("runningJobs", "running_jobs"),
                ("pendingJobs", "pending_jobs"),
                ("registeredCPUs", "cpu_registered"),
                ("registeredMemory[MB]", "mem_registered"),
                ("availableCPUs", "cpu_avail"),
                ("availableMemory[MB]", "mem_avail"),
            ]
        )
        self.output = Output(mapping=mapping)
        self.boto3_factory = boto3_factory
        self.ecs_client = boto3_factory.get_client("ecs")

    def run(self, compute_environments, show_details=False, instance_ids=None):
        """
        Print list of hosts associated to the compute environments.

        :param compute_environments: a list of compute environments
        :param show_details: show compute environment details
        :param instance_ids: instances to query
        """
        self.__init_output(compute_environments, instance_ids)
        if show_details or instance_ids:
            self.output.show()
        else:
            self.output.show_table(
                ["ec2InstanceId", "instanceType", "privateIpAddress", "publicIpAddress", "runningJobs"]
            )

    def __init_output(self, compute_environments, instance_ids=None):
        """
        Initialize host output by asking hosts associated to the given compute environments.

        :param compute_environments: a list of compute environments
        :param instance_ids: requested hosts
        """
        ecs_clusters = self.__get_ecs_clusters(compute_environments)
        try:
            for ecs_cluster in ecs_clusters:
                self.log.info("Cluster ARN = %s" % ecs_cluster)
                paginator = self.ecs_client.get_paginator("list_container_instances")
                for page in paginator.paginate(cluster=ecs_cluster):
                    self._add_host_items(ecs_cluster, page["containerInstanceArns"], instance_ids)
        except Exception as e:
            fail("Error listing container instances from AWS ECS. Failed with exception: %s" % e)

    @staticmethod
    def __create_host_item(container_instance, ec2_instance):
        """
        Merge container instance and ec2 instance information and create a Host item.

        :param container_instance: the containerInstance object to parse
        :param ec2_instance: the ec2Instance object to parse
        :return: the Host item
        """
        try:
            instance_type = AWSBhostsCommand.__get_instance_attribute(
                container_instance["attributes"], "ecs.instance-type"
            )
            cpu_registered, mem_registered = AWSBhostsCommand.__get_cpu_and_memory(
                container_instance["registeredResources"]
            )
            cpu_avail, mem_avail = AWSBhostsCommand.__get_cpu_and_memory(container_instance["remainingResources"])
            return Host(
                container_instance_arn=container_instance["containerInstanceArn"],
                status=container_instance["status"],
                ec2_instance=container_instance["ec2InstanceId"],
                instance_type=instance_type,
                private_ip_address=ec2_instance["PrivateIpAddress"],
                public_ip_address=ec2_instance["PublicIpAddress"] if ec2_instance.get("PublicIpAddress") else "-",
                private_dns_name=ec2_instance["PrivateDnsName"],
                public_dns_name=ec2_instance["PublicDnsName"] if ec2_instance.get("PublicDnsName") else "-",
                running_jobs=container_instance["runningTasksCount"],
                pending_jobs=container_instance["pendingTasksCount"],
                cpu_registered=cpu_registered,
                mem_registered=mem_registered,
                cpu_avail=cpu_avail,
                mem_avail=mem_avail,
            )
        except KeyError as e:
            fail("Error building Host item. Key (%s) not found." % e)

    @staticmethod
    def __get_instance_attribute(attributes, attribute_name):
        """
        Get container instance attribute by name.

        :param attributes: list of attributes
        :param attribute_name: name of the attribute
        :return: the attribute value
        """
        attr_value = "-"
        for attr in attributes:
            if attr["name"] == attribute_name:
                attr_value = attr["value"]
                break
        return attr_value

    @staticmethod
    def __get_cpu_and_memory(resources):
        """
        Get CPU and MEMORY information from given resources object.

        :param resources: resources json object
        :return: cpu and memory
        """
        cpu = "-"
        memory = "-"
        for resource in resources:
            if resource["name"] == "CPU":
                cpu = resource["integerValue"] / 1024
            elif resource["name"] == "MEMORY":
                memory = resource["integerValue"]
        return cpu, memory

    def _add_host_items(self, ecs_cluster_arn, container_instances_arns, instance_ids=None):
        """
        Add a list of Hosts to the output.

        :param ecs_cluster_arn: ECS Cluster arn
        :param container_instances_arns: container ids
        :param instance_ids: hosts requested
        """
        self.log.info("Container ARNs = %s" % container_instances_arns)
        if container_instances_arns:
            response = self.ecs_client.describe_container_instances(
                cluster=ecs_cluster_arn, containerInstances=container_instances_arns
            )
            container_instances = response["containerInstances"]
            self.log.debug("Container Instances = %s" % container_instances)
            # get ec2_instance_ids
            ec2_instances_ids = []
            for container_instance in container_instances:
                ec2_instances_ids.append(container_instance["ec2InstanceId"])

            # get ec2 instances information
            ec2_instances = {}
            try:
                ec2_client = self.boto3_factory.get_client("ec2")
                paginator = ec2_client.get_paginator("describe_instances")
                for page in paginator.paginate(InstanceIds=ec2_instances_ids):
                    for reservation in page["Reservations"]:
                        for instance in reservation["Instances"]:
                            ec2_instances[instance["InstanceId"]] = instance
            except Exception as e:
                fail("Error listing EC2 instances from AWS EC2. Failed with exception: %s" % e)

            # merge ec2 and container information
            for container_instance in container_instances:
                ec2_instance_id = container_instance["ec2InstanceId"]
                # filter by instance_id if there
                if not instance_ids or ec2_instance_id in instance_ids:
                    self.log.debug("Container Instance = %s" % container_instance)
                    self.log.debug("EC2 Instance = %s" % ec2_instances[ec2_instance_id])
                    self.output.add(self.__create_host_item(container_instance, ec2_instances[ec2_instance_id]))

    @staticmethod
    def __get_clusters(compute_environments):
        """
        Parse computeEnvironments object and return a list of ecsClusterArn.

        :param compute_environments: a list of Compute Environments
        :return: a list of ECS clusters
        """
        ecs_clusters = []
        for compute_env in compute_environments:
            ecs_clusters.append(compute_env["ecsClusterArn"])
        return ecs_clusters

    def __get_ecs_clusters(self, compute_environments):
        """
        Get Compute Environments from AWS Batch and create a list of ECS Cluster ARNs.

        :param compute_environments: compute environments to query
        :return: a list of ECS clusters
        """
        ecs_clusters = []
        try:
            # connect to batch and ask for compute environments
            batch_client = self.boto3_factory.get_client("batch")
            next_token = ""
            while next_token is not None:
                response = batch_client.describe_compute_environments(
                    computeEnvironments=compute_environments, nextToken=next_token
                )
                ecs_clusters.extend(self.__get_clusters(response["computeEnvironments"]))
                next_token = response.get("nextToken")
        except Exception as e:
            fail("Error listing compute environments from AWS Batch. Failed with exception: %s" % e)

        return ecs_clusters


def main():
    """Command entrypoint."""
    try:
        # parse input parameters and  config file
        args = _get_parser().parse_args()
        log = config_logger(args.log_level)
        log.info("Input parameters: %s" % args)
        config = AWSBatchCliConfig(log, args.cluster)
        boto3_factory = Boto3ClientFactory(
            region=config.region,
            proxy=config.proxy,
            aws_access_key_id=config.aws_access_key_id,
            aws_secret_access_key=config.aws_secret_access_key,
        )

        AWSBhostsCommand(log, boto3_factory).run(
            compute_environments=[config.compute_environment], instance_ids=args.instance_ids, show_details=args.details
        )

    except KeyboardInterrupt:
        print("Exiting...")
        sys.exit(0)
    except Exception as e:
        fail("Unexpected error. Command failed with exception: %s" % e)


if __name__ == "__main__":
    main()
