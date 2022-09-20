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

from pcluster.validators.database_validators import DatabaseUriValidator
from tests.pcluster.validators.utils import assert_failure_messages


@pytest.mark.parametrize(
    "uri, expected_message",
    [
        ("172.31.8.14:123456", "Invalid URI specified. Port out of range 0-65535"),
        ("172.31.8.14", "No port specified in the URI. Assuming the use of port 3306"),
        ("172.31.8.14:12345", None),
        ("test.example.com:12345", None),
        (
            "/test.example.com:12345",
            "Invalid URI specified. Please remove any trailing / at "
            "the beginning of the provided URI ('/test.example.com:12345')",
        ),
        ("test.example.com", "No port specified in the URI. Assuming the use of port 3306"),
        ("mysql://test.example.com", "Invalid URI specified. Please do not provide a scheme ('mysql://')"),
        ("", "Invalid URI specified. Please review the provided URI ('')"),
    ],
)
def test_database_uri(uri, expected_message):
    actual_failures = DatabaseUriValidator().execute(
        uri=uri,
    )
    assert_failure_messages(actual_failures, expected_message)
