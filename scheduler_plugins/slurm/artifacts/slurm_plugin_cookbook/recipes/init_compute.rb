# frozen_string_literal: true

#
# Cookbook:: slurm_plugin_cookbook
# Recipe:: init_compute
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

ruby_block 'retrieve compute node info' do
  block do
    slurm_nodename = get_node_info
    node.force_default['slurm_nodename'] = slurm_nodename
  end
  retries 5
  retry_delay 3
  not_if do
    !node['slurm_nodename'].nil? && !node['slurm_nodename'].empty?
  end
end

file "#{node['pcluster']['local_dir']}/slurm_nodename" do
  content(lazy { node['slurm_nodename'] })
  mode '0644'
  owner 'root'
  group 'root'
end

# Configure hostname and DNS
include_recipe 'slurm_plugin_cookbook::init_dns'
