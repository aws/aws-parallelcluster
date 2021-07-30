# StackEvent


## Properties
Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**event_id** | **str** | The unique ID of this event. | 
**physical_resource_id** | **str** | The name or unique identifier associated with the physical instance of the resource. | 
**resource_status** | [**CloudFormationResourceStatus**](CloudFormationResourceStatus.md) |  | 
**resource_status_reason** | **str** | Success/failure message associated with the resource. | 
**client_request_token** | **str** | The token passed to the operation that generated this event. | 
**resource_properties** | **str** | BLOB of the properties used to create the resource. | 
**stack_id** | **str** | The unique ID name of the instance of the stack. | 
**stack_name** | **str** | The name associated with a stack. | 
**logical_resource_id** | **str** | The logical name of the resource specified in the template. | 
**resource_type** | **str** | Type of resource. | 
**timestamp** | **datetime** | Time the status was updated. | 

[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


