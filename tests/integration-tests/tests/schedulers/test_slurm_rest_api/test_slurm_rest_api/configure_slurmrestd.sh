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
#   - Makes libhttp_parser discoverable by the dynamic linker before configuring slurmrestd
#     on ParallelCluster < 3.16.0 AMIs, see fix_http_parser_linker_cache below.
#   - Dumps the slurmrestd unit status and journal on failure, because the recipe only reports
#     "Timeout waiting for slurmrestd startup" and never why the daemon died.
#
# Arguments:
#   $1 - S3 URI of the adapted slurm_rest_api.rb (e.g. s3://bucket/scripts/slurm_rest_api.rb)

set -ex

SLURM_REST_API_RB_S3_URI="${1:?Usage: configure_slurmrestd.sh <s3-uri-of-slurm_rest_api.rb>}"

SLURMRESTD_BIN=/opt/slurm/sbin/slurmrestd

dump_slurmrestd_diagnostics() {
    set +e
    echo "=== slurmrestd failed to come up, collecting diagnostics ==="
    ldd "${SLURMRESTD_BIN}" 2>&1 | tail -n 20
    systemctl status slurmrestd --no-pager -l 2>&1 | tail -n 30
    journalctl -u slurmrestd --no-pager -n 100 2>&1
}

fix_http_parser_linker_cache() {
    # This function is gated by pcluster version check. For pcluster>=3.16.0,
    # this function is skipped because fix is already in the AMI:
    # https://github.com/aws/aws-parallelcluster-cookbook/pull/3173
    local pcluster_version
    pcluster_version=$(sed 's/^aws-parallelcluster-cookbook-//' /opt/parallelcluster/.bootstrapped 2>/dev/null || true)
    if [ -n "${pcluster_version}" ] && \
       [ "$(printf '%s\n' "${pcluster_version}" 3.16.0 | sort -V | head -n 1)" = "3.16.0" ]; then
        echo "ParallelCluster ${pcluster_version} >= 3.16.0, skipping http-parser linker cache fix"
        return 0
    fi

    [ -x "${SLURMRESTD_BIN}" ] || return 0
    ldd "${SLURMRESTD_BIN}" | grep -q "not found" || return 0

    local lib_dir
    lib_dir=$(dirname "$(ls /usr/local/lib*/libhttp_parser.so* /usr/local/lib/*/libhttp_parser.so* 2>/dev/null | head -n 1)")
    if [ -z "${lib_dir}" ] || [ ! -d "${lib_dir}" ]; then
        echo "ERROR: slurmrestd has unresolved shared libraries and no libhttp_parser was found under /usr/local"
        ldd "${SLURMRESTD_BIN}"
        return 1
    fi

    echo "${lib_dir}" > /etc/ld.so.conf.d/http_parser.conf
    ldconfig

    if ldd "${SLURMRESTD_BIN}" | grep -q "not found"; then
        echo "ERROR: slurmrestd still has unresolved shared libraries after adding ${lib_dir} to the linker cache"
        ldd "${SLURMRESTD_BIN}"
        return 1
    fi
}

fix_http_parser_linker_cache

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
trap dump_slurmrestd_diagnostics ERR
sudo cinc-client \
  --local-mode \
  --config /etc/chef/client.rb \
  --log_level auto \
  --force-formatter \
  --chef-zero-port 8889 \
  -j /etc/chef/dna.json \
  -z $tmp_dir/slurm_rest_api.rb
