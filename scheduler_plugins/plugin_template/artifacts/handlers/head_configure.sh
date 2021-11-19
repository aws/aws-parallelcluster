#!/bin/bash

### AVAILABLE ENV SET BY PARALLELCLUSTER
# - PCLUSTER_CLUSTER_CONFIG: path to a file containing the cluster configuration in a YAML format.
#   Changes to the content of this file are not preserved across handlers invocations.
# - PCLUSTER_LAUNCH_TEMPLATES: path to a JSON file containing the LaunchTemplate to use for each ComputeResource in each queue.
#   Changes to this file are not preserved across handlers invocations.
# - PCLUSTER_CLUSTER_NAME: Name of the cluster.
# - PCLUSTER_CFN_STACK_ARN: ARN of the CloudFormation stack associated with the cluster.
# - PCLUSTER_SCHEDULER_PLUGIN_CFN_SUBSTACK_ARN: ARN of the nested CloudFormation stack defining scheduler plugin custom resources.
# - PCLUSTER_SCHEDULER_PLUGIN_CFN_SUBSTACK_OUTPUTS: path to a JSON file containing a key value pair mapping of all outputs present in the CFN substack defined by the scheduler plugin.
#   Changes to this file are not preserved across handlers invocations.
# - PCLUSTER_SHARED_SCHEDULER_DIR: cluster shared dir to use when installing the scheduler or other packages (/opt/parallecluster/shared/byos)
# - PCLUSTER_LOCAL_SCHEDULER_DIR: local dir to use when installing the scheduler or other packages (/opt/parallecluster/byos)
# - PCLUSTER_AWS_REGION: AWS region name
# - PCLUSTER_EC2_INSTANCE_TYPE: type of the EC2 instance where the action is running
# - PCLUSTER_OS: OS distribution of the instance where the script is running
# - PCLUSTER_ARCH: architecture of the node: x86_64 or arm64
# - PCLUSTER_VERSION: version of ParallelCluster the cluster belongs to.
# - PCLUSTER_HEADNODE_PRIVATE_IP: private IP of the head node
# - PCLUSTER_HEADNODE_HOSTNAME: hostname of the head node
# - PCLUSTER_QUEUE_NAME: contains the name of the queue the node belongs to (empty in case of head node).
# - PCLUSTER_COMPUTE_RESOURCE_NAME: contains the name of the compute resource the node belongs to (empty in case of head node).
# - PCLUSTER_INSTANCE_TYPES_DATA: path to a JSON file containing the instance types data for the instances used in the queues
# - PCLUSTER_NODE_TYPE: type of the node: head or compute
##################################################################

set -e

echo "Handling event: HeadConfigure"
