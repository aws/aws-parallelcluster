#!/bin/bash
set -e

# Usage: /shared/assets/workloads/scale-test/run-scale-test.sh [ITERATIONS] [JOBS_PER_ITERATION] [NUM_PROCESSES_PER_JOB] [JOB_USERS] [JOB_COMMAND] [OUTPUT_DIR] [OUTPUT_S3_URI]
# Usage: /shared/assets/workloads/scale-test/run-scale-test.sh 3 5 4 ec2-user "/shared/assets/workloads/env-info.sh ; sleep 30" /shared/scale-tests/scale-test-$(date +"%Y-%m-%dT%H-%M-%S") s3://aws-parallelcluster-mgiacomo/scale-test/out
# Usage: /shared/assets/workloads/scale-test/run-scale-test.sh 5 5 4 ec2-user,PclusterUser1,PclusterUser2 "sleep 120" /shared/scale-tests/scale-test-$(date +"%Y-%m-%dT%H-%M-%S") s3://aws-parallelcluster-mgiacomo/scale-test/out

# Cluster variables
source /etc/parallelcluster/cfnconfig
CLUSTER_NAME="${stack_name}"
AWS_DEFAULT_REGION="${cfn_region}"
SHARED_DIR="$(echo $cfn_ebs_shared_dirs | cut -d ',' -f 1)"

# Load libraries
FUNCTIONS_SCRIPT="${SHARED_DIR}/assets/lib/functions.sh"
source "${FUNCTIONS_SCRIPT}"

# Functions
function launch_job () {
  local job_user=$1
  local num_processes=$2
  local job_wrapper_script=$3
  local output_dir=$4
  local job_command=$5

  local sbatch_result=$(sudo -iu ${job_user} sbatch -n ${num_processes} "${job_wrapper_script}" "${output_dir}" "${job_command}")
  local submission_line=$(echo $sbatch_result | grep "Submitted batch job")

  [ -z $submission_line ] && fail "Job submission failed"

  local job_id=$(echo $submission_line | cut -d ' ' -f 4)
  echo $job_id
}

# Input
ITERATIONS=${1:-3}
JOBS_PER_ITERATION=${2:-1}
NUM_PROCESSES_PER_JOB=${3:-1}
JOB_USERS=($(echo ${4:-$(whoami)} | tr "," " "))
JOB_COMMAND="${5:-"sleep 60"}"
OUTPUT_DIR=${6:-"${SHARED_DIR}/scale-tests/${CLUSTER_NAME}-$(timestamp_datetime)"}
OUTPUT_S3=${7}

# Job Details
JOB_WRAPPER_SCRIPT="${SHARED_DIR}/assets/workloads/scale-test/scale-test-job-wrapper.sh"

# Print Info
echo "# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #"
echo "# SCALE TEST"
echo "# - Iterations: ${ITERATIONS}"
echo "# - Jobs / Iteration: ${JOBS_PER_ITERATION}"
echo "# - Processes / Job: ${NUM_PROCESSES_PER_JOB}"
echo "# - Job Users: ${JOB_USERS[@]}"
echo "# - Job Wrapper Script: ${JOB_WRAPPER_SCRIPT}"
echo "# - Job Command: ${JOB_COMMAND}"
echo "# - Test Output: ${OUTPUT_DIR}"
echo "# - Test Output S3: ${OUTPUT_S3}"
echo "# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #"

# Init
for iteration in $(seq 1 ${ITERATIONS}); do
  log "Executing iteration ${iteration}/${ITERATIONS}"

  log "Terminating compute fleet"
  terminate_compute_fleet ${CLUSTER_NAME} ${AWS_DEFAULT_REGION}

  log "Waiting for compute fleet down to 0 nodes (can take up to the configured idle scale-down time, default 10 minutes)"
  wait_compute_fleet ${CLUSTER_NAME} ${AWS_DEFAULT_REGION} 0 120

  # Job Launch
  JOB_IDS=()
  for j in $(seq 1 ${JOBS_PER_ITERATION}); do
    JOB_USER=$(get_circular_array_element $(( ${j} - 1 )) ${JOB_USERS[@]})
    log "Submitting job ${j}/${JOBS_PER_ITERATION} for iteration ${iteration}/${ITERATIONS} as user ${JOB_USER}"
    JOB_ID=$(launch_job "${JOB_USER}" "${NUM_PROCESSES_PER_JOB}" "${JOB_WRAPPER_SCRIPT}" "${OUTPUT_DIR}" "${JOB_COMMAND}")
    JOB_SUBMISSION_TIME_MILLIS=$(timestamp_millis)
    JOB_METRICS_FILE="${OUTPUT_DIR}/job.${JOB_ID}.sample.json"
    mkdir -m 777 -p $(dirname ${JOB_METRICS_FILE})
    echo "{}" > ${JOB_METRICS_FILE}
    chmod 666 ${JOB_METRICS_FILE}

    log "Job ${JOB_ID} submitted at $(millis_to_date_time ${JOB_SUBMISSION_TIME_MILLIS}); metrics will be collected in ${JOB_METRICS_FILE}"
    add_to_json "jobId" ${JOB_ID} ${JOB_METRICS_FILE}
    add_to_json "user" ${JOB_USER} ${JOB_METRICS_FILE}
    add_to_json "jobSubmissionTimestamp" ${JOB_SUBMISSION_TIME_MILLIS} ${JOB_METRICS_FILE}
    JOB_IDS+=(${JOB_ID})
  done

  # Waiting Jobs Completion
  log "Waiting for jobs completion: ${JOB_IDS[@]}"
  wait_job_completion $(join_array_by "," ${JOB_IDS[@]}) 120

  # Metrics
  COMPUTE_NODES_METRICS=("instancePreInstallUpTime" "instancePostInstallUpTime")
  COMPUTE_NODES_METRICS_WITH_TIMESTAMPS=(${COMPUTE_NODES_METRICS[@]} "instancePreInstallTimestamp" "instancePostInstallTimestamp")
  COMPUTE_NODES_METRICS_WITH_TIMESTAMPS_AND_INSTANCE_ID=(${COMPUTE_NODES_METRICS_WITH_TIMESTAMPS[@]} "instanceId")
  JOB_METRICS=("jobRunTime" "jobWaitingTime" "jobWarmupLeaderNodeTime" "jobWarmupFirstNodeTime" "jobWarmupLastNodeTime")

  # Compute Nodes Sample
  # instancePreInstallTimestamp, instancePreInstallUpTime, instancePostInstallTimestamp, instancePostInstallUpTime
  COMPUTE_NODES_SAMPLE_FILE="${OUTPUT_DIR}/compute-nodes.${iteration}.sample.json"
  COMPUTE_NODES_METRICS_DIR="${SHARED_DIR}/metrics/compute-nodes"
  COMPUTE_NODES_METRICS_FILES=$(find ${COMPUTE_NODES_METRICS_DIR} -type f -name "instance-*.json")
  for metric in ${COMPUTE_NODES_METRICS_WITH_TIMESTAMPS[@]}; do
    add_to_json "${metric}Sample" $(get_sample_from_json "${metric}" "${COMPUTE_NODES_METRICS_FILES}") ${COMPUTE_NODES_SAMPLE_FILE}
  done

  for JOB_ID in ${JOB_IDS[@]}; do
    JOB_METRICS_FILE="${OUTPUT_DIR}/job.${JOB_ID}.sample.json"
    # Compute Nodes metrics
    # firstComputeNode timings, i.e. time metrics from the first launched compute node
    FIRST_COMPUTE_NODE_METRICS=$(get_json_with_minimum "instancePreInstallTimestamp" "${COMPUTE_NODES_METRICS_FILES}")
    for metric in ${COMPUTE_NODES_METRICS_WITH_TIMESTAMPS_AND_INSTANCE_ID[@]}; do
      add_to_json "firstComputeNode.${metric}" "$(echo ${FIRST_COMPUTE_NODE_METRICS} | jq -r ".${metric}")" ${JOB_METRICS_FILE}
    done
    # lastComputeNode timings, i.e. time metrics from the last launched compute node
    LAST_COMPUTE_NODE_METRICS=$(get_json_with_maximum "instancePreInstallTimestamp" "${COMPUTE_NODES_METRICS_FILES}")
    for metric in ${COMPUTE_NODES_METRICS_WITH_TIMESTAMPS_AND_INSTANCE_ID[@]}; do
      add_to_json "lastComputeNode.${metric}" "$(echo ${LAST_COMPUTE_NODE_METRICS} | jq -r ".${metric}")" ${JOB_METRICS_FILE}
    done

    # Derived Metrics: jobRunTime = jobEndTimestamp - jobStartTimestamp
    JOB_RUN_TIME_MILLIS=$(cat ${JOB_METRICS_FILE} | jq '(.jobEndTimestamp|tonumber) - (.jobStartTimestamp|tonumber)')
    add_to_json "jobRunTime" ${JOB_RUN_TIME_MILLIS} ${JOB_METRICS_FILE}

    # Derived Metrics: jobWaitingTime = jobStartTimestamp - jobSubmissionTimestamp
    JOB_WAITING_TIME_MILLIS=$(cat ${JOB_METRICS_FILE} | jq '(.jobStartTimestamp|tonumber) - (.jobSubmissionTimestamp|tonumber)')
    add_to_json "jobWaitingTime" ${JOB_WAITING_TIME_MILLIS} ${JOB_METRICS_FILE}

    # Derived Metrics: jobWarmupLeaderNodeTime = jobStartTimestamp - leaderComputeNode.instancePreInstallTimestamp
    JOB_WARMUP_LEADER_NODE_TIME_MILLIS=$(cat ${JOB_METRICS_FILE} | jq '(.jobStartTimestamp|tonumber) - (.leaderComputeNode.instancePreInstallTimestamp|tonumber)')
    add_to_json "jobWarmupLeaderNodeTime" ${JOB_WARMUP_LEADER_NODE_TIME_MILLIS} ${JOB_METRICS_FILE}

    # Derived Metrics: jobWarmupFirstNodeTime = jobStartTimestamp - firstComputeNode.instancePreInstallTimestamp
    JOB_WARMUP_FIRST_NODE_TIME_MILLIS=$(cat ${JOB_METRICS_FILE} | jq '(.jobStartTimestamp|tonumber) - (.firstComputeNode.instancePreInstallTimestamp|tonumber)')
    add_to_json "jobWarmupFirstNodeTime" ${JOB_WARMUP_FIRST_NODE_TIME_MILLIS} ${JOB_METRICS_FILE}

    # Derived Metrics: jobWarmupLastNodeTime = jobStartTimestamp - lastComputeNode.instancePreInstallTimestamp
    JOB_WARMUP_LAST_NODE_TIME_MILLIS=$(cat ${JOB_METRICS_FILE} | jq '(.jobStartTimestamp|tonumber) - (.lastComputeNode.instancePreInstallTimestamp|tonumber)')
    add_to_json "jobWarmupLastNodeTime" ${JOB_WARMUP_LAST_NODE_TIME_MILLIS} ${JOB_METRICS_FILE}
  done

  # Cleanup
  rm -rf ${COMPUTE_NODES_METRICS_FILES}

  # Finalize
  log "Iteration ${iteration}/${ITERATIONS} completed: job metrics in ${JOB_METRICS_FILE}"
  log "Waiting 60 seconds before the next iteration"
  sleep 60
  log "Terminating compute fleet"
  terminate_compute_fleet ${CLUSTER_NAME} ${AWS_DEFAULT_REGION}
done

# Samples
log "Generating samples"
SAMPLES_FILE="${OUTPUT_DIR}/samples.json"
JOBS_SAMPLE_FILES=$(find ${OUTPUT_DIR} -type f -name "job.*.sample.json")
for metric in ${JOB_METRICS[@]}; do
  add_to_json "${metric}Sample" $(get_sample_from_json "${metric}" "${JOBS_SAMPLE_FILES}") ${SAMPLES_FILE}
done
COMPUTE_NODES_SAMPLE_FILES=$(find ${OUTPUT_DIR} -type f -name "compute-nodes.*.sample.json")
for metric in ${COMPUTE_NODES_METRICS[@]}; do
  add_to_json "${metric}Sample" $(get_sample_from_json "${metric}Sample" "${COMPUTE_NODES_SAMPLE_FILES}") ${SAMPLES_FILE}
done

# Statistics
log "Generating statistics"
STATISTICS_FILE="${OUTPUT_DIR}/statistics.json"
STATISTICS_METRICS=(${JOB_METRICS[@]} ${COMPUTE_NODES_METRICS[@]})
for metric in ${STATISTICS_METRICS[@]}; do
  add_to_json "${metric}.min" $(get_min "$(cat ${SAMPLES_FILE} | jq -r ".${metric}Sample")") ${STATISTICS_FILE}
  add_to_json "${metric}.max" $(get_max "$(cat ${SAMPLES_FILE} | jq -r ".${metric}Sample")") ${STATISTICS_FILE}
  add_to_json "${metric}.avg" $(get_avg "$(cat ${SAMPLES_FILE} | jq -r ".${metric}Sample")") ${STATISTICS_FILE}
  add_to_json "${metric}.std" $(get_std "$(cat ${SAMPLES_FILE} | jq -r ".${metric}Sample")") ${STATISTICS_FILE}
  add_to_json "${metric}.med" $(get_med "$(cat ${SAMPLES_FILE} | jq -r ".${metric}Sample")") ${STATISTICS_FILE}
  add_to_json "${metric}.prc25" $(get_prc "$(cat ${SAMPLES_FILE} | jq -r ".${metric}Sample")" 25) ${STATISTICS_FILE}
  add_to_json "${metric}.prc75" $(get_prc "$(cat ${SAMPLES_FILE} | jq -r ".${metric}Sample")" 75) ${STATISTICS_FILE}
done

# End
log "Scale test completed: samples in ${SAMPLES_FILE}, statistics in ${STATISTICS_FILE}"

# Upload samples and statistics on S3
if [[ -z ${OUTPUT_S3} ]]; then
  log "Skipping upload on S3 as no OUTPUT_S3 has been specified"
else
  aws s3 cp --recursive ${OUTPUT_DIR} ${OUTPUT_S3}
  log "Results published to ${OUTPUT_S3}"
fi
