# Copyright 2019 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License").
# You may not use this file except in compliance with the License.
# A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file.
# This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, express or implied.
# See the License for the specific language governing permissions and limitations under the License.
import datetime
import logging
import multiprocessing
import os
import re
import sys
import time
import urllib.request
from tempfile import TemporaryDirectory

import argparse
import boto3
import pytest
from assertpy import assert_that
from conftest_networking import unmarshal_az_override
from framework.tests_configuration.config_renderer import dump_rendered_config_file, read_config_file
from framework.tests_configuration.config_utils import get_all_regions
from framework.tests_configuration.config_validator import assert_valid_config
from reports_generator import generate_cw_report, generate_json_report, generate_junitxml_merged_report
from retrying import retry
from utils import InstanceTypesData

logger = logging.getLogger()
logging.basicConfig(format="%(asctime)s - %(levelname)s - %(module)s - %(message)s", level=logging.INFO)

START_TIME = time.time()
START_TIME_ISO = datetime.datetime.fromtimestamp(START_TIME).isoformat()

LOGS_DIR = "{0}.logs".format(START_TIME)
OUT_DIR = "{0}.out".format(START_TIME)

TEST_DEFAULTS = {
    "parallelism": None,
    "retry_on_failures": False,
    "features": "",  # empty string means all
    "regions": [],
    "oss": [],
    "schedulers": [],
    "instances": [],
    "dry_run": False,
    "reports": [],
    "cw_region": "us-east-1",
    "cw_namespace": "ParallelCluster/IntegrationTests",
    "cw_timestamp_day_start": False,
    "sequential": False,
    "output_dir": "tests_outputs",
    "custom_node_url": None,
    "custom_cookbook_url": None,
    "createami_custom_cookbook_url": None,
    "cookbook_git_ref": None,
    "node_git_ref": None,
    "ami_owner": None,
    "createami_custom_node_url": None,
    "custom_awsbatchcli_url": None,
    "custom_ami": None,
    "pre_install": None,
    "post_install": None,
    "vpc_stack": None,
    "api_uri": None,
    "cluster": None,
    "policies_uri": None,
    "api_definition_s3_uri": None,
    "api_infrastructure_s3_uri": None,
    "no_delete": False,
    "benchmarks": False,
    "benchmarks_target_capacity": 200,
    "benchmarks_max_time": 30,
    "scaling_test_config": None,
    "stackname_suffix": "",
    "delete_logs_on_success": False,
    "tests_root_dir": "./tests",
    "instance_types_data": None,
    "use_default_iam_credentials": False,
    "iam_user_role_stack_name": None,
    "directory_stack_name": None,
    "ldaps_nlb_stack_name": None,
    "slurm_database_stack_name": None,
    "slurm_dbd_stack_name": None,
    "munge_key_secret_arn": None,
    "external_shared_storage_stack_name": None,
    "custom_security_groups_stack_name": None,
    "cluster_custom_resource_service_token": None,
    "resource_bucket": None,
    "lambda_layer_source": None,
    "force_run_instances": False,
    "force_elastic_ip": False,
    "retain_ad_stack": False,
}


def _init_argparser():
    parser = argparse.ArgumentParser(
        description="Run integration tests suite.", formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )

    parser.add_argument("--key-name", help="Key to use for EC2 instances", required=True)
    parser.add_argument("--key-path", help="Path to the key to use for SSH connections", required=True, type=_is_file)
    parser.add_argument(
        "-n", "--parallelism", help="Tests parallelism for every region.", default=TEST_DEFAULTS.get("parallelism")
    )
    parser.add_argument(
        "--sequential",
        help="Run tests in a single process. When not specified tests will spawn a process for each region under test.",
        action="store_true",
        default=TEST_DEFAULTS.get("sequential"),
    )
    parser.add_argument(
        "--credential",
        action="append",
        help="STS credential to assume when running tests in a specific region."
        "Credentials need to be in the format <region>,<endpoint>,<ARN>,<externalId> and can"
        " be specified multiple times. <region> represents the region credentials are used for, <endpoint> is the sts "
        " endpoint to contact in order to assume credentials, <account-id> is the id of the account where the role to "
        " assume is defined, <externalId> is the id to use when assuming the role. "
        "(e.g. ap-east-1,https://sts.us-east-1.amazonaws.com,arn:aws:iam::<account-id>:role/role-to-assume,externalId)",
        required=False,
    )
    parser.add_argument(
        "--use-default-iam-credentials",
        help="Use the default IAM creds to run pcluster CLI commands. Skips the creation of pcluster CLI IAM role.",
        action="store_true",
        default=TEST_DEFAULTS.get("use_default_iam_credentials"),
    )
    parser.add_argument(
        "--retry-on-failures",
        help="Retry once more the failed tests after a delay of 60 seconds.",
        action="store_true",
        default=TEST_DEFAULTS.get("retry_on_failures"),
    )
    parser.add_argument(
        "--tests-root-dir",
        help="Root dir where integration tests are defined",
        default=TEST_DEFAULTS.get("tests_root_dir"),
    )

    dimensions_group = parser.add_argument_group("Test dimensions")
    dimensions_group.add_argument(
        "-c",
        "--tests-config",
        help="Config file that specifies the tests to run and the dimensions to enable for each test. "
        "Note that when a config file is used the following flags are ignored: instances, regions, oss, schedulers. "
        "Refer to the docs for further details on the config format: "
        "https://github.com/aws/aws-parallelcluster/blob/develop/tests/integration-tests/README.md",
    )
    dimensions_group.add_argument(
        "-i",
        "--instances",
        help="AWS instances under test. Ignored when tests-config is used.",
        default=TEST_DEFAULTS.get("instances"),
        nargs="*",
    )
    dimensions_group.add_argument(
        "-o",
        "--oss",
        help="OSs under test. Ignored when tests-config is used.",
        default=TEST_DEFAULTS.get("oss"),
        nargs="*",
    )
    dimensions_group.add_argument(
        "-s",
        "--schedulers",
        help="Schedulers under test. Ignored when tests-config is used.",
        default=TEST_DEFAULTS.get("schedulers"),
        nargs="*",
    )
    dimensions_group.add_argument(
        "-r",
        "--regions",
        help="AWS regions where tests are executed. Ignored when tests-config is used.",
        default=TEST_DEFAULTS.get("regions"),
        nargs="*",
    )
    dimensions_group.add_argument(
        "-f",
        "--features",
        help="Run only tests for the listed features. Prepending the not keyword to the feature name causes the "
        "feature to be excluded.",
        default=TEST_DEFAULTS.get("features"),
        nargs="+",
    )

    reports_group = parser.add_argument_group("Test reports")
    reports_group.add_argument(
        "--show-output",
        help="Do not redirect tests stdout to file. Not recommended when running in multiple regions.",
        action="store_true",
        default=TEST_DEFAULTS.get("show_output"),
    )
    reports_group.add_argument(
        "--reports",
        help="create tests report files. junitxml creates a junit-xml style report file. html creates an html "
        "style report file. json creates a summary with details for each dimensions. cw publishes tests metrics into "
        "CloudWatch",
        nargs="+",
        choices=["html", "junitxml", "json", "cw"],
        default=TEST_DEFAULTS.get("reports"),
    )
    reports_group.add_argument(
        "--cw-region", help="Region where to publish CloudWatch metrics", default=TEST_DEFAULTS.get("cw_region")
    )
    reports_group.add_argument(
        "--cw-namespace",
        help="CloudWatch namespace where to publish metrics",
        default=TEST_DEFAULTS.get("cw_namespace"),
    )
    reports_group.add_argument(
        "--cw-timestamp-day-start",
        action="store_true",
        help="CloudWatch metrics pushed with at timestamp equal to the start of the current day (midnight)",
        default=TEST_DEFAULTS.get("cw_timestamp_day_start"),
    )
    reports_group.add_argument(
        "--output-dir", help="Directory where tests outputs are generated", default=TEST_DEFAULTS.get("output_dir")
    )

    custom_group = parser.add_argument_group("Custom packages and templates")
    custom_group.add_argument(
        "--custom-node-url",
        help="URL to a custom node package.",
        default=TEST_DEFAULTS.get("custom_node_url"),
        type=_is_url,
    )
    custom_group.add_argument(
        "--custom-cookbook-url",
        help="URL to a custom cookbook package.",
        default=TEST_DEFAULTS.get("custom_cookbook_url"),
        type=_is_url,
    )
    custom_group.add_argument(
        "--createami-custom-cookbook-url",
        help="URL to a custom cookbook package for the createami command.",
        default=TEST_DEFAULTS.get("createami_custom_cookbook_url"),
        type=_is_url,
    )
    custom_group.add_argument(
        "--createami-custom-node-url",
        help="URL to a custom node package for the createami command.",
        default=TEST_DEFAULTS.get("createami_custom_node_url"),
        type=_is_url,
    )
    custom_group.add_argument(
        "--custom-awsbatchcli-url",
        help="URL to a custom awsbatch cli package.",
        default=TEST_DEFAULTS.get("custom_awsbatchcli_url"),
        type=_is_url,
    )
    custom_group.add_argument(
        "--pre-install", help="URL to a pre install script", default=TEST_DEFAULTS.get("pre_install")
    )
    custom_group.add_argument(
        "--post-install", help="URL to a post install script", default=TEST_DEFAULTS.get("post_install")
    )
    custom_group.add_argument(
        "--instance-types-data",
        help="Additional information about instance types used in the tests. The format is a JSON map "
        "instance_type -> data, where data must respect the same structure returned by ec2 "
        "describe-instance-types",
        default=TEST_DEFAULTS.get("instance_types_data"),
    )

    ami_group = parser.add_argument_group("AMI selection parameters")
    ami_group.add_argument(
        "--custom-ami", help="custom AMI to use for all tests.", default=TEST_DEFAULTS.get("custom_ami")
    )
    ami_group.add_argument(
        "--pcluster-git-ref",
        help="Git ref of the custom cli package used to build the AMI.",
        default=TEST_DEFAULTS.get("pcluster_git_ref"),
    )
    ami_group.add_argument(
        "--cookbook-git-ref",
        help="Git ref of the custom cookbook package used to build the AMI.",
        default=TEST_DEFAULTS.get("cookbook_git_ref"),
    )
    ami_group.add_argument(
        "--node-git-ref",
        help="Git ref of the custom node package used to build the AMI.",
        default=TEST_DEFAULTS.get("node_git_ref"),
    )
    ami_group.add_argument(
        "--ami-owner",
        help="Override the owner value when fetching AMIs to use with cluster. By default pcluster uses amazon.",
        default=TEST_DEFAULTS.get("ami_owner"),
    )

    banchmarks_group = parser.add_argument_group("Benchmarks")
    banchmarks_group.add_argument(
        "--benchmarks",
        help="run benchmarks tests. This disables the execution of all tests defined under the tests directory.",
        action="store_true",
        default=TEST_DEFAULTS.get("benchmarks"),
    )
    banchmarks_group.add_argument(
        "--benchmarks-target-capacity",
        help="set the target capacity for benchmarks tests",
        default=TEST_DEFAULTS.get("benchmarks_target_capacity"),
        type=int,
    )
    banchmarks_group.add_argument(
        "--benchmarks-max-time",
        help="set the max waiting time in minutes for benchmarks tests",
        default=TEST_DEFAULTS.get("benchmarks_max_time"),
        type=int,
    )

    scaling_group = parser.add_argument_group("Scaling stress test options")
    scaling_group.add_argument(
        "--scaling-test-config",
        help="config file with scaling test parameters",
        default=TEST_DEFAULTS.get("scaling_test_config"),
    )

    custom_resource_group = parser.add_argument_group("CloudFormation / Custom Resource options")
    custom_resource_group.add_argument(
        "--cluster-custom-resource-service-token",
        help="ServiceToken (ARN) Cluster CloudFormation custom resource provider",
        default=TEST_DEFAULTS.get("cluster_custom_resource_service_token"),
    )
    custom_resource_group.add_argument(
        "--resource-bucket",
        help="Name of bucket to use to to retrieve standard hosted resources like CloudFormation templates.",
        default=TEST_DEFAULTS.get("resource_bucket"),
    )
    custom_resource_group.add_argument(
        "--lambda-layer-source",
        help="S3 URI of lambda layer to copy instead of building.",
        default=TEST_DEFAULTS.get("lambda_layer_source"),
    )

    api_group = parser.add_argument_group("API options")
    api_group.add_argument(
        "--api-definition-s3-uri",
        help="URI of the OpenAPI spec of the ParallelCluster API",
        default=TEST_DEFAULTS.get("api_definition_s3_uri"),
    )
    api_group.add_argument(
        "--api-infrastructure-s3-uri",
        help="URI of the CloudFormation template for the ParallelCluster API",
        default=TEST_DEFAULTS.get("api_definition_s3_uri"),
    )
    api_group.add_argument(
        "--api-uri", help="URI of an existing ParallelCluster API", default=TEST_DEFAULTS.get("api_uri")
    )
    api_group.add_argument(
        "--policies-uri",
        help="Use an existing policies URI instead of uploading one.",
        default=TEST_DEFAULTS.get("policies_uri"),
    )

    debug_group = parser.add_argument_group("Debugging/Development options")
    debug_group.add_argument(
        "--vpc-stack", help="Name of an existing vpc stack.", default=TEST_DEFAULTS.get("vpc_stack")
    )
    debug_group.add_argument(
        "--cluster", help="Use an existing cluster instead of creating one.", default=TEST_DEFAULTS.get("cluster")
    )
    debug_group.add_argument(
        "--no-delete",
        action="store_true",
        help="Don't delete stacks after tests are complete.",
        default=TEST_DEFAULTS.get("no_delete"),
    )
    debug_group.add_argument(
        "--delete-logs-on-success",
        help="delete CloudWatch logs when a test succeeds",
        action="store_true",
        default=TEST_DEFAULTS.get("delete_logs_on_success"),
    )
    debug_group.add_argument(
        "--stackname-suffix",
        help="set a suffix in the integration tests stack names",
        default=TEST_DEFAULTS.get("stackname_suffix"),
    )
    debug_group.add_argument(
        "--dry-run",
        help="Only show the list of tests that would run with specified options.",
        action="store_true",
        default=TEST_DEFAULTS.get("dry_run"),
    )
    debug_group.add_argument(
        "--iam-user-role-stack-name",
        help="Name of an existing IAM user role stack.",
        default=TEST_DEFAULTS.get("iam_user_role_stack_name"),
    )
    debug_group.add_argument(
        "--directory-stack-name",
        help="Name of CFN stack providing AD domain to be used for testing AD integration feature.",
        default=TEST_DEFAULTS.get("directory_stack_name"),
    )
    debug_group.add_argument(
        "--slurm-database-stack-name",
        help="Name of CFN stack providing database stack to be used for testing Slurm accounting feature.",
        default=TEST_DEFAULTS.get("slurm_database_stack_name"),
    )
    debug_group.add_argument(
        "--slurm-dbd-stack-name",
        help="Name of CFN stack providing external Slurm dbd stack to be used for testing Slurm accounting feature.",
        default=TEST_DEFAULTS.get("slurm_dbd_stack_name"),
    )
    debug_group.add_argument(
        "--munge-key-secret-arn",
        help="ARN of the secret containing the munge key to be used for testing Slurm accounting feature.",
        default=TEST_DEFAULTS.get("munge_key_secret_arn"),
    )
    debug_group.add_argument(
        "--external-shared-storage-stack-name",
        help="Name of existing external shared storage stack.",
        default=TEST_DEFAULTS.get("external_shared_storage_stack_name"),
    )
    debug_group.add_argument(
        "--custom-security-groups-stack-name",
        help="Name of existing custom security groups stack.",
        default=TEST_DEFAULTS.get("custom_security_groups_stack_name"),
    )

    debug_group.add_argument(
        "--force-run-instances",
        help="Force the usage of EC2 run-instances boto3 API instead of create-fleet for compute fleet scaling up."
        "Note: If there are multiple instances in the list, only the first will be used.",
        default=TEST_DEFAULTS.get("force_run_instances"),
        action="store_true",
    )
    debug_group.add_argument(
        "--force-elastic-ip",
        help="Force the usage of Elastic IP for Multi network interface EC2 instances",
        default=TEST_DEFAULTS.get("force_elastic_ip"),
        action="store_true",
    )
    debug_group.add_argument(
        "--retain-ad-stack",
        action="store_true",
        help="Retain AD stack and corresponding VPC stack.",
        default=TEST_DEFAULTS.get("retain_ad_stack"),
    )

    return parser


def _is_file(value):
    if not os.path.isfile(value):
        raise argparse.ArgumentTypeError("'{0}' is not a valid file".format(value))
    return value


@retry(stop_max_attempt_number=10, wait_fixed=5000)
def _is_url(value):
    scheme = urllib.request.urlparse(value).scheme
    if scheme in ["https", "s3", "file"]:
        try:
            if scheme == "s3":
                match = re.match(r"s3://(.*?)/(.*)", value)
                if not match or len(match.groups()) < 2:
                    raise argparse.ArgumentTypeError(f"'{value}' is not a valid S3url")
                else:
                    bucket_name, object_name = match.group(1), match.group(2)
                    boto3.client("s3").head_object(Bucket=bucket_name, Key=object_name)
            else:
                urllib.request.urlopen(value)
            return value
        except Exception as e:
            raise argparse.ArgumentTypeError(f"'{value}' is not a valid url:{e}")
    else:
        raise argparse.ArgumentTypeError("'{0}' is not a valid url".format(value))


def _test_config_file(config_file_path, config_args=None):
    _is_file(config_file_path)
    try:
        if config_args:
            config = read_config_file(config_file_path, **config_args)
        else:
            config = read_config_file(config_file_path)
        return config
    except Exception:
        raise argparse.ArgumentTypeError("'{0}' is not a valid test config".format(config_file_path))


def _join_with_not(args):
    """
    Join 'not' with next token, so they
    can be used together as single pytest marker
    """
    it = iter(args)
    while True:
        try:
            current = next(it)
        except StopIteration:
            break
        if current == "not":
            try:
                current += " " + next(it)
            except StopIteration:
                raise Exception("'not' needs to be always followed by an item")
        yield current


def _get_pytest_args(args, regions, log_file, out_dir):  # noqa: C901
    pytest_args = ["-s", "-vv", "-l"]

    pytest_args.append("--tests-log-file={0}/{1}".format(args.output_dir, log_file))
    pytest_args.append("--output-dir={0}/{1}".format(args.output_dir, out_dir))
    pytest_args.append(f"--key-name={args.key_name}")
    pytest_args.append(f"--key-path={args.key_path}")
    pytest_args.extend(["--stackname-suffix", args.stackname_suffix])

    pytest_args.extend(["--rootdir", args.tests_root_dir])
    pytest_args.append("--ignore=./benchmarks")
    if args.benchmarks:
        pytest_args.append("--benchmarks")

    # Show all tests durations
    pytest_args.append("--durations=0")
    # Run only tests with the given markers
    if args.features:
        pytest_args.append("-m")
        pytest_args.append(" or ".join(list(_join_with_not(args.features))))
    if args.tests_config:
        _set_tests_config_args(args, pytest_args, out_dir)
    if args.instance_types_data:
        pytest_args.append("--instance-types-data-file={0}".format(args.instance_types_data))

    if regions:
        pytest_args.append("--regions")
        pytest_args.extend(regions)
    if args.instances:
        pytest_args.append("--instances")
        pytest_args.extend(args.instances)
    if args.oss:
        pytest_args.append("--oss")
        pytest_args.extend(args.oss)
    if args.schedulers:
        pytest_args.append("--schedulers")
        pytest_args.extend(args.schedulers)

    if args.delete_logs_on_success:
        pytest_args.append("--delete-logs-on-success")

    if args.credential:
        pytest_args.append("--credential")
        pytest_args.extend(args.credential)

    if args.use_default_iam_credentials:
        pytest_args.append("--use-default-iam-credentials")

    if args.retry_on_failures:
        # Rerun tests on failures for one more time after 60 seconds delay
        pytest_args.extend(["--reruns", "1", "--reruns-delay", "60"])

    if args.parallelism:
        pytest_args.extend(["-n", args.parallelism])

    if args.dry_run:
        pytest_args.append("--collect-only")

    if any(report in ["junitxml", "json", "cw"] for report in args.reports):
        pytest_args.append("--junit-xml={0}/{1}/results.xml".format(args.output_dir, out_dir))

    if "html" in args.reports:
        pytest_args.append("--html={0}/{1}/results.html".format(args.output_dir, out_dir))
        pytest_args.append("--self-contained-html")
        pytest_args.append("--capture=tee-sys")

    if args.scaling_test_config:
        pytest_args.extend(["--scaling-test-config", args.scaling_test_config])

    _set_custom_packages_args(args, pytest_args)
    _set_ami_args(args, pytest_args)
    _set_custom_stack_args(args, pytest_args)
    _set_api_args(args, pytest_args)
    _set_custom_resource_args(args, pytest_args)
    _set_validate_instance_type_args(args, pytest_args)

    return pytest_args


def _set_custom_packages_args(args, pytest_args):  # noqa: C901
    if args.custom_node_url:
        pytest_args.extend(["--custom-node-package", args.custom_node_url])

    if args.custom_cookbook_url:
        pytest_args.extend(["--custom-chef-cookbook", args.custom_cookbook_url])

    if args.createami_custom_cookbook_url:
        pytest_args.extend(["--createami-custom-chef-cookbook", args.createami_custom_cookbook_url])

    if args.createami_custom_node_url:
        pytest_args.extend(["--createami-custom-node-package", args.createami_custom_node_url])

    if args.custom_awsbatchcli_url:
        pytest_args.extend(["--custom-awsbatchcli-package", args.custom_awsbatchcli_url])

    if args.pre_install:
        pytest_args.extend(["--pre-install", args.pre_install])

    if args.post_install:
        pytest_args.extend(["--post-install", args.post_install])


def _set_ami_args(args, pytest_args):
    if args.custom_ami:
        pytest_args.extend(["--custom-ami", args.custom_ami])

    if args.pcluster_git_ref:
        pytest_args.extend(["--pcluster-git-ref", args.pcluster_git_ref])

    if args.cookbook_git_ref:
        pytest_args.extend(["--cookbook-git-ref", args.cookbook_git_ref])

    if args.node_git_ref:
        pytest_args.extend(["--node-git-ref", args.node_git_ref])

    if args.ami_owner:
        pytest_args.extend(["--ami-owner", args.ami_owner])


def _set_custom_stack_args(args, pytest_args):  # noqa: C901
    if args.vpc_stack:
        pytest_args.extend(["--vpc-stack", args.vpc_stack])

    if args.cluster:
        pytest_args.extend(["--cluster", args.cluster])

    if args.no_delete:
        pytest_args.append("--no-delete")

    if args.force_run_instances:
        pytest_args.append("--force-run-instances")

    if args.iam_user_role_stack_name:
        pytest_args.extend(["--iam-user-role-stack-name", args.iam_user_role_stack_name])

    if args.directory_stack_name:
        pytest_args.extend(["--directory-stack-name", args.directory_stack_name])

    if args.slurm_database_stack_name:
        pytest_args.extend(["--slurm-database-stack-name", args.slurm_database_stack_name])

    if args.slurm_dbd_stack_name:
        pytest_args.extend(["--slurm-dbd-stack-name", args.slurm_dbd_stack_name])

    if args.munge_key_secret_arn:
        pytest_args.extend(["--munge-key-secret-arn", args.munge_key_secret_arn])

    if args.external_shared_storage_stack_name:
        pytest_args.extend(["--external-shared-storage-stack-name", args.external_shared_storage_stack_name])

    if args.retain_ad_stack:
        pytest_args.append("--retain-ad-stack")


def _set_validate_instance_type_args(args, pytest_args):
    if args.force_elastic_ip:
        pytest_args.append("--force-elastic-ip")


def _set_custom_resource_args(args, pytest_args):
    if args.cluster_custom_resource_service_token:
        pytest_args.extend(["--cluster-custom-resource-service-token", args.cluster_custom_resource_service_token])
    if args.resource_bucket:
        pytest_args.extend(["--resource-bucket", args.resource_bucket])
    if args.lambda_layer_source:
        pytest_args.extend(["--lambda-layer-source", args.lambda_layer_source])
    if args.custom_security_groups_stack_name:
        pytest_args.extend(["--custom-security-groups-stack-name", args.custom_security_groups_stack_name])


def _set_api_args(args, pytest_args):
    if args.api_definition_s3_uri:
        pytest_args.extend(["--api-definition-s3-uri", args.api_definition_s3_uri])

    if args.api_uri:
        pytest_args.extend(["--api-uri", args.api_uri])

    if args.api_infrastructure_s3_uri:
        pytest_args.extend(["--api-infrastructure-s3-uri", args.api_infrastructure_s3_uri])


def _set_tests_config_args(args, pytest_args, out_dir):
    # Dump the rendered file to avoid re-rendering in pytest processes
    rendered_config_file = f"{args.output_dir}/{out_dir}/tests_config.yaml"
    with open(rendered_config_file, "x", encoding="utf-8") as text_file:
        text_file.write(dump_rendered_config_file(args.tests_config))
    pytest_args.append(f"--tests-config-file={rendered_config_file}")


def _get_pytest_regionalized_args(region, args, our_dir, logs_dir):
    return _get_pytest_args(
        args=args,
        regions=[region],
        log_file="{0}/{1}.log".format(logs_dir, region),
        out_dir="{0}/{1}".format(our_dir, region),
    )


def _get_pytest_non_regionalized_args(args, out_dir, logs_dir):
    return _get_pytest_args(
        args=args, regions=args.regions, log_file="{0}/all_regions.log".format(logs_dir), out_dir=out_dir
    )


def _run_test_in_region(region, args, out_dir, logs_dir):
    out_dir_region = "{base_dir}/{out_dir}/{region}".format(base_dir=args.output_dir, out_dir=out_dir, region=region)
    os.makedirs(out_dir_region, exist_ok=True)

    # Redirect stdout to file
    if not args.show_output:
        sys.stdout = open("{0}/pytest.out".format(out_dir_region), "w")

    pytest_args_regionalized = _get_pytest_regionalized_args(region, args, out_dir, logs_dir)
    with TemporaryDirectory() as temp_dir:
        pytest_args_regionalized.extend(["--basetemp", temp_dir])
        logger.info("Starting pytest in region {0} with params {1}".format(region, pytest_args_regionalized))
        pytest.main(pytest_args_regionalized)


def _make_logging_dirs(base_dir):
    logs_dir = "{base_dir}/{logs_dir}".format(base_dir=base_dir, logs_dir=LOGS_DIR)
    os.makedirs(logs_dir, exist_ok=True)
    logger.info("Configured logs dir: {0}".format(logs_dir))
    out_dir = "{base_dir}/{out_dir}".format(base_dir=base_dir, out_dir=OUT_DIR)
    os.makedirs(out_dir, exist_ok=True)
    logger.info("Configured tests output dir: {0}".format(out_dir))


def _run_parallel(args):
    jobs = []
    if args.regions:
        enabled_regions = args.regions
    else:
        enabled_regions = get_all_regions(args.tests_config)

    # unmarshal az and collect unique regions
    unique_regions = set()
    for az in enabled_regions:
        unmarshalled_region = unmarshal_az_override(az)
        unique_regions.add(unmarshalled_region)

    for region in unique_regions:
        p = multiprocessing.Process(target=_run_test_in_region, args=(region, args, OUT_DIR, LOGS_DIR))
        jobs.append(p)
        p.start()

    for job in jobs:
        job.join()


def _get_config_arguments(args):
    test_config_args = {}
    if args.instances:
        test_config_args["INSTANCES"] = args.instances[0]
    if args.regions:
        test_config_args["REGIONS"] = args.regions[0]
    if args.oss:
        test_config_args["OSS"] = args.oss[0]
    return test_config_args


def _check_args(args):
    # If --cluster is set only one os, scheduler, instance type and region can be provided
    if args.cluster:
        if len(args.oss) > 1 or len(args.schedulers) > 1 or len(args.instances) > 1 or len(args.regions) > 1:
            logger.error(
                "when cluster option is specified, you can have a single value for oss, regions, instances "
                "and schedulers and you need to make sure they match the cluster specific ones"
            )
            exit(1)

    if not args.tests_config:
        assert_that(args.regions).described_as("--regions cannot be empty").is_not_empty()
        assert_that(args.instances).described_as("--instances cannot be empty").is_not_empty()
        assert_that(args.oss).described_as("--oss cannot be empty").is_not_empty()
        assert_that(args.schedulers).described_as("--schedulers cannot be empty").is_not_empty()
    else:
        try:
            test_config_args = _get_config_arguments(args)
            args.tests_config = _test_config_file(args.tests_config, test_config_args)
            assert_valid_config(args.tests_config, args.tests_root_dir)
            logger.info("Found valid config file:\n%s", dump_rendered_config_file(args.tests_config))
        except Exception:
            raise argparse.ArgumentTypeError("'{0}' is not a valid test config".format(args.tests_config))


def unset_proxy():
    """Unset proxies"""
    os.environ.pop("HTTP_PROXY", None)
    os.environ.pop("HTTPS_PROXY", None)
    os.environ.pop("http_proxy", None)
    os.environ.pop("https_proxy", None)


def _run_sequential(args):
    # Redirect stdout to file
    if not args.show_output:
        sys.stdout = open("{0}/{1}/pytest.out".format(args.output_dir, OUT_DIR), "w")

    pytest_args_non_regionalized = _get_pytest_non_regionalized_args(args, OUT_DIR, LOGS_DIR)
    logger.info("Starting pytest with params {0}".format(pytest_args_non_regionalized))
    pytest.main(pytest_args_non_regionalized)


def main():
    """Entrypoint for tests executor."""
    if sys.version_info < (3, 7):
        logger.error("test_runner requires python >= 3.7")
        exit(1)

    args = _init_argparser().parse_args()

    # Load additional instance types data, if provided.
    # This step must be done before loading test config files in order to resolve instance type placeholders.
    if args.instance_types_data:
        InstanceTypesData.load_additional_instance_types_data(args.instance_types_data)

    _check_args(args)
    logger.info("Parsed test_runner parameters {0}".format(args))

    # Unset any proxies used to avoid network issues with tests, such as DCV
    unset_proxy()

    _make_logging_dirs(args.output_dir)

    if args.sequential:
        _run_sequential(args)
    else:
        _run_parallel(args)

    logger.info("All tests completed!")

    reports_output_dir = "{base_dir}/{out_dir}".format(base_dir=args.output_dir, out_dir=OUT_DIR)
    if "junitxml" in args.reports:
        generate_junitxml_merged_report(reports_output_dir)

    if "json" in args.reports:
        logger.info("Generating tests report")
        generate_json_report(reports_output_dir)

    if "cw" in args.reports:
        logger.info("Publishing CloudWatch metrics")
        generate_cw_report(reports_output_dir, args.cw_namespace, args.cw_region, args.cw_timestamp_day_start)


if __name__ == "__main__":
    main()
