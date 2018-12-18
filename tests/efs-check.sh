#!/bin/bash

set -e

path=${1}
fs_id=${2}
status=0

path_exist=$(cat /etc/fstab | grep "$(echo ${path})";echo $?)
fs_grep=$(cat /etc/fstab | grep "fs-";echo $?)

if [[ ${path_exist} != 1 ]] && [[ ${fs_grep} != 1 ]]; then
  echo "found the file system"
else
  echo "error: file system not found"
  exit 1
fi

if [[ ${fs_id} ]]; then
  fs_exist=$(cat /etc/fstab | grep "${fs_id}";echo $?)
  if [[ ${fs_exist} == 1 ]]; then
      echo "Error: the given ${fs_id} was not attached"
      exit 1
  else
      echo "Success: the given ${fs_id} is attached"
  fi
fi

compute_ip=$(qhost | grep "ip-" | cut -d " " -f 1)

touch ${path}/master_file
scp ${path}/master_file ${compute_ip}:${path}/compute_file

compute_check=$(ls ${path} | grep "compute_file";echo $?)

if [[ ${compute_check} != 1 ]]; then
  echo "${path} is correctly mounted on compute"
  rm ${path}/compute_file
else
  echo "error: ${path} is not found on compute"
  status=1
fi

rm ${path}/master_file

exit ${status}
