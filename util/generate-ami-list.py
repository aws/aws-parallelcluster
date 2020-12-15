#!/usr/bin/python
#
# Copyright 2018 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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
# Search for AWS ParallelCluster AMIs and generate a list in json and txt format
#
# usage: ./generate-ami-list.py --version <aws-parallelcluster-version> --date <release-date>

import json
import re
from collections import OrderedDict

import argparse
import boto3
from botocore.exceptions import ClientError

from common import PARTITION_TO_MAIN_REGION, PARTITIONS

DISTROS = OrderedDict(
    [
        ("alinux", "amzn"),
        ("alinux2", "amzn2"),
        ("centos7", "centos7"),
        ("centos8", "centos8"),
        ("ubuntu1604", "ubuntu-1604"),
        ("ubuntu1804", "ubuntu-1804"),
    ]
)
ARCHITECTURES_TO_MAPPING_NAME = {"x86_64": "AWSRegionOS2AMIx86", "arm64": "AWSRegionOS2AMIarm64"}


def get_initialized_mappings_dicts():
    """
    Get dict with two keys initialized to empty dicts.

    This is the same structure as the portion of the CFN template's Mappings that contains default AMIs.
    """
    return {mapping_name: {} for _, mapping_name in ARCHITECTURES_TO_MAPPING_NAME.items()}


def get_placeholder_region_dict():
    """
    Return a dict with keys equal to those in DISTROS and with values of "UNSUPPORTED".

    The placeholder string expresses the fact that there's no AMI available for the given OS in that region.

    This is necessary to support ARM because of the way CloudFormation evaluates the template. A conditional expression
    chooses an AMI from either the x86_64 or ARM mappings. CloudFormation evaluates both of these expressions before
    choosing one. If one of the mappings doesn't contain a result (as would be expected for OSes for which we don't
    build ARM AMIs) then cluster creation fails if placeholders aren't used.
    """
    return {distro_mapping_key: "UNSUPPORTED" for distro_mapping_key in DISTROS}


def get_ami_list_from_file(regions, cfn_template_file):
    """Read the AMI mappings from cfn_template_file for the given regions."""
    amis_json = get_initialized_mappings_dicts()

    with open(cfn_template_file) as cfn_file:
        # object_pairs_hook=OrderedDict allows to preserve input order
        cfn_data = json.load(cfn_file, object_pairs_hook=OrderedDict)

    current_amis = {}
    for mapping_name in amis_json:
        current_amis[mapping_name] = cfn_data.get("Mappings").get(mapping_name, {})
        for region_name in regions:
            if region_name in current_amis.get(mapping_name, []):
                # Ensure mapping for the region_name is sorted by OS name
                amis_json[mapping_name][region_name] = OrderedDict(
                    sorted(current_amis.get(mapping_name).get(region_name).items())
                )
            else:
                print(
                    "Warning: there are no AMIs in the region ({region}) within the mapping ({mapping})".format(
                        region=region_name, mapping=mapping_name
                    )
                )
    return amis_json


def get_ami_list_from_ec2(main_region, regions, owner, credentials, filters):
    """Get the AMI mappings structure given the constraints represented by the args."""
    amis_json = get_initialized_mappings_dicts()
    for region_name in regions:
        images_for_region = get_images_ec2(filters, owner, region_name)
        for architecture, mapping_name in ARCHITECTURES_TO_MAPPING_NAME.items():
            amis_json[mapping_name][region_name] = get_amis_for_architecture(images_for_region, architecture)

            if main_region == region_name:
                for credential in credentials:
                    credential_region = credential[0]
                    images_for_credential_region = get_images_ec2_credential(filters, main_region, credential)
                    amis_json[mapping_name][credential_region] = get_amis_for_architecture(
                        images_for_credential_region, architecture
                    )

    return amis_json


def get_amis_for_architecture(images, architecture):
    """Select the subset of images that have the given architecture."""
    distro_to_image_id = get_placeholder_region_dict()
    for image in images.get("Images"):
        for distro_mapping_key, distro_image_name_query_string in DISTROS.items():
            name_query_string = "-{0}-".format(distro_image_name_query_string)
            if name_query_string in image.get("Name") and image.get("Architecture") == architecture:
                distro_to_image_id[distro_mapping_key] = image.get("ImageId")
    # Ensure mapping is sorted by OS name before returning
    return OrderedDict(sorted(distro_to_image_id.items()))


def get_ami_list_by_git_refs(main_region, regions, cookbook_git_ref, node_git_ref, build_date, owner, credentials):
    """Get the ParallelCluster AMIs by querying EC2 based on git refs and build date."""
    filters = [
        {"Name": "tag:parallelcluster_cookbook_ref", "Values": ["%s" % cookbook_git_ref]},
        {"Name": "tag:parallelcluster_node_ref", "Values": ["%s" % node_git_ref]},
        {"Name": "name", "Values": ["aws-parallelcluster-*%s" % (build_date if build_date else "")]},
    ]
    return get_ami_list_from_ec2(main_region, regions, owner, credentials, filters)


def get_images_ec2_credential(filters, main_region, credential):
    """Get list of AMIs subject to filters after assuming the identity represented by credential."""
    credential_region = credential[0]
    credential_endpoint = credential[1]
    credential_arn = credential[2]
    credential_external_id = credential[3]
    match = re.search(r"arn:aws:iam::(.*?):", credential_arn)
    credential_owner = match.group(1)

    try:
        sts = boto3.client("sts", region_name=main_region, endpoint_url=credential_endpoint)
        assumed_role_object = sts.assume_role(
            RoleArn=credential_arn,
            ExternalId=credential_external_id,
            RoleSessionName=credential_region + "generate_ami_list_sts_session",
        )
        aws_credentials = assumed_role_object["Credentials"]

        ec2 = boto3.client(
            "ec2",
            region_name=credential_region,
            aws_access_key_id=aws_credentials.get("AccessKeyId"),
            aws_secret_access_key=aws_credentials.get("SecretAccessKey"),
            aws_session_token=aws_credentials.get("SessionToken"),
        )

        images = ec2.describe_images(Owners=[credential_owner], Filters=filters)
        return get_latest_images(images)
    except ClientError:
        print("Warning: non authorized in region '{0}', skipping".format(credential_region))
        pass


def get_images_ec2(filters, owner, region_name):
    """
    Get the list of AMIs owned by owner, present in region_name, and subject to filters.

    NOTE: this call to describe_images is not paginated.
    """
    try:
        ec2 = boto3.client("ec2", region_name=region_name)
        images = ec2.describe_images(Owners=[owner], Filters=filters)
        return get_latest_images(images)
    except ClientError:
        print("Warning: non authorized in region '{0}', skipping".format(region_name))
        pass


def get_latest_images(images):
    """Return a list containing the latest images for each <OS>-<architecture> combination."""
    images_filtered = {"Images": []}
    for architecture in ARCHITECTURES_TO_MAPPING_NAME:
        for _key, value in DISTROS.items():
            ami_filtered_and_sorted = sorted(
                filter(
                    lambda ami: "-{0}-".format(value) in ami["Name"] and ami["Architecture"] == architecture,
                    images["Images"],
                ),
                key=lambda ami: ami["CreationDate"],
                reverse=True,
            )
            if ami_filtered_and_sorted:
                images_filtered["Images"].append(ami_filtered_and_sorted[0])
    return images_filtered


def convert_json_to_txt(amis_json):
    """
    Convert amis_json to a string suitable to writing to the amis text file.

    That format is as follows:
    ## <architecture>
    # <OS>
    <region>: <ami-id>
    <region>: <ami-id>
    """
    amis_txt = ""
    for architecture, mapping_name in ARCHITECTURES_TO_MAPPING_NAME.items():
        amis_txt += "## " + architecture + "\n"
        for key, _value in DISTROS.items():
            amis_txt += "# " + key + "\n"
            for region, amis in amis_json.get(mapping_name, {}).items():
                if key in amis:
                    amis_txt += region + ": " + amis[key] + "\n"

    return amis_txt


def get_aws_regions_from_file(region_file):
    """
    Return the list of region names read from region_file.

    The format of region_file is as follows:
    {
       "regions": [
           "cn-north-1",
           "cn-northwest-1"
       ]
    }
    """
    with open(region_file) as r_file:
        region_data = json.load(r_file)
    return sorted(r for r in region_data.get("regions"))


def get_all_aws_regions_from_ec2(region):
    """Return a list of all available regions for the partition in which the region arg resides in."""
    ec2 = boto3.client("ec2", region_name=region)
    return sorted(r.get("RegionName") for r in ec2.describe_regions().get("Regions"))


def read_cfn_template(template_path):
    """Read the existing CFN template from the given path."""
    with open(template_path) as cfn_file:
        # object_pairs_hook=OrderedDict allows to preserve input order
        return json.load(cfn_file, object_pairs_hook=OrderedDict)


def write_cfn_template(template_path, cfn_data):
    """Write the CFN template represented by cfn_data to the given path."""
    with open(template_path, "w") as cfn_file:
        # setting separators to (',', ': ') to avoid trailing spaces after commas
        json.dump(cfn_data, cfn_file, indent=2, separators=(",", ": "))
        # add new line at the end of the file
        cfn_file.write("\n")


def update_cfn_template(cfn_template_file, amis_to_update):
    """Update in-place the mappings section of cfn_template_file with the AMI IDs contained in amis_to_update."""
    # Read in existing CFN template
    cfn_data = read_cfn_template(cfn_template_file)
    # update id for new amis without removing regions that are not in the amis_to_update dict
    for mapping_name in ARCHITECTURES_TO_MAPPING_NAME.values():
        current_amis_for_mapping = cfn_data.get("Mappings").get(mapping_name, {})
        for region, amis_to_update_region_mapping in amis_to_update.get(mapping_name, {}).items():
            if not amis_to_update_region_mapping:
                # No new AMIs for this region in this mapping
                continue
            elif region not in current_amis_for_mapping and amis_to_update_region_mapping:
                # There are no AMIs for this region in the existing mapping, but there are in the updated version
                current_amis_for_mapping[region] = amis_to_update_region_mapping
            else:
                current_amis_for_mapping[region].update(amis_to_update_region_mapping)
            current_amis_for_mapping[region] = OrderedDict(sorted(current_amis_for_mapping[region].items()))

        # enforce alphabetical regions order
        current_amis_for_mapping = OrderedDict(sorted(current_amis_for_mapping.items()))
        cfn_data.get("Mappings")[mapping_name] = current_amis_for_mapping
    # Ensure mappings are sorted
    cfn_data["Mappings"] = OrderedDict(sorted(cfn_data["Mappings"].items()))
    # Write back modified CFN template
    write_cfn_template(cfn_template_file, cfn_data)


def update_amis_txt(amis_txt_file, cfn_template_file):
    """Write amis_txt_file using the updated information contained in cfn_template_file."""
    cfn_data = read_cfn_template(cfn_template_file)
    amis_txt = convert_json_to_txt(cfn_data.get("Mappings"))
    with open(amis_txt_file, "w") as f:
        f.write("%s" % amis_txt)


def parse_args():
    """Parse command line args."""
    parser = argparse.ArgumentParser(description="Get AWS ParallelCluster instances and generate a json and txt file")
    git_ref_group = parser.add_argument_group(
        "Retrieve instances from EC2 searching by cookbook and node git reference"
    )
    git_ref_group.add_argument("--cookbook-git-ref", type=str, help="cookbook git hash reference", required=False)
    git_ref_group.add_argument("--node-git-ref", type=str, help="node git hash reference", required=False)
    git_ref_group.add_argument(
        "--build-date", type=str, help="(optional) build date [timestamp] (e.g. 201801112350)", required=False
    )
    git_ref_group.add_argument(
        "--credential",
        type=str,
        action="append",
        help="STS credential endpoint, in the format <region>,<endpoint>,<ARN>,<externalId>. "
        "Could be specified multiple times",
        required=False,
    )
    local_file_group = parser.add_argument_group("Retrieve instances from local cfn template for given regions")
    local_file_group.add_argument(
        "--json-template", type=str, help="path to input json cloudformation template", required=False
    )
    local_file_group.add_argument(
        "--json-regions", type=str, help="path to input json file containing the regions", required=False
    )
    parser.add_argument("--txt-file", type=str, help="txt output file path", required=False, default="amis.txt")
    parser.add_argument(
        "--partition", type=str, help="commercial | china | govcloud", required=True, choices=PARTITIONS
    )
    parser.add_argument("--account-id", type=str, help="AWS account id owning the AMIs", required=True)
    parser.add_argument(
        "--cloudformation-template",
        type=str,
        help="path to output cloudfomation template",
        required=False,
        default="cloudformation/aws-parallelcluster.cfn.json",
    )
    return parser.parse_args()


def main():
    """Run the script."""
    args = parse_args()
    region = PARTITION_TO_MAIN_REGION.get(args.partition)

    credentials = []
    if args.credential:
        credentials = [
            tuple(credential_tuple.strip().split(","))
            for credential_tuple in args.credential
            if credential_tuple.strip()
        ]

    if args.cookbook_git_ref and args.node_git_ref:
        # This path is used by the build_and_test and retrive_ami_list pipelines.
        # Requiring all of the AMIs in the resulting mappings (for the applicable regions)
        # to be created from the same cookbook and node repo git refs on the same date
        # ensures that the AMIs were all produced by the same run of the build pipeline.
        amis_dict = get_ami_list_by_git_refs(
            main_region=region,
            regions=get_all_aws_regions_from_ec2(region),
            cookbook_git_ref=args.cookbook_git_ref,
            node_git_ref=args.node_git_ref,
            build_date=args.build_date,
            owner=args.account_id,
            credentials=credentials,
        )
    else:
        # This path is used by the pre_release_flow pipleine, which uses the
        # retrive_ami_list pipeline to generate CFN templates with updated mappings
        # for each partition and then aggregates the mappings from each those files
        # into a single CFN template.
        regions = get_aws_regions_from_file(args.json_regions)
        amis_dict = get_ami_list_from_file(regions, args.json_template)

    update_cfn_template(cfn_template_file=args.cloudformation_template, amis_to_update=amis_dict)
    update_amis_txt(amis_txt_file=args.txt_file, cfn_template_file=args.cloudformation_template)


if __name__ == "__main__":
    main()
