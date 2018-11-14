# Copyright 2013-2018 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance with the
# License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
from __future__ import absolute_import

import errno
import json
import logging
import os
import sys

import argparse

from . import easyconfig
from . import pcluster


def create(args):
    pcluster.create(args)


def configure(args):
    easyconfig.configure(args)


def command(args, extra_args):
    pcluster.command(args, extra_args)


def status(args):
    pcluster.status(args)


def list(args):
    pcluster.list(args)


def delete(args):
    pcluster.delete(args)


def instances(args):
    pcluster.instances(args)


def update(args):
    pcluster.update(args)


def version(args):
    pcluster.version(args)


def start(args):
    pcluster.start(args)


def stop(args):
    pcluster.stop(args)


def create_ami(args):
    pcluster.create_ami(args)


def config_logger():
    logger = logging.getLogger('pcluster.pcluster')
    logger.setLevel(logging.DEBUG)

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter('%(message)s'))
    logger.addHandler(ch)

    logfile = os.path.expanduser(os.path.join('~', '.parallelcluster', 'pcluster-cli.log'))
    try:
        os.makedirs(os.path.dirname(logfile))
    except OSError as e:
        if e.errno != errno.EEXIST:
            raise # can safely ignore EEXISTS for this purpose...

    fh = logging.FileHandler(logfile)
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(name)s - %(message)s'))
    logger.addHandler(fh)


def _addarg_config(subparser):
    subparser.add_argument("--config", "-c", dest="config_file", help='specify an alternative config file')


def _addarg_region(subparser):
    subparser.add_argument("--region", "-r", dest="region", help='specify a specific region to connect to', default=None)


def _addarg_nowait(subparser):
    subparser.add_argument("--nowait", "-nw", dest="nowait", action='store_true',
                    help='do not wait for stack events, after executing stack command')


def main():
    config_logger()

    logger = logging.getLogger('pcluster.pcluster')
    logger.debug("pcluster cli starting")

    parser = argparse.ArgumentParser(description='pcluster is a tool to launch and manage a cluster.',
                                     epilog="For command specific flags run pcluster [command] --help")
    subparsers = parser.add_subparsers()
    subparsers.required = True
    subparsers.dest = 'command'

    pcreate = subparsers.add_parser('create', help='creates a cluster')
    pcreate.add_argument("cluster_name", type=str, default=None,
                        help='create an AWS ParallelCluster with the provided name.')
    _addarg_config(pcreate)
    _addarg_region(pcreate)
    _addarg_nowait(pcreate)
    pcreate.add_argument("--norollback", "-nr", action='store_true', dest="norollback", default=False,
                         help='disable stack rollback on error')
    pcreate.add_argument("--template-url", "-u", type=str, dest="template_url", default=None,
                         help='specify a URL for a custom cloudformation template')
    pcreate.add_argument("--cluster-template", "-t", type=str, dest="cluster_template", default=None,
                         help='specify a specific cluster template to use')
    pcreate.add_argument("--extra-parameters", "-p", type=json.loads, dest="extra_parameters", default=None,
                         help='add extra parameters to stack create')
    pcreate.add_argument("--tags", "-g", type=json.loads, dest="tags", default=None,
                         help='tags to be added to the stack')
    pcreate.set_defaults(func=create)

    pupdate = subparsers.add_parser('update', help='update a running cluster')
    pupdate.add_argument("cluster_name", type=str, default=None,
                        help='update the AWS ParallelCluster with the provided name.')
    _addarg_config(pupdate)
    _addarg_region(pupdate)
    _addarg_nowait(pupdate)
    pupdate.add_argument("--norollback", "-nr", action='store_true', dest="norollback", default=False,
                         help='disable stack rollback on error')
    pupdate.add_argument("--template-url", "-u", type=str, dest="template_url", default=None,
                         help='specify a URL for a custom cloudformation template')
    pupdate.add_argument("--cluster-template", "-t", type=str, dest="cluster_template", default=None,
                         help='specify a specific cluster template to use')
    pupdate.add_argument("--extra-parameters", "-p", type=str, dest="extra_parameters", default=None,
                         help='add extra parameters to stack update')
    pupdate.add_argument("--reset-desired", "-rd", action='store_true', dest="reset_desired", default=False,
                         help='reset the current ASG desired capacity to initial config values')
    pupdate.set_defaults(func=update)

    pdelete = subparsers.add_parser('delete', help='delete a cluster')
    pdelete.add_argument("cluster_name", type=str, default=None,
                         help='delete the AWS ParallelCluster with the provided name.')
    _addarg_config(pdelete)
    _addarg_region(pdelete)
    _addarg_nowait(pdelete)
    pdelete.set_defaults(func=delete)

    pstart = subparsers.add_parser('start', help='start the compute fleet that has been stopped')
    pstart.add_argument("cluster_name", type=str, default=None,
                        help='starts the compute fleet of the provided cluster name.')
    _addarg_config(pstart)
    _addarg_region(pstart)
    pstart.set_defaults(func=start)

    pstop = subparsers.add_parser('stop', help='stop the compute fleet, but leave the master server running for '
                                               'debugging/development')
    pstop.add_argument("cluster_name", type=str, default=None,
                       help='stops the compute fleet of the provided cluster name.')
    _addarg_config(pstop)
    _addarg_region(pstop)
    pstop.set_defaults(func=stop)

    pstatus = subparsers.add_parser('status', help='pull the current status of the cluster')
    pstatus.add_argument("cluster_name", type=str, default=None,
                         help='show the status of the AWS ParallelCluster with the provided name.')
    _addarg_config(pstatus)
    _addarg_region(pstatus)
    _addarg_nowait(pstatus)
    pstatus.set_defaults(func=status)

    plist = subparsers.add_parser('list', help='display a list of stacks associated with AWS ParallelCluster')
    _addarg_config(plist)
    _addarg_region(plist)
    plist.set_defaults(func=list)

    pinstances = subparsers.add_parser('instances', help='display a list of all instances in a cluster')
    pinstances.add_argument("cluster_name", type=str, default=None,
                            help='show the status of the AWS ParallelCluster with the provided name.')
    _addarg_config(pinstances)
    _addarg_region(pinstances)
    pinstances.set_defaults(func=instances)

    pssh = subparsers.add_parser('ssh', help='connect to the master server using SSH',
                                 description='run ssh command with username and ip address pre-filled. '\
                                             'Arbitrary arguments are appended to the end of the ssh commmand. '\
                                             'This command may be customized in the aliases '
                                             'section of the config file.')
    pssh.add_argument("cluster_name", type=str, default=None,
                      help='name of the cluster to set variables for.')
    pssh.add_argument("--dryrun", "-d", action='store_true', dest="dryrun", default=False,
                      help='print command and exit.')
    pssh.set_defaults(func=command)

    pconfigure = subparsers.add_parser('configure', help='creating initial AWS ParallelCluster configuration')
    _addarg_config(pconfigure)
    pconfigure.set_defaults(func=configure)

    pversion = subparsers.add_parser('version', help='display version of AWS ParallelCluster')
    pversion.set_defaults(func=version)

    pami = subparsers.add_parser('createami', help='(Linux/OSX) create a custom AMI to use with AWS ParallelCluster')
    pami.add_argument("--ami-id", "-ai", type=str, dest="base_ami_id", default=None, required=True,
                      help="specify the base AMI to use for building the AWS ParallelCluster AMI")
    pami.add_argument("--os", "-os", type=str, dest="base_ami_os", default=None, required=True,
                      help="specify the OS of the base AMI. "
                           "Valid values are alinux, ubuntu1404, ubuntu1604, centos6 or centos7")
    pami.add_argument("--ami-name-prefix", "-ap", type=str, dest="custom_ami_name_prefix", default='custom-ami-',
                      help="specify the prefix name of the resulting AWS ParallelCluster AMI")
    pami.add_argument("--custom-cookbook", "-cc", type=str, dest="custom_ami_cookbook", default=None,
                      help="specify the cookbook to use to build the AWS ParallelCluster AMI")
    _addarg_config(pami)
    _addarg_region(pami)
    pami.set_defaults(template_url=None)
    pami.set_defaults(func=create_ami)

    args, extra_args = parser.parse_known_args()
    logger.debug(args)
    if args.func.__name__ == 'command':
        args.func(args, extra_args)
    else:
        if extra_args:
            parser.print_usage()
            print('Invalid arguments %s...' % extra_args)
            sys.exit(1)
        args.func(args)
