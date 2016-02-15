# Copyright 2013-2015 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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

import logging

log = logging.getLogger(__name__)

hostfile_path = 'sqswatcher.hosts'

def addHost(hostname,cluster_user):
    if hostname != None:
        log.info('Adding', hostname)
        hostfile = open(hostfile_path, 'a')
        print >> hostfile, hostname
        hostfile.close()

def removeHost(hostname,cluster_user):
    if hostname != None:
        log.info('Removing', hostname)
        hostfile = open(hostfile_path, 'r')
        lines = hostfile.readlines()
        hostfile.close()
        hostfile = open(hostfile_path, 'w')
        for line in lines:
            if line != hostname + '\n':
                hostfile.write(line)
        hostfile.close()
