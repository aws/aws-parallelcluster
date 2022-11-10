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
#
# This module contains all the classes representing the Resources objects.
# These objects are obtained from the configuration file through a conversion based on the Schema classes.
#
import json
import logging
from abc import ABC, abstractmethod
from typing import List, Set

from pcluster.validators.common import FailureLevel, ValidationResult, Validator, ValidatorContext
from pcluster.validators.iam_validators import AdditionalIamPolicyValidator
from pcluster.validators.networking_validators import LambdaFunctionsVpcConfigValidator
from pcluster.validators.s3_validators import UrlValidator

LOGGER = logging.getLogger(__name__)


class ValidatorSuppressor(ABC):
    """Interface for a class that encapsulates the logic to suppress config validators."""

    @abstractmethod
    def suppress_validator(self, validator: Validator) -> bool:
        """Return True if the given validator needs to be suppressed."""
        pass


class AllValidatorsSuppressor(ValidatorSuppressor):
    """Suppressor that suppresses all validators."""

    def __eq__(self, o: object) -> bool:  # pylint: disable=C0103
        return isinstance(o, AllValidatorsSuppressor)

    def __hash__(self) -> int:
        return hash(1)

    def suppress_validator(self, validator: Validator) -> bool:  # noqa: D102
        return True


class TypeMatchValidatorsSuppressor(ValidatorSuppressor):
    """Suppressor that suppresses validators based on their type."""

    def __eq__(self, o: object) -> bool:  # pylint: disable=C0103
        if isinstance(o, TypeMatchValidatorsSuppressor):
            return o._validators_to_suppress == self._validators_to_suppress
        return False

    def __hash__(self) -> int:
        return hash("".join(sorted(self._validators_to_suppress)))

    def __init__(self, validators_to_suppress: Set[str]):
        super().__init__()
        self._validators_to_suppress = validators_to_suppress

    def suppress_validator(self, validator: Validator) -> bool:  # noqa: D102
        return validator.type in self._validators_to_suppress


class Resource:
    """Represent an abstract Resource entity."""

    class Param:
        """
        Represent a Configuration-managed attribute of a Resource.

        Other than the value of the attribute, it contains metadata information that allows to check if the value is
        implied or not, get the update policy and the default value.
        Instances of this class are not meant to be created directly, but only through the `init_param` utility method
        of resource class.
        """

        def __init__(self, value, default=None, update_policy=None):

            # If the value is None, it means that the value has not been specified in the configuration; hence it can
            # be implied from its default, if present.
            if value is None and default is not None:
                self.__value = default
                self.__implied = True
            else:
                self.__value = value
                self.__implied = False
            self.__default = default
            self.__update_policy = update_policy

        @property
        def value(self):
            """
            Return the value of the parameter.

            This value is always kept in sync with the corresponding resource attribute, so it is always safe to read it
            from here, if needed.
            """
            return self.__value

        @property
        def implied(self):
            """Tell if the value of this parameter is implied or not."""
            return self.__implied

        @property
        def default(self):
            """Return the default value."""
            return self.__default

        @property
        def update_policy(self):
            """Return the update policy."""
            return self.__update_policy()

        def __repr__(self):
            return repr(self.value)

    def __init__(self, implied: bool = False):
        # Parameters registry
        self.__params = {}
        self._validation_failures: List[ValidationResult] = []
        self._validators: List = []
        self.implied = implied

    @property
    def params(self):
        """Return the params registry for this Resource."""
        return self.__params

    def get_param(self, param_name):
        """Get the information related to the specified parameter name."""
        return self.__params.get(param_name, None)

    def is_implied(self, param_name):
        """Tell if the value of an attribute is implied or not."""
        return self.__params[param_name].implied

    def __setattr__(self, key, value):
        """
        Override the parent __set_attr__ method to manage parameters information related to Resource attributes.

        When an attribute is initialized through the `init_param` method, a Resource.Param instance is associated to
        the attribute and then kept updated accordingly every time the attribute is updated.
        """
        if key != "_Resource__params":
            if isinstance(value, Resource.Param):
                # If value is a param instance, register the Param and replace the value in the attribute
                # Register in params dict
                self.__params[key] = value
                # Set parameter value as attribute value
                value = value.value
            else:
                # If other type, check if it is backed by a param; if yes, sync the param
                param = self.__params.get(key, None)
                if param:
                    param._Param__value = value
                    param._Param__implied = False

        super().__setattr__(key, value)

    @staticmethod
    def init_param(value, default=None, update_policy=None):
        """Create a resource attribute backed by a Configuration Parameter."""
        return Resource.Param(value, default=default, update_policy=update_policy)

    def _validator_execute(self, validator_class, validator_args, suppressors):
        validator = validator_class()
        if any(suppressor.suppress_validator(validator) for suppressor in (suppressors or [])):
            LOGGER.debug("Suppressing validator %s", validator_class.__name__)
            return []
        LOGGER.debug("Executing validator %s", validator_class.__name__)
        try:
            return validator.execute(**validator_args)
        except Exception as e:
            return [ValidationResult(str(e), FailureLevel.ERROR, validator.type)]

    def _nested_resources(self):
        nested_resources = []
        for _, value in self.__dict__.items():
            if isinstance(value, Resource):
                nested_resources.append(value)
            if isinstance(value, list) and value:
                nested_resources.extend(item for item in value if isinstance(item, Resource))
        return nested_resources

    def validate(
        self, suppressors: List[ValidatorSuppressor] = None, context: ValidatorContext = None
    ) -> List[ValidationResult]:
        """Execute registered validators."""
        # Cleanup failures and validators
        self._validation_failures.clear()

        # Call validators for nested resources
        for nested_resource in self._nested_resources():
            self._validation_failures.extend(nested_resource.validate(suppressors, context))

        # Update validators to be executed according to current status of the model and order by priority
        self._validators.clear()
        self._register_validators(context)
        for validator in self._validators:
            self._validation_failures.extend(self._validator_execute(*validator, suppressors))

        return self._validation_failures

    def _register_validators(self, context: ValidatorContext = None):
        """
        Execute validators.

        Method to be implemented in Resources.
        """
        pass

    def _register_validator(self, validator_class, **validator_args):
        """Execute the validator."""
        self._validators.append((validator_class, validator_args))

    def __repr__(self):
        """Return a human readable representation of the Resource object."""
        return "<{name}({attributes})>".format(
            name=self.__class__.__name__,
            attributes=",".join(f"{attr}={repr(value)}" for attr, value in self.__dict__.items()),
        )


# ------------ Common resources between ImageBuilder an Cluster models ----------- #


class BaseTag(Resource):
    """Represent the Tag configuration."""

    def __init__(self, key: str = None, value: str = None):
        super().__init__()
        self.key = Resource.init_param(key)
        self.value = Resource.init_param(value)


class AdditionalIamPolicy(Resource):
    """Represent the Additional IAM Policy configuration."""

    def __init__(self, policy: str):
        super().__init__()
        self.policy = Resource.init_param(policy)

    def _register_validators(self, context: ValidatorContext = None):
        self._register_validator(AdditionalIamPolicyValidator, policy=self.policy)


class Cookbook(Resource):
    """Represent the chef cookbook configuration."""

    def __init__(self, chef_cookbook: str = None, extra_chef_attributes: str = None):
        super().__init__()
        self.chef_cookbook = Resource.init_param(chef_cookbook)
        self.extra_chef_attributes = Resource.init_param(extra_chef_attributes)

    def _register_validators(self, context: ValidatorContext = None):
        if self.chef_cookbook is not None:
            self._register_validator(UrlValidator, url=self.chef_cookbook)


class LambdaFunctionsVpcConfig(Resource):
    """Represent the VPC configuration schema of PCluster Lambdas, used both by build image and cluster files."""

    def __init__(self, security_group_ids: List[str] = None, subnet_ids: List[str] = None, **kwargs):
        super().__init__(**kwargs)
        self.security_group_ids = Resource.init_param(security_group_ids)
        self.subnet_ids = Resource.init_param(subnet_ids)


class BaseDevSettings(Resource):
    """Represent the common dev settings configuration between the ImageBuilder and Cluster."""

    def __init__(
        self,
        cookbook: Cookbook = None,
        node_package: str = None,
        aws_batch_cli_package: str = None,
    ):
        super().__init__()
        self.cookbook = cookbook
        self.node_package = Resource.init_param(node_package)
        self.aws_batch_cli_package = Resource.init_param(aws_batch_cli_package)

    def _register_validators(self, context: ValidatorContext = None):
        if self.node_package:
            self._register_validator(UrlValidator, url=self.node_package)
        if self.aws_batch_cli_package:
            self._register_validator(UrlValidator, url=self.aws_batch_cli_package)


class Imds(Resource):
    """
    Represent the IMDS configuration shared between the ImageBuilder and Cluster.

    It represents the Imds element that can be either at top level in the cluster config file,
    or in the Build section of the build image config file.
    """

    def __init__(self, imds_support: str = None, **kwargs):
        super().__init__(**kwargs)
        self.imds_support = Resource.init_param(imds_support, default="v1.0")


class DeploymentSettings(Resource):
    """
    Represent the settings related to PCluster deployment, i.e. Lambda Functions for custom resources.

    This structure is common to both the cluster and build image configuration files, as the build image
    configuration file deploys some Cfn infrastructure as well.
    """

    def __init__(self, lambda_functions_vpc_config: LambdaFunctionsVpcConfig = None, **kwargs):
        super().__init__(**kwargs)
        self.lambda_functions_vpc_config = Resource.init_param(lambda_functions_vpc_config)

    def _register_validators(self, context: ValidatorContext = None):
        if self.lambda_functions_vpc_config:
            self._register_validator(
                LambdaFunctionsVpcConfigValidator,
                security_group_ids=self.lambda_functions_vpc_config.security_group_ids,
                subnet_ids=self.lambda_functions_vpc_config.subnet_ids,
            )


# ------------ Common attributes class between ImageBuilder an Cluster models ----------- #


class ExtraChefAttributes:
    """Extra Attributes for Chef Client."""

    def __init__(self, dev_settings: BaseDevSettings):
        self._cluster_attributes = {}
        self._extra_attributes = {}
        self._init_cluster_attributes(dev_settings)
        self._set_extra_attributes(dev_settings)

    def _init_cluster_attributes(self, dev_settings):
        if dev_settings and dev_settings.cookbook and dev_settings.cookbook.extra_chef_attributes:
            self._cluster_attributes = json.loads(dev_settings.cookbook.extra_chef_attributes).get("cluster") or {}

    def _set_extra_attributes(self, dev_settings):
        if dev_settings and dev_settings.cookbook and dev_settings.cookbook.extra_chef_attributes:
            self._extra_attributes = json.loads(dev_settings.cookbook.extra_chef_attributes)
            if "cluster" in self._extra_attributes:
                self._extra_attributes.pop("cluster")

    def dump_json(self):
        """Dump chef attribute json to string."""
        attribute_json = {"cluster": self._cluster_attributes}
        attribute_json.update(self._extra_attributes)
        return json.dumps(attribute_json, sort_keys=True)
