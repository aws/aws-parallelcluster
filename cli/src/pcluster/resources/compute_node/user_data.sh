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

output:
  all: "| tee -a /var/log/cloud-init-output.log | logger -t user-data -s 2>/dev/console"
write_files:
  - path: /tmp/dna.json
    permissions: '0644'
    owner: root:root
    content: |
      {
        "cfncluster": {
          "stack_name": "${AWS::StackName}",
          "enable_efa": "${EnableEfa}",
          "cfn_raid_parameters": "${RAIDOptions}",
          "cfn_base_os": "${BaseOS}",
          "cfn_preinstall": "${PreInstallScript}",
          "cfn_preinstall_args": "${PreInstallArgs}",
          "cfn_postinstall": "${PostInstallScript}",
          "cfn_postinstall_args": "${PostInstallArgs}",
          "cfn_region": "${AWS::Region}",
          "cfn_efs": "${EFSId}",
          "cfn_efs_shared_dir": "${EFSOptions}",
          "cfn_fsx_fs_id": "${FSXId}",
          "cfn_fsx_options": "${FSXOptions}",
          "cfn_scheduler": "${Scheduler}",
          "cfn_disable_hyperthreading_manually": "${DisableHyperThreadingManually}",
          "cfn_encrypted_ephemeral": "${EncryptedEphemeral}",
          "cfn_ephemeral_dir": "${EphemeralDir}",
          "cfn_shared_dir": "${EbsSharedDirs}",
          "cfn_proxy": "${ProxyServer}",
          "cfn_ddb_table": "${DynamoDBTable}",
          "cfn_log_group_name": "${LogGroupName}",
          "cfn_dns_domain": "${ClusterDNSDomain}",
          "cfn_hosted_zone": "${ClusterHostedZone}",
          "cfn_node_type": "ComputeFleet",
          "cfn_cluster_user": "${OSUser}",
          "enable_intel_hpc_platform": "${IntelHPCPlatform}",
          "cfn_cluster_cw_logging_enabled": "${CWLoggingEnabled}",
          "scheduler_queue_name": "${QueueName}",
          "enable_efa_gdr": "${EnableEfaGdr}"
        },
        "run_list": "recipe[aws-parallelcluster::${Scheduler}_config]"
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
  region=${AWS::Region}
  instance_id=$(curl --retry 3 --retry-delay 0 --silent --fail http://169.254.169.254/latest/meta-data/instance-id)
  log_dir=/home/logs/compute
  mkdir -p ${!log_dir}
  echo "Reporting instance as unhealthy and dumping logs to ${!log_dir}/${!instance_id}.tar.gz"
  tar -czf ${!log_dir}/${!instance_id}.tar.gz /var/log
  # TODO: add possibility to disable this behavior
  # wait logs flush before signaling the failure
  sleep 10
  aws --region ${!region} ec2 terminate-instances --instance-ids ${!instance_id}
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
    apt-cache search build-essential; apt-get clean; apt update -y; apt-get -y install build-essential curl wget jq python-setuptools awscli python3-pip
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
s3_url=${AWS::URLSuffix}
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

mkdir -p /etc/chef/ohai/hints
touch /etc/chef/ohai/hints/ec2.json
jq --argfile f1 /tmp/dna.json --argfile f2 /tmp/extra.json -n '$f1 + $f2 | .cfncluster = $f1.cfncluster + $f2.cfncluster' > /etc/chef/dna.json || ( echo "jq not installed or invalid extra_json"; cp /tmp/dna.json /etc/chef/dna.json)
{
  pushd /etc/chef &&
  chef-client --local-mode --config /etc/chef/client.rb --log_level auto --force-formatter --no-color --chef-zero-port 8889 --json-attributes /etc/chef/dna.json --override-runlist aws-parallelcluster::prep_env &&
  /opt/parallelcluster/scripts/fetch_and_run -preinstall &&
  chef-client --local-mode --config /etc/chef/client.rb --log_level auto --force-formatter --no-color --chef-zero-port 8889 --json-attributes /etc/chef/dna.json &&
  /opt/parallelcluster/scripts/fetch_and_run -postinstall &&
  chef-client --local-mode --config /etc/chef/client.rb --log_level auto --force-formatter --no-color --chef-zero-port 8889 --json-attributes /etc/chef/dna.json --override-runlist aws-parallelcluster::finalize &&
  popd
} || error_exit 'Failed to run bootstrap recipes. If --norollback was specified, check /var/log/cfn-init.log and /var/log/cloud-init-output.log.'

if [ ! -f /opt/parallelcluster/.bootstrapped ]; then
  echo ${!cookbook_version} | tee /opt/parallelcluster/.bootstrapped
fi
# End of file
--==BOUNDARY==
