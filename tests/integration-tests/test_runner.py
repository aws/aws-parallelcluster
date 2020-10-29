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
import sys
import time
from tempfile import TemporaryDirectory

import argparse
import pytest
from reports_generator import generate_cw_report, generate_json_report, generate_junitxml_merged_report

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
    "regions": [
        "us-east-1",
        "us-east-2",
        "us-west-1",
        "us-west-2",
        "ca-central-1",
        "eu-west-1",
        "eu-west-2",
        "eu-central-1",
        "ap-southeast-1",
        "ap-southeast-2",
        "ap-northeast-1",
        "ap-south-1",
        "sa-east-1",
        "eu-west-3",
    ],
    "oss": ["alinux", "alinux2", "centos7", "centos8", "ubuntu1804", "ubuntu1604"],
    "schedulers": ["sge", "slurm", "torque", "awsbatch"],
    "instances": ["c4.xlarge", "c5.xlarge"],
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
    "custom_template_url": None,
    "custom_awsbatchcli_url": None,
    "custom_hit_template_url": None,
    "custom_ami": None,
    "pre_install": None,
    "post_install": None,
    "vpc_stack": None,
    "cluster": None,
    "no_delete": False,
    "benchmarks": False,
    "benchmarks_target_capacity": 200,
    "benchmarks_max_time": 30,
    "stackname_suffix": "",
    "keep_logs_on_cluster_failure": False,
    "keep_logs_on_test_failure": False,
}


def _init_argparser():
    parser = argparse.ArgumentParser(
        description="Run integration tests suite.", formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        "-f",
        "--features",
        help="Run only tests for the listed features. Prepending the not keyword to the feature name causes the "
        "feature to be excluded.",
        default=TEST_DEFAULTS.get("features"),
        nargs="+",
    )
    parser.add_argument(
        "-r", "--regions", help="AWS region where tests are executed.", default=TEST_DEFAULTS.get("regions"), nargs="+"
    )
    parser.add_argument(
        "--credential",
        action="append",
        help="STS credential endpoint, in the format <region>,<endpoint>,<ARN>,<externalId>. "
        "Could be specified multiple times.",
        required=False,
    )
    parser.add_argument(
        "-i", "--instances", help="AWS instances under test.", default=TEST_DEFAULTS.get("instances"), nargs="+"
    )
    parser.add_argument("-o", "--oss", help="OSs under test.", default=TEST_DEFAULTS.get("oss"), nargs="+")
    parser.add_argument(
        "-s", "--schedulers", help="Schedulers under test.", default=TEST_DEFAULTS.get("schedulers"), nargs="+"
    )
    parser.add_argument(
        "-n", "--parallelism", help="Tests parallelism for every region.", default=TEST_DEFAULTS.get("parallelism")
    )
    parser.add_argument(
        "--retry-on-failures",
        help="Retry once more the failed tests after a delay of 60 seconds.",
        action="store_true",
        default=TEST_DEFAULTS.get("retry_on_failures"),
    )
    parser.add_argument(
        "--dry-run",
        help="Only show the list of tests that would run with specified options.",
        action="store_true",
        default=TEST_DEFAULTS.get("dry_run"),
    )
    parser.add_argument(
        "--show-output",
        help="Do not redirect tests stdout to file. Not recommended when running in multiple regions.",
        action="store_true",
        default=TEST_DEFAULTS.get("show_output"),
    )
    parser.add_argument(
        "--sequential",
        help="Run tests in a single process. When not specified tests will run concurrently in all regions.",
        action="store_true",
        default=TEST_DEFAULTS.get("sequential"),
    )
    parser.add_argument(
        "--reports",
        help="create tests report files. junitxml creates a junit-xml style report file. html creates an html "
        "style report file. json creates a summary with details for each dimensions. cw publishes tests metrics into "
        "CloudWatch",
        nargs="+",
        choices=["html", "junitxml", "json", "cw"],
        default=TEST_DEFAULTS.get("reports"),
    )
    parser.add_argument(
        "--cw-region", help="Region where to publish CloudWatch metrics", default=TEST_DEFAULTS.get("cw_region")
    )
    parser.add_argument(
        "--cw-namespace",
        help="CloudWatch namespace where to publish metrics",
        default=TEST_DEFAULTS.get("cw_namespace"),
    )
    parser.add_argument(
        "--cw-timestamp-day-start",
        action="store_true",
        help="CloudWatch metrics pushed with at timestamp equal to the start of the current day (midnight)",
        default=TEST_DEFAULTS.get("cw_timestamp_day_start"),
    )
    parser.add_argument("--key-name", help="Key to use for EC2 instances", required=True)
    parser.add_argument("--key-path", help="Path to the key to use for SSH connections", required=True, type=_is_file)
    parser.add_argument(
        "--output-dir", help="Directory where tests outputs are generated", default=TEST_DEFAULTS.get("output_dir")
    )
    parser.add_argument(
        "--custom-node-url", help="URL to a custom node package.", default=TEST_DEFAULTS.get("custom_node_url")
    )
    parser.add_argument(
        "--custom-cookbook-url",
        help="URL to a custom cookbook package.",
        default=TEST_DEFAULTS.get("custom_cookbook_url"),
    )
    parser.add_argument(
        "--createami-custom-cookbook-url",
        help="URL to a custom cookbook package for the createami command.",
        default=TEST_DEFAULTS.get("createami_custom_cookbook_url"),
    )
    parser.add_argument(
        "--custom-template-url", help="URL to a custom cfn template.", default=TEST_DEFAULTS.get("custom_template_url")
    )
    parser.add_argument(
        "--custom-hit-template-url",
        help="URL to a custom hit cfn template.",
        default=TEST_DEFAULTS.get("custom_hit_template_url"),
    )
    parser.add_argument(
        "--custom-awsbatchcli-url",
        help="URL to a custom awsbatch cli package.",
        default=TEST_DEFAULTS.get("custom_awsbatchcli_url"),
    )
    parser.add_argument(
        "--custom-ami", help="custom AMI to use for all tests.", default=TEST_DEFAULTS.get("custom_ami")
    )
    parser.add_argument("--pre-install", help="URL to a pre install script", default=TEST_DEFAULTS.get("pre_install"))
    parser.add_argument(
        "--post-install", help="URL to a post install script", default=TEST_DEFAULTS.get("post_install")
    )
    parser.add_argument("--vpc-stack", help="Name of an existing vpc stack.", default=TEST_DEFAULTS.get("vpc_stack"))
    parser.add_argument(
        "--cluster", help="Use an existing cluster instead of creating one.", default=TEST_DEFAULTS.get("cluster")
    )
    parser.add_argument(
        "--no-delete",
        action="store_true",
        help="Don't delete stacks after tests are complete.",
        default=TEST_DEFAULTS.get("no_delete"),
    )
    parser.add_argument(
        "--benchmarks",
        help="run benchmarks tests. This disables the execution of all tests defined under the tests directory.",
        action="store_true",
        default=TEST_DEFAULTS.get("benchmarks"),
    )
    parser.add_argument(
        "--benchmarks-target-capacity",
        help="set the target capacity for benchmarks tests",
        default=TEST_DEFAULTS.get("benchmarks_target_capacity"),
        type=int,
    )
    parser.add_argument(
        "--benchmarks-max-time",
        help="set the max waiting time in minutes for benchmarks tests",
        default=TEST_DEFAULTS.get("benchmarks_max_time"),
        type=int,
    )
    parser.add_argument(
        "--stackname-suffix",
        help="set a suffix in the integration tests stack names",
        default=TEST_DEFAULTS.get("stackname_suffix"),
    )
    parser.add_argument(
        "--keep-logs-on-cluster-failure",
        help="preserve CloudWatch logs when a cluster fails to be created",
        action="store_true",
        default=TEST_DEFAULTS.get("keep_logs_on_cluster_failure"),
    )
    parser.add_argument(
        "--keep-logs-on-test-failure",
        help="preserve CloudWatch logs when a test fails",
        action="store_true",
        default=TEST_DEFAULTS.get("keep_logs_on_test_failure"),
    )

    return parser


def _is_file(value):
    if not os.path.isfile(value):
        raise argparse.ArgumentTypeError("'{0}' is not a valid key".format(value))
    return value


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


def _get_pytest_args(args, regions, log_file, out_dir):
    pytest_args = ["-s", "-vv", "-l"]

    if args.benchmarks:
        pytest_args.append("--ignore=./tests")
        pytest_args.append("--rootdir=./benchmarks")
        pytest_args.append("--benchmarks-target-capacity={0}".format(args.benchmarks_target_capacity))
        pytest_args.append("--benchmarks-max-time={0}".format(args.benchmarks_max_time))
    else:
        pytest_args.append("--rootdir=./tests")
        pytest_args.append("--ignore=./benchmarks")

    # Show all tests durations
    pytest_args.append("--durations=0")
    # Run only tests with the given markers
    pytest_args.append("-m")
    pytest_args.append(" or ".join(list(_join_with_not(args.features))))
    pytest_args.append("--regions")
    pytest_args.extend(regions)
    pytest_args.append("--instances")
    pytest_args.extend(args.instances)
    pytest_args.append("--oss")
    pytest_args.extend(args.oss)
    pytest_args.append("--schedulers")
    pytest_args.extend(args.schedulers)
    pytest_args.extend(["--tests-log-file", "{0}/{1}".format(args.output_dir, log_file)])
    pytest_args.extend(["--output-dir", "{0}/{1}".format(args.output_dir, out_dir)])
    pytest_args.extend(["--key-name", args.key_name])
    pytest_args.extend(["--key-path", args.key_path])
    pytest_args.extend(["--stackname-suffix", args.stackname_suffix])

    if args.keep_logs_on_cluster_failure:
        pytest_args.append("--keep-logs-on-cluster-failure")
    if args.keep_logs_on_test_failure:
        pytest_args.append("--keep-logs-on-test-failure")

    if args.credential:
        pytest_args.append("--credential")
        pytest_args.extend(args.credential)

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

    _set_custom_packages_args(args, pytest_args)
    _set_custom_stack_args(args, pytest_args)
    return pytest_args


def _set_custom_packages_args(args, pytest_args):  # noqa: C901
    if args.custom_node_url:
        pytest_args.extend(["--custom-node-package", args.custom_node_url])

    if args.custom_cookbook_url:
        pytest_args.extend(["--custom-chef-cookbook", args.custom_cookbook_url])

    if args.createami_custom_cookbook_url:
        pytest_args.extend(["--createami-custom-chef-cookbook", args.createami_custom_cookbook_url])

    if args.custom_template_url:
        pytest_args.extend(["--template-url", args.custom_template_url])

    if args.custom_hit_template_url:
        pytest_args.extend(["--hit-template-url", args.custom_hit_template_url])

    if args.custom_awsbatchcli_url:
        pytest_args.extend(["--custom-awsbatchcli-package", args.custom_awsbatchcli_url])

    if args.custom_ami:
        pytest_args.extend(["--custom-ami", args.custom_ami])

    if args.pre_install:
        pytest_args.extend(["--pre-install", args.pre_install])

    if args.post_install:
        pytest_args.extend(["--post-install", args.post_install])


def _set_custom_stack_args(args, pytest_args):
    if args.vpc_stack:
        pytest_args.extend(["--vpc-stack", args.vpc_stack])

    if args.cluster:
        pytest_args.extend(["--cluster", args.cluster])

    if args.no_delete:
        pytest_args.append("--no-delete")


def _get_pytest_regionalized_args(region, args):
    return _get_pytest_args(
        args=args,
        regions=[region],
        log_file="{0}/{1}.log".format(LOGS_DIR, region),
        out_dir="{0}/{1}".format(OUT_DIR, region),
    )


def _get_pytest_non_regionalized_args(args):
    return _get_pytest_args(
        args=args, regions=args.regions, log_file="{0}/all_regions.log".format(LOGS_DIR), out_dir=OUT_DIR
    )


def _run_test_in_region(region, args):
    out_dir = "{base_dir}/{out_dir}/{region}".format(base_dir=args.output_dir, out_dir=OUT_DIR, region=region)
    os.makedirs(out_dir, exist_ok=True)

    # Redirect stdout to file
    if not args.show_output:
        sys.stdout = open("{0}/pytest.out".format(out_dir), "w")

    pytest_args_regionalized = _get_pytest_regionalized_args(region, args)
    with TemporaryDirectory() as temp_dir:
        pytest_args_regionalized.extend(["--basetemp", temp_dir])
        logger.info("Starting tests in region {0} with params {1}".format(region, pytest_args_regionalized))
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
    for region in args.regions:
        p = multiprocessing.Process(target=_run_test_in_region, args=[region, args])
        jobs.append(p)
        p.start()

    for job in jobs:
        job.join()


def _check_args(args):
    # If --cluster is set only one os, scheduler, instance type and region can be provided
    if args.cluster:
        if len(args.oss) > 1 or len(args.schedulers) > 1 or len(args.instances) > 1 or len(args.regions) > 1:
            logger.error(
                "when cluster option is specified, you can have a single value for oss, regions, instances "
                "and schedulers and you need to make sure they match the cluster specific ones"
            )
            exit(1)


def _run_sequential(args):
    # Redirect stdout to file
    if not args.show_output:
        sys.stdout = open("{0}/{1}/pytest.out".format(args.output_dir, OUT_DIR), "w")

    pytest_args_non_regionalized = _get_pytest_non_regionalized_args(args)
    logger.info("Starting tests with params {0}".format(pytest_args_non_regionalized))
    pytest.main(pytest_args_non_regionalized)


def main():
    """Entrypoint for tests executor."""
    if sys.version_info < (3, 7):
        logger.error("test_runner requires python >= 3.7")
        exit(1)

    args = _init_argparser().parse_args()
    _check_args(args)
    logger.info("Starting tests with parameters {0}".format(args))

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
