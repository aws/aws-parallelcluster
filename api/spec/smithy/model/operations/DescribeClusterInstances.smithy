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
        NotFoundException,
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
    nodeType: NodeType,
    @httpQuery("queueName")
    queueName: String,
}

structure DescribeClusterInstancesResponse {
    nextToken: PaginationToken,
    @required
    instances: InstanceSummaries,
}

list InstanceSummaries {
    member: EC2Instance
}
