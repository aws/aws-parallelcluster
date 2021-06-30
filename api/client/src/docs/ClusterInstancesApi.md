# pcluster_client.ClusterInstancesApi

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**delete_cluster_instances**](ClusterInstancesApi.md#delete_cluster_instances) | **DELETE** /v3/clusters/{clusterName}/instances | 
[**describe_cluster_instances**](ClusterInstancesApi.md#describe_cluster_instances) | **GET** /v3/clusters/{clusterName}/instances | 


# **delete_cluster_instances**
> delete_cluster_instances(cluster_name)



Initiate the forced termination of all cluster compute nodes. Does not work with AWS Batch clusters

### Example

* Api Key Authentication (aws.auth.sigv4):
```python
import time
import pcluster_client
from pcluster_client.api import cluster_instances_api
from pcluster_client.model.bad_request_exception_response_content import BadRequestExceptionResponseContent
from pcluster_client.model.unauthorized_client_error_response_content import UnauthorizedClientErrorResponseContent
from pcluster_client.model.limit_exceeded_exception_response_content import LimitExceededExceptionResponseContent
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
    api_instance = cluster_instances_api.ClusterInstancesApi(api_client)
    cluster_name = "AqWzy" # str | Name of the cluster
    region = "region_example" # str | AWS Region. Defaults to the region the API is deployed to. (optional)
    force = True # bool, none_type | Force the deletion also when the cluster id is not found. (optional)

    # example passing only required values which don't have defaults set
    try:
        api_instance.delete_cluster_instances(cluster_name)
    except pcluster_client.ApiException as e:
        print("Exception when calling ClusterInstancesApi->delete_cluster_instances: %s\n" % e)

    # example passing only required values which don't have defaults set
    # and optional values
    try:
        api_instance.delete_cluster_instances(cluster_name, region=region, force=force)
    except pcluster_client.ApiException as e:
        print("Exception when calling ClusterInstancesApi->delete_cluster_instances: %s\n" % e)
```


### Parameters

Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **cluster_name** | **str**| Name of the cluster |
 **region** | **str**| AWS Region. Defaults to the region the API is deployed to. | [optional]
 **force** | **bool, none_type**| Force the deletion also when the cluster id is not found. | [optional]

### Return type

void (empty response body)

### Authorization

[aws.auth.sigv4](../README.md#aws.auth.sigv4)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
**202** | DeleteClusterInstances 202 response |  -  |
**400** | BadRequestException 400 response |  -  |
**401** | UnauthorizedClientError 401 response |  -  |
**404** | NotFoundException 404 response |  -  |
**429** | LimitExceededException 429 response |  -  |
**500** | InternalServiceException 500 response |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **describe_cluster_instances**
> DescribeClusterInstancesResponseContent describe_cluster_instances(cluster_name)



Describe the instances belonging to a given cluster.

### Example

* Api Key Authentication (aws.auth.sigv4):
```python
import time
import pcluster_client
from pcluster_client.api import cluster_instances_api
from pcluster_client.model.bad_request_exception_response_content import BadRequestExceptionResponseContent
from pcluster_client.model.unauthorized_client_error_response_content import UnauthorizedClientErrorResponseContent
from pcluster_client.model.limit_exceeded_exception_response_content import LimitExceededExceptionResponseContent
from pcluster_client.model.node_type import NodeType
from pcluster_client.model.internal_service_exception_response_content import InternalServiceExceptionResponseContent
from pcluster_client.model.not_found_exception_response_content import NotFoundExceptionResponseContent
from pcluster_client.model.describe_cluster_instances_response_content import DescribeClusterInstancesResponseContent
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
    api_instance = cluster_instances_api.ClusterInstancesApi(api_client)
    cluster_name = "AqWzy" # str | Name of the cluster
    region = "region_example" # str | AWS Region. Defaults to the region the API is deployed to. (optional)
    next_token = "nextToken_example" # str | Token to use for paginated requests. (optional)
    node_type = NodeType("HEAD") # NodeType |  (optional)
    queue_name = "queueName_example" # str |  (optional)

    # example passing only required values which don't have defaults set
    try:
        api_response = api_instance.describe_cluster_instances(cluster_name)
        pprint(api_response)
    except pcluster_client.ApiException as e:
        print("Exception when calling ClusterInstancesApi->describe_cluster_instances: %s\n" % e)

    # example passing only required values which don't have defaults set
    # and optional values
    try:
        api_response = api_instance.describe_cluster_instances(cluster_name, region=region, next_token=next_token, node_type=node_type, queue_name=queue_name)
        pprint(api_response)
    except pcluster_client.ApiException as e:
        print("Exception when calling ClusterInstancesApi->describe_cluster_instances: %s\n" % e)
```


### Parameters

Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **cluster_name** | **str**| Name of the cluster |
 **region** | **str**| AWS Region. Defaults to the region the API is deployed to. | [optional]
 **next_token** | **str**| Token to use for paginated requests. | [optional]
 **node_type** | **NodeType**|  | [optional]
 **queue_name** | **str**|  | [optional]

### Return type

[**DescribeClusterInstancesResponseContent**](DescribeClusterInstancesResponseContent.md)

### Authorization

[aws.auth.sigv4](../README.md#aws.auth.sigv4)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | DescribeClusterInstances 200 response |  -  |
**400** | BadRequestException 400 response |  -  |
**401** | UnauthorizedClientError 401 response |  -  |
**404** | NotFoundException 404 response |  -  |
**429** | LimitExceededException 429 response |  -  |
**500** | InternalServiceException 500 response |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

