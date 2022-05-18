# DryrunOperationExceptionResponseContent

Communicates that the operation would have succeeded without the dryrun flag.

## Properties
Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**message** | **str** |  | [optional] 
**change_set** | [**[Change]**](Change.md) | List of configuration changes requested by the operation. | [optional] 
**validation_messages** | [**[ConfigValidationMessage]**](ConfigValidationMessage.md) | List of messages collected during cluster config validation whose level is lower than the &#39;validationFailureLevel&#39; set by the user. | [optional] 

[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


