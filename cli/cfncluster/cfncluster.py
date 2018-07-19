from __future__ import print_function
from __future__ import absolute_import
# Copyright 2013-2018 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance with the
# License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
from builtins import str
import sys
import time
import logging
import boto3
import os
from botocore.exceptions import ClientError

from . import cfnconfig

logger = logging.getLogger('cfncluster.cfncluster')

def version(args):
    config = cfnconfig.CfnClusterConfig(args)
    logger.info(config.version)

def create(args):
    logger.info('Beginning cluster creation for cluster: %s' % (args.cluster_name))
    logger.debug('Building cluster config based on args %s' % str(args))

    # Build the config based on args
    config = cfnconfig.CfnClusterConfig(args)

    # Set the ComputeWaitConditionCount parameter to match InitialQueueSize
    try:
        i = [p[0] for p in config.parameters].index('InitialQueueSize')
        initial_queue_size = config.parameters[i][1]
        config.parameters.append(('ComputeWaitConditionCount', initial_queue_size))
    except ValueError:
        pass

    # Get the MasterSubnetId and use it to determine AvailabilityZone
    try:
        i = [p[0] for p in config.parameters].index('MasterSubnetId')
        master_subnet_id = config.parameters[i][1]
        try:
            ec2 = boto3.client('ec2', region_name=config.region,
                                 aws_access_key_id=config.aws_access_key_id,
                                 aws_secret_access_key=config.aws_secret_access_key)
            availability_zone = ec2.describe_subnets(SubnetIds=[master_subnet_id])\
                .get('Subnets')[0]\
                .get('AvailabilityZone')
        except ClientError as e:
            logger.critical(e.response.get('Error').get('Message'))
            sys.stdout.flush()
            sys.exit(1)
        config.parameters.append(('AvailabilityZone', availability_zone))
    except ValueError:
        pass

    capabilities = ["CAPABILITY_IAM"]
    try:
        cfn = boto3.client('cloudformation', region_name=config.region,
                           aws_access_key_id=config.aws_access_key_id,
                           aws_secret_access_key=config.aws_secret_access_key)
        stack_name = 'cfncluster-' + args.cluster_name
        logger.info("Creating stack named: " + stack_name)

        cfn_params = [{'ParameterKey': param[0], 'ParameterValue': param[1]} for param in config.parameters]
        tags = [{'Key': t, 'Value': config.tags[t]} for t in config.tags]

        stack = cfn.create_stack(StackName=stack_name,
                                 TemplateURL=config.template_url,
                                 Parameters=cfn_params,
                                 Capabilities=capabilities,
                                 DisableRollback=args.norollback, Tags=tags)
        logger.debug('StackId: %s' % (stack.get('StackId')))

        status = cfn.describe_stacks(StackName=stack_name).get("Stacks")[0].get('StackStatus')

        if not args.nowait:
            resource_status = ''
            while status == 'CREATE_IN_PROGRESS':
                status = cfn.describe_stacks(StackName=stack_name).get("Stacks")[0].get('StackStatus')
                events = cfn.describe_stack_events(StackName=stack_name).get('StackEvents')[0]
                resource_status = ('Status: %s - %s' % (events.get('LogicalResourceId'), events.get('ResourceStatus'))).ljust(80)
                sys.stdout.write('\r%s' % resource_status)
                sys.stdout.flush()
                time.sleep(5)
            # print the last status update in the logs
            if resource_status != '':
                logger.debug(resource_status)

            if status != 'CREATE_COMPLETE':
                logger.critical('\nCluster creation failed.  Failed events:')
                events = cfn.describe_stack_events(StackName=stack_name).get('StackEvents')
                for event in events:
                    if event.get('ResourceStatus') == 'CREATE_FAILED':
                        logger.info("  - %s %s %s" %
                                    (event.get('ResourceType'), event.get('LogicalResourceId'),
                                     event.get('ResourceStatusReason')))
            logger.info('')
            outputs = cfn.describe_stacks(StackName=stack_name).get("Stacks")[0].get('Outputs', [])
            for output in outputs:
                logger.info("%s: %s" % (output.get('OutputKey'), output.get('OutputValue')))
        else:
            status = cfn.describe_stacks(StackName=stack_name).get("Stacks")[0].get('StackStatus')
            logger.info('Status: %s' % status)
    except ClientError as e:
        logger.critical(e.response.get('Error').get('Message'))
        sys.stdout.flush()
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info('\nExiting...')
        sys.exit(0)
    except Exception as e:
        logger.critical(e)
        sys.exit(1)


def update(args):
    logger.info('Updating: %s' % (args.cluster_name))
    stack_name = ('cfncluster-' + args.cluster_name)
    config = cfnconfig.CfnClusterConfig(args)
    capabilities = ["CAPABILITY_IAM"]

    cfn = boto3.client('cloudformation', region_name=config.region,
                       aws_access_key_id=config.aws_access_key_id,
                       aws_secret_access_key=config.aws_secret_access_key)

    asg = boto3.client('autoscaling', region_name=config.region,
                       aws_access_key_id=config.aws_access_key_id,
                       aws_secret_access_key=config.aws_secret_access_key)

    if not args.reset_desired:
        asg_name = get_asg_name(stack_name, config)
        desired_capacity = asg.describe_auto_scaling_groups(AutoScalingGroupNames=[asg_name])\
            .get('AutoScalingGroups')[0]\
            .get('DesiredCapacity')
        config.parameters.append(('InitialQueueSize', desired_capacity))

    # Get the MasterSubnetId and use it to determine AvailabilityZone
    try:
        i = [p[0] for p in config.parameters].index('MasterSubnetId')
        master_subnet_id = config.parameters[i][1]
        try:
            ec2 = boto3.client('ec2', region_name=config.region,
                               aws_access_key_id=config.aws_access_key_id,
                               aws_secret_access_key=config.aws_secret_access_key)
            availability_zone = ec2.describe_subnets(SubnetIds=[master_subnet_id]) \
                .get('Subnets')[0] \
                .get('AvailabilityZone')
        except ClientError as e:
            logger.critical(e.response.get('Error').get('Message'))
            sys.exit(1)
        config.parameters.append(('AvailabilityZone', availability_zone))
    except ValueError:
        pass

    try:
        logger.debug((config.template_url, config.parameters))

        cfn_params = [{'ParameterKey': param[0], 'ParameterValue': str(param[1])} for param in config.parameters]
        cfn.update_stack(StackName=stack_name,TemplateURL=config.template_url,
                         Parameters=cfn_params, Capabilities=capabilities)
        status = cfn.describe_stacks(StackName=stack_name).get("Stacks")[0].get('StackStatus')
        if not args.nowait:
            while status == 'UPDATE_IN_PROGRESS':
                status = cfn.describe_stacks(StackName=stack_name).get("Stacks")[0].get('StackStatus')
                events = cfn.describe_stack_events(StackName=stack_name).get('StackEvents')[0]
                resource_status = ('Status: %s - %s' % (events.get('LogicalResourceId'), events.get('ResourceStatus'))).ljust(80)
                sys.stdout.write('\r%s' % resource_status)
                sys.stdout.flush()
                time.sleep(5)
        else:
            status = cfn.describe_stacks(StackName=stack_name).get("Stacks")[0].get('StackStatus')
            logger.info('Status: %s' % status)
    except ClientError as e:
        logger.critical(e.response.get('Error').get('Message'))
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info('\nExiting...')
        sys.exit(0)

def start(args):
    # Set resource limits on compute fleet to min/max/desired = 0/max/0
    logger.info('Starting compute fleet : %s' % args.cluster_name)
    stack_name = ('cfncluster-' + args.cluster_name)
    config = cfnconfig.CfnClusterConfig(args)

    # Set asg limits
    max_queue_size = [param[1] for param in config.parameters if param[0] == 'MaxQueueSize']
    max_queue_size = int(max_queue_size[0] if len(max_queue_size) > 0 else 10)
    desired_queue_size = [param[1] for param in config.parameters if param[0] == 'InitialQueueSize']
    desired_queue_size = int(desired_queue_size[0] if len(desired_queue_size) > 0 else 2)
    min_queue_size = [desired_queue_size for param in config.parameters if param[0] == 'MaintainInitialSize' and param[1] == "true"]
    min_queue_size = int(min_queue_size[0] if len(min_queue_size) > 0 else 0)

    asg_name = get_asg_name(stack_name=stack_name, config=config)
    set_asg_limits(asg_name=asg_name, config=config, min=min_queue_size, max=max_queue_size, desired=desired_queue_size)

def stop(args):
    # Set resource limits on compute fleet to min/max/desired = 0/0/0
    logger.info('Stopping compute fleet : %s' % args.cluster_name)
    stack_name = ('cfncluster-' + args.cluster_name)
    config = cfnconfig.CfnClusterConfig(args)

    # Set Resource limits
    asg_name = get_asg_name(stack_name=stack_name, config=config)
    set_asg_limits(asg_name=asg_name, config=config, min=0, max=0, desired=0)

def list(args):
    config = cfnconfig.CfnClusterConfig(args)
    cfn = boto3.client('cloudformation', region_name=config.region,
                       aws_access_key_id=config.aws_access_key_id,
                       aws_secret_access_key=config.aws_secret_access_key)
    try:
        stacks = cfn.describe_stacks().get('Stacks')
        for stack in stacks:
            if stack.get('StackName').startswith('cfncluster-'):
                logger.info('%s' % (stack.get('StackName')[11:]))
    except ClientError as e:
        logger.critical(e.response.get('Error').get('Message'))
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info('Exiting...')
        sys.exit(0)

def get_master_server_id(stack_name, config):
    # returns the physical id of the master server
    # if no master server returns []
    cfn = boto3.client('cloudformation', region_name=config.region,
                       aws_access_key_id=config.aws_access_key_id,
                       aws_secret_access_key=config.aws_secret_access_key)

    try:
        resources = cfn.describe_stack_resource(StackName=stack_name, LogicalResourceId='MasterServer')
        return resources.get('StackResourceDetail').get('PhysicalResourceId')
    except ClientError as e:
        logger.critical(e.response.get('Error').get('Message'))
        sys.exit(1)


def poll_master_server_state(stack_name, config):
    ec2 = boto3.client('ec2', region_name=config.region,
                       aws_access_key_id=config.aws_access_key_id,
                       aws_secret_access_key=config.aws_secret_access_key)

    master_id = get_master_server_id(stack_name, config)

    try:
        instance = ec2.describe_instance_status(InstanceIds=[master_id]).get('InstanceStatuses')[0]
        state = instance.get('InstanceState').get('Name')
        sys.stdout.write('\rMasterServer: %s' % state.upper())
        sys.stdout.flush()
        while state not in ['running', 'stopped', 'terminated', 'shutting-down']:
            time.sleep(5)
            state = ec2.describe_instance_status(InstanceIds=[master_id]).get('InstanceStatuses')[0].get('InstanceState').get('Name')
            status = ('\r\033[KMasterServer: %s' % state.upper())
            sys.stdout.write(status)
            sys.stdout.flush()
        if state in ['terminated', 'shutting-down']:
            logger.info("State: %s is irrecoverable. Cluster needs to be re-created.")
            sys.exit(1)
        status = ('\rMasterServer: %s\n' % state.upper())
        sys.stdout.write(status)
        sys.stdout.flush()
    except ClientError as e:
        logger.critical(e.response.get('Error').get('Message'))
        sys.stdout.flush()
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info('\nExiting...')
        sys.exit(0)

    return state

def get_master_server_ip(stack_name, config):
    ec2 = boto3.client('ec2', region_name=config.region,
                       aws_access_key_id=config.aws_access_key_id,
                       aws_secret_access_key=config.aws_secret_access_key)

    master_id = get_master_server_id(stack_name, config)

    try:
        instance = ec2.describe_instances(InstanceIds=[master_id]) \
            .get('Reservations')[0] \
            .get('Instances')[0]
        ip_address = instance.get('PublicIpAddress')
        state = instance.get('State').get('Name')
        if state != 'running' or ip_address is None:
            logger.info("MasterServer: %s\nCannot get ip address." % state.upper)
            sys.exit(1)
        return ip_address
    except ClientError as e:
        logger.critical(e.response.get('Error').get('Message'))
        sys.stdout.flush()
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info('\nExiting...')
        sys.exit(0)

def get_ec2_instances(stack, config):
    cfn = boto3.client('cloudformation', region_name=config.region,
                       aws_access_key_id=config.aws_access_key_id,
                       aws_secret_access_key=config.aws_secret_access_key)

    try:
        resources = cfn.describe_stack_resources(StackName=stack).get('StackResources')
    except ClientError as e:
        logger.critical(e.response.get('Error').get('Message'))
        sys.stdout.flush()
        sys.exit(1)

    temp_instances = [r for r in resources if r.get('ResourceType') == 'AWS::EC2::Instance']

    instances = []
    for instance in temp_instances:
        instances.append([instance.get('LogicalResourceId'),instance.get('PhysicalResourceId')])

    return instances

def get_asg_name(stack_name, config):
    cfn = boto3.client('cloudformation', region_name=config.region,
                       aws_access_key_id=config.aws_access_key_id,
                       aws_secret_access_key=config.aws_secret_access_key)
    try:
        resources = cfn.describe_stack_resources(StackName=stack_name).get('StackResources')
        return [r for r in resources if r.get('LogicalResourceId') == 'ComputeFleet'][0].get('PhysicalResourceId')
    except ClientError as e:
        logger.critical(e.response.get('Error').get('Message'))
        sys.stdout.flush()
        sys.exit(1)
    except IndexError:
        logger.critical("Stack %s does not have a ComputeFleet" % stack_name)
        sys.exit(1)

def set_asg_limits(asg_name, config, min, max, desired):
    asg = boto3.client('autoscaling', region_name=config.region,
                 aws_access_key_id=config.aws_access_key_id,
                 aws_secret_access_key=config.aws_secret_access_key)

    asg.update_auto_scaling_group(AutoScalingGroupName=asg_name, MinSize=min, MaxSize=max,
                                  DesiredCapacity=desired)

def get_asg_instances(stack, config):
    asg = boto3.client('autoscaling', region_name=config.region,
                       aws_access_key_id=config.aws_access_key_id,
                       aws_secret_access_key=config.aws_secret_access_key)

    asg_name = get_asg_name(stack, config)
    asg = asg.describe_auto_scaling_groups(AutoScalingGroupNames=[asg_name]).get('AutoScalingGroups')[0]
    name = [tag.get('Value') for tag in asg.get('Tags') if tag.get('Key') == 'aws:cloudformation:logical-id'][0]

    temp_instances = []
    for instance in asg.get('Instances'):
        temp_instances.append([name,instance.get('InstanceId')])

    return temp_instances

def instances(args):
    stack = ('cfncluster-' + args.cluster_name)

    config = cfnconfig.CfnClusterConfig(args)
    instances = []
    instances.extend(get_ec2_instances(stack, config))
    instances.extend(get_asg_instances(stack, config))

    for instance in instances:
        print('%s         %s' % (instance[0],instance[1]))

def get_head_user(parameters, template):
    mappings = template.get("TemplateBody") \
            .get("Mappings") \
            .get("OSFeatures")
    base_os =[i.get('ParameterValue') for i in parameters if i.get('ParameterKey') == "BaseOS"][0]
    return mappings.get(base_os).get("User")

def command(args, extra_args):
    stack = ('cfncluster-' + args.cluster_name)
    config = cfnconfig.CfnClusterConfig(args)
    if args.command in config.aliases:
        config_command = config.aliases[args.command]
    else:
        config_command = "ssh {CFN_USER}@{MASTER_IP} {ARGS}"

    cfn = boto3.client('cloudformation', region_name=config.region,
                       aws_access_key_id=config.aws_access_key_id,
                       aws_secret_access_key=config.aws_secret_access_key)
    try:
        status = cfn.describe_stacks(StackName=stack).get("Stacks")[0].get('StackStatus')
        invalid_status = ['DELETE_COMPLETE', 'DELETE_IN_PROGRESS']
        if status in invalid_status:
            logger.info("Stack status: %s. Cannot SSH while in %s" % (status, ' or '.join(invalid_status)))
            sys.exit(1)
        ip = get_master_server_ip(stack, config)
        stack_result = cfn.describe_stacks(StackName=stack).get('Stacks')[0]
        template = cfn.get_template(StackName=stack)
        username = get_head_user(stack_result.get('Parameters'), template)

        try:
            from shlex import quote as cmd_quote
        except ImportError:
            from pipes import quote as cmd_quote

        # build command
        cmd = config_command.format(CFN_USER=username, MASTER_IP=ip, ARGS=' '.join(cmd_quote(str(e)) for e in extra_args))

        # run command
        if not args.dryrun:
            os.system(cmd)
        else:
            logger.info(cmd)
    except ClientError as e:
            logger.critical(e.response.get('Error').get('Message'))
            sys.stdout.flush()
            sys.exit(1)
    except KeyboardInterrupt:
        logger.info('\nExiting...')
        sys.exit(0)

def status(args):
    stack = ('cfncluster-' + args.cluster_name)
    config = cfnconfig.CfnClusterConfig(args)

    cfn = boto3.client('cloudformation', region_name=config.region,
                       aws_access_key_id=config.aws_access_key_id,
                       aws_secret_access_key=config.aws_secret_access_key)

    try:
        status = cfn.describe_stacks(StackName=stack).get("Stacks")[0].get('StackStatus')
        sys.stdout.write('\rStatus: %s' % status)
        sys.stdout.flush()
        if not args.nowait:
            while status not in ['CREATE_COMPLETE', 'UPDATE_COMPLETE', 'UPDATE_ROLLBACK_COMPLETE',
                                 'ROLLBACK_COMPLETE', 'CREATE_FAILED', 'DELETE_FAILED']:
                time.sleep(5)
                status = cfn.describe_stacks(StackName=stack).get("Stacks")[0].get('StackStatus')
                events = cfn.describe_stack_events(StackName=stack).get('StackEvents')[0]
                resource_status = ('Status: %s - %s' % (events.get('LogicalResourceId'), events.get('ResourceStatus'))).ljust(80)
                sys.stdout.write('\r%s' % resource_status)
                sys.stdout.flush()
            sys.stdout.write('\rStatus: %s\n' % status)
            sys.stdout.flush()
            if status in ['CREATE_COMPLETE', 'UPDATE_COMPLETE']:
                state = poll_master_server_state(stack, config)
                if state == 'running':
                    outputs = cfn.describe_stacks(StackName=stack).get("Stacks")[0].get('Outputs', [])
                    for output in outputs:
                        logger.info("%s: %s" % (output.get('OutputKey'), output.get('OutputValue')))
            elif status in ['ROLLBACK_COMPLETE', 'CREATE_FAILED', 'DELETE_FAILED', 'UPDATE_ROLLBACK_COMPLETE']:
                events = cfn.describe_stack_events(StackName=stack).get('StackEvents')
                for event in events:
                    if event.get('ResourceStatus') in ['CREATE_FAILED', 'DELETE_FAILED', 'UPDATE_FAILED']:
                        logger.info("%s %s %s %s %s" %
                                    (event.get('Timestamp'), event.get('ResourceStatus'),
                                     event.get('ResourceType'), event.get('LogicalResourceId'),
                                     event.get('ResourceStatusReason')))
        else:
            sys.stdout.write('\n')
            sys.stdout.flush()
    except ClientError as e:
        logger.critical(e.response.get('Error').get('Message'))
        sys.stdout.flush()
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info('\nExiting...')
        sys.exit(0)

def delete(args):
    saw_update = False
    logger.info('Deleting: %s' % args.cluster_name)
    stack = ('cfncluster-' + args.cluster_name)

    config = cfnconfig.CfnClusterConfig(args)

    cfn = boto3.client('cloudformation', region_name=config.region,
                       aws_access_key_id=config.aws_access_key_id,
                       aws_secret_access_key=config.aws_secret_access_key)

    try:
        # delete_stack does not raise an exception if stack does not exist
        # Use describe_stacks to explicitly check if the stack exists
        cfn.describe_stacks(StackName=stack)
        cfn.delete_stack(StackName=stack)
        saw_update = True
        status = cfn.describe_stacks(StackName=stack).get("Stacks")[0].get('StackStatus')
        sys.stdout.write('\rStatus: %s' % status)
        sys.stdout.flush()
        logger.debug('Status: %s' % status)
        if not args.nowait:
            while status == 'DELETE_IN_PROGRESS':
                time.sleep(5)
                status = cfn.describe_stacks(StackName=stack).get("Stacks")[0].get('StackStatus')
                events = cfn.describe_stack_events(StackName=stack).get('StackEvents')[0]
                resource_status = ('Status: %s - %s' % (events.get('LogicalResourceId'), events.get('ResourceStatus'))).ljust(80)
                sys.stdout.write('\r%s' % resource_status)
                sys.stdout.flush()
            sys.stdout.write('\rStatus: %s\n' % status)
            sys.stdout.flush()
            logger.debug('Status: %s' % status)
        else:
            sys.stdout.write('\n')
            sys.stdout.flush()
        if status == 'DELETE_FAILED':
            logger.info('Cluster did not delete successfully. Run \'cfncluster delete %s\' again' % stack)
    except ClientError as e:
        if e.response.get('Error').get('Message').endswith("does not exist"):
            if saw_update:
                logger.info('\nCluster deleted successfully.')
                sys.exit(0)
        logger.critical(e.response.get('Error').get('Message'))
        sys.stdout.flush()
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info('\nExiting...')
        sys.exit(0)
