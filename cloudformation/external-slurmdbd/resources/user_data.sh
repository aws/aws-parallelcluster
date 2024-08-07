Content-Type: multipart/mixed; boundary="==BOUNDARY=="
MIME-Version: 1.0

--==BOUNDARY==
Content-Type: text/cloud-config; charset=us-ascii
MIME-Version: 1.0

package_update: false
package_upgrade: false
repo_upgrade: none
datasource_list: [ Ec2, None ]

--==BOUNDARY==
Content-Type: text/x-shellscript; charset="us-ascii"
MIME-Version: 1.0
#!/bin/bash -x

function vendor_cookbook
{
  mkdir /tmp/cookbooks
  cd /tmp/cookbooks
  tar -xzf /etc/chef/aws-parallelcluster-cookbook.tgz
  HOME_BAK="${!HOME}"
  export HOME="/tmp"
  for d in /tmp/cookbooks/*; do
    cd "$d" || continue
    LANG=en_US.UTF-8 /opt/cinc/embedded/bin/berks vendor /etc/chef/cookbooks --delete
  done;
  export HOME="${!HOME_BAK}"
}

function wait_for_private_ip_assignment
{
  rc=1
  retries=10
  retry=1
  sleeptime=1
  while [ \( $rc -eq 1 \) -a \( $retry -le $retries \) ]; do
    number_of_ips=$(curl -H "X-aws-ec2-metadata-token: $TOKEN" -v http://169.254.169.254/latest/meta-data/network/interfaces/macs/"$MAC"/local-ipv4s | wc -l)
    ((number_of_ips>0))
    rc=$?
    retry=$((retry+1))
    sleep $sleeptime
  done
  return $rc
}

TOKEN=`curl -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 21600"`
MAC=$(curl -H "X-aws-ec2-metadata-token: $TOKEN" -v http://169.254.169.254/latest/meta-data/mac)
ENI_ID=$(curl -H "X-aws-ec2-metadata-token: $TOKEN" -v http://169.254.169.254/latest/meta-data/network/interfaces/macs/"$MAC"/interface-id)
DEVICE_NAME=$(ls /sys/class/net | grep e)

# Configure AWS CLI using the expected overrides, if any.
[ -f /etc/profile.d/aws-cli-default-config.sh ] && . /etc/profile.d/aws-cli-default-config.sh

aws ec2 assign-private-ip-addressess --region "${AWS::Region}" --network-interface-id "${!ENI_ID}" --private-ip-addresses ${PrivateIp} --allow-reassignment

wait_for_private_ip_assignment || echo "Assignment of private IP ${PrivateIp} was not successful."

ip addr add ${PrivateIp}/${SubnetPrefix} dev "${!DEVICE_NAME}"

if [ "${CustomCookbookUrl}" != "NONE" ]; then
  curl --retry 3 -v -L -o /etc/chef/aws-parallelcluster-cookbook.tgz ${CustomCookbookUrl}
  vendor_cookbook
fi

# This is necessary to find the cfn-init application
export PATH=/opt/aws/bin:${!PATH}
[ -f /etc/parallelcluster/pcluster_cookbook_environment.sh ] && . /etc/parallelcluster/pcluster_cookbook_environment.sh

$CFN_BOOTSTRAP_VIRTUALENV_PATH/cfn-init -s ${AWS::StackName} -v -c default -r LaunchTemplate --region "${AWS::Region}"
