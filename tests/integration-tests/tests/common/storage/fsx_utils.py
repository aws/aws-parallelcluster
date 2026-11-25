import logging

import boto3
from assertpy import assert_that
from botocore.exceptions import ClientError
from retrying import retry
from time_utils import minutes, seconds

from tests.common.networking.security_groups import (
    delete_security_group,
    describe_security_groups_for_network_interface,
)


@retry(stop_max_attempt_number=3, wait_fixed=seconds(5))
def describe_fsx_filesystem(region: str, file_system_id: str):
    logging.info(f"Describing FSx File System {file_system_id}")
    try:
        return _fsx(region).describe_file_systems(FileSystemIds=[file_system_id])["FileSystems"][0]
    except Exception as e:
        if isinstance(e, ClientError) and "FileSystemNotFound" in str(e):
            return None
        else:
            logging.error(f"Cannot describe FSx File System {file_system_id}: {e}")
            raise e


@retry(stop_max_attempt_number=10, wait_fixed=seconds(30))
def delete_fsx_filesystem(region: str, file_system_id: str, delete_dependent_resources: bool = True):
    logging.info(f"Deleting FSx File System {file_system_id}")
    try:
        security_group_ids = set()
        if delete_dependent_resources:
            security_group_ids |= describe_fsx_filesystem_security_groups(region, file_system_id)
        _fsx(region).delete_file_system(FileSystemId=file_system_id)
        if delete_dependent_resources:
            logging.info(
                "The following Security Groups will be deleted as part of "
                f"the deletion for the FSx File System {file_system_id}: {security_group_ids}"
            )
            wait_for_fsx_filesystem_deletion(region, file_system_id)
            for security_group_id in security_group_ids:
                delete_security_group(region, security_group_id)
    except Exception as e:
        if isinstance(e, ClientError) and "FileSystemNotFound" in str(e):
            logging.warning(f"Cannot delete FSx File System {file_system_id} because it does not exist")
        else:
            logging.error(f"Cannot delete FSx File System {file_system_id}: {e}")
            raise e


@retry(stop_max_attempt_number=3, wait_fixed=seconds(5))
def describe_fsx_filesystem_security_groups(region: str, file_system_id: str):
    logging.info(f"Describing Security Groups for FSx File System {file_system_id}")
    fs_description = _fsx(region).describe_file_systems(FileSystemIds=[file_system_id])
    network_interface_ids = fs_description["FileSystems"][0]["NetworkInterfaceIds"]
    security_group_ids = set()
    for network_interface_id in network_interface_ids:
        for security_group_id in describe_security_groups_for_network_interface(region, network_interface_id):
            security_group_ids.add(security_group_id)
    return security_group_ids


@retry(stop_max_attempt_number=10, wait_fixed=seconds(60))
def wait_for_fsx_filesystem_deletion(region: str, file_system_id: str):
    logging.info(f"Waiting for deletion of FSx File System {file_system_id}")
    fs_description = describe_fsx_filesystem(region, file_system_id)
    if fs_description is not None:
        state = fs_description.get("Lifecycle")
        raise Exception(f"FSx File System {file_system_id} in state {state} not deleted, yet. Sleeping 60 seconds ...")


@retry(
    stop_max_delay=minutes(40),
    wait_fixed=seconds(30),
    retry_on_result=lambda file_cache: file_cache.get("Lifecycle") == "CREATING"
    or (file_cache.get("Lifecycle") == "AVAILABLE" and not file_cache.get("NetworkInterfaceIds")),
)
def _describe_file_cache_until_created(region: str, file_cache_id: str):
    file_cache = _fsx(region).describe_file_caches(FileCacheIds=[file_cache_id])["FileCaches"][0]
    logging.info(
        f"File Cache {file_cache_id} in state {file_cache.get('Lifecycle')} "
        f"with network interfaces {file_cache.get('NetworkInterfaceIds')}"
    )
    return file_cache


def wait_for_file_cache_available(region: str, file_cache_id: str):
    """
    Wait for the File Cache to be AVAILABLE with its network interfaces reported by DescribeFileCaches.

    The custom resource creating the File Cache returns as soon as the creation is started.
    Until the File Cache is AVAILABLE, DescribeFileCaches does not report its network interfaces
    and the cluster validation fails with ExistingFsxNetworkingValidator.
    """
    logging.info(f"Waiting for File Cache {file_cache_id} to be available")
    file_cache = _describe_file_cache_until_created(region, file_cache_id)
    assert_that(file_cache.get("Lifecycle")).described_as(f"Lifecycle of File Cache {file_cache_id}").is_equal_to(
        "AVAILABLE"
    )


def _fsx(region):
    return boto3.client("fsx", region)
