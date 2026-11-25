#!/bin/bash
# This script blocks the bootstrap of the current node if a blocking marker object exists in S3.
# Usage: block_bootstrap.sh s3://bucket-name/blocking-key

S3_URI="${1}"

echo "block_bootstrap.sh: Checking for blocking marker at ${S3_URI}"

# Parse bucket and key from s3://bucket/key URI
BUCKET=$(echo "${S3_URI}" | sed 's|s3://||' | cut -d'/' -f1)
KEY=$(echo "${S3_URI}" | sed 's|s3://[^/]*/||')

while aws s3api head-object --bucket "${BUCKET}" --key "${KEY}" > /dev/null 2>&1; do
    echo "block_bootstrap.sh: Blocking marker exists at ${S3_URI}, waiting..."
    sleep 5
done

echo "block_bootstrap.sh: Blocking marker removed from ${S3_URI}, proceeding with bootstrap"
