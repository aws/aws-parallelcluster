#!/bin/bash

set -ex

yum -y update && yum install -y jq
pip install awscli==1.20.14
aws --version

if [ -z "$DIRECTORY_ID" ]; then
    echo "DIRECTORY_ID must be set"
    exit 1
elif [ -z "$ADMIN_NODE_INSTANCE_ID" ]; then
    echo "ADMIN_NODE_INSTANCE_ID must be set"
    exit 1
elif [ -z "$NUM_USERS_TO_CREATE" ]; then
    echo "NUM_USERS_TO_CREATE must be set"
    exit 1
elif [ -z "$USER_ADDING_DOCUMENT_NAME" ]; then
    echo "USER_ADDING_DOCUMENT_NAME must be set"
    exit 1
fi
OUTPUT_DIR=$(mktemp -d)
echo "Creating ${NUM_USERS_TO_CREATE} users in directory ${DIRECTORY_ID}"
output_file="${OUTPUT_DIR}/Create${NEW_USER_ALIAS}.json"

# Create users in directory
# TODO: add ability to trigger this via lambda
output_file="${OUTPUT_DIR}/Create${NEW_USER_ALIAS}.json"
# Invoke SSM document to run command on instances
aws ssm send-command \
    --document-name "$USER_ADDING_DOCUMENT_NAME" \
    --targets "[{\"Key\":\"InstanceIds\",\"Values\":[\"${ADMIN_NODE_INSTANCE_ID}\"]}]" \
    --parameters "{\"DirectoryId\":[\"${DIRECTORY_ID}\"], \"NumUsersToCreate\":[\"${NUM_USERS_TO_CREATE}\"]}" \
    --timeout-seconds 600 \
    --max-errors "0" \
    --region "$AWS_DEFAULT_REGION" \
| tee "$output_file"

COMMAND_ID=$(jq < "$output_file"  -r '.Command.CommandId')
echo "Waiting for ${COMMAND_ID} to finish."
aws ssm wait command-executed \
    --command-id "$COMMAND_ID" \
    --instance-id "$ADMIN_NODE_INSTANCE_ID"
echo "Getting exit status for ${COMMAND_ID}"
aws ssm get-command-invocation \
    --command-id "${COMMAND_ID}" \
    --instance-id "${ADMIN_NODE_INSTANCE_ID}" \
| jq -r ".Status"