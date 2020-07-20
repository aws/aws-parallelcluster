#!/bin/bash
set -x

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

# Verify no chef client is installed from S3
sudo grep -iEr "aws-parallelcluster.*/archives/chef/chef-install.sh" /var/log/cloud-init-output.log
if [ $? -eq 0 ]; then
    echo "Chef installer downloaded from S3"
    exit 1
fi


# Verify cinc.sh is not called to download cinc installer script or client
sudo grep -ir "omnitruck.cinc.sh/install.sh" /var/log/cloud-init-output.log
if [ $? -eq 0 ]; then
    echo "Cinc installer downloaded from cinc.sh"
    exit 1
fi

# Verify cinc client is installed from S3
sudo grep -iEr "aws-parallelcluster.*/archives/cinc/cinc-install.sh" /var/log/cloud-init-output.log
if [ $? -ne 0 ]; then
    echo "Cinc installer NOT downloaded from S3"
    exit 1
fi
