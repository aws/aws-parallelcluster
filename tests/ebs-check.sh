#!/bin/bash

set -e

paths=$1
region=$2
vol_id=$3
snap_id=$4
paths=$(echo $paths | tr "," " ")
status=0

pathCount=$(cat /etc/fstab | grep -E "$(echo $paths | tr " " "|")" | wc -l | xargs)
truePathCount=$(echo $paths | tr " " "\n"| wc -l |xargs)

if [[ $pathCount == $truePathCount ]]; then
    echo "found the $truePathCount volumes"
else
    echo "error: $truePathCount volumes not found"
    exit 1
fi

if [[ $vol_id ]]; then
    volCount=$(cat /etc/fstab | grep -E "${vol_id}" | wc -l | xargs)
    if [[ $volCount == "0" ]]; then
        echo "error: $vol_id was not created"
        exit 1
    else
        echo "Success: $vol_id is created"
    fi
fi

if [[ $snap_id ]]; then
    snapCount=$(aws ec2 describe-volumes --region ${region} --filters Name=snapshot-id,Values=${snap_id} | grep -E "VolumeType" | wc -l | xargs)
    if [[ $snapCount == "0" ]]; then
        echo "error: $snap_id was not created"
        exit 1
    else
        echo "Success: $snap_id is created"
    fi
fi

computeIP=$(qhost | grep "ip-" | cut -d " " -f 1)

for path in $paths
do
    touch ${path}/master_file
    scp ${path}/master_file ${computeIP}:${path}/compute_file

    computeCheck=$(ls $path | grep "compute_file")

    if [[ $computeCheck ]]; then
        echo "$path is correctly mounted on compute"
        rm ${path}/compute_file
    else
        echo "error: $path is not found on compute"
        status=1
    fi

    rm ${path}/master_file
done

exit $status