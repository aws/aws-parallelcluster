#!/bin/sh

. /opt/cfncluster/cfnconfig

ec2_region_url="http://169.254.169.254/latest/meta-data/placement/availability-zone"
ec2_region=$(curl --retry 3 --retry-delay 0 --silent --fail ${ec2_region_url})

pending=$(/opt/slurm/bin/squeue -h -o '%t %D' | awk '$1 == "PD" { total = total + 1} END {print total}')q

if [ "${pending}x" == "x" ]; then
pending=0
fi

aws --region ${ec2_region%?} cloudwatch put-metric-data --namespace cfncluster --metric-name pending --unit Count --value ${pending} --dimensions Stack=${stack_name}
