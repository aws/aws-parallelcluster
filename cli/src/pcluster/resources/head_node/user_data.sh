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
Content-Type: text/cloud-config; charset=us-ascii
MIME-Version: 1.0

bootcmd:
  # Disable multithreading using logic from https://aws.amazon.com/blogs/compute/disabling-intel-hyper-threading-technology-on-amazon-linux/
  # thread_siblings_list contains a comma (,) or dash (-) separated list of CPU hardware threads within the same core as cpu
  # e.g. 0-1 or 0,1
  # cat /sys/devices/system/cpu/cpu*/topology/thread_siblings_list
  #     | tr '-' ','       # convert hyphen (-) to comma (,), to account that some kernels and CPU architectures use a hyphen instead of a comma
  #     | cut -s -d, -f2-  # split over comma (,) and take the right part
  #     | tr ',' '\n'      # convert remaining comma (,) into new lines
  #     | sort -un         # sort and unique
  - if [ "${DisableMultiThreadingManually}" = "true" ]; then for cpunum in $(cat /sys/devices/system/cpu/cpu*/topology/thread_siblings_list | tr '-' ',' | cut -s -d, -f2- | tr ',' '\n' | sort -un); do echo 0 > /sys/devices/system/cpu/cpu$cpunum/online; done; fi

package_update: false
package_upgrade: false
repo_upgrade: none

datasource_list: [ Ec2, None ]

--==BOUNDARY==
Content-Type: text/x-shellscript; charset="us-ascii"
MIME-Version: 1.0

#!/bin/bash -x

function error_exit
{
  # wait logs flush before signaling the failure
  sleep 10
  reason=$(cat /var/log/parallelcluster/chef_error_msg 2>/dev/null) || reason="$1"
  cfn-signal --exit-code=1 --reason="${!reason}" "${!wait_condition_handle_presigned_url}"
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
[ -f /etc/profile.d/proxy.sh ] && . /etc/profile.d/proxy.sh

# deploy config files
export PATH=/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin:/opt/aws/bin
# Load ParallelCluster environment variables
[ -f /etc/profile.d/pcluster.sh ] && . /etc/profile.d/pcluster.sh

cd /tmp
cfn-init -s ${AWS::StackName} -v -c deployFiles -r HeadNodeLaunchTemplate --region ${AWS::Region}
wait_condition_handle_presigned_url=$(cat /tmp/wait_condition_handle.txt)

custom_cookbook=${CustomChefCookbook}
export _region=${AWS::Region}
s3_url=${AWS::URLSuffix}
if [ "${!custom_cookbook}" != "NONE" ]; then
  if [[ "${!custom_cookbook}" =~ ^s3://([^/]*)(.*) ]]; then
    bucket_region=$(aws s3api get-bucket-location --bucket ${!BASH_REMATCH[1]} | jq -r '.LocationConstraint')
    if [[ "${!bucket_region}" == null ]]; then
      bucket_region="us-east-1"
    fi
    cookbook_url=$(aws s3 presign "${!custom_cookbook}" --region "${!bucket_region}")
  else
    cookbook_url=${!custom_cookbook}
  fi
fi
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
  error_exit "This AMI was not baked by ParallelCluster. Please use pcluster build-image command to create an AMI by providing your AMI as parent image."
fi
if [ "${!custom_cookbook}" != "NONE" ]; then
  curl --retry 3 -v -L -o /etc/chef/aws-parallelcluster-cookbook.tgz ${!cookbook_url}
  vendor_cookbook
fi

# Call CloudFormation
cfn-init -s ${AWS::StackName} -v -c default -r HeadNodeLaunchTemplate --region ${AWS::Region} || error_exit 'Failed to run cfn-init. If --norollback was specified, check /var/log/cfn-init.log and /var/log/cloud-init-output.log.'
cfn-signal --exit-code=0 --reason="HeadNode setup complete" "${!wait_condition_handle_presigned_url}"
# End of file
--==BOUNDARY==
