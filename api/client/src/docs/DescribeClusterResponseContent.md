# DescribeClusterResponseContent


## Properties
Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**cluster_name** | **str** | Name of the cluster. | 
**region** | **str** | AWS region where the cluster is created. | 
**version** | **str** | ParallelCluster version used to create the cluster. | 
**cloud_formation_stack_status** | [**CloudFormationStackStatus**](CloudFormationStackStatus.md) |  | 
**cluster_status** | [**ClusterStatus**](ClusterStatus.md) |  | 
**cloudformation_stack_arn** | **str** | ARN of the main CloudFormation stack. | 
**creation_time** | **datetime** | Timestamp representing the cluster creation time. | 
**last_updated_time** | **datetime** | Timestamp representing the last cluster update time. | 
**cluster_configuration** | [**ClusterConfigurationStructure**](ClusterConfigurationStructure.md) |  | 
**compute_fleet_status** | [**ComputeFleetStatus**](ComputeFleetStatus.md) |  | 
**tags** | [**[Tag]**](Tag.md) | Tags associated with the cluster. | 
**head_node** | [**EC2Instance**](EC2Instance.md) |  | [optional] 
**failure_reason** | **str** | Reason of the failure when the stack is in CREATE_FAILED, UPDATE_FAILED or DELETE_FAILED status. | [optional] 

[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


