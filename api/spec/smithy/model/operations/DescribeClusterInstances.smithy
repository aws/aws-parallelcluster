namespace parallelcluster

@http(method: "GET", uri: "/v3/clusters/{clusterName}/instances", code: 200)
@tags(["Cluster Instances"])
@paginated
@readonly
@documentation("Describe the instances belonging to a given cluster.")
operation DescribeClusterInstances {
    input: DescribeClusterInstancesRequest,
    output: DescribeClusterInstancesResponse,
    errors: [
        InternalServiceException,
        BadRequestException,
        UnauthorizedClientError,
        LimitExceededException,
    ]
}

structure DescribeClusterInstancesRequest {
    @httpLabel
    @required
    clusterName: ClusterName,
    @httpQuery("region")
    region: Region,
    @httpQuery("nextToken")
    nextToken: PaginationToken,
    @httpQuery("nodeType")
    @documentation("Filter the instances by node type.")
    nodeType: NodeType,
    @httpQuery("queueName")
    @documentation("Filter the instances by queue name.")
    queueName: String,
}

structure DescribeClusterInstancesResponse {
    nextToken: PaginationToken,
    @required
    instances: InstanceSummaries,
}

structure ClusterInstance {
    @required
    instanceId: String,
    @required
    instanceType: String,
    @required
    @timestampFormat("date-time")
    launchTime: Timestamp,
    @required
    privateIpAddress: String, // only primary?
    publicIpAddress: String,
    @required
    state: InstanceState,
    @required
    nodeType: NodeType,
    queueName: String,
    poolName: String
}

list InstanceSummaries {
    member: ClusterInstance
}
