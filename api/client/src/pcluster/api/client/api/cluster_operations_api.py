"""
    ParallelCluster

    ParallelCluster API  # noqa: E501

    The version of the OpenAPI document: 3.0.0
    Generated by: https://openapi-generator.tech
"""


import re  # noqa: F401
import sys  # noqa: F401

from pcluster.api.client.api_client import ApiClient, Endpoint as _Endpoint
from pcluster.api.client.model_utils import (  # noqa: F401
    check_allowed_values,
    check_validations,
    date,
    datetime,
    file_type,
    none_type,
    validate_and_convert_types
)
from pcluster.api.client.model.bad_request_exception_response_content import BadRequestExceptionResponseContent
from pcluster.api.client.model.cluster_status_filtering_option import ClusterStatusFilteringOption
from pcluster.api.client.model.conflict_exception_response_content import ConflictExceptionResponseContent
from pcluster.api.client.model.create_cluster_bad_request_exception_response_content import CreateClusterBadRequestExceptionResponseContent
from pcluster.api.client.model.create_cluster_request_content import CreateClusterRequestContent
from pcluster.api.client.model.create_cluster_response_content import CreateClusterResponseContent
from pcluster.api.client.model.delete_cluster_response_content import DeleteClusterResponseContent
from pcluster.api.client.model.describe_cluster_response_content import DescribeClusterResponseContent
from pcluster.api.client.model.dryrun_operation_exception_response_content import DryrunOperationExceptionResponseContent
from pcluster.api.client.model.internal_service_exception_response_content import InternalServiceExceptionResponseContent
from pcluster.api.client.model.limit_exceeded_exception_response_content import LimitExceededExceptionResponseContent
from pcluster.api.client.model.list_clusters_response_content import ListClustersResponseContent
from pcluster.api.client.model.not_found_exception_response_content import NotFoundExceptionResponseContent
from pcluster.api.client.model.unauthorized_client_error_response_content import UnauthorizedClientErrorResponseContent
from pcluster.api.client.model.update_cluster_bad_request_exception_response_content import UpdateClusterBadRequestExceptionResponseContent
from pcluster.api.client.model.update_cluster_request_content import UpdateClusterRequestContent
from pcluster.api.client.model.update_cluster_response_content import UpdateClusterResponseContent
from pcluster.api.client.model.validation_level import ValidationLevel


class ClusterOperationsApi(object):
    """NOTE: This class is auto generated by OpenAPI Generator
    Ref: https://openapi-generator.tech

    Do not edit the class manually.
    """

    def __init__(self, api_client=None):
        if api_client is None:
            api_client = ApiClient()
        self.api_client = api_client

        def __create_cluster(
            self,
            create_cluster_request_content,
            **kwargs
        ):
            """create_cluster  # noqa: E501

            Create a ParallelCluster managed cluster in a given region.  # noqa: E501
            This method makes a synchronous HTTP request by default. To make an
            asynchronous HTTP request, please pass async_req=True

            >>> thread = api.create_cluster(create_cluster_request_content, async_req=True)
            >>> result = thread.get()

            Args:
                create_cluster_request_content (CreateClusterRequestContent):

            Keyword Args:
                suppress_validators ([str]): Identifies one or more config validators to suppress. Format: (ALL|type:[A-Za-z0-9]+). [optional]
                validation_failure_level (ValidationLevel): Min validation level that will cause the creation to fail. Defaults to 'ERROR'.. [optional]
                dryrun (bool, none_type): Only perform request validation without creating any resource. It can be used to validate the cluster configuration. Response code: 200. [optional]
                rollback_on_failure (bool, none_type): When set it automatically initiates a cluster stack rollback on failures. Defaults to true.. [optional]
                _return_http_data_only (bool): response data without head status
                    code and headers. Default is True.
                _preload_content (bool): if False, the urllib3.HTTPResponse object
                    will be returned without reading/decoding response data.
                    Default is True.
                _request_timeout (float/tuple): timeout setting for this request. If one
                    number provided, it will be total request timeout. It can also
                    be a pair (tuple) of (connection, read) timeouts.
                    Default is None.
                _check_input_type (bool): specifies if type checking
                    should be done one the data sent to the server.
                    Default is True.
                _check_return_type (bool): specifies if type checking
                    should be done one the data received from the server.
                    Default is True.
                _host_index (int/None): specifies the index of the server
                    that we want to use.
                    Default is read from the configuration.
                async_req (bool): execute request asynchronously

            Returns:
                CreateClusterResponseContent
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
            kwargs['_host_index'] = kwargs.get('_host_index')
            kwargs['create_cluster_request_content'] = \
                create_cluster_request_content
            return self.call_with_http_info(**kwargs)

        self.create_cluster = _Endpoint(
            settings={
                'response_type': (CreateClusterResponseContent,),
                'auth': [
                    'aws.auth.sigv4'
                ],
                'endpoint_path': '/v3/clusters',
                'operation_id': 'create_cluster',
                'http_method': 'POST',
                'servers': None,
            },
            params_map={
                'all': [
                    'create_cluster_request_content',
                    'suppress_validators',
                    'validation_failure_level',
                    'dryrun',
                    'rollback_on_failure',
                ],
                'required': [
                    'create_cluster_request_content',
                ],
                'nullable': [
                    'dryrun',
                    'rollback_on_failure',
                ],
                'enum': [
                ],
                'validation': [
                    'suppress_validators',
                ]
            },
            root_map={
                'validations': {
                    ('suppress_validators',): {

                    },
                },
                'allowed_values': {
                },
                'openapi_types': {
                    'create_cluster_request_content':
                        (CreateClusterRequestContent,),
                    'suppress_validators':
                        ([str],),
                    'validation_failure_level':
                        (ValidationLevel,),
                    'dryrun':
                        (bool, none_type,),
                    'rollback_on_failure':
                        (bool, none_type,),
                },
                'attribute_map': {
                    'suppress_validators': 'suppressValidators',
                    'validation_failure_level': 'validationFailureLevel',
                    'dryrun': 'dryrun',
                    'rollback_on_failure': 'rollbackOnFailure',
                },
                'location_map': {
                    'create_cluster_request_content': 'body',
                    'suppress_validators': 'query',
                    'validation_failure_level': 'query',
                    'dryrun': 'query',
                    'rollback_on_failure': 'query',
                },
                'collection_format_map': {
                    'suppress_validators': 'multi',
                }
            },
            headers_map={
                'accept': [
                    'application/json'
                ],
                'content_type': [
                    'application/json'
                ]
            },
            api_client=api_client,
            callable=__create_cluster
        )

        def __delete_cluster(
            self,
            cluster_name,
            **kwargs
        ):
            """delete_cluster  # noqa: E501

            Initiate the deletion of a cluster.  # noqa: E501
            This method makes a synchronous HTTP request by default. To make an
            asynchronous HTTP request, please pass async_req=True

            >>> thread = api.delete_cluster(cluster_name, async_req=True)
            >>> result = thread.get()

            Args:
                cluster_name (str): Name of the cluster

            Keyword Args:
                region (str): AWS Region. Defaults to the region the API is deployed to.. [optional]
                _return_http_data_only (bool): response data without head status
                    code and headers. Default is True.
                _preload_content (bool): if False, the urllib3.HTTPResponse object
                    will be returned without reading/decoding response data.
                    Default is True.
                _request_timeout (float/tuple): timeout setting for this request. If one
                    number provided, it will be total request timeout. It can also
                    be a pair (tuple) of (connection, read) timeouts.
                    Default is None.
                _check_input_type (bool): specifies if type checking
                    should be done one the data sent to the server.
                    Default is True.
                _check_return_type (bool): specifies if type checking
                    should be done one the data received from the server.
                    Default is True.
                _host_index (int/None): specifies the index of the server
                    that we want to use.
                    Default is read from the configuration.
                async_req (bool): execute request asynchronously

            Returns:
                DeleteClusterResponseContent
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
            kwargs['_host_index'] = kwargs.get('_host_index')
            kwargs['cluster_name'] = \
                cluster_name
            return self.call_with_http_info(**kwargs)

        self.delete_cluster = _Endpoint(
            settings={
                'response_type': (DeleteClusterResponseContent,),
                'auth': [
                    'aws.auth.sigv4'
                ],
                'endpoint_path': '/v3/clusters/{clusterName}',
                'operation_id': 'delete_cluster',
                'http_method': 'DELETE',
                'servers': None,
            },
            params_map={
                'all': [
                    'cluster_name',
                    'region',
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
                        'max_length': 60,
                        'min_length': 5,
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
                },
                'attribute_map': {
                    'cluster_name': 'clusterName',
                    'region': 'region',
                },
                'location_map': {
                    'cluster_name': 'path',
                    'region': 'query',
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
            api_client=api_client,
            callable=__delete_cluster
        )

        def __describe_cluster(
            self,
            cluster_name,
            **kwargs
        ):
            """describe_cluster  # noqa: E501

            Get detailed information about an existing cluster.  # noqa: E501
            This method makes a synchronous HTTP request by default. To make an
            asynchronous HTTP request, please pass async_req=True

            >>> thread = api.describe_cluster(cluster_name, async_req=True)
            >>> result = thread.get()

            Args:
                cluster_name (str): Name of the cluster

            Keyword Args:
                region (str): AWS Region. Defaults to the region the API is deployed to.. [optional]
                _return_http_data_only (bool): response data without head status
                    code and headers. Default is True.
                _preload_content (bool): if False, the urllib3.HTTPResponse object
                    will be returned without reading/decoding response data.
                    Default is True.
                _request_timeout (float/tuple): timeout setting for this request. If one
                    number provided, it will be total request timeout. It can also
                    be a pair (tuple) of (connection, read) timeouts.
                    Default is None.
                _check_input_type (bool): specifies if type checking
                    should be done one the data sent to the server.
                    Default is True.
                _check_return_type (bool): specifies if type checking
                    should be done one the data received from the server.
                    Default is True.
                _host_index (int/None): specifies the index of the server
                    that we want to use.
                    Default is read from the configuration.
                async_req (bool): execute request asynchronously

            Returns:
                DescribeClusterResponseContent
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
            kwargs['_host_index'] = kwargs.get('_host_index')
            kwargs['cluster_name'] = \
                cluster_name
            return self.call_with_http_info(**kwargs)

        self.describe_cluster = _Endpoint(
            settings={
                'response_type': (DescribeClusterResponseContent,),
                'auth': [
                    'aws.auth.sigv4'
                ],
                'endpoint_path': '/v3/clusters/{clusterName}',
                'operation_id': 'describe_cluster',
                'http_method': 'GET',
                'servers': None,
            },
            params_map={
                'all': [
                    'cluster_name',
                    'region',
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
                        'max_length': 60,
                        'min_length': 5,
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
                },
                'attribute_map': {
                    'cluster_name': 'clusterName',
                    'region': 'region',
                },
                'location_map': {
                    'cluster_name': 'path',
                    'region': 'query',
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
            api_client=api_client,
            callable=__describe_cluster
        )

        def __list_clusters(
            self,
            **kwargs
        ):
            """list_clusters  # noqa: E501

            Retrieve the list of existing clusters managed by the API. Deleted clusters are not listed by default.  # noqa: E501
            This method makes a synchronous HTTP request by default. To make an
            asynchronous HTTP request, please pass async_req=True

            >>> thread = api.list_clusters(async_req=True)
            >>> result = thread.get()


            Keyword Args:
                region (str): List clusters deployed to a given AWS Region. Defaults to the AWS region the API is deployed to.. [optional]
                next_token (str): Token to use for paginated requests.. [optional]
                cluster_status ([ClusterStatusFilteringOption]): Filter by cluster status.. [optional]
                _return_http_data_only (bool): response data without head status
                    code and headers. Default is True.
                _preload_content (bool): if False, the urllib3.HTTPResponse object
                    will be returned without reading/decoding response data.
                    Default is True.
                _request_timeout (float/tuple): timeout setting for this request. If one
                    number provided, it will be total request timeout. It can also
                    be a pair (tuple) of (connection, read) timeouts.
                    Default is None.
                _check_input_type (bool): specifies if type checking
                    should be done one the data sent to the server.
                    Default is True.
                _check_return_type (bool): specifies if type checking
                    should be done one the data received from the server.
                    Default is True.
                _host_index (int/None): specifies the index of the server
                    that we want to use.
                    Default is read from the configuration.
                async_req (bool): execute request asynchronously

            Returns:
                ListClustersResponseContent
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
            kwargs['_host_index'] = kwargs.get('_host_index')
            return self.call_with_http_info(**kwargs)

        self.list_clusters = _Endpoint(
            settings={
                'response_type': (ListClustersResponseContent,),
                'auth': [
                    'aws.auth.sigv4'
                ],
                'endpoint_path': '/v3/clusters',
                'operation_id': 'list_clusters',
                'http_method': 'GET',
                'servers': None,
            },
            params_map={
                'all': [
                    'region',
                    'next_token',
                    'cluster_status',
                ],
                'required': [],
                'nullable': [
                ],
                'enum': [
                ],
                'validation': [
                    'cluster_status',
                ]
            },
            root_map={
                'validations': {
                    ('cluster_status',): {

                    },
                },
                'allowed_values': {
                },
                'openapi_types': {
                    'region':
                        (str,),
                    'next_token':
                        (str,),
                    'cluster_status':
                        ([ClusterStatusFilteringOption],),
                },
                'attribute_map': {
                    'region': 'region',
                    'next_token': 'nextToken',
                    'cluster_status': 'clusterStatus',
                },
                'location_map': {
                    'region': 'query',
                    'next_token': 'query',
                    'cluster_status': 'query',
                },
                'collection_format_map': {
                    'cluster_status': 'multi',
                }
            },
            headers_map={
                'accept': [
                    'application/json'
                ],
                'content_type': [],
            },
            api_client=api_client,
            callable=__list_clusters
        )

        def __update_cluster(
            self,
            cluster_name,
            update_cluster_request_content,
            **kwargs
        ):
            """update_cluster  # noqa: E501

            This method makes a synchronous HTTP request by default. To make an
            asynchronous HTTP request, please pass async_req=True

            >>> thread = api.update_cluster(cluster_name, update_cluster_request_content, async_req=True)
            >>> result = thread.get()

            Args:
                cluster_name (str): Name of the cluster
                update_cluster_request_content (UpdateClusterRequestContent):

            Keyword Args:
                suppress_validators ([str]): Identifies one or more config validators to suppress. Format: (ALL|type:[A-Za-z0-9]+). [optional]
                validation_failure_level (ValidationLevel): Min validation level that will cause the update to fail. Defaults to 'error'.. [optional]
                region (str): AWS Region. Defaults to the region the API is deployed to.. [optional]
                dryrun (bool, none_type): Only perform request validation without creating any resource. It can be used to validate the cluster configuration and update requirements. Response code: 200. [optional]
                force_update (bool, none_type): Force update by ignoring the update validation errors.. [optional]
                _return_http_data_only (bool): response data without head status
                    code and headers. Default is True.
                _preload_content (bool): if False, the urllib3.HTTPResponse object
                    will be returned without reading/decoding response data.
                    Default is True.
                _request_timeout (float/tuple): timeout setting for this request. If one
                    number provided, it will be total request timeout. It can also
                    be a pair (tuple) of (connection, read) timeouts.
                    Default is None.
                _check_input_type (bool): specifies if type checking
                    should be done one the data sent to the server.
                    Default is True.
                _check_return_type (bool): specifies if type checking
                    should be done one the data received from the server.
                    Default is True.
                _host_index (int/None): specifies the index of the server
                    that we want to use.
                    Default is read from the configuration.
                async_req (bool): execute request asynchronously

            Returns:
                UpdateClusterResponseContent
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
            kwargs['_host_index'] = kwargs.get('_host_index')
            kwargs['cluster_name'] = \
                cluster_name
            kwargs['update_cluster_request_content'] = \
                update_cluster_request_content
            return self.call_with_http_info(**kwargs)

        self.update_cluster = _Endpoint(
            settings={
                'response_type': (UpdateClusterResponseContent,),
                'auth': [
                    'aws.auth.sigv4'
                ],
                'endpoint_path': '/v3/clusters/{clusterName}',
                'operation_id': 'update_cluster',
                'http_method': 'PUT',
                'servers': None,
            },
            params_map={
                'all': [
                    'cluster_name',
                    'update_cluster_request_content',
                    'suppress_validators',
                    'validation_failure_level',
                    'region',
                    'dryrun',
                    'force_update',
                ],
                'required': [
                    'cluster_name',
                    'update_cluster_request_content',
                ],
                'nullable': [
                    'dryrun',
                    'force_update',
                ],
                'enum': [
                ],
                'validation': [
                    'cluster_name',
                    'suppress_validators',
                ]
            },
            root_map={
                'validations': {
                    ('cluster_name',): {
                        'max_length': 60,
                        'min_length': 5,
                        'regex': {
                            'pattern': r'^[a-zA-Z][a-zA-Z0-9-]+$',  # noqa: E501
                        },
                    },
                    ('suppress_validators',): {

                    },
                },
                'allowed_values': {
                },
                'openapi_types': {
                    'cluster_name':
                        (str,),
                    'update_cluster_request_content':
                        (UpdateClusterRequestContent,),
                    'suppress_validators':
                        ([str],),
                    'validation_failure_level':
                        (ValidationLevel,),
                    'region':
                        (str,),
                    'dryrun':
                        (bool, none_type,),
                    'force_update':
                        (bool, none_type,),
                },
                'attribute_map': {
                    'cluster_name': 'clusterName',
                    'suppress_validators': 'suppressValidators',
                    'validation_failure_level': 'validationFailureLevel',
                    'region': 'region',
                    'dryrun': 'dryrun',
                    'force_update': 'forceUpdate',
                },
                'location_map': {
                    'cluster_name': 'path',
                    'update_cluster_request_content': 'body',
                    'suppress_validators': 'query',
                    'validation_failure_level': 'query',
                    'region': 'query',
                    'dryrun': 'query',
                    'force_update': 'query',
                },
                'collection_format_map': {
                    'suppress_validators': 'multi',
                }
            },
            headers_map={
                'accept': [
                    'application/json'
                ],
                'content_type': [
                    'application/json'
                ]
            },
            api_client=api_client,
            callable=__update_cluster
        )
