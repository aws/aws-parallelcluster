#!/bin/bash
########
# NOTE #
########
#
# THIS FILE IS PROVIDED AS AN EXAMPLE AND NOT INTENDED TO BE USED BESIDES TESTING
# USE IT AS AN EXAMPLE BUT NOT AS IS FOR PRODUCTION
#

# Setup the SSH authentication
ID=$(curl -s http://169.254.169.254/latest/meta-data/instance-id)
AZ=$(curl -s http://169.254.169.254/latest/meta-data/placement/availability-zone)
REGION=$(echo "${AZ}" | sed 's/[a-z]$//')

export AWS_DEFAULT_REGION=${REGION}

# install and setup cloudwatch to push in logs in the local region
sudo yum install awslogs -y
cat > /etc/awslogs/awscli.conf << EOF
[plugins]
cwlogs = cwlogs
[default]
region = ${REGION}
EOF

# check if this is the master instance
MASTER=false
if [[ $(aws ec2 describe-instances \
            --instance-id ${ID} \
            --query 'Reservations[].Instances[].Tags[?Key==`Name`].Value[]' \
            --output text) = "Master" ]]; then
    MASTER=true
fi

if ${MASTER}; then

# Setup cloudwatch logs for master
cat >>/etc/awslogs/awslogs.conf << EOF
[/opt/sge/default/spool/qmaster/messages]
datetime_format = %b %d %H:%M:%S
file = /opt/sge/default/spool/qmaster/messages
buffer_duration = 5000
log_stream_name = {instance_id}
initial_position = start_of_file
log_group_name = pcluster-master-sge-qmaster-messages

[/var/log/jobwatcher]
datetime_format = %b %d %H:%M:%S
file = /var/log/jobwatcher
buffer_duration = 5000
log_stream_name = {instance_id}
initial_position = start_of_file
log_group_name = pcluster-master-job-watcher

[/var/log/sqswatcher]
datetime_format = %b %d %H:%M:%S
file = /var/log/sqswatcher
buffer_duration = 5000
log_stream_name = {instance_id}
initial_position = start_of_file
log_group_name = pcluster-master-sqs-watcher
EOF


else

# Setup cloudwatch logs for compute
cat >>/etc/awslogs/awslogs.conf << EOF

[/var/log/nodewatcher]
datetime_format = %b %d %H:%M:%S
file = /var/log/nodewatcher
buffer_duration = 5000
log_stream_name = {instance_id}
initial_position = start_of_file
log_group_name = pcluster-compute-node-watcher
EOF

fi

# start awslogs
sudo service awslogs start
sudo chkconfig awslogs on
