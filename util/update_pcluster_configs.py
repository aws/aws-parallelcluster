#!/usr/bin/python
# Copyright 2019 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License").
# You may not use this file except in compliance with the License.
# A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file.
# This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, express or implied.
# See the License for the specific language governing permissions and limitations under the License.
import collections
import json
import logging
import os
import re
from abc import ABC, abstractmethod
from urllib.request import urlopen

import argparse
import boto3
from botocore.exceptions import ClientError, EndpointConnectionError

from jsonschema import validate
from s3_factory import S3DocumentManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")

PARTITIONS = ["commercial", "china", "govcloud"]
CONFIG_FILES = ["instances", "feature_whitelist"]
PARTITION_TO_MAIN_REGION = {"commercial": "us-east-1", "govcloud": "us-gov-west-1", "china": "cn-north-1"}
PARTITION_TO_PRICING_FILE_REGION = {"commercial": "us-east-1", "govcloud": "us-east-1", "china": "cn-north-1"}
FILE_TO_S3_PATH = {"instances": "instances/instances.json", "feature_whitelist": "features/feature_whitelist.json"}


def validate_document(old_doc, new_doc):
    """
    Diff's two dict object and checks the new_doc is a superset of old doc.

    :param old_doc: old object to diff
    :param new_doc: new object to diff
    :return: Raises an exception / logs diffs. Nothing returned.
    """
    try:
        import dictdiffer

        logging.info("Found following diffs: %s", list(dictdiffer.diff(old_doc, new_doc)))
    except ImportError:
        logging.warning("Install dictdiffer if you want to display diffs: pip install dictdiffer")

    logging.info("Found the following new root keys: %s", new_doc.keys() - old_doc.keys())
    logging.info("Checking that the new configuration file includes the old entries.")
    _assert_document_is_included(old_doc, new_doc)


def _assert_document_is_included(doc_to_be_included, doc):
    for k, v in doc_to_be_included.items():
        if k not in doc:
            raise Exception(f"Key {k} not found in new doc")
        if isinstance(v, collections.Mapping):
            _assert_document_is_included(v, doc[k])
        elif isinstance(v, list):
            if not all(elem in doc[k] for elem in v):
                raise Exception(f"Old list {v} is not included in new list {doc[k]}")
        else:
            if v != doc[k]:
                raise Exception(f"Old value {v} does not match new value {doc[k]}")


class _ConfigGenerator(ABC):
    @abstractmethod
    def generate(self, args, region, credentials):
        pass


class _InstancesConfigGenerator(_ConfigGenerator):
    SCHEMA = {
        "type": "object",
        "patternProperties": {
            r"^[a-z0-9-]+\.[a-z0-9]+$": {
                "type": "object",
                "properties": {
                    "vcpus": {"type": "string", "pattern": r"^\d+$"},
                    "memory": {"type": "string", "pattern": r"^\d+(\.\d+)?$"},
                    "gpus": {"type": "string", "pattern": r"^\d+$"},
                },
                "required": ["vcpus", "memory"],
            }
        },
        "additionalProperties": False,
    }

    def __init__(self):
        self.__pricing_file_cache = None

    def generate(self, args, region, credentials):
        pricing_file = self._read_pricing_file(PARTITION_TO_PRICING_FILE_REGION[args.partition], args.pricing_file)
        instances_config = self._parse_pricing_file(pricing_file)
        logging.info("Validating doc against its schema")
        validate(instance=instances_config, schema=self.SCHEMA)
        return instances_config

    # {
    #   "formatVersion" : "v1.0",
    #   "disclaimer" : "This pricing list is for informational purposes only...",
    #   "offerCode" : "AmazonEC2",
    #   "version" : "20191024230914",
    #   "publicationDate" : "2019-10-24T23:09:14Z",
    #   "products" : {
    #     "JF25X344J7WKTCG7" : {
    #       "sku" : "JF25X344J7WKTCG7",
    #       "productFamily" : "Compute Instance",
    #       "attributes" : {
    #         "servicecode" : "AmazonEC2",
    #         "location" : "EU (London)",
    #         "locationType" : "AWS Region",
    #         "instanceType" : "m4.large",
    #         "currentGeneration" : "Yes",
    #         "instanceFamily" : "General purpose",
    #         "vcpu" : "2",
    #         "physicalProcessor" : "Intel Xeon E5-2676 v3 (Haswell)",
    #         "clockSpeed" : "2.4 GHz",
    #         "memory" : "8 GiB",
    #         "storage" : "EBS only",
    #         "networkPerformance" : "Moderate",
    #         "processorArchitecture" : "64-bit",
    #         "tenancy" : "Dedicated",
    #         "operatingSystem" : "Windows",
    #         "licenseModel" : "No License required",
    #         "usagetype" : "EUW2-UnusedDed:m4.large",
    #         "operation" : "RunInstances:0202",
    #         "capacitystatus" : "UnusedCapacityReservation",
    #         "dedicatedEbsThroughput" : "450 Mbps",
    #         "ecu" : "6.5",
    #         "enhancedNetworkingSupported" : "Yes",
    #         "instancesku" : "FPPNXJEHX35MRPZJ",
    #         "normalizationSizeFactor" : "4",
    #         "preInstalledSw" : "SQL Web",
    #         "processorFeatures" : "Intel AVX; Intel AVX2; Intel Turbo",
    #         "servicename" : "Amazon Elastic Compute Cloud"
    #       }
    #     },
    #     ...
    @staticmethod
    def _parse_pricing_file(pricing_file):
        instances = {}
        for _, product in pricing_file.get("products").items():
            if "Compute Instance" in product.get("productFamily"):
                instance = product.get("attributes")
                instances[instance.get("instanceType")] = {"vcpus": instance.get("vcpu")}
                # Sample memory input: {"memory" : "1,952.5 GiB"}
                memory = instance.get("memory")
                memory = memory.replace(",", "")  # Remove comma delimiter
                memory = memory.replace(" GiB", "")  # Remove GiB
                instances[instance.get("instanceType")]["memory"] = memory
                # Adding instance's gpu information to instances.json
                if "gpu" in instance:
                    instances[instance.get("instanceType")]["gpu"] = instance.get("gpu")
        return instances

    def _read_pricing_file(self, region=None, pricing_file=None):
        if not self.__pricing_file_cache:
            if pricing_file:
                logging.info("Reading pricing file...")
                with open(pricing_file) as data_file:
                    self.__pricing_file_cache = json.load(data_file)
            else:
                self.__pricing_file_cache = self._download_pricing_file(region)
        return self.__pricing_file_cache

    @staticmethod
    def _download_pricing_file(region):
        logging.info("Downloading pricing file...This might take a while.")
        url_prefix = f"https://pricing.{region}.amazonaws.com{'.cn' if region.startswith('cn-') else ''}"
        index_json = _read_json_from_url(f"{url_prefix}/offers/v1.0/aws/index.json")
        ec2_pricing_url = index_json["offers"]["AmazonEC2"]["currentVersionUrl"]
        return _read_json_from_url(f"{url_prefix}{ec2_pricing_url}")


class _FeatureWhitelistConfigGenerator(_ConfigGenerator):
    SCHEMA = {
        "type": "object",
        "properties": {
            "Features": {
                "type": "object",
                "properties": {
                    "efa": {
                        "type": "object",
                        "properties": {
                            "instances": {
                                "type": "array",
                                "items": {"type": "string", "pattern": r"^[a-z0-9-]+\.[a-z0-9]+$"},
                            }
                        },
                        "required": ["instances"],
                    },
                    "batch": {
                        "type": "object",
                        "properties": {
                            "instances": {
                                "type": "array",
                                "items": {"type": "string", "pattern": r"^[a-z0-9-]+(\.[a-z0-9]+)?$"},
                            }
                        },
                        "required": ["instances"],
                    },
                },
                "required": ["efa", "batch"],
            }
        },
        "additionalProperties": False,
    }

    def generate(self, args, region, credentials):
        batch_instances = self._get_batch_instance_whitelist(region, credentials)
        config = {"Features": {"efa": {"instances": args.efa_instances}, "batch": {"instances": batch_instances}}}
        logging.info("Validating doc against its schema")
        validate(instance=config, schema=self.SCHEMA)
        return config

    @staticmethod
    def _get_batch_instance_whitelist(region, credentials):
        instances = []
        # try to create a dummy compute environment
        batch_client = boto3.client("batch", region_name=region, **credentials)

        try:
            batch_client.create_compute_environment(
                computeEnvironmentName="dummy",
                type="MANAGED",
                computeResources={
                    "type": "EC2",
                    "minvCpus": 0,
                    "maxvCpus": 0,
                    "instanceTypes": ["p8.84xlarge"],  # instance type must not exist
                    "subnets": ["subnet-12345"],  # security group, subnet and role aren't checked
                    "securityGroupIds": ["sg-12345"],
                    "instanceRole": "ecsInstanceRole",
                },
                serviceRole="AWSBatchServiceRole",
            )
        except ClientError as e:
            match = re.search(r"be one of \[(.*)\]", e.response.get("Error").get("Message"))
            if match:
                instances = match.groups(0)[0].split(", ")
            else:
                raise Exception(f"Invalid Error message, could not determine instance whitelist: {e}")
        except EndpointConnectionError:
            logging.warning(
                "Could not connect to the batch endpoint for region %s. Probably Batch is not available.", region
            )

        return instances


CONFIG_FILE_TO_GENERATOR = {
    "instances": _InstancesConfigGenerator().generate,
    "feature_whitelist": _FeatureWhitelistConfigGenerator().generate,
}


def _read_json_from_url(url):
    response = urlopen(url)
    return json.loads(response.read().decode("utf-8"))


def get_aws_regions(partition):
    ec2 = boto3.client("ec2", region_name=PARTITION_TO_MAIN_REGION[partition])
    return set(r.get("RegionName") for r in ec2.describe_regions().get("Regions"))


def _validate_args(args, parser):
    if args.config_files and "feature_whitelist" in args.config_files and not args.efa_instances:
        parser.error("feature_whitelist requires --efa-instances to be specified")

    if not args.rollback_file_path and not args.regions:
        parser.error("please specify --regions or --autodetect-regions")


def retrieve_sts_credentials(credentials, partition):
    """
    Given credentials from cli, returns a json credentials object.

    {
        'us-east-1': {
            'aws_access_key_id': 'sjkdnf',
            'aws_secret_access_key': 'ksjdfkjsd',
            'aws_session_token': 'skajdfksdjn'
        }
        ...
    }

    :param credentials: STS credential endpoint, in the format <region>,<endpoint>,<ARN>,<externalId>.
                        Could be specified multiple times
    :param partition: [commercial|china|govcloud]
    :return: sts credentials json
    """
    sts_credentials = {}
    for credential in credentials:
        region, endpoint, arn, external_id = credential
        sts = boto3.client("sts", region_name=PARTITION_TO_MAIN_REGION[partition], endpoint_url=endpoint)
        assumed_role_object = sts.assume_role(
            RoleArn=arn, ExternalId=external_id, RoleSessionName=region + "-upload_instance_slot_map_sts_session"
        )
        sts_credentials[region] = {
            "aws_access_key_id": assumed_role_object["Credentials"].get("AccessKeyId"),
            "aws_secret_access_key": assumed_role_object["Credentials"].get("SecretAccessKey"),
            "aws_session_token": assumed_role_object["Credentials"].get("SessionToken"),
        }

    return sts_credentials


def _parse_args():
    def _aws_credentials_type(value):
        return tuple(value.strip().split(","))

    def _file_type(value):
        if not os.path.isfile(value):
            raise argparse.ArgumentTypeError("'{0}' is not a valid file".format(value))
        return value

    parser = argparse.ArgumentParser(
        description="Update pcluster config files. Currently supports instances.json and feature_whitelist.json"
    )

    parser.add_argument(
        "--partition", choices=PARTITIONS, help="AWS Partition where to update the files", required=True
    )
    parser.add_argument(
        "--credentials",
        help="STS credential endpoint, in the format <region>,<endpoint>,<ARN>,<externalId>."
        "Could be specified multiple times",
        required=False,
        nargs="+",
        type=_aws_credentials_type,
        default=[],
    )
    parser.add_argument(
        "--deploy",
        action="store_true",
        help="If deploy is false, we will perform a dryrun and no file will be pushed to buckets",
        default=False,
        required=False,
    )
    parser.add_argument(
        "--skip-validation",
        action="store_true",
        help="WARNING: be careful when setting this flag. All validations are disabled",
        default=False,
        required=False,
    )
    parser.add_argument(
        "--regions",
        type=str,
        help="If not specified ec2.describe_regions is used to retrieve regions",
        required=False,
        nargs="+",
        default=[],
    )
    parser.add_argument(
        "--autodetect-regions",
        action="store_true",
        help="If set ec2.describe_regions is used to retrieve regions. "
        "Additional regions can be specified with --regions",
        required=False,
        default=False,
    )
    parser.add_argument(
        "--bucket",
        type=str,
        help="Bucket to upload too, defaults to {region}-aws-parallelcluster",
        required=False,
        default="{region}-aws-parallelcluster",
    )
    parser.add_argument(
        "--efa-instances",
        type=str,
        help="Comma separated list of instances supported by EFA",
        required=False,
        nargs="+",
    )
    parser.add_argument(
        "--pricing-file", type=str, help="If not specified this will be downloaded automatically", required=False
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--rollback-file-path", help="Path to file containing the rollback information", type=_file_type)
    group.add_argument("--config-files", choices=CONFIG_FILES, help="Configurations to update", nargs="+")

    args = parser.parse_args()

    if args.autodetect_regions:
        args.regions.extend(get_aws_regions(args.partition))

    _validate_args(args, parser)
    return args


def _generate_docs(args, sts_credentials):
    files_to_upload = {}
    for file in args.config_files:
        files_to_upload[file] = {}
        for region in args.regions:
            logging.info("Generating config file %s in region %s", file, region)
            files_to_upload[file][region] = CONFIG_FILE_TO_GENERATOR[file](
                args, region, sts_credentials.get(region, {})
            )
    return files_to_upload


def _validate_documents_against_existing_version(args, files_to_upload, sts_credentials):
    for file in files_to_upload.keys():
        for region in args.regions:
            logging.info("Validating file %s in region %s", file, region)
            doc_manager = S3DocumentManager(region, sts_credentials.get(region))
            current_file = json.loads(doc_manager.download(args.bucket.format(region=region), FILE_TO_S3_PATH[file]))
            logging.info("Current version: %s", current_file)
            logging.info("New version: %s", files_to_upload[file][region])
            validate_document(current_file, files_to_upload[file][region])
            logging.info("Document is valid", files_to_upload[file][region])


def _generate_rollback_data(args, files_to_upload, sts_credentials):
    rollback_data = {}
    for file in files_to_upload.keys():
        rollback_data[FILE_TO_S3_PATH[file]] = {}
        for region in args.regions:
            doc_manager = S3DocumentManager(region, sts_credentials.get(region))
            rollback_data[FILE_TO_S3_PATH[file]][region] = doc_manager.get_current_version(
                args.bucket.format(region=region), FILE_TO_S3_PATH[file], raise_on_object_not_found=False
            )
    logging.info("Rollback data:\n%s", json.dumps(rollback_data, indent=2))
    with open("rollback-data.json", "w") as outfile:
        json.dump(rollback_data, outfile, indent=2)


def _upload_documents(args, files_to_upload, sts_credentials):
    for file in files_to_upload.keys():
        for region in args.regions:
            logging.info("Uploading file %s in region %s", file, region)
            doc_manager = S3DocumentManager(region, sts_credentials.get(region))
            doc_manager.upload(
                args.bucket.format(region=region),
                FILE_TO_S3_PATH[file],
                json.dumps(files_to_upload[file][region]),
                dryrun=not args.deploy,
            )


def _execute_rollback(args, sts_credentials):
    with open(args.rollback_file_path) as rollback_file:
        rollback_data = json.load(rollback_file)
        logging.info("Loaded rollback data:\n%s", json.dumps(rollback_data, indent=2))

        # Rollback file format
        # {
        #     "s3_object": {
        #         "region": "version-id",
        #         "region": "version-id"
        #     },
        #     "s3_object": {
        #         "region": "version-id",
        #         "region": "version-id"
        #     }
        # }
        for s3_object in rollback_data:
            for region, version_id in rollback_data[s3_object].items():
                object_manager = S3DocumentManager(region, sts_credentials.get(region))
                object_manager.revert_object(args.bucket.format(region=region), s3_object, version_id, not args.deploy)


def main():
    args = _parse_args()
    logging.info("Parsed cli args: %s", vars(args))

    sts_credentials = retrieve_sts_credentials(args.credentials, args.partition)

    if args.rollback_file_path:
        _execute_rollback(args, sts_credentials)
    else:
        logging.info("Generating all documents to upload")
        files_to_upload = _generate_docs(args, sts_credentials)

        if not args.skip_validation:
            logging.info("Validating all documents to upload")
            _validate_documents_against_existing_version(args, files_to_upload, sts_credentials)

        logging.info("Generating rollback data")
        _generate_rollback_data(args, files_to_upload, sts_credentials)

        logging.info("Uploading documents...")
        _upload_documents(args, files_to_upload, sts_credentials)

        logging.info(
            "Summary of uploaded docs:\n%s",
            json.dumps({k: list(v.keys()) for k, v in files_to_upload.items()}, indent=2),
        )
        if not args.deploy:
            logging.warning(
                "Documents not uploaded since --deploy flag not specified. Rerun with --deploy flag to upload"
            )


if __name__ == "__main__":
    main()
