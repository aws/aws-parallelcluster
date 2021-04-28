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
from shutil import copyfile, rmtree
from tempfile import mkdtemp, mkstemp
from urllib.error import URLError
from urllib.parse import urlparse

import boto3
from botocore.exceptions import ClientError

import pcluster.utils as utils
from pcluster.commands import evaluate_pcluster_template_url
from pcluster.config.pcluster_config import PclusterConfig
from pcluster.constants import SUPPORTED_OSS

if sys.version_info[0] >= 3:
    from urllib.request import urlretrieve
else:
    from urllib import urlretrieve  # pylint: disable=no-name-in-module

LOGGER = logging.getLogger(__name__)


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
        urlretrieve(url=template_url, filename=tmp_template_file)  # nosec nosemgrep

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

        urlretrieve(url=cookbook_url, filename=tmp_cookbook_archive)  # nosec nosemgrep
        tar = tarfile.open(tmp_cookbook_archive)
        cookbook_archive_root = tar.firstmember.path
        tar.extractall(path=tmpdir)
        tar.close()

        return os.path.join(tmpdir, cookbook_archive_root)
    except (IOError, tarfile.ReadError) as e:
        LOGGER.error("Unable to download cookbook at URL %s", cookbook_url)
        LOGGER.critical("Error: %s", str(e))
        sys.exit(1)


def _is_valid_post_install_script(post_install_script_url):
    return urlparse(post_install_script_url).scheme in ["s3", "https", "file"]


def _get_current_timestamp():
    return datetime.datetime.now().strftime("%Y%m%d-%H%M%S")


def _get_post_install_script_dir(post_install_script_url, tmp_dir):
    try:
        tmp_post_install_script_folder = os.path.join(tmp_dir, "script")
        os.mkdir(tmp_post_install_script_folder)

        if post_install_script_url:
            LOGGER.info("Post install script url: %s", post_install_script_url)
            if not _is_valid_post_install_script(post_install_script_url):
                raise URLError(
                    "URL {0} is invalid. URLs starting with https, s3 and file are acceptable.".format(
                        post_install_script_url
                    )
                )

            tmp_post_install_script_path = os.path.join(
                tmp_post_install_script_folder, _get_current_timestamp() + "-" + post_install_script_url.split("/")[-1]
            )

            if urlparse(post_install_script_url).scheme == "https":
                urlretrieve(post_install_script_url, filename=tmp_post_install_script_path)  # nosec nosemgrep
            elif urlparse(post_install_script_url).scheme == "s3":
                output = urlparse(post_install_script_url)
                boto3.client("s3").download_file(output.netloc, output.path.lstrip("/"), tmp_post_install_script_path)
            elif urlparse(post_install_script_url).scheme == "file":
                copyfile(post_install_script_url.replace("file://", ""), tmp_post_install_script_path)
        else:
            tmp_post_install_script_path = None

        LOGGER.info(
            "Post install script dir %s",
            tmp_post_install_script_path if tmp_post_install_script_path else "not specified.",
        )
        return tmp_post_install_script_path
    except IOError as err:
        LOGGER.critical("I/O error: {0}".format(err))
        sys.exit(1)
    except ClientError as e:
        LOGGER.critical(e.response.get("Error").get("Message"))
        sys.exit(1)
    except URLError as e:
        LOGGER.critical(e.reason)
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
    _, path_log = mkstemp(prefix="packer.log." + _get_current_timestamp() + ".", text=True)
    LOGGER.info("Packer log: %s", path_log)
    try:
        dev_null = open(os.devnull, "rb")
        packer_env.update(os.environ.copy())
        process = sub.Popen(  # nosec
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
    ami_architecture_to_instance_type = {"x86_64": "t2.xlarge", "arm64": "m6g.xlarge"}
    instance_type = ami_architecture_to_instance_type.get(ami_architecture)
    if instance_type is None:
        LOGGER.error("Base AMI used in createami has an unsupported architecture: {0}".format(ami_architecture))
        sys.exit(1)

    # Ensure instance type is available in the selected region
    try:
        utils.InstanceTypeInfo.init_from_instance_type(instance_type)
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


def _validate_createami_args_ami_compatibility(args):
    """Validate the compatibility of the base_ami to the implied architectures and current pcluster version."""
    ami_info = utils.get_info_for_amis([args.base_ami_id])[0]

    # Validate the compatibility of the base_ami to the implied architectures
    ami_architecture = ami_info.get("Architecture")
    if not args.instance_type:
        args.instance_type = _get_default_createami_instance_type(ami_architecture)
    elif ami_architecture not in utils.get_supported_architectures_for_instance_type(args.instance_type):
        LOGGER.error(
            "Instance type used in createami, {0}, does not support the specified AMI's architecture, {1}".format(
                args.instance_type, ami_architecture
            )
        )
        sys.exit(1)

    if args.base_ami_os not in SUPPORTED_OSS:
        LOGGER.error(
            "ParallelCluster does not currently support the OS {0} on the base AMI's architecture {1}".format(
                args.base_ami_os, ami_architecture
            )
        )
        sys.exit(1)

    # Validate if the version of pcluster baked the base_ami is the same as current version
    utils.validate_pcluster_version_based_on_ami_name(ami_info.get("Name"))

    return ami_info


def create_ami(args):
    LOGGER.info("Building AWS ParallelCluster AMI. This could take a while...")

    # Do not autofresh; pcluster_config is only used to get info on vpc section, aws section, and template url
    # Logic in autofresh could make unexpected validations not needed in createami
    pcluster_config = PclusterConfig(config_file=args.config_file, fail_on_file_absence=True, auto_refresh=False)

    ami_info = _validate_createami_args_ami_compatibility(args)
    ami_architecture = ami_info.get("Architecture")

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

        template_url = evaluate_pcluster_template_url(pcluster_config)

        tmp_dir = mkdtemp()
        cookbook_dir = _get_cookbook_dir(aws_region, template_url, args, tmp_dir)

        _get_post_install_script_dir(args.post_install_script, tmp_dir)

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
