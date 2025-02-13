#!/bin/bash -ex
# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.

usage="$(basename "$0") [-h] --s3-bucket bucket-name --region aws-region [--stack-name name] [--enable-iam-admin true|false] [--create-api-user true|false] [--lambda-layer abs_path]"

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

S3_BUCKET=
STACK_NAME="ParallelClusterApi"
ENABLE_IAM_ADMIN="true"
CREATE_API_USER="false"
LAMBDA_LAYER=
while [[ $# -gt 0 ]]
do
key="$1"

case $key in
    -h)
    echo "$usage" >&2
    exit 1
    ;;
    --s3-bucket)
    S3_BUCKET=$2
    shift # past argument
    shift # past value
    ;;
    --region)
    export AWS_DEFAULT_REGION=$2
    shift # past argument
    shift # past value
    ;;
    --stack-name)
    export STACK_NAME=$2
    shift # past argument
    shift # past value
    ;;
    --enable-iam-admin)
    export ENABLE_IAM_ADMIN=$2
    shift # past argument
    shift # past value
    ;;
    --create-api-user)
    export CREATE_API_USER=$2
    shift # past argument
    shift # past value
    ;;
    --enable-fsx-s3-access)
    export ENABLE_FSX_S3_ACCESS=$2
    shift # past argument
    shift # past value
    ;;
    --fsx-s3-buckets)
    export FSX_S3_BUCKETS=$2
    shift # past argument
    shift # past value
    ;;
    --lambda-layer)
    export LAMBDA_LAYER=$2
    shift # past argument
    shift # past value
    ;;
    *)    # unknown option
    echo "$usage" >&2
    exit 1
    ;;
esac
done

if [ -z "${S3_BUCKET}" ] || [ -z "${AWS_DEFAULT_REGION}" ] ; then
    echo "$usage" >&2
    exit 1
fi

PC_VERSION=$(yq ".Mappings.ParallelCluster.Constants.Version" "${SCRIPT_DIR}/parallelcluster-api.yaml")

S3_UPLOAD_URI="s3://${S3_BUCKET}/api/ParallelCluster.openapi.yaml"
POLICIES_S3_URI="s3://${S3_BUCKET}/stacks/parallelcluster-policies.yaml"
POLICIES_TEMPLATE_URI="http://${S3_BUCKET}.s3.${AWS_DEFAULT_REGION}.amazonaws.com/stacks/parallelcluster-policies.yaml"

echo "Publishing OpenAPI specs to S3"
aws s3 cp "${SCRIPT_DIR}/../spec/openapi/ParallelCluster.openapi.yaml" "${S3_UPLOAD_URI}"

echo "Publishing policies CloudFormation stack to S3"
aws s3 cp "${SCRIPT_DIR}/../../cloudformation/policies/parallelcluster-policies.yaml" "${POLICIES_S3_URI}"

if [ -n "${LAMBDA_LAYER}" ]; then
  LAMBDA_LAYER_S3_URI="s3://${S3_BUCKET}/parallelcluster/${PC_VERSION}/layers/aws-parallelcluster/lambda-layer.zip"
  echo "Publishing Lambda Layer for version ${PC_VERSION} to S3"
  aws s3 cp "${LAMBDA_LAYER}" "${LAMBDA_LAYER_S3_URI}"
fi

echo "Deploying API template"
aws cloudformation deploy \
    --stack-name "${STACK_NAME}" \
    --template-file "${SCRIPT_DIR}/parallelcluster-api.yaml" \
    --s3-bucket "${S3_BUCKET}" \
    --s3-prefix "api/" \
    --parameter-overrides ApiDefinitionS3Uri="${S3_UPLOAD_URI}" \
                          PoliciesTemplateUri="${POLICIES_TEMPLATE_URI}" \
                          EnableIamAdminAccess="${ENABLE_IAM_ADMIN}" CreateApiUserRole="${CREATE_API_USER}" \
                          "$([[ -n "${LAMBDA_LAYER}" ]] && echo "CustomBucket=${S3_BUCKET}" || echo " ")" \
    --capabilities CAPABILITY_NAMED_IAM
