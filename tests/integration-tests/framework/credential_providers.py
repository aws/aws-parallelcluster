#  Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
#  with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
#  or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
#  OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
#  limitations under the License.
import logging
import os
import re
from contextlib import contextmanager

import boto3
from utils import run_command

cli_credentials = {}


def register_cli_credentials_for_region(region, iam_role):
    """Register a IAM role to be used for the CLI commands in a given region."""
    global cli_credentials
    logging.info("Configuring CLI IAM role %s for region %s", iam_role, region)
    cli_credentials[region] = iam_role


def run_pcluster_command(*args, custom_cli_credentials=None, **kwargs):
    """Run a command after assuming the role configured through register_cli_credentials_for_region."""

    region = kwargs.get("region")
    if not region:
        region = os.environ["AWS_DEFAULT_REGION"]

    if region in cli_credentials:
        with sts_credential_provider(region, credential_arn=custom_cli_credentials or cli_credentials.get(region)):
            return run_command(*args, **kwargs)
    else:
        return run_command(*args, **kwargs)


@contextmanager
def aws_credential_provider(region, credential_arg):
    """Set the AWS credentials in the environment for the duration of the context."""
    credentials_config = _parse_credential_arg(credential_arg)
    if region in credentials_config:
        credential_endpoint, credential_arn, credential_external_id = credentials_config.get(region)
        with sts_credential_provider(region, credential_arn, credential_external_id, credential_endpoint):
            yield
    else:
        # Default to configured credentials
        logging.info("Using default AWS credentials")
        yield


@contextmanager
def sts_credential_provider(region, credential_arn, credential_external_id=None, credential_endpoint=None):
    """Assume a role through STS and set such creds in the environment for the duration of the context."""
    credentials_to_backup = _get_current_credentials()

    logging.info("Assuming STS credentials for region %s and role %s", region, credential_arn)
    aws_credentials = _retrieve_sts_credential(region, credential_arn, credential_external_id, credential_endpoint)
    logging.info("Retrieved credentials %s", obfuscate_credentials(aws_credentials))

    try:
        logging.info("Unsetting current credentials %s", obfuscate_credentials(credentials_to_backup))
        _unset_credentials()

        os.environ["AWS_ACCESS_KEY_ID"] = aws_credentials["AccessKeyId"]
        os.environ["AWS_SECRET_ACCESS_KEY"] = aws_credentials["SecretAccessKey"]
        os.environ["AWS_SESSION_TOKEN"] = aws_credentials["SessionToken"]
        os.environ["AWS_CREDENTIAL_EXPIRATION"] = aws_credentials["Expiration"]
        boto3.setup_default_session()

        yield aws_credentials
    finally:
        logging.info("Restoring credentials %s", obfuscate_credentials(credentials_to_backup))
        _restore_credentials(credentials_to_backup)


# TODO: we could add caching but we need to refresh the creds if 1h is passed or increase the MaxSessionDuration
def _retrieve_sts_credential(region, credential_arn, credential_external_id=None, credential_endpoint=None):
    if credential_endpoint:
        match = re.search(r"https://sts\.(.*?)\.", credential_endpoint)
        endpoint_region = match.group(1)
        sts = boto3.client("sts", region_name=endpoint_region, endpoint_url=credential_endpoint)
    else:
        sts = boto3.client("sts", region_name=region)

    assume_role_kwargs = {
        "RoleArn": credential_arn,
        "RoleSessionName": region + "_integration_tests_session",
    }
    if credential_external_id:
        assume_role_kwargs["ExternalId"] = credential_external_id

    assumed_role_object = sts.assume_role(**assume_role_kwargs)
    aws_credentials = assumed_role_object["Credentials"]

    return aws_credentials


def _unset_credentials():
    # Unset credential for all boto3 client
    if "AWS_ACCESS_KEY_ID" in os.environ:
        del os.environ["AWS_ACCESS_KEY_ID"]
    if "AWS_SECRET_ACCESS_KEY" in os.environ:
        del os.environ["AWS_SECRET_ACCESS_KEY"]
    if "AWS_SESSION_TOKEN" in os.environ:
        del os.environ["AWS_SESSION_TOKEN"]
    if "AWS_PROFILE" in os.environ:
        del os.environ["AWS_PROFILE"]


def _restore_credentials(creds_to_restore):
    for key, value in creds_to_restore.items():
        if value:
            os.environ[key] = value
        elif key in os.environ:
            del os.environ[key]
    boto3.setup_default_session()


def _get_current_credentials():
    return {
        "AWS_ACCESS_KEY_ID": os.environ.get("AWS_ACCESS_KEY_ID"),
        "AWS_SECRET_ACCESS_KEY": os.environ.get("AWS_SECRET_ACCESS_KEY"),
        "AWS_SESSION_TOKEN": os.environ.get("AWS_SESSION_TOKEN"),
        "AWS_PROFILE": os.environ.get("AWS_PROFILE"),
    }


def _parse_credential_arg(credential_arg):
    if not credential_arg:
        return {}

    return {
        region: (endpoint, arn, external_id)
        for region, endpoint, arn, external_id in [
            tuple(credential_tuple.strip().split(","))
            for credential_tuple in credential_arg
            if credential_tuple.strip()
        ]
    }


def obfuscate_credentials(creds_dict):
    obfuscated_dict = {}
    for key, value in creds_dict.items():
        if value:
            obfuscated_dict[key] = value[0:3] + "*" * (len(value) - 3)
        else:
            obfuscated_dict[key] = value
    return obfuscated_dict
