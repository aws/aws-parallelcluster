import logging

import boto3
from botocore.exceptions import ClientError
from retrying import retry
from time_utils import seconds


@retry(stop_max_attempt_number=3, wait_fixed=seconds(5))
def describe_ebs_volume(region: str, volume_id: str):
    logging.info(f"Describing EBS Volume {volume_id}")
    try:
        return _ec2(region).describe_volumes(VolumeIds=[volume_id])["Volumes"][0]
    except Exception as e:
        if isinstance(e, ClientError) and "InvalidVolume.NotFound" in str(e):
            return None
        else:
            logging.error(f"Cannot describe EBS Volume {volume_id}: {e}")
            raise e


@retry(stop_max_attempt_number=3, wait_fixed=seconds(5))
def delete_ebs_volume(region: str, volume_id: str):
    logging.info(f"Deleting EBS Volume {volume_id}")
    try:
        _ec2(region).delete_volume(VolumeId=volume_id)
    except Exception as e:
        if isinstance(e, ClientError) and "InvalidVolume.NotFound" in str(e):
            logging.warning(f"Cannot delete EBS Volume {volume_id} because it does not exist")
        else:
            logging.error(f"Cannot delete EBS Volume {volume_id}: {e}")
            raise e


def _ec2(region):
    return boto3.client("ec2", region)
