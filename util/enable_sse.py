#!/usr/bin/env python
"""
Ensure server-side encryption (SSE) is enabled by default for ParallelCluster's S3 buckets in given set of regions.

It's assumed that the region to use for AWS calls has been configured per one of the methods described here:
https://docs.aws.amazon.com/credref/latest/refdocs/setting-global-region.html
"""

import json
import logging

import argparse
import boto3
from botocore.exceptions import ClientError


def configure_logging():
    """Enable INFO-level logging."""
    logging.basicConfig(level=logging.INFO)


def get_default_regions():
    """Get the regions whose buckets should be checked."""
    regions = [
        region.get("RegionName") for region in boto3.client("ec2").describe_regions(AllRegions=True).get("Regions")
    ]
    return regions


def credential_arg_type(credential_arg):
    """Turn 4-tuple passed to --credential into dict with keys "region", "endpoint", "role_arn", and "external_id"."""
    names = ("region", "endpoint", "role_arn", "external_id")
    values = tuple(credential_arg.strip().split(","))
    if len(names) != len(values):
        raise Exception(f"--credential expects arg of the form {' '.join(names)}")
    return {name: value.strip() for name, value in zip(names, values)}


def parse_args():
    """Parse command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    args = [
        {
            "name": "--bucket-name-format",
            "add_argument_kwargs": {
                "help": "Template string to use for constructing bucket names for a given region.",
                "default": "{region}-aws-parallelcluster",
            },
        },
        {
            "name": "--credential",
            "add_argument_kwargs": {
                "help": (
                    "Credentials to use for assuming a role in an opt-in account in the form "
                    "(region, STS endpoint URL, Role ARN, external ID)"
                ),
                "action": "append",
                "type": credential_arg_type,
            },
        },
        {
            "name": "--dry-run",
            "add_argument_kwargs": {
                "help": "Print information regarding how SSE would have been enabled instead of actually enabling it.",
                "action": "store_true",
            },
        },
        {
            "name": "--regions",
            "default_transform": lambda default_val: ",".join(default_val),
            "add_argument_kwargs": {
                "help": "CSV list of regions whose buckets to enable SSE for.",
                "type": lambda arg: arg.split(","),
                "default": get_default_regions(),
            },
        },
        {
            "name": "--unsupported-regions",
            "default_transform": lambda default_val: ",".join(default_val),
            "add_argument_kwargs": {
                "help": "CSV list of regions whose buckets to enable SSE for.",
                "type": lambda arg: arg.split(","),
                "default": ["ap-northeast-3"],
            },
        },
    ]
    for arg in args:
        if arg.get("add_argument_kwargs").get("default"):
            default_transform = arg.get("default_transform", lambda default_val: default_val)
            default_in_help_msg = default_transform(arg.get("add_argument_kwargs").get("default"))
            arg["add_argument_kwargs"]["help"] = " ".join(
                (arg.get("add_argument_kwargs").get("help"), f" Default: {default_in_help_msg}")
            )
        parser.add_argument(arg.get("name"), **arg.get("add_argument_kwargs"))
    return parser.parse_args()


def get_opt_in_region_boto3_client_kwargs(credential_info):
    """Return information used to assume role in opt-in account characterized by credential_info."""
    assume_role_response = boto3.client("sts", endpoint_url=credential_info.get("endpoint")).assume_role(
        RoleArn=credential_info.get("role_arn"),
        ExternalId=credential_info.get("external_id"),
        RoleSessionName="EnableSSE",
    )
    return {
        "region_name": credential_info.get("region"),
        "aws_access_key_id": assume_role_response.get("Credentials", {}).get("AccessKeyId"),
        "aws_secret_access_key": assume_role_response.get("Credentials", {}).get("SecretAccessKey"),
        "aws_session_token": assume_role_response.get("Credentials", {}).get("SessionToken"),
    }


def map_opt_in_region_to_cred_infos(opt_in_credential_dicts):
    """Return dict mapping opt-in region names to credential info dicts as returned by credential_arg_type."""
    if not opt_in_credential_dicts:
        return {}
    return {
        opt_in_credential_dict.get("region"): opt_in_credential_dict
        for opt_in_credential_dict in opt_in_credential_dicts
    }


def get_s3_client_for_region(region, opt_in_region_to_creds_tuple):
    """Return S3 client to use for the given region based on whether it's an opt-in region."""
    boto3_client_kwargs = {}
    if region in opt_in_region_to_creds_tuple:
        boto3_client_kwargs.update(get_opt_in_region_boto3_client_kwargs(opt_in_region_to_creds_tuple.get(region)))
    return boto3.client("s3", **boto3_client_kwargs)


def get_sse_settings(bucket, s3_client):
    """
    Return the response from calling s3:GetBucketEncryption for bucket.

    Return value is a dict like JSON of the form...

    {
      "ResponseMetadata": {
        "RequestId": "...",
        "HostId": "...",
        "HTTPHeaders": {...},
        "RetryAttempts": 0
      },
      "ServerSideEncryptionConfiguration": {
        "Rules": [
          {
            "ApplyServerSideEncryptionByDefault": {
              "SSEAlgorithm": "AES256"
            },
            "BucketKeyEnabled": false
          }
        ]
      }
    }
    """
    response = s3_client.get_bucket_encryption(Bucket=bucket)
    logging.info("GetBucketEncryption response for bucket %s:\n%s", bucket, json.dumps(response, indent=2))
    return response


def sse_is_enabled(bucket, s3_client):
    """Return a boolean describing whether SSE is enabled for bucket."""
    try:
        sse_settings = get_sse_settings(bucket, s3_client)

        for rule in sse_settings.get("ServerSideEncryptionConfiguration", {}).get("Rules", []):
            if all(
                [
                    rule.get("ApplyServerSideEncryptionByDefault", {}).get("SSEAlgorithm", "") == "AES256",
                    not rule.get("BucketKeyEnabled"),
                ]
            ):
                return True
    except ClientError as client_err:
        if client_err.response.get("Error", {}).get("Code") == "ServerSideEncryptionConfigurationNotFoundError":
            logging.info("ServerSideEncryptionConfigurationNotFoundError suggests SSE not enabled for %s", bucket)
            return False
        else:
            logging.error(
                "Unexpected ClientError. Error code '%s' Message: '%s'",
                client_err.response.get("Error", {}).get("Code"),
                client_err.response.get("Error", {}).get("Message"),
            )
        raise
    return False


def enable_sse(bucket, s3_client, dry_run):
    """Enable SSE for bucket."""
    logging.info("Enabling SSE for bucket %s", bucket)
    sse_config = {
        "Rules": [
            {
                "ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"},
                "BucketKeyEnabled": False,
            }
        ]
    }
    params = {"Bucket": bucket, "ServerSideEncryptionConfiguration": sse_config}
    if dry_run:
        logging.info(
            "DRYRUN - Would have called s3:PutBucketEncryption with these params:\n%s", json.dumps(params, indent=2)
        )
    else:
        try:
            s3_client.put_bucket_encryption(Bucket=bucket, ServerSideEncryptionConfiguration=sse_config)
        except ClientError as client_err:
            logging.error(
                "Unexpected ClientError. Error code '%s' Message: '%s'",
                client_err.response.get("Error", {}).get("Code"),
                client_err.response.get("Error", {}).get("Message"),
            )


def enable_sse_for_buckets_in_regions(regions, bucket_name_format, dry_run, opt_in_region_to_creds):
    """Enable SSE for the buckets in the given list of regions named per the given format."""
    for region in regions:
        s3_client = get_s3_client_for_region(region, opt_in_region_to_creds)
        bucket_name = bucket_name_format.format(region=region)
        logging.info("Enabling SSE for bucket %s in region %s", bucket_name, region)
        if sse_is_enabled(bucket_name, s3_client):
            logging.info("SSE is already enabled for bucket %s in region %s", bucket_name, region)
        else:
            enable_sse(bucket_name, s3_client, dry_run)


def main():
    """Run the script."""
    args = parse_args()
    configure_logging()
    enable_sse_for_buckets_in_regions(
        args.regions, args.bucket_name_format, args.dry_run, map_opt_in_region_to_cred_infos(args.credential)
    )


if __name__ == "__main__":
    main()
