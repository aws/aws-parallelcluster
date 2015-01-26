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

__author__ = 'dougalb'

import boto.ec2
import boto.vpc
import urllib2
from urlparse import urlparse
import boto.exception
import sys

def check_resource(region, aws_access_key_id, aws_secret_access_key, resource_type,resource_value):

    # Loop over all supported resource checks
    # EC2 KeyPair
    if resource_type == 'EC2KeyPair':
        try:
            ec2_conn = boto.ec2.connect_to_region(region,aws_access_key_id=aws_access_key_id,
                                                 aws_secret_access_key=aws_secret_access_key)
            test = ec2_conn.get_all_key_pairs(keynames=resource_value)
        except boto.exception.BotoServerError as e:
            print('Config sanity error: %s' % e.message)
            sys.exit(1)
    # VPC Id
    elif resource_type == 'VPC':
        try:
            vpc_conn = boto.vpc.connect_to_region(region,aws_access_key_id=aws_access_key_id,
                                                 aws_secret_access_key=aws_secret_access_key)
            test = vpc_conn.get_all_vpcs(vpc_ids=resource_value)
        except boto.exception.BotoServerError as e:
            print('Config sanity error: %s' % e.message)
            sys.exit(1)
        # Check for DNS support in the VPC
        if not vpc_conn.describe_vpc_attribute(test[0].id, attribute='enableDnsSupport').enable_dns_support:
            print("DNS Support is not enabled in %s" % test[0].id)
            sys.exit(1)
        if not vpc_conn.describe_vpc_attribute(test[0].id, attribute='enableDnsHostnames').enable_dns_hostnames:
            print("DNS Hostnames not enabled in %s" % test[0].id)
            sys.exit(1)
    # VPC Subnet Id
    elif resource_type == 'VPCSubnet':
        try:
            vpc_conn = boto.vpc.connect_to_region(region,aws_access_key_id=aws_access_key_id,
                                                 aws_secret_access_key=aws_secret_access_key)
            test = vpc_conn.get_all_subnets(subnet_ids=resource_value)
        except boto.exception.BotoServerError as e:
            print('Config sanity error: %s' % e.message)
            sys.exit(1)
    # VPC Security Group
    elif resource_type == 'VPCSecurityGroup':
        try:
            vpc_conn = boto.vpc.connect_to_region(region,aws_access_key_id=aws_access_key_id,
                                                 aws_secret_access_key=aws_secret_access_key)
            test = vpc_conn.get_all_security_groups(group_ids=resource_value)
        except boto.exception.BotoServerError as e:
            print('Config sanity error: %s' % e.message)
            sys.exit(1)
    # EC2 AMI Id
    elif resource_type == 'EC2Ami':
        try:
            ec2_conn = boto.ec2.connect_to_region(region,aws_access_key_id=aws_access_key_id,
                                                 aws_secret_access_key=aws_secret_access_key)
            test = ec2_conn.get_all_images(image_ids=resource_value)
        except boto.exception.BotoServerError as e:
            print('Config sanity error: %s' % e.message)
            sys.exit(1)
    # EC2 Placement Group
    elif resource_type == 'EC2PlacementGroup':
        try:
            ec2_conn = boto.ec2.connect_to_region(region,aws_access_key_id=aws_access_key_id,
                                                 aws_secret_access_key=aws_secret_access_key)
            test = ec2_conn.get_all_placement_groups(groupnames=resource_value)
        except boto.exception.BotoServerError as e:
            print('Config sanity error: %s' % e.message)
            sys.exit(1)
    # URL
    elif resource_type == 'URL':
        scheme = urlparse(resource_value).scheme
        if scheme == 's3':
            pass
        else:
            try:
                urllib2.urlopen(resource_value)
            except urllib2.HTTPError, e:
                print(e.code)
                sys.exit(1)
            except urllib2.URLError, e:
                print(e.args)
                sys.exit(1)
    # EC2 EBS Snapshot Id
    elif resource_type == 'EC2Snapshot':
        try:
            ec2_conn = boto.ec2.connect_to_region(region,aws_access_key_id=aws_access_key_id,
                                                 aws_secret_access_key=aws_secret_access_key)
            test = ec2_conn.get_all_snapshots(snapshot_ids=resource_value)
        except boto.exception.BotoServerError as e:
            print('Config sanity error: %s' % e.message)
            sys.exit(1)
