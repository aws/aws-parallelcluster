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

import subprocess as sub
from tempfile import mkstemp
from shutil import move
import os
import paramiko
import socket
import time
import logging

log = logging.getLogger(__name__)


def __runCommand(command):
    _command = command
    log.debug(repr(command))
    try:
        sub.check_call(_command, env=dict(os.environ))
    except sub.CalledProcessError:
        log.error("Failed to run %s\n" % _command)


def __restartSlurm(hostname, cluster_user):
    # Connect and restart Slurm on compute node
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    hosts_key_file = os.path.expanduser("~" + cluster_user) + '/.ssh/known_hosts'
    user_key_file = os.path.expanduser("~" + cluster_user) + '/.ssh/id_rsa'
    iter=0
    connected=False
    while iter < 3 and not connected:
        try:
            log.info('Connecting to host: %s iter: %d' % (hostname, iter))
            ssh.connect(hostname, username=cluster_user, key_filename=user_key_file)
            connected = True
        except socket.error, e:
            log.error('Socket error: %s' % e)
            time.sleep(10 + iter)
            iter = iter + 1
            if iter == 3:
                log.critical("Unable to connect to host")
                return
    try:
        ssh.load_host_keys(hosts_key_file)
    except IOError:
        ssh._host_keys_filename = None
        pass
    ssh.save_host_keys(hosts_key_file)
    command = "sudo sh -c \'/etc/init.d/slurm restart &> /tmp/slurmdstart.log\'"
    stdin, stdout, stderr = ssh.exec_command(command)
    ssh.close()


def __readNodeList():
    _config = "/opt/slurm/etc/slurm.conf"
    nodes = {}
    with open(_config) as slurm_config:
        for line in slurm_config:
            if line.startswith('#PARTITION'):
                partition = line.split(':')[1].rstrip()
                dummy_node = slurm_config.next()
                node_name = slurm_config.next()
                items = node_name.split(' ')
                node_line = items[0].split('=')
                if len(node_line[1]) > 0:
                    nodes[partition] = node_line[1].split(',')
                else:
                    nodes[partition] = []
    return nodes


def __writeNodeList(node_list):
    _config = "/opt/slurm/etc/slurm.conf"
    fh, abs_path = mkstemp()
    with open(abs_path,'w') as new_file:
        with open(_config) as slurm_config:
            for line in slurm_config:
                if line.startswith('#PARTITION'):
                    partition = line.split(':')[1].rstrip()
                    new_file.write(line)
                    dummy_node = slurm_config.next()
                    new_file.write(dummy_node)
                    node_names = slurm_config.next()
                    partitions = slurm_config.next()
                    items = node_names.split(' ')
                    node_line = items[0].split('=')
                    if len(node_list[partition]) > 0:
                        new_file.write('NodeName=' + ','.join(node_list[partition]) + " " + ' '.join(items[1:]))
                    else:
                        new_file.write("#NodeName= Procs=1 State=UNKNOWN\n")
                    items = partitions.split(' ')
                    node_line = items[1].split('=')
                    new_file.write(items[0] + " " + node_line[0] + '=dummy-' + partition + ',' + ','.join(node_list[partition]) + " " + ' '.join(items[2:]))
                else:
                    new_file.write(line)
    os.close(fh)
    #Remove original file
    os.remove(_config)
    #Move new file
    move(abs_path, _config)
    #Update permissions on new file
    os.chmod(_config, 0744)


def addHost(hostname, cluster_user):
    log.info('Adding %s' % hostname)

    # Get the current node list
    node_list = __readNodeList()

    # Add new node
    node_list['compute'].append(hostname)
    __writeNodeList(node_list)

    # Restart slurmctl locally
    command = ['/etc/init.d/slurm', 'restart']
    __runCommand(command)

    # Restart slurmctl on host
    __restartSlurm(hostname, cluster_user)

    # Reconfifure Slurm, prompts all compute nodes to reread slurm.conf
    command = ['/opt/slurm/bin/scontrol', 'reconfigure']
    __runCommand(command)


def removeHost(hostname, cluster_user):
    log.info('Removing %s', hostname)

    # Get the current node list
    node_list = __readNodeList()

    # Remove node
    node_list['compute'].remove(hostname)
    __writeNodeList(node_list)

    # Restart slurmctl
    command = ['/etc/init.d/slurm', 'restart']
    __runCommand(command)

    # Reconfifure Slurm, prompts all compute nodes to reread slurm.conf
    command = ['/opt/slurm/bin/scontrol', 'reconfigure']
    __runCommand(command)

