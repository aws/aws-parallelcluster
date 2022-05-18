# ImageInfoSummary


## Properties
Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**image_id** | **str** | Id of the image. | 
**region** | **str** | AWS region where the image is built. | 
**version** | **str** | ParallelCluster version used to build the image. | 
**image_build_status** | [**ImageBuildStatus**](ImageBuildStatus.md) |  | 
**ec2_ami_info** | [**Ec2AmiInfoSummary**](Ec2AmiInfoSummary.md) |  | [optional] 
**cloudformation_stack_arn** | **str** | ARN of the main CloudFormation stack. | [optional] 
**cloudformation_stack_status** | [**CloudFormationStackStatus**](CloudFormationStackStatus.md) |  | [optional] 

[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


