import logging

import boto3
from botocore.exceptions import ClientError
from retrying import retry
from time_utils import seconds

from tests.common.networking.security_groups import delete_security_group


@retry(stop_max_attempt_number=3, wait_fixed=seconds(5))
def describe_efs_filesystem(region: str, file_system_id: str):
    logging.info(f"Describing EFS File System {file_system_id}")
    try:
        return _efs(region).describe_file_systems(FileSystemId=file_system_id)["FileSystems"][0]
    except Exception as e:
        if isinstance(e, ClientError) and "FileSystemNotFound" in str(e):
            return None
        else:
            logging.error(f"Cannot describe EFS File System {file_system_id}: {e}")
            raise e


@retry(stop_max_attempt_number=10, wait_fixed=seconds(30))
def delete_efs_filesystem(region: str, file_system_id: str, delete_dependent_resources: bool = True):
    logging.info(f"Deleting EFS File System {file_system_id}")
    try:
        if delete_dependent_resources:
            mount_targets = describe_efs_mount_targets(region, file_system_id)
            security_group_ids = set()
            for mount_target in mount_targets:
                mount_target_id = mount_target["MountTargetId"]
                security_groups = describe_mount_target_security_groups(region, mount_target_id)
                for security_group_id in security_groups:
                    security_group_ids.add(security_group_id)
                delete_efs_mount_target(region, mount_target_id)
            logging.info(
                "The following Security Groups will be deleted as part of "
                f"the deletion for the EFS File System {file_system_id}: {security_group_ids}"
            )
            for mount_target in mount_targets:
                mount_target_id = mount_target["MountTargetId"]
                wait_for_efs_mount_target_deletion(region, file_system_id, mount_target_id)
            for security_group_id in security_group_ids:
                delete_security_group(region, security_group_id)
        _efs(region).delete_file_system(FileSystemId=file_system_id)
    except Exception as e:
        if isinstance(e, ClientError) and "FileSystemNotFound" in str(e):
            logging.warning(f"Cannot delete EFS File System {file_system_id} because it does not exist")
        else:
            logging.error(f"Cannot delete EFS File System {file_system_id}: {e}")
            raise e


@retry(stop_max_attempt_number=3, wait_fixed=seconds(5))
def describe_efs_mount_targets(region: str, file_system_id: str):
    logging.info(f"Describing Mount Targets for EFS File System {file_system_id}")
    return _efs(region).describe_mount_targets(FileSystemId=file_system_id).get("MountTargets", [])


@retry(stop_max_attempt_number=3, wait_fixed=seconds(5))
def describe_mount_target_security_groups(region: str, mount_target_id: str):
    logging.info(f"Describing Security Groups for EFS Mount Target {mount_target_id}")
    return _efs(region).describe_mount_target_security_groups(MountTargetId=mount_target_id).get("SecurityGroups", [])


@retry(stop_max_attempt_number=3, wait_fixed=seconds(5))
def delete_efs_mount_target(region: str, mount_target_id: str):
    logging.info(f"Deleting EFS Mount Target {mount_target_id}")
    _efs(region).delete_mount_target(MountTargetId=mount_target_id)


@retry(stop_max_attempt_number=10, wait_fixed=seconds(60))
def wait_for_efs_mount_target_deletion(region: str, file_system_id: str, mount_target_id: str):
    logging.info(f"Waiting for deletion of EFS Mount Target {mount_target_id} in EFS File System {file_system_id}")
    mount_targets = describe_efs_mount_targets(region, file_system_id)
    mount_target_ids = [mt["MountTargetId"] for mt in mount_targets]
    if mount_target_id in mount_target_ids:
        raise Exception(
            f"EFs Mount Target {mount_target_id} in EFS File System {file_system_id} not deleted, yet. "
            "Sleeping 60 seconds ..."
        )


def _efs(region):
    return boto3.client("efs", region)
