import subprocess as sub
import paramiko
from tempfile import mkstemp
from shutil import move
import time
import os
import socket

def __runCommand(command):
    _command = command
    try:
        sub.check_call(_command, env=dict(os.environ))
    except sub.CalledProcessError:
        print ("Failed to run %s\n" % _command)


def __readNodeList():
    with open("/opt/slurm/etc/slurm.conf") as slurm_config:
        for line in slurm_config:
            if line.startswith('NodeName'):
                items = line.split(' ')
                node_line = items[0].split('=')
                node_list = node_line[1].split(',')
                return node_list


def __writeNodeList(node_list):
    fh, abs_path = mkstemp()
    with open(abs_path,'w') as new_file:
        with open("/opt/slurm/etc/slurm.conf") as slurm_config:
            for line in slurm_config:
                if line.startswith('NodeName'):
                    items = line.split(' ')
                    node_line = items[0].split('=')
                    new_file.write(node_line[0] + '=' + ','.join(node_list) + " " + ' '.join(items[1:]))
                elif line.startswith('PartitionName'):
                    items = line.split(' ')
                    node_line = items[1].split('=')
                    new_file.write(items[0] + " " + node_line[0] + '=' + ','.join(node_list) + " " + ' '.join(items[2:]))
                else:
                    new_file.write(line)
    os.close(fh)
    #Remove original file
    os.remove("/opt/slurm/etc/slurm.conf")
    #Move new file
    move(abs_path, "/opt/slurm/etc/slurm.conf")

    os.chmod("/opt/slurm/etc/slurm.conf", 0744)


def addHost(hostname, cluster_user):
    print('Adding %s', hostname)

    # Get the current node list
    node_list = __readNodeList()

    # Add new node
    node_list.append(hostname)
    __writeNodeList(node_list)

    # Restart slurmctl
    command = ['/etc/init.d/slurm', 'restart']
    __runCommand(command)


def removeHost(hostname, cluster_user):
    print('Removing %s', hostname)

    # Get the current node list
    node_list = __readNodeList()

    # Remove node
    node_list.remove(hostname)
    __writeNodeList(node_list)

    # Restart slurmctl
    command = ['/etc/init.d/slurm', 'restart']
    __runCommand(command)

