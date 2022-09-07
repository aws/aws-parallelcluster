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

import re
from urllib.parse import urlparse

from pcluster.validators.common import FailureLevel, Validator


class DatabaseUriValidator(Validator):
    """Domain address validator."""

    def _validate(self, uri: str):
        """Validate database URI."""

        # First, throw error if the URI starts with a "/" (to prevent issues with the
        # manipulation below
        if uri[0] == "/":
            self._add_failure(
                f"Invalid URI specified. Please remove any trailing / at the beginning of the provided URI ('{uri}')",
                FailureLevel.ERROR,
            )
            return

        uri_parse = urlparse(uri)
        if not uri_parse.scheme and not uri_parse.netloc:
            # This happens if users provide an URI without explicit scheme followed by ://
            # (for example 'test.example.com:3306' instead of 'mysql://test.example.com:3306`).
            uri_parse = urlparse("//" + uri_parse.path)

        try:
            scheme = uri_parse.scheme
        except ValueError as e:
            self._add_failure(
                "Invalid URI specified. " + str(e),
                FailureLevel.ERROR
            )
            return

        if scheme:
            self._add_failure(
                f"Invalid URI specified. Please do not provide a scheme ('{scheme}://')",
                FailureLevel.ERROR,
            )

        try:
            netloc = uri_parse.netloc
        except ValueError as e:
            self._add_failure(
                "Invalid URI specified. " + str(e),
                FailureLevel.ERROR
            )
            return

        if not netloc:
            self._add_failure(
                f"Invalid URI specified. Please review the provided URI ('{uri}')",
                FailureLevel.ERROR,
            )

        default_mysql_port = 3306

        try:
            port = uri_parse.port
        except ValueError as e:
            self._add_failure(
                "Invalid URI specified. " + str(e),
                FailureLevel.ERROR
            )
            return

        if not port:
            self._add_failure(
                f"No port specified in the URI. Assuming the use of port {default_mysql_port}",
                FailureLevel.WARNING,
            )
