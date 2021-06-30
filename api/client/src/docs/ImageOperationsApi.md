# pcluster_client.ImageOperationsApi

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**build_image**](ImageOperationsApi.md#build_image) | **POST** /v3/images/custom | 
[**delete_image**](ImageOperationsApi.md#delete_image) | **DELETE** /v3/images/custom/{imageId} | 
[**describe_image**](ImageOperationsApi.md#describe_image) | **GET** /v3/images/custom/{imageId} | 
[**describe_official_images**](ImageOperationsApi.md#describe_official_images) | **GET** /v3/images/official | 
[**list_images**](ImageOperationsApi.md#list_images) | **GET** /v3/images/custom | 


# **build_image**
> BuildImageResponseContent build_image(build_image_request_content)



Create a custom ParallelCluster image in a given region.

### Example

* Api Key Authentication (aws.auth.sigv4):
```python
import time
import pcluster_client
from pcluster_client.api import image_operations_api
from pcluster_client.model.build_image_request_content import BuildImageRequestContent
from pcluster_client.model.build_image_bad_request_exception_response_content import BuildImageBadRequestExceptionResponseContent
from pcluster_client.model.unauthorized_client_error_response_content import UnauthorizedClientErrorResponseContent
from pcluster_client.model.limit_exceeded_exception_response_content import LimitExceededExceptionResponseContent
from pcluster_client.model.conflict_exception_response_content import ConflictExceptionResponseContent
from pcluster_client.model.build_image_response_content import BuildImageResponseContent
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
    api_instance = image_operations_api.ImageOperationsApi(api_client)
    build_image_request_content = BuildImageRequestContent(
        image_configuration='YQ==',
        id="AqWzy",
        region="region_example",
    ) # BuildImageRequestContent | 
    suppress_validators = [
        "type:u2LC",
    ] # [str] | Identifies one or more config validators to suppress. Format: (ALL|type:[A-Za-z0-9]+) (optional)
    validation_failure_level = ValidationLevel("INFO") # ValidationLevel | Min validation level that will cause the creation to fail. Defaults to 'error'. (optional)
    dryrun = True # bool, none_type | Only perform request validation without creating any resource. It can be used to validate the image configuration. Response code: 200 (optional)
    rollback_on_failure = True # bool, none_type | When set it automatically initiates an image stack rollback on failures. Defaults to true. (optional)

    # example passing only required values which don't have defaults set
    try:
        api_response = api_instance.build_image(build_image_request_content)
        pprint(api_response)
    except pcluster_client.ApiException as e:
        print("Exception when calling ImageOperationsApi->build_image: %s\n" % e)

    # example passing only required values which don't have defaults set
    # and optional values
    try:
        api_response = api_instance.build_image(build_image_request_content, suppress_validators=suppress_validators, validation_failure_level=validation_failure_level, dryrun=dryrun, rollback_on_failure=rollback_on_failure)
        pprint(api_response)
    except pcluster_client.ApiException as e:
        print("Exception when calling ImageOperationsApi->build_image: %s\n" % e)
```


### Parameters

Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **build_image_request_content** | [**BuildImageRequestContent**](BuildImageRequestContent.md)|  |
 **suppress_validators** | **[str]**| Identifies one or more config validators to suppress. Format: (ALL|type:[A-Za-z0-9]+) | [optional]
 **validation_failure_level** | **ValidationLevel**| Min validation level that will cause the creation to fail. Defaults to &#39;error&#39;. | [optional]
 **dryrun** | **bool, none_type**| Only perform request validation without creating any resource. It can be used to validate the image configuration. Response code: 200 | [optional]
 **rollback_on_failure** | **bool, none_type**| When set it automatically initiates an image stack rollback on failures. Defaults to true. | [optional]

### Return type

[**BuildImageResponseContent**](BuildImageResponseContent.md)

### Authorization

[aws.auth.sigv4](../README.md#aws.auth.sigv4)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
**202** | BuildImage 202 response |  -  |
**400** | BuildImageBadRequestException 400 response |  -  |
**401** | UnauthorizedClientError 401 response |  -  |
**409** | ConflictException 409 response |  -  |
**412** | DryrunOperationException 412 response |  -  |
**429** | LimitExceededException 429 response |  -  |
**500** | InternalServiceException 500 response |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **delete_image**
> DeleteImageResponseContent delete_image(image_id)



Initiate the deletion of the custom ParallelCluster image.

### Example

* Api Key Authentication (aws.auth.sigv4):
```python
import time
import pcluster_client
from pcluster_client.api import image_operations_api
from pcluster_client.model.bad_request_exception_response_content import BadRequestExceptionResponseContent
from pcluster_client.model.unauthorized_client_error_response_content import UnauthorizedClientErrorResponseContent
from pcluster_client.model.limit_exceeded_exception_response_content import LimitExceededExceptionResponseContent
from pcluster_client.model.delete_image_response_content import DeleteImageResponseContent
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
    api_instance = image_operations_api.ImageOperationsApi(api_client)
    image_id = "AqWzy" # str | Id of the image
    region = "region_example" # str | AWS Region. Defaults to the region the API is deployed to. (optional)
    force = True # bool, none_type | Force deletion in case there are instances using the AMI or in case the AMI is shared (optional)

    # example passing only required values which don't have defaults set
    try:
        api_response = api_instance.delete_image(image_id)
        pprint(api_response)
    except pcluster_client.ApiException as e:
        print("Exception when calling ImageOperationsApi->delete_image: %s\n" % e)

    # example passing only required values which don't have defaults set
    # and optional values
    try:
        api_response = api_instance.delete_image(image_id, region=region, force=force)
        pprint(api_response)
    except pcluster_client.ApiException as e:
        print("Exception when calling ImageOperationsApi->delete_image: %s\n" % e)
```


### Parameters

Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **image_id** | **str**| Id of the image |
 **region** | **str**| AWS Region. Defaults to the region the API is deployed to. | [optional]
 **force** | **bool, none_type**| Force deletion in case there are instances using the AMI or in case the AMI is shared | [optional]

### Return type

[**DeleteImageResponseContent**](DeleteImageResponseContent.md)

### Authorization

[aws.auth.sigv4](../README.md#aws.auth.sigv4)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
**202** | DeleteImage 202 response |  -  |
**400** | BadRequestException 400 response |  -  |
**401** | UnauthorizedClientError 401 response |  -  |
**404** | NotFoundException 404 response |  -  |
**429** | LimitExceededException 429 response |  -  |
**500** | InternalServiceException 500 response |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **describe_image**
> DescribeImageResponseContent describe_image(image_id)



Get detailed information about an existing image.

### Example

* Api Key Authentication (aws.auth.sigv4):
```python
import time
import pcluster_client
from pcluster_client.api import image_operations_api
from pcluster_client.model.bad_request_exception_response_content import BadRequestExceptionResponseContent
from pcluster_client.model.describe_image_response_content import DescribeImageResponseContent
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
    api_instance = image_operations_api.ImageOperationsApi(api_client)
    image_id = "AqWzy" # str | Id of the image
    region = "region_example" # str | AWS Region. Defaults to the region the API is deployed to. (optional)

    # example passing only required values which don't have defaults set
    try:
        api_response = api_instance.describe_image(image_id)
        pprint(api_response)
    except pcluster_client.ApiException as e:
        print("Exception when calling ImageOperationsApi->describe_image: %s\n" % e)

    # example passing only required values which don't have defaults set
    # and optional values
    try:
        api_response = api_instance.describe_image(image_id, region=region)
        pprint(api_response)
    except pcluster_client.ApiException as e:
        print("Exception when calling ImageOperationsApi->describe_image: %s\n" % e)
```


### Parameters

Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **image_id** | **str**| Id of the image |
 **region** | **str**| AWS Region. Defaults to the region the API is deployed to. | [optional]

### Return type

[**DescribeImageResponseContent**](DescribeImageResponseContent.md)

### Authorization

[aws.auth.sigv4](../README.md#aws.auth.sigv4)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | DescribeImage 200 response |  -  |
**400** | BadRequestException 400 response |  -  |
**401** | UnauthorizedClientError 401 response |  -  |
**404** | NotFoundException 404 response |  -  |
**429** | LimitExceededException 429 response |  -  |
**500** | InternalServiceException 500 response |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **describe_official_images**
> DescribeOfficialImagesResponseContent describe_official_images()



Describe ParallelCluster AMIs.

### Example

* Api Key Authentication (aws.auth.sigv4):
```python
import time
import pcluster_client
from pcluster_client.api import image_operations_api
from pcluster_client.model.bad_request_exception_response_content import BadRequestExceptionResponseContent
from pcluster_client.model.unauthorized_client_error_response_content import UnauthorizedClientErrorResponseContent
from pcluster_client.model.limit_exceeded_exception_response_content import LimitExceededExceptionResponseContent
from pcluster_client.model.describe_official_images_response_content import DescribeOfficialImagesResponseContent
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
    api_instance = image_operations_api.ImageOperationsApi(api_client)
    region = "region_example" # str | AWS Region. Defaults to the region the API is deployed to. (optional)
    os = "os_example" # str | Filter by OS distribution (optional)
    architecture = "architecture_example" # str | Filter by architecture (optional)

    # example passing only required values which don't have defaults set
    # and optional values
    try:
        api_response = api_instance.describe_official_images(region=region, os=os, architecture=architecture)
        pprint(api_response)
    except pcluster_client.ApiException as e:
        print("Exception when calling ImageOperationsApi->describe_official_images: %s\n" % e)
```


### Parameters

Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **region** | **str**| AWS Region. Defaults to the region the API is deployed to. | [optional]
 **os** | **str**| Filter by OS distribution | [optional]
 **architecture** | **str**| Filter by architecture | [optional]

### Return type

[**DescribeOfficialImagesResponseContent**](DescribeOfficialImagesResponseContent.md)

### Authorization

[aws.auth.sigv4](../README.md#aws.auth.sigv4)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | DescribeOfficialImages 200 response |  -  |
**400** | BadRequestException 400 response |  -  |
**401** | UnauthorizedClientError 401 response |  -  |
**429** | LimitExceededException 429 response |  -  |
**500** | InternalServiceException 500 response |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **list_images**
> ListImagesResponseContent list_images(image_status)



Retrieve the list of existing custom images managed by the API. Deleted images are not showed by default

### Example

* Api Key Authentication (aws.auth.sigv4):
```python
import time
import pcluster_client
from pcluster_client.api import image_operations_api
from pcluster_client.model.bad_request_exception_response_content import BadRequestExceptionResponseContent
from pcluster_client.model.unauthorized_client_error_response_content import UnauthorizedClientErrorResponseContent
from pcluster_client.model.limit_exceeded_exception_response_content import LimitExceededExceptionResponseContent
from pcluster_client.model.image_status_filtering_option import ImageStatusFilteringOption
from pcluster_client.model.list_images_response_content import ListImagesResponseContent
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
    api_instance = image_operations_api.ImageOperationsApi(api_client)
    image_status = ImageStatusFilteringOption("AVAILABLE") # ImageStatusFilteringOption | Filter by image status.
    region = "region_example" # str | List Images built into a given AWS Region. Defaults to the AWS region the API is deployed to. (optional)
    next_token = "nextToken_example" # str | Token to use for paginated requests. (optional)

    # example passing only required values which don't have defaults set
    try:
        api_response = api_instance.list_images(image_status)
        pprint(api_response)
    except pcluster_client.ApiException as e:
        print("Exception when calling ImageOperationsApi->list_images: %s\n" % e)

    # example passing only required values which don't have defaults set
    # and optional values
    try:
        api_response = api_instance.list_images(image_status, region=region, next_token=next_token)
        pprint(api_response)
    except pcluster_client.ApiException as e:
        print("Exception when calling ImageOperationsApi->list_images: %s\n" % e)
```


### Parameters

Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **image_status** | **ImageStatusFilteringOption**| Filter by image status. |
 **region** | **str**| List Images built into a given AWS Region. Defaults to the AWS region the API is deployed to. | [optional]
 **next_token** | **str**| Token to use for paginated requests. | [optional]

### Return type

[**ListImagesResponseContent**](ListImagesResponseContent.md)

### Authorization

[aws.auth.sigv4](../README.md#aws.auth.sigv4)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | ListImages 200 response |  -  |
**400** | BadRequestException 400 response |  -  |
**401** | UnauthorizedClientError 401 response |  -  |
**429** | LimitExceededException 429 response |  -  |
**500** | InternalServiceException 500 response |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

