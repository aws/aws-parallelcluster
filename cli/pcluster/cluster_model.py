# Copyright 2020 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
import abc
import sys
from abc import abstractmethod

import boto3
from botocore.exceptions import ClientError

from pcluster.utils import error, get_cfn_param, is_hit_enabled_cluster

if sys.version_info >= (3, 4):
    ABC = abc.ABC
else:
    ABC = abc.ABCMeta("ABC", (), {})


class ClusterModel(ABC):
    """
    Describes the model of the cluster produced by a configuration.

    The currently supported cluster models are:
    - SIT: Single Instance Type - One single queue and one instance type per queue
    - HIT: Heterogeneous Instance Types - Multiple queues and multiple instance types per queue
    """

    def __init__(self, name):
        self.name = name

    @abstractmethod
    def get_cluster_section_definition(self):
        """Get the cluster section definition used by the cluster model."""
        pass

    @abstractmethod
    def test_configuration(self, pcluster_config):
        """Do dryrun tests for the configuration."""
        pass

    def _ec2_run_instance(self, pcluster_config, **kwargs):
        """Wrap ec2 run_instance call. Useful since a successful run_instance call signals 'DryRunOperation'."""
        try:
            boto3.client("ec2").run_instances(**kwargs)
        except ClientError as e:
            code = e.response.get("Error").get("Code")
            message = e.response.get("Error").get("Message")
            if code == "DryRunOperation":
                pass
            elif code == "UnsupportedOperation":
                if "does not support specifying CpuOptions" in message:
                    pcluster_config.error(message.replace("CpuOptions", "disable_hyperthreading"))
                pcluster_config.error(message)
            elif code == "InstanceLimitExceeded":
                pcluster_config.error(
                    "You've reached the limit on the number of instances you can run concurrently "
                    "for the configured instance type.\n{0}".format(message)
                )
            elif code == "InsufficientInstanceCapacity":
                pcluster_config.error("There is not enough capacity to fulfill your request.\n{0}".format(message))
            elif code == "InsufficientFreeAddressesInSubnet":
                pcluster_config.error(
                    "The specified subnet does not contain enough free private IP addresses "
                    "to fulfill your request.\n{0}".format(message)
                )
            else:
                pcluster_config.error(
                    "Unable to validate configuration parameters. "
                    "Please double check your cluster configuration.\n{0}".format(message)
                )

    def _get_latest_alinux_ami_id(self):
        """Get latest alinux ami id."""
        try:
            alinux_ami_id = (
                boto3.client("ssm")
                .get_parameters_by_path(Path="/aws/service/ami-amazon-linux-latest")
                .get("Parameters")[0]
                .get("Value")
            )
        except ClientError as e:
            error("Unable to retrieve Amazon Linux AMI id.\n{0}".format(e.response.get("Error").get("Message")))
            raise

        return alinux_ami_id


def infer_cluster_model(config_parser=None, cluster_label=None, cfn_params=None):
    """
    Infer the cluster model from the provided configuration.

    The configuration can be provided as coming from CloudFormation (CfnParams) or from config_file, with cluster label
    and a config_parser instance.
    """
    return (
        _infer_cluster_model_from_cfn(cfn_params)
        if cfn_params
        else _infer_cluster_model_from_file(config_parser, cluster_label)
    )


def _infer_cluster_model_from_file(config_parser, cluster_label):
    """
    Infer the cluster model from the configuration file.

    SIT style config files are supported also with Slurm, so check is performed on queue_settings.
    """
    return (
        ClusterModel.HIT
        if config_parser.has_option("cluster {0}".format(cluster_label), "queue_settings")
        else ClusterModel.SIT
    )


def _infer_cluster_model_from_cfn(cfn_params):
    """
    Infer the cluster model from cfn params.

    Only HIT model is allowed to be stored if scheduler is Slurm, so checking the scheduler is enough to determine the
    cluster model.
    """
    return ClusterModel.HIT if is_hit_enabled_cluster(get_cfn_param(cfn_params, "Scheduler")) else ClusterModel.SIT


def get_cluster_model(name):
    """Get the cluster model by name."""
    # Simple binary check; no additional cluster models are expected in the next future.
    return ClusterModel.HIT if ClusterModel.HIT.name == name else ClusterModel.SIT


def load_cluster_models():
    """Load supported cluster models."""
    from pcluster.models.hit.hit_cluster_model import HITClusterModel
    from pcluster.models.sit.sit_cluster_model import SITClusterModel

    ClusterModel.HIT = HITClusterModel()
    ClusterModel.SIT = SITClusterModel()


load_cluster_models()
