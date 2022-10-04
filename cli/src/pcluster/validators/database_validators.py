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

from urllib.parse import ParseResult, urlparse

from pcluster.validators.common import FailureLevel, Validator


class DatabaseUriValidator(Validator):
    """Slurm database URI validator."""

    def _validate(self, uri: str):
        """Validate database URI."""
        # First, throw error if the URI starts with a "/" (to prevent issues with the
        # manipulation below
        if not self._check_leading_slash(uri):
            return

        uri_parse = urlparse(uri)
        if not uri_parse.netloc:
            # This happens if users provide an URI without explicit scheme followed by ://
            # (for example 'test.example.com:3306' instead of 'mysql://test.example.com:3306`).
            uri_parse = urlparse("//" + uri)

        # The following checks do:
        # - stop the flow in case of parsing exceptions
        # - throw error if the URI contains a scheme
        # - throw error if netloc cannot be parsed from the uri
        # - throw an info if a port has not been provided
        if not (self._check_scheme(uri_parse) and self._check_netloc(uri, uri_parse) and self._check_port(uri_parse)):
            return

    def _check_leading_slash(self, uri: str) -> bool:
        if uri.startswith("/"):
            self._add_failure(
                f"Invalid URI specified. Please remove any leading / at the beginning of the provided URI ('{uri}')",
                FailureLevel.ERROR,
            )
            return False
        return True

    def _check_scheme(self, uri_parse: ParseResult) -> bool:
        try:
            scheme = uri_parse.scheme
        except ValueError as e:
            self._add_failure("Invalid URI specified. " + str(e), FailureLevel.ERROR)
            return False
        if scheme:
            self._add_failure(
                f"Invalid URI specified. Please do not provide a scheme ('{scheme}://')",
                FailureLevel.ERROR,
            )
            return False
        return True

    def _check_netloc(self, uri: str, uri_parse: ParseResult) -> bool:
        try:
            netloc = uri_parse.netloc
        except ValueError as e:
            self._add_failure("Invalid URI specified. " + str(e), FailureLevel.ERROR)
            return False
        if not netloc:
            self._add_failure(
                f"Invalid URI specified. Please review the provided URI ('{uri}')",
                FailureLevel.ERROR,
            )
            return False
        return True

    def _check_port(self, uri_parse: ParseResult) -> bool:
        default_mysql_port = 3306
        try:
            port = uri_parse.port
        except ValueError as e:
            self._add_failure("Invalid URI specified. " + str(e), FailureLevel.ERROR)
            return False
        if not port:
            self._add_failure(
                f"No port specified in the URI. Assuming the use of port {default_mysql_port}",
                FailureLevel.INFO,
            )
        return True
