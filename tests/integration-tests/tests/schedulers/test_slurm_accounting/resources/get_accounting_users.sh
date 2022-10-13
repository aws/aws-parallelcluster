#!/bin/bash
get_setting_value() {
  local _file=$1
  local _search=$2
  local _pattern

  _pattern=$(grep "${_search}" "${_file}")
  echo "${_pattern}" | tr -d '\n' | cut -d = -f 2 | xargs
}

# Get the root user (root is added to Slurm accounting by default during configuration)
getent passwd 0 | cut -d : -f 1
# Get the configured cluster user name from the dna.json (added to the database during node configuration)
jq -r '.cluster.cluster_user' < "/etc/chef/dna.json"
# Get the configured Slurm user from the slurm configuration (added to the database during node configuration)
get_setting_value "/opt/slurm/etc/slurm.conf" "^SlurmUser="
