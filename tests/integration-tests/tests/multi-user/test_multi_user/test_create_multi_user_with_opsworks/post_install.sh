#!/bin/bash

exec > >(tee /var/log/post-install.log|logger -t post-inst -s 2>/dev/console) 2>&1

### Utility functions

register_opsworks_client() {
    source /etc/parallelcluster/cfnconfig
    aws opsworks register --use-instance-profile \
                          --infrastructure-class ec2 \
                          --region $region \
                          --stack-id $opsworks_stack_id \
                          --local
}

configure_opsworks_deregistration() {
    cat <<-'EOF' > /root/deregister_instances.sh
#!/bin/bash

dereg_log="/var/log/opsworks-deregister.log"

exec > >(tee -a $dereg_log|logger -t owdereg) 2>&1

export aws_bin="/opt/parallelcluster/pyenv/versions/3.6.9/envs/cookbook_virtualenv/bin/aws"

source /etc/parallelcluster/cfnconfig

export opsworks_stack_id=$postinstall_args

stack_members=$($aws_bin opsworks --region $region describe-instances --stack-id $opsworks_stack_id | jq -r ."Instances[] | [.Ec2InstanceId, .InstanceId] | @csv")

echo "`date`: OpsWorks deregistration cycle started." >> $dereg_log

for instance in $stack_members; do
  ec2_id=$(echo $instance | awk -F',' '{print $1}' | tr -d '"')
  opsworks_id=$(echo $instance | awk -F',' '{print $2}' | tr -d '"')
  echo "Checking instance: $ec2_id"
  ec2_state=$($aws_bin ec2 describe-instances --instance-id $ec2_id --region $region | jq -r ".Reservations[].Instances[].State.Name")
  echo "Instance $ec2_id is in state \"$ec2_state\""
  if [ "$ec2_state" = "terminated" ]; then
    echo "Instance $ec2_id will be deregistered from OpsWorks"
    aws opsworks deregister-instance --instance-id $opsworks_id --region $region
  else
    echo "Instance $ec2_id still in use or transitioning state - not deregistering."
  fi
done

echo "`date`: OpsWorks deregistration cycle completed." >> $dereg_log
EOF

chmod +x /root/deregister_instances.sh

echo "*  *  *  *  * root /root/deregister_instances.sh" >> /etc/crontab
}

### Main body

# Load environment variables from ParallelCluster
source /etc/parallelcluster/cfnconfig

# Obtain the OpsWorks stack ID from the pcluster "post_install_args" parameter
export opsworks_stack_id=$postinstall_args

# If the script is being executed on the controller, set up a cron job to run OpsWorks deregistration
if [ $node_type  == 'HeadNode' ]; then
    configure_opsworks_deregistration
fi

# For both controller and compute nodes, register the OpsWorks client
register_opsworks_client
