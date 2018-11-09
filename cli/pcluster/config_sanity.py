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
import json
from botocore.exceptions import ClientError

def get_partition(region):
    if region == 'us-gov-west-1':
        return 'aws-us-gov'
    return 'aws'


def check_resource(region, aws_access_key_id, aws_secret_access_key, resource_type, resource_value):

    # Loop over all supported resource checks
    # EC2 KeyPair
    if resource_type == 'EC2KeyPair':
        try:
            ec2 = boto3.client('ec2', region_name=region,
                                        aws_access_key_id=aws_access_key_id,
                                        aws_secret_access_key=aws_secret_access_key)
            test = ec2.describe_key_pairs(KeyNames=[resource_value])
        except ClientError as e:
            print('Config sanity error on resource %s: %s' % (resource_type, e.response.get('Error').get('Message')))
            sys.exit(1)
    if resource_type == 'EC2IAMRoleName':
        try:
            iam = boto3.client('iam', region_name=region,
                                aws_access_key_id=aws_access_key_id,
                                aws_secret_access_key=aws_secret_access_key)

            arn = iam.get_role(RoleName=resource_value).get('Role').get('Arn')
            accountid = boto3.client('sts', region_name=region,
                                        aws_access_key_id=aws_access_key_id,
                                        aws_secret_access_key=aws_secret_access_key).get_caller_identity().get('Account')

            partition = get_partition(region)

            iam_policy = [(['ec2:DescribeVolumes', 'ec2:AttachVolume', 'ec2:DescribeInstanceAttribute', 'ec2:DescribeInstanceStatus', 'ec2:DescribeInstances'], "*"),
                        (['dynamodb:ListTables'], "*"),
                        (['sqs:SendMessage', 'sqs:ReceiveMessage', 'sqs:ChangeMessageVisibility', 'sqs:DeleteMessage', 'sqs:GetQueueUrl'], "arn:%s:sqs:%s:%s:aws-parallelcluster-*" % (partition, region, accountid)),
                        (['autoscaling:DescribeAutoScalingGroups', 'autoscaling:TerminateInstanceInAutoScalingGroup', 'autoscaling:SetDesiredCapacity', 'autoscaling:DescribeTags', 'autoScaling:UpdateAutoScalingGroup'], "*"),
                        (['dynamodb:PutItem', 'dynamodb:Query', 'dynamodb:GetItem', 'dynamodb:DeleteItem', 'dynamodb:DescribeTable'], "arn:%s:dynamodb:%s:%s:table/aws-parallelcluster-*" % (partition, region, accountid)),
                        (['cloudformation:DescribeStacks'], "arn:%s:cloudformation:%s:%s:stack/aws-parallelcluster-*" % (partition, region, accountid)),
                        (['s3:GetObject'], "arn:%s:s3:::%s-aws-parallelcluster/*" % (partition, region)),
                        (['sqs:ListQueues'], "*"),
                        (['logs:*'], "arn:%s:logs:*:*:*" % partition)]

            for actions, resource_arn in iam_policy:
                response = iam.simulate_principal_policy(PolicySourceArn=arn, ActionNames=actions, ResourceArns=[resource_arn])
                for decision in response.get("EvaluationResults"):
                    if decision.get("EvalDecision") != "allowed":
                        print("IAM role error on user provided role %s: action %s is %s" %
                              (resource_value, decision.get("EvalActionName"), decision.get("EvalDecision")))
                        print("See https://aws-parallelcluster.readthedocs.io/en/latest/iam.html")
                        sys.exit(1)
        except ClientError as e:
            print('Config sanity error on resource %s: %s' % (resource_type, e.response.get('Error').get('Message')))
            sys.exit(1)
    # VPC Id
    elif resource_type == 'VPC':
        try:

            ec2 = boto3.client('ec2', region_name=region,
                                        aws_access_key_id=aws_access_key_id,
                                        aws_secret_access_key=aws_secret_access_key)
            test = ec2.describe_vpcs(VpcIds=[resource_value])
        except ClientError as e:
            print('Config sanity error on resource %s: %s' % (resource_type, e.response.get('Error').get('Message')))
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
            print('Config sanity error on resource %s: %s' % (resource_type, e.response.get('Error').get('Message')))
            sys.exit(1)
    # VPC Security Group
    elif resource_type == 'VPCSecurityGroup':
        try:
            ec2 = boto3.client('ec2', region_name=region,
                               aws_access_key_id=aws_access_key_id,
                               aws_secret_access_key=aws_secret_access_key)
            test = ec2.describe_security_groups(GroupIds=[resource_value])
        except ClientError as e:
            print('Config sanity error on resource %s: %s' % (resource_type, e.response.get('Error').get('Message')))
            sys.exit(1)
    # EC2 AMI Id
    elif resource_type == 'EC2Ami':
        try:
            ec2 = boto3.client('ec2', region_name=region,
                               aws_access_key_id=aws_access_key_id,
                               aws_secret_access_key=aws_secret_access_key)
            test = ec2.describe_images(ImageIds=[resource_value])
        except ClientError as e:
            print('Config sanity error on resource %s: %s' % (resource_type, e.response.get('Error').get('Message')))
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
                print('Config sanity error on resource %s: %s' % (resource_type, e.response.get('Error').get('Message')))
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
            print('Config sanity error on resource %s: %s' % (resource_type, e.response.get('Error').get('Message')))
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
            print('Config sanity error on resource %s: %s' % (resource_type, e.response.get('Error').get('Message')))
            sys.exit(1)
    # Batch Parameters
    elif resource_type == 'AWSBatch_Parameters':
        # Check region
        if region in ['us-gov-west-1', 'eu-west-3', 'ap-northeast-3']:
            print ("ERROR: %s region is not supported with awsbatch" % region)
            sys.exit(1)

        # Check compute instance types
        if 'ComputeInstanceType' in resource_value:
            try:
                s3 = boto3.resource('s3', region_name=region)
                bucket_name = '%s-aws-parallelcluster' % region
                file_name = 'instances/batch_instances.json'
                try:
                    file_contents = s3.Object(bucket_name, file_name).get()['Body'].read().decode('utf-8')
                    supported_instances = json.loads(file_contents)
                    for instance in resource_value['ComputeInstanceType'].split(','):
                        if not instance.strip() in supported_instances:
                            print ("Instance type %s not supported by batch in this region" % instance)
                            sys.exit(1)
                except ClientError as e:
                    print('Config sanity error on resource %s: %s' % (resource_type, e.response.get('Error').get('Message')))
                    sys.exit(1)
            except ClientError as e:
                print('Config sanity error on resource %s: %s' % (resource_type, e.response.get('Error').get('Message')))
                sys.exit(1)

        # Check spot bid percentage
        if 'SpotPrice' in resource_value:
            if int(resource_value['SpotPrice']) > 100 or int(resource_value['SpotPrice']) < 0:
                print("ERROR: Spot bid percentage needs to be between 0 and 100")
                sys.exit(1)

        # Check sanity on desired, min and max vcpus
        if 'DesiredSize' in resource_value and 'MinSize' in resource_value:
            if int(resource_value['DesiredSize']) < int(resource_value['MinSize']):
                print ('ERROR: Desired vcpus must be greater than or equal to min vcpus')
                sys.exit(1)

        if 'DesiredSize' in resource_value and 'MaxSize' in resource_value:
            if int(resource_value['DesiredSize']) > int(resource_value['MaxSize']):
                print('ERROR: Desired vcpus must be fewer than or equal to max vcpus')
                sys.exit(1)

        if 'MaxSize' in resource_value and 'MinSize' in resource_value:
            if int(resource_value['MaxSize']) < int(resource_value['MinSize']):
                print ('ERROR: Max vcpus must be greater than or equal to min vcpus')
                sys.exit(1)

        # Check custom batch url
        if 'CustomAWSBatchTemplateURL' in resource_value:
            check_resource(region, aws_access_key_id, aws_secret_access_key,
                           'URL', resource_value['CustomAWSBatchTemplateURL'])
