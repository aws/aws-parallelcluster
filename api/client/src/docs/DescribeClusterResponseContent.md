# DescribeClusterResponseContent


## Properties
Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**creation_time** | **datetime** | Timestamp representing the cluster creation time. | 
**version** | **str** | ParallelCluster version used to create the cluster. | 
**cluster_configuration** | [**ClusterConfigurationStructure**](ClusterConfigurationStructure.md) |  | 
**tags** | [**[Tag]**](Tag.md) | Tags associated with the cluster. | 
**cloud_formation_stack_status** | [**CloudFormationStackStatus**](CloudFormationStackStatus.md) |  | 
**cluster_name** | **str** | Name of the cluster. | 
**compute_fleet_status** | [**ComputeFleetStatus**](ComputeFleetStatus.md) |  | 
**cloudformation_stack_arn** | **str** | ARN of the main CloudFormation stack. | 
**last_updated_time** | **datetime** | Timestamp representing the last cluster update time. | 
**region** | **str** | AWS region where the cluster is created. | 
**cluster_status** | [**ClusterStatus**](ClusterStatus.md) |  | 
**failure_reason** | **str** | Reason of the failure when the stack is in CREATE_FAILED, UPDATE_FAILED or DELETE_FAILED status. | [optional] 
**head_node** | [**EC2Instance**](EC2Instance.md) |  | [optional] 

[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


