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

import subprocess as sub
import os
import paramiko

def __runOpenlavaCommand(command):
    _command = command
    try:
        sub.check_call(_command, env=dict(os.environ, LSF_ENVDIR='/opt/openlava-2.2/etc'))
    except sub.CalledProcessError:
        print ("Failed to run %s\n" % _command)


def addHost(hostname, cluster_user):
    print('Adding %s', hostname)

    command = ['/opt/openlava-2.2/bin/lsaddhost', '-t', 'linux', '-m', 'IntelXeon', hostname]

    __runOpenlavaCommand(command)

    # Connect and hostkey
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    hosts_key_file = '/home/' + cluster_user + '/.ssh/known_hosts'
    user_key_file = '/home/' + cluster_user + '/.ssh/id_rsa'
    iter=0
    connected=False
    while iter < 3 and connected == False:
        try:
            print('Connecting to host: %s iter: %d' % (hostname, iter))
            ssh.connect(hostname, username=cluster_user, key_filename=user_key_file)
            connected=True
        except socket.error, e:
            print('Socket error: %s' % e)
            time.sleep(10 + iter)
            iter = iter + 1
            if iter == 3:
               print("Unable to provison host")
               return
    try:
        ssh.load_host_keys(hosts_key_file)
    except IOError:
        ssh._host_keys_filename = None
        pass
    ssh.save_host_keys(hosts_key_file)
    ssh.close()

def removeHost(hostname,cluster_user):
    print('Removing %s', hostname)

    command = ['/opt/openlava-2.2/bin/lsrmhost', hostname]

    __runOpenlavaCommand(command)
