#!/usr/bin/env python2.6

# Copyright 2013-2016 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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
import boto.ec2.autoscale
import os
import time
import sys
import tempfile
import logging

log = logging.getLogger(__name__)

def getConfig(instance_id):
    log.debug('reading /etc/nodewatcher.cfg')

    config = ConfigParser.RawConfigParser()
    config.read('/etc/nodewatcher.cfg')
    if config.has_option('nodewatcher', 'loglevel'):
        lvl = logging._levelNames[config.get('nodewatcher', 'loglevel')]
        logging.getLogger().setLevel(lvl)
    _region = config.get('nodewatcher', 'region')
    _scheduler = config.get('nodewatcher', 'scheduler')
    try:
        _asg = config.get('nodewatcher', 'asg')
    except ConfigParser.NoOptionError:
        conn = boto.ec2.connect_to_region(_region,proxy=boto.config.get('Boto', 'proxy'),
                                          proxy_port=boto.config.get('Boto', 'proxy_port'))
        _asg = conn.get_all_instances(instance_ids=instance_id)[0].instances[0].tags['aws:autoscaling:groupName']
        log.debug("discovered asg: %s" % _asg)
        config.set('nodewatcher', 'asg', _asg)

        tup = tempfile.mkstemp(dir=os.getcwd())
        fd = os.fdopen(tup[0], 'w')
        config.write(fd)
        fd.close

        os.rename(tup[1], 'nodewatcher.cfg')

    log.debug("region=%s asg=%s scheduler=%s" % (_region, _asg, _scheduler))
    return _region, _asg, _scheduler

def getHourPercentile(instance_id, conn):
    _reservations = conn.get_all_instances(instance_ids=[instance_id])
    _instance = _reservations[0].instances[0]
    _launch_time = dateutil.parser.parse(_instance.launch_time).replace(tzinfo=None)
    _current_time = datetime.utcnow()
    _delta = _current_time - _launch_time
    _delta_in_hours = _delta.seconds / 3600.0
    _hour_percentile = (_delta_in_hours % 1) * 100

    log.debug("launch=%s delta=%s percentile=%s" % (_launch_time, _delta,
                                                    _hour_percentile))

    return _hour_percentile

def getInstanceId():

    try:
        _instance_id = urllib2.urlopen("http://169.254.169.254/latest/meta-data/instance-id").read()
    except urllib2.URLError:
        log.critical('Unable to get instance-id from metadata')
        sys.exit(1)

    log.debug("instance_id=%s" % _instance_id)

    return _instance_id

def getHostname():

    try:
        _hostname = urllib2.urlopen("http://169.254.169.254/latest/meta-data/local-hostname").read()
    except urllib2.URLError:
        log.critical('Unable to get hostname from metadata')
        sys.exit(1)

    log.debug("hostname=%s" % _hostname)

    return _hostname

def loadSchedulerModule(scheduler):
    scheduler = 'nodewatcher.plugins.' + scheduler
    _scheduler = __import__(scheduler)
    _scheduler = sys.modules[scheduler]

    log.debug("scheduler=%s" % repr(_scheduler))

    return _scheduler

def getJobs(s,hostname):

    _jobs = s.getJobs(hostname)

    log.debug("jobs=%s" % _jobs)

    return _jobs

def lockHost(s,hostname,unlock=False):
    log.debug("%s %s" % (unlock and "unlocking" or "locking",
                         hostname))

    _r = s.lockHost(hostname, unlock)

    time.sleep(15) # allow for some settling

    return _r

def selfTerminate(region, asg, instance_id):
    _as_conn = boto.ec2.autoscale.connect_to_region(region,proxy=boto.config.get('Boto', 'proxy'),
                                          proxy_port=boto.config.get('Boto', 'proxy_port'))
    if not maintainSize(region, asg):
        log.info("terminating %s" % instance_id)
        _as_conn.terminate_instance(instance_id, decrement_capacity=True)

def maintainSize(region, asg):
    _as_conn = boto.ec2.autoscale.connect_to_region(region,proxy=boto.config.get('Boto', 'proxy'),
                                          proxy_port=boto.config.get('Boto', 'proxy_port'))
    _asg = _as_conn.get_all_groups(names=[asg])[0]
    _capacity = _asg.desired_capacity
    _min_size = _asg.min_size
    log.debug("capacity=%d min_size=%d" % (_capacity, _min_size))
    if _capacity > _min_size:
        log.debug('capacity greater then min size.')
        return False
    else:
        log.debug('capacity less then or equal to min size.')
        return True

def main():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s [%(module)s:%(funcName)s] %(message)s'
    )
    log.info("nodewatcher startup")
    instance_id = getInstanceId()
    hostname = getHostname()
    region, asg, scheduler = getConfig(instance_id)

    s = loadSchedulerModule(scheduler)

    while True:
        time.sleep(60)
        conn = boto.ec2.connect_to_region(region)
        hour_percentile = getHourPercentile(instance_id,conn)
        log.info('Percent of hour used: %d' % hour_percentile)

        if hour_percentile < 95:
            continue
        
        jobs = getJobs(s, hostname)
        if jobs == True:
            log.info('Instance has active jobs.')
        else:
            if maintainSize(region, asg):
                continue
            # avoid race condition by locking and verifying
            lockHost(s, hostname)
            jobs = getJobs(s, hostname)
            if jobs == True:
                log.info('Instance actually has active jobs.')
                lockHost(s, hostname, unlock=True)
                continue
            else:
                selfTerminate(region, asg, instance_id)

if __name__ == "__main__":
    main()
