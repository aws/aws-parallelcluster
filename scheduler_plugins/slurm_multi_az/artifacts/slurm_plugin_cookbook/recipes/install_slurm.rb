# frozen_string_literal: true

#
# Cookbook:: slurm_plugin_cookbook
# Recipe:: install_slurm
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

# FIXME: assuming Slurm dependencies already exists (packages, Munge, PMIx)

slurm_build_deps = value_for_platform(
  'ubuntu' => {
    'default' => %w(libjson-c-dev libhttp-parser-dev),
  },
  'default' => %w(json-c-devel http-parser-devel)
)

package slurm_build_deps do
  retries 3
  retry_delay 5
end

slurm_tarball = "#{node['pcluster']['local_dir']}/slurm-#{node['slurm']['version']}.tar.gz"

# Get slurm tarball
remote_file slurm_tarball do
  source node['slurm']['url']
  mode '0644'
  retries 3
  retry_delay 5
  not_if { ::File.exist?(slurm_tarball) }
end

# Validate the authenticity of the downloaded archive based on the checksum published by SchedMD
ruby_block 'Validate Slurm Tarball Checksum' do
  block do
    require 'digest'
    checksum = Digest::SHA1.file(slurm_tarball).hexdigest # nosemgrep
    raise "Downloaded Tarball Checksum #{checksum} does not match expected checksum #{node['slurm']['sha1']}" if checksum != node['slurm']['sha1']
  end
end

# Install Slurm
bash 'make install' do
  user 'root'
  group 'root'
  cwd Chef::Config[:file_cache_path]
  code <<-SLURM
    set -e

    tar xf #{slurm_tarball}
    cd slurm-slurm-#{node['slurm']['version']}
    ./configure --prefix=#{node['slurm']['install_dir']} --with-pmix=/opt/pmix --enable-slurmrestd
    CORES=$(grep processor /proc/cpuinfo | wc -l)
    make -j $CORES
    make install
    make install-contrib
  SLURM
  creates "#{node['slurm']['install_dir']}/bin/srun"
end
