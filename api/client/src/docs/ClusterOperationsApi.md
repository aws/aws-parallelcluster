# pcluster_client.ClusterOperationsApi

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**create_cluster**](ClusterOperationsApi.md#create_cluster) | **POST** /v3/clusters | 
[**delete_cluster**](ClusterOperationsApi.md#delete_cluster) | **DELETE** /v3/clusters/{clusterName} | 
[**describe_cluster**](ClusterOperationsApi.md#describe_cluster) | **GET** /v3/clusters/{clusterName} | 
[**list_clusters**](ClusterOperationsApi.md#list_clusters) | **GET** /v3/clusters | 
[**update_cluster**](ClusterOperationsApi.md#update_cluster) | **PUT** /v3/clusters/{clusterName} | 


# **create_cluster**
> CreateClusterResponseContent create_cluster(create_cluster_request_content)



Create a ParallelCluster managed cluster in a given region.

### Example

* Api Key Authentication (aws.auth.sigv4):
```python
import time
import pcluster_client
from pcluster_client.api import cluster_operations_api
from pcluster_client.model.create_cluster_bad_request_exception_response_content import CreateClusterBadRequestExceptionResponseContent
from pcluster_client.model.create_cluster_request_content import CreateClusterRequestContent
from pcluster_client.model.unauthorized_client_error_response_content import UnauthorizedClientErrorResponseContent
from pcluster_client.model.limit_exceeded_exception_response_content import LimitExceededExceptionResponseContent
from pcluster_client.model.create_cluster_response_content import CreateClusterResponseContent
from pcluster_client.model.conflict_exception_response_content import ConflictExceptionResponseContent
from pcluster_client.model.internal_service_exception_response_content import InternalServiceExceptionResponseContent
from pcluster_client.model.validation_level import ValidationLevel
from pcluster_client.model.dryrun_operation_exception_response_content import DryrunOperationExceptionResponseContent
from pprint import pprint
# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = pcluster_client.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure API key authorization: aws.auth.sigv4
configuration.api_key['aws.auth.sigv4'] = 'YOUR_API_KEY'

# Uncomment below to setup prefix (e.g. Bearer) for API key, if needed
# configuration.api_key_prefix['aws.auth.sigv4'] = 'Bearer'

# Enter a context with an instance of the API client
with pcluster_client.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = cluster_operations_api.ClusterOperationsApi(api_client)
    create_cluster_request_content = CreateClusterRequestContent(
        name="AqWzy",
        region="region_example",
        cluster_configuration='YQ==',
    ) # CreateClusterRequestContent | 
    suppress_validators = [
        "type:u2LC",
    ] # [str] | Identifies one or more config validators to suppress. Format: (ALL|type:[A-Za-z0-9]+) (optional)
    validation_failure_level = ValidationLevel("INFO") # ValidationLevel | Min validation level that will cause the creation to fail. Defaults to 'ERROR'. (optional)
    dryrun = True # bool, none_type | Only perform request validation without creating any resource. It can be used to validate the cluster configuration. Response code: 200 (optional)
    rollback_on_failure = True # bool, none_type | When set it automatically initiates a cluster stack rollback on failures. Defaults to true. (optional)

    # example passing only required values which don't have defaults set
    try:
        api_response = api_instance.create_cluster(create_cluster_request_content)
        pprint(api_response)
    except pcluster_client.ApiException as e:
        print("Exception when calling ClusterOperationsApi->create_cluster: %s\n" % e)

    # example passing only required values which don't have defaults set
    # and optional values
    try:
        api_response = api_instance.create_cluster(create_cluster_request_content, suppress_validators=suppress_validators, validation_failure_level=validation_failure_level, dryrun=dryrun, rollback_on_failure=rollback_on_failure)
        pprint(api_response)
    except pcluster_client.ApiException as e:
        print("Exception when calling ClusterOperationsApi->create_cluster: %s\n" % e)
```


### Parameters

Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **create_cluster_request_content** | [**CreateClusterRequestContent**](CreateClusterRequestContent.md)|  |
 **suppress_validators** | **[str]**| Identifies one or more config validators to suppress. Format: (ALL|type:[A-Za-z0-9]+) | [optional]
 **validation_failure_level** | **ValidationLevel**| Min validation level that will cause the creation to fail. Defaults to &#39;ERROR&#39;. | [optional]
 **dryrun** | **bool, none_type**| Only perform request validation without creating any resource. It can be used to validate the cluster configuration. Response code: 200 | [optional]
 **rollback_on_failure** | **bool, none_type**| When set it automatically initiates a cluster stack rollback on failures. Defaults to true. | [optional]

### Return type

[**CreateClusterResponseContent**](CreateClusterResponseContent.md)

### Authorization

[aws.auth.sigv4](../README.md#aws.auth.sigv4)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
**202** | CreateCluster 202 response |  -  |
**400** | CreateClusterBadRequestException 400 response |  -  |
**401** | UnauthorizedClientError 401 response |  -  |
**409** | ConflictException 409 response |  -  |
**412** | DryrunOperationException 412 response |  -  |
**429** | LimitExceededException 429 response |  -  |
**500** | InternalServiceException 500 response |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **delete_cluster**
> DeleteClusterResponseContent delete_cluster(cluster_name)



Initiate the deletion of a cluster.

### Example

* Api Key Authentication (aws.auth.sigv4):
```python
import time
import pcluster_client
from pcluster_client.api import cluster_operations_api
from pcluster_client.model.bad_request_exception_response_content import BadRequestExceptionResponseContent
from pcluster_client.model.unauthorized_client_error_response_content import UnauthorizedClientErrorResponseContent
from pcluster_client.model.limit_exceeded_exception_response_content import LimitExceededExceptionResponseContent
from pcluster_client.model.delete_cluster_response_content import DeleteClusterResponseContent
from pcluster_client.model.internal_service_exception_response_content import InternalServiceExceptionResponseContent
from pcluster_client.model.not_found_exception_response_content import NotFoundExceptionResponseContent
from pprint import pprint
# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = pcluster_client.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure API key authorization: aws.auth.sigv4
configuration.api_key['aws.auth.sigv4'] = 'YOUR_API_KEY'

# Uncomment below to setup prefix (e.g. Bearer) for API key, if needed
# configuration.api_key_prefix['aws.auth.sigv4'] = 'Bearer'

# Enter a context with an instance of the API client
with pcluster_client.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = cluster_operations_api.ClusterOperationsApi(api_client)
    cluster_name = "AqWzy" # str | Name of the cluster
    region = "region_example" # str | AWS Region. Defaults to the region the API is deployed to. (optional)

    # example passing only required values which don't have defaults set
    try:
        api_response = api_instance.delete_cluster(cluster_name)
        pprint(api_response)
    except pcluster_client.ApiException as e:
        print("Exception when calling ClusterOperationsApi->delete_cluster: %s\n" % e)

    # example passing only required values which don't have defaults set
    # and optional values
    try:
        api_response = api_instance.delete_cluster(cluster_name, region=region)
        pprint(api_response)
    except pcluster_client.ApiException as e:
        print("Exception when calling ClusterOperationsApi->delete_cluster: %s\n" % e)
```


### Parameters

Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **cluster_name** | **str**| Name of the cluster |
 **region** | **str**| AWS Region. Defaults to the region the API is deployed to. | [optional]

### Return type

[**DeleteClusterResponseContent**](DeleteClusterResponseContent.md)

### Authorization

[aws.auth.sigv4](../README.md#aws.auth.sigv4)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
**202** | DeleteCluster 202 response |  -  |
**400** | BadRequestException 400 response |  -  |
**401** | UnauthorizedClientError 401 response |  -  |
**404** | NotFoundException 404 response |  -  |
**429** | LimitExceededException 429 response |  -  |
**500** | InternalServiceException 500 response |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **describe_cluster**
> DescribeClusterResponseContent describe_cluster(cluster_name)



Get detailed information about an existing cluster.

### Example

* Api Key Authentication (aws.auth.sigv4):
```python
import time
import pcluster_client
from pcluster_client.api import cluster_operations_api
from pcluster_client.model.bad_request_exception_response_content import BadRequestExceptionResponseContent
from pcluster_client.model.unauthorized_client_error_response_content import UnauthorizedClientErrorResponseContent
from pcluster_client.model.limit_exceeded_exception_response_content import LimitExceededExceptionResponseContent
from pcluster_client.model.internal_service_exception_response_content import InternalServiceExceptionResponseContent
from pcluster_client.model.not_found_exception_response_content import NotFoundExceptionResponseContent
from pcluster_client.model.describe_cluster_response_content import DescribeClusterResponseContent
from pprint import pprint
# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = pcluster_client.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure API key authorization: aws.auth.sigv4
configuration.api_key['aws.auth.sigv4'] = 'YOUR_API_KEY'

# Uncomment below to setup prefix (e.g. Bearer) for API key, if needed
# configuration.api_key_prefix['aws.auth.sigv4'] = 'Bearer'

# Enter a context with an instance of the API client
with pcluster_client.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = cluster_operations_api.ClusterOperationsApi(api_client)
    cluster_name = "AqWzy" # str | Name of the cluster
    region = "region_example" # str | AWS Region. Defaults to the region the API is deployed to. (optional)

    # example passing only required values which don't have defaults set
    try:
        api_response = api_instance.describe_cluster(cluster_name)
        pprint(api_response)
    except pcluster_client.ApiException as e:
        print("Exception when calling ClusterOperationsApi->describe_cluster: %s\n" % e)

    # example passing only required values which don't have defaults set
    # and optional values
    try:
        api_response = api_instance.describe_cluster(cluster_name, region=region)
        pprint(api_response)
    except pcluster_client.ApiException as e:
        print("Exception when calling ClusterOperationsApi->describe_cluster: %s\n" % e)
```


### Parameters

Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **cluster_name** | **str**| Name of the cluster |
 **region** | **str**| AWS Region. Defaults to the region the API is deployed to. | [optional]

### Return type

[**DescribeClusterResponseContent**](DescribeClusterResponseContent.md)

### Authorization

[aws.auth.sigv4](../README.md#aws.auth.sigv4)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | DescribeCluster 200 response |  -  |
**400** | BadRequestException 400 response |  -  |
**401** | UnauthorizedClientError 401 response |  -  |
**404** | NotFoundException 404 response |  -  |
**429** | LimitExceededException 429 response |  -  |
**500** | InternalServiceException 500 response |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **list_clusters**
> ListClustersResponseContent list_clusters()



Retrieve the list of existing clusters managed by the API. Deleted clusters are not listed by default.

### Example

* Api Key Authentication (aws.auth.sigv4):
```python
import time
import pcluster_client
from pcluster_client.api import cluster_operations_api
from pcluster_client.model.bad_request_exception_response_content import BadRequestExceptionResponseContent
from pcluster_client.model.cluster_status_filtering_option import ClusterStatusFilteringOption
from pcluster_client.model.unauthorized_client_error_response_content import UnauthorizedClientErrorResponseContent
from pcluster_client.model.limit_exceeded_exception_response_content import LimitExceededExceptionResponseContent
from pcluster_client.model.list_clusters_response_content import ListClustersResponseContent
from pcluster_client.model.internal_service_exception_response_content import InternalServiceExceptionResponseContent
from pprint import pprint
# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = pcluster_client.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure API key authorization: aws.auth.sigv4
configuration.api_key['aws.auth.sigv4'] = 'YOUR_API_KEY'

# Uncomment below to setup prefix (e.g. Bearer) for API key, if needed
# configuration.api_key_prefix['aws.auth.sigv4'] = 'Bearer'

# Enter a context with an instance of the API client
with pcluster_client.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = cluster_operations_api.ClusterOperationsApi(api_client)
    region = "region_example" # str | List clusters deployed to a given AWS Region. Defaults to the AWS region the API is deployed to. (optional)
    next_token = "nextToken_example" # str | Token to use for paginated requests. (optional)
    cluster_status = [
        ClusterStatusFilteringOption("CREATE_IN_PROGRESS"),
    ] # [ClusterStatusFilteringOption] | Filter by cluster status. (optional)

    # example passing only required values which don't have defaults set
    # and optional values
    try:
        api_response = api_instance.list_clusters(region=region, next_token=next_token, cluster_status=cluster_status)
        pprint(api_response)
    except pcluster_client.ApiException as e:
        print("Exception when calling ClusterOperationsApi->list_clusters: %s\n" % e)
```


### Parameters

Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **region** | **str**| List clusters deployed to a given AWS Region. Defaults to the AWS region the API is deployed to. | [optional]
 **next_token** | **str**| Token to use for paginated requests. | [optional]
 **cluster_status** | [**[ClusterStatusFilteringOption]**](ClusterStatusFilteringOption.md)| Filter by cluster status. | [optional]

### Return type

[**ListClustersResponseContent**](ListClustersResponseContent.md)

### Authorization

[aws.auth.sigv4](../README.md#aws.auth.sigv4)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | ListClusters 200 response |  -  |
**400** | BadRequestException 400 response |  -  |
**401** | UnauthorizedClientError 401 response |  -  |
**429** | LimitExceededException 429 response |  -  |
**500** | InternalServiceException 500 response |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **update_cluster**
> UpdateClusterResponseContent update_cluster(cluster_name, update_cluster_request_content)



### Example

* Api Key Authentication (aws.auth.sigv4):
```python
import time
import pcluster_client
from pcluster_client.api import cluster_operations_api
from pcluster_client.model.update_cluster_request_content import UpdateClusterRequestContent
from pcluster_client.model.update_cluster_response_content import UpdateClusterResponseContent
from pcluster_client.model.unauthorized_client_error_response_content import UnauthorizedClientErrorResponseContent
from pcluster_client.model.limit_exceeded_exception_response_content import LimitExceededExceptionResponseContent
from pcluster_client.model.conflict_exception_response_content import ConflictExceptionResponseContent
from pcluster_client.model.update_cluster_bad_request_exception_response_content import UpdateClusterBadRequestExceptionResponseContent
from pcluster_client.model.internal_service_exception_response_content import InternalServiceExceptionResponseContent
from pcluster_client.model.validation_level import ValidationLevel
from pcluster_client.model.dryrun_operation_exception_response_content import DryrunOperationExceptionResponseContent
from pcluster_client.model.not_found_exception_response_content import NotFoundExceptionResponseContent
from pprint import pprint
# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = pcluster_client.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure API key authorization: aws.auth.sigv4
configuration.api_key['aws.auth.sigv4'] = 'YOUR_API_KEY'

# Uncomment below to setup prefix (e.g. Bearer) for API key, if needed
# configuration.api_key_prefix['aws.auth.sigv4'] = 'Bearer'

# Enter a context with an instance of the API client
with pcluster_client.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = cluster_operations_api.ClusterOperationsApi(api_client)
    cluster_name = "AqWzy" # str | Name of the cluster
    update_cluster_request_content = UpdateClusterRequestContent(
        cluster_configuration='YQ==',
    ) # UpdateClusterRequestContent | 
    suppress_validators = [
        "type:u2LC",
    ] # [str] | Identifies one or more config validators to suppress. Format: (ALL|type:[A-Za-z0-9]+) (optional)
    validation_failure_level = ValidationLevel("INFO") # ValidationLevel | Min validation level that will cause the update to fail. Defaults to 'error'. (optional)
    region = "region_example" # str | AWS Region. Defaults to the region the API is deployed to. (optional)
    dryrun = True # bool, none_type | Only perform request validation without creating any resource. It can be used to validate the cluster configuration and update requirements. Response code: 200 (optional)
    force_update = True # bool, none_type | Force update by ignoring the update validation errors. (optional)

    # example passing only required values which don't have defaults set
    try:
        api_response = api_instance.update_cluster(cluster_name, update_cluster_request_content)
        pprint(api_response)
    except pcluster_client.ApiException as e:
        print("Exception when calling ClusterOperationsApi->update_cluster: %s\n" % e)

    # example passing only required values which don't have defaults set
    # and optional values
    try:
        api_response = api_instance.update_cluster(cluster_name, update_cluster_request_content, suppress_validators=suppress_validators, validation_failure_level=validation_failure_level, region=region, dryrun=dryrun, force_update=force_update)
        pprint(api_response)
    except pcluster_client.ApiException as e:
        print("Exception when calling ClusterOperationsApi->update_cluster: %s\n" % e)
```


### Parameters

Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **cluster_name** | **str**| Name of the cluster |
 **update_cluster_request_content** | [**UpdateClusterRequestContent**](UpdateClusterRequestContent.md)|  |
 **suppress_validators** | **[str]**| Identifies one or more config validators to suppress. Format: (ALL|type:[A-Za-z0-9]+) | [optional]
 **validation_failure_level** | **ValidationLevel**| Min validation level that will cause the update to fail. Defaults to &#39;error&#39;. | [optional]
 **region** | **str**| AWS Region. Defaults to the region the API is deployed to. | [optional]
 **dryrun** | **bool, none_type**| Only perform request validation without creating any resource. It can be used to validate the cluster configuration and update requirements. Response code: 200 | [optional]
 **force_update** | **bool, none_type**| Force update by ignoring the update validation errors. | [optional]

### Return type

[**UpdateClusterResponseContent**](UpdateClusterResponseContent.md)

### Authorization

[aws.auth.sigv4](../README.md#aws.auth.sigv4)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
**202** | UpdateCluster 202 response |  -  |
**400** | UpdateClusterBadRequestException 400 response |  -  |
**401** | UnauthorizedClientError 401 response |  -  |
**404** | NotFoundException 404 response |  -  |
**409** | ConflictException 409 response |  -  |
**412** | DryrunOperationException 412 response |  -  |
**429** | LimitExceededException 429 response |  -  |
**500** | InternalServiceException 500 response |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

