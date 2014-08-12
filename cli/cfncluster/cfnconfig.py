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

import ConfigParser
import os
import sys
import inspect
import pkg_resources
import logging
import json
import urllib2

class CfnClusterConfig:

    def __init__(self, args):
        self.args = args
        self.parameters = []
        self.version = pkg_resources.get_distribution("cfncluster").version
        self.__DEFAULT_CONFIG = False

        # Determine config file name based on args or default
        if args.config_file is not None:
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


        __config = ConfigParser.ConfigParser()
        __config.read(self.__config_file)

        # Determine which cluster template will be used
        try:
            if args.cluster_template is not None:
                self.__cluster_template = args.cluster_template
            else:
                self.__cluster_template = __config.get('global', 'cluster_template')
        except AttributeError:
            self.__cluster_template = __config.get('global', 'cluster_template')
        self.__cluster_section = ('cluster %s' % self.__cluster_template)

        # Check if package updates should be checked
        try:
            self.__update_check = __config.get('global', 'update_check')
        except ConfigParser.NoOptionError:
            self.__update_check = True

        if self.__update_check == True:
            try:
                __latest = json.loads(urllib2.urlopen("http://pypi.python.org/pypi/cfncluster/json").read())['info']['version']
                if self.version < __latest:
                    print('warning: There is a newer version %s of cfncluster available.' % __latest)
            except Exception:
                pass

        # Get the EC2 keypair name to be used, exit if not set
        try:
            self.key_name = __config.get(self.__cluster_section, 'key_name')
            if not self.key_name:
                raise Exception
        except ConfigParser.NoOptionError:
            raise Exception
        self.parameters.append(('KeyName', self.key_name))

        # Determine which keypair config will be used
        self.__keypair_section = ('keypair %s' % self.key_name)

        # Get the location of the keypair file
        try:
            self.key_location = __config.get(self.__keypair_section, 'key_location')
            if not self.key_location:
                raise Exception
        except ConfigParser.NoOptionError:
            raise Exception

        # Determine the EC2 region to used used or default to us-east-1
        # Order is 1) CLI arg 2) AWS_DEFAULT_REGION env 3) Config file 4) us-east-1
        if args.region:
            self.region = args.region
        else:
            if os.environ.get('AWS_DEFAULT_REGION'):
                self.region = os.environ.get('AWS_DEFAULT_REGION')
            else:
                try:
                    self.region = __config.get('aws', 'aws_region_name')
                except ConfigParser.NoOptionError:
                    self.region = 'us-east-1'

        # Check if credentials have been provided in config
        try:
            self.aws_access_key_id = __config.get('aws', 'aws_access_key_id')
        except ConfigParser.NoOptionError:
            self.aws_access_key_id=None
        try:
            self.aws_secret_access_key = __config.get('aws', 'aws_secret_access_key')
        except ConfigParser.NoOptionError:
            self.aws_secret_access_key=None

        # Determine the CloudFormation URL to be used
        # Config file or default
        try:
            self.template_url = __config.get(self.__cluster_section,
                                             'template_url')
            if not self.template_url:
                raise Exception
        except ConfigParser.NoOptionError:
            self.template_url = ('https://s3.amazonaws.com/cfncluster-%s/templates/cfncluster-%s.cfn.json' % (self.region, self.version))

        # Determine which vpc settings section will be used
        self.__vpc_settings = __config.get(self.__cluster_section, 'vpc_settings')
        self.__vpc_section = ('vpc %s' % self.__vpc_settings)

        # Dictionary list of all VPC options
        self.__vpc_options = dict(vpc_id='VPCId', public_subnet='PublicSubnet', private_cidrs='PrivateCIDRs',
                                  vpc_base_eni='VPCBaseNATENI1', compute_uses_public_subnet='ComputeUsesPublicSubnet',
                                  vpc_base_security_group='VPCBaseBackSecurityGroup', use_vpc_base='UseVPCBase',
                                  vpc_base_backend_subnet='VPCBaseBackendSubnet1',
                                  availability_zones='AvailabilityZones', ssh_from='SSHFrom')

        # Loop over all VPC options and add define to parameters, raise Exception is defined but null
        for key in self.__vpc_options:
            try:
                __temp__ = __config.get(self.__vpc_section, key)
                if not __temp__:
                    raise Exception
                self.parameters.append((self.__vpc_options.get(key),__temp__))
            except ConfigParser.NoOptionError:
                pass

        # Dictionary list of all cluster section options
        self.__cluster_options = dict(cluster_user='ClusterUser', compute_instance_type='ComputeInstanceType',
                                      master_instance_type='MasterInstanceType', initial_queue_size='InitialQueueSize',
                                      max_queue_size='MaxQueueSize', maintain_initial_size='MaintainInitialSize',
                                      scheduler='Scheduler', cluster_type='ClusterType', ephemeral_dir='EphemeralDir',
                                      spot_price='SpotPrice', custom_ami='CustomAMI', pre_install='PreInstallScript',
                                      post_install='PostInstallScript', proxy_server='ProxyServer',
                                      placement='Placement', placement_group='PlacementGroup',
                                      encrypted_ephemeral='EncryptedEphemeral',pre_install_args='PreInstallArgs',
                                      post_install_args='PostInstallArgs', s3_read_resource='S3ReadResource',
                                      s3_read_write_resource='S3ReadWriteResource')

        # Loop over all the cluster options and add define to parameters, raise Exception if defined but null
        for key in self.__cluster_options:
            try:
                __temp__ = __config.get(self.__cluster_section, key)
                if not __temp__:
                    raise Exception
                self.parameters.append((self.__cluster_options.get(key),__temp__))
            except ConfigParser.NoOptionError:
                pass

        # Determine if EBS settings are defined and set section
        try:
            self.__ebs_settings = __config.get(self.__cluster_section, 'ebs_settings')
            if not self.__ebs_settings:
                raise Exception
            self.__ebs_section = ('ebs %s' % self.__ebs_settings)
        except ConfigParser.NoOptionError:
            pass

        # Dictionary list of all EBS options
        self.__ebs_options = dict(ebs_snapshot_id='EBSSnapshotId', volume_type='VolumeType', volume_size='VolumeSize',
                                  volume_iops='VolumeIOPS', encrypted='EBSEncryption')

        try:
            if self.__ebs_section:
                for key in self.__ebs_options:
                    try:
                        __temp__ = __config.get(self.__ebs_section, key)
                        if not __temp__:
                            raise Exception
                        self.parameters.append((self.__ebs_options.get(key),__temp__))
                    except ConfigParser.NoOptionError:
                        pass
        except AttributeError:
            pass

        # Determine if scaling settings are defined and set section
        try:
            self.__scaling_settings = __config.get(self.__cluster_section, 'scaling_settings')
            if not self.__scaling_settings:
                raise Exception
            self.__scaling_section = ('scaling %s' % self.__scaling_settings)
        except ConfigParser.NoOptionError:
            pass

        # Dictionary list of all scaling options
        self.__scaling_options = dict(scaling_threshold='ScalingThreshold', scaling_period='ScalingPeriod',
                                      scaling_evaluation_periods='ScalingEvaluationPeriods')

        try:
            if self.__scaling_section:
                for key in self.__scaling_options:
                    try:
                        __temp__ = __config.get(self.__scaling_section, key)
                        if not __temp__:
                            raise Exception
                        self.parameters.append((self.__scaling_options.get(key),__temp__))
                    except ConfigParser.NoOptionError:
                        pass
        except AttributeError:
            pass

