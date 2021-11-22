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


from urllib.parse import urlparse

from pcluster.validators.common import FailureLevel, Validator


class DomainAddrValidator(Validator):
    """Domain address validator."""

    def _validate(self, domain_addr):
        """Warn user when ldap is used for the protocol instead of ldaps."""
        domain_addr_scheme = urlparse(domain_addr).scheme
        default_domain_addr_scheme = "ldaps"
        supported_domain_addr_schemes = (default_domain_addr_scheme, "ldap")
        if not domain_addr_scheme:
            self._add_failure(
                f"No protocol specified. Assuming the use of '{default_domain_addr_scheme}'",
                FailureLevel.WARNING,
            )
        elif domain_addr_scheme not in supported_domain_addr_schemes:
            self._add_failure(
                f"Unsupported protocol '{domain_addr_scheme}'. Supported protocols are: "
                + " ".join(supported_domain_addr_schemes),
                FailureLevel.WARNING,
            )
        elif domain_addr_scheme == "ldap":
            self._add_failure(
                "The use of the ldaps protocol is strongly encouraged for security reasons.", FailureLevel.WARNING
            )
