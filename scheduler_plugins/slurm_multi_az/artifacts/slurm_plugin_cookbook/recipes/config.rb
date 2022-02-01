# frozen_string_literal: true

#
# Cookbook:: slurm_plugin_cookbook
# Recipe:: config
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

case node['pcluster']['node_type']
when 'head'
  include_recipe 'slurm_plugin_cookbook::config_head_node'
when 'compute'
  include_recipe 'slurm_plugin_cookbook::config_compute'
else
  raise 'node_type must be head or compute'
end

link '/etc/profile.d/slurm.sh' do
  to "#{node['slurm']['install_dir']}/etc/slurm.sh"
end

link '/etc/profile.d/slurm.csh' do
  to "#{node['slurm']['install_dir']}/etc/slurm.csh"
end

# Ensure cluster admin user and slurm user can sudo on slurm commands.
# This permission is necessary for the cluster admin user, but it is not for the slurm user
# because the latter can run slurm commands without being root.
# We introduced it for sake of consistency because daemons and slurm suspend/resume scripts share the same code.
template '/etc/sudoers.d/99-parallelcluster-slurm' do
  source 'slurm/99-parallelcluster-slurm.erb'
  owner 'root'
  group 'root'
  mode '0600'
end
