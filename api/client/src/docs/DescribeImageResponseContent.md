# DescribeImageResponseContent


## Properties
Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**image_configuration** | [**ImageConfigurationStructure**](ImageConfigurationStructure.md) |  | 
**image_id** | **str** | Id of the Image to retrieve detailed information for. | 
**image_build_status** | [**ImageBuildStatus**](ImageBuildStatus.md) |  | 
**region** | **str** | AWS region where the image is created. | 
**version** | **str** | ParallelCluster version used to build the image. | 
**cloudformation_stack_status_reason** | **str** | Reason for the CloudFormation stack status. | [optional] 
**imagebuilder_image_status_reason** | **str** | Reason for the ImageBuilder Image status. | [optional] 
**imagebuilder_image_status** | [**ImageBuilderImageStatus**](ImageBuilderImageStatus.md) |  | [optional] 
**creation_time** | **datetime** | Timestamp representing the image creation time. | [optional] 
**cloudformation_stack_status** | [**CloudFormationStackStatus**](CloudFormationStackStatus.md) |  | [optional] 
**cloudformation_stack_arn** | **str** | ARN of the main CloudFormation stack. | [optional] 
**ec2_ami_info** | [**Ec2AmiInfo**](Ec2AmiInfo.md) |  | [optional] 

[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


