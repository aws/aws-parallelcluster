#!/bin/bash
# Copyright 2026 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License").
# You may not use this file except in compliance with the License.
# A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file.
# This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, express or implied.
# See the License for the specific language governing permissions and limitations under the License.
#
# Simulate EC2 DescribeInstances eventual consistency. clustermgtd's describe_instances path has no
# override hook, so we wrap common.ec2_utils.get_private_ip_address_and_dns_name to raise
# KeyError("PrivateIpAddress") for any instance id listed in the trigger file, exactly as a real
# DescribeInstances response with a missing PrivateIpAddress would.
#
# The wrapper is module-global (also used by fleet_manager) and toggled via the trigger file, which only
# ever lists already-running instance ids. clustermgtd does not hot-reload python, so the caller must
# restart clustermgtd once after this script; toggling the trigger file afterwards needs no restart.
set -ex

TRIGGER_FILE="/tmp/ec2_eventual_consistency_instances"
MARKER="# pcluster-integ-test: simulate missing PrivateIpAddress"

echo "Locating common/ec2_utils.py in the node virtualenv"
mapfile -t ec2_utils_paths < <(sudo find / -path "*/node_virtualenv/*/common/ec2_utils.py")
if [ "${#ec2_utils_paths[@]}" -eq 0 ]; then
    echo "Could not locate common/ec2_utils.py in the node virtualenv" >&2
    exit 1
elif [ "${#ec2_utils_paths[@]}" -gt 1 ]; then
    # Fail loudly rather than patch an arbitrary copy and produce a misleading test result.
    echo "Found multiple node_virtualenv ec2_utils.py copies, refusing to guess: ${ec2_utils_paths[*]}" >&2
    exit 1
fi
ec2_utils_path="${ec2_utils_paths[0]}"
echo "Patching ${ec2_utils_path}"

# Idempotent: only append the wrapper once.
if sudo grep -qF "${MARKER}" "${ec2_utils_path}"; then
    echo "Override already installed, skipping append"
    exit 0
fi

# Append to a temp copy and syntax-check before moving into place, so a half-written append can never
# leave clustermgtd importing a broken module. The heredoc is unquoted to expand ${TRIGGER_FILE}/${MARKER},
# so keep the Python below free of shell metacharacters (or escape them as \$).
tmp_file=$(mktemp)
sudo cat "${ec2_utils_path}" > "${tmp_file}"
cat << EOF >> "${tmp_file}"

${MARKER}
import os  # noqa: E402

_original_get_private_ip_address_and_dns_name = get_private_ip_address_and_dns_name
_MISSING_IP_TRIGGER_FILE = "${TRIGGER_FILE}"


def get_private_ip_address_and_dns_name(instance_info):  # noqa: F811
    # Read the target instance ids from a file so the fault can be toggled without reloading the module.
    if os.path.exists(_MISSING_IP_TRIGGER_FILE):
        with open(_MISSING_IP_TRIGGER_FILE) as trigger:
            targets = trigger.read().split()
        if instance_info.get("InstanceId") in targets:
            raise KeyError("PrivateIpAddress")
    return _original_get_private_ip_address_and_dns_name(instance_info)
EOF

echo "Validating that the patched ${ec2_utils_path} is syntactically valid before installing it"
python3 -c "import ast, sys; ast.parse(open(sys.argv[1]).read())" "${tmp_file}"
sudo cp "${tmp_file}" "${ec2_utils_path}"
rm -f "${tmp_file}"
echo "Wrapper installed successfully at ${ec2_utils_path}"
