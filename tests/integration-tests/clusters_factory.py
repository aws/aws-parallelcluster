import logging

from retrying import retry

from utils import random_alphanumeric, retry_if_subprocess_error, run_command


class ClustersFactory:
    """Manage creation and destruction of pcluster clusters."""

    def __init__(self, test_name=None):
        self.test_name = test_name
        self._created_clusters = {}

    def create_cluster(self, config, name=None):
        """
        Create a cluster with a given config.
        :param config: config file to use for cluster creation.
        :param name: name of the cluster. If not specified it defaults to "integ-tests-" + random_alphanumeric()
        :return:
        """
        if not name:
            name = "integ-tests-" + random_alphanumeric()

        if name in self._created_clusters:
            raise ValueError("Cluster {0} already exists".format(name))

        # create the cluster
        logging.info("Creating cluster {0} with config {1}".format(name, config))
        self._created_clusters[name] = config
        run_command(["pcluster", "create", "--config", config, name])
        logging.info("Cluster {0} created successfully".format(name))

    @retry(stop_max_attempt_number=10, wait_fixed=5000, retry_on_exception=retry_if_subprocess_error)
    def destroy_cluster(self, name):
        """Destroy a created cluster."""
        logging.info("Destroying cluster {0}".format(name))
        if name in self._created_clusters:
            config = self._created_clusters[name]

            # destroy the cluster
            run_command(["pcluster", "delete", "--config", config, name])
            del self._created_clusters[name]
            logging.info("Cluster {0} deleted successfully".format(name))
        else:
            logging.warning("Couldn't find cluster with name {0}. Skipping deletion.".format(name))

    def destroy_all_clusters(self):
        """Destroy all created clusters."""
        logging.debug("Destroying all clusters")
        for key in list(self._created_clusters.keys()):
            try:
                self.destroy_cluster(key)
            except Exception as e:
                logging.error("Failed when destroying cluster {0} with exception {1}.".format(key, e))
