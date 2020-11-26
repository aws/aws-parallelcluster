#!/usr/bin/env python2.6

# Copyright 2018 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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
from __future__ import print_function

import os
import pipes
import re
import shutil
import sys
import tempfile
import time

import argparse

from awsbatch.common import AWSBatchCliConfig, Boto3ClientFactory, config_logger
from awsbatch.utils import S3Uploader, fail, shell_join


def _get_parser():
    """
    Parse input parameters and return the ArgumentParser object.

    If the command is executed without the --cluster parameter, the command will use the default cluster_name
    specified in the [main] section of the user's awsbatch-cli.cfg configuration file and will search
    for the [cluster cluster-name] section, if the section doesn't exist, it will ask to CloudFormation
    the required information.

    If the --cluster parameter is set, the command will search for the [cluster cluster-name] section
    in the user's awsbatch-cli.cfg configuration file or, if the file doesn't exist, it will ask to CloudFormation
    the required information.

    :return: the ArgumentParser object
    """
    parser = argparse.ArgumentParser(description="Submits jobs to the cluster's Job Queue.")
    parser.add_argument(
        "-jn",
        "--job-name",
        help="The name of the job. The first character must be alphanumeric, and up to 128 letters "
        "(uppercase and lowercase), numbers, hyphens, and underscores are allowed",
    )
    parser.add_argument("-c", "--cluster", help="Cluster to use")
    parser.add_argument(
        "-cf",
        "--command-file",
        help="Identifies that the command is a file to be transferred to the compute instances",
        action="store_true",
    )
    parser.add_argument(
        "-w",
        "--working-dir",
        help="The folder to use as job working directory. "
        "If not specified the job will be executed in the job-<AWS_BATCH_JOB_ID> subfolder of the user's home",
    )
    parser.add_argument(
        "-pw",
        "--parent-working-dir",
        help="Parent folder for the job working directory. If not specified it is the user's home. "
        "A subfolder named job-<AWS_BATCH_JOB_ID> will be created in it. Alternative to the --working-dir parameter",
    )
    parser.add_argument(
        "-if",
        "--input-file",
        help="File to be transferred to the compute instances, in the job working directory. "
        "It can be expressed multiple times",
        action="append",
    )
    parser.add_argument(
        "-p",
        "--vcpus",
        help="The number of vCPUs to reserve for the container. When used in conjunction with --nodes it identifies "
        "the number of vCPUs per node. Default is 1",
        type=int,
        default=1,
    )
    parser.add_argument(
        "-m",
        "--memory",
        help="The hard limit (in MiB) of memory to present to the job. If your job attempts to exceed the memory "
        "specified here, the job is killed. Default is 128",
        type=int,
        default=128,
    )
    parser.add_argument(
        "-e",
        "--env",
        help="Comma separated list of environment variable names to export to the Job environment. "
        "Use 'all' to export all the environment variables, except the ones listed to the --env-blacklist parameter "
        "and variables starting with PCLUSTER_* and AWS_* prefix.",
    )
    parser.add_argument(
        "-eb",
        "--env-blacklist",
        help="Comma separated list of environment variable names to NOT export to the Job environment. "
        "Default: HOME, PWD, USER, PATH, LD_LIBRARY_PATH, TERM, TERMCAP.",
    )
    parser.add_argument(
        "-r",
        "--retry-attempts",
        help="The number of times to move a job to the RUNNABLE status. You may specify between 1 and 10 attempts. "
        "If the value of attempts is greater than one, the job is retried if it fails until it has moved to RUNNABLE "
        "that many times. Default value is 1",
        type=int,
        default=1,
    )
    parser.add_argument(
        "-t",
        "--timeout",
        help="The time duration in seconds (measured from the job attempt's startedAt timestamp) after which AWS "
        "Batch terminates your jobs if they have not finished. It must be at least 60 seconds",
        type=int,
    )
    # MNP parameter
    parser.add_argument(
        "-n",
        "--nodes",
        help="The number of nodes to reserve for the job. It enables Multi-Node Parallel submission",
        type=int,
    )
    # array parameters
    parser.add_argument(
        "-a",
        "--array-size",
        help="The size of the array. It can be between 2 and 10,000. If you specify array properties for a job, "
        "it becomes an array job",
        type=int,
    )
    parser.add_argument(
        "-d",
        "--depends-on",
        help="A semicolon separated list of dependencies for the job. A job can depend upon a maximum of 20 jobs. "
        "You can specify a SEQUENTIAL type dependency without specifying a job ID for array jobs so that each child "
        "array job completes sequentially, starting at index 0. You can also specify an N_TO_N type dependency "
        "with a job ID for array jobs so that each index child of this job must wait for the corresponding index "
        "child of each dependency to complete before it can begin. Syntax: jobId=<string>,type=<string>;...",
    )
    parser.add_argument("-aws", "--awscli", help=argparse.SUPPRESS, action="store_true")
    parser.add_argument("-ll", "--log-level", help=argparse.SUPPRESS, default="ERROR")
    parser.add_argument(
        "command",
        help="The command to submit (it must be available on the compute instances) "
        "or the file name to be transferred (see --command-file option).",
        default=sys.stdin,
        nargs="?",
    )
    parser.add_argument("arguments", help="Arguments for the command or the command-file (optional).", nargs="*")
    return parser


def _validate_parameters(args):
    """
    Validate input parameters.

    :param args: args variable
    """
    if args.command_file:
        if not type(args.command) == str:
            fail("The command parameter is required with --command-file option")
        elif not os.path.isfile(args.command):
            fail("The command parameter (%s) must be an existing file" % args.command)
    elif not sys.stdin.isatty():
        # stdin
        if args.arguments or type(args.command) == str:
            fail("Error: command and arguments cannot be specified when submitting by stdin.")
    elif not type(args.command) == str:
        fail("Parameters validation error: command parameter is required.")

    if args.depends_on and not re.match(r"^(jobId|type)=[^\s,]+([\s,]?(jobId|type)=[^\s]+)*$", args.depends_on):
        fail("Parameters validation error: please double check --depends-on parameter syntax.")

    if args.env_blacklist and (not args.env or args.env != "all"):
        fail('--env-blacklist parameter can be used only associated with --env "all"')

    if args.working_dir and args.parent_working_dir:
        fail("--parent-working-dir and --working-dir parameters cannot be used at the same time")


def _generate_unique_job_key(job_name):
    """
    Generate an unique job key to use as identifier.

    :param job_name: job name
    :return: "job-<job_name>-<timestamp>"
    """
    return "job-{0}-{1}".format(job_name, int(time.time() * 1000))


def _upload_and_get_command(boto3_factory, args, job_s3_folder, job_name, config, log):
    """
    Get command by parsing args and config.

    The function will also perform an s3 upload, if needed.
    :param boto3_factory: initialized Boto3ClientFactory object
    :param args: input arguments
    :param job_s3_folder: S3 folder for the job files
    :param job_name: job name
    :param config: config object
    :param log: log
    :return: command to submit
    """
    # create S3 folder for the job
    s3_uploader = S3Uploader(boto3_factory, config.s3_bucket, job_s3_folder)

    # upload input files, if there
    if args.input_file:
        for file in args.input_file:
            s3_uploader.put_file(file, os.path.basename(file))

    # upload command, if needed
    if args.command_file or not sys.stdin.isatty() or args.env:
        # define job script name
        job_script = job_name + ".sh"
        log.info("Using command-file option or stdin. Job script name: %s" % job_script)

        env_file = None
        if args.env:
            env_file = job_name + ".env.sh"
            # get environment variables and upload file used to extend the submission environment
            env_blacklist = args.env_blacklist if args.env_blacklist else config.env_blacklist
            _get_env_and_upload(s3_uploader, args.env, env_blacklist, env_file, log)

        # upload job script
        if args.command_file:
            # existing script file
            try:
                s3_uploader.put_file(args.command, job_script)
            except Exception as e:
                fail("Error creating job script. Failed with exception: %s" % e)
        elif not sys.stdin.isatty():
            # stdin
            _get_stdin_and_upload(s3_uploader, job_script)

        # define command to execute
        bash_command = _compose_bash_command(args, config.s3_bucket, config.region, job_s3_folder, job_script, env_file)
        command = ["/bin/bash", "-c", bash_command]
    elif type(args.command) == str:
        log.info("Using command parameter")
        command = [args.command] + args.arguments
    else:
        fail("Unexpected error. Command cannot be empty.")
    log.info("Command: %s" % shell_join(command))
    return command


def _get_stdin_and_upload(s3_uploader, job_script):
    """
    Create file from STDIN and upload to S3.

    :param s3_uploader: S3Uploader object
    :param job_script: job script name
    """
    try:
        # copy stdin to temporary file and upload
        with os.fdopen(sys.stdin.fileno(), "rb") as src:
            with tempfile.NamedTemporaryFile() as dst:
                shutil.copyfileobj(src, dst)
                dst.flush()
                s3_uploader.put_file(dst.name, job_script)
    except Exception as e:
        fail("Error creating job script. Failed with exception: %s" % e)


def _get_env_and_upload(s3_uploader, env, env_blacklist, env_file, log):
    """
    Get environment variables, create a file containing the list of the exported env variables and upload to S3.

    :param s3_uploader: S3Uploader object
    :param env: comma separated list of environment variables
    :param env_blacklist: comma separated list of blacklisted environment variables
    :param env_file: environment file name
    :param log: log
    """
    key_value_list = _get_env_key_value_list(env, log, env_blacklist)
    try:
        # copy env to temporary file
        with tempfile.NamedTemporaryFile() as dst:
            dst.write("\n".join(key_value_list) + "\n")
            dst.flush()
            s3_uploader.put_file(dst.name, env_file)
    except Exception as e:
        fail("Error creating environment file. Failed with exception: %s" % e)


def _compose_bash_command(args, s3_bucket, region, job_s3_folder, job_script, env_file):
    """
    Define bash command to execute.

    :param args: input arguments
    :param s3_bucket: S3 bucket
    :param region: AWS region
    :param job_s3_folder: S3 job folder
    :param job_script: job script file
    :param env_file: environment file
    :return: composed bash command
    """
    command_args = shell_join(args.arguments)
    # download awscli, if required.
    bash_command = []
    if args.awscli:
        bash_command.append(
            "curl -O https://bootstrap.pypa.io/get-pip.py >/dev/null 2>&1 && "
            "python get-pip.py --user >/dev/null 2>&1 && "
            "export PATH=~/.local/bin:$PATH >/dev/null 2>&1 && "
            "pip install awscli --upgrade --user >/dev/null 2>&1"
        )

    # set working directory
    if args.working_dir:
        # create and move to the working dir specified by the user
        bash_command.append('mkdir -p "{JOB_WD}" && cd "{JOB_WD}"'.format(JOB_WD=args.working_dir))
    else:
        if args.parent_working_dir:
            # create and move to the parent working dir specified by the user
            bash_command.append(
                'mkdir -p "{JOB_PARENT_WD}" && cd "{JOB_PARENT_WD}"'.format(JOB_PARENT_WD=args.parent_working_dir)
            )

        # create subfolder named job-<$AWS_BATCH_JOB_ID>
        bash_command.append("mkdir -p job-${AWS_BATCH_JOB_ID} && cd job-${AWS_BATCH_JOB_ID}")

    # download all job files to the job folder
    bash_command.append(
        "aws s3 --region {REGION} sync s3://{BUCKET}/{S3_FOLDER} . >/dev/null".format(
            REGION=region, BUCKET=s3_bucket, S3_FOLDER=job_s3_folder
        )
    )
    if env_file:  # source the environment file
        bash_command.append("source {ENV_FILE}".format(ENV_FILE=env_file))

    # execute the job script + arguments
    bash_command.append("chmod +x {SCRIPT} && ./{SCRIPT} {ARGS}".format(SCRIPT=job_script, ARGS=command_args))
    return " && ".join(bash_command)


def _get_env_key_value_list(env_vars, log, env_blacklist_vars=None):
    """
    Get key-value environment variables list by excluding blacklisted and internal variables.

    :param env_vars: list of variables to get from the environment and add to the list
    or use 'all' to add all the list except the blacklisted ones
    :param env_blacklist_vars: list of variable names to exclude when 'all' is passed as env_vars parameter
    """
    environment_blacklist = ["HOME", "LD_LIBRARY_PATH", "PATH", "PWD", "TERM", "TERMCAP", "USER", "VCPUS"]

    blacklisted_vars = (
        [var.strip() for var in env_blacklist_vars.split(",")] if env_blacklist_vars else environment_blacklist
    )

    key_value_list = []
    for var in env_vars.split(","):
        var_name = var.strip()

        if var_name == "all":
            # export all the env variables except the blacklisted and the internal ones
            log.info("Environment blacklist is (%s)", blacklisted_vars)
            for env_var in os.environ:
                if env_var not in blacklisted_vars:
                    _add_env_var_to_list(key_value_list, env_var, log)
        elif var_name in os.environ:
            # export variables explicitly specified by the user
            _add_env_var_to_list(key_value_list, var_name, log)
        else:
            log.warn("Environment variable (%s) does not exist." % var_name)

    return key_value_list


def _add_env_var_to_list(key_value_list, var_name, log):
    """
    Get key-value environment variable and add to the given list.

    Skip internal variables and functions.

    :param key_value_list: list to update
    :param var_name: var name
    :param log: log file
    """
    var = var_name.upper()
    # exclude reserved variables and functions
    if (
        not var.startswith("PCLUSTER_")  # reserved AWS ParallelCluster variables
        and not var.startswith("AWS_")  # reserved AWS variables
        and not var.startswith("LESS_TERMCAP_")  # terminal variables
        and "()" not in var  # functions
    ):
        var_value = os.environ[var_name]
        key_value_list.append("export %s=%s;" % (var_name, pipes.quote(var_value)))
        log.info("Exporting environment variable: (%s=%s)." % (var_name, var_value))
    else:
        log.warn("Excluded variable: (%s)." % var_name)


def _get_depends_on(args):
    """
    Get depends_on list by parsing input parameters.

    :param args: input parameters
    :return: depends_on list
    """
    depends_on = []
    if args.depends_on:
        dependencies = {}
        try:
            for dependency in args.depends_on.split(","):
                dep = dependency.split("=")
                dependencies[dep[0]] = dep[1]
        except IndexError:
            fail("Parameters validation error: please double check --depends-on parameter syntax.")
        depends_on.append(dependencies)
    return depends_on


class AWSBsubCommand(object):
    """awsbsub command."""

    def __init__(self, log, boto3_factory):
        """
        Initialize the object.

        :param log: log
        :param boto3_factory: an initialized Boto3ClientFactory object
        """
        self.log = log
        self.batch_client = boto3_factory.get_client("batch")

    def run(  # noqa: C901 FIXME
        self,
        job_definition,
        job_name,
        job_queue,
        command,
        nodes=None,
        vcpus=None,
        memory=None,
        array_size=None,
        retry_attempts=1,
        timeout=None,
        dependencies=None,
        env=None,
    ):
        """Submit the job."""
        try:
            # array properties
            array_properties = {}
            if array_size:
                array_properties.update(size=array_size)

            retry_strategy = {"attempts": retry_attempts}

            depends_on = dependencies if dependencies else []

            # populate container overrides
            container_overrides = {"command": command}
            if vcpus:
                container_overrides.update(vcpus=vcpus)
            if memory:
                container_overrides.update(memory=memory)
            # populate environment variables
            environment = []
            for env_var in env:
                environment.append({"name": env_var[0], "value": env_var[1]})
            container_overrides.update(environment=environment)

            # common submission arguments
            submission_args = {
                "jobName": job_name,
                "jobQueue": job_queue,
                "dependsOn": depends_on,
                "retryStrategy": retry_strategy,
            }

            if nodes:
                submission_args.update({"jobDefinition": job_definition})

                target_nodes = "0:"
                # populate node overrides
                node_overrides = {
                    "numNodes": nodes,
                    "nodePropertyOverrides": [{"targetNodes": target_nodes, "containerOverrides": container_overrides}],
                }
                submission_args.update({"nodeOverrides": node_overrides})
                if timeout:
                    submission_args.update({"timeout": {"attemptDurationSeconds": timeout}})
            else:
                # Standard submission
                submission_args.update({"jobDefinition": job_definition})
                submission_args.update({"containerOverrides": container_overrides})
                submission_args.update({"arrayProperties": array_properties})
                if timeout:
                    submission_args.update({"timeout": {"attemptDurationSeconds": timeout}})

            self.log.debug("Job submission args: %s" % submission_args)
            response = self.batch_client.submit_job(**submission_args)
            print("Job %s (%s) has been submitted." % (response["jobId"], response["jobName"]))
        except Exception as e:
            fail("Error submitting job to AWS Batch. Failed with exception: %s" % e)


def main():
    """Command entrypoint."""
    try:
        # parse input parameters and config file
        args = _get_parser().parse_args()
        _validate_parameters(args)
        log = config_logger(args.log_level)
        log.info("Input parameters: %s" % args)
        config = AWSBatchCliConfig(log=log, cluster=args.cluster)
        boto3_factory = Boto3ClientFactory(
            region=config.region,
            proxy=config.proxy,
            aws_access_key_id=config.aws_access_key_id,
            aws_secret_access_key=config.aws_secret_access_key,
        )

        # define job name
        if args.job_name:
            job_name = args.job_name
        else:
            # set a default job name if not specified
            if not sys.stdin.isatty():
                # stdin
                job_name = "STDIN"
            else:
                # normalize name
                job_name = re.sub(r"\W+", "_", os.path.basename(args.command))
            log.info("Job name not specified, setting it to (%s)" % job_name)

        # generate an internal unique job-id
        job_key = _generate_unique_job_key(job_name)
        job_s3_folder = "{prefix}/batch/{job_key}/".format(prefix=config.artifact_directory, job_key=job_key)
        # upload script, if needed, and get related command
        command = _upload_and_get_command(boto3_factory, args, job_s3_folder, job_name, config, log)
        # parse and validate depends_on parameter
        depends_on = _get_depends_on(args)

        # select submission (standard vs MNP)
        if args.nodes and args.nodes > 1:
            if not hasattr(config, "job_definition_mnp"):
                fail("Current cluster does not support MNP jobs submission")
            job_definition = config.job_definition_mnp
            nodes = args.nodes
        else:
            job_definition = config.job_definition
            nodes = None

        AWSBsubCommand(log, boto3_factory).run(
            job_definition=job_definition,
            job_name=job_name,
            job_queue=config.job_queue,
            command=command,
            nodes=nodes,
            vcpus=args.vcpus,
            memory=args.memory,
            array_size=args.array_size,
            dependencies=depends_on,
            retry_attempts=args.retry_attempts,
            timeout=args.timeout,
            env=[
                ("MASTER_IP", config.head_node_ip),  # TODO remove
                ("PCLUSTER_JOB_S3_URL", "s3://{0}/{1}".format(config.s3_bucket, job_s3_folder)),
            ],
        )
    except KeyboardInterrupt:
        print("Exiting...")
        sys.exit(0)
    except Exception as e:
        fail("Unexpected error. Command failed with exception: %s" % e)


if __name__ == "__main__":
    main()
