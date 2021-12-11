# frozen_string_literal: true

#
# Cookbook:: slurm_plugin_cookbook
# Recipe:: init_dns
#
# Copyright:: 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License").
# You may not use this file except in compliance with the License.
# A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file.
# This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, express or implied.
# See the License for the specific language governing permissions and limitations under the License.

if !node['dns']['domain'].nil? && !node['dns']['domain'].empty?
  # Configure custom dns domain (only if defined) by appending the Route53 domain created within the cluster
  # ($CLUSTER_NAME.pcluster) and be listed as a "search" domain in the resolv.conf file.
  if platform?('ubuntu')

    Chef::Log.info("Appending search domain '#{node['dns']['domain']}' to /etc/systemd/resolved.conf")
    # Configure resolved to automatically append Route53 search domain in resolv.conf.
    # On Ubuntu18 resolv.conf is managed by systemd-resolved.
    replace_or_add 'append Route53 search domain in /etc/systemd/resolved.conf' do
      path '/etc/systemd/resolved.conf'
      pattern 'Domains=*'
      line "Domains=#{node['dns']['domain']}"
    end
  else

    Chef::Log.info("Appending search domain '#{node['dns']['domain']}' to /etc/dhcp/dhclient.conf")
    # Configure dhclient to automatically append Route53 search domain in resolv.conf
    # - on CentOS7 and Alinux2 resolv.conf is managed by NetworkManager + dhclient,
    replace_or_add 'append Route53 search domain in /etc/dhcp/dhclient.conf' do
      path '/etc/dhcp/dhclient.conf'
      pattern 'append domain-name*'
      line "append domain-name \" #{node['dns']['domain']}\";"
    end
  end
  restart_network_service
end

if node['pcluster']['node_type'] == 'compute'
  # For compute node retrieve assigned hostname from DynamoDB and configure it
  # - hostname: $QUEUE-st-$INSTANCE_TYPE_1-[1-$MIN1]
  # - fqdn: $QUEUE-st-$INSTANCE_TYPE_1-[1-$MIN1].$CLUSTER_NAME.pcluster
  ruby_block 'retrieve assigned hostname' do
    block do
      node.force_default['assigned_short_hostname'] = node['slurm_nodename'].to_s

      if node['dns']['domain'].nil? || node['dns']['domain'].empty?
        # Use domain from DHCP
        dhcp_domain = node['ec2']['local_hostname'].split('.', 2).last
        node.force_default['assigned_hostname'] = "#{node['assigned_short_hostname']}.#{dhcp_domain}"
      else
        # Use cluster domain
        node.force_default['assigned_hostname'] = "#{node['assigned_short_hostname']}.#{node['dns']['domain']}"
      end
    end
    retries 5
    retry_delay 3
  end

else
  # Head node
  node.force_default['assigned_hostname'] = node['ec2']['local_hostname']
  node.force_default['assigned_short_hostname'] = node['ec2']['local_hostname'].split('.')[0].to_s
end

# Configure short hostname
hostname 'set short hostname' do
  compile_time false
  hostname(lazy { node['assigned_short_hostname'] })
end

# Resource to be called to reload ohai attributes after /etc/hosts update
ohai 'reload_hostname' do
  plugin 'hostname'
  action :nothing
end

# Configure fqdn in /etc/hosts
replace_or_add 'set fqdn in the /etc/hosts' do
  path '/etc/hosts'
  pattern "^#{node['ec2']['local_ipv4']}\s+"
  line(lazy { "#{node['ec2']['local_ipv4']} #{node['assigned_hostname']} #{node['assigned_short_hostname']}" })
  notifies :reload, 'ohai[reload_hostname]'
end
