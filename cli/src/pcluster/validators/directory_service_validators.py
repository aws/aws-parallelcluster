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

from pcluster.aws.aws_api import AWSApi
from pcluster.aws.common import AWSClientError
from pcluster.constants import DIRECTORY_SERVICE_RESERVED_SETTINGS
from pcluster.validators.common import FailureLevel, Validator


class DomainAddrValidator(Validator):
    """Domain address validator."""

    def _validate(self, domain_addr, additional_sssd_configs):
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
            warning_message = "The use of the ldaps protocol is strongly encouraged for security reasons."
            tls_disabled = (
                str(additional_sssd_configs.get("ldap_auth_disable_tls_never_use_in_production", "false")).lower()
                == "true"
            )
            if not tls_disabled:
                warning_message += (
                    " When using ldap, the additional SSSD config is required: "
                    "'ldap_auth_disable_tls_never_use_in_production: true'."
                )
            self._add_failure(warning_message, FailureLevel.WARNING)


class DomainNameValidator(Validator):
    """Domain name validator."""

    FQDN_PATTERN = "^([a-zA-Z0-9_-]+)(\\.[a-zA-Z0-9_-]+)*$"
    LDAP_DN_PATTERN = "^((DC|dc)=[a-zA-Z0-9_-]+)(,(DC|dc)=[a-zA-Z0-9_-]+)*$"

    def _validate(self, domain_name):
        """Validate that domain address is a Fully Qualified Domain Name (FQDN) or a LDAP Distinguished Name (DN)."""
        match = re.match(DomainNameValidator.FQDN_PATTERN, domain_name) or re.match(
            DomainNameValidator.LDAP_DN_PATTERN, domain_name
        )
        if not match:
            self._add_failure(
                "Unsupported domain address format. "
                "Supported formats are FQDN (corp.example.com) or LDAP Distinguished Name (DC=corp,DC=example,DC=com).",
                FailureLevel.ERROR,
            )


class PasswordSecretArnValidator(Validator):
    """PasswordSecretArn validator."""

    def _validate(self, password_secret_arn: str, region: str):
        """Validate that PasswordSecretArn contains a valid ARN for the given region.

        In particular, the ARN should be one of the following resources:
         1. a readable secret in AWS Secrets Manager, which is supported in all regions.
         2. a readable parameter in SSM Parameter Store, which is supported only in us-isob-east-1
            for retro-compatibility.
        """
        try:
            # We only require the secret to exist; we do not validate its content.
            arn_components = password_secret_arn.split(":")
            service = arn_components[2]
            resource = arn_components[5]
            if service == "ssm":
                resource = arn_components[5].split("/")[0]

            if service == "secretsmanager" and resource == "secret":
                AWSApi.instance().secretsmanager.describe_secret(password_secret_arn)
            elif service == "ssm" and resource == "parameter" and region == "us-isob-east-1":
                parameter_name = arn_components[5].split("/")[1]
                AWSApi.instance().ssm.get_parameter(parameter_name)
            else:
                self._add_failure(
                    f"The secret {password_secret_arn} is not supported in region {region}.", FailureLevel.ERROR
                )
        except AWSClientError as e:
            if e.error_code in ("ResourceNotFoundExceptionSecrets", "ParameterNotFound"):
                self._add_failure(f"The secret {password_secret_arn} does not exist.", FailureLevel.ERROR)
            elif e.error_code == "AccessDeniedException":
                self._add_failure(
                    f"Cannot validate secret {password_secret_arn} due to lack of permissions. "
                    "Please refer to ParallelCluster official documentation for more information.",
                    FailureLevel.WARNING,
                )
            else:
                self._add_failure(
                    f"Cannot validate secret {password_secret_arn}. "
                    "Please refer to ParallelCluster official documentation for more information.",
                    FailureLevel.WARNING,
                )


class LdapTlsReqCertValidator(Validator):
    """LDAP TLS require certificate parameter validator."""

    def _validate(self, ldap_tls_reqcert):
        """Warn user of potentially insecure configurations."""
        values_requiring_cert_validation = ("hard", "demand")
        if ldap_tls_reqcert not in values_requiring_cert_validation:
            self._add_failure(
                f"For security reasons it's recommended to use {' or '.join(values_requiring_cert_validation)}",
                FailureLevel.WARNING,
            )


class AdditionalSssdConfigsValidator(Validator):
    """AdditionalSssdConfigs validator."""

    def _validate(self, additional_sssd_configs, ldap_access_filter):
        """Validate that AdditionalSssdConfigs does not introduce unacceptable values."""
        for config_key, accepted_value in DIRECTORY_SERVICE_RESERVED_SETTINGS.items():
            if config_key in additional_sssd_configs:
                actual_value = additional_sssd_configs[config_key]
                if actual_value != accepted_value:
                    self._add_failure(
                        f"Cannot override the SSSD property '{config_key}' "
                        f"with value '{actual_value}'. "
                        f"Allowed value is: '{accepted_value}'. "
                        "Please refer to ParallelCluster official documentation for more information.",
                        FailureLevel.ERROR,
                    )

        if "access_provider" in additional_sssd_configs:
            actual_access_provider = additional_sssd_configs["access_provider"]
            if ldap_access_filter is not None and actual_access_provider != "ldap":
                self._add_failure(
                    "Cannot override the SSSD property 'access_provider' "
                    f"with value '{actual_access_provider}' when LdapAccessFilter is specified. "
                    "Allowed value is: 'ldap'. "
                    "Please refer to ParallelCluster official documentation for more information.",
                    FailureLevel.ERROR,
                )
