#!/bin/bash
set -x

# Verify chef.io is called to download chef installer script or client
sudo grep -ir "chef.io/chef/install.sh" /var/log/cloud-init-output.log
if [ $? -ne 0 ]; then
    echo "Chef installer not downloaded from chef.io"
    exit 1
fi
sudo grep -ir "packages.chef.io" /var/log/cloud-init-output.log
if [ $? -ne 0 ]; then
    echo "Chef package not downloaded from chef.io"
    exit 1
fi
