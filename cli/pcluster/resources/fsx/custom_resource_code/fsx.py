import logging
import os
import sys
import time
import botocore
import cfn_resource

os.environ['AWS_DATA_PATH'] = os.getcwd()
import boto3

logger = logging.getLogger()
handler = cfn_resource.Resource()

def _get_fsx_resources(props):
    logger.info(props)
    attrs_to_remove = ['Region', 'ServiceToken']
    for attr in attrs_to_remove:
        if attr in props:
            del props[attr]
    if 'StorageCapacity' in props:
        props['StorageCapacity'] = int(props['StorageCapacity'])
    if 'WindowsConfiguration' in props and 'ThroughputCapacity' in props['WindowsConfiguration']:
        props['WindowsConfiguration']['ThroughputCapacity'] = int(props['WindowsConfiguration']['ThroughputCapacity'])
    return props

@handler.create
def create(event, context):
    logger.info(event)
    c = boto3.client('fsx')
    resp = c.create_file_system(**_get_fsx_resources(event['ResourceProperties']))
    logger.info(resp)
    file_system_arn = resp['FileSystem']['ResourceARN']
    file_system_id = file_system_arn.split('/')[-1]
    
    # Wait for file system to be AVAILABLE
    while True:
        resp = c.describe_file_systems(
            FileSystemIds=[file_system_id]
        )
        if resp['FileSystems'][0]['Lifecycle'] == 'AVAILABLE':
            break
        time.sleep(10)
    
    return {
        'PhysicalResourceId': file_system_id
    }

@handler.update
def update(event, context):
    logger.info(event)
    return {}

@handler.delete
def delete(event, context):
    logger.info(event)
    file_system_arn = event['PhysicalResourceId']
    file_system_id = file_system_arn.split('/')[-1]
    
    c = boto3.client('fsx')
    resp = c.delete_file_system(FileSystemId=file_system_id)
    
    # Wait for file system to be gone
    while True:
        try:
            c.describe_file_systems(
                FileSystemIds=[file_system_id]
            )
        except botocore.exceptions.ClientError as e:
            if e.response['Error']['Code'] == 'FileSystemNotFound':
                break
        time.sleep(10)
    
    return {
        'PhysicalResourceId': file_system_id
    }