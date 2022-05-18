# frozen_string_literal: true

#
# Cookbook:: slurm_plugin_cookbook
# Recipe:: finalize_head_node
#
# Copyright:: 2013-2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance with the
# License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.

# Restart supervisord
service 'supervisord_pcluster_plugin' do
  supports restart: true
  action %i(enable start)
end

execute 'check if clustermgtd heartbeat is available' do
  command "cat #{node['pcluster']['shared_dir']}/.slurm_plugin/clustermgtd_heartbeat"
  retries 30
  retry_delay 10
end

ruby_block 'wait for static fleet capacity' do
  block do
    require 'chef/mixin/shell_out'
    require 'shellwords'

    # Example output for sinfo
    # $ sinfo -N -h -o '%N %t'
    # ondemand-dy-c5.2xlarge-1 idle~
    # ondemand-dy-c5.2xlarge-2 idle~
    # spot-dy-c5.xlarge-1 idle~
    # spot-st-t2.large-1 down
    # spot-st-t2.large-2 idle
    is_fleet_ready_command = Shellwords.escape(
      "set -o pipefail && #{node['slurm']['install_dir']}/bin/sinfo -N -h -o '%N %t' | { grep -E '^[a-z0-9\\-]+\\-st\\-[a-z0-9\\-]+\\-[0-9]+ .*' || true; } | { grep -v -E '(idle|alloc|mix)$' || true; }"
    )
    until shell_out!("/bin/bash -c #{is_fleet_ready_command}").stdout.strip.empty?
      Chef::Log.info('Waiting for static fleet capacity provisioning')
      sleep(15)
    end
    Chef::Log.info('Static fleet capacity is ready')
  end
end
