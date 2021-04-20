import pytest
from assertpy import assert_that

from common.aws.aws_resources import InstanceTypeInfo
from pcluster.config.cluster_config import (
    AmiSearchFilters,
    BaseClusterConfig,
    ClusterDevSettings,
    HeadNode,
    HeadNodeNetworking,
    Image,
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
        return BaseClusterConfig(image=Image("alinux2"), head_node=HeadNode("c5.xlarge", HeadNodeNetworking("subnet")))

    @pytest.mark.parametrize(
        "custom_ami, ami_filters",
        [
            (None, None),
            (None, AmiSearchFilters(owner="owner", tags=[Tag("key1", "value1")])),
            ("ami-custom", None),
            ("ami-custom", AmiSearchFilters(owner="owner", tags=[Tag("key1", "value1")])),
        ],
    )
    def test_ami_id(self, base_cluster_config, aws_api_mock, custom_ami, ami_filters):
        if custom_ami:
            base_cluster_config.image.custom_ami = custom_ami
        if ami_filters:
            base_cluster_config.dev_settings = ClusterDevSettings(ami_search_filters=ami_filters)

        expected_ami = custom_ami or "official-ami-id"
        aws_api_mock.ec2.get_official_image_id.return_value = expected_ami
        ami_id = base_cluster_config.ami_id
        assert_that(ami_id).is_equal_to(expected_ami)

        if not custom_ami:
            aws_api_mock.ec2.get_official_image_id.assert_called_with("alinux2", "x86_64", ami_filters)
        else:
            aws_api_mock.ec2.get_official_image_id.assert_not_called()
