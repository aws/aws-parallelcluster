#  Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
#  with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
#  or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
#  OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
#  limitations under the License.
import pytest
from assertpy import assert_that, soft_assertions

from pcluster.api.models import NodeType


def cfn_describe_instances_mock_response(
    instance_type="t2.micro", queue_name=None, node_type="HeadNode", cluster_name="clustername"
):
    instance_data = {
        "InstanceId": "i-0a9342a0000000000",
        "InstanceType": instance_type,
        "KeyName": "jenkinsjun",
        "LaunchTime": "2021-04-30T00:00:00+00:00",
        "PrivateIpAddress": "10.0.0.79",
        "PublicIpAddress": "1.2.3.4",
        "State": {"Code": 16, "Name": "running"},
        "Tags": [
            {"Key": "parallelcluster:version", "Value": "3.0.0"},
            {"Key": "parallelcluster:node-type", "Value": node_type},
            {"Key": "parallelcluster:cluster-name", "Value": cluster_name},
        ],
    }
    if queue_name:
        instance_data["Tags"].append({"Key": "QueueName", "Value": queue_name})

    return instance_data


def describe_cluster_instances_mock_response(instances):
    result = []
    for instance in instances:
        node_type = instance.get("node_type") or "HEAD"
        if node_type:
            node_type = node_type.upper()
        response = {
            "instanceId": "i-0a9342a0000000000",
            "instanceType": "t2.micro",
            "launchTime": "2021-04-30T00:00:00+00:00",
            "nodeType": node_type,
            "privateIpAddress": "10.0.0.79",
            "publicIpAddress": "1.2.3.4",
            "state": "running",
        }
        if node_type == "COMPUTE":
            response["queueName"] = instance.get("queue_name")
        result.append(response)
    return {"instances": result}


class TestDescribeClusterInstances:
    url = "/v3/clusters/{cluster_name}/instances"
    method = "GET"

    def _send_test_request(
        self, client, cluster_name="clustername", region="us-east-1", next_token=None, node_type=None, queue_name=None
    ):
        query_string = []
        if region:
            query_string.append(("region", region))
        if next_token:
            query_string.append(("nextToken", next_token))
        if node_type:
            query_string.append(("nodeType", node_type))
        if queue_name:
            query_string.append(("queueName", queue_name))

        headers = {
            "Accept": "application/json",
        }
        return client.open(
            self.url.format(cluster_name=cluster_name), method=self.method, headers=headers, query_string=query_string
        )

    @pytest.mark.parametrize(
        "instances, params, next_token",
        [
            ([], {}, None),
            (
                [
                    {},
                    {"node_type": "Compute", "queue_name": "queuename"},
                ],
                {},
                None,
            ),
            (
                [
                    {},
                    {"node_type": "Compute", "queue_name": "queuename"},
                    {"node_type": "Compute", "queue_name": "queuename"},
                ],
                {},
                "fakenexttoken=======",
            ),
        ],
        ids=["empty", "all", "next token"],
    )
    def test_successful_request(self, mocker, client, instances, params, next_token):
        describe_instances_response = []
        for instance in instances:
            describe_instances_response.append(cfn_describe_instances_mock_response(**instance))
        expected_response = describe_cluster_instances_mock_response(instances)
        if next_token:
            expected_response["nextToken"] = next_token
        mocker.patch(
            "pcluster.aws.ec2.Ec2Client.describe_instances", return_value=(describe_instances_response, next_token)
        )
        response = self._send_test_request(client, **params)
        with soft_assertions():
            assert_that(response.status_code).is_equal_to(200)
            assert_that(response.get_json()).is_equal_to(expected_response)

    @pytest.mark.parametrize(
        "cluster_name, node_type, queue_name",
        [
            ("clustername", None, None),
            ("clustername", NodeType.HEAD, None),
            ("clustername", NodeType.COMPUTE, None),
            ("clustername", None, "queuename"),
        ],
        ids=["all instances", "head only", "compute only", "queuename only"],
    )
    def test_filters(self, mocker, client, cluster_name, node_type, queue_name):
        describe_instances_mock = mocker.patch(
            "pcluster.aws.ec2.Ec2Client.describe_instances",
            return_value=([cfn_describe_instances_mock_response()], ""),
        )
        response = self._send_test_request(
            client, cluster_name=cluster_name, node_type=node_type, queue_name=queue_name
        )
        with soft_assertions():
            assert_that(response.status_code).is_equal_to(200)
            actual_filters = describe_instances_mock.call_args_list[0][0][0]
            actual_filters_dict = {}
            for filter in actual_filters:
                actual_filters_dict[filter["Name"]] = filter["Values"][0]
            assert_that(actual_filters_dict.get("tag:parallelcluster:cluster-name")).is_equal_to(cluster_name)
            if node_type:
                if node_type == NodeType.HEAD:
                    expected_value = "HeadNode"
                else:
                    expected_value = "Compute"
            else:
                expected_value = None
            assert_that(actual_filters_dict.get("tag:parallelcluster:node-type")).is_equal_to(expected_value)
            assert_that(actual_filters_dict.get("tag:QueueName")).is_equal_to(queue_name)

    @pytest.mark.parametrize(
        "params, expected_response",
        [
            (
                {"node_type": "wrong_node_type"},
                {"message": "Bad Request: 'wrong_node_type' is not one of ['HEAD', 'COMPUTE']"},
            ),
            (
                {"region": "eu-west-"},
                {"message": "Bad Request: invalid or unsupported region 'eu-west-'"},
            ),
            (
                {"region": None},
                {"message": "Bad Request: region needs to be set"},
            ),
        ],
    )
    def test_malformed_request(self, client, params, expected_response):
        response = self._send_test_request(client, **params)
        with soft_assertions():
            assert_that(response.status_code).is_equal_to(400)
            assert_that(response.get_json()).is_equal_to(expected_response)
