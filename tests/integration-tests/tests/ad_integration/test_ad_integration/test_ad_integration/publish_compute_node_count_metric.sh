#!/bin/bash
set -ex

# shellcheck source=/dev/null
source /etc/parallelcluster/cfnconfig
CLUSTER_NAME="${stack_name:?}"
AWS_DEFAULT_REGION="${cfn_region:?}"

NUM_COMPUTE_NODES=$(/opt/slurm/bin/sinfo --Node --noheader | awk '{print $1,$4}' | grep -cEv '(~|#|%)$')
aws cloudwatch put-metric-data \
    --region "$AWS_DEFAULT_REGION" \
    --namespace 'ParallelCluster/AdIntegration' \
    --metric-name 'ComputeNodeCount' \
    --dimensions "ClusterName=${CLUSTER_NAME}" \
    --value "$NUM_COMPUTE_NODES"