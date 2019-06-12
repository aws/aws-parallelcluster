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
import logging
import time

import boto3
import configparser
from retrying import retry

from utils import retrieve_cfn_outputs, retrieve_cfn_resources, retry_if_subprocess_error, run_command


class Cluster:
    """Contain all static and dynamic data related to a cluster instance."""

    def __init__(self, name, ssh_key, config_file):
        self.name = name
        self.config_file = config_file
        self.ssh_key = ssh_key
        self.config = configparser.ConfigParser()
        self.config.read(config_file)
        self.__cfn_outputs = None
        self.__cfn_resources = None

    def update(self, reset_desired=False, extra_params=None):
        """
        Update a cluster with an already updated config.
        :param reset_desired: reset the current ASG desired capacity to initial config values
        :param extra_params: extra parameters to pass to stack update
        """
        # update the cluster
        logging.info("Updating cluster {0} with config {1}".format(self.name, self.config_file))
        command = ["pcluster", "update", "--config", self.config_file]
        if reset_desired:
            command.append("--reset-desired")
        if extra_params:
            command.extend(["--extra-parameters", extra_params])
        command.append(self.name)
        result = run_command(command)
        if "Status: {0} - UPDATE_COMPLETE".format(self.cfn_name) not in result.stdout:
            error = "Cluster update failed for {0} with output: {1}".format(self.name, result.stdout)
            logging.error(error)
            raise Exception(error)
        logging.info("Cluster {0} updated successfully".format(self.name))

        # reset cached properties
        self.__cfn_outputs = None
        self.__cfn_resources = None

    @property
    def cfn_name(self):
        """Return the name of the CloudFormation stack associated to the cluster."""
        return "parallelcluster-" + self.name

    @property
    def region(self):
        """Return the aws region the cluster is created in."""
        return self.config.get("aws", "aws_region_name", fallback="us-east-1")

    @property
    def master_ip(self):
        """Return the public ip of the cluster master node."""
        if "MasterPublicIP" in self.cfn_outputs:
            return self.cfn_outputs["MasterPublicIP"]
        else:
            ec2 = boto3.client("ec2", region_name=self.region)
            master_server = self.cfn_resources["MasterServer"]
            instance = ec2.describe_instances(InstanceIds=[master_server]).get("Reservations")[0].get("Instances")[0]
            return instance.get("PublicIpAddress")

    @property
    def os(self):
        """Return the os used for the cluster."""
        cluster_template = self.config.get("global", "cluster_template", fallback="default")
        return self.config.get("cluster {0}".format(cluster_template), "base_os", fallback="alinux")

    @property
    def asg(self):
        """Return the asg name for the ComputeFleet."""
        return self.cfn_resources["ComputeFleet"]

    @property
    def cfn_outputs(self):
        """
        Return the CloudFormation stack outputs for the cluster.
        Outputs are retrieved only once and then cached.
        """
        if not self.__cfn_outputs:
            self.__cfn_outputs = retrieve_cfn_outputs(self.cfn_name, self.region)
        return self.__cfn_outputs

    @property
    def cfn_resources(self):
        """
        Return the CloudFormation stack resources for the cluster.
        Resources are retrieved only once and then cached.
        """
        if not self.__cfn_resources:
            self.__cfn_resources = retrieve_cfn_resources(self.cfn_name, self.region)
        return self.__cfn_resources


class ClustersFactory:
    """Manage creation and destruction of pcluster clusters."""

    def __init__(self):
        self.__created_clusters = {}

    def create_cluster(self, cluster):
        """
        Create a cluster with a given config.
        :param cluster: cluster to create.
        """
        name = cluster.name
        config = cluster.config_file
        if name in self.__created_clusters:
            raise ValueError("Cluster {0} already exists".format(name))

        # create the cluster
        logging.info("Creating cluster {0} with config {1}".format(name, config))
        self.__created_clusters[name] = cluster
        result = run_command(["pcluster", "create", "--norollback", "--config", config, name])
        if "Status: {0} - CREATE_COMPLETE".format(cluster.cfn_name) not in result.stdout:
            error = "Cluster creation failed for {0} with output: {1}".format(name, result.stdout)
            logging.error(error)
            raise Exception(error)
        logging.info("Cluster {0} created successfully".format(name))

        # FIXME: temporary workaround since in certain circumstances the cluster isn't ready for
        # job submission right after creation. We need to investigate this further.
        logging.info("Sleeping for 60 seconds in case cluster is not ready yet")
        time.sleep(60)

    @retry(stop_max_attempt_number=10, wait_fixed=5000, retry_on_exception=retry_if_subprocess_error)
    def destroy_cluster(self, name):
        """Destroy a created cluster."""
        logging.info("Destroying cluster {0}".format(name))
        if name in self.__created_clusters:
            cluster = self.__created_clusters[name]

            # destroy the cluster
            result = run_command(["pcluster", "delete", "--config", cluster.config_file, name])
            if "DELETE_FAILED" in result.stdout:
                error = "Cluster deletion failed for {0} with output: {1}".format(name, result.stdout)
                logging.error(error)
                raise Exception(error)
            del self.__created_clusters[name]
            logging.info("Cluster {0} deleted successfully".format(name))
        else:
            logging.warning("Couldn't find cluster with name {0}. Skipping deletion.".format(name))

    def destroy_all_clusters(self):
        """Destroy all created clusters."""
        logging.debug("Destroying all clusters")
        for key in list(self.__created_clusters.keys()):
            try:
                self.destroy_cluster(key)
            except Exception as e:
                logging.error("Failed when destroying cluster {0} with exception {1}.".format(key, e))
