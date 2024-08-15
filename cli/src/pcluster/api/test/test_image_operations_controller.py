# coding: utf-8

from __future__ import absolute_import
import unittest

from flask import json
from six import BytesIO

from pcluster.api.models.bad_request_exception_response_content import BadRequestExceptionResponseContent  # noqa: E501
from pcluster.api.models.build_image_bad_request_exception_response_content import BuildImageBadRequestExceptionResponseContent  # noqa: E501
from pcluster.api.models.build_image_request_content import BuildImageRequestContent  # noqa: E501
from pcluster.api.models.build_image_response_content import BuildImageResponseContent  # noqa: E501
from pcluster.api.models.conflict_exception_response_content import ConflictExceptionResponseContent  # noqa: E501
from pcluster.api.models.delete_image_response_content import DeleteImageResponseContent  # noqa: E501
from pcluster.api.models.describe_image_response_content import DescribeImageResponseContent  # noqa: E501
from pcluster.api.models.dryrun_operation_exception_response_content import DryrunOperationExceptionResponseContent  # noqa: E501
from pcluster.api.models.image_status_filtering_option import ImageStatusFilteringOption  # noqa: E501
from pcluster.api.models.internal_service_exception_response_content import InternalServiceExceptionResponseContent  # noqa: E501
from pcluster.api.models.limit_exceeded_exception_response_content import LimitExceededExceptionResponseContent  # noqa: E501
from pcluster.api.models.list_images_response_content import ListImagesResponseContent  # noqa: E501
from pcluster.api.models.list_official_images_response_content import ListOfficialImagesResponseContent  # noqa: E501
from pcluster.api.models.not_found_exception_response_content import NotFoundExceptionResponseContent  # noqa: E501
from pcluster.api.models.unauthorized_client_error_response_content import UnauthorizedClientErrorResponseContent  # noqa: E501
from pcluster.api.models.validation_level import ValidationLevel  # noqa: E501
from pcluster.api.test import BaseTestCase


class TestImageOperationsController(BaseTestCase):
    """ImageOperationsController integration test stubs"""

    def test_build_image(self):
        """Test case for build_image

        
        """
        build_image_request_content = {
  "imageConfiguration" : "imageConfiguration",
  "imageId" : "imageId"
}
        query_string = [('suppressValidators', ['suppress_validators_example']),
                        ('validationFailureLevel', pcluster.api.ValidationLevel()),
                        ('dryrun', True),
                        ('rollbackOnFailure', True),
                        ('region', 'region_example')]
        headers = { 
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'aws.auth.sigv4': 'special-key',
        }
        response = self.client.open(
            '/v3/images/custom',
            method='POST',
            headers=headers,
            data=json.dumps(build_image_request_content),
            content_type='application/json',
            query_string=query_string)
        self.assert200(response,
                       'Response body is : ' + response.data.decode('utf-8'))

    def test_delete_image(self):
        """Test case for delete_image

        
        """
        query_string = [('region', 'region_example'),
                        ('force', True)]
        headers = { 
            'Accept': 'application/json',
            'aws.auth.sigv4': 'special-key',
        }
        response = self.client.open(
            '/v3/images/custom/{image_id}'.format(image_id='image_id_example'),
            method='DELETE',
            headers=headers,
            query_string=query_string)
        self.assert200(response,
                       'Response body is : ' + response.data.decode('utf-8'))

    def test_describe_image(self):
        """Test case for describe_image

        
        """
        query_string = [('region', 'region_example')]
        headers = { 
            'Accept': 'application/json',
            'aws.auth.sigv4': 'special-key',
        }
        response = self.client.open(
            '/v3/images/custom/{image_id}'.format(image_id='image_id_example'),
            method='GET',
            headers=headers,
            query_string=query_string)
        self.assert200(response,
                       'Response body is : ' + response.data.decode('utf-8'))

    def test_list_images(self):
        """Test case for list_images

        
        """
        query_string = [('region', 'region_example'),
                        ('nextToken', 'next_token_example'),
                        ('imageStatus', pcluster.api.ImageStatusFilteringOption())]
        headers = { 
            'Accept': 'application/json',
            'aws.auth.sigv4': 'special-key',
        }
        response = self.client.open(
            '/v3/images/custom',
            method='GET',
            headers=headers,
            query_string=query_string)
        self.assert200(response,
                       'Response body is : ' + response.data.decode('utf-8'))

    def test_list_official_images(self):
        """Test case for list_official_images

        
        """
        query_string = [('region', 'region_example'),
                        ('os', 'os_example'),
                        ('architecture', 'architecture_example')]
        headers = { 
            'Accept': 'application/json',
            'aws.auth.sigv4': 'special-key',
        }
        response = self.client.open(
            '/v3/images/official',
            method='GET',
            headers=headers,
            query_string=query_string)
        self.assert200(response,
                       'Response body is : ' + response.data.decode('utf-8'))


if __name__ == '__main__':
    unittest.main()
