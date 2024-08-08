import pytest
from assertpy import assert_that

from pcluster.models.login_nodes_status import LoginNodesPoolState, LoginNodesStatus


class TestLoginNodesStatus:
    dummy_stack_name = "dummy_cluster_name"
    dummy_load_balancer_arn_1 = "dummy_load_balancer_arn_1"
    dummy_load_balancer_arn_2 = "dummy_load_balancer_arn_2"
    dummy_target_group_arn_1 = "dummy_target_group_arn_1"
    dummy_target_group_arn_2 = "dummy_target_group_arn_2"
    dummy_pool_name_1 = "dummy_pool_name_1"
    dummy_pool_name_2 = "dummy_pool_name_2"
    dummy_scheme_1 = "internet-facing"
    dummy_scheme_2 = "internal"
    dummy_dns_name_1 = "dummy_dns_name_1"
    dummy_dns_name_2 = "dummy_dns_name_2"
    dummy_status = "active"

    dummy_load_balancer_1 = {
        "LoadBalancerArn": dummy_load_balancer_arn_1,
        "DNSName": dummy_dns_name_1,
        "LoadBalancerName": "dummy-load-balancer-1",
        "Scheme": dummy_scheme_1,
        "State": {"Code": dummy_status},
    }
    dummy_load_balancer_2 = {
        "LoadBalancerArn": dummy_load_balancer_arn_2,
        "DNSName": dummy_dns_name_2,
        "LoadBalancerName": "dummy-load-balancer-2",
        "Scheme": dummy_scheme_2,
        "State": {"Code": dummy_status},
    }
    dummy_load_balancer_3 = {
        "LoadBalancerArn": "dummy_load_balancer_arn_3",
        "DNSName": "dummy_dns_name_3",
        "LoadBalancerName": "dummy-load-balancer-3",
        "Scheme": dummy_scheme_2,
        "State": {"Code": "provisioning"},
    }

    dummy_tags_description = [
        {
            "ResourceArn": dummy_load_balancer_arn_1,
            "Tags": [
                {
                    "Key": "parallelcluster:cluster-name",
                    "Value": dummy_stack_name,
                },
                {
                    "Key": "parallelcluster:login-nodes-pool",
                    "Value": dummy_pool_name_1,
                },
            ],
        },
        {
            "ResourceArn": dummy_load_balancer_arn_2,
            "Tags": [
                {
                    "Key": "parallelcluster:cluster-name",
                    "Value": dummy_stack_name,
                },
                {
                    "Key": "parallelcluster:login-nodes-pool",
                    "Value": dummy_pool_name_2,
                },
            ],
        },
        {
            "ResourceArn": "another_dummy_load_balancer_arn",
            "Tags": [
                {
                    "Key": "parallelcluster:cluster-name",
                    "Value": "pcluster-name-2",
                },
                {
                    "Key": "parallelcluster:login-nodes-pool",
                    "Value": "dummy_pool_name_3",
                },
            ],
        },
    ]

    dummy_target_groups = [
        {
            "TargetGroupArn": dummy_target_group_arn_1,
            "HealthCheckPort": "22",
            "LoadBalancerArns": [dummy_load_balancer_arn_1],
        },
        {
            "TargetGroupArn": dummy_target_group_arn_2,
            "HealthCheckPort": "22",
            "LoadBalancerArns": [dummy_load_balancer_arn_2],
        },
    ]

    dummy_targets_health = [
        {
            "HealthCheckPort": "22",
            "Target": {
                "Id": "i-123456",
                "Port": 22,
            },
            "TargetHealth": {
                "State": "healthy",
            },
        },
        {
            "HealthCheckPort": "22",
            "Target": {
                "Id": "i-789101",
                "Port": 22,
            },
            "TargetHealth": {
                "State": "healthy",
            },
        },
        {
            "HealthCheckPort": "22",
            "Target": {
                "Id": "i-234567",
                "Port": 22,
            },
            "TargetHealth": {
                "State": "unused",
            },
        },
    ]

    def test_full_login_nodes_status(self, mocker):
        mocker.patch("pcluster.aws.elb.ElbClient.__init__", return_value=None)
        mocker.patch(
            "pcluster.aws.elb.ElbClient.list_load_balancers",
            return_value=[self.dummy_load_balancer_1, self.dummy_load_balancer_2, self.dummy_load_balancer_3],
        )
        mocker.patch("pcluster.aws.elb.ElbClient.describe_tags", return_value=self.dummy_tags_description)
        mocker.patch("pcluster.aws.elb.ElbClient.describe_target_groups", return_value=self.dummy_target_groups)
        mocker.patch("pcluster.aws.elb.ElbClient.describe_target_health", return_value=self.dummy_targets_health)

        login_nodes_status = LoginNodesStatus(self.dummy_stack_name)
        login_nodes_status.retrieve_data([self.dummy_pool_name_1, self.dummy_pool_name_2])

        pool_1_status = login_nodes_status.get_pool_status_dict().get(self.dummy_pool_name_1)
        pool_2_status = login_nodes_status.get_pool_status_dict().get(self.dummy_pool_name_2)

        assert_that(login_nodes_status.get_login_nodes_pool_available()).is_true()

        assert_that(pool_1_status.get_status()).is_equal_to(LoginNodesPoolState.ACTIVE)
        assert_that(pool_2_status.get_status()).is_equal_to(LoginNodesPoolState.ACTIVE)

        assert_that(pool_1_status.get_address()).is_equal_to(self.dummy_dns_name_1)
        assert_that(pool_2_status.get_address()).is_equal_to(self.dummy_dns_name_2)

        assert_that(pool_1_status.get_scheme()).is_equal_to(self.dummy_scheme_1)
        assert_that(pool_2_status.get_scheme()).is_equal_to(self.dummy_scheme_2)

        assert_that(pool_1_status.get_healthy_nodes()).is_equal_to(2)
        assert_that(pool_2_status.get_healthy_nodes()).is_equal_to(2)

        assert_that(pool_1_status.get_unhealthy_nodes()).is_equal_to(1)
        assert_that(pool_2_status.get_unhealthy_nodes()).is_equal_to(1)

        assert_that(login_nodes_status.get_healthy_nodes()).is_equal_to(4)
        assert_that(login_nodes_status.get_unhealthy_nodes()).is_equal_to(2)

        string_representation = str(login_nodes_status)
        assert_that(string_representation).is_equal_to(
            f'("status": "{LoginNodesPoolState.ACTIVE}", "address": "{self.dummy_dns_name_1}", '
            f'"scheme": "{self.dummy_scheme_1}", "healthy_nodes": "2", "unhealthy_nodes": "1"),'
            f'("status": "{LoginNodesPoolState.ACTIVE}", "address": "{self.dummy_dns_name_2}", '
            f'"scheme": "{self.dummy_scheme_2}", "healthy_nodes": "2", "unhealthy_nodes": "1"),'
        )

    def test_retrieve_data_no_called(self):
        login_nodes_status = LoginNodesStatus(self.dummy_stack_name)
        assert_that(login_nodes_status.get_login_nodes_pool_available()).is_false()

    def test_no_load_balancers_available(self, mocker):
        mocker.patch("pcluster.aws.elb.ElbClient.__init__", return_value=None)
        mocker.patch("pcluster.aws.elb.ElbClient.list_load_balancers", return_value=[])
        login_nodes_status = LoginNodesStatus(self.dummy_stack_name)
        login_nodes_status.retrieve_data([self.dummy_pool_name_1, self.dummy_pool_name_2])
        assert_that(login_nodes_status.get_login_nodes_pool_available()).is_false()

    def test_wrong_load_balancer_available(self, mocker):
        mocker.patch("pcluster.aws.elb.ElbClient.__init__", return_value=None)
        mocker.patch("pcluster.aws.elb.ElbClient.list_load_balancers", return_value=[self.dummy_load_balancer_2])
        dummy_tags_description = [
            {
                "ResourceArn": "another_dummy_load_balancer_arn",
                "Tags": [
                    {
                        "Key": self.dummy_load_balancer_arn_2,
                        "Value": "pcluster-name-2",
                    },
                ],
            },
        ]
        mocker.patch("pcluster.aws.elb.ElbClient.describe_tags", return_value=dummy_tags_description)
        login_nodes_status = LoginNodesStatus(self.dummy_stack_name)
        login_nodes_status.retrieve_data([self.dummy_pool_name_1, self.dummy_pool_name_2])
        assert_that(login_nodes_status.get_login_nodes_pool_available()).is_false()

    def test_target_group_arn_not_available(self, mocker):
        mocker.patch("pcluster.aws.elb.ElbClient.__init__", return_value=None)
        mocker.patch(
            "pcluster.aws.elb.ElbClient.list_load_balancers",
            return_value=[self.dummy_load_balancer_1, self.dummy_load_balancer_2, self.dummy_load_balancer_3],
        )
        mocker.patch("pcluster.aws.elb.ElbClient.describe_tags", return_value=self.dummy_tags_description)
        mocker.patch(
            "pcluster.aws.elb.ElbClient.describe_target_groups", side_effect=Exception("Target Group Not Available")
        )
        login_nodes_status = LoginNodesStatus(self.dummy_stack_name)
        login_nodes_status.retrieve_data([self.dummy_pool_name_1, self.dummy_pool_name_2])
        assert_that(login_nodes_status.get_login_nodes_pool_available()).is_true()
        assert_that(login_nodes_status.get_healthy_nodes()).is_equal_to(0)
        assert_that(login_nodes_status.get_unhealthy_nodes()).is_equal_to(0)

    def test_target_group_health_not_available(self, mocker):
        mocker.patch("pcluster.aws.elb.ElbClient.__init__", return_value=None)
        mocker.patch(
            "pcluster.aws.elb.ElbClient.list_load_balancers",
            return_value=[self.dummy_load_balancer_1, self.dummy_load_balancer_2],
        )
        mocker.patch("pcluster.aws.elb.ElbClient.describe_tags", return_value=self.dummy_tags_description)
        mocker.patch("pcluster.aws.elb.ElbClient.describe_target_groups", return_value=self.dummy_target_groups)
        mocker.patch(
            "pcluster.aws.elb.ElbClient.describe_target_health", side_effect=Exception("Target Group Not Available")
        )
        login_nodes_status = LoginNodesStatus(self.dummy_stack_name)
        login_nodes_status.retrieve_data([self.dummy_pool_name_1, self.dummy_pool_name_2])
        assert_that(login_nodes_status.get_login_nodes_pool_available()).is_true()
        assert_that(login_nodes_status.get_healthy_nodes()).is_equal_to(0)
        assert_that(login_nodes_status.get_unhealthy_nodes()).is_equal_to(0)

    @pytest.mark.parametrize(
        "load_balancer_status, expected_status",
        [
            ("active", LoginNodesPoolState.ACTIVE),
            ("provisioning", LoginNodesPoolState.PENDING),
            ("active_impaired", LoginNodesPoolState.FAILED),
            ("failed", LoginNodesPoolState.FAILED),
        ],
    )
    def test_login_nodes_pool_state(self, mocker, load_balancer_status, expected_status):
        mocker.patch("pcluster.aws.elb.ElbClient.__init__", return_value=None)
        dummy_load_balancers = [
            {
                "LoadBalancerArn": self.dummy_load_balancer_arn_1,
                "DNSName": self.dummy_dns_name_1,
                "LoadBalancerName": "dummy-load-balancer-1",
                "Scheme": self.dummy_scheme_1,
                "State": {"Code": load_balancer_status},
            },
            {
                "LoadBalancerArn": self.dummy_load_balancer_arn_2,
                "DNSName": self.dummy_dns_name_2,
                "LoadBalancerName": "dummy-load-balancer-2",
                "Scheme": self.dummy_scheme_2,
                "State": {"Code": load_balancer_status},
            },
        ]
        mocker.patch(
            "pcluster.aws.elb.ElbClient.list_load_balancers",
            return_value=dummy_load_balancers,
        )
        mocker.patch("pcluster.aws.elb.ElbClient.describe_tags", return_value=self.dummy_tags_description)
        mocker.patch("pcluster.aws.elb.ElbClient.describe_target_groups", return_value=self.dummy_target_groups)
        mocker.patch("pcluster.aws.elb.ElbClient.describe_target_health", return_value=self.dummy_targets_health)
        login_nodes_status = LoginNodesStatus(self.dummy_stack_name)
        login_nodes_status.retrieve_data([self.dummy_pool_name_1, self.dummy_pool_name_2])

        pool_1_status = login_nodes_status.get_pool_status_dict().get(self.dummy_pool_name_1)
        pool_2_status = login_nodes_status.get_pool_status_dict().get(self.dummy_pool_name_2)

        assert_that(pool_1_status.get_pool_available()).is_true()
        assert_that(pool_2_status.get_pool_available()).is_true()

        assert_that(pool_1_status.get_status()).is_equal_to(expected_status)
        assert_that(pool_2_status.get_status()).is_equal_to(expected_status)
