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

# FIXME
# pylint: disable=too-many-locals
# pylint: disable=too-many-branches
# pylint: disable=too-many-statements

from __future__ import absolute_import, print_function

import datetime
import json
import logging
import os
import shlex
import subprocess as sub
import sys
import tarfile
import time
from builtins import str
from shutil import rmtree
from tempfile import mkdtemp, mkstemp

import boto3
from botocore.exceptions import ClientError

import pcluster.utils as utils
from pcluster.config.pcluster_config import PclusterConfig

if sys.version_info[0] >= 3:
    from urllib.request import urlretrieve
else:
    from urllib import urlretrieve  # pylint: disable=no-name-in-module

LOGGER = logging.getLogger(__name__)


def _evaluate_pcluster_template_url(pcluster_config, preferred_template_url=None):
    """
    Determine the CloudFormation Template URL to use.

    Order is 1) preferred_template_url 2) Config file 3) default for version + region.

    :param pcluster_config: PclusterConfig, it can contain the template_url
    :param preferred_template_url: preferred template url to use, if not None
    :return: the evaluated template url
    """
    configured_template_url = pcluster_config.get_section("cluster").get_param_value("template_url")

    return preferred_template_url or configured_template_url or _get_default_template_url(pcluster_config.region)


def _get_cookbook_url(region, template_url, args, tmpdir):
    if args.custom_ami_cookbook is not None:
        return args.custom_ami_cookbook

    cookbook_version = _get_cookbook_version(template_url, tmpdir)
    s3_suffix = ".cn" if region.startswith("cn") else ""
    return (
        "https://{region}-aws-parallelcluster.s3.{region}.amazonaws.com{suffix}/cookbooks/{cookbook_version}.tgz"
    ).format(region=region, suffix=s3_suffix, cookbook_version=cookbook_version)


def _get_cookbook_version(template_url, tmpdir):
    tmp_template_file = os.path.join(tmpdir, "aws-parallelcluster-template.json")
    try:
        LOGGER.info("Template: %s", template_url)
        urlretrieve(url=template_url, filename=tmp_template_file)

        with open(tmp_template_file) as cfn_file:
            cfn_data = json.load(cfn_file)

        return cfn_data.get("Mappings").get("PackagesVersions").get("default").get("cookbook")

    except IOError as e:
        LOGGER.error("Unable to download template at URL %s", template_url)
        LOGGER.critical("Error: %s", str(e))
        sys.exit(1)
    except (ValueError, AttributeError) as e:
        LOGGER.error("Unable to parse template at URL %s", template_url)
        LOGGER.critical("Error: %s", str(e))
        sys.exit(1)


def _get_cookbook_dir(region, template_url, args, tmpdir):
    cookbook_url = ""
    try:
        tmp_cookbook_archive = os.path.join(tmpdir, "aws-parallelcluster-cookbook.tgz")

        cookbook_url = _get_cookbook_url(region, template_url, args, tmpdir)
        LOGGER.info("Cookbook: %s", cookbook_url)

        urlretrieve(url=cookbook_url, filename=tmp_cookbook_archive)
        tar = tarfile.open(tmp_cookbook_archive)
        cookbook_archive_root = tar.firstmember.path
        tar.extractall(path=tmpdir)
        tar.close()

        return os.path.join(tmpdir, cookbook_archive_root)
    except (IOError, tarfile.ReadError) as e:
        LOGGER.error("Unable to download cookbook at URL %s", cookbook_url)
        LOGGER.critical("Error: %s", str(e))
        sys.exit(1)


def _dispose_packer_instance(results):
    time.sleep(2)
    try:
        ec2_client = boto3.client("ec2")
        instance = ec2_client.describe_instance_status(
            InstanceIds=[results["PACKER_INSTANCE_ID"]], IncludeAllInstances=True
        ).get("InstanceStatuses")[0]
        instance_state = instance.get("InstanceState").get("Name")
        if instance_state in ["running", "pending", "stopping", "stopped"]:
            LOGGER.info("Terminating Instance %s created by Packer", results["PACKER_INSTANCE_ID"])
            ec2_client.terminate_instances(InstanceIds=[results["PACKER_INSTANCE_ID"]])

    except ClientError as e:
        LOGGER.critical(e.response.get("Error").get("Message"))
        sys.exit(1)


def _run_packer(packer_command, packer_env):
    erase_line = "\x1b[2K"
    _command = shlex.split(packer_command)
    results = {}
    _, path_log = mkstemp(prefix="packer.log." + datetime.datetime.now().strftime("%Y%m%d-%H%M%S" + "."), text=True)
    LOGGER.info("Packer log: %s", path_log)
    try:
        dev_null = open(os.devnull, "rb")
        packer_env.update(os.environ.copy())
        process = sub.Popen(
            _command, env=packer_env, stdout=sub.PIPE, stderr=sub.STDOUT, stdin=dev_null, universal_newlines=True
        )

        with open(path_log, "w") as packer_log:
            while process.poll() is None:
                output_line = process.stdout.readline().strip()
                packer_log.write("\n%s" % output_line)
                packer_log.flush()
                sys.stdout.write(erase_line)
                sys.stdout.write("\rPacker status: %s" % output_line[:90] + (output_line[90:] and ".."))
                sys.stdout.flush()

                if output_line.find("packer build") > 0:
                    results["PACKER_COMMAND"] = output_line
                if output_line.find("Instance ID:") > 0:
                    results["PACKER_INSTANCE_ID"] = output_line.rsplit(":", 1)[1].strip(" \n\t")
                    sys.stdout.write(erase_line)
                    sys.stdout.write("\rPacker Instance ID: %s\n" % results["PACKER_INSTANCE_ID"])
                    sys.stdout.flush()
                if output_line.find("AMI:") > 0:
                    results["PACKER_CREATED_AMI"] = output_line.rsplit(":", 1)[1].strip(" \n\t")
                if output_line.find("Prevalidating AMI Name:") > 0:
                    results["PACKER_CREATED_AMI_NAME"] = output_line.rsplit(":", 1)[1].strip(" \n\t")
        sys.stdout.write("\texit code %s\n" % process.returncode)
        sys.stdout.flush()
        return results
    except sub.CalledProcessError:
        sys.stdout.flush()
        LOGGER.error("Failed to run %s\n", _command)
        sys.exit(1)
    except (IOError, OSError):  # noqa: B014
        sys.stdout.flush()
        LOGGER.error("Failed to run %s\nCommand not found", packer_command)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.stdout.flush()
        LOGGER.info("\nExiting...")
        sys.exit(0)
    finally:
        dev_null.close()
        if results.get("PACKER_INSTANCE_ID"):
            _dispose_packer_instance(results)


def _print_create_ami_results(results):
    if results.get("PACKER_CREATED_AMI"):
        LOGGER.info(
            "\nCustom AMI %s created with name %s", results["PACKER_CREATED_AMI"], results["PACKER_CREATED_AMI_NAME"]
        )
        print(
            "\nTo use it, add the following variable to the AWS ParallelCluster config file, "
            "under the [cluster ...] section"
        )
        print("custom_ami = %s" % results["PACKER_CREATED_AMI"])
    else:
        LOGGER.info("\nNo custom AMI created")


def _get_default_createami_instance_type(ami_architecture):
    """Return instance type to build AMI on based on architecture supported by base AMI."""
    ami_architecture_to_instance_type = {
        "x86_64": "t2.xlarge",
        "arm64": "m6g.xlarge",
    }
    instance_type = ami_architecture_to_instance_type.get(ami_architecture)
    if instance_type is None:
        LOGGER.error("Base AMI used in createami has an unsupported architecture: {0}".format(ami_architecture))
        sys.exit(1)

    # Ensure instance type is avaiable in the selected region
    try:
        utils.get_instance_types_info([instance_type], fail_on_error=True)
    except SystemExit as system_exit:
        if "instance types do not exist" in str(system_exit):
            LOGGER.error(
                "The default instance type to build on for architecture {0} is {1}. This instance type is not "
                "available in {2}. Please specify a different region or an instance type in the region that supports "
                "the AMI's architecture.".format(ami_architecture, instance_type, os.environ.get("AWS_DEFAULT_REGION"))
            )
            sys.exit(1)
        raise
    return instance_type


def _validate_createami_args_architecture_compatibility(args):
    """Validate the compatibility of the implied architectures for the args passed to the createami command."""
    ami_architecture = utils.get_info_for_amis([args.base_ami_id])[0].get("Architecture")
    if not args.instance_type:
        args.instance_type = _get_default_createami_instance_type(ami_architecture)
    elif ami_architecture not in utils.get_supported_architectures_for_instance_type(args.instance_type):
        LOGGER.error(
            "Instance type used in createami, {0}, does not support the specified AMI's architecture, {1}".format(
                args.instance_type, ami_architecture
            )
        )
        sys.exit(1)

    if args.base_ami_os not in utils.get_supported_os_for_architecture(ami_architecture):
        LOGGER.error(
            "ParallelCluster does not currently support the OS {0} on the base AMI's architecture {1}".format(
                args.base_ami_os, ami_architecture
            )
        )
        sys.exit(1)

    return ami_architecture


def create_ami(args):
    LOGGER.info("Building AWS ParallelCluster AMI. This could take a while...")

    # Ensure AWS_DEFAULT_REGION env is set.
    # Set it explicitly if the CLI arg was passed. Otherwise let the config object do it.
    if args.region:
        os.environ["AWS_DEFAULT_REGION"] = args.region
    pcluster_config = PclusterConfig(config_file=args.config_file, fail_on_file_absence=True)

    ami_architecture = _validate_createami_args_architecture_compatibility(args)

    LOGGER.debug("Building AMI based on args %s", str(args))
    results = {}

    instance_type = args.instance_type
    try:
        vpc_section = pcluster_config.get_section("vpc")
        vpc_id = args.vpc_id if args.vpc_id else vpc_section.get_param_value("vpc_id")
        subnet_id = args.subnet_id if args.subnet_id else vpc_section.get_param_value("master_subnet_id")

        packer_env = {
            "CUSTOM_AMI_ID": args.base_ami_id,
            "AWS_FLAVOR_ID": instance_type,
            "AMI_NAME_PREFIX": args.custom_ami_name_prefix,
            "AWS_VPC_ID": vpc_id,
            "AWS_SUBNET_ID": subnet_id,
            "ASSOCIATE_PUBLIC_IP": "true" if args.associate_public_ip else "false",
        }

        aws_section = pcluster_config.get_section("aws")
        aws_region = aws_section.get_param_value("aws_region_name")
        if aws_section and aws_section.get_param_value("aws_access_key_id"):
            packer_env["AWS_ACCESS_KEY_ID"] = aws_section.get_param_value("aws_access_key_id")
        if aws_section and aws_section.get_param_value("aws_secret_access_key"):
            packer_env["AWS_SECRET_ACCESS_KEY"] = aws_section.get_param_value("aws_secret_access_key")

        LOGGER.info("Base AMI ID: %s", args.base_ami_id)
        LOGGER.info("Base AMI OS: %s", args.base_ami_os)
        LOGGER.info("Instance Type: %s", instance_type)
        LOGGER.info("Region: %s", aws_region)
        LOGGER.info("VPC ID: %s", vpc_id)
        LOGGER.info("Subnet ID: %s", subnet_id)

        template_url = _evaluate_pcluster_template_url(pcluster_config)

        tmp_dir = mkdtemp()
        cookbook_dir = _get_cookbook_dir(aws_region, template_url, args, tmp_dir)

        packer_command = (
            cookbook_dir
            + "/amis/build_ami.sh --os "
            + args.base_ami_os
            + " --partition region"
            + " --region "
            + aws_region
            + " --custom"
            + " --arch "
            + ami_architecture
        )

        results = _run_packer(packer_command, packer_env)
    except KeyboardInterrupt:
        LOGGER.info("\nExiting...")
        sys.exit(0)
    finally:
        _print_create_ami_results(results)
        if "tmp_dir" in locals() and tmp_dir:
            rmtree(tmp_dir)


def _get_default_template_url(region):
    return (
        "https://{REGION}-aws-parallelcluster.s3.{REGION}.amazonaws.com{SUFFIX}/templates/"
        "aws-parallelcluster-{VERSION}.cfn.json".format(
            REGION=region, SUFFIX=".cn" if region.startswith("cn") else "", VERSION=utils.get_installed_version()
        )
    )
