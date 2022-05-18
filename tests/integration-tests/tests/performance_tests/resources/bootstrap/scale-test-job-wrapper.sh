#!/bin/bash
set -ex

# To submit this job, run:
# sbatch -n 16 /shared/assets/workloads/scale-test/scale-test-job-wrapper.sh [OUTPUT_DIR] [JOB_COMMAND]
# sbatch -n 16 /shared/assets/workloads/scale-test/scale-test-job-wrapper.sh /shared/scale-tests/scale-test-$(date +"%Y-%m-%dT%H-%M-%S") "/shared/assets/workloads/env-info.sh ; sleep 60"
# sbatch -n 16 /shared/assets/workloads/scale-test/scale-test-job-wrapper.sh /shared/scale-tests/scale-test-$(date +"%Y-%m-%dT%H-%M-%S") "sleep 120"
#
# Note: 16 processes = 4 compute nodes c5.xlarge having 4 vCPUs each

# Cluster variables
source /etc/parallelcluster/cfnconfig
SHARED_DIR="$(echo $cfn_ebs_shared_dirs | cut -d ',' -f 1)"

# Load libraries
FUNCTIONS_SCRIPT="${SHARED_DIR}/assets/lib/functions.sh"
source "${FUNCTIONS_SCRIPT}"

# Input
OUTPUT_DIR="${1}"
JOB_COMMAND="${2:-"sleep 60"}"

# Scale Test - Directories and Files
JOB_METRICS_FILE="${OUTPUT_DIR}/job.${SLURM_JOB_ID}.sample.json"
mkdir -m 777 -p $(dirname ${JOB_METRICS_FILE})

# Scale Test - Instance Info
INSTANCE_ID=$(get_instance_id)
INSTANCE_METRICS_FILE="${SHARED_DIR}/metrics/compute-nodes/instance-${INSTANCE_ID}.json"
for metric in "instancePreInstallTimestamp" "instancePreInstallUpTime" "instancePostInstallTimestamp" "instancePostInstallUpTime" "instanceId"; do
  add_to_json "leaderComputeNode.${metric}" "$(cat ${INSTANCE_METRICS_FILE} | jq -r ".${metric}")" ${JOB_METRICS_FILE}
done

# Scale Test - Job Info
add_to_json "processes" ${SLURM_NPROCS} ${JOB_METRICS_FILE}

# Scale Test - Job Start Time
JOB_START_TIME_MILLIS=$(timestamp_millis)
add_to_json "jobStartTimestamp" ${JOB_START_TIME_MILLIS} ${JOB_METRICS_FILE}

# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
# Job Command
bash -c "${JOB_COMMAND}"
# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #

# Scale Test - Job End Time
JOB_END_TIME_MILLIS=$(timestamp_millis)
add_to_json "jobEndTimestamp" ${JOB_END_TIME_MILLIS} ${JOB_METRICS_FILE}
