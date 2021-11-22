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

from pcluster.validators.directory_service_validators import DomainAddrValidator
from tests.pcluster.validators.utils import assert_failure_messages


@pytest.mark.parametrize(
    "domain_addr, expected_message",
    [
        ("ldaps://172.31.8.14", None),
        ("ldap://172.31.8.14", "use of the ldaps protocol is strongly encouraged for security reasons"),
        ("https://172.31.8.14", "Unsupported protocol 'https'. Supported protocols are: ldaps ldap"),
        ("172.31.8.14", "No protocol specified. Assuming the use of 'ldaps'"),
    ],
)
def test_domain_addr_protocol(domain_addr, expected_message):
    actual_failures = DomainAddrValidator().execute(domain_addr=domain_addr)
    assert_failure_messages(actual_failures, expected_message)
