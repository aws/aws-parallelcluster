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
# OnNodeStart wrapper for the "Creating a cluster with an EFA-enabled FSx Lustre" tutorial:
# https://docs.aws.amazon.com/parallelcluster/latest/ug/tutorial-efa-enabled-fsx-lustre.html
#
# It downloads the OFFICIAL FSx "configure-efa-fsx-lustre-client" package straight from the FSx
# for Lustre documentation endpoint and runs its setup.sh, exactly as documented in "Configuring
# EFA clients": https://docs.aws.amazon.com/fsx/latest/LustreGuide/configure-efa-clients.html
# We author no EFA/LNet logic here; setup.sh (from the official package) is the source of truth.
# Attached as OnNodeStart only where EFA for Lustre is supported (see pcluster.config.yaml).
set -euo pipefail

cd /tmp
curl -O https://docs.aws.amazon.com/fsx/latest/LustreGuide/samples/configure-efa-fsx-lustre-client.zip
unzip -o configure-efa-fsx-lustre-client.zip
cd configure-efa-fsx-lustre-client

# setup.sh sets the libcfs `cpu_npartitions` module option, which only applies at module insert time, so it
# has to be the one that inserts libcfs. The AMI loads lnet at boot, leaving libcfs resident with its
# default 2 partitions, and setup.sh then binds only 2 EFA devices. See V2331124295.
# Safe here: OnNodeStart runs before any shared storage is mounted, and setup.sh reinserts the stack.
# TODO: Revert the unloading of modules once configure-efa-fsx-lustre-client.zip handles module loading
echo "Unloading the boot-loaded Lustre/LNet stack so setup.sh owns the libcfs module insert"
sudo lnetctl lnet unconfigure || true
sudo lustre_rmmod || sudo modprobe -r kefalnd ksocklnd lustre lnet libcfs || true
if lsmod | grep -q "^libcfs"; then
  echo "WARNING: libcfs is still loaded; setup.sh will ignore cpu_npartitions and under-bind EFA devices." >&2
fi

# Configure the FSx Lustre client to use EFA.
sudo ./setup.sh
