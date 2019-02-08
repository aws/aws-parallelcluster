import datetime
import logging
import multiprocessing
import os
import sys
import time

import argparse
import pytest

from reports_generator import generate_json_report, generate_junitxml_merged_report

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
    "oss": ["alinux", "centos6", "centos7", "ubuntu1404", "ubuntu1604"],
    "schedulers": ["sge", "slurm", "torque", "awsbatch"],
    "instances": ["c4.xlarge", "c5.xlarge"],
    "custom_node_url": None,
    "custom_cookbook_url": None,
    "custom_template_url": None,
    "dry_run": False,
    "output": [],
    "sequential": False,
    "generate_report": False,
}


def _init_argparser():
    parser = argparse.ArgumentParser(description="Run integration tests suite.")
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
        "--custom-node-url", help="URL to a custom node package.", default=TEST_DEFAULTS.get("custom_node_url")
    )
    parser.add_argument(
        "--custom-cookbook-url",
        help="URL to a custom cookbook package.",
        default=TEST_DEFAULTS.get("custom_cookbook_url"),
    )
    parser.add_argument(
        "--custom-template-url", help="URL to a custom cfn template.", default=TEST_DEFAULTS.get("custom_template_url")
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
        "--output",
        help="create tests report files. junitxml creates a junit-xml style report file. html creates an html "
        "style report file",
        nargs="+",
        choices=["html", "junitxml"],
        default=TEST_DEFAULTS.get("output"),
    )
    parser.add_argument(
        "--generate-report",
        help="generate final test report",
        action="store_true",
        default=TEST_DEFAULTS.get("generate_report"),
    )
    parser.add_argument("--key-name", help="Key to use for EC2 instances", required=True)
    parser.add_argument("--key-path", help="Path to the key to use for SSH connections", required=True, type=_is_file)

    return parser


def _is_file(value):
    if not os.path.isfile(value):
        raise argparse.ArgumentTypeError("'{0}' is not a valid key".format(value))
    return value


def _get_pytest_args(args, regions, log_file, out_dir):
    pytest_args = ["-s", "-vv", "-l", "--rootdir=./tests"]
    # Show all tests durations
    pytest_args.append("--durations=0")
    # Run only tests with the given markers
    pytest_args.append("-m")
    pytest_args.append(" or ".join(args.features))
    pytest_args.append("--regions")
    pytest_args.extend(regions)
    pytest_args.append("--instances")
    pytest_args.extend(args.instances)
    pytest_args.append("--oss")
    pytest_args.extend(args.oss)
    pytest_args.append("--schedulers")
    pytest_args.extend(args.schedulers)
    pytest_args.extend(["--tests-log-file", log_file])
    pytest_args.extend(["--output-dir", out_dir])
    pytest_args.extend(["--key-name", args.key_name])
    pytest_args.extend(["--key-path", args.key_path])

    if args.custom_node_url:
        pytest_args.extend(["--custom-node-url", args.custom_node_url])

    if args.custom_cookbook_url:
        pytest_args.extend(["--custom-cookbook-url", args.custom_cookbook_url])

    if args.custom_template_url:
        pytest_args.extend(["--custom-template-url", args.custom_template_url])

    if args.retry_on_failures:
        # Rerun tests on failures for one more time after 60 seconds delay
        pytest_args.extend(["--reruns", "1", "--reruns-delay", "60"])

    if args.parallelism:
        pytest_args.extend(["-n", args.parallelism])

    if args.dry_run:
        pytest_args.append("--collect-only")

    if "junitxml" in args.output or args.generate_report:
        pytest_args.append("--junit-xml={0}/results.xml".format(out_dir))

    if "html" in args.output:
        pytest_args.append("--html={0}/results.html".format(out_dir))

    return pytest_args


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
    out_dir = "{0}/{1}".format(OUT_DIR, region)
    os.makedirs(out_dir, exist_ok=True)

    # Redirect stdout to file
    if not args.show_output:
        sys.stdout = open("{0}/pytest.out".format(out_dir), "w")

    pytest_args_regionalized = _get_pytest_regionalized_args(region, args)
    logger.info("Starting tests in region {0} with params {1}".format(region, pytest_args_regionalized))
    pytest.main(pytest_args_regionalized)


def _make_logging_dirs():
    os.makedirs(LOGS_DIR, exist_ok=True)
    logger.info("Configured logs dir: {0}".format(LOGS_DIR))
    os.makedirs(OUT_DIR, exist_ok=True)
    logger.info("Configured tests output dir: {0}".format(OUT_DIR))


def _run_parallel(args):
    jobs = []
    for region in args.regions:
        p = multiprocessing.Process(target=_run_test_in_region, args=[region, args])
        jobs.append(p)
        p.start()

    for job in jobs:
        job.join()


def _run_sequential(args):
    # Redirect stdout to file
    if not args.show_output:
        sys.stdout = open("{0}/pytest.out".format(OUT_DIR), "w")

    pytest_args_non_regionalized = _get_pytest_non_regionalized_args(args)
    logger.info("Starting tests with params {0}".format(pytest_args_non_regionalized))
    pytest.main(pytest_args_non_regionalized)


def main():
    """Entrypoint for tests executor."""
    args = _init_argparser().parse_args()
    logger.info("Starting tests with parameters {0}".format(args))

    _make_logging_dirs()

    if args.sequential:
        _run_sequential(args)
    else:
        _run_parallel(args)

    logger.info("All tests completed!")

    if "junitxml" in args.output:
        generate_junitxml_merged_report(OUT_DIR)

    if args.generate_report:
        logger.info("Generating tests report")
        generate_json_report(OUT_DIR)


if __name__ == "__main__":
    main()
