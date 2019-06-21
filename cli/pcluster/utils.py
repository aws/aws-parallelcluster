# Copyright 2018 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance with
# the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
from __future__ import absolute_import, print_function

import json
import os
import socket
import struct
import zipfile
from io import BytesIO
from ipaddress import ip_address, ip_network, summarize_address_range

import boto3
from botocore.exceptions import ClientError


def boto3_client(service, aws_client_config):
    return boto3.client(
        service,
        region_name=aws_client_config["region_name"],
        aws_access_key_id=aws_client_config["aws_access_key_id"],
        aws_secret_access_key=aws_client_config["aws_secret_access_key"],
    )


def boto3_resource(service, aws_client_config):
    return boto3.resource(
        service,
        region_name=aws_client_config["region_name"],
        aws_access_key_id=aws_client_config["aws_access_key_id"],
        aws_secret_access_key=aws_client_config["aws_secret_access_key"],
    )


def create_s3_bucket(bucket_name, aws_client_config):
    """
    Create a new S3 bucket.

    Args:
        bucket_name: name of the S3 bucket to create
        aws_client_config: dictionary containing configuration params for boto3 client
    """
    s3_client = boto3_client("s3", aws_client_config)
    """ :type : pyboto3.s3 """
    try:
        region = aws_client_config["region_name"]
        if region != "us-east-1":
            s3_client.create_bucket(Bucket=bucket_name, CreateBucketConfiguration={"LocationConstraint": region})
        else:
            s3_client.create_bucket(Bucket=bucket_name)
    except s3_client.exceptions.BucketAlreadyOwnedByYou:
        print("Bucket already exists")


def delete_s3_bucket(bucket_name, aws_client_config):
    """
    Delete an S3 bucket together with all stored objects.

    Args:
        bucket_name: name of the S3 bucket to delete
        aws_client_config: dictionary containing configuration params for boto3 client
    """
    try:
        bucket = boto3_resource("s3", aws_client_config).Bucket(bucket_name)
        bucket.objects.all().delete()
        bucket.delete()
    except boto3.client("s3").exceptions.NoSuchBucket:
        pass
    except ClientError:
        print("Failed to delete bucket %s. Please delete it manually." % bucket_name)
        pass


def zip_dir(path):
    """
    Create a zip archive containing all files and dirs rooted in path.

    The archive is created in memory and a file handler is returned by the function.
    Args:
        path: directory containing the resources to archive.
    Return:
        file_out: file handler pointing to the compressed archive.
    """
    file_out = BytesIO()
    with zipfile.ZipFile(file_out, "w", zipfile.ZIP_DEFLATED) as ziph:
        for root, _, files in os.walk(path):
            for file in files:
                ziph.write(os.path.join(root, file), os.path.relpath(os.path.join(root, file), start=path))
    file_out.seek(0)
    return file_out


def upload_resources_artifacts(bucket_name, root, aws_client_config):
    """
    Upload to the specified S3 bucket the content of the directory rooted in root path.

    All dirs contained in root dir will be uploaded as zip files to $bucket_name/$dir_name/artifacts.zip.
    All files contained in root dir will be uploaded to $bucket_name.
    Args:
        bucket_name: name of the S3 bucket where files are uploaded
        root: root directory containing the resources to upload.
        aws_client_config: dictionary containing configuration params for boto3 client
    """
    bucket = boto3_resource("s3", aws_client_config).Bucket(bucket_name)
    for res in os.listdir(root):
        if os.path.isdir(os.path.join(root, res)):
            bucket.upload_fileobj(zip_dir(os.path.join(root, res)), "%s/artifacts.zip" % res)
        elif os.path.isfile(os.path.join(root, res)):
            bucket.upload_file(os.path.join(root, res), res)


def _get_json_from_s3(region, file_name):
    """
    Get pricing file (if none) and parse content as json.

    :param region: AWS Region
    :param file_name the object name to get
    :return: a json object representing the file content
    :raises ClientError if unable to download the file
    :raises ValueError if unable to decode the file content
    """
    s3 = boto3.resource("s3", region_name=region)
    bucket_name = "{0}-aws-parallelcluster".format(region)

    file_contents = s3.Object(bucket_name, file_name).get()["Body"].read().decode("utf-8")
    return json.loads(file_contents)


def get_supported_features(region, feature):
    """
    Get a json object containing the attributes supported by a feature, for example.

    {
        "Features": {
            "efa": {
                "instances": ["c5n.18xlarge", "p3dn.24xlarge", "i3en.24xlarge"],
                "baseos": ["alinux", "centos7"],
                "schedulers": ["sge", "slurm", "torque"]
            },
            "batch": {
                "instances": ["r3.8xlarge", ..., "m5.4xlarge"]
            }
        }
    }

    :param region: AWS Region
    :param feature: the feature to search for, i.e. "efa" "awsbatch"
    :return: json object containing all the attributes supported by feature
    """
    try:
        features = _get_json_from_s3(region, "features/feature_whitelist.json")
        supported_features = features.get("Features").get(feature)
    except (ValueError, ClientError, KeyError):
        print(
            "Failed validate %s. This is probably a bug on our end. Please set sanity_check = false and retry" % feature
        )
        exit(1)

    return supported_features


def get_instance_vcpus(region, instance_type):
    """
    Get number of vcpus for the given instance type.

    :param region: AWS Region
    :param instance_type: the instance type to search for.
    :return: the number of vcpus or -1 if the instance type cannot be found
    or the pricing file cannot be retrieved/parsed
    """
    try:
        instances = _get_json_from_s3(region, "instances/instances.json")
        vcpus = int(instances[instance_type]["vcpus"])
    except (KeyError, ValueError, ClientError):
        vcpus = -1

    return vcpus


def get_supported_os(scheduler):
    """
    Return a tuple of the os supported by parallelcluster for the specific scheduler.

    :param scheduler: the scheduler for which we want to know the supported os
    :return: a tuple of strings of the supported os
    """
    return "alinux" if scheduler == "awsbatch" else "alinux", "centos6", "centos7", "ubuntu1404", "ubuntu1604"


def get_supported_schedulers():
    """
    Return a tuple of the scheduler supported by parallelcluster.

    :return: a tuple of strings of the supported scheduler
    """
    return "sge", "torque", "slurm", "awsbatch"


def next_power_of_2(x):
    """Given a number returns the following power of 2 of that number."""
    return 1 if x == 0 else 2 ** (x - 1).bit_length()


def get_subnet_cidr(vpc_cidr, occupied_cidr, max_queue_size):
    """
    Decide the parallelcluster subnet size of the compute fleet.
    :param vpc_cidr: the vpc_cidr in which the suitable subnet should be
    :param occupied_cidr: a list of cidr of the already occupied subnets in the vpc
    :param max_queue_size: the max nodes / vcpus that the user has set
    :return:
    """
    target_size = max(4000, 2 * max_queue_size)
    cidr = decide_cidr(vpc_cidr, occupied_cidr, target_size)
    while cidr is None:
        if target_size < max_queue_size:
            return None
        target_size = target_size // 2
        cidr = decide_cidr(vpc_cidr, occupied_cidr, target_size)
    return cidr


# This code is complex, get ready
def decide_cidr(vpc_cidr, occupied_cidr, target_size):
    """
    Decide the smallest suitable CIDR for a subnet with size >= target_size.

    :param vpc_cidr: the vpc_cidr in which the suitable subnet should be
    :param occupied_cidr: a list of cidr of the already occupied subnets in the vpc
    :param target_size: the minimum target size of the subnet
    :return: the suitable CIDR if found, else None
    """
    # How the algorithm works: If we want to find a suitable CIDR inside a vpc with already some subnet inside, we first
    # have to check wheter the size of the subnet we want to create is greater than the minimum Cidr (/16, /24, ecc...).
    # If it is, we have to transform all the occupied_cidr into subnets that have at least the cidr of the instance we
    # want to allocate. To do that, we use _promote_cidrs().
    #
    # Why doing that?
    #
    # Well, the function summarize_address_range() returns a iterator of all the cidr needed to encapsulate the given
    # begin ip and the end ip strictly. So for example, from 10.0.0.0 to 10.0.1.1, the function will return[10.0.0.0/24,
    # 10.0.1.0/31]. We therefore need to give to that function an ip range that can be compressed in just one cidr. In
    # order to do that, we basically expand all the cidr and then eliminate all the duplicates.

    # Once we have the target cidr (which is 32 - the power of 2 that is equal to subnet_size  ) to be the minimum
    # of all the occupied_cidr, we create a list of tuple (beginip, endip) that are sorted by endip. We then compare
    # each beginip with the endip of the previous one looking for a space greater than the one of subnet_size.
    # If we found it, we convert it to a cidr using the summarize_address_range() function.
    # Function cost: O(nlogn), where n is the size of occupied cidr
    # Understanding cost: O(over9000)
    aws_reserved_ip = 6
    min_bitmask_length = 28
    target_bitmask_length = min(
        32 - ((next_power_of_2(target_size + aws_reserved_ip) - 1).bit_length()), min_bitmask_length
    )
    subnet_size = 2 ** (32 - target_bitmask_length)
    vpc_begin_address_decimal, vpc_end_address_decimal = _get_cidr_limits_as_decimal(vpc_cidr)

    if vpc_end_address_decimal - vpc_begin_address_decimal + 1 < subnet_size:  # if we do not have enough space
        return None

    if not occupied_cidr:  # if we have space and no occupied cidr
        return _decimal_ip_limits_to_cidr(vpc_begin_address_decimal, vpc_begin_address_decimal + subnet_size)

    occupied_cidr_max_bitmask = max([int(subnet_cidr.split("/")[1]) for subnet_cidr in occupied_cidr])
    if occupied_cidr_max_bitmask > target_bitmask_length:
        # This means that it's smaller, so we need to make it bigger
        occupied_cidr = _expand_cidrs(occupied_cidr, min_size=target_bitmask_length)

    # subnets_number is a list of pair(begin ip, end ip) obtained from the cidr. So for example
    # 10.0.0.0/17 = 10.0.0.0, 10.0.127.255
    begin_ip_index = 0
    end_ip_index = 1
    subnets_limits = [_get_cidr_limits_as_decimal(subnet) for subnet in occupied_cidr]
    subnets_limits.sort(key=lambda x: x[1])  # sort by ending numbers, sorting by beginning is the same
    # to check for space between the last occupied and the end of the vpc
    subnets_limits.append((vpc_end_address_decimal, vpc_end_address_decimal))

    if (subnets_limits[0][begin_ip_index] - vpc_begin_address_decimal) >= subnet_size:
        return _decimal_ip_limits_to_cidr(vpc_begin_address_decimal, vpc_begin_address_decimal + subnet_size)

    #  Looking at space between occupied cidrs
    for index in range(1, len(subnets_limits)):
        begin_number = subnets_limits[index][begin_ip_index]
        end_previous_number = subnets_limits[index - 1][end_ip_index]
        if begin_number - end_previous_number > subnet_size:
            return _decimal_ip_limits_to_cidr(end_previous_number + 1, end_previous_number + subnet_size)
    return None


def _decimal_ip_limits_to_cidr(begin, end):
    """Given begin and end ip (as decimals number), return the CIDR that begins with begin ip and ends with end ip."""
    return str(
        summarize_address_range(
            ip_address(socket.inet_ntoa(struct.pack("!L", begin))), ip_address(socket.inet_ntoa(struct.pack("!L", end)))
        ).__next__()
    )


def _get_cidr_limits_as_decimal(cidr):
    """Given a cidr, return the begin ip and the end ip as decimal."""
    address = ip_network(cidr)
    return _ip_to_decimal(str(address[0])), _ip_to_decimal(str(address[-1]))


def _ip_to_decimal(ip):
    """Transform an ip into its decimal representantion."""
    return int(bin(struct.unpack("!I", socket.inet_aton(ip))[0]), 2)


def _expand_cidrs(occupied_cidrs, min_size):
    """Given a list of cidrs, it upgrade the netmask of each one to min_size and returns the updated cidrs."""
    new_cidrs = set()
    for cidr in occupied_cidrs:
        if int(cidr.split("/")[1]) > min_size:
            ip_addr = ip_network(u"{0}".format(cidr))
            new_cidrs.add(str(ip_addr.supernet(new_prefix=min_size)))
        else:
            new_cidrs.add(cidr)
    return list(new_cidrs)
