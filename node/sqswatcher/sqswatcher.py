#!/usr/bin/env python
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

import json
import time
import sys
import ConfigParser

import boto.sqs
import boto.ec2
import boto.dynamodb
import boto.dynamodb2
import boto.dynamodb2.exceptions
import boto.exception
from boto.sqs.message import RawMessage
from boto.dynamodb2.fields import HashKey
from boto.dynamodb2.table import Table


def getConfig():
    print('running getConfig')

    config = ConfigParser.RawConfigParser()
    config.read('/etc/sqswatcher.cfg')
    _region = config.get('sqswatcher', 'region')
    _sqsqueue = config.get('sqswatcher', 'sqsqueue')
    _table_name = config.get('sqswatcher', 'table_name')
    _scheduler = config.get('sqswatcher', 'scheduler')
    _cluster_user = config.get('sqswatcher', 'cluster_user')

    return _region, _sqsqueue, _table_name, _scheduler, _cluster_user


def setupQueue(region, sqsqueue):
    print('running setupQueue')

    conn = boto.sqs.connect_to_region(region,proxy=boto.config.get('Boto', 'proxy'),
                                          proxy_port=boto.config.get('Boto', 'proxy_port'))

    _q = conn.get_queue(sqsqueue)
    if _q != None:
        _q.set_message_class(RawMessage)
    return _q


def setupDDBTable(region, table_name):
    print('running setupDDBTable')

    conn = boto.dynamodb.connect_to_region(region,proxy=boto.config.get('Boto', 'proxy'),
                                          proxy_port=boto.config.get('Boto', 'proxy_port'))
    tables = conn.list_tables()
    check = [t for t in tables if t == table_name]
    conn = boto.dynamodb2.connect_to_region(region,proxy=boto.config.get('Boto', 'proxy'),
                                          proxy_port=boto.config.get('Boto', 'proxy_port'))
    if check:
        _table = Table(table_name,connection=conn)
    else:
        _table = Table.create(table_name,
                              schema=[HashKey('instanceId')
                              ],connection=conn)

    return _table


def loadSchedulerModule(scheduler):
    print 'running loadSchedulerModule'

    scheduler = 'sqswatcher.plugins.' + scheduler
    _scheduler = __import__(scheduler)
    _scheduler = sys.modules[scheduler]

    return _scheduler


def pollQueue(scheduler, q, t):
    print 'running pollQueue'
    s = loadSchedulerModule(scheduler)

    while True:

        results = q.get_messages(10)

        while len(results) > 0:

            for result in results:
                message = json.loads(result.get_body())
                message_attrs = json.loads(message['Message'])
                eventType = message_attrs['Event']

                if eventType == 'autoscaling:TEST_NOTIFICATION':
                    print eventType
                    q.delete_message(result)

                if eventType != 'autoscaling:TEST_NOTIFICATION':
                    instanceId = message_attrs['EC2InstanceId']
                    if eventType == 'cfncluster:COMPUTE_READY':
                        print eventType, instanceId

                        ec2 = boto.connect_ec2()
                        ec2 = boto.ec2.connect_to_region(region,proxy=boto.config.get('Boto', 'proxy'),
                                          proxy_port=boto.config.get('Boto', 'proxy_port'))

                        retry = 0
                        wait = 15
                        while retry < 3:
                            try:
                                hostname = ec2.get_all_instances(instance_ids=instanceId)

                                if not hostname:
                                    print "Unable to find running instance %s." % instanceId
                                else:
				    print "Adding Hostname: %s" % hostname
                                    hostname = hostname[0].instances[0].private_dns_name.split('.')[:1][0]
                                    s.addHost(hostname,cluster_user)

                                    t.put_item(data={
                                        'instanceId': instanceId,
                                        'hostname': hostname
                                    })

				q.delete_message(result)
                                break
                            except boto.exception.BotoServerError as e:
                                if e.error_code == 'RequestLimitExceeded':
                                    time.sleep(wait)
                                    retry += 1
                                    wait = (wait*2+retry)
                                else:
                                    raise e
                            except:
                                print "Unexpected error:", sys.exc_info()[0]
                                raise

                    elif eventType == 'autoscaling:EC2_INSTANCE_TERMINATE':
                        print eventType, instanceId

                        try:
                            item = t.get_item(consistent=True, instanceId=instanceId)
                            hostname = item['hostname']

                            if hostname:
                                s.removeHost(hostname,cluster_user)

                            item.delete()

                        except boto.dynamodb2.exceptions.ItemNotFound:
                            print ("Did not find %s in the metadb\n" % instanceId)
                        except:
                            print "Unexpected error:", sys.exc_info()[0]
                            raise

                        q.delete_message(result)

            results = q.get_messages(10)

        time.sleep(30)

def main():
    print('running __main__')
    print time.ctime()
    global region, cluster_user
    region, sqsqueue, table_name, scheduler, cluster_user = getConfig()
    q = setupQueue(region, sqsqueue)
    t = setupDDBTable(region, table_name)
    pollQueue(scheduler, q, t)

if __name__ == "__main__":
    main()
