# DescribeImageResponseContent


## Properties
Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**image_id** | **str** | Id of the Image to retrieve detailed information for. | 
**version** | **str** | ParallelCluster version used to build the image. | 
**image_configuration** | [**ImageConfigurationStructure**](ImageConfigurationStructure.md) |  | 
**image_build_status** | [**ImageBuildStatus**](ImageBuildStatus.md) |  | 
**region** | **str** | AWS region where the image is created. | 
**cloudformation_stack_status_reason** | **str** | Reason for the CloudFormation stack status. | [optional] 
**imagebuilder_image_status_reason** | **str** | Reason for the ImageBuilder Image status. | [optional] 
**cloudformation_stack_tags** | [**[Tag]**](Tag.md) | Tags for the CloudFormation stack. | [optional] 
**imagebuilder_image_status** | [**ImageBuilderImageStatus**](ImageBuilderImageStatus.md) |  | [optional] 
**creation_time** | **datetime** | Timestamp representing the image creation time. | [optional] 
**cloudformation_stack_status** | [**CloudFormationStackStatus**](CloudFormationStackStatus.md) |  | [optional] 
**image_build_logs_arn** | **str** | ARN of the logs for the image build process. | [optional] 
**cloudformation_stack_arn** | **str** | ARN of the main CloudFormation stack. | [optional] 
**cloudformation_stack_creation_time** | **datetime** | Timestamp representing the CloudFormation stack creation time. | [optional] 
**ec2_ami_info** | [**Ec2AmiInfo**](Ec2AmiInfo.md) |  | [optional] 

[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


