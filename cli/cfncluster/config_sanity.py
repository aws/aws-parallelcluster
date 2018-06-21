from __future__ import print_function
# Copyright 2013-2014 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance with the
# License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.

from future import standard_library
standard_library.install_aliases()
__author__ = 'dougalb'

import boto3
import urllib.request, urllib.error, urllib.parse
from urllib.parse import urlparse
import sys
from botocore.exceptions import ClientError

def check_resource(region, aws_access_key_id, aws_secret_access_key, resource_type,resource_value):

    # Loop over all supported resource checks
    # EC2 KeyPair
    if resource_type == 'EC2KeyPair':
        try:
            ec2 = boto3.client('ec2', region_name=region,
                                        aws_access_key_id=aws_access_key_id,
                                        aws_secret_access_key=aws_secret_access_key)
            test = ec2.describe_key_pairs(KeyNames=[resource_value])
        except ClientError as e:
            print('Config sanity error: %s' % e.response.get('Error').get('Message'))
            sys.exit(1)
    if resource_type == 'EC2IAMRoleName':
        try:
            iam = boto3.client('iam', region_name=region,
                                aws_access_key_id=aws_access_key_id,
                                aws_secret_access_key=aws_secret_access_key)

            arn = iam.get_role(RoleName=resource_value).get('Role').get('Arn')
            accountid = boto3.client('sts').get_caller_identity().get('Account')

            iam_policy = [(['ec2:DescribeVolumes', 'ec2:AttachVolume', 'ec2:DescribeInstanceAttribute', 'ec2:DescribeInstanceStatus', 'ec2:DescribeInstances'], "*"),
                        (['dynamodb:ListTables'], "*"),
                        (['sqs:SendMessage', 'sqs:ReceiveMessage', 'sqs:ChangeMessageVisibility', 'sqs:DeleteMessage', 'sqs:GetQueueUrl'], "arn:aws:sqs:%s:%s:cfncluster-*" % (region, accountid)),
                        (['autoscaling:DescribeAutoScalingGroups', 'autoscaling:TerminateInstanceInAutoScalingGroup', 'autoscaling:SetDesiredCapacity'], "*"),
                        (['cloudwatch:PutMetricData'], "*"),
                        (['dynamodb:PutItem', 'dynamodb:Query', 'dynamodb:GetItem', 'dynamodb:DeleteItem', 'dynamodb:DescribeTable'], "arn:aws:dynamodb:%s:%s:table/cfncluster-*" % (region, accountid)),
                        (['sqs:ListQueues'], "*"),
                        (['logs:*'], "arn:aws:logs:*:*:*")]

            for actions, resource_arn in iam_policy:
                response = iam.simulate_principal_policy(PolicySourceArn=arn, ActionNames=actions, ResourceArns=[resource_arn])
                for decision in response.get("EvaluationResults"):
                    if decision.get("EvalDecision") != "allowed":
                        print("IAM role error on user provided role %s: action %s is %s" %
                              (resource_value, decision.get("EvalActionName"), decision.get("EvalDecision")))
                        print("See https://cfncluster.readthedocs.io/en/latest/iam.html")
                        sys.exit(1)
        except ClientError as e:
            print('Config sanity error: %s' % e.response.get('Error').get('Message'))
            sys.exit(1)
    # VPC Id
    elif resource_type == 'VPC':
        try:

            ec2 = boto3.client('ec2', region_name=region,
                                        aws_access_key_id=aws_access_key_id,
                                        aws_secret_access_key=aws_secret_access_key)
            test = ec2.describe_vpcs(VpcIds=[resource_value])
        except ClientError as e:
            print('Config sanity error: %s' % e.response.get('Error').get('Message'))
            sys.exit(1)
        # Check for DNS support in the VPC
        if not ec2.describe_vpc_attribute(VpcId=resource_value, Attribute='enableDnsSupport')\
                .get('EnableDnsSupport').get('Value'):
            print("DNS Support is not enabled in %s" % resource_value)
            sys.exit(1)
        if not ec2.describe_vpc_attribute(VpcId=resource_value, Attribute='enableDnsHostnames')\
                .get('EnableDnsHostnames').get('Value'):
            print("DNS Hostnames not enabled in %s" % resource_value)
            sys.exit(1)
    # VPC Subnet Id
    elif resource_type == 'VPCSubnet':
        try:
            ec2 = boto3.client('ec2', region_name=region,
                                        aws_access_key_id=aws_access_key_id,
                                        aws_secret_access_key=aws_secret_access_key)
            test = ec2.describe_subnets(SubnetIds=[resource_value])
        except ClientError as e:
            print('Config sanity error: %s' % e.response.get('Error').get('Message'))
            sys.exit(1)
    # VPC Security Group
    elif resource_type == 'VPCSecurityGroup':
        try:
            ec2 = boto3.client('ec2', region_name=region,
                               aws_access_key_id=aws_access_key_id,
                               aws_secret_access_key=aws_secret_access_key)
            test = ec2.describe_security_groups(GroupIds=[resource_value])
        except ClientError as e:
            print('Config sanity error: %s' % e.response.get('Error').get('Message'))
            sys.exit(1)
    # EC2 AMI Id
    elif resource_type == 'EC2Ami':
        try:
            ec2 = boto3.client('ec2', region_name=region,
                               aws_access_key_id=aws_access_key_id,
                               aws_secret_access_key=aws_secret_access_key)
            test = ec2.describe_images(ImageIds=[resource_value])
        except ClientError as e:
            print('Config sanity error: %s' % e.response.get('Error').get('Message'))
            sys.exit(1)
    # EC2 Placement Group
    elif resource_type == 'EC2PlacementGroup':
        if resource_value == 'DYNAMIC':
            pass
        else:
            try:
                ec2 = boto3.client('ec2', region_name=region,
                                   aws_access_key_id=aws_access_key_id,
                                   aws_secret_access_key=aws_secret_access_key)
                test = ec2.describe_placement_groups(GroupNames=[resource_value])
            except ClientError as e:
                print('Config sanity error: %s' % e.response.get('Error').get('Message'))
                sys.exit(1)
    # URL
    elif resource_type == 'URL':
        scheme = urlparse(resource_value).scheme
        if scheme == 's3':
            pass
        else:
            try:
                urllib.request.urlopen(resource_value)
            except urllib.error.HTTPError as e:
                print('Config sanity error:', resource_value, e.code, e.reason)
                sys.exit(1)
            except urllib.error.URLError as e:
                print('Config sanity error:', resource_value, e.reason)
                sys.exit(1)
    # EC2 EBS Snapshot Id
    elif resource_type == 'EC2Snapshot':
        try:
            ec2 = boto3.client('ec2', region_name=region,
                               aws_access_key_id=aws_access_key_id,
                               aws_secret_access_key=aws_secret_access_key)
            test = ec2.describe_snapshots(SnapshotIds=[resource_value])
        except ClientError as e:
            print('Config sanity error: %s' % e.response.get('Error').get('Message'))
            sys.exit(1)
    # EC2 EBS Volume Id
    elif resource_type == 'EC2Volume':
        try:
            ec2 = boto3.client('ec2', region_name=region,
                               aws_access_key_id=aws_access_key_id,
                               aws_secret_access_key=aws_secret_access_key)
            test = ec2.describe_volumes(VolumeIds=[resource_value]).get('Volumes')[0]
            if test.get('State') != 'available':
                print('Volume %s is in state \'%s\' not \'available\'' % (resource_value, test.get('State')))
                sys.exit(1)
        except ClientError as e:
            if e.response.get('Error').get('Message').endswith('parameter volumes is invalid. Expected: \'vol-...\'.'):
                print('Config sanity error: volume %s does not exist.' % resource_value)
                sys.exit(1)
            print('Config sanity error: %s' % e.response.get('Error').get('Message'))
            sys.exit(1)
