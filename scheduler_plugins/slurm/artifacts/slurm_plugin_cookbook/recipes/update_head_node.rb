# frozen_string_literal: true

#
# Cookbook:: slurm_plugin_cookbook
# Recipe:: update_head_node
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

unless ::FileUtils.identical?(node['pcluster']['previous_cluster_config_path'], node['pcluster']['cluster_config_path'])
  # Generate pcluster specific configs
  no_gpu = nvidia_installed? ? "" : "--no-gpu"
  execute "generate_pcluster_slurm_configs" do
    command "#{node['pcluster']['python_root']}/python #{node['pcluster']['local_dir']}/scripts/slurm/pcluster_slurm_config_generator.py" \
            " --output-directory #{node['slurm']['install_dir']}/etc/" \
            " --template-directory #{node['pcluster']['local_dir']}/scripts/slurm/templates/" \
            " --input-file #{node['pcluster']['cluster_config_path']}" \
            " --instance-types-data #{node['pcluster']['instance_types_data_path']}" \
            " #{no_gpu}"
  end

  execute 'stop clustermgtd' do
    command "#{node['pcluster']['python_root']}/supervisorctl -c #{node['pcluster']['local_dir']}/supervisord.conf stop clustermgtd"
  end

  service 'slurmctld' do
    action :restart
  end

  execute 'reload config for running nodes' do
    command "#{node['slurm']['install_dir']}/bin/scontrol reconfigure && sleep 15"
    retries 3
    retry_delay 5
  end

  execute 'start clustermgtd' do
    command "#{node['pcluster']['python_root']}/supervisorctl -c #{node['pcluster']['local_dir']}/supervisord.conf start clustermgtd"
  end
end
