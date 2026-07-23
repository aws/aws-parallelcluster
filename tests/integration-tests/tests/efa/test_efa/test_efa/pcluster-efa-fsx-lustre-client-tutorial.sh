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
set -euo pipefail

cd /tmp
curl -O https://docs.aws.amazon.com/fsx/latest/LustreGuide/samples/configure-efa-fsx-lustre-client.zip
unzip -o configure-efa-fsx-lustre-client.zip
cd configure-efa-fsx-lustre-client

# Configure the FSx Lustre client to use EFA.
sudo ./setup.sh
