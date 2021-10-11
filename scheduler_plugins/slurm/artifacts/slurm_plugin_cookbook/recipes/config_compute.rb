# frozen_string_literal: true

#
# Cookbook:: slurm_plugin_cookbook
# Recipe:: config_compute
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

setup_munge_compute_node

# Create directory configured as SlurmdSpoolDir
directory '/var/spool/slurmd' do
  user node['slurm']['user']
  group node['slurm']['group']
  mode '0700'
end

# Check to see if is GPU instance with Nvidia installed
Chef::Log.warn('GPU instance but no Nvidia drivers found') if graphic_instance? && !nvidia_installed?

# Run nvidia-smi triggers loading of the kernel module and creation of the device files
if graphic_instance? && nvidia_installed?
  execute 'run_nvidiasmi' do
    command 'nvidia-smi'
  end
end

template '/etc/systemd/system/slurmd.service' do
  source 'slurm/slurmd.service.erb'
  owner 'root'
  group 'root'
  mode '0644'
  action :create
end

# Put supervisord config in place
template "#{node['pcluster']['local_dir']}/supervisord.conf" do
  source 'supervisord.conf.erb'
  owner 'root'
  group 'root'
  mode '0644'
end

# Put supervisord service in place
template 'supervisord-service' do
  source 'supervisord-service.erb'
  path '/etc/systemd/system/supervisord_pcluster_plugin.service'
  owner 'root'
  group 'root'
  mode '0644'
end
