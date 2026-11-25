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

    @staticmethod
    def _mock_tagging_api(mocker, arn_by_pool):
        """Mock the resource groups tagging api so it returns the NLB ARN for each pool."""
        mocker.patch(
            "pcluster.aws.resource_groups_tagging_api.ResourceGroupsTaggingApiClient.__init__", return_value=None
        )

        def get_resources(tag_filters, resource_type_filters=None):
            pool_name = tag_filters.get("parallelcluster:login-nodes-pool")
            arn = arn_by_pool.get(pool_name)
            return [arn] if arn else []

        mocker.patch(
            "pcluster.aws.resource_groups_tagging_api.ResourceGroupsTaggingApiClient.get_resources",
            side_effect=get_resources,
        )

    @staticmethod
    def _mock_describe_load_balancer(mocker, load_balancers_by_arn):
        mocker.patch("pcluster.aws.elb.ElbClient.__init__", return_value=None)

        def describe_load_balancer(arn):
            return load_balancers_by_arn.get(arn)

        mocker.patch(
            "pcluster.aws.elb.ElbClient.describe_load_balancer",
            side_effect=describe_load_balancer,
        )

    def test_full_login_nodes_status(self, mocker):
        self._mock_tagging_api(
            mocker,
            {
                self.dummy_pool_name_1: self.dummy_load_balancer_arn_1,
                self.dummy_pool_name_2: self.dummy_load_balancer_arn_2,
            },
        )
        self._mock_describe_load_balancer(
            mocker,
            {
                self.dummy_load_balancer_arn_1: self.dummy_load_balancer_1,
                self.dummy_load_balancer_arn_2: self.dummy_load_balancer_2,
            },
        )
        mocker.patch("pcluster.aws.elb.ElbClient.describe_target_groups", return_value=self.dummy_target_groups)
        mocker.patch("pcluster.aws.elb.ElbClient.describe_target_health", return_value=self.dummy_targets_health)

        pool_names = [self.dummy_pool_name_1, self.dummy_pool_name_2]
        dns_names = [self.dummy_dns_name_1, self.dummy_dns_name_2]
        schemes = [self.dummy_scheme_1, self.dummy_scheme_2]

        login_nodes_status = LoginNodesStatus(self.dummy_stack_name)
        login_nodes_status.retrieve_data(pool_names)

        assert_that(login_nodes_status.get_login_nodes_pool_available()).is_true()
        assert_that(login_nodes_status.get_healthy_nodes()).is_equal_to(4)
        assert_that(login_nodes_status.get_unhealthy_nodes()).is_equal_to(2)

        string_representation = str(login_nodes_status)
        assert_that(string_representation).is_equal_to(
            f'("status": "{LoginNodesPoolState.ACTIVE}", "address": "{self.dummy_dns_name_1}", '
            f'"scheme": "{self.dummy_scheme_1}", "healthy_nodes": "2", "unhealthy_nodes": "1"),'
            f'("status": "{LoginNodesPoolState.ACTIVE}", "address": "{self.dummy_dns_name_2}", '
            f'"scheme": "{self.dummy_scheme_2}", "healthy_nodes": "2", "unhealthy_nodes": "1"),'
        )

        for pool_name, dns_name, scheme in zip(pool_names, dns_names, schemes):
            pool_status = login_nodes_status.get_pool_status_dict().get(pool_name)

            assert_that(pool_status.get_status()).is_equal_to(LoginNodesPoolState.ACTIVE)
            assert_that(pool_status.get_address()).is_equal_to(dns_name)
            assert_that(pool_status.get_scheme()).is_equal_to(scheme)
            assert_that(pool_status.get_healthy_nodes()).is_equal_to(2)
            assert_that(pool_status.get_unhealthy_nodes()).is_equal_to(1)
            assert_that(login_nodes_status.get_healthy_nodes(pool_name)).is_equal_to(2)
            assert_that(login_nodes_status.get_unhealthy_nodes(pool_name)).is_equal_to(1)

    def test_retrieve_data_no_called(self):
        login_nodes_status = LoginNodesStatus(self.dummy_stack_name)
        assert_that(login_nodes_status.get_login_nodes_pool_available()).is_false()

    def test_no_load_balancers_available(self, mocker):
        # The tagging API returns no ARNs for any pool (e.g. cluster not yet created or already deleted).
        self._mock_tagging_api(mocker, {})
        self._mock_describe_load_balancer(mocker, {})
        login_nodes_status = LoginNodesStatus(self.dummy_stack_name)
        login_nodes_status.retrieve_data([self.dummy_pool_name_1, self.dummy_pool_name_2])
        assert_that(login_nodes_status.get_login_nodes_pool_available()).is_false()

    def test_target_group_arn_not_available(self, mocker):
        self._mock_tagging_api(
            mocker,
            {
                self.dummy_pool_name_1: self.dummy_load_balancer_arn_1,
                self.dummy_pool_name_2: self.dummy_load_balancer_arn_2,
            },
        )
        self._mock_describe_load_balancer(
            mocker,
            {
                self.dummy_load_balancer_arn_1: self.dummy_load_balancer_1,
                self.dummy_load_balancer_arn_2: self.dummy_load_balancer_2,
            },
        )
        mocker.patch(
            "pcluster.aws.elb.ElbClient.describe_target_groups", side_effect=Exception("Target Group Not Available")
        )
        login_nodes_status = LoginNodesStatus(self.dummy_stack_name)
        login_nodes_status.retrieve_data([self.dummy_pool_name_1, self.dummy_pool_name_2])
        assert_that(login_nodes_status.get_login_nodes_pool_available()).is_true()
        assert_that(login_nodes_status.get_healthy_nodes()).is_equal_to(0)
        assert_that(login_nodes_status.get_unhealthy_nodes()).is_equal_to(0)

    def test_target_group_health_not_available(self, mocker):
        self._mock_tagging_api(
            mocker,
            {
                self.dummy_pool_name_1: self.dummy_load_balancer_arn_1,
                self.dummy_pool_name_2: self.dummy_load_balancer_arn_2,
            },
        )
        self._mock_describe_load_balancer(
            mocker,
            {
                self.dummy_load_balancer_arn_1: self.dummy_load_balancer_1,
                self.dummy_load_balancer_arn_2: self.dummy_load_balancer_2,
            },
        )
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
        dummy_load_balancer_1 = {**self.dummy_load_balancer_1, "State": {"Code": load_balancer_status}}
        dummy_load_balancer_2 = {**self.dummy_load_balancer_2, "State": {"Code": load_balancer_status}}

        self._mock_tagging_api(
            mocker,
            {
                self.dummy_pool_name_1: self.dummy_load_balancer_arn_1,
                self.dummy_pool_name_2: self.dummy_load_balancer_arn_2,
            },
        )
        self._mock_describe_load_balancer(
            mocker,
            {
                self.dummy_load_balancer_arn_1: dummy_load_balancer_1,
                self.dummy_load_balancer_arn_2: dummy_load_balancer_2,
            },
        )
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

    def test_tagging_api_called_with_expected_filters(self, mocker):
        """Verify the tag filters and resource type filter passed to the Resource Groups Tagging API."""
        mocker.patch(
            "pcluster.aws.resource_groups_tagging_api.ResourceGroupsTaggingApiClient.__init__", return_value=None
        )
        get_resources_mock = mocker.patch(
            "pcluster.aws.resource_groups_tagging_api.ResourceGroupsTaggingApiClient.get_resources",
            return_value=[],
        )
        self._mock_describe_load_balancer(mocker, {})

        LoginNodesStatus(self.dummy_stack_name).retrieve_data([self.dummy_pool_name_1])

        get_resources_mock.assert_called_once_with(
            tag_filters={
                "parallelcluster:cluster-name": self.dummy_stack_name,
                "parallelcluster:login-nodes-pool": self.dummy_pool_name_1,
            },
            resource_type_filters=["elasticloadbalancing:loadbalancer"],
        )

    def test_load_balancer_deleted_between_tag_lookup_and_describe(self, mocker):
        """Race where the NLB is deleted between the tagging lookup and describe_load_balancer.

        The tagging API returns an ARN, but the subsequent describe_load_balancer returns None because the NLB
        no longer exists. The pool should still be considered available (ARN was found) but without status/DNS info.
        """
        self._mock_tagging_api(
            mocker,
            {self.dummy_pool_name_1: self.dummy_load_balancer_arn_1},
        )
        # describe_load_balancer returns None for this ARN, simulating a concurrent deletion.
        self._mock_describe_load_balancer(mocker, {})
        mocker.patch("pcluster.aws.elb.ElbClient.describe_target_groups", return_value=self.dummy_target_groups)
        mocker.patch("pcluster.aws.elb.ElbClient.describe_target_health", return_value=self.dummy_targets_health)

        login_nodes_status = LoginNodesStatus(self.dummy_stack_name)
        login_nodes_status.retrieve_data([self.dummy_pool_name_1])

        pool_status = login_nodes_status.get_pool_status_dict().get(self.dummy_pool_name_1)
        assert_that(pool_status.get_pool_available()).is_true()
        assert_that(pool_status.get_status()).is_none()
        assert_that(pool_status.get_address()).is_none()
        assert_that(pool_status.get_scheme()).is_none()
