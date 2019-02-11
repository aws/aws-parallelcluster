import logging

import boto3
import configparser
from retrying import retry

from utils import random_alphanumeric, retry_if_subprocess_error, run_command


class Cluster:
    """Contain all static and dynamic data related to a cluster instance."""

    def __init__(self, name, config_file, ssh_key):
        self.name = name
        self.config_file = config_file
        self.ssh_key = ssh_key
        self.config = configparser.ConfigParser()
        self.config.read(config_file)
        self.__cfn_outputs = None

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
        return self.cfn_outputs["MasterPublicIP"]

    @property
    def os(self):
        """Return the os used for the cluster."""
        cluster_template = self.config.get("global", "cluster_template", fallback="default")
        return self.config.get("cluster {0}".format(cluster_template), "base_os", fallback="alinux")

    @property
    def cfn_outputs(self):
        """
        Return the CloudFormation stack outputs for the cluster.
        Outputs are retrieved only once and then cached.
        """
        if self.__cfn_outputs:
            return self.__cfn_outputs
        self.__cfn_outputs = self.__retrieve_cfn_outputs()
        return self.__cfn_outputs

    @retry(wait_exponential_multiplier=500, wait_exponential_max=5000, stop_max_attempt_number=5)
    def __retrieve_cfn_outputs(self):
        logging.debug("Retrieving stack outputs for stack {}".format(self.cfn_name))
        try:
            cfn = boto3.client("cloudformation", region_name=self.region)
            stack = cfn.describe_stacks(StackName=self.cfn_name).get("Stacks")[0]
            outputs = {}
            for output in stack.get("Outputs", []):
                outputs[output.get("OutputKey")] = output.get("OutputValue")
            return outputs
        except Exception as e:
            logging.warning("Failed retrieving stack outputs for stack {} with exception: {}".format(self.cfn_name, e))
            raise


class ClustersFactory:
    """Manage creation and destruction of pcluster clusters."""

    def __init__(self, ssh_key, test_name=None):
        self.__test_name = test_name
        self.__ssh_key = ssh_key
        self.__created_clusters = {}

    def create_cluster(self, config, name=None):
        """
        Create a cluster with a given config.
        :param config: config file to use for cluster creation.
        :param name: name of the cluster. If not specified it defaults to "integ-tests-" + random_alphanumeric()
        :return:
        """
        if not name:
            name = "integ-tests-" + random_alphanumeric()

        if name in self.__created_clusters:
            raise ValueError("Cluster {0} already exists".format(name))

        # create the cluster
        logging.info("Creating cluster {0} with config {1}".format(name, config))
        self.__created_clusters[name] = Cluster(name, config, self.__ssh_key)
        result = run_command(["pcluster", "create", "--config", config, name])
        if "CREATE_COMPLETE" not in result.stdout:
            error = "Cluster creation failed for {0} with output: {1}".format(name, result.stdout)
            logging.error(error)
            raise Exception(error)
        logging.info("Cluster {0} created successfully".format(name))
        return self.__created_clusters[name]

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
