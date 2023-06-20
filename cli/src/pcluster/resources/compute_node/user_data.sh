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
output:
  all: "| tee -a /var/log/cloud-init-output.log | logger -t user-data -s 2>/dev/console"
write_files:
  - path: /tmp/dna.json
    permissions: '0644'
    owner: root:root
    content: |
      {
        "cluster": {
          "cluster_name": "${ClusterName}",
          "stack_name": "${AWS::StackName}",
          "stack_arn": "${AWS::StackId}",
          "enable_efa": "${EnableEfa}",
          "raid_shared_dir": "${RAIDSharedDir}",
          "raid_type": "${RAIDType}",
          "base_os": "${BaseOS}",
          "region": "${AWS::Region}",
          "efs_fs_ids": "${EFSIds}",
          "efs_shared_dirs": "${EFSSharedDirs}",
          "efs_encryption_in_transits": "${EFSEncryptionInTransits}",
          "efs_iam_authorizations": "${EFSIamAuthorizations}",
          "fsx_fs_ids": "${FSXIds}",
          "fsx_mount_names": "${FSXMountNames}",
          "fsx_dns_names": "${FSXDNSNames}",
          "fsx_volume_junction_paths": "${FSXVolumeJunctionPaths}",
          "fsx_fs_types": "${FSXFileSystemTypes}",
          "fsx_shared_dirs": "${FSXSharedDirs}",
          "scheduler": "${Scheduler}",
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
          "log_rotation_enabled": "${LogRotationEnabled}",
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
  - path: /tmp/bootstrap.sh
    permissions: '0744'
    owner: root:root
    content: |
      #!/bin/bash -x

      function error_exit
      {
        echo "Bootstrap failed with error: $1"
        # wait logs flush before signaling the failure
        sleep 10
        # TODO: add possibility to override this behavior and keep the instance for debugging
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

      function publish_startup_time
      {
        start_time=$1
        end_time=$2
        # Only put the startup time data if the scheduler is slurm
        slurm_node_path=/etc/parallelcluster/slurm_plugin/slurm_node_spec.json
        if test -f "$slurm_node_path"; then
            INSTANCE_ID=$(cat $slurm_node_path | jq -r .instance_id)
            INSTANCE_TYPE=$(cat $slurm_node_path | jq -r .'compute."instance-type"')
            aws cloudwatch put-metric-data --namespace "ParallelCluster" --metric-name "StartupTime" --value $(($end_time-$start_time)) --dimensions "InstanceID=${!INSTANCE_ID},InstanceType=${!INSTANCE_TYPE},ClusterName=${ClusterName}" --region "${AWS::Region}"
        fi
      }

      [ -f /etc/profile.d/proxy.sh ] && . /etc/profile.d/proxy.sh

      # Configure AWS CLI using the expected overrides, if any.
      [ -f /etc/profile.d/aws-cli-default-config.sh ] && . /etc/profile.d/aws-cli-default-config.sh

      custom_cookbook=${CustomChefCookbook}
      export _region=${AWS::Region}

      s3_url=${AWS::URLSuffix}
      if [ "${!custom_cookbook}" != "NONE" ]; then
        if [[ "${!custom_cookbook}" =~ ^s3://([^/]*)(.*) ]]; then
          # Set the socket connection timeout to 15s. Emperically, it seems like the actual
          # timeout is 8x(cli-connect-timeout). i.e. if cli-connection-timeout is set to
          # 60s, the call will timeout the connect attempt at 8m. Setting it to 15s, causes
          # each attempt to take 240s, so 2m * 3 attempts will result in a failure after 6
          # minutes.
          S3API_RESULT=$(AWS_RETRY_MODE=standard aws s3api get-bucket-location --cli-connect-timeout 15 --bucket ${!BASH_REMATCH[1]} --region ${AWS::Region} 2>&1) || error_exit "${!S3API_RESULT}"
          bucket_region=$(echo "${!S3API_RESULT}" | jq -r '.LocationConstraint')
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
          cookbook_version_number=$(echo ${!cookbook_version} | awk -F- '{print $NF}')
          installed_version_number=$(echo ${!installed_version} | awk -F- '{print $NF}')
          error_exit "This AMI was created with ParallelCluster ${!installed_version_number}, but is trying to be used with ParallelCluster ${!cookbook_version_number}. Please either use an AMI created with ParallelCluster ${!cookbook_version_number} or change your ParallelCluster to ${!installed_version_number}"
        fi
      else
        error_exit "This AMI was not baked by ParallelCluster. Please use pcluster build-image command to create an AMI by providing your AMI as parent image."
      fi
      if [ "${!custom_cookbook}" != "NONE" ]; then
        curl --retry 3 -v -L -o /etc/chef/aws-parallelcluster-cookbook.tgz ${!cookbook_url}
        vendor_cookbook
      fi
      cd /tmp

      mkdir -p /etc/chef/ohai/hints
      touch /etc/chef/ohai/hints/ec2.json

      # measure start time
      start=$(date +%s)

      jq --argfile f1 /tmp/dna.json --argfile f2 /tmp/extra.json -n '$f1 * $f2' > /etc/chef/dna.json || ( echo "jq not installed or invalid extra_json"; cp /tmp/dna.json /etc/chef/dna.json)
      {
        pushd /etc/chef &&
        cinc-client --local-mode --config /etc/chef/client.rb --log_level info --force-formatter --no-color --chef-zero-port 8889 --json-attributes /etc/chef/dna.json --override-runlist aws-parallelcluster-entrypoints::init &&
        /opt/parallelcluster/scripts/fetch_and_run -preinstall &&
        cinc-client --local-mode --config /etc/chef/client.rb --log_level info --force-formatter --no-color --chef-zero-port 8889 --json-attributes /etc/chef/dna.json --override-runlist aws-parallelcluster-entrypoints::config &&
        /opt/parallelcluster/scripts/fetch_and_run -postinstall &&
        cinc-client --local-mode --config /etc/chef/client.rb --log_level info --force-formatter --no-color --chef-zero-port 8889 --json-attributes /etc/chef/dna.json --override-runlist aws-parallelcluster-entrypoints::finalize &&
        popd
      } || error_exit 'Failed to run bootstrap recipes. If --norollback was specified, check /var/log/cfn-init.log and /var/log/cloud-init-output.log.'

      if [ ! -f /opt/parallelcluster/.bootstrapped ]; then
        echo ${!cookbook_version} | tee /opt/parallelcluster/.bootstrapped
      fi

      # measure end time
      end=$(date +%s)

      if [ "${ComputeStartupTimeMetricEnabled}" = "True" ]; then
        publish_startup_time $start $end || echo "[WARNING] failed to push the StartupTime metric to CloudWatch."
      fi

--==BOUNDARY==
Content-Type: text/x-shellscript; charset="us-ascii"
MIME-Version: 1.0

#!/bin/bash -x

function error_exit
{
  echo "Timed-out when bootstrapping instance"
  sleep 10  # Allow logs to propagate
  shutdown -h now
  exit 1
}

if [ "${Timeout}" == "NONE" ]; then
  /tmp/bootstrap.sh
else
  timeout ${Timeout} /tmp/bootstrap.sh || error_exit
fi

# End of file
--==BOUNDARY==
