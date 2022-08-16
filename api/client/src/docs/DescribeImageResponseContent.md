# DescribeImageResponseContent


## Properties
Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**image_id** | **str** | Id of the Image to retrieve detailed information for. | 
**region** | **str** | AWS region where the image is created. | 
**version** | **str** | ParallelCluster version used to build the image. | 
**image_build_status** | [**ImageBuildStatus**](ImageBuildStatus.md) |  | 
**image_configuration** | [**ImageConfigurationStructure**](ImageConfigurationStructure.md) |  | 
**image_build_logs_arn** | **str** | ARN of the logs for the image build process. | [optional] 
**cloudformation_stack_status** | [**CloudFormationStackStatus**](CloudFormationStackStatus.md) |  | [optional] 
**cloudformation_stack_status_reason** | **str** | Reason for the CloudFormation stack status. | [optional] 
**cloudformation_stack_arn** | **str** | ARN of the main CloudFormation stack. | [optional] 
**creation_time** | **datetime** | Timestamp representing the image creation time. | [optional] 
**cloudformation_stack_creation_time** | **datetime** | Timestamp representing the CloudFormation stack creation time. | [optional] 
**cloudformation_stack_tags** | [**[Tag]**](Tag.md) | Tags for the CloudFormation stack. | [optional] 
**imagebuilder_image_status** | [**ImageBuilderImageStatus**](ImageBuilderImageStatus.md) |  | [optional] 
**imagebuilder_image_status_reason** | **str** | Reason for the ImageBuilder Image status. | [optional] 
**ec2_ami_info** | [**Ec2AmiInfo**](Ec2AmiInfo.md) |  | [optional] 
**any string name** | **bool, date, datetime, dict, float, int, list, str, none_type** | any string name can be used but the value must be the correct type | [optional]

[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


