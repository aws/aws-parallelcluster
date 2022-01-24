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

package_update: false
package_upgrade: false
repo_upgrade: none

datasource_list: [ Ec2, None ]
output:
  all: "| tee -a /var/log/cloud-init-output.log | logger -t user-data -s 2>/dev/console"
write_files:
  - path: /tmp/dna.json
    permissions: '0644'
    owner: root:root
    content: |
      {
        "cluster": {
          "stack_name": "${AWS::StackName}",
          "enable_efa": "${EnableEfa}",
          "raid_parameters": "${RAIDOptions}",
          "base_os": "${BaseOS}",
          "preinstall": "${PreInstallScript}",
          "preinstall_args": "${PreInstallArgs}",
          "postinstall": "${PostInstallScript}",
          "postinstall_args": "${PostInstallArgs}",
          "region": "${AWS::Region}",
          "efs_fs_id": "${EFSId}",
          "efs_shared_dir": "${EFSOptions}",
          "fsx_fs_id": "${FSXId}",
          "fsx_mount_name": "${FSXMountName}",
          "fsx_dns_name": "${FSXDNSName}",
          "fsx_options": "${FSXOptions}",
          "scheduler": "${Scheduler}",
          "disable_hyperthreading_manually": "${DisableHyperThreadingManually}",
          "ephemeral_dir": "${EphemeralDir}",
          "ebs_shared_dirs": "${EbsSharedDirs}",
          "proxy": "${ProxyServer}",
          "slurm_ddb_table": "${SlurmDynamoDBTable}",
          "log_group_name": "${LogGroupName}",
          "dns_domain": "${ClusterDNSDomain}",
          "hosted_zone": "${ClusterHostedZone}",
          "node_type": "ComputeFleet",
          "cluster_user": "${OSUser}",
          "enable_intel_hpc_platform": "${IntelHPCPlatform}",
          "cw_logging_enabled": "${CWLoggingEnabled}",
          "scheduler_queue_name": "${QueueName}",
          "scheduler_compute_resource_name": "${ComputeResourceName}",
          "enable_efa_gdr": "${EnableEfaGdr}",
          "custom_node_package": "${CustomNodePackage}",
          "custom_awsbatchcli_package": "${CustomAwsBatchCliPackage}",
          "use_private_hostname": "${UsePrivateHostname}",
          "head_node_private_ip": "${HeadNodePrivateIp}",
          "directory_service": {
            "enabled": "${DirectoryServiceEnabled}"
          }
        }
      }
  - path: /etc/chef/client.rb
    permissions: '0644'
    owner: root:root
    content: cookbook_path ['/etc/chef/cookbooks']
  - path: /tmp/extra.json
    permissions: '0644'
    owner: root:root
    content: |
      ${ExtraJson}

--==BOUNDARY==
Content-Type: text/x-shellscript; charset="us-ascii"
MIME-Version: 1.0

#!/bin/bash -x

function error_exit
{
  instance_id=$(curl --retry 3 --retry-delay 0 --silent --fail http://169.254.169.254/latest/meta-data/instance-id)
  log_dir=/home/logs/compute
  mkdir -p ${!log_dir}
  echo "Reporting instance as unhealthy and dumping logs to ${!log_dir}/${!instance_id}.tar.gz"
  tar -czf ${!log_dir}/${!instance_id}.tar.gz /var/log
  # TODO: add possibility to disable this behavior
  # wait logs flush before signaling the failure
  sleep 10
  shutdown -h now
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
  error_exit "This AMI was not baked by ParallelCluster. Please use pcluster createami command to create an AMI by providing your AMI as parent image."
fi
if [ "${!custom_cookbook}" != "NONE" ]; then
  curl --retry 3 -v -L -o /etc/chef/aws-parallelcluster-cookbook.tgz ${!cookbook_url}
  vendor_cookbook
fi
cd /tmp

mkdir -p /etc/chef/ohai/hints
touch /etc/chef/ohai/hints/ec2.json
jq --argfile f1 /tmp/dna.json --argfile f2 /tmp/extra.json -n '$f1 * $f2' > /etc/chef/dna.json || ( echo "jq not installed or invalid extra_json"; cp /tmp/dna.json /etc/chef/dna.json)
{
  pushd /etc/chef &&
  cinc-client --local-mode --config /etc/chef/client.rb --log_level info --force-formatter --no-color --chef-zero-port 8889 --json-attributes /etc/chef/dna.json --override-runlist aws-parallelcluster::init &&
  /opt/parallelcluster/scripts/fetch_and_run -preinstall &&
  cinc-client --local-mode --config /etc/chef/client.rb --log_level info --force-formatter --no-color --chef-zero-port 8889 --json-attributes /etc/chef/dna.json --override-runlist aws-parallelcluster::config &&
  /opt/parallelcluster/scripts/fetch_and_run -postinstall &&
  cinc-client --local-mode --config /etc/chef/client.rb --log_level info --force-formatter --no-color --chef-zero-port 8889 --json-attributes /etc/chef/dna.json --override-runlist aws-parallelcluster::finalize &&
  popd
} || error_exit 'Failed to run bootstrap recipes. If --norollback was specified, check /var/log/cfn-init.log and /var/log/cloud-init-output.log.'

if [ ! -f /opt/parallelcluster/.bootstrapped ]; then
  echo ${!cookbook_version} | tee /opt/parallelcluster/.bootstrapped
fi
# End of file
--==BOUNDARY==
