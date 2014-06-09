#!/bin/bash

# Copyright 2013-2014 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Amazon Software License (the "License"). You may not use this file except in compliance with the
# License. A copy of the License is located at
#
# http://aws.amazon.com/asl/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES 
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.

set -x
echo "Determining the MAC address on eth0"
ETH0_MAC=`/sbin/ifconfig  | /bin/grep eth0 | awk '{print tolower($5)}' | grep '^[0-9a-f]\{2\}\(:[0-9a-f]\{2\}\)\{5\}$'`
if [ $? -ne 0 ] ; then
   echo "Unable to determine MAC address on eth0" | logger -t "ec2"
   exit 1
fi
echo "Found MAC: ${ETH0_MAC} on eth0" | logger -t "ec2"


VPC_CIDR_URI="http://169.254.169.254/latest/meta-data/network/interfaces/macs/${ETH0_MAC}/vpc-ipv4-cidr-block"
echo "Metadata location for vpc ipv4 range: ${VPC_CIDR_URI}" | logger -t "ec2"

VPC_CIDR_RANGE=`curl --retry 3 --retry-delay 0 --silent --fail ${VPC_CIDR_URI}`
if [ $? -ne 0 ] ; then
   echo "Unable to retrive VPC CIDR range from meta-data. Using 0.0.0.0/0 instead. PAT may not function correctly" | logger -t "ec2"
   VPC_CIDR_RANGE="0.0.0.0/0"
else
   echo "Retrived the VPC CIDR range: ${VPC_CIDR_RANGE} from meta-data" |logger -t "ec2"
fi

echo 1 >  /proc/sys/net/ipv4/ip_forward && \
   echo 0 >  /proc/sys/net/ipv4/conf/eth0/send_redirects && \
   /sbin/iptables -t nat -A POSTROUTING -o eth0 -s ${VPC_CIDR_RANGE} -j MASQUERADE

if [ $? -ne 0 ] ; then
   echo "Configuration of PAT failed" | logger -t "ec2"
   exit 0
fi

echo "Configuration of PAT complete" |logger -t "ec2"
exit 0
