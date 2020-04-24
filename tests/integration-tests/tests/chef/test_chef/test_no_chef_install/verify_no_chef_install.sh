#!/bin/bash
set -x

# Verify chef is not installed
sudo grep -ir "chef.io/chef/install.sh" /var/log/cloud-init-output.log
if [ $? -eq 0 ]; then
    echo "Chef installer downloaded from chef.io"
    exit 1
fi
sudo grep -ir "chef-install.sh" /var/log/cloud-init-output.log
if [ $? -eq 0 ]; then
    echo "Chef installer downloaded from S3"
    exit 1
fi
sudo grep -ir "packages.chef.io" /var/log/cloud-init-output.log
if [ $? -eq 0 ]; then
    echo "Chef package downloaded from chef.io"
    exit 1
fi
sudo grep -ir "archives/chef/chef" /var/log/cloud-init-output.log
if [ $? -eq 0 ]; then
    echo "Chef package downloaded from S3"
    exit 1
fi

