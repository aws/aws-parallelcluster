#!/bin/bash

# Install the required packages
yum -y install sssd realmd krb5-workstation samba-common-tools
instance_id=$(curl http://169.254.169.254/latest/meta-data/instance-id)
region=$(curl -s http://169.254.169.254/latest/meta-data/placement/availability-zone | sed 's/[a-z]$//')
# Lambda function to join the linux system in the domain
function_name=$2
aws --region ${region} lambda invoke --function-name $function_name /tmp/out --payload '{"instance": "'${instance_id}'"}' --log-type None
output=""
while [ -z "$output" ]
do
  sleep 5
  output=$(realm list)
done
#This line allows the users to login without the domain name
sed -i 's/use_fully_qualified_names = True/use_fully_qualified_names = False/g' /etc/sssd/sssd.conf
#This line configure sssd to create the home directories in the shared folder
mkdir -p /shared/home/
sed -i '/fallback_homedir/c\fallback_homedir = /home/%u' /etc/sssd/sssd.conf
sleep 1
service sssd restart
