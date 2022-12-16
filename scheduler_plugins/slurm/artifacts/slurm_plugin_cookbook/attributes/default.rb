# Copyright:: 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
require 'yaml'
require 'json'

default['pcluster']['cluster_name'] = ENV['PCLUSTER_CLUSTER_NAME']
default['pcluster']['local_dir'] = ENV['PCLUSTER_LOCAL_SCHEDULER_PLUGIN_DIR']
default['pcluster']['shared_dir'] = ENV['PCLUSTER_SHARED_SCHEDULER_PLUGIN_DIR']
default['pcluster']['region'] = ENV['PCLUSTER_AWS_REGION']
default['pcluster']['cluster_config_path'] = ENV['PCLUSTER_CLUSTER_CONFIG']
default['pcluster']['previous_cluster_config_path'] = ENV['PCLUSTER_CLUSTER_CONFIG_OLD']
default['pcluster']['cluster_config'] = YAML.safe_load(File.read(node['pcluster']['cluster_config_path']))
default['pcluster']['launch_templates_config_path'] = ENV['PCLUSTER_LAUNCH_TEMPLATES']
default['pcluster']['launch_templates_config'] = JSON.load_file(node['pcluster']['launch_templates_config_path'])
default['pcluster']['cfn_stack_outputs_file'] = ENV['PCLUSTER_SCHEDULER_PLUGIN_CFN_SUBSTACK_OUTPUTS']
default['pcluster']['cfn_stack_outputs'] = JSON.load_file(node['pcluster']['cfn_stack_outputs_file']) unless node['pcluster']['cfn_stack_outputs_file'].nil?
default['pcluster']['instance_types_data_path'] = ENV['PCLUSTER_INSTANCE_TYPES_DATA']
default['pcluster']['node_type'] = ENV['PCLUSTER_NODE_TYPE']
default['pcluster']['python_root'] = ENV['PCLUSTER_PYTHON_ROOT']

default['slurm']['version'] = '22-05-6-1'
default['slurm']['url'] = "https://github.com/SchedMD/slurm/archive/slurm-#{node['slurm']['version']}.tar.gz"
default['slurm']['sha1'] = 'bd2fbc4f6fcf41bfce899eaac0d92d9f09996cd3'
default['slurm']['user'] = 'slurm-user'
default['slurm']['group'] = node['slurm']['user']
default['slurm']['install_dir'] = "#{node['pcluster']['shared_dir']}/slurm"

default['munge']['user'] = 'munge'
default['munge']['group'] = node['munge']['user']

default['plugin']['user'] = 'pcluster-scheduler-plugin'
default['plugin']['fleet_mgt_user'] = 'fleet-mgt-user'
default['dns']['domain'] = "#{node['pcluster']['cluster_name']}.pcluster"
