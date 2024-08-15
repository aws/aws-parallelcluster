# coding: utf-8

from __future__ import absolute_import
import unittest

from flask import json
from six import BytesIO

from pcluster.api.models.bad_request_exception_response_content import BadRequestExceptionResponseContent  # noqa: E501
from pcluster.api.models.get_cluster_log_events_response_content import GetClusterLogEventsResponseContent  # noqa: E501
from pcluster.api.models.get_cluster_stack_events_response_content import GetClusterStackEventsResponseContent  # noqa: E501
from pcluster.api.models.internal_service_exception_response_content import InternalServiceExceptionResponseContent  # noqa: E501
from pcluster.api.models.limit_exceeded_exception_response_content import LimitExceededExceptionResponseContent  # noqa: E501
from pcluster.api.models.list_cluster_log_streams_response_content import ListClusterLogStreamsResponseContent  # noqa: E501
from pcluster.api.models.not_found_exception_response_content import NotFoundExceptionResponseContent  # noqa: E501
from pcluster.api.models.unauthorized_client_error_response_content import UnauthorizedClientErrorResponseContent  # noqa: E501
from pcluster.api.test import BaseTestCase


class TestClusterLogsController(BaseTestCase):
    """ClusterLogsController integration test stubs"""

    def test_get_cluster_log_events(self):
        """Test case for get_cluster_log_events

        
        """
        query_string = [('region', 'region_example'),
                        ('nextToken', 'next_token_example'),
                        ('startFromHead', True),
                        ('limit', 56),
                        ('startTime', '2013-10-20T19:20:30+01:00'),
                        ('endTime', '2013-10-20T19:20:30+01:00')]
        headers = { 
            'Accept': 'application/json',
            'aws.auth.sigv4': 'special-key',
        }
        response = self.client.open(
            '/v3/clusters/{cluster_name}/logstreams/{log_stream_name}'.format(cluster_name='cluster_name_example', log_stream_name='log_stream_name_example'),
            method='GET',
            headers=headers,
            query_string=query_string)
        self.assert200(response,
                       'Response body is : ' + response.data.decode('utf-8'))

    def test_get_cluster_stack_events(self):
        """Test case for get_cluster_stack_events

        
        """
        query_string = [('region', 'region_example'),
                        ('nextToken', 'next_token_example')]
        headers = { 
            'Accept': 'application/json',
            'aws.auth.sigv4': 'special-key',
        }
        response = self.client.open(
            '/v3/clusters/{cluster_name}/stackevents'.format(cluster_name='cluster_name_example'),
            method='GET',
            headers=headers,
            query_string=query_string)
        self.assert200(response,
                       'Response body is : ' + response.data.decode('utf-8'))

    def test_list_cluster_log_streams(self):
        """Test case for list_cluster_log_streams

        
        """
        query_string = [('region', 'region_example'),
                        ('filters', ['filters_example']),
                        ('nextToken', 'next_token_example')]
        headers = { 
            'Accept': 'application/json',
            'aws.auth.sigv4': 'special-key',
        }
        response = self.client.open(
            '/v3/clusters/{cluster_name}/logstreams'.format(cluster_name='cluster_name_example'),
            method='GET',
            headers=headers,
            query_string=query_string)
        self.assert200(response,
                       'Response body is : ' + response.data.decode('utf-8'))


if __name__ == '__main__':
    unittest.main()
