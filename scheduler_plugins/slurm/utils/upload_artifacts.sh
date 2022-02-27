#!/bin/bash

#
# Copyright 2022 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
#
set -e

function usage {
    echo "usage: $0 --bucket bucket_name --key-prefix key_prefix --region region"
    echo "  --bucket      [REQUIRED] S3 bucket name artifacts are uploaded to"
    echo "  --key-prefix  [OPTIONAL] - S3 bucket key prefix to use"
    echo "  --region      [REQUIRED] - AWS Region"
    exit 1
}

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "${SCRIPT_DIR}/.."

while [ $# -gt 0 ]; do
  case "$1" in
    --bucket)
      S3_BUCKET="$2"
      shift
    ;;
    --bucket=*)
      S3_BUCKET="${1#*=}"
    ;;
    --region)
      AWS_REGION="$2"
      shift
    ;;
    --region=*)
      AWS_REGION="${1#*=}"
    ;;
    --key-prefix)
      S3_BUCKET_PREFIX="/$2"
      shift
    ;;
    --key-prefix=*)
      S3_BUCKET_PREFIX="/${1#*=}"
    ;;
    *)
      usage
    ;;
  esac
  shift
done

[ -z "${S3_BUCKET}" ] || [ -z "${AWS_REGION}" ] && usage
[ -z "${S3_BUCKET_PREFIX}" ] && S3_BUCKET_PREFIX="/scheduler_plugins/slurm"

ADDITIONAL_CLUSTER_INFRASTRUCTURE_FILE="./slurm_plugin_infrastructure.cfn.yaml"
ADDITIONAL_CLUSTER_INFRASTRUCTURE_S3_URL="s3://${S3_BUCKET}${S3_BUCKET_PREFIX}/slurm_plugin_infrastructure.cfn.yaml"
echo "Uploading ${ADDITIONAL_CLUSTER_INFRASTRUCTURE_FILE} to ${ADDITIONAL_CLUSTER_INFRASTRUCTURE_S3_URL}"
aws s3 cp --region "${AWS_REGION}" "${ADDITIONAL_CLUSTER_INFRASTRUCTURE_FILE}" "${ADDITIONAL_CLUSTER_INFRASTRUCTURE_S3_URL}"
ADDITIONAL_CLUSTER_INFRASTRUCTURE_CHECKSUM=$(shasum --algorithm 256 "${ADDITIONAL_CLUSTER_INFRASTRUCTURE_FILE}" | cut -d' ' -f1)

PLUGIN_ARTIFACTS_DIR="./artifacts"
PLUGIN_ARTIFACTS_ARCHIVE="/tmp/artifacts.tar.gz"
PLUGIN_ARTIFACTS_S3_URL="s3://${S3_BUCKET}${S3_BUCKET_PREFIX}/artifacts.tar.gz"
echo "Uploading plugin artifacts to ${PLUGIN_ARTIFACTS_S3_URL}"
tar czf "${PLUGIN_ARTIFACTS_ARCHIVE}" "${PLUGIN_ARTIFACTS_DIR}"
# git archive --format=tar --output=artifacts.tar.gz HEAD artifacts
aws s3 cp --region "${AWS_REGION}" "${PLUGIN_ARTIFACTS_ARCHIVE}" "${PLUGIN_ARTIFACTS_S3_URL}"
PLUGIN_ARTIFACTS_CHECKSUM=$(shasum --algorithm 256 "${PLUGIN_ARTIFACTS_ARCHIVE}" | cut -d' ' -f1)

PLUGIN_DEFINITION_S3_URL="s3://${S3_BUCKET}${S3_BUCKET_PREFIX}/plugin_definition.yaml"
GENERATED_PLUGIN_DEFINITION_PATH="/tmp/plugin_template_plugin_definition.yaml"
cp plugin_definition.yaml ${GENERATED_PLUGIN_DEFINITION_PATH}
sed -i "s|<TEMPLATE_CHECKSUM>|${ADDITIONAL_CLUSTER_INFRASTRUCTURE_CHECKSUM}|g" ${GENERATED_PLUGIN_DEFINITION_PATH}
sed -i "s|<ARTIFACTS_CHECKSUM>|${PLUGIN_ARTIFACTS_CHECKSUM}|g" ${GENERATED_PLUGIN_DEFINITION_PATH}
sed -i "s|<BUCKET>|${S3_BUCKET}${S3_BUCKET_PREFIX}|g" ${GENERATED_PLUGIN_DEFINITION_PATH}
echo "Generated plugin definition:" && cat ${GENERATED_PLUGIN_DEFINITION_PATH}
echo "Uploading plugin_definition to ${PLUGIN_DEFINITION_S3_URL}"
aws s3 cp --region "${AWS_REGION}" "${GENERATED_PLUGIN_DEFINITION_PATH}" "${PLUGIN_DEFINITION_S3_URL}"

GENERATED_CONFIG_PATH="/tmp/slurm_plugin_cluster_config.yaml"
cp examples/cluster_configuration.yaml ${GENERATED_CONFIG_PATH}
sed -i "s|<PLUGIN_DEFINITION>|${PLUGIN_DEFINITION_S3_URL}|g" ${GENERATED_CONFIG_PATH}
PLUGIN_DEFINITION_CHECKSUM=$(shasum --algorithm 256 "${GENERATED_PLUGIN_DEFINITION_PATH}" | cut -d' ' -f1)
sed -i "s|<PLUGIN_DEFINITION_CHECKSUM>|${PLUGIN_DEFINITION_CHECKSUM}|g" ${GENERATED_CONFIG_PATH}

echo "Generated test cluster configuration in ${GENERATED_CONFIG_PATH}:"
cat ${GENERATED_CONFIG_PATH}
echo ""
echo "After replacing remaining placeholders run the following command to create a cluster:"
echo "  pcluster create-cluster --region ${AWS_REGION} --cluster-configuration ${GENERATED_CONFIG_PATH} --rollback-on-failure false --cluster-name slurm-plugin-test-cluster"
