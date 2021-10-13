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
import logging

from pcluster.constants import (
    PCLUSTER_IMAGE_BUILD_LOG_TAG,
    PCLUSTER_IMAGE_CONFIG_TAG,
    PCLUSTER_IMAGE_ID_TAG,
    PCLUSTER_IMAGE_OS_TAG,
    PCLUSTER_NODE_TYPE_TAG,
    PCLUSTER_QUEUE_NAME_TAG,
    PCLUSTER_S3_BUCKET_TAG,
    PCLUSTER_S3_IMAGE_DIR_TAG,
    PCLUSTER_VERSION_TAG,
    SUPPORTED_ARCHITECTURES,
)

LOGGER = logging.getLogger(__name__)


class StackInfo:
    """Object to store Stack information, initialized with a describe_stacks call."""

    def __init__(self, stack_data: dict):
        """
        Init StackInfo by performing a describe_stacks call.

        If the stack doesn't exist it raises an exception.
        """
        self._stack_data = stack_data
        self._params = self._stack_data.get("Parameters", [])
        self.tags = self._stack_data.get("Tags", [])
        self.outputs = self._stack_data.get("Outputs", [])

    @property
    def id(self):
        """Return the id/arn of the stack."""
        return self._stack_data.get("StackId")

    @property
    def name(self):
        """Return the name of the stack."""
        return self._stack_data.get("StackName")

    @property
    def status(self):
        """Return the status of the stack."""
        return self._stack_data.get("StackStatus")

    @property
    def status_reason(self):
        """Return the reason the stack is in its current status."""
        return self._stack_data.get("StackStatusReason", None)

    @property
    def creation_time(self):
        """Return creation time of the stack."""
        return str(self._stack_data.get("CreationTime"))

    @property
    def last_updated_time(self):
        """Return last updated time of the stack."""
        return str(self._stack_data.get("LastUpdatedTime", self.creation_time))

    @property
    def is_working_status(self):
        """Return true if the stack is in a working status."""
        return self.status in ["CREATE_COMPLETE", "UPDATE_COMPLETE", "UPDATE_ROLLBACK_COMPLETE"]

    def get_tag(self, tag_key: str):
        """Get stack tag by tag key."""
        return next(iter([tag["Value"] for tag in self.tags if tag["Key"] == tag_key]), None)

    def _get_output(self, output_key: str):
        return next((out["OutputValue"] for out in self.outputs if out["OutputKey"] == output_key), None)

    def _get_param(self, key_name):
        """
        Get parameter value from Cloudformation Stack Parameters.

        :param key_name: Parameter Key
        :return: ParameterValue if that parameter exists, otherwise None
        """
        param_value = next((par["ParameterValue"] for par in self._params if par["ParameterKey"] == key_name), None)
        return None if param_value is None else param_value.strip()


class InstanceInfo:
    """Object to store Instance information, initialized with a describe_instances call."""

    def __init__(self, instance_data: dict):
        self._instance_data = instance_data
        self._tags = self._instance_data.get("Tags", [])

    @property
    def id(self) -> str:
        """Return instance id."""
        return self._instance_data.get("InstanceId")

    @property
    def state(self) -> str:
        """Return instance state."""
        return self._instance_data.get("State").get("Name")

    @property
    def public_ip(self) -> str:
        """Return Public Ip of the instance or None if not present."""
        return self._instance_data.get("PublicIpAddress", None)

    @property
    def private_ip(self) -> str:
        """Return Private Ip of the instance."""
        return self._instance_data.get("PrivateIpAddress")

    @property
    def private_dns_name(self) -> str:
        """Return Private DNS name of the instance (e.g. "ip-10-0-0-157.us-east-2.compute.internal")."""
        return self._instance_data.get("PrivateDnsName")

    @property
    def private_dns_name_short(self) -> str:
        """Return short form of the Private DNS name of the instance (e.g. ip-10-0-0-157)."""
        return self.private_dns_name.split(".")[0]

    @property
    def instance_type(self) -> str:
        """Return instance type."""
        return self._instance_data.get("InstanceType")

    @property
    def launch_time(self):
        """Return launch time of the instance."""
        return self._instance_data.get("LaunchTime")

    @property
    def node_type(self) -> str:
        """Return node type of the instance."""
        return self._get_tag(PCLUSTER_NODE_TYPE_TAG)

    @property
    def queue_name(self) -> str:
        """Return queue name of the instance."""
        return self._get_tag(PCLUSTER_QUEUE_NAME_TAG)

    def _get_tag(self, tag_key):
        return next(iter([tag["Value"] for tag in self._tags if tag["Key"] == tag_key]), None)


class InstanceTypeInfo:
    """Data object wrapping the result of a describe_instance_types call."""

    def __init__(self, instance_type_data):
        self.instance_type_data = instance_type_data

    def gpu_count(self):
        """Return the number of GPUs for the instance."""
        # FixMe: this method is not used in the pcluster3 CLI
        gpu_info = self.instance_type_data.get("GpuInfo", None)

        gpu_count = 0
        if gpu_info:
            for gpus in gpu_info.get("Gpus", []):
                gpu_manufacturer = gpus.get("Manufacturer", "")
                if gpu_manufacturer.upper() == "NVIDIA":
                    gpu_count += gpus.get("Count", 0)
                else:
                    LOGGER.warning(
                        "ParallelCluster currently does not offer native support for '%s' GPUs. "
                        "Please make sure to use a custom AMI with the appropriate drivers in order to leverage "
                        "GPUs functionalities",
                        gpu_manufacturer,
                    )

        return gpu_count

    def max_network_interface_count(self) -> int:
        """Max number of NICs for the instance."""
        return int(self.instance_type_data.get("NetworkInfo").get("MaximumNetworkCards", 1))

    def default_threads_per_core(self):
        """Return the default threads per core for the given instance type."""
        return self.instance_type_data.get("VCpuInfo", {}).get("DefaultThreadsPerCore")

    def valid_threads_per_core(self):
        """Return the valid threads per core for the given instance type."""
        return self.instance_type_data.get("VCpuInfo", {}).get("ValidThreadsPerCore", [])

    def vcpus_count(self) -> int:
        """Get number of vcpus for the given instance type."""
        try:
            vcpus_info = self.instance_type_data.get("VCpuInfo")
            vcpus = vcpus_info.get("DefaultVCpus")
        except KeyError:
            vcpus = -1

        return vcpus

    def supported_architecture(self):
        """Return the list of supported architectures."""
        supported_architectures = self.instance_type_data.get("ProcessorInfo").get("SupportedArchitectures")
        # Some instance types support multiple architectures (x86_64 and i386). Filter unsupported ones.
        return list(set(supported_architectures) & set(SUPPORTED_ARCHITECTURES))

    def is_efa_supported(self):
        """Check whether EFA is supported."""
        return self.instance_type_data.get("NetworkInfo").get("EfaSupported")

    def instance_type(self):
        """Get the instance type."""
        return self.instance_type_data.get("InstanceType")

    def is_cpu_options_supported_in_lt(self):
        """Check whether hyperthreading can be disabled via CPU options."""
        # If default threads per core is 1, HT doesn't need to be disabled
        # When CpuOptions is not supported, valid threads per core can't be found in vcpu info
        return self.default_threads_per_core() > 1 and 1 in self.valid_threads_per_core()

    def is_ebs_optimized(self):
        """Check whether the instance has optimized EBS support."""
        ebs_optimized = False
        ebs_info = self.instance_type_data.get("EbsInfo")
        if ebs_info:
            ebs_optimized = ebs_info.get("EbsOptimizedSupport") != "unsupported"
        return ebs_optimized

    def supported_usage_classes(self):
        """Return the list supported usage classes."""
        supported_classes = self.instance_type_data.get("SupportedUsageClasses", [])
        if "on-demand" in supported_classes:
            # Replace official AWS with internal naming convention
            supported_classes.remove("on-demand")
            supported_classes.append("ondemand")
        return supported_classes


class FsxFileSystemInfo:
    """Data object wrapping the result of a describe_file_systems call."""

    def __init__(self, file_system_data):
        self.file_system_data = file_system_data

    @property
    def mount_name(self):
        """Return MountName of the filesystem."""
        return self.file_system_data.get("LustreConfiguration").get("MountName")

    @property
    def dns_name(self):
        """Return DNSName of the filesystem."""
        return self.file_system_data.get("DNSName")


class ImageInfo:
    """Object to store Ec2 Image information, initialized with the describe_image or describe_images in ec2 client."""

    def __init__(self, image_data: dict):
        self._image_data = image_data

    @property
    def name(self) -> str:
        """Return image name."""
        return self._image_data.get("Name")

    @property
    def pcluster_image_id(self) -> str:
        """Return pcluster image id."""
        return self._get_tag(PCLUSTER_IMAGE_ID_TAG)

    @property
    def id(self) -> str:
        """Return image id."""
        return self._image_data.get("ImageId")

    @property
    def description(self) -> str:
        """Return image description."""
        return self._image_data.get("Description")

    @property
    def state(self) -> str:
        """Return image state."""
        return self._image_data.get("State")

    @property
    def architecture(self) -> str:
        """Return image supports architecture."""
        return self._image_data.get("Architecture")

    @property
    def tags(self) -> list:
        """Return image tags."""
        return self._image_data.get("Tags", [])

    @property
    def block_device_mappings(self) -> list:
        """Return device block mappings."""
        return self._image_data.get("BlockDeviceMappings")

    @property
    def snapshot_ids(self) -> list:
        """Return snapshot ids."""
        snapshot_ids = []
        for block_device_mapping in self.block_device_mappings:
            if block_device_mapping.get("Ebs"):
                snapshot_ids.append(block_device_mapping.get("Ebs").get("SnapshotId"))
        return snapshot_ids

    @property
    def volume_size(self) -> int:
        """Return root volume size."""
        return self.block_device_mappings[0].get("Ebs").get("VolumeSize")

    @property
    def device_name(self) -> str:
        """Return root volume device name."""
        return self.block_device_mappings[0].get("DeviceName")

    @property
    def image_os(self) -> str:
        """Return os of image."""
        return self._get_tag(PCLUSTER_IMAGE_OS_TAG)

    @property
    def s3_bucket_name(self) -> str:
        """Return the name of the bucket used to store image information."""
        return self._get_tag(PCLUSTER_S3_BUCKET_TAG)

    @property
    def s3_artifact_directory(self) -> str:
        """Return the artifact directory of the bucket used to store image information."""
        return self._get_tag(PCLUSTER_S3_IMAGE_DIR_TAG)

    @property
    def creation_date(self) -> str:
        """Return image creation date."""
        return self._image_data.get("CreationDate")

    @property
    def build_log(self) -> str:
        """Return build log arn."""
        return self._get_tag(PCLUSTER_IMAGE_BUILD_LOG_TAG)

    @property
    def version(self) -> str:
        """Return version."""
        return self._get_tag(PCLUSTER_VERSION_TAG)

    @property
    def config_url(self) -> str:
        """Return config url in S3 bucket."""
        return self._get_tag(PCLUSTER_IMAGE_CONFIG_TAG)

    def _get_tag(self, tag_key: str):
        return next(iter([tag["Value"] for tag in self.tags if tag["Key"] == tag_key]), None)
