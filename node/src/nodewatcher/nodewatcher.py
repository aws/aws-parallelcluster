#!/usr/bin/env python2.6

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

__author__ = 'dougalb'

from datetime import datetime
import boto.ec2
import dateutil.parser
import urllib2
import ConfigParser
import logging #http://docs.python.org/2/howto/logging.html
import boto.ec2.autoscale
import os
import sys
import tempfile

def getConfig(instance_id):
    print('running getConfig')

    config = ConfigParser.RawConfigParser()
    config.read('nodewatcher.cfg')
    _region = config.get('nodewatcher', 'region')
    _scheduler = config.get('nodewatcher', 'scheduler')
    try:
        _asg = config.get('nodewatcher', 'asg')
    except ConfigParser.NoOptionError:
        conn = boto.ec2.connect_to_region(_region)
        _asg = conn.get_all_instances(instance_ids=instance_id)[0].instances[0].tags['aws:autoscaling:groupName']
        config.set('nodewatcher', 'asg', _asg)

        tup = tempfile.mkstemp(dir=os.getcwd())
        fd = os.fdopen(tup[0], 'w')
        config.write(fd)
        fd.close

        os.rename(tup[1], 'nodewatcher.cfg')

    return _region, _asg, _scheduler

def getHourPercentile(instance_id, conn):
    print('running checkRunTime')

    _reservations = conn.get_all_instances(instance_ids=[instance_id])
    _instance = _reservations[0].instances[0]
    _launch_time = dateutil.parser.parse(_instance.launch_time).replace(tzinfo=None)
    _current_time = datetime.utcnow()
    _delta = _current_time - _launch_time
    _delta_in_hours = _delta.seconds / 3600.0
    _hour_percentile = (_delta_in_hours % 1) * 100

    return _hour_percentile

def getInstanceId():

    try:
        _instance_id = urllib2.urlopen("http://169.254.169.254/latest/meta-data/instance-id").read()
    except urllib2.URLError:
        print('Unable to get instance-id from metadata')
        sys.exit(1)

    return _instance_id

def getHostname():

    try:
        _hostname = urllib2.urlopen("http://169.254.169.254/latest/meta-data/local-hostname").read()
    except urllib2.URLError:
        print('Unable to get hostname from metadata')
        sys.exit(1)

    return _hostname

def loadSchedulerModule(scheduler):
    print 'running loadSchedulerModule'

    scheduler = 'plugins.' + scheduler
    _scheduler = __import__(scheduler)
    _scheduler = sys.modules[scheduler]

    return _scheduler

def getJobs(s,hostname):

    _jobs = s.getJobs(hostname)

    return _jobs


def selfTerminate(asg):
    _as_conn = boto.ec2.autoscale.connect_to_region(region)
    _asg = _as_conn.get_all_groups(names=[asg])[0]
    _capacity = _asg.desired_capacity
    if _capacity > 0:
        _as_conn.terminate_instance(instance_id, decrement_capacity=True)

if __name__ == "__main__":
    print('Running __main__')
    instance_id = getInstanceId()
    hostname = getHostname()
    region, asg, scheduler = getConfig(instance_id)

    s = loadSchedulerModule(scheduler)

    jobs = getJobs(s, hostname)
    print jobs
    if jobs == True:
        print('Instance has active jobs. Exiting')
        sys.exit(0)

    conn = boto.ec2.connect_to_region(region)
    hour_percentile = getHourPercentile(instance_id,conn)
    print('Percent of hour used: %d' % hour_percentile)

    if hour_percentile > 95:
        selfTerminate(asg)
