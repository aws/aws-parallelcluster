import logging

import boto3
from botocore.exceptions import ClientError
from retrying import retry
from time_utils import seconds


@retry(stop_max_attempt_number=3, wait_fixed=seconds(5))
def delete_security_group(region: str, security_group_id: str):
    logging.info(f"Deleting Security Group {security_group_id}")
    try:
        _ec2(region).delete_security_group(GroupId=security_group_id)
    except Exception as e:
        if isinstance(e, ClientError) and "InvalidGroup.NotFound" in str(e):
            logging.warning(f"Cannot delete Security Group {security_group_id} because it does not exist")
        else:
            logging.error(f"Cannot delete Security Group {security_group_id}: {e}")
            raise e


@retry(stop_max_attempt_number=3, wait_fixed=seconds(5))
def describe_security_groups_for_network_interface(region: str, network_interface_id: str):
    logging.info(f"Describing Security Groups for Network Interface {network_interface_id}")
    try:
        network_inyterface_description = _ec2(region).describe_network_interfaces(
            NetworkInterfaceIds=[network_interface_id]
        )
        return [
            security_group["GroupId"]
            for security_group in network_inyterface_description["NetworkInterfaces"][0]["Groups"]
        ]
    except Exception as e:
        logging.error(f"Cannot describe Security Groups for Network Interface {network_interface_id}: {e}")
        raise e


def _ec2(region):
    return boto3.client("ec2", region)
