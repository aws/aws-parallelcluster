import pytest
from assertpy import assert_that

from pcluster.aws.aws_resources import InstanceTypeInfo
from pcluster.config.cluster_config import (
    AmiSearchFilters,
    BaseClusterConfig,
    ClusterDevSettings,
    HeadNode,
    HeadNodeImage,
    HeadNodeNetworking,
    Image,
    QueueImage,
    QueueNetworking,
    SlurmClusterConfig,
    SlurmComputeResource,
    SlurmQueue,
    SlurmScheduling,
    Tag,
)


@pytest.fixture
def instance_type_info_mock(aws_api_mock):
    aws_api_mock.ec2.get_instance_type_info.return_value = InstanceTypeInfo(
        {
            "InstanceType": "g4ad.16xlarge",
            "VCpuInfo": {"DefaultVCpus": 64},
            "GpuInfo": {"Gpus": [{"Name": "*", "Manufacturer": "AMD", "Count": 4}]},
            "NetworkInfo": {"EfaSupported": False, "MaximumNetworkCards": 1},
            "ProcessorInfo": {"SupportedArchitectures": ["x86_64"]},
        }
    )


@pytest.mark.usefixtures("instance_type_info_mock")
class TestBaseClusterConfig:
    @pytest.fixture()
    def base_cluster_config(self):
        return BaseClusterConfig(
            cluster_name="clustername",
            image=Image("alinux2"),
            head_node=HeadNode("c5.xlarge", HeadNodeNetworking("subnet")),
        )

    @pytest.fixture()
    def base_slurm_cluster_config(self):
        return SlurmClusterConfig(
            cluster_name="clustername",
            image=Image("alinux2"),
            head_node=HeadNode("c5.xlarge", HeadNodeNetworking("subnet")),
            scheduling=SlurmScheduling(
                [
                    SlurmQueue(
                        name="queue0",
                        networking=QueueNetworking(["subnet"]),
                        compute_resources=[SlurmComputeResource(name="compute_resource_1", instance_type="c5.xlarge")],
                    )
                ]
            ),
        )

    @pytest.mark.parametrize(
        "global_custom_ami, head_node_custom_ami, ami_filters",
        [
            (None, None, None),
            ("ami-custom", None, AmiSearchFilters(owner="owner", tags=[Tag("key1", "value1")])),
            (None, "ami-custom", AmiSearchFilters(owner="owner", tags=[Tag("key1", "value1")])),
            ("ami-custom-1", "ami-custom-2", AmiSearchFilters(owner="owner", tags=[Tag("key1", "value1")])),
        ],
    )
    def test_head_node_ami_id(
        self, base_cluster_config, aws_api_mock, global_custom_ami, head_node_custom_ami, ami_filters
    ):
        if global_custom_ami:
            base_cluster_config.image.custom_ami = global_custom_ami
        if head_node_custom_ami:
            base_cluster_config.head_node.image = HeadNodeImage(custom_ami=head_node_custom_ami)
        if ami_filters:
            base_cluster_config.dev_settings = ClusterDevSettings(ami_search_filters=ami_filters)

        expected_ami = head_node_custom_ami or global_custom_ami or "official-ami-id"
        aws_api_mock.ec2.get_official_image_id.return_value = "official-ami-id"
        ami_id = base_cluster_config.head_node_ami
        assert_that(ami_id).is_equal_to(expected_ami)

        if not (global_custom_ami or head_node_custom_ami):
            aws_api_mock.ec2.get_official_image_id.assert_called_with("alinux2", "x86_64", ami_filters)
        else:
            aws_api_mock.ec2.get_official_image_id.assert_not_called()

    @pytest.mark.parametrize(
        "global_custom_ami, compute_custom_ami, ami_filters",
        [
            (None, None, None),
            ("ami-custom", None, AmiSearchFilters(owner="owner", tags=[Tag("key1", "value1")])),
            (None, "ami-custom", AmiSearchFilters(owner="owner", tags=[Tag("key1", "value1")])),
            ("ami-custom-1", "ami-custom-2", AmiSearchFilters(owner="owner", tags=[Tag("key1", "value1")])),
        ],
    )
    def test_compute_node_ami_id(
        self, base_slurm_cluster_config, aws_api_mock, global_custom_ami, compute_custom_ami, ami_filters
    ):
        if global_custom_ami:
            base_slurm_cluster_config.image.custom_ami = global_custom_ami
        if compute_custom_ami:
            queues = base_slurm_cluster_config.scheduling.queues
            for queue in queues:
                queue.image = QueueImage(custom_ami=compute_custom_ami)
        if ami_filters:
            base_slurm_cluster_config.dev_settings = ClusterDevSettings(ami_search_filters=ami_filters)

        expected_ami = compute_custom_ami or global_custom_ami or "official-ami-id"
        aws_api_mock.ec2.get_official_image_id.return_value = "official-ami-id"
        image_dict = base_slurm_cluster_config.image_dict
        for queue in base_slurm_cluster_config.scheduling.queues:
            assert_that(image_dict[queue.name]).is_equal_to(expected_ami)

        if not (global_custom_ami or compute_custom_ami):
            aws_api_mock.ec2.get_official_image_id.assert_called_with("alinux2", "x86_64", ami_filters)
        else:
            aws_api_mock.ec2.get_official_image_id.assert_not_called()
