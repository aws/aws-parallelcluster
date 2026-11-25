# Adapted from the upstream aws-samples/aws-parallelcluster-post-install-scripts recipe:
#   https://raw.githubusercontent.com/aws-samples/aws-parallelcluster-post-install-scripts/main/rest-api/slurm_rest_api.rb
#
# Changes from upstream:
#   - Run `apt-get update` before installing nginx on Debian/Ubuntu to avoid stale package
#     index 404 errors.

slurm_etc = '/opt/slurm/etc'
slurm_conf = "#{slurm_etc}/slurm.conf"
slurmdbd_conf = "#{slurm_etc}/slurmdbd.conf"
socket_location = '/var/spool/socket'
state_save_location = '/var/spool/slurm.state'
key_location = "#{state_save_location}/jwt_hs256.key"
token_name = "slurm_token_#{node['cluster']['stack_name']}"
token_lifespan = 1800
id = 2005

if node['cluster']['node_type'] != 'HeadNode'
  raise "Slurm REST API post-install script must be run on a HeadNode"
end

if !::File.exist?(slurmdbd_conf)
  raise "#{slurmdbd_conf} not found. Slurm accounting may need to be enabled to use the Slurm REST API."
end

# Configure Slurm for JWT authentication
ruby_block 'Create JWT key file' do
  block do
    shell_out!("dd if=/dev/random of=#{key_location} bs=32 count=1")
  end
end

file key_location do
  owner 'slurm'
  group 'slurm'
  mode '0600'
end

directory state_save_location do
  owner 'slurm'
  group 'slurm'
  mode '0755'
end

ruby_block 'Add JWT configuration to slurm.conf' do
  block do
    file = Chef::Util::FileEdit.new(slurm_conf)
    file.insert_line_after_match(/AuthType=*/, "AuthAltParameters=jwt_key=#{key_location}")
    file.insert_line_after_match(/AuthType=*/, "AuthAltTypes=auth/jwt")
    file.write_file
  end
  not_if "grep -q auth/jwt #{slurm_conf}"
end

ruby_block 'Add JWT configuration to slurmdbd.conf' do
  block do
    file = Chef::Util::FileEdit.new(slurmdbd_conf)
    file.insert_line_after_match(/AuthType=*/, "AuthAltParameters=jwt_key=#{key_location}")
    file.insert_line_after_match(/AuthType=*/, "AuthAltTypes=auth/jwt")
    file.write_file
  end
  not_if "grep -q auth/jwt #{slurmdbd_conf}"
end

service 'slurmctld' do
  action :restart
end

service 'slurmdbd' do
  action :restart
end

ruby_block 'Generate JWT token and create/update AWS secret' do
  block do

    jwt_token = shell_out!("/opt/slurm/bin/scontrol token \
      lifespan=#{token_lifespan} \
      | grep -oP '^SLURM_JWT\\s*\\=\\s*\\K(.+)'").run_command.stdout

    begin
      shell_out!("aws secretsmanager create-secret \
        --name #{token_name} \
        --region #{node['cluster']['region']} \
        --secret-string #{jwt_token}"
      ).run_command
      Chef::Log.warn("Created secret #{token_name}. This must be deleted manually on cluster deletion.")
    rescue
      shell_out!("aws secretsmanager update-secret \
        --secret-id #{token_name} \
        --region #{node['cluster']['region']} \
        --secret-string #{jwt_token}"
      ).run_command
    end
  end
end

cron 'rotate JWT token' do
  minute '*/20'
  command "/opt/parallelcluster/scripts/rotate_jwt.sh #{token_name} #{node['cluster']['region']} #{token_lifespan}"
end

# NGINX installation and configuration
# On Debian/Ubuntu, refresh the package index first to avoid 404 errors from stale cached
# package versions that have been superseded in the upstream repositories.
execute 'apt-get update' do
  command 'apt-get update'
  only_if { platform_family?('debian') }
end

package 'nginx' do
  action :install
end

ruby_block 'Generate self-signed key' do
  block do
    shell_out!("sudo openssl req -x509 -nodes -days 36500 -newkey rsa:2048 \
      -keyout /etc/ssl/certs/nginx-selfsigned.key \
      -out /etc/ssl/certs/nginx-selfsigned.crt \
      -subj ""/CN=#{node['cluster']['stack_name']}"""
    ).run_command
  end
end

group 'nginx' do
  comment 'nginx group'
  gid id + 1
  system true
end

user 'nginx' do
  comment 'nginx user'
  uid id + 1
  gid id + 1
  system true
end

file '/etc/nginx/nginx.conf' do
  owner 'nginx'
  group 'nginx'
  mode '0644'
  content ::File.open('/tmp/slurm_rest_api/nginx.conf').read
end

service 'nginx' do
  action :start
end

# Enable slurmrestd
group 'slurmrestd' do
  comment 'slurmrestd group'
  gid id
  system true
end

user 'slurmrestd' do
  comment 'slurmrestd user'
  uid id
  gid id
  system true
end

directory socket_location do
  owner 'nginx'
  group 'nginx'
  mode '0777'
end

file '/etc/systemd/system/slurmrestd.service' do
  owner 'slurmrestd'
  group 'slurmrestd'
  mode '0644'
  content ::File.open('/tmp/slurm_rest_api/slurmrestd.service').read
end

service 'slurmrestd' do
  action :start
end

ruby_block 'Wait for slurmrestd' do
  block do
    iter=0
    until ::File.exist?("#{socket_location}/slurmrestd.sock") || iter > 20 do
      sleep 1
      iter += 1
    end
    raise "Timeout waiting for slurmrestd startup" unless iter < 20
  end
end

ruby_block 'Modify socket permissions' do
  notifies :start, 'service[slurmrestd]', :before
  block do
    shell_out!("chmod 0666 #{socket_location}/slurmrestd.sock").run_command
  end
end
