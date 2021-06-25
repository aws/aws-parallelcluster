# pcluster.api.client.ClusterComputeFleetApi

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**describe_compute_fleet_status**](ClusterComputeFleetApi.md#describe_compute_fleet_status) | **GET** /v3/clusters/{clusterName}/computefleet/status | 
[**update_compute_fleet_status**](ClusterComputeFleetApi.md#update_compute_fleet_status) | **PATCH** /v3/clusters/{clusterName}/computefleet/status | 


# **describe_compute_fleet_status**
> DescribeComputeFleetStatusResponseContent describe_compute_fleet_status(cluster_name)



Describe the status of the compute fleet

### Example

* Api Key Authentication (aws.auth.sigv4):
```python
import time
import pcluster.api.client
from pcluster.api.client.api import cluster_compute_fleet_api
from pcluster.api.client.model.bad_request_exception_response_content import BadRequestExceptionResponseContent
from pcluster.api.client.model.not_found_exception_response_content import NotFoundExceptionResponseContent
from pcluster.api.client.model.describe_compute_fleet_status_response_content import DescribeComputeFleetStatusResponseContent
from pcluster.api.client.model.limit_exceeded_exception_response_content import LimitExceededExceptionResponseContent
from pcluster.api.client.model.internal_service_exception_response_content import InternalServiceExceptionResponseContent
from pcluster.api.client.model.unauthorized_client_error_response_content import UnauthorizedClientErrorResponseContent
from pprint import pprint
# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = pcluster.api.client.Configuration(
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
with pcluster.api.client.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = cluster_compute_fleet_api.ClusterComputeFleetApi(api_client)
    cluster_name = "AqWzy" # str | Name of the cluster
    region = "region_example" # str | AWS Region. Defaults to the region the API is deployed to. (optional)

    # example passing only required values which don't have defaults set
    try:
        api_response = api_instance.describe_compute_fleet_status(cluster_name)
        pprint(api_response)
    except pcluster.api.client.ApiException as e:
        print("Exception when calling ClusterComputeFleetApi->describe_compute_fleet_status: %s\n" % e)

    # example passing only required values which don't have defaults set
    # and optional values
    try:
        api_response = api_instance.describe_compute_fleet_status(cluster_name, region=region)
        pprint(api_response)
    except pcluster.api.client.ApiException as e:
        print("Exception when calling ClusterComputeFleetApi->describe_compute_fleet_status: %s\n" % e)
```


### Parameters

Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **cluster_name** | **str**| Name of the cluster |
 **region** | **str**| AWS Region. Defaults to the region the API is deployed to. | [optional]

### Return type

[**DescribeComputeFleetStatusResponseContent**](DescribeComputeFleetStatusResponseContent.md)

### Authorization

[aws.auth.sigv4](../README.md#aws.auth.sigv4)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | DescribeComputeFleetStatus 200 response |  -  |
**400** | BadRequestException 400 response |  -  |
**401** | UnauthorizedClientError 401 response |  -  |
**404** | NotFoundException 404 response |  -  |
**429** | LimitExceededException 429 response |  -  |
**500** | InternalServiceException 500 response |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **update_compute_fleet_status**
> update_compute_fleet_status(cluster_name, update_compute_fleet_status_request_content)



Update the status of the cluster compute fleet.

### Example

* Api Key Authentication (aws.auth.sigv4):
```python
import time
import pcluster.api.client
from pcluster.api.client.api import cluster_compute_fleet_api
from pcluster.api.client.model.bad_request_exception_response_content import BadRequestExceptionResponseContent
from pcluster.api.client.model.not_found_exception_response_content import NotFoundExceptionResponseContent
from pcluster.api.client.model.limit_exceeded_exception_response_content import LimitExceededExceptionResponseContent
from pcluster.api.client.model.internal_service_exception_response_content import InternalServiceExceptionResponseContent
from pcluster.api.client.model.update_compute_fleet_status_request_content import UpdateComputeFleetStatusRequestContent
from pcluster.api.client.model.unauthorized_client_error_response_content import UnauthorizedClientErrorResponseContent
from pprint import pprint
# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = pcluster.api.client.Configuration(
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
with pcluster.api.client.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = cluster_compute_fleet_api.ClusterComputeFleetApi(api_client)
    cluster_name = "AqWzy" # str | Name of the cluster
    update_compute_fleet_status_request_content = UpdateComputeFleetStatusRequestContent(
        status=RequestedComputeFleetStatus("START_REQUESTED"),
    ) # UpdateComputeFleetStatusRequestContent | 
    region = "region_example" # str | AWS Region. Defaults to the region the API is deployed to. (optional)

    # example passing only required values which don't have defaults set
    try:
        api_instance.update_compute_fleet_status(cluster_name, update_compute_fleet_status_request_content)
    except pcluster.api.client.ApiException as e:
        print("Exception when calling ClusterComputeFleetApi->update_compute_fleet_status: %s\n" % e)

    # example passing only required values which don't have defaults set
    # and optional values
    try:
        api_instance.update_compute_fleet_status(cluster_name, update_compute_fleet_status_request_content, region=region)
    except pcluster.api.client.ApiException as e:
        print("Exception when calling ClusterComputeFleetApi->update_compute_fleet_status: %s\n" % e)
```


### Parameters

Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **cluster_name** | **str**| Name of the cluster |
 **update_compute_fleet_status_request_content** | [**UpdateComputeFleetStatusRequestContent**](UpdateComputeFleetStatusRequestContent.md)|  |
 **region** | **str**| AWS Region. Defaults to the region the API is deployed to. | [optional]

### Return type

void (empty response body)

### Authorization

[aws.auth.sigv4](../README.md#aws.auth.sigv4)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
**204** | UpdateComputeFleetStatus 204 response |  -  |
**400** | BadRequestException 400 response |  -  |
**401** | UnauthorizedClientError 401 response |  -  |
**404** | NotFoundException 404 response |  -  |
**429** | LimitExceededException 429 response |  -  |
**500** | InternalServiceException 500 response |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

