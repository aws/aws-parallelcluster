#!/bin/bash
set -x

# get cloudformation log if it doesn't exist
if [ ! -f "/var/log/cloud-init-output.log" ]; then
  sudo grep cloud-init /var/log/messages | sudo tee /var/log/cloud-init-output.log > /dev/null
fi

# Verify chef.io is not called to download chef installer script or client
sudo grep -ir "chef.io/chef/install.sh" /var/log/cloud-init-output.log
if [ $? -eq 0 ]; then
    echo "Chef installer downloaded from chef.io"
    exit 1
fi
sudo grep -ir "packages.chef.io" /var/log/cloud-init-output.log
if [ $? -eq 0 ]; then
    echo "Chef package downloaded from chef.io"
    exit 1
fi

# Verify cinc client is installed from S3
sudo grep -ir "archives/cinc/cinc-install.sh" /var/log/cloud-init-output.log
if [ $? -ne 0 ]; then
    echo "Cinc installer not downloaded from S3"
    exit 1
fi