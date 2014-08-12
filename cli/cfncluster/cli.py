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

import os
import argparse
import logging
import platform

import cfncluster

def create(args):
    cfncluster.create(args)

def stop(args):
    pass

def status(args):
    cfncluster.status(args)

def list(args):
    cfncluster.list(args)

def delete(args):
    cfncluster.delete(args)

def instances(args):
    cfncluster.instances(args)

def update(args):
    cfncluster.update(args)

def main():
    # set up logging to file
    if platform.system() is 'Windows':
        logfile = os.path.expanduser('~\.cfncluster\cfncluster-cli.log')
    else:
        logfile = '/tmp/cfncluster-cli.log'
    logging.basicConfig(level=logging.DEBUG,
                        format='%(asctime)s %(name)-12s %(levelname)-8s %(message)s',
                        datefmt='%m-%d %H:%M',
                        filename=logfile,
                        filemode='w')
    # define a Handler which writes INFO messages or higher to the sys.stderr
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    # set a format which is simpler for console use
    formatter = logging.Formatter('%(name)-12s: %(levelname)-8s %(message)s')
    # tell the handler to use this format
    console.setFormatter(formatter)
    # add the handler to the root logger
    logging.getLogger('cfncluster.cli').addHandler(console)

    parser = argparse.ArgumentParser(description='cfncluster is a tool to launch and manage a cluster.')
    parser.add_argument("--config", "-c", dest="config_file", help='specify a alternative config file')
    parser.add_argument( "--region", "-r", dest="region", help='specify a specific region to connect to',
                        default=None)
    parser.add_argument( "--nowait", "-nw", dest="nowait", action='store_true',
                        help='do not wait for stack events, after executing stack command')

    subparsers = parser.add_subparsers()

    pcreate = subparsers.add_parser('create', help='creates a cluster')
    pcreate.add_argument("cluster_name", type=str, default=None,
                        help='create a cfncluster with the provided name.')
    pcreate.add_argument("--norollback", "-nr", action='store_true', dest="norollback", default=False,
                         help='disable stack rollback on error')
    pcreate.add_argument("--template-url", "-u", type=str, dest="template_url", default=None,
                         help='specify a URL for a custom cloudformation template')
    pcreate.add_argument("--cluster-template", "-t", type=str, dest="cluster_template", default=None,
                         help='specify a specific cluster template to use')
    pcreate.add_argument("--extra-parameters", "-p", type=str, dest="extra_parameters", default=None,
                         help='add extra parameters to stack create')
    pcreate.add_argument("--tags", "-g", type=str, dest="tags", default=None,
                         help='tags to be added to the stack')
    pcreate.set_defaults(func=create)

    pupdate = subparsers.add_parser('update', help='update a running cluster')
    pupdate.add_argument("cluster_name", type=str, default=None,
                        help='update a cfncluster with the provided name.')
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

    pstop = subparsers.add_parser('stop', help='stop a cluster')
    pstop.add_argument("cluster_name", type=str, default=None,
                        help='stop a cfncluster with the provided name.')
    pstop.set_defaults(func=stop)

    pdelete = subparsers.add_parser('delete', help='delete a cluster')
    pdelete.add_argument("cluster_name", type=str, default=None,
                        help='delete a cfncluster with the provided name.')
    pdelete.set_defaults(func=delete)

    pstatus = subparsers.add_parser('status', help='pull the current status of the cluster')
    pstatus.add_argument("cluster_name", type=str, default=None,
                        help='show the status of cfncluster with the provided name.')
    pstatus.set_defaults(func=status)

    plist = subparsers.add_parser('list', help='display a list of stacks associated with cfncluster')
    plist.set_defaults(func=list)

    pinstances = subparsers.add_parser('instances', help='display a list of all instances in a cluster')
    pinstances.add_argument("cluster_name", type=str, default=None,
                        help='show the status of cfncluster with the provided name.')
    pinstances.set_defaults(func=instances)

    args = parser.parse_args()
    logging.debug(args)
    args.func(args)