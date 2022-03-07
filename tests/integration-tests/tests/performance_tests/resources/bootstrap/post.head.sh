#!/bin/bash
set -ex

# Cluster variables
source /etc/parallelcluster/cfnconfig
SHARED_DIR="$(echo $cfn_ebs_shared_dirs | cut -d ',' -f 1)"
CLUSTER_NAME="${stack_name:?}"
AWS_DEFAULT_REGION="${cfn_region:?}"

# Inputs
S3_BUCKET_URI="${1}"

# Check inputs
[ -z ${S3_BUCKET_URI} ] && echo "$(date +"%Y-%m-%dT%H-%M-%S") [ERROR] 1st argument S3_BUCKET_URI must not be empty" && exit 1

# Load libraries
FUNCTIONS_SCRIPT_S3="${S3_BUCKET_URI}/functions.sh"
FUNCTIONS_SCRIPT="${SHARED_DIR}/assets/lib/functions.sh"
mkdir -p $(dirname "${FUNCTIONS_SCRIPT}")
aws s3 cp "${FUNCTIONS_SCRIPT_S3}" "${FUNCTIONS_SCRIPT}"
chmod 755 "${FUNCTIONS_SCRIPT}"
source "${FUNCTIONS_SCRIPT}"

# Download - Scale Test Runner
SCALE_TEST_SCRIPT_S3="${S3_BUCKET_URI}/run-scale-test.sh"
SCALE_TEST_SCRIPT="${SHARED_DIR}/assets/workloads/scale-test/run-scale-test.sh"
download_asset "${SCALE_TEST_SCRIPT_S3}" "${SCALE_TEST_SCRIPT}" 755

# Download - Scale Test Job Wrapper
SCALE_TEST_JOB_WRAPPER_SCRIPT_S3="${S3_BUCKET_URI}/scale-test-job-wrapper.sh"
SCALE_TEST_JOB_WRAPPER_SCRIPT="${SHARED_DIR}/assets/workloads/scale-test/scale-test-job-wrapper.sh"
download_asset "${SCALE_TEST_JOB_WRAPPER_SCRIPT_S3}" "${SCALE_TEST_JOB_WRAPPER_SCRIPT}" 755

# Download - Script Env Info
ENV_INFO_SCRIPT_S3="${S3_BUCKET_URI}/env-info.sh"
ENV_INFO_SCRIPT="${SHARED_DIR}/assets/workloads/env-info.sh"
download_asset "${ENV_INFO_SCRIPT_S3}" "${ENV_INFO_SCRIPT}" 755

# Install AWS ParallelCluster
rm -rf aws-parallelcluster
pip3 uninstall -y aws-parallelcluster openapi-spec-validator pyrsistent
pip3 install pyrsistent==0.16.0
git clone https://github.com/aws/aws-parallelcluster.git
pip3 install aws-parallelcluster/cli/

# Install Python libraries
pip3 install numpy

# Dashboard improvements
DASHBOARD_WIDGETS_JSON_S3="${S3_BUCKET_URI}/cloudwatch-dashboard-widgets.json"
DASHBOARD_WIDGETS_JSON="${SHARED_DIR}/assets/monitoring/cloudwatch-dashboard-widgets.json"
download_asset "${DASHBOARD_WIDGETS_JSON_S3}" "${DASHBOARD_WIDGETS_JSON}" 755

TEMP_DIR=$(mktemp -d -t pcluster-post-head-XXXXXXXXXX)

CURRENT_DASHBOARD_JSON="${TEMP_DIR}/current-dashboard.json"
CURRENT_DASHBOARD=$(aws cloudwatch get-dashboard --region ${AWS_DEFAULT_REGION} --dashboard-name "${CLUSTER_NAME}-${AWS_DEFAULT_REGION}")
echo ${CURRENT_DASHBOARD} > "${CURRENT_DASHBOARD_JSON}"

NEW_DASHBOARD_WIDGETS_JSON="${TEMP_DIR}/new-dashboard-widgets.json"
NEW_DASHBOARD_WIDGETS=$(cat ${DASHBOARD_WIDGETS_JSON})
NEW_DASHBOARD_WIDGETS=${NEW_DASHBOARD_WIDGETS//INSERT_CLUSTER_NAME_HERE/${CLUSTER_NAME}}
NEW_DASHBOARD_WIDGETS=${NEW_DASHBOARD_WIDGETS//INSERT_AWS_REGION_HERE/${AWS_DEFAULT_REGION}}
echo ${NEW_DASHBOARD_WIDGETS} > ${NEW_DASHBOARD_WIDGETS_JSON}

FINAL_DASHBOARD_BODY_JSON="${TEMP_DIR}/final-dashboard-body.json"
echo $(cat ${CURRENT_DASHBOARD_JSON} | jq -r '.DashboardBody' | jq --argfile f2 ${NEW_DASHBOARD_WIDGETS_JSON} '.widgets |= . + $f2.widgets') > ${FINAL_DASHBOARD_BODY_JSON}
aws cloudwatch put-dashboard --region ${AWS_DEFAULT_REGION} --dashboard-name "${CLUSTER_NAME}-${AWS_DEFAULT_REGION}" --dashboard-body "$(cat ${FINAL_DASHBOARD_BODY_JSON})"


# TODO must complete dashboard enrichment

# Metrics publishing
METRICS_PUBLISHER_SCRIPT_S3="${S3_BUCKET_URI}/metrics-publisher.sh"
METRICS_PUBLISHER_SCRIPT="${SHARED_DIR}/assets/monitoring/metrics-publisher.sh"
download_asset "${METRICS_PUBLISHER_SCRIPT_S3}" "${METRICS_PUBLISHER_SCRIPT}" 755
cron_script "* * * * *" "${METRICS_PUBLISHER_SCRIPT}" "${METRICS_PUBLISHER_SCRIPT}.log"
