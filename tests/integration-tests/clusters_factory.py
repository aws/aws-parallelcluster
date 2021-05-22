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
import re
import subprocess
import time

import boto3
import yaml
from retrying import retry
from utils import (
    retrieve_cfn_outputs,
    retrieve_cfn_parameters,
    retrieve_cfn_resources,
    retry_if_subprocess_error,
    run_command,
)


class Cluster:
    """Contain all static and dynamic data related to a cluster instance."""

    def __init__(self, name, ssh_key, config_file, region):
        self.name = name
        self.config_file = config_file
        self.ssh_key = ssh_key
        self.region = region
        with open(config_file) as conf_file:
            self.config = yaml.load(conf_file, Loader=yaml.SafeLoader)
        self.has_been_deleted = False
        self.create_complete = False
        self.__cfn_parameters = None
        self.__cfn_outputs = None
        self.__cfn_resources = None

    def __repr__(self):
        attrs = ", ".join(["{key}={value}".format(key=key, value=repr(value)) for key, value in self.__dict__.items()])
        return "{class_name}({attrs})".format(class_name=self.__class__.__name__, attrs=attrs)

    def update(self, force=True):
        """
        Update a cluster with an already updated config.
        :param force: if to use --force flag when update
        """
        # update the cluster
        logging.info("Updating cluster {0} with config {1}".format(self.name, self.config_file))
        command = ["pcluster", "update", "--config", self.config_file]
        if force:
            command.append("--force")
        command.append(self.name)
        result = run_command(command)
        if "Status: {0} - UPDATE_COMPLETE".format(self.cfn_name) not in result.stdout:
            error = "Cluster update failed for {0} with output: {1}".format(self.name, result.stdout)
            logging.error(error)
            raise Exception(error)
        logging.info("Cluster {0} updated successfully".format(self.name))

        # reset cached properties
        self._reset_cached_properties()

        return result

    def delete(self, keep_logs=False):
        """Delete this cluster."""
        if self.has_been_deleted:
            return
        cmd_args = ["pcluster", "delete", self.name]
        if keep_logs:
            logging.warning("CloudWatch logs for cluster %s are preserved due to failure.", self.name)
            cmd_args.append("--keep-logs")
        try:
            result = run_command(cmd_args, log_error=False)
            if "DELETE_FAILED" in result.stdout:
                error = "Cluster deletion failed for {0} with output: {1}".format(self.name, result.stdout)
                logging.error(error)
                raise Exception(error)
            logging.info("Cluster {0} deleted successfully".format(self.name))
        except subprocess.CalledProcessError as e:
            if re.search(r"Stack with id parallelcluster-.+ does not exist", e.stdout):
                pass
            else:
                logging.error("Failed destroying cluster with with error:\n%s\nand output:\n%s", e.stderr, e.stdout)
                raise
        self.has_been_deleted = True

    def start(self):
        """Run pcluster start and return the result."""
        cmd_args = ["pcluster", "start", self.name]
        try:
            result = run_command(cmd_args, log_error=False)
            logging.info("Cluster {0} started successfully".format(self.name))
            return result.stdout
        except subprocess.CalledProcessError as e:
            logging.error("Failed starting cluster with with error:\n%s\nand output:\n%s", e.stderr, e.stdout)
            raise

    def stop(self):
        """Run pcluster stop and return the result."""
        cmd_args = ["pcluster", "stop", self.name]
        try:
            result = run_command(cmd_args, log_error=False)
            logging.info("Cluster {0} stopped successfully".format(self.name))
            return result.stdout
        except subprocess.CalledProcessError as e:
            logging.error("Failed stopping cluster with with error:\n%s\nand output:\n%s", e.stderr, e.stdout)
            raise

    def status(self):
        """Run pcluster stop and return the result."""
        cmd_args = ["pcluster", "status", self.name]
        try:
            result = run_command(cmd_args, log_error=False)
            logging.info("Get cluster {0} status successfully".format(self.name))
            return result.stdout
        except subprocess.CalledProcessError as e:
            logging.error(
                "Failed when getting cluster status with with error:\n%s\nand output:\n%s", e.stderr, e.stdout
            )
            raise

    def instances(self, desired_instance_role=None):
        """Run pcluster instances and return the result."""
        if desired_instance_role and desired_instance_role not in ("HeadNode", "Compute"):
            raise ValueError
        cmd_args = ["pcluster", "instances", self.name]
        try:
            result = run_command(cmd_args, log_error=False)
            logging.info("Get cluster {0} instances successfully".format(self.name))
            cluster_instances = []
            for entry in result.stdout.splitlines():
                instance_role, instance_id = re.split("\t", entry)
                instance_id = instance_id.strip()
                if not desired_instance_role or desired_instance_role == instance_role:
                    cluster_instances.append(instance_id)
            return cluster_instances
        except subprocess.CalledProcessError as e:
            logging.error(
                "Failed when getting cluster instances with with error:\n%s\nand output:\n%s", e.stderr, e.stdout
            )
            raise

    @property
    def cfn_name(self):
        """Return the name of the CloudFormation stack associated to the cluster."""
        return "parallelcluster-" + self.name

    @property
    def head_node_ip(self):
        """Return the public ip of the cluster head node."""
        if "HeadNodePublicIP" in self.cfn_outputs:
            return self.cfn_outputs["HeadNodePublicIP"]
        else:
            ec2 = boto3.client("ec2")
            filters = [
                {"Name": "tag:parallelcluster:application", "Values": [self.cfn_name]},
                {"Name": "instance-state-name", "Values": ["running"]},
                {"Name": "tag:parallelcluster:node-type", "Values": ["HeadNode"]},
            ]
            instance = ec2.describe_instances(Filters=filters).get("Reservations")[0].get("Instances")[0]
            return (
                instance.get("PublicIpAddress") if instance.get("PublicIpAddress") else instance.get("PrivateIpAddress")
            )

    @property
    def os(self):
        """Return the os used for the cluster."""
        return self.config["Image"]["Os"]

    @property
    def cfn_parameters(self):
        """
        Return the CloudFormation stack parameters for the cluster.
        Parameters are retrieved only once and then cached.
        """
        if not self.__cfn_parameters:
            self.__cfn_parameters = retrieve_cfn_parameters(self.cfn_name, self.region)
        return self.__cfn_parameters

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

    def _reset_cached_properties(self):
        """Discard cached data."""
        self.__cfn_parameters = None
        self.__cfn_outputs = None
        self.__cfn_resources = None


class ClustersFactory:
    """Manage creation and destruction of pcluster clusters."""

    def __init__(self, keep_logs_on_failure=False):
        self.__created_clusters = {}
        self._keep_logs_on_failure = keep_logs_on_failure

    def create_cluster(self, cluster, extra_args=None, raise_on_error=True):
        """
        Create a cluster with a given config.
        :param cluster: cluster to create.
        :param extra_args: list of strings; extra args to pass to `pcluster create`
        :param raise_on_error: raise exception if cluster creation fails
        """
        name = cluster.name
        config = cluster.config_file
        if name in self.__created_clusters:
            raise ValueError("Cluster {0} already exists".format(name))

        # create the cluster
        logging.info("Creating cluster {0} with config {1}".format(name, config))
        self.__created_clusters[name] = cluster
        create_cmd_args = ["pcluster", "create", "--norollback", "--config", config]
        if extra_args:
            create_cmd_args.extend(extra_args)
        create_cmd_args.append(name)
        result = run_command(
            create_cmd_args,
            timeout=7200,
            raise_on_error=raise_on_error,
        )
        if "Status: {0} - CREATE_COMPLETE".format(cluster.cfn_name) not in result.stdout:
            error = "Cluster creation failed for {0} with output: {1}".format(name, result.stdout)
            logging.error(error)
            if raise_on_error:
                raise Exception(error)
        elif "WARNING" in result.stdout:
            error = "Cluster creation for {0} generated a warning: {1}".format(name, result.stdout)
            logging.warning(error)
        logging.info("Cluster {0} created successfully".format(name))
        cluster.create_complete = True

        # FIXME: temporary workaround since in certain circumstances the cluster isn't ready for
        # job submission right after creation. We need to investigate this further.
        logging.info("Sleeping for 30 seconds in case cluster is not ready yet")
        time.sleep(30)

    @retry(stop_max_attempt_number=5, wait_fixed=5000, retry_on_exception=retry_if_subprocess_error)
    def destroy_cluster(self, name, keep_logs=False):
        """Destroy a created cluster."""
        logging.info("Destroying cluster {0}".format(name))
        if name in self.__created_clusters:
            keep_logs = keep_logs or (self._keep_logs_on_failure and not self.__created_clusters[name].create_complete)
            try:
                self.__created_clusters[name].delete(keep_logs=keep_logs)
            except subprocess.CalledProcessError as e:
                logging.error(
                    "Failed when deleting cluster %s with error %s. Retrying deletion without --keep-logs.", name, e
                )
                self.__created_clusters[name].delete(keep_logs=False)
            del self.__created_clusters[name]
            logging.info("Cluster {0} deleted successfully".format(name))
        else:
            logging.warning("Couldn't find cluster with name {0}. Skipping deletion.".format(name))

    def destroy_all_clusters(self, keep_logs=False):
        """Destroy all created clusters."""
        logging.debug("Destroying all clusters")
        for key in list(self.__created_clusters.keys()):
            try:
                self.destroy_cluster(key, keep_logs)
            except Exception as e:
                logging.error("Failed when destroying cluster {0} with exception {1}.".format(key, e))
