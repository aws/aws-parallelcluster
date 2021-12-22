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

from pcluster.validators.directory_service_validators import DomainAddrValidator, LdapTlsReqCertValidator
from tests.pcluster.validators.utils import assert_failure_messages


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
