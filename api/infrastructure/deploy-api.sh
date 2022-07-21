#!/bin/bash
set -ex
# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.

usage="$(basename "$0") [-h] --s3-bucket bucket-name --ecr-repo repo-name --region aws-region [--stack-name name] [--enable-iam-admin true|false] [--create-api-user  true|false])"

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

S3_BUCKET=
ECR_REPO=
IMAGE_BUILDER_VPC_ID=
IMAGE_BUILDER_SUBNET_ID=
STACK_NAME="ParallelClusterApi"
ENABLE_IAM_ADMIN="true"
CREATE_API_USER="false"
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
    --ecr-repo)
    ECR_REPO=$2
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
    --image-builder-vpc-id)
    export IMAGE_BUILDER_VPC_ID=$2
    shift # past argument
    shift # past value
    ;;
    --image-builder-subnet-id)
    export IMAGE_BUILDER_SUBNET_ID=$2
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
    *)    # unknown option
    echo "$usage" >&2
    exit 1
    ;;
esac
done

if [ -z "${S3_BUCKET}" ] || [ -z "${ECR_REPO}" ] || [ -z "${AWS_DEFAULT_REGION}" ] ; then
    echo "$usage" >&2
    exit 1
fi

ACCOUNT_ID=$(aws sts get-caller-identity --query "Account" --output text)
ECR_ENDPOINT="${ACCOUNT_ID}.dkr.ecr.${AWS_DEFAULT_REGION}.amazonaws.com"
S3_UPLOAD_URI="s3://${S3_BUCKET}/api/ParallelCluster.openapi.yaml"

echo "Building docker image"
"${SCRIPT_DIR}/../docker/awslambda/docker-build.sh"

echo "Pushing docker image to ${ECR_ENDPOINT}/${ECR_REPO}"
aws ecr get-login-password | docker login --username AWS --password-stdin "${ECR_ENDPOINT}"
docker tag pcluster-lambda:latest "${ECR_ENDPOINT}/${ECR_REPO}:latest"
docker push "${ECR_ENDPOINT}/${ECR_REPO}:latest"

echo "Publishing OpenAPI specs to S3"
aws s3 cp "${SCRIPT_DIR}/../spec/openapi/ParallelCluster.openapi.yaml" "${S3_UPLOAD_URI}"

echo "Deploying API template"
aws cloudformation deploy \
    --stack-name ${STACK_NAME} \
    --template-file ${SCRIPT_DIR}/parallelcluster-api.yaml \
    --parameter-overrides ApiDefinitionS3Uri="${S3_UPLOAD_URI}" PublicEcrImageUri="${ECR_ENDPOINT}/${ECR_REPO}:latest" \
                          EnableIamAdminAccess="${ENABLE_IAM_ADMIN}" CreateApiUserRole="${CREATE_API_USER}" \
                          ImageBuilderVpcId="${IMAGE_BUILDER_VPC_ID}" \
                          ImageBuilderSubnetId="${IMAGE_BUILDER_SUBNET_ID}" \
    --capabilities CAPABILITY_NAMED_IAM

echo "Updating API Lambda since updates are not fully automated yet"
LAMBDA_FUNCTION_ARN=$(aws cloudformation describe-stacks --stack-name ${STACK_NAME} --query "Stacks[0].Outputs[?OutputKey=='ParallelClusterLambdaArn'].OutputValue" --output text)
ECR_IMAGE_URI=$(aws cloudformation describe-stacks --stack-name ${STACK_NAME} --query "Stacks[0].Outputs[?OutputKey=='UriOfCopyOfPublicEcrImage'].OutputValue" --output text)

aws lambda update-function-code \
    --function-name ${LAMBDA_FUNCTION_ARN} \
    --image-uri ${ECR_IMAGE_URI} \
    --publish
