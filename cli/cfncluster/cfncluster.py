# Copyright 2013-2014 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Amazon Software License (the "License"). You may not use this file except in compliance with the
# License. A copy of the License is located at
#
# http://aws.amazon.com/asl/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.

import sys
import boto.cloudformation
import boto.ec2.autoscale
import boto.exception
import time
import os
import socket
import logging

import cfnconfig

logger = logging.getLogger('cfncluster.cfncluster')

def create(args):
    print('Starting: %s' % (args.cluster_name))

    config = cfnconfig.CfnClusterConfig(args)
    try:
        i = [p[0] for p in config.parameters].index('InitialQueueSize')
        initial_queue_size = config.parameters[i][1]
        config.parameters.append(('ComputeWaitConditionCount', initial_queue_size))
    except ValueError:
        pass

    capabilities = ["CAPABILITY_IAM"]
    cfnconn = boto.cloudformation.connect_to_region(config.region,aws_access_key_id=config.aws_access_key_id,
                                                    aws_secret_access_key=config.aws_secret_access_key)
    try:
        logger.debug((config.template_url, config.parameters))
        stack = cfnconn.create_stack(('cfncluster-' + args.cluster_name),template_url=config.template_url,
                                     parameters=config.parameters, capabilities=capabilities,
                                     disable_rollback=args.norollback, tags=args.tags)
        status = cfnconn.describe_stacks(stack)[0].stack_status
        if not args.nowait:
            while status == 'CREATE_IN_PROGRESS':
                status = cfnconn.describe_stacks(stack)[0].stack_status
                events = cfnconn.describe_stack_events(stack)[0]
                resource_status = ('Status: %s - %s' % (events.logical_resource_id, events.resource_status)).ljust(80)
                sys.stdout.write('\r%s' % resource_status)
                sys.stdout.flush()
                time.sleep(5)
            outputs = cfnconn.describe_stacks(stack)[0].outputs
            for output in outputs:
                print output
        else:
            status = cfnconn.describe_stacks(stack)[0].stack_status
            print('Status: %s' % status)
    except boto.exception.BotoServerError as e:
        print e.message
        sys.exit(1)
    except KeyboardInterrupt:
        print('\nExiting...')
        sys.exit(0)

def update(args):
    print('Updating: %s' % (args.cluster_name))
    stack_name = ('cfncluster-' + args.cluster_name)
    config = cfnconfig.CfnClusterConfig(args)
    capabilities = ["CAPABILITY_IAM"]
    cfnconn = boto.cloudformation.connect_to_region(config.region,aws_access_key_id=config.aws_access_key_id,
                                                    aws_secret_access_key=config.aws_secret_access_key)
    asgconn = boto.ec2.autoscale.connect_to_region(config.region,aws_access_key_id=config.aws_access_key_id,
                                                    aws_secret_access_key=config.aws_secret_access_key)
    if not args.reset_desired:
        temp_resources = []
        resources = cfnconn.describe_stack_resources(stack_name)
        while True:
            temp_resources.extend(resources)
            if not resources.next_token:
                break
            resources = cfnconn.describe_stack_resources(stack, next_token=resources.next_token)
        resources = temp_resources
        asg = [r for r in resources if r.logical_resource_id == 'ComputeFleet'][0].physical_resource_id

        desired_capacity = asgconn.get_all_groups(names=[asg])[0].desired_capacity
        config.parameters.append(('InitialQueueSize', desired_capacity))

    try:
        logger.debug((config.template_url, config.parameters))
        stack = cfnconn.update_stack(stack_name,template_url=config.template_url,
                                     parameters=config.parameters, capabilities=capabilities,
                                     disable_rollback=args.norollback)
        status = cfnconn.describe_stacks(stack)[0].stack_status
        if not args.nowait:
            while status == 'UPDATE_IN_PROGRESS':
                status = cfnconn.describe_stacks(stack)[0].stack_status
                events = cfnconn.describe_stack_events(stack)[0]
                resource_status = ('Status: %s - %s' % (events.logical_resource_id, events.resource_status)).ljust(80)
                sys.stdout.write('\r%s' % resource_status)
                sys.stdout.flush()
                time.sleep(5)
        else:
            status = cfnconn.describe_stacks(stack)[0].stack_status
            print('Status: %s' % status)
    except boto.exception.BotoServerError as e:
        print e.message
        sys.exit(1)
    except KeyboardInterrupt:
        print('\nExiting...')
        sys.exit(0)

def stop(args):
    ## The goal here is to a) stop scaling activities on a cluster
    ## b) stop all compute instances and then c) stop the master
    ## instance. Might also need to track somewhere that there is
    ## a stopped cluster, so that start can (start) it??
    print('Stopping: %s' % args.cluster_name)

def list(args):
    config = cfnconfig.CfnClusterConfig(args)
    cfnconn = boto.cloudformation.connect_to_region(config.region,aws_access_key_id=config.aws_access_key_id,
                                                    aws_secret_access_key=config.aws_secret_access_key)
    try:
        stacks = cfnconn.describe_stacks()
        for stack in stacks:
            if stack.stack_name.startswith('cfncluster-'):
                print('%s' % (stack.stack_name[11:]))
    except boto.exception.BotoServerError as e:
        if e.message.endswith("does not exist"):
            print e.message
        else:
            raise e
    except KeyboardInterrupt:
        print('Exiting...')
        sys.exit(0)

def get_ec2_instances(stack, config):
    cfnconn = boto.cloudformation.connect_to_region(config.region,aws_access_key_id=config.aws_access_key_id,
                                                    aws_secret_access_key=config.aws_secret_access_key)

    temp_resources = []

    while True:
        try:
            resources = cfnconn.describe_stack_resources(stack)
        except boto.exception.BotoServerError as e:
            if e.message.endswith("does not exist"):
                #sys.stdout.write('\r\n')
                print e.message
                sys.stdout.flush()
                sys.exit(0)
            else:
                raise e
        temp_resources.extend(resources)
        if not resources.next_token:
            break
        resources = cfnconn.describe_stack_resources(stack, next_token=resources.next_token)

    resources = temp_resources
    temp_instances = [r for r in resources if r.resource_type == 'AWS::EC2::Instance']

    instances = []
    for instance in temp_instances:
        instances.append([instance.logical_resource_id,instance.physical_resource_id])

    return instances

def get_asg_instances(stack, config):
    cfnconn = boto.cloudformation.connect_to_region(config.region,aws_access_key_id=config.aws_access_key_id,
                                                    aws_secret_access_key=config.aws_secret_access_key)
    asgconn = boto.ec2.autoscale.connect_to_region(config.region,aws_access_key_id=config.aws_access_key_id,
                                                    aws_secret_access_key=config.aws_secret_access_key)

    temp_resources = []

    while True:
        try:
            resources = cfnconn.describe_stack_resources(stack)
        except boto.exception.BotoServerError as e:
            if e.message.endswith("does not exist"):
                #sys.stdout.write('\r\n')
                print e.message
                sys.stdout.flush()
                sys.exit(0)
            else:
                raise e
        temp_resources.extend(resources)
        if not resources.next_token:
            break
        resources = cfnconn.describe_stack_resources(stack, next_token=resources.next_token)

    resources = temp_resources
    temp_asgs = [r for r in resources if r.resource_type == 'AWS::AutoScaling::AutoScalingGroup']

    asgs = []
    for asg in temp_asgs:
        asgs.append([asg.logical_resource_id,asg.physical_resource_id])

    temp_instances = []
    for asg in asgs:
        instances = asgconn.get_all_groups(names=[asg[1]])[0].instances
        for instance in instances:
            temp_instances.append([asg[0],instance.instance_id])

    return temp_instances

def instances(args):
    stack = ('cfncluster-' + args.cluster_name)
    config = cfnconfig.CfnClusterConfig(args)
    instances = []
    instances.extend(get_ec2_instances(stack, config))
    instances.extend(get_asg_instances(stack, config))

    for instance in instances:
        print('%s         %s' % (instance[0],instance[1]))

def status(args):
    stack = ('cfncluster-' + args.cluster_name)
    config = cfnconfig.CfnClusterConfig(args)
    cfnconn = boto.cloudformation.connect_to_region(config.region,aws_access_key_id=config.aws_access_key_id,
                                                    aws_secret_access_key=config.aws_secret_access_key)

    try:
        status = cfnconn.describe_stacks(stack)[0].stack_status
        sys.stdout.write('\rStatus: %s' % status)
        sys.stdout.flush()
        if not args.nowait:
            while ((status != 'CREATE_COMPLETE') and (status != 'UPDATE_COMPLETE') and (status != 'ROLLBACK_COMPLETE')):
                time.sleep(5)
                status = cfnconn.describe_stacks(stack)[0].stack_status
                events = cfnconn.describe_stack_events(stack)[0]
                resource_status = ('Status: %s - %s' % (events.logical_resource_id, events.resource_status)).ljust(80)
                sys.stdout.write('\r%s' % resource_status)
                sys.stdout.flush()
            sys.stdout.write('\rStatus: %s\n' % status)
            sys.stdout.flush()
            if ((status == 'CREATE_COMPLETE') or (status == 'UPDATE_COMPLETE')):
                outputs = cfnconn.describe_stacks(stack)[0].outputs
                for output in outputs:
                    print output
        else:
            sys.stdout.write('\n')
            sys.stdout.flush()
    except boto.exception.BotoServerError as e:
        if e.message.endswith("does not exist"):
            sys.stdout.write('\r')
            print e.message
            sys.stdout.flush()
            sys.exit(0)
        else:
            raise e
    except KeyboardInterrupt:
        print('\nExiting...')
        sys.exit(0)


def delete(args):
    print('Terminating: %s' % args.cluster_name)
    stack = ('cfncluster-' + args.cluster_name)

    config = cfnconfig.CfnClusterConfig(args)
    cfnconn = boto.cloudformation.connect_to_region(config.region,aws_access_key_id=config.aws_access_key_id,
                                                    aws_secret_access_key=config.aws_secret_access_key)
    try:
        cfnconn.delete_stack(stack)
        status = cfnconn.describe_stacks(stack)[0].stack_status
        sys.stdout.write('\rStatus: %s' % status)
        sys.stdout.flush()
        if not args.nowait:
            while status == 'DELETE_IN_PROGRESS':
                time.sleep(5)
                status = cfnconn.describe_stacks(stack)[0].stack_status
                events = cfnconn.describe_stack_events(stack)[0]
                resource_status = ('Status: %s - %s' % (events.logical_resource_id, events.resource_status)).ljust(80)
                sys.stdout.write('\r%s' % resource_status)
                sys.stdout.flush()
            sys.stdout.write('\rStatus: %s\n' % status)
            sys.stdout.flush()
        else:
            sys.stdout.write('\n')
            sys.stdout.flush()
        if status == 'DELETE_FAILED':
            print('Cluster did not delete successfully. Run \'cluster delete %s\' again' % stack)
    except boto.exception.BotoServerError as e:
        if e.message.endswith("does not exist"):
            #sys.stdout.write('\r\n')
            print e.message
            sys.stdout.flush()
            sys.exit(0)
        else:
            raise e
    except KeyboardInterrupt:
        print('\nExiting...')
        sys.exit(0)

