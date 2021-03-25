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

from typing import List

from common.imagebuilder_utils import ROOT_VOLUME_TYPE
from pcluster.models.common import BaseDevSettings, BaseTag, ExtraChefAttributes, Resource
from pcluster.utils import get_region
from pcluster.validators.ebs_validators import EbsVolumeTypeSizeValidator
from pcluster.validators.ec2_validators import InstanceTypeBaseAMICompatibleValidator
from pcluster.validators.imagebuilder_validators import AMIVolumeSizeValidator
from pcluster.validators.kms_validators import KmsKeyIdEncryptedValidator, KmsKeyValidator
from pcluster.validators.s3_validators import S3BucketRegionValidator, S3BucketValidator

# ---------------------- Image ---------------------- #


class Volume(Resource):
    """Represent the volume configuration for the ImageBuilder."""

    def __init__(self, size: int = None, encrypted: bool = None, kms_key_id: str = None):
        super().__init__()
        self.size = Resource.init_param(size)
        self.encrypted = Resource.init_param(encrypted, default=False)
        self.kms_key_id = Resource.init_param(kms_key_id)

    def _validate(self):
        if self.kms_key_id:
            self._execute_validator(KmsKeyIdEncryptedValidator, kms_key_id=self.kms_key_id, encrypted=self.encrypted)
            self._execute_validator(KmsKeyValidator, kms_key_id=self.kms_key_id)


class Image(Resource):
    """Represent the image configuration for the ImageBuilder."""

    def __init__(
        self,
        tags: List[BaseTag] = None,
        root_volume: Volume = None,
    ):
        super().__init__()
        self.tags = tags
        self.root_volume = root_volume


# ---------------------- Build ---------------------- #


class Component(Resource):
    """Represent the components configuration for the ImageBuilder."""

    def __init__(self, type: str, value: str):
        super().__init__()
        self.type = Resource.init_param(type)
        self.value = Resource.init_param(value)


class DistributionConfiguration(Resource):
    """Represent the distribution configuration for the ImageBuilder."""

    def __init__(self, regions: str, launch_permission: str = None):
        super().__init__()
        self.regions = Resource.init_param(regions)
        self.launch_permission = Resource.init_param(launch_permission)


class Build(Resource):
    """Represent the build configuration for the ImageBuilder."""

    def __init__(
        self,
        instance_type: str,
        parent_image: str,
        instance_role: str = None,
        subnet_id: str = None,
        tags: List[BaseTag] = None,
        security_group_ids: List[str] = None,
        components: List[Component] = None,
    ):
        super().__init__()
        self.instance_type = Resource.init_param(instance_type)
        self.parent_image = Resource.init_param(parent_image)
        self.instance_role = Resource.init_param(instance_role)
        self.tags = tags
        self.subnet_id = Resource.init_param(subnet_id)
        self.security_group_ids = security_group_ids
        self.components = components

    def _validate(self):
        self._execute_validator(
            InstanceTypeBaseAMICompatibleValidator,
            instance_type=self.instance_type,
            image=self.parent_image,
        )


# ---------------------- Dev Settings ---------------------- #


class ImagebuilderDevSettings(BaseDevSettings):
    """Represent the dev settings configuration for the ImageBuilder."""

    def __init__(
        self,
        update_os_and_reboot: bool = None,
        disable_pcluster_component: bool = None,
        distribution_configuration: DistributionConfiguration = None,
        terminate_instance_on_failure: bool = None,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.update_os_and_reboot = Resource.init_param(update_os_and_reboot, default=False)
        self.disable_pcluster_component = Resource.init_param(disable_pcluster_component, default=False)
        self.distribution_configuration = distribution_configuration
        self.terminate_instance_on_failure = Resource.init_param(terminate_instance_on_failure, default=True)


# ---------------------- ImageBuilder ---------------------- #


class ImageBuilderConfig(Resource):
    """Represent the configuration of an ImageBuilder."""

    def __init__(
        self,
        build: Build,
        image: Image = None,
        dev_settings: ImagebuilderDevSettings = None,
        custom_s3_bucket: str = None,
        source_config: str = None
    ):
        super().__init__()
        self.image = image
        self.build = build
        self.dev_settings = dev_settings
        self.custom_s3_bucket = Resource.init_param(custom_s3_bucket)
        self.source_config = source_config

    def _validate(self):
        # Volume size validator only validates specified volume size
        if self.image and self.image.root_volume and self.image.root_volume.size:
            self._execute_validator(
                EbsVolumeTypeSizeValidator,
                volume_type=ROOT_VOLUME_TYPE,
                volume_size=self.image.root_volume.size,
            )
            self._execute_validator(
                AMIVolumeSizeValidator,
                volume_size=self.image.root_volume.size,
                image=self.build.parent_image,
            )

        if self.custom_s3_bucket:
            self._execute_validator(S3BucketValidator, bucket=self.custom_s3_bucket)
            self._execute_validator(S3BucketRegionValidator, bucket=self.custom_s3_bucket, region=get_region())


# ------------ Attributes class used in imagebuilder resources ----------- #


class ImageBuilderExtraChefAttributes(ExtraChefAttributes):
    """Extra Attributes for ImageBuilder Chef Client."""

    def __init__(self, dev_settings: ImagebuilderDevSettings):
        super().__init__(dev_settings)
        self.cfn_region = None
        self.nvidia = None
        self.is_official_ami_build = None
        self.custom_node_package = None
        self.custom_awsbatchcli_package = None
        self.cfn_base_os = None
        self._set_default(dev_settings)

    def _set_default(self, dev_settings: ImagebuilderDevSettings):
        self.cfn_region = "{{ build.AWSRegion.outputs.stdout }}"
        self.nvidia = {"enabled": "false"}
        self.is_official_ami_build = "true" if dev_settings and dev_settings.update_os_and_reboot else "false"
        self.custom_node_package = dev_settings.node_package if dev_settings and dev_settings.node_package else ""
        self.custom_awsbatchcli_package = (
            dev_settings.aws_batch_cli_package if dev_settings and dev_settings.aws_batch_cli_package else ""
        )
        self.cfn_base_os = "{{ build.OperatingSystemName.outputs.stdout }}"
        for key, value in self.__dict__.items():
            if not key.startswith("_") and key not in self._cfncluster_attributes:
                self._cfncluster_attributes.update({key: value})
