# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.
import json
import logging
import os
from hashlib import sha256

import yaml

from pcluster.aws.aws_api import AWSApi
from pcluster.aws.common import AWSClientError
from pcluster.constants import (
    CLEANUP_ROLE_REVISION_TAG_KEY,
    IAM_ROLE_PATH,
    PCLUSTER_BUILD_IMAGE_CLEANUP_ROLE_EXPECTED_REVISION,
    PCLUSTER_BUILD_IMAGE_CLEANUP_ROLE_PREFIX,
)
from pcluster.utils import get_url_scheme, yaml_load

ROOT_VOLUME_TYPE = "gp3"
PCLUSTER_RESERVED_VOLUME_SIZE = 37
AMI_NAME_REQUIRED_SUBSTRING = " {{ imagebuilder:buildDate }}"


def get_ami_id(parent_image):
    """Get ami id from parent image, parent image could be image id or image arn."""
    if parent_image and parent_image.startswith("arn"):
        ami_id = AWSApi.instance().imagebuilder.get_image_id(parent_image)
    else:
        ami_id = parent_image
    return ami_id


def get_resources_directory():
    """Get imagebuilder resources directory."""
    current_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(current_dir, "..", "pcluster", "resources")


def search_tag(resource_info, tag_key):
    """Search tag in tag list by given tag key."""
    return next(
        (tag["Value"] for tag in resource_info.get("Tags", []) if tag["Key"] == tag_key),
        None,
    )


def wrap_script_to_component(url):
    """Wrap script to custom component data property."""
    scheme = get_url_scheme(url)
    current_dir = os.path.dirname(os.path.abspath(__file__))

    custom_component_script_template_file = os.path.join(current_dir, "resources", "imagebuilder", "custom_script.yaml")

    with open(custom_component_script_template_file, "r", encoding="utf-8") as file:
        custom_component_script_template = yaml_load(file)

    script_url_action = _generate_action("ScriptUrl", "set -v\necho {0}\n".format(url))
    custom_component_script_template["phases"][0]["steps"].insert(0, script_url_action)
    script_scheme_action = _generate_action("ScriptUrlScheme", "set -v\necho {0}\n".format(scheme))
    custom_component_script_template["phases"][0]["steps"].insert(0, script_scheme_action)

    return yaml.dump(custom_component_script_template)


def _generate_action(action_name, commands):
    """Generate action in imagebuilder components."""
    action = {"name": action_name, "action": "ExecuteBash", "inputs": {"commands": [commands]}}
    return action


def _hash(account_id: str) -> str:
    """Return first 12 hex chars of sha256(account_id)."""
    return sha256(account_id.encode()).hexdigest()[:12]


def get_cleanup_role_name(account_id: str) -> str:
    return f"{PCLUSTER_BUILD_IMAGE_CLEANUP_ROLE_PREFIX}-{_hash(account_id)}"


def _expected_inline_policy(account_id: str, partition: str):
    """Return the inline policy document (JSON-serialised string)."""
    return json.dumps(
        {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Action": ["iam:DetachRolePolicy", "iam:DeleteRole", "iam:DeleteRolePolicy"],
                    "Resource": f"arn:{partition}:iam::{account_id}:role/parallelcluster/*",
                    "Effect": "Allow",
                },
                {
                    "Action": ["iam:DeleteInstanceProfile", "iam:RemoveRoleFromInstanceProfile"],
                    "Resource": f"arn:{partition}:iam::{account_id}:instance-profile/parallelcluster/*",
                    "Effect": "Allow",
                },
                {
                    "Action": "imagebuilder:DeleteInfrastructureConfiguration",
                    "Resource": f"arn:{partition}:imagebuilder:*:{account_id}:infrastructure-configuration/"
                    f"parallelclusterimage-*",
                    "Effect": "Allow",
                },
                {
                    "Action": ["imagebuilder:DeleteComponent"],
                    "Resource": [f"arn:{partition}:imagebuilder:*:{account_id}:component/parallelclusterimage-*/*"],
                    "Effect": "Allow",
                },
                {
                    "Action": "imagebuilder:DeleteImageRecipe",
                    "Resource": f"arn:{partition}:imagebuilder:*:{account_id}:image-recipe/parallelclusterimage-*/*",
                    "Effect": "Allow",
                },
                {
                    "Action": "imagebuilder:DeleteDistributionConfiguration",
                    "Resource": f"arn:{partition}:imagebuilder:*:{account_id}:distribution-configuration/"
                    f"parallelclusterimage-*",
                    "Effect": "Allow",
                },
                {
                    "Action": ["imagebuilder:DeleteImage", "imagebuilder:GetImage", "imagebuilder:CancelImageCreation"],
                    "Resource": f"arn:{partition}:imagebuilder:*:{account_id}:image/parallelclusterimage-*/*",
                    "Effect": "Allow",
                },
                {
                    "Action": "cloudformation:DeleteStack",
                    "Resource": f"arn:{partition}:cloudformation:*:{account_id}:stack/*/*",
                    "Effect": "Allow",
                },
                # The below two permissions are required for the DeleteStackFunction Lambda to tag the
                # created AMI with 'parallelcluster:build_status' and 'parallelcluster:parent_image' tags
                {"Action": "ec2:CreateTags", "Resource": f"arn:{partition}:ec2:*::image/*", "Effect": "Allow"},
                {"Action": "tag:TagResources", "Resource": "*", "Effect": "Allow"},
                {
                    "Action": ["lambda:DeleteFunction", "lambda:RemovePermission"],
                    "Resource": f"arn:{partition}:lambda:*:{account_id}:function:ParallelClusterImage-*",
                    "Effect": "Allow",
                },
                {
                    "Action": "logs:DeleteLogGroup",
                    "Resource": f"arn:{partition}:logs:*:{account_id}:log-group:/aws/lambda/ParallelClusterImage-*:*",
                    "Effect": "Allow",
                },
                {
                    "Action": [
                        "SNS:GetTopicAttributes",
                        "SNS:DeleteTopic",
                        "SNS:GetSubscriptionAttributes",
                        "SNS:Unsubscribe",
                    ],
                    "Resource": f"arn:{partition}:sns:*:{account_id}:ParallelClusterImage-*",
                    "Effect": "Allow",
                },
            ],
        }
    )


def ensure_cleanup_role(account_id: str, partition: str = "aws", attach_vpc_access_policy: bool = False):
    """
    Ensure the global (account-wide) cleanup role exists and is at the expected revision.

    The function follows a safe order:
      1. If the role does not exist, create it without the revision tag.
      2. If LambdaFunctionsVpcConfig exists in the config, attach the AWS-managed LambdaVPCAccess policy
      3. Attach the AWS-managed Lambda basic policy.
      4. Update/write the inline policy (least-privilege cleanup policy).
      5. Only after the inline policy succeeds, set or bump the revision tag.

    This way, if step 2 or 3 fails (e.g., lack of iam:PutRolePolicy permission) the tag
    stays at an older revision and future invocations will keep retrying.
    """
    iam = AWSApi.instance().iam
    role_name = get_cleanup_role_name(account_id)
    role_arn = f"arn:{partition}:iam::{account_id}:role{IAM_ROLE_PATH}{role_name}"

    # Assume-role trust policy
    assume_doc = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "lambda.amazonaws.com"},
                "Action": "sts:AssumeRole",
                "Condition": {
                    "ArnLike": {
                        "aws:SourceArn": f"arn:{partition}:lambda:*:{account_id}:function:ParallelClusterImage-*"
                    }
                },
            }
        ],
    }

    # Check whether the role already exists
    try:
        resp = iam.get_role(role_name=role_name)
        tags = {t["Key"]: t["Value"] for t in resp["Role"].get("Tags", [])}
        current_revision = int(tags.get(CLEANUP_ROLE_REVISION_TAG_KEY, 0))
    except AWSClientError as e:
        if e.error_code == "NoSuchEntity":
            logging.info("Creating global cleanup role %s", role_name)
            iam.create_role(
                RoleName=role_name,
                Path=IAM_ROLE_PATH,
                AssumeRolePolicyDocument=json.dumps(assume_doc),
                Description="AWS ParallelCluster build-image cleanup Lambda execution role",
            )
            current_revision = 0
        else:
            raise e
    # (re)attach AWSLambdaVPCAccessExecutionRole
    if attach_vpc_access_policy:
        iam.attach_role_policy(
            role_name, f"arn:{partition}:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
        )

    if current_revision < PCLUSTER_BUILD_IMAGE_CLEANUP_ROLE_EXPECTED_REVISION:
        # (re)attach AWSLambdaBasicExecutionRole
        cleanup_role_basic_managed_policy = f"arn:{partition}:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
        iam.attach_role_policy(role_name, cleanup_role_basic_managed_policy)

        # Put (or overwrite) inline policy
        iam.put_role_policy(
            role_name=role_name,
            policy_name="ParallelClusterCleanupInline",
            policy_document=_expected_inline_policy(account_id, partition),
        )

        # Set/update revision tag after policy write succeeds
        iam.tag_role(
            role_name=role_name,
            tags=[
                {
                    "Key": CLEANUP_ROLE_REVISION_TAG_KEY,
                    "Value": str(PCLUSTER_BUILD_IMAGE_CLEANUP_ROLE_EXPECTED_REVISION),
                }
            ],
        )

    return role_arn
