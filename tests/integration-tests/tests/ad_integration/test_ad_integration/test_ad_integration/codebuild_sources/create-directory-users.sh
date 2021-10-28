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

# Generate aliases for new users
for i in $(seq 1 "$NUM_USERS_TO_CREATE"); do
    NEW_USER_ALIASES="${NEW_USER_ALIASES} PclusterUser${i}"
done

# Create users in directory
# TODO: add ability to trigger this via lambda
COMMAND_IDS=''
for NEW_USER_ALIAS in $NEW_USER_ALIASES; do
    echo "Creating ${NEW_USER_ALIAS} in directory ${DIRECTORY_ID}"
    output_file="${OUTPUT_DIR}/Create${NEW_USER_ALIAS}.json"
    # Invoke SSM document to run command on instances
    aws ssm send-command \
        --document-name "$USER_ADDING_DOCUMENT_NAME" \
        --targets "[{\"Key\":\"InstanceIds\",\"Values\":[\"${ADMIN_NODE_INSTANCE_ID}\"]}]" \
        --parameters "{\"NewUserAlias\":[\"${NEW_USER_ALIAS}\"]}" \
        --timeout-seconds 600 \
        --max-concurrency "50" \
        --max-errors "0" \
        --region "$AWS_DEFAULT_REGION" \
    | tee "$output_file"
    # Get command ID in order to check success status later
    command_id=$(jq < "$output_file"  -r '.Command.CommandId')
    echo "Command ID for creating ${NEW_USER_ALIAS}: ${command_id}"
    COMMAND_IDS="${COMMAND_IDS} ${command_id}"
done
for COMMAND_ID in ${COMMAND_IDS}; do
    echo "Waiting for ${COMMAND_ID} to finish."
    aws ssm wait command-executed \
        --command-id "$COMMAND_ID" \
        --instance-id "$ADMIN_NODE_INSTANCE_ID"
    echo "Getting exit status for ${COMMAND_ID}"
    aws ssm get-command-invocation \
        --command-id "${COMMAND_ID}" \
        --instance-id "${ADMIN_NODE_INSTANCE_ID}" \
    | jq -r ".Status"
done

# Change user passwords
# TODO: put this in a lambda that can be triggered by users
for NEW_USER_ALIAS in $NEW_USER_ALIASES; do
    sleep 1  # TODO: retry w/ backoff instead of sleeping
    echo "Setting password for user ${NEW_USER_ALIAS}"
    aws ds reset-user-password \
        --directory-id "$DIRECTORY_ID" \
        --user-name "$NEW_USER_ALIAS" \
        --new-password "ApplesBananasCherries!"  # TODO: generate random passwords
done