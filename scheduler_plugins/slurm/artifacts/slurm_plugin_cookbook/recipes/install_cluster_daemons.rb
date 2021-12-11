# frozen_string_literal: true

#
# Cookbook:: slurm_plugin_cookbook
# Recipe:: install_cluster_daemons
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

bash 'install' do
  user node['plugin']['user']
  group node['plugin']['user']
  code <<-DAEMONS
    set -e

    # FIXME: installing from GitHub is discouraged
    #{node['pcluster']['python_root']}/pip install https://github.com/aws/aws-parallelcluster-node/tarball/refs/heads/develop
  DAEMONS
  not_if "#{node['pcluster']['python_root']}/pip list | grep aws-parallelcluster-node"
end
