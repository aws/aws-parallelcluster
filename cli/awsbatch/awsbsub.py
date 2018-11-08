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

import argparse
import datetime
import os
import re
import shutil
import sys
import time

from awsbatch.common import AWSBatchCliConfig, Boto3ClientFactory, config_logger
from awsbatch.utils import fail, shell_join, get_job_definition_name_by_arn


def _get_parser():
    """
    Parse input parameters and return the ArgumentParser object

    If the command is executed without the --cluster parameter, the command will use the default cluster_name
    specified in the [main] section of the user's awsbatch-cli.cfg configuration file and will search
    for the [cluster cluster-name] section, if the section doesn't exist, it will ask to CloudFormation
    the required information.

    If the --cluster parameter is set, the command will search for the [cluster cluster-name] section
    in the user's awsbatch-cli.cfg configuration file or, if the file doesn't exist, it will ask to CloudFormation
    the required information.

    :return: the ArgumentParser object
    """
    parser = argparse.ArgumentParser(description='Submits jobs to the cluster\'s Job Queue.')
    parser.add_argument('-jn', '--job-name', help='The name of the job. The first character must be alphanumeric, '
                                                  'and up to 128 letters (uppercase and lowercase), '
                                                  'numbers, hyphens, and underscores are allowed')
    parser.add_argument('-c', '--cluster', help='Cluster to use')
    parser.add_argument('-cf', '--command-file', help='Identifies that the command is a file to be transferred '
                                                      'to the compute instances', action='store_true')
    parser.add_argument('-p', '--vcpus', help='The number of vCPUs to reserve for the container. '
                                              'When used in conjunction with --nodes it identifies the number '
                                              'of vCPUs per node. Default is 1', type=int, default=1)
    parser.add_argument('-m', '--memory', help='The hard limit (in MiB) of memory to present to the job. '
                                               'If your job attempts to exceed the memory specified here, '
                                               'the job is killed. Default is 128', type=int, default=128)
    parser.add_argument('-r', '--retry-attempts', help='The number of times to move a job to the RUNNABLE status. '
                                                       'You may specify between 1 and 10 attempts. '
                                                       'If the value of attempts is greater than one, '
                                                       'the job is retried if it fails '
                                                       'until it has moved to RUNNABLE that many times. '
                                                       'Default value is 1', type=int, default=1)
    parser.add_argument('-t', '--timeout', help='The time duration in seconds (measured from the job attempt\'s '
                                                'startedAt timestamp) after which AWS Batch terminates your jobs '
                                                'if they have not finished. It must be at least 60 seconds', type=int)
    # array parameters
    parser.add_argument('-a', '--array-size', help='The size of the array. It can be between 2 and 10,000. '
                                                   'If you specify array properties for a job, '
                                                   'it becomes an array job', type=int)
    parser.add_argument('-d', '--depends-on', help='A semicolon separated list of dependencies for the job. '
                                                   'A job can depend upon a maximum of 20 jobs. '
                                                   'You can specify a SEQUENTIAL type dependency without specifying '
                                                   'a job ID for array jobs so that each child array job completes '
                                                   'sequentially, starting at index 0. '
                                                   'You can also specify an N_TO_N type dependency with a job ID '
                                                   'for array jobs so that each index child of this job must wait '
                                                   'for the corresponding index child of each dependency '
                                                   'to complete before it can begin. '
                                                   'Syntax: jobId=<string>,type=<string>;...')
    parser.add_argument('-aws', '--awscli', help=argparse.SUPPRESS, action='store_true')
    parser.add_argument('-ll', '--log-level', help=argparse.SUPPRESS, default='ERROR')
    parser.add_argument('command', help='The command to submit (it must be available on the compute instances) '
                                        'or the file name to be transferred (see --command-file option).',
                        default=sys.stdin, nargs='?')
    parser.add_argument('arguments', help='Arguments for the command or the command-file (optional).', nargs='*')
    return parser


def _validate_parameters(args):
    """
    Validate input parameters
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

    if args.depends_on and not re.match('(jobId|type)=[^\s,]+([\s,]?(jobId|type)=[^\s]+)*', args.depends_on):
        fail("Parameters validation error: please double check --depends-on parameter syntax.")


def _prepend_s3_folder(file_name):
    return "batch/" + file_name


def _upload_to_s3(boto3_factory, s3_bucket, file_path, key_name, timeout):
    """
    Upload a file to an s3 bucket
    :param boto3_factory: initialized Boto3ClientFactory object
    :param s3_bucket: S3 bucket to use
    :param file_path: file to upload
    :param key_name: S3 key to create
    :param timeout: S3 expiration time in seconds
    """
    default_expiration = 30  # minutes
    expires = datetime.datetime.now() + datetime.timedelta(minutes=default_expiration)
    if timeout:
        expires += datetime.timedelta(seconds=timeout)

    s3_client = boto3_factory.get_client('s3')
    s3_client.upload_file(file_path, s3_bucket, _prepend_s3_folder(key_name), ExtraArgs={'Expires': expires})


def _upload_and_get_command(boto3_factory, args, job_name, region, s3_bucket, log):
    """
    Get command by parsing args and config.
    The function will also perform an s3 upload, if needed
    :param boto3_factory: initialized Boto3ClientFactory object
    :param args: input arguments
    :param job_name: job name
    :param region: region
    :param s3_bucket: S3 bucket to use
    :param log: log
    :return: command to submit
    """
    if args.command_file or not sys.stdin.isatty():
        # define job script name
        job_script = 'job-{0}-{1}.sh'.format(job_name, int(time.time() * 1000))
        log.info("Using command-file option or stdin. Job script name: %s" % job_script)

        # upload job script
        if args.command_file:
            # existing script file
            try:
                _upload_to_s3(boto3_factory, s3_bucket, args.command, job_script, args.timeout)
            except Exception as e:
                fail("Error creating job script. Failed with exception: %s" % e)
        else:
            try:
                # copy stdin to temporary file
                with os.fdopen(sys.stdin.fileno(), 'rb') as src:
                    with open(job_script, 'wb') as dst:
                        shutil.copyfileobj(src, dst)

                _upload_to_s3(boto3_factory, s3_bucket, job_script, job_script, args.timeout)
            except (OSError, Exception) as e:
                fail("Error creating job script. Failed with exception: %s" % e)
            finally:
                # remove temporary file
                if os.path.exists(job_script):
                    os.remove(job_script)

        # define command to execute
        command_args = shell_join(args.arguments)
        # download awscli, if required. TODO: remove
        s3_command = "curl -O https://bootstrap.pypa.io/get-pip.py >/dev/null 2>&1; " \
                     "python get-pip.py --user >/dev/null 2>&1; " \
                     "export PATH=~/.local/bin:$PATH >/dev/null 2>&1; " \
                     "pip install awscli --upgrade --user >/dev/null 2>&1; " if args.awscli else ""
        s3_command += "aws s3 --region {REGION} cp s3://{BUCKET}/{SCRIPT} /tmp/{SCRIPT}; " \
                      "bash /tmp/{SCRIPT} {ARGS}".format(REGION=region, BUCKET=s3_bucket,
                                                         SCRIPT=_prepend_s3_folder(job_script), ARGS=command_args)
        command = ['/bin/bash', '-c', s3_command]
    elif type(args.command) == str:
        log.info("Using command parameter")
        command = [args.command] + args.arguments
    else:
        fail("Unexpected error. Command cannot be empty.")
    log.info("Command: %s" % shell_join(command))
    return command


def _get_depends_on(args):
    """
    Get depends_on list by parsing input parameters
    :param args: input parameters
    :return: depends_on list
    """
    depends_on = []
    if args.depends_on:
        dependencies = {}
        try:
            for dependency in args.depends_on.split(','):
                dep = dependency.split('=')
                dependencies[dep[0]] = dep[1]
        except IndexError:
            fail("Parameters validation error: please double check --depends-on parameter syntax.")
        depends_on.append(dependencies)
    return depends_on


class AWSBsubCommand(object):
    """
    awsbsub command
    """
    def __init__(self, log, boto3_factory):
        """
        :param log: log
        :param boto3_factory: an initialized Boto3ClientFactory object
        """
        self.log = log
        self.batch_client = boto3_factory.get_client('batch')

    def run(self, job_definition, job_name, job_queue, command, nodes=None, vcpus=None, memory=None,
            array_size=None, retry_attempts=1, timeout=None, dependencies=None, master_ip=None):
        """
        submit the job
        """
        try:
            # array properties
            array_properties = {}
            if array_size:
                array_properties.update(size=array_size)

            retry_strategy = {'attempts': retry_attempts}

            depends_on = dependencies if dependencies else []

            # populate container overrides
            container_overrides = {'command': command}
            if vcpus:
                container_overrides.update(vcpus=vcpus)
            if memory:
                container_overrides.update(memory=memory)
            if master_ip:
                environment = [{'name': 'MASTER_IP', 'value': master_ip}]
                container_overrides.update(environment=environment)

            # common submission arguments
            submission_args = {
                'jobName': job_name,
                'jobQueue': job_queue,
                'dependsOn': depends_on,
                'retryStrategy': retry_strategy
            }

            if nodes:
                # Multi Node parallel submission
                job_definition_version = self.__get_mnp_job_definition_version(base_job_definition_arn=job_definition,
                                                                               nodes=nodes)
                submission_args.update({'jobDefinition': job_definition_version})

                target_nodes = '0:%d' % (nodes - 1)
                # populate node overrides
                node_overrides = {
                    'nodePropertyOverrides': [{
                       'targetNodes': target_nodes,
                       'containerOverrides': container_overrides
                    }]
                }
                submission_args.update({'nodeOverrides': node_overrides})
                if timeout:
                    submission_args.update({'timeout': {'attemptDurationSeconds': timeout}})
            else:
                # Standard submission
                submission_args.update({'jobDefinition': job_definition})
                submission_args.update({'containerOverrides': container_overrides})
                submission_args.update({'arrayProperties': array_properties})
                if timeout:
                    submission_args.update({'timeout': {'attemptDurationSeconds': timeout}})

            self.log.debug("Job submission args: %s" % submission_args)
            response = self.batch_client.submit_job(**submission_args)
            print("Job %s (%s) has been submitted." % (response['jobId'], response['jobName']))
        except Exception as e:
            fail("Error submitting job to AWS Batch. Failed with exception: %s" % e)

    def __get_mnp_job_definition_version(self, base_job_definition_arn, nodes):
        """
        Get (and create if required) job definition version to use for the submission
        :return: job definition arn
        """
        # Check if there is already a job definition for the given number of nodes
        job_definition_found = self.__search_for_job_definition(base_job_definition_arn, nodes)
        if job_definition_found:
            job_definition_arn = job_definition_found['jobDefinitionArn']
            self.log.info("Found existing Job definition (%s) with (%i) nodes" % (job_definition_arn, nodes))
        else:
            self.log.info("Creating new Job definition with (%i) nodes" % nodes)
            # create a new job definition revision
            job_definition_arn = self.__register_new_job_definition(base_job_definition_arn, nodes)

        self.log.info("Job definition to use is (%s)" % job_definition_arn)
        return job_definition_arn

    def __search_for_job_definition(self, base_job_definition, nodes):
        """
        Search for existing job definition with the same name of the base_job_definition and the same number of nodes
        :param base_job_definition: job definition arn
        :param nodes: number of nodes
        :return: the found jobDefinition object or None
        """
        job_definition_found = None
        base_job_definition_name = get_job_definition_name_by_arn(base_job_definition)
        try:
            next_token = ''
            while next_token is not None:
                response = self.batch_client.describe_job_definitions(jobDefinitionName=base_job_definition_name,
                                                                      status='ACTIVE', nextToken=next_token)
                for job_definition in response['jobDefinitions']:
                    if job_definition['nodeProperties']['numNodes'] == nodes:
                        job_definition_found = job_definition
                        break
                next_token = response.get('nextToken')
        except Exception as e:
            fail("Error listing job definition. Failed with exception: %s" % e)

        return job_definition_found

    def __register_new_job_definition(self, base_job_definition_arn, nodes):
        """
        Register a new job definition by using the base_job_definition_arn as starting point for the nodeRangeProperties
        :param base_job_definition_arn: job definition arn to use as starting point
        :param nodes: nuber of nodes to set in the job definition
        :return: the ARN of the created job definition
        """
        try:
            # get base job definition and reuse its nodeRangeProperties
            response = self.batch_client.describe_job_definitions(jobDefinitions=[base_job_definition_arn],
                                                                  status='ACTIVE')
            job_definition = response['jobDefinitions'][0]

            # create new job definition
            response = self.batch_client.register_job_definition(
                jobDefinitionName=job_definition['jobDefinitionName'],
                type='multinode',
                nodeProperties={
                    'numNodes': nodes,
                    'mainNode': 0,
                    'nodeRangeProperties': [
                        {
                            'targetNodes': '0:%d' % (nodes - 1),
                            'container': job_definition['nodeProperties']['nodeRangeProperties'][0]['container']
                        }
                    ]
                }
            )
            job_definition_arn = response['jobDefinitionArn']
        except Exception as e:
            fail("Error listing job definition. Failed with exception: %s" % e)

        return job_definition_arn


def main():
    try:
        # parse input parameters and config file
        args = _get_parser().parse_args()
        _validate_parameters(args)
        log = config_logger(args.log_level)
        log.info("Input parameters: %s" % args)
        config = AWSBatchCliConfig(log=log, cluster=args.cluster)
        boto3_factory = Boto3ClientFactory(region=config.region, proxy=config.proxy,
                                           aws_access_key_id=config.aws_access_key_id,
                                           aws_secret_access_key=config.aws_secret_access_key)

        # define job name
        if args.job_name:
            job_name = args.job_name
        else:
            # set a default job name if not specified
            if not sys.stdin.isatty():
                # stdin
                job_name = 'STDIN'
            else:
                # normalize name
                job_name = re.sub('\W+', '_', os.path.basename(args.command))
            log.info("Job name not specified, setting it to (%s)" % job_name)

        # upload script, if needed, and get related command
        command = _upload_and_get_command(boto3_factory, args, job_name, config.region, config.s3_bucket, log)
        # parse and validate depends_on parameter
        depends_on = _get_depends_on(args)

        job_definition = config.job_definition

        AWSBsubCommand(log, boto3_factory).run(job_definition=job_definition, job_name=job_name,
                                               job_queue=config.job_queue, command=command,
                                               vcpus=args.vcpus, memory=args.memory,
                                               array_size=args.array_size, dependencies=depends_on,
                                               retry_attempts=args.retry_attempts, timeout=args.timeout,
                                               master_ip=config.master_ip)
    except KeyboardInterrupt:
        print("Exiting...")
        sys.exit(0)
    except Exception as e:
        fail("Unexpected error. Command failed with exception: %s" % e)


if __name__ == '__main__':
    main()
