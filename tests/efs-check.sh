#!/bin/bash

set -e

paths=${1}
fs_id=${2}
paths=$(echo ${paths} | tr "," " ")
status=0

pathCount=$(cat /etc/fstab | grep -E "$(echo ${paths} | tr " " "|")" | wc -l | xargs)
fsGrep=$(cat /etc/fstab | grep -E "fs-" | wc -l | xargs)
truePathCount=$(echo ${paths} | tr " " "\n"| wc -l |xargs)

if [ ${pathCount} == ${truePathCount} ] && [ ${fsGrep} == ${truePathCount} ]; then
    echo "found the file system"
else
    echo "error: file system not found"
    exit 1
fi

if [[ ${fs_id} ]]; then
    fsCount=$(cat /etc/fstab | grep -E "${fs_id}" | wc -l | xargs)
    if [[ ${fsCount} == "0" ]]; then
        echo "Error: the given ${fs_id} was not attached"
        exit 1
    else
        echo "Success: the given ${fs_id} is attached"
    fi
fi

computeIP=$(qhost | grep "ip-" | cut -d " " -f 1)

for path in ${paths}
do
    touch ${path}/master_file
    scp ${path}/master_file ${computeIP}:${path}/compute_file

    computeCheck=$(ls ${path} | grep "compute_file")

    if [[ ${computeCheck} ]]; then
        echo "${path} is correctly mounted on compute"
        rm ${path}/compute_file
    else
        echo "error: ${path} is not found on compute"
        status=1
    fi

    rm ${path}/master_file
done

exit ${status}
