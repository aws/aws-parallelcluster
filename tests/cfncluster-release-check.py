#!/usr/bin/python
#
# Copyright 2018      Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You
# may not use this file except in compliance with the License. A copy
# of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is
# distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF
# ANY KIND, express or implied. See the License for the specific
# language governing permissions and limitations under the License.
#
#
# Build a cluster for each combination of region, base_os, and
# scheduler, and run a test script on each cluster.  To avoid bouncing
# against limits in each region, the number of simultaneously built
# clusters in each region is a configuration parameter.
#
# NOTE:
# - This script requires python2
# - To simplify this script, at least one subnet in every region
#   to be tested must have a resource tag named "CfnClusterTestSubnet"
#   (value does not matter). That subnet will be used as the launch
#   target for the cluster.

import os
import sys
import subprocess
import threading
import re
import argparse
import Queue
import boto3

#
# configuration
#
username_map = { 'alinux' : 'ec2-user',
                 'centos6' : 'centos',
                 'centos7' : 'centos',
                 'ubuntu1404' : 'ubuntu',
                 'ubuntu1604' : 'ubuntu' }

#
# global variables (sigh)
#
setup = {}

results_lock = threading.Lock()
failure = 0
success = 0


#
# run a single test, possibly in parallel
#
def run_test(region, distro, scheduler, key_name):
    testname = '%s-%s-%s' % (region, distro, scheduler)
    test_filename = "config-%s.cfg" % (testname)

    sys.stdout.write("--> %s: Starting\n" % (testname))

    file = open(test_filename, "w")
    file.write("[aws]\n")
    file.write("aws_region_name = %s\n" % region)
    file.write("[cluster default]\n")
    file.write("vpc_settings = public\n")
    file.write("key_name = %s\n" % key_name)
    file.write("base_os = %s\n" % distro)
    file.write("master_instance_type = c4.xlarge\n")
    file.write("compute_instance_type = c4.xlarge\n")
    file.write("initial_queue_size = 2\n")
    file.write("maintain_initial_size = true\n")
    file.write("scheduler = %s\n" % (scheduler))
    file.write("scaling_settings = custom\n")
    file.write("[vpc public]\n")
    file.write("master_subnet_id = %s\n" % (setup[region]['subnet']))
    file.write("vpc_id = %s\n" % (setup[region]['vpc']))
    file.write("[global]\n")
    file.write("cluster_template = default\n")
    file.write("[scaling custom]\n")
    file.write("scaling_adjustment = 2\n")
    file.close()

    stdout_f = open('stdout-%s.txt' % (testname), 'w')
    stderr_f = open('stderr-%s.txt' % (testname), 'w')

    master_ip = ''
    username = username_map[distro]

    try:
        # build the cluster
        subprocess.check_call(['cfncluster', '--config', test_filename,
                               'create', testname],
                              stdout=stdout_f, stderr=stderr_f)

        # get the master ip, which means grepping through cfncluster status gorp
        dump = subprocess.check_output(['cfncluster', 'status', testname], stderr=stderr_f)
        dump_array = dump.splitlines()
        for line in dump_array:
            m = re.search('MasterPublicIP"="(.+?)"', line)
            if m:
                master_ip = m.group(1)
                break
        if master_ip == '':
            print('!! %s: Master IP not found; aborting !!' % (testname))
            raise Exception('Master IP not found')
        print("--> %s master ip: %s" % (testname, master_ip))

        # run test on the cluster...
        subprocess.check_call(['scp', '-o', 'StrictHostKeyChecking=no',
                               'cluster-check.sh', '%s@%s:.' % (username, master_ip)],
                              stdout=stdout_f, stderr=stderr_f)
        subprocess.check_call(['ssh', '-o', 'StrictHostKeyChecking=no',
                               '%s@%s' % (username, master_ip),
                               '/bin/bash cluster-check.sh %s' % (scheduler)],
                              stdout=stdout_f, stderr=stderr_f)
    except Exception as e:
        sys.stdout.write("!! FAILURE: %s!!\n" % (testname))
        raise e

    finally:
        # clean up the cluster
        subprocess.call(['cfncluster', '--config', test_filename, 'delete', testname],
                        stdout=stdout_f, stderr=stderr_f)
        stdout_f.close()
        stderr_f.close()
        os.remove(test_filename)


#
# worker thread, there will be config['parallelism'] of these running
# per region, dispatching work from the work queue
#
def test_runner(region, q, key_name):
    global success
    global failure
    global results_lock

    while True:
        item = q.get()

        # just in case we miss an exception in run_test, don't abort everything...
        try:
            run_test(region=region, distro=item['distro'], scheduler=item['scheduler'], key_name=key_name)
            retval = 0
        except Exception as e:
            print("Unexpected exception %s: %s" % (str(type(e)), str((e))))
            retval = 1

        results_lock.acquire(True)
        if retval == 0:
            success += 1
        else:
            failure += 1
        results_lock.release()
        q.task_done()


if __name__ == '__main__':
    config = { 'parallelism' : 3,
               'regions' : 'us-east-1,us-east-2,us-west-1,us-west-2,' +
                           'ca-central-1,eu-west-1,eu-west-2,eu-central-1,' +
                           'ap-southeast-1,ap-southeast-2,ap-northeast-1,' +
                           'ap-south-1,sa-east-1,eu-west-3',
               'distros' : 'alinux,centos6,centos7,ubuntu1404,ubuntu1604',
               'schedulers' : 'sge,slurm,torque' }

    parser = argparse.ArgumentParser(description = 'Test runner for CfnCluster')
    parser.add_argument('--parallelism', help = 'Number of tests per region to run in parallel',
                        type = int, default = 3)
    parser.add_argument('--regions', help = 'Comma separated list of regions to test',
                        type = str)
    parser.add_argument('--distros', help = 'Comma separated list of distributions to test',
                        type = str)
    parser.add_argument('--schedulers', help = 'Comma separated list of schedulers to test',
                        type = str)
    parser.add_argument('--key-name', help='Key Pair to use for SSH connections',
                        type = str)

    for key, value in vars(parser.parse_args()).iteritems():
        if not value == None:
            config[key] = value

    region_list = config['regions'].split(',')
    distro_list = config['distros'].split(',')
    scheduler_list = config['schedulers'].split(',')

    print("==> Regions: %s" % (', '.join(region_list)))
    print("==> Distros: %s" % (', '.join(distro_list)))
    print("==> Schedulers: %s" % (', '.join(scheduler_list)))
    print("==> Key Pair: %s" % (config['key_name']))
    print("==> Parallelism: %d" % (config['parallelism']))

    # Populate subnet / vpc data for all regions we're going to test.
    for region in region_list:
        client = boto3.client('ec2', region_name=region)
        response = client.describe_tags(Filters=[{'Name': 'key',
                                                  'Values': [ 'CfnClusterTestSubnet' ]}],
                                        MaxResults=16)
        if len(response['Tags']) == 0:
            print('Could not find subnet in %s with CfnClusterTestSubnet tag.  Aborting.' %
                  (region))
            exit(1)
        subnetid = response['Tags'][0]['ResourceId']

        response = client.describe_subnets(SubnetIds = [ subnetid ])
        if len(response) == 0:
            print('Could not find subnet info for %s' % (subnetid))
            exit(1)
        vpcid = response['Subnets'][0]['VpcId']

        setup[region] = { 'vpc' : vpcid, 'subnet' : subnetid }


    work_queues = {}
    # build up a per-region list of work to do
    for region in region_list:
        work_queues[region] = Queue.Queue()
        for distro in distro_list:
            for scheduler in scheduler_list:
                work_item = { 'distro' : distro, 'scheduler' : scheduler }
                work_queues[region].put(work_item)

    # start all the workers
    for region in region_list:
        for i in range(0, config['parallelism']):
            t = threading.Thread(target = test_runner, args=(region, work_queues[region], config['key_name']))
            t.daemon = True
            t.start()

    # wait for all the work queues to be completed in each region
    for region in region_list:
        work_queues[region].join()

    # print status...
    print("==> Success: %d" % (success))
    print("==> Failure: %d" % (failure))
