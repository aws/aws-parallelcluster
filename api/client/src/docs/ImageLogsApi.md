# pcluster_client.ImageLogsApi

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**get_image_log_events**](ImageLogsApi.md#get_image_log_events) | **GET** /v3/images/custom/{imageId}/logstreams/{logStreamName} | 
[**get_image_stack_events**](ImageLogsApi.md#get_image_stack_events) | **GET** /v3/images/custom/{imageId}/stackevents | 
[**list_image_log_streams**](ImageLogsApi.md#list_image_log_streams) | **GET** /v3/images/custom/{imageId}/logstreams | 


# **get_image_log_events**
> GetImageLogEventsResponseContent get_image_log_events(image_id, log_stream_name)



Retrieve the events associated with an image build.

### Example

* Api Key Authentication (aws.auth.sigv4):

```python
import time
import pcluster_client
from pcluster_client.api import image_logs_api
from pcluster_client.model.bad_request_exception_response_content import BadRequestExceptionResponseContent
from pcluster_client.model.unauthorized_client_error_response_content import UnauthorizedClientErrorResponseContent
from pcluster_client.model.limit_exceeded_exception_response_content import LimitExceededExceptionResponseContent
from pcluster_client.model.internal_service_exception_response_content import InternalServiceExceptionResponseContent
from pcluster_client.model.not_found_exception_response_content import NotFoundExceptionResponseContent
from pcluster_client.model.get_image_log_events_response_content import GetImageLogEventsResponseContent
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
    api_instance = image_logs_api.ImageLogsApi(api_client)
    image_id = "AqWzyB" # str | Id of the image.
    log_stream_name = "logStreamName_example" # str | Name of the log stream.
    region = "region_example" # str | AWS Region that the operation corresponds to. (optional)
    next_token = "nextToken_example" # str | Token to use for paginated requests. (optional)
    start_from_head = True # bool | If the value is true, the earliest log events are returned first. If the value is false, the latest log events are returned first. (Defaults to 'false'.) (optional)
    limit = 3.14 # float | The maximum number of log events returned. If you don't specify a value, the maximum is as many log events as can fit in a response size of 1 MB, up to 10,000 log events. (optional)
    start_time = dateutil_parser('1970-01-01T00:00:00.00Z') # datetime | The start of the time range, expressed in ISO 8601 format (e.g. '2021-01-01T20:00:00Z'). Events with a timestamp equal to this time or later than this time are included. (optional)
    end_time = dateutil_parser('1970-01-01T00:00:00.00Z') # datetime | The end of the time range, expressed in ISO 8601 format (e.g. '2021-01-01T20:00:00Z'). Events with a timestamp equal to or later than this time are not included. (optional)

    # example passing only required values which don't have defaults set
    try:
        api_response = api_instance.get_image_log_events(image_id, log_stream_name)
        pprint(api_response)
    except pcluster_client.ApiException as e:
        print("Exception when calling ImageLogsApi->get_image_log_events: %s\n" % e)

    # example passing only required values which don't have defaults set
    # and optional values
    try:
        api_response = api_instance.get_image_log_events(image_id, log_stream_name, region=region, next_token=next_token, start_from_head=start_from_head, limit=limit, start_time=start_time, end_time=end_time)
        pprint(api_response)
    except pcluster_client.ApiException as e:
        print("Exception when calling ImageLogsApi->get_image_log_events: %s\n" % e)
```


### Parameters

Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **image_id** | **str**| Id of the image. |
 **log_stream_name** | **str**| Name of the log stream. |
 **region** | **str**| AWS Region that the operation corresponds to. | [optional]
 **next_token** | **str**| Token to use for paginated requests. | [optional]
 **start_from_head** | **bool**| If the value is true, the earliest log events are returned first. If the value is false, the latest log events are returned first. (Defaults to &#39;false&#39;.) | [optional]
 **limit** | **float**| The maximum number of log events returned. If you don&#39;t specify a value, the maximum is as many log events as can fit in a response size of 1 MB, up to 10,000 log events. | [optional]
 **start_time** | **datetime**| The start of the time range, expressed in ISO 8601 format (e.g. &#39;2021-01-01T20:00:00Z&#39;). Events with a timestamp equal to this time or later than this time are included. | [optional]
 **end_time** | **datetime**| The end of the time range, expressed in ISO 8601 format (e.g. &#39;2021-01-01T20:00:00Z&#39;). Events with a timestamp equal to or later than this time are not included. | [optional]

### Return type

[**GetImageLogEventsResponseContent**](GetImageLogEventsResponseContent.md)

### Authorization

[aws.auth.sigv4](../README.md#aws.auth.sigv4)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json


### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | GetImageLogEvents 200 response |  -  |
**400** | BadRequestException 400 response |  -  |
**401** | UnauthorizedClientError 401 response |  -  |
**404** | NotFoundException 404 response |  -  |
**429** | LimitExceededException 429 response |  -  |
**500** | InternalServiceException 500 response |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **get_image_stack_events**
> GetImageStackEventsResponseContent get_image_stack_events(image_id)



Retrieve the events associated with the stack for a given image build.

### Example

* Api Key Authentication (aws.auth.sigv4):

```python
import time
import pcluster_client
from pcluster_client.api import image_logs_api
from pcluster_client.model.bad_request_exception_response_content import BadRequestExceptionResponseContent
from pcluster_client.model.unauthorized_client_error_response_content import UnauthorizedClientErrorResponseContent
from pcluster_client.model.limit_exceeded_exception_response_content import LimitExceededExceptionResponseContent
from pcluster_client.model.get_image_stack_events_response_content import GetImageStackEventsResponseContent
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
    api_instance = image_logs_api.ImageLogsApi(api_client)
    image_id = "AqWzyB" # str | Id of the image.
    region = "region_example" # str | AWS Region that the operation corresponds to. (optional)
    next_token = "nextToken_example" # str | Token to use for paginated requests. (optional)

    # example passing only required values which don't have defaults set
    try:
        api_response = api_instance.get_image_stack_events(image_id)
        pprint(api_response)
    except pcluster_client.ApiException as e:
        print("Exception when calling ImageLogsApi->get_image_stack_events: %s\n" % e)

    # example passing only required values which don't have defaults set
    # and optional values
    try:
        api_response = api_instance.get_image_stack_events(image_id, region=region, next_token=next_token)
        pprint(api_response)
    except pcluster_client.ApiException as e:
        print("Exception when calling ImageLogsApi->get_image_stack_events: %s\n" % e)
```


### Parameters

Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **image_id** | **str**| Id of the image. |
 **region** | **str**| AWS Region that the operation corresponds to. | [optional]
 **next_token** | **str**| Token to use for paginated requests. | [optional]

### Return type

[**GetImageStackEventsResponseContent**](GetImageStackEventsResponseContent.md)

### Authorization

[aws.auth.sigv4](../README.md#aws.auth.sigv4)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json


### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | GetImageStackEvents 200 response |  -  |
**400** | BadRequestException 400 response |  -  |
**401** | UnauthorizedClientError 401 response |  -  |
**404** | NotFoundException 404 response |  -  |
**429** | LimitExceededException 429 response |  -  |
**500** | InternalServiceException 500 response |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **list_image_log_streams**
> ListImageLogStreamsResponseContent list_image_log_streams(image_id)



Retrieve the list of log streams associated with an image.

### Example

* Api Key Authentication (aws.auth.sigv4):

```python
import time
import pcluster_client
from pcluster_client.api import image_logs_api
from pcluster_client.model.bad_request_exception_response_content import BadRequestExceptionResponseContent
from pcluster_client.model.unauthorized_client_error_response_content import UnauthorizedClientErrorResponseContent
from pcluster_client.model.limit_exceeded_exception_response_content import LimitExceededExceptionResponseContent
from pcluster_client.model.list_image_log_streams_response_content import ListImageLogStreamsResponseContent
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
    api_instance = image_logs_api.ImageLogsApi(api_client)
    image_id = "AqWzyB" # str | Id of the image.
    region = "region_example" # str | Region that the given image belongs to. (optional)
    next_token = "nextToken_example" # str | Token to use for paginated requests. (optional)

    # example passing only required values which don't have defaults set
    try:
        api_response = api_instance.list_image_log_streams(image_id)
        pprint(api_response)
    except pcluster_client.ApiException as e:
        print("Exception when calling ImageLogsApi->list_image_log_streams: %s\n" % e)

    # example passing only required values which don't have defaults set
    # and optional values
    try:
        api_response = api_instance.list_image_log_streams(image_id, region=region, next_token=next_token)
        pprint(api_response)
    except pcluster_client.ApiException as e:
        print("Exception when calling ImageLogsApi->list_image_log_streams: %s\n" % e)
```


### Parameters

Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **image_id** | **str**| Id of the image. |
 **region** | **str**| Region that the given image belongs to. | [optional]
 **next_token** | **str**| Token to use for paginated requests. | [optional]

### Return type

[**ListImageLogStreamsResponseContent**](ListImageLogStreamsResponseContent.md)

### Authorization

[aws.auth.sigv4](../README.md#aws.auth.sigv4)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json


### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | ListImageLogStreams 200 response |  -  |
**400** | BadRequestException 400 response |  -  |
**401** | UnauthorizedClientError 401 response |  -  |
**404** | NotFoundException 404 response |  -  |
**429** | LimitExceededException 429 response |  -  |
**500** | InternalServiceException 500 response |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

