from __future__ import print_function
from __future__ import absolute_import
# Copyright 2013-2018 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the 'License'). You may not use this file except in compliance with the
# License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the 'LICENSE.txt' file accompanying this file. This file is distributed on an 'AS IS' BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.

from future import standard_library
standard_library.install_aliases()
from builtins import input
import configparser
import sys
import boto3
import os
import logging
import stat
import errno

from . import cfnconfig

logger = logging.getLogger('cfncluster.cfncluster')
unsupported_regions = ['ap-northeast-3']

def prompt(prompt, default_value=None, hidden=False, options=None):
    if hidden and default_value is not None:
        user_prompt = prompt + ' [*******' + default_value[-4:] + ']: '
    else:
        user_prompt = prompt + ' ['
        if default_value is not None:
            user_prompt = user_prompt + default_value + ']: '
        else:
            user_prompt = user_prompt + ']: '

    if isinstance(options, list):
        print('Acceptable Values for %s: ' % prompt)
        for o in options:
            print('    %s' % o)

    var = input(user_prompt)

    if var == '':
        return default_value
    else:
        return var.strip()

def get_regions():
    ec2 = boto3.client('ec2')
    regions = ec2.describe_regions().get('Regions')
    return [region.get('RegionName') for region in regions if region.get('RegionName') not in unsupported_regions]

def ec2_conn(aws_access_key_id, aws_secret_access_key, aws_region_name):
    if aws_region_name:
        region = aws_region_name
    elif os.environ.get('AWS_DEFAULT_REGION'):
        region = os.environ.get('AWS_DEFAULT_REGION')
    else:
        region = 'us-east-1'

    ec2 = boto3.client('ec2', region_name=region,
                       aws_access_key_id=aws_access_key_id,
                       aws_secret_access_key=aws_secret_access_key)
    return ec2

def list_keys(aws_access_key_id, aws_secret_access_key, aws_region_name):
    conn = ec2_conn(aws_access_key_id, aws_secret_access_key, aws_region_name)
    keypairs = conn.describe_key_pairs()
    keynames = []
    for key in keypairs.get('KeyPairs'):
        keynames.append(key.get('KeyName'))

    if not keynames:
        print('ERROR: No Key Pairs found in region ' + aws_region_name)
        print('Please create an EC2 Key Pair before continuing')
        sys.exit(1)

    return keynames

def list_vpcs(aws_access_key_id, aws_secret_access_key, aws_region_name):
    conn = ec2_conn(aws_access_key_id, aws_secret_access_key, aws_region_name)
    vpcs = conn.describe_vpcs()
    vpcids = []
    for vpc in vpcs.get('Vpcs'):
        vpcids.append(vpc.get('VpcId'))

    if not vpcids:
        print('ERROR: No VPCs found in region ' + aws_region_name)
        print('Please create a VPC before continuing')
        sys.exit(1)

    return vpcids

def list_subnets(aws_access_key_id, aws_secret_access_key, aws_region_name, vpc_id):
    conn = ec2_conn(aws_access_key_id, aws_secret_access_key, aws_region_name)
    subnets = conn.describe_subnets(Filters=[{'Name': 'vpcId', 'Values': [vpc_id]}])
    subnetids = []
    for subnet in subnets.get('Subnets'):
        subnetids.append(subnet.get('SubnetId'))

    if not subnetids:
        print('ERROR: No Subnets found in region ' + aws_region_name)
        print('Please create a VPC Subnet before continuing')
        sys.exit(1)

    return subnetids

def configure(args):

    # Determine config file name based on args or default
    if args.config_file is not None:
        config_file = args.config_file
    else:
        config_file = os.path.expanduser(os.path.join('~', '.cfncluster', 'config'))

    config = configparser.ConfigParser()

    # Check if configuration file exists
    if os.path.isfile(config_file):
        config.read(config_file)
        config_read = True

    # Prompt for required values, using existing as defaults
    cluster_template = prompt('Cluster Template', config.get('global', 'cluster_template') if config.has_option('global', 'cluster_template') else 'default')
    aws_access_key_id = prompt('AWS Access Key ID', config.get('aws', 'aws_access_key_id') if config.has_option('aws', 'aws_access_key_id') else None, True)
    aws_secret_access_key = prompt('AWS Secret Access Key ID', config.get('aws', 'aws_secret_access_key') if config.has_option('aws', 'aws_secret_access_key') else None, True)

    # Use built in boto regions as an available option
    aws_region_name = prompt('AWS Region ID', config.get('aws', 'aws_region_name') if config.has_option('aws', 'aws_region_name') else None, options=get_regions())
    vpcname = prompt('VPC Name', config.get('cluster ' + cluster_template, 'vpc_settings') if config.has_option('cluster ' + cluster_template, 'vpc_settings') else 'public')

    # Query EC2 for available keys as options
    key_name = prompt('Key Name', config.get('cluster ' + cluster_template, 'key_name') if config.has_option('cluster ' + cluster_template, 'key_name') else None, options=list_keys(aws_access_key_id, aws_secret_access_key, aws_region_name))
    vpc_id = prompt('VPC ID', config.get('vpc ' + vpcname, 'vpc_id') if config.has_option('vpc ' + vpcname, 'vpc_id') else None, options=list_vpcs(aws_access_key_id, aws_secret_access_key, aws_region_name))
    master_subnet_id = prompt('Master Subnet ID', config.get('vpc ' + vpcname, 'master_subnet_id') if config.has_option('vpc ' + vpcname, 'master_subnet_id') else None, options=list_subnets(aws_access_key_id, aws_secret_access_key, aws_region_name, vpc_id))

    # Dictionary of values we want to set
    s_global = { '__name__': 'global', 'cluster_template': cluster_template, 'update_check': 'true', 'sanity_check': 'true' }
    s_aws = { '__name__': 'aws', 'aws_access_key_id': aws_access_key_id, 'aws_secret_access_key': aws_secret_access_key, 'aws_region_name': aws_region_name }
    s_aliases = {'__name__': 'aliases', 'ssh': 'ssh {CFN_USER}@{MASTER_IP} {ARGS}'}
    s_cluster = { '__name__': 'cluster ' + cluster_template, 'key_name': key_name, 'vpc_settings': vpcname }
    s_vpc = { '__name__': 'vpc ' + vpcname, 'vpc_id': vpc_id, 'master_subnet_id': master_subnet_id }

    sections = [s_aws, s_cluster, s_vpc, s_global, s_aliases]

    # Loop through the configuration sections we care about
    for section in sections:
        try:
            config.add_section(section['__name__'])
        except configparser.DuplicateSectionError:
            pass
        for key, value in section.items():
            # Only update configuration if not set
            if value is not None and key is not '__name__':
                config.set(section['__name__'], key, value)

    # ensure that the directory for the config file exists (because
    # ~/.cfncluster is likely not to exist on first usage)
    try:
        os.makedirs(os.path.dirname(config_file))
    except OSError as e:
        if e.errno != errno.EEXIST:
            raise # can safely ignore EEXISTS for this purpose...

    # Write configuration to disk
    open(config_file,'a').close()
    os.chmod(config_file, stat.S_IRUSR | stat.S_IWUSR)
    with open(config_file,'w') as cf:
        config.write(cf)

    # Verify the configuration
    cfnconfig.CfnClusterConfig(args)
