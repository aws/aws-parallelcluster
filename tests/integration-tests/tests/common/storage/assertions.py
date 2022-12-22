import logging
from typing import List

from assertpy import assert_that

from tests.common.storage.constants import StorageType
from tests.common.storage.ebs_utils import describe_ebs_volume
from tests.common.storage.efs_utils import describe_efs_filesystem
from tests.common.storage.fsx_utils import describe_fsx_filesystem


def assert_storage_existence(
    region: str, storage_type: StorageType, storage_id: str, should_exist: bool, expected_states: List[str] = None
):
    logging.info(
        f"Checking existence for {storage_type.name} resource {storage_id}: "
        f"expected to{' not ' if not should_exist else ' '}exist"
    )
    if storage_type == StorageType.STORAGE_EBS:
        description = describe_ebs_volume(region, storage_id)
        state = description.get("State") if description else None
    elif storage_type == StorageType.STORAGE_EFS:
        description = describe_efs_filesystem(region, storage_id)
        state = description.get("LifeCycleState") if description else None
    elif storage_type == StorageType.STORAGE_FSX:
        description = describe_fsx_filesystem(region, storage_id)
        state = description.get("Lifecycle") if description else None
    else:
        raise Exception(f"Cannot check existence for storage type {storage_type.name}.")
    exists = description is not None
    assert_that(
        exists, f"The {storage_type.name} resource {storage_id} does{' not ' if not exists else ' '}exist"
    ).is_equal_to(should_exist)

    if should_exist and expected_states:
        assert_that(
            expected_states,
            f"The {storage_type.name} resource {storage_id} is not in the expected state: "
            f"expected states are {expected_states}, but actual is {state}",
        ).contains(state)
