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

import errno
import json
import logging
import os
import sys
import textwrap
from logging.handlers import RotatingFileHandler

import argparse
from botocore.exceptions import NoCredentialsError

import pcluster.cli_commands.delete as pcluster_delete
import pcluster.cli_commands.start as pcluster_start
import pcluster.cli_commands.stop as pcluster_stop
import pcluster.cli_commands.update as pcluster_update
import pcluster.commands as pcluster
import pcluster.configure.easyconfig as easyconfig
import pcluster.createami as createami
import pcluster.utils as utils
from pcluster.constants import SUPPORTED_OSS
from pcluster.dcv.connect import dcv_connect

LOGGER = logging.getLogger(__name__)


def create(args):
    pcluster.create(args)


def configure(args):
    easyconfig.configure(args)


def ssh(args, extra_args):
    pcluster.ssh(args, extra_args)


def dcv(args):
    dcv_connect(args)


def status(args):
    pcluster.status(args)


def list_stacks(args):
    pcluster.list_stacks(args)


def delete(args):
    pcluster_delete.delete(args)


def instances(args):
    pcluster.instances(args)


def update(args):
    pcluster_update.execute(args)


def version(args):
    print(pcluster.version())


def start(args):
    pcluster_start.start(args)


def stop(args):
    pcluster_stop.stop(args)


def create_ami(args):
    createami.create_ami(args)


def config_logger():
    logger = logging.getLogger("pcluster")
    file_only_logger = logging.getLogger("cli_log_file")
    logger.setLevel(logging.DEBUG)

    log_stream_handler = logging.StreamHandler(sys.stdout)
    log_stream_handler.setLevel(logging.INFO)
    log_stream_handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(log_stream_handler)

    logfile = utils.get_cli_log_file()
    try:
        os.makedirs(os.path.dirname(logfile))
    except OSError as e:
        if e.errno != errno.EEXIST:
            raise  # can safely ignore EEXISTS for this purpose...

    log_file_handler = RotatingFileHandler(logfile, maxBytes=5 * 1024 * 1024, backupCount=1)
    log_file_handler.setLevel(logging.DEBUG)
    log_file_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(module)s - %(message)s"))
    logger.addHandler(log_file_handler)
    file_only_logger.addHandler(log_file_handler)


def _addarg_config(subparser):
    subparser.add_argument("-c", "--config", dest="config_file", help="Defines an alternative config file.")


def _addarg_region(subparser):
    subparser.add_argument("-r", "--region", help="Indicates which region to connect to.")


def _addarg_nowait(subparser):
    subparser.add_argument(
        "-nw", "--nowait", action="store_true", help="Do not wait for stack events after executing stack command."
    )


def _get_parser():
    """
    Initialize ArgumentParser for pcluster commands.

    :return: the ArgumentParser object
    """
    parser = argparse.ArgumentParser(
        description="pcluster is the AWS ParallelCluster CLI and permits "
        "launching and management of HPC clusters in the AWS cloud.",
        epilog='For command specific flags, please run: "pcluster [command] --help"',
    )
    subparsers = parser.add_subparsers()
    subparsers.required = True
    subparsers.dest = "command"

    # create command subparser
    create_example = textwrap.dedent(
        """When the command is called and begins polling for status of that call,
it is safe to use 'Ctrl-C' to exit. You can return to viewing the current
status by calling "pcluster status mycluster".

Examples::

  $ pcluster create mycluster"""
    )
    pcreate = subparsers.add_parser(
        "create",
        help="Creates a new cluster.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=create_example,
    )
    pcreate.add_argument(
        "cluster_name",
        help="Defines the name of the cluster. The CloudFormation stack name will be " "parallelcluster-[cluster_name]",
    )
    _addarg_config(pcreate)
    _addarg_region(pcreate)
    _addarg_nowait(pcreate)
    pcreate.add_argument(
        "-nr", "--norollback", action="store_true", default=False, help="Disables stack rollback on error."
    )
    pcreate.add_argument(
        "-u",
        "--template-url",
        help="Specifies the URL for a custom CloudFormation template, if it was used at creation time.",
    )
    pcreate.add_argument(
        "-t",
        "--cluster-template",
        help="Indicates the 'cluster' section of the configuration file to use for cluster creation.",
    )
    pcreate.add_argument(
        "-p",
        "--extra-parameters",
        type=json.loads,
        help="Adds extra parameters to pass as input to the CloudFormation template.\n"
        'They must be in the form: {"ParameterKey1": "ParameterValue1", "ParameterKey2": "ParameterValue2"}',
    )
    pcreate.add_argument(
        "-g",
        "--tags",
        type=json.loads,
        help="Specifies additional tags to be added to the stack.\n"
        'They must be in the form: {"Key1": "Value1", "Key2": "Value2"}',
    )
    pcreate.set_defaults(func=create)

    # update command subparser
    pupdate = subparsers.add_parser(
        "update",
        help="Updates a running cluster using the values in the config file.",
        epilog="When the command is called and it begins polling for the status of that call, "
        'it is safe to "Ctrl-C" out. You can always return to that status by '
        'calling "pcluster status mycluster".',
    )
    pupdate.add_argument("cluster_name", help="Names the cluster to update.")
    _addarg_config(pupdate)
    _addarg_region(pupdate)
    _addarg_nowait(pupdate)
    pupdate.add_argument(
        "-nr",
        "--norollback",
        action="store_true",
        default=False,
        help="Disable CloudFormation stack rollback on error.",
    )
    pupdate.add_argument(
        "-t",
        "--cluster-template",
        help="Indicates the 'cluster' section of the configuration file to use for cluster update.",
    )
    pupdate.add_argument(
        "-p",
        "--extra-parameters",
        type=json.loads,
        help="Adds extra parameters to pass as input to the CloudFormation template.\n"
        'They must be in the form: {"ParameterKey1": "ParameterValue1", "ParameterKey2": "ParameterValue2"}',
    )
    pupdate.add_argument(
        "-rd",
        "--reset-desired",
        action="store_true",
        default=False,
        help="Resets the current ASG desired capacity to the initial config values.",
    )
    pupdate.add_argument(
        "-f", "--force", action="store_true", help="Forces the update skipping security checks. Not recommended."
    )
    pupdate.add_argument("-y", "--yes", action="store_true", help="Assumes 'yes' as answer to confirmation prompt.")
    pupdate.set_defaults(func=update)

    # delete command subparser
    pdelete = subparsers.add_parser(
        "delete",
        help="Deletes a cluster.",
        epilog="When the command is called and it begins polling for the status of that call "
        'it is safe to "Ctrl-C" out. You can return to that status by '
        'calling "pcluster status mycluster".',
    )
    pdelete.add_argument("cluster_name", help="Names the cluster to delete.")
    pdelete.add_argument(
        "--keep-logs",
        action="store_true",
        help="Keep cluster's CloudWatch log group data after deleting. The log group will persist until it's deleted "
        "manually, but log events will still expire based on the previously configured retention time.",
    )
    _addarg_config(pdelete)
    _addarg_region(pdelete)
    _addarg_nowait(pdelete)
    pdelete.set_defaults(func=delete)

    # start command subparser
    pstart = subparsers.add_parser(
        "start",
        help="Starts the compute fleet for a cluster that has been stopped.",
        epilog="This command sets the Auto Scaling Group parameters to either the initial "
        "configuration values (max_queue_size and initial_queue_size) specified in the "
        "template that was used to create the cluster or to the configuration values "
        "that were used to update the cluster after it was created.",
    )
    pstart.add_argument("cluster_name", help="Starts the compute fleet of the cluster name provided here.")
    _addarg_config(pstart)
    _addarg_region(pstart)
    pstart.set_defaults(func=start)

    # stop command subparser
    pstop = subparsers.add_parser(
        "stop",
        help="Stops the compute fleet, leaving the head node running.",
        epilog="This command sets the Auto Scaling Group parameters to min/max/desired = 0/0/0 and "
        "terminates the compute fleet. The head node will remain running. To terminate "
        "all EC2 resources and avoid EC2 charges, consider deleting the cluster.",
    )
    pstop.add_argument("cluster_name", help="Stops the compute fleet of the cluster name provided here.")
    _addarg_config(pstop)
    _addarg_region(pstop)
    pstop.set_defaults(func=stop)

    # status command subparser
    pstatus = subparsers.add_parser("status", help="Pulls the current status of the cluster.")
    pstatus.add_argument("cluster_name", help="Shows the status of the cluster with the name provided here.")
    _addarg_config(pstatus)
    _addarg_region(pstatus)
    _addarg_nowait(pstatus)
    pstatus.set_defaults(func=status)

    # list command subparser
    plist = subparsers.add_parser(
        "list",
        help="Displays a list of stacks associated with AWS ParallelCluster.",
        epilog="This command lists the names of any CloudFormation stacks named parallelcluster-*",
    )
    plist.add_argument("--color", action="store_true", default=False, help="Display the cluster status in color.")
    _addarg_config(plist)
    _addarg_region(plist)
    plist.set_defaults(func=list_stacks)

    # instances command subparser
    pinstances = subparsers.add_parser("instances", help="Displays a list of all instances in a cluster.")
    pinstances.add_argument("cluster_name", help="Display the instances for the cluster with the name provided here.")
    _addarg_config(pinstances)
    _addarg_region(pinstances)
    pinstances.set_defaults(func=instances)

    # ssh command subparser
    ssh_example = textwrap.dedent(
        """Example::

  $ pcluster ssh mycluster -i ~/.ssh/id_rsa

Returns an ssh command with the cluster username and IP address pre-populated::

  $ ssh ec2-user@1.1.1.1 -i ~/.ssh/id_rsa

The SSH command is defined in the global config file under the aliases section and it can be customized::

  [aliases]
  ssh = ssh {CFN_USER}@{MASTER_IP} {ARGS}

Variables substituted::

  {CFN_USER}
  {MASTER_IP}
  {ARGS} (only if specified on the cli)"""
    )
    pssh = subparsers.add_parser(
        "ssh",
        help="Connects to the head node instance using SSH.",
        description="Run ssh command with the cluster username and IP address pre-populated. "
        "Arbitrary arguments are appended to the end of the ssh command. "
        "This command can be customized in the aliases "
        "section of the config file.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=ssh_example,
    )
    _addarg_region(pssh)
    pssh.add_argument("cluster_name", help="Name of the cluster to connect to.")
    pssh.add_argument("-d", "--dryrun", action="store_true", default=False, help="Prints command and exits.")
    pssh.set_defaults(func=ssh)

    # createami command subparser
    pami = subparsers.add_parser(
        "createami", help="(Linux/macOS) Creates a custom AMI to use with AWS ParallelCluster."
    )
    pami.add_argument(
        "-ai",
        "--ami-id",
        dest="base_ami_id",
        required=True,
        help="Specifies the base AMI to use for building the AWS ParallelCluster AMI.",
    )
    pami.add_argument(
        "-os",
        "--os",
        dest="base_ami_os",
        required=True,
        help="Specifies the OS of the base AMI. " "Valid options are: %s." % ", ".join(SUPPORTED_OSS),
    )
    pami.add_argument(
        "-i",
        "--instance-type",
        dest="instance_type",
        default="t2.xlarge",
        help="Sets instance type to build the ami on. Defaults to t2.xlarge.",
    )
    pami.add_argument(
        "-ap",
        "--ami-name-prefix",
        dest="custom_ami_name_prefix",
        default="custom-ami-",
        help="Specifies the prefix name of the resulting AWS ParallelCluster AMI.",
    )
    pami.add_argument(
        "-cc",
        "--custom-cookbook",
        dest="custom_ami_cookbook",
        help="Specifies the cookbook to use to build the AWS ParallelCluster AMI.",
    )
    pami.add_argument(
        "--post-install",
        dest="post_install_script",
        help="Specifies the post install script to use to build the AWS ParallelCluster AMI.",
    )
    pami.add_argument(
        "--no-public-ip",
        dest="associate_public_ip",
        action="store_false",
        default=True,
        help="Do not associate public IP to the Packer instance. Defaults to associate public ip",
    )
    _addarg_config(pami)
    pami_group1 = pami.add_argument_group("Build AMI by using VPC settings from configuration file")
    pami_group1.add_argument(
        "-t",
        "--cluster-template",
        help="Specifies the 'cluster' section of the configuration file to retrieve VPC settings.",
    )
    pami_group2 = pami.add_argument_group("Build AMI in a custom VPC and Subnet")
    pami_group2.add_argument("--vpc-id", help="Specifies the VPC to use to build the AWS ParallelCluster AMI.")
    pami_group2.add_argument("--subnet-id", help="Specifies the Subnet to use to build the AWS ParallelCluster AMI.")
    _addarg_region(pami)
    pami.set_defaults(template_url=None)
    pami.set_defaults(func=create_ami)

    # configure command subparser
    pconfigure = subparsers.add_parser("configure", help="Start the AWS ParallelCluster configuration.")
    _addarg_config(pconfigure)
    _addarg_region(pconfigure)
    pconfigure.set_defaults(func=configure)

    # version command subparser
    pversion = subparsers.add_parser("version", help="Displays the version of AWS ParallelCluster.")
    pversion.set_defaults(func=version)

    # dcv command subparser
    pdcv = subparsers.add_parser(
        "dcv",
        help="The dcv command permits to use NICE DCV related features.",
        epilog='For dcv subcommand specific flags, please run: "pcluster dcv [subcommand] --help"',
    )
    dcv_subparsers = pdcv.add_subparsers()
    dcv_subparsers.required = True
    dcv_subparsers.dest = "subcommand"
    pdcv_connect = dcv_subparsers.add_parser(
        "connect", help="Permits to connect to the head node through an interactive session by using NICE DCV."
    )
    _addarg_region(pdcv_connect)
    pdcv_connect.add_argument("cluster_name", help="Name of the cluster to connect to")
    pdcv_connect.add_argument(
        "--key-path", "-k", dest="key_path", help="Key path of the SSH key to use for the connection"
    )
    pdcv_connect.add_argument("--show-url", "-s", action="store_true", default=False, help="Print URL and exit")
    pdcv.set_defaults(func=dcv)

    return parser


def main():
    config_logger()

    # TODO remove logger
    LOGGER.debug("pcluster CLI starting")

    parser = _get_parser()
    args, extra_args = parser.parse_known_args()
    LOGGER.debug(args)

    try:
        # set region in the environment to make it available to all the boto3 calls
        if "region" in args and args.region:
            os.environ["AWS_DEFAULT_REGION"] = args.region

        if args.func.__name__ == "ssh":
            args.func(args, extra_args)
        else:
            if extra_args:
                parser.print_usage()
                print("Invalid arguments %s..." % extra_args)
                sys.exit(1)
            args.func(args)
    except NoCredentialsError:
        LOGGER.error("AWS Credentials not found.")
        sys.exit(1)
    except KeyboardInterrupt:
        LOGGER.info("Exiting...")
        sys.exit(1)
    except Exception as e:
        LOGGER.exception("Unexpected error of type %s: %s", type(e).__name__, e)
        sys.exit(1)


if __name__ == "__main__":
    main()
