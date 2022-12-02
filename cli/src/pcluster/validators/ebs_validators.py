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
from pcluster.aws.aws_api import AWSApi
from pcluster.aws.common import AWSClientError
from pcluster.utils import get_partition
from pcluster.validators.common import FailureLevel, Validator

EBS_VOLUME_TYPE_TO_VOLUME_SIZE_BOUNDS = {
    "standard": (1, 1024),
    "io1": (4, 16 * 1024),
    "io2": (4, 64 * 1024),
    "gp2": (1, 16 * 1024),
    "gp3": (1, 16 * 1024),
    "st1": (500, 16 * 1024),
    "sc1": (500, 16 * 1024),
}

EBS_VOLUME_IOPS_BOUNDS = {
    "io1": (100, 64000),
    "io2": (100, 256000),
    "gp3": (3000, 16000),
}

EBS_VOLUME_TYPE_TO_IOPS_RATIO = {"io1": 50, "io2": 1000, "gp3": 500}


class EbsVolumeTypeSizeValidator(Validator):
    """EBS volume type and size validator.

    Validate that the EBS volume size matches the chosen volume type.

    The default value of volume_size for EBS volumes is 20 GiB.
    The volume size of standard ranges from 1 GiB - 1 TiB(1024 GiB)
    The volume size of gp2 and gp3 ranges from 1 GiB - 16 TiB(16384 GiB)
    The volume size of io1 and io2 ranges from 4 GiB - 16 TiB(16384 GiB)
    The volume sizes of st1 and sc1 range from 500 GiB - 16 TiB(16384 GiB)
    """

    def _validate(self, volume_type: str, volume_size: int):
        if volume_size is not None and volume_type in EBS_VOLUME_TYPE_TO_VOLUME_SIZE_BOUNDS:
            min_size, max_size = EBS_VOLUME_TYPE_TO_VOLUME_SIZE_BOUNDS.get(volume_type)
            if volume_size > max_size:
                self._add_failure(
                    f"The size of {volume_type} volumes can not exceed {max_size} GiB.",
                    FailureLevel.ERROR,
                )
            elif volume_size < min_size:
                self._add_failure(
                    f"The size of {volume_type} volumes must be at least {min_size} GiB.",
                    FailureLevel.ERROR,
                )


class EbsVolumeThroughputValidator(Validator):
    """
    EBS volume throughput validator.

    Validate gp3 throughput.
    """

    def _validate(self, volume_type, volume_throughput):
        if volume_type == "gp3":
            min_throughput, max_throughput = 125, 1000
            if volume_throughput < min_throughput or volume_throughput > max_throughput:
                self._add_failure(
                    f"Throughput must be between {min_throughput} MB/s and {max_throughput} MB/s when provisioning "
                    f"{volume_type} volumes.",
                    FailureLevel.ERROR,
                )


class EbsVolumeThroughputIopsValidator(Validator):
    """
    EBS volume throughput to iops ratio validator.

    Validate gp3 throughput.
    """

    def _validate(self, volume_type, volume_iops, volume_throughput):
        volume_throughput_to_iops_ratio = 0.25
        if volume_type == "gp3":
            if volume_throughput and volume_throughput > volume_iops * volume_throughput_to_iops_ratio:
                self._add_failure(
                    "Throughput to IOPS ratio of {0} is too high; maximum is 0.25.".format(
                        float(volume_throughput) / float(volume_iops)
                    ),
                    FailureLevel.ERROR,
                )


class EbsVolumeIopsValidator(Validator):
    """
    EBS volume IOPS validator.

    Validate IOPS value in respect of volume type.
    """

    def _validate(self, volume_type, volume_size, volume_iops):
        if volume_type in EBS_VOLUME_IOPS_BOUNDS:
            min_iops, max_iops = EBS_VOLUME_IOPS_BOUNDS.get(volume_type)
            if volume_iops and (volume_iops < min_iops or volume_iops > max_iops):
                self._add_failure(
                    f"IOPS rate must be between {min_iops} and {max_iops}" f" when provisioning {volume_type} volumes.",
                    FailureLevel.ERROR,
                )
            elif volume_iops and volume_iops > volume_size * EBS_VOLUME_TYPE_TO_IOPS_RATIO[volume_type]:
                self._add_failure(
                    "IOPS to volume size ratio of {0} is too high; maximum is {1}.".format(
                        float(volume_iops) / float(volume_size),
                        EBS_VOLUME_TYPE_TO_IOPS_RATIO[volume_type],
                    ),
                    FailureLevel.ERROR,
                )
        elif volume_iops:
            self._add_failure(
                f"The parameter IOPS is not supported for {volume_type} volumes.",
                FailureLevel.ERROR,
            )


class EbsVolumeSizeSnapshotValidator(Validator):
    """
    EBS volume size snapshot validator.

    Validate the following cases:
    - The EBS snapshot is in "completed" state if it is specified.
    - If users specify the volume size, the volume must be not smaller than the volume size of the EBS snapshot.
    """

    def _validate(self, snapshot_id: int, volume_size: int):
        if snapshot_id:
            try:
                snapshot_response_dict = AWSApi.instance().ec2.get_ebs_snapshot_info(snapshot_id)

                # validate that the input volume size is larger than the volume size of the EBS snapshot
                snapshot_volume_size = snapshot_response_dict.get("VolumeSize")
                if snapshot_volume_size is None:
                    self._add_failure(f"Unable to get volume size for snapshot {snapshot_id}.", FailureLevel.ERROR)
                elif volume_size < snapshot_volume_size:
                    self._add_failure(
                        f"The EBS volume size must not be smaller than {snapshot_volume_size}, "
                        f"which is the size of the provided snapshot {snapshot_id}.",
                        FailureLevel.ERROR,
                    )
                elif volume_size > snapshot_volume_size:
                    self._add_failure(
                        "The specified volume size is larger than snapshot size. In order to use the full capacity "
                        "of the volume, you'll need to manually resize the partition according to this doc: "
                        "https://{partition_url}/AWSEC2/latest/UserGuide/recognize-expanded-volume-linux.html".format(
                            partition_url="docs.amazonaws.cn" if get_partition() == "aws-cn" else "docs.aws.amazon.com"
                        ),
                        FailureLevel.WARNING,
                    )

                # validate that the state of ebs snapshot
                if snapshot_response_dict.get("State") != "completed":
                    self._add_failure(
                        "Snapshot {0} is in state '{1}' not 'completed'.".format(
                            snapshot_id, snapshot_response_dict.get("State")
                        ),
                        FailureLevel.WARNING,
                    )
            except Exception as exception:
                if isinstance(exception, AWSClientError) and exception.error_code in [
                    "InvalidSnapshot.NotFound",
                    "InvalidSnapshot.Malformed",
                ]:
                    self._add_failure(
                        "The snapshot {0} does not appear to exist: {1}.".format(snapshot_id, str(exception)),
                        FailureLevel.ERROR,
                    )
                else:
                    self._add_failure(
                        "Issue getting info for snapshot {0}: {1}.".format(
                            snapshot_id,
                            str(exception) if isinstance(exception, AWSClientError) else exception,
                        ),
                        FailureLevel.ERROR,
                    )


class MultiAzEbsVolumeValidator(Validator):
    """
    MultiAz Ebs Volume Validator.

    Validate that the EBS volume, HeanNode and ComputeFleet are in the same AZ.
    If they aren't inform the customers about possible increases of latency or costs.
    If the volume is in a different az w.r.t the HeadNode raises an error.
    """

    def _validate(self, head_node_az: str, ebs_volumes, queues):
        cross_az_queues = set()
        for volume in ebs_volumes:
            try:
                # if the EBS volume is managed we set the AZ == to the HeadNode AZ otherwise we ask EC2 about
                # the AZ where the existing volume is created
                ebs_az = head_node_az if volume.is_managed else volume.availability_zone
                if ebs_az != head_node_az:
                    self._add_failure(
                        "Your configuration includes an EBS volume '{0}' created in a different availability zone than "
                        "the Head Node. The volume and instance must be in the same availability "
                        "zone.".format(volume.name),
                        FailureLevel.ERROR,
                    )

                for queue in queues:
                    queue_az_set = set(queue.networking.az_list)
                    if len(queue_az_set) > 1 or ({ebs_az} != queue_az_set):
                        cross_az_queues.add(queue.name)
            except AWSClientError as e:
                if str(e).endswith("parameter volumes is invalid. Expected: 'vol-...'."):
                    self._add_failure(f"Volume '{volume.volume_id}' does not exist.", FailureLevel.ERROR)
                else:
                    self._add_failure(str(e), FailureLevel.ERROR)

        if cross_az_queues:
            self._add_failure(
                "Your configuration for Queues '{0}' includes multiple subnets and external shared storage "
                "configuration. Accessing a shared storage from different AZs can lead to increased storage "
                "network latency and inter-AZ data transfer costs.".format(", ".join(sorted(cross_az_queues))),
                FailureLevel.INFO,
            )


class MultiAzRootVolumeValidator(Validator):
    """
    Root Volume Validator.

    Validates that the root volume associated to the HeanNode and ComputeFleet are in the same AZ.
    If they aren't inform the customers about possible increases of latency or costs.
    """

    def _validate(self, head_node_az: str, queues):
        cross_az_queues = set()

        for queue in queues:
            queue_az_set = set(queue.networking.az_list)
            if len(queue_az_set) > 1 or (set([head_node_az]) != queue_az_set):
                cross_az_queues.add(queue.name)

        if cross_az_queues:
            self._add_failure(
                "Your configuration for Queues '{0}' includes multiple subnets different from where HeadNode is "
                "located. Accessing a shared storage from different AZs can lead to increased storage "
                "network latency and inter-AZ data transfer costs.".format(", ".join(sorted(cross_az_queues))),
                FailureLevel.INFO,
            )


class SharedEbsVolumeIdValidator(Validator):
    """
    SharedEBS volume id validator.

    Validate the volume exist and is available.
    """

    def _validate(self, volume_id: str, head_node_instance_id: str = None):
        if volume_id:
            try:
                respond = AWSApi.instance().ec2.describe_volume(volume_id)

                state = respond.get("State")
                attached_instances = [attachment.get("InstanceId") for attachment in respond.get("Attachments", [])]
                is_available = state == "available"
                is_attached_to_head_node = head_node_instance_id and head_node_instance_id in attached_instances
                # TODO Mounting and EBS Volume with multi-attach is not officially supported.
                # As long as it is not officially supported, we should emit the warning when mounting a not available
                # EBS volume with multi-attach.
                # is_multi_attach_enabled = respond.get("MultiAttachEnabled", False)
                if not is_available and not is_attached_to_head_node:
                    self._add_failure(
                        "Volume {0} is in state '{1}' not 'available'.".format(volume_id, respond.get("State")),
                        FailureLevel.ERROR,
                    )
            except AWSClientError as e:
                if str(e).endswith("parameter volumes is invalid. Expected: 'vol-...'."):
                    self._add_failure(f"Volume '{volume_id}' does not exist.", FailureLevel.ERROR)
                else:
                    self._add_failure(str(e), FailureLevel.ERROR)
