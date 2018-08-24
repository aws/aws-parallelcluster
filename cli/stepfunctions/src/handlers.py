from StringIO import StringIO
import configparser
import logging
import os
import sys
import traceback

from botocore.exceptions import ClientError
from cfncluster import cli, cfncluster
import boto3
import paramiko

import constants

# set logger and log level
logger = logging.getLogger()
logger.setLevel(logging.INFO)

idle = ['CREATE_IN_PROGRESS', 'UPDATE_IN_PROGRESS', 'REVIEW_IN_PROGRESS']
complete = ['CREATE_COMPLETE', 'UPDATE_COMPLETE']


class Args:
    """Setup arguments to pass to cfncluster cli
        
    Initializes with all possible arguments that could be
    passed into the cfncluster cli
    """

    config_file = 'config/cfncluster.config'
    reset_desired = False
    template_url = None
    norollback = False
    nowait = True

    def __init__(self, cluster_name, region, func):
        self.cluster_name = cluster_name
        self.region = region
        self.func = func


class EC2_SSH:
    """Creates a paramiko ssh client for EC2 instances
    
    Attributes:
        ip: Master public IP address of EC2 instance
    """

    def __init__(self, ip, username, key):
        self.ip = ip
        self.username = username
        self.key = key

    def __enter__(self):
        try:
            sm = boto3.client('secretsmanager')
            secret = sm.get_secret_value(SecretId=self.key)
            key_string = secret['SecretString']
            key_file = StringIO(key_string)
            pkey = paramiko.RSAKey.from_private_key(key_file)
            self.ssh = paramiko.SSHClient()
            self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self.ssh.connect(self.ip, username=self.username, pkey=pkey)
        except ClientError as e:
            print(e.response.get('Error').get('Message'))
            sys.exit(1)
        return self.ssh

    def __exit__(self, exc_type, exc_value, tb):
        if exc_type is not None:
            traceback.print_exception(exc_type, exc_value, tb)
        self.ssh.close()


class EC2_SFTP:
    """Creates a paramiko sftp client for EC2 instances

    Attributes:
        ip: Master public IP address of EC2 instance
    """

    def __init__(self, ip, username, key):
        self.ip = ip
        self.username = username
        self.key = key

    def __enter__(self):
        try:
            sm = boto3.client('secretsmanager')
            secret = sm.get_secret_value(SecretId=self.key)
            key_string = secret['SecretString']
            key_file = StringIO(key_string)
            pkey = paramiko.RSAKey.from_private_key(key_file)
            self.transport = paramiko.Transport(self.ip)
            self.transport.connect(username=self.username, pkey=pkey)
            self.sftp = paramiko.SFTPClient.from_transport(self.transport)
        except ClientError as e:
            print(e.response.get('Error').get('Message'))
            sys.exit(1)
        return self.sftp

    def __exit__(self, exc_type, exc_value, tb):
        if exc_type is not None:
            traceback.print_exception(exc_type, exc_value, tb)
        self.sftp.close()
        self.transport.close()


def create_cfncluster(event, context):
    """Handler for creating cfnclusters

    Args:
        event: should contain 'cluster_name' attribute
    """
    logging.info('event = {}\ncontext = {}'.format(event, context))
    
    # variable check
    if event.get('cluster_name') is None:
        raise Exception('cluster_name not specified')

    config = configparser.ConfigParser()
    config.readfp(open('config/cfncluster.config'))
    event['key_name'] = config.get('cluster default', 'key_name')

    region = os.getenv('AWS_DEFAULT_REGION', 'us-east-1')

    # create/get ec2 key pair
    try:
        ec2 = boto3.client('ec2')
        ec2.describe_key_pairs(KeyNames=[event['key_name']])
        sm = boto3.client('secretsmanager')
        sm.describe_secret(SecretId=event['key_name'])
    except ClientError as e:
        if e.response.get('Error').get('Code') == 'InvalidKeyPair.NotFound':
            try:
                ec2 = boto3.client('ec2')
                key = ec2.create_key_pair(KeyName=event['key_name'])
                sm = boto3.client('secretsmanager')
                sm.create_secret(
                    Name=event['key_name'],
                    SecretString=key['KeyMaterial']
                )
            except ClientError as e:
                print(e.response.get('Error').get('Message'))
                sys.exit(1)
        else:
            print(e.response.get('Error').get('Message'))
            sys.exit(1)

    args = Args(event['cluster_name'], region, constants.create)
    cli.create(args)
    return event

def is_cluster_ready(event, context):
    """Handler for waiting on successful cfncluster deployment

    Args:
        event: contains number of executions of this function
    """
    logging.debug('event = {}\ncontext = {}'.format(event, context))

    # variable check
    if event.get('execution_count') is None:
        event['execution_count'] = 0

    # poll on cluster creation
    stack = 'cfncluster-{}'.format(event['cluster_name'])
    try:
        cfn = boto3.resource('cloudformation')
        stack = cfn.Stack(stack)
        status = stack.stack_status
    except ClientError as e:
        print(e.response.get('Error').get('Message'))
        sys.exit(1)

    logger.info('Poll {}: {}'.format(event['execution_count'], status))

    if status in idle:
        event['status'] = 'idle'
    elif status in complete:
        event['status'] = 'complete'
        outputs = stack.outputs
        parameters = stack.parameters
        event['master_ip'] = filter(
            lambda op: op['OutputKey'] == 'MasterPublicIP', outputs
        )[0]['OutputValue']
        event['user_name'] = filter(
            lambda op: op['OutputKey'] == 'ClusterUser', outputs
        )[0]['OutputValue']
        event['scheduler'] = filter(
            lambda param: param['ParameterKey'] == 'Scheduler', parameters
        )[0]['ParameterValue']
    else:
        logging.error(status)
        event['status'] = 'failed'

    event['execution_count'] += 1

    # give timeout if applicable
    if event['execution_count'] == 15 and event['status'] == 'idle':
        event['status'] = 'timeout'

    # make working temporary directory in master node
    if event['status'] == 'complete':
        master_ip = event['master_ip']
        user_name = event['user_name']
        key_name = event['key_name']
        with EC2_SSH(master_ip, user_name, key_name) as ssh_client:
            command = 'mktemp -d -p /shared'
            workdir = ssh_client.exec_command(command)[1].read().strip()
            event['workdir'] = workdir

    return event

def delete_cfncluster(event, context):
    """Handler for deleting cfnclusters

    Args:
        event: should contain 'cluster_name' attribute
    """
    logging.debug('event = {}\ncontext = {}'.format(event, context))

    # the output of parallel states is a list of outputs of all branches
    is_list = isinstance(event, list)
    name = event[0]['cluster_name'] if is_list else event['cluster_name']

    region = os.getenv('AWS_DEFAULT_REGION', 'us-east-1')
    args = Args(name, region, constants.delete)
    cli.delete(args)

    return event
