"""
    ParallelCluster

    ParallelCluster API  # noqa: E501

    The version of the OpenAPI document: 3.7.1
    Generated by: https://openapi-generator.tech
"""


import re  # noqa: F401
import sys  # noqa: F401

from pcluster_client.api_client import ApiClient, Endpoint as _Endpoint
from pcluster_client.model_utils import (  # noqa: F401
    check_allowed_values,
    check_validations,
    date,
    datetime,
    file_type,
    none_type,
    validate_and_convert_types
)
from pcluster_client.model.bad_request_exception_response_content import BadRequestExceptionResponseContent
from pcluster_client.model.describe_cluster_instances_response_content import DescribeClusterInstancesResponseContent
from pcluster_client.model.internal_service_exception_response_content import InternalServiceExceptionResponseContent
from pcluster_client.model.limit_exceeded_exception_response_content import LimitExceededExceptionResponseContent
from pcluster_client.model.node_type import NodeType
from pcluster_client.model.not_found_exception_response_content import NotFoundExceptionResponseContent
from pcluster_client.model.unauthorized_client_error_response_content import UnauthorizedClientErrorResponseContent


class ClusterInstancesApi(object):
    """NOTE: This class is auto generated by OpenAPI Generator
    Ref: https://openapi-generator.tech

    Do not edit the class manually.
    """

    def __init__(self, api_client=None):
        if api_client is None:
            api_client = ApiClient()
        self.api_client = api_client
        self.delete_cluster_instances_endpoint = _Endpoint(
            settings={
                'response_type': None,
                'auth': [
                    'aws.auth.sigv4'
                ],
                'endpoint_path': '/v3/clusters/{clusterName}/instances',
                'operation_id': 'delete_cluster_instances',
                'http_method': 'DELETE',
                'servers': None,
            },
            params_map={
                'all': [
                    'cluster_name',
                    'region',
                    'force',
                ],
                'required': [
                    'cluster_name',
                ],
                'nullable': [
                ],
                'enum': [
                ],
                'validation': [
                    'cluster_name',
                ]
            },
            root_map={
                'validations': {
                    ('cluster_name',): {

                        'regex': {
                            'pattern': r'^[a-zA-Z][a-zA-Z0-9-]+$',  # noqa: E501
                        },
                    },
                },
                'allowed_values': {
                },
                'openapi_types': {
                    'cluster_name':
                        (str,),
                    'region':
                        (str,),
                    'force':
                        (bool,),
                },
                'attribute_map': {
                    'cluster_name': 'clusterName',
                    'region': 'region',
                    'force': 'force',
                },
                'location_map': {
                    'cluster_name': 'path',
                    'region': 'query',
                    'force': 'query',
                },
                'collection_format_map': {
                }
            },
            headers_map={
                'accept': [
                    'application/json'
                ],
                'content_type': [],
            },
            api_client=api_client
        )
        self.describe_cluster_instances_endpoint = _Endpoint(
            settings={
                'response_type': (DescribeClusterInstancesResponseContent,),
                'auth': [
                    'aws.auth.sigv4'
                ],
                'endpoint_path': '/v3/clusters/{clusterName}/instances',
                'operation_id': 'describe_cluster_instances',
                'http_method': 'GET',
                'servers': None,
            },
            params_map={
                'all': [
                    'cluster_name',
                    'region',
                    'next_token',
                    'node_type',
                    'queue_name',
                ],
                'required': [
                    'cluster_name',
                ],
                'nullable': [
                ],
                'enum': [
                ],
                'validation': [
                    'cluster_name',
                ]
            },
            root_map={
                'validations': {
                    ('cluster_name',): {

                        'regex': {
                            'pattern': r'^[a-zA-Z][a-zA-Z0-9-]+$',  # noqa: E501
                        },
                    },
                },
                'allowed_values': {
                },
                'openapi_types': {
                    'cluster_name':
                        (str,),
                    'region':
                        (str,),
                    'next_token':
                        (str,),
                    'node_type':
                        (NodeType,),
                    'queue_name':
                        (str,),
                },
                'attribute_map': {
                    'cluster_name': 'clusterName',
                    'region': 'region',
                    'next_token': 'nextToken',
                    'node_type': 'nodeType',
                    'queue_name': 'queueName',
                },
                'location_map': {
                    'cluster_name': 'path',
                    'region': 'query',
                    'next_token': 'query',
                    'node_type': 'query',
                    'queue_name': 'query',
                },
                'collection_format_map': {
                }
            },
            headers_map={
                'accept': [
                    'application/json'
                ],
                'content_type': [],
            },
            api_client=api_client
        )

    def delete_cluster_instances(
        self,
        cluster_name,
        **kwargs
    ):
        """delete_cluster_instances  # noqa: E501

        Initiate the forced termination of all cluster compute nodes. Does not work with AWS Batch clusters.  # noqa: E501
        This method makes a synchronous HTTP request by default. To make an
        asynchronous HTTP request, please pass async_req=True

        >>> thread = api.delete_cluster_instances(cluster_name, async_req=True)
        >>> result = thread.get()

        Args:
            cluster_name (str): Name of the cluster

        Keyword Args:
            region (str): AWS Region that the operation corresponds to.. [optional]
            force (bool): Force the deletion also when the cluster with the given name is not found. (Defaults to 'false'.). [optional]
            _return_http_data_only (bool): response data without head status
                code and headers. Default is True.
            _preload_content (bool): if False, the urllib3.HTTPResponse object
                will be returned without reading/decoding response data.
                Default is True.
            _request_timeout (int/float/tuple): timeout setting for this request. If
                one number provided, it will be total request timeout. It can also
                be a pair (tuple) of (connection, read) timeouts.
                Default is None.
            _check_input_type (bool): specifies if type checking
                should be done one the data sent to the server.
                Default is True.
            _check_return_type (bool): specifies if type checking
                should be done one the data received from the server.
                Default is True.
            _spec_property_naming (bool): True if the variable names in the input data
                are serialized names, as specified in the OpenAPI document.
                False if the variable names in the input data
                are pythonic names, e.g. snake case (default)
            _content_type (str/None): force body content-type.
                Default is None and content-type will be predicted by allowed
                content-types and body.
            _host_index (int/None): specifies the index of the server
                that we want to use.
                Default is read from the configuration.
            _request_auths (list): set to override the auth_settings for an a single
                request; this effectively ignores the authentication
                in the spec for a single request.
                Default is None
            async_req (bool): execute request asynchronously

        Returns:
            None
                If the method is called asynchronously, returns the request
                thread.
        """
        kwargs['async_req'] = kwargs.get(
            'async_req', False
        )
        kwargs['_return_http_data_only'] = kwargs.get(
            '_return_http_data_only', True
        )
        kwargs['_preload_content'] = kwargs.get(
            '_preload_content', True
        )
        kwargs['_request_timeout'] = kwargs.get(
            '_request_timeout', None
        )
        kwargs['_check_input_type'] = kwargs.get(
            '_check_input_type', True
        )
        kwargs['_check_return_type'] = kwargs.get(
            '_check_return_type', True
        )
        kwargs['_spec_property_naming'] = kwargs.get(
            '_spec_property_naming', False
        )
        kwargs['_content_type'] = kwargs.get(
            '_content_type')
        kwargs['_host_index'] = kwargs.get('_host_index')
        kwargs['_request_auths'] = kwargs.get('_request_auths', None)
        kwargs['cluster_name'] = \
            cluster_name
        return self.delete_cluster_instances_endpoint.call_with_http_info(**kwargs)

    def describe_cluster_instances(
        self,
        cluster_name,
        **kwargs
    ):
        """describe_cluster_instances  # noqa: E501

        Describe the instances belonging to a given cluster.  # noqa: E501
        This method makes a synchronous HTTP request by default. To make an
        asynchronous HTTP request, please pass async_req=True

        >>> thread = api.describe_cluster_instances(cluster_name, async_req=True)
        >>> result = thread.get()

        Args:
            cluster_name (str): Name of the cluster

        Keyword Args:
            region (str): AWS Region that the operation corresponds to.. [optional]
            next_token (str): Token to use for paginated requests.. [optional]
            node_type (NodeType): Filter the instances by node type.. [optional]
            queue_name (str): Filter the instances by queue name.. [optional]
            _return_http_data_only (bool): response data without head status
                code and headers. Default is True.
            _preload_content (bool): if False, the urllib3.HTTPResponse object
                will be returned without reading/decoding response data.
                Default is True.
            _request_timeout (int/float/tuple): timeout setting for this request. If
                one number provided, it will be total request timeout. It can also
                be a pair (tuple) of (connection, read) timeouts.
                Default is None.
            _check_input_type (bool): specifies if type checking
                should be done one the data sent to the server.
                Default is True.
            _check_return_type (bool): specifies if type checking
                should be done one the data received from the server.
                Default is True.
            _spec_property_naming (bool): True if the variable names in the input data
                are serialized names, as specified in the OpenAPI document.
                False if the variable names in the input data
                are pythonic names, e.g. snake case (default)
            _content_type (str/None): force body content-type.
                Default is None and content-type will be predicted by allowed
                content-types and body.
            _host_index (int/None): specifies the index of the server
                that we want to use.
                Default is read from the configuration.
            _request_auths (list): set to override the auth_settings for an a single
                request; this effectively ignores the authentication
                in the spec for a single request.
                Default is None
            async_req (bool): execute request asynchronously

        Returns:
            DescribeClusterInstancesResponseContent
                If the method is called asynchronously, returns the request
                thread.
        """
        kwargs['async_req'] = kwargs.get(
            'async_req', False
        )
        kwargs['_return_http_data_only'] = kwargs.get(
            '_return_http_data_only', True
        )
        kwargs['_preload_content'] = kwargs.get(
            '_preload_content', True
        )
        kwargs['_request_timeout'] = kwargs.get(
            '_request_timeout', None
        )
        kwargs['_check_input_type'] = kwargs.get(
            '_check_input_type', True
        )
        kwargs['_check_return_type'] = kwargs.get(
            '_check_return_type', True
        )
        kwargs['_spec_property_naming'] = kwargs.get(
            '_spec_property_naming', False
        )
        kwargs['_content_type'] = kwargs.get(
            '_content_type')
        kwargs['_host_index'] = kwargs.get('_host_index')
        kwargs['_request_auths'] = kwargs.get('_request_auths', None)
        kwargs['cluster_name'] = \
            cluster_name
        return self.describe_cluster_instances_endpoint.call_with_http_info(**kwargs)

