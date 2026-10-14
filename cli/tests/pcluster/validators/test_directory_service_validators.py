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
import pytest
from assertpy import fail

from pcluster.aws.common import AWSClientError
from pcluster.validators.common import FailureLevel
from pcluster.validators.directory_service_validators import (
    AdditionalSssdConfigsValidator,
    DomainAddrValidator,
    DomainNameValidator,
    LdapTlsReqCertValidator,
    PasswordSecretArnValidator,
)
from tests.pcluster.validators.utils import assert_failure_level, assert_failure_messages

DOMAIN_NAME_ERROR_MESSAGE = (
    "Unsupported domain address format. "
    "Supported formats are FQDN (corp.example.com) or LDAP Distinguished Name (DC=corp,DC=example,DC=com)."
)


@pytest.mark.parametrize(
    "domain_name, expected_message",
    [
        ("corp.example.com", None),
        ("DC=corp,DC=example,DC=com", None),
        ("dc=corp,dc=example,dc=com", None),
        ("dc=corp,DC=example,dc=com", None),
        ("O=org,dc=corp,dc=example,dc=com", None),
        ("o=org,dc=corp,dc=example,dc=com", None),
        ("", DOMAIN_NAME_ERROR_MESSAGE),
        ("   ", DOMAIN_NAME_ERROR_MESSAGE),
        ("corp.", DOMAIN_NAME_ERROR_MESSAGE),
        ("DC=corp,", DOMAIN_NAME_ERROR_MESSAGE),
        ("corp.examp/e.com", DOMAIN_NAME_ERROR_MESSAGE),
        ("DC=corp,DC=examp/e,DC=com", DOMAIN_NAME_ERROR_MESSAGE),
        ("o=or/g,dc=corp,dc=example,dc=com", DOMAIN_NAME_ERROR_MESSAGE),
    ],
)
def test_domain_name(domain_name, expected_message):
    actual_failures = DomainNameValidator().execute(domain_name=domain_name)
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "domain_addr, additional_sssd_configs, expected_message",
    [
        ("ldaps://172.31.8.14", "WHATEVER", None),
        (
            "ldap://172.31.8.14",
            {"ldap_auth_disable_tls_never_use_in_production": "true"},
            "The use of the ldaps protocol is strongly encouraged for security reasons.",
        ),
        (
            "ldap://172.31.8.14",
            {"ldap_auth_disable_tls_never_use_in_production": True},
            "The use of the ldaps protocol is strongly encouraged for security reasons.",
        ),
        (
            "ldap://172.31.8.14",
            {},
            [
                "The use of the ldaps protocol is strongly encouraged for security reasons.",
                "When using ldap, the additional SSSD config is required: "
                "'ldap_auth_disable_tls_never_use_in_production: true'.",
            ],
        ),
        (
            "ldap://172.31.8.14",
            {"ldap_auth_disable_tls_never_use_in_production": "false"},
            [
                "The use of the ldaps protocol is strongly encouraged for security reasons.",
                "When using ldap, the additional SSSD config is required: "
                "'ldap_auth_disable_tls_never_use_in_production: true'.",
            ],
        ),
        (
            "ldap://172.31.8.14",
            {"ldap_auth_disable_tls_never_use_in_production": False},
            [
                "The use of the ldaps protocol is strongly encouraged for security reasons.",
                "When using ldap, the additional SSSD config is required: "
                "'ldap_auth_disable_tls_never_use_in_production: true'.",
            ],
        ),
        ("https://172.31.8.14", "WHATEVER", "Unsupported protocol 'https'. Supported protocols are: ldaps ldap"),
        ("172.31.8.14", "WHATEVER", "No protocol specified. Assuming the use of 'ldaps'"),
    ],
)
def test_domain_addr_protocol(domain_addr, additional_sssd_configs, expected_message):
    actual_failures = DomainAddrValidator().execute(
        domain_addr=domain_addr, additional_sssd_configs=additional_sssd_configs
    )
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "ldap_tls_reqcert, expected_message",
    [
        ("hard", None),
        ("demand", None),
        ("never", "For security reasons it's recommended to use hard or demand"),
        ("allow", "For security reasons it's recommended to use hard or demand"),
        ("try", "For security reasons it's recommended to use hard or demand"),
    ],
)
def test_ldap_tls_reqcert_validator(ldap_tls_reqcert, expected_message):
    actual_failures = LdapTlsReqCertValidator().execute(ldap_tls_reqcert=ldap_tls_reqcert)
    assert_failure_messages(actual_failures, expected_message)


@pytest.mark.parametrize(
    "password_secret_arn, region, aws_service, error_from_aws_service, expected_message, expected_failure_level",
    [
        pytest.param(
            "arn:PARTITION:secretsmanager:REGION:ACCOUNT:secret:NOT_ACCESSIBLE_SECRET",
            "WHATEVER-NOT-us-isob-east-1",
            "secretsmanager",
            "ResourceNotFoundExceptionSecrets",
            "The secret arn:PARTITION:secretsmanager:REGION:ACCOUNT:secret:NOT_ACCESSIBLE_SECRET does not exist.",
            FailureLevel.ERROR,
            id="PasswordSecretArn as a Secret in Secrets Manager that does not exist, "
            "in regions other than us-isob-east-1",
        ),
        pytest.param(
            "arn:PARTITION:secretsmanager:REGION:ACCOUNT:secret:ANY_SECRET",
            "WHATEVER-NOT-us-isob-east-1",
            "secretsmanager",
            "AccessDeniedException",
            "Cannot validate secret arn:PARTITION:secretsmanager:REGION:ACCOUNT:secret:ANY_SECRET "
            "due to lack of permissions. Please refer to ParallelCluster official documentation for more information.",
            FailureLevel.WARNING,
            id="PasswordSecretArn as a Secret in Secrets Manager that is not accessible due to lack of permissions, "
            "in regions other than us-isob-east-1",
        ),
        pytest.param(
            "arn:PARTITION:secretsmanager:REGION:ACCOUNT:secret:NOT_ACCESSIBLE_SECRET",
            "WHATEVER-NOT-us-isob-east-1",
            "secretsmanager",
            "ANOTHER_ERROR",
            "Cannot validate secret arn:PARTITION:secretsmanager:REGION:ACCOUNT:secret:NOT_ACCESSIBLE_SECRET. "
            "Please refer to ParallelCluster official documentation for more information.",
            FailureLevel.WARNING,
            id="PasswordSecretArn as a Secret in Secrets Manager that is not accessible due to unexpected exception, "
            "in regions other than us-isob-east-1",
        ),
        pytest.param(
            "arn:PARTITION:secretsmanager:REGION:ACCOUNT:UNSUPPORTED_RESOURCE",
            "WHATEVER-NOT-us-isob-east-1",
            "secretsmanager",
            None,
            "The secret arn:PARTITION:secretsmanager:REGION:ACCOUNT:UNSUPPORTED_RESOURCE is not supported "
            "in region WHATEVER-NOT-us-isob-east-1.",
            FailureLevel.ERROR,
            id="PasswordSecretArn as an unsupported resource of Secrets Manager, in regions other than us-isob-east-1",
        ),
        pytest.param(
            "arn:PARTITION:secretsmanager:REGION:ACCOUNT:secret:ACCESSIBLE_SECRET",
            "WHATEVER-NOT-us-isob-east-1",
            "secretsmanager",
            None,
            None,
            None,
            id="PasswordSecretArn as a Secret in Secrets Manager that is accessible, "
            "in regions other than us-isob-east-1",
        ),
        pytest.param(
            "arn:PARTITION:secretsmanager:REGION:ACCOUNT:secret:WHATEVER_SECRET",
            "us-isob-east-1",
            "secretsmanager",
            None,
            None,
            None,
            id="PasswordSecretArn as a Secret in Secrets Manager, in us-isob-east-1",
        ),
        pytest.param(
            "arn:PARTITION:ssm:REGION:ACCOUNT:parameter/NOT_ACCESSIBLE_SECRET",
            "us-isob-east-1",
            "ssm",
            "ParameterNotFound",
            "The secret arn:PARTITION:ssm:REGION:ACCOUNT:parameter/NOT_ACCESSIBLE_SECRET does not exist.",
            FailureLevel.ERROR,
            id="PasswordSecretArn as a Parameter in SSM that does not exist, in us-isob-east-1",
        ),
        pytest.param(
            "arn:PARTITION:ssm:REGION:ACCOUNT:parameter/ANY_SECRET",
            "us-isob-east-1",
            "ssm",
            "AccessDeniedException",
            "Cannot validate secret arn:PARTITION:ssm:REGION:ACCOUNT:parameter/ANY_SECRET "
            "due to lack of permissions. Please refer to ParallelCluster official documentation for more information.",
            FailureLevel.WARNING,
            id="PasswordSecretArn as a Parameter in SSM that is not accessible due to lack of permissions, "
            "in us-isob-east-1",
        ),
        pytest.param(
            "arn:PARTITION:ssm:REGION:ACCOUNT:parameter/NOT_ACCESSIBLE_SECRET",
            "us-isob-east-1",
            "ssm",
            "ANOTHER_ERROR",
            "Cannot validate secret arn:PARTITION:ssm:REGION:ACCOUNT:parameter/NOT_ACCESSIBLE_SECRET. "
            "Please refer to ParallelCluster official documentation for more information.",
            FailureLevel.WARNING,
            id="PasswordSecretArn as a Parameter in SSM that is not accessible due to unexpected exception, "
            "in us-isob-east-1",
        ),
        pytest.param(
            "arn:PARTITION:ssm:REGION:ACCOUNT:parameter/ACCESSIBLE_SECRET",
            "us-isob-east-1",
            "ssm",
            None,
            None,
            None,
            id="PasswordSecretArn as a Parameter in SSM that is accessible, in us-isob-east-1",
        ),
        pytest.param(
            "arn:PARTITION:ssm:REGION:ACCOUNT:UNSUPPORTED_RESOURCE",
            "us-isob-east-1",
            "ssm",
            None,
            "The secret arn:PARTITION:ssm:REGION:ACCOUNT:UNSUPPORTED_RESOURCE is not supported.",
            FailureLevel.ERROR,
            id="PasswordSecretArn as an unsupported resource of SSM, in us-isob-east-1",
        ),
        pytest.param(
            "arn:PARTITION:UNSUPPORTED_SERVICE:REGION:ACCOUNT:RESOURCE",
            "us-isob-east-1",
            "UNSUPPORTED_SERVICE",
            None,
            "The secret arn:PARTITION:UNSUPPORTED_SERVICE:REGION:ACCOUNT:RESOURCE is not supported.",
            FailureLevel.ERROR,
            id="PasswordSecretArn as a resource of an unsupported service, in us-isob-east-1",
        ),
        pytest.param(
            "arn:PARTITION:ssm:REGION:ACCOUNT:parameter/WHATEVER_SECRET",
            "WHATEVER-NOT-us-isob-east-1",
            "UNSUPPORTED_SERVICE",
            None,
            "The secret arn:PARTITION:ssm:REGION:ACCOUNT:parameter/WHATEVER_SECRET is not supported "
            "in region WHATEVER-NOT-us-isob-east-1.",
            FailureLevel.ERROR,
            id="PasswordSecretArn as a Parameter in SSM, in regions other than us-isob-east-1",
        ),
    ],
)
def test_password_secret_arn_validator(
    password_secret_arn,
    region,
    aws_service,
    error_from_aws_service,
    expected_message,
    expected_failure_level,
    aws_api_mock,
):
    if error_from_aws_service:
        if aws_service == "secretsmanager":
            aws_api_mocked_call = aws_api_mock.secretsmanager.describe_secret
        elif aws_service == "ssm":
            aws_api_mocked_call = aws_api_mock.ssm.get_parameter
        else:
            fail(f"Unsupported aws_service: {aws_service}")
        aws_api_mocked_call.side_effect = AWSClientError(
            function_name="A_FUNCTION_NAME", error_code=str(error_from_aws_service), message="AN_ERROR_MESSAGE"
        )
    actual_failures = PasswordSecretArnValidator().execute(password_secret_arn=password_secret_arn, region=region)
    assert_failure_messages(actual_failures, expected_message)
    assert_failure_level(actual_failures, expected_failure_level)


@pytest.mark.parametrize(
    "additional_sssd_configs, ldap_access_filter, expected_message",
    [
        ("WHATEVER", "WHATEVER", None),
        (
            {"id_provider": "ldap", "whatever_property": "WHATEVER"},
            "WHATEVER",
            None,
        ),
        (
            {"access_provider": "ldap", "whatever_property": "WHATEVER"},
            "WHATEVER",
            None,
        ),
        (
            {"access_provider": "NOT_ldap", "whatever_property": "WHATEVER"},
            None,
            None,
        ),
        (
            {"id_provider": "NOT_ldap", "whatever_property": "WHATEVER"},
            "WHATEVER",
            "Cannot override the SSSD property 'id_provider' with value 'NOT_ldap'. Allowed value is: 'ldap'. "
            "Please refer to ParallelCluster official documentation for more information.",
        ),
        (
            {"access_provider": "NOT_ldap", "whatever_property": "WHATEVER"},
            "WHATEVER",
            "Cannot override the SSSD property 'access_provider' with value 'NOT_ldap' "
            "when LdapAccessFilter is specified. Allowed value is: 'ldap'. "
            "Please refer to ParallelCluster official documentation for more information.",
        ),
    ],
)
def test_additional_sssd_configs(additional_sssd_configs, ldap_access_filter, expected_message):
    actual_failures = AdditionalSssdConfigsValidator().execute(
        additional_sssd_configs=additional_sssd_configs, ldap_access_filter=ldap_access_filter
    )
    assert_failure_messages(actual_failures, expected_message)
