Content-Type: multipart/mixed; boundary="==BOUNDARY=="
MIME-Version: 1.0

--==BOUNDARY==
Content-Type: text/cloud-boothook; charset="us-ascii"
MIME-Version: 1.0

#!/bin/bash -x

which dnf 2>/dev/null; dnf=$?
which yum 2>/dev/null; yum=$?

if [ "${!dnf}" == "0" ]; then
  echo "proxy=${DnfProxy}" >> /etc/dnf/dnf.conf
elif [ "${!yum}" == "0" ]; then
  echo "proxy=${YumProxy}" >> /etc/yum.conf
else
  echo "Not yum system"
fi

which apt-get && echo "Acquire::http::Proxy \"${AptProxy}\";" >> /etc/apt/apt.conf || echo "Not apt system"

proxy=${ProxyServer}
if [ "${!proxy}" != "NONE" ]; then
  proxy_host=$(echo "${!proxy}" | awk -F/ '{print $3}' | cut -d: -f1)
  proxy_port=$(echo "${!proxy}" | awk -F/ '{print $3}' | cut -d: -f2)
  echo -e "[Boto]\nproxy = ${!proxy_host}\nproxy_port = ${!proxy_port}\n" >/etc/boto.cfg
  cat >> /etc/profile.d/proxy.sh <<PROXY
export http_proxy="${!proxy}"
export https_proxy="${!proxy}"
export no_proxy="localhost,127.0.0.1,169.254.169.254"
export HTTP_PROXY="${!proxy}"
export HTTPS_PROXY="${!proxy}"
export NO_PROXY="localhost,127.0.0.1,169.254.169.254"
PROXY
fi
--==BOUNDARY==
Content-Type: text/x-shellscript; charset="us-ascii"
MIME-Version: 1.0

#!/bin/bash -x

function error_exit
{
  # wait logs flush before signaling the failure
  sleep 10
  cfn-signal --exit-code=1 --reason="$1" --stack=${AWS::StackName} --role=${IamRoleName} --resource=MasterServer --region=${AWS::Region}
  exit 1
}
function vendor_cookbook
{
  mkdir /tmp/cookbooks
  cd /tmp/cookbooks
  tar -xzf /etc/chef/aws-parallelcluster-cookbook.tgz
  HOME_BAK="${!HOME}"
  export HOME="/tmp"
  for d in `ls /tmp/cookbooks`; do
    cd /tmp/cookbooks/$d
    LANG=en_US.UTF-8 /opt/cinc/embedded/bin/berks vendor /etc/chef/cookbooks --delete || error_exit 'Vendoring cookbook failed.'
  done;
  export HOME="${!HOME_BAK}"
}
function bootstrap_instance
{
  which dnf 2>/dev/null; dnf=$?
  which yum 2>/dev/null; yum=$?
  which apt-get 2>/dev/null; apt=$?
  if [ "${!dnf}" == "0" ]; then
    dnf -y groupinstall development && dnf -y install curl wget jq python3-pip
    pip3 install awscli --upgrade --user
  elif [ "${!yum}" == "0" ]; then
    yum -y groupinstall development && yum -y install curl wget jq awscli python3-pip
  fi
  if [ "${!apt}" == "0" ]; then
    apt-cache search build-essential; apt-get clean; apt-get update; apt-get -y install build-essential curl wget jq python-setuptools awscli python3-pip
  fi
  [[ ${!_region} =~ ^cn- ]] && s3_url="cn-north-1.amazonaws.com.cn/cn-north-1-aws-parallelcluster"
  which cfn-init 2>/dev/null || ( curl -s -L -o /tmp/aws-cfn-bootstrap-py3-latest.tar.gz https://s3.${!s3_url}/cloudformation-examples/aws-cfn-bootstrap-py3-latest.tar.gz; pip3 install -U /tmp/aws-cfn-bootstrap-py3-latest.tar.gz)
  mkdir -p /etc/chef && chown -R root:root /etc/chef
  curl --retry 3 -L https://${!_region}-aws-parallelcluster.s3.${!_region}.amazonaws.com$([ "${!_region}" != "${!_region#cn-*}" ] && echo ".cn" || exit 0)/archives/cinc/cinc-install.sh | bash -s -- -v ${!chef_version}
  /opt/cinc/embedded/bin/gem install --no-document berkshelf:${!berkshelf_version}
  curl --retry 3 -s -L -o /etc/chef/aws-parallelcluster-cookbook.tgz ${!cookbook_url}
  curl --retry 3 -s -L -o /etc/chef/aws-parallelcluster-cookbook.tgz.date ${!cookbook_url}.date
  curl --retry 3 -s -L -o /etc/chef/aws-parallelcluster-cookbook.tgz.md5 ${!cookbook_url}.md5
  vendor_cookbook
  mkdir /opt/parallelcluster
}
[ -f /etc/profile.d/proxy.sh ] && . /etc/profile.d/proxy.sh
custom_cookbook=${CustomChefCookbook}
export _region=${AWS::Region}
s3_url=${AWSDomain}
if [ "${!custom_cookbook}" != "NONE" ]; then
  if [[ "${!custom_cookbook}" =~ ^s3:// ]]; then
    cookbook_url=$(aws s3 presign "${!custom_cookbook}" --region "${!_region}")
  else
    cookbook_url=${!custom_cookbook}
  fi
else
  cookbook_url=https://s3.${!_region}.${!s3_url}/${!_region}-aws-parallelcluster/cookbooks/${CookbookVersion}.tgz
fi
export PATH=/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin:/opt/aws/bin
export parallelcluster_version=aws-parallelcluster-${ParallelClusterVersion}
export cookbook_version=${CookbookVersion}
export chef_version=${ChefVersion}
export berkshelf_version=${BerkshelfVersion}
if [ -f /opt/parallelcluster/.bootstrapped ]; then
  installed_version=$(cat /opt/parallelcluster/.bootstrapped)
  if [ "${!cookbook_version}" != "${!installed_version}" ]; then
    error_exit "This AMI was created with ${!installed_version}, but is trying to be used with ${!cookbook_version}. Please either use an AMI created with ${!cookbook_version} or change your ParallelCluster to ${!installed_version}"
  fi
else
  bootstrap_instance
fi
if [ "${!custom_cookbook}" != "NONE" ]; then
  curl --retry 3 -v -L -o /etc/chef/aws-parallelcluster-cookbook.tgz -z "$(cat /etc/chef/aws-parallelcluster-cookbook.tgz.date)" ${!cookbook_url}
  vendor_cookbook
fi
cd /tmp
# Call CloudFormation
cfn-init -s ${AWS::StackName} --role=${IamRoleName} -v -c default -r MasterServerLaunchTemplate --region ${AWS::Region} || error_exit 'Failed to run cfn-init. If --norollback was specified, check /var/log/cfn-init.log and /var/log/cloud-init-output.log.'
cfn-signal --exit-code=0 --reason="MasterServer setup complete" --stack=${AWS::StackName} --role=${IamRoleName} --resource=MasterServer --region=${AWS::Region}
# End of file
--==BOUNDARY==