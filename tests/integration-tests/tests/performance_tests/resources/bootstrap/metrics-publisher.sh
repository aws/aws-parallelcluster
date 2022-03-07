#!/bin/bash
set -e

# Cluster variables
source /etc/parallelcluster/cfnconfig
SHARED_DIR="$(echo $cfn_ebs_shared_dirs | cut -d ',' -f 1)"
CLUSTER_NAME="${stack_name:?}"
AWS_DEFAULT_REGION="${cfn_region:?}"

# Load libraries
source "${SHARED_DIR}/assets/lib/functions.sh"

CW_NAMESPACE="ParallelCluster/PerformanceTests"
CW_DIMENSIONS="ClusterName=${CLUSTER_NAME}"
PCLUSTER="/usr/local/bin/pcluster"
SQUEUE="/opt/slurm/bin/squeue"

function publish_metric () {
  local metric_name="$1"
  local metric_value="$2"

  put_metric ${AWS_DEFAULT_REGION} ${CW_NAMESPACE} "${CW_DIMENSIONS}" "${metric_name}" "${metric_value}"
}

log "Publishing metrics for cluster ${CLUSTER_NAME} in region ${AWS_DEFAULT_REGION} to CloudWatch namespace ${CW_NAMESPACE}"

NUM_COMPUTE_NODES=$(${PCLUSTER} describe-cluster-instances --region ${AWS_DEFAULT_REGION} --cluster-name "$CLUSTER_NAME" --query 'instances[].nodeType'  | grep -o ComputeNode  | wc -l)
publish_metric "ComputeNodeCount" "${NUM_COMPUTE_NODES}"

NUM_JOBS_QUEUED=$(${SQUEUE} -h | wc -l)
publish_metric "JobsQueuedCount" "${NUM_JOBS_QUEUED}"

NUM_JOBS_PENDING=$(${SQUEUE} -h -t configuring,pending | wc -l)
publish_metric "JobsPendingCount" "${NUM_JOBS_PENDING}"

NUM_JOBS_RUNNING=$(${SQUEUE} -h -t running | wc -l)
publish_metric "JobsRunningCount" "${NUM_JOBS_RUNNING}"

NUM_JOBS_FAILED=$(${SQUEUE} -h -t failed | wc -l)
publish_metric "JobsFailedCount" "${NUM_JOBS_FAILED}"

log "Published metrics for cluster ${CLUSTER_NAME} in region ${AWS_DEFAULT_REGION} to CloudWatch namespace ${CW_NAMESPACE}"
