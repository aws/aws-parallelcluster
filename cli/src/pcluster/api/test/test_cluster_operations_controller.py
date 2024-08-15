# coding: utf-8

from __future__ import absolute_import
import unittest

from flask import json
from six import BytesIO

from pcluster.api.models.bad_request_exception_response_content import BadRequestExceptionResponseContent  # noqa: E501
from pcluster.api.models.cluster_status_filtering_option import ClusterStatusFilteringOption  # noqa: E501
from pcluster.api.models.conflict_exception_response_content import ConflictExceptionResponseContent  # noqa: E501
from pcluster.api.models.create_cluster_bad_request_exception_response_content import CreateClusterBadRequestExceptionResponseContent  # noqa: E501
from pcluster.api.models.create_cluster_request_content import CreateClusterRequestContent  # noqa: E501
from pcluster.api.models.create_cluster_response_content import CreateClusterResponseContent  # noqa: E501
from pcluster.api.models.delete_cluster_response_content import DeleteClusterResponseContent  # noqa: E501
from pcluster.api.models.describe_cluster_response_content import DescribeClusterResponseContent  # noqa: E501
from pcluster.api.models.dryrun_operation_exception_response_content import DryrunOperationExceptionResponseContent  # noqa: E501
from pcluster.api.models.internal_service_exception_response_content import InternalServiceExceptionResponseContent  # noqa: E501
from pcluster.api.models.limit_exceeded_exception_response_content import LimitExceededExceptionResponseContent  # noqa: E501
from pcluster.api.models.list_clusters_response_content import ListClustersResponseContent  # noqa: E501
from pcluster.api.models.not_found_exception_response_content import NotFoundExceptionResponseContent  # noqa: E501
from pcluster.api.models.unauthorized_client_error_response_content import UnauthorizedClientErrorResponseContent  # noqa: E501
from pcluster.api.models.update_cluster_bad_request_exception_response_content import UpdateClusterBadRequestExceptionResponseContent  # noqa: E501
from pcluster.api.models.update_cluster_request_content import UpdateClusterRequestContent  # noqa: E501
from pcluster.api.models.update_cluster_response_content import UpdateClusterResponseContent  # noqa: E501
from pcluster.api.models.validation_level import ValidationLevel  # noqa: E501
from pcluster.api.test import BaseTestCase


class TestClusterOperationsController(BaseTestCase):
    """ClusterOperationsController integration test stubs"""

    def test_create_cluster(self):
        """Test case for create_cluster

        
        """
        create_cluster_request_content = {
  "clusterName" : "clusterName",
  "clusterConfiguration" : "clusterConfiguration"
}
        query_string = [('region', 'region_example'),
                        ('suppressValidators', ['suppress_validators_example']),
                        ('validationFailureLevel', pcluster.api.ValidationLevel()),
                        ('dryrun', True),
                        ('rollbackOnFailure', True)]
        headers = { 
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'aws.auth.sigv4': 'special-key',
        }
        response = self.client.open(
            '/v3/clusters',
            method='POST',
            headers=headers,
            data=json.dumps(create_cluster_request_content),
            content_type='application/json',
            query_string=query_string)
        self.assert200(response,
                       'Response body is : ' + response.data.decode('utf-8'))

    def test_delete_cluster(self):
        """Test case for delete_cluster

        
        """
        query_string = [('region', 'region_example')]
        headers = { 
            'Accept': 'application/json',
            'aws.auth.sigv4': 'special-key',
        }
        response = self.client.open(
            '/v3/clusters/{cluster_name}'.format(cluster_name='cluster_name_example'),
            method='DELETE',
            headers=headers,
            query_string=query_string)
        self.assert200(response,
                       'Response body is : ' + response.data.decode('utf-8'))

    def test_describe_cluster(self):
        """Test case for describe_cluster

        
        """
        query_string = [('region', 'region_example')]
        headers = { 
            'Accept': 'application/json',
            'aws.auth.sigv4': 'special-key',
        }
        response = self.client.open(
            '/v3/clusters/{cluster_name}'.format(cluster_name='cluster_name_example'),
            method='GET',
            headers=headers,
            query_string=query_string)
        self.assert200(response,
                       'Response body is : ' + response.data.decode('utf-8'))

    def test_list_clusters(self):
        """Test case for list_clusters

        
        """
        query_string = [('region', 'region_example'),
                        ('nextToken', 'next_token_example'),
                        ('clusterStatus', [pcluster.api.ClusterStatusFilteringOption()])]
        headers = { 
            'Accept': 'application/json',
            'aws.auth.sigv4': 'special-key',
        }
        response = self.client.open(
            '/v3/clusters',
            method='GET',
            headers=headers,
            query_string=query_string)
        self.assert200(response,
                       'Response body is : ' + response.data.decode('utf-8'))

    def test_update_cluster(self):
        """Test case for update_cluster

        
        """
        update_cluster_request_content = {
  "clusterConfiguration" : "clusterConfiguration"
}
        query_string = [('suppressValidators', ['suppress_validators_example']),
                        ('validationFailureLevel', pcluster.api.ValidationLevel()),
                        ('region', 'region_example'),
                        ('dryrun', True),
                        ('forceUpdate', True)]
        headers = { 
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'aws.auth.sigv4': 'special-key',
        }
        response = self.client.open(
            '/v3/clusters/{cluster_name}'.format(cluster_name='cluster_name_example'),
            method='PUT',
            headers=headers,
            data=json.dumps(update_cluster_request_content),
            content_type='application/json',
            query_string=query_string)
        self.assert200(response,
                       'Response body is : ' + response.data.decode('utf-8'))


if __name__ == '__main__':
    unittest.main()
