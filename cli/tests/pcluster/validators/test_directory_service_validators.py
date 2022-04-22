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
        ("", DOMAIN_NAME_ERROR_MESSAGE),
        ("   ", DOMAIN_NAME_ERROR_MESSAGE),
        ("corp.", DOMAIN_NAME_ERROR_MESSAGE),
        ("DC=corp,", DOMAIN_NAME_ERROR_MESSAGE),
        ("corp.examp/e.com", DOMAIN_NAME_ERROR_MESSAGE),
        ("DC=corp,DC=examp/e,DC=com", DOMAIN_NAME_ERROR_MESSAGE),
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
    "password_secret_arn, error_from_secrets_manager, expected_message, expected_failure_level",
    [
        (
            "arn:PARTITION:secretsmanager:REGION:ACCOUNT:secret:NOT_ACCESSIBLE_SECRET",
            "ResourceNotFoundExceptionSecrets",
            "The secret arn:PARTITION:secretsmanager:REGION:ACCOUNT:secret:NOT_ACCESSIBLE_SECRET does not exist.",
            FailureLevel.ERROR,
        ),
        (
            "arn:PARTITION:secretsmanager:REGION:ACCOUNT:secret:ANY_SECRET",
            "AccessDeniedException",
            "Cannot validate secret arn:PARTITION:secretsmanager:REGION:ACCOUNT:secret:ANY_SECRET "
            "due to lack of permissions. Please refer to ParallelCluster official documentation for more information.",
            FailureLevel.WARNING,
        ),
        (
            "arn:PARTITION:secretsmanager:REGION:ACCOUNT:secret:NOT_ACCESSIBLE_SECRET",
            "ANOTHER_ERROR",
            "Cannot validate secret arn:PARTITION:secretsmanager:REGION:ACCOUNT:secret:NOT_ACCESSIBLE_SECRET. "
            "Please refer to ParallelCluster official documentation for more information.",
            FailureLevel.WARNING,
        ),
        (
            "arn:PARTITION:secretsmanager:REGION:ACCOUNT:secret:ACCESSIBLE_SECRET",
            None,
            None,
            None,
        ),
    ],
)
def test_password_secret_arn_validator(
    password_secret_arn, error_from_secrets_manager, expected_message, expected_failure_level, aws_api_mock
):
    if error_from_secrets_manager:
        aws_api_mock.secretsmanager.describe_secret.side_effect = AWSClientError(
            function_name="A_FUNCTION_NAME", error_code=error_from_secrets_manager, message="AN_ERROR_MESSAGE"
        )
    actual_failures = PasswordSecretArnValidator().execute(password_secret_arn=password_secret_arn)
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
