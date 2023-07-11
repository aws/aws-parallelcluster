import pytest
from assertpy import assert_that

from pcluster.models.login_nodes_status import LoginNodesPoolState, LoginNodesStatus


class TestLoginNodesStatus:
    dummy_stack_name = "dummy_cluster_name"
    dummy_load_balancer_arn = "dummy_load_balancer_arn"
    dummy_load_balancer_arn_2 = "dummy_load_balancer_arn_2"
    dummy_scheme = "internet-facing"
    dummy_status = "active"
    dummy_dns_name = "dummy_dns_name"
    dummy_target_group_arn = "dummy_target_group_arn"

    dummy_load_balancers = {
        "LoadBalancerArn": dummy_load_balancer_arn,
        "DNSName": dummy_dns_name,
        "LoadBalancerName": "dummy-load-balancer",
        "Scheme": dummy_scheme,
        "State": {"Code": dummy_status},
    }
    dummy_load_balancer_2 = {
        "LoadBalancerArn": dummy_load_balancer_arn_2,
        "DNSName": "dummy_dns_name",
        "LoadBalancerName": "dummy-load-balancer-2",
        "Scheme": "internal",
        "State": {"Code": "provisioning"},
    }

    dummy_tags_description = [
        {
            "ResourceArn": dummy_load_balancer_arn,
            "Tags": [
                {
                    "Key": "parallelcluster:cluster-name",
                    "Value": dummy_stack_name,
                },
            ],
        },
        {
            "ResourceArn": "another_dummy_load_balancer_arn",
            "Tags": [
                {
                    "Key": dummy_load_balancer_arn_2,
                    "Value": "pcluster-name-2",
                },
            ],
        },
    ]

    dummy_target_groups = [
        {
            "TargetGroupArn": dummy_target_group_arn,
            "HealthCheckPort": "22",
            "LoadBalancerArns": [dummy_load_balancer_arn],
        }
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
            return_value=[self.dummy_load_balancer_2, self.dummy_load_balancers],
        )
        mocker.patch("pcluster.aws.elb.ElbClient.describe_tags", return_value=self.dummy_tags_description)
        mocker.patch("pcluster.aws.elb.ElbClient.describe_target_groups", return_value=self.dummy_target_groups)
        mocker.patch("pcluster.aws.elb.ElbClient.describe_target_health", return_value=self.dummy_targets_health)
        login_nodes_status = LoginNodesStatus(self.dummy_stack_name)
        login_nodes_status.retrieve_data()
        assert_that(login_nodes_status.get_login_nodes_pool_available()).is_true()
        assert_that(login_nodes_status.get_status()).is_equal_to(LoginNodesPoolState.ACTIVE)
        assert_that(login_nodes_status.get_address()).is_equal_to(self.dummy_dns_name)
        assert_that(login_nodes_status.get_scheme()).is_equal_to(self.dummy_scheme)
        assert_that(login_nodes_status.get_healthy_nodes()).is_equal_to(2)
        assert_that(login_nodes_status.get_unhealthy_nodes()).is_equal_to(1)
        string_representation = str(login_nodes_status)
        assert_that(string_representation).is_equal_to(
            f'("status": "{LoginNodesPoolState.ACTIVE}", "address": "{self.dummy_dns_name}", '
            f'"scheme": "{self.dummy_scheme}", "healthyNodes": "2", "unhealthy_nodes": "1")'
        )

    def test_retrieve_data_no_called(self):
        login_nodes_status = LoginNodesStatus(self.dummy_stack_name)
        assert_that(login_nodes_status.get_login_nodes_pool_available()).is_false()

    def test_no_load_balancers_available(self, mocker):
        mocker.patch("pcluster.aws.elb.ElbClient.__init__", return_value=None)
        mocker.patch("pcluster.aws.elb.ElbClient.list_load_balancers", return_value=[])
        login_nodes_status = LoginNodesStatus(self.dummy_stack_name)
        login_nodes_status.retrieve_data()
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
        login_nodes_status.retrieve_data()
        assert_that(login_nodes_status.get_login_nodes_pool_available()).is_false()

    def test_target_group_arn_not_available(self, mocker):
        mocker.patch("pcluster.aws.elb.ElbClient.__init__", return_value=None)
        mocker.patch(
            "pcluster.aws.elb.ElbClient.list_load_balancers",
            return_value=[self.dummy_load_balancer_2, self.dummy_load_balancers],
        )
        mocker.patch("pcluster.aws.elb.ElbClient.describe_tags", return_value=self.dummy_tags_description)
        mocker.patch(
            "pcluster.aws.elb.ElbClient.describe_target_groups", side_effect=Exception("Target Group Not Available")
        )
        login_nodes_status = LoginNodesStatus(self.dummy_stack_name)
        login_nodes_status.retrieve_data()
        assert_that(login_nodes_status.get_login_nodes_pool_available()).is_true()
        assert_that(login_nodes_status.get_healthy_nodes()).is_none()
        assert_that(login_nodes_status.get_unhealthy_nodes()).is_none()

    def test_target_group_health_not_available(self, mocker):
        mocker.patch("pcluster.aws.elb.ElbClient.__init__", return_value=None)
        mocker.patch(
            "pcluster.aws.elb.ElbClient.list_load_balancers",
            return_value=[self.dummy_load_balancer_2, self.dummy_load_balancers],
        )
        mocker.patch("pcluster.aws.elb.ElbClient.describe_tags", return_value=self.dummy_tags_description)
        mocker.patch("pcluster.aws.elb.ElbClient.describe_target_groups", return_value=self.dummy_target_groups)
        mocker.patch(
            "pcluster.aws.elb.ElbClient.describe_target_health", side_effect=Exception("Target Group Not Available")
        )
        login_nodes_status = LoginNodesStatus(self.dummy_stack_name)
        login_nodes_status.retrieve_data()
        assert_that(login_nodes_status.get_login_nodes_pool_available()).is_true()
        assert_that(login_nodes_status.get_healthy_nodes()).is_none()
        assert_that(login_nodes_status.get_unhealthy_nodes()).is_none()

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
        dummy_load_balancers = {
            "LoadBalancerArn": self.dummy_load_balancer_arn,
            "DNSName": self.dummy_dns_name,
            "LoadBalancerName": "dummy-load-balancer",
            "Scheme": self.dummy_scheme,
            "State": {"Code": load_balancer_status},
        }
        mocker.patch(
            "pcluster.aws.elb.ElbClient.list_load_balancers",
            return_value=[self.dummy_load_balancer_2, dummy_load_balancers],
        )
        mocker.patch("pcluster.aws.elb.ElbClient.describe_tags", return_value=self.dummy_tags_description)
        mocker.patch("pcluster.aws.elb.ElbClient.describe_target_groups", return_value=self.dummy_target_groups)
        mocker.patch("pcluster.aws.elb.ElbClient.describe_target_health", return_value=self.dummy_targets_health)
        login_nodes_status = LoginNodesStatus(self.dummy_stack_name)
        login_nodes_status.retrieve_data()
        assert_that(login_nodes_status.get_login_nodes_pool_available()).is_true()
        assert_that(login_nodes_status.get_status()).is_equal_to(expected_status)
