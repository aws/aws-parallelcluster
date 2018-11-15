#!/bin/bash

set -e

path=${1}
status=0

mount_point_grep=$(cat /etc/fstab | grep "md0";echo $?)

if [[ ! -z ${path} ]]
then
  path_exist=$(cat /etc/fstab | grep "${path}";echo $?)

  if [[ ${path_exist} != 1 ]] && [[ ${mount_point_grep} != 1 ]]
  then
    echo "Success: found the RAID array"
  else
    echo "Error: RAID array not found"
    exit 1
  fi

  compute_ip=$(qhost | grep "ip-" | cut -d " " -f 1)

  touch ${path}/master_file
  scp ${path}/master_file ${compute_ip}:${path}/compute_file

  compute_check=$(ls ${path} | grep "compute_file";echo $?)

  if [[ ${compute_check} != 1 ]]
  then
    echo "Success: ${path} is correctly mounted on compute"
    rm ${path}/compute_file
  else
    echo "Error: ${path} is not found on compute"
    status=1
  fi

  rm ${path}/master_file
else
  if [[ ${mount_point_grep} == 1 ]]
  then
    echo "Success: RAID array does not exist in default case"
  else
    echo "Error: RAID found in default case"
    exit 1
  fi
fi

exit ${status}
