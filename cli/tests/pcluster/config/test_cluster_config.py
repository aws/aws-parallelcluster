import pytest
from assertpy import assert_that

from pcluster.aws.aws_resources import CapacityReservationInfo, InstanceTypeInfo
from pcluster.config.cluster_config import (
    AmiSearchFilters,
    BaseClusterConfig,
    BaseQueue,
    CapacityReservationTarget,
    CapacityType,
    ClusterDevSettings,
    ComputeSettings,
    Ebs,
    FlexibleInstanceType,
    GpuHealthCheck,
    HeadNode,
    HeadNodeImage,
    HeadNodeNetworking,
    HeadNodeSsh,
    HealthChecks,
    Image,
    LoginNodes,
    LoginNodesImage,
    LoginNodesNetworking,
    LoginNodesPool,
    LoginNodesSsh,
    PlacementGroup,
    QueueImage,
    SharedEbs,
    SlurmClusterConfig,
    SlurmComputeResource,
    SlurmComputeResourceNetworking,
    SlurmFlexibleComputeResource,
    SlurmQueue,
    SlurmQueueNetworking,
    SlurmScheduling,
    SlurmSettings,
    Tag,
)
from pcluster.validators.ec2_validators import PlacementGroupCapacityTypeValidator
from tests.pcluster.aws.dummy_aws_api import mock_aws_api

mock_compute_resources = [
    SlurmComputeResource(
        instance_type="test",
        name="test1",
        networking=SlurmComputeResourceNetworking(placement_group=PlacementGroup(implied=True)),
        health_checks=HealthChecks(gpu=GpuHealthCheck(enabled=True)),
    ),
    SlurmComputeResource(
        instance_type="test",
        name="test2",
        networking=SlurmComputeResourceNetworking(placement_group=PlacementGroup(enabled=True)),
        health_checks=HealthChecks(gpu=GpuHealthCheck(enabled=False)),
    ),
    SlurmComputeResource(
        instance_type="test",
        name="test3",
        networking=SlurmComputeResourceNetworking(placement_group=PlacementGroup(enabled=False)),
    ),
    SlurmComputeResource(
        instance_type="test",
        name="test4",
        networking=SlurmComputeResourceNetworking(placement_group=PlacementGroup(name="test")),
    ),
    SlurmComputeResource(
        instance_type="test",
        name="test5",
        networking=SlurmComputeResourceNetworking(placement_group=PlacementGroup(id="test")),
    ),
]

network_test_parameters = [
    (
        [
            {"MaximumNetworkCards": 1, "NetworkCards": [{"NetworkCardIndex": 0}]},
            {"MaximumNetworkCards": 1, "NetworkCards": [{"NetworkCardIndex": 0}]},
        ],
        1,
        [0],
        1,
        [0],
    ),
    (
        [
            {"MaximumNetworkCards": 0, "NetworkCards": [{"NetworkCardIndex": 0}]},
            {"MaximumNetworkCards": 0, "NetworkCards": [{"NetworkCardIndex": 0}]},
        ],
        1,
        [0],
        1,
        [0],
    ),
    (
        [
            {"MaximumNetworkCards": 0, "NetworkCards": [{"NetworkCardIndex": 1}, {"NetworkCardIndex": 0}]},
            {
                "MaximumNetworkCards": 3,
                "NetworkCards": [{"NetworkCardIndex": 3}, {"NetworkCardIndex": 2}, {"NetworkCardIndex": 1}],
            },
        ],
        2,
        [1, 0],
        2,
        [1, 0],
    ),
    (
        [
            {
                "MaximumNetworkCards": 3,
                "NetworkCards": [{"NetworkCardIndex": 2}, {"NetworkCardIndex": 0}, {"NetworkCardIndex": 1}],
            },
            {
                "MaximumNetworkCards": 5,
                "NetworkCards": [
                    {"NetworkCardIndex": 0},
                    {"NetworkCardIndex": 1},
                    {"NetworkCardIndex": 2},
                    {"NetworkCardIndex": 3},
                    {"NetworkCardIndex": 4},
                ],
            },
        ],
        3,
        [2, 0, 1],
        3,
        [2, 0, 1],
    ),
    (
        [
            {
                "MaximumNetworkCards": 3,
                "NetworkCards": [{"NetworkCardIndex": 0}, {"NetworkCardIndex": 3}, {"NetworkCardIndex": 5}],
            },
            {
                "MaximumNetworkCards": 4,
                "NetworkCards": [
                    {"NetworkCardIndex": 0},
                    {"NetworkCardIndex": 1},
                    {"NetworkCardIndex": 2},
                    {"NetworkCardIndex": 3},
                ],
            },
        ],
        3,
        [0, 3, 5],
        3,
        [0, 3, 5],
    ),
    (
        [
            {
                "MaximumNetworkCards": 4,
                "NetworkCards": [
                    {"NetworkCardIndex": 7},
                    {"NetworkCardIndex": 3},
                    {"NetworkCardIndex": 5},
                    {"NetworkCardIndex": 0},
                ],
            },
            {
                "MaximumNetworkCards": 3,
                "NetworkCards": [{"NetworkCardIndex": 0}, {"NetworkCardIndex": 3}, {"NetworkCardIndex": 5}],
            },
        ],
        4,
        [7, 3, 5, 0],
        3,
        [0, 3, 5],
    ),
]


@pytest.fixture
def instance_type_info_networking_mock(aws_api_mock, network_info):
    aws_api_mock.ec2.get_instance_type_info.side_effect = [
        InstanceTypeInfo(
            {
                "NetworkInfo": network_info[0],
            }
        ),
        InstanceTypeInfo(
            {
                "NetworkInfo": network_info[1],
            }
        ),
    ]


@pytest.fixture
def get_region(mocker):
    mocker.patch("pcluster.config.cluster_config.get_region", return_value="WHATEVER_REGION")


@pytest.fixture
def instance_type_info_mock(aws_api_mock):
    aws_api_mock.ec2.get_instance_type_info.return_value = InstanceTypeInfo(
        {
            "InstanceType": "g4ad.16xlarge",
            "VCpuInfo": {"DefaultVCpus": 64},
            "GpuInfo": {"Gpus": [{"Name": "*", "Manufacturer": "AMD", "Count": 4}]},
            "NetworkInfo": {"EfaSupported": False, "MaximumNetworkCards": 1, "NetworkCards": [{"NetworkCardIndex": 0}]},
            "ProcessorInfo": {"SupportedArchitectures": ["x86_64"]},
        }
    )


class TestBaseQueue:
    @pytest.mark.parametrize(
        ("capacity_type", "expected_capacity_type", "expected_error"),
        [
            (None, CapacityType.ONDEMAND, False),
            ("", CapacityType.ONDEMAND, False),
            ("capacity_block", CapacityType.CAPACITY_BLOCK, False),
            ("CAPACITY_BLOCK", CapacityType.CAPACITY_BLOCK, False),
            ("spot", CapacityType.SPOT, False),
            ("SPOT", CapacityType.SPOT, False),
            ("ONDEMAND", CapacityType.ONDEMAND, False),
            ("ondemand", CapacityType.ONDEMAND, False),
            ("wrong-value", CapacityType.ONDEMAND, True),
        ],
    )
    def test_capacity_type_init(self, capacity_type, expected_capacity_type, expected_error, caplog):
        queue = BaseQueue(name="queue1", capacity_type=capacity_type)
        if expected_error:
            assert_that(caplog.text).contains("'WRONG-VALUE' is not a valid CapacityType value, setting ONDEMAND")

        assert_that(queue.name).is_equal_to("queue1")
        assert_that(queue.capacity_type).is_equal_to(expected_capacity_type)

    @pytest.mark.parametrize(
        ("capacity_type", "expected_result"),
        [("CAPACITY_BLOCK", False), ("spot", True), ("SPOT", True), ("ONDEMAND", False)],
    )
    def test_is_spot(self, capacity_type, expected_result):
        queue = BaseQueue(name="queue1", capacity_type=capacity_type)
        assert_that(queue.is_spot()).is_equal_to(expected_result)

    @pytest.mark.parametrize(
        ("capacity_type", "expected_result"),
        [("capacity_block", True), ("CAPACITY_BLOCK", True), ("SPOT", False), ("ONDEMAND", False)],
    )
    def test_is_capacity_block(self, capacity_type, expected_result):
        queue = BaseQueue(name="queue1", capacity_type=capacity_type)
        assert_that(queue.is_capacity_block()).is_equal_to(expected_result)


class TestSlurmComputeResource:
    @pytest.mark.parametrize(
        ("capacity_reservation_target", "avail_capacity_reservations", "expected_instance_type"),
        [
            (None, None, None),
            (CapacityReservationTarget(), None, None),
            (CapacityReservationTarget(capacity_reservation_resource_group_arn="arn"), None, None),
            (CapacityReservationTarget(capacity_reservation_id="cr-123456"), None, None),
            (CapacityReservationTarget(capacity_reservation_id="cr-123456"), [], None),
            (
                CapacityReservationTarget(capacity_reservation_id="cr-123456"),
                [CapacityReservationInfo({"InstanceType": "mocked-instance-type"})],
                "mocked-instance-type",
            ),
        ],
    )
    def test_instance_type_from_capacity_reservation(
        self, mocker, capacity_reservation_target, avail_capacity_reservations, expected_instance_type
    ):
        mock_aws_api(mocker)
        describe_capacity_res_mock = mocker.patch(
            "pcluster.aws.ec2.Ec2Client.describe_capacity_reservations", return_value=avail_capacity_reservations
        )

        compute_resource = SlurmComputeResource(name="name", capacity_reservation_target=capacity_reservation_target)
        assert_that(compute_resource._instance_type_from_capacity_reservation()).is_equal_to(expected_instance_type)
        if capacity_reservation_target and capacity_reservation_target.capacity_reservation_id:
            describe_capacity_res_mock.assert_called()
        else:
            describe_capacity_res_mock.assert_not_called()

    @pytest.mark.parametrize(
        ("instance_type", "capacity_reservation_target", "expected_instance_type"),
        [
            (None, None, None),
            ("t3.micro", None, "t3.micro"),
            (None, CapacityReservationTarget(capacity_reservation_resource_group_arn="arn"), None),
            (None, CapacityReservationTarget(capacity_reservation_id="cr-123456"), "mocked-instance-type"),
            # instance type param wins
            ("t3.micro", CapacityReservationTarget(capacity_reservation_id="cr-123456"), "t3.micro"),
        ],
    )
    def test_instance_types(self, mocker, instance_type, capacity_reservation_target, expected_instance_type):
        mock_aws_api(mocker)
        describe_capacity_res_mock = mocker.patch(
            "pcluster.aws.ec2.Ec2Client.describe_capacity_reservations",
            return_value=[CapacityReservationInfo({"InstanceType": "mocked-instance-type"})],
        )
        compute_resource = SlurmComputeResource(
            name="name", instance_type=instance_type, capacity_reservation_target=capacity_reservation_target
        )
        assert_that(compute_resource.instance_types).is_equal_to([expected_instance_type])

        if not instance_type and capacity_reservation_target and capacity_reservation_target.capacity_reservation_id:
            describe_capacity_res_mock.assert_called()
        else:
            describe_capacity_res_mock.assert_not_called()

    @pytest.mark.usefixtures("instance_type_info_networking_mock")
    @pytest.mark.usefixtures(
        "get_region", "expected_max_network_cards_flexible", "expected_network_cards_index_list_flexible"
    )
    @pytest.mark.parametrize(
        "network_info, expected_max_network_cards, expected_network_cards_index_list, "
        "expected_max_network_cards_flexible, expected_network_cards_index_list_flexible",
        network_test_parameters,
    )
    def test_network_cards(self, expected_max_network_cards, expected_network_cards_index_list):
        compute_resource = SlurmComputeResource(name="compute_resource")
        assert_that(compute_resource.max_network_cards).is_equal_to(expected_max_network_cards)
        network_cards_list = compute_resource.network_cards_list
        for index in range(len(expected_network_cards_index_list)):
            assert_that(network_cards_list[index].network_card_index()).is_equal_to(
                expected_network_cards_index_list[index]
            )


@pytest.mark.usefixtures("instance_type_info_mock")
@pytest.mark.usefixtures("get_region")
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
                        networking=SlurmQueueNetworking(subnet_ids=["subnet"]),
                        compute_resources=[SlurmComputeResource(name="compute_resource_1", instance_type="c5.xlarge")],
                    )
                ]
            ),
        )

    @pytest.mark.parametrize(
        "memory_scheduling_enabled",
        [True, False],
    )
    def test_registration_of_validators(self, memory_scheduling_enabled, mocker):
        cluster_config = SlurmClusterConfig(
            cluster_name="clustername",
            login_nodes=None,
            image=Image("alinux2"),
            head_node=HeadNode("c5.xlarge", HeadNodeNetworking("subnet")),
            scheduling=SlurmScheduling(
                [
                    SlurmQueue(
                        name="queue0",
                        networking=SlurmQueueNetworking(subnet_ids=["subnet"]),
                        compute_resources=[
                            SlurmComputeResource(name="compute_resource_1", instance_type="c5.xlarge"),
                            SlurmFlexibleComputeResource(
                                [FlexibleInstanceType(instance_type="c5.xlarge")], name="compute_resource_2"
                            ),
                            SlurmFlexibleComputeResource(
                                [FlexibleInstanceType(instance_type="c5n.18xlarge")], name="compute_resource_3"
                            ),
                        ],
                    )
                ],
                SlurmSettings(
                    enable_memory_based_scheduling=memory_scheduling_enabled,
                ),
            ),
        )
        cluster_config._register_validators()
        actual_validators = cluster_config._validators
        assert_that(actual_validators).is_not_empty()
        assert_that(actual_validators).contains(
            (
                PlacementGroupCapacityTypeValidator().__class__,
                {"capacity_type": CapacityType.ONDEMAND, "placement_group_enabled": False},
            )
        )

    def test_instances_in_slurm_queue(self):
        queue = SlurmQueue(
            name="queue0",
            networking=SlurmQueueNetworking(subnet_ids=["subnet"]),
            compute_resources=[
                SlurmComputeResource(name="compute_resource_1", instance_type="c5n.4xlarge"),
                SlurmComputeResource(name="compute_resource_2", instance_type="t3.micro"),
                SlurmFlexibleComputeResource(
                    name="compute_resource_3",
                    instances=[
                        FlexibleInstanceType(instance_type="c5n.4xlarge"),
                        FlexibleInstanceType(instance_type="c5n.9xlarge"),
                        FlexibleInstanceType(instance_type="c5n.18xlarge"),
                    ],
                ),
                SlurmFlexibleComputeResource(
                    name="compute_resource_4",
                    instances=[
                        FlexibleInstanceType(instance_type="c5n.4xlarge"),
                    ],
                ),
            ],
        )

        expected_instance_type_list = ["c5n.4xlarge", "t3.micro", "c5n.9xlarge", "c5n.18xlarge"]
        assert_that(queue.instance_type_list).is_length(len(expected_instance_type_list))
        assert_that(set(queue.instance_type_list) - set(expected_instance_type_list)).is_length(0)

    def test_placement_group_in_compute_resource(self):
        queue = SlurmQueue(
            name="queue0",
            networking=SlurmQueueNetworking(subnet_ids=["subnet"]),
            compute_resources=[
                SlurmComputeResource(
                    name="compute_resource_1",
                    instance_type="c5n.4xlarge",
                    networking=SlurmComputeResourceNetworking(placement_group=PlacementGroup(name="mock-pg")),
                ),
                SlurmComputeResource(name="compute_resource_2", instance_type="t3.micro"),
            ],
        )

        assert_that(queue.compute_resources[0].networking).is_not_none()
        assert_that(queue.compute_resources[0].networking.placement_group).is_not_none()
        assert_that(queue.compute_resources[0].networking.placement_group.name).is_equal_to("mock-pg")
        assert_that(queue.compute_resources[0].networking.placement_group.id).is_none()
        assert_that(queue.compute_resources[0].networking.placement_group.enabled).is_false()

        queue = SlurmQueue(
            name="queue0",
            networking=SlurmQueueNetworking(subnet_ids=["subnet"]),
            compute_resources=[
                SlurmComputeResource(
                    name="compute_resource_1",
                    instance_type="c5n.4xlarge",
                    networking=SlurmComputeResourceNetworking(placement_group=PlacementGroup(id="mock-pg")),
                ),
                SlurmComputeResource(name="compute_resource_2", instance_type="t3.micro"),
            ],
        )

        assert_that(queue.compute_resources[0].networking.placement_group.id).is_equal_to("mock-pg")
        assert_that(queue.compute_resources[0].networking.placement_group.name).is_none()
        assert_that(queue.compute_resources[0].networking.placement_group.enabled).is_false()

        queue = SlurmQueue(
            name="queue0",
            networking=SlurmQueueNetworking(subnet_ids=["subnet"]),
            compute_resources=[
                SlurmComputeResource(
                    name="compute_resource_1",
                    instance_type="c5n.4xlarge",
                    networking=SlurmComputeResourceNetworking(placement_group=PlacementGroup(enabled=True)),
                ),
                SlurmComputeResource(name="compute_resource_2", instance_type="t3.micro"),
            ],
        )

        assert_that(queue.compute_resources[0].networking.placement_group.id).is_none()
        assert_that(queue.compute_resources[0].networking.placement_group.name).is_none()
        assert_that(queue.compute_resources[0].networking.placement_group.enabled).is_true()

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

    @pytest.mark.parametrize(
        "queue_parameters, expected_result",
        [
            (
                dict(
                    name="queue",
                    networking=SlurmQueueNetworking(subnet_ids=[], placement_group=PlacementGroup(enabled=False)),
                    compute_resources=mock_compute_resources,
                ),
                [
                    {"key": None, "is_managed": False},
                    {"key": "queue-test2", "is_managed": True},
                    {"key": None, "is_managed": False},
                    {"key": "test", "is_managed": False},
                    {"key": "test", "is_managed": False},
                ],
            ),
            (
                dict(
                    name="queue",
                    networking=SlurmQueueNetworking(subnet_ids=[], placement_group=PlacementGroup(enabled=True)),
                    compute_resources=mock_compute_resources,
                ),
                [
                    {"key": "queue-test1", "is_managed": True},
                    {"key": "queue-test2", "is_managed": True},
                    {"key": None, "is_managed": False},
                    {"key": "test", "is_managed": False},
                    {"key": "test", "is_managed": False},
                ],
            ),
            (
                dict(
                    name="queue",
                    networking=SlurmQueueNetworking(subnet_ids=[], placement_group=PlacementGroup(name="test-q")),
                    compute_resources=mock_compute_resources,
                ),
                [
                    {"key": "test-q", "is_managed": False},
                    {"key": "queue-test2", "is_managed": True},
                    {"key": None, "is_managed": False},
                    {"key": "test", "is_managed": False},
                    {"key": "test", "is_managed": False},
                ],
            ),
            (
                dict(
                    name="queue",
                    networking=SlurmQueueNetworking(subnet_ids=[], placement_group=PlacementGroup()),
                    compute_resources=mock_compute_resources,
                ),
                [
                    {"key": None, "is_managed": False},
                    {"key": "queue-test2", "is_managed": True},
                    {"key": None, "is_managed": False},
                    {"key": "test", "is_managed": False},
                    {"key": "test", "is_managed": False},
                ],
            ),
        ],
    )
    def test_get_placement_group_settings_for_compute_resource(self, queue_parameters, expected_result):
        queue = SlurmQueue(**queue_parameters)
        actual = []
        for resource in queue.compute_resources:
            actual.append(queue.get_placement_group_settings_for_compute_resource(resource))
        assert_that(actual).is_equal_to(expected_result)

    @pytest.mark.parametrize(
        "queue_parameters, expected_result",
        [
            (
                dict(
                    name="queue",
                    networking=SlurmQueueNetworking(subnet_ids=[], placement_group=PlacementGroup(enabled=False)),
                    compute_resources=mock_compute_resources,
                ),
                ["queue-test2"],
            ),
            (
                dict(
                    name="queue",
                    networking=SlurmQueueNetworking(subnet_ids=[], placement_group=PlacementGroup(enabled=True)),
                    compute_resources=mock_compute_resources,
                ),
                ["queue-test1", "queue-test2"],
            ),
            (
                dict(
                    name="queue",
                    networking=SlurmQueueNetworking(subnet_ids=[], placement_group=PlacementGroup(name="test-q")),
                    compute_resources=mock_compute_resources,
                ),
                ["queue-test2"],
            ),
            (
                dict(
                    name="queue",
                    networking=SlurmQueueNetworking(subnet_ids=[], placement_group=PlacementGroup()),
                    compute_resources=mock_compute_resources,
                ),
                ["queue-test2"],
            ),
        ],
    )
    def test_get_managed_placement_group_keys(self, queue_parameters, expected_result):
        queue = SlurmQueue(**queue_parameters)
        actual = queue.get_managed_placement_group_keys()
        assert_that(actual).is_equal_to(expected_result)

    def test_get_instance_types_data(self, base_cluster_config):
        assert_that(base_cluster_config.get_instance_types_data()).is_equal_to({})

    @pytest.mark.parametrize(
        "queue_parameters, expected_result",
        [
            # At ComputeResource level the Health Check is enabled for CR test1, disabled for CR test2
            # undefined otherwise
            (
                # Health Checks section is not defined at SlurmQuel level
                dict(
                    name="queue",
                    networking=SlurmQueueNetworking(subnet_ids=[], placement_group=PlacementGroup(enabled=False)),
                    compute_resources=mock_compute_resources,
                ),
                ["test1", "", "", "", ""],
            ),
            (
                # Health Checks section is enabled at SlurmQuel level
                dict(
                    name="queue",
                    networking=SlurmQueueNetworking(subnet_ids=[], placement_group=PlacementGroup(enabled=False)),
                    health_checks=HealthChecks(gpu=GpuHealthCheck(enabled=True)),
                    compute_resources=mock_compute_resources,
                ),
                ["test1", "", "queue", "queue", "queue"],
            ),
            (
                # Health Checks section is disabled at SlurmQuel level
                dict(
                    name="queue",
                    networking=SlurmQueueNetworking(subnet_ids=[], placement_group=PlacementGroup(enabled=False)),
                    health_checks=HealthChecks(gpu=GpuHealthCheck(enabled=False)),
                    compute_resources=mock_compute_resources,
                ),
                ["test1", "", "", "", ""],
            ),
        ],
    )
    def test_get_enabled_health_checks_section(self, queue_parameters, expected_result):
        queue = SlurmQueue(**queue_parameters)
        health_check_gpu_enabled = []
        queue_gpu_check_enabled = queue.health_checks.gpu is not None and queue.health_checks.gpu.enabled
        for compute_resource in queue.compute_resources:
            compute_resource_gpu_check_enabled = (
                compute_resource.health_checks.gpu is not None and compute_resource.health_checks.gpu.enabled
            )
            if compute_resource_gpu_check_enabled:
                health_check_gpu_enabled.append(compute_resource.name)
            elif compute_resource_gpu_check_enabled is False:
                health_check_gpu_enabled.append("")
            elif queue_gpu_check_enabled:
                health_check_gpu_enabled.append(queue.name)
            else:
                health_check_gpu_enabled.append("")
        assert_that(health_check_gpu_enabled).is_equal_to(expected_result)

    @pytest.mark.parametrize(
        "region, expected_volume_type",
        [
            ("us-iso-WHATEVER", "gp3"),
            ("us-isob-WHATEVER", "gp3"),
            ("WHATEVER_ELSE_REGION", "gp3"),
        ],
    )
    def test_head_node_root_volume(self, mocker, region, expected_volume_type):
        mocker.patch("pcluster.config.cluster_config.get_region", return_value=region)

        cluster_config = BaseClusterConfig(
            cluster_name="clustername",
            image=Image("alinux2"),
            head_node=HeadNode("c5.xlarge", HeadNodeNetworking("subnet")),
        )

        assert_that(cluster_config.head_node.local_storage.root_volume.volume_type).is_equal_to(expected_volume_type)

    @pytest.mark.parametrize(
        "region, expected_volume_type",
        [
            ("us-iso-WHATEVER", "gp3"),
            ("us-isob-WHATEVER", "gp3"),
            ("WHATEVER_ELSE_REGION", "gp3"),
        ],
    )
    def test_compute_settings_root_volume(self, mocker, region, expected_volume_type):
        mocker.patch("pcluster.config.cluster_config.get_region", return_value=region)

        compute_settings = ComputeSettings()

        assert_that(compute_settings.local_storage.root_volume.volume_type).is_equal_to(expected_volume_type)

    def test_tags_in_slurm_queue(self):
        tags = [Tag("key1", "value1"), Tag("key2", "value2"), Tag("key3", "value3")]
        queue = SlurmQueue(
            name="queue0",
            networking=SlurmQueueNetworking(subnet_ids=["subnet"]),
            compute_resources=mock_compute_resources,
            tags=tags,
        )
        assert_that(queue.get_tags()).is_equal_to(tags)

    def test_login_node_pool_default_value(self):
        login_node_pool = LoginNodesPool(
            name="test_pool2",
            instance_type="t3.xlarge",
            image=LoginNodesImage(custom_ami="ami-0222222222222222"),
            networking=LoginNodesNetworking(subnet_ids=["subnet-0222222222222222"]),
            ssh=LoginNodesSsh(key_name="mykey"),
        )

        login_nodes = LoginNodes(pools=[login_node_pool])
        assert_that(login_nodes.pools[0].count).is_equal_to(1)
        assert_that(login_nodes.pools[0].gracetime_period).is_equal_to(10)

    @pytest.mark.parametrize(
        "queue, expected_value",
        [
            # JobExclusiveAllocation should be disabled by default
            (
                dict(
                    name="queue",
                    networking=SlurmQueueNetworking(subnet_ids=[], placement_group=PlacementGroup(enabled=False)),
                    compute_resources=mock_compute_resources,
                ),
                False,
            ),
            (
                dict(
                    name="queue",
                    networking=SlurmQueueNetworking(subnet_ids=[], placement_group=PlacementGroup(enabled=False)),
                    job_exclusive_allocation=True,
                    compute_resources=mock_compute_resources,
                ),
                True,
            ),
            (
                dict(
                    name="queue",
                    networking=SlurmQueueNetworking(subnet_ids=[], placement_group=PlacementGroup(enabled=False)),
                    job_exclusive_allocation=False,
                    compute_resources=mock_compute_resources,
                ),
                False,
            ),
        ],
    )
    def test_job_exclusive_allocation_defaults(self, queue, expected_value):
        queue = SlurmQueue(**queue)
        assert_that(queue.job_exclusive_allocation).is_equal_to(expected_value)

    @pytest.mark.parametrize(
        "head_node_ssh, login_node_ssh, expected_values",
        [
            (
                HeadNodeSsh(key_name="head-node-key", allowed_ips="1.2.3.4/24"),
                LoginNodesSsh(key_name="login-node-key", allowed_ips="6.5.4.3/24"),
                {"key_name": "login-node-key", "allowed_ips": "6.5.4.3/24"},
            ),
            (
                HeadNodeSsh(key_name="head-node-key", allowed_ips="1.2.3.4/24"),
                LoginNodesSsh(key_name=None),
                {"key_name": "head-node-key", "allowed_ips": "1.2.3.4/24"},
            ),
            (
                HeadNodeSsh(key_name="head-node-key", allowed_ips="1.2.3.4/24"),
                None,
                {"key_name": "head-node-key", "allowed_ips": "1.2.3.4/24"},
            ),
            (
                None,
                LoginNodesSsh(key_name="login-node-key"),
                {"key_name": "login-node-key", "allowed_ips": "0.0.0.0/0"},
            ),
        ],
    )
    def test_login_nodes_ssh_default_values(self, head_node_ssh, login_node_ssh, expected_values, mocker):
        cluster_config = SlurmClusterConfig(
            cluster_name="clustername",
            login_nodes=LoginNodes(
                [
                    LoginNodesPool(
                        name="test_pool",
                        instance_type="t3.xlarge",
                        image=LoginNodesImage(custom_ami="ami-12345678"),
                        networking=LoginNodesNetworking(subnet_ids=["subnet-12345678"]),
                        ssh=login_node_ssh,
                    )
                ]
            ),
            image=Image("alinux2"),
            head_node=HeadNode("c5.xlarge", HeadNodeNetworking("subnet"), ssh=head_node_ssh),
            scheduling=SlurmScheduling(
                [
                    SlurmQueue(
                        name="queue0",
                        networking=SlurmQueueNetworking(subnet_ids=["subnet"]),
                        compute_resources=[
                            SlurmComputeResource(name="compute_resource_1", instance_type="c5.xlarge"),
                            SlurmFlexibleComputeResource(
                                [FlexibleInstanceType(instance_type="c5.xlarge")], name="compute_resource_2"
                            ),
                            SlurmFlexibleComputeResource(
                                [FlexibleInstanceType(instance_type="c5n.18xlarge")], name="compute_resource_3"
                            ),
                        ],
                    )
                ],
            ),
        )
        print(cluster_config.head_node.ssh.key_name)
        print(cluster_config.login_nodes.pools[0].ssh.key_name)
        assert_that(cluster_config.login_nodes.pools[0].ssh.key_name).is_equal_to(expected_values["key_name"])
        assert_that(cluster_config.login_nodes.pools[0].ssh.allowed_ips).is_equal_to(expected_values["allowed_ips"])


class TestSharedEbs:
    @pytest.mark.parametrize(
        "region, expected_volume_type",
        [
            ("us-iso-WHATEVER", "gp3"),
            ("us-isob-WHATEVER", "gp3"),
            ("WHATEVER_ELSE_REGION", "gp3"),
        ],
    )
    def test_shared_storage_ebs(self, mocker, region, expected_volume_type):
        mocker.patch("pcluster.config.cluster_config.get_region", return_value=region)

        shared_ebs = SharedEbs(mount_dir="/mount/dir", name="mount-name")

        assert_that(shared_ebs.volume_type).is_equal_to(expected_volume_type)


class TestEbs:
    @pytest.mark.parametrize(
        "region, expected_volume_type",
        [
            ("us-iso-WHATEVER", "gp3"),
            ("us-isob-WHATEVER", "gp3"),
            ("WHATEVER_ELSE_REGION", "gp3"),
        ],
    )
    def test_shared_storage_ebs(self, mocker, region, expected_volume_type):
        mocker.patch("pcluster.config.cluster_config.get_region", return_value=region)

        ebs = Ebs()

        assert_that(ebs.volume_type).is_equal_to(expected_volume_type)


class TestHeadNode:
    @pytest.mark.usefixtures("instance_type_info_networking_mock")
    @pytest.mark.usefixtures(
        "get_region", "expected_max_network_cards_flexible", "expected_network_cards_index_list_flexible"
    )
    @pytest.mark.parametrize(
        "network_info, expected_max_network_cards, expected_network_cards_index_list, "
        "expected_max_network_cards_flexible, expected_network_cards_index_list_flexible",
        network_test_parameters,
    )
    def test_network_cards(self, expected_max_network_cards, expected_network_cards_index_list):
        head_node = HeadNode("c5.xlarge", HeadNodeNetworking("subnet"))
        assert_that(head_node.max_network_cards).is_equal_to(expected_max_network_cards)
        for index in range(len(expected_network_cards_index_list)):
            assert_that(head_node.network_cards_list[index].network_card_index()).is_equal_to(
                expected_network_cards_index_list[index]
            )


class TestSlurmFlexibleComputeResource:
    @pytest.mark.usefixtures("instance_type_info_networking_mock")
    @pytest.mark.usefixtures("get_region", "expected_max_network_cards", "expected_network_cards_index_list")
    @pytest.mark.parametrize(
        "network_info, expected_max_network_cards, expected_network_cards_index_list, "
        "expected_max_network_cards_flexible, expected_network_cards_index_list_flexible",
        network_test_parameters,
    )
    def test_network_cards(self, expected_max_network_cards_flexible, expected_network_cards_index_list_flexible):
        compute_resource = SlurmFlexibleComputeResource(
            [FlexibleInstanceType(instance_type="type_1"), FlexibleInstanceType(instance_type="type_2")],
            name="compute_resource",
        )
        assert_that(compute_resource.max_network_cards).is_equal_to(expected_max_network_cards_flexible)
        for index in range(len(expected_network_cards_index_list_flexible)):
            assert_that(compute_resource.network_cards_list[index].network_card_index()).is_equal_to(
                expected_network_cards_index_list_flexible[index]
            )
