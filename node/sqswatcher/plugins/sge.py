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
import paramiko
from tempfile import NamedTemporaryFile
import time
import os
import socket

def __runSgeCommand(command):
    _command = command
    try:
        sub.check_call(_command, env=dict(os.environ, SGE_ROOT='/opt/sge'))
    except sub.CalledProcessError:
        print ("Failed to run %s\n" % _command)

def addHost(hostname, cluster_user):
    print('Adding %s', hostname)

    # Adding host as administrative host
    command = ['/opt/sge/bin/lx-amd64/qconf', '-ah', hostname]
    __runSgeCommand(command)

    # Setup template to add execution host
    qconf_Ae_template = """hostname              %s
load_scaling          NONE
complex_values        NONE
user_lists            NONE
xuser_lists           NONE
projects              NONE
xprojects             NONE
usage_scaling         NONE
report_variables      NONE
"""

    with NamedTemporaryFile() as t:
        temp_template = open(t.name,'w')
        temp_template.write(qconf_Ae_template % hostname)
        temp_template.flush()
        os.fsync(t.fileno())

        # Add host as an execution host
        command = ['/opt/sge/bin/lx-amd64/qconf', '-Ae', t.name]
        __runSgeCommand(command)

    # Connect and start SGE
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
    command = "sudo sh -c \'cd /opt/sge && /opt/sge/inst_sge -x -auto /opt/cfncluster/templates/sge/sge_inst.conf\'"
    stdin, stdout, stderr = ssh.exec_command(command)
    ssh.close()

def removeHost(hostname,cluster_user):
    print('Removing %s', hostname)

    # Purge hostname from all.q
    command = ['/opt/sge/bin/lx-amd64/qconf', '-purge', 'queue', '*', 'all.q@%s' % hostname]
    __runSgeCommand(command)

    # Remove host from @allhosts group
    command = ['/opt/sge/bin/lx-amd64/qconf', '-dattr', 'hostgroup', 'hostlist', hostname, '@allhosts']
    __runSgeCommand(command)

    # Removing host as execution host
    command = ['/opt/sge/bin/lx-amd64/qconf', '-de', hostname]
    __runSgeCommand(command)

    # Removing host as administrative host
    command = ['/opt/sge/bin/lx-amd64/qconf', '-dh', hostname]
    __runSgeCommand(command)
