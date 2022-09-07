# StackEvent


## Properties
Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**stack_id** | **str** | The unique ID name of the instance of the stack. | 
**event_id** | **str** | The unique ID of this event. | 
**stack_name** | **str** | The name associated with a stack. | 
**logical_resource_id** | **str** | The logical name of the resource specified in the template. | 
**physical_resource_id** | **str** | The name or unique identifier associated with the physical instance of the resource. | 
**resource_type** | **str** | Type of resource. | 
**timestamp** | **datetime** | Time the status was updated. | 
**resource_status** | [**CloudFormationResourceStatus**](CloudFormationResourceStatus.md) |  | 
**resource_status_reason** | **str** | Success/failure message associated with the resource. | [optional] 
**resource_properties** | **str** | BLOB of the properties used to create the resource. | [optional] 
**client_request_token** | **str** | The token passed to the operation that generated this event. | [optional] 
**any string name** | **bool, date, datetime, dict, float, int, list, str, none_type** | any string name can be used but the value must be the correct type | [optional]

[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


