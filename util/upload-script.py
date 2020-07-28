import json
import logging
import os

import argparse
from s3_factory import S3DocumentManager
from update_pcluster_configs import get_aws_regions, retrieve_sts_credentials

LOGGER = logging.getLogger(__name__)
logging.basicConfig(format="%(asctime)s - %(levelname)s - %(module)s - %(message)s", level=logging.INFO)
PARTITIONS = ["commercial", "china", "govcloud"]


def _generate_rollback_data(bucket, regions, s3_path, sts_credentials):
    rollback_data = {}
    rollback_data[s3_path] = {}
    for region in regions:
        object_manager = S3DocumentManager(region, sts_credentials.get(region))
        try:
            rollback_data[s3_path][region] = object_manager.get_current_version(bucket.format(region=region), s3_path)
        except Exception:
            pass
    logging.info("Rollback data:\n%s", json.dumps(rollback_data, indent=2))
    with open("rollback-data.json", "w") as outfile:
        json.dump(rollback_data, outfile, indent=2)


def _execute_rollback(rollback_file_path, sts_credentials, bucket, deploy):
    with open(rollback_file_path) as rollback_file:
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
                object_manager.revert_object(bucket.format(region=region), s3_object, version_id, not deploy)


def _upload_documents(regions, bucket, s3_path, script, sts_credentials, deploy, override):
    for region in regions:
        logging.info("Uploading file %s in region %s", s3_path, region)
        doc_manager = S3DocumentManager(region, sts_credentials.get(region))
        exists = doc_manager.version_exists(s3_bucket=bucket.format(region=region), document_s3_path=s3_path)
        if exists and not override:
            logging.warning(f"Version s3://{bucket}/{s3_path} exists, skipping upload.")
        else:
            with open(script, "rb") as data:
                doc_manager.upload(bucket.format(region=region), s3_path, data, dryrun=not deploy)


if __name__ == "__main__":

    def _aws_credentials_type(value):
        return tuple(value.strip().split(","))

    def _file_type(value):
        if not os.path.isfile(value):
            raise argparse.ArgumentTypeError(f"'{value}' is not a valid file")
        return value

    # parse inputs
    parser = argparse.ArgumentParser(description="Upload scripts to S3")
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
    parser.add_argument("--version", type=str, help="Version of the script", required=False)
    parser.add_argument("--override", action="store_true", help="Overwrite existing version.", default=False)
    parser.add_argument(
        "--key-path",
        type=str,
        help="S3 Keypath, if {version} is contained in the string, it's interpolated.",
        default="scripts/aws_impi-{version}.sh",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--rollback-file-path", help="Path to file containing the rollback information", type=_file_type)
    group.add_argument("--script", type=_file_type, help="Script to upload")

    args = parser.parse_args()

    # get regions if --autodetect-regions is set
    if args.autodetect_regions:
        args.regions = set(args.regions) | get_aws_regions(args.partition)

    if not args.rollback_file_path and not args.regions:
        parser.error("please specify --regions or --autodetect-regions")

    sts_credentials = retrieve_sts_credentials(args.credentials, args.partition)
    s3_path = args.key_path.format(version=args.version)

    if args.rollback_file_path:
        _execute_rollback(
            rollback_file_path=args.rollback_file_path,
            bucket=args.bucket,
            sts_credentials=sts_credentials,
            deploy=args.deploy,
        )
    else:
        logging.info("Generating rollback data")
        _generate_rollback_data(
            bucket=args.bucket, s3_path=s3_path, regions=args.regions, sts_credentials=sts_credentials
        )

        logging.info("Uploading documents...")
        _upload_documents(
            regions=args.regions,
            bucket=args.bucket,
            s3_path=s3_path,
            script=args.script,
            sts_credentials=sts_credentials,
            deploy=args.deploy,
            override=args.override,
        )

        if not args.deploy:
            logging.warning(
                "Documents not uploaded since --deploy flag not specified. Rerun with --deploy flag to upload"
            )
