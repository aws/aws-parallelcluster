from __future__ import print_function
from __future__ import absolute_import
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
from builtins import str
from builtins import object
import configparser
import os
import sys
import inspect
import pkg_resources
import json
import urllib.request, urllib.error, urllib.parse
from . import config_sanity
import boto3
from botocore.exceptions import ClientError

def getStackTemplate(region, aws_access_key_id, aws_secret_access_key, stack):
    cfn = boto3.client('cloudformation', region_name=region,
                       aws_access_key_id=aws_access_key_id,
                       aws_secret_access_key=aws_secret_access_key)
    __stack_name = ('cfncluster-' + stack)

    try:
        __stack = cfn.describe_stacks(StackName=__stack_name).get('Stacks')[0]
    except ClientError as e:
        print(e.response.get('Error').get('Message'))
        sys.stdout.flush()
        sys.exit(1)
    __cli_template = [p.get('ParameterValue') for p in __stack.get('Parameters') if p.get('ParameterKey') == 'CLITemplate'][0]

    return __cli_template

class CfnClusterConfig(object):

    def __init__(self, args):
        self.args = args
        self.parameters = []
        self.version = pkg_resources.get_distribution("cfncluster").version
        self.__DEFAULT_CONFIG = False
        __args_func = self.args.func.__name__

        # Determine config file name based on args or default
        if hasattr(args, 'config_file') and args.config_file is not None:
            self.__config_file = args.config_file
        else:
            self.__config_file = os.path.expanduser(os.path.join('~', '.cfncluster', 'config'))
            self.__DEFAULT_CONFIG = True
        if os.path.isfile(self.__config_file):
            pass
        else:
            if self.__DEFAULT_CONFIG:
                print('Default config %s not found' % self.__config_file)
                print('You can copy a template from here: %s%sexamples%sconfig' %
                      (os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe()))),
                       os.path.sep, os.path.sep))
                sys.exit(1)
            else:
                print('Config file %s not found' % self.__config_file)
                sys.exit(1)


        __config = configparser.ConfigParser()
        __config.read(self.__config_file)

        # Determine the EC2 region to used used or default to us-east-1
        # Order is 1) CLI arg 2) AWS_DEFAULT_REGION env 3) Config file 4) us-east-1
        if hasattr(args, 'region') and args.region:
            self.region = args.region
        else:
            if os.environ.get('AWS_DEFAULT_REGION'):
                self.region = os.environ.get('AWS_DEFAULT_REGION')
            else:
                try:
                    self.region = __config.get('aws', 'aws_region_name')
                except configparser.NoOptionError:
                    self.region = 'us-east-1'

        # Check if credentials have been provided in config
        try:
            self.aws_access_key_id = __config.get('aws', 'aws_access_key_id')
        except configparser.NoOptionError:
            self.aws_access_key_id=None
        try:
            self.aws_secret_access_key = __config.get('aws', 'aws_secret_access_key')
        except configparser.NoOptionError:
            self.aws_secret_access_key=None

        # Determine which cluster template will be used
        if __args_func == 'start':
            # Starting a cluster is unique in that we would want to prevent the
            # customer from inadvertently using a different template than what
            # the cluster was created with, so we do not support the -t
            # parameter. We always get the template to use from CloudFormation.
            self.__cluster_template = getStackTemplate(self.region,self.aws_access_key_id,
                                        self.aws_secret_access_key, self.args.cluster_name)
        else:
            try:
                if args.cluster_template is not None:
                    self.__cluster_template = args.cluster_template
                else:
                    if __args_func == 'update':
                        self.__cluster_template = getStackTemplate(self.region,self.aws_access_key_id,
                                                                   self.aws_secret_access_key, self.args.cluster_name)
                    else:
                        self.__cluster_template = __config.get('global', 'cluster_template')
            except AttributeError:
                self.__cluster_template = __config.get('global', 'cluster_template')
        self.__cluster_section = ('cluster %s' % self.__cluster_template)
        self.parameters.append(('CLITemplate',self.__cluster_template))

        # Check if package updates should be checked
        try:
            self.__update_check = __config.getboolean('global', 'update_check')
        except configparser.NoOptionError:
            self.__update_check = True

        if self.__update_check == True:
            try:
                __latest = json.loads(urllib.request.urlopen("http://pypi.python.org/pypi/cfncluster/json").read())['info']['version']
                if self.version < __latest:
                    print('warning: There is a newer version %s of cfncluster available.' % __latest)
            except Exception:
                pass

        # Check if config sanity should be run
        try:
            self.__sanity_check = __config.getboolean('global', 'sanity_check')
        except configparser.NoOptionError:
            self.__sanity_check = False
        # Only check config on calls that mutate it
        __args_func = self.args.func.__name__
        if (__args_func == 'create' or __args_func == 'update' or __args_func == 'configure') and self.__sanity_check is True:
            pass
        else:
            self.__sanity_check = False

        # Get the EC2 keypair name to be used, exit if not set
        try:
            self.key_name = __config.get(self.__cluster_section, 'key_name')
            if not self.key_name:
                print("ERROR: key_name set in [%s] section but not defined." % self.__cluster_section)
                sys.exit(1)
            if self.__sanity_check:
                config_sanity.check_resource(self.region,self.aws_access_key_id, self.aws_secret_access_key,
                                             'EC2KeyPair', self.key_name)
        except configparser.NoOptionError:
            print("ERROR: Missing key_name option in [%s] section." % self.__cluster_section)
            sys.exit(1)
        self.parameters.append(('KeyName', self.key_name))

        # Determine the CloudFormation URL to be used
        # Order is 1) CLI arg 2) Config file 3) default for version + region
        try:
            if args.template_url is not None:
                self.template_url = args.template_url
            else:
                try:
                    self.template_url = __config.get(self.__cluster_section,
                                                     'template_url')
                    if not self.template_url:
                        print("ERROR: template_url set in [%s] section but not defined." % self.__cluster_section)
                        sys.exit(1)
                    if self.__sanity_check:
                        config_sanity.check_resource(self.region, self.aws_access_key_id, self.aws_secret_access_key,
                                                     'URL', self.template_url)
                except configparser.NoOptionError:
                    if self.region == 'us-gov-west-1':
                        self.template_url = ('https://s3-%s.amazonaws.com/%s-cfncluster/templates/cfncluster-%s.cfn.json'
                                             % (self.region, self.region, self.version))
                    else:
                        self.template_url = ('https://s3.amazonaws.com/%s-cfncluster/templates/cfncluster-%s.cfn.json'
                                             % (self.region, self.version))
        except AttributeError:
            pass

        # Determine which vpc settings section will be used
        self.__vpc_settings = __config.get(self.__cluster_section, 'vpc_settings')
        self.__vpc_section = ('vpc %s' % self.__vpc_settings)

        # Dictionary list of all VPC options
        self.__vpc_options = dict(vpc_id=('VPCId','VPC'), master_subnet_id=('MasterSubnetId', 'VPCSubnet'),
                                  compute_subnet_cidr=('ComputeSubnetCidr',None),
                                  compute_subnet_id=('ComputeSubnetId', 'VPCSubnet'), use_public_ips=('UsePublicIps',
                                                                                                      None),
                                  ssh_from=('AccessFrom', None), access_from=('AccessFrom', None),
                                  additional_sg=('AdditionalSG','VPCSecurityGroup'),
                                  vpc_security_group_id=('VPCSecurityGroupId','VPCSecurityGroup')
                                  )

        # Loop over all VPC options and add define to parameters, raise Exception is defined but null
        for key in self.__vpc_options:
            try:
                __temp__ = __config.get(self.__vpc_section, key)
                if not __temp__:
                    print("ERROR: %s defined but not set in [%s] section"
                                                    % (key, self.__vpc_section))
                    sys.exit(1)
                if self.__sanity_check and self.__vpc_options.get(key)[1] is not None:
                    config_sanity.check_resource(self.region,self.aws_access_key_id, self.aws_secret_access_key,
                                                self.__vpc_options.get(key)[1],__temp__)
                self.parameters.append((self.__vpc_options.get(key)[0],__temp__))
            except configparser.NoOptionError:
                pass
            except configparser.NoSectionError:
                print("ERROR: VPC section [%s] used in [%s] section is not defined"
                      % (self.__vpc_section, self.__cluster_section))
                sys.exit(1)

        # Dictionary list of all cluster section options
        self.__cluster_options = dict(cluster_user=('ClusterUser', None), compute_instance_type=('ComputeInstanceType',None),
                                      master_instance_type=('MasterInstanceType', None), initial_queue_size=('InitialQueueSize',None),
                                      max_queue_size=('MaxQueueSize',None), maintain_initial_size=('MaintainInitialSize',None),
                                      scheduler=('Scheduler',None), cluster_type=('ClusterType',None), ephemeral_dir=('EphemeralDir',None),
                                      spot_price=('SpotPrice',None), custom_ami=('CustomAMI','EC2Ami'), pre_install=('PreInstallScript','URL'),
                                      post_install=('PostInstallScript','URL'), proxy_server=('ProxyServer',None),
                                      placement=('Placement',None), placement_group=('PlacementGroup','EC2PlacementGroup'),
                                      encrypted_ephemeral=('EncryptedEphemeral',None),pre_install_args=('PreInstallArgs',None),
                                      post_install_args=('PostInstallArgs',None), s3_read_resource=('S3ReadResource',None),
                                      s3_read_write_resource=('S3ReadWriteResource',None),cwl_region=('CWLRegion',None),
                                      cwl_log_group=('CWLLogGroup',None),shared_dir=('SharedDir',None),tenancy=('Tenancy',None),
                                      ephemeral_kms_key_id=('EphemeralKMSKeyId',None), cluster_ready=('ClusterReadyScript','URL'),
                                      master_root_volume_size=('MasterRootVolumeSize',None),compute_root_volume_size=('ComputeRootVolumeSize',None),
                                      base_os=('BaseOS',None),ec2_iam_role=('EC2IAMRoleName','EC2IAMRoleName'),extra_json=('ExtraJson',None),
                                      custom_chef_cookbook=('CustomChefCookbook',None),custom_chef_runlist=('CustomChefRunList',None),
                                      additional_cfn_template=('AdditionalCfnTemplate',None)
                                      )

        # Loop over all the cluster options and add define to parameters, raise Exception if defined but null
        for key in self.__cluster_options:
            try:
                __temp__ = __config.get(self.__cluster_section, key)
                if not __temp__:
                    print("ERROR: %s defined but not set in [%s] section"
                                                    % (key, self.__cluster_section))
                    sys.exit(1)
                if self.__sanity_check and self.__cluster_options.get(key)[1] is not None:
                    config_sanity.check_resource(self.region,self.aws_access_key_id, self.aws_secret_access_key,
                                                self.__cluster_options.get(key)[1],__temp__)
                self.parameters.append((self.__cluster_options.get(key)[0],__temp__))
            except configparser.NoOptionError:
                pass

        # Merge tags from config with tags from command line args
        # Command line args take precedent and overwite tags supplied in the config
        self.tags = {}
        try:
            tags = __config.get(self.__cluster_section, 'tags')
            self.tags = json.loads(tags);
        except configparser.NoOptionError:
            pass
        try:
            if args.tags is not None:
                for key in args.tags:
                    self.tags[key] = args.tags[key]
        except AttributeError:
            pass

        # Determine if EBS settings are defined and set section
        try:
            self.__ebs_settings = __config.get(self.__cluster_section, 'ebs_settings')
            if not self.__ebs_settings:
                print("ERROR: ebs_settings defined by not set in [%s] section"
                                                % self.__cluster_section)
                sys.exit(1)
            self.__ebs_section = ('ebs %s' % self.__ebs_settings)
        except configparser.NoOptionError:
            pass

        # Dictionary list of all EBS options
        self.__ebs_options = dict(ebs_snapshot_id=('EBSSnapshotId','EC2Snapshot'), volume_type=('VolumeType',None),
                                  volume_size=('VolumeSize',None), ebs_kms_key_id=('EBSKMSKeyId', None),
                                  volume_iops=('VolumeIOPS',None), encrypted=('EBSEncryption',None),
                                  ebs_volume_id=('EBSVolumeId','EC2Volume')
                                  )

        try:
            if self.__ebs_section:
                for key in self.__ebs_options:
                    try:
                        __temp__ = __config.get(self.__ebs_section, key)
                        if not __temp__:
                            print("ERROR: %s defined but not set in [%s] section"
                                                    % (key, self.__ebs_section))
                            sys.exit(1)
                        if self.__sanity_check and self.__ebs_options.get(key)[1] is not None:
                            config_sanity.check_resource(self.region,self.aws_access_key_id, self.aws_secret_access_key,
                                                self.__ebs_options.get(key)[1],__temp__)
                        self.parameters.append((self.__ebs_options.get(key)[0],__temp__))
                    except configparser.NoOptionError:
                        pass
        except AttributeError:
            pass

        # Determine if scaling settings are defined and set section
        try:
            self.__scaling_settings = __config.get(self.__cluster_section, 'scaling_settings')
            if not self.__scaling_settings:
                print("ERROR: scaling_settings defined by not set in [%s] section"
                                                % self.__cluster_section)
                sys.exit(1)
            self.__scaling_section = ('scaling %s' % self.__scaling_settings)
        except configparser.NoOptionError:
            pass

        # Dictionary list of all scaling options
        self.__scaling_options = dict(scaling_threshold=('ScalingThreshold',None), scaling_period=('ScalingPeriod',None),
                                      scaling_evaluation_periods=('ScalingEvaluationPeriods',None),
                                      scaling_adjustment=('ScalingAdjustment',None),scaling_adjustment2=('ScalingAdjustment2',None),
                                      scaling_cooldown=('ScalingCooldown',None),scaling_threshold2=('ScalingThreshold2',None))

        try:
            if self.__scaling_section:
                for key in self.__scaling_options:
                    try:
                        __temp__ = __config.get(self.__scaling_section, key)
                        if not __temp__:
                            print("ERROR: %s defined but not set in [%s] section"
                                                    % (key, self.__scaling_section))
                            sys.exit(1)
                        if self.__sanity_check and self.__scaling_options.get(key)[1] is not None:
                            config_sanity.check_resource(self.region,self.aws_access_key_id, self.aws_secret_access_key,
                                                self.__scaling_options.get(key)[1],__temp__)
                        self.parameters.append((self.__scaling_options.get(key)[0],__temp__))
                    except configparser.NoOptionError:
                        pass
        except AttributeError:
            pass

        # handle aliases
        self.aliases = {}
        self.__alias_section = 'aliases'
        if __config.has_section(self.__alias_section):
            for alias in __config.options(self.__alias_section):
                self.aliases[alias] = __config.get(self.__alias_section, alias)

        # Handle extra parameters supplied on command-line
        try:
            if self.args.extra_parameters is not None:
                self.__temp_dict = dict(self.parameters)
                self.__temp_dict.update(dict(self.args.extra_parameters))
                self.__dictlist = []
                for key, value in self.__temp_dict.items():
                    temp = [str(key),str(value)]
                    self.__dictlist.append(temp)
                self.parameters = self.__dictlist
        except AttributeError:
            pass
