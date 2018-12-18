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
import random
import shlex
import string
import subprocess as sub
import sys
import tarfile
import time
from builtins import str
from shutil import rmtree
from tempfile import mkdtemp, mkstemp

import boto3
import pkg_resources
from botocore.exceptions import ClientError

from . import cfnconfig, utils

if sys.version_info[0] >= 3:
    from urllib.request import urlretrieve
else:
    from urllib import urlretrieve  # pylint: disable=no-name-in-module

LOGGER = logging.getLogger("pcluster.pcluster")


def create_bucket_with_batch_resources(stack_name, aws_client_config, resources_dir):
    random_string = "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(16))
    s3_bucket_name = "-".join([stack_name.lower(), random_string])

    try:
        utils.create_s3_bucket(bucket_name=s3_bucket_name, aws_client_config=aws_client_config)
        utils.upload_resources_artifacts(
            bucket_name=s3_bucket_name, root=resources_dir, aws_client_config=aws_client_config
        )
    except boto3.client("s3").exceptions.BucketAlreadyExists:
        LOGGER.error("Bucket %s already exists. Please retry cluster creation.", s3_bucket_name)
        raise
    except Exception:
        utils.delete_s3_bucket(bucket_name=s3_bucket_name, aws_client_config=aws_client_config)
        raise
    return s3_bucket_name


def version(args):
    config = cfnconfig.ParallelClusterConfig(args)
    LOGGER.info(config.version)


def create(args):  # noqa: C901 FIXME!!!
    LOGGER.info("Beginning cluster creation for cluster: %s", args.cluster_name)
    LOGGER.debug("Building cluster config based on args %s", str(args))

    # Build the config based on args
    config = cfnconfig.ParallelClusterConfig(args)
    aws_client_config = dict(
        region_name=config.region,
        aws_access_key_id=config.aws_access_key_id,
        aws_secret_access_key=config.aws_secret_access_key,
    )

    # Set the ComputeWaitConditionCount parameter to match DesiredSize
    if "DesiredSize" in config.parameters:
        config.parameters["ComputeWaitConditionCount"] = config.parameters["DesiredSize"]

    # Get the MasterSubnetId and use it to determine AvailabilityZone
    if "MasterSubnetId" in config.parameters:
        master_subnet_id = config.parameters["MasterSubnetId"]
        try:
            ec2 = utils.boto3_client("ec2", aws_client_config)
            availability_zone = (
                ec2.describe_subnets(SubnetIds=[master_subnet_id]).get("Subnets")[0].get("AvailabilityZone")
            )
        except ClientError as e:
            LOGGER.critical(e.response.get("Error").get("Message"))
            sys.stdout.flush()
            sys.exit(1)
        config.parameters["AvailabilityZone"] = availability_zone

    capabilities = ["CAPABILITY_IAM"]
    batch_temporary_bucket = None
    try:
        cfn = utils.boto3_client("cloudformation", aws_client_config)
        stack_name = "parallelcluster-" + args.cluster_name

        # If scheduler is awsbatch create bucket with resources
        if config.parameters["Scheduler"] == "awsbatch":
            batch_resources = pkg_resources.resource_filename(__name__, "resources/batch")
            batch_temporary_bucket = create_bucket_with_batch_resources(
                stack_name=stack_name, aws_client_config=aws_client_config, resources_dir=batch_resources
            )
            config.parameters["ResourcesS3Bucket"] = batch_temporary_bucket

        LOGGER.info("Creating stack named: %s", stack_name)

        cfn_params = [{"ParameterKey": key, "ParameterValue": value} for key, value in config.parameters.items()]
        tags = [{"Key": t, "Value": config.tags[t]} for t in config.tags]

        stack = cfn.create_stack(
            StackName=stack_name,
            TemplateURL=config.template_url,
            Parameters=cfn_params,
            Capabilities=capabilities,
            DisableRollback=args.norollback,
            Tags=tags,
        )
        LOGGER.debug("StackId: %s", stack.get("StackId"))

        status = cfn.describe_stacks(StackName=stack_name).get("Stacks")[0].get("StackStatus")

        if not args.nowait:
            resource_status = ""
            while status == "CREATE_IN_PROGRESS":
                status = cfn.describe_stacks(StackName=stack_name).get("Stacks")[0].get("StackStatus")
                events = cfn.describe_stack_events(StackName=stack_name).get("StackEvents")[0]
                resource_status = (
                    "Status: %s - %s" % (events.get("LogicalResourceId"), events.get("ResourceStatus"))
                ).ljust(80)
                sys.stdout.write("\r%s" % resource_status)
                sys.stdout.flush()
                time.sleep(5)
            # print the last status update in the logs
            if resource_status != "":
                LOGGER.debug(resource_status)

            if status != "CREATE_COMPLETE":
                LOGGER.critical("\nCluster creation failed.  Failed events:")
                events = cfn.describe_stack_events(StackName=stack_name).get("StackEvents")
                for event in events:
                    if event.get("ResourceStatus") == "CREATE_FAILED":
                        LOGGER.info(
                            "  - %s %s %s",
                            event.get("ResourceType"),
                            event.get("LogicalResourceId"),
                            event.get("ResourceStatusReason"),
                        )
            LOGGER.info("")
            result_stack = cfn.describe_stacks(StackName=stack_name).get("Stacks")[0]
            _print_stack_outputs(result_stack)
        else:
            status = cfn.describe_stacks(StackName=stack_name).get("Stacks")[0].get("StackStatus")
            LOGGER.info("Status: %s", status)
    except ClientError as e:
        LOGGER.critical(e.response.get("Error").get("Message"))
        sys.stdout.flush()
        if batch_temporary_bucket:
            utils.delete_s3_bucket(bucket_name=batch_temporary_bucket, aws_client_config=aws_client_config)
        sys.exit(1)
    except KeyboardInterrupt:
        LOGGER.info("\nExiting...")
        sys.exit(0)
    except KeyError as e:
        LOGGER.critical("ERROR: KeyError - reason:")
        LOGGER.critical(e)
        if batch_temporary_bucket:
            utils.delete_s3_bucket(bucket_name=batch_temporary_bucket, aws_client_config=aws_client_config)
        sys.exit(1)
    except Exception as e:
        LOGGER.critical(e)
        if batch_temporary_bucket:
            utils.delete_s3_bucket(bucket_name=batch_temporary_bucket, aws_client_config=aws_client_config)
        sys.exit(1)


def _print_stack_outputs(stack):
    """
    Print a limited set of the CloudFormation Stack outputs.

    :param stack: the stack dictionary
    """
    whitelisted_outputs = [
        "ClusterUser",
        "MasterPrivateIP",
        "MasterPublicIP",
        "BatchComputeEnvironmentArn",
        "BatchJobQueueArn",
        "BatchJobDefinitionArn",
        "BatchJobDefinitionMnpArn",
        "BatchUserRole",
    ]
    if is_ganglia_enabled(stack.get("Parameters")):
        whitelisted_outputs.extend(["GangliaPrivateURL", "GangliaPublicURL"])

    for output in stack.get("Outputs", []):
        output_key = output.get("OutputKey")
        if output_key in whitelisted_outputs:
            LOGGER.info("%s: %s", output_key, output.get("OutputValue"))


def is_ganglia_enabled(parameters):
    try:
        extra_json = filter(lambda x: x.get("ParameterKey") == "ExtraJson", parameters)[0].get("ParameterValue")
        extra_json = json.loads(extra_json).get("cfncluster")
        return extra_json.get("ganglia_enabled") == "yes"
    except Exception:
        pass
    return False


def update(args):  # noqa: C901 FIXME!!!
    LOGGER.info("Updating: %s", args.cluster_name)
    stack_name = "parallelcluster-" + args.cluster_name
    config = cfnconfig.ParallelClusterConfig(args)
    capabilities = ["CAPABILITY_IAM"]

    cfn = boto3.client(
        "cloudformation",
        region_name=config.region,
        aws_access_key_id=config.aws_access_key_id,
        aws_secret_access_key=config.aws_secret_access_key,
    )

    if config.parameters.get("Scheduler") != "awsbatch":
        asg = boto3.client(
            "autoscaling",
            region_name=config.region,
            aws_access_key_id=config.aws_access_key_id,
            aws_secret_access_key=config.aws_secret_access_key,
        )

        if not args.reset_desired:
            asg_name = get_asg_name(stack_name, config)
            desired_capacity = (
                asg.describe_auto_scaling_groups(AutoScalingGroupNames=[asg_name])
                .get("AutoScalingGroups")[0]
                .get("DesiredCapacity")
            )
            config.parameters["DesiredSize"] = str(desired_capacity)
    else:
        if args.reset_desired:
            LOGGER.info("reset_desired flag does not work with awsbatch scheduler")
        params = cfn.describe_stacks(StackName=stack_name).get("Stacks")[0].get("Parameters")

        for parameter in params:
            if parameter.get("ParameterKey") == "ResourcesS3Bucket":
                config.parameters["ResourcesS3Bucket"] = parameter.get("ParameterValue")

    # Get the MasterSubnetId and use it to determine AvailabilityZone
    if "MasterSubnetId" in config.parameters:
        master_subnet_id = config.parameters["MasterSubnetId"]
        try:
            ec2 = boto3.client(
                "ec2",
                region_name=config.region,
                aws_access_key_id=config.aws_access_key_id,
                aws_secret_access_key=config.aws_secret_access_key,
            )
            availability_zone = (
                ec2.describe_subnets(SubnetIds=[master_subnet_id]).get("Subnets")[0].get("AvailabilityZone")
            )
        except ClientError as e:
            LOGGER.critical(e.response.get("Error").get("Message"))
            sys.exit(1)
        config.parameters["AvailabilityZone"] = availability_zone

    try:
        LOGGER.debug((config.template_url, config.parameters))

        cfn_params = [{"ParameterKey": key, "ParameterValue": value} for key, value in config.parameters.items()]
        LOGGER.info("Calling update_stack")
        cfn.update_stack(
            StackName=stack_name, TemplateURL=config.template_url, Parameters=cfn_params, Capabilities=capabilities
        )
        status = cfn.describe_stacks(StackName=stack_name).get("Stacks")[0].get("StackStatus")
        if not args.nowait:
            while status == "UPDATE_IN_PROGRESS":
                status = cfn.describe_stacks(StackName=stack_name).get("Stacks")[0].get("StackStatus")
                events = cfn.describe_stack_events(StackName=stack_name).get("StackEvents")[0]
                resource_status = (
                    "Status: %s - %s" % (events.get("LogicalResourceId"), events.get("ResourceStatus"))
                ).ljust(80)
                sys.stdout.write("\r%s" % resource_status)
                sys.stdout.flush()
                time.sleep(5)
        else:
            status = cfn.describe_stacks(StackName=stack_name).get("Stacks")[0].get("StackStatus")
            LOGGER.info("Status: %s", status)
    except ClientError as e:
        LOGGER.critical(e.response.get("Error").get("Message"))
        sys.exit(1)
    except KeyboardInterrupt:
        LOGGER.info("\nExiting...")
        sys.exit(0)


def start(args):
    # Set resource limits on compute fleet or awsbatch ce to min/max/desired = 0/max/0
    stack_name = "parallelcluster-" + args.cluster_name
    config = cfnconfig.ParallelClusterConfig(args)

    if config.parameters.get("Scheduler") == "awsbatch":
        LOGGER.info("Enabling AWS Batch compute environment : %s", args.cluster_name)
        max_vcpus = (
            config.parameters.get("MaxSize")
            if config.parameters.get("MaxSize") and int(config.parameters.get("MaxSize")) >= 0
            else 20
        )
        desired_vcpus = (
            config.parameters.get("DesiredSize")
            if config.parameters.get("DesiredSize") and int(config.parameters.get("DesiredSize")) >= 0
            else 4
        )
        min_vcpus = (
            config.parameters.get("MinSize")
            if config.parameters.get("MinSize") and int(config.parameters.get("MinSize")) > 0
            else 0
        )
        start_batch_ce(
            ce_name=stack_name, config=config, min_vcpus=min_vcpus, desired_vcpus=desired_vcpus, max_vcpus=max_vcpus
        )
    else:
        LOGGER.info("Starting compute fleet : %s", args.cluster_name)

        # Set asg limits
        max_queue_size = (
            config.parameters.get("MaxSize")
            if config.parameters.get("MaxSize") and int(config.parameters.get("MaxSize")) >= 0
            else 10
        )
        desired_queue_size = (
            config.parameters.get("DesiredSize")
            if config.parameters.get("DesiredSize") and int(config.parameters.get("DesiredSize")) >= 0
            else 2
        )
        min_queue_size = (
            config.parameters.get("MinSize")
            if config.parameters.get("MinSize") and int(config.parameters.get("MinSize")) > 0
            else 0
        )

        asg_name = get_asg_name(stack_name=stack_name, config=config)
        set_asg_limits(
            asg_name=asg_name, config=config, min=min_queue_size, max=max_queue_size, desired=desired_queue_size
        )


def stop(args):
    # Set resource limits on compute fleet or awsbatch ce to min/max/desired = 0/0/0
    stack_name = "parallelcluster-" + args.cluster_name
    config = cfnconfig.ParallelClusterConfig(args)

    if config.parameters.get("Scheduler") == "awsbatch":
        LOGGER.info("Disabling AWS Batch compute environment : %s", args.cluster_name)
        stop_batch_ce(ce_name=stack_name, config=config)
    else:
        LOGGER.info("Stopping compute fleet : %s", args.cluster_name)
        # Set Resource limits
        asg_name = get_asg_name(stack_name=stack_name, config=config)
        set_asg_limits(asg_name=asg_name, config=config, min=0, max=0, desired=0)


def list_stacks(args):
    config = cfnconfig.ParallelClusterConfig(args)
    cfn = boto3.client(
        "cloudformation",
        region_name=config.region,
        aws_access_key_id=config.aws_access_key_id,
        aws_secret_access_key=config.aws_secret_access_key,
    )
    try:
        stacks = cfn.describe_stacks().get("Stacks")
        for stack in stacks:
            if stack.get("ParentId") is None and stack.get("StackName").startswith("parallelcluster-"):
                LOGGER.info("%s", stack.get("StackName")[len("parallelcluster-") :])  # noqa: E203
    except ClientError as e:
        LOGGER.critical(e.response.get("Error").get("Message"))
        sys.exit(1)
    except KeyboardInterrupt:
        LOGGER.info("Exiting...")
        sys.exit(0)


def get_master_server_id(stack_name, config):
    # returns the physical id of the master server
    # if no master server returns []
    cfn = boto3.client(
        "cloudformation",
        region_name=config.region,
        aws_access_key_id=config.aws_access_key_id,
        aws_secret_access_key=config.aws_secret_access_key,
    )

    try:
        resources = cfn.describe_stack_resource(StackName=stack_name, LogicalResourceId="MasterServer")
        return resources.get("StackResourceDetail").get("PhysicalResourceId")
    except ClientError as e:
        LOGGER.critical(e.response.get("Error").get("Message"))
        sys.exit(1)


def poll_master_server_state(stack_name, config):
    ec2 = boto3.client(
        "ec2",
        region_name=config.region,
        aws_access_key_id=config.aws_access_key_id,
        aws_secret_access_key=config.aws_secret_access_key,
    )

    master_id = get_master_server_id(stack_name, config)

    try:
        instance = ec2.describe_instance_status(InstanceIds=[master_id]).get("InstanceStatuses")[0]
        state = instance.get("InstanceState").get("Name")
        sys.stdout.write("\rMasterServer: %s" % state.upper())
        sys.stdout.flush()
        while state not in ["running", "stopped", "terminated", "shutting-down"]:
            time.sleep(5)
            state = (
                ec2.describe_instance_status(InstanceIds=[master_id])
                .get("InstanceStatuses")[0]
                .get("InstanceState")
                .get("Name")
            )
            status = "\r\033[KMasterServer: %s" % state.upper()
            sys.stdout.write(status)
            sys.stdout.flush()
        if state in ["terminated", "shutting-down"]:
            LOGGER.info("State: %s is irrecoverable. Cluster needs to be re-created.", state)
            sys.exit(1)
        status = "\rMasterServer: %s\n" % state.upper()
        sys.stdout.write(status)
        sys.stdout.flush()
    except ClientError as e:
        LOGGER.critical(e.response.get("Error").get("Message"))
        sys.stdout.flush()
        sys.exit(1)
    except KeyboardInterrupt:
        LOGGER.info("\nExiting...")
        sys.exit(0)

    return state


def get_ec2_instances(stack, config):
    cfn = boto3.client(
        "cloudformation",
        region_name=config.region,
        aws_access_key_id=config.aws_access_key_id,
        aws_secret_access_key=config.aws_secret_access_key,
    )

    try:
        resources = cfn.describe_stack_resources(StackName=stack).get("StackResources")
    except ClientError as e:
        LOGGER.critical(e.response.get("Error").get("Message"))
        sys.stdout.flush()
        sys.exit(1)

    temp_instances = [r for r in resources if r.get("ResourceType") == "AWS::EC2::Instance"]

    instances = []
    for instance in temp_instances:
        instances.append([instance.get("LogicalResourceId"), instance.get("PhysicalResourceId")])

    return instances


def get_asg_name(stack_name, config):
    cfn = boto3.client(
        "cloudformation",
        region_name=config.region,
        aws_access_key_id=config.aws_access_key_id,
        aws_secret_access_key=config.aws_secret_access_key,
    )
    try:
        resources = cfn.describe_stack_resources(StackName=stack_name).get("StackResources")
        return [r for r in resources if r.get("LogicalResourceId") == "ComputeFleet"][0].get("PhysicalResourceId")
    except ClientError as e:
        LOGGER.critical(e.response.get("Error").get("Message"))
        sys.stdout.flush()
        sys.exit(1)
    except IndexError:
        LOGGER.critical("Stack %s does not have a ComputeFleet", stack_name)
        sys.exit(1)


def set_asg_limits(asg_name, config, min, max, desired):
    asg = boto3.client(
        "autoscaling",
        region_name=config.region,
        aws_access_key_id=config.aws_access_key_id,
        aws_secret_access_key=config.aws_secret_access_key,
    )

    asg.update_auto_scaling_group(
        AutoScalingGroupName=asg_name, MinSize=int(min), MaxSize=int(max), DesiredCapacity=int(desired)
    )


def get_asg_instances(stack, config):
    asg = boto3.client(
        "autoscaling",
        region_name=config.region,
        aws_access_key_id=config.aws_access_key_id,
        aws_secret_access_key=config.aws_secret_access_key,
    )

    asg_name = get_asg_name(stack, config)
    asg = asg.describe_auto_scaling_groups(AutoScalingGroupNames=[asg_name]).get("AutoScalingGroups")[0]
    name = [tag.get("Value") for tag in asg.get("Tags") if tag.get("Key") == "aws:cloudformation:logical-id"][0]

    temp_instances = []
    for instance in asg.get("Instances"):
        temp_instances.append([name, instance.get("InstanceId")])

    return temp_instances


def start_batch_ce(ce_name, config, min_vcpus, desired_vcpus, max_vcpus):
    batch = boto3.client(
        "batch",
        region_name=config.region,
        aws_access_key_id=config.aws_access_key_id,
        aws_secret_access_key=config.aws_secret_access_key,
    )
    try:
        batch.update_compute_environment(
            computeEnvironment=ce_name,
            state="ENABLED",
            computeResources={
                "minvCpus": int(min_vcpus),
                "maxvCpus": int(max_vcpus),
                "desiredvCpus": int(desired_vcpus),
            },
        )
    except ClientError as e:
        LOGGER.critical(e.response.get("Error").get("Message"))
        sys.exit(1)


def stop_batch_ce(ce_name, config):
    batch = boto3.client(
        "batch",
        region_name=config.region,
        aws_access_key_id=config.aws_access_key_id,
        aws_secret_access_key=config.aws_secret_access_key,
    )

    batch.update_compute_environment(computeEnvironment=ce_name, state="DISABLED")


def instances(args):
    stack = "parallelcluster-" + args.cluster_name

    config = cfnconfig.ParallelClusterConfig(args)
    instances = []
    instances.extend(get_ec2_instances(stack, config))

    if config.parameters.get("Scheduler") != "awsbatch":
        instances.extend(get_asg_instances(stack, config))

    for instance in instances:
        print("%s         %s" % (instance[0], instance[1]))

    if config.parameters.get("Scheduler") == "awsbatch":
        LOGGER.info("Run 'awsbhosts --cluster %s' to list the compute instances", args.cluster_name)


def command(args, extra_args):
    stack = "parallelcluster-" + args.cluster_name
    config = cfnconfig.ParallelClusterConfig(args)
    if args.command in config.aliases:
        config_command = config.aliases[args.command]
    else:
        config_command = "ssh {CFN_USER}@{MASTER_IP} {ARGS}"

    cfn = boto3.client(
        "cloudformation",
        region_name=config.region,
        aws_access_key_id=config.aws_access_key_id,
        aws_secret_access_key=config.aws_secret_access_key,
    )
    try:
        stack_result = cfn.describe_stacks(StackName=stack).get("Stacks")[0]
        status = stack_result.get("StackStatus")
        valid_status = ["CREATE_COMPLETE", "UPDATE_COMPLETE"]
        if status not in valid_status:
            LOGGER.info("Stack status: %s. Stack needs to be in %s", status, " or ".join(valid_status))
            sys.exit(1)
        outputs = stack_result.get("Outputs")
        username = [o.get("OutputValue") for o in outputs if o.get("OutputKey") == "ClusterUser"][0]
        ip = [o.get("OutputValue") for o in outputs if o.get("OutputKey") == "MasterPublicIP"][0]

        try:
            from shlex import quote as cmd_quote
        except ImportError:
            from pipes import quote as cmd_quote

        # build command
        cmd = config_command.format(
            CFN_USER=username, MASTER_IP=ip, ARGS=" ".join(cmd_quote(str(e)) for e in extra_args)
        )

        # run command
        if not args.dryrun:
            os.system(cmd)
        else:
            LOGGER.info(cmd)
    except ClientError as e:
        LOGGER.critical(e.response.get("Error").get("Message"))
        sys.stdout.flush()
        sys.exit(1)
    except KeyboardInterrupt:
        LOGGER.info("\nExiting...")
        sys.exit(0)


def status(args):  # noqa: C901 FIXME!!!
    stack_name = "parallelcluster-" + args.cluster_name
    config = cfnconfig.ParallelClusterConfig(args)

    cfn = boto3.client(
        "cloudformation",
        region_name=config.region,
        aws_access_key_id=config.aws_access_key_id,
        aws_secret_access_key=config.aws_secret_access_key,
    )

    try:
        status = cfn.describe_stacks(StackName=stack_name).get("Stacks")[0].get("StackStatus")
        sys.stdout.write("\rStatus: %s" % status)
        sys.stdout.flush()
        if not args.nowait:
            while status not in [
                "CREATE_COMPLETE",
                "UPDATE_COMPLETE",
                "UPDATE_ROLLBACK_COMPLETE",
                "ROLLBACK_COMPLETE",
                "CREATE_FAILED",
                "DELETE_FAILED",
            ]:
                time.sleep(5)
                status = cfn.describe_stacks(StackName=stack_name).get("Stacks")[0].get("StackStatus")
                events = cfn.describe_stack_events(StackName=stack_name).get("StackEvents")[0]
                resource_status = (
                    "Status: %s - %s" % (events.get("LogicalResourceId"), events.get("ResourceStatus"))
                ).ljust(80)
                sys.stdout.write("\r%s" % resource_status)
                sys.stdout.flush()
            sys.stdout.write("\rStatus: %s\n" % status)
            sys.stdout.flush()
            if status in ["CREATE_COMPLETE", "UPDATE_COMPLETE"]:
                state = poll_master_server_state(stack_name, config)
                if state == "running":
                    stack = cfn.describe_stacks(StackName=stack_name).get("Stacks")[0]
                    _print_stack_outputs(stack)
            elif status in ["ROLLBACK_COMPLETE", "CREATE_FAILED", "DELETE_FAILED", "UPDATE_ROLLBACK_COMPLETE"]:
                events = cfn.describe_stack_events(StackName=stack_name).get("StackEvents")
                for event in events:
                    if event.get("ResourceStatus") in ["CREATE_FAILED", "DELETE_FAILED", "UPDATE_FAILED"]:
                        LOGGER.info(
                            "%s %s %s %s %s",
                            event.get("Timestamp"),
                            event.get("ResourceStatus"),
                            event.get("ResourceType"),
                            event.get("LogicalResourceId"),
                            event.get("ResourceStatusReason"),
                        )
        else:
            sys.stdout.write("\n")
            sys.stdout.flush()
    except ClientError as e:
        LOGGER.critical(e.response.get("Error").get("Message"))
        sys.stdout.flush()
        sys.exit(1)
    except KeyboardInterrupt:
        LOGGER.info("\nExiting...")
        sys.exit(0)


def delete(args):
    saw_update = False
    LOGGER.info("Deleting: %s", args.cluster_name)
    stack = "parallelcluster-" + args.cluster_name

    config = cfnconfig.ParallelClusterConfig(args)

    cfn = boto3.client(
        "cloudformation",
        region_name=config.region,
        aws_access_key_id=config.aws_access_key_id,
        aws_secret_access_key=config.aws_secret_access_key,
    )

    try:
        # delete_stack does not raise an exception if stack does not exist
        # Use describe_stacks to explicitly check if the stack exists
        cfn.describe_stacks(StackName=stack)
        cfn.delete_stack(StackName=stack)
        saw_update = True
        status = cfn.describe_stacks(StackName=stack).get("Stacks")[0].get("StackStatus")
        sys.stdout.write("\rStatus: %s" % status)
        sys.stdout.flush()
        LOGGER.debug("Status: %s", status)
        if not args.nowait:
            while status == "DELETE_IN_PROGRESS":
                time.sleep(5)
                status = cfn.describe_stacks(StackName=stack).get("Stacks")[0].get("StackStatus")
                events = cfn.describe_stack_events(StackName=stack).get("StackEvents")[0]
                resource_status = (
                    "Status: %s - %s" % (events.get("LogicalResourceId"), events.get("ResourceStatus"))
                ).ljust(80)
                sys.stdout.write("\r%s" % resource_status)
                sys.stdout.flush()
            sys.stdout.write("\rStatus: %s\n" % status)
            sys.stdout.flush()
            LOGGER.debug("Status: %s", status)
        else:
            sys.stdout.write("\n")
            sys.stdout.flush()
        if status == "DELETE_FAILED":
            LOGGER.info("Cluster did not delete successfully. Run 'pcluster delete %s' again", stack)
    except ClientError as e:
        if e.response.get("Error").get("Message").endswith("does not exist"):
            if saw_update:
                LOGGER.info("\nCluster deleted successfully.")
                sys.exit(0)
        LOGGER.critical(e.response.get("Error").get("Message"))
        sys.stdout.flush()
        sys.exit(1)
    except KeyboardInterrupt:
        LOGGER.info("\nExiting...")
        sys.exit(0)


def get_cookbook_url(config, tmpdir):
    if config.args.custom_ami_cookbook is not None:
        return config.args.custom_ami_cookbook

    cookbook_version = get_cookbook_version(config, tmpdir)
    if config.region == "us-east-1":
        return "https://s3.amazonaws.com/%s-aws-parallelcluster/cookbooks/%s.tgz" % (config.region, cookbook_version)

    return "https://s3.%s.amazonaws.com/%s-aws-parallelcluster/cookbooks/%s.tgz" % (
        config.region,
        config.region,
        cookbook_version,
    )


def get_cookbook_version(config, tmpdir):
    tmp_template_file = os.path.join(tmpdir, "aws-parallelcluster-template.json")
    try:
        LOGGER.info("Template: %s", config.template_url)
        urlretrieve(url=config.template_url, filename=tmp_template_file)

        with open(tmp_template_file) as cfn_file:
            cfn_data = json.load(cfn_file)

        return cfn_data.get("Mappings").get("PackagesVersions").get("default").get("cookbook")

    except IOError as e:
        LOGGER.error("Unable to download template at URL %s", config.template_url)
        LOGGER.critical("Error: %s", str(e))
        sys.exit(1)
    except (ValueError, AttributeError) as e:
        LOGGER.error("Unable to parse template at URL %s", config.template_url)
        LOGGER.critical("Error: %s", str(e))
        sys.exit(1)


def get_cookbook_dir(config, tmpdir):
    cookbook_url = ""
    try:
        tmp_cookbook_archive = os.path.join(tmpdir, "aws-parallelcluster-cookbook.tgz")

        cookbook_url = get_cookbook_url(config, tmpdir)
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


def dispose_packer_instance(results, config):
    time.sleep(2)
    try:
        ec2_client = boto3.client(
            "ec2",
            region_name=config.region,
            aws_access_key_id=config.aws_access_key_id,
            aws_secret_access_key=config.aws_secret_access_key,
        )
        """ :type : pyboto3.ec2 """

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


def run_packer(packer_command, packer_env, config):
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
    except (IOError, OSError):
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
            dispose_packer_instance(results, config)


def print_create_ami_results(results):
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


def create_ami(args):
    LOGGER.info("Building AWS ParallelCluster AMI. This could take a while...")
    LOGGER.debug("Building AMI based on args %s", str(args))
    results = {}

    instance_type = "t2.large"
    try:
        config = cfnconfig.ParallelClusterConfig(args)

        vpc_id = config.parameters.get("VPCId")
        master_subnet_id = config.parameters.get("MasterSubnetId")

        packer_env = {
            "CUSTOM_AMI_ID": args.base_ami_id,
            "AWS_FLAVOR_ID": instance_type,
            "AMI_NAME_PREFIX": args.custom_ami_name_prefix,
            "AWS_VPC_ID": vpc_id,
            "AWS_SUBNET_ID": master_subnet_id,
        }

        if config.aws_access_key_id:
            packer_env["AWS_ACCESS_KEY_ID"] = config.aws_access_key_id
        if config.aws_secret_access_key:
            packer_env["AWS_SECRET_ACCESS_KEY"] = config.aws_secret_access_key

        LOGGER.info("Base AMI ID: %s", args.base_ami_id)
        LOGGER.info("Base AMI OS: %s", args.base_ami_os)
        LOGGER.info("Instance Type: %s", instance_type)
        LOGGER.info("Region: %s", config.region)
        LOGGER.info("VPC ID: %s", vpc_id)
        LOGGER.info("Subnet ID: %s", master_subnet_id)

        tmp_dir = mkdtemp()
        cookbook_dir = get_cookbook_dir(config, tmp_dir)

        packer_command = (
            cookbook_dir
            + "/amis/build_ami.sh --os "
            + args.base_ami_os
            + " --partition region"
            + " --region "
            + config.region
            + " --custom"
        )

        results = run_packer(packer_command, packer_env, config)
    except KeyboardInterrupt:
        LOGGER.info("\nExiting...")
        sys.exit(0)
    finally:
        print_create_ami_results(results)
        if "tmp_dir" in locals() and tmp_dir:
            rmtree(tmp_dir)
