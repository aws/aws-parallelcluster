# Copyright 2013-2018 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
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
import textwrap

import argparse

from pcluster import easyconfig, pcluster


def create(args):
    pcluster.create(args)


def configure(args):
    easyconfig.configure(args)


def command(args, extra_args):
    pcluster.command(args, extra_args)


def status(args):
    pcluster.status(args)


def list_stacks(args):
    pcluster.list_stacks(args)


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
    logger = logging.getLogger("pcluster.pcluster")
    logger.setLevel(logging.DEBUG)

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(ch)

    logfile = os.path.expanduser(os.path.join("~", ".parallelcluster", "pcluster-cli.log"))
    try:
        os.makedirs(os.path.dirname(logfile))
    except OSError as e:
        if e.errno != errno.EEXIST:
            raise  # can safely ignore EEXISTS for this purpose...

    fh = logging.FileHandler(logfile)
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(name)s - %(message)s"))
    logger.addHandler(fh)


def _addarg_config(subparser):
    subparser.add_argument("-c", "--config", dest="config_file", help="alternative config file")


def _addarg_region(subparser):
    subparser.add_argument("-r", "--region", help="region to connect to")


def _addarg_nowait(subparser):
    subparser.add_argument(
        "-nw", "--nowait", action="store_true", help="do not wait for stack events, after executing stack command"
    )


def _get_parser():
    """
    Initialize ArgumentParser for pcluster commands.

    :return: the ArgumentParser object
    """
    parser = argparse.ArgumentParser(
        description="pcluster is the AWS ParallelCluster CLI and permits "
        "to launch and manage HPC clusters in the AWS cloud.",
        epilog='For command specific flags run "pcluster [command] --help"',
    )
    subparsers = parser.add_subparsers()
    subparsers.required = True
    subparsers.dest = "command"

    # create command subparser
    create_example = textwrap.dedent(
        """When the command is called and it starts polling for status of that call
it is safe to "Ctrl-C" out. You can always return to that status by calling "pcluster status mycluster".

Examples::

  $ pcluster create mycluster
  $ pcluster create mycluster --tags \'{ "Key1" : "Value1" , "Key2" : "Value2" }\'"""
    )
    pcreate = subparsers.add_parser(
        "create",
        help="Creates a new cluster.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=create_example,
    )
    pcreate.add_argument(
        "cluster_name",
        help="name for the cluster. The CloudFormation Stack name will be " "parallelcluster-[cluster_name]",
    )
    _addarg_config(pcreate)
    _addarg_region(pcreate)
    _addarg_nowait(pcreate)
    pcreate.add_argument(
        "-nr", "--norollback", action="store_true", default=False, help="disable stack rollback on error"
    )
    pcreate.add_argument(
        "-u",
        "--template-url",
        help="specify URL for the custom CloudFormation template, " "if it has been used at creation time",
    )
    pcreate.add_argument("-t", "--cluster-template", help="cluster template to use")
    pcreate.add_argument("-p", "--extra-parameters", type=json.loads, help="add extra parameters to stack create")
    pcreate.add_argument("-g", "--tags", type=json.loads, help="tags to be added to the stack")
    pcreate.set_defaults(func=create)

    # update command subparser
    pupdate = subparsers.add_parser(
        "update",
        help="Updates a running cluster by using the values in the config " "file or a TEMPLATE_URL provided.",
        epilog="When the command is called and it starts polling for status of that call "
        'it is safe to "Ctrl-C" out. You can always return to that status by '
        'calling "pcluster status mycluster"',
    )
    pupdate.add_argument("cluster_name", help="name of the cluster to update")
    _addarg_config(pupdate)
    _addarg_region(pupdate)
    _addarg_nowait(pupdate)
    pupdate.add_argument(
        "-nr", "--norollback", action="store_true", default=False, help="disable CloudFormation Stack rollback on error"
    )
    pupdate.add_argument("-u", "--template-url", help="URL for a custom CloudFormation template")
    pupdate.add_argument("-t", "--cluster-template", help="specific cluster template to use")
    pupdate.add_argument("-p", "--extra-parameters", help="add extra parameters to stack update")
    pupdate.add_argument(
        "-rd",
        "--reset-desired",
        action="store_true",
        default=False,
        help="reset the current ASG desired capacity to initial config values",
    )
    pupdate.set_defaults(func=update)

    # delete command subparser
    pdelete = subparsers.add_parser(
        "delete",
        help="Deletes a cluster.",
        epilog="When the command is called and it starts polling for status of that call "
        'it is safe to "Ctrl-C" out. You can always return to that status by '
        'calling "pcluster status mycluster"',
    )
    pdelete.add_argument("cluster_name", help="name of the cluster to delete")
    _addarg_config(pdelete)
    _addarg_region(pdelete)
    _addarg_nowait(pdelete)
    pdelete.set_defaults(func=delete)

    # start command subparser
    pstart = subparsers.add_parser(
        "start",
        help="Starts the compute fleet for a cluster that has been stopped.",
        epilog="This command sets the Auto Scaling Group parameters to either the initial "
        "configuration values (max_queue_size and initial_queue_size) from the "
        "template that was used to create the cluster or to the configuration values "
        "that were used to update the cluster since creation.",
    )
    pstart.add_argument("cluster_name", help="starts the compute fleet of the provided cluster name")
    _addarg_config(pstart)
    _addarg_region(pstart)
    pstart.set_defaults(func=start)

    # stop command subparser
    pstop = subparsers.add_parser(
        "stop",
        help="Stops the compute fleet, leaving the master server running.",
        epilog="Sets the Auto Scaling Group parameters to min/max/desired = 0/0/0 and "
        "terminates the compute fleet. The master will remain running. To terminate "
        "all EC2 resources and avoid EC2 charges, consider deleting the cluster.",
    )
    pstop.add_argument("cluster_name", help="stops the compute fleet of the provided cluster name")
    _addarg_config(pstop)
    _addarg_region(pstop)
    pstop.set_defaults(func=stop)

    # status command subparser
    pstatus = subparsers.add_parser("status", help="Pulls the current status of the cluster.")
    pstatus.add_argument("cluster_name", help="Shows the status of the cluster with the provided name.")
    _addarg_config(pstatus)
    _addarg_region(pstatus)
    _addarg_nowait(pstatus)
    pstatus.set_defaults(func=status)

    # list command subparser
    plist = subparsers.add_parser(
        "list",
        help="Displays a list of stacks associated with AWS ParallelCluster.",
        epilog="Lists the Stack Name of the CloudFormation stacks named parallelcluster-*",
    )
    _addarg_config(plist)
    _addarg_region(plist)
    plist.set_defaults(func=list_stacks)

    # instances command subparser
    pinstances = subparsers.add_parser("instances", help="Displays a list of all instances in a cluster.")
    pinstances.add_argument("cluster_name", help="Display the instances for the cluster with the provided name.")
    _addarg_config(pinstances)
    _addarg_region(pinstances)
    pinstances.set_defaults(func=instances)

    # ssh command subparser
    ssh_example = textwrap.dedent(
        """Example::

  $ pcluster ssh mycluster -i ~/.ssh/id_rsa

results in an ssh command with username and IP address pre-filled::

  $ ssh ec2-user@1.1.1.1 -i ~/.ssh/id_rsa

SSH command is defined in the global config file, under the aliases section and can be customized::

  [aliases]
  ssh = ssh {CFN_USER}@{MASTER_IP} {ARGS}

Variables substituted::

  {CFN_USER}
  {MASTER_IP}
  {ARGS} (only if specified on the cli)"""
    )
    pssh = subparsers.add_parser(
        "ssh",
        help="Connect to the master server using SSH.",
        description="Run ssh command with username and IP address pre-filled. "
        "Arbitrary arguments are appended to the end of the ssh command. "
        "This command may be customized in the aliases "
        "section of the config file.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=ssh_example,
    )
    pssh.add_argument("cluster_name", help="name of the cluster to connect to")
    pssh.add_argument("-d", "--dryrun", action="store_true", default=False, help="print command and exit")
    pssh.set_defaults(func=command)

    # createami command subparser
    pami = subparsers.add_parser("createami", help="(Linux/OSX) Creates a custom AMI to use with AWS ParallelCluster.")
    pami.add_argument(
        "-ai",
        "--ami-id",
        dest="base_ami_id",
        required=True,
        help="specify the base AMI to use for building the AWS ParallelCluster AMI",
    )
    pami.add_argument(
        "-os",
        "--os",
        dest="base_ami_os",
        required=True,
        help="specify the OS of the base AMI. " "Valid values are alinux, ubuntu1404, ubuntu1604, centos6 or centos7",
    )
    pami.add_argument(
        "-ap",
        "--ami-name-prefix",
        dest="custom_ami_name_prefix",
        default="custom-ami-",
        help="specify the prefix name of the resulting AWS ParallelCluster AMI",
    )
    pami.add_argument(
        "-cc",
        "--custom-cookbook",
        dest="custom_ami_cookbook",
        help="specify the cookbook to use to build the AWS ParallelCluster AMI",
    )
    _addarg_config(pami)
    _addarg_region(pami)
    pami.set_defaults(template_url=None)
    pami.set_defaults(func=create_ami)

    # configure command subparser
    pconfigure = subparsers.add_parser("configure", help="Start initial AWS ParallelCluster configuration.")
    _addarg_config(pconfigure)
    pconfigure.set_defaults(func=configure)

    # version command subparser
    pversion = subparsers.add_parser("version", help="Display version of AWS ParallelCluster.")
    pversion.set_defaults(func=version)

    return parser


def main():
    config_logger()

    logger = logging.getLogger("pcluster.pcluster")
    logger.debug("pcluster CLI starting")

    parser = _get_parser()
    args, extra_args = parser.parse_known_args()
    logger.debug(args)
    if args.func.__name__ == "command":
        args.func(args, extra_args)
    else:
        if extra_args:
            parser.print_usage()
            print("Invalid arguments %s..." % extra_args)
            sys.exit(1)
        args.func(args)
