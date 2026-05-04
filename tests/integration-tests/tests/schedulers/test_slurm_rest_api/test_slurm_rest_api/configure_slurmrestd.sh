#!/bin/bash
#
# OnNodeConfigured custom action for the test_slurm_rest_api integration test.
#
# Based on the upstream Slurm REST API postinstall script:
#   https://raw.githubusercontent.com/aws-samples/aws-parallelcluster-post-install-scripts/main/rest-api/postinstall.sh
#
# Differences from upstream:
#   - Uses a local slurm_rest_api.rb (uploaded to S3 by the test) instead of downloading
#     it from GitHub. The local copy includes an `apt-get update` before installing nginx
#     on Debian/Ubuntu to avoid stale package index 404 errors.
#
# Arguments:
#   $1 - S3 URI of the adapted slurm_rest_api.rb (e.g. s3://bucket/scripts/slurm_rest_api.rb)

set -ex

SLURM_REST_API_RB_S3_URI="${1:?Usage: configure_slurmrestd.sh <s3-uri-of-slurm_rest_api.rb>}"

# Copy Slurm REST API configuration files and scripts
tmp_dir=/tmp/slurm_rest_api
mkdir -p $tmp_dir

source_path=https://raw.githubusercontent.com/aws-samples/aws-parallelcluster-post-install-scripts/main/rest-api
files=(slurmrestd.service nginx.conf)
for file in "${files[@]}"
do
    wget -qO- $source_path/$file > $tmp_dir/$file
done

rotate_jwt_path=/opt/parallelcluster/scripts/rotate_jwt.sh
wget -qO- $source_path/rotate_jwt.sh > $rotate_jwt_path
chmod +x $rotate_jwt_path

# Download the adapted slurm_rest_api.rb from S3
aws s3 cp "${SLURM_REST_API_RB_S3_URI}" $tmp_dir/slurm_rest_api.rb

# Setup Slurm REST API
sudo cinc-client \
  --local-mode \
  --config /etc/chef/client.rb \
  --log_level auto \
  --force-formatter \
  --chef-zero-port 8889 \
  -j /etc/chef/dna.json \
  -z $tmp_dir/slurm_rest_api.rb
