# coding: utf-8

from __future__ import absolute_import
import unittest

from flask import json
from six import BytesIO

from pcluster.api.models.bad_request_exception_response_content import BadRequestExceptionResponseContent  # noqa: E501
from pcluster.api.models.describe_compute_fleet_response_content import DescribeComputeFleetResponseContent  # noqa: E501
from pcluster.api.models.internal_service_exception_response_content import InternalServiceExceptionResponseContent  # noqa: E501
from pcluster.api.models.limit_exceeded_exception_response_content import LimitExceededExceptionResponseContent  # noqa: E501
from pcluster.api.models.not_found_exception_response_content import NotFoundExceptionResponseContent  # noqa: E501
from pcluster.api.models.unauthorized_client_error_response_content import UnauthorizedClientErrorResponseContent  # noqa: E501
from pcluster.api.models.update_compute_fleet_request_content import UpdateComputeFleetRequestContent  # noqa: E501
from pcluster.api.models.update_compute_fleet_response_content import UpdateComputeFleetResponseContent  # noqa: E501
from pcluster.api.test import BaseTestCase


class TestClusterComputeFleetController(BaseTestCase):
    """ClusterComputeFleetController integration test stubs"""

    def test_describe_compute_fleet(self):
        """Test case for describe_compute_fleet

        
        """
        query_string = [('region', 'region_example')]
        headers = { 
            'Accept': 'application/json',
            'aws.auth.sigv4': 'special-key',
        }
        response = self.client.open(
            '/v3/clusters/{cluster_name}/computefleet'.format(cluster_name='cluster_name_example'),
            method='GET',
            headers=headers,
            query_string=query_string)
        self.assert200(response,
                       'Response body is : ' + response.data.decode('utf-8'))

    def test_update_compute_fleet(self):
        """Test case for update_compute_fleet

        
        """
        update_compute_fleet_request_content = { }
        query_string = [('region', 'region_example')]
        headers = { 
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'aws.auth.sigv4': 'special-key',
        }
        response = self.client.open(
            '/v3/clusters/{cluster_name}/computefleet'.format(cluster_name='cluster_name_example'),
            method='PATCH',
            headers=headers,
            data=json.dumps(update_compute_fleet_request_content),
            content_type='application/json',
            query_string=query_string)
        self.assert200(response,
                       'Response body is : ' + response.data.decode('utf-8'))


if __name__ == '__main__':
    unittest.main()
