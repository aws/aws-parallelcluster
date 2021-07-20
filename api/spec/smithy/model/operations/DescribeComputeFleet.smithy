namespace parallelcluster

@readonly
@http(method: "GET", uri: "/v3/clusters/{clusterName}/computefleet", code: 200)
@tags(["Cluster ComputeFleet"])
@documentation("Describe the status of the compute fleet.")
operation DescribeComputeFleet {
    input: DescribeComputeFleetRequest,
    output: DescribeComputeFleetResponse,
    errors: [
        InternalServiceException,
        BadRequestException,
        NotFoundException,
        UnauthorizedClientError,
        LimitExceededException,
    ]
}

structure DescribeComputeFleetRequest {
    @httpLabel
    @required
    clusterName: ClusterName,
    @httpQuery("region")
    region: Region,
}

structure DescribeComputeFleetResponse {
    @required
    status: ComputeFleetStatus,
    @documentation("Timestamp representing the last status update time.")
    @timestampFormat("date-time")
    lastStatusUpdatedTime: Timestamp,
}
