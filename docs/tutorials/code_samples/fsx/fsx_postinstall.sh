#!/usr/bin/env bash

. /etc/parallelcluster/cfnconfig

fsid=$2
mnt=$3

if [ "x${fsid}" == "x" ]; then
  echo "ERROR: You must provide the FSx File System Id i.e. fs-00079dd40d69349ce"
  exit 1
fi
if [ "x${mnt}" == "x" ]; then
  mnt=/fsx
fi

# Install lustre drivers
wget https://downloads.whamcloud.com/public/lustre/lustre-2.10.5/el7.5.1804/client/RPMS/x86_64/kmod-lustre-client-2.10.5-1.el7.x86_64.rpm
wget https://downloads.whamcloud.com/public/lustre/lustre-2.10.5/el7.5.1804/client/RPMS/x86_64/lustre-client-2.10.5-1.el7.x86_64.rpm

yum localinstall -y *lustre-client-2.10.5*.rpm

# Mount the file system

mkdir -p ${mnt}

mount -t lustre "${fsid}.fsx.${cfn_region}.amazonaws.com@tcp:/fsx" "${mnt}"