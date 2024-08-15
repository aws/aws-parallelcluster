# coding: utf-8

from __future__ import absolute_import
import unittest

from flask import json
from six import BytesIO

from pcluster.api.models.bad_request_exception_response_content import BadRequestExceptionResponseContent  # noqa: E501
from pcluster.api.models.describe_cluster_instances_response_content import DescribeClusterInstancesResponseContent  # noqa: E501
from pcluster.api.models.internal_service_exception_response_content import InternalServiceExceptionResponseContent  # noqa: E501
from pcluster.api.models.limit_exceeded_exception_response_content import LimitExceededExceptionResponseContent  # noqa: E501
from pcluster.api.models.node_type import NodeType  # noqa: E501
from pcluster.api.models.not_found_exception_response_content import NotFoundExceptionResponseContent  # noqa: E501
from pcluster.api.models.unauthorized_client_error_response_content import UnauthorizedClientErrorResponseContent  # noqa: E501
from pcluster.api.test import BaseTestCase


class TestClusterInstancesController(BaseTestCase):
    """ClusterInstancesController integration test stubs"""

    def test_delete_cluster_instances(self):
        """Test case for delete_cluster_instances

        
        """
        query_string = [('region', 'region_example'),
                        ('force', True)]
        headers = { 
            'Accept': 'application/json',
            'aws.auth.sigv4': 'special-key',
        }
        response = self.client.open(
            '/v3/clusters/{cluster_name}/instances'.format(cluster_name='cluster_name_example'),
            method='DELETE',
            headers=headers,
            query_string=query_string)
        self.assert200(response,
                       'Response body is : ' + response.data.decode('utf-8'))

    def test_describe_cluster_instances(self):
        """Test case for describe_cluster_instances

        
        """
        query_string = [('region', 'region_example'),
                        ('nextToken', 'next_token_example'),
                        ('nodeType', pcluster.api.NodeType()),
                        ('queueName', 'queue_name_example')]
        headers = { 
            'Accept': 'application/json',
            'aws.auth.sigv4': 'special-key',
        }
        response = self.client.open(
            '/v3/clusters/{cluster_name}/instances'.format(cluster_name='cluster_name_example'),
            method='GET',
            headers=headers,
            query_string=query_string)
        self.assert200(response,
                       'Response body is : ' + response.data.decode('utf-8'))


if __name__ == '__main__':
    unittest.main()
