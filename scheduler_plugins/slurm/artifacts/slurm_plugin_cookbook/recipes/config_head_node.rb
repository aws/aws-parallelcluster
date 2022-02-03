# frozen_string_literal: true

#
# Cookbook:: slurm_plugin_cookbook
# Recipe:: config_head_node
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

include_recipe 'slurm_plugin_cookbook::install_cluster_daemons'
# Configure hostname and DNS
include_recipe 'slurm_plugin_cookbook::init_dns'

setup_munge_head_node

# Ensure config directory is in place
directory "#{node['slurm']['install_dir']}/etc" do
  user node['plugin']['user']
  group node['plugin']['user']
  mode '0755'
end

# Create directory configured as StateSaveLocation
directory '/var/spool/slurm.state' do
  user node['slurm']['user']
  group node['slurm']['group']
  mode '0700'
end

template "#{node['slurm']['install_dir']}/etc/slurm.conf" do
  source 'slurm/slurm.conf.erb'
  owner node['plugin']['user']
  group node['plugin']['user']
  mode '0644'
end

template "#{node['slurm']['install_dir']}/etc/gres.conf" do
  source 'slurm/gres.conf.erb'
  owner node['plugin']['user']
  group node['plugin']['user']
  mode '0644'
end

# Copy pcluster config generator and templates
remote_directory "#{node['pcluster']['local_dir']}/scripts/slurm" do
  source 'head_node_slurm/slurm'
  mode '0755'
  action :create
  recursive true
end

# Generate pcluster specific configs
no_gpu = nvidia_installed? ? '' : '--no-gpu'
execute 'generate_pcluster_slurm_configs' do
  command "#{node['pcluster']['python_root']}/python #{node['pcluster']['local_dir']}/scripts/slurm/pcluster_slurm_config_generator.py"\
          " --output-directory #{node['slurm']['install_dir']}/etc/ --template-directory #{node['pcluster']['local_dir']}/scripts/slurm/templates/"\
          " --input-file #{node['pcluster']['cluster_config_path']}  --instance-types-data #{node['pcluster']['instance_types_data_path']} #{no_gpu}"
end

template "#{node['slurm']['install_dir']}/etc/cgroup.conf" do
  source 'slurm/cgroup.conf.erb'
  owner 'root'
  group 'root'
  mode '0644'
end

template "#{node['slurm']['install_dir']}/etc/slurm.sh" do
  source 'slurm/slurm.sh.erb'
  owner 'root'
  group 'root'
  mode '0755'
end

template "#{node['slurm']['install_dir']}/etc/slurm.csh" do
  source 'slurm/slurm.csh.erb'
  owner 'root'
  group 'root'
  mode '0755'
end

template "#{node['pcluster']['local_dir']}/scripts/slurm/slurm_fleet_status_manager" do
  source 'slurm/fleet_status_manager_program.erb'
  owner node['slurm']['user']
  group node['slurm']['group']
  mode '0744'
end

file "/var/log/parallelcluster/slurm_fleet_status_manager.log" do
  owner node['plugin']['fleet_mgt_user']
  group node['plugin']['fleet_mgt_user']
  mode '0644'
end

template "#{node['pcluster']['local_dir']}/parallelcluster_slurm_fleet_status_manager.conf" do
  source 'slurm/parallelcluster_slurm_fleet_status_manager.conf.erb'
  owner node['plugin']['user']
  group node['plugin']['user']
  mode '0644'
end

template "#{node['pcluster']['local_dir']}/scripts/slurm/slurm_resume" do
  source 'slurm/resume_program.erb'
  owner node['slurm']['user']
  group node['slurm']['group']
  mode '0744'
end

file '/var/log/parallelcluster/slurm_resume.log' do
  owner node['plugin']['user']
  group node['plugin']['user']
  mode '0644'
end

template "#{node['pcluster']['local_dir']}/parallelcluster_slurm_resume.conf" do
  source 'slurm/parallelcluster_slurm_resume.conf.erb'
  owner node['plugin']['user']
  group node['plugin']['user']
  mode '0644'
end

template "#{node['pcluster']['local_dir']}/scripts/slurm/slurm_suspend" do
  source 'slurm/suspend_program.erb'
  owner node['slurm']['user']
  group node['slurm']['group']
  mode '0744'
end

file '/var/log/parallelcluster/slurm_suspend.log' do
  owner node['plugin']['user']
  group node['plugin']['user']
  mode '0644'
end

template "#{node['pcluster']['local_dir']}/parallelcluster_slurm_suspend.conf" do
  source 'slurm/parallelcluster_slurm_suspend.conf.erb'
  owner node['plugin']['user']
  group node['plugin']['user']
  mode '0644'
end

template "#{node['pcluster']['local_dir']}/parallelcluster_clustermgtd.conf" do
  source 'slurm/parallelcluster_clustermgtd.conf.erb'
  owner 'root'
  group 'root'
  mode '0644'
end

# Create shared directory used to store clustermgtd heartbeat and computemgtd config
directory "#{node['pcluster']['shared_dir']}/.slurm_plugin" do
  owner node['plugin']['fleet_mgt_user']
  group node['plugin']['fleet_mgt_user']
  mode '0755'
  action :create
  recursive true
end

template "#{node['pcluster']['shared_dir']}/parallelcluster_computemgtd.conf" do
  source 'slurm/parallelcluster_computemgtd.conf.erb'
  owner 'root'
  group 'root'
  mode '0644'
end

template '/etc/systemd/system/slurmctld.service' do
  source 'slurm/slurmctld.service.erb'
  owner 'root'
  group 'root'
  mode '0644'
  action :create
end

service 'slurmctld' do
  supports restart: false
  action %i(enable start)
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
