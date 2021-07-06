namespace parallelcluster

@readonly
@http(method: "GET", uri: "/v3/clusters/{clusterName}/computefleet/status", code: 200)
@tags(["Cluster ComputeFleet"])
@documentation("Describe the status of the compute fleet")
operation DescribeComputeFleetStatus {
    input: DescribeComputeFleetStatusRequest,
    output: DescribeComputeFleetStatusResponse,
    errors: [
        InternalServiceException,
        BadRequestException,
        NotFoundException,
        UnauthorizedClientError,
        LimitExceededException,
    ]
}

structure DescribeComputeFleetStatusRequest {
    @httpLabel
    @required
    clusterName: ClusterName,
    @httpQuery("region")
    region: Region,
}

structure DescribeComputeFleetStatusResponse {
    @required
    status: ComputeFleetStatus,
    @documentation("Timestamp representing the last status update time")
    @timestampFormat("date-time")
    lastUpdatedTime: Timestamp,
}
