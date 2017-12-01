from __future__ import print_function
from __future__ import absolute_import
# Copyright 2013-2014 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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
import boto.cloudformation
import boto.ec2.autoscale
import boto.vpc
import boto.exception
import time
import os
import socket
import logging

from . import cfnconfig

def version(args):
    config = cfnconfig.CfnClusterConfig(args)
    print(config.version)

def create(args):
    logger = logging.getLogger('cfncluster.cfncluster.create')
    logger.info('Beginning cluster creation for cluster: %s' % (args.cluster_name))

    logger.debug('Building cluster config based on args')
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
            vpcconn = boto.vpc.connect_to_region(config.region,aws_access_key_id=config.aws_access_key_id,
                                                 aws_secret_access_key=config.aws_secret_access_key)
            availability_zone = str(vpcconn.get_all_subnets(subnet_ids=master_subnet_id)[0].availability_zone)
        except Exception as e:
            logger.critical(e.message)
            sys.exit(1)
        config.parameters.append(('AvailabilityZone', availability_zone))
    except ValueError:
        pass



    capabilities = ["CAPABILITY_IAM"]
    try:
        cfnconn = boto.cloudformation.connect_to_region(config.region,aws_access_key_id=config.aws_access_key_id,
                                                        aws_secret_access_key=config.aws_secret_access_key)
    except Exception as e:
        logger.critical(e.message)
        sys.exit(1)




    try:
        stack_name = 'cfncluster-' + args.cluster_name
        logger.info("Creating stack named: " + stack_name)
        stack = cfnconn.create_stack(stack_name,template_url=config.template_url,
                                     parameters=config.parameters, capabilities=capabilities,
                                     disable_rollback=args.norollback, tags=config.tags)
        logger.info("foo")
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
                print(output)
        else:
            status = cfnconn.describe_stacks(stack)[0].stack_status
            print('Status: %s' % status)
    except KeyboardInterrupt:
        print('\nExiting...')
        sys.exit(0)
    except Exception as e:
        logger.critical(e.message)
        sys.exit(1)


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

    # Get the MasterSubnetId and use it to determine AvailabilityZone
    try:
        i = [p[0] for p in config.parameters].index('MasterSubnetId')
        master_subnet_id = config.parameters[i][1]
        try:
            vpcconn = boto.vpc.connect_to_region(config.region,aws_access_key_id=config.aws_access_key_id,
                                                 aws_secret_access_key=config.aws_secret_access_key)
            availability_zone = str(vpcconn.get_all_subnets(subnet_ids=master_subnet_id)[0].availability_zone)
        except boto.exception.BotoServerError as e:
            print(e.message)
            sys.exit(1)
        config.parameters.append(('AvailabilityZone', availability_zone))
    except ValueError:
        pass

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
        print(e.message)
        sys.exit(1)
    except KeyboardInterrupt:
        print('\nExiting...')
        sys.exit(0)

def start(args):
    # Set resource limits on compute fleet to min/max/desired = 0/max/0
    print('Starting compute fleet : %s' % args.cluster_name)
    stack_name = ('cfncluster-' + args.cluster_name)
    config = cfnconfig.CfnClusterConfig(args)
    
    # Set asg limits
    max_queue_size = [param[1] for param in config.parameters if param[0] == 'MaxQueueSize']
    max_queue_size = max_queue_size[0] if len(max_queue_size) > 0 else 10
    desired_queue_size = [param[1] for param in config.parameters if param[0] == 'InitialQueueSize']
    desired_queue_size = desired_queue_size[0] if len(desired_queue_size) > 0 else 2
    min_queue_size = [desired_queue_size for param in config.parameters if param[0] == 'MaintainInitialSize' and param[1] == "true"]
    min_queue_size = min_queue_size[0] if len(min_queue_size) > 0 else 0

    asg = get_asg(stack_name=stack_name, config=config)
    set_asg_limits(asg=asg, min=min_queue_size, max=max_queue_size, desired=desired_queue_size)

def stop(args):
    # Set resource limits on compute fleet to min/max/desired = 0/0/0
    print('Stopping compute fleet : %s' % args.cluster_name)
    stack_name = ('cfncluster-' + args.cluster_name)
    config = cfnconfig.CfnClusterConfig(args)

    # Set Resource limits
    asg = get_asg(stack_name=stack_name, config=config)
    set_asg_limits(asg=asg, min=0, max=0, desired=0)

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
            print(e.message)
        else:
            raise e
    except KeyboardInterrupt:
        print('Exiting...')
        sys.exit(0)

def get_master_server_id(stack_name, config):
    # returns the physical id of the master server
    # if no master server returns []
    cfnconn = boto.cloudformation.connect_to_region(config.region,aws_access_key_id=config.aws_access_key_id,
                                                    aws_secret_access_key=config.aws_secret_access_key)
    temp_resources = []

    while True:
        try:
            resources = cfnconn.describe_stack_resources(stack_name)
        except boto.exception.BotoServerError as e:
            if e.message.endswith("does not exist"):
                print(e.message)
                sys.stdout.flush()
                sys.exit(0)
            else:
                raise e
        temp_resources.extend(resources)
        if not resources.next_token:
            break
        resources = cfnconn.describe_stack_resources(stack, next_token=resources.next_token)

    return [r.physical_resource_id for r in resources if r.logical_resource_id == 'MasterServer'][0]

def poll_master_server_state(stack_name, config):
    ec2conn = boto.ec2.connect_to_region(config.region,aws_access_key_id=config.aws_access_key_id,
                                                    aws_secret_access_key=config.aws_secret_access_key)

    master_id = get_master_server_id(stack_name, config)

    try:
        instance = ec2conn.get_only_instances(instance_ids=[master_id])[0]
        state = instance.state
        sys.stdout.write('\rMasterServer: %s' % state.upper())
        sys.stdout.flush()
        while (state != 'running' and state != 'stopped' and state != 'terminated' and state != 'shutting-down'):
            time.sleep(5)
            state = instance.update()
            status = ('\r\033[KMasterServer: %s' % state.upper())
            sys.stdout.write(status)
            sys.stdout.flush()
        if (state == 'terminated' or state == 'shutting-down'):
            print("State: %s is irrecoverable. Cluster needs to be re-created.")
            sys.exit(1)
        status = ('\rMasterServer: %s\n' % state.upper())
        sys.stdout.write(status)
        sys.stdout.flush()
    except boto.exception.BotoServerError as e:
        if e.message.endswith("does not exist"):
            print(e.message)
            sys.stdout.flush()
            sys.exit(0)
        else:
            raise e
    except KeyboardInterrupt:
        print('\nExiting...')
        sys.exit(0)

    return state

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
                print(e.message)
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

def get_asg(stack_name, config):
    # Gets the id of the Autoscaling group
    # Assumes only one Autoscaling Group
    asgconn = boto.ec2.autoscale.connect_to_region(config.region,aws_access_key_id=config.aws_access_key_id,
                                                    aws_secret_access_key=config.aws_secret_access_key)
    asg_ids = get_asg_ids(stack_name, config)
    asg_id = [asg[1] for asg in asg_ids if asg[0] == 'ComputeFleet'][0]

    try:
        return asgconn.get_all_groups(names=[asg_id])[0]
    except boto.exception.BotoServerError as e:
        if e.message.endswith("does not exist"):
            print(e.message)
            sys.stdout.flush()
            sys.exit(0)
        else:
            raise e
    except KeyboardInterrupt:
        print('\nExiting...')
        sys.exit(0)

def set_asg_limits(asg, min, max, desired):
    asg.max_size = max
    asg.min_size = min
    asg.desired_capacity = desired
    try:
        return asg.update()
    except:
        raise e

def get_asg_ids(stack, config):
    cfnconn = boto.cloudformation.connect_to_region(config.region,aws_access_key_id=config.aws_access_key_id,
                                                    aws_secret_access_key=config.aws_secret_access_key)

    temp_resources = []
    while True:
        try:
            resources = cfnconn.describe_stack_resources(stack)
        except boto.exception.BotoServerError as e:
            if e.message.endswith("does not exist"):
                #sys.stdout.write('\r\n')
                print(e.message)
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

    asg_ids = []
    for asg in temp_asgs:
        asg_ids.append([asg.logical_resource_id,asg.physical_resource_id])

    return asg_ids

def get_asg_instances(stack, config):
    asgconn = boto.ec2.autoscale.connect_to_region(config.region,aws_access_key_id=config.aws_access_key_id,
                                                    aws_secret_access_key=config.aws_secret_access_key)

    asgs = get_asg_ids(stack, config)

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
            while ((status != 'CREATE_COMPLETE') and (status != 'UPDATE_COMPLETE') and (status != 'UPDATE_ROLLBACK_COMPLETE')
                   and (status != 'ROLLBACK_COMPLETE') and (status != 'CREATE_FAILED') and (status != 'DELETE_FAILED')):
                time.sleep(5)
                status = cfnconn.describe_stacks(stack)[0].stack_status
                events = cfnconn.describe_stack_events(stack)[0]
                resource_status = ('Status: %s - %s' % (events.logical_resource_id, events.resource_status)).ljust(80)
                sys.stdout.write('\r%s' % resource_status)
                sys.stdout.flush()
            sys.stdout.write('\rStatus: %s\n' % status)
            sys.stdout.flush()
            if ((status == 'CREATE_COMPLETE') or (status == 'UPDATE_COMPLETE')):
                state = poll_master_server_state(stack, config)
                if state == 'running':
                    outputs = cfnconn.describe_stacks(stack)[0].outputs
                    for output in outputs:
                        print(output)
            elif ((status == 'ROLLBACK_COMPLETE') or (status == 'CREATE_FAILED') or (status == 'DELETE_FAILED') or
                      (status == 'UPDATE_ROLLBACK_COMPLETE')):
                events = cfnconn.describe_stack_events(stack)
                for event in events:
                    if ((event.resource_status == 'CREATE_FAILED') or (event.resource_status == 'DELETE_FAILED') or
                            (event.resource_status == 'UPDATE_FAILED')):
                        print(event.timestamp, event.resource_status, event.resource_type, event.logical_resource_id, \
                            event.resource_status_reason)
        else:
            sys.stdout.write('\n')
            sys.stdout.flush()
    except boto.exception.BotoServerError as e:
        if e.message.endswith("does not exist"):
            sys.stdout.write('\r')
            print(e.message)
            sys.stdout.flush()
            sys.exit(0)
        else:
            raise e
    except KeyboardInterrupt:
        print('\nExiting...')
        sys.exit(0)

def delete(args):
    print('Deleting: %s' % args.cluster_name)
    stack = ('cfncluster-' + args.cluster_name)

    config = cfnconfig.CfnClusterConfig(args)
    cfnconn = boto.cloudformation.connect_to_region(config.region,aws_access_key_id=config.aws_access_key_id,
                                                    aws_secret_access_key=config.aws_secret_access_key)
    try:
        cfnconn.delete_stack(stack)
        if not args.nowait:
            time.sleep(5)
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
            print(e.message)
            sys.stdout.flush()
            sys.exit(0)
        else:
            raise e
    except KeyboardInterrupt:
        print('\nExiting...')
        sys.exit(0)

