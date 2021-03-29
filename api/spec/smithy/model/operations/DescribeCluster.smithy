namespace parallelcluster

@readonly
@http(method: "GET", uri: "/v3/clusters/{clusterName}", code: 200)
@tags(["Cluster Operations"])
@documentation("Get detailed information about an existing cluster.")
operation DescribeCluster {
    input: DescribeClusterRequest,
    output: DescribeClusterResponse,
    errors: [
        InternalServiceException,
        BadRequestException,
        NotFoundException,
        UnauthorizedClientError,
        LimitExceededException,
    ]
}

structure DescribeClusterRequest {
    @httpLabel
    @required
    clusterName: ClusterName,
    @httpQuery("region")
    region: Region,
}

structure DescribeClusterResponse {
    @required
    @documentation("Name of the cluster")
    clusterName: ClusterName,
    @required
    @documentation("AWS region where the cluster is created")
    region: Region,
    @required
    @documentation("ParallelCluster version used to create the cluster")
    version: Version,
    @required
    @documentation("Status of the cluster. This corresponds to the CloudFormation stack status.")
    cloudFormationStatus: CloudFormationStatus,
    @required
    @documentation("Status of the cluster infrastructure")
    clusterStatus: ClusterStatus,
    @required
    @documentation("ARN of the main CloudFormation stack")
    cloudformationStackArn: String,
    @required
    @documentation("Timestamp representing the cluster creation time")
    @timestampFormat("date-time")
    creationTime: Timestamp,
    @required
    @documentation("Timestamp representing the last cluster update time")
    @timestampFormat("date-time")
    lastUpdatedTime: Timestamp,
    @required
    clusterConfiguration: ClusterConfigurationStructure,
    @required
    computeFleetStatus: ComputeFleetStatus,
    @required
    @documentation("Tags associated with the cluster")
    tags: Tags,
    headnode: EC2Instance,
    @documentation("Describe the reason of the failure when the stack is in CREATE_FAILED, UPDATE_FAILED or DELETE_FAILED status")
    failureReason: String
}
