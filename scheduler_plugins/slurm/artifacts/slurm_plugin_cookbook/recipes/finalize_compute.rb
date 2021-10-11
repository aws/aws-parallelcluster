# frozen_string_literal: true

#
# Cookbook:: slurm_plugin_cookbook
# Recipe:: finalize_compute
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

ruby_block 'get_compute_nodename' do
  block do
    node.run_state['slurm_nodename'] = slurm_nodename
  end
end

directory '/etc/sysconfig' do
  user 'root'
  group 'root'
  mode '0644'
end

template '/etc/sysconfig/slurmd' do
  source 'slurm/slurm.sysconfig.erb'
  user 'root'
  group 'root'
  mode '0644'
end

service 'slurmd' do
  supports restart: false
  action %i(enable start)
  not_if { node['kitchen'] }
end

execute 'resume_node' do
  # Always try to resume a static node on start up
  # Command will fail if node is already in IDLE, ignoring failure
  command(lazy { "#{node['slurm']['install_dir']}/bin/scontrol update nodename=#{node.run_state['slurm_nodename']} state=resume reason='Node start up'" })
  ignore_failure true
  # Only resume static nodes
  only_if { is_static_node?(node.run_state['slurm_nodename']) }
end
