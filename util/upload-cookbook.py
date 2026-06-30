#!/usr/bin/python
#
# Copyright 2019-2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not
# use this file except in compliance with the License. A copy of the License
# is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is
# distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, express or implied. See the License for the specific language
# governing permissions and limitations under the License.
#
#
# Upload cookbook
#
# usage: ./upload-cookbook.py --regions "<region>[,<region>, ...]" --cookbook-archive-path "<path to cookbook tgz>" \
# --partition <partition> \
# [--unsupportedregions "<region>[, <region>, ...]"] [--dryrun] [--override] \
# [--credential <region>,<endpoint>,<arn>,<role>]*
import os
import sys
from importlib.metadata import version

import argparse
from s3_uploader import S3Uploader, add_common_arguments

_COOKBOOKS_DIR = "parallelcluster/{version}/cookbooks".format(version=version("aws-parallelcluster"))


def _parse_args(uploader):
    parser = argparse.ArgumentParser(description="Uploads cookbook to S3")
    add_common_arguments(parser)
    parser.add_argument("--cookbook-archive-path", type=str, help="Cookbook archive path", required=True)
    return uploader.resolve_args(parser.parse_args())


def main():
    uploader = S3Uploader(artifact_dir=_COOKBOOKS_DIR, sts_session_name="upload_cfn_templates_sts_session")
    args = _parse_args(uploader)

    # Check if archive exists
    if not os.path.exists(args.cookbook_archive_path):
        print("Cookbook archive {0} not found".format(args.cookbook_archive_path))
        sys.exit(1)

    base_name = os.path.splitext(os.path.basename(args.cookbook_archive_path))[0]
    uploader.md5sum(args.cookbook_archive_path, "{0}.md5".format(base_name))

    for region in args.regions:
        s3 = uploader.create_s3_client(region)
        bucket_name = uploader.get_bucket_name(args, region)

        s3_key = _COOKBOOKS_DIR + "/" + base_name + ".tgz"
        print("Listing cookbook for region: {0}, bucket: {1}, key: {2}".format(region, bucket_name, s3_key))
        uploader.aws_s3_ls(s3, region, bucket_name, s3_key)

    if len(uploader.ls_error_array) > 0 and not args.override:
        print("We know the cookbook archives are already there, in this round we need to upload the .date files!")
        print("Failed to push cookbook, already present for regions: {0} ".format(" ".join(uploader.ls_error_array)))
        sys.exit(1)
    elif len(uploader.ls_error_array) > 0 and args.override:
        print("Some or all of the cookbook archives are already there but OVERRIDE=true")

    for region in args.regions:
        s3 = uploader.create_s3_client(region)
        bucket_name = uploader.get_bucket_name(args, region)

        if args.override:
            print("Backup cookbook for region: {0}".format(region))
            uploader.aws_s3_bck(s3, args, region, bucket_name, base_name + ".tgz")
            uploader.aws_s3_bck(s3, args, region, bucket_name, base_name + ".md5")
            uploader.aws_s3_bck(s3, args, region, bucket_name, base_name + ".tgz.date")

        print("Pushing cookbook for region: {0}".format(region))
        uploader.aws_s3_cp(s3, args, region, bucket_name, _COOKBOOKS_DIR, args.cookbook_archive_path)
        uploader.aws_s3_cp(s3, args, region, bucket_name, _COOKBOOKS_DIR, base_name + ".md5")

        if not args.dryrun:
            # Stores LastModified info into .tgz.date file and uploads it back to bucket
            with open(base_name + ".tgz.date", "w+") as f:
                response = s3.head_object(Bucket=bucket_name, Key=_COOKBOOKS_DIR + "/" + base_name + ".tgz")
                f.write(response.get("LastModified").strftime("%Y-%m-%d_%H-%M-%S"))

            uploader.aws_s3_cp(s3, args, region, bucket_name, _COOKBOOKS_DIR, base_name + ".tgz.date")
        else:
            print("File {0}.{1} not stored to bucket {2} due to dryrun mode".format(base_name, "tgz.date", bucket_name))

    if len(uploader.bck_error_array) > 0:
        print("Failed to backup cookbook for region ({0})".format(" ".join(uploader.bck_error_array)))

    if len(uploader.cp_error_array) > 0:
        print("Failed to push cookbook for region ({0})".format(" ".join(uploader.cp_error_array)))
        sys.exit(1)


if __name__ == "__main__":
    main()
