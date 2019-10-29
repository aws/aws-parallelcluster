import collections
import json
import logging
import re
from abc import ABC, abstractmethod
from urllib.request import urlopen

import argparse
import boto3
from botocore.exceptions import ClientError, EndpointConnectionError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")

PARTITIONS = ["commercial", "china", "govcloud"]
CONFIG_FILES = ["instances", "feature_whitelist"]
PARTITION_TO_MAIN_REGION = {"commercial": "us-east-1", "govcloud": "us-gov-west-1", "china": "cn-north-1"}
FILE_TO_S3_PATH = {"instances": "instances/instances.json", "feature_whitelist": "features/feature_whitelist.json"}


class S3JsonDocumentManager:
    def __init__(self, region, credentials=None):
        self._region = region
        self._credentials = credentials or {}

    def download(self, s3_bucket, document_s3_path):
        try:
            s3 = boto3.resource("s3", region_name=self._region, **self._credentials)
            instances_file_content = s3.Object(s3_bucket, document_s3_path).get()["Body"].read()
            return json.loads(instances_file_content)
        except Exception as e:
            logging.error(
                "Failed when downloading file %s from bucket %s in region %s with error %s",
                document_s3_path,
                s3_bucket,
                self._region,
                e,
            )
            raise

    def upload(self, s3_bucket, s3_key, document_data, dryrun=True):
        try:
            if not dryrun:
                object = boto3.resource("s3", region_name=self._region, **self._credentials).Object(s3_bucket, s3_key)
                object.put(Body=json.dumps(document_data), ACL="public-read")
            else:
                logging.info(
                    "Dryrun mode enabled. The following file would have been uploaded to %s/%s:\n%s",
                    s3_bucket,
                    s3_key,
                    json.dumps(document_data),
                )
        except Exception as e:
            logging.error(
                "Failed when uploading file %s to bucket %s in region %s with error %s",
                s3_key,
                s3_bucket,
                self._region,
                e,
            )
            raise

    @staticmethod
    def validate_document(old_doc, new_doc):
        try:
            import dictdiffer

            logging.info("Found following diffs: %s", list(dictdiffer.diff(old_doc, new_doc)))
        except ImportError:
            logging.warning("Install dictdiffer if you want to display diffs: pip install dictdiffer")

        logging.info("Checking that the new configuration file includes the old entries.")
        S3JsonDocumentManager._assert_document_is_included(old_doc, new_doc)

    @staticmethod
    def _assert_document_is_included(doc_to_be_included, doc):
        for k, v in doc_to_be_included.items():
            if k not in doc:
                raise Exception(f"Key {k} not found in new doc")
            if isinstance(v, collections.Mapping):
                S3JsonDocumentManager._assert_document_is_included(v, doc[k])
            elif isinstance(v, list):
                if not all(elem in doc[k] for elem in v):
                    raise Exception(f"Old list {v} is not included in new list {doc[k]}")
            else:
                if v != doc[k]:
                    raise Exception(f"Old value {v} does not match new value {doc[k]}")


class ConfigGenerator(ABC):
    @abstractmethod
    def generate(self, args, region, credentials):
        pass


class InstancesConfigGenerator(ConfigGenerator):
    def __init__(self):
        self.__pricing_file_cache = None

    def generate(self, args, region, credentials):
        pricing_file = self._read_pricing_file(PARTITION_TO_MAIN_REGION[args.partition], args.pricing_file)
        return self._parse_pricing_file(pricing_file)

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
                # Sample memory input: {"memory" : "30 GiB"}
                instances[instance.get("instanceType")]["memory"] = instance.get("memory")
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
        url_prefix = f"https://pricing.{region}.amazonaws.com"
        index_json = _read_json_from_url(f"{url_prefix}/offers/v1.0/aws/index.json")
        ec2_pricing_url = index_json["offers"]["AmazonEC2"]["currentVersionUrl"]
        return _read_json_from_url(f"{url_prefix}{ec2_pricing_url}")


class FeatureWhitelistConfigGenerator(ConfigGenerator):
    def generate(self, args, region, credentials):
        batch_instances = self._get_batch_instance_whitelist(region, credentials)
        return {"Features": {"efa": {"instances": args.efa_instances}, "batch": {"instances": batch_instances}}}

    @staticmethod
    def _get_batch_instance_whitelist(region, credentials):
        instances = []
        # try to create a dummy compute environmment
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
    "instances": InstancesConfigGenerator().generate,
    "feature_whitelist": FeatureWhitelistConfigGenerator().generate,
}


def _read_json_from_url(url):
    response = urlopen(url)
    return json.loads(response.read().decode("utf-8"))


def _get_aws_regions(partition):
    ec2 = boto3.client("ec2", region_name=PARTITION_TO_MAIN_REGION[partition])
    return set(sorted(r.get("RegionName") for r in ec2.describe_regions().get("Regions")))


def _validate_args(args, parser):
    if "feature_whitelist" in args.config_files and not args.efa_instances:
        parser.error("feature_whitelist requires --efa-instances to be specified")


def _retrieve_sts_credentials(credentials, partition):
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

    parser = argparse.ArgumentParser(
        description="Update pcluster config files. Currently supports instances.json and feature_whitelist.json"
    )

    parser.add_argument(
        "--partition", choices=PARTITIONS, help="AWS Partition where to update the files", required=True
    )
    parser.add_argument(
        "--config-files", choices=CONFIG_FILES, help="Configurations to update", required=True, nargs="+"
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
    )
    parser.add_argument(
        "--autodetect-regions",
        action="store_true",
        help="If set ec2.describe_regions is used to retrieve regions. "
        "Additional regions can be specified with --regions",
        required=False,
        default="True",
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

    args = parser.parse_args()

    if args.autodetect_regions:
        args.regions.extend(_get_aws_regions(args.partition))

    _validate_args(args, parser)
    return args


if __name__ == "__main__":
    args = _parse_args()
    logging.info("Parsed cli args: %s", vars(args))

    sts_credentials = _retrieve_sts_credentials(args.credentials, args.partition)

    logging.info("Generating all documents to upload")
    files_to_upload = {}
    for file in args.config_files:
        files_to_upload[file] = {}
        for region in args.regions:
            logging.info("Generating config file %s in region %s", file, region)
            files_to_upload[file][region] = CONFIG_FILE_TO_GENERATOR[file](
                args, region, sts_credentials.get(region, {})
            )

    if not args.skip_validation:
        logging.info("Validating all documents to upload")
        for file in files_to_upload.keys():
            for region in args.regions:
                logging.info("Validating file %s in region %s", file, region)
                doc_manager = S3JsonDocumentManager(region, sts_credentials.get(region))
                current_file = doc_manager.download(args.bucket.format(region=region), FILE_TO_S3_PATH[file])
                logging.info("Current version: %s", current_file)
                logging.info("New version: %s", files_to_upload[file][region])
                doc_manager.validate_document(current_file, files_to_upload[file][region])
                logging.info("Document is valid", files_to_upload[file][region])

    logging.info("Uploading documents...")
    for file in files_to_upload.keys():
        for region in args.regions:
            logging.info("Uploading file %s in region %s", file, region)
            doc_manager = S3JsonDocumentManager(region, sts_credentials.get(region))
            current_file = doc_manager.upload(
                args.bucket.format(region=region),
                FILE_TO_S3_PATH[file],
                files_to_upload[file][region],
                dryrun=not args.deploy,
            )
    if not args.deploy:
        logging.info("Documents not uploaded since --deploy flag not specified. Rerun with --deploy flag to upload")

    logging.info("Summary of uploaded docs:\n%s", {k: list(v.keys()) for k, v in files_to_upload.items()})
